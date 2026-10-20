"""common/watchlist.py: a ticker domain's own watchlist and its strict, one-line errors.

Every watchlist read here is a file written below pytest's ``tmp_path``; no domain's real
``watchlist.json`` is read.
"""

import dataclasses
import inspect
import sys
from pathlib import Path

import pytest

from market_state_research.common import watchlist as watchlist_module
from market_state_research.common.watchlist import (
    SECTIONS,
    WATCHLIST_NAME,
    Watchlist,
    domain_watchlist,
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


def test_a_domain_reads_its_own_watchlist_and_no_other(tmp_path):
    assert (WATCHLIST_NAME, SECTIONS) == ("watchlist.json", ("stock",))
    domain = tmp_path / "stock_iv_regime"
    domain.mkdir()
    # Missing, a directory of that name, or a file: always the domain's own path.
    assert domain_watchlist(domain) == domain / "watchlist.json"
    (domain / "watchlist.json").mkdir()
    assert domain_watchlist(domain) == domain / "watchlist.json"
    other = tmp_path / "fundamentals"
    other.mkdir()
    written(tmp_path, '{"stock": ["AMD"]}')  # a shared file beside the domains is never read
    own = written(other, '{"stock": ["MU"]}')
    assert domain_watchlist(other) == own
    assert stock_tickers(domain_watchlist(other)) == ("MU",)


def test_a_domain_without_its_own_watchlist_is_told_so(tmp_path):
    written(tmp_path, '{"stock": ["AMD"]}')
    domain = tmp_path / "fundamentals"
    domain.mkdir()

    with pytest.raises(ValueError) as caught:
        stock_tickers(domain_watchlist(domain))

    assert str(caught.value) == f"{domain / 'watchlist.json'}: file not found"


def test_there_is_no_shared_watchlist_to_default_to():
    assert not hasattr(watchlist_module, "WATCHLIST_PATH")
    for function in (load_watchlist, stock_tickers):
        assert inspect.signature(function).parameters["path"].default is inspect.Parameter.empty


# --- valid watchlists ---------------------------------------------------------------------------


def test_a_valid_watchlist_keeps_the_file_order(tmp_path):
    path = written(tmp_path, '{"stock": ["INTC", "AMD", "BRK.B"]}\n')

    watchlist = load_watchlist(path)

    assert watchlist == Watchlist(stock=("INTC", "AMD", "BRK.B"))
    assert type(watchlist.stock) is tuple
    assert stock_tickers(path) == ("INTC", "AMD", "BRK.B")


def test_symbols_are_normalised_to_uppercase(tmp_path):
    path = written(tmp_path, '{\n  "stock": ["intc", "Amd", "bf-b"]\n}\n')

    assert load_watchlist(path) == Watchlist(stock=("INTC", "AMD", "BF-B"))


def test_an_empty_list_is_a_valid_watchlist(tmp_path):
    assert load_watchlist(written(tmp_path, '{"stock": []}')) == Watchlist(stock=())


def test_a_watchlist_is_frozen():
    watchlist = Watchlist(stock=("INTC",))
    with pytest.raises(dataclasses.FrozenInstanceError):
        watchlist.stock = ("AMD",)  # type: ignore[misc]


def test_reading_leaves_the_file_unchanged(tmp_path):
    content = b'{"stock": ["intc"]}'
    path = written(tmp_path, content)

    load_watchlist(path)
    stock_tickers(path)

    assert path.read_bytes() == content
    assert sorted(tmp_path.iterdir()) == [path]


# --- stock_tickers ------------------------------------------------------------------------------


def test_stock_tickers_refuses_an_empty_list(tmp_path):
    path = written(tmp_path, '{"stock": []}')

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
        pytest.param(b'{"stock": ["INTC\xff"]}', id="invalid-byte"),
        pytest.param('{"stock": ["INTC"]}'.encode("utf-16"), id="utf-16"),
        pytest.param('{"stock": ["Ä"]}'.encode("latin-1"), id="latin-1"),
    ],
)
def test_bytes_that_are_not_utf8_are_refused(tmp_path, content):
    assert refused(written(tmp_path, content)) == "not UTF-8"


@pytest.mark.parametrize(
    ("content", "message"),
    [
        pytest.param("", "invalid JSON: Expecting value (line 1, column 1)", id="empty"),
        pytest.param(
            '{"stock": ["INTC"]\n "MU"}',
            "invalid JSON: Expecting ',' delimiter (line 2, column 2)",
            id="missing-comma",
        ),
        pytest.param(
            "{'stock': []}",
            "invalid JSON: Expecting property name enclosed in double quotes (line 1, column 2)",
            id="single-quotes",
        ),
        pytest.param('{"stock": []} []', "invalid JSON: Extra data (line 1, column 15)", id="extra-data"),
        pytest.param(
            '﻿{"stock": []}',
            "invalid JSON: Unexpected UTF-8 BOM (decode using utf-8-sig) (line 1, column 1)",
            id="byte-order-mark",
        ),
        pytest.param("[" * 100_000 + "]" * 100_000, "invalid JSON: nested too deeply", id="deep-nesting"),
    ],
)
def test_invalid_json_names_the_problem_line_and_column(tmp_path, content, message):
    assert refused(written(tmp_path, content)) == message


def test_a_key_given_twice_is_refused_rather_than_silently_replaced(tmp_path):
    path = written(tmp_path, '{"stock": ["INTC"], "stock": []}')

    assert refused(path) == 'key "stock" appears more than once'


@pytest.mark.parametrize(
    "content",
    ['["INTC"]', '"INTC"', "null", "1", "true", LONG_INTEGER],
    ids=["array", "string", "null", "number", "boolean", "long-integer"],
)
def test_the_document_must_be_an_object(tmp_path, content):
    assert refused(written(tmp_path, content)) == 'expected a JSON object with a "stock" list'


@pytest.mark.parametrize(
    ("content", "keys"),
    [
        pytest.param('{"stock": [], "index": []}', '"stock", "index"', id="index-section"),
        pytest.param('{"stock": [], "etf": []}', '"stock", "etf"', id="extra"),
        pytest.param('{"index": ["SPX"]}', '"index"', id="missing-stock"),
        pytest.param("{}", "none", id="empty-object"),
        pytest.param('{"stocks": []}', '"stocks"', id="misspelt"),
        pytest.param('{"Stock": []}', '"Stock"', id="capitalised"),
        pytest.param('{"stock\\n": []}', '"stock\\n"', id="line-break-escaped"),
    ],
)
def test_the_one_key_must_be_stock(tmp_path, content, keys):
    message = refused(written(tmp_path, content))

    assert message == f'the one key must be "stock", got {keys}'


# --- list and item errors -----------------------------------------------------------------------


@pytest.mark.parametrize(
    "content",
    [
        pytest.param('{"stock": "INTC"}', id="string"),
        pytest.param('{"stock": {"INTC": 1}}', id="object"),
        pytest.param('{"stock": null}', id="null"),
        pytest.param(f'{{"stock": {LONG_INTEGER}}}', id="long-integer"),
    ],
)
def test_the_section_must_be_a_list(tmp_path, content):
    assert refused(written(tmp_path, content)) == '"stock" must be a list of ticker symbols'


@pytest.mark.parametrize(
    ("content", "where"),
    [
        pytest.param('{"stock": ["INTC", 1]}', '"stock" item 2', id="number"),
        pytest.param('{"stock": [null]}', '"stock" item 1', id="null"),
        pytest.param('{"stock": ["SPX", ["NDX"]]}', '"stock" item 2', id="list"),
        pytest.param('{"stock": [{"ticker": "INTC"}]}', '"stock" item 1', id="object"),
        pytest.param('{"stock": [true]}', '"stock" item 1', id="boolean"),
        pytest.param('{"stock": [1.5]}', '"stock" item 1', id="fraction"),
        pytest.param(f'{{"stock": [{LONG_INTEGER}]}}', '"stock" item 1', id="long-integer"),
        pytest.param(f'{{"stock": ["MU", -{LONG_INTEGER}]}}', '"stock" item 2', id="long-negative"),
    ],
)
def test_an_item_must_be_a_string(tmp_path, content, where):
    assert refused(written(tmp_path, content)) == f"{where} must be a string"


@pytest.mark.parametrize(
    ("content", "where"),
    [
        pytest.param('{"stock": ["INTC", ""]}', '"stock" item 2 ""', id="empty"),
        pytest.param('{"stock": ["../INTC"]}', '"stock" item 1 "../INTC"', id="path"),
        pytest.param('{"stock": ["IN TC"]}', '"stock" item 1 "IN TC"', id="inner-space"),
        pytest.param('{"stock": ["^SPX"]}', '"stock" item 1 "^SPX"', id="caret"),
        pytest.param('{"stock": ["1ABC"]}', '"stock" item 1 "1ABC"', id="leading-digit"),
        pytest.param('{"stock": ["ÄBC"]}', '"stock" item 1 "ÄBC"', id="non-ascii"),
        pytest.param('{"stock": ["\\u00df"]}', '"stock" item 1 "ß"', id="folds-to-ascii"),
        pytest.param('{"stock": ["A\\nB"]}', '"stock" item 1 "A\\nB"', id="line-break"),
        pytest.param('{"stock": ["A\\u202eB"]}', '"stock" item 1 "A\\u202eB"', id="bidi"),
    ],
)
def test_an_item_must_be_a_ticker_symbol(tmp_path, content, where):
    assert refused(written(tmp_path, content)) == f"{where}: {REJECTED}"


@pytest.mark.parametrize(
    ("content", "message"),
    [
        pytest.param('{"stock": ["INTC", "AMD", "INTC"]}', '"stock" item 3 repeats INTC', id="same"),
        pytest.param('{"stock": ["INTC", "intc"]}', '"stock" item 2 repeats INTC', id="case"),
    ],
)
def test_a_repeated_symbol_is_refused(tmp_path, content, message):
    assert refused(written(tmp_path, content)) == message


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

    path = written(tmp_path, '{"stock": []}', name)
    with pytest.raises(ValueError) as caught:
        stock_tickers(path)
    assert str(caught.value) == f"{tmp_path}/{escaped} lists no stock tickers; pass a ticker"


def test_other_filesystem_errors_propagate_unchanged(tmp_path):
    with pytest.raises(IsADirectoryError):
        load_watchlist(tmp_path)
