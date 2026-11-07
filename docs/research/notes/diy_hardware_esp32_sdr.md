# DIY Hardware Paths for Talking to a Pokéwalker (ESP32 focus, SDR relevance)

Research date: 2026-11-06. "Demonstrated" means the project's own README or write-up says it works. "Theoretical" means someone suggested it, or I am inferring it.

Signaling baseline used throughout: the Pokéwalker uses **IrDA SIR at 115,200 baud, 8N1**. Every byte is **XORed with 0xAA**. Packets have an 8-byte header (cmd, extra, 16-bit checksum, 32-bit session ID) and payloads of up to about 128 bytes. The walker sends a 0xFC advertising byte every few hundred ms. — [dmitry.gr PokéWalker hacking](https://dmitry.gr/?r=05.Projects&proj=28.%20pokewalker)

**Scope note (coordinator update):** the target setup is a **modified melonDS with IR support running on an ARM Linux SBC handheld** (Anbernic/Retroid class), with a DIY IR transceiver attached. The first section below compares the two hardware options for that setup. The SDR answer is kept short. The later sections keep the broader survey.

## Linux handheld setup: TFDU4101 wired straight to a SoC UART vs. a small MCU bridge (ESP32-S2/S3, RP2040) over USB-CDC

### Takeaway
**Use the MCU bridge over USB-CDC.** A TFDU4101-class transceiver cannot be driven by a plain UART:
- It needs 3/16-bit SIR pulses.
- Its TXD watchdog cuts the LED after more than 50 µs high.

Linux lost its IrDA stack (and the N_IRDA line discipline users) in 4.17. So even SoC UARTs with hardware SIR mode (e.g., DesignWare 8250_dw's SIRE bit, toggled only via the N_IRDA ldisc hook) are hard to enable from userspace. Handhelds also typically expose only an internal debug-console UART header.

An RP2040 or ESP32-S3 bridge:
- does the SIR encoding and timing
- filters the transceiver's self-echo
- can absorb jitter or keepalive
- shows up as a driverless `/dev/ttyACM*` that melonDS opens with plain termios

That costs about 1-2 USB frames (1 ms each) of latency and roughly a thumbnail-sized board. The walker protocol tolerates far more: transport stalls of 250 ms succeeded in hachistep's melonDS bridge tests, while 3 s failed. Direct UART is viable only with an external SIR encoder chip (MCP2122) or a ready-made serial IrDA board, and still means opening the handheld and freeing the console UART.

### Cited Findings

**Why a bare transceiver on a plain UART does not work**
- The TFDU4101 has no encoder. TXD is a Schmitt-trigger input that drives the IRED directly, and "an on-chip protection circuit disables the LED driver if the TXD pin is asserted for longer than 50 µs (max. 300 µs)." RXD is an active-low push-pull output with **echo-on** during transmission. Supply is 2.4-5.5 V, idle current 0.07 mA, shutdown <1 µA. Package is 4 × 9.7 × 4.7 mm SMD. — [Vishay TFDU4101 datasheet](https://www.vishay.com/docs/81288/tfdu4101.pdf)
- SIR ENDEC behaviour: "a zero logic level is transmitted as high pulse of 3/16th duration of the selected baud rate bit period." Software must handle turnaround delays because the UART does not. — [Samsung S3F401F manual, IrDA SIR operation](https://www.manualsdir.com/manuals/152717/samsung-s3f401f.html?page=247) (generic SIR reference, not Pokéwalker-specific)
- An external encoder exists: the Microchip **MCP2122** is a stand-alone IrDA encoder/decoder between a UART and an IR transceiver. It is IrDA Physical Layer 1.3 compliant and pin-compatible with the HSDL-7000. Baud rate equals the 16XCLK input / 16, maximum 115.2 kbaud, 1.8-5.5 V, 8-pin PDIP/SOIC. — [MCP2122 datasheet (Farnell copy)](https://www.farnell.com/datasheets/60236.pdf); [radiolocman listing](https://www.radiolocman.com/datasheet/data.html?di=479267)
- A ready-made board: Irdroid's **IrDA PiHat** is an IrDA SIR transceiver HAT for Raspberry Pi that "works over a serial port at 9600 to 115200 baud." — [Tindie Irdroid IrDA PiHat](https://tindie.com/products/irdroid/irda-pihat) (via search summary; not tested with a Pokéwalker)

**Linux kernel side**
- The Linux IrDA network stack and drivers were deleted ("staging: irda: remove the irda network stack and drivers", March 2018). Linus noted the 4.17-rc1 pull deleted more lines than it added thanks to the IrDA removal. Leftover sysctl and docs were cleaned up in staging-4.17-rc3. — [zx2c4 linux-dev commit](https://git.zx2c4.com/linux-dev/commit/kernel?id=edf5c17d866eada03b8750368a12dc3def77d608); [LKML staging fixes 4.17-rc3](https://lkml.iu.edu/hypermail/linux/kernel/1804.3/04593.html)
- `8250_dw` (Synopsys DesignWare UART, common on ARM SoCs) gained IrDA SIR support in 2016 (commit 0e0b989e, Ed Blake). It adds a `set_ldisc` hook that sets or clears the **SIRE** bit in MCR when the line discipline switches to IrDA. It checks the SIR capability bit in the component parameter register, and reviewers noted that "not all implementations based on 8250_dw support IRDA feature." — [android-kvm mirror of commit](https://android-kvm.googlesource.com/linux/+/0e0b989eb330f0167c191a5c223be352f348c9c0%5E%21); [LKML review](https://lkml.iu.edu/hypermail/linux/kernel/1610.3/03806.html)
- `drivers/usb/serial/ir-usb.c` ("USB IR Dongle" driver) still exists in recent trees. It exposes a USB IrDA bridge-class adapter as a "dumb" serial port, matching by interface class, with one bulk-in and one bulk-out endpoint. — [wireguard-linux tree ir-usb.c](https://git.zx2c4.com/wireguard-linux/tree/drivers/usb/serial/ir-usb.c); [Android common kernel ir-usb.c](https://android.googlesource.com/kernel/common/+/4df1d2ffe176/drivers/usb/serial/ir-usb.c)

**Handheld UART availability (Anbernic example)**
- The Anbernic RG35XX H (Allwinner H700) has an internal serial header between the left SD slot and the left speaker, pin order GND, TX, RX, GND. Opening the case voids the warranty. — [linux-sunxi RG35XX H](https://linux-sunxi.org/Anbernic_RG35XX_H)
- Mainline device trees for the RG35XX line use that UART as the **kernel console** (`stdout-path = "serial0:115200n8"`). — [RG35XX-2024 DTS](https://android-kvm.googlesource.com/linux/+/0ea32f50b36fd0372b3232db85d340294d7f0a8a/arch/arm64/boot/dts/allwinner/sun50i-h700-anbernic-rg35xx-2024.dts); [kernel DTS commit](https://lab.nexedi.cn/kirr/linux/-/commit/0923a6c604fc68300d9b9f8e1205d9abd3025cf6)
- The RG35XX SP has a different serial pad layout. — [macromorgan blog](https://macromorgan.blogspot.com/2024/05/anbernic35xxspinfoextract.html)

**USB-CDC latency and Linux access**
- The FTDI `ftdi_sio` driver defaults `latency_timer` to **16 ms**, tunable to 1 ms via sysfs or `ASYNC_LOW_LATENCY`. This only matters if the user picks a USB-UART bridge chip plus an external SIR encoder rather than a CDC-ACM MCU. A 2026 patch series to make sysfs writes authoritative was still under review. — [anyserial Linux tuning](https://graysonbellamy.github.io/anyserial/linux-tuning/); [LKML ftdi_sio latency_timer patch (2026)](https://lkml.iu.edu/2607.2/12003.html)
- Full-speed USB bulk packets are a maximum of 64 bytes. CDC example throughput is about 300 kB/s on Linux, orders of magnitude above the walker's about 11.5 kB/s. — [Nordic DevZone CDC ACM speed](https://devzone.nordicsemi.com/f/nordic-q-a/83705/usb-cdc-acm-max-transfer-speed/348043)
- A caution: an Arch Linux ARM thread reported worst-case cdc_acm read delays of about 160-800+ ms on Raspberry Pi hardware. — [archlinuxarm forum](https://archlinuxarm.org/forum/viewtopic.php?f=65&p=54834&t=11361) (single anecdotal report; cause not established)
- ESP32-S3 has two USB paths. The fixed-function USB_SERIAL_JTAG (CDC console on the internal PHY) is one. USB-OTG via TinyUSB is the other, and it cannot coexist with the ROM CDC console. One user reported TinyUSB CDC reads under 50 KiB/s on IDF 5.2, which is still above the walker's ~11.5 kB/s. — [ESP-IDF USB OTG Console (ESP32-S3)](https://docs.espressif.com/projects/esp-idf/en/stable/esp32s3/api-guides/usb-otg-console.html); [idf-extra-components issue #311](https://www.github.com/espressif/idf-extra-components/issues/311)

**Protocol timing tolerance (the number that decides whether latency matters)**
- hachistep PR #15 (melonDS to emulated walker via GDB stub and RAM mailbox) reports:
  - registration takes 13-18 s and return about 4.5 s
  - **injected 250 ms stalls during registration completed**, but a sustained 3 s interruption ended in error
  - the bridge sends **local `0x2E` frames to cover transport stalls at each endpoint**
  - maintenance ends after "three seconds without application traffic"
  — [hachistep PR #15](https://github.com/lumirth/hachistep/pull/15)
- In contrast, RtcPwalker's extra ARM7-to-ARM11 RTCom hop makes the 3DS link "slow and unstable," and retries are needed. — [RtcPwalker](https://github.com/francesco265/RtcPwalker)

**Reusable firmware and hardware**
- **picowalker** implements "IrDA over PIO via Dmitry Gr." on RP2040/RP2350 (Waveshare RP2040/RP2350 touch-LCD boards plus custom picowalker hardware). It already uses TinyUSB, but only for mass-storage save backup, and `/dev/ttyACM0` only for debug output. No USB IR bridge mode exists. Its PIO SIR code is the most directly reusable RP2040 component. — [github.com/mamba2410/picowalker](https://github.com/mamba2410/picowalker)
- **FlippIR-Hardware** is an open board design: TFBS4711 with R/C supply filtering, an LED bulk cap, and a TX pull-down so the LED stays dark at boot. The transceiver circuit is a good template. — [FlippIR-Hardware](https://github.com/Jackv-makes/FlippIR-Hardware)
- **PocketWalker** speaks TCP to melonDS-IR and plans a "Serial IR Communication Mode." Its byte-stream conventions are the obvious interface to match. — [PocketWalker](https://github.com/h4lfheart/PocketWalker)
- No existing Pico or ESP32 "USB-IrDA dongle" firmware was found. A search for Pico PIO IrDA SIR projects found only NEC/38 kHz remote examples. — [pico-examples PIO IR PR](https://github.com/raspberrypi/pico-examples/pull/176/files); [GitHub irda topic](https://github.com/topics/irda)

**Size**
- Seeed XIAO ESP32S3 is 21 × 17.5 mm (some listings say 17.8). The XIAO family shares the footprint, so a XIAO RP2040 is likely the same size (inferred by Components101). — [Components101 XIAO ESP32S3](https://components101.com/development-boards/xiao-esp32-s3-sense-datasheet-pinout); [Seeed XIAO ESP32S3 (Core Electronics)](https://core-electronics.com.au/seeed-studio-xiao-esp32s3.html)

### Inferences

**Comparison matrix** (for the handheld use case):

| | (a) TFDU4101 → SoC UART directly | (a′) USB-UART chip + MCP2122 + TFDU4101 | (b) MCU bridge (RP2040 / ESP32-S2/S3) + TFDU4101/TFBS4711 over USB-CDC |
|---|---|---|---|
| Works without kernel hacks? | Only if the SoC UART has SIR **and** you can set SIRE. With no N_IRDA ldisc registered post-4.17, that likely needs a small kernel module or devmem register poke. Otherwise you need an MCP2122 between UART and transceiver. | Yes. MCP2122 does the 3/16 encoding and needs a 1.8432 MHz 16× clock for 115200. | Yes. The MCU does the SIR encoding (ESP32 `UART_MODE_IRDA`, RP2040 PIO). |
| Linux device | `/dev/ttyS*` (must remove `console=` from cmdline and stop getty) | `/dev/ttyUSB*` (FTDI: set latency_timer=1) or `/dev/ttyACM*` | `/dev/ttyACM*` (cdc_acm, driverless) |
| Latency | Lowest (tens of µs; 1 byte = 86.8 µs on air) | 1 ms USB frame plus FTDI timer (16 ms default) | About 1-2 ms per direction (USB FS 1 ms frames; inference, not measured) |
| Self-echo | Emulator must discard echoed TX bytes | Same | MCU can strip echo before forwarding |
| Physical | Open case, solder to internal header, route IR window outside | External dongle on USB-C OTG | External dongle on USB-C OTG (needs OTG host + 5 V; most Linux handhelds support it, verify per model) |
| Size | Transceiver only (about 10 × 5 mm) plus wires | Bridge chip + MCP2122 + crystal + transceiver | XIAO-size (21 × 17.5 mm) board + transceiver |
| Power | Transceiver about 0.07 mA idle | Bridge chip tens of mA | MCU tens of mA while active (unverified figure); can sleep or SD-shut the transceiver when idle |
| Difficulty | High (internal mod plus kernel/register work) | Medium (extra chip and clock) | Low-medium (firmware is about 100-300 lines; reuse picowalker PIO or ESP-IDF IrDA mode) |

- **Why (b) wins for this use case:** latency is not the constraint (a 1-2 ms USB hop is about 0.5-1% of the 250 ms stall budget hachistep showed works). The constraints are SIR encoding, echo handling, and not opening the handheld. The MCU can also synthesize keepalive or advertise traffic locally (as hachistep's `0x2E` frames do) if melonDS frame pacing causes gaps, for example during emulator stutter or fast-forward.
- **Emulator-side interface:** have melonDS open `/dev/ttyACM0`, call `cfmakeraw()`, set the baud (ignored by CDC-ACM but harmless) and `VMIN=0, VTIME=0` non-blocking, then poll each frame or from a thread. Keep the bridge a transparent byte pipe at the SIR byte level. The 0xAA XOR, checksum, and session handling are end-to-end between HGSS and the walker, so the bridge must not touch them. Optionally add a tiny out-of-band framing (e.g., a SLIP-style escape) only if you later want timestamps or link-quality reports. Matching PocketWalker's TCP byte-stream semantics lets the same melonDS code path talk to either the emulated walker (TCP) or real hardware (serial).
- **Chip choice:**
  - **RP2040 (e.g., XIAO RP2040, RP2040-Zero):** cheapest, with deterministic PIO SIR. picowalker's PIO code can be lifted, and TinyUSB CDC is mature. No radio, so lower idle draw than an ESP32.
  - **ESP32-S3:** native USB plus hardware `UART_MODE_IRDA` (documented on classic ESP32; verify on S3). Wi-Fi is available but unnecessary.
  - **ESP32-S2:** native USB-OTG (TinyUSB only, no USB-Serial-JTAG). Same IrDA caveat.
- **Retroid caveat:** Retroid Pocket devices ship Android rather than a mainline-style Linux userspace (general knowledge, not verified here). On those, USB serial needs Android USB-host APIs or root, while Anbernic/Knulli/ROCKNIX-style Linux images expose `/dev/ttyACM*` directly if `cdc_acm` is built in. Check the specific firmware's kernel config.
- **Generic USB IrDA dongles** (MCS7780/STIR4200-type) relied on the IrDA network-stack drivers removed in 4.17. Only "bridge-class" dongles handled by `ir-usb` still appear as tty devices. Whether any such dongle passes raw 115200 SIR bytes cleanly enough for a Pokéwalker is untested. A DIY MCU bridge is more predictable.

### Gaps
- I did not verify whether the Allwinner H700's (or the Rockchip RK3566's) UART IP has the DesignWare SIR option synthesized, or whether any mainline kernel can still enable SIRE without N_IRDA.
- No measured round-trip latency for cdc_acm on an ARM handheld was found. The 1-2 ms figure is an inference from USB full-speed 1 ms frame scheduling.
- The raw HGSS/walker protocol timeouts are not documented anywhere I found. hachistep's 250 ms success was with local keepalive frames, so the bare protocol's per-packet timeout may be shorter.
- No sourced power figures for RP2040 or ESP32-S3 active current were collected this session.
- Whether ESP32-S2/S3 UARTs support `UART_MODE_IRDA` the same way as classic ESP32 was not confirmed.

## Can an SDR (RTL-SDR, HackRF, etc.) receive or transmit the Pokéwalker's IR link?

### Takeaway
No, and it is not relevant to this build. The link is unmodulated near-IR light pulses (IrDA SIR, 115.2 kbaud), about 300+ THz. SDRs tune radio-frequency fields through an antenna, from kHz to a few GHz. Detecting the link needs a photodiode, and once you have one plus a comparator (i.e., a $3 IrDA transceiver), the SDR adds nothing. It is receive-only for this purpose, and it adds cost and latency.

### Cited Findings
- The Pokéwalker uses SIR signaling at 115,200 baud 8N1, captured with a "generic SIR-compatible IR transceiver." — [dmitry.gr](https://dmitry.gr/?r=05.Projects&proj=28.%20pokewalker)
- IR light is "far above the tuner's frequency range." The IR sensor on some RTL-SDR (DVB-T) dongles is a separate remote-control receiver read via the kernel DVB driver, not via the SDR path. — [R. X. Seger, Medium (search summary; fetch 403)](https://medium.com/@rxseger/receiving-ir-signals-with-rtl-sdr-dongles-5a8658a44b90)
- RTL-SDR direct sampling feeds the ADC directly (about 0-14.4 MHz, about 28.8 MHz with filtering) and bypasses protection circuitry. That is the only way a photodiode signal could reach an RTL-SDR. — [rtl-sdr.com](https://www.rtl-sdr.com/?p=209)
- 38 kHz consumer-IR receivers, like the one on those dongles or on a Flipper, "only see carrier bursts," so they cannot hear Pokéwalker links. — [FlippIR-Hardware](https://github.com/Jackv-makes/FlippIR-Hardware)

### Inferences
- A photodiode feeding RTL-SDR direct sampling with software SIR decoding is physically possible as a receive-only sniffer, but it is not demonstrated and has no advantage over a transceiver plus MCU. HackRF TX emits RF, not light.

### Gaps
- No published SDR-based IrDA SIR reception experiment was found. The RTL-SDR (about 24-1766 MHz) and HackRF (about 1 MHz-6 GHz) ranges are general knowledge, not fetched.

## What existing microcontroller projects talk to a Pokéwalker or to HGSS?

### Takeaway
As of Nov 2026 the active projects are almost all **"fake walker" recreations that talk to a real HGSS game**: Stickwalker (ESP32-S3), Flipwalker (Flipper Zero), and picowalker (RP2040/RP2350). They run on top of a now-complete matching decompilation of the walker firmware (lumirth/pw). The "act as the DS/HGSS side toward a real walker" role (watts injection, EEPROM/ROM dump, gifting) is demonstrated only by Dmitry Grinberg's PalmOS app and by DSi/3DS-based dumpers and patches. No finished Arduino, ESP32, Pico, or Flipper project that dumps or injects watts into a *real* walker over IR was found. Software emulators (PocketWalker, hachistep, PokeStroller, powar) handle the PC side.

### Cited Findings

**Demonstrated: fake walker talking to real HGSS**
- **Stickwalker (lumirth)**: "A Pokéwalker firmware port for the M5Stack Stick S3" (ESP32-S3; repo topics include esp32-s3). It ports the author's matching firmware reconstruction. MIT license. Parts: "a Stick S3, a BPV10NF photodiode and a USB-C data cable." Wiring: "photodiode's anode to GND and cathode to G5." — [github.com/lumirth/stickwalker](https://github.com/lumirth/stickwalker)
  - TX uses the Stick's built-in IR transmitter ("the stock transmitter in the Stick is sufficient"). The Stick's built-in IR receiver is "functionally incapable of *receiving*" Pokéwalker signals, so a bare photodiode replaces it. The project is called experimental, and battery life is "days instead of weeks or months." — [kukas.me/stickwalker](https://kukas.me/stickwalker)
  - The 2026-10-10 prerelease fixes a peer-play connection bug. Its notes say it is still pending physical-device tests. — [Stickwalker release candidate-2026-10-10](https://github.com/lumirth/stickwalker/releases/tag/candidate-2026-10-10)
  - The firmware's decoding method on the ESP32-S3 (UART IrDA mode, RMT, or GPIO capture) is **not stated** on either page.
- **Flipwalker (Jackv-makes)**: a Flipper Zero app that ports Stickwalker's reconstruction. Two-way IrDA with HGSS is verified ("sent a Pokemon out for a stroll and brought it back"). It counts steps with an external I2C accelerometer and loads a 64 KB EEPROM dump from a real walker as a save. — [github.com/Jackv-makes/Flipwalker](https://github.com/Jackv-makes/Flipwalker)
  - Why it needs an add-on: "The Flipper's IR handles only 38kHz remote-control signals. The Pokewalker uses IrDA SIR." It uses the STM32 USART1's built-in IrDA encoder/decoder with an external Vishay TFBS4711 (TFDU4101 also works) on GPIO pins 13/14 (PB6/PB7), with SD tied to GND. — [Flipwalker README](https://github.com/Jackv-makes/Flipwalker)
  - **FlippIR-Hardware** board: TFBS4711-TR1, LIS2DE12 accelerometer, MBR0520 reverse-protection Schottky, and a 10-pin header. Bare PCBs are on PCBWay. The TFBS4711 "limits long marks," so long marks must be sent as pulse chains. The board notes say the DS side of the protocol is documented, so the board "could in principle" read or write a real walker, but that is **not built or tested**. — [github.com/Jackv-makes/FlippIR-Hardware](https://github.com/Jackv-makes/FlippIR-Hardware)
- **picowalker (mamba2410)**: a faithful recreation on RP2350 (the earlier core targeted RP2040/Pico). It has an SH8601Z-driven OLED, BMA400 accelerometer, M95512 64 KB EEPROM, and BQ25628E PMIC. "IrDA over PIO, based on Dmitry Gr.'s original Pokewalker hack." USB mass storage handles save backup. The README does not state the IR transceiver part number. — [github.com/mamba2410/picowalker](https://github.com/mamba2410/picowalker); [picowalker-core (kandi summary)](https://kandi.openweaver.com/c/mamba2410/picowalker-core)
- **lumirth/pw**: a human-readable *matching* decompilation of the walker firmware (CC0). It builds a byte-identical binary given retail artwork and the Renesas HEW toolchain, and is the base layer for Stickwalker and Flipwalker. — [github.com/lumirth/pw](https://github.com/lumirth/pw)

**Early / partial ESP32 work**
- **jarzadon123/pokewalker**: "integrates an esp32 and irda4 click to transmit and receive IR signals" (MikroE IrDA 4 Click). It has achieved "raw byte-level transmission and reception" and passed a mirror optical-loopback test. Display, IMU, buttons, and power are still to do. It has 5 commits and no PC bridge. The README does not say whether it uses UART IrDA mode, RMT, or bit-bang. — [github.com/jarzadon123/pokewalker](https://github.com/jarzadon123/pokewalker)

**Demonstrated: DS/master side toward a real walker (not microcontroller-based)**
- **Dmitry Grinberg's WalkePoker** (PalmOS 4, Palm m500-series IrDA). It dumps ROM to SD, gifts event Pokémon and items, creates special routes, and adds 9,999 watts. It does this through a decompression-overflow exploit (cmd 0x00/0x80) and CMD_06 arbitrary RAM write, jumping via a pointer at 0xF7E0 and calling addWatts at 0x1F3E. Initial sniffing used an STM32F429 with a generic SIR transceiver. — [dmitry.gr](https://dmitry.gr/?r=05.Projects&proj=28.%20pokewalker); [Hackaday coverage](https://hackaday.com/2020/11/21/reverse-engineering-a-pokewalker/)
- **RtcPwalker**: a patch that lets HGSS on a 3DS use the 3DS's built-in IR transceiver (via RTCom, ARM7 to ARM11, libn3ds I2C) instead of the cartridge IR. It is experimental and tested only on Old 3DS. Communication is "slow and unstable because RTCom adds significant overhead." — [github.com/francesco265/RtcPwalker](https://github.com/francesco265/RtcPwalker)
- Established EEPROM dump methods are PoroCYon's DSi/3DS dumper and Dmitry's PalmOS app. A USB-IrDA-dongle dump method was "hoped for" but not available at the time of the thread. — [Project Pokémon "Seeking PokeWalker EEPROM Dumps"](https://projectpokemon.org/home/forums/topic/62695-seeking-pokewalker-eeprom-dumps/) (via search summary)
- A wired alternative is to hardwire 3.3 V and GND to the walker and read SPI or TX/RX with an Arduino. The M95512 EEPROM can be dumped over SPI (Dmitry confirmed the IR dump matched the SPI dump). — [GBAtemp PokeWalker Hacking thread](https://gbatemp.net/threads/pokewalker-hacking.419462/) (via search summary); [dmitry.gr](https://dmitry.gr/?r=05.Projects&proj=28.%20pokewalker); [mamba2410/reverse-pokewalker](https://github.com/mamba2410/reverse-pokewalker)

**Commercial "fake/alternate HGSS cart" path**
- **DS Pico "IR"** flash cart (Phenomods, posted 2026-09-08): it adds an IR transceiver "compatible with pokewalker" so HGSS on a flash cart can link. It costs about $10 more than the base DS Pico. The MCU and transceiver are unspecified. — [RetroRGB](https://retrorgb.com/ds-pico-ir-flash-cart-for-nintendo-ds.html)

**Failed or naive attempts (useful as warnings)**
- An Arduino forum reply suggested a TSOP2138-type tuned 38 kHz receiver. That does not match SIR (see the transceiver section). — [Arduino forum "Pokewalker and DS IR communication"](https://forum.arduino.cc/t/pokewalker-and-ds-ir-communication/17191)
- A GBAtemp user's Arduino Leonardo IR reader was suspected too slow to capture all the data. — [GBAtemp](https://gbatemp.net/threads/pokewalker-hacking.419462/) (via search summary)

### Inferences
- For a hobbyist who wants a working ESP32 device today, **Stickwalker on an M5Stack Stick S3 with one photodiode is the lowest-effort demonstrated ESP32 path**. It is a fake walker, not a bridge.
- The "microcontroller acting as the DS toward a real walker" role is open. The protocol is fully documented (Dmitry's write-up plus the pw decomp), and FlippIR's author calls it feasible. Expect to write the master-side handshake (0xFA/0xF8 session negotiation, checksum, XOR) yourself.

### Gaps
- I did not verify whether a Flipper Zero app exists that acts as the DS side toward a real walker. Search found none.
- picowalker's IR transceiver part, and whether picowalker is confirmed against real HGSS, are not stated in its README.
- The underlying transceiver chip on the MikroE IrDA 4 Click is not stated in the jarzadon123 README.
- No Raspberry Pi (Linux) plus IrDA-transceiver project was found. Linux removed its IrDA stack in kernel 4.17 (general knowledge, not verified here), so a Pi would bit-bang or use a UART with an external SIR encoder.

## ESP32 specifics: UART IrDA mode, RMT, transceiver choice, timing

### Takeaway
ESP32 UARTs have a hardware IrDA SIR mode (`UART_MODE_IRDA` via `uart_set_mode()`), and that is the natural fit for 115,200-baud SIR. Forum reports show it can be finicky: receive needs the duplex bit, transceivers echo, and UART2 was flaky on some boards. Use a true **IrDA SIR transceiver (Vishay TFDU4101 or TFBS4711)**, not a 38 kHz TSOP consumer-IR receiver. A 38 kHz demodulator cannot see SIR pulses at all, which is why both the Flipper and M5Stick built-in receivers fail. RMT or GPIO-capture approaches are plausible fallbacks but are undocumented for this use.

### Cited Findings
- ESP-IDF: the UART controllers "can also support Infrared Data Association (IrDA) protocols." `uart_mode_t` includes `UART_MODE_IRDA`, set with `uart_set_mode()` *after* `uart_driver_install()`. Inversion flags `UART_SIGNAL_IRDA_TX_INV` and `UART_SIGNAL_IRDA_RX_INV` exist. The page lists no IrDA-specific limitations. — [ESP-IDF UART docs (ESP32)](https://docs.espressif.com/projects/esp-idf/en/stable/esp32/api-reference/peripherals/uart.html)
- `UART_MODE_IRDA` = 0x02 in `uart_types.h`. — [SourceVu esp-idf symbol](https://sourcevu.sysprogs.com/espressif/esp-idf/symbols/uart_mode_t/UART_MODE_IRDA)
- esp32.com "How to wire for IrDA?" thread (about 2017-2018, register-level) reports:
  - IrDA was enabled by setting UART2 config bits directly from Arduino, because the IDF API was not reachable there.
  - TX worked with one bit, but RX worked only once the **UART_IRDA_DPLX** duplex bit was also set.
  - One user got junk bursts and wondered if a 38 kHz carrier was being added.
  - Another suspected a UART2 problem on newer boards.
  - A working TFDU4101 link reached 5 mm to 3 m at 3.3 V and up to 4 m at 5 V.
  — [esp32.com thread (search-result summaries; direct fetch blocked by bot check)](https://esp32.com/viewtopic.php?p=38000); [esp32.com p=90729](https://esp32.com/viewtopic.php?p=90729)
- **TFDU4101** datasheet facts:
  - SIR at 115.2 kbit/s, IrDA physical-layer compliant, link 0 to ≥1 m, 2.4-5.5 V, 0.07 mA idle, <1 µA shutdown.
  - Pins: VCC2/IRED anode, IRED cathode, TXD (Schmitt-trigger input, active high), RXD (push-pull CMOS output, **active low**, no pull-up needed), SD (shutdown, active high), VCC1, GND.
  - "During transmission the RXD output is active (**echo-on**)."
  - An on-chip protection circuit **disables the LED if TXD is high longer than 50 µs (max 300 µs)**.
  — [Vishay TFDU4101 datasheet](https://www.vishay.com/docs/81288/tfdu4101.pdf)
- Flipwalker and FlippIR use the **TFBS4711** (TFDU4101 also works) directly on an MCU UART that has a built-in IrDA encoder/decoder. The TFBS4711 limits long marks, so non-SIR (Game Boy) signals must be sent as pulse chains. — [Flipwalker](https://github.com/Jackv-makes/Flipwalker); [FlippIR-Hardware](https://github.com/Jackv-makes/FlippIR-Hardware)
- 38 kHz consumer IR receivers do not work: "The Flipper's built-in IR is a 38 kHz remote-control port that only sees carrier bursts, so it can't hear Game Boy or Pokéwalker links." — [FlippIR-Hardware](https://github.com/Jackv-makes/FlippIR-Hardware). The M5Stick S3's built-in receiver is likewise "functionally incapable of receiving" walker signals. — [kukas.me/stickwalker](https://kukas.me/stickwalker)
- A bare photodiode (BPV10NF) on an ESP32-S3 GPIO, with the stock IR LED for TX, is enough for a working walker link (Stickwalker). This shows that a full IrDA transceiver is not strictly required on ESP32-S3. — [stickwalker README](https://github.com/lumirth/stickwalker)
- On RP2040/RP2350, picowalker implements IrDA in **PIO**, not with a UART IrDA mode. The RP2040 UART has no SIR encoder (inferred from the PIO choice; not directly stated). — [picowalker](https://github.com/mamba2410/picowalker)

### Inferences
- **Recommended ESP32 receive/transmit chain:** ESP32 UART (UART1 or UART2 on classic ESP32, or any UART on S3/C3 if IrDA mode is present on that variant; verify per-chip) at 115200 8N1 in `UART_MODE_IRDA`, connected to TFDU4101 or TFBS4711 TXD/RXD with SD tied low. If polarity is wrong, use the `UART_SIGNAL_IRDA_RX_INV`/`TX_INV` flags. Set (or confirm the driver sets) the duplex bit if RX fails. Discard self-echo bytes after each transmit, because the transceiver echoes. Apply the 0xAA XOR and the Dmitry checksum in software.
- **Timing:** standard IrDA SIR encodes each 0 bit as a 3/16-bit-period pulse, about 1.63 µs at 115.2 kbaud. That is well within ESP32 UART IrDA, RMT (80 MHz APB clock, sub-µs resolution), or a fast GPIO ISR. It is general IrDA knowledge, not verified from a primary source this session. The TFDU4101's 50 µs TXD watchdog means you must never hold TXD high with a non-encoded (raw UART) signal: a raw idle-low/active-high UART "0" byte lasts about 78 µs and would trip it. This is why the UART's IrDA encoder, or RMT-generated short pulses, is required rather than a plain UART on TXD.
- **RMT as a fallback:** RMT TX can emit arbitrary short pulse trains (no carrier), and RMT RX can timestamp edges. A software SIR encoder/decoder on RMT is feasible if `UART_MODE_IRDA` misbehaves on a given chip. This approach is **theoretical**: no Pokéwalker project documented using RMT.
- **Which ESP32:** ESP32-S3 has native USB-OTG/USB-Serial-JTAG, which matters for a PC bridge, and it is proven by Stickwalker. Classic ESP32 has the documented IrDA mode but needs a USB-UART bridge chip.

### Gaps
- I did not confirm whether `UART_MODE_IRDA` is supported and documented on ESP32-S3, -C3, or -C6 (only the classic ESP32 page was fetched).
- I did not find an ESP-IDF GitHub issue documenting IrDA bugs. The forum reports are old and register-level.
- Stickwalker's exact IR decode method (UART IrDA, RMT, or GPIO) is not documented on its README or blog page. Reading its source would answer this.
- TFBS4711 datasheet specs were not fetched. The TFBS4711 is believed to be the smaller, lower-voltage sibling of the TFDU4101 (general knowledge).

## How would an ESP32 bridge to a PC/emulator? Existing bridge software

### Takeaway
No existing ESP32 "IR modem" firmware for Pokéwalker-to-emulator bridging was found. On the emulator side, the hooks exist:
- **melonDS-IR** (Ceravia fork) talks TCP to the **PocketWalker** emulator. It also needs Qt SerialPort to build, which suggests a serial IR transport.
- **PocketWalker** lists "Serial IR Communication Mode" as planned.
- **hachistep** has an open PR connecting walkers to stock melonDS via the GDB stub.

A DIY bridge would be a transparent UART-IrDA to USB-CDC (or TCP) byte pipe. The main risk is protocol timing: added latency demonstrably makes walker links "slow and unstable" (RtcPwalker).

### Cited Findings
- **PocketWalker** (h4lfheart): H8/38606F emulator. Current feature: "IR Communications over TCP with melonDS-IR". Planned: "Serial IR Communication Mode" and UDP. No hardware bridge support is mentioned. — [github.com/h4lfheart/PocketWalker](https://github.com/h4lfheart/PocketWalker)
- **melonDS-IR**: "Fork of the melonDS emulator that support IR functionality" by Ceravia. A tutorial video notes it "requires Qt-Serial to build." The video also links a "picowalker-sdl-tcp" fork of mamba's code. A Feb 2026 forum thread shows users struggling to build it (no prebuilt binaries). — [github.com/Ceravia/melonDS-IR](https://github.com/Ceravia/melonDS-IR); [YouTube "Pokewalker on melonDS modes, tutorial, updates" (via search snippet)](https://www.youtube.com/watch?v=2EzZ1mB50lU); [melonDS board thread 2079](https://melonds.kuribo64.net/board/thread.php?id=2079)
- **hachistep PR #15**: "Connect walkers to stock melonDS with a live cartridge mailbox." It reads a cartridge mailbox in RAM through melonDS 1.1's ARM9 GDB stub and keeps the retail IR driver and protocol. It is an open PR. hachistep itself is an alpha Rust walker emulator core (MIT). — [hachistep PR #15](https://github.com/lumirth/hachistep/pull/15); [github.com/lumirth/hachistep](https://github.com/lumirth/hachistep)
- **Pusty/PokewalkerUtils**: scripts for emulating Pokéwalker communication in DeSmuME and extracting EEPROM assets. — [github.com/Pusty/PokewalkerUtils](https://github.com/Pusty/PokewalkerUtils)
- **PokeStroller**: Windows Pokéwalker emulator with IR emulation to a DS emulator or another instance. **powar**: prototype emulator (SDL2 or WASM) without IR support yet. — [github.com/jpcerrone/pokestroller](https://github.com/jpcerrone/pokestroller); [github.com/UnrealPowerz/powar](https://github.com/UnrealPowerz/powar)
- Latency evidence: RtcPwalker's added RTCom hop makes the link "slow and unstable," and users must retry, especially when sending a Pokémon. — [RtcPwalker](https://github.com/francesco265/RtcPwalker)

### Inferences
- **Architecture A (real walker to emulated HGSS):** real Pokéwalker, IR, ESP32 + TFDU4101 (UART IrDA, 115200), USB-CDC serial, melonDS-IR's serial mode, if it exists and accepts raw bytes. Alternatively a small PC shim converts serial to melonDS-IR's TCP protocol (the one PocketWalker speaks). The ESP32 firmware can be a dumb pipe; XOR and checksums are handled by the game and the walker end-to-end.
- **Architecture B (real HGSS cart to emulated walker):** a DS with real HGSS, IR, ESP32 bridge, PC, then PocketWalker over TCP (or its future serial mode).
- **Wi-Fi/TCP variant:** ESP32 runs a TCP server and forwards bytes. That is simple, but Wi-Fi jitter of several ms to tens of ms may break the handshake. USB-CDC, especially on ESP32-S3's native USB, should have lower and steadier latency. Prefer USB first and treat Wi-Fi as experimental.
- **Smarter bridge:** to tolerate latency, the ESP32 could answer time-critical link-layer exchanges locally (e.g., the 0xFC advertise and session handshake) and only relay payload packets. That needs protocol awareness and is **theoretical**.
- **Standalone tool (no emulator):** an ESP32 acting as master could reimplement Dmitry's WalkePoker features (EEPROM dump, watts, gifting) and stream dumps to the PC over USB. All protocol details are public. No one has published this for ESP32.

### Gaps
- melonDS-IR's actual IR transport modes, serial framing, and TCP wire protocol could not be read: README and src listings fetched lacked IR details. The Qt-Serial dependency is the only hint of serial support.
- No measurements of the walker protocol's timeout and latency tolerance were found. That number determines whether a Wi-Fi bridge is viable.
- I found no existing ESP32, Arduino, or Pico USB-IrDA bridge firmware aimed at Pokéwalker.

## Rough parts list and difficulty

### Takeaway
A minimal ESP32 Pokéwalker IR bridge or master needs:
- an ESP32 dev board (ESP32-S3 preferred for native USB)
- one Vishay IrDA SIR transceiver (TFDU4101 or TFBS4711) or a breakout such as MikroE IrDA 4 Click
- a few passives, a breadboard, and soldering for an SMD part

Hardware difficulty is low to moderate. The real effort is firmware and protocol work, plus emulator-side integration, which is still immature. For a fake walker rather than a bridge, Stickwalker (M5Stack Stick S3 + BPV10NF photodiode) or Flipwalker (Flipper + FlippIR board) are near plug-and-play.

### Cited Findings
- Stickwalker BOM: M5Stack Stick S3, BPV10NF photodiode, USB-C data cable. — [stickwalker](https://github.com/lumirth/stickwalker)
- FlippIR BOM: TFBS4711-TR1, LIS2DE12 (optional; LIS2DH12 also fits), MBR0520, 10-pin right-angle header, R/C filtering on the receiver supply, a bulk cap for the LED, a TX pull-down, and I2C pull-ups. Boards come via PCBWay (bare or PCBA). Flipwalker also supports LIS3DH, MPU-6050/6500/9250, and ADXL345 accelerometers. — [FlippIR-Hardware](https://github.com/Jackv-makes/FlippIR-Hardware); [Flipwalker](https://github.com/Jackv-makes/Flipwalker)
- jarzadon123 used ESP32 + MikroE IrDA 4 Click. — [jarzadon123/pokewalker](https://github.com/jarzadon123/pokewalker)
- TFDU4101 is an 8-pin SMD package (4 × 9.7 × 4.7 mm), 2.4-5.5 V. The IRED anode can be supplied separately, and an external resistor is needed only for IrDA low-power current reduction. — [TFDU4101 datasheet](https://www.vishay.com/docs/81288/tfdu4101.pdf)
- picowalker uses custom PCB hardware (picowalker-hardware v0.4) with RP2350, OLED, BMA400, M95512, and BQ25628E, which is far more involved. — [picowalker](https://github.com/mamba2410/picowalker)

### Inferences
- **Suggested ESP32 bridge BOM (theoretical; nobody has built and published it):**
  1. ESP32-S3 dev board (native USB-CDC)
  2. TFDU4101 or TFBS4711. The fine-pitch SMD needs an adapter board or a breakout such as MikroE IrDA 4 Click.
  3. About 0.1 µF + 4.7 µF decoupling, plus an optional series resistor or RC filter on VCC1 per the Vishay reference layouts
  4. A pull-down on TXD so the LED stays off during boot (FlippIR uses one)
  5. SD tied to GND
  6. Optional: a SPI clip or pogo pins for a wired M95512 EEPROM dump as a fallback
- **Difficulty:** hardware about 2/5 (SMD soldering is the hardest bit). Firmware for a transparent bridge about 2/5. Firmware for a standalone master (dump, watts) about 3-4/5, porting Dmitry's protocol and exploit. Emulator integration about 3-4/5, given undocumented melonDS-IR transport and build pain.
- **Cheapest demonstrated route to "use a walker with an emulator" today, with no custom hardware:** PocketWalker (emulated walker) connected to melonDS-IR over TCP, with no real IR involved. Real-hardware-to-emulator bridging remains DIY.

### Gaps
- No prices were found for any parts or kits (M5Stack Stick S3, TFDU4101, TFBS4711, IrDA 4 Click, FlippIR PCBA). Current distributor pricing should be checked.
- The FlippIR BOM CSV contents were not visible.
