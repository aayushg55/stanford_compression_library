#pragma once

#include <cstdint>
#include <vector>

#include "fse.hpp"

namespace scl::fse {

struct FrameOptions {
    size_t block_size = 32 * 1024; // 0 => single block (whole input)
    uint32_t table_log = 12;       // hint/override; currently used as fixed
    FSELevel level = FSELevel::L0_Spec;
    bool use_lsb = false;
    bool use_lsb_wide = false;     // use 64-bit chunked LSB writer
};

struct EncodedFrame {
    std::vector<uint8_t> bytes;
    size_t original_size = 0;
};

// Encode a stream into framed blocks. Each block carries its counts, table_log,
// block_size, and payload bit_count.
EncodedFrame encode_stream(const std::vector<uint8_t>& input, const FrameOptions& opts);

// Decode a framed stream. Returns empty vector on error.
std::vector<uint8_t> decode_stream(const uint8_t* data, size_t size, const FrameOptions& opts);

} // namespace scl::fse
