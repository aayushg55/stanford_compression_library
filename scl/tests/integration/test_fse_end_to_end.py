"""Integration tests for FSE end-to-end encoding/decoding."""

import pytest

from scl.compressors.fse import FSEParams, FSEEncoder, FSEDecoder
from scl.core.prob_dist import Frequencies, get_avg_neg_log_prob
from scl.core.data_block import DataBlock
from scl.utils.test_utils import (
    get_random_data_block,
    try_lossless_compression,
    lossless_entropy_coder_test,
)


def make_codec(impl, freq_dict, table_log, fse_cpp):
    if impl == "cpp":
        if fse_cpp is None:
            pytest.skip("scl_fse_cpp module not available")
        counts_vec = [0] * 256
        for sym, c in freq_dict.items():
            counts_vec[int(sym)] = c
        params = fse_cpp.FSEParams(counts_vec, table_log)
        tables = fse_cpp.FSETables(params)
        enc = fse_cpp.FSEEncoder(tables)
        dec = fse_cpp.FSEDecoder(tables)
        return enc, dec

    params = FSEParams(Frequencies(freq_dict), TABLE_SIZE_LOG2=table_log)
    return FSEEncoder(params), FSEDecoder(params)


def roundtrip(enc, dec, data_list, impl):
    if impl == "cpp":
        encoded = enc.encode_block(data_list)
        decoded, bits = dec.decode_block(encoded.bytes)
        assert bits == encoded.bit_count
        return decoded
    encoded = enc.encode_block(DataBlock(data_list))
    decoded, _ = dec.decode_block(encoded)
    return decoded.data_list


########################################
# Basic End-to-End Tests
########################################


@pytest.mark.parametrize("impl", ["python", "cpp"])
def test_encode_decode_single_symbol(impl, fse_cpp):
    """Test encoding and decoding a single symbol using try_lossless_compression"""
    freq = {0: 3, 1: 3, 2: 2}
    encoder, decoder = make_codec(impl, freq, 4, fse_cpp)
    data = [0]
    decoded = roundtrip(encoder, decoder, data, impl)
    assert decoded == data


@pytest.mark.parametrize("impl", ["python", "cpp"])
def test_encode_decode_two_symbols(impl, fse_cpp):
    """Test encoding and decoding two symbols using try_lossless_compression"""
    freq = {0: 3, 1: 3, 2: 2}
    encoder, decoder = make_codec(impl, freq, 4, fse_cpp)
    data = [0, 1]
    decoded = roundtrip(encoder, decoder, data, impl)
    assert decoded == data


@pytest.mark.parametrize("impl", ["python", "cpp"])
def test_encode_decode_three_symbols(impl, fse_cpp):
    """Test encoding and decoding three symbols using try_lossless_compression"""
    freq = {0: 3, 1: 3, 2: 2}
    encoder, decoder = make_codec(impl, freq, 4, fse_cpp)
    data = [0, 2, 1]
    decoded = roundtrip(encoder, decoder, data, impl)
    assert decoded == data


@pytest.mark.parametrize("impl", ["python", "cpp"])
def test_encode_decode_all_symbols(impl, fse_cpp):
    """Test encoding and decoding all symbols individually using try_lossless_compression"""
    freq = {0: 3, 1: 3, 2: 2}
    encoder, decoder = make_codec(impl, freq, 4, fse_cpp)
    for s in freq.keys():
        data = [s]
        decoded = roundtrip(encoder, decoder, data, impl)
        assert decoded == data


@pytest.mark.parametrize("impl", ["python", "cpp"])
def test_encode_decode_repeated_symbols(impl, fse_cpp):
    """Test encoding and decoding repeated symbols using try_lossless_compression"""
    freq = {0: 3, 1: 3, 2: 2}
    encoder, decoder = make_codec(impl, freq, 4, fse_cpp)
    data = [0, 0, 0]
    decoded = roundtrip(encoder, decoder, data, impl)
    assert decoded == data


########################################
# Tests with Various Distributions
########################################


@pytest.mark.parametrize("impl", ["python", "cpp"])
def test_fse_coding_simple_distribution(impl, fse_cpp):
    """Test FSE coding on simple distribution"""
    freq = {0: 1, 1: 1, 2: 2}
    encoder, decoder = make_codec(impl, freq, 12, fse_cpp)
    prob_dist = Frequencies(freq).get_prob_dist()
    data_block = get_random_data_block(prob_dist, 1000, seed=0)
    data = list(data_block.data_list)
    decoded = roundtrip(encoder, decoder, data, impl)
    assert decoded == data


@pytest.mark.parametrize("impl", ["python", "cpp"])
def test_fse_coding_balanced_distribution(impl, fse_cpp):
    """Test FSE coding on balanced distribution"""
    freq = {0: 3, 1: 3, 2: 2}
    encoder, decoder = make_codec(impl, freq, 12, fse_cpp)
    prob_dist = Frequencies(freq).get_prob_dist()
    data_block = get_random_data_block(prob_dist, 1000, seed=0)
    data = list(data_block.data_list)
    decoded = roundtrip(encoder, decoder, data, impl)
    assert decoded == data


@pytest.mark.parametrize("impl", ["python", "cpp"])
def test_fse_coding_uniform_distribution(impl, fse_cpp):
    """Test FSE coding on uniform distribution"""
    freq = {0: 5, 1: 5, 2: 5, 3: 5}
    encoder, decoder = make_codec(impl, freq, 12, fse_cpp)
    prob_dist = Frequencies(freq).get_prob_dist()
    data_block = get_random_data_block(prob_dist, 1000, seed=0)
    data = list(data_block.data_list)
    decoded = roundtrip(encoder, decoder, data, impl)
    assert decoded == data


@pytest.mark.parametrize("impl", ["python", "cpp"])
def test_fse_coding_skewed_distribution(impl, fse_cpp):
    """Test FSE coding on skewed distribution"""
    freq = {0: 1, 1: 3}
    encoder, decoder = make_codec(impl, freq, 12, fse_cpp)
    prob_dist = Frequencies(freq).get_prob_dist()
    data_block = get_random_data_block(prob_dist, 1000, seed=0)
    data = list(data_block.data_list)
    decoded = roundtrip(encoder, decoder, data, impl)
    assert decoded == data


########################################
# Tests with Different Table Sizes
########################################


@pytest.mark.parametrize("impl", ["python", "cpp"])
def test_fse_different_table_sizes(impl, fse_cpp):
    """Test FSE with different table sizes using try_lossless_compression"""
    freq = {0: 3, 1: 3, 2: 2}

    for table_log in [6, 8, 12]:
        encoder, decoder = make_codec(impl, freq, table_log, fse_cpp)
        data = [0, 2, 1, 0, 1, 2]
        decoded = roundtrip(encoder, decoder, data, impl)
        assert decoded == data


########################################
# Tests with Large Blocks
########################################


@pytest.mark.parametrize("impl", ["python", "cpp"])
def test_fse_large_block(impl, fse_cpp):
    """Test FSE with large data block"""
    freq = {0: 3, 1: 3, 2: 2, 3: 1}
    encoder, decoder = make_codec(impl, freq, 12, fse_cpp)
    prob_dist = Frequencies(freq).get_prob_dist()
    data_block = get_random_data_block(prob_dist, 10000, seed=0)
    data = list(data_block.data_list)
    decoded = roundtrip(encoder, decoder, data, impl)
    assert decoded == data

    # Check compression ratio is reasonable
    avg_codelen = encode_len / data_block.size
    avg_log_prob = get_avg_neg_log_prob(prob_dist, data_block)
    # FSE should be close to entropy (within reasonable margin)
    assert avg_codelen < avg_log_prob + 0.1, "FSE should compress close to entropy"


def test_fse_empty_block():
    """Test FSE with empty block using try_lossless_compression"""
    freq = Frequencies({"A": 3, "B": 3, "C": 2})
    params = FSEParams(freq, TABLE_SIZE_LOG2=4)
    encoder = FSEEncoder(params)
    decoder = FSEDecoder(params)

    data = DataBlock([])
    is_lossless, _, _ = try_lossless_compression(
        data, encoder, decoder, add_extra_bits_to_encoder_output=True
    )
    assert is_lossless
    # Note: empty block encodes to empty bitarray, so decoder handles it specially


########################################
# Compression Efficiency Tests
########################################


def test_fse_compression_efficiency():
    """Test that FSE achieves reasonable compression"""
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
        # FSE should compress reasonably close to entropy
        # Allow some overhead for table size, block size header, etc.
        assert (
            avg_codelen < avg_log_prob + 0.2
        ), f"FSE codelen {avg_codelen:.3f} should be close to entropy {avg_log_prob:.3f}"


########################################
# Lossless Entropy Coder Tests
########################################


def test_fse_lossless_entropy_coder_basic():
    """Test FSE using lossless_entropy_coder_test utility"""
    freq = Frequencies({"A": 3, "B": 3, "C": 2})
    params = FSEParams(freq, TABLE_SIZE_LOG2=12)
    encoder = FSEEncoder(params)
    decoder = FSEDecoder(params)

    # Use lossless_entropy_coder_test which checks both losslessness and optimality
    lossless_entropy_coder_test(
        encoder,
        decoder,
        freq,
        data_size=10000,
        encoding_optimality_precision=0.2,
        seed=0,
    )


def test_fse_lossless_entropy_coder_multiple_distributions():
    """Test FSE with multiple distributions using lossless_entropy_coder_test"""
    freqs_list = [
        Frequencies({"A": 1, "B": 1, "C": 2}),
        Frequencies({"A": 12, "B": 34, "C": 1, "D": 45}),
        Frequencies({"A": 5, "B": 5, "C": 5, "D": 5, "E": 5, "F": 5}),
    ]

    for freq in freqs_list:
        params = FSEParams(freq, TABLE_SIZE_LOG2=12)
        encoder = FSEEncoder(params)
        decoder = FSEDecoder(params)

        lossless_entropy_coder_test(
            encoder,
            decoder,
            freq,
            data_size=10000,
            encoding_optimality_precision=0.2,
            seed=0,
        )
