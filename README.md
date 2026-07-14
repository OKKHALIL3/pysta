# PySTA

A static timing analysis (STA) engine for digital circuits, written in Python.

Given a gate-level Verilog netlist, a Liberty (`.lib`) timing library, and a
clock constraint, PySTA builds the timing graph, propagates delays using the
library's NLDM models, checks setup timing at every register and output, and
reports worst/total negative slack and the critical path — the analysis that
determines how fast a design can be clocked.

## Features

- **Liberty parser** with NLDM delay tables (2-D input-slew × output-load).
- **Gate-level Verilog parser** — buses, escaped identifiers, constants, `assign`.
- **SDC constraints** — clock period and input/output delays.
- **Timing engine** — forward arrival + slew propagation, backward required
  times, slack, WNS/TNS, and critical-path extraction.
- **Sequential support** — flip-flop clock-to-Q launch and setup checks.
- **Text reports + CLI**, plus an OpenSTA cross-check harness.

## Usage

```bash
python3 -m pysta report examples/pipe.v --lib examples/tiny.lib --sdc examples/pipe.sdc
```

The report prints the timing summary (WNS/TNS), the critical path with a
per-stage delay breakdown, and per-endpoint slack. The process exits non-zero
when timing is violated, so it can gate a build.

## Tests

```bash
python3 -m pytest
```

## Cross-checking against OpenSTA

`validation/run_opensta.py` runs the same design through PySTA and
[OpenSTA](https://github.com/parallaxsw/OpenSTA) and compares worst negative
slack (it skips cleanly if OpenSTA isn't installed):

```bash
python3 validation/run_opensta.py examples/pipe.v \
    --lib examples/tiny.lib --sdc examples/pipe.sdc --top pipe
```

## Architecture and scope

See [DESIGN.md](DESIGN.md) for the module breakdown, the delay model, and the
current scope. In short: setup-time analysis on a single ideal clock, with
rise/fall collapsed to a worst-case value per stage. Hold checks, multi-clock,
clock-tree modeling, and parasitic wire delay are not yet implemented.
