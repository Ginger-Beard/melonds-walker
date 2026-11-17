// Build-time configuration. Every macro here can be overridden with
// `-D<NAME>=<value>` in platformio.ini (build_flags) or PLATFORMIO_BUILD_FLAGS.
#pragma once

#define FW_VERSION_STRING "0.1.0"

// ---------------------------------------------------------------------------
// IR transceiver wiring (Vishay TFBS4711 / TFDU4101 class)
//
// Defaults are valid on both supported boards and avoid the S3 strapping pins
// (GPIO0, 3, 45, 46) and the USB pins (GPIO19/20):
//   GPIO1 = DevKitC-1 header J1 pin "1",  XIAO D0
//   GPIO2 = DevKitC-1 header J1 pin "2",  XIAO D1
//   GPIO4 = DevKitC-1 header J1 pin "4",  XIAO D3
// ---------------------------------------------------------------------------
#ifndef IR_UART_NUM
#define IR_UART_NUM 1  // UART0 carries the ROM/IDF log; UART1 is free
#endif
#ifndef IR_PIN_TX
#define IR_PIN_TX 1  // -> transceiver TXD (active high: LED on)
#endif
#ifndef IR_PIN_RX
#define IR_PIN_RX 2  // <- transceiver RXD (active low pulses)
#endif
#ifndef IR_PIN_SD
#define IR_PIN_SD 4  // -> transceiver SD (high = shutdown). -1 = not wired (SD tied to GND)
#endif

// ---------------------------------------------------------------------------
// Polarity. The defaults (no inversion anywhere) are confirmed on hardware with
// a TFBS4711 on the XIAO hat (2026-11-12); other transceivers are untested.
//
// The ESP32 IrDA encoder follows the usual SIR ENDEC convention (the same one
// the STM32 USART uses, and Flipwalker drives a TFBS4711 from an STM32 with no
// inverters): TX output idles low and emits a short HIGH pulse for each 0 bit,
// which is exactly what the transceiver's active-high TXD wants. The decoder
// expects an idle-high input with LOW pulses, which matches the transceiver's
// active-low RXD. So the natural default is "no inversion" on both sides.
// Neither the ESP-IDF docs nor the S3 TRM spell out the idle levels, so if
// nothing is received, try IR_RX_INVERT=1 first, then IR_RX_INVERT_PAD=1.
// Only set IR_TX_INVERT=1 if a scope shows idle-high / low-pulse output: with
// a TFBS4711 an inverted TX holds the LED on between pulses and trips its
// 100 us TXD watchdog (the TFDU4101's is 50 us).
// ---------------------------------------------------------------------------
#ifndef IR_TX_INVERT
#define IR_TX_INVERT 0  // UART_SIGNAL_IRDA_TX_INV
#endif
#ifndef IR_RX_INVERT
#define IR_RX_INVERT 0  // UART_SIGNAL_IRDA_RX_INV
#endif
#ifndef IR_RX_INVERT_PAD
#define IR_RX_INVERT_PAD 0  // UART_SIGNAL_RXD_INV (alternative to IR_RX_INVERT)
#endif

// conf0.irda_dplx. The S3 register header calls it "IrDA loopback mode"; an
// old esp32.com thread reported classic-ESP32 IrDA RX only worked with it set.
// We clear conf0.irda_tx_en while receiving instead (see ir_uart.cpp), which
// should make this unnecessary. Guess: 0. Try 1 if RX stays dead.
#ifndef IR_IRDA_DPLX
#define IR_IRDA_DPLX 0
#endif

// RX FIFO timeout in UART symbol times (driver default is 10). With the FIFO
// full threshold at 1 this rarely matters, so keep it small.
#ifndef IR_RX_TOUT_SYMBOLS
#define IR_RX_TOUT_SYMBOLS 2
#endif

// If an IR_TX has waited this long behind a still-active incoming packet
// (line never goes idle, e.g. noise), end that packet early and transmit.
#ifndef IR_TX_DEFER_MAX_US
#define IR_TX_DEFER_MAX_US 50000
#endif

// ---------------------------------------------------------------------------
// Status LED (optional). STATUS_LED_PIN < 0 disables it.
// STATUS_LED_RGB=1 drives a WS2812-style LED via rgbLedWrite().
// ---------------------------------------------------------------------------
#ifndef STATUS_LED_PIN
#define STATUS_LED_PIN -1
#endif
#ifndef STATUS_LED_RGB
#define STATUS_LED_RGB 0
#endif
#ifndef STATUS_LED_ACTIVE_LOW
#define STATUS_LED_ACTIVE_LOW 0
#endif

// ---------------------------------------------------------------------------
// Tasks
// ---------------------------------------------------------------------------
#ifndef IR_TASK_PRIORITY
#define IR_TASK_PRIORITY 20  // above everything except esp_timer (22) and IPC
#endif
#ifndef IR_TASK_CORE
#define IR_TASK_CORE 1  // keep away from Wi-Fi/BT and the TinyUSB task on core 0
#endif
#ifndef HOST_TASK_PRIORITY
#define HOST_TASK_PRIORITY 10
#endif
