"""EODHD's options API over HTTPS: every request ``fetch`` sends.

The source is the marketplace product "US Stock Options Data" by UnicornBay, read under
the user's own key (``EODHD_API``, from the ignored repository-root ``.env``). EODHD takes
the key only as the ``api_token`` query parameter, so it is appended to a URL at send time
and nowhere else: every URL this package builds, prints or stores is token-free, a URL that
already carries ``api_token`` is refused, and every message passes through ``redact``. The
key is checked before any request (``check_api_key``: 8 to 200 URL-safe ASCII characters,
so it needs no encoding) and is printed only as ``set``.

Requests go only to ``https://eodhd.com`` under ``/api/mp/unicornbay/options/``, without
credentials or a port in the URL; no redirect is followed. Bodies are accepted only as sent
(a ``Content-Encoding`` other than ``identity`` is refused), with status 200, at most
``PAGE_LIMIT_BYTES`` and not shorter than their ``Content-Length``. A client paces its
requests (``sleep(PACING)`` before every request after its first: EODHD allows 1,000 a
minute) and counts them; with a ``budget`` it refuses to send more than that many
(``BudgetSpent``), so a run can stop cleanly before the product's daily quota.

Statuses: 402 is the product's daily quota (100,000 API calls per rolling 24 hours, ten
per request), raised as ``QuotaExceeded`` so a run keeps what it wrote and stops cleanly;
429 is the per-minute limit; 401, 403, 5xx and every other status fail with one
``EodhdError`` line naming the token-free URL and the next step, and so do a network
failure, a timeout and a body cut short (``TransportError``): run ``fetch`` again. A request
that got HTTP 429 or no whole answer is sent once more, after the ``Retry-After`` pause (at
most ``RETRY_PAUSE`` seconds) or ``RETRY_PAUSE`` seconds, and the second answer is final.

The HTTP layer is a ``Fetch`` callable, so tests replace it (and ``sleep`` and the clock)
and never reach the network. The HTTP reading helpers are copies of the fundamentals
domain's: domains never import one another.
"""

import http.client
import re
import time
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

HOST: Final = "eodhd.com"
PATH_PREFIX: Final = "/api/mp/unicornbay/options/"
API_KEY_SETTING: Final = "EODHD_API"
TOKEN_PARAMETER: Final = "api_token"
PAGE_LIMIT_BYTES: Final = 8 * 1024 * 1024  # a page of at most 1,000 records is about 0.3 MB
TIMEOUT: Final = 60  # seconds per request
PACING: Final = 0.1  # seconds before every request after the first: EODHD allows 1,000 a minute
RETRY_PAUSE: Final = 60  # seconds before a request's second sending; a 429's Retry-After when shorter
REDACTED: Final = f"<{API_KEY_SETTING}>"
API_KEY_UNSET: Final = (
    f'{API_KEY_SETTING} is not set; add {API_KEY_SETTING}="..." to the repository-root .env'
)
API_KEY_MALFORMED: Final = f"{API_KEY_SETTING} must be 8 to 200 ASCII letters, digits, '.', '_', '~' or '-'"
QUOTA_SPENT: Final = (
    "EODHD's daily quota of the options product (100,000 API calls per rolling 24 hours, "
    "10 per request) is spent; run fetch again later"
)
REDIRECT_NOT_FOLLOWED: Final = "redirect not followed"

# Explicit ASCII classes: \d would also match other Unicode digits.
_API_KEY = re.compile(r"[A-Za-z0-9._~-]{8,200}", re.ASCII)
_BYTE_COUNT = re.compile(r"[0-9]+", re.ASCII)
_SECONDS = re.compile(r"[0-9]{1,6}", re.ASCII)


class EodhdError(Exception):
    """An EODHD request failed or was refused; the message is one line without the key."""


class QuotaExceeded(EodhdError):
    """HTTP 402: the product's daily quota is spent. A run stops cleanly and keeps its files."""


class BudgetSpent(EodhdError):
    """The run's ``--budget`` of requests is spent; nothing more is sent."""


class TransportError(Exception):
    """A network failure, a refused redirect or a body cut short; the message names no URL."""


@dataclass(frozen=True)
class Response:
    """What the HTTP layer received: ``headers`` has lower-case names, ``body`` at most limit + 1 bytes."""

    status: int
    reason: str
    headers: Mapping[str, str]
    body: bytes


# (url with the key, headers, limit) -> Response; a network failure raises TransportError.
Fetch = Callable[[str, Mapping[str, str], int], Response]


def check_api_key(value: str | None) -> str:
    """``value`` when it can be an EODHD key; never echoed."""
    if not value:
        raise EodhdError(API_KEY_UNSET)
    if not isinstance(value, str) or not _API_KEY.fullmatch(value):
        raise EodhdError(API_KEY_MALFORMED)
    return value


def redact(text: str, key: str) -> str:
    """``text`` with every occurrence of ``key`` replaced by ``<EODHD_API>``."""
    return text.replace(key, REDACTED) if key else text


def allowed_url(url: str) -> bool:
    """Whether ``url`` is a token-free HTTPS URL of the options API: printable ASCII, no
    spaces, credentials, port or fragment, and no ``api_token`` parameter."""
    if not isinstance(url, str) or not (url.isascii() and url.isprintable()) or " " in url:
        return False
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.netloc != HOST or parts.fragment:
        return False
    if not parts.path.startswith(PATH_PREFIX):
        return False
    return all(name != TOKEN_PARAMETER for name, _ in parse_qsl(parts.query, keep_blank_values=True))


def _with_key(url: str, key: str) -> str:
    return f"{url}{'&' if '?' in url else '?'}{TOKEN_PARAMETER}={key}"


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
    names the URL (it carries the key).
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


def _status_problem(url: str, response: Response) -> str:
    status = f"GET {url}: HTTP {response.status}"
    if response.reason:
        status += f" {printable(response.reason)}"
    if response.status == 401:
        return f"{status}; EODHD refused the key: check {API_KEY_SETTING}"
    if response.status == 403:
        return (
            f"{status}; EODHD refused the request: the account needs the marketplace product "
            '"US Stock Options Data" (UnicornBay)'
        )
    if response.status == 429:
        return f"{status}; EODHD's rate limit of requests per minute: wait a minute and run fetch again"
    if 500 <= response.status <= 599:
        return f"{status}; EODHD is unavailable: wait and run fetch again"
    return status


def _retry_after(headers: Mapping[str, str]) -> int:
    """Seconds to wait after HTTP 429: ``Retry-After`` in whole seconds, at most ``RETRY_PAUSE``."""
    value = headers.get("retry-after", "").strip(" \t")
    return min(int(value), RETRY_PAUSE) if _SECONDS.fullmatch(value) else RETRY_PAUSE


class EodhdClient:
    """Paced EODHD requests under one checked key; see the module docstring."""

    def __init__(
        self,
        api_key: str | None,
        fetch: Fetch = urllib_fetch,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], datetime] = _now,
        budget: int | None = None,
    ) -> None:
        self._key = check_api_key(api_key)
        self._fetch = fetch
        self._sleep = sleep
        self._clock = clock
        self._budget = budget
        self._requests = 0

    def __repr__(self) -> str:
        return f"EodhdClient(requests={self._requests})"

    @property
    def requests(self) -> int:
        """Requests attempted so far, failed ones and second sendings included."""
        return self._requests

    @property
    def budget(self) -> int | None:
        return self._budget

    def now(self) -> datetime:
        """The client's clock, New York time."""
        return to_eastern(self._clock(), "now")

    def _send(self, url: str) -> Response:
        """One sending of ``url``, paced and counted; ``TransportError`` when no whole answer came."""
        if self._budget is not None and self._requests >= self._budget:
            raise BudgetSpent(f"the run's budget of {self._budget} requests is spent; run fetch again")
        if self._requests:
            self._sleep(PACING)
        self._requests += 1
        return self._fetch(_with_key(url, self._key), {"Accept": "application/json"}, PAGE_LIMIT_BYTES)

    def _answer(self, url: str) -> Response:
        """The final answer to ``url``: after HTTP 429 or no whole answer, that of a second sending."""
        try:
            response = self._send(url)
        except TransportError:
            pause = RETRY_PAUSE
        else:
            if response.status != 429:
                return response
            pause = _retry_after({name.lower(): value for name, value in response.headers.items()})
        self._sleep(pause)
        try:
            return self._send(url)
        except TransportError as error:
            reason = redact(str(error), self._key)
            raise EodhdError(f"GET {url}: {reason}; run fetch again") from None

    def get(self, url: str) -> bytes:
        """GET the token-free ``url`` (status 200, identity encoding, whole, at most
        ``PAGE_LIMIT_BYTES``) and return its body, or raise ``EodhdError``."""
        if not allowed_url(url):
            raise EodhdError(
                f"GET {printable(redact(url, self._key))}: only token-free HTTPS URLs of the "
                f"options API on https://{HOST}{PATH_PREFIX} are requested"
            )
        response = self._answer(url)
        if response.status == 402:
            raise QuotaExceeded(f"GET {url}: HTTP 402; {QUOTA_SPENT}")
        if response.status != 200:
            raise EodhdError(redact(_status_problem(url, response), self._key))
        headers = {name.lower(): value for name, value in response.headers.items()}
        if headers.get("content-encoding", "identity").strip().lower() != "identity":
            raise EodhdError(f"GET {url}: the body is encoded (Content-Encoding); only identity is accepted")
        if len(response.body) > PAGE_LIMIT_BYTES:
            raise EodhdError(f"GET {url}: more than {PAGE_LIMIT_BYTES} bytes")
        received = str(len(response.body))
        declared = declared_length(headers)
        if declared is not None and count_order(received) < count_order(declared):
            raise EodhdError(
                f"GET {url}: the body ended after {received} of {declared} bytes; run fetch again"
            )
        return response.body
