"""The ticker watchlists of market state research, maintained by the bot and ignored by Git:
the default tickers of a ticker domain's ``plan`` and ``fetch``.

Each domain that takes tickers reads its own ``watchlist.json``, beside its ``AGENTS.md``;
there is no shared watchlist to fall back on. The file holds exactly one section,
``stock``, a list of stock ticker symbols kept in file order. ``--watchlist PATH`` reads
another file; tickers given on a command line override every file, which is then not read.
Hypothesis exploration reads no watchlist, and the list of posters in ``posts`` is the
bot's to read, never this module's.
"""

import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from .text import printable, ticker_symbol

WATCHLIST_NAME = "watchlist.json"
SECTIONS = ("stock",)


def domain_watchlist(domain: Path) -> Path:
    """The watchlist a domain reads by default: its own ``watchlist.json`` in ``domain``, the
    domain's directory, whether or not it exists yet (a missing one is reported when read)."""
    return domain / WATCHLIST_NAME


@dataclass(frozen=True)
class Watchlist:
    """Normalised stock ticker symbols, in file order; the list may be empty."""

    stock: tuple[str, ...]


def _quoted(text: str) -> str:
    return json.dumps(text, ensure_ascii=False)


def _unique_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """A JSON object; a repeated key, which ``json`` would resolve silently, is refused."""
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"key {_quoted(key)} appears more than once")
        value[key] = item
    return value


def _section(name: str, items: object) -> tuple[str, ...]:
    """The normalised symbols of one section; problems raise ``ValueError`` without the path."""
    if not isinstance(items, list):
        raise ValueError(f'"{name}" must be a list of ticker symbols')
    symbols: list[str] = []
    for number, item in enumerate(items, start=1):
        where = f'"{name}" item {number}'
        if not isinstance(item, str):
            raise ValueError(f"{where} must be a string")
        try:
            symbol = ticker_symbol(item)
        except ValueError as error:
            raise ValueError(f"{where} {_quoted(item)}: {error}") from None
        if symbol in symbols:  # after normalisation, so "intc" repeats "INTC"
            raise ValueError(f"{where} repeats {symbol}")
        symbols.append(symbol)
    return tuple(symbols)


def _parse(path: Path) -> Watchlist:
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        raise ValueError("file not found") from None
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise ValueError("not UTF-8") from None
    try:
        # Decimal, not int: int() refuses a number longer than sys.get_int_max_str_digits()
        # with a message that names no item, and every number is refused below anyway.
        value: object = json.loads(text, object_pairs_hook=_unique_keys, parse_int=Decimal)
    except json.JSONDecodeError as error:
        raise ValueError(f"invalid JSON: {error.msg} (line {error.lineno}, column {error.colno})") from None
    except RecursionError:
        raise ValueError("invalid JSON: nested too deeply") from None
    if not isinstance(value, dict):
        raise ValueError('expected a JSON object with a "stock" list')
    if set(value) != set(SECTIONS):
        listed = ", ".join(_quoted(key) for key in value) or "none"
        raise ValueError(f'the one key must be "stock", got {listed}')
    return Watchlist(stock=_section("stock", value["stock"]))


def load_watchlist(path: Path) -> Watchlist:
    """Read and validate the watchlist at ``path``.

    Symbols are normalised with ``ticker_symbol`` and kept in file order. Every problem
    (a missing file, bytes that are not UTF-8, invalid JSON, a repeated key, keys other
    than exactly ``stock``, a section that is not a list, an item that is not a valid
    symbol, a symbol repeated) raises one ``ValueError`` line prefixed by the printable
    path. Other filesystem errors (for example permissions) propagate unchanged.
    """
    try:
        return _parse(path)
    except ValueError as error:
        raise ValueError(printable(f"{path}: {error}")) from None


def stock_tickers(path: Path) -> tuple[str, ...]:
    """The ``stock`` section of the watchlist at ``path``: a ticker domain's default tickers.

    An empty section raises ``ValueError``, since a ``plan`` without tickers has nothing to do.
    """
    stock = load_watchlist(path).stock
    if not stock:
        raise ValueError(f"{printable(str(path))} lists no stock tickers; pass a ticker")
    return stock
