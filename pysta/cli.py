"""Command-line entry point.

    python -m pysta report design.v --lib cells.lib --sdc design.sdc
"""

from __future__ import annotations

import argparse
import sys

from . import report
from .graph import build_graph
from .liberty import load_liberty
from .netlist import load_verilog
from .sdc import Sdc, load_sdc
from .timing import analyze


def _build(args) -> tuple:
    lib = load_liberty(args.lib)
    nl = load_verilog(args.netlist, top=args.top)
    sdc = load_sdc(args.sdc) if args.sdc else Sdc()
    graph = build_graph(nl, lib)
    res = analyze(graph, lib, sdc)
    return graph, res


def cmd_report(args) -> int:
    graph, res = _build(args)
    print(report.full_report(res, graph))
    if res.wns is not None and res.wns < 0:
        return 2  # non-zero exit signals a timing violation
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="pysta", description="A static timing analyzer.")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("report", help="analyze a design and print a timing report")
    r.add_argument("netlist", help="gate-level Verilog netlist (.v)")
    r.add_argument("--lib", required=True, help="Liberty timing library (.lib)")
    r.add_argument("--sdc", help="constraints file (.sdc)")
    r.add_argument("--top", help="top module name (default: first module)")
    r.set_defaults(func=cmd_report)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
