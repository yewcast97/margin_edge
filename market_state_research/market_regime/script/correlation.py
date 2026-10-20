"""The 15-session correlation of the stock's daily return with the change of a 14-DTE 25Δ IV.

For session D, the pairs are (return(t), ΔIV(t)) of the ``WINDOW`` XNYS sessions t ending
with D, contemporaneous: return(t) the stock's daily return (``prices.daily_return``) and
ΔIV(t) the change of the 14-DTE call IV at +0.25Δ (or of the put IV at -0.25Δ) since the
previous XNYS session, both formed from the values as archived (rounded), so the CSV
reproduces every pair. The correlation is the sample Pearson coefficient of the pairs,
computed exactly from fractions (the one square root included) and rounded half-even once
to ``PLACES`` decimal places; zero is written without a sign.

There is none, with the reason, when any of the ``WINDOW + 1`` sessions to D (the pairs'
sessions and the one before them, which the first return and change rest on) has no
fetched chain (the reason counts them and names the first), when a pair session has no
return or no change (likewise, with the first one's reason), or when either series is
constant over the window. Every function here is pure.
"""

import math
from collections.abc import Callable, Mapping, Sequence
from datetime import date
from decimal import Decimal
from fractions import Fraction
from typing import Final

from market_state_research.common.sessions import previous_session, session_window

from .surface import Value, difference

WINDOW: Final = 15  # pairs: XNYS sessions, D included
PLACES: Final = 2


def _rounded_root(square: Fraction, places: int) -> Decimal:
    """The square root of ``square`` (not negative) rounded half-even to ``places`` places, exactly."""
    scaled = square * 10 ** (2 * places)
    whole = math.isqrt(scaled.numerator // scaled.denominator)  # floor(sqrt(scaled))
    half = Fraction(2 * whole + 1, 2) ** 2  # the square of the midpoint above it
    if scaled > half or (scaled == half and whole % 2 == 1):
        whole += 1
    return Decimal(whole).scaleb(-places)


def pearson(pairs: Sequence[tuple[Fraction, Fraction]], places: int = PLACES) -> Decimal | None:
    """The sample Pearson correlation of ``pairs``, rounded half-even to ``places`` places; None
    when either series is constant."""
    count = len(pairs)
    mean_x = sum((x for x, _ in pairs), Fraction(0)) / count
    mean_y = sum((y for _, y in pairs), Fraction(0)) / count
    sxx = sum(((x - mean_x) ** 2 for x, _ in pairs), Fraction(0))
    syy = sum(((y - mean_y) ** 2 for _, y in pairs), Fraction(0))
    sxy = sum(((x - mean_x) * (y - mean_y) for x, y in pairs), Fraction(0))
    if sxx == 0 or syy == 0:
        return None
    size = _rounded_root(sxy * sxy / (sxx * syy), places)  # |r|, as r squared is rational
    return -size if sxy < 0 and not size.is_zero() else size


def iv_change(values: Mapping[date, Decimal | None], day: date, label: str) -> Value:
    """The change of fetched session ``day``'s value since the previous XNYS session, from the
    rounded values of ``values`` (every fetched session's, None where it has none); ``label``
    names the value in the reason."""
    previous = previous_session(day)
    if previous not in values:
        return Value(None, f"the previous session {previous.isoformat()} is not fetched")
    current, before = values[day], values[previous]
    if current is None or before is None:
        without = " and ".join(item.isoformat() for item in (previous, day) if values[item] is None)
        return Value(None, f"no {label} on {without}")
    return Value(difference(current, before))


def _counted(count: int, total: int, day: date, verb: tuple[str, str]) -> str:
    return f"{count} of the {total} sessions to {day.isoformat()} {verb[0] if count == 1 else verb[1]}"


def correlation(
    day: date,
    fetched: Callable[[date], bool],
    returns: Mapping[date, Value],
    changes: Mapping[date, Value],
    label: str,
) -> Value:
    """The correlation of fetched session ``day`` (see the module docstring).

    ``returns`` and ``changes`` hold every fetched session's return and change; ``label``
    names the changing value in the reasons.
    """
    window = session_window(day, WINDOW + 1)
    unfetched = [item for item in window if not fetched(item)]
    if unfetched:
        counted = _counted(len(unfetched), WINDOW + 1, day, ("is not fetched", "are not fetched"))
        return Value(None, f"{counted}, the first {unfetched[0].isoformat()}")
    pairs: list[tuple[Fraction, Fraction]] = []
    lacking: list[tuple[date, str]] = []
    for item in window[1:]:
        found, change = returns[item], changes[item]
        if found.value is None or change.value is None:
            lacking.append((item, (found.reason if found.value is None else change.reason) or ""))
        else:
            pairs.append((Fraction(found.value), Fraction(change.value)))
    if lacking:
        counted = _counted(len(lacking), WINDOW, day, ("has", "have"))
        first, reason = lacking[0]
        return Value(
            None, f"{counted} no return or no {label} change, the first {first.isoformat()}: {reason}"
        )
    value = pearson(pairs)
    if value is None:
        return Value(
            None, f"the return or the {label} change is constant over the {WINDOW} sessions to {day}"
        )
    return Value(value)
