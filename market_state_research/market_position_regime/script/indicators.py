"""The three indicators and the values they rest on, each computed exactly and rounded once.

- **Margin debt** of month M is FINRA's debit balances as published: no value is derived.
- **Asset managers' net position** of week W = long − short, and **leveraged funds' net
  short position** = short − long, in contracts, from W's report.
- **Percentile over 52 weeks** of week W: 100 × the number of the other ``WEEKS`` − 1 weeks
  ending with W whose value is strictly below W's, divided by ``n``, the number of those
  weeks that have a value; equal values are not counted. There is none when any of the
  ``WEEKS`` weeks has no stored report (the reason counts them and names the first).
- **Percentile over 252 sessions** of XNYS session D: 100 × the number of the other
  ``SESSIONS`` − 1 sessions ending with D whose VIX close is strictly below D's, divided by
  ``SESSIONS`` − 1; equal closes are not counted. There is none when any of the ``SESSIONS``
  sessions has no close (the reason counts them and names the first), or when they begin
  before the first session of the calendar the domain uses.

Both percentiles are rounded half-even to ``PERCENTILE_PLACES`` decimal place: the stock IV
regime's percentile, over weeks or over sessions. Every function here is pure; a value is
``None`` only with the reason it is absent.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from fractions import Fraction
from typing import Final

from .periods import weeks_ending

PERCENTILE_PLACES: Final = 1
WEEKS: Final = 52  # the week and the 51 before it
SESSIONS: Final = 252  # the session and the 251 before it


@dataclass(frozen=True)
class Percentile:
    """A percentile with the count of weeks or sessions it rests on, or None and why."""

    value: Decimal | None
    n: int | None = None
    reason: str | None = None


def rounded(value: Fraction, places: int) -> Decimal:
    """``value`` rounded half-even to ``places`` decimal places, exactly; zero without a sign."""
    exact = round(value, places)  # Fraction rounding is half-even and exact
    result = (Decimal(exact.numerator) / Decimal(exact.denominator)).quantize(Decimal(1).scaleb(-places))
    return result.copy_abs() if result.is_zero() else result


def percentile(
    week: date, values: Mapping[date, int], stored: Callable[[date], bool], first_week: date
) -> Percentile:
    """The percentile of ``week``'s value among the ``WEEKS`` weeks ending with it.

    ``values`` holds each week's value by the Tuesday naming it; ``stored`` says whether a week
    has a stored report; ``first_week`` is the week of the market's first report.
    """
    window = weeks_ending(week, WEEKS)
    current = values.get(week)
    if current is None:
        return Percentile(None, None, f"the week of {week.isoformat()} has no report")
    if window[0] < first_week:
        return Percentile(
            None,
            None,
            f"the {WEEKS} weeks to {week.isoformat()} begin before the market's first report, "
            f"the week of {first_week.isoformat()}",
        )
    unstored = [day for day in window if not stored(day)]
    if unstored:
        count = len(unstored)
        return Percentile(
            None,
            None,
            f"{count} of the {WEEKS} weeks to {week.isoformat()} {'has' if count == 1 else 'have'} no "
            f"stored report, the first the week of {unstored[0].isoformat()}",
        )
    others = [values[day] for day in window[:-1] if day in values]
    if not others:
        return Percentile(None, 0, f"no other week of the {WEEKS} to {week.isoformat()} has a value")
    below = sum(1 for value in others if value < current)
    return Percentile(rounded(Fraction(100 * below, len(others)), PERCENTILE_PLACES), len(others))


def session_percentile(sessions: Sequence[date], index: int, closes: Mapping[date, Decimal]) -> Percentile:
    """The percentile of the close of ``sessions[index]`` among the ``SESSIONS`` sessions ending
    with it.

    ``sessions`` holds every XNYS session from the first of the calendar the domain uses,
    ascending; ``closes`` the VIX close of each session Cboe's file holds one for.
    """
    session = sessions[index]
    current = closes.get(session)
    if current is None:
        return Percentile(None, None, f"Cboe's file holds no close of {session.isoformat()}")
    if index < SESSIONS - 1:
        return Percentile(
            None,
            None,
            f"the {SESSIONS} sessions to {session.isoformat()} begin before {sessions[0].isoformat()}, "
            "the first session of the XNYS calendar the domain uses",
        )
    window = sessions[index - SESSIONS + 1 : index + 1]
    absent = [day for day in window if day not in closes]
    if absent:
        count = len(absent)
        return Percentile(
            None,
            None,
            f"{count} of the {SESSIONS} sessions to {session.isoformat()} {'has' if count == 1 else 'have'} "
            f"no close in Cboe's file, the first {absent[0].isoformat()}",
        )
    below = sum(1 for day in window[:-1] if closes[day] < current)
    return Percentile(rounded(Fraction(100 * below, SESSIONS - 1), PERCENTILE_PLACES), SESSIONS - 1)
