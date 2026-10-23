"""Fetch, plan, derive, check, render and show: the fundamentals pipeline over ``raw/``,
``formatted/`` and ``reports/``.

``fetch`` is the domain's one network step, under two clients ``__main__`` builds from the
user's settings: EDGAR (``client.EdgarClient``) and EarningsCalls.dev
(``earningscalls.EarningsCallsClient``). For each ticker (by default each ``stock`` ticker of
the watchlist ``__main__`` passes) it looks the CIK up in EDGAR's ``company_tickers.json``
(requested once per run), reads the company's submissions JSON and writes it to
``raw/{T}/submissions_{token}.json`` unless its bytes equal the newest such file's, and lists
the seasons (``filings.select_seasons``). For each season of the span (the seasons the
``Window`` admits and the ``items.BASELINE_SEASONS`` before them, whose documents the
window's readings compare with), oldest first, it writes the season's 10-K or 10-Q, then each
filing Rule B places in the season, in order: an 8-K's filing index page (read before it is
written), its primary document and every ``EX-99`` exhibit the page lists; a proxy
statement's or a schedule's primary document; a Form 4's XML (read before it is written).
Each lands at its path under ``raw/{T}/{PERIOD}/`` (``documents``), bytes as served; a file
already there is never rewritten, nor requested again without ``refresh``. Then it reads the
company facts and writes them to ``raw/{T}/companyfacts_{token}.json`` unless their bytes
equal the newest such file's. A failed request, or a body that does not read, aborts the run
with one line; nothing of that document is written, and the files written before it stay.
Filings Rule B leaves pending are listed when the window ends on or after the newest listed
season end, and none of their documents is requested; the rows Rule B cannot place are listed
as skipped; a window that starts before the oldest filing ``filings.recent`` lists is reported
``truncated``.

Then, for a ticker whose seasons are listed, the calls: when ``documents.RawState.events_due``
says so, it requests every page of the ticker's calls list, reads them strictly
(``earningscalls.check_capture``) and writes them as ``raw/{T}/calls_{token}_{PAGE}.json``;
then it writes the transcript of every call Rule B places in a span season to that season's
folder as ``transcript_{ID}.json``, each read against its listed call first and, without
``refresh``, never requested again once a copy is there. Pending calls are listed, never
requested. A list whose symbol names several issuers makes the ticker's calls ``unsupported``;
the provider's request limit (HTTP 429) stops every later request to it in the run, which goes
on with EDGAR alone (``stopped``).

With ``refresh`` (``--refresh``, run only when the user asks) ``fetch`` requests every span
document, the company facts, the calls list and every transcript again: an EDGAR document is
compared with its file (``verified`` or ``changed``, never rewritten), and a transcript whose
bytes changed is written beside the newest copy (``refreshed``).

The other commands work offline over ``documents.season_documents``, which validates every raw
file it reads. ``derive`` writes each document's derived text to
``formatted/{T}/{PERIOD}/{DOC_ID}.md`` and each season's ``measures.md`` (``measures``), each
only when it is missing or differs from its derivation. ``check`` parses and checks the bot's
readings of each season (``readings``). ``render`` writes a season's report
``reports/{T}/{PERIOD}/report_{token}.md`` (``report``), never over a file. ``plan`` says per
ticker what comes next, in this order: ``fetch`` while the former layout is in ``raw/``, no
season is listed, a span season's EDGAR document is not in ``raw/``, a raw file is invalid, no
valid company facts are in ``raw/``, a span season's call is ``missing`` or the calls list is
due (with ``refresh``, whenever the window holds a listed season); ``derive`` while a span
document's text or a window season's measures differ from their derivation; ``research`` while
a window season's readings are missing or fail ``check``; ``render`` while a window season's
newest report is not the report rendered now; else ``reuse``. ``show`` prints the newest
report of each ticker and their ranking by score.

Messages never repeat captured or private input, and the ``User-Agent`` and the
EarningsCalls.dev key reach this module only inside their clients. Every time is New York time.
"""

import os
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from functools import cached_property, partial
from pathlib import Path
from typing import Any, Literal

from market_state_research.common.layout import DataLayout, newest, stamped, write_file
from market_state_research.common.text import printable, ticker_symbol
from market_state_research.common.times import et_isoformat, to_eastern
from market_state_research.common.watchlist import domain_watchlist, stock_tickers

from .client import (
    COMPANYFACTS_LIMIT,
    DOCUMENT_LIMIT,
    INDEX_LIMIT,
    JSON_LIMIT,
    EdgarClient,
    archive_url,
    decode_document,
    index_url,
)
from .client import Fetched as EdgarFetched
from .documents import (
    COMPANYFACTS_PREFIX,
    FORMER,
    JSON_SUFFIX,
    SUBMISSIONS_PREFIX,
    Document,
    RawState,
    SeasonFiles,
    call_doc_id,
    calls_name,
    derive_call,
    derive_text,
    doc_id,
    filing_folder,
    layout_mode,
    read_raw,
    season_documents,
    season_folder,
    transcript_name,
)
from .earningscalls import (
    BODY_LIMIT,
    Ambiguous,
    CallEvent,
    EarningsCallsClient,
    Fetched,
    LimitReached,
    Turn,
    check_capture,
    check_issuer,
    parse_events_page,
    parse_transcript,
)
from .facts import read_companyfacts
from .filings import (
    TICKERS_FILE,
    Dated,
    Filing,
    Season,
    Window,
    default_window,
    lookup_cik,
    parse_filing_index,
    parse_submissions,
    select_seasons,
)
from .form4 import parse_form4
from .items import BASELINE_SEASONS, ITEMS
from .measures import Measures, baseline_seasons, season_measures
from .readings import Problem, Readings, Source, parse_readings, readings_problems
from .readings import Season as RulesSeason
from .report import entries, newest_report, ranking, render_report, report_name, same_report

WATCHLIST = domain_watchlist(Path(__file__).resolve().parent.parent)  # plan's, fetch's and show's default
MAX_READINGS_BYTES = 4 * 1024 * 1024
TEXT_LIMIT = 64 * 1024 * 1024  # a derived text file: at most what a 50 MiB document derives
READINGS = "readings.md"
MEASURES = "measures.md"
NOT_LISTED = "not in SEC company_tickers.json"
INVALID_RAW = (
    "{ticker}: {count} in raw/ failed validation; first: {path}: {reason}; "
    "run plan for the list and rename each with .rejected"
)
RENAME_AND_FETCH = "rename each with .rejected, then run fetch"
LIMIT_EARLIER = "not requested: EarningsCalls.dev's request limit was reached earlier in this run"
REFRESH_REASON = "--refresh: the span's documents, transcripts and calls list are requested again"
UNREADABLE = "the readings cannot be read: {error}"

Action = Literal["fetch", "derive", "research", "render", "reuse"]
FileStatus = Literal["new", "reused", "verified", "changed", "refreshed"]
TextStatus = Literal["present", "missing", "differs"]
TextWrite = Literal["published", "exists", "rewritten"]
Fresh = Literal["fresh", "stale", "missing"]


# --------------------------------------------------------------------------- shared helpers


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


def _invalid(files: Iterable[tuple[Path, str]]) -> list[dict[str, str]]:
    return [{"path": str(path), "reason": reason} for path, reason in files]


def _window_json(window: Window | None) -> dict[str, str] | None:
    if window is None:
        return None
    return {"from": window.start.isoformat(), "to": window.end.isoformat()}


def _dated_json(item: Dated) -> dict[str, Any]:
    return {
        "form": item.form,
        "accession": item.accession,
        "dated": item.dated.isoformat(),
        "filed": item.filed.isoformat(),
        "items": item.items,
    }


def _filing_identity(filing: Filing) -> dict[str, str]:
    return {
        "form": filing.form,
        "accession": filing.accession,
        "filed": filing.filed.isoformat(),
        "period": filing.period.isoformat(),
    }


def _calls_due(raw: RawState, window: Window, now: datetime, refresh: bool) -> str | None:
    """Why ``fetch`` asks for the calls list now (``RawState.events_due``), else, with ``refresh``,
    ``REFRESH_REASON`` while the window holds a listed season; None when it does not ask."""
    due = raw.events_due(window, now)
    if due is None and refresh and raw.within(window):
        return REFRESH_REASON
    return due


def _refuse_invalid(raw: RawState) -> None:
    """Refuse a command while the former layout is in ``raw/``, no season is listed or any raw
    file of the ticker fails validation."""
    if raw.former_layout:
        raise ValueError(f"{raw.ticker}: {raw.former_layout[0]} is {FORMER}")
    if raw.reason is not None:
        raise ValueError(f"{raw.ticker}: {raw.reason}")
    if raw.invalid_files:
        path, reason = raw.invalid_files[0]
        count = _plural(len(raw.invalid_files), "file")
        raise ValueError(INVALID_RAW.format(ticker=raw.ticker, count=count, path=path, reason=reason))


# --------------------------------------------------------------------------- fetch


class _TickerMap:
    """EDGAR's ``company_tickers.json``, requested on first use and at most once per run."""

    def __init__(self, client: EdgarClient) -> None:
        self._client = client
        self._body: str | None = None

    def cik(self, ticker: str) -> str | None:
        if self._body is None:
            fetched = self._client.company_tickers()
            try:
                self._body = fetched.body.decode("utf-8")
            except UnicodeDecodeError:
                raise ValueError(f"{TICKERS_FILE}: the body is not UTF-8") from None
        return lookup_cik(self._body, ticker)


def _unsupported(
    ticker: str,
    reason: str,
    window: Window,
    cik: str | None = None,
    entity_name: str | None = None,
    submissions: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "ticker": ticker,
        "status": "unsupported",
        "reason": reason,
        "cik": cik,
        "entity_name": entity_name,
        "submissions": submissions,
        "companyfacts": None,
        "window": _window_json(window),
        "truncated": None,
        "seasons": [],
        "pending_filings": [],
        "skipped_filings": [],
        "calls": None,
    }


def _compare(path: Path, body: bytes, limit: int) -> FileStatus:
    """``verified`` when the file at ``path`` holds exactly ``body``, else ``changed`` (a file that
    cannot be read too); the file is never rewritten."""
    try:
        return "verified" if read_raw(path, limit) == body else "changed"
    except ValueError:
        return "changed"


@dataclass(frozen=True)
class _Fetcher:
    """One ticker's fetch: where its raw files go, its CIK, the client and whether every document
    is requested again (``refresh``)."""

    raw: Path
    cik: str
    client: EdgarClient
    refresh: bool

    def _document(self, path: Path, url: str, check: Callable[[bytes], object] | None = None) -> FileStatus:
        """Write the document at ``url`` to ``path`` unless a file is there already; with ``refresh``,
        request it anyway and compare it with that file. ``check`` reads the body before it is
        written (a ``ValueError`` aborts the run)."""
        if not os.path.lexists(path):
            body = self.client.document(url).body
            if check is not None:
                try:
                    check(body)
                except ValueError as error:
                    raise ValueError(f"GET {url}: {error}") from None
            write_file(path, body)
            return "new"
        if not self.refresh:
            return "reused"
        return _compare(path, self.client.document(url).body, DOCUMENT_LIMIT)

    def _entry(self, path: Path, folder: str, status: FileStatus, quoted: bool) -> dict[str, Any]:
        return {"path": str(path), "doc_id": doc_id(folder, path.name) if quoted else None, "status": status}

    def filing(self, season: Season) -> dict[str, Any]:
        own = season.filing
        folder = filing_folder(own.form, own.period, own.accession)
        path = self.raw / season_folder(season.period) / folder / own.primary_document
        status = self._document(path, archive_url(self.cik, own.accession, own.primary_document))
        return {
            **_filing_identity(own),
            "doc_id": doc_id(folder, own.primary_document),
            "path": str(path),
            "status": status,
        }

    def _index(self, path: Path, item: Dated) -> tuple[FileStatus, list[str]]:
        """The 8-K's filing index page, unless it is in ``raw/`` already, and the exhibits it lists.
        The page is read before it is written; one in ``raw/`` that no longer reads aborts the run,
        naming the file."""
        url = index_url(self.cik, item.accession)
        status: FileStatus = "reused" if os.path.lexists(path) else "new"
        try:
            data = read_raw(path, INDEX_LIMIT) if status == "reused" else self.client.index_page(url).body
            rows = parse_filing_index(decode_document(data)[0], self.cik, item.accession).exhibits
        except ValueError as error:
            if status == "new":
                raise
            raise ValueError(f"{path}: {error}; rename it with .rejected and run fetch again") from None
        if status == "new":
            write_file(path, data)
        elif self.refresh:
            status = "verified" if self.client.index_page(url).body == data else "changed"
        return status, [row.document for row in rows]

    def dated(self, season: Season, item: Dated) -> dict[str, Any]:
        folder = filing_folder(item.form, item.dated, item.accession)
        directory = self.raw / season_folder(season.period) / folder
        files: list[dict[str, Any]] = []
        if item.form == "8-K":
            index_path = directory / f"{item.accession}-index.htm"
            status, exhibits = self._index(index_path, item)
            files.append(self._entry(index_path, folder, status, False))
            for name in (item.document, *exhibits):
                path = directory / name
                files.append(
                    self._entry(
                        path, folder, self._document(path, archive_url(self.cik, item.accession, name)), True
                    )
                )
        else:
            path = directory / item.document
            status = self._document(
                path,
                archive_url(self.cik, item.accession, item.document),
                parse_form4 if item.form == "4" else None,
            )
            files.append(self._entry(path, folder, status, item.form != "4"))
        return {**_dated_json(item), "files": files}


def _stamped_body(
    layout: DataLayout, ticker: str, prefix: str, fetched: EdgarFetched, limit: int
) -> tuple[Path, FileStatus]:
    """Write a body as ``{prefix}{token}.json`` unless its bytes equal the newest such file's."""
    directory = layout.raw(ticker)
    held = newest(directory, prefix, JSON_SUFFIX, fetched.fetched_at)
    if held is not None:
        try:
            if read_raw(held, limit) == fetched.body:
                return held, "reused"
        except ValueError:  # an invalid newest file is never the same body
            pass
    path = directory / stamped(prefix.rstrip("_"), fetched.fetched_at, JSON_SUFFIX)
    write_file(path, fetched.body)
    return path, "new"


def _submissions(
    layout: DataLayout, ticker: str, cik: str, client: EdgarClient
) -> tuple[dict[str, Any], str, datetime]:
    """Read the submissions JSON; write it unless its bytes equal the newest file's. The body and
    the time it arrived come last."""
    fetched = client.submissions(cik)
    try:
        body = fetched.body.decode("utf-8")
    except UnicodeDecodeError:
        raise ValueError("submissions: the body is not UTF-8") from None
    parse_submissions(body, cik)  # an unreadable body aborts the run before anything is written
    path, status = _stamped_body(layout, ticker, SUBMISSIONS_PREFIX, fetched, JSON_LIMIT)
    return {"path": str(path), "status": status}, body, fetched.fetched_at


def _companyfacts(layout: DataLayout, ticker: str, cik: str, client: EdgarClient) -> dict[str, Any]:
    """Read the company facts; write them unless their bytes equal the newest file's."""
    fetched = client.companyfacts(cik)
    try:
        read_companyfacts(fetched.body, cik)
    except ValueError as error:
        raise ValueError(f"GET {fetched.url}: {error}") from None
    path, status = _stamped_body(layout, ticker, COMPANYFACTS_PREFIX, fetched, COMPANYFACTS_LIMIT)
    return {"path": str(path), "status": status}


def span_seasons(seasons: Sequence[Season], window: Window) -> tuple[Season, ...]:
    """The window's seasons and the ``BASELINE_SEASONS`` listed seasons before the oldest of them."""
    inside = [position for position, season in enumerate(seasons) if window.admits(season.period)]
    if not inside:
        return ()
    return tuple(seasons[max(0, inside[0] - BASELINE_SEASONS) : inside[-1] + 1])


def _fetch_ticker(
    layout: DataLayout,
    ticker: str,
    client: EdgarClient,
    tickers: _TickerMap,
    window: Window,
    refresh: bool,
) -> tuple[dict[str, Any], datetime | None]:
    """The ticker's EDGAR step and the time its submissions arrived (None for a ticker EDGAR does
    not list): the raw tree is read as of then, or later, after the step."""
    cik = tickers.cik(ticker)
    if cik is None:
        return _unsupported(ticker, NOT_LISTED, window), None
    held, body, fetched_at = _submissions(layout, ticker, cik, client)
    submissions = parse_submissions(body, cik)
    try:
        listing = select_seasons(submissions)
    except ValueError as error:  # NoPeriodicFilings, two filings for one period, an undated release
        return _unsupported(ticker, str(error), window, cik, submissions.entity_name, held), fetched_at
    fetcher = _Fetcher(layout.raw(ticker), cik, client, refresh)
    span = span_seasons(listing.seasons, window)
    seasons = [
        {
            "season": season.period.isoformat(),
            "in_window": window.admits(season.period),
            "filing": fetcher.filing(season),
            "filings": [fetcher.dated(season, item) for item in season.fetched],
        }
        for season in span
    ]
    facts = _companyfacts(layout, ticker, cik, client) if span else None
    return {
        "ticker": ticker,
        "status": "fetched",
        "reason": None,
        "cik": cik,
        "entity_name": submissions.entity_name,
        "submissions": held,
        "companyfacts": facts,
        "window": _window_json(window),
        "truncated": listing.truncated(window),
        "seasons": seasons,
        "pending_filings": [_dated_json(item) for item in listing.pending_in(window)],
        "skipped_filings": [
            {
                "form": item.form,
                "accession": item.accession,
                "filed": item.filed.isoformat(),
                "reason": item.reason,
            }
            for item in listing.skipped
        ],
        "calls": None,
    }, fetched_at


def _request_events(client: EarningsCallsClient, ticker: str) -> list[Fetched]:
    """Every page of the ticker's calls list, read strictly before any is written.

    Page 1 tells how many pages there are; a list whose symbol names several issuers raises
    ``earningscalls.Ambiguous`` from page 1, before another page is requested. A body that
    does not read raises ``ValueError`` naming its URL.
    """
    fetched: list[Fetched] = []
    pages = []
    count = 1
    while len(fetched) < count:
        item = client.events_page(ticker, len(fetched) + 1)
        try:
            page = parse_events_page(item.body)
        except ValueError as error:
            raise ValueError(f"GET {item.url}: {error}") from None
        fetched.append(item)
        pages.append(page)
        if len(fetched) == 1:
            check_issuer(ticker, page)
            count = max(1, page.total_pages)
    try:
        check_capture(ticker, pages)
    except Ambiguous:
        raise
    except ValueError as error:
        raise ValueError(f"GET {fetched[0].url}: {error}") from None
    return fetched


def _transcript(
    directory: Path,
    client: EarningsCallsClient,
    event: CallEvent,
    season: date,
    held: Path | None,
    refresh: bool,
) -> dict[str, Any]:
    """Write the transcript of ``event`` unless a copy is in ``raw/`` already (``held``, the newest);
    its entry. With ``refresh`` it is requested anyway: bytes equal to the newest copy's leave it
    ``verified``, others are written beside it, named by the time they arrived (``refreshed``)."""
    path = directory / transcript_name(event.id) if held is None else held
    status: FileStatus = "reused"
    if refresh or not os.path.lexists(path):
        fetched = client.transcript(event.id)
        try:
            parse_transcript(fetched.body, event)
        except ValueError as error:
            raise ValueError(f"GET {fetched.url}: {error}") from None
        if not os.path.lexists(path):
            write_file(path, fetched.body)
            status = "new"
        elif _compare(path, fetched.body, BODY_LIMIT) == "verified":
            status = "verified"
        else:
            path = directory / transcript_name(event.id, fetched.fetched_at)
            write_file(path, fetched.body)
            status = "refreshed"
    return {
        **event.describe(),
        "season": season.isoformat(),
        "doc_id": call_doc_id(season, event.id),
        "path": str(path),
        "status": status,
    }


def _calls_entry(
    status: str,
    reason: str | None,
    events: dict[str, Any] | None,
    transcripts: list[dict[str, Any]],
    pending: Iterable[CallEvent] = (),
) -> dict[str, Any]:
    return {
        "status": status,
        "reason": reason,
        "events": events,
        "transcripts": transcripts,
        "pending_calls": [event.describe() for event in pending],
    }


def _fetch_calls(
    layout: DataLayout,
    ticker: str,
    client: EarningsCallsClient,
    window: Window,
    now: datetime,
    refresh: bool,
) -> dict[str, Any]:
    """The ticker's calls list when it is due, then the transcripts of its span seasons' calls; see
    the module docstring. The provider's request limit ends the step with the status ``stopped``
    and its line, keeping what was written before it."""
    raw = season_documents(layout, ticker, now)
    due = _calls_due(raw, window, now, refresh)
    events: dict[str, Any] | None = None
    transcripts: list[dict[str, Any]] = []
    try:
        if due is not None:
            try:
                fetched = _request_events(client, ticker)
            except Ambiguous as error:
                return _calls_entry("unsupported", str(error), None, [])
            fetched_at = fetched[0].fetched_at
            for number, item in enumerate(fetched, start=1):
                write_file(layout.raw(ticker) / calls_name(fetched_at, number), item.body)
            raw = season_documents(layout, ticker, max(to_eastern(now, "now"), fetched_at))
        if raw.capture is not None:
            events = {
                "status": "reused" if due is None else "new",
                "path": str(raw.capture.pages[0]),
                "pages": len(raw.capture.pages),
                "fetched_at": et_isoformat(raw.capture.fetched_at),
                "reason": due,
            }
        for files in raw.span(window):
            for event in files.call.events:
                held = raw.transcript_files.get(event.id)
                transcripts.append(_transcript(files.folder, client, event, files.day, held, refresh))
    except LimitReached as error:
        return _calls_entry("stopped", str(error), events, transcripts, raw.pending_in(window))
    return _calls_entry("fetched", None, events, transcripts, raw.pending_in(window))


def fetch(
    layout: DataLayout,
    tickers: Sequence[str],
    client: EdgarClient,
    calls: EarningsCallsClient,
    window: Window,
    now: datetime,
    *,
    refresh: bool = False,
    watchlist: Path = WATCHLIST,
) -> dict[str, Any]:
    """Write every ticker's submissions, the EDGAR documents of each span season not in ``raw/``
    yet and its company facts, then its calls list when due and its calls' transcripts; with
    ``refresh``, request all of them again (module docstring).

    Without tickers, the ``stock`` section of the ``watchlist`` file is fetched; explicit tickers
    never read the file. A ticker EDGAR does not list, or whose recent filings
    ``filings.select_seasons`` refuses, is ``unsupported`` and the run continues; so are a
    ticker's calls when the provider's symbol names several issuers. Once the provider's request
    limit is reached (``stopped``), no later ticker's calls are requested. A failed request
    raises ``client.EdgarError`` or ``earningscalls.EarningsCallsError`` and an unreadable body
    ``ValueError``, either aborting the run and keeping the files written before it.
    """
    tickers = tickers or stock_tickers(watchlist)
    symbols = list(dict.fromkeys(ticker_symbol(ticker) for ticker in tickers))
    ticker_map = _TickerMap(client)
    stopped: dict[str, str] | None = None
    results = []
    moment = to_eastern(now, "now")
    for symbol in symbols:
        result, fetched_at = _fetch_ticker(layout, symbol, client, ticker_map, window, refresh)
        if fetched_at is not None:
            moment = max(moment, fetched_at)  # the files the step wrote are named by later times
        if result["status"] == "fetched":
            if stopped is not None:
                result["calls"] = _calls_entry("stopped", LIMIT_EARLIER, None, [])
            else:
                result["calls"] = _fetch_calls(layout, symbol, calls, window, moment, refresh)
                if result["calls"]["status"] == "stopped":
                    stopped = {"ticker": symbol, "reason": result["calls"]["reason"]}
        results.append(result)
    return {
        "requests": client.requests,
        "user_agent": "set",
        "transcript_requests": calls.requests,
        "api_key": "set",
        "window": _window_json(window),
        "refresh": refresh,
        "stopped": stopped,
        "tickers": results,
    }


# --------------------------------------------------------------------------- texts


@dataclass
class _Texts:
    """Each document's derived text and text file, read once per command."""

    layout: DataLayout
    ticker: str
    derived_texts: dict[str, str] = field(default_factory=dict)
    call_turns: dict[str, tuple[Turn, ...]] = field(default_factory=dict)
    statuses: dict[str, TextStatus] = field(default_factory=dict)

    def path(self, document: Document) -> Path:
        return self.layout.formatted(self.ticker) / season_folder(document.season) / document.text_name

    def written(self, document: Document) -> str | None:
        """The text file's content; None when there is none, or none that reads as UTF-8 text
        within its limit (``derive`` writes it again)."""
        try:
            return read_raw(self.path(document), TEXT_LIMIT).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            return None

    def derived(self, document: Document) -> str:
        """A document's derived text, from ``raw/`` (once per command)."""
        if document.doc_id not in self.derived_texts:
            try:
                if document.kind == "call":
                    derived = derive_call(document)
                    self.derived_texts[document.doc_id] = derived.text
                    self.call_turns[document.doc_id] = derived.turns
                else:
                    self.derived_texts[document.doc_id] = derive_text(document)
            except ValueError as error:
                raise ValueError(f"{document.path}: {error}") from None
        return self.derived_texts[document.doc_id]

    def turns(self, document: Document) -> tuple[Turn, ...]:
        """A call's turns in its derived text; none for any other document."""
        if document.kind != "call":
            return ()
        self.derived(document)
        return self.call_turns[document.doc_id]

    def status(self, document: Document) -> TextStatus:
        """``present``, ``missing`` or ``differs`` (once per command)."""
        if document.doc_id not in self.statuses:
            written = self.written(document)
            if written is None:
                status: TextStatus = "differs" if os.path.lexists(self.path(document)) else "missing"
            else:
                status = "present" if written == self.derived(document) else "differs"
            self.statuses[document.doc_id] = status
        return self.statuses[document.doc_id]


# --------------------------------------------------------------------------- state


@dataclass(frozen=True)
class ReadingsCheck:
    """One season's readings and every problem ``check`` finds in them (valid without any)."""

    path: Path
    season: date
    readings: Readings | None
    problems: tuple[Problem, ...]

    @property
    def valid(self) -> bool:
        return not self.problems


@dataclass
class _State:
    """One ticker's raw files, derived texts, measures, readings and reports as of ``now``."""

    layout: DataLayout
    ticker: str
    now: datetime
    raw: RawState
    texts: _Texts
    measures_cache: dict[date, Measures] = field(default_factory=dict)
    checks_cache: dict[date, ReadingsCheck] = field(default_factory=dict)

    def measures(self, files: SeasonFiles) -> Measures:
        if files.day not in self.measures_cache:
            self.measures_cache[files.day] = season_measures(self.raw, files, self.texts.derived)
        return self.measures_cache[files.day]

    def measures_path(self, files: SeasonFiles) -> Path:
        return self.layout.formatted(self.ticker) / season_folder(files.day) / MEASURES

    def measures_status(self, files: SeasonFiles) -> Fresh:
        path = self.measures_path(files)
        if not os.path.lexists(path):
            return "missing"
        try:
            held = read_raw(path, TEXT_LIMIT).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            return "stale"
        return "fresh" if held == self.measures(files).text else "stale"

    def readings_path(self, files: SeasonFiles) -> Path:
        return self.layout.reports(self.ticker) / season_folder(files.day) / READINGS

    @cached_property
    def sources(self) -> dict[str, Source]:
        """Every document of every listed season a reading may name, as the rules see it."""
        texts = self.texts
        return {
            document.doc_id: Source(
                season=files.day,
                fresh=partial(lambda document: texts.status(document) == "present", document),
                call=document.kind == "call",
                layout=layout_mode(document),
                text=partial(texts.derived, document),
                turns=partial(texts.turns, document),
            )
            for files in self.raw.seasons
            for document in files.documents
        }

    def rules_season(self, files: SeasonFiles) -> RulesSeason:
        listing = self.raw.listing
        by_season = {
            held.day: tuple(document.doc_id for document in held.documents) for held in self.raw.seasons
        }
        baselines: dict[str, tuple[tuple[date, ...], tuple[str, ...]]] = {}
        if listing is not None:
            for item in ITEMS:
                if item.baseline not in baselines:
                    days = tuple(
                        season.period for season in baseline_seasons(listing, files.season, item.baseline)
                    )
                    baselines[item.baseline] = (
                        days,
                        tuple(doc for day in days for doc in by_season.get(day, ())),
                    )
        return RulesSeason(
            period=files.day,
            form=files.season.filing.form,
            proxy=bool(files.season.of_forms(("DEF 14A",))),
            call=files.call.status,
            documents=frozenset(document.doc_id for document in files.documents),
            sources=self.sources,
            baselines=baselines,
        )

    def check(self, files: SeasonFiles, path: Path | None = None) -> ReadingsCheck:
        """The season's readings (``path``, or its readings file) parsed and checked."""
        chosen = path or self.readings_path(files)
        if path is None and files.day in self.checks_cache:
            return self.checks_cache[files.day]
        try:
            content = read_raw(chosen, MAX_READINGS_BYTES).decode("utf-8-sig")
        except (ValueError, UnicodeDecodeError) as error:
            found = ReadingsCheck(chosen, files.day, None, (Problem(1, UNREADABLE.format(error=error)),))
        else:
            readings, problems = parse_readings(content, self.ticker, files.day)
            problems.extend(readings_problems(readings, self.rules_season(files)))
            found = ReadingsCheck(
                chosen, files.day, readings, tuple(sorted(problems, key=lambda item: item.line))
            )
        if path is None:
            self.checks_cache[files.day] = found
        return found

    def readings_status(self, files: SeasonFiles) -> tuple[str, int]:
        """``missing``, ``failing`` (with the number of problems) or ``valid``."""
        if not os.path.lexists(self.readings_path(files)):
            return "missing", 0
        found = self.check(files)
        return ("valid", 0) if found.valid else ("failing", len(found.problems))

    def report_directory(self, files: SeasonFiles) -> Path:
        return self.layout.reports(self.ticker) / season_folder(files.day)

    def renderable(self, files: SeasonFiles) -> str | None:
        """Why the season's report cannot be rendered now, or None."""
        missing = files.missing
        if missing is not None:
            return missing
        if files.call.status == "missing":
            return files.call.reason
        stale = [document.doc_id for document in files.documents if self.texts.status(document) != "present"]
        if stale:
            return f"{_plural(len(stale), 'text file')} missing or out of date; run derive"
        if self.measures_status(files) != "fresh":
            return "the season's measures.md is missing or out of date; run derive"
        status, problems = self.readings_status(files)
        if status != "valid":
            return f"the season's readings are {status}" + (
                f" ({_plural(problems, 'problem')})" if problems else ""
            )
        return None

    def render(self, files: SeasonFiles, moment: datetime) -> str:
        """The season's report rendered at ``moment``, or ``ValueError`` saying why it cannot be."""
        _refuse_invalid(self.raw)
        why = self.renderable(files)
        if why is not None:
            raise ValueError(f"{self.ticker} {files.day}: {why}")
        readings = self.check(files).readings
        if (
            readings is None
            or self.raw.listing is None
            or self.raw.cik is None
            or self.raw.entity_name is None
        ):
            raise ValueError(f"{self.ticker} {files.day}: the readings cannot be read")
        return render_report(
            self.ticker,
            self.raw.cik,
            self.raw.entity_name,
            self.raw.listing,
            files,
            self.measures(files),
            readings,
            moment,
        )

    def report_status(self, files: SeasonFiles) -> tuple[Fresh, Path | None]:
        """Whether the season's newest report is the report rendered now."""
        path = newest_report(self.report_directory(files), self.now)
        if path is None:
            return "missing", None
        if self.renderable(files) is not None or self.raw.invalid_files or self.raw.former_layout:
            return "stale", path
        try:
            held = read_raw(path, MAX_READINGS_BYTES).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            return "stale", path
        return ("fresh" if same_report(held, self.render(files, self.now)) else "stale"), path

    def action(self, window: Window, refresh: bool = False) -> tuple[Action, str | None]:
        """What comes next for the window's seasons, and why (module docstring)."""
        raw = self.raw
        if raw.former_layout:
            more = len(raw.former_layout) - 1
            also = f"; {_plural(more, 'other folder')} too (see former_layout)" if more else ""
            return "fetch", f"{raw.former_layout[0]} is {FORMER}{also}"
        if raw.reason is not None:
            return "fetch", raw.reason
        span = raw.span(window)
        missing = next((reason for files in span if (reason := files.missing) is not None), None)
        if missing is not None:
            return "fetch", missing
        if raw.invalid_files:
            return "fetch", _invalid_reason(raw.invalid_files, RENAME_AND_FETCH)
        for files in raw.within(window):
            status, reason = raw.facts_status(files)
            if status == "missing":
                return "fetch", reason
        call = next((files.call.reason for files in span if files.call.status == "missing"), None)
        if call is not None:
            return "fetch", call
        due = _calls_due(raw, window, self.now, refresh)
        if due is not None:
            return "fetch", due
        if refresh and span:
            return "fetch", REFRESH_REASON
        stale = [
            document.doc_id
            for files in span
            for document in files.documents
            if self.texts.status(document) != "present"
        ]
        if stale:
            return "derive", f"{_plural(len(stale), 'text file')} missing or out of date: {', '.join(stale)}"
        measures = [str(files.day) for files in raw.within(window) if self.measures_status(files) != "fresh"]
        if measures:
            return "derive", f"measures.md missing or out of date for: {', '.join(measures)}"
        research = []
        for files in raw.within(window):
            readings, problems = self.readings_status(files)
            if readings != "valid":
                count = f", {_plural(problems, 'problem')}" if problems else ""
                research.append(f"{files.day} ({readings}{count})")
        if research:
            return "research", "readings missing or failing check: " + ", ".join(research)
        reports = [str(files.day) for files in raw.within(window) if self.report_status(files)[0] != "fresh"]
        if reports:
            return "render", f"no current report for: {', '.join(reports)}"
        return "reuse", None


def _invalid_reason(files: Sequence[tuple[Path, str]], then: str) -> str:
    path, reason = files[0]
    return f"{_plural(len(files), 'raw file')} failed validation (first: {path}: {reason}); {then}"


def resolve(layout: DataLayout, ticker: str, now: datetime) -> _State:
    """Read the ticker's raw tree as of ``now``."""
    symbol = ticker_symbol(ticker)
    moment = to_eastern(now, "now")
    raw = season_documents(layout, symbol, moment)
    return _State(layout, symbol, moment, raw, _Texts(layout, symbol))


def _stray(state: _State) -> tuple[list[str], list[str]]:
    """The files of ``formatted/{T}/`` and ``reports/{T}/`` outside every season folder: the former
    layout's derived texts (rebuildable: delete them) and reports (left as they are)."""
    stray: list[list[str]] = []
    for root in (state.layout.formatted(state.ticker), state.layout.reports(state.ticker)):
        found = []
        if root.is_dir():
            for path in sorted(root.iterdir()):
                if path.name.startswith(".") or path.is_dir():
                    continue
                found.append(str(path))
        stray.append(found)
    return stray[0], stray[1]


# --------------------------------------------------------------------------- plan


def _season_json(state: _State, files: SeasonFiles, window: Window) -> dict[str, Any]:
    own = files.season.filing
    folder = filing_folder(own.form, own.period, own.accession)
    texts = [document.doc_id for document in files.documents if state.texts.status(document) != "present"]
    in_window = window.admits(files.day)
    readings_status, problems = state.readings_status(files) if in_window else ("not needed", 0)
    facts, facts_reason = state.raw.facts_status(files)
    entry: dict[str, Any] = {
        "season": files.day.isoformat(),
        "in_window": in_window,
        "filing": {
            **_filing_identity(own),
            "doc_id": doc_id(folder, own.primary_document),
            "raw": files.filing is not None,
        },
        "filings": [
            {
                **_dated_json(item.item),
                "raw": all(needed.present for needed in item.needed)
                and (item.item.form != "4" or item.form4 is not None),
            }
            for item in files.filings
        ],
        "listed_only": [_dated_json(item) for item in files.season.filings if not item.fetched],
        "documents": "complete" if files.missing is None else files.missing,
        "call": {
            "status": files.call.status,
            "due": files.call.due.isoformat(),
            "as_of": None if files.call.as_of is None else files.call.as_of.isoformat(),
            "calls": [event.describe() for event in files.call.events],
            "documents": [document.doc_id for document in files.call.documents],
            "reason": files.call.reason,
        },
        "texts": {"documents": len(files.documents), "stale": texts},
        "companyfacts": {"status": facts, "reason": facts_reason},
    }
    if in_window:
        report, path = state.report_status(files)
        entry["measures"] = {"path": str(state.measures_path(files)), "status": state.measures_status(files)}
        entry["readings"] = {
            "path": str(state.readings_path(files)),
            "status": readings_status,
            "problems": problems,
        }
        entry["report"] = {"path": None if path is None else str(path), "status": report}
    return entry


def describe(state: _State, window: Window, refresh: bool = False) -> dict[str, Any]:
    """``plan``'s JSON of one ticker."""
    raw = state.raw
    action, reason = state.action(window, refresh)
    listing = raw.listing
    stray_files, stray_reports = _stray(state)
    capture = raw.capture
    return {
        "ticker": state.ticker,
        "action": action,
        "reason": reason,
        "cik": raw.cik,
        "entity_name": raw.entity_name,
        "submissions": None if raw.submissions is None else str(raw.submissions),
        "companyfacts": None if raw.companyfacts is None else str(raw.companyfacts),
        "window": _window_json(window),
        "truncated": None if listing is None else listing.truncated(window),
        "former_layout": [str(path) for path in raw.former_layout],
        "invalid_files": _invalid(raw.invalid_files),
        "unlisted_files": [str(path) for path in raw.unlisted],
        "pending_filings": []
        if listing is None
        else [_dated_json(item) for item in listing.pending_in(window)],
        "skipped_filings": []
        if listing is None
        else [
            {
                "form": item.form,
                "accession": item.accession,
                "filed": item.filed.isoformat(),
                "reason": item.reason,
            }
            for item in listing.skipped
        ],
        "calls": {
            "events": None
            if capture is None
            else {
                "path": str(capture.pages[0]),
                "pages": len(capture.pages),
                "fetched_at": et_isoformat(capture.fetched_at),
            },
            "due": _calls_due(raw, window, state.now, refresh),
            "pending_calls": [event.describe() for event in raw.pending_in(window)],
        },
        "seasons": [_season_json(state, files, window) for files in raw.span(window)],
        "stray_files": stray_files,
        "stray_reports": stray_reports,
    }


def plan(
    layout: DataLayout,
    tickers: Sequence[str],
    now: datetime,
    window: Window,
    *,
    refresh: bool = False,
    watchlist: Path = WATCHLIST,
) -> dict[str, Any]:
    """Read-only state of the window's seasons and the next action of every requested ticker; never
    fails for a ticker without raw files. ``refresh`` plans ``fetch`` with ``refresh``.

    Without tickers, the ``stock`` section of the ``watchlist`` file is planned; explicit tickers
    never read the file.
    """
    tickers = tickers or stock_tickers(watchlist)
    symbols = list(dict.fromkeys(ticker_symbol(ticker) for ticker in tickers))
    now = to_eastern(now, "now")
    return {
        "generated_at": et_isoformat(now),
        "window": _window_json(window),
        "refresh": refresh,
        "tickers": [describe(resolve(layout, symbol, now), window, refresh) for symbol in symbols],
    }


# --------------------------------------------------------------------------- derive


def _write_text(path: Path, derived: str, existing: str | None) -> TextWrite:
    """Write ``derived`` at ``path`` unless the file there holds it already (a file that cannot be
    read is replaced)."""
    if existing == derived:
        return "exists"
    present = os.path.lexists(path)
    write_file(path, derived, overwrite=present)
    return "rewritten" if present else "published"


def derive(layout: DataLayout, ticker: str, now: datetime) -> dict[str, Any]:
    """Write the derived text of every document of every listed season in ``raw/`` and the
    ``measures.md`` of every listed season whose 10-K or 10-Q is in ``raw/``, each only when it
    is missing, cannot be read or differs from its derivation."""
    state = resolve(layout, ticker, now)
    _refuse_invalid(state.raw)
    texts = state.texts
    written: list[dict[str, Any]] = []
    measures: list[dict[str, Any]] = []
    for files in state.raw.seasons:
        for document in files.documents:
            path = texts.path(document)
            status = _write_text(path, texts.derived(document), texts.written(document))
            written.append(
                {
                    "doc_id": document.doc_id,
                    "season": files.day.isoformat(),
                    "kind": document.kind,
                    "path": str(path),
                    "status": status,
                }
            )
        if files.filing is not None:
            path = state.measures_path(files)
            try:
                existing = read_raw(path, TEXT_LIMIT).decode("utf-8")
            except (ValueError, UnicodeDecodeError):
                existing = None
            status = _write_text(path, state.measures(files).text, existing)
            measures.append({"season": files.day.isoformat(), "path": str(path), "status": status})
    stray_files, stray_reports = _stray(state)
    return {
        "ticker": state.ticker,
        "documents": written,
        "measures": measures,
        "stray_files": stray_files,
        "stray_reports": stray_reports,
    }


# --------------------------------------------------------------------------- check


def _check_json(found: ReadingsCheck) -> dict[str, Any]:
    return {
        "path": str(found.path),
        "season": found.season.isoformat(),
        "valid": found.valid,
        "problems": [{"line": problem.line, "message": problem.message} for problem in found.problems],
    }


def check(layout: DataLayout, ticker: str, now: datetime, paths: Sequence[Path] = ()) -> dict[str, Any]:
    """Check the readings at ``paths`` (each a season's draft: its season is its folder's name) or
    every season's readings file; write nothing."""
    state = resolve(layout, ticker, now)
    _refuse_invalid(state.raw)
    checks: list[ReadingsCheck] = []
    if paths:
        for path in paths:
            try:
                day = date.fromisoformat(path.parent.name)
            except ValueError:
                raise ValueError(
                    f"{path}: a readings draft lies in its season's folder, named YYYY-MM-DD"
                ) from None
            files = state.raw.season(day)
            if files is None:
                raise ValueError(f"{path}: no season of the newest submissions ends on {day}")
            checks.append(state.check(files, path))
    else:
        checks = [
            state.check(files) for files in state.raw.seasons if os.path.lexists(state.readings_path(files))
        ]
    return {"ticker": state.ticker, "readings": [_check_json(found) for found in checks]}


# --------------------------------------------------------------------------- render and show


def render(layout: DataLayout, ticker: str, now: datetime) -> dict[str, Any]:
    """Write a report of every listed season with readings whose report rendered now differs from its
    newest one (or which has none); refuse while a raw file is invalid, or when no season has a
    report to write and none a current one (the reason of the first season that cannot be
    rendered)."""
    state = resolve(layout, ticker, now)
    _refuse_invalid(state.raw)
    moment = state.now.replace(microsecond=0)
    candidates = [files for files in state.raw.seasons if os.path.lexists(state.readings_path(files))]
    if not candidates:
        raise ValueError(f"{state.ticker}: no season has readings; run plan")
    written, current, skipped = [], [], []
    for files in candidates:
        why = state.renderable(files)
        if why is not None:
            skipped.append({"season": files.day.isoformat(), "reason": why})
        elif state.report_status(files)[0] == "fresh":
            current.append(files.day.isoformat())
        else:
            path = state.report_directory(files) / report_name(moment)
            write_file(path, state.render(files, moment))
            written.append({"season": files.day.isoformat(), "path": str(path)})
    if not written and not current:
        raise ValueError(
            f"{state.ticker}: no report to write: {skipped[0]['season']}: {skipped[0]['reason']}"
        )
    return {"ticker": state.ticker, "reports": written, "current": current, "skipped": skipped}


def show(layout: DataLayout, tickers: Sequence[str], now: datetime, *, watchlist: Path = WATCHLIST) -> str:
    """Per ticker, the newest season report rendered now (or why there is none), then the ranking of
    the tickers' newest seasons by score."""
    tickers = tickers or stock_tickers(watchlist)
    symbols = list(dict.fromkeys(ticker_symbol(ticker) for ticker in tickers))
    moment = to_eastern(now, "now")
    window = default_window(moment.date())
    parts: list[str] = []
    rows = []
    for symbol in symbols:
        state = resolve(layout, symbol, moment)
        action, reason = state.action(window)
        header = f"{symbol}: action {action}" + ("." if reason is None else f": {printable(reason)}.")
        newest = None
        for files in reversed(state.raw.seasons):
            if os.path.lexists(state.readings_path(files)) and state.renderable(files) is None:
                newest = files
                break
        if newest is None or state.raw.invalid_files or state.raw.former_layout:
            parts.append(f"{header}\n\nNo season report can be rendered now.\n")
            continue
        text = state.render(newest, moment)
        status, path = state.report_status(newest)
        shown = "none" if path is None else str(path)
        parts.append(f"{header} Newest report: {printable(shown)} ({status}).\n\n{text}")
        readings = state.check(newest).readings
        if readings is not None:
            rows.append((symbol, newest.day.isoformat(), entries(state.measures(newest), readings), shown))
    ranked = "\n".join(ranking(rows)) + "\n"
    return "\n".join(parts) + "\n## Ranking\n\n" + ranked
