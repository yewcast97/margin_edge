"""The 15-session correlation of the daily return with the change of a 14-DTE IV, worked by hand."""

import statistics
from datetime import date
from decimal import Decimal
from fractions import Fraction

import pytest

from market_state_research.common.sessions import session_window
from market_state_research.market_regime.script.correlation import (
    WINDOW,
    _rounded_root,
    correlation,
    iv_change,
    pearson,
)
from market_state_research.market_regime.script.surface import Value

END = date(2026, 10, 16)
SESSIONS = session_window(END, WINDOW + 1)  # 2026-09-25 to 2026-10-16
LABEL = "14-DTE call IV"


def pairs_of(xs, ys):
    return [(Fraction(x), Fraction(y)) for x, y in zip(xs, ys, strict=True)]


def test_pearson_by_hand():
    # Deviations (-1, 0, 1) and (-1, 1, 0): sxy 1, sxx 2, syy 2, r = 1/2.
    assert pearson(pairs_of([1, 2, 3], [1, 3, 2])) == Decimal("0.50")
    assert pearson(pairs_of(range(15), range(15))) == Decimal("1.00")
    assert pearson(pairs_of(range(15), range(15, 0, -1))) == Decimal("-1.00")
    # Orthogonal deviations: r is 0, written without a sign.
    assert str(pearson(pairs_of([1, 2, 3], [1, 0, 1]))) == "0.00"


def test_pearson_agrees_with_an_independent_float_computation():
    xs = ["0.5", "-1.2", "2.25", "0.0", "-0.75", "1.1", "-2.4", "0.35", "1.9", "-0.6", "0.8", "-1.5", "2.0"]
    xs += ["-0.25", "0.65"]
    ys = ["0.12", "0.40", "-0.33", "0.05", "0.21", "-0.10", "0.66", "0.00", "-0.48", "0.15", "-0.07"]
    ys += ["0.52", "-0.41", "0.09", "-0.02"]
    expected = statistics.correlation([float(x) for x in xs], [float(y) for y in ys])
    assert pearson(pairs_of(xs, ys)) == Decimal(str(round(expected, 2)))
    assert pearson(pairs_of(xs, ys)) < 0


def test_a_constant_series_has_no_correlation():
    assert pearson(pairs_of([1, 2, 3], [5, 5, 5])) is None
    assert pearson(pairs_of([4, 4, 4], [1, 2, 3])) is None


def test_the_square_root_is_rounded_half_even_exactly():
    assert _rounded_root(Fraction(225, 10**6), 2) == Decimal("0.02")  # sqrt is 0.015: up to the even 2
    assert _rounded_root(Fraction(25, 10**6), 2) == Decimal("0.00")  # sqrt is 0.005: down to the even 0
    assert _rounded_root(Fraction(1), 2) == Decimal("1.00")
    assert _rounded_root(Fraction(1, 4), 2) == Decimal("0.50")


def test_iv_change():
    first, second, third = SESSIONS[:3]
    values = {first: Decimal("27.25"), second: Decimal("27.50"), third: None}
    assert iv_change(values, second, LABEL) == Value(Decimal("0.25"))
    assert iv_change(values, third, LABEL) == Value(None, f"no {LABEL} on 2026-09-29")
    assert iv_change(values, first, LABEL) == Value(None, "the previous session 2026-09-24 is not fetched")
    assert iv_change({first: None, second: None}, second, LABEL) == Value(
        None, f"no {LABEL} on 2026-09-25 and 2026-09-28"
    )
    assert str(iv_change({first: Decimal("1.10"), second: Decimal("1.1")}, second, LABEL).value) == "0.00"


def test_correlation_over_the_window():
    returns = {day: Value(Decimal(index % 4)) for index, day in enumerate(SESSIONS)}
    changes = {day: Value(Decimal(index % 4) * 2) for index, day in enumerate(SESSIONS)}
    found = correlation(END, lambda day: True, returns, changes, LABEL)
    assert found == Value(Decimal("1.00"))


def test_correlation_needs_every_session_fetched():
    returns = {day: Value(Decimal(index)) for index, day in enumerate(SESSIONS)}
    unfetched = {SESSIONS[0], SESSIONS[3]}
    found = correlation(END, lambda day: day not in unfetched, returns, returns, LABEL)
    assert found == Value(None, "2 of the 16 sessions to 2026-10-16 are not fetched, the first 2026-09-25")
    one = correlation(END, lambda day: day != SESSIONS[0], returns, returns, LABEL)
    assert one.reason == "1 of the 16 sessions to 2026-10-16 is not fetched, the first 2026-09-25"


def test_correlation_needs_every_pair():
    returns = {day: Value(Decimal(index)) for index, day in enumerate(SESSIONS)}
    changes = dict(returns)
    changes[SESSIONS[5]] = Value(None, f"no {LABEL} on 2026-10-02")
    returns[SESSIONS[9]] = Value(None, "no bar of 2026-10-08 in the prices from 2025-07-01 to 2026-10-16")
    returns[SESSIONS[0]] = Value(None, "the first session's own pair is not one of the 15")
    found = correlation(END, lambda day: True, returns, changes, LABEL)
    assert found == Value(
        None,
        f"2 of the 15 sessions to 2026-10-16 have no return or no {LABEL} change, the first 2026-10-02: "
        f"no {LABEL} on 2026-10-02",
    )


def test_a_constant_change_has_no_correlation():
    returns = {day: Value(Decimal(index)) for index, day in enumerate(SESSIONS)}
    changes = {day: Value(Decimal("0.00")) for day in SESSIONS}
    found = correlation(END, lambda day: True, returns, changes, LABEL)
    assert found == Value(
        None, f"the return or the {LABEL} change is constant over the 15 sessions to 2026-10-16"
    )


@pytest.mark.parametrize("day", [SESSIONS[-1], SESSIONS[-2]])
def test_the_window_ends_with_the_session(day):
    returns = {item: Value(Decimal(index)) for index, item in enumerate(session_window(day, WINDOW + 1))}
    assert correlation(day, lambda item: True, returns, returns, LABEL) == Value(Decimal("1.00"))
