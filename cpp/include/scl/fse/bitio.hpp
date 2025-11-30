#pragma once

#include <cstdint>
#include <stdexcept>
#include <cstring>
#include <vector>

#include "fse.hpp"

namespace scl::fse {

// LSB-first bit writer, parameterized by flush width (8 or 64 bits).
template <size_t FlushBits>
class BitWriterLSBGeneric {
    static_assert(FlushBits == 8 || FlushBits == 64, "FlushBits must be 8 or 64");
    static constexpr size_t kFlushBytes = FlushBits / 8;
    static constexpr uint64_t kFlushMask =
        (FlushBits == 64) ? ~0ull : ((1ull << FlushBits) - 1ull);
public:
    BitWriterLSBGeneric() = default;
    explicit BitWriterLSBGeneric(std::vector<uint8_t>& external) : external_(&external) { reset(); }

    void reset() {
        buffer().clear();
        bit_buffer_ = 0;
        bit_count_ = 0;
    }

    void reserve(size_t nbytes) { buffer().reserve(nbytes); }

    void append_bits(uint32_t value, uint32_t nbits) {
        if (nbits == 0) return;
        uint64_t val = value;

        if constexpr (FlushBits == 64) {
            // At most one flush because nbits <= 32 and bit_count_ < 64.
            const uint32_t space = static_cast<uint32_t>(FlushBits - bit_count_);
            if (nbits >= space) {
                bit_buffer_ |= (val & ((space == 64) ? ~0ull : ((1ull << space) - 1ull)))
                               << bit_count_;
                // Emit full 64-bit word.
                auto& buf = buffer();
                const size_t base = buf.size();
                buf.resize(base + kFlushBytes);
                std::memcpy(buf.data() + base, &bit_buffer_, kFlushBytes);
                // Carry any remaining bits into a fresh buffer.
                const uint32_t consumed = space;
                val >>= consumed;
                nbits -= consumed;
                bit_buffer_ = 0;
                bit_count_ = 0;
            }
            if (nbits > 0) {
                bit_buffer_ |= val << bit_count_;
                bit_count_ += nbits;
            }
        } else { // FlushBits == 8
            bit_buffer_ |= val << bit_count_;
            bit_count_ += nbits;
            while (bit_count_ >= FlushBits) {
                const uint64_t chunk = bit_buffer_ & kFlushMask;
                auto& buf = buffer();
                buf.push_back(static_cast<uint8_t>(chunk & 0xFFu));
                bit_buffer_ >>= FlushBits;
                bit_count_ -= FlushBits;
            }
        }
    }

    size_t finish_into() {
        const size_t total_bits_val = buffer().size() * 8 + bit_count_;
        while (bit_count_ > 0) {
            buffer().push_back(static_cast<uint8_t>(bit_buffer_ & 0xFFu));
            bit_buffer_ >>= 8;
            bit_count_ = (bit_count_ >= 8) ? (bit_count_ - 8) : 0;
        }
        return total_bits_val;
    }

    EncodedBlock finish() {
        const size_t total_bits_val = finish_into();
        if (external_) {
            return EncodedBlock{buffer(), total_bits_val}; // copy when external storage
        }
        return EncodedBlock{std::move(buffer()), total_bits_val};
    }

    std::vector<uint8_t> move_buffer() {
        if (external_) {
            throw std::runtime_error("BitWriterLSBGeneric: cannot move external buffer");
        }
        return std::move(owned_);
    }

private:
    std::vector<uint8_t>& buffer() { return external_ ? *external_ : owned_; }

    std::vector<uint8_t>* external_ = nullptr;
    std::vector<uint8_t> owned_;
    uint64_t bit_buffer_ = 0;
    uint32_t bit_count_ = 0;
};

using BitWriterLSB8 = BitWriterLSBGeneric<8>;
using BitWriterLSB64 = BitWriterLSBGeneric<64>;

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
    BitWriterMSB() = default;
    explicit BitWriterMSB(std::vector<uint8_t>& external) : external_(&external) { reset(); }

    void reset() {
        buffer().clear();
        bit_len_ = 0;
    }

    void reserve(size_t nbytes) { buffer().reserve(nbytes); }

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

    size_t finish_into() { return bit_len_; }

    EncodedBlock finish() && {
        if (external_) {
            return EncodedBlock{buffer(), bit_len_}; // copy when using external storage
        }
        return EncodedBlock{std::move(buffer()), bit_len_};
    }

    std::vector<uint8_t> move_buffer() {
        if (external_) {
            throw std::runtime_error("BitWriterMSB: cannot move external buffer");
        }
        return std::move(owned_);
    }

private:
    void append_bit(uint32_t bit) {
        const size_t byte_idx = bit_len_ / 8;
        const size_t bit_in_byte = bit_len_ % 8;
        if (byte_idx >= buffer().size()) {
            buffer().push_back(0);
        }
        // Place the bit at position (7 - bit_in_byte) so we fill each byte from MSB -> LSB.
        const uint8_t mask = static_cast<uint8_t>(1u << (7u - bit_in_byte));
        if (bit) buffer()[byte_idx] |= mask;
        ++bit_len_;
    }

    std::vector<uint8_t>& buffer() { return external_ ? *external_ : owned_; }

    std::vector<uint8_t>* external_ = nullptr;
    std::vector<uint8_t> owned_;
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
