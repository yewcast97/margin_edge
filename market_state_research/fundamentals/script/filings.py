"""EDGAR's ticker map, submissions JSON and filing index pages, read strictly, and the seasons.

Pure: the caller fetches the bodies (``client``) and keeps them in ``raw/`` (``workflow``);
this module reads them. ``company_tickers.json`` maps a ticker to its CIK, matched without
regard to case (``BRK.B`` and EDGAR's ``BRK-B`` stay different symbols). Of a company's
submissions JSON only ``filings.recent`` is read, the columns EDGAR publishes for at
least its latest year or 1,000 filings; the older pages listed under ``filings.files``
are not read, so a window that starts before the oldest recent filing is reported
``truncated``. Both bodies are checked as a strict subset of EDGAR's layout: every value
this module reads must have its documented type and grammar, while keys it does not read
are ignored (in ``company_tickers.json``, whose entries have exactly three keys, an
unknown key is refused). Repeated JSON keys, ``NaN`` and ``Infinity`` are refused, since
EDGAR never writes them and either would make a body mean two things. Every problem is
one ``ValueError`` line that names the field, row or accession; none echoes a value read
from a body, so nothing captured or private reaches output. The one exception is
``NoPeriodicFilings``, which lists the form types seen (EDGAR's own labels, cut to
``FORMS_SEEN_LIMIT`` characters and escaped onto one line) so an unsupported filer is
recognisable.

Seasons. Every exact ``10-K`` and ``10-Q`` of ``filings.recent`` is one season, named by its
``period`` (EDGAR's ``reportDate``): the end of the fiscal year or quarter it reports.
Amendments and transition reports (``10-K/A``, ``10-KT``, ``10-Q/A``, ``10-QT``,
``NT 10-Q``...) are not seasons. Two filings that report one period are refused rather than
one chosen, wherever they are listed. A ``Window`` selects the seasons whose end falls
between its two dates, both included.

Filings of a season. Every other row of a form the domain reads (``FETCHED_FORMS``, whose
documents ``fetch`` writes, and ``LISTED_FORMS``, which the measures list and nothing
fetches) is dated by its own date: an ``8-K`` and a Form ``4`` by their ``reportDate`` (the
event or the earliest transaction), which they must have and which may not be after their
filing date; every other form by its filing date (a proxy statement's ``reportDate`` is its
meeting's date, after its filing). Rule B places a filing dated D after the latest listed
season end P before D: when a later season is listed, the filing belongs to P; when P is the
newest listed season, it belongs to P only when D is not after the filing date of P's own
10-K or 10-Q, and is otherwise *pending*. Once EDGAR lists a later season, the same rule
places it again: it joins the latest season ending before its date, which is the formerly
newest season itself when the later season ends on or after that date, unless that is the
new newest season and the filing is dated after its filing, when it stays pending.
``Seasons.pending_in`` lists every pending filing for a window that ends on or after the
newest listed season end, and none for a window that ends before it. A filing dated on or
before the oldest listed season end is dropped, its season not being listed. An ``8-K`` with
Item 2.02 (results of operations: the earnings release) without a ``reportDate``, or with one
after its filing date, makes the ticker unsupported; any other row without the date or the
document it needs is *skipped* and listed with the reason. ``Seasons.place`` applies Rule B
to any other dated item, an earnings call dated by its New York date included.

Filing index pages. ``parse_filing_index`` reads an 8-K's filing index page
(``{accession}-index.htm``), the one EDGAR page that names each document's exhibit type,
with ``html.parser``, in the layout verified on Intel's 8-K 0000050863-26-000155: one
``<table class="tableFile" summary="Document Format Files">`` whose first row holds the
header cells Seq, Description, Document, Type and Size, then the cover row (its document
linked through EDGAR's ``/ix?doc=`` viewer, followed by an "iXBRL" label), one row per
exhibit and graphic, and the "Complete submission text file" row; a second ``tableFile``
table, ``summary="Data Files"``, lists the XBRL files and is never read. Rows whose Type
starts with ``EX-99`` are the exhibits; one whose document is a ``.pdf`` is EDGAR's
unofficial copy of an exhibit, whose official ``.htm`` or ``.txt`` is listed too, and is
skipped. The layout is a provider format: a change to it fails loudly, naming the
accession, the row position and the rule, never a cell's text.

Rules beyond EDGAR's column types, chosen as the conservative reading: an accession
number may appear only once among the recent rows, a 10-K or 10-Q may not report a
period after its filing date, ``items`` is printable ASCII of at most ``MAX_ITEMS``
characters on every row, ``acceptanceDateTime`` is empty or a UTC time written
``YYYY-MM-DDTHH:MM:SS.fffZ``, and a ticker matching two entries with different CIKs is
refused rather than resolved. A fetched form's primary document is a plain file name or,
for a form EDGAR renders from XML, ``xsl...`` and ``/`` before it (``rendered_document``
gives the raw file's name, which ``fetch`` requests). On an index page, the ``Document
Format Files`` table must end with its ``</table>`` (a page cut short is refused, not read
for fewer exhibits), an exhibit's Seq is a whole number from 1 to 999999999 written in ASCII
digits without a leading zero, its Type is ``EX-99`` alone or ``EX-99.`` followed by 1 to 16
letters, digits or dots (``EXHIBIT_PATTERN``; any other Type that starts with ``EX-99``, such
as ``EX-99-1``, is refused), and neither its Seq nor its document repeats another exhibit's.
``CIK_PATTERN``, ``ACCESSION_PATTERN`` and ``EXHIBIT_PATTERN`` are unanchored texts for
composing larger patterns: match them whole (``re.fullmatch``, or ``^...$`` where a
pattern is searched, as pydantic's ``pattern=`` does).
"""

import json
import re
from bisect import bisect_left
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from html.parser import HTMLParser
from itertools import pairwise
from typing import Final, Literal

from market_state_research.common.text import printable
from market_state_research.common.times import to_eastern

Form = Literal["10-K", "10-Q"]
Pending = Literal["pending"]

# Explicit ASCII classes: \d would also match other Unicode digits, which int() accepts.
CIK_PATTERN = r"[0-9]{10}"
ACCESSION_PATTERN = r"[0-9]{10}-[0-9]{2}-[0-9]{6}"
# A file name in the filing's archive folder, never a path; ".." is refused separately.
PRIMARY_DOCUMENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,199}", re.ASCII)
TICKERS_FILE = "company_tickers.json"
TICKER_KEYS = frozenset({"cik_str", "ticker", "title"})
RECENT_COLUMNS = (
    "accessionNumber",
    "filingDate",
    "reportDate",
    "acceptanceDateTime",
    "form",
    "primaryDocument",
    "items",
)
MAX_ITEMS: Final = 200
FORMS_SEEN_LIMIT = 200
# The item an 8-K names when it furnishes results of operations: the earnings release.
ITEM_RESULTS: Final = "2.02"
# The forms of a season whose documents fetch writes: every 8-K, the proxy statement, the
# amendments of the beneficial owners' schedules and the insiders' Form 4.
FETCHED_FORMS: Final = (
    "8-K",
    "DEF 14A",
    "SC 13D/A",
    "SC 13G/A",
    "SCHEDULE 13D/A",
    "SCHEDULE 13G/A",
    "4",
)
# The forms of a season the measures list and nothing fetches.
NOTICES: Final = ("NT 10-K", "NT 10-Q")
REGISTRATIONS: Final = ("S-3", "S-3ASR", "424B2", "424B3", "424B4", "424B5", "424B7")
AMENDMENTS: Final = ("8-K/A", "4/A", "10-K/A", "10-Q/A")
LISTED_FORMS: Final = (*NOTICES, *REGISTRATIONS, *AMENDMENTS)
HOLDER_FORMS: Final = ("SC 13D/A", "SC 13G/A", "SCHEDULE 13D/A", "SCHEDULE 13G/A")
# The forms dated by their reportDate; every other one by its filing date.
DATED_BY_REPORT: Final = ("8-K", "4")
# A folder's form part: the form without spaces or slashes.
FORM_TOKENS: Final = {
    "10-K": "10-K",
    "10-Q": "10-Q",
    "8-K": "8-K",
    "DEF 14A": "DEF14A",
    "SC 13D/A": "SC13DA",
    "SC 13G/A": "SC13GA",
    "SCHEDULE 13D/A": "SCHEDULE13DA",
    "SCHEDULE 13G/A": "SCHEDULE13GA",
    "4": "4",
}
# The filing index page's table of documents, its header and the exhibits read from it.
INDEX_TABLE: Final = "Document Format Files"
INDEX_COLUMNS: Final = ("Seq", "Description", "Document", "Type", "Size")
# A row whose Type starts with it is an exhibit, and its Type must then match EXHIBIT_PATTERN.
EXHIBIT_PREFIX: Final = "EX-99"
# An exhibit's Type: EX-99 alone (a valid EDGAR exhibit type) or with a suffix (EX-99.1);
# unanchored, like CIK_PATTERN.
EXHIBIT_PATTERN: Final = r"EX-99(?:\.[0-9A-Za-z.]{1,16})?"
MAX_DESCRIPTION: Final = 200
# What Rule B gives an item dated after the newest period's 10-K or 10-Q was filed.
PENDING: Final[Pending] = "pending"

_FORMS: dict[str, Form] = {"10-K": "10-K", "10-Q": "10-Q"}
_CIK = re.compile(CIK_PATTERN, re.ASCII)
_ACCESSION = re.compile(ACCESSION_PATTERN, re.ASCII)
_ISO_DAY = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", re.ASCII)
_ACCEPTED = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{3}Z", re.ASCII)
# A document EDGAR renders from XML: its stylesheet's folder, then the raw file's name.
_RENDERED = re.compile(r"xsl[A-Za-z0-9_]{1,40}/(?P<name>[A-Za-z0-9][A-Za-z0-9._-]{0,199})", re.ASCII)
# The submissions JSON writes the CIK without its leading zeros, as text.
_CIK_TEXT = re.compile(r"[0-9]{1,10}", re.ASCII)
_CIK_LIMIT = 10**10
# An exhibit row's Seq (a whole number from 1, in at most nine digits without a leading
# zero, so int() reads it at once and one number has one spelling) and its Type.
_SEQUENCE = re.compile(r"[1-9][0-9]{0,8}", re.ASCII)
_EXHIBIT_TYPE = re.compile(EXHIBIT_PATTERN, re.ASCII)
_VIEWER = "/ix?doc="
_TABLE_CLASS = "tableFile"
_CELL_TAGS = frozenset({"td", "th"})


class _NotJson(Exception):
    """A JSON body that the strict reader refuses although ``json`` would accept it."""


def _unique_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise _NotJson("an object repeats a key")
        value[key] = item
    return value


def _reject_constant(name: str) -> object:
    raise _NotJson(f"{name} is not JSON")


def _load_json(body: str) -> object:
    """Parse ``body``; integers become ``Decimal``, so no length limit of ``int`` applies."""
    try:
        return json.loads(
            body, object_pairs_hook=_unique_keys, parse_int=Decimal, parse_constant=_reject_constant
        )
    except json.JSONDecodeError as error:
        raise ValueError(f"invalid JSON: {error.msg} (line {error.lineno}, column {error.colno})") from None
    except _NotJson as error:
        raise ValueError(f"invalid JSON: {error}") from None
    except RecursionError:
        raise ValueError("invalid JSON: nested too deeply") from None


def is_primary_document(name: object) -> bool:
    """Whether ``name`` is a plain file name in a filing's archive folder (no path, no ``..``)."""
    return isinstance(name, str) and PRIMARY_DOCUMENT.fullmatch(name) is not None and ".." not in name


def rendered_document(primary: str) -> str | None:
    """The raw file a primary document names: itself when it is a plain file name, the file
    after the stylesheet's folder when EDGAR renders it from XML (``xslF345X06/form4.xml``
    gives ``form4.xml``, the XML in the filing's own folder); None for anything else."""
    if is_primary_document(primary):
        return primary
    match = _RENDERED.fullmatch(primary)
    if match is None or ".." in match["name"]:
        return None
    return match["name"]


# --------------------------------------------------------------------------- company_tickers.json


def _ticker_entry(position: int, entry: object) -> tuple[str, str]:
    """The (ticker, ten-digit CIK) of one entry; ``position`` counts entries from 0."""
    where = f"entry {position}"
    if not isinstance(entry, dict):
        raise ValueError(f"{where} must be an object")
    if set(entry) != TICKER_KEYS:
        raise ValueError(f"{where} must have exactly the keys cik_str, ticker and title")
    cik = entry["cik_str"]
    # parse_int gives Decimal for every JSON integer; a fraction or exponent stays float.
    if not isinstance(cik, Decimal) or not 0 < cik < _CIK_LIMIT:
        raise ValueError(f"{where}: cik_str must be an integer from 1 to 9999999999")
    if not isinstance(entry["ticker"], str):
        raise ValueError(f"{where}: ticker must be a string")
    if not isinstance(entry["title"], str):
        raise ValueError(f"{where}: title must be a string")
    return entry["ticker"], f"{int(cik):010d}"


def _same_ticker(listed: str, wanted: str) -> bool:
    # ASCII only: str.upper() folds some non-ASCII letters into ASCII ("ß" -> "SS").
    return listed.isascii() and wanted.isascii() and listed.upper() == wanted.upper()


def _lookup_cik(body: str, ticker: str) -> str | None:
    value = _load_json(body)
    if not isinstance(value, dict):
        raise ValueError("expected a JSON object of company entries")
    if not value:
        raise ValueError("lists no companies")
    found: set[str] = set()
    for position, entry in enumerate(value.values()):
        listed, cik = _ticker_entry(position, entry)
        if _same_ticker(listed, ticker):
            found.add(cik)
    if len(found) > 1:
        raise ValueError(f"the ticker matches entries with {len(found)} different CIKs")
    return found.pop() if found else None


def lookup_cik(body: str, ticker: str) -> str | None:
    """The ten-digit CIK that EDGAR's ``company_tickers.json`` lists for ``ticker``, or None.

    The whole file is checked before any answer: an object of entries, each exactly
    ``{"cik_str": integer, "ticker": string, "title": string}``. The ticker matches without
    regard to ASCII case; several entries for one ticker are fine when they agree on the
    CIK, and refused when they do not. Any problem raises one ``ValueError`` line,
    ``company_tickers.json: ...``, naming the entry by its position, never a value.
    """
    try:
        return _lookup_cik(body, ticker)
    except ValueError as error:
        raise ValueError(f"{TICKERS_FILE}: {error}") from None


# --------------------------------------------------------------------------- submissions JSON


@dataclass(frozen=True)
class RecentRow:
    """One row of ``filings.recent``: any form; ``period`` is None where EDGAR gives none.

    ``items`` is EDGAR's ``items`` cell as written (``"2.02,9.01"``, or empty for most forms);
    ``accepted`` the New York time EDGAR accepted the filing, None where it gives none.
    """

    form: str
    accession: str
    filed: date
    period: date | None
    primary_document: str
    items: str
    accepted: datetime | None = None


@dataclass(frozen=True)
class Submissions:
    """The checked subset of a submissions JSON; ``recent`` keeps EDGAR's row order."""

    cik: str
    entity_name: str
    recent: tuple[RecentRow, ...]


@dataclass(frozen=True)
class Filing:
    """The 10-K or 10-Q of one season; ``period`` is the fiscal year or quarter end it reports and
    ``accepted`` the New York time EDGAR accepted it (None where it gives none)."""

    form: Form
    accession: str
    filed: date
    period: date
    primary_document: str
    accepted: datetime | None = None


def _iso_date(value: str) -> date | None:
    # date.fromisoformat also accepts "20260627" and week dates; EDGAR writes YYYY-MM-DD only.
    if not _ISO_DAY.fullmatch(value):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _object(value: object, name: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be an object")
    return value


def _columns(recent: dict[str, object]) -> list[list[str]]:
    """The read columns of ``filings.recent`` (``RECENT_COLUMNS``): lists of strings of one length."""
    columns: list[list[str]] = []
    for name in RECENT_COLUMNS:
        if name not in recent:
            raise ValueError(f"filings.recent.{name} is missing")
        column = recent[name]
        if not isinstance(column, list):
            raise ValueError(f"filings.recent.{name} must be a list")
        for index, item in enumerate(column):
            if not isinstance(item, str):
                raise ValueError(f"filings.recent.{name}[{index}] must be a string")
        columns.append(column)
    lengths = {len(column) for column in columns}
    if len(lengths) > 1:
        counts = ", ".join(
            f"{name} {len(column)}" for name, column in zip(RECENT_COLUMNS, columns, strict=True)
        )
        raise ValueError(f"filings.recent columns must have one length; lengths: {counts}")
    return columns


def _accepted(index: int, value: str) -> datetime | None:
    """``acceptanceDateTime``: empty, or a UTC time ``YYYY-MM-DDTHH:MM:SS.fffZ``, in New York time."""
    if not value:
        return None
    if not _ACCEPTED.fullmatch(value):
        raise ValueError(
            f"filings.recent.acceptanceDateTime[{index}] must be empty or a UTC time YYYY-MM-DDTHH:MM:SS.fffZ"
        )
    try:
        instant = datetime.fromisoformat(value[:-1]).replace(tzinfo=UTC)
    except ValueError:
        raise ValueError(f"filings.recent.acceptanceDateTime[{index}] is not a time that exists") from None
    return to_eastern(instant, "acceptanceDateTime")


def _row(
    index: int,
    accession: str,
    filed_text: str,
    period_text: str,
    accepted_text: str,
    form: str,
    document: str,
    items: str,
) -> RecentRow:
    if not _ACCESSION.fullmatch(accession):
        raise ValueError(
            f"filings.recent.accessionNumber[{index}] must be an accession number (10-2-6 digits)"
        )
    filed = _iso_date(filed_text)
    if filed is None:
        raise ValueError(f"filings.recent.filingDate[{index}] must be a YYYY-MM-DD date")
    period = _iso_date(period_text) if period_text else None
    if period_text and period is None:
        raise ValueError(f"filings.recent.reportDate[{index}] must be a YYYY-MM-DD date or empty")
    if form in _FORMS:
        if period is None:
            raise ValueError(f"filings.recent.reportDate[{index}] is empty; a {form} must name its period")
        if period > filed:
            raise ValueError(f"filings.recent.reportDate[{index}] is after the {form}'s filing date")
        if not is_primary_document(document):
            raise ValueError(
                f"filings.recent.primaryDocument[{index}] must be a plain document file name for a {form}"
            )
    if not (items.isascii() and items.isprintable() and len(items) <= MAX_ITEMS):
        raise ValueError(
            f"filings.recent.items[{index}] must be printable ASCII of at most {MAX_ITEMS} characters"
        )
    return RecentRow(form, accession, filed, period, document, items, _accepted(index, accepted_text))


def _parse_submissions(body: str, cik: str) -> Submissions:
    value = _load_json(body)
    if not isinstance(value, dict):
        raise ValueError("expected a JSON object")
    if "cik" not in value:
        raise ValueError("cik is missing")
    listed = value["cik"]
    if isinstance(listed, Decimal):
        number = int(listed) if 0 <= listed < _CIK_LIMIT else None
    elif isinstance(listed, str) and _CIK_TEXT.fullmatch(listed):
        number = int(listed)
    else:
        raise ValueError("cik must be a string of digits or an integer")
    if number != int(cik):
        raise ValueError("cik is not the requested CIK")
    name = value.get("name")
    if not isinstance(name, str) or not name.strip() or not name.isprintable():
        raise ValueError("name must be a non-empty printable string")
    if "filings" not in value:
        raise ValueError("filings is missing")
    filings = _object(value["filings"], "filings")
    if "recent" not in filings:
        raise ValueError("filings.recent is missing")
    columns = _columns(_object(filings["recent"], "filings.recent"))
    rows: list[RecentRow] = []
    seen: dict[str, int] = {}
    for index, cells in enumerate(zip(*columns, strict=True)):
        row = _row(index, *cells)
        if row.accession in seen:
            raise ValueError(f"filings.recent.accessionNumber[{index}] repeats row {seen[row.accession]}")
        seen[row.accession] = index
        rows.append(row)
    return Submissions(cik=cik, entity_name=name, recent=tuple(rows))


def parse_submissions(body: str, cik: str) -> Submissions:
    """Read the strict subset of the submissions JSON of ``cik`` (ten digits).

    The body is an object with ``cik`` (EDGAR's unpadded text, or an integer, naming
    ``cik``), ``name`` (the entity name) and ``filings.recent`` whose
    ``accessionNumber``, ``filingDate``, ``reportDate``, ``acceptanceDateTime``, ``form``,
    ``primaryDocument`` and ``items`` are lists of strings of one length; other keys and
    columns are ignored. Accession numbers are 10-2-6 digits and unique, dates are
    ``YYYY-MM-DD`` (``reportDate`` may be empty), ``acceptanceDateTime`` is empty or a UTC
    time ``YYYY-MM-DDTHH:MM:SS.fffZ``, every exact ``10-K`` and ``10-Q`` names a period not
    after its filing date and a plain primary document file name, and every ``items``
    cell is printable ASCII of at most ``MAX_ITEMS`` characters. Any problem raises one
    ``ValueError`` line, ``submissions CIK{cik}: ...``, naming the field and row index,
    never a value.
    """
    if not isinstance(cik, str) or not _CIK.fullmatch(cik):
        raise ValueError("submissions: the CIK must be ten digits")
    try:
        return _parse_submissions(body, cik)
    except ValueError as error:
        raise ValueError(f"submissions CIK{cik}: {error}") from None


# --------------------------------------------------------------------------- seasons


@dataclass(frozen=True)
class Window:
    """The season ends a command covers: from ``start`` to ``end``, both included."""

    start: date
    end: date

    def __post_init__(self) -> None:
        if self.start > self.end:
            raise ValueError("the window's from date is after its to date")

    def admits(self, day: date) -> bool:
        return self.start <= day <= self.end


def default_window(today: date) -> Window:
    """The two years up to ``today``: from the same day two years earlier (29 February: the 28th)."""
    # Two years before 29 February is never a leap year.
    day = 28 if (today.month, today.day) == (2, 29) else today.day
    return Window(start=date(today.year - 2, today.month, day), end=today)


def release_items(items: str) -> tuple[str, ...]:
    """The items an ``items`` cell names: split on commas, each stripped, empty parts dropped."""
    return tuple(part for part in (piece.strip() for piece in items.split(",")) if part)


@dataclass(frozen=True)
class Dated:
    """One filing of a form the domain reads, other than a 10-K or 10-Q: its form, accession,
    filing date, the date Rule B places it by (``dated``), EDGAR's ``items`` cell, its primary
    document as EDGAR lists it and the New York time EDGAR accepted it."""

    form: str
    accession: str
    filed: date
    dated: date
    items: str
    primary_document: str
    accepted: datetime | None = None

    @property
    def fetched(self) -> bool:
        """Whether ``fetch`` writes its documents (``FETCHED_FORMS``)."""
        return self.form in FETCHED_FORMS

    @property
    def item_list(self) -> tuple[str, ...]:
        return release_items(self.items)

    @property
    def release(self) -> bool:
        """Whether it is an earnings release: an 8-K with Item 2.02."""
        return self.form == "8-K" and ITEM_RESULTS in self.item_list

    @property
    def document(self) -> str:
        """The raw file of its primary document (``rendered_document``); a fetched filing has one."""
        name = rendered_document(self.primary_document)
        if name is None:
            raise ValueError(f"{self.form} {self.accession}: no primary document")
        return name


@dataclass(frozen=True)
class Skipped:
    """A row of a form the domain reads that Rule B cannot place or ``fetch`` cannot read, and why."""

    form: str
    accession: str
    filed: date
    reason: str


@dataclass(frozen=True)
class Season:
    """One season: its 10-K or 10-Q and the filings Rule B places in it, ordered by (date, filing
    date, accession)."""

    filing: Filing
    filings: tuple[Dated, ...]

    @property
    def period(self) -> date:
        return self.filing.period

    def of_forms(self, forms: Iterable[str]) -> tuple[Dated, ...]:
        wanted = frozenset(forms)
        return tuple(item for item in self.filings if item.form in wanted)

    @property
    def eight_ks(self) -> tuple[Dated, ...]:
        return self.of_forms(("8-K",))

    @property
    def releases(self) -> tuple[Dated, ...]:
        """The 8-Ks with Item 2.02."""
        return tuple(item for item in self.eight_ks if item.release)

    @property
    def fetched(self) -> tuple[Dated, ...]:
        """The filings whose documents ``fetch`` writes."""
        return tuple(item for item in self.filings if item.fetched)


@dataclass(frozen=True)
class Seasons:
    """Every listed season, oldest first, the pending and skipped filings and the oldest recent
    filing date."""

    seasons: tuple[Season, ...]
    pending: tuple[Dated, ...]
    skipped: tuple[Skipped, ...]
    oldest_filed: date | None

    def within(self, window: Window) -> tuple[Season, ...]:
        """The seasons whose end the window admits, oldest first."""
        return tuple(season for season in self.seasons if window.admits(season.period))

    def pending_in(self, window: Window) -> tuple[Dated, ...]:
        """Every pending filing when the window ends on or after the newest listed season end.

        A pending filing is dated after the newest season's 10-K or 10-Q was filed. Once a
        later season is listed it joins the latest season ending before its date, possibly
        that newest season, so it concerns the newest season or a later one, which a window
        can admit only when it ends on or after the newest season end; a window that ends
        before it lists none.
        """
        if not self.seasons or window.end < self.seasons[-1].period:
            return ()
        return self.pending

    def truncated(self, window: Window) -> bool:
        """Whether the window starts before the oldest filing ``filings.recent`` lists."""
        return self.oldest_filed is None or window.start < self.oldest_filed

    def get(self, day: date) -> Season | None:
        """The season that ends on ``day``, or None."""
        return next((season for season in self.seasons if season.period == day), None)

    def index(self, day: date) -> int | None:
        """The position of the season that ends on ``day``, or None."""
        return next((position for position, season in enumerate(self.seasons) if season.period == day), None)

    def place(self, day: date) -> Season | Pending | None:
        """Rule B for an item dated ``day``: the season it belongs to, ``PENDING`` or None (dropped).

        The item belongs to the latest listed season ending before ``day``, unless that is the
        newest listed season and ``day`` is after the filing date of its 10-K or 10-Q
        (``PENDING``); an item dated on or before the oldest listed season end is dropped.
        """
        index = rule_b(tuple(season.filing for season in self.seasons), day)
        return self.seasons[index] if isinstance(index, int) else index

    def before(self, season: Season, count: int) -> tuple[Season, ...]:
        """Up to ``count`` listed seasons before ``season``, newest first."""
        position = self.index(season.period)
        if position is None:
            return ()
        return tuple(reversed(self.seasons[max(0, position - count) : position]))


def rule_b(filings: Sequence[Filing], day: date) -> int | Pending | None:
    """Rule B over ``filings``, one per listed season, oldest first, for an item dated ``day``.

    The index of the filing whose season the item belongs to: the latest season ending
    before ``day``; ``PENDING`` when that is the newest season and ``day`` is after its
    filing's date; None when no listed season ends before ``day`` (the item is dropped).
    """
    before = bisect_left([filing.period for filing in filings], day)  # listed season ends before day
    if before == 0:
        return None
    if before == len(filings) and day > filings[-1].filed:
        return PENDING
    return before - 1


class NoPeriodicFilings(ValueError):
    """The recent filings hold no exact 10-K or 10-Q, so the issuer has no season (a 20-F filer, say)."""


def _filing(row: RecentRow) -> Filing:
    form = _FORMS.get(row.form)
    # parse_submissions guarantees both for every exact 10-K and 10-Q; a Submissions built
    # by hand may not.
    if form is None or row.period is None:
        raise ValueError("a season's filing must be a 10-K or 10-Q row with a period")
    return Filing(form, row.accession, row.filed, row.period, row.primary_document, row.accepted)


def _forms_seen(forms: Iterable[str]) -> str:
    seen = ", ".join(sorted(set(forms)))[:FORMS_SEEN_LIMIT]
    return printable(seen) if seen else "none"


def _filing_order(filing: Filing) -> tuple[date, date, str]:
    return filing.period, filing.filed, filing.accession


def _dated_order(item: Dated) -> tuple[date, date, str]:
    return item.dated, item.filed, item.accession


def _dated(submissions: Submissions) -> tuple[list[Dated], list[Skipped]]:
    """Every row of a form the domain reads but a 10-K or 10-Q, dated for Rule B, in date order,
    and the rows skipped. An Item 2.02 8-K without its event date, or dated after its filing,
    raises ``ValueError``."""
    dated: list[Dated] = []
    skipped: list[Skipped] = []
    for index, row in enumerate(submissions.recent):
        if row.form not in FETCHED_FORMS and row.form not in LISTED_FORMS:
            continue
        if row.form in DATED_BY_REPORT:
            if row.period is None or row.period > row.filed:
                problem = "is empty" if row.period is None else f"is after the {row.form}'s filing date"
                if row.form == "8-K" and ITEM_RESULTS in release_items(row.items):
                    raise ValueError(
                        f"submissions CIK{submissions.cik}: filings.recent.reportDate[{index}] {problem}; "
                        f"an 8-K with Item {ITEM_RESULTS} must name its event date"
                    )
                skipped.append(Skipped(row.form, row.accession, row.filed, f"its reportDate {problem}"))
                continue
            day = row.period
        else:
            day = row.filed
        if row.form in FETCHED_FORMS and rendered_document(row.primary_document) is None:
            skipped.append(
                Skipped(
                    row.form, row.accession, row.filed, "its primaryDocument is no file fetch can request"
                )
            )
            continue
        dated.append(
            Dated(row.form, row.accession, row.filed, day, row.items, row.primary_document, row.accepted)
        )
    return sorted(dated, key=_dated_order), skipped


def select_seasons(submissions: Submissions) -> Seasons:
    """Every season of ``submissions``, oldest first, with its filings placed by Rule B.

    Every exact 10-K and 10-Q is one season; none raises ``NoPeriodicFilings`` listing the
    forms seen, and two for one period raise ``ValueError`` rather than choose one. Every row
    of ``FETCHED_FORMS`` and ``LISTED_FORMS`` is dated (module docstring) and placed by Rule B:
    in the latest listed season ending before its date, pending when that is the newest
    season and the date is after its 10-K's or 10-Q's filing date, dropped when no listed
    season ends before it. The result does not depend on the order of the rows.
    """
    recent = submissions.recent
    periodic = [row for row in recent if row.form in _FORMS]
    if not periodic:
        raise NoPeriodicFilings(
            f"no 10-K or 10-Q among the {len(recent)} recent filings; "
            f"forms seen: {_forms_seen(row.form for row in recent)}"
        )
    filings = sorted((_filing(row) for row in periodic), key=_filing_order)
    for earlier, later in pairwise(filings):
        if earlier.period == later.period:
            raise ValueError(
                f"submissions CIK{submissions.cik}: two filings report the period {later.period.isoformat()}"
            )
    dated, skipped = _dated(submissions)
    attached: list[list[Dated]] = [[] for _ in filings]
    pending: list[Dated] = []
    for item in dated:
        index = rule_b(filings, item.dated)
        if isinstance(index, int):
            attached[index].append(item)
        elif index is not None:  # pending; None: its season is not listed
            pending.append(item)
    return Seasons(
        seasons=tuple(
            Season(filing=filing, filings=tuple(items))
            for filing, items in zip(filings, attached, strict=True)
        ),
        pending=tuple(pending),
        skipped=tuple(skipped),
        oldest_filed=min(row.filed for row in recent),
    )


# --------------------------------------------------------------------------- filing index page


@dataclass(frozen=True)
class ExhibitRow:
    """One ``EX-99`` or ``EX-99.*`` row of a filing index page.

    ``description`` is the Description cell with its whitespace collapsed (it may be
    empty), ``document`` the plain file name the row links to and ``exhibit`` the Type
    cell (``EX-99.1``), as EDGAR writes them.
    """

    sequence: int
    description: str
    document: str
    exhibit: str


@dataclass(frozen=True)
class FilingIndex:
    """The exhibits a filing index page lists, in Seq order, EDGAR's ``.pdf`` copies excluded."""

    exhibits: tuple[ExhibitRow, ...]


@dataclass
class _Cell:
    parts: list[str] = field(default_factory=list)
    links: list[str | None] = field(default_factory=list)  # the href of each <a> in the cell

    @property
    def text(self) -> str:
        """The cell's text, character references decoded and whitespace runs collapsed."""
        return " ".join("".join(self.parts).split())


@dataclass
class _Table:
    summary: str | None
    rows: list[list[_Cell]] = field(default_factory=list)
    row: list[_Cell] | None = None  # the open row
    cell: _Cell | None = None  # the open cell
    nested: bool = False  # another table opened inside this one
    stray: bool = False  # a cell outside any row
    closed: bool = False  # its own </table> was read


class _IndexTables(HTMLParser):
    """Collects the rows and cells of every ``tableFile`` table of a page.

    End tags HTML lets a page omit are implied as a browser implies them: a new cell
    closes the open cell, and a new row or the table's end closes the open row. A
    table's own end tag, which HTML never lets a page omit, is recorded (``closed``).
    Text outside a cell is ignored.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[_Table] = []
        self._open: list[_Table | None] = []  # open tables, innermost last; None for any other table

    def _current(self) -> _Table | None:
        return self._open[-1] if self._open else None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        table = self._current()
        if tag == "table":
            if table is not None:
                table.nested = True
            classes = next((value for name, value in attrs if name == "class"), None) or ""
            if _TABLE_CLASS in classes.split():
                summary = next((value for name, value in attrs if name == "summary"), None)
                collected = _Table(summary=summary)
                self.tables.append(collected)
                self._open.append(collected)
            else:
                self._open.append(None)
            return
        if table is None:
            return
        if tag == "tr":
            table.cell = None
            table.row = []
            table.rows.append(table.row)
        elif tag in _CELL_TAGS:
            table.cell = None
            if table.row is None:
                table.stray = True
                return
            table.cell = _Cell()
            table.row.append(table.cell)
        elif table.cell is not None:
            if tag == "a":
                table.cell.links.append(next((value for name, value in attrs if name == "href"), None))
            elif tag == "br":
                table.cell.parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag == "table":
            closing = self._open.pop() if self._open else None
            if closing is not None:
                closing.closed = True
            return
        table = self._current()
        if table is None:
            return
        if tag == "tr":
            table.cell = None
            table.row = None
        elif tag in _CELL_TAGS:
            table.cell = None

    def handle_data(self, data: str) -> None:
        table = self._current()
        if table is not None and table.cell is not None:
            table.cell.parts.append(data)


def _exhibit(number: int, cells: list[_Cell], folder: str) -> ExhibitRow:
    """One ``EX-99`` or ``EX-99.*`` row, ``number`` counting the table's rows from 1 with the header row."""
    where = f"row {number}"
    sequence, description, document, exhibit = (cell.text for cell in cells[:4])
    if not _SEQUENCE.fullmatch(sequence):
        raise ValueError(f"{where}: Seq must be a whole number from 1 in ASCII digits")
    if len(description) > MAX_DESCRIPTION or not description.isprintable():
        raise ValueError(
            f"{where}: Description must be printable text of at most {MAX_DESCRIPTION} characters"
        )
    name = document.split(" ")[0]  # the cover's cell adds an "iXBRL" label after the name
    if not is_primary_document(name):
        raise ValueError(f"{where}: the document must be a plain file name")
    path = f"{folder}/{name}"
    links = cells[2].links
    if len(links) != 1 or links[0] not in (path, _VIEWER + path):
        raise ValueError(f"{where}: the Document cell must link only to its document in the filing's folder")
    if not _EXHIBIT_TYPE.fullmatch(exhibit):
        raise ValueError(
            f"{where}: Type must be EX-99, or EX-99. followed by 1 to 16 letters, digits or dots"
        )
    return ExhibitRow(sequence=int(sequence), description=description, document=name, exhibit=exhibit)


def _parse_filing_index(body: str, cik: str, accession: str) -> FilingIndex:
    reader = _IndexTables()
    reader.feed(body)
    reader.close()
    tables = [table for table in reader.tables if table.summary == INDEX_TABLE]
    if not tables:
        raise ValueError(f'no tableFile table with the summary "{INDEX_TABLE}"')
    if len(tables) > 1:
        raise ValueError(f'{len(tables)} tableFile tables have the summary "{INDEX_TABLE}"; expected one')
    table = tables[0]
    # HTML never lets </table> be omitted: a page without it was cut short and may lack exhibits.
    if not table.closed:
        raise ValueError(f"the {INDEX_TABLE} table is not closed")
    if table.nested:
        raise ValueError(f"the {INDEX_TABLE} table holds another table")
    if table.stray:
        raise ValueError(f"the {INDEX_TABLE} table has a cell outside a row")
    if not table.rows or tuple(cell.text for cell in table.rows[0]) != INDEX_COLUMNS:
        raise ValueError(f"the {INDEX_TABLE} table's first row is not {', '.join(INDEX_COLUMNS)}")
    folder = f"/Archives/edgar/data/{int(cik)}/{accession.replace('-', '')}"
    exhibits: list[ExhibitRow] = []
    sequences: dict[int, int] = {}
    documents: dict[str, int] = {}
    for number, cells in enumerate(table.rows[1:], start=2):
        if len(cells) != len(INDEX_COLUMNS):
            raise ValueError(f"row {number} has {len(cells)} cells; expected {len(INDEX_COLUMNS)}")
        if not cells[3].text.startswith(EXHIBIT_PREFIX):
            continue  # the cover, a graphic, the complete submission or another exhibit type
        row = _exhibit(number, cells, folder)
        if row.sequence in sequences:
            raise ValueError(f"row {number}: Seq repeats row {sequences[row.sequence]}")
        if row.document in documents:
            raise ValueError(f"row {number}: the document repeats row {documents[row.document]}")
        sequences[row.sequence] = documents[row.document] = number
        if not row.document.lower().endswith(".pdf"):  # EDGAR's unofficial copy of an exhibit
            exhibits.append(row)
    return FilingIndex(exhibits=tuple(sorted(exhibits, key=lambda row: row.sequence)))


def parse_filing_index(body: str, cik: str, accession: str) -> FilingIndex:
    """The ``EX-99`` and ``EX-99.*`` exhibits that the filing index page ``body`` of ``accession`` lists.

    The page must hold exactly one ``<table>`` whose ``class`` includes ``tableFile`` and
    whose ``summary`` is ``INDEX_TABLE``, closed by its own ``</table>`` and holding no
    other table; its first row's cell texts (character references decoded, whitespace
    collapsed) are exactly ``INDEX_COLUMNS`` and every other row has five cells. A row
    whose Type starts with ``EXHIBIT_PREFIX`` (``EX-99``, letter case counts) is an
    exhibit: its Type matches ``EXHIBIT_PATTERN`` whole (``EX-99`` alone, or ``EX-99.``
    and a suffix; ``EX-99-1`` or ``EX-99A`` is refused); its Seq is a whole number from 1
    to 999999999 in ASCII digits without a leading zero, unique among the exhibits; its
    document, the first word of the Document cell, is a plain file name (``is_primary_document``),
    unique among the exhibits, which the cell's only link names in the filing's folder,
    ``/Archives/edgar/data/{int(cik)}/{accession without hyphens}/{document}``, directly or
    through ``/ix?doc=``; its Description is printable text of at most
    ``MAX_DESCRIPTION`` characters and may be empty. A ``.pdf`` exhibit (any letter case)
    is EDGAR's unofficial copy and is checked, then skipped. Every other row and every
    other table (``Data Files``) is ignored. Any problem raises one ``ValueError`` line,
    ``filing index {accession}: ...``, naming the row by its position (the header row is
    row 1) and the rule, never a cell's text.
    """
    if not isinstance(cik, str) or not _CIK.fullmatch(cik):
        raise ValueError("filing index: the CIK must be ten digits")
    if not isinstance(accession, str) or not _ACCESSION.fullmatch(accession):
        raise ValueError("filing index: the accession number must be 10-2-6 digits")
    try:
        return _parse_filing_index(body, cik, accession)
    except ValueError as error:
        raise ValueError(f"filing index {accession}: {error}") from None
