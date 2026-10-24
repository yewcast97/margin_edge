"""SEC EDGAR over HTTPS: every request ``fetch`` sends to EDGAR, and the HTTP reading
``earningscalls`` shares.

EDGAR is a public, read-only API with a published fair-access policy: every request
names in ``User-Agent`` whom it is made for (``SEC_USER_AGENT``, a name and an email
address, from the ignored repository-root ``.env``) and stays well below ten requests a
second (``sleep(PACING)`` before every request after a client's first). The value is
checked before any request and never appears in a message, a file or the output.

Requests go only to ``https://www.sec.gov`` and ``https://data.sec.gov``, without
credentials or a port in the URL. No redirect is followed: one anywhere else, or to
plain HTTP, is refused as leaving EDGAR, and one within EDGAR is refused too, because a
document is kept in ``raw/`` at the path built from the URL requested, so a body served
from another URL would be kept as a document it may not be. Bodies are accepted only as
sent (no ``Accept-Encoding`` header is added, and a ``Content-Encoding`` other than
``identity`` is refused), with status 200 and at most a per-request number of bytes:
``urllib_fetch`` reads one byte more than the limit, so an oversized body is detected
without reading it all. A body within the limit but shorter than its ``Content-Length``
is refused as cut short, naming both byte counts: when a server closes the connection
cleanly before the end, http.client's ``read(amt)`` returns what arrived without raising,
and a document in ``raw/`` is never fetched again. ``urllib_fetch`` refuses, as a network
failure, a body that ended before the length http.client framed it by (http.client fails
a chunked body cut short itself);
http.client reads that length from the first value with ``int()``, which also takes a
sign, underscores and spaces other than space and tab. ``get`` refuses a body shorter
than any value of ASCII digits, spaces or tabs around it aside, whichever ``Fetch``
returned it. A value read as a length by neither frames no body; http.client reads such
a body until the close. Every failure is one ``EdgarError`` line naming the URL and the
problem; a status line's reason phrase and a network error's reason are printed escaped,
never the request's headers.

An 8-K's exhibits are found on its filing index page (``index_url``, the accession's
``-index.htm`` in its archive folder), which lists each document of the filing with its
type. ``index_page`` requests it as a document, under the same hosts, pacing, redirect,
encoding and size rules as every other request, with its own limit ``INDEX_LIMIT``; each
exhibit it names is then requested at ``archive_url``, so an exhibit's name passes the
same plain-file-name check as a primary document's.

The HTTP layer is a ``Fetch`` callable, so tests replace it (and ``sleep`` and the clock)
and never reach the network. ``requests`` counts every request a client attempted,
including one that then failed. Conservative choices the contract leaves open: the URL
builders refuse a malformed CIK, accession or primary document with ``ValueError``
instead of building a URL from it; a response header sent more than once is read as its
values joined by ``", "``, so a second ``Content-Encoding`` is never hidden and a body
must reach the largest ``Content-Length`` of ASCII digits among the values (http.client
reads by the first); byte counts are compared as text, so no ``Content-Length`` has too
many digits to read; a redirect that urllib declines before asking where to go (an
unknown scheme, no location) comes back as its status with the reason ``redirect not
followed``; and ``check_user_agent`` accepts only printable ASCII without surrounding
spaces whose last space-separated word is an address with one ``@`` and text on both
sides of it, after a non-empty name.

``Response``, ``Fetch``, ``read_body``, ``lower_headers``, ``declared_length``,
``count_order`` and ``failure_reason`` are public because ``earningscalls`` reads
EarningsCalls.dev's responses by the same rules: a bounded body, header names in lower
case with repeated values joined, byte counts compared as text and a network failure's
reason on one line.
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
from typing import IO, Final, Literal
from urllib.parse import urlsplit

from market_state_research.common.text import printable
from market_state_research.common.times import to_eastern

COMPANY_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
JSON_LIMIT = 20 * 1024 * 1024
DOCUMENT_LIMIT = 50 * 1024 * 1024
INDEX_LIMIT: Final = 20 * 1024 * 1024  # a filing index page: a listing of the filing's documents
TIMEOUT = 60  # seconds per request
PACING = 0.2  # seconds before every request after the first: half EDGAR's ten per second
ALLOWED_HOSTS = ("www.sec.gov", "data.sec.gov")
JSON_ACCEPT = "application/json"
DOCUMENT_ACCEPT = "text/html, text/plain;q=0.9, */*;q=0.1"
MAX_USER_AGENT = 200
USER_AGENT_UNSET = (
    'SEC_USER_AGENT is not set; add SEC_USER_AGENT="Name contact@example.com" to the repository-root .env'
)
USER_AGENT_MALFORMED = (
    'SEC_USER_AGENT must be a name and an email address, such as "Name contact@example.com"'
)
REDIRECT_NOT_FOLLOWED = "redirect not followed"
REDIRECT_WITHIN = "redirect to another EDGAR URL refused; a document is read only from the URL requested"

# Explicit ASCII classes: \d would also match other Unicode digits, which int() accepts.
_CIK = re.compile(r"[0-9]{10}", re.ASCII)
_ACCESSION = re.compile(r"[0-9]{10}-[0-9]{2}-[0-9]{6}", re.ASCII)
_PRIMARY_DOCUMENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,199}", re.ASCII)
_BYTE_COUNT = re.compile(r"[0-9]+", re.ASCII)
_ALLOWED = ", ".join(f"https://{host}" for host in ALLOWED_HOSTS)


class EdgarError(Exception):
    """An EDGAR request failed or was refused; the message is one line without the User-Agent."""


@dataclass(frozen=True)
class Response:
    """What the HTTP layer received: ``headers`` has lower-case names, ``body`` at most limit + 1 bytes."""

    status: int
    reason: str
    headers: Mapping[str, str]
    body: bytes


# (url, headers, limit) -> Response; a network failure raises EdgarError.
Fetch = Callable[[str, Mapping[str, str], int], Response]


@dataclass(frozen=True)
class Fetched:
    """A body EDGAR returned with status 200, and the New York time it arrived."""

    url: str
    fetched_at: datetime
    content_type: str
    body: bytes


def submissions_url(cik: str) -> str:
    """The submissions JSON of the 10-digit, zero-padded ``cik``."""
    if not isinstance(cik, str) or not _CIK.fullmatch(cik):
        raise ValueError("CIK must be 10 ASCII digits")
    return f"https://data.sec.gov/submissions/CIK{cik}.json"


def archive_url(cik: str, accession: str, primary_document: str) -> str:
    """The primary document of one filing in EDGAR's archive.

    Every part is checked first, so nothing that could act as a path or query reaches the URL.
    """
    if not isinstance(cik, str) or not _CIK.fullmatch(cik):
        raise ValueError("CIK must be 10 ASCII digits")
    if not isinstance(accession, str) or not _ACCESSION.fullmatch(accession):
        raise ValueError("accession must be 10, 2 and 6 ASCII digits joined by hyphens")
    if (
        not isinstance(primary_document, str)
        or not _PRIMARY_DOCUMENT.fullmatch(primary_document)
        or ".." in primary_document
    ):
        raise ValueError("primary document must be a plain file name")
    folder = f"{int(cik)}/{accession.replace('-', '')}"
    return f"https://www.sec.gov/Archives/edgar/data/{folder}/{primary_document}"


def index_url(cik: str, accession: str) -> str:
    """The filing index page of one filing, which lists each of its documents with its type.

    Both parts are checked first, as ``archive_url`` checks them and with the same messages.
    The folder is the company's CIK, even when the accession's prefix is a filing agent's.
    """
    if not isinstance(cik, str) or not _CIK.fullmatch(cik):
        raise ValueError("CIK must be 10 ASCII digits")
    if not isinstance(accession, str) or not _ACCESSION.fullmatch(accession):
        raise ValueError("accession must be 10, 2 and 6 ASCII digits joined by hyphens")
    folder = f"{int(cik)}/{accession.replace('-', '')}"
    return f"https://www.sec.gov/Archives/edgar/data/{folder}/{accession}-index.htm"


def allowed_url(url: str) -> bool:
    """Whether ``url`` is printable ASCII, HTTPS and on an allowed host, with no credentials or port."""
    if not isinstance(url, str) or not (url.isascii() and url.isprintable()) or " " in url:
        return False
    parts = urlsplit(url)
    return parts.scheme == "https" and parts.netloc in ALLOWED_HOSTS


def _refused(url: str) -> EdgarError:
    return EdgarError(f"GET {printable(url)}: only HTTPS requests to {_ALLOWED} are allowed")


def check_user_agent(value: str | None) -> str:
    """``value`` when it names a person or organisation and an email address; never echoed."""
    if not value:
        raise EdgarError(USER_AGENT_UNSET)
    name, _, address = value.rpartition(" ")
    local, at, domain = address.partition("@")
    if (
        len(value) > MAX_USER_AGENT
        or not (value.isascii() and value.isprintable())
        or value != value.strip()
        or not name.strip()
        or not (local and at and domain)
        or "@" in domain
    ):
        raise EdgarError(USER_AGENT_MALFORMED)
    return value


class EdgarRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Refuses every redirect urllib would follow: the body must come from the URL requested."""

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
        # The target comes from the server, so it is not printed.
        if not allowed_url(newurl):
            raise EdgarError(
                f"GET {printable(req.full_url)}: HTTP {code} redirect to a URL outside {_ALLOWED} refused"
            )
        raise EdgarError(f"GET {printable(req.full_url)}: HTTP {code} {REDIRECT_WITHIN}")


def _opener() -> urllib.request.OpenerDirector:
    return urllib.request.build_opener(EdgarRedirectHandler())


def lower_headers(message: Message | None) -> dict[str, str]:
    """Header values by lower-case name; a repeated header's values are joined by ``", "``."""
    headers: dict[str, str] = {}
    for name, value in message.items() if message is not None else ():
        key = name.lower()
        headers[key] = f"{headers[key]}, {value}" if key in headers else str(value)
    return headers


def _cut_short(url: str, received: str, declared: str) -> str:
    return f"GET {url}: the body ended after {received} of {declared} bytes; run fetch again"


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


def urllib_fetch(url: str, headers: Mapping[str, str], limit: int) -> Response:
    """GET ``url`` with exactly ``headers`` through urllib, reading at most ``limit + 1`` body bytes.

    An HTTP error status is returned (with an empty body) for the caller to judge; a
    network failure, a timeout and a refused URL or redirect raise ``EdgarError``, and so
    does a body within the limit that ended before the length http.client framed it by.
    """
    if not allowed_url(url):
        raise _refused(url)
    request = urllib.request.Request(url, headers=dict(headers), method="GET")
    try:
        with _opener().open(request, timeout=TIMEOUT) as response:
            status, reason = int(response.status), str(response.reason)
            received = lower_headers(response.headers)
            body = read_body(response, limit)
            # http.client counts its length down as it reads, so what is left was never sent.
            owed: object = getattr(response, "length", None)
    except urllib.error.HTTPError as error:
        with error:
            status = int(error.code)
            # urllib raises a redirect it declined to follow; its message would echo the target.
            reason = REDIRECT_NOT_FOLLOWED if 300 <= status < 400 else str(error.reason)
            return Response(status, reason, lower_headers(error.headers), b"")
    except urllib.error.URLError as error:
        raise EdgarError(f"GET {printable(url)}: {failure_reason(error.reason)}") from None
    except (OSError, http.client.HTTPException) as error:  # TimeoutError is an OSError
        raise EdgarError(f"GET {printable(url)}: {failure_reason(error)}") from None
    # Within the limit, read_body stopped at the end of the body, so a length still owed was cut short.
    if isinstance(owed, int) and owed > 0 and len(body) <= limit:
        raise EdgarError(_cut_short(printable(url), str(len(body)), str(len(body) + owed)))
    return Response(status, reason, received, body)


def _now() -> datetime:
    return to_eastern(datetime.now(UTC))


def _status_problem(url: str, response: Response) -> str:
    status = f"HTTP {response.status}"
    if response.reason:
        status += f" {printable(response.reason)}"
    if response.status == 403:
        return (
            f"GET {url}: {status}; EDGAR refused the request: check SEC_USER_AGENT "
            "(a name and an email address) and EDGAR's fair-access policy"
        )
    if response.status == 429:
        return f"GET {url}: {status}; EDGAR's rate limit: wait ten minutes and run fetch again"
    if 500 <= response.status <= 599:
        return f"GET {url}: {status}; EDGAR is unavailable: wait and run fetch again"
    return f"GET {url}: {status}"


def count_order(digits: str) -> tuple[int, str]:
    """Orders byte counts written without leading zeros as their numbers: more digits, then text."""
    return len(digits), digits


def declared_length(headers: Mapping[str, str]) -> str | None:
    """The largest ``Content-Length`` of ASCII digits, without leading zeros; None without one.

    ``headers`` has lower-case names. A repeated header arrives joined by ``", "``, so every
    value counts; spaces and tabs around a value are not part of it. Any other value is
    left to http.client, by whose length ``urllib_fetch`` refuses a body cut short.
    """
    values = (value.strip(" \t") for value in headers.get("content-length", "").split(","))
    counts = [value.lstrip("0") or "0" for value in values if _BYTE_COUNT.fullmatch(value)]
    return max(counts, key=count_order, default=None)


class EdgarClient:
    """Paced EDGAR requests under one checked ``User-Agent``; see the module docstring."""

    def __init__(
        self,
        user_agent: str | None,
        fetch: Fetch = urllib_fetch,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], datetime] = _now,
    ) -> None:
        self._user_agent = check_user_agent(user_agent)
        self._fetch = fetch
        self._sleep = sleep
        self._clock = clock
        self._requests = 0

    def __repr__(self) -> str:
        return f"EdgarClient(requests={self._requests})"

    @property
    def requests(self) -> int:
        """Requests attempted so far, failed ones included."""
        return self._requests

    def get(self, url: str, accept: str, limit: int) -> Fetched:
        """GET ``url`` (status 200, identity encoding, at most ``limit`` bytes) or raise ``EdgarError``.

        A body is also refused as cut short when it is shorter than a ``Content-Length`` of
        ASCII digits, whichever ``Fetch`` returned it.
        """
        if not allowed_url(url):
            raise _refused(url)
        if self._requests:
            self._sleep(PACING)
        self._requests += 1
        response = self._fetch(url, {"User-Agent": self._user_agent, "Accept": accept}, limit)
        fetched_at = to_eastern(self._clock(), "fetched_at")
        headers = {name.lower(): value for name, value in response.headers.items()}
        if response.status != 200:
            raise EdgarError(_status_problem(url, response))
        if headers.get("content-encoding", "identity").strip().lower() != "identity":
            raise EdgarError(f"GET {url}: the body is encoded (Content-Encoding); only identity is accepted")
        if len(response.body) > limit:
            raise EdgarError(f"GET {url}: more than {limit} bytes")
        received = str(len(response.body))
        declared = declared_length(headers)
        if declared is not None and count_order(received) < count_order(declared):
            raise EdgarError(_cut_short(url, received, declared))
        return Fetched(url, fetched_at, headers.get("content-type", ""), response.body)

    def company_tickers(self) -> Fetched:
        return self.get(COMPANY_TICKERS_URL, JSON_ACCEPT, JSON_LIMIT)

    def submissions(self, cik: str) -> Fetched:
        return self.get(submissions_url(cik), JSON_ACCEPT, JSON_LIMIT)

    def document(self, url: str) -> Fetched:
        return self.get(url, DOCUMENT_ACCEPT, DOCUMENT_LIMIT)

    def index_page(self, url: str) -> Fetched:
        return self.get(url, DOCUMENT_ACCEPT, INDEX_LIMIT)


def decode_document(body: bytes) -> tuple[str, Literal["utf-8", "latin-1"]]:
    """The text of a filing document and its encoding: strict UTF-8, else Latin-1.

    Latin-1 maps every byte to one character, so both decodings re-encode to ``body``.
    """
    try:
        return body.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        return body.decode("latin-1"), "latin-1"
