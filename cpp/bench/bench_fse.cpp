// Native benchmarking harness for the C++ FSE implementation and a few reference codecs.
// Focused on accurate timing with minimal overhead and explicit separation of setup vs hot loop.

#include <algorithm>
#include <chrono>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <limits>
#include <numeric>
#include <optional>
#include <sstream>
#include <string>
#include <string_view>
#include <tuple>
#include <utility>
#include <vector>

#include "scl/fse/fse.hpp"

#ifdef SCL_BENCH_HAVE_ZSTD
#include <zstd.h>
#endif

#ifdef SCL_BENCH_HAVE_ZLIB
#include <zlib.h>
#endif

#ifdef SCL_BENCH_HAVE_LZ4
#include <lz4.h>
#endif

using scl::fse::EncodedBlock;
using scl::fse::FSEEncoderMSB;
using scl::fse::FSEDecoderMSB;
using scl::fse::FSEParams;
using scl::fse::FSETables;

namespace fs = std::filesystem;
using Clock = std::chrono::high_resolution_clock;

struct Options {
    fs::path dataset_dir;
    std::vector<std::string> codecs{"fse", "fse_hot", "zstd", "zlib", "lz4", "memcpy"};
    uint32_t table_log = 12;
    double min_time_ms = 200.0;
    int warmup_iters = 1;
    bool include_setup = false; // if true, also report histogram + table build time.
    bool memcpy_baseline = false;
};

struct BenchMetrics {
    std::string name;
    bool ok = true;
    size_t original_bytes = 0;
    size_t compressed_bytes = 0;
    size_t compressed_bits = 0;
    double bits_per_byte = 0.0;
    double ratio = 0.0;
    double hist_ms = 0.0;
    double table_ms = 0.0;
    double encode_ms = 0.0;
    double decode_ms = 0.0;
    double encode_ms_median = 0.0;
    double decode_ms_median = 0.0;
    double encode_ms_std = 0.0;
    double decode_ms_std = 0.0;
    double encode_throughput_mb_s = 0.0;
    double decode_throughput_mb_s = 0.0;
};

struct TimeStats {
    double avg_ms = 0.0;
    double median_ms = 0.0;
    double std_ms = 0.0;
};

inline void finalize_metrics(BenchMetrics& m,
                             size_t compressed_bytes,
                             size_t compressed_bits,
                             const TimeStats& enc,
                             const TimeStats& dec,
                             double hist_ms = 0.0,
                             double table_ms = 0.0) {
    m.compressed_bytes = compressed_bytes;
    m.compressed_bits = compressed_bits;
    m.encode_ms = enc.avg_ms;
    m.decode_ms = dec.avg_ms;
    m.encode_ms_median = enc.median_ms;
    m.decode_ms_median = dec.median_ms;
    m.encode_ms_std = enc.std_ms;
    m.decode_ms_std = dec.std_ms;
    m.hist_ms = hist_ms;
    m.table_ms = table_ms;
    m.bits_per_byte =
        m.original_bytes > 0 ? static_cast<double>(m.compressed_bits) / m.original_bytes : 0.0;
    m.ratio = m.compressed_bits > 0
                  ? static_cast<double>(m.original_bytes * 8) /
                        static_cast<double>(m.compressed_bits)
                  : 0.0;
    const double size_mb = static_cast<double>(m.original_bytes) / 1'000'000.0;
    m.encode_throughput_mb_s = (m.encode_ms > 0.0) ? (size_mb / (m.encode_ms / 1000.0)) : 0.0;
    m.decode_throughput_mb_s = (m.decode_ms > 0.0) ? (size_mb / (m.decode_ms / 1000.0)) : 0.0;
}

template <typename Range1, typename Range2>
bool ranges_equal(const Range1& a, const Range2& b) {
    if (a.size() != b.size()) return false;
    return std::equal(a.begin(), a.end(), b.begin());
}

template <typename DecodeFn>
void verify_decode_once(const std::vector<uint8_t>& original, DecodeFn&& fn, std::string_view name) {
    auto decoded = fn();
    if (!ranges_equal(decoded, original)) {
        throw std::runtime_error(std::string(name) + " decode mismatch");
    }
}

template <typename Fn>
TimeStats time_stats(Fn&& fn, int warmup_iters, double min_time_ms) {
    for (int i = 0; i < warmup_iters; ++i) {
        fn();
    }
    std::vector<double> samples;
    samples.reserve(16);
    double total_ms = 0.0;
    do {
        auto t0 = Clock::now();
        fn();
        auto t1 = Clock::now();
        const double ms =
            std::chrono::duration<double, std::milli>(t1 - t0).count();
        total_ms += ms;
        samples.push_back(ms);
    } while (total_ms < min_time_ms);
    TimeStats stats;
    if (!samples.empty()) {
        const double sum = std::accumulate(samples.begin(), samples.end(), 0.0);
        stats.avg_ms = sum / samples.size();
        auto sorted = samples;
        std::sort(sorted.begin(), sorted.end());
        stats.median_ms = sorted[sorted.size() / 2];
        double sq = 0.0;
        for (double v : samples) {
            const double d = v - stats.avg_ms;
            sq += d * d;
        }
        stats.std_ms = std::sqrt(sq / samples.size());
    }
    return stats;
}

std::vector<uint8_t> read_file_bytes(const fs::path& path) {
    std::ifstream ifs(path, std::ios::binary);
    if (!ifs) {
        throw std::runtime_error("Failed to open file: " + path.string());
    }
    ifs.seekg(0, std::ios::end);
    const std::streampos size = ifs.tellg();
    ifs.seekg(0, std::ios::beg);
    std::vector<uint8_t> data(static_cast<size_t>(size));
    if (!ifs.read(reinterpret_cast<char*>(data.data()), size)) {
        throw std::runtime_error("Failed to read file: " + path.string());
    }
    return data;
}

std::vector<uint32_t> build_histogram(const std::vector<uint8_t>& data,
                                      double* hist_ms_out) {
    auto t0 = Clock::now();
    std::vector<uint32_t> counts(256, 0);
    for (uint8_t b : data) counts[b]++;
    auto t1 = Clock::now();
    if (hist_ms_out) {
        *hist_ms_out =
            std::chrono::duration<double, std::milli>(t1 - t0).count();
    }
    return counts;
}

struct FSECodec {
    explicit FSECodec(FSEParams p) : params(std::move(p)) {}
    FSEParams params;
    std::shared_ptr<FSETables> tables;
    std::unique_ptr<FSEEncoderMSB> encoder;
    std::unique_ptr<FSEDecoderMSB> decoder;
};

FSECodec make_fse_codec(const std::vector<uint32_t>& counts, uint32_t table_log, double* table_ms_out) {
    auto t0 = Clock::now();
    FSECodec codec(FSEParams(counts, table_log));
    codec.tables = std::make_shared<FSETables>(codec.params);
    codec.encoder = std::make_unique<FSEEncoderMSB>(*codec.tables);
    codec.decoder = std::make_unique<FSEDecoderMSB>(*codec.tables);
    auto t1 = Clock::now();
    if (table_ms_out) {
        *table_ms_out =
            std::chrono::duration<double, std::milli>(t1 - t0).count();
    }
    return codec;
}

#ifdef SCL_BENCH_HAVE_ZSTD
struct ZstdCodec {
    ZSTD_CCtx* cctx = ZSTD_createCCtx();
    ZSTD_DCtx* dctx = ZSTD_createDCtx();
    int level = 3;
    ~ZstdCodec() {
        ZSTD_freeCCtx(cctx);
        ZSTD_freeDCtx(dctx);
    }
};
#endif

#ifdef SCL_BENCH_HAVE_ZLIB
struct ZlibCodec {
    int level = Z_DEFAULT_COMPRESSION;
};
#endif

#ifdef SCL_BENCH_HAVE_LZ4
struct LZ4Codec {};
#endif

BenchMetrics bench_fse_full(const std::vector<uint8_t>& data, uint32_t table_log,
                            int warmup, double min_time_ms) {
    BenchMetrics m;
    m.name = "FSE";
    m.original_bytes = data.size();

    double hist_ms = 0.0;
    auto counts = build_histogram(data, &hist_ms);
    double table_ms = 0.0;
    auto codec = make_fse_codec(counts, table_log, &table_ms);

    EncodedBlock encoded = codec.encoder->encode_block(data);

    auto encode_fn = [&]() {
        volatile auto tmp = codec.encoder->encode_block(data);
        (void)tmp;
    };
    const TimeStats enc_stats = time_stats(encode_fn, warmup, min_time_ms);

    // Verify correctness once.
    verify_decode_once(data, [&]() {
        auto res = codec.decoder->decode_block(encoded.bytes.data(), encoded.bit_count);
        return res.symbols;
    }, "FSE");

    auto decode_fn = [&]() {
        auto res = codec.decoder->decode_block(encoded.bytes.data(), encoded.bit_count);
        if (res.symbols.size() != data.size()) {
            throw std::runtime_error("FSE decode size mismatch");
        }
    };
    const TimeStats dec_stats = time_stats(decode_fn, warmup, min_time_ms);

    finalize_metrics(m, encoded.bytes.size(), encoded.bit_count, enc_stats, dec_stats, hist_ms,
                     table_ms);
    return m;
}

BenchMetrics bench_fse_hot(const std::vector<uint8_t>& data, uint32_t table_log,
                           int warmup, double min_time_ms) {
    BenchMetrics m;
    m.name = "FSE_hot";
    m.original_bytes = data.size();

    auto counts = build_histogram(data, nullptr);
    auto codec = make_fse_codec(counts, table_log, nullptr);
    EncodedBlock encoded = codec.encoder->encode_block(data);

    auto encode_fn = [&]() {
        volatile auto tmp = codec.encoder->encode_block(data);
        (void)tmp;
    };
    const TimeStats enc_stats = time_stats(encode_fn, warmup, min_time_ms);

    // Verify correctness once.
    verify_decode_once(data, [&]() {
        auto res = codec.decoder->decode_block(encoded.bytes.data(), encoded.bit_count);
        return res.symbols;
    }, "FSE");

    auto decode_fn = [&]() {
        auto res = codec.decoder->decode_block(encoded.bytes.data(), encoded.bit_count);
        if (res.symbols.size() != data.size()) {
            throw std::runtime_error("FSE decode size mismatch");
        }
    };
    const TimeStats dec_stats = time_stats(decode_fn, warmup, min_time_ms);

    finalize_metrics(m, encoded.bytes.size(), encoded.bit_count, enc_stats, dec_stats, 0.0, 0.0);
    return m;
}

#ifdef SCL_BENCH_HAVE_ZSTD
BenchMetrics bench_zstd(const std::vector<uint8_t>& data, int level,
                        int warmup, double min_time_ms) {
    BenchMetrics m;
    m.name = "zstd";
    m.original_bytes = data.size();
    ZstdCodec codec;
    codec.level = level;

    size_t bound = ZSTD_compressBound(data.size());
    std::vector<uint8_t> compressed(bound);
    size_t comp_size = ZSTD_compressCCtx(codec.cctx, compressed.data(), compressed.size(),
                                         data.data(), data.size(), codec.level);
    if (ZSTD_isError(comp_size)) {
        throw std::runtime_error("zstd compress failed");
    }
    compressed.resize(comp_size);
    m.compressed_bytes = compressed.size();
    m.compressed_bits = compressed.size() * 8;

    // Verify correctness once.
    verify_decode_once(data, [&]() {
        std::vector<uint8_t> decompressed(data.size());
        size_t out = ZSTD_decompressDCtx(codec.dctx, decompressed.data(), decompressed.size(),
                                         compressed.data(), compressed.size());
        if (ZSTD_isError(out) || out != decompressed.size()) {
            throw std::runtime_error("zstd decompress mismatch");
        }
        return decompressed;
    }, "zstd");

    auto encode_fn = [&]() {
        std::vector<uint8_t> scratch(bound);
        size_t sz = ZSTD_compressCCtx(codec.cctx, scratch.data(), scratch.size(),
                                      data.data(), data.size(), codec.level);
        if (ZSTD_isError(sz)) {
            throw std::runtime_error("zstd compress failed: " + std::string(ZSTD_getErrorName(sz)));
        }
        compressed = scratch;
        compressed.resize(sz);
    };
    const TimeStats enc_stats = time_stats(encode_fn, warmup, min_time_ms);

    std::vector<uint8_t> decompressed(data.size());
    auto decode_fn = [&]() {
        size_t out = ZSTD_decompressDCtx(codec.dctx, decompressed.data(), decompressed.size(),
                                         compressed.data(), compressed.size());
        if (ZSTD_isError(out)) {
            throw std::runtime_error("zstd decompress failed: " +
                                     std::string(ZSTD_getErrorName(out)));
        }
        if (out != decompressed.size()) {
            throw std::runtime_error("zstd decompress size mismatch");
        }
    };
    const TimeStats dec_stats = time_stats(decode_fn, warmup, min_time_ms);

    finalize_metrics(m, m.compressed_bytes, m.compressed_bits, enc_stats, dec_stats);
    return m;
}
#endif

#ifdef SCL_BENCH_HAVE_ZLIB
BenchMetrics bench_zlib(const std::vector<uint8_t>& data, int level,
                        int warmup, double min_time_ms) {
    BenchMetrics m;
    m.name = "zlib";
    m.original_bytes = data.size();

    uLongf bound = compressBound(static_cast<uLong>(data.size()));
    std::vector<uint8_t> compressed(bound);
    uLongf comp_size = bound;
    if (compress2(compressed.data(), &comp_size, data.data(), data.size(), level) != Z_OK) {
        throw std::runtime_error("zlib compress failed");
    }
    compressed.resize(comp_size);
    m.compressed_bytes = compressed.size();
    m.compressed_bits = compressed.size() * 8;

    // Verify correctness once.
    verify_decode_once(data, [&]() {
        std::vector<uint8_t> decompressed(data.size());
        uLongf out = static_cast<uLongf>(decompressed.size());
        int rc = uncompress(decompressed.data(), &out, compressed.data(), compressed.size());
        if (rc != Z_OK || out != decompressed.size()) {
            throw std::runtime_error("zlib decompress mismatch");
        }
        return decompressed;
    }, "zlib");

    auto encode_fn = [&]() {
        uLongf sz = bound;
        volatile int rc = compress2(compressed.data(), &sz, data.data(), data.size(), level);
        (void)rc;
    };
    const TimeStats enc_stats = time_stats(encode_fn, warmup, min_time_ms);

    std::vector<uint8_t> decompressed(data.size());
    auto decode_fn = [&]() {
        uLongf out = static_cast<uLongf>(decompressed.size());
        int rc = uncompress(decompressed.data(), &out, compressed.data(), compressed.size());
        if (rc != Z_OK || out != decompressed.size()) {
            throw std::runtime_error("zlib decompress failed");
        }
    };
    const TimeStats dec_stats = time_stats(decode_fn, warmup, min_time_ms);

    finalize_metrics(m, m.compressed_bytes, m.compressed_bits, enc_stats, dec_stats);
    return m;
}
#endif

#ifdef SCL_BENCH_HAVE_LZ4
BenchMetrics bench_lz4(const std::vector<uint8_t>& data,
                       int warmup, double min_time_ms) {
    BenchMetrics m;
    m.name = "lz4";
    m.original_bytes = data.size();

    int bound = LZ4_compressBound(static_cast<int>(data.size()));
    std::vector<uint8_t> compressed(bound);
    int comp_size = LZ4_compress_default(
        reinterpret_cast<const char*>(data.data()), reinterpret_cast<char*>(compressed.data()),
        static_cast<int>(data.size()), bound);
    if (comp_size <= 0) {
        throw std::runtime_error("lz4 compress failed");
    }
    compressed.resize(comp_size);
    m.compressed_bytes = compressed.size();
    m.compressed_bits = compressed.size() * 8;

    // Verify correctness once.
    verify_decode_once(data, [&]() {
        std::vector<uint8_t> decompressed(data.size());
        int out = LZ4_decompress_safe(
            reinterpret_cast<const char*>(compressed.data()),
            reinterpret_cast<char*>(decompressed.data()),
            static_cast<int>(compressed.size()), static_cast<int>(decompressed.size()));
        if (out != static_cast<int>(decompressed.size())) {
            throw std::runtime_error("lz4 decompress mismatch");
        }
        return decompressed;
    }, "lz4");

    auto encode_fn = [&]() {
        volatile int sz = LZ4_compress_default(
            reinterpret_cast<const char*>(data.data()), reinterpret_cast<char*>(compressed.data()),
            static_cast<int>(data.size()), bound);
        (void)sz;
    };
    const TimeStats enc_stats = time_stats(encode_fn, warmup, min_time_ms);

    std::vector<uint8_t> decompressed(data.size());
    auto decode_fn = [&]() {
        int out = LZ4_decompress_safe(
            reinterpret_cast<const char*>(compressed.data()),
            reinterpret_cast<char*>(decompressed.data()),
            static_cast<int>(compressed.size()), static_cast<int>(decompressed.size()));
        if (out != static_cast<int>(decompressed.size())) {
            throw std::runtime_error("lz4 decompress failed");
        }
        if (!ranges_equal(decompressed, data)) {
            throw std::runtime_error("lz4 decompress mismatch");
        }
    };
    const TimeStats dec_stats = time_stats(decode_fn, warmup, min_time_ms);

    finalize_metrics(m, m.compressed_bytes, m.compressed_bits, enc_stats, dec_stats);
    return m;
}
#endif

BenchMetrics bench_memcpy(const std::vector<uint8_t>& data,
                          int warmup, double min_time_ms) {
    BenchMetrics m;
    m.name = "memcpy";
    m.original_bytes = data.size();
    std::vector<uint8_t> scratch(data.size());

    auto copy_fn = [&]() {
        std::memcpy(scratch.data(), data.data(), data.size());
    };
    const TimeStats enc_stats = time_stats(copy_fn, warmup, min_time_ms);
    const TimeStats dec_stats = time_stats(copy_fn, warmup, min_time_ms);

    finalize_metrics(m, data.size(), data.size() * 8, enc_stats, dec_stats);
    return m;
}

void print_metrics(const fs::path& file, const std::vector<BenchMetrics>& metrics,
                   bool include_setup) {
    std::cout << "\n" << std::string(120, '=') << "\n";
    std::cout << "File: " << file.filename().string() << " (" << metrics.front().original_bytes
              << " bytes)\n";
    std::cout << std::string(120, '=') << "\n";
    std::cout << std::left << std::setw(10) << "Codec"
              << std::setw(12) << "Bits/Byte"
              << std::setw(12) << "Ratio"
              << std::setw(15) << "Enc(ms)"
              << std::setw(15) << "Dec(ms)"
              << std::setw(15) << "Enc(md ms)"
              << std::setw(15) << "Dec(md ms)"
              << std::setw(15) << "Enc(std)"
              << std::setw(15) << "Dec(std)"
              << std::setw(15) << "Enc(MB/s)"
              << std::setw(15) << "Dec(MB/s)";
    if (include_setup) {
        std::cout << std::setw(12) << "Hist(ms)" << std::setw(12) << "Table(ms)";
    }
    std::cout << "\n" << std::string(120, '-') << "\n";
    for (const auto& m : metrics) {
        std::cout << std::left << std::setw(10) << m.name
                  << std::setw(12) << std::fixed << std::setprecision(3) << m.bits_per_byte
                  << std::setw(12) << std::fixed << std::setprecision(3) << m.ratio
                  << std::setw(15) << std::fixed << std::setprecision(3) << m.encode_ms
                  << std::setw(15) << std::fixed << std::setprecision(3) << m.decode_ms
                  << std::setw(15) << std::fixed << std::setprecision(3) << m.encode_ms_median
                  << std::setw(15) << std::fixed << std::setprecision(3) << m.decode_ms_median
                  << std::setw(15) << std::fixed << std::setprecision(3) << m.encode_ms_std
                  << std::setw(15) << std::fixed << std::setprecision(3) << m.decode_ms_std
                  << std::setw(15) << std::fixed << std::setprecision(3) << m.encode_throughput_mb_s
                  << std::setw(15) << std::fixed << std::setprecision(3) << m.decode_throughput_mb_s;
        if (include_setup) {
            std::cout << std::setw(12) << std::fixed << std::setprecision(3) << m.hist_ms
                      << std::setw(12) << std::fixed << std::setprecision(3) << m.table_ms;
        }
        std::cout << "\n";
    }
    std::cout << std::string(120, '=') << "\n";
}

Options parse_args(int argc, char** argv) {
    Options opt;
    for (int i = 1; i < argc; ++i) {
        std::string_view arg(argv[i]);
        auto next = [&]() -> std::string_view {
            if (i + 1 >= argc) {
                throw std::runtime_error("Missing value for argument: " + std::string(arg));
            }
            return std::string_view(argv[++i]);
        };
        if (arg == "--dataset") {
            opt.dataset_dir = fs::path(next());
        } else if (arg == "--codecs") {
            std::string list(next());
            opt.codecs.clear();
            std::stringstream ss(list);
            std::string item;
            while (std::getline(ss, item, ',')) {
                if (!item.empty()) opt.codecs.push_back(item);
            }
        } else if (arg == "--table-log") {
            opt.table_log = static_cast<uint32_t>(std::stoul(std::string(next())));
        } else if (arg == "--min-time-ms") {
            opt.min_time_ms = std::stod(std::string(next()));
        } else if (arg == "--warmup") {
            opt.warmup_iters = std::stoi(std::string(next()));
        } else if (arg == "--include-setup") {
            opt.include_setup = true;
        } else if (arg == "--memcpy-baseline") {
            opt.memcpy_baseline = true;
        } else if (arg == "--help" || arg == "-h") {
            std::cout << "Usage: bench_fse --dataset <dir> [--codecs fse,fse_hot,zstd,zlib,lz4] "
                         "[--table-log N] [--min-time-ms ms] [--warmup N] [--include-setup] "
                         "[--memcpy-baseline]\n";
            std::exit(0);
        } else {
            throw std::runtime_error("Unknown argument: " + std::string(arg));
        }
    }
    if (opt.dataset_dir.empty()) {
        throw std::runtime_error("--dataset is required");
    }
    return opt;
}

int main(int argc, char** argv) {
    try {
        Options opt = parse_args(argc, argv);
        if (!fs::exists(opt.dataset_dir) || !fs::is_directory(opt.dataset_dir)) {
            throw std::runtime_error("Dataset path is not a directory: " + opt.dataset_dir.string());
        }

        std::vector<fs::directory_entry> files;
        for (const auto& entry : fs::directory_iterator(opt.dataset_dir)) {
            if (entry.is_regular_file()) {
                files.push_back(entry);
            }
        }
        std::sort(files.begin(), files.end(),
                  [](const auto& a, const auto& b) { return a.file_size() < b.file_size(); });

        if (files.empty()) {
            std::cerr << "No files found in dataset directory\n";
            return 1;
        }

        std::cout << "Benchmarking dataset: " << opt.dataset_dir << "\n";
        std::cout << "Codecs: ";
        for (size_t i = 0; i < opt.codecs.size(); ++i) {
            if (i) std::cout << ", ";
            std::cout << opt.codecs[i];
        }
        std::cout << "\n";

        for (const auto& entry : files) {
            std::vector<uint8_t> data = read_file_bytes(entry.path());
            std::vector<BenchMetrics> metrics;

            for (const auto& name : opt.codecs) {
                try {
                    if (name == "fse") {
                        metrics.push_back(bench_fse_full(data, opt.table_log, opt.warmup_iters,
                                                         opt.min_time_ms));
                    } else if (name == "fse_hot") {
                        metrics.push_back(bench_fse_hot(data, opt.table_log, opt.warmup_iters,
                                                        opt.min_time_ms));
#ifdef SCL_BENCH_HAVE_ZSTD
                    } else if (name == "zstd") {
                        metrics.push_back(
                            bench_zstd(data, /*level=*/3, opt.warmup_iters, opt.min_time_ms));
#endif
#ifdef SCL_BENCH_HAVE_ZLIB
                    } else if (name == "zlib") {
                        metrics.push_back(
                            bench_zlib(data, Z_DEFAULT_COMPRESSION, opt.warmup_iters,
                                       opt.min_time_ms));
#endif
#ifdef SCL_BENCH_HAVE_LZ4
                    } else if (name == "lz4") {
                        metrics.push_back(
                            bench_lz4(data, opt.warmup_iters, opt.min_time_ms));
#endif
                    } else if (name == "memcpy") {
                        metrics.push_back(
                            bench_memcpy(data, opt.warmup_iters, opt.min_time_ms));
                    } else {
                        std::cerr << "Unknown codec: " << name << "\n";
                    }
                } catch (const std::exception& e) {
                    std::cerr << "ERROR [" << name << "]: " << e.what() << "\n";
                }
            }

            if (!metrics.empty()) {
                print_metrics(entry.path(), metrics, opt.include_setup);
            }
        }

    } catch (const std::exception& e) {
        std::cerr << "Fatal: " << e.what() << "\n";
        return 1;
    }

    return 0;
}
