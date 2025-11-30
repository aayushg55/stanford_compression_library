"""Integration tests for FSE end-to-end encoding/decoding (Python + C++ parity)."""

import pytest

from scl.compressors.fse import FSEParams, FSEEncoder, FSEDecoder
from scl.core.prob_dist import Frequencies, get_avg_neg_log_prob
from scl.core.data_block import DataBlock
from scl.utils.test_utils import (
    get_random_data_block,
    try_lossless_compression,
    lossless_entropy_coder_test,
)
from scl.external_compressors.fse_cpp_wrapper import FSECppWrapper


def make_codec(impl, freq_dict, table_log, fse_cpp):
    """Return encoder/decoder plus a normalizer for the given impl."""
    if impl == "cpp":
        if fse_cpp is None:
            pytest.skip("scl_fse_cpp module not available")
        # Wrapper builds dense IDs for the C++ tables and maps symbols back.
        wrapper = FSECppWrapper(Frequencies(freq_dict), table_log)
        return wrapper, wrapper, lambda seq: list(seq)

    params = FSEParams(Frequencies(freq_dict), TABLE_SIZE_LOG2=table_log)
    enc = FSEEncoder(params)
    dec = FSEDecoder(params)
    return enc, dec, lambda seq: list(seq)


def roundtrip(enc, dec, data_list, impl):
    if impl == "cpp":
        encoded_bits = enc.encode_block(DataBlock(data_list))
        decoded_block, bits = dec.decode_block(encoded_bits)
        assert bits == len(encoded_bits)
        return decoded_block.data_list
    encoded = enc.encode_block(DataBlock(data_list))
    decoded, _ = dec.decode_block(encoded)
    return decoded.data_list


########################################
# Python Baseline Checks
########################################


@pytest.mark.parametrize(
    "freq_dict, table_log",
    [
        ({0: 3, 1: 3, 2: 2}, 8),
        ({0: 1, 1: 1}, 6),
        ({0: 5, 1: 5, 2: 5, 3: 1}, 10),
    ],
)
def test_python_roundtrip_larger_blocks(freq_dict, table_log):
    """Ensure the Python spec stays healthy before exercising the C++ path."""
    params = FSEParams(Frequencies(freq_dict), TABLE_SIZE_LOG2=table_log)
    enc = FSEEncoder(params)
    dec = FSEDecoder(params)

    prob_dist = Frequencies(freq_dict).get_prob_dist()
    data_block = get_random_data_block(prob_dist, 4000, seed=7)

    encoded = enc.encode_block(DataBlock(data_block.data_list))
    decoded, bits_consumed = dec.decode_block(encoded)

    assert bits_consumed == len(encoded)
    assert decoded.data_list == data_block.data_list


########################################
# Basic End-to-End Tests
########################################


@pytest.mark.parametrize("impl", ["python", "cpp"])
def test_encode_decode_single_symbol(impl, fse_cpp):
    freq = {0: 3, 1: 3, 2: 2}
    encoder, decoder, normalize = make_codec(impl, freq, 4, fse_cpp)
    data = normalize([0])
    decoded = roundtrip(encoder, decoder, data, impl)
    assert decoded == data


@pytest.mark.parametrize("impl", ["python", "cpp"])
def test_encode_decode_two_symbols(impl, fse_cpp):
    freq = {0: 3, 1: 3, 2: 2}
    encoder, decoder, normalize = make_codec(impl, freq, 4, fse_cpp)
    data = normalize([0, 1])
    decoded = roundtrip(encoder, decoder, data, impl)
    assert decoded == data


@pytest.mark.parametrize("impl", ["python", "cpp"])
def test_encode_decode_three_symbols(impl, fse_cpp):
    freq = {0: 3, 1: 3, 2: 2}
    encoder, decoder, normalize = make_codec(impl, freq, 4, fse_cpp)
    data = normalize([0, 2, 1])
    decoded = roundtrip(encoder, decoder, data, impl)
    assert decoded == data


@pytest.mark.parametrize("impl", ["python", "cpp"])
def test_encode_decode_all_symbols(impl, fse_cpp):
    freq = {0: 3, 1: 3, 2: 2}
    encoder, decoder, normalize = make_codec(impl, freq, 4, fse_cpp)
    for s in freq.keys():
        data = normalize([s])
        decoded = roundtrip(encoder, decoder, data, impl)
        assert decoded == data


@pytest.mark.parametrize("impl", ["python", "cpp"])
def test_encode_decode_repeated_symbols(impl, fse_cpp):
    freq = {0: 3, 1: 3, 2: 2}
    encoder, decoder, normalize = make_codec(impl, freq, 4, fse_cpp)
    data = normalize([0, 0, 0])
    decoded = roundtrip(encoder, decoder, data, impl)
    assert decoded == data


########################################
# Tests with Various Distributions
########################################


@pytest.mark.parametrize("impl", ["python", "cpp"])
def test_fse_coding_simple_distribution(impl, fse_cpp):
    freq = {0: 1, 1: 1, 2: 2}
    encoder, decoder, normalize = make_codec(impl, freq, 12, fse_cpp)
    prob_dist = Frequencies(freq).get_prob_dist()
    data_block = get_random_data_block(prob_dist, 1000, seed=0)
    data = normalize(list(data_block.data_list))
    decoded = roundtrip(encoder, decoder, data, impl)
    assert decoded == data


@pytest.mark.parametrize("impl", ["python", "cpp"])
def test_fse_coding_balanced_distribution(impl, fse_cpp):
    freq = {0: 3, 1: 3, 2: 2}
    encoder, decoder, normalize = make_codec(impl, freq, 12, fse_cpp)
    prob_dist = Frequencies(freq).get_prob_dist()
    data_block = get_random_data_block(prob_dist, 1000, seed=0)
    data = normalize(list(data_block.data_list))
    decoded = roundtrip(encoder, decoder, data, impl)
    assert decoded == data


@pytest.mark.parametrize("impl", ["python", "cpp"])
def test_fse_coding_uniform_distribution(impl, fse_cpp):
    freq = {0: 5, 1: 5, 2: 5, 3: 5}
    encoder, decoder, normalize = make_codec(impl, freq, 12, fse_cpp)
    prob_dist = Frequencies(freq).get_prob_dist()
    data_block = get_random_data_block(prob_dist, 1000, seed=0)
    data = normalize(list(data_block.data_list))
    decoded = roundtrip(encoder, decoder, data, impl)
    assert decoded == data


@pytest.mark.parametrize("impl", ["python", "cpp"])
def test_fse_coding_skewed_distribution(impl, fse_cpp):
    freq = {0: 1, 1: 3}
    encoder, decoder, normalize = make_codec(impl, freq, 12, fse_cpp)
    prob_dist = Frequencies(freq).get_prob_dist()
    data_block = get_random_data_block(prob_dist, 1000, seed=0)
    data = normalize(list(data_block.data_list))
    decoded = roundtrip(encoder, decoder, data, impl)
    assert decoded == data


########################################
# Tests with Different Table Sizes
########################################


@pytest.mark.parametrize("impl", ["python", "cpp"])
def test_fse_different_table_sizes(impl, fse_cpp):
    freq = {0: 3, 1: 3, 2: 2}
    for table_log in [6, 8, 12]:
        encoder, decoder, normalize = make_codec(impl, freq, table_log, fse_cpp)
        data = normalize([0, 2, 1, 0, 1, 2])
        decoded = roundtrip(encoder, decoder, data, impl)
        assert decoded == data


########################################
# Tests with Large Blocks
########################################


@pytest.mark.parametrize("impl", ["python", "cpp"])
def test_fse_large_block(impl, fse_cpp):
    freq = {0: 3, 1: 3, 2: 2, 3: 1}
    encoder, decoder, normalize = make_codec(impl, freq, 12, fse_cpp)
    prob_dist = Frequencies(freq).get_prob_dist()
    data_block = get_random_data_block(prob_dist, 10000, seed=0)
    data = normalize(list(data_block.data_list))
    decoded = roundtrip(encoder, decoder, data, impl)
    assert decoded == data
