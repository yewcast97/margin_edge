"""Clock readings shared by the offline fundamentals tests.

Instants are written in New York time with fixed ``EDT``/``EST`` offsets, independently
of ``zoneinfo`` and of the code under test. Builders live beside this module, one module
per concern: ``edgar_support`` (EDGAR JSON and synthetic filing documents),
``fake_edgar`` (a recording fake of EDGAR's HTTP layer), ``calls_support`` (EarningsCalls.dev
calls pages and transcripts with known speakers), ``fake_earningscalls`` (a recording fake of
its HTTP layer), ``transport_support`` (urllib driven offline) and ``workflow_support`` (a
fake EDGAR and provider, raw-tree planters and sample reports whose quotes are copied from
the derived text).
"""

from datetime import date, datetime, timedelta, timezone

EDT = timezone(timedelta(hours=-4), "EDT")
EST = timezone(timedelta(hours=-5), "EST")


def edt(*fields: int) -> datetime:
    """A New York daylight-time wall clock reading with a fixed -04:00 offset."""
    return datetime(*fields, tzinfo=EDT)


def est(*fields: int) -> datetime:
    """A New York standard-time wall clock reading with a fixed -05:00 offset."""
    return datetime(*fields, tzinfo=EST)


NOW = edt(2026, 10, 8, 6, 0)  # Thursday morning
TODAY = date(2026, 10, 8)
