# Android handheld to IrDA dongle transport for melonDS–Pokéwalker linking (USB-C vs Wi-Fi vs Bluetooth)

Scope: how an Android dual-screen handheld (AYN Thor, Ayaneo Pocket DS, Retroid with the dual-screen add-on) running melonDS for Android can reach a small MCU+IrDA dongle that pipes bytes to a real Pokéwalker. The goal is that end users need no root and don't open the case. Current as of 2026-11-06. Labels: **[SHIPPED]** means released code or product, **[DEMO]** means demonstrated or in a PR, **[INFERENCE]** means my reasoning.

Timing facts used throughout (sourced):
- The HGSS game side has a **100 ms reply deadline**, per the WatermelonDS developer notes, which model it on the pret/pokeheartgold decompilation (overlay 112 and libirc). — [WatermelonDS docs/POKEWALKER.md](https://github.com/silver115/WatermelonDS/blob/melonds-pokewalker/docs/POKEWALKER.md)
- WatermelonDS ends a received IR packet after **3.5 ms of link silence** (`kPacketGapUs = 3500`, "same value the real cartridge timing uses"). — [WatermelonDS PokewalkerIR.cpp](https://github.com/silver115/WatermelonDS/blob/melonds-pokewalker/app/src/main/cpp/pokewalker/PokewalkerIR.cpp)
- HachiStep PR #15: "Registration completes with three injected 250 ms transport stalls", but "A sustained 3-second interruption ends with an error." "Local `0x2E` frames cover transport stalls at each endpoint." Maintenance ends after "three seconds without application traffic." Registration takes 13–18 s and return about 4.5 s. — [hachistep PR #15](https://github.com/lumirth/hachistep/pull/15)

## Q1. USB-C: Android USB host plus CDC-ACM without root (usb-serial-for-android), melonDS-android integration, emulator precedents, latency, and handheld port specifics

### Takeaway
USB-C CDC-ACM is fully supported without root. usb-serial-for-android is a mature MIT-licensed library that auto-detects any CDC-ACM interface, and a `USB_DEVICE_ATTACHED` device filter gives a one-tap "open melonDS?" dialog that also grants permission. The melonDS-android C++ core already calls back into Kotlin over JNI for the camera. Dolphin's Android GameCube adapter is a shipped precedent for native emulator code doing USB I/O through Kotlin `UsbManager`. Latency is about 1 ms-class, far below the 100 ms deadline. The main costs are that every target handheld has **only one USB-C port**, and that no shipped Android melonDS build has a serial IR backend yet, so new app code is required.

### Cited Findings
**usb-serial-for-android (mik3y)**
- "No root access, ADK, or special kernel drivers are required; all drivers are implemented in Java." — [usb-serial-for-android README](https://github.com/mik3y/usb-serial-for-android)
- Drivers: FTDI FT232R/FT232H/FT2232H/FT4232H/FT230X/FT231X/FT234XD, Prolific PL2303, Silabs CP2102/CP210x, Qinheng CH340/CH341A, and generic CDC/ACM (CH343, CH9102, MCP2221, ATmega32U4, Digispark). "As of v3.5.0 this library detects CDC/ACM devices by USB interface types instead of fixed VID+PID." The current quick-start dependency is `com.github.mik3y:usb-serial-for-android:3.11.0`. — [README](https://github.com/mik3y/usb-serial-for-android)
- API: blocking `port.read(buf, timeout)` / `port.write(buf, timeout)`, or the event-driven `SerialInputOutputManager.onNewData()`. A `device_filter.xml` with a `USB_DEVICE_ATTACHED` intent filter enables attach notification. — [README](https://github.com/mik3y/usb-serial-for-android)
- License: the README links MIT (LICENSE.txt). A secondary summary describes it as LGPL 2.1, which probably reflects older versions. MIT and LGPL-2.1 are both GPL-3.0-compatible. — [README](https://github.com/mik3y/usb-serial-for-android); contrasting claim in [search-result summary of library listings](https://github.com/mik3y/usb-serial-for-android/wiki/Projects-Using-usb-serial-for-android)
- The README says nothing about latency or throughput. — [README](https://github.com/mik3y/usb-serial-for-android)

**Android platform USB host API**
- USB host mode has been supported since Android 3.1 (API 12). Apps declare `<uses-feature android:name="android.hardware.usb.host"/>`. — [Android USB host docs](https://developer.android.com/develop/connectivity/usb/host)
- Auto-launch and implicit permission: "When users connect a device that matches your device filter, the system presents them with a dialog that asks if they want to start your application. If users accept, your application automatically has permission to access the device until the device is disconnected." Filters can match on vendor-id/product-id or on class/subclass/protocol. — [Android USB host docs](https://developer.android.com/develop/connectivity/usb/host)
- Without the intent path, `UsbManager.requestPermission()` shows a permission dialog and returns the result through a broadcast with `EXTRA_PERMISSION_GRANTED`. — [Android USB host docs](https://developer.android.com/develop/connectivity/usb/host)
- Transfers use `bulkTransfer(ep, buf, len, timeout)` (synchronous) or `UsbRequest.queue()` plus `requestWait()` (asynchronous), off the UI thread. — [Android USB host docs](https://developer.android.com/develop/connectivity/usb/host)

**MCU-side USB compatibility**
- The ESP32-C3's built-in USB Serial/JTAG controller has a "CDC-ACM portion ... [that] implements a serial port". It is fixed-function hardware that can't be reconfigured. If the host isn't reading, output fills a small buffer and the chip pauses once for 50 ms. — [ESP-IDF USB Serial/JTAG console (ESP32-C3)](https://docs.espressif.com/projects/esp-idf/en/stable/esp32c3/api-guides/usb-serial-jtag-console.html)

**melonDS-android architecture (rafaelvcaetano)**
- GPL-3.0. The Kotlin app plus `melonDS-android-lib` (a git submodule of the core) build with NDK and CMake. "Local multiplayer" is listed under Missing Features. — [melonDS-android repo](https://github.com/rafaelvcaetano/melonDS-android)
- The native glue lives in `app/src/main/cpp/` and includes `PlatformAndroid.cpp`, `MelonDSAndroidJNI.cpp`, `JniEnvHandler.cpp`, `MelonDSAndroidCameraHandler.cpp`, `AndroidMelonEventMessenger.cpp` and others. — [melonDS-android tree (GitHub API)](https://api.github.com/repos/rafaelvcaetano/melonDS-android/git/trees/master?recursive=1)
- Precedent for C++→Kotlin callbacks inside the core: `Platform::Camera_CaptureFrame` calls `cameraHandler->captureFrame()`. That function uses `JniEnvHandler::getCurrentThreadEnv()`, `GetMethodID(cameraManagerClass, "captureFrame", "(I[BIIZ)V")` and `CallVoidMethod`, then copies a Java `byte[]` back into the core buffer. `Mic_ReadInput` and `Net_SendPacket`/`Net_RecvPacket` are other Platform hooks implemented on Android. — [PlatformAndroid.cpp](https://github.com/rafaelvcaetano/melonDS-android/blob/master/app/src/main/cpp/PlatformAndroid.cpp); [MelonDSAndroidCameraHandler.cpp](https://github.com/rafaelvcaetano/melonDS-android/blob/master/app/src/main/cpp/MelonDSAndroidCameraHandler.cpp)
- The current upstream manifest requests CAMERA, RECORD_AUDIO, INTERNET, ACCESS/CHANGE_WIFI_STATE, CHANGE_NETWORK_STATE and NEARBY_WIFI_DEVICES (neverForLocation). It has no USB host feature and no Bluetooth permissions. — [AndroidManifest.xml](https://github.com/rafaelvcaetano/melonDS-android/blob/master/app/src/main/AndroidManifest.xml)
- Upstream issue "Need IR(Infrared) Connection Support" (#433) is open. — [melonDS-android #433](https://github.com/rafaelvcaetano/melonDS-android/issues/433)

**[SHIPPED] Android IR plumbing already exists in a fork (WatermelonDS "melonDS Pokéwalker", silver115)**
- Branch `melonds-pokewalker`, last commit 2026-11-01 (63dccbf). Prebuilt arm64 APKs are published both side-by-side and as a replacement. — [WatermelonDS release](https://github.com/silver115/WatermelonDS/releases/tag/melonds-pokewalker-latest); [commits API](https://api.github.com/repos/silver115/WatermelonDS/commits?sha=melonds-pokewalker)
- "`CartRetailIR` now implements the IR chip's SPI commands `0x01` (receive) and `0x02` (send). Bytes go through three new `Platform::IR_*` hooks." The hooks are `IR_Reset`, `IR_SendPacket` and `IR_ReceivePacket`, and they route to Off, Virtual or TCP. There is **no USB-serial or Bluetooth mode**. — [docs/POKEWALKER.md](https://github.com/silver115/WatermelonDS/blob/melonds-pokewalker/docs/POKEWALKER.md); [PlatformIR.cpp](https://github.com/silver115/WatermelonDS/blob/melonds-pokewalker/app/src/main/cpp/pokewalker/PlatformIR.cpp)
- The doc mentions dumping a real walker's EEPROM "with the pwsync tool and a Raspberry Pi Pico IR bridge" for import. That is offline EEPROM transfer, not a live link. — [docs/POKEWALKER.md](https://github.com/silver115/WatermelonDS/blob/melonds-pokewalker/docs/POKEWALKER.md)

**Emulator precedents for USB on Android**
- [SHIPPED] Dolphin Android, official GameCube adapter: "Android doesn't require anything special to make the adapter work." Android shows a "may Dolphin use this device" prompt. A known Android USBManager bug sometimes requires unplugging and replugging, and Dolphin shows a toast saying so. — [Dolphin GC adapter guide](https://dolphin-emu.org/docs/guides/how-use-official-gc-controller-adapter-wii-u/)
- Dolphin's implementation pattern: `GCAdapter.kt` exposes `@Keep` static methods `openAdapter()`, `input()` (=`bulkTransfer(usbIn, payload, len, 16)`, a 16 ms timeout), `output()` and `getFd()`. The C++ core `InputCommon/GCAdapter.cpp` under `GCADAPTER_USE_ANDROID_IMPLEMENTATION` calls them with `GetStaticMethodID` and `CallStaticIntMethod` from its polling thread. There is also a `USBPermService.kt`. — [GCAdapter.kt](https://github.com/dolphin-emu/dolphin/blob/master/Source/Android/app/src/main/java/org/dolphinemu/dolphinemu/utils/GCAdapter.kt); [GCAdapter.cpp](https://github.com/dolphin-emu/dolphin/blob/master/Source/Core/InputCommon/GCAdapter.cpp); [Dolphin tree](https://api.github.com/repos/dolphin-emu/dolphin/git/trees/master?recursive=1)
- [SHIPPED] GBCamera Android Manager talks over USB serial to an Arduino Game Boy Printer Emulator and to GBxCart. It is a retro-hardware precedent for USB-serial on Android, though not an emulator link. — [GBCamera Android Manager listing](https://awesome.ecosyste.ms/projects/github.com%2FMraulio%2FGBCamera-Android-Manager); [usb-serial-for-android "Projects using" wiki](https://github.com/mik3y/usb-serial-for-android/wiki/Projects-Using-usb-serial-for-android)
- I found no Android emulator that does GB/GBA link-cable play over a USB-serial adapter. Pizza Boy GBC advertises "Serial link emulation through WiFi or Bluetooth", not USB. A 2014 "USB link cable for emulators" thread was only an idea. — [Pizza Boy GBC on APKMirror](https://apkmirror.com/apk/pizza-emulators/pizza-boy-gbc-basic); [search summary](https://archives.glitchcity.info/forums/board-14/thread-6887/page-0.html)

**USB latency evidence (indirect)**
- An Android FTDI app had read problems with usb-serial-for-android until the FTDI latency timer was set to 1 ms. The author later used an event character. — [subvertallmedia blog](https://blog-subvertallmedia-com.pages.dev/2021/01/14/high-speed-ftdi-android-comms-or-why-am-i-always-reading-0-bytes)
- ODrive measured about 1.15 ms average USB read latency on a desktop host. Bulk transfers have no defined polling rate, so latency rises under bus load. — [ODrive forum](https://discourse.odriverobotics.com/t/decreasing-latency/1463/15)
- The `android-usb-serial` Rust crate polls bulk-IN at a 1 ms interval and limits in-flight transfers to 2 "to reduce failures on weak OTG ports." — [android-usb-serial nusb_transport.rs](https://docs.rs/crate/android-usb-serial/0.1.0/source/src/nusb_transport.rs)

**Handheld specifics**
- AYN Thor: Android 13 with AYN's dual-screen launcher. **One USB-C port** (USB 3.1, also described as USB 3.2 Gen1 5 Gbps) handling charging, data and video. DP Alt Mode is 4Kp60 on Base/Pro/Max and 1080p on Lite. It also has a 3.5 mm jack and microSD. Lite has Wi-Fi 6 + BT 5.1; the others have Wi-Fi 7 + BT 5.3. — [Android Authority](https://www.androidauthority.com/ayn-thor-3588861/); [Profesional Review](https://www.profesionalreview.com/2026/08/16/ayn-thor-review/amp/); [RetroCatalog](https://retrocatalog.com/retro-handhelds/thor); [Droix](https://droix.net/?p=198942)
- The Thor's USB-C port faces downward. Thor-specific USB-C docks are sold (JSAUX HB0602 five-port, ACASIS 6-in-1). — [TechTactician accessories](https://techtactician.com/my-best-ayn-thor-accessories/)
- Ayaneo Pocket DS: one full-function USB-C 3.2 Gen 2 (10 Gbps) with charging and video out, plus microSD. A reader comment notes no audio jack and no second USB-C. Snapdragon G3x Gen 2, Wi-Fi + BT 5.3. — [Retro Dodo review](https://retrododo.com/ayaneo-pocket-ds-review/); [Liliputing](https://liliputing.com/?p=184497); [YugaTech spec](https://www.yugatech.com/spec/ayaneo-pocket-ds/)
- Retroid Dual Screen Add-On (RP5, Mini, Mini V2, RP4 Pro): its clip "plugs into" the handheld's only USB-C port, so passthrough charging is required. The add-on has its own USB-C port for power passthrough. — [retrohandhelds.gg](https://retrohandhelds.gg/retroid-goes-dual-screen-with-new-add-on/); [Notebookcheck](https://www.notebookcheck.net/Retroid-s-Dual-Screen-Add-On-costs-69-and-works-with-third-party-devices.1032905.0.html)

### Inferences
- [INFERENCE] An RP2040 (TinyUSB CDC), ESP32-S3 (TinyUSB CDC) or ESP32-C3 (hardware USB Serial/JTAG CDC) dongle should be picked up by usb-serial-for-android ≥3.5's interface-class CDC detection with no custom driver. A `device_filter.xml` matching the dongle's VID:PID (or CDC class 2) gives users one "Open melonDS?" tap per plug-in, with no settings screens. The C3's fixed USB-JTAG descriptors mean a generic Espressif VID:PID, so the filter can't distinguish the dongle from other ESP32-C3 boards. RP2040 and S3 allow custom descriptors.
- [INFERENCE] Integration effort is moderate and well-trodden. Port WatermelonDS's `CartRetailIR` SPI 0x01/0x02 plus `Platform::IR_*` hooks, or upstream PR #2776's IR plumbing, into `melonDS-android-lib`. Then add a `Mode::Serial` next to Off/Virtual/TCP. There are two ways to do it:
  - (a) **Kotlin owns the port.** Use usb-serial-for-android with `SerialInputOutputManager`, and push bytes into a native ring buffer through a JNI `external fun`. `IR_ReceivePacket` drains that buffer, applying the same 3.5 ms gap framing. `IR_SendPacket` calls a static Kotlin `write()` through JNI, as in Dolphin's `output()`.
  - (b) **Native owns the port.** Kotlin opens the `UsbDeviceConnection` and passes `getFileDescriptor()` to C++ (Dolphin's `getFd()` pattern), which talks CDC bulk endpoints via libusb `libusb_wrap_sys_device` or raw usbfs ioctls. This avoids JNI per byte but duplicates driver logic.
  - Option (a) is simpler and reuses the camera-handler JNI pattern already in the codebase.
- [INFERENCE] Latency budget: SIR at 115200 baud 8N1 is about 86.8 µs/byte, so a 136-byte packet (8-byte header + 128-byte payload) takes about 11.8 ms on air. USB full-speed adds about 1–2 ms per direction plus Android thread scheduling of a few ms. The DS→walker→DS round trip through a USB pipe should land well under 20 ms of added delay, leaving most of the 100 ms deadline.
- [INFERENCE] Biggest UX costs:
  - (1) The single port is occupied, so long sessions need a USB-C hub or a dongle with PD passthrough. Registration plus a stroll exchange takes under 30 s, so battery is a non-issue in practice.
  - (2) Retroid's dual-screen add-on already occupies the RP5/Mini port. A dongle would need to go through a hub after the add-on's passthrough port, which the sources say carries power. It is unconfirmed whether it carries data.
  - (3) The dongle protrudes from the Thor's bottom-facing port, so the walker must sit roughly in line with it. That suits IR line-of-sight anyway.
  - (4) Dolphin's documented replug quirk suggests occasional "unplug and replug" support calls.
- [INFERENCE] The Thor's host mode isn't stated explicitly in spec pages, but DP Alt Mode, USB 3.x data and Thor-specific multi-port docks strongly imply a dual-role or host-capable port. The risk is low, but I have not verified it directly.

### Gaps
- No primary source states AYN Thor "USB OTG/host supported" in words. There are no Reddit or AYN forum confirmations of a USB-serial device (CH340, FTDI, Pico) working on Thor. A quick check with a USB Host Diagnostics app or a Pico running a CDC echo would settle it.
- usb-serial-for-android's minimum API and read-loop timing were not documented on the README. I did not inspect the source.
- No measured round-trip latency for CDC-ACM on Android handhelds (Snapdragon 8 Gen 2 / G3x Gen 2) was found.
- I could not confirm whether the Retroid add-on's passthrough USB-C carries data.
- No Android emulator was found using USB-serial for link play (GB/GBA/DS). USB-serial for IR would be a first.

## Q2. Wi-Fi: ESP32 dongle exposing TCP (soft-AP or LAN join); UX and latency

### Takeaway
Wi-Fi has a unique advantage: **WatermelonDS (shipped, Android) already has "Infrared mode → TCP" listening on port 8081 with a raw-byte protocol.** An ESP32 dongle acting as a TCP client and transparent SIR pipe could work with **zero Android app changes**. The cost is network UX. Either the handheld joins the dongle's soft-AP and loses its normal Wi-Fi (unless the device supports local-only STA concurrency), or the dongle must be provisioned onto the home LAN and told the handheld's IP. Wi-Fi power-save on either end can add latency spikes, and WatermelonDS's 3.5 ms gap-based packet framing is sensitive to TCP segment splitting.

### Cited Findings
- [SHIPPED] WatermelonDS: "*Infrared mode → TCP* opens port 8081 on the Thor. Walker emulators that speak melonDS-IR's TCP protocol (for example `picowalker-sdl-tcp`) can connect to it over Wi-Fi." — [docs/POKEWALKER.md](https://github.com/silver115/WatermelonDS/blob/melonds-pokewalker/docs/POKEWALKER.md)
- WatermelonDS TCP specifics, from source:
  - The handheld is the **server** (listen, accept; "newest peer wins") and sets `TCP_NODELAY` on the accepted socket.
  - Sends are raw IR bytes. Receives gather bytes until `kPacketGapUs = 3500` µs of silence and return them as one packet.
  - Before sending a disconnect packet (first byte `0xF4 ^ 0xAA`), it sleeps 10 ms "to keep disconnect separate from the previous packet".
  - [PokewalkerIR.cpp](https://github.com/silver115/WatermelonDS/blob/melonds-pokewalker/app/src/main/cpp/pokewalker/PokewalkerIR.cpp)
- Android local-only Wi-Fi: `WifiNetworkSpecifier` (API 29+) "can be used to request a local-only connection on devices that support concurrent connections (indicated via `WifiManager#isStaConcurrencyForLocalOnlyConnectionsSupported()`) and if the initiating app targets SDK ≥ S ... These local-only connections may be brought up as a secondary concurrent connection (primary connection will be used for networks with internet connectivity...)". — [Android WifiNetworkSpecifier reference](https://developer.android.com/reference/android/net/wifi/WifiNetworkSpecifier)
- Community experience with IoT APs that have no internet:
  - Specifier requests cannot include `NET_CAPABILITY_INTERNET`. The workaround is `bindProcessToNetwork()` in `onAvailable`.
  - Android 10 keeps the connection only while the network callback stays registered.
  - Default-route behavior with "Wi-Fi without connectivity" varies by vendor; "there are others that it's a nightmare."
  - [Stack Overflow via kiwix: keep Android on IoT AP](https://kaweah.freedombox.rocks/kiwix/stackoverflow.com_en_all_2023-11/questions/62277005/how-do-i-keep-android-connected-to-an-iot-wifi-ap-with-no-internet-access-when); [kiwix answer](https://kiwix.lema.org/stackoverflow.com_en_all_2023-11/a/73178258); [WifiWizard2 #94](https://github.com/tripflex/WifiWizard2/issues/94)
- The upstream melonDS-android manifest already holds INTERNET, CHANGE_WIFI_STATE, CHANGE_NETWORK_STATE and NEARBY_WIFI_DEVICES, so a `WifiNetworkSpecifier` flow needs no new manifest permissions. — [AndroidManifest.xml](https://github.com/rafaelvcaetano/melonDS-android/blob/master/app/src/main/AndroidManifest.xml)
- Two incompatible IR-over-IP conventions exist: melonDS-IR TCP/UDP, used by WatermelonDS and PocketWalker/picowalker-sdl-tcp, and celerizer's `CartRetailIRLink` on TCP 43690 in open melonDS PR #2776, used by Stepdad. — see sibling notes `emulator_and_software_support.md`; [melonDS PR #2776](https://github.com/melonDS-emu/melonDS/pull/2776)
- Thor radios: Wi-Fi 7 + BT 5.3 (Base/Pro/Max), Wi-Fi 6 + BT 5.1 (Lite). — [Android Authority](https://www.androidauthority.com/ayn-thor-3588861/)

### Inferences
- [INFERENCE] **Soft-AP variant (dongle is the AP, handheld joins "PokeIR-XXXX"):** The dongle's DHCP server knows the single client's IP, so it can connect out to `client:8081` automatically. Provisioning disappears, which makes this the zero-config path with stock WatermelonDS. The UX cost:
  - The user goes to Android Wi-Fi settings, picks the dongle's SSID, and accepts the "no internet" warning. The handheld drops home Wi-Fi, which loses RetroAchievements, cloud sync and so on during the session. Some vendor builds may auto-switch back to a network with internet.
  - A modified app could instead request the AP via `WifiNetworkSpecifier`, which shows a system picker. On hardware with STA+STA local-only concurrency, home Wi-Fi stays up. Whether Thor's Snapdragon 8 Gen 2 / Android 13 build or the Pocket DS's G3x Gen 2 reports `isStaConcurrencyForLocalOnlyConnectionsSupported()` is unknown.
- [INFERENCE] **LAN-join variant (dongle joins home Wi-Fi):** Requires one-time provisioning, either a captive portal on the dongle's setup AP, ESP-IDF SmartConfig/BLE provisioning, or Improv-Wi-Fi. The dongle must then find the handheld's IP: mDNS from the app, manual IP entry on the dongle, or reversing roles so the dongle is the server and the app is the client, which requires app changes. It fails on networks with client isolation (hotels, campus) and away from home. It is worse for end users than soft-AP.
- [INFERENCE] **Latency:** With 802.11 power save disabled on the ESP32 (`esp_wifi_set_ps(WIFI_PS_NONE)`) and the link idle, per-packet LAN latency is typically a few ms. Power-save on the client or AP side can buffer frames until the next beacon or DTIM, giving spikes of tens to hundreds of ms that can approach the 100 ms game deadline. Soft-AP mode on the ESP32 partly controls this, because the AP never sleeps, but the handheld's own STA power save remains.
- [INFERENCE] **Framing hazard:** WatermelonDS treats 3.5 ms of TCP silence as end-of-packet. If the dongle forwards SIR bytes as they arrive, or Wi-Fi splits a packet across delayed segments, one IR packet can be delivered as two, failing the checksum. Mitigation in dongle firmware: buffer until the SIR line is idle for about 3.5 ms, then `send()` the whole packet in one write with Nagle off. In the other direction the dongle simply emits bytes at 115200 back-to-back.
- [INFERENCE] Wi-Fi is the best fit when the goal is "works with an already-shipped Android build today". It is the worst fit for "a non-technical user plugs it in and it works", because of network switching.

### Gaps
- I could not retrieve the ESP-IDF power-save page (it moved to wifi-performance-and-power-save.html), so I have no citation for the default STA power-save mode or DTIM latency numbers.
- No measured ESP32↔Android TCP RTT or jitter figures were found.
- Unknown: STA+STA local-only concurrency support on Thor and Pocket DS.
- Unknown: whether WatermelonDS's TCP mode has been tested against anything other than picowalker-sdl-tcp, for example a hardware bridge.
- I did not confirm the exact wording of the Android system dialog shown for `WifiNetworkSpecifier` requests.

## Q3. Bluetooth: BLE GATT (NUS-style) vs Classic SPP; permissions, throughput and latency, pairing UX

### Takeaway
BLE works on all candidate MCUs and on the handhelds, without pairing (scan and connect) and without location permission on Android 12+. However, Android's fastest requested connection interval is **11.25–15 ms (since Android 6)**, and real negotiated intervals can be much worse. A transparent BLE pipe adds roughly 2–4 connection intervals per DS↔walker round trip, a meaningful slice of the 100 ms game deadline with vendor-dependent variance. Classic SPP needs the original ESP32, which is not S3 or C3, plus OS-level pairing. Throughput is not the issue (the link carries about 11.5 kB/s at most); latency and jitter are. No existing Android melonDS build supports either Bluetooth transport.

### Cited Findings
- ESP32-C3 supports Bluetooth 5.0 (LE). "ESP-Bluedroid for ESP32-C3 supports Bluetooth LE only. Classic Bluetooth is not supported", and NimBLE is LE-only. — [ESP-IDF BLE overview (ESP32-C3)](https://docs.espressif.com/projects/esp-idf/en/stable/esp32c3/api-guides/ble/overview.html)
- "The only ESP32 chip that supports 'Bluetooth Classic' (AKA BR/EDR) is the original ESP32"; S3, C3, C6 and H2 don't. — [Bluepad32 FAQ](https://bluepad32.readthedocs.io/en/latest/FAQ/); [esp32.com thread](https://esp32.com/viewtopic.php?p=85597)
- Android 12+ permissions:
  - `BLUETOOTH_SCAN` (to find devices; can carry `usesPermissionFlags="neverForLocation"`) and `BLUETOOTH_CONNECT` (to talk to devices) are runtime permissions shown as one "Nearby devices" prompt.
  - On Android ≤11, `ACCESS_FINE_LOCATION` is required for scanning.
  - "The Companion Device Manager (CDM) ... provides a pairing UI on behalf of your app and doesn't require location permissions" (Android 8.0+).
  - [Android Bluetooth permissions](https://developer.android.com/develop/connectivity/bluetooth/bt-permissions)
- `BluetoothGatt.requestConnectionPriority()`: `CONNECTION_PRIORITY_HIGH` = "Request a high priority, low latency connection". `CONNECTION_PRIORITY_DCK` = "priority preferred for Digital Car Key for a lower latency connection". The reference gives no numeric intervals. — [Android BluetoothGatt reference](https://developer.android.com/reference/android/bluetooth/BluetoothGatt)
- The AOSP config for HIGH is min 9 and max 12 units of 1.25 ms, i.e. **11.25–15 ms**. Before Android 6 it was 6–8 units (7.5–10 ms). The stated reason for the change was avoiding choppy Bluetooth audio. One Nordic thread disputes the root cause (a Bluedroid `BTM_BLE_CONN_INT_MIN_LIMIT` = 0x0009). — [/e/ OS AOSP Bluetooth commit](https://gitlab.e.foundation/e/os/android_packages_apps_bluetooth/-/commit/b67ba1ba297fd7cc962f26f79b57f844e9613d8b); [Stack Overflow: Android 6 BLE connection parameters](https://kiwix.lema.org/stackoverflow.com_en_all_2023-11/questions/34617061/android-6-0-marshmallow-ble-connection-parameters); [Nordic DevZone](https://devzone.nordicsemi.com/f/nordic-q-a/12702/nexus-5x-connection-interval/48241)
- Requesting HIGH doesn't guarantee it: a Nexus 5X calling `CONNECTION_PRIORITY_HIGH` still got a **72.5 ms** interval. Another developer got at best 11.25 ms on Android 6+. — [Nordic DevZone: slow BLE throughput Nexus 5X](https://devzone.nordicsemi.com/f/nordic-q-a/18579/slow-ble-throughput-with-nexus-5x); [Stack Overflow via kiwix](https://kiwix.lema.org/stackoverflow.com_en_all_2023-11/questions/34617061/android-6-0-marshmallow-ble-connection-parameters)
- Punch Through: "There is generally no benefit below 15ms" for throughput. Peripheral latency affects only the central-to-peripheral direction, so set it to 0. — [Punch Through: BLE connection interval](https://punchthrough.com/ble-connection-interval-throughput/)
- Precedent: Pizza Boy GBC offers "Serial link emulation through WiFi or Bluetooth" on Android. That is emulator-to-emulator, not hardware. — [Pizza Boy GBC on APKMirror](https://apkmirror.com/apk/pizza-emulators/pizza-boy-gbc-basic)

### Inferences
- [INFERENCE] **BLE latency model:** One notification per IR packet fits in one connection event if the dongle negotiates ATT MTU ≥ about 140 (HGSS packets are at most 136 bytes) with LE Data Length Extension. One-way delay is then roughly 0–1 connection intervals of waiting plus processing, so about 8–20 ms at 11.25–15 ms. A full DS→walker→DS exchange crosses BLE twice, giving about 20–45 ms added at best. That fits under 100 ms. If the handheld settles at a 30–50 ms "balanced" interval, or a vendor stack behaves like the 72.5 ms Nexus case, round trips approach or exceed 100 ms and registration fails intermittently.
  - Pure pipe or proxy: a transparent pipe can't hide this. Only a protocol-aware endpoint can, like HachiStep's local `0x2E` keepalive frames, and that is no longer a dumb byte pipe.
- [INFERENCE] **BLE UX:** On Android 12+, the user gets one "Nearby devices" permission prompt. Then the app scans for the dongle's service UUID and connects, with no OS pairing, no PIN and no network switch. The CDM path gives a system chooser with no location permission. This is the cleanest wireless UX, but it needs new app code (GATT client, MTU and priority negotiation, reconnection) and there is no shipped Android melonDS support.
- [INFERENCE] **Classic SPP:** Requires the original ESP32 (with an external transceiver; the ESP32 has no native USB, which is fine for a wireless dongle) plus pairing in Android Settings (or `createBond`) and an RFCOMM `BluetoothSocket`. SPP avoids the connection-interval quantization, but Android RFCOMM latency is undocumented in sources found. It also locks the hardware choice away from the RP2040, S3 and C3 that the existing tools (picowalker on RP2040 PIO, Stickwalker on ESP32-S3) target.
- [INFERENCE] Bluetooth also coexists with users' Bluetooth headphones and controllers on these handhelds. Bluetooth audio is the stated reason Android raised the minimum interval, so audio streaming may further degrade BLE scheduling.

### Gaps
- No measured BLE round-trip numbers on Thor or Pocket DS. It is unknown what interval they actually grant for `CONNECTION_PRIORITY_HIGH` or `DCK`.
- No sourced Android Classic SPP or RFCOMM latency figures.
- No sourced ESP32-S3/C3 NimBLE notification latency figures.

## Q4. Which transport is simplest for end users, and which is most robust given the protocol's timing?

### Takeaway
**USB-C CDC-ACM is both the most robust and, after a one-time app integration, the simplest for end users.** Plug in, tap "OK" on the system "Open melonDS?" dialog, and go: no pairing, no permissions screen, no network switching. Latency is about 1 ms-class against a 100 ms deadline. **Wi-Fi soft-AP is the only option that works with a shipped Android build today** (WatermelonDS TCP mode, port 8081), but it forces a Wi-Fi network switch. **BLE gives the nicest wireless UX but has the weakest timing margin**, which is device-dependent. A pragmatic plan is dual-mode firmware on an ESP32-S3 (USB CDC plus Wi-Fi soft-AP TCP client), or an RP2040 for USB only.

### Cited Findings
- Game reply deadline 100 ms; packet delimiter 3.5 ms of silence. — [WatermelonDS docs](https://github.com/silver115/WatermelonDS/blob/melonds-pokewalker/docs/POKEWALKER.md); [PokewalkerIR.cpp](https://github.com/silver115/WatermelonDS/blob/melonds-pokewalker/app/src/main/cpp/pokewalker/PokewalkerIR.cpp)
- The HachiStep bridge survived 3×250 ms injected stalls only with local `0x2E` keepalive frames at each endpoint, and failed at a sustained 3 s. — [hachistep PR #15](https://github.com/lumirth/hachistep/pull/15)
- USB attach intent auto-grants permission until disconnect. — [Android USB host docs](https://developer.android.com/develop/connectivity/usb/host)
- BLE HIGH priority is 11.25–15 ms and not guaranteed (a 72.5 ms case was observed). — [AOSP commit](https://gitlab.e.foundation/e/os/android_packages_apps_bluetooth/-/commit/b67ba1ba297fd7cc962f26f79b57f844e9613d8b); [Nordic DevZone](https://devzone.nordicsemi.com/f/nordic-q-a/18579/slow-ble-throughput-with-nexus-5x)
- A WatermelonDS TCP server already ships. — [docs/POKEWALKER.md](https://github.com/silver115/WatermelonDS/blob/melonds-pokewalker/docs/POKEWALKER.md)

### Inferences
- [INFERENCE] Robustness ranking for a **dumb transparent pipe**:
  1. USB CDC: deterministic, about 1–2 ms per direction.
  2. Wi-Fi soft-AP with power save off and whole-packet sends: a few ms typical, with occasional spikes.
  3. BLE: 10–50+ ms per direction depending on the negotiated interval.
  4. Classic SPP: unknown, and constrains the MCU choice.
- [INFERENCE] The 250 ms / 3 s HachiStep figures describe a proxy that synthesizes keepalives, not a pipe. In a pure pipe the 100 ms deadline is the binding constraint. Every transport's worst-case round trip, which is two transport crossings plus about 12 ms airtime per packet plus walker processing, must stay under it. Only USB clearly does so on all devices. If BLE or Wi-Fi is chosen, the Android side should add a protocol-aware "stall cover" like HachiStep's `0x2E` frames, which turns the pipe into a proxy.
- [INFERENCE] End-user simplicity ranking:
  1. USB: one tap per plug-in, and the dongle is powered by the handheld, so no battery is needed.
  2. BLE: one Nearby-devices grant, then auto-connect, but the dongle needs a battery or a power source.
  3. Wi-Fi soft-AP: switch networks every session, accept the "no internet" warning, and the dongle needs power.
  4. Wi-Fi LAN: provisioning plus IP discovery, and it fails off home networks.
  Classic SPP falls between 2 and 3 because of OS pairing.
- [INFERENCE] USB's real downsides are physical: the single port on all three handheld families, charging during use, and the Retroid add-on occupying the port. A dongle with a USB-C PD passthrough receptacle (a hub IC) addresses charging at extra BOM cost. A short USB-C extension or pigtail helps aim the IR window.
- [INFERENCE] Development-cost view:
  - USB requires adding a serial IR mode to an Android melonDS build: port the WatermelonDS `CartRetailIR` plus `IR_*` hooks, and add usb-serial-for-android with a JNI ring buffer. This is about a day's work for someone familiar with the codebase, given the camera-handler JNI precedent.
  - Wi-Fi requires only dongle firmware (an ESP32 TCP client to `<dhcp-client-ip>:8081` plus SIR UART), testable today against WatermelonDS.
  - A dual-mode ESP32-S3 dongle (native USB-OTG for CDC plus Wi-Fi) covers both, and matches Stickwalker's MCU.

### Gaps
- Nobody has published an end-to-end test of a real Pokéwalker over any of these transports to Android melonDS. All latency conclusions are modelled, not measured.
- The walker-side timeouts (how long the Pokéwalker firmware waits for the DS) were not found in sources reviewed here. They may be tighter or looser than the game's 100 ms.

## Q5. Existing commercial or open hardware: Android-supported USB IrDA dongles (MCS7780 etc.) and the DS Pico IR

### Takeaway
No off-the-shelf USB IrDA dongle works on stock Android. MCS7780-class adapters relied on the Linux kernel IrDA stack and a non-standard driver, and the whole stack was removed from mainline in 2018. Android OTG "IR" gadgets are consumer-IR remote blasters (LIRC, carrier-modulated), not IrDA SIR. No Pokéwalker app or dongle for Android exists. The **DS Pico IR** (Phenomods, about Sept 2026) is a real-DS flash cart with a Pokéwalker-compatible IR transceiver. It solves the problem for real DS hardware, not for Android emulators.

### Cited Findings
- MCS7780: "MosChip MCS7780 chipset is an IrDA USB bridge that doesn't conform with the IrDA-USB standard and thus needs its separate driver." The Linux driver is `drivers/net/irda/mcs7780.c` (Kconfig `MCS_FIR`). Windows drivers v1.3.0.0 exist. No Android driver or app was found. — [kernel commit](https://lab.nexedi.cn/kirr/linux/-/commit/c6ae522e3a50fc1ec483d7f03ece9c7a25e6de95?expanded=1); [Debian kernel source mcs7780.c](https://sources.debian.org/src/linux/3.2.73-2/drivers/net/irda/mcs7780.c); [Softpedia driver listing](https://drivers.softpedia.com/get/Other-DRIVERS-TOOLS/ASIX-MCS7780-USB-11-to-IrDA-Controller-Driver-1310-x64.shtml)
- Linux IrDA removal: in Aug 2017 GKH moved it to staging ("It's long been broken, and no one seems to use it anymore"). The removal commit "staging: irda: remove the irda network stack and drivers" is dated 2018-03-14, in the 4.17 merge window. — [LKML 2017](https://lkml.iu.edu/hypermail/linux/kernel/1708.3/03906.html); [removal commit d64c2a76123f](https://upd.dev/kernel/linux/commit/d64c2a76123f)
- Android OTG "IR" adapters are marketed as universal remotes for TVs and ACs. Irdroid is a USB IR transceiver with an open-source Android app, but it is a LIRC port for remote control. Some phones' IR blasters can't receive. No Pokéwalker-capable Android app was found. — [Irdroid](https://irdroid.com/2014/08/usb-infrared-transceiver-app-for-android/); [eBay OTG IR adapter](https://www.ebay.com/itm/225823091269); [DraStic forum Pokéwalker thread](https://drastic-ds.com/viewtopic.php?f=5&t=4390); [GBAtemp "Pokewalker app idea"](https://gbatemp.net/threads/pokewalker-app-idea.216217/)
- The Pokéwalker's IR transceiver is a generic SIR-compatible part. Dmitry.GR dumped its firmware using a Palm m500 IrDA PDA. — [Dmitry.GR Pokéwalker hacking](https://dmitry.gr/?r=05.Projects&proj=28.+pokewalker)
- [SHIPPED/backorder] DS Pico IR: "an upgraded version of the DS Pico, from Phenomods". It "includes an IR transceiver compatible with pokewalker", adds upgraded RAM, a USB-C port and .ndz compressed ROM support, and costs "about $10 more than the original". The US listing URL contains "dspico-ir-backorder"; the EU seller is Shiraseal. Posted 2026-09-08. The article does not say whether the IR was tested with a real walker. The original DS Pico (LNH-Team) is a Raspberry Pi (RP2040-class) based open-source cart. — [RetroRGB](https://retrorgb.com/ds-pico-ir-flash-cart-for-nintendo-ds.html); [TechEBlog](https://www.techeblog.com/ds-pico-nintendo-ds-flash-cart-mod/)
- Ordinary flash carts can't do Pokéwalker because they lack the IR chip. — [GBAtemp thread](https://gbatemp.net/threads/flashcarts-and-pokewalker-do-they-work.220396/)
- Open walker-side or bridge hardware relevant to reuse: picowalker (RP2350/RP2040, PIO IrDA). WatermelonDS references "a Raspberry Pi Pico IR bridge" with the pwsync tool for EEPROM dumps. — [picowalker](https://github.com/mamba2410/picowalker); [WatermelonDS docs](https://github.com/silver115/WatermelonDS/blob/melonds-pokewalker/docs/POKEWALKER.md)

### Inferences
- [INFERENCE] A userspace Android driver for an MCS7780 via `UsbManager` is theoretically possible, since the kernel driver documents the register protocol. It is pointless next to a $5 RP2040 or ESP32 CDC dongle. These chips also target IrLAP-framed IrDA (wrapping and CRC, FIR modes), and it is unverified that they pass raw unframed SIR bytes cleanly, which is what the Pokéwalker uses. usb-serial-for-android doesn't support them.
- [INFERENCE] The DS Pico IR's USB-C port and RP2040-class MCU make it conceivable as a future "IR modem" for PCs or Android if its firmware exposed CDC passthrough. Nothing indicates this exists.
- [INFERENCE] No commercial "Pokéwalker dongle for Android or PC emulators" exists as of Nov 2026. The custom RP2040/ESP32-S3/C3 plus TFBS4711 build remains the path.

### Gaps
- I did not find the DS Pico IR's IR transceiver part number, firmware source, real-walker test reports or the purpose of its USB-C port.
- I did not verify whether any Kingsun, KS-959 or STIr4200-class USB-IrDA adapter can pass raw SIR without IrLAP framing.
- Reddit and r/Pokewalker threads were not reachable or searched directly.
