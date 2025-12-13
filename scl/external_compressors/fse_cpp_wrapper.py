"""Wrapper around the C++ FSE pybind module to mirror the Python codec API"""

import sys
from pathlib import Path
from typing import Any, List, Tuple

from bitarray import bitarray

from scl.core.data_block import DataBlock
from scl.core.prob_dist import Frequencies
from scl.core.data_encoder_decoder import DataEncoder, DataDecoder

# Try to import the C++ pybind module, with fallback path search
try:
    import scl_fse_cpp  # type: ignore
except ImportError as e:
    scl_fse_cpp = None
    _IMPORT_ERROR = e
    # Fallback: search for build directory relative to repo root
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
    """Shared state for the C++ encoder/decoder pair
    
    Maintains symbol-to-ID mapping and FSE tables that are shared between
    encoder and decoder. The C++ implementation uses dense integer IDs (0..N-1)
    instead of arbitrary Python symbols, so we map symbols to IDs on encode
    and IDs back to symbols on decode.
    """

    def __init__(self, freqs: Frequencies, table_log: int):
        if scl_fse_cpp is None:
            raise ImportError(
                "scl_fse_cpp module not available; build the pybind module"
            ) from _IMPORT_ERROR

        # Build bidirectional mapping: symbol <-> dense integer ID
        symbols = list(freqs.freq_dict.keys())
        self._sym_to_id = {s: i for i, s in enumerate(symbols)}
        self._id_to_sym = {i: s for s, i in self._sym_to_id.items()}

        # Convert symbol frequencies to dense count vector for C++ API
        counts_vec = [0] * len(symbols)
        for sym, c in freqs.freq_dict.items():
            counts_vec[self._sym_to_id[sym]] = c

        # Build FSE tables (shared between encoder and decoder)
        self.params = scl_fse_cpp.FSEParams(counts_vec, table_log)
        self.tables = scl_fse_cpp.FSETables(self.params)
        self.encoder = scl_fse_cpp.FSEEncoder(self.tables)
        self.decoder = scl_fse_cpp.FSEDecoder(self.tables)

    def map_symbols(self, data_block: DataBlock) -> List[int]:
        """Convert Python symbols to dense integer IDs for C++ encoder"""
        try:
            return [self._sym_to_id[s] for s in data_block.data_list]
        except KeyError as e:
            raise ValueError(f"Symbol {e} not in alphabet") from e

    def ids_to_symbols(self, ids: List[int]) -> List[Any]:
        """Convert dense integer IDs back to Python symbols after C++ decode"""
        return [self._id_to_sym[i] for i in ids]


class FSECppEncoder(DataEncoder):
    """Encoder backed by the C++ implementation"""

    def __init__(self, ctx: _FSECppContext):
        self._ctx = ctx

    def encode_block(self, data_block: DataBlock) -> bitarray:
        """Encode using C++ implementation via symbol-to-ID mapping"""
        # Map Python symbols to dense IDs, encode, then convert bytes to bitarray
        mapped = self._ctx.map_symbols(data_block)
        encoded = self._ctx.encoder.encode_block(mapped)
        bits = bitarray(endian="big")
        bits.frombytes(bytes(encoded.bytes))
        # Truncate to actual bit count (last byte may be partially used)
        return bits[: encoded.bit_count]

    def reset(self):
        return None


class FSECppDecoder(DataDecoder):
    """Decoder backed by the C++ implementation"""

    def __init__(self, ctx: _FSECppContext):
        self._ctx = ctx

    def decode_block(self, encoded_bits: bitarray) -> Tuple[DataBlock, int]:
        """Decode using C++ implementation via ID-to-symbol mapping"""
        # Convert bitarray to bytes, decode to IDs, then map IDs back to symbols
        decoded_bytes = list(encoded_bits.tobytes())
        decoded_ids, bits_consumed = self._ctx.decoder.decode_block(decoded_bytes)
        decoded_syms = self._ctx.ids_to_symbols(decoded_ids)
        return DataBlock(decoded_syms), bits_consumed

    def reset(self):
        return None


def make_cpp_codec(
    freqs: Frequencies, table_log: int
) -> Tuple[FSECppEncoder, FSECppDecoder]:
    ctx = _FSECppContext(freqs, table_log)
    return FSECppEncoder(ctx), FSECppDecoder(ctx)
