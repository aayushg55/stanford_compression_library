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

#include "scl/fse/bitio.hpp"

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
    if (table_log_in > 16) {
        fprintf(stderr, "[sclfse] FSEParams table_log_in=%u exceeds 16, clamping to 12\n", table_log_in);
        table_log = 12;
        throw std::invalid_argument("FSEParams: table_log exceeds 16");
    }
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
        int64_t diff = static_cast<int64_t>(table_size) -
                       static_cast<int64_t>(check_sum);
        // Make a copy of symbol order by descending count to adjust deterministically.
        std::vector<size_t> sym_order(normalized.size());
        std::iota(sym_order.begin(), sym_order.end(), 0);
        std::stable_sort(sym_order.begin(), sym_order.end(),
                         [&](size_t a, size_t b) { return counts[a] > counts[b]; });

        // Adjust up or down one unit at a time to hit the exact target while keeping entries > 0.
        while (diff != 0) {
            bool changed = false;
            for (size_t idx : sym_order) {
                if (diff > 0) {
                    normalized[idx] += 1;
                    diff -= 1;
                    changed = true;
                } else { // diff < 0
                    if (normalized[idx] > 1) {
                        normalized[idx] -= 1;
                        diff += 1;
                        changed = true;
                    }
                }
                if (diff == 0) break;
            }
            // If no symbol could be changed (shouldn't happen), break to avoid infinite loop.
            if (!changed) {
                break;
            }
        }

        const uint64_t final_sum =
            std::accumulate(normalized.begin(), normalized.end(), uint64_t{0});
        if (final_sum != table_size) {
            // As a last resort, assign all weight to the most frequent symbol to keep encoding valid.
            normalized.assign(normalized.size(), 0);
            size_t best = 0;
            if (!counts.empty()) {
                best = static_cast<size_t>(std::distance(
                    counts.begin(), std::max_element(counts.begin(), counts.end())));
            }
            normalized[best] = table_size;
        }
    }
}

FSETables::FSETables(const FSEParams& params)
    : table_log(params.table_log),
      table_size(params.table_size),
      data_block_size_bits(params.data_block_size_bits),
      alphabet_size(params.counts.size()) {
    if (table_log > 16) {
        fprintf(stderr, "FSETables: table_log=%u exceeds 16 (counts=%zu)\n",
                table_log, alphabet_size);
        throw std::invalid_argument("FSETables: table_log too large for 16-bit new_state_base");
    }
    const auto& norm = params.normalized;
    const size_t alpha = norm.size();

    auto align_up = [](size_t off, size_t align) {
        const size_t mask = align - 1;
        return (off + mask) & ~mask;
    };

    size_t offset = 0;
    const size_t dtable_bytes = table_size * sizeof(DecodeEntry);
    const size_t tableU16_bytes = table_size * sizeof(uint16_t);
    const size_t sym_bytes = alpha * sizeof(SymTransform);

    offset = align_up(offset, alignof(DecodeEntry));
    const size_t dtable_off = offset;
    offset += dtable_bytes;

    offset = align_up(offset, alignof(uint16_t));
    const size_t tableU16_off = offset;
    offset += tableU16_bytes;

    offset = align_up(offset, alignof(SymTransform));
    const size_t sym_off = offset;
    offset += sym_bytes;

    slab.resize(offset, 0);
    dtable = reinterpret_cast<DecodeEntry*>(slab.data() + dtable_off);
    tableU16 = reinterpret_cast<uint16_t*>(slab.data() + tableU16_off);
    symTT = reinterpret_cast<SymTransform*>(slab.data() + sym_off);

    // Build spread table with co-prime step algorithm.
    const uint32_t table_mask = table_size - 1;
    const uint32_t step = (table_size >> 1) + (table_size >> 3) + 3;

    std::vector<uint32_t> spread(table_size, std::numeric_limits<uint32_t>::max());
    std::vector<uint32_t> syms;
    syms.reserve(table_size);
    for (uint32_t s = 0; s < alpha; ++s) {
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
            /*new_state_base=*/static_cast<uint16_t>(new_state_base),
            /*nb_bits=*/static_cast<uint8_t>(nb_bits),
            /*symbol=*/static_cast<uint8_t>(s),
        };
    }

    // Build encode table and symbol transforms.
    std::vector<uint32_t> cumul(alpha, 0);
    {
        uint32_t acc = 0;
        for (uint32_t s = 0; s < alpha; ++s) {
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
        for (uint32_t s = 0; s < alpha; ++s) {
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

template <class Writer>
size_t encode_block_impl_into(const std::vector<uint8_t>& symbols,
                              const FSETables& tables,
                              Writer& writer) {
    writer.reset();
    // Rough preallocation: block size bits + table_log bits + payload (~avg).
    const size_t est_bits = static_cast<size_t>(symbols.size()) * tables.table_log +
                            tables.data_block_size_bits + tables.table_log;
    writer.reserve((est_bits + 7) / 8 + 8);
    const uint32_t block_size = static_cast<uint32_t>(symbols.size());
    writer.append_bits(block_size, tables.data_block_size_bits);
    if (symbols.empty()) {
        return writer.finish_into();
    }

    uint32_t state = tables.table_size;
    std::vector<uint32_t> chunk_vals;
    std::vector<uint32_t> chunk_bits;
    chunk_vals.reserve(symbols.size());
    chunk_bits.reserve(symbols.size());

    for (auto it = symbols.rbegin(); it != symbols.rend(); ++it) {
        const uint8_t s = *it;
#ifndef NDEBUG
        if (s >= tables.alphabet_size) {
            fprintf(stderr, "FSEEncoderMSB: symbol %u out of range (size %zu)\n",
                    static_cast<unsigned>(s), tables.alphabet_size);
            throw std::runtime_error("FSEEncoderMSB: symbol out of range for tables");
        }
#endif
        const SymTransform& tr = tables.symTT[s];

        const uint32_t nb_out = (state + tr.delta_nb_bits) >> 16;
        const uint32_t mask = (nb_out == 32) ? 0xFFFFFFFFu : ((1u << nb_out) - 1u);
        const uint32_t out_bits_value = state & mask;

        chunk_vals.push_back(out_bits_value);
        chunk_bits.push_back(nb_out);

        const uint32_t subrange_id = state >> nb_out;
        const uint32_t idx = subrange_id + static_cast<uint32_t>(tr.delta_find_state);
        state = tables.tableU16[idx];
    }

    assert(state >= tables.table_size && state < tables.table_size * 2);
    const uint32_t final_state_offset = state - tables.table_size;
    writer.append_bits(final_state_offset, tables.table_log);

    for (auto val_it = chunk_vals.rbegin(), bits_it = chunk_bits.rbegin();
         val_it != chunk_vals.rend(); ++val_it, ++bits_it) {
        if (*bits_it) writer.append_bits(*val_it, *bits_it);
    }

    return writer.finish_into();
}

template <class Writer>
EncodedBlock encode_block_impl(const std::vector<uint8_t>& symbols, const FSETables& tables) {
    Writer writer;
    const size_t bit_count = encode_block_impl_into(symbols, tables, writer);
    EncodedBlock out;
    out.bytes = writer.move_buffer();
    out.bit_count = bit_count;
    return out;
}

template <class Reader>
DecodeResult decode_block_impl(const uint8_t* bits,
                               size_t bit_len,
                               size_t bit_offset,
                               const FSETables& tables) {
    Reader br(bits, bit_len, bit_offset);
    DecodeResult result;

    const uint32_t block_size = br.read_bits(tables.data_block_size_bits);
    result.bits_consumed = tables.data_block_size_bits;

    if (block_size == 0) {
        return result;
    }

    const uint32_t state_offset = br.read_bits(tables.table_log);
    uint32_t state = state_offset;
    result.bits_consumed += tables.table_log;

    result.symbols.resize(block_size);

    for (size_t i = 0; i < block_size; ++i) {
        const DecodeEntry& entry = tables.dtable[state];
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

FSEEncoderMSB::FSEEncoderMSB(const FSETables& tables) : tables_(tables) {}

EncodedBlock FSEEncoderMSB::encode_block(const std::vector<uint8_t>& symbols) const {
    return encode_block_impl<BitWriterMSB>(symbols, tables_);
}

size_t FSEEncoderMSB::encode_block_into(const std::vector<uint8_t>& symbols,
                                        std::vector<uint8_t>& out_bytes) const {
    BitWriterMSB writer(out_bytes);
    return encode_block_impl_into(symbols, tables_, writer);
}

FSEDecoderMSB::FSEDecoderMSB(const FSETables& tables) : tables_(tables) {}

DecodeResult FSEDecoderMSB::decode_block(const uint8_t* bits,
                                         size_t bit_len,
                                         size_t bit_offset) const {
    return decode_block_impl<BitReaderMSB>(bits, bit_len, bit_offset, tables_);
}

class FSEEncoderLSB : public IFSEEncoder {
public:
    explicit FSEEncoderLSB(const FSETables& tables) : tables_(tables) {}
    EncodedBlock encode_block(const std::vector<uint8_t>& symbols) const override {
        return encode_block_impl<BitWriterLSB8>(symbols, tables_);
    }
    size_t encode_block_into(const std::vector<uint8_t>& symbols,
                             std::vector<uint8_t>& out_bytes) const override {
        BitWriterLSB8 writer(out_bytes);
        return encode_block_impl_into(symbols, tables_, writer);
    }
private:
    const FSETables& tables_;
};

class FSEEncoderLSB64 : public IFSEEncoder {
public:
    explicit FSEEncoderLSB64(const FSETables& tables) : tables_(tables) {}
    EncodedBlock encode_block(const std::vector<uint8_t>& symbols) const override {
        return encode_block_impl<BitWriterLSBWide>(symbols, tables_);
    }
    size_t encode_block_into(const std::vector<uint8_t>& symbols,
                             std::vector<uint8_t>& out_bytes) const override {
        BitWriterLSBWide writer;
        const size_t bit_count = encode_block_impl_into(symbols, tables_, writer);
        out_bytes = writer.move_buffer();
        return bit_count;
    }
private:
    const FSETables& tables_;
};

class FSEDecoderLSB : public IFSEDecoder {
public:
    explicit FSEDecoderLSB(const FSETables& tables) : tables_(tables) {}
    DecodeResult decode_block(const uint8_t* bits,
                              size_t bit_len,
                              size_t bit_offset = 0) const override {
        return decode_block_impl<BitReaderLSB>(bits, bit_len, bit_offset, tables_);
    }
private:
    const FSETables& tables_;
};

template <class EncoderT>
std::unique_ptr<IFSEEncoder> make_encoder_core(FSELevel level, const FSETables& tables) {
    switch (level) {
        case FSELevel::L0_Spec:
        case FSELevel::L1_Clean:
        case FSELevel::L2_Tuned:
        case FSELevel::L3_Experimental:
        default:
            return std::make_unique<EncoderT>(tables);
    }
}

template <class DecoderT>
std::unique_ptr<IFSEDecoder> make_decoder_core(FSELevel level, const FSETables& tables) {
    switch (level) {
        case FSELevel::L0_Spec:
        case FSELevel::L1_Clean:
        case FSELevel::L2_Tuned:
        case FSELevel::L3_Experimental:
        default:
            return std::make_unique<DecoderT>(tables);
    }
}

std::unique_ptr<IFSEEncoder> make_encoder(FSELevel level,
                                          const FSETables& tables,
                                          bool use_lsb,
                                          bool use_lsb_wide) {
    if (!use_lsb) {
        return make_encoder_core<FSEEncoderMSB>(level, tables);
    }
    if (use_lsb_wide) {
        return make_encoder_core<FSEEncoderLSB64>(level, tables);
    }
    return make_encoder_core<FSEEncoderLSB>(level, tables);
}

std::unique_ptr<IFSEDecoder> make_decoder(FSELevel level, const FSETables& tables, bool use_lsb) {
    return use_lsb ? make_decoder_core<FSEDecoderLSB>(level, tables)
                   : make_decoder_core<FSEDecoderMSB>(level, tables);
}

} // namespace scl::fse
