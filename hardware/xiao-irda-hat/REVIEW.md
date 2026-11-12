# Independent pre-order review: XIAO IrDA hat v0.1

Reviewed 2026-11-06 against the fab outputs (`fab/gerbers.zip`, `fab/bom.csv`, `fab/cpl.csv`), the KiCad board, the tscircuit source, and these primary sources:

- Vishay TFBS4711 datasheet 82633 rev 3.9, downloaded from vishay.com.
- Seeed `OPL_Kicad_Library`: `XIAO-ESP32-S3-DIP.kicad_mod`, `Seeed Studio XIAO ESP32S3/ESP32S3.kicad_pcb` (Seeed's own XIAO board file) and its schematic PDF.
- Espressif ESP32-S3 datasheet, Tables 2-1 and 2-2.
- The live JLCPCB and LCSC part APIs.

I formed these conclusions before reading the README. No design file was changed. The scratch tools I used (a gerber rasterizer with a connectivity check, and a silk-over-mask check) are in the session scratchpad, not in this repo.

## Verdict

**No BLOCKER found. OK to order**, once you have dealt with the SHOULD-FIX items below. They are process and documentation items: none of them needs a change to the copper. The two things that could ruin the board are the XIAO pin mirroring and the TFBS4711 pin order and lens direction. I checked both from first principles, then checked them again directly on the gerbers. Both are correct.

---

## BLOCKER

None.

---

## SHOULD-FIX

### S1. The XIAO's USB-C is a receptacle, so the dongle cannot plug straight into a handheld
- **Evidence.** In Seeed's board file, `USB0` is a `USB2.0-TYPE-C` *receptacle* on F.Cu. Its shell legs S1 to S4 are through-hole, and its CC pins have 5.1 kΩ pull-downs (schematic R1 "5.1K A5/CC1"). Handheld USB-C ports are receptacles too.
- **Impact.** The brief and the README both say the dongle "plugs into a handheld's USB-C port by the XIAO's USB-C connector". That needs either a USB-C male-to-male adapter (USB 2.0 is enough) or a short C-to-C cable. With a rigid coupler, the whole dongle hangs off a non-compliant adapter, which is a lever on both ports.
- **CC behaviour is fine.** The XIAO presents as a sink/UFP, so the handheld becomes host through a passive male-male adapter.
- **Fix.** No PCB change. Update the README and the enclosure plan: name the adapter or cable, and consider a short cable or an enclosure that takes the strain.

### S2. The JLCPCB production panel and tooling holes are uncontrolled, and they matter near the IR edge
- **Evidence.** The lens tips sit 0.100 mm inside the IR edge (verified on the board), and JLCPCB's outline tolerance is about ±0.2 mm.
- **Why it matters.** A mouse-bite tab on that edge leaves a nub right in front of the lenses. JLCPCB might also add a V-score there, or tooling holes inside a board this crowded. The README's order remark asks JLCPCB to avoid tabs on that edge, but a remark is not binding.
- **Fix.** In the order:
  - Enable **"Confirm Production File"** so you see JLCPCB's panel, rails, tabs and tooling holes before production.
  - Reject any rail, tab or V-score on the short edge opposite USB-C. Rails or tabs on the two long (24.4 mm) edges are fine: the header pads there are 0.42 mm from the edge.

### S3. Keep the U1 placement check, and know exactly what correct looks like
I believe the CPL entry is correct, for these reasons:
- The KiCad footprint at 0° and the EasyEDA/LCSC C102624 footprint (`footprints/tfbs4711.pretty/OPTO-SMD_TFBS4711-TR1.kicad_mod`) are in the same frame: pin 1 at -X, pads on y = 0, and the body and domes toward +y (screen-down).
- So the CPL `U1,100.00,-88.97,T,180.00` is the right rotation.
- The EasyEDA origin is the pad-row centre, and so is the pad bounding-box centre. That matches the CPL point, so I don't expect the 1.3 mm "body-centre" offset the README worries about.

This is still the only placement whose failure is fatal. A 180° error reverses the pins (pin 1 VCC2 lands on the GND pad) and points the lenses into the board.

- **Fix: what to check in the JLCPCB preview** (top view, IR edge at the top of the screen):
  - The domes point toward the top edge.
  - The pin-1 marker is at the **right-hand** end of the pad row, the end next to C1.
  - The pad row is under the back of the body, not under the domes.

### S4. `verify_netlist.py` is not an independent check of what gets fabricated
- **What it does well.**
  - Its `INTENDED` table (`verify_netlist.py:34-56`) matches the requirements exactly: D0 = TXD, D1 = RXD, D3 = SD, pin 12 = 3V3, pin 13 = GND, 5V not connected.
  - Its `XIAO_PINS` map matches Seeed.
  - Its U1 check, "pitch +0.95 with pin 1 at +x" combined with "lenses toward the IR edge", correctly encodes the pin-order chirality.
- **Gaps.**
  1. It reads the pad `(net ...)` labels from `circuit.json` and `.kicad_pcb`. The same exporter wrote both, so it never checks copper connectivity. It also never reads `gerbers.zip`, `cpl.csv` or `bom.csv`.
  2. It never checks header **geometry**: J1 and J2 X/Y positions, which row is which, or mirroring. Swapping J1 and J2, or mirroring the whole board, would still PASS.
  3. The lens position is assumed from the pad row (`LENS_FROM_PAD_CENTRE`), not derived from anything.
- **What I did instead.** I ran an independent check straight from `fab/gerbers.zip`. It rasterizes F.Cu and B.Cu, labels the copper islands, joins the layers through every plated hole in the PTH drill file, then reads the islands at XIAO pad positions I derived separately from Seeed's board file:
  - D0 ↔ U1.2 ↔ R3.1
  - D1 ↔ U1.3
  - D3 ↔ U1.4 ↔ R4.2
  - 3V3 ↔ U1.1 ↔ C1.2 ↔ R2.1
  - VCC1 = U1.5 ↔ C2.2 ↔ R2.2 only
  - GND ↔ U1.6, C1.1, C2.1, R3.2, R4.1
  - 5V, D2 and D4 to D10 are each isolated
  - All 5 top-side GND pour islands tie to the single bottom plane. There are 19 top islands and 14 bottom islands, with no floating copper.

  So the design passes. The script just doesn't prove it.
- **Fix.** Add a gerber-level connectivity check and a CPL sanity check (U1 at 180°, Y matches the pad row) to the build. Also assert the J1/J2 pad coordinates against Seeed's numbers: pin k of J1 at (+7.62, -7.62 + 2.54(k-1)), and J2.5 (3V3) at (-7.62, -2.54).

---

## NIT

1. **Silk below JLCPCB minimums.**
   - The U1 pin-1 circle is drawn with a 0.10 mm stroke (gerber aperture D13 on `SilkTop`), and the 0603 silk ticks use 0.12 mm (D12). JLCPCB's minimum line is about 0.15 mm, so these may not print. That's harmless, since JLCPCB uses its own footprint, but the pin-1 dot is your only visual check after assembly. Fix: 0.15 mm stroke, radius ≥ 0.25 mm.
   - Text is 0.8 mm high with a 0.15 mm stroke. JLCPCB recommends ≥ 1.0 mm.
2. **Silk is 0.24 mm from the IR edge** (the U1 body lines and the IR arrows end at gerber y -86.34, with the edge at -86.10). JLCPCB may clip them. Stop them 0.5 mm short.
3. **C1 DC-bias derating.** CL10A475KO8NNNC (4.7 µF 16 V X5R 0603) keeps only about 60 to 70 % of its value at 3.3 V.
   - One 430 mA × 1.63 µs pulse takes about 0.7 µC, which is a 0.2 to 0.25 V droop on C1 alone.
   - That is acceptable: VCC1 is behind the R2/C2 filter (τ = 4.7 µs).
   - Fix: optionally use **C19702** (CL10A106KP8NNNC, 10 µF 10 V X5R 0603, Basic, in stock) in the same footprint.
4. **Worst-case TFBS4711 average power.**
   - With no R1, a continuous stream of 0x00 bytes gives a pulse on 9 of every 10 bit times at 3/16 duty. That is about 0.17 × 430 mA ≈ 73 mA average on pin 1 at the max IRED current, against an 85 mA absolute maximum.
   - The total input power is then about 3.3 V × 73 mA ≈ 240 mW, against a 250 mW device PD.
   - Real Pokéwalker packets are short and mixed, so this is a corner case. Fix: cap continuous raw-mode TX in firmware, or (in a future revision) add a 0 Ω R1 footprint in series with pin 1.
5. **No RXD filter footprint.** The datasheet (p. 6) recommends at least 12 pF on RXD "under extreme EMI conditions". If Wi-Fi or BLE will run while the XIAO's external antenna lies near the hat, a DNP 0603 footprint from RXD to GND would be cheap insurance.
6. **ESD.** The TFBS4711 is rated 2 kV HBM, and the trimmed header tails on the outer face are bare GPIO. Fine for a DIY dongle in an enclosure; consider heat-shrink or a case over the bottom face.
7. **Solid (non-relief) SMD pad connections to the GND pour.**
   - U1 pin 6 and the GND pads of C1, C2, R3 and R4 connect solid; the other pad of each part sits on a thin trace.
   - That is a small tombstone or skew risk in reflow, low for 0603 and a 6-pad part. No action needed unless the first boards show it.
8. **The XIAO's USB-C shell legs sit above R3.**
   - Shell leg S2 maps to hat (+4.32, -9.46) and S4 to (+4.32, -5.27) (from `ESP32S3.kicad_pcb`, rotated 180° into hat coordinates).
   - S2 overlaps R3 pad 1 in XY. With standard 2.54 mm header plastic the vertical clearance is still about 1 mm or more.
   - Another reason never to use low-profile headers. Add it to the README's stacking notes.
9. **Comment inaccuracies.**
   - `index.circuit.tsx:28-30` and the README say the TFBS4711 back face is "0.2 mm beyond the XIAO's far edge". It is actually 11.27 - 10.594 = **0.68 mm**: the XIAO's far edge is +10.594 from the header centre in Seeed's board file. The error is conservative.
   - The firmware's "50 us" TXD watchdog should be 100 µs. The README already notes this.
10. **Schematic parity is not part of the build.** `kicad-cli pcb drc --schematic-parity` reports 31 warnings. All of them are cosmetic:
    - `/TXD` vs `TXD` net naming.
    - The J1/J2 DNP and exclude-from-BOM flags are set on the board but not in the schematic.
    - The Description fields are empty on the board.

    No real net conflict appears. Fix: normalize the names and add `--schematic-parity` to the build so a real conflict would show up.
11. **The gerber zip has a `gerber/` subfolder** plus drill maps, a CmtUser layer and a `.gbrjob`. This is KiKit's standard JLCPCB package and normally accepted. Check that JLCPCB's viewer identifies 2 copper layers, 2 mask, 2 silk and the outline, and doesn't mistake a drill-map file for a layer.
12. **Stock and moisture sensitivity.**
    - JLCPCB shows C102624 at **40 pcs**, Extended. Order soon, and keep the TR3 alternate (C3171514) ready.
    - The TFBS4711 has a 72 h floor life after the dry pack is opened (datasheet p. 7). JLCPCB may add a baking step. No action needed.
13. **Lens tolerance stack.** The package is ±0.2 mm, the outline is about ±0.2 mm and placement is about ±0.1 mm. So the lens tips may end up from about 0.4 mm proud of the edge to about 0.5 mm inside it. Optically both are fine: the beam half-angle is ±24° and the lens axis is 0.95 mm above the board. Size the enclosure window for it.

---

## VERIFIED-OK

**XIAO geometry, pinout and mirroring**
- **Header geometry.** Seeed's own XIAO board file has the castellations at x 140.881 and 156.121 (**15.24 mm** apart), at 2.54 mm pitch, in two 1x7 rows. The XIAO outline is 17.78 x 21.135 mm. The header-field centre is 10.541 mm from the USB edge and 10.594 mm from the far edge.
- **Pin map** (Seeed board file net names; top view, USB up):
  - Left column, top to bottom: D0/A0, D1, D2, D3, D4, D5, D6.
  - Right column, top to bottom: VBUS(5V), GND, VCC_3V3, D10, D9, D8, D7.
  - So pin 1 = D0, 12 = 3V3, 13 = GND, 14 = 5V. The OPL DIP footprint agrees: pins 1 and 14 are at the USB (+X) end, with pin 1 on the -Y row.
- **Mirroring, worked through.**
  - Both boards are viewed from above with component sides up, and the hat's top face meets the XIAO's underside. Stacking is therefore a pure 180° in-plane rotation, not a mirror: XIAO (dx, dy_down) → hat (X, Y) = (-dx, +dy_down).
  - D0 at XIAO (-7.62, -7.62) lands at hat **(+7.62, -7.62)**, which is J1.1, the square pad at the USB end. ✓
  - 3V3 (+7.62, -2.54) lands at hat (-7.62, -2.54), which is J2.5. ✓
  - GND lands at (-7.62, -5.08), which is J2.6. ✓
  - 5V lands at (-7.62, -7.62), which is J2.7. ✓
  - In the gerber drill file, J1 and J2 are at X 107.62 and X 92.38, which matches.
- **5V is unconnected.** In the gerber connectivity check, the J2.7 hole is its own island on both layers. ✓
- **Outline fit.** The hat's USB edge is at -10.5, recessed 0.04 mm from the XIAO's edge, so it is clear of the USB-C receptacle overhang. The hat is ±8.9 wide against the XIAO's ±8.89.

**TFBS4711 (datasheet 82633 rev 3.9)**
- **Pin functions** (p. 2): 1 VCC2/IRED anode, 2 TXD (active high), 3 RXD (active low), 4 SD (active high), 5 VCC1, 6 GND. The board pads carry V3V3, TXD, RXD, SD, VCC1 and GND in that order (KiCad file and gerbers). ✓
- **Pin order and lens direction.**
  - Fig. 4, side-view footprint seen from the PCB top: pads at the top, body and domes below, pins 1 to 6 left to right, emitter on the pin-1 side.
  - I cross-checked this by rotating the top-view mounting 90° about the package's long axis. That gives the same arrangement: with the lens pointing "south", pin 1 is to the "west".
  - On the board at 180°, the lenses face +Y (the IR edge) and pin 1 is at **+X**. That is the same arrangement rotated 180°. ✓
  - The EasyEDA C102624 footprint is in the same frame. ✓
- **Land pattern.** 6 pads of 0.64 x 1.27 mm at 0.95 mm pitch. The pad centre is 0.235 mm in front of the back face, so the pads stick out 0.4 mm behind it. That puts the lens tips 2.765 mm from the pad centre, which is **0.100 mm inside the edge**, with the pads 2.23 mm from the edge. ✓
- **The body is fully clear of the XIAO.** The back face is at Y 11.27 and the XIAO's far edge at 10.594. The body is 1.9 mm tall, against 2.54 mm of plastic. Nothing is above the lenses or in front of them.
- **External components** (Fig. 1 / Table 1): C1 4.7 µF at VCC2, C2 0.1 µF ceramic at VCC1, R2 47 Ω from supply to VCC1. R1 is optional and is omitted: internal control gives 200 to 430 mA. All match. ✓
- **Logic levels at 3.3 V.**
  - VCC1 is about 3.2 to 3.3 V (at most 2 mA × 47 Ω ≈ 0.1 V drop).
  - TXD VIH ≥ VCC1 - 0.5 V and SD VIH ≥ VCC1 - 0.3 V. The ESP32-S3 drives about 3.3 V into CMOS plus 10 kΩ, and an input above VCC1 is explicitly allowed.
  - RXD VOH ≥ 0.8·VCC1 ≈ 2.6 V, above the S3's VIH of 0.75·3.3 = 2.48 V.
  - RXD VOL ≤ 0.15·VCC1 ≈ 0.5 V, below the S3's VIL of 0.83 V. ✓
- **SD polarity and TXD idle.** SD low enables the transceiver and R4 pulls it low, which matches `ir_uart.cpp early_init()` (SD driven low). TXD low keeps the LED off and R3 pulls it low. The RXD output is push-pull, weak 500 kΩ to VCC1 in shutdown, and the firmware enables the internal pull-up. ✓
- **Pull-down values vs leakage.** The input leakage is ≤ 10 µA (p. 4), giving at most 0.1 V across 10 kΩ against VIL ≤ 0.4 V. ✓ (100 kΩ would not be guaranteed, as the README says.)

**Boot behaviour (ESP32-S3 datasheet Table 2-1)**
- GPIO1 and GPIO2: "IE", no pull, at reset and after reset. GPIO4: no IE and no pull (high-Z). So the external pull-downs alone set TXD and SD low.
- The 60 µs low-level power-up glitch on GPIO1, 2 and 4 is harmless (it holds the LED off and the transceiver on).
- No strapping pin is used: GPIO0, 3, 45 and 46 are untouched, and D2/GPIO3 is isolated. The UART0 log pins GPIO43/44 (D6/D7) are isolated.
- The firmware pins in `config.h` (TX 1, RX 2, SD 4) match the board.

**Electrical**
- **Decoupling placement.**
  - C2 sits directly below U1 pin 5, about 0.4 mm from pad to pad, with its own GND via.
  - C1 is next to pin 1 on a short 0.4 mm trace, with its GND via at (1.075, 8.25).
  - R2 is in series from 3V3 to VCC1.
  - VCC1 is a separate island (U1.5, C2.2 and R2.2 only).
- **Power budget.** The XIAO's 3V3 comes from an SGM6029 buck (Seeed schematic). The IR average is about 51 mA at 300 mA typical, even for continuous zeros (worst case in NIT 4), plus the ESP32-S3 on USB. The 1.6 µs peaks are buffered by C1 and the XIAO's output caps. Adequate.
- **DRC re-run** on a scratch copy with `kicad-cli pcb drc --severity-all --refill-zones`: **0 violations, 0 unconnected**.

**Mechanical**
- **Header plastic** (x 6.35 to 8.89 for J1) vs parts: the nearest part is R4 at x ≤ 6.08, which is 0.27 mm clear. R3 ends at x ≤ 5.83. The 0603 parts are ≤ 0.55 mm tall, under 2.54 mm of plastic.
- **XIAO underside** (Seeed board file, B.Cu): only flat pads.
  - BAT+/BAT- map to hat (+4.445, -0.381 / -2.286), inside the top-copper keep-out (x 2.695 to 6.6, y -3.336 to 0.669). ✓
  - The 8 test pads map to X ±1.27, Y -8.64 to -1.02, about 2.5 mm above masked copper. No XIAO bottom-side components.
- **Header drill.** 1.0 mm finished on a 1.7 mm pad (0.35 mm annular ring). A 0.64 mm square pin has a 0.905 mm diagonal, and JLCPCB's PTH tolerance of +0.13/-0.08 mm leaves at least 0.92 mm. This is the standard land, and hand-solderable with thermal reliefs on GND (0.3 mm gap, 0.45 mm spokes).
- **Dongle shape.** 17.8 x 24.4 mm, with the IR end sticking out 3.3 mm past the XIAO. About 8.5 mm tall plus the USB-C receptacle. Sensible, apart from the adapter question in S1.

**Manufacturing**
- **Gerber set** (KiCad 10 via KiKit): F/B copper, F/B mask, F/B silk, F/B paste (the bottom paste is empty), Edge.Cuts profile, plus PTH and NPTH Excellon files. All metric, with X2 FileFunction attributes.
- **Drills.** 13 × 0.30 mm vias (0.6 mm pad, 0.15 mm ring) and 14 × 1.00 mm header holes. No NPTH.
- **Edge clearance.** Minimum copper to edge is 0.42 mm (header pads on the long edges). The pours are 0.49 to 0.5 mm in. Rules: 0.2 mm clearance, ≥ 0.25 mm tracks.
- **Silk over pads.** Rasterized silk AND mask-opening = **0 px** on both sides.
- **Solder paste.** `PasteTop` has exactly 16 apertures: the 6 U1 pads plus 10 passive pads. The mask web between U1 pads is 0.31 - 2 × 0.05 = 0.21 mm.
- **BOM.**
  - The header is JLCPCB's `Comment,Designator,Footprint,LCSC Part #`, and R3/R4 are grouped.
  - Live JLCPCB check:
    - C102624 TFBS4711-TR1: Extended, 40 in stock.
    - C19666 CL10A475KO8NNNC: Basic.
    - C14663 CC0603KRX7R9BB104: Basic, 34.7 M (LCSC's own stock reads 0; JLCPCB's stock is the one that matters).
    - C23182 0603WAF470JT5E, 47 Ω 1 %: Basic.
    - C25804 0603WAF1002T5E, 10 kΩ 1 %: Basic.
  - All are 0603 except U1, and all values match.
- **CPL.**
  - KiKit format; Layer T; coordinates in the same frame as the gerbers (gerber Y = -KiCad Y).
  - Every passive's centre matches its paste pads.
  - U1 is at the pad-row centre at 180° (see S3).
  - J1/J2 are excluded (DNP / exclude from position files).
- **Economic PCBA minimum size.** 17.8 x 24.4 mm is above JLCPCB's Economic minimum, which I believe is 10 x 10 mm; confirm in the quote. Economic PCBA doesn't need fiducials.
- **JLCPCB order-number placeholder.** `JLCJLCJLCJLC` is on top, under the XIAO.

---

## Resolution

Applied 2026-11-06. No copper, pad, via, zone or outline was moved. Copper, mask, paste, outline and drill gerbers are byte-identical to the reviewed package (apart from comment headers); only the silkscreen layers, BOM (C1), README and checks changed. Rebuilt with `scripts/build.sh`: DRC 0 errors, 0 warnings, 0 unconnected; `verify_netlist.py` passes; the new gerber and silkscreen checks pass.

| Finding | Status | Reason |
|---|---|---|
| S1. USB-C receptacle | Fixed (docs) | README Assumptions now says a short male-to-male USB-C cable or adapter is needed, with a right-angle or U-shaped M-M adapter as the compact option. No PCB change. |
| S2. Panel, rails and tooling holes on the IR edge | Fixed (docs) | README ordering steps: enable "Confirm Production File" and reject any rails, tabs, V-scores or tooling holes on the IR edge. Also "Specify a location" for the order number. |
| S3. U1 placement check | Fixed (docs) | README step 6 has the quick check: IR edge at the top, lenses up, pin-1 marker at the right-hand end next to C1; a 180 degree error puts 3V3 on the GND pad. `gerber_netcheck.py` also asserts U1 = 180 in the CPL. |
| S4. `verify_netlist.py` not independent | Fixed | `scripts/gerber_netcheck.py` traces copper on both layers through plated holes from `fab/gerbers.zip` and asserts the intended nets by pad location, the J1/J2 geometry (15.24 mm rows, 2.54 mm pitch, D0 = J1.1 at the USB end, 3V3 = J2.5, GND = J2.6, 5V = J2.7 isolated), and the BOM/CPL (LCSC numbers, U1 at 180, headers excluded). Run from `build.sh` and from `verify_netlist.py` when it is run standalone. It was shown to fail on a shifted J1 header, a swapped J1/J2 header, exchanged U1 pins, a U1 rotation of 0, the old C1 number and a header left in the CPL. The lens position is still assumed from the pad row (the existing KiCad-side check). |
| NIT 1. Silk below minimums | Fixed | All silk strokes are at least 0.15 mm (KiCad post-processing clamps the 0603 and U1 outlines; the U1 pin-1 circle is now a filled dot). Text is 1.0 mm high everywhere, with the labels on the bottom-left moved 0.4 mm clear of J2. `silk_check.py` verifies strokes, text height and that silk over mask openings is 0 px on both sides. |
| NIT 2. Silk 0.24 mm from the IR edge | Fixed | U1 body lines shortened; silk is now 0.43 mm from the IR edge and at least 0.34 mm from the outline anywhere. Checked by `silk_check.py` (0.3 mm limit). |
| NIT 3. C1 DC-bias derating | Fixed | C1 is now 10 uF 10 V X5R 0603, C19702 (Basic), same footprint. Updated in the source, post-processing, BOM, README and docs/hardware.md. |
| NIT 4. Worst-case TFBS4711 average power | Deferred to v0.2 | Needs either a firmware cap on continuous raw-mode TX or a 0 ohm R1 footprint (copper change). Real packets are short and mixed. |
| NIT 5. No RXD filter footprint | Deferred to v0.2 | Needs a new DNP 0603 pad pair (copper change). |
| NIT 6. ESD on bare header tails | Deferred to v0.2 | Needs added parts or a case; fine for a DIY dongle in an enclosure. |
| NIT 7. Solid SMD connections to the GND pour | Deferred to v0.2 | Needs copper (thermal relief) changes; low risk for 0603. Revisit if the first boards show tombstoning. |
| NIT 8. USB-C shell legs above R3 | Fixed (docs) | Added to the README assumptions: never use low-profile headers. |
| NIT 9. Comment inaccuracies | Fixed | "0.2 mm" is now 0.68 mm in the source comment and README. The TFBS4711 TXD watchdog is 100 us (the TFDU4101 is 50 us) in `config.h`, `ir_uart.cpp` and `firmware/README.md`; `docs/hardware.md` already had it right. Comment-only change; the firmware still builds for `seeed_xiao_esp32s3`. |
| NIT 10. Schematic parity | Deferred to v0.2 | Name normalisation plus a `--schematic-parity` build step is not trivial, and all 31 warnings are cosmetic. |
| NIT 11. Gerber zip layout | Won't fix | KiKit's standard JLCPCB package. The README ordering step already says to check the viewer's layer detection. |
| NIT 12. Stock and moisture | Fixed (docs) / won't fix | README notes about 40 TR1 at JLCPCB and C3171514 (TR3) as the alternate. Moisture floor life needs no action. |
| NIT 13. Lens tolerance stack | Won't fix | A property of the part and fab tolerances, not a defect. Size the enclosure window for about +0.4 / -0.5 mm. |

## Correction (2026-11-12)

NIT 9 and the VERIFIED-OK line "The back face is at Y 11.27" are wrong. The package back face is on the side away from the lenses, so it is the pad-row centre **minus** 0.235 mm: 11.035 - 0.235 = **10.80**, not 11.27. Against the XIAO's far edge at 10.594, the body sits about **0.2 mm** beyond it, as the original comment said. The rear ~0.2 mm of U1's pads therefore sits under the XIAO edge. The body is still fully outside the XIAO's shadow, so nothing changes in the design. Found in a post-order review; the README and the `index.circuit.tsx` comment now give 0.2 mm.

The built v0.1 boards confirm the fit: the headers supplied with the XIAO measured about 2.55 mm of plastic, and the 1.9 mm TFBS4711 cleared it with room to spare.
