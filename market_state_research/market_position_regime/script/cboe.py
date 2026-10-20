"""Cboe's daily history of the VIX: the file, its raw unit and every rule a read checks.

Cboe calculates the Cboe Volatility Index (VIX) from the quotes of S&P 500 index options and
publishes the index's open, high, low and close of every day it calculated it, from
``FIRST_DAY``, as one CSV file at a fixed address (``URL``, public, no key), replaced in place
in the evening after each such day. ``fetch`` writes the file's bytes as received, compressed
with gzip (``dump``: deterministic, no name or time in the gzip header), to
``raw/market/cboe_vix_{TOKEN}.csv.gz``, ``TOKEN`` naming the time it arrived.

Every read checks the whole file again (``parse_history``, ``check_history``): ASCII lines,
each ended by a line feed; the first exactly ``HEADER``; then one row per day, in date
order, the first of ``FIRST_DAY``: the day written ``MM/DD/YYYY``, then the open, high, low
and close, each a decimal above 0 with six places (no order among the four is checked: in
some of Cboe's early rows the high or the low does not bound the open and the close); no row
dated after the day the file was fetched, nor a row of an XNYS session whose VIX was not due
yet when it was fetched (``periods.vix_due``); the fetch time not after the clock. The file
also holds rows of days XNYS does not trade (the US holidays on which Cboe has calculated
the index in its global trading hours since 2022, and 2004-06-11): they are kept as
received and never used, since the domain ranks the closes of XNYS sessions only.
"""

import gzip
import io
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Final

from market_state_research.common.sessions import is_session
from market_state_research.common.text import printable
from market_state_research.common.times import (
    TOKEN_PATTERN,
    et_isoformat,
    parse_timestamp_token,
    timestamp_token,
    to_eastern,
)

from .periods import vix_due

HOST: Final = "cdn-api.cboe.com"
PATH: Final = "/api/global/us_indices/daily_prices/VIX_History.csv"
URL: Final = f"https://{HOST}{PATH}"
HEADER: Final = "DATE,OPEN,HIGH,LOW,CLOSE"
FIRST_DAY: Final = date(1990, 1, 2)  # the file's first row
MAX_UNCOMPRESSED: Final = 16 * 1024 * 1024  # bytes of a raw file unpacked; the file is about 0.5 MB
RAW_NAME: Final = re.compile(rf"cboe_vix_(?P<token>{TOKEN_PATTERN})(?:_[0-9]+)?\.csv\.gz", re.ASCII)
MAX_SUFFIX: Final = 99

_VALUE: Final = r"(?:0|[1-9][0-9]{0,5})\.[0-9]{6}"
_ROW = re.compile(
    rf"(?P<month>[0-9]{{2}})/(?P<day>[0-9]{{2}})/(?P<year>[0-9]{{4}}),"
    rf"(?P<open>{_VALUE}),(?P<high>{_VALUE}),(?P<low>{_VALUE}),(?P<close>{_VALUE})",
    re.ASCII,
)
_FIELDS: Final = ("open", "high", "low", "close")


@dataclass(frozen=True)
class Bar:
    """One day's row: the day and its four values as Cboe wrote them."""

    day: date
    open: str
    high: str
    low: str
    close: str

    @property
    def close_value(self) -> Decimal:
        return Decimal(self.close)


@dataclass(frozen=True)
class History:
    """One valid file: when it was fetched and its rows, ascending by day."""

    fetched_at: datetime
    bars: tuple[Bar, ...]

    @property
    def newest(self) -> date:
        return self.bars[-1].day

    def by_day(self) -> dict[date, Bar]:
        return {bar.day: bar for bar in self.bars}


def raw_name(fetched_at: datetime, suffix: str = "") -> str:
    """The name of a file fetched at ``fetched_at``; ``suffix`` is ``""`` or ``_N``."""
    return f"cboe_vix_{timestamp_token(fetched_at)}{suffix}.csv.gz"


def parse_history(data: bytes) -> tuple[Bar, ...]:
    """The rows of the file ``data``, ascending; every rule of the module docstring but the time
    checks, each problem one ``ValueError`` line."""
    try:
        text = data.decode("ascii")
    except UnicodeDecodeError:
        raise ValueError("the file is not ASCII text") from None
    if not text.endswith("\n"):
        raise ValueError("the file must end with a line feed")
    lines = text[:-1].split("\n")
    if lines[0] != HEADER:
        raise ValueError(f"the first line must be exactly {HEADER}")
    bars: list[Bar] = []
    for number, line in enumerate(lines[1:], start=2):
        match = _ROW.fullmatch(line)
        if match is None:
            raise ValueError(
                f"line {number} must be a MM/DD/YYYY day and four decimals with six places, separated by "
                f"commas, got {printable(line[:80])!r}"
            )
        try:
            day = date(int(match["year"]), int(match["month"]), int(match["day"]))
        except ValueError:
            raise ValueError(f"line {number}: {line[:10]} is not a day that exists") from None
        for field in _FIELDS:
            if Decimal(match[field]) == 0:
                raise ValueError(f"line {number}: the {field} of {day} must be above 0")
        if bars and day <= bars[-1].day:
            raise ValueError(
                f"line {number} is dated {day}, not after {bars[-1].day}: the days must ascend, once each"
            )
        bars.append(Bar(day, match["open"], match["high"], match["low"], match["close"]))
    if not bars:
        raise ValueError("the file holds no day")
    if bars[0].day != FIRST_DAY:
        raise ValueError(f"the first day must be {FIRST_DAY}, got {bars[0].day}")
    return tuple(bars)


def check_history(data: bytes, fetched_at: datetime, now: datetime) -> History:
    """The valid file ``data`` fetched at ``fetched_at``; every rule of the module docstring."""
    fetched_at = to_eastern(fetched_at, "fetched_at")
    if fetched_at > to_eastern(now, "now"):
        raise ValueError(f"fetched_at {et_isoformat(fetched_at)} is later than the current time")
    bars = parse_history(data)
    newest = bars[-1].day
    if newest > fetched_at.date():
        raise ValueError(
            f"the newest day, {newest}, is after the day the file was fetched ({et_isoformat(fetched_at)})"
        )
    # Days ascend, so only the newest row can be of the day of the fetch.
    if newest == fetched_at.date() and is_session(newest) and vix_due(newest) > fetched_at:
        raise ValueError(
            f"the row of {newest} was fetched at {et_isoformat(fetched_at)}, before the session's VIX "
            f"was due at {et_isoformat(vix_due(newest))}"
        )
    return History(fetched_at, bars)


def dump(data: bytes) -> bytes:
    """The bytes ``fetch`` writes: the file as received, in deterministic gzip."""
    return gzip.compress(data, compresslevel=9, mtime=0)


def load(data: bytes) -> bytes:
    """The file a raw file's gzip bytes hold; ``ValueError`` for anything else."""
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(data), mode="rb") as stream:
            payload = stream.read(MAX_UNCOMPRESSED + 1)
    except (OSError, EOFError, gzip.BadGzipFile) as error:
        raise ValueError(f"not a gzip file: {printable(str(error)) or type(error).__name__}") from None
    if len(payload) > MAX_UNCOMPRESSED:
        raise ValueError(f"more than {MAX_UNCOMPRESSED} bytes uncompressed")
    return payload


def read_history(data: bytes, name: str, now: datetime) -> History:
    """Validate one raw file named ``name``; every problem raises a one-line ``ValueError``."""
    match = RAW_NAME.fullmatch(name)
    instant = None if match is None else parse_timestamp_token(match["token"])
    if instant is None:
        raise ValueError("the name must be cboe_vix_TOKEN.csv.gz (or end _N.csv.gz), TOKEN a New York time")
    return check_history(load(data), instant, now)
