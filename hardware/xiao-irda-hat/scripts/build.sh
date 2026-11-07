#!/usr/bin/env bash
# Rebuild the XIAO IrDA hat end to end: tscircuit -> KiCad -> DRC -> netlist
# check -> renders -> JLCPCB package -> STEP.
#
# Runs on the host. All tools come from the pcb-env distrobox through its host
# wrappers (bin/tsci, bin/kicad-cli, bin/kikit, bin/py, bin/pcb):
#
#   PCB_ENV=~/projects/radio/pcb-env hardware/xiao-irda-hat/scripts/build.sh
#
# Outputs: kicad/ (fab-ready KiCad board, project, schematic), fab/ (gerbers.zip,
# bom.csv, cpl.csv), renders/ (PNG), board.step, build/ (scratch, gitignored).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PCB_ENV="${PCB_ENV:-$HOME/projects/radio/pcb-env}"
B="$PCB_ENV/bin"
for t in tsci kicad-cli kikit py pcb; do
  [ -x "$B/$t" ] || { echo "missing $B/$t (set PCB_ENV)"; exit 1; }
done
cd "$HERE"
mkdir -p build kicad fab renders

# KiCad's Python bindings print a harmless assert on every start; hide it.
quiet() { grep -v -E 'property\.h|memory leak' || true; }

echo "== 1. tscircuit build"
"$B/tsci" build --disable-parts-engine --pcb-svgs --schematic-svgs index.circuit.tsx 2>&1 \
  | grep -v -E 'requires_(power|ground)|underspecified|prefix is being used|schematicsheet' | quiet
"$B/tsci" export --disable-parts-engine index.circuit.tsx -f kicad_pcb -o build/export.kicad_pcb 2>&1 | quiet
"$B/tsci" export --disable-parts-engine index.circuit.tsx -f kicad_sch -o build/export.kicad_sch 2>&1 | quiet

echo "== 2. KiCad post-processing (zones, paste, fields, rules, 3D models)"
"$B/py" scripts/kicad_postprocess.py build/export.kicad_pcb build/export.kicad_sch kicad 2>&1 | quiet
rm -f kicad/*.kicad_prl

echo "== 3. DRC"
( cd kicad
  "$B/kicad-cli" pcb drc --severity-all --refill-zones --save-board -o ../build/drc.rpt xiao-irda-hat.kicad_pcb 2>&1 | quiet
  "$B/kicad-cli" pcb drc --severity-all --refill-zones --format json -o ../build/drc.json xiao-irda-hat.kicad_pcb 2>&1 | quiet
)
rm -f kicad/*.kicad_prl
cp build/drc.rpt renders/drc-report.txt
python3 - <<'PY'
import json, sys
d = json.load(open("build/drc.json"))
v = d.get("violations", []) + d.get("unconnected_items", []) + d.get("schematic_parity", [])
err = [x for x in v if x.get("severity") == "error"]
print(f"DRC: {len(err)} errors, {len(v) - len(err)} warnings")
for x in v:
    print(f"  [{x['severity']}] {x['type']}: {x['description']}")
sys.exit(1 if err else 0)
PY

echo "== 4. netlist check"
VERIFY_SKIP_FAB=1 python3 verify_netlist.py

echo "== 5. renders"
S=build/svg
mkdir -p "$S"
K="$B/kicad-cli"
"$K" pcb export svg --mode-single --exclude-drawing-sheet --page-size-mode 2 \
  --layers F.Cu,F.Mask,F.Silkscreen,F.Fab,Edge.Cuts -o "$S/top.svg" kicad/xiao-irda-hat.kicad_pcb 2>&1 | quiet
"$K" pcb export svg --mode-single --exclude-drawing-sheet --page-size-mode 2 --mirror \
  --layers B.Cu,B.Mask,B.Silkscreen,Edge.Cuts -o "$S/bottom.svg" kicad/xiao-irda-hat.kicad_pcb 2>&1 | quiet
"$B/pcb" rsvg-convert -w 1400 -b white -o renders/pcb-top.png "$S/top.svg"
"$B/pcb" rsvg-convert -w 1400 -b white -o renders/pcb-bottom.png "$S/bottom.svg"
"$B/pcb" rsvg-convert -w 1400 -b white -o renders/tscircuit-pcb.png dist/index/pcb.svg
"$B/pcb" rsvg-convert -w 1600 -b white -o renders/schematic.png dist/index/schematic.svg
for side in top bottom; do
  "$K" pcb render --side "$side" --width 1600 --height 1200 --quality high --background opaque \
    -o "renders/3d-$side.png" kicad/xiao-irda-hat.kicad_pcb 2>&1 | quiet || echo "3D render ($side) failed"
done
"$K" pcb render --width 1600 --height 1200 --quality high --background opaque \
  --rotate '-55,0,-150' --zoom 1.1 -o renders/3d-iso.png kicad/xiao-irda-hat.kicad_pcb 2>&1 | quiet || echo "3D iso render failed"

echo "== 6. JLCPCB package (KiKit)"
rm -rf build/fab
"$B/kikit" fab jlcpcb --no-drc --assembly --schematic kicad/xiao-irda-hat.kicad_sch \
  --field LCSC --missingError kicad/xiao-irda-hat.kicad_pcb build/fab 2>&1 | quiet
cp build/fab/gerbers.zip fab/gerbers.zip
cp build/fab/pos.csv fab/cpl.csv
# JLCPCB's BOM template header is "LCSC Part #"; drop the KiCad library prefix.
python3 - build/fab/bom.csv fab/bom.csv <<'PY'
import csv, sys
rows = list(csv.reader(open(sys.argv[1], newline="")))
assert rows[0] == ["Comment", "Designator", "Footprint", "LCSC"], rows[0]
rows[0] = ["Comment", "Designator", "Footprint", "LCSC Part #"]
for r in rows[1:]:
    r[2] = r[2].split(":", 1)[-1]
csv.writer(open(sys.argv[2], "w", newline="")).writerows(rows)
PY

echo "== 6b. fab package checks (gerbers, BOM/CPL, silkscreen)"
"$B/py" scripts/gerber_netcheck.py fab/gerbers.zip
"$B/py" scripts/silk_check.py fab/gerbers.zip
"$B/py" scripts/gerber_netcheck.py --self-test >/dev/null && echo "gerber check self-test: broken copies are rejected"

echo "== 7. STEP"
"$K" pcb export step --force --subst-models -o board.step kicad/xiao-irda-hat.kicad_pcb 2>&1 | quiet | tail -3

echo
ls -l fab renders board.step
echo "build OK"
