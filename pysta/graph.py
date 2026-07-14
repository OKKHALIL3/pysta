"""Turn a netlist + library into a timing graph.

The timing graph is the object STA actually walks. Its nodes are pins (and the
chip's boundary ports); its edges are the two ways a signal moves:

  * a **net edge** carries a signal along a wire from the pin driving it to every
    pin listening (delay ~0 in this model), and
  * a **cell edge** is a timing arc *through* a gate, from an input pin to an
    output pin (delay comes from the Liberty NLDM table).

Flip-flops are the trick that keeps this a DAG (no loops): we cut them open.
A flip-flop's **Q** output is treated as a path START (it launches on the clock),
and its **D** input as a path END (it captures on the clock). We never draw an
edge straight through a flop, so feedback loops through registers disappear and
the combinational logic in between is a clean acyclic graph.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .liberty import Library, TimingArc
from .netlist import Netlist


@dataclass
class Node:
    id: str
    kind: str                    # 'in_port' | 'out_port' | 'pin'
    net: str                     # canonical net this node sits on
    inst: str | None = None
    pin: str | None = None
    cell_type: str | None = None
    load_cap: float = 0.0        # total downstream capacitance (drivers only)
    is_startpoint: bool = False
    is_endpoint: bool = False
    is_clock: bool = False
    is_ff_q: bool = False
    is_ff_d: bool = False


@dataclass
class Edge:
    src: str
    dst: str
    kind: str                    # 'net' | 'cell'
    arc: TimingArc | None = None
    inst: str | None = None


@dataclass
class TimingGraph:
    nodes: dict[str, Node] = field(default_factory=dict)
    edges: list[Edge] = field(default_factory=list)
    startpoints: list[str] = field(default_factory=list)
    endpoints: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def build_graph(nl: Netlist, lib: Library) -> TimingGraph:
    # `assign a = b;` makes two net names the same electrical node. Union-find
    # merges them so driver/load bookkeeping sees one net.
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        root = x
        while parent[root] != root:
            root = parent[root]
        while parent[x] != root:
            parent[x], x = root, parent[x]
        return root

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for lhs, rhs in nl.assigns:
        union(lhs, rhs)

    warnings: list[str] = []

    # First pass: which nets are clock nets (they feed a pin marked `clock`)?
    clock_nets: set[str] = set()
    for inst in nl.instances.values():
        cell = lib.cells.get(inst.cell_type)
        if not cell:
            continue
        for pin, netname in inst.conns.items():
            lp = cell.pins.get(pin)
            if lp and lp.is_clock:
                clock_nets.add(find(netname))

    nodes: dict[str, Node] = {}
    net_driver: dict[str, str] = {}
    net_loads: dict[str, list[str]] = {}
    net_load_cap: dict[str, float] = {}

    def add_load(root: str, nid: str, cap: float) -> None:
        net_loads.setdefault(root, []).append(nid)
        net_load_cap[root] = net_load_cap.get(root, 0.0) + cap

    def set_driver(root: str, nid: str) -> None:
        if root in net_driver:
            warnings.append(f"net '{root}' has multiple drivers")
        net_driver[root] = nid

    # Boundary ports.
    for name in nl.inputs:
        root = find(name)
        node = Node(f"port:{name}", "in_port", root, is_clock=(root in clock_nets))
        nodes[node.id] = node
        set_driver(root, node.id)
    for name in nl.outputs:
        root = find(name)
        node = Node(f"port:{name}", "out_port", root)
        nodes[node.id] = node
        add_load(root, node.id, 0.0)

    # Instance pins.
    for inst in nl.instances.values():
        cell = lib.cells.get(inst.cell_type)
        if cell is None:
            warnings.append(f"unknown cell type '{inst.cell_type}' (instance {inst.name})")
        for pin, netname in inst.conns.items():
            root = find(netname)
            nid = f"{inst.name}/{pin}"
            node = Node(nid, "pin", root, inst=inst.name, pin=pin, cell_type=inst.cell_type)
            lp = cell.pins.get(pin) if cell else None
            nodes[nid] = node
            if lp is None:
                continue
            if lp.is_clock:
                node.is_clock = True
                add_load(root, nid, lp.capacitance)
            elif lp.direction == "output":
                set_driver(root, nid)
            else:  # input pin -- a load on its net
                add_load(root, nid, lp.capacitance)

        # Cut the flip-flop open: Q starts a path, D ends one.
        if cell and cell.is_sequential:
            if cell.ff_q and f"{inst.name}/{cell.ff_q}" in nodes:
                q = nodes[f"{inst.name}/{cell.ff_q}"]
                q.is_ff_q = True
                q.is_startpoint = True
            dname = (cell.ff_next_state or "").strip().strip('"')
            if dname and f"{inst.name}/{dname}" in nodes:
                d = nodes[f"{inst.name}/{dname}"]
                d.is_ff_d = True
                d.is_endpoint = True

    # Push each net's total load capacitance onto its driver.
    for root, driver in net_driver.items():
        nodes[driver].load_cap = net_load_cap.get(root, 0.0)

    # Boundary startpoints / endpoints (clock port is neither -- it's ideal).
    for name in nl.inputs:
        node = nodes[f"port:{name}"]
        if not node.is_clock:
            node.is_startpoint = True
    for name in nl.outputs:
        nodes[f"port:{name}"].is_endpoint = True

    # Edges.
    edges: list[Edge] = []

    # Net edges (skip the clock network -- the clock is modelled as ideal).
    for root, driver in net_driver.items():
        if root in clock_nets:
            continue
        for load in net_loads.get(root, []):
            edges.append(Edge(driver, load, "net"))

    # Cell edges: combinational arcs only. A flop's CLK->Q arc is handled
    # analytically in the engine, not as a graph edge.
    for inst in nl.instances.values():
        cell = lib.cells.get(inst.cell_type)
        if not cell:
            continue
        for outpin in cell.outputs():
            dst = f"{inst.name}/{outpin.name}"
            if dst not in nodes:
                continue
            if cell.is_sequential and outpin.name == cell.ff_q:
                continue
            for arc in outpin.arcs:
                if arc.timing_type != "combinational":
                    continue
                src = f"{inst.name}/{arc.related_pin}"
                if src in nodes:
                    edges.append(Edge(src, dst, "cell", arc=arc, inst=inst.name))

    g = TimingGraph(nodes=nodes, edges=edges, warnings=warnings)
    g.startpoints = [nid for nid, n in nodes.items() if n.is_startpoint]
    g.endpoints = [nid for nid, n in nodes.items() if n.is_endpoint]
    return g
