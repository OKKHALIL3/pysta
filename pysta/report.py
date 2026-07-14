"""Human-readable timing reports."""

from __future__ import annotations

from .graph import TimingGraph
from .timing import Result

_KIND_LABEL = {
    "launch": "clk->Q (register launches)",
    "input": "input arrives",
    "net": "wire",
    "cell": "gate delay",
}


def _fmt(x: float | None) -> str:
    if x is None:
        return "  n/a"
    if x == float("inf"):
        return "  inf"
    return f"{x:8.4f}"


def summary(res: Result, graph: TimingGraph) -> str:
    lines = ["=" * 60, "TIMING SUMMARY", "=" * 60]
    lines.append(f"clock period : {_fmt(res.period).strip()} ns"
                 if res.period is not None else "clock period : (none -- pure delay report)")
    lines.append(f"startpoints  : {len(graph.startpoints)}")
    lines.append(f"endpoints    : {len(graph.endpoints)}")
    if res.wns is not None:
        verdict = "MET" if res.wns >= 0 else "VIOLATED"
        lines.append(f"WNS (worst slack) : {res.wns:+.4f} ns   [{verdict}]")
        lines.append(f"TNS (total neg.)  : {res.tns:+.4f} ns")
    for w in res.warnings:
        lines.append(f"warning: {w}")
    return "\n".join(lines)


def critical_path(res: Result, graph: TimingGraph) -> str:
    if not res.critical_path:
        return "(no critical path -- no endpoints)"
    ep = res.critical_endpoint
    lines = ["", "-" * 60, "CRITICAL PATH  (the slowest route in the design)", "-" * 60]
    lines.append(f"{'stage':<22}{'kind':<28}{'delay':>9}{'arrival':>10}")
    for st in res.critical_path:
        label = _KIND_LABEL.get(st.kind, st.kind)
        lines.append(f"{st.node:<22}{label:<28}{st.delay:>9.4f}{st.arrival:>10.4f}")
    slack = res.endpoint_slack.get(ep)
    total = res.critical_path[-1].arrival
    lines.append("-" * 60)
    lines.append(f"data arrival at {ep}: {total:.4f} ns")
    if slack is not None and slack != float("inf"):
        req = res.required.get(ep)
        lines.append(f"required time         : {req:.4f} ns")
        lines.append(f"slack                 : {slack:+.4f} ns  "
                     f"[{'MET' if slack >= 0 else 'VIOLATED'}]")
    return "\n".join(lines)


def endpoint_table(res: Result, graph: TimingGraph, limit: int = 20) -> str:
    if not res.endpoint_slack:
        return ""
    rows = sorted(res.endpoint_slack.items(), key=lambda kv: kv[1])
    lines = ["", "-" * 60, "ENDPOINT SLACK (worst first)", "-" * 60]
    lines.append(f"{'endpoint':<24}{'arrival':>10}{'required':>10}{'slack':>10}")
    for nid, sl in rows[:limit]:
        lines.append(f"{nid:<24}{res.arrival.get(nid, 0.0):>10.4f}"
                     f"{res.required.get(nid, 0.0):>10.4f}{sl:>+10.4f}")
    if len(rows) > limit:
        lines.append(f"... and {len(rows) - limit} more")
    return "\n".join(lines)


def full_report(res: Result, graph: TimingGraph) -> str:
    parts = [summary(res, graph), critical_path(res, graph), endpoint_table(res, graph)]
    return "\n".join(p for p in parts if p)
