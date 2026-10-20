"""Tiingo's end-of-day stock prices over HTTPS: the second source ``fetch`` reads.

The source is Tiingo's daily prices endpoint, read under the user's own key
(``TIINGO_API``, from the ignored repository-root ``.env``). The key travels only in the
``Authorization: Token ...`` header, so every URL this package builds, prints or stores is
key-free by construction: a URL that carries a ``token`` parameter is refused, and every
message passes through ``redact``. The key is checked before any request
(``check_api_key``: 8 to 200 URL-safe ASCII characters) and is printed only as ``set``.

Requests go only to ``https://api.tiingo.com/tiingo/daily/{TICKER}/prices``, without
credentials or a port in the URL; no redirect is followed. Bodies are accepted only as sent
(a ``Content-Encoding`` other than ``identity`` is refused), with status 200, at most
``BODY_LIMIT`` and not shorter than their ``Content-Length``. A run sends one request per
ticker, so no pacing is needed: the Starter plan allows 50 an hour and 1,000 a day.

Statuses: 404 is ``NotCovered`` (Tiingo has no prices for the ticker); 401, 403 and 429 are
``Stopped`` (Tiingo refused the key, which it answers with 403, or the plan's hourly or
daily request limit is reached), after which a run asks Tiingo nothing more; every other
status, a network failure, a timeout and a body cut short raise ``TiingoError`` for the
ticker at hand.

The HTTP layer is ``client``'s (``Fetch``, ``urllib_fetch``: the same domain), so tests
replace it and never reach the network.
"""

import re
from collections.abc import Callable, Mapping
from datetime import UTC, date, datetime
from typing import Final
from urllib.parse import parse_qsl, urlencode, urlsplit

from market_state_research.common.text import printable
from market_state_research.common.times import to_eastern

from .client import Fetch, Response, TransportError, count_order, declared_length, urllib_fetch

HOST: Final = "api.tiingo.com"
PATH_PREFIX: Final = "/tiingo/daily/"
API_KEY_SETTING: Final = "TIINGO_API"
TOKEN_PARAMETER: Final = "token"
BODY_LIMIT: Final = 8 * 1024 * 1024  # a year of daily bars is about 65 KB
REDACTED: Final = f"<{API_KEY_SETTING}>"
API_KEY_UNSET: Final = (
    f'{API_KEY_SETTING} is not set; add {API_KEY_SETTING}="..." to the repository-root .env'
)
API_KEY_MALFORMED: Final = f"{API_KEY_SETTING} must be 8 to 200 ASCII letters, digits, '.', '_', '~' or '-'"

# Explicit ASCII classes: \d would also match other Unicode digits.
_API_KEY = re.compile(r"[A-Za-z0-9._~-]{8,200}", re.ASCII)
_PRICES_PATH = re.compile(r"/tiingo/daily/[A-Z][A-Z0-9.\-]{0,14}/prices", re.ASCII)


class TiingoError(Exception):
    """A Tiingo request failed or was refused; the message is one line without the key."""


class NotCovered(TiingoError):
    """HTTP 404: Tiingo has no prices for the ticker."""


class Stopped(TiingoError):
    """HTTP 401, 403 or 429: the key or the plan's request limit refuses every further request."""


def check_api_key(value: str | None) -> str:
    """``value`` when it can be a Tiingo key; never echoed."""
    if not value:
        raise TiingoError(API_KEY_UNSET)
    if not isinstance(value, str) or not _API_KEY.fullmatch(value):
        raise TiingoError(API_KEY_MALFORMED)
    return value


def redact(text: str, key: str) -> str:
    """``text`` with every occurrence of ``key`` replaced by ``<TIINGO_API>``."""
    return text.replace(key, REDACTED) if key else text


def prices_url(ticker: str, start: date, end: date) -> str:
    """The key-free URL of ``ticker``'s daily bars from ``start`` to ``end``, both included."""
    query = urlencode([("startDate", start.isoformat()), ("endDate", end.isoformat())])
    return f"https://{HOST}{PATH_PREFIX}{ticker}/prices?{query}"


def allowed_url(url: str) -> bool:
    """Whether ``url`` is a key-free HTTPS URL of Tiingo's daily prices: printable ASCII, no
    spaces, credentials, port or fragment, and no ``token`` parameter."""
    if not isinstance(url, str) or not (url.isascii() and url.isprintable()) or " " in url:
        return False
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.netloc != HOST or parts.fragment:
        return False
    if _PRICES_PATH.fullmatch(parts.path) is None:
        return False
    return all(name != TOKEN_PARAMETER for name, _ in parse_qsl(parts.query, keep_blank_values=True))


def _now() -> datetime:
    return to_eastern(datetime.now(UTC))


def _status_problem(url: str, response: Response) -> tuple[type[TiingoError], str]:
    status = f"GET {url}: HTTP {response.status}"
    if response.reason:
        status += f" {printable(response.reason)}"
    if response.status == 404:
        return NotCovered, f"{status}; Tiingo has no prices for this ticker"
    if response.status in (401, 403):
        return (
            Stopped,
            f"{status}; Tiingo refused the key or the request: check {API_KEY_SETTING} and its plan",
        )
    if response.status == 429:
        return Stopped, (
            f"{status}; Tiingo's request limit (per hour or per day) is reached: run fetch again once it "
            "resets"
        )
    if 500 <= response.status <= 599:
        return TiingoError, f"{status}; Tiingo is unavailable: run fetch again later"
    return TiingoError, status


class TiingoClient:
    """Tiingo requests under one checked key; see the module docstring."""

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
        return f"TiingoClient(requests={self._requests})"

    @property
    def requests(self) -> int:
        """Requests attempted so far, failed ones included."""
        return self._requests

    def now(self) -> datetime:
        """The client's clock, New York time."""
        return to_eastern(self._clock(), "now")

    def get(self, url: str) -> bytes:
        """GET the key-free ``url`` (status 200, identity encoding, whole, at most
        ``BODY_LIMIT``) and return its body, or raise ``TiingoError``."""
        if not allowed_url(url):
            raise TiingoError(
                f"GET {printable(redact(url, self._key))}: only key-free HTTPS URLs of Tiingo's daily "
                f"prices on https://{HOST}{PATH_PREFIX} are requested"
            )
        self._requests += 1
        headers: Mapping[str, str] = {"Accept": "application/json", "Authorization": f"Token {self._key}"}
        try:
            response = self._fetch(url, headers, BODY_LIMIT)
        except TransportError as error:
            raise TiingoError(f"GET {url}: {redact(str(error), self._key)}; run fetch again later") from None
        if response.status != 200:
            kind, message = _status_problem(url, response)
            raise kind(redact(message, self._key))
        received_headers = {name.lower(): value for name, value in response.headers.items()}
        if received_headers.get("content-encoding", "identity").strip().lower() != "identity":
            raise TiingoError(f"GET {url}: the body is encoded (Content-Encoding); only identity is accepted")
        if len(response.body) > BODY_LIMIT:
            raise TiingoError(f"GET {url}: more than {BODY_LIMIT} bytes")
        received = str(len(response.body))
        declared = declared_length(received_headers)
        if declared is not None and count_order(received) < count_order(declared):
            raise TiingoError(
                f"GET {url}: the body ended after {received} of {declared} bytes; run fetch again later"
            )
        return response.body
