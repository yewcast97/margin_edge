"""common/text.py: ticker normalisation and one-line message text."""

import pytest

from market_state_research.common.text import TICKER_PATTERN, printable, ticker_symbol

REJECTED = "^ticker must be a US symbol without path or query characters$"


def test_ticker_pattern_is_ascii_letters_digits_dots_and_hyphens_after_a_letter():
    assert TICKER_PATTERN.pattern == r"[A-Z][A-Z0-9.\-]{0,14}"


@pytest.mark.parametrize(
    ("value", "symbol"),
    [
        pytest.param("spx", "SPX", id="lowercase"),
        pytest.param("Intc", "INTC", id="mixed-case"),
        pytest.param("SPX", "SPX", id="already-normalised"),
        pytest.param("BRK.B", "BRK.B", id="dot-share-class"),
        pytest.param("brk.b", "BRK.B", id="dot-share-class-lowercase"),
        pytest.param("BF-B", "BF-B", id="hyphen-share-class"),
        pytest.param("A", "A", id="single-letter"),
        pytest.param("X1", "X1", id="digit-after-letter"),
        pytest.param("A" * 15, "A" * 15, id="fifteen-characters"),
    ],
)
def test_ticker_symbol_normalises_case_and_accepts_share_classes(value, symbol):
    assert ticker_symbol(value) == symbol
    assert ticker_symbol(symbol) == symbol  # normalising twice changes nothing


@pytest.mark.parametrize(
    "value",
    [
        pytest.param("", id="empty"),
        pytest.param("../TEST", id="parent-directory"),
        pytest.param("A/B", id="slash"),
        pytest.param("A\\B", id="backslash"),
        pytest.param("A?B", id="query"),
        pytest.param("A#B", id="fragment"),
        pytest.param("A&B", id="query-separator"),
        pytest.param("A%2F", id="percent-escape"),
        pytest.param("A_B", id="underscore"),
        pytest.param("1ABC", id="leading-digit"),
        pytest.param(".SPX", id="leading-dot"),
        pytest.param("-SPX", id="leading-hyphen"),
        pytest.param("A" * 16, id="sixteen-characters"),
        pytest.param("a" * 20, id="twenty-characters"),
        pytest.param("SPX\n", id="trailing-newline"),
        pytest.param(" SPX", id="leading-space"),
        pytest.param("S P", id="inner-space"),
        pytest.param("ÄBC", id="non-ascii-letter"),
    ],
)
def test_ticker_symbol_rejects_path_query_and_malformed_symbols(value):
    with pytest.raises(ValueError, match=REJECTED):
        ticker_symbol(value)


@pytest.mark.parametrize(
    ("value", "folded"),
    [
        pytest.param("\u00df", "SS", id="sharp-s"),
        pytest.param("\u017fpx", "SPX", id="long-s"),
        pytest.param("\u0131", "I", id="dotless-i"),
        pytest.param("\ufb00", "FF", id="ff-ligature"),
        pytest.param("TEST\u0130", "TEST\u0130", id="dotted-capital-i"),
    ],
)
def test_ticker_symbol_rejects_non_ascii_letters_that_fold_to_ascii(value, folded):
    assert value.upper() == folded  # what an unguarded str.upper() would have produced
    with pytest.raises(ValueError, match=REJECTED):
        ticker_symbol(value)


@pytest.mark.parametrize("value", [None, 1, b"SPX", ["SPX"]], ids=["none", "int", "bytes", "list"])
def test_ticker_symbol_rejects_values_that_are_not_text(value):
    with pytest.raises(ValueError, match=REJECTED):
        ticker_symbol(value)


@pytest.mark.parametrize(
    "text",
    [
        "plain ASCII text: 1 + 1 = 2",
        "Volatility Context — SPX · ±$113.34 (1.5%) Δ −",
        "emoji \U0001f4c8",
        "backslash \\ stays",
        "",
    ],
    ids=["ascii", "panel-symbols", "emoji", "backslash", "empty"],
)
def test_printable_leaves_printable_text_unchanged(text):
    assert printable(text) == text


@pytest.mark.parametrize(
    ("text", "escaped"),
    [
        pytest.param("a\nb", "a\\nb", id="line-feed"),
        pytest.param("a\rb", "a\\rb", id="carriage-return"),
        pytest.param("a\tb", "a\\tb", id="tab"),
        pytest.param("a\x00b", "a\\x00b", id="nul"),
        pytest.param("notes\x1b[2J.txt", "notes\\x1b[2J.txt", id="escape-sequence"),
        pytest.param("a\x7fb", "a\\x7fb", id="delete"),
        pytest.param("a\xa0b", "a\\xa0b", id="no-break-space"),
        pytest.param("notes\u202etxt.parquet", "notes\\u202etxt.parquet", id="right-to-left-override"),
        pytest.param("a\u2028b", "a\\u2028b", id="line-separator"),
        pytest.param("a\U000e0001b", "a\\U000e0001b", id="astral-tag-character"),
        pytest.param("Δ\n—", "Δ\\n—", id="only-the-control-character"),
    ],
)
def test_printable_escapes_every_non_printable_character(text, escaped):
    result = printable(text)

    assert result == escaped
    assert result.isprintable()
    assert "\n" not in result
