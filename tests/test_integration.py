import os

from conftest import EXAMPLES
from pysta import report
from pysta.graph import build_graph
from pysta.liberty import load_liberty
from pysta.netlist import load_verilog
from pysta.sdc import load_sdc
from pysta.timing import analyze


def _run(netlist, lib, sdc=None):
    library = load_liberty(os.path.join(EXAMPLES, lib))
    nl = load_verilog(os.path.join(EXAMPLES, netlist))
    constraints = load_sdc(os.path.join(EXAMPLES, sdc)) if sdc else None
    from pysta.sdc import Sdc
    graph = build_graph(nl, library)
    res = analyze(graph, library, constraints or Sdc())
    return graph, res


def test_pipe_end_to_end_meets_timing():
    graph, res = _run("pipe.v", "tiny.lib", "pipe.sdc")
    assert not res.warnings                      # netlist wires up cleanly
    assert res.period == 2.0
    assert res.wns is not None
    assert res.wns > 0                           # 2 ns is comfortably enough
    # Every endpoint got a finite, real slack.
    for nid, sl in res.endpoint_slack.items():
        assert sl == sl and sl != float("inf")   # not NaN, not inf
    assert res.critical_endpoint in graph.endpoints
    assert len(res.critical_path) >= 2


def test_report_renders():
    graph, res = _run("pipe.v", "tiny.lib", "pipe.sdc")
    text = report.full_report(res, graph)
    assert "TIMING SUMMARY" in text
    assert "CRITICAL PATH" in text
    assert "WNS" in text


def test_realistic_arrivals_are_ordered():
    # Real NLDM delays: a register launch should take longer than a single INV.
    graph, res = _run("pipe.v", "tiny.lib", "pipe.sdc")
    assert res.arrival["r0/Q"] > 0
    assert res.arrival["g0/Y"] > res.arrival["r0/Q"]   # NAND adds delay
    assert res.arrival["g1/Y"] > res.arrival["g0/Y"]   # INV adds delay
