// Host-side unit tests for lib/cobs. Run with: pio test -e native
#include <unity.h>

#include <stdlib.h>
#include <string.h>

#include "cobs.h"

void setUp() {}
void tearDown() {}

static void check_vector(const uint8_t* raw, size_t raw_len, const uint8_t* enc, size_t enc_len) {
    uint8_t buf[600];
    size_t n = cobs_encode(raw, raw_len, buf, sizeof(buf));
    TEST_ASSERT_EQUAL_UINT(enc_len, n);
    TEST_ASSERT_EQUAL_UINT8_ARRAY(enc, buf, enc_len);

    uint8_t dec[600];
    int m = cobs_decode(enc, enc_len, dec, sizeof(dec));
    TEST_ASSERT_EQUAL_INT((int)raw_len, m);
    if (raw_len) {
        TEST_ASSERT_EQUAL_UINT8_ARRAY(raw, dec, raw_len);
    }
}

// Vectors from the COBS paper / Wikipedia.
static void test_known_vectors() {
    { const uint8_t e[] = {0x01}; check_vector(nullptr, 0, e, sizeof e); }
    { const uint8_t r[] = {0x00}; const uint8_t e[] = {0x01, 0x01}; check_vector(r, sizeof r, e, sizeof e); }
    { const uint8_t r[] = {0x00, 0x00}; const uint8_t e[] = {0x01, 0x01, 0x01}; check_vector(r, sizeof r, e, sizeof e); }
    { const uint8_t r[] = {0x00, 0x11, 0x00}; const uint8_t e[] = {0x01, 0x02, 0x11, 0x01}; check_vector(r, sizeof r, e, sizeof e); }
    { const uint8_t r[] = {0x11, 0x22, 0x00, 0x33}; const uint8_t e[] = {0x03, 0x11, 0x22, 0x02, 0x33}; check_vector(r, sizeof r, e, sizeof e); }
    { const uint8_t r[] = {0x11, 0x22, 0x33, 0x44}; const uint8_t e[] = {0x05, 0x11, 0x22, 0x33, 0x44}; check_vector(r, sizeof r, e, sizeof e); }
    { const uint8_t r[] = {0x11, 0x00, 0x00, 0x00}; const uint8_t e[] = {0x02, 0x11, 0x01, 0x01, 0x01}; check_vector(r, sizeof r, e, sizeof e); }
}

static void test_254_nonzero() {
    uint8_t raw[254];
    for (int i = 0; i < 254; i++) raw[i] = (uint8_t)(i + 1);
    uint8_t enc[300];
    size_t n = cobs_encode(raw, sizeof raw, enc, sizeof enc);
    TEST_ASSERT_EQUAL_UINT(256, n);  // FF + 254 data + trailing 01
    TEST_ASSERT_EQUAL_HEX8(0xFF, enc[0]);
    TEST_ASSERT_EQUAL_HEX8(0x01, enc[255]);
    uint8_t dec[300];
    TEST_ASSERT_EQUAL_INT(254, cobs_decode(enc, n, dec, sizeof dec));
    TEST_ASSERT_EQUAL_UINT8_ARRAY(raw, dec, 254);
    // The shorter form without the trailing 01 must decode identically.
    TEST_ASSERT_EQUAL_INT(254, cobs_decode(enc, 255, dec, sizeof dec));
    TEST_ASSERT_EQUAL_UINT8_ARRAY(raw, dec, 254);
}

static void test_255_nonzero_then_zero() {
    uint8_t raw[256];
    for (int i = 0; i < 255; i++) raw[i] = (uint8_t)((i % 255) + 1);
    raw[255] = 0;
    uint8_t enc[300];
    size_t n = cobs_encode(raw, sizeof raw, enc, sizeof enc);
    TEST_ASSERT_TRUE(n > 0 && n <= cobs_max_encoded_len(sizeof raw));
    for (size_t i = 0; i < n; i++) TEST_ASSERT_NOT_EQUAL(0, enc[i]);
    uint8_t dec[300];
    TEST_ASSERT_EQUAL_INT(256, cobs_decode(enc, n, dec, sizeof dec));
    TEST_ASSERT_EQUAL_UINT8_ARRAY(raw, dec, 256);
}

static void test_roundtrip_random() {
    srand(12345);
    uint8_t raw[300], enc[310], dec[300];
    for (int iter = 0; iter < 2000; iter++) {
        size_t len = (size_t)(rand() % 301);
        int zero_bias = rand() % 4;  // vary zero density
        for (size_t i = 0; i < len; i++) {
            raw[i] = (rand() % 8 < zero_bias) ? 0 : (uint8_t)(rand() & 0xFF);
        }
        size_t n = cobs_encode(raw, len, enc, sizeof enc);
        TEST_ASSERT_TRUE(n > 0);
        TEST_ASSERT_TRUE(n <= cobs_max_encoded_len(len));
        TEST_ASSERT_NULL(memchr(enc, 0, n));
        int m = cobs_decode(enc, n, dec, sizeof dec);
        TEST_ASSERT_EQUAL_INT((int)len, m);
        if (len) TEST_ASSERT_EQUAL_UINT8_ARRAY(raw, dec, len);
    }
}

static void test_encode_buffer_too_small() {
    const uint8_t raw[] = {1, 2, 3};
    uint8_t enc[3];
    TEST_ASSERT_EQUAL_UINT(0, cobs_encode(raw, sizeof raw, enc, sizeof enc));
}

static void test_decode_rejects_malformed() {
    uint8_t dec[16];
    { const uint8_t e[] = {0x00}; TEST_ASSERT_EQUAL_INT(-1, cobs_decode(e, sizeof e, dec, sizeof dec)); }
    { const uint8_t e[] = {0x03, 0x11}; TEST_ASSERT_EQUAL_INT(-1, cobs_decode(e, sizeof e, dec, sizeof dec)); }
    { const uint8_t e[] = {0x03, 0x11, 0x00}; TEST_ASSERT_EQUAL_INT(-1, cobs_decode(e, sizeof e, dec, sizeof dec)); }
    { const uint8_t e[] = {0x02, 0x11, 0x00, 0x01}; TEST_ASSERT_EQUAL_INT(-1, cobs_decode(e, sizeof e, dec, sizeof dec)); }
    // Empty input is an empty frame, not an error.
    TEST_ASSERT_EQUAL_INT(0, cobs_decode(dec, 0, dec, sizeof dec));
}

static void test_decode_respects_capacity() {
    const uint8_t e[] = {0x05, 0x11, 0x22, 0x33, 0x44};
    uint8_t dec[4];
    TEST_ASSERT_EQUAL_INT(4, cobs_decode(e, sizeof e, dec, 4));
    TEST_ASSERT_EQUAL_INT(-1, cobs_decode(e, sizeof e, dec, 3));
    // Implicit trailing zero must also fit.
    const uint8_t e2[] = {0x02, 0x11, 0x02, 0x22};  // 11 00 22
    TEST_ASSERT_EQUAL_INT(-1, cobs_decode(e2, sizeof e2, dec, 2));
    TEST_ASSERT_EQUAL_INT(3, cobs_decode(e2, sizeof e2, dec, 3));
}

static void test_decode_in_place() {
    const uint8_t raw[] = {0x81, 0x00, 0x10, 0x00, 0x00, 0xAA, 0x55};
    uint8_t buf[16];
    size_t n = cobs_encode(raw, sizeof raw, buf, sizeof buf);
    int m = cobs_decode(buf, n, buf, sizeof buf);
    TEST_ASSERT_EQUAL_INT((int)sizeof raw, m);
    TEST_ASSERT_EQUAL_UINT8_ARRAY(raw, buf, sizeof raw);
}

int main() {
    UNITY_BEGIN();
    RUN_TEST(test_known_vectors);
    RUN_TEST(test_254_nonzero);
    RUN_TEST(test_255_nonzero_then_zero);
    RUN_TEST(test_roundtrip_random);
    RUN_TEST(test_encode_buffer_too_small);
    RUN_TEST(test_decode_rejects_malformed);
    RUN_TEST(test_decode_respects_capacity);
    RUN_TEST(test_decode_in_place);
    return UNITY_END();
}
