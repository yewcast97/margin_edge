"""``readings``: the grammar of a season's readings file and the rules ``check`` holds it to.

The grammar (G1 to G7) is read from text alone (``parse_readings``). The rules (R1 to R10)
are checked on a real tree: ``workflow_support.research`` fetches, derives and writes the
window seasons' default readings once for the module, and each test writes one draft beside
them that breaks one thing, which ``workflow.check`` reads; a test that changes the tree
builds its own. The quote rules (R9) are also held against small derived texts written the
way ``text.py`` derives documents (``quote_problems``). Every expected message is written
out, so a change of wording fails here first.
"""

import itertools
from datetime import date

import pytest

from market_state_research.common.layout import DataLayout
from market_state_research.fundamentals.script import workflow
from market_state_research.fundamentals.script.earningscalls import Turn
from market_state_research.fundamentals.script.items import BOT_ITEMS, BY_ID
from market_state_research.fundamentals.script.readings import (
    WORDING,
    Problem,
    Quote,
    Source,
    parse_readings,
    quote_problems,
    wording_problems,
)

from .calls_support import (
    ANALYST_QUESTION,
    CEO_CAPACITY,
    CEO_DEMAND,
    CFO_GUIDANCE,
    CFO_SUPPLY,
    OPERATOR_QUESTION,
)
from .edgar_support import COMMENTARY_CAPEX, RELEASE_GUIDANCE, TEN_K_CUSTOMERS, TEN_Q_SUPPLY, TICKER
from .support import NOW
from .workflow_support import DOC_IDS, QUOTE_CALL, QUOTE_FILING, Reading, place, readings_text, research

FY = date(2025, 12, 27)  # the 10-K season: a proxy statement, no call transcript
Q2 = date(2026, 6, 27)  # the 10-Q season most tests read: its call has a transcript
DEFAULT = readings_text(Q2)  # every bot item at its default reading
LAST = len(DEFAULT.splitlines())
# The bot's items, in catalogue order: the sections of a readings file.
BOT_IDS = (
    *("1.1", "1.2", "1.4", "1.5", "1.6", "1.7", "1.9", "1.10"),
    *("2.7", "2.8", "2.9"),
    *(f"3.{number}" for number in range(1, 12)),
    *(f"4.{number}" for number in range(1, 9)),
    *(f"5.{number}" for number in range(1, 7)),
    *(f"6.{number}" for number in range(1, 7)),
    *(f"7.{number}" for number in range(1, 5)),
    *(f"8.{number}" for number in range(1, 5)),
    "9.2",
)

TITLE = "the first line must be '# INTC · 2026-06-27 · readings'"
HEADINGS = "the sections must be the bot's items, each once, in catalogue order: '## {id} {title}'"
OUTSIDE_SECTION = "this line is outside the readings' sections"
FIRST_LINES = "a section starts with its 'baseline:', 'level:' and 'observation:' lines, in that order"
UNEXPECTED_LINE = (
    "a section holds its three lines, then '> TEXT' lines each quote ended by its '— DOC_ID' line"
)
EMPTY_QUOTE_LINE = "an empty '>' line; a quote's lines each hold text"
NO_ATTRIBUTION = "a quote's '>' lines must be followed by its attribution line '— DOC_ID'"
ATTRIBUTION_WITHOUT_QUOTE = "an attribution line must follow a quote's '>' lines"
BASELINE_TEXT = "the baseline must be 'none' or DOC_IDs joined by '; '"
LEVEL_TEXT = (
    "the level must be one of: red, yellow, grey, none, no baseline, not applicable, not disclosed, "
    "unavailable, not computable"
)
OBSERVATION_TEXT = "the observation must be 1 to 600 printable characters"
QUOTE_SOURCE = "a quote comes from a document of the season or one the baseline line names"
RED_NEEDS_QUOTE = "a red level needs a quote from a document of the season itself"
NOT_FOUND = "quote not found in the document's derived text"
NOT_WHOLE = (
    "a quote must be whole sentences, or whole lines of an HTML, XML or call document: it must start, never "
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


def parsed(text: str, season: date = Q2) -> list[tuple[int, str]]:
    """The grammar problems of ``text`` as ``season``'s readings."""
    _, found = parse_readings(text, TICKER, season)
    return [(problem.line, problem.message) for problem in found]


def line_of(text: str, start: str) -> int:
    """The number of the first line of ``text`` that starts with ``start``."""
    return next(number for number, line in enumerate(text.splitlines(), start=1) if line.startswith(start))


def lines_of(text: str, item: str) -> tuple[int, int, int]:
    """The lines of an item's ``baseline:``, ``level:`` and ``observation:`` in ``text``."""
    heading = line_of(text, f"## {item} ")
    return heading + 1, heading + 2, heading + 3


def section(text: str, item: str, following: str) -> str:
    """The section of ``item`` in ``text``, from its heading to the heading of ``following``."""
    return text[text.index(f"## {item} ") : text.index(f"## {following} ")]


def missing(item: str) -> str:
    return f"the section '## {BY_ID[item].heading}' is missing"


# --------------------------------------------------------------------------- grammar


def test_the_sections_are_the_bots_items_in_catalogue_order():
    readings, found = parse_readings(DEFAULT, TICKER, Q2)

    assert [item.id for item in BOT_ITEMS] == list(BOT_IDS)
    assert found == []
    assert readings.title_line == 1
    assert [reading.item.id for reading in readings.items] == list(BOT_IDS)
    assert [reading.line for reading in readings.items] == [3 + 5 * index for index in range(51)]
    assert LAST == 2 + 5 * 51 - 1  # the title, a blank line, then four lines and a blank per section


def test_valid_readings_parse_into_their_items_with_every_line():
    text = readings_text(
        Q2,
        i3_6=Reading(
            f"{DOC_IDS['ten_q_1']}; {DOC_IDS['exhibit_1']}",
            "red",
            "The 10-Q adopts a standard the previous one did not name.",
            (QUOTE_FILING, (TEN_Q_SUPPLY[0], DOC_IDS["ten_q_1"])),
        ),
        i7_4=Reading("none", "yellow", "One figure differs.", (QUOTE_CALL,)),
    )
    heading = line_of(text, "## 3.6 ")
    call = line_of(text, "## 7.4 ")

    readings, found = parse_readings(text, TICKER, Q2)

    assert found == []
    policy = readings.get("3.6")
    assert policy is not None
    assert (policy.line, policy.baseline, policy.baseline_line) == (
        heading,
        (DOC_IDS["ten_q_1"], DOC_IDS["exhibit_1"]),
        heading + 1,
    )
    assert (policy.level, policy.level_line) == ("red", heading + 2)
    assert (policy.observation, policy.observation_line) == (
        "The 10-Q adopts a standard the previous one did not name.",
        heading + 3,
    )
    assert policy.quotes == (
        Quote(heading + 4, TEN_Q_SUPPLY[0], DOC_IDS["ten_q_2"], None, heading + 5),
        Quote(heading + 6, TEN_Q_SUPPLY[0], DOC_IDS["ten_q_1"], None, heading + 7),
    )
    statement = readings.get("7.4")
    assert statement is not None
    assert (statement.baseline, statement.level) == ((), "yellow")
    assert statement.quotes == (
        Quote(call + 4, CEO_DEMAND, DOC_IDS["call_q2"], "Lip-Bu Tan (executive)", call + 5),
    )
    assert readings.get("2.1") is None  # Python's item: never a section of the readings
    levels = readings.levels()
    assert (len(levels), levels["3.6"], levels["3.2"], levels["2.7"]) == (
        51,
        "red",
        "not applicable",
        "no baseline",
    )


def test_a_quotes_lines_are_joined_by_one_space_and_blank_lines_may_separate_quotes():
    block = (
        "> Supply of substrates and certain specialty\n"
        ">  chemicals remained\ttight during the quarter.  \n"
        f"— {DOC_IDS['ten_q_2']}\n"
        "\n"
        f"> {CEO_DEMAND}\n"
        f"— {DOC_IDS['call_q2']}, Lip-Bu Tan (executive)\n"
    )
    text = DEFAULT.replace("## 3.7 ", f"{block}\n## 3.7 ")
    first = line_of(text, "> Supply of substrates")

    readings, found = parse_readings(text, TICKER, Q2)

    assert found == []
    reading = readings.get("3.6")
    assert reading is not None
    assert reading.quotes == (
        Quote(first, TEN_Q_SUPPLY[0], DOC_IDS["ten_q_2"], None, first + 2),
        Quote(first + 4, CEO_DEMAND, DOC_IDS["call_q2"], "Lip-Bu Tan (executive)", first + 5),
    )


def test_blank_lines_before_the_title_trailing_spaces_and_crlf_are_accepted():
    text = "\n\n" + DEFAULT.replace("\n", "  \r\n")

    readings, found = parse_readings(text, TICKER, Q2)

    assert found == []
    assert (readings.title_line, readings.items[0].line) == (3, 5)


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("# INTC · 2026-03-28 · readings", [(1, TITLE)]),
        ("# AMD · 2026-06-27 · readings", [(1, TITLE)]),
        ("# INTC - 2026-06-27 - readings", [(1, TITLE)]),
        ("# INTC · 2026-06-27 · readings · draft", [(1, TITLE)]),
        ("#INTC · 2026-06-27 · readings", [(1, TITLE), (1, OUTSIDE_SECTION)]),  # read as a body line
    ],
    ids=["other-season", "other-ticker", "hyphens", "extra-text", "no-space"],
)
def test_the_title_names_the_ticker_and_the_season(title, expected):
    assert parsed(DEFAULT.replace("# INTC · 2026-06-27 · readings", title, 1)) == expected


def test_readings_without_their_title_read_their_first_line_as_a_section():
    without = DEFAULT.removeprefix("# INTC · 2026-06-27 · readings\n\n")

    readings, found = parse_readings(without, TICKER, Q2)

    assert [(problem.line, problem.message) for problem in found] == [(1, TITLE)]
    assert readings.items[0].item.id == "1.1"
    assert len(readings.items) == 51


def test_a_line_before_any_section_is_outside_the_sections():
    text = DEFAULT.replace("readings\n\n", "readings\nA line before the sections.\n", 1)

    assert parsed(text) == [(2, OUTSIDE_SECTION)]


def test_empty_readings_lack_their_title_and_every_section():
    assert parsed("") == [(1, TITLE), *((1, missing(item)) for item in BOT_IDS)]
    assert parsed("\n\n\n") == [(3, TITLE), *((3, missing(item)) for item in BOT_IDS)]


def test_sections_out_of_order_are_reported_once_and_still_read():
    first, second = section(DEFAULT, "1.1", "1.2"), section(DEFAULT, "1.2", "1.4")
    swapped = DEFAULT.replace(first + second, second + first)

    readings, found = parse_readings(swapped, TICKER, Q2)

    assert [(problem.line, problem.message) for problem in found] == [(line_of(swapped, "## 1.1 "), HEADINGS)]
    assert [reading.item.id for reading in readings.items][:3] == ["1.2", "1.1", "1.4"]


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        (
            lambda text: (
                text
                + "\n## 1.1 Full-year revenue guidance\nbaseline: none\nlevel: none\nobservation: Again.\n"
            ),
            [(LAST + 2, HEADINGS)],
        ),
        (
            lambda text: text.replace(
                "## 2.7 ",
                "## 2.1 Revenue and net income growth\nbaseline: none\nlevel: none\n"
                "observation: Python's.\n\n## 2.7 ",
            ),
            [(line_of(DEFAULT, "## 2.7 "), HEADINGS)],
        ),
        (
            lambda text: text.replace("## 1.4 Guidance range width", "## 1.4 Guidance width"),
            [(line_of(DEFAULT, "## 1.4 "), HEADINGS), (LAST, missing("1.4"))],
        ),
        (
            lambda text: text.replace("## 1.4 Guidance range width", "## Guidance range width"),
            [(line_of(DEFAULT, "## 1.4 "), HEADINGS), (LAST, missing("1.4"))],
        ),
    ],
    ids=["repeated", "python-item", "renamed", "without-id"],
)
def test_an_unknown_repeated_or_python_section_is_refused_and_its_lines_skipped(change, expected):
    assert parsed(change(DEFAULT)) == expected


@pytest.mark.parametrize(
    ("first_lines", "expected"),
    [
        ("level: none\nobservation: Nothing new.\n", [(1, FIRST_LINES), (2, UNEXPECTED_LINE)]),
        (
            f"level: none\nbaseline: {DOC_IDS['ten_q_1']}\nobservation: Nothing new.\n",
            [(1, FIRST_LINES), (2, UNEXPECTED_LINE), (3, UNEXPECTED_LINE)],
        ),
        (f"baseline: {DOC_IDS['ten_q_1']}\nobservation: Nothing new.\n", [(2, FIRST_LINES)]),
        ("", [(0, FIRST_LINES)]),
        (
            f"> {TEN_Q_SUPPLY[0]}\n— {DOC_IDS['ten_q_2']}\n",
            [(1, FIRST_LINES)],
        ),
    ],
    ids=["no-baseline-line", "level-first", "no-level-line", "heading-alone", "quote-first"],
)
def test_a_section_starts_with_its_baseline_level_and_observation_lines(first_lines, expected):
    text = DEFAULT.replace(section(DEFAULT, "3.3", "3.4"), f"## 3.3 Going concern\n{first_lines}\n")
    heading = line_of(text, "## 3.3 ")

    assert parsed(text) == [(heading + offset, message) for offset, message in expected]


@pytest.mark.parametrize(
    "value",
    ["", "A, B", "A;  B", "A ;B", f"{DOC_IDS['ten_q_1']} ; {DOC_IDS['exhibit_1']}"],
    ids=["empty", "commas", "two-spaces", "space-before", "spaced"],
)
def test_the_baseline_is_none_or_doc_ids_joined_by_a_semicolon_and_a_space(value):
    text = readings_text(Q2, i3_3=Reading(value, "none"))

    assert parsed(text) == [(lines_of(text, "3.3")[0], BASELINE_TEXT)]


def test_a_baseline_of_several_doc_ids_is_read_in_its_order():
    text = readings_text(Q2, i4_1=Reading(f"{DOC_IDS['ten_k']}; {DOC_IDS['ten_q_1']}", "none"))

    readings, found = parse_readings(text, TICKER, Q2)

    reading = readings.get("4.1")
    assert reading is not None
    assert (found, reading.baseline) == ([], (DOC_IDS["ten_k"], DOC_IDS["ten_q_1"]))


@pytest.mark.parametrize("level", ["orange", "Red", "no source", "", "red, yellow"])
def test_the_level_is_a_level_or_a_status_the_bot_may_give(level):
    text = readings_text(Q2, i3_3=Reading(DOC_IDS["ten_q_1"], level))

    assert parsed(text) == [(lines_of(text, "3.3")[1], LEVEL_TEXT)]


@pytest.mark.parametrize(
    "observation",
    ["", "x" * 601, "Two\tcolumns.", "A zero\u200bwidth space."],
    ids=["empty", "601-characters", "tab", "zero-width-space"],
)
def test_the_observation_is_1_to_600_printable_characters(observation):
    text = readings_text(Q2, i3_3=Reading(DOC_IDS["ten_q_1"], "none", observation))

    assert parsed(text) == [(lines_of(text, "3.3")[2], OBSERVATION_TEXT)]


def test_an_observation_of_600_characters_passes_without_its_outer_spaces():
    text = readings_text(Q2, i3_3=Reading(DOC_IDS["ten_q_1"], "none", "  " + "x" * 600 + "  "))

    readings, found = parse_readings(text, TICKER, Q2)

    reading = readings.get("3.3")
    assert reading is not None
    assert (found, reading.observation) == ([], "x" * 600)


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
        (f"{QUOTE}\n{ATTRIBUTION}\nlevel: red", [(2, UNEXPECTED_LINE)]),
        ("- a list item", [(0, UNEXPECTED_LINE)]),
    ],
    ids=[
        "empty-quote-line",
        "no-attribution",
        "attribution-alone",
        "attribution-first",
        "free-text",
        "quote-then-text",
        "second-level",
        "list-item",
    ],
)
def test_after_its_first_lines_a_section_holds_quotes_each_ended_by_its_attribution(block, expected):
    text = readings_text(Q2, i3_6=Reading(DOC_IDS["ten_q_1"], "none", "The 3.6 observation."))
    text = text.replace(
        "observation: The 3.6 observation.\n", f"observation: The 3.6 observation.\n{block}\n"
    )
    start = line_of(text, "observation: The 3.6 observation.") + 1

    assert parsed(text) == [(start + offset, message) for offset, message in expected]


def test_an_attribution_line_is_a_dash_a_space_and_its_doc_id():
    text = readings_text(Q2, i3_6=Reading(DOC_IDS["ten_q_1"], "none", quotes=(QUOTE_FILING,)))
    joined = text.replace(f"— {DOC_IDS['ten_q_2']}", f"—{DOC_IDS['ten_q_2']}")

    assert parsed(joined) == [
        (
            line_of(joined, "—"),
            "an attribution line is '— DOC_ID', or '— DOC_ID, Speaker (role)' for a call's quote",
        )
    ]


def test_problems_come_in_line_order_and_the_sections_read_are_still_returned():
    text = readings_text(Q2, i3_6=Reading(DOC_IDS["ten_q_1"], "orange", quotes=(QUOTE_FILING,)))
    text = text.replace("# INTC · 2026-06-27 · readings", "# INTC", 1).replace(
        "## 2.7 ", "A stray line.\n## 2.7 "
    )

    readings, found = parse_readings(text, TICKER, Q2)

    assert [(problem.line, problem.message) for problem in found] == [
        (1, TITLE),
        (line_of(text, "A stray line."), UNEXPECTED_LINE),
        (lines_of(text, "3.6")[1], LEVEL_TEXT),
    ]
    reading = readings.get("3.6")
    assert reading is not None
    assert (reading.level, [quote.text for quote in reading.quotes]) == ("orange", [TEN_Q_SUPPLY[0]])


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


def test_the_default_readings_of_every_window_season_pass(tree):
    output = workflow.check(tree, TICKER, NOW)

    assert [(found["season"], found["valid"], found["problems"]) for found in output["readings"]] == [
        ("2025-12-27", True, []),
        ("2026-03-28", True, []),
        ("2026-06-27", True, []),
    ]


def test_readings_with_levels_baselines_statuses_and_quotes_of_any_speaker_pass(tree):
    text = readings_text(
        Q2,
        i1_1=Reading(
            f"{DOC_IDS['exhibit_1']}; {DOC_IDS['call_q1']}",
            "yellow",
            "The revenue guidance midpoint went from $13.1 billion to $13.9 billion, 6.1% higher.",
            ((RELEASE_GUIDANCE[0], DOC_IDS["exhibit_2_1"]), (RELEASE_GUIDANCE[0], DOC_IDS["exhibit_1"])),
        ),
        i1_2=Reading("none", "not disclosed", "Neither release gives full-year profit guidance."),
        i1_9=Reading(f"{DOC_IDS['old_ten_k']}; {DOC_IDS['call_old_q']}", "grey", "No result fell short."),
        i2_9=Reading("none", "not computable", "Net income is below zero."),
        i3_6=Reading(DOC_IDS["ten_q_1"], "red", "The 10-Q names one more policy change.", (QUOTE_FILING,)),
        i4_1=Reading(f"{DOC_IDS['ten_q_1']}; {DOC_IDS['ten_k']}", "none", "The risk factors are unchanged."),
        i6_4=Reading("none", "not computable", "No amount is stated."),
        i7_4=Reading("none", "red", "The chief executive states demand above supply.", (QUOTE_CALL,)),
        i8_1=Reading(
            DOC_IDS["call_q1"],
            "yellow",
            "One question on substrates; its answer gives no figure.",
            (
                (OPERATOR_QUESTION, f"{DOC_IDS['call_q2']}, Operator (operator)"),
                (ANALYST_QUESTION, f"{DOC_IDS['call_q2']}, Jane Analyst (analyst)"),
                (CFO_SUPPLY, f"{DOC_IDS['call_q2']}, David Zinsner (executive)"),
            ),
        ),
    )

    assert checked(tree, text) == []


def test_a_byte_order_mark_crlf_line_ends_and_trailing_spaces_are_accepted(tree):
    text = readings_text(Q2, i3_6=Reading(DOC_IDS["ten_q_1"], "red", quotes=(QUOTE_FILING,)))

    found = draft(tree, b"\xef\xbb\xbf" + text.replace("\n", "  \r\n").encode("utf-8"))

    assert (found["valid"], found["problems"]) == (True, [])


def test_readings_that_are_not_utf_8_are_one_problem_on_line_1(tree):
    found = draft(tree, DEFAULT.encode("utf-16"))

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


# R1: every DOC_ID named is a document in raw/ whose text file equals its derivation.


def test_a_doc_id_that_is_no_document_in_raw_is_refused(tree):
    unknown = "10-Q_2026-03-28_0000050863-26-000041_intc-2026032"
    text = readings_text(
        Q2,
        i3_3=Reading(unknown, "none"),
        i3_6=Reading(DOC_IDS["ten_q_1"], "none", quotes=((TEN_Q_SUPPLY[0], unknown),)),
    )
    message = f"{unknown} is no document in raw/ (a DOC_ID of a text file in formatted/)"

    assert checked(tree, text) == [
        (lines_of(text, "3.3")[0], message),
        (line_of(text, f"— {unknown}"), message),
    ]


def test_a_document_whose_text_file_is_stale_or_missing_is_refused(layout):
    research(layout)
    stale = layout.formatted(TICKER) / "2026-03-28" / f"{DOC_IDS['eight_k_1']}.md"
    stale.write_text(stale.read_text(encoding="utf-8") + "A line derive never writes.\n", encoding="utf-8")
    (layout.formatted(TICKER) / "2026-06-27" / f"{DOC_IDS['exhibit_2_2']}.md").unlink()
    text = readings_text(
        Q2,
        i3_3=Reading(DOC_IDS["eight_k_1"], "none", quotes=((COMMENTARY_CAPEX[0], DOC_IDS["exhibit_2_2"]),)),
    )

    assert checked(layout, text) == [
        (
            lines_of(text, "3.3")[0],
            f"the text file of {DOC_IDS['eight_k_1']} is missing or differs from its derivation; run derive",
        ),
        (
            line_of(text, f"— {DOC_IDS['exhibit_2_2']}"),
            f"the text file of {DOC_IDS['exhibit_2_2']} is missing or differs from its derivation; "
            "run derive",
        ),
    ]


# R2: the baseline names documents of the item's baseline seasons only, at least one for a
# level of an item with a baseline, and none for an item without one or for a status.


@pytest.mark.parametrize(
    ("season", "changed", "item", "messages"),
    [
        (
            Q2,
            {"i3_3": Reading(DOC_IDS["ten_k"], "none")},
            "3.3",
            [
                f"{DOC_IDS['ten_k']} is no document of this item's baseline (previous quarter: 2026-03-28)",
            ],
        ),
        (
            Q2,
            {"i3_3": Reading(f"{DOC_IDS['ten_q_1']}; {DOC_IDS['old_ten_q']}", "none")},
            "3.3",
            [
                f"{DOC_IDS['old_ten_q']} is no document of this item's baseline "
                "(previous quarter: 2026-03-28)",
            ],
        ),
        (
            Q2,
            {"i2_7": Reading(DOC_IDS["ten_k"], "none")},
            "2.7",
            [
                f"{DOC_IDS['ten_k']} is no document of this item's baseline "
                "(same quarter last year: none listed)",
            ],
        ),
        (
            Q2,
            {"i3_3": Reading("none", "none")},
            "3.3",
            ["a level of an item with a baseline names the baseline documents read (previous quarter)"],
        ),
        (
            Q2,
            {"i1_1": Reading("none", "red", quotes=((RELEASE_GUIDANCE[0], DOC_IDS["exhibit_2_1"]),))},
            "1.1",
            ["a level of an item with a baseline names the baseline documents read (previous guidance)"],
        ),
        (
            Q2,
            {"i3_1": Reading(DOC_IDS["ten_q_1"], "none")},
            "3.1",
            ["the baseline must be 'none' for an item without a baseline"],
        ),
        (
            Q2,
            {"i3_2": Reading(DOC_IDS["ten_k"], "not applicable")},
            "3.2",
            ["the baseline must be 'none' for the status 'not applicable'"],
        ),
        (
            FY,
            {"i7_1": Reading(DOC_IDS["old_ten_q"], "unavailable")},
            "7.1",
            ["the baseline must be 'none' for the status 'unavailable'"],
        ),
    ],
    ids=[
        "older-season",
        "one-of-two",
        "no-season-listed",
        "level-without-baseline",
        "red-without-baseline",
        "item-without-baseline",
        "not-applicable-with-baseline",
        "unavailable-with-baseline",
    ],
)
def test_the_baseline_names_documents_of_the_items_baseline_seasons(tree, season, changed, item, messages):
    text = readings_text(season, **changed)
    line = lines_of(text, item)[0]

    assert checked(tree, text, season) == [(line, message) for message in messages]


def test_baselines_of_several_seasons_and_statuses_without_a_baseline_pass(tree):
    text = readings_text(
        Q2,
        i1_9=Reading(f"{DOC_IDS['ten_q_1']}; {DOC_IDS['proxy']}; {DOC_IDS['old_ten_k']}", "none"),
        i4_3=Reading(f"{DOC_IDS['ten_q_1']}; {DOC_IDS['ten_k']}", "grey", "One risk factor is gone."),
        i1_6=Reading("none", "not disclosed", "No capital expenditure guidance is given."),
    )

    assert checked(tree, text) == []


# R3: a quote comes from a document of the season or from one its baseline line names.


def test_a_quote_comes_from_the_season_or_a_baseline_document_the_reading_names(tree):
    text = readings_text(
        Q2,
        i3_3=Reading(
            DOC_IDS["ten_q_1"],
            "none",
            quotes=((TEN_K_CUSTOMERS[0], DOC_IDS["ten_k"]), (TEN_Q_SUPPLY[0], DOC_IDS["ten_q_1"])),
        ),
        i3_7=Reading(DOC_IDS["ten_q_1"], "none", quotes=((RELEASE_GUIDANCE[0], DOC_IDS["exhibit_1"]),)),
    )

    assert checked(tree, text) == [
        (line_of(text, f"— {DOC_IDS['ten_k']}"), QUOTE_SOURCE),
        (line_of(text, f"— {DOC_IDS['exhibit_1']}"), QUOTE_SOURCE),
    ]


# R4: red needs a quote from a document of the season itself.


@pytest.mark.parametrize(
    "quotes",
    [(), ((TEN_Q_SUPPLY[0], DOC_IDS["ten_q_1"]),)],
    ids=["no-quote", "a-baseline-quote"],
)
def test_red_needs_a_quote_from_the_seasons_own_documents(tree, quotes):
    text = readings_text(Q2, i3_6=Reading(DOC_IDS["ten_q_1"], "red", quotes=quotes))

    assert checked(tree, text) == [(lines_of(text, "3.6")[1], RED_NEEDS_QUOTE)]


def test_yellow_and_grey_need_no_quote(tree):
    text = readings_text(
        Q2,
        i3_6=Reading(DOC_IDS["ten_q_1"], "yellow"),
        i4_3=Reading(DOC_IDS["ten_k"], "grey"),
    )

    assert checked(tree, text) == []


# R5: no baseline only while no document of the item's baseline seasons is in raw/.


@pytest.mark.parametrize(
    ("season", "item", "message"),
    [
        (
            Q2,
            "3.3",
            f"'no baseline' while the baseline is in raw/: {DOC_IDS['ten_q_1']}, {DOC_IDS['eight_k_1']}, "
            f"{DOC_IDS['exhibit_1']} ...",
        ),
        (
            FY,
            "1.5",
            f"'no baseline' while the baseline is in raw/: {DOC_IDS['old_ten_q']}, {DOC_IDS['call_old_q']}",
        ),
        (Q2, "3.1", "this item does not allow 'no baseline'"),
    ],
    ids=["four-documents", "two-documents", "item-without-baseline"],
)
def test_no_baseline_only_while_no_baseline_document_is_in_raw(tree, season, item, message):
    key = "i" + item.replace(".", "_")
    text = readings_text(season, **{key: Reading("none", "no baseline", "No baseline.")})

    assert checked(tree, text, season) == [(lines_of(text, item)[1], message)]


# R6: not applicable exactly for an annual item in a 10-Q season and a proxy item in a
# season without a proxy statement; R7: unavailable exactly for a call item while the
# season's call has no transcript.


@pytest.mark.parametrize(
    ("season", "item", "reading", "message"),
    [
        (
            Q2,
            "3.2",
            Reading(DOC_IDS["ten_k"], "none"),
            "this item is 'not applicable' in this season (an annual item in a 10-Q season)",
        ),
        (
            Q2,
            "5.5",
            Reading(DOC_IDS["proxy"], "none"),
            "this item is 'not applicable' in this season (a proxy item in a season without a proxy "
            "statement)",
        ),
        (
            Q2,
            "3.3",
            Reading("none", "not applicable", "Not this season."),
            "'not applicable' is only for an annual item in a 10-Q season or a proxy item without a proxy "
            "statement",
        ),
        (
            FY,
            "3.2",
            Reading("none", "not applicable", "Not this season."),
            "'not applicable' is only for an annual item in a 10-Q season or a proxy item without a proxy "
            "statement",
        ),
        (
            FY,
            "5.6",
            Reading("none", "not applicable", "Not this season."),
            "'not applicable' is only for an annual item in a 10-Q season or a proxy item without a proxy "
            "statement",
        ),
        (
            FY,
            "7.1",
            Reading(DOC_IDS["old_ten_q"], "none"),
            "a call item is 'unavailable' while the season's call has no transcript (unavailable)",
        ),
        (
            Q2,
            "7.1",
            Reading("none", "unavailable", "No transcript."),
            "'unavailable' is only for a call item while the season's call has no transcript",
        ),
        (
            Q2,
            "3.3",
            Reading("none", "unavailable", "No transcript."),
            "'unavailable' is only for a call item while the season's call has no transcript",
        ),
    ],
    ids=[
        "annual-item-in-10-Q",
        "proxy-item-without-proxy",
        "season-item",
        "annual-item-in-10-K",
        "proxy-item-with-proxy",
        "call-item-without-transcript",
        "call-item-with-transcript",
        "season-item-unavailable",
    ],
)
def test_not_applicable_and_unavailable_exactly_where_the_season_requires_them(
    tree, season, item, reading, message
):
    text = readings_text(season, **{"i" + item.replace(".", "_"): reading})

    assert checked(tree, text, season) == [(lines_of(text, item)[1], message)]


# R8: not disclosed and not computable only where the item allows them.


@pytest.mark.parametrize(
    ("item", "status"),
    [
        ("3.3", "not disclosed"),
        ("1.1", "not computable"),
        ("5.1", "not disclosed"),
        ("6.6", "not computable"),
    ],
)
def test_not_disclosed_and_not_computable_only_where_the_item_allows_them(tree, item, status):
    text = readings_text(Q2, **{"i" + item.replace(".", "_"): Reading("none", status, "Not stated.")})

    assert checked(tree, text) == [(lines_of(text, item)[1], f"this item does not allow '{status}'")]


@pytest.mark.parametrize(
    ("item", "status"),
    [
        ("1.1", "not disclosed"),
        ("2.9", "not computable"),
        ("2.9", "not disclosed"),
        ("6.4", "not computable"),
    ],
)
def test_an_item_may_take_the_statuses_it_allows(tree, item, status):
    text = readings_text(Q2, **{"i" + item.replace(".", "_"): Reading("none", status, "Not stated.")})

    assert checked(tree, text) == []


# R9: a quote is 20 to 800 characters, verbatim, whole sentences or lines; a call's quote
# names its turn's heading exactly and lies within that turn's words.

CALL_ID = DOC_IDS["call_q2"]


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
    text = readings_text(Q2, i3_6=Reading(DOC_IDS["ten_q_1"], "none", quotes=((quote, attribution),)))
    line = line_of(text, ">") if where == "quote" else line_of(text, "— ")

    assert checked(tree, text) == [(line, message)]


def test_a_speakers_later_turn_is_named_by_the_same_heading(tree):
    text = readings_text(
        Q2,
        i8_2=Reading(
            DOC_IDS["call_q1"],
            "none",
            quotes=(
                (CFO_GUIDANCE, f"{CALL_ID}, David Zinsner (executive)"),
                (CFO_SUPPLY, f"{CALL_ID}, David Zinsner (executive)"),
            ),
        ),
    )

    assert checked(tree, text) == []


# R10: an observation carries no valuation, forecast or advice wording; quotes are the
# issuer's words and never checked against it; no quote is repeated in an item.


def test_an_observation_carries_no_valuation_forecast_or_advice_wording(tree):
    text = readings_text(
        Q2, i3_3=Reading(DOC_IDS["ten_q_1"], "none", "The upside makes the shares a Buy; buy.")
    )

    assert checked(tree, text) == [
        (
            lines_of(text, "3.3")[2],
            "an observation states facts only, without valuation, forecast or advice wording; found: "
            "upside, buy",
        )
    ]


def test_a_quote_may_carry_such_wording(tree):
    quote = "The Board recommends that stockholders vote for each of the director nominees."
    text = readings_text(
        FY,
        i5_3=Reading(
            "none", "none", "The proxy statement names the director nominees.", ((quote, DOC_IDS["proxy"]),)
        ),
    )

    assert checked(tree, text, FY) == []


@pytest.mark.parametrize(
    "again",
    [QUOTE_FILING[0], QUOTE_FILING[0].replace(" of ", "  of ")],
    ids=["same", "other-spacing"],
)
def test_a_quote_is_given_once_per_item(tree, again):
    text = readings_text(
        Q2,
        i3_6=Reading(DOC_IDS["ten_q_1"], "yellow", quotes=(QUOTE_FILING, (again, QUOTE_FILING[1]))),
    )
    second = lines_of(text, "3.6")[2] + 3

    assert checked(tree, text) == [(second, REPEATED_QUOTE)]


def test_one_quote_may_serve_several_items_and_documents(tree):
    text = readings_text(
        Q2,
        i3_6=Reading(
            DOC_IDS["ten_q_1"], "yellow", quotes=(QUOTE_FILING, (TEN_Q_SUPPLY[0], DOC_IDS["ten_q_1"]))
        ),
        i3_7=Reading(DOC_IDS["ten_q_1"], "yellow", quotes=(QUOTE_FILING,)),
    )

    assert checked(tree, text) == []


def test_the_wording_rule_reads_whole_words_and_names_each_term_once():
    assert wording_problems(7, "Shares look undervalued; we Recommend a BUY, then buy more.") == [
        Problem(
            7,
            "an observation states facts only, without valuation, forecast or advice wording; found: "
            "undervalued, recommend, buy",
        )
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
SUPPLY = TEN_Q_SUPPLY[0]
CAPEX = COMMENTARY_CAPEX[0]
DERIVED = f"Quarterly Report\nLiquidity\n{SUPPLY}\n{CAPEX} We continue to invest.\n"


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
    assert quoted(CAPEX.replace("$9", "$10")) == [(5, NOT_FOUND)]
    assert quoted(CAPEX.lower()) == [(5, NOT_FOUND)]


def test_whitespace_between_words_may_differ():
    assert quoted(f"Liquidity {SUPPLY}") == []
    assert (
        quoted(
            "Supply of\tsubstrates and\u00a0certain  specialty chemicals remained tight during the quarter."
        )
        == []
    )


SUFFICIENT = "Supply of substrates remained sufficient for the quarter."


@pytest.mark.parametrize(
    ("quote", "derived"),
    [
        (SUPPLY.replace("substrates", "sub\u00adstrates"), DERIVED),  # a soft hyphen
        (SUPPLY.replace("specialty", "special\u200bty"), DERIVED),  # a zero-width space
        (SUFFICIENT.replace("ffi", "\ufb03"), f"{SUFFICIENT}\n"),  # a ligature the text writes as letters
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


def test_only_a_calls_quote_names_a_speaker():
    assert quoted(SUPPLY, speaker="David Zinsner (executive)") == [(6, NO_SPEAKER)]
