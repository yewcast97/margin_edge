"""Fetch, plan, derive, check, render and show: the fundamentals pipeline over ``raw/``,
``formatted/`` and ``reports/``.

``fetch`` is the domain's one network step, under two clients ``__main__`` builds from the
user's settings: EDGAR (``client.EdgarClient``) and EarningsCalls.dev
(``earningscalls.EarningsCallsClient``). For each ticker (by default each ``stock`` ticker of
the watchlist ``__main__`` passes) it looks the CIK up in EDGAR's ``company_tickers.json``
(requested once per run), reads the company's submissions JSON and writes it to
``raw/{T}/submissions_{token}.json`` unless its bytes equal the newest such file's, and lists
the seasons (``filings.select_seasons``). For each season of the span (the seasons the
``Window`` admits and the ``aspects.BASELINE_SEASONS`` before them, the baselines of the
window's comparisons), oldest first, it writes the season's 10-K or 10-Q, then each 8-K Rule B
places in the season, in order: its filing index page (read before it is written), its primary
document and every ``EX-99`` exhibit the page lists. Each lands at its path under
``raw/{T}/{PERIOD}/`` (``documents``), bytes as served; a file already there is never
rewritten, nor requested again without ``refresh``. A failed request, or a body that does not
read, aborts the run with one line; nothing of that document is written, and the files written
before it stay. Filings Rule B leaves pending are listed when the window ends on or after the
newest listed season end, and none of their documents is requested; the rows Rule B cannot
place are listed as skipped; a window that starts before the oldest filing ``filings.recent``
lists is reported ``truncated``.

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
document, the calls list and every transcript again: an EDGAR document is compared with its file
(``verified`` or ``changed``, never rewritten), and a transcript whose bytes changed is written
beside the newest copy (``refreshed``).

The other commands work offline over ``documents.season_documents``, which validates every raw
file it reads. ``derive`` writes each document's derived text to
``formatted/{T}/{PERIOD}/{DOC_ID}.md`` and each season's sheet, ``season.md`` (``sheet``),
each only when it is missing or differs from its derivation. ``check`` parses and checks the
bot's readings of each comparison of each season (``readings``). ``render`` writes a
comparison's report ``reports/{T}/{PERIOD}/report_{KIND}_{token}.md`` (``report``), never over a
file. ``plan`` says per ticker what comes next, in this order: ``fetch`` while the former layout
is in ``raw/``, no season is listed, a span season's EDGAR document is not in ``raw/``, a raw
file is invalid, a span season's call is ``missing`` or the calls list is due (with
``refresh``, whenever the window holds a listed season); ``derive`` while a span document's
text or a window season's sheet differs from its derivation; ``research`` while the readings of
a window season's comparison are missing or fail ``check``; ``render`` while a window
comparison's newest report is not the report rendered now; else ``reuse``. ``show`` prints the
newest season's reports of each ticker.

Messages never repeat captured or private input, and the ``User-Agent`` and the
EarningsCalls.dev key reach this module only inside their clients. Every time is New York time.
"""

import os
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from functools import cached_property, partial
from pathlib import Path
from typing import Any, Literal

from market_state_research.common.layout import DataLayout, newest, stamped, write_file
from market_state_research.common.text import printable, ticker_symbol
from market_state_research.common.times import et_isoformat, to_eastern
from market_state_research.common.watchlist import domain_watchlist, stock_tickers

from .aspects import BASELINE_SEASONS, KINDS, Comparison, Kind, comparison, comparisons
from .client import (
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
from .readings import Comparison as RulesComparison
from .readings import Problem, Readings, Source, parse_readings, readings_name, readings_problems
from .report import newest_report, render_report, report_name, same_report
from .sheet import SHEET, baseline_documents, season_sheet

WATCHLIST = domain_watchlist(Path(__file__).resolve().parent.parent)  # plan's, fetch's and show's default
MAX_READINGS_BYTES = 4 * 1024 * 1024
TEXT_LIMIT = 64 * 1024 * 1024  # a derived text file: at most what a 50 MiB document derives
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

    def _document(self, path: Path, url: str) -> FileStatus:
        """Write the document at ``url`` to ``path`` unless a file is there already; with ``refresh``,
        request it anyway and compare it with that file."""
        if not os.path.lexists(path):
            write_file(path, self.client.document(url).body)
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

    def eight_k(self, season: Season, item: Dated) -> dict[str, Any]:
        """An 8-K's index page, then its primary document and the exhibits the page lists."""
        folder = filing_folder(item.form, item.dated, item.accession)
        directory = self.raw / season_folder(season.period) / folder
        index_path = directory / f"{item.accession}-index.htm"
        status, exhibits = self._index(index_path, item)
        files = [self._entry(index_path, folder, status, False)]
        for name in (item.document, *exhibits):
            path = directory / name
            url = archive_url(self.cik, item.accession, name)
            files.append(self._entry(path, folder, self._document(path, url), True))
        return {**_dated_json(item), "files": files}


def _stamped_body(layout: DataLayout, ticker: str, fetched: EdgarFetched) -> tuple[Path, FileStatus]:
    """Write the submissions as ``submissions_{token}.json`` unless their bytes equal the newest
    such file's."""
    directory = layout.raw(ticker)
    held = newest(directory, SUBMISSIONS_PREFIX, JSON_SUFFIX, fetched.fetched_at)
    if held is not None:
        try:
            if read_raw(held, JSON_LIMIT) == fetched.body:
                return held, "reused"
        except ValueError:  # an invalid newest file is never the same body
            pass
    path = directory / stamped(SUBMISSIONS_PREFIX.rstrip("_"), fetched.fetched_at, JSON_SUFFIX)
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
    path, status = _stamped_body(layout, ticker, fetched)
    return {"path": str(path), "status": status}, body, fetched.fetched_at


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
            "filings": [fetcher.eight_k(season, item) for item in season.fetched],
        }
        for season in span
    ]
    return {
        "ticker": ticker,
        "status": "fetched",
        "reason": None,
        "cik": cik,
        "entity_name": submissions.entity_name,
        "submissions": held,
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
    """Write every ticker's submissions and the EDGAR documents of each span season not in ``raw/``
    yet, then its calls list when due and its calls' transcripts; with ``refresh``, request all of
    them again (module docstring).

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
    """One comparison's readings and every problem ``check`` finds in them (valid without any); the
    kind is the one they were read as, None for a draft that could not be read."""

    path: Path
    season: date
    kind: Kind | None
    readings: Readings | None
    problems: tuple[Problem, ...]

    @property
    def valid(self) -> bool:
        return not self.problems


@dataclass
class _State:
    """One ticker's raw files, derived texts, sheets, readings and reports as of ``now``."""

    layout: DataLayout
    ticker: str
    now: datetime
    raw: RawState
    texts: _Texts
    sheets_cache: dict[date, str] = field(default_factory=dict)
    checks_cache: dict[tuple[date, Kind], ReadingsCheck] = field(default_factory=dict)

    def sheet(self, files: SeasonFiles) -> str:
        if files.day not in self.sheets_cache:
            self.sheets_cache[files.day] = season_sheet(self.raw, files)
        return self.sheets_cache[files.day]

    def sheet_path(self, files: SeasonFiles) -> Path:
        return self.layout.formatted(self.ticker) / season_folder(files.day) / SHEET

    def sheet_status(self, files: SeasonFiles) -> Fresh:
        path = self.sheet_path(files)
        if not os.path.lexists(path):
            return "missing"
        try:
            held = read_raw(path, TEXT_LIMIT).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            return "stale"
        return "fresh" if held == self.sheet(files) else "stale"

    def comparisons(self, files: SeasonFiles) -> tuple[Comparison, ...]:
        listing = self.raw.listing
        return () if listing is None else comparisons(listing, files.season)

    def baseline_files(self, files: SeasonFiles, kind: Kind) -> SeasonFiles | None:
        """The season files of the comparison's baseline season, None when there is none."""
        listing = self.raw.listing
        found = None if listing is None else comparison(listing, files.season, kind)
        if found is None or found.baseline is None:
            return None
        return self.raw.season(found.baseline.period)

    def readings_path(self, files: SeasonFiles, kind: Kind) -> Path:
        return self.layout.reports(self.ticker) / season_folder(files.day) / readings_name(kind)

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

    def rules(self, files: SeasonFiles, kind: Kind) -> RulesComparison:
        """What the rules need of the season's comparison of ``kind`` (a 10-Q season's ``year``
        has no baseline: the rules refuse it)."""
        listing = self.raw.listing
        found = None if listing is None else comparison(listing, files.season, kind)
        baseline = None if found is None else found.baseline
        return RulesComparison(
            kind=kind,
            period=files.day,
            form=files.season.filing.form,
            documents=frozenset(document.doc_id for document in files.documents),
            baseline=None if baseline is None else baseline.period,
            baseline_documents=() if found is None else baseline_documents(self.raw, found),
            sources=self.sources,
        )

    def _checked(self, files: SeasonFiles, path: Path, kind: Kind | None) -> ReadingsCheck:
        """The readings at ``path`` parsed and checked as ``kind``'s, or as their title's (a draft)."""
        try:
            content = read_raw(path, MAX_READINGS_BYTES).decode("utf-8-sig")
        except (ValueError, UnicodeDecodeError) as error:
            return ReadingsCheck(path, files.day, kind, None, (Problem(1, UNREADABLE.format(error=error)),))
        readings, problems = parse_readings(content, self.ticker, files.day, kind)
        problems.extend(readings_problems(readings, self.rules(files, readings.kind)))
        return ReadingsCheck(
            path, files.day, readings.kind, readings, tuple(sorted(problems, key=lambda item: item.line))
        )

    def check(self, files: SeasonFiles, kind: Kind) -> ReadingsCheck:
        """The season's readings file of ``kind``, parsed and checked."""
        key = (files.day, kind)
        if key not in self.checks_cache:
            self.checks_cache[key] = self._checked(files, self.readings_path(files, kind), kind)
        return self.checks_cache[key]

    def check_draft(self, files: SeasonFiles, path: Path) -> ReadingsCheck:
        """A draft of the season's readings, read as the kind its title names."""
        return self._checked(files, path, None)

    def readings_status(self, files: SeasonFiles, kind: Kind) -> tuple[str, int]:
        """``missing``, ``failing`` (with the number of problems) or ``valid``."""
        if not os.path.lexists(self.readings_path(files, kind)):
            return "missing", 0
        found = self.check(files, kind)
        return ("valid", 0) if found.valid else ("failing", len(found.problems))

    def unnamed(self, files: SeasonFiles, kind: Kind) -> list[str] | None:
        """The season's documents its readings of ``kind`` name on no line, None without readings."""
        if not os.path.lexists(self.readings_path(files, kind)):
            return None
        readings = self.check(files, kind).readings
        if readings is None:
            return None
        named = {
            doc_id
            for _, item in readings.items
            for doc_id in (
                *(item.season or ()),
                *(item.baseline or ()),
                *(quote.doc_id for quote in item.quotes),
            )
        }
        return [document.doc_id for document in files.documents if document.doc_id not in named]

    def report_directory(self, files: SeasonFiles) -> Path:
        return self.layout.reports(self.ticker) / season_folder(files.day)

    def renderable(self, files: SeasonFiles, kind: Kind) -> str | None:
        """Why the report of the season's comparison of ``kind`` cannot be rendered now, or None."""
        sides = [files] + [held for held in (self.baseline_files(files, kind),) if held is not None]
        for held in sides:
            missing = held.missing
            if missing is not None:
                return missing
            if held.call.status == "missing":
                return held.call.reason
        stale = [
            document.doc_id
            for held in sides
            for document in held.documents
            if self.texts.status(document) != "present"
        ]
        if stale:
            return f"{_plural(len(stale), 'text file')} missing or out of date; run derive"
        if self.sheet_status(files) != "fresh":
            return f"the season's {SHEET} is missing or out of date; run derive"
        status, problems = self.readings_status(files, kind)
        if status != "valid":
            return f"the season's {kind} readings are {status}" + (
                f" ({_plural(problems, 'problem')})" if problems else ""
            )
        return None

    def render(self, files: SeasonFiles, kind: Kind, moment: datetime) -> str:
        """The report of the season's comparison of ``kind`` rendered at ``moment``, or ``ValueError``
        saying why it cannot be."""
        _refuse_invalid(self.raw)
        why = self.renderable(files, kind)
        if why is not None:
            raise ValueError(f"{self.ticker} {files.day} {kind}: {why}")
        readings = self.check(files, kind).readings
        listing = self.raw.listing
        found = None if listing is None else comparison(listing, files.season, kind)
        if readings is None or found is None:
            raise ValueError(f"{self.ticker} {files.day} {kind}: the readings cannot be read")
        return render_report(self.raw, files, found, readings, moment)

    def report_status(self, files: SeasonFiles, kind: Kind) -> tuple[Fresh, Path | None]:
        """Whether the newest report of the season's comparison of ``kind`` is the report rendered
        now."""
        path = newest_report(self.report_directory(files), kind, self.now)
        if path is None:
            return "missing", None
        if self.renderable(files, kind) is not None or self.raw.invalid_files or self.raw.former_layout:
            return "stale", path
        try:
            held = read_raw(path, MAX_READINGS_BYTES).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            return "stale", path
        return ("fresh" if same_report(held, self.render(files, kind, self.now)) else "stale"), path

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
        sheets = [str(files.day) for files in raw.within(window) if self.sheet_status(files) != "fresh"]
        if sheets:
            return "derive", f"{SHEET} missing or out of date for: {', '.join(sheets)}"
        research = []
        for files in raw.within(window):
            for found in self.comparisons(files):
                readings, problems = self.readings_status(files, found.kind)
                if readings != "valid":
                    count = f", {_plural(problems, 'problem')}" if problems else ""
                    research.append(f"{files.day} {found.kind} ({readings}{count})")
        if research:
            return "research", "readings missing or failing check: " + ", ".join(research)
        reports = [
            f"{files.day} {found.kind}"
            for files in raw.within(window)
            for found in self.comparisons(files)
            if self.report_status(files, found.kind)[0] != "fresh"
        ]
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


def _comparison_json(state: _State, files: SeasonFiles, found: Comparison) -> dict[str, Any]:
    status, problems = state.readings_status(files, found.kind)
    report, path = state.report_status(files, found.kind)
    baseline = found.baseline
    return {
        "kind": found.kind,
        "baseline": None
        if baseline is None
        else {"season": baseline.period.isoformat(), "form": baseline.filing.form},
        "readings": {
            "path": str(state.readings_path(files, found.kind)),
            "status": status,
            "problems": problems,
            "unnamed_documents": state.unnamed(files, found.kind),
        },
        "report": {"path": None if path is None else str(path), "status": report},
    }


def _season_json(state: _State, files: SeasonFiles, window: Window) -> dict[str, Any]:
    own = files.season.filing
    folder = filing_folder(own.form, own.period, own.accession)
    texts = [document.doc_id for document in files.documents if state.texts.status(document) != "present"]
    in_window = window.admits(files.day)
    entry: dict[str, Any] = {
        "season": files.day.isoformat(),
        "in_window": in_window,
        "filing": {
            **_filing_identity(own),
            "doc_id": doc_id(folder, own.primary_document),
            "raw": files.filing is not None,
        },
        "filings": [
            {**_dated_json(item.item), "raw": all(needed.present for needed in item.needed)}
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
    }
    if in_window:
        entry["sheet"] = {"path": str(state.sheet_path(files)), "status": state.sheet_status(files)}
        entry["comparisons"] = [_comparison_json(state, files, found) for found in state.comparisons(files)]
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
    ``season.md`` of every listed season whose 10-K or 10-Q is in ``raw/``, each only when it is
    missing, cannot be read or differs from its derivation."""
    state = resolve(layout, ticker, now)
    _refuse_invalid(state.raw)
    texts = state.texts
    written: list[dict[str, Any]] = []
    sheets: list[dict[str, Any]] = []
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
            path = state.sheet_path(files)
            try:
                existing = read_raw(path, TEXT_LIMIT).decode("utf-8")
            except (ValueError, UnicodeDecodeError):
                existing = None
            status = _write_text(path, state.sheet(files), existing)
            sheets.append({"season": files.day.isoformat(), "path": str(path), "status": status})
    stray_files, stray_reports = _stray(state)
    return {
        "ticker": state.ticker,
        "documents": written,
        "sheets": sheets,
        "stray_files": stray_files,
        "stray_reports": stray_reports,
    }


# --------------------------------------------------------------------------- check


def _check_json(found: ReadingsCheck) -> dict[str, Any]:
    return {
        "path": str(found.path),
        "season": found.season.isoformat(),
        "kind": found.kind,
        "valid": found.valid,
        "problems": [{"line": problem.line, "message": problem.message} for problem in found.problems],
    }


def check(layout: DataLayout, ticker: str, now: datetime, paths: Sequence[Path] = ()) -> dict[str, Any]:
    """Check the readings at ``paths`` (each a season's draft: its season is its folder's name, its
    kind its title's) or every readings file of every season; write nothing."""
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
            checks.append(state.check_draft(files, path))
    else:
        checks = [
            state.check(files, kind)
            for files in state.raw.seasons
            for kind in KINDS
            if os.path.lexists(state.readings_path(files, kind))
        ]
    return {"ticker": state.ticker, "readings": [_check_json(found) for found in checks]}


# --------------------------------------------------------------------------- render and show


def render(layout: DataLayout, ticker: str, now: datetime) -> dict[str, Any]:
    """Write a report of every comparison of a listed season with readings whose report rendered now
    differs from its newest one (or which has none); refuse while a raw file is invalid, or when no
    comparison has a report to write and none a current one (the reason of the first that cannot
    be rendered)."""
    state = resolve(layout, ticker, now)
    _refuse_invalid(state.raw)
    moment = state.now.replace(microsecond=0)
    candidates = [
        (files, found.kind)
        for files in state.raw.seasons
        for found in state.comparisons(files)
        if os.path.lexists(state.readings_path(files, found.kind))
    ]
    if not candidates:
        raise ValueError(f"{state.ticker}: no season has readings; run plan")
    written, current, skipped = [], [], []
    for files, kind in candidates:
        named = {"season": files.day.isoformat(), "kind": kind}
        why = state.renderable(files, kind)
        if why is not None:
            skipped.append({**named, "reason": why})
        elif state.report_status(files, kind)[0] == "fresh":
            current.append(named)
        else:
            path = state.report_directory(files) / report_name(kind, moment)
            write_file(path, state.render(files, kind, moment))
            written.append({**named, "path": str(path)})
    if not written and not current:
        first = skipped[0]
        raise ValueError(
            f"{state.ticker}: no report to write: {first['season']} {first['kind']}: {first['reason']}"
        )
    return {"ticker": state.ticker, "reports": written, "current": current, "skipped": skipped}


def show(layout: DataLayout, tickers: Sequence[str], now: datetime, *, watchlist: Path = WATCHLIST) -> str:
    """Per ticker, the action ``plan`` gives and the reports of the newest season one of whose
    reports can be rendered now, each rendered now (or why there is none)."""
    tickers = tickers or stock_tickers(watchlist)
    symbols = list(dict.fromkeys(ticker_symbol(ticker) for ticker in tickers))
    moment = to_eastern(now, "now")
    window = default_window(moment.date())
    parts: list[str] = []
    for symbol in symbols:
        state = resolve(layout, symbol, moment)
        action, reason = state.action(window)
        header = f"{symbol}: action {action}" + ("." if reason is None else f": {printable(reason)}.")
        newest: tuple[SeasonFiles, list[Kind]] | None = None
        for files in reversed(state.raw.seasons):
            kinds = [
                found.kind
                for found in state.comparisons(files)
                if os.path.lexists(state.readings_path(files, found.kind))
                and state.renderable(files, found.kind) is None
            ]
            if kinds:
                newest = (files, kinds)
                break
        if newest is None or state.raw.invalid_files or state.raw.former_layout:
            parts.append(f"{header}\n\nNo season report can be rendered now.\n")
            continue
        files, kinds = newest
        named, texts = [], []
        for kind in kinds:
            texts.append(state.render(files, kind, moment))
            status, path = state.report_status(files, kind)
            named.append(
                f"Newest {kind} report: {printable('none' if path is None else str(path))} ({status})."
            )
        parts.append(f"{header} {' '.join(named)}\n\n" + "\n".join(texts))
    return "\n".join(parts)
