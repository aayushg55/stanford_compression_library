#!/usr/bin/env python3
"""
Parse a saved FiniteStateEntropy fullbench output file and emit a concise table
for selected codecs, including compression ratio (block_size / compressed_size).

Usage:
  python scripts/parse_fullbench.py --raw scl/benchmark/benchmark_results/fullbench_proba_raw.txt \
    --output scl/benchmark/benchmark_results/fullbench_proba_sclfse_filtered.txt \
    --block-size 32768
"""

import argparse
import re
from pathlib import Path
from typing import Dict, List, Tuple

CompressKey = Tuple[str, float, int]  # (codec_name, speed, compressed_size)
DecompressKey = Tuple[str, float]     # (codec_name, speed)


def parse_metrics(raw_path: Path, block_size: int) -> Dict[str, Dict[str, Dict[str, float]]]:
    """
    Returns nested dict: proba -> codec -> {"ratio": ..., "comp": ..., "csize": ..., "decomp": ...}
    """
    compress_re = re.compile(r"\s*\d+[-#](\S+).*:\s*([\d.]+)\s*MB/s[^()]*\(\s*(\d+)\s*\)")
    decompress_re = re.compile(r"\s*\d+[-#](\S+).*:\s*([\d.]+)\s*MB/s")

    # Map compress functions to canonical codecs with preference (higher is better).
    compress_map: Dict[str, tuple[str, int]] = {
        # Huff0: prefer 4x using CTable
        "HUF_compress4x_usingCTable_bmi2": ("HUF_inner", 2),
        "HUF_compress4x_usingCTable": ("HUF_inner", 2),
        "HUF_compress_usingCTable": ("HUF_inner", 1),
        "HUF_compress": ("HUF", 0),
        # FSE: prefer usingCTable
        "FSE_compress_usingCTable_smallDst": ("FSE_inner", 1),
        "FSE_compress_usingCTable": ("FSE_inner", 1),
        "FSE_compress": ("FSE", 0),
        # zlibh
        "zlibh_compress": ("zlibh", 0),
        # scl fse variants
        "scl_fse_1_compress": ("scl_fse_1", 0),
        "scl_fse_2_compress": ("scl_fse_2", 0),
        "scl_fse_4_compress": ("scl_fse_4", 0),
    }

    # Decompress mapping with preference scores: higher wins; ties broken by faster MB/s.
    decompress_map: Dict[str, tuple[str, int]] = {
        # Huff0: prefer 4X usingDTable (bmi2 highest), then 4X, then 1X.
        "HUF_decompress4X2_usingDTable_bmi2": ("HUF_inner", 3),
        "HUF_decompress4X2_usingDTable": ("HUF_inner", 3),
        "HUF_decompress4X1_usingDTable_bmi2": ("HUF_inner", 2),
        "HUF_decompress4X1_usingDTable": ("HUF_inner", 2),
        "HUF_decompress4X1": ("HUF", 1),
        "HUF_decompress4X2": ("HUF", 1),
        "HUF_decompress": ("HUF", 0),
        "HUF_decompress1X1": ("HUF", 0),
        "HUF_decompress1X1_usingDTable": ("HUF_inner", 1),
        "HUF_decompress1X1_usingDTable_bmi2": ("HUF_inner", 1),
        "HUF_decompress1X2": ("HUF", 0),
        "HUF_decompress1X2_usingDTable": ("HUF_inner", 1),
        "HUF_decompress1X2_usingDTable_bmi2": ("HUF_inner", 1),
        # FSE: prefer usingDTable
        "FSE_decompress_usingDTable": ("FSE_inner", 1),
        "FSE_decompress": ("FSE", 0),
        "zlibh_decompress": ("zlibh", 0),
        "scl_fse_1_decompress": ("scl_fse_1", 0),
        "scl_fse_2_decompress": ("scl_fse_2", 0),
        "scl_fse_4_decompress": ("scl_fse_4", 0),
    }

    metrics: Dict[str, Dict[str, Dict[str, float]]] = {}
    current_proba = None

    for raw_line in raw_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.replace("\r", "")
        if line.startswith("== Proba"):
            current_proba = line.strip("= ").replace("Proba", "")
            metrics.setdefault(current_proba, {})
            continue
        if not current_proba:
            continue

        m = compress_re.search(line)
        if m:
            name, speed_s, csize_s = m.groups()
            mapping = compress_map.get(name)
            if mapping:
                canon, pref = mapping
                speed = float(speed_s)
                csize = int(csize_s)
                entry = metrics.setdefault(current_proba, {}).setdefault(canon, {})
                current_pref = entry.get("_comp_pref", -1)
                # keep highest pref; if equal, keep faster comp
                if pref > current_pref or (pref == current_pref and speed > entry.get("comp", 0.0)):
                    entry["comp"] = speed
                    entry["csize"] = csize
                    entry["ratio"] = (block_size / csize) if csize else 0.0
                    entry["_comp_pref"] = pref
                continue  # handled

        m = decompress_re.search(line)
        if m:
            name, speed_s = m.groups()
            mapping = decompress_map.get(name)
            if mapping:
                canon, pref = mapping
                speed = float(speed_s)
                entry = metrics.setdefault(current_proba, {}).setdefault(canon, {})
                current_pref = entry.get("_pref", -1)
                if pref > current_pref or (pref == current_pref and speed > entry.get("decomp", 0.0)):
                    entry["decomp"] = speed
                    entry["_pref"] = pref

    return metrics


def format_tables(metrics: Dict[str, Dict[str, Dict[str, float]]]) -> List[str]:
    order = [
        "HUF",
        "HUF_inner",
        "FSE",
        "FSE_inner",
        "zlibh",
        "scl_fse_1",
        "scl_fse_2",
        "scl_fse_4",
    ]
    pretty = {
        "HUF": "HUF",
        "HUF_inner": "HUF (using CTable/DTable)",
        "FSE": "FSE",
        "FSE_inner": "FSE (using CTable/DTable)",
        "zlibh": "zlibh",
        "scl_fse_1": "scl_fse_1",
        "scl_fse_2": "scl_fse_2",
        "scl_fse_4": "scl_fse_4",
    }

    lines: List[str] = []
    for proba in sorted(metrics.keys(), key=lambda x: float(x)):
        lines.append(f"### Proba{proba}")
        lines.append("| Codec | Ratio | Compression (MB/s) | Decompression (MB/s) |")
        lines.append("| ----- | ----- | -----------------: | -------------------: |")
        for key in order:
            m = metrics[proba].get(key, {})
            ratio = f"{m.get('ratio', ''):.2f}" if "ratio" in m else ""
            comp = f"{m.get('comp', ''):.1f}" if "comp" in m else ""
            decomp = f"{m.get('decomp', ''):.1f}" if "decomp" in m else ""
            lines.append(
                f"| {pretty[key]} | {ratio} | {comp} | {decomp} |"
            )
        lines.append("")  # blank line between tables
    return lines


def format_plain(metrics: Dict[str, Dict[str, Dict[str, float]]]) -> List[str]:
    order = [
        "HUF",
        "HUF_inner",
        "FSE",
        "FSE_inner",
        "zlibh",
        "scl_fse_1",
        "scl_fse_2",
        "scl_fse_4",
    ]
    pretty = {
        "HUF": "HUF",
        "HUF_inner": "HUF (using C/D tables)",
        "FSE": "FSE",
        "FSE_inner": "FSE (using C/D tables)",
        "zlibh": "zlibh",
        "scl_fse_1": "scl_fse_1",
        "scl_fse_2": "scl_fse_2",
        "scl_fse_4": "scl_fse_4",
    }
    lines: List[str] = []
    for proba in sorted(metrics.keys(), key=lambda x: float(x)):
        lines.append(f"Proba{proba}")
        lines.append(f"{'Codec':<24} {'Ratio':>8} {'Comp MB/s':>10} {'Decomp MB/s':>12}")
        lines.append("-" * 58)
        for key in order:
            m = metrics[proba].get(key, {})
            ratio = f"{m.get('ratio', 0):.2f}" if "ratio" in m else ""
            comp = f"{m.get('comp', 0):.1f}" if "comp" in m else ""
            decomp = f"{m.get('decomp', 0):.1f}" if "decomp" in m else ""
            lines.append(f"{pretty[key]:<24} {ratio:>8} {comp:>10} {decomp:>12}")
        lines.append("")
    return lines


def main() -> None:
    parser = argparse.ArgumentParser(description="Parse fullbench raw output.")
    parser.add_argument("--raw", required=True, type=Path, help="Path to raw fullbench output.")
    parser.add_argument("--output", type=Path, help="Optional path to write filtered table.")
    parser.add_argument("--block-size", type=int, default=32768, help="Block size used in bench.")
    parser.add_argument("--plain", action="store_true", help="Emit fixed-width plain text instead of markdown.")
    args = parser.parse_args()

    metrics = parse_metrics(args.raw, args.block_size)
    text_lines = format_plain(metrics) if args.plain else format_tables(metrics)
    text = "\n".join(text_lines) + ("\n" if text_lines else "")

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    print(text, end="")


if __name__ == "__main__":
    main()
