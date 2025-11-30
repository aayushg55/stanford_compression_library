// Thin wrapper to expose our C++ FSE codec to lzbench (hot-path variant).

#include "codecs.h"

#include <cstdint>
#include <cstdlib>
#include <memory>
#include <vector>
#include <cstring>

#include "scl/fse/fse.hpp"

using namespace scl::fse;

namespace {

struct FSEBenchCtx {
    FSELevel level;
    uint32_t table_log;
    std::vector<uint32_t> counts;
    std::unique_ptr<FSEParams> params;
    std::unique_ptr<FSETables> tables;
    std::unique_ptr<FSEEncoderSpec> encoder;
    std::unique_ptr<FSEDecoderSpec> decoder;
};

FSELevel level_from_bench(int lvl) {
    if (lvl <= 3) return FSELevel::L0_Spec;
    if (lvl <= 6) return FSELevel::L1_Clean;
    if (lvl <= 9) return FSELevel::L2_Tuned;
    return FSELevel::L3_Experimental;
}

uint32_t table_log_from_bench(int lvl) {
    if (lvl <= 3) return 10;
    if (lvl <= 6) return 11;
    if (lvl <= 9) return 12;
    return 12;
}

} // namespace

extern "C" {

char* lzbench_fse_init(size_t insize, size_t level_in, size_t) {
    // Histogram will be built in compress on first use; we just allocate ctx here.
    auto ctx = new (std::nothrow) FSEBenchCtx();
    if (!ctx) return nullptr;
    ctx->level = level_from_bench(static_cast<int>(level_in));
    ctx->table_log = table_log_from_bench(static_cast<int>(level_in));
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

    // Build histogram and tables once.
    if (!ctx->encoder || !ctx->decoder) {
        ctx->counts.assign(256, 0);
        const uint8_t* in = reinterpret_cast<uint8_t*>(inbuf);
        for (size_t i = 0; i < insize; ++i) {
            ctx->counts[in[i]] += 1;
        }
        ctx->params = std::make_unique<FSEParams>(ctx->counts, ctx->table_log);
        ctx->tables = std::make_unique<FSETables>(*ctx->params);
        ctx->encoder = std::make_unique<FSEEncoderSpec>(*ctx->tables);
        ctx->decoder = std::make_unique<FSEDecoderSpec>(*ctx->tables);
    }

    std::vector<uint8_t> symbols(reinterpret_cast<uint8_t*>(inbuf),
                                 reinterpret_cast<uint8_t*>(inbuf) + insize);
    EncodedBlock encoded = ctx->encoder->encode_block(symbols);

    // Prefix with bit_count (little-endian uint32) so decode knows exact bits.
    const size_t total_size = sizeof(uint32_t) + encoded.bytes.size();
    if (total_size > outsize) {
        return 0; // insufficient output buffer
    }
    uint32_t bit_count = static_cast<uint32_t>(encoded.bit_count);
    std::memcpy(outbuf, &bit_count, sizeof(uint32_t));
    std::memcpy(outbuf + sizeof(uint32_t), encoded.bytes.data(), encoded.bytes.size());
    return static_cast<int64_t>(total_size);
}

int64_t lzbench_fse_decompress(char* inbuf, size_t insize, char* outbuf, size_t outsize,
                               codec_options_t* codec_options) {
    auto ctx = reinterpret_cast<FSEBenchCtx*>(codec_options->work_mem);
    if (!ctx || !ctx->decoder) return 0;
    if (insize < sizeof(uint32_t)) return 0;
    uint32_t bit_count = 0;
    std::memcpy(&bit_count, inbuf, sizeof(uint32_t));
    const uint8_t* payload = reinterpret_cast<uint8_t*>(inbuf + sizeof(uint32_t));
    size_t payload_bytes = insize - sizeof(uint32_t);
    auto res = ctx->decoder->decode_block(payload, bit_count);
    if (res.symbols.size() > outsize) return 0;
    std::memcpy(outbuf, res.symbols.data(), res.symbols.size());
    return static_cast<int64_t>(res.symbols.size());
}

} // extern "C"

// Pull in the FSE implementation.
#include "../../cpp/src/fse.cpp"
