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
from scl.core.prob_dist import Frequencies


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
        # Table size must be power of 2 for FSE state space
        self.TABLE_SIZE = 1 << self.TABLE_SIZE_LOG2

        # Normalize frequencies to table size (sum must equal TABLE_SIZE exactly)
        self.normalized_freqs = self._normalize_frequencies()
        assert (
            sum(self.normalized_freqs.values()) == self.TABLE_SIZE
        ), f"Normalized frequencies must sum to {self.TABLE_SIZE}"

        # Initial encoder state = table_size (FSE convention: encoder state in [table_size, 2*table_size))
        self.INITIAL_STATE = self.TABLE_SIZE

    def _normalize_frequencies(self) -> Dict[Any, int]:
        """Normalize frequencies to sum to TABLE_SIZE

        Uses simple proportional scaling with rounding adjustment.
        """
        table_size = self.TABLE_SIZE
        total = self.freqs.total_freq

        if total == 0:
            raise ValueError("empty distribution")

        # Initial proportional allocation: scale each frequency proportionally
        norm = {}
        allocated = 0

        for s in self.freqs.alphabet:
            c = self.freqs.frequency(s)
            if c == 0:
                norm[s] = 0
                continue

            x = c * table_size / total
            n = max(1, int(round(x)))
            norm[s] = n
            allocated += n

        # Fix rounding errors: adjust frequencies to sum exactly to table_size
        diff = table_size - allocated
        if diff != 0:
            # Sort by frequency (descending) to prioritize high-frequency symbols
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


class BitReader:
    """Bit reader for decoding"""

    def __init__(self, bits: BitArray):
        self.bits = bits
        self.pos = 0  # bit position from left

    def read_bits(self, n: int) -> int:
        """Read n bits from current position (MSB-first, left to right)"""
        if n == 0:
            return 0
        # Read bits starting at pos, convert to integer (MSB-first)
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
    # FSE step formula: ensures step is odd and co-prime with table_size
    step = (table_size >> 1) + (table_size >> 3) + 3

    # Build list of symbols, each appearing according to its normalized frequency
    syms = []
    for s, freq in norm_freq.items():
        syms.extend([s] * freq)

    # Use FSE spread algorithm: place symbols using step pattern
    pos = 0
    for s in syms:
        start_pos = pos
        attempts = 0
        while spread[pos] is not None:
            pos = (pos + step) & table_mask  # Wrap around using mask
            attempts += 1
            if attempts >= table_size or pos == start_pos:
                # Fallback: find any empty position if step pattern fails
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
            spread[pos] = s
            pos = (pos + step) & table_mask

    assert all(x is not None for x in spread), "Spread table must be fully populated"
    return spread


def build_decode_table(
    spread: List[Any], norm_freq: Dict[Any, int], table_log: int
) -> List[DecodeEntry]:
    """Build FSE decode table

    For each state, computes:
    - symbol: from spread table
    - nb_bits: number of bits to read, computed as table_log - floor_log2(next_state_enc)
    - new_state_base: base value for new state, computed as (next_state_enc << nb_bits) - table_size

    Args:
        spread: Spread table (symbol per state)
        norm_freq: Normalized frequencies
        table_log: Log2 of table size

    Returns:
        List of DecodeEntry, one per state
    """
    table_size = 1 << table_log
    D = [None] * table_size
    # Track next encoder state for each symbol (starts at normalized frequency)
    symbol_next = {s: norm_freq[s] for s in norm_freq}

    for u in range(table_size):
        s = spread[u]
        # Encoder state is in [table_size, 2*table_size)
        next_state_enc = symbol_next[s]
        symbol_next[s] += 1

        # Compute nb_bits: number of bits to read, chosen so average matches Shannon code length
        nb_bits = table_log - floor_log2(next_state_enc)
        # Compute base for new decoder state (decoder state is in [0, table_size))
        new_state_base = (next_state_enc << nb_bits) - table_size

        assert (
            0 <= new_state_base < table_size
        ), f"New state base {new_state_base} not in [0, {table_size})"

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

    # Build tableU16: maps subrange_id to next encoder state (in [table_size, 2*table_size))
    tableU16 = [0] * table_size
    local_cumul = cumul.copy()
    for u, s in enumerate(spread):
        tableU16[local_cumul[s]] = (
            table_size + u
        )  # Encoder state = table_size + decoder state
        local_cumul[s] += 1

    # Build symbolTT: per-symbol transforms for encoding
    symbolTT = {}
    total = 0
    for s in symbols:
        freq = norm_freq[s]
        if freq == 0:
            # Special case: zero-frequency symbol
            delta_nb_bits = ((table_log + 1) << 16) - (1 << table_log)
            symbolTT[s] = SymTransform(delta_nb_bits, 0)
            continue

        # Compute max bits output for this symbol
        max_bits_out = table_log - floor_log2(freq - 1)
        min_state_plus = freq << max_bits_out
        # delta_nb_bits encodes both max_bits_out (high 16 bits) and min_state_plus (low 16 bits)
        delta_nb_bits = (max_bits_out << 16) - min_state_plus
        # delta_find_state: offset to find the symbol's subrange in tableU16
        delta_find_state = total - freq
        total += freq

        symbolTT[s] = SymTransform(delta_nb_bits, delta_find_state)

    return tableU16, symbolTT


class FSEEncoder(DataEncoder):
    """FSE Encoder"""

    def __init__(self, fse_params: FSEParams):
        self.params = fse_params
        self.table_log = fse_params.TABLE_SIZE_LOG2
        self.table_size = fse_params.TABLE_SIZE
        self.DATA_BLOCK_SIZE_BITS = fse_params.DATA_BLOCK_SIZE_BITS

        norm_freq = fse_params.normalized_freqs
        self.spread_table = build_spread_table(norm_freq, self.table_log)
        self.DTable = build_decode_table(self.spread_table, norm_freq, self.table_log)
        self.tableU16, self.symbolTT = build_encode_table(
            self.spread_table, norm_freq, self.table_log
        )

    def encode_symbol(self, state: int, s: Any) -> Tuple[int, int, int]:
        """Encode one symbol

        Args:
            state: Current state (in [table_size, 2*table_size))
            s: Symbol to encode

        Returns:
            (new_state, nb_bits_out, out_bits_value)
        """
        tt = self.symbolTT[s]
        # Extract number of bits to output
        nb_out = (state + tt.delta_nb_bits) >> 16
        # Extract low nb_out bits from state to output
        out_mask = (1 << nb_out) - 1
        out_bits_value = state & out_mask
        # Compute subrange_id and look up next state
        subrange_id = state >> nb_out
        new_state = self.tableU16[subrange_id + tt.delta_find_state]
        return new_state, nb_out, out_bits_value

    def encode_block(self, data_block: DataBlock) -> BitArray:
        """Encode a block of data"""
        symbols = list(data_block.data_list)
        block_size = len(symbols)

        # Handle empty block: still encode block size (0)
        if not symbols:
            return uint_to_bitarray(0, bit_width=self.DATA_BLOCK_SIZE_BITS)

        # FSE encodes in reverse order (last symbol first)
        state = self.table_size

        # Encode from last symbol to first (reverse order)
        bits = BitArray("")
        for s in reversed(symbols):
            state, nb_out, out_bits_value = self.encode_symbol(state, s)
            if nb_out > 0:
                # Prepend bits since we're encoding backwards
                bits = uint_to_bitarray(out_bits_value, bit_width=nb_out) + bits

        # Store final state offset (encoder state is in [table_size, 2*table_size))
        # Offset is in [0, table_size), encoded with table_log bits
        state_offset = state - self.table_size
        final_state_bits = uint_to_bitarray(state_offset, bit_width=self.table_log)
        bits = final_state_bits + bits

        # Prepend block size header (encoded with DATA_BLOCK_SIZE_BITS)
        block_size_bits = uint_to_bitarray(
            block_size, bit_width=self.DATA_BLOCK_SIZE_BITS
        )
        bits = block_size_bits + bits

        return bits


class FSEDecoder(DataDecoder):
    """FSE Decoder

    Decodes symbols using a table-based approach, reading variable numbers of bits
    based on the current state to determine the next symbol and state.
    """

    def __init__(self, fse_params: FSEParams):
        """Initialize FSE decoder with parameters"""
        self.params = fse_params
        self.table_log = fse_params.TABLE_SIZE_LOG2
        self.table_size = fse_params.TABLE_SIZE
        self.DATA_BLOCK_SIZE_BITS = fse_params.DATA_BLOCK_SIZE_BITS

        norm_freq = fse_params.normalized_freqs
        self.spread_table = build_spread_table(norm_freq, self.table_log)
        self.DTable = build_decode_table(self.spread_table, norm_freq, self.table_log)

    def decode_symbol(self, state: int, bitreader: BitReader) -> Tuple[Any, int]:
        """Decode one symbol: lookup in decode table, read bits, compute next state"""
        entry = self.DTable[state]  # Decoder state is in [0, table_size)
        s = entry.symbol
        nb = entry.nb_bits  # Number of bits to read (variable, depends on state)
        bits = bitreader.read_bits(nb)
        # Next state = base + read bits (both in [0, table_size))
        new_state = entry.new_state_base + bits
        return s, new_state

    def decode_block(self, encoded_bitarray: BitArray) -> Tuple[DataBlock, int]:
        """Decode a block of data"""
        num_bits_consumed = 0

        if len(encoded_bitarray) < self.DATA_BLOCK_SIZE_BITS:
            return DataBlock([]), 0

        # Read block size
        block_size_bits = encoded_bitarray[: self.DATA_BLOCK_SIZE_BITS]
        block_size = (
            bitarray_to_uint(block_size_bits) if len(block_size_bits) > 0 else 0
        )
        num_bits_consumed += self.DATA_BLOCK_SIZE_BITS

        if block_size == 0:
            return DataBlock([]), num_bits_consumed

        # Read final state offset (decoder state is in [0, table_size))
        # Offset was encoded with table_log bits, decoder uses it directly as initial state
        final_state_bits = encoded_bitarray[
            num_bits_consumed : num_bits_consumed + self.table_log
        ]
        state_offset = bitarray_to_uint(final_state_bits)
        state = state_offset  # Decoder starts at this state (encoder started at table_size, offset 0)
        num_bits_consumed += self.table_log

        # Set up bit reader for remaining bits
        bitreader = BitReader(encoded_bitarray[num_bits_consumed:])

        # Decode forward
        # When we encode in reverse order, the bits are written in reverse
        # When we decode forward, we read bits in forward order
        # The symbols come out in the correct order (not reversed)
        result = []
        for _ in range(block_size):
            s, state = self.decode_symbol(state, bitreader)
            result.append(s)

        # Verify we end at state 0 (encoder started at table_size, offset 0)
        assert state == 0, f"Final decode state {state} != initial decode state 0"
        num_bits_consumed += bitreader.pos
        return DataBlock(result), num_bits_consumed
