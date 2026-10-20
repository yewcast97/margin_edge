"""EODHD's options endpoints: the queries ``fetch`` sends and the pages they return.

Two endpoints are read, both as JSON:API-like pages ``{"meta": {...}, "data": [...],
"links": {"next": ...}}`` of at most ``PAGE_LIMIT`` records:

- ``contracts`` lists every contract ever listed (expired ones included) with its latest
  end-of-day values; a record's ``id`` is its OCC symbol.
- ``eod`` lists one record per contract per weekday (holidays included, as stale copies);
  a record's ``id`` is ``{OCC symbol}-{YYYY-MM-DD}``, the date being the session the record
  is for (``Record.date``). Its ``tradetime`` attribute is the contract's last trade date,
  which the ``tradetime`` filters select on: never the record's date.

Every query asks for the same ``FIELDS`` and is answered by one page of at most
``PAGE_LIMIT`` records; ``links.next`` is read only for whether it is null, and no further
page is ever requested: EODHD orders records only by the sort key, so records that tie on it
across a page boundary come back in another order on the next page, some twice and as many
never (verified live; see the domain's ``AGENTS.md``). A query whose page is full is narrowed
by the caller instead (``fetch``), so every URL is one this module built and checked.

Numbers are kept as the provider's literal text: a page is parsed with ``parse_float`` and
``parse_int`` set to ``str``, so ``0.10`` stays ``"0.10"`` and no value passes through a
float; NaN, infinities and repeated keys are refused. Every record is checked as it
arrives: its attributes are exactly ``FIELDS``, each a decimal number, a date or a word of
the expected form (or null where the provider leaves one blank), and its OCC symbol agrees
with its expiry, type and strike (``check_item``).
"""

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Final, Literal
from urllib.parse import urlencode

from market_state_research.common.text import printable

from .client import EodhdClient, EodhdError

BASE_URL: Final = "https://eodhd.com/api/mp/unicornbay/options"
FIELDS: Final = (
    "contract",
    "exp_date",
    "expiration_type",
    "type",
    "strike",
    "bid",
    "ask",
    "volume",
    "open_interest",
    "volatility",
    "delta",
    "tradetime",
)
NUMBER_FIELDS: Final = ("strike", "bid", "ask", "volume", "open_interest", "volatility", "delta")
PAGE_LIMIT: Final = 1000
Endpoint = Literal["contracts", "eod"]
ITEM_TYPES: Final[Mapping[Endpoint, str]] = {"contracts": "options-contracts", "eod": "options-eod"}

# Explicit ASCII classes: \d would also match other Unicode digits, which int() accepts.
DAY_PATTERN: Final = r"[0-9]{4}-[0-9]{2}-[0-9]{2}"
_DAY = re.compile(DAY_PATTERN, re.ASCII)
# JSON's number syntax: what parse_float and parse_int hand over.
_NUMBER = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?", re.ASCII)
_COUNT = re.compile(r"0|[1-9][0-9]*", re.ASCII)
_WORD = re.compile(r"[a-z]{1,20}", re.ASCII)
# An OCC symbol: root, expiry YYMMDD, C or P, strike x 1000 in eight digits.
OCC = re.compile(
    r"(?P<root>[A-Z][A-Z0-9.]{0,5})(?P<expiry>[0-9]{6})(?P<right>[CP])(?P<strike>[0-9]{8})", re.ASCII
)
_RECORD_ID = re.compile(rf"(?P<contract>[A-Z][A-Z0-9.]{{0,20}})-(?P<date>{DAY_PATTERN})", re.ASCII)
_RIGHTS: Final = {"C": "call", "P": "put"}


def _quoted(text: str) -> str:
    return json.dumps(text, ensure_ascii=True)


def _unique_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"key {_quoted(key)} appears more than once")
        value[key] = item
    return value


def _refuse_constant(name: str) -> object:
    raise ValueError(f"{name} is not a number")


def load_json(body: bytes) -> object:
    """A response body as JSON with every number kept as its literal text; ``ValueError`` otherwise."""
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError:
        raise ValueError("the body is not UTF-8") from None
    try:
        return json.loads(
            text,
            parse_float=str,
            parse_int=str,
            parse_constant=_refuse_constant,
            object_pairs_hook=_unique_keys,
        )
    except json.JSONDecodeError as error:
        raise ValueError(f"invalid JSON: {error.msg} (line {error.lineno}, column {error.colno})") from None
    except RecursionError:
        raise ValueError("invalid JSON: nested too deeply") from None


def parse_day(text: str) -> date:
    """A ``YYYY-MM-DD`` date of ASCII digits that exists; ``ValueError`` otherwise."""
    if not isinstance(text, str) or not _DAY.fullmatch(text):
        raise ValueError(f"{_quoted(str(text))} is not a YYYY-MM-DD date")
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise ValueError(f"{_quoted(text)} is not a date that exists") from None


def is_number(text: object) -> bool:
    return isinstance(text, str) and _NUMBER.fullmatch(text) is not None


@dataclass(frozen=True)
class Contract:
    """What an OCC symbol says: the root, the expiry, call or put and the strike."""

    root: str
    expiry: date
    right: Literal["call", "put"]
    strike: Decimal


def parse_occ(symbol: str) -> Contract:
    """The parts of an OCC symbol; ``ValueError`` when it is not one."""
    match = OCC.fullmatch(symbol) if isinstance(symbol, str) else None
    if match is None:
        raise ValueError(f"{_quoted(str(symbol))} is not an OCC option symbol")
    digits = match["expiry"]
    try:
        expiry = date(2000 + int(digits[:2]), int(digits[2:4]), int(digits[4:]))
    except ValueError:
        raise ValueError(f"{_quoted(symbol)} names an expiry that does not exist") from None
    right: Literal["call", "put"] = "call" if match["right"] == "C" else "put"
    return Contract(match["root"], expiry, right, Decimal(int(match["strike"])) / 1000)


def check_attributes(attributes: Mapping[str, object]) -> str | None:
    """Why ``attributes`` is not one record of ``FIELDS`` in the provider's forms, or None.

    ``contract``, ``exp_date``, ``type`` and ``strike`` are required; the market values may
    be null. The OCC symbol must agree with the expiry, the type and the strike.
    """
    if set(attributes) != set(FIELDS):
        extra = sorted(set(attributes) - set(FIELDS))
        absent = [name for name in FIELDS if name not in attributes]
        parts = []
        if absent:
            parts.append(f"lacks {', '.join(absent)}")
        if extra:
            parts.append(f"has {', '.join(_quoted(name) for name in extra)}")
        return f"the attributes must be exactly {', '.join(FIELDS)}: {'; '.join(parts)}"
    for name in ("contract", "exp_date", "type", "strike"):
        if attributes[name] is None:
            return f"{name} is null"
    for name, value in attributes.items():
        if value is not None and not isinstance(value, str):
            return f"{name} must be text, a number or null"
    try:
        contract = parse_occ(str(attributes["contract"]))
        expiry = parse_day(str(attributes["exp_date"]))
        if attributes["tradetime"] is not None:
            parse_day(str(attributes["tradetime"]))
    except ValueError as error:
        return str(error)
    for name in NUMBER_FIELDS:
        value = attributes[name]
        if value is not None and not is_number(value):
            return f"{name} {_quoted(str(value))} is not a decimal number"
    for name in ("volume", "open_interest"):
        value = attributes[name]
        if value is not None and not _COUNT.fullmatch(str(value)):
            return f"{name} {_quoted(str(value))} is not a whole number"
    kind = attributes["expiration_type"]
    if kind is not None and not _WORD.fullmatch(str(kind)):
        return f"expiration_type {_quoted(str(kind))} is not a lower-case word"
    if attributes["type"] not in ("call", "put"):
        return f"type {_quoted(str(attributes['type']))} is neither call nor put"
    if contract.expiry != expiry:
        return f"{attributes['contract']} expires {contract.expiry}, not on exp_date {expiry}"
    if contract.right != attributes["type"]:
        return f"{attributes['contract']} is a {contract.right}, not a {attributes['type']}"
    if Decimal(str(attributes["strike"])) != contract.strike:
        return f"{attributes['contract']} has strike {contract.strike}, not {attributes['strike']}"
    if contract.strike <= 0:
        return f"{attributes['contract']} has no positive strike"
    for name in ("bid", "ask", "volatility"):
        value = attributes[name]
        if value is not None and Decimal(str(value)) < 0:
            return f"{name} {value} is negative"
    delta = attributes["delta"]
    if delta is not None and not -1 <= Decimal(str(delta)) <= 1:
        return f"delta {delta} is outside -1 to 1"
    return None


@dataclass(frozen=True)
class Record:
    """One checked record: its ``id``, its JSON:API ``type`` and its attributes as provider text."""

    id: str
    type: str
    attributes: Mapping[str, str | None]

    @property
    def contract(self) -> str:
        return str(self.attributes["contract"])

    @property
    def expiry(self) -> date:
        return date.fromisoformat(str(self.attributes["exp_date"]))

    @property
    def right(self) -> str:
        return str(self.attributes["type"])

    @property
    def strike(self) -> Decimal:
        return Decimal(str(self.attributes["strike"]))

    @property
    def root(self) -> str:
        return parse_occ(self.contract).root

    @property
    def date(self) -> date | None:
        """The session an ``eod`` record is for; None for a ``contracts`` record."""
        match = _RECORD_ID.fullmatch(self.id)
        return None if match is None else date.fromisoformat(match["date"])

    def item(self) -> dict[str, object]:
        """The record as the provider sent it, numbers as their literal text."""
        return {"id": self.id, "type": self.type, "attributes": dict(self.attributes)}


def check_item(item: object, endpoint: Endpoint) -> Record:
    """One ``data`` item of ``endpoint`` as a ``Record``; ``ValueError`` with the reason otherwise."""
    if not isinstance(item, dict) or set(item) != {"id", "type", "attributes"}:
        raise ValueError("an item must hold exactly id, type and attributes")
    identifier, kind, attributes = item["id"], item["type"], item["attributes"]
    if kind != ITEM_TYPES[endpoint]:
        raise ValueError(f"an item of {endpoint} must have type {ITEM_TYPES[endpoint]}")
    if not isinstance(attributes, dict):
        raise ValueError("attributes must be an object")
    problem = check_attributes(attributes)
    if problem is not None:
        raise ValueError(f"item {_quoted(str(identifier))}: {problem}")
    contract = attributes["contract"]
    if endpoint == "contracts":
        if identifier != contract:
            raise ValueError(f"item {_quoted(str(identifier))} must have its contract {contract} as id")
    else:
        match = _RECORD_ID.fullmatch(identifier) if isinstance(identifier, str) else None
        if match is None or match["contract"] != contract:
            raise ValueError(f"item {_quoted(str(identifier))} must have the id {contract}-YYYY-MM-DD")
        parse_day(match["date"])
    return Record(str(identifier), str(kind), dict(attributes))


@dataclass(frozen=True)
class Query:
    """One query of one endpoint: its filters, in order, and its sort; every page asks for ``FIELDS``."""

    endpoint: Endpoint
    filters: tuple[tuple[str, str], ...]
    sort: Literal["exp_date", "strike"]

    def _parameters(self) -> list[tuple[str, str]]:
        return [
            *((f"filter[{name}]", value) for name, value in self.filters),
            (f"fields[{ITEM_TYPES[self.endpoint]}]", ",".join(FIELDS)),
            ("sort", self.sort),
            ("page[limit]", str(PAGE_LIMIT)),
        ]

    def url(self) -> str:
        """The URL requested, which a raw file names: the first page, of ``PAGE_LIMIT`` records."""
        return f"{BASE_URL}/{self.endpoint}?{urlencode(self._parameters())}"


@dataclass(frozen=True)
class Page:
    records: tuple[Record, ...]
    more: bool  # whether links.next names a further page: the query matched more records


def parse_page(body: bytes, query: Query) -> Page:
    """The page answering ``query``, checked; ``ValueError`` naming the problem otherwise."""
    value = load_json(body)
    if not isinstance(value, dict):
        raise ValueError("the body is not a JSON object")
    meta, data, links = value.get("meta"), value.get("data"), value.get("links")
    if not isinstance(meta, dict) or not isinstance(data, list) or not isinstance(links, dict):
        raise ValueError("the body must hold the objects meta and links and the list data")
    if meta.get("offset") != "0" or meta.get("limit") != str(PAGE_LIMIT):
        raise ValueError(f"meta must state offset 0 and limit {PAGE_LIMIT}")
    fields = meta.get("fields")
    expected = sorted(FIELDS) if data else []  # a page without records names no field
    if not isinstance(fields, list) or sorted(map(str, fields)) != expected or len(fields) != len(expected):
        names = ", ".join(FIELDS) if data else "none on a page without records"
        raise ValueError(f"meta.fields must be exactly {names}")
    if len(data) > PAGE_LIMIT:
        raise ValueError(f"the page holds more than {PAGE_LIMIT} records")
    following = links.get("next")
    if following is not None and not isinstance(following, str):
        raise ValueError("links.next must be a URL or null")
    records = tuple(check_item(item, query.endpoint) for item in data)
    return Page(records, following is not None)


def page(client: EodhdClient, query: Query) -> Page:
    """The one page answering ``query``; an invalid page raises ``EodhdError`` naming its URL."""
    url = query.url()
    body = client.get(url)
    try:
        return parse_page(body, query)
    except ValueError as error:
        raise EodhdError(
            f"GET {url}: the response is not EODHD's options page: {printable(str(error))}"
        ) from None
