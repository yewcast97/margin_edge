"""``workflow.fetch``: the ticker map, the submissions, each span season's EDGAR documents and the
company facts in ``raw/``, then the ticker's calls list from EarningsCalls.dev when it is due and
the transcripts of the span seasons' calls.

The span is the window's seasons and the four listed before them. Every request goes to
``workflow_support.edgar`` or ``fake_earningscalls.provider``, recording fakes of the HTTP layers
that fail loudly on a URL they do not serve, so no test reaches the network and a test proves which
requests were made, in which order. ``raw/`` must hold exactly the bytes served, at the paths
``workflow_support.RAW`` writes out; the clients' clocks start at ``FETCHED_AT`` and
``CALLS_FETCHED_AT`` and read one second later at each request, so the stamped files' names are
known before any code runs. Every file lives below pytest's ``tmp_path`` (the ``layout`` fixture).
"""

import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import date, timedelta

import pytest

from market_state_research.fundamentals.script import workflow
from market_state_research.fundamentals.script.client import (
    COMPANY_TICKERS_URL,
    COMPANYFACTS_LIMIT,
    DOCUMENT_ACCEPT,
    DOCUMENT_LIMIT,
    INDEX_LIMIT,
    JSON_ACCEPT,
    JSON_LIMIT,
    PACING,
    EdgarError,
    Response,
)
from market_state_research.fundamentals.script.documents import season_documents
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
    EIGHT_K_OTHER,
    EIGHT_K_Q1,
    EIGHT_K_Q2,
    ENTITY_NAME,
    OLD_TEN_K,
    OLD_TEN_Q,
    PROXY,
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
    ten_q_html,
)
from .fake_earningscalls import API_KEY, CANARY, FakeEarningsCalls, calls_client, provider
from .fake_earningscalls import ok as provider_ok
from .fake_earningscalls import status as provider_status
from .fake_edgar import FakeEdgar, RecordingSleep, ok, status
from .support import NOW, TODAY, edt
from .workflow_support import (
    CALLS_FETCHED_AT,
    CALLS_OF_SEASONS,
    DEFAULT_WINDOW,
    DOC_IDS,
    FETCH_URLS,
    FETCHED_AT,
    RAW,
    WINDOW,
    FetchClock,
    archive_document_url,
    client,
    companyfacts_document,
    companyfacts_json,
    companyfacts_url,
    edgar,
    eight_k_html,
    fetch,
    filing_url,
    index_url,
    place,
    plant_former_layout,
    raw_bytes,
    raw_file,
    role_url,
    snapshot,
    submissions_url,
    write_watchlist,
)

WINDOW_JSON = {"from": "2025-12-01", "to": "2026-10-08"}
# The stamped files of a first fetch of WINDOW: EDGAR's second and eighteenth requests, then the
# provider's first.
SUBMISSIONS = "submissions_20261008T053002EDT.json"
COMPANYFACTS = "companyfacts_20261008T053018EDT.json"
EVENTS = "calls_20261008T053100EDT_1.json"
NO_CAPTURE = "no calls list from EarningsCalls.dev is in raw/; run fetch"
REFRESH_REASON = "--refresh: the span's documents, transcripts and calls list are requested again"
LIMIT_EARLIER = "not requested: EarningsCalls.dev's request limit was reached earlier in this run"
MARKER = "private-marker"  # a value no message may echo
JSON_TYPE = "application/json"
HTML_TYPE = "text/html"
# Later runs' clocks, still before NOW, so each run's stamped files are named after the last's.
AGAIN, CALLS_AGAIN = FETCHED_AT + timedelta(minutes=10), CALLS_FETCHED_AT + timedelta(minutes=10)
LATER, CALLS_LATER = FETCHED_AT + timedelta(minutes=15), CALLS_FETCHED_AT + timedelta(minutes=15)
# The EDGAR documents of RAW, in the order a first fetch of WINDOW requests them.
DOCUMENTS = tuple(role for role in RAW if not role.startswith("transcript_"))
# Every URL a first fetch of WINDOW asks the provider for, in order: the list, then the transcripts
# of the span seasons' calls, oldest season first.
CALLS_URLS = (
    events_url(TICKER, 1),
    transcript_url(CALL_OLD_Q.id),
    transcript_url(CALL_Q1.id),
    transcript_url(CALL_Q2.id),
)
# Each span season of WINDOW, oldest first: its 10-K's or 10-Q's role and row, whether the window
# admits it, and its fetched filings, each with the date Rule B places it by and its files' roles.
SPAN = (
    ("old_ten_k", OLD_TEN_K, False, ()),
    ("old_ten_q", OLD_TEN_Q, False, ()),
    (
        "ten_k",
        TEN_K,
        True,
        (
            (EIGHT_K_OTHER, "2026-02-09", ("index_other", "eight_k_other")),
            (PROXY, "2026-03-27", ("proxy",)),
        ),
    ),
    ("ten_q_1", TEN_Q_1, True, ((EIGHT_K_Q1, "2026-04-23", ("index_1", "eight_k_1", "exhibit_1")),)),
    (
        "ten_q_2",
        TEN_Q_2,
        True,
        ((EIGHT_K_Q2, "2026-07-23", ("index_2", "eight_k_2", "exhibit_2_1", "exhibit_2_2")),),
    ),
)
# Each span season's call: its transcript's role, the call, its New York date, its season and its
# DOC_IDS key.
SPAN_CALLS = (
    ("transcript_old_q", CALL_OLD_Q, "2025-10-23", "2025-09-27", "call_old_q"),
    ("transcript_q1", CALL_Q1, "2026-04-23", "2026-03-28", "call_q1"),
    ("transcript_q2", CALL_Q2, "2026-07-23", "2026-06-27", "call_q2"),
)
# The Form 4 of 2026-07-30, filed after the last 10-Q: pending.
PENDING_FORM_4 = {
    "form": "4",
    "accession": "0001209191-26-061234",
    "dated": "2026-07-30",
    "filed": "2026-08-03",
    "items": "",
}


def raw_tree(layout, ticker: str = TICKER) -> dict[str, bytes]:
    """Every file below ``raw/{ticker}/``, by its path below it."""
    root = layout.raw(ticker)
    return {
        str(path.relative_to(root)): path.read_bytes() for path in sorted(root.rglob("*")) if path.is_file()
    }


def season_files(layout) -> dict[str, bytes]:
    """The files below ``raw/INTC/``'s season folders, by their path below ``raw/INTC/``."""
    return {path: data for path, data in raw_tree(layout).items() if "/" in path}


def tree(*roles: str, rows: Sequence[Row] = RECENT) -> dict[str, bytes]:
    """``raw/INTC/`` after a run that wrote the submissions listing ``rows`` and the files of ``roles``."""
    return {
        SUBMISSIONS: submissions_json(rows=rows).encode(),
        **{RAW[role]: raw_bytes(role) for role in roles},
    }


def first_tree() -> dict[str, bytes]:
    """``raw/INTC/`` after a first fetch of WINDOW."""
    return {**tree(*RAW), COMPANYFACTS: companyfacts_json().encode(), EVENTS: events_page()}


def before(role: str) -> tuple[str, ...]:
    """The EDGAR documents a first fetch writes before ``role``."""
    return DOCUMENTS[: DOCUMENTS.index(role)]


def through(role: str) -> list[str]:
    """The URLs a first fetch requests up to ``role``'s, included."""
    return list(FETCH_URLS[: FETCH_URLS.index(role_url(role)) + 1])


def file_entry(layout, role: str, state: str) -> dict:
    return {
        "path": str(raw_file(layout, role)),
        "doc_id": DOC_IDS.get(role),
        "status": state,
    }  # an index: None


def season_entries(layout, state: str = "new", states: Mapping[str, str] | None = None) -> list[dict]:
    """``fetch``'s ``seasons`` for WINDOW, every file ``state`` but those ``states`` names by role."""
    named = states or {}
    entries = []
    for role, row, in_window, filings in SPAN:
        assert row.period is not None
        entries.append(
            {
                "season": row.period.isoformat(),
                "in_window": in_window,
                "filing": {
                    "form": row.form,
                    "accession": row.accession,
                    "filed": row.filed.isoformat(),
                    "period": row.period.isoformat(),
                    "doc_id": DOC_IDS[role],
                    "path": str(raw_file(layout, role)),
                    "status": named.get(role, state),
                },
                "filings": [
                    {
                        "form": item.form,
                        "accession": item.accession,
                        "dated": dated,
                        "filed": item.filed.isoformat(),
                        "items": item.items,
                        "files": [file_entry(layout, name, named.get(name, state)) for name in roles],
                    }
                    for item, dated, roles in filings
                ],
            }
        )
    return entries


def transcript_entries(layout, state: str = "new") -> list[dict]:
    return [
        {
            "id": call.id,
            "date": day,
            "fiscal_year": call.fiscal_year,
            "fiscal_quarter": call.fiscal_quarter,
            "season": season,
            "doc_id": DOC_IDS[key],
            "path": str(raw_file(layout, role)),
            "status": state,
        }
        for role, call, day, season, key in SPAN_CALLS
    ]


def calls_entry(
    layout, events: str = "new", transcripts: str = "new", reason: str | None = NO_CAPTURE
) -> dict:
    """``fetch``'s ``calls`` of INTC for WINDOW: the first run's capture and the span calls' transcripts."""
    return {
        "status": "fetched",
        "reason": None,
        "events": {
            "status": events,
            "path": str(layout.raw(TICKER) / EVENTS),
            "pages": 1,
            "fetched_at": "2026-10-08T05:31:00-04:00",
            "reason": reason,
        },
        "transcripts": transcript_entries(layout, transcripts),
        "pending_calls": [],
    }


def unsupported_entry(ticker: str, reason: str, **values: object) -> dict:
    return {
        "ticker": ticker,
        "status": "unsupported",
        "reason": reason,
        "cik": values.get("cik"),
        "entity_name": values.get("entity_name"),
        "submissions": values.get("submissions"),
        "companyfacts": None,
        "window": WINDOW_JSON,
        "truncated": None,
        "seasons": [],
        "pending_filings": [],
        "skipped_filings": [],
        "calls": None,
    }


def serve_eight_k(served: FakeEdgar, row: Row, exhibits: tuple[IndexRow, ...] = ()) -> None:
    """Serve an 8-K's index page listing ``exhibits`` and its primary document."""
    served.responses[index_url(row)] = ok(filing_index_html(row, exhibits).encode(), HTML_TYPE)
    served.responses[filing_url(row)] = ok(eight_k_html(row).encode(), HTML_TYPE)


# --------------------------------------------------------------------------- a first fetch


def test_a_first_fetch_writes_every_span_seasons_documents_as_served(layout):
    sleep, calls_sleep = RecordingSleep(), RecordingSleep()
    served, answering = edgar(), provider(transcripts=CALLS_OF_SEASONS)

    result = workflow.fetch(
        layout,
        [TICKER],
        client(served, sleep),
        calls_client(answering, calls_sleep, FetchClock(CALLS_FETCHED_AT)),
        WINDOW,
        NOW,
    )

    assert served.urls == [
        COMPANY_TICKERS_URL,
        submissions_url(),
        *map(role_url, DOCUMENTS),
        companyfacts_url(),
    ]
    assert served.urls == list(FETCH_URLS)
    assert answering.urls == list(CALLS_URLS)
    assert sleep.calls == [PACING] * 17
    assert calls_sleep.calls == [CALLS_PACING] * 3
    assert {key: value for key, value in result.items() if key != "tickers"} == {
        "requests": 18,
        "user_agent": "set",
        "transcript_requests": 4,
        "api_key": "set",
        "window": WINDOW_JSON,
        "refresh": False,
        "stopped": None,
    }
    (entry,) = result["tickers"]
    assert entry == {
        "ticker": TICKER,
        "status": "fetched",
        "reason": None,
        "cik": CIK,
        "entity_name": ENTITY_NAME,
        "submissions": {"path": str(layout.raw(TICKER) / SUBMISSIONS), "status": "new"},
        "companyfacts": {"path": str(layout.raw(TICKER) / COMPANYFACTS), "status": "new"},
        "window": WINDOW_JSON,
        "truncated": False,
        "seasons": season_entries(layout),
        "pending_filings": [PENDING_FORM_4],
        "skipped_filings": [],
        "calls": calls_entry(layout),
    }
    assert raw_tree(layout) == first_tree()
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
        "companyfacts",
        "window",
        "truncated",
        "seasons",
        "pending_filings",
        "skipped_filings",
        "calls",
    ]
    season = entry["seasons"][4]
    assert list(season) == ["season", "in_window", "filing", "filings"]
    assert list(season["filing"]) == ["form", "accession", "filed", "period", "doc_id", "path", "status"]
    assert list(season["filings"][0]) == ["form", "accession", "dated", "filed", "items", "files"]
    assert list(season["filings"][0]["files"][0]) == ["path", "doc_id", "status"]
    assert list(entry["pending_filings"][0]) == ["form", "accession", "dated", "filed", "items"]
    assert list(entry["calls"]) == ["status", "reason", "events", "transcripts", "pending_calls"]
    assert list(entry["calls"]["events"]) == ["status", "path", "pages", "fetched_at", "reason"]
    assert list(entry["calls"]["transcripts"][0]) == [
        "id",
        "date",
        "fiscal_year",
        "fiscal_quarter",
        "season",
        "doc_id",
        "path",
        "status",
    ]


def test_every_request_names_the_user_agent_and_the_accepted_media(layout):
    served = edgar()

    fetch(layout, served)

    document, index = (DOCUMENT_ACCEPT, DOCUMENT_LIMIT), (DOCUMENT_ACCEPT, INDEX_LIMIT)
    assert [(headers["Accept"], limit) for _, headers, limit in served.calls] == [
        (JSON_ACCEPT, JSON_LIMIT),  # the ticker map
        (JSON_ACCEPT, JSON_LIMIT),  # the submissions
        *(document, document, document),  # the 10-K, the 10-Q and the 10-K of the first three seasons
        *(index, document, document),  # the 8-K of 2026-02-09 and the proxy statement
        *(document, index, document, document),  # the first quarter's 10-Q and its release
        *(document, index, document, document, document),  # the second quarter's
        (JSON_ACCEPT, COMPANYFACTS_LIMIT),
    ]
    assert {headers["User-Agent"] for _, headers, _ in served.calls} == {"margin_edge tests@example.com"}


def test_the_user_agent_never_reaches_raw_files_or_the_output(layout):
    result = fetch(layout)

    assert "tests@example.com" not in repr(result)
    assert all(b"tests@example.com" not in data for data in raw_tree(layout).values())


# --------------------------------------------------------------------------- fetching again


def test_fetching_again_requests_only_the_listings_and_writes_nothing(layout):
    fetch(layout)
    stored = raw_tree(layout)
    served, answering = edgar(), provider(transcripts=CALLS_OF_SEASONS)

    again = fetch(layout, served, calls=answering, start=AGAIN, calls_start=CALLS_AGAIN)

    assert served.urls == [COMPANY_TICKERS_URL, submissions_url(), companyfacts_url()]
    assert answering.urls == []  # the list is not due again, and every transcript is in raw/
    (entry,) = again["tickers"]
    assert entry["submissions"] == {"path": str(layout.raw(TICKER) / SUBMISSIONS), "status": "reused"}
    assert entry["companyfacts"] == {"path": str(layout.raw(TICKER) / COMPANYFACTS), "status": "reused"}
    assert entry["seasons"] == season_entries(layout, "reused")
    assert entry["calls"] == calls_entry(layout, "reused", "reused", None)
    assert raw_tree(layout) == stored


def test_an_existing_file_is_never_rewritten(layout):
    fetch(layout)
    altered = place(raw_file(layout, "exhibit_2_1"), "edited by hand\n")
    served = edgar()

    fetch(layout, served, start=AGAIN, calls_start=CALLS_AGAIN)

    assert altered.read_text(encoding="utf-8") == "edited by hand\n"
    assert served.urls == [COMPANY_TICKERS_URL, submissions_url(), companyfacts_url()]


def test_a_file_renamed_rejected_is_requested_and_written_again(layout):
    fetch(layout)
    stored = raw_file(layout, "exhibit_2_1")
    withdrawn = stored.rename(stored.with_name(f"{stored.name}.rejected"))
    served = edgar()

    again = fetch(layout, served, start=AGAIN, calls_start=CALLS_AGAIN)

    assert served.urls == [
        COMPANY_TICKERS_URL,
        submissions_url(),
        role_url("exhibit_2_1"),
        companyfacts_url(),
    ]
    assert again["tickers"][0]["seasons"] == season_entries(layout, "reused", {"exhibit_2_1": "new"})
    assert stored.read_bytes() == withdrawn.read_bytes() == raw_bytes("exhibit_2_1")


def test_the_former_layout_is_left_alone_and_the_span_written_beside_it(layout):
    folders = plant_former_layout(layout)
    planted = {folder.name: snapshot(folder) for folder in folders}
    served = edgar()

    result = fetch(layout, served)

    assert served.urls == list(FETCH_URLS)
    assert result["tickers"][0]["status"] == "fetched"
    assert {folder.name: snapshot(folder) for folder in folders} == planted
    written = {
        path: data for path, data in raw_tree(layout).items() if not path.startswith(("edgar/", "calls/"))
    }
    assert written == first_tree()


# --------------------------------------------------------------------------- the span and the window

# A 10-Q older than every season of RECENT: the span of a window reaches it only from the 10-K's.
OLDER_TEN_Q = Row("10-Q", "0000050863-24-000155", date(2024, 11, 1), date(2024, 9, 28), "intc-20240928.htm")
OLDER_PATH = "2024-09-28/10-Q_2024-09-28_0000050863-24-000155/intc-20240928.htm"


def test_the_span_reaches_back_four_listed_seasons_from_the_window(layout):
    served = edgar((*RECENT, OLDER_TEN_Q))  # serves no document of the season ended 2024-09-28

    result = fetch(layout, served, window=Window(date(2026, 6, 27), TODAY))

    assert served.urls == list(FETCH_URLS)
    (entry,) = result["tickers"]
    assert [(season["season"], season["in_window"]) for season in entry["seasons"]] == [
        ("2024-12-28", False),
        ("2025-09-27", False),
        ("2025-12-27", False),
        ("2026-03-28", False),
        ("2026-06-27", True),
    ]
    assert not (layout.raw(TICKER) / "2024-09-28").exists()


def test_a_window_of_one_season_spans_it_and_the_four_seasons_before_it(layout):
    older = ten_q_html(period=date(2024, 9, 28)).encode()
    served = edgar((*RECENT, OLDER_TEN_Q))
    served.responses[filing_url(OLDER_TEN_Q)] = ok(older, HTML_TYPE)
    answering = provider(transcripts=(CALL_DROPPED, CALL_OLD_Q))

    result = fetch(layout, served, window=Window(date(2025, 12, 27), date(2025, 12, 27)), calls=answering)

    assert served.urls == [
        COMPANY_TICKERS_URL,
        submissions_url(),
        filing_url(OLDER_TEN_Q),
        *map(role_url, ("old_ten_k", "old_ten_q", "ten_k", "index_other", "eight_k_other", "proxy")),
        companyfacts_url(),
    ]
    # The call of 2024-10-31 belongs to the season ended 2024-09-28 once that season is listed.
    assert answering.urls == [CALLS_URLS[0], transcript_url(CALL_DROPPED.id), CALLS_URLS[1]]
    (entry,) = result["tickers"]
    assert [(season["season"], season["in_window"]) for season in entry["seasons"]] == [
        ("2024-09-28", False),
        ("2024-12-28", False),
        ("2025-09-27", False),
        ("2025-12-27", True),
    ]
    assert entry["pending_filings"] == []  # the window ends before the newest season end
    tree_now = raw_tree(layout)
    assert tree_now[OLDER_PATH] == older
    assert tree_now[f"2024-09-28/transcript_{CALL_DROPPED.id}.json"] == transcript_body(CALL_DROPPED)


@pytest.mark.parametrize(
    ("window", "admitted"),
    [
        (Window(date(2025, 12, 27), date(2026, 3, 28)), ["2025-12-27", "2026-03-28"]),
        (Window(date(2026, 3, 28), date(2026, 3, 28)), ["2026-03-28"]),
    ],
    ids=["from-and-to-season-ends", "one-day"],
)
def test_the_window_admits_the_seasons_ending_on_its_from_and_to_dates(layout, window, admitted):
    served, answering = edgar(), provider(transcripts=CALLS_OF_SEASONS)

    result = fetch(layout, served, window=window, calls=answering)

    (entry,) = result["tickers"]
    assert [season["season"] for season in entry["seasons"]] == [
        "2024-12-28",
        "2025-09-27",
        "2025-12-27",
        "2026-03-28",
    ]
    assert [season["season"] for season in entry["seasons"] if season["in_window"]] == admitted
    assert served.urls == [*through("exhibit_1"), companyfacts_url()]
    assert answering.urls == list(CALLS_URLS[:3])
    assert entry["pending_filings"] == []  # the window ends before the newest season end


@pytest.mark.parametrize(
    ("window", "truncated", "pending"),
    [
        (Window(date(2025, 12, 28), date(2026, 3, 27)), False, []),
        (Window(date(2026, 6, 28), TODAY), False, [PENDING_FORM_4]),
        (Window(date(2025, 1, 31), date(2025, 9, 26)), False, []),
        (Window(date(2025, 1, 30), date(2025, 9, 26)), True, []),
    ],
    ids=[
        "between-two-seasons",
        "after-the-newest-season",
        "from-the-oldest-filing-date",
        "from-the-day-before",
    ],
)
def test_a_window_that_selects_no_season_fetches_only_the_submissions(layout, window, truncated, pending):
    served, answering = edgar(), FakeEarningsCalls()

    result = fetch(layout, served, window=window, calls=answering)

    assert served.urls == [COMPANY_TICKERS_URL, submissions_url()]  # no document, no company facts
    assert answering.urls == []  # no window season: nothing to ask the provider
    (entry,) = result["tickers"]
    assert (entry["truncated"], entry["seasons"], entry["pending_filings"]) == (truncated, [], pending)
    assert entry["companyfacts"] is None
    assert entry["calls"] == {
        "status": "fetched",
        "reason": None,
        "events": None,
        "transcripts": [],
        "pending_calls": [],
    }
    assert raw_tree(layout) == tree()


def test_the_default_window_is_two_years_and_may_be_truncated(layout):
    window = default_window(TODAY)
    served, answering = edgar(), provider(transcripts=CALLS_OF_SEASONS)

    result = fetch(layout, served, window=window, calls=answering)

    assert window == DEFAULT_WINDOW
    (entry,) = result["tickers"]
    assert entry["window"] == {"from": "2024-10-08", "to": "2026-10-08"}
    assert entry["truncated"] is True  # the oldest filing listed is the 10-K filed 2025-01-31
    assert [(season["season"], season["in_window"]) for season in entry["seasons"]] == [
        ("2024-12-28", True),
        ("2025-09-27", True),
        ("2025-12-27", True),
        ("2026-03-28", True),
        ("2026-06-27", True),
    ]
    assert served.urls == list(FETCH_URLS)  # WINDOW's span holds the same five seasons
    assert answering.urls == list(CALLS_URLS)


def test_a_window_whose_from_is_after_its_to_is_refused_before_any_request(layout):
    served = edgar()

    with pytest.raises(ValueError, match="^the window's from date is after its to date$"):
        fetch(layout, served, window=Window(TODAY, WINDOW.start))

    assert served.calls == []
    assert not layout.root.exists()


# --------------------------------------------------------------------------- 8-Ks

# Two more 8-Ks of the season ended 2026-03-28, neither an earnings release: a Regulation FD
# disclosure furnishing a presentation as EX-99.1, and an agreement without an exhibit.
EIGHT_K_FD = Row(
    "8-K", "0000050863-26-000050", date(2026, 5, 4), date(2026, 5, 1), "intc-20260501.htm", "7.01,9.01"
)
EIGHT_K_DEAL = Row(
    "8-K", "0000050863-26-000055", date(2026, 6, 2), date(2026, 6, 1), "intc-20260601.htm", "1.01"
)
PRESENTATION = IndexRow("2", "EX-99.1", "investorday.htm", "EX-99.1", "1024")
PRESENTATION_BODY = b"<html><body><p>Investor day presentation.</p></body></html>"


def test_every_8_k_is_fetched_with_its_index_page_primary_document_and_ex_99_exhibits(layout):
    served = edgar((EIGHT_K_DEAL, EIGHT_K_FD, *RECENT))
    serve_eight_k(served, EIGHT_K_FD, (PRESENTATION,))
    serve_eight_k(served, EIGHT_K_DEAL)
    presentation_url = archive_document_url(EIGHT_K_FD.accession, "investorday.htm")
    served.responses[presentation_url] = ok(PRESENTATION_BODY, HTML_TYPE)

    result = fetch(layout, served)

    assert served.urls == [
        *through("exhibit_1"),
        index_url(EIGHT_K_FD),
        filing_url(EIGHT_K_FD),
        presentation_url,
        index_url(EIGHT_K_DEAL),
        filing_url(EIGHT_K_DEAL),
        *FETCH_URLS[12:],
    ]
    root = layout.raw(TICKER) / "2026-03-28"
    fd, deal = root / "8-K_2026-05-01_0000050863-26-000050", root / "8-K_2026-06-01_0000050863-26-000055"
    assert result["tickers"][0]["seasons"][3]["filings"][1:] == [
        {
            "form": "8-K",
            "accession": "0000050863-26-000050",
            "dated": "2026-05-01",
            "filed": "2026-05-04",
            "items": "7.01,9.01",
            "files": [
                {"path": str(fd / "0000050863-26-000050-index.htm"), "doc_id": None, "status": "new"},
                {
                    "path": str(fd / "intc-20260501.htm"),
                    "doc_id": "8-K_2026-05-01_0000050863-26-000050_intc-20260501",
                    "status": "new",
                },
                {
                    "path": str(fd / "investorday.htm"),
                    "doc_id": "8-K_2026-05-01_0000050863-26-000050_investorday",
                    "status": "new",
                },
            ],
        },
        {
            "form": "8-K",
            "accession": "0000050863-26-000055",
            "dated": "2026-06-01",
            "filed": "2026-06-02",
            "items": "1.01",
            "files": [
                {"path": str(deal / "0000050863-26-000055-index.htm"), "doc_id": None, "status": "new"},
                {
                    "path": str(deal / "intc-20260601.htm"),
                    "doc_id": "8-K_2026-06-01_0000050863-26-000055_intc-20260601",
                    "status": "new",
                },
            ],
        },
    ]
    assert (fd / "0000050863-26-000050-index.htm").read_bytes() == filing_index_html(
        EIGHT_K_FD, (PRESENTATION,)
    ).encode()
    assert (fd / "intc-20260501.htm").read_bytes() == eight_k_html(EIGHT_K_FD).encode()
    assert (fd / "investorday.htm").read_bytes() == PRESENTATION_BODY


def test_an_8_k_without_ex_99_exhibits_writes_its_index_page_and_primary_document(layout):
    others = (
        IndexRow("2", "EX-10.1", "q126agreement.htm", "EX-10.1", "51200"),
        IndexRow("3", "EX-104", "q126cover.htm", "EX-104", "40960"),
    )
    page = filing_index_html(EIGHT_K_Q1, others)
    served = edgar()
    served.responses[role_url("index_1")] = ok(page.encode(), HTML_TYPE)

    result = fetch(layout, served)

    assert served.urls == [url for url in FETCH_URLS if url != role_url("exhibit_1")]
    (release,) = result["tickers"][0]["seasons"][3]["filings"]
    assert [file["path"] for file in release["files"]] == [
        str(raw_file(layout, "index_1")),
        str(raw_file(layout, "eight_k_1")),
    ]
    assert raw_file(layout, "index_1").read_bytes() == page.encode()
    assert not raw_file(layout, "exhibit_1").exists()


def test_an_exhibits_pdf_copy_on_the_index_page_is_never_requested(layout):
    listed = (*Q2_EXHIBITS, IndexRow("4", "EX-99.1", "q226earningsrelease.pdf", "EX-99.1", "512000"))
    served = edgar()
    served.responses[role_url("index_2")] = ok(filing_index_html(EIGHT_K_Q2, listed).encode(), HTML_TYPE)

    fetch(layout, served)

    assert served.urls == list(FETCH_URLS)


def test_an_index_page_in_raw_is_never_requested_again(layout):
    failing = edgar()
    failing.responses[role_url("exhibit_2_1")] = status(503, "Service Unavailable")
    with pytest.raises(EdgarError):
        fetch(layout, failing)
    served = edgar()
    # EDGAR's page now lists only the release; the page in raw/, which lists both exhibits, stands.
    served.responses[role_url("index_2")] = ok(
        filing_index_html(EIGHT_K_Q2, Q2_EXHIBITS[:1]).encode(), HTML_TYPE
    )

    again = fetch(layout, served, start=AGAIN, calls_start=CALLS_AGAIN)

    assert served.urls == [
        COMPANY_TICKERS_URL,
        submissions_url(),
        role_url("exhibit_2_1"),
        role_url("exhibit_2_2"),
        companyfacts_url(),
    ]
    (release,) = again["tickers"][0]["seasons"][4]["filings"]
    assert release["files"] == [
        file_entry(layout, "index_2", "reused"),
        file_entry(layout, "eight_k_2", "reused"),
        file_entry(layout, "exhibit_2_1", "new"),
        file_entry(layout, "exhibit_2_2", "new"),
    ]
    assert season_files(layout) == {RAW[role]: raw_bytes(role) for role in RAW}


def test_an_index_page_in_raw_that_no_longer_parses_aborts_naming_it(layout):
    fetch(layout)
    path = place(raw_file(layout, "index_2"), f"<html>{MARKER}</html>")
    served = edgar()

    with pytest.raises(ValueError) as raised:
        fetch(layout, served, start=AGAIN, calls_start=CALLS_AGAIN)

    assert str(raised.value) == (
        f'{path}: filing index 0000050863-26-000062: no tableFile table with the summary "Document Format '
        'Files"; rename it with .rejected and run fetch again'
    )
    assert MARKER not in str(raised.value)
    assert served.urls == [COMPANY_TICKERS_URL, submissions_url()]
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
def test_an_index_page_that_cannot_be_parsed_aborts_and_writes_nothing_of_its_8_k(layout, body, rule):
    served = edgar()
    served.responses[role_url("index_2")] = ok(body.encode(), HTML_TYPE)

    with pytest.raises(ValueError) as raised:
        fetch(layout, served)

    assert str(raised.value) == f"filing index {EIGHT_K_Q2.accession}: {rule}"
    assert MARKER not in str(raised.value)
    assert served.urls == through("index_2")  # no document of the 8-K is requested
    assert raw_tree(layout) == tree(*before("index_2"))


# --------------------------------------------------------------------------- proxies and schedules


def test_a_proxy_statement_is_placed_by_its_filing_date_not_its_meeting_date(layout):
    meeting = replace(PROXY, period=date(2026, 5, 13))  # a DEF 14A's reportDate is its meeting's date
    served = edgar(tuple(meeting if row is PROXY else row for row in RECENT))

    result = fetch(layout, served)

    assert served.urls == list(FETCH_URLS)
    assert result["tickers"][0]["seasons"][2]["filings"][1] == {
        "form": "DEF 14A",
        "accession": "0001193125-26-112233",
        "dated": "2026-03-27",
        "filed": "2026-03-27",
        "items": "",
        "files": [file_entry(layout, "proxy", "new")],
    }
    assert raw_file(layout, "proxy").read_bytes() == raw_bytes("proxy")


# A beneficial owner's amended schedule under each of EDGAR's spellings: the older one's primary
# document is HTML, the newer one's a rendering of the XML in the filing's folder.
SC_13G_A = Row("SC 13G/A", "0000950103-26-004321", date(2026, 5, 8), date(2026, 3, 31), "dp123456_sc13ga.htm")
SCHEDULE_13G_A = Row(
    "SCHEDULE 13G/A",
    "0001104659-26-054321",
    date(2026, 5, 12),
    date(2026, 3, 31),
    "xslSCHEDULE_13G_X02/primary_doc.xml",
)
SC_13G_A_BODY = b"<html><body><p>Amendment No. 3 to Schedule 13G.</p></body></html>"
SCHEDULE_13G_A_BODY = (
    b'<?xml version="1.0"?><edgarSubmission><formData><coverPageHeader><issuerInfo>'
    b"<issuerCik>0000050863</issuerCik></issuerInfo></coverPageHeader></formData></edgarSubmission>"
)


def test_both_spellings_of_an_amended_schedule_are_fetched_by_their_raw_documents(layout):
    served = edgar((SCHEDULE_13G_A, SC_13G_A, *RECENT))
    html_url = archive_document_url(SC_13G_A.accession, "dp123456_sc13ga.htm")
    xml_url = archive_document_url(SCHEDULE_13G_A.accession, "primary_doc.xml")  # not the rendering
    served.responses[html_url] = ok(SC_13G_A_BODY, HTML_TYPE)
    served.responses[xml_url] = ok(SCHEDULE_13G_A_BODY, "text/xml")

    result = fetch(layout, served)

    assert served.urls == [*through("exhibit_1"), html_url, xml_url, *FETCH_URLS[12:]]
    older = "2026-03-28/SC13GA_2026-05-08_0000950103-26-004321/dp123456_sc13ga.htm"
    newer = "2026-03-28/SCHEDULE13GA_2026-05-12_0001104659-26-054321/primary_doc.xml"
    assert result["tickers"][0]["seasons"][3]["filings"][1:] == [
        {
            "form": "SC 13G/A",
            "accession": "0000950103-26-004321",
            "dated": "2026-05-08",
            "filed": "2026-05-08",
            "items": "",
            "files": [
                {
                    "path": str(layout.raw(TICKER) / older),
                    "doc_id": "SC13GA_2026-05-08_0000950103-26-004321_dp123456_sc13ga",
                    "status": "new",
                }
            ],
        },
        {
            "form": "SCHEDULE 13G/A",
            "accession": "0001104659-26-054321",
            "dated": "2026-05-12",
            "filed": "2026-05-12",
            "items": "",
            "files": [
                {
                    "path": str(layout.raw(TICKER) / newer),
                    "doc_id": "SCHEDULE13GA_2026-05-12_0001104659-26-054321_primary_doc",
                    "status": "new",
                }
            ],
        },
    ]
    written = raw_tree(layout)
    assert (written[older], written[newer]) == (SC_13G_A_BODY, SCHEDULE_13G_A_BODY)


# --------------------------------------------------------------------------- Form 4

# An insider's Form 4 of the season ended 2026-03-28, listed as EDGAR's rendering of its XML.
FORM_4_IN_SEASON = Row(
    "4", "0001209191-26-050505", date(2026, 5, 4), date(2026, 4, 30), "xslF345X06/form4.xml"
)
FORM_4_URL = archive_document_url("0001209191-26-050505", "form4.xml")
FORM_4_PATH = "2026-03-28/4_2026-04-30_0001209191-26-050505/form4.xml"
OTHER_ISSUER = "0001234567"


def form4_xml(issuer: str = CIK, document_type: str = "4") -> bytes:
    """A Form 4 laid out as EDGAR keeps it: an officer's sale of ``issuer``'s shares."""
    return f"""<?xml version="1.0"?>
<ownershipDocument>
    <schemaVersion>X0609</schemaVersion>
    <documentType>{document_type}</documentType>
    <periodOfReport>2026-04-30</periodOfReport>
    <issuer>
        <issuerCik>{issuer}</issuerCik>
        <issuerName>Example Issuer</issuerName>
        <issuerTradingSymbol>EXMP</issuerTradingSymbol>
    </issuer>
    <reportingOwner>
        <reportingOwnerId>
            <rptOwnerCik>0001999999</rptOwnerCik>
            <rptOwnerName>Officer Example</rptOwnerName>
        </reportingOwnerId>
        <reportingOwnerRelationship>
            <isOfficer>1</isOfficer>
            <officerTitle>Chief Financial Officer</officerTitle>
        </reportingOwnerRelationship>
    </reportingOwner>
    <nonDerivativeTable>
        <nonDerivativeTransaction>
            <transactionDate><value>2026-04-30</value></transactionDate>
            <transactionCoding>
                <transactionFormType>4</transactionFormType>
                <transactionCode>S</transactionCode>
            </transactionCoding>
            <transactionAmounts>
                <transactionShares><value>10000</value></transactionShares>
                <transactionPricePerShare><value>24.50</value></transactionPricePerShare>
                <transactionAcquiredDisposedCode><value>D</value></transactionAcquiredDisposedCode>
            </transactionAmounts>
        </nonDerivativeTransaction>
    </nonDerivativeTable>
</ownershipDocument>
""".encode()


def test_a_form_4s_xml_is_fetched_at_its_raw_files_path(layout):
    served = edgar((FORM_4_IN_SEASON, *RECENT))
    served.responses[FORM_4_URL] = ok(form4_xml(), "text/xml")

    result = fetch(layout, served)

    assert served.urls == [*through("exhibit_1"), FORM_4_URL, *FETCH_URLS[12:]]
    assert result["tickers"][0]["seasons"][3]["filings"][1] == {
        "form": "4",
        "accession": "0001209191-26-050505",
        "dated": "2026-04-30",
        "filed": "2026-05-04",
        "items": "",
        "files": [{"path": str(layout.raw(TICKER) / FORM_4_PATH), "doc_id": None, "status": "new"}],
    }
    assert raw_tree(layout)[FORM_4_PATH] == form4_xml()


def test_a_form_4_of_another_issuer_is_written_too(layout):
    served = edgar((FORM_4_IN_SEASON, *RECENT))
    served.responses[FORM_4_URL] = ok(form4_xml(OTHER_ISSUER), "text/xml")

    result = fetch(layout, served)

    (form4,) = result["tickers"][0]["seasons"][3]["filings"][1]["files"]
    assert form4["status"] == "new"
    assert raw_tree(layout)[FORM_4_PATH] == form4_xml(OTHER_ISSUER)


@pytest.mark.parametrize(
    ("body", "problem"),
    [
        (
            f'<?xml version="1.0"?><!DOCTYPE ownershipDocument [<!ENTITY owner "{MARKER}">]>'
            "<ownershipDocument>&owner;</ownershipDocument>".encode(),
            "Form 4: the XML declares a document type or an entity",
        ),
        (
            f"<html><body><p>{MARKER}</p></body></html>".encode(),
            "Form 4: the root element must be ownershipDocument",
        ),
        (form4_xml(document_type="5"), "Form 4: documentType must be 4"),
        (form4_xml(issuer=MARKER), "Form 4: issuer/issuerCik must be ten digits"),
    ],
    ids=["entity", "html", "document-type", "issuer"],
)
def test_a_form_4_that_does_not_read_aborts_the_run_before_it_is_written(layout, body, problem):
    served = edgar((FORM_4_IN_SEASON, *RECENT))
    served.responses[FORM_4_URL] = ok(body, "text/xml")

    with pytest.raises(ValueError) as raised:
        fetch(layout, served)

    assert str(raised.value) == f"GET {FORM_4_URL}: {problem}"
    assert MARKER not in str(raised.value)
    assert served.urls == [*through("exhibit_1"), FORM_4_URL]
    assert raw_tree(layout) == tree(*before("ten_q_2"), rows=(FORM_4_IN_SEASON, *RECENT))


# --------------------------------------------------------------------------- what is never fetched

# Forms the measures list and nothing fetches (one filed after the last 10-Q: pending), then forms
# the domain does not read at all.
LISTED_ONLY = (
    Row("S-3ASR", "0001193125-26-200001", date(2026, 8, 15), None, "d200001ds3asr.htm"),
    Row("10-Q/A", "0000050863-26-000071", date(2026, 6, 3), date(2026, 3, 28), "intc-20260328a.htm"),
    Row("424B5", "0001193125-26-150002", date(2026, 6, 2), None, "d150002d424b5.htm"),
    Row("NT 10-Q", "0000050863-26-000045", date(2026, 5, 7), date(2026, 3, 28), "ntq.htm"),
    Row("4/A", "0001209191-26-055555", date(2026, 5, 6), date(2026, 4, 30), "xslF345X05/wk-form4a.xml"),
    Row(
        "8-K/A",
        "0000050863-26-000070",
        date(2026, 5, 5),
        date(2026, 4, 23),
        "intc-20260423a.htm",
        "2.02,9.01",
    ),
)
NOT_READ = (
    Row("S-8", "0000050863-26-000025", date(2026, 2, 21), None, "s8.htm"),
    Row("3", "0001209191-26-033333", date(2026, 2, 20), date(2026, 2, 18), "xslF345X02/wk-form3.xml"),
    Row("SC 13G", "0000950103-26-001111", date(2026, 2, 14), None, "sc13g.htm"),
    Row("DEFA14A", "0001193125-26-112234", date(2026, 3, 27), None, "d123456ddefa14a.htm"),
)


def test_forms_listed_but_never_fetched_and_forms_not_read_are_never_requested(layout):
    served = edgar((*LISTED_ONLY, *NOT_READ, *RECENT))

    result = fetch(layout, served)

    assert served.urls == list(FETCH_URLS)
    (entry,) = result["tickers"]
    assert entry["seasons"] == season_entries(layout)
    assert entry["pending_filings"] == [
        PENDING_FORM_4,
        {
            "form": "S-3ASR",
            "accession": "0001193125-26-200001",
            "dated": "2026-08-15",
            "filed": "2026-08-15",
            "items": "",
        },
    ]
    assert entry["skipped_filings"] == []


# Filings Rule B leaves pending, after the 10-Q filed 2026-07-24: a proxy statement (by its filing
# date) and the next quarter's earnings release, beside the Form 4 of RECENT.
LATE_PROXY = Row(
    "DEF 14A", "0001193125-26-210001", date(2026, 8, 10), date(2026, 9, 24), "d210001ddef14a.htm"
)
RELEASE_Q3 = Row(
    "8-K", "0000050863-26-000089", date(2026, 10, 6), date(2026, 10, 6), "intc-20261006.htm", "2.02,9.01"
)
PENDING = [
    PENDING_FORM_4,
    {
        "form": "DEF 14A",
        "accession": "0001193125-26-210001",
        "dated": "2026-08-10",
        "filed": "2026-08-10",
        "items": "",
    },
    {
        "form": "8-K",
        "accession": "0000050863-26-000089",
        "dated": "2026-10-06",
        "filed": "2026-10-06",
        "items": "2.02,9.01",
    },
]


@pytest.mark.parametrize(
    ("to", "pending", "urls"),
    [
        (TODAY, PENDING, FETCH_URLS),
        (date(2026, 6, 27), PENDING, FETCH_URLS),
        (date(2026, 6, 26), [], (*FETCH_URLS[:12], companyfacts_url())),
    ],
    ids=["to-today", "to-the-newest-season-end", "to-the-day-before-it"],
)
def test_pending_filings_are_listed_and_none_of_their_documents_is_requested(layout, to, pending, urls):
    served = edgar((RELEASE_Q3, LATE_PROXY, *RECENT))  # serves none of the pending filings' documents

    result = fetch(layout, served, window=Window(WINDOW.start, to))

    assert served.urls == list(urls)
    assert result["tickers"][0]["pending_filings"] == pending
    assert not list(layout.raw(TICKER).rglob("*_2026-07-30_*"))


# Rows Rule B cannot place or fetch cannot request, in EDGAR's order (newest first).
SKIPPED = (
    Row("4", "0001209191-26-066666", date(2026, 5, 2), date(2026, 5, 9), "xslF345X06/form4.xml"),
    Row("8-K", "0000050863-26-000044", date(2026, 5, 1), None, "intc-20260501x.htm", "5.02,9.01"),
    Row("DEF 14A", "0001193125-26-120000", date(2026, 4, 2), None, "proxy/d120000ddef14a.htm"),
)


def test_rows_that_cannot_be_placed_or_requested_are_listed_as_skipped(layout):
    served = edgar((*SKIPPED, *RECENT))

    result = fetch(layout, served)

    assert served.urls == list(FETCH_URLS)
    (entry,) = result["tickers"]
    assert entry["skipped_filings"] == [
        {
            "form": "4",
            "accession": "0001209191-26-066666",
            "filed": "2026-05-02",
            "reason": "its reportDate is after the 4's filing date",
        },
        {
            "form": "8-K",
            "accession": "0000050863-26-000044",
            "filed": "2026-05-01",
            "reason": "its reportDate is empty",
        },
        {
            "form": "DEF 14A",
            "accession": "0001193125-26-120000",
            "filed": "2026-04-02",
            "reason": "its primaryDocument is no file fetch can request",
        },
    ]
    assert entry["seasons"] == season_entries(layout)


# --------------------------------------------------------------------------- seasons listed later

# A 10-K filed after the next quarter ended, and an 8-K dated between that quarter's end and the
# 10-K's filing: Rule B places it in the 10-K's season until the quarter's 10-Q is listed.
LATE_TEN_K = replace(TEN_K, filed=date(2026, 4, 15))
EIGHT_K_APRIL = Row(
    "8-K", "0000050863-26-000030", date(2026, 4, 2), date(2026, 4, 1), "intc-20260401.htm", "8.01,9.01"
)


def test_a_filing_a_later_listing_places_in_another_season_is_written_again_there(layout):
    early, later = edt(2026, 4, 20, 6, 0), edt(2026, 4, 25, 6, 0)
    first_rows = (EIGHT_K_APRIL, PROXY, EIGHT_K_OTHER, LATE_TEN_K, OLD_TEN_Q, OLD_TEN_K)
    served = edgar(first_rows)
    serve_eight_k(served, EIGHT_K_APRIL)
    fetch(
        layout,
        served,
        window=Window(WINDOW.start, early.date()),
        calls=provider(events_page([call_row(CALL_OLD_Q)]), (CALL_OLD_Q,)),
        now=early,
        start=early.replace(second=1),
        calls_start=early.replace(minute=1),
    )
    stored = layout.raw(TICKER) / "2025-12-27" / "8-K_2026-04-01_0000050863-26-000030"
    assert sorted(path.name for path in stored.iterdir()) == [
        "0000050863-26-000030-index.htm",
        "intc-20260401.htm",
    ]
    held = snapshot(stored)
    served = edgar((TEN_Q_1, EIGHT_K_Q1, *first_rows))
    serve_eight_k(served, EIGHT_K_APRIL)

    fetch(
        layout,
        served,
        window=Window(WINDOW.start, later.date()),
        calls=provider(events_page([call_row(call) for call in (CALL_Q1, CALL_OLD_Q)]), (CALL_Q1,)),
        now=later,
        start=later.replace(second=1),
        calls_start=later.replace(minute=1),
    )

    assert served.urls == [
        COMPANY_TICKERS_URL,
        submissions_url(),
        role_url("ten_q_1"),
        index_url(EIGHT_K_APRIL),
        filing_url(EIGHT_K_APRIL),
        *map(role_url, ("index_1", "eight_k_1", "exhibit_1")),
        companyfacts_url(),
    ]
    placed = layout.raw(TICKER) / "2026-03-28" / "8-K_2026-04-01_0000050863-26-000030"
    assert (placed / "0000050863-26-000030-index.htm").read_bytes() == filing_index_html(
        EIGHT_K_APRIL, ()
    ).encode()
    assert (placed / "intc-20260401.htm").read_bytes() == eight_k_html(EIGHT_K_APRIL).encode()
    assert snapshot(stored) == held  # the copy in the former season is left for the bot to withdraw
    moved = (
        "the newest submissions place this filing in the season 2026-03-28, not in this season; rename it "
        "with .rejected and run fetch"
    )
    assert (stored, moved) in season_documents(layout, TICKER, later + timedelta(minutes=5)).invalid_files


# --------------------------------------------------------------------------- company facts


def test_the_company_facts_are_written_again_only_when_their_bytes_changed(layout):
    fetch(layout)
    same = fetch(layout, start=AGAIN, calls_start=CALLS_AGAIN)
    assert same["tickers"][0]["companyfacts"] == {
        "path": str(layout.raw(TICKER) / COMPANYFACTS),
        "status": "reused",
    }
    respaced = json.dumps(companyfacts_document(), separators=(",", ": ")).encode()  # the same facts
    served = edgar()
    served.responses[companyfacts_url()] = ok(respaced, JSON_TYPE)

    changed = fetch(layout, served, start=LATER, calls_start=CALLS_LATER)

    newer = layout.raw(TICKER) / "companyfacts_20261008T054503EDT.json"
    assert changed["tickers"][0]["companyfacts"] == {"path": str(newer), "status": "new"}
    assert newer.read_bytes() == respaced
    assert (layout.raw(TICKER) / COMPANYFACTS).read_bytes() == companyfacts_json().encode()  # kept


@pytest.mark.parametrize(
    ("body", "problem"),
    [
        (b'{"cik": 320193, "entityName": "APPLE INC", "facts": {}}', "cik is not the requested CIK"),
        (b"\xff{}", "the body is not UTF-8"),
        (b'{"cik": 50863, "cik": 50863}', "invalid JSON: an object repeats a key"),
        (
            json.dumps(
                {
                    "cik": 50863,
                    "entityName": ENTITY_NAME,
                    "facts": {
                        "us-gaap": {
                            "Goodwill": {
                                "units": {
                                    "USD": [{"end": "2026-06-27", "val": MARKER, "accn": TEN_Q_2.accession}]
                                }
                            }
                        }
                    },
                }
            ).encode(),
            "facts.us-gaap.Goodwill.units.USD[0].val must be a number",
        ),
    ],
    ids=["another-company", "not-utf8", "repeated-key", "value"],
)
def test_company_facts_that_do_not_read_abort_the_run_before_they_are_written(layout, body, problem):
    served, answering = edgar(), FakeEarningsCalls()
    served.responses[companyfacts_url()] = ok(body, JSON_TYPE)

    with pytest.raises(ValueError) as raised:
        fetch(layout, served, calls=answering)

    assert str(raised.value) == f"GET {companyfacts_url()}: companyfacts CIK{CIK}: {problem}"
    assert MARKER not in str(raised.value)
    assert served.urls == list(FETCH_URLS)
    assert answering.calls == []  # the run ends before the calls
    assert raw_tree(layout) == tree(*DOCUMENTS)


# --------------------------------------------------------------------------- refresh

# Where a run with --refresh on the clocks AGAIN and CALLS_AGAIN writes its calls list, below raw/INTC/.
REFRESH_EVENTS = "calls_20261008T054100EDT_1.json"
CORRECTED_TITLE = "Intel Corporation - Q2 2026 Earnings Call (corrected)"


def test_refresh_requests_every_span_document_and_transcript_again_and_rewrites_none(layout):
    fetch(layout)
    stored = raw_tree(layout)
    served, answering = edgar(), provider(transcripts=CALLS_OF_SEASONS)

    again = fetch(layout, served, calls=answering, start=AGAIN, calls_start=CALLS_AGAIN, refresh=True)

    assert served.urls == list(FETCH_URLS)  # the ticker map, the submissions, every document, the facts
    assert answering.urls == list(CALLS_URLS)  # the calls list, then every span call's transcript
    assert (again["refresh"], again["requests"], again["transcript_requests"]) == (True, 18, 4)
    (entry,) = again["tickers"]
    assert entry["submissions"] == {"path": str(layout.raw(TICKER) / SUBMISSIONS), "status": "reused"}
    assert entry["companyfacts"] == {"path": str(layout.raw(TICKER) / COMPANYFACTS), "status": "reused"}
    assert entry["seasons"] == season_entries(layout, "verified")
    assert entry["calls"] == {
        **calls_entry(layout, transcripts="verified"),
        "events": {
            "status": "new",
            "path": str(layout.raw(TICKER) / REFRESH_EVENTS),
            "pages": 1,
            "fetched_at": "2026-10-08T05:41:00-04:00",
            "reason": REFRESH_REASON,
        },
    }
    # The one file written is the calls list asked for again: every list request writes its pages.
    assert raw_tree(layout) == {**stored, REFRESH_EVENTS: events_page()}


def test_refresh_writes_a_changed_transcript_beside_the_stored_one_and_the_newest_is_read(layout):
    fetch(layout)
    corrected = transcript_body(CALL_Q2, header={"title": CORRECTED_TITLE})
    answering = provider(transcripts=CALLS_OF_SEASONS)
    answering.responses[transcript_url(CALL_Q2.id)] = provider_ok(corrected)

    again = fetch(layout, calls=answering, start=AGAIN, calls_start=CALLS_AGAIN, refresh=True)

    newer = layout.raw(TICKER) / "2026-06-27" / "transcript_248001_20261008T054103EDT.json"
    old, first, second = again["tickers"][0]["calls"]["transcripts"]
    assert [old["status"], first["status"]] == ["verified", "verified"]
    assert (second["path"], second["status"]) == (str(newer), "refreshed")
    assert newer.read_bytes() == corrected
    assert raw_file(layout, "transcript_q2").read_bytes() == raw_bytes("transcript_q2")  # kept
    call = season_documents(layout, TICKER, NOW).documents()[DOC_IDS["call_q2"]]
    assert (call.path, call.title) == (newer, CORRECTED_TITLE)

    # Without --refresh the newest copy is kept: nothing is due, so the provider is not asked.
    kept = fetch(layout, calls=FakeEarningsCalls(), start=LATER, calls_start=CALLS_LATER)
    assert kept["tickers"][0]["calls"]["transcripts"][2] == {**second, "status": "reused"}
    # With it again, the newest copy is the one compared.
    answering = provider(transcripts=CALLS_OF_SEASONS)
    answering.responses[transcript_url(CALL_Q2.id)] = provider_ok(corrected)
    last = fetch(
        layout,
        calls=answering,
        start=FETCHED_AT + timedelta(minutes=20),
        calls_start=CALLS_FETCHED_AT + timedelta(minutes=20),
        refresh=True,
    )
    assert last["tickers"][0]["calls"]["transcripts"][2] == {**second, "status": "verified"}


def test_refresh_reports_an_edgar_document_that_changed_and_never_rewrites_it(layout, tmp_path):
    fetch(layout)
    # The second exhibit in raw/ becomes a symbolic link to a copy of itself: a file that cannot be read.
    stored = raw_file(layout, "exhibit_2_2")
    target = place(tmp_path / "elsewhere.htm", stored.read_bytes())
    stored.unlink()
    os.symlink(target, stored)
    held = snapshot(layout.raw(TICKER))
    served = edgar()
    served.responses[role_url("exhibit_2_1")] = ok(b"<p>A corrected release.</p>", HTML_TYPE)
    # EDGAR's index page now lists only the release; the page in raw/ lists both exhibits.
    served.responses[role_url("index_2")] = ok(
        filing_index_html(EIGHT_K_Q2, Q2_EXHIBITS[:1]).encode(), HTML_TYPE
    )

    again = fetch(layout, served, start=AGAIN, calls_start=CALLS_AGAIN, refresh=True)

    assert served.urls == list(FETCH_URLS)  # both exhibits the page in raw/ lists
    changed = {"index_2": "changed", "exhibit_2_1": "changed", "exhibit_2_2": "changed"}
    assert again["tickers"][0]["seasons"] == season_entries(layout, "verified", changed)
    after = snapshot(layout.raw(TICKER))
    assert {path: state for path, state in after.items() if path != REFRESH_EVENTS} == held  # none rewritten


def test_refresh_asks_the_provider_nothing_for_a_window_without_a_listed_season(layout):
    fetch(layout)
    served, answering = edgar(), FakeEarningsCalls()

    result = fetch(
        layout,
        served,
        window=Window(date(2026, 6, 28), TODAY),
        calls=answering,
        start=AGAIN,
        calls_start=CALLS_AGAIN,
        refresh=True,
    )

    assert served.urls == [COMPANY_TICKERS_URL, submissions_url()]
    assert answering.urls == []
    calls = result["tickers"][0]["calls"]
    assert (calls["events"]["status"], calls["events"]["reason"], calls["transcripts"]) == (
        "reused",
        None,
        [],
    )


# --------------------------------------------------------------------------- tickers

APPLE_CIK = "0000320193"
# A foreign private issuer's recent filings: no 10-K or 10-Q, so no season.
FOREIGN_FILINGS = (
    Row("6-K", "0000320193-26-000020", date(2026, 5, 1), None, "aapl-6k.htm"),
    Row("20-F", "0000320193-26-000010", date(2026, 3, 2), date(2025, 12, 31), "aapl-20f.htm"),
)


def test_unsupported_tickers_are_reported_and_the_run_goes_on(layout):
    served = edgar()
    apple_body = submissions_json(APPLE_CIK, "APPLE INC", FOREIGN_FILINGS)
    served.responses[submissions_url(APPLE_CIK)] = ok(apple_body.encode(), JSON_TYPE)

    result = fetch(layout, served, "ZZZZ", "aapl", "INTC")

    unlisted, foreign, intel = result["tickers"]
    assert unlisted == unsupported_entry("ZZZZ", "not in SEC company_tickers.json")
    apple_path = layout.raw("AAPL") / "submissions_20261008T053002EDT.json"
    assert foreign == unsupported_entry(
        "AAPL",
        "no 10-K or 10-Q among the 2 recent filings; forms seen: 20-F, 6-K",
        cik=APPLE_CIK,
        entity_name="APPLE INC",
        submissions={"path": str(apple_path), "status": "new"},
    )
    assert raw_tree(layout, "AAPL") == {apple_path.name: apple_body.encode()}  # its submissions stay
    assert intel["status"] == "fetched"
    assert served.urls == [COMPANY_TICKERS_URL, submissions_url(APPLE_CIK), *FETCH_URLS[1:]]  # the map once


@pytest.mark.parametrize(
    ("row", "problem"),
    [
        (
            Row("10-Q", "0000050863-26-000070", date(2026, 7, 30), date(2026, 6, 27), "intc-20260627x.htm"),
            "two filings report the period 2026-06-27",
        ),
        (
            Row("8-K", "0000050863-26-000063", date(2026, 7, 23), None, "intc-20260723x.htm", "2.02,9.01"),
            "filings.recent.reportDate[0] is empty; an 8-K with Item 2.02 must name its event date",
        ),
        (
            Row(
                "8-K",
                "0000050863-26-000063",
                date(2026, 7, 23),
                date(2026, 7, 24),
                "intc-20260724x.htm",
                "2.02,9.01",
            ),
            "filings.recent.reportDate[0] is after the 8-K's filing date; "
            "an 8-K with Item 2.02 must name its event date",
        ),
    ],
    ids=["two-filings-for-a-season", "undated-release", "release-dated-after-its-filing"],
)
def test_submissions_whose_seasons_cannot_be_listed_make_the_ticker_unsupported(layout, row, problem):
    rows = (row, *RECENT)
    served = edgar(rows)

    result = fetch(layout, served)

    (entry,) = result["tickers"]
    assert entry == unsupported_entry(
        TICKER,
        f"submissions CIK{CIK}: {problem}",
        cik=CIK,
        entity_name=ENTITY_NAME,
        submissions={"path": str(layout.raw(TICKER) / SUBMISSIONS), "status": "new"},
    )
    assert served.urls == [COMPANY_TICKERS_URL, submissions_url()]
    assert raw_tree(layout) == {SUBMISSIONS: submissions_json(rows=rows).encode()}


def test_tickers_are_normalised_and_each_fetched_once(layout):
    result = fetch(layout, None, "intc", "INTC")

    assert [entry["ticker"] for entry in result["tickers"]] == [TICKER]
    assert result["requests"] == 18


def test_an_invalid_ticker_is_refused_before_any_request(layout):
    served = edgar()

    with pytest.raises(ValueError, match="ticker must be a US symbol"):
        fetch(layout, served, "INTC", "../INTC")

    assert served.calls == []
    assert not layout.root.exists()


def test_the_watchlists_stock_section_is_the_default(layout, tmp_path):
    watchlist = write_watchlist(tmp_path, ("intc",))

    result = workflow.fetch(
        layout,
        [],
        client(edgar()),
        calls_client(provider(transcripts=CALLS_OF_SEASONS)),
        WINDOW,
        NOW,
        watchlist=watchlist,
    )

    assert [entry["ticker"] for entry in result["tickers"]] == [TICKER]


def test_explicit_tickers_never_read_the_watchlist(layout, tmp_path):
    result = workflow.fetch(
        layout,
        [TICKER],
        client(edgar()),
        calls_client(provider(transcripts=CALLS_OF_SEASONS)),
        WINDOW,
        NOW,
        watchlist=tmp_path / "missing.json",
    )

    assert result["tickers"][0]["status"] == "fetched"


def test_a_missing_watchlist_fails_before_any_request(layout, tmp_path):
    served, answering = edgar(), provider(transcripts=CALLS_OF_SEASONS)

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
    served.responses[role_url("exhibit_2_1")] = response

    with pytest.raises(EdgarError) as raised:
        fetch(layout, served)

    assert str(raised.value) == f"GET {role_url('exhibit_2_1')}: {problem}"
    assert served.urls == through("exhibit_2_1")
    assert raw_tree(layout) == tree(*before("exhibit_2_1"))


@pytest.mark.parametrize("role", ["proxy", "ten_q_2", "index_2", "exhibit_2_1"])
def test_a_document_cut_short_aborts_the_run_and_a_later_fetch_writes_it(layout, role):
    served = edgar()
    full = served.responses[role_url(role)]
    assert isinstance(full, Response)
    size = len(full.body)
    served.responses[role_url(role)] = ok(
        full.body, full.headers["content-type"], content_length=str(size + 1)
    )

    with pytest.raises(EdgarError) as raised:
        fetch(layout, served)

    assert (
        str(raised.value)
        == f"GET {role_url(role)}: the body ended after {size} of {size + 1} bytes; run fetch again"
    )
    assert raw_tree(layout) == tree(*before(role))

    later = edgar()
    fetch(layout, later, start=AGAIN, calls_start=CALLS_AGAIN)

    missing = DOCUMENTS[DOCUMENTS.index(role) :]
    assert later.urls == [COMPANY_TICKERS_URL, submissions_url(), *map(role_url, missing), companyfacts_url()]
    assert season_files(layout) == {RAW[name]: raw_bytes(name) for name in RAW}


def test_an_answer_over_its_limit_aborts_the_run_and_writes_nothing_of_it(layout):
    served = edgar()
    served.responses[role_url("index_2")] = ok(b" " * (INDEX_LIMIT + 1), HTML_TYPE)

    with pytest.raises(EdgarError) as raised:
        fetch(layout, served)

    assert str(raised.value) == f"GET {role_url('index_2')}: more than {INDEX_LIMIT} bytes"
    assert raw_tree(layout) == tree(*before("index_2"))


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
    ("url", "body", "message"),
    [
        (COMPANY_TICKERS_URL, b"\xff{}", "company_tickers.json: the body is not UTF-8"),
        (
            submissions_url(),
            b'{"cik": "50863", "name": "INTEL CORP"}',
            f"submissions CIK{CIK}: filings is missing",
        ),
        (submissions_url(), b"\xff{}", "submissions: the body is not UTF-8"),
    ],
    ids=["ticker-map-not-utf8", "no-filings", "submissions-not-utf8"],
)
def test_listings_that_cannot_be_read_abort_before_anything_is_written(layout, url, body, message):
    served = edgar()
    served.responses[url] = ok(body, JSON_TYPE)

    with pytest.raises(ValueError) as raised:
        fetch(layout, served)

    assert str(raised.value) == message
    assert served.urls == [COMPANY_TICKERS_URL, submissions_url()][: 1 if url == COMPANY_TICKERS_URL else 2]
    assert not layout.root.exists()


# --------------------------------------------------------------------------- calls


def test_every_provider_request_sends_the_key_and_no_value_reaches_raw_or_the_output(layout):
    served, answering = edgar(), provider(transcripts=CALLS_OF_SEASONS)

    result = workflow.fetch(
        layout, [TICKER], client(served), calls_client(answering, api_key=CANARY), WINDOW, NOW
    )

    assert [(headers, limit) for _, headers, limit in answering.calls] == [
        ({"X-API-Key": CANARY, "Accept": "application/json"}, BODY_LIMIT)
    ] * 4
    assert CANARY not in repr(result) and API_KEY not in repr(result)
    assert all(CANARY.encode() not in data for data in raw_tree(layout).values())
    assert {headers.get("X-API-Key") for _, headers, _ in served.calls} == {None}  # never sent to EDGAR


def test_the_list_is_asked_for_again_once_due_and_each_request_writes_a_capture(layout):
    fetch(layout)  # no call is listed for the season ended 2025-12-27: unavailable as of 2026-10-08
    answering = provider(transcripts=CALLS_OF_SEASONS)
    week = edt(2026, 10, 15, 6, 0)

    again = fetch(
        layout,
        calls=answering,
        now=week,
        start=edt(2026, 10, 15, 5, 30, 1),
        calls_start=edt(2026, 10, 15, 5, 31),
    )

    assert answering.urls == [CALLS_URLS[0]]  # the transcripts are in raw/ already
    newer = layout.raw(TICKER) / "calls_20261015T053100EDT_1.json"
    assert again["tickers"][0]["calls"]["events"] == {
        "status": "new",
        "path": str(newer),
        "pages": 1,
        "fetched_at": "2026-10-15T05:31:00-04:00",
        "reason": (
            "the newest calls list, fetched 2026-10-08, is 7 days old or more and lists no call for the "
            "season 2025-12-27"
        ),
    }
    assert newer.read_bytes() == (layout.raw(TICKER) / EVENTS).read_bytes() == events_page()  # both kept


def test_a_season_listed_later_brings_its_release_and_its_call(layout):
    # On the release day, before the call: the quarter's 10-Q is not listed yet, so its release is pending.
    noon = edt(2026, 7, 23, 12, 0)
    first = fetch(
        layout,
        edgar(tuple(row for row in RECENT if row.filed <= noon.date())),
        window=Window(WINDOW.start, noon.date()),
        calls=provider(
            events_page([call_row(call) for call in (CALL_Q1, CALL_OLD_Q, CALL_DROPPED)]),
            (CALL_OLD_Q, CALL_Q1),
        ),
        now=noon,
        start=noon.replace(second=1),
        calls_start=noon.replace(minute=1),
    )
    (entry,) = first["tickers"]
    assert [season["season"] for season in entry["seasons"]][-1] == "2026-03-28"
    assert entry["pending_filings"] == [
        {
            "form": "8-K",
            "accession": "0000050863-26-000062",
            "dated": "2026-07-23",
            "filed": "2026-07-23",
            "items": "2.02,9.01",
        }
    ]
    # Two days on, the 10-Q is listed: the release joins its season, and the calls list, fetched on
    # the season's due date, is due.
    later = edt(2026, 7, 25, 6, 30)
    served = edgar(tuple(row for row in RECENT if row.filed <= later.date()))
    answering = provider(transcripts=CALLS_OF_SEASONS)

    result = fetch(
        layout,
        served,
        window=Window(WINDOW.start, later.date()),
        calls=answering,
        now=later,
        start=later.replace(second=1),
        calls_start=later.replace(minute=31),
    )

    assert served.urls == [
        COMPANY_TICKERS_URL,
        submissions_url(),
        *map(role_url, ("ten_q_2", "index_2", "eight_k_2", "exhibit_2_1", "exhibit_2_2")),
        companyfacts_url(),
    ]
    assert answering.urls == [CALLS_URLS[0], CALLS_URLS[3]]
    (entry,) = result["tickers"]
    assert entry["pending_filings"] == []
    assert entry["calls"]["events"]["reason"] == (
        "the newest calls list was fetched 2026-07-23, on or before the season 2026-06-27's due date "
        "2026-07-23"
    )
    assert [item["status"] for item in entry["calls"]["transcripts"]] == ["reused", "reused", "new"]
    assert season_files(layout) == {RAW[role]: raw_bytes(role) for role in RAW}


def test_pending_calls_are_listed_and_never_requested(layout):
    listed = events_page([call_row(call) for call in (CALL_Q3, *CALLS)])
    answering = provider(listed, CALLS_OF_SEASONS)  # serves no transcript of the call of 2026-10-06

    result = fetch(layout, calls=answering)

    assert answering.urls == list(CALLS_URLS)
    pending = {"id": CALL_Q3.id, "date": "2026-10-06", "fiscal_year": 2026, "fiscal_quarter": 3}
    assert result["tickers"][0]["calls"]["pending_calls"] == [pending]
    assert not list(layout.raw(TICKER).rglob(f"transcript_{CALL_Q3.id}*"))

    earlier = fetch(
        layout,
        window=Window(WINDOW.start, date(2026, 6, 26)),
        calls=FakeEarningsCalls(),
        start=AGAIN,
        calls_start=CALLS_AGAIN,
    )
    assert earlier["tickers"][0]["calls"]["pending_calls"] == []  # the window ends before the newest season


def test_an_ambiguous_symbol_leaves_the_calls_unsupported_and_writes_nothing(layout):
    answering = provider(events_page(ambiguous=True, issuer_count=2), CALLS_OF_SEASONS)

    result = fetch(layout, calls=answering)

    assert answering.urls == [CALLS_URLS[0]]  # no other page and no transcript
    assert result["tickers"][0]["calls"] == {
        "status": "unsupported",
        "reason": "EarningsCalls.dev lists 2 issuers for INTC (ambiguous): their calls cannot be told apart",
        "events": None,
        "transcripts": [],
        "pending_calls": [],
    }
    assert not list(layout.raw(TICKER).glob("calls_*"))


NVIDIA_CIK = "0001045810"
NVIDIA_TEN_Q = Row("10-Q", "0001045810-26-000100", date(2026, 8, 27), date(2026, 7, 26), "nvda-20260726.htm")


def test_the_request_limit_stops_the_calls_and_the_run_goes_on_with_edgar_alone(layout):
    served = edgar()
    served.responses[submissions_url(NVIDIA_CIK)] = ok(
        submissions_json(NVIDIA_CIK, "NVIDIA CORP", (NVIDIA_TEN_Q,)).encode(), JSON_TYPE
    )
    nvidia_document = archive_document_url(
        NVIDIA_TEN_Q.accession, NVIDIA_TEN_Q.primary_document, cik=NVIDIA_CIK
    )
    served.responses[nvidia_document] = ok(b"<p>A quarterly report.</p>", HTML_TYPE)
    served.responses[companyfacts_url(NVIDIA_CIK)] = ok(
        b'{"cik": 1045810, "entityName": "NVIDIA CORP", "facts": {}}', JSON_TYPE
    )
    limit = b'{"error": "Monthly request limit reached; it resets on 2026-11-01"}'
    answering = provider(transcripts=CALLS_OF_SEASONS)
    answering.responses[transcript_url(CALL_Q2.id)] = provider_status(429, "Too Many Requests", limit)

    result = fetch(layout, served, "INTC", "NVDA", calls=answering)

    assert answering.urls == list(CALLS_URLS)  # nothing after the refusal
    message = (
        f"GET {CALLS_URLS[3]}: HTTP 429; EarningsCalls.dev's request limit is reached (the key's 3,000 "
        "requests a month or 20 a minute); the provider says: Monthly request limit reached; it resets on "
        "2026-11-01; run fetch again once it resets"
    )
    assert result["stopped"] == {"ticker": TICKER, "reason": message}
    intel, nvidia = result["tickers"]
    assert (intel["calls"]["status"], intel["calls"]["reason"]) == ("stopped", message)
    assert intel["calls"]["transcripts"] == transcript_entries(layout)[:2]  # written before the refusal
    assert not raw_file(layout, "transcript_q2").exists()
    assert nvidia["status"] == "fetched" and nvidia["seasons"][0]["filing"]["status"] == "new"
    assert nvidia["calls"] == {
        "status": "stopped",
        "reason": LIMIT_EARLIER,
        "events": None,
        "transcripts": [],
        "pending_calls": [],
    }
    assert served.urls[-3:] == [submissions_url(NVIDIA_CIK), nvidia_document, companyfacts_url(NVIDIA_CIK)]


def test_a_calls_page_that_does_not_read_aborts_the_run_and_writes_nothing_of_it(layout):
    answering = provider(events_page([call_row(CALL_Q2, symbol="INTL")]), CALLS_OF_SEASONS)

    with pytest.raises(ValueError) as raised:
        fetch(layout, calls=answering)

    assert str(raised.value) == f"GET {CALLS_URLS[0]}: calls list page 1: a call's stock_symbol is not INTC"
    assert raw_tree(layout) == {
        **tree(*DOCUMENTS),
        COMPANYFACTS: companyfacts_json().encode(),
    }  # EDGAR's stay


def test_a_transcript_that_does_not_read_aborts_the_run_and_keeps_what_was_written(layout):
    answering = provider(transcripts=CALLS_OF_SEASONS)
    answering.responses[transcript_url(CALL_Q2.id)] = provider_ok(transcript_body(CALL_Q1))  # another call's

    with pytest.raises(ValueError) as raised:
        fetch(layout, calls=answering)

    assert str(raised.value) == (
        f"GET {CALLS_URLS[3]}: transcript: data.header.event_date_time is not the time the calls list gives"
    )
    assert raw_tree(layout) == {
        **tree(*DOCUMENTS, "transcript_old_q", "transcript_q1"),
        COMPANYFACTS: companyfacts_json().encode(),
        EVENTS: events_page(),
    }


def test_a_transcript_over_its_limit_aborts_the_run_and_keeps_what_was_written(layout):
    answering = provider(transcripts=CALLS_OF_SEASONS)
    answering.responses[transcript_url(CALL_Q2.id)] = provider_ok(b" " * (BODY_LIMIT + 1))

    with pytest.raises(EarningsCallsError) as raised:
        fetch(layout, calls=answering)

    assert str(raised.value) == f"GET {CALLS_URLS[3]}: more than {BODY_LIMIT} bytes"
    assert not raw_file(layout, "transcript_q2").exists()
    assert raw_file(layout, "transcript_q1").read_bytes() == raw_bytes("transcript_q1")


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
        (
            provider_status(503, "Service Unavailable"),
            "HTTP 503 Service Unavailable; EarningsCalls.dev is unavailable: wait and run fetch again",
        ),
    ],
    ids=["401", "404", "503"],
)
def test_a_provider_error_aborts_the_run(layout, response, problem):
    answering = provider(transcripts=CALLS_OF_SEASONS)
    answering.responses[CALLS_URLS[0]] = response

    with pytest.raises(EarningsCallsError) as raised:
        fetch(layout, calls=answering)

    assert str(raised.value) == f"GET {CALLS_URLS[0]}: {problem}"
    assert not list(layout.raw(TICKER).glob("calls_*"))


def test_a_ticker_edgar_does_not_list_asks_the_provider_nothing(layout):
    answering = FakeEarningsCalls()

    result = fetch(layout, None, "ZZZZ", calls=answering)

    assert answering.calls == [] and result["tickers"][0]["calls"] is None
