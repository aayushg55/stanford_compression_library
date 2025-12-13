# Efficient FSE: Project Overview

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

```bash
# Build (from repo root)
cmake -S cpp -B cpp/build -DSCL_FSE_BUILD_PYBIND=ON \
  -Dpybind11_DIR=$(python -m pybind11 --cmakedir)
cmake --build cpp/build

# Run parity tests
python -m pytest scl/tests/integration/test_fse_cpp_parity.py
```

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

- **Core library headers** (`cpp/include/scl/fse/`):
  - `fse.hpp`: main FSE API, `FSEParams`, `FSETables`, encoder/decoder interfaces
  - `bitio.hpp`: bit I/O utilities (MSB/LSB readers/writers)
  - `frame.hpp`: frame/stream encoding and decoding utilities
  - `levels.hpp`: `FSELevel` enum and factory functions

- **Core library sources** (`cpp/src/`):
  - `fse.cpp`: FSE table construction, normalization, spreading, encoder/decoder implementations
  - `frame.cpp`: `encode_stream`/`decode_stream` for multi-block framing
  - `pybind_module.cpp`: pybind11 bindings to expose C++ FSE to Python for parity testing
  - `main.cpp`: example/demo binary (`fse_example`)

- **Build system**: `cpp/CMakeLists.txt`
  - Builds static library `libscl_fse.a`
  - Optional targets: `fse_example`, `scl_fse_cpp` (pybind module)
  - See `cpp/README.md` for detailed build instructions

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

**Individual build commands:**

**lzbench** (full pipeline comparison):
```bash
cd lzbench
make -j$(sysctl -n hw.ncpu)
./lzbench -efse,12/zstd,1/lz4/zlib -r ../scl/benchmark/datasets/silesia -t2,2 -j1
```

**fullbench** (entropy-only comparison):
```bash
# Build fullbench (after building cpp/build/libscl_fse.a)
make -C FiniteStateEntropy/programs fullbench

# Run
./FiniteStateEntropy/programs/fullbench -b90 -B32768 scl/benchmark/datasets/silesia/webster
```

See `cpp/README.md` for detailed C++ benchmark instructions.

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

- **C++ detailed reference**: `cpp/README.md` (build options, API details, advanced benchmarking)
- **Project milestone report**: `project_milestone.md`
- **Poster**: `Project_poster/main.tex`
