// Consistent Overhead Byte Stuffing (COBS) encoder/decoder.
//
// Plain C++ with no platform dependencies, so the same code runs in the
// firmware and in the host-side unit tests (pio test -e native).
//
// Conventions (match docs/protocol.md and tools/walkerctl.py):
//   - The encoded output never contains 0x00.
//   - The 0x00 frame delimiter is NOT written by cobs_encode and must NOT be
//     passed to cobs_decode. The caller appends / strips it.
#pragma once

#include <stddef.h>
#include <stdint.h>

// Worst-case encoded size for `n` input bytes (without the delimiter).
// One code byte per started 254-byte block, plus one for the empty block.
constexpr size_t cobs_max_encoded_len(size_t n) { return n + n / 254 + 1; }

// Encode `len` bytes from `src` into `dst`. `dst_cap` must be at least
// cobs_max_encoded_len(len). Returns the number of bytes written, or 0 if
// `dst_cap` is too small. (A valid encoding is never 0 bytes long.)
size_t cobs_encode(const uint8_t* src, size_t len, uint8_t* dst, size_t dst_cap);

// Decode `len` bytes of COBS data from `src` into `dst`. Returns the decoded
// length, or -1 if the input is malformed (contains 0x00, a code byte runs
// past the end) or the output would exceed `dst_cap`. Empty input decodes to
// an empty output (returns 0). `src` and `dst` may be the same buffer.
int cobs_decode(const uint8_t* src, size_t len, uint8_t* dst, size_t dst_cap);
