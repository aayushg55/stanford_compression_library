# Efficient FSE: Project Overview

> **Built on**: This project is built on top of the [Stanford Compression Library (SCL)](SCL_README.md), which provides the framework and infrastructure for compression algorithm implementations.

A Finite State Entropy (FSE) project inside the Stanford Compression Library (SCL) with two matching implementations:
- **Python reference**: clear, tested, bitstream definition.
- **C++ core port**: mirrors the Python bitstream for a single-block, single-state codec, with faster LSB bit I/O and bindings.

Integrations into standard benchmarks (lzbench, fullbench) to compare against upstream FSE/Huff0 and real-world codecs (zstd/zlib/lz4).

## Quick Start

### Python

```bash
# Install dependencies
pip install -e .

# Run FSE tests (Python tests always run; C++ tests skip if module not built)
make test-fse

# Fetch datasets (required for benchmarks)
make datasets

# Run Python benchmarks
python scl/benchmark/benchmark_fse.py --dataset silesia
```

### C++

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

### Datasets

Benchmarks require datasets. Fetch them with:
```bash
make datasets
```

Or manually download from:
- Silesia: https://sun.aei.polsl.pl/~sdeor/corpus/silesia.zip
- Canterbury/Calgary/etc: https://corpus.canterbury.ac.nz/resources/

## Implementation Files

### Python Reference Implementation

- **Main implementation**: `scl/compressors/fse.py`
  - `FSEParams`: holds frequencies, table_log, table_size, normalized frequencies
  - `FSEEncoder`/`FSEDecoder`: block-level encode/decode, inherit from `DataEncoder`/`DataDecoder`
  - Core algorithm: normalization, FSE spread, decode/encode table construction
  - Block format: `[block_size (32 bits)] [final_state_offset (table_log bits)] [payload bits]`

- **Tests**:
  - **Unit tests**:
    - `scl/tests/unit/test_fse_normalization.py`: frequency normalization tests
    - `scl/tests/unit/test_fse_spreading.py`: symbol spreading algorithm tests
    - `scl/tests/unit/test_fse_tables.py`: decode and encode table structure tests
  - **Integration tests**:
    - `scl/tests/integration/test_fse_end_to_end.py`: end-to-end encode/decode tests
    - `scl/tests/integration/test_fse_cpp_parity.py`: Python/C++ bitstream parity verification

- **Python benchmarks**: `scl/benchmark/benchmark_fse.py`: Python-level timing and compression ratio measurements

### C++ Implementation

**Core headers** (`cpp/include/scl/fse/`):
- `fse.hpp`: Main FSE API, `FSEParams`, `FSETables`, encoder/decoder interfaces
- `bitio.hpp`: Bit I/O utilities (MSB/LSB readers/writers) for optimized bitstream handling
- `frame.hpp`: Frame/stream encoding and decoding utilities
- `levels.hpp`: `FSELevel` enum and factory functions

**Core sources** (`cpp/src/`):
- `fse.cpp`: FSE table construction, normalization, spreading, encoder/decoder implementations
- `frame.cpp`: `encode_stream`/`decode_stream` for multi-block framing with per-block headers
- `pybind_module.cpp`: pybind11 bindings to expose C++ FSE to Python for parity testing
- `main.cpp`: example/demo binary (`fse_example`)

The `bitio.hpp` header provides optimized bit readers and writers (MSB-first and LSB-first) that are used by the encoder/decoder implementations. The `frame.cpp` source implements multi-block framing, allowing the codec to handle arbitrarily large inputs by splitting them into blocks with independent frequency counts and FSE tables.

**Related components:**
- **Python wrapper** (`scl/external_compressors/fse_cpp_wrapper.py`): Bridges arbitrary Python symbols to dense integer IDs expected by the C++ implementation
- **Benchmark shims**: 
  - `lzbench/bench/lz_fse_scl.cpp`: Registers FSE with lzbench for full pipeline comparison
  - `FiniteStateEntropy/programs/scl_fse_wrapper.cpp`: Registers FSE with fullbench for entropy-only comparison

## Benchmarks

### Python Benchmarks

```bash
python scl/benchmark/benchmark_fse.py --dataset silesia --codecs fse,zlib,zstd
```

Compares FSE against other SCL codecs (rANS, tANS, Huffman) and external codecs (zlib, zstd).

### C++ Benchmarks

This project integrates with two external benchmarking tools. Quick start:

```bash
# Build everything (datasets, C++ lib, fullbench, lzbench)
make all
```

**Detailed instructions:**

#### lzbench

`lzbench` (third-party, cloned under `lzbench/`): a widely used in-memory benchmark. It preloads each file into RAM and loops encode/decode for a fixed time, reusing preallocated buffers and checking correctness once per codec.

**Integration**: The FSE codec is registered with lzbench via `lzbench/bench/lz_fse_scl.cpp`, which implements the lzbench codec interface (`lzbench_fse_init`, `lzbench_fse_compress`, `lzbench_fse_decompress`). This shim wraps the C++ FSE framed API (`encode_stream`/`decode_stream`) to enable comparison with production codecs like zstd/zlib/lz4. Separate shims are used because `lzbench` uses a stateful interface (init/deinit with context) while `fullbench` uses a stateless interface (level passed per call).

To build and run with local CPU tuning:
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

If you don't want full level sweeps, pick a few representative levels:
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

**Comparable codecs to sanity-check against:**
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

#### FiniteStateEntropy fullbench (entropy-only)

This codec has been added to Yann Collet's `fullbench` to compare entropy-only speed/ratio against upstream FSE/Huff0/zlibh.

**Integration**: The FSE codec is registered with fullbench via `FiniteStateEntropy/programs/scl_fse_wrapper.cpp`, which implements the fullbench codec interface (`sclfse_compress_level`, `sclfse_decompress_level`). This wrapper uses the C++ FSE framed API to enable direct comparison with upstream FSE, Huff0, and zlibh implementations.

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

**Fullbench synthetic table (with scl_fse):**

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

## Key Algorithm Components

- **Normalization**: Proportional scaling to power-of-two table size (`2^tableLog`), with fix-up to ensure exact sum
- **FSE spread**: Co-prime step algorithm to distribute symbols across state space according to normalized frequencies
- **Decode table**: Per-state entries `(symbol, nbBits, newStateBase)` where `nbBits` is state-dependent
- **Encode tables**: `tableU16` (shared next-state mapping) + per-symbol `symbolTT` transforms `(deltaNbBits, deltaFindState)`
- **Block format**: `[block_size][state_offset][payload_bits]` (big-endian bits per byte to match Python bitarray)

## Performance Characteristics

- **Python path**: Passes unit tests for normalization/table build/round-trip; faster than SCL rANS/tANS but far slower than native codecs; serves as the reference
- **C++ path**: Parity with Python; MSB/LSB encoder/decoder; framed `encode_stream/decode_stream`; pybind11 bindings to reuse Python tests; faster LSB bitreader in place

## Documentation

- **Project milestone report**: `project_milestone.md`
- **Poster**: `poster/main.tex`
