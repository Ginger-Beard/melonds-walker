#!/usr/bin/env python3
"""Fab-package check, independent of the tscircuit and KiCad exporters.

Reads fab/gerbers.zip, fab/bom.csv and fab/cpl.csv only. It rasterizes the top
and bottom copper, joins the layers through every plated hole in the PTH drill
file, and then asserts:

  1. Header geometry (J1/J2 holes) against the XIAO ESP32S3 castellation
     geometry: two rows 15.24 mm apart, 2.54 mm pitch, D0 = J1.1 at the USB end,
     3V3 = J2.5, GND = J2.6, 5V = J2.7.
  2. Connectivity: pads, identified by physical location, form exactly the
     intended nets. 5V and the unused GPIOs are isolated. No floating copper.
  3. BOM/CPL: every SMD designator present with the right LCSC number, U1 at
     rotation 180, headers excluded.

Run through pcb-env (needs numpy, Pillow, scipy):

    pcb-env/bin/py scripts/gerber_netcheck.py [fab/gerbers.zip]
    pcb-env/bin/py scripts/gerber_netcheck.py --self-test   # prove it can fail
"""
import csv
import math
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gerblib as G  # noqa: E402
import numpy as np  # noqa: E402
from scipy import ndimage  # noqa: E402

HERE = Path(__file__).resolve().parent.parent
FAB = HERE / "fab"

# ---------------------------------------------------------------------------
# Physical truth, written by hand. Gerber coordinates (x, y); the board centre
# is at x = 100, the USB end is the low-y edge (y = -110.5), the IR edge is at
# y = -86.1.
# ---------------------------------------------------------------------------
ROW_SPACING = 15.24  # XIAO castellation rows (Seeed ESP32S3.kicad_pcb: 140.881 / 156.121)
PITCH = 2.54
CX = 100.0
USB_END_PIN_Y = -107.62  # D0 / J1.1 and 5V / J2.7 sit 7.62 mm in from the board centre line
IR_PAD_Y = -88.965  # U1 pad row

# header pad k (1..7) of J1 / J2 in the XIAO's own pin order
J1 = {k: (CX + ROW_SPACING / 2, USB_END_PIN_Y + (k - 1) * PITCH) for k in range(1, 8)}  # D0..D6
J2 = {k: (CX - ROW_SPACING / 2, USB_END_PIN_Y + (7 - k) * PITCH) for k in range(1, 8)}  # D7 .. 5V
J1_NETS = {1: "TXD", 2: "RXD", 3: None, 4: "SD", 5: None, 6: None, 7: None}
J2_NETS = {1: None, 2: None, 3: None, 4: None, 5: "V3V3", 6: "GND", 7: None}
# J2.k: k=1 D7 (far end) ... k=5 3V3, k=6 GND, k=7 5V (USB end)

# TFBS4711 (pin 1 at +x with the lenses toward +y, i.e. at 180 degrees)
U1_NETS = {1: "V3V3", 2: "TXD", 3: "RXD", 4: "SD", 5: "VCC1", 6: "GND"}
U1 = {n: (CX + 2.375 - (n - 1) * 0.95, IR_PAD_Y) for n in range(1, 7)}

# 0603 pads (centres, read off the paste layer; each must coincide with a paste flash)
PASSIVES = {
    ("C1", 1): ((101.075, -90.65), "GND"), ("C1", 2): ((102.725, -90.65), "V3V3"),
    ("C2", 1): ((98.575, -92.075), "GND"), ("C2", 2): ((98.575, -90.425), "VCC1"),
    ("R2", 1): ((97.0, -92.525), "V3V3"), ("R2", 2): ((97.0, -90.875), "VCC1"),
    ("R3", 1): ((103.775, -108.7), "TXD"), ("R3", 2): ((105.425, -108.7), "GND"),
    ("R4", 1): ((105.6, -94.825), "GND"), ("R4", 2): ((105.6, -93.175), "SD"),
}

BOM_EXPECT = {
    "U1": "C102624", "C1": "C19702", "C2": "C14663", "R2": "C23182",
    "R3": "C25804", "R4": "C25804",
}
CPL_EXPECT = {  # designator -> (mid x, mid y, rotation)
    "U1": (100.0, -88.97, 180.0), "C1": (101.9, -90.65, 0.0), "C2": (98.58, -91.25, 90.0),
    "R2": (97.0, -91.7, 90.0), "R3": (104.6, -108.7, 0.0), "R4": (105.6, -94.0, 90.0),
}

failures = []


def check(cond, msg):
    if not cond:
        failures.append(msg)
    return cond


def pad_points():
    """-> {(ref, pin): ((x, y), net or None)}"""
    pts = {}
    for k in range(1, 8):
        pts[("J1", k)] = (J1[k], J1_NETS[k])
        pts[("J2", k)] = (J2[k], J2_NETS[k])
    for n in range(1, 7):
        pts[("U1", n)] = (U1[n], U1_NETS[n])
    pts.update(PASSIVES)
    return pts


def run(layers, bom_text, cpl_text, quiet=False):
    """Run every check on in-memory fab data. Returns the list of failures."""
    failures.clear()
    log = (lambda *a: None) if quiet else print

    # ---- outline / window sanity
    x0, x1, y0, y1 = G.edge_bbox(layers["edge"])
    check(abs((x0 + x1) / 2 - CX) < 0.01, f"board not centred on x={CX}: {x0}..{x1}")
    check(G.X0 < x0 and x1 < G.X0 + G.W and G.Y0 < y0 and y1 < G.Y0 + G.H, "outline outside the raster window")
    log(f"outline x {x0:.2f}..{x1:.2f}  y {y0:.2f}..{y1:.2f} ({x1 - x0:.2f} x {y1 - y0:.2f} mm)")

    # ---- plated holes
    holes = {"via": [], "header": []}
    section = None
    for line in layers["pth"].splitlines():
        m = re.match(r"T(\d+)C([\d.]+)", line)
        if m:
            section = float(m.group(2))
            continue
        if re.fullmatch(r"T\d+", line.strip()):
            section = {1: 0.3, 2: 1.0}.get(int(line.strip()[1:]), section)
            continue
        m = re.match(r"X(-?[\d.]+)Y(-?[\d.]+)", line)
        if m and section is not None:
            holes["header" if section >= 0.9 else "via"].append((float(m.group(1)), float(m.group(2))))
    log(f"plated holes: {len(holes['via'])} vias, {len(holes['header'])} header holes")

    # ---- 1. header geometry from the drill file
    hh = sorted(holes["header"])
    if check(len(hh) == 14, f"expected 14 header holes, found {len(hh)}"):
        left = sorted(h for h in hh if h[0] < CX)
        right = sorted(h for h in hh if h[0] > CX)
        check(len(left) == 7 and len(right) == 7, f"header holes not 7+7: {len(left)}+{len(right)}")
        xs_l = {round(h[0], 3) for h in left}
        xs_r = {round(h[0], 3) for h in right}
        check(len(xs_l) == 1 and len(xs_r) == 1, f"header rows not straight: {xs_l} {xs_r}")
        if len(xs_l) == 1 and len(xs_r) == 1:
            spacing = next(iter(xs_r)) - next(iter(xs_l))
            check(abs(spacing - ROW_SPACING) < 0.005, f"row spacing {spacing:.3f}, want {ROW_SPACING}")
        for name, col, ref in (("J1", right, J1), ("J2", left, J2)):
            ys = [h[1] for h in col]
            pitches = {round(b - a, 3) for a, b in zip(ys, ys[1:])}
            check(pitches == {PITCH}, f"{name} pitch {pitches}, want {PITCH}")
        # each expected header pad coincides with a drilled hole
        for k in range(1, 8):
            for name, ref in (("J1", J1), ("J2", J2)):
                ex, ey = ref[k]
                ok = any(math.hypot(ex - hx, ey - hy) < 0.01 for hx, hy in hh)
                check(ok, f"{name}.{k}: no plated hole at ({ex:.3f}, {ey:.3f})")
        log(f"header: rows x {sorted(xs_l | xs_r)}, D0 = J1.1 at y {J1[1][1]:.2f} (USB end), "
            f"3V3 = J2.5 at y {J2[5][1]:.2f}, GND = J2.6, 5V = J2.7 at y {J2[7][1]:.2f}")

    # ---- 2. copper connectivity
    top = G.raster(layers["cu_top"], strict=True)
    bot = G.raster(layers["cu_bot"], strict=True)
    lt, nt = ndimage.label(top)
    lb, nb = ndimage.label(bot)
    log(f"copper islands: {nt} top, {nb} bottom")

    parent = {}

    def find(a):
        parent.setdefault(a, a)
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def union(a, b):
        parent[find(a)] = find(b)

    def island(arr, tag, x, y):
        cx, cy = G.px(x, y)
        i, j = int(round(cy)), int(round(cx))
        v = int(arr[i, j])
        return (tag, v) if v else None

    for v in range(1, nt + 1):
        find(("T", v))
    for v in range(1, nb + 1):
        find(("B", v))
    for hx, hy in holes["via"] + holes["header"]:
        a, b = island(lt, "T", hx, hy), island(lb, "B", hx, hy)
        check(a is not None and b is not None, f"plated hole at ({hx}, {hy}) lacks copper on a layer")
        if a and b:
            union(a, b)

    pts = pad_points()
    # passive pad centres must be real paste flashes
    paste = [(int(a) / 1e6, int(b) / 1e6) for a, b in re.findall(r"X(-?\d+)Y(-?\d+)D03", layers["paste_top"])]
    for (ref, pin), ((x, y), _) in pts.items():
        if ref in ("U1", "C1", "C2", "R2", "R3", "R4"):
            check(any(math.hypot(x - px_, y - py_) < 0.01 for px_, py_ in paste),
                  f"{ref}.{pin}: no paste aperture at ({x:.3f}, {y:.3f})")

    where = {}
    for (ref, pin), ((x, y), net) in pts.items():
        # through-hole pads exist on both layers; SMD only on top
        g = None
        for arr, tag in ((lt, "T"), (lb, "B")):
            isl = island(arr, tag, x, y)
            if isl:
                g = find(isl)
                break
        if not check(g is not None, f"{ref}.{pin} at ({x:.3f}, {y:.3f}): no copper"):
            continue
        where[(ref, pin)] = g
    groups = {}
    for key, g in where.items():
        groups.setdefault(g, []).append(key)

    # intended partition: pads of one net share a group; NC pads are alone; nets differ
    net_group = {}
    for key, g in where.items():
        net = pts[key][1]
        if net is None:
            others = [k for k in groups[g] if k != key]
            check(not others, f"{key[0]}.{key[1]} should be isolated but shares copper with {others}")
        else:
            net_group.setdefault(net, set()).add(g)
    for net, gs in net_group.items():
        check(len(gs) == 1, f"net {net} is split over {len(gs)} copper groups")
    seen = {}
    for net, gs in net_group.items():
        for g in gs:
            check(g not in seen, f"nets {net} and {seen.get(g)} are shorted together")
            seen[g] = net
    for g, members in groups.items():
        nets = {pts[k][1] for k in members if pts[k][1]}
        if len(nets) > 1:
            check(False, f"short between {sorted(nets)}: {members}")

    log("\nnets traced from copper (pad: net):")
    for net in sorted(net_group):
        g = next(iter(net_group[net]))
        log(f"  {net:5} {sorted(f'{r}.{p}' for r, p in groups[g])}")
    log("  isolated: " + ", ".join(f"{r}.{p}" for (r, p), (_, n) in sorted(pts.items()) if n is None))

    # floating copper: every island group must hold a pad or a via
    anchor = set(where.values())
    for hx, hy in holes["via"] + holes["header"]:
        isl = island(lt, "T", hx, hy)
        if isl:
            anchor.add(find(isl))
    floating = [g for g in {find(k) for k in list(parent)} if g not in anchor]
    check(not floating, f"{len(floating)} floating copper island(s) with no pad or hole")
    log(f"floating copper groups: {len(floating)}")

    # ---- 3. BOM / CPL
    rows = list(csv.reader(bom_text.splitlines()))
    check(rows[0] == ["Comment", "Designator", "Footprint", "LCSC Part #"], f"BOM header {rows[0]}")
    bom = {}
    for r in rows[1:]:
        for d in r[1].replace('"', "").split(","):
            bom[d.strip()] = r[3]
    check(bom == BOM_EXPECT, f"BOM mismatch: got {bom}, want {BOM_EXPECT}")
    check(not any(d.startswith("J") for d in bom), "headers must not be in the BOM")
    cpl = {}
    for r in list(csv.reader(cpl_text.splitlines()))[1:]:
        cpl[r[0]] = (float(r[1]), float(r[2]), r[3], float(r[4]))
    check(set(cpl) == set(CPL_EXPECT), f"CPL designators {sorted(cpl)} != {sorted(CPL_EXPECT)} (headers must be excluded)")
    for d, (ex, ey, er) in CPL_EXPECT.items():
        if d in cpl:
            cx_, cy_, side, rot = cpl[d]
            check(side == "T", f"CPL {d} layer {side}")
            check(abs(cx_ - ex) < 0.02 and abs(cy_ - ey) < 0.02, f"CPL {d} at ({cx_}, {cy_}), want ({ex}, {ey})")
            check(abs(rot - er) < 0.01, f"CPL {d} rotation {rot}, want {er}")
    check(cpl.get("U1", (0, 0, "", -1))[3] == 180.0, "CPL U1 rotation must be 180")
    log(f"BOM: {bom}")
    log(f"CPL: {sorted(cpl)}; U1 rotation {cpl.get('U1', ('', '', '', None))[3]}")
    return list(failures)


# ---------------------------------------------------------------------------
def self_test(layers, bom_text, cpl_text):
    """Deliberately broken copies must FAIL; returns True when every one does."""
    import copy

    def swap_x(txt, a, b):
        ia, ib = f"X{round(a * 1e6)}", f"X{round(b * 1e6)}"
        return re.sub(rf"({ia}|{ib})(?=Y)", lambda m: ib if m.group(1) == ia else ia, txt)

    def swap_drill(txt, a, b):
        return re.sub(r"X(107\.62|92\.38)(?=Y)", lambda m: "X92.38" if m.group(1) == "107.62" else "X107.62", txt)

    cases = []
    # 1. J1 holes one pitch off (D0 not at the USB end) in the drill file only
    c = copy.deepcopy(layers)
    c["pth"] = re.sub(r"^X107\.62Y(-?[\d.]+)$", lambda m: f"X107.62Y{float(m.group(1)) + 2.54:g}", c["pth"], flags=re.M)
    cases.append(("J1 holes shifted one pitch in the drill file", c, bom_text, cpl_text))
    # 2. header swapped in drill and in every copper/mask/paste flash
    c = copy.deepcopy(layers)
    c["pth"] = swap_drill(c["pth"], 0, 0)
    for k in ("cu_top", "cu_bot", "mask_top", "mask_bot"):
        c[k] = swap_x(c[k], 107.62, 92.38)
    cases.append(("J1/J2 swapped in drill and pad flashes", c, bom_text, cpl_text))
    # 3. U1 mirrored: pad flashes of pin 1 and pin 6 exchanged on top copper
    c = copy.deepcopy(layers)
    c["cu_top"] = swap_x(c["cu_top"], 102.375, 97.625)
    cases.append(("U1 pin 1 / pin 6 flashes exchanged", c, bom_text, cpl_text))
    # 4. CPL with U1 at 0 degrees, BOM with the old C1 part
    cases.append(("U1 rotation 0 in the CPL", layers, bom_text,
                  cpl_text.replace("U1,100.00,-88.97,T,180.00", "U1,100.00,-88.97,T,0.00")))
    cases.append(("old C1 LCSC number in the BOM", layers, bom_text.replace("C19702", "C19666"), cpl_text))
    cases.append(("header left in the CPL", layers, bom_text, cpl_text + "J1,107.62,-100.00,T,0.00\n"))
    ok = True
    for name, ly, b, p in cases:
        f = run(ly, b, p, quiet=True)
        status = "FAILS as it should" if f else "STILL PASSES (checker is blind to this!)"
        print(f"  self-test: {name}: {status}" + (f"  [{f[0][:90]}]" if f else ""))
        ok = ok and bool(f)
    return ok


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    zpath = Path(args[0]) if args else FAB / "gerbers.zip"
    layers = G.load_zip(zpath)
    bom_text = (zpath.parent / "bom.csv").read_text()
    cpl_text = (zpath.parent / "cpl.csv").read_text()
    if "--self-test" in sys.argv:
        print("breaking copies of the fab data:")
        sys.exit(0 if self_test(layers, bom_text, cpl_text) else 1)
    f = run(layers, bom_text, cpl_text)
    if f:
        print(f"\nFAIL: {len(f)} problem(s)")
        for m in f:
            print("  - " + m)
        sys.exit(1)
    print("\nPASS: gerber connectivity, header geometry, BOM and CPL match the intended design")


if __name__ == "__main__":
    main()
