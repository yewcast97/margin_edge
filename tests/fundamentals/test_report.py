"""script/report.py: a season's report, its file names and its freshness.

The report is rendered from dataclasses built here, as ``workflow`` hands them over: the listed
seasons (``filings.Seasons``), the season's files (``documents.SeasonFiles``), its Python items
(``measures.Measures``) and the bot's parsed readings (``readings.Readings``). ``season`` gives
every item its old and new values: the Python items one stand-in row each but 2.2 (two rows)
and 2.10 (a note), the bot's items their words, quotes or the statuses an annual item and a
proxy item take in a 10-Q season without a proxy statement, and two items without a source.
The expected text is written out by hand; its rule lines are the catalogue's
(``items.BY_ID``). File names are tried under ``tmp_path``.
"""

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from market_state_research.fundamentals.script.documents import CallState, SeasonFiles
from market_state_research.fundamentals.script.earningscalls import CallEvent
from market_state_research.fundamentals.script.filings import Dated, Filing, Season, Seasons
from market_state_research.fundamentals.script.items import (
    BOT_ITEMS,
    BY_ID,
    ITEMS,
    PYTHON_ITEMS,
    Item,
    by_importance,
)
from market_state_research.fundamentals.script.measures import Measures, Reading, Row
from market_state_research.fundamentals.script.readings import WORDING, ItemReading, Quote, Readings
from market_state_research.fundamentals.script.report import (
    counts_line,
    entries,
    newest_report,
    ordered,
    render_report,
    report_name,
    same_report,
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
PREVIOUS = "previous quarter 2026-03-28 (10-Q)"
AGO = "same quarter last year 2025-06-28 (10-Q)"
MARGINS = (
    Row("gross margin (%)", AGO, "40.00", "38.50", "-1.50 pp"),
    Row("gross margin (%)", PREVIOUS, "39.10", "38.50", "-0.60 pp"),
)
SHARES = Row(
    "weighted average diluted shares", PREVIOUS, "4,400,000,000", "4,500,000,000", "+100,000,000 (+2.27%)"
)
SEGMENTS = "Client 55% | Data Center 30%"
NOT_APPLICABLE = ("3.2", "3.8", "3.9", "3.11", "4.8", "5.5", "5.6")


def files(call: CallState = TRANSCRIPT, row: Season = S) -> SeasonFiles:
    """The files of the season ``row``, its documents left out: the report names none of them."""
    folder = ROOT / str(row.period)
    return SeasonFiles(row, folder, folder / "filing.htm", None, (), call, frozenset())


def key(item: Item) -> str:
    return "i" + item.id.replace(".", "_")


def stand_in(item: Item) -> Reading:
    return Reading(
        item, (Row(f"compared {item.id}", f"baseline of {item.id}", f"old {item.id}", f"new {item.id}", "—"),)
    )


def python_readings(**changed: Reading) -> Measures:
    """The Python items, each one stand-in row, but those ``changed`` gives, keyed ``i2_1``."""
    found = tuple(changed.get(key(item), stand_in(item)) for item in PYTHON_ITEMS)
    return Measures(files(), found, (), "")


def bot(
    identifier: str,
    old: str,
    new: str = "none",
    baseline: tuple[str, ...] = (),
    *quotes: tuple[str, str] | tuple[str, str, str],
) -> ItemReading:
    """The bot's reading of an item; a quote is (text, DOC_ID) or (text, DOC_ID, speaker heading)."""
    read = tuple(Quote(0, quote[0], quote[1], quote[2] if len(quote) > 2 else None, 0) for quote in quotes)
    return ItemReading(BY_ID[identifier], 0, baseline, 0, old, 0, new, 0, read)


def bot_readings(*changed: ItemReading) -> Readings:
    """Every bot item at ``none`` (``—`` for the old value of an item without a baseline), without
    a baseline document, but the readings ``changed`` gives."""
    given = {reading.item.id: reading for reading in changed}
    return Readings(
        1,
        tuple(
            given.get(item.id, bot(item.id, "—" if item.baseline == "none" else "none")) for item in BOT_ITEMS
        ),
    )


def season() -> tuple[Measures, Readings]:
    """The season of 2026-06-27: values, quotes, statuses and a note."""
    measures = python_readings(
        i2_2=Reading(BY_ID["2.2"], MARGINS),
        i2_10=Reading(BY_ID["2.10"], (SHARES,), "a stand-in note"),
    )
    readings = bot_readings(
        bot(
            "1.1",
            "full-year revenue $62.0 to $66.0 billion, midpoint $64.0 billion",
            "full-year revenue $60.0 to $62.0 billion, midpoint $61.0 billion",
            (RELEASE_1,),
            ("We now expect full-year revenue of $60.0 billion to $62.0 billion.", RELEASE_2),
        ),
        bot("1.6", "not disclosed", "not disclosed", (RELEASE_1,)),
        bot("1.9", "no baseline", "within the range"),
        bot("2.7", "Client 50% | Data Center 32%", SEGMENTS, (TEN_Q_AGO,)),
        bot("2.9", "—", "not computable"),
        *(bot(identifier, "not applicable", "not applicable") for identifier in NOT_APPLICABLE),
        bot(
            "4.2",
            "none",
            "a risk factor states a substrate shortage as a fact",
            (TEN_Q_1, TEN_K),
            ("We have experienced shortages of substrates this quarter.", CALL, "Jane Roe (executive)"),
            ("Supply of substrates was constrained throughout the quarter.", TEN_Q_2),
        ),
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


def section(text: str, heading: str, following: str | None) -> list[str]:
    """The lines of ``text`` from ``heading`` to the line before ``following`` (or the end)."""
    lines = text.splitlines()
    start = lines.index(heading)
    end = len(lines) if following is None else lines.index(following)
    return lines[start:end]


# --------------------------------------------------------------------------- entries


def test_entries_are_every_item_in_catalogue_order_with_its_rows():
    measures, readings = season()

    found = entries(LISTING, files(), measures, readings)

    assert [entry.item.id for entry in found] == [item.id for item in ITEMS]
    by_id = {entry.item.id: entry for entry in found}
    assert by_id["2.2"].rows == MARGINS
    assert (by_id["2.10"].rows, by_id["2.10"].note) == ((SHARES,), "a stand-in note")
    assert by_id["2.1"].rows == (Row("compared 2.1", "baseline of 2.1", "old 2.1", "new 2.1", "—"),)
    assert by_id["1.3"].rows == (Row("", "none", "no source", "no source", "—"),)
    assert by_id["1.1"].rows == (
        Row(
            "",
            "previous guidance 2026-03-28 (10-Q)",
            "full-year revenue $62.0 to $66.0 billion, midpoint $64.0 billion",
            "full-year revenue $60.0 to $62.0 billion, midpoint $61.0 billion",
            "—",
        ),
    )
    assert (by_id["1.1"].documents, by_id["1.1"].quotes) == (
        RELEASE_1,
        (("We now expect full-year revenue of $60.0 billion to $62.0 billion.", RELEASE_2),),
    )
    assert by_id["4.2"].documents == f"{TEN_Q_1}; {TEN_K}"
    assert by_id["4.2"].quotes[0] == (
        "We have experienced shortages of substrates this quarter.",
        f"{CALL}, Jane Roe (executive)",
    )
    assert (by_id["3.1"].documents, by_id["3.1"].rows[0].old, by_id["3.1"].rows[0].new) == (
        "none",
        "—",
        "none",
    )


@pytest.mark.parametrize(
    ("identifier", "baseline"),
    [
        ("1.1", "previous guidance 2026-03-28 (10-Q)"),
        ("1.9", "previous eight seasons 2026-03-28 (10-Q), 2025-12-27 (10-K), 2025-06-28 (10-Q)"),
        ("2.7", "same quarter last year 2025-06-28 (10-Q)"),
        ("2.8", "previous quarter 2026-03-28 (10-Q)"),
        ("3.1", "none"),
        ("3.2", "previous 10-K 2025-12-27 (10-K)"),
        ("4.1", "previous filings 2026-03-28 (10-Q), 2025-12-27 (10-K)"),
        ("5.5", "previous proxy 2025-12-27 (10-K)"),
        ("1.3", "none"),
    ],
)
def test_a_bot_items_row_names_its_baseline_and_the_seasons_it_names(identifier, baseline):
    measures, readings = season()

    found = {entry.item.id: entry for entry in entries(LISTING, files(), measures, readings)}

    assert found[identifier].rows[0].baseline == baseline


def test_a_baseline_the_listing_does_not_hold_names_none_listed():
    measures, readings = season()
    listing = Seasons((P, S), (), (), date(2026, 4, 24))

    found = {entry.item.id: entry for entry in entries(listing, files(), measures, readings)}

    assert found["2.7"].rows[0].baseline == "same quarter last year none listed"
    assert found["3.2"].rows[0].baseline == "previous 10-K none listed"


def test_readings_without_an_item_cannot_be_reported():
    measures, readings = season()
    lacking = Readings(1, tuple(reading for reading in readings.items if reading.item.id != "2.8"))

    with pytest.raises(ValueError, match=r"^the readings lack item 2\.8$"):
        entries(LISTING, files(), measures, lacking)


def test_entries_are_ordered_high_then_medium_then_low_each_in_catalogue_order():
    measures, readings = season()

    found = ordered(entries(LISTING, files(), measures, readings))

    assert [entry.item.id for entry in found] == [item.id for item in by_importance()]
    assert [entry.item.importance for entry in found] == ["high"] * 22 + ["medium"] * 37 + ["low"] * 9


def test_the_count_line_counts_the_items_by_importance_and_by_hand():
    measures, readings = season()

    assert counts_line(entries(LISTING, files(), measures, readings)) == (
        "68 items, every one listed by importance (22 high, 37 medium, 9 low): 15 read by Python, 51 by "
        "the bot, 2 without a source."
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
def test_the_report_opens_with_the_issuer_the_season_its_baselines_and_the_count(
    call, generated_at, generated, call_line
):
    text = rendered(call=call, generated_at=generated_at)

    assert text.splitlines()[:13] == [
        "# INTC · 2026-06-27 · season report",
        "",
        f"Generated {generated}.",
        "",
        "Issuer: INTEL CORP (CIK 0000050863). Season: the 10-Q for the period ended 2026-06-27 (accession "
        f"0000050863-26-000064, filed 2026-07-24). {call_line}",
        "Baselines: previous quarter 2026-03-28; same quarter last year 2025-06-28; "
        "previous 10-K 2025-12-27; previous proxy 2025-12-27.",
        "",
        "68 items, every one listed by importance (22 high, 37 medium, 9 low): 15 read by Python, 51 by "
        "the bot, 2 without a source.",
        "",
        "## Items",
        "",
        "| Importance | Item | Baseline | Old | New | Change |",
        "| --- | --- | --- | --- | --- | --- |",
    ]


def test_the_report_names_a_baseline_the_listing_does_not_hold_none_listed():
    text = rendered(listing=Seasons((P, S), (), (), date(2026, 4, 24)))

    assert text.splitlines()[5] == (
        "Baselines: previous quarter 2026-03-28; same quarter last year none listed; "
        "previous 10-K none listed; previous proxy none listed."
    )


def table(text: str) -> list[str]:
    return [line for line in section(text, "## Items", "## Evidence") if line.startswith("| ")][2:]


def test_the_table_has_a_row_per_comparison_of_every_item_high_first():
    rows = table(rendered())

    ids = [row.split(" | ")[1].split(" ", 1)[0] for row in rows]
    expected = [item.id for item in by_importance() for _ in range(2 if item.id == "2.2" else 1)]
    assert ids == expected
    assert len(rows) == 69
    assert [row.split(" | ")[0] for row in rows] == ["| high"] * 22 + ["| medium"] * 38 + ["| low"] * 9


def test_each_row_states_the_old_and_new_values_in_columns_of_their_own():
    rows = table(rendered())

    assert rows[0] == (
        "| high | 1.1 Full-year revenue guidance | previous guidance 2026-03-28 (10-Q) | full-year revenue "
        "$62.0 to $66.0 billion, midpoint $64.0 billion | full-year revenue $60.0 to $62.0 billion, midpoint "
        "$61.0 billion | — |"
    )
    assert "| high | 1.3 Next-quarter guidance against consensus | none | no source | no source | — |" in rows
    assert "| high | 3.1 Auditor change | none | — | none | — |" in rows
    assert (
        "| high | 3.2 Audit opinion | previous 10-K 2025-12-27 (10-K) | not applicable | not applicable | — |"
        in rows
    )
    assert (
        "| medium | 2.2 Gross and operating margins · gross margin (%) | same quarter last year 2025-06-28 "
        "(10-Q) | 40.00 | 38.50 | -1.50 pp |"
    ) in rows
    assert (
        "| low | 2.10 Weighted diluted shares · weighted average diluted shares | previous quarter "
        "2026-03-28 (10-Q) | 4,400,000,000 | 4,500,000,000 | +100,000,000 (+2.27%) |"
    ) in rows
    assert (
        "| low | 2.7 Segment revenue shares | same quarter last year 2025-06-28 (10-Q) | Client 50% \\| Data "
        "Center 32% | Client 55% \\| Data Center 30% | — |"
    ) in rows
    assert (
        "| low | 1.9 Guidance record | previous eight seasons 2026-03-28 (10-Q), 2025-12-27 (10-K), "
        "2025-06-28 (10-Q) | no baseline | within the range | — |"
    ) in rows


EVIDENCE_1_1 = [
    "### 1.1 Full-year revenue guidance",
    "",
    "importance: high; read by the bot (readings.md)",
    f"rule: {BY_ID['1.1'].rule}",
    f"baseline: {RELEASE_1}",
    "",
    "> We now expect full-year revenue of $60.0 billion to $62.0 billion.",
    f"— {RELEASE_2}",
    "",
]
EVIDENCE_4_2 = [
    "### 4.2 Risk wording escalated",
    "",
    "importance: high; read by the bot (readings.md)",
    f"rule: {BY_ID['4.2'].rule}",
    f"baseline: {TEN_Q_1}; {TEN_K}",
    "",
    "> We have experienced shortages of substrates this quarter.",
    f"— {CALL}, Jane Roe (executive)",
    "",
    "> Supply of substrates was constrained throughout the quarter.",
    f"— {TEN_Q_2}",
    "",
]


def test_the_evidence_gives_each_items_rule_documents_quotes_and_note_in_the_tables_order():
    text = rendered()
    evidence = section(text, "## Evidence", None)

    headings = [line[4:].split(" ", 1)[0] for line in evidence if line.startswith("### ")]
    assert headings == [item.id for item in by_importance()]
    assert (
        section(text, "### 1.1 Full-year revenue guidance", "### 1.2 Full-year profit guidance")
        == EVIDENCE_1_1
    )
    assert section(text, "### 4.2 Risk wording escalated", "### 4.4 Litigation and investigations") == (
        EVIDENCE_4_2
    )
    assert section(text, "### 1.3 Next-quarter guidance against consensus", "### 1.5 Guidance withdrawn") == [
        "### 1.3 Next-quarter guidance against consensus",
        "",
        "importance: high; read by no source",
        "rule: No source: the domain reads no consensus.",
        "",
    ]
    assert section(text, "### 2.10 Weighted diluted shares", "### 4.3 Risk factor deleted") == [
        "### 2.10 Weighted diluted shares",
        "",
        "importance: low; read by Python (measures.md)",
        f"rule: {BY_ID['2.10'].rule}",
        "note: a stand-in note",
        "",
    ]
    assert section(text, "### 3.1 Auditor change", "### 3.2 Audit opinion") == [
        "### 3.1 Auditor change",
        "",
        "importance: high; read by the bot (readings.md)",
        f"rule: {BY_ID['3.1'].rule}",
        "baseline: none",
        "",
    ]
    assert text.endswith(f"rule: {BY_ID['9.4'].rule}\n")


def test_every_item_is_listed_whatever_its_values():
    text = rendered(python_readings(), bot_readings())

    assert len(table(text)) == 68
    assert "## Triggered" not in text and "Score" not in text


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
    changed = bot_readings(*(reading for reading in readings.items if reading.item.id != "2.7"))
    assert not same_report(held, rendered(measures, changed))
    assert not same_report(held, held.replace("| 38.50 |", "| 38.60 |", 1))
