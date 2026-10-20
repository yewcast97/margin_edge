"""The second raw unit: one ticker's daily prices from Tiingo, as ``fetch`` writes them.

``raw/{TICKER}/prices_{END}_{TOKEN}.json.gz`` (``_N`` before ``.json.gz`` for a second file
in one second) is gzip, as a chain is (``chain.load``), of one JSON object:

- ``ticker``; ``start`` and ``end``, the first and the last day asked for, ``end`` being the
  XNYS session ``END``; ``fetched_at``, New York ISO time with offset, which ``TOKEN``
  names to the second;
- ``request``: the key-free URL whose answer supplied it (``tiingo.prices_url``);
- ``bars``: Tiingo's daily bars from ``start`` to ``end``, ascending, each with exactly the
  fields ``BAR_FIELDS`` as Tiingo sent them, numbers as its literal text in JSON strings.

A bar's ``date`` (``2026-10-16T00:00:00.000Z``) is a day label: its ``YYYY-MM-DD`` names
the session, and it is never converted to New York time, which would name the day before
(the one exception to converting a source's times when they are read).

A file holds either no bar (Tiingo has no prices for the ticker, by HTTP 404 or an empty
answer) or a bar of ``end``, which proves that Tiingo has published that session. Tiingo
adjusts every earlier bar for each split and dividend, so ``fetch`` writes one file of the
whole range the rows need whenever the newest is not current, and only the newest file is
read (``store.select_prices``); every file is validated on every read.

``check_prices`` holds every rule a file must meet, for ``fetch`` before it writes one and
for every read after: the keys and forms; the request built from the ticker, ``start`` and
``end``; the name against ``end`` and ``fetched_at``; ``end`` a session, not before
``start``; fetched after ``end``'s close and not after the clock; every bar a session from
``start`` to ``end``, ascending, once each, its ``close``, ``adjClose`` and ``splitFactor``
above 0 and its other numbers not negative; no bar, or one of ``end``.

``daily_return`` is a session's return from two adjusted closes of one file.
"""

import gzip
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from fractions import Fraction
from functools import cached_property
from typing import Final

from market_state_research.common.sessions import is_session, previous_session, session_close
from market_state_research.common.text import printable
from market_state_research.common.times import TOKEN_PATTERN, et_isoformat, timestamp_token, to_eastern

from .api import DAY_PATTERN, is_number, load_json, parse_day
from .chain import load
from .surface import Value, rounded
from .tiingo import prices_url

RETURN_PLACES: Final = 4
BAR_FIELDS: Final = (
    "date",
    "close",
    "high",
    "low",
    "open",
    "volume",
    "adjClose",
    "adjHigh",
    "adjLow",
    "adjOpen",
    "adjVolume",
    "divCash",
    "splitFactor",
)
RAW_NAME = re.compile(
    rf"prices_(?P<date>{DAY_PATTERN})_(?P<token>{TOKEN_PATTERN})(?:_[0-9]+)?\.json\.gz", re.ASCII
)
_KEYS: Final = ("ticker", "start", "end", "fetched_at", "request", "bars")
_POSITIVE: Final = ("close", "adjClose", "splitFactor")
_BAR_DATE = re.compile(rf"(?P<day>{DAY_PATTERN})T00:00:00\.000Z", re.ASCII)


@dataclass(frozen=True)
class Bar:
    """One daily bar: the session it labels and its fields as Tiingo's text, ``date`` included."""

    day: date
    values: Mapping[str, str]

    @property
    def close(self) -> Decimal:
        return Decimal(self.values["close"])

    @property
    def adj_close(self) -> Decimal:
        """The close adjusted for every later split and dividend, as of the file's fetch."""
        return Decimal(self.values["adjClose"])

    def item(self) -> dict[str, str]:
        return dict(self.values)


@dataclass(frozen=True)
class Prices:
    """One valid prices file's content."""

    ticker: str
    start: date
    end: date
    fetched_at: datetime
    request: str
    bars: tuple[Bar, ...]

    @cached_property
    def _by_day(self) -> dict[date, Bar]:
        return {bar.day: bar for bar in self.bars}

    def bar(self, day: date) -> Bar | None:
        return self._by_day.get(day)


def raw_name(end: date, fetched_at: datetime, suffix: str = "") -> str:
    """The name of a prices file ending ``end`` fetched at ``fetched_at``; ``suffix`` is ``""`` or ``_N``."""
    return f"prices_{end.isoformat()}_{timestamp_token(fetched_at)}{suffix}.json.gz"


def dump(prices: Prices) -> bytes:
    """The bytes ``fetch`` writes: deterministic gzip of compact, key-ordered JSON."""
    value = {
        "ticker": prices.ticker,
        "start": prices.start.isoformat(),
        "end": prices.end.isoformat(),
        "fetched_at": et_isoformat(prices.fetched_at),
        "request": prices.request,
        "bars": [bar.item() for bar in prices.bars],
    }
    payload = json.dumps(value, ensure_ascii=True, allow_nan=False, separators=(",", ":")).encode("ascii")
    return gzip.compress(payload, compresslevel=9, mtime=0)


def check_bar(item: object, number: int) -> Bar:
    """``item`` as a ``Bar``: exactly ``BAR_FIELDS`` in that order, each Tiingo's text in its form."""
    where = f"bar {number}"
    if not isinstance(item, dict) or tuple(item) != BAR_FIELDS:
        raise ValueError(f"{where} must hold exactly {', '.join(BAR_FIELDS)}, in that order")
    for name, text in item.items():
        if not isinstance(text, str):
            raise ValueError(f"{where}: {name} must be text")
    match = _BAR_DATE.fullmatch(item["date"])
    if match is None:
        raise ValueError(f"{where}: date must be YYYY-MM-DDT00:00:00.000Z")
    day = parse_day(match["day"])
    for name in BAR_FIELDS[1:]:
        text = item[name]
        if not is_number(text):
            raise ValueError(f"{where}: {name} {json.dumps(text)} is not a decimal number")
        if Decimal(text) < 0 or (name in _POSITIVE and Decimal(text) == 0):
            raise ValueError(
                f"{where}: {name} {text} must be {'above' if name in _POSITIVE else 'at least'} 0"
            )
    return Bar(day, dict(item))


def parse_bars(body: bytes) -> tuple[Bar, ...]:
    """Tiingo's answer, a JSON array of daily bars, numbers kept as literal text; each bar keeps
    the fields ``BAR_FIELDS`` and drops any other. ``ValueError`` names the problem."""
    value = load_json(body)
    if not isinstance(value, list):
        raise ValueError("the body is not a JSON array")
    bars: list[Bar] = []
    for number, item in enumerate(value, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"bar {number} is not an object")
        absent = [name for name in BAR_FIELDS if name not in item]
        if absent:
            raise ValueError(f"bar {number} lacks {', '.join(absent)}")
        bars.append(check_bar({name: item[name] for name in BAR_FIELDS}, number))
    return tuple(bars)


def _day(value: object, name: str) -> date:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a YYYY-MM-DD date")
    return parse_day(value)


def check_prices(value: object, ticker: str, name: str | None, now: datetime) -> Prices:
    """``value`` as valid ``Prices`` of ``ticker`` named ``name`` (None: not named yet); every
    problem raises one ``ValueError`` line."""
    if not isinstance(value, dict):
        raise ValueError("a prices file must hold one JSON object")
    if tuple(value) != _KEYS:
        raise ValueError(f"the keys must be exactly {', '.join(_KEYS)}, in that order")
    if value["ticker"] != ticker:
        raise ValueError(f"the file is of {printable(str(value['ticker']))}, not {ticker}")
    start, end = _day(value["start"], "start"), _day(value["end"], "end")
    fetched_text = value["fetched_at"]
    try:
        fetched_at = to_eastern(datetime.fromisoformat(fetched_text), "fetched_at")
    except (TypeError, ValueError):
        raise ValueError("fetched_at must be an ISO time with an offset") from None
    if et_isoformat(fetched_at) != fetched_text:
        raise ValueError("fetched_at must be written in New York time with its offset")
    if name is not None:
        match = RAW_NAME.fullmatch(name)
        if match is None or match["date"] != end.isoformat() or match["token"] != timestamp_token(fetched_at):
            raise ValueError(f"the name must be {raw_name(end, fetched_at)} (or end _N.json.gz)")
    if not is_session(end):
        raise ValueError(f"end {end} is not an XNYS trading session")
    if start > end:
        raise ValueError(f"start {start} is after end {end}")
    if value["request"] != prices_url(ticker, start, end):
        raise ValueError(f"request must be {prices_url(ticker, start, end)}")
    close = session_close(end)
    if fetched_at < close:
        raise ValueError(
            f"fetched at {et_isoformat(fetched_at)}, before the session {end} closed at {et_isoformat(close)}"
        )
    if fetched_at > to_eastern(now, "now"):
        raise ValueError(f"fetched_at {et_isoformat(fetched_at)} is later than the current time")
    items = value["bars"]
    if not isinstance(items, list):
        raise ValueError("bars must be a list")
    bars = tuple(check_bar(item, number) for number, item in enumerate(items, start=1))
    previous: date | None = None
    for number, bar in enumerate(bars, start=1):
        if not start <= bar.day <= end:
            raise ValueError(f"bar {number} is dated {bar.day}, outside {start} to {end}")
        if not is_session(bar.day):
            raise ValueError(f"bar {number} is dated {bar.day}, not an XNYS trading session")
        if previous is not None and bar.day <= previous:
            raise ValueError("bars must be listed once each, in date order")
        previous = bar.day
    if bars and bars[-1].day != end:
        raise ValueError(f"the bars hold none of {end}: Tiingo has not published it")
    return Prices(ticker, start, end, fetched_at, value["request"], bars)


def read_prices(data: bytes, ticker: str, name: str, now: datetime) -> Prices:
    """Validate one prices file's bytes; every problem raises a one-line ``ValueError``."""
    return check_prices(load(data), ticker, name, now)


def daily_return(prices: Prices | None, day: date) -> Value:
    """The stock's return of session ``day`` in percent: (adjClose(day) / adjClose(P) - 1) x 100,
    P the XNYS session before it, both bars of ``prices`` (one adjustment), exact and rounded
    half-even to ``RETURN_PLACES`` places; or None and why."""
    if prices is None:
        return Value(None, "no prices are fetched")
    if not prices.bars:
        return Value(None, f"Tiingo has no prices for {prices.ticker}")
    previous = previous_session(day)
    current, before = prices.bar(day), prices.bar(previous)
    if current is None or before is None:
        missing = " and ".join(item.isoformat() for item in (previous, day) if prices.bar(item) is None)
        return Value(None, f"no bar of {missing} in the prices from {prices.start} to {prices.end}")
    ratio = Fraction(current.adj_close) / Fraction(before.adj_close)
    return Value(rounded((ratio - 1) * 100, RETURN_PLACES))
