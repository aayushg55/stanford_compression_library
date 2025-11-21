# Project Milestone: Implementing Finite State Entropy (FSE) for Efficient Compression

**Course:** EE274 – Data Compression  
**Student:** Aayush Gupta  
**Mentor:** Pulkit  
**Repo:** https://github.com/aayushg55/stanford_compression_library

---

## 1. Introduction

Modern lossless compressors depend critically on the entropy coding stage: given an LZ-style or predictive front-end, the entropy coder must convert a stream of symbols to bits at rates close to the Shannon limit while remaining fast enough not to bottleneck the pipeline. Classical choices are Huffman coding (very fast, but limited to integer bit-lengths) and arithmetic/range coding (near-optimal rates, but traditionally slower and more complex).

Finite State Entropy (FSE), used in Zstandard, is a practical table-based realization of Asymmetric Numeral Systems (ANS). It maintains a single integer “state” that evolves as symbols are encoded or decoded, emitting or consuming small bursts of bits whenever the state leaves a fixed range. In practice, FSE achieves compression ratios comparable to arithmetic coding while approaching speeds of Huffman coding.

This project aims to reimplement and analyze FSE in a pedagogical setting. First, I implement a pure-Python FSE encoder/decoder inside the Stanford Compression Library (SCL) as a readable, well-documented reference. Then I port the implementation to C++ and incrementally add low-level optimizations inspired by Yann Collet’s FiniteStateEntropy library and Zstandard. The broader goal is to understand how ANS moves from theory to production-grade code: how symbol frequencies are normalized, how state tables are built, why the decode loop can be written as a tiny branchless kernel, and how each optimization trades memory, complexity, and speed.

---

## 2. Literature and Code Review

Jarek Duda’s ANS framework provides entropy coders that match arithmetic coding’s compression efficiency while using simpler operations [1]. Instead of emitting variable-length codewords or maintaining an interval, ANS keeps a single integer state that jointly encodes the past bitstream and the next symbol to be decoded. Each symbol update applies a bijection between states and bit sequences, with symbol probabilities reflected in how many states each symbol occupies. Variants include range-based ANS (rANS) and table-based ANS (tANS). FSE is a highly optimized tANS realization [2].

Yann Collet’s blog series on Finite State Entropy explains how to turn tANS theory into a fast implementation [2]. The decoder maintains a state in `[0, 2^tableLog)`, and a decoding table indexed by state stores the symbol, the number of bits to read, and a base for the next state. Each decode step consists of a table lookup, a bit read, and an addition, giving a very small, predictable hot loop. Encoding runs in reverse order: starting from a final state, the encoder processes the message backwards, decides how many bits to flush, emits them, and transitions using a shared `stateTable` plus per-symbol transforms. Collet also discusses how to normalize symbol counts so they sum to `2^tableLog` and how to “spread” symbols over the state space using modular stepping to avoid clustering.

The FiniteStateEntropy GitHub repository is the canonical C implementation of FSE and a related Huffman coder (Huff0) [3]. It exposes public APIs (`FSE_compress`, `FSE_decompress`) and internal structures that closely match the blog descriptions: decoder entries storing `(symbol, nbBits, newState)`, encoder transforms that encode per-symbol subranges, and a compact shared `stateTable`. Benchmarks in the repository show FSE achieving near-Shannon compression and very high decode throughput on synthetic distributions.

Zstandard integrates FSE as its main entropy coder for literals and for length/offset codes, using block-level histograms, adaptive `tableLog` selection, and multi-threaded table build and compression [4]. Within SCL, existing pure-Python entropy coders (Huffman, rANS, tANS, arithmetic) and wrappers around zlib/zstd provide practical baselines and reference implementations for both behavior and performance [5].


---

## 3. Methods

This section outlines what this project implements and how it will be evaluated.

### 3.1 Goals

The goals are:

1. A clear, well-documented FSE implementation in pure Python within SCL, suitable as a pedagogical reference.
2. A C++ implementation that mirrors the Python version but adds low-level optimizations to approach production-grade performance.
3. A quantitative comparison of FSE against other entropy coders in SCL and against zlib/zstd on standard benchmarks.

### 3.2 Implementation Plan

The Python implementation in SCL is already substantially in place. It includes histogram computation, normalization that maps raw counts to integer weights summing to `2^tableLog`, and decoding table construction that spreads each symbol across the state space according to its normalized weight. The DTable stores, for each state, the symbol, the number of bits to read, and a base for the next state. The encoding side builds per-symbol transforms and a shared `stateTable`, following the structure described by Collet and the FiniteStateEntropy C code. A simple LSB-first bitstream abstraction underlies both encoder and decoder, and the core loops are written as small, state-driven kernels.

The next stage is a C++ port of this logic, either as part of SCL or as a closely coupled library. The baseline C++ version will follow the Python structure closely to ensure correctness. Afterwards, I will incrementally add optimizations: more compact table layouts for better cache locality, branchless encoding using the `deltaNbBits` trick, tuned `tableLog` policies, and inlined 64-bit bit I/O primitives. The aim is to isolate which micro-optimizations matter most in practice.

### 3.3 Evaluation Plan

Evaluation will use both synthetic and standard benchmark data. Synthetic tests will use simple small alphabets (e.g., symbols A, B, C with fixed distributions) to check behavior against theory and to compare directly with SCL’s pure-Python Huffman, rANS, and tANS coders. For more realistic workloads, I plan to use standard corpora such as the Canterbury or Silesia suites.

Metrics will include compression ratio (bits per symbol or compressed/original size) and encode/decode throughput in MB/s. Pure-Python FSE will be compared against the other pure-Python coders in SCL. The C++ implementation will be compared both through the Python harness (acknowledging Python overhead) and, if time permits, via a small standalone C++ driver to measure “clean” performance. Wrappers around zlib and Zstandard in SCL provide additional baselines that represent mature, highly optimized C libraries.

---

## 4. Progress Report

### 4.1 Completed So Far

On the theory side, I have read and summarized Duda’s ANS paper and Collet’s FSE blog series, focusing on the table-based (tANS) formulation and FSE’s decoding, encoding, and table-construction details. I have also inspected the FiniteStateEntropy repository to understand how these ideas are realized in C and how Zstandard uses FSE in a full compressor.

On the implementation side, a pure-Python FSE encoder/decoder is implemented in SCL. It includes histogram and normalization routines, symbol spreading and DTable construction, CTable and `stateTable` construction, and bitstream utilities. There are unit tests for normalization and table construction as well as end-to-end round-trip tests on random and simple structured data, which confirm correct decoding.

I have run preliminary benchmarks on synthetic small-alphabet data comparing pure-Python FSE to SCL’s rANS, tANS, and Huffman coders, as well as to wrappers around zlib and Zstandard. In pure Python, FSE achieves faster decode speeds than the rANS and tANS implementations, but remains slower than the pure-Python Huffman coder, which is consistent with Huffman having the lightest inner loop. All pure-Python implementations, including FSE, currently achieve sub–1 MB/s decode speeds. The zlib and zstd wrappers, despite Python overhead in the benchmarking harness, are still much faster than any pure-Python implementation, as expected from optimized C libraries.

Overall, the “basic goal” has been reached at the Python level: FSE matches other ANS variants in compression behavior, is faster than the existing pure-Python rANS/tANS implementations, and slower than Huffman, while remaining far from the performance of optimized C-based coders.

### 4.2 Plan for Remaining Weeks

In the next 1–2 weeks, I plan to clean up and slightly harden the Python implementation (edge cases, documentation, and tests) while designing the baseline C++ FSE implementation. The initial C++ version will prioritize correctness and API compatibility with the existing Python code, using simple data structures and clear control flow.

After that, I will focus on performance work: packing tables for cache locality, using branchless transforms for the encoder, tuning `tableLog`, and inlining bit I/O. In parallel, I will improve the benchmarking setup to reduce Python overhead (for example by batching operations and minimizing Python/C crossings) and, if time permits, add a standalone C++ benchmark. Final experiments will include compression and throughput comparisons on synthetic distributions and on standard corpora, producing plots and tables that can be reused directly in the final report.

---

## References

[1] J. Duda, *Asymmetric numeral systems: entropy coding combining speed of Huffman coding with compression rate of arithmetic coding*, arXiv, 2013.  
[2] Y. Collet, “Finite State Entropy – a new breed of entropy coder” and follow-up posts, fastcompression.blogspot.com.  
[3] Y. Collet, **FiniteStateEntropy** library (FSE/Huff0), GitHub.  
[4] Y. Collet et al., **Zstandard** compression format and source code.  
[5] Stanford Compression Library (SCL) documentation and existing entropy coder implementations.
