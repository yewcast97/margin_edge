"""script/report.py: a season's report, its file names, its freshness and the ranking ``show`` prints.

The report is rendered from dataclasses built here, as ``workflow`` hands them over: the listed
seasons (``filings.Seasons``), the season's files (``documents.SeasonFiles``), its Python items
(``measures.Measures``) and the bot's parsed readings (``readings.Readings``). ``season`` gives
every item a level: three red, two yellow, two grey, the statuses an annual item and a proxy
item take in a 10-Q season without a proxy statement, and two items without a source. The
expected text is written out by hand; its rule lines are the catalogue's (``items.BY_ID``).
File names are tried under ``tmp_path``.
"""

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from market_state_research.fundamentals.script.documents import CallState, SeasonFiles
from market_state_research.fundamentals.script.earningscalls import CallEvent
from market_state_research.fundamentals.script.filings import Dated, Filing, Season, Seasons
from market_state_research.fundamentals.script.items import BOT_ITEMS, BY_ID, ITEMS, PYTHON_ITEMS, Item
from market_state_research.fundamentals.script.measures import Measures, Reading
from market_state_research.fundamentals.script.readings import WORDING, ItemReading, Quote, Readings
from market_state_research.fundamentals.script.report import (
    NONE_TRIGGERED,
    Entry,
    entries,
    newest_report,
    ranking,
    render_report,
    report_name,
    same_report,
    score_line,
    season_score,
)

from .support import NOW, edt, est

TICKER = "INTC"
CIK = "0000050863"
ENTITY = "INTEL CORP"
ROOT = Path("data/raw/INTC")  # never read: the report reads no file

PROXY = Dated("DEF 14A", "0001193125-26-112233", date(2026, 3, 20), date(2026, 3, 20), "", "def14a.htm")
A = Season(
    Filing("10-Q", "0000050863-25-000020", date(2025, 7, 25), date(2025, 6, 28), "intc-20250628.htm"), ()
)
K = Season(
    Filing("10-K", "0000050863-26-000012", date(2026, 1, 30), date(2025, 12, 27), "intc-20251227.htm"),
    (PROXY,),
)
P = Season(
    Filing("10-Q", "0000050863-26-000041", date(2026, 4, 24), date(2026, 3, 28), "intc-20260328.htm"), ()
)
S = Season(
    Filing("10-Q", "0000050863-26-000064", date(2026, 7, 24), date(2026, 6, 27), "intc-20260627.htm"), ()
)
LISTING = Seasons((A, K, P, S), (), (), date(2025, 7, 25))
TRANSCRIPT = CallState(
    "transcript",
    (CallEvent(248001, edt(2026, 7, 23, 17, 0)),),
    (),
    (),
    date(2026, 7, 23),
    date(2026, 8, 1),
    None,
)

TEN_Q_AGO = "10-Q_2025-06-28_0000050863-25-000020_intc-20250628"
TEN_K = "10-K_2025-12-27_0000050863-26-000012_intc-20251227"
TEN_Q_1 = "10-Q_2026-03-28_0000050863-26-000041_intc-20260328"
TEN_Q_2 = "10-Q_2026-06-27_0000050863-26-000064_intc-20260627"
RELEASE_1 = "8-K_2026-04-23_0000050863-26-000040_q126earningsrelease"
RELEASE_2 = "8-K_2026-07-23_0000050863-26-000062_q226earningsrelease"
CALL = "call_2026-06-27_248001"
GROWTH = (
    "same quarter last year 2025-06-28 (10-Q); previous quarter 2026-03-28 (10-Q) and its year-ago "
    "2025-03-29 (10-Q)"
)
TIMING = (
    "previous four 10-Qs: 2026-03-28, 2025-06-28; previous four seasons: 2026-03-28, 2025-12-27, 2025-06-28"
)
LATE = (
    "filed 31 days after the period end; the previous four at most 30; releases accepted after 16:00 "
    "before a day without a session: none; in the previous four seasons: none; late-filing notices: none"
)
SHARES = "weighted diluted shares 4,500,000,000 shares against 4,400,000,000 shares (+2.27%)"
NET_DEBT = "net debt 1,000,000 USD against —; previous quarter's equity 10,000,000 USD"
SEGMENTS = "Segment shares moved: Client 55% | Data Center 30% against 50% | 32%."
RULE = {item.id: item.rule for item in ITEMS}


def files(call: CallState = TRANSCRIPT, row: Season = S) -> SeasonFiles:
    """The files of the season ``row``, its documents left out: the report names none of them."""
    folder = ROOT / str(row.period)
    return SeasonFiles(row, folder, folder / "filing.htm", None, (), call, frozenset())


def key(item: Item) -> str:
    return "i" + item.id.replace(".", "_")


def python_readings(**changed: tuple[str, str, str]) -> Measures:
    """The Python items, each at ``none`` against a stand-in baseline, but those ``changed`` gives
    as (baseline, values, level), keyed ``i2_1`` for item 2.1."""
    found = tuple(
        Reading(item, *changed.get(key(item), (f"baseline of {item.id}", f"values of {item.id}", "none")))
        for item in PYTHON_ITEMS
    )
    return Measures(files(), found, (), "")


def bot(
    identifier: str,
    level: str,
    baseline: tuple[str, ...] = (),
    observation: str = "No change from the baseline.",
    *quotes: tuple[str, str] | tuple[str, str, str],
) -> ItemReading:
    """The bot's reading of an item; a quote is (text, DOC_ID) or (text, DOC_ID, speaker heading)."""
    read = tuple(Quote(0, quote[0], quote[1], quote[2] if len(quote) > 2 else None, 0) for quote in quotes)
    return ItemReading(BY_ID[identifier], 0, baseline, 0, level, 0, observation, 0, read)


def bot_readings(*changed: ItemReading) -> Readings:
    """Every bot item at ``none`` without a baseline, but the readings ``changed`` gives."""
    given = {reading.item.id: reading for reading in changed}
    return Readings(1, tuple(given.get(item.id, bot(item.id, "none")) for item in BOT_ITEMS))


ANNUAL = "The item does not apply to this season."


def season() -> tuple[Measures, Readings]:
    """The season of 2026-06-27: three items red, two yellow, two grey, and statuses."""
    measures = python_readings(
        i2_1=(GROWTH, "revenue: growth 8.00% against 20.00% a quarter earlier (-12.00 pp)", "yellow"),
        i2_6=("previous quarter 2026-03-28 (10-Q)", NET_DEBT, "not computable"),
        i2_10=("previous quarter 2026-03-28 (10-Q)", SHARES, "grey"),
        i9_1=(TIMING, LATE, "red"),
    )
    readings = bot_readings(
        bot(
            "1.1",
            "red",
            (RELEASE_1,),
            "The full-year revenue guidance midpoint went from 64.0 to 61.0 billion dollars.",
            ("We now expect full-year revenue of $60.0 billion to $62.0 billion.", RELEASE_2),
        ),
        bot("1.6", "not disclosed", (), "The season's documents give no capital expenditure guidance."),
        bot("1.9", "no baseline", (), "No earlier season's readings are in reports/."),
        bot("2.7", "grey", (TEN_Q_AGO,), SEGMENTS),
        bot("2.9", "not computable", (), "Net income is 0 or below."),
        bot("3.2", "not applicable", (), ANNUAL),
        bot(
            "3.6",
            "yellow",
            (TEN_Q_1,),
            "The filing states the adoption of a new standard on segment reporting.",
        ),
        bot("3.8", "not applicable", (), ANNUAL),
        bot("3.9", "not applicable", (), ANNUAL),
        bot("3.11", "not applicable", (), ANNUAL),
        bot(
            "4.2",
            "red",
            (TEN_Q_1, TEN_K),
            "A risk factor now states a substrate shortage as a fact.",
            ("We have experienced shortages of substrates this quarter.", CALL, "Jane Roe (executive)"),
            ("Supply of substrates was constrained throughout the quarter.", TEN_Q_2),
        ),
        bot("4.5", "not disclosed", (), "The filing quantifies no contingent liability."),
        bot("4.8", "not applicable", (), ANNUAL),
        bot("5.5", "not applicable", (), ANNUAL),
        bot("5.6", "not applicable", (), ANNUAL),
    )
    return measures, readings


def rendered(
    measures: Measures | None = None,
    readings: Readings | None = None,
    *,
    listing: Seasons = LISTING,
    call: CallState = TRANSCRIPT,
    generated_at: datetime = NOW,
) -> str:
    """The report of the season of 2026-06-27 (``season`` unless given)."""
    if measures is None or readings is None:
        measures, readings = season()
    return render_report(TICKER, CIK, ENTITY, listing, files(call), measures, readings, generated_at)


def level_entries(**levels: str) -> list[Entry]:
    """Every item of the catalogue at ``none`` (``no source`` for the items without one), but the
    levels given, keyed ``i1_1`` for item 1.1."""
    found = []
    for item in ITEMS:
        who = {"python": "Python", "bot": "bot", "none": "no source"}[item.who]
        level = "no source" if item.who == "none" else levels.get(key(item), "none")
        found.append(Entry(item, level, who, "none", ""))
    return found


# --------------------------------------------------------------------------- entries and the score


def test_entries_are_every_item_in_catalogue_order():
    measures, readings = season()

    found = entries(measures, readings)

    assert [entry.item for entry in found] == list(ITEMS)
    assert found[0] == Entry(
        BY_ID["1.1"],
        "red",
        "bot",
        RELEASE_1,
        "The full-year revenue guidance midpoint went from 64.0 to 61.0 billion dollars.",
        (("We now expect full-year revenue of $60.0 billion to $62.0 billion.", RELEASE_2),),
    )
    assert found[2] == Entry(
        BY_ID["1.3"], "no source", "no source", "none", "No source: the domain reads no consensus."
    )
    by_id = {entry.item.id: entry for entry in found}
    assert by_id["1.2"] == Entry(BY_ID["1.2"], "none", "bot", "none", "No change from the baseline.")
    assert by_id["2.1"] == Entry(
        BY_ID["2.1"],
        "yellow",
        "Python",
        GROWTH,
        "revenue: growth 8.00% against 20.00% a quarter earlier (-12.00 pp)",
    )
    assert by_id["4.2"].baseline == f"{TEN_Q_1}; {TEN_K}"
    assert by_id["4.2"].quotes == (
        ("We have experienced shortages of substrates this quarter.", f"{CALL}, Jane Roe (executive)"),
        ("Supply of substrates was constrained throughout the quarter.", TEN_Q_2),
    )
    assert season_score(found) == 38


def test_the_score_line_counts_levels_hands_and_statuses():
    found = level_entries(
        i1_1="red",
        i2_1="yellow",
        i2_2="yellow",
        i2_10="grey",
        i3_2="not applicable",
        i5_5="not applicable",
        i1_6="not disclosed",
        i2_6="not computable",
        i2_9="not computable",
        i2_4="no baseline",
        i7_1="unavailable",
        i8_5="unavailable",
    )

    assert score_line(found) == (
        "Score: 17 (1 red, 2 yellow, 1 grey) over 69 items: 16 read by Python, 51 by the bot, 2 without a "
        "source; 2 not applicable, 1 not disclosed, 2 not computable, 1 no baseline, 2 unavailable."
    )
    assert season_score(found) == 17


def test_a_season_without_a_triggered_item_scores_0():
    found = level_entries()

    assert score_line(found) == (
        "Score: 0 (0 red, 0 yellow, 0 grey) over 69 items: 16 read by Python, 51 by the bot, 2 without a "
        "source; 0 not applicable, 0 not disclosed, 0 not computable, 0 no baseline, 0 unavailable."
    )


# --------------------------------------------------------------------------- the report


@pytest.mark.parametrize(
    ("call", "generated_at", "generated", "call_line"),
    [
        pytest.param(
            TRANSCRIPT,
            NOW,
            "2026-10-08 06:00:00 EDT",
            "Call: transcript as of the calls list of 2026-08-01.",
            id="transcript",
        ),
        pytest.param(
            CallState("missing", (), (), (), date(2026, 7, 23), None, "no calls list"),
            datetime(2026, 11, 2, 11, 0, tzinfo=UTC),
            "2026-11-02 06:00:00 EST",
            "Call: missing.",
            id="missing",
        ),
    ],
)
def test_the_report_opens_with_the_issuer_the_season_its_baselines_and_the_score(
    call, generated_at, generated, call_line
):
    text = rendered(call=call, generated_at=generated_at)

    assert text.splitlines()[:12] == [
        "# INTC · 2026-06-27 · season report",
        "",
        f"Generated {generated}.",
        "",
        "Issuer: INTEL CORP (CIK 0000050863). Season: the 10-Q for the period ended 2026-06-27 (accession "
        f"0000050863-26-000064, filed 2026-07-24). {call_line}",
        "Baselines: previous quarter 2026-03-28; same quarter last year 2025-06-28; "
        "previous 10-K 2025-12-27; previous proxy 2025-12-27.",
        "",
        "Score: 38 (3 red, 2 yellow, 2 grey) over 69 items: 16 read by Python, 51 by the bot, 2 without a "
        "source; 7 not applicable, 2 not disclosed, 2 not computable, 1 no baseline, 0 unavailable.",
        "",
        "## Triggered",
        "",
        "### 1.1 Full-year revenue guidance · red",
    ]


def test_a_baseline_the_listing_does_not_hold_is_named_none_listed():
    text = rendered(listing=Seasons((P, S), (), (), date(2026, 4, 24)))

    assert text.splitlines()[5] == (
        "Baselines: previous quarter 2026-03-28; same quarter last year none listed; "
        "previous 10-K none listed; previous proxy none listed."
    )


TRIGGERED = f"""### 1.1 Full-year revenue guidance · red

baseline: {RELEASE_1}
observation: The full-year revenue guidance midpoint went from 64.0 to 61.0 billion dollars.
rule: {RULE["1.1"]}

> We now expect full-year revenue of $60.0 billion to $62.0 billion.
— {RELEASE_2}

### 4.2 Risk wording escalated · red

baseline: {TEN_Q_1}; {TEN_K}
observation: A risk factor now states a substrate shortage as a fact.
rule: {RULE["4.2"]}

> We have experienced shortages of substrates this quarter.
— {CALL}, Jane Roe (executive)

> Supply of substrates was constrained throughout the quarter.
— {TEN_Q_2}

### 9.1 Filing timing · red

baseline: {TIMING}
values: {LATE}
rule: {RULE["9.1"]}

### 2.1 Revenue and net income growth · yellow

baseline: {GROWTH}
values: revenue: growth 8.00% against 20.00% a quarter earlier (-12.00 pp)
rule: {RULE["2.1"]}

### 3.6 Accounting policy change · yellow

baseline: {TEN_Q_1}
observation: The filing states the adoption of a new standard on segment reporting.
rule: {RULE["3.6"]}

### 2.7 Segment revenue shares · grey

baseline: {TEN_Q_AGO}
observation: {SEGMENTS}
rule: {RULE["2.7"]}

### 2.10 Weighted diluted shares · grey

baseline: previous quarter 2026-03-28 (10-Q)
values: {SHARES}
rule: {RULE["2.10"]}"""


def test_triggered_items_come_red_yellow_grey_each_in_catalogue_order_with_their_evidence():
    text = rendered()

    triggered = text.split("\n## Triggered\n\n", 1)[1].split("\n\n## 1 Guidance\n", 1)[0]
    assert triggered == TRIGGERED


def test_a_season_where_nothing_triggered_says_so():
    text = rendered(python_readings(), bot_readings())

    assert "\n## Triggered\n\nNone of the items triggered.\n\n## 1 Guidance\n\n" in text
    assert NONE_TRIGGERED == "None of the items triggered."


GUIDANCE = f"""## 1 Guidance

| Item | Level | Read by | Baseline | Values or observation |
| --- | --- | --- | --- | --- |
| 1.1 Full-year revenue guidance | red | bot | {RELEASE_1} | The full-year revenue guidance midpoint went from 64.0 to 61.0 billion dollars. |
| 1.2 Full-year profit guidance | none | bot | none | No change from the baseline. |
| 1.3 Next-quarter guidance against consensus | no source | no source | none | No source: the domain reads no consensus. |
| 1.4 Guidance range width | none | bot | none | No change from the baseline. |
| 1.5 Guidance withdrawn | none | bot | none | No change from the baseline. |
| 1.6 Capital expenditure guidance | not disclosed | bot | none | The season's documents give no capital expenditure guidance. |
| 1.7 Results against the previous guidance | none | bot | none | No change from the baseline. |
| 1.8 Results against consensus | no source | no source | none | No source: the domain reads no consensus. |
| 1.9 Guidance record | no baseline | bot | none | No earlier season's readings are in reports/. |
| 1.10 Full-year kept, next quarter lowered | none | bot | none | No change from the baseline. |
"""  # noqa: E501
FINANCIALS = f"""## 2 Financials

| Item | Level | Read by | Baseline | Values or observation |
| --- | --- | --- | --- | --- |
| 2.1 Revenue and net income growth | yellow | Python | {GROWTH} | revenue: growth 8.00% against 20.00% a quarter earlier (-12.00 pp) |
| 2.2 Gross and operating margins | none | Python | baseline of 2.2 | values of 2.2 |
| 2.3 Operating cash flow to net income | none | Python | baseline of 2.3 | values of 2.3 |
| 2.4 Days of receivables, inventory and payables | none | Python | baseline of 2.4 | values of 2.4 |
| 2.5 Receivables growth against revenue growth | none | Python | baseline of 2.5 | values of 2.5 |
| 2.6 Net debt | not computable | Python | previous quarter 2026-03-28 (10-Q) | {NET_DEBT} |
| 2.7 Segment revenue shares | grey | bot | {TEN_Q_AGO} | Segment shares moved: Client 55% \\| Data Center 30% against 50% \\| 32%. |
| 2.8 Segments merged, split or renamed | none | bot | none | No change from the baseline. |
| 2.9 Non-recurring items | not computable | bot | none | Net income is 0 or below. |
| 2.10 Weighted diluted shares | grey | Python | previous quarter 2026-03-28 (10-Q) | {SHARES} |
| 2.11 Goodwill added | none | Python | baseline of 2.11 | values of 2.11 |
"""  # noqa: E501
DISCLOSURE = f"""## 9 Disclosure

| Item | Level | Read by | Baseline | Values or observation |
| --- | --- | --- | --- | --- |
| 9.1 Filing timing | red | Python | {TIMING} | {LATE} |
| 9.2 Operating metric no longer disclosed | none | bot | none | No change from the baseline. |
| 9.3 Questions and answers compressed | none | Python | baseline of 9.3 | values of 9.3 |
| 9.4 Text length | none | Python | baseline of 9.4 | values of 9.4 |
| 9.5 8-K count | none | Python | baseline of 9.5 | values of 9.5 |
| 9.6 Call cancelled | none | Python | baseline of 9.6 | values of 9.6 |
"""


def test_each_section_tables_its_items_with_their_level_hand_baseline_and_values_or_observation():
    text = rendered()

    assert f"\n\n{GUIDANCE}\n## 2 Financials\n" in text
    assert f"\n\n{FINANCIALS}\n## 3 Accounting and audit\n" in text
    assert text.endswith(f"\n\n{DISCLOSURE}")


def test_the_nine_sections_come_in_order_each_with_its_items():
    text = rendered()

    headings = [line for line in text.splitlines() if line.startswith("## ")]
    assert headings == [
        "## Triggered",
        "## 1 Guidance",
        "## 2 Financials",
        "## 3 Accounting and audit",
        "## 4 Risk, legal and related parties",
        "## 5 Governance and insiders",
        "## 6 Capital allocation and financing",
        "## 7 Earnings call: statements",
        "## 8 Earnings call: questions and answers",
        "## 9 Disclosure",
    ]
    rows = [
        line
        for line in text.splitlines()
        if line.startswith("| ") and not line.startswith(("| Item", "| ---"))
    ]
    assert [row.split(" ", 2)[1] for row in rows] == [item.id for item in ITEMS]


def test_the_report_carries_no_valuation_forecast_or_advice_wording():
    assert WORDING.search(rendered()) is None
    assert WORDING.search(rendered(python_readings(), bot_readings())) is None


# --------------------------------------------------------------------------- files and freshness


def test_a_report_is_named_by_the_new_york_time_it_was_rendered():
    assert report_name(edt(2026, 10, 8, 6, 0)) == "report_20261008T060000EDT.md"
    assert report_name(datetime(2026, 12, 1, 14, 30, 5, tzinfo=UTC)) == "report_20261201T093005EST.md"


def place(directory: Path, *names: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for name in names:
        (directory / name).write_text("# report\n", encoding="utf-8")


def test_the_newest_report_is_the_latest_named_not_after_now(tmp_path):
    place(
        tmp_path,
        "report_20261008T050000EDT.md",
        "report_20261008T055959EDT.md",
        "report_20261008T060001EDT.md",  # after now: not written yet
        "report_20261008T055959EDT.md.rejected",
        "report_20261301T000000EST.md",  # no such time
        "report_latest.md",
        "readings.md",
        "INTC_2026-07-24_20261008T055959EDT.md",
    )
    (tmp_path / "report_20261008T055900EDT.md").mkdir()  # not a file

    assert newest_report(tmp_path, NOW) == tmp_path / "report_20261008T055959EDT.md"
    assert newest_report(tmp_path, edt(2026, 10, 8, 4, 59, 59)) is None


def test_reports_are_ordered_by_instant_across_the_fall_back_hour(tmp_path):
    place(tmp_path, "report_20261101T015959EDT.md", "report_20261101T013000EST.md")

    assert newest_report(tmp_path, est(2026, 11, 1, 2, 0)) == tmp_path / "report_20261101T013000EST.md"
    assert newest_report(tmp_path, est(2026, 11, 1, 1, 15)) == tmp_path / "report_20261101T015959EDT.md"


def test_a_missing_directory_holds_no_report(tmp_path):
    assert newest_report(tmp_path / "2026-06-27", NOW) is None


def test_two_reports_are_the_same_apart_from_their_generated_line():
    held = rendered()

    assert same_report(held, rendered(generated_at=NOW + timedelta(days=3)))
    measures, readings = season()
    changed = bot_readings(*(reading for reading in readings.items if reading.item.id != "3.6"))
    assert not same_report(held, rendered(measures, changed))
    assert not same_report(held, held.replace("Score: 38", "Score: 39"))


# --------------------------------------------------------------------------- the ranking


def test_the_ranking_orders_the_tickers_by_score_then_by_name():
    lines = ranking(
        [
            (
                "AMD",
                "2026-06-27",
                level_entries(i2_1="yellow"),
                "reports/AMD/2026-06-27/report_20261008T060000EDT.md",
            ),
            (
                "MU",
                "2026-05-28",
                level_entries(i1_1="red", i2_7="grey"),
                "reports/MU/2026-05-28/report_20261008T060000EDT.md",
            ),
            (
                "INTC",
                "2026-06-27",
                level_entries(i9_1="red", i2_10="grey"),
                "reports/INTC/2026-06-27/report_20261008T060000EDT.md",
            ),
            ("AAOI", "2026-06-30", level_entries(), "reports/AAOI/2026-06-30/report_20261008T060000EDT.md"),
        ]
    )

    assert lines == [
        "| Ticker | Season | Score | red | yellow | grey | Report |",
        "| --- | --- | --- | --- | --- | --- | --- |",
        "| INTC | 2026-06-27 | 11 | 1 | 0 | 1 | reports/INTC/2026-06-27/report_20261008T060000EDT.md |",
        "| MU | 2026-05-28 | 11 | 1 | 0 | 1 | reports/MU/2026-05-28/report_20261008T060000EDT.md |",
        "| AMD | 2026-06-27 | 3 | 0 | 1 | 0 | reports/AMD/2026-06-27/report_20261008T060000EDT.md |",
        "| AAOI | 2026-06-30 | 0 | 0 | 0 | 0 | reports/AAOI/2026-06-30/report_20261008T060000EDT.md |",
    ]


def test_an_empty_ranking_is_its_header():
    assert ranking([]) == [
        "| Ticker | Season | Score | red | yellow | grey | Report |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
