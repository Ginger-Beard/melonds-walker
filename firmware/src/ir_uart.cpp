// IrDA SIR transport on UART1. See ir_uart.h for the threading contract.
//
// Design notes
// ------------
// * Hardware IrDA mode. The ESP32-S3 UART has the classic ESP32 IrDA block:
//   conf0.irda_en / irda_tx_en / irda_dplx / irda_wctl / irda_tx_inv /
//   irda_rx_inv (soc/esp32s3/register/soc/uart_struct.h) and the IDF HAL maps
//   UART_MODE_IRDA to uart_ll_set_mode_irda() (hal/esp32s3/include/hal/
//   uart_ll.h). The encoder makes the 3/16-bit SIR pulses (~1.6 us at
//   115200), so TXD is never held high long enough to hit the TFBS4711's
//   100 us LED watchdog (the TFDU4101's is 50 us).
//
// * irda_tx_en. The IDF driver sets irda_en but never touches irda_tx_en
//   ("start enable bit for IrDA transmitter"). The TRM describes the IrDA
//   block as half duplex, and an esp32.com report says RX only worked once
//   TX was not permanently enabled (or DPLX was set). We therefore raise
//   irda_tx_en only while a packet is going out and clear it to receive.
//
// * TXD idle level. Outside a transmission the TX pad is detached from the
//   UART and driven as a plain GPIO low, so the LED is guaranteed dark at
//   boot, in shutdown, and between packets, whatever the UART's idle output
//   happens to be in IrDA mode. The external pull-down covers reset/boot.
//
// * RX latency. RX FIFO full threshold = 1, so the driver ISR moves every
//   byte into its ring buffer as soon as its stop bit is in and posts a
//   UART_DATA event. The IR task timestamps on that event with esp_timer.
//
// * End of packet. An esp_timer one-shot fires gap_us after the packet's
//   first byte and re-arms itself for the remaining time until the line has
//   really been idle for gap_us since the last byte. It posts a private event
//   into the same queue the UART driver uses, so the IR task blocks on a
//   single queue for UART data, gap expiry and TX requests.
//
// * Echo stripping. The transceiver echoes our own pulses back on RXD.
//   Everything received during a transmission and for echo_guard_us after
//   uart_wait_tx_done() returns is discarded with uart_flush_input(). The
//   walker starts replying ~150 us after our last stop bit, so the guard must
//   stay well below that (default 50 us; the TX-done wake-up adds ~10-20 us).
//
// * TX bursts. The walker ends a packet after ~122 us of idle, so a packet
//   must leave as one continuous burst. The driver is installed WITHOUT a TX
//   ring buffer: uart_write_bytes() then copies straight into the 128-byte
//   hardware FIFO from this task (an empty FIFO takes a whole 128-byte packet
//   in one go). For longer packets (real ones are at most 136 bytes) the
//   driver tops the FIFO up from this task when it falls below 10 bytes,
//   i.e. with ~870 us of slack, and this is the highest-priority task on its
//   core, so the FIFO cannot run dry mid-packet.
//
// * TX queue and pacing. Framed IR_TX packets queue in a FIFO of
//   kTxFifoDepth entries. A packet starts only once the line has been idle
//   for gap_us: after the end of any RX packet (gap elapsed and its IR_RX
//   sent) and after the end of our previous transmitted packet, so the
//   receiver always sees separate packets.
//
// * Why a dedicated task rather than a loop(): the IR task must react to
//   bytes within microseconds and must never wait behind USB. A
//   high-priority task pinned to core 1 (TinyUSB, the Arduino event loop and
//   esp_timer live on core 0 by default) blocks on one queue and is woken
//   directly by the UART ISR, which gives lower and steadier latency than
//   polling from loop() while the host task deals with USB at lower priority.

#include "ir_uart.h"

#include <atomic>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include <Arduino.h>
#include <driver/gpio.h>
#include <driver/uart.h>
#include <esp_rom_gpio.h>
#include <esp_rom_sys.h>
#include <esp_timer.h>
#include <freertos/queue.h>
#include <hal/uart_ll.h>
#include <soc/gpio_sig_map.h>
#include <soc/soc_caps.h>
#include <soc/uart_periph.h>

#include "config.h"
#include "protocol.h"

#if !defined(CONFIG_IDF_TARGET_ESP32S3)
#error "This firmware targets the ESP32-S3"
#endif
#if IR_UART_NUM >= SOC_UART_HP_NUM
#error "IR_UART_NUM must be a high-power UART (0..2 on the S3)"
#endif

namespace ir {
namespace {

constexpr uart_port_t kPort = static_cast<uart_port_t>(IR_UART_NUM);
constexpr int kBaud = 115200;
constexpr int64_t kByteUs = (10 * 1000000 + kBaud - 1) / kBaud;  // 8N1 = 10 bits, ~87 us

constexpr int kRxRingSize = 1024;   // driver RX ring buffer (> SOC_UART_FIFO_LEN)
constexpr int kTxRingSize = 0;      // no TX ring: write straight into the FIFO (see "TX bursts")
constexpr int kTxFifoDepth = 8;     // queued framed IR_TX packets
constexpr int kEventQueueLen = 64;
constexpr size_t kTxMbSize = 2048;  // host -> IR message buffer

// Private event types posted into the UART driver's event queue.
constexpr int kEvtGap = UART_EVENT_MAX + 1;
constexpr int kEvtWake = UART_EVENT_MAX + 2;  // TX queued, mode change, TX pacing timer

QueueHandle_t s_evt_q = nullptr;
MessageBufferHandle_t s_tx_mb = nullptr;
MessageBufferHandle_t s_out_mb = nullptr;
TaskHandle_t s_host_task = nullptr;
esp_timer_handle_t s_gap_timer = nullptr;      // RX end-of-packet
esp_timer_handle_t s_tx_pace_timer = nullptr;  // idle time before the next TX
std::atomic<int> s_tx_framed_queued{0};
int64_t s_last_tx_end_us = INT64_MIN / 2;  // end of our last framed packet

std::atomic<uint32_t> s_gap_us{proto::kDefaultGapUs};
std::atomic<uint32_t> s_echo_guard_us{proto::kDefaultEchoGuardUs};
std::atomic<bool> s_raw{false};
std::atomic<uint32_t> s_activity_ms{0};

// RX state, owned by the IR task.
struct RxState {
    bool active = false;     // a packet is in progress (gap not yet elapsed)
    bool damaged = false;    // driver overflow hit this packet
    uint32_t dropped = 0;    // bytes beyond kMaxIrPacket
    int64_t first_us = 0;
    int64_t last_us = 0;
    uint16_t len = 0;
    uint8_t buf[proto::kMaxIrPacket];
};
RxState s_rx;
bool s_cur_raw = false;
int64_t s_tx_wait_since = 0;  // when a TX started waiting behind an RX packet (0 = not waiting)

struct Stats {
    uint32_t frame_err = 0;
    uint32_t parity_err = 0;
    uint32_t overflow = 0;
    uint32_t out_dropped = 0;
} s_stats;

// --------------------------------------------------------------------------
// Output to the host task
// --------------------------------------------------------------------------

void post_out(uint8_t kind, uint8_t type, const uint8_t* a, size_t alen, const uint8_t* b = nullptr,
              size_t blen = 0) {
    uint8_t msg[2 + proto::kMaxFrame];
    size_t n = 0;
    msg[n++] = kind;
    if (kind == kOutFrame) {
        msg[n++] = type;
    }
    if (n + alen + blen > sizeof(msg)) {
        return;
    }
    if (alen) {
        memcpy(msg + n, a, alen);
        n += alen;
    }
    if (blen) {
        memcpy(msg + n, b, blen);
        n += blen;
    }
    if (xMessageBufferSend(s_out_mb, msg, n, 0) != n) {
        s_stats.out_dropped++;  // host is not draining; never block the IR task
        return;
    }
    xTaskNotifyGive(s_host_task);
}

void post_frame(uint8_t type, const uint8_t* a, size_t alen, const uint8_t* b = nullptr, size_t blen = 0) {
    if (!s_cur_raw) {
        post_out(kOutFrame, type, a, alen, b, blen);
    }
}

void post_error(uint8_t code, const char* text) {
    post_frame(proto::kError, &code, 1, reinterpret_cast<const uint8_t*>(text), strlen(text));
}

void post_log(const char* text) {
    post_frame(proto::kLog, reinterpret_cast<const uint8_t*>(text), strlen(text));
}

void put_u32le(uint8_t* p, uint32_t v) {
    p[0] = static_cast<uint8_t>(v);
    p[1] = static_cast<uint8_t>(v >> 8);
    p[2] = static_cast<uint8_t>(v >> 16);
    p[3] = static_cast<uint8_t>(v >> 24);
}

// --------------------------------------------------------------------------
// Pins and IrDA control
// --------------------------------------------------------------------------

void tx_pin_to_gpio_low() {
    gpio_set_level(static_cast<gpio_num_t>(IR_PIN_TX), 0);
    esp_rom_gpio_connect_out_signal(IR_PIN_TX, SIG_GPIO_OUT_IDX, false, false);
}

void tx_pin_to_uart() {
    esp_rom_gpio_connect_out_signal(IR_PIN_TX, UART_PERIPH_SIGNAL(IR_UART_NUM, SOC_UART_TX_PIN_IDX), false, false);
}

void post_event(int type) {
    uart_event_t e = {};
    e.type = static_cast<uart_event_type_t>(type);
    xQueueSend(s_evt_q, &e, 0);  // if full, the IR task's backstop timeout covers it
}

void gap_timer_cb(void*) { post_event(kEvtGap); }
void tx_pace_timer_cb(void*) { post_event(kEvtWake); }

void arm_gap_timer(int64_t delay_us) {
    if (delay_us < 50) {
        delay_us = 50;
    }
    // Fails harmlessly with ESP_ERR_INVALID_STATE if it is already armed.
    esp_timer_start_once(s_gap_timer, static_cast<uint64_t>(delay_us));
}

// Wait until esp_timer reaches `t`: sleep for the bulk, spin for the rest.
void wait_until_us(int64_t t) {
    for (;;) {
        const int64_t rem = t - esp_timer_get_time();
        if (rem <= 0) {
            return;
        }
        if (rem > 3000) {
            vTaskDelay(pdMS_TO_TICKS((rem - 1500) / 1000));
        } else {
            esp_rom_delay_us(static_cast<uint32_t>(rem));
        }
    }
}

bool uart_setup() {
    uart_config_t cfg = {};
    cfg.baud_rate = kBaud;
    cfg.data_bits = UART_DATA_8_BITS;
    cfg.parity = UART_PARITY_DISABLE;
    cfg.stop_bits = UART_STOP_BITS_1;
    cfg.flow_ctrl = UART_HW_FLOWCTRL_DISABLE;
    cfg.source_clk = UART_SCLK_DEFAULT;

    esp_err_t err;
    // Install from the IR task so the UART ISR is allocated on this core.
    if ((err = uart_driver_install(kPort, kRxRingSize, kTxRingSize, kEventQueueLen, &s_evt_q, 0)) != ESP_OK ||
        (err = uart_param_config(kPort, &cfg)) != ESP_OK ||
        (err = uart_set_mode(kPort, UART_MODE_IRDA)) != ESP_OK) {
        log_e("uart setup failed: %s", esp_err_to_name(err));
        return false;
    }

    uint32_t inv = 0;
    if (IR_TX_INVERT) inv |= UART_SIGNAL_IRDA_TX_INV;
    if (IR_RX_INVERT) inv |= UART_SIGNAL_IRDA_RX_INV;
    if (IR_RX_INVERT_PAD) inv |= UART_SIGNAL_RXD_INV;
    uart_set_line_inverse(kPort, inv);

    uart_set_rx_full_threshold(kPort, 1);
    uart_set_rx_timeout(kPort, IR_RX_TOUT_SYMBOLS);

    // RX only: TX is routed by hand in transmit() so it can idle as GPIO low.
    if ((err = uart_set_pin(kPort, UART_PIN_NO_CHANGE, IR_PIN_RX, UART_PIN_NO_CHANGE, UART_PIN_NO_CHANGE)) !=
        ESP_OK) {
        log_e("uart_set_pin failed: %s", esp_err_to_name(err));
        return false;
    }
    // Idle level of the (non-inverted) transceiver RXD is high; keep it there
    // while the transceiver is shut down and its RXD floats.
    const bool rx_idle_low = (IR_RX_INVERT != 0) != (IR_RX_INVERT_PAD != 0);
    gpio_set_pull_mode(static_cast<gpio_num_t>(IR_PIN_RX), rx_idle_low ? GPIO_PULLDOWN_ONLY : GPIO_PULLUP_ONLY);

    uart_dev_t* hw = UART_LL_GET_HW(IR_UART_NUM);
    hw->conf0.irda_tx_en = 0;
    hw->conf0.irda_dplx = IR_IRDA_DPLX ? 1 : 0;

    uart_flush_input(kPort);
    return true;
}

// --------------------------------------------------------------------------
// RX
// --------------------------------------------------------------------------

void rx_reset() {
    s_rx.active = false;
    s_rx.damaged = false;
    s_rx.dropped = 0;
    s_rx.len = 0;
    esp_timer_stop(s_gap_timer);
}

void rx_finish() {
    if (!s_rx.active) {
        return;
    }
    if (!s_cur_raw) {
        if (s_rx.damaged) {
            post_error(proto::kErrRxOverflow, "rx overflow, packet dropped");
        } else {
            uint8_t ts[4];
            put_u32le(ts, static_cast<uint32_t>(s_rx.first_us));
            post_frame(proto::kIrRx, ts, sizeof(ts), s_rx.buf, s_rx.len);
            if (s_rx.dropped) {
                char msg[48];
                snprintf(msg, sizeof(msg), "rx truncated, %u bytes dropped", static_cast<unsigned>(s_rx.dropped));
                post_error(proto::kErrRxOverflow, msg);
            }
        }
    }
    rx_reset();
}

void rx_drain_uart() {
    uint8_t tmp[128];
    for (;;) {
        const int n = uart_read_bytes(kPort, tmp, sizeof(tmp), 0);
        if (n <= 0) {
            return;
        }
        const int64_t now = esp_timer_get_time();
        s_activity_ms.store(millis(), std::memory_order_relaxed);

        if (!s_rx.active) {
            s_rx.active = true;
            s_rx.damaged = false;
            s_rx.dropped = 0;
            s_rx.len = 0;
            // All n bytes may have arrived in one go; the last one completed
            // about now, so back-date the first.
            s_rx.first_us = now - static_cast<int64_t>(n - 1) * kByteUs;
            arm_gap_timer(s_gap_us.load(std::memory_order_relaxed));
        }
        s_rx.last_us = now;

        if (s_cur_raw) {
            post_out(kOutRaw, 0, tmp, static_cast<size_t>(n));
            continue;
        }
        size_t room = proto::kMaxIrPacket - s_rx.len;
        size_t take = static_cast<size_t>(n) < room ? static_cast<size_t>(n) : room;
        memcpy(s_rx.buf + s_rx.len, tmp, take);
        s_rx.len = static_cast<uint16_t>(s_rx.len + take);
        s_rx.dropped += static_cast<uint32_t>(n) - static_cast<uint32_t>(take);
    }
}

void rx_check_gap(bool from_timer) {
    if (!s_rx.active) {
        return;
    }
    const int64_t gap = s_gap_us.load(std::memory_order_relaxed);
    const int64_t idle = esp_timer_get_time() - s_rx.last_us;
    if (idle >= gap) {
        rx_finish();
    } else if (from_timer) {
        arm_gap_timer(gap - idle);
    }
}

// --------------------------------------------------------------------------
// TX
// --------------------------------------------------------------------------

// In raw mode, append any further raw chunks the host has queued so a packet
// split across USB transfers still goes out back to back. Returns true if
// anything was written.
bool tx_top_up_raw(uint8_t* buf, size_t cap) {
    bool any = false;
    while (s_raw.load(std::memory_order_relaxed) && !xMessageBufferIsEmpty(s_tx_mb)) {
        const size_t n = xMessageBufferReceive(s_tx_mb, buf, cap, 0);
        if (n >= 1 && buf[0] == kTxFramed) {
            s_tx_framed_queued.fetch_sub(1);
        }
        if (n < 2 || buf[0] != kTxRaw) {
            continue;
        }
        uart_write_bytes(kPort, buf + 1, n - 1);
        any = true;
    }
    return any;
}

void transmit_one() {
    uint8_t buf[1 + proto::kMaxFrame];
    const size_t n = xMessageBufferReceive(s_tx_mb, buf, sizeof(buf), 0);
    if (n < 2) {
        return;
    }
    if (buf[0] == kTxFramed) {
        s_tx_framed_queued.fetch_sub(1);
    }
    const bool raw = (buf[0] == kTxRaw);
    if (raw != s_cur_raw) {
        return;  // queued before a mode switch; drop
    }

    uart_dev_t* hw = UART_LL_GET_HW(IR_UART_NUM);
    hw->conf0.irda_tx_en = 1;
    tx_pin_to_uart();
    uart_write_bytes(kPort, buf + 1, n - 1);

    esp_err_t done;
    if (raw) {
        // Keep feeding while the UART is busy; stop once it has drained and
        // nothing else is queued.
        for (;;) {
            done = uart_wait_tx_done(kPort, 1);
            const bool more = tx_top_up_raw(buf, sizeof(buf));
            if (done == ESP_OK && !more) {
                break;
            }
        }
    } else {
        // 256 bytes take ~22 ms at 115200.
        done = uart_wait_tx_done(kPort, pdMS_TO_TICKS(100));
    }
    const int64_t t_done = esp_timer_get_time();
    if (!raw) {
        s_last_tx_end_us = t_done;
    }

    tx_pin_to_gpio_low();
    hw->conf0.irda_tx_en = 0;
    s_activity_ms.store(millis(), std::memory_order_relaxed);

    // Echo stripping: drop whatever arrived during TX and the guard window.
    wait_until_us(t_done + s_echo_guard_us.load(std::memory_order_relaxed));
    uart_flush_input(kPort);
    rx_reset();

    if (!raw) {
        if (done != ESP_OK) {
            post_log("tx: uart_wait_tx_done timed out");
        }
        uint8_t ts[4];
        put_u32le(ts, static_cast<uint32_t>(t_done));
        post_frame(proto::kTxDone, ts, sizeof(ts));
    }
}

// --------------------------------------------------------------------------
// Task
// --------------------------------------------------------------------------

void handle_event(const uart_event_t& e) {
    switch (static_cast<int>(e.type)) {
        case UART_DATA:
            rx_drain_uart();
            break;
        case UART_FIFO_OVF:
        case UART_BUFFER_FULL:
            // The driver stops taking data until the buffer is flushed.
            s_stats.overflow++;
            uart_flush_input(kPort);
            if (s_rx.active) {
                s_rx.damaged = true;
                s_rx.last_us = esp_timer_get_time();
            } else if (!s_cur_raw) {
                post_error(proto::kErrRxOverflow, "rx overflow");
            }
            break;
        case UART_FRAME_ERR:
            s_stats.frame_err++;
            break;
        case UART_PARITY_ERR:
            s_stats.parity_err++;
            break;
        case kEvtGap:
            rx_check_gap(true);
            break;
        default:  // kEvtWake, UART_BREAK, ...
            break;
    }
}

void report_stats(int64_t now) {
    static int64_t last_report = 0;
    static Stats last = {};
    if (now - last_report < 2000000) {
        return;
    }
    last_report = now;
    if (s_stats.frame_err != last.frame_err || s_stats.overflow != last.overflow ||
        s_stats.out_dropped != last.out_dropped) {
        char msg[96];
        snprintf(msg, sizeof(msg), "ir stats: frame_err=%u overflow=%u host_drops=%u",
                 static_cast<unsigned>(s_stats.frame_err), static_cast<unsigned>(s_stats.overflow),
                 static_cast<unsigned>(s_stats.out_dropped));
        post_log(msg);
        log_i("%s", msg);
        last = s_stats;
    }
}

void ir_task(void*) {
    if (!uart_setup()) {
        post_log("ir: UART IrDA setup failed, IR disabled");
        vTaskDelete(nullptr);
        return;
    }
    log_i("IrDA UART%d ready: TX=%d RX=%d SD=%d", IR_UART_NUM, IR_PIN_TX, IR_PIN_RX, IR_PIN_SD);

    for (;;) {
        uart_event_t e;
        // Backstop timeout in case a private event was lost to a full queue.
        const TickType_t wait = pdMS_TO_TICKS(s_rx.active ? 2 : 20);
        if (xQueueReceive(s_evt_q, &e, wait) == pdTRUE) {
            handle_event(e);
        }

        const bool raw = s_raw.load(std::memory_order_acquire);
        if (raw != s_cur_raw) {
            rx_reset();
            uart_flush_input(kPort);
            s_cur_raw = raw;
        }

        rx_check_gap(false);

        // TX waits until the current RX packet has ended (gap elapsed) and
        // its IR_RX has been sent; see docs/protocol.md.
        if (!xMessageBufferIsEmpty(s_tx_mb)) {
            // Pick up bytes the ISR has buffered but whose event we have not
            // seen yet, so an incoming packet that just started defers the TX
            // instead of being flushed as "echo".
            rx_drain_uart();
            const int64_t now = esp_timer_get_time();
            if (s_rx.active) {
                if (s_tx_wait_since == 0) {
                    s_tx_wait_since = now;
                } else if (now - s_tx_wait_since >= IR_TX_DEFER_MAX_US) {
                    rx_finish();
                }
            }
            if (!s_rx.active) {
                s_tx_wait_since = 0;
                // Framed mode: keep gap_us of idle after our previous packet.
                const int64_t ready_at =
                    s_cur_raw ? 0 : s_last_tx_end_us + static_cast<int64_t>(s_gap_us.load(std::memory_order_relaxed));
                if (now < ready_at) {
                    esp_timer_start_once(s_tx_pace_timer, static_cast<uint64_t>(ready_at - now));
                } else {
                    transmit_one();
                    if (!xMessageBufferIsEmpty(s_tx_mb)) {
                        post_event(kEvtWake);  // more queued: come straight back
                    }
                }
            }
        } else {
            s_tx_wait_since = 0;
        }

        report_stats(esp_timer_get_time());
    }
}

}  // namespace

// --------------------------------------------------------------------------
// Public API
// --------------------------------------------------------------------------

void early_init() {
    gpio_config_t io = {};
    io.pin_bit_mask = 1ULL << IR_PIN_TX;
    io.mode = GPIO_MODE_OUTPUT;
    io.pull_down_en = GPIO_PULLDOWN_ENABLE;
    gpio_set_level(static_cast<gpio_num_t>(IR_PIN_TX), 0);
    gpio_config(&io);
    gpio_set_level(static_cast<gpio_num_t>(IR_PIN_TX), 0);

#if IR_PIN_SD >= 0
    io.pin_bit_mask = 1ULL << IR_PIN_SD;
    io.pull_down_en = GPIO_PULLDOWN_DISABLE;
    gpio_set_level(static_cast<gpio_num_t>(IR_PIN_SD), 0);  // SD low = transceiver on
    gpio_config(&io);
    gpio_set_level(static_cast<gpio_num_t>(IR_PIN_SD), 0);
#endif
}

bool begin(MessageBufferHandle_t to_host, TaskHandle_t host_task) {
    s_out_mb = to_host;
    s_host_task = host_task;
    s_tx_mb = xMessageBufferCreate(kTxMbSize);
    if (!s_tx_mb) {
        return false;
    }
    esp_timer_create_args_t targs = {};
    targs.callback = gap_timer_cb;
    targs.dispatch_method = ESP_TIMER_TASK;
    targs.name = "ir_gap";
    if (esp_timer_create(&targs, &s_gap_timer) != ESP_OK) {
        return false;
    }
    targs.callback = tx_pace_timer_cb;
    targs.name = "ir_tx_pace";
    if (esp_timer_create(&targs, &s_tx_pace_timer) != ESP_OK) {
        return false;
    }
    // s_evt_q is created by uart_driver_install inside the task; submit_tx()
    // checks for it before posting wake-ups.
    return xTaskCreatePinnedToCore(ir_task, "ir", 6144, nullptr, IR_TASK_PRIORITY, nullptr, IR_TASK_CORE) == pdPASS;
}

bool submit_tx(uint8_t kind, const uint8_t* data, size_t len) {
    if (!s_tx_mb || len == 0 || len > proto::kMaxFrame) {
        return false;
    }
    if (kind == kTxFramed && s_tx_framed_queued.load() >= kTxFifoDepth) {
        return false;
    }
    uint8_t msg[1 + proto::kMaxFrame];
    msg[0] = kind;
    memcpy(msg + 1, data, len);
    if (kind == kTxFramed) {
        s_tx_framed_queued.fetch_add(1);  // before the send, so the IR task never sees it negative
    }
    if (xMessageBufferSend(s_tx_mb, msg, len + 1, 0) != len + 1) {
        if (kind == kTxFramed) {
            s_tx_framed_queued.fetch_sub(1);
        }
        return false;
    }
    if (s_evt_q) {
        post_event(kEvtWake);
    }
    return true;
}

size_t tx_space() {
    if (!s_tx_mb) {
        return 0;
    }
    // Each message costs its length plus a size_t header in the buffer.
    const size_t free_bytes = xMessageBufferSpacesAvailable(s_tx_mb);
    const size_t overhead = sizeof(size_t) + 1;
    return free_bytes > overhead ? free_bytes - overhead : 0;
}

void set_gap_us(uint16_t us) { s_gap_us.store(us, std::memory_order_relaxed); }
void set_echo_guard_us(uint16_t us) { s_echo_guard_us.store(us, std::memory_order_relaxed); }

void set_transceiver_enabled(bool on) {
#if IR_PIN_SD >= 0
    gpio_set_level(static_cast<gpio_num_t>(IR_PIN_SD), on ? 0 : 1);
#else
    (void)on;
#endif
}

void set_raw_mode(bool raw) {
    s_raw.store(raw, std::memory_order_release);
    if (s_evt_q) {
        post_event(kEvtWake);
    }
}

bool raw_mode() { return s_raw.load(std::memory_order_acquire); }

void reset_config() {
    set_gap_us(proto::kDefaultGapUs);
    set_echo_guard_us(proto::kDefaultEchoGuardUs);
    set_transceiver_enabled(true);
}

uint32_t last_activity_ms() { return s_activity_ms.load(std::memory_order_relaxed); }

}  // namespace ir
