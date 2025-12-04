#pragma once

#include <cstddef>
#include "fse.hpp"

namespace scl::fse {

struct BenchConfig {
    FSELevel level;
    uint32_t table_log;
    size_t block_size; // 0 => single block
    bool use_lsb;
    bool use_lsb_wide;
    bool use_lsb_reader;
};

inline BenchConfig config_from_level(int lvl) {
    if (lvl <= 1) {
        // Single-block, MSB baseline
        return BenchConfig{FSELevel::L0_Spec, 12, 0,
                           /*use_lsb=*/false, /*use_lsb_wide=*/false,
                           /*use_lsb_reader=*/false};
    }
    if (lvl == 2) {
        // Single-block, LSB baseline
        return BenchConfig{FSELevel::L0_Spec, 12, 0,
                           /*use_lsb=*/true, /*use_lsb_wide=*/false,
                           /*use_lsb_reader=*/false};
    }
    if (lvl == 3) {
        // Single-block, LSB wide writer
        return BenchConfig{FSELevel::L0_Spec, 12, 0,
                           /*use_lsb=*/true, /*use_lsb_wide=*/true,
                           /*use_lsb_reader=*/false};
    }
    if (lvl <= 4) {
        // Framed, clean path
        uint32_t tl = (lvl == 4) ? 12 : 11;
        return BenchConfig{FSELevel::L0_Spec, tl, 32 * 1024,
                           /*use_lsb=*/true, /*use_lsb_wide=*/true,
                           /*use_lsb_reader=*/false};
    }
    if (lvl == 5) {
        // Framed, MSB writer with LSB reader option
        return BenchConfig{FSELevel::L0_Spec, 12, 0,
                           /*use_lsb=*/true, /*use_lsb_wide=*/true,
                           /*use_lsb_reader=*/true};
    }
    if (lvl <= 8) {
        // Tuned path
        uint32_t tl = (lvl <= 6) ? 11 : 12;
        size_t bs = (lvl <= 6) ? 32 * 1024 : 64 * 1024;
        return BenchConfig{FSELevel::L2_Tuned, tl, bs,
                           /*use_lsb=*/true, /*use_lsb_wide=*/false,
                           /*use_lsb_reader=*/false};
    }
    // Experimental
    return BenchConfig{FSELevel::L3_Experimental, 12, 64 * 1024,
                       /*use_lsb=*/true, /*use_lsb_wide=*/false,
                       /*use_lsb_reader=*/false};
}

} // namespace scl::fse
