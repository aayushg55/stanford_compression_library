import random
import sys
from pathlib import Path

import pytest
from bitarray import bitarray

# Try to import the built module; fall back to adding cpp/build to sys.path.
try:
    import scl_fse_cpp as fsecpp  # type: ignore
except ImportError:  # pragma: no cover - optional dependency
    fsecpp = None
    root = Path(__file__).resolve()
    for parent in root.parents:
        candidate = parent / "cpp" / "build"
        if candidate.exists():
            sys.path.append(str(candidate))
            break
    try:
        import scl_fse_cpp as fsecpp  # type: ignore  # noqa: F401
    except ImportError:
        fsecpp = None

from scl.compressors.fse import FSEEncoder as PyEnc, FSEDecoder as PyDec, FSEParams as PyParams
from scl.core.data_block import DataBlock
from scl.core.prob_dist import Frequencies


@pytest.mark.skipif(fsecpp is None, reason="scl_fse_cpp module not available")
@pytest.mark.parametrize("table_log", [6, 8, 10])
def test_cpp_matches_python_roundtrip(table_log):
    rng = random.Random(12345)
    alphabet = list(range(4))
    data = [rng.choice(alphabet) for _ in range(512)]

    # Build Python params/codec
    counts = {sym: data.count(sym) for sym in alphabet}
    py_params = PyParams(Frequencies(counts), TABLE_SIZE_LOG2=table_log)
    py_enc = PyEnc(py_params)
    py_dec = PyDec(py_params)

    py_encoded = py_enc.encode_block(DataBlock(data))
    py_decoded, _ = py_dec.decode_block(py_encoded)
    assert py_decoded.data_list == data

    # Build C++ params/codec
    counts_vec = [0] * 256
    for sym, c in counts.items():
        counts_vec[sym] = c
    cpp_params = fsecpp.FSEParams(counts_vec, table_log)
    cpp_tables = fsecpp.FSETables(cpp_params)
    cpp_enc = fsecpp.FSEEncoder(cpp_tables)
    cpp_dec = fsecpp.FSEDecoder(cpp_tables)

    cpp_encoded = cpp_enc.encode_block(data)
    cpp_decoded, bits_consumed = cpp_dec.decode_block(cpp_encoded.bytes)
    assert cpp_decoded == data
    assert bits_consumed == cpp_encoded.bit_count

    # Bit-for-bit check: align bitarray with emitted bit_count
    cpp_bits = bitarray(endian="big")
    cpp_bits.frombytes(bytes(cpp_encoded.bytes))
    cpp_bits = cpp_bits[: cpp_encoded.bit_count]
    py_bits = py_encoded[: cpp_encoded.bit_count]

    assert cpp_bits.tolist() == py_bits.tolist()
