import os

import pytest

from conftest import FIXTURES
from pysta.graph import build_graph
from pysta.liberty import load_liberty, parse_liberty
from pysta.netlist import load_verilog, parse_verilog
from pysta.sdc import Sdc
from pysta.timing import CombinationalLoopError, analyze


@pytest.fixture(scope="module")
def unit_lib():
    return load_liberty(os.path.join(FIXTURES, "unit.lib"))


@pytest.fixture()
def seq(unit_lib):
    nl = load_verilog(os.path.join(FIXTURES, "seq.v"))
    return build_graph(nl, unit_lib), unit_lib


# With unit.lib every delay is constant, so arrivals are exact:
#   CK->Q = 0.30, AND2 = 0.25, INV = 0.10, setup = 0.05.
def test_forward_arrivals_are_exact(seq):
    graph, lib = seq
    res = analyze(graph, lib, Sdc(period=1.0))
    assert res.arrival["r0/Q"] == pytest.approx(0.30)
    assert res.arrival["g0/Y"] == pytest.approx(0.55)   # 0.30 + 0.25
    assert res.arrival["g1/Y"] == pytest.approx(0.65)   # 0.55 + 0.10
    assert res.arrival["r1/D"] == pytest.approx(0.65)   # net delay 0


def test_setup_slack_and_wns(seq):
    graph, lib = seq
    res = analyze(graph, lib, Sdc(period=1.0))
    # reg-to-reg: required = period - setup = 0.95; slack = 0.95 - 0.65 = 0.30
    assert res.endpoint_slack["r1/D"] == pytest.approx(0.30)
    # input-to-reg: a arrives at 0; slack = 0.95 - 0 = 0.95
    assert res.endpoint_slack["r0/D"] == pytest.approx(0.95)
    # reg-to-output: y arrives at 0.30; required = period = 1.0; slack = 0.70
    assert res.endpoint_slack["port:y"] == pytest.approx(0.70)
    assert res.wns == pytest.approx(0.30)
    assert res.critical_endpoint == "r1/D"


def test_critical_path_walks_reg_to_reg(seq):
    graph, lib = seq
    res = analyze(graph, lib, Sdc(period=1.0))
    nodes = [st.node for st in res.critical_path]
    assert nodes[0] == "r0/Q"          # launched by the register
    assert nodes[-1] == "r1/D"         # captured at the next register
    assert "g0/Y" in nodes and "g1/Y" in nodes
    assert res.critical_path[0].kind == "launch"


def test_tighter_clock_violates(seq):
    graph, lib = seq
    res = analyze(graph, lib, Sdc(period=0.5))
    # required = 0.45, arrival 0.65 -> slack -0.20, timing VIOLATED
    assert res.wns == pytest.approx(-0.20)
    assert res.wns < 0


def test_no_clock_gives_delay_report(seq):
    graph, lib = seq
    res = analyze(graph, lib, Sdc(period=None))
    assert res.wns is None
    # Still reports the slowest data arrival and its path.
    assert res.critical_endpoint == "r1/D"
    assert res.arrival["r1/D"] == pytest.approx(0.65)


def test_combinational_loop_detected(unit_lib):
    text = """
    module loop ();
      wire a, b;
      INV u0 (.A(a), .Y(b));
      INV u1 (.A(b), .Y(a));
    endmodule
    """
    nl = parse_verilog(text)
    graph = build_graph(nl, unit_lib)
    with pytest.raises(CombinationalLoopError):
        analyze(graph, unit_lib, Sdc(period=1.0))
