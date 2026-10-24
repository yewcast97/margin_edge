"""``documents``: one ticker's raw tree read into its seasons, every raw file validated, and derived text.

The tree is written through ``workflow.fetch`` over the fake EDGAR and EarningsCalls.dev of
``workflow_support``, and by the planters here, which put a submissions body, a calls page or a
transcript where ``fetch`` writes them. Expected paths, ``DOC_ID`` values,
dates and messages are written out in ``workflow_support``, ``calls_support`` and here,
independently of the code under test. Every file lives below pytest's ``tmp_path``.
"""

import io
import os
import shutil
from datetime import date, datetime
from pathlib import Path

import pytest

from market_state_research.common.layout import DataLayout
from market_state_research.common.times import timestamp_token
from market_state_research.fundamentals.script import documents
from market_state_research.fundamentals.script.documents import (
    Document,
    Needed,
    RawState,
    SeasonFiles,
    call_doc_id,
    calls_name,
    derive_call,
    derive_text,
    doc_id,
    due_date,
    edgar_text,
    filing_folder,
    layout_mode,
    read_raw,
    season_documents,
    season_folder,
    transcript_name,
)
from market_state_research.fundamentals.script.filings import Window
from market_state_research.fundamentals.script.text import html_text

from .calls_support import (
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
    CIK,
    EIGHT_K_OTHER,
    EIGHT_K_Q2,
    ENTITY_NAME,
    OLD_TEN_K,
    OLD_TEN_Q,
    PENDING_8K,
    Q2_EXHIBITS,
    RECENT,
    TEN_K,
    TEN_Q_1,
    TICKER,
    Row,
    filing_index_html,
    submissions_json,
)
from .support import NOW, TODAY, edt, est
from .workflow_support import (
    CALLS_FETCHED_AT,
    DOC_IDS,
    FETCHED_AT,
    RAW,
    WINDOW,
    edgar,
    fetch,
    place,
    plant_former_layout,
    raw_bytes,
    raw_file,
    snapshot,
)

# The company-level files a first fetch of WINDOW writes: EDGAR's clock reads 05:30:01 for the
# ticker map and a second later for the submissions; the provider's reads 05:31:00 for the calls
# list.
SUBMISSIONS = "submissions_20261008T053002EDT.json"
CAPTURE = "calls_20261008T053100EDT_1.json"
# Each season's documents after that fetch, in order, by their role in DOC_IDS.
SEASON_DOCUMENTS = {
    "2024-12-28": ("old_ten_k",),
    "2025-09-27": ("old_ten_q", "call_old_q"),
    "2025-12-27": ("ten_k", "eight_k_other"),
    "2026-03-28": ("ten_q_1", "eight_k_1", "exhibit_1", "call_q1"),
    "2026-06-27": ("ten_q_2", "eight_k_2", "exhibit_2_1", "exhibit_2_2", "call_q2"),
}
# A call's role in RAW, by its role in DOC_IDS.
TRANSCRIPTS = {"call_old_q": "transcript_old_q", "call_q1": "transcript_q1", "call_q2": "transcript_q2"}
Q1 = date(2026, 3, 28)
Q2 = date(2026, 6, 27)
FISCAL_YEAR = date(2025, 12, 27)

NOT_RAW = (
    "not a file or folder fetch writes in raw/ (see the domain's AGENTS.md, Runtime files); "
    "rename it with .rejected"
)
NOT_RAW_IN_Q2 = (
    "not a file or folder fetch writes in raw/2026-06-27/ (see the domain's AGENTS.md, Runtime files); "
    "rename it with .rejected"
)
NOT_REGULAR = "not a regular file"
NOT_A_FOLDER = "not a folder: a filing's or a season's documents belong in a folder of this name"
NOT_A_SEASON = "no season of the newest submissions ends on this date; rename it with .rejected"
NO_CAPTURE = "no calls list from EarningsCalls.dev is in raw/; run fetch"
INVALID_CAPTURE = (
    "the newest calls list in raw/ is invalid (see invalid_files); rename its pages with .rejected "
    "and run fetch"
)
TRANSCRIPT_Q2_INVALID = (
    "the transcript of the call 248001 (2026-07-23) in raw/ is invalid (see invalid_files); rename it "
    "with .rejected and run fetch"
)
# A copy of the call 248001's transcript as fetch --refresh writes it, read at 05:45:06 (before NOW).
REFRESHED_Q2 = "transcript_248001_20261008T054506EDT.json"
CORRECTED_TITLE = "Intel Corporation - Q2 2026 Earnings Call (corrected)"

# A later 10-Q, listed only by the tests that need it: it places the 8-K of 2026-07-30 in the
# quarter ended 2026-06-27 and the call of 2026-10-06 in its own season.
TEN_Q_3 = Row("10-Q", "0000050863-26-000090", date(2026, 10, 7), date(2026, 9, 26), "intc-20260926.htm")
LATER_RECENT = (TEN_Q_3, *RECENT)
# Two more quarters between the default history's two oldest seasons: four seasons then precede
# a window of the newest one.
Q1_2025 = Row("10-Q", "0000050863-25-000080", date(2025, 5, 2), date(2025, 3, 29), "intc-20250329.htm")
Q2_2025 = Row("10-Q", "0000050863-25-000140", date(2025, 8, 1), date(2025, 6, 28), "intc-20250628.htm")
LONGER_RECENT = (*RECENT[:-1], Q2_2025, Q1_2025, OLD_TEN_K)


def state(layout: DataLayout, now: datetime = NOW) -> RawState:
    return season_documents(layout, TICKER, now)


def invalid(layout: DataLayout, now: datetime = NOW) -> dict[str, str]:
    """The invalid files, by their path below ``raw/INTC/``."""
    root = layout.raw(TICKER)
    return {str(path.relative_to(root)): reason for path, reason in state(layout, now).invalid_files}


def season_of(layout: DataLayout, day: date, now: datetime = NOW) -> SeasonFiles:
    files = state(layout, now).season(day)
    assert files is not None
    return files


def raw_path(layout: DataLayout, relative: str) -> Path:
    return layout.raw(TICKER) / relative


def plant_submissions(layout: DataLayout, at: datetime, rows: tuple[Row, ...] = RECENT) -> Path:
    """A submissions body listing ``rows`` under the name ``fetch`` gives one read at ``at``."""
    return place(layout.raw(TICKER) / f"submissions_{timestamp_token(at)}.json", submissions_json(rows=rows))


def plant_capture(
    layout: DataLayout, page: bytes | None = None, at: datetime = CALLS_FETCHED_AT, number: int = 1
) -> Path:
    """Page ``number`` of a calls capture read at ``at`` (the default capture's page by default)."""
    name = f"calls_{timestamp_token(at)}_{number}.json"
    return place(layout.raw(TICKER) / name, events_page() if page is None else page)


def plant_transcript(
    layout: DataLayout, call: Call, season: date, body: bytes | None = None, at: datetime | None = None
) -> Path:
    """The transcript of ``call`` in the folder of ``season``; with ``at``, the copy read then."""
    name = f"transcript_{call.id}.json" if at is None else f"transcript_{call.id}_{timestamp_token(at)}.json"
    return place(
        layout.raw(TICKER) / season.isoformat() / name, transcript_body(call) if body is None else body
    )


def edgar_only(layout: DataLayout) -> None:
    """Every EDGAR file of ``WINDOW``'s span, the transcripts, and no calls list."""
    fetch(layout)
    raw_path(layout, CAPTURE).unlink()


# --------------------------------------------------------------------------- names


def test_doc_ids_are_the_folder_and_the_file_name_without_its_extension():
    assert doc_id("10-Q_2026-06-27_0000050863-26-000157", "intc-20260627.htm") == (
        "10-Q_2026-06-27_0000050863-26-000157_intc-20260627"
    )
    assert doc_id("8-K_2026-07-23_0000050863-26-000155", "q2.earnings.htm") == (
        "8-K_2026-07-23_0000050863-26-000155_q2.earnings"
    )
    assert doc_id("8-K_2026-07-23_0000050863-26-000155", "q226cfocommentary.htm") == (
        "8-K_2026-07-23_0000050863-26-000155_q226cfocommentary"
    )
    assert call_doc_id(date(2026, 6, 27), 248001) == "call_2026-06-27_248001"


@pytest.mark.parametrize(
    ("form", "folder"),
    [
        ("10-K", "10-K_2026-05-08_0000950123-26-005001"),
        ("10-Q", "10-Q_2026-05-08_0000950123-26-005001"),
        ("8-K", "8-K_2026-05-08_0000950123-26-005001"),
    ],
)
def test_a_filings_folder_is_its_form_without_spaces_or_slashes_its_date_and_accession(form, folder):
    assert filing_folder(form, date(2026, 5, 8), "0000950123-26-005001") == folder
    assert season_folder(date(2026, 6, 27)) == "2026-06-27"


def test_call_file_names_carry_the_fetch_time_and_page_or_the_call_id():
    assert calls_name(edt(2026, 10, 8, 5, 31, 0, 250000), 1) == "calls_20261008T053100EDT_1.json"
    assert calls_name(est(2026, 1, 29, 12, 0), 12) == "calls_20260129T120000EST_12.json"
    assert transcript_name(248001) == "transcript_248001.json"
    assert transcript_name(248001, edt(2026, 10, 8, 5, 45, 6, 500000)) == REFRESHED_Q2
    for page in (0, 21, True):
        with pytest.raises(ValueError, match="^a calls page is a number from 1 to 20$"):
            calls_name(NOW, page)
    for call_id in (0, 10**12 + 1, True):
        with pytest.raises(ValueError, match="^a call id is a whole number from 1 to 1000000000000$"):
            transcript_name(call_id)


@pytest.mark.parametrize(
    ("kind", "name", "layout_read"),
    [
        ("call", "transcript_248001.json", False),
        ("filing", "intc-20260627.htm", False),
        ("filing", "0000950123-09-000001.txt", True),
        ("exhibit", "ex99.TXT", True),
        ("exhibit", "ex99.htm", False),
        ("8-K", "intc-20260723.htm", False),
        ("8-K", "intc-20260723.txt", True),
    ],
)
def test_layout_mode_follows_the_documents_kind_and_name_alone(tmp_path, kind, name, layout_read):
    document = Document("id", kind, date(2026, 6, 27), tmp_path / name, "label")
    assert layout_mode(document) is layout_read
    assert document.text_name == "id.md"


# --------------------------------------------------------------------------- the tree fetch writes


def test_fetch_writes_the_company_files_at_the_top_and_each_seasons_documents_in_its_folder(layout):
    fetch(layout)
    root = layout.raw(TICKER)

    written = sorted(str(path.relative_to(root)) for path in root.rglob("*") if path.is_file())

    assert written == sorted([SUBMISSIONS, CAPTURE, *RAW.values()])
    assert (root / SUBMISSIONS).read_bytes() == submissions_json().encode()
    assert (root / CAPTURE).read_bytes() == events_page()
    for role in RAW:
        assert raw_file(layout, role).read_bytes() == raw_bytes(role)


def test_the_seasons_come_from_the_newest_submissions_with_every_document_fetch_wrote(layout):
    fetch(layout)

    raw = state(layout)

    assert (raw.ticker, raw.cik, raw.entity_name, raw.reason, raw.invalid_files, raw.unlisted) == (
        TICKER,
        CIK,
        ENTITY_NAME,
        None,
        (),
        (),
    )
    assert (raw.submissions, raw.former_layout) == (raw_path(layout, SUBMISSIONS), ())
    assert [files.day.isoformat() for files in raw.seasons] == list(SEASON_DOCUMENTS)
    for files in raw.seasons:
        assert files.folder == raw_path(layout, files.day.isoformat())
        assert files.missing is None
        assert files.call.settled
        roles = SEASON_DOCUMENTS[files.day.isoformat()]
        assert [document.doc_id for document in files.documents] == [DOC_IDS[role] for role in roles]
        assert [document.path for document in files.documents] == [
            raw_file(layout, TRANSCRIPTS.get(role, role)) for role in roles
        ]
    assert raw.documents().keys() == set(DOC_IDS.values())


def test_each_document_names_its_kind_season_filing_and_label(layout):
    fetch(layout)

    by_id = state(layout).documents()

    assert by_id[DOC_IDS["ten_q_2"]] == Document(
        DOC_IDS["ten_q_2"],
        "filing",
        Q2,
        raw_file(layout, "ten_q_2"),
        "10-Q for the period ended 2026-06-27",
        "10-Q",
        "0000050863-26-000064",
        date(2026, 7, 24),
    )
    assert by_id[DOC_IDS["eight_k_other"]] == Document(
        DOC_IDS["eight_k_other"],
        "8-K",
        FISCAL_YEAR,
        raw_file(layout, "eight_k_other"),
        "8-K dated 2026-02-09 (items 5.02,9.01)",
        "8-K",
        "0000050863-26-000020",
        date(2026, 2, 10),
    )
    assert by_id[DOC_IDS["exhibit_2_2"]] == Document(
        DOC_IDS["exhibit_2_2"],
        "exhibit",
        Q2,
        raw_file(layout, "exhibit_2_2"),
        "EX-99.2 of the 8-K dated 2026-07-23 (q226cfocommentary.htm)",
        "8-K",
        "0000050863-26-000062",
        date(2026, 7, 23),
    )


def test_an_8_k_needs_its_index_page_its_primary_document_and_the_exhibits_the_page_lists(layout):
    fetch(layout)

    q2, fiscal_year = season_of(layout, Q2), season_of(layout, FISCAL_YEAR)

    (release,) = q2.filings
    what = "of the 8-K 0000050863-26-000062 dated 2026-07-23"
    assert (release.item.accession, release.folder, release.index_valid) == (
        EIGHT_K_Q2.accession,
        raw_path(layout, "2026-06-27/8-K_2026-07-23_0000050863-26-000062"),
        True,
    )
    assert [(row.exhibit, row.sequence, row.document) for row in release.exhibits] == [
        ("EX-99.1", 2, "q226earningsrelease.htm"),
        ("EX-99.2", 3, "q226cfocommentary.htm"),
    ]
    assert release.needed == (
        Needed(f"filing index page {what}", raw_file(layout, "index_2"), True),
        Needed(f"primary document {what}", raw_file(layout, "eight_k_2"), True),
        Needed(f"EX-99.1 q226earningsrelease.htm {what}", raw_file(layout, "exhibit_2_1"), True),
        Needed(f"EX-99.2 q226cfocommentary.htm {what}", raw_file(layout, "exhibit_2_2"), True),
    )
    assert [document.doc_id for document in release.documents] == [
        DOC_IDS[role] for role in ("eight_k_2", "exhibit_2_1", "exhibit_2_2")
    ]
    # An 8-K whose page lists no exhibit needs its page and primary document; the proxy statement
    # EDGAR lists in the season is no filing the domain reads.
    (officers,) = fiscal_year.filings
    assert (officers.item.accession, officers.exhibits, officers.index_valid) == (
        EIGHT_K_OTHER.accession,
        (),
        True,
    )
    assert [needed.path for needed in officers.needed] == [
        raw_file(layout, "index_other"),
        raw_file(layout, "eight_k_other"),
    ]


def test_an_8_ks_exhibits_come_from_its_index_page_on_every_read(layout):
    fetch(layout)
    place(raw_file(layout, "index_2"), filing_index_html(EIGHT_K_Q2, Q2_EXHIBITS[:1]))

    q2 = season_of(layout, Q2)

    (release,) = q2.filings
    assert [row.document for row in release.exhibits] == ["q226earningsrelease.htm"]
    assert DOC_IDS["exhibit_2_2"] not in [document.doc_id for document in q2.documents]
    assert q2.missing is None


# --------------------------------------------------------------------------- seasons of a window


def test_within_span_and_season_select_listed_seasons_oldest_first(layout):
    plant_submissions(layout, FETCHED_AT, LONGER_RECENT)

    raw = state(layout)

    def days(found: tuple[SeasonFiles, ...]) -> list[str]:
        return [files.day.isoformat() for files in found]

    listed = [
        "2024-12-28",
        "2025-03-29",
        "2025-06-28",
        "2025-09-27",
        "2025-12-27",
        "2026-03-28",
        "2026-06-27",
    ]
    assert days(raw.seasons) == listed
    assert (days(raw.within(WINDOW)), days(raw.span(WINDOW))) == (listed[4:], listed)
    newest = Window(date(2026, 6, 1), TODAY)
    assert (days(raw.within(newest)), days(raw.span(newest))) == (listed[6:], listed[2:])  # four before it
    middle = Window(date(2025, 6, 1), date(2025, 6, 30))
    assert (days(raw.within(middle)), days(raw.span(middle))) == (["2025-06-28"], listed[:3])
    later = Window(date(2026, 7, 1), TODAY)
    assert (raw.within(later), raw.span(later)) == ((), ())
    assert raw.season(date(2025, 3, 29)) is raw.seasons[1]
    assert raw.season(date(2025, 3, 30)) is None


def test_every_listed_season_is_listed_even_without_its_documents(layout):
    fetch(layout)
    plant_submissions(layout, edt(2026, 10, 8, 5, 45), LATER_RECENT)

    raw = state(layout)

    newest = raw.seasons[-1]
    assert (newest.day, newest.filing, newest.filings, newest.documents) == (date(2026, 9, 26), None, (), ())
    path = raw_path(layout, "2026-09-26/10-Q_2026-09-26_0000050863-26-000090/intc-20260926.htm")
    assert newest.filing_path == path
    assert newest.missing == (
        f"the 10-Q 0000050863-26-000090 for the period ended 2026-09-26 is not in raw/ ({path}); run fetch"
    )
    assert raw.invalid_files == ()


def test_the_newest_submissions_place_every_filing_again_by_rule_b(layout):
    fetch(layout)
    listing = state(layout).listing
    assert listing is not None
    # The 8-K of 2026-07-30 is dated after the newest season's 10-Q was filed: pending.
    assert [item.accession for item in listing.pending] == [PENDING_8K.accession]
    newer = plant_submissions(layout, edt(2026, 10, 8, 5, 45), LATER_RECENT)

    raw = state(layout)

    assert raw.submissions == newer
    assert raw.listing is not None and raw.listing.pending == ()
    q2 = season_of(layout, Q2)
    assert [(item.form, item.accession) for item in q2.season.fetched] == [
        ("8-K", EIGHT_K_Q2.accession),
        ("8-K", PENDING_8K.accession),
    ]
    index = raw_path(layout, "2026-06-27/8-K_2026-07-30_0000050863-26-000066/0000050863-26-000066-index.htm")
    assert q2.missing == (
        "the filing index page of the 8-K 0000050863-26-000066 dated 2026-07-30 is not in raw/ "
        f"({index}); run fetch"
    )


@pytest.mark.parametrize(
    ("name", "reason"),
    [
        pytest.param(
            "submissions_20261008T070000EDT.json",
            "submissions: cik must be a string of up to ten digits or an integer",
            id="submissions",
        ),
        pytest.param(
            "calls_20261008T070000EDT_1.json",
            "calls list: invalid JSON: Expecting value (line 1, column 1)",
            id="calls",
        ),
    ],
)
def test_a_file_named_after_the_clock_is_not_read_until_the_clock_reaches_it(layout, name, reason):
    fetch(layout)
    place(raw_path(layout, name), b"not even JSON")

    assert state(layout).invalid_files == ()
    assert invalid(layout, edt(2026, 10, 8, 7, 0)) == {name: reason}


def test_without_a_submissions_file_no_season_is_listed(layout):
    raw = state(layout)

    assert (raw.submissions, raw.reason, raw.listing, raw.seasons, raw.invalid_files) == (
        None,
        "no submissions file is in raw/; run fetch",
        None,
        (),
        (),
    )
    assert (raw.capture, raw.capture_problem) == (None, NO_CAPTURE)
    assert raw.events_due(WINDOW, NOW) is None  # nothing to weigh without a season


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
def test_a_newest_submissions_file_that_does_not_parse_is_invalid_and_lists_no_season(layout, body, reason):
    path = place(raw_path(layout, "submissions_20261008T053001EDT.json"), body)

    raw = state(layout)

    assert raw.invalid_files == ((path, reason),)
    assert (raw.seasons, raw.listing, raw.cik) == ((), None, None)
    assert raw.reason == f"{path.name} is invalid (see invalid_files); rename it with .rejected and run fetch"


@pytest.mark.parametrize(
    ("rows", "reason"),
    [
        pytest.param(
            (Row("8-K", "0000050863-26-000001", date(2026, 1, 2), date(2026, 1, 2), "a.htm", "8.01"),),
            "no 10-K or 10-Q among the 1 recent filings; forms seen: 8-K",
            id="no-season",
        ),
        pytest.param(
            (
                *RECENT[:2],
                Row("8-K", EIGHT_K_Q2.accession, EIGHT_K_Q2.filed, None, "a.htm", "2.02"),
                *RECENT[3:],
            ),
            f"submissions CIK{CIK}: filings.recent.reportDate[2] is empty; an 8-K with Item 2.02 must name "
            "its event date",
            id="undated-release",
        ),
    ],
)
def test_submissions_whose_seasons_cannot_be_listed_give_the_reason_without_an_invalid_file(
    layout, rows, reason
):
    plant_submissions(layout, FETCHED_AT, rows)

    raw = state(layout)

    assert (raw.reason, raw.seasons, raw.listing, raw.invalid_files) == (reason, (), None, ())
    assert raw.cik == CIK  # the body itself reads


# --------------------------------------------------------------------------- missing and invalid documents


@pytest.mark.parametrize(
    ("role", "season", "what"),
    [
        pytest.param("ten_q_2", Q2, "10-Q 0000050863-26-000064 for the period ended 2026-06-27", id="filing"),
        pytest.param(
            "index_2", Q2, "filing index page of the 8-K 0000050863-26-000062 dated 2026-07-23", id="index"
        ),
        pytest.param(
            "eight_k_2", Q2, "primary document of the 8-K 0000050863-26-000062 dated 2026-07-23", id="8-K"
        ),
        pytest.param(
            "exhibit_2_2",
            Q2,
            "EX-99.2 q226cfocommentary.htm of the 8-K 0000050863-26-000062 dated 2026-07-23",
            id="exhibit",
        ),
    ],
)
def test_a_missing_document_names_itself_as_the_first_one_to_fetch(layout, role, season, what):
    fetch(layout)
    path = raw_file(layout, role)
    path.unlink()

    files = season_of(layout, season)

    assert files.missing == f"the {what} is not in raw/ ({path}); run fetch"
    assert path not in [document.path for document in files.documents]


def test_without_its_index_page_an_8_ks_exhibits_are_unknown(layout):
    fetch(layout)
    raw_file(layout, "index_2").unlink()

    (release,) = season_of(layout, Q2).filings

    assert (release.index_valid, release.exhibits) == (False, ())
    assert [needed.present for needed in release.needed] == [False, True]
    assert [document.doc_id for document in release.documents] == [DOC_IDS["eight_k_2"]]


def test_an_index_page_that_does_not_parse_is_invalid_and_its_exhibits_unknown(layout):
    fetch(layout)
    path = place(raw_file(layout, "index_2"), "<html><body>no table</body></html>")

    raw = state(layout)

    assert raw.invalid_files == (
        (
            path,
            'filing index 0000050863-26-000062: no tableFile table with the summary "Document Format Files"',
        ),
    )
    q2 = raw.season(Q2)
    assert q2 is not None
    (release,) = q2.filings
    assert (release.index_valid, release.exhibits) == (False, ())
    assert [document.doc_id for document in q2.documents] == [
        DOC_IDS["ten_q_2"],
        DOC_IDS["eight_k_2"],
        DOC_IDS["call_q2"],
    ]


def test_an_index_page_that_does_not_parse_leaves_its_seasons_documents_incomplete(layout):
    fetch(layout)
    place(raw_file(layout, "index_2"), "<html><body>no table</body></html>")

    assert season_of(layout, Q2).missing == (
        "the filing index page of the 8-K 0000050863-26-000062 dated 2026-07-23 in raw/ is invalid "
        "(see invalid_files); rename it with .rejected and run fetch"
    )


@pytest.mark.parametrize("kind", ["folder", "link"])
def test_an_edgar_document_that_is_not_a_regular_file_is_invalid(layout, tmp_path, kind):
    fetch(layout)
    path = raw_file(layout, "ten_k")
    target = place(tmp_path / "elsewhere.htm", path.read_bytes())
    path.unlink()
    if kind == "folder":
        path.mkdir()
    else:
        os.symlink(target, path)

    raw = state(layout)

    assert raw.invalid_files == ((path, NOT_REGULAR),)
    files = raw.season(FISCAL_YEAR)
    assert files is not None and files.filing is None
    assert files.missing == (
        "the 10-K 0000050863-26-000012 for the period ended 2025-12-27 in raw/ is invalid "
        "(see invalid_files); rename it with .rejected and run fetch"
    )


def test_a_file_where_a_filings_folder_belongs_is_invalid(layout):
    fetch(layout)
    folder = raw_file(layout, "ten_k").parent
    shutil.rmtree(folder)
    place(folder, b"x")

    raw = state(layout)

    assert set(raw.invalid_files) == {(folder, NOT_A_FOLDER)}
    files = raw.season(FISCAL_YEAR)
    assert files is not None and files.filing is None
    assert files.missing == (
        "the 10-K 0000050863-26-000012 for the period ended 2025-12-27 in raw/ is invalid "
        "(see invalid_files); rename it with .rejected and run fetch"
    )


def test_a_file_where_a_filings_folder_belongs_is_listed_once(layout):
    fetch(layout)
    folder = raw_file(layout, "ten_k").parent
    shutil.rmtree(folder)
    place(folder, b"x")

    assert state(layout).invalid_files == ((folder, NOT_A_FOLDER),)


def test_a_file_where_a_seasons_folder_belongs_is_the_one_invalid_file(layout):
    fetch(layout)
    folder = raw_path(layout, "2026-06-27")
    shutil.rmtree(folder)
    place(folder, b"x")

    assert invalid(layout) == {"2026-06-27": NOT_A_FOLDER}


def test_doc_ids_that_differ_only_in_letter_case_collide(tmp_path):
    def document(name: str) -> Document:
        return Document(name, "exhibit", Q2, tmp_path / name, name)

    class Files:  # the one attribute _repeated_ids reads
        def __init__(self, *names: str) -> None:
            self.documents = tuple(document(name) for name in names)

    found = list(documents._repeated_ids((Files("8-K_x_ex99", "8-K_x_EX99"), Files("8-K_x_Ex99"))))

    assert found == [
        (tmp_path / "8-K_x_EX99", "its DOC_ID 8-K_x_EX99 is already another document's"),
        (tmp_path / "8-K_x_Ex99", "its DOC_ID 8-K_x_Ex99 is already another document's"),
    ]


# --------------------------------------------------------------------------- moved, unlisted, not raw


def test_a_late_10_q_moves_the_filing_and_the_call_rule_b_placed_before_it(layout):
    # EDGAR lists the 10-Q for the quarter ended 2026-03-28 late: its release and call land in the
    # fiscal year's season, then move to their own once the 10-Q is listed.
    fetch(layout, edgar(rows=tuple(row for row in RECENT if row is not TEN_Q_1)))
    assert raw_path(layout, "2025-12-27/8-K_2026-04-23_0000050863-26-000040").is_dir()
    assert raw_path(layout, "2025-12-27/transcript_26083.json").is_file()
    plant_submissions(layout, edt(2026, 10, 8, 5, 45))

    raw = state(layout)

    assert invalid(layout) == {
        "2025-12-27/8-K_2026-04-23_0000050863-26-000040": (
            "the newest submissions place this filing in the season 2026-03-28, not in this season; "
            "rename it with .rejected and run fetch"
        ),
        "2025-12-27/transcript_26083.json": (
            "the newest calls list places this call in the season 2026-03-28, not in this season; "
            "rename it with .rejected and run fetch"
        ),
    }
    q1 = raw.season(Q1)
    assert q1 is not None
    ten_q = raw_path(layout, "2026-03-28/10-Q_2026-03-28_0000050863-26-000041/intc-20260328.htm")
    assert q1.missing == (
        f"the 10-Q 0000050863-26-000041 for the period ended 2026-03-28 is not in raw/ ({ten_q}); run fetch"
    )
    transcript = raw_path(layout, "2026-03-28/transcript_26083.json")
    assert (q1.call.status, q1.call.reason) == (
        "missing",
        f"the transcript of the call 26083 (2026-04-23) is not in raw/ ({transcript}); run fetch",
    )
    fiscal_year = raw.season(FISCAL_YEAR)
    assert fiscal_year is not None
    assert [item.accession for item in fiscal_year.season.fetched] == [EIGHT_K_OTHER.accession]
    assert fiscal_year.missing is None


def test_a_filing_folder_where_rule_b_does_not_place_it_is_moved_or_misnamed(layout):
    fetch(layout)
    placed = {
        "2026-06-27/8-K_2026-07-30_0000050863-26-000066": "pending",
        "2026-06-27/8-K_2026-02-09_0000050863-26-000020": "in the season 2025-12-27",
        "2026-06-27/10-Q_2026-03-28_0000050863-26-000041": "in the season 2026-03-28",
    }
    for folder in placed:
        raw_path(layout, folder).mkdir()
    raw_path(layout, "2025-12-27/8-K_2026-02-10_0000050863-26-000020").mkdir()

    assert invalid(layout) == {
        **{
            folder: (
                f"the newest submissions place this filing {where}, not in this season; rename it with "
                ".rejected and run fetch"
            )
            for folder, where in placed.items()
        },
        "2025-12-27/8-K_2026-02-10_0000050863-26-000020": (
            "the newest submissions name this filing's folder 8-K_2026-02-09_0000050863-26-000020; "
            "rename it with .rejected and run fetch"
        ),
    }
    assert [files.missing for files in state(layout).seasons] == [None] * 5


def test_a_filing_or_transcript_the_newest_listing_does_not_hold_is_unlisted_and_left_out(layout):
    fetch(layout)
    folder = place(raw_path(layout, "2026-06-27/8-K_2026-07-01_0000050863-26-099999/x.htm"), b"x").parent
    transcript = place(raw_path(layout, "2026-06-27/transcript_999.json"), b"anything")

    raw = state(layout)

    assert (raw.unlisted, raw.invalid_files) == ((folder, transcript), ())
    assert [document.doc_id for document in season_of(layout, Q2).documents] == [
        DOC_IDS[role] for role in SEASON_DOCUMENTS["2026-06-27"]
    ]


def test_entries_fetch_does_not_write_are_invalid(layout):
    fetch(layout)
    top = (
        "notes.txt",
        "submissions.json",
        "submissions_20261008T253000EDT.json",  # no such time
        "companyfacts_20261008T053018.json",  # no zone
        "measures_20261008T053018EDT.json",  # no file fetch ever wrote
        "calls_20261008T053100EDT_0.json",  # no page 0
        "calls_20261008T053100EDT.json",  # no page
        "2026-02-30",  # no such day
        "edgar",  # a file: the former layout is a folder
    )
    in_season = (
        "notes.txt",
        "transcript_0.json",
        "transcript_248001.json.bak",
        "transcript_248001_20261008T253000EDT.json",  # no such time
        "transcript_248001_20261008T054506.json",  # no zone
        "10-Q_2026-06-27_0000050863-26-000064.zip",
        "10-K405_2026-06-27_0000050863-26-000064",  # no form fetch writes or wrote
        "DEFA14A_2026-06-27_0000050863-26-000064",
    )
    for name in top:
        place(raw_path(layout, name), b"x")
    for name in in_season:
        place(raw_path(layout, f"2026-06-27/{name}"), b"x")
    raw_path(layout, "companyfacts_20261008T040000EDT.json").mkdir()
    raw_path(layout, f"2026-06-27/{REFRESHED_Q2}").mkdir()

    assert invalid(layout) == {
        **{name: NOT_RAW for name in top},
        **{f"2026-06-27/{name}": NOT_RAW_IN_Q2 for name in in_season},
        "companyfacts_20261008T040000EDT.json": NOT_REGULAR,
        f"2026-06-27/{REFRESHED_Q2}": NOT_REGULAR,
    }


def test_season_folders_the_newest_submissions_do_not_list_are_invalid_unless_older_than_every_season(layout):
    fetch(layout)
    place(raw_path(layout, "2023-12-30/10-K_2023-12-30_0000050863-24-000010/intc-20231230.htm"), b"x")
    raw_path(layout, "2026-01-15").mkdir()

    raw = state(layout)

    assert invalid(layout) == {"2026-01-15": NOT_A_SEASON}
    assert (raw.unlisted, raw.former_layout) == ((), ())


def test_the_former_layout_is_listed_and_never_read(layout):
    fetch(layout)
    folders = plant_former_layout(layout)

    raw = state(layout)

    assert raw.former_layout == tuple(sorted(folders))  # calls/, then edgar/
    assert (raw.invalid_files, raw.unlisted) == ((), ())
    assert [files.missing for files in raw.seasons] == [None] * 5


def test_names_ending_in_rejected_and_dotfiles_are_skipped(layout):
    fetch(layout)
    place(raw_path(layout, "stray.pdf.rejected"), b"x")
    place(raw_path(layout, ".DS_Store"), b"x")
    place(raw_path(layout, "2026-06-27/.DS_Store"), b"x")
    raw_path(layout, "edgar.rejected").mkdir()
    release = raw_file(layout, "index_2").parent
    release.rename(release.with_name(release.name + ".rejected"))
    transcript = raw_file(layout, "transcript_q1")
    transcript.rename(transcript.with_name(transcript.name + ".rejected"))
    raw_path(layout, "2024-12-28").rename(raw_path(layout, "2024-12-28.rejected"))

    raw = state(layout)

    assert (raw.invalid_files, raw.unlisted, raw.former_layout) == ((), (), ())
    missing = [files.missing for files in raw.seasons]
    assert missing[0] == (
        "the 10-K 0000050863-25-000009 for the period ended 2024-12-28 is not in raw/ "
        f"({raw_file(layout, 'old_ten_k')}); run fetch"
    )
    assert missing[4] == (
        "the filing index page of the 8-K 0000050863-26-000062 dated 2026-07-23 is not in raw/ "
        f"({raw_file(layout, 'index_2')}); run fetch"
    )
    q1 = season_of(layout, Q1).call
    assert (q1.status, q1.reason) == (
        "missing",
        "the transcript of the call 26083 (2026-04-23) is not in raw/ "
        f"({raw_file(layout, 'transcript_q1')}); run fetch",
    )


# --------------------------------------------------------------------------- retired files


def test_the_company_facts_and_the_folders_of_forms_no_longer_read_are_unlisted_and_left_out(layout):
    fetch(layout)
    facts = place(raw_path(layout, "companyfacts_20261008T053018EDT.json"), b"not even JSON")
    folders = [
        place(raw_path(layout, f"{relative}/document"), b"x").parent
        for relative in (
            "2025-12-27/DEF14A_2026-03-27_0001193125-26-112233",
            "2026-03-28/4_2026-04-30_0001209191-26-050505",
            "2026-03-28/SC13DA_2026-05-08_0000950103-26-004322",
            "2026-03-28/SC13GA_2026-05-08_0000950103-26-004321",
            "2026-03-28/SCHEDULE13DA_2026-05-12_0001104659-26-054322",
            "2026-03-28/SCHEDULE13GA_2026-05-12_0001104659-26-054321",
        )
    ]
    place(raw_path(layout, "companyfacts_20261008T070000EDT.json"), b"x")  # named after the clock

    raw = state(layout)

    assert (raw.unlisted, raw.invalid_files) == ((facts, *folders), ())
    assert [files.missing for files in raw.seasons] == [None] * 5
    assert [document.doc_id for document in season_of(layout, Q1).documents] == [
        DOC_IDS[role] for role in SEASON_DOCUMENTS["2026-03-28"]
    ]


# --------------------------------------------------------------------------- calls


def test_the_newest_calls_list_places_each_call_in_its_season_by_rule_b(layout):
    fetch(layout)

    raw = state(layout)

    assert (raw.invalid_files, raw.unlisted, raw.pending_calls, raw.capture_problem) == ((), (), (), None)
    capture = raw.capture
    assert capture is not None
    assert (capture.fetched_at, capture.day, capture.pages) == (
        edt(2026, 10, 8, 5, 31),  # the token's time, to the second
        date(2026, 10, 8),
        (raw_path(layout, CAPTURE),),
    )
    assert [call.id for call in capture.calls] == [call.id for call in CALLS]  # newest first, as listed
    calls = {files.day.isoformat(): files.call for files in raw.seasons}
    assert {
        day: (call.status, [event.id for event in call.events], call.due.isoformat(), call.as_of, call.reason)
        for day, call in calls.items()
    } == {
        "2024-12-28": ("unavailable", [], "2025-01-31", TODAY, None),  # 64251 is before it: dropped
        "2025-09-27": ("transcript", [CALL_OLD_Q.id], "2025-10-31", TODAY, None),
        "2025-12-27": ("unavailable", [], "2026-01-30", TODAY, None),
        "2026-03-28": ("transcript", [CALL_Q1.id], "2026-04-23", TODAY, None),
        "2026-06-27": ("transcript", [CALL_Q2.id], "2026-07-23", TODAY, None),
    }
    assert {call.settled for call in calls.values()} == {True}
    assert raw.transcript_files == {
        CALL_OLD_Q.id: raw_file(layout, "transcript_old_q"),
        CALL_Q1.id: raw_file(layout, "transcript_q1"),
        CALL_Q2.id: raw_file(layout, "transcript_q2"),
    }


def test_a_seasons_call_is_due_by_its_latest_release_else_by_its_filing(layout):
    fetch(layout)
    listing = state(layout).listing
    assert listing is not None

    # The 8-K of 2026-02-09 names no Item 2.02: the fiscal year's call is due by its 10-K's filing.
    assert [due_date(season) for season in listing.seasons] == [
        OLD_TEN_K.filed,
        OLD_TEN_Q.filed,
        TEN_K.filed,
        date(2026, 4, 23),
        date(2026, 7, 23),
    ]


def test_a_call_document_names_its_transcript_and_the_listed_call(layout):
    fetch(layout)

    call = season_of(layout, Q2).call

    (document,) = call.documents
    assert document.call is not None
    assert document == Document(
        doc_id="call_2026-06-27_248001",
        kind="call",
        season=Q2,
        path=raw_file(layout, "transcript_q2"),
        label="earnings call 2026-07-23: Intel Corporation - Q2 2026 Earnings Call",
        title="Intel Corporation - Q2 2026 Earnings Call",
        call=document.call,
    )
    event = document.call
    assert (event.id, event.at, event.day, event.fiscal_year, event.fiscal_quarter) == (
        CALL_Q2.id,
        edt(2026, 7, 23, 17, 0),  # 21:00 UTC
        date(2026, 7, 23),
        2026,
        2,
    )
    (transcript,) = call.transcripts
    assert (transcript.title, transcript.at, transcript.duration_seconds, len(transcript.turns)) == (
        "Intel Corporation - Q2 2026 Earnings Call",
        edt(2026, 7, 23, 17, 0),
        3525,
        7,
    )
    assert document.text_name == "call_2026-06-27_248001.md"


def test_without_a_calls_list_every_seasons_call_is_missing_and_its_transcripts_unlisted(layout):
    edgar_only(layout)

    raw = state(layout)

    assert (raw.capture, raw.capture_problem, raw.invalid_files) == (None, NO_CAPTURE, ())
    assert {(files.call.status, files.call.reason, files.call.as_of) for files in raw.seasons} == {
        ("missing", NO_CAPTURE, None)
    }
    assert raw.unlisted == tuple(
        raw_file(layout, role) for role in ("transcript_old_q", "transcript_q1", "transcript_q2")
    )
    assert raw.events_due(WINDOW, NOW) == NO_CAPTURE


def test_a_season_without_a_listed_call_waits_until_seven_days_after_its_due_date(layout):
    plant_submissions(layout, FETCHED_AT)
    rows = [call_row(CALL_Q1), call_row(CALL_OLD_Q)]  # the quarter ended 2026-06-27 has no call listed yet
    plant_capture(layout, events_page(rows), at=edt(2026, 7, 29, 23, 59, 59))

    call = season_of(layout, Q2).call

    assert (call.status, call.due, call.as_of, call.events, call.documents, call.settled) == (
        "waiting",
        date(2026, 7, 23),  # the release's report date
        date(2026, 7, 29),
        (),
        (),
        False,
    )
    assert call.reason == (
        "EarningsCalls.dev lists no call for the season as of 2026-07-29; a list fetched on or after "
        "2026-07-30 that lists none shows it unavailable"
    )

    plant_capture(layout, events_page(rows), at=edt(2026, 7, 30, 0, 0))  # a newer list, 7 days on

    call = season_of(layout, Q2).call
    assert (call.status, call.as_of, call.reason, call.settled) == (
        "unavailable",
        date(2026, 7, 30),
        None,
        True,
    )


def test_a_season_without_a_release_is_due_by_its_filing_date(layout):
    edgar_only(layout)
    plant_capture(layout, events_page([]), at=est(2026, 2, 5, 12, 0))

    call = season_of(layout, FISCAL_YEAR).call

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
        "season 2025-12-27"
    )
    # A window whose calls are all transcripts never asks again, nor one that holds no listed season.
    assert raw.events_due(Window(date(2026, 3, 1), TODAY), edt(2027, 1, 1)) is None
    assert raw.events_due(Window(date(2026, 7, 1), TODAY), edt(2027, 1, 1)) is None


def test_a_list_fetched_on_or_before_a_seasons_due_date_is_due_once_that_date_has_passed(layout):
    # EDGAR as of the 10-K's filing day: the fiscal year ended 2025-12-27 is the newest season, without
    # a release, so its call is due by the 10-K's filing date, 2026-01-30.
    plant_submissions(layout, est(2026, 1, 30, 18, 0), rows=(TEN_K, OLD_TEN_Q, OLD_TEN_K))
    plant_capture(layout, events_page([]), at=est(2026, 1, 29, 12, 0))
    on_the_day, after = est(2026, 1, 30, 20, 0), est(2026, 1, 31, 6, 0)

    assert season_of(layout, FISCAL_YEAR, on_the_day).call.status == "waiting"
    assert state(layout, on_the_day).events_due(WINDOW, on_the_day) is None  # the due date has not passed
    assert state(layout, after).events_due(WINDOW, after) == (
        "the newest calls list was fetched 2026-01-29, on or before the season 2025-12-27's due date "
        "2026-01-30"
    )
    plant_capture(layout, events_page([]), at=after)  # asked again: no call yet, and not due again
    assert state(layout, after).events_due(WINDOW, after) is None


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
    path = plant_capture(layout, page)

    raw = state(layout)

    assert raw.invalid_files == ((path, reason),)
    assert (raw.capture, raw.capture_problem) == (None, INVALID_CAPTURE)
    assert {(files.call.status, files.call.reason) for files in raw.seasons} == {("missing", INVALID_CAPTURE)}
    assert raw.events_due(WINDOW, NOW) == INVALID_CAPTURE


def test_a_capture_without_its_first_page_is_invalid(layout):
    edgar_only(layout)
    path = plant_capture(layout, events_page(page=2, total=150), number=2)

    assert invalid(layout) == {
        path.name: "page 1 of this calls capture is not in raw/; rename the capture's pages with .rejected"
    }


def test_a_capture_of_several_pages_is_read_in_page_order(layout):
    edgar_only(layout)
    first = [
        call_row(Call(1000 + number, f"2026-0{1 + number % 9}-01T21:00:00.000Z", "", None, None, ""))
        for number in range(100)
    ]
    second = [call_row(CALL_Q2), call_row(CALL_Q1)]
    one = plant_capture(layout, events_page(first, total=102))
    two = plant_capture(layout, events_page(second, page=2, total=102), number=2)

    raw = state(layout)

    assert raw.capture is not None and raw.capture.pages == (one, two)
    assert [call.id for call in raw.capture.calls][-2:] == [CALL_Q2.id, CALL_Q1.id]
    assert CALL_Q2.id in [event.id for event in season_of(layout, Q2).call.events]


def test_only_the_newest_capture_is_read(layout):
    fetch(layout)
    plant_capture(layout, b"not json", at=edt(2026, 10, 1, 9, 0))  # older, invalid, never read

    assert state(layout).invalid_files == ()
    assert state(layout).capture is not None


def test_the_newest_copy_of_a_transcript_is_read_and_an_older_one_never(layout):
    fetch(layout)
    # The first copy no longer reads, and fetch --refresh wrote a later one under another title.
    plant_transcript(layout, CALL_Q2, Q2, b"not json")
    newer = plant_transcript(
        layout,
        CALL_Q2,
        Q2,
        transcript_body(CALL_Q2, header={"title": CORRECTED_TITLE}),
        at=edt(2026, 10, 8, 5, 45, 6),
    )

    raw = state(layout)

    assert newer.name == REFRESHED_Q2
    assert raw.invalid_files == ()
    assert raw.transcript_files[CALL_Q2.id] == newer
    (document,) = season_of(layout, Q2).call.documents
    assert (document.path, document.title, document.doc_id) == (newer, CORRECTED_TITLE, DOC_IDS["call_q2"])


def test_a_transcript_copy_named_after_now_is_not_read_yet(layout):
    fetch(layout)
    seven = edt(2026, 10, 8, 7, 0)
    later = plant_transcript(layout, CALL_Q2, Q2, b"{}", at=seven)

    assert state(layout).invalid_files == ()
    assert state(layout).transcript_files[CALL_Q2.id] == raw_file(layout, "transcript_q2")
    # Once the clock reaches its token it is the newest copy: invalid, so the call is missing.
    assert invalid(layout, seven) == {f"2026-06-27/{later.name}": "transcript: data: Field required"}


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
    path = plant_transcript(layout, CALL_Q2, Q2, body)

    raw = state(layout)

    assert raw.invalid_files == ((path, reason),)
    call = season_of(layout, Q2).call
    assert (call.status, call.documents, call.transcripts, call.reason) == (
        "missing",
        (),
        (),
        TRANSCRIPT_Q2_INVALID,
    )


def test_a_symbolic_link_is_not_a_transcript(layout, tmp_path):
    fetch(layout)
    path = raw_file(layout, "transcript_q2")
    target = place(tmp_path / "elsewhere.json", path.read_bytes())
    path.unlink()
    os.symlink(target, path)

    assert invalid(layout) == {"2026-06-27/transcript_248001.json": NOT_REGULAR}


def test_a_call_after_the_newest_seasons_filing_is_pending_until_rule_b_places_it(layout):
    fetch(layout)
    rows = [call_row(CALL_Q3), *(call_row(call) for call in CALLS)]
    plant_capture(layout, events_page(rows), at=edt(2026, 10, 8, 5, 50))

    raw = state(layout)

    assert [event.id for event in raw.pending_calls] == [CALL_Q3.id]
    assert raw.pending_in(WINDOW) == raw.pending_calls
    assert raw.pending_in(Window(date(2025, 12, 1), date(2026, 6, 26))) == ()
    assert raw.invalid_files == ()

    plant_submissions(layout, edt(2026, 10, 8, 5, 55), LATER_RECENT)

    raw = state(layout)
    assert raw.pending_calls == ()
    newest = raw.season(date(2026, 9, 26))
    assert newest is not None
    path = raw_path(layout, "2026-09-26/transcript_250001.json")
    assert (newest.call.status, [event.id for event in newest.call.events], newest.call.reason) == (
        "missing",
        [CALL_Q3.id],
        f"the transcript of the call 250001 (2026-10-06) is not in raw/ ({path}); run fetch",
    )


def test_without_listed_seasons_the_calls_list_is_still_validated(layout):
    path = plant_capture(layout, b"not json")

    raw = state(layout)

    assert (raw.reason, raw.seasons) == ("no submissions file is in raw/; run fetch", ())
    assert raw.invalid_files == ((path, "calls list: invalid JSON: Expecting value (line 1, column 1)"),)
    assert raw.capture_problem == INVALID_CAPTURE
    assert raw.events_due(WINDOW, NOW) is None  # nothing to weigh without a season


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


def test_reading_the_raw_tree_writes_nothing(layout):
    fetch(layout)
    before = snapshot(layout.root)

    state(layout)
    state(layout, edt(2027, 1, 1))

    assert snapshot(layout.root) == before


# --------------------------------------------------------------------------- derived text


def test_derived_text_of_edgar_documents(layout):
    fetch(layout)
    by_id = state(layout).documents()

    assert derive_text(by_id[DOC_IDS["ten_q_2"]]) == html_text(raw_bytes("ten_q_2").decode())
    assert derive_text(by_id[DOC_IDS["exhibit_2_2"]]) == html_text(raw_bytes("exhibit_2_2").decode())
    assert derive_text(by_id[DOC_IDS["eight_k_2"]]) == (
        "UNITED STATES SECURITIES AND EXCHANGE COMMISSION\n"
        "FORM 8-K\n"
        "Item 2.02. The Company reports under Item 2.02 of Form 8-K.\n"
        "Item 9.01. The Company reports under Item 9.01 of Form 8-K.\n"
        "Pursuant to the requirements of the Securities Exchange Act of 1934, the registrant has duly "
        "caused this report to be signed.\n"
    )


def test_edgar_text_reads_txt_names_as_plain_text_every_other_as_html_and_latin_1_as_windows_1252():
    assert edgar_text(b"Line one\r\n  wrapped   here\n", "filing.TXT") == "Line one\nwrapped here\n"
    assert edgar_text(b"<p>A&nbsp;b</p>", "filing.htm") == "A b\n"
    assert edgar_text(b"<p>It\x92s \x96 fine</p>", "filing.htm") == "It’s – fine\n"
    # No document is read as XML any more: an XML name is read as HTML, its elements' text kept.
    assert edgar_text(b'<?xml version="1.0"?><a><b>kept</b></a>', "primary_doc.xml") == "kept\n"


def test_a_calls_text_is_derived_from_its_transcript_with_its_turns(layout):
    fetch(layout)
    by_id = state(layout).documents()
    call = by_id[DOC_IDS["call_q2"]]

    derived = derive_call(call)

    assert derive_text(call) == derived.text == call_text(CALL_Q2)
    assert [(derived.text[turn.start : turn.end], turn.heading) for turn in derived.turns][2:4] == [
        (
            "Demand for our server processors exceeded our supply in the quarter.\n"
            "We are adding capacity for Intel 18A at our Arizona factory.",
            "Lip-Bu Tan (executive)",
        ),
        (
            "We expect gross margin of approximately 36% in the third quarter.\n"
            "We funded our capital spending with cash from operations and partner contributions.",
            "David Zinsner (executive)",
        ),
    ]
    assert derive_text(by_id[DOC_IDS["call_q1"]]) == call_text(CALL_Q1)
    assert derive_text(by_id[DOC_IDS["call_old_q"]]) == call_text(CALL_OLD_Q)
    with pytest.raises(ValueError, match=f"^{DOC_IDS['ten_q_2']}: not a call$"):
        derive_call(by_id[DOC_IDS["ten_q_2"]])


def test_a_transcript_changed_after_the_read_fails_the_derivation(layout):
    fetch(layout)
    call = state(layout).documents()[DOC_IDS["call_q2"]]
    plant_transcript(
        layout, CALL_Q2, Q2, transcript_body(CALL_Q2, header={"event_date_time": "2026-07-24T21:00:00Z"})
    )

    with pytest.raises(ValueError) as caught:
        derive_text(call)
    assert str(caught.value) == "transcript: data.header.event_date_time is not the time the calls list gives"
