"""The raw unit: one ticker's option chain on one session, as ``fetch`` writes it.

``raw/{TICKER}/chain_{DATE}_{TOKEN}.json.gz`` (``_N`` before ``.json.gz`` for a second
file in one second) is gzip (level 9, no name, mtime 0, so equal content gives equal
bytes) of one JSON object:

- ``session``: the XNYS session ``DATE``; ``ticker``; ``fetched_at``, New York ISO time
  with offset, which ``TOKEN`` names to the second;
- ``source``: ``contracts`` (the latest session, from the contracts listing, proved to be
  that session's by the ``eod`` records dated it, kept in ``traded``) or ``eod`` (from
  sweeps of each expiry's ``eod`` records);
- ``window_days`` (65): the rule the file was cut by;
- ``requests``: the token-free queries whose pages supplied it, without ``page[offset]``;
- ``expiries``: every expiry listed on the session within ``window_days`` calendar days
  after it, with the number of contracts it listed;
- ``rows``: every contract of every listed expiry, usable or not, as the provider's items
  (``id``, ``type``, ``attributes``), numbers as the provider's literal text;
- ``traded`` (``contracts`` only): the ``eod`` records dated the session of the contracts
  traded on it, within the same expiries.

Every expiry within the window is kept, so the horizon the values are read at
(``surface.HORIZON``) is a rule of the derivation, not of the file: it can move without a
new fetch. The cost is size and time: MU's chain of 2026-10-16 (Monday, Wednesday and
Friday expiries) held 11 expiries, 4,696 contracts and 2,485 traded records, 0.2 MB gzipped
and 0.07 s to validate. A file of another window is refused, so changing the window means
fetching again. Files cut by the former rule (a 30-day horizon, the two bracket expiries
only, a ``horizon_days`` key) are refused with a message saying so.

``check_chain`` holds every rule a file must meet, for ``fetch`` before it writes one and
for every read after: the shape and forms (``api.check_attributes``), the name, the
session, the time, the counts of every listed expiry, and for the ``contracts`` source the
proof again: at least one record dated the session, each equal to the row of its contract,
and no row traded after the session.
"""

import gzip
import io
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Final, Literal

from market_state_research.common.sessions import is_session, session_close
from market_state_research.common.text import printable
from market_state_research.common.times import TOKEN_PATTERN, et_isoformat, timestamp_token, to_eastern

from .api import DAY_PATTERN, FIELDS, Record, check_item, is_number, parse_day, parse_occ
from .client import allowed_url

# A session's expiries are kept up to WINDOW_DAYS calendar days out: E1 lies at most
# surface.HORIZON (14) days out and the next monthly expiry at most 35 days after it, so E2
# is found for monthly-only names; 65 also lets a horizon up to 30 days be read from the same files.
WINDOW_DAYS: Final = 65
MAX_UNCOMPRESSED: Final = 64 * 1024 * 1024
FORMER_HORIZON: Final = (
    "this chain was cut by the former 30-day horizon rule; rename it .rejected and fetch the session again"
)
Source = Literal["contracts", "eod"]
RAW_NAME = re.compile(
    rf"chain_(?P<date>{DAY_PATTERN})_(?P<token>{TOKEN_PATTERN})(?:_[0-9]+)?\.json\.gz", re.ASCII
)
_KEYS: Final = (
    "session",
    "ticker",
    "fetched_at",
    "source",
    "window_days",
    "requests",
    "expiries",
    "rows",
    "traded",
)
_TEXT_FIELDS: Final = ("contract", "exp_date", "expiration_type", "type", "tradetime")


@dataclass(frozen=True)
class Expiry:
    exp_date: date
    contracts: int


@dataclass(frozen=True)
class Chain:
    """One valid raw file's content."""

    session: date
    ticker: str
    fetched_at: datetime
    source: Source
    requests: tuple[str, ...]
    expiries: tuple[Expiry, ...]
    rows: tuple[Record, ...]
    traded: tuple[Record, ...] | None

    @property
    def listed(self) -> tuple[date, ...]:
        return tuple(item.exp_date for item in self.expiries)


def raw_name(session: date, fetched_at: datetime, suffix: str = "") -> str:
    """The name of a raw file of ``session`` fetched at ``fetched_at``; ``suffix`` is ``""`` or ``_N``."""
    return f"chain_{session.isoformat()}_{timestamp_token(fetched_at)}{suffix}.json.gz"


def dump(chain: Chain) -> bytes:
    """The bytes ``fetch`` writes: deterministic gzip of compact, key-ordered JSON."""
    value = {
        "session": chain.session.isoformat(),
        "ticker": chain.ticker,
        "fetched_at": et_isoformat(chain.fetched_at),
        "source": chain.source,
        "window_days": WINDOW_DAYS,
        "requests": list(chain.requests),
        "expiries": [
            {"exp_date": item.exp_date.isoformat(), "contracts": item.contracts} for item in chain.expiries
        ],
        "rows": [row.item() for row in chain.rows],
        "traded": None if chain.traded is None else [row.item() for row in chain.traded],
    }
    payload = json.dumps(value, ensure_ascii=True, allow_nan=False, separators=(",", ":")).encode("ascii")
    return gzip.compress(payload, compresslevel=9, mtime=0)


def _unique_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"key {json.dumps(key)} appears more than once")
        value[key] = item
    return value


def _refuse(text: str) -> object:
    raise ValueError(f"the file holds {text}, which a raw file never does")


def load(data: bytes) -> object:
    """The JSON object of a raw file's bytes; ``ValueError`` for anything else."""
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(data), mode="rb") as stream:
            payload = stream.read(MAX_UNCOMPRESSED + 1)
    except (OSError, EOFError, gzip.BadGzipFile) as error:
        raise ValueError(f"not a gzip file: {printable(str(error)) or type(error).__name__}") from None
    if len(payload) > MAX_UNCOMPRESSED:
        raise ValueError(f"more than {MAX_UNCOMPRESSED} bytes uncompressed")
    try:
        return json.loads(
            payload.decode("ascii"),
            object_pairs_hook=_unique_keys,
            parse_float=_refuse,
            parse_constant=_refuse,
        )
    except UnicodeDecodeError:
        raise ValueError("the JSON is not ASCII") from None
    except json.JSONDecodeError as error:
        raise ValueError(f"invalid JSON: {error.msg} (line {error.lineno}, column {error.colno})") from None
    except RecursionError:
        raise ValueError("invalid JSON: nested too deeply") from None


def _whole(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be a whole number")
    return value


def _items(value: object, name: str, source: Source | Literal["traded"]) -> tuple[Record, ...]:
    if not isinstance(value, list):
        raise ValueError(f"{name} must be a list")
    endpoint: Literal["contracts", "eod"] = "eod" if source in ("eod", "traded") else "contracts"
    rows: list[Record] = []
    for number, item in enumerate(value, start=1):
        try:
            rows.append(check_item(item, endpoint))
        except ValueError as error:
            raise ValueError(f"{name} item {number}: {error}") from None
    return tuple(rows)


def _equal(row: Record, record: Record) -> str | None:
    """The first field on which ``record`` differs from ``row``, or None; numbers compare as decimals."""
    for field in FIELDS:
        mine, theirs = row.attributes[field], record.attributes[field]
        if mine is None or theirs is None or field in _TEXT_FIELDS:
            if mine != theirs:
                return field
        elif not (is_number(mine) and is_number(theirs) and Decimal(mine) == Decimal(theirs)):
            return field
    return None


def proof_problem(session: date, rows: Sequence[Record], traded: Sequence[Record]) -> str | None:
    """Why ``rows`` from the contracts listing are not the values of ``session``, or None.

    ``traded`` holds the ``eod`` records dated ``session``. There must be at least one; each
    must equal the row of its contract in ``rows``; and no row may have traded after
    ``session``.
    """
    if not traded:
        return f"no eod record dated {session} proves that the contracts listing is that session's"
    by_contract = {row.contract: row for row in rows}
    for record in traded:
        if record.date != session:
            return f"traded record {record.id} is not dated {session}"
        row = by_contract.get(record.contract)
        if row is None:
            return f"{record.contract} traded on {session}, but the contracts listing does not list it"
        field = _equal(row, record)
        if field is not None:
            return (
                f"{record.contract}: the contracts listing's {field} differs from its eod record dated "
                f"{session}, so the listing is not that session's"
            )
    for row in rows:
        traded_on = row.attributes["tradetime"]
        if traded_on is not None and parse_day(traded_on) > session:
            return f"{row.contract} last traded on {traded_on}, after {session}"
    return None


def check_chain(value: object, ticker: str, name: str | None, now: datetime) -> Chain:
    """``value`` as a valid ``Chain`` of ``ticker`` named ``name`` (None: not named yet); every
    problem raises one ``ValueError`` line."""
    if not isinstance(value, dict):
        raise ValueError("a raw file must hold one JSON object")
    if "horizon_days" in value:
        raise ValueError(FORMER_HORIZON)
    if tuple(value) != _KEYS:
        raise ValueError(f"the keys must be exactly {', '.join(_KEYS)}, in that order")
    session = parse_day(value["session"]) if isinstance(value["session"], str) else None
    if session is None:
        raise ValueError("session must be a YYYY-MM-DD date")
    if value["ticker"] != ticker:
        raise ValueError(f"the file is of {printable(str(value['ticker']))}, not {ticker}")
    fetched_text = value["fetched_at"]
    try:
        fetched_at = to_eastern(datetime.fromisoformat(fetched_text), "fetched_at")
    except (TypeError, ValueError):
        raise ValueError("fetched_at must be an ISO time with an offset") from None
    if et_isoformat(fetched_at) != fetched_text:
        raise ValueError("fetched_at must be written in New York time with its offset")
    source = value["source"]
    if source not in ("contracts", "eod"):
        raise ValueError("source must be contracts or eod")
    if _whole(value["window_days"], "window_days") != WINDOW_DAYS:
        raise ValueError(f"window_days must be {WINDOW_DAYS}; a file of another window is never read")
    if name is not None:
        match = RAW_NAME.fullmatch(name)
        if (
            match is None
            or match["date"] != session.isoformat()
            or match["token"] != timestamp_token(fetched_at)
        ):
            raise ValueError(f"the name must be {raw_name(session, fetched_at)} (or end _N.json.gz)")
    if not is_session(session):
        raise ValueError(f"{session} is not an XNYS trading session")
    close = session_close(session)
    if fetched_at < close:
        raise ValueError(
            f"fetched at {et_isoformat(fetched_at)}, before the session closed at {et_isoformat(close)}"
        )
    if fetched_at > to_eastern(now, "now"):
        raise ValueError(f"fetched_at {et_isoformat(fetched_at)} is later than the current time")
    requests = value["requests"]
    if (
        not isinstance(requests, list)
        or not requests
        or not all(isinstance(url, str) and allowed_url(url) for url in requests)
    ):
        raise ValueError("requests must list the token-free EODHD queries that supplied the file")
    expiries = _expiries(value["expiries"], session)
    rows = _items(value["rows"], "rows", source)
    traded = None if value["traded"] is None else _items(value["traded"], "traded", "traded")
    if (source == "contracts") != (traded is not None):
        raise ValueError("traded must be a list for the contracts source and null for the eod source")
    _check_rows(rows, expiries, session, ticker, source)
    if traded is not None:
        listed = {item.exp_date for item in expiries}
        seen: set[str] = set()
        for record in traded:
            if record.contract in seen:
                raise ValueError(f"traded lists {record.contract} more than once")
            seen.add(record.contract)
            if parse_occ(record.contract).root != ticker or record.expiry not in listed:
                raise ValueError(f"traded record {record.id} is not a listed contract of {ticker}")
        problem = proof_problem(session, rows, traded)
        if problem is not None:
            raise ValueError(problem)
    return Chain(session, ticker, fetched_at, source, tuple(requests), expiries, rows, traded)


def _expiries(value: object, session: date) -> tuple[Expiry, ...]:
    if not isinstance(value, list):
        raise ValueError("expiries must be a list")
    items: list[Expiry] = []
    last = session + timedelta(days=WINDOW_DAYS)
    for number, item in enumerate(value, start=1):
        if not isinstance(item, dict) or tuple(item) != ("exp_date", "contracts"):
            raise ValueError(f"expiries item {number} must hold exactly exp_date and contracts")
        expiry = parse_day(item["exp_date"]) if isinstance(item["exp_date"], str) else None
        if expiry is None or not session < expiry <= last:
            raise ValueError(
                f"expiries item {number} must be an expiry 1 to {WINDOW_DAYS} days after {session}"
            )
        if items and expiry <= items[-1].exp_date:
            raise ValueError("expiries must be listed once each, in date order")
        count = _whole(item["contracts"], f"expiries item {number} contracts")
        if count < 1:
            raise ValueError(f"expiries item {number} lists no contract")
        items.append(Expiry(expiry, count))
    return tuple(items)


def _check_rows(
    rows: Sequence[Record], expiries: Sequence[Expiry], session: date, ticker: str, source: Source
) -> None:
    listed: Mapping[date, int] = {item.exp_date: item.contracts for item in expiries}
    counts: dict[date, int] = {}
    seen: set[str] = set()
    for row in rows:
        if row.contract in seen:
            raise ValueError(f"rows list {row.contract} more than once")
        seen.add(row.contract)
        if parse_occ(row.contract).root != ticker:
            raise ValueError(f"row {row.id} is not a contract of {ticker}")
        if row.expiry not in listed:
            raise ValueError(f"row {row.id} expires {row.expiry}, not a listed expiry")
        if source == "eod" and row.date != session:
            raise ValueError(f"row {row.id} is not dated {session}")
        traded_on = row.attributes["tradetime"]
        if traded_on is not None and parse_day(traded_on) > session:
            raise ValueError(f"row {row.id} last traded on {traded_on}, after {session}")
        counts[row.expiry] = counts.get(row.expiry, 0) + 1
    for expiry, count in listed.items():
        held = counts.get(expiry, 0)
        if held != count:
            raise ValueError(f"the expiry {expiry} lists {count} contracts but rows hold {held}")


def read_chain(data: bytes, ticker: str, name: str, now: datetime) -> Chain:
    """Validate one raw file's bytes; every problem raises a one-line ``ValueError``."""
    return check_chain(load(data), ticker, name, now)
