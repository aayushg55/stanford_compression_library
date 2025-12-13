# C++ FSE Implementation

Detailed reference for the C++ FSE implementation. For a quick start and overview, see `FSE_PROJECT_README.md`.

## Building

**Quick start** (from repo root):
```bash
make all  # Builds datasets, C++ lib, fullbench, and lzbench
```

**Manual build** (detailed steps):

```bash
conda activate ee274_env

# Configure (exports compile_commands.json; builds pybind if available)
cmake -S cpp -B cpp/build \
  -DSCL_FSE_BUILD_PYBIND=ON \
  -DCMAKE_EXPORT_COMPILE_COMMANDS=ON \
  -Dpybind11_DIR=$(python -m pybind11 --cmakedir)

# Build
cmake --build cpp/build


# Run pybind-backed parity tests
python -m pytest scl/tests/integration/test_fse_cpp_parity.py 
```

**Build outputs:**
- `libscl_fse.a`: static library
- `fse_example`: demo binary
- `scl_fse_cpp*.so`: pybind11 module for Python integration

**Dependencies:**
- pybind11: `pip install pybind11` (if building pybind module)

## C++ Benchmarking

**Quick start**: `make all` builds both lzbench and fullbench. See `FSE_PROJECT_README.md` for usage examples.

**Detailed instructions:**

### lzbench

`lzbench` (third-party, cloned under `lzbench/`): a widely used in-memory benchmark. It preloads each file into RAM and loops encode/decode for a fixed time, reusing preallocated buffers and checking correctness once per codec. To build and run with local CPU tuning:
  ```bash
  cd lzbench
  make -j$(sysctl -n hw.ncpu)               # MOREFLAGS=-march=native is enabled by default in this repo

  ./lzbench -ezstd,1,3,4,5/lz4/zlib \
    -r ../scl/benchmark/datasets/silesia \
    -t2,2 -j1 \
    > ../scl/benchmark/benchmark_results/lzbench_silesia.txt
  ```
  Use `-t` to control the time per codec (seconds for compress/decompress), `-j1` for single-threaded numbers, and `-r` to recurse over a dataset directory. The lzbench output is a good reference for expected zstd/lz4/zlib throughput on your hardware.

  Quick fse-inclusive run (single-threaded, zstd level 1, lz4, zlib, fse level 12):
  ```bash
  ./lzbench -efse,12/zstd,1/lz4/zlib \
    -r ../scl/benchmark/datasets/silesia \
    -t2,2 -j1 \
    > ../scl/benchmark/benchmark_results/lzbench_silesia_fse_zstd1_lz4_zlib.txt
  ```

  If you don’t want full level sweeps, pick a few representative levels:
  - zlib: default is level 6. Common picks: `1` (fastest), `6` (default/medium), `9` (max). Example: `-ezlib,1,6,9`.
  - zstd: default is level 3. Common picks: `1` (fastest), `3` (default-ish), `5` or `7` (higher ratio). Example: `-ezstd,1,3,5`.
  - fse: use one level, e.g., `-efse,12` (table_log=12).
  Combined example:
  ```bash
  ./lzbench -efse,1/zstd,1,3,5/lz4/zlib,1,6,9 \
    -r ../scl/benchmark/datasets/silesia \
    -t2,2 -j1 \
    > ../scl/benchmark/benchmark_results/lzbench_silesia_fse_trimmed.txt
  ```

## Comparable codecs to sanity-check against
- `snappy` (very light LZ + Huffman; good speed baseline)
- `lzf`, `lzjb`, `brieflz`, `fastlz` (lightweight LZ; moderate ratios)
- `memcpy` (no compression; ceiling for speed)
- Heavier baselines (`lz4`, `zlib`, `zstd`) if you want to see the gap to full LZ+entropy stacks

  Tips to avoid wall-clock timeouts when running under wrappers/CI:
  - Limit scope: point `-r` at a single file instead of the whole dataset.
  - Shorten timed loops: use smaller `-tX,Y` (e.g., `-t0.5,0.5`) or fixed iterations via `-t0,0 -i1,1`.

  Other lzbench codecs (see `lzbench/bench/codecs.h`):
  - Very light LZ: `memlz`, `brieflz`, `fastlz`, `lzf`, `lzjb`, `lzrw`, `yappy`
  - Apple: `lzfse`, `lzvn`
  - Google/Meta: `snappy`, `density`
  - Heavier transforms: `bsc`, `brotli`, `bzip2`, `bzip3`
  - Speed ceiling: `memcpy`

### FiniteStateEntropy fullbench (entropy-only)

This codec has been added to Yann Collet's `fullbench` to compare entropy-only speed/ratio against upstream FSE/Huff0/zlibh.

**Build** (from repo root, after building `cpp/build/libscl_fse.a`):
```bash
# Build our C++ lib (if not already)
cmake -S cpp -B cpp/build -DCMAKE_BUILD_TYPE=Release
cmake --build cpp/build

# Build fullbench with our codec wired in (targets live in FiniteStateEntropy/programs)
make -C FiniteStateEntropy/programs fullbench
```

Or use `make all` which builds everything including fullbench.

Run fullbench on the default synthetic block (32 KB) or a file. New cases:
- `-b90/91`: `scl_fse` level 1 compress/decompress (MSB single-block)
- `-b92/93`: level 2 (LSB single-block)
- `-b94/95`: level 4 (framed 32 KiB, wide writer)

Examples:
```bash
# Synthetic 32 KB block (default)
./FiniteStateEntropy/programs/fullbench -b90       # scl_fse level 1 compress
./FiniteStateEntropy/programs/fullbench -b91       # scl_fse level 1 decompress

# On a real file (e.g., Silesia/webster)
./FiniteStateEntropy/programs/fullbench -b90 -B32768 ../scl/benchmark/datasets/silesia/webster

# Compare to upstream FSE/Huff0/zlibh (see fullbench cases, e.g., -b9 for FSE_compress)
./FiniteStateEntropy/programs/fullbench -b9  -B32768 ../scl/benchmark/datasets/silesia/webster   # FSE_compress
./FiniteStateEntropy/programs/fullbench -b20 -B32768 ../scl/benchmark/datasets/silesia/webster   # HUF_compress
```

`fullbench` defaults to generating its own synthetic block if no file is provided; use `-B` to control block size and pass a filename to benchmark on real data.

### Fullbench synthetic table (with scl_fse)

To recreate the synthetic Proba80/14/02 table (Huff0/FSE/zlibh) plus our `scl_fse` entries, run the full benchmark sweep on generated data (32 KiB blocks by default):
```bash
# Build everything fresh
cmake -S cpp -B cpp/build -DCMAKE_BUILD_TYPE=Release
cmake --build cpp/build
make -C FiniteStateEntropy/programs clean fullbench

# Run all bench cases (includes Huff0/FSE/zlibh and scl_fse levels 1/2/4)
./FiniteStateEntropy/programs/fullbench -i1 -b0 -B32768 \
  > scl/benchmark/benchmark_results/fullbench_proba_sclfse.txt
```

The generated table in the log will mirror the README's Proba80/14/02 section and append `scl_fse` rows for levels 1/2/4 (bench IDs 90/92/94). Use `-B` to change block size or pass a filename to benchmark real data instead of the synthetic probagen.

## Dataset requirements

Both lzbench and fullbench require datasets to be downloaded first. Run `make datasets` from the repo root (or `make all` which includes datasets), or see `FSE_PROJECT_README.md` for manual download instructions.