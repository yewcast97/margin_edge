"""A recording fake of EarningsCalls.dev's HTTP layer, so no test reaches the provider.

``FakeEarningsCalls`` is a ``client.Fetch``: it serves a ``{url: Response}`` map (a value
may instead be an exception to raise, such as an ``EarningsCallsError`` standing for a
network failure), records ``(url, headers, limit)`` for every call, the failing ones
included, and fails loudly with ``AssertionError`` on a URL it does not serve, so code
under test cannot mistake a missing fixture for a provider error. ``calls_client`` wires
it, a ``RecordingSleep`` and a clock into an ``EarningsCallsClient`` under the test-only
``API_KEY``; ``CANARY`` is a key no output may ever show.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime

from market_state_research.fundamentals.script.client import Response
from market_state_research.fundamentals.script.earningscalls import (
    EarningsCallsClient,
    events_url,
    transcript_url,
)

from .calls_support import CALL_Q1, CALL_Q2, Call, events_page, transcript_body
from .edgar_support import TICKER
from .fake_edgar import RecordingSleep
from .support import NOW

API_KEY = "test-earningscalls-key"  # a test value, never a private setting
CANARY = "CANARY-earningscalls-key-0123456789"  # a key that must never appear in any output


def ok(body: bytes, content_type: str = "application/json; charset=utf-8", **headers: str) -> Response:
    """A status 200 response; ``headers`` are extra lower-case header names (``_`` for ``-``)."""
    named = {name.replace("_", "-"): value for name, value in headers.items()}
    return Response(200, "OK", {"content-type": content_type, **named}, body)


def status(code: int, reason: str = "", body: bytes = b"", **headers: str) -> Response:
    """A response with status ``code``, as ``urllib_fetch`` returns HTTP errors (a 429 with its body)."""
    named = {name.replace("_", "-"): value for name, value in headers.items()}
    return Response(code, reason, {"content-type": "application/json", **named}, body)


@dataclass
class FakeEarningsCalls:
    """A ``Fetch`` serving ``responses`` and recording every call."""

    responses: dict[str, Response | Exception] = field(default_factory=dict)
    calls: list[tuple[str, dict[str, str], int]] = field(default_factory=list)

    def __call__(self, url: str, headers: Mapping[str, str], limit: int) -> Response:
        self.calls.append((url, dict(headers), limit))
        if url not in self.responses:
            raise AssertionError(f"FakeEarningsCalls serves no response for {url}")
        served = self.responses[url]
        if isinstance(served, Exception):
            raise served
        return served

    @property
    def urls(self) -> list[str]:
        """The URL of every call, in order."""
        return [url for url, _, _ in self.calls]


def provider(
    page: bytes | None = None,
    transcripts: tuple[Call, ...] = (CALL_Q2, CALL_Q1),
    ticker: str = TICKER,
) -> FakeEarningsCalls:
    """The provider serving ``ticker``'s calls list (``page``, the default capture's page by default)
    and the transcript of each of ``transcripts``."""
    responses: dict[str, Response | Exception] = {
        events_url(ticker, 1): ok(events_page() if page is None else page),
    }
    for call in transcripts:
        responses[transcript_url(call.id)] = ok(transcript_body(call))
    return FakeEarningsCalls(responses)


def calls_client(
    fake: FakeEarningsCalls,
    sleep: RecordingSleep | None = None,
    clock: Callable[[], datetime] = lambda: NOW,
    api_key: str = API_KEY,
) -> EarningsCallsClient:
    """An ``EarningsCallsClient`` over ``fake``, recording its pacing in ``sleep`` (a new one by default)."""
    return EarningsCallsClient(
        api_key, fetch=fake, sleep=sleep if sleep is not None else RecordingSleep(), clock=clock
    )
