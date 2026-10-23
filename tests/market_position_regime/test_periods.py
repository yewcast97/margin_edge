"""Months, weeks and XNYS sessions, and when each source's document is due."""

from datetime import date

import pytest

from market_state_research.market_position_regime.script.periods import (
    Month,
    cboe_due,
    cboe_is_due,
    cftc_release,
    finra_due,
    months_ending_within,
    sessions_within,
    week_days,
    week_of,
    weeks_ending,
    weeks_within,
)

from .support import edt, est


def test_a_month_is_written_and_shifted_exactly():
    assert Month.parse("2026-09") == Month(2026, 9)
    assert Month(2026, 9).isoformat() == "2026-09"
    assert Month(2026, 1).shifted(-1) == Month(2025, 12)
    assert Month(2025, 12).shifted(1) == Month(2026, 1)
    assert Month(2026, 9).shifted(-12) == Month(2025, 9)
    assert (Month(2024, 2).first_day(), Month(2024, 2).last_day()) == (date(2024, 2, 1), date(2024, 2, 29))
    assert Month(2025, 2).last_day() == date(2025, 2, 28)
    assert Month(2025, 12).last_day() == date(2025, 12, 31)
    assert Month(2026, 1) < Month(2026, 2) < Month(2027, 1)


@pytest.mark.parametrize(
    "text", ["2026-9", "2026-13", "2026-00", "26-09", "2026-09-01", "２０２６-09", " 2026-09"]
)
def test_a_month_must_be_written_yyyy_mm(text):
    with pytest.raises(ValueError):
        Month.parse(text)


def test_the_months_of_a_window_are_those_whose_last_day_lies_in_it():
    months = months_ending_within(date(2023, 10, 20), date(2026, 10, 20))
    assert (months[0], months[-1], len(months)) == (Month(2023, 10), Month(2026, 9), 36)
    assert months_ending_within(date(2026, 9, 30), date(2026, 9, 30)) == (Month(2026, 9),)
    assert months_ending_within(date(2026, 10, 1), date(2026, 10, 30)) == ()


def test_finra_is_due_from_the_15th_of_the_following_month():
    assert finra_due(Month(2026, 9)) == date(2026, 10, 15)
    assert finra_due(Month(2026, 12)) == date(2027, 1, 15)


def test_a_week_is_named_by_its_tuesday():
    assert week_of(date(2025, 11, 10)) == date(2025, 11, 11)  # a Monday report (Veterans Day)
    assert week_of(date(2026, 10, 13)) == date(2026, 10, 13)
    assert week_of(date(2026, 10, 18)) == date(2026, 10, 13)  # Sunday ends the week
    assert week_of(date(2026, 10, 19)) == date(2026, 10, 20)
    assert week_days(date(2026, 10, 13)) == (date(2026, 10, 12), date(2026, 10, 18))


def test_the_weeks_of_a_window_are_those_whose_tuesday_lies_in_it():
    assert weeks_within(date(2026, 10, 7), date(2026, 10, 20)) == (date(2026, 10, 13), date(2026, 10, 20))
    assert weeks_within(date(2026, 10, 14), date(2026, 10, 19)) == ()
    assert weeks_ending(date(2026, 10, 13), 3) == (date(2026, 9, 29), date(2026, 10, 6), date(2026, 10, 13))
    with pytest.raises(ValueError, match="Tuesday"):
        weeks_ending(date(2026, 10, 12), 3)


def test_a_cftc_week_is_due_its_friday_at_half_past_three_new_york_time():
    assert cftc_release(date(2026, 10, 13)) == edt(2026, 10, 16, 15, 30)
    assert cftc_release(date(2026, 11, 3)) == est(2026, 11, 6, 15, 30)  # after the clocks fell back
    with pytest.raises(ValueError):
        cftc_release(date(2026, 10, 12))


def test_the_sessions_of_a_span_are_xnys_sessions_from_2000():
    assert sessions_within(date(2026, 9, 3), date(2026, 9, 9)) == (
        date(2026, 9, 3),
        date(2026, 9, 4),
        date(2026, 9, 8),  # Labor Day and the weekend are no sessions
        date(2026, 9, 9),
    )
    assert sessions_within(date(1997, 1, 1), date(2000, 1, 4)) == (date(2000, 1, 3), date(2000, 1, 4))
    assert sessions_within(date(1990, 1, 2), date(1999, 12, 31)) == ()


def test_a_sessions_vix_and_skew_are_due_a_quarter_of_an_hour_after_its_close():
    assert cboe_due(date(2026, 10, 20)) == edt(2026, 10, 20, 16, 15)
    assert cboe_due(date(2026, 11, 27)) == est(2026, 11, 27, 13, 15)  # an early close
    assert cboe_due(date(2026, 11, 2)) == est(2026, 11, 2, 16, 15)  # after the clocks fell back
    with pytest.raises(ValueError):
        cboe_due(date(2026, 9, 7))  # Labor Day is no session
    assert not cboe_is_due(date(2026, 10, 20), edt(2026, 10, 20, 16, 14, 59))
    assert cboe_is_due(date(2026, 10, 20), edt(2026, 10, 20, 16, 15))
    assert cboe_is_due(date(2026, 10, 19), edt(2026, 10, 20, 9, 0))
    assert not cboe_is_due(date(2026, 10, 21), edt(2026, 10, 20, 23, 0))
