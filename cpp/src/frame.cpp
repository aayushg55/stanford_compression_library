#include "scl/fse/frame.hpp"

#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <vector>

#include "scl/fse/bitio.hpp"

namespace scl::fse {

EncodedFrame encode_stream(const std::vector<uint8_t>& input, const FrameOptions& opts) {
    fprintf(stderr, "[encode_stream] table_log=%u block_size=%zu lsb=%d wide=%d\n",
            opts.table_log, opts.block_size, (int)opts.use_lsb, (int)opts.use_lsb_wide);
    EncodedFrame frame;
    frame.original_size = input.size();
    const size_t block_size = (opts.block_size == 0) ? input.size() : opts.block_size;
    std::vector<uint32_t> counts(256, 0);
    std::vector<uint8_t> symbols;
    std::vector<uint8_t> payload;
    size_t pos = 0;
    while (pos < input.size()) {
        const size_t chunk = std::min(block_size, input.size() - pos);
        std::fill(counts.begin(), counts.end(), 0);
        for (size_t i = 0; i < chunk; ++i) {
            counts[input[pos + i]]++;
        }

        fprintf(stderr, "[encode_stream] building params table_log=%u\n", opts.table_log);
        FSEParams params(counts, opts.table_log);
        FSETables tables(params);
        symbols.assign(input.begin() + pos, input.begin() + pos + chunk);
        auto encoder = make_encoder(opts.level, tables, opts.use_lsb, opts.use_lsb_wide);
        const size_t bit_count = encoder->encode_block_into(symbols, payload);

        uint32_t blk_sz_u32 = static_cast<uint32_t>(chunk);
        uint32_t bit_count_u32 = static_cast<uint32_t>(bit_count);
        uint32_t table_log_u32 = params.table_log;

        size_t header_size = sizeof(uint32_t) * (3 + counts.size());
        size_t old_size = frame.bytes.size();
        frame.bytes.resize(old_size + header_size + payload.size());
        uint8_t* dst = frame.bytes.data() + old_size;

        std::memcpy(dst, &blk_sz_u32, sizeof(uint32_t));
        std::memcpy(dst + sizeof(uint32_t), &bit_count_u32, sizeof(uint32_t));
        std::memcpy(dst + sizeof(uint32_t) * 2, &table_log_u32, sizeof(uint32_t));
        std::memcpy(dst + sizeof(uint32_t) * 3, counts.data(), counts.size() * sizeof(uint32_t));
        std::memcpy(dst + header_size, payload.data(), payload.size());

        pos += chunk;
    }
    return frame;
}

std::vector<uint8_t> decode_stream(const uint8_t* data, size_t size, const FrameOptions& opts) {
    std::vector<uint8_t> output;
    size_t pos = 0;
    while (pos + sizeof(uint32_t) * 3 <= size) {
        uint32_t blk_sz = 0, bit_count = 0, table_log = 0;
        std::memcpy(&blk_sz, data + pos, sizeof(uint32_t));
        std::memcpy(&bit_count, data + pos + sizeof(uint32_t), sizeof(uint32_t));
        std::memcpy(&table_log, data + pos + sizeof(uint32_t) * 2, sizeof(uint32_t));
        pos += sizeof(uint32_t) * 3;
        const size_t counts_bytes = 256 * sizeof(uint32_t);
        if (pos + counts_bytes > size) return {};
        std::vector<uint32_t> counts(256);
        std::memcpy(counts.data(), data + pos, counts_bytes);
        pos += counts_bytes;

        const size_t payload_bytes = (bit_count + 7) / 8;
        if (pos + payload_bytes > size) return {};
        const uint8_t* payload = data + pos;

        FSEParams params(counts, table_log);
        FSETables tables(params);
        auto decoder = make_decoder(opts.level, tables, opts.use_lsb);
        DecodeResult res = decoder->decode_block(payload, bit_count);
        if (res.symbols.size() != blk_sz) return {};
        output.insert(output.end(), res.symbols.begin(), res.symbols.end());
        pos += payload_bytes;
    }
    return output;
}

} // namespace scl::fse
