"""The bot's readings of one season: their grammar and the rules ``check`` holds them to.

The bot reads a season's documents (their derived text, ``formatted/{T}/{PERIOD}/{DOC_ID}.md``)
and those of the seasons each item compares with (``measures.baseline_seasons``), and writes
``reports/{T}/{PERIOD}/readings.md``, one section per bot item of the catalogue
(``items.BOT_ITEMS``). ``parse_readings`` reads it line by line:

- G1: the first non-blank line is ``# {T} · {PERIOD} · readings``;
- G2: then one ``## {id} {title}`` heading per bot item, each once, in catalogue order;
- G3: a section's first three lines are ``baseline:``, ``old:`` and ``new:``, in order;
- G4: ``baseline:`` is ``none`` or the ``DOC_ID``s read as the baseline, joined by ``; ``;
- G5: ``old:`` is the baseline's value and ``new:`` the season's: a status (``items.STATUSES``
  but ``no source``; ``no baseline`` is an old value only), ``—`` (the old value of an item
  without a baseline) or a value of facts, ``none`` when the documents state nothing of the
  kind;
- G6: each value is 1 to ``MAX_VALUE`` printable characters on its line;
- G7: then zero or more quotes: ``> TEXT`` lines, whose texts are joined by one space, and then
  one attribution line, ``— {DOC_ID}``, or ``— {DOC_ID}, {Speaker} ({role})`` for a call's
  quote; blank lines may separate quotes.

Any other line is an error; trailing spaces, CRLF line ends and a leading byte order mark are
accepted. Every problem names its line (1 for the first).

``readings_problems`` then holds each reading to the rules (``Season`` gives what they need):

- R1: every ``DOC_ID`` named is a document in ``raw/`` whose text file equals its derivation;
- R2: the baseline names documents of the item's baseline seasons only, and at least one for
  an old value read from them (facts, ``none``, ``not disclosed`` or ``not computable``); it is
  ``none`` for an item without a baseline and for the old values ``no baseline``,
  ``not applicable`` and ``unavailable``; the old value is ``—`` exactly for an item without a
  baseline;
- R3: a quote comes from a document of the season or from one its baseline line names;
- R4: an item of ``high`` importance whose new value is facts other than ``none`` needs a
  quote from a document of the season itself;
- R5: ``no baseline`` only while no document of the item's baseline seasons is in ``raw/``
  (for a call item, no call of those seasons);
- R6: ``not applicable`` exactly for an annual item in a 10-Q season and a proxy item in a
  season without a proxy statement, as its new value and, when it has a baseline, its old one;
- R7: ``unavailable`` exactly for a call item while the season's call has no transcript, in
  the same places;
- R8: ``not disclosed`` and ``not computable`` only where the item allows them;
- R9: a quote is 20 to 800 characters once normalised, found verbatim in its document's
  derived text, spelt as it writes it, and whole sentences or lines at its first occurrence
  (``text.sentence_bounded`` in the document's mode); a call's quote names its turn's
  heading, ``{Speaker} ({role})``, exactly, and lies within that turn's words, any role's; a
  quote of another document names no speaker;
- R10: an old or new value carries no valuation, forecast or advice wording (``WORDING``;
  quotes are the issuer's words and never checked against it), and no quote is repeated in an
  item.
"""

import re
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Final

from .earningscalls import Turn
from .items import BOT_ITEMS, STATUSES, Item
from .text import QUOTE_MAX, QUOTE_MIN, locate, normalise, sentence_bounded

# Accounting's "fair value" and a proxy statement's "advisory vote" are facts, not advice.
WORDING = re.compile(
    r"\b(?:buy|sell|hold|overweight|underweight|undervalued|overvalued|price target|target price|"
    r"upside|downside|bullish|bearish|recommend\w*|advice|advis(?:e[ds]?|ing|able)|should (?:buy|sell)|"
    r"outperform|underperform)\b",
    re.IGNORECASE,
)
MAX_VALUE: Final = 600
DASH: Final = "— "
NONE: Final = "none"
NOTHING: Final = "—"
BOT_STATUSES: Final = tuple(status for status in STATUSES if status != "no source")
WITHOUT_BASELINE: Final = ("no baseline", "not applicable", "unavailable")

TITLE_LINE = "the first line must be '# {title}'"
HEADINGS = "the sections must be the bot's items, each once, in catalogue order: '## {id} {title}'"
MISSING_SECTION = "the section '## {heading}' is missing"
OUTSIDE_SECTION = "this line is outside the readings' sections"
FIRST_LINES = "a section starts with its 'baseline:', 'old:' and 'new:' lines, in that order"
UNEXPECTED_LINE = (
    "a section holds its three lines, then '> TEXT' lines each quote ended by its '— DOC_ID' line"
)
EMPTY_QUOTE_LINE = "an empty '>' line; a quote's lines each hold text"
NO_ATTRIBUTION = "a quote's '>' lines must be followed by its attribution line '— DOC_ID'"
ATTRIBUTION_TEXT = "an attribution line is '— DOC_ID', or '— DOC_ID, Speaker (role)' for a call's quote"
ATTRIBUTION_WITHOUT_QUOTE = "an attribution line must follow a quote's '>' lines"
BASELINE_TEXT = "the baseline must be 'none' or DOC_IDs joined by '; '"
VALUE_TEXT = f"the {{side}} value must be 1 to {MAX_VALUE} printable characters"
WORDING_FOUND = (
    "an old or new value states facts only, without valuation, forecast or advice wording; found: {terms}"
)
NOTHING_NEEDED = "the old value of an item without a baseline is '—'"
NOTHING_FALSE = "'—' is only the old value of an item without a baseline"
NO_BASELINE_NEW = "'no baseline' is an old value only; the new value is the season's"
UNKNOWN_DOCUMENT = "{doc_id} is no document in raw/ (a DOC_ID of a text file in formatted/)"
TEXT_STALE = "the text file of {doc_id} is missing or differs from its derivation; run derive"
NOT_BASELINE = "{doc_id} is no document of this item's baseline ({kind}: {seasons})"
BASELINE_NEEDED = "an old value names the baseline documents it was read from ({kind})"
BASELINE_NONE = "the baseline must be 'none' for {why}"
NO_BASELINE_FALSE = "'no baseline' while the baseline is in raw/: {documents}"
NOT_APPLICABLE_NEEDED = "this item is 'not applicable' in this season ({why})"
NOT_APPLICABLE_FALSE = (
    "'not applicable' is only for an annual item in a 10-Q season or a proxy item without a proxy statement"
)
UNAVAILABLE_NEEDED = "a call item is 'unavailable' while the season's call has no transcript ({status})"
UNAVAILABLE_FALSE = "'unavailable' is only for a call item while the season's call has no transcript"
STATUS_NOT_ALLOWED = "this item does not allow '{status}'"
QUOTE_SOURCE = "a quote comes from a document of the season or one the baseline line names"
HIGH_NEEDS_QUOTE = (
    "an item of high importance whose new value is stated, not 'none' or a status, needs a quote from a "
    "document of the season itself"
)
QUOTE_LENGTH = (
    f"the quote is {{length}} characters long after normalisation; it must be {QUOTE_MIN} to {QUOTE_MAX}"
)
QUOTE_NOT_FOUND = "quote not found in the document's derived text"
QUOTE_SPELLING = (
    "the quote is not spelt as the derived text writes it: copy its characters exactly; only the "
    "whitespace between words may differ"
)
NOT_WHOLE = (
    "a quote must be whole sentences, or whole lines of an HTML, XML or call document: it must start, never "
    "in lowercase even after a list glyph, at such a line start or after a sentence end or a colon that ends "
    "a line, and end at such a line end or with a sentence end and whitespace, before text that does not "
    "start in lowercase"
)
CALL_SPEAKER = "a call's quote names its turn: '— DOC_ID, Speaker (role)', as the turn's heading writes it"
ACROSS_TURNS = "a call's quote lies within the words of one turn, below its heading"
OTHER_TURN = "the quote lies in the turn '{heading}', not the one its attribution names"
NO_SPEAKER = "only a call's quote names a speaker"
REPEATED_QUOTE = "this quote is already given in this item"


@dataclass(frozen=True)
class Problem:
    """One broken rule of a readings file: its line (from 1) and what is wrong."""

    line: int
    message: str


@dataclass(frozen=True)
class Quote:
    """One quote: the line of its first ``>`` line, its text, the ``DOC_ID`` and speaker heading its
    attribution names, and the attribution's line."""

    line: int
    text: str
    doc_id: str
    speaker: str | None
    attribution_line: int


@dataclass(frozen=True)
class ItemReading:
    """One bot item's section: its baseline (``DOC_ID``s, empty for ``none``), old and new values
    and quotes, with each line's number."""

    item: Item
    line: int
    baseline: tuple[str, ...] | None = None
    baseline_line: int = 0
    old: str | None = None
    old_line: int = 0
    new: str | None = None
    new_line: int = 0
    quotes: tuple[Quote, ...] = ()


@dataclass(frozen=True)
class Readings:
    """A parsed readings file: the season it names and its sections in catalogue order."""

    title_line: int
    items: tuple[ItemReading, ...]

    def get(self, identifier: str) -> ItemReading | None:
        return next((reading for reading in self.items if reading.item.id == identifier), None)


def title(ticker: str, season: date) -> str:
    return f"{ticker} · {season.isoformat()} · readings"


@dataclass
class _Section:
    item: Item
    line: int
    baseline: tuple[str, ...] | None = None
    baseline_line: int = 0
    old: str | None = None
    old_line: int = 0
    new: str | None = None
    new_line: int = 0
    quotes: list[Quote] = field(default_factory=list)
    stage: int = 0  # the first lines read: 0 none, 1 baseline, 2 old, 3 new


class _Parser:
    """The line-by-line reading of one readings file; ``problems`` collects every broken rule."""

    def __init__(self, heading: str) -> None:
        self.heading = heading
        self.problems: list[Problem] = []
        self.sections: list[_Section] = []
        self.section: _Section | None = None
        self.lost = False  # after a refused heading, until the next one
        self.title: int | None = None
        self.block: list[str] | None = None
        self.block_line = 0

    def add(self, line: int, message: str) -> None:
        self.problems.append(Problem(line, message))

    def close(self, line: int) -> None:
        """End a quote whose attribution never came."""
        if self.block is not None:
            self.add(self.block_line, NO_ATTRIBUTION)
        self.block = None

    def start(self, number: int, text: str) -> None:
        self.close(number)
        seen = [section.item for section in self.sections]
        item = next((item for item in BOT_ITEMS if item.heading == text), None)
        self.lost = item is None or item in seen
        if item is None or item in seen:
            self.add(number, HEADINGS)
            self.section = None
            return
        if any(BOT_ITEMS.index(other) > BOT_ITEMS.index(item) for other in seen):
            self.add(number, HEADINGS)
        self.section = _Section(item, number)
        self.sections.append(self.section)

    def first_line(self, section: _Section, number: int, line: str) -> bool:
        """Read ``line`` as the section's next first line; False when the line is to be read as a
        quote's (a section that skipped its first lines is reported once)."""
        labels = ("baseline:", "old:", "new:")
        label = labels[section.stage]
        if not line.startswith(label):
            self.add(number, FIRST_LINES)
            section.stage = 3
            return not line.startswith((">", DASH.strip()))
        value = line[len(label) :].strip()
        if section.stage == 0:
            section.baseline_line = number
            if value == NONE:
                section.baseline = ()
            else:
                parts = value.split("; ")
                if not value or any(not part or part != part.strip() or " " in part for part in parts):
                    self.add(number, BASELINE_TEXT)
                section.baseline = tuple(part for part in parts if part)
        else:
            side = "old" if section.stage == 1 else "new"
            if side == "old":
                section.old, section.old_line = value, number
            else:
                section.new, section.new_line = value, number
            if not 0 < len(value) <= MAX_VALUE or not value.isprintable():
                self.add(number, VALUE_TEXT.format(side=side))
        section.stage += 1
        return True

    def attribution(self, section: _Section, number: int, line: str) -> None:
        if self.block is None:
            self.add(number, ATTRIBUTION_WITHOUT_QUOTE)
            return
        if not line.startswith(DASH):
            self.add(number, ATTRIBUTION_TEXT)
            self.block = None
            return
        named = line[len(DASH) :].strip()
        doc_id, _, speaker = named.partition(", ")
        text = " ".join(" ".join(self.block).split())
        section.quotes.append(Quote(self.block_line, text, doc_id, speaker or None, number))
        self.block = None

    def read(self, text: str) -> Readings:
        lines = text.splitlines()
        for number, raw in enumerate(lines, start=1):
            line = raw.rstrip()
            if self.title is None:
                if not line:
                    continue
                self.title = number
                if line == f"# {self.heading}":
                    continue
                self.add(number, TITLE_LINE.format(title=self.heading))
                if line.startswith("# "):
                    continue
            if line.startswith("## "):
                self.start(number, line[3:].strip())
                continue
            if not line:
                continue
            section = self.section
            if section is None:
                if not self.lost:
                    self.add(number, OUTSIDE_SECTION)
                continue
            if section.stage < 3 and self.first_line(section, number, line):
                continue
            if line.startswith(">"):
                quoted = line[1:].strip()
                if not quoted:
                    self.add(number, EMPTY_QUOTE_LINE)
                    continue
                if self.block is None:
                    self.block, self.block_line = [], number
                self.block.append(quoted)
            elif line.startswith(DASH.strip()):
                self.attribution(section, number, line)
            else:
                self.close(number)
                self.add(number, UNEXPECTED_LINE)
        self.close(len(lines))
        last = max(len(lines), 1)
        if self.title is None:
            self.add(last, TITLE_LINE.format(title=self.heading))
        named = {section.item.id for section in self.sections}
        for item in BOT_ITEMS:
            if item.id not in named:
                self.add(last, MISSING_SECTION.format(heading=item.heading))
        for section in self.sections:
            if section.stage < 3:
                self.add(section.line, FIRST_LINES)
        return Readings(
            self.title or 1,
            tuple(
                ItemReading(
                    section.item,
                    section.line,
                    section.baseline,
                    section.baseline_line,
                    section.old,
                    section.old_line,
                    section.new,
                    section.new_line,
                    tuple(section.quotes),
                )
                for section in self.sections
            ),
        )


def parse_readings(text: str, ticker: str, season: date) -> tuple[Readings, list[Problem]]:
    """The readings ``text`` of ``ticker``'s season ``season``, and every grammar problem in line
    order. The sections read so far are returned even when the file breaks the grammar, so
    ``readings_problems`` can check them too."""
    parser = _Parser(title(ticker, season))
    readings = parser.read(text)
    return readings, sorted(parser.problems, key=lambda problem: problem.line)


# --------------------------------------------------------------------------- the rules


@dataclass(frozen=True)
class Source:
    """A document a reading may name: its season, whether its text file is fresh, whether it is a
    call, whether the sentence rule reads it in layout mode, and its derived text and turns."""

    season: date
    fresh: Callable[[], bool]
    call: bool
    layout: bool
    text: Callable[[], str]
    turns: Callable[[], Sequence[Turn]]


@dataclass(frozen=True)
class Season:
    """What the rules need of a season: its period, its form, whether it holds a proxy statement,
    its call's status, its documents' ``DOC_ID``s, every document a reading may name, and each
    baseline kind's seasons with their documents in ``raw/``."""

    period: date
    form: str
    proxy: bool
    call: str
    documents: frozenset[str]
    sources: Mapping[str, Source]
    baselines: Mapping[str, tuple[tuple[date, ...], tuple[str, ...]]]


def wording_problems(line: int, text: str) -> list[Problem]:
    """The wording rule on text the bot writes: no valuation, forecast or advice terms."""
    terms = dict.fromkeys(match.group(0).casefold() for match in WORDING.finditer(text))
    return [Problem(line, WORDING_FOUND.format(terms=", ".join(terms)))] if terms else []


def _required_status(item: Item, season: Season) -> tuple[str | None, str]:
    """The status the item must have in the season, with why, or None."""
    if item.scope == "annual" and season.form == "10-Q":
        return "not applicable", "an annual item in a 10-Q season"
    if item.scope == "proxy" and not season.proxy:
        return "not applicable", "a proxy item in a season without a proxy statement"
    if item.scope == "call" and season.call != "transcript":
        return "unavailable", season.call
    return None, ""


def _baseline_documents(item: Item, season: Season) -> tuple[str, ...]:
    """The documents of the item's baseline seasons in ``raw/``: for a call item, their calls."""
    documents = season.baselines.get(item.baseline, ((), ()))[1]
    if item.scope == "call":
        return tuple(
            doc_id for doc_id in documents if doc_id in season.sources and season.sources[doc_id].call
        )
    return documents


def _value_problems(item: Item, side: str, value: str, line: int, season: Season) -> list[Problem]:
    """The status rules (R5 to R8) on one value; ``—`` is checked by ``_status_problems``."""
    required, why = _required_status(item, season)
    if required == "not applicable" and value != required:
        return [Problem(line, NOT_APPLICABLE_NEEDED.format(why=why))]
    if required == "unavailable" and value != required:
        return [Problem(line, UNAVAILABLE_NEEDED.format(status=why))]
    if value == "not applicable" and required != value:
        return [Problem(line, NOT_APPLICABLE_FALSE)]
    if value == "unavailable" and required != value:
        return [Problem(line, UNAVAILABLE_FALSE)]
    if value in ("not disclosed", "not computable") and value not in item.allows:
        return [Problem(line, STATUS_NOT_ALLOWED.format(status=value))]
    if value == "no baseline":
        if side == "new":
            return [Problem(line, NO_BASELINE_NEW)]
        documents = _baseline_documents(item, season)
        if documents:
            shown = ", ".join(documents[:3]) + (" ..." if len(documents) > 3 else "")
            return [Problem(line, NO_BASELINE_FALSE.format(documents=shown))]
    return []


def _status_problems(reading: ItemReading, season: Season) -> list[Problem]:
    item = reading.item
    problems = []
    if reading.old is not None:
        if item.baseline == "none":
            if reading.old != NOTHING:
                problems.append(Problem(reading.old_line, NOTHING_NEEDED))
        elif reading.old == NOTHING:
            problems.append(Problem(reading.old_line, NOTHING_FALSE))
        else:
            problems.extend(_value_problems(item, "old", reading.old, reading.old_line, season))
    if reading.new is not None:
        if reading.new == NOTHING:
            problems.append(Problem(reading.new_line, NOTHING_FALSE))
        else:
            problems.extend(_value_problems(item, "new", reading.new, reading.new_line, season))
    return problems


def _stated(value: str | None) -> bool:
    """Whether ``value`` states facts: neither a status, ``—`` nor ``none``."""
    return value is not None and value not in (*BOT_STATUSES, NOTHING, NONE)


def _baseline_problems(reading: ItemReading, season: Season) -> list[Problem]:
    item, named, line = reading.item, reading.baseline, reading.baseline_line
    if named is None or reading.old is None:
        return []
    if named and item.baseline == "none":
        return [Problem(line, BASELINE_NONE.format(why="an item without a baseline"))]
    if named and reading.old in WITHOUT_BASELINE:
        return [Problem(line, BASELINE_NONE.format(why=f"the old value '{reading.old}'"))]
    problems = []
    if not named and item.baseline != "none" and reading.old not in (*WITHOUT_BASELINE, NOTHING):
        problems.append(Problem(line, BASELINE_NEEDED.format(kind=item.baseline)))
    seasons, allowed = season.baselines.get(item.baseline, ((), ()))
    for doc_id in named:
        if doc_id not in season.sources:
            problems.append(Problem(line, UNKNOWN_DOCUMENT.format(doc_id=doc_id)))
        elif doc_id not in allowed:
            listed = ", ".join(str(day) for day in seasons) or "none listed"
            problems.append(
                Problem(line, NOT_BASELINE.format(doc_id=doc_id, kind=item.baseline, seasons=listed))
            )
        elif not season.sources[doc_id].fresh():
            problems.append(Problem(line, TEXT_STALE.format(doc_id=doc_id)))
    return problems


def _turn_problems(quote: Quote, start: int, end: int, turns: Sequence[Turn]) -> list[Problem]:
    if quote.speaker is None:
        return [Problem(quote.attribution_line, CALL_SPEAKER)]
    turn = next((turn for turn in turns if turn.start <= start and end <= turn.end), None)
    if turn is None:
        return [Problem(quote.line, ACROSS_TURNS)]
    if turn.heading != quote.speaker:
        return [Problem(quote.attribution_line, OTHER_TURN.format(heading=turn.heading))]
    return []


def quote_problems(quote: Quote, source: Source) -> list[Problem]:
    """The rules a located quote keeps against its document (R9)."""
    if quote.speaker is not None and not source.call:
        return [Problem(quote.attribution_line, NO_SPEAKER)]
    length = len(normalise(quote.text))
    if not QUOTE_MIN <= length <= QUOTE_MAX:
        return [Problem(quote.line, QUOTE_LENGTH.format(length=length))]
    derived = source.text()
    location = locate(quote.text, derived)
    if location is None:
        return [Problem(quote.line, QUOTE_NOT_FOUND)]
    if " ".join(derived[location.start : location.end].split()) != " ".join(quote.text.split()):
        return [Problem(quote.line, QUOTE_SPELLING)]
    problems = []
    label = None if quote.speaker is None else quote.speaker.rpartition(" (")[0]
    if not sentence_bounded(
        derived, location.start, location.end, layout=source.layout, label=label if source.call else None
    ):
        problems.append(Problem(quote.line, NOT_WHOLE))
    if source.call:
        problems.extend(_turn_problems(quote, location.start, location.end, source.turns()))
    return problems


def _quotes_problems(reading: ItemReading, season: Season) -> list[Problem]:
    problems = []
    baseline = set(reading.baseline or ())
    seen: set[tuple[str, str]] = set()
    own = False
    for quote in reading.quotes:
        source = season.sources.get(quote.doc_id)
        if source is None:
            problems.append(Problem(quote.attribution_line, UNKNOWN_DOCUMENT.format(doc_id=quote.doc_id)))
            continue
        if quote.doc_id not in season.documents and quote.doc_id not in baseline:
            problems.append(Problem(quote.attribution_line, QUOTE_SOURCE))
            continue
        if not source.fresh():
            problems.append(Problem(quote.attribution_line, TEXT_STALE.format(doc_id=quote.doc_id)))
            continue
        key = (quote.doc_id, normalise(quote.text))
        if key in seen:
            problems.append(Problem(quote.line, REPEATED_QUOTE))
            continue
        seen.add(key)
        own = own or quote.doc_id in season.documents
        problems.extend(quote_problems(quote, source))
    if reading.item.importance == "high" and _stated(reading.new) and not own:
        problems.append(Problem(reading.new_line, HIGH_NEEDS_QUOTE))
    return problems


def _item_problems(reading: ItemReading, season: Season) -> Iterator[Problem]:
    yield from _status_problems(reading, season)
    yield from _baseline_problems(reading, season)
    for value, line in ((reading.old, reading.old_line), (reading.new, reading.new_line)):
        if value is not None:
            yield from wording_problems(line, value)
    yield from _quotes_problems(reading, season)


def readings_problems(readings: Readings, season: Season) -> list[Problem]:
    """Every rule (R1 to R10) the readings break in ``season``, in line order."""
    problems = [problem for reading in readings.items for problem in _item_problems(reading, season)]
    return sorted(problems, key=lambda problem: problem.line)
