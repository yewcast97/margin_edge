"""Plan, fetch, record and show: the look-back pipeline over the raw files.

The window is the ``lookback`` XNYS sessions ending at the latest completed session; the
span adds the ``percentile.WINDOW - 1`` sessions before it, which the window's percentiles
rest on. The prices are current when the newest prices file ends at the latest completed
session and starts no later than the session before the earliest one a row needs (the
span's first, or an older fetched one), so every row's return has both its bars.

``plan`` lists, per ticker, the window sessions without a fetched chain (newest first), how
many sessions before the window lack one, whether the prices are current, the invalid raw
files and whether the CSV and the newest report of the window are current; its action is
``fetch``, ``record`` or ``reuse``. ``fetch`` first requests from Tiingo the prices of every
ticker whose prices are not current, one request each, then writes the missing chains of the
span (``fetch`` module): the latest session of every ticker, then the older sessions ticker
by ticker, until the run's budget, EODHD's daily quota or an interruption stops it cleanly.
No answer of Tiingo stops the chains. ``record`` rewrites the formatted CSV from ``raw/`` and
writes a new report (the chart and its Markdown twin) each time it runs, when the span is
complete and the prices current, or when ``--partial`` is given. ``show`` prints the window
as Markdown.

A report is fresh while its twin and its chart are exactly what ``record`` would write now,
at the time in the report's name. Reports are never overwritten; every time printed is New
York time.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from market_state_research.common.layout import DataLayout, name_instant, newest, stamped, write_file
from market_state_research.common.sessions import completed_session, previous_session, session_window
from market_state_research.common.text import ticker_symbol
from market_state_research.common.times import et_isoformat, to_eastern
from market_state_research.common.watchlist import domain_watchlist, stock_tickers

from .chart import ChartSpec, load_library, render_html, render_markdown
from .client import BudgetSpent, EodhdClient, QuotaExceeded
from .fetch import Outcome, fetch_prices, history, latest, write_chain
from .percentile import WINDOW
from .store import (
    DATA_DIRECTORY,
    REASONS,
    SERIES,
    VALUES,
    Capture,
    InvalidFile,
    PriceFile,
    Row,
    csv_path,
    csv_text,
    derive,
    read_raw,
    select,
    select_prices,
    write_csv,
)
from .tiingo import Stopped, TiingoClient, TiingoError

DEFAULT_LOOKBACK = 50
DEFAULT_BUDGET = 9000  # requests; the product allows 10,000 a day (100,000 calls at 10 each)
WATCHLIST = domain_watchlist(DATA_DIRECTORY.parent)  # the default of plan and fetch without tickers
INTERRUPTED = "the run was interrupted; every chain written is kept; run fetch again"


@dataclass(frozen=True)
class Report:
    """The newest report of a window: ``fresh``, ``stale`` (with a reason) or ``missing``."""

    status: str
    path: Path | None = None
    reason: str | None = None

    def describe(self) -> dict[str, str | None]:
        return {
            "status": self.status,
            "path": None if self.path is None else str(self.path),
            "reason": self.reason,
        }


@dataclass(frozen=True)
class State:
    """One ticker's validated raw files, rows and CSV for one window.

    ``span`` is the window and the ``WINDOW - 1`` sessions before it; ``rows`` holds every
    fetched session's row, those before the span included; ``prices`` is the newest valid
    prices file.
    """

    ticker: str
    as_of: date
    lookback: int
    window: tuple[date, ...]
    span: tuple[date, ...]
    sessions: dict[date, Capture]
    prices: PriceFile | None
    invalid: tuple[InvalidFile, ...]
    rows: dict[date, Row]
    csv: Path

    @property
    def window_rows(self) -> tuple[Row, ...]:
        return tuple(self.rows[session] for session in self.window if session in self.rows)

    @property
    def missing(self) -> tuple[date, ...]:
        """Window sessions without a fetched chain, ascending."""
        return tuple(session for session in self.window if session not in self.sessions)

    @property
    def missing_history(self) -> tuple[date, ...]:
        """Sessions before the window, within the span, without a fetched chain, ascending."""
        start = self.window[0]
        return tuple(session for session in self.span if session < start and session not in self.sessions)

    @property
    def prices_start(self) -> date:
        """The first day the prices must hold: the session before the earliest one a row needs
        (the span's first, or an older fetched one), whose bar its return rests on."""
        return previous_session(min([self.span[0], *self.sessions]))

    @property
    def prices_problem(self) -> str | None:
        """Why the prices are not current, or None when they are."""
        if self.prices is None:
            return "no prices are fetched"
        found = self.prices.prices
        if found.end != self.as_of:
            return f"the prices end {found.end}, before the latest completed session {self.as_of}"
        if found.start > self.prices_start:
            return f"the prices start {found.start}, after {self.prices_start}, the first day the rows need"
        return None

    def to_fetch(self, refresh: bool = False) -> tuple[date, ...]:
        """The span sessions to fetch, newest first: the missing ones, and with ``refresh`` every
        window session."""
        chosen = set(self.missing) | set(self.missing_history)
        if refresh:
            chosen |= set(self.window)
        return tuple(sorted(chosen, reverse=True))

    @property
    def csv_current(self) -> bool:
        """Whether the CSV holds exactly what ``record`` would write from every fetched session."""
        return self.csv.is_file() and self.csv.read_bytes() == csv_text(self.rows.values()).encode()

    def action(self, report: Report) -> str:
        if self.missing or self.missing_history or self.prices_problem is not None:
            return "fetch"
        return "reuse" if self.csv_current and report.status == "fresh" else "record"

    def spec(self, layout: DataLayout, now: datetime) -> ChartSpec:
        return ChartSpec(
            ticker=self.ticker,
            as_of=self.as_of,
            lookback=self.lookback,
            window=self.window,
            rows=self.window_rows,
            generated_at=now,
            csv=self.csv.relative_to(layout.root).as_posix(),
        )

    def refuse_invalid(self) -> None:
        if self.invalid:
            listed = "; ".join(f"{item.path}: {item.reason}" for item in self.invalid)
            raise ValueError(
                f"{self.ticker}: {len(self.invalid)} raw file(s) failed validation ({listed}); "
                "rename each with the suffix .rejected, then run the command again"
            )


def _report_stem(ticker: str, as_of: date, lookback: int) -> str:
    return f"{ticker}_{as_of.isoformat()}_{lookback}s"


def _holds(path: Path, text: str) -> bool:
    return path.is_file() and path.read_bytes() == text.encode()


def _report(layout: DataLayout, state: State, now: datetime) -> Report:
    stem = _report_stem(state.ticker, state.as_of, state.lookback)
    path = newest(layout.reports(state.ticker), f"{stem}_", ".html", now)
    if path is None:
        return Report("missing")
    made = name_instant(path.name)
    if made is None or not state.window_rows:
        return Report("stale", path, f"{path.stem} differs from the report rendered now")
    spec = state.spec(layout, made)
    if not (
        _holds(path.with_suffix(".md"), render_markdown(spec))
        and _holds(path, render_html(spec, load_library()))
    ):
        return Report("stale", path, f"{path.stem} differs from the report rendered now")
    return Report("fresh", path)


def resolve(layout: DataLayout, ticker: str, lookback: int, now: datetime) -> State:
    """Validate every raw file of ``ticker``, select each session's chain and derive the rows."""
    symbol = ticker_symbol(ticker)
    now = to_eastern(now, "now")
    as_of = completed_session(now)
    raw = read_raw(layout, symbol, now)
    sessions = select(raw.captures)
    prices = select_prices(raw.prices)
    return State(
        ticker=symbol,
        as_of=as_of,
        lookback=lookback,
        window=session_window(as_of, lookback),
        span=session_window(as_of, lookback + WINDOW - 1),
        sessions=sessions,
        prices=prices,
        invalid=raw.invalid,
        rows=derive(sessions, prices),
        csv=csv_path(layout, symbol),
    )


def _symbols(tickers: Sequence[str], watchlist: Path) -> list[str]:
    return list(dict.fromkeys(ticker_symbol(ticker) for ticker in (tickers or stock_tickers(watchlist))))


def _invalid(state: State) -> list[dict[str, str]]:
    return [{"path": str(item.path), "reason": item.reason} for item in state.invalid]


def _range(sessions: Sequence[date]) -> dict[str, Any]:
    ordered = sorted(sessions)
    return {
        "sessions": len(ordered),
        "first": ordered[0].isoformat() if ordered else None,
        "last": ordered[-1].isoformat() if ordered else None,
    }


def _window(state: State) -> dict[str, Any]:
    return {
        "start": state.window[0].isoformat(),
        "end": state.window[-1].isoformat(),
        "sessions": len(state.window),
        "span_start": state.span[0].isoformat(),
    }


def _prices_path(layout: DataLayout, state: State) -> str | None:
    return None if state.prices is None else str(layout.raw(state.ticker) / state.prices.source)


def _prices(layout: DataLayout, state: State) -> dict[str, Any]:
    found = None if state.prices is None else state.prices.prices
    problem = state.prices_problem
    return {
        "status": "missing" if found is None else "stale" if problem is not None else "current",
        "path": _prices_path(layout, state),
        "start": None if found is None else found.start.isoformat(),
        "end": None if found is None else found.end.isoformat(),
        "bars": None if found is None else len(found.bars),
        "reason": problem,
    }


def _gaps(state: State) -> list[dict[str, str | None]]:
    gaps: list[dict[str, str | None]] = []
    for row in state.window_rows:
        for series in SERIES:
            if VALUES[series](row) is None:
                gaps.append({"date": row.date.isoformat(), "series": series, "reason": REASONS[series](row)})
    return gaps


def plan(
    layout: DataLayout,
    tickers: Sequence[str],
    lookback: int,
    now: datetime,
    refresh: bool = False,
    *,
    watchlist: Path = WATCHLIST,
) -> dict[str, Any]:
    """Read-only: per ticker, what to fetch, which raw files are invalid and the action.

    Without tickers, the ``stock`` section of the ``watchlist`` file is planned; explicit
    tickers never read the file. ``refresh`` lists every window session for fetching.
    """
    now = to_eastern(now, "now")
    entries = []
    for symbol in _symbols(tickers, watchlist):
        state = resolve(layout, symbol, lookback, now)
        report = _report(layout, state, now)
        missing = tuple(reversed(state.window)) if refresh else tuple(reversed(state.missing))
        entries.append(
            {
                "ticker": symbol,
                "action": "fetch" if refresh else state.action(report),
                "as_of": state.as_of.isoformat(),
                "window": _window(state),
                "missing_sessions": [session.isoformat() for session in missing],
                "missing_history": _range(state.missing_history),
                "prices": _prices(layout, state),
                "gaps": _gaps(state),
                "invalid_files": _invalid(state),
                "csv": str(state.csv) if state.csv.is_file() else None,
                "report": report.describe(),
            }
        )
    return {
        "generated_at": et_isoformat(now),
        "as_of": completed_session(now).isoformat(),
        "lookback": lookback,
        "refresh": refresh,
        "tickers": entries,
    }


@dataclass
class _Run:
    """One ticker's part of a fetch run: what it needs, not its rows."""

    ticker: str
    as_of: date
    to_fetch: tuple[date, ...]
    invalid: list[dict[str, str]]
    prices_due: tuple[date, date] | None  # the range to request, or None when the prices are current
    prices: dict[str, str | None]
    outcome: Outcome = field(default_factory=Outcome)
    requests: int = 0

    def describe(self) -> dict[str, Any]:
        outcome = self.outcome
        remaining = sorted(set(self.to_fetch) - set(outcome.written))
        return {
            "ticker": self.ticker,
            "prices": self.prices,
            "fetched": _range(outcome.written),
            "empty": [day.isoformat() for day in sorted(outcome.empty)],
            "pending": [day.isoformat() for day in sorted(outcome.pending)],
            "fallbacks": [{"date": day.isoformat(), "reason": reason} for day, reason in outcome.fallbacks],
            "remaining": _range(remaining),
            "requests": self.requests,
            "invalid_files": self.invalid,
        }


def _price_entry(status: str, path: str | None = None, reason: str | None = None) -> dict[str, str | None]:
    return {"status": status, "path": path, "reason": reason}


def _fetch_prices(
    tiingo: TiingoClient, layout: DataLayout, run: _Run, halted: str | None
) -> dict[str, str | None]:
    """Run's prices from Tiingo, or why there are none; ``halted`` names the ticker at which
    Tiingo stopped the run."""
    if run.prices_due is None:
        return run.prices
    if halted is not None:
        return _price_entry("stopped", reason=f"not requested: Tiingo stopped the run at {halted}")
    start, end = run.prices_due
    try:
        found = fetch_prices(tiingo, layout, run.ticker, start, end)
    except Stopped as error:
        return _price_entry("stopped", reason=str(error))
    except TiingoError as error:
        return _price_entry("failed", reason=str(error))
    if found.status == "pending":
        return _price_entry("pending", reason=f"Tiingo has not published {end} yet; run fetch again later")
    return _price_entry(found.status, None if found.path is None else str(found.path))


def fetch(
    layout: DataLayout,
    tickers: Sequence[str],
    lookback: int,
    now: datetime,
    client: EodhdClient,
    tiingo: TiingoClient,
    refresh: bool = False,
    *,
    watchlist: Path = WATCHLIST,
) -> dict[str, Any]:
    """Write each ticker's prices when they are not current, then the missing chains of its
    span (see the module docstring).

    Tiingo is asked first, one request per ticker: a ticker's prices are ``new`` or
    ``empty`` (written), ``reused`` (current already), ``pending`` (Tiingo has not published
    the latest session), ``failed`` (that request failed) or ``stopped`` (Tiingo refused the
    key or its request limit is reached: no later ticker's prices are requested). Then the
    latest session of every ticker is fetched from the contracts listing, and each ticker's
    older sessions by sweeps, in ticker order. EODHD's daily quota (HTTP 402), the client's
    budget or an interruption (``KeyboardInterrupt``: Ctrl-C, or SIGTERM as the command line
    turns it) stops the run cleanly: every file written is kept, ``stopped`` names the ticker
    and the reason, and each ticker's ``requests`` counts every request sent for it, so that
    they add up to the run's. Any other EODHD failure raises.
    """
    now = to_eastern(now, "now")
    runs = []
    for symbol in _symbols(tickers, watchlist):
        state = resolve(layout, symbol, lookback, now)
        due = (state.prices_start, state.as_of) if refresh or state.prices_problem is not None else None
        runs.append(
            _Run(
                ticker=state.ticker,
                as_of=state.as_of,
                to_fetch=state.to_fetch(refresh),
                invalid=_invalid(state),
                prices_due=due,
                prices=_price_entry("reused", _prices_path(layout, state)),
            )
        )
    halted: str | None = None
    for run in runs:
        run.prices = _fetch_prices(tiingo, layout, run, halted)
        if run.prices["status"] == "stopped" and halted is None:
            halted = run.ticker
    stopped: dict[str, str] | None = None
    current: _Run | None = None
    try:
        for run in runs:
            current = run
            session = run.as_of
            if session not in run.to_fetch:
                continue
            before = client.requests
            try:
                found = latest(client, run.ticker, session)
            finally:
                run.requests += client.requests - before
            if found.chain is not None:
                run.outcome.files.append(write_chain(layout, found.chain))
                run.outcome.written.append(session)
            elif found.pending:
                run.outcome.pending.append(session)
            else:
                run.outcome.fallbacks.append((session, found.reason or ""))
        for run in runs:
            current = run
            older = [
                day
                for day in run.to_fetch
                if day not in run.outcome.written and day not in run.outcome.pending
            ]
            before = client.requests
            try:
                history(client, layout, run.ticker, older, run.outcome)
            finally:
                run.requests += client.requests - before
    except (QuotaExceeded, BudgetSpent) as error:
        stopped = {"ticker": "" if current is None else current.ticker, "reason": str(error)}
    except KeyboardInterrupt:
        stopped = {"ticker": "" if current is None else current.ticker, "reason": INTERRUPTED}
    return {
        "generated_at": et_isoformat(now),
        "as_of": completed_session(now).isoformat(),
        "lookback": lookback,
        "refresh": refresh,
        "eodhd_key": "set",
        "tiingo_key": "set",
        "budget": client.budget,
        "requests": client.requests,
        "price_requests": tiingo.requests,
        "tickers": [run.describe() for run in runs],
        "stopped": stopped,
    }


def _pending_reason(state: State) -> str:
    parts = []
    if state.missing:
        parts.append(f"{len(state.missing)} of {state.lookback} window sessions are not fetched")
    if state.missing_history:
        count = len(state.missing_history)
        parts.append(
            f"{count} of the {WINDOW - 1} sessions before the window the percentiles need are not fetched"
        )
    if state.prices_problem is not None:
        parts.append(state.prices_problem)
    return "; ".join(parts) + "; run fetch or pass --partial"


def _decimal(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def _session(row: Row) -> dict[str, Any]:
    item = row.surface
    return {
        "date": row.date.isoformat(),
        "fetched_at": et_isoformat(row.fetched_at),
        "source": row.source,
        "method": item.method,
        "expiries": [expiry.isoformat() for expiry in item.expiries],
        **{series: _decimal(VALUES[series](row)) for series in SERIES},
        "call25_iv_14d_pct": _decimal(item.call25.value),
        "put25_iv_14d_pct": _decimal(item.put25.value),
        "daily_return_pct": _decimal(row.daily_return.value),
    }


def record(
    layout: DataLayout, ticker: str, lookback: int, now: datetime, partial: bool = False
) -> dict[str, Any]:
    """Rewrite the CSV from ``raw/`` and write a new report of the window.

    Every raw file of the ticker must be valid and, with ``partial``, a chain of the window
    fetched. The report is written whenever the span is complete (every window session and
    every session before it that the percentiles need fetched) and the prices are current,
    or with ``partial``, whether or not ``plan`` calls the newest one fresh. It is rendered
    in memory before any write, and a report of the same second refuses the run.
    """
    now = to_eastern(now, "now")
    state = resolve(layout, ticker, lookback, now)
    state.refuse_invalid()
    if not state.window_rows and (partial or not state.sessions):
        raise ValueError(
            f"{state.ticker}: no session of the {lookback}-session window has a raw chain; "
            "fetch at least one before recording"
        )
    report: dict[str, Any]
    documents: list[tuple[Path, str]] = []
    if (state.missing or state.missing_history or state.prices_problem is not None) and not partial:
        report = {"status": "pending", "path": None, "markdown": None, "reason": _pending_reason(state)}
    else:
        spec = state.spec(layout, now.replace(microsecond=0))  # the instant its name gives
        stem, directory = _report_stem(state.ticker, state.as_of, lookback), layout.reports(state.ticker)
        twin, chart = directory / stamped(stem, now, ".md"), directory / stamped(stem, now, ".html")
        # The twin first, so a chart's presence (what freshness reads) implies its twin's.
        documents = [(twin, render_markdown(spec)), (chart, render_html(spec, load_library()))]
        report = {"status": "written", "path": str(chart), "markdown": str(twin), "reason": None}
    written = write_csv(state.csv, state.rows.values())
    for path, document in documents:
        write_file(path, document)
    return {
        "ticker": state.ticker,
        "as_of": state.as_of.isoformat(),
        "lookback": lookback,
        "window": _window(state),
        "sessions": [_session(row) for row in state.window_rows],
        "missing_sessions": [session.isoformat() for session in state.missing],
        "missing_history": _range(state.missing_history),
        "gaps": _gaps(state),
        "csv": {"path": str(state.csv), "rows": len(state.rows), "written": written},
        "report": report,
    }


def show(layout: DataLayout, ticker: str, lookback: int, now: datetime) -> str:
    """The window as Markdown, recomputed from ``raw/``, after one status line."""
    now = to_eastern(now, "now")
    state = resolve(layout, ticker, lookback, now)
    state.refuse_invalid()
    report = _report(layout, state, now)
    status = (
        f"Action: {state.action(report)}. CSV: {state.csv if state.csv.is_file() else 'none'}. "
        f"Report: {report.path or 'none'} ({report.status})."
    )
    if not state.window_rows:
        return f"{status}\n\nNo session of the {lookback}-session window has a raw chain.\n"
    return f"{status}\n\n{render_markdown(state.spec(layout, now))}"
