"""HTTPS to the domain's three sources: every request ``fetch`` sends.

Three fixed endpoints, each read with one plain GET and none with a key: FINRA's margin
statistics workbook (``www.finra.org``), the CFTC's Traders in Financial Futures dataset
through its public Socrata API (``publicreporting.cftc.gov``) and Cboe's daily history of
the VIX (``cdn-api.cboe.com``). So the domain reads no setting, and no URL it builds, prints
or stores carries a secret.

Requests go only to the three paths of ``ENDPOINTS``, over HTTPS, without credentials, a
port or a fragment in the URL, and with a query only where the endpoint takes one; no
redirect is followed. A body is accepted only as sent (a ``Content-Encoding`` other than
``identity`` is refused), with status 200, at most its endpoint's limit and not shorter than
its ``Content-Length``. Any other status, a network failure, a timeout and a body cut short
fail with one ``SourceError`` line naming the URL and the next step.

The HTTP layer is a ``Fetch`` callable, so tests replace it (and the clock) and never reach
the network. The HTTP reading helpers are copies of the stock IV regime domain's: domains
never import one another.
"""

import http.client
import re
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from email.message import Message
from typing import IO, Final
from urllib.parse import urlsplit

from market_state_research.common.text import printable
from market_state_research.common.times import to_eastern

TIMEOUT: Final = 60  # seconds per request
REDIRECT_NOT_FOLLOWED: Final = "redirect not followed"


@dataclass(frozen=True)
class Endpoint:
    """One source's fixed host and path, the body limit and what its answers are."""

    name: str
    host: str
    path: str
    query: bool  # whether its URLs carry a query
    limit: int  # bytes
    accept: str


FINRA: Final = Endpoint(
    "FINRA",
    "www.finra.org",
    "/sites/default/files/2021-03/margin-statistics.xlsx",
    False,
    4 * 1024 * 1024,  # the workbook is about 20 KB
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
)
CFTC: Final = Endpoint(
    "CFTC",
    "publicreporting.cftc.gov",
    "/resource/gpe5-46if.json",
    True,
    16 * 1024 * 1024,  # a full page of 5,000 rows is about 2.6 MB
    "application/json",
)
CBOE: Final = Endpoint(
    "Cboe",
    "cdn-api.cboe.com",
    "/api/global/us_indices/daily_prices/VIX_History.csv",
    False,
    8 * 1024 * 1024,  # the history since 1990 is about 0.5 MB and grows by about 12 KB a year
    "text/csv",
)
ENDPOINTS: Final = (FINRA, CFTC, CBOE)

# Explicit ASCII classes: \d would also match other Unicode digits.
_BYTE_COUNT = re.compile(r"[0-9]+", re.ASCII)


class SourceError(Exception):
    """A request failed or was refused; the message is one line."""


class TransportError(Exception):
    """A network failure, a refused redirect or a body cut short; the message names no URL."""


@dataclass(frozen=True)
class Response:
    """What the HTTP layer received: ``headers`` has lower-case names, ``body`` at most limit + 1 bytes."""

    status: int
    reason: str
    headers: Mapping[str, str]
    body: bytes


# (url, headers, limit) -> Response; a network failure raises TransportError.
Fetch = Callable[[str, Mapping[str, str], int], Response]


def endpoint_of(url: str) -> Endpoint | None:
    """The endpoint ``url`` is an HTTPS URL of, or None: printable ASCII, no spaces, credentials,
    port or fragment, its host and path exactly an endpoint's, and a query only where the
    endpoint takes one."""
    if not isinstance(url, str) or not (url.isascii() and url.isprintable()) or " " in url:
        return None
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.fragment:
        return None
    for endpoint in ENDPOINTS:
        if parts.netloc == endpoint.host and parts.path == endpoint.path:
            return endpoint if bool(parts.query) == endpoint.query else None
    return None


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuses every redirect urllib would follow; the target is never printed."""

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: IO[bytes],
        code: int,
        msg: str,
        headers: http.client.HTTPMessage,
        newurl: str,
    ) -> urllib.request.Request | None:
        fp.close()
        raise TransportError(f"HTTP {code} {REDIRECT_NOT_FOLLOWED}")


def lower_headers(message: Message | None) -> dict[str, str]:
    """Header values by lower-case name; a repeated header's values are joined by ``", "``."""
    headers: dict[str, str] = {}
    for name, value in message.items() if message is not None else ():
        key = name.lower()
        headers[key] = f"{headers[key]}, {value}" if key in headers else str(value)
    return headers


def failure_reason(cause: object, timeout: int = TIMEOUT) -> str:
    """A network failure's reason on one line; a timeout names the ``timeout`` the request had."""
    if isinstance(cause, TimeoutError):
        return f"no response within {timeout} seconds"
    if isinstance(cause, OSError) and cause.strerror:
        return printable(str(cause.strerror))
    return printable(str(cause)) or type(cause).__name__


def read_body(response: IO[bytes], limit: int) -> bytes:
    """At most ``limit + 1`` bytes of ``response``: enough to tell that a body is too large."""
    chunks: list[bytes] = []
    remaining = limit + 1
    while remaining > 0:
        chunk = response.read(min(remaining, 1024 * 1024))
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def count_order(digits: str) -> tuple[int, str]:
    """Orders byte counts written without leading zeros as their numbers: more digits, then text."""
    return len(digits), digits


def declared_length(headers: Mapping[str, str]) -> str | None:
    """The largest ``Content-Length`` of ASCII digits, without leading zeros; None without one."""
    values = (value.strip(" \t") for value in headers.get("content-length", "").split(","))
    counts = [value.lstrip("0") or "0" for value in values if _BYTE_COUNT.fullmatch(value)]
    return max(counts, key=count_order, default=None)


def urllib_fetch(url: str, headers: Mapping[str, str], limit: int) -> Response:
    """GET ``url`` through urllib, reading at most ``limit + 1`` body bytes.

    An HTTP error status is returned (with an empty body) for the client to judge; a
    network failure, a timeout, a redirect and a body within the limit that ended before
    the length http.client framed it by raise ``TransportError``, whose message never
    names the URL.
    """
    request = urllib.request.Request(url, headers=dict(headers), method="GET")
    try:
        with urllib.request.build_opener(_NoRedirect()).open(request, timeout=TIMEOUT) as response:
            status, reason = int(response.status), str(response.reason)
            received = lower_headers(response.headers)
            body = read_body(response, limit)
            owed: object = getattr(response, "length", None)
    except urllib.error.HTTPError as error:
        with error:
            status = int(error.code)
            reason = REDIRECT_NOT_FOLLOWED if 300 <= status < 400 else str(error.reason)
            return Response(status, reason, lower_headers(error.headers), b"")
    except urllib.error.URLError as error:
        raise TransportError(failure_reason(error.reason)) from None
    except (OSError, http.client.HTTPException) as error:  # TimeoutError is an OSError
        raise TransportError(failure_reason(error)) from None
    if isinstance(owed, int) and owed > 0 and len(body) <= limit:
        raise TransportError(f"the body ended after {len(body)} of {len(body) + owed} bytes")
    return Response(status, reason, received, body)


def _now() -> datetime:
    return to_eastern(datetime.now(UTC))


def _status_problem(url: str, endpoint: Endpoint, response: Response) -> str:
    status = f"GET {url}: HTTP {response.status}"
    if response.reason:
        status += f" {printable(response.reason)}"
    if response.status in (403, 404):
        return f"{status}; {endpoint.name} no longer serves this address: report it"
    if response.status == 429:
        return f"{status}; {endpoint.name}'s rate limit: wait some minutes and run fetch again"
    if 500 <= response.status <= 599:
        return f"{status}; {endpoint.name} is unavailable: wait and run fetch again"
    return status


class Client:
    """Requests to the three sources; see the module docstring."""

    def __init__(self, fetch: Fetch = urllib_fetch, clock: Callable[[], datetime] = _now) -> None:
        self._fetch = fetch
        self._clock = clock
        self._requests = 0

    def __repr__(self) -> str:
        return f"Client(requests={self._requests})"

    @property
    def requests(self) -> int:
        """Requests attempted so far, failed ones included."""
        return self._requests

    def now(self) -> datetime:
        """The client's clock, New York time."""
        return to_eastern(self._clock(), "now")

    def get(self, url: str) -> bytes:
        """GET the ``url`` of an endpoint (status 200, identity encoding, whole, at most the
        endpoint's limit) and return its body, or raise ``SourceError``."""
        endpoint = endpoint_of(url)
        if endpoint is None:
            hosts = ", ".join(f"https://{item.host}{item.path}" for item in ENDPOINTS)
            raise SourceError(f"GET {printable(url)}: only URLs of {hosts} are requested")
        self._requests += 1
        try:
            response = self._fetch(url, {"Accept": endpoint.accept}, endpoint.limit)
        except TransportError as error:
            raise SourceError(f"GET {url}: {error}; run fetch again") from None
        if response.status != 200:
            raise SourceError(_status_problem(url, endpoint, response))
        headers = {name.lower(): value for name, value in response.headers.items()}
        if headers.get("content-encoding", "identity").strip().lower() != "identity":
            raise SourceError(f"GET {url}: the body is encoded (Content-Encoding); only identity is accepted")
        if len(response.body) > endpoint.limit:
            raise SourceError(f"GET {url}: more than {endpoint.limit} bytes")
        received = str(len(response.body))
        declared = declared_length(headers)
        if declared is not None and count_order(received) < count_order(declared):
            raise SourceError(
                f"GET {url}: the body ended after {received} of {declared} bytes; run fetch again"
            )
        return response.body
