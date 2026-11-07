# Pokéwalker IR protocol: facts resolved from the decompilations

Compiled 2026-11-06. All statements below describe behaviour in my own words. Short code
fragments appear only as citations.

## Sources (read only, nothing built or run)

Cloned under `/tmp/claude-1000/-var-home-josh-projects-radio/f4df7dee-d40b-4349-9c44-1cdb3790ac1f/scratchpad/src2/`:

| Tag | Repo | Commit | Files used |
|---|---|---|---|
| **PW** | github.com/lumirth/pw (walker firmware reconstruction, H8/38606) | 6dc7bc0 | `src/support/ir.c`, `include/protocol.h`, `include/support/ir.h`, `include/support/ir_state.h`, `include/records.h`, `include/eeprom_map.h`, `src/startup/h8_resetprg.c`, `src/application/pw_buzzer.c` |
| **PHG** | github.com/pret/pokeheartgold (sparse) | e1d5a46 | `asm/overlay_112.s` (the Pokéwalker IR link layer and session logic, not yet decompiled to C), `lib/asm/libirc.s` (cart SPI IR transport) |
| **PWC** | github.com/mamba2410/picowalker-core (+ picowalker drivers) | 77a0669 | `src/ir/ir.c`, `src/ir/actions.c`, `picowalker/src/drivers/ir/rp2xxx_uart.c` |

GBATEK was not needed: both decomps agree on every point GBATEK covers.

Naming: PHG function names are the pret placeholder names (`ov112_021Exxxx`). The meanings I give them come from reading the code. PW names are the reconstruction's own.

---

## 1. Handshake byte layout

### 1.1 Beacon 0xFC
- **Only the walker sends it.** It is a single bare byte, 0xFC (0x56 on the wire after XOR), with no header and no checksum.
  - PW `ir.c:208-224` (`IrBegin`): when the walker enters IR mode (the user picks "Connect"), it records its local random token, sets phase PROBING, and transmits 0xFC immediately.
  - PW `ir.c:344-368`: in PROBING, whenever more than 3200 Timer W ticks pass with no received byte, the walker waits a random 0–15 × 96 ticks and then sends 0xFC again (see §3 for timing).
- The game never transmits 0xFC. In PHG `overlay_112.s`, nothing in the link layer sends it. The game only reacts to it:
  - `ov112_021E5A84` (`overlay_112.s:235-270`) accepts a 1-byte frame only when it is 0xFC and the link is not yet connected.
  - The 0xFC case `_021E5C1A` (`overlay_112.s:464-525`) answers with 0xFA.
- Walker-to-walker: if a walker that is still PROBING receives a bare 0xFC, it answers with its own 0xFA (arg 2) (PW `ir.c:375-393`). This does not apply to the DS link.

### 1.2 0xFA connect request (DS to walker)
Packet = 8 bytes, header only, no payload:

| Offset | Value |
|---|---|
| 0 | 0xFA |
| 1 | **0x01** (the game's "extra" byte; set by `ov112_021E5D5C(1)` at `overlay_112.s:3549-3550`, used for every packet the game sends except where a call site overrides it) |
| 2..3 | checksum, little-endian |
| 4..7 | **the DS's random 32-bit value. Not zero.** |

- The random value goes in the **header session field**, and there is **no payload**.
  - PHG `_021E5C4E`/`_021E5C6C` (`overlay_112.s:483-525`) calls the packet builder `ov112_021E59B4` with payload pointer 0, length 0, command 0xFA, extra = the configured byte (1), and session = the local random word at state+0x20.
- The game's "random" is the low 32 bits of `OS_GetTick()`, captured at link init (`ov112_021E5964`, `overlay_112.s:75-101`, which stores it at +0x20 and +0x04).
- The walker accepts 0xFA with arg 1 **or** 2 (PW `ir.c:430-457`). Any other arg makes the walker abort with "rejected".
- The walker does not look at the payload length of 0xFA.
- The walker acts on 0xFA only while it is in PROBING. If 0xFA arrives in any later phase, the walker re-enters PROBING and re-beacons (PW `ir.c:440-451`). So a stray 0xFA mid-session resets the handshake.

### 1.3 0xF8 connect reply (walker to DS)
8 bytes, header only: `F8 02 ckL ckH  T0 T1 T2 T3`.
- `T` is the **walker's own random token**, not the XOR.
  - In PW `ir.c:434-438`, `SendPacket(0, 0xF8, 2)` runs *before* `sessionToken = received ^ local`. At that moment `sessionToken` still equals `localHandshakeToken` (set in `IrBegin`, `ir.c:212-213`, from `g_state.randomState`).
- Extra = 0x02 (`IR_WALKER_PARAMETER`, `protocol.h:9`).
- The game handles 0xF8 in `_021E5CD0` (`overlay_112.s:557-583`):
  - It is accepted only if the game has just sent 0xFA (internal state 2).
  - The game stores the walker's extra byte, sets session = local random XOR the received header session, marks the link connected, and calls the "connected" callback `ov112_021E6A6C`.
  - That callback rejects the session (error 0x0C, disconnect) if the walker's extra byte is 0 or greater than 2 (`overlay_112.s:2336-2356`).

### 1.4 Session ID derivation
- **session = DS_random XOR walker_random, byte for byte, over header bytes 4..7.**
  - Walker side: PW `ir.c:437-438`.
  - Game side: `eor` of the two words at `overlay_112.s:569-572`.
- Byte order does not matter.
  - The walker (big-endian H8) and the game (little-endian ARM) each load the 4 bytes as a native u32. XOR and equality on a native word are the same as bytewise XOR and equality.
  - Both sides compare the 4 bytes for exact equality (PW `ir.c:413,422`; PHG `overlay_112.s:440-444`).
  - walkerctl's "LE int, XOR, LE bytes" approach is therefore correct.

### 1.5 Which session ID later packets carry
- Every packet after the handshake carries the XOR session, **in both directions**. This includes 0xF4 and the walker's own replies: the walker's `SendPacket` always writes the current `sessionToken`, `ir.c:97`.
- Session check exemptions differ between the two sides:
  - **Walker:** commands **< 0xF8** must carry the correct session *and* arrive after the handshake (phase ≥ 3). Otherwise they are silently dropped (PW `ir.c:421-428`). So **0xF0 and 0xF4 need the session**. 0xF8, 0xFA, 0xFC and **0xFE bypass both checks**.
  - **Game:** commands **< 0xF0** need the session and a connected link (PHG `overlay_112.s:429-444`).
- GBATEK's "except F8h and up" matches the walker side exactly.

### 1.6 Complete DS-side sequence (what HGSS does)
1. Walker: `FC`
2. DS: `FA 01 ck ck R0 R1 R2 R3`. The game sends this within ≤ 4 ms of polling the beacon.
3. Walker: `F8 02 ck ck W0 W1 W2 W3`, sent about 0.15–0.3 ms after the 0xFA ends (§3).
4. DS: `20 01 ck ck S0..S3`, sent immediately from the connected callback.
   - `ov112_021E6A6C`: for the walk/identity operations it goes to `_021E6BAA` (`overlay_112.s:2494-2501`), which sends command 0x20, extra 1, empty payload.
5. Walker: `22 02 ck ck S0..S3 + 0x68-byte status`.
6. The DS continues with the operation. On finish or error it sends `F4 01 ck ck S0..S3`.

---

## 2. Checksum

### 2.1 Algorithm, identical in both implementations
- Walker: PW `ir.c:14-34` (`PacketChecksum`).
- Game: PHG `ov112_021E5900` (`overlay_112.s:9-35`).

How it works:
1. Start with `sum = 2`, held in a 32-bit accumulator.
2. For each byte at index i over the whole packet (header + payload, as many bytes as are sent or received): add `byte << 8` if i is even, or `byte` if i is odd. This is a sum of big-endian 16-bit words. With an odd length, the last byte counts as a high byte.
3. Fold once: `f = (sum >> 16) + (sum & 0xFFFF)`.
4. Fold again: `f = f + (f >> 16)`.
5. Result: `f & 0xFFFF`. There is **no final inversion**.

Evidence:
- The game's fold is explicit at `overlay_112.s:24-31`: mask to 16 bits, add the high half, add the high half again, mask.
- The walker writes the same thing using 16-bit `uint`. That the two devices interoperate confirms the walker's `uint` is 16-bit.

### 2.2 Inputs and storage
- Computed over **plain (un-XORed) bytes**, with **checksum bytes 2..3 set to zero** first.
  - Walker TX: `ir.c:98-104`. Walker RX: `ir.c:397-400`.
  - Game TX: `overlay_112.s:121-136`. Game RX: `ov112_021E5B28`, `overlay_112.s:348-364`.
- XOR 0xAA is applied after the checksum, byte by byte:
  - Walker: `IrTransmitByte`, `ir.c:146-151`. The walker de-XORs on receive at `ir.c:334-335`.
  - Game: `overlay_112.s:144-152` on TX. The cart RX helper in `libirc.s` de-XORs on receive (`CARD_SpiWaitReadRange`, the `eor r0, r0, #0xaa` loop at `libirc.s:260`).
- **Stored little-endian**: byte 2 = low byte, byte 3 = high byte.
  - Walker `ir.c:103-104`; game `overlay_112.s:137-139`.

### 2.3 GBATEK seed 2 vs Dmitry seed 0: resolved, the seed is 2
- Both firmwares hard-code 2: PW `ir.c:16` and PHG `overlay_112.s:12` (`mov r5, #2`).
- picowalker-core also uses seed 2 (PWC `src/ir/ir.c:123`).
- A seed of 0 produces checksums that are exactly 2 too small (modulo the fold). That accounts for Dmitry's "almost, but not perfectly correct".

### 2.4 Worked test vectors
Plain bytes are shown first, then the bytes on the wire after XOR 0xAA. I verified each one against walkerctl's own `build_packet`/`checksum`/`session_from` (imported read-only with `python3 -B`), and each matched.

Assume DS random bytes `12 34 56 78` and walker random bytes `AB CD EF 01`. (In walkerctl's little-endian int convention these are `0x78563412` and `0x01EFCDAB`.)

| Packet | Plain (hex) | Wire (hex) | Checksum |
|---|---|---|---|
| FA connect request | `fa 01 b0 62 12 34 56 78` | `50 ab 1a c8 b8 9e fc d2` | 0x62B0 |
| F8 connect reply | `f8 02 d4 92 ab cd ef 01` | `52 a8 7e 38 01 67 45 ab` | 0x92D4 |
| session = XOR | `b9 f9 b9 79` | | |
| 20 identity request | `20 01 76 93 b9 f9 b9 79` | `8a ab dc 39 13 53 13 d3` | 0x9376 |
| F4 disconnect | `f4 01 77 67 b9 f9 b9 79` | `5e ab dd cd 13 53 13 d3` | 0x6777 |
| 24 ping, session 0 (existing walkerctl vector) | `24 01 03 24 00 00 00 00` | `8e ab a9 8e aa aa aa aa` | 0x2403 |
| 0C read 2 bytes at 0xCE8A (watts) | `0c 02 02 50 b9 f9 b9 79 ce 8a 02` | `a6 a8 a8 fa 13 53 13 d3 64 20 a8` | 0x5002 |
| fold-carry check: `ff ff 00 00 ff ff ff ff` + 0x80 × `ff` | header `ff ff 02 00 ff ff ff ff` | | 0x0002 (both folds carry) |
| 22 reply with payload bytes 00..67 | header `22 02 11 fc b9 f9 b9 79` | | 0xFC11 |

Hand check for FA: 0xFA01 + 0x0000 + 0x1234 + 0x5678 + 2 = 0x162AF. Folding gives 0x0001 + 0x62AF = 0x62B0, stored as `b0 62`.

---

## 3. Timing

### 3.1 Walker clock basis
- The walker's IR protocol clock is Timer W, started in `IrHardwareStart` (PW `ir.c:170-174`) with clock-select bits CKS = 1xx. pw's buzzer driver uses the same source and states it runs at **32 768 watch-clock ticks/s** (PW `pw_buzzer.c:57,162-167`; `pw_builtin.c:4`). So **1 tick = 30.52 µs**.
- Caveat: that rate is the reconstruction's own statement. If CKS = 1xx were φw/4 instead, every walker figure below would be 4× longer.
- Two things support 32 768 Hz:
  - The game's 100 ms deadline (§3.3) matches the walker's 97.7 ms idle limit almost exactly.
  - The buzzer pitch table then lands in a sane 134 Hz–1.4 kHz range.
- **Cheap confirmation:** run `walkerctl sniff` while the walker beacons. Consecutive 0x56 beacons should be about 98–142 ms apart.

Constants: PW `ir.c:187-193`.

| Item | Ticks | Time at 32 768 Hz | Citation |
|---|---|---|---|
| End-of-packet idle gap (RX frame closes when idle is **> 4** ticks) | >4 | about 122–153 µs, i.e. ~1.4–1.8 byte times at 115200 | `ir.c:188,340-343` |
| Inactivity limit | >3200 (0xC80) | **97.7 ms** | `ir.c:189,344` |
| Retry jitter before re-beacon | (rand & 15) × 96 | 0–43.9 ms (busy-wait, **RX blind**) | `ir.c:192-193,356-360` |
| Max timeouts in PROBING | 20 | — | `ir.c:190,345-347` |
| Max checksum failures per session | 20 (the 20th aborts) | — | `ir.c:191,401-410` |
| Post-TX guard (after TEND, before resuming RX; drains 1 RX byte) | 2 | 61 µs | `ir.c:113-120` |

### 3.2 Walker behaviour
- **Beacon interval:** the first 0xFC is sent at once on entering IR mode. After that, one beacon goes out per idle timeout: 97.7 ms of silence, then a 0–44 ms random wait, giving a period of about **98–142 ms**.
- **How long it waits for the DS:**
  - 20 timeouts are allowed in PROBING. That means 20 beacons over about **1.95–2.8 s (typically ~2.4 s)**, then the walker gives up with "no response" (`IR_RESULT_NO_RESPONSE`).
  - The counter is not reset by unrelated received bytes.
- **Blind windows:** during the jitter busy-wait the walker does not service SCI3, so bytes arriving then are lost or overrun. A 0xFA has the best chance if it arrives soon after a beacon, within the following ~97 ms.
- **Reply latency:**
  - The walker replies as soon as it has seen > 4 idle ticks after our last byte (~0.12–0.15 ms) and finished processing.
  - For 0xF8 and 0x26 that adds well under 1 ms.
  - For 0x22 the walker first performs EEPROM writes (§4.3), so expect roughly 5–20 ms (M95512 page write ≤ 5 ms each; estimate, not measured).
- **Inter-byte timing:** the walker transmits back-to-back with no inter-byte idle (`IrTransmitByte` polls TDRE, `ir.c:146-151`). Our dongle must also transmit a packet contiguously. **Any idle > ~120 µs inside a packet splits it**, and the walker then sees two bad-checksum fragments.
- **After the handshake (phase ≥ 3):** a single 97.7 ms silence ends the session with no retry (`ir.c:346-354`). The result is `CONNECTION_ERROR` if anything had been received, otherwise `NO_RESPONSE`.
  - The reference point is reset after every reply the walker sends (`ir.c:1144-1145`) and on every received byte (`ir.c:336`).
  - So **the DS must start its next packet within ~97 ms of the end of the walker's previous reply**.
- **The walker never retransmits a reply.** A bad-checksum packet is dropped silently (up to 19 per session); the 20th aborts.

### 3.3 Game behaviour
- The IR thread `ov112_021E7398` polls the cart every **4 ms** (`OS_Sleep(4)`, `overlay_112.s:3511-3530`).
- **Reply deadline: 100 ms.**
  - `ov112_021E5AD0` (`overlay_112.s:285-329`) runs only on polls that return nothing, and only while connected or while waiting for 0xF8.
  - It measures time since the **last valid received packet**: `(now − t_last) × 64 / 33514` ms ≥ `0x64`, at `overlay_112.s:300-313`.
  - On expiry it tears the link down **without** sending 0xF4 (`ov112_021E5A14(1)`) and the thread reports error 2.
- **The game does not resend requests.** Its only "retry" is to reset after a timeout and answer the walker's next 0xFC with a new 0xFA (beacon case, `overlay_112.s:483-525`).
  - While it is waiting for 0xF8 (flag at +0x24), further beacons are ignored until the 100 ms timeout clears that flag.
- **A bad checksum while connected** sets an error flag (`ov112_021E5938`). The flag suppresses delivery of further data packets to the application (`overlay_112.s:584-591`), so in practice the session dies at the 100 ms timeout.
- The cart SPI transfers use 0x32 wait cycles, or 0 once SPI command 0x08 returns 0xAA (`overlay_112.s:3557-3563`). That timing applies only to the cart; it is irrelevant for an IR-only host.

### 3.4 Practical values from picowalker (interoperates with a real HGSS)
- Packet-end idle: **3742 µs** byte timeout (`picowalker/src/drivers/ir/rp2xxx_uart.c:31-33`; `picowalker_structures.h:161`).
- First-byte wait: 50 ms (driver) or 200 ms (`PW_IR_READ_TIMEOUT_US`).
- MAX_ADVERTISING_PACKETS 20 (PWC `ir.h:77`), which matches the real walker.
- A 3.7 ms end-of-packet threshold is fine for picowalker, which plays the walker side and talks to a DS that replies ≥ 4 ms later.
- For our dongle the risk is different: our own TX echo plus the walker's reply, which starts ~150 µs later, could merge into one frame. See fix F3 in §7.

---

## 4. Identity request 0x20 and reply 0x22

### 4.1 Request
- Format: `20 01 ck ck S0..S3`, with an **empty payload**. Sent by the game at `overlay_112.s:2494-2501` and `2502-2510`.
- The walker ignores any payload on 0x20.

### 4.2 Reply
- Format: `22 02 ck ck S0..S3` + **0x68 (104) bytes**. The payload is the walker's `DeviceStatus` record:
  - layout: PW `include/records.h:28-54`;
  - offset asserts: `records.h:56-69`;
  - sending: `ir.c:630-641`.
- The game copies exactly 0x68 bytes and then byte-swaps the u32 at +0x64 (`_021E7076`, `overlay_112.s:3125-3151`). That swap is direct proof that totalSteps is **big-endian** on the wire.
- The game itself writes +0x60 (RTC) big-endian when building its own status payloads (`ov112_021E5E48`, `overlay_112.s:776-812`).
- Fields whose pw name ends in `Le` are little-endian; the walker forwards them opaquely in the game's byte order. Other multi-byte fields are big-endian.

| Off | Size | Field (pw name) | Notes |
|---|---|---|---|
| 0x00 | 4 LE | consoleCompatibilityLe | Game-defined compatibility word; the walker treats it as opaque |
| 0x04 | 4 LE | pokemonCompatibilityLe | The game compares this with its save during walk-end checks (`overlay_112.s:2665-2676`, in the walk-end request path `_021E6C8E`) |
| 0x08 | 2 LE | gameVersionLe | |
| 0x0A | 2 LE | pokemonGameVersionLe | The game compares `>>2` of this (`overlay_112.s:2679-2690`) |
| 0x0C | 4 LE | trainerIdLe | Paired trainer's ID. TID = low 16 bits, SID = high 16 bits (Gen 4 convention; inference). The game compares the full u32 (`overlay_112.s:2650-2662`) |
| 0x10 | 40 | deviceId | Walker unique identity (stored at EEPROM 0x0083/0x0183; also returned by 0x2A) |
| 0x38 | 16 | receivedEvents | Event-receipt bitmap |
| 0x48 | 18 | trainerNameData | First 16 bytes = trainer name, 8 Gen-4-encoded u16 characters (LE, game charset); the last 2 bytes are preserved and unused |
| 0x5A | 1 | receiptIndex | |
| 0x5B | 1 | flags | bit0 registered (paired), bit1 hasPokemon (on a walk), bit2 generatedPokemon, bits3..7 rolloverHour. The game tests bit0 and bit1 (`overlay_112.s:2590-2600, 2618-2648`) |
| 0x5C | 1 | peerProtocol | Must be equal between peers |
| 0x5D | 1 | consoleProtocolLevel | The game requires walker level ≤ its own (`overlay_112.s:2694-2701`) |
| 0x5E | 1 | firmwareCompatibility | |
| 0x5F | 1 | firmwareRevision | |
| 0x60 | 4 **BE** | rtcSeconds | Walker clock, in seconds |
| 0x64 | 4 **BE** | totalSteps | Lifetime steps. The walker overwrites this from live RAM just before replying (`ir.c:634`) |

- **Watts are not in 0x22.**
  - Before replying, the walker writes its live watts (u16, **big-endian**) to EEPROM **0xCE8A**: `EEPROM_WALK` 0xCE80 + `WalkData.watts` offset 0x0A (`eeprom_map.h:42`, `records.h:234-239`, `ir.c:637-638`).
  - The game reads watts afterwards with 0x0C.
- Today's step count is not in 0x22 either; it lives elsewhere in walker RAM and EEPROM.

### 4.3 Side effects of 0x20 (it is *not* strictly read-only)
The walker performs these writes before replying (`ir.c:630-641`):
1. A mirror write of its live SaveData to EEPROM 0x0156 and 0x0256.
2. Watts to 0xCE8A.

All of this is the walker's own state; nothing in our packet is consumed. The game does it on every connection, so it is benign. It does, however, cost EEPROM write cycles.

---

## 5. Disconnect 0xF4

- **Format:** `F4 01 ck ck S0..S3`, empty payload.
  - Built in `ov112_021E5A14` (`overlay_112.s:166-197`): command 0xF4, length 0, extra = the configured byte (1), session = the current XOR session.
  - The game sends it only when it was the 0xFA sender and is connected, and never on the timeout path.
  - It sends it at the end of every operation and on every error path (`ov112_021E5A5C` call sites, e.g. `overlay_112.s:1141, 2345, 2352`).
- **On the walker:**
  - 0xF4 is below 0xF8, so it needs the correct session and phase ≥ 3. Otherwise it is ignored, and the walker then times out 97.7 ms later with "connection error". That is harmless.
  - With a valid session, `IrFinish` runs immediately (`ir.c:458-460`). It powers down SCI3 and Timer W and calls `IrComplete` (`h8_resetprg.c:64-194`).
  - After a bare 0x20 no completion action is queued and the result is NONE, so the walker returns to the home screen with no further writes (`h8_resetprg.c:166-169,175-178`).
- **Safe right after identity: yes.** It is exactly what the game does on error paths after 0x22.
- Send it promptly, within ~97 ms of the 0x22 arriving, or the walker ends by timeout instead and shows a connection-error screen. That is also harmless.

---

## 6. What a malformed or unexpected packet can do to the walker

Dispatch is in PW `ir.c:429-1137`.

**Important:** completion actions queued by a command run in `IrComplete` **even if the session ends in an error or timeout** (`h8_resetprg.c:61-63`). Sending a dangerous command is enough; no clean disconnect is needed for its effect.

### 6.1 Safe

| Cmd | Reply | Effect |
|---|---|---|
| 0x24 ping | 0x26, empty | None (`ir.c:814-816`) |
| 0x0C EEPROM read: payload `addrHi addrLo len` | 0x0E, `len` bytes, arg 2 | Read only (`ir.c:1070-1079`). **The walker does not bound `len`.** A value > 0x80 overruns the 136-byte packet buffer into the rest of `g_work`, and > 0xF7 also wraps the u8 TX length. **Always cap at 0x80 and always send exactly 3 payload bytes.** The game sends 0x0C with extra = 2 (`overlay_112.s:1155-1180`); the walker ignores the extra byte for 0x0C |
| 0x20 identity | 0x22 | Benign self-flush writes (§4.3) |
| 0xF4 disconnect | none | Ends the session (§5) |

### 6.2 Destructive or state-changing (never send from the bench tool)
- **0x2A RESET_ALL / 0x2C RESET_KEEP_STEPS.** The walker replies 0x2A with its 40-byte device ID, which is why GBATEK calls this "Unique ID read". It also **queues a persistent reset** that wipes pairing, the walk, inventory, peer history and (for 0x2A) lifetime steps when the session ends (`ir.c:1058-1069`, `h8_resetprg.c:80-90`).
  - **walkerctl currently labels 0x2A "unique ID read reply". That label is dangerously wrong.**
- **0xF0 factory setup:** overwrites the device ID (EEPROM 0x0083 and its mirror) and the motion thresholds. Mode 0 or 3 rewrites the LCD parameters, and mode 3 also queues a full factory reset (`ir.c:1006-1050`).
- **0xFE motion-test setup:** **needs no session and no handshake**, because it is ≥ 0xF8. With arg = 1 and an 8-byte payload it overwrites the pedometer thresholds at EEPROM 0x0008 and switches to the threshold-test view (`ir.c:1051-1057`).
- **0x06 RAM write:** arbitrary memory poke, i.e. code execution (`ir.c:1123-1134`).
- **0x00 / 0x80 compressed page write:** runs `BulkDecode`, the decompressor with the known overflow bugs (Dmitry's exploit), then writes the page (`ir.c:817-830`).
- **0x02 / 0x82 / 0x0A raw EEPROM writes** (`ir.c:831-839, 1115-1122`).
- **0x0E sent unsolicited:** writes its payload to the walker's stale `bulkDestinationEepromAddress` (`ir.c:1080-1114`).
- **0x32 / 0x40 / 0x52 / 0x60 walk-start / walk-end / update / gift requests, and 0xA0–0xAE event checks:** call `StatusApplyTime`, which takes the **RTC and rollover hour from our payload** and sets the walker clock (`h8_resetprg.c:254-270`). Most also mirror-write the save.
- **0x38 / 0x4E / 0x5A / 0x66 commits:** queue a walk start or end, or clear watts and inventory.
- **0xB8–0xBE, 0xC0–0xC6, 0xD0–0xD6:** set event flags and save fields.
- **0x14:** writes peer info to EEPROM.
- **0x10 / 0x12:** start the peer exchange.
- **0xF8 / 0xFA / 0xFC sent mid-session:**
  - 0xFA re-enters PROBING (`ir.c:440-451`).
  - 0xF8 with arg ≠ 2 aborts the session with "rejected". With arg 2 in phase < 3 it starts walker-to-walker peer mode (`ir.c:461-478`).

### 6.3 Malformed framing
- **2–7 byte packets:** the walker treats the first bytes as a header. `payloadLength = received − 8` wraps to 250+ as a u8 (`ir.c:417-418`).
  - With a write command (0x02, 0x82, 0x06, 0x0A) this would write about 250 bytes of garbage, or smash RAM in the 0x06 case.
  - A fragment has to pass a 16-bit checksum first (about 1 in 65 536), and our tool only ever sends 0x20, 0xFA and 0xF4. Even so, **never emit short packets, and keep TX contiguous so the walker never sees fragments.**
- **More than 136 bytes received:** the walker aborts with `RECEIVE_OVERFLOW` (`ir.c:328-333`). Safe.
- **Bad checksum:** dropped (§3.2). Safe.
- **Unknown command (with a valid session):** ignored by the `default` case. Safe.

---

## 7. Review of walkerctl.py

**Correct as written** (verified against the vectors in §2.4):
- `checksum` (L136-150): seed 2, even bytes as high byte, two folds, field zeroed, plain bytes.
- `build_packet` (L153-161): little-endian checksum, session in bytes 4..7.
- `xor_bytes`; `session_from` (L188-189).
- The 0xFA layout (L456: extra 1, random in the header session field, no payload).
- 0x20 and 0xF4 with extra 1 and the XOR session (L469, L489).

The bugs and gaps are in flow, timing, the receive path and labels.

### F1 (real bug): IR replies that arrive while waiting for TX_DONE are thrown away
- `send_ir` (L438-442) uses `Dongle.request` (L231-247). `request` passes every non-TX_DONE frame to `on_other`, and `main` sets `on_other` to a no-op (L558).
- The walker starts its 0xF8 reply about 150 µs after our 0xFA ends. If the dongle emits `IR_RX(F8)` before `TX_DONE` (for example because it delays TX_DONE until an echo-blanking window ends), the 0xF8 is silently dropped, and the tool reports "no 0xF8".
- The same applies to 0x22 after 0x20.

Fix: queue IR_RX frames during the TX wait and let `wait_ir` consume them first.
```python
# Dongle.__init__ (after L199)
        self.pending_ir = []      # IR_RX payloads seen while waiting for other frames
        self.last_tx = b""        # last plain packet we sent (for echo stripping)

# replace send_ir (L438-442)
def send_ir(d, pkt: bytes, timeout=1.0):
    d.last_tx = pkt
    d.send(T_IR_TX, xor_bytes(pkt))
    deadline = time.monotonic() + timeout
    while True:
        left = deadline - time.monotonic()
        fr = d.recv(left) if left > 0 else None
        if fr is None:
            die("no TX_DONE from dongle")
        t, pl = fr
        if t == T_TX_DONE:
            return
        if t == T_IR_RX:
            d.pending_ir.append(pl)       # keep it; it may be the walker's reply
        elif t == T_LOG:
            print(f"  LOG {pl.decode('ascii', 'replace')}")
        elif t == T_ERROR and pl:
            print(f"  ERROR 0x{pl[0]:02x} ({ERROR_NAMES.get(pl[0], 'unknown')}) "
                  f"{pl[1:].decode('ascii', 'replace')}")
```
In `wait_ir` (L413-436), drain `d.pending_ir` before calling `d.recv`:
```python
def wait_ir(d, timeout, match):
    deadline = time.monotonic() + timeout
    while True:
        if d.pending_ir:
            fr = (T_IR_RX, d.pending_ir.pop(0))
        else:
            left = deadline - time.monotonic()
            if left <= 0:
                return None
            fr = d.recv(left)
            if fr is None:
                return None
        t, pl = fr
        if t == T_IR_RX and len(pl) >= 4:
            dec = strip_echo(d, xor_bytes(pl[4:]))
            if not dec:
                continue
            pk = parse_packet(dec, d.seed)
            if pk and match(dec, pk):
                return dec, pk
            print(f"  (ignored RX: {hexs(dec)})")
        elif t == T_LOG:
            ...  # unchanged
```
(`Dongle.recv` reads `self.ser` directly, so `pending_ir` has to be honoured in `wait_ir`, not in `recv`.)

### F2: answer every beacon until 0xF8 arrives, as the game does
- L449-461 wait for one beacon, send one 0xFA, and then wait only for 0xF8.
- If that 0xFA is lost (it landed in the walker's 0–44 ms blind jitter window, or was corrupted), the walker keeps beaconing for about 2.4 s while the tool waits blindly and then dies.
- The game re-answers the next 0xFC (§3.3).

Replace L447-466 with:
```python
    print(f"waiting up to {args.beacon_timeout:.0f}s for walker beacon 0xFC. Start this first, "
          f"then pick Connect on the walker (it beacons for only ~2.5 s)")
    my_id = random.getrandbits(32)
    fa = build_packet(0xFA, 0x01, my_id, seed=args.seed)
    deadline = time.monotonic() + args.beacon_timeout
    sent = 0
    while True:
        r = wait_ir(d, deadline - time.monotonic(),
                    lambda dec, pk: pk.get("beacon") or pk["cmd"] == 0xF8)
        if not r:
            die("timeout: no 0xF8 connect reply" if sent else
                "timeout: no 0xFC beacon seen. Check wiring/aiming with `sniff` "
                "(expect a 0x56 byte every ~100-140 ms for ~2.5 s)")
        dec, pk = r
        if pk.get("beacon"):
            send_ir(d, fa)
            sent += 1
            print(f"beacon -> sent 0xFA #{sent}, random id {fa[4:8].hex(' ')}")
            continue
        break
    if not pk["checksum_ok"] or pk["extra"] != 0x02:
        die(f"bad 0xF8 (checksum/extra): {hexs(dec)}")
    sid = session_from(my_id, pk["session_id"])
```

### F3: echo from our own transmitter
- IrDA transceivers such as the TFBS4711 normally see their own LED. The walker itself discards an echo byte after each TX (`ir.c:118-120`).
- If the dongle does not blank RX during TX, our 0xFA (or 0x20) comes back as IR_RX. The walker's reply then follows only ~150 µs later.
  - If the dongle's RX end-of-packet gap is longer than ~150 µs (for example picowalker-like 3.7 ms), echo and reply **merge into one frame**. That frame parses as cmd 0xFA with a BAD checksum, and the reply is lost.
- Firmware-side fixes:
  - blank RX for the TX duration plus ~50 µs (the `echo` config key);
  - set the RX gap (`gap` key) to about 100–120 µs, just above one byte time (86.8 µs) and matching the walker's own ~122 µs threshold.
- Host-side safety net: strip a leading copy of the last transmitted packet.
```python
def strip_echo(d, dec: bytes) -> bytes:
    tx = getattr(d, "last_tx", b"")
    if tx and dec.startswith(tx):
        return dec[len(tx):]
    return dec
```

### F4: send 0xF4 before printing, and keep within the walker's 97.7 ms idle limit
- L474-486 print the header and a full hex dump before the `finally` sends 0xF4.
- The walker gives up 97.7 ms after its 0x22 ends. Disconnect first, then print.
```python
        dec, pk = r
        send_ir(d, build_packet(0xF4, 0x01, sid, seed=args.seed))  # immediately
        disconnected = True
        print("sent 0xF4 disconnect")
        ...  # then print/parse
    finally:
        if not disconnected:
            try:
                send_ir(d, build_packet(0xF4, 0x01, sid, seed=args.seed))
                print("sent 0xF4 disconnect")
            except SystemExit:
                pass
```
(Initialise `disconnected = False` before the `try`.) Also tighten the match at L471 to `pk["cmd"] == 0x22`, since 0x26 is not a possible reply to 0x20.

### F5: decode the 0x22 payload
L484-486 say no layout is known. It now is (§4.2):
```python
def parse_identity(pl: bytes):
    if len(pl) < 0x68:
        return None
    compat, mon_compat, ver, mon_ver, ot = struct.unpack_from("<IIHHI", pl, 0)
    f = pl[0x5B]
    return {
        "console_compat": compat, "pokemon_compat": mon_compat,
        "game_version": ver, "pokemon_game_version": mon_ver,
        "tid": ot & 0xFFFF, "sid": ot >> 16,          # TID/SID split = Gen4 convention
        "device_id": pl[0x10:0x38].hex(),
        "received_events": pl[0x38:0x48].hex(),
        "trainer_name_u16": list(struct.unpack_from("<8H", pl, 0x48)),  # Gen4 charset
        "receipt_index": pl[0x5A],
        "registered": bool(f & 1), "has_pokemon": bool(f & 2),
        "generated_pokemon": bool(f & 4), "rollover_hour": f >> 3,
        "peer_protocol": pl[0x5C], "console_protocol_level": pl[0x5D],
        "fw_compat": pl[0x5E], "fw_revision": pl[0x5F],
        "rtc_seconds": int.from_bytes(pl[0x60:0x64], "big"),
        "total_steps": int.from_bytes(pl[0x64:0x68], "big"),
    }
```
(This needs `import struct`.)

### F6: the command-name table (L46-77) is wrong in several safety-relevant places
Replace it with the names from PW `protocol.h:19-87` and §6:
```python
CMD_NAMES = {
    0x00: "compressed page write (addr=extra<<8|0x00) [WRITE]",
    0x80: "compressed page write (addr=extra<<8|0x80) [WRITE]",
    0x02: "raw EEPROM write (addr=extra<<8|0x00) [WRITE]",
    0x82: "raw EEPROM write (addr=extra<<8|0x80) [WRITE]",
    0x04: "EEPROM write ack",
    0x06: "RAM write [DANGEROUS]",
    0x0A: "EEPROM write (addr=extra<<8|pl[0]) [WRITE]",
    0x0C: "EEPROM read (pl: hi, lo, len<=0x80)", 0x0E: "EEPROM read reply",
    0x10: "peer status request", 0x12: "peer status reply",
    0x14: "peer info", 0x16: "peer start", 0x1C: "peer already recorded",
    0x20: "identity/status request", 0x22: "identity/status reply (0x68)",
    0x24: "ping", 0x26: "pong",
    0x2A: "RESET ALL (reply carries device ID) [DESTRUCTIVE]",
    0x2C: "RESET keep steps (reply cmd 0x2A) [DESTRUCTIVE]",
    0x32: "walk start request [WRITE]", 0x34: "walk start accepted",
    0x36: "walk start rejected", 0x38: "walk start commit",
    0x40: "walk end request [WRITE]", 0x42: "walk end accepted",
    0x44: "walk end rejected", 0x4E: "walk end commit", 0x50: "walk end ack",
    0x52: "walk update request [WRITE]", 0x54: "walk update accepted",
    0x56: "walk update rejected", 0x5A: "walk update commit",
    0x60: "gift request [WRITE]", 0x62: "gift accepted", 0x64: "gift rejected",
    0x66: "gift collection commit", 0x68: "gift collection ack",
    0x9C: "event buffer full", 0x9E: "event already received",
    0xA0: "event map check", 0xA2: "event pokemon check",
    0xA4: "event item check", 0xA6: "event course check",
    0xA8: "event stamp0 check", 0xAA: "event stamp1 check",
    0xAC: "event stamp2 check", 0xAE: "event stamp3 check",
    0xB8: "event stamp0", 0xBA: "event stamp1", 0xBC: "event stamp2", 0xBE: "event stamp3",
    0xC8: "event stamp0 ack", 0xCA: "event stamp1 ack",
    0xCC: "event stamp2 ack", 0xCE: "event stamp3 ack",
    0xC0: "event map done", 0xC2: "event pokemon done",
    0xC4: "event item done", 0xC6: "event course done",
    0xD0: "event stamp+map done", 0xD2: "event stamp+pokemon done",
    0xD4: "event stamp+item done", 0xD6: "event stamp+course done",
    0xD8: "event rejected",
    0xF0: "factory setup [DESTRUCTIVE]",
    0xF4: "disconnect",
    0xF8: "connect reply", 0xFA: "connect request", 0xFC: "connection beacon",
    0xFE: "motion threshold setup (no session needed) [WRITE]",
}
```

### F7: defaults and comments
- **L79-80:** replace the comment with "Seed 2 is confirmed by both firmwares (walker PacketChecksum, HGSS ov112_021E5900); Dmitry's seed-0 variant is off by 2." Keep `--seed` as a debug knob only, and update the help text at L533.
- **L544:** set the reply `--timeout` default to 0.3 s instead of 1.0. The walker answers in under ~20 ms and abandons the session after 97.7 ms of idle, so a 1 s wait only delays the error.
- **L8-9 docstring:** "read-only" should note that 0x20 makes the walker flush its own save and watts to EEPROM (§4.3).
- **L11-12 TODO dump:** cap `len` at 0x80, send exactly 3 payload bytes, use extra 0x02 like the game, and send each read within 97 ms of the previous reply.
- **L466 and L457:** print session values as raw bytes (`pk['payload']`-style hex), not as little-endian ints. The walker's own (big-endian) view of the same token is byte-reversed, which confuses comparisons with walker-side logs.

### F8: tests to add to test_walkerctl.py
```python
def test_decomp_vectors():
    ds, wk = 0x78563412, 0x01EFCDAB          # wire bytes 12 34 56 78 / ab cd ef 01
    assert w.build_packet(0xFA, 1, ds) == bytes.fromhex("fa01b06212345678")
    assert w.parse_packet(bytes.fromhex("f802d492abcdef01"))["checksum_ok"]
    sid = w.session_from(ds, wk)
    assert sid.to_bytes(4, "little") == bytes.fromhex("b9f9b979")
    assert w.build_packet(0x20, 1, sid) == bytes.fromhex("20017693b9f9b979")
    assert w.build_packet(0xF4, 1, sid) == bytes.fromhex("f4017767b9f9b979")
    assert w.build_packet(0x0C, 2, sid, bytes([0xCE, 0x8A, 2])) == \
        bytes.fromhex("0c020250b9f9b979ce8a02")
    assert w.xor_bytes(bytes.fromhex("fa01b06212345678")) == bytes.fromhex("50ab1ac8b89efcd2")
    assert w.checksum(bytes([0xFF, 0xFF, 0, 0, 0xFF, 0xFF, 0xFF, 0xFF]) + b"\xff" * 0x80) == 0x0002
```
All of these pass against the current walkerctl.py: I checked them with `python3 -B`, which left no pycache behind.

---

## 8. Corrections to the project notes (`ir_hardware_and_protocol.md` §3)
- **"Checksum initial sum 2":** confirmed by both decomps. Drop the conflict entry.
- **"0x2A Unique ID read" (GBATEK) vs "erase walker" (Dmitry):** both are right. The reply carries the ID, and a reset runs when the session ends.
- **0x32 / 0x40 / 0x52 / 0x60:** these are walk start / walk end / walk update / gift *requests*, each with accept and reject replies. They are not "identity writes".
- **0x38 / 0x4E / 0x5A / 0x66:** these are the corresponding commits.
- **Session-check boundary:** the walker exempts ≥ 0xF8 and the game exempts ≥ 0xF0. 0xF4 needs the session on both.
- **Gaps now filled:**
  - packet-end gap: walker > 4 ticks ≈ 122–153 µs;
  - idle timeout: 97.7 ms;
  - beacon period: ~98–142 ms, 20 tries;
  - game deadline: 100 ms from the last valid packet;
  - nobody retransmits data packets.
- **Walker idle-gap caveat:** these walker figures assume the 32 768 Hz Timer W clock (§3.1). Confirm with one `sniff` capture of the beacon spacing.
