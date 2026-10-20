"""Where a session's value lies among the ``WINDOW`` XNYS sessions ending with it.

The percentile of session D is 100 times the number of the other ``WINDOW - 1`` sessions
whose value is strictly below D's, divided by ``n``, the number of those sessions that have
a value; equal values are not counted. It is computed exactly and rounded half-even once to
``PLACES`` decimal place. There is none when D has no value, when any of the ``WINDOW``
sessions has no fetched chain (the reason counts them and names the first), or when no
other session has a value. Every function here is pure.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from fractions import Fraction
from typing import Final

from .surface import rounded

WINDOW: Final = 252  # XNYS sessions, D included
PLACES: Final = 1


@dataclass(frozen=True)
class Percentile:
    """A percentile with the count of sessions it rests on, or None and why."""

    value: Decimal | None
    n: int | None = None
    reason: str | None = None


def percentile(
    window: Sequence[date],
    fetched: Callable[[date], bool],
    values: Mapping[date, Decimal],
) -> Percentile:
    """The percentile of ``window[-1]`` over ``window`` (``WINDOW`` sessions, ascending).

    ``fetched`` says whether a session has a chain; ``values`` holds the sessions with a value.
    """
    if len(window) != WINDOW:
        raise ValueError(f"a percentile window holds {WINDOW} sessions")
    session = window[-1]
    current = values.get(session)
    if current is None:
        return Percentile(None, None, f"{session.isoformat()} has no value")
    unfetched = [day for day in window if not fetched(day)]
    if unfetched:
        count = len(unfetched)
        return Percentile(
            None,
            None,
            f"{count} of the {WINDOW} sessions to {session.isoformat()} {'is' if count == 1 else 'are'} "
            f"not fetched, the first {unfetched[0].isoformat()}",
        )
    others = [values[day] for day in window[:-1] if day in values]
    if not others:
        return Percentile(None, 0, f"no other session of the {WINDOW} to {session.isoformat()} has a value")
    below = sum(1 for value in others if value < current)
    return Percentile(rounded(Fraction(100 * below, len(others)), PLACES), len(others))
