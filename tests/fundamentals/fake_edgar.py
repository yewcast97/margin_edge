"""A recording fake of the EDGAR HTTP layer, so no issuer test reaches the network.

``FakeEdgar`` is a ``client.Fetch``: it serves a ``{url: Response}`` map (a value may
instead be an exception to raise, such as an ``EdgarError`` standing for a network
failure), records ``(url, headers, limit)`` for every call, the failing ones included,
and fails loudly with ``AssertionError`` on a URL it does not serve, so code under test
cannot mistake a missing fixture for an EDGAR error. ``RecordingSleep`` records the
pacing instead of sleeping. ``edgar_client`` wires both (and a fixed clock) into an
``EdgarClient`` under the test-only ``USER_AGENT``.
"""

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime

from market_state_research.fundamentals.script.client import EdgarClient, Response

from .support import NOW

USER_AGENT = "margin_edge tests@example.com"  # a test value, never a private setting


def ok(body: bytes, content_type: str = "application/json", **headers: str) -> Response:
    """A status 200 response; ``headers`` are extra lower-case header names (``_`` for ``-``)."""
    named = {name.replace("_", "-"): value for name, value in headers.items()}
    return Response(200, "OK", {"content-type": content_type, **named}, body)


def ok_json(value: object) -> Response:
    """A status 200 JSON response holding ``value`` as compact UTF-8 JSON."""
    return ok(json.dumps(value).encode())


def ok_html(text: str, charset: str = "utf-8") -> Response:
    """A status 200 HTML response holding ``text`` encoded in ``charset``."""
    return ok(text.encode(charset), f"text/html; charset={charset}")


def status(code: int, reason: str = "") -> Response:
    """A response with status ``code`` and an empty body, as ``urllib_fetch`` returns HTTP errors."""
    return Response(code, reason, {"content-type": "text/html"}, b"")


@dataclass
class FakeEdgar:
    """A ``Fetch`` serving ``responses`` and recording every call."""

    responses: dict[str, Response | Exception] = field(default_factory=dict)
    calls: list[tuple[str, dict[str, str], int]] = field(default_factory=list)

    def __call__(self, url: str, headers: Mapping[str, str], limit: int) -> Response:
        self.calls.append((url, dict(headers), limit))
        if url not in self.responses:
            raise AssertionError(f"FakeEdgar serves no response for {url}")
        served = self.responses[url]
        if isinstance(served, Exception):
            raise served
        return served

    @property
    def urls(self) -> list[str]:
        """The URL of every call, in order."""
        return [url for url, _, _ in self.calls]


@dataclass
class RecordingSleep:
    """A ``sleep`` that records each requested pause instead of pausing."""

    calls: list[float] = field(default_factory=list)

    def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)


def edgar_client(
    edgar: FakeEdgar,
    sleep: RecordingSleep | None = None,
    clock: Callable[[], datetime] = lambda: NOW,
    user_agent: str = USER_AGENT,
) -> EdgarClient:
    """An ``EdgarClient`` over ``edgar``, recording its pacing in ``sleep`` (a new one by default)."""
    return EdgarClient(
        user_agent, fetch=edgar, sleep=sleep if sleep is not None else RecordingSleep(), clock=clock
    )
