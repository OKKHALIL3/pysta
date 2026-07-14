# PySTA — Design

A static timing analysis engine for digital circuits.

## Overview

Given a gate-level Verilog netlist, a Liberty timing library, and a clock
constraint, PySTA reports how fast the design can run: it propagates delays
through the timing graph, checks setup timing at every flip-flop and output, and
reports worst negative slack (WNS), total negative slack (TNS), and the critical
path.

## Pipeline

1. **Parse** — Liberty library, gate-level Verilog netlist, and SDC constraints.
2. **Build the timing graph** — nodes are pins and boundary ports; edges are net
   connections and cell timing arcs. Flip-flops are split so that a register's Q
   output starts a path and its D input ends one, which keeps the graph acyclic.
3. **Forward pass** — propagate arrival time and slew in topological order:
   `arrival(out) = max over inputs of (arrival(in) + arc_delay)`.
4. **Backward pass** — propagate required time from the endpoints
   (`clock_period − setup` at registers; `clock_period − output_delay` at ports).
5. **Slack** — `required − arrival` at each endpoint; report WNS/TNS and trace
   the worst path.

## Delay model

Cell delay comes from Liberty **NLDM** tables: a 2-D grid indexed by input slew
and output load, bilinearly interpolated (`pysta/nldm.py`). Slew is propagated
alongside arrival time, because a stage's delay depends on how sharply its input
switches. Each stage uses the worst case of the rise and fall tables.

## Modules

- `pysta/liberty.py` — Liberty parser → cells, pins, timing arcs, NLDM tables.
- `pysta/nldm.py` — NLDM lookup-table interpolation.
- `pysta/netlist.py` — structural Verilog parser → in-memory netlist.
- `pysta/sdc.py` — clock and I/O-delay constraints.
- `pysta/graph.py` — timing-graph construction.
- `pysta/timing.py` — forward/backward passes, slack, WNS/TNS, critical path.
- `pysta/report.py` — timing and critical-path reports.
- `pysta/cli.py` — `python -m pysta report` / `export`.
- `pysta/export_graph.py` — emit a resolved timing graph for the C++ core.
- `cpp/sta_core.cpp` — the graph solver in C++ (see below).
- `validation/` — OpenSTA cross-check harness.
- `tests/` — unit and end-to-end tests.

## C++ core

The forward/backward graph propagation is the hot path — on a real design the
timing graph has millions of nodes. It is also implemented in C++
(`cpp/sta_core.cpp`) as a self-contained solver over a "resolved timing graph":
Python does the parsing and NLDM delay lookup and emits each node's launch
arrival, each edge's delay, and each endpoint's required time
(`pysta/export_graph.py` / `python -m pysta export`); the C++ core runs the
topological longest-path, backward required-time, slack, and critical-path
computation. The two implementations are cross-checked in
`tests/test_cpp_core.py`.

## Scope and limitations

Implemented:
- Combinational and sequential (register-to-register) paths.
- Setup checks on a single ideal clock.
- Real Liberty NLDM delays with slew propagation.

Not yet implemented:
- Hold checks; rise and fall are collapsed to a single worst-case value per stage.
- Multiple clocks, and clock-tree / propagated-clock modeling.
- Multi-corner analysis and timing exceptions (false / multicycle paths).
- Interconnect (wire) delay — nets are treated as lumped / zero-delay; parasitic
  wire delay is a planned extension.

## Validation

`validation/run_opensta.py` cross-checks worst negative slack against OpenSTA on
the same netlist, library, and constraints, reporting the difference against a
tolerance.
