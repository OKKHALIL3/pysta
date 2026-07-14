"""The STA engine: the actual timing analysis.

Given a timing graph, the library, and the clock constraint, we do three things:

  1. FORWARD pass -- push "arrival time" through the graph in dependency order.
     A gate's output can't settle until its slowest input has, plus the gate's
     own delay:  arrival(out) = max over inputs of (arrival(in) + arc_delay).

  2. BACKWARD pass -- pull "required time" back from the endpoints: the latest a
     signal is *allowed* to arrive and still be captured in time. For a flop's
     data pin that's (clock_period - setup_time); for an output it's the clock
     period minus whatever the outside world needs.

  3. SLACK = required - arrival, at every endpoint. Positive slack = meets
     timing. Negative = too slow. The worst slack (WNS) and the sum of the
     negative ones (TNS) summarise the whole design, and the single worst path
     is the "critical path".

Simplification (documented in DESIGN.md): we track one worst-case value per pin
rather than separate rise/fall numbers -- arc delay is max(cell_rise, cell_fall).
Everything else (real NLDM tables, slew propagation, setup checks) is faithful.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .graph import Edge, Node, TimingGraph
from .liberty import Library, TimingArc
from .nldm import lookup


class CombinationalLoopError(Exception):
    """Raised when the logic graph has a cycle no flip-flop breaks."""


# ---------------------------------------------------------------------------
# Delay helpers (worst-case of rise/fall)
# ---------------------------------------------------------------------------
def _arc_delay(arc: TimingArc, in_slew: float, load: float) -> float:
    dr = lookup(arc.cell_rise, in_slew, load) if arc.cell_rise else 0.0
    df = lookup(arc.cell_fall, in_slew, load) if arc.cell_fall else 0.0
    return max(dr, df)


def _arc_slew(arc: TimingArc, in_slew: float, load: float) -> float:
    sr = lookup(arc.rise_transition, in_slew, load) if arc.rise_transition else in_slew
    sf = lookup(arc.fall_transition, in_slew, load) if arc.fall_transition else in_slew
    return max(sr, sf)


def _setup(arc: TimingArc, data_slew: float, clk_slew: float) -> float:
    cr = lookup(arc.rise_constraint, data_slew, clk_slew) if arc.rise_constraint else 0.0
    cf = lookup(arc.fall_constraint, data_slew, clk_slew) if arc.fall_constraint else 0.0
    return max(cr, cf)


def _port_name(nid: str) -> str:
    return nid[5:] if nid.startswith("port:") else nid


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------
@dataclass
class PathStage:
    node: str
    delay: float          # incremental delay arriving at this node
    arrival: float
    kind: str             # 'launch' | 'input' | 'net' | 'cell'
    detail: str = ""


@dataclass
class Result:
    arrival: dict[str, float] = field(default_factory=dict)
    slew: dict[str, float] = field(default_factory=dict)
    required: dict[str, float] = field(default_factory=dict)
    slack: dict[str, float] = field(default_factory=dict)
    endpoint_slack: dict[str, float] = field(default_factory=dict)
    wns: float | None = None
    tns: float | None = None
    critical_path: list[PathStage] = field(default_factory=list)
    critical_endpoint: str | None = None
    period: float | None = None
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------
def analyze(graph: TimingGraph, lib: Library, sdc) -> Result:
    nodes = graph.nodes
    incoming: dict[str, list[Edge]] = {nid: [] for nid in nodes}
    outgoing: dict[str, list[Edge]] = {nid: [] for nid in nodes}
    indeg: dict[str, int] = {nid: 0 for nid in nodes}
    for e in graph.edges:
        outgoing[e.src].append(e)
        incoming[e.dst].append(e)
        indeg[e.dst] += 1

    order = _topo_order(nodes, outgoing, indeg)

    period = sdc.period
    default_slew = sdc.default_input_slew
    clk_slew = sdc.default_clock_slew

    arrival: dict[str, float] = {}
    slew: dict[str, float] = {}
    crit_pred: dict[str, tuple[str, Edge, float] | None] = {}

    # ---- FORWARD: arrival times ----
    for u in order:
        node = nodes[u]
        inc = incoming[u]

        if node.is_ff_q:  # launched by the clock edge (ideal clock arrives at 0)
            cell = lib.cells[node.cell_type]
            d, s = _clk_to_q(cell, node.pin, node.load_cap, clk_slew)
            arrival[u], slew[u], crit_pred[u] = d, s, None
            continue

        if not inc:  # a startpoint input, or a constant/unconnected pin
            if node.is_startpoint and node.kind == "in_port":
                arrival[u] = sdc.input_delay.get(_port_name(u), 0.0)
            else:
                arrival[u] = 0.0
            slew[u] = default_slew
            crit_pred[u] = None
            continue

        best = None  # (arrival, slew, pred, edge, delay)
        for e in inc:
            a_src = arrival.get(e.src, 0.0)
            s_src = slew.get(e.src, default_slew)
            if e.kind == "net":
                d, s, a = 0.0, s_src, a_src
            else:
                load = node.load_cap
                d = _arc_delay(e.arc, s_src, load)
                s = _arc_slew(e.arc, s_src, load)
                a = a_src + d
            if best is None or a > best[0]:
                best = (a, s, e.src, e, d)
        arrival[u], slew[u] = best[0], best[1]
        crit_pred[u] = (best[2], best[3], best[4])

    # ---- BACKWARD: required times ----
    def edge_delay(e: Edge) -> float:
        if e.kind == "net":
            return 0.0
        return _arc_delay(e.arc, slew.get(e.src, default_slew), nodes[e.dst].load_cap)

    INF = float("inf")
    required: dict[str, float] = {}

    for u in order:  # seed endpoints
        node = nodes[u]
        if not node.is_endpoint:
            continue
        if period is None:
            required[u] = INF
        elif node.is_ff_d:
            cell = lib.cells[node.cell_type]
            setup = _ff_setup(cell, node.pin, slew.get(u, default_slew), clk_slew)
            required[u] = period - setup                 # capture edge at +period
        else:  # output port
            required[u] = period - sdc.output_delay.get(_port_name(u), 0.0)

    for u in reversed(order):
        best = required.get(u, INF) if nodes[u].is_endpoint else INF
        for e in outgoing[u]:
            best = min(best, required.get(e.dst, INF) - edge_delay(e))
        required[u] = best

    # ---- SLACK ----
    slack = {u: required.get(u, INF) - arrival.get(u, 0.0) for u in nodes}
    endpoint_slack = {u: slack[u] for u in nodes if nodes[u].is_endpoint}

    res = Result(
        arrival=arrival, slew=slew, required=required, slack=slack,
        endpoint_slack=endpoint_slack, period=period, warnings=list(graph.warnings),
    )
    if endpoint_slack and period is not None:
        res.wns = min(endpoint_slack.values())
        res.tns = sum(min(0.0, s) for s in endpoint_slack.values())

    # ---- CRITICAL PATH ----
    ep = _worst_endpoint(graph.endpoints, endpoint_slack, arrival, period)
    if ep is not None:
        res.critical_endpoint = ep
        res.critical_path = _trace(ep, crit_pred, nodes, arrival)
    return res


def _trace(ep: str, crit_pred, nodes, arrival) -> list[PathStage]:
    """Walk the 'slowest predecessor' breadcrumbs from the endpoint back to a
    startpoint, recording the delay contributed at each hop."""
    chain: list[tuple[str, str]] = []  # (node, edge_kind arriving here)
    node, seen = ep, set()
    while node is not None and node not in seen:
        seen.add(node)
        cp = crit_pred.get(node)
        if cp is None:
            kind = "launch" if nodes[node].is_ff_q else "input"
            chain.append((node, kind))
            break
        chain.append((node, cp[1].kind))
        node = cp[0]
    chain.reverse()

    stages: list[PathStage] = []
    for idx, (nid, kind) in enumerate(chain):
        a = arrival.get(nid, 0.0)
        delay = a if idx == 0 else a - arrival.get(chain[idx - 1][0], 0.0)
        stages.append(PathStage(node=nid, delay=delay, arrival=a, kind=kind))
    return stages


def _worst_endpoint(endpoints, endpoint_slack, arrival, period):
    if not endpoints:
        return None
    if endpoint_slack and period is not None:
        return min(endpoint_slack, key=lambda k: endpoint_slack[k])
    return max(endpoints, key=lambda k: arrival.get(k, 0.0))


def _topo_order(nodes, outgoing, indeg) -> list[str]:
    ready = [nid for nid in nodes if indeg[nid] == 0]
    indeg = dict(indeg)
    order: list[str] = []
    while ready:
        u = ready.pop()
        order.append(u)
        for e in outgoing[u]:
            indeg[e.dst] -= 1
            if indeg[e.dst] == 0:
                ready.append(e.dst)
    if len(order) != len(nodes):
        stuck = [nid for nid in nodes if nid not in set(order)]
        raise CombinationalLoopError(
            f"combinational loop involving {len(stuck)} node(s), e.g. {stuck[:5]}"
        )
    return order


def _clk_to_q(cell, qpin: str, load: float, clk_slew: float) -> tuple[float, float]:
    for arc in cell.pins[qpin].arcs:
        if arc.is_edge:
            return _arc_delay(arc, clk_slew, load), _arc_slew(arc, clk_slew, load)
    return 0.0, clk_slew


def _ff_setup(cell, dpin: str, data_slew: float, clk_slew: float) -> float:
    for arc in cell.pins[dpin].arcs:
        if arc.is_setup:
            return _setup(arc, data_slew, clk_slew)
    return 0.0
