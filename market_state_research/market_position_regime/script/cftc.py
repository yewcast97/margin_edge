"""The CFTC's Traders in Financial Futures: the query, the raw file and every rule a read checks.

The CFTC publishes the Commitments of Traders weekly: each week's positions as of its Tuesday
(as of its Monday when the Tuesday is a holiday), released on its Friday at 15:30 New York
time. Its Traders in Financial Futures (TFF) report splits each financial futures market's
open interest among dealers, asset managers, leveraged funds and other reportables; the
futures-only dataset is served by the CFTC's public Socrata API (``DATASET``), without a key.
The domain reads one market, the S&P 500 Consolidated (``CONTRACT``: the S&P 500 futures of
the Chicago Mercantile Exchange in standard-contract equivalents), reported every week since
``FIRST_REPORT``. Its standard contract changed: until 2023-04-25 the CFTC counted contracts
of $250 times the index, from 2023-05-02 contracts of $50 times the index (the E-mini), and
it did not restate the earlier weeks. Each row names its unit (``UNITS``), so every position
is converted to E-mini equivalents (``Report``: the count times its multiplier, divided by
``EMINI``) before two weeks are compared.

``query_url`` asks for the market's rows dated from ``first`` to ``last`` (both included)
with the ``FIELDS`` alone, ascending by report date, in one page of at most ``PAGE_ROWS``
rows; an answer that fills the page is refused, never paged. ``fetch`` writes an answer to
``raw/market/cftc_tff_{FIRST}_{LAST}_{TOKEN}.json``: one JSON object with exactly the keys
``request`` (the URL), ``fetched_at`` (New York ISO time with its offset; ``TOKEN`` names it
to the second), ``first``, ``last`` and ``rows``, the answer's rows as the API wrote them,
numbers as text.

Every read checks every rule again (``check_answer``): the keys and forms; the request
rebuilt from ``first`` and ``last``; the name against them and the time; a time not after
the clock and later than the day of the newest row; at least one row; each row with exactly
the ``FIELDS``, of the market (code, name, units, futures only, its ``id``), dated a weekday
from ``first`` to ``last`` at midnight; one row per week, in date order; every position a
whole number of contracts; the unit one of ``UNITS``.
"""

import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Final
from urllib.parse import quote, urlencode

from market_state_research.common.text import printable
from market_state_research.common.times import TOKEN_PATTERN, et_isoformat, timestamp_token, to_eastern

from .periods import FRIDAY, week_of

HOST: Final = "publicreporting.cftc.gov"
DATASET: Final = "gpe5-46if"  # TFF - Futures Only
ENDPOINT: Final = f"https://{HOST}/resource/{DATASET}.json"
CONTRACT: Final = "13874+"
MARKET: Final = "S&P 500 Consolidated - CHICAGO MERCANTILE EXCHANGE"
# Each unit the market's rows have named, and its multiplier in dollars per index point. Rows to
# 2014-12-30 wrap the unit in quotes; the multiplier fell from 250 to 50 on 2023-05-02.
UNITS: Final = {
    "'(S&P 500 INDEX X $250.00)'": 250,
    "(S&P 500 INDEX X $250.00)": 250,
    "(S&P 500 INDEX X $50.00)": 50,
}
EMINI: Final = 50  # dollars per index point of the E-mini, the unit positions are compared in
FUTURES_ONLY: Final = "FutOnly"
FIRST_REPORT: Final = date(2010, 6, 15)  # the market's first TFF report
PAGE_ROWS: Final = 5000
DATE_FIELD: Final = "report_date_as_yyyy_mm_dd"
POSITIONS: Final = (
    "open_interest_all",
    "asset_mgr_positions_long",
    "asset_mgr_positions_short",
    "asset_mgr_positions_spread",
    "lev_money_positions_long",
    "lev_money_positions_short",
    "lev_money_positions_spread",
)
FIELDS: Final = (
    "id",
    DATE_FIELD,
    "market_and_exchange_names",
    "cftc_contract_market_code",
    "futonly_or_combined",
    "contract_units",
    *POSITIONS,
)
RAW_NAME: Final = re.compile(
    rf"cftc_tff_(?P<first>[0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}})_(?P<last>[0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}})"
    rf"_(?P<token>{TOKEN_PATTERN})(?:_[0-9]+)?\.json",
    re.ASCII,
)
MAX_SUFFIX: Final = 99

_KEYS: Final = ("request", "fetched_at", "first", "last", "rows")
_DAY = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", re.ASCII)
_REPORT_DATE = re.compile(r"(?P<day>[0-9]{4}-[0-9]{2}-[0-9]{2})T00:00:00\.000", re.ASCII)
_WHOLE_NUMBER = re.compile(r"0|[1-9][0-9]{0,14}", re.ASCII)


@dataclass(frozen=True)
class Report:
    """One week's positions in contracts, as the CFTC wrote them."""

    as_of: date  # the day of the positions: the week's Tuesday, or its Monday
    open_interest: int
    asset_mgr_long: int
    asset_mgr_short: int
    asset_mgr_spread: int
    lev_money_long: int
    lev_money_short: int
    lev_money_spread: int
    multiplier: int  # dollars per index point of the report's contracts
    row: dict[str, str]  # the row verbatim

    @property
    def scale(self) -> int:
        """E-mini contracts per contract of the report."""
        return self.multiplier // EMINI

    @property
    def week(self) -> date:
        """The Tuesday that names the report's week."""
        return week_of(self.as_of)

    @property
    def asset_mgr_net(self) -> int:
        """Asset managers' net position in E-mini equivalents: (long − short) × the scale."""
        return (self.asset_mgr_long - self.asset_mgr_short) * self.scale

    @property
    def lev_money_net_short(self) -> int:
        """Leveraged funds' net short position in E-mini equivalents: (short − long) × the scale."""
        return (self.lev_money_short - self.lev_money_long) * self.scale

    @property
    def open_interest_emini(self) -> int:
        """The open interest in E-mini equivalents."""
        return self.open_interest * self.scale


@dataclass(frozen=True)
class Answer:
    """One valid answer: the request, when it arrived, the dates asked for and the reports."""

    request: str
    fetched_at: datetime
    first: date
    last: date
    reports: tuple[Report, ...]


def query_url(first: date, last: date) -> str:
    """The key-free URL of the market's rows dated from ``first`` to ``last``, both included."""
    if first > last:
        raise ValueError(f"the first report date {first} is after the last, {last}")
    parameters = (
        ("$select", ",".join(FIELDS)),
        (
            "$where",
            f"cftc_contract_market_code = '{CONTRACT}' AND {DATE_FIELD} between "
            f"'{first.isoformat()}T00:00:00.000' and '{last.isoformat()}T00:00:00.000'",
        ),
        ("$order", f"{DATE_FIELD} ASC"),
        ("$limit", str(PAGE_ROWS)),
    )
    return f"{ENDPOINT}?{urlencode(parameters, quote_via=quote, safe='')}"


def raw_name(first: date, last: date, fetched_at: datetime, suffix: str = "") -> str:
    """The name of an answer from ``first`` to ``last`` fetched at ``fetched_at``; ``suffix`` is
    ``""`` or ``_N``."""
    return f"cftc_tff_{first.isoformat()}_{last.isoformat()}_{timestamp_token(fetched_at)}{suffix}.json"


def _day(value: object, name: str) -> date:
    if not isinstance(value, str) or not _DAY.fullmatch(value):
        raise ValueError(f"{name} must be a YYYY-MM-DD date")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ValueError(f"{name} must be a YYYY-MM-DD date that exists") from None


def _count(row: dict[str, str], field: str, number: int) -> int:
    text = row[field]
    if not _WHOLE_NUMBER.fullmatch(text):
        raise ValueError(
            f"row {number}: {field} must be a whole number of contracts, got {printable(text)!r}"
        )
    return int(text)


def check_row(item: object, number: int) -> Report:
    """``item``, the answer's row ``number``, as a valid ``Report``; one ``ValueError`` line otherwise."""
    if not isinstance(item, dict) or set(item) != set(FIELDS):
        raise ValueError(f"row {number} must hold exactly the fields {', '.join(FIELDS)}")
    if not all(isinstance(value, str) for value in item.values()):
        raise ValueError(f"row {number}: every value must be a JSON string")
    row: dict[str, str] = dict(item)
    match = _REPORT_DATE.fullmatch(row[DATE_FIELD])
    if match is None:
        raise ValueError(f"row {number}: {DATE_FIELD} must be YYYY-MM-DDT00:00:00.000")
    day = _day(match["day"], f"row {number}: {DATE_FIELD}")
    if day.weekday() > FRIDAY:
        raise ValueError(f"row {number}: the report date {day} is not a weekday")
    expected = {
        "id": f"{day:%y%m%d}{CONTRACT}F",
        "market_and_exchange_names": MARKET,
        "cftc_contract_market_code": CONTRACT,
        "futonly_or_combined": FUTURES_ONLY,
    }
    for field, value in expected.items():
        if row[field] != value:
            raise ValueError(f"row {number}: {field} must be {value!r}, got {printable(row[field])!r}")
    multiplier = UNITS.get(row["contract_units"])
    if multiplier is None:
        known = " or ".join(repr(unit) for unit in UNITS)
        raise ValueError(
            f"row {number}: contract_units must be {known}, got {printable(row['contract_units'])!r}"
        )
    counts = {field: _count(row, field, number) for field in POSITIONS}
    return Report(
        as_of=day,
        open_interest=counts["open_interest_all"],
        asset_mgr_long=counts["asset_mgr_positions_long"],
        asset_mgr_short=counts["asset_mgr_positions_short"],
        asset_mgr_spread=counts["asset_mgr_positions_spread"],
        lev_money_long=counts["lev_money_positions_long"],
        lev_money_short=counts["lev_money_positions_short"],
        lev_money_spread=counts["lev_money_positions_spread"],
        multiplier=multiplier,
        row=row,
    )


def parse_rows(data: bytes) -> list[object]:
    """The rows of the API's answer ``data``, a JSON array; ``check_answer`` checks each row."""
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError):
        raise ValueError("the answer is not the CFTC's JSON rows") from None
    if not isinstance(value, list):
        raise ValueError("the answer is not the CFTC's JSON rows (an array)")
    if len(value) >= PAGE_ROWS:
        raise ValueError(f"the answer filled a page of {PAGE_ROWS} rows; ask for fewer dates")
    return value


def check_answer(value: object, name: str | None, now: datetime) -> Answer:
    """``value`` as a valid ``Answer`` named ``name`` (None: not named yet); every problem raises
    one ``ValueError`` line."""
    if not isinstance(value, dict):
        raise ValueError("a CFTC answer file must hold one JSON object")
    if tuple(value) != _KEYS:
        raise ValueError(f"the keys must be exactly {', '.join(_KEYS)}, in that order")
    first, last = _day(value["first"], "first"), _day(value["last"], "last")
    if first > last:
        raise ValueError(f"first {first} is after last {last}")
    if value["request"] != query_url(first, last):
        raise ValueError("request must be the query of first to last")
    fetched_text = value["fetched_at"]
    try:
        fetched_at = to_eastern(datetime.fromisoformat(fetched_text), "fetched_at")
    except (TypeError, ValueError):
        raise ValueError("fetched_at must be an ISO time with an offset") from None
    if et_isoformat(fetched_at) != fetched_text:
        raise ValueError("fetched_at must be written in New York time with its offset")
    if name is not None:
        match = RAW_NAME.fullmatch(name)
        if (
            match is None
            or match["first"] != first.isoformat()
            or match["last"] != last.isoformat()
            or match["token"] != timestamp_token(fetched_at)
        ):
            raise ValueError(f"the name must be {raw_name(first, last, fetched_at)} (or end _N.json)")
    if fetched_at > to_eastern(now, "now"):
        raise ValueError(f"fetched_at {et_isoformat(fetched_at)} is later than the current time")
    items = value["rows"]
    if not isinstance(items, list) or not items:
        raise ValueError("rows must be a list of at least one row")
    if len(items) >= PAGE_ROWS:
        raise ValueError(f"rows fill a page of {PAGE_ROWS}; an answer is never paged")
    reports = tuple(check_row(item, number) for number, item in enumerate(items, start=1))
    previous: date | None = None
    for number, report in enumerate(reports, start=1):
        if not first <= report.as_of <= last:
            raise ValueError(f"row {number} is dated {report.as_of}, outside {first} to {last}")
        if previous is not None and report.week <= previous:
            raise ValueError("rows must be one per week, in date order")
        previous = report.week
    if fetched_at.date() <= reports[-1].as_of:
        raise ValueError(
            f"fetched at {et_isoformat(fetched_at)}, not after the newest report date {reports[-1].as_of}"
        )
    return Answer(value["request"], fetched_at, first, last, reports)


def dump(answer: Answer) -> bytes:
    """The bytes ``fetch`` writes: compact ASCII JSON, the rows as the API wrote them."""
    value = {
        "request": answer.request,
        "fetched_at": et_isoformat(answer.fetched_at),
        "first": answer.first.isoformat(),
        "last": answer.last.isoformat(),
        "rows": [report.row for report in answer.reports],
    }
    return json.dumps(value, ensure_ascii=True, allow_nan=False, separators=(",", ":")).encode("ascii")


def read_answer(data: bytes, name: str, now: datetime) -> Answer:
    """Validate one raw answer file's bytes; every problem raises a one-line ``ValueError``."""
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError):
        raise ValueError("not a JSON document") from None
    return check_answer(value, name, now)
