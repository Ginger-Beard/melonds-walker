// USB CDC host link. See docs/protocol.md for the wire format.
//
// Writes go straight to TinyUSB (tud_cdc_n_write*) instead of through
// USBCDC::write(), for two reasons:
//   * USBCDC::write() and availableForWrite() return 0 unless DTR is set.
//     Some Android serial stacks never raise DTR, and the protocol must work
//     for them.
//   * USBCDC::write() blocks for up to tx_timeout_ms when the host is not
//     reading. Here every outgoing frame is COBS-encoded into an 8 KiB ring
//     and drained into the 64-byte TinyUSB FIFO as space appears. If the ring
//     is full the whole frame is dropped, so nothing ever blocks on USB.
// Only this task writes to the CDC interface, so no extra locking is needed.
//
// Mode handling: raw mode is left only when the USB device is (re)mounted or
// unmounted (unplug, bus reset / re-enumeration). Closing the port or dropping
// DTR deliberately does NOT leave raw mode (see docs/protocol.md). USB
// suspend does not leave raw mode either, because a host may autosuspend an
// idle device between the RAW_MODE sender closing the port and the raw-mode
// consumer opening it.

#include "host_link.h"

#include <atomic>
#include <string.h>

#include <Arduino.h>
#include <USB.h>
#include <USBCDC.h>
// TinyUSB's headers trip -Wextra; keep our own sources warning-clean.
#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wextra"
#pragma GCC diagnostic ignored "-Wmissing-field-initializers"
#include <esp32-hal-tinyusb.h>
#pragma GCC diagnostic pop

#include "cobs.h"
#include "config.h"
#include "ir_uart.h"
#include "protocol.h"

#if ARDUINO_USB_MODE != 0
#error "Build with -DARDUINO_USB_MODE=0 (TinyUSB / USB-OTG mode)"
#endif

namespace host {
namespace {

constexpr uint16_t kUsbVid = 0x303A;
constexpr uint16_t kUsbPid = 0x4001;
constexpr const char* kUsbManufacturer = "melonDS-walker";
constexpr const char* kUsbProduct = "melonDS-walker IR dongle";
constexpr uint8_t kCdcItf = 0;

constexpr size_t kIrOutMbSize = 8192;
constexpr size_t kRingSize = 8192;
constexpr size_t kEncMax = cobs_max_encoded_len(proto::kMaxFrame);

USBCDC s_cdc(kCdcItf);
MessageBufferHandle_t s_ir_out = nullptr;
TaskHandle_t s_task = nullptr;

std::atomic<bool> s_usb_reset{false};  // mounted or unmounted since last check
std::atomic<bool> s_dtr_rose{false};   // a host just opened the port
bool s_last_dtr = false;               // touched only from the USB event task

struct Stats {
    uint32_t frames_dropped = 0;
} s_stats;

// --------------------------------------------------------------------------
// Output ring (host task only)
// --------------------------------------------------------------------------

struct Ring {
    uint8_t data[kRingSize];
    size_t head = 0;  // write
    size_t tail = 0;  // read
    size_t used = 0;

    size_t space() const { return kRingSize - used; }
    void clear() { head = tail = used = 0; }
    void put(const uint8_t* p, size_t n) {
        for (size_t i = 0; i < n; i++) {
            data[head] = p[i];
            head = (head + 1) % kRingSize;
        }
        used += n;
    }
    // Contiguous readable span.
    size_t peek(const uint8_t** p) const {
        *p = data + tail;
        size_t n = (tail + used <= kRingSize) ? used : kRingSize - tail;
        return n;
    }
    void consume(size_t n) {
        tail = (tail + n) % kRingSize;
        used -= n;
    }
};
Ring s_ring;

// Queue one complete encoded frame (with delimiter) or drop it whole.
bool ring_put_frame(const uint8_t* enc, size_t n) {
    if (s_ring.space() < n + 1) {
        s_stats.frames_dropped++;
        return false;
    }
    static const uint8_t kDelim = 0;
    s_ring.put(enc, n);
    s_ring.put(&kDelim, 1);
    return true;
}

bool send_frame(uint8_t type, const uint8_t* a, size_t alen, const uint8_t* b = nullptr, size_t blen = 0) {
    uint8_t dec[proto::kMaxFrame];
    if (1 + alen + blen > sizeof(dec)) {
        return false;
    }
    dec[0] = type;
    if (alen) memcpy(dec + 1, a, alen);
    if (blen) memcpy(dec + 1 + alen, b, blen);
    uint8_t enc[kEncMax];
    const size_t n = cobs_encode(dec, 1 + alen + blen, enc, sizeof(enc));
    return n && ring_put_frame(enc, n);
}

void send_error(uint8_t code, const char* text) {
    send_frame(proto::kError, &code, 1, reinterpret_cast<const uint8_t*>(text), strlen(text));
}

void send_config_ack(uint8_t key, uint8_t status) {
    const uint8_t p[2] = {key, status};
    send_frame(proto::kConfigAck, p, sizeof(p));
}

void drain_ring_to_usb() {
    if (!tud_mounted()) {
        s_ring.clear();  // nobody to deliver to
        return;
    }
    bool wrote = false;
    while (s_ring.used) {
        const uint32_t avail = tud_cdc_n_write_available(kCdcItf);
        if (!avail) {
            break;
        }
        const uint8_t* p;
        size_t n = s_ring.peek(&p);
        if (n > avail) n = avail;
        const uint32_t w = tud_cdc_n_write(kCdcItf, p, n);
        if (!w) {
            break;
        }
        s_ring.consume(w);
        wrote = true;
    }
    if (wrote) {
        tud_cdc_n_write_flush(kCdcItf);
    }
}

// --------------------------------------------------------------------------
// IR task -> host
// --------------------------------------------------------------------------

void pump_ir_output() {
    uint8_t msg[2 + proto::kMaxFrame];
    uint8_t enc[kEncMax];
    const bool raw = ir::raw_mode();
    for (;;) {
        const size_t n = xMessageBufferReceive(s_ir_out, msg, sizeof(msg), 0);
        if (n == 0) {
            return;
        }
        if (msg[0] == ir::kOutFrame && !raw && n >= 2) {
            const size_t e = cobs_encode(msg + 1, n - 1, enc, sizeof(enc));
            if (e) ring_put_frame(enc, e);
        } else if (msg[0] == ir::kOutRaw && raw) {
            if (s_ring.space() >= n - 1) {
                s_ring.put(msg + 1, n - 1);
            } else {
                s_stats.frames_dropped++;
            }
        }
        // Anything else was produced under the other mode: drop it.
    }
}

// --------------------------------------------------------------------------
// Commands
// --------------------------------------------------------------------------

uint16_t get_u16le(const uint8_t* p) { return static_cast<uint16_t>(p[0] | (p[1] << 8)); }

void cmd_set_config(const uint8_t* p, size_t len) {
    if (len < 1) {
        send_error(proto::kErrMalformed, "SET_CONFIG without key");
        return;
    }
    const uint8_t key = p[0];
    const uint8_t* v = p + 1;
    const size_t vlen = len - 1;
    switch (key) {
        case proto::kCfgGapUs:
            if (vlen != 2) return send_config_ack(key, proto::kStatusBadLength);
            if (get_u16le(v) < proto::kMinGapUs) return send_config_ack(key, proto::kStatusBadValue);
            ir::set_gap_us(get_u16le(v));
            return send_config_ack(key, proto::kStatusOk);
        case proto::kCfgEchoGuardUs:
            if (vlen != 2) return send_config_ack(key, proto::kStatusBadLength);
            ir::set_echo_guard_us(get_u16le(v));
            return send_config_ack(key, proto::kStatusOk);
        case proto::kCfgTransceiverEnable:
            if (vlen != 1) return send_config_ack(key, proto::kStatusBadLength);
            if (v[0] > 1) return send_config_ack(key, proto::kStatusBadValue);
            ir::set_transceiver_enabled(v[0] == 1);
            return send_config_ack(key, proto::kStatusOk);
        default: {
            char msg[32];
            snprintf(msg, sizeof(msg), "bad config key 0x%02x", key);
            send_error(proto::kErrBadConfigKey, msg);
        }
    }
}

void cmd_raw_mode() {
    // Flush framed IR output queued so far, then the ACK, then switch. Every
    // byte after the ACK on the wire is raw.
    pump_ir_output();
    send_config_ack(proto::kCfgRawModeAckKey, proto::kStatusOk);
    ir::set_raw_mode(true);
}

void dispatch(const uint8_t* f, size_t len) {
    const uint8_t type = f[0];
    const uint8_t* p = f + 1;
    const size_t plen = len - 1;
    switch (type) {
        case proto::kIrTx:
            if (plen == 0) {
                send_error(proto::kErrMalformed, "empty IR_TX");
            } else if (plen > proto::kMaxIrPacket) {
                send_error(proto::kErrTxTooLong, "IR_TX longer than 256 bytes");
            } else if (!ir::submit_tx(ir::kTxFramed, p, plen)) {
                send_error(proto::kErrTxQueueFull, "IR TX queue full");
            }
            break;
        case proto::kIdentify: {
            uint8_t r[4 + 2 + sizeof(FW_VERSION_STRING)];
            memcpy(r, proto::kMagic, 4);
            r[4] = proto::kVersion;
            r[5] = proto::kCapFramed | proto::kCapRaw;
            const size_t vl = strlen(FW_VERSION_STRING);
            memcpy(r + 6, FW_VERSION_STRING, vl);
            send_frame(proto::kIdentifyResp, r, 6 + vl);
            break;
        }
        case proto::kSetConfig:
            cmd_set_config(p, plen);
            break;
        case proto::kRawMode:
            cmd_raw_mode();
            break;
        case proto::kPing:
            if (plen > proto::kMaxPing) {
                send_error(proto::kErrMalformed, "PING payload longer than 32 bytes");
            } else {
                send_frame(proto::kPong, p, plen);
            }
            break;
        default: {
            char msg[24];
            snprintf(msg, sizeof(msg), "unknown type 0x%02x", type);
            send_error(proto::kErrUnknownType, msg);
        }
    }
}

// --------------------------------------------------------------------------
// USB -> dongle
// --------------------------------------------------------------------------

struct FrameAccumulator {
    uint8_t buf[kEncMax];
    size_t len = 0;
    bool overflow = false;
    void reset() {
        len = 0;
        overflow = false;
    }
};
FrameAccumulator s_acc;

// Feed framed-mode bytes. Returns how many were consumed; stops early if a
// RAW_MODE command switched modes (the rest of the chunk is raw data).
size_t feed_framed(const uint8_t* data, size_t n) {
    for (size_t i = 0; i < n; i++) {
        const uint8_t b = data[i];
        if (b != 0) {
            if (s_acc.len < sizeof(s_acc.buf)) {
                s_acc.buf[s_acc.len++] = b;
            } else {
                s_acc.overflow = true;
            }
            continue;
        }
        // Delimiter. Empty frames (0x00 0x00) are ignored: hosts may send a
        // lone 0x00 to resynchronise.
        if (s_acc.overflow) {
            send_error(proto::kErrMalformed, "frame longer than 300 bytes");
        } else if (s_acc.len) {
            uint8_t dec[proto::kMaxFrame];
            const int dl = cobs_decode(s_acc.buf, s_acc.len, dec, sizeof(dec));
            if (dl < 0) {
                send_error(proto::kErrMalformed, "bad COBS");
            } else if (dl == 0) {
                send_error(proto::kErrMalformed, "frame without type");
            } else {
                dispatch(dec, static_cast<size_t>(dl));
            }
        }
        s_acc.reset();
        if (ir::raw_mode()) {
            return i + 1;
        }
    }
    return n;
}

void pump_usb_input() {
    uint8_t chunk[256];
    for (;;) {
        const int avail = s_cdc.available();
        if (avail <= 0) {
            return;
        }
        if (ir::raw_mode()) {
            // Back-pressure: only take what the IR TX queue can hold; the rest
            // stays queued in USBCDC (and then in TinyUSB, which NAKs).
            size_t want = static_cast<size_t>(avail);
            const size_t space = ir::tx_space();
            if (want > space) want = space;
            if (want > sizeof(chunk)) want = sizeof(chunk);
            if (want == 0) {
                return;
            }
            const size_t got = s_cdc.read(chunk, want);
            if (got) ir::submit_tx(ir::kTxRaw, chunk, got);
            continue;
        }
        size_t want = static_cast<size_t>(avail);
        if (want > sizeof(chunk)) want = sizeof(chunk);
        const size_t got = s_cdc.read(chunk, want);
        if (got == 0) {
            return;
        }
        const size_t used = feed_framed(chunk, got);
        if (used < got) {
            // Switched to raw mid-chunk: the remainder is raw data.
            if (!ir::submit_tx(ir::kTxRaw, chunk + used, got - used)) {
                log_w("raw: dropped %u bytes after RAW_MODE", static_cast<unsigned>(got - used));
            }
        }
    }
}

// --------------------------------------------------------------------------
// Status LED
// --------------------------------------------------------------------------

void led_update() {
#if STATUS_LED_PIN >= 0
    // 0 = off, 1 = idle, 2 = IR activity
    static int shown = -1;
    const bool active = (millis() - ir::last_activity_ms()) < 40 && ir::last_activity_ms() != 0;
    const bool raw = ir::raw_mode();
    const bool mounted = tud_mounted();
    const int want = active ? 2 : (mounted ? 1 : 0);
    const int key = want | (raw ? 4 : 0);
    if (key == shown) {
        return;
    }
    shown = key;
#if STATUS_LED_RGB
    // idle: dim green (framed) / dim magenta (raw); activity: bright white-ish
    if (want == 2) {
        rgbLedWrite(STATUS_LED_PIN, 40, 40, 40);
    } else if (want == 1) {
        rgbLedWrite(STATUS_LED_PIN, raw ? 6 : 0, raw ? 0 : 6, raw ? 6 : 0);
    } else {
        rgbLedWrite(STATUS_LED_PIN, 0, 0, 0);
    }
#else
    // single LED: lit only on IR activity
    const bool on = (want == 2);
    digitalWrite(STATUS_LED_PIN, (on != (STATUS_LED_ACTIVE_LOW != 0)) ? HIGH : LOW);
#endif
#endif
}

// --------------------------------------------------------------------------
// Events and task
// --------------------------------------------------------------------------

void usb_event_cb(void*, esp_event_base_t base, int32_t id, void*) {
    if (base == ARDUINO_USB_EVENTS && (id == ARDUINO_USB_STARTED_EVENT || id == ARDUINO_USB_STOPPED_EVENT)) {
        s_usb_reset.store(true);
        if (s_task) xTaskNotifyGive(s_task);
    }
}

void cdc_event_cb(void*, esp_event_base_t base, int32_t id, void* data) {
    if (base != ARDUINO_USB_CDC_EVENTS) {
        return;
    }
    if (id == ARDUINO_USB_CDC_LINE_STATE_EVENT) {
        const auto* d = static_cast<arduino_usb_cdc_event_data_t*>(data);
        if (d->line_state.dtr && !s_last_dtr) {
            s_dtr_rose.store(true);
        }
        s_last_dtr = d->line_state.dtr;
    } else if (id == ARDUINO_USB_CDC_RX_OVERFLOW_EVENT) {
        log_w("CDC RX overflow");
    }
    if (s_task) xTaskNotifyGive(s_task);
}

void discard_pending_output() {
    s_ring.clear();
    tud_cdc_n_write_clear(kCdcItf);
}

void host_task(void*) {
    for (;;) {
        ulTaskNotifyTake(pdTRUE, s_ring.used ? 1 : pdMS_TO_TICKS(10));

        if (s_usb_reset.exchange(false)) {
            // (Re)enumerated or unplugged: back to framed mode and defaults.
            ir::set_raw_mode(false);
            ir::reset_config();
            s_acc.reset();
            discard_pending_output();
            // Messages the IR task queued under raw mode are dropped by
            // pump_ir_output() now that the mode is framed. (No
            // xMessageBufferReset: the IR task may be writing concurrently.)
        }
        if (s_dtr_rose.exchange(false)) {
            // A host just opened the port: do not hand it stale bytes that
            // piled up while nobody was listening.
            discard_pending_output();
        }

        pump_usb_input();
        pump_ir_output();
        drain_ring_to_usb();
        led_update();
    }
}

}  // namespace

bool begin() {
    s_ir_out = xMessageBufferCreate(kIrOutMbSize);
    if (!s_ir_out) {
        return false;
    }

#if STATUS_LED_PIN >= 0 && !STATUS_LED_RGB
    pinMode(STATUS_LED_PIN, OUTPUT);
    digitalWrite(STATUS_LED_PIN, STATUS_LED_ACTIVE_LOW ? HIGH : LOW);
#endif

    // Start the task first so event callbacks have someone to notify.
    if (xTaskCreatePinnedToCore(host_task, "host", 6144, nullptr, HOST_TASK_PRIORITY, &s_task, tskNO_AFFINITY) !=
        pdPASS) {
        return false;
    }

    USB.VID(kUsbVid);
    USB.PID(kUsbPid);
    USB.manufacturerName(kUsbManufacturer);
    USB.productName(kUsbProduct);
    USB.onEvent(usb_event_cb);

    s_cdc.onEvent(cdc_event_cb);
    s_cdc.setRxBufferSize(1024);
    // Keep the core's esptool DTR/RTS reset sequence and 1200-baud touch
    // working, so `pio run -t upload` can reboot into the ROM bootloader.
    s_cdc.enableReboot(true);
    s_cdc.begin();
    return USB.begin();
}

MessageBufferHandle_t ir_out_buffer() { return s_ir_out; }
TaskHandle_t task_handle() { return s_task; }

}  // namespace host
