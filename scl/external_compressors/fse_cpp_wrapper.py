"""
Wrapper around the C++ FSE pybind module to mirror the Python codec API.

It builds a dense 0..N alphabet from the provided frequencies, maps symbols to
dense IDs before calling the C++ encoder/decoder, and maps them back on decode.
"""

import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

from bitarray import bitarray

from scl.core.data_block import DataBlock
from scl.core.prob_dist import Frequencies

try:
    import scl_fse_cpp  # type: ignore
except ImportError as e:  # pragma: no cover - optional dependency
    # Try adding cpp/build relative to the repo root, then retry import.
    scl_fse_cpp = None
    _IMPORT_ERROR = e
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "cpp" / "build"
        if candidate.exists():
            sys.path.append(str(candidate))
            try:
                import scl_fse_cpp  # type: ignore
                _IMPORT_ERROR = None
            except ImportError as inner_e:  # pragma: no cover
                _IMPORT_ERROR = inner_e
                scl_fse_cpp = None
            break
else:
    _IMPORT_ERROR = None


class FSECppWrapper:
    def __init__(self, freqs: Frequencies, table_log: int):
        if scl_fse_cpp is None:
            raise ImportError(
                "scl_fse_cpp module not available; build the pybind module"
            ) from _IMPORT_ERROR

        symbols = list(freqs.freq_dict.keys())
        self._sym_to_id = {s: i for i, s in enumerate(symbols)}
        self._id_to_sym = {i: s for s, i in self._sym_to_id.items()}

        counts_vec = [0] * len(symbols)
        for sym, c in freqs.freq_dict.items():
            counts_vec[self._sym_to_id[sym]] = c

        # Keep params/tables alive for the encoder/decoder reference lifetimes.
        self._params = scl_fse_cpp.FSEParams(counts_vec, table_log)
        self._tables = scl_fse_cpp.FSETables(self._params)
        self._enc = scl_fse_cpp.FSEEncoder(self._tables)
        self._dec = scl_fse_cpp.FSEDecoder(self._tables)

    def encode_block(self, data_block: DataBlock) -> bitarray:
        try:
            mapped: List[int] = [self._sym_to_id[s] for s in data_block.data_list]
        except KeyError as e:
            raise ValueError(f"Symbol {e} not in alphabet") from e
        encoded = self._enc.encode_block(mapped)
        bits = bitarray(endian="big")
        bits.frombytes(bytes(encoded.bytes))
        return bits[: encoded.bit_count]

    def decode_block(self, encoded_bits: bitarray) -> Tuple[DataBlock, int]:
        encoded_bytes = list(encoded_bits.tobytes())
        decoded_ids, bits_consumed = self._dec.decode_block(encoded_bytes)
        decoded_syms = [self._id_to_sym[i] for i in decoded_ids]
        return DataBlock(decoded_syms), bits_consumed


def make_cpp_codec(freq_dict: Dict[Any, int], table_log: int) -> FSECppWrapper:
    return FSECppWrapper(Frequencies(freq_dict), table_log)
