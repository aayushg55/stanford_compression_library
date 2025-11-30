#pragma once

#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

size_t sclfse_compress_level(const void* src, size_t srcSize, void* dst, size_t dstCapacity, int level);
size_t sclfse_decompress_level(void* dst, size_t dstCapacity, const void* src, size_t srcSize, int level);

#ifdef __cplusplus
}
#endif
