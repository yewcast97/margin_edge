"""``workflow``: plan, text, check, render and show over a raw tree built in a temporary directory.

The raw tree is written by ``workflow.fetch`` over ``workflow_support``'s fake EDGAR and fake
EarningsCalls.dev, and by the planters that put a calls page or a transcript where ``fetch``
writes them; reports are the samples of ``workflow_support``, whose quotes are copied from the
fixtures' sentences. Expected names, ``DOC_ID`` values and dates are written out. Every file
lives below pytest's ``tmp_path``.
"""

from datetime import date
from pathlib import Path

import pytest

from market_state_research.common.layout import FileExists
from market_state_research.fundamentals.script import report, workflow
from market_state_research.fundamentals.script.filings import Window
from market_state_research.fundamentals.script.research import FIELD_TITLES, WORDING
from market_state_research.fundamentals.script.text import html_text

from .calls_support import (
    ANALYST_QUESTION,
    CALL_DROPPED,
    CALL_OLD_Q,
    CALL_Q1,
    CALL_Q2,
    CEO,
    CEO_DEMAND,
    CFO,
    CFO_GUIDANCE,
    CFO_SUPPLY,
    call_row,
    call_text,
    events_page,
)
from .edgar_support import (
    COMMENTARY_CAPEX,
    RECENT,
    RELEASE_GUIDANCE,
    TEN_K_CAPEX,
    TEN_K_CUSTOMERS,
    TEN_Q_SUPPLY,
    TICKER,
    submissions_json,
)
from .fake_earningscalls import provider
from .support import NOW, TODAY, edt, est
from .workflow_support import (
    AS_OF,
    DEFAULT_WINDOW,
    DOC_IDS,
    PERIOD_DOCUMENTS,
    PERIODS,
    SAMPLES,
    WINDOW,
    calls_directory,
    fetch,
    place,
    plant_transcript,
    raw_bytes,
    raw_file,
    report_file,
    report_text,
    research,
    snapshot,
    write_report,
    write_watchlist,
)

EDGAR_DOCUMENTS = ("ten_k", "ten_q_1", "exhibit_1", "ten_q_2", "exhibit_2_1", "exhibit_2_2")
SERIES = f"{TICKER}_2026-07-24_20261008T060000EDT.md"  # rendered at NOW, as of TEN_Q_2's filing date
CALLS_PAGE = "events_20261008T053100EDT_1.json"
NOT_A_CALL_FILE = (
    "not a file fetch writes in calls/ (events_{TOKEN}_{PAGE}.json, transcript_{ID}.json or "
    "transcript_{ID}_{TOKEN}.json); rename it with .rejected"
)
DOCUMENTS = [DOC_IDS[role] for roles in PERIOD_DOCUMENTS.values() for role in roles]


def entry(layout, now=NOW, window=WINDOW) -> dict:
    (ticker,) = workflow.plan(layout, [TICKER], now, window)["tickers"]
    return ticker


def text_path(layout, role: str) -> Path:
    """A document's text file: ``{DOC_ID}.md``."""
    return layout.formatted(TICKER) / f"{DOC_IDS[role]}.md"


def periods_of(planned: dict) -> dict[str, dict]:
    return {period["period"]: period for period in planned["periods"]}


# --------------------------------------------------------------------------- plan: the action


def test_an_empty_data_directory_plans_a_fetch(layout):
    planned = entry(layout)

    assert planned == {
        "ticker": TICKER,
        "action": "fetch",
        "reason": "no submissions file is in raw/; run fetch",
        "cik": None,
        "entity_name": None,
        "submissions": None,
        "window": {"from": "2025-12-01", "to": "2026-10-08"},
        "truncated": None,
        "pending_releases": [],
        "calls": {"events": None, "due": None, "pending_calls": [], "unlisted_files": []},
        "periods": [],
        "invalid_files": [],
        "failing_reports": [],
        "series": {"status": "missing", "path": None, "as_of": None},
    }
    assert not layout.root.exists()


def test_a_fetched_window_plans_text_and_lists_each_periods_documents_and_call(layout):
    fetch(layout)

    planned = entry(layout)

    assert planned["action"] == "text"
    assert planned["reason"] == "8 text files missing or out of date: " + ", ".join(DOCUMENTS)
    assert (planned["cik"], planned["entity_name"], planned["truncated"]) == (
        "0000050863",
        "INTEL CORP",
        False,
    )
    assert planned["submissions"] == str(raw_file(layout, "submissions"))
    assert planned["calls"] == {
        "events": {
            "path": str(raw_file(layout, "events")),
            "pages": 1,
            "fetched_at": "2026-10-08T05:31:00-04:00",
        },
        "due": None,
        "pending_calls": [],
        "unlisted_files": [],
    }
    assert list(periods_of(planned)) == list(PERIODS)
    q2 = periods_of(planned)["2026-06-27"]
    assert q2["status"] == "not researched"
    assert q2["filing"] == {
        "form": "10-Q",
        "accession": "0000050863-26-000064",
        "filed": "2026-07-24",
        "doc_id": DOC_IDS["ten_q_2"],
        "raw": True,
    }
    assert q2["releases"] == [
        {
            "accession": "0000050863-26-000062",
            "filed": "2026-07-23",
            "report_date": "2026-07-23",
            "index": {"path": str(raw_file(layout, "index_2")), "raw": True},
            "exhibits": [
                {
                    "exhibit": "EX-99.1",
                    "sequence": 2,
                    "document": "q226earningsrelease.htm",
                    "doc_id": DOC_IDS["exhibit_2_1"],
                    "raw": True,
                },
                {
                    "exhibit": "EX-99.2",
                    "sequence": 3,
                    "document": "q226cfocommentary.htm",
                    "doc_id": DOC_IDS["exhibit_2_2"],
                    "raw": True,
                },
            ],
        }
    ]
    assert q2["call"] == {
        "status": "transcript",
        "due": "2026-07-23",
        "as_of": "2026-10-08",
        "calls": [{"id": CALL_Q2.id, "date": "2026-07-23", "fiscal_year": 2026, "fiscal_quarter": 2}],
        "documents": [DOC_IDS["call_q2"]],
        "reason": None,
    }
    assert periods_of(planned)["2025-12-27"]["call"] == {
        "status": "unavailable",
        "due": "2026-01-30",
        "as_of": "2026-10-08",
        "calls": [],
        "documents": [],
        "reason": None,
    }
    assert [(document["doc_id"], document["kind"]) for document in q2["documents"]] == [
        (DOC_IDS["ten_q_2"], "filing"),
        (DOC_IDS["exhibit_2_1"], "exhibit"),
        (DOC_IDS["exhibit_2_2"], "exhibit"),
        (DOC_IDS["call_q2"], "call"),
    ]
    assert q2["documents"][-1] == {
        "doc_id": DOC_IDS["call_q2"],
        "kind": "call",
        "text": {"path": str(text_path(layout, "call_q2")), "status": "missing"},
        "report": {"path": str(report_file(layout, "call_q2")), "status": "missing", "problems": 0},
    }


def test_a_window_period_whose_documents_are_not_all_in_raw_plans_a_fetch(layout):
    fetch(layout)

    planned = entry(layout, window=DEFAULT_WINDOW)

    assert planned["action"] == "fetch"
    assert planned["reason"] == (
        "the 10-K 0000050863-25-000009 for the period ended 2024-12-28 is not in raw/ "
        f"({layout.raw(TICKER) / 'edgar/10-K_2024-12-28_0000050863-25-000009/intc-20241228.htm'}); run fetch"
    )
    assert periods_of(planned)["2024-12-28"]["filing"]["raw"] is False


def test_a_window_calls_transcript_not_in_raw_plans_a_fetch(layout):
    fetch(layout)
    transcript = raw_file(layout, "transcript_q2")
    transcript.unlink()

    planned = entry(layout)

    assert (planned["action"], planned["reason"]) == (
        "fetch",
        f"the transcript of the call 248001 (2026-07-23) is not in raw/ ({transcript}); run fetch",
    )
    assert periods_of(planned)["2026-06-27"]["call"]["status"] == "missing"
    assert DOC_IDS["call_q2"] not in [
        item["doc_id"] for item in periods_of(planned)["2026-06-27"]["documents"]
    ]


def test_without_a_calls_list_the_plan_is_a_fetch(layout):
    fetch(layout)
    for path in calls_directory(layout).iterdir():
        path.unlink()

    planned = entry(layout)

    reason = "no calls list from EarningsCalls.dev is in raw/; run fetch"
    assert (planned["action"], planned["reason"], planned["calls"]["due"]) == ("fetch", reason, reason)


def test_a_calls_list_due_again_plans_a_fetch(layout):
    research(layout)
    workflow.render(layout, TICKER, NOW)
    week = edt(2026, 10, 15, 5, 31)

    assert entry(layout, edt(2026, 10, 15, 5, 30))["action"] == "reuse"
    planned = entry(layout, week)

    due = (
        "the newest calls list, fetched 2026-10-08, is 7 days old or more and lists no call for the period "
        "2025-12-27"
    )
    assert (planned["action"], planned["reason"], planned["calls"]["due"]) == ("fetch", due, due)


def test_a_call_not_listed_yet_waits_without_blocking_the_periods_other_documents(layout):
    # The run of 2026-07-27: the list does not hold the call of 2026-07-23 yet.
    morning = edt(2026, 7, 27, 6, 0)
    rows = [call_row(call) for call in (CALL_Q1, CALL_OLD_Q, CALL_DROPPED)]
    fetch(
        layout,
        times=tuple(morning.replace(second=second) for second in range(10)),
        calls=provider(events_page(rows), (CALL_Q1,)),
        calls_times=(morning.replace(second=30), morning.replace(second=33)),
        now=morning,
    )
    later = edt(2026, 7, 27, 7, 0)

    planned = entry(layout, later)

    assert planned["action"] == "text"  # the list is not due again before 2026-08-03
    q2 = periods_of(planned)["2026-06-27"]["call"]
    assert (q2["status"], q2["as_of"], q2["documents"]) == ("waiting", "2026-07-27", [])
    assert q2["reason"] == (
        "EarningsCalls.dev lists no call for the period as of 2026-07-27; a list fetched on or after "
        "2026-07-30 that lists none shows it unavailable"
    )

    workflow.text(layout, TICKER, later)
    for role in ("ten_k", "ten_q_1", "exhibit_1", "call_q1", "ten_q_2", "exhibit_2_1", "exhibit_2_2"):
        write_report(layout, role)
    output = workflow.render(layout, TICKER, later)

    missing = "the earnings call is not listed yet"
    assert output["periods"][0] == {"period": "2026-06-27", "status": "incomplete", "missing": [missing]}
    lines = Path(output["path"]).read_text(encoding="utf-8").split("\n")
    assert f"| 2026-06-27 | incomplete: missing {missing} | waiting | 3 |{' — |' * 11}" in lines
    assert entry(layout, later)["action"] == "reuse"


def test_every_document_with_a_passing_report_leads_to_render_then_reuse(layout):
    research(layout)

    planned = entry(layout)
    assert (planned["action"], planned["reason"]) == ("render", "no series file")
    assert planned["series"] == {"status": "missing", "path": None, "as_of": "2026-07-24"}
    assert [period["status"] for period in planned["periods"]] == ["complete"] * 3
    assert all(
        document["report"]["status"] == "valid" and document["text"]["status"] == "present"
        for period in planned["periods"]
        for document in period["documents"]
    )

    rendered = workflow.render(layout, TICKER, NOW)
    planned = entry(layout, edt(2026, 10, 8, 7, 0))

    assert (planned["action"], planned["reason"]) == ("reuse", None)
    assert planned["series"] == {"status": "fresh", "path": rendered["path"], "as_of": "2026-07-24"}


def test_a_report_changed_after_the_render_makes_the_series_stale(layout):
    research(layout)
    rendered = workflow.render(layout, TICKER, NOW)
    write_report(layout, "ten_k", report_text(DOC_IDS["ten_k"], capex_plans=[TEN_K_CAPEX[1]]))

    planned = entry(layout, edt(2026, 10, 8, 7, 0))

    assert planned["series"]["status"] == "stale"
    assert (planned["action"], planned["reason"]) == ("render", f"{SERIES} is not the series rendered now")
    assert rendered["path"].endswith(SERIES)


def test_a_failing_report_plans_research_and_names_it(layout):
    research(layout)
    write_report(
        layout, "exhibit_2_2", report_text(DOC_IDS["exhibit_2_2"], capex_plans=["Not in the text at all."])
    )

    planned = entry(layout)

    path = report_file(layout, "exhibit_2_2")
    assert planned["action"] == "research"
    assert planned["reason"] == f"1 document without a passing report; 1 report failing check: {path}"
    assert planned["failing_reports"] == [
        {"path": str(path), "document": DOC_IDS["exhibit_2_2"], "problems": 1}
    ]
    assert periods_of(planned)["2026-06-27"]["status"] == "incomplete"


def test_a_report_naming_no_document_fails_and_plans_research(layout):
    research(layout)
    stray = place(layout.reports(TICKER) / "notes.md", "# notes\n")

    planned = entry(layout)

    assert planned["action"] == "research"
    assert planned["failing_reports"] == [{"path": str(stray), "document": "notes", "problems": 12}]


def test_a_period_with_some_reports_is_incomplete_and_names_what_is_missing(layout):
    research(layout, roles=("ten_q_2", "exhibit_2_1"))

    planned = entry(layout)
    rendered_periods = {period["period"]: period["status"] for period in planned["periods"]}

    assert rendered_periods == {
        "2025-12-27": "not researched",
        "2026-03-28": "not researched",
        "2026-06-27": "incomplete",
    }
    with pytest.raises(ValueError, match="no period is complete"):
        workflow.render(layout, TICKER, NOW)


def test_plan_with_refresh_plans_a_fetch_while_the_window_holds_a_listed_period(layout):
    research(layout)
    workflow.render(layout, TICKER, NOW)
    assert workflow.plan(layout, [TICKER], NOW, WINDOW)["refresh"] is False

    planned = workflow.plan(layout, [TICKER], NOW, WINDOW, refresh=True)

    assert planned["refresh"] is True
    (ticker,) = planned["tickers"]
    assert (ticker["action"], ticker["reason"], ticker["calls"]["due"]) == (
        "fetch",
        "--refresh: the window's documents, transcripts and calls list are requested again",
        workflow.REFRESH_REASON,
    )
    # A window without a listed period has nothing to request again.
    (later,) = workflow.plan(layout, [TICKER], NOW, Window(date(2026, 6, 28), TODAY), refresh=True)["tickers"]
    assert (later["action"], later["calls"]["due"]) == ("reuse", None)
    # A reason that applies without --refresh comes first.
    transcript = raw_file(layout, "transcript_q2")
    transcript.unlink()
    (missing,) = workflow.plan(layout, [TICKER], NOW, WINDOW, refresh=True)["tickers"]
    assert (missing["action"], missing["reason"]) == (
        "fetch",
        f"the transcript of the call 248001 (2026-07-23) is not in raw/ ({transcript}); run fetch",
    )


def test_plan_reads_the_watchlist_without_tickers_and_never_writes(layout, tmp_path):
    research(layout)
    watchlist = write_watchlist(tmp_path, stock=("intc",))
    before = snapshot(layout.root)

    planned = workflow.plan(layout, [], NOW, WINDOW, watchlist=watchlist)

    assert [item["ticker"] for item in planned["tickers"]] == [TICKER]
    assert planned["generated_at"] == "2026-10-08T06:00:00-04:00"
    assert snapshot(layout.root) == before


# --------------------------------------------------------------------------- invalid raw files


def test_an_invalid_call_file_plans_a_fetch_and_refuses_text_check_and_render(layout):
    research(layout)
    workflow.render(layout, TICKER, NOW)
    # A recording the former browser path left in calls/: no file fetch writes.
    orphan = place(calls_directory(layout) / "j7ofen85_en_enc1_audio_part1.ts", b"\x47")

    planned = entry(layout)

    assert planned["invalid_files"] == [{"path": str(orphan), "reason": NOT_A_CALL_FILE}]
    assert planned["action"] == "fetch"
    assert planned["reason"] == (
        f"1 raw file failed validation (first: {orphan}: {NOT_A_CALL_FILE}); rename each with .rejected, "
        "then run fetch"
    )
    message = (
        f"{TICKER}: 1 file in raw/ failed validation; first: {orphan}: {NOT_A_CALL_FILE}; run plan for the "
        "list and rename each with .rejected"
    )
    for command in (
        lambda: workflow.text(layout, TICKER, NOW),
        lambda: workflow.check(layout, TICKER, NOW),
        lambda: workflow.render(layout, TICKER, edt(2026, 10, 8, 7, 0)),
    ):
        with pytest.raises(ValueError) as raised:
            command()
        assert str(raised.value) == message

    orphan.rename(orphan.with_name(f"{orphan.name}.rejected"))
    assert entry(layout)["action"] == "reuse"


def test_an_invalid_transcript_is_withdrawn_then_fetched_again(layout):
    research(layout)
    workflow.render(layout, TICKER, NOW)
    invalid = plant_transcript(layout, CALL_Q2, b"{}")

    planned = entry(layout)

    reason = "transcript: data: Field required"
    assert planned["invalid_files"] == [{"path": str(invalid), "reason": reason}]
    assert (planned["action"], planned["reason"]) == (
        "fetch",
        f"1 raw file failed validation (first: {invalid}: {reason}); rename each with .rejected, then run "
        "fetch",
    )

    invalid.rename(invalid.with_name(f"{invalid.name}.rejected"))
    assert entry(layout)["action"] == "fetch"  # the transcript is not in raw/

    fetch(layout, calls_times=(edt(2026, 10, 8, 6, 30),), now=edt(2026, 10, 8, 6, 30))
    later = edt(2026, 10, 8, 7, 0)
    assert raw_file(layout, "transcript_q2").read_bytes() == raw_bytes("transcript_q2")
    assert entry(layout, later)["action"] == "reuse"  # the same transcript: its text and report stand


def test_a_period_the_newest_submissions_no_longer_list_blocks_nothing(layout):
    research(layout)
    workflow.render(layout, TICKER, NOW)
    # EDGAR's filings.recent has moved on: the 10-K's period 2025-12-27 is no longer listed.
    place(layout.raw(TICKER) / "edgar/submissions_20261008T055000EDT.json", submissions_json(rows=RECENT[:7]))
    later = edt(2026, 10, 8, 7, 0)

    planned = entry(layout, later)

    assert (planned["invalid_files"], planned["failing_reports"]) == ([], [])  # its report left out
    assert list(periods_of(planned)) == ["2026-03-28", "2026-06-27"]
    checked = workflow.check(layout, TICKER, later)["reports"]
    assert {item["document"] for item in checked} == {DOC_IDS[role] for role in SAMPLES} - {DOC_IDS["ten_k"]}
    rendered = workflow.render(layout, TICKER, later)
    assert [period["period"] for period in rendered["periods"]] == ["2026-06-27", "2026-03-28"]


def test_check_and_render_refuse_while_no_period_is_listed(layout):
    research(layout)
    submissions = raw_file(layout, "submissions")
    submissions.rename(submissions.with_name(f"{submissions.name}.rejected"))

    planned = entry(layout)
    assert (planned["action"], planned["reason"]) == ("fetch", "no submissions file is in raw/; run fetch")
    assert planned["failing_reports"] == []  # no report can be checked, so none is called failing
    for command in (
        lambda: workflow.text(layout, TICKER, NOW),
        lambda: workflow.check(layout, TICKER, NOW),
        lambda: workflow.render(layout, TICKER, NOW),
    ):
        with pytest.raises(ValueError, match="^INTC: no submissions file is in raw/; run fetch$"):
            command()


def test_an_invalid_edgar_file_plans_a_fetch(layout):
    research(layout)
    place(raw_file(layout, "index_1"), "<html>no table</html>")

    planned = entry(layout)

    assert planned["action"] == "fetch"
    assert planned["reason"] == (
        "the filing index page of the 8-K 0000050863-26-000040 dated 2026-04-23 in raw/ is invalid "
        "(see invalid_files); rename it with .rejected and run fetch"
    )


def test_an_unlisted_transcript_is_named_and_blocks_nothing(layout):
    research(layout)
    workflow.render(layout, TICKER, NOW)
    unlisted = place(calls_directory(layout) / "transcript_999.json", b"{}")

    planned = entry(layout)

    assert planned["calls"]["unlisted_files"] == [str(unlisted)]
    assert (planned["action"], planned["invalid_files"]) == ("reuse", [])


# --------------------------------------------------------------------------- text


def test_text_writes_every_documents_derived_text_once(layout):
    fetch(layout)

    first = workflow.text(layout, TICKER, NOW)

    assert first["ticker"] == TICKER
    documents = {document["doc_id"]: document for document in first["documents"]}
    assert list(documents) == DOCUMENTS
    assert {document["status"] for document in documents.values()} == {"published"}
    assert documents[DOC_IDS["call_q2"]] == {
        "doc_id": DOC_IDS["call_q2"],
        "period": "2026-06-27",
        "kind": "call",
        "path": str(text_path(layout, "call_q2")),
        "status": "published",
    }
    for role in EDGAR_DOCUMENTS:
        assert text_path(layout, role).read_text(encoding="utf-8") == html_text(raw_bytes(role).decode())
    assert text_path(layout, "call_q2").read_text(encoding="utf-8") == call_text(CALL_Q2)
    assert text_path(layout, "call_q1").read_text(encoding="utf-8") == call_text(CALL_Q1)

    second = workflow.text(layout, TICKER, NOW)

    assert {document["status"] for document in second["documents"]} == {"exists"}


def test_text_rewrites_a_text_that_differs_from_its_derivation(layout):
    research(layout)
    place(text_path(layout, "ten_k"), "edited\n")
    place(text_path(layout, "call_q2"), "edited\n")

    output = workflow.text(layout, TICKER, NOW)

    statuses = {document["doc_id"]: document["status"] for document in output["documents"]}
    assert (statuses[DOC_IDS["ten_k"]], statuses[DOC_IDS["call_q2"]]) == ("rewritten", "rewritten")
    assert text_path(layout, "ten_k").read_text(encoding="utf-8") == html_text(raw_bytes("ten_k").decode())
    assert text_path(layout, "call_q2").read_text(encoding="utf-8") == call_text(CALL_Q2)


def test_text_rewrites_a_text_file_that_cannot_be_read(layout):
    research(layout)
    place(text_path(layout, "ten_k"), b"\xff\xfe")
    place(text_path(layout, "call_q2"), b"\xff\xfe")

    planned = entry(layout)

    texts = {
        document["doc_id"]: document["text"]
        for period in planned["periods"]
        for document in period["documents"]
    }
    assert texts[DOC_IDS["ten_k"]]["status"] == texts[DOC_IDS["call_q2"]]["status"] == "differs"
    assert planned["action"] == "text"
    output = workflow.text(layout, TICKER, NOW)
    statuses = {document["doc_id"]: document["status"] for document in output["documents"]}
    assert statuses[DOC_IDS["ten_k"]] == statuses[DOC_IDS["call_q2"]] == "rewritten"


def test_text_without_a_submissions_file_is_refused(layout):
    with pytest.raises(ValueError, match="^INTC: no submissions file is in raw/; run fetch$"):
        workflow.text(layout, TICKER, NOW)


# --------------------------------------------------------------------------- check


def test_check_lists_every_report_with_its_problems(layout):
    research(layout)
    write_report(
        layout,
        "ten_q_2",
        report_text(DOC_IDS["ten_q_2"], upstream_shortage=[TEN_Q_SUPPLY[0].lower(), "too short"]),
    )

    output = workflow.check(layout, TICKER, NOW)

    reports = {item["document"]: item for item in output["reports"]}
    assert output["ticker"] == TICKER
    assert set(reports) == {DOC_IDS[role] for role in SAMPLES}
    assert reports[DOC_IDS["ten_q_2"]] == {
        "path": str(report_file(layout, "ten_q_2")),
        "document": DOC_IDS["ten_q_2"],
        "valid": False,
        "problems": [
            {"line": 5, "message": "quote not found in the document's derived text"},
            {
                "line": 8,
                "message": "the quote is 9 characters long after normalisation; it must be 20 to 800",
            },
        ],
    }
    assert all(item["valid"] for name, item in reports.items() if name != DOC_IDS["ten_q_2"])


def test_check_takes_explicit_report_paths_anywhere(layout, tmp_path):
    research(layout)
    draft = place(tmp_path / "drafts" / f"{DOC_IDS['exhibit_2_1']}.md", SAMPLES["exhibit_2_1"])

    output = workflow.check(layout, TICKER, NOW, [draft])

    assert output["reports"] == [
        {"path": str(draft), "document": DOC_IDS["exhibit_2_1"], "valid": True, "problems": []}
    ]


def test_a_call_quote_comes_from_an_executives_turn_under_their_own_name(layout):
    research(layout)
    write_report(
        layout,
        "call_q2",
        report_text(
            DOC_IDS["call_q2"],
            upstream_shortage=[("Jane Analyst", ANALYST_QUESTION)],  # an analyst's question
            capacity_shortfall=[CEO_DEMAND],  # no speaker
            earnings_guidance=[(CEO[0], CFO_GUIDANCE)],  # the CFO's words under the CEO's name
            margin_drivers=[(CFO[0], CFO_SUPPLY)],
        ),
    )
    write_report(
        layout,
        "exhibit_2_2",
        report_text(DOC_IDS["exhibit_2_2"], capex_plans=[(CFO[0], COMMENTARY_CAPEX[0])]),
    )

    reports = {item["document"]: item for item in workflow.check(layout, TICKER, NOW)["reports"]}

    assert reports[DOC_IDS["call_q2"]]["problems"] == [
        {
            "line": 6,
            "message": "the quote lies in a turn whose role is analyst, not executive: quote only the "
            "issuer's executives",
        },
        {
            "line": 11,
            "message": "a call quote needs a 'Speaker:' line naming the executive whose turn it quotes",
        },
        {
            "line": 24,  # the Speaker: line
            "message": "the quote lies in another speaker's turn: the 'Speaker:' line must be the name its "
            "heading writes",
        },
    ]
    # A filing or exhibit names no speaker of its own: the name must be written before the quote.
    assert reports[DOC_IDS["exhibit_2_2"]]["problems"] == [
        {"line": 13, "message": "the speaker is not found in the document's derived text before the quote"}
    ]


def test_a_report_for_an_index_page_or_unknown_name_names_no_document(layout):
    research(layout)
    index = place(
        layout.reports(TICKER) / "8-K_2026-07-23_0000050863-26-000062_0000050863-26-000062-index.md",
        report_text("8-K_2026-07-23_0000050863-26-000062_0000050863-26-000062-index"),
    )

    (checked,) = workflow.check(layout, TICKER, NOW, [index])["reports"]

    assert checked["problems"] == [
        {
            "line": 1,
            "message": "the report names no document of a listed period in raw/ (its file name must be the "
            "DOC_ID of a 10-K, 10-Q, EX-99 exhibit or call; an index page or a calls list has none)",
        }
    ]


def test_the_report_of_a_call_whose_transcript_is_withdrawn_names_no_document(layout):
    research(layout)
    transcript = raw_file(layout, "transcript_q2")
    transcript.rename(transcript.with_name(f"{transcript.name}.rejected"))

    reports = {item["document"]: item["problems"] for item in workflow.check(layout, TICKER, NOW)["reports"]}

    assert [problem["message"] for problem in reports.pop(DOC_IDS["call_q2"])] == [
        "the report names no document of a listed period in raw/ (its file name must be the DOC_ID of a "
        "10-K, 10-Q, EX-99 exhibit or call; an index page or a calls list has none)"
    ]
    assert all(problems == [] for problems in reports.values())


def test_a_text_file_missing_or_out_of_date_fails_its_reports(layout):
    research(layout)
    text_path(layout, "ten_k").unlink()
    place(text_path(layout, "exhibit_1"), "edited\n")
    text_path(layout, "call_q2").unlink()

    reports = {item["document"]: item["problems"] for item in workflow.check(layout, TICKER, NOW)["reports"]}

    assert reports[DOC_IDS["ten_k"]] == [
        {"line": 1, "message": f"the document's text file {text_path(layout, 'ten_k')} is missing; run text"}
    ]
    assert reports[DOC_IDS["exhibit_1"]] == [
        {
            "line": 1,
            "message": f"the text file {text_path(layout, 'exhibit_1')} differs from the document's derived "
            "text; run text",
        }
    ]
    assert reports[DOC_IDS["call_q2"]] == [
        {
            "line": 1,
            "message": f"the document's text file {text_path(layout, 'call_q2')} is missing; run text",
        }
    ]


def test_a_report_that_is_not_utf_8_fails_without_echoing_it(layout):
    research(layout)
    report_file(layout, "ten_k").write_bytes(b"# \xff\n")

    (checked,) = [item for item in workflow.check(layout, TICKER, NOW)["reports"] if not item["valid"]]

    assert checked["problems"][0]["message"].startswith("the report cannot be read: ")
    assert "\\xff" not in checked["problems"][0]["message"]


def test_a_report_saved_with_a_byte_order_mark_is_read_without_it(layout):
    research(layout)
    report_file(layout, "ten_k").write_bytes(b"\xef\xbb\xbf" + SAMPLES["ten_k"].encode("utf-8"))

    reports = {item["document"]: item for item in workflow.check(layout, TICKER, NOW)["reports"]}

    assert reports[DOC_IDS["ten_k"]]["valid"] is True


def test_check_writes_nothing(layout):
    research(layout)
    before = snapshot(layout.root)

    workflow.check(layout, TICKER, NOW)

    assert snapshot(layout.root) == before


# --------------------------------------------------------------------------- render


def test_render_writes_the_series_of_the_complete_periods(layout):
    research(layout)

    output = workflow.render(layout, TICKER, NOW)

    path = layout.reports(TICKER) / SERIES
    assert output == {
        "ticker": TICKER,
        "as_of": "2026-07-24",
        "path": str(path),
        "periods": [
            {"period": "2026-06-27", "status": "complete", "missing": []},
            {"period": "2026-03-28", "status": "complete", "missing": []},
            {"period": "2025-12-27", "status": "complete", "missing": []},
        ],
    }
    series = path.read_text(encoding="utf-8")
    lines = series.split("\n")
    assert lines[:5] == [
        f"# {TICKER} · Issuer disclosures · as of 2026-07-24",
        "",
        "Generated 2026-10-08 06:00:00 EDT.",
        "",
        "INTEL CORP, CIK 0000050863. 3 of 3 periods with documents in raw/ are complete: 2026-06-27, "
        "2026-03-28, 2025-12-27. As of 2026-07-24, the filing date of the newest filing or exhibit of the "
        "complete periods.",
    ]
    headings = [line for line in lines if line.startswith("#")]
    assert headings[1:14] == [
        "## 2026-06-27",
        "### Upstream shortage",
        "### Capacity shortfall",
        "### Capex plans",
        "### Capacity expansion",
        "### Earnings guidance",
        "### Pricing",
        "### Backlog and contracts",
        "### Product ramp",
        "### Margin drivers",
        "### Financing methods",
        "### Customer concentration",
        "## 2026-03-28",
    ]
    assert headings[-1] == "## Coverage"
    assert (
        "- EX-99.2 q226cfocommentary.htm of the 8-K 0000050863-26-000062 dated 2026-07-23, filed 2026-07-23 "
        f"(`{DOC_IDS['exhibit_2_2']}`)" in lines
    )
    assert (
        "- Earnings call: Intel Corporation - Q2 2026 Earnings Call, held 2026-07-23, transcript "
        f"(`{DOC_IDS['call_q2']}`)" in lines
    )
    assert (
        "- Earnings call: Intel Corporation - Q1 2026 Earnings Call, held 2026-04-23, transcript "
        f"(`{DOC_IDS['call_q1']}`)" in lines
    )
    assert (
        "- Earnings call: none listed by the transcript provider (EarningsCalls.dev) as of 2026-10-08"
        in lines
    )
    assert (
        f"> {CFO_SUPPLY}\n\n— earnings call 2026-06-27: Intel Corporation - Q2 2026 Earnings Call, {CFO[0]}"
        in series
    )
    guidance = series.index(
        f"> {RELEASE_GUIDANCE[0]}\n\n— EX-99.1 of the 8-K dated 2026-07-23 (q226earningsrelease.htm)"
    )
    assert guidance > series.index("## 2026-06-27")
    # The oldest period, its 10-K alone: no earnings guidance; its last field holds the 10-K's quote.
    assert "### Earnings guidance\n\nNone found in the period's documents.\n\n### Pricing" in series
    assert (
        f"### Customer concentration\n\n> {TEN_K_CUSTOMERS[0]}\n\n— 10-K for the period ended 2025-12-27"
        "\n\n## Coverage" in series
    )
    assert "| Period | Status | Earnings call | Documents | Upstream shortage |" in series
    assert "| 2026-06-27 | complete | transcript | 4 | 4 | 5 | 3 | 3 | 3 | 0 | 1 | 1 | 1 | 1 | 0 |" in lines
    assert "| 2026-03-28 | complete | transcript | 3 | 2 | 2 | 2 | 1 | 2 | 0 | 0 | 1 | 0 | 0 | 0 |" in lines
    assert (
        "| 2025-12-27 | complete | unavailable (provider lists no call as of 2026-10-08) | 1 | 1 | 1 | 1 | "
        "1 | 0 | 1 | 1 | 0 | 0 | 2 | 1 |" in lines
    )
    assert series.endswith("\n")


def test_the_series_fixed_text_carries_no_valuation_forecast_or_advice_wording(layout):
    research(layout, roles=("ten_q_2", "exhibit_2_1", "exhibit_2_2", "call_q2", "ten_q_1"))

    series = Path(workflow.render(layout, TICKER, NOW)["path"]).read_text(encoding="utf-8")

    unquoted = [line for line in series.split("\n") if not line.startswith("> ")]
    assert WORDING.search("\n".join(unquoted)) is None
    constants = (
        report.TITLE,
        *FIELD_TITLES.values(),
        report.NONE_FOUND,
        report.NO_COMPLETE_PERIOD,
        report.CALL_MISSING,
        report.CALL_WAITING,
        report.UNAVAILABLE,
        report.NOT_IN_RAW,
    )
    assert all(WORDING.search(constant) is None for constant in constants)


def test_the_series_lists_periods_without_reports_and_incomplete_ones(layout):
    research(layout, roles=("ten_q_2", "exhibit_2_1", "exhibit_2_2", "call_q2", "ten_q_1"))

    output = workflow.render(layout, TICKER, NOW)

    assert output["periods"] == [
        {"period": "2026-06-27", "status": "complete", "missing": []},
        {
            "period": "2026-03-28",
            "status": "incomplete",
            "missing": [DOC_IDS["exhibit_1"], DOC_IDS["call_q1"]],
        },
        {"period": "2025-12-27", "status": "not researched", "missing": [DOC_IDS["ten_k"]]},
    ]
    series = (layout.reports(TICKER) / SERIES).read_text(encoding="utf-8")
    lines = series.split("\n")
    assert "## 2026-03-28" not in series and "## 2025-12-27" not in series
    assert (
        f"| 2026-03-28 | incomplete: missing {DOC_IDS['exhibit_1']}, {DOC_IDS['call_q1']} | transcript | 3 |"
        f"{' — |' * 11}" in lines
    )
    assert (
        "| 2025-12-27 | not researched | unavailable (provider lists no call as of 2026-10-08) | 1 |"
        f"{' — |' * 11}" in lines
    )


def test_a_period_whose_transcript_is_withdrawn_is_incomplete_until_fetch_writes_it_again(layout):
    research(layout)
    transcript = raw_file(layout, "transcript_q2")
    transcript.rename(transcript.with_name(f"{transcript.name}.rejected"))
    report_file(layout, "call_q2").unlink()

    planned = entry(layout)
    output = workflow.render(layout, TICKER, NOW)

    assert (planned["action"], planned["reason"]) == (
        "fetch",
        f"the transcript of the call 248001 (2026-07-23) is not in raw/ ({transcript}); run fetch",
    )
    missing = "the earnings call's transcript is not in raw/"
    assert output["periods"][0] == {"period": "2026-06-27", "status": "incomplete", "missing": [missing]}
    series = Path(output["path"]).read_text(encoding="utf-8")
    assert f"| 2026-06-27 | incomplete: missing {missing} | missing | 3 |{' — |' * 11}" in series.split("\n")

    fetch(layout, calls_times=(edt(2026, 10, 8, 6, 30),), now=edt(2026, 10, 8, 6, 30))
    later = edt(2026, 10, 8, 7, 0)
    assert entry(layout, later)["action"] == "research"  # its text exists already; its report does not
    write_report(layout, "call_q2")
    assert entry(layout, later)["action"] == "render"


def test_the_as_of_date_is_the_newest_filing_of_the_complete_periods(layout):
    research(layout, roles=("ten_k",))

    output = workflow.render(layout, TICKER, NOW)

    assert output["as_of"] == "2026-01-30"  # the 10-K's filing date; the newer 10-Qs are not complete
    assert output["path"].endswith(f"{TICKER}_2026-01-30_20261008T060000EDT.md")


def test_render_refuses_while_a_report_fails_check(layout):
    research(layout)
    write_report(layout, "ten_k", "# wrong\n")

    with pytest.raises(ValueError) as raised:
        workflow.render(layout, TICKER, NOW)

    assert str(raised.value) == (
        f"{TICKER}: 1 report failed check; first: {report_file(layout, 'ten_k')}: line 1: the first "
        "line must "
        f"be '# {DOC_IDS['ten_k']}', the report file's name without .md; run check"
    )
    assert not (layout.reports(TICKER) / SERIES).exists()


def test_render_refuses_without_a_complete_period(layout):
    fetch(layout)

    with pytest.raises(ValueError) as raised:
        workflow.render(layout, TICKER, NOW)

    assert str(raised.value) == (
        f"{TICKER}: no period is complete: every document of a period needs a report that passes check"
    )


def test_render_never_overwrites_a_series(layout):
    research(layout)
    first = workflow.render(layout, TICKER, NOW)["path"]
    before = Path(first).read_bytes()

    with pytest.raises(FileExists):
        workflow.render(layout, TICKER, NOW)

    assert Path(first).read_bytes() == before
    assert sorted(path.name for path in layout.root.rglob(".*")) == []  # no temporary file left
    later = workflow.render(layout, TICKER, edt(2026, 10, 8, 6, 0, 1))
    assert later["path"].endswith(f"{TICKER}_2026-07-24_20261008T060001EDT.md")


def test_the_series_is_the_same_but_for_its_generated_line(layout):
    research(layout)
    first = workflow.render(layout, TICKER, NOW)["path"]
    second = workflow.render(layout, TICKER, est(2026, 11, 8, 6, 0))["path"]

    one = Path(first).read_text(encoding="utf-8").split("\n")
    two = Path(second).read_text(encoding="utf-8").split("\n")

    assert [index for index, (a, b) in enumerate(zip(one, two, strict=True)) if a != b] == [2]
    assert two[2] == "Generated 2026-11-08 06:00:00 EST."


# --------------------------------------------------------------------------- show


def test_show_prints_the_action_status_lines_and_the_series(layout):
    research(layout)
    workflow.render(layout, TICKER, NOW)

    shown = workflow.show(layout, TICKER, edt(2026, 10, 8, 7, 0))

    lines = shown.split("\n")
    assert lines[:5] == [
        "Action: fetch (default window 2024-10-08 to 2026-10-08): the 10-K 0000050863-25-000009 for the "
        "period ended 2024-12-28 is not in raw/ "
        f"({layout.raw(TICKER) / 'edgar/10-K_2024-12-28_0000050863-25-000009/intc-20241228.htm'}); "
        "run fetch.",
        "Periods with documents in raw/: 3: 3 complete (2025-12-27, 2026-03-28, 2026-06-27), 0 incomplete, "
        "0 not researched.",
        "Reports: 8 pass check, 0 fail.",
        f"Series: {layout.reports(TICKER) / SERIES} (fresh).",
        "",
    ]
    assert lines[5] == f"# {TICKER} · Issuer disclosures · as of 2026-07-24"
    assert lines[7] == "Generated 2026-10-08 07:00:00 EDT."


def test_show_without_a_complete_period_says_why_no_series_is_shown(layout):
    fetch(layout)
    orphan = place(calls_directory(layout) / "remarks.pdf", b"%PDF-1.6")

    shown = workflow.show(layout, TICKER, NOW)

    assert f"Invalid file: {orphan} (not a file fetch writes in calls/" in shown
    assert shown.endswith(
        f"No series can be rendered: {TICKER}: 1 file in raw/ failed validation; first: {orphan}: "
        f"{NOT_A_CALL_FILE}; run plan for the list and rename each with .rejected\n"
    )


def test_show_writes_nothing(layout):
    research(layout)
    before = snapshot(layout.root)

    workflow.show(layout, TICKER, NOW)

    assert snapshot(layout.root) == before


@pytest.mark.parametrize("ticker", ["../INTC", "INTC/..", ""])
def test_unsafe_tickers_are_refused(layout, ticker):
    for command in (
        lambda: workflow.text(layout, ticker, NOW),
        lambda: workflow.check(layout, ticker, NOW),
        lambda: workflow.render(layout, ticker, NOW),
        lambda: workflow.show(layout, ticker, NOW),
    ):
        with pytest.raises(ValueError, match="ticker must be a US symbol"):
            command()


def test_names_and_lines_carry_new_york_time(layout):
    research(layout)

    output = workflow.render(layout, TICKER, est(2026, 12, 31, 23, 30))

    assert output["path"].endswith(f"{TICKER}_2026-07-24_20261231T233000EST.md")
    assert "Generated 2026-12-31 23:30:00 EST." in Path(output["path"]).read_text(encoding="utf-8")
    assert date.fromisoformat(output["as_of"]) == AS_OF
