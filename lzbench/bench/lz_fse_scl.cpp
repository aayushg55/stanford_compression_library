// Thin wrapper to expose our C++ FSE codec to lzbench using the framed API.

#include "codecs.h"

#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <memory>
#include <vector>
#include <cstdio>

#include "scl/fse/frame.hpp"
#include "scl/fse/levels.hpp"

using namespace scl::fse;

namespace {

struct FSEBenchCtx {
    BenchConfig config;
};

// Lightweight header dump to help debug mismatches in the lzbench harness.
void log_frame_header(const char* tag, const uint8_t* data, size_t size, const BenchConfig& cfg) {
    if (!data) {
        std::fprintf(stderr, "[fse-debug] %s: null data\n", tag);
        return;
    }
    if (size < sizeof(uint32_t) * 3) {
        std::fprintf(stderr, "[fse-debug] %s: size=%zu too small for header (lvl=%d lsb=%d wide=%d)\n",
                     tag, size, static_cast<int>(cfg.level), cfg.use_lsb, cfg.use_lsb_wide);
        return;
    }
    uint32_t blk_sz = 0, bit_count = 0, table_log = 0;
    std::memcpy(&blk_sz, data, sizeof(uint32_t));
    std::memcpy(&bit_count, data + sizeof(uint32_t), sizeof(uint32_t));
    std::memcpy(&table_log, data + sizeof(uint32_t) * 2, sizeof(uint32_t));
    const size_t payload_bytes = (bit_count + 7u) / 8u;
    const bool has_counts = size >= sizeof(uint32_t) * (3 + 256);
    std::fprintf(stderr,
                 "[fse-debug] %s: size=%zu blk_sz=%u bit_count=%u payload_bytes=%zu "
                 "table_log=%u header_counts=%d cfg(level=%d tl=%u bs=%zu lsb=%d wide=%d)\n",
                 tag,
                 size,
                 blk_sz,
                 bit_count,
                 payload_bytes,
                 table_log,
                 has_counts ? 1 : 0,
                 static_cast<int>(cfg.level),
                 cfg.table_log,
                 cfg.block_size,
                 cfg.use_lsb,
                 cfg.use_lsb_wide);
}

} // namespace

extern "C" {

char* lzbench_fse_init(size_t, size_t level_in, size_t) {
    BenchConfig cfg = config_from_level(static_cast<int>(level_in));
    auto ctx = new (std::nothrow) FSEBenchCtx();
    if (!ctx) return nullptr;
    ctx->config = cfg;
    // std::fprintf(stderr,
    //              "[fse-debug] init level_in=%zu -> level=%d table_log=%u block_size=%zu lsb=%d wide=%d\n",
    //              level_in,
    //              static_cast<int>(cfg.level),
    //              cfg.table_log,
    //              cfg.block_size,
    //              cfg.use_lsb,
    //              cfg.use_lsb_wide);
    return reinterpret_cast<char*>(ctx);
}

void lzbench_fse_deinit(char* workmem) {
    auto ctx = reinterpret_cast<FSEBenchCtx*>(workmem);
    delete ctx;
}

int64_t lzbench_fse_compress(char* inbuf, size_t insize, char* outbuf, size_t outsize,
                             codec_options_t* codec_options) {
    auto ctx = reinterpret_cast<FSEBenchCtx*>(codec_options->work_mem);
    if (!ctx) return 0;
    std::vector<uint8_t> input(reinterpret_cast<uint8_t*>(inbuf),
                               reinterpret_cast<uint8_t*>(inbuf) + insize);
    FrameOptions fo;
    fo.block_size = ctx->config.block_size;
    fo.table_log = ctx->config.table_log;
    fo.level = ctx->config.level;
    fo.use_lsb = ctx->config.use_lsb;
    fo.use_lsb_wide = ctx->config.use_lsb_wide;
    EncodedFrame frame = encode_stream(input, fo);
    // log_frame_header("compress", frame.bytes.data(), frame.bytes.size(), ctx->config);
    if (frame.bytes.size() > outsize) return 0;
    std::memcpy(outbuf, frame.bytes.data(), frame.bytes.size());
    return static_cast<int64_t>(frame.bytes.size());
}

int64_t lzbench_fse_decompress(char* inbuf, size_t insize, char* outbuf, size_t outsize,
                               codec_options_t* codec_options) {
    auto ctx = reinterpret_cast<FSEBenchCtx*>(codec_options->work_mem);
    if (!ctx) return 0;
    FrameOptions fo;
    fo.block_size = ctx->config.block_size;
    fo.table_log = ctx->config.table_log;
    fo.level = ctx->config.level;
    fo.use_lsb = ctx->config.use_lsb;
    fo.use_lsb_wide = ctx->config.use_lsb_wide;
    // log_frame_header("decompress-in", reinterpret_cast<uint8_t*>(inbuf), insize, ctx->config);
    std::vector<uint8_t> decoded = decode_stream(reinterpret_cast<uint8_t*>(inbuf), insize, fo);
    if (decoded.empty() || decoded.size() > outsize) {
        std::fprintf(stderr,
                     "[fse-debug] decompress failed: decoded_size=%zu outsize=%zu insize=%zu\n",
                     decoded.size(), outsize, insize);
        return 0;
    }
    std::memcpy(outbuf, decoded.data(), decoded.size());
    return static_cast<int64_t>(decoded.size());
}

} // extern "C"
