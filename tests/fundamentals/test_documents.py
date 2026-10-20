"""``documents``: the raw tree read into periods and documents, every raw file validated, and derived text.

The raw tree is written through ``workflow.fetch`` over the fake EDGAR and EarningsCalls.dev
of ``workflow_support``, and by the planters that put a calls page or a transcript where
``fetch`` writes them; expected paths, ``DOC_ID`` values and dates are written out in
``workflow_support``, ``calls_support`` and here, independently of the code under test.
Every file lives below pytest's ``tmp_path``.
"""

import io
import os
from datetime import date, datetime
from pathlib import Path

import pytest

from market_state_research.common.times import timestamp_token
from market_state_research.fundamentals.script import documents
from market_state_research.fundamentals.script.documents import (
    Document,
    call_doc_id,
    derive_call,
    derive_text,
    doc_id,
    edgar_text,
    events_name,
    layout_mode,
    period_documents,
    read_raw,
    transcript_name,
)
from market_state_research.fundamentals.script.filings import Release, Window, parse_submissions
from market_state_research.fundamentals.script.text import html_text

from .calls_support import (
    CALL_DROPPED,
    CALL_OLD_Q,
    CALL_Q1,
    CALL_Q2,
    CALL_Q3,
    CALLS,
    Call,
    call_row,
    call_text,
    events_page,
    transcript_body,
)
from .edgar_support import (
    EIGHT_K_Q2,
    ENTITY_NAME,
    OLD_TEN_K,
    OLD_TEN_Q,
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
    CALLS_FETCHED_AT,
    DOC_IDS,
    EIGHT_K_Q3,
    FETCHED_AT,
    LATER_RECENT,
    LATER_TIMES,
    PENDING_RECENT,
    PERIOD_DOCUMENTS,
    Q3_EXHIBITS,
    RAW,
    TEN_Q_3,
    WINDOW,
    calls_directory,
    edgar,
    fetch,
    place,
    plant_events,
    plant_transcript,
    raw_bytes,
    raw_file,
)

CIK = "0000050863"
NOT_A_CALL_FILE = (
    "not a file fetch writes in calls/ (events_{TOKEN}_{PAGE}.json, transcript_{ID}.json or "
    "transcript_{ID}_{TOKEN}.json); rename it with .rejected"
)
NO_CAPTURE = "no calls list from EarningsCalls.dev is in raw/; run fetch"
INVALID_CAPTURE = (
    "the newest calls list in raw/ is invalid (see invalid_files); rename its pages with .rejected "
    "and run fetch"
)
# A copy of the call 248001's transcript as fetch --refresh writes it, read at 05:45:06 (before NOW).
REFRESHED_Q2 = "transcript_248001_20261008T054506EDT.json"
CORRECTED_TITLE = "Intel Corporation - Q2 2026 Earnings Call (corrected)"


def state(layout, now=NOW):
    return period_documents(layout, TICKER, now)


def invalid(layout, now=NOW) -> dict[str, str]:
    """The invalid files, by their path below the data directory."""
    return {str(path.relative_to(layout.root)): reason for path, reason in state(layout, now).invalid_files}


def calls_path(name: str) -> str:
    return f"raw/{TICKER}/calls/{name}"


def files_of(layout, period: date, now=NOW):
    """The raw files of the period ending ``period``."""
    (files,) = [files for files in state(layout, now).periods if files.day == period]
    return files


def edgar_only(layout) -> None:
    """Every EDGAR file of ``WINDOW`` and nothing in ``calls/``."""
    fetch(layout)
    for path in calls_directory(layout).iterdir():
        path.unlink()


def plant_submissions(layout, at: datetime, rows=RECENT) -> Path:
    """A submissions body listing ``rows`` under the name ``fetch`` gives one read at ``at``."""
    name = f"submissions_{timestamp_token(at)}.json"
    return place(layout.raw(TICKER) / "edgar" / name, submissions_json(rows=rows))


# --------------------------------------------------------------------------- names


def test_doc_ids_are_the_folder_and_the_file_name_without_its_extension():
    assert doc_id("10-Q_2026-06-27_0000050863-26-000157", "intc-20260627.htm") == (
        "10-Q_2026-06-27_0000050863-26-000157_intc-20260627"
    )
    assert doc_id("8-K_2026-07-23_0000050863-26-000155", "q2.earnings.htm") == (
        "8-K_2026-07-23_0000050863-26-000155_q2.earnings"
    )
    assert call_doc_id(date(2026, 6, 27), 248001) == "call_2026-06-27_248001"


def test_call_file_names_carry_the_fetch_time_and_page_or_the_call_id():
    assert events_name(edt(2026, 10, 8, 5, 31, 0, 250000), 1) == "events_20261008T053100EDT_1.json"
    assert events_name(edt(2026, 10, 8, 5, 31), 12) == "events_20261008T053100EDT_12.json"
    assert transcript_name(248001) == "transcript_248001.json"
    assert transcript_name(248001, edt(2026, 10, 8, 5, 45, 6, 500000)) == REFRESHED_Q2
    for page in (0, 21, True):
        with pytest.raises(ValueError, match="^a calls page is a number from 1 to 20$"):
            events_name(NOW, page)
    for call_id in (0, 10**12 + 1, True):
        with pytest.raises(ValueError, match="^a call id is a whole number from 1 to 1000000000000$"):
            transcript_name(call_id)


@pytest.mark.parametrize(
    ("kind", "name", "layout"),
    [
        ("call", "transcript_248001.json", False),
        ("filing", "intc-20260627.htm", False),
        ("filing", "0000950123-09-000001.txt", True),
        ("exhibit", "ex99.TXT", True),
        ("exhibit", "ex99.htm", False),
    ],
)
def test_layout_mode_follows_the_documents_kind_and_name_alone(tmp_path, kind, name, layout):
    document = Document("id", kind, date(2026, 6, 27), tmp_path / name, "label")
    assert layout_mode(document) is layout
    assert document.text_name == "id.md"


# --------------------------------------------------------------------------- EDGAR documents


def test_the_periods_come_from_the_newest_submissions_with_every_document_fetch_wrote(layout):
    fetch(layout)

    raw = state(layout)

    assert (raw.ticker, raw.cik, raw.entity_name, raw.reason, raw.invalid_files) == (
        TICKER,
        CIK,
        ENTITY_NAME,
        None,
        (),
    )
    assert raw.submissions == raw_file(layout, "submissions")
    listed = {files.day.isoformat(): files for files in raw.periods}
    for period, roles in PERIOD_DOCUMENTS.items():
        files = listed[period]
        assert files.missing is None
        assert files.call.settled
        assert [document.doc_id for document in files.documents] == [DOC_IDS[role] for role in roles]
    q2 = listed["2026-06-27"]
    assert q2.filing is not None
    assert (q2.filing.path, q2.filing.kind, q2.filing.filed, q2.filing.label) == (
        raw_file(layout, "ten_q_2"),
        "filing",
        TEN_Q_2.filed,
        "10-Q for the period ended 2026-06-27",
    )
    (release,) = q2.releases
    assert (release.release.accession, release.folder, release.index_path) == (
        EIGHT_K_Q2.accession,
        "8-K_2026-07-23_0000050863-26-000062",
        raw_file(layout, "index_2"),
    )
    assert [(row.exhibit, row.sequence, document.path) for row, document in release.exhibits if document] == [
        ("EX-99.1", 2, raw_file(layout, "exhibit_2_1")),
        ("EX-99.2", 3, raw_file(layout, "exhibit_2_2")),
    ]
    exhibit = release.exhibits[0][1]
    assert exhibit is not None
    assert (exhibit.kind, exhibit.period, exhibit.filed, exhibit.label) == (
        "exhibit",
        date(2026, 6, 27),
        EIGHT_K_Q2.filed,
        "EX-99.1 of the 8-K dated 2026-07-23 (q226earningsrelease.htm)",
    )


def test_every_listed_period_is_listed_even_without_its_documents(layout):
    fetch(layout)

    raw = state(layout)

    assert [files.day for files in raw.periods] == [
        date(2024, 12, 28),
        date(2025, 9, 27),
        TEN_K.period,
        TEN_Q_1.period,
        TEN_Q_2.period,
    ]
    old = raw.periods[0]
    assert old.filing is None and old.documents == ()
    assert old.missing == (
        "the 10-K 0000050863-25-000009 for the period ended 2024-12-28 is not in raw/ "
        f"({old.filing_path}); run fetch"
    )
    assert raw.documents().keys() == set(DOC_IDS.values())


def test_without_a_submissions_file_no_period_is_listed(layout):
    raw = state(layout)

    assert (raw.submissions, raw.reason, raw.periods, raw.invalid_files) == (
        None,
        "no submissions file is in raw/; run fetch",
        (),
        (),
    )


@pytest.mark.parametrize("role", ["ten_q_2", "index_2", "exhibit_2_2"])
def test_a_missing_document_names_itself_as_the_first_one_to_fetch(layout, role):
    fetch(layout)
    path = raw_file(layout, role)
    path.unlink()

    (files,) = [files for files in state(layout).periods if files.day == TEN_Q_2.period]

    what = {
        "ten_q_2": "10-Q 0000050863-26-000064 for the period ended 2026-06-27",
        "index_2": "filing index page of the 8-K 0000050863-26-000062 dated 2026-07-23",
        "exhibit_2_2": "EX-99.2 q226cfocommentary.htm of the 8-K 0000050863-26-000062",
    }[role]
    assert files.missing == f"the {what} is not in raw/ ({path}); run fetch"


def test_an_index_page_that_does_not_parse_is_invalid_and_its_exhibits_unknown(layout):
    fetch(layout)
    path = raw_file(layout, "index_2")
    place(path, "<html><body>no table</body></html>")

    raw = state(layout)

    assert raw.invalid_files == (
        (
            path,
            'filing index 0000050863-26-000062: no tableFile table with the summary "Document Format Files"',
        ),
    )
    (files,) = [files for files in raw.periods if files.day == TEN_Q_2.period]
    assert files.releases[0].exhibits == () and not files.releases[0].index_valid
    assert files.missing == (
        "the filing index page of the 8-K 0000050863-26-000062 dated 2026-07-23 in raw/ is invalid "
        "(see invalid_files); rename it with .rejected and run fetch"
    )


def test_an_edgar_document_that_is_not_a_regular_file_is_invalid(layout):
    fetch(layout)
    path = raw_file(layout, "ten_k")
    path.unlink()
    path.mkdir()

    raw = state(layout)

    assert raw.invalid_files == ((path, "not a regular file"),)
    assert raw.periods[2].filing is None


def test_a_file_where_a_filings_folder_belongs_is_invalid(layout):
    fetch(layout)
    folder = raw_file(layout, "ten_k").parent
    raw_file(layout, "ten_k").unlink()
    folder.rmdir()
    place(folder, b"x")

    raw = state(layout)

    assert raw.invalid_files == (
        (folder, "not a folder: a filing's documents belong in a folder of this name"),
    )
    (files,) = [files for files in raw.periods if files.day == TEN_K.period]
    assert files.missing == (
        "the 10-K 0000050863-26-000012 for the period ended 2025-12-27 in raw/ is invalid "
        "(see invalid_files); rename it with .rejected and run fetch"
    )


def test_the_newest_submissions_file_lists_the_periods_and_rule_b_places_releases_again(layout):
    fetch(layout, edgar(rows=PENDING_RECENT))
    (later,) = [files for files in state(layout).periods if files.day == TEN_Q_2.period]
    assert [release.release.accession for release in later.releases] == [EIGHT_K_Q2.accession]  # Q3's pends
    listing = state(layout).listing
    assert listing is not None and EIGHT_K_Q3.period is not None
    assert listing.pending == (
        Release(EIGHT_K_Q3.accession, EIGHT_K_Q3.filed, EIGHT_K_Q3.period, EIGHT_K_Q3.items),
    )

    fetch(
        layout,
        edgar(rows=LATER_RECENT, documents=(TEN_Q_3,), releases=((EIGHT_K_Q3, Q3_EXHIBITS),)),
        times=LATER_TIMES,
    )

    raw = state(layout, edt(2026, 10, 8, 6, 0))
    assert raw.submissions == layout.raw(TICKER) / "edgar/submissions_20261008T054001EDT.json"
    (newest,) = [files for files in raw.periods if files.day == TEN_Q_3.period]
    assert newest.missing is None
    assert [document.doc_id for document in newest.documents] == [
        "10-Q_2026-09-26_0000050863-26-000090_intc-20260926",
        "8-K_2026-10-06_0000050863-26-000089_q326earningsrelease",
    ]


def test_a_submissions_file_named_after_now_is_not_read(layout):
    fetch(layout)
    later = layout.raw(TICKER) / "edgar/submissions_20261008T070000EDT.json"
    place(later, "not even JSON")

    raw = state(layout)  # 06:00

    assert (raw.submissions, raw.invalid_files) == (raw_file(layout, "submissions"), ())


@pytest.mark.parametrize(
    ("body", "reason"),
    [
        pytest.param(b"\xff", "the submissions body is not UTF-8", id="not-utf-8"),
        pytest.param(
            b"{}", "submissions: cik must be a string of up to ten digits or an integer", id="no-cik"
        ),
        pytest.param(
            submissions_json().replace('"filings"', '"filed"').encode(),
            f"submissions CIK{CIK}: filings is missing",
            id="no-filings",
        ),
    ],
)
def test_a_newest_submissions_file_that_does_not_parse_is_invalid_and_lists_no_period(layout, body, reason):
    path = place(layout.raw(TICKER) / "edgar/submissions_20261008T053001EDT.json", body)

    raw = state(layout)

    assert raw.invalid_files == ((path, reason),)
    assert raw.periods == ()
    assert raw.reason == f"{path.name} is invalid (see invalid_files); rename it with .rejected and run fetch"


def test_submissions_whose_periods_cannot_be_listed_give_the_reason_without_an_invalid_file(layout):
    rows = parse_submissions(submissions_json(), CIK).recent
    body = submissions_json(rows=[Row("8-K", "0000050863-26-000001", date(2026, 1, 2), None, "a.htm")])
    place(layout.raw(TICKER) / "edgar/submissions_20261008T053001EDT.json", body)

    raw = state(layout)

    assert rows  # the default history lists periods; this one lists none
    assert raw.invalid_files == ()
    assert raw.reason is not None and raw.reason.startswith("no 10-K or 10-Q among the 1 recent filings")


# --------------------------------------------------------------------------- calls


def test_the_newest_calls_list_places_each_call_in_its_period_by_rule_b(layout):
    fetch(layout)

    raw = state(layout)

    assert (raw.invalid_files, raw.unlisted, raw.pending_calls, raw.capture_problem) == ((), (), (), None)
    capture = raw.capture
    assert capture is not None
    assert (capture.fetched_at, capture.day, capture.pages) == (
        edt(2026, 10, 8, 5, 31),  # the token's time, to the second
        date(2026, 10, 8),
        (raw_file(layout, "events"),),
    )
    assert [call.id for call in capture.calls] == [call.id for call in CALLS]  # newest first, as listed
    calls = {files.day.isoformat(): files.call for files in raw.periods}
    assert {
        day: (call.status, [event.id for event in call.events], call.due.isoformat(), call.as_of)
        for day, call in calls.items()
    } == {
        "2024-12-28": ("unavailable", [], "2025-01-31", date(2026, 10, 8)),  # 64251 is dropped
        "2025-09-27": ("missing", [CALL_OLD_Q.id], "2025-10-31", date(2026, 10, 8)),
        "2025-12-27": ("unavailable", [], "2026-01-30", date(2026, 10, 8)),
        "2026-03-28": ("transcript", [CALL_Q1.id], "2026-04-23", date(2026, 10, 8)),
        "2026-06-27": ("transcript", [CALL_Q2.id], "2026-07-23", date(2026, 10, 8)),
    }
    old = calls_directory(layout) / f"transcript_{CALL_OLD_Q.id}.json"
    assert calls["2025-09-27"].reason == (
        f"the transcript of the call 35174 (2025-10-23) is not in raw/ ({old}); run fetch"
    )
    assert [call.reason for day, call in calls.items() if day != "2025-09-27"] == [None] * 4
    assert [call.settled for call in calls.values()] == [True, False, True, True, True]


def test_a_call_document_names_its_transcript_and_the_listed_call(layout):
    fetch(layout)

    (document,) = files_of(layout, TEN_Q_2.period).calls

    assert document.call is not None
    assert document == Document(
        doc_id="call_2026-06-27_248001",
        kind="call",
        period=date(2026, 6, 27),
        path=raw_file(layout, "transcript_q2"),
        label="earnings call 2026-06-27: Intel Corporation - Q2 2026 Earnings Call",
        title="Intel Corporation - Q2 2026 Earnings Call",
        call=document.call,
    )
    call = document.call
    assert (call.id, call.at, call.day, call.fiscal_year, call.fiscal_quarter) == (
        CALL_Q2.id,
        edt(2026, 7, 23, 17, 0),  # 21:00 UTC
        date(2026, 7, 23),
        2026,
        2,
    )
    assert document.text_name == "call_2026-06-27_248001.md"


def test_without_a_calls_list_every_periods_call_is_missing(layout):
    edgar_only(layout)

    raw = state(layout)

    assert (raw.capture, raw.capture_problem, raw.invalid_files) == (None, NO_CAPTURE, ())
    assert {(files.call.status, files.call.reason, files.call.as_of) for files in raw.periods} == {
        ("missing", NO_CAPTURE, None)
    }
    assert raw.events_due(WINDOW, NOW) == NO_CAPTURE


def test_a_period_without_a_listed_call_waits_until_seven_days_after_its_due_date(layout):
    edgar_only(layout)
    rows = [call_row(CALL_Q1)]  # the quarter ended 2026-06-27 has no call listed yet
    plant_events(layout, events_page(rows), at=edt(2026, 7, 29, 23, 59, 59))

    call = files_of(layout, TEN_Q_2.period).call

    assert (call.status, call.due, call.as_of, call.events, call.documents) == (
        "waiting",
        date(2026, 7, 23),  # the release's report date
        date(2026, 7, 29),
        (),
        (),
    )
    assert call.reason == (
        "EarningsCalls.dev lists no call for the period as of 2026-07-29; a list fetched on or after "
        "2026-07-30 that lists none shows it unavailable"
    )
    assert not call.settled

    plant_events(layout, events_page(rows), at=edt(2026, 7, 30, 0, 0))  # a newer list, 7 days on

    call = files_of(layout, TEN_Q_2.period).call
    assert (call.status, call.as_of, call.reason, call.settled) == (
        "unavailable",
        date(2026, 7, 30),
        None,
        True,
    )


def test_a_period_without_a_release_is_due_by_its_filing_date(layout):
    edgar_only(layout)
    plant_events(layout, events_page([]), at=edt(2026, 2, 5, 12, 0))

    call = files_of(layout, TEN_K.period).call

    assert (call.status, call.due, call.as_of) == ("waiting", TEN_K.filed, date(2026, 2, 5))
    assert call.reason is not None and call.reason.endswith(
        "on or after 2026-02-06 that lists none shows it unavailable"
    )


def test_the_calls_list_is_due_again_seven_days_after_it_was_fetched_while_a_call_is_unavailable(layout):
    fetch(layout)  # the fiscal year ended 2025-12-27 has no call listed: unavailable as of 2026-10-08
    raw = state(layout)

    assert raw.events_due(WINDOW, NOW) is None
    assert raw.events_due(WINDOW, edt(2026, 10, 15, 5, 30, 59)) is None
    assert raw.events_due(WINDOW, edt(2026, 10, 15, 5, 31)) == (
        "the newest calls list, fetched 2026-10-08, is 7 days old or more and lists no call for the "
        "period 2025-12-27"
    )
    # A window whose calls are all transcripts never asks again.
    assert raw.events_due(Window(date(2026, 3, 1), TODAY), edt(2027, 1, 1)) is None


def test_a_list_fetched_on_or_before_a_periods_due_date_is_due_once_that_date_has_passed(layout):
    edgar_only(layout)
    # EDGAR as of the 10-K's filing day: the fiscal year ended 2025-12-27 is the newest period, without
    # a release, so its call is due by the 10-K's filing date, 2026-01-30.
    plant_submissions(layout, est(2026, 1, 30, 18, 0), rows=(TEN_K, OLD_TEN_Q, OLD_TEN_K))
    plant_events(layout, events_page([]), at=est(2026, 1, 29, 12, 0))
    on_the_day, after = est(2026, 1, 30, 20, 0), est(2026, 1, 31, 6, 0)

    assert files_of(layout, TEN_K.period, on_the_day).call.status == "waiting"
    assert state(layout, on_the_day).events_due(WINDOW, on_the_day) is None  # the due date has not passed
    assert state(layout, after).events_due(WINDOW, after) == (
        "the newest calls list was fetched 2026-01-29, on or before the period 2025-12-27's due date "
        "2026-01-30"
    )
    plant_events(layout, events_page([]), at=after)  # asked again: no call yet, and not due again
    assert state(layout, after).events_due(WINDOW, after) is None


def test_files_in_calls_that_fetch_does_not_write_are_invalid(layout):
    fetch(layout)
    names = (
        "j7ofen85_en_enc1_audio_part1.ts",
        "j7ofen85_en_enc1_audio_part1.ts.meta.json",
        "j7ofen85_en_enc1_audio_part1.ts.ac519ab7e0c5.transcript.json",
        "events_20261008T253000EDT_1.json",  # no such time
        "events_20261008T053100EDT_0.json",  # no page 0
        "events_20261008T053100EDT.json",  # no page
        "transcript_0.json",
        "transcript_248001.json.bak",
        "transcript_248001_20261008T253000EDT.json",  # no such time
        "transcript_248001_20261008T054506.json",  # no zone
    )
    for name in names:
        place(calls_directory(layout) / name, b"x")
    (calls_directory(layout) / "folder").mkdir()

    assert invalid(layout) == {
        **{calls_path(name): NOT_A_CALL_FILE for name in names},
        calls_path("folder"): "not a regular file",
    }


def test_files_renamed_rejected_and_dotfiles_are_skipped(layout):
    fetch(layout)
    place(calls_directory(layout) / "Q2+2026+Prepared+Remarks.pdf.rejected", b"x")
    place(calls_directory(layout) / ".DS_Store", b"x")
    raw_file(layout, "transcript_q2").rename(raw_file(layout, "transcript_q2").with_name("x.json.rejected"))

    raw = state(layout)

    assert raw.invalid_files == ()
    q2 = files_of(layout, TEN_Q_2.period).call
    assert q2.status == "missing" and q2.reason is not None and q2.reason.startswith("the transcript of")


def test_a_symbolic_link_is_not_a_transcript(layout, tmp_path):
    fetch(layout)
    path = raw_file(layout, "transcript_q2")
    target = place(tmp_path / "elsewhere.json", path.read_bytes())
    path.unlink()
    os.symlink(target, path)

    assert invalid(layout) == {calls_path(path.name): "not a regular file"}


@pytest.mark.parametrize(
    ("page", "reason"),
    [
        pytest.param(
            b"not json", "calls list: invalid JSON: Expecting value (line 1, column 1)", id="not-json"
        ),
        pytest.param(
            events_page(ambiguous=True, issuer_count=2),
            "EarningsCalls.dev lists 2 issuers for INTC (ambiguous): their calls cannot be told apart",
            id="ambiguous",
        ),
        pytest.param(
            events_page([call_row(CALL_Q2, symbol="INTL")]),
            "calls list page 1: a call's stock_symbol is not INTC",
            id="other-symbol",
        ),
        pytest.param(
            events_page(total=150),
            "the calls capture holds 1 page; its total of 150 calls fills 2",
            id="a-page-short",
        ),
    ],
)
def test_a_calls_list_that_does_not_read_is_invalid_and_knows_no_call(layout, page, reason):
    edgar_only(layout)
    path = plant_events(layout, page)

    raw = state(layout)

    assert raw.invalid_files == ((path, reason),)
    assert (raw.capture, raw.capture_problem) == (None, INVALID_CAPTURE)
    assert {(files.call.status, files.call.reason) for files in raw.periods} == {("missing", INVALID_CAPTURE)}
    assert raw.events_due(WINDOW, NOW) == INVALID_CAPTURE


def test_a_capture_without_its_first_page_is_invalid(layout):
    edgar_only(layout)
    path = plant_events(layout, events_page(page=2, total=150), number=2)

    assert invalid(layout) == {
        calls_path(path.name): (
            "page 1 of this calls capture is not in raw/; rename the capture's pages with .rejected"
        )
    }


def test_a_capture_of_several_pages_is_read_in_page_order(layout):
    edgar_only(layout)
    first = [
        call_row(Call(1000 + number, f"2026-0{1 + number % 9}-01T21:00:00.000Z", "", None, None, ""))
        for number in range(100)
    ]
    second = [call_row(CALL_Q2), call_row(CALL_Q1)]
    one = plant_events(layout, events_page(first, total=102))
    two = plant_events(layout, events_page(second, page=2, total=102), number=2)

    raw = state(layout)

    assert raw.invalid_files == ()
    assert raw.capture is not None and raw.capture.pages == (one, two)
    assert [call.id for call in raw.capture.calls][-2:] == [CALL_Q2.id, CALL_Q1.id]


def test_only_the_newest_capture_is_read(layout):
    fetch(layout)
    plant_events(layout, b"not json", at=edt(2026, 10, 1, 9, 0))  # older, invalid, never read

    assert state(layout).invalid_files == ()

    later = plant_events(layout, b"not json", at=edt(2026, 10, 8, 7, 0))  # named after NOW: not read yet
    assert state(layout).invalid_files == ()
    assert invalid(layout, edt(2026, 10, 8, 7, 0)) == {
        calls_path(later.name): "calls list: invalid JSON: Expecting value (line 1, column 1)"
    }


def test_the_newest_copy_of_a_transcript_is_read_and_an_older_one_never(layout):
    fetch(layout)
    # The first copy no longer reads, and fetch --refresh wrote a later one under another title.
    plant_transcript(layout, CALL_Q2, b"not json")
    newer = place(
        calls_directory(layout) / REFRESHED_Q2, transcript_body(CALL_Q2, header={"title": CORRECTED_TITLE})
    )

    raw = state(layout)

    assert raw.invalid_files == ()
    assert raw.transcript_files == {CALL_Q1.id: raw_file(layout, "transcript_q1"), CALL_Q2.id: newer}
    (document,) = files_of(layout, TEN_Q_2.period).calls
    assert (document.path, document.title, document.doc_id) == (newer, CORRECTED_TITLE, DOC_IDS["call_q2"])


def test_a_transcript_copy_named_after_now_is_not_read_yet(layout):
    fetch(layout)
    later = place(calls_directory(layout) / "transcript_248001_20261008T070000EDT.json", b"{}")
    seven = edt(2026, 10, 8, 7, 0)

    assert state(layout).invalid_files == ()
    assert state(layout).transcript_files[CALL_Q2.id] == raw_file(layout, "transcript_q2")
    # Once the clock reaches its token, it is the newest copy: invalid, so the call is missing.
    assert invalid(layout, seven) == {calls_path(later.name): "transcript: data: Field required"}
    call = files_of(layout, TEN_Q_2.period, seven).call
    assert (call.status, call.documents, call.reason) == (
        "missing",
        (),
        "the transcript of the call 248001 (2026-07-23) in raw/ is invalid (see invalid_files); rename it "
        "with .rejected and run fetch",
    )


def test_a_transcript_of_a_call_the_newest_list_does_not_list_is_unlisted(layout):
    fetch(layout)
    path = place(calls_directory(layout) / "transcript_999.json", b"anything")

    raw = state(layout)

    assert (raw.unlisted, raw.invalid_files) == ((path,), ())


@pytest.mark.parametrize(
    ("body", "reason"),
    [
        pytest.param(b"{}", "transcript: data: Field required", id="no-data"),
        pytest.param(
            transcript_body(CALL_Q2, header={"event_date_time": "2026-07-23T22:00:00Z"}),
            "transcript: data.header.event_date_time is not the time the calls list gives",
            id="another-call",
        ),
        pytest.param(
            transcript_body(CALL_Q2, turns=()),
            "transcript: data.components: List should have at least 1 item after validation, not 0",
            id="no-turns",
        ),
    ],
)
def test_an_invalid_transcript_is_listed_and_leaves_its_call_missing(layout, body, reason):
    fetch(layout)
    path = plant_transcript(layout, CALL_Q2, body)

    raw = state(layout)

    assert raw.invalid_files == ((path, reason),)
    call = files_of(layout, TEN_Q_2.period).call
    assert (call.status, call.documents, call.reason) == (
        "missing",
        (),
        "the transcript of the call 248001 (2026-07-23) in raw/ is invalid (see invalid_files); rename it "
        "with .rejected and run fetch",
    )


def test_a_dropped_calls_transcript_is_left_out_unchecked(layout):
    fetch(layout)
    place(calls_directory(layout) / f"transcript_{CALL_DROPPED.id}.json", b"not json")

    raw = state(layout)

    assert (raw.invalid_files, raw.unlisted) == ((), ())


def test_a_call_after_the_newest_periods_filing_is_pending_until_rule_b_places_it(layout):
    rows = [call_row(CALL_Q3), *(call_row(call) for call in CALLS)]
    fetch(layout, edgar(rows=PENDING_RECENT), calls=provider(events_page(rows), (CALL_Q3, CALL_Q2, CALL_Q1)))

    raw = state(layout)

    assert [event.id for event in raw.pending_calls] == [CALL_Q3.id]
    assert raw.pending_in(WINDOW) == raw.pending_calls
    assert raw.pending_in(Window(date(2025, 12, 1), date(2026, 6, 26))) == ()
    assert raw.invalid_files == ()

    fetch(
        layout,
        edgar(rows=LATER_RECENT, documents=(TEN_Q_3,), releases=((EIGHT_K_Q3, Q3_EXHIBITS),)),
        times=LATER_TIMES,
        calls=provider(events_page(rows), ()),
    )

    raw = state(layout)
    assert raw.pending_calls == ()
    (newest,) = [files for files in raw.periods if files.day == TEN_Q_3.period]
    assert (newest.call.status, [document.doc_id for document in newest.calls]) == (
        "transcript",
        ["call_2026-09-26_250001"],
    )


def test_without_listed_periods_listed_transcripts_are_still_validated(layout):
    plant_events(layout)
    path = plant_transcript(layout, CALL_Q2, b"{}")

    raw = state(layout)

    assert (raw.reason, raw.periods) == ("no submissions file is in raw/; run fetch", ())
    assert raw.invalid_files == ((path, "transcript: data: Field required"),)
    assert raw.events_due(WINDOW, NOW) is None  # nothing to weigh without a period


def test_doc_ids_that_differ_only_in_letter_case_collide(tmp_path):
    def document(name: str) -> Document:
        return Document(name, "exhibit", date(2026, 6, 27), tmp_path / name, name)

    class Files:  # the one attribute _repeated_ids reads
        def __init__(self, *names: str) -> None:
            self.documents = tuple(document(name) for name in names)

    found = list(documents._repeated_ids((Files("8-K_x_ex99", "8-K_x_EX99"), Files("8-K_x_Ex99"))))

    assert found == [
        (tmp_path / "8-K_x_EX99", "its DOC_ID 8-K_x_EX99 is already another document's"),
        (tmp_path / "8-K_x_Ex99", "its DOC_ID 8-K_x_Ex99 is already another document's"),
    ]


# --------------------------------------------------------------------------- reading raw files


def test_read_raw_refuses_what_is_not_a_regular_file_within_its_limit(tmp_path):
    path = place(tmp_path / "file.json", b"0123456789")
    os.symlink(path, tmp_path / "link.json")
    (tmp_path / "folder.json").mkdir()

    assert read_raw(path, 10) == b"0123456789"
    for target, message in (
        (path, "larger than 9 bytes"),
        (tmp_path / "link.json", "not a regular file"),
        (tmp_path / "folder.json", "not a regular file"),
        (tmp_path / "gone.json", "file not found"),
    ):
        with pytest.raises(ValueError) as caught:
            read_raw(target, 9)
        assert str(caught.value) == message


class CountingReader(io.BufferedReader):
    """A file opened for reading that counts the bytes ``read`` returned."""

    def __init__(self, path: Path) -> None:
        super().__init__(io.FileIO(path, "rb"))
        self.returned = 0

    def read(self, size: int | None = -1, /) -> bytes:
        data = super().read(size)
        self.returned += len(data)
        return data


@pytest.mark.parametrize("limit", [100, 200, 1000])
def test_a_file_that_grew_after_its_check_is_refused_after_one_byte_more_than_the_limit(
    tmp_path, monkeypatch, limit
):
    path = place(tmp_path / "grown.json", b"x" * 4096)
    opened: list[CountingReader] = []

    def counted(self: Path, *args: object, **kwargs: object) -> CountingReader:
        opened.append(CountingReader(self))
        return opened[-1]

    # The size check passed while the file was small; it has grown to 4096 bytes since.
    monkeypatch.setattr(documents, "_regular", lambda path, limit: None)
    monkeypatch.setattr(Path, "open", counted)

    with pytest.raises(ValueError, match=f"^larger than {limit} bytes$"):
        read_raw(path, limit)
    [handle] = opened
    assert handle.closed
    assert handle.returned == limit + 1


# --------------------------------------------------------------------------- derived text


def test_derived_text_of_edgar_documents(layout):
    fetch(layout)
    by_id = state(layout).documents()

    assert derive_text(by_id[DOC_IDS["ten_q_2"]]) == html_text(raw_bytes("ten_q_2").decode())
    assert derive_text(by_id[DOC_IDS["exhibit_2_2"]]) == html_text(raw_bytes("exhibit_2_2").decode())


def test_edgar_text_reads_txt_names_as_plain_text_and_latin_1_as_windows_1252():
    assert edgar_text(b"Line one\r\n  wrapped   here\n", "filing.TXT") == "Line one\nwrapped here\n"
    assert edgar_text(b"<p>A&nbsp;b</p>", "filing.htm") == "A b\n"
    assert edgar_text(b"<p>It\x92s \x96 fine</p>", "filing.htm") == "It’s – fine\n"


def test_a_calls_text_is_derived_from_its_transcript_with_its_turns(layout):
    fetch(layout)
    by_id = state(layout).documents()
    call = by_id[DOC_IDS["call_q2"]]

    derived = derive_call(call)

    assert derive_text(call) == derived.text == call_text(CALL_Q2)
    assert [(derived.text[turn.start : turn.end], turn.speaker, turn.role) for turn in derived.turns][
        2:4
    ] == [
        (
            "Demand for our server processors exceeded our supply in the quarter.\n"
            "We are adding capacity for Intel 18A at our Arizona factory.",
            "Lip-Bu Tan",
            "executive",
        ),
        (
            "We expect gross margin of approximately 36% in the third quarter.\n"
            "We funded our capital spending with cash from operations and partner contributions.",
            "David Zinsner",
            "executive",
        ),
    ]
    assert derive_text(by_id[DOC_IDS["call_q1"]]) == call_text(CALL_Q1)


def test_a_transcript_changed_after_the_read_fails_the_derivation(layout):
    fetch(layout)
    call = state(layout).documents()[DOC_IDS["call_q2"]]
    plant_transcript(
        layout, CALL_Q2, transcript_body(CALL_Q2, header={"event_date_time": "2026-07-24T21:00:00Z"})
    )

    with pytest.raises(ValueError) as caught:
        derive_text(call)
    assert str(caught.value) == "transcript: data.header.event_date_time is not the time the calls list gives"


def test_reading_the_raw_tree_writes_nothing(layout):
    fetch(layout)
    before = sorted(path for path in layout.root.rglob("*"))

    state(layout)
    state(layout, edt(2027, 1, 1))

    assert sorted(path for path in layout.root.rglob("*")) == before


def test_the_files_fetch_writes_carry_their_fetch_times_and_the_bytes_served(layout):
    fetch(layout)

    assert raw_file(layout, "submissions").read_bytes() == raw_bytes("submissions")
    assert raw_file(layout, "submissions").name == f"submissions_{FETCHED_AT:%Y%m%dT%H%M%S}EDT.json"
    assert raw_file(layout, "events").name == f"events_{CALLS_FETCHED_AT:%Y%m%dT%H%M%S}EDT_1.json"
    for role in ("events", "transcript_q1", "transcript_q2"):
        assert raw_file(layout, role).read_bytes() == raw_bytes(role)
    assert sorted(path.name for path in calls_directory(layout).iterdir()) == sorted(
        Path(RAW[role]).name for role in ("events", "transcript_q1", "transcript_q2")
    )
