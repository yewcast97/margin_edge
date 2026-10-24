"""script/report.py: a comparison's report, its file names and its freshness.

The report is rendered from dataclasses built here, as ``workflow`` hands them over: the raw
tree's state (``documents.RawState``: the issuer, the listing with a pending 8-K, a pending
call and each season's documents), the season's files (``documents.SeasonFiles``), one of its
comparisons (``aspects.Comparison``) and the bot's parsed readings (``readings.Readings``).
``READINGS`` gives three aspects items (values on both sides, a value of the season alone, one
of the baseline alone, a call's quote, a cell holding ``|``) and leaves three ``na``. The
expected text is written out by hand. File names are tried under ``tmp_path``.
"""

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from market_state_research.fundamentals.script.aspects import ASPECTS, Comparison
from market_state_research.fundamentals.script.documents import (
    CallState,
    Document,
    FilingFiles,
    RawState,
    SeasonFiles,
)
from market_state_research.fundamentals.script.earningscalls import CallEvent
from market_state_research.fundamentals.script.filings import Dated, Filing, Season, Seasons
from market_state_research.fundamentals.script.readings import WORDING, Item, Quote, Readings, Section
from market_state_research.fundamentals.script.report import (
    newest_report,
    render_report,
    report_files,
    report_name,
    same_report,
)

from .support import NOW, edt, est

TICKER = "INTC"
CIK = "0000050863"
ENTITY = "INTEL CORP"
ROOT = Path("data/raw/INTC")  # never read: the report reads no file

OLD_K = Season(Filing("10-K", "0000050863-25-000009", date(2025, 1, 31), date(2024, 12, 28), "k24.htm"), ())
OLD_Q = Season(Filing("10-Q", "0000050863-25-000201", date(2025, 10, 31), date(2025, 9, 27), "q325.htm"), ())
K = Season(Filing("10-K", "0000050863-26-000012", date(2026, 1, 30), date(2025, 12, 27), "k25.htm"), ())
P = Season(Filing("10-Q", "0000050863-26-000041", date(2026, 4, 24), date(2026, 3, 28), "q126.htm"), ())
S = Season(Filing("10-Q", "0000050863-26-000064", date(2026, 7, 24), date(2026, 6, 27), "q226.htm"), ())
PENDING_8K = Dated("8-K", "0000050863-26-000066", date(2026, 8, 3), date(2026, 7, 30), "8.01", "x.htm")
PENDING_CALL = CallEvent(250001, edt(2026, 10, 6, 17, 0), 2026, 3)
LISTING = Seasons((OLD_K, OLD_Q, K, P, S), (PENDING_8K,), (), date(2025, 1, 31))

OLD_TEN_K = "10-K_2024-12-28_0000050863-25-000009_k24"
OLD_TEN_Q = "10-Q_2025-09-27_0000050863-25-000201_q325"
TEN_K = "10-K_2025-12-27_0000050863-26-000012_k25"
TEN_Q_1 = "10-Q_2026-03-28_0000050863-26-000041_q126"
RELEASE_1 = "8-K_2026-04-23_0000050863-26-000040_q126earningsrelease"
CALL_1 = "call_2026-03-28_26083"
TEN_Q_2 = "10-Q_2026-06-27_0000050863-26-000064_q226"
RELEASE_2 = "8-K_2026-07-23_0000050863-26-000062_q226earningsrelease"
CALL_2 = "call_2026-06-27_248001"
TRANSCRIPT = CallState(
    "transcript",
    (CallEvent(248001, edt(2026, 7, 23, 17, 0)),),
    (),
    (),
    date(2026, 7, 23),
    date(2026, 8, 1),
    None,
)
UNAVAILABLE = CallState("unavailable", (), (), (), date(2026, 1, 30), date(2026, 10, 8), None)


def document(doc_id: str, day: date) -> Document:
    return Document(doc_id, "call" if doc_id.startswith("call_") else "filing", day, ROOT / doc_id, doc_id)


# An 8-K of a season, whose documents stand for its earnings release: the report reads no item of it.
RELEASE = Dated("8-K", "0000050863-26-000062", date(2026, 7, 23), date(2026, 7, 23), "2.02,9.01", "x.htm")


def season_files(row: Season, filing: str, *others: str, call: CallState = UNAVAILABLE) -> SeasonFiles:
    """The files of ``row``: its 10-K or 10-Q ``filing``, then the documents of one 8-K and of its
    call (a ``DOC_ID`` starting ``call_``) that ``others`` names."""
    folder = ROOT / str(row.period)
    releases = tuple(document(doc_id, row.period) for doc_id in others if not doc_id.startswith("call_"))
    calls = tuple(document(doc_id, row.period) for doc_id in others if doc_id.startswith("call_"))
    eight_ks = (FilingFiles(RELEASE, folder, (), True, (), releases),) if releases else ()
    held = CallState(call.status, call.events, calls, (), call.due, call.as_of, call.reason)
    return SeasonFiles(
        row, folder, folder / "filing.htm", document(filing, row.period), eight_ks, held, frozenset()
    )


FILES = {
    OLD_K.period: season_files(OLD_K, OLD_TEN_K),
    OLD_Q.period: season_files(OLD_Q, OLD_TEN_Q),
    K.period: season_files(K, TEN_K),
    P.period: season_files(P, TEN_Q_1, RELEASE_1, CALL_1, call=TRANSCRIPT),
    S.period: season_files(S, TEN_Q_2, RELEASE_2, CALL_2, call=TRANSCRIPT),
}


def raw_state(listing: Seasons = LISTING, pending: tuple[CallEvent, ...] = (PENDING_CALL,)) -> RawState:
    return RawState(
        ticker=TICKER,
        submissions=ROOT / "submissions_20261008T053002EDT.json",
        cik=CIK,
        entity_name=ENTITY,
        reason=None,
        listing=listing,
        seasons=tuple(FILES[season.period] for season in listing.seasons),
        capture=None,
        capture_problem=None,
        pending_calls=pending,
        unlisted=(),
        former_layout=(),
        transcript_files={},
        invalid_files=(),
    )


def quote(text: str, doc_id: str, speaker: str | None = None) -> Quote:
    return Quote(0, text, doc_id, speaker, 0)


GUIDANCE = Item(
    "Next-quarter revenue guidance",
    0,
    (RELEASE_2,),
    "revenue of $12.6 billion to $13.6 billion",
    (RELEASE_1,),
    "revenue of $11.8 billion to $12.8 billion",
    "$0.8 billion higher at both ends of the range",
    (
        quote("For the coming quarter, we expect revenue of $12.6 billion to $13.6 billion.", RELEASE_2),
        quote("For the coming quarter, we expect revenue of $11.8 billion to $12.8 billion.", RELEASE_1),
    ),
)
CAPEX = Item(
    "Full-year net capital spending",
    0,
    (RELEASE_2,),
    "approximately $9 billion",
    (),
    "na",
    "na",
    (quote("We now expect net capital spending of approximately $9 billion for the full year.", RELEASE_2),),
)
DEMAND = Item(
    "Server demand | supply on the call",
    0,
    (CALL_2,),
    "demand above supply",
    (CALL_1,),
    "demand grew faster than planned",
    "demand stated against supply, not against plan",
    (
        quote(
            "Demand for our server processors exceeded our supply in the quarter.",
            CALL_2,
            "Lip-Bu Tan (executive)",
        ),
        quote(
            "Data center demand grew faster than we planned in the first quarter.",
            CALL_1,
            "Lip-Bu Tan (executive)",
        ),
    ),
)
ONLY_BEFORE = Item(
    "Data center demand against plan",
    0,
    (),
    "na",
    (CALL_1,),
    "grew faster than planned",
    "na",
    (
        quote(
            "Data center demand grew faster than we planned in the first quarter.",
            CALL_1,
            "Lip-Bu Tan (executive)",
        ),
    ),
)


def readings(kind: str = "quarter", **items: tuple[Item, ...]) -> Readings:
    """Every aspect ``na`` but those ``items`` gives, by key."""
    return Readings(
        kind,  # type: ignore[arg-type]
        1,
        tuple(
            Section(aspect, 0, 0 if aspect.key in items else 1, items.get(aspect.key, ()))
            for aspect in ASPECTS
        ),
    )


READINGS = readings(guidance=(GUIDANCE,), capex=(CAPEX,), demand=(DEMAND, ONLY_BEFORE))
QUARTER = Comparison("quarter", P)


def rendered(
    found: Comparison = QUARTER,
    read: Readings = READINGS,
    *,
    season: Season = S,
    raw: RawState | None = None,
    generated_at: datetime = NOW,
) -> str:
    return render_report(raw or raw_state(), FILES[season.period], found, read, generated_at)


EXPECTED = f"""# INTC · 2026-06-27 · quarter report

Generated 2026-10-08 06:00:00 EDT.

Issuer: INTEL CORP (CIK 0000050863). Season: the 10-Q for the period ended 2026-06-27 (accession 0000050863-26-000064, filed 2026-07-24). Call: transcript (call 248001 of 2026-07-23).
Comparison: quarter: this season against the previous season, 2026-03-28 (10-Q).
The season's documents: {TEN_Q_2}; {RELEASE_2}; {CALL_2}.
The baseline's documents: {TEN_Q_1}; {RELEASE_1}; {CALL_1}.
Pending, dated after the season's 10-Q was filed: the 8-K 0000050863-26-000066 dated 2026-07-30; the call 250001 of 2026-10-06.

4 items in 6 aspects; aspects without an item: Upstream supply, Debt structure, Product roadmap.

## Guidance

| Item | New | Old | Difference |
| --- | --- | --- | --- |
| Next-quarter revenue guidance | revenue of $12.6 billion to $13.6 billion · {RELEASE_2} | revenue of $11.8 billion to $12.8 billion · {RELEASE_1} | $0.8 billion higher at both ends of the range |

## Capital expenditure

| Item | New | Old | Difference |
| --- | --- | --- | --- |
| Full-year net capital spending | approximately $9 billion · {RELEASE_2} | na | na |

## Upstream supply

na

## Downstream demand

| Item | New | Old | Difference |
| --- | --- | --- | --- |
| Server demand \\| supply on the call | demand above supply · {CALL_2} | demand grew faster than planned · {CALL_1} | demand stated against supply, not against plan |
| Data center demand against plan | na | grew faster than planned · {CALL_1} | na |

## Debt structure

na

## Product roadmap

na

## Evidence

### Guidance · Next-quarter revenue guidance

season: {RELEASE_2}
baseline: {RELEASE_1}

> For the coming quarter, we expect revenue of $12.6 billion to $13.6 billion.
— {RELEASE_2}

> For the coming quarter, we expect revenue of $11.8 billion to $12.8 billion.
— {RELEASE_1}

### Capital expenditure · Full-year net capital spending

season: {RELEASE_2}
baseline: none

> We now expect net capital spending of approximately $9 billion for the full year.
— {RELEASE_2}

### Downstream demand · Server demand | supply on the call

season: {CALL_2}
baseline: {CALL_1}

> Demand for our server processors exceeded our supply in the quarter.
— {CALL_2}, Lip-Bu Tan (executive)

> Data center demand grew faster than we planned in the first quarter.
— {CALL_1}, Lip-Bu Tan (executive)

### Downstream demand · Data center demand against plan

season: none
baseline: {CALL_1}

> Data center demand grew faster than we planned in the first quarter.
— {CALL_1}, Lip-Bu Tan (executive)
"""  # noqa: E501


# --------------------------------------------------------------------------- the report


def test_the_report_states_each_aspects_items_with_their_documents_and_evidence():
    assert rendered() == EXPECTED


def test_the_generated_line_names_the_new_york_time_of_the_render():
    text = rendered(generated_at=datetime(2026, 11, 2, 11, 0, tzinfo=UTC))

    assert text.splitlines()[2] == "Generated 2026-11-02 06:00:00 EST."


def test_a_year_report_compares_the_10_k_season_with_the_previous_10_k():
    text = rendered(Comparison("year", OLD_K), readings("year"), season=K)

    assert text.splitlines()[:11] == [
        "# INTC · 2025-12-27 · year report",
        "",
        "Generated 2026-10-08 06:00:00 EDT.",
        "",
        "Issuer: INTEL CORP (CIK 0000050863). Season: the 10-K for the period ended 2025-12-27 (accession "
        "0000050863-26-000012, filed 2026-01-30). Call: unavailable as of the calls list of 2026-10-08.",
        "Comparison: year: this 10-K season against the previous 10-K season, 2024-12-28.",
        f"The season's documents: {TEN_K}.",
        f"The baseline's documents: {OLD_TEN_K}.",
        "",
        "0 items in 6 aspects; aspects without an item: Guidance, Capital expenditure, Upstream supply, "
        "Downstream demand, Debt structure, Product roadmap.",
        "",
    ]
    assert text.endswith("## Product roadmap\n\nna\n\n## Evidence\n\nna\n")


def test_the_quarter_report_of_a_10_k_season_compares_it_with_the_third_quarter():
    text = rendered(Comparison("quarter", OLD_Q), readings(), season=K)

    assert text.splitlines()[5:8] == [
        "Comparison: quarter: this season against the previous season, 2025-09-27 (10-Q).",
        f"The season's documents: {TEN_K}.",
        f"The baseline's documents: {OLD_TEN_Q}.",
    ]


@pytest.mark.parametrize(
    ("found", "line"),
    [
        (
            Comparison("quarter", None),
            "Comparison: quarter: this season against the previous season: none is listed.",
        ),
        (
            Comparison("year", None),
            "Comparison: year: this 10-K season against the previous 10-K season: none is listed.",
        ),
    ],
    ids=["quarter", "year"],
)
def test_a_comparison_whose_baseline_is_not_listed_says_so(found, line):
    text = rendered(found, readings(found.kind), season=OLD_K)

    assert text.splitlines()[5:8] == [
        line,
        f"The season's documents: {OLD_TEN_K}.",
        "The baseline's documents: none in raw/.",
    ]


def test_a_baseline_season_without_documents_in_raw_has_none():
    raw = raw_state()
    empty = SeasonFiles(P, ROOT / "2026-03-28", ROOT / "x.htm", None, (), UNAVAILABLE, frozenset())
    raw = replace(raw, seasons=tuple(empty if files.season is P else files for files in raw.seasons))

    assert rendered(raw=raw).splitlines()[7] == "The baseline's documents: none in raw/."


def test_only_the_newest_listed_seasons_report_names_what_is_pending():
    newest = rendered().splitlines()
    earlier = rendered(Comparison("quarter", K), readings(), season=P).splitlines()
    nothing = rendered(
        raw=raw_state(Seasons((OLD_K, OLD_Q, K, P, S), (), (), date(2025, 1, 31)), ())
    ).splitlines()

    assert newest[8].startswith(
        "Pending, dated after the season's 10-Q was filed: the 8-K 0000050863-26-000066"
    )
    assert earlier[8] == "" and not any(line.startswith("Pending") for line in earlier)
    assert nothing[8] == "Pending, dated after the season's 10-Q was filed: none."


def test_the_count_line_counts_the_items_listed():
    one = rendered(read=readings(capex=(CAPEX,))).splitlines()

    assert one[10] == (
        "1 item in 6 aspects; aspects without an item: Guidance, Upstream supply, Downstream demand, Debt "
        "structure, Product roadmap."
    )


def test_every_item_is_listed_in_the_readings_order_whatever_its_values():
    text = rendered(read=readings(demand=(ONLY_BEFORE, DEMAND)))

    section = text.split("## Downstream demand\n")[1].split("## Debt structure")[0]
    rows = [line.split(" | ")[0] for line in section.splitlines() if line.startswith("| ")]
    assert rows == [
        "| Item",
        "| ---",
        "| Data center demand against plan",
        "| Server demand \\| supply on the call",
    ]


def test_the_report_carries_no_valuation_forecast_or_advice_wording_of_its_own():
    assert WORDING.search(rendered()) is None
    assert WORDING.search(rendered(Comparison("year", OLD_K), readings("year"), season=K)) is None


# --------------------------------------------------------------------------- files and freshness


def test_a_report_is_named_by_its_comparison_and_the_new_york_time_it_was_rendered():
    assert report_name("quarter", edt(2026, 10, 8, 6, 0)) == "report_quarter_20261008T060000EDT.md"
    assert (
        report_name("year", datetime(2026, 12, 1, 14, 30, 5, tzinfo=UTC))
        == "report_year_20261201T093005EST.md"
    )


def place(directory: Path, *names: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for name in names:
        (directory / name).write_text("# report\n", encoding="utf-8")


def test_the_newest_report_of_a_comparison_is_the_latest_named_not_after_now(tmp_path):
    place(
        tmp_path,
        "report_quarter_20261008T050000EDT.md",
        "report_quarter_20261008T055959EDT.md",
        "report_quarter_20261008T060001EDT.md",  # after now: not written yet
        "report_quarter_20261008T055959EDT.md.rejected",
        "report_quarter_20261301T000000EST.md",  # no such time
        "report_year_20261008T055000EDT.md",
        "report_20261008T055959EDT.md",  # the season report of the catalogue before 2026-10-24
        "report_latest.md",
        "readings_quarter.md",
    )
    (tmp_path / "report_quarter_20261008T055900EDT.md").mkdir()  # not a file

    assert newest_report(tmp_path, "quarter", NOW) == tmp_path / "report_quarter_20261008T055959EDT.md"
    assert newest_report(tmp_path, "year", NOW) == tmp_path / "report_year_20261008T055000EDT.md"
    assert newest_report(tmp_path, "quarter", edt(2026, 10, 8, 4, 59, 59)) is None
    assert [path.name for path in report_files(tmp_path, "year")] == ["report_year_20261008T055000EDT.md"]


def test_reports_are_ordered_by_instant_across_the_fall_back_hour(tmp_path):
    place(tmp_path, "report_year_20261101T015959EDT.md", "report_year_20261101T013000EST.md")

    assert (
        newest_report(tmp_path, "year", est(2026, 11, 1, 2, 0))
        == tmp_path / "report_year_20261101T013000EST.md"
    )
    assert newest_report(tmp_path, "year", est(2026, 11, 1, 1, 15)) == (
        tmp_path / "report_year_20261101T015959EDT.md"
    )


def test_a_missing_directory_holds_no_report(tmp_path):
    assert newest_report(tmp_path / "2026-06-27", "quarter", NOW) is None


def test_two_reports_are_the_same_apart_from_their_generated_line():
    held = rendered()

    assert same_report(held, rendered(generated_at=NOW + timedelta(days=3)))
    assert not same_report(held, rendered(read=readings(guidance=(GUIDANCE,))))
    assert not same_report(held, held.replace("| na | na |", "| na | none |", 1))
