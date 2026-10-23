"""A fake EDGAR and EarningsCalls.dev, raw-tree planters and readings for the workflow tests.

``edgar`` serves INTC's ticker map, submissions JSON (``edgar_support.RECENT``), company
facts (``companyfacts_json``) and every document of the five seasons ``fetch`` requests for
``WINDOW`` (2025-12-01 to ``TODAY``): its three seasons, the fiscal year ended 2025-12-27 and
the quarters ended 2026-03-28 and 2026-06-27, and the two listed before them, the quarter
ended 2025-09-27 and the fiscal year ended 2024-12-28 (``items.BASELINE_SEASONS`` reaches
four back). The fiscal year's season holds the 8-K of 2026-02-09 (Item 5.02, no exhibit)
and the proxy statement filed 2026-03-27; each quarter its earnings release (index page,
primary document and EX-99 exhibits). The Form 4 of 2026-07-30 is pending. ``provider``
(``fake_earningscalls``) serves INTC's calls list and the transcripts of the calls Rule B
places in those seasons: 2025-10-23, 2026-04-23 and 2026-07-23; none is listed for either
fiscal year, which the list so shows unavailable.

``RAW`` names, written out independently of the code under test, where each document lands
under ``raw/INTC/`` and ``DOC_IDS`` each quoted document's ``DOC_ID``. ``readings_text`` writes
a readings file of a season in the grammar, every bot item at ``none`` but the statuses its
season requires, each naming one baseline document (``BASELINES``); ``research`` fetches,
derives and writes the window seasons' readings, so ``plan`` then says ``render``.
"""

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from market_state_research.common.layout import DataLayout
from market_state_research.fundamentals.script import workflow
from market_state_research.fundamentals.script.client import COMPANY_TICKERS_URL, EdgarClient
from market_state_research.fundamentals.script.filings import Window
from market_state_research.fundamentals.script.items import BOT_ITEMS, Item

from .calls_support import CALL_OLD_Q, CALL_Q1, CALL_Q2, CEO, CEO_DEMAND, Call, events_page, transcript_body
from .edgar_support import (
    CIK,
    EIGHT_K_OTHER,
    EIGHT_K_Q1,
    EIGHT_K_Q2,
    ENTITY_NAME,
    OLD_TEN_K,
    OLD_TEN_Q,
    PROXY,
    Q1_EXHIBITS,
    Q2_EXHIBITS,
    RECENT,
    RELEASE_TITLES,
    TEN_K,
    TEN_Q_1,
    TEN_Q_2,
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

WINDOW = Window(date(2025, 12, 1), TODAY)  # the fiscal year ended 2025-12-27 and the next two quarters
DEFAULT_WINDOW = Window(date(2024, 10, 8), TODAY)  # the two years up to TODAY: every listed season
JSON_TYPE = "application/json"
HTML_TYPE = "text/html"
SEASONS = (OLD_TEN_K, OLD_TEN_Q, TEN_K, TEN_Q_1, TEN_Q_2)  # the listed seasons' filings, oldest first
WINDOW_SEASONS = (TEN_K, TEN_Q_1, TEN_Q_2)
FETCHED_AT = edt(2026, 10, 8, 5, 30, 1)
COMPANYFACTS_AT = edt(2026, 10, 8, 5, 30, 30)
CALLS_FETCHED_AT = edt(2026, 10, 8, 5, 31, 0)

DOC_IDS = {
    "old_ten_k": "10-K_2024-12-28_0000050863-25-000009_intc-20241228",
    "old_ten_q": "10-Q_2025-09-27_0000050863-25-000201_intc-20250927",
    "call_old_q": "call_2025-09-27_35174",
    "ten_k": "10-K_2025-12-27_0000050863-26-000012_intc-20251227",
    "eight_k_other": "8-K_2026-02-09_0000050863-26-000020_intc-20260209",
    "proxy": "DEF14A_2026-03-27_0001193125-26-112233_d123456ddef14a",
    "ten_q_1": "10-Q_2026-03-28_0000050863-26-000041_intc-20260328",
    "eight_k_1": "8-K_2026-04-23_0000050863-26-000040_intc-20260423",
    "exhibit_1": "8-K_2026-04-23_0000050863-26-000040_q126earningsrelease",
    "call_q1": "call_2026-03-28_26083",
    "ten_q_2": "10-Q_2026-06-27_0000050863-26-000064_intc-20260627",
    "eight_k_2": "8-K_2026-07-23_0000050863-26-000062_intc-20260723",
    "exhibit_2_1": "8-K_2026-07-23_0000050863-26-000062_q226earningsrelease",
    "exhibit_2_2": "8-K_2026-07-23_0000050863-26-000062_q226cfocommentary",
    "call_q2": "call_2026-06-27_248001",
}
# Where each file lands under raw/INTC/.
RAW = {
    "old_ten_k": "2024-12-28/10-K_2024-12-28_0000050863-25-000009/intc-20241228.htm",
    "old_ten_q": "2025-09-27/10-Q_2025-09-27_0000050863-25-000201/intc-20250927.htm",
    "transcript_old_q": "2025-09-27/transcript_35174.json",
    "ten_k": "2025-12-27/10-K_2025-12-27_0000050863-26-000012/intc-20251227.htm",
    "index_other": "2025-12-27/8-K_2026-02-09_0000050863-26-000020/0000050863-26-000020-index.htm",
    "eight_k_other": "2025-12-27/8-K_2026-02-09_0000050863-26-000020/intc-20260209.htm",
    "proxy": "2025-12-27/DEF14A_2026-03-27_0001193125-26-112233/d123456ddef14a.htm",
    "ten_q_1": "2026-03-28/10-Q_2026-03-28_0000050863-26-000041/intc-20260328.htm",
    "index_1": "2026-03-28/8-K_2026-04-23_0000050863-26-000040/0000050863-26-000040-index.htm",
    "eight_k_1": "2026-03-28/8-K_2026-04-23_0000050863-26-000040/intc-20260423.htm",
    "exhibit_1": "2026-03-28/8-K_2026-04-23_0000050863-26-000040/q126earningsrelease.htm",
    "transcript_q1": "2026-03-28/transcript_26083.json",
    "ten_q_2": "2026-06-27/10-Q_2026-06-27_0000050863-26-000064/intc-20260627.htm",
    "index_2": "2026-06-27/8-K_2026-07-23_0000050863-26-000062/0000050863-26-000062-index.htm",
    "eight_k_2": "2026-06-27/8-K_2026-07-23_0000050863-26-000062/intc-20260723.htm",
    "exhibit_2_1": "2026-06-27/8-K_2026-07-23_0000050863-26-000062/q226earningsrelease.htm",
    "exhibit_2_2": "2026-06-27/8-K_2026-07-23_0000050863-26-000062/q226cfocommentary.htm",
    "transcript_q2": "2026-06-27/transcript_248001.json",
}
RELEASES: dict[str, tuple[Row, Sequence[IndexRow]]] = {
    "index_other": (EIGHT_K_OTHER, ()),
    "index_1": (EIGHT_K_Q1, Q1_EXHIBITS),
    "index_2": (EIGHT_K_Q2, Q2_EXHIBITS),
}
CALLS_OF_SEASONS = (CALL_OLD_Q, CALL_Q1, CALL_Q2)


# --------------------------------------------------------------------------- documents


def archive_document_url(accession: str, document: str, cik: str = CIK) -> str:
    """A document in the archive folder of the filing ``accession``."""
    return f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession.replace('-', '')}/{document}"


def submissions_url(cik: str = CIK) -> str:
    return f"https://data.sec.gov/submissions/CIK{cik}.json"


def companyfacts_url(cik: str = CIK) -> str:
    return f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"


def filing_url(row: Row) -> str:
    return archive_document_url(row.accession, row.primary_document)


def index_url(row: Row) -> str:
    return archive_document_url(row.accession, f"{row.accession}-index.htm")


def filing_document(row: Row) -> str:
    """The synthetic primary document of a 10-K or 10-Q row."""
    assert row.period is not None
    return ten_k_html(period=row.period) if row.form == "10-K" else ten_q_html(period=row.period)


def eight_k_html(row: Row) -> str:
    """The synthetic primary document of an 8-K: its cover and one paragraph per item."""
    items = "".join(
        f"<p>Item {item}. The Company reports under Item {item} of Form 8-K.</p>"
        for item in row.items.split(",")
        if item
    )
    return (
        "<html><head><title>8-K</title></head><body>"
        f"<p>UNITED STATES SECURITIES AND EXCHANGE COMMISSION</p><p>FORM 8-K</p>{items}"
        "<p>Pursuant to the requirements of the Securities Exchange Act of 1934, the registrant has duly "
        "caused this report to be signed.</p></body></html>"
    )


PROXY_SENTENCE = "The Board recommends that stockholders vote for each of the director nominees."


def proxy_html() -> str:
    """The synthetic proxy statement."""
    return (
        "<html><head><title>DEF 14A</title></head><body><p>Notice of 2026 Annual Meeting of Stockholders</p>"
        f"<p>{PROXY_SENTENCE}</p><p>No director or executive officer has pledged shares of the Company.</p>"
        "</body></html>"
    )


def exhibit_document(row: Row, index_row: IndexRow) -> str:
    quarter = TEN_Q_1 if row is EIGHT_K_Q1 else TEN_Q_2
    assert quarter.period is not None
    if index_row.document.endswith("cfocommentary.htm"):
        return commentary_html(quarter.period)
    title = RELEASE_TITLES.get(index_row.document, f"Intel Reports Results ({index_row.document})")
    return exhibit_html(quarter.period, title=title)


@dataclass(frozen=True)
class Quarter:
    """One season's figures for the company facts: the quarter's flows and the period-end balances."""

    revenue: int
    cost: int
    operating: int
    income: int
    cash_flow: int
    receivables: int
    inventory: int
    payables: int
    debt: int
    cash: int
    shares: int
    goodwill: int
    equity: int
    assets: int


FIGURES: Mapping[date, Quarter] = {
    date(2025, 9, 27): Quarter(
        13_000, 8_000, 500, 400, 600, 3_000, 11_000, 10_000, 46_000, 11_000, 4_500, 23_000, 106_000, 204_000
    ),
    date(2025, 12, 27): Quarter(
        13_500, 8_500, 600, 500, 700, 3_800, 11_600, 9_800, 46_500, 14_000, 4_600, 23_000, 114_000, 211_000
    ),
    date(2026, 3, 28): Quarter(
        13_600, 8_200, 700, 550, 1_100, 4_000, 12_400, 7_100, 45_000, 17_000, 5_080, 20_400, 111_000, 205_000
    ),
    date(2026, 6, 27): Quarter(
        16_100, 9_600, 1_800, 900, 7_000, 4_000, 12_500, 8_700, 50_500, 12_800, 5_100, 20_400, 87_500, 202_000
    ),
}
_FLOWS = {
    "RevenueFromContractWithCustomerExcludingAssessedTax": "revenue",
    "CostOfGoodsAndServicesSold": "cost",
    "OperatingIncomeLoss": "operating",
    "NetIncomeLoss": "income",
}
_BALANCES = {
    "AccountsReceivableNetCurrent": "receivables",
    "InventoryNet": "inventory",
    "AccountsPayableCurrent": "payables",
    "LongTermDebtNoncurrent": "debt",
    "CashAndCashEquivalentsAtCarryingValue": "cash",
    "Goodwill": "goodwill",
    "StockholdersEquity": "equity",
    "Assets": "assets",
}
MILLION = 1_000_000


def _entry(row: Row, start: date | None, end: date, value: int) -> dict[str, object]:
    entry: dict[str, object] = {
        "end": end.isoformat(),
        "val": value,
        "accn": row.accession,
        "fy": 2026,
        "fp": "Q",
        "form": row.form,
        "filed": row.filed.isoformat(),
    }
    if start is not None:
        entry = {"start": start.isoformat(), **entry}
    return entry


def companyfacts_document() -> dict[str, object]:
    """INTC's company facts in EDGAR's layout, the figures of ``FIGURES`` in millions: each 10-Q
    reports its quarter (operating cash flow as the year to date only, the second quarter's from
    the first's), the 10-K its year, from which the third quarter's nine months come off."""
    concepts: dict[str, dict[str, list[dict[str, object]]]] = {}

    def add(tag: str, unit: str, entry: dict[str, object]) -> None:
        concepts.setdefault(tag, {}).setdefault(unit, []).append(entry)

    rows = {row.period: row for row in SEASONS}
    for period, quarter in FIGURES.items():
        row = rows[period]
        start = period - timedelta(days=90)
        for tag, name in _FLOWS.items():
            value = getattr(quarter, name) * MILLION
            if row.form == "10-K":
                nine = getattr(FIGURES[date(2025, 9, 27)], name) * MILLION * 3
                add(tag, "USD", _entry(row, date(2024, 12, 29), period, value + nine))
                add(tag, "USD", _entry(OLD_TEN_Q, date(2024, 12, 29), date(2025, 9, 27), nine))
            else:
                add(tag, "USD", _entry(row, start, period, value))
        for tag, name in _BALANCES.items():
            add(tag, "USD", _entry(row, None, period, getattr(quarter, name) * MILLION))
        if row.form == "10-Q":
            add(
                "WeightedAverageNumberOfDilutedSharesOutstanding",
                "shares",
                _entry(row, start, period, quarter.shares * MILLION),
            )
        cash_flow = quarter.cash_flow * MILLION
        if period == date(2026, 6, 27):
            first = FIGURES[date(2026, 3, 28)].cash_flow * MILLION
            add(
                "NetCashProvidedByUsedInOperatingActivities",
                "USD",
                _entry(row, date(2025, 12, 28), period, first + cash_flow),
            )
        elif row.form == "10-Q":
            add("NetCashProvidedByUsedInOperatingActivities", "USD", _entry(row, start, period, cash_flow))
    return {
        "cik": int(CIK),
        "entityName": ENTITY_NAME,
        "facts": {
            "dei": {"EntityCommonStockSharesOutstanding": {"units": {"shares": []}}},
            "us-gaap": {
                tag: {"label": tag, "description": "", "units": units} for tag, units in concepts.items()
            },
        },
    }


def companyfacts_json() -> str:
    return json.dumps(companyfacts_document(), separators=(",", ":"))


def raw_bytes(role: str) -> bytes:
    """The bytes EDGAR or EarningsCalls.dev serves for each role of ``RAW``."""
    filings = {
        "old_ten_k": OLD_TEN_K,
        "old_ten_q": OLD_TEN_Q,
        "ten_k": TEN_K,
        "ten_q_1": TEN_Q_1,
        "ten_q_2": TEN_Q_2,
    }
    if role in filings:
        return filing_document(filings[role]).encode()
    if role in RELEASES:
        return filing_index_html(*RELEASES[role]).encode()
    if role in ("eight_k_other", "eight_k_1", "eight_k_2"):
        row = {"eight_k_other": EIGHT_K_OTHER, "eight_k_1": EIGHT_K_Q1, "eight_k_2": EIGHT_K_Q2}[role]
        return eight_k_html(row).encode()
    if role == "proxy":
        return proxy_html().encode()
    if role == "exhibit_1":
        return exhibit_document(EIGHT_K_Q1, Q1_EXHIBITS[0]).encode()
    if role in ("exhibit_2_1", "exhibit_2_2"):
        return exhibit_document(EIGHT_K_Q2, Q2_EXHIBITS[0 if role == "exhibit_2_1" else 1]).encode()
    calls = {"transcript_old_q": CALL_OLD_Q, "transcript_q1": CALL_Q1, "transcript_q2": CALL_Q2}
    return transcript_body(calls[role])


def edgar(rows: Sequence[Row] = RECENT, **replaced: bytes) -> FakeEdgar:
    """EDGAR serving the ticker map, INTC's submissions listing ``rows``, its company facts and
    every document of ``RAW``'s seasons; ``replaced`` serves other bytes at a role's URL."""
    responses = {
        COMPANY_TICKERS_URL: ok(tickers_json().encode(), JSON_TYPE),
        submissions_url(): ok(submissions_json(rows=rows).encode(), JSON_TYPE),
        companyfacts_url(): ok(companyfacts_json().encode(), JSON_TYPE),
        **{filing_url(row): ok(filing_document(row).encode(), HTML_TYPE) for row in SEASONS},
        filing_url(PROXY): ok(proxy_html().encode(), HTML_TYPE),
    }
    for row, exhibits in RELEASES.values():
        responses[index_url(row)] = ok(filing_index_html(row, exhibits).encode(), HTML_TYPE)
        responses[filing_url(row)] = ok(eight_k_html(row).encode(), HTML_TYPE)
        for index_row in exhibits:
            url = archive_document_url(row.accession, index_row.document)
            responses[url] = ok(exhibit_document(row, index_row).encode(), HTML_TYPE)
    for role, data in replaced.items():
        responses[role_url(role)] = ok(data, HTML_TYPE)
    return FakeEdgar(responses)


def role_url(role: str) -> str:
    """The URL a role of ``RAW`` is requested at."""
    if role == "companyfacts":
        return companyfacts_url()
    path = RAW[role]
    folder = path.split("/")[1]
    accession = folder.rsplit("_", 1)[1]
    return archive_document_url(accession, path.rsplit("/", 1)[1])


# Every EDGAR URL a first fetch of WINDOW requests, in order.
FETCH_URLS = (
    COMPANY_TICKERS_URL,
    submissions_url(),
    filing_url(OLD_TEN_K),
    filing_url(OLD_TEN_Q),
    filing_url(TEN_K),
    index_url(EIGHT_K_OTHER),
    filing_url(EIGHT_K_OTHER),
    filing_url(PROXY),
    filing_url(TEN_Q_1),
    index_url(EIGHT_K_Q1),
    filing_url(EIGHT_K_Q1),
    archive_document_url(EIGHT_K_Q1.accession, Q1_EXHIBITS[0].document),
    filing_url(TEN_Q_2),
    index_url(EIGHT_K_Q2),
    filing_url(EIGHT_K_Q2),
    *(archive_document_url(EIGHT_K_Q2.accession, row.document) for row in Q2_EXHIBITS),
    companyfacts_url(),
)


@dataclass
class FetchClock:
    """The client's clock: ``start``, then one second later at each reading."""

    start: datetime = FETCHED_AT
    readings: int = 0

    def __call__(self) -> datetime:
        self.readings += 1
        return self.start + timedelta(seconds=self.readings - 1)


def client(fake: FakeEdgar, sleep: RecordingSleep | None = None, start: datetime = FETCHED_AT) -> EdgarClient:
    return EdgarClient(
        "margin_edge tests@example.com",
        fetch=fake,
        sleep=sleep if sleep is not None else RecordingSleep(),
        clock=FetchClock(start),
    )


def fetch(
    layout: DataLayout,
    fake: FakeEdgar | None = None,
    *tickers: str,
    window: Window = WINDOW,
    calls: FakeEarningsCalls | None = None,
    now: datetime = NOW,
    start: datetime = FETCHED_AT,
    calls_start: datetime = CALLS_FETCHED_AT,
    refresh: bool = False,
) -> dict:
    """Fetch ``tickers`` (INTC by default) over ``window`` from ``fake`` (``edgar()`` by default) and
    ``calls`` (the provider of the seasons' calls by default)."""
    served = edgar() if fake is None else fake
    answering = provider(transcripts=CALLS_OF_SEASONS) if calls is None else calls
    return workflow.fetch(
        layout,
        list(tickers) or [TICKER],
        client(served, start=start),
        calls_client(answering, None, FetchClock(calls_start)),
        window,
        now,
        refresh=refresh,
    )


def raw_file(layout: DataLayout, role: str) -> Path:
    return layout.raw(TICKER) / RAW[role]


def place(path: Path, content: bytes | str) -> Path:
    """Write a file the way a person or another tool might (not through ``write_file``)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content.encode("utf-8") if isinstance(content, str) else content)
    return path


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


# --------------------------------------------------------------------------- readings


# Per window season: its form, whether it holds a proxy statement, whether its call has a
# transcript, and the baseline document each baseline kind names (None: no baseline in raw/).
@dataclass(frozen=True)
class SeasonFacts:
    period: date
    form: str
    proxy: bool
    transcript: bool
    baselines: Mapping[str, str | None]


SEASON_FACTS = {
    date(2025, 12, 27): SeasonFacts(
        date(2025, 12, 27),
        "10-K",
        True,
        False,
        {
            "previous quarter": DOC_IDS["old_ten_q"],
            "previous guidance": DOC_IDS["old_ten_q"],
            "same quarter last year": DOC_IDS["old_ten_k"],
            "previous quarter and same quarter last year": DOC_IDS["old_ten_q"],
            "previous filings": DOC_IDS["old_ten_k"],
            "previous 10-K": DOC_IDS["old_ten_k"],
            "previous proxy": None,
            "previous eight seasons": DOC_IDS["call_old_q"],
        },
    ),
    date(2026, 3, 28): SeasonFacts(
        date(2026, 3, 28),
        "10-Q",
        False,
        True,
        {
            "previous quarter": DOC_IDS["ten_k"],
            "previous guidance": DOC_IDS["eight_k_other"],
            "same quarter last year": None,
            "previous quarter and same quarter last year": DOC_IDS["ten_k"],
            "previous filings": DOC_IDS["ten_k"],
            "previous 10-K": DOC_IDS["ten_k"],
            "previous proxy": DOC_IDS["proxy"],
            "previous eight seasons": DOC_IDS["old_ten_q"],
        },
    ),
    date(2026, 6, 27): SeasonFacts(
        date(2026, 6, 27),
        "10-Q",
        False,
        True,
        {
            "previous quarter": DOC_IDS["ten_q_1"],
            "previous guidance": DOC_IDS["exhibit_1"],
            "same quarter last year": None,
            "previous quarter and same quarter last year": DOC_IDS["ten_q_1"],
            "previous filings": DOC_IDS["ten_k"],
            "previous 10-K": DOC_IDS["ten_k"],
            "previous proxy": DOC_IDS["proxy"],
            "previous eight seasons": DOC_IDS["ten_q_1"],
        },
    ),
}
# A quote of the season of 2026-06-27 and of its call, with their attributions.
QUOTE_FILING = (TEN_Q_SUPPLY[0], DOC_IDS["ten_q_2"])
QUOTE_CALL = (CEO_DEMAND, f"{DOC_IDS['call_q2']}, {CEO[0]} ({CEO[1]})")


@dataclass(frozen=True)
class Reading:
    """One item's section: its baseline line, old and new values and quotes (text, attribution)."""

    baseline: str
    old: str
    new: str = "none"
    quotes: tuple[tuple[str, str], ...] = ()


def default_reading(item: Item, facts: SeasonFacts) -> Reading:
    """The reading the rules require of ``item`` in the season, else ``none`` against its baseline."""
    old = "—" if item.baseline == "none" else None
    if item.scope == "annual" and facts.form == "10-Q" or item.scope == "proxy" and not facts.proxy:
        return Reading("none", old or "not applicable", "not applicable")
    if item.scope == "call" and not facts.transcript:
        return Reading("none", old or "unavailable", "unavailable")
    if old is not None:
        return Reading("none", old)
    named = facts.baselines.get(item.baseline)
    if named is None:
        return Reading("none", "no baseline")
    return Reading(named, "none")


def readings_text(period: date, **changed: Reading) -> str:
    """The readings of the window season ``period``: every bot item's default reading, but those
    ``changed`` gives (keyed ``i1_1`` for item 1.1)."""
    facts = SEASON_FACTS[period]
    lines = [f"# {TICKER} · {period.isoformat()} · readings", ""]
    for item in BOT_ITEMS:
        reading = changed.get("i" + item.id.replace(".", "_"), default_reading(item, facts))
        lines += [
            f"## {item.heading}",
            f"baseline: {reading.baseline}",
            f"old: {reading.old}",
            f"new: {reading.new}",
        ]
        for text, attribution in reading.quotes:
            lines += [f"> {text}", f"— {attribution}"]
        lines.append("")
    return "\n".join(lines)


def readings_file(layout: DataLayout, period: date) -> Path:
    return layout.reports(TICKER) / period.isoformat() / "readings.md"


def write_readings(layout: DataLayout, period: date, text: str | None = None) -> Path:
    return place(readings_file(layout, period), readings_text(period) if text is None else text)


def research(layout: DataLayout, now: datetime = NOW) -> None:
    """Fetch, derive, then write each window season's default readings: ``plan`` says ``render``."""
    fetch(layout)
    workflow.derive(layout, TICKER, now)
    for row in WINDOW_SEASONS:
        assert row.period is not None
        write_readings(layout, row.period)


def plant_former_layout(layout: DataLayout) -> list[Path]:
    """The folders of the former layout, as a tree fetched before 2026-10-23 holds them."""
    root = layout.raw(TICKER)
    return [
        place(root / "edgar" / "submissions_20261001T050000EDT.json", "{}").parent,
        place(root / "calls" / "transcript_248001.json", "{}").parent,
    ]


def call_body(call: Call) -> bytes:
    return transcript_body(call)


def events() -> bytes:
    return events_page()
