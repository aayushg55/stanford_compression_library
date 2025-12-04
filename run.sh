#!/bin/bash
set -euo pipefail

RAW="scl/benchmark/benchmark_results/fullbench_proba_raw.txt"
OUT="scl/benchmark/benchmark_results/fullbench_proba_sclfse_filtered.txt"
B=32768

rm -f "${RAW}"
for p in 80 14 2; do
  echo "== Proba${p} ==" >> "${RAW}"
  # Restrict to the SCL FSE cases (levels 1/2/4/5, compress + decompress) to keep the run short.
  for t in 90 91 92 93 94 95 96 97; do
    ./FiniteStateEntropy/programs/fullbench -i1 -b${t} -P${p} -B${B} >> "${RAW}" 2>&1
  done
done

python scripts/parse_fullbench.py --raw "${RAW}" --output "${OUT}" --block-size "${B}" --plain
