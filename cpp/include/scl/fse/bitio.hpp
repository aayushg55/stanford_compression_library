#pragma once

#include <cstdint>
#include <vector>

#include "fse.hpp"

namespace scl::fse {

// LSB-first bit writer: accumulates bits into a little-endian buffer and flushes bytes.
class BitWriterLSB {
public:
    void append_bits(uint32_t value, uint32_t nbits) {
        if (nbits == 0) return;
        // Pack bits into the buffer starting at the current bit offset.
        bit_buffer_ |= static_cast<uint64_t>(value) << bit_count_;
        bit_count_ += nbits;
        // Flush whole bytes as soon as they are complete; leave partial bits buffered.
        while (bit_count_ >= 8) {
            bytes_.push_back(static_cast<uint8_t>(bit_buffer_ & 0xFFu)); // low 8 bits
            bit_buffer_ >>= 8;
            bit_count_ -= 8;
        }
    }

    EncodedBlock finish() {
        size_t total_bits_val = bytes_.size() * 8 + bit_count_;
        if (bit_count_ > 0) {
            // Flush remaining partial byte (LSB-aligned).
            bytes_.push_back(static_cast<uint8_t>(bit_buffer_ & 0xFFu));
            bit_buffer_ = 0;
            bit_count_ = 0;
        }
        EncodedBlock out;
        out.bytes = std::move(bytes_);
        out.bit_count = total_bits_val;
        return out;
    }

private:
    std::vector<uint8_t> bytes_;
    uint64_t bit_buffer_ = 0;
    uint32_t bit_count_ = 0;
};

// LSB-first reader: consumes bits from a little-endian buffer starting at offset_bits.
class BitReaderLSB {
public:
    BitReaderLSB(const uint8_t* data, size_t total_bits, size_t offset_bits = 0)
        : data_(data), total_bits_(total_bits), bit_pos_(offset_bits) {}

    uint32_t read_bits(uint32_t nbits) {
        if (nbits == 0) return 0;
        size_t byte_idx = bit_pos_ / 8;
        uint32_t bit_off = static_cast<uint32_t>(bit_pos_ % 8);
        uint64_t chunk = 0;
        // Read up to 8 bytes into a 64-bit chunk.
        for (uint32_t i = 0; i < 8 && (byte_idx + i) < (total_bits_ + 7) / 8; ++i) {
            chunk |= static_cast<uint64_t>(data_[byte_idx + i]) << (8 * i);
        }
        // Drop bits already consumed in the current byte.
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

// MSB-first bit IO (matches spec). This path is inherently slower than the LSB buffer
// because it emits/consumes bits one at a time; kept for parity/debug. In principle
// it could be chunked too but use LSB to match the original FSE implementation.
class BitWriterMSB {
public:
    void append_bits(uint32_t value, uint32_t nbits) {
        if (nbits == 0) return;
        for (int i = static_cast<int>(nbits) - 1; i >= 0; --i) {
            append_bit((value >> i) & 1u);
        }
    }

    void append_bits(const std::vector<uint8_t>& bits) {
        for (uint8_t b : bits) {
            append_bit(b & 1u);
        }
    }

    EncodedBlock finish() && { return EncodedBlock{std::move(bytes_), bit_len_}; }

private:
    void append_bit(uint32_t bit) {
        const size_t byte_idx = bit_len_ / 8;
        const size_t bit_in_byte = bit_len_ % 8;
        if (byte_idx >= bytes_.size()) {
            bytes_.push_back(0);
        }
        // Place the bit at position (7 - bit_in_byte) so we fill each byte from MSB -> LSB.
        const uint8_t mask = static_cast<uint8_t>(1u << (7u - bit_in_byte));
        if (bit) bytes_[byte_idx] |= mask;
        ++bit_len_;
    }

    std::vector<uint8_t> bytes_;
    size_t bit_len_ = 0;
};

class BitReaderMSB {
public:
    BitReaderMSB(const uint8_t* data, size_t total_bits, size_t offset_bits = 0)
        : data_(data), total_bits_(total_bits), bit_pos_(offset_bits) {
        if (offset_bits > total_bits_) {
            throw std::runtime_error("BitReaderMSB: offset exceeds total bits");
        }
    }

    uint32_t read_bits(uint32_t nbits) {
        if (nbits == 0) return 0;
        if (bit_pos_ + nbits > total_bits_) {
            throw std::runtime_error("BitReaderMSB: out of bits");
        }
        uint32_t value = 0;
        for (uint32_t i = 0; i < nbits; ++i) {
            const size_t bit_index = bit_pos_ + i;
            const size_t byte_idx = bit_index / 8;
            const size_t bit_in_byte = bit_index % 8;
            const uint8_t byte = data_[byte_idx];
            // Extract bit at position (7 - bit_in_byte) to maintain MSB-first order.
            const uint8_t bit = static_cast<uint8_t>((byte >> (7u - bit_in_byte)) & 1u);
            value = static_cast<uint32_t>((value << 1) | bit);
        }
        bit_pos_ += nbits;
        return value;
    }

    size_t position() const { return bit_pos_; }

private:
    const uint8_t* data_;
    size_t total_bits_;
    size_t bit_pos_;
};

} // namespace scl::fse
