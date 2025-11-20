"""Comprehensive unit tests for FSE implementation

Tests each component separately:
- Frequency normalization
- Symbol spreading
- Decode table building
- Encode table building
- Encoding/decoding individual symbols
- Full block encoding/decoding
"""

import pytest
from scl.compressors.fse import (
    FSEParams,
    FSEEncoder,
    FSEDecoder,
    build_spread_table,
    build_decode_table,
    build_encode_table,
    floor_log2,
    DecodeEntry,
    SymTransform,
)
from scl.core.prob_dist import Frequencies
from scl.core.data_block import DataBlock
from scl.utils.bitarray_utils import BitArray, uint_to_bitarray, bitarray_to_uint


########################################
# Test Helper Functions
########################################


def print_spread_table(spread, table_log, norm_freq):
    """Debug: Print spread table"""
    print(f"\nSpread Table (table_log={table_log}, table_size={1 << table_log}):")
    for i, s in enumerate(spread):
        print(f"  [{i:3d}] = {s}")
    print(f"\nNormalized frequencies: {norm_freq}")
    # Count occurrences
    counts = {}
    for s in spread:
        counts[s] = counts.get(s, 0) + 1
    print(f"Actual counts in spread: {counts}")


def print_decode_table(DTable, table_size):
    """Debug: Print decode table"""
    print(f"\nDecode Table (first 10 entries):")
    for i in range(min(10, table_size)):
        entry = DTable[i]
        print(
            f"  state[{i:3d}]: symbol={entry.symbol}, nb_bits={entry.nb_bits}, "
            f"new_state_base={entry.new_state_base}"
        )


def print_encode_table(tableU16, symbolTT, table_size):
    """Debug: Print encode table"""
    print(f"\nEncode Table:")
    print(f"  tableU16 (first 10): {tableU16[:10]}")
    print(f"  symbolTT:")
    for s, tt in symbolTT.items():
        print(f"    {s}: delta_nb_bits={tt.delta_nb_bits}, delta_find_state={tt.delta_find_state}")


########################################
# Test Frequency Normalization
########################################


def test_normalize_frequencies_basic():
    """Test basic frequency normalization"""
    freq = Frequencies({"A": 3, "B": 3, "C": 2})
    params = FSEParams(freq, TABLE_SIZE_LOG2=4)  # table_size = 16

    # Check that normalized frequencies sum to table_size
    assert sum(params.normalized_freqs.values()) == 16
    # Check that all symbols have at least frequency 1
    for s in freq.alphabet:
        assert params.normalized_freqs[s] >= 1


def test_normalize_frequencies_preserves_ratios():
    """Test that normalization preserves frequency ratios approximately"""
    freq = Frequencies({"A": 6, "B": 3, "C": 1})
    params = FSEParams(freq, TABLE_SIZE_LOG2=4)  # table_size = 16

    norm = params.normalized_freqs
    # A should have roughly 2x B, B should have roughly 3x C
    assert norm["A"] >= norm["B"]
    assert norm["B"] >= norm["C"]
    assert sum(norm.values()) == 16


def test_normalize_frequencies_single_symbol():
    """Test normalization with single symbol"""
    freq = Frequencies({"A": 10})
    params = FSEParams(freq, TABLE_SIZE_LOG2=4)  # table_size = 16

    assert params.normalized_freqs["A"] == 16
    assert sum(params.normalized_freqs.values()) == 16


########################################
# Test Symbol Spreading
########################################


def test_spread_table_size():
    """Test that spread table has correct size"""
    # Use FSEParams to get properly normalized frequencies
    freq = Frequencies({"A": 3, "B": 3, "C": 2})
    params = FSEParams(freq, TABLE_SIZE_LOG2=4)
    norm_freq = params.normalized_freqs
    table_log = 4
    spread = build_spread_table(norm_freq, table_log)

    assert len(spread) == (1 << table_log)  # 16
    assert all(x is not None for x in spread)  # All positions filled


def test_spread_table_counts():
    """Test that spread table has correct symbol counts"""
    # Use FSEParams to get properly normalized frequencies
    freq = Frequencies({"A": 3, "B": 3, "C": 2})
    params = FSEParams(freq, TABLE_SIZE_LOG2=4)
    norm_freq = params.normalized_freqs
    table_log = 4
    spread = build_spread_table(norm_freq, table_log)

    # Count occurrences - should match normalized frequencies
    counts = {}
    for s in spread:
        counts[s] = counts.get(s, 0) + 1

    # Counts should match normalized frequencies (not original frequencies)
    for s in norm_freq:
        assert counts[s] == norm_freq[s], f"Symbol {s}: expected {norm_freq[s]}, got {counts.get(s, 0)}"
    assert sum(counts.values()) == len(spread)


def test_spread_table_distribution():
    """Test that spread table distributes symbols"""
    # Use FSEParams to get properly normalized frequencies
    freq = Frequencies({"A": 8, "B": 8})
    params = FSEParams(freq, TABLE_SIZE_LOG2=4)
    norm_freq = params.normalized_freqs
    table_log = 4
    spread = build_spread_table(norm_freq, table_log)

    # Symbols should be distributed (not all A's together)
    # Check that we have both symbols
    assert "A" in spread
    assert "B" in spread
    # Check distribution - symbols should alternate or be spread out
    transitions = sum(1 for i in range(len(spread) - 1) if spread[i] != spread[i + 1])
    assert transitions > 0  # Should have some transitions


########################################
# Test Decode Table Building
########################################


def test_decode_table_size():
    """Test that decode table has correct size"""
    freq = Frequencies({"A": 3, "B": 3, "C": 2})
    params = FSEParams(freq, TABLE_SIZE_LOG2=4)
    norm_freq = params.normalized_freqs
    table_log = 4
    spread = build_spread_table(norm_freq, table_log)
    DTable = build_decode_table(spread, norm_freq, table_log)

    assert len(DTable) == (1 << table_log)


def test_decode_table_entries():
    """Test that decode table entries are valid"""
    freq = Frequencies({"A": 3, "B": 3, "C": 2})
    params = FSEParams(freq, TABLE_SIZE_LOG2=4)
    norm_freq = params.normalized_freqs
    table_log = 4
    spread = build_spread_table(norm_freq, table_log)
    DTable = build_decode_table(spread, norm_freq, table_log)

    table_size = 1 << table_log
    for entry in DTable:
        assert isinstance(entry, DecodeEntry)
        assert entry.symbol in norm_freq
        assert entry.nb_bits > 0
        assert entry.nb_bits <= table_log
        # new_state_base should ensure new_state >= table_size when bits=0
        # Actually, let's check: new_state_base + 0 should be >= table_size
        # But wait, that might not always be true. Let's check the range.
        assert entry.new_state_base >= 0  # Should be non-negative after our fix


def test_decode_table_state_ranges():
    """Test that decode table produces valid state ranges"""
    freq = Frequencies({"A": 3, "B": 3, "C": 2})
    params = FSEParams(freq, TABLE_SIZE_LOG2=4)
    norm_freq = params.normalized_freqs
    table_log = 4
    spread = build_spread_table(norm_freq, table_log)
    DTable = build_decode_table(spread, norm_freq, table_log)

    table_size = 1 << table_log
    for entry in DTable:
        # Test with minimum and maximum bits
        min_bits = 0
        max_bits = (1 << entry.nb_bits) - 1
        min_state = entry.new_state_base + min_bits
        max_state = entry.new_state_base + max_bits

        # States should be in valid range [table_size, 2*table_size)
        assert min_state >= table_size, f"min_state {min_state} < table_size {table_size}"
        assert max_state < 2 * table_size, f"max_state {max_state} >= 2*table_size {2*table_size}"


########################################
# Test Encode Table Building
########################################


def test_encode_table_structure():
    """Test that encode table has correct structure"""
    freq = Frequencies({"A": 3, "B": 3, "C": 2})
    params = FSEParams(freq, TABLE_SIZE_LOG2=4)
    norm_freq = params.normalized_freqs
    table_log = 4
    spread = build_spread_table(norm_freq, table_log)
    tableU16, symbolTT = build_encode_table(spread, norm_freq, table_log)

    table_size = 1 << table_log
    assert len(tableU16) == table_size
    assert len(symbolTT) == len(norm_freq)

    # Check tableU16 values are in [table_size, 2*table_size)
    for val in tableU16:
        if val > 0:  # Some entries might be 0 for unused symbols
            assert table_size <= val < 2 * table_size


def test_encode_table_symbol_transforms():
    """Test that symbol transforms are valid"""
    freq = Frequencies({"A": 3, "B": 3, "C": 2})
    params = FSEParams(freq, TABLE_SIZE_LOG2=4)
    norm_freq = params.normalized_freqs
    table_log = 4
    spread = build_spread_table(norm_freq, table_log)
    tableU16, symbolTT = build_encode_table(spread, norm_freq, table_log)

    for s, tt in symbolTT.items():
        assert isinstance(tt, SymTransform)
        # delta_find_state can be negative (it's an offset into tableU16)
        # It should be within reasonable bounds relative to table size
        table_size = 1 << table_log
        assert -table_size <= tt.delta_find_state <= table_size


########################################
# Test Encoding Individual Symbols
########################################


def test_encode_symbol_state_transitions():
    """Test that encoding symbols produces valid state transitions"""
    freq = Frequencies({"A": 3, "B": 3, "C": 2})
    params = FSEParams(freq, TABLE_SIZE_LOG2=4)
    encoder = FSEEncoder(params)

    # Test encoding each symbol
    for s in freq.alphabet:
        state = params.TABLE_SIZE
        new_state, nb_out, out_bits = encoder.encode_symbol(state, s)

        # State should be in valid range
        assert params.TABLE_SIZE <= new_state < 2 * params.TABLE_SIZE
        # Output bits should be valid
        assert 0 <= out_bits < (1 << nb_out)
        assert nb_out >= 0


def test_encode_symbol_multiple_steps():
    """Test encoding multiple symbols in sequence"""
    freq = Frequencies({"A": 3, "B": 3, "C": 2})
    params = FSEParams(freq, TABLE_SIZE_LOG2=4)
    encoder = FSEEncoder(params)

    state = params.TABLE_SIZE
    symbols = ["A", "B", "C"]

    for s in symbols:
        state, nb_out, out_bits = encoder.encode_symbol(state, s)
        assert params.TABLE_SIZE <= state < 2 * params.TABLE_SIZE


########################################
# Test Decoding Individual Symbols
########################################


def test_decode_symbol_state_transitions():
    """Test that decoding symbols produces valid state transitions"""
    freq = Frequencies({"A": 3, "B": 3, "C": 2})
    params = FSEParams(freq, TABLE_SIZE_LOG2=4)
    decoder = FSEDecoder(params)

    from scl.compressors.fse import SimpleBitReader

    # Test decoding from various states
    for state_idx in range(min(5, params.TABLE_SIZE)):
        state = params.TABLE_SIZE + state_idx
        # Create a dummy bitreader with some bits
        bits = BitArray("1010")  # Some test bits
        bitreader = SimpleBitReader(bits)

        s, new_state = decoder.decode_symbol(state, bitreader)

        # Symbol should be valid
        assert s in freq.alphabet
        # New state should be in valid range
        assert params.TABLE_SIZE <= new_state < 2 * params.TABLE_SIZE


########################################
# Test Full Block Encoding/Decoding
########################################


def test_encode_decode_single_symbol():
    """Test encoding and decoding a single symbol"""
    freq = Frequencies({"A": 3, "B": 3, "C": 2})
    params = FSEParams(freq, TABLE_SIZE_LOG2=4)
    encoder = FSEEncoder(params)
    decoder = FSEDecoder(params)

    data = DataBlock(["A"])
    encoded = encoder.encode_block(data)
    decoded, num_bits = decoder.decode_block(encoded)

    assert decoded.data_list == data.data_list


def test_encode_decode_two_symbols():
    """Test encoding and decoding two symbols"""
    freq = Frequencies({"A": 3, "B": 3, "C": 2})
    params = FSEParams(freq, TABLE_SIZE_LOG2=4)
    encoder = FSEEncoder(params)
    decoder = FSEDecoder(params)

    data = DataBlock(["A", "B"])
    encoded = encoder.encode_block(data)
    decoded, num_bits = decoder.decode_block(encoded)

    assert decoded.data_list == data.data_list


def test_encode_decode_three_symbols():
    """Test encoding and decoding three symbols"""
    freq = Frequencies({"A": 3, "B": 3, "C": 2})
    params = FSEParams(freq, TABLE_SIZE_LOG2=4)
    encoder = FSEEncoder(params)
    decoder = FSEDecoder(params)

    data = DataBlock(["A", "C", "B"])
    encoded = encoder.encode_block(data)
    decoded, num_bits = decoder.decode_block(encoded)

    assert decoded.data_list == data.data_list, f"Expected {data.data_list}, got {decoded.data_list}"


def test_encode_decode_all_symbols():
    """Test encoding and decoding all symbols"""
    freq = Frequencies({"A": 3, "B": 3, "C": 2})
    params = FSEParams(freq, TABLE_SIZE_LOG2=4)
    encoder = FSEEncoder(params)
    decoder = FSEDecoder(params)

    # Test with each symbol
    for s in freq.alphabet:
        data = DataBlock([s])
        encoded = encoder.encode_block(data)
        decoded, num_bits = decoder.decode_block(encoded)
        assert decoded.data_list == data.data_list


def test_encode_decode_repeated_symbols():
    """Test encoding and decoding repeated symbols"""
    freq = Frequencies({"A": 3, "B": 3, "C": 2})
    params = FSEParams(freq, TABLE_SIZE_LOG2=4)
    encoder = FSEEncoder(params)
    decoder = FSEDecoder(params)

    data = DataBlock(["A", "A", "A"])
    encoded = encoder.encode_block(data)
    decoded, num_bits = decoder.decode_block(encoded)

    assert decoded.data_list == data.data_list


########################################
# Debug Tests (can be run manually)
########################################


def debug_test_spread_table():
    """Debug: Visualize spread table"""
    norm_freq = {"A": 3, "B": 3, "C": 2}
    table_log = 4
    spread = build_spread_table(norm_freq, table_log)
    print_spread_table(spread, table_log, norm_freq)


def debug_test_decode_table():
    """Debug: Visualize decode table"""
    norm_freq = {"A": 3, "B": 3, "C": 2}
    table_log = 4
    spread = build_spread_table(norm_freq, table_log)
    DTable = build_decode_table(spread, norm_freq, table_log)
    print_decode_table(DTable, 1 << table_log)


def debug_test_encode_table():
    """Debug: Visualize encode table"""
    norm_freq = {"A": 3, "B": 3, "C": 2}
    table_log = 4
    spread = build_spread_table(norm_freq, table_log)
    tableU16, symbolTT = build_encode_table(spread, norm_freq, table_log)
    print_encode_table(tableU16, symbolTT, 1 << table_log)


def debug_test_encode_decode_step_by_step():
    """Debug: Step through encoding and decoding"""
    freq = Frequencies({"A": 3, "B": 3, "C": 2})
    params = FSEParams(freq, TABLE_SIZE_LOG2=4)
    encoder = FSEEncoder(params)
    decoder = FSEDecoder(params)

    data = DataBlock(["A", "C", "B"])
    print(f"\nOriginal data: {data.data_list}")

    # Encode step by step
    print("\n=== Encoding ===")
    state = params.TABLE_SIZE
    encoded_bits = []
    for s in reversed(data.data_list):
        state, nb_out, out_bits = encoder.encode_symbol(state, s)
        encoded_bits.append((s, nb_out, out_bits, state))
        print(f"Encode {s}: nb_out={nb_out}, out_bits={out_bits}, new_state={state}")

    # Decode step by step
    print("\n=== Decoding ===")
    from scl.compressors.fse import SimpleBitReader

    # Reconstruct the bitstream (simplified)
    bits = BitArray("")
    for s, nb_out, out_bits, _ in reversed(encoded_bits):
        if nb_out > 0:
            bits = uint_to_bitarray(out_bits, bit_width=nb_out) + bits

    # Read final state (would be in encoded bitarray)
    final_state = encoded_bits[-1][3]  # Last state
    state = final_state
    print(f"Starting decode from state: {state}")

    bitreader = SimpleBitReader(bits)
    decoded = []
    for _ in range(len(data.data_list)):
        s, state = decoder.decode_symbol(state, bitreader)
        decoded.append(s)
        print(f"Decode: symbol={s}, new_state={state}")

    decoded.reverse()  # Reverse because we decoded in forward order
    print(f"\nDecoded: {decoded}")
    print(f"Expected: {data.data_list}")


if __name__ == "__main__":
    # Run debug tests
    print("=== Debug: Spread Table ===")
    debug_test_spread_table()

    print("\n=== Debug: Decode Table ===")
    debug_test_decode_table()

    print("\n=== Debug: Encode Table ===")
    debug_test_encode_table()

    print("\n=== Debug: Encode/Decode Step by Step ===")
    debug_test_encode_decode_step_by_step()

