"""urllib driven offline: a fake HTTPS handler that serves canned responses and records requests.

``client.urllib_fetch`` and ``earningscalls.urllib_fetch`` run urllib's real opener
(redirect handling, error processing, the headers urllib adds) over ``FakeTransport``,
which replaces the HTTPS handler; plain HTTP and socket connections fail loudly.
``offline_network`` installs it for one test (each test module wraps it in its own
``network`` fixture). A route is served by URL, whatever the method: a ``Served``
response, a ``Raw`` one that http.client itself reads from the bytes a server sent before
closing the connection (so a body cut short reaches the code as it would from the
server), or an exception to raise. Every request is recorded as ``Sent``, with its
method, headers, body and timeout, the failing ones included.
"""

import http.client
import io
import socket
import urllib.request
import urllib.response
from dataclasses import dataclass, field

import pytest


@dataclass
class Served:
    """One canned HTTPS response; ``headers`` may repeat a name."""

    status: int = 200
    reason: str = "OK"
    headers: tuple[tuple[str, str], ...] = (("Content-Type", "application/json"),)
    body: bytes = b"{}"
    step: int | None = None  # serve at most this many bytes per read
    failure: BaseException | None = None  # raised by the first read of the body


class Body(io.BytesIO):
    """A response body that records the size of every read."""

    def __init__(self, served: Served) -> None:
        super().__init__(served.body)
        self.served = served
        self.asked: list[int | None] = []
        self.consumed = 0

    def read(self, size: int | None = -1) -> bytes:
        self.asked.append(size)
        if self.served.failure is not None:
            raise self.served.failure
        step = self.served.step
        if step is not None and (size is None or size < 0 or size > step):
            size = step
        data = super().read(size)
        self.consumed += len(data)
        return data


@dataclass(frozen=True)
class Raw:
    """What a server sent before closing the connection cleanly, read by http.client itself."""

    data: bytes


class RawSocket:
    """The one socket method http.client's response uses: a file of the bytes received."""

    def __init__(self, data: bytes) -> None:
        self.data = data

    def makefile(self, mode: str) -> io.BytesIO:
        return io.BytesIO(self.data)


@dataclass
class Sent:
    """One request as urllib handed it to the HTTPS handler."""

    url: str
    method: str
    headers: dict[str, str]  # every header, urllib's own included, under urllib's capitalisation
    timeout: float | None
    body: bytes | None = None
    added: tuple[str, ...] = ()  # the names of the headers urllib added itself


class FakeTransport(urllib.request.HTTPSHandler):
    """Replaces urllib's HTTPS handler: serves ``routes`` by URL and records every request."""

    def __init__(self) -> None:
        super().__init__()
        self.routes: dict[str, Served | Raw | BaseException] = {}
        self.sent: list[Sent] = []
        self.bodies: list[Body] = []

    def https_open(self, req):
        self.sent.append(
            Sent(
                req.full_url,
                req.get_method(),
                dict(req.header_items()),
                req.timeout,
                req.data,
                tuple(req.unredirected_hdrs),
            )
        )
        if req.full_url not in self.routes:
            raise AssertionError(f"FakeTransport serves no response for {req.full_url}")
        served = self.routes[req.full_url]
        if isinstance(served, BaseException):
            raise served
        if isinstance(served, Raw):
            parsed = http.client.HTTPResponse(RawSocket(served.data), method=req.get_method())
            parsed.begin()
            parsed.url, parsed.msg = req.full_url, parsed.reason  # as urllib's own HTTPS handler sets them
            return parsed
        message = http.client.HTTPMessage()
        for name, value in served.headers:
            message[name] = value  # assignment appends, so a name may repeat
        body = Body(served)
        self.bodies.append(body)
        response = urllib.response.addinfourl(body, message, req.full_url, served.status)
        response.msg = response.reason = served.reason  # as http.client's response carries them
        return response


class NoPlainHTTP(urllib.request.HTTPHandler):
    def http_open(self, req):
        raise AssertionError("plain HTTP reached the transport")


@dataclass
class Network:
    transport: FakeTransport = field(default_factory=FakeTransport)
    openers: int = 0


def offline_network(monkeypatch: pytest.MonkeyPatch) -> Network:
    """urllib with ``FakeTransport`` in place of HTTPS; plain HTTP and sockets fail loudly."""
    state = Network()
    build_opener = urllib.request.build_opener

    def offline_opener(*handlers):
        state.openers += 1
        return build_opener(urllib.request.ProxyHandler({}), NoPlainHTTP(), state.transport, *handlers)

    def no_connection(*args, **kwargs):
        raise AssertionError("a socket connection was attempted")

    monkeypatch.setattr(urllib.request, "build_opener", offline_opener)
    monkeypatch.setattr(socket, "create_connection", no_connection)
    return state
