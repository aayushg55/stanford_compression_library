"""Debug utilities for FSE implementation

Helper functions to visualize and debug FSE components.
"""

from scl.compressors.fse import (
    FSEParams,
    FSEEncoder,
    FSEDecoder,
    build_spread_table,
    build_decode_table,
    build_encode_table,
    SimpleBitReader,
)
from scl.core.prob_dist import Frequencies
from scl.core.data_block import DataBlock
from scl.utils.bitarray_utils import BitArray, uint_to_bitarray


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
    print("\nDecode Table (first 10 entries):")
    for i in range(min(10, table_size)):
        entry = DTable[i]
        print(
            f"  state[{i:3d}]: symbol={entry.symbol}, nb_bits={entry.nb_bits}, "
            f"new_state_base={entry.new_state_base}"
        )


def print_encode_table(tableU16, symbolTT, table_size):
    """Debug: Print encode table"""
    print("\nEncode Table:")
    print(f"  tableU16 (first 10): {tableU16[:10]}")
    print("  symbolTT:")
    for s, tt in symbolTT.items():
        print(
            f"    {s}: delta_nb_bits={tt.delta_nb_bits}, delta_find_state={tt.delta_find_state}"
        )


def debug_test_spread_table():
    """Debug: Visualize spread table"""
    freq = Frequencies({"A": 3, "B": 3, "C": 2})
    params = FSEParams(freq, TABLE_SIZE_LOG2=4)
    norm_freq = params.normalized_freqs
    table_log = 4
    spread = build_spread_table(norm_freq, table_log)
    print_spread_table(spread, table_log, norm_freq)


def debug_test_decode_table():
    """Debug: Visualize decode table"""
    freq = Frequencies({"A": 3, "B": 3, "C": 2})
    params = FSEParams(freq, TABLE_SIZE_LOG2=4)
    norm_freq = params.normalized_freqs
    table_log = 4
    spread = build_spread_table(norm_freq, table_log)
    DTable = build_decode_table(spread, norm_freq, table_log)
    print_decode_table(DTable, 1 << table_log)


def debug_test_encode_table():
    """Debug: Visualize encode table"""
    freq = Frequencies({"A": 3, "B": 3, "C": 2})
    params = FSEParams(freq, TABLE_SIZE_LOG2=4)
    norm_freq = params.normalized_freqs
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
