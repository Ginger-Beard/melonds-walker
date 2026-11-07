# melonDS-walker dongle firmware (ESP32-S3)

USB CDC to IrDA SIR bridge. It lets an emulated HeartGold/SoulSilver talk to a real Pokéwalker. The host protocol (COBS-framed mode and raw mode) is specified in [`../docs/protocol.md`](../docs/protocol.md).

- Framework: Arduino-ESP32 3.3.5 (ESP-IDF 5.5) via the pioarduino PlatformIO platform `55.03.35`.
- USB: native USB in TinyUSB mode (`ARDUINO_USB_MODE=0`, no CDC console on boot). The device enumerates as `303a:4001` with manufacturer "melonDS-walker" and product "melonDS-walker IR dongle".
- IR: UART1 in hardware IrDA mode (`UART_MODE_IRDA`) at 115200 8N1, driving a Vishay TFBS4711 (or TFDU4101).

## Build and flash

```sh
cd firmware
pio run                                   # default env: esp32-s3-devkitc-1
pio run -e seeed_xiao_esp32s3
pio run -e esp32-s3-devkitc-1 -t upload   # add --upload-port /dev/ttyACMx if needed
pio test -e native                        # COBS unit tests on the host (needs gcc)
```

If `~/.local/bin/pio` fails with `ModuleNotFoundError: No module named 'requirements'`, a different PyPI package called `pio` is shadowing PlatformIO. Use `~/.platformio/penv/bin/pio` or `platformio` instead.

**Upload and the bootloader.** Because the firmware owns the USB port (TinyUSB), esptool cannot reach the ROM directly. The Arduino core watches the CDC port and reboots into the ROM bootloader on esptool's DTR/RTS reset sequence or on a 1200-baud "touch". `platformio.ini` enables the 1200-baud touch and `wait_for_upload_port`, because the ROM bootloader re-enumerates as a different device (`303a:1001`, USB-Serial-JTAG), often on a new `/dev/ttyACM*`.

If that fails (first flash, or a crashed firmware), **hold BOOT (GPIO0), tap RESET, release BOOT**, then upload. The board then sits in the ROM bootloader. Press RESET once more after flashing if it does not start on its own. On the DevKitC-1 you can also flash through the "UART" USB port (CP210x/CH343 bridge), which uses the classic auto-reset circuit.

Side effect: opening the dongle's port at **1200 baud** reboots it into the bootloader. Hosts should use any other baud rate. The CDC baud rate is otherwise ignored.

## Wiring

| Signal | ESP32-S3 GPIO | DevKitC-1 | XIAO ESP32S3 | TFBS4711 pin |
|--------|---------------|-----------|--------------|--------------|
| IR TXD (out, active high) | GPIO1 | J1 "1" | D0 | TXD |
| IR RXD (in, active-low pulses) | GPIO2 | J1 "2" | D1 | RXD |
| IR SD (out, high = shutdown) | GPIO4 | J1 "4" | D3 | SD |
| 3V3 | | 3V3 | 3V3 | VCC1 (and VCC2/IRED anode through its resistor) |
| GND | | GND | GND | GND |

These pins avoid the S3 strapping pins (GPIO0, 3, 45, 46) and USB (GPIO19/20). Put an external pull-down (for example 100 kΩ) on TXD so the LED stays dark while the ESP32 is in reset or in the bootloader, as on the FlippIR board. The firmware drives TXD low as its first action and keeps it as a plain GPIO low whenever it is not transmitting. If SD is hard-wired to GND, build with `-DIR_PIN_SD=-1`. See `docs/hardware.md` for the full circuit.

## Build flags

Add these to `build_flags` in `platformio.ini`, or pass them for a single build: `PLATFORMIO_BUILD_FLAGS="-DIR_RX_INVERT=1" pio run -t upload`. Defaults live in `src/config.h`.

| Flag | Default | Meaning |
|------|---------|---------|
| `IR_PIN_TX` / `IR_PIN_RX` / `IR_PIN_SD` | 1 / 2 / 4 | GPIOs. `IR_PIN_SD=-1` means SD is not wired. |
| `IR_UART_NUM` | 1 | UART used for IrDA. |
| `IR_TX_INVERT` | 0 | Invert IrDA TX output (`UART_SIGNAL_IRDA_TX_INV`). |
| `IR_RX_INVERT` | 0 | Invert IrDA RX decoder input (`UART_SIGNAL_IRDA_RX_INV`). |
| `IR_RX_INVERT_PAD` | 0 | Invert the RXD pad instead (`UART_SIGNAL_RXD_INV`). |
| `IR_IRDA_DPLX` | 0 | Set the UART's IrDA duplex/loopback bit. |
| `IR_RX_TOUT_SYMBOLS` | 2 | UART RX timeout in symbol times. |
| `IR_TX_DEFER_MAX_US` | 50000 | Longest an `IR_TX` waits behind a never-ending RX packet. |
| `STATUS_LED_PIN` | DevKitC: 48 (RGB), XIAO: 21 | Status LED GPIO, `-1` = none. |
| `STATUS_LED_RGB` / `STATUS_LED_ACTIVE_LOW` | per board | LED type. |
| `CORE_DEBUG_LEVEL` | 0 | Arduino log level for the UART0 debug log (4 = debug). |

## If nothing is received: polarity

The polarity defaults are **educated guesses** that still need a hardware test. The ESP32's IrDA encoder is assumed to follow the usual SIR ENDEC convention (STM32 does the same, and Flipwalker drives a TFBS4711 from an STM32 with no inverters): TX idles low with short high pulses (matching the TFBS4711's active-high TXD), and RX idles high with low pulses (matching its active-low RXD). Espressif does not document the idle levels.

Try these in order, one at a time, with a walker beaconing (0xFC every few hundred ms, `0x56` on the wire):

1. `-DIR_RX_INVERT=1`. A periodic `LOG "ir stats: frame_err=..."` that keeps climbing usually means the RX polarity is wrong.
2. `-DIR_RX_INVERT_PAD=1` (with `IR_RX_INVERT=0`).
3. `-DIR_IRDA_DPLX=1`. This is the old esp32.com fix for "IrDA RX dead". The firmware already clears `irda_tx_en` while receiving, which should make it unnecessary.
4. If the walker never answers our packets, check TX with a scope or a phone camera (most phone cameras see 870 nm). You should see ~1.6 µs pulses on TXD during a transmission and a flat low line otherwise. Only use `-DIR_TX_INVERT=1` if the pulses really are inverted. With a TFBS4711, an inverted TX holds the LED on between pulses and trips its 100 µs TXD watchdog (the TFDU4101's is 50 µs).

`walkerctl.py` (in `tools/`) can sniff and print the `IR_RX` frames and `LOG` lines.

## Status LED and logs

- **DevKitC-1:** addressable RGB LED on GPIO48 (board v1.0). Board v1.1 moved it to GPIO38, so build with `-DSTATUS_LED_PIN=38` there. Dim green = USB mounted, framed mode. Dim magenta = raw mode. White flash = IR byte received or packet sent. Off = USB not mounted.
- **XIAO ESP32S3:** orange user LED (GPIO21) flashes on IR activity.
- **Debug log:** Arduino `log_x()` output goes to UART0 (GPIO43 TX, 115200 baud), which is the DevKitC-1's "UART" USB port. It is off by default. Enable it with `-DCORE_DEBUG_LEVEL=4`. The dongle also sends `LOG` frames over USB in framed mode, for example IR error counters every 2 s when they change.

## Architecture

```
            host task (prio 10)                        IR task (prio 20, core 1)
USB CDC <-> COBS decode/dispatch -- tx msgbuf (8 pkts) --> pacing -> UART1 IrDA TX burst
        <-> 8 KiB output ring    <-- out msgbuf (8 KiB) -- gap timer <- UART1 RX ISR (thresh 1)
```

- `src/ir_uart.*`: the IrDA UART. It sets the RX FIFO threshold to 1, timestamps bytes with `esp_timer`, ends a packet after `gap_us` idle (esp_timer one-shot), and strips echo (RX discarded during TX and for `echo_guard_us` afterwards, then `uart_flush_input`). TX goes straight into the 128-byte hardware FIFO (no driver TX ring), so a packet leaves as one gap-free burst. It also keeps `gap_us` idle between packets and holds a TX until an in-progress RX packet has been delivered.
- `src/host_link.*`: USB descriptor and TinyUSB CDC, COBS framing, commands, raw mode, LED. Writes never block. Frames go into a ring that is drained into TinyUSB as space appears. A frame that does not fit is dropped whole.
- `lib/cobs`: the COBS codec, shared with the native unit tests.
- Raw mode is left only on USB unmount or re-enumeration (or reset), not on DTR drop or suspend. See `docs/protocol.md`.

## Hardware-test checklist (unverified assumptions)

- RX/TX polarity defaults (see above).
- That toggling `conf0.irda_tx_en` around each transmission is right for the S3. The IDF driver never sets this bit.
- Echo timing: the 50 µs guard plus ~10–20 µs of TX-done wake-up latency must stay under the walker's ~150 µs reply delay.
- Behaviour of the reset-to-bootloader path on your particular board.
