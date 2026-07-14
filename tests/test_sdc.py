import os

import pytest

from conftest import EXAMPLES
from pysta.sdc import load_sdc, parse_sdc


def test_pipe_sdc():
    sdc = load_sdc(os.path.join(EXAMPLES, "pipe.sdc"))
    assert sdc.period == pytest.approx(2.0)
    assert sdc.clock_port == "clk"
    assert sdc.input_delay["a"] == pytest.approx(0.2)
    assert sdc.input_delay["b"] == pytest.approx(0.2)
    assert sdc.output_delay["y"] == pytest.approx(0.3)


def test_create_clock_variants():
    a = parse_sdc("create_clock -period 5 -name c [get_ports clk]")
    assert a.period == 5.0 and a.clock_port == "clk" and a.clock_name == "c"

    b = parse_sdc("create_clock -name c2 -period 3.5 {CLK}")
    assert b.period == 3.5 and b.clock_port == "CLK"


def test_comments_ignored():
    sdc = parse_sdc("# just a comment\ncreate_clock -period 1.0 [get_ports clk]\n")
    assert sdc.period == 1.0
