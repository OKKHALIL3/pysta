"""Parse a structural (gate-level) Verilog netlist.

A gate-level netlist is what you get *after* synthesis: no `always` blocks or
arithmetic, just concrete library cells wired together by nets. For example:

    module pipe (clk, a, b, y);
        input clk, a, b;
        output y;
        wire q0, d2;
        DFF   r0 (.CK(clk), .D(a),  .Q(q0));
        NAND2 g0 (.A(q0),  .B(b),  .Y(d2));
        DFF   r1 (.CK(clk), .D(d2), .Q(y));
    endmodule

We support the realistic subset a synthesis tool (e.g. Yosys) emits: bus
declarations (`input [3:0] a;`) expanded to scalar bits, escaped identifiers
(`\a[0] `), constant nets (`1'b0`), named port connections, and `assign`
aliases.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Instance:
    name: str
    cell_type: str
    conns: dict[str, str] = field(default_factory=dict)  # pin name -> net name


@dataclass
class Netlist:
    module: str = ""
    inputs: list[str] = field(default_factory=list)
    outputs: list[str] = field(default_factory=list)
    wires: list[str] = field(default_factory=list)
    instances: dict[str, Instance] = field(default_factory=dict)
    assigns: list[tuple[str, str]] = field(default_factory=list)  # (lhs, rhs)

    @property
    def ports(self) -> list[str]:
        return self.inputs + self.outputs


def _tokenize(text: str) -> list[str]:
    toks: list[str] = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c in " \t\r\n":
            i += 1
            continue
        if text[i : i + 2] == "//":
            end = text.find("\n", i)
            i = end if end != -1 else n
            continue
        if text[i : i + 2] == "/*":
            end = text.find("*/", i)
            i = end + 2 if end != -1 else n
            continue
        if c == "`":  # `timescale and friends -- skip the whole line
            end = text.find("\n", i)
            i = end if end != -1 else n
            continue
        if c == "\\":  # escaped identifier: runs until whitespace
            j = i + 1
            while j < n and text[j] not in " \t\r\n":
                j += 1
            toks.append(text[i + 1 : j])  # store without the leading backslash
            i = j
            continue
        if c in "(){}[];:,.=":
            toks.append(c)
            i += 1
            continue
        j = i
        while j < n and (text[j].isalnum() or text[j] in "_$'"):
            j += 1
        if j > i:
            toks.append(text[i:j])
            i = j
        else:
            toks.append(c)
            i += 1
    return toks


class _TokenStream:
    def __init__(self, toks: list[str]):
        self.t = toks
        self.i = 0

    def peek(self, k: int = 0) -> str:
        j = self.i + k
        return self.t[j] if j < len(self.t) else ""

    def next(self) -> str:
        tok = self.peek()
        self.i += 1
        return tok

    def eat(self, val: str) -> None:
        if self.peek() == val:
            self.next()


def _expand_range(names: list[str], msb: int, lsb: int) -> list[str]:
    step = -1 if msb >= lsb else 1
    bits = list(range(msb, lsb + step, step))
    out: list[str] = []
    for name in names:
        out.extend(f"{name}[{b}]" for b in bits)
    return out


def _read_net(ts: _TokenStream) -> str:
    """Read one net expression: `id`, `id[3]`, or a constant like `1'b0`."""
    tok = ts.next()
    if ts.peek() == "[":  # bit-select -> fold into the net name
        ts.next()
        idx = ts.next()
        ts.eat("]")
        return f"{tok}[{idx}]"
    return tok


def _decl_names(ts: _TokenStream) -> tuple[list[str], int | None, int | None]:
    """Parse `[msb:lsb] a, b, c` after an input/output/wire keyword."""
    msb = lsb = None
    if ts.peek() == "[":
        ts.next()
        msb = int(ts.next())
        ts.eat(":")
        lsb = int(ts.next())
        ts.eat("]")
    names: list[str] = []
    while ts.peek() not in (";", "", ")"):
        tok = ts.next()
        if tok == ",":
            continue
        names.append(tok)
    return names, msb, lsb


def parse_verilog(text: str, top: str | None = None) -> Netlist:
    ts = _TokenStream(_tokenize(text))
    nl = Netlist()

    # Skip to the requested module (or the first one).
    while ts.peek():
        if ts.next() == "module":
            name = ts.next()
            if top is None or name == top:
                nl.module = name
                break
    # Skip the header port list up to the first ';'.
    while ts.peek() and ts.peek() != ";":
        ts.next()
    ts.eat(";")

    while ts.peek() and ts.peek() != "endmodule":
        kw = ts.peek()
        if kw in ("input", "output", "inout", "wire", "reg"):
            ts.next()
            names, msb, lsb = _decl_names(ts)
            ts.eat(";")
            if msb is not None:
                names = _expand_range(names, msb, lsb)
            if kw == "input":
                nl.inputs.extend(names)
            elif kw == "output":
                nl.outputs.extend(names)
            elif kw in ("wire", "reg"):
                nl.wires.extend(names)
        elif kw == "assign":
            ts.next()
            lhs = _read_net(ts)
            ts.eat("=")
            rhs = _read_net(ts)
            ts.eat(";")
            nl.assigns.append((lhs, rhs))
        else:
            # An instance:  CELLTYPE instname ( .pin(net), ... ) ;
            cell_type = ts.next()
            inst_name = ts.next()
            inst = Instance(name=inst_name, cell_type=cell_type)
            ts.eat("(")
            while ts.peek() and ts.peek() != ")":
                if ts.peek() == ".":
                    ts.next()
                    pin = ts.next()
                    ts.eat("(")
                    if ts.peek() != ")":
                        inst.conns[pin] = _read_net(ts)
                    ts.eat(")")
                elif ts.peek() == ",":
                    ts.next()
                else:
                    ts.next()  # tolerate positional/oddities
            ts.eat(")")
            ts.eat(";")
            nl.instances[inst_name] = inst
    return nl


def load_verilog(path: str, top: str | None = None) -> Netlist:
    with open(path, "r") as fh:
        return parse_verilog(fh.read(), top=top)
