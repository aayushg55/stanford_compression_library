#!/bin/bash
set -euo pipefail

RAW="scl/benchmark/benchmark_results/fullbench_proba_raw.txt"
OUT="scl/benchmark/benchmark_results/fullbench_proba_sclfse_filtered.txt"
B=32768

rm -f "${RAW}"
for p in 80 14 2; do
  echo "== Proba${p} ==" >> "${RAW}"
  ./FiniteStateEntropy/programs/fullbench -i1 -b0 -P${p} -B${B} >> "${RAW}" 2>&1
done

python scripts/parse_fullbench.py --raw "${RAW}" --output "${OUT}" --block-size "${B}"
