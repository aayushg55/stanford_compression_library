#include "scl_fse_wrapper.h"

#include <vector>
#include <cstring>

#include "scl/fse/frame.hpp"
#include "scl/fse/levels.hpp"

using namespace scl::fse;

extern "C" size_t sclfse_compress_level(const void* src, size_t srcSize, void* dst, size_t dstCapacity, int level) {
    BenchConfig cfg = config_from_level(level);
    FrameOptions opts;
    opts.block_size = cfg.block_size;
    opts.table_log = cfg.table_log;
    opts.level = cfg.level;
    opts.use_lsb = cfg.use_lsb;
    opts.use_lsb_wide = cfg.use_lsb_wide;

    fprintf(stderr, "[sclfse] compress level=%d table_log=%u block=%zu lsb=%d wide=%d\n",
            level, opts.table_log, opts.block_size, (int)opts.use_lsb, (int)opts.use_lsb_wide);

    const auto* in = static_cast<const uint8_t*>(src);
    std::vector<uint8_t> input(in, in + srcSize);
    EncodedFrame frame = encode_stream(input, opts);
    if (frame.bytes.size() > dstCapacity) {
        return 0;
    }
    std::memcpy(dst, frame.bytes.data(), frame.bytes.size());
    return frame.bytes.size();
}

extern "C" size_t sclfse_decompress_level(void* dst, size_t dstCapacity, const void* src, size_t srcSize, int level) {
    BenchConfig cfg = config_from_level(level);
    FrameOptions opts;
    opts.block_size = cfg.block_size;
    opts.table_log = cfg.table_log;
    opts.level = cfg.level;
    opts.use_lsb = cfg.use_lsb;
    opts.use_lsb_wide = cfg.use_lsb_wide;

    std::vector<uint8_t> decoded = decode_stream(static_cast<const uint8_t*>(src), srcSize, opts);
    if (decoded.empty() || decoded.size() > dstCapacity) {
        return 0;
    }
    std::memcpy(dst, decoded.data(), decoded.size());
    return decoded.size();
}
