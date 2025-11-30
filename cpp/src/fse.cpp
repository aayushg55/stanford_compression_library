#include "scl/fse/fse.hpp"

#include <algorithm>
#include <cassert>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <bit>
#include <memory>
#include <limits>
#include <numeric>
#include <stdexcept>
#include <utility>
#include <vector>

namespace scl::fse {

namespace {

uint32_t floor_log2(uint32_t x) {
    assert(x > 0);
    return std::bit_width(x) - 1u;
}

uint32_t round_ties_to_even(double x) {
    const double floor_x = std::floor(x);
    const double frac = x - floor_x;

    if (frac > 0.5) {
        return static_cast<uint32_t>(floor_x + 1.0);
    }
    if (frac < 0.5) {
        return static_cast<uint32_t>(floor_x);
    }

    // Exactly .5 => round to even integer.
    const uint64_t base = static_cast<uint64_t>(floor_x);
    if (base & 1ull) {
        return static_cast<uint32_t>(floor_x + 1.0);
    }
    return static_cast<uint32_t>(floor_x);
}

// Bit writer/reader: big-endian per bit (bit 0 of stream is MSB of byte 0).
class BitWriter {
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

    EncodedBlock finish() && {
        return EncodedBlock{std::move(bytes_), bit_len_};
    }

private:
    void append_bit(uint32_t bit) {
        const size_t byte_idx = bit_len_ / 8;
        const size_t bit_in_byte = bit_len_ % 8;
        if (byte_idx >= bytes_.size()) {
            bytes_.push_back(0);
        }
        // Big-endian bit numbering inside a byte: first bit is MSB.
        const uint8_t mask = static_cast<uint8_t>(1u << (7u - bit_in_byte));
        if (bit) {
            bytes_[byte_idx] |= mask;
        }
        ++bit_len_;
    }

    std::vector<uint8_t> bytes_;
    size_t bit_len_ = 0;
};

class BitReader {
public:
    BitReader(const uint8_t* data, size_t total_bits, size_t offset_bits = 0)
        : data_(data), total_bits_(total_bits), bit_pos_(offset_bits) {
        if (offset_bits > total_bits_) {
            throw std::runtime_error("BitReader: offset exceeds total bits");
        }
    }

    uint32_t read_bits(uint32_t nbits) {
        if (nbits == 0) return 0;
        if (bit_pos_ + nbits > total_bits_) {
            throw std::runtime_error("BitReader: out of bits");
        }

        uint32_t value = 0;
        for (uint32_t i = 0; i < nbits; ++i) {
            const size_t bit_index = bit_pos_ + i;
            const size_t byte_idx = bit_index / 8;
            const size_t bit_in_byte = bit_index % 8;
            const uint8_t byte = data_[byte_idx];
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

std::vector<uint8_t> bits_from_value(uint32_t value, uint32_t width) {
    std::vector<uint8_t> bits;
    bits.reserve(width);
    for (int i = static_cast<int>(width) - 1; i >= 0; --i) {
        bits.push_back(static_cast<uint8_t>((value >> i) & 1u));
    }
    return bits;
}

} // namespace

FSEParams::FSEParams(const std::vector<uint32_t>& counts_in,
                     uint32_t table_log_in,
                     uint32_t data_block_size_bits_in)
    : counts(counts_in),
      table_log(table_log_in),
      table_size(1u << table_log_in),
      normalized(counts_in.size(), 0),
      data_block_size_bits(data_block_size_bits_in),
      initial_state(1u << table_log_in) {
    if (counts.empty()) {
        throw std::invalid_argument("FSEParams: counts must not be empty");
    }

    const uint64_t total = std::accumulate(counts.begin(), counts.end(), uint64_t{0});
    if (total == 0) {
        throw std::invalid_argument("FSEParams: total frequency is zero");
    }

    uint64_t allocated = 0;

    // Initial proportional allocation with Python-style rounding.
    for (size_t i = 0; i < counts.size(); ++i) {
        const uint32_t c = counts[i];
        if (c == 0) {
            normalized[i] = 0;
            continue;
        }
        const double x = static_cast<double>(c) * static_cast<double>(table_size) /
                         static_cast<double>(total);
        uint32_t n = round_ties_to_even(x);
        if (n == 0) n = 1;
        normalized[i] = n;
        allocated += n;
    }

    int64_t diff = static_cast<int64_t>(table_size) - static_cast<int64_t>(allocated);
    if (diff != 0) {
        std::vector<size_t> symbols(counts.size());
        std::iota(symbols.begin(), symbols.end(), 0);

        std::stable_sort(symbols.begin(), symbols.end(),
                         [&](size_t a, size_t b) { return counts[a] > counts[b]; });

        size_t idx = 0;
        const int step = (diff > 0) ? 1 : -1;
        while (diff != 0 && idx < symbols.size()) {
            const size_t s = symbols[idx];
            const int64_t candidate = static_cast<int64_t>(normalized[s]) + step;
            if (candidate > 0) {
                normalized[s] = static_cast<uint32_t>(candidate);
                diff -= step;
            } else {
                ++idx;
            }
        }
    }

    const uint64_t check_sum =
        std::accumulate(normalized.begin(), normalized.end(), uint64_t{0});
    if (check_sum != table_size) {
        throw std::runtime_error("FSEParams: normalization did not reach table size");
    }
}

FSETables::FSETables(const FSEParams& params)
    : table_log(params.table_log),
      table_size(params.table_size),
      data_block_size_bits(params.data_block_size_bits),
      dtable(table_size),
      tableU16(table_size, 0),
      symTT(params.counts.size()) {
    const auto& norm = params.normalized;
    const size_t alphabet_size = norm.size();

    // Build spread table with co-prime step algorithm.
    const uint32_t table_mask = table_size - 1;
    const uint32_t step = (table_size >> 1) + (table_size >> 3) + 3;

    std::vector<uint32_t> spread(table_size, std::numeric_limits<uint32_t>::max());
    std::vector<uint32_t> syms;
    syms.reserve(table_size);
    for (uint32_t s = 0; s < alphabet_size; ++s) {
        for (uint32_t i = 0; i < norm[s]; ++i) {
            syms.push_back(s);
        }
    }

    uint32_t pos = 0;
    for (uint32_t s : syms) {
        uint32_t start_pos = pos;
        uint32_t attempts = 0;
        while (spread[pos] != std::numeric_limits<uint32_t>::max()) {
            pos = (pos + step) & table_mask;
            ++attempts;
            if (attempts >= table_size || pos == start_pos) {
                bool placed = false;
                for (uint32_t i = 0; i < table_size; ++i) {
                    if (spread[i] == std::numeric_limits<uint32_t>::max()) {
                        spread[i] = s;
                        pos = (i + step) & table_mask;
                        placed = true;
                        break;
                    }
                }
                if (!placed) {
                    throw std::runtime_error("Spread table placement failed");
                }
                break;
            }
        }
        if (spread[pos] == std::numeric_limits<uint32_t>::max()) {
            spread[pos] = s;
            pos = (pos + step) & table_mask;
        }
    }

    // Build decode table.
    std::vector<uint32_t> symbol_next = norm;
    for (uint32_t u = 0; u < table_size; ++u) {
        const uint32_t s = spread[u];
        const uint32_t next_state_enc = symbol_next[s];
        symbol_next[s] += 1;

        const uint32_t safe_state = std::max(1u, next_state_enc);
        const uint32_t nb_bits = table_log - floor_log2(safe_state);
        const uint32_t new_state_base = (next_state_enc << nb_bits) - table_size;
        dtable[u] = DecodeEntry{
            /*new_state_base=*/new_state_base,
            /*nb_bits=*/static_cast<uint16_t>(nb_bits),
            /*symbol=*/static_cast<uint8_t>(s),
        };
    }

    // Build encode table and symbol transforms.
    std::vector<uint32_t> cumul(alphabet_size, 0);
    {
        uint32_t acc = 0;
        for (uint32_t s = 0; s < alphabet_size; ++s) {
            cumul[s] = acc;
            acc += norm[s];
        }
    }

    {
        std::vector<uint32_t> local_cumul = cumul;
        for (uint32_t u = 0; u < table_size; ++u) {
            const uint32_t s = spread[u];
            const uint32_t idx = local_cumul[s];
            tableU16[idx] = static_cast<uint16_t>(table_size + u);
            local_cumul[s] += 1;
        }
    }

    {
        uint32_t total = 0;
        for (uint32_t s = 0; s < alphabet_size; ++s) {
            const uint32_t freq = norm[s];
            if (freq == 0) {
                const uint32_t delta_nb_bits =
                    ((table_log + 1u) << 16) - (1u << table_log);
                symTT[s] = SymTransform{delta_nb_bits, 0};
                continue;
            }

            uint32_t max_bits_out = table_log;
            if (freq > 1) {
                max_bits_out = table_log - floor_log2(freq - 1u);
            }
            const uint32_t min_state_plus = freq << max_bits_out;
            const uint32_t delta_nb_bits = (max_bits_out << 16) - min_state_plus;
            const int32_t delta_find_state = static_cast<int32_t>(total) -
                                             static_cast<int32_t>(freq);
            total += freq;

            symTT[s] = SymTransform{delta_nb_bits, delta_find_state};
        }
    }
}

FSEEncoderSpec::FSEEncoderSpec(const FSETables& tables) : tables_(tables) {}

EncodedBlock FSEEncoderSpec::encode_block(const std::vector<uint8_t>& symbols) const {
    BitWriter writer;

    const uint32_t block_size = static_cast<uint32_t>(symbols.size());
    writer.append_bits(block_size, tables_.data_block_size_bits);

    if (symbols.empty()) {
        return std::move(writer).finish();
    }

    uint32_t state = tables_.table_size;
    std::vector<std::vector<uint8_t>> chunks;
    chunks.reserve(symbols.size());

    for (auto it = symbols.rbegin(); it != symbols.rend(); ++it) {
        const uint8_t s = *it;
        if (s >= tables_.symTT.size()) {
            fprintf(stderr, "FSEEncoderSpec: symbol %u out of range (size %zu)\n",
                    static_cast<unsigned>(s), tables_.symTT.size());
            throw std::runtime_error("FSEEncoderSpec: symbol out of range for tables");
        }
        const SymTransform& tr = tables_.symTT[s];

        const uint32_t nb_out = (state + tr.delta_nb_bits) >> 16;
        const uint32_t mask = (nb_out == 32) ? 0xFFFFFFFFu : ((1u << nb_out) - 1u);
        const uint32_t out_bits_value = state & mask;

        if (nb_out > 0) {
            chunks.push_back(bits_from_value(out_bits_value, nb_out));
        } else {
            chunks.emplace_back();
        }

        const uint32_t subrange_id = state >> nb_out;
        const uint32_t idx = subrange_id + static_cast<uint32_t>(tr.delta_find_state);
        state = tables_.tableU16[idx];
    }

    assert(state >= tables_.table_size && state < tables_.table_size * 2);
    const uint32_t final_state_offset = state - tables_.table_size;
    writer.append_bits(final_state_offset, tables_.table_log);

    for (auto it = chunks.rbegin(); it != chunks.rend(); ++it) {
        writer.append_bits(*it);
    }

    return std::move(writer).finish();
}

FSEDecoderSpec::FSEDecoderSpec(const FSETables& tables) : tables_(tables) {}

DecodeResult FSEDecoderSpec::decode_block(const uint8_t* bits,
                                          size_t bit_len,
                                          size_t bit_offset) const {
    BitReader br(bits, bit_len, bit_offset);
    DecodeResult result;

    const uint32_t block_size = br.read_bits(tables_.data_block_size_bits);
    result.bits_consumed = tables_.data_block_size_bits;

    if (block_size == 0) {
        return result;
    }

    const uint32_t state_offset = br.read_bits(tables_.table_log);
    uint32_t state = state_offset;
    result.bits_consumed += tables_.table_log;

    result.symbols.resize(block_size);

    for (size_t i = 0; i < block_size; ++i) {
        const DecodeEntry& entry = tables_.dtable[state];
        uint32_t bits_val = 0;
        if (entry.nb_bits > 0) {
            bits_val = br.read_bits(entry.nb_bits);
        }
        state = entry.new_state_base + bits_val;
        result.symbols[i] = entry.symbol;
    }

    result.bits_consumed = br.position() - bit_offset;
#ifndef NDEBUG
    assert(state == 0);
#else
    (void)state;
#endif
    return result;
}

std::unique_ptr<IFSEEncoder> make_encoder(FSELevel level, const FSETables& tables) {
    switch (level) {
        case FSELevel::L0_Spec:
        case FSELevel::L1_Clean:
        case FSELevel::L2_Tuned:
        case FSELevel::L3_Experimental:
        default:
            // Future levels can branch to dedicated implementations.
            return std::make_unique<FSEEncoderSpec>(tables);
    }
}

std::unique_ptr<IFSEDecoder> make_decoder(FSELevel level, const FSETables& tables) {
    switch (level) {
        case FSELevel::L0_Spec:
        case FSELevel::L1_Clean:
        case FSELevel::L2_Tuned:
        case FSELevel::L3_Experimental:
        default:
            return std::make_unique<FSEDecoderSpec>(tables);
    }
}

} // namespace scl::fse
