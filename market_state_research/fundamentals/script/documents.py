"""One ticker's ``raw/`` tree read into its fiscal periods and their documents, and their derived text.

The raw tree of a ticker ``T`` (``common.layout.DataLayout.raw``) holds, verbatim, what
``fetch`` wrote:

- ``edgar/submissions_{token}.json``: EDGAR's submissions JSON, named by the New York time
  ``fetch`` read it, written only when its body differs from the newest one's;
- ``edgar/{FORM}_{DATE}_{ACCESSION}/{document}``: a document EDGAR served, bytes as served.
  ``FORM`` is the submissions row's form (``10-K``, ``10-Q`` or ``8-K``) and ``DATE`` the
  document's own date: the period end of a 10-K or 10-Q, the report date of an 8-K, so a
  folder never moves when Rule B places a release again. An 8-K's folder holds its filing
  index page ``{ACCESSION}-index.htm`` and the ``EX-99`` exhibits the page lists;
- ``calls/events_{token}_{PAGE}.json``: one page of the ticker's earnings calls as
  EarningsCalls.dev listed them (``earningscalls``); the pages of one request share the
  New York time ``fetch`` read the first one and form one *capture*. Each request writes
  a capture, so the newest one's time is when the provider last showed its list;
- ``calls/transcript_{ID}.json``: the transcript of the call ``ID`` as EarningsCalls.dev
  served it, written once; ``fetch --refresh`` writes a copy whose bytes differ from the
  newest one's beside it, as ``calls/transcript_{ID}_{token}.json``, named by the New York
  time it arrived.

Nothing a later read needs lives only in a name: the newest submissions file lists the
periods and places each Item 2.02 8-K by Rule B (``filings.select_periods``) on every
read, so every EDGAR document's form, accession, dates and period, and the CIK its URLs
are built from, come from that file; an exhibit's type and Seq come from its index page,
parsed again on every read; the newest capture lists the calls, each placed in a period
by Rule B on its New York date (``filings.Periods.place``), and a transcript's turns
come from its file.

Every read validates what it reads: the newest submissions file through
``filings.parse_submissions``; each listed release's index page through
``filings.parse_filing_index`` (an index page that does not parse is an invalid file, and
its exhibits are unknown); each document as a regular file within its size limit, decoded
by ``client.decode_document`` when its text is derived; every page of the newest capture
(``earningscalls.parse_events_page``, then ``check_capture`` over the pages together); and
the newest copy of the transcript of every call the capture lists that Rule B does not
drop (``earningscalls.parse_transcript``, against the listed call). A file in ``calls/``
named otherwise, a token that names no instant, an entry that is not a regular file (a
symbolic link, directory or special file) and a file where a filing's folder belongs are
invalid too. Invalid files are listed (``RawState.invalid_files``) and never repaired; the
agent renames one with the suffix ``.rejected``, which every read skips. A transcript of a
call the newest capture does not list is *unlisted*: left out and listed as such, never
invalid, since the provider's list decides which calls exist. A call's newest copy is the
one whose token names the latest instant not after the read's clock, the tokenless
``transcript_{ID}.json`` being the oldest; older captures and older copies are never read.

EDGAR's ``filings.recent`` covers a year or 1,000 filings at least, so a later submissions
file may no longer list an old period: everything of a period older than the oldest one
the newest submissions list is left out, as if it were not in ``raw/`` (its EDGAR folders,
the transcripts of its calls, which are then not checked, and its reports), and blocks
nothing.

A document's ``DOC_ID`` names its report ``reports/{T}/{DOC_ID}.md`` and its text file
``formatted/{T}/{DOC_ID}.md`` (``Document.text_name``): an EDGAR document's folder name,
``_`` and its file name without the extension
(``10-Q_2026-06-27_0000050863-26-000157_intc-20260627``); a call's ``call_{period}_{ID}``
(``call_2026-06-27_248001``). Two ``DOC_ID``s that differ only in letter case collide, as
their files would on a case-insensitive file system. An index page and a capture have no
text and no ``DOC_ID``.

The sentence rule reads an EDGAR document whose name ends in ``.txt`` (any case) in
layout mode (``layout_mode``), every other document, a call included, in block mode.

A period's earnings call (``PeriodFiles.call``) is ``transcript`` when the newest capture
lists calls Rule B places in the period and each one's transcript is in ``raw/``;
``missing`` when there is no valid capture, or a placed call's transcript is not in
``raw/`` or is invalid; and, when the capture places no call in the period, ``unavailable``
once the capture was fetched ``CALL_WAIT`` days or more after the period's *due date* (the
report date of its latest release, else the filing date of its 10-K or 10-Q), else
``waiting``. ``RawState.events_due`` says when ``fetch`` asks the provider for the list
again.
"""

import re
import stat
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from market_state_research.common.layout import REJECTED_SUFFIX, DataLayout, newest, stamped
from market_state_research.common.times import TOKEN_PATTERN, parse_timestamp_token, to_eastern

from .client import DOCUMENT_LIMIT, INDEX_LIMIT, JSON_LIMIT, decode_document
from .earningscalls import (
    BODY_LIMIT,
    MAX_ID,
    MAX_PAGES,
    CallEvent,
    CallText,
    call_text,
    check_capture,
    parse_events_page,
    parse_transcript,
)
from .filings import (
    PENDING,
    ExhibitRow,
    Period,
    Periods,
    Release,
    Submissions,
    Window,
    parse_filing_index,
    parse_submissions,
    select_periods,
)
from .text import html_text, plain_text, windows_1252

EDGAR = "edgar"
CALLS = "calls"
SUBMISSIONS_PREFIX = "submissions_"
SUBMISSIONS_SUFFIX = ".json"
EVENTS_PREFIX = "events_"
TRANSCRIPT_PREFIX = "transcript_"
INDEX_SUFFIX = "-index.htm"
# Days after a period's due date from which a calls list that places no call in the period
# shows it unavailable, and after which an unchanged verdict is asked for again.
CALL_WAIT = 7

NO_SUBMISSIONS = "no submissions file is in raw/; run fetch"
NOT_UTF8 = "the submissions body is not UTF-8"
NOT_IN_RAW = "the {what} is not in raw/ ({path}); run fetch"
INVALID_RAW = "the {what} in raw/ is invalid (see invalid_files); rename it with .rejected and run fetch"
NOT_REGULAR = "not a regular file"
NOT_A_FOLDER = "not a folder: a filing's documents belong in a folder of this name"
REPEATED_DOC_ID = "its DOC_ID {doc_id} is already another document's"
NOT_A_CALL_FILE = (
    "not a file fetch writes in calls/ (events_{TOKEN}_{PAGE}.json, transcript_{ID}.json or "
    "transcript_{ID}_{TOKEN}.json); rename it with .rejected"
)
PAGE_MISSING = "page {page} of this calls capture is not in raw/; rename the capture's pages with .rejected"
NO_CAPTURE = "no calls list from EarningsCalls.dev is in raw/; run fetch"
INVALID_CAPTURE = (
    "the newest calls list in raw/ is invalid (see invalid_files); rename its pages with .rejected "
    "and run fetch"
)
TRANSCRIPT_MISSING = "the transcript of the call {id} ({day}) is not in raw/ ({path}); run fetch"
TRANSCRIPT_INVALID = (
    "the transcript of the call {id} ({day}) in raw/ is invalid (see invalid_files); "
    "rename it with .rejected and run fetch"
)
NOT_LISTED_YET = (
    "EarningsCalls.dev lists no call for the period as of {as_of}; a list fetched on or after "
    "{verdict} that lists none shows it unavailable"
)

DocumentKind = Literal["filing", "exhibit", "call"]
CallStatus = Literal["transcript", "unavailable", "waiting", "missing"]

# The date a DOC_ID starts with: a 10-K's, 10-Q's or call's period, an 8-K's report date.
_DOC_ID_DATE = re.compile(r"(?:10-K|10-Q|8-K|call)_([0-9]{4}-[0-9]{2}-[0-9]{2})_", re.ASCII)
_EVENTS_NAME = re.compile(rf"events_(?P<token>{TOKEN_PATTERN})_(?P<page>[1-9][0-9]?)\.json", re.ASCII)
_TRANSCRIPT_NAME = re.compile(
    rf"transcript_(?P<id>[1-9][0-9]{{0,11}})(?:_(?P<token>{TOKEN_PATTERN}))?\.json", re.ASCII
)


class _SubmissionsHead(BaseModel):
    """The one value read before ``parse_submissions``: the CIK the body names, as EDGAR writes it."""

    model_config = ConfigDict(strict=True, extra="ignore", frozen=True, hide_input_in_errors=True)

    cik: Annotated[str, Field(pattern=r"^[0-9]{1,10}$")] | Annotated[int, Field(ge=0, lt=10**10)]


@dataclass(frozen=True)
class Document:
    """One document of a period that research quotes: a 10-K or 10-Q, an exhibit or a call.

    ``label`` names it for people (``10-Q for the period ended 2026-06-27``); ``filed`` is
    the EDGAR filing date of a filing or an exhibit's 8-K, None for a call; ``title`` and
    ``call`` are a call's: its transcript's title and the call the capture lists, whose
    New York date is ``call.day``.
    """

    doc_id: str
    kind: DocumentKind
    period: date
    path: Path
    label: str
    filed: date | None = None
    title: str | None = None
    call: CallEvent | None = None

    @property
    def text_name(self) -> str:
        """Its text file's name in ``formatted/{T}/``: ``{DOC_ID}.md``."""
        return f"{self.doc_id}.md"


@dataclass(frozen=True)
class ReleaseFiles:
    """One release of a period: its index page and each ``EX-99`` row the page lists, in Seq
    order, with the exhibit's document (None while it is not in ``raw/``). ``exhibits`` is
    empty while the index page is not in ``raw/`` or does not parse (``index_valid``)."""

    release: Release
    folder: str
    index_path: Path
    index_valid: bool
    exhibits: tuple[tuple[ExhibitRow, Document | None], ...]


@dataclass(frozen=True)
class Capture:
    """The newest valid calls capture: the New York time ``fetch`` read its first page, its
    pages' files in page order and the calls they list, newest first."""

    fetched_at: datetime
    pages: tuple[Path, ...]
    calls: tuple[CallEvent, ...]

    @property
    def day(self) -> date:
        return self.fetched_at.date()


@dataclass(frozen=True)
class CallState:
    """A period's earnings call: ``status`` (module docstring), the calls Rule B places in the
    period, their documents (the calls whose transcript is valid in ``raw/``), the period's
    due date, the date of the capture a verdict rests on and why the call is not settled."""

    status: CallStatus
    events: tuple[CallEvent, ...]
    documents: tuple[Document, ...]
    due: date
    as_of: date | None
    reason: str | None

    @property
    def settled(self) -> bool:
        """Whether the call is collected or shown unavailable: what a complete period needs."""
        return self.status in ("transcript", "unavailable")


@dataclass(frozen=True)
class PeriodFiles:
    """The raw files of one listed period: its filing (None while not in ``raw/``), its releases
    and its earnings call."""

    period: Period
    filing_path: Path
    filing: Document | None
    releases: tuple[ReleaseFiles, ...]
    call: CallState
    invalid: frozenset[Path]

    @property
    def day(self) -> date:
        return self.period.period

    @property
    def missing(self) -> str | None:
        """Why the period's EDGAR documents are not all in ``raw/`` (the first one), or None."""
        filing = self.period.filing
        what = f"{filing.form} {filing.accession} for the period ended {filing.period}"
        if self.filing is None:
            return self._absent(what, self.filing_path)
        for files in self.releases:
            release = files.release
            if not files.index_valid:
                return self._absent(
                    f"filing index page of the 8-K {release.accession} dated {release.report_date}",
                    files.index_path,
                )
            for row, document in files.exhibits:
                if document is None:
                    path = files.index_path.parent / row.document
                    return self._absent(f"{row.exhibit} {row.document} of the 8-K {release.accession}", path)
        return None

    def _absent(self, what: str, path: Path) -> str:
        if path in self.invalid or path.parent in self.invalid:
            return INVALID_RAW.format(what=what)
        return NOT_IN_RAW.format(what=what, path=path)

    @property
    def calls(self) -> tuple[Document, ...]:
        return self.call.documents

    @property
    def documents(self) -> tuple[Document, ...]:
        """Every document of the period in ``raw/``: the filing, the exhibits (release, then Seq
        order), then the calls (by their time)."""
        documents = [] if self.filing is None else [self.filing]
        documents.extend(document for files in self.releases for _, document in files.exhibits if document)
        documents.extend(self.calls)
        return tuple(documents)


def due_date(period: Period) -> date:
    """The date a period's call is expected by: its latest release's report date, else the filing
    date of its 10-K or 10-Q."""
    if period.releases:
        return max(release.report_date for release in period.releases)
    return period.filing.filed


@dataclass(frozen=True)
class RawState:
    """What one ticker's ``raw/`` tree holds: the periods the newest submissions file lists,
    oldest first, with their files, or ``reason`` why none is listed; the newest valid calls
    capture, the calls Rule B leaves pending and their transcripts, the unlisted transcripts,
    the newest copy of each call's transcript by call id (``transcript_files``, whatever its
    validity: the file ``fetch`` keeps or compares) and every invalid file."""

    ticker: str
    submissions: Path | None
    cik: str | None
    entity_name: str | None
    reason: str | None
    listing: Periods | None
    periods: tuple[PeriodFiles, ...]
    capture: Capture | None
    capture_problem: str | None
    pending_calls: tuple[CallEvent, ...]
    unlisted: tuple[Path, ...]
    transcript_files: Mapping[int, Path]
    invalid_files: tuple[tuple[Path, str], ...]

    def within(self, window: Window) -> tuple[PeriodFiles, ...]:
        """The listed periods whose end the window admits, oldest first."""
        return tuple(files for files in self.periods if window.admits(files.day))

    def documents(self) -> dict[str, Document]:
        """Every document of every listed period in ``raw/``, by ``DOC_ID``."""
        return {document.doc_id: document for files in self.periods for document in files.documents}

    def before_listing(self, doc_id: str) -> bool:
        """Whether ``doc_id`` (a report's file name without ``.md``) starts with a date before the
        oldest listed period's end: the report of a period ``filings.recent`` no longer lists."""
        match = _DOC_ID_DATE.match(doc_id)
        if match is None or not self.periods:
            return False
        try:
            return date.fromisoformat(match[1]) < self.periods[0].day
        except ValueError:  # not a calendar date
            return False

    def pending_in(self, window: Window) -> tuple[CallEvent, ...]:
        """The calls Rule B leaves pending, when the window ends on or after the newest listed
        period end (as ``filings.Periods.pending_in`` lists releases)."""
        if not self.periods or window.end < self.periods[-1].day:
            return ()
        return self.pending_calls

    def calls_to_fetch(self, window: Window) -> tuple[CallEvent, ...]:
        """Every call whose transcript ``fetch`` keeps: those Rule B places in a window period,
        oldest period first, then the pending ones ``pending_in`` lists."""
        placed = [event for files in self.within(window) for event in files.call.events]
        return (*placed, *self.pending_in(window))

    def events_due(self, window: Window, now: datetime) -> str | None:
        """Why ``fetch`` should ask EarningsCalls.dev for the calls list now, or None.

        Never while the window holds no listed period. With no valid capture, always.
        Otherwise only while a window period's call is ``waiting`` or ``unavailable``: when
        the newest capture is ``CALL_WAIT`` days old or more, or, for a ``waiting`` call,
        when the capture was fetched on or before the period's due date and that date has
        passed.
        """
        if not self.within(window):
            return None
        if self.capture is None:
            return self.capture_problem or NO_CAPTURE
        moment = to_eastern(now, "now")
        stale = moment - self.capture.fetched_at >= timedelta(days=CALL_WAIT)
        for files in self.within(window):
            call = files.call
            if call.status not in ("waiting", "unavailable"):
                continue
            day = files.day.isoformat()
            if stale:
                fetched = self.capture.day.isoformat()
                return (
                    f"the newest calls list, fetched {fetched}, is {CALL_WAIT} days old or more and lists "
                    f"no call for the period {day}"
                )
            if call.status == "waiting" and self.capture.day <= call.due < moment.date():
                return (
                    f"the newest calls list was fetched {self.capture.day.isoformat()}, on or before the "
                    f"period {day}'s due date {call.due.isoformat()}"
                )
        return None


# --------------------------------------------------------------------------- names


def edgar_folder(form: str, day: date, accession: str) -> str:
    """``{FORM}_{DATE}_{ACCESSION}``: a filing's folder under ``raw/{T}/edgar/``."""
    return f"{form}_{day.isoformat()}_{accession}"


def doc_id(folder: str, name: str) -> str:
    """An EDGAR document's ``DOC_ID``: its folder, ``_`` and its file name without the extension."""
    return f"{folder}_{Path(name).stem}"


def call_doc_id(period: date, call_id: int) -> str:
    """A call's ``DOC_ID``: ``call_{period}_{ID}``."""
    return f"call_{period.isoformat()}_{call_id}"


def events_name(moment: datetime, page: int) -> str:
    """Page ``page`` of the calls capture ``fetch`` read at ``moment``: ``events_{token}_{PAGE}.json``."""
    if isinstance(page, bool) or not isinstance(page, int) or not 1 <= page <= MAX_PAGES:
        raise ValueError(f"a calls page is a number from 1 to {MAX_PAGES}")
    return stamped(EVENTS_PREFIX.rstrip("_"), moment, f"_{page}.json")


def transcript_name(call_id: int, moment: datetime | None = None) -> str:
    """The transcript of the call ``call_id``: ``transcript_{ID}.json``, or the copy ``fetch --refresh``
    read at ``moment``: ``transcript_{ID}_{token}.json``."""
    if isinstance(call_id, bool) or not isinstance(call_id, int) or not 1 <= call_id <= MAX_ID:
        raise ValueError(f"a call id is a whole number from 1 to {MAX_ID}")
    if moment is None:
        return f"{TRANSCRIPT_PREFIX}{call_id}.json"
    return stamped(f"{TRANSCRIPT_PREFIX}{call_id}", moment, ".json")


def layout_mode(document: Document) -> bool:
    """Whether the sentence rule reads the document's line breaks as whitespace: an EDGAR document
    whose name ends in ``.txt`` (any case), whose lines wrap where the page ran out. HTML and
    iXBRL documents and a call's text (a heading line, then a line per paragraph, per turn)
    break at their blocks."""
    return document.kind in ("filing", "exhibit") and document.path.name.lower().endswith(".txt")


# --------------------------------------------------------------------------- files


def _regular(path: Path, limit: int) -> None:
    """Refuse ``path`` unless it is a regular file of at most ``limit`` bytes, without opening it."""
    try:
        info = path.lstat()
    except FileNotFoundError:
        raise ValueError("file not found") from None
    if not stat.S_ISREG(info.st_mode):
        raise ValueError(NOT_REGULAR)
    if info.st_size > limit:
        raise ValueError(f"larger than {limit} bytes")


def read_raw(path: Path, limit: int) -> bytes:
    """The bytes of the regular file ``path``, at most ``limit`` of them, else ``ValueError``.

    A symbolic link, directory or special file is refused without being opened.
    """
    _regular(path, limit)
    with path.open("rb") as handle:
        data = handle.read(limit + 1)
    if len(data) > limit:  # the file grew after it was checked
        raise ValueError(f"larger than {limit} bytes")
    return data


def _present(path: Path, limit: int, invalid: list[tuple[Path, str]]) -> bool:
    """Whether ``path`` is a regular file within ``limit``; anything else there is invalid."""
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    except NotADirectoryError:  # a file where the document's folder belongs
        invalid.append((path.parent, NOT_A_FOLDER))
        return False
    if not stat.S_ISREG(info.st_mode):
        invalid.append((path, NOT_REGULAR))
        return False
    if info.st_size > limit:
        invalid.append((path, f"larger than {limit} bytes"))
        return False
    return True


def read_submissions(path: Path) -> Submissions:
    """The submissions file ``path``, read strictly by ``filings.parse_submissions`` for the CIK
    its body names (so a body is never read as another issuer's)."""
    data = read_raw(path, JSON_LIMIT)
    try:
        body = data.decode("utf-8")
    except UnicodeDecodeError:
        raise ValueError(NOT_UTF8) from None
    try:
        cik = _SubmissionsHead.model_validate_json(data).cik
    except ValidationError:
        raise ValueError("submissions: cik must be a string of up to ten digits or an integer") from None
    return parse_submissions(body, f"{int(cik):010d}")


# --------------------------------------------------------------------------- calls


@dataclass(frozen=True)
class _Calls:
    """What ``calls/`` holds: the newest valid capture, the valid newest transcript copy of each
    listed call that Rule B keeps (with its title), the unlisted transcripts, the newest copy of
    each call's transcript whatever its validity, and the invalid files."""

    capture: Capture | None
    problem: str | None  # why there is no valid capture: none in raw/, or the newest is invalid
    transcripts: dict[int, tuple[Path, str]]
    unlisted: tuple[Path, ...]
    transcript_files: dict[int, Path]
    invalid: list[tuple[Path, str]]


def read_capture(ticker: str, pages: list[Path]) -> tuple[CallEvent, ...]:
    """The calls of one capture, its page files in page order, read strictly; ``ValueError``
    names the page file at fault (``earningscalls.check_capture`` for the pages together)."""
    read = []
    for path in pages:
        try:
            read.append(parse_events_page(read_raw(path, BODY_LIMIT)))
        except ValueError as error:
            raise _PageError(path, str(error)) from None
    return check_capture(ticker, read)


class _PageError(ValueError):
    """A problem of one page file of a capture."""

    def __init__(self, path: Path, message: str) -> None:
        super().__init__(message)
        self.path = path


def _newest_capture(
    ticker: str, captures: dict[datetime, dict[int, Path]], now: datetime, invalid: list[tuple[Path, str]]
) -> tuple[Capture | None, bool]:
    """The newest capture not after ``now``, validated, and whether there was one at all."""
    instants = [instant for instant in captures if instant <= now]
    if not instants:
        return None, False
    fetched_at = max(instants)
    pages = captures[fetched_at]
    numbers = sorted(pages)
    ordered = [pages[number] for number in numbers]
    gaps = [number for number in range(1, numbers[-1] + 1) if number not in pages]
    if gaps:
        invalid.append((ordered[0], PAGE_MISSING.format(page=gaps[0])))
        return None, True
    try:
        calls = read_capture(ticker, ordered)
    except _PageError as error:
        invalid.append((error.path, str(error)))
        return None, True
    except ValueError as error:  # the pages together: their count, totals, symbols or issuers
        invalid.append((ordered[0], str(error)))
        return None, True
    return Capture(fetched_at, tuple(ordered), calls), True


def _read_calls(directory: Path, ticker: str, listing: Periods | None, now: datetime) -> _Calls:
    """The newest capture and the newest copy of each transcript in ``directory``, every file there
    validated as the module docstring says."""
    moment = to_eastern(now, "now")
    invalid: list[tuple[Path, str]] = []
    captures: dict[datetime, dict[int, Path]] = {}
    # Each call's newest copy so far, with the instant its token names (None: the tokenless one).
    copies: dict[int, tuple[datetime | None, Path]] = {}
    for path in sorted(directory.iterdir()) if directory.is_dir() else ():
        if path.name.startswith(".") or path.name.endswith(REJECTED_SUFFIX):
            continue
        if not stat.S_ISREG(path.lstat().st_mode):
            invalid.append((path, NOT_REGULAR))
            continue
        events = _EVENTS_NAME.fullmatch(path.name)
        if events is not None:
            instant = parse_timestamp_token(events["token"])
            if instant is None:
                invalid.append((path, NOT_A_CALL_FILE))
            else:
                captures.setdefault(instant, {})[int(events["page"])] = path
            continue
        named = _TRANSCRIPT_NAME.fullmatch(path.name)
        token = None if named is None else named["token"]
        instant = None if token is None else parse_timestamp_token(token)
        if named is None or (token is not None and instant is None):
            invalid.append((path, NOT_A_CALL_FILE))
            continue
        if instant is not None and instant > moment:
            continue  # named after the clock: not read yet
        call_id = int(named["id"])
        held = copies.get(call_id)
        if held is None or (instant is not None and (held[0] is None or instant > held[0])):
            copies[call_id] = (instant, path)
    capture, existed = _newest_capture(ticker, captures, moment, invalid)
    problem = None if capture is not None else INVALID_CAPTURE if existed else NO_CAPTURE
    listed = {} if capture is None else {event.id: event for event in capture.calls}
    transcripts = {call_id: path for call_id, (_, path) in sorted(copies.items())}
    kept: dict[int, tuple[Path, str]] = {}
    unlisted: list[Path] = []
    for call_id, path in transcripts.items():
        event = listed.get(call_id)
        if event is None:
            unlisted.append(path)
            continue
        if listing is not None and listing.place(event.day) is None:
            continue  # its period is older than every listed one: left out unchecked
        try:
            transcript = parse_transcript(read_raw(path, BODY_LIMIT), event)
        except ValueError as error:
            invalid.append((path, str(error)))
            continue
        kept[call_id] = (path, transcript.title)
    return _Calls(capture, problem, kept, tuple(unlisted), transcripts, invalid)


def _call_document(period: date, event: CallEvent, path: Path, title: str) -> Document:
    return Document(
        doc_id=call_doc_id(period, event.id),
        kind="call",
        period=period,
        path=path,
        label=f"earnings call {period}: {title}",
        title=title,
        call=event,
    )


def _call_state(
    period: Period,
    placed: tuple[CallEvent, ...],
    calls: _Calls,
    directory: Path,
    invalid: frozenset[Path],
) -> CallState:
    """The period's earnings call (module docstring); ``placed`` are the calls of the newest
    capture Rule B places in it, oldest first."""
    due = due_date(period)
    capture = calls.capture
    if capture is None:
        return CallState("missing", (), (), due, None, calls.problem)
    if not placed:
        verdict = due + timedelta(days=CALL_WAIT)
        if capture.day >= verdict:
            return CallState("unavailable", (), (), due, capture.day, None)
        reason = NOT_LISTED_YET.format(as_of=capture.day.isoformat(), verdict=verdict.isoformat())
        return CallState("waiting", (), (), due, capture.day, reason)
    documents: list[Document] = []
    missing: str | None = None
    for event in placed:
        held = calls.transcripts.get(event.id)
        if held is not None:
            documents.append(_call_document(period.period, event, *held))
            continue
        path = calls.transcript_files.get(event.id, directory / transcript_name(event.id))
        message = TRANSCRIPT_INVALID if path in invalid else TRANSCRIPT_MISSING
        missing = missing or message.format(id=event.id, day=event.day.isoformat(), path=path)
    status: CallStatus = "transcript" if missing is None else "missing"
    return CallState(status, placed, tuple(documents), due, capture.day, missing)


# --------------------------------------------------------------------------- EDGAR documents


def _filing(edgar: Path, period: Period, invalid: list[tuple[Path, str]]) -> tuple[Path, Document | None]:
    filing = period.filing
    folder = edgar_folder(filing.form, filing.period, filing.accession)
    path = edgar / folder / filing.primary_document
    if not _present(path, DOCUMENT_LIMIT, invalid):
        return path, None
    return path, Document(
        doc_id=doc_id(folder, filing.primary_document),
        kind="filing",
        period=filing.period,
        path=path,
        label=f"{filing.form} for the period ended {filing.period}",
        filed=filing.filed,
    )


def _release(
    edgar: Path, cik: str, period: date, release: Release, invalid: list[tuple[Path, str]]
) -> ReleaseFiles:
    folder = edgar_folder("8-K", release.report_date, release.accession)
    index_path = edgar / folder / f"{release.accession}{INDEX_SUFFIX}"
    if not _present(index_path, INDEX_LIMIT, invalid):
        return ReleaseFiles(release, folder, index_path, False, ())
    try:
        body, _ = decode_document(read_raw(index_path, INDEX_LIMIT))
        rows = parse_filing_index(body, cik, release.accession).exhibits
    except ValueError as error:
        invalid.append((index_path, str(error)))
        return ReleaseFiles(release, folder, index_path, False, ())
    exhibits: list[tuple[ExhibitRow, Document | None]] = []
    for row in rows:
        path = edgar / folder / row.document
        document = None
        if _present(path, DOCUMENT_LIMIT, invalid):
            document = Document(
                doc_id=doc_id(folder, row.document),
                kind="exhibit",
                period=period,
                path=path,
                label=f"{row.exhibit} of the 8-K dated {release.report_date} ({row.document})",
                filed=release.filed,
            )
        exhibits.append((row, document))
    return ReleaseFiles(release, folder, index_path, True, tuple(exhibits))


def _period_files(
    edgar: Path,
    cik: str,
    period: Period,
    placed: tuple[CallEvent, ...],
    calls: _Calls,
    directory: Path,
    invalid: list[tuple[Path, str]],
) -> PeriodFiles:
    filing_path, filing = _filing(edgar, period, invalid)
    releases = tuple(_release(edgar, cik, period.period, release, invalid) for release in period.releases)
    paths = frozenset(path for path, _ in (*invalid, *calls.invalid))
    return PeriodFiles(
        period=period,
        filing_path=filing_path,
        filing=filing,
        releases=releases,
        call=_call_state(period, placed, calls, directory, paths),
        invalid=paths,
    )


def _repeated_ids(periods: tuple[PeriodFiles, ...]) -> Iterator[tuple[Path, str]]:
    """Every document whose ``DOC_ID`` an earlier document already has, letter case aside (their
    files would collide, on a case-insensitive file system too)."""
    seen: set[str] = set()
    for files in periods:
        for document in files.documents:
            folded = document.doc_id.casefold()
            if folded in seen:
                yield document.path, REPEATED_DOC_ID.format(doc_id=document.doc_id)
            seen.add(folded)


def period_documents(layout: DataLayout, ticker: str, now: datetime) -> RawState:
    """Read ``ticker``'s raw tree: the periods its newest submissions file lists, each with its
    files and its call, the newest calls capture, and every invalid file with the reason.

    Without a submissions file, or with one that does not parse or whose periods
    ``filings.select_periods`` refuses, no period is listed and ``reason`` says why; the
    files in ``calls/`` are still validated, every transcript of a listed call included.
    The transcript of a call Rule B drops (dated on or before the oldest listed period end)
    is left out unchecked.
    """
    now = to_eastern(now, "now")
    raw = layout.raw(ticker)
    edgar = raw / EDGAR
    invalid: list[tuple[Path, str]] = []
    path = newest(edgar, SUBMISSIONS_PREFIX, SUBMISSIONS_SUFFIX, now)
    submissions: Submissions | None = None
    listing: Periods | None = None
    reason: str | None = NO_SUBMISSIONS if path is None else None
    if path is not None:
        try:
            submissions = read_submissions(path)
        except ValueError as error:  # the file is not a submissions body EDGAR serves
            invalid.append((path, str(error)))
            reason = f"{path.name} is invalid (see invalid_files); rename it with .rejected and run fetch"
    if submissions is not None:
        try:
            listing = select_periods(submissions)
        except ValueError as error:  # no exact 10-K or 10-Q, two for one period, an undated release
            reason = str(error)
    directory = raw / CALLS
    calls = _read_calls(directory, ticker, listing, now)
    # Rule B on each listed call's New York date, oldest call first.
    placed: dict[date, list[CallEvent]] = {}
    pending: list[CallEvent] = []
    if listing is not None and calls.capture is not None:
        for event in reversed(calls.capture.calls):
            place = listing.place(event.day)
            if place == PENDING:
                pending.append(event)
            elif isinstance(place, Period):
                placed.setdefault(place.period, []).append(event)
    periods: tuple[PeriodFiles, ...] = ()
    if listing is not None and submissions is not None:
        cik = submissions.cik
        periods = tuple(
            _period_files(edgar, cik, period, tuple(placed.get(period.period, ())), calls, directory, invalid)
            for period in listing.periods
        )
    invalid.extend(calls.invalid)
    invalid.extend(_repeated_ids(periods))
    return RawState(
        ticker=ticker,
        submissions=path,
        cik=None if submissions is None else submissions.cik,
        entity_name=None if submissions is None else submissions.entity_name,
        reason=reason,
        listing=listing,
        periods=periods,
        capture=calls.capture,
        capture_problem=calls.problem,
        pending_calls=tuple(pending),
        unlisted=calls.unlisted,
        transcript_files=calls.transcript_files,
        invalid_files=tuple(invalid),
    )


# --------------------------------------------------------------------------- derived text


def edgar_text(data: bytes, name: str) -> str:
    """The derived text of a document EDGAR served: plain text for a ``.txt`` name, else HTML.

    The bytes are decoded as ``client.decode_document`` decodes them (strict UTF-8, else
    Latin-1); a Latin-1 document is read as windows-1252, as a browser shows it.
    """
    body, encoding = decode_document(data)
    text = windows_1252(body) if encoding == "latin-1" else body
    if name.lower().endswith(".txt"):
        return plain_text(text)
    return html_text(text)


def derive_call(document: Document) -> CallText:
    """A call's derived text and its turns, from its transcript in ``raw/``
    (``earningscalls.call_text``)."""
    if document.call is None:
        raise ValueError(f"{document.doc_id}: not a call")
    return call_text(parse_transcript(read_raw(document.path, BODY_LIMIT), document.call))


def derive_text(document: Document) -> str:
    """The derived text of a filing or exhibit, from its raw bytes, or of a call, from its
    transcript."""
    if document.kind == "call":
        return derive_call(document).text
    return edgar_text(read_raw(document.path, DOCUMENT_LIMIT), document.path.name)
