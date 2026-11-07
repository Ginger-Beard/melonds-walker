#include "cobs.h"

size_t cobs_encode(const uint8_t* src, size_t len, uint8_t* dst, size_t dst_cap) {
    if (dst_cap < cobs_max_encoded_len(len)) {
        return 0;
    }
    size_t out = 1;       // next write position
    size_t code_pos = 0;  // where the current block's code byte goes
    uint8_t code = 1;     // 1 + number of data bytes in the current block

    for (size_t i = 0; i < len; i++) {
        if (src[i] == 0) {
            dst[code_pos] = code;
            code_pos = out++;
            code = 1;
        } else {
            dst[out++] = src[i];
            code++;
            if (code == 0xFF) {
                // Full 254-byte block: close it. A new block starts even if
                // this was the last byte; that matches the reference
                // algorithm and the length bound above.
                dst[code_pos] = code;
                code_pos = out++;
                code = 1;
            }
        }
    }
    dst[code_pos] = code;
    return out;
}

int cobs_decode(const uint8_t* src, size_t len, uint8_t* dst, size_t dst_cap) {
    size_t in = 0;
    size_t out = 0;

    while (in < len) {
        const uint8_t code = src[in++];
        if (code == 0) {
            return -1;
        }
        const size_t n = static_cast<size_t>(code) - 1;
        if (n > len - in) {
            return -1;  // block runs past the end of the input
        }
        if (n > dst_cap - out) {
            return -1;
        }
        for (size_t k = 0; k < n; k++) {
            const uint8_t b = src[in++];
            if (b == 0) {
                return -1;
            }
            dst[out++] = b;
        }
        // A block shorter than 254 data bytes implies a zero after it,
        // unless it is the final block.
        if (code != 0xFF && in < len) {
            if (out >= dst_cap) {
                return -1;
            }
            dst[out++] = 0;
        }
    }
    return static_cast<int>(out);
}
