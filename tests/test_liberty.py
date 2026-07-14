import os

import pytest

from conftest import EXAMPLES
from pysta.liberty import load_liberty, parse_liberty


@pytest.fixture(scope="module")
def lib():
    return load_liberty(os.path.join(EXAMPLES, "tiny.lib"))


def test_cells_present(lib):
    assert set(lib.cells) >= {"INV", "BUF", "NAND2", "NOR2", "DFF"}


def test_inv_arc_and_table(lib):
    inv = lib.cells["INV"]
    y = inv.pins["Y"]
    assert y.direction == "output"
    assert len(y.arcs) == 1
    arc = y.arcs[0]
    assert arc.related_pin == "A"
    assert arc.timing_sense == "negative_unate"
    # First grid value of cell_rise.
    assert arc.cell_rise.values[0][0] == pytest.approx(0.012)
    assert arc.cell_rise.index_1 == [0.01, 0.10, 0.50]
    assert arc.cell_rise.index_2 == [0.001, 0.010, 0.050]


def test_input_capacitance(lib):
    assert lib.cells["NAND2"].pins["A"].capacitance == pytest.approx(0.0020)


def test_nand2_has_two_arcs(lib):
    arcs = lib.cells["NAND2"].pins["Y"].arcs
    assert {a.related_pin for a in arcs} == {"A", "B"}


def test_dff_is_sequential(lib):
    dff = lib.cells["DFF"]
    assert dff.is_sequential
    assert dff.ff_q == "Q"
    assert dff.ff_next_state.strip('"') == "D"
    assert dff.pins["CK"].is_clock
    # Q has a clock->Q edge arc; D has a setup constraint arc.
    assert any(a.is_edge for a in dff.pins["Q"].arcs)
    assert any(a.is_setup for a in dff.pins["D"].arcs)


def test_comment_and_continuation_handling():
    text = """
    library (t) {
      /* block comment */
      cell (X) {
        pin (Y) { direction : output;
          timing () { related_pin : "A";
            cell_rise (tmpl) {
              index_1 ("0.1, 0.2");
              values ("1.0, 2.0", \\
                      "3.0, 4.0");
            }
          }
        }
      }
    }
    """
    lib = parse_liberty(text)
    tbl = lib.cells["X"].pins["Y"].arcs[0].cell_rise
    assert tbl.values == [[1.0, 2.0], [3.0, 4.0]]
