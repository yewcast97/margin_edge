"""script/measures.py: the Python items of a season, the seasons each baseline names and measures.md.

Every season here is built from the dataclasses ``documents.season_documents`` returns, not
from a raw tree: the listed seasons (``filings.Season``), the company facts each season's own
filing reports (``facts.CompanyFacts``: a quarter's flows over the 91 days to its period end,
the balances at its end), each season's files (``documents.SeasonFiles``) with their Form 4s
and calls, and the derived texts by ``DOC_ID``. ``measures`` reads no file, so the paths only
name documents. Each item is checked at, just below and just above its threshold and in the
statuses it may take, with the values it states written out by hand; ``GOLDEN`` is the whole
``measures.md`` of a small season (its rule lines are the catalogue's, ``items.BY_ID``); and
every text ``measures`` writes passes the wording rule (``readings.WORDING``).
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import replace
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from market_state_research.fundamentals.script.documents import (
    CallState,
    Document,
    FilingFiles,
    RawState,
    SeasonFiles,
)
from market_state_research.fundamentals.script.earningscalls import CallEvent, Transcript, TranscriptTurn
from market_state_research.fundamentals.script.facts import CompanyFacts, Entry
from market_state_research.fundamentals.script.filings import Dated, Filing, Season, Seasons
from market_state_research.fundamentals.script.form4 import Form4, Owner, Transaction
from market_state_research.fundamentals.script.items import BY_ID, PYTHON_ITEMS
from market_state_research.fundamentals.script.measures import (
    Measures,
    Reading,
    baseline_seasons,
    season_measures,
)
from market_state_research.fundamentals.script.readings import WORDING

from .support import edt, est

TICKER = "INTC"
CIK = "0000050863"
ENTITY = "INTEL CORP"
ROOT = Path("data/raw/INTC")  # never read: measures reads no file
FACTS_FILE = ROOT / "companyfacts_20260801T090000EDT.json"
CAPTURED = date(2026, 8, 1)  # the calls list every call state here rests on
CALL_AT = edt(2026, 7, 23, 17, 0)  # when every call here began, unless a test says otherwise
TEXT = "The text of a document." * 40  # 920 characters: a document's derived text unless a test gives one

# A figure a test gives, by short name: the concept the filing reports it under and its unit;
# a flow over the quarter, a balance at the period end.
QUARTER = {
    "revenue": ("RevenueFromContractWithCustomerExcludingAssessedTax", "USD"),
    "cost": ("CostOfGoodsAndServicesSold", "USD"),
    "gross": ("GrossProfit", "USD"),
    "operating": ("OperatingIncomeLoss", "USD"),
    "income": ("NetIncomeLoss", "USD"),
    "cash_flow": ("NetCashProvidedByUsedInOperatingActivities", "USD"),
    "shares": ("WeightedAverageNumberOfDilutedSharesOutstanding", "shares"),
    "eps": ("EarningsPerShareDiluted", "USD/shares"),
}
PERIOD_END = {
    "receivables": "AccountsReceivableNetCurrent",
    "inventory": "InventoryNet",
    "payables": "AccountsPayableCurrent",
    "debt": "LongTermDebtNoncurrent",
    "debt_current": "DebtCurrent",
    "cash": "CashAndCashEquivalentsAtCarryingValue",
    "goodwill": "Goodwill",
    "equity": "StockholdersEquity",
    "assets": "Assets",
}
FOLDER_FORMS = {"8-K": "8-K", "4": "4", "DEF 14A": "DEF14A", "SCHEDULE 13G/A": "SCHEDULE13GA"}


# --------------------------------------------------------------------------- builders


def season(
    form: str, period: date, lag: int, accession: str, *filings: Dated, accepted: datetime | None = None
) -> Season:
    """A season whose 10-K or 10-Q was filed ``lag`` days after its period end, holding ``filings``
    in Rule B's order."""
    primary = f"intc-{period:%Y%m%d}.htm"
    return Season(Filing(form, accession, period + timedelta(days=lag), period, primary, accepted), filings)


def dated(
    form: str,
    accession: str,
    day: date,
    items: str = "",
    primary: str = "primary.htm",
    *,
    filed: date | None = None,
    accepted: datetime | None = None,
) -> Dated:
    """A filing Rule B dates ``day``, filed that day unless ``filed`` says otherwise."""
    return Dated(form, accession, filed or day, day, items, primary, accepted)


def release(accession: str, day: date, accepted: datetime | None = None) -> Dated:
    """An earnings release: an 8-K with Item 2.02, furnished on its event date."""
    return dated("8-K", accession, day, "2.02,9.01", f"intc-{day:%Y%m%d}.htm", accepted=accepted)


# Six listed seasons, oldest first: S is the season most tests read, A its same quarter last
# year, P its previous quarter and PA that quarter's year-ago. Each 10-Q was filed 27 or 30 days
# after its period end, the 10-K 34.
PA = season("10-Q", date(2025, 3, 29), 30, "0000050863-25-000010")
A = season("10-Q", date(2025, 6, 28), 27, "0000050863-25-000020")
B = season("10-Q", date(2025, 9, 27), 30, "0000050863-25-000030")
K = season("10-K", date(2025, 12, 27), 34, "0000050863-26-000012")
P = season("10-Q", date(2026, 3, 28), 27, "0000050863-26-000041")
S = season("10-Q", date(2026, 6, 27), 30, "0000050863-26-000064")
YEARS = (PA, A, B, K, P, S)


def figures(row: Season, **values: int | str) -> list[tuple[tuple[str, str], Entry]]:
    """The figures ``row``'s own filing reports, by short name (``QUARTER``, ``PERIOD_END``)."""
    found = []
    for name, value in values.items():
        start: date | None = None
        if name in QUARTER:
            tag, unit = QUARTER[name]
            start = row.period - timedelta(days=90)
        else:
            tag, unit = PERIOD_END[name], "USD"
        found.append(((tag, unit), Entry(start, row.period, Decimal(value), row.filing.accession)))
    return found


def company_facts(*reported: Iterable[tuple[tuple[str, str], Entry]]) -> CompanyFacts:
    entries: dict[tuple[str, str], list[Entry]] = {}
    for pairs in reported:
        for key, entry in pairs:
            entries.setdefault(key, []).append(entry)
    return CompanyFacts(CIK, ENTITY, {key: tuple(found) for key, found in entries.items()})


def filing_document(row: Season) -> Document:
    """The season's 10-K or 10-Q, named as ``documents`` names it."""
    own = row.filing
    folder = f"{own.form}_{own.period}_{own.accession}"
    path = ROOT / str(own.period) / folder / own.primary_document
    label = f"{own.form} for the period ended {own.period}"
    return Document(
        f"{folder}_{path.stem}", "filing", own.period, path, label, own.form, own.accession, own.filed
    )


def filing_files(row: Season, item: Dated, *names: str, form4: Form4 | None = None) -> FilingFiles:
    """A filing of ``row`` in ``raw/`` with its documents of ``names``: an 8-K's primary document
    first, then its exhibits; a schedule's or proxy statement's one document; a Form 4 none."""
    folder_name = f"{FOLDER_FORMS[item.form]}_{item.dated}_{item.accession}"
    folder = ROOT / str(row.period) / folder_name
    kinds = {"8-K": "exhibit", "DEF 14A": "proxy", "SCHEDULE 13G/A": "holder"}
    documents = tuple(
        Document(
            f"{folder_name}_{Path(name).stem}",
            "8-K" if item.form == "8-K" and position == 0 else kinds[item.form],
            row.period,
            folder / name,
            name,
            item.form,
            item.accession,
            item.filed,
        )
        for position, name in enumerate(names)
    )
    return FilingFiles(item, folder, (), True, (), documents, form4)


def turn(speaker: str, role: str, words: int) -> TranscriptTurn:
    """A turn of ``words`` words."""
    return TranscriptTurn(speaker, role, " ".join(["word"] * words))


def transcribed(
    row: Season,
    *turns: TranscriptTurn,
    duration: int | None = 3600,
    call_id: int = 248001,
    at: datetime = CALL_AT,
) -> CallState:
    """The season's call with its transcript in ``raw/``: one call of ``turns``."""
    event = CallEvent(call_id, at)
    transcript = Transcript(f"Call {call_id}", at, turns, duration)
    path = ROOT / str(row.period) / f"transcript_{call_id}.json"
    document = Document(
        f"call_{row.period}_{call_id}", "call", row.period, path, "call", title=transcript.title, call=event
    )
    return CallState("transcript", (event,), (document,), (transcript,), row.filing.filed, CAPTURED, None)


def no_call(row: Season, status: str = "unavailable", *events: CallEvent) -> CallState:
    """The season's call without a transcript in ``raw/``, with the calls the list places in it."""
    return CallState(status, events, (), (), row.filing.filed, CAPTURED, None)


def season_files(
    row: Season, *filings: FilingFiles, call: CallState | None = None, filed: bool = True
) -> SeasonFiles:
    """The season's files: its 10-K or 10-Q (unless ``filed`` is False), ``filings`` and its call,
    unavailable unless given."""
    document = filing_document(row)
    return SeasonFiles(
        row,
        ROOT / str(row.period),
        document.path,
        document if filed else None,
        filings,
        call or no_call(row),
        frozenset(),
    )


def raw_state(rows: Sequence[Season], *files: SeasonFiles, facts: CompanyFacts | None = None) -> RawState:
    """``raw/`` whose newest submissions list ``rows``, oldest first: each season with ``files``
    where given, else its 10-K or 10-Q alone and its call unavailable; ``facts`` read from
    ``FACTS_FILE``."""
    given = {held.day: held for held in files}
    return RawState(
        ticker=TICKER,
        submissions=ROOT / "submissions_20260801T090000EDT.json",
        cik=CIK,
        entity_name=ENTITY,
        reason=None,
        listing=Seasons(tuple(rows), (), (), rows[0].filing.filed),
        seasons=tuple(given.get(row.period) or season_files(row) for row in rows),
        companyfacts=None if facts is None else FACTS_FILE,
        facts=facts,
        facts_problem=None if facts is not None else "no companyfacts file is in raw/; run fetch",
        capture=None,
        capture_problem=None,
        pending_calls=(),
        unlisted=(),
        former_layout=(),
        transcript_files={},
        invalid_files=(),
    )


def measured(raw: RawState, row: Season, texts: Mapping[str, str] | None = None) -> Measures:
    """The measures of ``row``'s season; each document's derived text is ``texts``' (``TEXT``
    without them)."""
    files = raw.season(row.period)
    assert files is not None
    return season_measures(raw, files, lambda document: TEXT if texts is None else texts[document.doc_id])


def computed(
    raw: RawState, row: Season, identifier: str, texts: Mapping[str, str] | None = None
) -> tuple[str, str, str]:
    """The Python item ``identifier`` of ``row``'s season: its baseline, values and level."""
    found = next(item for item in measured(raw, row, texts).readings if item.item.id == identifier)
    return found.baseline, found.values, found.level


# --------------------------------------------------------------------------- the season


def test_a_season_reads_every_python_item_in_catalogue_order():
    measures = measured(raw_state(YEARS), S)

    assert [found.item.id for found in measures.readings] == [
        "2.1",
        "2.2",
        "2.3",
        "2.4",
        "2.5",
        "2.6",
        "2.10",
        "2.11",
        "5.7",
        "8.5",
        "8.6",
        "9.1",
        "9.3",
        "9.4",
        "9.5",
        "9.6",
    ]
    assert [found.item for found in measures.readings] == list(PYTHON_ITEMS)
    assert all(isinstance(found, Reading) for found in measures.readings)
    assert (measures.level("2.1"), measures.level("9.1")) == ("not computable", "none")


def test_measures_need_a_listed_season():
    raw = raw_state(YEARS)
    files = raw.season(S.period)

    with pytest.raises(ValueError, match=r"^INTC: no season is listed$"):
        season_measures(replace(raw, listing=None), files, lambda document: TEXT)


def test_the_figures_are_those_of_the_season_and_of_the_seasons_it_compares_with():
    facts = company_facts(figures(S, revenue=1_000), figures(PA, revenue=900))

    measures = measured(raw_state(YEARS, facts=facts), S)

    # The season, its same quarter last year, its previous quarter and that quarter's year-ago.
    assert [found.season for found in measures.figures[::16]] == [S.period, A.period, P.period, PA.period]
    assert [found.measure for found in measures.figures[:16]] == [
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
    assert len(measures.figures) == 64
    assert [found.value for found in measures.figures if found.measure == "revenue"] == [
        Decimal(1_000),
        None,
        None,
        Decimal(900),
    ]


def test_without_company_facts_no_figure_is_listed():
    assert measured(raw_state(YEARS), S).figures == ()


@pytest.mark.parametrize("identifier", ["2.1", "2.2", "2.3", "2.4", "2.5", "2.6", "2.10", "2.11"])
def test_without_company_facts_the_financial_items_are_not_computable(identifier):
    _, values, level = computed(raw_state(YEARS), S, identifier)

    assert (values, level) == ("no company facts are in raw/", "not computable")


@pytest.mark.parametrize(
    ("identifier", "baseline", "values"),
    [
        pytest.param(
            "2.1",
            "same quarter last year none; previous quarter none and its year-ago none",
            "a season the comparison needs is not listed",
            id="2.1",
        ),
        pytest.param(
            "2.2",
            "same quarter last year none; previous quarter none",
            "no baseline season is listed",
            id="2.2",
        ),
        pytest.param(
            "2.3",
            "same quarter last year none; previous quarter none and its year-ago none",
            "the same quarter last year is not listed",
            id="2.3",
        ),
        pytest.param(
            "2.4", "same quarter last year none", "the same quarter last year is not listed", id="2.4"
        ),
        pytest.param(
            "2.5", "same quarter last year none", "the same quarter last year is not listed", id="2.5"
        ),
        pytest.param("2.6", "previous quarter none", "the previous quarter is not listed", id="2.6"),
        pytest.param("2.10", "previous quarter none", "the previous quarter is not listed", id="2.10"),
        pytest.param("2.11", "previous quarter none", "the previous quarter is not listed", id="2.11"),
        pytest.param(
            "8.5", "previous quarter none", "the previous season's call has no transcript in raw/", id="8.5"
        ),
        pytest.param(
            "8.6", "previous quarter none", "the previous season's call has no transcript in raw/", id="8.6"
        ),
        pytest.param(
            "9.1",
            "previous four 10-Qs: none; previous four seasons: none",
            "filed 30 days after the period end; no earlier 10-Q is listed; late-filing notices: none",
            id="9.1",
        ),
        pytest.param(
            "9.3", "previous quarter none", "the previous season's call has no transcript in raw/", id="9.3"
        ),
        pytest.param(
            "9.4",
            "previous 10-Q none; previous season none",
            "10-Q: 920 characters, no baseline; release exhibits: not in raw/; "
            "call: 920 characters, no baseline",
            id="9.4",
        ),
        pytest.param("9.5", "previous four seasons: none", "0 8-Ks", id="9.5"),
    ],
)
def test_the_oldest_listed_season_has_no_baseline(identifier, baseline, values):
    call = transcribed(PA, turn("Pat Lee", "executive", 300), turn("Analyst 1", "analyst", 20))
    raw = raw_state(YEARS, season_files(PA, call=call), facts=company_facts(figures(PA, revenue=1_000)))

    assert computed(raw, PA, identifier) == (baseline, values, "no baseline")


# --------------------------------------------------------------------------- 2.1 growth


GROWTH_BASELINE = (
    "same quarter last year 2025-06-28 (10-Q); previous quarter 2026-03-28 (10-Q) and its year-ago "
    "2025-03-29 (10-Q)"
)


@pytest.mark.parametrize(
    ("revenue", "income", "values", "level"),
    [
        pytest.param(
            1_100_100,
            120_000,
            "revenue: growth 10.01% against 20.00% a quarter earlier (-9.99 pp); "
            "net income: growth 20.00% against 20.00% a quarter earlier (+0.00 pp)",
            "none",
            id="below",
        ),
        pytest.param(
            1_100_000,
            120_000,
            "revenue: growth 10.00% against 20.00% a quarter earlier (-10.00 pp); "
            "net income: growth 20.00% against 20.00% a quarter earlier (+0.00 pp)",
            "none",
            id="at",
        ),
        pytest.param(
            1_099_900,
            120_000,
            "revenue: growth 9.99% against 20.00% a quarter earlier (-10.01 pp); "
            "net income: growth 20.00% against 20.00% a quarter earlier (+0.00 pp)",
            "yellow",
            id="above",
        ),
        pytest.param(
            1_200_000,
            108_000,
            "revenue: growth 20.00% against 20.00% a quarter earlier (+0.00 pp); "
            "net income: growth 8.00% against 20.00% a quarter earlier (-12.00 pp)",
            "yellow",
            id="net-income",
        ),
    ],
)
def test_growth_down_more_than_ten_points_on_the_previous_quarter_turns_yellow(
    revenue, income, values, level
):
    facts = company_facts(
        figures(PA, revenue=1_000_000, income=100_000),
        figures(A, revenue=1_000_000, income=100_000),
        figures(P, revenue=1_200_000, income=120_000),
        figures(S, revenue=revenue, income=income),
    )

    assert computed(raw_state(YEARS, facts=facts), S, "2.1") == (GROWTH_BASELINE, values, level)


def test_growth_is_not_computable_without_a_year_ago_figure_above_0():
    facts = company_facts(
        figures(PA, revenue=1_000_000),
        figures(A, revenue=0),
        figures(P, revenue=1_200_000),
        figures(S, revenue=1_100_000),
    )

    assert computed(raw_state(YEARS, facts=facts), S, "2.1") == (
        GROWTH_BASELINE,
        "revenue: not computable (a figure is missing, or a year-ago figure is 0 or below); "
        "net income: not computable (a figure is missing, or a year-ago figure is 0 or below)",
        "not computable",
    )


def test_growth_needs_the_year_ago_of_the_season_and_of_its_previous_quarter():
    rows = (PA, B, K, P, S)  # the same quarter last year is not listed

    assert computed(raw_state(rows, facts=company_facts()), S, "2.1") == (
        "same quarter last year none; previous quarter 2026-03-28 (10-Q) and its year-ago 2025-03-29 (10-Q)",
        "a season the comparison needs is not listed",
        "no baseline",
    )


# --------------------------------------------------------------------------- 2.2 margins


@pytest.mark.parametrize(
    ("gross", "margin", "move", "level"),
    [
        pytest.param(480_100, "48.01", "+199", "none", id="below"),
        pytest.param(480_000, "48.00", "+200", "none", id="at"),
        pytest.param(479_900, "47.99", "+201", "yellow", id="above"),
        pytest.param(520_100, "52.01", "-201", "yellow", id="above-falling"),
    ],
)
def test_a_margin_more_than_200_basis_points_from_a_baseline_turns_yellow(gross, margin, move, level):
    facts = company_facts(
        figures(A, revenue=1_000_000, gross=gross, operating=100_000),
        figures(P, revenue=1_000_000, gross=500_000, operating=100_000),
        figures(S, revenue=1_000_000, gross=500_000, operating=100_000),
    )

    assert computed(raw_state(YEARS, facts=facts), S, "2.2") == (
        "same quarter last year 2025-06-28 (10-Q); previous quarter 2026-03-28 (10-Q)",
        f"gross margin 50.00% against {margin}% a year ago ({move} bps); "
        "gross margin 50.00% against 50.00% a quarter ago (+0 bps); "
        "operating margin 10.00% against 10.00% a year ago (+0 bps); "
        "operating margin 10.00% against 10.00% a quarter ago (+0 bps)",
        level,
    )


def test_gross_margin_is_revenue_less_cost_where_no_gross_profit_is_reported():
    facts = company_facts(
        figures(P, revenue=1_000_000, cost=600_000),
        figures(S, revenue=1_000_000, cost=640_000),
    )

    _, values, level = computed(raw_state(YEARS, facts=facts), S, "2.2")

    # The same quarter last year reports nothing: its comparisons are left out.
    assert (
        values
        == "gross margin 36.00% against 40.00% a quarter ago (-400 bps); operating margin: not computable"
    )
    assert level == "yellow"


def test_margins_are_not_computable_without_the_seasons_revenue():
    facts = company_facts(figures(P, revenue=1_000_000, gross=500_000), figures(S, gross=500_000))

    _, values, level = computed(raw_state(YEARS, facts=facts), S, "2.2")

    assert (values, level) == (
        "gross margin: not computable; operating margin: not computable",
        "not computable",
    )


# --------------------------------------------------------------------------- 2.3 cash to net income


CASH_BASELINE = GROWTH_BASELINE


@pytest.mark.parametrize(
    ("now", "year_ago", "previous", "previous_year_ago", "level"),
    [
        pytest.param("0.70", "1.01", "1.20", "1.10", "none", id="at-0.7"),
        pytest.param("0.69", "1.01", "1.20", "1.10", "red", id="below-0.7-after-above-1"),
        pytest.param("0.69", "1.00", "1.20", "1.10", "none", id="below-0.7-after-1"),
        pytest.param("0.99", "1.00", "0.99", "1.00", "red", id="below-1-twice"),
        pytest.param("1.00", "1.00", "0.99", "1.00", "none", id="at-1"),
        pytest.param("0.99", "1.00", "0.99", "0.99", "none", id="a-year-ago-below-1"),
    ],
)
def test_operating_cash_flow_falling_behind_net_income_turns_red(
    now, year_ago, previous, previous_year_ago, level
):
    ratios = {S: now, A: year_ago, P: previous, PA: previous_year_ago}
    facts = company_facts(
        *(figures(row, cash_flow=int(Decimal(ratio) * 100), income=100) for row, ratio in ratios.items())
    )

    assert computed(raw_state(YEARS, facts=facts), S, "2.3") == (
        CASH_BASELINE,
        "operating cash flow ÷ net income (none where net income is 0 or below): "
        f"now {now}; year ago {year_ago}; previous {previous}; previous year ago {previous_year_ago}",
        level,
    )


def test_a_ratio_is_not_computable_where_net_income_is_0_or_below():
    facts = company_facts(
        figures(S, cash_flow=50, income=-10),
        figures(A, cash_flow=101, income=100),
        figures(P, cash_flow=120, income=100),
        figures(PA, cash_flow=110, income=0),
    )

    assert computed(raw_state(YEARS, facts=facts), S, "2.3") == (
        CASH_BASELINE,
        "operating cash flow ÷ net income (none where net income is 0 or below): "
        "now not computable; year ago 1.01; previous 1.20; previous year ago not computable",
        "not computable",
    )


def test_cash_flow_to_net_income_needs_the_same_quarter_last_year():
    _, values, level = computed(raw_state((PA, B, K, P, S), facts=company_facts()), S, "2.3")

    assert (values, level) == ("the same quarter last year is not listed", "no baseline")


# --------------------------------------------------------------------------- 2.4 days


@pytest.mark.parametrize(
    ("receivables", "days", "rise", "level"),
    [
        pytest.param(499, "49.9", "+14.9", "none", id="below"),
        pytest.param(500, "50.0", "+15.0", "none", id="at"),
        pytest.param(501, "50.1", "+15.1", "yellow", id="above"),
    ],
)
def test_days_of_sales_outstanding_up_more_than_15_days_turn_yellow(receivables, days, rise, level):
    # 91 days in both quarters: days are a tenth of a balance against a flow of 910.
    facts = company_facts(
        figures(A, revenue=910, cost=910, receivables=350, inventory=400, payables=300),
        figures(S, revenue=910, cost=910, receivables=receivables, inventory=400, payables=300),
    )

    assert computed(raw_state(YEARS, facts=facts), S, "2.4") == (
        "same quarter last year 2025-06-28 (10-Q)",
        f"days of sales outstanding {days} against 35.0 ({rise} days); "
        "days of inventory 40.0 against 40.0 (+0.0 days); days of payables 30.0 against 30.0 (+0.0 days)",
        level,
    )


def test_days_of_inventory_and_payables_count_against_cost_of_revenue():
    facts = company_facts(
        figures(A, revenue=910, cost=910, receivables=350, inventory=400, payables=300),
        figures(S, revenue=910, cost=455, receivables=350, inventory=400, payables=300),
    )

    _, values, level = computed(raw_state(YEARS, facts=facts), S, "2.4")

    assert values == (
        "days of sales outstanding 35.0 against 35.0 (+0.0 days); days of inventory 80.0 against 40.0 "
        "(+40.0 days); days of payables 60.0 against 30.0 (+30.0 days)"
    )
    assert level == "yellow"


def test_days_need_the_cost_of_revenue_and_the_length_of_each_quarter():
    facts = company_facts(
        figures(A, revenue=910, receivables=350, inventory=400, payables=300),
        figures(S, revenue=910, cost=910, receivables=350, inventory=400, payables=300),
    )

    _, values, level = computed(raw_state(YEARS, facts=facts), S, "2.4")
    assert values == (
        "days of sales outstanding 35.0 against 35.0 (+0.0 days); days of inventory: not computable; "
        "days of payables: not computable"
    )
    assert level == "none"

    # Without the season listed before the same quarter last year, that quarter has no length.
    _, values, level = computed(raw_state((A, B, K, P, S), facts=facts), S, "2.4")
    assert values == (
        "days of sales outstanding: not computable; days of inventory: not computable; "
        "days of payables: not computable"
    )
    assert level == "not computable"


# --------------------------------------------------------------------------- 2.5 receivables


@pytest.mark.parametrize(
    ("receivables", "growth", "gap", "level"),
    [
        pytest.param(1_299_900, "29.99", "19.99", "none", id="below"),
        pytest.param(1_300_000, "30.00", "20.00", "none", id="at"),
        pytest.param(1_300_100, "30.01", "20.01", "red", id="above"),
    ],
)
def test_receivables_outgrowing_revenue_by_more_than_20_points_turn_red(receivables, growth, gap, level):
    facts = company_facts(
        figures(A, revenue=1_000_000, receivables=1_000_000),
        figures(S, revenue=1_100_000, receivables=receivables),
    )

    assert computed(raw_state(YEARS, facts=facts), S, "2.5") == (
        "same quarter last year 2025-06-28 (10-Q)",
        f"receivables growth {growth}% less revenue growth 10.00%: {gap} pp",
        level,
    )


def test_receivables_growth_is_not_computable_without_both_figures():
    facts = company_facts(figures(A, revenue=1_000_000, receivables=1_000_000), figures(S, revenue=1_100_000))

    _, values, level = computed(raw_state(YEARS, facts=facts), S, "2.5")

    assert (values, level) == ("receivables or revenue growth not computable", "not computable")


# --------------------------------------------------------------------------- 2.6 net debt


@pytest.mark.parametrize(
    ("debt", "now", "move", "level"),
    [
        pytest.param(1_749_900, "1,249,900", "+24.99", "none", id="below"),
        pytest.param(1_750_000, "1,250,000", "+25.00", "none", id="at"),
        pytest.param(1_750_100, "1,250,100", "+25.01", "yellow", id="above"),
        pytest.param(1_250_000, "750,000", "-25.00", "none", id="at-falling"),
        pytest.param(1_249_900, "749,900", "-25.01", "yellow", id="above-falling"),
    ],
)
def test_net_debt_more_than_25_percent_from_the_previous_quarter_turns_yellow(debt, now, move, level):
    facts = company_facts(
        figures(P, debt=1_500_000, cash=500_000, equity=10_000_000),
        figures(S, debt=debt, cash=500_000),
    )

    assert computed(raw_state(YEARS, facts=facts), S, "2.6") == (
        "previous quarter 2026-03-28 (10-Q)",
        f"net debt {now} USD against 1,000,000 USD; previous quarter's equity 10,000,000 USD; {move}%",
        level,
    )


@pytest.mark.parametrize(
    ("previous", "current", "values", "level"),
    [
        pytest.param(
            {"debt": 599_999, "cash": 500_000, "equity": 10_000_000},
            {"debt": 600_000, "cash": 500_000},
            "net debt 100,000 USD against 99,999 USD; previous quarter's equity 10,000,000 USD "
            "(sign changed, or under 1% of equity)",
            "not computable",
            id="under-1-percent-of-equity",
        ),
        pytest.param(
            {"debt": 600_000, "cash": 500_000, "equity": 10_000_000},
            {"debt": 600_000, "cash": 500_000},
            "net debt 100,000 USD against 100,000 USD; previous quarter's equity 10,000,000 USD; +0.00%",
            "none",
            id="at-1-percent-of-equity",
        ),
        pytest.param(
            {"debt": 1_500_000, "cash": 500_000, "equity": 10_000_000},
            {"debt": 400_000, "cash": 500_000},
            "net debt -100,000 USD against 1,000,000 USD; previous quarter's equity 10,000,000 USD "
            "(sign changed, or under 1% of equity)",
            "not computable",
            id="sign-changed",
        ),
        pytest.param(
            {"debt": 500_000, "cash": 1_500_000, "equity": 10_000_000},
            {"debt": 500_000, "cash": 1_800_000},
            "net debt -1,300,000 USD against -1,000,000 USD; previous quarter's equity 10,000,000 USD; "
            "+30.00%",
            "yellow",
            id="net-cash",
        ),
        pytest.param(
            {"debt": 1_500_000, "cash": 500_000, "equity": 0},
            {"debt": 1_500_000, "cash": 500_000},
            "net debt 1,000,000 USD against 1,000,000 USD; previous quarter's equity 0 USD",
            "not computable",
            id="no-equity",
        ),
        pytest.param(
            {"debt": 1_500_000, "equity": 10_000_000},
            {"debt": 1_500_000, "cash": 500_000},
            "net debt 1,000,000 USD against —; previous quarter's equity 10,000,000 USD",
            "not computable",
            id="no-cash",
        ),
    ],
)
def test_net_debt_across_0_from_a_small_base_or_as_net_cash(previous, current, values, level):
    facts = company_facts(figures(P, **previous), figures(S, **current))

    assert computed(raw_state(YEARS, facts=facts), S, "2.6")[1:] == (values, level)


def test_debt_adds_its_current_part():
    facts = company_facts(
        figures(P, debt=1_000_000, debt_current=500_000, cash=500_000, equity=10_000_000),
        figures(S, debt=1_000_000, debt_current=750_000, cash=500_000),
    )

    _, values, level = computed(raw_state(YEARS, facts=facts), S, "2.6")

    assert (
        values
        == "net debt 1,250,000 USD against 1,000,000 USD; previous quarter's equity 10,000,000 USD; +25.00%"
    )
    assert level == "none"


# --------------------------------------------------------------------------- 2.10 and 2.11


@pytest.mark.parametrize(
    ("shares", "move", "level"),
    [
        pytest.param(1_019_900, "+1.99", "none", id="below"),
        pytest.param(1_020_000, "+2.00", "none", id="at"),
        pytest.param(1_020_100, "+2.01", "grey", id="above"),
        pytest.param(980_000, "-2.00", "none", id="at-falling"),
        pytest.param(979_900, "-2.01", "grey", id="above-falling"),
    ],
)
def test_diluted_shares_more_than_2_percent_from_the_previous_quarter_turn_grey(shares, move, level):
    facts = company_facts(figures(P, shares=1_000_000), figures(S, shares=shares))

    assert computed(raw_state(YEARS, facts=facts), S, "2.10") == (
        "previous quarter 2026-03-28 (10-Q)",
        f"weighted diluted shares {shares:,} shares against 1,000,000 shares ({move}%)",
        level,
    )


def test_diluted_shares_are_not_computable_in_a_10_k_season_or_after_one():
    facts = company_facts(
        figures(B, shares=1_000_000), figures(K, shares=1_000_000), figures(P, shares=1_000_000)
    )
    raw = raw_state(YEARS, facts=facts)

    assert computed(raw, K, "2.10") == (
        "previous quarter 2025-09-27 (10-Q)",
        "a 10-K reports the year's average",
        "not computable",
    )
    # The 10-K reports no quarter of its own here, so the next quarter has nothing to compare with.
    facts = company_facts(figures(B, shares=1_000_000), figures(P, shares=1_000_000))
    assert computed(raw_state(YEARS, facts=facts), P, "2.10")[1:] == (
        "weighted diluted shares 1,000,000 shares against —",
        "not computable",
    )


@pytest.mark.parametrize(
    ("goodwill", "added", "level"),
    [
        pytest.param(2_999_000, "9.99", "none", id="below"),
        pytest.param(3_000_000, "10.00", "none", id="at"),
        pytest.param(3_001_000, "10.01", "yellow", id="above"),
        pytest.param(1_000_000, "-10.00", "none", id="impaired"),
    ],
)
def test_goodwill_added_above_10_percent_of_equity_turns_yellow(goodwill, added, level):
    facts = company_facts(figures(P, goodwill=2_000_000), figures(S, goodwill=goodwill, equity=10_000_000))

    assert computed(raw_state(YEARS, facts=facts), S, "2.11") == (
        "previous quarter 2026-03-28 (10-Q)",
        f"goodwill {goodwill:,} USD against 2,000,000 USD; equity 10,000,000 USD; added {added}% of equity",
        level,
    )


def test_goodwill_added_is_not_computable_without_the_equity_of_the_season():
    facts = company_facts(figures(P, goodwill=2_000_000, equity=10_000_000), figures(S, goodwill=3_000_000))

    assert computed(raw_state(YEARS, facts=facts), S, "2.11")[1:] == (
        "goodwill 3,000,000 USD against 2,000,000 USD; equity —",
        "not computable",
    )


# --------------------------------------------------------------------------- 5.7 officers selling


OFFICER = Owner("0001000001", "Roe Jane", False, True, False, "Chief Financial Officer")
OTHER_OFFICER = Owner("0001000002", "Poe Alex", False, True, False, "")
DIRECTOR = Owner("0001000003", "Moe Sam", True, False, False, "")


def form4(*owners: Owner, code: str = "S", issuer: str = CIK) -> Form4:
    """A Form 4 of ``owners`` reporting one transaction of ``code``."""
    transaction = Transaction(date(2026, 7, 1), code, Decimal(1000), Decimal("20.50"), code == "A")
    return Form4(date(2026, 7, 1), issuer, owners, (transaction,))


def insiders(*forms: Form4) -> RawState:
    """``raw/`` whose season S holds ``forms``, each the XML of a Form 4 of its own."""
    items = tuple(
        dated("4", f"0001000001-26-{number:06d}", date(2026, 7, 1), primary="xslF345X06/form4.xml")
        for number in range(1, len(forms) + 1)
    )
    row = replace(S, filings=items)
    files = season_files(
        row, *(filing_files(row, item, form4=form) for item, form in zip(items, forms, strict=True))
    )
    return raw_state((*YEARS[:-1], row), files)


@pytest.mark.parametrize(
    ("forms", "values", "level"),
    [
        pytest.param(
            (form4(OFFICER), form4(OFFICER)),
            "2 Form 4s read, 0 of another issuer left out; officers selling: 1: Roe Jane (Chief Financial "
            "Officer, 0001000001-26-000001, 0001000001-26-000002)",
            "none",
            id="one-officer",
        ),
        pytest.param(
            (form4(OFFICER), form4(OTHER_OFFICER, code="D")),
            "2 Form 4s read, 0 of another issuer left out; officers selling: 2: Roe Jane (Chief Financial "
            "Officer, 0001000001-26-000001); Poe Alex (officer, 0001000001-26-000002)",
            "yellow",
            id="two-officers",
        ),
        pytest.param(
            (form4(DIRECTOR), form4(OFFICER, code="A"), form4(OTHER_OFFICER, code="G")),
            "3 Form 4s read, 0 of another issuer left out; officers selling: 0",
            "none",
            id="no-sale-by-an-officer",
        ),
        pytest.param(
            (form4(OFFICER), form4(OTHER_OFFICER, issuer="0001000099")),
            "2 Form 4s read, 1 of another issuer left out; officers selling: 1: Roe Jane (Chief Financial "
            "Officer, 0001000001-26-000001)",
            "none",
            id="another-issuer",
        ),
        pytest.param(
            (), "0 Form 4s read, 0 of another issuer left out; officers selling: 0", "none", id="none"
        ),
    ],
)
def test_two_officers_selling_turn_yellow(forms, values, level):
    raw = insiders(*forms)

    assert computed(raw, S, "5.7") == ("none", values, level)


# --------------------------------------------------------------------------- the call: 8.5, 8.6, 9.3


TEN = tuple(f"Analyst {number}" for number in range(1, 11))


def questions(*names: str) -> tuple[TranscriptTurn, ...]:
    """Prepared remarks, then each analyst named asks a question that an executive answers."""
    turns = [turn("Pat Lee", "executive", 300)]
    for name in names:
        turns += [turn(name, "analyst", 20), turn("Pat Lee", "executive", 100)]
    return tuple(turns)


def answers(*words: int) -> tuple[TranscriptTurn, ...]:
    """Prepared remarks of 1,000 words, then per answer of ``words`` words the operator's line and an
    analyst's question before it."""
    turns = [turn("Pat Lee", "executive", 1000)]
    for count in words:
        turns += [
            turn("Operator", "operator", 10),
            turn("Analyst 1", "analyst", 20),
            turn("Kim Park", "executive", count),
        ]
    return tuple(turns)


def calls(previous: CallState, current: CallState) -> RawState:
    """``raw/`` where P's call is ``previous`` and S's ``current``."""
    return raw_state(YEARS, season_files(P, call=previous), season_files(S, call=current))


@pytest.mark.parametrize(
    ("names", "values", "level"),
    [
        pytest.param(
            TEN[:8],
            "8 analysts against 10; gone: Analyst 9, Analyst 10; new: none (-20.00%)",
            "none",
            id="below",
        ),
        pytest.param(
            TEN[:7],
            "7 analysts against 10; gone: Analyst 8, Analyst 9, Analyst 10; new: none (-30.00%)",
            "none",
            id="at",
        ),
        pytest.param(
            TEN[:6],
            "6 analysts against 10; gone: Analyst 7, Analyst 8, Analyst 9, Analyst 10; new: none (-40.00%)",
            "grey",
            id="above",
        ),
        pytest.param(
            (*TEN[2:], "Analyst 11"),
            "9 analysts against 10; gone: Analyst 1, Analyst 2; new: Analyst 11 (-10.00%)",
            "none",
            id="gone-and-new",
        ),
    ],
)
def test_analysts_down_more_than_30_percent_turn_grey(names, values, level):
    raw = calls(transcribed(P, *questions(*TEN)), transcribed(S, *questions(*names)))

    assert computed(raw, S, "8.5") == ("previous quarter 2026-03-28 (10-Q)", values, level)


def test_an_analyst_asking_twice_counts_once_however_the_transcript_spaces_the_name():
    raw = calls(
        transcribed(P, *questions("Analyst 1", "Analyst 2")),
        transcribed(S, *questions("Analyst 1", " Analyst  1", "Analyst 2")),
    )

    assert computed(raw, S, "8.5")[1:] == ("2 analysts against 2; gone: none; new: none (+0.00%)", "none")


def test_analysts_are_not_computable_against_a_call_without_questions():
    raw = calls(transcribed(P, turn("Pat Lee", "executive", 300)), transcribed(S, *questions("Analyst 1")))

    assert computed(raw, S, "8.5")[1:] == (
        "1 analyst against 0; gone: none; new: Analyst 1",
        "not computable",
    )


@pytest.mark.parametrize(
    ("words", "values", "level"),
    [
        pytest.param(
            (71,), "mean words of an executive's answer 71.0 against 100.0 (-29.00%)", "none", id="below"
        ),
        pytest.param(
            (70,), "mean words of an executive's answer 70.0 against 100.0 (-30.00%)", "none", id="at"
        ),
        pytest.param(
            (69, 70), "mean words of an executive's answer 69.5 against 100.0 (-30.50%)", "grey", id="above"
        ),
    ],
)
def test_answers_shorter_by_more_than_30_percent_turn_grey(words, values, level):
    # The prepared remarks before the first question and the operator's lines are no answers.
    raw = calls(transcribed(P, *answers(100, 100)), transcribed(S, *answers(*words)))

    assert computed(raw, S, "8.6") == ("previous quarter 2026-03-28 (10-Q)", values, level)


def test_answers_are_not_computable_in_a_call_without_questions():
    raw = calls(transcribed(P, *answers(100)), transcribed(S, turn("Pat Lee", "executive", 1000)))

    assert computed(raw, S, "8.6")[1:] == (
        "mean words of an executive's answer — against 100.0",
        "not computable",
    )


def questions_and_answers(words: int) -> tuple[TranscriptTurn, ...]:
    """Prepared remarks of 500 words, then ``words`` words from the first analyst's question on."""
    return (
        turn("Pat Lee", "executive", 500),
        turn("Analyst 1", "analyst", 100),
        turn("Pat Lee", "executive", words - 100),
    )


@pytest.mark.parametrize(
    ("duration", "words", "values", "level"),
    [
        pytest.param(
            2521,
            1000,
            "duration (seconds) 2,521 against 3,600 (-29.97%); "
            "words from the first analyst's turn 1,000 against 1,000 (+0.00%)",
            "none",
            id="duration-below",
        ),
        pytest.param(
            2520,
            1000,
            "duration (seconds) 2,520 against 3,600 (-30.00%); "
            "words from the first analyst's turn 1,000 against 1,000 (+0.00%)",
            "none",
            id="duration-at",
        ),
        pytest.param(
            2519,
            1000,
            "duration (seconds) 2,519 against 3,600 (-30.03%); "
            "words from the first analyst's turn 1,000 against 1,000 (+0.00%)",
            "yellow",
            id="duration-above",
        ),
        pytest.param(
            3600,
            700,
            "duration (seconds) 3,600 against 3,600 (+0.00%); "
            "words from the first analyst's turn 700 against 1,000 (-30.00%)",
            "none",
            id="words-at",
        ),
        pytest.param(
            3600,
            699,
            "duration (seconds) 3,600 against 3,600 (+0.00%); "
            "words from the first analyst's turn 699 against 1,000 (-30.10%)",
            "yellow",
            id="words-above",
        ),
        pytest.param(
            None,
            699,
            "duration (seconds): not computable; "
            "words from the first analyst's turn 699 against 1,000 (-30.10%)",
            "yellow",
            id="no-duration",
        ),
    ],
)
def test_a_call_compressed_by_more_than_30_percent_turns_yellow(duration, words, values, level):
    raw = calls(
        transcribed(P, *questions_and_answers(1000), duration=3600),
        transcribed(S, *questions_and_answers(words), duration=duration),
    )

    assert computed(raw, S, "9.3") == ("previous quarter 2026-03-28 (10-Q)", values, level)


def test_compression_is_not_computable_without_a_duration_or_a_question():
    raw = calls(
        transcribed(P, *questions_and_answers(1000), duration=None),
        transcribed(S, turn("Pat Lee", "executive", 1000), duration=3000),
    )

    assert computed(raw, S, "9.3")[1:] == (
        "duration (seconds): not computable; words from the first analyst's turn: not computable",
        "not computable",
    )


@pytest.mark.parametrize("identifier", ["8.5", "8.6", "9.3"])
@pytest.mark.parametrize("status", ["unavailable", "waiting", "missing"])
def test_a_call_item_is_unavailable_while_the_call_of_the_season_has_no_transcript(identifier, status):
    raw = calls(transcribed(P, *questions(*TEN)), no_call(S, status))

    assert computed(raw, S, identifier) == (
        "previous quarter 2026-03-28 (10-Q)",
        f"the call has no transcript in raw/ ({status})",
        "unavailable",
    )


@pytest.mark.parametrize("identifier", ["8.5", "8.6", "9.3"])
def test_a_call_item_has_no_baseline_while_the_previous_call_has_no_transcript(identifier):
    raw = calls(no_call(P), transcribed(S, *questions(*TEN)))

    assert computed(raw, S, identifier)[1:] == (
        "the previous season's call has no transcript in raw/",
        "no baseline",
    )


# --------------------------------------------------------------------------- 9.1 timing


TIMING_BASELINE = (
    "previous four 10-Qs: 2026-03-28, 2025-09-27, 2025-06-28, 2025-03-29; "
    "previous four seasons: 2026-03-28, 2025-12-27, 2025-09-27, 2025-06-28"
)
RELEASE = "0000050863-26-000062"


def timed(lag: int = 30, *filings: Dated, previous: Season = P) -> tuple[RawState, Season]:
    """``raw/`` whose season S, filed ``lag`` days after its period end, holds ``filings``; P is
    ``previous``. The previous four 10-Qs were filed at most 30 days after their period ends."""
    row = season("10-Q", S.period, lag, S.filing.accession, *filings)
    return raw_state((PA, A, B, K, previous, row)), row


def timing(lag: int = 30, releases: str = "none", before: str = "none", notices: str = "none") -> str:
    return (
        f"filed {lag} days after the period end; the previous four at most 30; releases accepted after 16:00 "
        f"before a day without a session: {releases}; in the previous four seasons: {before}; "
        f"late-filing notices: {notices}"
    )


@pytest.mark.parametrize(
    ("lag", "level"),
    [
        pytest.param(29, "none", id="below"),
        pytest.param(30, "none", id="at"),
        pytest.param(31, "red", id="above"),
    ],
)
def test_a_filing_later_than_each_of_the_previous_four_of_its_form_turns_red(lag, level):
    raw, row = timed(lag)

    assert computed(raw, row, "9.1") == (TIMING_BASELINE, timing(lag), level)


@pytest.mark.parametrize(
    ("accepted", "late"),
    [
        pytest.param(edt(2026, 7, 24, 15, 59, 59), False, id="friday-before-16"),
        pytest.param(edt(2026, 7, 24, 16, 0, 1), True, id="friday-after-16"),
        pytest.param(edt(2026, 7, 23, 16, 30), False, id="thursday-evening"),
        # Friday 2026-07-03 is Independence Day, observed: the next session is Monday.
        pytest.param(edt(2026, 7, 2, 16, 30), True, id="holiday-eve"),
        pytest.param(None, False, id="no-acceptance-time"),
    ],
)
def test_a_release_accepted_after_16_00_before_a_day_without_a_session_turns_red(accepted, late):
    day = date(2026, 7, 2) if accepted is None else accepted.date()
    raw, row = timed(30, release(RELEASE, day, accepted))

    shown = f"{RELEASE} ({accepted:%Y-%m-%d %H:%M:%S} EDT)" if late else "none"
    assert computed(raw, row, "9.1") == (TIMING_BASELINE, timing(releases=shown), "red" if late else "none")


def test_a_release_accepted_at_16_00_exactly_is_not_after_16_00():
    raw, row = timed(30, release(RELEASE, date(2026, 7, 24), edt(2026, 7, 24, 16, 0, 0)))

    assert computed(raw, row, "9.1")[2] == "none"


def test_a_late_release_is_no_trigger_when_one_of_the_previous_four_seasons_had_one():
    previous = season(
        "10-Q",
        P.period,
        27,
        P.filing.accession,
        release("0000050863-26-000040", date(2026, 4, 24), edt(2026, 4, 24, 16, 30)),
    )
    raw, row = timed(30, release(RELEASE, date(2026, 7, 24), edt(2026, 7, 24, 16, 30)), previous=previous)

    assert computed(raw, row, "9.1") == (
        TIMING_BASELINE,
        timing(
            releases=f"{RELEASE} (2026-07-24 16:30:00 EDT)",
            before="0000050863-26-000040 (2026-04-24 16:30:00 EDT)",
        ),
        "none",
    )


def test_a_late_filing_notice_in_the_season_turns_red():
    notice = dated("NT 10-Q", "0000050863-26-000063", date(2026, 7, 27), primary="nt10q.htm")
    raw, row = timed(30, notice)

    assert computed(raw, row, "9.1") == (
        TIMING_BASELINE,
        timing(notices="NT 10-Q 0000050863-26-000063"),
        "red",
    )
    # Even in the oldest listed season, with nothing to compare with.
    oldest = season("10-Q", S.period, 30, S.filing.accession, notice)
    assert computed(raw_state((oldest,)), oldest, "9.1") == (
        "previous four 10-Qs: none; previous four seasons: none",
        "filed 30 days after the period end; no earlier 10-Q is listed; "
        "late-filing notices: NT 10-Q 0000050863-26-000063",
        "red",
    )


def test_a_10_k_is_timed_against_the_previous_10_ks_alone():
    assert computed(raw_state(YEARS), K, "9.1") == (
        "previous four 10-Ks: none; previous four seasons: 2025-09-27, 2025-06-28, 2025-03-29",
        "filed 34 days after the period end; no earlier 10-K is listed; releases accepted after 16:00 "
        "before a day without a session: none; in the previous four seasons: none; late-filing notices: none",
        "none",
    )


# --------------------------------------------------------------------------- 9.4 text length


def lengths(filing: int) -> tuple[RawState, dict[str, str]]:
    """``raw/`` where P and S each hold an earnings release with one exhibit and a call, and the
    derived texts: S's 10-Q ``filing`` characters long, the other texts as long in both seasons."""
    files, texts = [], {}
    for row, number, length in ((P, "0000050863-26-000040", 1_000), (S, "0000050863-26-000062", filing)):
        item = release(number, row.period + timedelta(days=26))
        held = replace(row, filings=(item,))
        release_files = filing_files(held, item, "primary.htm", "exhibit.htm")
        call = transcribed(held, *questions("Analyst 1"), call_id=1 if row is P else 2)
        files.append(season_files(held, release_files, call=call))
        texts[filing_document(held).doc_id] = "x" * length
        texts[release_files.documents[1].doc_id] = "x" * 500
        texts[call.documents[0].doc_id] = "x" * 2_000
    return raw_state((PA, A, B, K, files[0].season, files[1].season), *files), texts


@pytest.mark.parametrize(
    ("filing", "move", "level"),
    [
        pytest.param(1_199, "+19.90", "none", id="below"),
        pytest.param(1_200, "+20.00", "none", id="at"),
        pytest.param(1_201, "+20.10", "grey", id="above"),
        pytest.param(800, "-20.00", "none", id="at-shorter"),
        pytest.param(799, "-20.10", "grey", id="above-shorter"),
    ],
)
def test_a_text_more_than_20_percent_longer_or_shorter_turns_grey(filing, move, level):
    raw, texts = lengths(filing)

    assert computed(raw, S, "9.4", texts) == (
        "previous 10-Q 2026-03-28 (10-Q); previous season 2026-03-28 (10-Q)",
        f"10-Q {filing:,} characters against 1,000 ({move}%); release exhibits 500 characters against 500 "
        "(+0.00%); call 2,000 characters against 2,000 (+0.00%)",
        level,
    )


def test_a_filing_is_compared_with_the_previous_one_of_its_form():
    texts = {
        filing_document(row).doc_id: "x" * length for row, length in ((B, 1_000), (K, 3_000), (P, 1_100))
    }

    assert computed(raw_state(YEARS), P, "9.4", texts) == (
        "previous 10-Q 2025-09-27 (10-Q); previous season 2025-12-27 (10-K)",
        "10-Q 1,100 characters against 1,000 (+10.00%); release exhibits: not in raw/; call: not in raw/",
        "none",
    )


def test_a_text_not_in_raw_is_named_and_leaves_the_lengths_not_computable():
    raw = raw_state(YEARS, season_files(S, filed=False))

    assert computed(raw, S, "9.4")[1:] == (
        "10-Q: not in raw/; release exhibits: not in raw/; call: not in raw/",
        "not computable",
    )


# --------------------------------------------------------------------------- 9.5 8-K count


def with_eight_ks(row: Season, count: int, *amendments: int) -> Season:
    """``row`` holding ``count`` 8-Ks of Item 8.01, then 8-K/As."""
    day = row.period + timedelta(days=10)
    reports = tuple(
        dated("8-K", f"0000050863-26-{number:06d}", day, "8.01") for number in range(1, count + 1)
    )
    amended = tuple(dated("8-K/A", f"0000050863-26-{number:06d}", day) for number in amendments)
    return replace(row, filings=reports + amended)


@pytest.mark.parametrize(
    ("count", "shown", "level"),
    [
        pytest.param(1, "1 8-K", "none", id="one"),
        pytest.param(3, "3 8-Ks", "none", id="at"),
        pytest.param(4, "4 8-Ks", "grey", id="above"),
    ],
)
def test_more_8_ks_than_twice_the_previous_four_seasons_mean_turn_grey(count, shown, level):
    # The oldest season's five 8-Ks lie beyond the previous four seasons; 8-K/As count for none.
    rows = (
        with_eight_ks(PA, 5),
        with_eight_ks(A, 2),
        with_eight_ks(B, 1, 900),
        with_eight_ks(K, 2),
        with_eight_ks(P, 1),
        with_eight_ks(S, count, 901, 902),
    )

    assert computed(raw_state(rows), rows[-1], "9.5") == (
        "previous four seasons: 2026-03-28, 2025-12-27, 2025-09-27, 2025-06-28",
        f"{shown} against a mean of 1.50 (1, 2, 1, 2)",
        level,
    )


# --------------------------------------------------------------------------- 9.6 call cancelled


def with_calls(current: CallState, *previous: Season) -> RawState:
    """``raw/`` where S's call is ``current`` and each season of ``previous`` had a call transcribed."""
    held = [season_files(row, call=transcribed(row, *questions("Analyst 1"))) for row in previous]
    return raw_state(YEARS, *held, season_files(S, call=current))


@pytest.mark.parametrize(
    ("current", "previous", "values", "level"),
    [
        pytest.param(
            no_call(S),
            (A, B, K, P),
            "the season's call: unavailable; listed in the previous seasons: 4 of 4",
            "red",
            id="cancelled",
        ),
        pytest.param(
            no_call(S),
            (A, B, P),
            "the season's call: unavailable; listed in the previous seasons: 3 of 4",
            "none",
            id="one-season-without-a-call",
        ),
        pytest.param(
            transcribed(S, *questions("Analyst 1")),
            (A, B, K, P),
            "the season's call: transcript; listed in the previous seasons: 4 of 4",
            "none",
            id="transcript",
        ),
        pytest.param(
            no_call(S, "waiting"),
            (A, B, K, P),
            "the season's call: waiting; listed in the previous seasons: 4 of 4",
            "none",
            id="waiting",
        ),
        pytest.param(
            no_call(S, "missing", CallEvent(248001, CALL_AT)),
            (A, B, K, P),
            "the season's call: missing; listed in the previous seasons: 4 of 4",
            "none",
            id="missing",
        ),
    ],
)
def test_a_call_unavailable_after_a_call_in_each_of_the_previous_four_seasons_turns_red(
    current, previous, values, level
):
    assert computed(with_calls(current, *previous), S, "9.6") == (
        "previous four seasons: 2026-03-28, 2025-12-27, 2025-09-27, 2025-06-28",
        values,
        level,
    )


def test_a_call_listed_without_its_transcript_counts_as_listed():
    missing = no_call(K, "missing", CallEvent(35174, edt(2026, 1, 29, 17, 0)))
    raw = raw_state(
        YEARS,
        *(season_files(row, call=transcribed(row, *questions("Analyst 1"))) for row in (A, B, P)),
        season_files(K, call=missing),
        season_files(S, call=no_call(S)),
    )

    assert computed(raw, S, "9.6")[1:] == (
        "the season's call: unavailable; listed in the previous seasons: 4 of 4",
        "red",
    )


def test_a_call_unavailable_with_fewer_than_four_seasons_before_it_has_no_baseline():
    raw = raw_state(
        YEARS, *(season_files(row, call=transcribed(row, *questions("Analyst 1"))) for row in (PA, A))
    )

    assert computed(raw, B, "9.6") == (
        "previous four seasons: 2025-06-28, 2025-03-29",
        "the season's call: unavailable; listed in the previous seasons: 2 of 2",
        "no baseline",
    )


# --------------------------------------------------------------------------- baselines


PROXY = dated("DEF 14A", "0001193125-26-112233", date(2026, 3, 20), primary="def14a.htm")
K_PROXY = replace(K, filings=(PROXY,))
OLD = (
    season("10-Q", date(2024, 6, 29), 30, "0000050863-24-000020"),
    season("10-Q", date(2024, 9, 28), 30, "0000050863-24-000030"),
    season("10-K", date(2024, 12, 28), 34, "0000050863-25-000005"),
)
LISTED = Seasons((*OLD, PA, A, B, K_PROXY, P, S), (), (), OLD[0].filing.filed)


@pytest.mark.parametrize(
    ("row", "kind", "expected"),
    [
        pytest.param(S, "previous quarter", ("2026-03-28",), id="previous-quarter"),
        pytest.param(S, "previous guidance", ("2026-03-28",), id="previous-guidance"),
        pytest.param(S, "same quarter last year", ("2025-06-28",), id="same-quarter-last-year"),
        pytest.param(
            S,
            "previous quarter and same quarter last year",
            ("2026-03-28", "2025-06-28"),
            id="previous-quarter-and-same-quarter-last-year",
        ),
        pytest.param(S, "previous 10-K", ("2025-12-27",), id="previous-10-K"),
        pytest.param(S, "previous filings", ("2026-03-28", "2025-12-27"), id="previous-filings"),
        pytest.param(S, "previous proxy", ("2025-12-27",), id="previous-proxy"),
        pytest.param(
            S,
            "previous eight seasons",
            (
                "2026-03-28",
                "2025-12-27",
                "2025-09-27",
                "2025-06-28",
                "2025-03-29",
                "2024-12-28",
                "2024-09-28",
                "2024-06-29",
            ),
            id="previous-eight-seasons",
        ),
        pytest.param(
            S,
            "previous four seasons",
            ("2026-03-28", "2025-12-27", "2025-09-27", "2025-06-28"),
            id="previous-four-seasons",
        ),
        pytest.param(S, "none", (), id="none"),
        pytest.param(P, "previous filings", ("2025-12-27",), id="previous-filings-after-a-10-K"),
        pytest.param(P, "same quarter last year", ("2025-03-29",), id="same-quarter-last-year-of-a-10-Q"),
        pytest.param(
            K_PROXY, "same quarter last year", ("2024-12-28",), id="same-quarter-last-year-of-a-10-K"
        ),
        pytest.param(K_PROXY, "previous 10-K", ("2024-12-28",), id="previous-10-K-of-a-10-K"),
        pytest.param(K_PROXY, "previous proxy", (), id="no-earlier-proxy"),
        pytest.param(OLD[0], "previous quarter", (), id="oldest-previous-quarter"),
        pytest.param(OLD[0], "previous eight seasons", (), id="oldest-previous-eight-seasons"),
        pytest.param(OLD[0], "same quarter last year", (), id="oldest-same-quarter-last-year"),
    ],
)
def test_each_baseline_names_its_listed_seasons_newest_first(row, kind, expected):
    found = baseline_seasons(LISTED, row, kind)

    assert tuple(str(other.period) for other in found) == expected


def test_the_proxy_baseline_reaches_eight_seasons_back_only():
    rows = (
        K_PROXY,
        *(
            season("10-Q", K.period + timedelta(days=91 * n), 30, f"0000050863-27-{n:06d}")
            for n in range(1, 10)
        ),
    )
    listing = Seasons(rows, (), (), K.filing.filed)

    assert baseline_seasons(listing, rows[8], "previous proxy") == (K_PROXY,)
    assert baseline_seasons(listing, rows[9], "previous proxy") == ()


# --------------------------------------------------------------------------- measures.md


GK = season("10-K", date(2025, 12, 27), 34, "0000050863-26-000012", accepted=est(2026, 1, 30, 16, 5, 12))
FORM4_FILING = dated(
    "4",
    "0001234567-26-000001",
    date(2026, 4, 2),
    primary="xslF345X06/form4.xml",
    filed=date(2026, 4, 3),
    accepted=edt(2026, 4, 3, 18, 2, 11),
)
SHELF = dated(
    "S-3ASR",
    "0000050863-26-000033",
    date(2026, 4, 10),
    primary="s3asr.htm",
    accepted=edt(2026, 4, 10, 8, 0, 5),
)
DEPARTURE = dated(
    "8-K",
    "0000050863-26-000036",
    date(2026, 4, 15),
    "5.02",
    "intc-20260415.htm",
    filed=date(2026, 4, 16),
    accepted=edt(2026, 4, 16, 17, 30),
)
SCHEDULE = dated(
    "SCHEDULE 13G/A",
    "0000102909-26-000123",
    date(2026, 4, 20),
    primary="xslSCHEDULE_13G_X02/primary_doc.xml",
    accepted=edt(2026, 4, 20, 11, 0),
)
RESULTS = release("0000050863-26-000040", date(2026, 4, 23), edt(2026, 4, 23, 16, 2, 3))
GQ = season(
    "10-Q",
    date(2026, 3, 28),
    27,
    "0000050863-26-000041",
    FORM4_FILING,
    SHELF,
    DEPARTURE,
    SCHEDULE,
    RESULTS,
    accepted=edt(2026, 4, 24, 16, 1),
)
GOLDEN_FACTS = company_facts(
    figures(
        GQ,
        revenue=12_700_000_000,
        cost=7_620_000_000,
        operating=635_000_000,
        income=508_000_000,
        cash_flow=1_016_000_000,
        receivables=3_810_000_000,
        inventory=11_430_000_000,
        payables=9_144_000_000,
        debt=44_000_000_000,
        debt_current=6_000_000_000,
        cash=15_000_000_000,
        shares=4_400_000_000,
        goodwill=24_000_000_000,
        equity=100_000_000_000,
        assets=200_000_000_000,
        eps="0.11",
    ),
    figures(
        GK,
        revenue=14_000_000_000,
        cost=8_960_000_000,
        operating=560_000_000,
        debt=46_000_000_000,
        cash=14_000_000_000,
        goodwill=23_000_000_000,
        equity=98_000_000_000,
    ),
)
GOLDEN_TEXTS = {
    "10-Q_2026-03-28_0000050863-26-000041_intc-20260328": "x" * 12_000,
    "10-K_2025-12-27_0000050863-26-000012_intc-20251227": "x" * 15_000,
    "8-K_2026-04-23_0000050863-26-000040_q126earningsrelease": "x" * 4_000,
    "call_2026-03-28_26083": "x" * 30_000,
}


def golden_raw() -> RawState:
    """The fiscal year ended 2025-12-27, the first season listed, then the quarter ended
    2026-03-28: its insider's Form 4, a shelf registration, an 8-K with Item 5.02, a holder's
    Schedule 13G amendment, its earnings release and its call."""
    files = season_files(
        GQ,
        filing_files(GQ, FORM4_FILING, form4=form4(OFFICER)),
        filing_files(GQ, DEPARTURE, "intc-20260415.htm"),
        filing_files(GQ, SCHEDULE, "primary_doc.xml"),
        filing_files(GQ, RESULTS, "intc-20260423.htm", "q126earningsrelease.htm"),
        call=transcribed(GQ, *questions("Analyst 1"), call_id=26083, at=edt(2026, 4, 23, 17, 0)),
    )
    return raw_state((GK, GQ), files, facts=GOLDEN_FACTS)


RULE = {item.id: item.rule for item in PYTHON_ITEMS}
TEN_K = "10-K_2025-12-27_0000050863-26-000012_intc-20251227"
GOLDEN = f"""# INTC · 2026-03-28 · measures

Season: the 10-Q for the period ended 2026-03-28, accession 0000050863-26-000041, filed 2026-04-24, accepted 2026-04-24 16:01:00 EDT.
Call: transcript as of the calls list of 2026-08-01 (call 26083 of 2026-04-23).
Company facts: companyfacts_20260801T090000EDT.json (present).

## Baselines

Each baseline of the catalogue, the listed seasons it names and their documents in raw/: a reading's baseline line names some of these DOC_IDs.

| Baseline | Seasons | Documents in raw/ (DOC_ID) |
| --- | --- | --- |
| previous guidance | 2025-12-27 (10-K) | {TEN_K} |
| previous eight seasons | 2025-12-27 (10-K) | {TEN_K} |
| previous quarter and same quarter last year | 2025-12-27 (10-K) | {TEN_K} |
| same quarter last year | none listed | none |
| previous quarter | 2025-12-27 (10-K) | {TEN_K} |
| previous 10-K | 2025-12-27 (10-K) | {TEN_K} |
| previous filings | 2025-12-27 (10-K) | {TEN_K} |
| previous proxy | none listed | none |
| previous four seasons | 2025-12-27 (10-K) | {TEN_K} |

## Filings of the season

| Form | Dated | Filed | Accepted | Accession | Items | Documents (DOC_ID) |
| --- | --- | --- | --- | --- | --- | --- |
| 10-Q | 2026-03-28 | 2026-04-24 | 2026-04-24 16:01:00 EDT | 0000050863-26-000041 |  | 10-Q_2026-03-28_0000050863-26-000041_intc-20260328 |
| 4 | 2026-04-02 | 2026-04-03 | 2026-04-03 18:02:11 EDT | 0001234567-26-000001 |  | Form 4 XML (read by Python) |
| S-3ASR | 2026-04-10 | 2026-04-10 | 2026-04-10 08:00:05 EDT | 0000050863-26-000033 |  | listed only |
| 8-K | 2026-04-15 | 2026-04-16 | 2026-04-16 17:30:00 EDT | 0000050863-26-000036 | 5.02 | 8-K_2026-04-15_0000050863-26-000036_intc-20260415 |
| SCHEDULE 13G/A | 2026-04-20 | 2026-04-20 | 2026-04-20 11:00:00 EDT | 0000102909-26-000123 |  | SCHEDULE13GA_2026-04-20_0000102909-26-000123_primary_doc |
| 8-K | 2026-04-23 | 2026-04-23 | 2026-04-23 16:02:03 EDT | 0000050863-26-000040 | 2.02,9.01 | 8-K_2026-04-23_0000050863-26-000040_intc-20260423; 8-K_2026-04-23_0000050863-26-000040_q126earningsrelease |

## Figures

| Measure | Season | Value | Unit | Concept | Accession | Start | End | Formula or reason |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| revenue | 2026-03-28 | 12,700,000,000 | USD | RevenueFromContractWithCustomerExcludingAssessedTax | 0000050863-26-000041 | 2025-12-28 | 2026-03-28 | reported for the quarter |
| cost_of_revenue | 2026-03-28 | 7,620,000,000 | USD | CostOfGoodsAndServicesSold | 0000050863-26-000041 | 2025-12-28 | 2026-03-28 | reported for the quarter |
| gross_profit | 2026-03-28 | 5,080,000,000 | USD | RevenueFromContractWithCustomerExcludingAssessedTax − CostOfGoodsAndServicesSold | 0000050863-26-000041 | 2025-12-28 | 2026-03-28 | revenue less cost of revenue |
| operating_income | 2026-03-28 | 635,000,000 | USD | OperatingIncomeLoss | 0000050863-26-000041 | 2025-12-28 | 2026-03-28 | reported for the quarter |
| net_income | 2026-03-28 | 508,000,000 | USD | NetIncomeLoss | 0000050863-26-000041 | 2025-12-28 | 2026-03-28 | reported for the quarter |
| operating_cash_flow | 2026-03-28 | 1,016,000,000 | USD | NetCashProvidedByUsedInOperatingActivities | 0000050863-26-000041 | 2025-12-28 | 2026-03-28 | reported for the quarter |
| receivables | 2026-03-28 | 3,810,000,000 | USD | AccountsReceivableNetCurrent | 0000050863-26-000041 | — | 2026-03-28 | the balance at the period end |
| inventory | 2026-03-28 | 11,430,000,000 | USD | InventoryNet | 0000050863-26-000041 | — | 2026-03-28 | the balance at the period end |
| payables | 2026-03-28 | 9,144,000,000 | USD | AccountsPayableCurrent | 0000050863-26-000041 | — | 2026-03-28 | the balance at the period end |
| debt | 2026-03-28 | 50,000,000,000 | USD | LongTermDebtNoncurrent, DebtCurrent | 0000050863-26-000041 | — | 2026-03-28 | LongTermDebtNoncurrent + DebtCurrent (an absent part counts 0) |
| cash | 2026-03-28 | 15,000,000,000 | USD | CashAndCashEquivalentsAtCarryingValue | 0000050863-26-000041 | — | 2026-03-28 | the balance at the period end |
| diluted_shares | 2026-03-28 | 4,400,000,000 | shares | WeightedAverageNumberOfDilutedSharesOutstanding | 0000050863-26-000041 | 2025-12-28 | 2026-03-28 | reported for the quarter |
| goodwill | 2026-03-28 | 24,000,000,000 | USD | Goodwill | 0000050863-26-000041 | — | 2026-03-28 | the balance at the period end |
| equity | 2026-03-28 | 100,000,000,000 | USD | StockholdersEquity | 0000050863-26-000041 | — | 2026-03-28 | the balance at the period end |
| assets | 2026-03-28 | 200,000,000,000 | USD | Assets | 0000050863-26-000041 | — | 2026-03-28 | the balance at the period end |
| diluted_eps | 2026-03-28 | 0.11 | USD/shares | EarningsPerShareDiluted | 0000050863-26-000041 | 2025-12-28 | 2026-03-28 | reported for the quarter |
| revenue | 2025-12-27 | 14,000,000,000 | USD | RevenueFromContractWithCustomerExcludingAssessedTax | 0000050863-26-000012 | 2025-09-28 | 2025-12-27 | reported for the quarter |
| cost_of_revenue | 2025-12-27 | 8,960,000,000 | USD | CostOfGoodsAndServicesSold | 0000050863-26-000012 | 2025-09-28 | 2025-12-27 | reported for the quarter |
| gross_profit | 2025-12-27 | 5,040,000,000 | USD | RevenueFromContractWithCustomerExcludingAssessedTax − CostOfGoodsAndServicesSold | 0000050863-26-000012 | 2025-09-28 | 2025-12-27 | revenue less cost of revenue |
| operating_income | 2025-12-27 | 560,000,000 | USD | OperatingIncomeLoss | 0000050863-26-000012 | 2025-09-28 | 2025-12-27 | reported for the quarter |
| net_income | 2025-12-27 | — | USD | — | — | — | — | the filing 0000050863-26-000012 reports no NetIncomeLoss or ProfitLoss for the quarter |
| operating_cash_flow | 2025-12-27 | — | USD | — | — | — | — | the filing 0000050863-26-000012 reports no NetCashProvidedByUsedInOperatingActivities for the quarter |
| receivables | 2025-12-27 | — | USD | — | — | — | — | the filing 0000050863-26-000012 reports no AccountsReceivableNetCurrent or ReceivablesNetCurrent at 2025-12-27 |
| inventory | 2025-12-27 | — | USD | — | — | — | — | the filing 0000050863-26-000012 reports no InventoryNet at 2025-12-27 |
| payables | 2025-12-27 | — | USD | — | — | — | — | the filing 0000050863-26-000012 reports no AccountsPayableCurrent or AccountsPayableTradeCurrent at 2025-12-27 |
| debt | 2025-12-27 | 46,000,000,000 | USD | LongTermDebtNoncurrent | 0000050863-26-000012 | — | 2025-12-27 | LongTermDebtNoncurrent (an absent part counts 0) |
| cash | 2025-12-27 | 14,000,000,000 | USD | CashAndCashEquivalentsAtCarryingValue | 0000050863-26-000012 | — | 2025-12-27 | the balance at the period end |
| diluted_shares | 2025-12-27 | — | shares | — | — | — | — | the filing 0000050863-26-000012 reports no WeightedAverageNumberOfDilutedSharesOutstanding for the quarter |
| goodwill | 2025-12-27 | 23,000,000,000 | USD | Goodwill | 0000050863-26-000012 | — | 2025-12-27 | the balance at the period end |
| equity | 2025-12-27 | 98,000,000,000 | USD | StockholdersEquity | 0000050863-26-000012 | — | 2025-12-27 | the balance at the period end |
| assets | 2025-12-27 | — | USD | — | — | — | — | the filing 0000050863-26-000012 reports no Assets at 2025-12-27 |
| diluted_eps | 2025-12-27 | — | USD/shares | — | — | — | — | the filing 0000050863-26-000012 reports no EarningsPerShareDiluted for the quarter |

## Python items

### 2.1 Revenue and net income growth

baseline: same quarter last year none; previous quarter 2025-12-27 (10-K) and its year-ago none
values: a season the comparison needs is not listed
rule: {RULE["2.1"]}
level: no baseline

### 2.2 Gross and operating margins

baseline: same quarter last year none; previous quarter 2025-12-27 (10-K)
values: gross margin 40.00% against 36.00% a quarter ago (+400 bps); operating margin 5.00% against 4.00% a quarter ago (+100 bps)
rule: {RULE["2.2"]}
level: yellow

### 2.3 Operating cash flow to net income

baseline: same quarter last year none; previous quarter 2025-12-27 (10-K) and its year-ago none
values: the same quarter last year is not listed
rule: {RULE["2.3"]}
level: no baseline

### 2.4 Days of receivables, inventory and payables

baseline: same quarter last year none
values: the same quarter last year is not listed
rule: {RULE["2.4"]}
level: no baseline

### 2.5 Receivables growth against revenue growth

baseline: same quarter last year none
values: the same quarter last year is not listed
rule: {RULE["2.5"]}
level: no baseline

### 2.6 Net debt

baseline: previous quarter 2025-12-27 (10-K)
values: net debt 35,000,000,000 USD against 32,000,000,000 USD; previous quarter's equity 98,000,000,000 USD; +9.38%
rule: {RULE["2.6"]}
level: none

### 2.10 Weighted diluted shares

baseline: previous quarter 2025-12-27 (10-K)
values: weighted diluted shares 4,400,000,000 shares against —
rule: {RULE["2.10"]}
level: not computable

### 2.11 Goodwill added

baseline: previous quarter 2025-12-27 (10-K)
values: goodwill 24,000,000,000 USD against 23,000,000,000 USD; equity 100,000,000,000 USD; added 1.00% of equity
rule: {RULE["2.11"]}
level: none

### 5.7 Officers selling

baseline: none
values: 1 Form 4 read, 0 of another issuer left out; officers selling: 1: Roe Jane (Chief Financial Officer, 0001234567-26-000001)
rule: {RULE["5.7"]}
level: none

### 8.5 Analysts on the call

baseline: previous quarter 2025-12-27 (10-K)
values: the previous season's call has no transcript in raw/
rule: {RULE["8.5"]}
level: no baseline

### 8.6 Shorter answers

baseline: previous quarter 2025-12-27 (10-K)
values: the previous season's call has no transcript in raw/
rule: {RULE["8.6"]}
level: no baseline

### 9.1 Filing timing

baseline: previous four 10-Qs: none; previous four seasons: 2025-12-27
values: filed 27 days after the period end; no earlier 10-Q is listed; releases accepted after 16:00 before a day without a session: none; in the previous four seasons: none; late-filing notices: none
rule: {RULE["9.1"]}
level: none

### 9.3 Questions and answers compressed

baseline: previous quarter 2025-12-27 (10-K)
values: the previous season's call has no transcript in raw/
rule: {RULE["9.3"]}
level: no baseline

### 9.4 Text length

baseline: previous 10-Q none; previous season 2025-12-27 (10-K)
values: 10-Q: 12,000 characters, no baseline; release exhibits: 4,000 characters, no baseline; call: 30,000 characters, no baseline
rule: {RULE["9.4"]}
level: no baseline

### 9.5 8-K count

baseline: previous four seasons: 2025-12-27
values: 2 8-Ks against a mean of 0.00 (0)
rule: {RULE["9.5"]}
level: grey

### 9.6 Call cancelled

baseline: previous four seasons: 2025-12-27
values: the season's call: transcript; listed in the previous seasons: 0 of 1
rule: {RULE["9.6"]}
level: none

## Inputs for the bot's items

- 1.7: revenue 12,700,000,000 USD; net income 508,000,000 USD; diluted earnings per share 0.11 USD/shares.
- 2.9, 4.4: net income 508,000,000 USD.
- 4.7: stockholders' equity 100,000,000,000 USD.
- 6.4: stockholders' equity 100,000,000,000 USD; total assets 200,000,000,000 USD.
- 3.1: the 8-Ks with Item 4.01: none.
- 3.4: the 8-Ks with Item 4.02: none.
- 5.1, 5.2, 5.3: the 8-Ks with Item 5.02: 8-K_2026-04-15_0000050863-26-000036_intc-20260415.
- 5.4: the beneficial owners' schedules: SCHEDULE13GA_2026-04-20_0000102909-26-000123_primary_doc (SCHEDULE 13G/A, filer prefix 0000102909).
- 6.3: the 8-Ks with Items 3.02 or 1.01: none; the registrations listed: S-3ASR 0000050863-26-000033 filed 2026-04-10.
- Amendments listed: none.
"""  # noqa: E501


def test_measures_md_of_a_small_season():
    measures = measured(golden_raw(), GQ, GOLDEN_TEXTS)

    assert measures.text == GOLDEN


def test_measures_md_names_what_is_missing():
    no_facts = raw_state((GK, GQ))
    measures = measured(no_facts, GQ)

    lines = measures.text.splitlines()
    assert lines[2:5] == [
        "Season: the 10-Q for the period ended 2026-03-28, accession 0000050863-26-000041, filed 2026-04-24, "
        "accepted 2026-04-24 16:01:00 EDT.",
        "Call: unavailable as of the calls list of 2026-08-01.",
        "Company facts: none (missing: no companyfacts file is in raw/; run fetch).",
    ]
    assert lines[lines.index("## Figures") + 2 : lines.index("## Figures") + 5] == [
        "| Measure | Season | Value | Unit | Concept | Accession | Start | End | Formula or reason |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
        "",
    ]
    # The listed filings whose documents are not in raw/ are named as such.
    assert (
        "| 8-K | 2026-04-23 | 2026-04-23 | 2026-04-23 16:02:03 EDT | 0000050863-26-000040 | 2.02,9.01 | "
        "not in raw/ |" in lines
    )
    assert "- 5.1, 5.2, 5.3: the 8-Ks with Item 5.02: 0000050863-26-000036 (not in raw/)." in lines
    assert (
        "- 5.4: the beneficial owners' schedules: SCHEDULE 13G/A 0000102909-26-000123 (not in raw/)." in lines
    )
    assert (
        "- 1.7: revenue not computable; net income not computable; diluted earnings per share not "
        "computable." in lines
    )


@pytest.mark.parametrize(
    ("raw", "row", "texts"),
    [
        pytest.param(golden_raw(), GQ, GOLDEN_TEXTS, id="golden-quarter"),
        pytest.param(golden_raw(), GK, GOLDEN_TEXTS, id="golden-year"),
        pytest.param(raw_state(YEARS), S, None, id="no-facts"),
        pytest.param(insiders(form4(OFFICER), form4(OTHER_OFFICER, code="D")), S, None, id="officers"),
        pytest.param(calls(transcribed(P, *questions(*TEN)), no_call(S)), S, None, id="calls"),
    ],
)
def test_the_text_measures_writes_passes_the_wording_rule(raw, row, texts):
    text = measured(raw, row, texts).text

    assert WORDING.search(text) is None


def test_the_python_items_rules_and_titles_pass_the_wording_rule():
    for item in PYTHON_ITEMS:
        assert WORDING.search(item.title) is None, item.id
        assert WORDING.search(item.rule) is None, item.id
    assert BY_ID["5.7"].heading == "5.7 Officers selling"
