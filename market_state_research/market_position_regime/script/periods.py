"""The dates the three sources publish by, and when each document is due.

FINRA dates its balances by month (``Month``, as of the month's last business day), the CFTC
its positions by week, and the Fed's Financial Accounts (Z.1, through FRED) its market values
by quarter end. The CFTC reports one week's positions as of its Tuesday, or as of its Monday
when the Tuesday is a holiday, so a week is named by its Tuesday (``week_of``), whatever day
its report is dated. A document is due from the earliest time its source publishes it: a
FINRA month from the 15th of the month after it (FINRA publishes in the third week); a CFTC
week from its Friday at 15:30 New York time; a Z.1 quarter from the 15th of the third month
after its end (the Fed publishes in the second week of that month). A due document the
source has not published yet is ``pending`` after a ``fetch``. Every function here is pure.
"""

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Final

from market_state_research.common.times import NEW_YORK, to_eastern

FINRA_DUE_DAY: Final = 15  # of the month after the month
Z1_DUE_DAY: Final = 15  # of the third month after the quarter end
CFTC_RELEASE: Final = time(15, 30)  # New York time, on the week's Friday
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


def is_quarter_end(day: date) -> bool:
    return day.month in (3, 6, 9, 12) and day == Month.of(day).last_day()


def quarter_end_of(month: Month) -> date:
    """The latest quarter end on or before ``month``'s last day: the market value a month's
    balances are divided by."""
    return month.shifted(-(month.month % 3)).last_day()


def quarter_ends_from(start: date, end: date) -> tuple[date, ...]:
    """The quarter ends from ``start`` to ``end``, both included, ascending."""
    ends = []
    current = Month.of(start)
    while current.first_day() <= end:
        day = current.last_day()
        if current.month % 3 == 0 and start <= day <= end:
            ends.append(day)
        current = current.shifted(1)
    return tuple(ends)


def z1_due(quarter_end: date) -> date:
    """The day the Z.1 values of ``quarter_end`` are due: the 15th of the third month after it."""
    if not is_quarter_end(quarter_end):
        raise ValueError(f"{quarter_end} is not a quarter end")
    later = Month.of(quarter_end).shifted(3)
    return date(later.year, later.month, Z1_DUE_DAY)


def observation_date(quarter_end: date) -> date:
    """FRED's date of a quarterly value as of ``quarter_end``: the quarter's first day."""
    if not is_quarter_end(quarter_end):
        raise ValueError(f"{quarter_end} is not a quarter end")
    return Month.of(quarter_end).shifted(-2).first_day()


def quarter_end_at(observation: date) -> date:
    """The quarter end of FRED's quarterly observation dated ``observation`` (a quarter's first day)."""
    if observation.day != 1 or observation.month not in (1, 4, 7, 10):
        raise ValueError(f"{observation} is not the first day of a quarter")
    return Month.of(observation).shifted(2).last_day()
