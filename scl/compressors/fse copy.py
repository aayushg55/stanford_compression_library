"""FSE (Finite State Entropy) implementation

FSE is a variant of tANS (table ANS) used in zstandard compression.
It uses a normalization algorithm and spread function to build efficient
encoding/decoding tables.

## Key Differences from tANS:
- Uses normalization to scale frequencies to power-of-2 table size
- Uses spread function to distribute symbols across the table
- More efficient table construction algorithm

## References:
1. zstandard compression format: https://github.com/facebook/zstd
2. FSE algorithm: Yann Collet's blog posts on FSE
3. RFC 8478: Zstandard Compression and the 'application/zstd' Media Type
"""

from dataclasses import dataclass
from typing import Tuple, Any, List, Dict
from scl.core.data_encoder_decoder import DataDecoder, DataEncoder
from scl.utils.bitarray_utils import (
    BitArray,
    get_bit_width,
    uint_to_bitarray,
    bitarray_to_uint,
)
from scl.core.data_block import DataBlock
from scl.core.prob_dist import Frequencies, get_avg_neg_log_prob
from scl.utils.test_utils import get_random_data_block, try_lossless_compression
from scl.utils.misc_utils import is_power_of_two


@dataclass
class FSEParams:
    """Parameters for FSE encoder/decoder
    
    FSE uses a table-based approach where the table size is a power of 2.
    Frequencies are normalized to fit this table size.
    """
    
    freqs: Frequencies
    
    # Number of bits to encode data block size
    DATA_BLOCK_SIZE_BITS: int = 32
    
    # Table size is 2^TABLE_SIZE_LOG2
    # Common values: 6 (64 states), 7 (128 states), 8 (256 states)
    TABLE_SIZE_LOG2: int = 6
    
    # Number of bits to output per encoding step
    NUM_BITS_OUT: int = 1
    
    def __post_init__(self):
        """Compute derived parameters"""
        # Table size (must be power of 2)
        self.TABLE_SIZE = 1 << self.TABLE_SIZE_LOG2
        
        # Normalize frequencies to table size
        self.normalized_freqs = self._normalize_frequencies()
        
        # Verify normalization
        assert sum(self.normalized_freqs.values()) == self.TABLE_SIZE, \
            f"Normalized frequencies must sum to {self.TABLE_SIZE}"
        
        # State range: [TABLE_SIZE, 2*TABLE_SIZE - 1]
        self.L = self.TABLE_SIZE
        self.H = (self.TABLE_SIZE << self.NUM_BITS_OUT) - 1
        
        # Initial state
        self.INITIAL_STATE = self.L
        
        # Number of bits to represent state
        self.NUM_STATE_BITS = get_bit_width(self.H)
        
        # Compute symbol ranges for encoding
        self.symbol_ranges = self._compute_symbol_ranges()
    
    def _normalize_frequencies(self) -> Dict[Any, int]:
        """Normalize frequencies to sum to TABLE_SIZE
        
        Uses scaling algorithm to ensure frequencies sum exactly to TABLE_SIZE
        while preserving relative frequencies as much as possible.
        """
        total_freq = self.freqs.total_freq
        normalized = {}
        remaining = self.TABLE_SIZE
        
        # Sort symbols by frequency (descending) for better distribution
        sorted_symbols = sorted(
            self.freqs.alphabet,
            key=lambda s: self.freqs.frequency(s),
            reverse=True
        )
        
        for s in sorted_symbols[:-1]:  # All but last symbol
            freq = self.freqs.frequency(s)
            # Scale frequency proportionally
            normalized_freq = max(1, int(round(freq * self.TABLE_SIZE / total_freq)))
            # Ensure we don't exceed remaining
            normalized_freq = min(normalized_freq, remaining - (len(sorted_symbols) - len(normalized) - 1))
            normalized[s] = normalized_freq
            remaining -= normalized_freq
        
        # Last symbol gets remaining frequency
        last_symbol = sorted_symbols[-1]
        normalized[last_symbol] = remaining
        
        return normalized
    
    def _compute_symbol_ranges(self) -> Dict[Any, Tuple[int, int]]:
        """Compute the state range for each symbol
        
        Returns dict mapping symbol to (min_state, max_state)
        """
        ranges = {}
        cumulative = 0
        for s in self.freqs.alphabet:
            norm_freq = self.normalized_freqs[s]
            min_state = self.L * cumulative // self.TABLE_SIZE
            max_state = self.L * (cumulative + norm_freq) // self.TABLE_SIZE - 1
            ranges[s] = (min_state, max_state)
            cumulative += norm_freq
        return ranges


class FSEEncoder(DataEncoder):
    """FSE Encoder
    
    Uses lookup tables built using FSE normalization and spread algorithm.
    """
    
    def __init__(self, fse_params: FSEParams):
        """Initialize FSE encoder
        
        Args:
            fse_params (FSEParams): FSE parameters
        """
        self.params = fse_params
        
        # Build FSE encoding table
        self.encode_table = self._build_encode_table()
        
        # Build state shrinking lookup tables
        self.shrink_tables = self._build_shrink_tables()
    
    def _build_encode_table(self) -> Dict[Tuple[Any, int], int]:
        """Build FSE encoding table
        
        The table maps (symbol, state_shrunk) -> next_state
        Uses spread function to distribute symbols across states.
        """
        table = {}
        
        # Build spread table: maps table position -> symbol
        spread_table = self._build_spread_table()
        
        # Find positions for each symbol in spread table
        symbol_positions = {}
        for s in self.params.freqs.alphabet:
            symbol_positions[s] = [i for i, sym in enumerate(spread_table) if sym == s]
        
        # For each symbol and each possible shrunk state
        for s in self.params.freqs.alphabet:
            norm_freq = self.params.normalized_freqs[s]
            positions = symbol_positions[s]
            
            # Build encoding table for this symbol
            # For each possible shrunk state value
            for state_shrunk in range(self.params.L, self.params.H + 1):
                # Map state to table position
                table_pos = state_shrunk % self.params.TABLE_SIZE
                
                # Find which symbol is at this position
                current_symbol = spread_table[table_pos]
                
                # If this is our symbol, compute next state
                if current_symbol == s:
                    # Find next position for this symbol
                    # Use round-robin through symbol positions
                    pos_idx = positions.index(table_pos)
                    next_pos_idx = (pos_idx + 1) % len(positions)
                    next_pos = positions[next_pos_idx]
                    
                    # Compute next state
                    block_id = state_shrunk // self.params.TABLE_SIZE
                    next_state = block_id * self.params.TABLE_SIZE + next_pos
                    
                    # Ensure next_state is in valid range
                    if next_state < self.params.L:
                        next_state += self.params.TABLE_SIZE
                    if next_state > self.params.H:
                        next_state = self.params.H
                    
                    table[(s, state_shrunk)] = next_state
        
        return table
    
    def _build_spread_table(self) -> List[Any]:
        """Build spread table using FSE spread algorithm
        
        Distributes symbols across table positions based on normalized frequencies.
        Returns list of symbols, one per table position.
        """
        spread_table = [None] * self.params.TABLE_SIZE
        symbol_positions = {}
        
        # Initialize positions for each symbol
        for s in self.params.freqs.alphabet:
            symbol_positions[s] = []
        
        # Distribute symbols using spread algorithm
        # This is a simplified version - full FSE uses a more sophisticated spread
        cumulative = 0
        for s in self.params.freqs.alphabet:
            norm_freq = self.params.normalized_freqs[s]
            for i in range(norm_freq):
                pos = (cumulative + i) % self.params.TABLE_SIZE
                # Find next available position if this one is taken
                while spread_table[pos] is not None:
                    pos = (pos + 1) % self.params.TABLE_SIZE
                spread_table[pos] = s
                symbol_positions[s].append(pos)
            cumulative += norm_freq
        
        return spread_table
    
    def _build_shrink_tables(self) -> Dict[Any, Tuple[int, int]]:
        """Build tables for state shrinking
        
        Returns dict mapping symbol to (num_bits_base, threshold)
        """
        shrink_tables = {}
        
        for s in self.params.freqs.alphabet:
            norm_freq = self.params.normalized_freqs[s]
            min_state, max_state = self.params.symbol_ranges[s]
            
            # Calculate number of bits to output
            # Similar to tANS approach
            y = get_bit_width(max_state)
            num_bits_base = self.params.NUM_STATE_BITS - y
            
            # Threshold for outputting one more bit
            thresh = (max_state + 1) << num_bits_base
            
            shrink_tables[s] = (num_bits_base, thresh)
        
        return shrink_tables
    
    def encode_symbol(self, s: Any, state: int) -> Tuple[int, BitArray]:
        """Encode one symbol
        
        Args:
            s: Symbol to encode
            state: Current state
            
        Returns:
            (new_state, output_bits)
        """
        output_bits = BitArray("")
        
        # Shrink state to bring it into acceptable range for this symbol
        num_bits_base, thresh = self.shrink_tables[s]
        num_out_bits = num_bits_base
        if state >= thresh:
            num_out_bits += 1
        
        # Output lower bits
        if num_out_bits > 0:
            out_bits = uint_to_bitarray(state)[-num_out_bits:]
            state = state >> num_out_bits
            output_bits = out_bits + output_bits
        
        # Apply FSE encoding step using lookup table
        state_shrunk = state
        if (s, state_shrunk) in self.encode_table:
            state = self.encode_table[(s, state_shrunk)]
        else:
            # Fallback: use simplified encoding based on spread table
            spread_table = self._build_spread_table()
            norm_freq = self.params.normalized_freqs[s]
            table_pos = state % self.params.TABLE_SIZE
            
            # Find next position for this symbol
            symbol_positions = [i for i, sym in enumerate(spread_table) if sym == s]
            if symbol_positions:
                current_idx = symbol_positions.index(table_pos) if table_pos in symbol_positions else 0
                next_idx = (current_idx + 1) % len(symbol_positions)
                next_pos = symbol_positions[next_idx]
                
                block_id = state // self.params.TABLE_SIZE
                state = block_id * self.params.TABLE_SIZE + next_pos
                
                if state < self.params.L:
                    state += self.params.TABLE_SIZE
                if state > self.params.H:
                    state = self.params.H
        
        return state, output_bits
    
    def encode_block(self, data_block: DataBlock) -> BitArray:
        """Encode a block of data
        
        Args:
            data_block: Input data block
            
        Returns:
            Encoded bitarray
        """
        encoded_bitarray = BitArray("")
        
        # Initialize state
        state = self.params.INITIAL_STATE
        
        # Encode each symbol
        for s in data_block.data_list:
            state, symbol_bits = self.encode_symbol(s, state)
            encoded_bitarray = symbol_bits + encoded_bitarray
        
        # Prepend final state
        encoded_bitarray = uint_to_bitarray(state, self.params.NUM_STATE_BITS) + encoded_bitarray
        
        # Prepend block size
        encoded_bitarray = (
            uint_to_bitarray(data_block.size, self.params.DATA_BLOCK_SIZE_BITS) + encoded_bitarray
        )
        
        return encoded_bitarray


class FSEDecoder(DataDecoder):
    """FSE Decoder
    
    Decodes FSE-encoded data by reversing the encoding process.
    """
    
    def __init__(self, fse_params: FSEParams):
        """Initialize FSE decoder
        
        Args:
            fse_params (FSEParams): FSE parameters
        """
        self.params = fse_params
        
        # Build FSE decoding table
        self.decode_table = self._build_decode_table()
        
        # Build state expansion lookup tables
        self.expand_tables = self._build_expand_tables()
    
    def _build_decode_table(self) -> Dict[int, Tuple[Any, int]]:
        """Build FSE decoding table
        
        The table maps state -> (symbol, prev_state_shrunk)
        This is the inverse of the encoding table.
        """
        table = {}
        
        # Build spread table (same as encoder)
        spread_table = self._build_spread_table()
        
        # Build inverse mapping: for each (symbol, next_state), find prev_state
        # We need to reverse the encoding table
        for state in range(self.params.L, self.params.H + 1):
            # Find which symbol this state corresponds to
            table_pos = state % self.params.TABLE_SIZE
            s = spread_table[table_pos]
            
            # Find positions for this symbol
            symbol_positions = [i for i, sym in enumerate(spread_table) if sym == s]
            
            # Find previous position in the sequence
            if table_pos in symbol_positions:
                pos_idx = symbol_positions.index(table_pos)
                prev_pos_idx = (pos_idx - 1) % len(symbol_positions)
                prev_pos = symbol_positions[prev_pos_idx]
            else:
                # Fallback
                prev_pos = (table_pos - 1) % self.params.TABLE_SIZE
            
            # Compute previous state
            block_id = state // self.params.TABLE_SIZE
            prev_state_shrunk = block_id * self.params.TABLE_SIZE + prev_pos
            
            table[state] = (s, prev_state_shrunk)
        
        return table
    
    def _build_spread_table(self) -> List[Any]:
        """Build spread table (same as encoder)"""
        spread_table = [None] * self.params.TABLE_SIZE
        cumulative = 0
        
        for s in self.params.freqs.alphabet:
            norm_freq = self.params.normalized_freqs[s]
            for i in range(norm_freq):
                pos = (cumulative + i) % self.params.TABLE_SIZE
                while spread_table[pos] is not None:
                    pos = (pos + 1) % self.params.TABLE_SIZE
                spread_table[pos] = s
            cumulative += norm_freq
        
        return spread_table
    
    def _build_expand_tables(self) -> Dict[int, int]:
        """Build tables for state expansion
        
        Returns dict mapping shrunk_state -> num_bits_to_read
        """
        expand_tables = {}
        
        for state_shrunk in range(self.params.L, self.params.H + 1):
            num_bits = self.params.NUM_STATE_BITS - get_bit_width(state_shrunk)
            expand_tables[state_shrunk] = num_bits
        
        return expand_tables
    
    def decode_symbol(self, state: int, encoded_bitarray: BitArray) -> Tuple[Any, int, int]:
        """Decode one symbol
        
        Args:
            state: Current state
            encoded_bitarray: Encoded bitstream
            
        Returns:
            (symbol, new_state, num_bits_consumed)
        """
        # Apply FSE decoding step using lookup table
        if state in self.decode_table:
            s, state_shrunk = self.decode_table[state]
        else:
            # Fallback decoding
            spread_table = self._build_spread_table()
            table_pos = state % self.params.TABLE_SIZE
            s = spread_table[table_pos]
            
            # Find previous position for this symbol
            symbol_positions = [i for i, sym in enumerate(spread_table) if sym == s]
            if table_pos in symbol_positions:
                pos_idx = symbol_positions.index(table_pos)
                prev_pos_idx = (pos_idx - 1) % len(symbol_positions)
                prev_pos = symbol_positions[prev_pos_idx]
            else:
                prev_pos = (table_pos - 1) % self.params.TABLE_SIZE
            
            block_id = state // self.params.TABLE_SIZE
            state_shrunk = block_id * self.params.TABLE_SIZE + prev_pos
        
        # Expand state by reading bits
        num_bits = self.params.NUM_STATE_BITS - get_bit_width(state_shrunk)
        state_remainder = 0
        if num_bits > 0:
            state_remainder = bitarray_to_uint(encoded_bitarray[:num_bits])
        state = (state_shrunk << num_bits) + state_remainder
        
        return s, state, num_bits
    
    def decode_block(self, encoded_bitarray: BitArray) -> Tuple[DataBlock, int]:
        """Decode a block of data
        
        Args:
            encoded_bitarray: Encoded bitarray
            
        Returns:
            (decoded_block, num_bits_consumed)
        """
        num_bits_consumed = 0
        
        # Read block size
        data_block_size_bitarray = encoded_bitarray[:self.params.DATA_BLOCK_SIZE_BITS]
        input_data_block_size = bitarray_to_uint(data_block_size_bitarray)
        num_bits_consumed += self.params.DATA_BLOCK_SIZE_BITS
        
        # Read final state
        state = bitarray_to_uint(
            encoded_bitarray[num_bits_consumed:num_bits_consumed + self.params.NUM_STATE_BITS]
        )
        num_bits_consumed += self.params.NUM_STATE_BITS
        
        # Decode symbols (in reverse order)
        decoded_data_list = []
        for _ in range(input_data_block_size):
            s, state, num_symbol_bits = self.decode_symbol(
                state, encoded_bitarray[num_bits_consumed:]
            )
            decoded_data_list = [s] + decoded_data_list
            num_bits_consumed += num_symbol_bits
        
        # Verify final state
        assert state == self.params.INITIAL_STATE, \
            f"Final state {state} != initial state {self.params.INITIAL_STATE}"
        
        return DataBlock(decoded_data_list), num_bits_consumed


######################################## TESTS ##########################################


def test_fse_basic():
    """Basic test for FSE encoding/decoding"""
    freq = Frequencies({"A": 3, "B": 3, "C": 2})
    data = DataBlock(["A", "C", "B"])
    params = FSEParams(freq, DATA_BLOCK_SIZE_BITS=5, TABLE_SIZE_LOG2=4)
    
    encoder = FSEEncoder(params)
    decoder = FSEDecoder(params)
    
    encoded = encoder.encode_block(data)
    decoded, num_bits = decoder.decode_block(encoded)
    
    assert decoded.data_list == data.data_list
    print("Basic FSE test passed!")


def test_fse_coding():
    """Test FSE coding on various distributions"""
    freqs_list = [
        Frequencies({"A": 1, "B": 1, "C": 2}),
        Frequencies({"A": 3, "B": 3, "C": 2}),
        Frequencies({"A": 5, "B": 5, "C": 5, "D": 5}),
        Frequencies({"A": 1, "B": 3}),
    ]
    
    params_list = [
        FSEParams(freqs_list[0], TABLE_SIZE_LOG2=4),
        FSEParams(freqs_list[1], TABLE_SIZE_LOG2=4),
        FSEParams(freqs_list[2], TABLE_SIZE_LOG2=5),
        FSEParams(freqs_list[3], TABLE_SIZE_LOG2=4),
    ]
    
    DATA_SIZE = 1000
    SEED = 0
    
    for freq, fse_params in zip(freqs_list, params_list):
        # Generate random data
        prob_dist = freq.get_prob_dist()
        data_block = get_random_data_block(prob_dist, DATA_SIZE, seed=SEED)
        avg_log_prob = get_avg_neg_log_prob(prob_dist, data_block)
        
        # Create encoder/decoder
        encoder = FSEEncoder(fse_params)
        decoder = FSEDecoder(fse_params)
        
        # Test lossless compression
        is_lossless, encode_len, _ = try_lossless_compression(
            data_block, encoder, decoder, add_extra_bits_to_encoder_output=True
        )
        assert is_lossless, "FSE encoding/decoding must be lossless"
        
        # Calculate average code length
        avg_codelen = encode_len / data_block.size
        print(f"FSE coding: avg_log_prob={avg_log_prob:.3f}, FSE codelen: {avg_codelen:.3f}")


if __name__ == "__main__":
    test_fse_basic()
    test_fse_coding()
    print("All FSE tests passed!")

