"""script/text.py: quote normalisation and verbatim quote location in derived text.

A quote is located as the bot copied it from the derived text: whitespace runs match
any whitespace, everything else matches itself exactly (case, smart quotes, dashes and
regex metacharacters included), and a quote never starts or ends inside a word, nor
between a letter and its combining accent. Offsets are code-point indices.

``sentence_bounded`` (sentence rule v2) accepts a located quote only when it is whole
sentences, or whole lines of a block document. Its cases are small derived texts written
here as derived text is, one line per block or layout line and a final ``"\\n"``, each read
in block mode, layout mode or both (``MODES``), so every clause of the rule, every
consequence and every residual case it cannot see is visible next to its case. The
shapes of the real fragments that rule v1 accepted (page lines wrapped inside a sentence,
a continuation line, a colon inside a sentence, an abbreviation inside a sentence, a
sentence split across two HTML blocks) are reproduced in small synthetic texts; no test
reads the real data. Pure string work; nothing touches the filesystem.
"""

import unicodedata
from dataclasses import FrozenInstanceError

import pytest

from market_state_research.fundamentals.script import text as text_module
from market_state_research.fundamentals.script.text import (
    BULLETS,
    CLOSERS,
    OPENERS,
    QUOTE_MAX,
    QUOTE_MIN,
    SENTENCE_ENDS,
    Location,
    html_text,
    locate,
    normalise,
    plain_text,
    sentence_bounded,
)

DERIVED = (
    "Intel Corporation designs and manufactures essential technologies.\n"
    "Our products include Intel Core Ultra processors for AI PCs.\n"
    "Revenue in the third quarter was $13.7 billion, up 3% year over year.\n"
)


def found(quote: str, derived: str) -> str:
    """The derived span a quote was located at; fails when it was not found."""
    location = locate(quote, derived)
    assert location is not None
    return derived[location.start : location.end]


def test_quote_limits():
    assert (QUOTE_MIN, QUOTE_MAX) == (20, 800)


# --------------------------------------------------------------------------- normalise


@pytest.mark.parametrize(
    ("quote", "expected"),
    [
        pytest.param("  Intel  Foundry\n", "Intel Foundry", id="trimmed-and-collapsed"),
        pytest.param("Intel\nFoundry\r\nservices", "Intel Foundry services", id="line-breaks"),
        pytest.param("Intel\tFoundry services and　more", "Intel Foundry services and more", id="spaces"),
        pytest.param("manu­facturing", "manufacturing", id="soft-hyphen"),
        pytest.param("zero​width‌‍⁠﻿", "zerowidth", id="zero-width"),
        pytest.param("ﬁnancial ﬂow eﬀect", "financial flow effect", id="ligatures"),
        pytest.param("a ​ b", "a b", id="zero-width-between-spaces"),
    ],
)
def test_normalise_cleans_and_collapses_whitespace(quote, expected):
    assert normalise(quote) == expected


def test_normalise_keeps_case_quotes_dashes_and_punctuation():
    quote = "Intel’s “AI” PCs – 3rd quarter — $13.7 (up 3%) café Ａ"
    assert normalise(quote) == quote


@pytest.mark.parametrize("quote", ["", "   ", "\n\t ", "­​﻿", " ⁠ "])
def test_normalise_of_a_quote_without_text_is_empty(quote):
    assert normalise(quote) == ""


def test_normalise_is_idempotent_and_leaves_derived_lines_unchanged():
    quote = "  Revenue in the\nthird ﬁscal quarter "
    assert normalise(normalise(quote)) == normalise(quote)
    for line in DERIVED.splitlines():
        assert normalise(line) == line


# --------------------------------------------------------------------------- locate


def test_locate_returns_the_span_and_its_code_point_offsets():
    quote = "Our products include Intel Core Ultra processors"
    location = locate(quote, DERIVED)
    start = DERIVED.index(quote)
    assert location == Location(start, start + len(quote))
    assert DERIVED[location.start : location.end] == quote


def test_location_is_an_immutable_value():
    location = Location(1, 2)
    assert location == Location(1, 2)
    with pytest.raises(FrozenInstanceError):
        location.start = 0


def test_locate_matches_across_a_line_break():
    quote = "essential technologies. Our products include"
    assert found(quote, DERIVED) == "essential technologies.\nOur products include"


@pytest.mark.parametrize(
    "quote",
    [
        "essential  technologies.\nOur\tproducts include",
        "essential technologies.\r\nOur products include",
        "  essential technologies. Our products include  ",
    ],
)
def test_locate_ignores_how_the_quotes_whitespace_was_copied(quote):
    assert found(quote, DERIVED) == "essential technologies.\nOur products include"


def test_locate_cleans_the_quote_like_the_derived_text():
    assert found("manu­factures essen​tial", DERIVED) == "manufactures essential"
    assert found("ﬁscal", html_text("<p>the &#xFB01;scal year</p>")) == "fiscal"


def test_locate_across_html_blocks_and_page_breaks():
    derived = html_text(
        "<p>Our foundry business depends on a limited number of suppliers of</p>"
        '<hr style="page-break-after:always"/><p>photomask and lithography equipment.</p>'
    )
    quote = "a limited number of suppliers of photomask and lithography equipment."
    assert found(quote, derived) == "a limited number of suppliers of\nphotomask and lithography equipment."


def test_locate_is_case_sensitive():
    assert locate("intel corporation designs", DERIVED) is None
    assert locate("INTEL CORPORATION DESIGNS", DERIVED) is None
    assert locate("processors for Al PCs", DERIVED) is None  # OCR's "Al" is not "AI"
    assert found("processors for AI PCs", DERIVED) == "processors for AI PCs"


@pytest.mark.parametrize(
    ("quote", "derived"),
    [
        pytest.param("tel Corporation", "Intel Corporation", id="starts-inside-a-word"),
        pytest.param("Intel Corp", "Intel Corporation", id="ends-inside-a-word"),
        pytest.param("2026 revenue", "12026 revenue", id="starts-after-a-digit"),
        pytest.param("revenue 202", "revenue 2026", id="ends-before-a-digit"),
        pytest.param("3 billion", "13 billion", id="digit-after-digit"),
        pytest.param("caf", "café", id="non-ascii-letter-after"),
        pytest.param("ber", "über", id="non-ascii-letter-before"),
        pytest.param("été", "l'étés", id="non-ascii-letters-at-both-ends"),
    ],
)
def test_locate_never_starts_or_ends_inside_a_word(quote, derived):
    assert locate(quote, derived) is None


SOCIETE = unicodedata.normalize("NFD", "Revenue from Societé Générale grew in the quarter.\n")


@pytest.mark.parametrize(
    "quote",
    [
        pytest.param("rale grew in the quarter", id="starts-after-an-accent"),
        pytest.param("Revenue from Societe", id="ends-before-an-accent"),
        pytest.param("́rale grew in the quarter", id="starts-with-the-accent-of-a-letter"),
        pytest.param("Revenue from Société G", id="ends-inside-the-next-word"),
    ],
)
def test_locate_never_cuts_a_letter_from_its_combining_accent(quote):
    """A PDF layer or OCR may write "é" as "e" and U+0301: the accent belongs to the word."""
    assert "é" in SOCIETE  # the accents are decomposed
    assert locate(unicodedata.normalize("NFD", quote), SOCIETE) is None
    assert locate(quote, unicodedata.normalize("NFC", SOCIETE)) is None  # as with precomposed letters


def test_a_quote_ending_with_a_combining_accent_ends_the_word_there():
    quote = unicodedata.normalize("NFD", "Revenue from Societé")
    assert locate(quote, SOCIETE) == Location(0, len(quote))
    assert locate(quote, SOCIETE.replace("́ ", "́s ", 1)) is None  # "Societés"
    whole = unicodedata.normalize("NFD", "Générale grew in the quarter")
    assert found(whole, SOCIETE) == whole


def test_a_match_inside_a_word_is_skipped_for_a_later_one():
    derived = unicodedata.normalize("NFD", "Générale grew; rale grew.\n")
    assert locate("rale grew", derived) == Location(derived.index("; ") + 2, derived.index("."))
    assert locate("ab ab", "xab ab ab ab") == Location(4, 9)  # the rejected start is not skipped past


def test_locate_treats_underscore_as_a_word_boundary():
    assert found("bar baz", "foo_bar baz") == "bar baz"
    assert locate("bar baz", "foo_bar baz") == Location(4, 11)
    assert found("foo", "foo_bar") == "foo"
    assert found("revenue 2026", "x_revenue 2026_y") == "revenue 2026"


@pytest.mark.parametrize(
    ("quote", "derived", "start"),
    [
        pytest.param("Intel", "(Intel)", 1, id="parentheses"),
        pytest.param("Intel", "Intel’s", 0, id="apostrophe-after"),
        pytest.param("2026", "Q2-2026.", 3, id="hyphen-and-period"),
        pytest.param("AI", "“AI”", 1, id="smart-quotes"),
        pytest.param("Corporation", "Intel Corporation", 6, id="space"),
    ],
)
def test_locate_accepts_punctuation_and_whitespace_as_word_boundaries(quote, derived, start):
    assert locate(quote, derived) == Location(start, start + len(quote))


def test_locate_guards_only_alphanumeric_ends_of_the_quote():
    # A quote that starts or ends with punctuation may touch a word there.
    assert found("(Intel", "x(Intel)") == "(Intel"
    assert found("quarter.", "the quarter.Next") == "quarter."
    assert found("$13", "US$13") == "$13"
    assert found("_id", "user_id") == "_id"  # "_" is not alphanumeric: no guard
    assert found("Intel_", "Intel_x") == "Intel_"
    assert locate("_Intel", "x_Intel") == Location(1, 7)


@pytest.mark.parametrize(
    ("quote", "derived"),
    [
        pytest.param("Intel's AI", "Intel’s AI", id="apostrophe"),
        pytest.param("Intel’s AI", "Intel's AI", id="curly-apostrophe"),
        pytest.param('"AI" PCs', "“AI” PCs", id="double-quotes"),
        pytest.param("2025-2026 plan", "2025–2026 plan", id="en-dash"),
        pytest.param("growth -- again", "growth — again", id="em-dash"),
        pytest.param("café au lait", "café au lait", id="decomposed-accent"),
        pytest.param("ＡＩ PCs", "AI PCs", id="fullwidth"),
    ],
)
def test_locate_folds_no_smart_quotes_dashes_or_compatibility_characters(quote, derived):
    assert locate(quote, derived) is None
    assert locate(derived, derived) == Location(0, len(derived))


@pytest.mark.parametrize(
    "quote",
    [
        "$13.7 billion, up 3% year",
        "(up 3%) [a+b]* ^x|y? {2} \\d",
        "a.b",
        "x+y",
        "*",
        "C++ and .NET",
    ],
)
def test_locate_escapes_regex_metacharacters(quote):
    derived = f"text {quote} text\n"
    location = locate(quote, derived)
    assert location == Location(5, 5 + len(quote))


def test_locate_metacharacters_match_only_themselves():
    assert locate("13.7 billion", "1307 billion") is None
    assert locate("up 3% y.y", "up 3% yoy") is None
    assert locate("a+b", "aab") is None
    assert locate("C++", "C") is None


def test_locate_offsets_count_code_points_not_utf16_units_or_bytes():
    prefix = "\U0001f600\U0001d538\U00020000 "  # three astral characters and a space
    derived = f"{prefix}Intel Foundry services\n"
    location = locate("Intel Foundry", derived)
    assert location == Location(4, 17)
    assert derived[location.start : location.end] == "Intel Foundry"
    assert len(prefix.encode("utf-16-le")) // 2 == 7  # what a UTF-16 offset would have been


def test_locate_returns_the_first_occurrence():
    assert locate("net revenue", "net revenues fell; net revenue, net revenue.\n") == Location(19, 30)
    assert locate("ab ab", "x ab ab ab ab ab y") == Location(2, 7)


@pytest.mark.parametrize(
    ("quote", "derived"),
    [
        pytest.param("", DERIVED, id="empty-quote"),
        pytest.param(" \n\t", DERIVED, id="whitespace-quote"),
        pytest.param("­​", DERIVED, id="invisible-quote"),
        pytest.param("Intel Corporation", "", id="empty-derived"),
        pytest.param("Intel Corporation designs chips", DERIVED, id="absent"),
        pytest.param(DERIVED + " more", DERIVED, id="longer-than-derived"),
        pytest.param("manufactures", "manu\nfactures", id="split-word"),
        pytest.param("net revenue", "net-revenue", id="hyphen-is-not-whitespace"),
        pytest.param("net revenue", "netrevenue", id="whitespace-is-required"),
    ],
)
def test_locate_returns_none_for_an_empty_or_absent_quote(quote, derived):
    assert locate(quote, derived) is None


# --------------------------------------------------------------------------- sentence_bounded (rule v2)

# Every opening mark with the closing mark that ends it, as the cases below write them.
MARKS = (
    pytest.param('"', '"', id="quotation-mark"),
    pytest.param("'", "'", id="apostrophe"),
    pytest.param("“", "”", id="double-curly-quotes"),
    pytest.param("‘", "’", id="single-curly-quotes"),
    pytest.param("(", ")", id="parentheses"),
    pytest.param("[", "]", id="square-brackets"),
    pytest.param("{", "}", id="curly-brackets"),
    pytest.param("«", "»", id="guillemets"),
)
# The two ways the rule reads a line break: a block's end (HTML, captured pages) or a page's wrap.
MODES = (pytest.param(False, id="block"), pytest.param(True, id="layout"))


def whole(derived: str, quote: str, *, layout: bool = False, label: str | None = None) -> bool:
    """``sentence_bounded`` at the one place ``quote`` occurs, character for character, in
    ``derived``, which must read as derived text does."""
    assert plain_text(derived) == derived
    assert derived.count(quote) == 1
    start = derived.index(quote)
    return sentence_bounded(derived, start, start + len(quote), layout=layout, label=label)


def copied(derived: str, quote: str, *, layout: bool, label: str | None = None) -> bool:
    """``sentence_bounded`` where ``locate`` finds ``quote`` as the agent copies it (a line break
    as a space), as ``check`` checks it; the quote must occur once."""
    location = locate(quote, derived)
    assert location is not None and locate(quote, derived[location.end :]) is None
    return sentence_bounded(derived, location.start, location.end, layout=layout, label=label)


def test_sentence_boundary_characters():
    # In code point order; the curly marks, guillemets and the ellipsis written as escapes.
    assert "".join(sorted(SENTENCE_ENDS)) == "!.?…"
    assert "".join(sorted(CLOSERS)) == "\"')]}»’”"
    assert "".join(sorted(OPENERS)) == "\"'([{«‘“"
    assert {type(characters) for characters in (SENTENCE_ENDS, CLOSERS, OPENERS)} == {frozenset}
    assert {mark.values[0] for mark in MARKS} == OPENERS
    assert {mark.values[1] for mark in MARKS} == CLOSERS
    # Rule v2 has no set of start ends: a colon is handled by its own rule.
    assert not hasattr(text_module, "START_ENDS")


def test_list_markers():
    # The bullets, squares, circles, diamonds, arrows and check marks issuers set before list items,
    # and Word's Symbol and Wingdings bullets (private-use code points, written as escapes), in code
    # point order.
    assert "".join(sorted(BULLETS)) == "·•‣⁃∙■□▪▫►◆◇○●◦♦✓✔❖➢➤\uf0a7\uf0b7"
    assert type(BULLETS) is frozenset
    # No marker is a mark, a sentence end, a colon or semicolon, a dash or an asterisk (which also
    # mark empty table cells, wrapped clauses and footnotes), a letter, a digit or whitespace.
    assert not BULLETS & (SENTENCE_ENDS | CLOSERS | OPENERS | set(":;-‐‑‒–—―*"))
    assert not any(character.isalnum() or character.isspace() for character in BULLETS)


def test_layout_and_label_are_keyword_only_and_default_to_block_mode_without_a_label():
    derived = "Business outlook\nRevenue of $13.7 billion is expected.\n"
    start, end = derived.index("Revenue"), len(derived) - 1
    with pytest.raises(TypeError):
        sentence_bounded(derived, start, end, True)  # layout given by position
    assert sentence_bounded(derived, start, end) is True
    assert sentence_bounded(derived, start, end, layout=False, label=None) is True
    assert sentence_bounded(derived, start, end, layout=True) is False


# --- rule 1: the first character -------------------------------------------------------------------


@pytest.mark.parametrize("layout", MODES)
@pytest.mark.parametrize(
    ("derived", "quote"),
    [
        pytest.param("demand rose in the quarter.\n", "demand rose in the quarter.", id="at-the-text-start"),
        pytest.param(
            "Outlook\nrevenue of $13.7 billion, up 3%\n",
            "revenue of $13.7 billion, up 3%",
            id="at-a-line-start",
        ),
        pytest.param("Prices fell. demand rose.\n", "demand rose.", id="after-a-sentence-end"),
        pytest.param("Prices fell. “demand rose.”\n", "“demand rose.”", id="after-its-opening-mark"),
        pytest.param("Prices fell. “demand rose.”\n", "demand rose.”", id="its-opening-mark-omitted"),
        pytest.param("Shipments grew in the U.S. market.\n", "market.", id="after-an-abbreviation"),
        pytest.param("Prices fell. iPhone sales rose.\n", "iPhone sales rose.", id="a-lowercase-brand"),
        pytest.param("Prices fell. élan rose.\n", "élan rose.", id="a-lowercase-accented-letter"),
    ],
)
def test_a_quote_never_starts_with_a_lowercase_letter(derived, quote, layout):
    """A quote that starts in lowercase continues a sentence ("market" after "U.S.", "above"
    after a wrapped PDF line); a sentence that really starts in lowercase, as one opening
    with a brand such as "iPhone", cannot be quoted from its start (a conservative refusal)."""
    assert not whole(derived, quote, layout=layout)


@pytest.mark.parametrize("layout", MODES)
@pytest.mark.parametrize(
    "first", ["Revenue", "2026", "$13.7", "• Revenue", "Été", "RTX", "“Revenue", "(Revenue", "中文"]
)
def test_a_quote_may_start_with_any_character_that_is_not_lowercase(first, layout):
    assert whole(
        f"Prices fell. {first} rose in the quarter.\n", f"{first} rose in the quarter.", layout=layout
    )


# Every list marker, named by its code point.
GLYPHS = [pytest.param(glyph, id=f"U+{ord(glyph):04X}") for glyph in sorted(BULLETS)]
# How an item's text follows its marker in derived text: attached (Intel's filings set the glyph and
# the item in two spans), after a space, on the next line (a marker in a block or a layout line of
# its own) or after an opening mark; each with the closing mark the item then ends with.
GAPS = [
    pytest.param("", "", id="attached"),
    pytest.param(" ", "", id="space"),
    pytest.param("\n", "", id="own-line"),
    pytest.param("“", "”", id="opening-mark"),
]


@pytest.mark.parametrize("layout", MODES)
@pytest.mark.parametrize(("gap", "closer"), GAPS)
@pytest.mark.parametrize("glyph", GLYPHS)
def test_a_list_marker_never_hides_that_an_item_starts_in_lowercase(glyph, gap, closer, layout):
    """A lowercase item ("▪we received…;") continues its lead-in ("…pursuant to the Agreement:")
    as the same item does where the page draws its marker with CSS and the derived text holds
    none; a capitalised item is a whole statement with its marker."""
    item = f"{glyph}{gap}we received $5.7 billion;{closer}"
    assert not whole(f"The Agreement took effect.\n{item}\n", item, layout=layout)
    capitalised = f"{glyph}{gap}We received $5.7 billion.{closer}"
    assert whole(f"The Agreement took effect.\n{capitalised}\n", capitalised, layout=layout)


# --- rule 2: the start -------------------------------------------------------------------------


@pytest.mark.parametrize("layout", MODES)
@pytest.mark.parametrize(("opener", "closer"), MARKS)
def test_a_quote_may_start_at_the_text_start_and_omit_its_opening_mark(opener, closer, layout):
    derived = f"{opener}Demand rose.{closer} Prices fell.\n"
    assert whole(derived, f"{opener}Demand rose.{closer}", layout=layout)
    assert whole(derived, "Demand rose.", layout=layout)


def test_a_line_start_is_a_quote_start_in_block_mode_only():
    """In layout mode a line break is a page's wrap: a sentence after a heading without
    punctuation can only be quoted together with that heading."""
    derived = "Business outlook\nRevenue of $13.7 billion is expected.\n"
    assert whole(derived, "Revenue of $13.7 billion is expected.")
    assert not whole(derived, "Revenue of $13.7 billion is expected.", layout=True)
    assert whole(derived, derived.rstrip("\n"), layout=True)


@pytest.mark.parametrize("layout", MODES)
def test_a_quote_may_start_after_a_sentence_end_and_whitespace(layout):
    assert whole("Revenue rose. Margins fell.\n", "Margins fell.", layout=layout)


def test_a_line_break_after_a_sentence_end_is_whitespace_in_layout_mode():
    derived = "Revenue rose in the quarter.\nMargins fell.\n"
    assert whole(derived, "Margins fell.", layout=True)
    assert whole(derived, "Margins fell.")  # a block line start


@pytest.mark.parametrize("layout", MODES)
def test_a_quote_starting_right_after_a_sentence_end_is_not_whole(layout):
    assert not whole("Revenue rose.Margins fell.\n", "Margins fell.", layout=layout)


def test_whitespace_back_to_the_text_start_is_a_start():
    assert sentence_bounded(" Margins fell.", 1, 14)
    assert sentence_bounded("\nMargins fell.", 1, 14, layout=True)


@pytest.mark.parametrize("layout", MODES)
@pytest.mark.parametrize(
    "before",
    [
        pytest.param(", ", id="comma"),
        pytest.param(" and ", id="word"),
        pytest.param("; ", id="semicolon"),
        pytest.param(" – ", id="dash"),
        pytest.param(" “ ", id="opening-mark-set-apart"),
        pytest.param(" (", id="opening-bracket-after-a-word"),
    ],
)
def test_a_quote_starting_inside_a_sentence_is_not_whole(before, layout):
    assert not whole(f"Revenue rose{before}Margins fell.\n", "Margins fell.", layout=layout)


@pytest.mark.parametrize("layout", MODES)
def test_a_colon_inside_a_line_starts_no_quote(layout):
    """ "Excluding the divestiture: we expect…" can be quoted only from "Excluding": after a
    colon inside a line the quote starts in the middle of the sentence, in lowercase or not."""
    derived = (
        "Excluding the divestiture: we expect revenue to grow. "
        "Excluding the divestiture: We expect margins to grow.\n"
    )
    assert not whole(derived, "we expect revenue to grow.", layout=layout)
    assert not whole(derived, "We expect margins to grow.", layout=layout)
    assert whole(derived, "Excluding the divestiture: we expect revenue to grow.", layout=layout)
    assert whole(derived, "Excluding the divestiture: We expect margins to grow.", layout=layout)


@pytest.mark.parametrize("layout", MODES)
@pytest.mark.parametrize(
    ("label", "accepted"),
    [
        pytest.param("Chief Executive Officer", True, id="its-own-label"),
        pytest.param(None, False, id="no-speaker"),
        pytest.param("Operator", False, id="the-label-of-another-line"),
        pytest.param("Executive Officer", False, id="part-of-the-label"),
        pytest.param("Chief Executive Officer:", False, id="the-label-with-its-colon"),
        pytest.param("chief executive officer", False, id="other-letter-case"),
    ],
)
def test_a_quote_may_start_after_the_colon_of_its_own_speakers_label(label, accepted, layout):
    derived = (
        "Operator: Our next question comes now.\nChief Executive Officer: Thank you. Demand was strong.\n"
    )
    assert whole(derived, "Thank you. Demand was strong.", layout=layout, label=label) is accepted


@pytest.mark.parametrize("layout", MODES)
def test_the_label_is_the_whole_text_of_the_colons_line_before_it(layout):
    assert whole("Operator : Thank you all.\n", "Thank you all.", layout=layout, label="Operator")
    derived = "Revenue rose. Operator: Thank you all.\n"
    assert not whole(derived, "Thank you all.", layout=layout, label="Operator")
    assert whole(derived, "Operator: Thank you all.", layout=layout)


def test_a_label_wrapped_across_layout_lines_is_not_found():
    # The colon's own line reads "Officer": a label the layout wrapped is not found (a refusal), and
    # "Officer" is no label either, as its line follows a wrap inside "Chief Executive Officer".
    derived = "Revenue rose.\nChief Executive\nOfficer: Thank you all.\n"
    assert not whole(derived, "Thank you all.", layout=True, label="Chief Executive Officer")
    assert not whole(derived, "Thank you all.", layout=True, label="Officer")
    assert whole(derived, "Thank you all.", label="Officer")  # in block mode the line is a block


def test_in_layout_mode_a_labels_line_must_itself_start_where_a_quote_may():
    """In layout mode "the colon's own line" is only a page's wrap, so the label opens its colon
    only when its line starts where a quote may: at the text's start, after a sentence end or
    after a colon that ends a layout line. The words of a wrapped line before an inline colon,
    written as a speaker (Intel's "About Intel" page: "Intel (Nasdaq: INTC) designs…"), open
    nothing."""
    about = "About Intel\nIntel (Nasdaq: INTC) designs and manufactures chips.\n"
    assert not whole(about, "INTC) designs and manufactures chips.", layout=True, label="Intel (Nasdaq")
    assert whole(about, "INTC) designs and manufactures chips.", label="Intel (Nasdaq")  # a block's start
    turn = "Chief Executive Officer: Thank you all.\n"
    for before in ("", "Revenue rose.\n", "Prepared remarks:\n"):
        assert whole(before + turn, "Thank you all.", layout=True, label="Chief Executive Officer")
    after_heading = "Prepared remarks\nChief Executive Officer: Thank you all.\n"
    assert not whole(after_heading, "Thank you all.", layout=True, label="Chief Executive Officer")
    assert whole(after_heading, "Thank you all.", label="Chief Executive Officer")


@pytest.mark.parametrize("layout", MODES)
def test_a_label_that_starts_in_lowercase_opens_no_colon(layout):
    derived = "Revenue rose.\noperator: Thank you all.\n"
    assert not whole(derived, "Thank you all.", layout=layout, label="operator")


@pytest.mark.parametrize("layout", MODES)
def test_residual_a_speaker_written_as_the_words_before_an_inline_colon_reads_as_a_label(layout):
    """Residual, documented: the label is matched as text, so a clause before an inline colon at a
    statement's start, written as the speaker, reads as a speaker's label. ``check`` passes a
    label for a call document only, and research writes as a speaker only the name the
    document gives."""
    derived = "Revenue rose.\nOur message is simple: Demand is strong.\n"
    assert whole(derived, "Demand is strong.", layout=layout, label="Our message is simple")
    assert not whole(derived, "Demand is strong.", layout=layout)


@pytest.mark.parametrize("layout", MODES)
def test_a_quote_after_a_label_may_omit_its_opening_mark(layout):
    derived = "Operator: “Our next question comes now.”\n"
    assert whole(derived, "Our next question comes now.”", layout=layout, label="Operator")
    assert not whole(derived, "Our next question comes now.”", layout=layout)


def test_in_layout_mode_a_quote_may_start_after_a_colon_that_ends_a_line():
    """A speaker heading of prepared remarks, "...of Intel (bio):", ends its layout line."""
    derived = "Chief Executive Officer of Intel (bio):\nQ2 was another quarter of solid execution.\n"
    assert whole(derived, "Q2 was another quarter of solid execution.", layout=True)
    assert whole(derived, "Q2 was another quarter of solid execution.")  # a block line start


def test_residual_a_colon_inside_a_sentence_that_ends_a_layout_line_reads_as_a_headings():
    """Residual, documented: the rule cannot tell a heading's colon from a colon inside a
    sentence that the page happens to wrap after, before a capital; research must not start a
    quote there."""
    derived = "Excluding the divestiture:\nWe expect margins to grow.\n"
    assert whole(derived, "We expect margins to grow.", layout=True)


# --- rule 3: the end -------------------------------------------------------------------------------


@pytest.mark.parametrize("layout", MODES)
def test_a_quote_may_end_at_the_text_end(layout):
    assert sentence_bounded("Margins fell", 0, 12, layout=layout)  # a text that ends without "\n"
    assert sentence_bounded("Margins fell\n", 0, 12, layout=layout)
    assert sentence_bounded("Margins fell \n", 0, 12, layout=layout)  # only whitespace remains
    assert sentence_bounded("Margins fell “\n", 0, 12, layout=layout)  # an opening mark and whitespace


@pytest.mark.parametrize(
    ("next_line", "accepted"),
    [
        pytest.param("Tax rate 12 percent", True, id="capital"),
        pytest.param("12 percent tax rate", True, id="digit"),
        pytest.param("• Revenue up 3%", True, id="bullet"),
        pytest.param("▪Revenue up 3%", True, id="attached-bullet"),
        pytest.param("(Excluding Mobileye)", True, id="opening-mark-then-capital"),
        pytest.param("excluding Mobileye", False, id="lowercase"),
        pytest.param("• excluding Mobileye", False, id="bullet-then-lowercase"),
        pytest.param("▪excluding Mobileye", False, id="attached-bullet-then-lowercase"),
        pytest.param("▪\nexcluding Mobileye", False, id="bullet-on-its-own-line-then-lowercase"),
        pytest.param("(excluding Mobileye)", False, id="opening-mark-then-lowercase"),
        pytest.param("“excluding Mobileye”", False, id="quotation-mark-then-lowercase"),
    ],
)
def test_a_block_line_ends_a_quote_unless_the_next_line_starts_in_lowercase(next_line, accepted):
    """In block mode a whole line (a table row, a bullet, a heading) passes, with or without a
    sentence end, unless the next line continues it, after any opening marks and list markers.
    In layout mode a line end is whitespace: only a sentence end ends the quote, and the next
    line still must not start in lowercase."""
    row = f"Gross margin approximately 36 percent\n{next_line}\n"
    assert whole(row, "Gross margin approximately 36 percent") is accepted
    assert not whole(row, "Gross margin approximately 36 percent", layout=True)
    sentence = f"Gross margin was approximately 36 percent.\n{next_line}\n"
    assert whole(sentence, "Gross margin was approximately 36 percent.") is accepted
    assert whole(sentence, "Gross margin was approximately 36 percent.", layout=True) is accepted


@pytest.mark.parametrize("layout", MODES)
@pytest.mark.parametrize(
    ("after", "accepted"),
    [
        pytest.param(" Prices held.", True, id="capital"),
        pytest.param(" 3% of it came from servers.", True, id="digit"),
        pytest.param(" (Prices held.)", True, id="opening-mark-then-capital"),
        pytest.param(" market share held.", False, id="lowercase"),
        pytest.param(" (and prices held.)", False, id="opening-mark-then-lowercase"),
        pytest.param(" • Prices held.", True, id="bullet-then-capital"),
        pytest.param(" • and prices held.", False, id="bullet-then-lowercase"),
        pytest.param(" (▪and prices held.)", False, id="opening-mark-bullet-then-lowercase"),
    ],
)
def test_a_sentence_end_ends_a_quote_unless_the_next_word_starts_in_lowercase(after, accepted, layout):
    assert whole(f"Revenue rose.{after}\n", "Revenue rose.", layout=layout) is accepted


@pytest.mark.parametrize("layout", MODES)
@pytest.mark.parametrize(
    "quote",
    [
        pytest.param("Shipments grew in the U.S.", id="ends-at-the-abbreviation"),
        pytest.param("market! Prices held.", id="starts-after-the-abbreviation"),
    ],
)
def test_an_abbreviation_inside_a_sentence_ends_no_quote(quote, layout):
    """ "U.S." before the lowercase "market" is no sentence end, so a quote neither ends there
    nor starts after it; the whole sentence passes."""
    derived = "Shipments grew in the U.S. market! Prices held.\n"
    assert not whole(derived, quote, layout=layout)
    assert whole(derived, "Shipments grew in the U.S. market!", layout=layout)


def test_an_abbreviation_at_a_layout_line_end_ends_no_quote():
    derived = "Shipments grew in the U.S.\nmarket as well. Prices held.\n"
    assert not whole(derived, "Shipments grew in the U.S.", layout=True)
    assert not whole(derived, "Shipments grew in the U.S.")  # the next block line starts in lowercase
    assert whole(derived, "Shipments grew in the U.S.\nmarket as well.", layout=True)


@pytest.mark.parametrize("layout", MODES)
def test_residual_an_abbreviation_before_a_word_that_is_not_lowercase_reads_as_a_sentence_end(layout):
    """Residual, documented: the full stop of an abbreviation reads as a sentence end before
    anything that does not start in lowercase: a capitalised word ("U.S. Government", "2 p.m.
    PT"), a digit ("2025 vs. 2024", "15 U.S.C. 7262") or an opening mark before a capital ("N.V.
    (NXP)"); research must neither end nor start a quote there."""
    derived = (
        "Shipments to the U.S. Government rose. Sales held at 2 p.m. PT on the day. "
        "Revenue for 2025 vs. 2024 rose. It is filed under 15 U.S.C. 7262 in full. "
        "We bought it from NXP Semiconductors N.V. (NXP) in Europe.\n"
    )
    for cut in (
        "Shipments to the U.S.",
        "Sales held at 2 p.m.",
        "Revenue for 2025 vs.",
        "2024 rose.",
        "It is filed under 15 U.S.C.",
        "We bought it from NXP Semiconductors N.V.",
    ):
        assert whole(derived, cut, layout=layout), cut


@pytest.mark.parametrize("layout", MODES)
@pytest.mark.parametrize(
    "quote",
    [
        pytest.param("Net capital spending is expected to be between $8.", id="ends-at-a-decimal-point"),
        pytest.param("0 billion and $11.0 billion.", id="starts-after-a-decimal-point"),
    ],
)
def test_a_decimal_point_is_not_a_sentence_end(quote, layout):
    """``$8.`` cut from ``$8.0`` is refused: the character after the full stop is ``0``."""
    assert not whole(
        "Net capital spending is expected to be between $8.0 billion and $11.0 billion.\n",
        quote,
        layout=layout,
    )


@pytest.mark.parametrize("layout", MODES)
@pytest.mark.parametrize(
    ("derived", "quote"),
    [
        pytest.param(
            "We offer Core Ultra processors for notebooks.\n",
            "We offer Core Ultra processors",
            id="ends-mid-sentence",
        ),
        pytest.param(
            "We offer Core Ultra processors for notebooks.\n",
            "Core Ultra processors for notebooks.",
            id="starts-mid-sentence-at-a-capital",
        ),
        pytest.param(
            "Revenue rose in the quarter.Next\n",
            "Revenue rose in the quarter.",
            id="text-after-a-sentence-end",
        ),
        pytest.param("Intel’s revenue rose.\n", "s revenue rose.", id="after-an-apostrophe-in-a-word"),
        pytest.param(
            "We sell to the U.S.’s largest carriers.\n",
            "We sell to the U.S.",
            id="abbreviation-before-a-possessive",
        ),
        pytest.param(
            "Operator: “ Our next question comes.”\n",
            "Our next question comes.",
            id="after-a-mark-set-apart-by-a-space",
        ),
        pytest.param(
            "Highlights\n• Revenue of $13.7 billion, up 3%\n",
            "Revenue of $13.7 billion, up 3%",
            id="bullet-without-its-bullet",
        ),
        pytest.param(
            "Highlights\n▪Revenue of $13.7 billion, up 3%\n",
            "Revenue of $13.7 billion, up 3%",
            id="attached-bullet-without-its-bullet",
        ),
    ],
)
def test_a_quote_cut_inside_a_sentence_or_a_line_is_not_whole(derived, quote, layout):
    assert not whole(derived, quote, layout=layout)


@pytest.mark.parametrize("layout", MODES)
@pytest.mark.parametrize(("opener", "closer"), MARKS)
@pytest.mark.parametrize("kept", [pytest.param(True, id="kept"), pytest.param(False, id="omitted")])
def test_a_closing_mark_after_a_sentence_end_may_be_kept_or_omitted(opener, closer, kept, layout):
    quote = f"He said {opener}demand rose." + (closer if kept else "")
    assert whole(f"He said {opener}demand rose.{closer} Prices fell.\n", quote, layout=layout)


@pytest.mark.parametrize("layout", MODES)
@pytest.mark.parametrize(("opener", "closer"), MARKS)
@pytest.mark.parametrize("kept", [pytest.param(True, id="kept"), pytest.param(False, id="omitted")])
@pytest.mark.parametrize("after", [pytest.param("s", id="letter"), pytest.param("2", id="digit")])
def test_a_closing_mark_before_a_letter_or_a_digit_ends_no_quote(opener, closer, kept, after, layout):
    """A closing mark followed by a letter or a digit continues the sentence, as in ``the
    U.S.’s largest carriers``: the quote ends neither at the full stop nor after the mark."""
    quote = f"We sell to the {opener}U.S." + (closer if kept else "")
    assert not whole(f"We sell to the {opener}U.S.{closer}{after} largest carriers.\n", quote, layout=layout)


@pytest.mark.parametrize("layout", MODES)
@pytest.mark.parametrize(("opener", "closer"), MARKS)
def test_a_quote_may_start_after_a_closing_mark_and_whitespace(opener, closer, layout):
    assert whole(f"He said {opener}demand rose.{closer} Prices fell.\n", "Prices fell.", layout=layout)


@pytest.mark.parametrize("layout", MODES)
@pytest.mark.parametrize(("opener", "closer"), MARKS)
def test_a_quote_may_omit_its_opening_mark(opener, closer, layout):
    derived = f"Prices fell. {opener}Demand rose.{closer} Costs held.\n"
    assert whole(derived, "Demand rose.", layout=layout)
    assert whole(derived, f"{opener}Demand rose.{closer}", layout=layout)


@pytest.mark.parametrize("layout", MODES)
@pytest.mark.parametrize(("opener", "closer"), MARKS)
def test_a_quote_after_an_opening_mark_inside_a_sentence_is_not_whole(opener, closer, layout):
    """A quote cut after ``said that “`` starts in the middle of the sentence that holds it."""
    derived = f"He said that {opener}Demand remains strong.{closer}\n"
    assert not whole(derived, "Demand remains strong.", layout=layout)


@pytest.mark.parametrize("layout", MODES)
@pytest.mark.parametrize(("opener", "closer"), MARKS)
def test_opening_marks_are_skipped_only_directly_before_the_quote(opener, closer, layout):
    """Walking left from a quote's start, opening marks are skipped before the whitespace and
    only closing marks after it, so an opening mark set apart from the quote by a space never
    sits between it and a sentence end. The straight marks ``"`` and ``'`` are closing marks
    too: right after a sentence end they read as one, so the quote is whole (mechanical)."""
    assert not whole(f"Prices fell. {opener} Demand rose.\n", "Demand rose.", layout=layout)
    assert whole(f"Prices fell.{opener} Demand rose.\n", "Demand rose.", layout=layout) is (opener in CLOSERS)


# A closing run ".”)" after a sentence end, and an opening run "(“" before a sentence start.
CLOSING_RUN = "He said (“demand rose.”) Prices fell.\n"
OPENING_RUN = "Prices fell. (“Demand rose.”) Costs held.\n"
TRIPLE_RUN = "Prices fell. ([“Demand rose.”]) Costs held.\n"


@pytest.mark.parametrize("layout", MODES)
@pytest.mark.parametrize(
    ("derived", "quote"),
    [
        pytest.param(CLOSING_RUN, "Prices fell.", id="start-after-two-closers"),
        pytest.param(CLOSING_RUN, "He said (“demand rose.”)", id="two-closers-kept"),
        pytest.param(CLOSING_RUN, "He said (“demand rose.", id="two-closers-omitted"),
        pytest.param(OPENING_RUN, "(“Demand rose.”)", id="two-of-each-kept"),
        pytest.param(OPENING_RUN, "Demand rose.”)", id="two-openers-omitted"),
        pytest.param(OPENING_RUN, "Demand rose.", id="two-of-each-omitted"),
        pytest.param(OPENING_RUN, "Costs held.", id="start-after-two-closers-again"),
        pytest.param(TRIPLE_RUN, "Demand rose.", id="three-of-each-omitted"),
        pytest.param(TRIPLE_RUN, "([“Demand rose.”])", id="three-of-each-kept"),
        pytest.param(TRIPLE_RUN, "Costs held.", id="start-after-three-closers"),
    ],
)
def test_a_run_of_marks_is_skipped_as_a_single_mark_is(derived, quote, layout):
    """Each case keeps a whole run of marks or omits it whole: a run is skipped mark by mark."""
    assert whole(derived, quote, layout=layout)


@pytest.mark.parametrize("layout", MODES)
@pytest.mark.parametrize(
    ("derived", "quote"),
    [
        pytest.param("He said that (“Demand rose.”)\n", "Demand rose.", id="after-two-openers-mid-sentence"),
        pytest.param(
            "We sell to the (“U.S.”)s largest carriers.\n", "We sell to the (“U.S.”)", id="before-a-letter"
        ),
    ],
)
def test_a_run_of_marks_hides_no_cut(derived, quote, layout):
    assert not whole(derived, quote, layout=layout)


@pytest.mark.parametrize("layout", MODES)
@pytest.mark.parametrize(
    ("derived", "quote"),
    [
        pytest.param(
            "We call this plan “Project Alpha” and it continues.\n",
            "We call this plan “Project Alpha”",
            id="closing-quote",
        ),
        pytest.param(
            "Revenue (excluding Mobileye) rose 3%.\n",
            "Revenue (excluding Mobileye)",
            id="closing-parenthesis",
        ),
        pytest.param("The ‘AI PC’ era began.\n", "The ‘AI PC’", id="closing-single-quote"),
    ],
)
def test_a_closing_mark_ends_a_quote_only_after_a_sentence_end(derived, quote, layout):
    assert not whole(derived, quote, layout=layout)


@pytest.mark.parametrize("layout", MODES)
@pytest.mark.parametrize(
    ("derived", "quote"),
    [
        pytest.param(
            "Chief Executive Officer: Thank you.\n", "Chief Executive Officer", id="before-a-speakers-colon"
        ),
        pytest.param(
            "Chief Executive Officer: Thank you.\n", "Chief Executive Officer:", id="with-a-speakers-colon"
        ),
        pytest.param("We see three drivers: pricing and mix.\n", "We see three drivers", id="before-a-colon"),
        pytest.param("We see three drivers: pricing and mix.\n", "We see three drivers:", id="with-a-colon"),
    ],
)
def test_a_quote_ending_at_a_colon_mid_line_is_not_whole(derived, quote, layout):
    """A colon never ends a quote mid-line: it is no sentence end."""
    assert not whole(derived, quote, layout=layout)


def test_a_line_ending_with_a_colon_is_a_whole_line_in_block_mode_only():
    derived = "We see three drivers:\nPricing, mix and volume.\n"
    assert whole(derived, "We see three drivers:")
    assert not whole(derived, "We see three drivers:", layout=True)
    assert not whole("We see three drivers:\npricing and mix.\n", "We see three drivers:")
    for layout in (False, True):
        assert whole(derived, "Pricing, mix and volume.", layout=layout)  # after a line-ending colon
        assert whole(derived, derived.rstrip("\n"), layout=layout)


@pytest.mark.parametrize("layout", MODES)
@pytest.mark.parametrize("dots", [pytest.param("...", id="three-dots"), pytest.param("…", id="ellipsis")])
def test_three_dots_and_the_ellipsis_end_a_sentence(dots, layout):
    derived = f"Lead times for substrates fell{dots} Prices rose.\n"
    assert whole(derived, f"Lead times for substrates fell{dots}", layout=layout)
    assert whole(derived, "Prices rose.", layout=layout)
    assert not whole(derived, "Lead times for substrates fell", layout=layout)


# --- consequences --------------------------------------------------------------------------------

# A page of prepared remarks as a PDF lays it out, reproducing the shapes of Intel's real Q2 2026
# Prepared Remarks that rule v1 accepted as quotes: lines wrapped inside sentences, before a
# lowercase continuation or a capitalised one ("US"), and a figure cut by a wrap.
REMARKS_LINES = (
    "July 23, 2026 - Chief Executive Officer of Intel (bio):",
    "Q2 was another quarter of solid execution. Revenue, gross margin, and earnings per share were",
    "above our guidance. This marks the seventh consecutive quarter of exceeding our financial",
    "expectations.",
    "Turning to CapEx. Due to strong customer demand signals, we are raising our outlook for 2026 and",
    "now expect our capex to be more than $20 billion. At the midpoint of",
    "$16.3 billion, we forecast gross margin of 42 percent, a tax rate of 11 percent, and EPS of $0.38",
    "cents, all on a non-GAAP basis.",
    "In fact, as we look back from 2021 through 2026, our total capital spending in tools and space in the",
    "US is approaching $100 billion.",
)
REMARKS = "\n".join(REMARKS_LINES) + "\n"
# The line wrapped before the capitalised "US": a block document would read it as a whole line.
BEFORE_A_CAPITAL = REMARKS_LINES[8]


@pytest.mark.parametrize(
    "fragment",
    [
        pytest.param(REMARKS_LINES[4].partition(". ")[2], id="raising-outlook"),
        pytest.param(REMARKS_LINES[6], id="midpoint"),
        pytest.param(REMARKS_LINES[1], id="wrapped-line"),
        pytest.param(f"{REMARKS_LINES[2]} {REMARKS_LINES[3]}", id="continuation-start"),
        pytest.param(BEFORE_A_CAPITAL, id="wrap-before-a-capital"),
    ],
)
def test_the_real_pdf_fragments_are_refused_in_layout_mode(fragment):
    assert not copied(REMARKS, fragment, layout=True)


@pytest.mark.parametrize(
    "sentence",
    [
        "Q2 was another quarter of solid execution.",
        "Revenue, gross margin, and earnings per share were above our guidance.",
        "This marks the seventh consecutive quarter of exceeding our financial expectations.",
        "Due to strong customer demand signals, we are raising our outlook for 2026 and now expect our capex "
        "to be more than $20 billion.",
        "At the midpoint of $16.3 billion, we forecast gross margin of 42 percent, a tax rate of 11 percent, "
        "and EPS of $0.38 cents, all on a non-GAAP basis.",
        f"{BEFORE_A_CAPITAL} US is approaching $100 billion.",
    ],
)
def test_in_layout_mode_a_quote_runs_from_a_sentence_start_to_a_sentence_end_across_wraps(sentence):
    assert copied(REMARKS, sentence, layout=True)


def test_block_mode_would_take_a_line_wrapped_before_a_capital_for_a_whole_line():
    """Why page-wrapped text (a ``.txt`` filing's) is read in layout mode: its lines are the
    page's wraps, and a wrap before a capitalised word looks like a block's end."""
    assert copied(REMARKS, BEFORE_A_CAPITAL, layout=False)
    assert not copied(REMARKS, BEFORE_A_CAPITAL, layout=True)


def test_in_layout_mode_a_row_or_bullet_without_a_full_stop_is_quoted_through_the_next_sentence_end():
    derived = (
        "Outlook for the third quarter.\n"
        "• Revenue of $15.8 to $16.8 billion\n"
        "• Gross margin of 42 percent\n"
        "We expect both to rise.\n"
    )
    bullet = "• Revenue of $15.8 to $16.8 billion"
    assert not whole(derived, bullet, layout=True)
    assert whole(derived, bullet)  # a whole line of a block document
    assert whole(derived, derived[derived.index(bullet) :].rstrip("\n"), layout=True)


@pytest.mark.parametrize("layout", MODES)
def test_a_lead_in_and_its_lowercase_items_can_only_be_quoted_together(layout):
    """The real 10-K shape: a lead-in ending with a colon and items that continue it in lowercase
    after an attached glyph. Neither the lead-in nor an item is a whole statement alone, with
    or without its glyph; the lead-in with every item is."""
    lead_in = "On August 27, 2025, pursuant to the terms of the Agreement:"
    items = ("▪we received $5.7 billion; and", "▪we issued 275 million shares of our common stock.")
    derived = "\n".join((lead_in, *items, "Revenue rose in the quarter.")) + "\n"
    for cut in (lead_in, *items, *(item[1:] for item in items), f"{lead_in}\n{items[0]}"):
        assert not whole(derived, cut, layout=layout), cut
    assert whole(derived, "\n".join((lead_in, *items)), layout=layout)


@pytest.mark.parametrize("layout", MODES)
@pytest.mark.parametrize("marker", ["-", "–", "—", "*"])
def test_residual_a_lowercase_item_after_a_dash_or_an_asterisk_reads_as_whole(marker, layout):
    """Residual, documented: a dash or an asterisk is no list marker to the rule (they also mark
    empty table cells, wrapped clauses and footnotes), so a lowercase item after one reads as a
    statement of its own, and its lead-in as one before it; research quotes them together."""
    lead_in = "The Agreement took effect. Pursuant to its terms:"
    item = f"{marker} we received $5.7 billion."
    derived = f"{lead_in}\n{item}\n"
    assert whole(derived, item, layout=layout)
    assert whole(derived, lead_in) is True  # a block line before a line that starts with the marker


@pytest.mark.parametrize("layout", MODES)
def test_a_sentence_split_across_two_html_blocks_can_only_be_quoted_whole(layout):
    first = "Energy and water prices at our fabrication facilities in Arizona, Oregon, Ireland and Israel"
    second = "affect the cost of producing each wafer."
    derived = f"Item 1A. Risk Factors\n{first}\n{second}\nItem 7. Management’s Discussion and Analysis\n"
    assert not whole(derived, first, layout=layout)  # the next line continues it in lowercase
    assert not whole(derived, second, layout=layout)  # it starts in lowercase
    assert whole(derived, f"{first}\n{second}") is True
    # In layout mode the heading without punctuation before it belongs to the quote.
    assert whole(derived, f"{first}\n{second}", layout=True) is False
    assert whole(derived, f"Item 1A. Risk Factors\n{first}\n{second}", layout=True)


def test_residual_an_html_block_split_before_a_capital_reads_as_two_whole_lines():
    """Residual, documented: a sentence split across two HTML blocks whose second part starts
    with a capital ("Arizona") passes block by block; research must not quote one block."""
    derived = (
        "We plan to build two new fabrication facilities in\nArizona and Ohio over the next three years.\n"
    )
    assert whole(derived, "We plan to build two new fabrication facilities in")
    assert not whole(derived, "We plan to build two new fabrication facilities in", layout=True)


def test_in_layout_mode_a_running_page_header_belongs_to_the_sentence_after_it_or_inside_it():
    """A real page header ("CEO/CFO Earnings Call Comments", without punctuation) recurs on
    every page: the first sentence after it can only be quoted together with it, and a sentence
    it interrupts only with the header inside, verbatim, as the derived text holds it."""
    header = "CEO/CFO Earnings Call Comments"
    after = "During Q2, our factories exceeded internal volume targets."
    interrupted = ("Intel Foundry has driven down the cost", "of our primary SKU by roughly 50 percent.")
    derived = "\n".join(
        ("Revenue grew at Intel Foundry.", header, after, interrupted[0], header, interrupted[1])
    )
    derived += "\n"
    assert not whole(derived, after, layout=True)
    assert whole(derived, f"{header}\n{after}", layout=True)
    assert whole(derived, after)  # a block document's line start
    assert locate(" ".join(interrupted), derived) is None  # the header sits inside the sentence
    assert whole(derived, f"{interrupted[0]}\n{header}\n{interrupted[1]}", layout=True)


@pytest.mark.parametrize("layout", MODES)
def test_a_footnote_marker_after_a_full_stop_joins_its_two_sentences(layout):
    """A footnote digit set right after a full stop ("website.1 We…") is no whitespace, so neither
    sentence is whole alone: the two can only be quoted together, with the marker."""
    first, second = "Our report is on our website.", "We are subject to new disclosure rules."
    derived = f"{first}1 {second}\n"
    assert not whole(derived, first, layout=layout)
    assert not whole(derived, f"{first}1", layout=layout)
    assert not whole(derived, second, layout=layout)
    assert whole(derived, f"{first}1 {second}", layout=layout)


def test_a_line_before_a_heading_that_starts_in_lowercase_ends_no_quote_in_block_mode():
    """A heading or glossary term that starts in lowercase ("x86 Architecture") reads as a
    continuation: the line before it can only be quoted with it."""
    paragraph = "We design processors for every market."
    derived = f"{paragraph}\nx86 Architecture and Ecosystem\nOur processors lead the market.\n"
    assert not whole(derived, paragraph)
    assert whole(derived, f"{paragraph}\nx86 Architecture and Ecosystem")
    assert not whole(derived, paragraph, layout=True)  # a sentence end before a lowercase word


@pytest.mark.parametrize("layout", MODES)
@pytest.mark.parametrize("enumerator", ["(a)", "(i)", "(iv)"])
def test_an_item_lettered_in_lowercase_reads_as_a_continuation(enumerator, layout):
    """An enumerator such as "(a)" is an opening mark and a lowercase letter: the item cannot be
    quoted from its start, and the line before it cannot end there (in a filing's index of items
    or a table's footnotes); in block mode an item lettered in capitals or numbered passes."""
    heading = "Item 11. Executive Compensation"
    item = f"{enumerator} Incorporated by reference to the Proxy Statement."
    derived = f"{heading}\n{item}\n"
    assert not whole(derived, item, layout=layout)
    assert not whole(derived, heading, layout=layout)
    assert whole(derived, f"{heading}\n{item}", layout=layout)
    for capital in ("(A)", "(1)"):  # lettered in capitals or numbered: two whole block lines
        numbered = f"{heading}\n{capital} Incorporated by reference to the Proxy Statement.\n"
        assert whole(numbered, numbered.split("\n")[1])
        assert whole(numbered, heading)
    lines = [
        "Outlook",
        "Gross margin approximately 36 percent",
        "• Revenue of $13.7 billion, up 3%",
        "Processors for AI PCs, and",
        "PROVIDED ON THE SECOND-QUARTER 2026 CALL",
        "Chief Executive Officer: Thank you.",
    ]
    derived = "\n".join(lines) + "\n"
    starts = [derived.index(line) for line in lines]
    for first, start in enumerate(starts):
        for last in range(first, len(lines)):
            end = starts[last] + len(lines[last])
            assert sentence_bounded(derived, start, end), (first, last)
            # Read as a page's wraps, the lines are one sentence from the text start to its end.
            assert sentence_bounded(derived, start, end, layout=True) is (
                first == 0 and last == len(lines) - 1
            )


@pytest.mark.parametrize(
    ("quote", "block", "layout"),
    [
        pytest.param(
            "Our foundry depends on suppliers of\nPhotomask and lithography equipment.",
            True,
            True,
            id="one-sentence-across-a-break",
        ),
        pytest.param(
            "Lead times fell.\nOur foundry depends on suppliers of", True, False, id="to-a-line-end"
        ),
        pytest.param("Our foundry depends on suppliers of", True, False, id="one-line"),
        pytest.param(
            "Photomask and lithography equipment. Prices rose.\nLead times fell.",
            True,
            False,  # after the "of" of the line before
            id="sentences-across-a-break",
        ),
    ],
)
def test_a_quote_may_span_lines(quote, block, layout):
    derived = (
        "Lead times fell.\n"
        "Our foundry depends on suppliers of\n"
        "Photomask and lithography equipment. Prices rose.\n"
        "Lead times fell. Costs held.\n"
    )
    assert whole(derived, quote) is block
    assert whole(derived, quote, layout=True) is layout


# --- offsets and the first occurrence ------------------------------------------------------------


@pytest.mark.parametrize("layout", MODES)
def test_offsets_may_reach_both_ends_of_the_derived_text(layout):
    derived = "Revenue rose. Margins fell\n"
    assert sentence_bounded(derived, 0, len(derived), layout=layout)
    assert sentence_bounded(derived, 0, len("Revenue rose."), layout=layout)
    assert sentence_bounded(derived, len("Revenue rose. "), len(derived), layout=layout)
    assert not sentence_bounded(derived, len("Revenue rose. Margins "), len(derived), layout=layout)


@pytest.mark.parametrize("layout", MODES)
@pytest.mark.parametrize(
    ("start", "end"),
    [
        pytest.param(-1, 5, id="negative-start"),
        pytest.param(-3, -1, id="negative-end"),
        pytest.param(6, 5, id="start-after-end"),
        pytest.param(0, 15, id="end-after-the-text"),
        pytest.param(15, 15, id="start-after-the-text"),
    ],
)
def test_offsets_outside_the_derived_text_are_refused_on_one_line(start, end, layout):
    derived = "Revenue rose.\n"
    assert len(derived) == 14
    with pytest.raises(ValueError) as raised:
        sentence_bounded(derived, start, end, layout=layout, label="Revenue")
    message = str(raised.value)
    assert message == "a quote's offsets must satisfy 0 <= start <= end <= the derived text's length"
    assert "Revenue" not in message


@pytest.mark.parametrize("layout", MODES)
def test_the_rule_is_checked_at_the_first_occurrence_that_locate_reports(layout):
    """``check`` reads a quote at its first occurrence, so that occurrence decides,
    whatever the later ones are."""
    quote = "Intel Foundry revenue grew in the quarter."
    cut = "Unit sales rose and Intel Foundry revenue grew in the quarter.\n"
    line = "Intel Foundry revenue grew in the quarter.\n"
    for derived, accepted in ((cut + line, False), (line + cut, True)):
        assert plain_text(derived) == derived
        location = locate(quote, derived)
        assert location == Location(derived.index(quote), derived.index(quote) + len(quote))
        assert sentence_bounded(derived, location.start, location.end, layout=layout) is accepted
        later = derived.rindex(quote)
        assert sentence_bounded(derived, later, later + len(quote), layout=layout) is not accepted
