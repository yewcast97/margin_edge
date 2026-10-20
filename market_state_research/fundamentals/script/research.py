"""The agent's eleven-field report of one document, its grammar and the rules its quotes keep.

The agent reads a document's derived text (``formatted/{T}/{DOC_ID}.md``) and writes what
it says, in eleven fields of verbatim quotes (``FIELDS``, in this order: ``upstream_shortage``,
``capacity_shortfall``, ``capex_plans``, ``capacity_expansion``, ``earnings_guidance``,
``pricing``, ``backlog_contracts``, ``product_ramp``, ``margin_drivers``,
``financing_methods``, ``customer_concentration``; the definitions are AGENTS.md's), as the
Markdown report ``reports/{T}/{DOC_ID}.md``. ``parse_report`` reads it line by line:

- the first non-blank line is ``# {DOC_ID}``, the file's name without ``.md``;
- then exactly one ``## {field}`` heading per field of ``FIELDS``, in that order
  (``## upstream_shortage`` to ``## customer_concentration``);
- a section holds either the line ``None found.`` or quote blocks separated by blank lines;
- a quote block is an optional ``Speaker: {name}`` line followed by consecutive ``> {text}``
  lines, whose texts are joined by one space (every whitespace run in them reads as one
  space);
- an empty ``>`` line, or any other non-blank line, is an error.

Every problem names its line (1 for the first). ``quote_problems`` then checks each quote
against its document's derived text: its normalised length is ``QUOTE_MIN`` to
``QUOTE_MAX`` characters; it is found there (``text.locate``) spelt as the derived text
writes it (only the whitespace between its words may differ, so a soft hyphen, a
zero-width character or a ligature the text writes as letters is refused, and the series
shows the document's own characters) and is whole sentences, or whole lines of a document
read in block mode, at its first occurrence (``text.sentence_bounded`` in the document's
mode, with the speaker as the label a quote may start after in a call document only: a
filing's or exhibit's speaker never lets a quote start after a colon); a speaker is spelt
as the derived text writes it in the same way and first occurs before the quote; and a
speaker carries no valuation, forecast or advice wording (``WORDING``). In a call
document, whose derived text is the transcript's turns (``Turn``: a heading line naming
the speaker and the role the transcript provider gives them, then their words), a quote
also names its speaker, lies within one turn's words, that turn's role is ``executive``
(the issuer's own executives; never an analyst, the operator or a speaker of any other
role) and its ``Speaker:`` line is exactly the name the turn's heading writes. Quotes are
the issuer's own words and are never checked against the wording rule. Messages repeat no
quote text; the only report text a message names is what the agent must change: the
wording terms found in a speaker, and the role of a turn that is not an executive's.
"""

import re
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Final, Literal

from .text import QUOTE_MAX, QUOTE_MIN, locate, normalise, sentence_bounded

FieldName = Literal[
    "upstream_shortage",
    "capacity_shortfall",
    "capex_plans",
    "capacity_expansion",
    "earnings_guidance",
    "pricing",
    "backlog_contracts",
    "product_ramp",
    "margin_drivers",
    "financing_methods",
    "customer_concentration",
]
# The eleven fields of a report, in the order a report and the time series list them.
FIELDS: Final[tuple[FieldName, ...]] = (
    "upstream_shortage",
    "capacity_shortfall",
    "capex_plans",
    "capacity_expansion",
    "earnings_guidance",
    "pricing",
    "backlog_contracts",
    "product_ramp",
    "margin_drivers",
    "financing_methods",
    "customer_concentration",
)
FIELD_TITLES: Final[Mapping[FieldName, str]] = {
    "upstream_shortage": "Upstream shortage",
    "capacity_shortfall": "Capacity shortfall",
    "capex_plans": "Capex plans",
    "capacity_expansion": "Capacity expansion",
    "earnings_guidance": "Earnings guidance",
    "pricing": "Pricing",
    "backlog_contracts": "Backlog and contracts",
    "product_ramp": "Product ramp",
    "margin_drivers": "Margin drivers",
    "financing_methods": "Financing methods",
    "customer_concentration": "Customer concentration",
}
WORDING = re.compile(
    r"\b(?:buy|sell|hold|overweight|underweight|undervalued|overvalued|price target|target price|"
    r"fair value|upside|downside|bullish|bearish|recommend\w*|advice|advis\w*|should (?:buy|sell)|"
    r"outperform|underperform)\b",
    re.IGNORECASE,
)
NONE_FOUND = "None found."
SPEAKER = "Speaker:"
MAX_SPEAKER = 120
# The one role a call quote may come from: the issuer's own executives.
EXECUTIVE: Final = "executive"

TITLE_LINE = "the first line must be '# {doc_id}', the report file's name without .md"
HEADINGS = (
    "the sections must be "
    + ", ".join(f"'## {name}'" for name in FIELDS[:-1])
    + f" and '## {FIELDS[-1]}', each once, in that order"
)
MISSING_SECTION = "the section '## {name}' is missing"
EMPTY_SECTION = "the section '## {name}' must hold quotes or the line 'None found.'"
NONE_AND_QUOTES = "a section holds either the line 'None found.' or quotes, never both"
OUTSIDE_SECTION = "this line is outside the report's sections"
EMPTY_QUOTE_LINE = "an empty '>' line; a quote's lines each hold text"
UNEXPECTED_LINE = (
    "a section holds only the line 'None found.', 'Speaker: NAME' lines and '> TEXT' lines, "
    "with blank lines between quotes"
)
SPEAKER_WITHOUT_QUOTE = "a 'Speaker:' line must be followed by its quote's '>' lines"
BLANK_BETWEEN = "a blank line must separate two quotes"
SPEAKER_TEXT = (
    f"a speaker must be 1 to {MAX_SPEAKER} printable characters without repeated spaces, "
    "as the derived text writes the name"
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
    "a quote must be whole sentences, or whole lines of an HTML document or a call transcript: it must "
    "start, never in lowercase even after a list glyph, at such a line start or after a sentence end, "
    "a colon that ends a line or, in a call, its speaker's label, and end at such a line end or with "
    "a sentence end and whitespace, before text that does not start in lowercase even after a list glyph"
)
SPEAKER_NOT_FOUND = "the speaker is not found in the document's derived text before the quote"
WORDING_FOUND = "names state facts only, without valuation, forecast or advice wording; found: {terms}"
CALL_SPEAKER = "a call quote needs a 'Speaker:' line naming the executive whose turn it quotes"
ACROSS_TURNS = "a call quote must lie within the words of one speaker's turn, below its heading"
NOT_EXECUTIVE = (
    "the quote lies in a turn whose role is {role}, not executive: quote only the issuer's executives"
)
OTHER_SPEAKER = (
    "the quote lies in another speaker's turn: the 'Speaker:' line must be the name its heading writes"
)


@dataclass(frozen=True)
class Turn:
    """One speaker's turn in a call document's derived text: the offsets of its words (its
    heading line left out), the speaker's name as the heading writes it and the speaker's
    role as the transcript provider gives it (``executive``, ``analyst``, ``operator`` ...)."""

    start: int
    end: int
    speaker: str
    role: str


@dataclass(frozen=True)
class Problem:
    """One broken rule of a report: its line (from 1) and what is wrong."""

    line: int
    message: str


@dataclass(frozen=True)
class Quote:
    """One quote block: the line of its first ``>`` line, its text (the ``>`` lines' words joined by
    one space) and the speaker its ``Speaker:`` line names (with that line's number), if any."""

    line: int
    text: str
    speaker: str | None = None
    speaker_line: int | None = None


@dataclass(frozen=True)
class Report:
    """A parsed report: the document it names and each field's quotes, in ``FIELDS`` order."""

    doc_id: str
    line: int
    fields: tuple[tuple[FieldName, tuple[Quote, ...]], ...]

    def quotes(self) -> Iterator[tuple[FieldName, Quote]]:
        for name, quotes in self.fields:
            for quote in quotes:
                yield name, quote

    def field(self, name: FieldName) -> tuple[Quote, ...]:
        return dict(self.fields)[name]


@dataclass
class _Section:
    name: FieldName
    line: int
    none_found: bool = False
    quotes: list[Quote] | None = None


class _Parser:
    """The line-by-line reading of one report; ``problems`` collects every broken rule."""

    def __init__(self, doc_id: str) -> None:
        self.doc_id = doc_id
        self.problems: list[Problem] = []
        self.sections: list[_Section] = []
        self.section: _Section | None = None
        self.lost = False  # after a refused heading, until the next one: its lines are not reported
        self.title: int | None = None
        self.speaker: tuple[str, int] | None = None  # a Speaker: line waiting for its quote
        self.block: list[str] | None = None  # the open quote's texts
        self.block_line = 0
        self.block_speaker: tuple[str, int] | None = None

    def add(self, line: int, message: str) -> None:
        self.problems.append(Problem(line, message))

    def close(self) -> None:
        """End the open quote block, if any, and refuse a speaker left without one."""
        if self.block is not None and self.section is not None:
            speaker, speaker_line = self.block_speaker or (None, None)
            quotes = self.section.quotes if self.section.quotes is not None else []
            text = " ".join(" ".join(self.block).split())
            quotes.append(Quote(self.block_line, text, speaker, speaker_line))
            self.section.quotes = quotes
        self.block = None
        self.block_speaker = None
        if self.speaker is not None:
            self.add(self.speaker[1], SPEAKER_WITHOUT_QUOTE)
            self.speaker = None

    def heading(self, number: int, name: str) -> None:
        """A ``##`` line: a field's section, refused when unknown or repeated; one out of order
        is reported once and still read, so its quotes are checked and no later heading fails."""
        self.close()
        seen = [section.name for section in self.sections]
        field = next((field for field in FIELDS if field == name), None)
        self.lost = field is None or field in seen
        if field is None or field in seen:
            self.add(number, HEADINGS)
            self.section = None
            return
        if any(FIELDS.index(other) > FIELDS.index(field) for other in seen):
            self.add(number, HEADINGS)
        self.section = _Section(field, number)
        self.sections.append(self.section)

    def in_section(self, number: int) -> _Section | None:
        if self.section is None and not self.lost:
            self.add(number, OUTSIDE_SECTION)
        return self.section

    def none_found(self, number: int) -> None:
        self.close()
        section = self.in_section(number)
        if section is None:
            return
        if section.none_found or section.quotes:
            self.add(number, NONE_AND_QUOTES)
        section.none_found = True

    def speaker_line(self, number: int, name: str) -> None:
        if self.block is not None:
            self.add(number, BLANK_BETWEEN)
        self.close()
        section = self.in_section(number)
        if section is None:
            return
        if section.none_found:
            self.add(number, NONE_AND_QUOTES)
        if not (0 < len(name) <= MAX_SPEAKER and name.isprintable() and name == " ".join(name.split())):
            self.add(number, SPEAKER_TEXT)
        self.speaker = (name, number)

    def quote_line(self, number: int, text: str) -> None:
        section = self.in_section(number)
        if section is None:
            return
        if not text:
            self.add(number, EMPTY_QUOTE_LINE)
            return
        if self.block is None:
            if section.none_found:
                self.add(number, NONE_AND_QUOTES)
            self.block, self.block_line = [], number
            self.block_speaker, self.speaker = self.speaker, None
        self.block.append(text)

    def read(self, text: str) -> Report:
        lines = text.splitlines()
        for number, raw in enumerate(lines, start=1):
            line = raw.rstrip()
            if self.title is None:
                if not line:
                    continue
                self.title = number
                if line == f"# {self.doc_id}":
                    continue
                self.add(number, TITLE_LINE.format(doc_id=self.doc_id))
                if line.startswith("# "):
                    continue  # a wrong title; any other first line is read as the body's
            if not line:
                self.close()
            elif line.startswith("## "):
                self.heading(number, line[3:].strip())
            elif line == NONE_FOUND:
                self.none_found(number)
            elif line.startswith(SPEAKER):
                self.speaker_line(number, line[len(SPEAKER) :].strip())
            elif line.startswith(">"):
                self.quote_line(number, line[1:].strip())
            else:
                self.close()
                self.add(number, UNEXPECTED_LINE)
        self.close()
        last = max(len(lines), 1)
        if self.title is None:
            self.add(last, TITLE_LINE.format(doc_id=self.doc_id))
        named = {section.name for section in self.sections}
        for name in FIELDS:
            if name not in named:
                self.add(last, MISSING_SECTION.format(name=name))
        for section in self.sections:
            if not section.none_found and not section.quotes:
                self.add(section.line, EMPTY_SECTION.format(name=section.name))
        quotes = {section.name: tuple(section.quotes or ()) for section in self.sections}
        return Report(self.doc_id, self.title or 1, tuple((name, quotes.get(name, ())) for name in FIELDS))


def parse_report(text: str, doc_id: str) -> tuple[Report, list[Problem]]:
    """The report ``text`` of the document ``doc_id`` (its file's name without ``.md``), and every
    grammar problem in line order. The quotes read so far are returned even when the report
    breaks the grammar, so ``quote_problems`` can check them too."""
    parser = _Parser(doc_id)
    report = parser.read(text)
    return report, sorted(parser.problems, key=lambda problem: problem.line)


def written(name: str, derived: str) -> int | None:
    """Where ``name`` first occurs in ``derived`` spelt as the derived text writes it, or None.

    ``locate`` finds a name by its normalised form, so a name spelt with characters the
    derived text writes otherwise (a ligature such as U+FB03, which it writes as ``ffi``)
    would be found in a spelling the document never shows: such a name is not found. Only
    the whitespace between its words may differ, as where a line break splits the name.
    """
    location = locate(name, derived)
    if location is None or " ".join(derived[location.start : location.end].split()) != name:
        return None
    return location.start


def wording_problems(line: int, name: str) -> list[Problem]:
    """The wording rule on a name the agent writes: no valuation, forecast or advice terms."""
    terms = dict.fromkeys(match.group(0).casefold() for match in WORDING.finditer(name))
    return [Problem(line, WORDING_FOUND.format(terms=", ".join(terms)))] if terms else []


def _turn_problems(quote: Quote, start: int, end: int, turns: Sequence[Turn]) -> list[Problem]:
    """The call rules of a quote located at ``start``-``end``: its speaker, one turn, an executive's."""
    problems: list[Problem] = []
    if quote.speaker is None:
        problems.append(Problem(quote.line, CALL_SPEAKER))
    turn = next((turn for turn in turns if turn.start <= start and end <= turn.end), None)
    if turn is None:
        problems.append(Problem(quote.line, ACROSS_TURNS))
    elif turn.role != EXECUTIVE:
        problems.append(Problem(quote.line, NOT_EXECUTIVE.format(role=turn.role)))
    elif quote.speaker is not None and quote.speaker != turn.speaker:
        problems.append(Problem(quote.speaker_line or quote.line, OTHER_SPEAKER))
    return problems


def quote_problems(
    report: Report, derived: str, *, layout: bool, call: bool, turns: Sequence[Turn] | None = None
) -> list[Problem]:
    """Every rule the report's quotes break against ``derived``, the document's derived text.

    ``layout`` reads its line breaks as whitespace (a ``.txt`` EDGAR document); ``call``
    lets a quote start after its own speaker's label (call documents only); ``turns``, a
    call transcript's turns in ``derived``, holds each quote to the call rules.
    """
    problems: list[Problem] = []
    for _, quote in report.quotes():
        if quote.speaker is not None and quote.speaker_line is not None:
            problems.extend(wording_problems(quote.speaker_line, quote.speaker))
        length = len(normalise(quote.text))
        if not QUOTE_MIN <= length <= QUOTE_MAX:
            problems.append(Problem(quote.line, QUOTE_LENGTH.format(length=length)))
            continue
        location = locate(quote.text, derived)
        if location is None:
            problems.append(Problem(quote.line, QUOTE_NOT_FOUND))
            continue
        if " ".join(derived[location.start : location.end].split()) != " ".join(quote.text.split()):
            problems.append(Problem(quote.line, QUOTE_SPELLING))
            continue
        label = quote.speaker if call else None
        if not sentence_bounded(derived, location.start, location.end, layout=layout, label=label):
            problems.append(Problem(quote.line, NOT_WHOLE))
        if quote.speaker is not None:
            named = written(quote.speaker, derived)
            if named is None or named >= location.start:
                problems.append(Problem(quote.speaker_line or quote.line, SPEAKER_NOT_FOUND))
        if turns is not None:
            problems.extend(_turn_problems(quote, location.start, location.end, turns))
    return sorted(problems, key=lambda problem: problem.line)
