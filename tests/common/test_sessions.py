"""XNYS sessions: opens, closes, completed sessions, closed periods, neighbouring sessions and
look-back windows.

Expected values come from the published NYSE holiday and early-close schedule, written out
below independently of ``exchange-calendars``. Instants are written in New York time with
fixed EDT/EST offsets and compared as aware datetimes; every returned instant must itself
be fixed-offset New York time.
"""

from datetime import UTC, date, datetime, time, timedelta, timezone
from decimal import Decimal
from itertools import pairwise
from zoneinfo import ZoneInfo

import pytest

from market_state_research.common.sessions import (
    EXCHANGE,
    FIRST_SUPPORTED_DATE,
    LAST_SUPPORTED_DATE,
    ClosedPeriod,
    MarketStatus,
    closed_period,
    closed_period_at,
    completed_session,
    is_session,
    market_status,
    next_session,
    previous_session,
    session_close,
    session_open,
    session_window,
    sessions_between,
)

from .support import (
    EDT,
    END,
    EST,
    FIRST_SESSION,
    FRIDAY_CLOSE,
    LAST_SESSION,
    MICROSECOND,
    MONDAY,
    MONDAY_CLOSE,
    NEW_YORK,
    NOW,
    OffsetlessZone,
    edt,
    est,
)

# Published NYSE schedule from SCHEDULE_START to SCHEDULE_END: full-day closures and the
# 13:00 New York early closes. Every other weekday is a session that closes at 16:00.
SCHEDULE_START, SCHEDULE_END = date(2025, 7, 1), date(2026, 12, 31)
HOLIDAYS = {
    date(2025, 7, 4): "Independence Day",
    date(2025, 9, 1): "Labor Day",
    date(2025, 11, 27): "Thanksgiving Day",
    date(2025, 12, 25): "Christmas Day",
    date(2026, 1, 1): "New Year's Day",
    date(2026, 1, 19): "Martin Luther King Jr. Day",
    date(2026, 2, 16): "Washington's Birthday",
    date(2026, 4, 3): "Good Friday",
    date(2026, 5, 25): "Memorial Day",
    date(2026, 6, 19): "Juneteenth",
    date(2026, 7, 3): "Independence Day (observed)",
    date(2026, 9, 7): "Labor Day",
    date(2026, 11, 26): "Thanksgiving Day",
    date(2026, 12, 25): "Christmas Day",
}
EARLY_CLOSES = frozenset(
    {date(2025, 7, 3), date(2025, 11, 28), date(2025, 12, 24), date(2026, 11, 27), date(2026, 12, 24)}
)
# Daylight-saving periods of the schedule: (first EDT day, first EST day after it).
DAYLIGHT = [(date(2025, 3, 9), date(2025, 11, 2)), (date(2026, 3, 8), date(2026, 11, 1))]

NON_SESSIONS = [
    pytest.param(date(2026, 10, 3), id="saturday"),
    pytest.param(date(2026, 10, 4), id="sunday"),
    pytest.param(date(2026, 9, 7), id="labor-day"),
    pytest.param(date(2026, 7, 3), id="observed-independence-day"),
    pytest.param(date(2026, 4, 3), id="good-friday"),
    pytest.param(date(2026, 11, 26), id="thanksgiving"),
    pytest.param(date(2026, 12, 25), id="christmas"),
]


def calendar_days(start: date, end: date) -> list[date]:
    return [start + timedelta(days=offset) for offset in range((end - start).days + 1)]


def published_sessions() -> list[date]:
    days = calendar_days(SCHEDULE_START, SCHEDULE_END)
    return [day for day in days if day.weekday() < 5 and day not in HOLIDAYS]


def offset(day: date) -> timezone:
    return EDT if any(start <= day < end for start, end in DAYLIGHT) else EST


def published_open(session: date) -> datetime:
    """09:30 New York."""
    return datetime.combine(session, time(9, 30), tzinfo=offset(session))


def published_close(session: date) -> datetime:
    """16:00 New York, or 13:00 on an early close."""
    return datetime.combine(
        session, time(13) if session in EARLY_CLOSES else time(16), tzinfo=offset(session)
    )


def assert_eastern(moment: datetime, expected: datetime) -> None:
    """``moment`` is fixed-offset New York time equal to ``expected``, offset included."""
    assert type(moment) is datetime
    assert type(moment.tzinfo) is timezone
    assert moment.tzname() == expected.tzname()
    assert moment.utcoffset() == expected.utcoffset()
    assert moment.fold == 0
    assert moment == expected
    assert moment.isoformat() == expected.isoformat()


def assert_completed(now: datetime, expected: date, settle: timedelta = timedelta(0)) -> None:
    """The completed session at ``now``, read in New York time and in UTC."""
    for reading in (now, now.astimezone(UTC)):
        resolved = completed_session(reading, settle)
        assert type(resolved) is date
        assert resolved == expected, reading.isoformat()


def test_the_calendar_is_xnys_from_2000_to_2099():
    assert EXCHANGE == "XNYS"
    assert FIRST_SUPPORTED_DATE.isoformat() == "2000-01-01"
    assert LAST_SUPPORTED_DATE.isoformat() == "2099-12-31"


# --- session_window -----------------------------------------------------------------------------


@pytest.mark.parametrize("lookback", [1, 5, 50, 260], ids=lambda lookback: f"{lookback}-sessions")
def test_window_holds_exactly_lookback_consecutive_sessions_ending_at_end(lookback):
    window = session_window(END, lookback)

    assert isinstance(window, tuple)
    assert len(window) == lookback
    assert window[-1] == END
    assert all(type(day) is date for day in window)
    assert all(earlier < later for earlier, later in pairwise(window))
    assert all(day.weekday() < 5 for day in window)
    assert not set(window) & HOLIDAYS.keys()
    published = published_sessions()
    assert list(window) == published[: published.index(END) + 1][-lookback:]


@pytest.mark.parametrize(
    ("end", "lookback", "start", "skipped_holidays"),
    [
        pytest.param(END, 1, END, [], id="1-session"),
        pytest.param(END, 5, date(2026, 9, 28), [], id="5-sessions"),
        pytest.param(END, 50, date(2026, 7, 24), [date(2026, 9, 7)], id="50-sessions"),
        pytest.param(
            END,
            260,
            date(2025, 9, 22),
            [
                date(2025, 11, 27),
                date(2025, 12, 25),
                date(2026, 1, 1),
                date(2026, 1, 19),
                date(2026, 2, 16),
                date(2026, 4, 3),
                date(2026, 5, 25),
                date(2026, 6, 19),
                date(2026, 7, 3),
                date(2026, 9, 7),
            ],
            id="260-sessions",
        ),
        pytest.param(
            date(2026, 12, 31),
            260,
            date(2025, 12, 18),
            [
                date(2025, 12, 25),
                date(2026, 1, 1),
                date(2026, 1, 19),
                date(2026, 2, 16),
                date(2026, 4, 3),
                date(2026, 5, 25),
                date(2026, 6, 19),
                date(2026, 7, 3),
                date(2026, 9, 7),
                date(2026, 11, 26),
                date(2026, 12, 25),
            ],
            id="260-sessions-to-year-end",
        ),
    ],
)
def test_window_skips_exactly_the_weekday_holidays_in_its_span(end, lookback, start, skipped_holidays):
    window = session_window(end, lookback)

    assert (window[0], window[-1], len(window)) == (start, end, lookback)
    weekdays = [day for day in calendar_days(start, end) if day.weekday() < 5]
    # Early closes (e.g. 2025-11-28, 2026-12-24) are sessions, so only holidays are skipped.
    assert [day for day in weekdays if day not in window] == skipped_holidays


@pytest.mark.parametrize(
    ("end", "lookback", "expected"),
    [
        pytest.param(MONDAY, 2, (END, MONDAY), id="weekend"),
        pytest.param(date(2026, 9, 8), 2, (date(2026, 9, 4), date(2026, 9, 8)), id="labor-day"),
        pytest.param(
            date(2026, 7, 6),
            3,
            (date(2026, 7, 1), date(2026, 7, 2), date(2026, 7, 6)),
            id="observed-independence-day",
        ),
        pytest.param(date(2026, 4, 6), 2, (date(2026, 4, 2), date(2026, 4, 6)), id="good-friday"),
        pytest.param(
            date(2026, 11, 30),
            4,
            (date(2026, 11, 24), date(2026, 11, 25), date(2026, 11, 27), date(2026, 11, 30)),
            id="thanksgiving-and-early-close",
        ),
        pytest.param(
            date(2026, 12, 28),
            3,
            (date(2026, 12, 23), date(2026, 12, 24), date(2026, 12, 28)),
            id="christmas-and-early-close",
        ),
        pytest.param(
            date(2026, 1, 2),
            3,
            (date(2025, 12, 30), date(2025, 12, 31), date(2026, 1, 2)),
            id="new-year",
        ),
    ],
)
def test_window_steps_over_weekends_and_holidays(end, lookback, expected):
    assert session_window(end, lookback) == expected


def test_shorter_windows_are_suffixes_of_longer_ones():
    longest = session_window(END, 260)

    for lookback in (1, 5, 50, 259):
        assert session_window(END, lookback) == longest[-lookback:]
    assert session_window(longest[-2], 259) == longest[:-1]


def test_window_after_the_next_close_drops_the_oldest_session_and_adds_the_new_one():
    as_of = completed_session(MONDAY_CLOSE)
    window = session_window(as_of, 50)

    assert as_of == MONDAY
    assert window[-1] == MONDAY
    assert window[:-1] == session_window(END, 50)[1:]


@pytest.mark.parametrize(
    "lookback",
    [
        pytest.param(0, id="zero"),
        pytest.param(-1, id="negative"),
        pytest.param(-50, id="negative-50"),
        pytest.param(True, id="bool-true"),
        pytest.param(False, id="bool-false"),
        pytest.param(2.5, id="float"),
        pytest.param(50.0, id="integral-float"),
        pytest.param(Decimal(50), id="decimal"),
        pytest.param("50", id="string"),
        pytest.param(None, id="none"),
    ],
)
def test_window_rejects_a_lookback_that_is_not_a_positive_int(lookback):
    with pytest.raises(ValueError, match="^lookback must be a positive number of trading sessions$"):
        session_window(END, lookback)


@pytest.mark.parametrize("lookback", [1, 50], ids=["1-session", "50-sessions"])
@pytest.mark.parametrize("end", NON_SESSIONS)
def test_window_end_must_be_a_session(end, lookback):
    with pytest.raises(ValueError, match=f"^{end} is not an XNYS trading session$"):
        session_window(end, lookback)


@pytest.mark.parametrize(
    ("end", "lookback"),
    [
        pytest.param(date(2000, 1, 10), 50, id="50-sessions-to-2000-01-10"),
        pytest.param(date(2000, 1, 10), 7, id="one-session-too-many"),
        pytest.param(FIRST_SESSION, 2, id="before-the-first-session"),
        pytest.param(END, 10_000, id="10000-sessions"),
        pytest.param(END, 2**63, id="2pow63-sessions"),
        pytest.param(END, 10**20, id="1e20-sessions"),
    ],
)
def test_window_cannot_start_before_the_supported_calendar(end, lookback):
    with pytest.raises(ValueError) as caught:
        session_window(end, lookback)
    assert str(caught.value) == (
        f"a {lookback}-session window ending {end} starts before the supported calendar range"
    )


def test_window_may_start_on_the_first_supported_session():
    assert session_window(FIRST_SESSION, 1) == (FIRST_SESSION,)
    assert session_window(date(2000, 1, 10), 6) == (
        date(2000, 1, 3),
        date(2000, 1, 4),
        date(2000, 1, 5),
        date(2000, 1, 6),
        date(2000, 1, 7),
        date(2000, 1, 10),
    )


def test_a_window_may_span_the_whole_supported_calendar_but_no_more():
    supported = tuple(day for day in calendar_days(FIRST_SESSION, LAST_SESSION) if is_session(day))

    assert session_window(LAST_SESSION, len(supported)) == supported
    with pytest.raises(ValueError, match="starts before the supported calendar range"):
        session_window(LAST_SESSION, len(supported) + 1)


# --- is_session and the supported range ---------------------------------------------------------


def test_is_session_follows_the_published_nyse_schedule():
    answers = {day: is_session(day) for day in calendar_days(SCHEDULE_START, SCHEDULE_END)}

    assert all(type(answer) is bool for answer in answers.values())
    assert [day for day, answer in answers.items() if answer] == published_sessions()


@pytest.mark.parametrize("day", NON_SESSIONS)
def test_weekends_and_holidays_are_not_sessions(day):
    assert is_session(day) is False


@pytest.mark.parametrize(
    ("closed", "now", "completed", "reopened", "window"),
    [
        pytest.param(
            [date(2001, 9, 11), date(2001, 9, 12), date(2001, 9, 13), date(2001, 9, 14)],
            edt(2001, 9, 14, 18),
            date(2001, 9, 10),
            date(2001, 9, 17),
            (date(2001, 9, 10), date(2001, 9, 17)),
            id="september-11",
        ),
        pytest.param(
            [date(2012, 10, 29), date(2012, 10, 30)],
            edt(2012, 10, 30, 18),
            date(2012, 10, 26),
            date(2012, 10, 31),
            (date(2012, 10, 26), date(2012, 10, 31)),
            id="hurricane-sandy",
        ),
        pytest.param(
            [date(2025, 1, 9)],
            est(2025, 1, 9, 17),
            date(2025, 1, 8),
            date(2025, 1, 10),
            (date(2025, 1, 8), date(2025, 1, 10)),
            id="national-day-of-mourning-2025",
        ),
    ],
)
def test_unscheduled_weekday_closures_are_not_sessions(closed, now, completed, reopened, window):
    assert all(day.weekday() < 5 and is_session(day) is False for day in closed)
    assert_completed(now, completed)
    assert session_window(reopened, 2) == window
    assert next_session(completed) == reopened
    assert previous_session(reopened) == completed
    assert all(next_session(day) == reopened and previous_session(day) == completed for day in closed)


QUERIES = [
    pytest.param(is_session, id="is_session"),
    pytest.param(session_open, id="session_open"),
    pytest.param(session_close, id="session_close"),
    pytest.param(lambda day: session_window(day, 1), id="session_window"),
    pytest.param(next_session, id="next_session"),
    pytest.param(previous_session, id="previous_session"),
    pytest.param(closed_period, id="closed_period"),
]


@pytest.mark.parametrize("query", QUERIES)
@pytest.mark.parametrize(
    "day",
    [
        pytest.param(date(1999, 12, 31), id="1999-12-31"),
        pytest.param(date(1999, 12, 30), id="1999-12-30-a-trading-day"),
        pytest.param(date(2000, 1, 2), id="2000-01-02-the-day-before-the-first-session"),
        pytest.param(date(2100, 1, 1), id="2100-01-01-the-day-after-the-last-session"),
        pytest.param(date(2100, 1, 4), id="2100-01-04-a-monday"),
    ],
)
def test_dates_outside_the_supported_calendar_are_rejected(query, day):
    with pytest.raises(ValueError) as caught:
        query(day)
    assert (
        str(caught.value) == f"{day} is outside the supported XNYS calendar range (2000-01-03 to 2099-12-31)"
    )


def test_supported_range_begins_at_the_first_session_of_2000():
    assert is_session(FIRST_SESSION) is True
    # The message names the effective range, which starts at the first session.
    with pytest.raises(ValueError, match=r"outside the supported XNYS calendar range \(2000-01-03 to "):
        is_session(FIRST_SESSION - timedelta(days=1))


# --- session_open and session_close -------------------------------------------------------------


@pytest.mark.parametrize(
    ("session", "expected"),
    [
        pytest.param(END, edt(2026, 10, 2, 9, 30), id="friday-edt"),
        pytest.param(date(2026, 3, 6), est(2026, 3, 6, 9, 30), id="last-est-friday-before-dst"),
        pytest.param(date(2026, 3, 9), edt(2026, 3, 9, 9, 30), id="first-edt-monday"),
        pytest.param(date(2026, 10, 30), edt(2026, 10, 30, 9, 30), id="last-edt-friday"),
        pytest.param(date(2026, 11, 2), est(2026, 11, 2, 9, 30), id="first-est-monday"),
        pytest.param(date(2026, 11, 27), est(2026, 11, 27, 9, 30), id="early-close-day-opens-as-usual"),
        pytest.param(FIRST_SESSION, est(2000, 1, 3, 9, 30), id="first-supported-session"),
        pytest.param(LAST_SESSION, est(2099, 12, 31, 9, 30), id="last-supported-session"),
    ],
)
def test_session_open_is_the_new_york_open_instant(session, expected):
    assert_eastern(session_open(session), expected)


def test_every_session_opens_at_09_30_new_york():
    sessions = published_sessions()
    opens = {session: session_open(session) for session in sessions}

    assert {session: value.isoformat() for session, value in opens.items()} == {
        session: published_open(session).isoformat() for session in sessions
    }
    assert all(type(value.tzinfo) is timezone for value in opens.values())


@pytest.mark.parametrize(
    ("session", "expected"),
    [
        pytest.param(END, FRIDAY_CLOSE, id="friday-edt"),
        pytest.param(MONDAY, MONDAY_CLOSE, id="monday-edt"),
        pytest.param(date(2026, 3, 6), est(2026, 3, 6, 16), id="last-est-friday-before-dst"),
        pytest.param(date(2026, 3, 9), edt(2026, 3, 9, 16), id="first-edt-monday"),
        pytest.param(date(2026, 10, 30), edt(2026, 10, 30, 16), id="last-edt-friday"),
        pytest.param(date(2026, 11, 2), est(2026, 11, 2, 16), id="first-est-monday"),
        pytest.param(date(2026, 7, 2), edt(2026, 7, 2, 16), id="full-day-before-observed-holiday"),
        pytest.param(date(2026, 11, 27), est(2026, 11, 27, 13), id="early-close-after-thanksgiving"),
        pytest.param(date(2026, 12, 24), est(2026, 12, 24, 13), id="early-close-christmas-eve"),
        pytest.param(date(2025, 7, 3), edt(2025, 7, 3, 13), id="early-close-in-edt"),
        # Before 2007 DST began on the first Sunday of April and ended on the last Sunday of October.
        pytest.param(date(2006, 3, 31), est(2006, 3, 31, 16), id="pre-2007-rules-late-march-est"),
        pytest.param(date(2006, 10, 30), est(2006, 10, 30, 16), id="pre-2007-rules-late-october-est"),
        pytest.param(FIRST_SESSION, est(2000, 1, 3, 16), id="first-supported-session"),
        pytest.param(LAST_SESSION, est(2099, 12, 31, 16), id="last-supported-session"),
    ],
)
def test_session_close_is_the_new_york_close_instant(session, expected):
    assert_eastern(session_close(session), expected)


def test_every_session_closes_at_16_00_new_york_or_13_00_on_early_closes():
    sessions = published_sessions()
    closes = {session: session_close(session) for session in sessions}

    assert {session: value.isoformat() for session, value in closes.items()} == {
        session: published_close(session).isoformat() for session in sessions
    }
    assert all(type(value.tzinfo) is timezone and value.fold == 0 for value in closes.values())
    assert all(session_open(session) < close for session, close in closes.items())


@pytest.mark.parametrize("query", [session_open, session_close], ids=["session_open", "session_close"])
@pytest.mark.parametrize("day", NON_SESSIONS)
def test_opens_and_closes_exist_only_for_sessions(query, day):
    with pytest.raises(ValueError, match=f"^{day} is not an XNYS trading session$"):
        query(day)


# --- next_session and previous_session ----------------------------------------------------------


@pytest.mark.parametrize(
    ("day", "following", "preceding"),
    [
        pytest.param(END, MONDAY, date(2026, 10, 1), id="friday-session"),
        pytest.param(date(2026, 10, 3), MONDAY, END, id="saturday"),
        pytest.param(date(2026, 10, 4), MONDAY, END, id="sunday"),
        pytest.param(MONDAY, date(2026, 10, 6), END, id="monday-session"),
        pytest.param(date(2026, 9, 4), date(2026, 9, 8), date(2026, 9, 3), id="friday-before-labor-day"),
        pytest.param(date(2026, 9, 7), date(2026, 9, 8), date(2026, 9, 4), id="labor-day"),
        pytest.param(date(2026, 7, 2), date(2026, 7, 6), date(2026, 7, 1), id="before-observed-holiday"),
        pytest.param(date(2026, 11, 26), date(2026, 11, 27), date(2026, 11, 25), id="thanksgiving"),
        pytest.param(date(2026, 11, 27), date(2026, 11, 30), date(2026, 11, 25), id="early-close"),
        pytest.param(date(2026, 12, 24), date(2026, 12, 28), date(2026, 12, 23), id="christmas-eve"),
        pytest.param(date(2026, 12, 31), date(2027, 1, 4), date(2026, 12, 30), id="new-year"),
        pytest.param(date(2026, 3, 6), date(2026, 3, 9), date(2026, 3, 5), id="spring-forward-weekend"),
        pytest.param(date(2026, 11, 1), date(2026, 11, 2), date(2026, 10, 30), id="fall-back-sunday"),
    ],
)
def test_neighbouring_sessions_are_strictly_after_and_before_the_day(day, following, preceding):
    assert type(next_session(day)) is date
    assert type(previous_session(day)) is date
    assert next_session(day) == following
    assert previous_session(day) == preceding


def test_neighbouring_sessions_follow_the_published_schedule_for_every_day():
    sessions = published_sessions()
    for day in calendar_days(sessions[0], sessions[-1] - timedelta(days=1)):
        assert next_session(day) == min(session for session in sessions if session > day), day
    for day in calendar_days(sessions[0] + timedelta(days=1), sessions[-1]):
        assert previous_session(day) == max(session for session in sessions if session < day), day
    for earlier, later in pairwise(sessions):
        assert (next_session(earlier), previous_session(later)) == (later, earlier)


def test_neighbouring_sessions_stop_at_the_ends_of_the_supported_calendar():
    assert next_session(date(2099, 12, 30)) == LAST_SESSION
    assert previous_session(date(2000, 1, 4)) == FIRST_SESSION
    with pytest.raises(ValueError) as caught:
        next_session(LAST_SESSION)
    assert str(caught.value) == "no XNYS session after 2099-12-31 in the supported calendar range"
    with pytest.raises(ValueError) as caught:
        previous_session(FIRST_SESSION)
    assert str(caught.value) == "no XNYS session before 2000-01-03 in the supported calendar range"


# --- sessions_between ---------------------------------------------------------------------------


def test_the_sessions_between_two_days_follow_the_published_schedule():
    found = sessions_between(SCHEDULE_START, SCHEDULE_END)
    assert type(found) is tuple and all(type(day) is date for day in found)
    assert list(found) == published_sessions()
    assert sessions_between(date(2026, 9, 4), date(2026, 9, 8)) == (date(2026, 9, 4), date(2026, 9, 8))
    assert sessions_between(date(2026, 9, 5), date(2026, 9, 7)) == ()  # a weekend and Labor Day
    assert sessions_between(END, END) == (END,)
    assert sessions_between(MONDAY, END) == ()  # the end before the start


def test_a_span_beyond_the_supported_calendar_holds_only_the_sessions_inside_it():
    assert sessions_between(date(1997, 1, 1), date(2000, 1, 5)) == (
        FIRST_SESSION,
        date(2000, 1, 4),
        date(2000, 1, 5),
    )
    assert sessions_between(date(2099, 12, 30), date(2100, 1, 31)) == (date(2099, 12, 30), LAST_SESSION)
    assert sessions_between(date(1990, 1, 2), date(1999, 12, 31)) == ()
    whole = sessions_between(FIRST_SUPPORTED_DATE, LAST_SUPPORTED_DATE)
    assert (whole[0], whole[-1]) == (FIRST_SESSION, LAST_SESSION)
    assert whole == session_window(LAST_SESSION, len(whole))


# --- completed_session --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        pytest.param(NOW, END, id="friday-evening"),
        pytest.param(FRIDAY_CLOSE, END, id="friday-at-close"),
        pytest.param(FRIDAY_CLOSE - MICROSECOND, date(2026, 10, 1), id="friday-1us-before-close"),
        pytest.param(edt(2026, 10, 2, 9, 30), date(2026, 10, 1), id="friday-at-open"),
        pytest.param(edt(2026, 10, 3, 11), END, id="saturday"),
        pytest.param(edt(2026, 10, 4, 19, 59), END, id="sunday"),
        pytest.param(edt(2026, 10, 5, 8), END, id="monday-before-open"),
        pytest.param(edt(2026, 10, 5, 15, 59, 59), END, id="monday-155959"),
        pytest.param(MONDAY_CLOSE - MICROSECOND, END, id="monday-1us-before-close"),
        pytest.param(edt(2026, 10, 5, 16), MONDAY, id="monday-1600-close-is-inclusive"),
        pytest.param(MONDAY_CLOSE + timedelta(seconds=1), MONDAY, id="monday-after-close"),
        pytest.param(edt(2026, 10, 6, 15, 59, 59), MONDAY, id="tuesday-before-close"),
    ],
)
def test_completed_session_is_the_latest_session_closed_at_or_before_now(now, expected):
    assert_completed(now, expected)


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        pytest.param(edt(2026, 7, 3, 17), date(2026, 7, 2), id="observed-independence-day"),
        pytest.param(edt(2026, 7, 5, 8), date(2026, 7, 2), id="independence-day-weekend"),
        pytest.param(edt(2026, 7, 6, 15, 59, 59), date(2026, 7, 2), id="next-monday-before-close"),
        pytest.param(edt(2026, 7, 6, 16), date(2026, 7, 6), id="next-monday-at-close"),
        pytest.param(edt(2026, 9, 7, 18), date(2026, 9, 4), id="labor-day"),
        pytest.param(edt(2026, 4, 3, 17), date(2026, 4, 2), id="good-friday"),
        pytest.param(est(2026, 11, 26, 17), date(2026, 11, 25), id="thanksgiving"),
        pytest.param(est(2026, 12, 25, 18), date(2026, 12, 24), id="christmas"),
        pytest.param(est(2027, 1, 1, 17), date(2026, 12, 31), id="new-year-2027"),
    ],
)
def test_completed_session_skips_holidays(now, expected):
    assert_completed(now, expected)


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        pytest.param(est(2026, 11, 27, 12, 59), date(2026, 11, 25), id="day-after-thanksgiving-1259"),
        pytest.param(
            est(2026, 11, 27, 13) - MICROSECOND, date(2026, 11, 25), id="day-after-thanksgiving-1us"
        ),
        pytest.param(est(2026, 11, 27, 13), date(2026, 11, 27), id="day-after-thanksgiving-1300"),
        pytest.param(est(2026, 11, 27, 15), date(2026, 11, 27), id="day-after-thanksgiving-afternoon"),
        pytest.param(est(2026, 12, 24, 12, 59, 59), date(2026, 12, 23), id="christmas-eve-before-close"),
        pytest.param(est(2026, 12, 24, 13), date(2026, 12, 24), id="christmas-eve-1300"),
        pytest.param(est(2026, 12, 28, 15, 59, 59), date(2026, 12, 24), id="next-monday-before-close"),
        pytest.param(est(2026, 12, 28, 16), date(2026, 12, 28), id="next-monday-at-close"),
    ],
)
def test_completed_session_honours_early_closes(now, expected):
    assert_completed(now, expected)


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        # The same UTC hour falls on either side of the close depending on the New York offset.
        pytest.param(est(2026, 3, 6, 15, 30), date(2026, 3, 5), id="est-friday-still-open-2030-utc"),
        pytest.param(est(2026, 3, 6, 16), date(2026, 3, 6), id="est-friday-closes-2100-utc"),
        pytest.param(edt(2026, 3, 9, 15, 59, 59), date(2026, 3, 6), id="edt-monday-open-1959-utc"),
        pytest.param(edt(2026, 3, 9, 16), date(2026, 3, 9), id="edt-monday-closes-2000-utc"),
        pytest.param(edt(2026, 10, 30, 16), date(2026, 10, 30), id="edt-friday-closes-2000-utc"),
        pytest.param(est(2026, 11, 2, 15, 30), date(2026, 10, 30), id="est-monday-still-open-2030-utc"),
        pytest.param(est(2026, 11, 2, 16), date(2026, 11, 2), id="est-monday-closes-2100-utc"),
    ],
)
def test_completed_session_follows_daylight_saving_time(now, expected):
    assert_completed(now, expected)


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        pytest.param(edt(2026, 10, 2, 23, 59), END, id="friday-2359-edt"),
        pytest.param(edt(2026, 10, 3, 0), END, id="saturday-0000-edt"),
        pytest.param(edt(2026, 10, 5, 21), MONDAY, id="monday-2100-edt-already-tuesday-in-utc"),
        pytest.param(edt(2026, 10, 5, 23, 59, 59), MONDAY, id="monday-235959-edt"),
        pytest.param(edt(2026, 10, 6, 0), MONDAY, id="tuesday-0000-edt"),
        pytest.param(est(2026, 11, 30, 23, 59, 59), date(2026, 11, 30), id="monday-235959-est"),
        pytest.param(est(2026, 12, 1, 0), date(2026, 11, 30), id="tuesday-0000-est"),
    ],
)
def test_completed_session_across_new_york_midnight(now, expected):
    assert_completed(now, expected)


def test_completed_session_switches_exactly_at_every_published_close():
    for previous, session in pairwise(published_sessions()):
        close = published_close(session)
        assert completed_session(close - MICROSECOND) == previous, close.isoformat()
        assert completed_session(close) == session, close.isoformat()
        assert completed_session(close.astimezone(UTC)) == session, close.isoformat()


@pytest.mark.parametrize(
    "zone",
    [
        pytest.param(UTC, id="UTC"),
        pytest.param(NEW_YORK, id="New_York"),
        pytest.param(ZoneInfo("Asia/Tokyo"), id="Tokyo"),
        pytest.param(ZoneInfo("Asia/Kathmandu"), id="Kathmandu-0545"),
        pytest.param(ZoneInfo("Pacific/Kiritimati"), id="Kiritimati-plus14"),
        pytest.param(timezone(timedelta(hours=-12)), id="fixed-minus12"),
    ],
)
@pytest.mark.parametrize(
    ("instant", "expected"),
    [
        pytest.param(NOW, END, id="friday-evening"),
        pytest.param(edt(2026, 10, 2, 23, 59), END, id="friday-2359-edt"),
        pytest.param(MONDAY_CLOSE - MICROSECOND, END, id="monday-before-close"),
        pytest.param(MONDAY_CLOSE, MONDAY, id="monday-at-close"),
        pytest.param(edt(2026, 10, 5, 21), MONDAY, id="monday-evening-already-tuesday-in-utc"),
        pytest.param(est(2026, 11, 27, 13), date(2026, 11, 27), id="early-close"),
    ],
)
def test_completed_session_depends_on_the_instant_not_the_clock_timezone(zone, instant, expected):
    local = instant.astimezone(zone)

    assert local == instant
    assert completed_session(local) == completed_session(instant) == expected


@pytest.mark.parametrize(
    ("zone", "offset"),
    [
        # POSIX TZ strings count hours west of UTC: "EAST-14" is UTC+14.
        pytest.param("EAST-14", timedelta(hours=14), id="host-plus14"),
        pytest.param("WEST+12", timedelta(hours=-12), id="host-minus12"),
    ],
)
def test_completed_session_uses_new_york_dates_not_the_host_time_zone(host_time_zone, zone, offset):
    host_time_zone(zone)
    assert NOW.astimezone().utcoffset() == offset

    assert_completed(NOW, END)
    # Near the calendar's ends the host's date and New York's can fall on opposite sides of a boundary.
    assert_completed(est(2099, 12, 31, 17), LAST_SESSION)
    for instant in (est(2000, 1, 2, 23, 59), est(2100, 1, 1, 0)):
        with pytest.raises(ValueError, match="outside the supported XNYS calendar range"):
            completed_session(instant)
    assert session_close(END).isoformat() == "2026-10-02T16:00:00-04:00"
    assert next_session(END) == MONDAY


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        pytest.param(datetime(2026, 10, 5, 15, 59, 59, tzinfo=NEW_YORK), END, id="monday-155959"),
        pytest.param(datetime(2026, 10, 5, 16, tzinfo=NEW_YORK), MONDAY, id="monday-1600"),
        pytest.param(datetime(2026, 3, 8, 2, 30, tzinfo=NEW_YORK), date(2026, 3, 6), id="spring-forward-gap"),
        pytest.param(datetime(2026, 11, 1, 1, 30, tzinfo=NEW_YORK), date(2026, 10, 30), id="fall-back-first"),
        pytest.param(
            datetime(2026, 11, 1, 1, 30, fold=1, tzinfo=NEW_YORK), date(2026, 10, 30), id="fall-back-second"
        ),
    ],
)
def test_completed_session_accepts_new_york_wall_clock_readings(now, expected):
    assert_completed(now, expected)


@pytest.mark.parametrize(
    "now",
    [
        pytest.param(NOW.replace(tzinfo=None), id="naive"),
        pytest.param(datetime(2026, 10, 3, tzinfo=OffsetlessZone()), id="tzinfo-without-offset"),
    ],
)
def test_completed_session_rejects_a_clock_without_a_utc_offset(now):
    with pytest.raises(ValueError, match="^now must include a timezone$"):
        completed_session(now)


@pytest.mark.parametrize(
    "now",
    [
        pytest.param(est(1999, 12, 31, 18), id="1999"),
        pytest.param(est(2100, 1, 4, 18), id="2100"),
    ],
)
def test_completed_session_rejects_a_clock_outside_the_supported_calendar(now):
    with pytest.raises(ValueError, match="outside the supported XNYS calendar range"):
        completed_session(now)


@pytest.mark.parametrize(
    "now",
    [
        pytest.param(est(2000, 1, 2, 23, 59), id="sunday-2359-est-before-the-first-session"),
        pytest.param(est(2000, 1, 3, 9, 30), id="first-session-open"),
        pytest.param(est(2000, 1, 3, 16) - MICROSECOND, id="1us-before-the-first-close"),
    ],
)
def test_no_session_is_complete_before_the_first_supported_close(now):
    with pytest.raises(ValueError):
        completed_session(now)


def test_the_first_supported_session_completes_at_its_close():
    assert_completed(est(2000, 1, 3, 16), FIRST_SESSION)
    with pytest.raises(ValueError) as caught:
        completed_session(est(2000, 1, 3, 16) - MICROSECOND)
    assert str(caught.value) == "no completed XNYS session before 2000-01-03T15:59:59.999999-05:00"


# --- completed_session with a settle period -----------------------------------------------------

HOUR = timedelta(hours=1)


@pytest.mark.parametrize(
    ("now", "settle", "expected"),
    [
        pytest.param(edt(2026, 10, 2, 17) - MICROSECOND, HOUR, date(2026, 10, 1), id="1us-before-settled"),
        pytest.param(edt(2026, 10, 2, 17), HOUR, END, id="settled-at-close-plus-settle"),
        pytest.param(edt(2026, 10, 2, 16), timedelta(0), END, id="zero-settle-is-the-close"),
        pytest.param(edt(2026, 10, 2, 16), MICROSECOND, date(2026, 10, 1), id="one-microsecond-settle"),
        pytest.param(edt(2026, 10, 3, 11), HOUR, END, id="saturday"),
        pytest.param(edt(2026, 10, 5, 16, 30), HOUR, END, id="monday-not-yet-settled"),
        pytest.param(
            est(2026, 11, 27, 14) - MICROSECOND, HOUR, date(2026, 11, 25), id="early-close-unsettled"
        ),
        pytest.param(est(2026, 11, 27, 14), HOUR, date(2026, 11, 27), id="early-close-settled"),
        pytest.param(edt(2026, 10, 5, 17), timedelta(days=3), END, id="settle-of-days"),
        pytest.param(edt(2026, 10, 5, 16) - MICROSECOND, timedelta(days=3), date(2026, 10, 1), id="days-1us"),
        # Elapsed time across the fall-back night: Friday 16:00 EDT + 72 h is Monday 15:00 EST.
        pytest.param(est(2026, 11, 2, 15), timedelta(hours=72), date(2026, 10, 30), id="72h-over-fall-back"),
        pytest.param(
            est(2026, 11, 2, 15) - MICROSECOND, timedelta(hours=72), date(2026, 10, 29), id="72h-less-1us"
        ),
        # And across the spring-forward night: Friday 16:00 EST + 72 h is Monday 17:00 EDT.
        pytest.param(edt(2026, 3, 9, 17), timedelta(hours=72), date(2026, 3, 6), id="72h-over-spring"),
        pytest.param(
            edt(2026, 3, 9, 17) - MICROSECOND, timedelta(hours=72), date(2026, 3, 5), id="spring-1us"
        ),
    ],
)
def test_completed_session_waits_for_the_settle_period_after_the_close(now, settle, expected):
    assert_completed(now, expected, settle)


@pytest.mark.parametrize(
    ("settle", "first", "second"),
    [
        # Friday 2026-10-30 closes 16:00 EDT. 33.5 h later is the first 01:30 (EDT) of
        # 2026-11-01, 34.5 h later the second (EST): two readings of one wall time.
        pytest.param(timedelta(hours=33, minutes=30), date(2026, 10, 30), date(2026, 10, 30), id="33h30"),
        pytest.param(timedelta(hours=34, minutes=30), date(2026, 10, 29), date(2026, 10, 30), id="34h30"),
    ],
)
def test_completed_session_tells_the_two_fall_back_readings_apart(settle, first, second):
    early, late = (
        datetime(2026, 11, 1, 1, 30, tzinfo=NEW_YORK),
        datetime(2026, 11, 1, 1, 30, fold=1, tzinfo=NEW_YORK),
    )

    assert completed_session(early, settle) == first
    assert completed_session(late, settle) == second
    assert completed_session(early - MICROSECOND, settle) == date(2026, 10, 29)


def test_completed_session_settle_defaults_to_zero():
    assert completed_session(FRIDAY_CLOSE) == completed_session(FRIDAY_CLOSE, timedelta(0)) == END


@pytest.mark.parametrize(
    "settle",
    [pytest.param(-MICROSECOND, id="minus-1us"), pytest.param(-HOUR, id="minus-1h")],
)
def test_completed_session_rejects_a_negative_settle(settle):
    with pytest.raises(ValueError, match="^settle must not be negative$"):
        completed_session(NOW, settle)


def test_a_settle_reaching_before_the_first_close_finds_no_completed_session():
    with pytest.raises(ValueError) as caught:
        completed_session(est(2000, 1, 4, 16), timedelta(days=2))
    assert str(caught.value) == "no completed XNYS session before 2000-01-02T16:00:00-05:00"
    assert completed_session(est(2000, 1, 4, 17), timedelta(days=1, hours=1)) == FIRST_SESSION


# --- closed periods and market status -----------------------------------------------------------


def assert_period(period: ClosedPeriod, session: date, start: datetime, end: datetime) -> None:
    assert type(period) is ClosedPeriod
    assert period.session == session
    assert_eastern(period.start, start)
    assert_eastern(period.end, end)


@pytest.mark.parametrize(
    ("session", "start", "end"),
    [
        pytest.param(date(2026, 10, 1), edt(2026, 10, 1, 16), edt(2026, 10, 2, 9, 30), id="overnight"),
        pytest.param(END, FRIDAY_CLOSE, edt(2026, 10, 5, 9, 30), id="over-the-weekend"),
        pytest.param(date(2026, 9, 4), edt(2026, 9, 4, 16), edt(2026, 9, 8, 9, 30), id="over-labor-day"),
        pytest.param(
            date(2026, 11, 25), est(2026, 11, 25, 16), est(2026, 11, 27, 9, 30), id="over-thanksgiving"
        ),
        pytest.param(
            date(2026, 11, 27), est(2026, 11, 27, 13), est(2026, 11, 30, 9, 30), id="from-an-early-close"
        ),
        pytest.param(
            date(2026, 12, 24), est(2026, 12, 24, 13), est(2026, 12, 28, 9, 30), id="christmas-early-close"
        ),
        # Friday 16:00 EDT to Monday 09:30 EST: 66.5 hours of elapsed time, 65.5 on the wall clock.
        pytest.param(date(2026, 10, 30), edt(2026, 10, 30, 16), est(2026, 11, 2, 9, 30), id="over-fall-back"),
        pytest.param(date(2026, 3, 6), est(2026, 3, 6, 16), edt(2026, 3, 9, 9, 30), id="over-spring-forward"),
        pytest.param(
            date(2099, 12, 30), est(2099, 12, 30, 16), est(2099, 12, 31, 9, 30), id="last-supported"
        ),
        pytest.param(FIRST_SESSION, est(2000, 1, 3, 16), est(2000, 1, 4, 9, 30), id="first-supported"),
    ],
)
def test_a_closed_period_runs_from_a_close_to_the_next_open(session, start, end):
    assert_period(closed_period(session), session, start, end)


def test_closed_periods_follow_the_published_schedule_for_every_session():
    sessions = published_sessions()
    for session, following in pairwise(sessions):
        assert_period(closed_period(session), session, published_close(session), published_open(following))


@pytest.mark.parametrize("day", NON_SESSIONS)
def test_only_a_session_has_a_closed_period(day):
    with pytest.raises(ValueError, match=f"^{day} is not an XNYS trading session$"):
        closed_period(day)


def test_the_last_supported_session_has_no_closed_period():
    with pytest.raises(ValueError) as caught:
        closed_period(LAST_SESSION)
    assert str(caught.value) == "no XNYS session after 2099-12-31 in the supported calendar range"


def test_a_closed_period_contains_its_close_but_not_the_next_open():
    period = closed_period(END)
    assert FRIDAY_CLOSE in period
    assert FRIDAY_CLOSE - MICROSECOND not in period
    assert edt(2026, 10, 5, 9, 30) - MICROSECOND in period
    assert edt(2026, 10, 5, 9, 30) not in period
    # Instants, not wall times: the same moments read in UTC and in Tokyo.
    assert FRIDAY_CLOSE.astimezone(UTC) in period
    assert edt(2026, 10, 5, 9, 30).astimezone(timezone(timedelta(hours=9))) not in period
    with pytest.raises(ValueError, match="^moment must include a timezone$"):
        datetime(2026, 10, 3, 12) in period  # noqa: B015 - the membership test is the call under test


CLOSED_READINGS = [
    pytest.param(FRIDAY_CLOSE, END, id="friday-at-the-close"),
    pytest.param(NOW, END, id="friday-evening"),
    pytest.param(edt(2026, 10, 3, 11), END, id="saturday"),
    pytest.param(edt(2026, 10, 5, 9, 30) - MICROSECOND, END, id="monday-1us-before-the-open"),
    pytest.param(MONDAY_CLOSE, MONDAY, id="monday-at-the-close"),
    pytest.param(edt(2026, 9, 7, 18), date(2026, 9, 4), id="labor-day"),
    pytest.param(est(2026, 11, 27, 13), date(2026, 11, 27), id="early-close-at-13"),
    pytest.param(est(2026, 11, 26, 12), date(2026, 11, 25), id="thanksgiving-midday"),
    pytest.param(datetime(2026, 11, 1, 1, 30, tzinfo=NEW_YORK), date(2026, 10, 30), id="fall-back-edt-0130"),
    pytest.param(
        datetime(2026, 11, 1, 1, 30, fold=1, tzinfo=NEW_YORK), date(2026, 10, 30), id="fall-back-est-0130"
    ),
]

TRADING_READINGS = [
    pytest.param(edt(2026, 10, 5, 9, 30), MONDAY, id="monday-at-the-open"),
    pytest.param(edt(2026, 10, 5, 12), MONDAY, id="monday-midday"),
    pytest.param(MONDAY_CLOSE - MICROSECOND, MONDAY, id="monday-1us-before-the-close"),
    pytest.param(FRIDAY_CLOSE - MICROSECOND, END, id="friday-1us-before-the-close"),
    pytest.param(est(2026, 11, 27, 13) - MICROSECOND, date(2026, 11, 27), id="before-an-early-close"),
    pytest.param(est(2026, 11, 2, 9, 30), date(2026, 11, 2), id="first-est-open"),
    pytest.param(edt(2026, 3, 9, 9, 30), date(2026, 3, 9), id="first-edt-open"),
]


@pytest.mark.parametrize(("moment", "session"), CLOSED_READINGS)
def test_a_reading_while_xnys_is_closed_falls_in_the_latest_sessions_closed_period(moment, session):
    for reading in (moment, moment.astimezone(UTC)):
        period = closed_period_at(reading)
        assert period == closed_period(session), reading.isoformat()
        status = market_status(reading)
        assert status == MarketStatus("closed", closed_period(session))


@pytest.mark.parametrize(("moment", "session"), TRADING_READINGS)
def test_a_reading_while_a_session_trades_has_no_closed_period(moment, session):
    for reading in (moment, moment.astimezone(UTC)):
        assert closed_period_at(reading) is None, reading.isoformat()
        # The trading session's coming closed period: when a live page can next be read.
        assert market_status(reading) == MarketStatus("trading", closed_period(session))


def test_closed_and_trading_alternate_exactly_at_every_published_open_and_close():
    for session in published_sessions():
        opened, closed = published_open(session), published_close(session)
        assert closed_period_at(opened - MICROSECOND) == closed_period(previous_session(session))
        assert closed_period_at(opened) is None
        assert closed_period_at(closed - MICROSECOND) is None
        assert closed_period_at(closed) == closed_period(session)
        assert market_status(opened).status == "trading"
        assert market_status(closed) == MarketStatus("closed", closed_period(session))


def test_closed_periods_do_not_depend_on_the_host_time_zone(host_time_zone):
    for zone in ("EAST-14", "WEST+12", "UTC0"):
        host_time_zone(zone)
        assert closed_period_at(NOW) == closed_period(END)
        assert closed_period_at(edt(2026, 10, 5, 12)) is None
        assert market_status(edt(2026, 10, 5, 21)) == MarketStatus("closed", closed_period(MONDAY))


def test_closed_period_queries_reject_a_reading_without_a_utc_offset():
    with pytest.raises(ValueError, match="^moment must include a timezone$"):
        closed_period_at(datetime(2026, 10, 3, 12))
    with pytest.raises(ValueError, match="^moment must include a timezone$"):
        closed_period_at(datetime(2026, 10, 3, 12, tzinfo=OffsetlessZone()))
    with pytest.raises(ValueError, match="^now must include a timezone$"):
        market_status(datetime(2026, 10, 3, 12))


def test_closed_period_queries_stop_at_the_ends_of_the_supported_calendar():
    with pytest.raises(ValueError) as caught:
        closed_period_at(est(2000, 1, 3, 12))
    assert str(caught.value) == "no completed XNYS session before 2000-01-03T12:00:00-05:00"
    with pytest.raises(ValueError) as caught:
        market_status(est(2099, 12, 31, 17))
    assert str(caught.value) == "no XNYS session after 2099-12-31 in the supported calendar range"
    # The last supported session trades, but its close would start a period without an end.
    with pytest.raises(ValueError) as caught:
        market_status(est(2099, 12, 31, 12))
    assert str(caught.value) == "no XNYS session after 2099-12-31 in the supported calendar range"
    before_the_open = market_status(est(2099, 12, 31, 9, 29))
    assert before_the_open == MarketStatus("closed", closed_period(date(2099, 12, 30)))
