#include "scl/fse/fse.hpp"

#include <array>
#include <cstdint>
#include <iostream>
#include <random>
#include <vector>

using namespace scl::fse;

int main() {
    constexpr size_t kDataSize = 1024;
    std::mt19937 rng(1234);
    std::uniform_int_distribution<int> dist(0, 3);

    std::vector<uint8_t> data;
    data.reserve(kDataSize);
    std::array<uint32_t, 256> counts{};
    for (size_t i = 0; i < kDataSize; ++i) {
        const uint8_t v = static_cast<uint8_t>(dist(rng));
        data.push_back(v);
        counts[v] += 1;
    }

    const uint32_t table_log = 12; // 4096 states
    FSEParams params({counts.begin(), counts.end()}, table_log);
    FSETables tables(params);

    FSEEncoderSpec encoder(tables);
    FSEDecoderSpec decoder(tables);

    const auto encoded = encoder.encode_block(data);
    const auto decoded = decoder.decode_block(encoded.bytes.data(), encoded.bit_count);

    const bool ok = decoded.symbols == data;
    std::cout << "Roundtrip ok? " << (ok ? "yes" : "no") << "\n";
    std::cout << "Encoded bits: " << encoded.bit_count
              << " (bytes stored: " << encoded.bytes.size() << ")\n";

    return ok ? 0 : 1;
}
