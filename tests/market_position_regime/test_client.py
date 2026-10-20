"""HTTPS to the three sources: fixed endpoints, FRED's key appended at send time and never shown."""

from datetime import date

import pytest

from market_state_research.market_position_regime.script import cftc, finra, fred
from market_state_research.market_position_regime.script.client import (
    CFTC,
    FINRA,
    FRED,
    Client,
    Response,
    SourceError,
    TransportError,
    check_api_key,
    endpoint_of,
    redact,
)

from .support import KEY

FRED_URL = fred.observations_url(fred.NONFINANCIAL)


class Recorder:
    """A fetch that records what it was asked and answers one scripted response."""

    def __init__(self, response: Response | Exception) -> None:
        self.response = response
        self.calls: list[tuple[str, dict[str, str], int]] = []

    def __call__(self, url, headers, limit):
        self.calls.append((url, dict(headers), limit))
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def ok(body: bytes = b"[]", **headers: str) -> Response:
    return Response(200, "OK", headers, body)


@pytest.mark.parametrize("value", [None, ""])
def test_an_unset_key_is_refused_before_anything_is_sent(value):
    with pytest.raises(SourceError, match='FRED_API is not set; add FRED_API="..."'):
        Client(value, fetch=Recorder(ok()))


@pytest.mark.parametrize("value", ["SHORT", KEY.upper(), KEY + "0", KEY[:-1] + "-", KEY[:-1] + "é"])
def test_a_key_not_in_freds_form_is_refused_without_being_echoed(value):
    with pytest.raises(SourceError) as caught:
        check_api_key(value)
    assert str(caught.value) == "FRED_API must be 32 lowercase ASCII letters or digits"
    assert value not in str(caught.value)


def test_only_the_three_endpoints_are_known():
    assert endpoint_of(finra.URL) is FINRA
    assert endpoint_of(cftc.query_url(date(2026, 10, 12), date(2026, 10, 18))) is CFTC
    assert endpoint_of(FRED_URL) is FRED
    for url in (
        "http://www.finra.org/sites/default/files/2021-03/margin-statistics.xlsx",
        finra.URL + "?x=1",
        finra.URL + "#top",
        "https://www.finra.org:443/sites/default/files/2021-03/margin-statistics.xlsx",
        "https://user@www.finra.org/sites/default/files/2021-03/margin-statistics.xlsx",
        "https://www.finra.org/sites/default/files/2021-04/margin-statistics.xlsx",
        "https://publicreporting.cftc.gov/resource/yw9f-hn96.json?$limit=1",
        "https://publicreporting.cftc.gov/resource/gpe5-46if.json",
        FRED_URL + f"&api_key={KEY}",
        "https://api.stlouisfed.org/fred/series?series_id=X",
        "https://example.com/fred/series/observations?series_id=X",
        FRED_URL + " ",
    ):
        assert endpoint_of(url) is None, url


def test_the_key_is_sent_to_fred_alone_and_never_in_a_message():
    fetch = Recorder(ok(b"{}"))
    client = Client(KEY, fetch=fetch)
    client.get(FRED_URL)
    client.get(finra.URL)
    sent = [call[0] for call in fetch.calls]
    assert sent == [f"{FRED_URL}&api_key={KEY}", finra.URL]
    assert [call[2] for call in fetch.calls] == [FRED.limit, FINRA.limit]
    assert client.requests == 2 and repr(client) == "Client(requests=2)"


def test_a_url_with_a_key_or_outside_the_endpoints_is_refused_unsent():
    fetch = Recorder(ok())
    client = Client(KEY, fetch=fetch)
    with pytest.raises(SourceError) as caught:
        client.get(f"{FRED_URL}&api_key={KEY}")
    assert KEY not in str(caught.value) and "<FRED_API>" in str(caught.value)
    with pytest.raises(SourceError, match="only key-free URLs of"):
        client.get("https://example.com/")
    assert fetch.calls == []


@pytest.mark.parametrize(
    ("url", "status", "message"),
    [
        (FRED_URL, 400, "FRED refused the request: check FRED_API"),
        (FRED_URL, 403, "FRED refused the request: check FRED_API"),
        (finra.URL, 404, "FINRA no longer serves this address: report it"),
        (finra.URL, 429, "FINRA's rate limit: wait some minutes and run fetch again"),
        (FRED_URL, 503, "FRED is unavailable: wait and run fetch again"),
        (finra.URL, 418, f"GET {finra.URL}: HTTP 418 Scripted"),
    ],
)
def test_a_status_other_than_200_is_one_line_naming_the_key_free_url(url, status, message):
    client = Client(KEY, fetch=Recorder(Response(status, "Scripted", {}, b"")))
    with pytest.raises(SourceError) as caught:
        client.get(url)
    text = str(caught.value)
    assert text.startswith(f"GET {url}: HTTP {status}") and text.endswith(message)
    assert KEY not in text and "\n" not in text


def test_a_network_failure_names_no_key():
    client = Client(KEY, fetch=Recorder(TransportError(f"refused for {KEY}")))
    with pytest.raises(SourceError) as caught:
        client.get(FRED_URL)
    assert str(caught.value) == f"GET {FRED_URL}: refused for <FRED_API>; run fetch again"
    assert redact(f"a{KEY}b", KEY) == "a<FRED_API>b"


def test_bodies_are_accepted_only_whole_unencoded_and_within_the_limit():
    with pytest.raises(SourceError, match="only identity is accepted"):
        Client(KEY, fetch=Recorder(ok(b"x", **{"Content-Encoding": "gzip"}))).get(finra.URL)
    with pytest.raises(SourceError, match=f"more than {FINRA.limit} bytes"):
        Client(KEY, fetch=Recorder(ok(b"x" * (FINRA.limit + 1)))).get(finra.URL)
    with pytest.raises(SourceError, match="the body ended after 3 of 10 bytes; run fetch again"):
        Client(KEY, fetch=Recorder(ok(b"abc", **{"Content-Length": "10"}))).get(finra.URL)
    assert Client(KEY, fetch=Recorder(ok(b"abc", **{"Content-Length": "3"}))).get(finra.URL) == b"abc"
