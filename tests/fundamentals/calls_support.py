"""EarningsCalls.dev bodies for the offline tests: calls pages and transcripts with known speakers.

Every body is synthetic, in the layout verified live on 2026-10-19 (the domain's
``AGENTS.md``): a calls page ``{"data": [...], "pagination": {...}, "ambiguous": false,
"issuer_count": 1}`` whose rows carry the provider's keys (more than the code reads), and
a transcript ``{"data": {..., "header": {...}, "components": [...]}}`` whose turns hold
sentences written for these tests, never a real call's words. Bodies are compact JSON as
the provider serves them.

The default capture lists four INTC calls, newest first: ``CALL_Q2`` (2026-07-23, the
quarter ended 2026-06-27), ``CALL_Q1`` (2026-04-23, the quarter ended 2026-03-28),
``CALL_OLD_Q`` (2025-10-23, the quarter ended 2025-09-27) and ``CALL_DROPPED``
(2024-10-31, on or before the oldest period end the fixtures' submissions list, so Rule B
drops it). No call is listed for the fiscal year ended 2025-12-27. ``TRANSCRIPTS`` holds
each call's turns, and ``call_text`` the derived text written out independently of the
code under test.
"""

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from .edgar_support import TICKER

ISSUER = "0123456789abcdef0123456789abcdef"  # a test issuer id, 32 lowercase hex digits
OTHER_ISSUER = "fedcba9876543210fedcba9876543210"


@dataclass(frozen=True)
class Call:
    """One listed call: its id, the provider's UTC time (list and header forms) and fiscal labels."""

    id: int
    listed_at: str  # as the calls list writes it, with milliseconds
    header_at: str  # as the transcript's header writes the same instant
    fiscal_year: int | None
    fiscal_quarter: int | None
    title: str


CALL_Q2 = Call(
    248001,
    "2026-07-23T21:00:00.000Z",
    "2026-07-23T21:00:00Z",
    2026,
    2,
    "Intel Corporation - Q2 2026 Earnings Call",
)
CALL_Q1 = Call(
    26083,
    "2026-04-23T21:00:00.000Z",
    "2026-04-23T21:00:00Z",
    2026,
    1,
    "Intel Corporation - Q1 2026 Earnings Call",
)
CALL_OLD_Q = Call(
    35174,
    "2025-10-23T21:00:00.000Z",
    "2025-10-23T21:00:00Z",
    2025,
    3,
    "Intel Corporation - Q3 2025 Earnings Call",
)
CALL_DROPPED = Call(
    64251,
    "2024-10-31T21:00:00.000Z",
    "2024-10-31T21:00:00Z",
    2024,
    3,
    "Intel Corporation - Q3 2024 Earnings Call",
)
CALLS = (CALL_Q2, CALL_Q1, CALL_OLD_Q, CALL_DROPPED)  # newest first, as the provider sorts them
# A later call, listed only by the tests that need it: after the 10-Q for the quarter ended
# 2026-06-27 was filed, so pending until the 10-Q for the quarter ended 2026-09-26 is listed.
CALL_Q3 = Call(
    250001,
    "2026-10-06T21:00:00.000Z",
    "2026-10-06T21:00:00Z",
    2026,
    3,
    "Intel Corporation - Q3 2026 Earnings Call",
)

# The speakers and their roles, as the transcripts name them.
OPERATOR = ("Operator", "operator")
HOST = ("John Pitzer", "executive")
CEO = ("Lip-Bu Tan", "executive")
CFO = ("David Zinsner", "executive")
ANALYST = ("Jane Analyst", "analyst")

# Sentences written for these tests, by speaker.
WELCOME = "Good afternoon and welcome to the Intel earnings conference call."
HOST_OPENING = "Thank you, operator. With me today are our CEO and our CFO."
CEO_DEMAND = "Demand for our server processors exceeded our supply in the quarter."
CEO_CAPACITY = "We are adding capacity for Intel 18A at our Arizona factory."
CFO_GUIDANCE = "We expect gross margin of approximately 36% in the third quarter."
CFO_FINANCING = "We funded our capital spending with cash from operations and partner contributions."
OPERATOR_QUESTION = "Our first question comes from Jane Analyst with Example Securities."
ANALYST_QUESTION = "Can you talk about how substrate supply constrained shipments in the quarter?"
CFO_SUPPLY = "Substrate supply remained tight during the quarter and limited our shipments."
Q1_DEMAND = "Data center demand grew faster than we planned in the first quarter."
Q3_DEMAND = "Client demand held up better than we expected in the third quarter."

# Each call's turns: (speaker, role, text), the text's paragraphs separated by CRLF as served.
TRANSCRIPTS: Mapping[int, tuple[tuple[str, str, str], ...]] = {
    CALL_Q2.id: (
        (*OPERATOR, WELCOME),
        (*HOST, HOST_OPENING),
        (*CEO, f"{CEO_DEMAND}\r\n{CEO_CAPACITY}"),
        (*CFO, f"{CFO_GUIDANCE}\r\n{CFO_FINANCING}"),
        (*OPERATOR, OPERATOR_QUESTION),
        (*ANALYST, ANALYST_QUESTION),
        (*CFO, CFO_SUPPLY),
    ),
    CALL_Q1.id: (
        (*OPERATOR, WELCOME),
        (*CEO, Q1_DEMAND),
    ),
    CALL_OLD_Q.id: ((*CEO, CEO_DEMAND),),
    CALL_DROPPED.id: ((*CEO, CEO_DEMAND),),
    CALL_Q3.id: ((*CEO, Q3_DEMAND),),
}


def compact(value: object) -> bytes:
    """``value`` as compact UTF-8 JSON, as the provider serves it."""
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def call_row(call: Call, *, symbol: str = TICKER, issuer: str | None = ISSUER, **fields: object) -> dict:
    """One calls-list row in the provider's layout; ``fields`` replace or add keys."""
    row: dict[str, object] = {
        "id": call.id,
        "company_name": "Intel Corporation",
        "transcript_title": "Intel Corporation - Earnings",
        "event_type": "earnings",
        "event_date_time": call.listed_at,
        "sector": "Information Technology",
        "industry": "Semiconductors and Semiconductor Equipment",
        "market_cap": None,
        "stock_symbol": symbol,
        "company_ticker": f"{symbol}:US",
        "exchange": "NASDAQ",
        "mic": "XNAS",
        "country": "US",
        "currency": "USD",
        "fiscal_year": call.fiscal_year,
        "fiscal_quarter": call.fiscal_quarter,
        "issuer_id": issuer,
        "issuer_ref": issuer,
        "isin": "US4581401001",
        "timezone": "America/New_York",
        "matched_alias": symbol,
    }
    row.update(fields)
    return row


def events_page(
    rows: Sequence[Mapping[str, object]] = tuple(call_row(call) for call in CALLS),
    *,
    page: int = 1,
    total: int | None = None,
    total_pages: int | None = None,
    ambiguous: bool = False,
    issuer_count: int | None = None,
    **fields: object,
) -> bytes:
    """One calls page holding ``rows``; ``total`` defaults to their count, ``total_pages`` to the
    pages that count fills and ``issuer_count`` to 1 (0 without a row)."""
    count = len(rows) if total is None else total
    value: dict[str, object] = {
        "data": list(rows),
        "pagination": {
            "page": page,
            "limit": 100,
            "total": count,
            "total_pages": -(-count // 100) if total_pages is None else total_pages,
        },
        "ambiguous": ambiguous,
        "issuer_count": (1 if rows else 0) if issuer_count is None else issuer_count,
    }
    value.update(fields)
    return compact(value)


def components(turns: Sequence[tuple[str, str, str]]) -> list[dict[str, object]]:
    return [
        {"order": order, "speaker_name": speaker, "speaker_type": role, "text": text}
        for order, (speaker, role, text) in enumerate(turns)
    ]


def transcript_body(
    call: Call = CALL_Q2,
    turns: Sequence[tuple[str, str, str]] | None = None,
    *,
    header: Mapping[str, object] | None = None,
    **data: object,
) -> bytes:
    """A transcript in the provider's layout: ``turns`` (the call's own by default) as its
    components; ``header`` replaces or adds header keys, ``data`` data keys."""
    held = TRANSCRIPTS[call.id] if turns is None else turns
    head: dict[str, object] = {
        "company_name": "Intel Corporation",
        "title": call.title,
        "transcript_title": "Intel Corporation - Earnings",
        "formatted_title": "Intel Corporation - Earnings",
        "event_type": "earnings",
        "event_date_time": call.header_at,
        "announced_date": "2026-06-30T20:30:00Z",
        "duration": 3525,
        "created_at": "2026-07-23T23:19:52Z",
    }
    head.update(header or {})
    value: dict[str, object] = {
        "company_name": "Intel Corporation",
        "transcript_title": "Intel Corporation - Earnings",
        "event_type": "earnings",
        "duration_seconds": 3525,
        "header": head,
        "components": components(held),
    }
    value.update(data)
    return compact({"data": value})


def call_text(call: Call = CALL_Q2) -> str:
    """The derived text of ``call``, written out: per turn its heading line, then its paragraphs."""
    lines: list[str] = []
    for speaker, role, text in TRANSCRIPTS[call.id]:
        lines.append(f"{speaker} ({role})")
        lines.extend(text.split("\r\n"))
    return "\n".join(lines) + "\n"
