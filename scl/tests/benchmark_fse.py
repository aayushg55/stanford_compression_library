#!/usr/bin/env python3
"""Benchmark script for FSE implementation.

Compares FSE against other codecs (rANS, tANS, Huffman, zlib, zstd, pickle)
on compression ratio and speed.
"""

import argparse
import inspect
import math
import os
import pickle
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

import pandas as pd

# Add project root to Python path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from scl.compressors.fse import FSEParams, FSEEncoder, FSEDecoder
from scl.compressors.huffman_coder import HuffmanDecoder, HuffmanEncoder
from scl.compressors.rANS import rANSParams, rANSDecoder, rANSEncoder
from scl.compressors.tANS import tANSParams, tANSDecoder, tANSEncoder
from scl.core.data_block import DataBlock
from scl.external_compressors.zlib_external import (
    ZlibExternalDecoder,
    ZlibExternalEncoder,
)
from scl.core.prob_dist import Frequencies, get_avg_neg_log_prob
from scl.external_compressors.pickle_external import PickleDecoder, PickleEncoder
from scl.external_compressors.zstd_external import (
    ZstdExternalDecoder,
    ZstdExternalEncoder,
)
from scl.utils.test_utils import are_blocks_equal, get_random_data_block
from tests.dataset_utils import (
    get_frequencies_from_datablock,
    load_dataset_files,
    read_file_as_bytes,
)


@dataclass
class CodecResult:
    """Benchmark results for a single codec."""

    name: str
    is_lossless: bool
    compressed_bits: int
    compression_ratio: float
    bits_per_symbol: float
    encode_throughput_mbps: float
    decode_throughput_mbps: float
    encode_time_ms: float
    decode_time_ms: float


def time_function(func: Callable, *args, **kwargs) -> Tuple[Any, float]:
    """Time a function call and return result and elapsed time in seconds."""
    start = time.perf_counter()
    result = func(*args, **kwargs)
    elapsed = time.perf_counter() - start
    return result, elapsed


def calculate_throughput_mbps(data_size_bytes: int, time_seconds: float) -> float:
    """Calculate throughput in MB/s.

    Args:
        data_size_bytes: Data size in bytes
        time_seconds: Elapsed time in seconds

    Returns:
        Throughput in MB/s, or 0.0 if time <= 0
    """
    if time_seconds <= 0:
        return 0.0
    return (data_size_bytes / (1024 * 1024)) / time_seconds


def create_fse_codec(freq: Frequencies, table_log: int = 12):
    """Create FSE encoder/decoder pair."""
    params = FSEParams(freq, TABLE_SIZE_LOG2=table_log)
    return FSEEncoder(params), FSEDecoder(params)


def create_rans_codec(freq: Frequencies):
    """Create rANS encoder/decoder pair."""
    params = rANSParams(freq)
    return rANSEncoder(params), rANSDecoder(params)


def create_tans_codec(freq: Frequencies):
    """Create tANS encoder/decoder pair.

    Normalizes frequencies to power of 2 as required by tANS.
    """
    total = freq.total_freq
    next_pow2 = 1 << math.ceil(math.log2(total))
    scale = next_pow2 / total
    normalized_freq = {s: max(1, int(freq.frequency(s) * scale)) for s in freq.alphabet}
    normalized_freq_list = list(normalized_freq.values())
    diff = next_pow2 - sum(normalized_freq_list)
    if diff != 0:
        max_sym = max(normalized_freq, key=normalized_freq.get)
        normalized_freq[max_sym] += diff
    tans_freq = Frequencies(normalized_freq)

    params = tANSParams(tans_freq, RANGE_FACTOR=1)
    return tANSEncoder(params), tANSDecoder(params)


def create_huffman_codec(freq: Frequencies):
    """Create Huffman encoder/decoder pair."""
    prob_dist = freq.get_prob_dist()
    return HuffmanEncoder(prob_dist), HuffmanDecoder(prob_dist)


def create_zlib_codec():
    """Create zlib codec using existing ZlibExternalEncoder/Decoder.

    Note: Returns BitArray (with 32-bit size header), not raw bytes.
    This matches the existing library implementation.
    """

    return ZlibExternalEncoder(), ZlibExternalDecoder()


def create_pickle_codec():
    """Create pickle codec (serialization-based, for reference only)."""
    return PickleEncoder(), PickleDecoder()


def create_zstd_codec():
    """Create zstandard codec (byte-level LZ77-based, for reference only)."""

    class ZstdEncoderWrapper:
        def __init__(self, encoder):
            self.encoder = encoder

        def encode_block(self, data_block: DataBlock):
            if all(isinstance(s, int) and 0 <= s < 256 for s in data_block.data_list):
                data_bytes = bytes(data_block.data_list)
            elif all(isinstance(s, str) and len(s) == 1 for s in data_block.data_list):
                data_bytes = bytes(ord(s) for s in data_block.data_list)
            else:
                data_bytes = str(data_block.data_list).encode("utf-8")
            byte_block = DataBlock(list(data_bytes))
            return self.encoder.encode_block(byte_block)

    class ZstdDecoderWrapper:
        def __init__(self, decoder):
            self.decoder = decoder

        def decode_block(self, encoded):
            return self.decoder.decode_block(encoded)

    encoder = ZstdExternalEncoder(level=6)
    decoder = ZstdExternalDecoder(level=6)
    return ZstdEncoderWrapper(encoder), ZstdDecoderWrapper(decoder)


def get_codec_factories(codecs: Optional[List[str]] = None):
    """Get list of codec factory functions.

    Args:
        codecs: List of codec names to include. If None, uses default set.
                Valid names: 'fse', 'rans', 'tans', 'huffman', 'zlib', 'zstd', 'pickle'
                Default: ['fse', 'zlib', 'zstd', 'pickle']

    Returns:
        List of (factory_func, name, get_size_func) tuples.
        get_size_func is None for symbol-level codecs (uses data_block.size).
    """
    if codecs is None:
        codecs = ["fse", "zlib", "zstd", "pickle"]

    codecs_lower = [c.lower() for c in codecs]

    codec_map = {
        "fse": (lambda f: create_fse_codec(f, table_log=12), "FSE", None),
        "rans": (lambda f: create_rans_codec(f), "rANS", None),
        "tans": (lambda f: create_tans_codec(f), "tANS", None),
        "huffman": (lambda f: create_huffman_codec(f), "Huffman", None),
        "zlib": (lambda: create_zlib_codec(), "zlib", lambda db: db.size),
        "zstd": (lambda: create_zstd_codec(), "zstd", lambda db: db.size),
        "pickle": (lambda: create_pickle_codec(), "pickle", None),
    }

    factories = []
    for codec in codecs_lower:
        if codec in codec_map:
            factories.append(codec_map[codec])
        else:
            print(
                f"WARNING: Unknown codec '{codec}', skipping. Valid: {list(codec_map.keys())}"
            )

    return factories


def benchmark_codec(
    encoder,
    decoder,
    data_block: DataBlock,
    name: str,
    get_data_size_bytes: Optional[Callable] = None,
) -> CodecResult:
    """Benchmark a codec (encoder/decoder pair) on a single block.

    Note: This benchmarks a single contiguous block. For multi-block streaming,
    use the encoder/decoder's encode()/decode() methods with DataStream.

    Args:
        encoder: Encoder with encode_block() method
        decoder: Decoder with decode_block() method
        data_block: Single DataBlock to encode/decode
        name: Codec name for reporting
        get_data_size_bytes: Optional function to get data size in bytes

    Returns:
        CodecResult with benchmark metrics
    """
    # Convert string symbols to bytes for byte-level codecs (zlib, zstd)
    # Byte-level codecs expect bytes (0-255), but synthetic data uses strings
    byte_level_codecs = {"zlib", "zstd"}
    if name.lower() in byte_level_codecs:
        if all(isinstance(s, str) and len(s) == 1 for s in data_block.data_list):
            data_block = DataBlock([ord(s) for s in data_block.data_list])
        elif not all(isinstance(s, int) and 0 <= s < 256 for s in data_block.data_list):
            raise ValueError(
                f"{name} requires bytes (0-255) or single-char strings, "
                f"got {type(data_block.data_list[0]) if data_block.data_list else 'empty'}"
            )

    encoded, encode_time = time_function(encoder.encode_block, data_block)
    encode_time_ms = encode_time * 1000

    decoded_result, decode_time = time_function(decoder.decode_block, encoded)
    decode_time_ms = decode_time * 1000
    decoded = decoded_result[0]

    # Compare decoded with original (data_block was converted to bytes for byte-level codecs)
    is_lossless = are_blocks_equal(data_block, decoded)
    data_size_bytes = (
        get_data_size_bytes(data_block) if get_data_size_bytes else data_block.size
    )
    compressed_bits = len(encoded)
    original_bits = data_size_bytes * 8

    # Compression ratio = original_size / compressed_size (higher = better)
    # 2.0 means 2x smaller (compressed is half the size)
    # 0.5 means 2x larger (compressed is twice the size)
    compression_ratio = original_bits / compressed_bits if compressed_bits > 0 else 0

    # Bits per symbol: compressed_bits / number_of_symbols
    # For byte-level codecs, this is bits per byte
    bits_per_symbol = compressed_bits / data_block.size if data_block.size > 0 else 0

    encode_throughput = calculate_throughput_mbps(data_size_bytes, encode_time)
    decode_throughput = calculate_throughput_mbps(data_size_bytes, decode_time)

    return CodecResult(
        name=name,
        is_lossless=is_lossless,
        compressed_bits=compressed_bits,
        compression_ratio=compression_ratio,
        bits_per_symbol=bits_per_symbol,
        encode_throughput_mbps=encode_throughput,
        decode_throughput_mbps=decode_throughput,
        encode_time_ms=encode_time_ms,
        decode_time_ms=decode_time_ms,
    )


def benchmark_codecs(
    freq: Frequencies,
    data_block: DataBlock,
    codec_factories: List[Tuple[Callable, str, Optional[Callable]]],
) -> List[CodecResult]:
    """Benchmark all codecs on given data.

    Args:
        freq: Frequency distribution (None for codecs that don't need it)
        data_block: Data to encode/decode
        codec_factories: List of (factory_func, name, get_size_func) tuples

    Returns:
        List of CodecResult objects
    """
    results = []
    for factory, name, get_size_func in codec_factories:
        try:
            sig = inspect.signature(factory)
            if len(sig.parameters) > 0:
                encoder, decoder = factory(freq)
            else:
                encoder, decoder = factory()
            result = benchmark_codec(encoder, decoder, data_block, name, get_size_func)
            results.append(result)
        except Exception as e:
            print(f"ERROR: {name} failed: {e}")
            continue
    return results


def print_benchmark_table(
    results: List[CodecResult],
    title: str,
    entropy: Optional[float] = None,
    file_size_bytes: Optional[int] = None,
):
    """Print formatted benchmark results table."""
    print(f"\n{title}")
    print("=" * 120)

    # Build header dynamically
    cols = ["Codec", "Bits/Sym"]
    if entropy is not None:
        cols.append("Entropy")
    cols.extend(["Comp Ratio"])
    if file_size_bytes is not None:
        cols.append("Size (bytes)")
    cols.extend(["Encode (MB/s)", "Decode (MB/s)", "Total (ms)"])

    header = " ".join(
        f"{col:<{15 if 'MB/s' in col else 12 if col != 'Codec' else 12}}"
        for col in cols
    )
    print(header)
    print("-" * 120)

    for result in results:
        total_time = result.encode_time_ms + result.decode_time_ms
        parts = [
            f"{result.name:<12}",
            f"{result.bits_per_symbol:<10.3f}",
        ]
        if entropy is not None:
            parts.append(f"{entropy:<10.3f}")
        parts.append(f"{result.compression_ratio:<12.3f}")
        if file_size_bytes is not None:
            parts.append(f"{file_size_bytes:<12}")
        parts.extend(
            [
                f"{result.encode_throughput_mbps:<15.2f}",
                f"{result.decode_throughput_mbps:<15.2f}",
                f"{total_time:<12.2f}",
            ]
        )
        print(" ".join(parts))
    print("=" * 120)


def verify_lossless(results: List[CodecResult], byte_level_codecs: set) -> List[str]:
    """Verify codecs are lossless and return list of failed codec names.

    Args:
        results: List of CodecResult objects
        byte_level_codecs: Set of codec names that are byte-level (may not be lossless)

    Returns:
        List of failed codec names (excluding byte-level codecs)
    """
    failed = []
    for result in results:
        if not result.is_lossless:
            if result.name in byte_level_codecs:
                print(
                    f"NOTE: {result.name} is not lossless (expected for byte-level compressor)"
                )
            else:
                failed.append(result.name)
                print(f"ERROR: {result.name} is not lossless!")
    return failed


def compute_aggregated_stats(per_file_results: List[dict]) -> dict:
    """Compute aggregated statistics across all files.

    Args:
        per_file_results: List of per-file result dicts

    Returns:
        Dict mapping codec name to aggregated stats
    """
    if not per_file_results:
        return {}

    codec_names = [r.name for r in per_file_results[0]["results"]]
    aggregated = {}
    total_size = 0
    total_compressed_bits = {name: 0 for name in codec_names}
    total_encode_time = {name: 0.0 for name in codec_names}
    total_decode_time = {name: 0.0 for name in codec_names}

    for file_result in per_file_results:
        total_size += file_result["size"]
        for result in file_result["results"]:
            total_compressed_bits[result.name] += result.compressed_bits
            total_encode_time[result.name] += result.encode_time_ms / 1000.0
            total_decode_time[result.name] += result.decode_time_ms / 1000.0

    for name in codec_names:
        if total_size > 0 and total_compressed_bits[name] > 0:
            avg_bits_per_byte = total_compressed_bits[name] / total_size
            original_bits = total_size * 8
            compression_ratio = original_bits / total_compressed_bits[name]
        else:
            avg_bits_per_byte = 0
            compression_ratio = 0

        total_time = total_encode_time[name] + total_decode_time[name]
        encode_throughput = (
            (total_size / (1024 * 1024)) / total_encode_time[name]
            if total_encode_time[name] > 0
            else 0
        )
        decode_throughput = (
            (total_size / (1024 * 1024)) / total_decode_time[name]
            if total_decode_time[name] > 0
            else 0
        )

        aggregated[name] = {
            "avg_bits_per_byte": avg_bits_per_byte,
            "compression_ratio": compression_ratio,
            "encode_throughput_mbps": encode_throughput,
            "decode_throughput_mbps": decode_throughput,
            "total_time_ms": total_time * 1000,
            "total_size_bytes": total_size,
            "total_compressed_bits": total_compressed_bits[name],
        }

    return aggregated


def print_aggregated_table(aggregated: dict):
    """Print aggregated benchmark results table."""
    if not aggregated:
        return

    print(
        f"{'Codec':<12} {'Bits/Byte':<12} {'Comp Ratio':<12} {'Encode (MB/s)':<15} {'Decode (MB/s)':<15} {'Total (ms)':<12}"
    )
    print("-" * 120)

    for name, stats in aggregated.items():
        print(
            f"{name:<12} {stats['avg_bits_per_byte']:<12.3f} "
            f"{stats['compression_ratio']:<12.3f} "
            f"{stats['encode_throughput_mbps']:<15.2f} "
            f"{stats['decode_throughput_mbps']:<15.2f} "
            f"{stats['total_time_ms']:<12.2f}"
        )
    print("=" * 120)


def save_results(results_dict: Dict, dataset_name: str, project_root: str):
    """Save benchmark results to files.

    Saves:
    - {dataset}_{timestamp}_dataframes.pkl: pandas DataFrames (primary format)
    - {dataset}_{timestamp}_per_file.csv: Per-file results (CSV)
    - {dataset}_{timestamp}_aggregated.csv: Aggregated results (CSV)

    Args:
        results_dict: Dict with 'per_file', 'aggregated', 'metadata' keys
        dataset_name: Name of dataset
        project_root: Root directory of project
    """
    results_dir = os.path.join(project_root, "benchmark_results")
    os.makedirs(results_dir, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base_name = f"{dataset_name}_{timestamp}"

    per_file_data = []
    for file_result in results_dict["per_file"]:
        for codec_result in file_result["results"]:
            per_file_data.append(
                {
                    "file": file_result["file"],
                    "file_path": file_result.get("file_path", ""),
                    "file_size_bytes": file_result["size"],
                    "alphabet_size": file_result["alphabet_size"],
                    "entropy": file_result["entropy"],
                    "codec": codec_result.name,
                    "is_lossless": codec_result.is_lossless,
                    "compressed_bits": codec_result.compressed_bits,
                    "compression_ratio": codec_result.compression_ratio,
                    "bits_per_symbol": codec_result.bits_per_symbol,
                    "encode_throughput_mbps": codec_result.encode_throughput_mbps,
                    "decode_throughput_mbps": codec_result.decode_throughput_mbps,
                    "encode_time_ms": codec_result.encode_time_ms,
                    "decode_time_ms": codec_result.decode_time_ms,
                }
            )

    df_per_file = pd.DataFrame(per_file_data)

    df_agg = None
    if results_dict["aggregated"]:
        agg_data = []
        for codec_name, stats in results_dict["aggregated"].items():
            agg_data.append(
                {
                    "codec": codec_name,
                    "avg_bits_per_byte": stats["avg_bits_per_byte"],
                    "compression_ratio": stats["compression_ratio"],
                    "encode_throughput_mbps": stats["encode_throughput_mbps"],
                    "decode_throughput_mbps": stats["decode_throughput_mbps"],
                    "total_time_ms": stats["total_time_ms"],
                    "total_size_bytes": stats["total_size_bytes"],
                    "total_compressed_bits": stats["total_compressed_bits"],
                }
            )
        df_agg = pd.DataFrame(agg_data)

    pkl_df_path = os.path.join(results_dir, f"{base_name}_dataframes.pkl")
    pd.to_pickle(
        {
            "per_file": df_per_file,
            "aggregated": df_agg,
            "metadata": results_dict["metadata"],
        },
        pkl_df_path,
    )
    print(f"\nResults saved to: {pkl_df_path}")

    csv_per_file_path = os.path.join(results_dir, f"{base_name}_per_file.csv")
    df_per_file.to_csv(csv_per_file_path, index=False)
    print(f"Results saved to: {csv_per_file_path}")

    if df_agg is not None:
        csv_agg_path = os.path.join(results_dir, f"{base_name}_aggregated.csv")
        df_agg.to_csv(csv_agg_path, index=False)
        print(f"Results saved to: {csv_agg_path}")


def run_benchmark_suite(
    freqs_list: List[Frequencies],
    data_size: int = 10000,
    seed: int = 0,
    codecs: Optional[List[str]] = None,
):
    """Run benchmark suite on synthetic distributions.

    Args:
        freqs_list: List of Frequencies objects to test
        data_size: Size of synthetic data blocks
        seed: Random seed for reproducibility
        codecs: List of codec names to benchmark (default: ['fse', 'zlib', 'zstd', 'pickle'])
    """
    codec_factories = get_codec_factories(codecs)

    print("\n" + "=" * 120)
    print("FSE BENCHMARK: Compression Ratio and Speed Comparison")
    print("=" * 120)

    all_results = []
    byte_level_codecs = {"zlib", "zstd"}

    for freq in freqs_list:
        prob_dist = freq.get_prob_dist()
        data_block = get_random_data_block(prob_dist, data_size, seed=seed)
        avg_log_prob = get_avg_neg_log_prob(prob_dist, data_block)

        print(f"\n{'='*120}")
        print(f"Distribution: {freq.freq_dict}")
        print(f"Entropy: {avg_log_prob:.3f} bits/symbol")
        print(f"Data size: {data_size} symbols ({data_size} bytes)")
        print(f"{'='*120}")

        results = benchmark_codecs(freq, data_block, codec_factories)
        failed = verify_lossless(results, byte_level_codecs)

        if failed:
            raise AssertionError(
                f"Correctness check failed: {failed} are not lossless!"
            )

        print_benchmark_table(
            results, f"Benchmark Results: {freq.freq_dict}", entropy=avg_log_prob
        )

        all_results.append(
            {
                "distribution": str(freq.freq_dict),
                "entropy": avg_log_prob,
                "results": results,
            }
        )

    print("\n" + "=" * 120)
    print("SUMMARY")
    print("=" * 120)
    print(f"Tested {len(freqs_list)} distributions with {data_size} symbols each")

    all_lossless = True
    failed_codecs = set()
    for result_dict in all_results:
        for result in result_dict["results"]:
            if not result.is_lossless and result.name not in byte_level_codecs:
                all_lossless = False
                failed_codecs.add(result.name)

    if all_lossless:
        print(
            "✓ All symbol-level codecs verified to be lossless (correctness check passed)"
        )
    else:
        print(f"✗ Correctness check FAILED: {failed_codecs} are not lossless!")
        raise AssertionError(
            f"Correctness check failed: {failed_codecs} are not lossless!"
        )

    print("\nBenchmark complete!")
    return all_results


def run_benchmark_on_dataset(
    dataset_name: str,
    project_root: str,
    test_mode: bool = False,
    codecs: Optional[List[str]] = None,
) -> Dict:
    """Run benchmark suite on a dataset (unzipped directory).

    All files are treated as byte streams (0-255) for consistency.

    Args:
        dataset_name: Name of dataset directory (should be unzipped)
        project_root: Root directory of project
        test_mode: If True, only process smallest file for quick validation
        codecs: List of codec names to benchmark (default: ['fse', 'zlib', 'zstd', 'pickle'])

    Returns:
        Dict with 'per_file', 'aggregated', 'metadata' keys
    """
    codec_factories = get_codec_factories(codecs)

    print("\n" + "=" * 120)
    print(f"FSE BENCHMARK: Dataset '{dataset_name}' (all files as byte streams)")
    if test_mode:
        print("TEST MODE: Processing smallest file only (for quick validation)")
    print("=" * 120)

    files = load_dataset_files(dataset_name, project_root)

    file_sizes = []
    for file_path in files:
        try:
            size = os.path.getsize(file_path)
            file_sizes.append((size, file_path))
        except:
            continue

    file_sizes.sort(key=lambda x: x[0])

    if test_mode:
        files_to_process = [path for _, path in file_sizes[:1]]
        print(f"TEST MODE: Processing 1 of {len(files)} files (smallest)")
    else:
        files_to_process = [path for _, path in file_sizes]
        print(f"Processing all {len(files_to_process)} files")

    per_file_results = []
    byte_level_codecs = {"zlib", "zstd"}

    for file_path in files_to_process:
        print(f"\n{'='*120}")
        print(f"File: {os.path.basename(file_path)}")

        try:
            data_block = read_file_as_bytes(file_path)
        except Exception as e:
            print(f"  ERROR: Failed to read file: {e}")
            continue

        freq = get_frequencies_from_datablock(data_block)
        # Use empirical entropy from data_block itself (more accurate)
        empirical_entropy = data_block.get_entropy()

        print(f"  Size: {data_block.size} bytes")
        print(f"  Alphabet size: {len(freq.alphabet)} unique bytes")
        print(f"  Entropy: {empirical_entropy:.3f} bits/byte")
        print(f"{'='*120}")

        results = benchmark_codecs(freq, data_block, codec_factories)
        failed = verify_lossless(results, byte_level_codecs)

        if failed:
            print(f"WARNING: Some codecs failed correctness check: {failed}")

        print_benchmark_table(
            results,
            f"Benchmark Results: {os.path.basename(file_path)}",
            entropy=empirical_entropy,
            file_size_bytes=data_block.size,
        )

        per_file_results.append(
            {
                "file": os.path.basename(file_path),
                "file_path": file_path,
                "size": data_block.size,
                "alphabet_size": len(freq.alphabet),
                "entropy": empirical_entropy,
                "results": results,
            }
        )

    aggregated = compute_aggregated_stats(per_file_results)

    if len(per_file_results) > 1:
        print("\n" + "=" * 120)
        print("AGGREGATED RESULTS (across all files)")
        print("=" * 120)
        print_aggregated_table(aggregated)

    print("\n" + "=" * 120)
    print("SUMMARY")
    print("=" * 120)
    print(f"Tested {len(per_file_results)} files from dataset '{dataset_name}'")

    all_lossless = True
    failed_codecs = set()
    for result_dict in per_file_results:
        for result in result_dict["results"]:
            if not result.is_lossless and result.name not in byte_level_codecs:
                all_lossless = False
                failed_codecs.add(result.name)

    if all_lossless:
        print(
            "✓ All symbol-level codecs verified to be lossless (correctness check passed)"
        )
    else:
        print(f"✗ Correctness check FAILED: {failed_codecs} are not lossless!")
        print("  (Some files may have failed - check individual file results above)")

    print("\nBenchmark complete!")

    results_dict = {
        "per_file": per_file_results,
        "aggregated": aggregated,
        "metadata": {
            "dataset_name": dataset_name,
            "num_files": len(per_file_results),
            "test_mode": test_mode,
            "timestamp": datetime.now().isoformat(),
        },
    }

    save_results(results_dict, dataset_name, project_root)
    return results_dict


def main():
    """Main entry point for FSE benchmarking."""
    # Custom argument parsing with underscore prefix instead of dashes
    dataset = None
    codecs = None
    synthetic_large = False
    dataset_fast = False

    i = 1
    while i < len(sys.argv):
        arg = sys.argv[i]
        if arg == "_codecs" and i + 1 < len(sys.argv):
            codecs = [c.strip() for c in sys.argv[i + 1].split(",")]
            i += 2
        elif arg == "_synthetic_large":
            synthetic_large = True
            i += 1
        elif arg == "_dataset_fast":
            dataset_fast = True
            i += 1
        elif arg.startswith("_"):
            print(f"WARNING: Unknown argument '{arg}', ignoring")
            i += 1
        elif not arg.startswith("-"):
            # Positional argument (dataset name)
            dataset = arg
            i += 1
        else:
            i += 1

    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    if codecs:
        print(f"Codecs: {', '.join(codecs)}")

    if dataset:
        print(f"Dataset mode: {dataset}")
        if dataset_fast:
            print("VALIDATION mode: Processing smallest file only")
        run_benchmark_on_dataset(
            dataset,
            project_root,
            test_mode=dataset_fast,
            codecs=codecs,
        )
    else:
        if synthetic_large:
            print("SYNTHETIC DATA mode: LARGE benchmark (1M symbols)")
            data_size = 100_000
        else:
            print("SYNTHETIC DATA mode: Standard benchmark (10K symbols)")
            data_size = 10_000

        freqs_list = [
            Frequencies({"A": 1, "B": 1, "C": 2}),
            Frequencies({"A": 3, "B": 3, "C": 2}),
            Frequencies({"A": 5, "B": 5, "C": 5, "D": 5}),
            Frequencies({"A": 1, "B": 3}),
            Frequencies({"A": 12, "B": 34, "C": 1, "D": 45}),
        ]
        run_benchmark_suite(
            freqs_list,
            data_size=data_size,
            seed=0,
            codecs=codecs,
        )


if __name__ == "__main__":
    main()
