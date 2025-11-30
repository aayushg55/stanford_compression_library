// Thin wrapper to expose our C++ FSE codec to lzbench using the framed API.

#include "codecs.h"

#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <memory>
#include <vector>

#include "scl/fse/frame.hpp"

using namespace scl::fse;

namespace {

struct BenchConfig {
    FSELevel level;
    uint32_t table_log;
    size_t block_size; // 0 => single block
    bool use_lsb;
    bool use_lsb_wide;
};

BenchConfig config_from_level(int lvl) {
    if (lvl <= 1) {
        // Single-block, MSB baseline
        return BenchConfig{FSELevel::L0_Spec, 12, 0, /*use_lsb=*/false, /*use_lsb_wide=*/false};
    }
    if (lvl == 2) {
        // Single-block, LSB baseline (faster)
        return BenchConfig{FSELevel::L0_Spec, 12, 0, /*use_lsb=*/true, /*use_lsb_wide=*/false};
    }
    if (lvl == 3) {
        // Single-block, LSB with 64-bit chunked writer
        return BenchConfig{FSELevel::L0_Spec, 12, 0, /*use_lsb=*/true, /*use_lsb_wide=*/true};
    }
    if (lvl <= 4) {
        // Framed, clean path
        uint32_t tl = (lvl == 4) ? 12 : 11;
        return BenchConfig{FSELevel::L1_Clean, tl, 32 * 1024, true, /*use_lsb_wide=*/false};
    }
    if (lvl <= 8) {
        // Tuned path, larger table/block as level increases
        uint32_t tl = (lvl <= 6) ? 11 : 12;
        size_t bs = (lvl <= 6) ? 32 * 1024 : 64 * 1024;
        return BenchConfig{FSELevel::L2_Tuned, tl, bs, true, /*use_lsb_wide=*/false};
    }
    // Experimental path
    return BenchConfig{FSELevel::L3_Experimental, 12, 64 * 1024, true, /*use_lsb_wide=*/false};
}

struct FSEBenchCtx {
    BenchConfig config;
};

} // namespace

extern "C" {

char* lzbench_fse_init(size_t, size_t level_in, size_t) {
    BenchConfig cfg = config_from_level(static_cast<int>(level_in));
    auto ctx = new (std::nothrow) FSEBenchCtx();
    if (!ctx) return nullptr;
    ctx->config = cfg;
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
    std::vector<uint8_t> decoded = decode_stream(reinterpret_cast<uint8_t*>(inbuf), insize, fo);
    if (decoded.empty() || decoded.size() > outsize) return 0;
    std::memcpy(outbuf, decoded.data(), decoded.size());
    return static_cast<int64_t>(decoded.size());
}

} // extern "C"

// Pull in the FSE implementation and framing layer.
#include "../../cpp/src/fse.cpp"
#include "../../cpp/src/frame.cpp"
