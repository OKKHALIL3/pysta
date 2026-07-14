import os

from conftest import EXAMPLES
from pysta.netlist import load_verilog, parse_verilog


def test_pipe_structure():
    nl = load_verilog(os.path.join(EXAMPLES, "pipe.v"))
    assert nl.module == "pipe"
    assert nl.inputs == ["clk", "a", "b"]
    assert nl.outputs == ["y"]
    assert set(nl.instances) == {"r0", "g0", "g1", "r1", "g2"}
    assert nl.instances["r0"].cell_type == "DFF"
    assert nl.instances["r0"].conns == {"CK": "clk", "D": "a", "Q": "q0"}


def test_bus_expansion_and_assign():
    text = """
    module t (a, y);
      input [1:0] a;
      output y;
      wire w;
      INV u0 (.A(a[0]), .Y(w));
      assign y = w;
    endmodule
    """
    nl = parse_verilog(text)
    assert nl.inputs == ["a[1]", "a[0]"]
    assert nl.assigns == [("y", "w")]
    assert nl.instances["u0"].conns["A"] == "a[0]"


def test_escaped_identifiers_and_constants():
    text = r"""
    module t (y);
      output y;
      NAND2 u1 (.A(\a[1] ), .B(1'b0), .Y(y));
    endmodule
    """
    nl = parse_verilog(text)
    conns = nl.instances["u1"].conns
    assert conns["A"] == "a[1]"
    assert conns["B"] == "1'b0"
    assert conns["Y"] == "y"


def test_multiple_modules_pick_top():
    text = """
    module sub (a, y); input a; output y; INV u (.A(a), .Y(y)); endmodule
    module top (a, y); input a; output y; BUF u (.A(a), .Y(y)); endmodule
    """
    nl = parse_verilog(text, top="top")
    assert nl.module == "top"
    assert nl.instances["u"].cell_type == "BUF"
