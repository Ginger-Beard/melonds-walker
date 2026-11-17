# Hardware build guide

A DIY dongle: an ESP32-S3 board with native USB, wired to a Vishay TFBS4711 IrDA SIR transceiver. The firmware does the SIR encoding and timing and presents a USB CDC serial port (see [protocol.md](protocol.md)). Flashing instructions are in [../firmware/README.md](../firmware/README.md).

Status: built, tested and in regular use with the XIAO hat v0.1 and a TFBS4711 (first test 2026-11-12, in use with the game as of 2026-11-17). The TFDU4101 alternate is untested. Circuit values below are from the Vishay TFBS4711 datasheet ([82633 rev. 3.9](https://www.vishay.com/docs/82633/tfbs4711.pdf)).

## Recommended build: the XIAO IrDA hat

Use the hat in [`hardware/xiao-irda-hat/`](../hardware/xiao-irda-hat/README.md). It is a small 2-layer board that sits under a Seeed XIAO ESP32S3 on two 1x7 headers and carries the TFBS4711 with its decoupling, supply filter and pull-downs. The transceiver looks out of the end opposite the XIAO's USB-C, so with the dongle plugged into a handheld you aim the walker at the far end.

- JLCPCB assembles all the SMD parts, including the fine-pitch side-view transceiver. The README has the step-by-step order (Economic PCBA, top side, quantity 5) and the U1 rotation check.
- You solder only the two headers.
- It uses the firmware's default pins (D0 = GPIO1 TXD, D1 = GPIO2 RXD, D3 = GPIO4 SD), so build with `pio run -e seeed_xiao_esp32s3` and no flags.
- Gerbers, BOM and CPL are committed in `hardware/xiao-irda-hat/fab/`.

The rest of this page is the **alternative**: wiring the transceiver to an ESP32-S3 board by hand (jumper wires to a breakout or adapter). The circuit is the same as on the hat.

## Why a real IrDA SIR transceiver

The Pokewalker link is IrDA SIR, 115200 baud 8N1, unmodulated short pulses. A 38 kHz TSOP-style receiver or a phone IR blaster cannot work. See [research/notes/ir_hardware_and_protocol.md](research/notes/ir_hardware_and_protocol.md) section 1.

## BOM

| Part | Notes |
|------|-------|
| ESP32-S3 board with native USB | Espressif ESP32-S3-DevKitC-1 (use the port labelled USB, not UART) or Seeed XIAO ESP32S3 (21 x 17.5 mm, good for a compact dongle). |
| Vishay TFBS4711 | Primary choice. Used by Flipwalker/FlippIR with real HGSS. 6 pads at 0.95 mm pitch, 6 x 3 x 1.9 mm, 2.4-5.5 V, 70 uA idle, <1 uA shutdown. TXD protection turns the LED off if TXD stays high > 100 us. Order TFBS4711-TR1 or -TR3 (side-view taping; -TT1 is top-view). |
| Vishay TFDU4101 (alternate) | 8-pin SMD, 4 x 9.7 x 4.7 mm, 2.4-5.5 V, 0.07 mA idle, <1 uA shutdown. TXD is a Schmitt input; an on-chip protection disables the LED driver if TXD is high longer than 50 us (max 300 us). RXD is active-low push-pull, echoes during TX. [Datasheet](https://www.vishay.com/docs/81288/tfdu4101.pdf) |
| TXD pull-down resistor | Required, keeps the LED dark at boot. 10 kOhm on the hat (FlippIR uses 100 kOhm; 10 k guarantees a logic low against the datasheet's 10 uA worst-case input leakage). |
| SD pull-down (if SD is wired to a GPIO) | 10 kOhm to GND, so the transceiver is enabled until the firmware drives SD. |
| VCC1 decoupling | 100 nF ceramic right at pin 5 (datasheet C2). |
| VCC1 supply filter | 47 Ohm in series from 3V3 to pin 5 (datasheet R2); with the 100 nF it forms the recommended low-pass. |
| LED supply bulk capacitor | 4.7 uF or more (the hat uses 10 uF X5R for DC-bias margin) ceramic at pin 1, VCC2 / IRED anode (datasheet C1). |
| Series resistor on IRED | Not needed: datasheet R1 only reduces LED intensity. The TFBS4711 regulates its own IRED current (200-430 mA). Tie pin 1 straight to 3V3. |
| Breakout / adapter board | See below. |
| USB-C cable, hookup wire | |

Sources: [TFBS4711 datasheet](https://www.vishay.com/docs/82633/tfbs4711.pdf) (Fig. 1 / Table 1 recommended circuit, pin table), [FlippIR-Hardware](https://github.com/Jackv-makes/FlippIR-Hardware) (TFBS4711-TR1, same circuit: 47 Ohm + 100 nF on VCC1, 4.7 uF on the IRED supply, TX pull-down), [Flipwalker](https://github.com/Jackv-makes/Flipwalker), [TFDU4101 datasheet](https://www.vishay.com/docs/81288/tfdu4101.pdf). The accelerometer, MBR0520 Schottky and header on the FlippIR board are Flipper-specific and not needed.

## Package warning and breakouts

The TFBS4711 is a tiny fine-pitch SMD part; the TFDU4101 is also SMD and awkward by hand. Do not plan to hand-wire either on a perfboard without an adapter. Options:

- The XIAO IrDA hat above (factory-assembled, recommended).

- A breakout or adapter PCB for the part. The FlippIR board is an open design (PCBs on PCBWay) with the transceiver circuit already laid out; it can be used as a template for your own board.
- MikroE IrDA 4 Click, a ready-made IrDA transceiver board (the notes list it as an alternative; check which transceiver and level it uses before relying on it).
- Hot-air or reflow if you build your own carrier.

## Wiring

Default pins (configurable in firmware):

| ESP32-S3 | TFBS4711 | Notes |
|----------|----------|-------|
| GPIO1 (TX) | 2 TXD | **Pull-down on TXD is required** so the LED stays off at boot and while the GPIO floats. |
| GPIO2 (RX) | 3 RXD | Active-low push-pull output; no pull-up needed. |
| GPIO4 | 4 SD | Shutdown, active high (high = shutdown). Firmware drives it via `transceiver_enable`. Tie to GND instead if you skip firmware control (Flipwalker does this). |
| 3V3 | 1 VCC2 (IRED anode) | Straight to 3V3, 4.7 to 10 uF to GND at the pin. |
| 3V3 | 5 VCC1 | Through 47 Ohm, 100 nF to GND at the pin. |
| GND | 6 GND | |

```
        ESP32-S3                         TFBS4711
     +-------------+                  +-------------+
     |       GPIO1 |--------+---------| TXD         |
     |             |        |         |             |
     |             |       [Rpd]      |             |
     |             |        |         |             |
     |       GPIO2 |--------|---------| RXD         |
     |       GPIO4 |--------|---------| SD          |
     |             |        |         |      (LED)  |))) IR
     |         3V3 |--+-----|----+----| VCC / IRED  |
     |             | ===    |   ===   |             |
     |             | C1,C2  |   Cbulk |             |
     |         GND |--+-----+----+----| GND         |
     +-------------+                  +-------------+
          | USB-C (native USB) to host

     Rpd = TXD pull-down to GND (required)
     C1,C2 = 100 nF at VCC1 (pin 5), fed through 47 Ohm from 3V3
     Cbulk = 4.7-10 uF at VCC2 / IRED anode (pin 1)
     TFBS4711 pins: 1 VCC2/IRED anode, 2 TXD, 3 RXD, 4 SD, 5 VCC1, 6 GND
```

The diagram is schematic, not a pinout; the pin list above is the TFBS4711's. For the TFDU4101, take pin numbers from its datasheet.

## Aiming and range

- Point the transceiver window at the walker's IR window, a few cm apart, aligned face to face. Good alignment matters more than distance.
- GBATEK reports full Activity Meter dumps working at about 5-10 cm. FlippIR reports a few cm against a weak LED. No measured Pokewalker figure exists; this is part of what the bench test establishes.
- Keep strong light sources (sun, incandescent) away from the receiver while testing.
- Use `walkerctl.py sniff` with the walker on its Connect screen; you should see a repeating 0xFC beacon, which is raw byte `56` after XOR. Adjust aim until it appears reliably.

## Bring-up checklist

1. Check wiring, especially that the TXD pull-down is present.
2. Flash the firmware ([../firmware/README.md](../firmware/README.md)).
3. `python3 tools/walkerctl.py identify`, then `ping`.
4. `sniff` against a walker, then `handshake`. See the test plan in [research/report.md](research/report.md).
