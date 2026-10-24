"""``readings``: the grammar of a comparison's readings file and the rules ``check`` holds it to.

The grammar (G1 to G6) is read from text alone (``parse_readings``). The rules (R0 to R7) are
checked on a real tree: ``workflow_support.research`` fetches, derives and writes the readings
of the window's comparisons once for the module, every aspect ``na``, and each test writes one
draft beside them that breaks one thing, which ``workflow.check`` reads; a test that changes the
tree builds its own. The quote rules (R6) are also held against small derived texts written the
way ``text.py`` derives documents (``quote_problems``). Every expected message is written out,
so a change of wording fails here first.
"""

import itertools
from datetime import date

import pytest

from market_state_research.common.layout import DataLayout
from market_state_research.fundamentals.script import workflow
from market_state_research.fundamentals.script.aspects import ASPECTS
from market_state_research.fundamentals.script.earningscalls import Turn
from market_state_research.fundamentals.script.readings import (
    WORDING,
    Comparison,
    Item,
    Problem,
    Quote,
    Source,
    alike,
    parse_readings,
    quote_problems,
    readings_name,
    readings_problems,
    stated,
    wording_problems,
)

from .calls_support import (
    ANALYST_QUESTION,
    CEO_CAPACITY,
    CEO_DEMAND,
    CFO_GUIDANCE,
    CFO_SUPPLY,
    OPERATOR_QUESTION,
    Q1_DEMAND,
)
from .edgar_support import (
    COMMENTARY_CAPEX,
    RELEASE_CAPEX,
    RELEASE_GUIDANCE,
    TEN_K_CAPEX,
    TEN_K_FINANCING,
    TEN_Q_SUPPLY,
    TICKER,
)
from .support import NOW
from .workflow_support import (
    DOC_IDS,
    QUOTE_CALL,
    QUOTE_FILING,
    WINDOW,
    Reading,
    place,
    readings_text,
    research,
)

OLDEST = date(2024, 12, 28)  # the oldest listed season: no season is listed before it
FY = date(2025, 12, 27)  # the 10-K season: a quarter and a year comparison, no call transcript
Q1 = date(2026, 3, 28)  # a 10-Q season compared with the 10-K season
Q2 = date(2026, 6, 27)  # the 10-Q season most tests read, compared with the quarter ended 2026-03-28
DEFAULT = readings_text(Q2)  # every aspect na
LAST = len(DEFAULT.splitlines())
TITLES = [aspect.title for aspect in ASPECTS]

TITLE = "the first line must be '# INTC · 2026-06-27 · quarter readings'"
DRAFT_TITLE = (
    "the first line must be '# INTC · 2026-06-27 · quarter readings' or '# INTC · 2026-06-27 · year readings'"
)
HEADINGS = (
    "the sections must be the aspects, each once, in this order: '## Guidance', '## Capital expenditure', "
    "'## Upstream supply', '## Downstream demand', '## Debt structure', '## Product roadmap'"
)
OUTSIDE_SECTION = "this line is outside the readings' sections"
SECTION_FORM = "a section is the one line 'na' or its items, each headed '### TITLE'"
EMPTY_SECTION = "the section holds neither 'na' nor an item"
ITEM_TITLE = "an item's title is 1 to 120 printable characters"
REPEATED_TITLE = "another item of this aspect has this title"
ITEM_LINES = (
    "an item's heading is followed by its 'season:', 'new:', 'baseline:', 'old:' and 'difference:' lines, "
    "in that order"
)
UNEXPECTED_LINE = "an item holds its five lines, then '> TEXT' lines each quote ended by its '— DOC_ID' line"
EMPTY_QUOTE_LINE = "an empty '>' line; a quote's lines each hold text"
NO_ATTRIBUTION = "a quote's '>' lines must be followed by its attribution line '— DOC_ID'"
ATTRIBUTION_WITHOUT_QUOTE = "an attribution line must follow a quote's '>' lines"
ATTRIBUTION_TEXT = "an attribution line is '— DOC_ID', or '— DOC_ID, Speaker (role)' for a call's quote"
YEAR_OF_10Q = (
    "only a 10-K season has year readings: a 10-Q season is compared with the season before it alone"
)
QUOTE_SOURCE = "a quote comes from a document the item's 'season:' or 'baseline:' line names"
NONE_VALUE = (
    "'none' is no value: write 'na' when the documents state nothing of the item, or state the fact "
    "itself (no borrowings outstanding)"
)
NO_BASELINE_NEW = "'no baseline' is an old value only"
NOTHING_STATED = (
    "an item states a value on one side at least: an aspect whose documents state nothing of it is 'na'"
)
DIFFERENCE_NA = "the difference is 'na' while a value is 'na' or 'no baseline'"
DIFFERENCE_NOT_NA = "the difference is 'na' only while a value is 'na' or 'no baseline'"
DIFFERENCE_NONE = "the two values are written alike: the difference is 'none'"
DIFFERENCE_NOT_NONE = "the difference is 'none' only when the two values are written alike"
WORDING_FOUND = (
    "an item's title, values and difference state facts only, without valuation, forecast or advice "
    "wording; found: {terms}"
)
NOT_FOUND = "quote not found in the document's derived text"
NOT_WHOLE = (
    "a quote must be whole sentences, or whole lines of an HTML or call document: it must start, never "
    "in lowercase even after a list glyph, at such a line start or after a sentence end or a colon that ends "
    "a line, and end at such a line end or with a sentence end and whitespace, before text that does not "
    "start in lowercase"
)
SPELLING = (
    "the quote is not spelt as the derived text writes it: copy its characters exactly; only the "
    "whitespace between words may differ"
)
CALL_SPEAKER = "a call's quote names its turn: '— DOC_ID, Speaker (role)', as the turn's heading writes it"
ACROSS_TURNS = "a call's quote lies within the words of one turn, below its heading"
NO_SPEAKER = "only a call's quote names a speaker"
REPEATED_QUOTE = "this quote is already given in this item"

# Items of the quarter ended 2026-06-27 against the quarter before, each valid as written.
SUPPLY = Reading(
    "Supply of substrates and specialty chemicals",
    DOC_IDS["ten_q_2"],
    "tight during the quarter ended 2026-06-27",
    DOC_IDS["ten_q_1"],
    "tight during the quarter ended 2026-03-28",
    "the same statement, of the next quarter",
    (QUOTE_FILING, (TEN_Q_SUPPLY[0], DOC_IDS["ten_q_1"])),
)
GUIDANCE = Reading(
    "Next-quarter revenue guidance",
    DOC_IDS["exhibit_2_1"],
    "revenue of $12.6 billion to $13.6 billion for the coming quarter",
    DOC_IDS["exhibit_1"],
    "revenue of $12.6 billion to $13.6 billion for the coming quarter",
    "none",
    ((RELEASE_GUIDANCE[0], DOC_IDS["exhibit_2_1"]), (RELEASE_GUIDANCE[0], DOC_IDS["exhibit_1"])),
)
CAPEX = Reading(
    "Full-year net capital spending",
    DOC_IDS["exhibit_2_2"],
    "approximately $9 billion for the full year",
    DOC_IDS["exhibit_1"],
    "between $8.0 billion and $11.0 billion",
    "a point of approximately $9 billion in place of a range of $8.0 billion to $11.0 billion",
    ((COMMENTARY_CAPEX[0], DOC_IDS["exhibit_2_2"]), (RELEASE_CAPEX[1], DOC_IDS["exhibit_1"])),
)
DEMAND = Reading(
    "Demand on the call",
    DOC_IDS["call_q2"],
    "demand for server processors exceeded supply in the quarter",
    DOC_IDS["call_q1"],
    "data center demand grew faster than planned in the first quarter",
    "the second quarter's call states demand above supply, the first quarter's growth above plan",
    (QUOTE_CALL, (Q1_DEMAND, f"{DOC_IDS['call_q1']}, Lip-Bu Tan (executive)")),
)
# A statement of the baseline the season no longer makes: its new value is na.
ONLY_BEFORE = Reading(
    "Data center demand against plan",
    "none",
    "na",
    DOC_IDS["call_q1"],
    "data center demand grew faster than planned in the first quarter",
    "na",
    ((Q1_DEMAND, f"{DOC_IDS['call_q1']}, Lip-Bu Tan (executive)"),),
)


def parsed(text: str, season: date = Q2, kind: str | None = "quarter") -> list[tuple[int, str]]:
    """The grammar problems of ``text`` as ``season``'s readings of ``kind`` (None: a draft)."""
    _, found = parse_readings(text, TICKER, season, kind)  # type: ignore[arg-type]
    return [(problem.line, problem.message) for problem in found]


def line_of(text: str, start: str, after: int = 0) -> int:
    """The number of the first line of ``text`` after line ``after`` that starts with ``start``."""
    return next(
        number
        for number, line in enumerate(text.splitlines(), start=1)
        if number > after and line.startswith(start)
    )


def label_line(text: str, title: str, label: str) -> int:
    """The line of ``label`` in the item ``title`` of ``text``."""
    return line_of(text, f"{label}:", line_of(text, f"### {title}"))


def missing(title: str) -> str:
    return f"the section '## {title}' is missing"


def section_of(text: str, title: str) -> str:
    """The section ``## title`` of ``text``, up to the next section's heading."""
    start = text.index(f"## {title}\n")
    following = text.find("\n## ", start + 1)
    return text[start : len(text) if following < 0 else following + 1]


def item(title: str = "Substrates", **lines: str) -> str:
    """An item's lines, each ``none`` or ``na`` but those ``lines`` gives."""
    values = {"season": "none", "new": "na", "baseline": "none", "old": "na", "difference": "na", **lines}
    return "\n".join([f"### {title}", *(f"{label}: {value}" for label, value in values.items())])


def with_items(*items: str, title: str = "Upstream supply") -> str:
    return DEFAULT.replace(f"## {title}\n\nna\n", f"## {title}\n\n" + "\n\n".join(items) + "\n")


# --------------------------------------------------------------------------- grammar


def test_readings_of_six_na_sections_parse_into_the_aspects():
    readings, found = parse_readings(DEFAULT, TICKER, Q2, "quarter")

    assert found == []
    assert (readings.kind, readings.title_line) == ("quarter", 1)
    assert [section.aspect.title for section in readings.sections] == TITLES
    assert [(section.line, section.na, section.items) for section in readings.sections] == [
        (3 + 4 * index, 5 + 4 * index, ()) for index in range(6)
    ]
    assert LAST == 2 + 4 * 6 - 1  # the title, a blank line, then a heading, a blank, na and a blank each
    assert readings.items == ()


def test_items_parse_with_every_line_and_quote():
    text = readings_text(Q2, supply=[SUPPLY], demand=[DEMAND, ONLY_BEFORE])
    heading = line_of(text, f"### {SUPPLY.title}")

    readings, found = parse_readings(text, TICKER, Q2, "quarter")

    assert found == []
    supply = readings.section("supply")
    assert supply is not None and supply.na == 0
    (item,) = supply.items
    assert item == Item(
        SUPPLY.title,
        heading,
        (DOC_IDS["ten_q_2"],),
        "tight during the quarter ended 2026-06-27",
        (DOC_IDS["ten_q_1"],),
        "tight during the quarter ended 2026-03-28",
        "the same statement, of the next quarter",
        (
            Quote(heading + 6, TEN_Q_SUPPLY[0], DOC_IDS["ten_q_2"], None, heading + 7),
            Quote(heading + 8, TEN_Q_SUPPLY[0], DOC_IDS["ten_q_1"], None, heading + 9),
        ),
        heading + 1,
        heading + 2,
        heading + 3,
        heading + 4,
        heading + 5,
    )
    assert [(aspect.key, entry.title) for aspect, entry in readings.items] == [
        ("supply", SUPPLY.title),
        ("demand", DEMAND.title),
        ("demand", ONLY_BEFORE.title),
    ]
    only = readings.items[2][1]
    assert (only.season, only.new, only.baseline, only.difference) == ((), "na", (DOC_IDS["call_q1"],), "na")
    assert readings.items[1][1].quotes[0].speaker == "Lip-Bu Tan (executive)"
    assert readings.section("guidance") is not None and readings.section("guidance").na == 5  # type: ignore[union-attr]


def test_a_quotes_lines_are_joined_by_one_space_and_blank_lines_may_separate_quotes():
    block = (
        "> Supply of substrates and certain specialty\n"
        ">  chemicals remained\ttight during the quarter.  \n"
        f"— {DOC_IDS['ten_q_2']}\n"
        "\n"
        f"> {TEN_Q_SUPPLY[0]}\n"
        f"— {DOC_IDS['ten_q_1']}\n"
    )
    item = Reading(SUPPLY.title, SUPPLY.season, SUPPLY.new, SUPPLY.baseline, SUPPLY.old, SUPPLY.difference)
    text = readings_text(Q2, supply=[item]).replace(
        f"difference: {SUPPLY.difference}\n", f"difference: {SUPPLY.difference}\n{block}"
    )
    first = line_of(text, "> Supply of substrates")

    readings, found = parse_readings(text, TICKER, Q2, "quarter")

    assert found == []
    assert readings.items[0][1].quotes == (
        Quote(first, TEN_Q_SUPPLY[0], DOC_IDS["ten_q_2"], None, first + 2),
        Quote(first + 4, TEN_Q_SUPPLY[0], DOC_IDS["ten_q_1"], None, first + 5),
    )


def test_blank_lines_before_the_title_trailing_spaces_and_crlf_are_accepted():
    text = "\n\n" + readings_text(Q2, supply=[SUPPLY]).replace("\n", "  \r\n")

    readings, found = parse_readings(text, TICKER, Q2, "quarter")

    assert found == []
    assert (readings.title_line, readings.sections[0].line, readings.items[0][1].new) == (3, 5, SUPPLY.new)


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("# INTC · 2026-03-28 · quarter readings", [(1, TITLE)]),
        ("# AMD · 2026-06-27 · quarter readings", [(1, TITLE)]),
        ("# INTC · 2026-06-27 · year readings", [(1, TITLE)]),
        ("# INTC · 2026-06-27 · readings", [(1, TITLE)]),
        ("# INTC - 2026-06-27 - quarter readings", [(1, TITLE)]),
        ("#INTC · 2026-06-27 · quarter readings", [(1, TITLE), (1, OUTSIDE_SECTION)]),  # read as a body line
    ],
    ids=["other-season", "other-ticker", "other-kind", "no-kind", "hyphens", "no-space"],
)
def test_the_title_names_the_ticker_the_season_and_the_comparison(title, expected):
    assert parsed(DEFAULT.replace("# INTC · 2026-06-27 · quarter readings", title, 1)) == expected


def test_a_draft_is_read_as_the_comparison_its_title_names():
    year = readings_text(Q2, "year")

    readings, found = parse_readings(year, TICKER, Q2)

    assert (readings.kind, found) == ("year", [])
    assert parse_readings(DEFAULT, TICKER, Q2)[0].kind == "quarter"
    other = DEFAULT.replace("quarter readings", "half-year readings", 1)
    readings, found = parse_readings(other, TICKER, Q2)
    assert readings.kind == "quarter"
    assert [(problem.line, problem.message) for problem in found] == [(1, DRAFT_TITLE)]


def test_readings_without_their_title_read_their_first_line_as_a_section():
    without = DEFAULT.removeprefix("# INTC · 2026-06-27 · quarter readings\n\n")

    readings, found = parse_readings(without, TICKER, Q2, "quarter")

    assert [(problem.line, problem.message) for problem in found] == [(1, TITLE)]
    assert [section.aspect.title for section in readings.sections] == TITLES


def test_a_line_before_any_section_is_outside_the_sections():
    text = DEFAULT.replace("readings\n\n", "readings\nA line before the sections.\n### An item\n", 1)

    assert parsed(text) == [(2, OUTSIDE_SECTION), (3, OUTSIDE_SECTION)]


def test_empty_readings_lack_their_title_and_every_section():
    assert parsed("") == [(1, TITLE), *((1, missing(title)) for title in TITLES)]
    assert parsed("\n\n\n") == [(3, TITLE), *((3, missing(title)) for title in TITLES)]


def test_sections_out_of_order_are_reported_once_and_still_read():
    first, second = section_of(DEFAULT, "Guidance"), section_of(DEFAULT, "Capital expenditure")
    swapped = DEFAULT.replace(first + second, second + first)

    readings, found = parse_readings(swapped, TICKER, Q2, "quarter")

    assert [(problem.line, problem.message) for problem in found] == [
        (line_of(swapped, "## Guidance"), HEADINGS)
    ]
    assert [section.aspect.key for section in readings.sections][:3] == ["capex", "guidance", "supply"]


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        (lambda text: text + "\n## Guidance\n\nna\n", [(LAST + 2, HEADINGS)]),
        (
            lambda text: text.replace("## Upstream supply", "## Supply"),
            [(11, HEADINGS), (LAST, missing("Upstream supply"))],
        ),
        (
            lambda text: text.replace(
                "## Debt structure\n\nna\n", "## Liquidity\n\n### Cash\nseason: none\n"
            ),
            [(19, HEADINGS), (LAST + 1, missing("Debt structure"))],
        ),
    ],
    ids=["repeated", "renamed", "unknown-with-an-item"],
)
def test_an_unknown_or_repeated_section_is_refused_and_its_lines_skipped(change, expected):
    assert parsed(change(DEFAULT)) == expected


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ("na\n\nna", [(2, SECTION_FORM)]),
        ("A line of text.", [(-2, EMPTY_SECTION), (0, SECTION_FORM)]),
        ("", [(-2, EMPTY_SECTION)]),
        ("na\n\n" + item("x"), [(2, SECTION_FORM)]),
    ],
    ids=["na-twice", "text", "empty", "na-and-an-item"],
)
def test_a_section_is_na_or_its_items(body, expected):
    text = DEFAULT.replace("## Upstream supply\n\nna\n", f"## Upstream supply\n\n{body}\n")
    start = line_of(text, "## Upstream supply") + 2

    assert parsed(text) == [(start + offset, message) for offset, message in expected]


def test_na_after_an_item_breaks_the_section():
    text = DEFAULT.replace("## Debt structure\n\nna\n", f"## Debt structure\n\n{item('Cash')}\nna\n")

    assert parsed(text) == [(line_of(text, "na", line_of(text, "### Cash")), SECTION_FORM)]


@pytest.mark.parametrize(
    ("lines", "expected"),
    [
        (
            "new: na\nseason: none\nbaseline: none\nold: na\ndifference: na",
            [(1, ITEM_LINES), *((offset, UNEXPECTED_LINE) for offset in range(2, 6))],
        ),
        ("season: none\nnew: na\nold: na\ndifference: na", [(3, ITEM_LINES), (4, UNEXPECTED_LINE)]),
        ("season: none\nnew: na\nbaseline: none\nold: na", [(0, ITEM_LINES)]),
        ("", [(0, ITEM_LINES)]),
        (f"> {TEN_Q_SUPPLY[0]}\n— {DOC_IDS['ten_q_2']}", [(1, ITEM_LINES)]),
    ],
    ids=["new-first", "no-baseline-line", "no-difference-line", "heading-alone", "quote-first"],
)
def test_an_item_holds_its_five_lines_in_order(lines, expected):
    text = DEFAULT.replace("## Upstream supply\n\nna\n", f"## Upstream supply\n\n### Substrates\n{lines}\n")
    heading = line_of(text, "### Substrates")

    assert parsed(text) == [(heading + offset, message) for offset, message in expected]


@pytest.mark.parametrize(
    ("titles", "expected"),
    [
        (("x" * 121,), [(0, ITEM_TITLE)]),
        (("Two\tcolumns",), [(0, ITEM_TITLE)]),
        (("Substrates", "SUBSTRATES"), [(7, REPEATED_TITLE)]),
    ],
    ids=["121-characters", "tab", "repeated-letter-case-aside"],
)
def test_an_items_title_is_1_to_120_printable_characters_once_per_aspect(titles, expected):
    text = with_items(*(item(title) for title in titles))
    heading = line_of(text, "### ")

    assert parsed(text) == [(heading + offset, message) for offset, message in expected]


def test_a_title_of_120_characters_passes_and_two_aspects_may_share_one():
    text = with_items(item("x" * 120), item("Substrates", season=DOC_IDS["ten_q_2"]))
    text = text.replace("## Debt structure\n\nna\n", f"## Debt structure\n\n{item()}\n")

    assert parsed(text) == []


@pytest.mark.parametrize(
    "value",
    ["", "A, B", "A;  B", "A ;B", "A; A", f"{DOC_IDS['ten_q_1']} ; {DOC_IDS['exhibit_1']}"],
    ids=["empty", "commas", "two-spaces", "space-before", "repeated", "spaced"],
)
@pytest.mark.parametrize("label", ["season", "baseline"])
def test_a_documents_line_is_none_or_distinct_doc_ids_joined_by_a_semicolon_and_a_space(label, value):
    text = with_items(item(**{label: value}))

    assert parsed(text) == [
        (
            label_line(text, "Substrates", label),
            f"the '{label}:' line must be 'none' or distinct DOC_IDs joined by '; '",
        )
    ]


def test_documents_lines_are_read_in_their_order():
    text = with_items(
        item(season=f"{DOC_IDS['exhibit_2_1']}; {DOC_IDS['ten_q_2']}", baseline=DOC_IDS["ten_q_1"])
    )

    readings, found = parse_readings(text, TICKER, Q2, "quarter")

    assert found == []
    assert (readings.items[0][1].season, readings.items[0][1].baseline) == (
        (DOC_IDS["exhibit_2_1"], DOC_IDS["ten_q_2"]),
        (DOC_IDS["ten_q_1"],),
    )


@pytest.mark.parametrize(
    "value",
    ["", "x" * 601, "Two\tcolumns.", "A zero​width space."],
    ids=["empty", "601-characters", "tab", "zero-width-space"],
)
@pytest.mark.parametrize("label", ["new", "old", "difference"])
def test_a_value_is_1_to_600_printable_characters(label, value):
    text = with_items(item(**{label: value}))

    assert parsed(text) == [
        (
            label_line(text, "Substrates", label),
            f"the '{label}:' line must hold 1 to 600 printable characters",
        )
    ]


def test_values_of_600_characters_pass_without_their_outer_spaces():
    text = with_items(item(new="  " + "x" * 600 + "  ", old=" " + "y" * 600, difference="z" * 600 + " "))

    readings, found = parse_readings(text, TICKER, Q2, "quarter")

    entry = readings.items[0][1]
    assert (found, entry.new, entry.old, entry.difference) == ([], "x" * 600, "y" * 600, "z" * 600)


@pytest.mark.parametrize("value", ["orange", "none", "no baseline", "na", "—"])
def test_the_grammar_reads_any_printable_text_as_a_value(value):
    text = with_items(item(new=value, old=value, difference=value))

    readings, found = parse_readings(text, TICKER, Q2, "quarter")

    entry = readings.items[0][1]
    assert (found, entry.new, entry.old, entry.difference) == ([], value, value, value)


QUOTE = f"> {TEN_Q_SUPPLY[0]}"
ATTRIBUTION = f"— {DOC_IDS['ten_q_2']}"


@pytest.mark.parametrize(
    ("block", "expected"),
    [
        (
            f"> Supply of substrates and certain specialty\n>\n> chemicals remained tight.\n{ATTRIBUTION}",
            [(1, EMPTY_QUOTE_LINE)],
        ),
        (QUOTE, [(0, NO_ATTRIBUTION)]),
        (ATTRIBUTION, [(0, ATTRIBUTION_WITHOUT_QUOTE)]),
        (f"{ATTRIBUTION}\n{QUOTE}\n{ATTRIBUTION}", [(0, ATTRIBUTION_WITHOUT_QUOTE)]),
        ("A note on the reading.", [(0, UNEXPECTED_LINE)]),
        (f"{QUOTE}\nA note on the quote.", [(0, NO_ATTRIBUTION), (1, UNEXPECTED_LINE)]),
        (f"{QUOTE}\n{ATTRIBUTION}\nnew: Again.", [(2, UNEXPECTED_LINE)]),
        ("- a list item", [(0, UNEXPECTED_LINE)]),
    ],
    ids=[
        "empty-quote-line",
        "no-attribution",
        "attribution-alone",
        "attribution-first",
        "free-text",
        "quote-then-text",
        "second-value",
        "list-item",
    ],
)
def test_after_its_five_lines_an_item_holds_quotes_each_ended_by_its_attribution(block, expected):
    text = with_items(item() + "\n" + block)
    start = label_line(text, "Substrates", "difference") + 1

    assert parsed(text) == [(start + offset, message) for offset, message in expected]


def test_an_attribution_line_is_a_dash_a_space_and_its_doc_id():
    text = with_items(item() + f"\n{QUOTE}\n—{DOC_IDS['ten_q_2']}")

    assert parsed(text) == [(line_of(text, "—"), ATTRIBUTION_TEXT)]


def test_problems_come_in_line_order_and_the_items_read_are_still_returned():
    text = with_items(item(new="x" * 601) + f"\n{QUOTE}\n{ATTRIBUTION}")
    text = text.replace("# INTC · 2026-06-27 · quarter readings", "# INTC", 1).replace(
        "## Downstream demand\n\nna", "## Downstream demand\n\nA stray line."
    )

    readings, found = parse_readings(text, TICKER, Q2, "quarter")

    assert [(problem.line, problem.message) for problem in found] == [
        (1, TITLE),
        (label_line(text, "Substrates", "new"), "the 'new:' line must hold 1 to 600 printable characters"),
        (line_of(text, "## Downstream demand"), EMPTY_SECTION),
        (line_of(text, "A stray line."), SECTION_FORM),
    ]
    entry = readings.items[0][1]
    assert (entry.new, [quote.text for quote in entry.quotes]) == ("x" * 601, [TEN_Q_SUPPLY[0]])


def test_the_helpers_read_values_alike_and_stated():
    assert alike("$20  billion in 2026", "$20 billion in\t2026")
    assert not alike("$20 billion", "$20.0 billion")
    assert [stated(value) for value in ("na", "no baseline", None, "none", "tight")] == [
        False,
        False,
        False,
        True,
        True,
    ]
    assert (readings_name("quarter"), readings_name("year")) == ("readings_quarter.md", "readings_year.md")


# --------------------------------------------------------------------------- the rules, on a real tree

DRAFTS = itertools.count()


@pytest.fixture(scope="module")
def tree(tmp_path_factory) -> DataLayout:
    """One researched tree for the module's checks, each writing its own draft and nothing else."""
    layout = DataLayout(tmp_path_factory.mktemp("readings") / "data")
    research(layout)
    return layout


def draft(layout: DataLayout, content: str | bytes, season: date = Q2) -> dict:
    """``check``'s verdict on ``content`` written as a draft in ``season``'s folder."""
    path = place(layout.reports(TICKER) / season.isoformat() / f"draft_{next(DRAFTS)}.md", content)
    (found,) = workflow.check(layout, TICKER, NOW, [path])["readings"]
    return found


def checked(layout: DataLayout, text: str, season: date = Q2) -> list[tuple[int, str]]:
    """The problems ``check`` finds in ``text`` as a draft of ``season``'s readings."""
    return [(problem["line"], problem["message"]) for problem in draft(layout, text, season)["problems"]]


def test_the_readings_of_every_window_comparison_pass(tree):
    output = workflow.check(tree, TICKER, NOW)

    assert [
        (found["season"], found["kind"], found["valid"], found["problems"]) for found in output["readings"]
    ] == [
        ("2025-12-27", "quarter", True, []),
        ("2025-12-27", "year", True, []),
        ("2026-03-28", "quarter", True, []),
        ("2026-06-27", "quarter", True, []),
    ]


def test_items_of_every_kind_quoted_from_both_sides_and_any_speaker_pass(tree):
    operator = (OPERATOR_QUESTION, f"{DOC_IDS['call_q2']}, Operator (operator)")
    analyst = (ANALYST_QUESTION, f"{DOC_IDS['call_q2']}, Jane Analyst (analyst)")
    cfo = (CFO_SUPPLY, f"{DOC_IDS['call_q2']}, David Zinsner (executive)")
    call_supply = Reading(
        "Substrate supply on the call",
        DOC_IDS["call_q2"],
        "substrate supply tight, limiting shipments",
        quotes=(operator, analyst, cfo),
    )
    text = readings_text(
        Q2,
        guidance=[GUIDANCE],
        capex=[CAPEX],
        supply=[SUPPLY, call_supply],
        demand=[DEMAND, ONLY_BEFORE],
    )

    assert checked(tree, text) == []


def test_the_year_readings_of_a_10_k_season_compare_it_with_the_previous_10_k(tree):
    capex = Reading(
        "Capital expenditures planned for 2026",
        DOC_IDS["ten_k"],
        "approximately $20 billion in 2026, mainly for new process nodes",
        DOC_IDS["old_ten_k"],
        "approximately $20 billion  in 2026, mainly for new process nodes",
        "none",
        ((TEN_K_CAPEX[0], DOC_IDS["ten_k"]), (TEN_K_CAPEX[0], DOC_IDS["old_ten_k"])),
    )
    debt = Reading(
        "Funding of the expansion",
        DOC_IDS["ten_k"],
        "cash from operations, senior notes and an Arizona partner's contributions",
        quotes=((TEN_K_FINANCING[0], DOC_IDS["ten_k"]),),
    )

    assert checked(tree, readings_text(FY, "year", capex=[capex], debt=[debt]), FY) == []
    # Against the quarter before it, the 10-K season's baseline is the 10-Q of 2025-09-27.
    quarter = readings_text(FY, capex=[capex])
    assert checked(tree, quarter, FY) == [
        (
            label_line(quarter, capex.title, "baseline"),
            f"{DOC_IDS['old_ten_k']} is no document of the baseline season 2025-09-27",
        )
    ]


def test_a_byte_order_mark_crlf_line_ends_and_trailing_spaces_are_accepted(tree):
    text = readings_text(Q2, supply=[SUPPLY])

    found = draft(tree, b"\xef\xbb\xbf" + text.replace("\n", "  \r\n").encode("utf-8"))

    assert (found["kind"], found["valid"], found["problems"]) == ("quarter", True, [])


def test_readings_that_are_not_utf_8_are_one_problem_on_line_1(tree):
    found = draft(tree, DEFAULT.encode("utf-16"))

    assert found["kind"] is None
    assert found["problems"] == [
        {
            "line": 1,
            "message": "the readings cannot be read: 'utf-8' codec can't decode byte 0xff in position 0: "
            "invalid start byte",
        }
    ]


def test_a_draft_names_its_season_by_its_folder_and_the_season_must_be_listed(tree):
    path = place(tree.reports(TICKER) / "2026-09-26" / "draft.md", readings_text(Q2))

    with pytest.raises(ValueError) as refused:
        workflow.check(tree, TICKER, NOW, [path])

    assert str(refused.value) == f"{path}: no season of the newest submissions ends on 2026-09-26"


# R0: year readings are a 10-K season's only.


def test_year_readings_of_a_10_q_season_are_refused(tree):
    text = readings_text(Q2, "year", supply=[SUPPLY])

    found = draft(tree, text)

    assert (found["kind"], found["problems"]) == ("year", [{"line": 1, "message": YEAR_OF_10Q}])


def test_a_10_q_seasons_year_readings_file_is_checked_and_refused(layout):
    research(layout)
    stray = place(layout.reports(TICKER) / "2026-03-28" / "readings_year.md", readings_text(Q1, "year"))

    output = workflow.check(layout, TICKER, NOW)

    year = next(found for found in output["readings"] if found["path"] == str(stray))
    assert (year["season"], year["kind"], year["valid"], year["problems"]) == (
        "2026-03-28",
        "year",
        False,
        [{"line": 1, "message": YEAR_OF_10Q}],
    )
    assert workflow.plan(layout, [TICKER], NOW, WINDOW)["tickers"][0]["action"] == "render"


# R1: every DOC_ID named is a document in raw/ whose text file equals its derivation.


def test_a_doc_id_that_is_no_document_in_raw_is_refused(tree):
    unknown = "10-Q_2026-06-27_0000050863-26-000064_intc-20260628"
    entry = Reading(
        "Substrates",
        f"{DOC_IDS['ten_q_2']}; {unknown}",
        SUPPLY.new,
        quotes=(QUOTE_FILING, (TEN_Q_SUPPLY[0], unknown)),
    )
    text = readings_text(Q2, supply=[entry])
    message = f"{unknown} is no document in raw/ (a DOC_ID of a text file in formatted/)"

    assert checked(tree, text) == [
        (label_line(text, "Substrates", "season"), message),
        (line_of(text, f"— {unknown}"), message),
    ]


def test_a_document_whose_text_file_is_stale_or_missing_is_refused(layout):
    research(layout)
    stale = layout.formatted(TICKER) / "2026-03-28" / f"{DOC_IDS['exhibit_1']}.md"
    stale.write_text(stale.read_text(encoding="utf-8") + "A line derive never writes.\n", encoding="utf-8")
    (layout.formatted(TICKER) / "2026-06-27" / f"{DOC_IDS['exhibit_2_2']}.md").unlink()
    text = readings_text(Q2, capex=[CAPEX])

    commentary, release = (
        f"the text file of {DOC_IDS[role]} is missing or differs from its derivation; run derive"
        for role in ("exhibit_2_2", "exhibit_1")
    )
    assert checked(layout, text) == [
        (label_line(text, CAPEX.title, "season"), commentary),
        (label_line(text, CAPEX.title, "baseline"), release),
        (line_of(text, f"— {DOC_IDS['exhibit_2_2']}"), commentary),
        (line_of(text, f"— {DOC_IDS['exhibit_1']}"), release),
    ]


# R2: the season line names the season's documents only, the baseline line the baseline's.


@pytest.mark.parametrize(
    ("season", "entry", "label", "message"),
    [
        (
            Q2,
            Reading(
                "Substrates", DOC_IDS["ten_q_1"], SUPPLY.new, quotes=((TEN_Q_SUPPLY[0], DOC_IDS["ten_q_1"]),)
            ),
            "season",
            f"{DOC_IDS['ten_q_1']} is no document of the season 2026-06-27",
        ),
        (
            Q2,
            Reading(
                "Substrates",
                baseline=DOC_IDS["ten_k"],
                old="tight in the fiscal year",
                quotes=((TEN_K_CAPEX[0], DOC_IDS["ten_k"]),),
            ),
            "baseline",
            f"{DOC_IDS['ten_k']} is no document of the baseline season 2026-03-28",
        ),
        (
            Q1,
            Reading(
                "Substrates",
                baseline=DOC_IDS["ten_q_2"],
                old="tight in the second quarter",
                quotes=(QUOTE_FILING,),
            ),
            "baseline",
            f"{DOC_IDS['ten_q_2']} is no document of the baseline season 2025-12-27",
        ),
    ],
    ids=["baseline-document-as-the-seasons", "older-season", "later-season"],
)
def test_each_line_names_its_own_sides_documents(tree, season, entry, label, message):
    text = readings_text(season, supply=[entry])

    assert checked(tree, text, season) == [(label_line(text, "Substrates", label), message)]


# R3: a stated value names the documents it rests on, each quoted; na stands with none.


@pytest.mark.parametrize(
    ("entry", "label", "message"),
    [
        (
            Reading("Substrates", "none", SUPPLY.new),
            "season",
            "the new value is stated: 'season:' names the documents it rests on",
        ),
        (
            Reading("Substrates", "none", "na", "none", SUPPLY.old),
            "baseline",
            "the old value is stated: 'baseline:' names the documents it rests on",
        ),
        (
            Reading(
                "Substrates", DOC_IDS["ten_q_2"], "na", DOC_IDS["ten_q_1"], SUPPLY.old, quotes=SUPPLY.quotes
            ),
            "season",
            "'season:' is 'none' while the new value is 'na'",
        ),
        (
            Reading(
                "Substrates", DOC_IDS["ten_q_2"], SUPPLY.new, DOC_IDS["ten_q_1"], "na", quotes=SUPPLY.quotes
            ),
            "baseline",
            "'baseline:' is 'none' while the old value is 'na'",
        ),
    ],
    ids=["new-without-documents", "old-without-documents", "documents-of-na-new", "documents-of-na-old"],
)
def test_a_documents_line_is_none_exactly_beside_a_value_that_is_na(tree, entry, label, message):
    text = readings_text(Q2, supply=[entry])

    assert checked(tree, text) == [(label_line(text, "Substrates", label), message)]


def test_every_document_a_line_names_is_quoted_in_the_item(tree):
    entry = Reading(
        "Substrates",
        f"{DOC_IDS['ten_q_2']}; {DOC_IDS['exhibit_2_1']}",
        SUPPLY.new,
        DOC_IDS["ten_q_1"],
        SUPPLY.old,
        SUPPLY.difference,
        (QUOTE_FILING,),
    )
    text = readings_text(Q2, supply=[entry])

    assert checked(tree, text) == [
        (
            label_line(text, "Substrates", "season"),
            f"{DOC_IDS['exhibit_2_1']} is named on this line but quoted nowhere in this item",
        ),
        (
            label_line(text, "Substrates", "baseline"),
            f"{DOC_IDS['ten_q_1']} is named on this line but quoted nowhere in this item",
        ),
    ]


@pytest.mark.parametrize(("new", "old", "label"), [("none", SUPPLY.old, "new"), (SUPPLY.new, "none", "old")])
def test_none_is_no_value(tree, new, old, label):
    entry = Reading("Substrates", SUPPLY.season, new, SUPPLY.baseline, old, SUPPLY.difference, SUPPLY.quotes)
    text = readings_text(Q2, supply=[entry])

    assert checked(tree, text) == [(label_line(text, "Substrates", label), NONE_VALUE)]


# R4: no baseline, an old value only, exactly while the baseline is not in raw/; an item states a
# value on one side at least.


def test_no_baseline_while_the_baseline_is_in_raw_is_refused(tree):
    q2 = readings_text(
        Q2,
        supply=[
            Reading("Substrates", DOC_IDS["ten_q_2"], SUPPLY.new, old="no baseline", quotes=(QUOTE_FILING,))
        ],
    )
    fy = readings_text(
        FY,
        capex=[
            Reading(
                "Capex",
                DOC_IDS["ten_k"],
                "approximately $20 billion",
                old="no baseline",
                quotes=((TEN_K_CAPEX[0], DOC_IDS["ten_k"]),),
            )
        ],
    )

    assert checked(tree, q2) == [
        (
            label_line(q2, "Substrates", "old"),
            f"'no baseline' while the baseline is in raw/: {DOC_IDS['ten_q_1']}, {DOC_IDS['eight_k_1']}, "
            f"{DOC_IDS['exhibit_1']} ...",
        )
    ]
    assert checked(tree, fy, FY) == [
        (
            label_line(fy, "Capex", "old"),
            f"'no baseline' while the baseline is in raw/: {DOC_IDS['old_ten_q']}, {DOC_IDS['call_old_q']}",
        )
    ]


def test_without_a_listed_baseline_season_every_old_value_is_no_baseline(tree):
    capex = Reading(
        "Capex",
        DOC_IDS["old_ten_k"],
        "approximately $20 billion",
        old="no baseline",
        quotes=((TEN_K_CAPEX[0], DOC_IDS["old_ten_k"]),),
    )
    passing = readings_text(OLDEST, capex=[capex])
    failing = readings_text(
        OLDEST, "year", capex=[Reading("Capex", capex.season, capex.new, quotes=capex.quotes)]
    )

    assert checked(tree, passing, OLDEST) == []
    assert checked(tree, failing, OLDEST) == [
        (
            label_line(failing, "Capex", "old"),
            "the old value is 'no baseline' while the baseline is not in raw/ (no baseline season is listed)",
        )
    ]


def test_no_baseline_is_never_a_new_value_and_an_item_states_one_side_at_least(tree):
    new = readings_text(
        Q2,
        supply=[
            Reading(
                "Substrates",
                "none",
                "no baseline",
                DOC_IDS["ten_q_1"],
                SUPPLY.old,
                "na",
                ((TEN_Q_SUPPLY[0], DOC_IDS["ten_q_1"]),),
            )
        ],
    )
    nothing = readings_text(Q2, supply=[Reading("Substrates")])

    assert checked(tree, new) == [(label_line(new, "Substrates", "new"), NO_BASELINE_NEW)]
    assert checked(tree, nothing) == [(line_of(nothing, "### Substrates"), NOTHING_STATED)]


# R5: the difference is na beside a status, none exactly when the values are written alike.


@pytest.mark.parametrize(
    ("entry", "message"),
    [
        (
            Reading("Capex", DOC_IDS["exhibit_2_2"], CAPEX.new, difference="none", quotes=(CAPEX.quotes[0],)),
            DIFFERENCE_NA,
        ),
        (
            Reading("Capex", "none", "na", DOC_IDS["exhibit_1"], CAPEX.old, "lower", (CAPEX.quotes[1],)),
            DIFFERENCE_NA,
        ),
        (
            Reading("Capex", CAPEX.season, CAPEX.new, CAPEX.baseline, CAPEX.old, "na", CAPEX.quotes),
            DIFFERENCE_NOT_NA,
        ),
        (
            Reading("Capex", CAPEX.season, CAPEX.new, CAPEX.baseline, CAPEX.old, "none", CAPEX.quotes),
            DIFFERENCE_NOT_NONE,
        ),
        (
            Reading(
                "Capex", CAPEX.season, CAPEX.new, CAPEX.baseline, CAPEX.new, "a different range", CAPEX.quotes
            ),
            DIFFERENCE_NONE,
        ),
    ],
    ids=["status-new", "status-old", "na-between-values", "none-between-different-values", "alike-values"],
)
def test_the_difference_is_na_none_or_facts_as_the_values_require(tree, entry, message):
    text = readings_text(Q2, capex=[entry])

    assert checked(tree, text) == [(label_line(text, "Capex", "difference"), message)]


def test_values_alike_but_for_their_whitespace_have_no_difference(tree):
    entry = Reading(
        "Capex", CAPEX.season, CAPEX.new, CAPEX.baseline, CAPEX.new.replace(" ", "  "), "none", CAPEX.quotes
    )

    assert checked(tree, readings_text(Q2, capex=[entry])) == []


# R6: a quote comes from a document a line of its item names, 20 to 800 characters, verbatim,
# whole sentences or lines; a call's quote names its turn's heading exactly; none is repeated.

CALL_ID = DOC_IDS["call_q2"]


def test_a_quote_comes_from_a_document_its_items_lines_name(tree):
    entry = Reading(
        "Substrates",
        DOC_IDS["ten_q_2"],
        SUPPLY.new,
        quotes=(
            QUOTE_FILING,
            (TEN_Q_SUPPLY[0], DOC_IDS["ten_q_1"]),
            (RELEASE_GUIDANCE[0], DOC_IDS["exhibit_2_1"]),
        ),
    )
    text = readings_text(Q2, supply=[entry])

    assert checked(tree, text) == [
        (line_of(text, f"— {DOC_IDS['ten_q_1']}"), QUOTE_SOURCE),
        (line_of(text, f"— {DOC_IDS['exhibit_2_1']}"), QUOTE_SOURCE),
    ]


@pytest.mark.parametrize(
    ("quote", "attribution", "where", "message"),
    [
        (
            "Supply of substrates and certain specialty chemicals remained loose during the quarter.",
            DOC_IDS["ten_q_2"],
            "quote",
            NOT_FOUND,
        ),
        (
            "Risk Factors",
            DOC_IDS["ten_q_2"],
            "quote",
            "the quote is 12 characters long after normalisation; it must be 20 to 800",
        ),
        (
            "certain specialty chemicals remained tight during the quarter.",
            DOC_IDS["ten_q_2"],
            "quote",
            NOT_WHOLE,
        ),
        (TEN_Q_SUPPLY[0], f"{DOC_IDS['ten_q_2']}, Lip-Bu Tan (executive)", "attribution", NO_SPEAKER),
        (CEO_DEMAND, CALL_ID, "attribution", CALL_SPEAKER),
        (
            CEO_DEMAND,
            f"{CALL_ID}, David Zinsner (executive)",
            "attribution",
            "the quote lies in the turn 'Lip-Bu Tan (executive)', not the one its attribution names",
        ),
        (
            CEO_DEMAND,
            f"{CALL_ID}, Lip-Bu Tan",
            "attribution",
            "the quote lies in the turn 'Lip-Bu Tan (executive)', not the one its attribution names",
        ),
        (
            CEO_DEMAND,
            f"{CALL_ID}, Lip-Bu Tan (analyst)",
            "attribution",
            "the quote lies in the turn 'Lip-Bu Tan (executive)', not the one its attribution names",
        ),
        (
            f"{CEO_CAPACITY} David Zinsner (executive) {CFO_GUIDANCE}",
            f"{CALL_ID}, Lip-Bu Tan (executive)",
            "quote",
            ACROSS_TURNS,
        ),
        (f"Lip-Bu Tan (executive) {CEO_DEMAND}", f"{CALL_ID}, Lip-Bu Tan (executive)", "quote", ACROSS_TURNS),
    ],
    ids=[
        "not-found",
        "too-short",
        "mid-sentence",
        "filing-names-a-speaker",
        "call-without-speaker",
        "another-speaker",
        "name-without-role",
        "another-role",
        "across-turns",
        "with-its-heading",
    ],
)
def test_a_quote_is_found_whole_and_a_calls_quote_names_its_turn(tree, quote, attribution, where, message):
    doc_id = attribution.partition(", ")[0]
    entry = Reading("Substrates", doc_id, SUPPLY.new, quotes=((quote, attribution),))
    text = readings_text(Q2, supply=[entry])
    line = line_of(text, ">") if where == "quote" else line_of(text, "— ")

    assert checked(tree, text) == [(line, message)]


def test_a_speakers_later_turn_is_named_by_the_same_heading(tree):
    entry = Reading(
        "Gross margin guidance and supply on the call",
        CALL_ID,
        "gross margin of approximately 36% in the third quarter; substrate supply tight",
        quotes=(
            (CFO_GUIDANCE, f"{CALL_ID}, David Zinsner (executive)"),
            (CFO_SUPPLY, f"{CALL_ID}, David Zinsner (executive)"),
        ),
    )

    assert checked(tree, readings_text(Q2, guidance=[entry])) == []


@pytest.mark.parametrize(
    "again",
    [QUOTE_FILING[0], QUOTE_FILING[0].replace(" of ", "  of ")],
    ids=["same", "other-spacing"],
)
def test_a_quote_is_given_once_per_item(tree, again):
    entry = Reading(
        "Substrates", DOC_IDS["ten_q_2"], SUPPLY.new, quotes=(QUOTE_FILING, (again, QUOTE_FILING[1]))
    )
    text = readings_text(Q2, supply=[entry])

    assert checked(tree, text) == [(label_line(text, "Substrates", "difference") + 3, REPEATED_QUOTE)]


def test_one_quote_may_serve_several_items_and_aspects(tree):
    other = Reading("Specialty chemicals", DOC_IDS["ten_q_2"], "tight", quotes=(QUOTE_FILING,))
    roadmap = Reading(
        "Capacity at the Arizona factory",
        CALL_ID,
        "capacity added for Intel 18A",
        quotes=((CEO_CAPACITY, f"{CALL_ID}, Lip-Bu Tan (executive)"),),
    )
    capacity = Reading("Intel 18A capacity", CALL_ID, "capacity added for Intel 18A", quotes=roadmap.quotes)

    assert checked(tree, readings_text(Q2, supply=[SUPPLY, other, capacity], roadmap=[roadmap])) == []


# R7: an item's title, values and difference carry no valuation, forecast or advice wording;
# quotes are the issuer's words and never checked against it.


def test_titles_values_and_differences_carry_no_valuation_forecast_or_advice_wording(tree):
    entry = Reading(
        "Upside in substrates",
        SUPPLY.season,
        "The shares are a Buy; buy.",
        SUPPLY.baseline,
        "A downside case.",
        "We recommend holding.",
        SUPPLY.quotes,
    )
    text = readings_text(Q2, supply=[entry])

    assert checked(tree, text) == [
        (line_of(text, "### Upside"), WORDING_FOUND.format(terms="upside")),
        (label_line(text, entry.title, "new"), WORDING_FOUND.format(terms="buy")),
        (label_line(text, entry.title, "old"), WORDING_FOUND.format(terms="downside")),
        (label_line(text, entry.title, "difference"), WORDING_FOUND.format(terms="recommend")),
    ]


def test_a_quote_may_carry_such_wording():
    sentence = "The Board recommends that stockholders vote for each of the director nominees."
    document = Source(Q2, lambda: True, False, False, lambda: f"{sentence}\n", lambda: ())
    sources = {DOC_IDS["ten_q_2"]: document, DOC_IDS["ten_q_1"]: document}
    comparison = Comparison("quarter", Q2, "10-Q", frozenset(sources), Q1, (DOC_IDS["ten_q_1"],), sources)
    entry = Reading(
        "Director nominees",
        DOC_IDS["ten_q_2"],
        "each of the director nominees",
        quotes=((sentence, DOC_IDS["ten_q_2"]),),
    )

    readings, found = parse_readings(readings_text(Q2, debt=[entry]), TICKER, Q2, "quarter")

    assert (found, readings_problems(readings, comparison)) == ([], [])


def test_the_wording_rule_reads_whole_words_and_names_each_term_once():
    assert wording_problems(7, "Shares look undervalued; we Recommend a BUY, then buy more.") == [
        Problem(7, WORDING_FOUND.format(terms="undervalued, recommend, buy"))
    ]
    assert wording_problems(7, "Holdings rose; the holder is selling shares and buybacks paused.") == []
    assert WORDING.search("a price target of $40") is not None
    assert WORDING.search("Officers sold 10,000 shares.") is None
    # An accounting measure and a proxy statement's vote are facts.
    assert WORDING.search("The fair value of the unit exceeded its carrying value by 12%.") is None
    assert WORDING.search("The say-on-pay advisory vote passed; the advisor resigned.") is None
    assert WORDING.search("The board advised holders; it advises; it is advisable.") is not None


# --------------------------------------------------------------------------- quotes in small texts

DOC = DOC_IDS["ten_q_2"]
SUPPLY_SENTENCE = TEN_Q_SUPPLY[0]
CAPEX_SENTENCE = COMMENTARY_CAPEX[0]
DERIVED = f"Quarterly Report\nLiquidity\n{SUPPLY_SENTENCE}\n{CAPEX_SENTENCE} We continue to invest.\n"


def source(derived: str = DERIVED, *, layout: bool = False, turns: tuple[Turn, ...] | None = None) -> Source:
    """A document whose derived text is ``derived``; a call, read with ``turns``, when they are given."""
    return Source(Q2, lambda: True, turns is not None, layout, lambda: derived, lambda: turns or ())


def quoted(
    text: str,
    derived: str = DERIVED,
    speaker: str | None = None,
    *,
    layout: bool = False,
    turns: tuple[Turn, ...] | None = None,
) -> list[tuple[int, str]]:
    """The problems of ``text`` quoted on line 5 and attributed on line 6, its whitespace runs
    read as single spaces as the parser joins a quote's lines."""
    quote = Quote(5, " ".join(text.split()), DOC, speaker, 6)
    return [
        (problem.line, problem.message)
        for problem in quote_problems(quote, source(derived, layout=layout, turns=turns))
    ]


@pytest.mark.parametrize(("quote", "length"), [("Too short here.", 15), ("A" * 801, 801)])
def test_a_quote_is_20_to_800_characters_after_normalisation(quote, length):
    assert quoted(quote) == [
        (5, f"the quote is {length} characters long after normalisation; it must be 20 to 800")
    ]


def test_a_quote_of_20_characters_passes():
    assert quoted("Revenue grew by 20%.", "Revenue grew by 20%.\n") == []


def test_a_quote_must_be_found_verbatim():
    assert quoted(CAPEX_SENTENCE.replace("$9", "$10")) == [(5, NOT_FOUND)]
    assert quoted(CAPEX_SENTENCE.lower()) == [(5, NOT_FOUND)]


def test_whitespace_between_words_may_differ():
    assert quoted(f"Liquidity {SUPPLY_SENTENCE}") == []
    assert (
        quoted("Supply of\tsubstrates and certain  specialty chemicals remained tight during the quarter.")
        == []
    )


SUFFICIENT = "Supply of substrates remained sufficient for the quarter."


@pytest.mark.parametrize(
    ("quote", "derived"),
    [
        (SUPPLY_SENTENCE.replace("substrates", "sub­strates"), DERIVED),  # a soft hyphen
        (SUPPLY_SENTENCE.replace("specialty", "special​ty"), DERIVED),  # a zero-width space
        (SUFFICIENT.replace("ffi", "ﬃ"), f"{SUFFICIENT}\n"),  # a ligature the text writes as letters
    ],
    ids=["soft-hyphen", "zero-width-space", "ligature"],
)
def test_a_quote_is_spelt_as_the_derived_text_writes_it(quote, derived):
    assert quoted(SUFFICIENT, f"{SUFFICIENT}\n") == []
    assert quoted(quote, derived) == [(5, SPELLING)]


@pytest.mark.parametrize(
    "quote",
    [
        "capital spending of approximately $9 billion for the full year.",  # starts mid-sentence
        "We now expect net capital spending of approximately $9 billion",  # ends mid-sentence
    ],
    ids=["starts-mid-sentence", "ends-mid-sentence"],
)
def test_a_quote_must_be_whole_sentences(quote):
    assert quoted(quote) == [(5, NOT_WHOLE)]


def test_layout_mode_reads_a_line_break_as_whitespace():
    wrapped = "We now expect net capital spending\nof approximately $9 billion for the full year.\n"
    sentence = "We now expect net capital spending of approximately $9 billion for the full year."
    table = "Outlook\nNet capital spending approximately $9 billion\nGross margin approximately 36 percent\n"
    row = "Net capital spending approximately $9 billion"

    assert quoted(sentence, wrapped, layout=True) == []
    assert quoted(sentence, wrapped, layout=False) == []  # the next line continues in lowercase
    assert quoted(row, table, layout=False) == []  # a whole block line
    assert quoted(row, table, layout=True) == [(5, NOT_WHOLE)]  # no sentence end


# A call's derived text as ``earningscalls.call_text`` lays it out: per turn a heading line
# "{speaker} ({role})", then its paragraphs; the offsets below are written out by hand.
OPERATOR_LINE = "Our first question comes from Jane Analyst with Example Securities."
ANALYST_LINE = "Can you talk about how substrate supply constrained shipments in the quarter?"
CFO_FIRST = "We expect gross margin of approximately 36% in the third quarter."
CFO_SECOND = "We funded our capital spending with cash from operations."
TURN_TEXT = (
    "Operator (operator)\n"
    f"{OPERATOR_LINE}\n"
    "Jane Analyst (analyst)\n"
    f"{ANALYST_LINE}\n"
    "David Zinsner (executive)\n"
    f"{CFO_FIRST}\n{CFO_SECOND}\n"
)


def turns_of(text: str) -> tuple[Turn, ...]:
    """The turns of ``text``: each heading line's speaker and role, and the span of the lines up
    to the next heading (the last turn's without the final line break)."""
    lines = text.split("\n")[:-1]
    headings = [index for index, line in enumerate(lines) if line.endswith(")") and " (" in line]
    turns = []
    for position, index in enumerate(headings):
        start = sum(len(line) + 1 for line in lines[: index + 1])
        last = headings[position + 1] if position + 1 < len(headings) else len(lines)
        end = sum(len(line) + 1 for line in lines[:last]) - 1
        speaker, role = lines[index].removesuffix(")").rsplit(" (", 1)
        turns.append(Turn(start, end, speaker, role))
    return tuple(turns)


TURNS = turns_of(TURN_TEXT)


def test_the_turns_helper_finds_each_turns_words():
    assert [(TURN_TEXT[turn.start : turn.end], turn.heading) for turn in TURNS] == [
        (OPERATOR_LINE, "Operator (operator)"),
        (ANALYST_LINE, "Jane Analyst (analyst)"),
        (f"{CFO_FIRST}\n{CFO_SECOND}", "David Zinsner (executive)"),
    ]


@pytest.mark.parametrize(
    ("quote", "speaker"),
    [
        (CFO_FIRST, "David Zinsner (executive)"),
        (f"{CFO_FIRST} {CFO_SECOND}", "David Zinsner (executive)"),
        (ANALYST_LINE, "Jane Analyst (analyst)"),
        (OPERATOR_LINE, "Operator (operator)"),
    ],
    ids=["executive", "two-lines", "analyst", "operator"],
)
def test_a_call_quote_of_any_role_naming_its_turn_passes(quote, speaker):
    assert quoted(quote, TURN_TEXT, speaker, turns=TURNS) == []


def test_a_call_quote_names_its_turn():
    assert quoted(CFO_FIRST, TURN_TEXT, turns=TURNS) == [(6, CALL_SPEAKER)]
    assert quoted(CFO_FIRST, TURN_TEXT, "Jane Analyst (analyst)", turns=TURNS) == [
        (6, "the quote lies in the turn 'David Zinsner (executive)', not the one its attribution names")
    ]


@pytest.mark.parametrize(
    "quote",
    [f"{ANALYST_LINE} David Zinsner (executive) {CFO_FIRST}", f"David Zinsner (executive) {CFO_FIRST}"],
    ids=["across-turns", "with-its-heading"],
)
def test_a_call_quote_lies_within_one_turns_words(quote):
    assert quoted(quote, TURN_TEXT, "David Zinsner (executive)", turns=TURNS) == [(5, ACROSS_TURNS)]
