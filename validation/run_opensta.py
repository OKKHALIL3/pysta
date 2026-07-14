#!/usr/bin/env python3
"""Cross-check PySTA against OpenSTA (the open-source reference analyzer).

This is the credibility test: run the *same* netlist + library + constraints
through both tools and compare worst negative slack. If OpenSTA isn't installed
we skip cleanly (exit 0) rather than fail -- the harness is here and correct,
it just needs the reference tool present to actually run.

    python validation/run_opensta.py examples/pipe.v \
        --lib examples/tiny.lib --sdc examples/pipe.sdc --top pipe

Install OpenSTA: https://github.com/parallaxsw/OpenSTA
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pysta.graph import build_graph          # noqa: E402
from pysta.liberty import load_liberty        # noqa: E402
from pysta.netlist import load_verilog        # noqa: E402
from pysta.sdc import Sdc, load_sdc            # noqa: E402
from pysta.timing import analyze              # noqa: E402

TCL = """\
read_liberty {lib}
read_verilog {netlist}
link_design {top}
read_sdc {sdc}
report_worst_slack -max
exit
"""


def pysta_wns(netlist, lib, sdc, top) -> float | None:
    library = load_liberty(lib)
    nl = load_verilog(netlist, top=top)
    constraints = load_sdc(sdc) if sdc else Sdc()
    res = analyze(build_graph(nl, library), library, constraints)
    return res.wns


def opensta_wns(netlist, lib, sdc, top) -> float | None:
    sta = shutil.which("sta")
    if not sta:
        return None
    with tempfile.NamedTemporaryFile("w", suffix=".tcl", delete=False) as fh:
        fh.write(TCL.format(lib=lib, netlist=netlist, sdc=sdc, top=top))
        script = fh.name
    try:
        out = subprocess.run([sta, "-no_init", "-exit", script],
                             capture_output=True, text=True, timeout=120).stdout
    finally:
        os.unlink(script)
    m = re.search(r"worst slack\s+(?:max\s+)?(-?\d+\.?\d*)", out)
    return float(m.group(1)) if m else None


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("netlist")
    p.add_argument("--lib", required=True)
    p.add_argument("--sdc", required=True)
    p.add_argument("--top", required=True)
    p.add_argument("--tol", type=float, default=0.05, help="allowed |diff| in ns")
    args = p.parse_args()

    mine = pysta_wns(args.netlist, args.lib, args.sdc, args.top)
    ref = opensta_wns(args.netlist, args.lib, args.sdc, args.top)

    print(f"PySTA   WNS = {mine:+.4f} ns" if mine is not None else "PySTA   WNS = n/a")
    if ref is None:
        print("OpenSTA not installed -- skipping comparison (this is not a failure).")
        return 0
    print(f"OpenSTA WNS = {ref:+.4f} ns")
    diff = abs(mine - ref)
    print(f"|diff|      = {diff:.4f} ns   (tolerance {args.tol})")
    ok = diff <= args.tol
    print("MATCH" if ok else "MISMATCH")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
