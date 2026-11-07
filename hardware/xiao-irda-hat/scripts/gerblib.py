"""Minimal Gerber (RS-274X, KiCad flavour) rasterizer shared by the fab checks.

Reads layers straight out of fab/gerbers.zip, so the checks look at exactly what
JLCPCB receives and not at what the tscircuit/KiCad exporters believe they wrote.
Needs numpy, Pillow and scipy: run it through pcb-env/bin/py.

Coordinates are gerber millimetres (KiCad y is negated: gerber = (x, -y_kicad)).
"""
import math
import re
import zipfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

RES = 0.01  # mm per pixel
X0, Y0, W, H = 90.0, -112.0, 20.0, 27.0  # raster window: x 90..110, y -112..-85

LAYERS = {
    "cu_top": "CuTop.gtl", "cu_bot": "CuBottom.gbl",
    "mask_top": "MaskTop.gts", "mask_bot": "MaskBottom.gbs",
    "silk_top": "SilkTop.gto", "silk_bot": "SilkBottom.gbo",
    "paste_top": "PasteTop.gtp", "edge": "EdgeCuts.gm1", "pth": "PTH.drl",
}


def load_zip(path):
    """-> {layer key: text}"""
    out = {}
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        for key, suffix in LAYERS.items():
            hits = [n for n in names if n.endswith("-" + suffix)]
            if len(hits) != 1:
                raise SystemExit(f"gerbers.zip: expected exactly one *-{suffix}, found {hits}")
            out[key] = z.read(hits[0]).decode()
    return out


def px(x, y):
    return ((x - X0) / RES, (Y0 + H - y) / RES)


def apertures(txt):
    aps = {}
    for m in re.finditer(r"%ADD(\d+)([A-Za-z]+),([\d.]+)(?:X([\d.]+))?[^*]*\*%", txt):
        aps[int(m.group(1))] = (m.group(2), float(m.group(3)), float(m.group(4) or m.group(3)))
    return aps


def raster(txt, strict=False):
    """Rasterize a gerber layer. strict: reject features this reader can't draw faithfully."""
    if strict and "%LPC" in txt:
        raise SystemExit("clear polarity in a copper layer is not supported by this checker")
    img = Image.new("1", (int(W / RES), int(H / RES)), 0)
    dr = ImageDraw.Draw(img)
    aps = apertures(txt)
    cur = None
    x = y = 0.0
    region = False
    poly = []
    mode = 1  # G01 linear, G02 cw arc, G03 ccw arc

    def seg(p0, p1, w):
        a, b = px(*p0), px(*p1)
        dr.line([a, b], fill=1, width=max(1, int(round(w / RES))))
        r = w / 2 / RES
        for p in (a, b):
            dr.ellipse([p[0] - r, p[1] - r, p[0] + r, p[1] + r], fill=1)

    for cmd in re.findall(r"[^*%]+\*", txt):
        cmd = cmd[:-1].strip()
        if re.match(r"(G04|AD|AM|FS|MO|TF|TA|TO|TD|LP|G75|M02)", cmd):
            continue
        if cmd == "G36":
            region, poly = True, []
            continue
        if cmd == "G37":
            if len(poly) > 2:
                dr.polygon([px(*p) for p in poly], fill=1)
            region = False
            continue
        m = re.fullmatch(r"(?:G0?1)?D(\d+)", cmd)
        if m and int(m.group(1)) >= 10:
            cur = int(m.group(1))
            continue
        m = re.fullmatch(r"(?:G0?([123]))?(?:X(-?\d+))?(?:Y(-?\d+))?(?:I(-?\d+))?(?:J(-?\d+))?D0?([123])", cmd)
        if not m:
            if strict and cmd not in ("G01", "G02", "G03"):
                raise SystemExit(f"unparsed gerber command {cmd!r}")
            if cmd in ("G01", "G02", "G03"):
                mode = int(cmd[-1])
            continue
        if m.group(1):
            mode = int(m.group(1))
        nx = int(m.group(2)) / 1e6 if m.group(2) else x
        ny = int(m.group(3)) / 1e6 if m.group(3) else y
        op = int(m.group(6))
        pts = [(nx, ny)]
        if op == 1 and mode in (2, 3):
            if strict:
                raise SystemExit("arc in a copper layer is not supported by this checker")
            i = int(m.group(4) or 0) / 1e6
            j = int(m.group(5) or 0) / 1e6
            cx, cy = x + i, y + j
            a0 = math.atan2(y - cy, x - cx)
            a1 = math.atan2(ny - cy, nx - cx)
            if mode == 3 and a1 <= a0:
                a1 += 2 * math.pi
            if mode == 2 and a1 >= a0:
                a1 -= 2 * math.pi
            if abs(a1 - a0) < 1e-9:  # full circle
                a1 = a0 + (2 * math.pi if mode == 3 else -2 * math.pi)
            r = math.hypot(x - cx, y - cy)
            n = max(8, int(abs(a1 - a0) * r / 0.02))
            pts = [(cx + r * math.cos(a0 + (a1 - a0) * k / n), cy + r * math.sin(a0 + (a1 - a0) * k / n))
                   for k in range(1, n + 1)]
        if region:
            if op == 2:
                if len(poly) > 2:
                    dr.polygon([px(*p) for p in poly], fill=1)
                poly = [(nx, ny)]
            else:
                poly.extend(pts)
        else:
            ap = aps.get(cur)
            if op == 3:
                if ap is None:
                    raise SystemExit(f"flash with undefined aperture D{cur}")
                t, a, b = ap
                cx, cy = px(nx, ny)
                if t == "C":
                    r = a / 2 / RES
                    dr.ellipse([cx - r, cy - r, cx + r, cy + r], fill=1)
                elif t == "R":
                    dr.rectangle([cx - a / 2 / RES, cy - b / 2 / RES, cx + a / 2 / RES, cy + b / 2 / RES], fill=1)
                elif t == "O":
                    dr.rounded_rectangle([cx - a / 2 / RES, cy - b / 2 / RES, cx + a / 2 / RES, cy + b / 2 / RES],
                                         radius=min(a, b) / 2 / RES, fill=1)
                else:
                    raise SystemExit(f"unsupported aperture type {t} (macro pads) in a layer that must be flashed")
            elif op == 1 and ap:
                p = (x, y)
                for q in pts:
                    seg(p, q, ap[1])
                    p = q
        x, y = nx, ny
    return np.array(img, dtype=bool)


def edge_bbox(txt):
    xs = [int(a) / 1e6 for a in re.findall(r"^X(-?\d+)Y", txt, re.M)]
    ys = [int(a) / 1e6 for a in re.findall(r"^X-?\d+Y(-?\d+)D", txt, re.M)]
    return min(xs), max(xs), min(ys), max(ys)
