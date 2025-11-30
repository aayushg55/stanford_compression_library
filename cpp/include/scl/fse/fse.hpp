#pragma once

#include <cstdint>
#include <memory>
#include <utility>
#include <vector>

namespace scl::fse {

enum class FSELevel {
    L0_Spec,
    L1_Clean,
    L2_Tuned,
    L3_Experimental
};

// Implementation invariant: table_log is capped to 15 to keep state/new_state_base in 16 bits.
constexpr uint32_t kMaxTableLog = 15;

// Encoded bitstream with explicit bit length (last byte may be partially used).
struct EncodedBlock {
    std::vector<uint8_t> bytes;
    size_t bit_count = 0;
};

struct DecodeEntry {
    uint16_t new_state_base = 0; // table_log capped -> fits in 16 bits
    uint8_t nb_bits = 0;
    uint8_t symbol = 0;
};
static_assert(sizeof(DecodeEntry) == 4, "DecodeEntry should remain 4 bytes");

struct SymTransform {
    uint32_t delta_nb_bits = 0;
    int32_t delta_find_state = 0;
};
static_assert(sizeof(SymTransform) == 8, "SymTransform should remain 8 bytes");

struct FSEParams {
    std::vector<uint32_t> counts;       // histogram (size = alphabet)
    uint32_t table_log = 0;             // e.g., 12 for 4096 states
    uint32_t table_size = 0;            // 1 << table_log
    std::vector<uint32_t> normalized;   // normalized freqs summing to table_size
    uint32_t data_block_size_bits = 32; // encoded block-size field width
    uint32_t initial_state = 0;         // equals table_size

    FSEParams(const std::vector<uint32_t>& counts,
              uint32_t table_log,
              uint32_t data_block_size_bits = 32);
};

struct FSETables {
    uint32_t table_log = 0;
    uint32_t table_size = 0;
    uint32_t data_block_size_bits = 32;
    size_t alphabet_size = 0;

    std::vector<uint8_t> slab;           // contiguous storage for all tables
    DecodeEntry* dtable = nullptr;       // decode table
    uint16_t* tableU16 = nullptr;        // encode table
    SymTransform* symTT = nullptr;       // per symbol transforms

    explicit FSETables(const FSEParams& params);
};

struct IFSEEncoder {
    virtual ~IFSEEncoder() = default;
    virtual EncodedBlock encode_block(const std::vector<uint8_t>& symbols) const = 0;
    // Encode into a caller-provided byte buffer; returns bit length.
    virtual size_t encode_block_into(const std::vector<uint8_t>& symbols,
                                     std::vector<uint8_t>& out_bytes) const = 0;
};

class FSEEncoderMSB : public IFSEEncoder {
public:
    explicit FSEEncoderMSB(const FSETables& tables);

    EncodedBlock encode_block(const std::vector<uint8_t>& symbols) const override;
    size_t encode_block_into(const std::vector<uint8_t>& symbols,
                             std::vector<uint8_t>& out_bytes) const override;

private:
    const FSETables& tables_;
};

struct DecodeResult {
    std::vector<uint8_t> symbols;
    size_t bits_consumed = 0;
};

struct IFSEDecoder {
    virtual ~IFSEDecoder() = default;
    virtual DecodeResult decode_block(const uint8_t* bits,
                                      size_t bit_len,
                                      size_t bit_offset = 0) const = 0;
};

class FSEDecoderMSB : public IFSEDecoder {
public:
    explicit FSEDecoderMSB(const FSETables& tables);

    DecodeResult decode_block(const uint8_t* bits,
                              size_t bit_len,
                              size_t bit_offset = 0) const override;

private:
    const FSETables& tables_;
};

// Factories to select encoder/decoder level at runtime.
std::unique_ptr<IFSEEncoder> make_encoder(FSELevel level,
                                          const FSETables& tables,
                                          bool use_lsb = false,
                                          bool use_lsb_wide = false);
std::unique_ptr<IFSEDecoder> make_decoder(FSELevel level, const FSETables& tables, bool use_lsb = false);

} // namespace scl::fse
