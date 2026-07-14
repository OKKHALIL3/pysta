# Validation — cross-checking against OpenSTA

The point of this directory is to prove PySTA is *correct*, not just
self-consistent: feed the same design to PySTA and to
[OpenSTA](https://github.com/parallaxsw/OpenSTA) (the open-source
industry-reference analyzer) and confirm the worst negative slack agrees.

```bash
python validation/run_opensta.py examples/pipe.v \
    --lib examples/tiny.lib --sdc examples/pipe.sdc --top pipe
```

If OpenSTA isn't installed, the harness prints PySTA's number and skips the
comparison (exit 0) — it's wired up and ready, it just needs `sta` on the PATH.

## The full frontend flow this fits into

Real gate-level netlists come out of **synthesis**. The end-to-end path a chip
team runs, and the one to reproduce here for bigger benchmarks, is:

```
RTL (Verilog)
   │  yosys:  read_verilog design.v
   │          synth -flatten
   │          dfflibmap -liberty cells.lib     # map flip-flops
   │          abc -liberty cells.lib           # map logic to real cells
   │          write_verilog design_gate.v
   ▼
gate-level netlist  ──►  PySTA report  ──►  compare WNS  ◄──  OpenSTA
                                    (run_opensta.py)
```

`examples/tiny.lib` is intentionally tiny (a handful of cells), so it's meant
for the hand-written `examples/pipe.v`. To validate on synthesized benchmarks,
point all three tools at a fuller open library (e.g. SkyWater sky130) and a
design synthesized against it — the harness arguments are the same.
