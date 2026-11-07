# Emulator and software support for the Pokéwalker / HGSS IR link (state as of 2026-11-06)

**Target use case:**
- HGSS on melonDS on Android dual-screen handhelds (e.g. the AYN Thor), linked to a real Pokéwalker through a USB-C dongle or over Wi-Fi/Bluetooth, with no modified carts.
- Secondarily, a software Pokéwalker on a phone for people who don't own one.

**Status labels used below:**
- **SHIPPED**: in an official release of the main project.
- **FORK**: in a third-party fork or standalone project.
- **OPEN PR**: proposed upstream, not merged.
- **INFERENCE**: my reasoning.

## 1. melonDS-IR fork, HachiStep's melonDS bridge, PR #2776, and the Android forks: status, transport, wire format, API seam, Android reach

### Takeaway
Four separate melonDS IR efforts exist, and none is in an official melonDS or melonDS Android release.

| Effort | Platform | Transport | Notes |
|---|---|---|---|
| DaveuRrr/Ceravia **melonDS-IR** | desktop Qt | raw-byte TCP via QTcpSocket, UDP via ENet, raw serial via Qt SerialPort | Hooks are `Platform::IRSendPacket/IRReceivePacket` |
| **PR #2776** (celerizer) | upstream melonDS | TCP 127.0.0.1:43690 | 8-byte timestamped records; open, marked "[no merge yet]" |
| **HachiStep** bridge | desktop only | melonDS's GDB stub | Works with *stock* melonDS 1.1 by planting a RAM mailbox in the game; no IR emulation at all |
| **WatermelonDS "melonDS Pokéwalker"** | Android | Off / Virtual / TCP (port 8081) | Built from rafaelvcaetano's melonDS Android; the only Android build with IR; built-in walker plus a TCP mode compatible with melonDS-IR-style peers; explicitly targets the AYN Thor |

No Android build supports a USB serial IR dongle or Bluetooth yet.

### Cited Findings
**DaveuRrr/melonDS-IR (FORK, desktop)**
- History and status:
  - Forked from Ceravia/melonDS-IR (created 2025-07-05, last push 2026-01-07).
  - The DaveuRrr fork was created 2025-10-04, last pushed 2026-08-09, and has about 10 stars.
  - The README is unmodified upstream, so there are no user docs.
  - [DaveuRrr/melonDS-IR](https://github.com/DaveuRrr/melonDS-IR); [repo API](https://api.github.com/repos/DaveuRrr/melonDS-IR); [Ceravia/melonDS-IR](https://github.com/Ceravia/melonDS-IR)
- API seam:
  - `src/NDSCart/CartRetailIR.cpp` implements IR-cart SPI command `0x01` (receive: first byte is the length, from `Platform::IRReceivePacket`) and `0x02` (send: bytes buffered, flushed on `SPIRelease()` via `Platform::IRSendPacket`).
  - It also adds `IRReadTimeOutUs`, `IRSendDelayUs` and `IRClose`, declared in `src/Platform.h` and implemented in `src/frontend/qt_sdl/Platform_IR.cpp`.
  - [CartRetailIR.cpp](https://raw.githubusercontent.com/DaveuRrr/melonDS-IR/master/src/NDSCart/CartRetailIR.cpp); [Platform.h](https://raw.githubusercontent.com/DaveuRrr/melonDS-IR/master/src/Platform.h)
- Transports, per `Platform_IR.cpp`:
  - **TCP**: `QTcpServer`/`QTcpSocket`. A send is `Sock->write(data,len); flush()`. A receive is `Sock->read()` of whatever is available. That is a raw byte stream with **no framing**. The default role is client to `127.0.0.1`.
  - **UDP**: implemented with ENet peers.
  - **Serial**: `QSerialPort` at 115200 8N1, raw bytes.
  - [Platform_IR.cpp](https://raw.githubusercontent.com/DaveuRrr/melonDS-IR/master/src/frontend/qt_sdl/Platform_IR.cpp); [Config.cpp](https://raw.githubusercontent.com/DaveuRrr/melonDS-IR/master/src/frontend/qt_sdl/Config.cpp)
- IR settings UI:
  - Modes Serial/TCP/UDP, Client/Server.
  - A "Direct" mode with an EEPROM file (commit: "Direct mode works (barely & spoofed)").
  - Serial read-timeout and send-delay in µs.
  - Packet log with XOR-0xAA decrypt.
  - It carries the warning "Experimental, Backup your save before using!!!"
  - Serial timing commits include "Serial Timing Ownership FTDI 22,000 to 25,000 ReadTimeout" (2026-05).
  - [IRSettingsDialog.ui](https://raw.githubusercontent.com/DaveuRrr/melonDS-IR/master/src/frontend/qt_sdl/IRSettingsDialog.ui); [commits](https://api.github.com/repos/DaveuRrr/melonDS-IR/commits?per_page=60)
- Known peers: PocketWalker connects to it over TCP. — [PocketWalker](https://github.com/h4lfheart/PocketWalker)

**melonDS PR #2776 (OPEN PR, upstream desktop core)**
- "[no merge yet] Add communication with emulated IR accessories", by celerizer, opened 2026-10-07.
  - It targets emulated NTR-027 and NTR-032 (Pokéwalker) devices via the author's **Stepdad** emulator (libh8300h), "or any future H8 300/H emulator that adopts the same comms format".
  - SPI commands are simulated locally.
  - TODOs: LAN support and BW cart-to-cart.
  - [PR #2776](https://github.com/melonDS-emu/melonDS/pull/2776)
- Wire format, from `CartRetailIRLink.h`:
  - TCP client to 127.0.0.1:43690 (0xAAAA), with `TCP_NODELAY` ("IR replies are expected within milliseconds").
  - Each record is 8 bytes: `[0]` 'B' (IR byte) or 'T' (end of burst/packet), `[1]` the byte, `[2..3]` 'I','R' (resync marker), `[4..7]` the sender's clock in 3.6864 MHz walker-CPU cycles, big-endian.
  - It queues at most 8 received packets and drops the oldest.
  - It enforces a 16-character gap between back-to-back packets.
  - [PR #2776 diff](https://patch-diff.githubusercontent.com/raw/melonDS-emu/melonDS/pull/2776.diff)
- API seam: `IRLink::SendByte/EndPacket/Receive/ReceivedByte/DropPacket`, called from `CartRetailIR` (`0x01`/`0x02`). The connection is non-blocking. It adds an enum `CartRetailIRVersionEarly` (NTR-027) / `CartRetailIRVersionLate` (NTR-032; IPK/IPG = HGSS). — [PR #2776 diff](https://patch-diff.githubusercontent.com/raw/melonDS-emu/melonDS/pull/2776.diff)
- Stepdad repo: "An NTR-032 and NTR-027 emulator", created 2026-10-08, with a libretro core. — [Stepdad API](https://api.github.com/repos/celerizer/Stepdad)

**HachiStep melonDS bridge (FORK/standalone, desktop)**
- lumirth/hachistep PR #15, "Connect walkers to stock melonDS with a live cartridge mailbox", merged 2026-10-22, shipped in v0.4.0–v0.5.1 (2026-10-22/23).
- How it works:
  - "Tools → Infrared → Connect to melonDS…" requires **stock melonDS 1.1 with the ARM9 GDB stub enabled**.
  - HachiStep pauses melonDS and installs an adapter in game RAM.
  - Data then flows HGSS ↔ RAM mailbox ↔ GDB ↔ HachiStep's emulated walker "optical input".
  - It recognizes 32 HGSS images across 7 languages plus Sacred Gold Plus; hacks must keep the retail IR driver.
- Caveats:
  - Resets and savestate loads remove the adapter.
  - The GDB stub accepts unauthenticated network connections.
  - Live tests were on macOS only.
- [hachistep PR #15](https://github.com/lumirth/hachistep/pull/15)
- HachiStep releases are Linux x86_64, macOS arm64 and Windows x86_64 only. There is no Android build. — [releases API](https://api.github.com/repos/lumirth/hachistep/releases)

**Android: rafaelvcaetano/melonDS-android (official port)**
- No IR. Issue #433 "Need IR(Infrared) Connection Support" has been open since 2021-06-18. A search for IR/infrared/Pokéwalker turned up no IR PRs. — [melonDS-android #433](https://github.com/rafaelvcaetano/melonDS-android/issues/433); [issue search API](https://api.github.com/search/issues?q=repo:rafaelvcaetano/melonDS-android+infrared+OR+pokewalker+OR+IR)

**Android: silver115/WatermelonDS, branch `melonds-pokewalker` (FORK)**
- Lineage and builds:
  - Fork chain: rafaelvcaetano/melonDS-android → SapphireRhodonite/WatermelonDS → silver115/WatermelonDS (created 2026-10-22).
  - The branch is 117 commits ahead of Develop. The Pokéwalker commits run 2026-10-22 to 2026-11-01, starting with "Add Pokéwalker support: IR cartridge, virtual Pokéwalker and step sync".
  - Releases are arm64 APKs, either side-by-side or replacing the `me.magnum.melonds` app ID.
  - [repo API](https://api.github.com/repos/silver115/WatermelonDS); [compare API](https://api.github.com/repos/silver115/WatermelonDS/compare/Develop...melonds-pokewalker); [release](https://github.com/silver115/WatermelonDS/releases/tag/melonds-pokewalker-latest)
- Its docs are titled "Pokéwalker support (AYN Thor and other Android devices)". A commit adds "AYN Thor controls". — [docs/POKEWALKER.md](https://raw.githubusercontent.com/silver115/WatermelonDS/melonds-pokewalker/docs/POKEWALKER.md)
- API seam:
  - `CartRetailIR` in `melonDS-android-lib/src/NDSCart.cpp` implements `0x01`/`0x02` through three new hooks: `Platform::IR_Reset`, `IR_SendPacket` and `IR_ReceivePacket` (`PlatformIR.cpp`).
  - These are routed by `PokewalkerIR.cpp` to `Mode::Off`, `Mode::Virtual` or `Mode::Tcp` (default `tcpPort = 8081`).
  - [PokewalkerIR.h](https://raw.githubusercontent.com/silver115/WatermelonDS/melonds-pokewalker/app/src/main/cpp/pokewalker/PokewalkerIR.h); [PlatformIR.cpp](https://raw.githubusercontent.com/silver115/WatermelonDS/melonds-pokewalker/app/src/main/cpp/pokewalker/PlatformIR.cpp)
- TCP mode: "*Infrared mode → TCP* opens port 8081 on the Thor. Walker emulators that speak melonDS-IR's TCP protocol (for example `picowalker-sdl-tcp`) can connect to it over Wi-Fi." The header comment names PocketWalker as a TCP peer. — [docs/POKEWALKER.md](https://raw.githubusercontent.com/silver115/WatermelonDS/melonds-pokewalker/docs/POKEWALKER.md); [PokewalkerIR.h](https://raw.githubusercontent.com/silver115/WatermelonDS/melonds-pokewalker/app/src/main/cpp/pokewalker/PokewalkerIR.h)
- Virtual walker: an independent high-level (HLE) implementation of the walker side. It covers the handshake, session ID, checksums, EEPROM read/write with LZ77, pairing and stroll start/end, and keeps a real-format 64 KiB EEPROM image. It "contains no Nintendo code or data", so **no walker ROM is needed**. Steps come from Health Connect, a Samsung Health export or manual entry. — [docs/POKEWALKER.md](https://raw.githubusercontent.com/silver115/WatermelonDS/melonds-pokewalker/docs/POKEWALKER.md)
- Limits:
  - Simplified Poké Radar and dowsing.
  - No event routes or event Pokémon.
  - HGSS only.
  - A real walker's data can only be *imported* as an EEPROM dump ("for example with the pwsync tool and a Raspberry Pi Pico IR bridge"). There is no live link to a physical walker.
  - [docs/POKEWALKER.md](https://raw.githubusercontent.com/silver115/WatermelonDS/melonds-pokewalker/docs/POKEWALKER.md)
- The tagged release commit is signed by an account named "claude", which suggests AI-assisted development. The project is very new (2 weeks). — [release](https://github.com/silver115/WatermelonDS/releases/tag/melonds-pokewalker-latest)

### Inferences
- For the AYN Thor today, the only working route is WatermelonDS:
  - Virtual mode needs no walker at all.
  - TCP mode works with PocketWalker-Android on the same device via 127.0.0.1:8081, or a PC walker emulator over Wi-Fi.
- A **real** Pokéwalker on Android needs one of two new pieces:
  - A Wi-Fi IR bridge, e.g. an ESP32 plus an IrDA SIR transceiver acting as a TCP client/server that pumps raw IR bytes into WatermelonDS's port 8081. This matches melonDS-IR's unframed raw-byte TCP.
  - A USB-serial mode in the Android frontend.
  - A Wi-Fi bridge needs zero app changes, but raw-byte TCP has no packet boundaries, so the bridge must preserve inter-packet gaps (see §4 timing).
- PR #2776's timestamped record format is better suited to remote/wireless links than melonDS-IR's raw stream. If it merges upstream, melonDS Android would likely pick it up eventually, since it tracks upstream via melonDS-android-lib.
- HachiStep's GDB approach is unlikely to reach Android. It needs a GDB stub exposed by the frontend, and I found no evidence that melonDS Android exposes one.

### Gaps
- I couldn't confirm whether WatermelonDS's TCP mode is byte-for-byte compatible with DaveuRrr's raw TCP. The docs claim it is, but this is untested by me.
- The default TCP port of DaveuRrr/melonDS-IR could not be read from the config. PocketWalker Android uses 8081, which suggests that is the convention.
- No upstream melonDS or melonDS-android maintainer statement exists on PR #2776 or WatermelonDS.
- "pwsync" and "picowalker-sdl-tcp" could not be located on GitHub. mamba2410/picowalker-sdl exists, but its README lists "connect" as not yet done.
- There is no Bluetooth transport in any project.

## 2. Pokéwalker emulators and decompilations: platforms, ROM/EEPROM requirements, connection to melonDS, maturity

### Takeaway
Three kinds of project exist:
1. **LLE emulators that run the real firmware** need a user-dumped walker ROM (48 KB) and usually the 64 KB EEPROM:
   - PocketWalker: Windows, plus Android via the ATEMVEGETA fork, which can connect to melonDS at 127.0.0.1:8081.
   - HachiStep: desktop.
   - Stepdad: desktop/libretro.
   - PokeStride: 3DS.
   - pwdbg: PC CLI.
2. **The firmware decompilation** (lumirth/pw, a CC0 matching decomp) lets firmware be built with *placeholder* art and no Nintendo ROM. It is already ported to M5Stack Stick S3 (Stickwalker), Flipper Zero (Flipwalker) and a browser/WASM sim (pw-sim). A second, AI-driven decomp (UnrealPowerz/pw_firm) runs on PocketWalker at about 76% byte match.
3. **High-level reimplementations** (WatermelonDS's virtual walker, picowalker) need no ROM.

For a phone user without a walker, the most complete option today is WatermelonDS Virtual mode (Android, no ROM). The most faithful option is PocketWalker-Android plus a dumped ROM. There is nothing confirmed for iOS.

### Cited Findings
**PocketWalker, h4lfheart (LLE)**
- Facts:
  - H8/38606F emulator: CPU, SSU/SCI3, timers, RTC, ADC, BMA150, M95512 EEPROM, NT7508 LCD, buzzer.
  - "IR Communications over TCP with melonDS-IR"; UDP and serial IR are planned.
  - GPL-3.0, created 2025-06-27.
  - Releases v2.0.0 (2026-04-22) and v2.0.1 (2026-08-13) ship as a Windows `pocketwalker.exe`.
- [PocketWalker](https://github.com/h4lfheart/PocketWalker); [releases API](https://api.github.com/repos/h4lfheart/PocketWalker/releases)
- First demo connecting to melonDS was 2025-07-27. — [HalfHeart on X](https://x.com/HalfHeart/status/1949620263970107632)

**ATEMVEGETA/PocketWalker fork (Android + Windows)**
- Releases custom-v0.52.4 (2026-10-28) and custom-v0.53.0 (2026-11-05) include `PocketWalker-Android-arm64-*.apk` and a Windows exe. — [releases API](https://api.github.com/repos/ATEMVEGETA/PocketWalker/releases)
- Android port behaviour:
  - Feeds the phone accelerometer into the emulated BMA150, so the original firmware does step detection.
  - Runs as a foreground service with screen-off walking, and needs Android 10+ on ARM64.
  - The user selects a folder containing `rom.bin`, and saves go to `rom.pwsav`.
  - "Connect melonDS makes the phone a TCP client. It first checks `127.0.0.1` for melonDS running on the same Android device, then tries the optional saved PC address and local-network discovery on port 8081."
  - Also offers automatic Android-to-Android peer play.
  - Described as "a hardware-test build", developed with OpenAI Codex assistance.
  - [android/README.md](https://raw.githubusercontent.com/ATEMVEGETA/PocketWalker/main/android/README.md); [ATEMVEGETA/PocketWalker](https://github.com/ATEMVEGETA/PocketWalker)

**HachiStep, lumirth (LLE, Rust)**
- "Pokéwalker emulator for arbitrary firmware", alpha, created 2026-09-17, v0.5.1 2026-10-23, desktop builds only.
- It links to stock melonDS 1.1 via GDB (see §1).
- [hachistep README](https://raw.githubusercontent.com/lumirth/hachistep/main/README.md); [releases API](https://api.github.com/repos/lumirth/hachistep/releases)

**Stepdad, celerizer (LLE, libh8300h)**
- Desktop and libretro. Links to melonDS PR #2776 builds over TCP 43690. Binaries were not yet distributed as of the PR. — [PR #2776](https://github.com/melonDS-emu/melonDS/pull/2776)

**PokeStride, edgarburgues (LLE on 3DS homebrew)**
- Runs the original firmware on a 3DS. Needs the user's `pwflash.rom` and `pweep.rom` ("They belong to Nintendo and are **not** included here").
- Status:
  - IR with a real walker is "close, but not there yet".
  - Peer play against the PC tool "pwlink" works.
  - Audio is off.
  - Steps count only with the lid closed.
- [pokestride](https://github.com/edgarburgues/pokestride)
- pwdbg: a PC CLI debug emulator reusing PokeStride's core, with a REPL and two-walker IR "duo" mode. It needs ROM/EEPROM dumps. — [pwdbg](https://github.com/edgarburgues/pwdbg)
- PkwBridge: a 3DS app that sends and returns Pokémon by editing the HGSS `.sav` and `pweep.rom` on SD, with **no IR**. Beta; verified on EU 1.1 saves. — [pkwbridge](https://github.com/edgarburgues/pkwbridge)

**lumirth/pw (decompilation)**
- "A human-readable matching decompilation of the Pokéwalker firmware", CC0, created 2026-09-13.
- With retail artwork and Renesas H8 compiler v6.02.01/02 it builds a byte-identical binary.
- Placeholder artwork can be used instead, so the ROM is needed only to extract art.
- [lumirth/pw](https://github.com/lumirth/pw); [repo API](https://api.github.com/repos/lumirth/pw)

**Ports of the decomp**
- **pw-sim**: firmware recompiled to WebAssembly with a browser UI and 3D physics-driven step input. It "no longer targets a byte-identical H8 ROM". — [pw-sim](https://github.com/lumirth/pw-sim)
- **Stickwalker** (M5Stack Stick S3 plus a BPV10NF photodiode):
  - Release downloads "use placeholder built-in artwork".
  - The user can build with art from their own ROM.
  - MIT licence.
  - [stickwalker](https://github.com/lumirth/stickwalker)
- **Flipwalker** (Flipper Zero, a Stickwalker port):
  - Connects to HGSS in both directions using the FlippIR add-on (TFBS4711 on the STM32 USART1 IrDA encoder).
  - Loads a real 64 KB EEPROM dump.
  - [Flipwalker](https://github.com/Jackv-makes/Flipwalker); [FlippIR](https://github.com/Jackv-makes/FlippIR-Hardware)

**UnrealPowerz/pw_firm**
- "An AI-driven C decompilation". Every function is implemented and the binary "runs end-to-end on the pocketwalker emulator". Byte match is about 76% and has plateaued because the compiler is unknown. — [pw_firm](https://github.com/UnrealPowerz/pw_firm)

**High-level reimplementations (no ROM)**
- WatermelonDS virtual walker (§1). — [docs/POKEWALKER.md](https://raw.githubusercontent.com/silver115/WatermelonDS/melonds-pokewalker/docs/POKEWALKER.md)
- picowalker: RP2350 hardware, "not an emulator", not yet at parity. — [picowalker](https://github.com/mamba2410/picowalker)
- picowalker-sdl: a desktop SDL build of picowalker. It needs a 64 KB `eeprom.bin` cloned from a real walker, and "connect can be left alone for now". — [picowalker-sdl](https://github.com/mamba2410/picowalker-sdl)

**Others**
- PokeStroller: Windows, no IR. — [pokestroller](https://github.com/jpcerrone/pokestroller)
- PokeWear: Wear OS port of PokeStroller. — [GitHub topic](https://github.com/topics/pokewalker)
- pwemu: WIP. — [pwemu](https://github.com/PoroCYon/pwemu)
- Many "Pokéwalker-like" phone apps (a PWA generating PKHeX data, Wear OS, iOS repos with no description) do not run the firmware or speak IR. — [GitHub search](https://api.github.com/search/repositories?q=pokewalker&sort=updated&per_page=40)

### Inferences
- **For people without a walker, on an Android handheld:**
  - WatermelonDS Virtual mode is turnkey: no ROM, one app.
  - PocketWalker-Android plus WatermelonDS TCP on the same device (127.0.0.1:8081) gives the real firmware experience, but needs someone's ROM dump.
- **A ROM-free but faithful option** would be an Android build of the lumirth/pw decomp with placeholder art. pw-sim's WASM build shows that is feasible, and the Stickwalker and Flipwalker ports show it interoperates with real HGSS. Nobody has shipped an Android build yet.
- **iOS:** no LLE walker emulator or IR-capable DS emulator was found. A pw-sim browser build is the only plausible near-term route.

### Gaps
- No published reliability data for PocketWalker-Android ↔ WatermelonDS on one device. The ATEMVEGETA README says "compatible ... Android melonDS builds" without naming one.
- pw-sim: no info on whether a hosted build exists.
- iOS: the star-studios-official/Pokewalker-iOS repo has no description and was not inspected.

## 3. How a user dumps their own Pokéwalker ROM/EEPROM, and the legal/distribution caveats

### Takeaway
- **With a 3DS:** pwalkerHax uses the 3DS's built-in IR and needs no cart. It dumps both the ROM and the EEPROM.
- **With a DSi or 3DS in DSi mode plus a real HGSS/BW/B2W2 cart:** use PoroCYon's pokewalker-rom-dumper.
- **Historical:** Dmitry's PalmOS app.
- **On a PC with a USB-IrDA serial dongle:** mze9412/PokewalkerClient does EEPROM backup/restore.

Reading the ROM requires Dmitry's IR exploit; the EEPROM is readable via protocol commands. RtcPwalker is not a dumper: it is an HGSS patch letting the game use the 3DS IR port.

On the legal side, every project refuses to distribute ROMs. The firmware and EEPROM contents are Nintendo/Game Freak material, so users must dump their own. The CC0 decomp and HLE implementations avoid needing them.

### Cited Findings
**Dumping tools**
- **Dmitry.GR (origin):**
  - Found a decompressor stack-overflow exploit in the compressed EEPROM-write command, plus CMD_06 direct RAM write, giving code execution over IR.
  - Used it to dump the 48 KB ROM over IR.
  - The PalmOS app "WalkePokér" dumps ROM to SD as POKEROM.BIN, gifts Pokémon/items and adds watts. It targets PalmOS 4 / Palm m500-class devices, GPLv3.
  - [Dmitry.GR](https://dmitry.gr/?r=05.Projects&proj=28.+pokewalker); [Hackaday 2020-11-21](https://hackaday.com/2020/11/21/reverse-engineering-a-pokewalker/)
- **PoroCYon pokewalker-rom-dumper:**
  - DSi homebrew that dumps the walker ROM/EEPROM to SD using an HGSS, BW or B2W2 cart's IR. It needs only cart power.
  - "Others tell me it works on a 3DS/2DS in DSi backwards-compat mode".
  - X dumps the EEPROM; Y restores it (restore untested).
  - It freezes if a non-IR cart (e.g. a flashcart) is inserted.
  - [pokewalker-rom-dumper](https://zff.dev/PoroCYon/pokewalker-rom-dumper)
  - Referenced by PokeStroller, PokeStride (francesco265 fork) and picowalker-sdl. — [pokestroller](https://github.com/jpcerrone/pokestroller); [pokestride](https://github.com/edgarburgues/pokestride); [picowalker-sdl](https://github.com/mamba2410/picowalker-sdl)
- **pwalkerHax** (francesco265, 3DS homebrew `.3dsx`):
  - "uses the built-in infrared transceiver" of the 3DS, so no cart is needed.
  - Features: add watts, set steps, gift event items and Pokémon, **Dump ROM**, **Dump EEPROM**.
  - It is a port of Dmitry's work. Last push 2026-01-08, 37 stars.
  - [pwalkerHax](https://github.com/francesco265/pwalkerHax); [search API](https://api.github.com/search/repositories?q=pokewalker&sort=updated&per_page=40)
- **RtcPwalker** (francesco265):
  - An HGSS Action Replay patch plus TWPatch/RTCom-patched TWL_FIRM. It lets HGSS running on 3DS (via TWiLight Menu++) talk to a real walker through the 3DS IR port, "without needing a IR capable cartridge".
  - Marked "EXPERIMENTAL". The README says "RTCom adds a big overhead ... the communication is **SLOW and UNSTABLE**". Tested on Old 3DS only.
  - It is a link path, not a dumper.
  - [RtcPwalker](https://github.com/francesco265/RtcPwalker)
- **mze9412/PokewalkerClient** (Python CLI/TUI, PC):
  - EEPROM 64 KB backup/restore, add watts via shellcode, set or gift Pokémon/items.
  - Needs a USB-IrDA dongle exposing raw SIR at 115200 as a serial port. "Confirmed working" chipsets are MosChip MCS7780 and MCS7840.
  - Dongles using the Linux `irda`/`ircomm` stack are "Not compatible".
  - No ROM dump is listed.
  - [PokewalkerClient](https://github.com/mze9412/PokewalkerClient)
- **pwlink**: PC-side walker IR protocol implementation using "an IrDA SIR transceiver on a serial port", e.g. a Flipper Zero in USB-UART bridge mode with an MY018 module. "pwlink completes encounters with a real PokéWalker". — [pokestride README](https://github.com/edgarburgues/pokestride)
- WatermelonDS docs mention dumping the EEPROM "with the pwsync tool and a Raspberry Pi Pico IR bridge". I could not locate pwsync. — [docs/POKEWALKER.md](https://raw.githubusercontent.com/silver115/WatermelonDS/melonds-pokewalker/docs/POKEWALKER.md)
- **EEPROM tools:**
  - UnrealPowerz's web-based Pokéwalker EEPROM Editor/viewer. — [pokewalker-eeprom-editor](https://github.com/UnrealPowerz/pokewalker-eeprom-editor)
  - mamba2410's `help.c` "fix broken walker eeproms so that game accepts them in walk end". — [pokewalker-tools](https://github.com/mamba2410/pokewalker-tools)
- The EEPROM holds images and strings uploaded by the game, not just Pokémon data. — [PokewalkerUtils](https://github.com/Pusty/PokewalkerUtils)

**Legal and distribution positions**
- PokeStride: the ROM and EEPROM "belong to Nintendo and are **not** included here". — [pokestride](https://github.com/edgarburgues/pokestride)
- lumirth/pw:
  - Requires "lawfully-obtained copies" of the ROM (for art) and the Renesas compiler.
  - "Retail firmware images, extracted retail artwork, and the Renesas compiler toolchain are not distributed".
  - Contributions must not include leaked material or retail artwork.
  - The project is unaffiliated with Nintendo, TPC, Game Freak or Renesas, and its CC0 covers only the authors' own material.
  - [lumirth/pw](https://github.com/lumirth/pw)
- Stickwalker's release binaries use placeholder art. — [stickwalker](https://github.com/lumirth/stickwalker)
- WatermelonDS's virtual walker "is an independent implementation and contains no Nintendo code or data". — [docs/POKEWALKER.md](https://raw.githubusercontent.com/silver115/WatermelonDS/melonds-pokewalker/docs/POKEWALKER.md)
- A Project Pokémon thread collects EEPROM dumps from volunteers for research. — [Project Pokémon](https://projectpokemon.org/home/forums/topic/62695-seeking-pokewalker-eeprom-dumps)

### Inferences
- The simplest dumping path for most owners is a hacked 3DS running pwalkerHax, with no cart needed. Next is a DSi or 3DS with an HGSS/BW cart and PoroCYon's dumper. On PC, a MosChip USB-IrDA dongle with PokewalkerClient covers the EEPROM only.
- Shipping an Android app that bundles the walker ROM, or an EEPROM image containing game-uploaded sprites, would be redistribution of copyrighted material. The community norm is BYO dumps, or HLE/decomp with placeholder art. This is not legal advice, and I found no court or Nintendo takedown specific to Pokéwalker projects.

### Gaps
- I didn't verify whether pwalkerHax's ROM dump works on New 3DS.
- There are no official legal analyses or Nintendo DMCA notices against Pokéwalker repos in what I searched.
- pwsync and the "Raspberry Pi Pico IR bridge" were not found.

## 4. melonDS implementation internals and timing (for someone adding IR or a new transport)

### Takeaway
The call chain is:
1. The game accesses AUXSPICNT/AUXSPIDATA (0x040001A0/A2).
2. `NDSCartSlot::Interface::WriteSPIData` in `src/NDSCart.cpp` runs.
3. That calls `Cart->SPISelect()`, `SPITransmitReceive(u8)` and `SPIRelease()` synchronously on the emulation thread.
4. The cart object is `CartRetailIR` (for game codes starting with 'I'), which wraps `CartRetail` (the save chip).

The IR-cart protocol is:
- `0x00` save pass-through.
- `0x01` receive (length byte first; zero-length means nothing pending).
- `0x02` send (ends on CS release).
- `0x03`–`0x06` IR-MCU RAM access.
- `0x08` status (returns 0xAA).

Upstream implements only `0x00` and `0x08`.

On timing: the game polls in software, inserting about 50 µs of busy-wait between SPI bytes. A WatermelonDS host test models a **100 ms reply deadline** derived from the pokeheartgold decomp. The walker beacons every few hundred ms. USB-serial is workable if the FTDI latency timer is set to 1 ms and the transport never blocks the emulation thread.

### Cited Findings
**Upstream code path**
- `NDS.cpp` maps 0x040001A0–A2 to `NDSCartSlots[0]` SPI accessors. — [NDS.cpp](https://raw.githubusercontent.com/melonDS-emu/melonDS/master/src/NDS.cpp)
- `WriteSPIData` calls `Parent.Cart->SPITransmitReceive(val)`, releases CS if hold bit 6 is clear, and schedules completion after `8 * (8 << (SPICnt & 0x3))` cycles. — [NDSCart.cpp](https://raw.githubusercontent.com/melonDS-emu/melonDS/master/src/NDSCart.cpp)
- `ParseROM` sets `irversion` 1 (Walk With Me) or 2 (HG/SS, B/W, B2/W2) for 'I' game codes and constructs `CartRetailIR`. — [NDSCart.cpp](https://raw.githubusercontent.com/melonDS-emu/melonDS/master/src/NDSCart.cpp)
- `CartRetailIR::SPITransmitReceive`: `0x00` goes to `CartRetail::SPITransmitReceive`, `0x08` returns `0xAA`, and the source carries `// TODO: emulate actual IR comm`. — [CartRetailIR.cpp](https://raw.githubusercontent.com/melonDS-emu/melonDS/master/src/NDSCart/CartRetailIR.cpp)
- `CartRetail` handles the EEPROM/FLASH save chip and flushes via `Platform::WriteNDSSave` on release. — [CartRetail.cpp](https://raw.githubusercontent.com/melonDS-emu/melonDS/master/src/NDSCart/CartRetail.cpp)
- Latest melonDS releases: 1.1 (2025-11-18), 1.0 (2025-07-08). — [releases API](https://api.github.com/repos/melonDS-emu/melonDS/releases)

**IR-cart protocol (PoroCYon, melonDS board "GBAtek addendum/errata", 2020-11-16 / 2021-03-01)**
- Commands run over the save SPI at 1 MHz; the IR side runs at 115200 8N1 automatically.
- Command details:
  - `0x01`: the first byte is the count (≤255); with 0 bytes, release CS with a zero byte.
  - `0x02`: no length prefix; CS release ends the packet.
  - `0x03`–`0x06`: MCU RAM access (credited to nocash).
  - `0x08`: status. HGSS sends it twice; carts return 0x00 then 0xAA.
- HGSS sequence: `0x01`, `0x08` ×2, then repeated `0x01` until the walker beacon arrives.
- The cart MCU is believed to be an H8/38602F or 38606F.
- [melonDS board](http://melonds.kuribo64.net/board/thread.php?pid=2762#2762); [pokewalker-rom-dumper](https://zff.dev/PoroCYon/pokewalker-rom-dumper)
- GBATEK itself was unreachable from this environment.

**Walker protocol**
- SIR 115200 8N1, XOR 0xAA, 8-byte header (cmd, extra, checksum, session ID), payload ≤128 bytes.
- Beacon 0xFC "every few hundred milliseconds", then 0xFA (master/DS), then 0xF8 (walker).
- [Dmitry.GR](https://dmitry.gr/?r=05.Projects&proj=28.+pokewalker)

**Game-side timing**
- The HGSS IR library `lib/asm/libirc.s` in pret/pokeheartgold contains `CARD_SpiWaitInit` (stores 0x32 into the read, write and dummy wait-cycle bytes), `CARDi_SpiDummyWait` (busy-loops on `OS_GetTick` scaled by 0xFA00/0x82EA), and `CARDi_SpiWaitWriteByte/ReadByte`. — [libirc.s](https://raw.githubusercontent.com/pret/pokeheartgold/master/lib/asm/libirc.s)
- WatermelonDS's `hgss_flow_test` "replays every Pokéwalker flow the game has (register, stroll, return, gifts, erase), with the game's own checks, sizes and 100 ms reply deadline", modelled on pokeheartgold overlay 112 and libirc. — [docs/POKEWALKER.md](https://raw.githubusercontent.com/silver115/WatermelonDS/melonds-pokewalker/docs/POKEWALKER.md)

**Reimplementation timing choices**
- picowalker UART driver: waits ≤50,000 µs for the first byte, and ends a packet after 3,742 µs of idle. — [rp2xxx_uart.c](https://raw.githubusercontent.com/mamba2410/picowalker/main/src/drivers/ir/rp2xxx_uart.c)
- DaveuRrr's fork:
  - Busy-waits inside the SPI call for `readTimeoutUs` (about 22–25 ms for FTDI).
  - Sleeps 10 ms before packets starting with raw byte 0x5E, commented "or else it will be piggybacked onto the latest packet (on the pokewalker's end)".
  - [CartRetailIR.cpp (DaveuRrr)](https://raw.githubusercontent.com/DaveuRrr/melonDS-IR/master/src/NDSCart/CartRetailIR.cpp)
- HachiStep needed local `0x2E` keepalive frames to survive 250 ms stalls, and a 3 s interruption fails. — [hachistep PR #15](https://github.com/lumirth/hachistep/pull/15)
- RtcPwalker notes "the 3DS needs to follow the strict timings of the Pokewalker", and its RTCom overhead makes it "SLOW and UNSTABLE". — [RtcPwalker](https://github.com/francesco265/RtcPwalker)

**Transport hardware**
- The FTDI latency timer defaults to 16 ms. On Linux it is set via `/sys/bus/usb-serial/devices/ttyUSBx/latency_timer`, and 1 is the usual fix; it may revert on replug. — [projectgus](https://www.projectgus.com/2011/10/notes-on-ftdi-latency-with-arduino/); [Granite Devices](https://granitedevices.com/wiki/FTDI_Linux_USB_latency)
- On Android, usb-serial-for-android gives raw serial over USB Host/OTG with "No root access ... all drivers are implemented in Java". Since v3.5.0 it detects CDC/ACM devices by interface type. — [usb-serial-for-android](https://github.com/mik3y/usb-serial-for-android)
- MCP2122: UART to IrDA SIR encoder/decoder, max 115.2 kbaud, baud set by 16XCLK. — [MCP2122 datasheet](https://www.farnell.com/datasheets/60236.pdf)
- The STM32 USART has a built-in IrDA ENDEC; FlippIR pairs it with a TFBS4711. — [FlippIR](https://github.com/Jackv-makes/FlippIR-Hardware)

### Inferences (my arithmetic and analysis)
- **libirc wait loop:** it converts ticks to µs (×64000/33514 matches the 33.514 MHz/64 OS tick). The 0x32 default therefore means about **50 µs of busy-wait per SPI byte**. The game paces SPI in software, which melonDS's synchronous SPI model already satisfies. This is my reading of the disassembly.
- **Wire time:** 1 char ≈ 86.8 µs at 115200, so a full 136-byte packet takes about 11.8 ms on air. With a 100 ms reply budget:
  - USB full-speed with the FTDI timer at 1 ms (or a CDC-ACM Pico) adds roughly 1–3 ms each way. That fits.
  - At the default 16 ms, plus Android scheduling jitter, it is tight but possibly OK.
  - Wi-Fi to an ESP32 typically adds a few ms. That is likely OK with `TCP_NODELAY`, but power-save Wi-Fi spikes could break sessions.
  - Bluetooth SPP/BLE adds roughly 7.5–30+ ms connection intervals. That is risky but conceivable.
  - All latency estimates here are general knowledge, not sourced.
- **Never block in `SPITransmitReceive`.** Use a reader thread that assembles packets by idle gap (about 3–4 ms) into a queue, so `0x01` returns the queued length or 0. That is PR #2776's design; DaveuRrr's busy-wait stalls emulation.
- **Frame packets at the hardware end.** A Pico or ESP32 should delimit packets by idle gap and send whole packets, which mimics the cart MCU's buffering. Raw unframed byte streams (melonDS-IR TCP) lose packet boundaries across Wi-Fi jitter.
- **Keep emulation at 1x speed during transfers.** The game's deadlines run in emulated time, the walker's in real time.

### Gaps
- The original walker firmware's reply timeouts are unpublished, though the lumirth/pw decomp now makes them extractable. HGSS overlay 112's exact timeout constant was not independently verified; it comes only from the WatermelonDS docs.
- No measured end-to-end latency exists for any USB, Wi-Fi or BT IR bridge.
- The cart MCU's receive-side packet delimiting rule is undocumented.

## 5. Brief survey: other emulators, save editing, real-walker bridges

### Takeaway
DeSmuME and NooDS stub only the `0x08` ID. PKHeX edits HGSS-side walker data (steps, watts, courses). The real-walker links shown to work are:
- RtcPwalker on 3DS (slow).
- Real IR carts on DSi/3DS.
- Flipwalker (a walker *replacement*) to a real cart.
- PC tools (pwlink, PokewalkerClient) talking to a real walker.

No bridge from a real walker to melonDS (desktop or Android) is documented as working.

### Cited Findings
**Other emulators**
- DeSmuME `BM_CMD_IRDA 0x08` returns 0xAA, "Unverified". — [DeSmuME mc.cpp](https://raw.githubusercontent.com/TASEmulators/desmume/master/desmume/src/mc.cpp)
- A DeSmuME forum regular (windwakr) doubts IR will ever land and points users to PocketWalker plus melonDS-IR. — [DeSmuME forum](https://forums.desmume.org/viewtopic.php?pid=31886)
- PokewalkerUtils (2021): a DeSmuME dev-build Lua hook to a Python walker over 127.0.0.1:54545, US HeartGold only. — [PokewalkerUtils](https://github.com/Pusty/PokewalkerUtils)
- NooDS returns 0xAA for `0x08` on 'I' game codes ("anti-piracy measure"). — [NooDS cartridge.cpp](https://raw.githubusercontent.com/Hydr8gon/NooDS/master/src/core/memory/cartridge.cpp)

**Save editing**
- PKHeX `SAV4HGSS`: `PokewalkerSteps`/`PokewalkerWatts` (General+0xE704/+0xE708), a course bitfield at +0xE70C, `PokewalkerCoursesUnlockAll()`, and per-language masks. — [SAV4HGSS.cs](https://raw.githubusercontent.com/kwsch/PKHeX/master/PKHeX.Core/Saves/SAV4HGSS.cs)
- PkwBridge does a full send/return by save+EEPROM file editing (§2). — [pkwbridge](https://github.com/edgarburgues/pkwbridge)

**Real hardware**
- An HGSS ROM via TWiLight Menu++ on DSi/3DS with a real SoulSilver cart in slot 1 handled all walker tasks; a Walk With Me cart failed with HG ROMs. — [nds-bootstrap #431](https://github.com/DS-Homebrew/nds-bootstrap/issues/431)
- Arduino Mega RCE on a real walker. — [pokewalker-rce](https://github.com/mamba2410/pokewalker-rce)
- ESP32 plus IrDA Click raw TX/RX. — [jarzadon123/pokewalker](https://github.com/jarzadon123/pokewalker)
- Losing the cart means a walked Pokémon can't truly be recovered, because its personality value lives only in the original save. — [Hackaday 2026-04-06](https://hackaday.com/tag/pokewalker)

### Inferences
- The missing piece for "a real walker plus melonDS on Android" is small and well-scoped: an IrDA SIR front end (Pico PIO, ESP32, or an STM32 USART with TFBS4711/MCP2122) feeding an existing TCP mode (WatermelonDS port 8081 over Wi-Fi), or a new USB-serial mode built on usb-serial-for-android. Every protocol and hardware component has been proven separately by the projects above.

### Gaps
- No sources on 3DS emulators (Citra/Azahar) running DS titles. I believe they don't emulate TWL mode, but that is uncited.
- Nothing found on DraStic.
- Reddit r/Pokewalker was not retrieved.
