#!/usr/bin/env python3
"""Turn tscircuit's KiCad export into the fab-ready KiCad board.

Run with the pcb-env venv python (pcbnew importable):
    bin/py scripts/kicad_postprocess.py build/export.kicad_pcb build/export.kicad_sch kicad/

Placement, pads, traces, vias, silkscreen and the outline all come from
index.circuit.tsx unchanged. This script only adds what the exporter does not
carry over, and every change is listed here:

  1. Delete the empty "tscircuit:Unknown" footprints the exporter emits for named
     vias (they have no pads and would otherwise leak into the BOM/CPL).
  2. Solder paste: drop tscircuit's separate 70 % paste-only pads and put F.Paste
     back on each SMD copper pad (paste = pad, KiCad/JLCPCB default).
  3. Silkscreen: the auto-placed 0.4 mm reference designators are below the
     JLCPCB minimum text height, so they move to F.Fab (assembly drawing).
  4. 3D models for STEP/render (KiCad stock 0603 + 1x07 header models, and the
     EasyEDA TFBS4711 STEP imported by easyeda2kicad).
  5. GND zones on F.Cu and B.Cu rebuilt as normal KiCad zones (0.5 mm in from
     the edge, 0.25 mm clearance, thermal reliefs on the through-hole header
     pads, islands removed), plus a top-copper keep-out rule area under the
     XIAO's BAT+/BAT- pads; then refilled.
  6. Board setup: JLCPCB-comfortable design rules, 0.05 mm mask expansion,
     1.6 mm stackup, title block; LCSC fields added to the schematic symbols
     for KiKit.
"""
import json
import os
import re
import sys

import pcbnew

SRC_PCB, SRC_SCH, OUTDIR = sys.argv[1], sys.argv[2], sys.argv[3]
NAME = "xiao-irda-hat"
OUT_PCB = os.path.join(OUTDIR, NAME + ".kicad_pcb")
OUT_SCH = os.path.join(OUTDIR, NAME + ".kicad_sch")
OUT_PRO = os.path.join(OUTDIR, NAME + ".kicad_pro")

# KiCad's import of a tscircuit board puts the tscircuit origin at (100, 100)
# and flips Y. Helpers convert tscircuit (mm, +Y up) to KiCad internal units.
OX, OY = 100.0, 100.0


def seq(container):
    """KiCad 10 SWIG containers are indexable but not iterable under Python 3.14."""
    return [container[i] for i in range(container.size())]


def kc(x, y):
    return pcbnew.VECTOR2I(pcbnew.FromMM(OX + x), pcbnew.FromMM(OY - y))


# Single source of truth for parts that are factory assembled.
LCSC = {
    "U1": ("C102624", "TFBS4711-TR1"),
    "C1": ("C19702", "10uF 10V X5R"),
    "C2": ("C14663", "100nF 50V X7R"),
    "R2": ("C23182", "47R 1%"),
    "R3": ("C25804", "10k 1%"),
    "R4": ("C25804", "10k 1%"),
}

MODEL_DIR = "${KICAD10_3DMODEL_DIR}"
MODELS = {
    "R_0603_1608Metric": (MODEL_DIR + "/Resistor_SMD.3dshapes/R_0603_1608Metric.step", (0, 0, 0), (0, 0, 0)),
    "C_0603_1608Metric": (MODEL_DIR + "/Capacitor_SMD.3dshapes/C_0603_1608Metric.step", (0, 0, 0), (0, 0, 0)),
    # easyeda2kicad's STEP for C102624 has the right orientation for our footprint
    # (lenses toward local +y) but its bounding box is x +/-3, y(3D) -2.1..+0.9,
    # z -0.95..+0.95: half sunk into the board and 0.665 mm too far back. Shift it
    # so the back face is 0.235 mm behind the pad centre and the lens tips 2.765 mm
    # in front (datasheet Fig. 3/4), sitting on the board surface.
    "TFBS4711_SideView_Vishay": (
        "${KIPRJMOD}/../footprints/tfbs4711.3dshapes/OPTO-SMD_TFBS4711-TR1.step",
        (0, -0.665, 0.951),
        (0, 0, 0),
    ),
    # KiCad header model: pin 1 at the origin, pins toward +Y (screen down).
    # Our footprint origin is the row centre with pin 1 at local y = +7.62
    # (screen down), pin 7 at -7.62, so shift the model up by 7.62 mm and turn
    # it 180 degrees. 3D offsets use +Y = screen up.
    "XIAO_Header_1x07_P2.54mm": (
        MODEL_DIR + "/Connector_PinHeader_2.54mm.3dshapes/PinHeader_1x07_P2.54mm_Vertical.step",
        (0, -7.62, 0),
        (0, 0, 180),
    ),
}

board = pcbnew.LoadBoard(SRC_PCB)

# ---------------------------------------------------------------- 1. empty fps
# Collect first, then remove: removing inside the iteration breaks the SWIG
# proxies under Python 3.14. Removed objects are kept referenced (GRAVEYARD)
# so Python never frees memory KiCad still knows about.
GRAVEYARD = []
empty = [f for f in board.GetFootprints() if f.Pads().size() == 0]
for f in empty:
    board.Remove(f)
GRAVEYARD += empty

# ---------------------------------------------------------------- 2-4. per footprint
for fp in list(board.GetFootprints()):
    ref = fp.GetReference()
    paste_only = [
        p
        for p in seq(fp.Pads())
        if p.GetNumber() == ""
        and not p.GetLayerSet().Contains(pcbnew.F_Cu)
        and not p.GetLayerSet().Contains(pcbnew.B_Cu)
    ]
    for p in paste_only:
        fp.Remove(p)
    GRAVEYARD += paste_only
    for pad in seq(fp.Pads()):
        if pad.GetAttribute() == pcbnew.PAD_ATTRIB_SMD:
            ls = pad.GetLayerSet()
            ls.AddLayer(pcbnew.F_Paste)
            pad.SetLayerSet(ls)

    # reference designator to the fab layer, readable size
    rf = fp.Reference()
    rf.SetLayer(pcbnew.F_Fab)
    rf.SetVisible(True)
    rf.SetTextSize(pcbnew.VECTOR2I(pcbnew.FromMM(0.5), pcbnew.FromMM(0.5)))
    rf.SetTextThickness(pcbnew.FromMM(0.08))
    rf.SetPosition(fp.GetPosition())
    small_silk = [
        g
        for g in (x.Cast() for x in seq(fp.GraphicalItems()))
        if isinstance(g, pcbnew.PCB_TEXT)
        and g.GetLayer() == pcbnew.F_SilkS
        and (g.GetText() in (ref, "${REFERENCE}") or g.GetTextHeight() < pcbnew.FromMM(0.8))
    ]
    for g in small_silk:
        fp.Remove(g)
    GRAVEYARD += small_silk

    # JLCPCB silkscreen minimum: every stroke >= 0.15 mm; the pin-1 circle becomes a filled dot
    for g in (x.Cast() for x in seq(fp.GraphicalItems())):
        if g.GetLayer() in (pcbnew.F_SilkS, pcbnew.B_SilkS) and isinstance(g, pcbnew.PCB_SHAPE):
            if g.GetWidth() < pcbnew.FromMM(0.15):
                g.SetWidth(pcbnew.FromMM(0.15))
            if g.GetShape() == pcbnew.SHAPE_T_CIRCLE:
                g.SetFilled(True)

    if ref in LCSC:
        code, value = LCSC[ref]
        exported = fp.GetFieldText("LCSC") if fp.HasField("LCSC") else ""
        assert exported == code, f"{ref}: LCSC {exported!r} in index.circuit.tsx != {code!r} here"
        fp.SetValue(value)
        fp.SetField("LCSC", code)

    name = str(fp.GetFPID().GetLibItemName())
    fp.SetFPID(pcbnew.LIB_ID("melonds_walker", name))
    if name in MODELS:
        path, off, rot = MODELS[name]
        fp.Models().clear()
        m = pcbnew.FP_3DMODEL()
        m.m_Filename = path
        m.m_Offset = pcbnew.VECTOR3D(*off)
        m.m_Rotation = pcbnew.VECTOR3D(*rot)
        m.m_Scale = pcbnew.VECTOR3D(1, 1, 1)
        fp.Models().push_back(m)

# ---------------------------------------------------------------- 5. zones
old_zones = list(board.Zones())
for z in old_zones:
    board.Remove(z)
GRAVEYARD += old_zones

gnd = board.GetNetInfo().GetNetItem("GND")
assert gnd is not None, "GND net missing"


def poly(points):
    chain = pcbnew.SHAPE_LINE_CHAIN()
    for x, y in points:
        chain.Append(kc(x, y))
    chain.SetClosed(True)
    return chain


# zone outline: the board outline (x +/-8.9, y -10.5..13.9, corner r 1.0) inset
# 0.5 mm, with concentric 0.5 mm corner arcs
import math

ZX0, ZX1, ZY0, ZY1, ZR = -8.4, 8.4, -10.0, 13.4, 0.5
ZONE_PTS = [(0.0, ZY0)]  # note: KiCad reports zone DRC markers at this first vertex
for cx, cy, a0 in ((ZX1 - ZR, ZY0 + ZR, -90), (ZX1 - ZR, ZY1 - ZR, 0), (ZX0 + ZR, ZY1 - ZR, 90), (ZX0 + ZR, ZY0 + ZR, 180)):
    for i in range(7):
        a = math.radians(a0 + 15 * i)
        ZONE_PTS.append((cx + ZR * math.cos(a), cy + ZR * math.sin(a)))

for layer in (pcbnew.F_Cu, pcbnew.B_Cu):
    z = pcbnew.ZONE(board)
    z.SetLayer(layer)
    z.SetNet(gnd)
    z.Outline().AddOutline(poly(ZONE_PTS))
    z.SetLocalClearance(pcbnew.FromMM(0.25))
    z.SetMinThickness(pcbnew.FromMM(0.2))
    z.SetPadConnection(pcbnew.ZONE_CONNECTION_THT_THERMAL)
    z.SetThermalReliefGap(pcbnew.FromMM(0.3))
    z.SetThermalReliefSpokeWidth(pcbnew.FromMM(0.45))
    z.SetIslandRemovalMode(pcbnew.ISLAND_REMOVAL_MODE_ALWAYS)
    z.SetZoneName("GND_" + ("TOP" if layer == pcbnew.F_Cu else "BOTTOM"))
    board.Add(z)

# keep-out under the XIAO battery pads (top copper only), taken from the
# <keepout> in index.circuit.tsx via tscircuit's circuit JSON
CIRCUIT_JSON = os.path.join(os.path.dirname(os.path.abspath(SRC_PCB)), "..", "dist", "index", "circuit.json")
_ko = [e for e in json.load(open(CIRCUIT_JSON)) if e["type"] == "pcb_keepout"]
assert len(_ko) == 1 and _ko[0]["shape"] == "rect", "expected one rectangular keep-out"
KX, KY = _ko[0]["center"]["x"], _ko[0]["center"]["y"]
KW, KH = _ko[0]["width"], _ko[0]["height"]
ka = pcbnew.ZONE(board)
ka.SetIsRuleArea(True)
ka.SetLayer(pcbnew.F_Cu)
ka.SetDoNotAllowTracks(True)
ka.SetDoNotAllowVias(True)
ka.SetDoNotAllowZoneFills(True)
ka.SetDoNotAllowPads(True)
ka.SetDoNotAllowFootprints(False)
ka.SetZoneName("KEEPOUT_XIAO_BATTERY_PADS")
ka.Outline().AddOutline(
    poly([(KX - KW / 2, KY - KH / 2), (KX + KW / 2, KY - KH / 2), (KX + KW / 2, KY + KH / 2), (KX - KW / 2, KY + KH / 2)])
)
board.Add(ka)

# ---------------------------------------------------------------- 6. setup
ds = board.GetDesignSettings()
ds.SetBoardThickness(pcbnew.FromMM(1.6))
ds.m_SolderMaskExpansion = pcbnew.FromMM(0.05)
ds.m_SolderMaskMinWidth = pcbnew.FromMM(0.1)

tb = board.GetTitleBlock()
tb.SetTitle("melonDS-walker XIAO IrDA hat")
tb.SetRevision("v0.1")
tb.SetCompany("melonDS-walker (DIY, not a product)")
tb.SetComment(0, "Generated from index.circuit.tsx (tscircuit) by scripts/kicad_postprocess.py")

filler = pcbnew.ZONE_FILLER(board)
filler.Fill(board.Zones())

os.makedirs(OUTDIR, exist_ok=True)
pcbnew.SaveBoard(OUT_PCB, board)

# Project file: design rules (JLCPCB 2-layer capability with margin) and the
# DRC severities for checks that do not apply to a generated board.
pro = {
    "meta": {"filename": NAME + ".kicad_pro", "version": 3},
    "board": {
        "design_settings": {
            "defaults": {"board_outline_line_width": 0.1},
            "rules": {
                "min_clearance": 0.2,
                "min_track_width": 0.2,
                "min_connection": 0.2,
                "min_via_diameter": 0.6,
                "min_via_annular_width": 0.15,
                "min_through_hole_diameter": 0.3,
                "min_hole_clearance": 0.25,
                "min_hole_to_hole": 0.5,
                "min_copper_edge_clearance": 0.3,
                "min_text_height": 0.8,
                "min_text_thickness": 0.15,
                "min_silk_clearance": 0.0,
                "solder_mask_to_copper_clearance": 0.0,
                "min_microvia_diameter": 0.2,
                "min_microvia_drill": 0.1,
                "max_error": 0.005,
                "use_height_for_length_calcs": True,
                "allow_blind_buried_vias": False,
                "allow_microvias": False,
            },
            "rule_severities": {
                # generated footprints are not from a configured library
                "lib_footprint_issues": "ignore",
                "lib_footprint_mismatch": "ignore",
            },
        }
    },
    "net_settings": {
        "classes": [
            {
                "name": "Default",
                "clearance": 0.2,
                "track_width": 0.25,
                "via_diameter": 0.6,
                "via_drill": 0.3,
                "microvia_diameter": 0.3,
                "microvia_drill": 0.1,
                "diff_pair_gap": 0.25,
                "diff_pair_width": 0.2,
                "diff_pair_via_gap": 0.25,
                "wire_width": 6,
                "bus_width": 12,
                "line_style": 0,
                "schematic_color": "rgba(0, 0, 0, 0.000)",
                "pcb_color": "rgba(0, 0, 0, 0.000)",
                "priority": 2147483647,
            }
        ],
        "meta": {"version": 4},
    },
}
with open(OUT_PRO, "w") as f:
    json.dump(pro, f, indent=2)

# ---------------------------------------------------------------- schematic
# KiKit reads Value, Footprint and the LCSC order code from the schematic
# symbols, so set them on each placed symbol from the same tables as the board.
SCH_FOOTPRINT = {
    "U1": "TFBS4711_SideView_Vishay",
    "C1": "C_0603_1608Metric",
    "C2": "C_0603_1608Metric",
    "R2": "R_0603_1608Metric",
    "R3": "R_0603_1608Metric",
    "R4": "R_0603_1608Metric",
    "J1": "XIAO_Header_1x07_P2.54mm",
    "J2": "XIAO_Header_1x07_P2.54mm",
}


def top_level_symbol_blocks(text):
    """Yield (start, end) of each placed '(symbol (lib_id ...' block."""
    for m in re.finditer(r"\(symbol\s*\(lib_id ", text):
        depth, i = 0, m.start()
        while True:
            c = text[i]
            if c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
                if depth == 0:
                    yield m.start(), i + 1
                    break
            elif c == '"':
                i = text.index('"', i + 1)
                while text[i - 1] == "\\":
                    i = text.index('"', i + 1)
            i += 1


def set_prop(block, name, value):
    pat = re.compile(r'(\(property "' + re.escape(name) + r'" )"[^"]*"')
    if pat.search(block):
        return pat.sub(lambda m: m.group(1) + '"' + value + '"', block, count=1)
    # insert a hidden property just after the Reference property
    i = block.index('(property "Reference"')
    return (
        block[:i]
        + f'(property "{name}" "{value}" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))\n      '
        + block[i:]
    )


sch = open(SRC_SCH).read()
out, pos, seen = [], 0, set()
for a, b in list(top_level_symbol_blocks(sch)):
    block = sch[a:b]
    m = re.search(r'\(property "Reference" "([^"]+)"', block)
    ref = m.group(1) if m else None
    if ref in SCH_FOOTPRINT:
        block = set_prop(block, "Footprint", "melonds_walker:" + SCH_FOOTPRINT[ref])
        if ref in LCSC:
            block = set_prop(block, "Value", LCSC[ref][1])
            block = set_prop(block, "LCSC", LCSC[ref][0])
        seen.add(ref)
    out.append(sch[pos:a])
    out.append(block)
    pos = b
out.append(sch[pos:])
missing = set(SCH_FOOTPRINT) - seen
assert not missing, f"schematic symbols not found: {missing}"
open(OUT_SCH, "w").write("".join(out))

print(f"wrote {OUT_PCB}, {OUT_PRO}, {OUT_SCH}", flush=True)
# Skip interpreter teardown: SWIG destructors on removed KiCad objects can crash.
sys.stderr.flush()
os._exit(0)
