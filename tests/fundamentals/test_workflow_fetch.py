"""``workflow.fetch``: the ticker map, the submissions and each window period's EDGAR documents in
``raw/``, then the ticker's calls list from EarningsCalls.dev when it is due and the transcripts of
the window periods' calls.

Every request goes to ``workflow_support.edgar`` or ``fake_earningscalls.provider``, recording
fakes of the HTTP layers that fail loudly on a URL they do not serve, so no test reaches the
network and a test proves which requests were made, in which order. ``raw/`` must hold exactly
the bytes served, at the paths ``workflow_support.RAW`` writes out; the clients' clocks read
``FETCH_TIMES`` and ``CALLS_TIMES``, so the files' names are known before any code runs. Every
file lives below pytest's ``tmp_path`` (the ``layout`` fixture).
"""

import os
from datetime import date

import pytest

from market_state_research.fundamentals.script import workflow
from market_state_research.fundamentals.script.client import (
    COMPANY_TICKERS_URL,
    DOCUMENT_ACCEPT,
    DOCUMENT_LIMIT,
    INDEX_LIMIT,
    JSON_ACCEPT,
    JSON_LIMIT,
    PACING,
    EdgarError,
    Response,
)
from market_state_research.fundamentals.script.documents import period_documents
from market_state_research.fundamentals.script.earningscalls import (
    BODY_LIMIT,
    EarningsCallsError,
    events_url,
    transcript_url,
)
from market_state_research.fundamentals.script.earningscalls import PACING as CALLS_PACING
from market_state_research.fundamentals.script.filings import Window, default_window

from .calls_support import (
    CALL_DROPPED,
    CALL_OLD_Q,
    CALL_Q1,
    CALL_Q2,
    CALL_Q3,
    CALLS,
    call_row,
    events_page,
    transcript_body,
)
from .edgar_support import (
    CIK,
    EIGHT_K_Q1,
    EIGHT_K_Q2,
    ENTITY_NAME,
    OLD_TEN_K,
    OLD_TEN_Q,
    Q2_EXHIBITS,
    RECENT,
    TEN_K,
    TEN_Q_1,
    TEN_Q_2,
    TICKER,
    IndexRow,
    Row,
    filing_index_html,
    submissions_json,
)
from .fake_earningscalls import API_KEY, CANARY, FakeEarningsCalls, calls_client, provider
from .fake_earningscalls import ok as provider_ok
from .fake_earningscalls import status as provider_status
from .fake_edgar import RecordingSleep, ok, status
from .support import NOW, TODAY, edt
from .workflow_support import (
    APPLE_CIK,
    DEFAULT_WINDOW,
    DOC_IDS,
    EIGHT_K_Q3,
    EXHIBITS,
    FETCH_URLS,
    FILINGS,
    INDEXES,
    LATER_RECENT,
    LATER_TIMES,
    NO_PERIODIC_FILINGS,
    OLD_DOCUMENTS,
    PENDING_RECENT,
    Q3_EXHIBITS,
    RAW,
    REFRESH_TIMES,
    TEN_Q_3,
    WINDOW,
    WINDOW_FROM,
    archive_document_url,
    calls_directory,
    client,
    edgar,
    fetch,
    filing_url,
    index_url,
    place,
    raw_bytes,
    raw_file,
    snapshot,
    submissions_url,
    write_watchlist,
)

WINDOW_JSON = {"from": "2025-12-01", "to": "2026-10-08"}
NO_CAPTURE = "no calls list from EarningsCalls.dev is in raw/; run fetch"
MARKER = "private-marker"  # a value no message may echo
# The EDGAR roles a first fetch of WINDOW writes, in fetch order, each with the URL it requests.
FETCHED = tuple(role for role in RAW if RAW[role].startswith("edgar/"))
URLS = dict(zip(FETCHED, FETCH_URLS[1:], strict=True))
CALL_ROLES = ("events", "transcript_q1", "transcript_q2")
# Every URL a first fetch of WINDOW asks the provider for, in order: the list, then the transcripts of
# the window periods' calls, oldest period first.
CALLS_URLS = (events_url(TICKER, 1), transcript_url(CALL_Q1.id), transcript_url(CALL_Q2.id))
# Each period of WINDOW: its filing role and, per release, its index page role and exhibit roles.
PERIOD_ROLES: dict[str, tuple[str, tuple[tuple[str, tuple[str, ...]], ...]]] = {
    "2025-12-27": ("ten_k", ()),
    "2026-03-28": ("ten_q_1", (("index_1", ("exhibit_1",)),)),
    "2026-06-27": ("ten_q_2", (("index_2", ("exhibit_2_1", "exhibit_2_2")),)),
}


def raw_tree(layout, section: str = "edgar") -> dict[str, bytes]:
    """Every file below ``raw/INTC/{section}/``, by its path below ``raw/INTC/``."""
    root = layout.raw(TICKER)
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in sorted((root / section).rglob("*"))
        if path.is_file()
    }


def expected_tree(*roles: str) -> dict[str, bytes]:
    return {RAW[role]: raw_bytes(role) for role in roles}


def before(role: str) -> tuple[str, ...]:
    """The roles a first fetch writes before ``role``."""
    return FETCHED[: FETCHED.index(role)]


def filing_entry(layout, role: str, state: str = "new") -> dict:
    row = FILINGS[role]
    assert row.period is not None
    return {
        "form": row.form,
        "accession": row.accession,
        "filed": row.filed.isoformat(),
        "period": row.period.isoformat(),
        "doc_id": DOC_IDS[role],
        "path": str(raw_file(layout, role)),
        "status": state,
    }


def exhibit_entry(layout, role: str, state: str = "new") -> dict:
    _, index_row = EXHIBITS[role]
    return {
        "exhibit": index_row.type,
        "sequence": int(index_row.seq),
        "document": index_row.document,
        "doc_id": DOC_IDS[role],
        "path": str(raw_file(layout, role)),
        "status": state,
    }


def release_identity(row: Row) -> dict:
    assert row.period is not None
    return {
        "accession": row.accession,
        "filed": row.filed.isoformat(),
        "report_date": row.period.isoformat(),
        "items": row.items,
    }


def period_entries(layout, state: str = "new") -> list[dict]:
    """``fetch``'s ``periods`` for WINDOW, every file ``state``."""
    periods = []
    for period, (filing_role, releases) in PERIOD_ROLES.items():
        entries = [
            {
                **release_identity(INDEXES[index_role][0]),
                "index": {"path": str(raw_file(layout, index_role)), "status": state},
                "exhibits": [exhibit_entry(layout, role, state) for role in exhibit_roles],
            }
            for index_role, exhibit_roles in releases
        ]
        periods.append(
            {"period": period, "filing": filing_entry(layout, filing_role, state), "releases": entries}
        )
    return periods


def unsupported_entry(ticker: str, reason: str, **values: object) -> dict:
    return {
        "ticker": ticker,
        "status": "unsupported",
        "reason": reason,
        "cik": values.get("cik"),
        "entity_name": values.get("entity_name"),
        "submissions": values.get("submissions"),
        "window": WINDOW_JSON,
        "truncated": None,
        "periods": [],
        "pending_releases": [],
        "calls": None,
    }


def calls_entry(
    layout, events: str = "new", transcripts: str = "new", reason: str | None = NO_CAPTURE
) -> dict:
    """``fetch``'s ``calls`` of INTC for WINDOW: the default capture and the window calls' transcripts."""
    return {
        "status": "fetched",
        "reason": None,
        "events": {
            "status": events,
            "path": str(raw_file(layout, "events")),
            "pages": 1,
            "fetched_at": "2026-10-08T05:31:00-04:00",
            "reason": reason,
        },
        "transcripts": [
            {
                "id": CALL_Q1.id,
                "date": "2026-04-23",
                "fiscal_year": 2026,
                "fiscal_quarter": 1,
                "period": "2026-03-28",
                "doc_id": DOC_IDS["call_q1"],
                "path": str(raw_file(layout, "transcript_q1")),
                "status": transcripts,
            },
            {
                "id": CALL_Q2.id,
                "date": "2026-07-23",
                "fiscal_year": 2026,
                "fiscal_quarter": 2,
                "period": "2026-06-27",
                "doc_id": DOC_IDS["call_q2"],
                "path": str(raw_file(layout, "transcript_q2")),
                "status": transcripts,
            },
        ],
    }


# --------------------------------------------------------------------------- a first fetch


def test_a_first_fetch_writes_every_window_periods_documents_as_served(layout):
    sleep, calls_sleep = RecordingSleep(), RecordingSleep()
    served, answering = edgar(), provider()

    result = fetch(layout, served, sleep=sleep, calls=answering, calls_sleep=calls_sleep)

    assert served.urls == list(FETCH_URLS)
    assert answering.urls == list(CALLS_URLS)
    assert (result["requests"], result["user_agent"], result["window"]) == (10, "set", WINDOW_JSON)
    assert (result["transcript_requests"], result["api_key"], result["stopped"]) == (3, "set", None)
    assert sleep.calls == [PACING] * 9
    assert calls_sleep.calls == [CALLS_PACING] * 2
    (entry,) = result["tickers"]
    assert entry == {
        "ticker": TICKER,
        "status": "fetched",
        "reason": None,
        "cik": CIK,
        "entity_name": ENTITY_NAME,
        "submissions": {"path": str(raw_file(layout, "submissions")), "status": "new"},
        "window": WINDOW_JSON,
        "truncated": False,
        "periods": period_entries(layout),
        "pending_releases": [],
        "calls": calls_entry(layout),
    }
    assert raw_tree(layout) == expected_tree(*FETCHED)
    assert raw_tree(layout, "calls") == expected_tree(*CALL_ROLES)
    assert sorted(path.name for path in layout.root.iterdir()) == ["raw"]  # no text, no report


def test_the_output_lists_its_keys_in_the_contracts_order(layout):
    result = fetch(layout)

    assert list(result) == [
        "requests",
        "user_agent",
        "transcript_requests",
        "api_key",
        "window",
        "refresh",
        "stopped",
        "tickers",
    ]
    (entry,) = result["tickers"]
    assert list(entry) == [
        "ticker",
        "status",
        "reason",
        "cik",
        "entity_name",
        "submissions",
        "window",
        "truncated",
        "periods",
        "pending_releases",
        "calls",
    ]
    assert list(entry["calls"]) == ["status", "reason", "events", "transcripts"]
    assert list(entry["calls"]["events"]) == ["status", "path", "pages", "fetched_at", "reason"]
    assert list(entry["periods"][2]["releases"][0]) == [
        "accession",
        "filed",
        "report_date",
        "items",
        "index",
        "exhibits",
    ]


def test_every_request_names_the_user_agent_and_the_accepted_media(layout):
    served = edgar()

    fetch(layout, served)

    accepts = [(headers["Accept"], limit) for _, headers, limit in served.calls]
    assert accepts == [
        (JSON_ACCEPT, JSON_LIMIT),
        (JSON_ACCEPT, JSON_LIMIT),
        (DOCUMENT_ACCEPT, DOCUMENT_LIMIT),
        (DOCUMENT_ACCEPT, DOCUMENT_LIMIT),
        (DOCUMENT_ACCEPT, INDEX_LIMIT),
        (DOCUMENT_ACCEPT, DOCUMENT_LIMIT),
        (DOCUMENT_ACCEPT, DOCUMENT_LIMIT),
        (DOCUMENT_ACCEPT, INDEX_LIMIT),
        (DOCUMENT_ACCEPT, DOCUMENT_LIMIT),
        (DOCUMENT_ACCEPT, DOCUMENT_LIMIT),
    ]
    assert {headers["User-Agent"] for _, headers, _ in served.calls} == {"margin_edge tests@example.com"}


def test_the_user_agent_never_reaches_raw_files_or_the_output(layout):
    result = fetch(layout)

    assert "tests@example.com" not in repr(result)
    assert all(b"tests@example.com" not in data for data in raw_tree(layout).values())


# --------------------------------------------------------------------------- fetching again


def test_fetching_again_requests_no_document_and_writes_nothing(layout):
    fetch(layout)
    before_tree = {**raw_tree(layout), **raw_tree(layout, "calls")}
    served, answering = edgar(), provider()

    again = fetch(layout, served, calls=answering)

    assert served.urls == [COMPANY_TICKERS_URL, submissions_url()]
    assert answering.urls == []  # the list is not due again, and every transcript is in raw/
    (entry,) = again["tickers"]
    assert entry["submissions"] == {"path": str(raw_file(layout, "submissions")), "status": "reused"}
    assert entry["periods"] == period_entries(layout, "reused")
    assert entry["calls"] == calls_entry(layout, "reused", "reused", None)
    assert {**raw_tree(layout), **raw_tree(layout, "calls")} == before_tree


def test_submissions_whose_body_changed_are_written_under_their_fetch_time(layout):
    fetch(layout, edgar(rows=PENDING_RECENT))
    served = edgar(LATER_RECENT, documents=(TEN_Q_3,), releases=((EIGHT_K_Q3, Q3_EXHIBITS),))

    again = fetch(layout, served, times=LATER_TIMES)

    later = "edgar/submissions_20261008T054001EDT.json"
    third_quarter = "https://www.sec.gov/Archives/edgar/data/50863/000005086326000089"
    assert served.urls == [
        COMPANY_TICKERS_URL,
        submissions_url(),
        filing_url(TEN_Q_3),
        f"{third_quarter}/0000050863-26-000089-index.htm",
        f"{third_quarter}/q326earningsrelease.htm",
    ]
    (entry,) = again["tickers"]
    assert entry["submissions"] == {"path": str(layout.raw(TICKER) / later), "status": "new"}
    tree = raw_tree(layout)
    assert tree[later] == submissions_json(rows=LATER_RECENT).encode()
    assert tree[RAW["submissions"]] == submissions_json(rows=PENDING_RECENT).encode()  # kept
    assert {
        "edgar/10-Q_2026-09-26_0000050863-26-000090/intc-20260926.htm",
        "edgar/8-K_2026-10-06_0000050863-26-000089/0000050863-26-000089-index.htm",
        "edgar/8-K_2026-10-06_0000050863-26-000089/q326earningsrelease.htm",
    } < set(tree)
    assert [period["period"] for period in entry["periods"]] == [*PERIOD_ROLES, "2026-09-26"]
    assert entry["pending_releases"] == []


# --------------------------------------------------------------------------- refresh

# Where a run with --refresh at REFRESH_TIMES writes its calls list, below raw/INTC/.
REFRESH_EVENTS = "calls/events_20261008T054500EDT_1.json"
CORRECTED_TITLE = "Intel Corporation - Q2 2026 Earnings Call (corrected)"


def test_refresh_requests_every_window_document_and_transcript_again_and_rewrites_none(layout):
    fetch(layout)
    before_tree = {**raw_tree(layout), **raw_tree(layout, "calls")}
    served, answering = edgar(), provider()

    again = fetch(layout, served, calls=answering, calls_times=REFRESH_TIMES, refresh=True)

    assert served.urls == list(FETCH_URLS)  # the ticker map, the submissions and every document
    assert answering.urls == list(CALLS_URLS)  # the calls list, then every window call's transcript
    assert (again["refresh"], again["requests"], again["transcript_requests"]) == (True, 10, 3)
    (entry,) = again["tickers"]
    assert entry["submissions"] == {"path": str(raw_file(layout, "submissions")), "status": "reused"}
    assert entry["periods"] == period_entries(layout, "verified")
    assert entry["calls"] == {
        **calls_entry(layout, transcripts="verified"),
        "events": {
            "status": "new",
            "path": str(layout.raw(TICKER) / REFRESH_EVENTS),
            "pages": 1,
            "fetched_at": "2026-10-08T05:45:00-04:00",
            "reason": workflow.REFRESH_REASON,
        },
    }
    # The one file written is the calls list asked for again: every list request writes its pages.
    assert {**raw_tree(layout), **raw_tree(layout, "calls")} == {
        **before_tree,
        REFRESH_EVENTS: raw_bytes("events"),
    }


def test_refresh_writes_a_changed_transcript_beside_the_stored_one_and_the_newest_is_read(layout):
    fetch(layout)
    corrected = transcript_body(CALL_Q2, header={"title": CORRECTED_TITLE})
    answering = provider()
    answering.responses[transcript_url(CALL_Q2.id)] = provider_ok(corrected)

    again = fetch(layout, calls=answering, calls_times=REFRESH_TIMES, refresh=True)

    newer = calls_directory(layout) / "transcript_248001_20261008T054506EDT.json"
    first, second = again["tickers"][0]["calls"]["transcripts"]
    assert (first["path"], first["status"]) == (str(raw_file(layout, "transcript_q1")), "verified")
    assert (second["path"], second["status"]) == (str(newer), "refreshed")
    assert newer.read_bytes() == corrected
    assert raw_file(layout, "transcript_q2").read_bytes() == raw_bytes("transcript_q2")  # kept
    call = period_documents(layout, TICKER, NOW).documents()[DOC_IDS["call_q2"]]
    assert (call.path, call.title) == (newer, CORRECTED_TITLE)

    # Without --refresh the newest copy is kept: nothing is due, so the provider is not asked.
    later = fetch(layout, calls=FakeEarningsCalls())
    assert later["tickers"][0]["calls"]["transcripts"][1] == {**second, "status": "reused"}
    # With it again, the newest copy is the one compared.
    answering = provider()
    answering.responses[transcript_url(CALL_Q2.id)] = provider_ok(corrected)
    times = tuple(moment.replace(minute=50) for moment in REFRESH_TIMES)
    last = fetch(layout, calls=answering, calls_times=times, refresh=True)
    assert last["tickers"][0]["calls"]["transcripts"][1] == {**second, "status": "verified"}


def test_refresh_reports_an_edgar_document_that_changed_and_never_rewrites_it(layout, tmp_path):
    fetch(layout)
    # The second exhibit in raw/ becomes a symbolic link to a copy of itself: a file that cannot be read.
    stored = raw_file(layout, "exhibit_2_2")
    target = place(tmp_path / "elsewhere.htm", stored.read_bytes())
    stored.unlink()
    os.symlink(target, stored)
    edgar_tree = snapshot(layout.raw(TICKER) / "edgar")
    served = edgar()
    served.responses[URLS["exhibit_2_1"]] = ok(b"<p>A corrected release.</p>", "text/html")
    # EDGAR's index page now lists only the release; the page in raw/ lists both exhibits.
    served.responses[URLS["index_2"]] = ok(
        filing_index_html(EIGHT_K_Q2, Q2_EXHIBITS[:1]).encode(), "text/html"
    )

    again = fetch(layout, served, calls_times=REFRESH_TIMES, refresh=True)

    assert served.urls == list(FETCH_URLS)  # both exhibits the page in raw/ lists
    expected = period_entries(layout, "verified")
    (release,) = expected[2]["releases"]
    release["index"]["status"] = "changed"
    for exhibit in release["exhibits"]:
        exhibit["status"] = "changed"
    assert again["tickers"][0]["periods"] == expected
    assert snapshot(layout.raw(TICKER) / "edgar") == edgar_tree  # nothing written, moved or deleted


def test_refresh_asks_the_provider_nothing_for_a_window_without_a_listed_period(layout):
    fetch(layout)
    served, answering = edgar(), FakeEarningsCalls()

    result = fetch(layout, served, window=Window(date(2026, 6, 28), TODAY), calls=answering, refresh=True)

    assert served.urls == [COMPANY_TICKERS_URL, submissions_url()]
    assert answering.urls == []
    assert result["tickers"][0]["calls"]["transcripts"] == []


# --------------------------------------------------------------------------- windows


def test_the_default_window_is_two_years_and_may_be_truncated(layout):
    window = default_window(TODAY)
    served = edgar(documents=(*OLD_DOCUMENTS, *FILINGS.values()))
    answering = provider(transcripts=(CALL_Q2, CALL_Q1, CALL_OLD_Q))

    result = fetch(layout, served, window=window, calls=answering)

    assert window == DEFAULT_WINDOW
    (entry,) = result["tickers"]
    assert entry["window"] == {"from": "2024-10-08", "to": "2026-10-08"}
    assert entry["truncated"] is True  # the oldest filing listed is the 10-K filed 2025-01-31
    assert [period["period"] for period in entry["periods"]] == [
        "2024-12-28",
        "2025-09-27",
        "2025-12-27",
        "2026-03-28",
        "2026-06-27",
    ]
    assert served.urls == [
        COMPANY_TICKERS_URL,
        submissions_url(),
        filing_url(OLD_TEN_K),
        filing_url(OLD_TEN_Q),
        *FETCH_URLS[2:],
    ]
    assert raw_tree(layout)["edgar/10-K_2024-12-28_0000050863-25-000009/intc-20241228.htm"]
    # The quarter ended 2025-09-27 is in the window too: its call's transcript is fetched first.
    assert answering.urls == [CALLS_URLS[0], transcript_url(CALL_OLD_Q.id), *CALLS_URLS[1:]]


@pytest.mark.parametrize(
    ("window", "periods", "urls"),
    [
        (Window(TEN_K.period, TEN_Q_1.period), ["2025-12-27", "2026-03-28"], FETCH_URLS[:6]),
        (Window(TEN_Q_1.period, TEN_Q_1.period), ["2026-03-28"], (*FETCH_URLS[:2], *FETCH_URLS[3:6])),
    ],
    ids=["from-and-to-period-ends", "one-day"],
)
def test_the_window_admits_the_periods_ending_on_its_from_and_to_dates(layout, window, periods, urls):
    assert TEN_K.period is not None and TEN_Q_1.period is not None
    served = edgar()

    result = fetch(layout, served, window=window)

    (entry,) = result["tickers"]
    assert [period["period"] for period in entry["periods"]] == periods
    assert served.urls == list(urls)


@pytest.mark.parametrize(
    ("window", "truncated"),
    [
        (Window(date(2025, 12, 28), date(2026, 3, 27)), False),
        (Window(date(2026, 6, 28), TODAY), False),
        (Window(date(2025, 1, 31), date(2025, 9, 26)), False),
        (Window(date(2025, 1, 30), date(2025, 9, 26)), True),
    ],
    ids=[
        "between-two-periods",
        "after-the-newest-period",
        "from-the-oldest-filing-date",
        "from-the-day-before",
    ],
)
def test_a_window_that_selects_no_period_fetches_only_the_submissions(layout, window, truncated):
    served, answering = edgar(documents=(), releases=()), FakeEarningsCalls()

    result = fetch(layout, served, window=window, calls=answering)

    assert served.urls == [COMPANY_TICKERS_URL, submissions_url()]
    assert answering.urls == []  # no window period: nothing to ask the provider
    (entry,) = result["tickers"]
    assert (entry["truncated"], entry["periods"], entry["pending_releases"]) == (truncated, [], [])
    assert entry["calls"] == {"status": "fetched", "reason": None, "events": None, "transcripts": []}
    assert raw_tree(layout) == expected_tree("submissions")
    assert not calls_directory(layout).exists()


def test_fetch_refuses_a_window_whose_from_is_after_its_to(layout):
    served = edgar()

    with pytest.raises(ValueError, match="^the window's from date is after its to date$"):
        fetch(layout, served, window=Window(TODAY, WINDOW_FROM))

    assert served.calls == []
    assert not layout.root.exists()


# --------------------------------------------------------------------------- releases


@pytest.mark.parametrize(
    ("to", "periods", "listed"),
    [(TODAY, 3, True), (TEN_Q_2.period, 3, True), (date(2026, 6, 26), 2, False)],
    ids=["to-today", "to-the-newest-period-end", "to-the-day-before-it"],
)
def test_a_pending_release_is_reported_and_its_index_page_is_not_requested(layout, to, periods, listed):
    served = edgar(PENDING_RECENT)

    result = fetch(layout, served, window=Window(WINDOW_FROM, to))

    assert served.urls == list(FETCH_URLS if periods == 3 else FETCH_URLS[:6])
    (entry,) = result["tickers"]
    assert entry["periods"] == period_entries(layout)[:periods]
    pending = {"accession": "0000050863-26-000089", "filed": "2026-10-06", "report_date": "2026-10-06"}
    assert entry["pending_releases"] == ([{**pending, "items": "2.02,9.01"}] if listed else [])


def test_8_k_amendments_and_8_ks_without_item_2_02_are_never_requested(layout):
    ignored = (
        Row("8-K/A", "0000050863-26-000070", date(2026, 8, 5), date(2026, 7, 23), "a.htm", "2.02,9.01"),
        Row("8-K", "0000050863-26-000050", date(2026, 5, 4), date(2026, 5, 1), "b.htm", "7.01,9.01"),
        Row("8-K", "0000050863-26-000081", date(2026, 9, 3), date(2026, 9, 3), "c.htm", ""),
    )
    served = edgar((*ignored, *RECENT))

    result = fetch(layout, served)

    assert served.urls == list(FETCH_URLS)
    assert result["tickers"][0]["periods"] == period_entries(layout)


def test_a_release_without_ex_99_exhibits_writes_only_its_index_page(layout):
    others = (
        IndexRow("2", "EX-10.1", "q126agreement.htm", "EX-10.1", "51200"),
        IndexRow("3", "EX-104", "q126cover.htm", "EX-104", "40960"),
    )
    page = filing_index_html(EIGHT_K_Q1, others)
    served = edgar()
    served.responses[URLS["index_1"]] = ok(page.encode(), "text/html")

    result = fetch(layout, served)

    assert served.urls == [*FETCH_URLS[:5], *FETCH_URLS[6:]]
    (release,) = result["tickers"][0]["periods"][1]["releases"]
    assert release["exhibits"] == []
    assert raw_tree(layout)[RAW["index_1"]] == page.encode()
    assert RAW["exhibit_1"] not in raw_tree(layout)


def test_an_exhibits_pdf_copy_on_the_index_page_is_never_requested(layout):
    listed = (*Q2_EXHIBITS, IndexRow("4", "EX-99.1", "q226earningsrelease.pdf", "EX-99.1", "512000"))
    served = edgar()
    served.responses[URLS["index_2"]] = ok(filing_index_html(EIGHT_K_Q2, listed).encode(), "text/html")

    fetch(layout, served)

    assert served.urls == list(FETCH_URLS)


def test_an_index_page_in_raw_is_never_requested_again(layout):
    failing = edgar()
    failing.responses[URLS["exhibit_2_1"]] = status(503, "Service Unavailable")
    with pytest.raises(EdgarError):
        fetch(layout, failing)
    served = edgar()
    # EDGAR's page now lists only the release; the page in raw/, which lists both exhibits, stands.
    served.responses[URLS["index_2"]] = ok(
        filing_index_html(EIGHT_K_Q2, Q2_EXHIBITS[:1]).encode(), "text/html"
    )

    again = fetch(layout, served)

    assert served.urls == [COMPANY_TICKERS_URL, submissions_url(), URLS["exhibit_2_1"], URLS["exhibit_2_2"]]
    (release,) = again["tickers"][0]["periods"][2]["releases"]
    assert release["index"] == {"path": str(raw_file(layout, "index_2")), "status": "reused"}
    assert raw_tree(layout) == expected_tree(*FETCHED)


def test_an_index_page_in_raw_that_no_longer_parses_aborts_naming_it(layout):
    fetch(layout)
    path = place(raw_file(layout, "index_2"), f"<html>{MARKER}</html>")
    served = edgar()

    with pytest.raises(ValueError) as raised:
        fetch(layout, served)

    assert str(raised.value) == (
        f'{path}: filing index 0000050863-26-000062: no tableFile table with the summary "Document Format '
        'Files"; rename it with .rejected and run fetch again'
    )
    assert MARKER not in str(raised.value)
    assert path.read_text(encoding="utf-8") == f"<html>{MARKER}</html>"  # never rewritten


@pytest.mark.parametrize(
    ("body", "rule"),
    [
        (
            f"<html><body><p>{MARKER}</p></body></html>",
            'no tableFile table with the summary "Document Format Files"',
        ),
        (
            filing_index_html(
                EIGHT_K_Q2, Q2_EXHIBITS, header=("Seq", "Description", "Document", "Type", MARKER)
            ),
            "the Document Format Files table's first row is not Seq, Description, Document, Type, Size",
        ),
        (
            filing_index_html(
                EIGHT_K_Q2,
                (
                    Q2_EXHIBITS[0],
                    IndexRow("3", "EX-99.2", "q226cfocommentary.htm", f"EX-99{MARKER}", "88120"),
                ),
            ),
            "row 4: Type must be EX-99, or EX-99. followed by 1 to 16 letters, digits or dots",
        ),
        (
            filing_index_html(
                EIGHT_K_Q2, (Q2_EXHIBITS[0], IndexRow("3", "EX-99.2", f"../{MARKER}.htm", "EX-99.2", "88120"))
            ),
            "row 4: the document must be a plain file name",
        ),
    ],
    ids=["no-table", "header", "type", "path"],
)
def test_an_index_page_that_cannot_be_parsed_aborts_and_writes_nothing_of_its_release(layout, body, rule):
    served = edgar()
    served.responses[URLS["index_2"]] = ok(body.encode(), "text/html")

    with pytest.raises(ValueError) as raised:
        fetch(layout, served)

    assert str(raised.value) == f"filing index {EIGHT_K_Q2.accession}: {rule}"
    assert MARKER not in str(raised.value)
    assert served.urls == list(FETCH_URLS[:8])  # no exhibit of the release is requested
    assert raw_tree(layout) == expected_tree(*before("index_2"))


# --------------------------------------------------------------------------- tickers


def test_unsupported_tickers_are_reported_and_the_run_goes_on(layout):
    served = edgar()
    apple_body = submissions_json(APPLE_CIK, "APPLE INC", NO_PERIODIC_FILINGS)
    served.responses[submissions_url(APPLE_CIK)] = ok(apple_body.encode(), "application/json")

    result = fetch(layout, served, "ZZZZ", "aapl", "INTC")

    unlisted, foreign, intel = result["tickers"]
    assert unlisted == unsupported_entry("ZZZZ", "not in SEC company_tickers.json")
    apple_path = layout.raw("AAPL") / "edgar/submissions_20261008T053001EDT.json"
    assert foreign == unsupported_entry(
        "AAPL",
        "no 10-K or 10-Q among the 2 recent filings; forms seen: 20-F, 6-K",
        cik=APPLE_CIK,
        entity_name="APPLE INC",
        submissions={"path": str(apple_path), "status": "new"},
    )
    assert apple_path.read_bytes() == apple_body.encode()  # its submissions stay in raw/
    assert intel["status"] == "fetched"
    assert served.urls == [COMPANY_TICKERS_URL, submissions_url(APPLE_CIK), *FETCH_URLS[1:]]  # the map once


@pytest.mark.parametrize(
    ("row", "problem"),
    [
        (
            Row("10-Q", "0000050863-26-000070", date(2026, 7, 30), TEN_Q_2.period, "intc-20260627x.htm"),
            "two filings report the period 2026-06-27",
        ),
        (
            Row("8-K", "0000050863-26-000063", date(2026, 7, 23), None, "intc-20260723x.htm", "2.02,9.01"),
            "filings.recent.reportDate[0] is empty; an 8-K with Item 2.02 must name its event date",
        ),
    ],
    ids=["two-filings-for-a-period", "undated-release"],
)
def test_submissions_whose_periods_cannot_be_listed_make_the_ticker_unsupported(layout, row, problem):
    rows = (row, *RECENT)
    served = edgar(rows, documents=(), releases=())

    result = fetch(layout, served)

    (entry,) = result["tickers"]
    assert entry == unsupported_entry(
        TICKER,
        f"submissions CIK{CIK}: {problem}",
        cik=CIK,
        entity_name=ENTITY_NAME,
        submissions={"path": str(raw_file(layout, "submissions")), "status": "new"},
    )
    assert served.urls == [COMPANY_TICKERS_URL, submissions_url()]
    assert raw_tree(layout) == {RAW["submissions"]: submissions_json(rows=rows).encode()}


def test_tickers_are_normalised_and_each_fetched_once(layout):
    result = fetch(layout, None, "intc", "INTC")

    assert [entry["ticker"] for entry in result["tickers"]] == [TICKER]
    assert result["requests"] == 10


def test_an_invalid_ticker_is_refused_before_any_request(layout):
    served = edgar()

    with pytest.raises(ValueError, match="ticker must be a US symbol"):
        fetch(layout, served, "INTC", "../INTC")

    assert served.calls == []
    assert not layout.root.exists()


def test_the_watchlists_stock_section_is_the_default(layout, tmp_path):
    watchlist = write_watchlist(tmp_path, ("intc",))

    result = workflow.fetch(
        layout, [], client(edgar()), calls_client(provider()), WINDOW, NOW, watchlist=watchlist
    )

    assert [entry["ticker"] for entry in result["tickers"]] == [TICKER]


def test_explicit_tickers_never_read_the_watchlist(layout, tmp_path):
    result = workflow.fetch(
        layout,
        [TICKER],
        client(edgar()),
        calls_client(provider()),
        WINDOW,
        NOW,
        watchlist=tmp_path / "missing.json",
    )

    assert result["tickers"][0]["status"] == "fetched"


def test_a_missing_watchlist_fails_before_any_request(layout, tmp_path):
    served, answering = edgar(), provider()

    with pytest.raises(ValueError, match="missing.json: file not found"):
        workflow.fetch(
            layout,
            [],
            client(served),
            calls_client(answering),
            WINDOW,
            NOW,
            watchlist=tmp_path / "missing.json",
        )

    assert served.calls == [] and answering.calls == []
    assert not layout.root.exists()


# --------------------------------------------------------------------------- failures


@pytest.mark.parametrize(
    ("response", "problem"),
    [
        (
            status(403, "Forbidden"),
            "HTTP 403 Forbidden; EDGAR refused the request: check SEC_USER_AGENT "
            "(a name and an email address) and EDGAR's fair-access policy",
        ),
        (
            status(429, "Too Many Requests"),
            "HTTP 429 Too Many Requests; EDGAR's rate limit: wait ten minutes and run fetch again",
        ),
        (
            status(503, "Service Unavailable"),
            "HTTP 503 Service Unavailable; EDGAR is unavailable: wait and run fetch again",
        ),
    ],
    ids=["403", "429", "503"],
)
def test_an_http_error_aborts_the_run_and_keeps_what_was_written_before_it(layout, response, problem):
    served = edgar()
    served.responses[URLS["exhibit_2_1"]] = response

    with pytest.raises(EdgarError) as raised:
        fetch(layout, served)

    assert str(raised.value) == f"GET {URLS['exhibit_2_1']}: {problem}"
    assert served.urls == list(FETCH_URLS[:9])
    assert raw_tree(layout) == expected_tree(*before("exhibit_2_1"))


@pytest.mark.parametrize("role", ["ten_q_2", "index_2", "exhibit_2_1"])
def test_a_document_cut_short_aborts_the_run_and_a_later_fetch_writes_it(layout, role):
    served = edgar()
    full = served.responses[URLS[role]]
    assert isinstance(full, Response)
    size = len(full.body)
    served.responses[URLS[role]] = ok(full.body, full.headers["content-type"], content_length=str(size + 1))

    with pytest.raises(EdgarError) as raised:
        fetch(layout, served)

    assert (
        str(raised.value)
        == f"GET {URLS[role]}: the body ended after {size} of {size + 1} bytes; run fetch again"
    )
    assert raw_tree(layout) == expected_tree(*before(role))

    later = edgar()
    fetch(layout, later)

    missing = FETCHED[FETCHED.index(role) :]
    assert later.urls == [COMPANY_TICKERS_URL, submissions_url(), *(URLS[name] for name in missing)]
    assert raw_tree(layout) == expected_tree(*FETCHED)


def test_a_network_failure_on_the_ticker_map_writes_nothing(layout):
    served = edgar()
    served.responses[COMPANY_TICKERS_URL] = EdgarError(
        f"GET {COMPANY_TICKERS_URL}: no response within 60 seconds"
    )

    with pytest.raises(EdgarError, match="no response within 60 seconds"):
        fetch(layout, served)

    assert served.urls == [COMPANY_TICKERS_URL]
    assert not layout.root.exists()


@pytest.mark.parametrize(
    ("body", "message"),
    [
        (b'{"cik": "50863", "name": "INTEL CORP"}', f"submissions CIK{CIK}: filings is missing"),
        (b"\xff{}", "submissions: the body is not UTF-8"),
    ],
    ids=["no-filings", "not-utf8"],
)
def test_submissions_that_cannot_be_read_abort_before_anything_is_written(layout, body, message):
    served = edgar()
    served.responses[submissions_url()] = ok(body, "application/json")

    with pytest.raises(ValueError) as raised:
        fetch(layout, served)

    assert str(raised.value) == message
    assert served.urls == [COMPANY_TICKERS_URL, submissions_url()]
    assert not layout.root.exists()


def test_an_existing_file_is_never_rewritten(layout):
    fetch(layout)
    altered = place(raw_file(layout, "exhibit_2_1"), "edited by hand\n")
    served = edgar()

    fetch(layout, served)

    assert altered.read_text(encoding="utf-8") == "edited by hand\n"
    assert archive_document_url(EIGHT_K_Q2.accession, Q2_EXHIBITS[0].document) not in served.urls
    assert index_url(EIGHT_K_Q2) not in served.urls


# --------------------------------------------------------------------------- calls


def test_every_provider_request_sends_the_key_and_no_value_reaches_raw_or_the_output(layout):
    answering = provider()
    served = edgar()

    result = workflow.fetch(
        layout,
        [TICKER],
        client(served),
        calls_client(answering, api_key=CANARY),
        WINDOW,
        NOW,
    )

    assert [(headers, limit) for _, headers, limit in answering.calls] == [
        ({"X-API-Key": CANARY, "Accept": "application/json"}, BODY_LIMIT)
    ] * 3
    assert CANARY not in repr(result) and API_KEY not in repr(result)
    assert all(CANARY.encode() not in data for data in raw_tree(layout, "calls").values())
    assert {headers.get("X-API-Key") for _, headers, _ in served.calls} == {None}  # never sent to EDGAR


def test_the_list_is_asked_for_again_once_due_and_each_request_writes_a_capture(layout):
    fetch(layout)  # 2025-12-27's call is not listed: unavailable as of 2026-10-08
    answering = provider()
    week = edt(2026, 10, 15, 6, 0)

    again = fetch(layout, calls=answering, calls_times=(edt(2026, 10, 15, 5, 31),), now=week)

    assert answering.urls == [CALLS_URLS[0]]  # the transcripts are in raw/ already
    events = again["tickers"][0]["calls"]["events"]
    newer = calls_directory(layout) / "events_20261015T053100EDT_1.json"
    assert events == {
        "status": "new",
        "path": str(newer),
        "pages": 1,
        "fetched_at": "2026-10-15T05:31:00-04:00",
        "reason": (
            "the newest calls list, fetched 2026-10-08, is 7 days old or more and lists no call for the "
            "period 2025-12-27"
        ),
    }
    assert newer.read_bytes() == raw_file(layout, "events").read_bytes()  # the same list, asked again


def test_a_call_listed_later_is_fetched_when_the_list_is_due(layout):
    # The first run, on the call's day before the call: the list lacks the call of 2026-07-23.
    noon = edt(2026, 7, 23, 12, 0)
    without_q2 = events_page([call_row(call) for call in (CALL_Q1, CALL_OLD_Q, CALL_DROPPED)])
    fetch(
        layout,
        times=tuple(noon.replace(second=second) for second in range(10)),
        calls=provider(without_q2, (CALL_Q1,)),
        calls_times=(noon.replace(second=30), noon.replace(second=33)),
        now=noon,
    )
    # Two days on, the quarter's due date (its release's, 2026-07-23) has passed: the list is due.
    later = edt(2026, 7, 25, 6, 30)
    answering = provider()

    result = fetch(
        layout,
        times=tuple(later.replace(second=second) for second in range(10)),
        calls=answering,
        calls_times=(later.replace(second=30), later.replace(second=33)),
        now=later,
    )

    assert answering.urls == [CALLS_URLS[0], transcript_url(CALL_Q2.id)]
    assert result["tickers"][0]["calls"]["events"]["reason"] == (
        "the newest calls list was fetched 2026-07-23, on or before the period 2026-06-27's due date "
        "2026-07-23"
    )
    assert raw_file(layout, "transcript_q2").read_bytes() == transcript_body(CALL_Q2)


def test_an_ambiguous_symbol_leaves_the_calls_unsupported_and_writes_nothing(layout):
    answering = provider(events_page(ambiguous=True, issuer_count=2))

    result = fetch(layout, calls=answering)

    assert answering.urls == [CALLS_URLS[0]]  # no other page and no transcript
    assert result["tickers"][0]["calls"] == {
        "status": "unsupported",
        "reason": "EarningsCalls.dev lists 2 issuers for INTC (ambiguous): their calls cannot be told apart",
        "events": None,
        "transcripts": [],
    }
    assert not calls_directory(layout).exists()


def test_the_request_limit_stops_the_calls_and_the_run_goes_on_with_edgar_alone(layout):
    nvidia_cik, nvidia_row = (
        "0001045810",
        Row("10-Q", "0001045810-26-000100", date(2026, 8, 27), date(2026, 7, 26), "nvda-20260726.htm"),
    )
    served = edgar()
    served.responses[submissions_url(nvidia_cik)] = ok(
        submissions_json(nvidia_cik, "NVIDIA CORP", (nvidia_row,)).encode(), "application/json"
    )
    nvidia_document = archive_document_url(nvidia_row.accession, nvidia_row.primary_document, cik=nvidia_cik)
    served.responses[nvidia_document] = ok(b"<p>A quarterly report.</p>", "text/html")
    limit = b'{"error": "Monthly request limit reached; it resets on 2026-11-01"}'
    answering = provider()
    answering.responses[transcript_url(CALL_Q2.id)] = provider_status(429, "Too Many Requests", limit)

    result = fetch(layout, served, "INTC", "NVDA", calls=answering)

    assert answering.urls == list(CALLS_URLS)  # nothing after the refusal
    message = (
        f"GET {CALLS_URLS[2]}: HTTP 429; EarningsCalls.dev's request limit is reached (the key's 3,000 "
        "requests a month or 20 a minute); the provider says: Monthly request limit reached; it resets on "
        "2026-11-01; run fetch again once it resets"
    )
    assert result["stopped"] == {"ticker": TICKER, "reason": message}
    intel, nvidia = result["tickers"]
    assert (intel["calls"]["status"], intel["calls"]["reason"]) == ("stopped", message)
    assert [item["status"] for item in intel["calls"]["transcripts"]] == ["new"]  # Q1's, before the refusal
    assert raw_tree(layout, "calls") == expected_tree("events", "transcript_q1")  # kept
    assert nvidia["status"] == "fetched" and nvidia["periods"][0]["filing"]["status"] == "new"
    assert nvidia["calls"] == {
        "status": "stopped",
        "reason": "not requested: EarningsCalls.dev's request limit was reached earlier in this run",
        "events": None,
        "transcripts": [],
    }
    assert served.urls[-2:] == [submissions_url(nvidia_cik), nvidia_document]


def test_a_calls_page_that_does_not_read_aborts_the_run_and_writes_nothing_of_it(layout):
    answering = provider(events_page([call_row(CALL_Q2, symbol="INTL")]))

    with pytest.raises(ValueError) as raised:
        fetch(layout, calls=answering)

    assert str(raised.value) == f"GET {CALLS_URLS[0]}: calls list page 1: a call's stock_symbol is not INTC"
    assert not calls_directory(layout).exists()
    assert raw_tree(layout) == expected_tree(*FETCHED)  # EDGAR's files stay


def test_a_transcript_that_does_not_read_aborts_the_run_and_keeps_what_was_written(layout):
    answering = provider()
    answering.responses[transcript_url(CALL_Q2.id)] = provider_ok(transcript_body(CALL_Q1))  # another call's

    with pytest.raises(ValueError) as raised:
        fetch(layout, calls=answering)

    assert str(raised.value) == (
        f"GET {CALLS_URLS[2]}: transcript: data.header.event_date_time is not the time the calls list gives"
    )
    assert raw_tree(layout, "calls") == expected_tree("events", "transcript_q1")


@pytest.mark.parametrize(
    ("response", "problem"),
    [
        (
            provider_status(401, "Unauthorized"),
            "HTTP 401 Unauthorized; EarningsCalls.dev refused the key: check EARNINGSCALLS_API",
        ),
        (
            provider_status(404, "Not Found"),
            "HTTP 404 Not Found; EarningsCalls.dev serves nothing at this address",
        ),
    ],
    ids=["401", "404"],
)
def test_a_provider_error_aborts_the_run(layout, response, problem):
    answering = provider()
    answering.responses[CALLS_URLS[0]] = response

    with pytest.raises(EarningsCallsError) as raised:
        fetch(layout, calls=answering)

    assert str(raised.value) == f"GET {CALLS_URLS[0]}: {problem}"
    assert not calls_directory(layout).exists()


def test_a_ticker_edgar_does_not_list_asks_the_provider_nothing(layout):
    answering = FakeEarningsCalls()

    result = fetch(layout, None, "ZZZZ", calls=answering)

    assert answering.calls == [] and result["tickers"][0]["calls"] is None


def test_a_pending_calls_transcript_is_fetched_when_the_window_reaches_the_newest_period(layout):
    rows = [call_row(CALL_Q3), *(call_row(call) for call in CALLS)]
    answering = provider(events_page(rows), (CALL_Q3, CALL_Q2, CALL_Q1))

    result = fetch(layout, edgar(PENDING_RECENT), calls=answering)

    assert answering.urls == [*CALLS_URLS, transcript_url(CALL_Q3.id)]
    pending = result["tickers"][0]["calls"]["transcripts"][-1]
    assert pending == {
        "id": CALL_Q3.id,
        "date": "2026-10-06",
        "fiscal_year": 2026,
        "fiscal_quarter": 3,
        "period": None,
        "doc_id": None,
        "path": str(calls_directory(layout) / f"transcript_{CALL_Q3.id}.json"),
        "status": "new",
    }

    earlier = provider(events_page(rows), ())
    fetch(layout, edgar(PENDING_RECENT), window=Window(WINDOW_FROM, date(2026, 6, 26)), calls=earlier)
    assert earlier.urls == []  # the window ends before the newest period: no pending call is weighed
