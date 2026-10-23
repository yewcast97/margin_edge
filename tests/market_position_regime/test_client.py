"""HTTPS to the three sources: four fixed endpoints, no key, bodies only whole and as sent."""

from datetime import date

import pytest

from market_state_research.market_position_regime.script import cboe, cftc, finra
from market_state_research.market_position_regime.script.client import (
    CBOE_SKEW,
    CBOE_VIX,
    CFTC,
    FINRA,
    Client,
    Response,
    SourceError,
    TransportError,
    endpoint_of,
)

CFTC_URL = cftc.query_url(date(2026, 10, 12), date(2026, 10, 18))


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


def test_only_the_four_endpoints_are_known():
    assert endpoint_of(finra.URL) is FINRA
    assert endpoint_of(CFTC_URL) is CFTC
    assert endpoint_of(cboe.VIX.url) is CBOE_VIX
    assert endpoint_of(cboe.SKEW.url) is CBOE_SKEW
    for url in (
        "http://www.finra.org/sites/default/files/2021-03/margin-statistics.xlsx",
        finra.URL + "?x=1",
        finra.URL + "#top",
        "https://www.finra.org:443/sites/default/files/2021-03/margin-statistics.xlsx",
        "https://user@www.finra.org/sites/default/files/2021-03/margin-statistics.xlsx",
        "https://www.finra.org/sites/default/files/2021-04/margin-statistics.xlsx",
        "https://publicreporting.cftc.gov/resource/yw9f-hn96.json?$limit=1",
        "https://publicreporting.cftc.gov/resource/gpe5-46if.json",
        cboe.VIX.url + "?date=2026-10-20",
        # Cboe answers these two with 307 to cboe.VIX.url and cboe.SKEW.url.
        "https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv",
        "https://cdn.cboe.com/api/global/us_indices/daily_prices/SKEW_History.csv",
        cboe.SKEW.url + "?date=2026-10-20",
        "https://cdn-api.cboe.com/api/global/us_indices/daily_prices/SPX_History.csv",
        cboe.VIX.url + " ",
        "https://example.com/",
    ):
        assert endpoint_of(url) is None, url


def test_each_request_asks_for_its_endpoints_kind_within_its_limit():
    fetch = Recorder(ok(b"x"))
    client = Client(fetch=fetch)
    for url in (finra.URL, CFTC_URL, cboe.VIX.url, cboe.SKEW.url):
        assert client.get(url) == b"x"
    assert [call[0] for call in fetch.calls] == [finra.URL, CFTC_URL, cboe.VIX.url, cboe.SKEW.url]
    assert [call[1] for call in fetch.calls] == [
        {"Accept": FINRA.accept},
        {"Accept": "application/json"},
        {"Accept": "text/csv"},
        {"Accept": "text/csv"},
    ]
    assert [call[2] for call in fetch.calls] == [FINRA.limit, CFTC.limit, CBOE_VIX.limit, CBOE_SKEW.limit]
    assert client.requests == 4 and repr(client) == "Client(requests=4)"


def test_a_url_outside_the_endpoints_is_refused_unsent():
    fetch = Recorder(ok())
    client = Client(fetch=fetch)
    with pytest.raises(SourceError, match="only URLs of https://www.finra.org/"):
        client.get("https://example.com/")
    assert fetch.calls == [] and client.requests == 0


@pytest.mark.parametrize(
    ("url", "status", "message"),
    [
        (finra.URL, 404, "FINRA no longer serves this address: report it"),
        (cboe.VIX.url, 403, "Cboe no longer serves this address: report it"),
        (finra.URL, 429, "FINRA's rate limit: wait some minutes and run fetch again"),
        (cboe.VIX.url, 503, "Cboe is unavailable: wait and run fetch again"),
        (CFTC_URL, 500, "CFTC is unavailable: wait and run fetch again"),
        (finra.URL, 418, f"GET {finra.URL}: HTTP 418 Scripted"),
    ],
)
def test_a_status_other_than_200_is_one_line_naming_the_url(url, status, message):
    client = Client(fetch=Recorder(Response(status, "Scripted", {}, b"")))
    with pytest.raises(SourceError) as caught:
        client.get(url)
    text = str(caught.value)
    assert text.startswith(f"GET {url}: HTTP {status}") and text.endswith(message)
    assert "\n" not in text


def test_a_network_failure_is_one_line():
    client = Client(fetch=Recorder(TransportError("connection refused")))
    with pytest.raises(SourceError) as caught:
        client.get(cboe.VIX.url)
    assert str(caught.value) == f"GET {cboe.VIX.url}: connection refused; run fetch again"


def test_bodies_are_accepted_only_whole_unencoded_and_within_the_limit():
    with pytest.raises(SourceError, match="only identity is accepted"):
        Client(fetch=Recorder(ok(b"x", **{"Content-Encoding": "gzip"}))).get(cboe.VIX.url)
    with pytest.raises(SourceError, match=f"more than {FINRA.limit} bytes"):
        Client(fetch=Recorder(ok(b"x" * (FINRA.limit + 1)))).get(finra.URL)
    with pytest.raises(SourceError, match="the body ended after 3 of 10 bytes; run fetch again"):
        Client(fetch=Recorder(ok(b"abc", **{"Content-Length": "10"}))).get(finra.URL)
    assert Client(fetch=Recorder(ok(b"abc", **{"Content-Length": "3"}))).get(finra.URL) == b"abc"
    assert Client(fetch=Recorder(ok(b"abc"))).get(cboe.VIX.url) == b"abc"  # Cboe sends no Content-Length
