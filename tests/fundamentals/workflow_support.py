"""A fake EDGAR and EarningsCalls.dev, raw-tree planters and sample reports for the workflow tests.

``edgar`` serves INTC's ticker map, submissions JSON and, for the three periods of
``WINDOW`` (2025-12-01 to ``TODAY``), each period's documents from ``edgar_support``: the
10-K for the fiscal year ended 2025-12-27 (no release), the 10-Q for the quarter ended
2026-03-28 with its 8-K's filing index page and ``EX-99.1``, and the 10-Q for the quarter
ended 2026-06-27 with its 8-K's index page, ``EX-99.1`` and ``EX-99.2``. ``provider``
(``fake_earningscalls``) serves INTC's calls list (``calls_support``: the calls of
2026-07-23 and 2026-04-23 fall in the window's quarters, none in the fiscal year ended
2025-12-27, which the list so shows unavailable) and both calls' transcripts. ``fetch``
writes them to ``raw/`` through the public path; ``FETCH_TIMES`` are the EDGAR client's
clock readings in fetch order and ``CALLS_TIMES`` the provider client's. ``RAW`` names,
written out independently of the code under test, where each lands under ``raw/INTC/`` and
``DOC_IDS`` each document's ``DOC_ID``; ``raw_bytes`` gives the bytes served.
``WIDER_WINDOW`` adds the older quarter ended 2025-09-27 and ``DEFAULT_WINDOW`` (the two
years up to ``TODAY``) also the fiscal year ended 2024-12-28; ``edgar`` serves their
documents only when asked to (``OLD_DOCUMENTS``).

``plant_events`` and ``plant_transcript`` put a calls page or a transcript in
``raw/INTC/calls/`` as ``fetch`` writes them, without a request.

``SAMPLES`` is one report per document that passes ``check``, its quotes copied from the
sentences ``edgar_support`` and ``calls_support`` write (the 10-K's report quotes every field
but ``earnings_guidance`` and ``product_ramp``, which the releases' reports quote, and
``margin_drivers``, which the second 10-Q's report quotes, so the
series fills all eleven; a call's quotes name the executive whose turn they come from);
``research`` fetches, derives the text and writes every sample, so all three periods are
complete.
"""

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from market_state_research.common.layout import DataLayout
from market_state_research.common.times import timestamp_token
from market_state_research.fundamentals.script import workflow
from market_state_research.fundamentals.script.client import COMPANY_TICKERS_URL, EdgarClient
from market_state_research.fundamentals.script.filings import Window
from market_state_research.fundamentals.script.research import FIELDS

from .calls_support import (
    CALL_Q1,
    CALL_Q2,
    CEO,
    CEO_CAPACITY,
    CEO_DEMAND,
    CFO,
    CFO_FINANCING,
    CFO_GUIDANCE,
    CFO_SUPPLY,
    Q1_DEMAND,
    Call,
    events_page,
    transcript_body,
)
from .edgar_support import (
    CIK,
    COMMENTARY_CAPEX,
    COMMENTARY_COLON,
    COMMENTARY_DEMAND,
    COMMENTARY_SUPPLY,
    EIGHT_K_Q1,
    EIGHT_K_Q2,
    OLD_TEN_K,
    OLD_TEN_Q,
    Q1_EXHIBITS,
    Q2_EXHIBITS,
    RECENT,
    RELEASE_CAPEX,
    RELEASE_DEMAND,
    RELEASE_GUIDANCE,
    RELEASE_RAMP,
    RELEASE_SUPPLY,
    RELEASE_TITLES,
    TEN_K,
    TEN_K_CAPEX,
    TEN_K_CUSTOMERS,
    TEN_K_DEMAND,
    TEN_K_FINANCING,
    TEN_K_PRICING,
    TEN_K_SUPPLY,
    TEN_Q_1,
    TEN_Q_2,
    TEN_Q_CAPEX,
    TEN_Q_DEMAND,
    TEN_Q_SPLIT,
    TEN_Q_SUPPLY,
    TICKER,
    IndexRow,
    Row,
    commentary_html,
    exhibit_html,
    filing_index_html,
    submissions_json,
    ten_k_html,
    ten_q_html,
    tickers_json,
)
from .fake_earningscalls import FakeEarningsCalls, calls_client, provider
from .fake_edgar import FakeEdgar, RecordingSleep, ok
from .support import NOW, TODAY, edt

# The windows the tests fetch and plan: WINDOW holds the three default periods.
WINDOW_FROM = date(2025, 12, 1)
WINDOW = Window(WINDOW_FROM, TODAY)
WIDER_WINDOW = Window(date(2025, 9, 1), TODAY)  # adds the quarter ended 2025-09-27 (OLD_TEN_Q)
DEFAULT_WINDOW = Window(date(2024, 10, 8), TODAY)  # two years up to TODAY: adds 2024-12-28 (OLD_TEN_K)
JSON_TYPE = "application/json"
HTML_TYPE = "text/html"

FETCHED_AT = edt(2026, 10, 8, 5, 30, 1, 234567)  # the client reads its clock to the microsecond
# The client's clock readings, in fetch order: the ticker map, the submissions, then per period
# (oldest first) the filing, each release's index page and its exhibits in Seq order.
FETCH_TIMES = (
    edt(2026, 10, 8, 5, 30, 0, 500000),  # company_tickers.json
    FETCHED_AT,  # submissions
    *(edt(2026, 10, 8, 5, 30, second) for second in range(2, 10)),
)
# Where each default document lands under raw/INTC/, and the order fetch requests them.
RAW = {
    "submissions": "edgar/submissions_20261008T053001EDT.json",
    "ten_k": "edgar/10-K_2025-12-27_0000050863-26-000012/intc-20251227.htm",
    "ten_q_1": "edgar/10-Q_2026-03-28_0000050863-26-000041/intc-20260328.htm",
    "index_1": "edgar/8-K_2026-04-23_0000050863-26-000040/0000050863-26-000040-index.htm",
    "exhibit_1": "edgar/8-K_2026-04-23_0000050863-26-000040/q126earningsrelease.htm",
    "ten_q_2": "edgar/10-Q_2026-06-27_0000050863-26-000064/intc-20260627.htm",
    "index_2": "edgar/8-K_2026-07-23_0000050863-26-000062/0000050863-26-000062-index.htm",
    "exhibit_2_1": "edgar/8-K_2026-07-23_0000050863-26-000062/q226earningsrelease.htm",
    "exhibit_2_2": "edgar/8-K_2026-07-23_0000050863-26-000062/q226cfocommentary.htm",
    "events": "calls/events_20261008T053100EDT_1.json",
    "transcript_q1": "calls/transcript_26083.json",
    "transcript_q2": "calls/transcript_248001.json",
}
# The provider client's clock readings, in fetch order: the calls list, then the transcripts of the
# window periods' calls, oldest period first.
CALLS_FETCHED_AT = edt(2026, 10, 8, 5, 31, 0, 250000)
CALLS_TIMES = (CALLS_FETCHED_AT, edt(2026, 10, 8, 5, 31, 3), edt(2026, 10, 8, 5, 31, 6))
# The provider client's clock in a run with --refresh a quarter of an hour later, before NOW.
REFRESH_TIMES = (edt(2026, 10, 8, 5, 45, 0, 500000), edt(2026, 10, 8, 5, 45, 3), edt(2026, 10, 8, 5, 45, 6))
DOC_IDS = {
    "ten_k": "10-K_2025-12-27_0000050863-26-000012_intc-20251227",
    "ten_q_1": "10-Q_2026-03-28_0000050863-26-000041_intc-20260328",
    "exhibit_1": "8-K_2026-04-23_0000050863-26-000040_q126earningsrelease",
    "call_q1": "call_2026-03-28_26083",
    "ten_q_2": "10-Q_2026-06-27_0000050863-26-000064_intc-20260627",
    "exhibit_2_1": "8-K_2026-07-23_0000050863-26-000062_q226earningsrelease",
    "exhibit_2_2": "8-K_2026-07-23_0000050863-26-000062_q226cfocommentary",
    "call_q2": "call_2026-06-27_248001",
}
# Each period's documents in the order a period lists them: filing, exhibits, calls.
PERIOD_DOCUMENTS = {
    "2025-12-27": ("ten_k",),
    "2026-03-28": ("ten_q_1", "exhibit_1", "call_q1"),
    "2026-06-27": ("ten_q_2", "exhibit_2_1", "exhibit_2_2", "call_q2"),
}
PERIODS = tuple(PERIOD_DOCUMENTS)
AS_OF = TEN_Q_2.filed  # the filing date of the newest filing or exhibit of the three periods

# A third 10-Q and its release dated the day before: Rule B attaches the release to the quarter
# ended 2026-09-26 once the 10-Q is listed, and leaves it pending until then.
TEN_Q_3 = Row("10-Q", "0000050863-26-000090", date(2026, 10, 7), date(2026, 9, 26), "intc-20260926.htm")
EIGHT_K_Q3 = Row(
    "8-K", "0000050863-26-000089", date(2026, 10, 6), date(2026, 10, 6), "intc-20261006.htm", "2.02,9.01"
)
Q3_EXHIBITS = (IndexRow("2", "EX-99.1", "q326earningsrelease.htm", "EX-99.1", "401200"),)
LATER_RECENT = (TEN_Q_3, EIGHT_K_Q3, *RECENT)
PENDING_RECENT = (EIGHT_K_Q3, *RECENT)
LATER_TIMES = tuple(edt(2026, 10, 8, 5, 40, second) for second in range(5))
# A company EDGAR lists whose recent filings hold no 10-K or 10-Q (a foreign private issuer, say).
APPLE_CIK = "0000320193"
NO_PERIODIC_FILINGS = (
    Row("6-K", "0000320193-26-000071", date(2026, 7, 31), None, "aapl-20260731.htm"),
    Row("20-F", "0000320193-26-000012", date(2026, 1, 30), date(2025, 12, 27), "aapl-20251227.htm"),
)

FILINGS = {"ten_k": TEN_K, "ten_q_1": TEN_Q_1, "ten_q_2": TEN_Q_2}
EXHIBITS: dict[str, tuple[Row, IndexRow]] = {
    "exhibit_1": (EIGHT_K_Q1, Q1_EXHIBITS[0]),
    "exhibit_2_1": (EIGHT_K_Q2, Q2_EXHIBITS[0]),
    "exhibit_2_2": (EIGHT_K_Q2, Q2_EXHIBITS[1]),
}
INDEXES = {"index_1": (EIGHT_K_Q1, Q1_EXHIBITS), "index_2": (EIGHT_K_Q2, Q2_EXHIBITS)}
DEFAULT_RELEASES: tuple[tuple[Row, Sequence[IndexRow]], ...] = tuple(INDEXES.values())
OLD_DOCUMENTS = (OLD_TEN_K, OLD_TEN_Q)  # the filings of the two older periods, never fetched by WINDOW
_QUARTERS = {EIGHT_K_Q1.accession: TEN_Q_1, EIGHT_K_Q2.accession: TEN_Q_2, EIGHT_K_Q3.accession: TEN_Q_3}


# --------------------------------------------------------------------------- EDGAR


def archive_document_url(accession: str, document: str, cik: str = CIK) -> str:
    """A document in the archive folder of the filing ``accession``."""
    return f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession.replace('-', '')}/{document}"


def submissions_url(cik: str = CIK) -> str:
    return f"https://data.sec.gov/submissions/CIK{cik}.json"


def filing_url(row: Row) -> str:
    return archive_document_url(row.accession, row.primary_document)


def index_url(row: Row) -> str:
    return archive_document_url(row.accession, f"{row.accession}-index.htm")


def filing_document(row: Row) -> str:
    """The synthetic primary document of a 10-K or 10-Q row."""
    assert row.period is not None
    return ten_k_html(period=row.period) if row.form == "10-K" else ten_q_html(period=row.period)


def exhibit_document(row: Row, index_row: IndexRow) -> str:
    """The synthetic exhibit ``index_row`` names on the index page of the release ``row``."""
    quarter = _QUARTERS[row.accession]
    assert quarter.period is not None
    if index_row.document.endswith("cfocommentary.htm"):
        return commentary_html(quarter.period)
    title = RELEASE_TITLES.get(index_row.document, f"Intel Reports Results ({index_row.document})")
    return exhibit_html(quarter.period, title=title)


def raw_bytes(role: str) -> bytes:
    """The bytes EDGAR or EarningsCalls.dev serves for each default role: what ``raw/`` must hold,
    byte for byte."""
    if role == "submissions":
        return submissions_json().encode()
    if role == "events":
        return events_page()
    if role in TRANSCRIPTS:
        return transcript_body(TRANSCRIPTS[role])
    if role in FILINGS:
        return filing_document(FILINGS[role]).encode()
    if role in INDEXES:
        return filing_index_html(*INDEXES[role]).encode()
    return exhibit_document(*EXHIBITS[role]).encode()


def edgar(
    rows: Sequence[Row] = RECENT,
    documents: Sequence[Row] = tuple(FILINGS.values()),
    releases: Sequence[tuple[Row, Sequence[IndexRow]]] = DEFAULT_RELEASES,
) -> FakeEdgar:
    """EDGAR serving the ticker map, INTC's submissions listing ``rows``, the primary document of
    each of ``documents``, and for each release its filing index page and its exhibits."""
    responses = {
        COMPANY_TICKERS_URL: ok(tickers_json().encode(), JSON_TYPE),
        submissions_url(): ok(submissions_json(rows=rows).encode(), JSON_TYPE),
        **{filing_url(row): ok(filing_document(row).encode(), HTML_TYPE) for row in documents},
    }
    for row, exhibits in releases:
        responses[index_url(row)] = ok(filing_index_html(row, exhibits).encode(), HTML_TYPE)
        for index_row in exhibits:
            url = archive_document_url(row.accession, index_row.document)
            responses[url] = ok(exhibit_document(row, index_row).encode(), HTML_TYPE)
    return FakeEdgar(responses)


# Every URL a first fetch of WINDOW requests, in order.
FETCH_URLS = (
    COMPANY_TICKERS_URL,
    submissions_url(),
    filing_url(TEN_K),
    filing_url(TEN_Q_1),
    index_url(EIGHT_K_Q1),
    archive_document_url(EIGHT_K_Q1.accession, Q1_EXHIBITS[0].document),
    filing_url(TEN_Q_2),
    index_url(EIGHT_K_Q2),
    *(archive_document_url(EIGHT_K_Q2.accession, row.document) for row in Q2_EXHIBITS),
)
assert len(FETCH_URLS) == len(FETCH_TIMES)


@dataclass
class FetchClock:
    """The client's clock: each reading is the next of ``times``, then one second after the last."""

    times: Sequence[datetime] = FETCH_TIMES
    readings: int = 0

    def __call__(self) -> datetime:
        index = self.readings
        self.readings += 1
        if index < len(self.times):
            return self.times[index]
        return self.times[-1] + timedelta(seconds=index - len(self.times) + 1)


def client(
    fake: FakeEdgar, sleep: RecordingSleep | None = None, times: Sequence[datetime] = FETCH_TIMES
) -> EdgarClient:
    """An ``EdgarClient`` over ``fake`` whose clock reads ``times``; ``sleep`` records the pacing."""
    return EdgarClient(
        "margin_edge tests@example.com",
        fetch=fake,
        sleep=sleep if sleep is not None else RecordingSleep(),
        clock=FetchClock(times),
    )


def fetch(
    layout: DataLayout,
    fake: FakeEdgar | None = None,
    *tickers: str,
    sleep: RecordingSleep | None = None,
    times: Sequence[datetime] = FETCH_TIMES,
    window: Window = WINDOW,
    calls: FakeEarningsCalls | None = None,
    calls_sleep: RecordingSleep | None = None,
    calls_times: Sequence[datetime] = CALLS_TIMES,
    now: datetime = NOW,
    refresh: bool = False,
) -> dict:
    """Fetch ``tickers`` (INTC by default) over ``window`` from ``fake`` (``edgar()`` by default)
    and ``calls`` (``provider()`` by default), with ``refresh`` as ``fetch --refresh``."""
    served = edgar() if fake is None else fake
    answering = provider() if calls is None else calls
    return workflow.fetch(
        layout,
        list(tickers) or [TICKER],
        client(served, sleep, times),
        calls_client(answering, calls_sleep, FetchClock(calls_times)),
        window,
        now,
        refresh=refresh,
    )


def raw_file(layout: DataLayout, role: str) -> Path:
    return layout.raw(TICKER) / RAW[role]


# --------------------------------------------------------------------------- calls

# The transcript files of the default capture's window calls, by role.
TRANSCRIPTS = {"transcript_q1": CALL_Q1, "transcript_q2": CALL_Q2}


def place(path: Path, content: bytes | str) -> Path:
    """Write a file the way a person or another tool might (not through ``write_file``)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content.encode("utf-8") if isinstance(content, str) else content)
    return path


def calls_directory(layout: DataLayout) -> Path:
    return layout.raw(TICKER) / "calls"


def plant_events(
    layout: DataLayout, page: bytes | None = None, *, at: datetime = CALLS_FETCHED_AT, number: int = 1
) -> Path:
    """Page ``number`` of a calls capture read at ``at`` (the default capture's page by default),
    where ``fetch`` writes it: ``events_{token}_{PAGE}.json``."""
    name = f"events_{timestamp_token(at)}_{number}.json"
    return place(calls_directory(layout) / name, events_page() if page is None else page)


def plant_transcript(layout: DataLayout, call: Call = CALL_Q2, body: bytes | None = None) -> Path:
    """The transcript of ``call`` (its default body unless ``body``), where ``fetch`` writes it."""
    data = transcript_body(call) if body is None else body
    return place(calls_directory(layout) / f"transcript_{call.id}.json", data)


# --------------------------------------------------------------------------- reports

# Each field's quotes: a quote is its text, or (speaker, text).
Quotes = Sequence[str | tuple[str, str]]


def report_text(doc_id: str, **fields: Quotes) -> str:
    """A per-document report in the grammar: ``fields`` gives quotes per field of ``research.FIELDS``
    (any other keyword is refused), any other field reads ``None found.``; each quote's text is
    wrapped at its spaces into ``>`` lines of at most eight words."""
    unknown = sorted(set(fields) - set(FIELDS))
    if unknown:
        raise TypeError(f"report_text: not a field of research.FIELDS: {', '.join(unknown)}")
    lines = [f"# {doc_id}", ""]
    for name in FIELDS:
        lines.extend([f"## {name}", ""])
        quotes = fields.get(name, ())
        if not quotes:
            lines.extend(["None found.", ""])
        for quote in quotes:
            speaker, text = quote if isinstance(quote, tuple) else (None, quote)
            if speaker is not None:
                lines.append(f"Speaker: {speaker}")
            words = text.split(" ")
            lines.extend("> " + " ".join(words[start : start + 8]) for start in range(0, len(words), 8))
            lines.append("")
    return "\n".join(lines)


# A statement is quoted in every field whose definition it fits: the 10-K's partner capital for new
# fabrication facilities (capacity expansion, financing), the 10-Q's slowed construction in Ohio
# (capex, capacity expansion) and the commentary's bookings (demand, backlog).
_FILING_QUOTES: dict[str, dict[str, Quotes]] = {
    "ten_k": {
        "upstream_shortage": [TEN_K_SUPPLY[1]],
        "capacity_shortfall": [TEN_K_DEMAND[0]],
        "capex_plans": [TEN_K_CAPEX[0]],
        "capacity_expansion": [TEN_K_CAPEX[1]],
        "pricing": [TEN_K_PRICING[0]],
        "backlog_contracts": [TEN_K_DEMAND[2]],
        "financing_methods": [TEN_K_CAPEX[1], TEN_K_FINANCING[0]],
        "customer_concentration": [TEN_K_CUSTOMERS[0]],
    },
    "ten_q_1": {
        "upstream_shortage": [TEN_Q_SUPPLY[0]],
        "capex_plans": [TEN_Q_CAPEX[0]],
        "capacity_expansion": [TEN_Q_CAPEX[0]],
    },
    "ten_q_2": {
        "upstream_shortage": [TEN_Q_SUPPLY[0]],
        "capacity_shortfall": [TEN_Q_DEMAND[0], TEN_Q_DEMAND[1]],
        "capex_plans": [TEN_Q_CAPEX[0]],
        "capacity_expansion": [TEN_Q_CAPEX[0]],
        "margin_drivers": [" ".join(TEN_Q_SPLIT)],  # the sentence split across two blocks, whole
    },
}
_RELEASE_QUOTES: dict[str, Quotes] = {
    "upstream_shortage": [RELEASE_SUPPLY[0]],
    "capacity_shortfall": [RELEASE_DEMAND[0]],
    "capex_plans": [RELEASE_CAPEX[0]],
    "earnings_guidance": [RELEASE_GUIDANCE[0], RELEASE_GUIDANCE[1]],
    "product_ramp": [RELEASE_RAMP[0]],
}
QUOTES: dict[str, dict[str, Quotes]] = {
    **_FILING_QUOTES,
    "exhibit_1": _RELEASE_QUOTES,
    "exhibit_2_1": _RELEASE_QUOTES,
    "exhibit_2_2": {
        "upstream_shortage": [COMMENTARY_SUPPLY[0]],
        "capacity_shortfall": [COMMENTARY_DEMAND[0]],
        "capex_plans": [COMMENTARY_CAPEX[0]],
        "capacity_expansion": [COMMENTARY_COLON],
        "backlog_contracts": [COMMENTARY_DEMAND[0]],
    },
    "call_q1": {"capacity_shortfall": [(CEO[0], Q1_DEMAND)]},
    "call_q2": {
        "upstream_shortage": [(CFO[0], CFO_SUPPLY)],
        "capacity_shortfall": [(CEO[0], CEO_DEMAND)],
        "capacity_expansion": [(CEO[0], CEO_CAPACITY)],
        "earnings_guidance": [(CFO[0], CFO_GUIDANCE)],
        "financing_methods": [(CFO[0], CFO_FINANCING)],
    },
}
SAMPLES = {role: report_text(DOC_IDS[role], **quotes) for role, quotes in QUOTES.items()}


def report_file(layout: DataLayout, role: str) -> Path:
    return layout.reports(TICKER) / f"{DOC_IDS[role]}.md"


def write_report(layout: DataLayout, role: str, text: str | None = None) -> Path:
    """Write the agent's report of the document ``role`` (its sample by default)."""
    return place(report_file(layout, role), SAMPLES[role] if text is None else text)


def research(layout: DataLayout, roles: Sequence[str] = tuple(SAMPLES), now: datetime = NOW) -> None:
    """Fetch and derive every text, then write the sample report of each of ``roles``."""
    fetch(layout)
    workflow.text(layout, TICKER, now)
    for role in roles:
        write_report(layout, role)


# --------------------------------------------------------------------------- files


def snapshot(root: Path) -> dict[str, tuple[int, int, bytes | None]]:
    """Every path below ``root`` with its mode, mtime and bytes: detects any write, move or delete."""
    if not root.exists():
        return {}
    state = {}
    for path in sorted(root.rglob("*")):
        info = path.lstat()
        state[str(path.relative_to(root))] = (
            info.st_mode,
            info.st_mtime_ns,
            path.read_bytes() if path.is_file() else None,
        )
    return state


def write_watchlist(directory: Path, stock: Sequence[str] = (TICKER,)) -> Path:
    """A watchlist in ``directory`` (a temporary one); the domain's own is never read."""
    path = directory / "watchlist.json"
    path.write_text(json.dumps({"stock": list(stock)}), encoding="utf-8")
    return path
