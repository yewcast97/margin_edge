"""The bot's readings of one comparison of a season: their grammar and the rules ``check`` holds them to.

The bot reads the documents of a season and of its comparison's baseline season
(``aspects.comparisons``; the season's sheet, ``formatted/{T}/{PERIOD}/season.md``, names both
sides' ``DOC_ID``s) in their derived text, ``formatted/{T}/{PERIOD}/{DOC_ID}.md``, and writes,
per comparison, ``reports/{T}/{PERIOD}/readings_{KIND}.md``: every item it finds of each aspect
(``aspects.ASPECTS``), the season's value and the baseline's side by side, the difference
between them and the quotes they rest on. ``parse_readings`` reads it line by line:

- G1: the first non-blank line is ``# {T} · {PERIOD} · {KIND} readings``, ``KIND`` the
  comparison's: ``quarter`` or ``year``;
- G2: then one section per aspect, each once, in the aspects' order, headed ``## {title}``;
- G3: a section is the one line ``na``, when the documents of neither side state anything of
  the aspect, or its items, each headed ``### {title}`` (1 to ``MAX_TITLE`` printable
  characters, no two alike in one aspect, letter case aside) and followed by five lines in this
  order: ``season:``, ``new:``, ``baseline:``, ``old:`` and ``difference:``;
- G4: ``season:`` and ``baseline:`` are ``none`` or distinct ``DOC_ID``s joined by ``; ``: the
  documents of the season, and of the baseline, that the new value, and the old one, rest on;
- G5: ``new:`` is the season's value and ``old:`` the baseline's, each ``na`` when the
  documents of its side state nothing of the item (``no baseline``, for the old one, while the
  baseline is not in ``raw/``) or the value in facts; ``difference:`` is ``na`` beside a value
  that is ``na`` or ``no baseline``, ``none`` when the two values are written alike, else the
  difference in facts; each is 1 to ``MAX_VALUE`` printable characters on its line;
- G6: then zero or more quotes: ``> TEXT`` lines, whose texts are joined by one space, and then
  one attribution line, ``— {DOC_ID}``, or ``— {DOC_ID}, {Speaker} ({role})`` for a call's
  quote; blank lines may separate quotes.

Any other line is an error; trailing spaces, CRLF line ends and a leading byte order mark are
accepted. Every problem names its line (1 for the first).

``readings_problems`` then holds every item to the rules (``Comparison`` gives what they need):

- R0: ``year`` readings are a 10-K season's only;
- R1: every ``DOC_ID`` named is a document in ``raw/`` whose text file equals its derivation;
- R2: ``season:`` names documents of the season only, ``baseline:`` documents of the
  comparison's baseline season only;
- R3: ``season:`` is ``none`` exactly when ``new:`` is ``na``, and ``baseline:`` exactly when
  ``old:`` is ``na`` or ``no baseline``, so that a stated value names the documents it rests on;
  every document either line names is quoted in the item; ``none`` is no value;
- R4: ``no baseline`` is an old value only, and exactly while the baseline season is not listed
  or none of its documents is in ``raw/``; an item states a value on one side at least;
- R5: ``difference:`` is ``na`` exactly when a value is ``na`` or ``no baseline``, and ``none``
  exactly when the two values are written alike (whitespace runs aside);
- R6: a quote comes from a document the item's ``season:`` or ``baseline:`` line names, is 20
  to 800 characters once normalised, is found verbatim in its document's derived text, spelt as
  it writes it, and is whole sentences or lines at its first occurrence
  (``text.sentence_bounded`` in the document's mode); a call's quote names its turn's heading,
  ``{Speaker} ({role})``, exactly, and lies within that turn's words, any role's; a quote of
  another document names no speaker; no quote is given twice in one item;
- R7: an item's title, values and difference carry no valuation, forecast or advice wording
  (``WORDING``; quotes are the issuer's words and are never checked against it).
"""

import re
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Final

from .aspects import ASPECTS, KINDS, Aspect, Kind
from .earningscalls import Turn
from .text import QUOTE_MAX, QUOTE_MIN, locate, normalise, sentence_bounded

# Accounting's "fair value" and a proxy statement's "advisory vote" are facts, not advice.
WORDING = re.compile(
    r"\b(?:buy|sell|hold|overweight|underweight|undervalued|overvalued|price target|target price|"
    r"upside|downside|bullish|bearish|recommend\w*|advice|advis(?:e[ds]?|ing|able)|should (?:buy|sell)|"
    r"outperform|underperform)\b",
    re.IGNORECASE,
)
MAX_TITLE: Final = 120
MAX_VALUE: Final = 600
DASH: Final = "— "
NA: Final = "na"
NONE: Final = "none"
NO_BASELINE: Final = "no baseline"
LABELS: Final = ("season", "new", "baseline", "old", "difference")

TITLE_LINE = "the first line must be '# {title}'"
DRAFT_TITLE = "the first line must be '# {quarter}' or '# {year}'"
HEADINGS = "the sections must be the aspects, each once, in this order: " + ", ".join(
    f"'## {aspect.title}'" for aspect in ASPECTS
)
MISSING_SECTION = "the section '## {title}' is missing"
OUTSIDE_SECTION = "this line is outside the readings' sections"
SECTION_FORM = "a section is the one line 'na' or its items, each headed '### TITLE'"
EMPTY_SECTION = "the section holds neither 'na' nor an item"
ITEM_TITLE = f"an item's title is 1 to {MAX_TITLE} printable characters"
REPEATED_TITLE = "another item of this aspect has this title"
ITEM_LINES = (
    "an item's heading is followed by its 'season:', 'new:', 'baseline:', 'old:' and 'difference:' lines, "
    "in that order"
)
UNEXPECTED_LINE = "an item holds its five lines, then '> TEXT' lines each quote ended by its '— DOC_ID' line"
EMPTY_QUOTE_LINE = "an empty '>' line; a quote's lines each hold text"
NO_ATTRIBUTION = "a quote's '>' lines must be followed by its attribution line '— DOC_ID'"
ATTRIBUTION_TEXT = "an attribution line is '— DOC_ID', or '— DOC_ID, Speaker (role)' for a call's quote"
ATTRIBUTION_WITHOUT_QUOTE = "an attribution line must follow a quote's '>' lines"
DOCUMENTS_TEXT = "the '{label}:' line must be 'none' or distinct DOC_IDs joined by '; '"
VALUE_TEXT = f"the '{{label}}:' line must hold 1 to {MAX_VALUE} printable characters"

YEAR_OF_10Q = (
    "only a 10-K season has year readings: a 10-Q season is compared with the season before it alone"
)
UNKNOWN_DOCUMENT = "{doc_id} is no document in raw/ (a DOC_ID of a text file in formatted/)"
TEXT_STALE = "the text file of {doc_id} is missing or differs from its derivation; run derive"
NOT_SEASON = "{doc_id} is no document of the season {period}"
NOT_BASELINE = "{doc_id} is no document of the baseline season {baseline}"
NO_BASELINE_SEASON = "{doc_id} is no document of the baseline: no baseline season is listed"
NAMES_NEEDED = "the {side} value is stated: '{label}:' names the documents it rests on"
NAMES_NONE = "'{label}:' is 'none' while the {side} value is '{status}'"
NOT_QUOTED = "{doc_id} is named on this line but quoted nowhere in this item"
NONE_VALUE = (
    "'none' is no value: write 'na' when the documents state nothing of the item, or state the fact "
    "itself (no borrowings outstanding)"
)
NO_BASELINE_NEW = "'no baseline' is an old value only"
NO_BASELINE_NEEDED = "the old value is 'no baseline' while the baseline is not in raw/ ({why})"
NO_BASELINE_FALSE = "'no baseline' while the baseline is in raw/: {documents}"
NOTHING_STATED = (
    "an item states a value on one side at least: an aspect whose documents state nothing of it is 'na'"
)
DIFFERENCE_NA = "the difference is 'na' while a value is 'na' or 'no baseline'"
DIFFERENCE_NOT_NA = "the difference is 'na' only while a value is 'na' or 'no baseline'"
DIFFERENCE_NONE = "the two values are written alike: the difference is 'none'"
DIFFERENCE_NOT_NONE = "the difference is 'none' only when the two values are written alike"
QUOTE_SOURCE = "a quote comes from a document the item's 'season:' or 'baseline:' line names"
WORDING_FOUND = (
    "an item's title, values and difference state facts only, without valuation, forecast or advice "
    "wording; found: {terms}"
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
    "a quote must be whole sentences, or whole lines of an HTML or call document: it must start, never "
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
class Item:
    """One item of an aspect: its title and heading's line, its five lines' values (the documents of
    ``season:`` and ``baseline:`` as ``DOC_ID``s, empty for ``none``; None where a line is
    missing), its quotes, and each line's number."""

    title: str
    line: int
    season: tuple[str, ...] | None = None
    new: str | None = None
    baseline: tuple[str, ...] | None = None
    old: str | None = None
    difference: str | None = None
    quotes: tuple[Quote, ...] = ()
    season_line: int = 0
    new_line: int = 0
    baseline_line: int = 0
    old_line: int = 0
    difference_line: int = 0


@dataclass(frozen=True)
class Section:
    """One aspect's section: its heading's line, the line of its ``na`` (0 without one) and its items,
    in the order written."""

    aspect: Aspect
    line: int
    na: int = 0
    items: tuple[Item, ...] = ()


@dataclass(frozen=True)
class Readings:
    """A parsed readings file: the kind of comparison it reads, its title's line and its sections as
    written."""

    kind: Kind
    title_line: int
    sections: tuple[Section, ...]

    def section(self, key: str) -> Section | None:
        return next((section for section in self.sections if section.aspect.key == key), None)

    @property
    def items(self) -> tuple[tuple[Aspect, Item], ...]:
        """Every item with its aspect, in the order written."""
        return tuple((section.aspect, item) for section in self.sections for item in section.items)


def title(ticker: str, season: date, kind: Kind) -> str:
    return f"{ticker} · {season.isoformat()} · {kind} readings"


def readings_name(kind: Kind) -> str:
    """A comparison's readings file in its season's folder: ``readings_{KIND}.md``."""
    return f"readings_{kind}.md"


def alike(new: str, old: str) -> bool:
    """Whether two values are written alike, the runs of whitespace between their words aside."""
    return new.split() == old.split()


def stated(value: str | None) -> bool:
    """Whether ``value`` is a value in facts: neither missing, ``na`` nor ``no baseline``."""
    return value is not None and value not in (NA, NO_BASELINE)


@dataclass
class _Item:
    title: str
    line: int
    values: dict[str, str] = field(default_factory=dict)
    documents: dict[str, tuple[str, ...]] = field(default_factory=dict)
    lines: dict[str, int] = field(default_factory=dict)
    quotes: list[Quote] = field(default_factory=list)
    stage: int = 0  # the five lines read so far

    def done(self) -> Item:
        return Item(
            self.title,
            self.line,
            self.documents.get("season"),
            self.values.get("new"),
            self.documents.get("baseline"),
            self.values.get("old"),
            self.values.get("difference"),
            tuple(self.quotes),
            *(self.lines.get(label, 0) for label in LABELS),
        )


@dataclass
class _Section:
    aspect: Aspect
    line: int
    na: int = 0
    items: list[_Item] = field(default_factory=list)
    titles: set[str] = field(default_factory=set)  # the items' titles, letter case aside


class _Parser:
    """The line-by-line reading of one readings file; ``problems`` collects every broken rule."""

    def __init__(self, titles: Mapping[Kind, str], kind: Kind) -> None:
        self.titles = titles  # each title line the file may open with, by the kind it names
        self.kind = kind
        self.problems: list[Problem] = []
        self.sections: list[_Section] = []
        self.section: _Section | None = None
        self.item: _Item | None = None
        self.lost = False  # after a refused heading, until the next section's
        self.title: int | None = None
        self.block: list[str] | None = None
        self.block_line = 0

    def add(self, line: int, message: str) -> None:
        self.problems.append(Problem(line, message))

    def title_problem(self) -> str:
        if len(self.titles) == 1:
            return TITLE_LINE.format(title=next(iter(self.titles.values())))
        return DRAFT_TITLE.format(quarter=self.titles["quarter"], year=self.titles["year"])

    def close(self) -> None:
        """End a quote whose attribution never came."""
        if self.block is not None:
            self.add(self.block_line, NO_ATTRIBUTION)
        self.block = None

    def start_section(self, number: int, text: str) -> None:
        self.close()
        self.item = None
        seen = [section.aspect for section in self.sections]
        aspect = next((aspect for aspect in ASPECTS if aspect.title == text), None)
        if aspect is None or aspect in seen:
            self.add(number, HEADINGS)
            self.section, self.lost = None, True
            return
        if any(ASPECTS.index(other) > ASPECTS.index(aspect) for other in seen):
            self.add(number, HEADINGS)
        self.lost = False
        self.section = _Section(aspect, number)
        self.sections.append(self.section)

    def start_item(self, number: int, text: str) -> None:
        self.close()
        section = self.section
        if section is None:
            if not self.lost:
                self.add(number, OUTSIDE_SECTION)
            self.item, self.lost = None, True
            return
        if section.na:
            self.add(number, SECTION_FORM)
        if not 0 < len(text) <= MAX_TITLE or not text.isprintable():
            self.add(number, ITEM_TITLE)
        elif text.casefold() in section.titles:
            self.add(number, REPEATED_TITLE)
        section.titles.add(text.casefold())
        self.item = _Item(text, number)
        section.items.append(self.item)

    def na(self, section: _Section, number: int) -> None:
        if section.na or section.items:
            self.add(number, SECTION_FORM)
        else:
            section.na = number

    def documents(self, number: int, label: str, value: str) -> tuple[str, ...]:
        if value == NONE:
            return ()
        parts = value.split("; ")
        if (
            not value
            or any(not part or part != part.strip() or " " in part for part in parts)
            or len(set(parts)) != len(parts)
        ):
            self.add(number, DOCUMENTS_TEXT.format(label=label))
        return tuple(dict.fromkeys(part for part in parts if part))

    def labelled(self, item: _Item, number: int, line: str) -> bool:
        """Read ``line`` as the item's next labelled line; False when the line is to be read as a
        quote's (an item that skipped its lines is reported once)."""
        label = LABELS[item.stage]
        if not line.startswith(f"{label}:"):
            self.add(number, ITEM_LINES)
            item.stage = len(LABELS)
            return not line.startswith((">", DASH.strip()))
        value = line[len(label) + 1 :].strip()
        item.lines[label] = number
        if label in ("season", "baseline"):
            item.documents[label] = self.documents(number, label, value)
        else:
            item.values[label] = value
            if not 0 < len(value) <= MAX_VALUE or not value.isprintable():
                self.add(number, VALUE_TEXT.format(label=label))
        item.stage += 1
        return True

    def attribution(self, item: _Item, number: int, line: str) -> None:
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
        item.quotes.append(Quote(self.block_line, text, doc_id, speaker or None, number))
        self.block = None

    def body(self, number: int, line: str) -> None:
        """A line inside a section, neither a heading nor blank."""
        section, item = self.section, self.item
        if section is None:
            if not self.lost:
                self.add(number, OUTSIDE_SECTION)
            return
        if item is not None and item.stage < len(LABELS) and self.labelled(item, number, line):
            return
        if line == NA:
            self.close()
            self.na(section, number)
            return
        if item is None:
            self.add(number, SECTION_FORM)
            return
        if line.startswith(">"):
            quoted = line[1:].strip()
            if not quoted:
                self.add(number, EMPTY_QUOTE_LINE)
                return
            if self.block is None:
                self.block, self.block_line = [], number
            self.block.append(quoted)
        elif line.startswith(DASH.strip()):
            self.attribution(item, number, line)
        else:
            self.close()
            self.add(number, UNEXPECTED_LINE)

    def read(self, text: str) -> Readings:
        lines = text.splitlines()
        for number, raw in enumerate(lines, start=1):
            line = raw.rstrip()
            if self.title is None:
                if not line:
                    continue
                self.title = number
                opened = next((kind for kind, title in self.titles.items() if line == f"# {title}"), None)
                if opened is not None:
                    self.kind = opened
                    continue
                self.add(number, self.title_problem())
                if line.startswith("# "):
                    continue
            if line.startswith("## "):
                self.start_section(number, line[3:].strip())
            elif line.startswith("### "):
                self.start_item(number, line[4:].strip())
            elif line:
                self.body(number, line)
        self.close()
        last = max(len(lines), 1)
        if self.title is None:
            self.add(last, self.title_problem())
        named = {section.aspect for section in self.sections}
        for aspect in ASPECTS:
            if aspect not in named:
                self.add(last, MISSING_SECTION.format(title=aspect.title))
        for section in self.sections:
            if not section.na and not section.items:
                self.add(section.line, EMPTY_SECTION)
            for item in section.items:
                if item.stage < len(LABELS):
                    self.add(item.line, ITEM_LINES)
        return Readings(
            self.kind,
            self.title or 1,
            tuple(
                Section(
                    section.aspect, section.line, section.na, tuple(item.done() for item in section.items)
                )
                for section in self.sections
            ),
        )


def parse_readings(
    text: str, ticker: str, season: date, kind: Kind | None = None
) -> tuple[Readings, list[Problem]]:
    """The readings ``text`` of ``ticker``'s season ``season``, read as ``kind``'s, and every grammar
    problem in line order. Without ``kind`` (a draft) the readings are the kind their title names,
    ``quarter`` when it names neither. The sections read so far are returned even when the file
    breaks the grammar, so ``readings_problems`` can check them too."""
    kinds = KINDS if kind is None else (kind,)
    parser = _Parser({named: title(ticker, season, named) for named in kinds}, kind or "quarter")
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
class Comparison:
    """What the rules need of one comparison: its kind; its season's period, form and documents'
    ``DOC_ID``s; its baseline season's period (None when none is listed) and documents in
    ``raw/``; and every document a reading may name."""

    kind: Kind
    period: date
    form: str
    documents: frozenset[str]
    baseline: date | None
    baseline_documents: tuple[str, ...]
    sources: Mapping[str, Source]

    @property
    def missing(self) -> str | None:
        """Why the baseline is not in ``raw/``, or None."""
        if self.baseline is None:
            return "no baseline season is listed"
        if not self.baseline_documents:
            return f"no document of the season {self.baseline} is in raw/"
        return None


def wording_problems(line: int, text: str) -> list[Problem]:
    """The wording rule on text the bot writes: no valuation, forecast or advice terms."""
    terms = dict.fromkeys(match.group(0).casefold() for match in WORDING.finditer(text))
    return [Problem(line, WORDING_FOUND.format(terms=", ".join(terms)))] if terms else []


def _sides(item: Item) -> tuple[tuple[str, tuple[str, ...] | None, int], ...]:
    return (("season", item.season, item.season_line), ("baseline", item.baseline, item.baseline_line))


def _allowed(label: str, doc_id: str, comparison: Comparison) -> str | None:
    """Why ``doc_id`` may not stand on the ``label`` line (R2), or None."""
    if label == "season":
        return (
            None
            if doc_id in comparison.documents
            else NOT_SEASON.format(doc_id=doc_id, period=comparison.period)
        )
    if comparison.baseline is None:
        return NO_BASELINE_SEASON.format(doc_id=doc_id)
    if doc_id in comparison.baseline_documents:
        return None
    return NOT_BASELINE.format(doc_id=doc_id, baseline=comparison.baseline)


def _documents_problems(item: Item, comparison: Comparison) -> Iterator[Problem]:
    """R1 and R2 on the ``season:`` and ``baseline:`` lines."""
    for label, named, line in _sides(item):
        for doc_id in named or ():
            source = comparison.sources.get(doc_id)
            if source is None:
                yield Problem(line, UNKNOWN_DOCUMENT.format(doc_id=doc_id))
            elif (why := _allowed(label, doc_id, comparison)) is not None:
                yield Problem(line, why)
            elif not source.fresh():
                yield Problem(line, TEXT_STALE.format(doc_id=doc_id))


def _status_problems(item: Item, comparison: Comparison) -> Iterator[Problem]:
    """R3's lines, R4 and R5."""
    new, old = item.new, item.old
    for value, line in ((new, item.new_line), (old, item.old_line)):
        if value == NONE:
            yield Problem(line, NONE_VALUE)
    if new == NO_BASELINE:
        yield Problem(item.new_line, NO_BASELINE_NEW)
    for label, side, value, named, line in (
        ("season", "new", new, item.season, item.season_line),
        ("baseline", "old", old, item.baseline, item.baseline_line),
    ):
        if named is None or value is None:
            continue
        if not stated(value) and named:
            yield Problem(line, NAMES_NONE.format(label=label, side=side, status=value))
        elif stated(value) and not named:
            yield Problem(line, NAMES_NEEDED.format(label=label, side=side))
    missing = comparison.missing
    if old is not None:
        if missing is not None and old != NO_BASELINE:
            yield Problem(item.old_line, NO_BASELINE_NEEDED.format(why=missing))
        elif missing is None and old == NO_BASELINE:
            documents = comparison.baseline_documents
            shown = ", ".join(documents[:3]) + (" ..." if len(documents) > 3 else "")
            yield Problem(item.old_line, NO_BASELINE_FALSE.format(documents=shown))
    if new == NA and old in (NA, NO_BASELINE):
        yield Problem(item.line, NOTHING_STATED)
    difference = item.difference
    if difference is None or new is None or old is None:
        return
    if not stated(new) or not stated(old):
        if difference != NA:
            yield Problem(item.difference_line, DIFFERENCE_NA)
    elif difference == NA:
        yield Problem(item.difference_line, DIFFERENCE_NOT_NA)
    elif alike(new, old):
        if difference != NONE:
            yield Problem(item.difference_line, DIFFERENCE_NONE)
    elif difference == NONE:
        yield Problem(item.difference_line, DIFFERENCE_NOT_NONE)


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
    """The rules a located quote keeps against its document (R6)."""
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


def _quotes_problems(item: Item, comparison: Comparison) -> Iterator[Problem]:
    """R6, and R3's rule that every document a line names is quoted."""
    named = {doc_id for _, documents, _ in _sides(item) for doc_id in documents or ()}
    seen: set[tuple[str, str]] = set()
    quoted: set[str] = set()
    for quote in item.quotes:
        source = comparison.sources.get(quote.doc_id)
        if source is None:
            yield Problem(quote.attribution_line, UNKNOWN_DOCUMENT.format(doc_id=quote.doc_id))
            continue
        if quote.doc_id not in named:
            yield Problem(quote.attribution_line, QUOTE_SOURCE)
            continue
        quoted.add(quote.doc_id)
        if not source.fresh():
            yield Problem(quote.attribution_line, TEXT_STALE.format(doc_id=quote.doc_id))
            continue
        key = (quote.doc_id, normalise(quote.text))
        if key in seen:
            yield Problem(quote.line, REPEATED_QUOTE)
            continue
        seen.add(key)
        yield from quote_problems(quote, source)
    for label, documents, line in _sides(item):
        for doc_id in documents or ():
            known = doc_id in comparison.sources and _allowed(label, doc_id, comparison) is None
            if known and doc_id not in quoted:
                yield Problem(line, NOT_QUOTED.format(doc_id=doc_id))


def _item_problems(item: Item, comparison: Comparison) -> Iterator[Problem]:
    yield from _documents_problems(item, comparison)
    yield from _status_problems(item, comparison)
    for value, line in (
        (item.title, item.line),
        (item.new, item.new_line),
        (item.old, item.old_line),
        (item.difference, item.difference_line),
    ):
        if value is not None:
            yield from wording_problems(line, value)
    yield from _quotes_problems(item, comparison)


def readings_problems(readings: Readings, comparison: Comparison) -> list[Problem]:
    """Every rule (R0 to R7) the readings break in ``comparison``, in line order."""
    if comparison.kind == "year" and comparison.form != "10-K":
        return [Problem(readings.title_line, YEAR_OF_10Q)]
    problems = [problem for _, item in readings.items for problem in _item_problems(item, comparison)]
    return sorted(problems, key=lambda problem: problem.line)
