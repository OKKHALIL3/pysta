"""Export an analyzed design as a 'resolved timing graph' for the C++ core.

The C++ solver (`cpp/sta_core.cpp`) implements the performance-critical graph
propagation, but not the parsing or delay-model lookup. So Python does the
front-end work -- parse, build the graph, resolve every edge's delay from the
NLDM tables -- and emits a flat description the C++ core can solve directly:

    nodes N
    <idx> <name> <start 0|1> <launch>
    edges M
    <src> <dst> <delay>
    endpoints K
    <idx> <required>

A node is a "start" (its arrival is given, not computed) when it has no incoming
edges -- a primary input, a flip-flop's Q output, or a constant.
"""

from __future__ import annotations

from .graph import TimingGraph
from .timing import Result, _arc_delay


def _edge_delay(edge, nodes, slew, default_slew: float) -> float:
    if edge.kind == "net":
        return 0.0
    return _arc_delay(edge.arc, slew.get(edge.src, default_slew), nodes[edge.dst].load_cap)


def to_resolved_graph(graph: TimingGraph, res: Result, default_slew: float = 0.05) -> str:
    nodes = graph.nodes
    ids = list(nodes.keys())
    index = {nid: i for i, nid in enumerate(ids)}

    indeg = {nid: 0 for nid in nodes}
    for e in graph.edges:
        indeg[e.dst] += 1

    lines = [f"nodes {len(ids)}"]
    for nid in ids:
        start = 1 if indeg[nid] == 0 else 0
        launch = res.arrival.get(nid, 0.0) if start else 0.0
        lines.append(f"{index[nid]} {nid} {start} {launch:.6f}")

    lines.append(f"edges {len(graph.edges)}")
    for e in graph.edges:
        d = _edge_delay(e, nodes, res.slew, default_slew)
        lines.append(f"{index[e.src]} {index[e.dst]} {d:.6f}")

    endpoints = [
        (nid, res.required[nid])
        for nid in graph.endpoints
        if res.required.get(nid, float("inf")) != float("inf")
    ]
    lines.append(f"endpoints {len(endpoints)}")
    for nid, req in endpoints:
        lines.append(f"{index[nid]} {req:.6f}")

    return "\n".join(lines) + "\n"
