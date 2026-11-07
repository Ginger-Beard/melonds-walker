// melonDS-walker XIAO IrDA hat v0.1
//
// A 2-layer carrier that sits UNDER a Seeed Studio XIAO ESP32S3 (XIAO on top,
// joined by two 1x7 2.54 mm headers) and carries a Vishay TFBS4711 IrDA SIR
// transceiver, side-view, at the end opposite the XIAO's USB-C connector.
//
// Coordinates: millimetres, tscircuit convention (+Y up), origin at the centre
// of the XIAO header field. Seen from the top (component side, XIAO side) the
// USB-C end is at -Y and the IR window edge is at +Y. Every part position and
// every copper trace is given explicitly below; the autorouter is disabled.
//
// Dimension sources (see README.md for the full list):
//  - XIAO header holes, 15.24 mm row spacing, 2.54 mm pitch, pin 1 = D0 at the
//    USB end: Seeed OPL_Kicad_Library XIAO-ESP32-S3-DIP.kicad_mod (pads at
//    x = +/-7.62, y = +/-7.62) and the Seeed wiki pin map. Dimensions only.
//  - XIAO outline 17.78 x ~21 mm and its bottom-side pads (battery BAT+/BAT-,
//    test pads): Seeed OPL "Seeed Studio XIAO ESP32S3/ESP32S3.kicad_pcb".
//  - TFBS4711 side-view land pattern: Vishay datasheet 82633 rev 3.9 Fig. 4
//    (6 pads, 0.95 mm pitch, 0.64 x 1.27 mm, pads extend 0.4 mm behind the
//    package back face) and Fig. 3 (6 x 3 x 1.9 mm body, lenses 3 mm from back).

type Pt = { x: number; y: number }

// --- board geometry --------------------------------------------------------
const BOARD = { xMin: -8.9, xMax: 8.9, yMin: -10.5, yMax: 13.9, r: 1.0 }

// TFBS4711: pad-row centre. Datasheet: lens tip is 2.765 mm in front of the
// pad centre (3.0 mm body depth - 0.235 mm). Lens tip sits 0.1 mm inside the
// board edge; the package back face (pad centre + 0.235 = y 11.27) is 0.68 mm
// beyond the XIAO's far edge (y +10.594 from the header centre in Seeed's board
// file), so the whole body is outside the XIAO shadow.
const U1_Y = BOARD.yMax - 0.1 - 2.765 // 11.035

// Component placement table. rot = pcbRotation (degrees, CCW).
const PL: Record<string, { x: number; y: number; rot: number }> = {
  U1: { x: 0, y: U1_Y, rot: 180 },
  J1: { x: 7.62, y: 0, rot: 0 }, // XIAO pins 1..7  (D0..D6), USB end first
  J2: { x: -7.62, y: 0, rot: 0 }, // XIAO pins 8..14 (D7..5V), far end first
  C1: { x: 1.9, y: 9.35, rot: 0 }, // 10 uF (C19702), VCC2 / IRED anode buffer
  C2: { x: -1.425, y: 8.75, rot: 90 }, // 100 nF, VCC1 decoupling
  R2: { x: -3.0, y: 8.3, rot: 90 }, // 47 R, VCC1 supply filter
  R3: { x: 4.6, y: -8.7, rot: 0 }, // 10 k, TXD pull-down
  R4: { x: 5.6, y: 6.0, rot: 90 }, // 10 k, SD pull-down
}

const r3 = (v: number) => Math.round(v * 1e4) / 1e4

// tscircuit applies the anchor component's transform to pcbPath points, so
// convert absolute board coordinates into that component's local frame.
const local = (ref: string, pts: Pt[]): Pt[] => {
  const p = PL[ref]
  const a = (-p.rot * Math.PI) / 180
  return pts.map(({ x, y }) => {
    const dx = x - p.x
    const dy = y - p.y
    return {
      x: r3(dx * Math.cos(a) - dy * Math.sin(a)),
      y: r3(dx * Math.sin(a) + dy * Math.cos(a)),
    }
  })
}

// Rounded-rectangle board outline.
const outline = (() => {
  const { xMin, xMax, yMin, yMax, r } = BOARD
  const pts: Pt[] = []
  const arc = (cx: number, cy: number, a0: number) => {
    for (let i = 0; i <= 6; i++) {
      const a = ((a0 + i * 15) * Math.PI) / 180
      pts.push({ x: r3(cx + r * Math.cos(a)), y: r3(cy + r * Math.sin(a)) })
    }
  }
  arc(xMax - r, yMin + r, -90)
  arc(xMax - r, yMax - r, 0)
  arc(xMin + r, yMax - r, 90)
  arc(xMin + r, yMin + r, 180)
  return pts
})()

// --- trace widths ------------------------------------------------------------
const W_SIG = "0.25mm"
const W_PWR = "0.4mm"

// Channel under the TFBS4711 body (between the pad tips and the lenses):
// TXD, RXD and SD leave their pads from the inner end and exit east.
const CH_TX = 12.05
const CH_RX = 12.5
const CH_SD = 12.95
// Vertical run east of the body, 0.45 mm pitch.
const X_TX = 3.7
const X_RX = 4.15
const X_SD = 4.6
// Corridor west of the XIAO battery pads (keep-out below), 0.45 mm pitch.
const X_TX2 = 1.85
const X_RX2 = 2.3
// 45-degree jog: keeps 0.45 mm pitch, TX turns 0.1864 mm above RX.
const Y_RX_TURN = 3.2
const Y_TX_TURN = Y_RX_TURN + 0.1864

// XIAO bottom-side battery pads (BAT+ at y -0.381, BAT- at y -2.286, 2.0 x 1.0 mm
// on the XIAO; 2.5 x 1.1 mm envelope used, x 3.195..5.695) sit 2.5 mm above the
// hat. No top copper under them (+0.5 mm), so a wire soldered there cannot
// short the hat. The east side runs on to x 6.6 (just short of the J1 pads) so
// no thin sliver of pour is left between the keep-out and the header.
const BAT_KEEPOUT = { x0: 2.695, x1: 6.6, y0: -3.336, y1: 0.669 }

// TFBS4711 side-view footprint, drawn in the same orientation as the LCSC /
// EasyEDA footprint for C102624 (pin 1 at -X, lenses toward -Y) so that the
// JLCPCB rotation is simply the board rotation (180 deg here).
const tfbsPads = [1, 2, 3, 4, 5, 6].map((n) => ({
  n,
  x: r3(-2.375 + (n - 1) * 0.95),
}))

const TFBS4711 = (
  <footprint>
    {tfbsPads.map(({ n, x }) => (
      <smtpad
        key={`p${n}`}
        portHints={[`pin${n}`]}
        shape="rect"
        pcbX={x}
        pcbY={0}
        width="0.64mm"
        height="1.27mm"
      />
    ))}
    {/* body sides (package is 6 mm wide, back face at +0.235, lenses at -2.765) */}
    <silkscreenpath
      route={[
        { x: -3.15, y: -0.5 },
        { x: -3.15, y: -2.35 },
      ]}
      strokeWidth="0.15mm"
    />
    <silkscreenpath
      route={[
        { x: 3.15, y: -0.5 },
        { x: 3.15, y: -2.35 },
      ]}
      strokeWidth="0.15mm"
    />
    {/* pin 1 marker beside the back end of pad 1; postprocess makes it a filled dot */}
    <silkscreencircle pcbX={-3.2} pcbY={0.6} radius="0.15mm" />
    <courtyardrect pcbX={0} pcbY={-1.0575} width="6.5mm" height="3.615mm" />
  </footprint>
)

// XIAO header rows as 1x7 plated-hole rows (1.0 mm drill, 1.7 mm pad, the
// usual 2.54 mm header land). Pin 1 of J1 (XIAO pin 1, D0) has a square pad.
const headerRow = (dir: 1 | -1, squareFirst: boolean) => (
  <footprint>
    {[1, 2, 3, 4, 5, 6, 7].map((k) =>
      k === 1 && squareFirst ? (
        <platedhole
          key={`h${k}`}
          portHints={[`pin${k}`]}
          shape="circular_hole_with_rect_pad"
          holeDiameter="1.0mm"
          rectPadWidth="1.7mm"
          rectPadHeight="1.7mm"
          pcbX={0}
          pcbY={r3(dir * (-7.62 + (k - 1) * 2.54))}
        />
      ) : (
        <platedhole
          key={`h${k}`}
          portHints={[`pin${k}`]}
          shape="circle"
          holeDiameter="1.0mm"
          outerDiameter="1.7mm"
          pcbX={0}
          pcbY={r3(dir * (-7.62 + (k - 1) * 2.54))}
        />
      ),
    )}
    <courtyardrect pcbX={0} pcbY={0} width="2.54mm" height="18.0mm" />
  </footprint>
)

const headerMeta = {
  attributes: { through_hole: true, exclude_from_bom: true, exclude_from_pos_files: true },
}

const via = (name: string, x: number, y: number) => (
  <via
    key={name}
    name={name}
    pcbX={x}
    pcbY={y}
    holeDiameter="0.3mm"
    outerDiameter="0.6mm"
    connectsTo="net.GND"
  />
)

// GND vias: one at each decoupling / pull-down ground, plus plane stitching.
const VIAS: [string, number, number][] = [
  ["V1", -3.7, 12.05], // TFBS4711 pin 6
  ["V2", 1.075, 8.25], // C1
  ["V3", -1.425, 6.9], // C2
  ["V4", 5.6, 4.1], // R4
  ["V5", 6.45, -9.0], // R3
  ["V6", -6.6, 12.6],
  ["V7", 7.3, 12.6],
  ["V8", -3.5, 3.0],
  ["V9", -3.5, -6.0],
  ["V10", 0.0, -9.2],
  ["V11", 4.4, -4.0],
  ["V12", 0.0, -2.0],
  ["V13", 4.0, -6.35], // pocket between RXD and TXD
]

const label = (text: string, x: number, y: number, layer: "top" | "bottom", size = 1.0) => (
  <silkscreentext
    key={`${layer}-${text}-${x}-${y}`}
    text={text}
    pcbX={x}
    pcbY={y}
    fontSize={`${size}mm`}
    layer={layer}
  />
)

const arrowUp = (x: number, y0: number, y1: number, layer: "top" | "bottom") => [
  <silkscreenpath
    key={`${layer}-arrow-shaft-${x}`}
    layer={layer}
    route={[
      { x, y: y0 },
      { x, y: y1 },
    ]}
    strokeWidth="0.2mm"
  />,
  <silkscreenpath
    key={`${layer}-arrow-head-${x}`}
    layer={layer}
    route={[
      { x: x - 0.6, y: y1 - 0.7 },
      { x, y: y1 },
      { x: x + 0.6, y: y1 - 0.7 },
    ]}
    strokeWidth="0.2mm"
  />,
]

export default () => (
  <board
    outline={outline}
    thickness="1.6mm"
    layers={2}
    routingDisabled
  >
    {/* ---------------- parts ---------------- */}
    <chip
      name="U1"
      manufacturerPartNumber="TFBS4711-TR1"
      supplierPartNumbers={{ jlcpcb: ["C102624"] }}
      footprint={TFBS4711}
      pcbX={PL.U1.x}
      pcbY={PL.U1.y}
      pcbRotation={PL.U1.rot}
      pinLabels={{
        pin1: "VCC2_IRED_A",
        pin2: "TXD",
        pin3: "RXD",
        pin4: "SD",
        pin5: "VCC1",
        pin6: "GND",
      }}
      schX={2}
      schY={0}
      kicadFootprintMetadata={{
        footprintName: "TFBS4711_SideView_Vishay",
        properties: { LCSC: { value: "C102624" } },
      }}
    />
    <chip
      name="J1"
      footprint={headerRow(1, true)}
      pcbX={PL.J1.x}
      pcbY={PL.J1.y}
      doNotPlace
      pinLabels={{
        pin1: "D0_GPIO1",
        pin2: "D1_GPIO2",
        pin3: "D2_GPIO3",
        pin4: "D3_GPIO4",
        pin5: "D4_GPIO5",
        pin6: "D5_GPIO6",
        pin7: "D6_GPIO43",
      }}
      schX={-6}
      schY={1.2}
      kicadFootprintMetadata={{ footprintName: "XIAO_Header_1x07_P2.54mm", ...headerMeta }}
    />
    <chip
      name="J2"
      footprint={headerRow(-1, false)}
      pcbX={PL.J2.x}
      pcbY={PL.J2.y}
      doNotPlace
      pinLabels={{
        pin1: "D7_GPIO44",
        pin2: "D8_GPIO7",
        pin3: "D9_GPIO8",
        pin4: "D10_GPIO9",
        pin5: "V3V3",
        pin6: "GND",
        pin7: "V5V",
      }}
      schX={-6}
      schY={-2.5}
      kicadFootprintMetadata={{ footprintName: "XIAO_Header_1x07_P2.54mm", ...headerMeta }}
    />
    <capacitor
      name="C1"
      capacitance="10uF"
      maxVoltageRating="10V"
      footprint="0603"
      supplierPartNumbers={{ jlcpcb: ["C19702"] }}
      pcbX={PL.C1.x}
      pcbY={PL.C1.y}
      pcbRotation={PL.C1.rot}
      schX={-0.6}
      schY={2.6}
      schRotation={90}
      kicadFootprintMetadata={{ footprintName: "C_0603_1608Metric", properties: { LCSC: { value: "C19702" } } }}
    />
    <capacitor
      name="C2"
      capacitance="100nF"
      maxVoltageRating="50V"
      footprint="0603"
      supplierPartNumbers={{ jlcpcb: ["C14663"] }}
      pcbX={PL.C2.x}
      pcbY={PL.C2.y}
      pcbRotation={PL.C2.rot}
      schX={5.4}
      schY={-1.6}
      schRotation={90}
      kicadFootprintMetadata={{ footprintName: "C_0603_1608Metric", properties: { LCSC: { value: "C14663" } } }}
    />
    <resistor
      name="R2"
      resistance="47"
      footprint="0603"
      supplierPartNumbers={{ jlcpcb: ["C23182"] }}
      pcbX={PL.R2.x}
      pcbY={PL.R2.y}
      pcbRotation={PL.R2.rot}
      schX={5.4}
      schY={1.4}
      schRotation={90}
      kicadFootprintMetadata={{ footprintName: "R_0603_1608Metric", properties: { LCSC: { value: "C23182" } } }}
    />
    <resistor
      name="R3"
      resistance="10k"
      footprint="0603"
      supplierPartNumbers={{ jlcpcb: ["C25804"] }}
      pcbX={PL.R3.x}
      pcbY={PL.R3.y}
      pcbRotation={PL.R3.rot}
      schX={0.6}
      schY={-2.0}
      schRotation={270}
      kicadFootprintMetadata={{ footprintName: "R_0603_1608Metric", properties: { LCSC: { value: "C25804" } } }}
    />
    <resistor
      name="R4"
      resistance="10k"
      footprint="0603"
      supplierPartNumbers={{ jlcpcb: ["C25804"] }}
      pcbX={PL.R4.x}
      pcbY={PL.R4.y}
      pcbRotation={PL.R4.rot}
      schX={7.0}
      schY={-1.6}
      schRotation={90}
      kicadFootprintMetadata={{ footprintName: "R_0603_1608Metric", properties: { LCSC: { value: "C25804" } } }}
    />

    {/* ---------------- net names (connectivity only, no copper) ---------------- */}
    <trace name="n_txd" from=".U1 > .pin2" to="net.TXD" />
    <trace name="n_rxd" from=".U1 > .pin3" to="net.RXD" />
    <trace name="n_sd" from=".U1 > .pin4" to="net.SD" />
    <trace name="n_vcc1" from=".U1 > .pin5" to="net.VCC1" />
    <trace name="n_3v3" from=".U1 > .pin1" to="net.V3V3" />
    <trace name="n_gnd_u1" from=".U1 > .pin6" to="net.GND" />
    <trace name="n_gnd_j2" from=".J2 > .pin6" to="net.GND" />

    {/* ---------------- signal traces ---------------- */}
    {/* TXD: U1 pin 2 -> under body -> east run -> corridor -> XIAO D0 (J1.1) */}
    <trace
      name="t_txd"
      schDisplayLabel="TXD"
      from=".U1 > .pin2"
      to=".J1 > .pin1"
      pcbPathRelativeTo=".U1 > .pin2"
      thickness={W_SIG}
      pcbPath={local("U1", [
        { x: 1.425, y: CH_TX },
        { x: X_TX, y: CH_TX },
        { x: X_TX, y: Y_TX_TURN },
        { x: X_TX2, y: r3(Y_TX_TURN - (X_TX - X_TX2)) },
        { x: X_TX2, y: -7.62 },
      ])}
    />
    {/* RXD: U1 pin 3 -> XIAO D1 (J1.2) */}
    <trace
      name="t_rxd"
      schDisplayLabel="RXD"
      from=".U1 > .pin3"
      to=".J1 > .pin2"
      pcbPathRelativeTo=".U1 > .pin3"
      thickness={W_SIG}
      pcbPath={local("U1", [
        { x: 0.475, y: CH_RX },
        { x: X_RX, y: CH_RX },
        { x: X_RX, y: Y_RX_TURN },
        { x: X_RX2, y: r3(Y_RX_TURN - (X_RX - X_RX2)) },
        { x: X_RX2, y: -5.08 },
      ])}
    />
    {/* SD: U1 pin 4 -> XIAO D3 (J1.4) */}
    <trace
      name="t_sd"
      schDisplayLabel="SD"
      from=".U1 > .pin4"
      to=".J1 > .pin4"
      pcbPathRelativeTo=".U1 > .pin4"
      thickness={W_SIG}
      pcbPath={local("U1", [
        { x: -0.475, y: CH_SD },
        { x: X_SD, y: CH_SD },
        { x: X_SD, y: 1.5 },
        { x: 6.1, y: 1.5 },
      ])}
    />
    {/* R3 (TXD pull-down) tap */}
    <trace
      name="t_txd_pd"
      schDisplayLabel="TXD"
      from=".R3 > .pin1"
      to=".J1 > .pin1"
      pcbPathRelativeTo=".R3 > .pin1"
      thickness={W_SIG}
      pcbPath={local("R3", [{ x: 3.775, y: -7.62 }])}
    />
    {/* R4 (SD pull-down) tap */}
    <trace
      name="t_sd_pd"
      schDisplayLabel="SD"
      from=".J1 > .pin4"
      to=".R4 > .pin2"
      pcbPathRelativeTo=".J1 > .pin4"
      thickness={W_SIG}
      pcbPath={local("J1", [
        { x: 6.1, y: 1.5 },
        { x: X_SD, y: 1.5 },
        { x: X_SD, y: 6.825 },
      ])}
    />

    {/* ---------------- power traces ---------------- */}
    {/* 3V3 from XIAO pin 12 (J2.5) to C1 / IRED anode */}
    <trace
      name="t_3v3_c1"
      schDisplayLabel="V3V3"
      from=".J2 > .pin5"
      to=".C1 > .pin2"
      pcbPathRelativeTo=".J2 > .pin5"
      thickness={W_PWR}
      pcbPath={local("J2", [
        { x: -5.0, y: -2.54 },
        { x: -5.0, y: 6.0 },
        { x: 2.725, y: 6.0 },
      ])}
    />
    {/* 3V3 branch to R2 (VCC1 filter) */}
    <trace
      name="t_3v3_r2"
      schDisplayLabel="V3V3"
      from=".J2 > .pin5"
      to=".R2 > .pin1"
      pcbPathRelativeTo=".J2 > .pin5"
      thickness={W_PWR}
      pcbPath={local("J2", [
        { x: -5.0, y: -2.54 },
        { x: -5.0, y: 6.0 },
        { x: -3.0, y: 6.0 },
      ])}
    />
    {/* VCC2 / IRED anode (pin 1) to C1 */}
    <trace
      name="t_vcc2"
      schDisplayLabel="V3V3"
      from=".U1 > .pin1"
      to=".C1 > .pin2"
      pcbPathRelativeTo=".U1 > .pin1"
      thickness={W_PWR}
      pcbPath={local("U1", [{ x: 2.375, y: 10.0 }])}
    />
    {/* VCC1 (pin 5) to C2, and to R2 */}
    <trace
      name="t_vcc1_c2"
      schDisplayLabel="VCC1"
      from=".U1 > .pin5"
      to=".C2 > .pin2"
      pcbPathRelativeTo=".U1 > .pin5"
      thickness="0.3mm"
      pcbPath={[]}
    />
    <trace
      name="t_vcc1_r2"
      schDisplayLabel="VCC1"
      from=".U1 > .pin5"
      to=".R2 > .pin2"
      pcbPathRelativeTo=".U1 > .pin5"
      thickness="0.3mm"
      pcbPath={local("U1", [
        { x: -1.425, y: 9.35 },
        { x: -3.0, y: 9.35 },
      ])}
    />

    {/* ---------------- ground stubs to vias ---------------- */}
    <trace
      name="t_gnd_u1"
      from=".U1 > .pin6"
      to="net.GND"
      pcbPathRelativeTo=".U1 > .pin6"
      thickness={W_PWR}
      pcbPath={local("U1", [
        { x: -2.375, y: 12.05 },
        { x: -3.7, y: 12.05 },
      ])}
    />
    <trace
      name="t_gnd_c1"
      from=".C1 > .pin1"
      to="net.GND"
      pcbPathRelativeTo=".C1 > .pin1"
      thickness={W_PWR}
      pcbPath={local("C1", [{ x: 1.075, y: 8.25 }])}
    />
    <trace
      name="t_gnd_c2"
      from=".C2 > .pin1"
      to="net.GND"
      pcbPathRelativeTo=".C2 > .pin1"
      thickness={W_PWR}
      pcbPath={local("C2", [{ x: -1.425, y: 6.9 }])}
    />
    <trace
      name="t_gnd_r4"
      from=".R4 > .pin1"
      to="net.GND"
      pcbPathRelativeTo=".R4 > .pin1"
      thickness={W_PWR}
      pcbPath={local("R4", [{ x: 5.6, y: 4.1 }])}
    />
    <trace
      name="t_gnd_r3"
      from=".R3 > .pin2"
      to="net.GND"
      pcbPathRelativeTo=".R3 > .pin2"
      thickness={W_PWR}
      pcbPath={local("R3", [{ x: 6.45, y: -9.0 }])}
    />

    {VIAS.map(([n, x, y]) => via(n, x, y))}

    {/* ---------------- copper ---------------- */}
    <keepout
      shape="rect"
      pcbX={r3((BAT_KEEPOUT.x0 + BAT_KEEPOUT.x1) / 2)}
      pcbY={r3((BAT_KEEPOUT.y0 + BAT_KEEPOUT.y1) / 2)}
      width={`${r3(BAT_KEEPOUT.x1 - BAT_KEEPOUT.x0)}mm`}
      height={`${r3(BAT_KEEPOUT.y1 - BAT_KEEPOUT.y0)}mm`}
      layers={["top"]}
    />
    <copperpour layer="top" connectsTo="net.GND" boardEdgeMargin="0.5mm" clearance="0.25mm" />
    <copperpour layer="bottom" connectsTo="net.GND" boardEdgeMargin="0.5mm" clearance="0.25mm" />

    {/* ---------------- silkscreen: top (XIAO side) ---------------- */}
    {label("TX", 5.6, -6.85, "top")}
    {label("RX", 5.6, -4.3, "top")}
    {label("SD", 5.6, 0.75, "top")}
    {label("3V3", -5.4, -1.75, "top")}
    {label("GND", -5.4, -4.3, "top")}
    {label("USB-C", -3.2, -9.6, "top")}
    {/* JLCPCB order-number placeholder ("Specify a location"), hidden under the XIAO */}
    {label("JLCJLCJLCJLC", -1.4, -7.2, "top")}
    {label("IR", -5.0, 11.2, "top")}
    {label("IR", 5.6, 11.2, "top")}
    {arrowUp(-6.4, 10.9, 13.2, "top")}
    {arrowUp(6.4, 10.9, 13.2, "top")}

    {/* ---------------- silkscreen: bottom (outside face) ---------------- */}
    {label("melonDS-walker", 0, 6.4, "bottom")}
    {label("XIAO IrDA hat", 0, 4.8, "bottom")}
    {label("v0.1", 0, 3.3, "bottom")}
    {label("XIAO on top", 0, 1.6, "bottom")}
    {label("TX", 5.6, -7.62, "bottom")}
    {label("RX", 5.6, -5.08, "bottom")}
    {label("SD", 5.6, 0.0, "bottom")}
    {label("3V3", -5.0, -2.54, "bottom")}
    {label("GND", -5.0, -5.08, "bottom")}
    {label("USB-C", 0, -9.3, "bottom")}
    {label("IR", -1.5, 11.0, "bottom")}
    {arrowUp(0, 8.4, 13.1, "bottom")}
  </board>
)
