"""The percentile over the 252 sessions ending with a session."""

from datetime import date
from decimal import Decimal

import pytest

from market_state_research.common.sessions import session_window
from market_state_research.stock_iv_regime.script.percentile import WINDOW, percentile

END = date(2026, 10, 16)
SESSIONS = session_window(END, WINDOW)


def everything(day: date) -> bool:
    return True


def values_for(numbers: list[str | None], current: str) -> dict[date, Decimal]:
    """The window's values: ``numbers`` for the sessions before ``END`` (latest last), then ``current``."""
    found = {}
    for day, number in zip(SESSIONS[-1 - len(numbers) : -1], numbers, strict=True):
        if number is not None:
            found[day] = Decimal(number)
    found[END] = Decimal(current)
    return found


def test_share_of_sessions_strictly_below():
    numbers = [str(value) for value in range(100)]  # 0 to 99
    result = percentile(SESSIONS, everything, values_for(numbers, "59.5"))
    assert (result.value, result.n, result.reason) == (Decimal("60.0"), 100, None)


def test_equal_values_are_not_counted():
    result = percentile(SESSIONS, everything, values_for(["1", "2", "2", "3"], "2"))
    assert (result.value, result.n) == (Decimal("25.0"), 4)


@pytest.mark.parametrize(
    ("below", "of", "expected"),
    [(7, 9, "77.8"), (5, 16, "31.2"), (1, 8, "12.5"), (3, 16, "18.8"), (0, 3, "0.0"), (3, 3, "100.0")],
)
def test_rounded_half_even_to_one_place(below, of, expected):
    numbers = ["0"] * below + ["9"] * (of - below)
    result = percentile(SESSIONS, everything, values_for(numbers, "5"))
    assert (str(result.value), result.n) == (expected, of)


def test_a_full_window():
    numbers = [str(value) for value in range(1, 252)]
    result = percentile(SESSIONS, everything, values_for(numbers, "100.5"))
    assert (result.value, result.n) == (Decimal("39.8"), 251)


def test_no_value_on_the_session():
    result = percentile(SESSIONS, everything, {SESSIONS[0]: Decimal(1)})
    assert (result.value, result.reason) == (None, "2026-10-16 has no value")


def test_an_unfetched_session_in_the_window():
    missing = {SESSIONS[3], SESSIONS[10]}
    result = percentile(SESSIONS, lambda day: day not in missing, values_for(["1"], "2"))
    assert result.value is None
    assert result.reason == f"2 of the 252 sessions to 2026-10-16 are not fetched, the first {SESSIONS[3]}"


def test_no_other_session_with_a_value():
    result = percentile(SESSIONS, everything, values_for([None, None], "2"))
    assert (result.value, result.n) == (None, 0)
    assert result.reason == "no other session of the 252 to 2026-10-16 has a value"


def test_the_window_must_hold_252_sessions():
    with pytest.raises(ValueError):
        percentile(SESSIONS[1:], everything, {})
