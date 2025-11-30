"""
Wrapper around the C++ FSE pybind module to mirror the Python codec API.

Provides separate encoder/decoder classes that share dense-ID mapping and tables,
so they can plug into existing SCL helpers and benchmarks.
"""

import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple, Union

from bitarray import bitarray

from scl.core.data_block import DataBlock
from scl.core.prob_dist import Frequencies
from scl.core.data_encoder_decoder import DataEncoder, DataDecoder

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


class _FSECppContext:
    """Shared state for the C++ encoder/decoder pair (dense mapping + tables)."""

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

        self.params = scl_fse_cpp.FSEParams(counts_vec, table_log)
        self.tables = scl_fse_cpp.FSETables(self.params)
        self.encoder = scl_fse_cpp.FSEEncoder(self.tables)
        self.decoder = scl_fse_cpp.FSEDecoder(self.tables)

    def map_symbols(self, data_block: DataBlock) -> List[int]:
        try:
            return [self._sym_to_id[s] for s in data_block.data_list]
        except KeyError as e:
            raise ValueError(f"Symbol {e} not in alphabet") from e

    def ids_to_symbols(self, ids: List[int]) -> List[Any]:
        return [self._id_to_sym[i] for i in ids]


class FSECppEncoder(DataEncoder):
    """Dense-ID encoder backed by the C++ tables."""

    def __init__(self, ctx: _FSECppContext):
        self._ctx = ctx

    def encode_block(self, data_block: DataBlock) -> bitarray:
        mapped = self._ctx.map_symbols(data_block)
        encoded = self._ctx.encoder.encode_block(mapped)
        bits = bitarray(endian="big")
        bits.frombytes(bytes(encoded.bytes))
        return bits[: encoded.bit_count]

    def reset(self):
        return None


class FSECppDecoder(DataDecoder):
    """Dense-ID decoder backed by the C++ tables."""

    def __init__(self, ctx: _FSECppContext):
        self._ctx = ctx

    def decode_block(self, encoded_bits: bitarray) -> Tuple[DataBlock, int]:
        decoded_bytes = list(encoded_bits.tobytes())
        decoded_ids, bits_consumed = self._ctx.decoder.decode_block(decoded_bytes)
        decoded_syms = self._ctx.ids_to_symbols(decoded_ids)
        return DataBlock(decoded_syms), bits_consumed

    def reset(self):
        return None


def make_cpp_codec(
    freq_dict: Union[Dict[Any, int], Frequencies], table_log: int
) -> Tuple[FSECppEncoder, FSECppDecoder]:
    freqs = freq_dict if isinstance(freq_dict, Frequencies) else Frequencies(freq_dict)
    ctx = _FSECppContext(freqs, table_log)
    return FSECppEncoder(ctx), FSECppDecoder(ctx)
