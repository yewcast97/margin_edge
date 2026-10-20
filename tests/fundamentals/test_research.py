"""``research``: the per-document report grammar and the rules each quote keeps against its derived text.

Reports are written out as text; derived texts are small strings written the way
``text.py`` derives documents (lines trimmed, single spaces, a final line break). Every
expected message is written out, so a change of wording fails here first.
"""

import pytest

from market_state_research.fundamentals.script import research
from market_state_research.fundamentals.script.research import (
    FIELD_TITLES,
    FIELDS,
    WORDING,
    Problem,
    Quote,
    Turn,
    parse_report,
    quote_problems,
    written,
)

DOC = "10-Q_2026-06-27_0000050863-26-000157_intc-20260627"
NOT_WHOLE = (
    "a quote must be whole sentences, or whole lines of an HTML document or a call transcript: it must "
    "start, never in lowercase even after a list glyph, at such a line start or after a sentence end, "
    "a colon that ends a line or, in a call, its speaker's label, and end at such a line end or with "
    "a sentence end and whitespace, before text that does not start in lowercase even after a list glyph"
)
HEADINGS = (
    "the sections must be '## upstream_shortage', '## capacity_shortfall', '## capex_plans', "
    "'## capacity_expansion', '## earnings_guidance', '## pricing', '## backlog_contracts', "
    "'## product_ramp', '## margin_drivers', '## financing_methods' and '## customer_concentration', "
    "each once, in that order"
)
SUPPLY = "Supply of substrates and certain specialty chemicals remained tight during the quarter."
CAPEX = "We now expect net capital spending of approximately $9 billion for the full year."
DERIVED = f"Quarterly Report\nLiquidity\n{SUPPLY}\n{CAPEX} We continue to invest.\n"
CALL = (
    "Prepared Remarks\n"
    "Operator: Good afternoon, and welcome.\n"
    "Chief Executive Officer: Thank you. Revenue from our products grew in the quarter.\n"
)
VALID = f"""# {DOC}

## upstream_shortage

> Supply of substrates and certain specialty
> chemicals remained tight during the quarter.

## capacity_shortfall

None found.

## capex_plans

> {CAPEX}

> {CAPEX} We continue to invest.

## capacity_expansion

None found.

## earnings_guidance

None found.

## pricing

None found.

## backlog_contracts

None found.

## product_ramp

None found.

## margin_drivers

None found.

## financing_methods

None found.

## customer_concentration

None found.
"""


def problems(text: str, doc_id: str = DOC) -> list[tuple[int, str]]:
    _, found = parse_report(text, doc_id)
    return [(problem.line, problem.message) for problem in found]


def checked(
    text: str,
    derived: str = DERIVED,
    *,
    layout: bool = False,
    call: bool = False,
    turns: tuple[Turn, ...] | None = None,
) -> list[tuple[int, str]]:
    report, found = parse_report(text, DOC)
    assert found == []
    return [
        (problem.line, problem.message)
        for problem in quote_problems(report, derived, layout=layout, call=call, turns=turns)
    ]


def one_quote(quote: str, speaker: str | None = None) -> str:
    """A valid report whose first field holds one quote, every other field ``None found.``:
    the quote's ``>`` line is line 5, or line 6 after a ``Speaker:`` line on line 5."""
    lines = [f"# {DOC}", "", f"## {FIELDS[0]}", ""]
    lines.extend([f"Speaker: {speaker}"] if speaker is not None else [])
    lines.extend([f"> {quote}", ""])
    for name in FIELDS[1:]:
        lines.extend([f"## {name}", "", "None found.", ""])
    return "\n".join(lines)


# --------------------------------------------------------------------------- fields


def test_the_eleven_fields_in_their_order_and_titles():
    assert FIELDS == (
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
    assert [FIELD_TITLES[name] for name in FIELDS] == [
        "Upstream shortage",
        "Capacity shortfall",
        "Capex plans",
        "Capacity expansion",
        "Earnings guidance",
        "Pricing",
        "Backlog and contracts",
        "Product ramp",
        "Margin drivers",
        "Financing methods",
        "Customer concentration",
    ]
    assert set(FIELD_TITLES) == set(FIELDS)


def test_the_headings_message_names_every_field_in_its_order():
    named = [research.HEADINGS.index(f"'## {name}'") for name in FIELDS]

    assert named == sorted(named)
    assert research.HEADINGS.count("'## ") == len(FIELDS)
    assert research.HEADINGS == HEADINGS


# --------------------------------------------------------------------------- grammar
# VALID's lines: 1 the title, 3 upstream_shortage (quote on 5-6), 8 capacity_shortfall (10 None
# found.), 12 capex_plans (quotes on 14 and 16), 18 capacity_expansion (20 None found.),
# 22 earnings_guidance (24 None found.), 26 pricing (28 None found.), 30 backlog_contracts (32 None
# found.), 34 product_ramp (36 None found.), 38 margin_drivers (40 None found.), 42 financing_methods
# (44 None found.), 46 customer_concentration (48 None found.); 48 lines.


def test_a_valid_report_parses_into_its_quotes_with_their_lines():
    report, found = parse_report(VALID, DOC)

    assert found == []
    assert (report.doc_id, report.line) == (DOC, 1)
    assert report.field("upstream_shortage") == (Quote(5, SUPPLY),)
    assert report.field("capacity_shortfall") == ()
    assert report.field("capex_plans") == (Quote(14, CAPEX), Quote(16, f"{CAPEX} We continue to invest."))
    assert report.field("capacity_expansion") == ()
    assert report.field("earnings_guidance") == ()
    assert report.field("pricing") == ()
    assert report.field("backlog_contracts") == ()
    assert report.field("product_ramp") == ()
    assert report.field("margin_drivers") == ()
    assert report.field("financing_methods") == ()
    assert report.field("customer_concentration") == ()
    assert [name for name, _ in report.quotes()] == ["upstream_shortage", "capex_plans", "capex_plans"]


def test_blank_lines_before_the_title_trailing_spaces_and_crlf_are_accepted():
    text = "\n\n" + VALID.replace("\n", "  \r\n")

    report, found = parse_report(text, DOC)

    assert found == []
    assert report.line == 3
    assert report.field("upstream_shortage") == (Quote(7, SUPPLY),)


def test_a_speaker_line_names_the_quote_after_it():
    report, found = parse_report(one_quote("Thank you.", speaker="Chief Executive Officer"), DOC)

    assert found == []
    assert report.field("upstream_shortage") == (Quote(6, "Thank you.", "Chief Executive Officer", 5),)


def test_the_title_must_be_the_doc_id():
    assert problems(VALID, "other") == [
        (1, "the first line must be '# other', the report file's name without .md")
    ]
    assert problems(VALID.replace(f"# {DOC}", f"#  {DOC} extra")) == [
        (1, f"the first line must be '# {DOC}', the report file's name without .md")
    ]


def test_a_report_without_its_title_reads_its_first_line_as_the_body():
    without = VALID.removeprefix(f"# {DOC}\n\n")

    report, found = parse_report(without, DOC)

    assert [(problem.line, problem.message) for problem in found] == [
        (1, f"the first line must be '# {DOC}', the report file's name without .md")
    ]
    assert report.field("upstream_shortage") == (Quote(3, SUPPLY),)


def test_an_empty_report_lacks_its_title_and_every_section():
    assert problems("") == [
        (1, f"the first line must be '# {DOC}', the report file's name without .md"),
        (1, "the section '## upstream_shortage' is missing"),
        (1, "the section '## capacity_shortfall' is missing"),
        (1, "the section '## capex_plans' is missing"),
        (1, "the section '## capacity_expansion' is missing"),
        (1, "the section '## earnings_guidance' is missing"),
        (1, "the section '## pricing' is missing"),
        (1, "the section '## backlog_contracts' is missing"),
        (1, "the section '## product_ramp' is missing"),
        (1, "the section '## margin_drivers' is missing"),
        (1, "the section '## financing_methods' is missing"),
        (1, "the section '## customer_concentration' is missing"),
    ]


def test_sections_out_of_order_are_reported_once_and_still_read():
    swapped = VALID.replace("## upstream_shortage", "## SWAP").replace(
        "## capacity_shortfall", "## upstream_shortage"
    )
    swapped = swapped.replace("## SWAP", "## capacity_shortfall")

    report, found = parse_report(swapped, DOC)

    assert [(problem.line, problem.message) for problem in found] == [(8, HEADINGS)]
    assert report.field("capacity_shortfall") == (Quote(5, SUPPLY),)  # still checked


def test_an_unknown_or_repeated_section_is_refused_and_its_lines_skipped():
    assert problems(VALID + "\n## earnings_guidance\n\nNone found.\n") == [(50, HEADINGS)]
    assert problems(VALID.replace("## capex_plans", "## capex")) == [
        (12, HEADINGS),
        (48, "the section '## capex_plans' is missing"),
    ]


def test_a_section_holds_none_found_or_quotes():
    assert problems(VALID.replace("## capacity_shortfall\n\nNone found.\n", "## capacity_shortfall\n\n")) == [
        (8, "the section '## capacity_shortfall' must hold quotes or the line 'None found.'")
    ]
    guidance = "## earnings_guidance\n\nNone found.\n"
    both = VALID.replace(guidance, f"{guidance}\n> {CAPEX}\n")
    assert problems(both) == [(26, "a section holds either the line 'None found.' or quotes, never both")]
    twice = VALID.replace(guidance, f"{guidance}None found.\n")
    assert problems(twice) == [(25, "a section holds either the line 'None found.' or quotes, never both")]


def test_lines_outside_the_grammar_are_errors_at_their_line():
    assert problems(VALID.replace("## capacity_shortfall\n", "## capacity_shortfall\n- a list item\n")) == [
        (
            9,
            "a section holds only the line 'None found.', 'Speaker: NAME' lines and '> TEXT' lines, with "
            "blank lines between quotes",
        )
    ]
    assert problems(VALID.replace(f"# {DOC}\n", f"# {DOC}\n> A quote before any section.\n")) == [
        (2, "this line is outside the report's sections")
    ]


def test_an_empty_quote_line_is_an_error():
    text = VALID.replace("> chemicals remained", ">\n> chemicals remained")

    assert problems(text) == [(6, "an empty '>' line; a quote's lines each hold text")]


def test_a_speaker_needs_its_quote_right_after_it():
    alone = VALID.replace(
        "## capacity_shortfall\n\nNone found.\n", "## capacity_shortfall\n\nSpeaker: Jane Doe\n\n"
    )
    assert problems(alone) == [
        (8, "the section '## capacity_shortfall' must hold quotes or the line 'None found.'"),
        (10, "a 'Speaker:' line must be followed by its quote's '>' lines"),
    ]
    joined = VALID.replace(f"> {CAPEX}\n\n>", f"> {CAPEX}\nSpeaker: Jane Doe\n>")
    assert problems(joined) == [(15, "a blank line must separate two quotes")]


@pytest.mark.parametrize("name", ["Jane  Doe", "x" * 121, "Jane\u200bDoe", ""])
def test_a_speaker_is_written_on_one_line_with_single_spaces(name):
    assert problems(one_quote("Thank you.", speaker=name)) == [
        (
            5,
            "a speaker must be 1 to 120 printable characters without repeated spaces, as the derived text "
            "writes the name",
        )
    ]


def test_problems_are_returned_in_line_order_and_the_parsed_quotes_still_returned():
    text = VALID.replace("## capacity_shortfall\n", "## capacity_shortfall\nstray\n").replace(
        f"# {DOC}", "# x"
    )

    report, found = parse_report(text, DOC)

    assert [problem.line for problem in found] == [1, 9]
    assert report.field("capex_plans")[0].text == CAPEX


# --------------------------------------------------------------------------- quotes


def test_a_valid_reports_quotes_keep_every_rule():
    assert checked(VALID) == []


@pytest.mark.parametrize(
    ("quote", "length"),
    [("Too short here.", 15), ("A" * 801, 801)],
)
def test_a_quote_is_20_to_800_characters_after_normalisation(quote, length):
    assert checked(one_quote(quote)) == [
        (5, f"the quote is {length} characters long after normalisation; it must be 20 to 800")
    ]


def test_a_quote_must_be_found_verbatim():
    assert checked(one_quote(CAPEX.replace("$9", "$10"))) == [
        (5, "quote not found in the document's derived text")
    ]
    assert checked(one_quote(CAPEX.lower())) == [(5, "quote not found in the document's derived text")]


def test_whitespace_between_words_may_differ():
    assert (
        checked(
            one_quote(
                "Liquidity Supply of substrates and certain specialty chemicals remained tight "
                "during the quarter."
            )
        )
        == []
    )
    spaced = one_quote(
        "Supply of\tsubstrates and\u00a0certain  specialty chemicals remained tight during the quarter."
    )
    report, _ = parse_report(spaced, DOC)
    assert report.field("upstream_shortage") == (Quote(5, SUPPLY),)  # whitespace runs read as one space
    assert checked(spaced) == []


SUFFICIENT = "Supply of substrates remained sufficient for the quarter."


@pytest.mark.parametrize(
    ("quote", "derived"),
    [
        (SUPPLY.replace("substrates", "sub\u00adstrates"), DERIVED),  # a soft hyphen
        (SUPPLY.replace("specialty", "special\u200bty"), DERIVED),  # a zero-width space
        (SUFFICIENT.replace("ffi", "\ufb03"), f"{SUFFICIENT}\n"),  # a ligature the text writes as letters
    ],
)
def test_a_quote_is_spelt_as_the_derived_text_writes_it(quote, derived):
    assert checked(one_quote(SUFFICIENT), f"{SUFFICIENT}\n") == []
    assert checked(one_quote(quote), derived) == [
        (
            5,
            "the quote is not spelt as the derived text writes it: copy its characters exactly; only the "
            "whitespace between words may differ",
        )
    ]


@pytest.mark.parametrize(
    "quote",
    [
        "capital spending of approximately $9 billion for the full year.",  # starts mid-sentence
        "We now expect net capital spending of approximately $9 billion",  # ends mid-sentence
    ],
)
def test_a_quote_must_be_whole_sentences(quote):
    assert checked(one_quote(quote)) == [(5, NOT_WHOLE)]


def test_layout_mode_reads_a_line_break_as_whitespace():
    wrapped = "We now expect net capital spending\nof approximately $9 billion for the full year.\n"
    sentence = "We now expect net capital spending of approximately $9 billion for the full year."
    table = "Outlook\nNet capital spending approximately $9 billion\nGross margin approximately 36 percent\n"
    row = "Net capital spending approximately $9 billion"

    assert checked(one_quote(sentence), wrapped, layout=True) == []
    assert checked(one_quote(sentence), wrapped, layout=False) == []  # the next line continues in lowercase
    assert checked(one_quote(row), table, layout=False) == []  # a whole block line
    assert checked(one_quote(row), table, layout=True) == [(5, NOT_WHOLE)]  # no sentence end


def test_only_a_call_lets_a_quote_start_after_its_speakers_label():
    quote = "Thank you. Revenue from our products grew in the quarter."
    report = one_quote(quote, speaker="Chief Executive Officer")

    assert checked(report, CALL, call=True) == []
    assert checked(report, CALL, call=False) == [(6, NOT_WHOLE)]
    assert checked(one_quote(quote, speaker="Operator"), CALL, call=True) == [(6, NOT_WHOLE)]


def test_a_speaker_must_be_written_before_the_quote_as_the_text_spells_it():
    quote = "Revenue from our products grew in the quarter."
    assert checked(one_quote(quote, speaker="Chief Executive Officer"), CALL, call=True) == []
    assert checked(one_quote(quote, speaker="Chief Financial Officer"), CALL, call=True) == [
        (5, "the speaker is not found in the document's derived text before the quote")
    ]
    after = CALL + "Chief Financial Officer: Thanks.\n"
    assert checked(one_quote(quote, speaker="Chief Financial Officer"), after, call=True) == [
        (5, "the speaker is not found in the document's derived text before the quote")
    ]
    assert checked(one_quote(quote, speaker="Chief Executive Ofﬁcer"), CALL, call=True) == [
        (5, "the speaker is not found in the document's derived text before the quote")
    ]


def test_a_filing_may_name_a_speaker_written_before_the_quote():
    derived = f"Dave Zinsner, Chief Financial Officer\n“{CAPEX}”\n"

    assert checked(one_quote(CAPEX, speaker="Dave Zinsner"), derived) == []


def test_a_speaker_carries_no_valuation_forecast_or_advice_wording_but_a_quote_may():
    derived = "Buy Recommendation Desk\nWe recommend that customers buy our new processors this year.\n"
    quote = "We recommend that customers buy our new processors this year."

    assert checked(one_quote(quote), derived) == []
    assert checked(one_quote(quote, speaker="Buy Recommendation Desk"), derived) == [
        (
            5,
            "names state facts only, without valuation, forecast or advice wording; found: buy, "
            "recommendation",
        )
    ]
    assert WORDING.search("Holdings") is None and WORDING.search("price target") is not None


def test_written_finds_a_name_only_in_the_spelling_the_text_uses():
    assert written("Jane Doe", "Remarks\nJane\nDoe: Thank you.\n") == 8
    assert written("Jane Doe", "Remarks\n") is None
    assert written("ofﬁce", "the office\n") is None


def test_problems_are_ordered_by_line():
    text = one_quote("too short").replace(
        "## capex_plans\n\nNone found.", f"## capex_plans\n\n> {CAPEX.replace('$9', '$10')}"
    )
    report, found = parse_report(text, DOC)
    assert found == []

    result = quote_problems(report, DERIVED, layout=False, call=False)

    assert result == [
        Problem(5, "the quote is 9 characters long after normalisation; it must be 20 to 800"),
        Problem(13, "quote not found in the document's derived text"),
    ]


# --------------------------------------------------------------------------- call turns

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
    assert [(TURN_TEXT[turn.start : turn.end], turn.speaker, turn.role) for turn in TURNS] == [
        (OPERATOR_LINE, "Operator", "operator"),
        (ANALYST_LINE, "Jane Analyst", "analyst"),
        (f"{CFO_FIRST}\n{CFO_SECOND}", "David Zinsner", "executive"),
    ]


def test_an_executives_quote_naming_its_speaker_passes():
    assert checked(one_quote(CFO_FIRST, "David Zinsner"), TURN_TEXT, call=True, turns=TURNS) == []
    both = f"{CFO_FIRST} {CFO_SECOND}"
    assert checked(one_quote(both, "David Zinsner"), TURN_TEXT, call=True, turns=TURNS) == []


def test_a_call_quote_needs_its_speaker():
    assert checked(one_quote(CFO_FIRST), TURN_TEXT, call=True, turns=TURNS) == [
        (5, "a call quote needs a 'Speaker:' line naming the executive whose turn it quotes")
    ]


@pytest.mark.parametrize(
    ("quote", "speaker", "role"),
    [(ANALYST_LINE, "Jane Analyst", "analyst"), (OPERATOR_LINE, "Operator", "operator")],
)
def test_a_quote_from_a_turn_that_is_not_an_executives_fails(quote, speaker, role):
    assert checked(one_quote(quote, speaker), TURN_TEXT, call=True, turns=TURNS) == [
        (
            6,
            f"the quote lies in a turn whose role is {role}, not executive: quote only the issuer's "
            "executives",
        )
    ]


def test_the_speaker_must_be_the_turns_own():
    assert checked(one_quote(CFO_FIRST, "Jane Analyst"), TURN_TEXT, call=True, turns=TURNS) == [
        (
            5,
            "the quote lies in another speaker's turn: the 'Speaker:' line must be the name its heading "
            "writes",
        )
    ]


def test_a_quote_reaching_into_another_turn_or_its_heading_fails():
    # Either quote starts where the speaker's name is not yet written, so it is not found before it.
    not_before = (5, "the speaker is not found in the document's derived text before the quote")
    across_turns = (6, "a call quote must lie within the words of one speaker's turn, below its heading")
    across = f"{ANALYST_LINE} David Zinsner (executive) {CFO_FIRST}"
    assert checked(one_quote(across, "David Zinsner"), TURN_TEXT, call=True, turns=TURNS) == [
        not_before,
        across_turns,
    ]
    heading = f"David Zinsner (executive) {CFO_FIRST}"
    assert checked(one_quote(heading, "David Zinsner"), TURN_TEXT, call=True, turns=TURNS) == [
        not_before,
        across_turns,
    ]


def test_turn_rules_apply_only_with_turns():
    assert checked(one_quote(ANALYST_LINE), TURN_TEXT, call=True) == []
    assert checked(one_quote(ANALYST_LINE), TURN_TEXT, call=False) == []
