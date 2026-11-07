# melonds-walker: a real Pokéwalker with HeartGold/SoulSilver on an emulator

**Goal:** play HG/SS in melonDS on an Android handheld (e.g. an AYN Thor), plug in a small USB-C dongle, and do Pokéwalker transfers with a real Pokéwalker. No modified carts, no rooting.

## How the original works

- The Pokéwalker talks over **infrared**: IrDA SIR, the old laptop/PDA IR standard, at 115200 baud. It is plain serial data sent as light pulses. It isn't radio and it isn't TV-remote IR.
- **The IR hardware is in the game cartridge, not the DS.** The HG/SS cart has its own IR chip on the same bus as the save chip. The game sends it a handful of commands: "send this packet", "give me what you received". That's why it works on a 3DS too.

## How this project works

```
Pokéwalker  ))) IR )))  dongle  ── USB-C ──  Android handheld
                     (ESP32-S3 + IR chip)    (melonDS emulates the cart's IR chip)
```

1. **melonDS pretends to be the cart's IR chip.** When the game says "send this packet", melonDS passes it to the dongle. When the game asks "anything received?", melonDS hands back what the dongle heard.
2. **The dongle is a dumb pipe.** An ESP32-S3 (about $7) plus a Vishay TFBS4711 IrDA transceiver (about $4.50) moves bytes between USB and infrared. It doesn't understand the Pokéwalker protocol. The game and the walker handle that themselves, exactly as they would with a real cart.
3. **Plug and play:** Android asks once whether melonDS can use the USB device. After that there's one setting in melonDS (IR: off / USB dongle).

## Why it's feasible: every piece has been done before, separately

| Piece | Already proven by |
|---|---|
| The IR protocol, fully reverse-engineered | Dmitry Grinberg's write-up, GBATEK docs, and full decompilations of both the Pokéwalker firmware (lumirth/pw) and the game (pret/pokeheartgold) |
| A TFBS4711 on a microcontroller talking to real HG/SS, both directions | Flipwalker (Flipper Zero + TFBS4711) |
| An ESP32-S3 doing Pokéwalker IR | Stickwalker (M5Stack Stick S3) |
| melonDS emulating the cart's IR chip on Android, on the AYN Thor | WatermelonDS fork (built-in virtual walker plus a network mode); the core change is about 70 lines |
| ESP32-S3 hardware IrDA support | Confirmed in Espressif's register headers |
| Android talking to USB serial devices without root | usb-serial-for-android library; Dolphin's Android GameCube adapter uses the same pattern |

**Timing works out.** The game checks for IR data every 4 ms and gives up after 100 ms of silence. USB adds about 1–2 ms each way, and a full packet takes about 12 ms over IR. Estimated round trip is under 40 ms. One catch: emulator fast-forward shrinks the game's deadline, so melonDS has to lock to 1× speed during transfers.

**What's actually new:** nobody has published a *real* Pokéwalker linked live to melonDS. That is the gap this fills, by gluing proven parts together.

## Status

- **Done:** dongle firmware (builds for ESP32-S3 DevKitC-1 and Seeed XIAO ESP32S3), the USB protocol, and a PC bench tool. The bench tool does a handshake with a real walker and reads its trainer name and step count. It is hard-limited to safe, read-only commands, because some walker commands can wipe the device.
- **Waiting on:** the IR transceiver part. Nothing has been tested on hardware yet.
- **Next:**
  1. Bench test against a real walker from a PC.
  2. Link to WatermelonDS over Wi-Fi.
  3. Add a USB-serial mode to melonDS Android and offer it upstream.
  4. A small custom PCB "hat" for the XIAO so the dongle is solder-headers-only.
  5. A 3D-printed case.

## Known risks

- Signal polarity on the IR lines may need flipping. It's a firmware build flag, not a redesign.
- The TFBS4711 is tiny surface-mount, hence the factory-assembled hat plan.
- Savestates across a walk start or return will confuse a real walker. No emulator can fix that.

No Nintendo code or data ships with any of this. The dongle and the melonDS changes are original code.
