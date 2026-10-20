"""New York exchange time: the only time zone in stored values, file names and output.

Python compares and subtracts two aware datetimes that share one tzinfo object by their
naive wall times and ignores ``fold``. ``ZoneInfo`` instances are cached, so every
``America/New_York`` datetime shares one object, and 01:30 EDT and 01:30 EST on the
fall-back day compare equal. Conversely, ``==`` between
different tzinfos is always False when either side's offset depends on ``fold``, even
for the same instant (PEP 495). ``to_eastern`` therefore gives each instant a
fixed-offset ``EDT``/``EST`` tzinfo, which compares and subtracts correctly. Normalise
every datetime with it before comparing; never compare raw ``ZoneInfo`` datetimes.
"""

import re
from datetime import UTC, date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

NEW_YORK = ZoneInfo("America/New_York")
TOKEN_FORMAT = "%Y%m%dT%H%M%S"
# Explicit ASCII classes: \d would also match other Unicode digits, which strptime() accepts.
# The zone suffix makes the repeated fall-back hour unambiguous.
TOKEN_PATTERN = r"[0-9]{8}T[0-9]{6}(?:EDT|EST)"

_TOKEN = re.compile(TOKEN_PATTERN, re.ASCII)
_ZONE_NAMES = ("EDT", "EST")
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_MILLISECOND = timedelta(milliseconds=1)


def require_aware(moment: datetime, name: str = "now") -> None:
    """Reject naive datetimes, which name no instant and cannot be compared with closes."""
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise ValueError(f"{name} must include a timezone")


def to_eastern(moment: datetime, name: str = "timestamp") -> datetime:
    """The same instant as New York wall time with a fixed-offset ``EDT``/``EST`` tzinfo.

    The result has ``fold=0``. Ordering and subtraction are correct against any aware
    datetime, but ``==``, ``!=`` and hashing (sets, dict keys) are reliable only between
    normalised values: per PEP 495 a raw ``ZoneInfo`` datetime in the fall-back hour or
    the spring-forward gap never equals it, even for the same instant, so normalise both
    operands first. Instants outside datetime's range raise ``OverflowError``; instants
    when New York kept neither EDT nor EST (local mean time before 1883, war time in
    1942-1945) raise ``ValueError``, because no ``EDT``/``EST`` text could name them.
    """
    require_aware(moment, name)
    # Through UTC, so a wall time that does not exist (spring-forward gap) is resolved to
    # the real instant and its canonical wall time, and fold selects the offset.
    local = moment.astimezone(UTC).astimezone(NEW_YORK)
    offset, zone = local.utcoffset(), local.tzname()
    if offset is None or zone not in _ZONE_NAMES:
        raise ValueError(f"{name} falls outside New York's EDT/EST era")
    return local.replace(tzinfo=timezone(offset, zone), fold=0)


def et_isoformat(moment: datetime) -> str:
    """ISO 8601 New York time with offset and full precision, e.g. ``2026-10-06T05:09:17.044000-04:00``."""
    return to_eastern(moment).isoformat()


def et_display(moment: datetime) -> str:
    """New York time to the second for text meant only for people (headers, report pages and
    their notes), e.g. ``2026-10-06 05:09:17 EDT``."""
    return to_eastern(moment).strftime("%Y-%m-%d %H:%M:%S %Z")


def timestamp_token(moment: datetime) -> str:
    """New York time to the second for file names, e.g. ``20261006T050917EDT``.

    Sub-second precision is truncated. Tokens are not ordered as strings: compare the
    instants that ``parse_timestamp_token`` returns.
    """
    eastern = to_eastern(moment)
    return eastern.strftime(TOKEN_FORMAT) + eastern.strftime("%Z")


def parse_timestamp_token(token: str) -> datetime | None:
    """The New York instant (fixed offset) a token names, or None if it names none.

    None for text that does not match ``TOKEN_PATTERN``, an impossible date or time, a
    wall time that does not exist (the spring-forward gap), a suffix that is not the zone
    in force (``20260701T120000EST``) and an instant outside ``to_eastern``'s range. In
    the fall-back hour ``...T013000EDT`` and ``...T013000EST`` are both valid and name
    instants one hour apart.
    """
    if not _TOKEN.fullmatch(token):
        return None
    wall, zone = token[:-3], token[-3:]
    try:
        naive = datetime.strptime(wall, TOKEN_FORMAT)
    except ValueError:
        return None
    for fold in (0, 1):
        candidate = naive.replace(tzinfo=NEW_YORK, fold=fold)
        if candidate.tzname() != zone:
            continue
        try:
            instant = to_eastern(candidate)
        except (ValueError, OverflowError):
            return None
        # A nonexistent wall time maps to a different one; only a wall time that occurs
        # in New York round-trips unchanged.
        if instant.replace(tzinfo=None) == naive:
            return instant
    return None


def eastern_midnight(day: date) -> datetime:
    """00:00 New York time on ``day`` as a fixed-offset datetime.

    New York changes its clocks at 02:00, so midnight always exists and occurs once.
    """
    return to_eastern(datetime.combine(day, time(0), tzinfo=NEW_YORK), day.isoformat())


def epoch_ms(moment: datetime) -> int:
    """Whole milliseconds since the Unix epoch at ``moment``, rounded down."""
    require_aware(moment, "timestamp")
    return (moment - _EPOCH) // _MILLISECOND


def from_epoch_ms(value: int) -> datetime:
    """The New York instant (fixed offset) ``value`` milliseconds after the Unix epoch.

    ``OverflowError`` outside datetime's range; ``ValueError`` for a value that is not an
    int or an instant outside ``to_eastern``'s range.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("epoch milliseconds must be an int")
    return to_eastern(_EPOCH + timedelta(milliseconds=value))
