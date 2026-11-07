# WatermelonDS IR receiver end and transport: analysis and port plan

Date: 2026-11-06. Scope: the cart-IR and transport side of silver115/WatermelonDS (branch `melonds-pokewalker`). The goal is to port only that part into our fork of rafaelvcaetano/melonDS-android and add a USB-serial transport for the melonDS-walker ESP32-S3 + TFBS4711 dongle (framed protocol, `docs/protocol.md`). The Virtual walker is out of scope except where it constrains the interface.

## 0. TL;DR

- **The core change is small and sound.** It is 2 commits in `silver115/melonDS-android-lib` (branch `melonds-pokewalker`), about 74 added lines in `NDSCart.cpp`, `NDSCart.h` and `Platform.h`. It adds three Platform hooks: `IR_Reset`, `IR_SendPacket` and `IR_ReceivePacket`. These are packet-granular, synchronous, and called on the emulator thread from inside an SPI byte transfer. We want this part, minus the `rom/romlen` (and gamecode) arguments on `IR_Reset`, which exist only for the Virtual walker's ROM check.
- **The frontend transport is not worth porting as code.** `app/src/main/cpp/pokewalker/PokewalkerIR.cpp` (676 lines) mixes the mode switch, a TCP server, logging, ROM checking, game-screen tracing and the virtual walker under one global mutex. The TCP transport does all socket I/O inline on the emulator thread. It frames packets with a 3.5 ms idle wait that blocks the emulator thread on every received packet. It has an unbounded send retry loop and a 10 ms `sleep` before the game's disconnect packet. About 200 of the 676 lines are transport-related, and we need none of them for a framed serial link.
- **Timing is not handled anywhere in WatermelonDS.** The game's deadline is real: overlay 112 `ov112_021E5AD0` gives up 100 ms after the last valid packet, polled every 4 ms (`OS_Sleep(4)`). Both are measured in **emulated** OS ticks. Virtual mode dodges the deadline by answering on the very next poll. TCP mode simply hopes. Fast-forward shrinks the deadline proportionally (to under 10 ms at an unlimited multiplier). Savestate load, rewind and reset never flush the transport.
- **Recommended interface.** Keep a minimal, Net_*-shaped pair of core hooks: `IR_SendPacket(const u8*, int, void* userdata)` and `IR_RecvPacket(u8*, int, void* userdata)`. Route them through `userdata` → `MelonInstance` → a small `IrLink` object that holds a bounded native RX packet queue and a TX sink. The native side has no "mode": Kotlin owns the dongle (usb-serial-for-android, COBS, IDENTIFY), pushes whole IR packets in through JNI, and receives transmitted packets through a cached static JNI callback that only enqueues. The frontend flushes on reset, ROM load, savestate/rewind load and resume, and clamps fast-forward to 1x while IR traffic is recent.
- **Upstream fit.** WatermelonDS's hook shape is close to what is likely to merge. PR #2776 opens sockets inside the core with global state and is self-labelled "[no merge yet]". Its `IRLink` API maps 1:1 onto a packet-level Platform pair, so aligning with Platform hooks keeps us compatible with both.

## 1. Repositories examined (read-only clones)

All clones are under `/tmp/claude-1000/-var-home-josh-projects-radio/f4df7dee-d40b-4349-9c44-1cdb3790ac1f/scratchpad/src/`. Nothing was built or run.

| Dir | Source | Ref |
|---|---|---|
| `watermelon/` | silver115/WatermelonDS | `melonds-pokewalker` @ 63dccbf (2026-11-01). Merge base with upstream: c42995c (2026-09-12) |
| `watermelon-lib/` | silver115/melonDS-android-lib | `melonds-pokewalker` @ 689e8b9. Base: rafaelvcaetano/melonDS-android-lib master 431ab4b, which is also what upstream melonDS-android HEAD pins |
| `upstream-android/` | rafaelvcaetano/melonDS-android | master @ feab12e (2026-11-05) |
| `melonds-pr2776/` | melonDS-emu/melonDS `pull/2776/head` | 33969af ("squash", celerizer, 2026-10-07); `up/master` 497aa6c (2026-11-04) still has `// TODO: emulate actual IR comm` |
| `melonds-ir/` | DaveuRrr/melonDS-IR | master @ 9466718 (2026-08-09) |
| `phg/` | pret/pokeheartgold (sparse) | `asm/overlay_112.s`, `lib/asm/libirc.s`, used to verify the game-side timing |

Every one of the 25 WatermelonDS commits and both lib commits is authored by `Claude <noreply@anthropic.com>`, with `Co-Authored-By: Claude Opus 5.5` and `Claude-Session:` trailers. The code is AI-generated, so treat every claim in its comments and docs as unverified. I checked the important ones against the code and the decompilation below.

Upstream drift: between c42995c and upstream HEAD only 10 commits landed. The files the port touches changed trivially (`MelonInstance.cpp` +7/-1, `MelonDSAndroidJNI.cpp` 5 lines, `AndroidEmulatorManager.kt` 1 line), and the lib pointer is identical, so the core patch applies cleanly.

## 2. End-to-end path

### 2.1 Game side (verified in pret/pokeheartgold)

- The IR thread is `ov112_021E7398` (`asm/overlay_112.s` ~L3510–3525). In a loop it locks a mutex, calls `ov112_021E5B98` (one link poll), unlocks, then `OS_Sleep(4)`. So the game polls about every 4 ms of emulated time, which is about 4 polls per emulated frame.
- The poll calls `CARD_SpiWaitReadRange` (`lib/asm/libirc.s` L194–270). It selects the chip, writes command `0x01` with CS held, and reads the length byte.
  - If `len > 0xB9` it is treated as 0.
  - If `len == 0` it does one extra dummy read with CS released (AUXSPICNT `0xA002`, hold bit clear).
  - Otherwise it reads `len` bytes, dropping hold on the last one, and then XORs every byte with `0xAA` itself. So the bytes on the SPI and on the air are the obfuscated ones, which is why every implementation passes "still XOR'd" bytes.
- The timeout is `ov112_021E5AD0` (`asm/overlay_112.s` L285–328). It is only evaluated on a poll that returned nothing:
  ```asm
  bl OS_GetTick            ; now - lastValidRx (stored at _021FF9E0+0x30 by ov112_021E5B98 on each good packet)
  ... lsl #6 / _ll_udiv by 0x82EA   ; = OS_TicksToMilliSeconds
  mov r2, #0x64            ; 100
  sub/sbc ; bhs -> timeout (ov112_021E5A14(1))
  ```
  So the **100 ms deadline is confirmed**. It is measured in emulated ticks and runs from the last *valid* received packet. Each poll returns at most one packet, and the game checksums it as a whole: `ov112_021E5B28` checksums exactly `n` bytes. The transport must therefore deliver exactly one complete packet per poll. Partial or merged packets fail the checksum.

### 2.2 Core: NDSCartSlot → CartRetailIR (watermelon-lib)

- `src/NDSCart.cpp` L2042–2073, `NDSCartSlot::WriteSPIData`: each ARM9 write to AUXSPIDATA computes `SPIDataPos` and `islast` (hold bit clear) and calls `Cart->SPIWrite(val, pos, last)` **synchronously**. The return value becomes `SPIData`, which the game reads back after `8*(8<<speed)` cycles. This is the old melonDS SPI API. Upstream melonDS master has since moved to `SPISelect/SPITransmitReceive/SPIRelease`, as PR #2776 and melonDS-IR use.
- `src/NDSCart.cpp` L1128–1162, `CartRetailIR::SPIWrite`:
  ```cpp
  case 0x01: // read from the IR receiver: [length] [data...]
      if (pos == 1) return IRReceive();                 // calls Platform::IR_ReceivePacket once per transfer
      else { u32 index = pos - 2; return (index < IRRxLen) ? IRRxBuf[index] : 0; }
  case 0x02: // send over IR
      if (pos - 1 < IRBufferSize) IRTxBuf[pos - 1] = val;
      if (last) IRSend(pos < IRBufferSize ? pos : IRBufferSize);   // Platform::IR_SendPacket on CS release
      return 0;
  case 0x08: return 0xAA;   // ID (returned for all IR versions; PR #2776 limits it to the late version)
  ```
  `IRReceive` (L1164–1171) clamps the hook's return value to `[0, 0xB8]`. `IRSend` (L1173–1177) skips zero lengths.
- `src/NDSCart.h` L231–250: `IRBufferSize = 0xB8`, plus `IRRxBuf/IRRxLen/IRTxBuf`. These are deliberately **not** savestated; only `IRCmd` is.
- `src/NDSCart.cpp` L1112–1119, `CartRetailIR::Reset`: sets `IRRxLen = 0` and calls `Platform::IR_Reset(Header.GameCodeAsU32(), IRVersion, GetROM(), GetROMLength(), UserData)`. `Cart->Reset()` runs from `NDSCartSlot::SetCart` (L1751, at ROM insertion) and from `ResetCart` (L1834, on console reset).
- `src/Platform.h` L327–352 declares the hooks (see §3).

### 2.3 Frontend glue (WatermelonDS app)

- `app/src/main/cpp/pokewalker/PlatformIR.cpp` (28 lines): the three hooks forward to `pokewalker::ir::OnCartReset/OnGameSend/OnGamePoll`. **`userdata` is ignored** and a process-global singleton is used instead. Upstream's own hooks, such as `Net_SendPacket` at `PlatformAndroid.cpp` L558–568, cast `userdata` to `MelonInstance*`.
- `app/src/main/cpp/pokewalker/PokewalkerIR.cpp`:
  - L161–201: `State` is a global behind one `std::mutex lock`. It holds the config, `VirtualPokewalker`, `TcpLink`, `WalkerDevice`s, `GameTrace`, the ROM-check cache and the log file.
  - L532–549, `OnGameSend`: takes the lock and switches on the mode. Virtual → `walker.OnGameSend`. TCP → `tcp.Send`, preceded by `sleep_for(10ms)` when `data[0] == 0xF4^0xAA`. Off → return 0.
  - L551–569, `OnGamePoll`: takes the lock. Virtual → `walker.OnGamePoll`. TCP → `tcp.Receive` (blocking gap framing). Optionally logs every packet with an `fflush`.
  - L300–344, `Configure`: called from the UI and app threads. Under the same lock it opens the log, opens the EEPROM, and starts or stops the TCP listener.
- **TCP transport** (`TcpLink`, L43–159):
  - **Role:** the Android device is the **server**. It binds `INADDR_ANY:8081` (configurable), with `listen(…, 1)`, `SO_REUSEADDR`, and a non-blocking listen socket (L52–72). The peer (a walker emulator or bridge) connects to it.
  - **Accept:** lazy, only inside `Connected()`, which runs from the game's send/poll hooks (L81–85, L132–142). The newest peer wins, and the old client is closed silently. `TCP_NODELAY` is set on the accepted socket only, so it affects only Android→peer segments. Peer→Android framing depends on the peer having Nagle off.
  - **No thread.** Every socket operation runs on the emulator thread inside the hooks.
  - **Send** (L87–104): loops until every byte is written. On `EAGAIN` it `poll(POLLOUT, 20 ms)` and retries **forever**.
  - **Receive** (L108–126): one non-blocking `recv` of up to `maxLen`. If anything arrived, it keeps polling until 3500 µs pass with no new bytes (`kPacketGapUs`, L45). The gap is measured from the time *we read* the bytes, not from when they arrived. So every received packet blocks the emulator thread for at least 3.5 ms, longer if the peer trickles bytes (a byte-forwarding bridge sends 136 bytes over about 11.8 ms). Two packets already buffered in the socket are merged into one.
- **JNI and settings:**
  - `PokewalkerJNI.cpp` L36–46: `configure(mode, eepromPath, logPath, tcpPort, logPackets)` → `Configure`.
  - `PokewalkerNative.kt` L13–14: `external fun configure(...)`, on a separate `object` that loads the library itself.
  - `Pokewalker.kt` L67–98, `applySettings`: reads `pokewalker_ir_mode` ("off", "virtual" default, "tcp"), `pokewalker_tcp_port`, `pokewalker_log_packets` from default SharedPreferences.
  - `applySettings` is called from `MelonDSApplication.onCreate`, from `AndroidEmulatorManager.setupEmulator(startingGame=true)`, and from the settings listener in `PokewalkerPreferencesFragment.kt` L84–88.
  - UI: `res/xml/pref_pokewalker.xml` L84–110 (a ListPreference, an EditTextPreference for the port, and a log switch). `res/values/arrays.xml` (+12 lines) and 9 strings.
  - The IR setting is not part of upstream's `EmulatorConfiguration`/`SettingsRepository` flow.

## 3. Hook contract (WatermelonDS), as actually implemented

| Hook | Signature (watermelon-lib `Platform.h` L327–352) | Called from | Thread | Semantics |
|---|---|---|---|---|
| `IR_Reset` | `void IR_Reset(u32 gamecode, u32 irversion, const u8* rom, u32 romlen, void* userdata)` | `CartRetailIR::Reset` ← `SetCart` (ROM insert) and `ResetCart` (console reset) | **Not the emulator thread.** ROM load runs on the `Dispatchers.IO` coroutine via JNI `loadRom`. Reset runs on the JNI caller of `resetEmulation`, after it spin-waits for `isThreadReallyPaused` (`MelonDSAndroidJNI.cpp` L343–363) | Notification only. `rom` is borrowed and valid while the cart lives. On first insertion it is unencrypted; melonDS re-encrypts the secure area right after (`SetCart` L1756+). `rom` exists only for the Virtual walker's ROM check (commit 689e8b9) |
| `IR_SendPacket` | `int IR_SendPacket(const u8* data, int len, void* userdata)` | `SPIWrite` case 0x02 when `last` (CS released) | Emulator thread (`EmulatorThread` pthread, inside `nds->RunFrame()`) | `data` = `IRTxBuf`, **borrowed for the call only**, so the callee must copy. `len` is 1..0xB8. The return value is **ignored** by the core. The doc says "bytes accepted / negative on error". Must not block: any time spent here freezes emulated time and stalls audio and video |
| `IR_ReceivePacket` | `int IR_ReceivePacket(u8* data, int maxlen, void* userdata)` | `SPIWrite` case 0x01 at `pos == 1` (the length byte), once per poll transfer | Emulator thread | Callee writes into `IRRxBuf` (`maxlen` = 0xB8) and returns the count. **0 = nothing ready**, the normal case on about 99% of polls. Negative values are clamped to 0, and values over `maxlen` to `maxlen`. **Consume-on-read**: whatever is returned is gone, with no peek/commit. Expected to hold **at most one whole packet**. Must not block |

There is no hook for savestate load, rewind or pause. The core's IR buffers are transient, and a mid-transfer savestate simply drops the in-flight packet. That is fine, because each transfer is atomic within one emulated poll.

## 4. Timing, deadline, savestates, reset, fast-forward

### 4.1 How WatermelonDS handles the 100 ms deadline

It doesn't, explicitly. `docs/POKEWALKER.md` L153–157 and `pokewalker-tests/hgss_flow_test.cpp` (L6, L12, L159–190) only *model* the 100 ms deadline in a host test.

- **Virtual mode** is immune: `VirtualPokewalker::OnGameSend` builds the reply synchronously into `pending`, and the next poll, about 4 emulated ms later, returns it (`VirtualPokewalker.cpp` L1022–1093). Its own timeouts (`kSessionTimeoutMs = 3000`, `kPollGapResetMs = 1000`, L35–36) use wall-clock `nowMs()`.
- **TCP mode** relies on the peer replying fast enough in *wall* time while the game counts *emulated* time. The blocking 3.5 ms receive incidentally freezes emulated time while it waits, so the game never "sees" those 3.5 ms. That accident is no design.

### 4.2 What actually governs latency on melonDS Android (applies to our port)

- `emulate()` (`upstream-android/.../MelonDSAndroidJNI.cpp` L613–700) runs one whole frame (16.7 emulated ms) as fast as it can, then sleeps to the frame deadline. The game's four 4 ms polls per frame therefore happen in a burst of a few wall-ms, followed by about 10 ms with no polls.
- A packet arriving from the dongle waits in the queue for up to about one frame. A game TX leaves immediately.
- At 1x, a realistic DS→walker→DS round trip is under 40 ms against a 100 ms deadline: up to one frame of queueing, plus USB at about 1 ms each way, plus SIR airtime of about 11.8 ms for 136 bytes, plus walker processing, plus the 3.5 ms end-of-packet gap.
- **Fast-forward is the real risk.** `setFastForwardEnabled` (L514–538) sets `targetFps = 60*multiplier`, or turns the limiter off entirely when the multiplier is ≤ 0. At 4x the game's 100 ms becomes 25 wall-ms. When unlimited, it becomes a few ms. Real-walker sessions will fail. Neither WatermelonDS nor upstream handles this.
- **Below-1x devices** stretch the game's deadline, which is harmless for the game, but slow the DS side's replies in wall time. The real walker's own timeouts are wall-clock and undocumented. Worth logging if sessions fail on slow devices.
- **Pause** (menu or app background) freezes the game while the real walker keeps running, so the session is lost. This is unavoidable. Flush the queue on resume.

### 4.3 Savestates / rewind / reset in WatermelonDS

- **Reset / ROM load:** `IR_Reset` → `OnCartReset` (L398–429) resets the virtual walker session (`VirtualPokewalker::OnCartReset` L1007–1020). TCP mode does nothing: no socket drain, and the peer stays connected.
- **Savestate load / rewind:** no IR hook. In Virtual mode only, the `WriteNDSSave` tap (`PlatformAndroid.cpp` hunk → `OnSaveWrite`, L571–578) guesses a state load by spotting a full-save rewrite. That feeds the virtual walker's "transfer not saved" bookkeeping (commit d911f92). TCP mode does nothing, so stale bytes in the socket are delivered after a load.
- **Implication for a real walker:** loading a savestate taken before a completed stroll start or return desyncs the game from the walker's EEPROM, exactly as on hardware if you power off before saving. The emulator cannot fix this. A user-facing warning is the most we can do.

## 5. Code-quality findings (transport and core seam only)

Severity: H = will bite us / must not copy; M = notable; L = nit.

1. **H, `TcpLink::Receive` (L108–126):** it blocks the emulator thread for at least 3.5 ms per received packet, measures idle from read time rather than arrival time, and merges back-to-back buffered packets into one, which breaks the checksum. All of this happens while holding the global lock.
2. **H, `TcpLink::Send` (L87–104):** an unbounded retry loop on `EAGAIN`. A peer that stops reading hangs the emulator thread forever, with the lock held.
3. **H, `OnGameSend` (L543–544):** `sleep_for(10ms)` on the emulator thread under the lock before every `0xF4` (disconnect) packet. It is copied from melonDS-IR (`CartRetailIR.cpp`: `if ((u8)TxBuf[0] == 0x5E) Platform::Sleep(10000);`, where 0x5E = 0xF4^0xAA). It papers over the raw-byte stream having no packet boundaries. With framed IR_TX, the right fix is a minimum inter-packet idle enforced by the dongle (see §7.5).
4. **H, one global mutex** shared by the emulator-thread hooks (`OnGamePoll`/`OnGameSend`/`OnFrame`) and by UI-rate calls: `DeviceFrame` and `WidgetFrame` (walker screen animation), `StatusJson`, `Configure` (`bind`/`listen`/`fopen`), and step import. UI work can stall emulation (priority inversion, frame hitches) right when IR timing matters.
5. **M, `userdata` ignored and global state** (`PlatformIR.cpp`, `S()` L197–201): not instance-safe, and inconsistent with upstream's `Net_*` hooks.
6. **M, TCP port change ignored** while a listener is running: `Configure` L329–338 only starts when `!tcpRunning`.
7. **M, accept only happens during game polls.** The peer connects but nothing accepts until the game sends or polls. "Newest peer wins" silently kills an existing session. The listener is on `INADDR_ANY` with no authentication, so any LAN host can inject IR packets (low risk, but worth a line in the docs).
8. **M, no flush** on savestate load, rewind, reset (TCP) or resume.
9. **M, per-packet logging** does `__android_log_print` plus `fprintf` plus `fflush` on the emulator thread (L204–223, L235–246).
10. **M, `IR_Reset(rom, romlen)`** (lib commit 689e8b9) exists only to SHA-1 the whole ROM and overlays for a "copy check" (`RomCheck.cpp`, `OverlayHashes.inc`) on the load path. It leaks a frontend concern into the core API. Upstream would reject it, so drop it.
11. **L, core `IRBufferSize = 0xB8`** while libirc accepts lengths up to `0xB9`. Harmless, since walker packets are at most 136 bytes, but `0xB9` matches the game.
12. **L, `0x08` returns `0xAA`** for every IR version. PR #2776 returns it only for NTR-032 (late) carts.
13. **L, `IR_SendPacket`'s return value** is documented but ignored. Make it `void` or document that it is ignored.
14. **L, Kotlin/JNI hygiene:** a separate `PokewalkerNative` object that calls `System.loadLibrary` itself, settings outside `EmulatorConfiguration`, `applySettings` called from `Application.onCreate`, a ProGuard keep for the whole object. Also, upstream's `MelonDSAndroidCameraHandler` calls `GetMethodID` on every frame. Don't copy that pattern; cache the method ID.
15. **Repo hygiene (do not copy):** `.github/signing/pokewalker-release.jks` is a release keystore committed to the repo. There is also a second build flavour that reuses upstream's application ID.

The core `CartRetailIR` hunk itself is correct for the old SPI API. It matches libirc's framing: the length byte at pos 1, data from pos 2, the extra dummy read when the length is 0, and TX flushed on the hold-released last byte.

## 6. File-by-file port list

### 6.1 Core: `melonDS-android-lib` (needed)

| File | WatermelonDS hunk | Lines | Port? |
|---|---|---|---|
| `src/Platform.h` | IR hook declarations + docs (L327–352) | +27 | **Yes, reshaped**: two hooks (§7.1), drop `rom/romlen/gamecode/irversion`, ~+20 |
| `src/NDSCart.h` | `CartRetailIR` private: buffer const, RX/TX buffers, `IRReceive/IRSend` (L231–250) | +14 | **Yes** (optionally `0xB9`) |
| `src/NDSCart.cpp` | `Reset` clears `IRRxLen` (+ `IR_Reset` call); `SPIWrite` 0x01/0x02; `IRReceive`; `IRSend` (L1112–1177) | +35 −2 | **Yes**; drop or simplify the `IR_Reset` call (§7.1) |

Core total: about 70 lines, against old API `SPIWrite(val,pos,last)`. When the lib next rebases onto upstream melonDS (which has the `NDSCart/` split and the `SPISelect/SPITransmitReceive/SPIRelease` API), the same logic moves to `src/NDSCart/CartRetailIR.{h,cpp}`, with TX flushed in `SPIRelease` as PR #2776 and melonDS-IR do.

### 6.2 Android frontend: receiver end + transport seam (needed, mostly rewritten)

| WatermelonDS file | Size | Transport-relevant part | Our action |
|---|---|---|---|
| `app/src/main/cpp/pokewalker/PlatformIR.cpp` | 28 | all | **Rewrite** (~25 lines) into `PlatformAndroid.cpp`, next to `Net_*`: cast `userdata` → `MelonInstance*` → `irLink` |
| `app/src/main/cpp/pokewalker/PokewalkerIR.{h,cpp}` | 98 + 676 | `Mode`/`Config` (h L18–35), `TcpLink` (cpp L43–159, ~117), TCP part of `Configure` (L329–343), `OnGameSend`/`OnGamePoll` (L532–569). About 200 lines | **Do not copy.** Write a new `IrLink.{h,cpp}` (~120–150 lines): bounded RX queue, TX sink, flush, activity timestamp. If TCP is wanted later, reimplement it with a reader thread feeding the same queue and explicit framing |
| `app/src/main/cpp/pokewalker/PokewalkerJNI.cpp` | 218 | `configure` (L36–46) | **Replace** with ~3 JNI functions on `MelonEmulator` (~40 lines): `irPushPacket`, `irSetTxCallback`/`irAttach`, `irFlush` |
| `app/src/main/java/.../pokewalker/PokewalkerNative.kt` | 80 | `configure` | **Replace** with `external fun`s on `MelonEmulator.kt` (~10 lines) |
| `app/src/main/java/.../pokewalker/Pokewalker.kt` | 297 | `applySettings` mode/port (L67–98, ~30) | **Replace** with an `irLinkMode` setting in `SettingsRepository` / `EmulatorConfiguration` (~20 lines) |
| `.../ui/settings/fragments/PokewalkerPreferencesFragment.kt` | 655 | listener + port visibility (~15) | **Replace** with a small "Infrared" pref screen, or a section in `pref_system.xml` (~40 lines incl. XML) |
| `res/xml/pref_pokewalker.xml` | 157 | "Connection" category (L84–110) | Pattern only |
| `res/values/arrays.xml`, `strings.xml` | +12, +283 | mode arrays, 9 strings | Rewrite for Off/USB dongle (~15 lines) |
| `app/CMakeLists.txt` | +13 | `PlatformIR.cpp`, `PokewalkerIR.cpp` | +1–2 lines (`IrLink.cpp`) |
| `MelonDSApplication.kt`, `AndroidEmulatorManager.kt` | +4, +6 | `applySettings` calls | Not needed; config flows through `EmulatorConfiguration` |
| `app/proguard-rules.pro` | +3 | keep `PokewalkerNative` | Add a keep for the Kotlin IR bridge's JNI-called static method |

New code we must write (not in WatermelonDS):

- `MelonInstance.{h,cpp}`: own an `IrLink`, and call `irLink.flush()` in `reset()`, `loadRom()`, `loadState()` and `loadRewindState()`. About 15 lines.
- `MelonDSAndroidJNI.cpp`: clamp fast-forward while `irLink.recentlyActive()`, and flush on `resumeEmulation`. About 15 lines.
- Kotlin `ir/` package: dongle manager (usb-serial-for-android, COBS codec, IDENTIFY/"MDSW" check, frame dispatch), `device_filter.xml`, a `USB_DEVICE_ATTACHED` intent filter, and the `usb.host` feature (`required=false`). About 300–400 lines.

### 6.3 Virtual-walker-only or unrelated (exclude)

- **Native** `app/src/main/cpp/pokewalker/`: `VirtualPokewalker.{cpp,h}` (1547+240), `WalkerDevice.{cpp,h}` (1383+235), `EepromStore` (207+63), `GameTrace` (292+65), `RomCheck` (324+60) + `OverlayHashes.inc` (290), `PixelFont` (107+26), `PwProtocol` (126+87), `PwText` (250+30), `PwCommon.h` (158).
- **Frontend hooks:**
  - `MelonInstance.cpp` hunks: the `OnFrame` screen trace, `SetTouching`, the cheats `Note`.
  - `PlatformAndroid.cpp` hunks: the core-log tee into the walker log, and the `OnSaveWrite` tap in `WriteNDSSave`.
- **Kotlin:**
  - Everything in `app/src/main/java/me/magnum/melonds/pokewalker/` except the bits listed above (about 14k lines: route map, music, widget, wallpaper, Health Connect, step ledger, device activity, ...).
  - `EmulatorActivity.kt`/`EmulatorViewModel.kt`/`RomPauseMenuOption.kt` ("send home" key macro), `SettingsActivity.kt` entry point.
- **Build and packaging:** the `pokewalker` flavour, its strings, the manifest additions (widget, tile, wallpaper, health permissions), `GitHubPokewalkerModule.kt`, CI workflows, the signing keystore, `docs/POKEWALKER.md`, `pokewalker-tests/` (about 6k lines).
  - `pokewalker-tests/cart_ir_test.cpp` (202 lines) is a useful **reference** for a host test that drives `CartRetailIR::SPIWrite` the way the DS does, but it links the virtual walker.

## 7. Recommended interface for a `Serial` (USB dongle) mode

### 7.1 Core seam (lib): two Net_*-style hooks

```cpp
// Platform.h -- infrared transceiver of IR carts (CartRetailIR)
// Bytes are exactly as on the air (the game's XOR-0xAA obfuscation intact).
// Both are called on the emulator thread from inside an SPI transfer: they must not block.

/// The game transmitted one complete IR packet. `data` is only valid during the call.
void IR_SendPacket(const u8* data, int len, void* userdata);

/// The game polls the IR receiver. Copy at most one complete packet (len <= maxlen) into
/// `data` and return its length, or 0 if none is pending. The returned packet is consumed.
int IR_RecvPacket(u8* data, int maxlen, void* userdata);
```

- It mirrors the existing `Net_SendPacket` / `Net_RecvPacket` pair in shape, threading and "0 = nothing" semantics. That is the strongest upstream precedent for "frontend-owned I/O behind the core".
- **No `IR_Reset` hook is needed.** The frontend itself calls every path that should flush: `nds->Reset()`, `SetNDSCart`, `DoSavestate` load, rewind and resume. If Rafael prefers a core-driven notification, the most to accept is `void IR_Reset(void* userdata)`, with no ROM or gamecode. The frontend can read the header itself if it ever needs to.
- Keep the WatermelonDS `CartRetailIR` logic. Optionally move consumption to the hold-released last byte (peek at pos 1, commit at `last`) to match PR #2776's `DropPacket`-on-release. That is not required, because libirc always reads the full length in the same transfer.
- Guard against null `userdata`: `CartLoader.cpp` L72 creates carts with `nullptr` userdata for metadata parsing. It never resets them, but be defensive.

### 7.2 Frontend native: `IrLink`, owned by `MelonInstance`

```cpp
class IrLink {
public:
    // emulator thread (from Platform hooks)
    void onGameSend(const u8* data, int len);   // copy -> txSink (non-blocking), stamp activity
    int  onGamePoll(u8* out, int maxLen);       // pop one packet or return 0; never blocks
    // any thread
    void pushReceived(const u8* data, int len); // from JNI (Kotlin reader thread)
    void flush();                                // reset / ROM load / state load / rewind / resume / detach
    void setTxSink(std::function<void(const u8*, int)> sink); // null = drop (link off)
    bool recentlyActive() const;                 // any TX/RX in the last ~2 s (atomic timestamp)
};
```

- **RX queue:** a `std::deque<std::vector<u8>>` capped at about 4–8 packets, dropping the oldest (PR #2776 uses 8). A plain `std::mutex` is fine because contention is about 10 packets/s and the critical sections are a memcpy. Use a lock-free SPSC ring if you want strict non-blocking. Optionally also drop packets older than about 500 ms wall time at poll time, so a pause, hitch or ANR never feeds the game stale replies.
- **No 3.5 ms gap logic in native.** The dongle already delimits packets by line idle (`gap_us` = 3500 by default) and sends one `IR_RX` frame per packet. One frame equals one `pushReceived` call, which equals one poll result.
- **TX sink = JNI callback.** At attach time, cache a `GlobalRef` to the Kotlin bridge class plus a static `jmethodID onIrTransmit([B)V`. In `onGameSend`: `getCurrentThreadEnv()` (the emulator thread is already JVM-attached through `JniEnvHandler`), `NewByteArray`/`SetByteArrayRegion`, `CallStaticVoidMethod`, `DeleteLocalRef`, then clear any pending exception. The Kotlin side must only enqueue (`Channel.trySend`) and never write to USB on this thread.
  - An equivalent alternative avoids JNI calls on the emulator thread entirely: a native TX queue plus a Kotlin writer thread blocking in `external fun irAwaitTx(timeoutMs): ByteArray?`. Either is fine; the callback matches the brief and the camera precedent.
- **Fast-forward clamp:** in `emulate()`, if `irLink.recentlyActive()` while fast-forward is on, use `limitFps = true; targetFps = 60`. Optionally emit a one-time UI message through `eventMessenger`. This is the only defence against §4.2.
- **Flush points:** `MelonInstance::reset()`, `loadRom()`, `loadState()`, `loadRewindState()`, JNI `resumeEmulation`, and dongle detach.

### 7.3 JNI surface (on `MelonEmulator`, like upstream's other natives)

```kotlin
external fun irAttach(bridge: Class<*>)          // or a static method resolved by name; enables TX sink
external fun irDetach()                          // TX sink = null, flush
external fun irPushPacket(packet: ByteArray, len: Int) // one decoded IR_RX payload, ts stripped
```

The mode itself (Off / USB dongle, and TCP later) lives in Kotlin `SettingsRepository`/`EmulatorConfiguration`. Native has no mode switch: no sink attached means off. That is a deliberate simplification over WatermelonDS's native `Mode` enum.

### 7.4 Kotlin dongle owner

- usb-serial-for-android (MIT, compatible with GPL-3) `CdcAcmSerialDriver` + `SerialInputOutputManager`. Raise its thread priority for low latency.
- COBS stream decoder → dispatch by type:
  - `0x81 IR_RX`: drop the 4-byte `ts_us`, then `irPushPacket`.
  - `0x82` IDENTIFY_RESP: check `"MDSW"`, proto 1, caps bit0.
  - `0x84 TX_DONE`: metrics only.
  - `0x8E LOG` / `0x8F ERROR`: logcat or UI.
- The writer coroutine takes from the TX channel, builds `0x01` + payload, COBS-encodes, appends `0x00`, and calls `port.write(frame, ~50 ms)`.
- On open: DTR on, `IDENTIFY`, and optionally `SET_CONFIG gap_us`. Note that `RAW_MODE` is unnecessary and must never be sent from the app.
- Attach UX: `device_filter.xml` on `0x303A:0x4001` (provisional PID) plus the `USB_DEVICE_ATTACHED` intent filter. Handle permission, detach → `irDetach()`, and reconnect.

### 7.5 Dongle-firmware requirements this design relies on

- One `IR_RX` frame per IR packet, which is already specified. Make sure single-byte walker adverts (`0xFC`, sent as `0x56` on air) are forwarded as 1-byte frames. The game accepts length-1 packets only as adverts.
- **TX queueing with a minimum idle gap** (at least `gap_us`) between consecutive `IR_TX` packets, and between the end of RX and the start of TX. The game can emit its next packet, for example `0xF4` disconnect, before the previous one has finished on the air. This replaces WatermelonDS's and melonDS-IR's 10 ms sleep hack. `protocol.md` doesn't state this explicitly yet; suggest adding it.

### 7.6 Comparison with PR #2776 and melonDS-IR, and which seam to align with

| | WatermelonDS | PR #2776 (celerizer) | melonDS-IR (DaveuRrr) | Recommended |
|---|---|---|---|---|
| Core API | Platform hooks `IR_Reset/IR_SendPacket/IR_ReceivePacket` | Core-internal `NDSCart::IRLink::{Reset,SendByte,EndPacket,Receive,ReceivedByte,DropPacket}`, no `userdata`, global state | Platform `IRSendPacket/IRReceivePacket` + `IRReadTimeOutUs/IRSendDelayUs/IRClose` (`u8` return, `char*`) | Platform `IR_SendPacket/IR_RecvPacket` (Net_* shape) |
| Granularity | packet | byte in, packet out (`'B'`…`'T'` records) | partial packets; the core busy-waits to assemble them | packet |
| Transport location | frontend | **inside the core** (BSD/Winsock TCP client to 127.0.0.1:43690, 8-byte timestamped records) | frontend (Qt TCP / ENet UDP / QSerialPort) | frontend (Kotlin) |
| Blocking | intended non-blocking; TCP impl blocks | non-blocking | **core spins** `while (GetUSCount() - last < readTimeout)` and `Platform::Sleep` | non-blocking |
| RX queue | none (gap-framed on read) | deque, max 8, drop oldest; peek + `DropPacket` on `SPIRelease` | none | bounded deque + flush |
| SPI API | old `SPIWrite(pos,last)` | new `SPISelect/TransmitReceive/Release` | new | old now; new on lib rebase |
| Merge status | fork | open, author-labelled "[no merge yet]" | fork | — |

- PR #2776 has the best *semantics*: a packet queue, explicit end-of-packet markers, drop-after-read, and reset clears. It has the least mergeable *placement*: raw sockets and global state in the core. No other core subsystem in melonDS does OS networking itself; even LAN/WiFi goes through Platform hooks and frontend net code.
- Its six `IRLink` functions collapse exactly onto the two packet hooks: `Receive`+`ReceivedByte`*n+`DropPacket` = `IR_RecvPacket`, and `SendByte`*n+`EndPacket` = `IR_SendPacket`. The Stepdad record protocol (per-byte timestamps derived from `IRCharTime`) can be produced in a frontend from a whole packet. So a packet-level Platform seam is a strict superset that would let PR #2776's Stepdad link, melonDS-IR's TCP/UDP/serial links and our dongle all live in frontends.
- **Recommendation:** align with the Platform-hook, packet-level seam (WatermelonDS's shape, trimmed, with Net_* naming and semantics). Borrow PR #2776's queue semantics (bounded, drop-oldest, flush on reset) in the frontend `IrLink`. Keep the lib diff to about 70 lines so that if upstream melonDS merges a different IR API, migrating is a rename plus moving the hunk to `NDSCart/CartRetailIR.cpp`.
- For melonDS-android upstream (Rafael), present it as a generic "IR accessory link (USB dongle)" feature: no Pokéwalker branding in the core, settings in `EmulatorConfiguration`, and JNI on `MelonEmulator`. That is more acceptable than WatermelonDS's parallel `PokewalkerNative`/SharedPreferences stack.

## 8. Licensing and attribution

- **Licences:** melonDS core (and melonDS-android-lib) is GPL-3.0-or-later. melonDS-android is GPL-3.0 (`LICENSE`). WatermelonDS files carry "GPL-3.0-or-later, see PwCommon.h" (`PwCommon.h` L1–11, with no named copyright holder). The lib commits add no header, so they inherit melonDS's "Copyright 2016-2026 melonDS team" GPL header. usb-serial-for-android is MIT. All of these are compatible with our GPL-3 fork.
- **What we would actually reuse:** only the about 50-line `CartRetailIR` 0x01/0x02 hunk and the hook idea. This logic is near-identical across WatermelonDS, melonDS-IR and PR #2776, because libirc's framing dictates it. Still, credit it in the commit message and a code comment, e.g. "IR SPI command handling based on silver115/WatermelonDS melonDS-android-lib (GPL-3.0-or-later); cf. DaveuRrr/melonDS-IR and melonDS PR #2776". Keep the GPL header on any file derived from WatermelonDS.
- **AI-generated provenance:** silver115's commits are authored by an AI agent. The copyrightability of purely AI-generated code is unsettled. Treating it as GPL-3.0-or-later as published by silver115 is the safe assumption, and costs nothing given our licence.
- Do not reuse WatermelonDS's signing keystore, flavour or application IDs, or Pokémon names, strings or assets.

## 9. Open items / caveats

- The real Pokéwalker's own reply timeouts are still unmeasured. The 1x latency budget looks comfortable, but test at 1x first and log `TX_DONE` → `IR_RX` deltas.
- Should packets that arrive while the game isn't polling (outside the Pokéwalker menu) be dropped immediately? A staleness cap (about 500 ms) plus a flush on resume handles this without knowing the game state.
- Decide whether to keep a TCP mode at all. If yes, implement it in Kotlin (or a native reader thread) feeding the same `IrLink` queue. Never put it on the emulator thread, and prefer a framed protocol (length-prefixed or PR #2776's records) over idle-gap framing.
