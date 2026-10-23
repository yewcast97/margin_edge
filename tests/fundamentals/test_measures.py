"""script/measures.py: the Python items of a season, the seasons each baseline names and measures.md.

Every season here is built from the dataclasses ``documents.season_documents`` returns, not
from a raw tree: the listed seasons (``filings.Season``), the company facts each season's own
filing reports (``facts.CompanyFacts``: a quarter's flows over the 91 days to its period end,
the balances at its end), and each season's files (``documents.SeasonFiles``) with their Form
4s and calls. ``measures`` reads no file, so the paths only name documents. Each item is
checked row by row: what it compares, its baseline, the old value (the baseline's), the new
value (the season's) and the change, written out by hand, with the statuses its cells may hold
(``no baseline``, ``not computable``, ``unavailable``, ``—``) and its note; no threshold is
left to test. ``GOLDEN`` is the whole ``measures.md`` of a small season (its rule lines are the
catalogue's, ``items.BY_ID``); and every text ``measures`` writes passes the wording rule
(``readings.WORDING``).
"""

from collections.abc import Iterable, Sequence
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
    Row,
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


def measured(raw: RawState, row: Season) -> Measures:
    """The measures of ``row``'s season."""
    files = raw.season(row.period)
    assert files is not None
    return season_measures(raw, files)


def computed(raw: RawState, row: Season, identifier: str) -> Reading:
    """The Python item ``identifier`` of ``row``'s season."""
    return measured(raw, row).reading(identifier)


def cells(reading: Reading) -> list[tuple[str, str, str, str, str]]:
    """Each row of ``reading`` as (compared, baseline, old, new, change)."""
    return [(row.compared, row.baseline, row.old, row.new, row.change) for row in reading.rows]


NO_FACTS = "no company facts are in raw/"
PREVIOUS_CALL = "the previous season's call has no transcript in raw/"
NEWEST_FIRST = "the old values are newest first"
PREVIOUS = "previous quarter 2026-03-28 (10-Q)"
YEAR_AGO = "same quarter last year 2025-06-28 (10-Q)"
YEARS_NOTE = (
    "the year before this season: 2025-06-28 (10-Q); the year before the previous quarter: 2025-03-29 "
    "(10-Q); not computable where a figure is missing or the year-ago figure is 0 or below"
)
RECORD = "previous four seasons: 2026-03-28, 2025-12-27, 2025-09-27, 2025-06-28"
LAG = "days from the period end to the 10-Q's filing"
TEN_QS = "previous four 10-Qs: 2026-03-28, 2025-09-27, 2025-06-28, 2025-03-29"
LATE = "earnings releases accepted after 16:00 on a day whose next XNYS session is not the next day"
NOTICES = "late-filing notices (NT 10-K, NT 10-Q)"


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
    ]
    assert [found.item for found in measures.readings] == list(PYTHON_ITEMS)
    assert all(isinstance(found, Reading) and found.rows for found in measures.readings)
    assert all(isinstance(row, Row) for found in measures.readings for row in found.rows)
    assert (measures.reading("9.4").item.title, measures.reading("9.5").item.title) == (
        "8-K count",
        "Call cancelled",
    )


def test_measures_need_a_listed_season():
    raw = raw_state(YEARS)
    files = raw.season(S.period)
    assert files is not None

    with pytest.raises(ValueError, match=r"^INTC: no season is listed$"):
        season_measures(replace(raw, listing=None), files)


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


@pytest.mark.parametrize(
    ("identifier", "count"),
    [("2.1", 2), ("2.2", 4), ("2.3", 2), ("2.4", 3), ("2.5", 2), ("2.6", 1), ("2.10", 1), ("2.11", 2)],
)
def test_without_company_facts_every_financial_value_is_not_computable(identifier, count):
    found = computed(raw_state(YEARS), S, identifier)

    assert len(found.rows) == count
    assert {(row.old, row.new, row.change) for row in found.rows} == {
        ("not computable", "not computable", "—")
    }
    assert found.note.split("; ")[0] == NO_FACTS


NONE_LISTED = "previous quarter none listed"
NOT_LISTED_YEAR = "same quarter last year none listed"


@pytest.mark.parametrize(
    ("identifier", "rows", "note"),
    [
        pytest.param(
            "2.1",
            [
                (
                    "revenue growth on the same quarter a year before (%)",
                    NONE_LISTED,
                    "no baseline",
                    "no baseline",
                    "—",
                ),
                (
                    "net income growth on the same quarter a year before (%)",
                    NONE_LISTED,
                    "no baseline",
                    "no baseline",
                    "—",
                ),
            ],
            "the year before this season: none listed; the year before the previous quarter: none listed; "
            "not computable where a figure is missing or the year-ago figure is 0 or below",
            id="2.1",
        ),
        pytest.param(
            "2.2",
            [
                ("gross margin (%)", NOT_LISTED_YEAR, "no baseline", "not computable", "—"),
                ("gross margin (%)", NONE_LISTED, "no baseline", "not computable", "—"),
                ("operating margin (%)", NOT_LISTED_YEAR, "no baseline", "not computable", "—"),
                ("operating margin (%)", NONE_LISTED, "no baseline", "not computable", "—"),
            ],
            "",
            id="2.2",
        ),
        pytest.param(
            "2.3",
            [
                ("operating cash flow ÷ net income", NOT_LISTED_YEAR, "no baseline", "not computable", "—"),
                ("operating cash flow ÷ net income", NONE_LISTED, "no baseline", "not computable", "—"),
            ],
            "",
            id="2.3",
        ),
        pytest.param(
            "2.4",
            [
                ("days of sales outstanding", NOT_LISTED_YEAR, "no baseline", "not computable", "—"),
                ("days of inventory", NOT_LISTED_YEAR, "no baseline", "not computable", "—"),
                ("days of payables", NOT_LISTED_YEAR, "no baseline", "not computable", "—"),
            ],
            "",
            id="2.4",
        ),
        pytest.param(
            "2.5",
            [
                (
                    "receivables at the period end (USD)",
                    NOT_LISTED_YEAR,
                    "no baseline",
                    "not computable",
                    "—",
                ),
                ("revenue of the quarter (USD)", NOT_LISTED_YEAR, "no baseline", "1,000", "—"),
            ],
            "",
            id="2.5",
        ),
        pytest.param(
            "2.6", [("net debt (USD)", NONE_LISTED, "no baseline", "not computable", "—")], "", id="2.6"
        ),
        pytest.param(
            "2.10",
            [("weighted average diluted shares", NONE_LISTED, "no baseline", "not computable", "—")],
            "",
            id="2.10",
        ),
        pytest.param(
            "2.11",
            [
                ("goodwill (USD)", NONE_LISTED, "no baseline", "not computable", "—"),
                ("goodwill ÷ stockholders' equity (%)", NONE_LISTED, "no baseline", "not computable", "—"),
            ],
            "",
            id="2.11",
        ),
        pytest.param(
            "8.5",
            [
                ("distinct analysts asking questions", NONE_LISTED, "no baseline", "1", "—"),
                ("analysts on one of the two calls only", NONE_LISTED, "no baseline", "no baseline", "—"),
            ],
            PREVIOUS_CALL,
            id="8.5",
        ),
        pytest.param(
            "8.6",
            [
                (
                    "mean words of an executive's turn after the first analyst's",
                    NONE_LISTED,
                    "no baseline",
                    "not computable",
                    "—",
                )
            ],
            PREVIOUS_CALL,
            id="8.6",
        ),
        pytest.param(
            "9.1",
            [
                (
                    LAG,
                    "previous four 10-Qs: none listed",
                    "no baseline",
                    "30",
                    "—",
                ),
                (
                    LATE,
                    "previous four seasons: none listed",
                    "no baseline",
                    "none",
                    "—",
                ),
                (
                    NOTICES,
                    "previous four seasons: none listed",
                    "no baseline",
                    "none",
                    "—",
                ),
            ],
            NEWEST_FIRST,
            id="9.1",
        ),
        pytest.param(
            "9.3",
            [
                ("call duration (seconds)", NONE_LISTED, "no baseline", "3,600", "—"),
                ("words from the first analyst's turn to the end", NONE_LISTED, "no baseline", "20", "—"),
            ],
            PREVIOUS_CALL,
            id="9.3",
        ),
        pytest.param(
            "9.4",
            [("8-Ks placed in the season", "previous four seasons: none listed", "no baseline", "0", "—")],
            NEWEST_FIRST,
            id="9.4",
        ),
        pytest.param(
            "9.5",
            [("the season's call", "previous four seasons: none listed", "no baseline", "transcript", "—")],
            NEWEST_FIRST,
            id="9.5",
        ),
    ],
)
def test_the_oldest_listed_season_has_no_baseline(identifier, rows, note):
    call = transcribed(PA, turn("Pat Lee", "executive", 300), turn("Analyst 1", "analyst", 20))
    raw = raw_state(YEARS, season_files(PA, call=call), facts=company_facts(figures(PA, revenue=1_000)))

    found = computed(raw, PA, identifier)

    assert (cells(found), found.note) == (rows, note)


# --------------------------------------------------------------------------- 2.1 growth


REVENUE_GROWTH = "revenue growth on the same quarter a year before (%)"
INCOME_GROWTH = "net income growth on the same quarter a year before (%)"


@pytest.mark.parametrize(
    ("revenue", "income", "rows"),
    [
        pytest.param(
            1_099_900,
            108_000,
            [
                (REVENUE_GROWTH, PREVIOUS, "20.00", "9.99", "-10.01 pp"),
                (INCOME_GROWTH, PREVIOUS, "20.00", "8.00", "-12.00 pp"),
            ],
            id="slower",
        ),
        pytest.param(
            1_200_000,
            120_000,
            [
                (REVENUE_GROWTH, PREVIOUS, "20.00", "20.00", "+0.00 pp"),
                (INCOME_GROWTH, PREVIOUS, "20.00", "20.00", "+0.00 pp"),
            ],
            id="unchanged",
        ),
        pytest.param(
            1_300_100,
            90_000,
            [
                (REVENUE_GROWTH, PREVIOUS, "20.00", "30.01", "+10.01 pp"),
                (INCOME_GROWTH, PREVIOUS, "20.00", "-10.00", "-30.00 pp"),
            ],
            id="faster-and-shrinking",
        ),
    ],
)
def test_growth_states_the_previous_quarters_and_the_seasons_year_over_year_growth(revenue, income, rows):
    facts = company_facts(
        figures(PA, revenue=1_000_000, income=100_000),
        figures(A, revenue=1_000_000, income=100_000),
        figures(P, revenue=1_200_000, income=120_000),
        figures(S, revenue=revenue, income=income),
    )

    found = computed(raw_state(YEARS, facts=facts), S, "2.1")

    assert (cells(found), found.note) == (rows, YEARS_NOTE)


def test_growth_is_not_computable_without_a_year_ago_figure_above_0():
    facts = company_facts(
        figures(PA, revenue=1_000_000),
        figures(A, revenue=0),
        figures(P, revenue=1_200_000),
        figures(S, revenue=1_100_000),
    )

    assert cells(computed(raw_state(YEARS, facts=facts), S, "2.1")) == [
        (REVENUE_GROWTH, PREVIOUS, "20.00", "not computable", "—"),
        (INCOME_GROWTH, PREVIOUS, "not computable", "not computable", "—"),
    ]


def test_growth_needs_the_year_ago_of_the_season_and_of_its_previous_quarter():
    rows = (PA, B, K, P, S)  # the same quarter last year is not listed

    found = computed(raw_state(rows, facts=company_facts()), S, "2.1")

    assert cells(found) == [
        (REVENUE_GROWTH, PREVIOUS, "not computable", "no baseline", "—"),
        (INCOME_GROWTH, PREVIOUS, "not computable", "no baseline", "—"),
    ]
    assert found.note == (
        "the year before this season: none listed; the year before the previous quarter: 2025-03-29 "
        "(10-Q); not computable where a figure is missing or the year-ago figure is 0 or below"
    )


# --------------------------------------------------------------------------- 2.2 margins


def test_each_margin_is_stated_against_the_same_quarter_last_year_and_the_previous_quarter():
    facts = company_facts(
        figures(A, revenue=1_000_000, gross=479_900, operating=100_000),
        figures(P, revenue=1_000_000, gross=500_000, operating=100_000),
        figures(S, revenue=1_000_000, gross=500_000, operating=120_000),
    )

    found = computed(raw_state(YEARS, facts=facts), S, "2.2")

    assert (cells(found), found.note) == (
        [
            ("gross margin (%)", YEAR_AGO, "47.99", "50.00", "+2.01 pp"),
            ("gross margin (%)", PREVIOUS, "50.00", "50.00", "+0.00 pp"),
            ("operating margin (%)", YEAR_AGO, "10.00", "12.00", "+2.00 pp"),
            ("operating margin (%)", PREVIOUS, "10.00", "12.00", "+2.00 pp"),
        ],
        "",
    )


def test_gross_margin_is_revenue_less_cost_where_no_gross_profit_is_reported():
    facts = company_facts(
        figures(P, revenue=1_000_000, cost=600_000),
        figures(S, revenue=1_000_000, cost=640_000),
    )

    # The same quarter last year reports nothing: its margins are not computable.
    assert cells(computed(raw_state(YEARS, facts=facts), S, "2.2")) == [
        ("gross margin (%)", YEAR_AGO, "not computable", "36.00", "—"),
        ("gross margin (%)", PREVIOUS, "40.00", "36.00", "-4.00 pp"),
        ("operating margin (%)", YEAR_AGO, "not computable", "not computable", "—"),
        ("operating margin (%)", PREVIOUS, "not computable", "not computable", "—"),
    ]


def test_margins_are_not_computable_without_the_seasons_revenue():
    facts = company_facts(figures(P, revenue=1_000_000, gross=500_000), figures(S, gross=500_000))

    assert [row[2:] for row in cells(computed(raw_state(YEARS, facts=facts), S, "2.2"))] == [
        ("not computable", "not computable", "—"),
        ("50.00", "not computable", "—"),
        ("not computable", "not computable", "—"),
        ("not computable", "not computable", "—"),
    ]


# --------------------------------------------------------------------------- 2.3 cash to net income


CASH_RATIO = "operating cash flow ÷ net income"


def test_cash_flow_to_net_income_is_stated_against_both_baselines():
    facts = company_facts(
        figures(S, cash_flow=69, income=100),
        figures(A, cash_flow=101, income=100),
        figures(P, cash_flow=120, income=100),
    )

    found = computed(raw_state(YEARS, facts=facts), S, "2.3")

    assert (cells(found), found.note) == (
        [(CASH_RATIO, YEAR_AGO, "1.01", "0.69", "-0.32"), (CASH_RATIO, PREVIOUS, "1.20", "0.69", "-0.51")],
        "",
    )


def test_a_ratio_is_rounded_half_even_once():
    facts = company_facts(
        figures(S, cash_flow=1_015, income=1_000),
        figures(A, cash_flow=1_005, income=1_000),
        figures(P, cash_flow=1_025, income=1_000),
    )

    # 1.015 and 1.025 round to the even 1.02; 1.005 to 1.00.
    assert cells(computed(raw_state(YEARS, facts=facts), S, "2.3")) == [
        (CASH_RATIO, YEAR_AGO, "1.00", "1.02", "+0.02"),
        (CASH_RATIO, PREVIOUS, "1.02", "1.02", "+0.00"),
    ]


def test_a_ratio_is_not_computable_where_net_income_is_0_or_below():
    facts = company_facts(
        figures(S, cash_flow=50, income=-10),
        figures(A, cash_flow=101, income=100),
        figures(P, cash_flow=120, income=0),
    )

    assert cells(computed(raw_state(YEARS, facts=facts), S, "2.3")) == [
        (CASH_RATIO, YEAR_AGO, "1.01", "not computable", "—"),
        (CASH_RATIO, PREVIOUS, "not computable", "not computable", "—"),
    ]


def test_cash_flow_to_net_income_has_no_baseline_where_the_same_quarter_last_year_is_not_listed():
    facts = company_facts(figures(S, cash_flow=90, income=100), figures(P, cash_flow=120, income=100))

    assert cells(computed(raw_state((PA, B, K, P, S), facts=facts), S, "2.3")) == [
        (CASH_RATIO, NOT_LISTED_YEAR, "no baseline", "0.90", "—"),
        (CASH_RATIO, PREVIOUS, "1.20", "0.90", "-0.30"),
    ]


# --------------------------------------------------------------------------- 2.4 days


def test_days_are_stated_against_the_same_quarter_last_year():
    # 91 days in both quarters: days are a tenth of a balance against a flow of 910.
    facts = company_facts(
        figures(A, revenue=910, cost=910, receivables=350, inventory=400, payables=300),
        figures(S, revenue=910, cost=455, receivables=501, inventory=400, payables=300),
    )

    found = computed(raw_state(YEARS, facts=facts), S, "2.4")

    # Inventory and payables count against cost of revenue, receivables against revenue.
    assert (cells(found), found.note) == (
        [
            ("days of sales outstanding", YEAR_AGO, "35.0", "50.1", "+15.1"),
            ("days of inventory", YEAR_AGO, "40.0", "80.0", "+40.0"),
            ("days of payables", YEAR_AGO, "30.0", "60.0", "+30.0"),
        ],
        "",
    )


def test_days_need_the_cost_of_revenue_and_the_length_of_each_quarter():
    facts = company_facts(
        figures(A, revenue=910, receivables=350, inventory=400, payables=300),
        figures(S, revenue=910, cost=910, receivables=364, inventory=400, payables=300),
    )

    assert cells(computed(raw_state(YEARS, facts=facts), S, "2.4")) == [
        ("days of sales outstanding", YEAR_AGO, "35.0", "36.4", "+1.4"),
        ("days of inventory", YEAR_AGO, "not computable", "40.0", "—"),
        ("days of payables", YEAR_AGO, "not computable", "30.0", "—"),
    ]
    # Without the season listed before the same quarter last year, that quarter has no length.
    assert [row[2:] for row in cells(computed(raw_state((A, B, K, P, S), facts=facts), S, "2.4"))] == [
        ("not computable", "36.4", "—"),
        ("not computable", "40.0", "—"),
        ("not computable", "30.0", "—"),
    ]


# --------------------------------------------------------------------------- 2.5 receivables


RECEIVABLES = "receivables at the period end (USD)"
REVENUE = "revenue of the quarter (USD)"


def test_receivables_and_revenue_are_stated_with_their_growth():
    facts = company_facts(
        figures(A, revenue=1_000_000, receivables=1_000_000),
        figures(S, revenue=1_100_000, receivables=1_300_100),
    )

    found = computed(raw_state(YEARS, facts=facts), S, "2.5")

    assert (cells(found), found.note) == (
        [
            (RECEIVABLES, YEAR_AGO, "1,000,000", "1,300,100", "+300,100 (+30.01%)"),
            (REVENUE, YEAR_AGO, "1,000,000", "1,100,000", "+100,000 (+10.00%)"),
        ],
        "",
    )


def test_an_amount_over_an_old_amount_of_0_has_no_percent_change():
    facts = company_facts(
        figures(A, revenue=1_000_000, receivables=0),
        figures(S, revenue=900_000, receivables=250_000),
    )

    assert cells(computed(raw_state(YEARS, facts=facts), S, "2.5")) == [
        (RECEIVABLES, YEAR_AGO, "0", "250,000", "+250,000"),
        (REVENUE, YEAR_AGO, "1,000,000", "900,000", "-100,000 (-10.00%)"),
    ]


def test_receivables_are_not_computable_without_the_figure():
    facts = company_facts(figures(A, revenue=1_000_000, receivables=1_000_000), figures(S, revenue=1_100_000))

    assert cells(computed(raw_state(YEARS, facts=facts), S, "2.5"))[0] == (
        RECEIVABLES,
        YEAR_AGO,
        "1,000,000",
        "not computable",
        "—",
    )


# --------------------------------------------------------------------------- 2.6 net debt


@pytest.mark.parametrize(
    ("previous", "current", "old", "new", "change"),
    [
        pytest.param(
            {"debt": 1_500_000, "cash": 500_000},
            {"debt": 1_750_100, "cash": 500_000},
            "1,000,000",
            "1,250,100",
            "+250,100 (+25.01%)",
            id="rising",
        ),
        pytest.param(
            {"debt": 1_500_000, "cash": 500_000},
            {"debt": 1_249_900, "cash": 500_000},
            "1,000,000",
            "749,900",
            "-250,100 (-25.01%)",
            id="falling",
        ),
        pytest.param(
            {"debt": 1_500_000, "cash": 500_000},
            {"debt": 400_000, "cash": 500_000},
            "1,000,000",
            "-100,000",
            "-1,100,000 (-110.00%)",
            id="sign-changed",
        ),
        pytest.param(
            {"debt": 500_000, "cash": 1_500_000},
            {"debt": 500_000, "cash": 1_800_000},
            "-1,000,000",
            "-1,300,000",
            "-300,000",
            id="net-cash",
        ),
        pytest.param(
            {"debt": 1_500_000},
            {"debt": 1_500_000, "cash": 500_000},
            "not computable",
            "1,000,000",
            "—",
            id="no-cash",
        ),
    ],
)
def test_net_debt_is_stated_against_the_previous_quarter(previous, current, old, new, change):
    facts = company_facts(figures(P, **previous), figures(S, **current))

    found = computed(raw_state(YEARS, facts=facts), S, "2.6")

    assert (cells(found), found.note) == ([("net debt (USD)", PREVIOUS, old, new, change)], "")


def test_debt_adds_its_current_part():
    facts = company_facts(
        figures(P, debt=1_000_000, debt_current=500_000, cash=500_000),
        figures(S, debt=1_000_000, debt_current=750_000, cash=500_000),
    )

    assert cells(computed(raw_state(YEARS, facts=facts), S, "2.6")) == [
        ("net debt (USD)", PREVIOUS, "1,000,000", "1,250,000", "+250,000 (+25.00%)")
    ]


# --------------------------------------------------------------------------- 2.10 and 2.11


SHARES = "weighted average diluted shares"
ANNUAL = "a 10-K reports the year's average, so a 10-K season has no quarter's value"


@pytest.mark.parametrize(
    ("shares", "change"),
    [
        pytest.param(1_020_100, "+20,100 (+2.01%)", id="more"),
        pytest.param(1_000_000, "+0 (+0.00%)", id="unchanged"),
        pytest.param(979_900, "-20,100 (-2.01%)", id="fewer"),
    ],
)
def test_diluted_shares_are_stated_against_the_previous_quarter(shares, change):
    facts = company_facts(figures(P, shares=1_000_000), figures(S, shares=shares))

    found = computed(raw_state(YEARS, facts=facts), S, "2.10")

    assert (cells(found), found.note) == ([(SHARES, PREVIOUS, "1,000,000", f"{shares:,}", change)], "")


def test_diluted_shares_are_not_computable_in_a_10_k_season_or_against_one():
    # A 10-K reports the year's average, no quarter of its own.
    facts = company_facts(figures(B, shares=1_000_000), figures(P, shares=1_000_000))
    raw = raw_state(YEARS, facts=facts)

    found = computed(raw, K, "2.10")
    assert (cells(found), found.note) == (
        [(SHARES, "previous quarter 2025-09-27 (10-Q)", "1,000,000", "not computable", "—")],
        ANNUAL,
    )
    found = computed(raw, P, "2.10")
    assert (cells(found), found.note) == (
        [(SHARES, "previous quarter 2025-12-27 (10-K)", "not computable", "1,000,000", "—")],
        ANNUAL,
    )


def test_a_10_k_tagging_a_quarters_diluted_shares_still_has_no_value():
    # The filing's own quarter entry is not read: a 10-K season's shares are the year's.
    facts = company_facts(
        figures(B, shares=1_000_000), figures(K, shares=1_050_000), figures(P, shares=1_100_000)
    )
    raw = raw_state(YEARS, facts=facts)

    assert cells(computed(raw, K, "2.10")) == [
        (SHARES, "previous quarter 2025-09-27 (10-Q)", "1,000,000", "not computable", "—")
    ]
    assert cells(computed(raw, P, "2.10")) == [
        (SHARES, "previous quarter 2025-12-27 (10-K)", "not computable", "1,100,000", "—")
    ]


GOODWILL = "goodwill (USD)"
GOODWILL_SHARE = "goodwill ÷ stockholders' equity (%)"


@pytest.mark.parametrize(
    ("goodwill", "new", "change", "share", "share_change"),
    [
        pytest.param(3_001_000, "3,001,000", "+1,001,000 (+50.05%)", "30.01", "+10.01 pp", id="added"),
        pytest.param(2_000_000, "2,000,000", "+0 (+0.00%)", "20.00", "+0.00 pp", id="unchanged"),
        pytest.param(1_000_000, "1,000,000", "-1,000,000 (-50.00%)", "10.00", "-10.00 pp", id="impaired"),
    ],
)
def test_goodwill_and_its_share_of_equity_are_stated_against_the_previous_quarter(
    goodwill, new, change, share, share_change
):
    facts = company_facts(
        figures(P, goodwill=2_000_000, equity=10_000_000), figures(S, goodwill=goodwill, equity=10_000_000)
    )

    found = computed(raw_state(YEARS, facts=facts), S, "2.11")

    assert (cells(found), found.note) == (
        [
            (GOODWILL, PREVIOUS, "2,000,000", new, change),
            (GOODWILL_SHARE, PREVIOUS, "20.00", share, share_change),
        ],
        "",
    )


def test_goodwills_share_is_not_computable_without_the_equity_of_the_season():
    facts = company_facts(figures(P, goodwill=2_000_000, equity=10_000_000), figures(S, goodwill=3_000_000))

    assert cells(computed(raw_state(YEARS, facts=facts), S, "2.11")) == [
        (GOODWILL, PREVIOUS, "2,000,000", "3,000,000", "+1,000,000 (+50.00%)"),
        (GOODWILL_SHARE, PREVIOUS, "20.00", "not computable", "—"),
    ]


# --------------------------------------------------------------------------- 5.7 officers selling


OFFICER = Owner("0001000001", "Roe Jane", False, True, False, "Chief Financial Officer")
OTHER_OFFICER = Owner("0001000002", "Poe Alex", False, True, False, "")
DIRECTOR = Owner("0001000003", "Moe Sam", True, False, False, "")
SELLERS = "officers reporting a sale (S) or a disposition to the issuer (D)"


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
    ("forms", "new", "note"),
    [
        pytest.param(
            (form4(OFFICER), form4(OFFICER)),
            "1: Roe Jane (Chief Financial Officer, 0001000001-26-000001, 0001000001-26-000002)",
            "2 Form 4s read, 0 of another issuer left out",
            id="one-officer",
        ),
        pytest.param(
            (form4(OFFICER), form4(OTHER_OFFICER, code="D")),
            "2: Roe Jane (Chief Financial Officer, 0001000001-26-000001); Poe Alex (officer, "
            "0001000001-26-000002)",
            "2 Form 4s read, 0 of another issuer left out",
            id="two-officers",
        ),
        pytest.param(
            (form4(DIRECTOR), form4(OFFICER, code="A"), form4(OTHER_OFFICER, code="G")),
            "0",
            "3 Form 4s read, 0 of another issuer left out",
            id="no-sale-by-an-officer",
        ),
        pytest.param(
            (form4(OFFICER), form4(OTHER_OFFICER, issuer="0001000099")),
            "1: Roe Jane (Chief Financial Officer, 0001000001-26-000001)",
            "2 Form 4s read, 1 of another issuer left out",
            id="another-issuer",
        ),
        pytest.param((), "0", "0 Form 4s read, 0 of another issuer left out", id="none"),
    ],
)
def test_the_officers_selling_are_named_in_the_new_value(forms, new, note):
    found = computed(insiders(*forms), S, "5.7")

    assert (cells(found), found.note) == ([(SELLERS, "none", "—", new, "—")], note)


# --------------------------------------------------------------------------- the call: 8.5, 8.6, 9.3


TEN = tuple(f"Analyst {number}" for number in range(1, 11))
ANALYSTS = "distinct analysts asking questions"
ONE_CALL_ONLY = "analysts on one of the two calls only"
ANSWERS = "mean words of an executive's turn after the first analyst's"
DURATION = "call duration (seconds)"
WORDS = "words from the first analyst's turn to the end"


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
    ("names", "counted", "named"),
    [
        pytest.param(
            TEN[:6],
            ("10", "6", "-4 (-40.00%)"),
            ("Analyst 7, Analyst 8, Analyst 9, Analyst 10", "none", "—"),
            id="fewer",
        ),
        pytest.param(TEN, ("10", "10", "+0 (+0.00%)"), ("none", "none", "—"), id="the-same"),
        pytest.param(
            (*TEN[2:], "Analyst 11"),
            ("10", "9", "-1 (-10.00%)"),
            ("Analyst 1, Analyst 2", "Analyst 11", "—"),
            id="gone-and-new",
        ),
    ],
)
def test_the_analysts_are_counted_and_those_on_one_call_only_named(names, counted, named):
    raw = calls(transcribed(P, *questions(*TEN)), transcribed(S, *questions(*names)))

    found = computed(raw, S, "8.5")

    assert (cells(found), found.note) == (
        [(ANALYSTS, PREVIOUS, *counted), (ONE_CALL_ONLY, PREVIOUS, *named)],
        "",
    )


def test_an_analyst_asking_twice_counts_once_however_the_transcript_spaces_the_name():
    raw = calls(
        transcribed(P, *questions("Analyst 1", "Analyst 2")),
        transcribed(S, *questions("Analyst 1", " Analyst  1", "Analyst 2")),
    )

    assert [row[2:] for row in cells(computed(raw, S, "8.5"))] == [
        ("2", "2", "+0 (+0.00%)"),
        ("none", "none", "—"),
    ]


def test_analysts_against_a_call_without_questions_have_no_percent_change():
    raw = calls(transcribed(P, turn("Pat Lee", "executive", 300)), transcribed(S, *questions("Analyst 1")))

    assert [row[2:] for row in cells(computed(raw, S, "8.5"))] == [
        ("0", "1", "+1"),
        ("none", "Analyst 1", "—"),
    ]


@pytest.mark.parametrize(
    ("words", "new", "change"),
    [
        pytest.param((70,), "70.0", "-30.0 (-30.00%)", id="shorter"),
        pytest.param((69, 70), "69.5", "-30.5 (-30.50%)", id="a-mean"),
        pytest.param((130,), "130.0", "+30.0 (+30.00%)", id="longer"),
    ],
)
def test_the_mean_answer_is_stated_against_the_previous_calls(words, new, change):
    # The prepared remarks before the first question and the operator's lines are no answers.
    raw = calls(transcribed(P, *answers(100, 100)), transcribed(S, *answers(*words)))

    found = computed(raw, S, "8.6")

    assert (cells(found), found.note) == ([(ANSWERS, PREVIOUS, "100.0", new, change)], "")


def test_answers_are_not_computable_in_a_call_without_questions():
    raw = calls(transcribed(P, *answers(100)), transcribed(S, turn("Pat Lee", "executive", 1000)))

    assert cells(computed(raw, S, "8.6")) == [(ANSWERS, PREVIOUS, "100.0", "not computable", "—")]


def questions_and_answers(words: int) -> tuple[TranscriptTurn, ...]:
    """Prepared remarks of 500 words, then ``words`` words from the first analyst's question on."""
    return (
        turn("Pat Lee", "executive", 500),
        turn("Analyst 1", "analyst", 100),
        turn("Pat Lee", "executive", words - 100),
    )


@pytest.mark.parametrize(
    ("duration", "words", "rows"),
    [
        pytest.param(
            2519,
            699,
            [
                (DURATION, PREVIOUS, "3,600", "2,519", "-1,081 (-30.03%)"),
                (WORDS, PREVIOUS, "1,000", "699", "-301 (-30.10%)"),
            ],
            id="shorter",
        ),
        pytest.param(
            3600,
            1200,
            [
                (DURATION, PREVIOUS, "3,600", "3,600", "+0 (+0.00%)"),
                (WORDS, PREVIOUS, "1,000", "1,200", "+200 (+20.00%)"),
            ],
            id="longer-answers",
        ),
        pytest.param(
            None,
            699,
            [
                (DURATION, PREVIOUS, "3,600", "not computable", "—"),
                (WORDS, PREVIOUS, "1,000", "699", "-301 (-30.10%)"),
            ],
            id="no-duration",
        ),
    ],
)
def test_the_calls_length_is_stated_against_the_previous_calls(duration, words, rows):
    raw = calls(
        transcribed(P, *questions_and_answers(1000), duration=3600),
        transcribed(S, *questions_and_answers(words), duration=duration),
    )

    found = computed(raw, S, "9.3")

    assert (cells(found), found.note) == (rows, "")


def test_the_calls_length_is_not_computable_without_a_duration_or_a_question():
    raw = calls(
        transcribed(P, *questions_and_answers(1000), duration=None),
        transcribed(S, turn("Pat Lee", "executive", 1000), duration=3000),
    )

    assert cells(computed(raw, S, "9.3")) == [
        (DURATION, PREVIOUS, "not computable", "3,000", "—"),
        (WORDS, PREVIOUS, "1,000", "not computable", "—"),
    ]


@pytest.mark.parametrize(
    ("identifier", "compared"),
    [("8.5", (ANALYSTS, ONE_CALL_ONLY)), ("8.6", (ANSWERS,)), ("9.3", (DURATION, WORDS))],
)
@pytest.mark.parametrize("status", ["unavailable", "waiting", "missing"])
def test_a_call_item_is_unavailable_while_the_call_of_the_season_has_no_transcript(
    identifier, compared, status
):
    raw = calls(transcribed(P, *questions(*TEN)), no_call(S, status))

    found = computed(raw, S, identifier)

    assert (cells(found), found.note) == (
        [(label, PREVIOUS, "unavailable", "unavailable", "—") for label in compared],
        f"the call has no transcript in raw/ ({status})",
    )


@pytest.mark.parametrize(
    ("identifier", "rows"),
    [
        pytest.param(
            "8.5",
            [
                (ANALYSTS, PREVIOUS, "no baseline", "10", "—"),
                (ONE_CALL_ONLY, PREVIOUS, "no baseline", "no baseline", "—"),
            ],
            id="8.5",
        ),
        pytest.param("8.6", [(ANSWERS, PREVIOUS, "no baseline", "100.0", "—")], id="8.6"),
        pytest.param(
            "9.3",
            [
                (DURATION, PREVIOUS, "no baseline", "3,600", "—"),
                (WORDS, PREVIOUS, "no baseline", "1,200", "—"),
            ],
            id="9.3",
        ),
    ],
)
def test_a_call_item_has_no_baseline_while_the_previous_call_has_no_transcript(identifier, rows):
    raw = calls(no_call(P), transcribed(S, *questions(*TEN)))

    found = computed(raw, S, identifier)

    assert (cells(found), found.note) == (rows, PREVIOUS_CALL)


# --------------------------------------------------------------------------- 9.1 timing


RELEASE = "0000050863-26-000062"


def timed(lag: int = 30, *filings: Dated, previous: Season = P) -> tuple[RawState, Season]:
    """``raw/`` whose season S, filed ``lag`` days after its period end, holds ``filings``; P is
    ``previous``. The previous four 10-Qs were filed 27, 30, 27 and 30 days after their period
    ends, newest first."""
    row = season("10-Q", S.period, lag, S.filing.accession, *filings)
    return raw_state((PA, A, B, K, previous, row)), row


def timing(
    lag: int = 30,
    releases: str = "none",
    before: str = "none",
    notices: str = "none",
    earlier_notices: str = "none",
) -> list[tuple[str, str, str, str, str]]:
    return [
        (LAG, TEN_QS, "27, 30, 27, 30", str(lag), "—"),
        (LATE, RECORD, before, releases, "—"),
        (NOTICES, RECORD, earlier_notices, notices, "—"),
    ]


@pytest.mark.parametrize("lag", [29, 30, 31, 90])
def test_the_days_to_the_filing_are_stated_against_each_of_the_previous_four_of_its_form(lag):
    raw, row = timed(lag)

    found = computed(raw, row, "9.1")

    assert (cells(found), found.note) == (timing(lag), NEWEST_FIRST)


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
def test_a_release_accepted_after_16_00_before_a_day_without_a_session_is_named(accepted, late):
    day = date(2026, 7, 2) if accepted is None else accepted.date()
    raw, row = timed(30, release(RELEASE, day, accepted))

    shown = f"{RELEASE} ({accepted:%Y-%m-%d %H:%M:%S} EDT)" if late else "none"
    assert cells(computed(raw, row, "9.1")) == timing(releases=shown)


def test_a_release_accepted_at_16_00_exactly_is_not_after_16_00():
    raw, row = timed(30, release(RELEASE, date(2026, 7, 24), edt(2026, 7, 24, 16, 0, 0)))

    assert cells(computed(raw, row, "9.1")) == timing()


def test_a_late_release_of_the_previous_four_seasons_is_the_old_value():
    previous = season(
        "10-Q",
        P.period,
        27,
        P.filing.accession,
        release("0000050863-26-000040", date(2026, 4, 24), edt(2026, 4, 24, 16, 30)),
    )
    raw, row = timed(30, release(RELEASE, date(2026, 7, 24), edt(2026, 7, 24, 16, 30)), previous=previous)

    assert cells(computed(raw, row, "9.1")) == timing(
        releases=f"{RELEASE} (2026-07-24 16:30:00 EDT)",
        before="0000050863-26-000040 (2026-04-24 16:30:00 EDT)",
    )


def test_late_filing_notices_of_the_season_and_of_the_previous_four():
    notice = dated("NT 10-Q", "0000050863-26-000063", date(2026, 7, 27), primary="nt10q.htm")
    raw, row = timed(30, notice)
    assert cells(computed(raw, row, "9.1")) == timing(notices="NT 10-Q 0000050863-26-000063")

    earlier = dated("NT 10-Q", "0000050863-26-000039", date(2026, 4, 27), primary="nt10q.htm")
    previous = season("10-Q", P.period, 27, P.filing.accession, earlier)
    raw, row = timed(30, previous=previous)
    assert cells(computed(raw, row, "9.1")) == timing(earlier_notices="NT 10-Q 0000050863-26-000039")

    # Even in the oldest listed season, with nothing to compare with.
    oldest = season("10-Q", S.period, 30, S.filing.accession, notice)
    assert cells(computed(raw_state((oldest,)), oldest, "9.1")) == [
        (LAG, "previous four 10-Qs: none listed", "no baseline", "30", "—"),
        (LATE, "previous four seasons: none listed", "no baseline", "none", "—"),
        (NOTICES, "previous four seasons: none listed", "no baseline", "NT 10-Q 0000050863-26-000063", "—"),
    ]


def test_a_10_k_is_timed_against_the_previous_10_ks_alone():
    record = "previous four seasons: 2025-09-27, 2025-06-28, 2025-03-29"

    assert cells(computed(raw_state(YEARS), K, "9.1")) == [
        (
            "days from the period end to the 10-K's filing",
            "previous four 10-Ks: none listed",
            "no baseline",
            "34",
            "—",
        ),
        (LATE, record, "none", "none", "—"),
        (NOTICES, record, "none", "none", "—"),
    ]


# --------------------------------------------------------------------------- 9.4 8-K count


def with_eight_ks(row: Season, count: int, *amendments: int) -> Season:
    """``row`` holding ``count`` 8-Ks of Item 8.01, then 8-K/As."""
    day = row.period + timedelta(days=10)
    reports = tuple(
        dated("8-K", f"0000050863-26-{number:06d}", day, "8.01") for number in range(1, count + 1)
    )
    amended = tuple(dated("8-K/A", f"0000050863-26-{number:06d}", day) for number in amendments)
    return replace(row, filings=reports + amended)


@pytest.mark.parametrize("count", [0, 1, 4])
def test_the_8_ks_of_the_season_are_stated_against_each_of_the_previous_four_seasons(count):
    # The oldest season's five 8-Ks lie beyond the previous four seasons; 8-K/As count for none.
    rows = (
        with_eight_ks(PA, 5),
        with_eight_ks(A, 2),
        with_eight_ks(B, 1, 900),
        with_eight_ks(K, 2),
        with_eight_ks(P, 1),
        with_eight_ks(S, count, 901, 902),
    )

    found = computed(raw_state(rows), rows[-1], "9.4")

    assert (cells(found), found.note) == (
        [("8-Ks placed in the season", RECORD, "1, 2, 1, 2", str(count), "—")],
        NEWEST_FIRST,
    )


# --------------------------------------------------------------------------- 9.5 call cancelled


def with_calls(current: CallState, *previous: Season) -> RawState:
    """``raw/`` where S's call is ``current`` and each season of ``previous`` had a call transcribed;
    every other season's call is unavailable."""
    held = [season_files(row, call=transcribed(row, *questions("Analyst 1"))) for row in previous]
    return raw_state(YEARS, *held, season_files(S, call=current))


@pytest.mark.parametrize(
    ("current", "previous", "old", "new"),
    [
        pytest.param(
            no_call(S),
            (A, B, K, P),
            "transcript, transcript, transcript, transcript",
            "unavailable",
            id="cancelled",
        ),
        pytest.param(
            no_call(S),
            (A, B, P),
            "transcript, unavailable, transcript, transcript",
            "unavailable",
            id="one-season-without-a-call",
        ),
        pytest.param(
            transcribed(S, *questions("Analyst 1")),
            (A, B, K, P),
            "transcript, transcript, transcript, transcript",
            "transcript",
            id="transcript",
        ),
        pytest.param(
            no_call(S, "waiting"),
            (A, B, K, P),
            "transcript, transcript, transcript, transcript",
            "waiting",
            id="waiting",
        ),
        pytest.param(
            no_call(S, "missing", CallEvent(248001, CALL_AT)),
            (A, B, K, P),
            "transcript, transcript, transcript, transcript",
            "missing",
            id="missing",
        ),
    ],
)
def test_the_seasons_call_is_stated_against_each_of_the_previous_four_seasons(current, previous, old, new):
    found = computed(with_calls(current, *previous), S, "9.5")

    assert (cells(found), found.note) == ([("the season's call", RECORD, old, new, "—")], NEWEST_FIRST)


def test_a_call_listed_without_its_transcript_is_missing_and_a_season_not_in_raw_is_named():
    missing = no_call(K, "missing", CallEvent(35174, edt(2026, 1, 29, 17, 0)))
    raw = raw_state(
        YEARS,
        *(season_files(row, call=transcribed(row, *questions("Analyst 1"))) for row in (A, B, P)),
        season_files(K, call=missing),
        season_files(S, call=no_call(S)),
    )
    assert cells(computed(raw, S, "9.5"))[0][2] == "transcript, missing, transcript, transcript"

    without_b = replace(raw, seasons=tuple(files for files in raw.seasons if files.day != B.period))
    assert cells(computed(without_b, S, "9.5"))[0][2] == "transcript, missing, not in raw/, transcript"


def test_fewer_than_four_seasons_before_are_all_stated():
    raw = raw_state(
        YEARS, *(season_files(row, call=transcribed(row, *questions("Analyst 1"))) for row in (PA, A))
    )

    assert cells(computed(raw, B, "9.5")) == [
        (
            "the season's call",
            "previous four seasons: 2025-06-28, 2025-03-29",
            "transcript, transcript",
            "unavailable",
            "—",
        )
    ]


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

rule: {RULE["2.1"]}

| Compared | Baseline | Old | New | Change |
| --- | --- | --- | --- | --- |
| revenue growth on the same quarter a year before (%) | previous quarter 2025-12-27 (10-K) | no baseline | no baseline | — |
| net income growth on the same quarter a year before (%) | previous quarter 2025-12-27 (10-K) | no baseline | no baseline | — |

note: the year before this season: none listed; the year before the previous quarter: none listed; not computable where a figure is missing or the year-ago figure is 0 or below

### 2.2 Gross and operating margins

rule: {RULE["2.2"]}

| Compared | Baseline | Old | New | Change |
| --- | --- | --- | --- | --- |
| gross margin (%) | same quarter last year none listed | no baseline | 40.00 | — |
| gross margin (%) | previous quarter 2025-12-27 (10-K) | 36.00 | 40.00 | +4.00 pp |
| operating margin (%) | same quarter last year none listed | no baseline | 5.00 | — |
| operating margin (%) | previous quarter 2025-12-27 (10-K) | 4.00 | 5.00 | +1.00 pp |

### 2.3 Operating cash flow to net income

rule: {RULE["2.3"]}

| Compared | Baseline | Old | New | Change |
| --- | --- | --- | --- | --- |
| operating cash flow ÷ net income | same quarter last year none listed | no baseline | 2.00 | — |
| operating cash flow ÷ net income | previous quarter 2025-12-27 (10-K) | not computable | 2.00 | — |

### 2.4 Days of receivables, inventory and payables

rule: {RULE["2.4"]}

| Compared | Baseline | Old | New | Change |
| --- | --- | --- | --- | --- |
| days of sales outstanding | same quarter last year none listed | no baseline | 27.3 | — |
| days of inventory | same quarter last year none listed | no baseline | 136.5 | — |
| days of payables | same quarter last year none listed | no baseline | 109.2 | — |

### 2.5 Receivables growth against revenue growth

rule: {RULE["2.5"]}

| Compared | Baseline | Old | New | Change |
| --- | --- | --- | --- | --- |
| receivables at the period end (USD) | same quarter last year none listed | no baseline | 3,810,000,000 | — |
| revenue of the quarter (USD) | same quarter last year none listed | no baseline | 12,700,000,000 | — |

### 2.6 Net debt

rule: {RULE["2.6"]}

| Compared | Baseline | Old | New | Change |
| --- | --- | --- | --- | --- |
| net debt (USD) | previous quarter 2025-12-27 (10-K) | 32,000,000,000 | 35,000,000,000 | +3,000,000,000 (+9.38%) |

### 2.10 Weighted diluted shares

rule: {RULE["2.10"]}

| Compared | Baseline | Old | New | Change |
| --- | --- | --- | --- | --- |
| weighted average diluted shares | previous quarter 2025-12-27 (10-K) | not computable | 4,400,000,000 | — |

note: a 10-K reports the year's average, so a 10-K season has no quarter's value

### 2.11 Goodwill added

rule: {RULE["2.11"]}

| Compared | Baseline | Old | New | Change |
| --- | --- | --- | --- | --- |
| goodwill (USD) | previous quarter 2025-12-27 (10-K) | 23,000,000,000 | 24,000,000,000 | +1,000,000,000 (+4.35%) |
| goodwill ÷ stockholders' equity (%) | previous quarter 2025-12-27 (10-K) | 23.47 | 24.00 | +0.53 pp |

### 5.7 Officers selling

rule: {RULE["5.7"]}

| Compared | Baseline | Old | New | Change |
| --- | --- | --- | --- | --- |
| officers reporting a sale (S) or a disposition to the issuer (D) | none | — | 1: Roe Jane (Chief Financial Officer, 0001234567-26-000001) | — |

note: 1 Form 4 read, 0 of another issuer left out

### 8.5 Analysts on the call

rule: {RULE["8.5"]}

| Compared | Baseline | Old | New | Change |
| --- | --- | --- | --- | --- |
| distinct analysts asking questions | previous quarter 2025-12-27 (10-K) | no baseline | 1 | — |
| analysts on one of the two calls only | previous quarter 2025-12-27 (10-K) | no baseline | no baseline | — |

note: the previous season's call has no transcript in raw/

### 8.6 Shorter answers

rule: {RULE["8.6"]}

| Compared | Baseline | Old | New | Change |
| --- | --- | --- | --- | --- |
| mean words of an executive's turn after the first analyst's | previous quarter 2025-12-27 (10-K) | no baseline | 100.0 | — |

note: the previous season's call has no transcript in raw/

### 9.1 Filing timing

rule: {RULE["9.1"]}

| Compared | Baseline | Old | New | Change |
| --- | --- | --- | --- | --- |
| days from the period end to the 10-Q's filing | previous four 10-Qs: none listed | no baseline | 27 | — |
| earnings releases accepted after 16:00 on a day whose next XNYS session is not the next day | previous four seasons: 2025-12-27 | none | none | — |
| late-filing notices (NT 10-K, NT 10-Q) | previous four seasons: 2025-12-27 | none | none | — |

note: the old values are newest first

### 9.3 Questions and answers compressed

rule: {RULE["9.3"]}

| Compared | Baseline | Old | New | Change |
| --- | --- | --- | --- | --- |
| call duration (seconds) | previous quarter 2025-12-27 (10-K) | no baseline | 3,600 | — |
| words from the first analyst's turn to the end | previous quarter 2025-12-27 (10-K) | no baseline | 120 | — |

note: the previous season's call has no transcript in raw/

### 9.4 8-K count

rule: {RULE["9.4"]}

| Compared | Baseline | Old | New | Change |
| --- | --- | --- | --- | --- |
| 8-Ks placed in the season | previous four seasons: 2025-12-27 | 0 | 2 | — |

note: the old values are newest first

### 9.5 Call cancelled

rule: {RULE["9.5"]}

| Compared | Baseline | Old | New | Change |
| --- | --- | --- | --- | --- |
| the season's call | previous four seasons: 2025-12-27 | unavailable | transcript | — |

note: the old values are newest first

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
    measures = measured(golden_raw(), GQ)

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
    # Without company facts, each financial item says so in its note.
    assert "note: no company facts are in raw/" in lines
    assert (
        "| net debt (USD) | previous quarter 2025-12-27 (10-K) | not computable | not computable | — |"
        in lines
    )


def test_a_cell_holding_a_pipe_is_escaped_in_its_table():
    previous = transcribed(P, *questions("Lee | Partners", "Analyst 1"))
    raw = calls(previous, transcribed(S, *questions("Analyst 1")))

    lines = measured(raw, S).text.splitlines()

    assert (
        "| analysts on one of the two calls only | previous quarter 2026-03-28 (10-Q) | Lee \\| Partners "
        "| none | — |" in lines
    )


@pytest.mark.parametrize(
    ("raw", "row"),
    [
        pytest.param(golden_raw(), GQ, id="golden-quarter"),
        pytest.param(golden_raw(), GK, id="golden-year"),
        pytest.param(raw_state(YEARS), S, id="no-facts"),
        pytest.param(insiders(form4(OFFICER), form4(OTHER_OFFICER, code="D")), S, id="officers"),
        pytest.param(calls(transcribed(P, *questions(*TEN)), no_call(S)), S, id="calls"),
    ],
)
def test_the_text_measures_writes_passes_the_wording_rule(raw, row):
    text = measured(raw, row).text

    assert WORDING.search(text) is None


def test_the_python_items_rules_and_titles_pass_the_wording_rule():
    for item in PYTHON_ITEMS:
        assert WORDING.search(item.title) is None, item.id
        assert WORDING.search(item.rule) is None, item.id
    assert BY_ID["5.7"].heading == "5.7 Officers selling"
