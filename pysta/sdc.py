"""Parse the timing constraints (a small subset of SDC).

SDC (Synopsys Design Constraints) is the Tcl-ish file that tells the analyzer
the *goal*: how fast the clock runs and when signals arrive/are needed at the
chip's boundary. We support the three commands that matter for setup analysis:

    create_clock -name clk -period 10.0 [get_ports clk]
    set_input_delay  2.0 -clock clk [get_ports a]
    set_output_delay 3.0 -clock clk [get_ports y]

Everything else is ignored (safely), which is fine for this scope.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Sdc:
    period: float | None = None
    clock_port: str | None = None
    clock_name: str | None = None
    input_delay: dict[str, float] = field(default_factory=dict)
    output_delay: dict[str, float] = field(default_factory=dict)
    # Slews we assume for boundary/clock signals, since NLDM delay depends on
    # input slew and a constraints file rarely pins these down.
    default_input_slew: float = 0.05
    default_clock_slew: float = 0.05


def _clean(tokens: list[str]) -> list[str]:
    """Drop Tcl wrappers like get_ports/get_clocks and stray braces/brackets."""
    out: list[str] = []
    for tok in tokens:
        t = tok.strip("[]{}")
        if t in ("get_ports", "get_clocks", "get_pins", "all_inputs", "all_outputs", ""):
            continue
        out.append(t)
    return out


def parse_sdc(text: str) -> Sdc:
    sdc = Sdc()
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        # Normalise brackets/braces to spaces so tokens split cleanly.
        for ch in "[]{}":
            line = line.replace(ch, " ")
        parts = line.split()
        if not parts:
            continue
        cmd, args = parts[0], parts[1:]

        if cmd == "create_clock":
            _parse_create_clock(sdc, args)
        elif cmd == "set_input_delay":
            _parse_io_delay(args, sdc.input_delay)
        elif cmd == "set_output_delay":
            _parse_io_delay(args, sdc.output_delay)
        elif cmd == "set_input_transition":
            val, ports = _value_and_ports(args)
            if val is not None:
                sdc.default_input_slew = val
    return sdc


def _parse_create_clock(sdc: Sdc, args: list[str]) -> None:
    i = 0
    ports: list[str] = []
    while i < len(args):
        a = args[i]
        if a == "-period":
            sdc.period = float(args[i + 1])
            i += 2
        elif a == "-name":
            sdc.clock_name = args[i + 1]
            i += 2
        elif a in ("get_ports", "get_clocks"):
            i += 1
        else:
            ports.append(a)
            i += 1
    ports = [p for p in ports if p not in ("get_ports", "get_clocks")]
    if ports:
        sdc.clock_port = ports[0]
    if sdc.clock_name is None and sdc.clock_port:
        sdc.clock_name = sdc.clock_port


def _value_and_ports(args: list[str]) -> tuple[float | None, list[str]]:
    val: float | None = None
    ports: list[str] = []
    i = 0
    while i < len(args):
        a = args[i]
        if a in ("-clock", "-clk", "-min", "-max", "-rise", "-fall", "-add_delay"):
            # -clock/-clk take a value; the rest are bare flags.
            if a in ("-clock", "-clk"):
                i += 2
            else:
                i += 1
            continue
        try:
            val = float(a)
        except ValueError:
            ports.append(a)
        i += 1
    return val, _clean(ports)


def _parse_io_delay(args: list[str], target: dict[str, float]) -> None:
    val, ports = _value_and_ports(args)
    if val is None:
        return
    for p in ports:
        target[p] = val


def load_sdc(path: str) -> Sdc:
    with open(path, "r") as fh:
        return parse_sdc(fh.read())
