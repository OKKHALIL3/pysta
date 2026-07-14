import pytest

from pysta.nldm import LookupTable, lookup


def _grid():
    # values[i][j] at (slew index_1[i], load index_2[j])
    return LookupTable(
        index_1=[0.0, 1.0],
        index_2=[0.0, 10.0],
        values=[[0.0, 10.0], [100.0, 110.0]],
    )


def test_exact_grid_point():
    t = _grid()
    assert lookup(t, 1.0, 10.0) == pytest.approx(110.0)
    assert lookup(t, 0.0, 0.0) == pytest.approx(0.0)


def test_bilinear_center():
    # slew halfway, load halfway -> average of the four corners.
    assert lookup(_grid(), 0.5, 5.0) == pytest.approx(55.0)


def test_load_only_interpolation():
    # Fix slew at a grid row, sweep load.
    assert lookup(_grid(), 0.0, 5.0) == pytest.approx(5.0)
    assert lookup(_grid(), 1.0, 5.0) == pytest.approx(105.0)


def test_extrapolation_beyond_end():
    # slew=2 is past the last index (1.0): keep the last segment's slope.
    assert lookup(_grid(), 2.0, 5.0) == pytest.approx(205.0)


def test_scalar_table():
    t = LookupTable(values=[[7.0]])
    assert lookup(t, 123.0, 456.0) == pytest.approx(7.0)


def test_one_dimensional_slew():
    t = LookupTable(index_1=[0.0, 1.0, 2.0], values=[[5.0], [10.0], [20.0]])
    assert lookup(t, 1.0, 999.0) == pytest.approx(10.0)
    assert lookup(t, 1.5, 0.0) == pytest.approx(15.0)


def test_empty_table_is_zero():
    assert lookup(LookupTable(), 1.0, 1.0) == 0.0
