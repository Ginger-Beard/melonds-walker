#!/usr/bin/env python3
"""Pin-by-pin netlist check for the XIAO IrDA hat.

Compares the intended net table below (written by hand from the TFBS4711
datasheet, the XIAO ESP32S3 pin map and firmware/src/config.h) against:

  1. tscircuit's logical netlist   dist/index/circuit.json
  2. the fab board's pad nets      kicad/xiao-irda-hat.kicad_pcb
  3. (standalone only) scripts/gerber_netcheck.py and scripts/silk_check.py on
     fab/gerbers.zip, via pcb-env/bin/py: copper traced from the gerbers, header
     geometry, BOM/CPL, silkscreen. build.sh runs those after packaging.

Every pin of every part must match, no part may be missing or extra, and the
firmware's default GPIOs must land on the header pins the table says. It also
checks the TFBS4711 land pattern (pad count, size, 0.95 mm pitch, pin 1 side)
and that its lenses sit 0..0.3 mm inside the IR edge, opposite the USB end. Exits
non-zero on any mismatch. Standard library only:

    python3 verify_netlist.py
"""
import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CIRCUIT_JSON = HERE / "dist" / "index" / "circuit.json"
KICAD_PCB = HERE / "kicad" / "xiao-irda-hat.kicad_pcb"
CONFIG_H = HERE.parent.parent / "firmware" / "src" / "config.h"

NC = "NC"  # pin intentionally not connected

# ---------------------------------------------------------------------------
# Intended netlist: every pin of every part.
# ---------------------------------------------------------------------------
INTENDED = {
    # Vishay TFBS4711 (datasheet 82633, pin description table)
    "U1": {
        "1": "V3V3",  # VCC2 / IRED anode, straight to 3V3 (no R1 at 3.3 V)
        "2": "TXD",  # TXD, active high
        "3": "RXD",  # RXD, active low, push-pull
        "4": "SD",  # shutdown, active high
        "5": "VCC1",  # receiver supply, through R2 (47 R) with C2 (100 nF)
        "6": "GND",
    },
    "C1": {"1": "GND", "2": "V3V3"},  # 10 uF at VCC2 / IRED anode
    "C2": {"1": "GND", "2": "VCC1"},  # 100 nF at VCC1
    "R2": {"1": "V3V3", "2": "VCC1"},  # 47 R supply filter
    "R3": {"1": "TXD", "2": "GND"},  # 10 k TXD pull-down
    "R4": {"1": "GND", "2": "SD"},  # 10 k SD pull-down
    # XIAO pins 1..7 (D0..D6)
    "J1": {"1": "TXD", "2": "RXD", "3": NC, "4": "SD", "5": NC, "6": NC, "7": NC},
    # XIAO pins 8..14 (D7, D8, D9, D10, 3V3, GND, 5V)
    "J2": {"1": NC, "2": NC, "3": NC, "4": NC, "5": "V3V3", "6": "GND", "7": NC},
}

# XIAO ESP32S3 header pin -> (label, GPIO), Seeed wiki pin map.
XIAO_PINS = {
    1: ("D0", 1), 2: ("D1", 2), 3: ("D2", 3), 4: ("D3", 4), 5: ("D4", 5),
    6: ("D5", 6), 7: ("D6", 43), 8: ("D7", 44), 9: ("D8", 7), 10: ("D9", 8),
    11: ("D10", 9), 12: ("3V3", None), 13: ("GND", None), 14: ("5V", None),
}


def header_ref(xiao_pin):
    """XIAO pin number -> (designator, pin) on this board."""
    return ("J1", str(xiao_pin)) if xiao_pin <= 7 else ("J2", str(xiao_pin - 7))


failures = []


def check(cond, msg):
    if not cond:
        failures.append(msg)
    return cond


# ---------------------------------------------------------------------------
# 0. firmware defaults vs the table
# ---------------------------------------------------------------------------
def firmware_defaults():
    text = CONFIG_H.read_text()
    out = {}
    for name in ("IR_PIN_TX", "IR_PIN_RX", "IR_PIN_SD"):
        m = re.search(rf"#define\s+{name}\s+(-?\d+)", text)
        out[name] = int(m.group(1)) if m else None
    return out


fw = firmware_defaults()
gpio_to_xiao = {g: p for p, (_, g) in XIAO_PINS.items() if g is not None}
for macro, net in (("IR_PIN_TX", "TXD"), ("IR_PIN_RX", "RXD"), ("IR_PIN_SD", "SD")):
    g = fw.get(macro)
    if not check(g in gpio_to_xiao, f"firmware {macro}={g} is not a XIAO header GPIO"):
        continue
    ref, pin = header_ref(gpio_to_xiao[g])
    check(
        INTENDED[ref][pin] == net,
        f"firmware {macro}=GPIO{g} is XIAO pin {gpio_to_xiao[g]} ({ref}.{pin}), "
        f"but the table puts {INTENDED[ref][pin]} there, not {net}",
    )
check(INTENDED[header_ref(12)[0]][header_ref(12)[1]] == "V3V3", "XIAO pin 12 (3V3) must carry V3V3")
check(INTENDED[header_ref(13)[0]][header_ref(13)[1]] == "GND", "XIAO pin 13 (GND) must carry GND")
check(INTENDED[header_ref(14)[0]][header_ref(14)[1]] == NC, "XIAO pin 14 (5V) must stay unconnected")


# ---------------------------------------------------------------------------
# 1. tscircuit circuit JSON (logical connectivity)
# ---------------------------------------------------------------------------
def netlist_from_circuit_json(path):
    elems = json.loads(path.read_text())
    comps = {e["source_component_id"]: e["name"] for e in elems if e["type"] == "source_component"}
    ports = {}
    for e in elems:
        if e["type"] != "source_port":
            continue
        ref = comps.get(e.get("source_component_id"))
        if ref is None:
            continue
        num = None
        for h in [e.get("name", "")] + list(e.get("port_hints") or []):
            m = re.fullmatch(r"(?:pin)?(\d+)", str(h))
            if m:
                num = m.group(1)
                break
        if num is None and e.get("pin_number") is not None:
            num = str(e["pin_number"])
        ports[e["source_port_id"]] = (ref, num)
    nets = {e["source_net_id"]: e["name"] for e in elems if e["type"] == "source_net"}

    parent = {}

    def find(a):
        parent.setdefault(a, a)
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def union(a, b):
        parent[find(a)] = find(b)

    in_trace = set()
    for e in elems:
        if e["type"] != "source_trace":
            continue
        ids = list(e.get("connected_source_port_ids") or []) + list(e.get("connected_source_net_ids") or [])
        in_trace.update(ids)
        for a, b in zip(ids, ids[1:]):
            union(a, b)

    group_names = {}
    for nid, name in nets.items():
        group_names.setdefault(find(nid), set()).add(name)

    result = {}
    for pid, (ref, num) in ports.items():
        names = group_names.get(find(pid), set())
        connected = pid in in_trace
        if len(names) > 1:
            result.setdefault(ref, {})[num] = "MERGED(" + "+".join(sorted(names)) + ")"
        elif names:
            result.setdefault(ref, {})[num] = next(iter(names))
        else:
            result.setdefault(ref, {})[num] = "UNNAMED" if connected else NC
    return result


# ---------------------------------------------------------------------------
# 2. KiCad board pad nets (what gets fabricated)
# ---------------------------------------------------------------------------
def sexp(text):
    tokens = re.findall(r'\(|\)|"(?:\\.|[^"\\])*"|[^\s()]+', text)
    stack, cur = [], []
    for t in tokens:
        if t == "(":
            stack.append(cur)
            cur = []
        elif t == ")":
            done, cur = cur, stack.pop()
            cur.append(done)
        else:
            cur.append(t[1:-1] if t.startswith('"') else t)
    return cur[0]


def netlist_from_kicad(path):
    root = sexp(path.read_text())
    net_names = {n[1]: n[2] for n in root if isinstance(n, list) and n and n[0] == "net" and len(n) >= 3}
    result = {}
    for fp in root:
        if not (isinstance(fp, list) and fp and fp[0] == "footprint"):
            continue
        ref = None
        for item in fp:
            if isinstance(item, list) and item[:2] == ["property", "Reference"]:
                ref = item[2]
        if ref is None:
            continue
        for item in fp:
            if not (isinstance(item, list) and item and item[0] == "pad"):
                continue
            num = item[1]
            if num == "":
                continue
            net = NC
            for sub in item:
                if isinstance(sub, list) and sub and sub[0] == "net":
                    # KiCad <= 9: (net 5 "NAME"); KiCad 10 may write (net "NAME")
                    net = sub[2] if len(sub) >= 3 else net_names.get(sub[1], sub[1])
                    net = net or NC
            prev = result.setdefault(ref, {}).get(num)
            check(prev in (None, net), f"KiCad {ref}.{num}: pads with the same number on different nets")
            result[ref][num] = net
    return result


def compare(label, actual):
    print(f"\n{label}")
    print(f"  {'pin':8} {'intended':10} {'actual':10}")
    ok = True
    for ref in sorted(set(INTENDED) | set(actual)):
        if ref not in INTENDED:
            ok = check(False, f"{label}: unexpected part {ref}") and ok
            continue
        if ref not in actual:
            ok = check(False, f"{label}: part {ref} missing") and ok
            continue
        for pin in sorted(set(INTENDED[ref]) | set(actual[ref]), key=lambda p: int(p) if p.isdigit() else 999):
            want = INTENDED[ref].get(pin, "<no such pin>")
            got = actual[ref].get(pin, "<missing>")
            mark = "ok" if want == got else "MISMATCH"
            print(f"  {ref + '.' + pin:8} {want:10} {got:10} {mark}")
            if want != got:
                ok = check(False, f"{label}: {ref}.{pin} intended {want}, got {got}") and ok
    return ok


# ---------------------------------------------------------------------------
# 3. TFBS4711 land pattern and optical face on the fab board
# ---------------------------------------------------------------------------
# Vishay 82633 Fig. 4 (side view): 6 pads, 0.95 mm pitch, 0.64 x 1.27 mm.
# Fig. 3: lens tips 3.0 mm in front of the back face; pads extend 0.4 mm behind
# it, so the lens tips are 3.0 - 0.4 + 1.27 / 2 = 2.765 mm from the pad centre.
LENS_FROM_PAD_CENTRE = 2.765


def check_tfbs4711(path):
    import math

    root = sexp(path.read_text())
    ys = []
    for g in root:
        if isinstance(g, list) and g and g[0] in ("gr_line", "gr_arc", "gr_rect", "gr_poly"):
            if any(isinstance(x, list) and x[:2] == ["layer", "Edge.Cuts"] for x in g):
                for x in g:
                    if isinstance(x, list) and x and x[0] in ("start", "end", "mid"):
                        ys.append(float(x[2]))
    edge_ir = min(ys)  # KiCad y grows toward the USB end; the IR edge is the top (min y)
    edge_usb = max(ys)
    for fp in root:
        if not (isinstance(fp, list) and fp and fp[0] == "footprint"):
            continue
        if not any(isinstance(i, list) and i[:3] == ["property", "Reference", "U1"] for i in fp):
            continue
        at = next(i for i in fp if isinstance(i, list) and i and i[0] == "at")
        fx, fy = float(at[1]), float(at[2])
        rot = float(at[3]) if len(at) > 3 else 0.0
        t = math.radians(rot)
        pads = {}
        for i in fp:
            if isinstance(i, list) and i and i[0] == "pad" and i[1]:
                pa = next(x for x in i if isinstance(x, list) and x and x[0] == "at")
                sz = next(x for x in i if isinstance(x, list) and x and x[0] == "size")
                lx, ly = float(pa[1]), float(pa[2])
                # KiCad: y down, positive rotation is counter-clockwise on screen
                gx = fx + lx * math.cos(t) + ly * math.sin(t)
                gy = fy - lx * math.sin(t) + ly * math.cos(t)
                pads[i[1]] = (gx, gy, float(sz[1]), float(sz[2]))
        print(f"\nTFBS4711 land pattern on the fab board (U1 at rotation {rot:g})")
        check(sorted(pads) == ["1", "2", "3", "4", "5", "6"], f"U1 pads {sorted(pads)}")
        for n in sorted(pads):
            gx, gy, w, h = pads[n]
            print(f"  pad {n}: x {gx - 100:+.3f} mm, size {w:.2f} x {h:.2f} mm")
            check(abs(w - 0.64) < 1e-3 and abs(h - 1.27) < 1e-3, f"U1 pad {n} size {w} x {h}, want 0.64 x 1.27")
        xs = [pads[str(n)][0] for n in range(1, 7)]
        pitches = [round(xs[k] - xs[k + 1], 4) for k in range(5)]
        check(all(abs(p - 0.95) < 1e-3 for p in pitches), f"U1 pitch {pitches}, want 0.95 (pin 1 at +x)")
        row_y = sum(p[1] for p in pads.values()) / 6
        check(all(abs(p[1] - row_y) < 1e-3 for p in pads.values()), "U1 pads not in one row")
        lens = row_y - LENS_FROM_PAD_CENTRE  # lenses face the IR edge (smaller KiCad y)
        gap = lens - edge_ir
        print(f"  pitch {pitches}; lens tips {gap:.3f} mm inside the IR edge; "
              f"pads {row_y - 0.635 - edge_ir:.2f} mm from it")
        check(0.0 <= gap <= 0.3, f"U1 lens tips {gap:.3f} mm from the IR edge, want 0..0.3 mm inside")
        check(edge_usb - row_y > 20, "U1 is not at the end opposite the USB-C end")
        return
    check(False, "U1 not found on the KiCad board")


for label, path, fn in (
    ("tscircuit circuit.json", CIRCUIT_JSON, netlist_from_circuit_json),
    ("KiCad board (fab source)", KICAD_PCB, netlist_from_kicad),
):
    if check(path.exists(), f"{path} not found (run scripts/build.sh first)"):
        compare(f"{label}: {path.relative_to(HERE)}", fn(path))

if KICAD_PCB.exists():
    check_tfbs4711(KICAD_PCB)

print(
    f"\nfirmware defaults: TX=GPIO{fw.get('IR_PIN_TX')} RX=GPIO{fw.get('IR_PIN_RX')} "
    f"SD=GPIO{fw.get('IR_PIN_SD')} (from {CONFIG_H.relative_to(HERE.parent.parent)})"
)
# ---------------------------------------------------------------------------
# 4. fab package: gerber connectivity, BOM/CPL, silkscreen (independent of the exporters)
# ---------------------------------------------------------------------------
# These need numpy/Pillow/scipy, so they run through pcb-env/bin/py. build.sh runs
# them itself after packaging (VERIFY_SKIP_FAB=1), since the fab files do not exist yet
# when this script runs mid-build.
if not os.environ.get("VERIFY_SKIP_FAB"):
    import subprocess

    py = Path(os.environ.get("PCB_ENV", Path.home() / "projects" / "radio" / "pcb-env")) / "bin" / "py"
    if check(py.exists(), f"{py} not found (set PCB_ENV) - cannot run the gerber checks"):
        for script in ("gerber_netcheck.py", "silk_check.py"):
            r = subprocess.run([str(py), str(HERE / "scripts" / script), str(HERE / "fab" / "gerbers.zip")],
                               capture_output=True, text=True)
            print(f"\n{script}: {'ok' if r.returncode == 0 else 'FAILED'}")
            if r.returncode:
                print(r.stdout[-1500:] + r.stderr[-500:])
            check(r.returncode == 0, f"scripts/{script} failed")

if failures:
    print(f"\nFAIL: {len(failures)} problem(s)")
    for f in failures:
        print("  - " + f)
    sys.exit(1)
pins = sum(len(v) for v in INTENDED.values())
print(f"\nPASS: {pins} pins on {len(INTENDED)} parts match in both netlists; firmware pins agree; U1 land pattern and IR edge OK")
