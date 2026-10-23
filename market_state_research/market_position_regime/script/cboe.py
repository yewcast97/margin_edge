"""Cboe's daily histories of the VIX and of the SKEW: the files, their raw units and every rule
a read checks.

Cboe calculates the Cboe Volatility Index (VIX) and the Cboe SKEW Index (SKEW) from the quotes
of S&P 500 index options, and publishes each index's values of every day it calculated it,
from ``FIRST_DAY``, as one CSV file at a fixed address (``Index.url``, public, no key),
replaced in place in the evening after each such day: the VIX's open, high, low and close,
the SKEW's one value. ``fetch`` writes a file's bytes as received, compressed with gzip
(``dump``: deterministic, no name or time in the gzip header), to
``raw/market/cboe_{vix,skew}_{TOKEN}.csv.gz``, ``TOKEN`` naming the time it arrived.

Every read checks the whole file again (``parse_history``, ``check_history``): ASCII lines,
each ended by a line feed; the first exactly the index's header; then one row per day, in
date order, the first of ``FIRST_DAY``: the day written ``MM/DD/YYYY``, then the index's
values, each a decimal above 0 with six places (no order among the VIX's four is checked: in
some of Cboe's early rows the high or the low does not bound the open and the close); no row
dated after the day the file was fetched, nor a row of an XNYS session whose values were not
due yet when it was fetched (``periods.cboe_due``); the fetch time not after the clock. The
VIX file also holds rows of days XNYS does not trade (the US holidays on which Cboe has
calculated the index in its global trading hours since 2022, and 2004-06-11): they are kept
as received and never used, since the domain ranks the values of XNYS sessions only. The
SKEW file lacks some sessions (the domain's ``AGENTS.md`` lists them): a session without a
row has no value.
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

from .periods import cboe_due

HOST: Final = "cdn-api.cboe.com"
FIRST_DAY: Final = date(1990, 1, 2)  # the first row of either file
MAX_UNCOMPRESSED: Final = 16 * 1024 * 1024  # bytes of a raw file unpacked; the VIX file is about 0.5 MB
MAX_SUFFIX: Final = 99


@dataclass(frozen=True)
class Index:
    """One of Cboe's daily index histories: the word naming it in raw names and sources, its
    name, its path on ``HOST`` and the values of a row after the day, in order, the last of
    them the one the domain ranks."""

    key: str
    name: str
    path: str
    fields: tuple[str, ...]

    @property
    def url(self) -> str:
        return f"https://{HOST}{self.path}"

    @property
    def header(self) -> str:
        """The file's first line."""
        return ",".join(("DATE", *(field.upper() for field in self.fields)))

    @property
    def level(self) -> str:
        """The value the domain ranks: the VIX's close, the SKEW."""
        return self.fields[-1]


VIX: Final = Index(
    "vix", "VIX", "/api/global/us_indices/daily_prices/VIX_History.csv", ("open", "high", "low", "close")
)
SKEW: Final = Index("skew", "SKEW", "/api/global/us_indices/daily_prices/SKEW_History.csv", ("skew",))
INDICES: Final = (VIX, SKEW)
_KEYS: Final = "|".join(index.key for index in INDICES)
RAW_NAME: Final = re.compile(
    rf"cboe_(?P<key>{_KEYS})_(?P<token>{TOKEN_PATTERN})(?:_[0-9]+)?\.csv\.gz", re.ASCII
)

_VALUE: Final = r"(?:0|[1-9][0-9]{0,5})\.[0-9]{6}"
_COUNTS: Final = {1: "one decimal", 4: "four decimals"}


def _row_pattern(index: Index) -> re.Pattern[str]:
    values = "".join(rf",(?P<{field}>{_VALUE})" for field in index.fields)
    return re.compile(rf"(?P<month>[0-9]{{2}})/(?P<day>[0-9]{{2}})/(?P<year>[0-9]{{4}}){values}", re.ASCII)


_ROWS: Final = {index: _row_pattern(index) for index in INDICES}


@dataclass(frozen=True)
class Row:
    """One day's row: the day and its values as Cboe wrote them, in the header's order."""

    day: date
    values: tuple[str, ...]

    @property
    def level(self) -> str:
        """The value the domain ranks, as Cboe wrote it: the last of the row."""
        return self.values[-1]

    @property
    def level_value(self) -> Decimal:
        return Decimal(self.level)


@dataclass(frozen=True)
class History:
    """One valid file of ``index``: when it was fetched and its rows, ascending by day."""

    index: Index
    fetched_at: datetime
    rows: tuple[Row, ...]

    @property
    def newest(self) -> date:
        return self.rows[-1].day

    def by_day(self) -> dict[date, Row]:
        return {row.day: row for row in self.rows}


def raw_name(index: Index, fetched_at: datetime, suffix: str = "") -> str:
    """The name of a file of ``index`` fetched at ``fetched_at``; ``suffix`` is ``""`` or ``_N``."""
    return f"cboe_{index.key}_{timestamp_token(fetched_at)}{suffix}.csv.gz"


def parse_history(data: bytes, index: Index) -> tuple[Row, ...]:
    """The rows of the file ``data`` of ``index``, ascending; every rule of the module docstring
    but the time checks, each problem one ``ValueError`` line."""
    try:
        text = data.decode("ascii")
    except UnicodeDecodeError:
        raise ValueError("the file is not ASCII text") from None
    if not text.endswith("\n"):
        raise ValueError("the file must end with a line feed")
    lines = text[:-1].split("\n")
    if lines[0] != index.header:
        raise ValueError(f"the first line must be exactly {index.header}")
    pattern = _ROWS[index]
    rows: list[Row] = []
    for number, line in enumerate(lines[1:], start=2):
        match = pattern.fullmatch(line)
        if match is None:
            raise ValueError(
                f"line {number} must be a MM/DD/YYYY day and {_COUNTS[len(index.fields)]} with six places, "
                f"separated by commas, got {printable(line[:80])!r}"
            )
        try:
            day = date(int(match["year"]), int(match["month"]), int(match["day"]))
        except ValueError:
            raise ValueError(f"line {number}: {line[:10]} is not a day that exists") from None
        for field in index.fields:
            if Decimal(match[field]) == 0:
                raise ValueError(f"line {number}: the {field} of {day} must be above 0")
        if rows and day <= rows[-1].day:
            raise ValueError(
                f"line {number} is dated {day}, not after {rows[-1].day}: the days must ascend, once each"
            )
        rows.append(Row(day, tuple(match[field] for field in index.fields)))
    if not rows:
        raise ValueError("the file holds no day")
    if rows[0].day != FIRST_DAY:
        raise ValueError(f"the first day must be {FIRST_DAY}, got {rows[0].day}")
    return tuple(rows)


def check_history(data: bytes, index: Index, fetched_at: datetime, now: datetime) -> History:
    """The valid file ``data`` of ``index`` fetched at ``fetched_at``; every rule of the module
    docstring."""
    fetched_at = to_eastern(fetched_at, "fetched_at")
    if fetched_at > to_eastern(now, "now"):
        raise ValueError(f"fetched_at {et_isoformat(fetched_at)} is later than the current time")
    rows = parse_history(data, index)
    newest = rows[-1].day
    if newest > fetched_at.date():
        raise ValueError(
            f"the newest day, {newest}, is after the day the file was fetched ({et_isoformat(fetched_at)})"
        )
    # Days ascend, so only the newest row can be of the day of the fetch.
    if newest == fetched_at.date() and is_session(newest) and cboe_due(newest) > fetched_at:
        raise ValueError(
            f"the row of {newest} was fetched at {et_isoformat(fetched_at)}, before the session's "
            f"{index.name} was due at {et_isoformat(cboe_due(newest))}"
        )
    return History(index, fetched_at, rows)


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
    """Validate one raw file named ``name``, of the index its name gives; every problem raises a
    one-line ``ValueError``."""
    match = RAW_NAME.fullmatch(name)
    instant = None if match is None else parse_timestamp_token(match["token"])
    if match is None or instant is None:
        raise ValueError(
            "the name must be cboe_vix_TOKEN.csv.gz or cboe_skew_TOKEN.csv.gz (or end _N.csv.gz), "
            "TOKEN a New York time"
        )
    index = next(index for index in INDICES if index.key == match["key"])
    return check_history(load(data), index, instant, now)
