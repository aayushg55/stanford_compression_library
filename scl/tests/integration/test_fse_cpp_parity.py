import random

import pytest
from bitarray import bitarray

from scl.compressors.fse import (
    FSEEncoder as PyEnc,
    FSEDecoder as PyDec,
    FSEParams as PyParams,
)
from scl.core.data_block import DataBlock
from scl.core.prob_dist import Frequencies


@pytest.mark.parametrize("table_log", [6, 8, 10])
def test_cpp_matches_python_roundtrip(table_log, fse_cpp):
    if fse_cpp is None:
        pytest.skip("scl_fse_cpp module not available")
    rng = random.Random(12345)
    alphabet = list(range(4))
    data = [rng.choice(alphabet) for _ in range(512)]

    # Python codec
    counts = {sym: data.count(sym) for sym in alphabet}
    py_params = PyParams(Frequencies(counts), TABLE_SIZE_LOG2=table_log)
    py_enc = PyEnc(py_params)
    py_dec = PyDec(py_params)
    py_encoded = py_enc.encode_block(DataBlock(data))
    py_decoded, _ = py_dec.decode_block(py_encoded)
    assert py_decoded.data_list == data

    # C++ codec (dense ids already ints)
    counts_vec = [0] * len(counts)
    for sym, c in counts.items():
        counts_vec[sym] = c
    cpp_params = fse_cpp.FSEParams(counts_vec, table_log)
    cpp_tables = fse_cpp.FSETables(cpp_params)
    cpp_enc = fse_cpp.FSEEncoder(cpp_tables)
    cpp_dec = fse_cpp.FSEDecoder(cpp_tables)

    cpp_encoded = cpp_enc.encode_block(data)
    cpp_decoded, bits_consumed = cpp_dec.decode_block(cpp_encoded.bytes)
    assert cpp_decoded == data
    assert bits_consumed == cpp_encoded.bit_count

    cpp_bits = bitarray(endian="big")
    cpp_bits.frombytes(bytes(cpp_encoded.bytes))
    cpp_bits = cpp_bits[: cpp_encoded.bit_count]
    py_bits = py_encoded[: cpp_encoded.bit_count]
    assert cpp_bits.tolist() == py_bits.tolist()
