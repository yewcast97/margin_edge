"""The dates the three sources publish by, and when each document is due.

FINRA dates its balances by month (``Month``, as of the month's last business day), the CFTC
its positions by week, and Cboe the VIX and the SKEW by day. The CFTC reports one week's
positions as of its Tuesday, or as of its Monday when the Tuesday is a holiday, so a week is
named by its Tuesday (``week_of``), whatever day its report is dated. The VIX and the SKEW
are read by XNYS session (``common.sessions``): the calendar the domain uses knows the
sessions from 2000-01-03, so a span of days holds only the sessions from then on
(``sessions_within``). A document is due from the earliest time its source publishes it: a
FINRA month from the 15th of the month after it (FINRA publishes in the third week); a CFTC
week from its Friday at 15:30 New York time; a session's VIX and SKEW from a quarter of an
hour after its XNYS close (``cboe_due``), when Cboe ends the day's calculation of the VIX
(Cboe replaces each file later that evening). A due document the source has not published
yet is ``pending`` after a ``fetch``. Every function here is pure.
"""

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Final

from market_state_research.common.sessions import session_close, sessions_between
from market_state_research.common.times import NEW_YORK, to_eastern

FINRA_DUE_DAY: Final = 15  # of the month after the month
CFTC_RELEASE: Final = time(15, 30)  # New York time, on the week's Friday
CBOE_SETTLE: Final = timedelta(minutes=15)  # Cboe calculates the VIX until 15 minutes after XNYS closes
TUESDAY: Final = 1  # date.weekday()
FRIDAY: Final = 4
WEEK: Final = timedelta(days=7)

_MONTH = re.compile(r"(?P<year>[0-9]{4})-(?P<month>[0-9]{2})", re.ASCII)


@dataclass(frozen=True, order=True)
class Month:
    """A calendar month, written ``YYYY-MM``."""

    year: int
    month: int

    def __post_init__(self) -> None:
        if not (1 <= self.month <= 12 and 1 <= self.year <= 9999):
            raise ValueError(f"no month {self.year:04d}-{self.month:02d}")

    @classmethod
    def parse(cls, text: str) -> "Month":
        """The month ``YYYY-MM`` names in ASCII digits, or ``ValueError``."""
        match = _MONTH.fullmatch(text) if isinstance(text, str) else None
        if match is None:
            raise ValueError(f"expected a YYYY-MM month, got {text!r}")
        return cls(int(match["year"]), int(match["month"]))

    @classmethod
    def of(cls, day: date) -> "Month":
        return cls(day.year, day.month)

    def isoformat(self) -> str:
        return f"{self.year:04d}-{self.month:02d}"

    def shifted(self, months: int) -> "Month":
        """The month ``months`` later (earlier when negative)."""
        index = self.year * 12 + self.month - 1 + months
        return Month(index // 12, index % 12 + 1)

    def first_day(self) -> date:
        return date(self.year, self.month, 1)

    def last_day(self) -> date:
        following = self.shifted(1)
        return date(following.year, following.month, 1) - timedelta(days=1)


def months_ending_within(start: date, end: date) -> tuple[Month, ...]:
    """The months whose last day lies from ``start`` to ``end``, both included, ascending."""
    months = []
    current = Month.of(start)
    while current.last_day() <= end:
        if current.last_day() >= start:
            months.append(current)
        current = current.shifted(1)
    return tuple(months)


def finra_due(month: Month) -> date:
    """The day FINRA's balances of ``month`` are due: the 15th of the month after it."""
    following = month.shifted(1)
    return date(following.year, following.month, FINRA_DUE_DAY)


def week_of(day: date) -> date:
    """The Tuesday that names the week (Monday to Sunday) holding ``day``."""
    return day + timedelta(days=TUESDAY - day.weekday())


def is_week(day: date) -> bool:
    """Whether ``day`` names a week: a Tuesday."""
    return day.weekday() == TUESDAY


def weeks_within(start: date, end: date) -> tuple[date, ...]:
    """The weeks whose Tuesday lies from ``start`` to ``end``, both included, ascending."""
    first = start + timedelta(days=(TUESDAY - start.weekday()) % 7)
    days = []
    while first <= end:
        days.append(first)
        first += WEEK
    return tuple(days)


def weeks_ending(week: date, count: int) -> tuple[date, ...]:
    """The ``count`` consecutive weeks ending with ``week``, ascending."""
    if not is_week(week):
        raise ValueError(f"{week} does not name a week (a Tuesday)")
    return tuple(week - WEEK * offset for offset in range(count - 1, -1, -1))


def cftc_release(week: date) -> datetime:
    """When the CFTC report of ``week`` is due: its Friday, 15:30 New York time."""
    if not is_week(week):
        raise ValueError(f"{week} does not name a week (a Tuesday)")
    return to_eastern(datetime.combine(week + timedelta(days=3), CFTC_RELEASE, tzinfo=NEW_YORK))


def week_days(week: date) -> tuple[date, date]:
    """The Monday and the Sunday of ``week``."""
    if not is_week(week):
        raise ValueError(f"{week} does not name a week (a Tuesday)")
    return week - timedelta(days=1), week + timedelta(days=5)


def sessions_within(start: date, end: date) -> tuple[date, ...]:
    """The XNYS sessions from ``start`` to ``end``, both included, ascending: those the calendar
    the domain uses knows (from 2000-01-03)."""
    return sessions_between(start, end)


def cboe_due(session: date) -> datetime:
    """When the VIX and the SKEW of ``session`` are due: a quarter of an hour after its XNYS close
    (16:15 New York time on a full day), when Cboe ends the day's calculation of the VIX."""
    return to_eastern(session_close(session) + CBOE_SETTLE)


def cboe_is_due(session: date, at: datetime) -> bool:
    """Whether the VIX and the SKEW of ``session`` are due at ``at``; only a session of ``at``'s
    New York day needs its close looked up."""
    day = to_eastern(at, "at").date()
    return session < day or (session == day and cboe_due(session) <= at)
