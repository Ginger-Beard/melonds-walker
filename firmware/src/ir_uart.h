// IrDA SIR side of the dongle: UART1 in hardware IrDA mode driving a
// TFBS4711-class transceiver, packet framing by line idle, echo stripping.
//
// Threading: everything here runs in one high-priority FreeRTOS task (the "IR
// task"). The host task talks to it only through the functions below, which
// are safe to call from the host task.
#pragma once

#include <stddef.h>
#include <stdint.h>

#include <freertos/FreeRTOS.h>
#include <freertos/message_buffer.h>
#include <freertos/task.h>

namespace ir {

// First byte of every message in the IR -> host message buffer.
enum : uint8_t {
    kOutFrame = 'F',  // [kOutFrame][frame type][payload...]: COBS-frame it (framed mode only)
    kOutRaw = 'R',    // [kOutRaw][bytes...]: pass through as-is (raw mode only)
};

// First byte of every message in the host -> IR message buffer.
enum : uint8_t {
    kTxFramed = 'F',  // one IR packet; reply TX_DONE when it has left
    kTxRaw = 'R',     // raw-mode chunk; consecutive chunks are sent back to back
};

// Drive TXD low and the transceiver out of shutdown as early as possible in
// boot. Safe to call before begin().
void early_init();

// Start the IR task. Messages for the host are written to `to_host` (the IR
// task is its only writer) and `host_task` is notified after each one.
bool begin(MessageBufferHandle_t to_host, TaskHandle_t host_task);

// Queue an IR transmission. `kind` is kTxFramed or kTxRaw. Returns false if
// it does not fit in the TX queue right now (nothing is queued then).
bool submit_tx(uint8_t kind, const uint8_t* data, size_t len);

// Bytes of payload that submit_tx() can currently accept in one message.
size_t tx_space();

void set_gap_us(uint16_t us);
void set_echo_guard_us(uint16_t us);
void set_transceiver_enabled(bool on);
void set_raw_mode(bool raw);
bool raw_mode();

// Restore gap_us, echo_guard_us and transceiver_enable to their defaults.
void reset_config();

// millis() of the last IR byte received or packet sent (for the status LED).
uint32_t last_activity_ms();

}  // namespace ir
