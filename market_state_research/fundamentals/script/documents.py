"""One ticker's ``raw/`` tree read into its seasons and their documents, and their derived text.

The raw tree of a ticker ``T`` (``common.layout.DataLayout.raw``) holds, verbatim, what
``fetch`` wrote:

- ``submissions_{TOKEN}.json``: EDGAR's submissions JSON, written only when its body differs
  from the newest one's; the newest lists the seasons on every read;
- ``companyfacts_{TOKEN}.json``: EDGAR's XBRL company facts (``facts``), likewise;
- ``calls_{TOKEN}_{PAGE}.json``: one page of the ticker's earnings calls as EarningsCalls.dev
  listed them (``earningscalls``); the pages of one request share the New York time ``fetch``
  read the first one and form one *capture*, and the newest capture's time is when the
  provider last showed its list;
- ``{PERIOD}/``: one folder per season, named by its period end, holding
  - ``{FORM}_{DATE}_{ACCESSION}/``: one filing's documents as EDGAR served them, ``FORM``
    the form without spaces or slashes (``filings.FORM_TOKENS``) and ``DATE`` the date Rule B
    places it by (the period end for the season's own 10-K or 10-Q): a 10-K's or 10-Q's
    primary document; an 8-K's filing index page ``{ACCESSION}-index.htm``, its primary
    document and the ``EX-99`` exhibits the page lists; a proxy statement's or a beneficial
    owner's schedule's primary document (an XML one under the raw file's own name,
    ``filings.rendered_document``); a Form 4's XML;
  - ``transcript_{ID}.json``: the transcript of the call ``ID`` Rule B places in the season,
    as EarningsCalls.dev served it, written once; ``fetch --refresh`` writes a copy whose
    bytes differ from the newest one's beside it as ``transcript_{ID}_{TOKEN}.json``.

Nothing a later read needs lives only in a name: the newest submissions file lists the
seasons and places every filing by Rule B (``filings.select_seasons``) on every read; an
8-K's exhibits come from its index page, parsed again on every read; the newest capture
lists the calls, each placed in a season by Rule B on its New York date; a Form 4's issuer
and transactions come from its XML (``form4``). A file is kept where Rule B placed it when
``fetch`` wrote it; a read that places it in another season, or leaves it pending, reports
it *moved*: an invalid file, which the bot renames with ``.rejected`` so that ``fetch`` writes
it again in its season.

Every read validates what it reads: the newest submissions file through
``filings.parse_submissions``; the newest company facts through ``facts.read_companyfacts``;
each 8-K's index page through ``filings.parse_filing_index`` (one that does not parse is an
invalid file, and its exhibits are unknown); each Form 4 through ``form4.parse_form4``; each
document as a regular file within its size limit; every page of the newest capture
(``earningscalls.parse_events_page``, then ``check_capture``); and the newest copy of the
transcript of every call the capture places in a listed season (``parse_transcript``). Every
entry of ``raw/{T}/`` and of a season folder that ``fetch`` does not write, an entry that is
not a regular file where a file belongs, and a file where a folder belongs are invalid too,
but for three kinds left out: a name ending in ``.rejected`` (withdrawn by the bot), a
season folder older than the oldest listed season (``filings.recent`` no longer lists it),
and a filing folder or transcript whose accession or call the newest listing does not hold
(*unlisted*). ``raw/{T}/edgar/`` and ``raw/{T}/calls/`` are the *former layout* (until
2026-10-23), never read: the bot renames each with ``.rejected`` and ``fetch`` writes the
window again. Invalid files are listed (``RawState.invalid_files``) and never repaired.

A document's ``DOC_ID`` names its derived text ``formatted/{T}/{PERIOD}/{DOC_ID}.md``
(``Document.text_name``) and is how a reading cites it: an EDGAR document's folder name,
``_`` and its file name without the extension
(``10-Q_2026-06-27_0000050863-26-000157_intc-20260627``); a call's ``call_{PERIOD}_{ID}``.
Two ``DOC_ID``s that differ only in letter case collide. A filing index page, a Form 4's XML,
the company facts and a capture are read by Python and quoted by no one: they have no
``DOC_ID``.

The sentence rule reads an EDGAR document whose name ends in ``.txt`` (any case) in layout
mode (``layout_mode``), every other document, a call included, in block mode.

A season's earnings call (``SeasonFiles.call``) is ``transcript`` when the newest capture
places calls in the season and each one's transcript is in ``raw/``; ``missing`` when there is
no valid capture, or a placed call's transcript is not in ``raw/`` or is invalid; and, when the
capture places no call in the season, ``unavailable`` once the capture was fetched
``CALL_WAIT`` days or more after the season's *due date* (the date of its latest earnings
release, else the filing date of its 10-K or 10-Q), else ``waiting``.
``RawState.events_due`` says when ``fetch`` asks the provider for the list again.
"""

import re
import stat
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from market_state_research.common.layout import REJECTED_SUFFIX, DataLayout, stamped
from market_state_research.common.times import TOKEN_PATTERN, parse_timestamp_token, to_eastern

from .client import COMPANYFACTS_LIMIT, DOCUMENT_LIMIT, INDEX_LIMIT, JSON_LIMIT, decode_document
from .earningscalls import (
    BODY_LIMIT,
    MAX_ID,
    MAX_PAGES,
    CallEvent,
    CallText,
    Transcript,
    call_text,
    check_capture,
    parse_events_page,
    parse_transcript,
)
from .facts import CompanyFacts, read_companyfacts
from .filings import (
    FORM_TOKENS,
    PENDING,
    Dated,
    ExhibitRow,
    Season,
    Seasons,
    Submissions,
    Window,
    parse_filing_index,
    parse_submissions,
    select_seasons,
)
from .form4 import Form4, parse_form4
from .items import BASELINE_SEASONS
from .text import html_text, plain_text, windows_1252, xml_text

SUBMISSIONS_PREFIX = "submissions_"
COMPANYFACTS_PREFIX = "companyfacts_"
CALLS_PREFIX = "calls_"
JSON_SUFFIX = ".json"
TRANSCRIPT_PREFIX = "transcript_"
INDEX_SUFFIX = "-index.htm"
FORMER_LAYOUT = ("edgar", "calls")
# Days after a season's due date from which a calls list that places no call in the season
# shows it unavailable, and after which an unchanged verdict is asked for again.
CALL_WAIT = 7

NO_SUBMISSIONS = "no submissions file is in raw/; run fetch"
NOT_UTF8 = "the submissions body is not UTF-8"
SUBMISSIONS_INVALID = "is invalid (see invalid_files); rename it with .rejected and run fetch"
NOT_IN_RAW = "the {what} is not in raw/ ({path}); run fetch"
INVALID_RAW = "the {what} in raw/ is invalid (see invalid_files); rename it with .rejected and run fetch"
NOT_REGULAR = "not a regular file"
NOT_A_FOLDER = "not a folder: a filing's or a season's documents belong in a folder of this name"
REPEATED_DOC_ID = "its DOC_ID {doc_id} is already another document's"
NOT_RAW = (
    "not a file or folder fetch writes in raw/{where} (see the domain's AGENTS.md, Runtime files); "
    "rename it with .rejected"
)
NOT_A_SEASON = "no season of the newest submissions ends on this date; rename it with .rejected"
MOVED = (
    "the newest submissions place this filing {where}, not in this season; rename it with .rejected "
    "and run fetch"
)
MOVED_CALL = (
    "the newest calls list places this call {where}, not in this season; rename it with .rejected and "
    "run fetch"
)
MISNAMED = "the newest submissions name this filing's folder {name}; rename it with .rejected and run fetch"
FORMER = "the former layout (until 2026-10-23): rename it with .rejected, then run fetch"
PAGE_MISSING = "page {page} of this calls capture is not in raw/; rename the capture's pages with .rejected"
NO_CAPTURE = "no calls list from EarningsCalls.dev is in raw/; run fetch"
INVALID_CAPTURE = (
    "the newest calls list in raw/ is invalid (see invalid_files); rename its pages with .rejected and "
    "run fetch"
)
NO_FACTS = "no companyfacts file is in raw/; run fetch"
INVALID_FACTS = (
    "the newest companyfacts file is invalid (see invalid_files); rename it with .rejected and run fetch"
)
FACTS_WAITING = (
    "the newest companyfacts, fetched {fetched}, on or before the {form} {accession} was filed, holds no "
    "fact of it: a later fetch brings them"
)
FACTS_ABSENT = "EDGAR's companyfacts, fetched {fetched}, holds no fact of the {form} {accession}"
TRANSCRIPT_MISSING = "the transcript of the call {id} ({day}) is not in raw/ ({path}); run fetch"
TRANSCRIPT_INVALID = (
    "the transcript of the call {id} ({day}) in raw/ is invalid (see invalid_files); rename it with "
    ".rejected and run fetch"
)
NOT_LISTED_YET = (
    "EarningsCalls.dev lists no call for the season as of {as_of}; a list fetched on or after {verdict} "
    "that lists none shows it unavailable"
)

DocumentKind = Literal["filing", "8-K", "exhibit", "proxy", "holder", "call"]
CallStatus = Literal["transcript", "unavailable", "waiting", "missing"]
FactsStatus = Literal["present", "missing", "waiting", "absent"]

_SEASON_NAME = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", re.ASCII)
_FILING_NAME = re.compile(
    rf"(?P<form>{'|'.join(re.escape(token) for token in FORM_TOKENS.values())})_"
    r"(?P<date>[0-9]{4}-[0-9]{2}-[0-9]{2})_(?P<accession>[0-9]{10}-[0-9]{2}-[0-9]{6})",
    re.ASCII,
)
_STAMPED = re.compile(rf"(?P<prefix>submissions|companyfacts)_(?P<token>{TOKEN_PATTERN})\.json", re.ASCII)
_CALLS_NAME = re.compile(rf"calls_(?P<token>{TOKEN_PATTERN})_(?P<page>[1-9][0-9]?)\.json", re.ASCII)
_TRANSCRIPT_NAME = re.compile(
    rf"transcript_(?P<id>[1-9][0-9]{{0,11}})(?:_(?P<token>{TOKEN_PATTERN}))?\.json", re.ASCII
)
_KINDS: Mapping[str, DocumentKind] = {
    "8-K": "8-K",
    "DEF 14A": "proxy",
    "SC 13D/A": "holder",
    "SC 13G/A": "holder",
    "SCHEDULE 13D/A": "holder",
    "SCHEDULE 13G/A": "holder",
}


class _SubmissionsHead(BaseModel):
    """The one value read before ``parse_submissions``: the CIK the body names, as EDGAR writes it."""

    model_config = ConfigDict(strict=True, extra="ignore", frozen=True, hide_input_in_errors=True)

    cik: Annotated[str, Field(pattern=r"^[0-9]{1,10}$")] | Annotated[int, Field(ge=0, lt=10**10)]


@dataclass(frozen=True)
class Document:
    """One document of a season that the bot reads and quotes: a 10-K or 10-Q (``filing``), an
    8-K's primary document (``8-K``), an exhibit, a proxy statement (``proxy``), a beneficial
    owner's schedule (``holder``) or a call.

    ``label`` names it for people; ``form``, ``accession`` and ``filed`` are its filing's (None
    for a call); ``title`` and ``call`` are a call's: its transcript's title and the call the
    capture lists, whose New York date is ``call.day``.
    """

    doc_id: str
    kind: DocumentKind
    season: date
    path: Path
    label: str
    form: str | None = None
    accession: str | None = None
    filed: date | None = None
    title: str | None = None
    call: CallEvent | None = None

    @property
    def text_name(self) -> str:
        """Its text file's name in ``formatted/{T}/{PERIOD}/``: ``{DOC_ID}.md``."""
        return f"{self.doc_id}.md"


@dataclass(frozen=True)
class Needed:
    """One file a filing needs in ``raw/``: what it is, where, and whether it is there."""

    what: str
    path: Path
    present: bool


@dataclass(frozen=True)
class FilingFiles:
    """One filing of a season whose documents ``fetch`` writes: its listing row, its folder, the
    files it needs (an 8-K's exhibits are known once its index page parses: ``index_valid``),
    its quotable documents in ``raw/`` and, for a Form 4, its XML read (None while it is not in
    ``raw/`` or does not parse)."""

    item: Dated
    folder: Path
    needed: tuple[Needed, ...]
    index_valid: bool
    exhibits: tuple[ExhibitRow, ...]
    documents: tuple[Document, ...]
    form4: Form4 | None = None


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
    """A season's earnings call: ``status`` (module docstring), the calls Rule B places in the
    season, their documents (the calls whose transcript is valid in ``raw/``) with each one's
    transcript, the season's due date, the date of the capture a verdict rests on and why the
    call is not settled."""

    status: CallStatus
    events: tuple[CallEvent, ...]
    documents: tuple[Document, ...]
    transcripts: tuple[Transcript, ...]
    due: date
    as_of: date | None
    reason: str | None

    @property
    def settled(self) -> bool:
        """Whether the call is collected or shown unavailable."""
        return self.status in ("transcript", "unavailable")


@dataclass(frozen=True)
class SeasonFiles:
    """The raw files of one listed season: its folder, its 10-K or 10-Q (None while not in
    ``raw/``), the filings ``fetch`` writes, its earnings call and the invalid paths among them."""

    season: Season
    folder: Path
    filing_path: Path
    filing: Document | None
    filings: tuple[FilingFiles, ...]
    call: CallState
    invalid: frozenset[Path]

    @property
    def day(self) -> date:
        return self.season.period

    @property
    def missing(self) -> str | None:
        """Why the season's EDGAR documents are not all in ``raw/`` (the first one), or None."""
        own = self.season.filing
        if self.filing is None:
            return self._absent(
                f"{own.form} {own.accession} for the period ended {own.period}", self.filing_path
            )
        for files in self.filings:
            for needed in files.needed:
                if not needed.present:
                    return self._absent(needed.what, needed.path)
        return None

    def _absent(self, what: str, path: Path) -> str:
        if path in self.invalid or path.parent in self.invalid:
            return INVALID_RAW.format(what=what)
        return NOT_IN_RAW.format(what=what, path=path)

    @property
    def documents(self) -> tuple[Document, ...]:
        """Every document of the season in ``raw/``: the 10-K or 10-Q, each filing's documents (in
        the season's order), then the calls (by their time)."""
        documents = [] if self.filing is None else [self.filing]
        documents.extend(document for files in self.filings for document in files.documents)
        documents.extend(self.call.documents)
        return tuple(documents)

    def form4s(self) -> tuple[tuple[str, Form4], ...]:
        """Each Form 4 of the season read from ``raw/``, by accession."""
        return tuple((files.item.accession, files.form4) for files in self.filings if files.form4 is not None)


def due_date(season: Season) -> date:
    """The date a season's call is expected by: its latest release's date, else the filing date
    of its 10-K or 10-Q."""
    releases = season.releases
    return max(release.dated for release in releases) if releases else season.filing.filed


@dataclass(frozen=True)
class RawState:
    """What one ticker's ``raw/`` tree holds: the seasons the newest submissions file lists,
    oldest first, with their files, or ``reason`` why none is listed; the newest valid company
    facts and calls capture; the pending calls; what is left out (``unlisted``, the former
    layout); the newest copy of each call's transcript by call id (``transcript_files``,
    whatever its validity: the file ``fetch`` keeps or compares); and every invalid file."""

    ticker: str
    submissions: Path | None
    cik: str | None
    entity_name: str | None
    reason: str | None
    listing: Seasons | None
    seasons: tuple[SeasonFiles, ...]
    companyfacts: Path | None
    facts: CompanyFacts | None
    facts_problem: str | None
    capture: Capture | None
    capture_problem: str | None
    pending_calls: tuple[CallEvent, ...]
    unlisted: tuple[Path, ...]
    former_layout: tuple[Path, ...]
    transcript_files: Mapping[int, Path]
    invalid_files: tuple[tuple[Path, str], ...]

    def within(self, window: Window) -> tuple[SeasonFiles, ...]:
        """The listed seasons whose end the window admits, oldest first."""
        return tuple(files for files in self.seasons if window.admits(files.day))

    def span(self, window: Window) -> tuple[SeasonFiles, ...]:
        """The window's seasons and the ``BASELINE_SEASONS`` listed seasons before the oldest of
        them, whose documents the window's readings compare with; oldest first."""
        inside = [position for position, files in enumerate(self.seasons) if window.admits(files.day)]
        if not inside:
            return ()
        return self.seasons[max(0, inside[0] - BASELINE_SEASONS) : inside[-1] + 1]

    def season(self, day: date) -> SeasonFiles | None:
        return next((files for files in self.seasons if files.day == day), None)

    def documents(self) -> dict[str, Document]:
        """Every document of every listed season in ``raw/``, by ``DOC_ID``."""
        return {document.doc_id: document for files in self.seasons for document in files.documents}

    def pending_in(self, window: Window) -> tuple[CallEvent, ...]:
        """The calls Rule B leaves pending, when the window ends on or after the newest listed
        season end (as ``filings.Seasons.pending_in`` lists filings)."""
        if not self.seasons or window.end < self.seasons[-1].day:
            return ()
        return self.pending_calls

    def facts_status(self, files: SeasonFiles) -> tuple[FactsStatus, str | None]:
        """Whether the newest company facts hold the season's 10-K or 10-Q: ``present``;
        ``missing`` (no valid file: ``fetch`` writes one); ``waiting`` (fetched on or before the
        filing's date, so without it: every ``fetch`` asks again); ``absent`` (fetched after it
        and still without it: its figures are not computable); with the reason."""
        if self.facts is None or self.companyfacts is None:
            return "missing", self.facts_problem or NO_FACTS
        own = files.season.filing
        if own.accession in self.facts.accessions:
            return "present", None
        fetched = _token_instant(self.companyfacts)
        fetched_day = None if fetched is None else fetched.date()
        details = {"fetched": str(fetched_day), "form": own.form, "accession": own.accession}
        if fetched_day is None or fetched_day <= own.filed:
            return "waiting", FACTS_WAITING.format(**details)
        return "absent", FACTS_ABSENT.format(**details)

    def events_due(self, window: Window, now: datetime) -> str | None:
        """Why ``fetch`` should ask EarningsCalls.dev for the calls list now, or None.

        Never while the window holds no listed season. With no valid capture, always.
        Otherwise only while a window season's call is ``waiting`` or ``unavailable``: when the
        newest capture is ``CALL_WAIT`` days old or more, or, for a ``waiting`` call, when the
        capture was fetched on or before the season's due date and that date has passed.
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
                    f"no call for the season {day}"
                )
            if call.status == "waiting" and self.capture.day <= call.due < moment.date():
                return (
                    f"the newest calls list was fetched {self.capture.day.isoformat()}, on or before the "
                    f"season {day}'s due date {call.due.isoformat()}"
                )
        return None


# --------------------------------------------------------------------------- names


def season_folder(day: date) -> str:
    """A season's folder under ``raw/{T}/``, ``formatted/{T}/`` and ``reports/{T}/``: its period end."""
    return day.isoformat()


def filing_folder(form: str, day: date, accession: str) -> str:
    """``{FORM}_{DATE}_{ACCESSION}``: a filing's folder in its season's folder."""
    return f"{FORM_TOKENS[form]}_{day.isoformat()}_{accession}"


def doc_id(folder: str, name: str) -> str:
    """An EDGAR document's ``DOC_ID``: its folder, ``_`` and its file name without the extension."""
    return f"{folder}_{Path(name).stem}"


def call_doc_id(season: date, call_id: int) -> str:
    """A call's ``DOC_ID``: ``call_{PERIOD}_{ID}``."""
    return f"call_{season.isoformat()}_{call_id}"


def calls_name(moment: datetime, page: int) -> str:
    """Page ``page`` of the calls capture ``fetch`` read at ``moment``: ``calls_{token}_{PAGE}.json``."""
    if isinstance(page, bool) or not isinstance(page, int) or not 1 <= page <= MAX_PAGES:
        raise ValueError(f"a calls page is a number from 1 to {MAX_PAGES}")
    return stamped(CALLS_PREFIX.rstrip("_"), moment, f"_{page}.json")


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
    whose name ends in ``.txt`` (any case), whose lines wrap where the page ran out. HTML, iXBRL
    and XML documents and a call's text break at their blocks."""
    return document.kind != "call" and document.path.name.lower().endswith(".txt")


def _token_instant(path: Path) -> datetime | None:
    match = _STAMPED.fullmatch(path.name)
    return None if match is None else parse_timestamp_token(match["token"])


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
    except NotADirectoryError:  # a file where a folder belongs: that file is listed
        invalid.append((_blocking_file(path), NOT_A_FOLDER))
        return False
    if not stat.S_ISREG(info.st_mode):
        invalid.append((path, NOT_REGULAR))
        return False
    if info.st_size > limit:
        invalid.append((path, f"larger than {limit} bytes"))
        return False
    return True


def _blocking_file(path: Path) -> Path:
    """The nearest ancestor of ``path`` that is there and is no folder."""
    for parent in path.parents:
        try:
            if not stat.S_ISDIR(parent.lstat().st_mode):
                return parent
        except (FileNotFoundError, NotADirectoryError):
            continue
    return path.parent


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


# --------------------------------------------------------------------------- the top of raw/{T}/


@dataclass
class _Top:
    """What the top of ``raw/{T}/`` holds, sorted by kind."""

    submissions: dict[datetime, Path] = field(default_factory=dict)
    companyfacts: dict[datetime, Path] = field(default_factory=dict)
    captures: dict[datetime, dict[int, Path]] = field(default_factory=dict)
    seasons: dict[date, Path] = field(default_factory=dict)
    former: list[Path] = field(default_factory=list)


def _entries(directory: Path) -> Iterator[Path]:
    """The entries of ``directory`` but dotfiles and ``.rejected`` names, by name."""
    if not directory.is_dir():
        return
    for path in sorted(directory.iterdir()):
        if not path.name.startswith(".") and not path.name.endswith(REJECTED_SUFFIX):
            yield path


def _is_folder(path: Path) -> bool:
    return stat.S_ISDIR(path.lstat().st_mode)


def _top(raw: Path, now: datetime, invalid: list[tuple[Path, str]]) -> _Top:
    found = _Top()
    for path in _entries(raw):
        name = path.name
        if name in FORMER_LAYOUT and _is_folder(path):
            found.former.append(path)
            continue
        stamped_name = _STAMPED.fullmatch(name)
        calls = _CALLS_NAME.fullmatch(name)
        token = (
            stamped_name["token"]
            if stamped_name is not None
            else calls["token"]
            if calls is not None
            else None
        )
        if token is not None:
            if not stat.S_ISREG(path.lstat().st_mode):
                invalid.append((path, NOT_REGULAR))
                continue
            instant = parse_timestamp_token(token)
            if instant is None:
                invalid.append((path, NOT_RAW.format(where="")))
            elif instant > now:
                continue  # named after the clock: not read yet
            elif calls is not None:
                found.captures.setdefault(instant, {})[int(calls["page"])] = path
            elif stamped_name is not None and stamped_name["prefix"] == "submissions":
                found.submissions[instant] = path
            else:
                found.companyfacts[instant] = path
            continue
        if _SEASON_NAME.fullmatch(name):
            try:
                day = date.fromisoformat(name)
            except ValueError:
                invalid.append((path, NOT_RAW.format(where="")))
                continue
            if not _is_folder(path):
                invalid.append((path, NOT_A_FOLDER))
                continue
            found.seasons[day] = path
            continue
        invalid.append((path, NOT_RAW.format(where="")))
    return found


# --------------------------------------------------------------------------- calls


class _PageError(ValueError):
    """A problem of one page file of a capture."""

    def __init__(self, path: Path, message: str) -> None:
        super().__init__(message)
        self.path = path


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


def _newest_capture(
    ticker: str, captures: dict[datetime, dict[int, Path]], invalid: list[tuple[Path, str]]
) -> tuple[Capture | None, str | None]:
    """The newest capture, validated, or why there is none."""
    if not captures:
        return None, NO_CAPTURE
    fetched_at = max(captures)
    pages = captures[fetched_at]
    numbers = sorted(pages)
    ordered = [pages[number] for number in numbers]
    gaps = [number for number in range(1, numbers[-1] + 1) if number not in pages]
    if gaps:
        invalid.append((ordered[0], PAGE_MISSING.format(page=gaps[0])))
        return None, INVALID_CAPTURE
    try:
        calls = read_capture(ticker, ordered)
    except _PageError as error:
        invalid.append((error.path, str(error)))
        return None, INVALID_CAPTURE
    except ValueError as error:  # the pages together: their count, totals, symbols or issuers
        invalid.append((ordered[0], str(error)))
        return None, INVALID_CAPTURE
    return Capture(fetched_at, tuple(ordered), calls), None


def _call_document(season: date, event: CallEvent, path: Path, title: str) -> Document:
    return Document(
        doc_id=call_doc_id(season, event.id),
        kind="call",
        season=season,
        path=path,
        label=f"earnings call {event.day}: {title}",
        title=title,
        call=event,
    )


@dataclass
class _Transcripts:
    """Each call's newest transcript copy found in season folders, by call id, with the folder's
    season; and every copy, for ``fetch``."""

    newest: dict[int, tuple[datetime | None, Path, date]] = field(default_factory=dict)

    def add(self, call_id: int, instant: datetime | None, path: Path, season: date) -> None:
        held = self.newest.get(call_id)
        if held is None or (instant is not None and (held[0] is None or instant > held[0])):
            self.newest[call_id] = (instant, path, season)


def _call_state(
    season: Season,
    placed: tuple[CallEvent, ...],
    capture: Capture | None,
    capture_problem: str | None,
    transcripts: Mapping[int, tuple[Path, Transcript]],
    files: Mapping[int, Path],
    folder: Path,
    invalid: frozenset[Path],
) -> CallState:
    """The season's earnings call (module docstring); ``placed`` are the calls of the newest
    capture Rule B places in it, oldest first."""
    due = due_date(season)
    if capture is None:
        return CallState("missing", (), (), (), due, None, capture_problem)
    if not placed:
        verdict = due + timedelta(days=CALL_WAIT)
        if capture.day >= verdict:
            return CallState("unavailable", (), (), (), due, capture.day, None)
        reason = NOT_LISTED_YET.format(as_of=capture.day.isoformat(), verdict=verdict.isoformat())
        return CallState("waiting", (), (), (), due, capture.day, reason)
    documents: list[Document] = []
    read: list[Transcript] = []
    missing: str | None = None
    for event in placed:
        held = transcripts.get(event.id)
        if held is not None:
            path, transcript = held
            documents.append(_call_document(season.period, event, path, transcript.title))
            read.append(transcript)
            continue
        path = files.get(event.id, folder / transcript_name(event.id))
        message = TRANSCRIPT_INVALID if path in invalid else TRANSCRIPT_MISSING
        missing = missing or message.format(id=event.id, day=event.day.isoformat(), path=path)
    status: CallStatus = "transcript" if missing is None else "missing"
    return CallState(status, placed, tuple(documents), tuple(read), due, capture.day, missing)


# --------------------------------------------------------------------------- EDGAR filings


def _where(place: Season | str) -> str:
    return f"in the season {place.period}" if isinstance(place, Season) else "pending"


def _filing_document(
    kind: DocumentKind,
    season: date,
    folder: str,
    path: Path,
    label: str,
    form: str,
    accession: str,
    filed: date,
) -> Document:
    return Document(doc_id(folder, path.name), kind, season, path, label, form, accession, filed)


def _eight_k(
    cik: str, season: date, item: Dated, folder: Path, invalid: list[tuple[Path, str]]
) -> FilingFiles:
    index_path = folder / f"{item.accession}{INDEX_SUFFIX}"
    what = f"8-K {item.accession} dated {item.dated}"
    needed = [
        Needed(f"filing index page of the {what}", index_path, _present(index_path, INDEX_LIMIT, invalid))
    ]
    primary = folder / item.document
    needed.append(
        Needed(f"primary document of the {what}", primary, _present(primary, DOCUMENT_LIMIT, invalid))
    )
    documents: list[Document] = []
    if needed[1].present:
        label = f"8-K dated {item.dated} (items {item.items or 'none'})"
        documents.append(
            _filing_document(
                "8-K", season, folder.name, primary, label, item.form, item.accession, item.filed
            )
        )
    exhibits: tuple[ExhibitRow, ...] = ()
    valid = False
    if needed[0].present:
        try:
            body, _ = decode_document(read_raw(index_path, INDEX_LIMIT))
            exhibits = parse_filing_index(body, cik, item.accession).exhibits
            valid = True
        except ValueError as error:
            invalid.append((index_path, str(error)))
            needed[0] = Needed(needed[0].what, index_path, False)  # its exhibits are unknown
    for row in exhibits:
        path = folder / row.document
        present = _present(path, DOCUMENT_LIMIT, invalid)
        needed.append(Needed(f"{row.exhibit} {row.document} of the {what}", path, present))
        if present:
            label = f"{row.exhibit} of the 8-K dated {item.dated} ({row.document})"
            documents.append(
                _filing_document(
                    "exhibit", season, folder.name, path, label, item.form, item.accession, item.filed
                )
            )
    return FilingFiles(item, folder, tuple(needed), valid, exhibits, tuple(documents))


def _single(season: date, item: Dated, folder: Path, invalid: list[tuple[Path, str]]) -> FilingFiles:
    """A filing of one primary document: a proxy statement, a schedule or a Form 4."""
    path = folder / item.document
    present = _present(path, DOCUMENT_LIMIT, invalid)
    if item.form == "4":
        form4 = None
        if present:
            try:
                form4 = parse_form4(read_raw(path, DOCUMENT_LIMIT))
            except ValueError as error:
                invalid.append((path, str(error)))
        what = f"XML of the Form 4 {item.accession} dated {item.dated}"
        return FilingFiles(item, folder, (Needed(what, path, form4 is not None),), True, (), (), form4)
    what = f"primary document of the {item.form} {item.accession} filed {item.filed}"
    needed = (Needed(what, path, present),)
    documents: tuple[Document, ...] = ()
    if present:
        label = f"{item.form} filed {item.filed} ({item.document})"
        documents = (
            _filing_document(
                _KINDS[item.form], season, folder.name, path, label, item.form, item.accession, item.filed
            ),
        )
    return FilingFiles(item, folder, needed, True, (), documents)


def _season_files(
    raw: Path,
    cik: str,
    season: Season,
    placed: tuple[CallEvent, ...],
    capture: Capture | None,
    capture_problem: str | None,
    transcripts: Mapping[int, tuple[Path, Transcript]],
    transcript_files: Mapping[int, Path],
    invalid: list[tuple[Path, str]],
) -> SeasonFiles:
    folder = raw / season_folder(season.period)
    own = season.filing
    own_folder = filing_folder(own.form, own.period, own.accession)
    filing_path = folder / own_folder / own.primary_document
    filing = None
    if _present(filing_path, DOCUMENT_LIMIT, invalid):
        label = f"{own.form} for the period ended {own.period}"
        filing = _filing_document(
            "filing", season.period, own_folder, filing_path, label, own.form, own.accession, own.filed
        )
    filings: list[FilingFiles] = []
    for item in season.fetched:
        item_folder = folder / filing_folder(item.form, item.dated, item.accession)
        if item.form == "8-K":
            filings.append(_eight_k(cik, season.period, item, item_folder, invalid))
        else:
            filings.append(_single(season.period, item, item_folder, invalid))
    paths = frozenset(path for path, _ in invalid)
    call = _call_state(season, placed, capture, capture_problem, transcripts, transcript_files, folder, paths)
    return SeasonFiles(season, folder, filing_path, filing, tuple(filings), call, paths)


def _scan_season(
    path: Path,
    day: date,
    now: datetime,
    accessions: Mapping[str, tuple[str, Season | str]],
    placement: Mapping[int, Season | str],
    found: _Transcripts,
    unlisted: list[Path],
    invalid: list[tuple[Path, str]],
) -> None:
    """Check the entries of the season folder ``path`` against the listing: each filing folder
    and transcript must be where Rule B places it (``accessions``: the folder name each listed
    accession has, and its place; ``placement``: each listed call's place)."""
    for entry in _entries(path):
        name = entry.name
        filing = _FILING_NAME.fullmatch(name)
        if filing is not None:
            if not _is_folder(entry):
                invalid.append((entry, NOT_A_FOLDER))
                continue
            listed = accessions.get(filing["accession"])
            if listed is None:
                unlisted.append(entry)
                continue
            expected, place = listed
            if not isinstance(place, Season) or place.period != day:
                invalid.append((entry, MOVED.format(where=_where(place))))
            elif name != expected:
                invalid.append((entry, MISNAMED.format(name=expected)))
            continue
        transcript = _TRANSCRIPT_NAME.fullmatch(name)
        if transcript is not None:
            token = transcript["token"]
            instant = None if token is None else parse_timestamp_token(token)
            if token is not None and instant is None:
                invalid.append((entry, NOT_RAW.format(where=f"{day}/")))
                continue
            if instant is not None and instant > now:
                continue  # named after the clock: not read yet
            if not stat.S_ISREG(entry.lstat().st_mode):
                invalid.append((entry, NOT_REGULAR))
                continue
            call_id = int(transcript["id"])
            placed = placement.get(call_id)
            if placed is None:
                unlisted.append(entry)
            elif not isinstance(placed, Season) or placed.period != day:
                invalid.append((entry, MOVED_CALL.format(where=_where(placed))))
            else:
                found.add(call_id, instant, entry, day)
            continue
        invalid.append((entry, NOT_RAW.format(where=f"{day}/")))


def _repeated_ids(seasons: tuple[SeasonFiles, ...]) -> Iterator[tuple[Path, str]]:
    """Every document whose ``DOC_ID`` an earlier document already has, letter case aside."""
    seen: set[str] = set()
    for files in seasons:
        for document in files.documents:
            folded = document.doc_id.casefold()
            if folded in seen:
                yield document.path, REPEATED_DOC_ID.format(doc_id=document.doc_id)
            seen.add(folded)


def _accessions(listing: Seasons) -> dict[str, tuple[str, Season | str]]:
    """Every listed accession whose documents ``fetch`` writes, with the folder name it gets and
    where Rule B places it."""
    found: dict[str, tuple[str, Season | str]] = {}
    for season in listing.seasons:
        own = season.filing
        found[own.accession] = (filing_folder(own.form, own.period, own.accession), season)
        for item in season.fetched:
            found[item.accession] = (filing_folder(item.form, item.dated, item.accession), season)
    for item in listing.pending:
        if item.fetched:
            found[item.accession] = (filing_folder(item.form, item.dated, item.accession), PENDING)
    return found


def season_documents(layout: DataLayout, ticker: str, now: datetime) -> RawState:
    """Read ``ticker``'s raw tree: the seasons its newest submissions file lists, each with its
    files and its call, the newest company facts and calls capture, and every invalid file
    with the reason (module docstring).

    Without a submissions file, or with one that does not parse or whose seasons
    ``filings.select_seasons`` refuses, no season is listed and ``reason`` says why; the
    company facts and the calls list are still validated.
    """
    now = to_eastern(now, "now")
    raw = layout.raw(ticker)
    invalid: list[tuple[Path, str]] = []
    top = _top(raw, now, invalid)
    submissions_path = top.submissions[max(top.submissions)] if top.submissions else None
    submissions: Submissions | None = None
    listing: Seasons | None = None
    reason: str | None = NO_SUBMISSIONS if submissions_path is None else None
    if submissions_path is not None:
        try:
            submissions = read_submissions(submissions_path)
        except ValueError as error:  # the file is not a submissions body EDGAR serves
            invalid.append((submissions_path, str(error)))
            reason = f"{submissions_path.name} {SUBMISSIONS_INVALID}"
    if submissions is not None:
        try:
            listing = select_seasons(submissions)
        except ValueError as error:  # no exact 10-K or 10-Q, two for one period, an undated release
            reason = str(error)
    facts_path = top.companyfacts[max(top.companyfacts)] if top.companyfacts else None
    facts: CompanyFacts | None = None
    facts_problem: str | None = NO_FACTS if facts_path is None else None
    if facts_path is not None:
        cik = None if submissions is None else submissions.cik
        try:
            facts = read_companyfacts(read_raw(facts_path, COMPANYFACTS_LIMIT), cik)
        except ValueError as error:
            invalid.append((facts_path, str(error)))
            facts_problem = INVALID_FACTS
    capture, capture_problem = _newest_capture(ticker, top.captures, invalid)
    seasons: tuple[SeasonFiles, ...] = ()
    pending_calls: list[CallEvent] = []
    unlisted: list[Path] = []
    transcript_files: dict[int, Path] = {}
    if listing is not None and submissions is not None:
        placement: dict[int, Season | str] = {}
        placed: dict[date, list[CallEvent]] = {}
        for event in reversed(capture.calls if capture is not None else ()):
            place = listing.place(event.day)
            if place is None:
                continue
            placement[event.id] = place
            if isinstance(place, Season):
                placed.setdefault(place.period, []).append(event)
            else:
                pending_calls.append(event)
        accessions = _accessions(listing)
        found = _Transcripts()
        oldest = listing.seasons[0].period
        for day, path in sorted(top.seasons.items()):
            if day < oldest:
                continue  # a season filings.recent no longer lists: left out
            if listing.get(day) is None:
                invalid.append((path, NOT_A_SEASON))
                continue
            _scan_season(path, day, now, accessions, placement, found, unlisted, invalid)
        transcripts: dict[int, tuple[Path, Transcript]] = {}
        events = {event.id: event for event in (capture.calls if capture is not None else ())}
        for call_id, (_, path, _day) in sorted(found.newest.items()):
            transcript_files[call_id] = path
            try:
                transcripts[call_id] = (path, parse_transcript(read_raw(path, BODY_LIMIT), events[call_id]))
            except ValueError as error:
                invalid.append((path, str(error)))
        seasons = tuple(
            _season_files(
                raw,
                submissions.cik,
                season,
                tuple(placed.get(season.period, ())),
                capture,
                capture_problem,
                transcripts,
                transcript_files,
                invalid,
            )
            for season in listing.seasons
        )
        invalid.extend(_repeated_ids(seasons))
    return RawState(
        ticker=ticker,
        submissions=submissions_path,
        cik=None if submissions is None else submissions.cik,
        entity_name=None if submissions is None else submissions.entity_name,
        reason=reason,
        listing=listing,
        seasons=seasons,
        companyfacts=facts_path,
        facts=facts,
        facts_problem=facts_problem,
        capture=capture,
        capture_problem=capture_problem,
        pending_calls=tuple(pending_calls),
        unlisted=tuple(unlisted),
        former_layout=tuple(top.former),
        transcript_files=transcript_files,
        invalid_files=_first_per_path(invalid),
    )


def _first_per_path(invalid: list[tuple[Path, str]]) -> tuple[tuple[Path, str], ...]:
    """Each invalid path once, with the first reason found for it."""
    found: dict[Path, str] = {}
    for path, reason in invalid:
        found.setdefault(path, reason)
    return tuple(found.items())


# --------------------------------------------------------------------------- derived text


def edgar_text(data: bytes, name: str) -> str:
    """The derived text of a document EDGAR served: plain text for a ``.txt`` name, the XML
    derivation for an ``.xml`` name, else HTML.

    A text document's bytes are decoded as ``client.decode_document`` decodes them (strict
    UTF-8, else Latin-1); a Latin-1 document is read as windows-1252, as a browser shows it.
    An XML document is read by its own declaration.
    """
    lower = name.lower()
    if lower.endswith(".xml"):
        return xml_text(data)
    body, encoding = decode_document(data)
    text = windows_1252(body) if encoding == "latin-1" else body
    if lower.endswith(".txt"):
        return plain_text(text)
    return html_text(text)


def derive_call(document: Document) -> CallText:
    """A call's derived text and its turns, from its transcript in ``raw/``
    (``earningscalls.call_text``)."""
    if document.call is None:
        raise ValueError(f"{document.doc_id}: not a call")
    return call_text(parse_transcript(read_raw(document.path, BODY_LIMIT), document.call))


def derive_text(document: Document) -> str:
    """The derived text of an EDGAR document, from its raw bytes, or of a call, from its transcript."""
    if document.kind == "call":
        return derive_call(document).text
    return edgar_text(read_raw(document.path, DOCUMENT_LIMIT), document.path.name)
