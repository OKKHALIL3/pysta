"""Parse a Liberty (.lib) timing library into an in-memory model.

A Liberty file describes every cell a chip can be built from: its pins, how much
each input pin loads the wire driving it, and -- the part STA lives on -- its
*timing arcs* (how long a signal takes to travel from each input to each output,
as NLDM tables).

The file format is a nested "group" syntax:

    library (name) {
        cell (INV) {
            pin (Y) {
                direction : output;
                timing () {
                    related_pin : "A";
                    cell_rise (tmpl) { index_1(...); index_2(...); values(...); }
                }
            }
        }
    }

We parse in two stages: a generic tokenizer + group parser turns the text into a
tree of ``Group`` objects, then an interpreter walks that tree into the typed
``Library`` model the rest of PySTA uses.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .nldm import LookupTable


# ---------------------------------------------------------------------------
# Typed model
# ---------------------------------------------------------------------------
@dataclass
class TimingArc:
    """A timing relationship ending on the pin that owns this arc.

    For a combinational arc under an OUTPUT pin, ``related_pin`` is the input
    that drives it. For a setup/hold constraint under a flip-flop DATA pin,
    ``related_pin`` is the clock.
    """

    related_pin: str = ""
    timing_sense: str = ""          # positive_unate / negative_unate / non_unate
    timing_type: str = "combinational"  # combinational / rising_edge / setup_rising ...
    cell_rise: LookupTable | None = None
    cell_fall: LookupTable | None = None
    rise_transition: LookupTable | None = None
    fall_transition: LookupTable | None = None
    rise_constraint: LookupTable | None = None
    fall_constraint: LookupTable | None = None

    @property
    def is_setup(self) -> bool:
        return self.timing_type.startswith("setup")

    @property
    def is_edge(self) -> bool:
        return self.timing_type in ("rising_edge", "falling_edge")


@dataclass
class LibPin:
    name: str
    direction: str = ""             # input / output
    capacitance: float = 0.0        # how much this input pin loads its net
    is_clock: bool = False
    function: str | None = None
    arcs: list[TimingArc] = field(default_factory=list)


@dataclass
class LibCell:
    name: str
    area: float = 0.0
    pins: dict[str, LibPin] = field(default_factory=dict)
    is_sequential: bool = False
    ff_clocked_on: str | None = None
    ff_next_state: str | None = None
    ff_q: str | None = None         # the output pin that presents the stored bit

    def outputs(self) -> list[LibPin]:
        return [p for p in self.pins.values() if p.direction == "output"]

    def inputs(self) -> list[LibPin]:
        return [p for p in self.pins.values() if p.direction == "input"]


@dataclass
class Library:
    name: str = ""
    time_unit: str = "1ns"
    cap_unit: str = "1pf"
    cells: dict[str, LibCell] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Generic tokenizer + group parser
# ---------------------------------------------------------------------------
class Group:
    """A raw ``name (args) { ... }`` block before interpretation."""

    def __init__(self, gtype: str, args: list[str]):
        self.type = gtype
        self.args = args
        self.simple: dict[str, str] = {}            # name : value ;
        self.complex: dict[str, list[list[str]]] = {}  # name(a, b, ...);  (repeatable)
        self.groups: list[Group] = []

    def find(self, gtype: str) -> list[Group]:
        return [g for g in self.groups if g.type == gtype]


def _tokenize(text: str) -> list[tuple[str, str]]:
    tokens: list[tuple[str, str]] = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c in " \t\r\n":
            i += 1
            continue
        if c == "\\" and i + 1 < n and text[i + 1] == "\n":  # line continuation
            i += 2
            continue
        if c == "/" and text[i : i + 2] == "/*":
            end = text.find("*/", i + 2)
            i = end + 2 if end != -1 else n
            continue
        if c == "/" and text[i : i + 2] == "//":
            end = text.find("\n", i)
            i = end if end != -1 else n
            continue
        if c == '"':
            j = i + 1
            buf = []
            while j < n and text[j] != '"':
                buf.append(text[j])
                j += 1
            tokens.append(("str", "".join(buf)))
            i = j + 1
            continue
        if c in "(){};:,":
            tokens.append(("punc", c))
            i += 1
            continue
        j = i
        while j < n and text[j] not in " \t\r\n(){};:,\"" and text[j : j + 2] not in ("/*", "//"):
            j += 1
        tokens.append(("word", text[i:j]))
        i = j
    return tokens


class _Parser:
    def __init__(self, tokens: list[tuple[str, str]]):
        self.t = tokens
        self.i = 0

    def peek(self) -> tuple[str, str]:
        return self.t[self.i] if self.i < len(self.t) else ("eof", "")

    def next(self) -> tuple[str, str]:
        tok = self.peek()
        self.i += 1
        return tok

    def _args(self) -> list[str]:
        args: list[str] = []
        while True:
            kind, val = self.peek()
            if kind == "eof" or val == ")":
                self.next()
                break
            if val == ",":
                self.next()
                continue
            args.append(self.next()[1])
        return args

    def parse_group(self) -> Group:
        name = self.next()[1]
        assert self.next()[1] == "(", f"expected ( after {name}"
        args = self._args()
        grp = Group(name, args)
        assert self.next()[1] == "{", f"expected {{ for group {name}"
        while self.peek()[1] != "}" and self.peek()[0] != "eof":
            self._stmt(grp)
        self.next()  # consume }
        return grp

    def _stmt(self, grp: Group) -> None:
        name = self.next()[1]
        kind, val = self.peek()
        if val == ":":  # simple attribute:  name : value ;
            self.next()
            parts = []
            while self.peek()[1] != ";" and self.peek()[0] != "eof":
                parts.append(self.next()[1])
            if self.peek()[1] == ";":
                self.next()
            grp.simple[name] = " ".join(parts)
        elif val == "(":  # complex attribute or a nested group
            self.next()
            args = self._args()
            if self.peek()[1] == "{":
                self.next()
                sub = Group(name, args)
                while self.peek()[1] != "}" and self.peek()[0] != "eof":
                    self._stmt(sub)
                self.next()  # consume }
                grp.groups.append(sub)
            else:
                if self.peek()[1] == ";":
                    self.next()
                grp.complex.setdefault(name, []).append(args)
        else:  # a bare word statement -- skip to the next ;
            while self.peek()[1] not in (";", "}") and self.peek()[0] != "eof":
                self.next()
            if self.peek()[1] == ";":
                self.next()


# ---------------------------------------------------------------------------
# Interpretation: Group tree -> typed Library
# ---------------------------------------------------------------------------
def _floats(text: str) -> list[float]:
    return [float(x) for x in text.replace(",", " ").split() if x]


def _table(grp: Group) -> LookupTable:
    t = LookupTable()
    if "index_1" in grp.complex:
        t.index_1 = _floats(" ".join(grp.complex["index_1"][0]))
    if "index_2" in grp.complex:
        t.index_2 = _floats(" ".join(grp.complex["index_2"][0]))
    if "values" in grp.complex:
        t.values = [_floats(row) for row in grp.complex["values"][0]]
    else:
        t.values = [[0.0]]
    return t


_TABLE_KINDS = {
    "cell_rise", "cell_fall", "rise_transition", "fall_transition",
    "rise_constraint", "fall_constraint",
}


def _arc(tg: Group) -> TimingArc:
    arc = TimingArc(
        related_pin=tg.simple.get("related_pin", "").strip(),
        timing_sense=tg.simple.get("timing_sense", ""),
        timing_type=tg.simple.get("timing_type", "combinational"),
    )
    for sub in tg.groups:
        if sub.type in _TABLE_KINDS:
            setattr(arc, sub.type, _table(sub))
    return arc


def _cell(cg: Group) -> LibCell:
    cell = LibCell(name=cg.args[0] if cg.args else "?")
    if "area" in cg.simple:
        try:
            cell.area = float(cg.simple["area"])
        except ValueError:
            pass

    ff = cg.find("ff")
    ff_vars: list[str] = []
    if ff:
        cell.is_sequential = True
        cell.ff_clocked_on = ff[0].simple.get("clocked_on")
        cell.ff_next_state = ff[0].simple.get("next_state")
        ff_vars = ff[0].args

    for pg in cg.find("pin"):
        pin = LibPin(
            name=pg.args[0] if pg.args else "?",
            direction=pg.simple.get("direction", ""),
            is_clock=(pg.simple.get("clock", "false") == "true"),
            function=pg.simple.get("function"),
        )
        if "capacitance" in pg.simple:
            try:
                pin.capacitance = float(pg.simple["capacitance"])
            except ValueError:
                pass
        for tg in pg.find("timing"):
            pin.arcs.append(_arc(tg))
        cell.pins[pin.name] = pin

    # Which output pin presents the stored bit? The one whose function names the
    # flip-flop's internal state variable (IQ), so we know where CLK->Q starts.
    if cell.is_sequential and ff_vars:
        iq = ff_vars[0]
        for p in cell.pins.values():
            if p.direction == "output" and p.function and iq == p.function.strip().strip('"'):
                cell.ff_q = p.name
        if cell.ff_q is None:  # fall back to the sole output
            outs = cell.outputs()
            if len(outs) == 1:
                cell.ff_q = outs[0].name
    return cell


def parse_liberty(text: str) -> Library:
    """Parse Liberty source text into a :class:`Library`."""
    parser = _Parser(_tokenize(text))
    root = parser.parse_group()  # the top-level `library (...) { ... }`
    lib = Library(name=root.args[0] if root.args else "")
    lib.time_unit = root.simple.get("time_unit", lib.time_unit)
    for cg in root.find("cell"):
        cell = _cell(cg)
        lib.cells[cell.name] = cell
    return lib


def load_liberty(path: str) -> Library:
    with open(path, "r") as fh:
        return parse_liberty(fh.read())
