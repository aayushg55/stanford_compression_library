#include "scl/fse/frame.hpp"

#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <vector>

namespace scl::fse {

namespace {

class BitWriterLSB {
public:
    void append_bits(uint32_t value, uint32_t nbits) {
        if (nbits == 0) return;
        bit_buffer_ |= static_cast<uint64_t>(value) << bit_count_;
        bit_count_ += nbits;
        while (bit_count_ >= 8) {
            bytes_.push_back(static_cast<uint8_t>(bit_buffer_ & 0xFFu));
            bit_buffer_ >>= 8;
            bit_count_ -= 8;
        }
    }

    EncodedBlock finish() {
        size_t total_bits_val = bytes_.size() * 8 + bit_count_;
        if (bit_count_ > 0) {
            bytes_.push_back(static_cast<uint8_t>(bit_buffer_ & 0xFFu));
            bit_buffer_ = 0;
            bit_count_ = 0;
        }
        EncodedBlock out;
        out.bytes = std::move(bytes_);
        out.bit_count = total_bits_val;
        return out;
    }

    size_t total_bits() const { return bytes_.size() * 8 + bit_count_; }

private:
    std::vector<uint8_t> bytes_;
    uint64_t bit_buffer_ = 0;
    uint32_t bit_count_ = 0;
};

class BitReaderLSB {
public:
    BitReaderLSB(const uint8_t* data, size_t total_bits) : data_(data), total_bits_(total_bits) {}

    uint32_t read_bits(uint32_t nbits) {
        if (nbits == 0) return 0;
        size_t byte_idx = bit_pos_ / 8;
        uint32_t bit_off = static_cast<uint32_t>(bit_pos_ % 8);
        uint64_t chunk = 0;
        for (uint32_t i = 0; i < 8 && (byte_idx + i) < (total_bits_ + 7) / 8; ++i) {
            chunk |= static_cast<uint64_t>(data_[byte_idx + i]) << (8 * i);
        }
        chunk >>= bit_off;
        uint32_t mask = (nbits == 32) ? 0xFFFFFFFFu : ((1u << nbits) - 1u);
        uint32_t val = static_cast<uint32_t>(chunk) & mask;
        bit_pos_ += nbits;
        return val;
    }

    size_t position() const { return bit_pos_; }

private:
    const uint8_t* data_;
    size_t total_bits_;
    size_t bit_pos_ = 0;
};

EncodedBlock encode_block_lsb(const std::vector<uint8_t>& symbols, const FSETables& tables) {
    BitWriterLSB writer;
    const uint32_t block_size = static_cast<uint32_t>(symbols.size());
    writer.append_bits(block_size, tables.data_block_size_bits);
    if (symbols.empty()) return writer.finish();
    uint32_t state = tables.table_size;
    std::vector<uint32_t> chunks_value;
    std::vector<uint32_t> chunks_bits;
    chunks_value.reserve(symbols.size());
    chunks_bits.reserve(symbols.size());

    for (auto it = symbols.rbegin(); it != symbols.rend(); ++it) {
        const uint8_t s = *it;
        const SymTransform& tr = tables.symTT[s];
        const uint32_t nb_out = (state + tr.delta_nb_bits) >> 16;
        const uint32_t mask = (nb_out == 32) ? 0xFFFFFFFFu : ((1u << nb_out) - 1u);
        const uint32_t out_bits_value = state & mask;
        chunks_value.push_back(out_bits_value);
        chunks_bits.push_back(nb_out);
        const uint32_t subrange_id = state >> nb_out;
        const uint32_t idx = subrange_id + static_cast<uint32_t>(tr.delta_find_state);
        state = tables.tableU16[idx];
    }

    const uint32_t final_state_offset = state - tables.table_size;
    writer.append_bits(final_state_offset, tables.table_log);

    for (auto v_it = chunks_value.rbegin(), b_it = chunks_bits.rbegin();
         v_it != chunks_value.rend(); ++v_it, ++b_it) {
        if (*b_it) writer.append_bits(*v_it, *b_it);
    }
    return writer.finish();
}

DecodeResult decode_block_lsb(const uint8_t* bits, size_t bit_len, const FSETables& tables) {
    BitReaderLSB br(bits, bit_len);
    DecodeResult result;
    const uint32_t block_size = br.read_bits(tables.data_block_size_bits);
    result.bits_consumed = tables.data_block_size_bits;
    if (block_size == 0) return result;
    const uint32_t state_offset = br.read_bits(tables.table_log);
    uint32_t state = state_offset;
    result.bits_consumed += tables.table_log;
    result.symbols.resize(block_size);
    for (size_t i = 0; i < block_size; ++i) {
        const DecodeEntry& entry = tables.dtable[state];
        uint32_t bits_val = (entry.nb_bits > 0) ? br.read_bits(entry.nb_bits) : 0;
        state = entry.new_state_base + bits_val;
        result.symbols[i] = entry.symbol;
    }
    result.bits_consumed = br.position();
    return result;
}

} // namespace

EncodedFrame encode_stream(const std::vector<uint8_t>& input, const FrameOptions& opts) {
    EncodedFrame frame;
    frame.original_size = input.size();
    const size_t block_size = (opts.block_size == 0) ? input.size() : opts.block_size;
    size_t pos = 0;
    while (pos < input.size()) {
        const size_t chunk = std::min(block_size, input.size() - pos);
        std::vector<uint32_t> counts(256, 0);
        for (size_t i = 0; i < chunk; ++i) counts[input[pos + i]]++;

        FSEParams params(counts, opts.table_log);
        FSETables tables(params);
        auto encoder = make_encoder(opts.level, tables);
        std::vector<uint8_t> symbols(input.begin() + pos, input.begin() + pos + chunk);
        EncodedBlock encoded =
            opts.use_lsb ? encode_block_lsb(symbols, tables) : encoder->encode_block(symbols);

        uint32_t blk_sz_u32 = static_cast<uint32_t>(chunk);
        uint32_t bit_count_u32 = static_cast<uint32_t>(encoded.bit_count);
        uint32_t table_log_u32 = params.table_log;

        size_t header_size = sizeof(uint32_t) * (3 + counts.size());
        size_t old_size = frame.bytes.size();
        frame.bytes.resize(old_size + header_size + encoded.bytes.size());
        uint8_t* dst = frame.bytes.data() + old_size;

        std::memcpy(dst, &blk_sz_u32, sizeof(uint32_t));
        std::memcpy(dst + sizeof(uint32_t), &bit_count_u32, sizeof(uint32_t));
        std::memcpy(dst + sizeof(uint32_t) * 2, &table_log_u32, sizeof(uint32_t));
        std::memcpy(dst + sizeof(uint32_t) * 3, counts.data(), counts.size() * sizeof(uint32_t));
        std::memcpy(dst + header_size, encoded.bytes.data(), encoded.bytes.size());

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
        auto decoder = make_decoder(opts.level, tables);
        DecodeResult res = opts.use_lsb ? decode_block_lsb(payload, bit_count, tables)
                                        : decoder->decode_block(payload, bit_count);
        if (res.symbols.size() != blk_sz) return {};
        output.insert(output.end(), res.symbols.begin(), res.symbols.end());
        pos += payload_bytes;
    }
    return output;
}

} // namespace scl::fse
