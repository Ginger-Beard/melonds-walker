# melonDS-walker

A DIY USB-C dongle that lets Pokemon HeartGold/SoulSilver running in an emulator talk to a real Pokewalker. An ESP32-S3 and a Vishay TFBS4711 IrDA transceiver act as the IR link, with plug-and-play use after flashing.

This is a personal/community project, not a product. The goal is to upstream IR support into [melonDS Android](https://github.com/rafaelvcaetano/melonDS-android) (rafaelvcaetano/melonDS-android), or failing that to ship it in a fork.

## WARNING: destructive walker commands

Commands 0x2A and 0x2C make the walker wipe itself (pairing, walk, inventory, and for 0x2A lifetime steps), even though 0x2A also replies with the device ID. 0xF0 (factory setup), 0xFE (motion-test setup) and all write commands (EEPROM and RAM writes, walk start/end/update, gift and event commands) are also destructive. `walkerctl` never sends them: a hard-coded allowlist in its send path permits only 0xFA, 0x20, 0x24 and 0xF4 (plus 0x0C reads of exactly 3 payload bytes). Do not bypass this, and take care with any other tool pointed at a real walker.

## Status

Tested on hardware as of 2026-11-12. The XIAO IrDA hat v0.1 worked on first power-on with no rework, and the firmware with default settings talks to a real Pokéwalker. `tools/walkerctl.py handshake` succeeds, and `sniff`, `identify` and `ping` work. On an AYN Thor, the melonDS-android fork (branch `pokewalker-ir`, debug build) used the dongle over USB: HeartGold/SoulSilver erased the walker's old pairing, registered it, and sent a Pokémon on a stroll.

Not yet tested: returning a Pokémon from a stroll, link range, long sessions, the melonDS release (R8) build, the DevKitC-1 build, and the TFDU4101 alternate.

## Repo layout

- `docs/research/` research report and notes (protocol, hardware, emulator landscape, Android transport)
  - `report.md` main research report
  - `notes/` raw research notes (e.g. `notes/ir_hardware_and_protocol.md`)
  - `watermelonds-ir-transport.md` analysis of WatermelonDS's IR transport
  - `walker-protocol-facts.md` handshake, checksum, timing and command facts resolved from the walker and HGSS decompilations, plus the walkerctl review
- `docs/protocol.md` host to dongle USB serial protocol
- `docs/hardware.md` DIY build guide and wiring
- `firmware/` ESP32-S3 firmware
- `hardware/xiao-irda-hat/` XIAO ESP32S3 + TFBS4711 hat PCB (tscircuit source, KiCad board, JLCPCB fab files)
- `tools/` `walkerctl.py` bench tool and its tests

## How it works

The IR transceiver is in the game cartridge, not the console. The cart has a small MCU on the cartridge SPI bus that forwards IR packets. melonDS emulates that cart, and sends and receives the IR packets as bytes. The dongle is a byte pipe: it does the IrDA SIR encoding and timing, strips its own echo, splits packets on line idle, and carries them over USB. It does not interpret packet contents. XOR 0xAA, checksums and session IDs are the game's job. See [docs/protocol.md](docs/protocol.md).

## Quick start

1. Build the hardware: [docs/hardware.md](docs/hardware.md).
2. Flash the firmware: `firmware/README.md`.
3. Install the host tool and check the dongle:

```
pip install -r tools/requirements.txt
python3 tools/walkerctl.py identify
python3 tools/walkerctl.py ping -n 50
```

## Test plan

Bench-test against a real walker before touching melonDS: `walkerctl.py sniff` to confirm the 0xFC beacon, then `walkerctl.py handshake` to connect and read the identity. The staged plan is in the "Validating the link without a working DS" section of [docs/research/report.md](docs/research/report.md). The tool never writes to the walker. A read-only EEPROM `dump` is a TODO.

## Prior art and credits

- Dmitry Grinberg, Pokewalker hacking: https://dmitry.gr/?r=05.Projects&proj=28.%20pokewalker
- GBATEK (Martin Korth / nocash), DS Cart Infrared chapter: https://mgba-emu.github.io/gbatek/#dscartinfraredpedometers
- PoroCYon, pokewalker-rom-dumper: https://zff.dev/PoroCYon/pokewalker-rom-dumper
- mamba2410/picowalker: https://github.com/mamba2410/picowalker
- lumirth/pw: https://github.com/lumirth/pw
- lumirth/stickwalker: https://github.com/lumirth/stickwalker
- Flipwalker and FlippIR-Hardware (Jackv-makes): https://github.com/Jackv-makes/Flipwalker, https://github.com/Jackv-makes/FlippIR-Hardware
- WatermelonDS Pokewalker branch (silver115): https://github.com/silver115/WatermelonDS
- DaveuRrr/melonDS-IR: https://github.com/DaveuRrr/melonDS-IR
- melonDS PR #2776: https://github.com/melonDS-emu/melonDS/pull/2776
- PocketWalker (h4lfheart): https://github.com/h4lfheart/PocketWalker
- usb-serial-for-android (mik3y): https://github.com/mik3y/usb-serial-for-android

## Legal

No Nintendo code or data is in this repo. The dongle never needs a ROM; you only need your own game to use it from an emulator.

## License

TBD
