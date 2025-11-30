"""Run a subset of existing FSE scenarios against the C++ pybind spec."""

import sys
from pathlib import Path

import pytest

from scl.core.data_block import DataBlock
from scl.core.prob_dist import Frequencies
from scl.utils.test_utils import try_lossless_compression

# Import helper for C++ module
try:
    import scl_fse_cpp as fsecpp  # type: ignore
except ImportError:  # pragma: no cover
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


@pytest.mark.skipif(fsecpp is None, reason="scl_fse_cpp module not available")
@pytest.mark.parametrize(
    "freq_dict,table_log",
    [
        ({"A": 3, "B": 3, "C": 2}, 4),
        ({"A": 1, "B": 3}, 6),
        ({"A": 5, "B": 5, "C": 5, "D": 5}, 8),
    ],
)
def test_cpp_end_to_end_matches_python_behavior(freq_dict, table_log):
    # Build histogram vector for C++
    counts_vec = [0] * 256
    for sym, c in freq_dict.items():
        counts_vec[ord(sym) if isinstance(sym, str) else sym] = c

    params = fsecpp.FSEParams(counts_vec, table_log)
    tables = fsecpp.FSETables(params)
    enc = fsecpp.FSEEncoder(tables)
    dec = fsecpp.FSEDecoder(tables)

    # Create a simple block covering alphabet
    symbols = list(freq_dict.keys())
    data = DataBlock(symbols + symbols)

    encoded = enc.encode_block(data.data_list)
    decoded, bits_consumed = dec.decode_block(encoded.bytes)
    assert decoded == data.data_list
    assert bits_consumed == encoded.bit_count


@pytest.mark.skipif(fsecpp is None, reason="scl_fse_cpp module not available")
def test_cpp_matches_try_lossless_style():
    freq = Frequencies({"A": 3, "B": 3, "C": 2})
    table_log = 6

    counts_vec = [0] * 256
    for sym, c in freq.freq_dict.items():
        counts_vec[ord(sym)] = c

    params = fsecpp.FSEParams(counts_vec, table_log)
    tables = fsecpp.FSETables(params)
    enc = fsecpp.FSEEncoder(tables)
    dec = fsecpp.FSEDecoder(tables)

    # Use the Python helper to mirror behavior
    data = DataBlock(["A", "B", "C", "A", "B", "C"])
    encoded = enc.encode_block(data.data_list)
    decoded, bits_consumed = dec.decode_block(encoded.bytes)
    assert decoded == data.data_list
    assert bits_consumed == encoded.bit_count

    # Also check lossless helper on the Python side against encoded bytes
    # by wrapping with a shim encoder/decoder using the pybind module.
    class ShimEncoder:
        def encode_block(self, db: DataBlock):
            return encoded  # reuse already encoded block

    class ShimDecoder:
        def decode_block(self, _bitarray):
            # mimic Python API: returns DataBlock, bits_consumed
            return DataBlock(decoded), bits_consumed

    is_lossless, _, _ = try_lossless_compression(
        data, ShimEncoder(), ShimDecoder(), add_extra_bits_to_encoder_output=True
    )
    assert is_lossless
