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

inline constexpr uint32_t mask_for_nbits(uint32_t nbits) {
    if (nbits < sizeof(kMaskTable) / sizeof(kMaskTable[0])) {
        return kMaskTable[nbits];
    }
    // Fallback should never fire; keep safe for defensive builds.
    return nbits >= 32 ? 0xFFFFFFFFu : ((uint32_t(1) << nbits) - 1u);
}

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



// class BitReaderLSB {
//     public:
//         BitReaderLSB(const uint8_t* data,
//                      size_t /*total_bits*/,
//                      size_t offset_bits = 0)
//             : data_(data),
//               bit_pos_(offset_bits) {}
    
//         // Precondition: 1 <= nbits <= 15, buffer padded with >=7 trailing zero bytes.
//         inline uint32_t read_bits(uint32_t nbits) {
//             // Optional in non-hot builds:
//             // assert(nbits > 0 && nbits <= 15);
    
//             const size_t   byte_idx = bit_pos_ >> 3;   // / 8
//             const uint32_t bit_off  = bit_pos_ & 7u;   // % 8
    
//             uint32_t w;
//             std::memcpy(&w, data_ + byte_idx, 4);

//             uint32_t val = static_cast<uint32_t>(w >> bit_off) & kMaskTable[nbits];
//             bit_pos_ += nbits;
//             return val;
//         }
    
//         size_t position() const { return bit_pos_; }
    
//     private:
//         const uint8_t* data_;
//         size_t bit_pos_;
//     };

// class BitReaderLSB {
//     public:
//         BitReaderLSB(const uint8_t* data, size_t total_bits, size_t offset_bits = 0)
//             : data_(data),
//               total_bits_(total_bits),
//               total_bytes_((total_bits + 7) / 8),
//               bit_pos_(offset_bits) {}
    
//         uint32_t read_bits(uint32_t nbits) {
//             // nbits in [0, 15]
//             if (nbits == 0) return 0;
    
//             // Optional safety check:
//             // if (bit_pos_ + nbits > total_bits_) { /* handle error */ }
    
//             const size_t  byte_idx = bit_pos_ >> 3;     // bit_pos / 8
//             const uint32_t bit_off = bit_pos_ & 7u;    // bit_pos % 8
    
//             // Build a 24-bit little-endian window safely near the end.
//             uint32_t w = load24_tail_safe(data_, total_bytes_, byte_idx);
    
//             // Shift down to our bit position and mask.
//             uint32_t val = (w >> bit_off) & kMaskTable[nbits];
    
//             bit_pos_ += nbits;
//             return val;
//         }
    
//         size_t position() const { return bit_pos_; }
    
//     private:
//         static inline uint32_t load24_tail_safe(const uint8_t* data,
//                                                 size_t total_bytes,
//                                                 size_t byte_idx)
//         {
//             // Fast path: we have at least 3 bytes left.
//             // if (byte_idx + 3 <= total_bytes) {
//             // This compiles down to 3 loads and a couple shifts.
//             uint32_t w = 0;
//             std::memcpy(&w, data + byte_idx, 4);
//             return w;
//             // return  (uint32_t)data[byte_idx]
//             //         | (uint32_t)data[byte_idx + 1] << 8
//             //         | (uint32_t)data[byte_idx + 2] << 16;
//             // }
    
//             // // Tail: fewer than 3 bytes remain; zero-pad.
//             // uint32_t v = 0;
//             // if (byte_idx < total_bytes) {
//             //     v |= (uint32_t)data[byte_idx];
//             //     if (byte_idx + 1 < total_bytes)
//             //         v |= (uint32_t)data[byte_idx + 1] << 8;
//             //     // If there were 3 bytes, we'd have hit the fast path.
//             // }
//             // return v;
//         }
    
//         const uint8_t* data_;
//         size_t total_bits_;
//         size_t total_bytes_;
//         size_t bit_pos_;
//     };

// class BitReaderLSB {
//     public:
//         BitReaderLSB(const uint8_t* data, size_t total_bits, size_t offset_bits = 0)
//             : data_(data),
//               total_bits_(total_bits),
//               bit_pos_(offset_bits),
//               cached_base_byte_(SIZE_MAX),   // “invalid”
//               cached_word_(0) {}
    
//         uint32_t read_bits(uint32_t nbits) {
//             if (nbits == 0) return 0;
    
//             // Optional bounds check here.
    
//             const size_t byte_idx = bit_pos_ >> 3; // /8
//             const uint32_t bit_off = static_cast<uint32_t>(bit_pos_ & 7u); // %8
    
//             // Reload cached window if we've moved out of it
//             if (byte_idx < cached_base_byte_ ||
//                 byte_idx >= cached_base_byte_ + 8) {
//                 // align start to 8-byte boundary for nicer loads
//                 cached_base_byte_ = byte_idx & ~size_t(7);
//                 cached_word_ = load64_le(data_ + cached_base_byte_);
//             }
    
//             const size_t bit_base = cached_base_byte_ << 3;
//             uint64_t val = cached_word_ >> (bit_pos_ - bit_base);
    
//             if ((bit_pos_ - bit_base) + nbits > 64) {
//                 // Crosses into the next 64-bit word, need one extra load
//                 uint64_t w1 = load64_le(data_ + cached_base_byte_ + 8);
//                 val |= w1 << (64 - (bit_pos_ - bit_base));
//             }
    
//             bit_pos_ += nbits;
    
//             const uint32_t mask = kMaskTable[nbits];
//             return static_cast<uint32_t>(val) & mask;
//         }
    
//         size_t position() const { return bit_pos_; }
    
//     private:
//         static inline uint64_t load64_le(const uint8_t* p) {
//             uint64_t v;
//             std::memcpy(&v, p, sizeof(v));  // safe unaligned
//         #if __BYTE_ORDER__ == __ORDER_BIG_ENDIAN__
//             v = __builtin_bswap64(v);
//         #endif
//             return v;
//         }
    
//         const uint8_t* data_;
//         size_t total_bits_;
//         size_t bit_pos_;
    
//         size_t   cached_base_byte_;
//         uint64_t cached_word_;
//     };

class BitReaderLSB {
    public:
        BitReaderLSB(const uint8_t* data, size_t total_bits, size_t offset_bits = 0)
            : data_(data),
              total_bits_(total_bits),
              bit_pos_(offset_bits) {}
    
        // assume nbits <= 32 here; if you need more we can extend
        uint32_t read_bits(uint32_t nbits) {
            if (nbits == 0) return 0;
    
            // Optional: bounds check
            // if (bit_pos_ + nbits > total_bits_) { /* handle error */ }
    
            const size_t byte_idx = bit_pos_ >> 3;         // bit_pos_ / 8
            const uint32_t bit_off = bit_pos_ & 7u;        // bit_pos_ % 8
    
            // Load first 64 bits from the stream, little-endian, possibly unaligned
            uint64_t word0 = load64_le(data_ + byte_idx);
    
            // Shift down by the bit offset
            uint64_t val = word0 >> bit_off;
    
            // // If the request straddles the 64-bit boundary, grab the next word
            // if (bit_off + nbits > 64) {
            //     uint64_t word1 = load64_le(data_ + byte_idx + 8);
            //     val |= (word1 << (64 - bit_off));
            // }
    
            bit_pos_ += nbits;
            const uint32_t mask = kMaskTable[nbits];
            return static_cast<uint32_t>(val) & mask;
        }
    
        size_t position() const { return bit_pos_; }
    
    private:
        static inline uint64_t load64_le(const uint8_t* p) {
            uint64_t v;
            std::memcpy(&v, p, sizeof(v));
    #if __BYTE_ORDER__ == __ORDER_BIG_ENDIAN__
            v = __builtin_bswap64(v);
    #endif
            return v;
        }
    
        const uint8_t* data_;
        size_t total_bits_;
        size_t bit_pos_;  // current absolute bit position
    };

// LSB-first reader: consumes bits from a little-endian buffer starting at offset_bits.
// class BitReaderLSB {
// public:
//     BitReaderLSB(const uint8_t* data, size_t total_bits, size_t offset_bits = 0)
//         : data_(data),
//           end_(data + ((total_bits + 7) / 8)),
//           total_bits_(total_bits),
//           bit_pos_(offset_bits),
//           ptr_(data + (offset_bits / 8)) {
//         const uint32_t bit_off = static_cast<uint32_t>(offset_bits % 8);
//         if (bit_off != 0 && ptr_ < end_) {
//             // Prime the container with the tail of the first byte.
//             lo_ = static_cast<uint64_t>(*ptr_ >> bit_off);
//             bits_in_lo_ = 8u - bit_off;
//             ++ptr_;
//         }
//     }

//     uint32_t read_bits(uint32_t nbits) {
//         if (nbits == 0) return 0;
//         ensure(nbits);
//         const uint32_t mask = kMaskTable[nbits];
//         const uint32_t val = static_cast<uint32_t>(lo_) & mask;
//         consume(nbits);
//         bit_pos_ += nbits;
//         return val;
//     }

//     size_t position() const { return bit_pos_; }

// private:
//     void ensure(uint32_t nbits) {
//         if ((bits_in_lo_ + bits_in_hi_) >= nbits) return;
//         if (ptr_ >= end_) return;

//         // First chunk.
//         uint64_t chunk = 0;
//         size_t avail = static_cast<size_t>(end_ - ptr_);
//         size_t load = std::min<size_t>(8, avail);
//         std::memcpy(&chunk, ptr_, load);
//         append_chunk(chunk, static_cast<uint32_t>(load * 8));
//         ptr_ += load;

//         // // Optional second chunk if still short and bytes remain.
//         // if ((bits_in_lo_ + bits_in_hi_) < nbits && ptr_ < end_) {
//         //     chunk = 0;
//         //     avail = static_cast<size_t>(end_ - ptr_);
//         //     load = std::min<size_t>(8, avail);
//         //     std::memcpy(&chunk, ptr_, load);
//         //     append_chunk(chunk, static_cast<uint32_t>(load * 8));
//         //     ptr_ += load;
//         // }
//     }

//     inline void append_chunk(uint64_t chunk, uint32_t chunk_bits) {
//         // Place chunk after existing bits in the 128-bit window (hi_:lo_).
//         const uint32_t total_bits = bits_in_lo_ + bits_in_hi_;
//         if (total_bits == 0) {
//             lo_ = chunk;
//             bits_in_lo_ = chunk_bits;
//             return;
//         }
//         if (bits_in_lo_ < 64) {
//             const uint32_t space_lo = 64u - bits_in_lo_;
//             if (chunk_bits <= space_lo) {
//                 lo_ |= chunk << bits_in_lo_;
//                 bits_in_lo_ += chunk_bits;
//                 return;
//             }
//             // Fill lo_ and spill remainder into hi_.
//             lo_ |= chunk << bits_in_lo_;
//             const uint32_t spill = chunk_bits - space_lo;
//             if (spill < 64) {
//                 hi_ |= chunk >> space_lo;
//             } else {
//                 hi_ = chunk >> space_lo; // spill can only be up to 64 here
//             }
//             bits_in_lo_ = 64;
//             bits_in_hi_ += spill;
//             return;
//         }
//         // lo_ full: append into hi_.
//         const uint32_t space_hi = 64u - bits_in_hi_;
//         const uint32_t take = (chunk_bits < space_hi) ? chunk_bits : space_hi;
//         hi_ |= chunk << bits_in_hi_;
//         bits_in_hi_ += take;
//     }

//     inline void consume(uint32_t nbits) {
//         if (nbits == 0) return;
//         if (nbits < bits_in_lo_) {
//             lo_ >>= nbits;
//             bits_in_lo_ -= nbits;
//             return;
//         }
//         // Drop lo_ entirely and pull from hi_ if needed.
//         const uint32_t remaining = nbits - bits_in_lo_;
//         lo_ = hi_;
//         hi_ = 0;
//         bits_in_lo_ = bits_in_hi_;
//         bits_in_hi_ = 0;
//         if (remaining) {
//             lo_ >>= remaining;
//             bits_in_lo_ = (bits_in_lo_ > remaining) ? (bits_in_lo_ - remaining) : 0;
//         }
//     }

//     const uint8_t* data_;
//     const uint8_t* end_;
//     const uint8_t* ptr_;
//     size_t total_bits_;
//     size_t bit_pos_ = 0;
//     uint64_t lo_ = 0;
//     uint64_t hi_ = 0;
//     uint32_t bits_in_lo_ = 0;
//     uint32_t bits_in_hi_ = 0;
// };

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
