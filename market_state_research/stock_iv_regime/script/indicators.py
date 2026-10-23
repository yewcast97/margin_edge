"""A session's indicators, computed from its rounded levels.

- The 14-DTE 25Δ skew = the 14-DTE put IV at -0.25 - the 14-DTE call IV at +0.25, in
  percentage points.
- The ATM IV at a horizon = (its call IV at +0.50 + its put IV at -0.50) / 2, in percent.
- The term structure = the 30-DTE ATM IV - the 14-DTE ATM IV, in percentage points, from the
  four 50Δ levels: ((call50_30 + put50_30) - (call50_14 + put50_14)) / 2.

The inputs are the levels as ``surface`` rounds them and the CSV caches them, so the CSV
reproduces every indicator. Each is computed exactly and rounded half-even once to
``surface.PLACES`` places; zero is written without a sign. An indicator one of whose levels is
missing is None, with that level's reason. Every function here is pure.
"""

from collections.abc import Callable
from fractions import Fraction

from .surface import Surface, Target, Value, rounded


def _from(levels: list[Value], formula: Callable[[list[Fraction]], Fraction]) -> Value:
    """``formula`` of ``levels``, rounded; or None with the first missing level's reason."""
    for level in levels:
        if level.value is None:
            return Value(None, level.reason)
    return Value(rounded(formula([Fraction(level.value) for level in levels if level.value is not None])))


def _levels(item: Surface, *targets: Target) -> list[Value]:
    return [item.level(target) for target in targets]


def skew(near: Surface) -> Value:
    """The 25Δ skew of the 14-DTE levels ``near``, in percentage points."""
    return _from(_levels(near, "put25", "call25"), lambda values: values[0] - values[1])


def atm(item: Surface) -> Value:
    """The ATM IV of the levels ``item`` (either horizon), in percent."""
    return _from(_levels(item, "call50", "put50"), lambda values: (values[0] + values[1]) / 2)


def term(near: Surface, far: Surface) -> Value:
    """The term structure of the 14-DTE levels ``near`` and the 30-DTE levels ``far``, in
    percentage points."""
    levels = _levels(near, "call50", "put50") + _levels(far, "call50", "put50")
    return _from(levels, lambda values: (values[2] + values[3] - values[0] - values[1]) / 2)
