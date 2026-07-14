"""The delay model: NLDM lookup-table interpolation.

A real chip library doesn't store one delay per gate -- a gate's delay depends
on two things:

  * how fast its input is changing (the "input slew" / transition time), and
  * how much capacitance it has to drive (the "output load").

So the library stores a small GRID of measured delays, indexed by slew and load,
and we look up (interpolating between grid points) for the actual slew/load we
have. That grid is called an NLDM table (Non-Linear Delay Model). This module is
just the math that reads such a grid.

Convention used throughout PySTA:
    index_1 = input slew (transition time)
    index_2 = output load capacitance
    values[i][j] = value at (index_1[i], index_2[j])
This matches the ``variable_1 = input_net_transition``,
``variable_2 = total_output_net_capacitance`` template that essentially every
real library uses.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class LookupTable:
    """One NLDM grid (a delay table, a slew table, or a setup/hold table)."""

    index_1: list[float] = field(default_factory=list)  # input slew axis
    index_2: list[float] = field(default_factory=list)  # output load axis
    values: list[list[float]] = field(default_factory=list)  # values[i][j]

    @property
    def is_empty(self) -> bool:
        return not self.values or not self.values[0]


def _interp1(xs: list[float], ys: list[float], x: float) -> float:
    """Linear interpolation of y at x, with flat-ish extrapolation past the ends.

    ``xs`` is sorted ascending. If x falls outside the table we keep going along
    the nearest segment's slope (standard NLDM behaviour), which is why we grab
    the first/last *two* points rather than clamping.
    """
    n = len(xs)
    if n == 1:
        return ys[0]
    if x <= xs[0]:
        x0, x1, y0, y1 = xs[0], xs[1], ys[0], ys[1]
    elif x >= xs[-1]:
        x0, x1, y0, y1 = xs[-2], xs[-1], ys[-2], ys[-1]
    else:
        i = 0
        while x > xs[i + 1]:
            i += 1
        x0, x1, y0, y1 = xs[i], xs[i + 1], ys[i], ys[i + 1]
    if x1 == x0:
        return y0
    t = (x - x0) / (x1 - x0)
    return y0 + t * (y1 - y0)


def lookup(table: LookupTable, in_slew: float, load: float) -> float:
    """Read ``table`` at the given input slew and output load.

    Handles the full 2-D grid (bilinear interpolation) and gracefully degrades
    to 1-D or scalar tables, which real libraries do use for simple cells.
    """
    if table is None or table.is_empty:
        return 0.0

    r1, r2, v = table.index_1, table.index_2, table.values

    # Scalar table: a single number, no dependence on slew or load.
    if len(v) == 1 and len(v[0]) == 1:
        return v[0][0]

    # 1-D over the load axis only (one row).
    if len(v) == 1:
        return _interp1(r2, v[0], load)

    # 1-D over the slew axis only (one column).
    if len(v[0]) == 1 or not r2:
        column = [row[0] for row in v]
        return _interp1(r1, column, in_slew)

    # Full 2-D: interpolate each slew-row across load, then across slew.
    per_slew = [_interp1(r2, row, load) for row in v]
    return _interp1(r1, per_slew, in_slew)
