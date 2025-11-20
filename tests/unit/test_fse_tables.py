"""Unit tests for FSE table building (decode and encode tables).

These tests assume a canonical FSE-style implementation:

- Decode state is an index into DTable: 0 <= state < table_size.
- Decode step: state' = new_state_base + bits, bits in [0, 2^nb_bits).
- Encode state (tableU16 values) lives in [table_size, 2*table_size).

No modulo tricks on decode: DTable[state] expects state in [0, table_size).
"""

import pytest
from scl.compressors.fse import (
    FSEParams,
    build_spread_table,
    build_decode_table,
    build_encode_table,
    DecodeEntry,
    SymTransform,
)
from scl.core.prob_dist import Frequencies
from tests.conftest import TEST_FREQUENCIES, TEST_TABLE_LOGS


########################################
# Decode Table Tests
########################################


@pytest.mark.parametrize("freq_dict,table_log,description", TEST_FREQUENCIES)
def test_decode_table_size(freq_dict, table_log, description):
    """Decode table must have exactly 2^table_log entries."""
    freq = Frequencies(freq_dict)
    params = FSEParams(freq, TABLE_SIZE_LOG2=table_log)
    norm_freq = params.normalized_freqs
    spread = build_spread_table(norm_freq, table_log)
    dtable = build_decode_table(spread, norm_freq, table_log)

    assert len(dtable) == (1 << table_log), f"Failed for {description}"


@pytest.mark.parametrize("freq_dict,table_log,description", TEST_FREQUENCIES)
def test_decode_table_entries(freq_dict, table_log, description):
    """Each decode entry must be well-formed and produce states in [0, table_size)."""
    freq = Frequencies(freq_dict)
    params = FSEParams(freq, TABLE_SIZE_LOG2=table_log)
    norm_freq = params.normalized_freqs
    spread = build_spread_table(norm_freq, table_log)
    dtable = build_decode_table(spread, norm_freq, table_log)

    table_size = 1 << table_log

    for entry in dtable:
        # Basic type and symbol checks
        assert isinstance(entry, DecodeEntry), f"Failed for {description}"
        assert entry.symbol in norm_freq, f"Failed for {description}"

        # nb_bits must be in [0, table_log]
        assert (
            0 <= entry.nb_bits <= table_log
        ), f"Failed for {description}: nb_bits {entry.nb_bits} must be in [0, {table_log}]"

        # Decode step: state' = new_state_base + bits, bits in [0, 2^nb_bits)
        max_bits = (1 << entry.nb_bits) - 1 if entry.nb_bits > 0 else 0
        min_state = entry.new_state_base
        max_state = entry.new_state_base + max_bits

        # State must always be a valid index into DTable: [0, table_size)
        assert (
            0 <= min_state < table_size
        ), f"Failed for {description}: min_state {min_state} not in [0, {table_size})"
        assert (
            max_state < table_size
        ), f"Failed for {description}: max_state {max_state} >= table_size {table_size}"


@pytest.mark.parametrize("freq_dict,table_log,description", TEST_FREQUENCIES)
def test_decode_table_nb_bits_range(freq_dict, table_log, description):
    """nb_bits values in decode table must lie in [0, table_log]."""
    freq = Frequencies(freq_dict)
    params = FSEParams(freq, TABLE_SIZE_LOG2=table_log)
    norm_freq = params.normalized_freqs
    spread = build_spread_table(norm_freq, table_log)
    dtable = build_decode_table(spread, norm_freq, table_log)

    nb_bits_values = [entry.nb_bits for entry in dtable]
    assert all(
        0 <= nb <= table_log for nb in nb_bits_values
    ), f"{description}: Invalid nb_bits values {set(nb_bits_values)}"
    # We don't enforce k/(k+1) variation here; that is a compression-efficiency property
    # checked in integration/roundtrip tests, not in low-level table-shape tests.


@pytest.mark.parametrize("table_log", TEST_TABLE_LOGS)
def test_decode_table_different_table_sizes(table_log):
    """Decode table invariants must hold for multiple table_log values."""
    freq = Frequencies({"A": 3, "B": 3, "C": 2})
    params = FSEParams(freq, TABLE_SIZE_LOG2=table_log)
    norm_freq = params.normalized_freqs
    spread = build_spread_table(norm_freq, table_log)
    dtable = build_decode_table(spread, norm_freq, table_log)

    table_size = 1 << table_log
    assert len(dtable) == table_size

    for entry in dtable:
        max_bits = (1 << entry.nb_bits) - 1 if entry.nb_bits > 0 else 0
        min_state = entry.new_state_base
        max_state = entry.new_state_base + max_bits

        assert (
            0 <= min_state < table_size
        ), f"table_log {table_log}: min_state {min_state} not in [0, {table_size})"
        assert (
            max_state < table_size
        ), f"table_log {table_log}: max_state {max_state} >= table_size {table_size}"


def test_decode_table_single_symbol():
    """Single-symbol distribution: all decode entries should decode to that symbol.

    For canonical FSE, decode states stay in [0, table_size).
    nb_bits is typically 0 in this degenerate case, but we only enforce range.
    """
    freq = Frequencies({"A": 10})
    table_log = 4
    params = FSEParams(freq, TABLE_SIZE_LOG2=table_log)
    norm_freq = params.normalized_freqs
    spread = build_spread_table(norm_freq, table_log)
    dtable = build_decode_table(spread, norm_freq, table_log)

    table_size = 1 << table_log
    assert len(dtable) == table_size

    for entry in dtable:
        assert entry.symbol == "A"
        assert 0 <= entry.new_state_base < table_size
        assert 0 <= entry.nb_bits <= table_log


########################################
# Encode Table Tests
########################################


@pytest.mark.parametrize("freq_dict,table_log,description", TEST_FREQUENCIES)
def test_encode_table_structure(freq_dict, table_log, description):
    """Encode table must have correct shape and encoder states in [table_size, 2*table_size)."""
    freq = Frequencies(freq_dict)
    params = FSEParams(freq, TABLE_SIZE_LOG2=table_log)
    norm_freq = params.normalized_freqs
    spread = build_spread_table(norm_freq, table_log)
    table_u16, symbol_tt = build_encode_table(spread, norm_freq, table_log)

    table_size = 1 << table_log
    assert len(table_u16) == table_size, f"Failed for {description}"
    assert len(symbol_tt) == len(norm_freq), f"Failed for {description}"

    # Canonical FSE: tableU16 entries are encoder states in [tableSize, 2*tableSize).
    for val in table_u16:
        assert table_size <= val < 2 * table_size, (
            f"{description}: Invalid tableU16 value {val}, "
            f"should be in [{table_size}, {2 * table_size})"
        )


@pytest.mark.parametrize("freq_dict,table_log,description", TEST_FREQUENCIES)
def test_encode_table_symbol_transforms(freq_dict, table_log, description):
    """Symbol transform entries must be well-formed and reasonably bounded."""
    freq = Frequencies(freq_dict)
    params = FSEParams(freq, TABLE_SIZE_LOG2=table_log)
    norm_freq = params.normalized_freqs
    spread = build_spread_table(norm_freq, table_log)
    table_u16, symbol_tt = build_encode_table(spread, norm_freq, table_log)

    table_size = 1 << table_log

    for s, tt in symbol_tt.items():
        assert isinstance(tt, SymTransform), f"Failed for {description}"
        # delta_find_state is an offset into tableU16; expect it to be in a sane range
        assert (
            -table_size <= tt.delta_find_state <= table_size
        ), f"{description}: Invalid delta_find_state {tt.delta_find_state} for symbol {s}"
        # delta_nb_bits is used to compute nbBitsOut = (state + delta_nb_bits) >> 16.
        # We don't assert a numeric bound here, just its existence; correctness is
        # exercised indirectly via encode/decode roundtrip tests.


@pytest.mark.parametrize("freq_dict,table_log,description", TEST_FREQUENCIES)
def test_encode_decode_symbol_coverage(freq_dict, table_log, description):
    """All symbols used to build the encode table must also appear in the decode table.

    This is a coverage sanity check. Full encode/decode consistency is verified
    in higher-level roundtrip tests.
    """
    freq = Frequencies(freq_dict)
    params = FSEParams(freq, TABLE_SIZE_LOG2=table_log)
    norm_freq = params.normalized_freqs
    spread = build_spread_table(norm_freq, table_log)
    dtable = build_decode_table(spread, norm_freq, table_log)
    table_u16, symbol_tt = build_encode_table(spread, norm_freq, table_log)

    symbols_in_decode = {entry.symbol for entry in dtable}
    for s in norm_freq:
        assert s in symbols_in_decode, (
            f"{description}: Symbol {s} from encode-side frequencies "
            f"does not appear in decode table"
        )


@pytest.mark.parametrize("table_log", TEST_TABLE_LOGS)
def test_encode_table_different_table_sizes(table_log):
    """Encode table structural properties must hold for multiple table_log values."""
    freq = Frequencies({"A": 3, "B": 3, "C": 2})
    params = FSEParams(freq, TABLE_SIZE_LOG2=table_log)
    norm_freq = params.normalized_freqs
    spread = build_spread_table(norm_freq, table_log)
    table_u16, symbol_tt = build_encode_table(spread, norm_freq, table_log)

    table_size = 1 << table_log
    assert len(table_u16) == table_size
    assert len(symbol_tt) == len(norm_freq)

    for val in table_u16:
        assert table_size <= val < 2 * table_size


def test_encode_table_single_symbol():
    """Single-symbol distribution: encode table must be structurally sound."""
    freq = Frequencies({"A": 10})
    table_log = 4
    params = FSEParams(freq, TABLE_SIZE_LOG2=table_log)
    norm_freq = params.normalized_freqs
    spread = build_spread_table(norm_freq, table_log)
    table_u16, symbol_tt = build_encode_table(spread, norm_freq, table_log)

    table_size = 1 << table_log
    assert len(symbol_tt) == 1
    assert "A" in symbol_tt
    assert len(table_u16) == table_size

    for val in table_u16:
        assert (
            table_size <= val < 2 * table_size
        ), f"tableU16 value {val} should be in [{table_size}, {2 * table_size})"

    # We don't enforce a specific delta_nb_bits here; that depends on normalization.
    # Single-symbol encode behavior is exercised via roundtrip tests.
