# Pokéwalker IR Communication: Hardware and Protocol (physical layer up)

Research notes compiled 2026-11-06. Primary sources: Dmitry Grinberg's Pokéwalker article (dmitry.gr), GBATEK by Martin Korth / nocash (read via the mgba-emu.github.io mirror because problemkaputt.de could not be reached from this environment), PoroCYon's pokewalker-rom-dumper README (zff.dev), the NESdev forum thread, and current hobbyist hardware projects (Flipwalker / FlippIR, picowalker). Bulbapedia returned HTTP 403, so its claims below come only from search-result snippets and are marked as such.

Terminology: GBATEK calls the device "P-Walker" and the games "P-Letter HeartGold/SoulSilver". PCB marking is NTR-PHC-01.

## 1. Physical link technology (IR vs RF, wavelength, IrDA SIR vs consumer IR, baud, framing)

### Takeaway
The link is infrared, not RF. It is IrDA-SIR-style (unmodulated, UART-framed, short pulses) at a fixed 115200 baud, 8N1, half-duplex. It is not a 38 kHz consumer-IR remote-control carrier. Packets are delimited by a pause on the line, not by framing bytes. Every byte is XORed with 0xAA. The transceiver wavelength has never been measured or published; the IrDA standard band is 850–900 nm.

### Cited Findings
- Grinberg used an IR transceiver on an STM32F429 board to sniff a DS cartridge talking to a walker. The pulses were "consistent with SIR signaling at 115,200, 8n1." — [dmitry.gr Pokéwalker hacking](https://dmitry.gr/?r=05.Projects&proj=28.%20pokewalker)
- GBATEK: "The IR transfers are using a fixed baudrate: 115200 baud, 8n1, one-directional (RX gets disabled during TX)." Packets are "terminated by a 'pause' in the IR transmission", and this "packet+pause" scheme rules out streaming anything larger than the buffer. — [GBATEK DS Cart Infrared Cartridge SPI Commands (mirror)](https://mgba-emu.github.io/gbatek/#dscartinfraredcartridgespicommands)
- In both the cartridge and the walker, GBATEK names the MCU pins "IrDA PWDOWN (1=disable IrDA RX)", "IrDA RXD" and "IrDA TXD", driven "via serial IrDA registers" of the H8/3860x. This means the MCU's built-in IrDA-mode SCI does the 3/16 pulse encoding. — [GBATEK P-Walker Memory Map / Cartridge Memory Map (mirror)](https://mgba-emu.github.io/gbatek/#dscartinfraredpwalkermemorymap)
- Both the Pokéwalker and the cartridge have a 7-pin IR transceiver. Its markings are unidentified ("U5 7pin Side-B IR transceiver"). In the Walk with Me cart the transceiver pinout is 1=GND, 2=TXD, 3=RXD, 4=PWDOWN, 5=NC, 6=GND, 7=VCC. — [GBATEK DS Cart Infrared Component Lists (mirror)](https://mgba-emu.github.io/gbatek/#dscartinfraredcomponentlists). Grinberg calls it "a generic SIR-compatible part with no distinguishing markings." — [dmitry.gr](https://dmitry.gr/?r=05.Projects&proj=28.%20pokewalker)
- The walker's 3.68 MHz crystal is annotated "(115.2kHz*32)". Grinberg gives the system clock as 3.6864 MHz. That is an exact UART-friendly frequency (32 × 115200). — [GBATEK Component Lists](https://mgba-emu.github.io/gbatek/#dscartinfraredcomponentlists); [dmitry.gr](https://dmitry.gr/?r=05.Projects&proj=28.%20pokewalker)
- IrDA SIR physical layer: wavelength "850–900 nm", rates 2.4–115.2 kbit/s, encoding "asynchronous, RZI, UART-like, 3/16 pulse", cone of at least 15° half-angle, and a nominal range of about 0.2–2 m depending on power class. — [Wikipedia: Infrared Data Association](https://en.wikipedia.org/wiki/Infrared_Data_Association)
- Hobbyist confirmation that the link is not consumer IR: the Flipper Zero's built-in IR "is a remote-control port: the receiver is a 38 kHz demodulator and only sees carrier bursts", while the Pokéwalker/DS signal is "plain, unmodulated light with microsecond timing", so the built-in port never sees it. — [FlippIR-Hardware README](https://github.com/Jackv-makes/FlippIR-Hardware). The Flipwalker README says the Pokéwalker "uses IrDA SIR" and that the built-in IR "only does 38kHz remote control stuff". — [Flipwalker README](https://github.com/Jackv-makes/Flipwalker)
- Bytes on the wire are XORed with 0xAA. — [dmitry.gr](https://dmitry.gr/?r=05.Projects&proj=28.%20pokewalker); GBATEK: Nintendo wants all IR packet bytes "encrypted" (XORed by AAh), done on the ARM side, not in the cart MCU. — [GBATEK Activity Meter IR Commands](https://mgba-emu.github.io/gbatek/#dscartinfraredactivitymeterircommands)
- Range: for the related Activity Meter, GBATEK says the range is unknown but full 64K dumps worked "without checksum errors at about 5-10cm distance". — [GBATEK](https://mgba-emu.github.io/gbatek/#dscartinfraredactivitymeterircommands). FlippIR reports range of "a few centimetres against a Game Boy's weak LED and more against an IrDA device" (no figure for the Pokéwalker). — [FlippIR-Hardware](https://github.com/Jackv-makes/FlippIR-Hardware)

### Inferences
- At 115200 baud one bit lasts about 8.68 µs. A standard SIR 3/16 pulse is therefore about 1.63 µs per "0" bit, and "1" bits are dark. Any receiver must resolve microsecond pulses. A 38 kHz demodulating receiver (TSOP-style) cannot work, and neither can phone "IR blasters", which are carrier-modulated transmit-only parts.
- The user-visible behavior (point the devices at each other, a few cm to tens of cm) fits a low-power IrDA SIR transceiver. RF is ruled out: the DS's Wi-Fi is not used, and both ends show IrDA transceivers on the PCB.
- Practical hobbyist hardware: any off-the-shelf IrDA SIR transceiver (for example Vishay TFBS4711 or TFDU4101, both proven by Flipwalker) attached to a UART with IrDA/SIR mode (STM32 USART IrDA mode, H8 SCI) or to an external SIR encoder chip, set to 115200 8N1. Software must apply XOR 0xAA and detect packet ends by inter-byte idle time.

### Gaps
- I found no measured emission wavelength or part number for the Pokéwalker's or the HGSS cart's transceiver. "850–900 nm" comes from the IrDA spec, not a measurement.
- I found no published exact inter-packet "pause" duration. It has to be measured or taken from an emulator's source.
- No measured link range for Pokéwalker to DS was found.

## 2. Where the IR transceiver lives, how the DS talks to it, and why it works on 3DS

### Takeaway
The IR hardware is in the HGSS game card, not the console. The card has its own small Renesas H8/3860x MCU and an IrDA transceiver. Both sit on the DS cartridge's auxiliary SPI ("AUXSPI", save-memory) bus, sharing it with the save EEPROM/FLASH. The DS sends SPI command bytes: 0x00 = pass-through to the save chip, 0x01 = read a received IR packet, 0x02 = transmit an IR packet, 0x03–0x06 = peek/poke cart-MCU memory, 0x07 = echo of the previous command's parameters, 0x08 = version. A 3DS (or DSi) runs the DS game with the same cart and slot signals, so the link works there too. The 3DS's own IrDA hardware is not involved.

### Cited Findings
- "The DS has no IR hardware", so the HGSS cartridge contains the IR transceiver. Counterfeit carts lack it. — [dmitry.gr](https://dmitry.gr/?r=05.Projects&proj=28.%20pokewalker)
- "The IR-port is accessed via SPI bus commands; that bus is also shared for accessing FLASH/EEPROM memory (via 00h-prefix)." — [GBATEK Cartridge SPI Commands](https://mgba-emu.github.io/gbatek/#dscartinfraredcartridgespicommands). GBATEK's cart backup section: "A few NDS/DSi carts are sharing the SPI bus for FLASH and Infrared, this requires a 00h-prefix byte for FLASH access, with slower 1MHz SPI clock and delays." — [GBATEK mirror](https://mgba-emu.github.io/gbatek/)
- nocash on NESdev: the IR port "is wired to the SPI bus, not to the ROM chip." Shonumi: "All infrared communications on the NTR-031 happen via auxiliary SPI (AUXSPI)." — [NESdev forum t=21140](https://forums.nesdev.org/viewtopic.php?t=21140)
- GBATEK SPI command summary (OLD = Walk with Me cart firmware, NEW = P-Letter/HGSS/BW series):
  - `00h,cmd,params...` Savedata access (forwarded to the FLASH/EEPROM)
  - `01h,00h,00h` IR RX, nothing pending; `01h,len,data[len]` IR RX (OLD max 84h, NEW max B8h bytes)
  - `02h,data[...]` IR TX (same limits). OLD firmware refuses to TX data starting with F2h.
  - `03h,msb,lsb,data` / `05h,msb,lsb,d,d` MCU memory write 8/16-bit; `04h` / `06h` memory read 8/16-bit
  - `07h,00h,num,...` returns parameters of the previous SPI command
  - `08h,ver` NEW only: returns version (ver=AAh)
  - `04h,04h` initial dummy in Walk with Me
  — [GBATEK Cartridge SPI Commands](https://mgba-emu.github.io/gbatek/#dscartinfraredcartridgespicommands)
- PoroCYon's dumper README (independent, earlier, credited to a melonDS BBS post): 0x00 escape ("as long as chip select is held, the bytes that follow will be treated like a regular savegame transfer"); 0x01 receive ("The first byte read indicates the amount of bytes that will follow", and even with zero bytes you must deselect or the next transfer fails); 0x02 send (no length prefix, CS release ends the packet); 0x03–0x06 RAM write/read, credited to nocash, with 0x04 able to "dump the ROM inside the in-cart IR MCU"; 0x07 "mystery"; 0x08 "probably a status thing", sent twice by HGSS at connection time. — [zff.dev PoroCYon/pokewalker-rom-dumper](https://zff.dev/PoroCYon/pokewalker-rom-dumper)
- SPI timing: max 1 MHz SPI clock for IR commands, plus a delay after each byte ("Waiting 800h clks at 33MHz seems to work okay"). Savedata pass-through runs at 4 MHz without delays, but the leading 00h must be sent at 1 MHz plus delay. — [GBATEK](https://mgba-emu.github.io/gbatek/#dscartinfraredcartridgespicommands). PoroCYon agrees that transfers run at 1 MHz and the 0x00 byte "needs to be transferred at 1 MHz." — [zff.dev](https://zff.dev/PoroCYon/pokewalker-rom-dumper). Shonumi's early failures were attributed to using a 4 MHz SPI clock. — [NESdev](https://forums.nesdev.org/viewtopic.php?t=21140)
- Cart-side behavior: RX returns len=00h until a whole IR packet has arrived. TX does not start until the whole packet has been written over SPI and chip select is released. There is no TX-done indication; you wait for the walker's reply or use a timer. There is no IRQ (the cart IRQ pin is grounded in Walk with Me). — [GBATEK](https://mgba-emu.github.io/gbatek/#dscartinfraredcartridgespicommands)
- Cart MCU role: "In the cartridge it's merely used for forwarding IR messages via SPI bus." A 5-pin gate (U3) forwards SPI /CS to the FLASH /CS. Cart MCU pin Port 8 bit 3 is "Savedata chipselect (0=select) (cmd 00h)". — [GBATEK overview, Component Lists, Cartridge Memory Map](https://mgba-emu.github.io/gbatek/#dscartinfraredcomponentlists)
- Hands-on corroboration: on SoulSilver carts the edge-connector /CS pin (pin 6) goes to the small MCU, not directly to the EEPROM. Dumping the save required bridging it to the EEPROM's CS. — [Project Pokémon forum, "dumping HGSS US saves" (via search summary)](https://projectpokemon.org/home/forums/topic/7032-dumping-hgss-us-saves)
- Detection: IR carts have game codes starting with "I" (NTR-Ixxx / TWL-Ixxx), and the ROM chip ID has an "IR" flag in bit 0 of byte 3 that is unreliable (Jam with the Band sets it without IR). HGSS = NTR-IPKx/IPGx, BW = TWL-IRBO/IRAO, B2W2 = TWL-IREO/IRDO. — [GBATEK gamecode / chip ID / Component Lists](https://mgba-emu.github.io/gbatek/); [NESdev](https://forums.nesdev.org/viewtopic.php?t=21140)
- Access needs only cart power-on/reset (DSi SCFG registers in homebrew), "but doesn't require any ROM commands like secure area loading." — [GBATEK](https://mgba-emu.github.io/gbatek/#dscartinfraredcartridgespicommands); PoroCYon: "No header reading or KEY1/KEY2 init". — [zff.dev](https://zff.dev/PoroCYon/pokewalker-rom-dumper)
- 3DS: the 3DS has its own, unrelated IrDA block, an NXP SC16IS750 UART with IrDA SIR on I2C device 2:9Ah, used by 3DS software. — [GBATEK 3DS I2C Infrared (mirror)](https://mgba-emu.github.io/gbatek/#3dsi2cinfraredreceivertransmitterirda). PoroCYon's homebrew dumper using the cart IR reportedly works on 3DS/2DS in DSi backwards-compatibility mode. — [zff.dev](https://zff.dev/PoroCYon/pokewalker-rom-dumper)
- Flashcarts: standard flashcarts lack IR hardware and cannot connect. A newer "DS Pico" flashcart variant reportedly adds an IR transceiver for Pokéwalker use. — [GBAtemp: Flashcarts and Pokewalker](https://gbatemp.net/threads/flashcarts-and-pokewalker-do-they-work.220396/); [RetroRGB: DS Pico "IR" Flash Cart](https://retrorgb.com/ds-pico-ir-flash-cart-for-nintendo-ds.html) (search-snippet level)
- Anecdote: any IR cart (for example Pokémon Black) can provide the IR port to software, since the cart IR firmware is generic across the P-Letter series. — [Reddit r/3dspiracy (via search summary)](https://reddit.birdcat.cafe/r/3dspiracy/comments/11k0hu6/big_brain_move_with_pokewalker/jb6yo83/?context=3). GBATEK lists HGSS, BW and B2W2 under the same P-Walker heading. — [GBATEK Component Lists](https://mgba-emu.github.io/gbatek/#dscartinfraredcomponentlists)

### Inferences
- Why it works on a 3DS: all IR electronics (MCU and transceiver) are in the card, and the console only drives the standard DS card-slot AUXSPI lines, which the 3DS provides in DS/DSi compatibility mode. No console-side IR is needed, so the 3DS's SC16IS750 IrDA port is irrelevant to HGSS.
- To build a "DS-side" device without a DS, a hobbyist needs only an IrDA SIR transceiver plus UART, as in section 1. Alternatively, an HGSS/BW cart on a 1 MHz SPI master (with per-byte delays) gives a ready-made IR modem: SPI 0x02 sends, SPI 0x01 polls.
- Note on a reported conflict: one write-up (Cloudspress, via search snippet) set "0x02 = EEPROM write" against PoroCYon's "0x02 = IR send". This is a layer confusion, not a real conflict. SPI byte 0x02 (DS to cart: transmit) and IR packet command 0x02 (inside the IR payload: raw EEPROM write on the walker) are different namespaces.

### Gaps
- No component list or part markings were found specifically for the HGSS cart PCB. GBATEK lists the Walk with Me cart (CPU marked "38600R") and a P-Letter Black cart (illegible parts).
- The HGSS cart's IR transceiver part number and the exact /CS gating logic part (U3) are unidentified.
- I found no first-party or measured statement that HGSS + Pokéwalker works on 3DS. It is widely used that way, but the only sources here are the architectural argument and anecdotal Reddit/homebrew reports.

## 3. Packet / protocol structure

### Takeaway
Every packet (after the bare 0xFC beacon) has an 8-byte header followed by up to 0x80 bytes of payload. The header is cmd (1), extra (1: 0x01 = from DS/master, 0x02 = from walker/slave), checksum (2, little-endian, Internet-style one's-complement-ish fold of big-endian 16-bit words, initial sum 2 per GBATEK), and session ID (4). The whole packet is XORed with 0xAA on the wire. Handshake: walker sends 0xFC, master sends 0xFA with a random 32-bit value, walker replies 0xF8 with its own random value, and session ID = XOR of the two. After that the DS mostly does raw/compressed EEPROM reads and writes (0x0C/0x0E, 0x02/0x82, 0x00/0x80 LZSS) plus a handful of semantic commands (identity 0x20/0x22, walk start 0x5A/0x38, walk end 0x4E/0x50, ping 0x24/0x26, disconnect 0xF4).

### Cited Findings
- Header (8 bytes): command, "extra" (usually 0x01 from master, 0x02 from slave), 2-byte checksum, 4-byte session ID. — [dmitry.gr](https://dmitry.gr/?r=05.Projects&proj=28.%20pokewalker). GBATEK agrees: ".. short for 16bit Checksum at hdr[2..3] and 32bit Session ID at hdr[4..7]"; "xx ... usually 01h=From NDS, or 02h=From Walker". — [GBATEK P-Walker IR Commands](https://mgba-emu.github.io/gbatek/#dscartinfraredpwalkerircommands)
- Walker IR buffer: "F8CEh 8+80h Infrared RX/TX buffer hdr+data", so maximum packet = 8 + 128 bytes. — [GBATEK P-Walker Memory Map](https://mgba-emu.github.io/gbatek/#dscartinfraredpwalkermemorymap)
- Checksum (GBATEK, on decrypted packet, checksum field zeroed): sum += packet[i]*0x100 for even i and packet[i] for odd i; then fold twice: `sum=(sum>>16)+(sum&0xFFFF)`, `sum=(sum>>16)+sum`; store little-endian. For the P-Walker use "initial sum=2, not sum=0". — [GBATEK Activity Meter + P-Walker IR Commands](https://mgba-emu.github.io/gbatek/#dscartinfraredactivitymeterircommands). Grinberg describes the same even/odd big-endian sum and fold, admits his version was "almost, but not perfectly correct", and gives the walker ROM routine as 0x0714 calcPacketCrc. — [dmitry.gr](https://dmitry.gr/?r=05.Projects&proj=28.%20pokewalker). The initial-2 value is confirmed by both firmware decompilations and explains Grinberg's small discrepancy (see Corrections (from decompilation) below).
- Session: "The Connect Request & Reply commands are sending a 'random' SessionID each, all following commands/replies (except F8h and up on the walker side; the game side exempts F0h and up, and F4 needs the session on both) must use SessionID = ConnectRequestRandomID XOR ConnectReplyRandomID." — [GBATEK](https://mgba-emu.github.io/gbatek/#dscartinfraredpwalkerircommands). Grinberg: packets without it are ignored. — [dmitry.gr](https://dmitry.gr/?r=05.Projects&proj=28.%20pokewalker)
- Beacon: the walker sends a single 0xFC "every few hundred milliseconds", the only non-packet traffic. — [dmitry.gr](https://dmitry.gr/?r=05.Projects&proj=28.%20pokewalker). GBATEK: "FC Connection Beacon from Walker ;SendCmd=FA". — [GBATEK](https://mgba-emu.github.io/gbatek/#dscartinfraredpwalkerircommands)
- Handshake: FC (walker) → FA,01 (DS, random ID) → F8,02 (walker, random ID). Between walkers: FA,02 from walker → F8,02 → 10 (peer step 1, 0x68 bytes) → 12 → 14 (step 2) → 16; 1C = peer refuse. — [GBATEK](https://mgba-emu.github.io/gbatek/#dscartinfraredpwalkerircommands); [dmitry.gr](https://dmitry.gr/?r=05.Projects&proj=28.%20pokewalker)
- EEPROM commands: 00/80 = compressed write of the 128-byte half-page [hi00–hi7F]/[hi80–hiFF]; 02/82 = raw write; 04 = write ack; 0A = variable-length EEPROM write; 0C = read (hi, lo, len ≤ 0x80), reply 0E. Compression is "Nintendo's standard LZSS (including the header value 10h, and little-endian 24bit length; which should be always 80h)", used only to speed up IR. A compressed write with exactly 0x80 incoming bytes is treated as uncompressed. — [GBATEK](https://mgba-emu.github.io/gbatek/#dscartinfraredpwalkerircommands); [dmitry.gr](https://dmitry.gr/?r=05.Projects&proj=28.%20pokewalker)
- Semantic commands (GBATEK naming, cross-checked against Grinberg): 20/22 identity read (0x68 bytes); 24/26 ping/pong; 4E/50 walk end commit/ack; 5A walk update commit, 38 walk start commit (GBATEK: silent start); 32/40/52/60 walk start / walk end / walk update / gift requests, each with accept and reject replies (GBATEK's "identity writes" label is wrong, see Corrections (from decompilation) below); 06 CPU memory write (direct RAM/MMIO poke, reply 06); F0 factory setup (0x71 bytes, overwrites unique-ID/LCD-init data; DESTRUCTIVE); F4 disconnect; FE motion-test setup (writes EEPROM 0x0008–0x000F, needs no session; DESTRUCTIVE); B8/BA/BC/BE award stamps; C0/C2/C4/C6 award special map / event Pokémon / event item / event route; D0–D6 the same plus all stamps; A0–AE event-participation checks; 9C/9E error variants. GBATEK marks most of the latter (`*`) as unused by retail HGSS, probably prototype or event tests. — [GBATEK](https://mgba-emu.github.io/gbatek/#dscartinfraredpwalkerircommands); [dmitry.gr](https://dmitry.gr/?r=05.Projects&proj=28.%20pokewalker)
- Sending/receiving Pokémon and watts work through these EEPROM primitives, not dedicated commands. CMD 0x20 writes current watts into EEPROM 0xCE8A–0xCE8B (big-endian) before replying, so the game reads watts out of the identity/EEPROM data. Event content lives at fixed EEPROM addresses (event item 0xBD40, event Pokémon 0xBA44, special route 0xBF00). — [dmitry.gr](https://dmitry.gr/?r=05.Projects&proj=28.%20pokewalker)
- The same packet family (XOR 0xAA, checksum, FC beacon, FA/F8 connect, F4 disconnect) is used by the Activity Meter (Walk with Me / Personal Trainer: Walking), with its own command numbers (08/0A memory, 20/22 EEPROM, 24 RTC). — [GBATEK Activity Meter IR Commands](https://mgba-emu.github.io/gbatek/#dscartinfraredactivitymeterircommands). NESdev describes the IR cart protocol as "very similar to the NTR-PHC-01 (aka PokeWalker)" (search snippet). — [NESdev](https://forums.nesdev.org/viewtopic.php?t=21140)
- DS-side code: Grinberg names HGSS ARM9 functions irDoTx at 0x020DDFE0 and irRx at 0x020DDE94, with packet functions in overlay9_112. — [dmitry.gr](https://dmitry.gr/?r=05.Projects&proj=28.%20pokewalker). The pret HeartGold/SoulSilver decompilation is cited as the DS-side reference by Flipwalker. — [Flipwalker README](https://github.com/Jackv-makes/Flipwalker)

### Conflicting claims
- **Peer step 2 payload size:** Grinberg says 0x34 bytes; GBATEK says `14,xx,..,data(38h)`. — [dmitry.gr](https://dmitry.gr/?r=05.Projects&proj=28.%20pokewalker) vs [GBATEK](https://mgba-emu.github.io/gbatek/#dscartinfraredpwalkerircommands)
- **Cmd 0x2A / 0x2C:** Grinberg: "Erase walker, set RTC (used by game to reset)" and a variant. GBATEK: "Unique ID Read Request ;Reply=2A" with data(28h). Resolved: both are right, and it is DESTRUCTIVE (see Corrections (from decompilation) below). — same sources
- **Checksum initial value:** resolved, the seed is 2 (see Corrections (from decompilation) below). Grinberg's algorithm (initial 0) was "almost" right because it is off by exactly 2. — same sources
- **SPI 0x08:** GBATEK says it returns version byte 0xAA (NEW firmware). PoroCYon guessed "status". — [GBATEK](https://mgba-emu.github.io/gbatek/#dscartinfraredcartridgespicommands) vs [zff.dev](https://zff.dev/PoroCYon/pokewalker-rom-dumper)
- **Max RX size:** GBATEK gives OLD 0x84 / NEW 0xB8 bytes. PoroCYon says it "doesn't seem to be able to receive more than 255 bytes" (an upper bound, not contradictory).

### Corrections (from decompilation)
Source: `docs/research/walker-protocol-facts.md` (lumirth/pw walker reconstruction and pret/pokeheartgold overlay_112). These override the conflicting claims above.

- **Checksum initial sum 2:** confirmed by both decompilations. The seed-0 conflict entry is dropped.
- **0x2A "Unique ID read" (GBATEK) vs "erase walker" (Dmitry):** both are right. The reply carries the 40-byte ID, and a persistent reset (0x2A wipes everything incl. lifetime steps, 0x2C keeps steps) runs when the session ends. Never send 0x2A/0x2C from a bench tool.
- **0x32 / 0x40 / 0x52 / 0x60:** walk start / walk end / walk update / gift *requests*, each with accept and reject replies. They are not "identity writes".
- **0x38 / 0x4E / 0x5A / 0x66:** the corresponding commits.
- **Session-check boundary:** the walker exempts commands >= 0xF8, the game exempts >= 0xF0. 0xF4 needs the session on both sides.
- **Gaps filled:** walker packet-end gap is > 4 Timer W ticks (about 122–153 µs); walker idle timeout 97.7 ms; beacon period about 98–142 ms with 20 tries; game reply deadline 100 ms from the last valid packet; nobody retransmits data packets.
- **Caveat:** the walker figures assume a 32 768 Hz Timer W clock. Confirm with one `sniff` capture of the beacon spacing.

### Inferences
- Minimal DS-emulating host flow: wait for 0xFC, send FA/01 with a random 4-byte ID, take the F8 reply, compute the session ID, then use 0x0C reads/0x02 writes against the walker's 64 KB EEPROM map. Every packet is ≤ 136 bytes, XOR 0xAA, with checksum initial 2, and is ended by idling the line.

### Gaps
- No exact timeout or retry values, and no inter-packet idle threshold, were found in these sources. Now filled from the decompilations (see Corrections (from decompilation) below).
- The full EEPROM memory map (where the walking Pokémon, steps and watts history live) is in GBATEK's P-Walker Memory Map and Grinberg's article. It was not extracted here beyond the addresses listed.

## 4. Hardware inside the Pokéwalker

### Takeaway
Renesas H8/38606F (flash version, marked "F38606"; H8/300H core, 48 KB flash, 2 KB RAM) at 3.6864 MHz, with a 32 kHz watch crystal. ST M95512 64 KB SPI EEPROM. Bosch BMA150 accelerometer (SPI). An unmarked 7-pin IrDA SIR transceiver on the MCU's IrDA SCI pins. A 96×64 2-bit greyscale SPI LCD (controller identified variously as SSD1854, NT7508 or SSD1850-like). A piezo buzzer, three buttons, and a CR2032 cell.

### Cited Findings
- MCU "Renesas H8/38606, part of the H8/38602R family". EEPROM ST M95512 64 KB SPI. Accelerometer Bosch BMA150. IR "generic SIR-compatible part with no distinguishing markings". LCD first guessed as SSD1854, later "very likely the Novatek NT7508". Clock 3.6864 MHz. Chip selects: accel P9.0, EEPROM P1.2, LCD P1.0 (D/C on P1.1). Buttons on PB0/PB2/PB4. — [dmitry.gr](https://dmitry.gr/?r=05.Projects&proj=28.%20pokewalker)
- GBATEK component list (PCB NTR-PHC-01): U1 "F38606, F04V, AK04052, 0942" (CPU, FLASH 48Kbyte, RAM 2KByte); U5 7-pin IR transceiver; U6 8-pin (maybe SPI EEPROM); U7 12-pin (BMA150?); X1 32.768 kHz-class resonator; Y1 "3.68" (115.2 kHz × 32); BZ1 piezo; LCD "SSD1850 display controller (or similar)", "96x64 2-bit greyscale", SPI; CR2032. — [GBATEK Component Lists](https://mgba-emu.github.io/gbatek/#dscartinfraredcomponentlists)
- Walker RAM is 2 KB at F780h–FF7Fh, with main_callback at F7E0h and the IR buffer at F8CEh. The SPI bus is shared by the 64 KB EEPROM, the LCD and the accelerometer. Audio comes from Timer W. — [GBATEK P-Walker Memory Map](https://mgba-emu.github.io/gbatek/#dscartinfraredpwalkermemorymap)
- Bulbapedia (search snippet only, page returned 403): H8/38606R, 8/16-bit, 3.6 MHz, 2 KiB RAM, 48 KiB internal program ROM; 64 KiB ST M95512 EEPROM. — [Bulbapedia Pokéwalker](https://bulbapedia.bulbagarden.net/wiki/Pok%C3%A9walker)
- Hackaday (2020) summary of Grinberg's teardown: 64 KB EEPROM, Renesas H8/38606R, Bosch BMA150, generic IR transceiver (search snippet). — [Hackaday 2020-11-21](https://hackaday.com/2020/11/21/reverse-engineering-a-pokewalker)
- Cartridge IR MCU: PoroCYon says it is "Allegedly" "another H8/38606F (or 38602F?)". GBATEK shows the Walk with Me cart CPU marked "38600R" (nominally 8 KB ROM / 0.5 KB RAM, apparently behaving like a 38602R), and lists the P-Letter Black cart CPU with "ROM 8Kbyte, RAM 0.5KByte". — [zff.dev](https://zff.dev/PoroCYon/pokewalker-rom-dumper); [GBATEK Component Lists](https://mgba-emu.github.io/gbatek/#dscartinfraredcomponentlists)

### Inferences
- The MCU naming differences (H8/38606 vs 38606R vs F38606) refer to the same family. The package marking "F38606" indicates the flash variant. Bulbapedia's "R" and "internal ROM" wording is probably imprecise.
- The cart MCU identity conflicts (38606F per PoroCYon vs 38600R-class per GBATEK). GBATEK's is based on photographed markings of other IR carts, not HGSS specifically.

### Gaps
- No HGSS-cart teardown with legible markings was found.
- The walker's IR transceiver and LCD controller remain unconfirmed by datasheet match.

## 5. Key reverse-engineering sources and what each establishes

### Takeaway
Dmitry Grinberg (2020) established the physical layer, packet format, command set, and the code-execution exploit. Martin Korth/nocash's GBATEK (about 2021 onward) is the most complete reference for cart SPI commands, the P-Walker command table, the checksum with initial value 2, memory maps and part lists. PoroCYon's dumper documented the cart SPI interface independently and gave working DSi homebrew. Current hobbyist projects (Flipwalker/FlippIR, picowalker, PocketWalker, PokeStroller, pwemu, melonDS-IR) show the link can be driven with stock IrDA parts or emulated over TCP.

### Cited Findings
- **dmitry.gr "PokéWalker hacking"**: SIR 115200 8N1 capture; XOR 0xAA; header and checksum; session-ID XOR; full command table; hardware ID; compressed-write decompressor bugs leading to a stack overflow and code execution (ROM dump SHA-256 f9e210a3…5607); the cleaner CMD 0x06 RAM-write exploit (write code to 0xF956–0xFF40, hook main_callback at 0xF7E0); and event-content injection. — [dmitry.gr](https://dmitry.gr/?r=05.Projects&proj=28.%20pokewalker)
- **GBATEK (problemkaputt.de, mirrored at mgba-emu.github.io/gbatek)**: "DS Cart Infrared/Pedometers" chapter covering cart SPI commands, OLD/NEW cart firmware, SPI timing, IR transfer semantics, cart and walker memory maps, Activity Meter and P-Walker IR command tables, LCD and BMA150 port docs, and component lists. It cites Grinberg and NESdev t=21140 as references. — [GBATEK mirror](https://mgba-emu.github.io/gbatek/#dscartinfraredpedometers); original pages e.g. [problemkaputt.de/gbatek-ds-cart-infrared-p-walker-ir-commands.htm](https://problemkaputt.de/gbatek-ds-cart-infrared-p-walker-ir-commands.htm)
- **PoroCYon pokewalker-rom-dumper**: DSi homebrew that talks to a walker through an IR cart. It dumps/restores the walker EEPROM, dumps walker internal flash via Grinberg's exploit, and dumps the cart IR MCU ROM/RAM. It documents the cart SPI commands and the 1 MHz requirement. — [zff.dev](https://zff.dev/PoroCYon/pokewalker-rom-dumper)
- **NESdev forum t=21140**: nocash and Shonumi's working notes (AUXSPI wiring, 1 MHz limit, 0x84 buffer, chip-ID IR flag ambiguity). — [NESdev](https://forums.nesdev.org/viewtopic.php?t=21140)
- **Flipwalker / FlippIR (Jackv-makes)**: Flipper Zero + Vishay TFBS4711 (or TFDU4101) on STM32 USART1 IrDA mode, 3.3 V, SD tied low. It runs lumirth's CC0 "pw" reconstruction of the walker firmware (via Stickwalker), and the author reports bidirectional Pokémon transfer with HGSS. TFBS4711 caveat: drive pulses ≥23 µs are clamped and the LED shuts off past 100 µs. — [Flipwalker](https://github.com/Jackv-makes/Flipwalker); [FlippIR-Hardware](https://github.com/Jackv-makes/FlippIR-Hardware)
- **picowalker (mamba2410)**: RP2350 recreation with "IrDA over PIO". — [picowalker](https://github.com/mamba2410/picowalker). ESP32 + MikroE IrDA 4 Click raw byte link. — [jarzadon123/pokewalker](https://github.com/jarzadon123/pokewalker) (README-level claims only)
- **Emulators**: PocketWalker (IR over TCP with a melonDS-IR fork), PokeStroller (IR to a DS emulator or another instance), pwemu (PoroCYon, WIP), Powar. Shonumi's 2025 survey lists melonDS IR as a WIP branch. — [PocketWalker](https://gh.r-mj.com/h4lfheart/pocketwalker); [PokeStroller](https://github.com/jpcerrone/pokestroller); [powar](https://github.com/UnrealPowerz/powar); [Shonumi, State of Emulation 2025](https://shonumi.github.io/articles/art40.html)
- **Hackaday 2026-04-06** (Etchy video): the walker holds only summary data. The game checks game version, region and trainer/secret IDs, and the full Pokémon (PID) stays in the save, so a "trapped" Pokémon cannot be recovered from the walker alone. — [Hackaday](https://hackaday.com/2026/04/06/rescuing-a-pokemon-off-a-pokewalker-after-losing-the-game-cartridge)

### Inferences
- What a hobbyist needs to talk to a Pokéwalker:
  - **Physical layer:** an IrDA SIR transceiver (TFBS4711/TFDU4101 class, 3.3 V) and a UART with SIR encode/decode at 115200 8N1. Alternatives are an MCU with a native IrDA mode (STM32 USART, H8 SCI), a PIO/bit-banged encoder producing about 1.6 µs pulses, or an HGSS/BW/B2W2 cart on a 1 MHz SPI master.
  - **Protocol layer:** XOR 0xAA, the 8-byte header, checksum with initial 2, the FA/F8 session handshake, and idle-gap packet framing.
  - **Will not work:** 38 kHz consumer-IR receivers/blasters, Flipper built-in IR, and any RF radio.

### Gaps
- The live problemkaputt.de GBATEK could not be fetched (connection refused). The mgba mirror may lag the current revision.
- Bulbapedia's page was blocked (403).
- The Arduino forum thread "Pokewalker and DS IR communication" (2010) was not reviewed.
