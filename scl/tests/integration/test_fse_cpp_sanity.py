"""Minimal C++ FSE sanity checks driven from Python."""

import pytest

from scl.core.data_block import DataBlock
from scl.core.prob_dist import Frequencies
from scl.external_compressors.fse_cpp_wrapper import FSECppWrapper


def test_cpp_roundtrip_tiny_alphabet(fse_cpp):
    """
    Tiny smoke test to ensure the pybind layer can build params/tables and
    perform a roundtrip without tripping the range check.
    """
    if fse_cpp is None:
        pytest.skip("scl_fse_cpp module not available")

    counts = {0: 1, 1: 1}
    counts_vec = [counts[i] for i in range(len(counts))]
    params = fse_cpp.FSEParams(counts_vec, 2)
    tables = fse_cpp.FSETables(params)
    enc = fse_cpp.FSEEncoder(tables)
    dec = fse_cpp.FSEDecoder(tables)

    data = [0, 1, 0]
    encoded = enc.encode_block(data)
    decoded, bits_consumed = dec.decode_block(encoded.bytes)

    assert decoded == data
    assert bits_consumed == encoded.bit_count


def test_cpp_wrapper_handles_sparse_symbols(fse_cpp):
    """Wrapper should remap sparse symbols to dense IDs for the C++ codec."""
    if fse_cpp is None:
        pytest.skip("scl_fse_cpp module not available")

    freq = {10: 2, 42: 1, 255: 1}
    wrapper = FSECppWrapper(Frequencies(freq), table_log=6)

    data = [10, 255, 10, 42, 10, 255]
    encoded_bits = wrapper.encode_block(DataBlock(data))
    decoded_block, bits_consumed = wrapper.decode_block(encoded_bits)

    assert decoded_block.data_list == data
    assert bits_consumed == len(encoded_bits)
