"""The growth, the ratio and the percentile over 52 weeks, worked by hand."""

from datetime import date, timedelta
from decimal import Decimal
from fractions import Fraction

import pytest

from market_state_research.market_position_regime.script.indicators import (
    WEEKS,
    growth,
    percentile,
    ratio,
    rounded,
)

from .support import weeks_back

FIRST = date(2010, 6, 15)


def test_rounding_is_half_even_exact_and_unsigned_at_zero():
    assert rounded(Fraction(25, 1000), 2) == Decimal("0.02")
    assert rounded(Fraction(35, 1000), 2) == Decimal("0.04")
    assert rounded(Fraction(-1, 1000), 2) == Decimal("0.00")
    assert str(rounded(Fraction(-1, 1000), 2)) == "0.00"


def test_growth_is_the_change_over_the_base_in_percent():
    assert growth(1_480_054, 1_126_355) == Decimal("31.4")  # 31.40...%
    assert growth(110, 100) == Decimal("10.0")
    assert growth(90, 100) == Decimal("-10.0")
    assert growth(100_050, 100_000) == Decimal("0.0")  # 0.05 % rounds half-even to 0.0
    with pytest.raises(ValueError):
        growth(1, 0)


def test_ratio_is_a_share_in_percent_to_two_places():
    # 1,502,072 / 109,244,695 = 1.37496...%
    assert ratio(1_502_072, Decimal("109244695")) == Decimal("1.37")
    assert ratio(1, Decimal("200")) == Decimal("0.50")
    assert ratio(1, Decimal("80000")) == Decimal("0.00")  # 0.00125 % rounds half-even to 0.00
    with pytest.raises(ValueError):
        ratio(1, Decimal(0))


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
