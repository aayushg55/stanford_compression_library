#pragma once

#include <cassert>
#include <cstdint>
#include <stdexcept>
#include <cstring>
#include <vector>

#include "fse.hpp"

namespace scl::fse {

// Mask table for nb_bits in [0, 32]. Payload nb_bits <= table_log <= 15; headers use 32.
inline constexpr uint32_t kMaskTable[33] = {
    0x0u,        0x1u,        0x3u,        0x7u,
    0xFu,        0x1Fu,       0x3Fu,       0x7Fu,
    0xFFu,       0x1FFu,      0x3FFu,      0x7FFu,
    0xFFFu,      0x1FFFu,     0x3FFFu,     0x7FFFu,
    0xFFFFu,     0x1FFFFu,    0x3FFFFu,    0x7FFFFu,
    0xFFFFFu,    0x1FFFFFu,   0x3FFFFFu,   0x7FFFFFu,
    0xFFFFFFu,   0x1FFFFFFu,  0x3FFFFFFu,  0x7FFFFFFu,
    0xFFFFFFFu,  0x1FFFFFFFu, 0x3FFFFFFFu, 0x7FFFFFFFu,
    0xFFFFFFFFu
};

// inline constexpr uint32_t mask_for_nbits(uint32_t nbits) {
//     if (nbits < sizeof(kMaskTable) / sizeof(kMaskTable[0])) {
//         return kMaskTable[nbits];
//     }
//     // Fallback should never fire; keep safe for defensive builds.
//     return nbits >= 32 ? 0xFFFFFFFFu : ((uint32_t(1) << nbits) - 1u);
// }

// LSB-first bit writer, parameterized by flush width (8 bits).
template <size_t FlushBits>
class BitWriterLSBGeneric {
    static_assert(FlushBits == 8, "BitWriterLSBGeneric only supports 8-bit flush");
    static constexpr size_t kFlushBytes = FlushBits / 8;
    static constexpr uint64_t kFlushMask = (1ull << FlushBits) - 1ull;
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
        bit_buffer_ |= static_cast<uint64_t>(value) << bit_count_;
        bit_count_ += nbits;
        while (bit_count_ >= FlushBits) {
            const uint64_t chunk = bit_buffer_ & kFlushMask;
            auto& buf = buffer();
            buf.push_back(static_cast<uint8_t>(chunk & 0xFFu));
            bit_buffer_ >>= FlushBits;
            bit_count_ -= FlushBits;
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

#if false && defined(__SIZEOF_INT128__)
// 128-bit flush variant for platforms with __uint128_t support.
class BitWriterLSB128 {
public:
    BitWriterLSB128() = default;
    explicit BitWriterLSB128(std::vector<uint8_t>& external) : external_(&external) { reset(); }

    void reset() {
        buffer().clear();
        bit_buffer_ = 0;
        bit_count_ = 0;
    }

    void reserve(size_t nbytes) { buffer().reserve(nbytes); }

    void append_bits(uint32_t value, uint32_t nbits) {
        if (nbits == 0) return;
        UInt128 val = value;
        const uint32_t space = static_cast<uint32_t>(kFlushBits - bit_count_);
        if (nbits >= space) {
            const UInt128 mask = (space == 128) ? kAllOnes : ((UInt128(1) << space) - 1);
            bit_buffer_ |= (val & mask) << bit_count_;

            // Emit 128-bit word.
            auto& buf = buffer();
            const size_t base = buf.size();
            buf.resize(base + kFlushBytes);
            std::memcpy(buf.data() + base, &bit_buffer_, kFlushBytes);

            // Carry remainder.
            val >>= space;
            nbits -= space;
            bit_buffer_ = 0;
            bit_count_ = 0;
        }
        if (nbits > 0) {
            bit_buffer_ |= val << bit_count_;
            bit_count_ += nbits;
        }
    }

    size_t finish_into() {
        const size_t total_bits_val = buffer().size() * 8 + bit_count_;
        while (bit_count_ > 0) {
            auto& buf = buffer();
            buf.push_back(static_cast<uint8_t>(bit_buffer_ & 0xFFu));
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
            throw std::runtime_error("BitWriterLSB128: cannot move external buffer");
        }
        return std::move(owned_);
    }

private:
    using UInt128 = unsigned __int128;
    static constexpr uint32_t kFlushBits = 128;
    static constexpr size_t kFlushBytes = kFlushBits / 8;
    static constexpr UInt128 kAllOnes = ~UInt128(0);

    std::vector<uint8_t>& buffer() { return external_ ? *external_ : owned_; }

    std::vector<uint8_t>* external_ = nullptr;
    std::vector<uint8_t> owned_;
    UInt128 bit_buffer_ = 0;
    uint32_t bit_count_ = 0;
};

using BitWriterLSBWide = BitWriterLSB128;
#else
// Fallback "wide" writer using a 64-bit buffer when __uint128_t is unavailable.
class BitWriterLSBWide {
public:
    BitWriterLSBWide() = default;

    void reset() {
        buffer_.clear();
        bit_buffer_ = 0;
        bit_count_ = 0;
    }

    void reserve(size_t nbytes) { buffer_.reserve(nbytes); }

    void inline append_bits(uint32_t value, uint32_t nbits) {
        if (nbits == 0) return;
        // Fast path: everything fits without flush.
        if (bit_count_ + nbits < 64) {
            bit_buffer_ |= static_cast<uint64_t>(value) << bit_count_;
            bit_count_ += nbits;
            return;
        }
        // Flush current buffer plus some bits from value.
        const uint32_t space = 64 - bit_count_;
        const uint64_t mask = ~0ull >> (64 - space); // when space=64, shift by 0
        bit_buffer_ |= (static_cast<uint64_t>(value) & mask) << bit_count_;
        emit_word(bit_buffer_);
        bit_buffer_ = static_cast<uint64_t>(value) >> space;
        bit_count_ = nbits - space;
    }

    size_t finish_into() {
        const size_t total_bits_val = buffer_.size() * 8 + bit_count_;
        if (bit_count_ > 0) {
            const size_t tail_bytes = (bit_count_ + 7) / 8;
            const size_t base = buffer_.size();
            buffer_.resize(base + tail_bytes);
            std::memcpy(buffer_.data() + base, &bit_buffer_, tail_bytes);
            bit_buffer_ = 0;
            bit_count_ = 0;
        }
        return total_bits_val;
    }

    EncodedBlock finish() {
        const size_t total_bits_val = finish_into();
        EncodedBlock out;
        out.bytes = std::move(buffer_);
        out.bit_count = total_bits_val;
        return out;
    }

    std::vector<uint8_t> move_buffer() { return std::move(buffer_); }

private:
    void inline emit_word(uint64_t word) {
        const size_t base = buffer_.size();
        buffer_.resize(base + 8);
        std::memcpy(buffer_.data() + base, &word, 8);
    }

    std::vector<uint8_t> buffer_;
    uint64_t bit_buffer_ = 0;
    uint32_t bit_count_ = 0;
};
#endif

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
        const uint32_t mask = kMaskTable[nbits];

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

// Buffered LSB-first reader: loads up to 64 bits into a local buffer to reduce per-call overhead.
class BitReaderLSBBuffered {
public:
    BitReaderLSBBuffered(const uint8_t* data, size_t total_bits, size_t offset_bits = 0)
        : data_(data), total_bits_(total_bits), bit_pos_(offset_bits) {}

    uint32_t read_bits(uint32_t nbits) {
        if (nbits == 0) return 0;
        // assert(nbits < 16);
        uint32_t out = 0;
        uint32_t out_shift = 0;
        uint32_t remaining = nbits;
        while (remaining > 0) {
            if (bit_count_ == 0) refill();
            if (bit_count_ == 0) break; // no more bits available
            const uint32_t take = (remaining < bit_count_) ? remaining : bit_count_;
            const uint64_t mask = (take == 64) ? ~0ull : ((1ull << take) - 1ull);
            out |= static_cast<uint32_t>(bit_buffer_ & mask) << out_shift;
            bit_buffer_ >>= take;
            bit_count_ -= take;
            bit_pos_ += take;
            out_shift += take;
            remaining -= take;
        }
        const uint32_t mask = mask_for_nbits(nbits);
        return out & mask;
    }

    size_t position() const { return bit_pos_; }

private:
    void refill() {
        if (bit_pos_ >= total_bits_) {
            bit_count_ = 0;
            return;
        }
        const size_t byte_idx = bit_pos_ / 8;
        const size_t bit_off = bit_pos_ % 8;
        const size_t remaining_bits = total_bits_ - bit_pos_;
        const size_t load_bytes = std::min<size_t>(8, (remaining_bits + 7) / 8);

        uint64_t chunk = 0;
        std::memcpy(&chunk, data_ + byte_idx, load_bytes);
        chunk >>= bit_off;

        bit_buffer_ = chunk;
        const size_t avail_bits = std::min<size_t>(64 - bit_off, remaining_bits);
        bit_count_ = static_cast<uint32_t>(avail_bits);
    }

    const uint8_t* data_;
    size_t total_bits_;
    size_t bit_pos_;
    uint64_t bit_buffer_ = 0;
    uint32_t bit_count_ = 0;
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
