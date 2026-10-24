"""script/sheet.py: a season's sheet, ``formatted/{T}/{PERIOD}/season.md``.

The sheet is read from a real tree: ``workflow_support.fetch`` writes the fake EDGAR's and the
fake provider's files, and ``documents.season_documents`` reads them, as ``derive`` does. Every
expected text is written out by hand from the fixtures (``edgar_support``, ``calls_support``),
so a change of layout or wording fails here first.
"""

from datetime import date

from market_state_research.common.layout import DataLayout
from market_state_research.fundamentals.script.aspects import Comparison
from market_state_research.fundamentals.script.documents import season_documents
from market_state_research.fundamentals.script.readings import WORDING
from market_state_research.fundamentals.script.sheet import SHEET, baseline_documents, call_line, season_sheet

from .edgar_support import RECENT, TICKER, Row
from .support import NOW
from .workflow_support import DOC_IDS, fetch, place, submissions_json

Q1 = date(2026, 3, 28)
Q2 = date(2026, 6, 27)
FY = date(2025, 12, 27)
INTRO = (
    "Each comparison of the season, its baseline season and that season's documents in raw/: a reading's "
    "baseline lines name some of these DOC_IDs."
)
FILINGS_HEADER = (
    "| Form | Dated | Filed | Accepted | Accession | Items | Documents (DOC_ID) |\n"
    "| --- | --- | --- | --- | --- | --- | --- |\n"
)
Q2_RELEASE = f"{DOC_IDS['eight_k_2']}; {DOC_IDS['exhibit_2_1']}; {DOC_IDS['exhibit_2_2']}"
Q1_DOCUMENTS = f"{DOC_IDS['ten_q_1']}; {DOC_IDS['eight_k_1']}; {DOC_IDS['exhibit_1']}; {DOC_IDS['call_q1']}"
GOLDEN_10Q = f"""# INTC · 2026-06-27 · season

Season: the 10-Q for the period ended 2026-06-27, accession 0000050863-26-000064, filed 2026-07-24, accepted 2026-07-24 16:05:00 EDT.
Call: transcript (call 248001 of 2026-07-23).

## Comparisons

{INTRO}

| Comparison | Baseline season | Its documents in raw/ (DOC_ID) |
| --- | --- | --- |
| quarter | 2026-03-28 (10-Q) | {Q1_DOCUMENTS} |

## Filings of the season

{FILINGS_HEADER}| 10-Q | 2026-06-27 | 2026-07-24 | 2026-07-24 16:05:00 EDT | 0000050863-26-000064 |  | {DOC_IDS["ten_q_2"]} |
| 8-K | 2026-07-23 | 2026-07-23 | 2026-07-23 16:05:00 EDT | 0000050863-26-000062 | 2.02,9.01 | {Q2_RELEASE} |

## Inputs for the bot

- The 10-Q: {DOC_IDS["ten_q_2"]}.
- Earnings releases, the 8-Ks with Item 2.02: {Q2_RELEASE}.
- Agreements and direct financial obligations, the 8-Ks with Items 1.01 or 2.03: none.
- Other 8-Ks: none.
- The call: {DOC_IDS["call_q2"]}.
- Registrations and prospectuses, listed, not fetched: none.
- Amendments, listed, not fetched: none.
- Late-filing notices, listed, not fetched: none.
"""  # noqa: E501
GOLDEN_10K = f"""# INTC · 2025-12-27 · season

Season: the 10-K for the period ended 2025-12-27, accession 0000050863-26-000012, filed 2026-01-30, accepted 2026-01-30 15:05:00 EST.
Call: unavailable as of the calls list of 2026-10-08.

## Comparisons

{INTRO}

| Comparison | Baseline season | Its documents in raw/ (DOC_ID) |
| --- | --- | --- |
| quarter | 2025-09-27 (10-Q) | {DOC_IDS["old_ten_q"]}; {DOC_IDS["call_old_q"]} |
| year | 2024-12-28 (10-K) | {DOC_IDS["old_ten_k"]} |

## Filings of the season

{FILINGS_HEADER}| 10-K | 2025-12-27 | 2026-01-30 | 2026-01-30 15:05:00 EST | 0000050863-26-000012 |  | {DOC_IDS["ten_k"]} |
| 8-K | 2026-02-09 | 2026-02-10 | 2026-02-10 15:05:00 EST | 0000050863-26-000020 | 5.02,9.01 | {DOC_IDS["eight_k_other"]} |

## Inputs for the bot

- The 10-K: {DOC_IDS["ten_k"]}.
- Earnings releases, the 8-Ks with Item 2.02: none.
- Agreements and direct financial obligations, the 8-Ks with Items 1.01 or 2.03: none.
- Other 8-Ks: {DOC_IDS["eight_k_other"]}.
- The call: none (unavailable).
- Registrations and prospectuses, listed, not fetched: none.
- Amendments, listed, not fetched: none.
- Late-filing notices, listed, not fetched: none.
"""  # noqa: E501


def sheet(layout: DataLayout, day: date) -> str:
    raw = season_documents(layout, TICKER, NOW)
    files = raw.season(day)
    assert files is not None
    return season_sheet(raw, files)


def test_a_10_q_seasons_sheet_names_its_comparison_its_filings_and_its_inputs(layout):
    fetch(layout)

    assert sheet(layout, Q2) == GOLDEN_10Q


def test_a_10_k_seasons_sheet_names_both_its_comparisons(layout):
    fetch(layout)

    assert sheet(layout, FY) == GOLDEN_10K


def test_the_oldest_listed_season_has_no_baseline_listed(layout):
    fetch(layout)

    lines = sheet(layout, date(2024, 12, 28)).splitlines()

    assert lines[lines.index("| --- | --- | --- |") + 1 :][:2] == [
        "| quarter | none listed | none |",
        "| year | none listed | none |",
    ]


# Filings of the season ended 2026-03-28 beside its release: an agreement, a Regulation FD 8-K
# whose documents are not fetched yet, a shelf registration, a prospectus, an amendment and a notice.
AGREEMENT = Row(
    "8-K", "0000050863-26-000055", date(2026, 6, 2), date(2026, 6, 1), "intc-20260601.htm", "1.01"
)
DISCLOSURE = Row(
    "8-K", "0000050863-26-000050", date(2026, 5, 4), date(2026, 5, 1), "intc-20260501.htm", "7.01"
)
LISTED = (
    Row("S-3ASR", "0001193125-26-200001", date(2026, 5, 1), None, "d200001ds3asr.htm"),
    Row("424B5", "0001193125-26-200002", date(2026, 5, 4), None, "d200002d424b5.htm"),
    Row("8-K/A", "0000050863-26-000045", date(2026, 5, 2), date(2026, 4, 23), "intc-20260423a.htm", "2.02"),
    Row("NT 10-Q", "0000950170-26-000003", date(2026, 5, 8), None, "nt10q.htm"),
)


def test_listed_only_forms_and_8_ks_by_their_items_are_inputs(layout):
    fetch(layout)
    place(
        layout.raw(TICKER) / "submissions_20261008T055000EDT.json",
        submissions_json(rows=(AGREEMENT, DISCLOSURE, *LISTED, *RECENT)),
    )

    text = sheet(layout, Q1)

    assert (
        "| S-3ASR | 2026-05-01 | 2026-05-01 | 2026-05-01 16:05:00 EDT | 0001193125-26-200001 |  | "
        "listed only |"
    ) in text
    assert (
        "| 8-K | 2026-06-01 | 2026-06-02 | 2026-06-02 16:05:00 EDT | 0000050863-26-000055 | 1.01 | "
        "not in raw/ |"
    ) in text
    assert text.endswith(
        f"- The 10-Q: {DOC_IDS['ten_q_1']}.\n"
        f"- Earnings releases, the 8-Ks with Item 2.02: {DOC_IDS['eight_k_1']}; {DOC_IDS['exhibit_1']}.\n"
        "- Agreements and direct financial obligations, the 8-Ks with Items 1.01 or 2.03: "
        "0000050863-26-000055 (not in raw/).\n"
        "- Other 8-Ks: 0000050863-26-000050 (not in raw/).\n"
        f"- The call: {DOC_IDS['call_q1']}.\n"
        "- Registrations and prospectuses, listed, not fetched: S-3ASR 0001193125-26-200001 filed "
        "2026-05-01, 424B5 0001193125-26-200002 filed 2026-05-04.\n"
        "- Amendments, listed, not fetched: 8-K/A 0000050863-26-000045 filed 2026-05-02.\n"
        "- Late-filing notices, listed, not fetched: NT 10-Q 0000950170-26-000003 filed 2026-05-08.\n"
    )


def test_a_baseline_without_a_listed_season_has_no_documents(layout):
    fetch(layout)
    raw = season_documents(layout, TICKER, NOW)
    listing = raw.listing
    assert listing is not None

    assert baseline_documents(raw, Comparison("quarter", None)) == ()
    assert baseline_documents(raw, Comparison("year", listing.seasons[0])) == (DOC_IDS["old_ten_k"],)


def test_the_call_line_dates_only_a_verdict_the_calls_list_gives(layout):
    fetch(layout)
    raw = season_documents(layout, TICKER, NOW)

    lines = {files.day: call_line(files.call) for files in raw.seasons}

    assert lines[Q2] == "Call: transcript (call 248001 of 2026-07-23)."
    assert lines[FY] == "Call: unavailable as of the calls list of 2026-10-08."


def test_the_sheet_is_named_season_md_and_carries_no_valuation_forecast_or_advice_wording(layout):
    fetch(layout)

    assert SHEET == "season.md"
    assert WORDING.search(sheet(layout, Q2)) is None
    assert WORDING.search(sheet(layout, FY)) is None
