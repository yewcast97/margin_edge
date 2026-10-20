"""Tiingo's client: the key-free URLs, the key in the header only, statuses and bodies."""

from datetime import date

import pytest

from market_state_research.stock_iv_regime.script.client import Response, TransportError
from market_state_research.stock_iv_regime.script.tiingo import (
    BODY_LIMIT,
    NotCovered,
    Stopped,
    TiingoClient,
    TiingoError,
    allowed_url,
    check_api_key,
    prices_url,
    redact,
)

from .fake_tiingo import FakeTiingo
from .support import NOW, TICKER, TIINGO_CANARY, rising

URL = "https://api.tiingo.com/tiingo/daily/TEST/prices?startDate=2026-10-15&endDate=2026-10-16"


def answering(status=200, body=b"[]", headers=None):
    seen = []

    def fetch(url, sent, limit):
        seen.append((url, dict(sent), limit))
        return Response(status, "Reason", headers or {}, body)

    return seen, TiingoClient(TIINGO_CANARY, fetch=fetch, clock=lambda: NOW)


def test_prices_url_is_key_free():
    assert prices_url(TICKER, date(2026, 10, 15), date(2026, 10, 16)) == URL
    assert allowed_url(URL)


@pytest.mark.parametrize(
    "url",
    [
        URL + "&token=x",
        URL.replace("https://", "http://"),
        URL.replace("api.tiingo.com", "api.tiingo.com:443"),
        URL.replace("api.tiingo.com", "user@api.tiingo.com"),
        URL.replace("/prices", "/meta"),
        URL.replace("/TEST/", "/test/"),
        URL + "#x",
        URL.replace("TEST", "TE ST"),
    ],
)
def test_other_urls_are_refused(url):
    assert not allowed_url(url)
    seen, client = answering()
    with pytest.raises(TiingoError, match="only key-free HTTPS URLs"):
        client.get(url)
    assert seen == [] and client.requests == 0


@pytest.mark.parametrize(
    ("value", "message"),
    [
        (None, "TIINGO_API is not set"),
        ("", "TIINGO_API is not set"),
        ("short", "8 to 200"),
        ("a b c d e f", "8 to 200"),
    ],
)
def test_check_api_key_refuses_without_echoing(value, message):
    with pytest.raises(TiingoError, match=message) as caught:
        check_api_key(value)
    assert value is None or value == "" or value not in str(caught.value)


def test_the_key_travels_only_in_the_header():
    seen, client = answering()
    assert client.get(URL) == b"[]"
    ((url, headers, limit),) = seen
    assert url == URL and TIINGO_CANARY not in url
    assert headers == {"Accept": "application/json", "Authorization": f"Token {TIINGO_CANARY}"}
    assert limit == BODY_LIMIT and client.requests == 1
    assert TIINGO_CANARY not in repr(client)


@pytest.mark.parametrize(
    ("status", "kind", "message"),
    [
        (404, NotCovered, "HTTP 404 Reason; Tiingo has no prices for this ticker"),
        (403, Stopped, "Tiingo refused the key or the request: check TIINGO_API and its plan"),
        (401, Stopped, "Tiingo refused the key or the request"),
        (429, Stopped, "request limit \\(per hour or per day\\) is reached"),
        (503, TiingoError, "Tiingo is unavailable: run fetch again later"),
        (418, TiingoError, "HTTP 418 Reason$"),
    ],
)
def test_statuses(status, kind, message):
    _, client = answering(status, b'{"detail":"x"}')
    with pytest.raises(kind, match=message) as caught:
        client.get(URL)
    assert type(caught.value) is kind
    assert str(caught.value).startswith(f"GET {URL}: HTTP {status}")


def test_encoded_oversized_and_cut_short_bodies_are_refused():
    _, client = answering(headers={"Content-Encoding": "gzip"})
    with pytest.raises(TiingoError, match="only identity is accepted"):
        client.get(URL)
    _, client = answering(body=b" " * (BODY_LIMIT + 1))
    with pytest.raises(TiingoError, match=f"more than {BODY_LIMIT} bytes"):
        client.get(URL)
    _, client = answering(body=b"[]", headers={"Content-Length": "10"})
    with pytest.raises(TiingoError, match="the body ended after 2 of 10 bytes"):
        client.get(URL)


def test_a_network_failure_is_one_line_without_the_key():
    def fetch(url, headers, limit):
        raise TransportError(f"refused for {TIINGO_CANARY}")

    client = TiingoClient(TIINGO_CANARY, fetch=fetch, clock=lambda: NOW)
    with pytest.raises(TiingoError) as caught:
        client.get(URL)
    assert str(caught.value) == f"GET {URL}: refused for <TIINGO_API>; run fetch again later"
    assert redact("a TIINGOkey0123456789 b", TIINGO_CANARY) == "a <TIINGO_API> b"


def test_the_fake_answers_as_tiingo_does():
    fake = FakeTiingo()
    fake.add(TICKER, rising([date(2026, 10, 14), date(2026, 10, 15), date(2026, 10, 16)]))
    body = fake.client().get(URL)
    assert body.startswith(b'[{"date":"2026-10-15T00:00:00.000Z","close":101,"high":101,')
    assert body.count(b'"date"') == 2
    assert fake.tokens == [TIINGO_CANARY]
    with pytest.raises(NotCovered):
        fake.client().get(URL.replace("TEST", "OTHER"))
