#!/usr/bin/env python3
"""Silkscreen check against JLCPCB minimums, straight from fab/gerbers.zip.

  * every silkscreen stroke (aperture) is at least 0.15 mm wide
  * text is at least 1.0 mm high (from the KiCad board; exceptions listed below)
  * no silkscreen over an exposed (solder-mask-opening) pad, on either side
  * silkscreen stays at least 0.3 mm from the board outline (IR edge in particular)
  * the JLCJLCJLCJLC order-number placeholder is present on the top silk layer

Run through pcb-env (needs numpy, Pillow, scipy):

    pcb-env/bin/py scripts/silk_check.py [fab/gerbers.zip]
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gerblib as G  # noqa: E402
import numpy as np  # noqa: E402
from scipy import ndimage  # noqa: E402

HERE = Path(__file__).resolve().parent.parent
KICAD_PCB = HERE / "kicad" / "xiao-irda-hat.kicad_pcb"
MIN_STROKE = 0.15
MIN_TEXT_H = 1.0
MIN_EDGE = 0.3
IR_EDGE_Y = -86.10
# Text allowed below MIN_TEXT_H because it cannot fit without touching pads.
SMALL_TEXT_OK = set()

failures = []


def check(cond, msg):
    if not cond:
        failures.append(msg)
    return cond


def main():
    zpath = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "fab" / "gerbers.zip"
    L = G.load_zip(zpath)
    ex0, ex1, ey0, ey1 = G.edge_bbox(L["edge"])
    edge = G.raster(L["edge"])
    dist_mm = ndimage.distance_transform_edt(~edge) * G.RES
    for side, s, m in (("top", "silk_top", "mask_top"), ("bottom", "silk_bot", "mask_bot")):
        txt = L[s]
        widths = sorted({a[1] for a in G.apertures(txt).values()})
        print(f"{side}: silk aperture widths {widths} mm")
        check(all(w >= MIN_STROKE - 1e-9 for w in widths), f"{side} silk has a stroke below {MIN_STROKE} mm: {widths}")
        silk = G.raster(txt)
        mask = G.raster(L[m])
        ov = silk & mask
        lab, n = ndimage.label(ov)
        print(f"{side}: silk over mask openings: {int(ov.sum())} px in {n} blob(s)")
        for sl in ndimage.find_objects(lab):
            print(f"    at x {G.X0 + sl[1].start * G.RES:.2f}..{G.X0 + sl[1].stop * G.RES:.2f} "
                  f"y {G.Y0 + G.H - sl[0].stop * G.RES:.2f}..{G.Y0 + G.H - sl[0].start * G.RES:.2f}")
        check(int(ov.sum()) == 0, f"{side}: silkscreen overlaps exposed pads ({int(ov.sum())} px)")
        ys, xs = np.nonzero(silk)
        if len(xs):
            d = dist_mm[ys, xs].min()
            top_y = G.Y0 + G.H - ys.min() * G.RES
            print(f"{side}: silk min distance to outline {d:.2f} mm; highest silk y {top_y:.2f} "
                  f"({IR_EDGE_Y - top_y:+.2f} to the IR edge)")
            check(d >= MIN_EDGE - 0.005, f"{side}: silk only {d:.2f} mm from the board outline (min {MIN_EDGE})")
            # all silk must be inside the outline
            check(G.X0 + xs.min() * G.RES > ex0 and G.X0 + xs.max() * G.RES < ex1 and top_y < ey1,
                  f"{side}: silk outside the board outline")

    # placeholder: text is stroked, so check the KiCad board for the string and silk for ink under the XIAO
    pcb = KICAD_PCB.read_text() if KICAD_PCB.exists() else ""
    check('"JLCJLCJLCJLC"' in pcb, "JLCJLCJLCJLC placeholder missing from the KiCad board")
    texts = re.findall(r'\(gr_text "([^"]*)"\s*\(at [^)]*\)\s*\(layer "([FB])\.SilkS"\).*?\(size ([\d.]+) ([\d.]+)\)', pcb, re.S)
    small = sorted({(t, l, float(h)) for t, l, w, h in texts if float(h) < MIN_TEXT_H - 1e-9 and t not in SMALL_TEXT_OK})
    print(f"silk texts: {len(texts)}, smallest height {min((float(h) for *_, h in texts), default=0)} mm")
    check(not small, f"silk text below {MIN_TEXT_H} mm: {small}")
    check(any(t == "JLCJLCJLCJLC" and l == "F" for t, l, *_ in texts), "JLCJLCJLCJLC not on F.SilkS")

    if failures:
        print(f"\nFAIL: {len(failures)} problem(s)")
        for f in failures:
            print("  - " + f)
        sys.exit(1)
    print("\nPASS: silkscreen meets stroke, text, pad-clearance and edge-clearance limits")


if __name__ == "__main__":
    main()
