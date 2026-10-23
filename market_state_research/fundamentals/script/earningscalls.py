"""EarningsCalls.dev over HTTPS: a ticker's earnings calls and each call's transcript, read strictly.

``fetch`` reads the transcripts of the issuer's earnings calls from EarningsCalls.dev
under the user's own key (``EARNINGSCALLS_API``, from the ignored repository-root
``.env``), which travels only in the ``X-API-Key`` header. The key is checked before any
request and never appears in a message, a file, the output or a representation: a
client's ``repr`` names its request count alone, and a message that repeats the
provider's own words has the key replaced first. Two endpoints are read, both ``GET``:

- ``/api/v1/earnings/?ticker={T}&event_type=earnings&country=US&limit=100&sort=date_desc&page={N}``
  (``events_url``), the ticker's earnings calls, newest first, one page of at most
  ``PAGE_SIZE`` calls each; ``fetch`` keeps every page of one request verbatim as one
  *capture* (``documents``), which ``check_capture`` reads;
- ``/api/v1/transcripts/{id}/components`` (``transcript_url``), one call's transcript as
  the provider structures it: a header and the call's turns in order, each with its
  speaker's name and role; ``fetch`` keeps it verbatim, and ``parse_transcript`` reads it
  against the call the capture lists.

Requests go only to ``https://earningscalls.dev``, without credentials or a port in the
URL, paced ``PACING`` seconds apart (the plan allows 20 a minute), and no redirect is
followed. Bodies are read by ``client``'s rules for EDGAR's: status 200 only, a
``Content-Encoding`` other than ``identity`` refused, at most ``BODY_LIMIT`` bytes
(``urllib_fetch`` reads one byte more than the limit, so an oversized body is detected
without reading it all), and a body shorter than its ``Content-Length`` refused as cut
short, whether http.client framed it by that length or the value is one of ASCII digits.
HTTP 429 is the provider's request limit (3,000 requests in the plan's month, 20 a
minute), raised as ``LimitReached``, which ends the run's requests to the provider
cleanly; every other failure is one ``EarningsCallsError`` line naming the URL and the
problem, with the next step. Only a 429's own message is repeated (escaped, cut at
``SHOWN`` characters, the key removed), since it names when the limit resets.

Both bodies are read as a strict subset of what the provider serves, verified live on
2026-10-19 (``AGENTS.md``): UTF-8 JSON without a repeated key, ``NaN`` or ``Infinity``,
every value read of its type and grammar, every other key ignored. A calls page holds
``data`` (the calls: ``id``, ``event_type`` ``earnings``, ``event_date_time`` in UTC as
``YYYY-MM-DDTHH:MM:SS[.fff]Z``, ``stock_symbol``, ``country`` ``US``, ``issuer_id``,
``fiscal_year``, ``fiscal_quarter``), ``pagination`` (``page``, ``limit``, ``total``,
``total_pages``), ``ambiguous`` and ``issuer_count``; a capture is pages 1 to
``total_pages`` (page 1 alone when it lists no call) of one ``total``, every call's
``stock_symbol`` the ticker's, of one issuer, its ids unique, and not ``ambiguous``. A
transcript holds ``data.event_type`` ``earnings``, ``data.duration_seconds`` (a whole
number from 0, null or absent), ``data.header`` (``title``, ``event_date_time``, the instant
the capture lists for the call) and ``data.components`` (the turns: ``order`` from 0 without
a gap, ``speaker_name``, ``speaker_type`` one of ``ROLES``, ``text``). Every problem is one
``ValueError`` line naming the field and the rule, never a value read.

The derived text of a call (``call_text``) is read in block mode: per turn, in order, a
heading line ``{speaker_name} ({speaker_type})``, then the turn's text, whose ``\\r\\n``
paragraph breaks become line breaks, normalised as plain text (``text.plain_text``).
``CallText.turns`` gives each turn's words as offsets into it (``Turn``), which
``check`` holds every call quote to.

The HTTP layer is a ``client.Fetch`` callable, so tests replace it (and ``sleep`` and
the clock) and never reach the network. ``requests`` counts every request a client
attempted, including one that then failed.
"""

import http.client
import json
import re
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import IO, Annotated, Final, Literal
from urllib.parse import urlsplit

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, ValidationError

from market_state_research.common.text import printable
from market_state_research.common.times import to_eastern

from .client import (
    REDIRECT_NOT_FOLLOWED,
    Fetch,
    Response,
    count_order,
    declared_length,
    failure_reason,
    lower_headers,
    read_body,
)
from .text import normalise, plain_text

HOST: Final = "earningscalls.dev"
API: Final = f"https://{HOST}/api/v1"
API_KEY_SETTING: Final = "EARNINGSCALLS_API"
PAGE_SIZE: Final = 100  # calls per page, the most the provider serves
MAX_PAGES: Final = 20  # pages of one capture: 2,000 calls, far more than any issuer has
BODY_LIMIT: Final = 8 * 1024 * 1024  # bytes of a page or a transcript
ERROR_LIMIT: Final = 4096  # bytes of a 429's body read for its message
TIMEOUT: Final = 60  # seconds per request
PACING: Final = 3.1  # seconds before every request after the first: under 20 a minute
MAX_API_KEY: Final = 200
MAX_ID: Final = 10**12
MAX_NAME: Final = 200
MAX_TITLE: Final = 300
SHOWN: Final = 200  # characters of the provider's message for a 429
ROLES: Final = ("executive", "analyst", "operator", "attendee", "shareholder", "unknown")
ACCEPT: Final = "application/json"

API_KEY_UNSET: Final = (
    f'{API_KEY_SETTING} is not set; add {API_KEY_SETTING}="..." to the repository-root .env'
)
API_KEY_MALFORMED: Final = f"{API_KEY_SETTING} must be printable ASCII without spaces"
EVENT_TIME = "event_date_time must be a UTC time written YYYY-MM-DDTHH:MM:SS[.fff]Z"

Role = Literal["executive", "analyst", "operator", "attendee", "shareholder", "unknown"]

# Explicit ASCII classes; [!-~] is printable ASCII without the space.
_API_KEY = re.compile(r"[!-~]+", re.ASCII)
_EVENT_TIME = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?Z", re.ASCII)
_ISSUER = re.compile(r"[0-9a-f]{32}", re.ASCII)
_RETRY_AFTER = re.compile(r"[0-9]{1,6}", re.ASCII)
_KEY_SHOWN = "<key>"


class EarningsCallsError(Exception):
    """An EarningsCalls.dev request failed or was refused; the message is one line without the key."""


class LimitReached(EarningsCallsError):
    """HTTP 429: the provider's request limit is reached; no request to it can succeed for now."""


@dataclass(frozen=True)
class Fetched:
    """A body the provider returned with status 200, and the New York time it arrived."""

    url: str
    fetched_at: datetime
    body: bytes = field(repr=False)


def events_url(ticker: str, page: int) -> str:
    """Page ``page`` of the earnings calls the provider lists for ``ticker``, newest first.

    ``ticker`` must already be a normalised symbol (``common.text.ticker_symbol``), which
    holds no character that could act as a query.
    """
    if isinstance(page, bool) or not isinstance(page, int) or not 1 <= page <= MAX_PAGES:
        raise ValueError(f"a page of the calls list is a number from 1 to {MAX_PAGES}")
    return (
        f"{API}/earnings/?ticker={ticker}&event_type=earnings&country=US&limit={PAGE_SIZE}"
        f"&sort=date_desc&page={page}"
    )


def transcript_url(call_id: int) -> str:
    """The transcript of the call ``call_id``: its header and turns."""
    if isinstance(call_id, bool) or not isinstance(call_id, int) or not 1 <= call_id <= MAX_ID:
        raise ValueError(f"a call id is a whole number from 1 to {MAX_ID}")
    return f"{API}/transcripts/{call_id}/components"


def check_api_key(value: str | None) -> str:
    """``value`` when it can be an EarningsCalls.dev key: printable ASCII without spaces; never echoed."""
    if not value:
        raise EarningsCallsError(API_KEY_UNSET)
    if not isinstance(value, str) or len(value) > MAX_API_KEY or not _API_KEY.fullmatch(value):
        raise EarningsCallsError(API_KEY_MALFORMED)
    return value


def allowed_url(url: str) -> bool:
    """Whether ``url`` is printable ASCII, HTTPS and on ``HOST``, with no credentials or port."""
    if not isinstance(url, str) or not (url.isascii() and url.isprintable()) or " " in url:
        return False
    parts = urlsplit(url)
    return parts.scheme == "https" and parts.netloc == HOST


def _refused(url: str) -> EarningsCallsError:
    return EarningsCallsError(f"GET {printable(url)}: only HTTPS requests to https://{HOST} are allowed")


def _cut_short(url: str, received: str, declared: str) -> str:
    return f"GET {url}: the body ended after {received} of {declared} bytes; run fetch again"


class EarningsCallsRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Refuses every redirect urllib would follow: the provider is read only at the URL requested."""

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
        raise EarningsCallsError(f"GET {printable(req.full_url)}: HTTP {code} {REDIRECT_NOT_FOLLOWED}")


def _opener() -> urllib.request.OpenerDirector:
    return urllib.request.build_opener(EarningsCallsRedirectHandler())


def urllib_fetch(url: str, headers: Mapping[str, str], limit: int) -> Response:
    """GET ``url`` with exactly ``headers`` through urllib, reading at most ``limit + 1`` body bytes.

    An HTTP error status is returned for the client to judge, with an empty body except a
    429's, of which at most ``ERROR_LIMIT`` bytes are read; a network failure, a timeout
    and a refused URL or redirect raise ``EarningsCallsError``, and so does a body within
    the limit that ended before the length http.client framed it by.
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
            told = b""
            if status == 429:
                try:
                    told = read_body(error, ERROR_LIMIT)[:ERROR_LIMIT]
                except (OSError, http.client.HTTPException):
                    told = b""  # the message is a courtesy; the status says enough
            return Response(status, reason, lower_headers(error.headers), told)
    except urllib.error.URLError as error:
        raise EarningsCallsError(f"GET {printable(url)}: {failure_reason(error.reason, TIMEOUT)}") from None
    except (OSError, http.client.HTTPException) as error:  # TimeoutError is an OSError
        raise EarningsCallsError(f"GET {printable(url)}: {failure_reason(error, TIMEOUT)}") from None
    # Within the limit, read_body stopped at the end of the body, so a length still owed was cut short.
    if isinstance(owed, int) and owed > 0 and len(body) <= limit:
        raise EarningsCallsError(_cut_short(printable(url), str(len(body)), str(len(body) + owed)))
    return Response(status, reason, received, body)


def _now() -> datetime:
    return to_eastern(datetime.now(UTC))


def _said(body: bytes, api_key: str) -> str | None:
    """The provider's own message in a 429's JSON body (``message`` or ``error``), the key
    removed, escaped and cut at ``SHOWN`` characters; None without one."""
    try:
        value = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError):
        return None
    if not isinstance(value, dict):
        return None
    for name in ("message", "error"):
        text = value.get(name)
        if isinstance(text, str) and text.strip():
            return printable(text.replace(api_key, _KEY_SHOWN))[:SHOWN]
    return None


def _status_problem(url: str, response: Response) -> str:
    status = f"GET {url}: HTTP {response.status}"
    if response.reason:
        status += f" {printable(response.reason)}"
    if response.status == 401:
        return f"{status}; EarningsCalls.dev refused the key: check {API_KEY_SETTING}"
    if response.status == 403:
        return (
            f"{status}; EarningsCalls.dev refused the request: the key's plan does not include it "
            "(full transcripts need the Pro plan)"
        )
    if response.status == 404:
        return f"{status}; EarningsCalls.dev serves nothing at this address"
    if 500 <= response.status <= 599:
        return f"{status}; EarningsCalls.dev is unavailable: wait and run fetch again"
    return status


class EarningsCallsClient:
    """Paced EarningsCalls.dev requests under one checked key; see the module docstring."""

    def __init__(
        self,
        api_key: str | None,
        fetch: Fetch = urllib_fetch,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], datetime] = _now,
    ) -> None:
        self._api_key = check_api_key(api_key)
        self._fetch = fetch
        self._sleep = sleep
        self._clock = clock
        self._requests = 0

    def __repr__(self) -> str:
        return f"EarningsCallsClient(requests={self._requests})"

    @property
    def requests(self) -> int:
        """Requests attempted so far, failed ones included."""
        return self._requests

    def get(self, url: str) -> Fetched:
        """GET ``url`` (status 200, identity encoding, at most ``BODY_LIMIT`` bytes), or raise
        ``LimitReached`` for HTTP 429 and ``EarningsCallsError`` for any other failure.

        A body is also refused as cut short when it is shorter than a ``Content-Length`` of
        ASCII digits, whichever ``Fetch`` returned it.
        """
        if not allowed_url(url):
            raise _refused(url)
        if self._requests:
            self._sleep(PACING)
        self._requests += 1
        response = self._fetch(url, {"X-API-Key": self._api_key, "Accept": ACCEPT}, BODY_LIMIT)
        fetched_at = to_eastern(self._clock(), "fetched_at")
        headers = {name.lower(): value for name, value in response.headers.items()}
        if response.status == 429:
            wait = headers.get("retry-after", "").strip()
            after = f"; retry after {wait} seconds" if _RETRY_AFTER.fullmatch(wait) else ""
            said = _said(response.body, self._api_key)
            told = f"; the provider says: {said}" if said else ""
            raise LimitReached(
                f"GET {url}: HTTP 429; EarningsCalls.dev's request limit is reached (the key's 3,000 "
                f"requests a month or 20 a minute){after}{told}; run fetch again once it resets"
            )
        if response.status != 200:
            raise EarningsCallsError(_status_problem(url, response))
        if headers.get("content-encoding", "identity").strip().lower() != "identity":
            raise EarningsCallsError(
                f"GET {url}: the body is encoded (Content-Encoding); only identity is accepted"
            )
        if len(response.body) > BODY_LIMIT:
            raise EarningsCallsError(f"GET {url}: more than {BODY_LIMIT} bytes")
        received = str(len(response.body))
        declared = declared_length(headers)
        if declared is not None and count_order(received) < count_order(declared):
            raise EarningsCallsError(_cut_short(url, received, declared))
        return Fetched(url, fetched_at, response.body)

    def events_page(self, ticker: str, page: int) -> Fetched:
        return self.get(events_url(ticker, page))

    def transcript(self, call_id: int) -> Fetched:
        return self.get(transcript_url(call_id))


# --------------------------------------------------------------------------- the bodies


class _NotJson(Exception):
    """A JSON body the strict reader refuses although ``json`` would accept it."""


def _unique_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise _NotJson("an object repeats a key")
        value[key] = item
    return value


def _reject_constant(name: str) -> object:
    raise _NotJson(f"{name} is not JSON")


def load_json(body: bytes) -> object:
    """``body`` as strict UTF-8 JSON: no repeated key, ``NaN`` or ``Infinity``; else ``ValueError``."""
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError:
        raise ValueError("the body is not UTF-8") from None
    try:
        return json.loads(text, object_pairs_hook=_unique_keys, parse_constant=_reject_constant)
    except json.JSONDecodeError as error:
        raise ValueError(f"invalid JSON: {error.msg} (line {error.lineno}, column {error.colno})") from None
    except _NotJson as error:
        raise ValueError(f"invalid JSON: {error}") from None
    except RecursionError:
        raise ValueError("invalid JSON: nested too deeply") from None
    except ValueError:  # an integer longer than Python's integer-string conversion limit
        raise ValueError("invalid JSON: a number is too long") from None


def event_time(value: str) -> datetime:
    """A provider time (``YYYY-MM-DDTHH:MM:SS[.fff]Z``, UTC) as the New York instant it names."""
    if not _EVENT_TIME.fullmatch(value):
        raise ValueError(EVENT_TIME)
    try:
        return to_eastern(datetime.fromisoformat(value), "event_date_time")
    except (ValueError, OverflowError):
        raise ValueError(EVENT_TIME) from None


def _event_time(value: str) -> str:
    event_time(value)
    return value


def _named(value: str) -> str:
    if not value.strip() or not value.isprintable():
        raise ValueError("must be printable text with a character that is not whitespace")
    return value


def _issuer(value: str | None) -> str | None:
    if value is not None and not _ISSUER.fullmatch(value):
        raise ValueError("must be 32 lowercase hex digits or null")
    return value


_CONFIG = ConfigDict(strict=True, extra="ignore", frozen=True, hide_input_in_errors=True)
Count = Annotated[int, Field(ge=0)]
EventTime = Annotated[str, AfterValidator(_event_time)]


class _Event(BaseModel):
    model_config = _CONFIG

    id: Annotated[int, Field(ge=1, le=MAX_ID)]
    event_type: Literal["earnings"]
    event_date_time: EventTime
    stock_symbol: str
    country: Literal["US"]
    issuer_id: Annotated[str | None, AfterValidator(_issuer)]
    fiscal_year: Annotated[int, Field(ge=1900, le=2999)] | None
    fiscal_quarter: Annotated[int, Field(ge=1, le=4)] | None


class _Pagination(BaseModel):
    model_config = _CONFIG

    page: Annotated[int, Field(ge=1, le=MAX_PAGES)]
    limit: Literal[100]
    total: Count
    total_pages: Annotated[int, Field(ge=0, le=MAX_PAGES)]


class _EventsPage(BaseModel):
    model_config = _CONFIG

    data: list[_Event]  # strict mode reads a JSON array as a list only
    pagination: _Pagination
    ambiguous: bool
    issuer_count: Count


class _Header(BaseModel):
    model_config = _CONFIG

    title: Annotated[str, Field(max_length=MAX_TITLE), AfterValidator(_named)]
    event_date_time: EventTime


class _Component(BaseModel):
    model_config = _CONFIG

    order: Count
    speaker_name: Annotated[str, Field(max_length=MAX_NAME), AfterValidator(_named)]
    speaker_type: Role
    text: str


class _TranscriptData(BaseModel):
    model_config = _CONFIG

    event_type: Literal["earnings"]
    duration_seconds: Count | None = None
    header: _Header
    components: Annotated[list[_Component], Field(min_length=1)]


class _TranscriptBody(BaseModel):
    model_config = _CONFIG

    data: _TranscriptData


def _details(error: ValidationError) -> str:
    """Every error as ``location: message``, in order, on one line; never the input."""
    return "; ".join(
        f"{printable('.'.join(map(str, item['loc'])))}: {printable(item['msg'])}"
        if item["loc"]
        else printable(item["msg"])
        for item in error.errors(include_input=False, include_context=False, include_url=False)
    )


def _validated[Model: BaseModel](model: type[Model], body: bytes, what: str) -> Model:
    try:
        return model.model_validate(load_json(body))
    except ValueError as error:
        if isinstance(error, ValidationError):
            raise ValueError(f"{what}: {_details(error)}") from None
        raise ValueError(f"{what}: {error}") from None


@dataclass(frozen=True)
class CallEvent:
    """One earnings call the provider lists: its id, the New York instant it began and the
    fiscal year and quarter the provider read from its title (None when it read none)."""

    id: int
    at: datetime
    fiscal_year: int | None = None
    fiscal_quarter: int | None = None

    @property
    def day(self) -> date:
        """The call's New York date, which Rule B places it by."""
        return self.at.date()

    def describe(self) -> dict[str, object]:
        return {
            "id": self.id,
            "date": self.day.isoformat(),
            "fiscal_year": self.fiscal_year,
            "fiscal_quarter": self.fiscal_quarter,
        }


@dataclass(frozen=True)
class EventsPage:
    """One page of a ticker's calls list, read strictly."""

    page: int
    total: int
    total_pages: int
    ambiguous: bool
    issuer_count: int
    calls: tuple[CallEvent, ...]
    symbols: frozenset[str]
    issuers: frozenset[str]


def parse_events_page(body: bytes) -> EventsPage:
    """One calls page read as the strict subset of the provider's body (module docstring)."""
    page = _validated(_EventsPage, body, "calls list")
    return EventsPage(
        page=page.pagination.page,
        total=page.pagination.total,
        total_pages=page.pagination.total_pages,
        ambiguous=page.ambiguous,
        issuer_count=page.issuer_count,
        calls=tuple(
            CallEvent(row.id, event_time(row.event_date_time), row.fiscal_year, row.fiscal_quarter)
            for row in page.data
        ),
        symbols=frozenset(row.stock_symbol for row in page.data),
        issuers=frozenset(row.issuer_id for row in page.data if row.issuer_id is not None),
    )


class Ambiguous(ValueError):
    """The provider's symbol names several issuers, so their calls cannot be told apart."""


def _ambiguous(ticker: str, count: int) -> Ambiguous:
    return Ambiguous(
        f"EarningsCalls.dev lists {count} issuers for {ticker} (ambiguous): their calls cannot be told apart"
    )


def check_issuer(ticker: str, page: EventsPage) -> None:
    """Raise ``Ambiguous`` when ``page`` says the ticker's symbol names more than one issuer."""
    if page.ambiguous or page.issuer_count > 1 or len(page.issuers) > 1:
        raise _ambiguous(ticker, max(2, page.issuer_count, len(page.issuers)))


def check_capture(ticker: str, pages: Sequence[EventsPage]) -> tuple[CallEvent, ...]:
    """The calls of one capture, ``pages`` in page order, newest first as the provider lists them.

    The pages are 1 to ``total_pages`` (page 1 alone when no call is listed), each naming
    its own number and the same ``total`` and ``total_pages``, every page but the last
    full (``PAGE_SIZE`` calls); every call's ``stock_symbol`` is ``ticker``, all of one
    issuer, without a repeated id. A list that is ``ambiguous`` or counts more than one
    issuer raises ``Ambiguous`` (``check_issuer``); any other problem ``ValueError``,
    naming the page.
    """
    if not pages:
        raise ValueError("a calls capture holds at least its first page")
    first = pages[0]
    for page in pages:
        check_issuer(ticker, page)
    expected = max(1, first.total_pages)
    if first.total_pages != -(-first.total // PAGE_SIZE):  # whole pages, rounded up
        raise ValueError(f"calls list page 1: total_pages does not fit a total of {first.total} calls")
    if len(pages) != expected:
        count = f"{len(pages)} page" if len(pages) == 1 else f"{len(pages)} pages"
        total = f"its total of {first.total} calls fills {expected}"
        raise ValueError(f"the calls capture holds {count}; {total}")
    calls: list[CallEvent] = []
    issuers: set[str] = set()
    for number, page in enumerate(pages, start=1):
        where = f"calls list page {number}"
        if page.page != number:
            raise ValueError(f"{where}: pagination.page is not {number}")
        if (page.total, page.total_pages) != (first.total, first.total_pages):
            raise ValueError(f"{where}: total or total_pages differs from page 1's")
        held = max(0, min(PAGE_SIZE, first.total - (number - 1) * PAGE_SIZE))
        if len(page.calls) != held:
            raise ValueError(f"{where} holds {len(page.calls)} calls; its total names {held}")
        if page.symbols - {ticker}:
            raise ValueError(f"{where}: a call's stock_symbol is not {ticker}")
        issuers |= page.issuers
        calls.extend(page.calls)
    if len(issuers) > 1:
        raise _ambiguous(ticker, len(issuers))
    if len({call.id for call in calls}) != len(calls):
        raise ValueError("the calls capture lists one call id twice")
    return tuple(calls)


@dataclass(frozen=True)
class TranscriptTurn:
    """One turn of a call as the provider gives it: its speaker, their role and the words."""

    speaker: str
    role: Role
    text: str


@dataclass(frozen=True)
class Transcript:
    """A call's transcript, read strictly: its title, its time, its turns in order and the
    duration the provider gives (None where it gives none)."""

    title: str
    at: datetime
    turns: tuple[TranscriptTurn, ...]
    duration_seconds: int | None = None


def parse_transcript(body: bytes, event: CallEvent) -> Transcript:
    """The transcript ``body`` of the call ``event``, read as the strict subset of the provider's
    body (module docstring); its header must name the instant the capture lists for the call."""
    data = _validated(_TranscriptBody, body, "transcript").data
    orders = [component.order for component in data.components]
    if orders != list(range(len(orders))):
        raise ValueError("transcript: data.components must be in order from 0 without a gap")
    at = event_time(data.header.event_date_time)
    if at != event.at:
        raise ValueError("transcript: data.header.event_date_time is not the time the calls list gives")
    return Transcript(
        title=data.header.title,
        at=at,
        turns=tuple(
            TranscriptTurn(component.speaker_name, component.speaker_type, component.text)
            for component in data.components
        ),
        duration_seconds=data.duration_seconds,
    )


@dataclass(frozen=True)
class Turn:
    """One speaker's turn in a call document's derived text: the offsets of its words (its
    heading line left out), the speaker's name as the heading writes it and the speaker's
    role as the transcript provider gives it (``executive``, ``analyst``, ``operator`` ...)."""

    start: int
    end: int
    speaker: str
    role: str

    @property
    def heading(self) -> str:
        """The heading line the derived text writes before the turn's words."""
        return f"{self.speaker} ({self.role})"


@dataclass(frozen=True)
class CallText:
    """A call's derived text and, per turn, its words' offsets in it (``Turn``)."""

    text: str
    turns: tuple[Turn, ...]


def heading(turn: TranscriptTurn) -> str:
    """A turn's heading line as the derived text writes it: ``{speaker_name} ({speaker_type})``."""
    return plain_text(f"{turn.speaker} ({turn.role})").removesuffix("\n")


def call_text(transcript: Transcript) -> CallText:
    """The derived text of a call: per turn, its heading line, then its text as plain text.

    Each part is normalised by itself (``text.plain_text``), so the text is the plain text
    of all of them joined by line breaks, and a turn's words are a span of it.
    """
    parts: list[str] = []
    turns: list[Turn] = []
    offset = 0
    for turn in transcript.turns:
        title = heading(turn) + "\n"
        words = plain_text(turn.text)
        start = offset + len(title)
        parts.extend([title, words])
        offset = start + len(words)
        # The words' span ends before their last line break; a turn without words has none.
        turns.append(Turn(start, max(start, offset - 1), normalise(turn.speaker), turn.role))
    return CallText("".join(parts), tuple(turns))
