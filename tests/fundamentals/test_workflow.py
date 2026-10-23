"""``workflow``: plan, derive, check, render and show over a raw tree built in a temporary directory.

The raw tree is written by ``workflow.fetch`` over ``workflow_support``'s fake EDGAR and fake
EarningsCalls.dev (five listed seasons, three of them in ``WINDOW``), or planted where ``fetch``
writes; readings are ``workflow_support.readings_text``'s, every bot item at the level the
rules require of it. Expected names, ``DOC_ID`` values, dates and messages are written out.
Every file lives below pytest's ``tmp_path``.
"""

import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from market_state_research.common.layout import FileExists
from market_state_research.fundamentals.script import workflow
from market_state_research.fundamentals.script.filings import Window
from market_state_research.fundamentals.script.items import BOT_ITEMS
from market_state_research.fundamentals.script.text import html_text

from .calls_support import (
    CALL_DROPPED,
    CALL_OLD_Q,
    CALL_Q1,
    CALL_Q2,
    CALL_Q3,
    CALLS,
    call_row,
    call_text,
    events_page,
)
from .edgar_support import (
    CIK,
    OLD_TEN_K,
    OLD_TEN_Q,
    PROXY,
    RECENT,
    TEN_K,
    TEN_Q_1,
    TEN_Q_2,
    TICKER,
    Row,
    submissions_json,
)
from .fake_earningscalls import provider
from .support import NOW, TODAY, edt, est
from .workflow_support import (
    CALLS_OF_SEASONS,
    DEFAULT_WINDOW,
    DOC_IDS,
    QUOTE_FILING,
    RAW,
    WINDOW,
    Reading,
    companyfacts_document,
    edgar,
    fetch,
    place,
    plant_former_layout,
    raw_bytes,
    raw_file,
    readings_file,
    readings_text,
    research,
    snapshot,
    write_readings,
    write_watchlist,
)

Q1 = date(2026, 3, 28)
Q2 = date(2026, 6, 27)
LATER = edt(2026, 10, 8, 7, 0)  # an hour after NOW, when the reports render() wrote at NOW are the newest
SUBMISSIONS = "submissions_20261008T053002EDT.json"
COMPANYFACTS = "companyfacts_20261008T053018EDT.json"
CALLS_PAGE = "calls_20261008T053100EDT_1.json"
REPORT = "report_20261008T060000EDT.md"
WINDOW_JSON = {"from": "2025-12-01", "to": "2026-10-08"}
WINDOW_SEASONS = ["2025-12-27", "2026-03-28", "2026-06-27"]
SPAN_SEASONS = ["2024-12-28", "2025-09-27", *WINDOW_SEASONS]
# Every document of the span in the order derive writes their texts: season by season, oldest
# first; in each the 10-K or 10-Q, its filings' documents in date order, then its call.
ROLES = (
    "old_ten_k",
    "old_ten_q",
    "call_old_q",
    "ten_k",
    "eight_k_other",
    "proxy",
    "ten_q_1",
    "eight_k_1",
    "exhibit_1",
    "call_q1",
    "ten_q_2",
    "eight_k_2",
    "exhibit_2_1",
    "exhibit_2_2",
    "call_q2",
)
KINDS = {
    "old_ten_k": "filing",
    "old_ten_q": "filing",
    "call_old_q": "call",
    "ten_k": "filing",
    "eight_k_other": "8-K",
    "proxy": "proxy",
    "ten_q_1": "filing",
    "eight_k_1": "8-K",
    "exhibit_1": "exhibit",
    "call_q1": "call",
    "ten_q_2": "filing",
    "eight_k_2": "8-K",
    "exhibit_2_1": "exhibit",
    "exhibit_2_2": "exhibit",
    "call_q2": "call",
}
SEASON_OF = {
    "old_ten_k": "2024-12-28",
    "old_ten_q": "2025-09-27",
    "call_old_q": "2025-09-27",
    "ten_k": "2025-12-27",
    "eight_k_other": "2025-12-27",
    "proxy": "2025-12-27",
    "ten_q_1": "2026-03-28",
    "eight_k_1": "2026-03-28",
    "exhibit_1": "2026-03-28",
    "call_q1": "2026-03-28",
    "ten_q_2": "2026-06-27",
    "eight_k_2": "2026-06-27",
    "exhibit_2_1": "2026-06-27",
    "exhibit_2_2": "2026-06-27",
    "call_q2": "2026-06-27",
}
CALL_OF_ROLE = {"call_old_q": CALL_OLD_Q, "call_q1": CALL_Q1, "call_q2": CALL_Q2}
# The bot's call items, which are "unavailable" while the season's call has no transcript.
UNAVAILABLE = {
    "i" + item.id.replace(".", "_"): Reading(
        "none", "—" if item.baseline == "none" else "unavailable", "unavailable"
    )
    for item in BOT_ITEMS
    if item.scope == "call"
}
NOT_RAW = (
    "not a file or folder fetch writes in raw/{where} (see the domain's AGENTS.md, Runtime files); "
    "rename it with .rejected"
)
FORMER = "the former layout (until 2026-10-23): rename it with .rejected, then run fetch"
NO_SUBMISSIONS = "no submissions file is in raw/; run fetch"
NO_REPORT = "No season report can be rendered now."
MOVED = (
    "the newest submissions place this filing in the season 2026-03-28, not in this season; rename it with "
    ".rejected and run fetch"
)


def entry(layout, now=NOW, window=WINDOW, refresh=False) -> dict:
    (ticker,) = workflow.plan(layout, [TICKER], now, window, refresh=refresh)["tickers"]
    return ticker


def seasons_of(planned: dict) -> dict[str, dict]:
    return {season["season"]: season for season in planned["seasons"]}


def text_path(layout, role: str) -> Path:
    """A document's text file: ``formatted/INTC/{PERIOD}/{DOC_ID}.md``."""
    return layout.formatted(TICKER) / SEASON_OF[role] / f"{DOC_IDS[role]}.md"


def measures_path(layout, season: str) -> Path:
    return layout.formatted(TICKER) / season / "measures.md"


def report_path(layout, season: str, name: str = REPORT) -> Path:
    return layout.reports(TICKER) / season / name


def rejected(path: Path) -> Path:
    """Withdraw ``path`` as the bot does: rename it with ``.rejected``."""
    return path.rename(path.with_name(f"{path.name}.rejected"))


def rendered(layout) -> None:
    """Fetch, derive, write the window's readings and render each season's report at ``NOW``."""
    research(layout)
    workflow.render(layout, TICKER, NOW)


def form4_xml(issuer: str = CIK) -> bytes:
    """A Form 4 of one officer's sale of ``issuer``'s shares, in the subset ``form4`` reads."""
    return f"""<?xml version="1.0"?>
<ownershipDocument>
<schemaVersion>X0609</schemaVersion>
<documentType>4</documentType>
<periodOfReport>2026-07-01</periodOfReport>
<issuer><issuerCik>{issuer}</issuerCik><issuerTradingSymbol>INTC</issuerTradingSymbol></issuer>
<reportingOwner>
<reportingOwnerId><rptOwnerCik>0001234567</rptOwnerCik><rptOwnerName>Officer Example</rptOwnerName>
</reportingOwnerId>
<reportingOwnerRelationship><isOfficer>1</isOfficer><officerTitle>Chief Financial Officer</officerTitle>
</reportingOwnerRelationship>
</reportingOwner>
<nonDerivativeTable><nonDerivativeTransaction>
<transactionDate><value>2026-07-01</value></transactionDate>
<transactionCoding><transactionFormType>4</transactionFormType><transactionCode>S</transactionCode>
</transactionCoding>
<transactionAmounts><transactionShares><value>1000</value></transactionShares>
<transactionPricePerShare><value>20.50</value></transactionPricePerShare>
<transactionAcquiredDisposedCode><value>D</value></transactionAcquiredDisposedCode></transactionAmounts>
</nonDerivativeTransaction></nonDerivativeTable>
</ownershipDocument>
""".encode()


# --------------------------------------------------------------------------- plan: the state


def test_an_empty_data_directory_plans_a_fetch_and_writes_nothing(layout):
    planned = workflow.plan(layout, [TICKER], NOW, WINDOW)

    assert planned == {
        "generated_at": "2026-10-08T06:00:00-04:00",
        "window": WINDOW_JSON,
        "refresh": False,
        "tickers": [
            {
                "ticker": TICKER,
                "action": "fetch",
                "reason": NO_SUBMISSIONS,
                "cik": None,
                "entity_name": None,
                "submissions": None,
                "companyfacts": None,
                "window": WINDOW_JSON,
                "truncated": None,
                "former_layout": [],
                "invalid_files": [],
                "unlisted_files": [],
                "pending_filings": [],
                "skipped_filings": [],
                "calls": {"events": None, "due": None, "pending_calls": []},
                "seasons": [],
                "stray_files": [],
                "stray_reports": [],
            }
        ],
    }
    assert not layout.root.exists()


def test_a_fetched_window_plans_derive_and_states_each_span_season(layout):
    fetch(layout)

    planned = entry(layout)

    assert planned["action"] == "derive"
    assert planned["reason"] == "15 text files missing or out of date: " + ", ".join(
        DOC_IDS[role] for role in ROLES
    )
    assert (planned["cik"], planned["entity_name"], planned["truncated"]) == (
        "0000050863",
        "INTEL CORP",
        False,
    )
    assert planned["submissions"] == str(layout.raw(TICKER) / SUBMISSIONS)
    assert planned["companyfacts"] == str(layout.raw(TICKER) / COMPANYFACTS)
    assert planned["calls"] == {
        "events": {
            "path": str(layout.raw(TICKER) / CALLS_PAGE),
            "pages": 1,
            "fetched_at": "2026-10-08T05:31:00-04:00",
        },
        "due": None,
        "pending_calls": [],
    }
    assert planned["pending_filings"] == [
        {
            "form": "4",
            "accession": "0001209191-26-061234",
            "dated": "2026-07-30",
            "filed": "2026-08-03",
            "items": "",
        }
    ]
    assert (planned["former_layout"], planned["invalid_files"], planned["unlisted_files"]) == ([], [], [])
    assert (planned["skipped_filings"], planned["stray_files"], planned["stray_reports"]) == ([], [], [])
    seasons = seasons_of(planned)
    assert list(seasons) == SPAN_SEASONS
    assert [season["in_window"] for season in planned["seasons"]] == [False, False, True, True, True]
    assert seasons["2026-06-27"] == {
        "season": "2026-06-27",
        "in_window": True,
        "filing": {
            "form": "10-Q",
            "accession": "0000050863-26-000064",
            "filed": "2026-07-24",
            "period": "2026-06-27",
            "doc_id": DOC_IDS["ten_q_2"],
            "raw": True,
        },
        "filings": [
            {
                "form": "8-K",
                "accession": "0000050863-26-000062",
                "dated": "2026-07-23",
                "filed": "2026-07-23",
                "items": "2.02,9.01",
                "raw": True,
            }
        ],
        "listed_only": [],
        "documents": "complete",
        "call": {
            "status": "transcript",
            "due": "2026-07-23",
            "as_of": "2026-10-08",
            "calls": [{"id": CALL_Q2.id, "date": "2026-07-23", "fiscal_year": 2026, "fiscal_quarter": 2}],
            "documents": [DOC_IDS["call_q2"]],
            "reason": None,
        },
        "texts": {
            "documents": 5,
            "stale": [
                DOC_IDS[role] for role in ("ten_q_2", "eight_k_2", "exhibit_2_1", "exhibit_2_2", "call_q2")
            ],
        },
        "companyfacts": {"status": "present", "reason": None},
        "measures": {"path": str(measures_path(layout, "2026-06-27")), "status": "missing"},
        "readings": {"path": str(readings_file(layout, Q2)), "status": "missing", "problems": 0},
        "report": {"path": None, "status": "missing"},
    }


def test_the_fiscal_years_season_holds_its_8_k_and_proxy_statement_and_shows_its_call_unavailable(layout):
    fetch(layout)

    season = seasons_of(entry(layout))["2025-12-27"]

    assert season["filings"] == [
        {
            "form": "8-K",
            "accession": "0000050863-26-000020",
            "dated": "2026-02-09",
            "filed": "2026-02-10",
            "items": "5.02,9.01",
            "raw": True,
        },
        {  # a proxy statement is dated by its filing date
            "form": "DEF 14A",
            "accession": "0001193125-26-112233",
            "dated": "2026-03-27",
            "filed": "2026-03-27",
            "items": "",
            "raw": True,
        },
    ]
    assert season["call"] == {
        "status": "unavailable",
        "due": "2026-01-30",  # no earnings release: the 10-K's filing date
        "as_of": "2026-10-08",
        "calls": [],
        "documents": [],
        "reason": None,
    }
    assert season["texts"] == {
        "documents": 3,
        "stale": [DOC_IDS["ten_k"], DOC_IDS["eight_k_other"], DOC_IDS["proxy"]],
    }


def test_the_seasons_before_the_window_carry_no_measures_readings_or_report(layout):
    fetch(layout)

    seasons = seasons_of(entry(layout))

    for day in ("2024-12-28", "2025-09-27"):
        assert not {"measures", "readings", "report"} & set(seasons[day])
    # The company facts hold no fact of the oldest 10-K, fetched long after it: never asked for again.
    assert seasons["2024-12-28"]["companyfacts"] == {
        "status": "absent",
        "reason": "EDGAR's companyfacts, fetched 2026-10-08, holds no fact of the 10-K 0000050863-25-000009",
    }
    assert seasons["2025-09-27"]["call"]["documents"] == [DOC_IDS["call_old_q"]]


def test_the_default_window_holds_every_listed_season_and_is_truncated(layout):
    fetch(layout)

    planned = entry(layout, window=DEFAULT_WINDOW)

    assert planned["truncated"] is True  # it starts before the oldest filing filings.recent lists
    assert [season["in_window"] for season in planned["seasons"]] == [True] * 5
    assert planned["action"] == "derive"


# --------------------------------------------------------------------------- plan: fetch


@pytest.mark.parametrize(
    ("submissions", "reason"),
    [
        pytest.param(None, NO_SUBMISSIONS, id="no-submissions"),
        pytest.param(
            "{}",
            f"{SUBMISSIONS} is invalid (see invalid_files); rename it with .rejected and run fetch",
            id="invalid-submissions",
        ),
        pytest.param(
            submissions_json(rows=(PROXY,)),
            "no 10-K or 10-Q among the 1 recent filings; forms seen: DEF 14A",
            id="no-periodic-filing",
        ),
        pytest.param(
            submissions_json(
                rows=(Row("8-K", "0000050863-26-000099", date(2026, 7, 23), None, "x.htm", "2.02"), TEN_Q_2)
            ),
            "submissions CIK0000050863: filings.recent.reportDate[0] is empty; an 8-K with Item 2.02 must "
            "name its event date",
            id="undated-release",
        ),
    ],
)
def test_without_a_listed_season_plan_says_fetch_and_the_offline_commands_refuse(layout, submissions, reason):
    if submissions is not None:
        place(layout.raw(TICKER) / SUBMISSIONS, submissions)

    planned = entry(layout)

    assert (planned["action"], planned["reason"], planned["seasons"]) == ("fetch", reason, [])
    for command in (workflow.derive, workflow.check, workflow.render):
        with pytest.raises(ValueError) as raised:
            command(layout, TICKER, NOW)
        assert str(raised.value) == f"{TICKER}: {reason}"
    assert workflow.show(layout, [TICKER], NOW) == (f"{TICKER}: action fetch: {reason}.\n\n{NO_REPORT}\n")


def test_an_invalid_submissions_file_is_listed_with_why(layout):
    path = place(layout.raw(TICKER) / SUBMISSIONS, "{}")

    planned = entry(layout)

    assert planned["invalid_files"] == [
        {"path": str(path), "reason": "submissions: cik must be a string of up to ten digits or an integer"}
    ]


@pytest.mark.parametrize(
    ("role", "what"),
    [
        pytest.param("ten_q_2", "10-Q 0000050863-26-000064 for the period ended 2026-06-27", id="10-Q"),
        pytest.param(
            "old_ten_q", "10-Q 0000050863-25-000201 for the period ended 2025-09-27", id="span-10-Q"
        ),
        pytest.param(
            "index_2", "filing index page of the 8-K 0000050863-26-000062 dated 2026-07-23", id="index"
        ),
        pytest.param(
            "eight_k_2", "primary document of the 8-K 0000050863-26-000062 dated 2026-07-23", id="8-K"
        ),
        pytest.param(
            "exhibit_2_2",
            "EX-99.2 q226cfocommentary.htm of the 8-K 0000050863-26-000062 dated 2026-07-23",
            id="exhibit",
        ),
        pytest.param(
            "proxy", "primary document of the DEF 14A 0001193125-26-112233 filed 2026-03-27", id="proxy"
        ),
    ],
)
def test_a_span_document_not_in_raw_plans_a_fetch(layout, role, what):
    fetch(layout)
    path = raw_file(layout, role)
    path.unlink()

    planned = entry(layout)

    reason = f"the {what} is not in raw/ ({path}); run fetch"
    assert (planned["action"], planned["reason"]) == ("fetch", reason)
    assert seasons_of(planned)[RAW[role].split("/")[0]]["documents"] == reason


def test_a_filing_not_in_raw_is_flagged_in_its_season(layout):
    fetch(layout)
    raw_file(layout, "eight_k_other").unlink()
    raw_file(layout, "ten_q_1").unlink()

    seasons = seasons_of(entry(layout))

    assert [item["raw"] for item in seasons["2025-12-27"]["filings"]] == [False, True]
    assert seasons["2026-03-28"]["filing"]["raw"] is False
    assert seasons["2026-03-28"]["texts"]["documents"] == 3  # the 8-K, its exhibit and the call


def test_the_former_layout_plans_a_fetch_and_refuses_derive_check_render_and_show(layout):
    rendered(layout)
    edgar_folder, calls_folder = plant_former_layout(layout)

    planned = entry(layout, LATER)

    assert planned["former_layout"] == [str(calls_folder), str(edgar_folder)]
    assert (planned["action"], planned["reason"]) == (
        "fetch",
        f"{calls_folder} is {FORMER}; 1 other folder too (see former_layout)",
    )
    assert {season["report"]["status"] for season in planned["seasons"] if season["in_window"]} == {"stale"}
    for command in (workflow.derive, workflow.check, workflow.render):
        with pytest.raises(ValueError) as raised:
            command(layout, TICKER, LATER)
        assert str(raised.value) == f"{TICKER}: {calls_folder} is {FORMER}"
    assert f"\n\n{NO_REPORT}\n" in workflow.show(layout, [TICKER], LATER)

    rejected(calls_folder)
    rejected(edgar_folder)
    assert entry(layout, LATER)["action"] == "reuse"


def plant_top(layout) -> tuple[Path, str]:
    return place(layout.raw(TICKER) / "notes.txt", "notes\n"), NOT_RAW.format(where="")


def plant_in_season(layout) -> tuple[Path, str]:
    return place(layout.raw(TICKER) / "2026-06-27/notes.txt", "notes\n"), NOT_RAW.format(where="2026-06-27/")


def plant_unlisted_season(layout) -> tuple[Path, str]:
    folder = place(layout.raw(TICKER) / "2026-01-15/notes.txt", "notes\n").parent
    return folder, "no season of the newest submissions ends on this date; rename it with .rejected"


def plant_symbolic_link(layout) -> tuple[Path, str]:
    link = layout.raw(TICKER) / "2026-06-27/transcript_248001.json"
    target = rejected(link)
    link.symlink_to(target)
    return link, "not a regular file"


@pytest.mark.parametrize(
    "plant",
    [
        pytest.param(plant_top, id="top"),
        pytest.param(plant_in_season, id="season"),
        pytest.param(plant_unlisted_season, id="unlisted-season"),
        pytest.param(plant_symbolic_link, id="symbolic-link"),
    ],
)
def test_an_invalid_raw_entry_plans_a_fetch_and_refuses_derive_check_and_render(layout, plant):
    rendered(layout)
    path, reason = plant(layout)

    planned = entry(layout, LATER)

    assert planned["invalid_files"] == [{"path": str(path), "reason": reason}]
    assert planned["action"] == "fetch"
    message = (
        f"{TICKER}: 1 file in raw/ failed validation; first: {path}: {reason}; run plan for the list and "
        "rename each with .rejected"
    )
    for command in (workflow.derive, workflow.check, workflow.render):
        with pytest.raises(ValueError) as raised:
            command(layout, TICKER, LATER)
        assert str(raised.value) == message


def test_a_file_where_a_filings_folder_belongs_is_listed_once(layout):
    rendered(layout)
    folder = raw_file(layout, "index_2").parent
    rejected(folder)
    place(folder, "<html></html>")

    planned = entry(layout, LATER)

    assert planned["invalid_files"] == [
        {
            "path": str(folder),
            "reason": "not a folder: a filing's or a season's documents belong in a folder of this name",
        }
    ]
    assert (planned["action"], planned["reason"]) == (
        "fetch",
        "the filing index page of the 8-K 0000050863-26-000062 dated 2026-07-23 in raw/ is invalid (see "
        "invalid_files); rename it with .rejected and run fetch",
    )


def test_a_stray_raw_file_names_itself_in_the_reason_and_withdrawing_it_restores_the_plan(layout):
    rendered(layout)
    stray = place(layout.raw(TICKER) / "notes.txt", "notes\n")
    reason = NOT_RAW.format(where="")

    planned = entry(layout, LATER)

    assert planned["invalid_files"] == [{"path": str(stray), "reason": reason}]
    assert planned["reason"] == (
        f"1 raw file failed validation (first: {stray}: {reason}); rename each with .rejected, then run fetch"
    )
    with pytest.raises(ValueError) as raised:
        workflow.render(layout, TICKER, LATER)
    assert str(raised.value) == (
        f"{TICKER}: 1 file in raw/ failed validation; first: {stray}: {reason}; run plan for the list and "
        "rename each with .rejected"
    )

    rejected(stray)
    assert entry(layout, LATER)["action"] == "reuse"


def test_an_index_page_that_does_not_parse_is_invalid_and_plans_a_fetch(layout):
    research(layout)
    index = place(raw_file(layout, "index_1"), "<html>no table</html>")

    planned = entry(layout)

    reason = 'filing index 0000050863-26-000040: no tableFile table with the summary "Document Format Files"'
    assert planned["invalid_files"] == [{"path": str(index), "reason": reason}]
    assert planned["action"] == "fetch"


def test_an_8_k_whose_index_page_does_not_parse_leaves_its_season_incomplete(layout):
    research(layout)
    place(raw_file(layout, "index_1"), "<html>no table</html>")

    planned = entry(layout)

    # Its exhibits are unknown: the season cannot hold all its documents.
    reason = (
        "the filing index page of the 8-K 0000050863-26-000040 dated 2026-04-23 in raw/ is invalid (see "
        "invalid_files); rename it with .rejected and run fetch"
    )
    assert (planned["action"], planned["reason"]) == ("fetch", reason)
    q1 = seasons_of(planned)["2026-03-28"]
    assert (q1["documents"], q1["filings"][0]["raw"]) == (reason, False)


def test_a_season_listed_late_reports_the_filing_and_call_it_takes_as_moved(layout):
    # On 2026-10-01 EDGAR does not list the 10-Q for the quarter ended 2026-03-28 yet: Rule B places
    # the earnings release and the call of 2026-04-23 in the season ended 2025-12-27.
    early = edt(2026, 10, 1, 6, 0)
    without = tuple(row for row in RECENT if row is not TEN_Q_1)
    fetch(layout, edgar(rows=without), start=early, calls_start=early + timedelta(minutes=1), now=early)
    moved_filing = layout.raw(TICKER) / "2025-12-27/8-K_2026-04-23_0000050863-26-000040"
    moved_call = layout.raw(TICKER) / "2025-12-27/transcript_26083.json"
    assert moved_filing.is_dir() and moved_call.is_file()

    fetch(layout)  # the listing of 2026-10-08 holds it: fetch writes both in their season

    planned = entry(layout)
    assert planned["invalid_files"] == [
        {
            "path": str(moved_filing),
            "reason": MOVED,
        },
        {
            "path": str(moved_call),
            "reason": "the newest calls list places this call in the season 2026-03-28, not in this season; "
            "rename it with .rejected and run fetch",
        },
    ]
    assert planned["action"] == "fetch"
    assert planned["reason"] == (
        f"2 raw files failed validation (first: {moved_filing}: {MOVED}); rename each with .rejected, then "
        "run fetch"
    )
    assert raw_file(layout, "exhibit_1").is_file() and raw_file(layout, "transcript_q1").is_file()

    rejected(moved_filing)
    rejected(moved_call)
    assert entry(layout)["action"] == "derive"


def test_a_window_season_without_company_facts_plans_a_fetch(layout):
    research(layout)
    rejected(layout.raw(TICKER) / COMPANYFACTS)

    planned = entry(layout)

    reason = "no companyfacts file is in raw/; run fetch"
    assert (planned["action"], planned["reason"], planned["companyfacts"]) == ("fetch", reason, None)
    assert {season["companyfacts"]["status"] for season in planned["seasons"]} == {"missing"}


def without_ten_q_2() -> str:
    """INTC's company facts without any fact of the 10-Q for the quarter ended 2026-06-27."""
    document = companyfacts_document()
    for concept in document["facts"]["us-gaap"].values():
        for unit, entries in concept["units"].items():
            concept["units"][unit] = [fact for fact in entries if fact["accn"] != TEN_Q_2.accession]
    return json.dumps(document)


def test_company_facts_fetched_by_the_filing_date_without_it_are_waiting_and_block_nothing(layout):
    research(layout)
    rejected(layout.raw(TICKER) / COMPANYFACTS)
    place(layout.raw(TICKER) / "companyfacts_20260724T180000EDT.json", without_ten_q_2())

    planned = entry(layout)

    reason = (
        "the newest companyfacts, fetched 2026-07-24, on or before the 10-Q 0000050863-26-000064 was "
        "filed, holds no fact of it: a later fetch brings them"
    )
    assert seasons_of(planned)["2026-06-27"]["companyfacts"] == {"status": "waiting", "reason": reason}
    assert seasons_of(planned)["2026-03-28"]["companyfacts"] == {"status": "present", "reason": None}
    # Every fetch asks for the facts again; the season's figures wait for them, and nothing else does.
    assert (planned["action"], planned["reason"]) == (
        "derive",
        "measures.md missing or out of date for: 2025-12-27, 2026-03-28, 2026-06-27",
    )


def test_company_facts_fetched_after_the_filing_date_without_it_leave_it_absent(layout):
    research(layout)
    place(layout.raw(TICKER) / "companyfacts_20261008T055000EDT.json", without_ten_q_2())

    planned = entry(layout)

    assert seasons_of(planned)["2026-06-27"]["companyfacts"] == {
        "status": "absent",
        "reason": "EDGAR's companyfacts, fetched 2026-10-08, holds no fact of the 10-Q 0000050863-26-000064",
    }
    # Not asked for again: the newer facts change every window season's measures.md.
    assert (planned["action"], planned["reason"]) == (
        "derive",
        "measures.md missing or out of date for: 2025-12-27, 2026-03-28, 2026-06-27",
    )


def test_a_window_calls_transcript_not_in_raw_plans_a_fetch(layout):
    research(layout)
    transcript = raw_file(layout, "transcript_q2")
    transcript.unlink()

    planned = entry(layout)

    reason = f"the transcript of the call 248001 (2026-07-23) is not in raw/ ({transcript}); run fetch"
    assert (planned["action"], planned["reason"]) == ("fetch", reason)
    q2 = seasons_of(planned)["2026-06-27"]
    assert (q2["call"]["status"], q2["call"]["reason"], q2["call"]["documents"]) == ("missing", reason, [])
    assert q2["texts"]["documents"] == 4
    assert q2["report"] == {"path": None, "status": "missing"}


def test_an_invalid_transcript_is_withdrawn_then_fetched_again(layout):
    rendered(layout)
    transcript = place(raw_file(layout, "transcript_q2"), b"{}")

    planned = entry(layout, LATER)

    reason = "transcript: data: Field required"
    assert planned["invalid_files"] == [{"path": str(transcript), "reason": reason}]
    assert (planned["action"], planned["reason"]) == (
        "fetch",
        f"1 raw file failed validation (first: {transcript}: {reason}); rename each with .rejected, then run "
        "fetch",
    )
    call = seasons_of(planned)["2026-06-27"]["call"]
    assert (call["status"], call["reason"]) == (
        "missing",
        "the transcript of the call 248001 (2026-07-23) in raw/ is invalid (see invalid_files); rename it "
        "with .rejected and run fetch",
    )

    rejected(transcript)
    assert entry(layout, LATER)["reason"] == (
        f"the transcript of the call 248001 (2026-07-23) is not in raw/ ({transcript}); run fetch"
    )

    again = edt(2026, 10, 8, 7, 30)
    output = fetch(layout, start=again, calls_start=again + timedelta(minutes=1), now=again)

    assert output["transcript_requests"] == 1
    assert transcript.read_bytes() == raw_bytes("transcript_q2")
    # The same transcript: its text, the season's measures and its report stand.
    assert entry(layout, edt(2026, 10, 8, 8, 0))["action"] == "reuse"


def test_without_a_calls_list_the_plan_is_a_fetch(layout):
    research(layout)
    (layout.raw(TICKER) / CALLS_PAGE).unlink()

    planned = entry(layout)

    reason = "no calls list from EarningsCalls.dev is in raw/; run fetch"
    assert (planned["action"], planned["reason"], planned["calls"]) == (
        "fetch",
        reason,
        {"events": None, "due": reason, "pending_calls": []},
    )
    assert {season["call"]["status"] for season in planned["seasons"]} == {"missing"}


def test_a_calls_list_seven_days_old_is_asked_for_again_while_a_season_lists_no_call(layout):
    rendered(layout)

    assert entry(layout, edt(2026, 10, 15, 5, 30, 59))["action"] == "reuse"
    planned = entry(layout, edt(2026, 10, 15, 5, 31))

    due = (
        "the newest calls list, fetched 2026-10-08, is 7 days old or more and lists no call for the season "
        "2025-12-27"
    )
    assert (planned["action"], planned["reason"], planned["calls"]["due"]) == ("fetch", due, due)


def test_a_calls_list_fetched_by_a_seasons_due_date_is_asked_for_again_once_it_passes(layout):
    # The day the 10-K was filed: no release in its season, so its call is due by that date.
    filed = edt(2026, 1, 30, 12, 0)
    page = events_page([call_row(CALL_OLD_Q), call_row(CALL_DROPPED)])
    fetch(
        layout,
        edgar(rows=(TEN_K, OLD_TEN_Q, OLD_TEN_K)),
        calls=provider(page, (CALL_OLD_Q,)),
        start=filed,
        calls_start=filed + timedelta(minutes=1),
        now=filed,
    )
    window = Window(date(2025, 12, 1), date(2026, 1, 31))

    same_day = entry(layout, edt(2026, 1, 30, 13, 0), window)
    next_day = entry(layout, edt(2026, 1, 31, 6, 0), window)

    assert same_day["action"] == "derive"
    assert seasons_of(same_day)["2025-12-27"]["call"] == {
        "status": "waiting",
        "due": "2026-01-30",
        "as_of": "2026-01-30",
        "calls": [],
        "documents": [],
        "reason": "EarningsCalls.dev lists no call for the season as of 2026-01-30; a list fetched on or "
        "after 2026-02-06 that lists none shows it unavailable",
    }
    due = (
        "the newest calls list was fetched 2026-01-30, on or before the season 2025-12-27's due date "
        "2026-01-30"
    )
    assert (next_day["action"], next_day["reason"], next_day["calls"]["due"]) == ("fetch", due, due)


def test_plan_with_refresh_plans_a_fetch_while_the_window_holds_a_listed_season(layout):
    rendered(layout)
    assert workflow.plan(layout, [TICKER], LATER, WINDOW)["refresh"] is False

    planned = workflow.plan(layout, [TICKER], LATER, WINDOW, refresh=True)

    assert planned["refresh"] is True
    (ticker,) = planned["tickers"]
    reason = "--refresh: the span's documents, transcripts and calls list are requested again"
    assert reason == workflow.REFRESH_REASON
    assert (ticker["action"], ticker["reason"], ticker["calls"]["due"]) == ("fetch", reason, reason)
    # A window without a listed season has nothing to request again.
    later = entry(layout, LATER, Window(date(2026, 6, 28), TODAY), refresh=True)
    assert (later["action"], later["calls"]["due"], later["seasons"]) == ("reuse", None, [])
    # A reason that applies without --refresh comes first.
    transcript = raw_file(layout, "transcript_q2")
    transcript.unlink()
    missing = entry(layout, LATER, refresh=True)
    assert (missing["action"], missing["reason"]) == (
        "fetch",
        f"the transcript of the call 248001 (2026-07-23) is not in raw/ ({transcript}); run fetch",
    )


# --------------------------------------------------------------------------- plan: derive to reuse


def test_a_text_of_a_span_season_missing_or_out_of_date_plans_derive(layout):
    rendered(layout)
    text_path(layout, "old_ten_q").unlink()  # a season before the window: its baselines need it
    place(text_path(layout, "call_q2"), "edited\n")

    planned = entry(layout, LATER)

    assert (planned["action"], planned["reason"]) == (
        "derive",
        f"2 text files missing or out of date: {DOC_IDS['old_ten_q']}, {DOC_IDS['call_q2']}",
    )
    assert seasons_of(planned)["2025-09-27"]["texts"]["stale"] == [DOC_IDS["old_ten_q"]]
    q2 = seasons_of(planned)["2026-06-27"]
    assert q2["texts"]["stale"] == [DOC_IDS["call_q2"]]
    assert q2["report"]["status"] == "stale"


def test_a_window_seasons_measures_missing_or_out_of_date_plan_derive(layout):
    rendered(layout)
    measures_path(layout, "2025-12-27").unlink()
    place(measures_path(layout, "2026-06-27"), "edited\n")
    measures_path(layout, "2025-09-27").unlink()  # before the window: never needed for a report

    planned = entry(layout, LATER)

    assert (planned["action"], planned["reason"]) == (
        "derive",
        "measures.md missing or out of date for: 2025-12-27, 2026-06-27",
    )
    seasons = seasons_of(planned)
    assert seasons["2025-12-27"]["measures"]["status"] == "missing"
    assert seasons["2026-06-27"]["measures"] == {
        "path": str(measures_path(layout, "2026-06-27")),
        "status": "stale",
    }
    assert seasons["2026-03-28"]["measures"]["status"] == "fresh"


def test_readings_missing_or_failing_plan_research(layout):
    fetch(layout)
    workflow.derive(layout, TICKER, NOW)
    planned = entry(layout)
    assert (planned["action"], planned["reason"]) == (
        "research",
        "readings missing or failing check: 2025-12-27 (missing), 2026-03-28 (missing), 2026-06-27 (missing)",
    )

    write_readings(layout, date(2025, 12, 27))
    write_readings(layout, Q1)
    two = readings_text(Q2, i3_3=Reading(DOC_IDS["ten_q_1"], "none", "A rule broken twice in one item."))
    write_readings(layout, Q2, two.replace("new: A rule", "new: A buy rule"))

    planned = entry(layout)

    assert (planned["action"], planned["reason"]) == (
        "research",
        "readings missing or failing check: 2026-06-27 (failing, 2 problems)",
    )
    assert seasons_of(planned)["2026-06-27"]["readings"] == {
        "path": str(readings_file(layout, Q2)),
        "status": "failing",
        "problems": 2,
    }
    assert seasons_of(planned)["2026-03-28"]["readings"]["status"] == "valid"


def test_a_failing_readings_reason_counts_one_problem_in_the_singular(layout):
    research(layout)
    write_readings(layout, Q2, readings_text(Q2, i3_3=Reading(DOC_IDS["ten_q_1"], "none", "No quote.")))

    planned = entry(layout)

    assert planned["reason"] == "readings missing or failing check: 2026-06-27 (failing, 1 problem)"


def test_passing_readings_lead_to_render_then_reuse(layout):
    research(layout)

    planned = entry(layout)

    assert (planned["action"], planned["reason"]) == (
        "render",
        "no current report for: 2025-12-27, 2026-03-28, 2026-06-27",
    )
    for season in planned["seasons"][2:]:
        assert (season["measures"]["status"], season["readings"]["status"]) == ("fresh", "valid")
        assert season["report"] == {"path": None, "status": "missing"}

    workflow.render(layout, TICKER, NOW)
    planned = entry(layout, LATER)

    assert (planned["action"], planned["reason"]) == ("reuse", None)
    assert [season["report"] for season in planned["seasons"][2:]] == [
        {"path": str(report_path(layout, day)), "status": "fresh"} for day in WINDOW_SEASONS
    ]


def test_readings_changed_after_the_render_make_the_report_stale(layout):
    rendered(layout)
    write_readings(
        layout,
        Q2,
        readings_text(Q2, i1_1=Reading(DOC_IDS["exhibit_1"], "not disclosed", "not disclosed")),
    )

    planned = entry(layout, LATER)

    assert (planned["action"], planned["reason"]) == ("render", "no current report for: 2026-06-27")
    assert seasons_of(planned)["2026-06-27"]["report"] == {
        "path": str(report_path(layout, "2026-06-27")),
        "status": "stale",
    }


def test_a_report_named_after_now_is_not_read_yet(layout):
    research(layout)
    workflow.render(layout, TICKER, LATER)

    planned = entry(layout, NOW)

    assert planned["action"] == "render"
    assert {season["report"]["status"] for season in planned["seasons"][2:]} == {"missing"}


def test_a_waiting_call_blocks_nothing_and_its_transcript_later_makes_the_report_stale(layout):
    # The run of 2026-07-27: the calls list does not hold the call of 2026-07-23 yet.
    morning = edt(2026, 7, 27, 6, 0)
    page = events_page([call_row(call) for call in (CALL_Q1, CALL_OLD_Q, CALL_DROPPED)])
    fetch(
        layout,
        edgar(rows=RECENT[1:]),  # the Form 4 of 2026-08-03 is not filed yet
        calls=provider(page, (CALL_OLD_Q, CALL_Q1)),
        start=morning,
        calls_start=morning + timedelta(minutes=1),
        now=morning,
    )
    later = edt(2026, 7, 27, 7, 0)
    planned = entry(layout, later)

    assert planned["action"] == "derive"  # the list is not asked for again before 2026-08-03
    assert seasons_of(planned)["2026-06-27"]["call"] == {
        "status": "waiting",
        "due": "2026-07-23",
        "as_of": "2026-07-27",
        "calls": [],
        "documents": [],
        "reason": "EarningsCalls.dev lists no call for the season as of 2026-07-27; a list fetched on or "
        "after 2026-07-30 that lists none shows it unavailable",
    }

    workflow.derive(layout, TICKER, later)
    write_readings(layout, Q2, readings_text(Q2, **UNAVAILABLE))
    assert workflow.check(layout, TICKER, later)["readings"][0]["valid"] is True
    output = workflow.render(layout, TICKER, later)

    path = report_path(layout, "2026-06-27", "report_20260727T070000EDT.md")
    assert output == {
        "ticker": TICKER,
        "reports": [{"season": "2026-06-27", "path": str(path)}],
        "current": [],
        "skipped": [],
    }
    lines = path.read_text(encoding="utf-8").split("\n")
    assert lines[4].endswith(" Call: waiting as of the calls list of 2026-07-27.")
    analysts = (
        "| low | 8.5 Analysts on the call · distinct analysts asking questions | previous quarter 2026-03-28 "
        "(10-Q) | unavailable | unavailable | — |"
    )
    assert analysts in lines
    assert "note: the call has no transcript in raw/ (waiting)" in lines
    opening = (
        "| medium | 7.1 Opening topics | previous quarter 2026-03-28 (10-Q) | unavailable | unavailable | — |"
    )
    assert opening in lines
    assert "| high | 7.4 Statement against the filing | none | — | unavailable | — |" in lines
    assert seasons_of(entry(layout, edt(2026, 7, 27, 8, 0)))["2026-06-27"]["report"]["status"] == "fresh"

    # A week later the list is asked for again and holds the call: the report no longer stands.
    week = edt(2026, 8, 3, 7, 0)
    assert entry(layout, week)["action"] == "fetch"
    fetch(layout, edgar(rows=RECENT[1:]), start=week, calls_start=week + timedelta(minutes=1), now=week)
    after = edt(2026, 8, 3, 8, 0)

    planned = entry(layout, after)

    assert (planned["action"], planned["reason"]) == (
        "derive",
        f"1 text file missing or out of date: {DOC_IDS['call_q2']}",
    )
    q2 = seasons_of(planned)["2026-06-27"]
    assert (q2["call"]["status"], q2["measures"]["status"], q2["report"]["status"]) == (
        "transcript",
        "stale",
        "stale",
    )
    workflow.derive(layout, TICKER, after)
    q2 = seasons_of(entry(layout, after))["2026-06-27"]
    # Each call item's 'unavailable' is refused: on both lines of the seven with a baseline, on 7.4's new.
    assert q2["readings"] == {"path": str(readings_file(layout, Q2)), "status": "failing", "problems": 15}
    assert q2["report"]["status"] == "stale"


# --------------------------------------------------------------------------- plan: what is left out


def test_pending_filings_and_calls_are_listed_when_the_window_reaches_the_newest_season(layout):
    page = events_page([call_row(call) for call in (CALL_Q3, *CALLS)])
    fetch(layout, calls=provider(page, CALLS_OF_SEASONS))  # the call of 2026-10-06 is never requested

    planned = entry(layout)
    earlier = entry(layout, window=Window(date(2025, 12, 1), date(2026, 6, 26)))

    assert planned["pending_filings"] == [
        {
            "form": "4",
            "accession": "0001209191-26-061234",
            "dated": "2026-07-30",
            "filed": "2026-08-03",
            "items": "",
        }
    ]
    assert planned["calls"]["pending_calls"] == [
        {"id": CALL_Q3.id, "date": "2026-10-06", "fiscal_year": 2026, "fiscal_quarter": 3}
    ]
    assert (earlier["pending_filings"], earlier["calls"]["pending_calls"]) == ([], [])


def test_rows_rule_b_cannot_place_or_fetch_cannot_request_are_listed_as_skipped(layout):
    rows = (
        Row("4", "0001209191-26-050002", date(2026, 7, 2), None, "xslF345X05/form4.xml"),
        Row("8-K", "0000050863-26-000070", date(2026, 8, 1), None, "intc-20260801.htm", "8.01"),
        Row("SC 13G/A", "0000950103-26-000001", date(2026, 2, 12), None, "a/b/c.htm"),
    )
    fetch(layout, edgar(rows=(*rows, *RECENT)))

    planned = entry(layout)

    assert planned["skipped_filings"] == [
        {
            "form": "4",
            "accession": "0001209191-26-050002",
            "filed": "2026-07-02",
            "reason": "its reportDate is empty",
        },
        {
            "form": "8-K",
            "accession": "0000050863-26-000070",
            "filed": "2026-08-01",
            "reason": "its reportDate is empty",
        },
        {
            "form": "SC 13G/A",
            "accession": "0000950103-26-000001",
            "filed": "2026-02-12",
            "reason": "its primaryDocument is no file fetch can request",
        },
    ]
    assert planned["action"] == "derive"


def test_forms_listed_only_appear_in_their_season_and_are_never_requested(layout):
    rows = (
        Row("S-3ASR", "0001193125-26-200001", date(2026, 5, 1), None, "d200001ds3asr.htm"),
        Row("424B5", "0001193125-26-200002", date(2026, 5, 4), None, "d200002d424b5.htm"),
        Row("NT 10-Q", "0000950170-26-000003", date(2026, 5, 8), None, "nt10q.htm"),
        Row(
            "8-K/A", "0000050863-26-000045", date(2026, 5, 2), date(2026, 4, 23), "intc-20260423a.htm", "2.02"
        ),
    )
    output = fetch(layout, edgar(rows=(*rows, *RECENT)))  # the fake EDGAR serves none of them

    seasons = seasons_of(entry(layout))

    assert output["tickers"][0]["status"] == "fetched"
    assert seasons["2026-03-28"]["listed_only"] == [  # dated by their filing date, an amendment too
        {
            "form": "S-3ASR",
            "accession": "0001193125-26-200001",
            "dated": "2026-05-01",
            "filed": "2026-05-01",
            "items": "",
        },
        {
            "form": "8-K/A",
            "accession": "0000050863-26-000045",
            "dated": "2026-05-02",
            "filed": "2026-05-02",
            "items": "2.02",
        },
        {
            "form": "424B5",
            "accession": "0001193125-26-200002",
            "dated": "2026-05-04",
            "filed": "2026-05-04",
            "items": "",
        },
        {
            "form": "NT 10-Q",
            "accession": "0000950170-26-000003",
            "dated": "2026-05-08",
            "filed": "2026-05-08",
            "items": "",
        },
    ]
    assert [item["form"] for item in seasons["2026-03-28"]["filings"]] == ["8-K"]
    assert all(season["listed_only"] == [] for day, season in seasons.items() if day != "2026-03-28")


def test_unlisted_filing_folders_and_transcripts_are_named_and_block_nothing(layout):
    rendered(layout)
    folder = place(
        layout.raw(TICKER) / "2026-06-27/8-K_2026-07-01_0000050863-26-099999/x.htm", "<p>x</p>"
    ).parent
    transcript = place(layout.raw(TICKER) / "2026-06-27/transcript_999.json", b"{}")

    planned = entry(layout, LATER)

    assert planned["unlisted_files"] == [str(folder), str(transcript)]
    assert (planned["action"], planned["invalid_files"]) == ("reuse", [])


def test_a_form_4_counts_in_raw_only_once_its_xml_reads(layout):
    rendered(layout)
    # A newer listing holds a Form 4 dated in the season ended 2026-06-27, before its 10-Q was filed.
    form4 = Row("4", "0001209191-26-050001", date(2026, 7, 2), date(2026, 7, 1), "xslF345X05/form4.xml")
    place(layout.raw(TICKER) / "submissions_20261008T055000EDT.json", submissions_json(rows=(form4, *RECENT)))
    xml = layout.raw(TICKER) / "2026-06-27/4_2026-07-01_0001209191-26-050001/form4.xml"

    planned = entry(layout, LATER)

    what = "XML of the Form 4 0001209191-26-050001 dated 2026-07-01"
    assert (planned["action"], planned["reason"]) == (
        "fetch",
        f"the {what} is not in raw/ ({xml}); run fetch",
    )
    assert [(item["form"], item["raw"]) for item in seasons_of(planned)["2026-06-27"]["filings"]] == [
        ("4", False),
        ("8-K", True),
    ]

    place(xml, form4_xml())
    planned = entry(layout, LATER)
    assert [item["raw"] for item in seasons_of(planned)["2026-06-27"]["filings"]] == [True, True]
    assert (planned["action"], planned["reason"]) == (
        "derive",
        "measures.md missing or out of date for: 2026-06-27",
    )
    assert seasons_of(planned)["2026-06-27"]["texts"]["documents"] == 5  # a Form 4 is never quoted

    place(xml, b"<ownershipDocument>")
    planned = entry(layout, LATER)
    assert [item["path"] for item in planned["invalid_files"]] == [str(xml)]
    assert (planned["action"], planned["reason"]) == (
        "fetch",
        f"the {what} in raw/ is invalid (see invalid_files); rename it with .rejected and run fetch",
    )


def test_stray_formatted_and_report_files_are_listed_and_block_nothing(layout):
    rendered(layout)
    text = place(layout.formatted(TICKER) / f"{DOC_IDS['ten_q_2']}.md", "former text\n")
    series = place(layout.reports(TICKER) / f"{TICKER}_2026-07-24_20261008T060000EDT.md", "# former series\n")
    place(layout.reports(TICKER) / ".DS_Store", b"\0")

    planned = entry(layout, LATER)
    derived = workflow.derive(layout, TICKER, LATER)

    assert (planned["stray_files"], planned["stray_reports"]) == ([str(text)], [str(series)])
    assert (derived["stray_files"], derived["stray_reports"]) == ([str(text)], [str(series)])
    assert planned["action"] == "reuse"
    assert text.read_text(encoding="utf-8") == "former text\n"  # left for the bot to delete


def test_a_season_the_newest_submissions_no_longer_list_is_left_out(layout):
    rendered(layout)
    # EDGAR's filings.recent has moved on: the 10-K for the fiscal year ended 2024-12-28 is gone.
    rows = tuple(row for row in RECENT if row is not OLD_TEN_K)
    place(layout.raw(TICKER) / "submissions_20261008T055000EDT.json", submissions_json(rows=rows))

    planned = entry(layout, LATER)

    assert planned["invalid_files"] == []  # its folder is older than every listed season
    assert list(seasons_of(planned)) == SPAN_SEASONS[1:]
    assert planned["action"] == "derive"  # the seasons its baselines named are measured anew
    workflow.derive(layout, TICKER, LATER)
    planned = entry(layout, LATER)
    # The fiscal year ended 2025-12-27 lost its baselines of a year ago: its readings name them.
    assert planned["action"] == "research"
    assert planned["reason"].startswith("readings missing or failing check: 2025-12-27 (failing, ")
    assert workflow.check(layout, TICKER, LATER)["readings"][0]["problems"][0]["message"] == (
        f"{DOC_IDS['old_ten_k']} is no document in raw/ (a DOC_ID of a text file in formatted/)"
    )


def test_plan_reads_the_watchlist_without_tickers_and_never_writes(layout, tmp_path):
    research(layout)
    watchlist = write_watchlist(tmp_path, stock=("intc", "amd"))
    before = snapshot(layout.root)

    planned = workflow.plan(layout, [], NOW, WINDOW, watchlist=watchlist)

    assert [(item["ticker"], item["action"]) for item in planned["tickers"]] == [
        (TICKER, "render"),
        ("AMD", "fetch"),
    ]
    assert planned["generated_at"] == "2026-10-08T06:00:00-04:00"
    assert snapshot(layout.root) == before


# --------------------------------------------------------------------------- derive


def test_derive_writes_every_documents_text_and_every_seasons_measures_once(layout):
    fetch(layout)

    first = workflow.derive(layout, TICKER, NOW)

    assert first["ticker"] == TICKER
    assert first["documents"] == [
        {
            "doc_id": DOC_IDS[role],
            "season": SEASON_OF[role],
            "kind": KINDS[role],
            "path": str(text_path(layout, role)),
            "status": "published",
        }
        for role in ROLES
    ]
    assert first["measures"] == [
        {"season": day, "path": str(measures_path(layout, day)), "status": "published"}
        for day in SPAN_SEASONS
    ]
    assert (first["stray_files"], first["stray_reports"]) == ([], [])
    for role in ROLES:
        written = text_path(layout, role).read_text(encoding="utf-8")
        if role in CALL_OF_ROLE:
            assert written == call_text(CALL_OF_ROLE[role])
        else:
            assert written == html_text(raw_bytes(role).decode("utf-8"))
    for day in SPAN_SEASONS:
        assert (
            measures_path(layout, day)
            .read_text(encoding="utf-8")
            .startswith(f"# {TICKER} · {day} · measures\n")
        )

    second = workflow.derive(layout, TICKER, NOW)

    assert {item["status"] for item in (*second["documents"], *second["measures"])} == {"exists"}


def test_derive_rewrites_a_text_or_measures_that_differs_or_cannot_be_read(layout):
    research(layout)
    expected = text_path(layout, "ten_k").read_text(encoding="utf-8")
    measures = measures_path(layout, "2026-06-27").read_text(encoding="utf-8")
    place(text_path(layout, "ten_k"), "edited\n")
    place(text_path(layout, "call_q2"), b"\xff\xfe")
    place(measures_path(layout, "2026-06-27"), b"\xff\xfe")
    place(measures_path(layout, "2026-03-28"), "edited\n")

    stale = seasons_of(entry(layout))
    output = workflow.derive(layout, TICKER, NOW)

    assert stale["2026-06-27"]["texts"]["stale"] == [DOC_IDS["call_q2"]]
    assert stale["2026-06-27"]["measures"]["status"] == stale["2026-03-28"]["measures"]["status"] == "stale"
    statuses = {item["doc_id"]: item["status"] for item in output["documents"]}
    assert (statuses[DOC_IDS["ten_k"]], statuses[DOC_IDS["call_q2"]]) == ("rewritten", "rewritten")
    assert {
        status for doc_id, status in statuses.items() if doc_id not in (DOC_IDS["ten_k"], DOC_IDS["call_q2"])
    } == {"exists"}
    assert [item["status"] for item in output["measures"]] == [
        "exists",
        "exists",
        "exists",
        "rewritten",
        "rewritten",
    ]
    assert text_path(layout, "ten_k").read_text(encoding="utf-8") == expected
    assert measures_path(layout, "2026-06-27").read_text(encoding="utf-8") == measures
    assert entry(layout)["action"] == "render"


def test_derive_writes_no_measures_for_a_season_whose_filing_is_not_in_raw(layout):
    fetch(layout)
    raw_file(layout, "ten_q_2").unlink()

    output = workflow.derive(layout, TICKER, NOW)

    assert [item["season"] for item in output["measures"]] == SPAN_SEASONS[:-1]
    assert not measures_path(layout, "2026-06-27").exists()
    assert DOC_IDS["exhibit_2_1"] in [item["doc_id"] for item in output["documents"]]
    assert DOC_IDS["ten_q_2"] not in [item["doc_id"] for item in output["documents"]]


# --------------------------------------------------------------------------- check


def test_check_reads_every_seasons_readings_by_default(layout):
    research(layout)
    stub = place(readings_file(layout, date(2025, 9, 27)), f"# {TICKER} · 2025-09-27 · readings\n")

    output = workflow.check(layout, TICKER, NOW)

    assert output["ticker"] == TICKER
    assert [(item["path"], item["season"], item["valid"]) for item in output["readings"]] == [
        (str(stub), "2025-09-27", False),  # before the window, yet read: it is a listed season's
        (str(readings_file(layout, date(2025, 12, 27))), "2025-12-27", True),
        (str(readings_file(layout, Q1)), "2026-03-28", True),
        (str(readings_file(layout, Q2)), "2026-06-27", True),
    ]
    assert len(output["readings"][0]["problems"]) == len(BOT_ITEMS)  # one missing section each
    assert all(item["problems"] == [] for item in output["readings"][1:])


def test_check_lists_every_problem_with_its_line(layout):
    research(layout)
    text = readings_text(
        Q2,
        i3_6=Reading(
            DOC_IDS["ten_q_1"],
            "yellow",
            quotes=(
                ("Not a sentence of the 10-Q at all.", QUOTE_FILING[1]),
                ("Too short.", QUOTE_FILING[1]),
            ),
        ),
    )
    write_readings(layout, Q2, text)

    (checked,) = [item for item in workflow.check(layout, TICKER, NOW)["readings"] if not item["valid"]]

    lines = text.splitlines()
    assert checked == {
        "path": str(readings_file(layout, Q2)),
        "season": "2026-06-27",
        "valid": False,
        "problems": [
            {
                "line": lines.index("> Not a sentence of the 10-Q at all.") + 1,
                "message": "quote not found in the document's derived text",
            },
            {
                "line": lines.index("> Too short.") + 1,
                "message": "the quote is 10 characters long after normalisation; it must be 20 to 800",
            },
        ],
    }


def test_check_takes_a_draft_in_a_folder_named_after_its_season_anywhere(layout, tmp_path):
    research(layout)
    draft = place(tmp_path / "drafts" / "2026-06-27" / "draft.md", readings_text(Q2))

    output = workflow.check(layout, TICKER, NOW, [draft])

    assert output == {
        "ticker": TICKER,
        "readings": [{"path": str(draft), "season": "2026-06-27", "valid": True, "problems": []}],
    }


@pytest.mark.parametrize(
    ("folder", "message"),
    [
        pytest.param(
            "drafts", "a readings draft lies in its season's folder, named YYYY-MM-DD", id="no-season"
        ),
        pytest.param(
            "2026-02-30", "a readings draft lies in its season's folder, named YYYY-MM-DD", id="no-date"
        ),
        pytest.param("2026-06-28", "no season of the newest submissions ends on 2026-06-28", id="unlisted"),
    ],
)
def test_a_draft_outside_a_listed_seasons_folder_is_refused(layout, tmp_path, folder, message):
    research(layout)
    draft = place(tmp_path / folder / "draft.md", readings_text(Q2))

    with pytest.raises(ValueError) as raised:
        workflow.check(layout, TICKER, NOW, [draft])

    assert str(raised.value) == f"{draft}: {message}"


def test_readings_that_cannot_be_read_fail_without_echoing_them(layout, tmp_path):
    research(layout)
    readings_file(layout, Q2).write_bytes(b"# \xff\n")
    missing = tmp_path / "2026-06-27" / "missing.md"

    (unreadable,) = [item for item in workflow.check(layout, TICKER, NOW)["readings"] if not item["valid"]]
    (absent,) = workflow.check(layout, TICKER, NOW, [missing])["readings"]

    (problem,) = unreadable["problems"]
    assert problem["line"] == 1
    assert problem["message"].startswith("the readings cannot be read: ")
    assert "\\xff" not in problem["message"]
    assert absent["problems"] == [{"line": 1, "message": "the readings cannot be read: file not found"}]


def test_readings_saved_with_a_byte_order_mark_and_crlf_line_ends_pass(layout):
    research(layout)
    text = readings_text(Q2).replace("\n", "\r\n")
    readings_file(layout, Q2).write_bytes(b"\xef\xbb\xbf" + text.encode("utf-8"))

    output = workflow.check(layout, TICKER, NOW)

    assert all(item["valid"] for item in output["readings"])


def test_a_text_file_missing_or_out_of_date_fails_the_readings_naming_its_document(layout):
    research(layout)
    text_path(layout, "exhibit_1").unlink()

    (checked,) = [item for item in workflow.check(layout, TICKER, NOW)["readings"] if not item["valid"]]

    lines = readings_text(Q2).splitlines()
    named = [number for number, line in enumerate(lines, 1) if line == f"baseline: {DOC_IDS['exhibit_1']}"]
    assert len(named) == 7  # 1.1, 1.2, 1.4, 1.5, 1.6, 1.7 and 1.10 compare with the previous guidance
    assert checked["season"] == "2026-06-27"
    assert checked["problems"] == [
        {
            "line": number,
            "message": f"the text file of {DOC_IDS['exhibit_1']} is missing or differs from its derivation; "
            "run derive",
        }
        for number in named
    ]


def test_check_writes_nothing(layout):
    research(layout)
    before = snapshot(layout.root)

    workflow.check(layout, TICKER, NOW)

    assert snapshot(layout.root) == before


# --------------------------------------------------------------------------- render


def test_render_writes_the_report_of_every_season_whose_readings_pass(layout):
    research(layout)

    output = workflow.render(layout, TICKER, NOW)

    assert output == {
        "ticker": TICKER,
        "reports": [{"season": day, "path": str(report_path(layout, day))} for day in WINDOW_SEASONS],
        "current": [],
        "skipped": [],
    }
    lines = report_path(layout, "2026-06-27").read_text(encoding="utf-8").split("\n")
    assert lines[:9] == [
        f"# {TICKER} · 2026-06-27 · season report",
        "",
        "Generated 2026-10-08 06:00:00 EDT.",
        "",
        "Issuer: INTEL CORP (CIK 0000050863). Season: the 10-Q for the period ended 2026-06-27 (accession "
        "0000050863-26-000064, filed 2026-07-24). Call: transcript as of the calls list of 2026-10-08.",
        "Baselines: previous quarter 2026-03-28; same quarter last year none listed; previous 10-K "
        "2025-12-27; previous proxy 2025-12-27.",
        "",
        "68 items, every one listed by importance (22 high, 37 medium, 9 low): 15 read by Python, 51 by the "
        "bot, 2 without a source.",
        "",
    ]
    assert (
        "| medium | 2.2 Gross and operating margins · operating margin (%) | previous quarter 2026-03-28 "
        "(10-Q) | 5.15 | 11.18 | +6.03 pp |"
    ) in lines
    assert (
        "| medium | 2.6 Net debt · net debt (USD) | previous quarter 2026-03-28 (10-Q) | 28,000,000,000 | "
        "37,700,000,000 | +9,700,000,000 (+34.64%) |"
    ) in lines
    assert (
        "| high | 9.5 Call cancelled · the season's call | previous four seasons: 2026-03-28, 2025-12-27, "
        "2025-09-27, 2024-12-28 | transcript, unavailable, transcript, unavailable | transcript | — |"
    ) in lines
    ten_k = report_path(layout, "2025-12-27").read_text(encoding="utf-8").split("\n")
    assert ten_k[4].endswith("Call: unavailable as of the calls list of 2026-10-08.")
    assert ten_k[5] == (
        "Baselines: previous quarter 2025-09-27; same quarter last year 2024-12-28; previous 10-K "
        "2024-12-28; previous proxy none listed."
    )


def test_render_skips_a_season_that_cannot_render_and_names_the_current_ones(layout):
    rendered(layout)
    write_readings(layout, Q1, readings_text(Q1, i3_3=Reading(DOC_IDS["ten_k"], "none", "No quote.")))
    write_readings(
        layout,
        Q2,
        readings_text(Q2, i1_1=Reading(DOC_IDS["exhibit_1"], "not disclosed", "not disclosed")),
    )

    output = workflow.render(layout, TICKER, LATER)

    assert output == {
        "ticker": TICKER,
        "reports": [
            {
                "season": "2026-06-27",
                "path": str(report_path(layout, "2026-06-27", "report_20261008T070000EDT.md")),
            }
        ],
        "current": ["2025-12-27"],
        "skipped": [{"season": "2026-03-28", "reason": "the season's readings are failing (1 problem)"}],
    }
    assert report_path(layout, "2026-06-27").is_file()  # the earlier report stays


def remove_text(layout) -> None:
    text_path(layout, "exhibit_2_1").unlink()


def remove_measures(layout) -> None:
    measures_path(layout, "2026-06-27").unlink()


def break_readings(layout) -> None:
    write_readings(layout, Q2, readings_text(Q2, i3_3=Reading(DOC_IDS["ten_q_1"], "none", "No quote.")))


def remove_transcript(layout) -> None:
    raw_file(layout, "transcript_q2").unlink()


def remove_filing(layout) -> None:
    raw_file(layout, "ten_q_2").unlink()


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        pytest.param(remove_text, "1 text file missing or out of date; run derive", id="text"),
        pytest.param(
            remove_measures, "the season's measures.md is missing or out of date; run derive", id="measures"
        ),
        pytest.param(break_readings, "the season's readings are failing (1 problem)", id="readings"),
        pytest.param(
            remove_transcript,
            "the transcript of the call 248001 (2026-07-23) is not in raw/ "
            "({raw}/2026-06-27/transcript_248001.json); run fetch",
            id="call",
        ),
        pytest.param(
            remove_filing,
            "the 10-Q 0000050863-26-000064 for the period ended 2026-06-27 is not in raw/ "
            "({raw}/2026-06-27/10-Q_2026-06-27_0000050863-26-000064/intc-20260627.htm); run fetch",
            id="filing",
        ),
    ],
)
def test_render_refuses_when_no_season_with_readings_can_render(layout, change, reason):
    fetch(layout)
    workflow.derive(layout, TICKER, NOW)
    write_readings(layout, Q2)
    change(layout)

    with pytest.raises(ValueError) as raised:
        workflow.render(layout, TICKER, NOW)

    assert str(raised.value) == f"{TICKER}: no report to write: 2026-06-27: " + reason.format(
        raw=layout.raw(TICKER)
    )
    assert not layout.reports(TICKER).joinpath("2026-06-27", REPORT).exists()


def test_render_refuses_while_no_season_has_readings(layout):
    fetch(layout)
    workflow.derive(layout, TICKER, NOW)

    with pytest.raises(ValueError) as raised:
        workflow.render(layout, TICKER, NOW)

    assert str(raised.value) == f"{TICKER}: no season has readings; run plan"


def test_render_writes_nothing_while_every_report_is_current(layout):
    rendered(layout)
    before = snapshot(layout.root)

    output = workflow.render(layout, TICKER, est(2026, 11, 8, 6, 0))

    assert output == {"ticker": TICKER, "reports": [], "current": WINDOW_SEASONS, "skipped": []}
    assert snapshot(layout.root) == before


def test_render_never_overwrites_a_report(layout):
    rendered(layout)
    first = report_path(layout, "2026-06-27")
    before = first.read_bytes()
    write_readings(
        layout,
        Q2,
        readings_text(Q2, i1_1=Reading(DOC_IDS["exhibit_1"], "not disclosed", "not disclosed")),
    )

    with pytest.raises(FileExists):
        workflow.render(layout, TICKER, NOW)  # the same second: the same name

    assert first.read_bytes() == before
    assert sorted(path.name for path in layout.root.rglob(".*")) == []  # no temporary file left
    later = workflow.render(layout, TICKER, edt(2026, 10, 8, 6, 0, 1))
    assert later["reports"] == [
        {
            "season": "2026-06-27",
            "path": str(report_path(layout, "2026-06-27", "report_20261008T060001EDT.md")),
        }
    ]
    assert first.read_bytes() == before


def test_a_report_rendered_later_is_the_same_but_for_its_generated_line(layout):
    rendered(layout)
    first = report_path(layout, "2026-06-27")
    one = first.read_text(encoding="utf-8").split("\n")
    first.unlink()  # by the test alone: no command or bot deletes a report

    output = workflow.render(layout, TICKER, est(2026, 11, 8, 6, 0))

    (written,) = output["reports"]
    two = Path(written["path"]).read_text(encoding="utf-8").split("\n")
    assert written["path"].endswith("2026-06-27/report_20261108T060000EST.md")
    assert [index for index, (a, b) in enumerate(zip(one, two, strict=True)) if a != b] == [2]
    assert two[2] == "Generated 2026-11-08 06:00:00 EST."


def test_names_and_lines_carry_new_york_time(layout):
    research(layout)

    output = workflow.render(layout, TICKER, est(2026, 12, 31, 23, 30))

    path = output["reports"][-1]["path"]
    assert path.endswith("2026-06-27/report_20261231T233000EST.md")
    assert "\nGenerated 2026-12-31 23:30:00 EST.\n" in Path(path).read_text(encoding="utf-8")


# --------------------------------------------------------------------------- show


def test_show_prints_each_tickers_action_and_newest_report_rendered_now(layout):
    rendered(layout)

    shown = workflow.show(layout, [TICKER, "amd"], LATER)

    path = report_path(layout, "2026-06-27")
    stored = path.read_text(encoding="utf-8")
    now = stored.replace("Generated 2026-10-08 06:00:00 EDT.", "Generated 2026-10-08 07:00:00 EDT.")
    # The default window, two years to today, holds the seasons fetched as baselines too.
    header = (
        f"{TICKER}: action research: readings missing or failing check: 2024-12-28 (missing), 2025-09-27 "
        f"(missing). Newest report: {path} (fresh).\n\n"
    )
    assert shown == f"{header}{now}\nAMD: action fetch: {NO_SUBMISSIONS}.\n\n{NO_REPORT}\n"


def test_show_falls_back_to_the_newest_season_whose_report_renders(layout):
    rendered(layout)
    write_readings(layout, Q2, readings_text(Q2, i3_3=Reading(DOC_IDS["ten_q_1"], "none", "No quote.")))

    shown = workflow.show(layout, [TICKER], LATER)

    path = report_path(layout, "2026-03-28")
    assert f" Newest report: {path} (fresh).\n\n# {TICKER} · 2026-03-28 · season report\n" in shown
    assert "2026-06-27 · season report" not in shown


def test_show_names_a_season_never_rendered_without_a_report_file(layout):
    research(layout)

    shown = workflow.show(layout, [TICKER], NOW)

    assert f" Newest report: none (missing).\n\n# {TICKER} · 2026-06-27 · season report\n" in shown


def test_show_renders_no_report_while_a_raw_file_is_invalid(layout):
    rendered(layout)
    stray = place(layout.raw(TICKER) / "notes.txt", "notes\n")

    shown = workflow.show(layout, [TICKER], LATER)

    assert shown.startswith(f"{TICKER}: action fetch: 1 raw file failed validation (first: {stray}: ")
    assert shown.endswith(f"\n\n{NO_REPORT}\n")


def test_show_reads_the_watchlist_without_tickers(layout, tmp_path):
    rendered(layout)
    watchlist = write_watchlist(tmp_path, stock=("amd", "intc"))

    shown = workflow.show(layout, [], LATER, watchlist=watchlist)

    assert shown.startswith(
        f"AMD: action fetch: {NO_SUBMISSIONS}.\n\n{NO_REPORT}\n\n{TICKER}: action research"
    )
    assert f" Newest report: {report_path(layout, '2026-06-27')} (fresh).\n\n" in shown
    assert shown.endswith("\nnote: the old values are newest first\n")


def test_show_writes_nothing(layout):
    rendered(layout)
    before = snapshot(layout.root)

    workflow.show(layout, [TICKER], LATER)

    assert snapshot(layout.root) == before


# --------------------------------------------------------------------------- tickers


@pytest.mark.parametrize("ticker", ["../INTC", "INTC/..", ""])
def test_unsafe_tickers_are_refused(layout, ticker):
    for command in (
        lambda: workflow.plan(layout, [ticker], NOW, WINDOW),
        lambda: workflow.derive(layout, ticker, NOW),
        lambda: workflow.check(layout, ticker, NOW),
        lambda: workflow.render(layout, ticker, NOW),
        lambda: workflow.show(layout, [ticker], NOW),
    ):
        with pytest.raises(ValueError, match="ticker must be a US symbol"):
            command()
    assert not layout.root.exists()
