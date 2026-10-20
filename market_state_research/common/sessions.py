"""XNYS cash sessions: opens, closes, completed-session resolution, closed periods,
neighbours, spans and windows.

Trading days, holidays, early closes and daylight-saving transitions come from the
``exchange-calendars`` XNYS calendar. Freshness follows exchange closes, never local
midnight or elapsed 24-hour periods. Every returned instant is New York time with a
fixed offset (see ``times``).

Domains work as of the latest completed session. A source's end-of-day values of a
completed session may be read at any time; a value that is live is as of a completed
session only when read while XNYS is closed, inside that session's ``ClosedPeriod``.
"""

from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from functools import cache
from typing import Literal

import exchange_calendars
import pandas as pd

from .times import NEW_YORK, et_isoformat, require_aware, to_eastern

EXCHANGE = "XNYS"
MarketState = Literal["closed", "trading"]
# XNYS sessions are generated from exchange rules. Fixed bounds keep results independent
# of the host clock; building the calendar once costs about 0.2 s per process.
FIRST_SUPPORTED_DATE = date(2000, 1, 1)
LAST_SUPPORTED_DATE = date(2099, 12, 31)


@cache
def _calendar() -> exchange_calendars.ExchangeCalendar:
    return exchange_calendars.get_calendar(
        EXCHANGE, start=FIRST_SUPPORTED_DATE.isoformat(), end=LAST_SUPPORTED_DATE.isoformat()
    )


@cache
def _sessions() -> tuple[date, ...]:
    """Every session of the supported calendar, in order, as plain dates."""
    return tuple(session.date() for session in _calendar().sessions)


def _check_supported(day: date) -> None:
    calendar = _calendar()
    first, last = calendar.first_session.date(), calendar.last_session.date()
    if not first <= day <= last:
        raise ValueError(f"{day} is outside the supported XNYS calendar range ({first} to {last})")


def is_session(day: date) -> bool:
    """Whether ``day`` is an XNYS cash session."""
    _check_supported(day)
    return bool(_calendar().is_session(pd.Timestamp(day)))


def session_open(session: date) -> datetime:
    """New York open of an XNYS session."""
    if not is_session(session):
        raise ValueError(f"{session} is not an XNYS trading session")
    opened: datetime = _calendar().session_open(pd.Timestamp(session)).to_pydatetime()
    return to_eastern(opened)


def session_close(session: date) -> datetime:
    """New York close of an XNYS session, including early closes."""
    if not is_session(session):
        raise ValueError(f"{session} is not an XNYS trading session")
    close: datetime = _calendar().session_close(pd.Timestamp(session)).to_pydatetime()
    return to_eastern(close)


def completed_session(now: datetime, settle: timedelta = timedelta(0)) -> date:
    """Latest XNYS session whose close plus ``settle`` is at or before ``now``.

    Weekends, holidays and a session that is still open (or closed less than ``settle``
    ago) resolve to the preceding completed session. ``settle`` is elapsed time, so it
    spans a daylight-saving change exactly.
    """
    require_aware(now)
    if settle < timedelta(0):
        raise ValueError("settle must not be negative")
    _check_supported(now.astimezone(NEW_YORK).date())
    latest = to_eastern(to_eastern(now, "now") - settle)
    sessions = _sessions()
    # Only the last session on or before latest's New York date can still be open: every
    # earlier one closed on an earlier day, so at most two sessions are examined.
    position = bisect_right(sessions, latest.date()) - 1
    while position >= 0:
        if session_close(sessions[position]) <= latest:
            return sessions[position]
        position -= 1
    raise ValueError(f"no completed XNYS session before {et_isoformat(latest)}")


def session_window(end: date, lookback: int) -> tuple[date, ...]:
    """The ``lookback`` consecutive XNYS sessions ending with session ``end``."""
    if isinstance(lookback, bool) or not isinstance(lookback, int) or lookback < 1:
        raise ValueError("lookback must be a positive number of trading sessions")
    if not is_session(end):
        raise ValueError(f"{end} is not an XNYS trading session")
    calendar = _calendar()
    sessions: pd.DatetimeIndex | tuple[()] = ()
    # A window longer than the whole calendar cannot fit; checking first also keeps huge
    # integers away from exchange-calendars' fixed-width index arithmetic.
    if lookback <= len(calendar.sessions):
        try:
            sessions = calendar.sessions_window(pd.Timestamp(end), -lookback)
        except (ValueError, OverflowError):
            sessions = ()
    if len(sessions) != lookback:
        raise ValueError(
            f"a {lookback}-session window ending {end} starts before the supported calendar range"
        )
    return tuple(session.date() for session in sessions)


def sessions_between(start: date, end: date) -> tuple[date, ...]:
    """The XNYS sessions from ``start`` to ``end``, both included, ascending.

    Only the sessions of the supported calendar range are known: a span reaching beyond it
    holds the sessions inside it, and one wholly outside it, or ending before it starts,
    holds none.
    """
    sessions = _sessions()
    return sessions[bisect_left(sessions, start) : bisect_right(sessions, end)]


def next_session(day: date) -> date:
    """The first XNYS session strictly after ``day``, which need not be a session."""
    _check_supported(day)
    sessions = _sessions()
    position = bisect_right(sessions, day)
    if position == len(sessions):
        raise ValueError(f"no XNYS session after {day} in the supported calendar range")
    return sessions[position]


def previous_session(day: date) -> date:
    """The last XNYS session strictly before ``day``, which need not be a session."""
    _check_supported(day)
    sessions = _sessions()
    position = bisect_left(sessions, day)
    if position == 0:
        raise ValueError(f"no XNYS session before {day} in the supported calendar range")
    return sessions[position - 1]


@dataclass(frozen=True)
class ClosedPeriod:
    """XNYS closed after ``session``: from its close (inclusive) to the next session's open
    (exclusive), weekends and holidays included. A live value read inside it is as of
    ``session``."""

    session: date
    start: datetime  # the session's close, New York time with a fixed offset
    end: datetime  # the next session's open

    def __contains__(self, moment: datetime) -> bool:
        return self.start <= to_eastern(moment, "moment") < self.end


@dataclass(frozen=True)
class MarketStatus:
    """Whether XNYS is closed or a session is trading at one instant.

    ``period`` is the closed period that contains the instant, or while a session is
    trading the one that session's close will start.
    """

    status: MarketState
    period: ClosedPeriod


def closed_period(session: date) -> ClosedPeriod:
    """The closed period after ``session``: from its close to the next session's open."""
    start = session_close(session)
    return ClosedPeriod(session, start, session_open(next_session(session)))


def closed_period_at(moment: datetime) -> ClosedPeriod | None:
    """The closed period that contains ``moment``, or None while a session is trading (from
    its open, inclusive, to its close, exclusive)."""
    require_aware(moment, "moment")
    period = closed_period(completed_session(moment))
    return period if moment in period else None


def market_status(now: datetime) -> MarketStatus:
    """Whether XNYS is closed at ``now`` (and since which close) or a session is trading."""
    period = closed_period(completed_session(now))
    if now in period:
        return MarketStatus("closed", period)
    # The completed session's closed period has ended, so the next session is trading.
    return MarketStatus("trading", closed_period(next_session(period.session)))
