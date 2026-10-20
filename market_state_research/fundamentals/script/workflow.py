"""Fetch, plan, text, check, render and show: the fundamentals pipeline over ``raw/``,
``formatted/`` and ``reports/``.

``fetch`` is the domain's one network step, under two clients ``__main__`` builds from the
user's settings: EDGAR (``client.EdgarClient``) and EarningsCalls.dev
(``earningscalls.EarningsCallsClient``). For each ticker (by default each ``stock``
ticker of the watchlist ``__main__`` passes) it looks the CIK up in EDGAR's
``company_tickers.json`` (requested once per run), reads the company's submissions JSON
and writes it to ``raw/{T}/edgar/submissions_{token}.json`` unless its bytes equal the
newest such file's, and lists the fiscal periods (``filings.select_periods``). For each
period the ``Window`` admits, oldest first, it writes the period's 10-K or 10-Q, then for
each release the 8-K's filing index page and every ``EX-99`` exhibit the page lists, in
Seq order, each at its path under ``raw/{T}/edgar/`` (``documents``), bytes as served. A
file already there is never rewritten, nor requested again without ``refresh`` (below). A
failed request, or an index page that ``filings.parse_filing_index`` cannot read, aborts
the run with one line; nothing of that document is written, and the files written before
it stay. Releases Rule B leaves pending are listed when the window ends on or after the
newest listed period end, and none of their documents is requested; a window that starts
before the oldest filing ``filings.recent`` lists is reported ``truncated``.

Then, for a ticker whose periods are listed, the calls: when ``documents.RawState.events_due``
says so (no valid calls list in ``raw/``, or a window period's call not listed and the
list due again), it requests every page of the ticker's calls list, reads them strictly
(``earningscalls.check_capture``) and writes them as ``raw/{T}/calls/events_{token}_{PAGE}.json``;
then it writes the transcript of every call Rule B places in a window period, and of every
pending call when the window ends on or after the newest listed period end, as
``raw/{T}/calls/transcript_{ID}.json``, each read against its listed call first and, without
``refresh``, never requested again once a copy is there. A list whose symbol names several
issuers makes the ticker's calls ``unsupported`` (nothing written); the provider's request
limit (HTTP 429) stops every later request to it in the run, which goes on with EDGAR alone
(``stopped``); any other failed request or a body that does not read aborts the run with
one line, keeping what was written before it.

With ``refresh`` (``--refresh``, run only when the user asks) ``fetch`` reuses nothing it
could request: every window period's 10-K or 10-Q, index pages and exhibits are requested
again and compared with their files in ``raw/``, ``verified`` when the bytes are equal and
``changed`` when they differ or the file cannot be read, and never rewritten, so a
release's exhibits are those its page in ``raw/`` lists; the calls list is asked for
whenever the window holds a listed period (``REFRESH_REASON``); and every transcript is
requested again, ``verified`` when its bytes equal the newest copy's, else written beside
it as ``raw/{T}/calls/transcript_{ID}_{token}.json`` (``refreshed``), the copy later reads
take.

The other commands work offline over ``documents.period_documents``, which validates every
raw file it reads. ``text`` writes each document's derived text to
``formatted/{T}/{DOC_ID}.md``: a missing file, one that cannot be read, or one that
differs from its derivation. ``check`` parses and checks the agent's per-document reports
(``research``), every one but those of a period older than every listed period.
``render`` writes the time series ``reports/{T}/{T}_{AS_OF}_{token}.md`` (``report``),
never over a file. ``plan`` says per ticker what comes next for the window's periods, in
this order: ``fetch`` while no period is listed, a window period's EDGAR document is not
in ``raw/``, a raw file is invalid, a window period's call is ``missing`` (no valid calls
list, or a listed call's transcript not in ``raw/``) or the calls list is due again (with
``refresh``, whenever the window holds a listed period);
``text`` while a window document's text file is missing or differs from its derivation;
``research`` while a window document has no report that passes ``check`` or any report
fails it; ``render`` while the newest series file is not the series rendered now; else
``reuse``. ``show`` prints the action ``plan`` gives over the default window, status lines
and the series rendered in memory.

Invalid raw files, and a newest submissions file that lists no period, refuse ``text``,
``check`` and ``render``: they are listed by ``plan``, and the agent renames each invalid
file with ``.rejected``. Messages never repeat captured or private input, and the
``User-Agent`` and the EarningsCalls.dev key reach this module only inside their clients.
Every time is New York time.
"""

import os
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from functools import cached_property
from pathlib import Path
from typing import Any, Literal

from market_state_research.common.layout import DataLayout, listed, newest, stamped, write_file
from market_state_research.common.text import printable, ticker_symbol
from market_state_research.common.times import et_isoformat, to_eastern
from market_state_research.common.watchlist import WATCHLIST_PATH, stock_tickers

from .client import (
    DOCUMENT_LIMIT,
    INDEX_LIMIT,
    JSON_LIMIT,
    EdgarClient,
    archive_url,
    decode_document,
    index_url,
)
from .documents import (
    CALLS,
    EDGAR,
    SUBMISSIONS_PREFIX,
    SUBMISSIONS_SUFFIX,
    Document,
    PeriodFiles,
    RawState,
    call_doc_id,
    derive_call,
    derive_text,
    doc_id,
    edgar_folder,
    events_name,
    layout_mode,
    period_documents,
    read_raw,
    transcript_name,
)
from .earningscalls import (
    BODY_LIMIT,
    Ambiguous,
    CallEvent,
    EarningsCallsClient,
    Fetched,
    LimitReached,
    check_capture,
    check_issuer,
    parse_events_page,
    parse_transcript,
)
from .filings import (
    TICKERS_FILE,
    ExhibitRow,
    Filing,
    Release,
    Window,
    default_window,
    lookup_cik,
    parse_filing_index,
    parse_submissions,
    select_periods,
)
from .report import SeriesPeriod, newest_series, render_series, same_series, series_files, series_name
from .research import Problem, Report, Turn, parse_report, quote_problems

MAX_REPORT_BYTES = 4 * 1024 * 1024
TEXT_LIMIT = 64 * 1024 * 1024  # a derived text file: at most what a 50 MiB document derives
NOT_LISTED = "not in SEC company_tickers.json"
INVALID_RAW = (
    "{ticker}: {count} in raw/ failed validation; first: {path}: {reason}; "
    "run plan for the list and rename each with .rejected"
)
FAILING_REPORTS = "{ticker}: {count} failed check; first: {path}: line {line}: {message}; run check"
NO_DOCUMENT = (
    "the report names no document of a listed period in raw/ (its file name must be the DOC_ID of a "
    "10-K, 10-Q, EX-99 exhibit or call; an index page or a calls list has none)"
)
TEXT_MISSING = "the document's text file {path} is missing; run text"
TEXT_DIFFERS = "the text file {path} differs from the document's derived text; run text"
UNREADABLE_REPORT = "the report cannot be read: {error}"
# What to do about invalid raw files, after "N raw files failed validation (first: ...); ".
RENAME_AND_FETCH = "rename each with .rejected, then run fetch"
LIMIT_EARLIER = "not requested: EarningsCalls.dev's request limit was reached earlier in this run"
REFRESH_REASON = "--refresh: the window's documents, transcripts and calls list are requested again"

Action = Literal["fetch", "text", "research", "render", "reuse"]
FileStatus = Literal["new", "reused", "verified", "changed", "refreshed"]
TextStatus = Literal["present", "missing", "differs"]
TextWrite = Literal["published", "exists", "rewritten"]
SeriesStatus = Literal["fresh", "stale", "missing"]


# --------------------------------------------------------------------------- shared helpers


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


def _invalid(files: Iterable[tuple[Path, str]]) -> list[dict[str, str]]:
    return [{"path": str(path), "reason": reason} for path, reason in files]


def _window_json(window: Window | None) -> dict[str, str] | None:
    if window is None:
        return None
    return {"from": window.start.isoformat(), "to": window.end.isoformat()}


def _release_json(release: Release) -> dict[str, str]:
    return {
        "accession": release.accession,
        "filed": release.filed.isoformat(),
        "report_date": release.report_date.isoformat(),
        "items": release.items,
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
    ``REFRESH_REASON`` while the window holds a listed period; None when it does not ask."""
    due = raw.events_due(window, now)
    if due is None and refresh and raw.within(window):
        return REFRESH_REASON
    return due


def _refuse_invalid(raw: RawState) -> None:
    """Refuse a command while no period is listed or any raw file of the ticker fails validation."""
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
        "periods": [],
        "pending_releases": [],
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
    """One ticker's fetch: where its EDGAR files go, its CIK, the client and whether every document
    is requested again (``refresh``)."""

    edgar: Path
    cik: str
    client: EdgarClient
    refresh: bool

    def _document(self, path: Path, url: str) -> FileStatus:
        """Write the document at ``url`` to ``path`` unless a file is there already; with ``refresh``,
        request it anyway and compare it with that file (``verified`` or ``changed``)."""
        if not os.path.lexists(path):
            write_file(path, self.client.document(url).body)
            return "new"
        if not self.refresh:
            return "reused"
        return _compare(path, self.client.document(url).body, DOCUMENT_LIMIT)

    def filing(self, filing: Filing) -> dict[str, Any]:
        folder = edgar_folder(filing.form, filing.period, filing.accession)
        path = self.edgar / folder / filing.primary_document
        status = self._document(path, archive_url(self.cik, filing.accession, filing.primary_document))
        return {
            **_filing_identity(filing),
            "doc_id": doc_id(folder, filing.primary_document),
            "path": str(path),
            "status": status,
        }

    def exhibit(self, folder: str, release: Release, row: ExhibitRow) -> dict[str, Any]:
        path = self.edgar / folder / row.document
        status = self._document(path, archive_url(self.cik, release.accession, row.document))
        return {
            "exhibit": row.exhibit,
            "sequence": row.sequence,
            "document": row.document,
            "doc_id": doc_id(folder, row.document),
            "path": str(path),
            "status": status,
        }

    def release(self, release: Release) -> dict[str, Any]:
        """The release's filing index page, unless it is in ``raw/`` already, then its exhibits.

        The page is parsed before it is written, so a page that cannot be read aborts the
        run and nothing of the release is written; one already in ``raw/`` that no longer
        parses aborts it too, naming the file. With ``refresh``, a page in ``raw/`` is
        requested again and compared with it (``verified`` or ``changed``); the exhibits are
        those the page in ``raw/`` lists.
        """
        folder = edgar_folder("8-K", release.report_date, release.accession)
        path = self.edgar / folder / f"{release.accession}-index.htm"
        url = index_url(self.cik, release.accession)
        status: FileStatus = "reused" if os.path.lexists(path) else "new"
        try:
            data = read_raw(path, INDEX_LIMIT) if status == "reused" else self.client.index_page(url).body
            rows = parse_filing_index(decode_document(data)[0], self.cik, release.accession).exhibits
        except ValueError as error:
            if status == "new":
                raise
            raise ValueError(f"{path}: {error}; rename it with .rejected and run fetch again") from None
        if status == "new":
            write_file(path, data)
        elif self.refresh:
            status = "verified" if self.client.index_page(url).body == data else "changed"
        return {
            **_release_json(release),
            "index": {"path": str(path), "status": status},
            "exhibits": [self.exhibit(folder, release, row) for row in rows],
        }


def _submissions(
    layout: DataLayout, ticker: str, cik: str, client: EdgarClient
) -> tuple[Path, FileStatus, str, datetime]:
    """Read the submissions JSON; write it unless its bytes equal the newest file's. The time it
    arrived comes last."""
    fetched = client.submissions(cik)
    try:
        body = fetched.body.decode("utf-8")
    except UnicodeDecodeError:
        raise ValueError("submissions: the body is not UTF-8") from None
    parse_submissions(body, cik)  # an unreadable body aborts the run before anything is written
    edgar = layout.raw(ticker) / EDGAR
    held = newest(edgar, SUBMISSIONS_PREFIX, SUBMISSIONS_SUFFIX, fetched.fetched_at)
    if held is not None:
        try:
            if read_raw(held, JSON_LIMIT) == fetched.body:
                return held, "reused", body, fetched.fetched_at
        except ValueError:  # an invalid newest file is never the same body
            pass
    path = edgar / stamped(SUBMISSIONS_PREFIX.rstrip("_"), fetched.fetched_at, SUBMISSIONS_SUFFIX)
    write_file(path, fetched.body)
    return path, "new", body, fetched.fetched_at


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
    path, status, body, fetched_at = _submissions(layout, ticker, cik, client)
    submissions = parse_submissions(body, cik)
    held = {"path": str(path), "status": status}
    try:
        periods = select_periods(submissions)
    except ValueError as error:  # NoPeriodicFilings, two filings for one period, an undated release
        return _unsupported(ticker, str(error), window, cik, submissions.entity_name, held), fetched_at
    fetcher = _Fetcher(layout.raw(ticker) / EDGAR, cik, client, refresh)
    return {
        "ticker": ticker,
        "status": "fetched",
        "reason": None,
        "cik": cik,
        "entity_name": submissions.entity_name,
        "submissions": held,
        "window": _window_json(window),
        "truncated": periods.truncated(window),
        "periods": [
            {
                "period": period.period.isoformat(),
                "filing": fetcher.filing(period.filing),
                "releases": [fetcher.release(release) for release in period.releases],
            }
            for period in periods.within(window)
        ],
        "pending_releases": [_release_json(release) for release in periods.pending_in(window)],
        "calls": None,
    }, fetched_at


def _request_events(client: EarningsCallsClient, ticker: str) -> list[Fetched]:
    """Every page of the ticker's calls list, read strictly before any is written.

    Page 1 tells how many pages there are; a list whose symbol names several issuers
    raises ``earningscalls.Ambiguous`` from page 1, before another page is requested. A
    body that does not read raises ``ValueError`` naming its URL.
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
    period: date | None,
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
        "period": None if period is None else period.isoformat(),
        "doc_id": None if period is None else call_doc_id(period, event.id),
        "path": str(path),
        "status": status,
    }


def _calls_entry(
    status: str, reason: str | None, events: dict[str, Any] | None, transcripts: list[dict[str, Any]]
) -> dict[str, Any]:
    return {"status": status, "reason": reason, "events": events, "transcripts": transcripts}


def _fetch_calls(
    layout: DataLayout,
    ticker: str,
    client: EarningsCallsClient,
    window: Window,
    now: datetime,
    refresh: bool,
) -> dict[str, Any]:
    """The ticker's calls list when it is due, then the transcripts of its window periods' calls
    and of its pending calls; see the module docstring.

    The provider's request limit ends the step with the status ``stopped`` and its line,
    keeping what was written before it.
    """
    raw = period_documents(layout, ticker, now)
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
                write_file(layout.raw(ticker) / CALLS / events_name(fetched_at, number), item.body)
            raw = period_documents(layout, ticker, max(to_eastern(now, "now"), fetched_at))
        if raw.capture is not None:
            events = {
                "status": "reused" if due is None else "new",
                "path": str(raw.capture.pages[0]),
                "pages": len(raw.capture.pages),
                "fetched_at": et_isoformat(raw.capture.fetched_at),
                "reason": due,
            }
        directory = layout.raw(ticker) / CALLS
        targets: list[tuple[date | None, CallEvent]] = [
            (files.day, event) for files in raw.within(window) for event in files.call.events
        ]
        targets.extend((None, event) for event in raw.pending_in(window))
        for period, event in targets:
            held = raw.transcript_files.get(event.id)
            transcripts.append(_transcript(directory, client, event, period, held, refresh))
    except LimitReached as error:
        return _calls_entry("stopped", str(error), events, transcripts)
    return _calls_entry("fetched", None, events, transcripts)


def fetch(
    layout: DataLayout,
    tickers: Sequence[str],
    client: EdgarClient,
    calls: EarningsCallsClient,
    window: Window,
    now: datetime,
    *,
    refresh: bool = False,
    watchlist: Path = WATCHLIST_PATH,
) -> dict[str, Any]:
    """Write every ticker's submissions and the EDGAR documents of each period in ``window`` that
    are not in ``raw/`` yet, then its calls list when due and its calls' transcripts; with
    ``refresh``, request every window document, the calls list and every transcript again
    (module docstring).

    Without tickers, the ``stock`` section of the ``watchlist`` file is fetched; explicit
    tickers never read the file. Every ticker is normalised before the first request. A
    ticker EDGAR does not list, or whose recent filings ``filings.select_periods`` refuses
    (no exact 10-K or 10-Q, say), is ``unsupported`` and the run continues; so are a
    ticker's calls when the provider's symbol names several issuers. Once the provider's
    request limit is reached (``stopped``), no later ticker's calls are requested. A failed
    request raises ``client.EdgarError`` or ``earningscalls.EarningsCallsError`` and an
    unreadable body or index page ``ValueError``, either aborting the run and keeping the
    files written before it.
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


# --------------------------------------------------------------------------- texts and reports


@dataclass
class _Texts:
    """Each document's derived text and text file, read once per command."""

    layout: DataLayout
    ticker: str
    derived_texts: dict[str, str] = field(default_factory=dict)
    call_turns: dict[str, tuple[Turn, ...]] = field(default_factory=dict)

    def path(self, document: Document) -> Path:
        return self.layout.formatted(self.ticker) / document.text_name

    def written(self, document: Document) -> str | None:
        """The text file's content; None when there is none, or none that reads as UTF-8 text
        within its limit (``text`` writes it again)."""
        try:
            return read_raw(self.path(document), TEXT_LIMIT).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            return None

    def derived(self, document: Document) -> str:
        """A filing's, exhibit's or call's derived text, from ``raw/`` (once per command)."""
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

    def turns(self, document: Document) -> tuple[Turn, ...] | None:
        """A call's turns in its derived text; None for any other document."""
        if document.kind != "call":
            return None
        self.derived(document)
        return self.call_turns[document.doc_id]

    def status(self, document: Document) -> TextStatus:
        """``present``, ``missing`` or ``differs``."""
        written = self.written(document)
        if written is None:
            return "differs" if os.path.lexists(self.path(document)) else "missing"
        return "present" if written == self.derived(document) else "differs"


@dataclass(frozen=True)
class ReportCheck:
    """One per-document report and every problem ``check`` finds in it (valid without any)."""

    path: Path
    doc_id: str
    report: Report | None
    problems: tuple[Problem, ...]

    @property
    def valid(self) -> bool:
        return not self.problems


def check_report(path: Path, documents: dict[str, Document], texts: _Texts) -> ReportCheck:
    """Parse the report at ``path`` and check it against the derived text of the document its
    name gives (``path``'s name without ``.md``); a call's quotes also against its turns."""
    name = path.name.removesuffix(".md")
    try:
        content = read_raw(path, MAX_REPORT_BYTES).decode("utf-8-sig")
    except (ValueError, UnicodeDecodeError) as error:
        return ReportCheck(path, name, None, (Problem(1, UNREADABLE_REPORT.format(error=error)),))
    report, problems = parse_report(content, name)
    document = documents.get(name)
    if document is None:
        problems.append(Problem(report.line, NO_DOCUMENT))
    else:
        derived = texts.derived(document)
        text_path = texts.path(document)
        status = texts.status(document)
        if status == "missing":
            problems.append(Problem(report.line, TEXT_MISSING.format(path=text_path)))
        elif status == "differs":
            problems.append(Problem(report.line, TEXT_DIFFERS.format(path=text_path)))
        problems.extend(
            quote_problems(
                report,
                derived,
                layout=layout_mode(document),
                call=document.kind == "call",
                turns=texts.turns(document),
            )
        )
    return ReportCheck(path, name, report, tuple(sorted(problems, key=lambda problem: problem.line)))


def report_paths(layout: DataLayout, ticker: str) -> list[Path]:
    """The ticker's per-document reports: every ``*.md`` in ``reports/{T}/`` but its series files."""
    directory = layout.reports(ticker)
    series = set(series_files(directory, ticker))
    return [path for path in listed(directory, ".md") if path not in series]


# --------------------------------------------------------------------------- state


@dataclass(frozen=True)
class _Series:
    status: SeriesStatus
    path: Path | None
    as_of: date | None
    text: str | None  # the series rendered now, when it can be
    reason: str | None  # why it cannot be rendered now


@dataclass(frozen=True)
class _State:
    """One ticker's raw files, derived texts, reports and series as of ``now``."""

    layout: DataLayout
    ticker: str
    now: datetime
    raw: RawState
    texts: _Texts
    checks: tuple[ReportCheck, ...]

    @cached_property
    def passing(self) -> dict[str, Report]:
        return {
            check.doc_id: check.report for check in self.checks if check.valid and check.report is not None
        }

    @cached_property
    def failing(self) -> tuple[ReportCheck, ...]:
        return tuple(check for check in self.checks if not check.valid)

    def series_period(self, files: PeriodFiles) -> SeriesPeriod:
        passing = self.passing
        reports = {
            document.doc_id: passing[document.doc_id]
            for document in files.documents
            if document.doc_id in passing
        }
        return SeriesPeriod(files, reports)

    def series_periods(self) -> list[SeriesPeriod]:
        """Every listed period whose 10-K or 10-Q is in ``raw/``."""
        return [self.series_period(files) for files in self.raw.periods if files.filing is not None]

    def render(self) -> tuple[date, str]:
        """The series rendered now, or ``ValueError`` saying why it cannot be."""
        _refuse_invalid(self.raw)
        if self.failing:
            first = self.failing[0]
            problem = first.problems[0]
            raise ValueError(
                FAILING_REPORTS.format(
                    ticker=self.ticker,
                    count=_plural(len(self.failing), "report"),
                    path=first.path,
                    line=problem.line,
                    message=problem.message,
                )
            )
        if self.raw.cik is None or self.raw.entity_name is None:  # never once a period is listed
            raise ValueError(f"{self.ticker}: no period is listed")
        try:
            return render_series(
                self.ticker, self.raw.cik, self.raw.entity_name, self.series_periods(), self.now
            )
        except ValueError as error:
            raise ValueError(f"{self.ticker}: {error}") from None

    @cached_property
    def series(self) -> _Series:
        """The newest series file and whether it is the series rendered now."""
        path = newest_series(self.layout.reports(self.ticker), self.ticker, self.now)
        try:
            as_of, text = self.render()
        except ValueError as error:
            return _Series("missing" if path is None else "stale", path, None, None, str(error))
        if path is None:
            return _Series("missing", None, as_of, text, None)
        try:
            held = read_raw(path, MAX_REPORT_BYTES).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            held = ""
        return _Series("fresh" if same_series(held, text) else "stale", path, as_of, text, None)

    def action(self, window: Window, refresh: bool = False) -> tuple[Action, str | None]:
        """What comes next for the window's periods, and why; with ``refresh``, ``fetch`` while the
        window holds a listed period."""
        raw = self.raw
        if raw.reason is not None:
            return "fetch", raw.reason
        periods = raw.within(window)
        missing = next((reason for files in periods if (reason := files.missing) is not None), None)
        if missing is not None:
            return "fetch", missing
        if raw.invalid_files:
            return "fetch", _invalid_reason(raw.invalid_files, RENAME_AND_FETCH)
        call = next((files.call.reason for files in periods if files.call.status == "missing"), None)
        if call is not None:
            return "fetch", call
        due = _calls_due(raw, window, self.now, refresh)
        if due is not None:
            return "fetch", due
        documents = [document for files in periods for document in files.documents]
        texts = [document.doc_id for document in documents if self.texts.status(document) != "present"]
        if texts:
            return "text", f"{_plural(len(texts), 'text file')} missing or out of date: {', '.join(texts)}"
        unreported = [document.doc_id for document in documents if document.doc_id not in self.passing]
        if unreported or self.failing:
            failing = [str(check.path) for check in self.failing]
            parts = []
            if unreported:
                parts.append(f"{_plural(len(unreported), 'document')} without a passing report")
            if failing:
                parts.append(f"{_plural(len(failing), 'report')} failing check: {', '.join(failing)}")
            return "research", "; ".join(parts)
        series = self.series
        if series.status != "fresh" and series.text is not None:
            reason = (
                "no series file"
                if series.path is None
                else f"{series.path.name} is not the series rendered now"
            )
            return "render", reason
        return "reuse", None


def _invalid_reason(files: Sequence[tuple[Path, str]], then: str) -> str:
    path, reason = files[0]
    return f"{_plural(len(files), 'raw file')} failed validation (first: {path}: {reason}); {then}"


def resolve(layout: DataLayout, ticker: str, now: datetime) -> _State:
    """Read the ticker's raw tree and check every per-document report against it, but those of a
    period older than every listed period; none while no period is listed."""
    symbol = ticker_symbol(ticker)
    now = to_eastern(now, "now")
    raw = period_documents(layout, symbol, now)
    texts = _Texts(layout, symbol)
    documents = raw.documents()
    paths = [] if raw.reason is not None else report_paths(layout, symbol)
    paths = [path for path in paths if not raw.before_listing(path.stem)]
    checks = tuple(check_report(path, documents, texts) for path in paths)
    return _State(layout, symbol, now, raw, texts, checks)


# --------------------------------------------------------------------------- plan


def _document_json(state: _State, document: Document) -> dict[str, Any]:
    check = next((item for item in state.checks if item.doc_id == document.doc_id), None)
    report_path = state.layout.reports(state.ticker) / f"{document.doc_id}.md"
    if check is None:
        report: dict[str, Any] = {"path": str(report_path), "status": "missing", "problems": 0}
    else:
        status = "valid" if check.valid else "failing"
        report = {"path": str(check.path), "status": status, "problems": len(check.problems)}
    return {
        "doc_id": document.doc_id,
        "kind": document.kind,
        "text": {"path": str(state.texts.path(document)), "status": state.texts.status(document)},
        "report": report,
    }


def _call_json(files: PeriodFiles) -> dict[str, Any]:
    call = files.call
    return {
        "status": call.status,
        "due": call.due.isoformat(),
        "as_of": None if call.as_of is None else call.as_of.isoformat(),
        "calls": [event.describe() for event in call.events],
        "documents": [document.doc_id for document in call.documents],
        "reason": call.reason,
    }


def _period_json(state: _State, files: PeriodFiles) -> dict[str, Any]:
    filing = files.period.filing
    folder = edgar_folder(filing.form, filing.period, filing.accession)
    return {
        "period": files.day.isoformat(),
        "status": state.series_period(files).status,
        "filing": {
            "form": filing.form,
            "accession": filing.accession,
            "filed": filing.filed.isoformat(),
            "doc_id": doc_id(folder, filing.primary_document),
            "raw": files.filing is not None,
        },
        "releases": [
            {
                "accession": release.release.accession,
                "filed": release.release.filed.isoformat(),
                "report_date": release.release.report_date.isoformat(),
                "index": {"path": str(release.index_path), "raw": release.index_valid},
                "exhibits": [
                    {
                        "exhibit": row.exhibit,
                        "sequence": row.sequence,
                        "document": row.document,
                        "doc_id": doc_id(release.folder, row.document),
                        "raw": document is not None,
                    }
                    for row, document in release.exhibits
                ],
            }
            for release in files.releases
        ],
        "call": _call_json(files),
        "documents": [_document_json(state, document) for document in files.documents],
    }


def _calls_json(state: _State, window: Window, refresh: bool) -> dict[str, Any]:
    raw = state.raw
    capture = raw.capture
    return {
        "events": None
        if capture is None
        else {
            "path": str(capture.pages[0]),
            "pages": len(capture.pages),
            "fetched_at": et_isoformat(capture.fetched_at),
        },
        "due": _calls_due(raw, window, state.now, refresh),
        "pending_calls": [event.describe() for event in raw.pending_in(window)],
        "unlisted_files": [str(path) for path in raw.unlisted],
    }


def describe(state: _State, window: Window, refresh: bool = False) -> dict[str, Any]:
    """``plan``'s JSON of one ticker."""
    raw = state.raw
    action, reason = state.action(window, refresh)
    series = state.series
    listing = raw.listing
    return {
        "ticker": state.ticker,
        "action": action,
        "reason": reason,
        "cik": raw.cik,
        "entity_name": raw.entity_name,
        "submissions": None if raw.submissions is None else str(raw.submissions),
        "window": _window_json(window),
        "truncated": None if listing is None else listing.truncated(window),
        "pending_releases": []
        if listing is None
        else [_release_json(item) for item in listing.pending_in(window)],
        "calls": _calls_json(state, window, refresh),
        "periods": [_period_json(state, files) for files in raw.within(window)],
        "invalid_files": _invalid(raw.invalid_files),
        "failing_reports": [
            {"path": str(check.path), "document": check.doc_id, "problems": len(check.problems)}
            for check in state.failing
        ],
        "series": {
            "status": series.status,
            "path": None if series.path is None else str(series.path),
            "as_of": None if series.as_of is None else series.as_of.isoformat(),
        },
    }


def plan(
    layout: DataLayout,
    tickers: Sequence[str],
    now: datetime,
    window: Window,
    *,
    refresh: bool = False,
    watchlist: Path = WATCHLIST_PATH,
) -> dict[str, Any]:
    """Read-only state of the periods in ``window`` and the next action of every requested ticker;
    never fails for a ticker without raw files. ``refresh`` plans ``fetch`` with ``refresh``.

    Without tickers, the ``stock`` section of the ``watchlist`` file is planned; explicit
    tickers never read the file.
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


# --------------------------------------------------------------------------- text


def _write_text(path: Path, derived: str, existing: str | None) -> TextWrite:
    """Write ``derived`` at ``path`` unless the file there holds it already (a file that cannot
    be read is replaced)."""
    if existing == derived:
        return "exists"
    present = os.path.lexists(path)
    write_file(path, derived, overwrite=present)
    return "rewritten" if present else "published"


def text(layout: DataLayout, ticker: str, now: datetime) -> dict[str, Any]:
    """Write the derived text of every document of every listed period in ``raw/``: a missing text
    file, one that cannot be read, or one that differs from its derivation."""
    symbol = ticker_symbol(ticker)
    raw = period_documents(layout, symbol, to_eastern(now, "now"))
    _refuse_invalid(raw)
    texts = _Texts(layout, symbol)
    written: list[dict[str, Any]] = []
    for files in raw.periods:
        for document in files.documents:
            path = texts.path(document)
            status = _write_text(path, texts.derived(document), texts.written(document))
            written.append(
                {
                    "doc_id": document.doc_id,
                    "period": files.day.isoformat(),
                    "kind": document.kind,
                    "path": str(path),
                    "status": status,
                }
            )
    return {"ticker": symbol, "documents": written}


# --------------------------------------------------------------------------- check


def _check_json(check: ReportCheck) -> dict[str, Any]:
    return {
        "path": str(check.path),
        "document": check.doc_id,
        "valid": check.valid,
        "problems": [{"line": problem.line, "message": problem.message} for problem in check.problems],
    }


def check(layout: DataLayout, ticker: str, now: datetime, paths: Sequence[Path] = ()) -> dict[str, Any]:
    """Check the reports at ``paths``, or every per-document report of the ticker; write nothing."""
    state = resolve(layout, ticker, now)
    _refuse_invalid(state.raw)
    if paths:
        documents = state.raw.documents()
        checks: Sequence[ReportCheck] = [check_report(path, documents, state.texts) for path in paths]
    else:
        checks = state.checks
    return {"ticker": state.ticker, "reports": [_check_json(item) for item in checks]}


# --------------------------------------------------------------------------- render and show


def _periods_json(state: _State) -> list[dict[str, Any]]:
    return [
        {"period": period.files.day.isoformat(), "status": period.status, "missing": list(period.missing)}
        for period in sorted(state.series_periods(), key=lambda period: period.files.day, reverse=True)
    ]


def render(layout: DataLayout, ticker: str, now: datetime) -> dict[str, Any]:
    """Write a new time series of every complete period; refuse while no period is listed, a raw
    file is invalid, a report fails check or no period is complete."""
    state = resolve(layout, ticker, now)
    as_of, series = state.render()
    path = layout.reports(state.ticker) / series_name(state.ticker, as_of, state.now)
    write_file(path, series)
    return {
        "ticker": state.ticker,
        "as_of": as_of.isoformat(),
        "path": str(path),
        "periods": _periods_json(state),
    }


def show(layout: DataLayout, ticker: str, now: datetime) -> str:
    """The action ``plan`` gives over the default window, status lines and the series rendered now."""
    eastern = to_eastern(now, "now")
    window = default_window(eastern.date())
    state = resolve(layout, ticker, eastern)
    action, reason = state.action(window)
    series = state.series
    periods = state.series_periods()
    by_status = {
        status: [period.files.day.isoformat() for period in periods if period.status == status]
        for status in ("complete", "incomplete", "not researched")
    }
    weighed = f"default window {window.start.isoformat()} to {window.end.isoformat()}"
    lines = [
        f"Action: {action} ({weighed})" + ("." if reason is None else f": {printable(reason)}."),
        f"Periods with documents in raw/: {len(periods)}: "
        + ", ".join(
            f"{len(days)} {status}" + (f" ({', '.join(days)})" if days else "")
            for status, days in by_status.items()
        )
        + ".",
        f"Reports: {len(state.checks) - len(state.failing)} pass check, {len(state.failing)} fail.",
        f"Series: {'none' if series.path is None else printable(str(series.path))} ({series.status}).",
        *(
            f"Invalid file: {printable(str(path))} ({printable(why)})"
            for path, why in state.raw.invalid_files
        ),
        *(
            f"Failing report: {printable(str(item.path))} ({len(item.problems)} problems)"
            for item in state.failing
        ),
    ]
    body = (
        series.text
        if series.text is not None
        else f"No series can be rendered: {printable(series.reason or '')}\n"
    )
    return "\n".join(lines) + "\n\n" + body
