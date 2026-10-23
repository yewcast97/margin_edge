"""A season's figures from EDGAR's XBRL company facts.

Pure. ``data.sec.gov/api/xbrl/companyfacts/CIK##########.json`` holds every XBRL fact EDGAR
extracted from a company's filings: ``{"cik", "entityName", "facts": {"us-gaap": {concept:
{"units": {unit: [entry, ...]}}}}}``, each entry ``{"start"?, "end", "val", "accn", "fy",
"fp", "form", "filed", "frame"?}``. ``read_companyfacts`` reads the strict subset the
measures need: ``cik`` (the requested CIK), ``entityName`` and the entries of the concepts of
``TAGS`` in their units, each with ``end`` and an optional ``start`` (``YYYY-MM-DD``), ``val``
(a number) and ``accn`` (an accession number); every other key is ignored, and repeated keys,
``NaN`` and ``Infinity`` are refused. Numbers are read as decimals, exactly.

Every figure of a season comes from that season's own 10-K or 10-Q (its ``accn``), as the
filing first reported it; ``frame``, which marks the figure EDGAR deems latest for a
calendar period, is never used. Per measure, the first concept of its ``TAGS`` that the
filing reports is read:

- a balance (``BALANCES``) is the entry without ``start`` whose ``end`` is the season's
  period end;
- a flow (``FLOWS``) is the entry of the quarter, ``end`` the period end and 80 to 100 days
  long; else, when the previous listed season ends 80 to 100 days before, in a 10-Q the year
  to date (101 to 290 days) less the previous season's own year to date from the same start,
  and in a 10-K the year (350 to 380 days) less the previous season's nine months from the
  same start. A figure that is not additive (``PER_QUARTER``: diluted
  earnings per share and the weighted diluted shares) is read for the quarter only;
- gross profit is ``GrossProfit``, else revenue less cost of revenue; debt is the
  noncurrent long-term debt plus ``DebtCurrent`` (else the current long-term debt, the
  short-term borrowings and the commercial paper), an absent part counting 0, none when no
  part is reported.

Two distinct values of one concept, filing and span make the figure ambiguous: it has no
value. A figure without a value says why (``Figure.reason``). The year-ago season of a
season is the listed season of the same form ending 350 to 380 days before it.
"""

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Final, Literal

from .filings import ACCESSION_PATTERN, Season, Seasons

Measure = Literal[
    "revenue",
    "cost_of_revenue",
    "gross_profit",
    "operating_income",
    "net_income",
    "operating_cash_flow",
    "receivables",
    "inventory",
    "payables",
    "debt",
    "cash",
    "diluted_shares",
    "goodwill",
    "equity",
    "assets",
    "diluted_eps",
]
USD: Final = "USD"
SHARES: Final = "shares"
PER_SHARE: Final = "USD/shares"
# Each measure's concepts, in the order they are tried, and its unit.
TAGS: Final[Mapping[str, tuple[tuple[str, ...], str]]] = {
    "revenue": (("Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet"), USD),
    "cost_of_revenue": (("CostOfRevenue", "CostOfGoodsAndServicesSold"), USD),
    "gross_profit": (("GrossProfit",), USD),
    "operating_income": (("OperatingIncomeLoss",), USD),
    "net_income": (("NetIncomeLoss", "ProfitLoss"), USD),
    "operating_cash_flow": (("NetCashProvidedByUsedInOperatingActivities",), USD),
    "receivables": (("AccountsReceivableNetCurrent", "ReceivablesNetCurrent"), USD),
    "inventory": (("InventoryNet",), USD),
    "payables": (("AccountsPayableCurrent", "AccountsPayableTradeCurrent"), USD),
    "debt_noncurrent": (("LongTermDebtNoncurrent",), USD),
    "debt_current": (("DebtCurrent",), USD),
    "long_term_debt_current": (("LongTermDebtCurrent",), USD),
    "short_term_borrowings": (("ShortTermBorrowings",), USD),
    "commercial_paper": (("CommercialPaper",), USD),
    "cash": (("CashAndCashEquivalentsAtCarryingValue",), USD),
    "diluted_shares": (("WeightedAverageNumberOfDilutedSharesOutstanding",), SHARES),
    "goodwill": (("Goodwill",), USD),
    "equity": (("StockholdersEquity",), USD),
    "assets": (("Assets",), USD),
    "diluted_eps": (("EarningsPerShareDiluted",), PER_SHARE),
}
BALANCES: Final = (
    "receivables",
    "inventory",
    "payables",
    "debt_noncurrent",
    "debt_current",
    "long_term_debt_current",
    "short_term_borrowings",
    "commercial_paper",
    "cash",
    "goodwill",
    "equity",
    "assets",
)
FLOWS: Final = (
    "revenue",
    "cost_of_revenue",
    "gross_profit",
    "operating_income",
    "net_income",
    "operating_cash_flow",
    "diluted_shares",
    "diluted_eps",
)
PER_QUARTER: Final = ("diluted_shares", "diluted_eps")
# The measures a season's facts table lists, in order.
MEASURES: Final[tuple[Measure, ...]] = (
    "revenue",
    "cost_of_revenue",
    "gross_profit",
    "operating_income",
    "net_income",
    "operating_cash_flow",
    "receivables",
    "inventory",
    "payables",
    "debt",
    "cash",
    "diluted_shares",
    "goodwill",
    "equity",
    "assets",
    "diluted_eps",
)
UNITS: Final[Mapping[str, str]] = {name: unit for name, (_, unit) in TAGS.items()} | {"debt": USD}
QUARTER_DAYS: Final = (80, 100)
YEAR_TO_DATE_DAYS: Final = (101, 290)  # a 10-Q's two or three quarters, never twelve months
YEAR_DAYS: Final = (350, 380)
YEAR_AGO_DAYS: Final = (350, 380)
_ACCESSION = re.compile(ACCESSION_PATTERN, re.ASCII)
_DAY = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", re.ASCII)


class _NotJson(Exception):
    """A JSON body that the strict reader refuses although ``json`` would accept it."""


def _unique_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise _NotJson("an object repeats a key")
        value[key] = item
    return value


def _reject_constant(name: str) -> object:
    raise _NotJson(f"{name} is not JSON")


def _load(body: bytes) -> object:
    try:
        return json.loads(
            body.decode("utf-8"),  # strictly: json would also take UTF-16 and UTF-32
            object_pairs_hook=_unique_keys,
            parse_int=Decimal,
            parse_float=Decimal,
            parse_constant=_reject_constant,
        )
    except json.JSONDecodeError as error:
        raise ValueError(f"invalid JSON: {error.msg} (line {error.lineno}, column {error.colno})") from None
    except UnicodeDecodeError:
        raise ValueError("the body is not UTF-8") from None
    except _NotJson as error:
        raise ValueError(f"invalid JSON: {error}") from None
    except RecursionError:
        raise ValueError("invalid JSON: nested too deeply") from None


@dataclass(frozen=True)
class Entry:
    """One fact: the span it covers (``start`` None for a balance), its value and the filing."""

    start: date | None
    end: date
    value: Decimal
    accession: str

    @property
    def days(self) -> int | None:
        return None if self.start is None else (self.end - self.start).days + 1


@dataclass(frozen=True)
class CompanyFacts:
    """The checked subset of a company facts body: the entries of each (concept, unit) read."""

    cik: str
    entity_name: str
    entries: Mapping[tuple[str, str], tuple[Entry, ...]]

    def of(self, tag: str, unit: str, accession: str) -> tuple[Entry, ...]:
        return tuple(entry for entry in self.entries.get((tag, unit), ()) if entry.accession == accession)

    @property
    def accessions(self) -> frozenset[str]:
        """Every filing some entry read comes from."""
        return frozenset(entry.accession for entries in self.entries.values() for entry in entries)


def _day(value: object, where: str) -> date:
    if not isinstance(value, str) or _DAY.fullmatch(value) is None:  # fromisoformat takes week dates too
        raise ValueError(f"{where} must be a YYYY-MM-DD date")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ValueError(f"{where} must be a YYYY-MM-DD date") from None


def _entry(item: object, where: str) -> Entry:
    if not isinstance(item, dict):
        raise ValueError(f"{where} must be an object")
    for key in ("end", "val", "accn"):
        if key not in item:
            raise ValueError(f"{where}.{key} is missing")
    start = None if "start" not in item else _day(item["start"], f"{where}.start")
    end = _day(item["end"], f"{where}.end")
    if start is not None and start > end:
        raise ValueError(f"{where}: start is after end")
    value = item["val"]
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError(f"{where}.val must be a number")
    accession = item["accn"]
    if not isinstance(accession, str) or _ACCESSION.fullmatch(accession) is None:
        raise ValueError(f"{where}.accn must be an accession number")
    return Entry(start, end, value, accession)


def read_companyfacts(body: bytes, cik: str | None) -> CompanyFacts:
    """The strict subset of the company facts ``body`` of ``cik`` (ten digits; None, when it is
    not known, takes the body's own); ``ValueError`` names the field, never a value."""
    try:
        value = _load(body)
        if not isinstance(value, dict):
            raise ValueError("expected a JSON object")
        listed = value.get("cik")
        if (
            not isinstance(listed, Decimal)
            or listed != listed.to_integral_value()
            or not 0 <= listed < 10**10
        ):
            raise ValueError("cik must be a whole number of at most ten digits")
        if cik is not None and listed != int(cik):
            raise ValueError("cik is not the requested CIK")
        cik = f"{int(listed):010d}" if cik is None else cik
        name = value.get("entityName")
        if not isinstance(name, str) or not name.strip() or not name.isprintable():
            raise ValueError("entityName must be a non-empty printable string")
        facts = value.get("facts", {})
        if not isinstance(facts, dict):
            raise ValueError("facts must be an object")
        gaap = facts.get("us-gaap", {})
        if not isinstance(gaap, dict):
            raise ValueError("facts.us-gaap must be an object")
        entries: dict[tuple[str, str], tuple[Entry, ...]] = {}
        for tags, unit in TAGS.values():
            for tag in tags:
                concept = gaap.get(tag)
                if concept is None:
                    continue
                where = f"facts.us-gaap.{tag}"
                if not isinstance(concept, dict) or not isinstance(concept.get("units"), dict):
                    raise ValueError(f"{where}.units must be an object")
                items = concept["units"].get(unit)
                if items is None:
                    continue
                if not isinstance(items, list):
                    raise ValueError(f"{where}.units.{unit} must be a list")
                entries[(tag, unit)] = tuple(
                    _entry(item, f"{where}.units.{unit}[{index}]") for index, item in enumerate(items)
                )
    except ValueError as error:
        raise ValueError(f"companyfacts{'' if cik is None else f' CIK{cik}'}: {error}") from None
    return CompanyFacts(cik, name, entries)


# --------------------------------------------------------------------------- figures


@dataclass(frozen=True)
class Figure:
    """One measure of one season: its value, or None and why, and how it was read (the concept,
    the filing, the span and the formula)."""

    measure: str
    season: date
    value: Decimal | None
    unit: str
    tag: str | None = None
    accession: str | None = None
    start: date | None = None
    end: date | None = None
    formula: str = ""
    reason: str | None = None
    ambiguous: bool = False


def _none(measure: str, season: Season, reason: str, ambiguous: bool = False) -> Figure:
    return Figure(measure, season.period, None, UNITS.get(measure, USD), reason=reason, ambiguous=ambiguous)


def _one(entries: Sequence[Entry]) -> Entry | None | str:
    """The one value among ``entries``: an entry, None when there are none, ``"ambiguous"`` when
    they hold two distinct values."""
    values = {entry.value for entry in entries}
    if not values:
        return None
    if len(values) > 1:
        return "ambiguous"
    return entries[0]


def _balance(facts: CompanyFacts, measure: str, season: Season) -> Figure:
    tags, unit = TAGS[measure]
    accession = season.filing.accession
    for tag in tags:
        found = _one(
            [
                entry
                for entry in facts.of(tag, unit, accession)
                if entry.start is None and entry.end == season.period
            ]
        )
        if found == "ambiguous":
            return _none(measure, season, f"{tag}: two values in the filing {accession}", True)
        if isinstance(found, Entry):
            return Figure(
                measure,
                season.period,
                found.value,
                unit,
                tag,
                accession,
                None,
                found.end,
                "the balance at the period end",
            )
    return _none(measure, season, f"the filing {accession} reports no {' or '.join(tags)} at {season.period}")


def _spanning(entries: Sequence[Entry], end: date, days: tuple[int, int]) -> list[Entry]:
    return [
        entry
        for entry in entries
        if entry.start is not None and entry.end == end and days[0] <= (entry.days or 0) <= days[1]
    ]


def _flow(facts: CompanyFacts, seasons: Seasons, measure: str, season: Season) -> Figure:
    tags, unit = TAGS[measure]
    accession = season.filing.accession
    previous = seasons.before(season, 1)
    for tag in tags:
        own = facts.of(tag, unit, accession)
        quarter = _one(_spanning(own, season.period, QUARTER_DAYS))
        if quarter == "ambiguous":
            return _none(
                measure, season, f"{tag}: two values for the quarter in the filing {accession}", True
            )
        if isinstance(quarter, Entry):
            return Figure(
                measure,
                season.period,
                quarter.value,
                unit,
                tag,
                accession,
                quarter.start,
                quarter.end,
                "reported for the quarter",
            )
        if measure in PER_QUARTER or not own or not previous:
            continue
        earlier = previous[0]
        if not QUARTER_DAYS[0] <= (season.period - earlier.period).days <= QUARTER_DAYS[1]:
            continue  # the previous listed season ends no quarter before: a difference is no quarter
        if season.filing.form == "10-K":
            spans = _spanning(own, season.period, YEAR_DAYS)
            what, before = "the year", "nine months"
        else:
            spans = _spanning(own, season.period, YEAR_TO_DATE_DAYS)
            what, before = "the year to date", "year to date"
        for start in sorted({entry.start for entry in spans if entry.start is not None}):
            prior = _one(
                [
                    entry
                    for entry in facts.of(tag, unit, earlier.filing.accession)
                    if entry.start == start and entry.end == earlier.period
                ]
            )
            if prior is None:
                continue  # the previous filing reports no span from this start
            total = _one([entry for entry in spans if entry.start == start])
            if total == "ambiguous" or prior == "ambiguous":
                return _none(measure, season, f"{tag}: two values for one span", True)
            if isinstance(total, Entry) and isinstance(prior, Entry):
                formula = (
                    f"{what} {start} to {season.period} less the {before} {start} to {earlier.period} "
                    f"of the filing {earlier.filing.accession}"
                )
                return Figure(
                    measure,
                    season.period,
                    total.value - prior.value,
                    unit,
                    tag,
                    accession,
                    earlier.period + timedelta(days=1),
                    season.period,
                    formula,
                )
    return _none(measure, season, f"the filing {accession} reports no {' or '.join(tags)} for the quarter")


def _gross_profit(facts: CompanyFacts, seasons: Seasons, season: Season) -> Figure:
    reported = _flow(facts, seasons, "gross_profit", season)
    if reported.value is not None or reported.ambiguous:  # a reported concept is the one read
        return _none("gross_profit", season, reported.reason or "", True) if reported.ambiguous else reported
    revenue = _flow(facts, seasons, "revenue", season)
    cost = _flow(facts, seasons, "cost_of_revenue", season)
    if revenue.value is None or cost.value is None:
        return _none("gross_profit", season, reported.reason or "no gross profit, revenue or cost of revenue")
    return Figure(
        "gross_profit",
        season.period,
        revenue.value - cost.value,
        USD,
        f"{revenue.tag} − {cost.tag}",
        season.filing.accession,
        revenue.start,
        revenue.end,
        "revenue less cost of revenue",
    )


def _debt(facts: CompanyFacts, season: Season) -> Figure:
    parts = {name: _balance(facts, name, season) for name in ("debt_noncurrent", "debt_current")}
    if parts["debt_current"].value is None and not parts["debt_current"].ambiguous:
        for name in ("long_term_debt_current", "short_term_borrowings", "commercial_paper"):
            parts[name] = _balance(facts, name, season)
        del parts["debt_current"]
    unclear = next((part for part in parts.values() if part.ambiguous), None)
    if unclear is not None:  # a part with two values leaves the sum unknown
        return _none("debt", season, unclear.reason or "", True)
    known = {name: figure for name, figure in parts.items() if figure.value is not None}
    if not known:
        return _none("debt", season, "the filing reports no debt balance")
    total = sum((figure.value for figure in known.values() if figure.value is not None), Decimal(0))
    formula = " + ".join(f"{figure.tag}" for figure in known.values()) + " (an absent part counts 0)"
    return Figure(
        "debt",
        season.period,
        total,
        USD,
        ", ".join(str(figure.tag) for figure in known.values()),
        season.filing.accession,
        None,
        season.period,
        formula,
    )


def figure(facts: CompanyFacts, seasons: Seasons, measure: str, season: Season) -> Figure:
    """The ``measure`` of ``season`` (module docstring)."""
    if measure == "debt":
        return _debt(facts, season)
    if measure == "gross_profit":
        return _gross_profit(facts, seasons, season)
    if measure in BALANCES:
        return _balance(facts, measure, season)
    return _flow(facts, seasons, measure, season)


def season_figures(facts: CompanyFacts, seasons: Seasons, season: Season) -> dict[str, Figure]:
    """Every measure of ``MEASURES`` for ``season``."""
    return {measure: figure(facts, seasons, measure, season) for measure in MEASURES}


def year_ago(seasons: Seasons, season: Season) -> Season | None:
    """The listed season of the same form ending 350 to 380 days before ``season``, or None."""
    low, high = YEAR_AGO_DAYS
    return next(
        (
            other
            for other in reversed(seasons.seasons)
            if other.filing.form == season.filing.form and low <= (season.period - other.period).days <= high
        ),
        None,
    )


def quarter_days(seasons: Seasons, season: Season) -> int | None:
    """The days of ``season``'s quarter: from the previous listed season's end, or None."""
    previous = seasons.before(season, 1)
    return None if not previous else (season.period - previous[0].period).days
