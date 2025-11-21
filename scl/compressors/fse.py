"""FSE (Finite State Entropy) implementation

FSE is a variant of tANS (table ANS) used in zstandard compression.
This implementation follows the baseline FSE algorithm as described in
Yann Collet's blogs.
"""

from dataclasses import dataclass
from typing import Tuple, Any, List, Dict
from scl.core.data_encoder_decoder import DataDecoder, DataEncoder
from scl.utils.bitarray_utils import (
    BitArray,
    uint_to_bitarray,
    bitarray_to_uint,
)
from scl.core.data_block import DataBlock
from scl.core.prob_dist import Frequencies, get_avg_neg_log_prob
from scl.utils.test_utils import get_random_data_block, try_lossless_compression


def floor_log2(x: int) -> int:
    """Compute floor(log2(x)) for x > 0"""
    return x.bit_length() - 1


@dataclass
class DecodeEntry:
    """Decode table entry: maps state to (symbol, nb_bits, new_state_base)"""

    symbol: Any
    nb_bits: int
    new_state_base: int


@dataclass
class SymTransform:
    """Symbol transform for encoding: (delta_nb_bits, delta_find_state)"""

    delta_nb_bits: int
    delta_find_state: int


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
    # Default: 12 (4096 states)
    # trades off compression for memory usage
    TABLE_SIZE_LOG2: int = 12

    def __post_init__(self):
        """Compute derived parameters"""
        # Table size (must be power of 2)
        self.TABLE_SIZE = 1 << self.TABLE_SIZE_LOG2

        # Normalize frequencies to table size
        self.normalized_freqs = self._normalize_frequencies()

        # Verify normalization
        assert (
            sum(self.normalized_freqs.values()) == self.TABLE_SIZE
        ), f"Normalized frequencies must sum to {self.TABLE_SIZE}"

        # Initial state = table_size (FSE convention)
        self.INITIAL_STATE = self.TABLE_SIZE

    def _normalize_frequencies(self) -> Dict[Any, int]:
        """Normalize frequencies to sum to TABLE_SIZE

        Uses simple proportional scaling with rounding adjustment.
        """
        table_size = self.TABLE_SIZE
        total = self.freqs.total_freq

        if total == 0:
            raise ValueError("empty distribution")

        # Initial proportional allocation
        norm = {}
        allocated = 0

        for s in self.freqs.alphabet:
            c = self.freqs.frequency(s)
            if c == 0:
                norm[s] = 0
                continue

            # Simple proportion (floating point is fine in Python)
            x = c * table_size / total
            n = max(1, int(round(x)))
            norm[s] = n
            allocated += n

        # Fix rounding so sum(norm) == table_size
        diff = table_size - allocated

        if diff != 0:
            # Sort symbols by original frequency descending
            sorted_syms = sorted(
                self.freqs.alphabet, key=lambda s: self.freqs.frequency(s), reverse=True
            )
            i = 0
            step = 1 if diff > 0 else -1
            while diff != 0 and i < len(sorted_syms):
                s = sorted_syms[i]
                if norm[s] + step > 0:  # keep strictly positive
                    norm[s] += step
                    diff -= step
                else:
                    i += 1

        return norm


class SimpleBitReader:
    """Simple bit reader for decoding"""

    def __init__(self, bits: BitArray):
        self.bits = bits
        self.pos = 0  # bit position from left

    def read_bits(self, n: int) -> int:
        """Read n bits from current position"""
        if n == 0:
            return 0
        v = bitarray_to_uint(self.bits[self.pos : self.pos + n])
        self.pos += n
        return v


def build_spread_table(norm_freq: Dict[Any, int], table_log: int) -> List[Any]:
    """Build FSE spread table using the co-prime step algorithm

    Distributes symbols across table positions based on normalized frequencies.
    Uses FSE's step formula: step = (table_size >> 1) + (table_size >> 3) + 3

    Args:
        norm_freq: Normalized frequencies dict
        table_log: Log2 of table size

    Returns:
        List of symbols, one per table position (length = 2^table_log)
    """
    table_size = 1 << table_log
    table_mask = table_size - 1
    spread = [None] * table_size

    # FSE step formula (must be odd, co-prime with table_size)
    step = (table_size >> 1) + (table_size >> 3) + 3

    # Build list of all symbols with their frequencies
    syms = []
    for s, freq in norm_freq.items():
        syms.extend([s] * freq)

    # Use FSE spread algorithm: place symbols using step pattern
    pos = 0
    for s in syms:
        # Find next empty position using step pattern
        start_pos = pos
        attempts = 0
        while spread[pos] is not None:
            pos = (pos + step) & table_mask
            attempts += 1
            # Safety check: if we've cycled through all positions, find any empty one
            if attempts >= table_size or pos == start_pos:
                # Fallback: find any empty position
                found = False
                for i in range(table_size):
                    if spread[i] is None:
                        spread[i] = s
                        pos = (i + step) & table_mask
                        found = True
                        break
                if not found:
                    # This should never happen if frequencies sum correctly
                    raise ValueError(f"Cannot find empty position for symbol {s}")
                break
        else:
            # Found empty position via step pattern
            spread[pos] = s
            pos = (pos + step) & table_mask

    assert all(x is not None for x in spread), "Spread table must be fully populated"
    return spread


def build_decode_table(
    spread: List[Any], norm_freq: Dict[Any, int], table_log: int
) -> List[DecodeEntry]:
    """Build FSE decode table with real k/(k+1) logic

    For each state, computes:
    - symbol: from spread table
    - nb_bits: table_log - floor_log2(nextState) (this gives k/k+1 distribution)
    - new_state_base: (nextState << nb_bits) - table_size

    Args:
        spread: Spread table (symbol per state)
        norm_freq: Normalized frequencies
        table_log: Log2 of table size

    Returns:
        List of DecodeEntry, one per state
    """
    table_size = 1 << table_log
    D = [None] * table_size

    # symbol_next starts at normalized frequency (like FSE C code)
    symbol_next = {s: norm_freq[s] for s in norm_freq}

    for u in range(table_size):
        s = spread[u]
        next_state_enc = symbol_next[s]  # Encoder state in [table_size, 2*table_size)
        symbol_next[s] += 1

        nb_bits = table_log - floor_log2(next_state_enc)

        max_bits = (1 << nb_bits) - 1 if nb_bits > 0 else 0

        new_state_base = (next_state_enc << nb_bits) - table_size

        # Adjust to ensure it's in valid range for decode states
        # We need: 0 <= new_state_base and new_state_base + max_bits < table_size
        if new_state_base < 0:
            new_state_base = 0
        if new_state_base + max_bits >= table_size:
            new_state_base = table_size - max_bits - 1
            if new_state_base < 0:
                new_state_base = 0

        D[u] = DecodeEntry(symbol=s, nb_bits=nb_bits, new_state_base=new_state_base)

    return D


def build_encode_table(
    spread: List[Any], norm_freq: Dict[Any, int], table_log: int
) -> Tuple[List[int], Dict[Any, SymTransform]]:
    """Build FSE encode table (tableU16 and symbolTT)

    Args:
        spread: Spread table
        norm_freq: Normalized frequencies
        table_log: Log2 of table size

    Returns:
        (tableU16, symbolTT) where:
        - tableU16: next-state table (length = table_size)
        - symbolTT: dict mapping symbol to SymTransform
    """
    table_size = 1 << table_log
    symbols = list(norm_freq.keys())

    # Compute cumulative start index per symbol
    cumul = {}
    acc = 0
    for s in symbols:
        cumul[s] = acc
        acc += norm_freq[s]
    assert acc == table_size

    # Build tableU16: next-state table
    # Stores states in [table_size, 2*table_size) range
    tableU16 = [0] * table_size
    local_cumul = cumul.copy()
    for u, s in enumerate(spread):
        tableU16[local_cumul[s]] = table_size + u
        local_cumul[s] += 1

    # Build symbol transforms (delta_nb_bits, delta_find_state)
    symbolTT = {}
    total = 0
    for s in symbols:
        freq = norm_freq[s]
        if freq == 0:
            delta_nb_bits = ((table_log + 1) << 16) - (1 << table_log)
            symbolTT[s] = SymTransform(delta_nb_bits, 0)
            continue

        # FSE formulas (baseline, no low-prob special-casing)
        max_bits_out = table_log - floor_log2(freq - 1)
        min_state_plus = freq << max_bits_out
        delta_nb_bits = (max_bits_out << 16) - min_state_plus
        delta_find_state = total - freq
        total += freq

        symbolTT[s] = SymTransform(delta_nb_bits, delta_find_state)

    return tableU16, symbolTT


class FSEEncoder(DataEncoder):
    """FSE Encoder using proper FSE algorithm with k/(k+1) bit distribution"""

    def __init__(self, fse_params: FSEParams):
        """Initialize FSE encoder

        Args:
            fse_params (FSEParams): FSE parameters
        """
        self.params = fse_params
        self.table_log = fse_params.TABLE_SIZE_LOG2
        self.table_size = fse_params.TABLE_SIZE
        self.DATA_BLOCK_SIZE_BITS = fse_params.DATA_BLOCK_SIZE_BITS

        # Build FSE tables
        norm_freq = fse_params.normalized_freqs

        # Build spread table
        self.spread_table = build_spread_table(norm_freq, self.table_log)

        # Build decode table (needed for verification, encoder uses encode tables)
        self.DTable = build_decode_table(self.spread_table, norm_freq, self.table_log)

        # Build encode tables
        self.tableU16, self.symbolTT = build_encode_table(
            self.spread_table, norm_freq, self.table_log
        )

    def encode_symbol(self, state: int, s: Any) -> Tuple[int, int, int]:
        """Encode one symbol using FSE algorithm

        Args:
            state: Current state (in [table_size, 2*table_size))
            s: Symbol to encode

        Returns:
            (new_state, nb_bits_out, out_bits_value)
        """
        tt = self.symbolTT[s]

        nb_out = (state + tt.delta_nb_bits) >> 16

        # Write out lowest nb_out bits of state
        out_mask = (1 << nb_out) - 1
        out_bits_value = state & out_mask

        # Compute subrange ID and next state
        subrange_id = state >> nb_out
        new_state = self.tableU16[subrange_id + tt.delta_find_state]

        return new_state, nb_out, out_bits_value

    def encode_block(self, data_block: DataBlock) -> BitArray:
        """Encode a block of data

        Args:
            data_block: Input data block

        Returns:
            Encoded bitarray
        """
        symbols = list(data_block.data_list)
        block_size = len(symbols)

        # Handle empty block: still encode block size (0)
        if not symbols:
            block_size_bits = uint_to_bitarray(0, bit_width=self.DATA_BLOCK_SIZE_BITS)
            return block_size_bits

        # Initialize state (FSE convention: start at table_size)
        state = self.table_size

        # Encode from last symbol to first (reverse order)
        bits = BitArray("")
        for s in reversed(symbols):
            state, nb_out, out_bits_value = self.encode_symbol(state, s)
            if nb_out > 0:
                # Prepend bits (since we're encoding in reverse)
                bits = uint_to_bitarray(out_bits_value, bit_width=nb_out) + bits

        # Prepend final state
        # State is in [table_size, 2*table_size), so we encode (state - table_size) with table_log bits
        state_offset = state - self.table_size
        final_state_bits = uint_to_bitarray(state_offset, bit_width=self.table_log)
        bits = final_state_bits + bits

        # Prepend block size
        block_size_bits = uint_to_bitarray(
            block_size, bit_width=self.DATA_BLOCK_SIZE_BITS
        )
        bits = block_size_bits + bits

        return bits


class FSEDecoder(DataDecoder):
    """FSE Decoder using proper FSE algorithm with k/(k+1) bit distribution"""

    def __init__(self, fse_params: FSEParams):
        """Initialize FSE decoder

        Args:
            fse_params (FSEParams): FSE parameters (must match encoder)
        """
        self.params = fse_params
        self.table_log = fse_params.TABLE_SIZE_LOG2
        self.table_size = fse_params.TABLE_SIZE
        self.DATA_BLOCK_SIZE_BITS = fse_params.DATA_BLOCK_SIZE_BITS

        # Build FSE tables (same as encoder)
        norm_freq = fse_params.normalized_freqs

        # Build spread table
        self.spread_table = build_spread_table(norm_freq, self.table_log)

        # Build decode table
        self.DTable = build_decode_table(self.spread_table, norm_freq, self.table_log)

    def decode_symbol(self, state: int, bitreader: SimpleBitReader) -> Tuple[Any, int]:
        """Decode one symbol using FSE algorithm

        Args:
            state: Current state (in [table_size, 2*table_size))
            bitreader: Bit reader for reading bits from stream

        Returns:
            (symbol, new_state)
        """
        # DTable is indexed by state in [0, table_size)
        entry = self.DTable[state]
        s = entry.symbol
        nb = entry.nb_bits
        bits = bitreader.read_bits(nb)
        new_state = entry.new_state_base + bits
        return s, new_state

    def decode_block(self, encoded_bitarray: BitArray) -> Tuple[DataBlock, int]:
        """Decode a block of data

        Args:
            encoded_bitarray: Encoded bitarray

        Returns:
            (decoded_block, num_bits_consumed)
        """
        num_bits_consumed = 0

        # Handle empty block
        if len(encoded_bitarray) < self.DATA_BLOCK_SIZE_BITS:
            return DataBlock([]), 0

        # Read block size
        block_size_bits = encoded_bitarray[: self.DATA_BLOCK_SIZE_BITS]
        block_size = (
            bitarray_to_uint(block_size_bits) if len(block_size_bits) > 0 else 0
        )
        num_bits_consumed += self.DATA_BLOCK_SIZE_BITS

        # Handle empty block
        if block_size == 0:
            return DataBlock([]), num_bits_consumed

        # Read final state (encoded as offset from table_size in encoder)
        # Encoder state is in [table_size, 2*table_size), encoded as offset in [0, table_size)
        # Decoder state is in [0, table_size), so we use the offset directly
        final_state_bits = encoded_bitarray[
            num_bits_consumed : num_bits_consumed + self.table_log
        ]
        state_offset = bitarray_to_uint(final_state_bits)
        # Decode state is the offset directly (encoder state - table_size)
        state = state_offset
        num_bits_consumed += self.table_log

        # Set up bit reader for remaining bits
        bitreader = SimpleBitReader(encoded_bitarray[num_bits_consumed:])

        # Decode forward
        # When we encode in reverse order, the bits are written in reverse
        # When we decode forward, we read bits in forward order
        # The symbols come out in the correct order (not reversed)
        result = []
        for _ in range(block_size):
            s, state = self.decode_symbol(state, bitreader)
            result.append(s)

        # Verify final state
        # Encoder starts at table_size (offset 0), so decoder should end at state 0
        assert state == 0, f"Final decode state {state} != initial decode state 0"

        num_bits_consumed += bitreader.pos
        return DataBlock(result), num_bits_consumed


######################################## TESTS ##########################################


def test_fse_basic():
    freq = Frequencies({"A": 3, "B": 3, "C": 2})
    data = DataBlock(["A", "C", "B"])
    # Use default TABLE_SIZE_LOG2=12 (4096 states) unless testing with smaller table
    params = FSEParams(freq, DATA_BLOCK_SIZE_BITS=5, TABLE_SIZE_LOG2=4)

    encoder = FSEEncoder(params)
    decoder = FSEDecoder(params)

    encoded = encoder.encode_block(data)
    decoded, num_bits = decoder.decode_block(encoded)

    assert decoded.data_list == data.data_list
    print("Basic FSE test passed!")


def test_fse_coding():
    freqs_list = [
        Frequencies({"A": 1, "B": 1, "C": 2}),
        Frequencies({"A": 3, "B": 3, "C": 2}),
        Frequencies({"A": 5, "B": 5, "C": 5, "D": 5}),
        Frequencies({"A": 1, "B": 3}),
    ]

    params_list = [
        FSEParams(freqs_list[0], TABLE_SIZE_LOG2=12),
        FSEParams(freqs_list[1], TABLE_SIZE_LOG2=12),
        FSEParams(freqs_list[2], TABLE_SIZE_LOG2=12),
        FSEParams(freqs_list[3], TABLE_SIZE_LOG2=12),
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
        print(
            f"FSE coding: avg_log_prob={avg_log_prob:.3f}, FSE codelen: {avg_codelen:.3f}"
        )


if __name__ == "__main__":
    test_fse_basic()
    test_fse_coding()
    print("All FSE tests passed!")
