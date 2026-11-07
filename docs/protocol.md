# Host ⇄ dongle protocol (v1)

The dongle is a USB CDC-ACM serial device. It knows nothing about Pokéwalker packet contents: it carries IR packets as opaque bytes. The XOR-0xAA encoding, checksums and session IDs are the game's (or the host tool's) job.

The dongle has two modes:

- **Framed mode** is the default at boot and after every USB reconnect (unmount or re-enumeration). Each IR packet is delimited by line idle and carried in its own frame. melonDS and `tools/walkerctl.py` use this mode.
- **Raw mode** is a transparent byte pipe for existing tools such as DaveuRrr/melonDS-IR's serial transport. You enter it with the `RAW_MODE` command. Host bytes are transmitted as they arrive (back to back when the host keeps up), received bytes are forwarded immediately, and echo stripping still applies; the TX queue depth and inter-packet pacing below are framed-mode only. You leave it by unplugging the dongle, by a USB re-enumeration (bus reset followed by a new mount, or an unmount), or by resetting it. Closing the port or dropping DTR does **not** leave raw mode, because the tool that sends `RAW_MODE` (for example `walkerctl.py raw`) exits before the raw-mode consumer opens the port. USB **suspend does not** leave raw mode either: a host may autosuspend the idle device in exactly that window between the two tools, and a resume does not re-enumerate.

`SET_CONFIG` values persist across port open/close and are reset to their defaults together with the mode (USB re-enumeration or dongle reset).

## IR line parameters

- IrDA SIR, 115200 baud, 8N1, half-duplex.
- **End of packet:** the dongle treats `gap_us` of line idle as the end of an IR packet. The default is 1000 µs (minimum 200), and you can change it with `SET_CONFIG`. The walker sends one packet per request, so 1 ms is well above inter-byte jitter and well below any protocol timeout. A walker beacon is a single bare byte (`0xFC`, `0x56` on the wire) and arrives as a 1-byte `IR_RX`.
- **Echo stripping:** the transceiver echoes its own transmissions back on RXD. The dongle discards received bytes while it is transmitting and for `echo_guard_us` after the last bit has left. The default is 50 µs. Keep it well under 150 µs: the walker starts its reply about 150 µs after our packet ends, and a longer guard would eat the first reply byte.
- **TX bursts:** each `IR_TX` packet goes out as one continuous burst with no inter-byte gaps (the walker ends a packet after about 122 µs of idle).
- **TX queue and pacing:** `IR_TX` packets queue in a FIFO of 8 packets. If the queue is full the dongle replies `ERROR 0x06` and drops that packet. Between the end of one transmitted packet and the start of the next, the dongle leaves at least `gap_us` of line idle, so the receiver sees separate packets. Hosts do not need their own sleeps between packets (for example before the disconnect packet).
- **RX in progress:** if an `IR_TX` arrives while an IR packet is still being received (its `gap_us` has not yet elapsed), the dongle holds the TX until the gap has elapsed, sends that packet's `IR_RX` first, then transmits. As a safety valve, if the line never goes idle (noise) for 50 ms, the dongle ends the RX packet early and transmits anyway.
- **Maximum IR packet:** 256 bytes. Real packets are at most 8 + 128 = 136 bytes. Longer input is truncated and reported with an `ERROR`.

## Framing (framed mode)

Every frame is COBS-encoded and terminated by a single `0x00` byte.

Decoded frame contents:

```
+--------+-------------------+
| type   | payload (0..N)    |
| 1 byte | depends on type   |
+--------+-------------------+
```

The decoded frame size limit is 300 bytes. An empty frame (two `0x00` bytes in a row) is ignored, so a host may send a lone `0x00` to resynchronise. USB is reliable, so frames carry no CRC. All multi-byte integers are little-endian. Timestamps are the dongle's microsecond clock (`esp_timer_get_time()`), truncated to `u32`.

### Host → dongle

| Type | Name | Payload | Reply |
|------|------|---------|-------|
| `0x01` | `IR_TX` | IR packet bytes exactly as they go on the wire, already XOR'd | `TX_DONE` |
| `0x02` | `IDENTIFY` | none | `IDENTIFY_RESP` |
| `0x03` | `SET_CONFIG` | `key u8`, `value` (see below) | `CONFIG_ACK` |
| `0x04` | `RAW_MODE` | none | `CONFIG_ACK`, then raw mode |
| `0x05` | `PING` | 0–32 arbitrary bytes | `PONG` echoing the payload |

`SET_CONFIG` keys:

| Key | Name | Value | Default |
|-----|------|-------|---------|
| `0x01` | `gap_us` | `u16`, at least 200 | 1000 |
| `0x02` | `echo_guard_us` | `u16` | 50 |
| `0x03` | `transceiver_enable` | `u8` (0 or 1); drives the TFBS4711 SD pin, where SD high = shutdown | 1 |

### Dongle → host

| Type | Name | Payload |
|------|------|---------|
| `0x81` | `IR_RX` | `ts_us u32` (time of the packet's first byte), then the IR packet bytes as received, still XOR'd |
| `0x82` | `IDENTIFY_RESP` | magic `"MDSW"` (4 bytes), `proto_version u8` (=1), `caps u8`, `fw_version` (ASCII, rest of frame) |
| `0x83` | `CONFIG_ACK` | `key u8` (`0xFF` for `RAW_MODE`), `status u8` (0 = ok) |
| `0x84` | `TX_DONE` | `ts_us u32` (when the last bit left the UART) |
| `0x85` | `PONG` | echoed `PING` payload |
| `0x8E` | `LOG` | ASCII text (debug or info) |
| `0x8F` | `ERROR` | `code u8`, then optional ASCII text |

`CONFIG_ACK` status: 0 = ok, 1 = wrong value length for this key, 2 = value out of range. An unknown key gets `ERROR 0x05` instead.

An empty `IR_TX` or a `PING` longer than 32 bytes gets `ERROR 0x01`.

`caps` bits: bit0 = framed mode, bit1 = raw mode, bit2 = Wi-Fi transport present. Bits 0 and 1 are set in v1.

`ERROR` codes:

| Code | Meaning |
|------|---------|
| `0x01` | malformed frame |
| `0x02` | unknown type |
| `0x03` | IR RX overflow or truncation |
| `0x04` | IR TX too long |
| `0x05` | bad config key |
| `0x06` | IR TX queue full (packet dropped) |

## Identification

A host should send `IDENTIFY` after opening the port and check for the magic `"MDSW"`. A board that shares a USB VID:PID with something else (for example, a stock ESP32-S3 descriptor) is then never mistaken for the dongle.

## USB descriptor

- Manufacturer string: `melonDS-walker`.
- Product string: `melonDS-walker IR dongle`.
- VID:PID is `0x303A:0x4001` for now, which is Espressif's VID with a TinyUSB-style PID.
- TODO: request a dedicated PID through https://github.com/espressif/usb-pids so Android `device_filter.xml` can match it exactly.
