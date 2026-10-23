"""The indicators computed from a session's rounded levels, worked by hand."""

from datetime import date
from decimal import Decimal

from market_state_research.stock_iv_regime.script import indicators
from market_state_research.stock_iv_regime.script.surface import REQUIRED, Surface, Value

SESSION = date(2026, 10, 16)


def levels(horizon: int, **values: str | None) -> Surface:
    """A surface of ``horizon`` with the levels ``values`` (text, or None for a blank one)."""
    found = {
        target: Value(None, f"no {target} at {horizon} days")
        if values[target] is None
        else Value(Decimal(values[target]))
        for target in REQUIRED[horizon]
    }
    return Surface(SESSION, horizon, "exact", (), found)


NEAR = levels(14, call25="27.25", put25="34.53", call50="29.00", put50="34.53")
FAR = levels(30, call50="30.10", put50="35.63")


def test_the_skew_is_the_put_minus_the_call():
    assert indicators.skew(NEAR) == Value(Decimal("7.28"))
    assert indicators.skew(levels(14, call25="30.00", put25="30.00", call50="1", put50="1")) == Value(
        Decimal("0.00")
    )


def test_an_atm_iv_is_the_mean_of_the_50_delta_levels_rounded_half_even():
    assert indicators.atm(NEAR) == Value(Decimal("31.76"))  # 31.765 rounds to the even 31.76
    assert indicators.atm(FAR) == Value(Decimal("32.86"))  # 32.865 rounds to 32.86
    assert indicators.atm(levels(30, call50="30.10", put50="35.65")) == Value(Decimal("32.88"))  # 32.875


def test_the_term_structure_is_computed_once_from_the_four_50_delta_levels():
    # (30.10 + 35.63 - 29.00 - 34.53) / 2 = 1.10; the rounded ATM IVs would give 32.86 - 31.76 = 1.10 too.
    assert indicators.term(NEAR, FAR) == Value(Decimal("1.10"))
    # (30.11 + 35.63 - 29.00 - 34.53) / 2 = 1.105, rounded once to 1.10 (half-even); the difference of
    # the rounded ATM IVs (32.87 - 31.76) would be 1.11.
    far = levels(30, call50="30.11", put50="35.63")
    assert indicators.term(NEAR, far) == Value(Decimal("1.10"))
    assert indicators.term(far, far) == Value(Decimal("0.00"))


def test_an_indicator_without_a_level_has_the_levels_reason():
    blank = levels(30, call50=None, put50="35.63")
    assert indicators.atm(blank) == Value(None, "no call50 at 30 days")
    assert indicators.term(NEAR, blank) == Value(None, "no call50 at 30 days")
    near = levels(14, call25="27.25", put25=None, call50=None, put50="34.53")
    assert indicators.skew(near) == Value(None, "no put25 at 14 days")
    assert indicators.term(near, blank) == Value(None, "no call50 at 14 days")  # the 14-DTE reason first
