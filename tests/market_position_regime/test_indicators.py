"""The percentiles over 52 weeks and over 252 sessions, worked by hand."""

from datetime import date, timedelta
from decimal import Decimal
from fractions import Fraction

from market_state_research.market_position_regime.script.indicators import (
    SESSIONS,
    WEEKS,
    Percentile,
    percentile,
    rounded,
    session_percentile,
)
from market_state_research.market_position_regime.script.periods import sessions_within

from .support import weeks_back

FIRST = date(2010, 6, 15)


def test_rounding_is_half_even_exact_and_unsigned_at_zero():
    assert rounded(Fraction(25, 1000), 2) == Decimal("0.02")
    assert rounded(Fraction(35, 1000), 2) == Decimal("0.04")
    assert rounded(Fraction(-1, 1000), 2) == Decimal("0.00")
    assert str(rounded(Fraction(-1, 1000), 2)) == "0.00"


def _weeks(values: list[int], newest: date = date(2026, 10, 13)) -> dict[date, int]:
    return dict(zip(weeks_back(newest, len(values)), values, strict=True))


def test_the_percentile_counts_the_other_weeks_strictly_below():
    values = _weeks(list(range(1, WEEKS + 1)))  # rising: the newest is above all 51 others
    newest = max(values)
    assert percentile(newest, values, values.__contains__, FIRST).value == Decimal("100.0")
    assert percentile(newest, values, values.__contains__, FIRST).n == WEEKS - 1
    falling = _weeks(list(range(WEEKS, 0, -1)))
    assert percentile(newest, falling, falling.__contains__, FIRST).value == Decimal("0.0")
    # 26 of the 51 others below: 100 x 26 / 51 = 50.98...
    middle = _weeks([*range(1, 27), *range(100, 125), 50])
    assert percentile(newest, middle, middle.__contains__, FIRST).value == Decimal("51.0")


def test_equal_values_are_not_counted_below():
    flat = _weeks([7] * WEEKS)
    newest = max(flat)
    assert percentile(newest, flat, flat.__contains__, FIRST).value == Decimal("0.0")


def test_a_week_without_every_one_of_the_52_reports_has_no_percentile():
    values = _weeks(list(range(WEEKS)))
    newest = max(values)
    gone = newest - timedelta(weeks=10)
    del values[gone]
    found = percentile(newest, values, values.__contains__, FIRST)
    assert found.value is None
    assert found.reason == (
        f"1 of the 52 weeks to {newest} has no stored report, the first the week of {gone}"
    )
    short = _weeks(list(range(10)))
    assert percentile(newest, short, short.__contains__, FIRST).reason == (
        f"42 of the 52 weeks to {newest} have no stored report, the first the week of {min(values)}"
    )


def test_the_first_51_weeks_of_the_market_have_no_percentile():
    values = _weeks(list(range(WEEKS)), newest=date(2011, 5, 31))  # 52 weeks back reach before 2010-06-15
    found = percentile(date(2011, 5, 31), values, values.__contains__, FIRST)
    assert found.value is None and "begin before the market's first report, the week of 2010-06-15" in (
        found.reason or ""
    )


def test_a_week_without_a_report_has_no_percentile():
    values = _weeks([1, 2, 3])
    week = date(2026, 10, 20)
    assert (
        percentile(week, values, values.__contains__, FIRST).reason == "the week of 2026-10-20 has no report"
    )


SESSIONS_2000 = sessions_within(date(2000, 1, 1), date(2026, 10, 20))
NEWEST = len(SESSIONS_2000) - 1  # 2026-10-20


def _closes(values: list[str], end: int = NEWEST) -> dict[date, Decimal]:
    """``values`` as the closes of the sessions ending with ``SESSIONS_2000[end]``."""
    days = SESSIONS_2000[end - len(values) + 1 : end + 1]
    return {day: Decimal(value) for day, value in zip(days, values, strict=True)}


def test_the_session_percentile_counts_the_other_251_sessions_strictly_below():
    rising = _closes([f"{10 + index}.00" for index in range(SESSIONS)])
    found = session_percentile(SESSIONS_2000, NEWEST, rising, "VIX close")
    assert (found.value, found.n, found.reason) == (Decimal("100.0"), SESSIONS - 1, None)
    falling = _closes([f"{300 - index}.00" for index in range(SESSIONS)])
    assert session_percentile(SESSIONS_2000, NEWEST, falling, "VIX close").value == Decimal("0.0")
    # 126 of the 251 others below: 100 x 126 / 251 = 50.199...
    middle = _closes([*("40.00",) * 126, *("90.00",) * 125, "50.00"])
    assert session_percentile(SESSIONS_2000, NEWEST, middle, "VIX close").value == Decimal("50.2")
    flat = _closes(["20.00"] * SESSIONS)  # equal closes are not counted below
    assert session_percentile(SESSIONS_2000, NEWEST, flat, "VIX close").value == Decimal("0.0")


def test_a_session_without_a_value_lowers_n_and_the_session_itself_needs_one():
    values = _closes([f"{10 + index}.00" for index in range(SESSIONS)])
    gone = SESSIONS_2000[NEWEST - 10]
    del values[gone]
    # 250 others have a value, all below: 100 x 250 / 250.
    found = session_percentile(SESSIONS_2000, NEWEST, values, "SKEW")
    assert (found.value, found.n, found.reason) == (Decimal("100.0"), 250, None)
    # 126 of the 249 others with a value below the session's: 100 x 126 / 249 = 50.6024...
    middle = _closes([*("40.00",) * 126, *("90.00",) * 125, "50.00"])
    for day in SESSIONS_2000[NEWEST - 3 : NEWEST - 1]:
        del middle[day]
    found = session_percentile(SESSIONS_2000, NEWEST, middle, "SKEW")
    assert (found.value, found.n) == (Decimal("50.6"), 249)
    alone = _closes(["20.00"])
    assert session_percentile(SESSIONS_2000, NEWEST, alone, "SKEW") == Percentile(
        None, 0, "no other session of the 252 to 2026-10-20 has a SKEW"
    )
    assert session_percentile(SESSIONS_2000, NEWEST, {}, "VIX close").reason == (
        "Cboe's file holds no VIX close of 2026-10-20"
    )


def test_the_first_251_sessions_of_the_calendar_have_no_percentile():
    closes = _closes(["20.00"] * SESSIONS, end=SESSIONS - 1)
    first = session_percentile(
        SESSIONS_2000, SESSIONS - 1, closes, "VIX close"
    )  # 2000-12-29: the 252nd session
    assert first.value == Decimal("0.0") and SESSIONS_2000[SESSIONS - 1] == date(2000, 12, 29)
    before = session_percentile(SESSIONS_2000, SESSIONS - 2, closes, "VIX close")
    assert before.reason == (
        "the 252 sessions to 2000-12-28 begin before 2000-01-03, the first session of the XNYS calendar the "
        "domain uses"
    )
