"""HTTPS to the domain's three sources: every request ``fetch`` sends.

Three fixed endpoints, each read with one plain GET: FINRA's margin statistics workbook
(``www.finra.org``, public, no key), the CFTC's Traders in Financial Futures dataset through
its public Socrata API (``publicreporting.cftc.gov``, no key) and FRED's series observations
(``api.stlouisfed.org``) under the user's own key, ``FRED_API``, from the ignored
repository-root ``.env``. FRED takes the key only as the ``api_key`` query parameter, so it
is appended to a FRED URL at send time and nowhere else: every URL this package builds,
prints or stores is key-free, a URL that already carries ``api_key`` is refused, and every
message passes through ``redact``. The key is checked before any request (``check_api_key``:
FRED's form, 32 lowercase ASCII letters or digits) and is printed only as ``set``.

Requests go only to the three paths of ``ENDPOINTS``, over HTTPS, without credentials, a
port or a fragment in the URL; no redirect is followed. A body is accepted only as sent (a
``Content-Encoding`` other than ``identity`` is refused), with status 200, at most its
endpoint's limit and not shorter than its ``Content-Length``. Any other status, a network
failure, a timeout and a body cut short fail with one ``SourceError`` line naming the
key-free URL and the next step.

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
from urllib.parse import parse_qsl, urlsplit

from market_state_research.common.text import printable
from market_state_research.common.times import to_eastern

API_KEY_SETTING: Final = "FRED_API"
KEY_PARAMETER: Final = "api_key"
TIMEOUT: Final = 60  # seconds per request
REDACTED: Final = f"<{API_KEY_SETTING}>"
API_KEY_UNSET: Final = (
    f'{API_KEY_SETTING} is not set; add {API_KEY_SETTING}="..." to the repository-root .env'
)
API_KEY_MALFORMED: Final = f"{API_KEY_SETTING} must be 32 lowercase ASCII letters or digits"
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
FRED: Final = Endpoint(
    "FRED",
    "api.stlouisfed.org",
    "/fred/series/observations",
    True,
    4 * 1024 * 1024,  # a series of 323 quarters is about 32 KB
    "application/json",
)
ENDPOINTS: Final = (FINRA, CFTC, FRED)

# Explicit ASCII classes: \d would also match other Unicode digits.
_API_KEY = re.compile(r"[a-z0-9]{32}", re.ASCII)
_BYTE_COUNT = re.compile(r"[0-9]+", re.ASCII)


class SourceError(Exception):
    """A request failed or was refused; the message is one line without the key."""


class TransportError(Exception):
    """A network failure, a refused redirect or a body cut short; the message names no URL."""


@dataclass(frozen=True)
class Response:
    """What the HTTP layer received: ``headers`` has lower-case names, ``body`` at most limit + 1 bytes."""

    status: int
    reason: str
    headers: Mapping[str, str]
    body: bytes


# (url, with the key for FRED; headers; limit) -> Response; a network failure raises TransportError.
Fetch = Callable[[str, Mapping[str, str], int], Response]


def check_api_key(value: str | None) -> str:
    """``value`` when it can be a FRED key; never echoed."""
    if not value:
        raise SourceError(API_KEY_UNSET)
    if not isinstance(value, str) or not _API_KEY.fullmatch(value):
        raise SourceError(API_KEY_MALFORMED)
    return value


def redact(text: str, key: str) -> str:
    """``text`` with every occurrence of ``key`` replaced by ``<FRED_API>``."""
    return text.replace(key, REDACTED) if key else text


def endpoint_of(url: str) -> Endpoint | None:
    """The endpoint ``url`` is a key-free HTTPS URL of, or None: printable ASCII, no spaces,
    credentials, port or fragment, its host and path exactly an endpoint's, a query only where
    the endpoint takes one, and no ``api_key`` parameter."""
    if not isinstance(url, str) or not (url.isascii() and url.isprintable()) or " " in url:
        return None
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.fragment:
        return None
    for endpoint in ENDPOINTS:
        if parts.netloc == endpoint.host and parts.path == endpoint.path:
            if bool(parts.query) != endpoint.query:
                return None
            names = [name for name, _ in parse_qsl(parts.query, keep_blank_values=True)]
            return None if KEY_PARAMETER in names else endpoint
    return None


def _with_key(url: str, key: str) -> str:
    return f"{url}&{KEY_PARAMETER}={key}"


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
    names the URL (a FRED URL carries the key).
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
    if endpoint is FRED and response.status in (400, 401, 403):
        return f"{status}; FRED refused the request: check {API_KEY_SETTING}"
    if response.status == 404:
        return f"{status}; {endpoint.name} no longer serves this address: report it"
    if response.status == 429:
        return f"{status}; {endpoint.name}'s rate limit: wait some minutes and run fetch again"
    if 500 <= response.status <= 599:
        return f"{status}; {endpoint.name} is unavailable: wait and run fetch again"
    return status


class Client:
    """Requests to the three sources under one checked FRED key; see the module docstring."""

    def __init__(
        self,
        api_key: str | None,
        fetch: Fetch = urllib_fetch,
        clock: Callable[[], datetime] = _now,
    ) -> None:
        self._key = check_api_key(api_key)
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
        """GET the key-free ``url`` of an endpoint (status 200, identity encoding, whole, at most
        the endpoint's limit) and return its body, or raise ``SourceError``."""
        endpoint = endpoint_of(url)
        if endpoint is None:
            hosts = ", ".join(f"https://{item.host}{item.path}" for item in ENDPOINTS)
            raise SourceError(
                f"GET {printable(redact(url, self._key))}: only key-free URLs of {hosts} are requested"
            )
        self._requests += 1
        sent = _with_key(url, self._key) if endpoint is FRED else url
        try:
            response = self._fetch(sent, {"Accept": endpoint.accept}, endpoint.limit)
        except TransportError as error:
            raise SourceError(f"GET {url}: {redact(str(error), self._key)}; run fetch again") from None
        if response.status != 200:
            raise SourceError(redact(_status_problem(url, endpoint, response), self._key))
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
