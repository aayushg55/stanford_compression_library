"""Unit tests for individual symbol encoding/decoding operations.

These tests verify state transitions and bit output:

- Encode state lives in [TABLE_SIZE, 2*TABLE_SIZE).
- Decode state lives in [0, TABLE_SIZE).
- encode_symbol(state, s) returns (new_state, nb_out, out_bits)
  with new_state in encode range.
- decode_symbol(state, bitreader) returns (symbol, new_state)
  with state and new_state in decode range.
"""

import pytest
from scl.compressors.fse import FSEParams, FSEEncoder, FSEDecoder, SimpleBitReader
from scl.core.prob_dist import Frequencies
from scl.utils.bitarray_utils import BitArray
from tests.conftest import TEST_FREQUENCIES, TEST_TABLE_LOGS


########################################
# Test Data for Parameterization
########################################

TEST_SYMBOL_SEQUENCES = [
    (["A"], "single_A"),
    (["A", "B"], "two_different"),
    (["A", "A", "A"], "repeated"),
    (["A", "B", "C"], "all_symbols"),
    (["A", "B", "A", "B"], "alternating"),
    (["C", "C", "B", "A"], "mixed"),
]


########################################
# Encode: individual symbols
########################################


@pytest.mark.parametrize("freq_dict,table_log,description", TEST_FREQUENCIES)
def test_encode_symbol_state_transitions(freq_dict, table_log, description):
    """Encoding a symbol must keep the state in [TABLE_SIZE, 2*TABLE_SIZE)."""
    freq = Frequencies(freq_dict)
    params = FSEParams(freq, TABLE_SIZE_LOG2=table_log)
    encoder = FSEEncoder(params)

    for s in freq.alphabet:
        state = params.TABLE_SIZE
        new_state, nb_out, out_bits = encoder.encode_symbol(state, s)

        # State stays in encode range
        assert (
            params.TABLE_SIZE <= new_state < 2 * params.TABLE_SIZE
        ), f"{description}: Invalid state {new_state} for symbol {s}"

        # nb_out is non-negative and reasonably bounded
        assert nb_out >= 0
        # out_bits must fit in nb_out bits
        if nb_out > 0:
            assert (
                0 <= out_bits < (1 << nb_out)
            ), f"{description}: Invalid out_bits {out_bits} for nb_out {nb_out}"
        else:
            assert out_bits == 0, f"{description}: With nb_out=0, out_bits should be 0"


@pytest.mark.parametrize("freq_dict,table_log,description", TEST_FREQUENCIES)
@pytest.mark.parametrize("symbols,seq_description", TEST_SYMBOL_SEQUENCES)
def test_encode_symbol_multiple_steps(
    freq_dict, table_log, description, symbols, seq_description
):
    """Multiple encode steps must keep state in encode range."""
    freq = Frequencies(freq_dict)
    params = FSEParams(freq, TABLE_SIZE_LOG2=table_log)
    encoder = FSEEncoder(params)

    # Only keep symbols present in this alphabet
    valid_symbols = [s for s in symbols if s in freq.alphabet]
    if not valid_symbols:
        pytest.skip(f"No valid symbols in sequence for {description}")

    state = params.TABLE_SIZE
    for s in valid_symbols:
        state, nb_out, out_bits = encoder.encode_symbol(state, s)
        assert (
            params.TABLE_SIZE <= state < 2 * params.TABLE_SIZE
        ), f"{description}/{seq_description}: Invalid state {state} after encoding {s}"


@pytest.mark.parametrize("freq_dict,table_log,description", TEST_FREQUENCIES)
def test_encode_symbol_state_dependent_bits(freq_dict, table_log, description):
    """For each symbol, nb_out should have at most 2 distinct consecutive values."""
    freq = Frequencies(freq_dict)
    params = FSEParams(freq, TABLE_SIZE_LOG2=table_log)
    encoder = FSEEncoder(params)

    if not freq.alphabet:
        pytest.skip("No symbols to test")

    # For each symbol, collect nb_out values across different states
    for symbol in freq.alphabet:
        nb_outs_dict = {}  # Dictionary to track nb_out values for this symbol

        # Sample encode states within [TABLE_SIZE, 2*TABLE_SIZE)
        max_samples = min(params.TABLE_SIZE, 32)
        for offset in range(0, max_samples):
            state = params.TABLE_SIZE + offset
            if state < 2 * params.TABLE_SIZE:
                _, nb_out, _ = encoder.encode_symbol(state, symbol)
                nb_outs_dict[nb_out] = nb_outs_dict.get(nb_out, 0) + 1

        # Check: should have at most 2 distinct nb_out values
        unique_nb_outs = sorted(nb_outs_dict.keys())
        assert (
            len(unique_nb_outs) <= 2
        ), f"{description}, symbol {symbol}: Expected at most 2 distinct nb_out values, got {unique_nb_outs}"

        # Check: if there are 2 values, they should be consecutive
        if len(unique_nb_outs) == 2:
            assert (
                abs(unique_nb_outs[1] - unique_nb_outs[0]) == 1
            ), f"{description}, symbol {symbol}: Expected consecutive nb_out values, got {unique_nb_outs}"

        # Check: all values should be non-negative
        assert all(
            nb >= 0 for nb in unique_nb_outs
        ), f"{description}, symbol {symbol}: All nb_out values must be non-negative, got {unique_nb_outs}"


########################################
# Decode: individual symbols
########################################


@pytest.mark.parametrize("freq_dict,table_log,description", TEST_FREQUENCIES)
def test_decode_symbol_state_transitions(freq_dict, table_log, description):
    """Decoding from valid decode states must keep state in [0, TABLE_SIZE)."""
    freq = Frequencies(freq_dict)
    params = FSEParams(freq, TABLE_SIZE_LOG2=table_log)
    decoder = FSEDecoder(params)

    table_size = params.TABLE_SIZE
    max_nb_bits = table_log

    # Enough bits for multiple decodes; exact bit pattern not important here
    bits = BitArray("1" * (max_nb_bits * 20))
    bitreader = SimpleBitReader(bits)

    for state in range(0, min(8, table_size)):
        try:
            s, new_state = decoder.decode_symbol(state, bitreader)

            assert (
                s in freq.alphabet
            ), f"{description}: Invalid symbol {s} decoded from state {state}"
            assert (
                0 <= new_state < table_size
            ), f"{description}: Invalid new_state {new_state} after decoding {s}"
        except Exception as e:
            # Running out of bits is fine for this low-level test
            if "not enough bits" in str(e).lower() or "index" in str(e).lower():
                break
            raise


@pytest.mark.parametrize("freq_dict,table_log,description", TEST_FREQUENCIES)
def test_decode_symbol_all_states(freq_dict, table_log, description):
    """Decoding from several decode states must keep state in [0, TABLE_SIZE)."""
    freq = Frequencies(freq_dict)
    params = FSEParams(freq, TABLE_SIZE_LOG2=table_log)
    decoder = FSEDecoder(params)

    table_size = params.TABLE_SIZE
    max_nb_bits = table_log
    bits = BitArray("1" * (max_nb_bits * table_size))
    bitreader = SimpleBitReader(bits)

    # Exercise a prefix of all possible decode states
    for state in range(0, min(table_size, 16)):
        s, new_state = decoder.decode_symbol(state, bitreader)
        assert s in freq.alphabet
        assert 0 <= new_state < table_size


########################################
# Encode-side local correctness
########################################


@pytest.mark.parametrize("freq_dict,table_log,description", TEST_FREQUENCIES)
def test_encode_symbol_local_validity(freq_dict, table_log, description):
    """Encoding must produce a valid next state and valid bit payload."""
    freq = Frequencies(freq_dict)
    params = FSEParams(freq, TABLE_SIZE_LOG2=table_log)
    encoder = FSEEncoder(params)

    for original_symbol in freq.alphabet:
        state = params.TABLE_SIZE
        new_state, nb_out, out_bits = encoder.encode_symbol(state, original_symbol)

        assert (
            params.TABLE_SIZE <= new_state < 2 * params.TABLE_SIZE
        ), f"{description}: Invalid state after encoding {original_symbol}"

        if nb_out > 0:
            assert (
                0 <= out_bits < (1 << nb_out)
            ), f"{description}: Invalid out_bits for {original_symbol}"
        else:
            assert out_bits == 0


########################################
# Edge cases
########################################


def test_encode_symbol_single_symbol():
    """Encoding with a single-symbol alphabet (degenerate case)."""
    freq = Frequencies({"A": 10})
    params = FSEParams(freq, TABLE_SIZE_LOG2=4)
    encoder = FSEEncoder(params)

    state = params.TABLE_SIZE
    new_state, nb_out, out_bits = encoder.encode_symbol(state, "A")

    assert params.TABLE_SIZE <= new_state < 2 * params.TABLE_SIZE
    assert nb_out >= 0
    if nb_out > 0:
        assert 0 <= out_bits < (1 << nb_out)
    else:
        assert out_bits == 0


def test_decode_symbol_single_symbol():
    """Decoding with a single-symbol alphabet (degenerate case)."""
    freq = Frequencies({"A": 10})
    params = FSEParams(freq, TABLE_SIZE_LOG2=4)
    decoder = FSEDecoder(params)

    table_size = params.TABLE_SIZE
    bits = BitArray("1111")
    bitreader = SimpleBitReader(bits)

    state = 0  # any decode state in [0, table_size)
    s, new_state = decoder.decode_symbol(state, bitreader)

    assert s == "A"
    assert 0 <= new_state < table_size


@pytest.mark.parametrize("table_log", TEST_TABLE_LOGS)
def test_encode_symbol_different_table_sizes(table_log):
    """Encoding must behave correctly across table sizes."""
    freq = Frequencies({"A": 3, "B": 3, "C": 2})
    params = FSEParams(freq, TABLE_SIZE_LOG2=table_log)
    encoder = FSEEncoder(params)

    for s in freq.alphabet:
        state = params.TABLE_SIZE
        new_state, nb_out, out_bits = encoder.encode_symbol(state, s)
        assert params.TABLE_SIZE <= new_state < 2 * params.TABLE_SIZE


@pytest.mark.parametrize("table_log", TEST_TABLE_LOGS)
def test_decode_symbol_different_table_sizes(table_log):
    """Decoding must behave correctly across table sizes."""
    freq = Frequencies({"A": 3, "B": 3, "C": 2})
    params = FSEParams(freq, TABLE_SIZE_LOG2=table_log)
    decoder = FSEDecoder(params)

    table_size = params.TABLE_SIZE
    max_nb_bits = table_log
    bits = BitArray("1" * (max_nb_bits * 2))
    bitreader = SimpleBitReader(bits)

    state = 0
    s, new_state = decoder.decode_symbol(state, bitreader)

    assert s in freq.alphabet
    assert 0 <= new_state < table_size


def test_encode_symbol_extreme_states(basic_encoder, basic_params, basic_freq):
    """Encoding from extreme encode states must stay in [TABLE_SIZE, 2*TABLE_SIZE)."""
    # Minimum encode state
    state_min = basic_params.TABLE_SIZE
    for s in basic_freq.alphabet:
        new_state, _, _ = basic_encoder.encode_symbol(state_min, s)
        assert basic_params.TABLE_SIZE <= new_state < 2 * basic_params.TABLE_SIZE

    # Maximum encode state
    state_max = 2 * basic_params.TABLE_SIZE - 1
    for s in basic_freq.alphabet:
        new_state, _, _ = basic_encoder.encode_symbol(state_max, s)
        assert basic_params.TABLE_SIZE <= new_state < 2 * basic_params.TABLE_SIZE


def test_decode_symbol_extreme_states(basic_decoder, basic_params, basic_freq):
    """Decoding from extreme decode states must stay in [0, TABLE_SIZE)."""
    table_size = basic_params.TABLE_SIZE
    bits = BitArray("11111111")
    bitreader = SimpleBitReader(bits)

    # Minimum decode state
    state_min = 0
    s, new_state = basic_decoder.decode_symbol(state_min, bitreader)
    assert s in basic_freq.alphabet
    assert 0 <= new_state < table_size

    # Maximum decode state
    state_max = table_size - 1
    bitreader2 = SimpleBitReader(bits)
    s, new_state = basic_decoder.decode_symbol(state_max, bitreader2)
    assert s in basic_freq.alphabet
    assert 0 <= new_state < table_size
