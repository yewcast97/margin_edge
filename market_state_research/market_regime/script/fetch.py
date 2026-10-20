"""Fetching chains from EODHD (the latest session from the contracts listing, older ones by
sweeps) and daily prices from Tiingo.

EODHD has no filter on a record's date, so a session's chain is reached in one of two ways:

- **The latest completed session** (``latest``): the contracts listing holds every contract
  with its latest values, so the listing of the expiries 1 to ``WINDOW_DAYS`` days out gives
  the whole chain, all of which is kept, and the ``eod`` records of the contracts last
  traded on the session (``tradetime_eq``) are asked for beside it. Those dated the session
  prove that EODHD has published it and that the listing is its: each must equal its
  contract's listing row (``chain.proof_problem``). None dated the session: it is
  ``pending`` (not published yet) and nothing is written; a run later (or the next day's
  sweep) fetches it. A listing that fails the proof, or lists no contract, leaves the
  session to the sweeps.
- **Older sessions** (``history``): every expiry the contracts listing names between the
  first session's next day and ``WINDOW_DAYS`` days after the last is swept whole, from the
  latest expiry down, per type. Every record is assigned to the session its ``id`` dates
  when that session is one being fetched and the expiry lies 1 to ``WINDOW_DAYS`` days after
  it; records of other dates (holiday copies among them) are dropped. A session is complete,
  and written with every expiry's records, once every expiry after it within the window has
  been swept, so sessions are written newest first and a stop loses only the sweeps in
  progress. A session no expiry lists gets an empty chain: EODHD shows no contract then.

Every query is answered by one page (``api``). A full page is used up to its last key: a
listing is sorted by expiry and a sweep by strike, so every record of a key below the page's
last one is on it, and the next query starts at that last key (``_by_expiry``,
``_by_strike``). A page that holds a single key is narrowed instead: an expiry to each type,
a strike to its one contract (``filter[contract]``). Contracts whose OCC root is not the
ticker (adjusted series such as ``AAPL1``) are dropped on arrival. Every chain is checked with
``chain.check_chain`` before it is written; Python never modifies a raw file once written.

The prices (``fetch_prices``) take one request: Tiingo's daily bars of the range the rows
need. They are written when they hold the bar of the range's last session, or no bar at all
(Tiingo has no prices for the ticker); without that bar the session is ``pending`` (not
published yet) and nothing is written. Every prices file is checked with
``prices.check_prices`` before it is written.
"""

import calendar
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Final, Literal

from market_state_research.common.layout import DataLayout, FileExists, write_file
from market_state_research.common.text import printable

from .api import PAGE_LIMIT, Endpoint, Query, Record, page
from .chain import WINDOW_DAYS, Chain, Expiry, check_chain, dump, load, proof_problem, raw_name
from .client import EodhdClient, EodhdError
from .prices import Prices, check_prices, parse_bars
from .prices import dump as dump_prices
from .prices import raw_name as prices_name
from .tiingo import NotCovered, TiingoClient, TiingoError, prices_url

STEP: Final = Decimal("0.001")  # OCC strikes are whole thousandths
MAX_SUFFIX: Final = 99
Right = Literal["call", "put"]
RIGHTS: Final[tuple[Right, ...]] = ("call", "put")
Filters = tuple[tuple[str, str], ...]


@dataclass
class Outcome:
    """What one ticker's fetch did: the sessions written (empty chains among them), those pending
    and those the contracts listing could not supply."""

    written: list[date] = field(default_factory=list)
    empty: list[date] = field(default_factory=list)
    pending: list[date] = field(default_factory=list)
    fallbacks: list[tuple[date, str]] = field(default_factory=list)
    files: list[Path] = field(default_factory=list)


def write_chain(layout: DataLayout, chain: Chain) -> Path:
    """Check ``chain`` as every read will, then write it under the first free name; the path."""
    data = dump(chain)
    directory = layout.raw(chain.ticker)
    check_chain(load(data), chain.ticker, raw_name(chain.session, chain.fetched_at), chain.fetched_at)
    for number in range(MAX_SUFFIX + 1):
        name = raw_name(chain.session, chain.fetched_at, "" if number == 0 else f"_{number}")
        try:
            return write_file(directory / name, data)
        except FileExists:
            continue
    raise ValueError(f"{chain.ticker} {chain.session}: {MAX_SUFFIX + 1} raw files of one second exist")


# --------------------------------------------------------------------------- one-page queries


def occ(ticker: str, expiry: date, right: Right, strike: Decimal) -> str:
    """The OCC symbol of ``ticker``'s contract."""
    return f"{ticker}{expiry:%y%m%d}{'C' if right == 'call' else 'P'}{int(strike * 1000):08d}"


def _contract(
    client: EodhdClient, endpoint: Endpoint, ticker: str, symbol: str, extra: Filters, sent: list[str]
) -> list[Record]:
    """Every record of one contract; they must fit one page."""
    query = Query(endpoint, (("underlying_symbol", ticker), ("contract", symbol), *extra), "exp_date")
    answer = page(client, query)
    sent.append(query.url())
    if answer.more:
        raise EodhdError(f"{query.url()}: one contract holds more than {PAGE_LIMIT} records")
    return list(answer.records)


def _by_strike(
    client: EodhdClient,
    endpoint: Endpoint,
    ticker: str,
    expiry: date,
    right: Right,
    extra: Filters,
    sent: list[str],
) -> list[Record]:
    """Every record of one expiry and type, by strike: each full page up to its last strike, the
    next query from that strike on; a page of one strike only is read by its contract."""
    found: list[Record] = []
    low: Decimal | None = None
    while True:
        filters: list[tuple[str, str]] = [
            ("underlying_symbol", ticker),
            ("exp_date_eq", expiry.isoformat()),
            ("type", right),
            *extra,
        ]
        if low is not None:
            filters.append(("strike_from", format(low, "f")))
        query = Query(endpoint, tuple(filters), "strike")
        answer = page(client, query)
        sent.append(query.url())
        if not answer.more:
            return found + list(answer.records)
        if not answer.records:
            raise EodhdError(f"{query.url()}: an empty page names a further page")
        last = answer.records[-1].strike
        below = [record for record in answer.records if record.strike < last]
        if below:
            found.extend(below)
            low = last
        else:  # the page holds one strike: its contract alone, then the strikes above it
            found.extend(_contract(client, endpoint, ticker, occ(ticker, expiry, right, last), extra, sent))
            low = last + STEP


def _by_expiry(
    client: EodhdClient,
    endpoint: Endpoint,
    ticker: str,
    first: date,
    last: date,
    extra: Filters,
    sent: list[str],
) -> list[Record]:
    """Every record of ``endpoint`` expiring from ``first`` to ``last``, by expiry: each full page
    up to its last expiry, the next query from that expiry on; a page of one expiry only is read
    type by type."""
    found: list[Record] = []
    low = first
    while low <= last:
        filters = (
            ("underlying_symbol", ticker),
            *extra,
            ("exp_date_from", low.isoformat()),
            ("exp_date_to", last.isoformat()),
        )
        query = Query(endpoint, filters, "exp_date")
        answer = page(client, query)
        sent.append(query.url())
        if not answer.more:
            return found + list(answer.records)
        if not answer.records:
            raise EodhdError(f"{query.url()}: an empty page names a further page")
        newest = answer.records[-1].expiry
        below = [record for record in answer.records if record.expiry < newest]
        if below:
            found.extend(below)
            low = newest
        else:  # the page holds one expiry: each type alone, then the expiries after it
            for right in RIGHTS:
                found.extend(_by_strike(client, endpoint, ticker, newest, right, extra, sent))
            low = newest + timedelta(days=1)
    return found


# --------------------------------------------------------------------------- the latest session


def _counts(rows: Sequence[Record]) -> tuple[Expiry, ...]:
    counts: dict[date, int] = {}
    for row in rows:
        counts[row.expiry] = counts.get(row.expiry, 0) + 1
    return tuple(Expiry(expiry, counts[expiry]) for expiry in sorted(counts))


@dataclass(frozen=True)
class Latest:
    """The latest session from the contracts listing: its chain, pending, or why the sweeps fetch it."""

    chain: Chain | None = None
    pending: bool = False
    reason: str | None = None


def latest(client: EodhdClient, ticker: str, session: date) -> Latest:
    """The chain of the latest completed ``session`` from the contracts listing (see the module docstring)."""
    first, last = session + timedelta(days=1), session + timedelta(days=WINDOW_DAYS)
    sent: list[str] = []
    listing = [
        row for row in _by_expiry(client, "contracts", ticker, first, last, (), sent) if row.root == ticker
    ]
    traded_on = (("tradetime_eq", session.isoformat()),)
    traded = [
        row
        for row in _by_expiry(client, "eod", ticker, first, last, traded_on, sent)
        if row.root == ticker and row.date == session
    ]
    if not listing:
        return Latest(reason="the contracts listing names no contract expiring within the window")
    if not traded:
        return Latest(pending=True)
    problem = proof_problem(session, listing, traded)
    if problem is not None:
        return Latest(reason=problem)
    chain = Chain(
        session=session,
        ticker=ticker,
        fetched_at=client.now(),
        source="contracts",
        requests=tuple(dict.fromkeys(sent)),
        expiries=_counts(listing),
        rows=tuple(listing),
        traded=tuple(traded),
    )
    try:
        check_chain(load(dump(chain)), ticker, None, chain.fetched_at)
    except ValueError as error:
        return Latest(reason=str(error))
    return Latest(chain=chain)


# --------------------------------------------------------------------------- the sweeps


def months(first: date, last: date) -> list[tuple[date, date]]:
    """The calendar months from ``first`` to ``last``, cut to them, latest first."""
    spans: list[tuple[date, date]] = []
    start = first
    while start <= last:
        end = date(start.year, start.month, calendar.monthrange(start.year, start.month)[1])
        spans.append((start, min(end, last)))
        start = end + timedelta(days=1)
    return spans[::-1]


@dataclass
class _Session:
    """What the sweeps have found so far for one session being fetched: each swept expiry's records."""

    rows: dict[date, list[Record]] = field(default_factory=dict)
    requests: list[str] = field(default_factory=list)


def _assign(found: Sequence[Record], expiry: date, sessions: dict[date, _Session]) -> None:
    """Add one swept expiry's records to the sessions they are dated, where the expiry is in their window."""
    by_session: dict[date, list[Record]] = {}
    seen: set[str] = set()
    for record in found:
        if record.id in seen:
            raise EodhdError(f"EODHD returned the record {record.id} twice")
        seen.add(record.id)
        day = record.date
        if day is None or day not in sessions or not day < expiry <= day + timedelta(days=WINDOW_DAYS):
            continue
        by_session.setdefault(day, []).append(record)
    for day, rows in by_session.items():
        sessions[day].rows[expiry] = rows


def _session_chain(ticker: str, day: date, item: _Session, fetched_at: datetime) -> Chain:
    expiries = tuple(Expiry(expiry, len(item.rows[expiry])) for expiry in sorted(item.rows))
    rows = tuple(
        row for expiry in sorted(item.rows) for row in sorted(item.rows[expiry], key=lambda row: row.contract)
    )
    return Chain(
        session=day,
        ticker=ticker,
        fetched_at=fetched_at,
        source="eod",
        requests=tuple(dict.fromkeys(item.requests)),
        expiries=expiries,
        rows=rows,
        traded=None,
    )


def history(
    client: EodhdClient,
    layout: DataLayout,
    ticker: str,
    sessions: Sequence[date],
    outcome: Outcome,
) -> None:
    """Fetch ``sessions`` by sweeps (see the module docstring), writing each as it completes."""
    pending = {day: _Session() for day in sorted(set(sessions))}
    if not pending:
        return
    first = min(pending) + timedelta(days=1)
    last = max(pending) + timedelta(days=WINDOW_DAYS)

    def complete(floor: date) -> None:
        """Write every pending session from ``floor`` on: each expiry after it is known and swept."""
        for day in sorted((day for day in pending if day >= floor), reverse=True):
            chain = _session_chain(ticker, day, pending.pop(day), client.now())
            outcome.files.append(write_chain(layout, chain))
            outcome.written.append(day)
            if not chain.expiries:
                outcome.empty.append(day)

    for start, end in months(first, last):
        sent: list[str] = []
        contracts = _by_expiry(client, "contracts", ticker, start, end, (), sent)
        for day, item in pending.items():
            if day < end and start <= day + timedelta(days=WINDOW_DAYS):  # the month meets the window
                item.requests.extend(sent)
        expiries = sorted({row.expiry for row in contracts if row.root == ticker}, reverse=True)
        for position, expiry in enumerate(expiries):
            queries: list[str] = []
            found = [
                record
                for right in RIGHTS
                for record in _by_strike(client, "eod", ticker, expiry, right, (), queries)
                if record.root == ticker
            ]
            for day, item in pending.items():
                if day < expiry <= day + timedelta(days=WINDOW_DAYS):
                    item.requests.extend(queries)
            _assign(found, expiry, pending)
            # Every expiry from the month's first day on is known; those after the next unswept one are swept.
            floor = start - timedelta(days=1)
            if position + 1 < len(expiries):
                floor = max(floor, expiries[position + 1])
            complete(floor)
        complete(start - timedelta(days=1))
    complete(date.min)


# --------------------------------------------------------------------------- the prices


@dataclass(frozen=True)
class PricesFetch:
    """What one prices request gave: ``new`` or ``empty`` with the file written, or ``pending``
    (Tiingo has not published the range's last session yet) with nothing written."""

    status: Literal["new", "empty", "pending"]
    path: Path | None = None


def write_prices(layout: DataLayout, item: Prices) -> Path:
    """Check ``item`` as every read will, then write it under the first free name; the path."""
    data = dump_prices(item)
    directory = layout.raw(item.ticker)
    check_prices(load(data), item.ticker, prices_name(item.end, item.fetched_at), item.fetched_at)
    for number in range(MAX_SUFFIX + 1):
        name = prices_name(item.end, item.fetched_at, "" if number == 0 else f"_{number}")
        try:
            return write_file(directory / name, data)
        except FileExists:
            continue
    raise ValueError(f"{item.ticker} prices to {item.end}: {MAX_SUFFIX + 1} raw files of one second exist")


def fetch_prices(
    tiingo: TiingoClient, layout: DataLayout, ticker: str, start: date, end: date
) -> PricesFetch:
    """Request ``ticker``'s daily bars from ``start`` to ``end`` (see the module docstring).

    A refused or failed request raises ``TiingoError`` (``tiingo``), and so does an answer
    that is not Tiingo's bars or bars that fail ``prices.check_prices``, naming the URL.
    """
    url = prices_url(ticker, start, end)
    try:
        bars = parse_bars(tiingo.get(url))
    except NotCovered:
        bars = ()
    except ValueError as error:
        raise TiingoError(
            f"GET {url}: the response is not Tiingo's daily prices: {printable(str(error))}"
        ) from None
    if bars and all(bar.day != end for bar in bars):
        return PricesFetch("pending")
    try:
        path = write_prices(layout, Prices(ticker, start, end, tiingo.now(), url, bars))
    except ValueError as error:
        raise TiingoError(f"GET {url}: {printable(str(error))}") from None
    return PricesFetch("new" if bars else "empty", path)
