"""EODHD's HTTP layer: the key, the URLs, the statuses and the bodies accepted."""

import pytest

from market_state_research.stock_iv_regime.script.client import (
    API_KEY_MALFORMED,
    API_KEY_UNSET,
    PACING,
    PAGE_LIMIT_BYTES,
    BudgetSpent,
    EodhdClient,
    EodhdError,
    QuotaExceeded,
    Response,
    allowed_url,
    check_api_key,
    declared_length,
    redact,
)

from .fake_eodhd import Sleeps
from .support import CANARY, NOW

URL = "https://eodhd.com/api/mp/unicornbay/options/contracts?filter%5Bunderlying_symbol%5D=TEST"


class Scripted:
    """A Fetch answering each request with the next scripted response, recording what it was sent."""

    def __init__(self, *responses: Response) -> None:
        self.responses = list(responses)
        self.sent: list[tuple[str, dict[str, str], int]] = []

    def __call__(self, url, headers, limit):
        self.sent.append((url, dict(headers), limit))
        return self.responses.pop(0)


def ok(body: bytes = b"{}", **headers: str) -> Response:
    return Response(200, "OK", headers, body)


def client(fetch, sleep=None, budget=None) -> EodhdClient:
    return EodhdClient(CANARY, fetch=fetch, sleep=sleep or Sleeps(), clock=lambda: NOW, budget=budget)


@pytest.mark.parametrize(
    ("value", "message"),
    [
        (None, API_KEY_UNSET),
        ("", API_KEY_UNSET),
        ("short", API_KEY_MALFORMED),
        ("has space here", API_KEY_MALFORMED),
        ("a&b=c12345678", API_KEY_MALFORMED),
    ],
)
def test_check_api_key_refuses_without_echoing(value, message):
    with pytest.raises(EodhdError) as error:
        check_api_key(value)
    assert str(error.value) == message


def test_check_api_key_accepts_url_safe_text():
    assert check_api_key("65f1a2b3c4d5e6.12345678") == "65f1a2b3c4d5e6.12345678"


@pytest.mark.parametrize(
    ("url", "allowed"),
    [
        (URL, True),
        ("http://eodhd.com/api/mp/unicornbay/options/eod", False),
        ("https://eodhd.com:443/api/mp/unicornbay/options/eod", False),
        ("https://user@eodhd.com/api/mp/unicornbay/options/eod", False),
        ("https://eodhd.com/api/eod/AAPL.US", False),
        ("https://evil.example/api/mp/unicornbay/options/eod", False),
        (URL + "&api_token=x", False),
        (URL + "#fragment", False),
        (URL + " ", False),
    ],
)
def test_allowed_url(url, allowed):
    assert allowed_url(url) is allowed


def test_the_key_travels_only_at_send_time():
    fetch = Scripted(ok(b"body"))
    assert client(fetch).get(URL) == b"body"
    ((sent, headers, limit),) = fetch.sent
    assert sent == URL + "&api_token=" + CANARY
    assert headers == {"Accept": "application/json"}
    assert limit == PAGE_LIMIT_BYTES


def test_requests_are_paced_and_counted():
    sleeps = Sleeps()
    eodhd = client(Scripted(ok(), ok(), ok()), sleeps)
    for _ in range(3):
        eodhd.get(URL)
    assert (eodhd.requests, sleeps.calls) == (3, [PACING, PACING])
    assert repr(eodhd) == "EodhdClient(requests=3)"


def test_a_url_with_a_token_is_refused():
    fetch = Scripted()
    with pytest.raises(EodhdError, match="only token-free HTTPS URLs"):
        client(fetch).get(URL + "&api_token=" + CANARY)
    assert fetch.sent == []


def test_the_budget_stops_before_sending():
    eodhd = client(Scripted(ok(), ok()), budget=2)
    eodhd.get(URL)
    eodhd.get(URL)
    with pytest.raises(BudgetSpent, match="the run's budget of 2 requests is spent"):
        eodhd.get(URL)
    assert eodhd.requests == 2


def test_402_is_the_daily_quota():
    with pytest.raises(QuotaExceeded, match="100,000 API calls per rolling 24 hours"):
        client(Scripted(Response(402, "Payment Required", {}, b""))).get(URL)


@pytest.mark.parametrize(
    ("status", "message"),
    [
        (401, "HTTP 401 Unauthorized; EODHD refused the key: check EODHD_API"),
        (403, "HTTP 403 Forbidden; EODHD refused the request: the account needs the marketplace product"),
        (500, "HTTP 500 Server Error; EODHD is unavailable: wait and run fetch again"),
        (422, "HTTP 422 Unprocessable Content"),
    ],
)
def test_statuses(status, message):
    reasons = {401: "Unauthorized", 403: "Forbidden", 500: "Server Error", 422: "Unprocessable Content"}
    with pytest.raises(EodhdError) as error:
        client(Scripted(Response(status, reasons[status], {}, b""))).get(URL)
    assert message in str(error.value)
    assert CANARY not in str(error.value)


def test_429_waits_once_then_retries():
    sleeps = Sleeps()
    fetch = Scripted(Response(429, "Too Many Requests", {"Retry-After": "7"}, b""), ok(b"later"))
    assert client(fetch, sleeps).get(URL) == b"later"
    assert sleeps.calls == [7, PACING]


def test_a_second_429_fails_and_long_waits_are_capped():
    sleeps = Sleeps()
    fetch = Scripted(
        Response(429, "Too Many Requests", {"Retry-After": "3600"}, b""),
        Response(429, "Too Many Requests", {}, b""),
    )
    with pytest.raises(EodhdError, match="rate limit of requests per minute"):
        client(fetch, sleeps).get(URL)
    assert sleeps.calls == [60, PACING]


def test_encoded_oversized_and_cut_short_bodies_are_refused():
    with pytest.raises(EodhdError, match="encoded"):
        client(Scripted(ok(b"x", **{"Content-Encoding": "gzip"}))).get(URL)
    with pytest.raises(EodhdError, match="more than"):
        client(Scripted(ok(b"x" * (PAGE_LIMIT_BYTES + 1)))).get(URL)
    with pytest.raises(EodhdError, match="the body ended after 3 of 10 bytes"):
        client(Scripted(ok(b"abc", **{"Content-Length": "10"}))).get(URL)


def test_declared_length_takes_the_largest_value():
    assert declared_length({"content-length": "10, 012"}) == "12"
    assert declared_length({"content-length": "ten"}) is None


def test_redact():
    assert redact(f"failed for {CANARY}", CANARY) == "failed for <EODHD_API>"
