"""common/watchlist.py: the repository-root watchlist, a domain's own, and their strict, one-line errors.

Every watchlist read here is a file written below pytest's ``tmp_path``; the real
``watchlist.json`` is never read, only its location is compared.
"""

import dataclasses
import inspect
import sys
from pathlib import Path

import pytest

from market_state_research.common import REPOSITORY_ROOT
from market_state_research.common.watchlist import (
    SECTIONS,
    WATCHLIST_PATH,
    Watchlist,
    default_watchlist,
    load_watchlist,
    stock_tickers,
)

REJECTED = "ticker must be a US symbol without path or query characters"
# More digits than int() converts, which would otherwise fail with a message naming no item.
LONG_INTEGER = "1" * (sys.get_int_max_str_digits() + 1)


def written(directory: Path, content: str | bytes, name: str = "watchlist.json") -> Path:
    """A watchlist file below ``directory`` holding ``content`` (text is written as UTF-8)."""
    path = directory / name
    path.write_bytes(content.encode() if isinstance(content, str) else content)
    return path


def refused(path: Path) -> str:
    """The one-line message ``load_watchlist`` raises for ``path``, without the path prefix."""
    with pytest.raises(ValueError) as caught:
        load_watchlist(path)
    message = str(caught.value)
    assert "\n" not in message
    assert message.startswith(f"{path}: ")
    return message.removeprefix(f"{path}: ")


# --- location -----------------------------------------------------------------------------------


def test_the_watchlist_is_the_tracked_file_at_the_repository_root():
    assert (REPOSITORY_ROOT / "pyproject.toml").is_file()
    assert (REPOSITORY_ROOT / "market_state_research" / "common" / "watchlist.py").is_file()
    assert WATCHLIST_PATH == REPOSITORY_ROOT / "watchlist.json"
    assert SECTIONS == ("stock", "index")


def test_both_readers_default_to_the_repository_root_watchlist():
    for function in (load_watchlist, stock_tickers):
        assert inspect.signature(function).parameters["path"].default == WATCHLIST_PATH


def test_a_domains_own_watchlist_overrides_the_repository_roots(tmp_path):
    domain = tmp_path / "market_regime"
    domain.mkdir()
    assert default_watchlist(domain) == WATCHLIST_PATH
    (domain / "watchlist.json").mkdir()  # a directory of that name is no watchlist
    assert default_watchlist(domain) == WATCHLIST_PATH
    other = tmp_path / "fundamentals"
    other.mkdir()
    own = written(other, '{"stock": ["MU"], "index": []}')
    assert default_watchlist(other) == own
    assert stock_tickers(default_watchlist(other)) == ("MU",)


# --- valid watchlists ---------------------------------------------------------------------------


def test_a_valid_watchlist_keeps_each_section_in_file_order(tmp_path):
    path = written(tmp_path, '{"stock": ["INTC", "AMD", "BRK.B"], "index": ["SPX", "NDX"]}\n')

    watchlist = load_watchlist(path)

    assert watchlist == Watchlist(stock=("INTC", "AMD", "BRK.B"), index=("SPX", "NDX"))
    assert type(watchlist.stock) is tuple and type(watchlist.index) is tuple
    assert stock_tickers(path) == ("INTC", "AMD", "BRK.B")


def test_the_key_order_of_the_file_does_not_matter(tmp_path):
    path = written(tmp_path, '{\n  "index": ["SPX"],\n  "stock": ["INTC"]\n}\n')

    assert load_watchlist(path) == Watchlist(stock=("INTC",), index=("SPX",))


def test_symbols_are_normalised_to_uppercase(tmp_path):
    path = written(tmp_path, '{"stock": ["intc", "Amd", "bf-b"], "index": ["spx"]}')

    assert load_watchlist(path) == Watchlist(stock=("INTC", "AMD", "BF-B"), index=("SPX",))


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        pytest.param('{"stock": [], "index": []}', Watchlist((), ()), id="both-empty"),
        pytest.param('{"stock": ["INTC"], "index": []}', Watchlist(("INTC",), ()), id="index-empty"),
        pytest.param('{"stock": [], "index": ["SPX"]}', Watchlist((), ("SPX",)), id="stock-empty"),
    ],
)
def test_empty_sections_are_allowed(tmp_path, content, expected):
    assert load_watchlist(written(tmp_path, content)) == expected


def test_a_watchlist_is_frozen():
    watchlist = Watchlist(stock=("INTC",), index=("SPX",))
    with pytest.raises(dataclasses.FrozenInstanceError):
        watchlist.stock = ("AMD",)  # type: ignore[misc]


def test_reading_leaves_the_file_unchanged(tmp_path):
    content = b'{"stock": ["intc"], "index": []}'
    path = written(tmp_path, content)

    load_watchlist(path)
    stock_tickers(path)

    assert path.read_bytes() == content
    assert sorted(tmp_path.iterdir()) == [path]


# --- stock_tickers ------------------------------------------------------------------------------


def test_stock_tickers_ignores_the_index_section(tmp_path):
    path = written(tmp_path, '{"stock": ["INTC"], "index": ["SPX", "NDX"]}')

    assert stock_tickers(path) == ("INTC",)


@pytest.mark.parametrize(
    "content",
    ['{"stock": [], "index": ["SPX"]}', '{"stock": [], "index": []}'],
    ids=["only-indexes", "both-empty"],
)
def test_stock_tickers_refuses_an_empty_stock_section(tmp_path, content):
    path = written(tmp_path, content)

    with pytest.raises(ValueError) as caught:
        stock_tickers(path)

    assert str(caught.value) == f"{path} lists no stock tickers; pass a ticker"


def test_stock_tickers_reports_an_invalid_watchlist_like_load_watchlist(tmp_path):
    path = tmp_path / "missing.json"

    with pytest.raises(ValueError) as caught:
        stock_tickers(path)

    assert str(caught.value) == f"{path}: file not found"


# --- file and JSON errors -----------------------------------------------------------------------


def test_a_missing_file_is_one_line(tmp_path):
    assert refused(tmp_path / "watchlist.json") == "file not found"


@pytest.mark.parametrize(
    "content",
    [
        pytest.param(b'{"stock": ["INTC\xff"], "index": []}', id="invalid-byte"),
        pytest.param('{"stock": ["INTC"], "index": []}'.encode("utf-16"), id="utf-16"),
        pytest.param('{"stock": ["Ä"], "index": []}'.encode("latin-1"), id="latin-1"),
    ],
)
def test_bytes_that_are_not_utf8_are_refused(tmp_path, content):
    assert refused(written(tmp_path, content)) == "not UTF-8"


@pytest.mark.parametrize(
    ("content", "message"),
    [
        pytest.param("", "invalid JSON: Expecting value (line 1, column 1)", id="empty"),
        pytest.param(
            '{"stock": ["INTC"]\n "index": ["SPX"]}',
            "invalid JSON: Expecting ',' delimiter (line 2, column 2)",
            id="missing-comma",
        ),
        pytest.param(
            "{'stock': [], 'index': []}",
            "invalid JSON: Expecting property name enclosed in double quotes (line 1, column 2)",
            id="single-quotes",
        ),
        pytest.param(
            '{"stock": [], "index": []} []',
            "invalid JSON: Extra data (line 1, column 28)",
            id="extra-data",
        ),
        pytest.param(
            '﻿{"stock": [], "index": []}',
            "invalid JSON: Unexpected UTF-8 BOM (decode using utf-8-sig) (line 1, column 1)",
            id="byte-order-mark",
        ),
        pytest.param("[" * 100_000 + "]" * 100_000, "invalid JSON: nested too deeply", id="deep-nesting"),
    ],
)
def test_invalid_json_names_the_problem_line_and_column(tmp_path, content, message):
    assert refused(written(tmp_path, content)) == message


def test_a_key_given_twice_is_refused_rather_than_silently_replaced(tmp_path):
    path = written(tmp_path, '{"stock": ["INTC"], "index": [], "stock": []}')

    assert refused(path) == 'key "stock" appears more than once'


@pytest.mark.parametrize(
    "content",
    ['["INTC"]', '"INTC"', "null", "1", "true", LONG_INTEGER],
    ids=["array", "string", "null", "number", "boolean", "long-integer"],
)
def test_the_document_must_be_an_object(tmp_path, content):
    assert refused(written(tmp_path, content)) == 'expected a JSON object with "stock" and "index" lists'


@pytest.mark.parametrize(
    ("content", "keys"),
    [
        pytest.param('{"stock": [], "index": [], "etf": []}', '"stock", "index", "etf"', id="extra"),
        pytest.param('{"stock": []}', '"stock"', id="missing-index"),
        pytest.param('{"index": []}', '"index"', id="missing-stock"),
        pytest.param("{}", "none", id="empty-object"),
        pytest.param('{"stocks": [], "index": []}', '"stocks", "index"', id="misspelt"),
        pytest.param('{"Stock": [], "index": []}', '"Stock", "index"', id="capitalised"),
        pytest.param('{"stock\\n": [], "index": []}', '"stock\\n", "index"', id="line-break-escaped"),
    ],
)
def test_the_keys_must_be_exactly_stock_and_index(tmp_path, content, keys):
    message = refused(written(tmp_path, content))

    assert message == f'keys must be exactly "stock" and "index", got {keys}'


# --- section and item errors --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("content", "section"),
    [
        pytest.param('{"stock": "INTC", "index": []}', "stock", id="stock-string"),
        pytest.param('{"stock": [], "index": {"SPX": 1}}', "index", id="index-object"),
        pytest.param('{"stock": null, "index": []}', "stock", id="stock-null"),
        pytest.param(f'{{"stock": [], "index": {LONG_INTEGER}}}', "index", id="index-long-integer"),
    ],
)
def test_a_section_must_be_a_list(tmp_path, content, section):
    assert refused(written(tmp_path, content)) == f'"{section}" must be a list of ticker symbols'


@pytest.mark.parametrize(
    ("content", "where"),
    [
        pytest.param('{"stock": ["INTC", 1], "index": []}', '"stock" item 2', id="number"),
        pytest.param('{"stock": [null], "index": []}', '"stock" item 1', id="null"),
        pytest.param('{"stock": [], "index": ["SPX", ["NDX"]]}', '"index" item 2', id="list"),
        pytest.param('{"stock": [{"ticker": "INTC"}], "index": []}', '"stock" item 1', id="object"),
        pytest.param('{"stock": [true], "index": []}', '"stock" item 1', id="boolean"),
        pytest.param('{"stock": [1.5], "index": []}', '"stock" item 1', id="fraction"),
        pytest.param(f'{{"stock": [{LONG_INTEGER}], "index": []}}', '"stock" item 1', id="long-integer"),
        pytest.param(
            f'{{"stock": [], "index": ["SPX", -{LONG_INTEGER}]}}', '"index" item 2', id="long-negative"
        ),
    ],
)
def test_an_item_must_be_a_string(tmp_path, content, where):
    assert refused(written(tmp_path, content)) == f"{where} must be a string"


@pytest.mark.parametrize(
    ("content", "where"),
    [
        pytest.param('{"stock": ["INTC", ""], "index": []}', '"stock" item 2 ""', id="empty"),
        pytest.param('{"stock": ["../INTC"], "index": []}', '"stock" item 1 "../INTC"', id="path"),
        pytest.param('{"stock": ["IN TC"], "index": []}', '"stock" item 1 "IN TC"', id="inner-space"),
        pytest.param('{"stock": [], "index": ["^SPX"]}', '"index" item 1 "^SPX"', id="caret"),
        pytest.param('{"stock": ["1ABC"], "index": []}', '"stock" item 1 "1ABC"', id="leading-digit"),
        pytest.param('{"stock": ["ÄBC"], "index": []}', '"stock" item 1 "ÄBC"', id="non-ascii"),
        pytest.param('{"stock": ["\\u00df"], "index": []}', '"stock" item 1 "ß"', id="folds-to-ascii"),
        pytest.param('{"stock": ["A\\nB"], "index": []}', '"stock" item 1 "A\\nB"', id="line-break"),
        pytest.param('{"stock": ["A\\u202eB"], "index": []}', '"stock" item 1 "A\\u202eB"', id="bidi"),
    ],
)
def test_an_item_must_be_a_ticker_symbol(tmp_path, content, where):
    assert refused(written(tmp_path, content)) == f"{where}: {REJECTED}"


@pytest.mark.parametrize(
    ("content", "message"),
    [
        pytest.param(
            '{"stock": ["INTC", "AMD", "INTC"], "index": []}', '"stock" item 3 repeats INTC', id="same"
        ),
        pytest.param('{"stock": ["INTC", "intc"], "index": []}', '"stock" item 2 repeats INTC', id="case"),
        pytest.param('{"stock": [], "index": ["SPX", "Spx"]}', '"index" item 2 repeats SPX', id="index"),
    ],
)
def test_a_symbol_repeated_within_a_section_is_refused(tmp_path, content, message):
    assert refused(written(tmp_path, content)) == message


@pytest.mark.parametrize(
    ("content", "symbol"),
    [
        pytest.param('{"stock": ["INTC", "SPX"], "index": ["SPX"]}', "SPX", id="same-case"),
        pytest.param('{"stock": ["intc"], "index": ["NDX", "INTC"]}', "INTC", id="after-normalising"),
    ],
)
def test_a_symbol_listed_in_both_sections_is_refused(tmp_path, content, symbol):
    assert refused(written(tmp_path, content)) == f'{symbol} is listed in both "stock" and "index"'


def test_the_stock_section_is_checked_before_the_index_section(tmp_path):
    path = written(tmp_path, '{"index": [1], "stock": [2]}')

    assert refused(path) == '"stock" item 1 must be a string'


# --- paths --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "escaped"),
    [
        pytest.param("list\nforged.json", "list\\nforged.json", id="line-break"),
        pytest.param("list\x1b[2J.json", "list\\x1b[2J.json", id="escape-sequence"),
        pytest.param("list‮nosj.json", "list\\u202enosj.json", id="right-to-left-override"),
    ],
)
def test_control_characters_in_the_path_are_escaped(tmp_path, name, escaped):
    with pytest.raises(ValueError) as caught:
        load_watchlist(tmp_path / name)
    assert str(caught.value) == f"{tmp_path}/{escaped}: file not found"

    path = written(tmp_path, '{"stock": [], "index": []}', name)
    with pytest.raises(ValueError) as caught:
        stock_tickers(path)
    assert str(caught.value) == f"{tmp_path}/{escaped} lists no stock tickers; pass a ticker"


def test_other_filesystem_errors_propagate_unchanged(tmp_path):
    with pytest.raises(IsADirectoryError):
        load_watchlist(tmp_path)
