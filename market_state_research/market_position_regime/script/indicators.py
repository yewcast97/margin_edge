"""The four indicators and the values they rest on, each computed exactly and rounded once.

- **Year-over-year growth of margin debt** of month M = (debit(M) / debit(M − 12) − 1) × 100,
  from one workbook, rounded half-even to ``YOY_PLACES`` decimal place.
- **Ratio of margin debt to market value** of month M = debit(M) / market value(E) × 100,
  E the latest quarter end on or before M's last day (``periods.quarter_end_of``) and the
  market value the sum of the two Z.1 series at E (``fred``), rounded half-even to
  ``RATIO_PLACES`` decimal places. Both are in $ millions. A month whose quarter end the Fed
  has not published yet has no ratio; no other quarter stands in for it.
- **Asset managers' net position** of week W = long − short, and **leveraged funds' net
  short position** = short − long, in contracts, from W's report.
- **Percentile over 52 weeks** of week W: 100 × the number of the other ``WEEKS`` − 1 weeks
  ending with W whose value is strictly below W's, divided by ``n``, the number of those
  weeks that have a value; equal values are not counted. It is rounded half-even to
  ``PERCENTILE_PLACES`` decimal place, the stock IV regime's percentile over weeks instead of
  sessions. There is none when any of the ``WEEKS`` weeks has no stored report (the reason
  counts them and names the first).

Every function here is pure; a value is ``None`` only with the reason it is absent.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from fractions import Fraction
from typing import Final

from .periods import weeks_ending

YOY_PLACES: Final = 1
RATIO_PLACES: Final = 2
PERCENTILE_PLACES: Final = 1
WEEKS: Final = 52  # the week and the 51 before it


@dataclass(frozen=True)
class Value:
    """One value: rounded, or None and why."""

    value: Decimal | None
    reason: str | None = None


@dataclass(frozen=True)
class Percentile:
    """A percentile with the count of weeks it rests on, or None and why."""

    value: Decimal | None
    n: int | None = None
    reason: str | None = None


def rounded(value: Fraction, places: int) -> Decimal:
    """``value`` rounded half-even to ``places`` decimal places, exactly; zero without a sign."""
    exact = round(value, places)  # Fraction rounding is half-even and exact
    result = (Decimal(exact.numerator) / Decimal(exact.denominator)).quantize(Decimal(1).scaleb(-places))
    return result.copy_abs() if result.is_zero() else result


def growth(current: int, base: int) -> Decimal:
    """(``current`` / ``base`` − 1) × 100, rounded to ``YOY_PLACES``."""
    if base <= 0:
        raise ValueError("a growth needs a positive base")
    return rounded((Fraction(current, base) - 1) * 100, YOY_PLACES)


def ratio(part: int, whole: Decimal) -> Decimal:
    """``part`` / ``whole`` × 100, rounded to ``RATIO_PLACES``."""
    if whole <= 0:
        raise ValueError("a ratio needs a positive whole")
    return rounded(Fraction(part) / Fraction(whole) * 100, RATIO_PLACES)


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
