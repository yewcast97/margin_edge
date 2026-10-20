"""Derived text of raw documents, verbatim quote location and whole quotes.

Every research quote is a span of a document's *derived text*: one deterministic
function of the raw bytes, written as ``data/formatted/{T}/{DOC_ID}.md`` by ``text`` and
re-derived from ``raw/`` on every read. Derived text holds no whitespace but ``" "`` and ``"\\n"``:
each line is trimmed, its whitespace runs (NBSP and the other Unicode spaces included)
are single spaces, empty lines are dropped, and non-empty text ends with one ``"\\n"``.
Soft hyphens and zero-width characters are removed and the Latin ligatures expanded, so
a word reads the same however the issuer typeset it; nothing else is folded.

- Filings (HTML and iXBRL): the text a reader sees. A filing whose bytes are not UTF-8
  (stored decoded as Latin-1) is first read as browsers read such a page, as
  windows-1252 (``windows_1252``): its bytes 0x80 to 0x9F are "’", "–", "…" and the other
  characters a reader sees, as a numeric reference such as ``&#146;`` already is, never
  invisible C1 controls. Hidden subtrees (``head``, ``title``,
  ``script``, ``style``, ``noscript``, ``template``, the iXBRL ``ix:header`` and any
  element styled ``display: none``) are dropped; block elements break lines and table
  cells are separated by a space. A hidden element (or one inside a hidden element)
  emits no line break or space either, because it generates no box: a hidden ``div``
  between two words joins them as the page does. The parser never raises on malformed
  markup, and an unclosed element extends to the end of the document.
- Plain text (old ``.txt`` filings and exhibits, and each turn of an earnings call's
  transcript, ``earningscalls.call_text``): the line normalisation only.

``locate`` finds a quote as the agent copied it from the derived text: the quote's
whitespace runs match any whitespace (a quote may cross a line break), letters match
case-sensitively, and smart quotes, dashes and every other character match only
themselves. A quote that starts or ends with a letter, a digit or a combining mark
cannot start or end inside a word. A combining mark (an accent written as a code point
of its own after its letter, "é" written as "e" and U+0301) counts as part of the word,
so a quote never cuts a letter from its accent. Offsets are code-point indices into the
derived text.

``sentence_bounded`` (sentence rule v2) decides whether a located quote is whole
sentences, or whole lines of a document whose lines are its own blocks, so that no quote
cuts a statement. It is a research rule over located quotes, not part of any derivation:
it changes no derived text and no offset. It reads
a line break in one of two modes. In *layout* mode (a plain-text filing's hard wraps) a
line break is ordinary whitespace: such lines are wrapped where the page ran out, as
often inside a sentence as at its end, so they carry no structure and a quote runs from
a sentence start to a sentence end across them. In *block* mode (HTML and iXBRL filings
and exhibits, a call transcript's paragraphs) a line break ends a block: a whole line (a
table row, a bullet, a heading, a paragraph) is a quote of its own unless the next line
starts in lowercase and so continues it. In both modes a quote never starts with a
lowercase letter, after any opening marks and list markers (``BULLETS``: "▪we received…;"
continues its lead-in as the same item does where the page draws its marker with CSS);
it starts at the text's start, at a block's start (block mode), after a sentence end and
whitespace, after a colon that ends a line, or after the colon of its own speaker's label
("Chief Executive Officer: Thank you.") on a line that itself starts where a quote may,
never after any other colon; and it ends at the text's end, at a block's end (block
mode) before a line that does not start in lowercase, or with a sentence end followed by
whitespace and a word that does not start in lowercase, opening marks and list markers
before that word skipped, so "U.S." followed by "market", "$8." cut from "$8.0" and a
lead-in before a lowercase item end no quote. A quote may omit the opening and closing
marks around it, never a list marker it starts after.

The rule sees characters, not grammar. Research must avoid the cases it cannot tell
apart: the full stop of an abbreviation followed by anything that does not start in
lowercase, a capitalised word ("U.S. Government", "2 p.m. PT"), a digit ("2025 vs.
2024", "15 U.S.C. 7262") or an opening mark before a capital ("N.V. (NXP)"), reads as a
sentence end, at a quote's end and before its start; an HTML sentence split across two
blocks whose second part starts with a capital letter (a list item or a lead-in before a
capitalised item among them) reads as two whole lines; in layout mode, a colon inside a
sentence that happens to end a layout line before a capitalised word reads as a
heading's colon; a lowercase list item after a dash or an asterisk, which are no list
markers (they also mark empty table cells, wrapped clauses and footnotes), reads as a
statement of its own; and a speaker label is matched as text, so a clause before an
inline colon at a statement's start, written as the speaker, reads as a label (``check``
passes a label for a call document only, and research writes as a speaker only the name
the document gives). It also refuses some whole statements rather than risk a cut: in a
plain-text filing a sentence after a heading or a running page header without
punctuation can only be quoted with that heading, and a sentence a page header
interrupts only with the header inside it, verbatim; a plain-text table row or bullet
without a full stop only through to the next sentence end; a sentence that starts in
lowercase (a brand such as "iPhone") not from its start; a sentence followed by one that
starts in lowercase, or an HTML line
followed by a heading or glossary term that does ("x86 Architecture"), only together
with it; two sentences joined by a footnote digit set right after the full stop
("website.1 We…") only together, with the digit; an item lettered "(a)" or "(iv)", whose
opening mark is followed by a lowercase letter, not from its start, and the line before
it not up to it; and a lowercase list item only with its lead-in, the lead-in only with
its items. Research checks the rule at a quote's first occurrence, where ``locate`` finds it.

A change to a rule of the derivation changes the derived text of every document it
touches: ``text`` rewrites each text file that differs from its derivation, and ``check``
then refuses every quote the new text no longer holds whole. The derivation also relies
on the standard library's ``html.parser`` and Unicode database, so a Python upgrade that
changes either one has the same effect.
"""

import re
import unicodedata
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Final

# Normalised quote length limits (characters), enforced by check (research.quote_problems).
QUOTE_MIN = 20
QUOTE_MAX = 800
# Sentence ends: a quote starts after one (and whitespace) and may end with one.
SENTENCE_ENDS: Final = frozenset(".!?…")
# Closing marks: they may follow a sentence end, and a quote may keep or omit them.
CLOSERS: Final = frozenset("\"'’”)]}»")
# Opening marks: a quote may keep or omit them at its start.
OPENERS: Final = frozenset("\"'“‘([{«")
# List markers ("▪", "•" and the other glyphs issuers set before a list item, Word's Symbol
# and Wingdings bullets among them): the item's words begin after the marker and the
# whitespace after it, so a marker never hides that an item starts in lowercase. Dashes and
# asterisks are not among them: they also mark empty table cells, wrapped clauses and footnotes.
BULLETS: Final = frozenset("·•‣⁃∙▪▫■□►◆◇◦○●♦✓✔❖➢➤\uf0a7\uf0b7")

# Characters that only affect typesetting: removed. Ligatures: their NFKC expansion.
_CLEAN: dict[int, str | None] = {
    0x00AD: None,  # SOFT HYPHEN
    0x200B: None,  # ZERO WIDTH SPACE
    0x200C: None,  # ZERO WIDTH NON-JOINER
    0x200D: None,  # ZERO WIDTH JOINER
    0x2060: None,  # WORD JOINER
    0xFEFF: None,  # ZERO WIDTH NO-BREAK SPACE (byte order mark)
    0xFB00: "ff",
    0xFB01: "fi",
    0xFB02: "fl",
    0xFB03: "ffi",
    0xFB04: "ffl",
    0xFB05: "st",  # LATIN SMALL LIGATURE LONG S T
    0xFB06: "st",
}
# The characters windows-1252 gives the bytes 0x80-0x9F, by the C1 control Latin-1 gives them.
# The five bytes windows-1252 leaves undefined stay C1 controls, as browsers keep them.
_WINDOWS_1252_UNDEFINED = frozenset({0x81, 0x8D, 0x8F, 0x90, 0x9D})
_WINDOWS_1252 = {
    code: bytes([code]).decode("cp1252") for code in range(0x80, 0xA0) if code not in _WINDOWS_1252_UNDEFINED
}

# HTML elements whose subtree a reader never sees.
_HIDDEN_TAGS = frozenset({"script", "style", "head", "title", "noscript", "template", "ix:header"})
_DISPLAY_NONE = re.compile(r"display\s*:\s*none", re.IGNORECASE)
# Elements without content or end tag; never pushed on the open-element stack.
_VOID_TAGS = frozenset(
    {"area", "base", "br", "col", "embed", "hr", "img"}
    | {"input", "link", "meta", "param", "source", "track", "wbr"}
)
# Elements that start and end a line (``br`` and ``hr`` once, having no end tag).
_BLOCK_TAGS = frozenset(
    {"address", "article", "aside", "blockquote", "body", "br", "caption", "center", "dd", "div", "dl"}
    | {"dt", "fieldset", "figcaption", "figure", "footer", "form", "h1", "h2", "h3", "h4", "h5", "h6"}
    | {"header", "hr", "html", "li", "main", "nav", "ol", "p", "pre", "section", "table", "tbody"}
    | {"tfoot", "thead", "tr", "ul"}
)
# Table cells: separated from their neighbours by a space.
_CELL_TAGS = frozenset({"td", "th"})
_WHITESPACE_RUN = re.compile(r"\s+")
# What remains of derived text that has ended: whitespace only (matched from a position, never copied).
_ONLY_WHITESPACE = re.compile(r"[ \n]*\Z")


def _clean(text: str) -> str:
    return text.translate(_CLEAN)


def windows_1252(body: str) -> str:
    """A document decoded as Latin-1, read as browsers read it: as windows-1252 (WHATWG reads a
    page labelled ISO-8859-1 or Latin-1 that way), so U+0080 to U+009F become "€", "’", "–",
    "…" and the rest; every other character, the five undefined bytes included, is unchanged."""
    return body.translate(_WINDOWS_1252)


def plain_text(body: str) -> str:
    """The derived text of plain text: every kind of line end splits lines, and each line's
    whitespace runs collapse to single spaces; empty lines are dropped."""
    lines = [" ".join(line.split()) for line in _clean(body).splitlines()]
    kept = [line for line in lines if line]
    return "\n".join(kept) + "\n" if kept else ""


class _VisibleText(HTMLParser):
    """Collects the text outside hidden subtrees, with line breaks at block elements."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._stack: list[tuple[str, bool]] = []  # open elements: (tag, hidden)
        self._open: dict[str, int] = {}  # open elements per tag, so an end tag never scans the stack
        self._hidden = 0  # open hidden elements

    def _separate(self, tag: str) -> None:
        if tag in _BLOCK_TAGS:
            self.parts.append("\n")
        elif tag in _CELL_TAGS:
            self.parts.append(" ")

    def _start(self, tag: str, attrs: list[tuple[str, str | None]], *, opens: bool) -> None:
        hidden = tag in _HIDDEN_TAGS or any(
            name == "style" and value is not None and _DISPLAY_NONE.search(value) for name, value in attrs
        )
        if not (hidden or self._hidden):
            self._separate(tag)
        if opens and tag not in _VOID_TAGS:
            self._stack.append((tag, hidden))
            self._open[tag] = self._open.get(tag, 0) + 1
            self._hidden += hidden

    def _pop(self) -> tuple[str, bool]:
        tag, hidden = self._stack.pop()
        self._open[tag] -= 1
        self._hidden -= hidden
        return tag, hidden

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._start(tag, attrs, opens=True)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._start(tag, attrs, opens=False)

    def handle_endtag(self, tag: str) -> None:
        if not self._open.get(tag):
            return  # no open element of that name: ignored
        while True:
            popped, hidden = self._pop()
            if popped == tag:
                break
        if not (hidden or self._hidden):
            self._separate(tag)

    def handle_data(self, data: str) -> None:
        if not self._hidden:
            self.parts.append(_WHITESPACE_RUN.sub(" ", data))


def html_text(body: str) -> str:
    """The derived text of an HTML or iXBRL document: what a reader sees, one block per line."""
    parser = _VisibleText()
    parser.feed(body)
    parser.close()
    return plain_text("".join(parser.parts))


def normalise(quote: str) -> str:
    """A quote as it is checked and located: cleaned like derived text, whitespace runs as single spaces."""
    return " ".join(_clean(quote).split())


@dataclass(frozen=True)
class Location:
    """The first occurrence of a quote, as code-point offsets."""

    start: int
    end: int


def _is_word(character: str) -> bool:
    """A letter or digit (an underscore is not part of a word here), or a combining mark, which
    belongs to the letter before it."""
    return character.isalnum() or unicodedata.category(character).startswith("M")


def locate(quote: str, derived: str) -> Location | None:
    """Where the normalised ``quote`` first occurs in ``derived``, or None.

    A match that a word boundary rules out is skipped, and the search goes on from the next
    character, as a regular expression with the boundaries as lookarounds would.
    """
    normalised = normalise(quote)
    if not normalised:
        return None
    pattern = re.compile(r"\s+".join(re.escape(token) for token in normalised.split(" ")))
    bounded_start, bounded_end = _is_word(normalised[0]), _is_word(normalised[-1])
    position = 0
    while (match := pattern.search(derived, position)) is not None:
        start, end = match.span()
        if (bounded_start and start > 0 and _is_word(derived[start - 1])) or (
            bounded_end and end < len(derived) and _is_word(derived[end])
        ):
            position = start + 1  # inside a word: not an occurrence
            continue
        return Location(start, end)
    return None


def _is_space(character: str, layout: bool) -> bool:
    """Whether ``character`` is whitespace to the sentence rule: a space, and in layout mode a
    line break as well (derived text holds no other whitespace)."""
    return character == " " or (layout and character == "\n")


def _past_marks(derived: str, position: int, limit: int) -> int:
    """The first index from ``position`` (below ``limit``) past opening marks and list markers,
    each marker with the spaces and line breaks after it: where the words themselves begin."""
    while position < limit:
        if derived[position] in OPENERS:
            position += 1
        elif derived[position] in BULLETS:
            position += 1
            while position < limit and derived[position] in " \n":
                position += 1
        else:
            break
    return position


def _first_not_lowercase(derived: str, start: int, end: int) -> bool:
    """Rule 1: the quote's first character after any opening marks and list markers is not
    lowercase.

    A quote that starts in lowercase continues a sentence, as "market" after "U.S.",
    "above" after a wrapped plain-text line or a list item "▪we received…" after its lead-in
    ("…pursuant to the Agreement:") does.
    """
    first = _past_marks(derived, start, end)
    return not (first < end and derived[first].islower())


def _starts_whole(derived: str, start: int, layout: bool, label: str | None) -> bool:
    """Rule 2: ``derived[start:]`` starts at the text's start, at a block's start, after a
    sentence end and whitespace, after a colon that ends a line, or after the colon of
    ``label``'s own line where that line itself starts a statement."""
    i = start
    while i > 0 and derived[i - 1] in OPENERS:
        i -= 1  # a quote may omit its opening marks
    if i == 0 or (not layout and derived[i - 1] == "\n"):
        return True  # the text's start, or a block's start
    spaces_end = i
    while i > 0 and _is_space(derived[i - 1], layout):
        i -= 1
    if i == spaces_end:
        return False  # no whitespace: the quote starts inside a word or right after punctuation
    if i == 0 or (not layout and derived[i - 1] == "\n"):
        return True
    spaces = derived[i:spaces_end]
    while i > 0 and derived[i - 1] in CLOSERS:
        i -= 1
    if i > 0 and derived[i - 1] in SENTENCE_ENDS:
        return True
    if i > 0 and derived[i - 1] == ":":
        colon = i - 1
        # A colon that ends a layout line (a speaker heading "...(bio):"), or the colon of the
        # quote's own speaker label: the label is the whole text of the colon's line before it,
        # and that line starts where a statement may (always at a block's start; in layout mode
        # after the text's start, a sentence end or a line-ending colon, never after a wrap).
        heading = "\n" in spaces
        line = derived.rfind("\n", 0, colon) + 1
        labelled = (
            label is not None
            and derived[line:colon].strip(" ") == label
            and _first_not_lowercase(derived, line, colon)
            and _starts_whole(derived, line, layout, None)
        )
        return heading or labelled
    return False  # inside a sentence: after a word, a comma, an opening mark set apart, or any other colon


def _ends_whole(derived: str, start: int, end: int, layout: bool) -> bool:
    """Rule 3: ``derived[start:end]`` ends at the text's end, at a block's end before a line
    that does not start in lowercase, or with a sentence end before whitespace and a word
    that does not start in lowercase."""
    j = end
    while j < len(derived) and derived[j] in CLOSERS:
        j += 1  # a quote may omit its closing marks
    k = end
    while k > start and derived[k - 1] in CLOSERS:
        k -= 1
    sentence_end = k > start and derived[k - 1] in SENTENCE_ENDS
    # The next visible character: past one block break, whitespace, opening marks and list markers.
    n = j
    if not layout and n < len(derived) and derived[n] == "\n":
        n += 1
    while n < len(derived) and _is_space(derived[n], layout):
        n += 1
    n = _past_marks(derived, n, len(derived))
    if _ONLY_WHITESPACE.match(derived, n):
        return True  # the text ends: nothing but whitespace follows
    if not layout and derived[j] == "\n":
        return not derived[n].islower()  # a block's end, unless the next line continues it
    if _is_space(derived[j], layout):
        return sentence_end and not derived[n].islower()  # a sentence end, not an abbreviation
    return False  # the sentence goes on: a digit after "$8.", a letter, other punctuation


def sentence_bounded(
    derived: str, start: int, end: int, *, layout: bool = False, label: str | None = None
) -> bool:
    """Whether the quote at ``derived[start:end]`` is whole sentences or whole block lines
    (sentence rule v2).

    ``layout`` reads a line break as ordinary whitespace (a plain-text document's hard
    wraps); otherwise a line break ends a block (HTML and iXBRL documents, a call
    transcript's paragraphs). Whitespace is a space, and in layout mode a line break too.
    ``label`` is the quote's speaker, if any.

    1. The first character after any opening marks and list markers (``BULLETS``, each
       with the spaces and line breaks after it) is not lowercase.
    2. The start: opening marks before the quote are skipped (a quote may omit them); then
       it starts at the text's start or, in block mode, at a line start; or after at
       least one whitespace character that follows the text's start, a block line's
       start, or a sentence end (``SENTENCE_ENDS``) and any closing marks; or after such
       whitespace that follows a colon, but only when the whitespace holds a line break
       (a layout line that ends with the colon, as a speaker heading does) or when the
       text of the colon's line before it, stripped of spaces, is exactly ``label`` and
       that line itself starts a quote by rules 1 and 2 without a label (always at a
       block's start; in layout mode after the text's start, a sentence end or a
       line-ending colon).
    3. The end: closing marks after the quote are skipped (a quote may omit them); the
       next visible character is found past one line break in block mode, whitespace,
       then opening marks and list markers (each with the spaces and line breaks after
       it). The quote ends whole when the text ends there; in block mode at a line end
       when the next line does not start in lowercase; and before whitespace when its
       last character before closing marks is a sentence end and the next word does not
       start in lowercase. Anything else (a digit after "$8.", a letter, other
       punctuation) continues the sentence.

    It sees characters, not grammar: an abbreviation before a word that does not start
    in lowercase ("U.S. Government", "2025 vs. 2024"), an HTML sentence split across two
    blocks before a capital letter, in layout mode a colon inside a sentence that ends a
    layout line before a capital letter, a lowercase item after a dash or an asterisk,
    and a clause before an inline colon given as ``label`` still pass, and research must
    not cut a quote there. A research rule over located quotes, not part of any derivation.

    Raises ``ValueError`` unless ``0 <= start <= end <= len(derived)``.
    """
    if not 0 <= start <= end <= len(derived):
        raise ValueError("a quote's offsets must satisfy 0 <= start <= end <= the derived text's length")
    return (
        _first_not_lowercase(derived, start, end)
        and _starts_whole(derived, start, layout, label)
        and _ends_whole(derived, start, end, layout)
    )
