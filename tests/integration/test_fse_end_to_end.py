"""Integration tests for FSE end-to-end encoding/decoding

Tests full block encoding and decoding with various scenarios.
Uses test_utils functions for consistency with other codecs.
"""

from scl.compressors.fse import FSEParams, FSEEncoder, FSEDecoder
from scl.core.prob_dist import Frequencies, get_avg_neg_log_prob
from scl.core.data_block import DataBlock
from scl.utils.test_utils import (
    get_random_data_block,
    try_lossless_compression,
    lossless_entropy_coder_test,
)


########################################
# Basic End-to-End Tests
########################################


def test_encode_decode_single_symbol():
    """Test encoding and decoding a single symbol using try_lossless_compression"""
    freq = Frequencies({"A": 3, "B": 3, "C": 2})
    params = FSEParams(freq, TABLE_SIZE_LOG2=4)
    encoder = FSEEncoder(params)
    decoder = FSEDecoder(params)

    data = DataBlock(["A"])
    # Use try_lossless_compression for consistency (uses are_blocks_equal internally)
    is_lossless, encode_len, _ = try_lossless_compression(
        data, encoder, decoder, add_extra_bits_to_encoder_output=True
    )
    assert is_lossless, "FSE encoding/decoding must be lossless"


def test_encode_decode_two_symbols():
    """Test encoding and decoding two symbols using try_lossless_compression"""
    freq = Frequencies({"A": 3, "B": 3, "C": 2})
    params = FSEParams(freq, TABLE_SIZE_LOG2=4)
    encoder = FSEEncoder(params)
    decoder = FSEDecoder(params)

    data = DataBlock(["A", "B"])
    is_lossless, encode_len, _ = try_lossless_compression(
        data, encoder, decoder, add_extra_bits_to_encoder_output=True
    )
    assert is_lossless


def test_encode_decode_three_symbols():
    """Test encoding and decoding three symbols using try_lossless_compression"""
    freq = Frequencies({"A": 3, "B": 3, "C": 2})
    params = FSEParams(freq, TABLE_SIZE_LOG2=4)
    encoder = FSEEncoder(params)
    decoder = FSEDecoder(params)

    data = DataBlock(["A", "C", "B"])
    is_lossless, encode_len, _ = try_lossless_compression(
        data, encoder, decoder, add_extra_bits_to_encoder_output=True
    )
    assert is_lossless


def test_encode_decode_all_symbols():
    """Test encoding and decoding all symbols individually using try_lossless_compression"""
    freq = Frequencies({"A": 3, "B": 3, "C": 2})
    params = FSEParams(freq, TABLE_SIZE_LOG2=4)
    encoder = FSEEncoder(params)
    decoder = FSEDecoder(params)

    # Test with each symbol
    for s in freq.alphabet:
        data = DataBlock([s])
        is_lossless, _, _ = try_lossless_compression(
            data, encoder, decoder, add_extra_bits_to_encoder_output=True
        )
        assert is_lossless


def test_encode_decode_repeated_symbols():
    """Test encoding and decoding repeated symbols using try_lossless_compression"""
    freq = Frequencies({"A": 3, "B": 3, "C": 2})
    params = FSEParams(freq, TABLE_SIZE_LOG2=4)
    encoder = FSEEncoder(params)
    decoder = FSEDecoder(params)

    data = DataBlock(["A", "A", "A"])
    is_lossless, _, _ = try_lossless_compression(
        data, encoder, decoder, add_extra_bits_to_encoder_output=True
    )
    assert is_lossless


########################################
# Tests with Various Distributions
########################################


def test_fse_coding_simple_distribution():
    """Test FSE coding on simple distribution"""
    freq = Frequencies({"A": 1, "B": 1, "C": 2})
    params = FSEParams(freq, TABLE_SIZE_LOG2=12)  # Use default table size
    encoder = FSEEncoder(params)
    decoder = FSEDecoder(params)

    # Generate random data
    prob_dist = freq.get_prob_dist()
    data_block = get_random_data_block(prob_dist, 1000, seed=0)

    # Test lossless compression
    is_lossless, encode_len, _ = try_lossless_compression(
        data_block, encoder, decoder, add_extra_bits_to_encoder_output=True
    )
    assert is_lossless, "FSE encoding/decoding must be lossless"


def test_fse_coding_balanced_distribution():
    """Test FSE coding on balanced distribution"""
    freq = Frequencies({"A": 3, "B": 3, "C": 2})
    params = FSEParams(freq, TABLE_SIZE_LOG2=12)
    encoder = FSEEncoder(params)
    decoder = FSEDecoder(params)

    prob_dist = freq.get_prob_dist()
    data_block = get_random_data_block(prob_dist, 1000, seed=0)

    is_lossless, encode_len, _ = try_lossless_compression(
        data_block, encoder, decoder, add_extra_bits_to_encoder_output=True
    )
    assert is_lossless


def test_fse_coding_uniform_distribution():
    """Test FSE coding on uniform distribution"""
    freq = Frequencies({"A": 5, "B": 5, "C": 5, "D": 5})
    params = FSEParams(freq, TABLE_SIZE_LOG2=12)
    encoder = FSEEncoder(params)
    decoder = FSEDecoder(params)

    prob_dist = freq.get_prob_dist()
    data_block = get_random_data_block(prob_dist, 1000, seed=0)

    is_lossless, encode_len, _ = try_lossless_compression(
        data_block, encoder, decoder, add_extra_bits_to_encoder_output=True
    )
    assert is_lossless


def test_fse_coding_skewed_distribution():
    """Test FSE coding on skewed distribution"""
    freq = Frequencies({"A": 1, "B": 3})
    params = FSEParams(freq, TABLE_SIZE_LOG2=12)
    encoder = FSEEncoder(params)
    decoder = FSEDecoder(params)

    prob_dist = freq.get_prob_dist()
    data_block = get_random_data_block(prob_dist, 1000, seed=0)

    is_lossless, encode_len, _ = try_lossless_compression(
        data_block, encoder, decoder, add_extra_bits_to_encoder_output=True
    )
    assert is_lossless


########################################
# Tests with Different Table Sizes
########################################


def test_fse_different_table_sizes():
    """Test FSE with different table sizes using try_lossless_compression"""
    freq = Frequencies({"A": 3, "B": 3, "C": 2})

    for table_log in [6, 8, 12]:
        params = FSEParams(freq, TABLE_SIZE_LOG2=table_log)
        encoder = FSEEncoder(params)
        decoder = FSEDecoder(params)

        data = DataBlock(["A", "C", "B", "A", "B", "C"])
        is_lossless, _, _ = try_lossless_compression(
            data, encoder, decoder, add_extra_bits_to_encoder_output=True
        )
        assert is_lossless


########################################
# Tests with Large Blocks
########################################


def test_fse_large_block():
    """Test FSE with large data block"""
    freq = Frequencies({"A": 3, "B": 3, "C": 2, "D": 1})
    params = FSEParams(freq, TABLE_SIZE_LOG2=12)
    encoder = FSEEncoder(params)
    decoder = FSEDecoder(params)

    # Generate large block
    prob_dist = freq.get_prob_dist()
    data_block = get_random_data_block(prob_dist, 10000, seed=0)

    is_lossless, encode_len, _ = try_lossless_compression(
        data_block, encoder, decoder, add_extra_bits_to_encoder_output=True
    )
    assert is_lossless

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
