"""``earningscalls``: the EarningsCalls.dev client, the strict reading of its bodies and a call's text.

The client runs over the recording fake (``fake_earningscalls``) and, for ``urllib_fetch``,
over urllib's real opener with a fake HTTPS handler (``transport_support``); no test
reaches the provider. Bodies are the synthetic ones of ``calls_support``. Every expected
message is written out, so a change of wording fails here first.
"""

import json
import socket
import urllib.error
from datetime import date

import pytest

from market_state_research.fundamentals.script.client import Response
from market_state_research.fundamentals.script.earningscalls import (
    API,
    BODY_LIMIT,
    ERROR_LIMIT,
    PACING,
    TIMEOUT,
    Ambiguous,
    CallEvent,
    EarningsCallsClient,
    EarningsCallsError,
    LimitReached,
    Transcript,
    TranscriptTurn,
    Turn,
    allowed_url,
    call_text,
    check_api_key,
    check_capture,
    event_time,
    events_url,
    load_json,
    parse_events_page,
    parse_transcript,
    transcript_url,
    urllib_fetch,
)

from .calls_support import (
    ANALYST,
    CALL_DROPPED,
    CALL_OLD_Q,
    CALL_Q1,
    CALL_Q2,
    CALLS,
    CEO,
    CFO,
    ISSUER,
    OPERATOR,
    OTHER_ISSUER,
    Call,
    call_row,
    compact,
    events_page,
    transcript_body,
)
from .calls_support import (
    call_text as written_text,
)
from .fake_earningscalls import API_KEY, CANARY, FakeEarningsCalls, calls_client, ok, status
from .fake_edgar import RecordingSleep
from .support import NOW, edt, est
from .transport_support import Network, Raw, Served, offline_network

EVENTS = f"{API}/earnings/?ticker=INTC&event_type=earnings&country=US&limit=100&sort=date_desc&page=1"
TRANSCRIPT = f"{API}/transcripts/248001/components"
Q2_EVENT = CallEvent(CALL_Q2.id, edt(2026, 7, 23, 17, 0), 2026, 2)


def serving(body: bytes = b"{}", url: str = EVENTS) -> FakeEarningsCalls:
    return FakeEarningsCalls({url: ok(body)})


# --------------------------------------------------------------------------- URLs and the key


def test_the_urls_ask_for_one_tickers_earnings_calls_and_one_calls_turns():
    assert events_url("INTC", 1) == EVENTS
    assert events_url("BRK.B", 20).endswith(
        "ticker=BRK.B&event_type=earnings&country=US&limit=100&sort=date_desc&page=20"
    )
    assert transcript_url(248001) == TRANSCRIPT
    assert (API, TIMEOUT, PACING, BODY_LIMIT) == (
        "https://earningscalls.dev/api/v1",
        60,
        3.1,
        8 * 1024 * 1024,
    )


@pytest.mark.parametrize("page", [0, 21, True, "1"])
def test_events_url_refuses_a_page_outside_1_to_20(page):
    with pytest.raises(ValueError, match="^a page of the calls list is a number from 1 to 20$"):
        events_url("INTC", page)


@pytest.mark.parametrize("call_id", [0, -1, 10**12 + 1, True, "248001"])
def test_transcript_url_refuses_an_id_that_is_not_a_whole_number(call_id):
    with pytest.raises(ValueError, match="^a call id is a whole number from 1 to 1000000000000$"):
        transcript_url(call_id)


@pytest.mark.parametrize("value", [None, ""])
def test_a_missing_key_names_the_setting_and_where_to_add_it(value):
    with pytest.raises(EarningsCallsError) as caught:
        check_api_key(value)
    assert str(caught.value) == (
        'EARNINGSCALLS_API is not set; add EARNINGSCALLS_API="..." to the repository-root .env'
    )


@pytest.mark.parametrize("value", ["two words", "tab\there", "é-key", "x" * 201, "line\nbreak"])
def test_a_malformed_key_is_refused_without_echoing_it(value):
    with pytest.raises(EarningsCallsError) as caught:
        check_api_key(value)
    assert str(caught.value) == "EARNINGSCALLS_API must be printable ASCII without spaces"


def test_a_well_formed_key_is_returned_unchanged():
    assert check_api_key(CANARY) == CANARY
    assert check_api_key("x" * 200) == "x" * 200


@pytest.mark.parametrize(
    ("url", "allowed"),
    [
        (EVENTS, True),
        ("http://earningscalls.dev/api/v1/me", False),
        ("https://earningscalls.dev:443/api/v1/me", False),
        ("https://user@earningscalls.dev/api/v1/me", False),
        ("https://api.earningscalls.dev/api/v1/me", False),
        ("https://earningscalls.dev/api/v1/me x", False),
        ("https://earningscalls.dev/é", False),
    ],
)
def test_only_https_urls_on_the_providers_host_are_allowed(url, allowed):
    assert allowed_url(url) is allowed


# --------------------------------------------------------------------------- the client


def test_each_request_sends_exactly_the_key_and_the_accepted_type():
    fake = serving()
    client = calls_client(fake, api_key=CANARY)

    fetched = client.events_page("INTC", 1)

    assert fake.calls == [(EVENTS, {"X-API-Key": CANARY, "Accept": "application/json"}, BODY_LIMIT)]
    assert (fetched.url, fetched.fetched_at, fetched.body) == (EVENTS, NOW, b"{}")
    assert CANARY not in repr(client) and CANARY not in repr(fetched)
    assert repr(client) == "EarningsCallsClient(requests=1)"


def test_no_sleep_before_the_first_request_and_pacing_before_each_later_one():
    fake = FakeEarningsCalls(
        {EVENTS: ok(b"{}"), TRANSCRIPT: status(500), f"{API}/transcripts/26083/components": ok(b"{}")}
    )
    sleep = RecordingSleep()
    client = calls_client(fake, sleep)

    client.events_page("INTC", 1)
    with pytest.raises(EarningsCallsError):
        client.transcript(248001)
    client.transcript(26083)

    assert sleep.calls == [PACING, PACING]
    assert client.requests == 3  # the failed request counts


def test_fetched_at_is_new_york_time_read_after_the_response():
    readings = iter([est(2026, 1, 5, 9, 0)])
    client = EarningsCallsClient(
        API_KEY, fetch=serving(), sleep=RecordingSleep(), clock=lambda: next(readings)
    )

    assert client.events_page("INTC", 1).fetched_at == est(2026, 1, 5, 9, 0)


@pytest.mark.parametrize(
    ("response", "message"),
    [
        (
            status(401, "Unauthorized"),
            f"GET {EVENTS}: HTTP 401 Unauthorized; EarningsCalls.dev refused the key: "
            "check EARNINGSCALLS_API",
        ),
        (
            status(403, "Forbidden"),
            f"GET {EVENTS}: HTTP 403 Forbidden; EarningsCalls.dev refused the request: "
            "the key's plan does not "
            "include it (full transcripts need the Pro plan)",
        ),
        (status(404), f"GET {EVENTS}: HTTP 404; EarningsCalls.dev serves nothing at this address"),
        (
            status(502, "Bad Gateway"),
            f"GET {EVENTS}: HTTP 502 Bad Gateway; EarningsCalls.dev is unavailable: wait and run fetch again",
        ),
        (status(400, "Bad Request"), f"GET {EVENTS}: HTTP 400 Bad Request"),
        (status(302, "redirect not followed"), f"GET {EVENTS}: HTTP 302 redirect not followed"),
    ],
)
def test_any_status_but_200_is_one_line_naming_the_url_status_and_next_step(response, message):
    client = calls_client(FakeEarningsCalls({EVENTS: response}))
    with pytest.raises(EarningsCallsError) as caught:
        client.events_page("INTC", 1)
    assert str(caught.value) == message
    assert not isinstance(caught.value, LimitReached)


def test_http_429_is_the_request_limit_with_the_wait_and_the_providers_own_words():
    said = json.dumps({"error": f"Monthly quota exceeded for key {CANARY}; resets 2026-11-01"}).encode()
    client = calls_client(
        FakeEarningsCalls({EVENTS: status(429, "Too Many Requests", said, retry_after="3600")}),
        api_key=CANARY,
    )

    with pytest.raises(LimitReached) as caught:
        client.events_page("INTC", 1)

    assert str(caught.value) == (
        f"GET {EVENTS}: HTTP 429; EarningsCalls.dev's request limit is reached (the key's 3,000 requests a "
        "month or 20 a minute); retry after 3600 seconds; the provider says: Monthly quota exceeded for key "
        "<key>; resets 2026-11-01; run fetch again once it resets"
    )
    assert CANARY not in str(caught.value)


@pytest.mark.parametrize(
    "body", [b"", b"<html>slow down</html>", b'{"message": 5}', b"[1]", b'{"message": "  "}', b"\xff"]
)
def test_a_429_without_a_readable_message_still_names_the_limit(body):
    client = calls_client(FakeEarningsCalls({EVENTS: status(429, body=body, retry_after="soon")}))
    with pytest.raises(LimitReached) as caught:
        client.events_page("INTC", 1)
    assert str(caught.value) == (
        f"GET {EVENTS}: HTTP 429; EarningsCalls.dev's request limit is reached (the key's 3,000 requests a "
        "month or 20 a minute); run fetch again once it resets"
    )


def test_a_long_providers_message_is_escaped_and_cut():
    said = json.dumps({"message": "x" * 300 + "\n"}).encode()
    client = calls_client(FakeEarningsCalls({EVENTS: status(429, body=said)}))
    with pytest.raises(LimitReached) as caught:
        client.events_page("INTC", 1)
    assert f"the provider says: {'x' * 200}; run fetch" in str(caught.value)


@pytest.mark.parametrize("encoding", ["gzip", "br", "identity, gzip"])
def test_an_encoded_body_is_refused(encoding):
    client = calls_client(FakeEarningsCalls({EVENTS: ok(b"{}", content_encoding=encoding)}))
    with pytest.raises(EarningsCallsError) as caught:
        client.events_page("INTC", 1)
    assert (
        str(caught.value)
        == f"GET {EVENTS}: the body is encoded (Content-Encoding); only identity is accepted"
    )


def test_a_body_of_exactly_the_limit_is_accepted_and_one_more_byte_is_refused():
    assert calls_client(serving(b"x" * BODY_LIMIT)).events_page("INTC", 1).body == b"x" * BODY_LIMIT
    with pytest.raises(EarningsCallsError) as caught:
        calls_client(serving(b"x" * (BODY_LIMIT + 1))).events_page("INTC", 1)
    assert str(caught.value) == f"GET {EVENTS}: more than {BODY_LIMIT} bytes"


def test_a_body_shorter_than_its_content_length_is_refused_as_cut_short():
    client = calls_client(FakeEarningsCalls({EVENTS: ok(b"0123456789", content_length="11")}))
    with pytest.raises(EarningsCallsError) as caught:
        client.events_page("INTC", 1)
    assert str(caught.value) == f"GET {EVENTS}: the body ended after 10 of 11 bytes; run fetch again"
    exact = calls_client(FakeEarningsCalls({EVENTS: ok(b"0123456789", content_length="10")}))
    assert exact.events_page("INTC", 1).body == b"0123456789"


def test_a_url_off_the_host_is_refused_before_any_request():
    fake = FakeEarningsCalls()
    with pytest.raises(EarningsCallsError) as caught:
        calls_client(fake).get("https://example.com/api/v1/me")
    assert str(caught.value) == (
        "GET https://example.com/api/v1/me: only HTTPS requests to https://earningscalls.dev are allowed"
    )
    assert fake.calls == []


def test_the_fake_fails_loudly_on_a_url_it_does_not_serve():
    with pytest.raises(AssertionError, match="FakeEarningsCalls serves no response for"):
        calls_client(FakeEarningsCalls()).events_page("INTC", 1)


# --------------------------------------------------------------------------- urllib_fetch, offline


@pytest.fixture
def network(monkeypatch) -> Network:
    """urllib with ``FakeTransport`` in place of HTTPS; plain HTTP and sockets fail loudly."""
    return offline_network(monkeypatch)


HEADERS = {"X-API-Key": API_KEY, "Accept": "application/json"}


def test_urllib_fetch_sends_exactly_the_given_headers_with_the_timeout(network):
    network.transport.routes[EVENTS] = Served(body=b'{"data": []}')

    response = urllib_fetch(EVENTS, HEADERS, BODY_LIMIT)

    assert response == Response(200, "OK", {"content-type": "application/json"}, b'{"data": []}')
    [sent] = network.transport.sent
    assert (sent.url, sent.method, sent.timeout) == (EVENTS, "GET", TIMEOUT)
    # urllib adds Host only: no Accept-Encoding, and no User-Agent of its own beside them.
    assert sent.headers == {
        "X-api-key": API_KEY,
        "Accept": "application/json",
        "Host": "earningscalls.dev",
        "User-agent": sent.headers["User-agent"],
    }


def test_urllib_fetch_reads_at_most_one_byte_more_than_the_limit(network):
    network.transport.routes[EVENTS] = Served(body=bytes(range(100)), step=3)
    assert urllib_fetch(EVENTS, HEADERS, 10).body == bytes(range(11))
    [body] = network.transport.bodies
    assert body.consumed == 11 and body.closed


@pytest.mark.parametrize(
    ("code", "reason"), [(401, "Unauthorized"), (404, "Not Found"), (503, "Unavailable")]
)
def test_urllib_fetch_returns_an_error_status_with_an_empty_body(network, code, reason):
    network.transport.routes[EVENTS] = Served(status=code, reason=reason, body=b'{"error": "no"}')
    assert urllib_fetch(EVENTS, HEADERS, BODY_LIMIT) == Response(
        code, reason, {"content-type": "application/json"}, b""
    )


def test_urllib_fetch_keeps_a_429s_body_for_its_message_within_a_bound(network):
    network.transport.routes[EVENTS] = Served(status=429, reason="Too Many Requests", body=b"x" * 10_000)
    response = urllib_fetch(EVENTS, HEADERS, BODY_LIMIT)
    assert (response.status, len(response.body)) == (429, ERROR_LIMIT)


def test_a_429_reaches_the_client_as_the_limit(network):
    body = b'{"message": "Rate limit exceeded; resets 2026-11-01"}'
    network.transport.routes[EVENTS] = Served(status=429, reason="Too Many Requests", body=body)
    client = EarningsCallsClient(API_KEY, sleep=RecordingSleep(), clock=lambda: NOW)  # the default fetch
    with pytest.raises(LimitReached, match="the provider says: Rate limit exceeded; resets 2026-11-01; run"):
        client.events_page("INTC", 1)


@pytest.mark.parametrize("location", [TRANSCRIPT, "https://example.com/", "/api/v1/me"])
def test_a_redirect_is_refused_without_naming_its_target(network, location):
    network.transport.routes[EVENTS] = Served(status=302, reason="Found", headers=(("Location", location),))
    with pytest.raises(EarningsCallsError) as caught:
        urllib_fetch(EVENTS, HEADERS, BODY_LIMIT)
    assert str(caught.value) == f"GET {EVENTS}: HTTP 302 redirect not followed"
    assert len(network.transport.sent) == 1


def test_urllib_fetch_refuses_a_url_off_the_host_before_opening_anything(network):
    with pytest.raises(
        EarningsCallsError, match="only HTTPS requests to https://earningscalls.dev are allowed"
    ):
        urllib_fetch("https://www.sec.gov/files/company_tickers.json", HEADERS, BODY_LIMIT)
    assert network.openers == 0


@pytest.mark.parametrize(
    ("failure", "reason"),
    [
        (
            urllib.error.URLError(socket.gaierror(8, "nodename nor servname provided")),
            "nodename nor servname provided",
        ),
        (TimeoutError("timed out"), "no response within 60 seconds"),
        (OSError(50, "Network is down"), "Network is down"),
    ],
)
def test_a_network_failure_is_one_line_naming_the_url_and_reason(network, failure, reason):
    network.transport.routes[EVENTS] = failure
    with pytest.raises(EarningsCallsError) as caught:
        urllib_fetch(EVENTS, HEADERS, BODY_LIMIT)
    assert str(caught.value) == f"GET {EVENTS}: {reason}"


def test_urllib_fetch_refuses_a_body_that_ended_before_http_clients_length(network):
    network.transport.routes[EVENTS] = Raw(
        b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 11\r\n\r\n0123456789"
    )
    with pytest.raises(EarningsCallsError) as caught:
        urllib_fetch(EVENTS, HEADERS, BODY_LIMIT)
    assert str(caught.value) == f"GET {EVENTS}: the body ended after 10 of 11 bytes; run fetch again"


# --------------------------------------------------------------------------- strict JSON


@pytest.mark.parametrize(
    ("body", "message"),
    [
        (b"\xff", "the body is not UTF-8"),
        (b'{"a": 1, "a": 2}', "invalid JSON: an object repeats a key"),
        (b'{"a": NaN}', "invalid JSON: NaN is not JSON"),
        (b'{"a": -Infinity}', "invalid JSON: -Infinity is not JSON"),
        (b"[" * 100_000, "invalid JSON: nested too deeply"),
        (b'{"a": ' + b"1" * 5000 + b"}", "invalid JSON: a number is too long"),
        (b"{", "invalid JSON: Expecting property name enclosed in double quotes (line 1, column 2)"),
    ],
)
def test_load_json_refuses_what_the_provider_never_writes(body, message):
    with pytest.raises(ValueError) as caught:
        load_json(body)
    assert str(caught.value) == message


def test_event_time_reads_the_providers_utc_times_as_new_york_instants():
    assert event_time("2026-07-23T21:00:00.000Z") == edt(2026, 7, 23, 17, 0)
    assert event_time("2026-01-22T22:00:00Z") == est(2026, 1, 22, 17, 0)
    assert event_time("2026-07-24T03:30:00Z").date() == date(2026, 7, 23)  # New York's date
    for value in (
        "2026-07-23T21:00:00",
        "2026-07-23T21:00:00+00:00",
        "2026-07-23 21:00:00Z",
        "2026-02-30T21:00:00Z",
    ):
        with pytest.raises(
            ValueError, match="^event_date_time must be a UTC time written YYYY-MM-DDTHH:MM:SS"
        ):
            event_time(value)


# --------------------------------------------------------------------------- calls pages


def test_a_calls_page_is_read_as_the_strict_subset_of_the_providers_body():
    page = parse_events_page(events_page())

    assert (page.page, page.total, page.total_pages, page.ambiguous, page.issuer_count) == (1, 4, 1, False, 1)
    assert [(call.id, call.at, call.day) for call in page.calls] == [
        (CALL_Q2.id, edt(2026, 7, 23, 17, 0), date(2026, 7, 23)),
        (CALL_Q1.id, edt(2026, 4, 23, 17, 0), date(2026, 4, 23)),
        (CALL_OLD_Q.id, edt(2025, 10, 23, 17, 0), date(2025, 10, 23)),
        (CALL_DROPPED.id, edt(2024, 10, 31, 17, 0), date(2024, 10, 31)),
    ]
    assert (page.symbols, page.issuers) == (frozenset({"INTC"}), frozenset({ISSUER}))
    assert page.calls[0].describe() == {
        "id": 248001,
        "date": "2026-07-23",
        "fiscal_year": 2026,
        "fiscal_quarter": 2,
    }


def test_an_empty_list_reads_as_one_page_without_a_call():
    body = (  # as served live for ASML, whose calls are listed under its Amsterdam symbol only
        b'{"data":[],"pagination":{"page":1,"limit":100,"total":0,"total_pages":0},'
        b'"ambiguous":false,"issuer_count":0}'
    )
    page = parse_events_page(body)
    assert check_capture("ASML", [page]) == ()


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"event_type": "special"}, "calls list: data.0.event_type: Input should be 'earnings'"),
        ({"id": "248001"}, "calls list: data.0.id: Input should be a valid integer"),
        ({"id": 0}, "calls list: data.0.id: Input should be greater than or equal to 1"),
        ({"country": "NL"}, "calls list: data.0.country: Input should be 'US'"),
        ({"fiscal_quarter": 5}, "calls list: data.0.fiscal_quarter: Input should be less than or equal to 4"),
        (
            {"issuer_id": "ABC"},
            "calls list: data.0.issuer_id: Value error, must be 32 lowercase hex digits or null",
        ),
        (
            {"event_date_time": "2026-07-23T21:00:00+00:00"},
            "calls list: data.0.event_date_time: Value error, event_date_time must be a UTC time written "
            "YYYY-MM-DDTHH:MM:SS[.fff]Z",
        ),
    ],
)
def test_a_call_row_breaking_the_subset_is_refused_naming_the_field(change, message):
    with pytest.raises(ValueError) as caught:
        parse_events_page(events_page([call_row(CALL_Q2, **change)]))
    assert str(caught.value) == message


def test_a_row_may_carry_null_fiscal_labels_and_issuer():
    (call,) = parse_events_page(
        events_page([call_row(CALL_Q2, fiscal_year=None, fiscal_quarter=None, issuer=None)])
    ).calls
    assert (call.fiscal_year, call.fiscal_quarter) == (None, None)


def test_a_page_without_its_pagination_or_flags_is_refused():
    value = json.loads(events_page())
    del value["ambiguous"]
    with pytest.raises(ValueError) as caught:
        parse_events_page(compact(value))
    assert str(caught.value) == "calls list: ambiguous: Field required"


def numbered(start: int, count: int) -> list[dict]:
    return [
        call_row(Call(start + index, "2025-01-02T21:00:00.000Z", "", None, None, ""))
        for index in range(count)
    ]


def test_a_capture_of_two_pages_reads_every_call_in_page_order():
    first = parse_events_page(events_page(numbered(1, 100), total=101))
    second = parse_events_page(events_page(numbered(101, 1), page=2, total=101))

    calls = check_capture("INTC", [first, second])

    assert [call.id for call in calls] == list(range(1, 102))


@pytest.mark.parametrize(
    ("pages", "message"),
    [
        ([events_page(total=101)], "the calls capture holds 1 page; its total of 101 calls fills 2"),
        (
            [events_page(total=4, total_pages=2)],
            "calls list page 1: total_pages does not fit a total of 4 calls",
        ),
        (
            [events_page(numbered(1, 100), total=101), events_page(numbered(101, 1), page=3, total=101)],
            "calls list page 2: pagination.page is not 2",
        ),
        (
            [events_page(numbered(1, 100), total=101), events_page(numbered(101, 1), page=2, total=102)],
            "calls list page 2: total or total_pages differs from page 1's",
        ),
        (
            [events_page(numbered(1, 99), total=101), events_page(numbered(101, 2), page=2, total=101)],
            "calls list page 1 holds 99 calls; its total names 100",
        ),
        (
            [events_page([call_row(CALL_Q2, symbol="INTL")])],
            "calls list page 1: a call's stock_symbol is not INTC",
        ),
        ([events_page([call_row(CALL_Q2), call_row(CALL_Q2)])], "the calls capture lists one call id twice"),
    ],
)
def test_a_capture_breaking_its_rules_is_refused_naming_the_page(pages, message):
    with pytest.raises(ValueError) as caught:
        check_capture("INTC", [parse_events_page(page) for page in pages])
    assert str(caught.value) == message
    assert not isinstance(caught.value, Ambiguous)


@pytest.mark.parametrize(
    ("page", "count"),
    [
        (events_page(ambiguous=True), 2),
        (events_page(issuer_count=3), 3),
        (events_page([call_row(CALL_Q2), call_row(CALL_Q1, issuer=OTHER_ISSUER)]), 2),
    ],
)
def test_a_symbol_naming_several_issuers_is_ambiguous(page, count):
    with pytest.raises(Ambiguous) as caught:
        check_capture("INTC", [parse_events_page(page)])
    assert str(caught.value) == (
        f"EarningsCalls.dev lists {count} issuers for INTC (ambiguous): their calls cannot be told apart"
    )


def test_issuers_across_pages_must_agree():
    first = parse_events_page(events_page(numbered(1, 100), total=101))
    second = parse_events_page(events_page([call_row(CALL_Q2, issuer=OTHER_ISSUER)], page=2, total=101))
    with pytest.raises(Ambiguous, match="lists 2 issuers for INTC"):
        check_capture("INTC", [first, second])


# --------------------------------------------------------------------------- transcripts


def test_a_transcript_is_read_against_its_listed_call():
    transcript = parse_transcript(transcript_body(CALL_Q2), Q2_EVENT)

    assert (transcript.title, transcript.at) == (
        "Intel Corporation - Q2 2026 Earnings Call",
        edt(2026, 7, 23, 17, 0),
    )
    assert [(turn.speaker, turn.role) for turn in transcript.turns] == [
        OPERATOR,
        ("John Pitzer", "executive"),
        CEO,
        CFO,
        OPERATOR,
        ANALYST,
        CFO,
    ]


@pytest.mark.parametrize(
    ("body", "message"),
    [
        (b"[]", "transcript: Input should be a valid dictionary or instance of _TranscriptBody"),
        (
            transcript_body(CALL_Q2, event_type="special"),
            "transcript: data.event_type: Input should be 'earnings'",
        ),
        (
            transcript_body(CALL_Q2, header={"title": "  "}),
            "transcript: data.header.title: Value error, must be printable text with a character that is "
            "not whitespace",
        ),
        (
            transcript_body(CALL_Q2, turns=(("Lip-Bu\nTan", "executive", "Words."),)),
            "transcript: data.components.0.speaker_name: Value error, must be printable text with a "
            "character "
            "that is not whitespace",
        ),
        (
            transcript_body(CALL_Q2, turns=(("Lip-Bu Tan", "host", "Words."),)),
            "transcript: data.components.0.speaker_type: Input should be 'executive', 'analyst', 'operator', "
            "'attendee', 'shareholder' or 'unknown'",
        ),
        (
            transcript_body(CALL_Q2, header={"event_date_time": "2026-07-23T21:00:01Z"}),
            "transcript: data.header.event_date_time is not the time the calls list gives",
        ),
    ],
)
def test_a_transcript_breaking_the_subset_is_refused_naming_the_field(body, message):
    with pytest.raises(ValueError) as caught:
        parse_transcript(body, Q2_EVENT)
    assert str(caught.value) == message


def test_a_transcripts_turns_must_be_in_order_from_zero():
    value = json.loads(transcript_body(CALL_Q2))
    value["data"]["components"][1]["order"] = 5
    with pytest.raises(ValueError) as caught:
        parse_transcript(compact(value), Q2_EVENT)
    assert str(caught.value) == "transcript: data.components must be in order from 0 without a gap"


def test_a_transcript_header_may_write_its_time_with_milliseconds():
    body = transcript_body(CALL_Q2, header={"event_date_time": "2026-07-23T21:00:00.000Z"})
    assert parse_transcript(body, Q2_EVENT).at == Q2_EVENT.at


def test_a_transcript_gives_the_calls_duration_in_seconds_where_the_provider_gives_one():
    absent = json.loads(transcript_body(CALL_Q2))
    del absent["data"]["duration_seconds"]

    assert parse_transcript(transcript_body(CALL_Q2), Q2_EVENT).duration_seconds == 3525
    assert parse_transcript(transcript_body(CALL_Q2, duration_seconds=0), Q2_EVENT).duration_seconds == 0
    assert (
        parse_transcript(transcript_body(CALL_Q2, duration_seconds=None), Q2_EVENT).duration_seconds is None
    )
    assert parse_transcript(compact(absent), Q2_EVENT).duration_seconds is None


@pytest.mark.parametrize(
    ("duration", "message"),
    [
        pytest.param(-1, "Input should be greater than or equal to 0", id="negative"),
        pytest.param("3525", "Input should be a valid integer", id="text"),
        pytest.param(3525.5, "Input should be a valid integer", id="fraction"),
        pytest.param(3525.0, "Input should be a valid integer", id="float"),
        pytest.param(True, "Input should be a valid integer", id="boolean"),
    ],
)
def test_a_duration_that_is_not_a_whole_number_from_0_is_refused(duration, message):
    with pytest.raises(ValueError) as caught:
        parse_transcript(transcript_body(CALL_Q2, duration_seconds=duration), Q2_EVENT)
    assert str(caught.value) == f"transcript: data.duration_seconds: {message}"


# --------------------------------------------------------------------------- derived text


def test_a_calls_text_is_a_heading_per_turn_then_its_paragraphs():
    text = call_text(parse_transcript(transcript_body(CALL_Q2), Q2_EVENT))

    assert text.text == written_text(CALL_Q2)
    assert [(text.text[turn.start : turn.end], turn.speaker, turn.role) for turn in text.turns][:2] == [
        ("Good afternoon and welcome to the Intel earnings conference call.", "Operator", "operator"),
        ("Thank you, operator. With me today are our CEO and our CFO.", "John Pitzer", "executive"),
    ]
    assert all(text.text[turn.start - 1] == "\n" and text.text[turn.end] == "\n" for turn in text.turns)


def test_a_calls_text_normalises_whitespace_names_and_empty_turns():
    transcript = Transcript(
        "Title",
        NOW,
        (
            TranscriptTurn("Ann  O’Neil", "executive", "  First line.\r\n\r\n  Second   line.  "),
            TranscriptTurn("Oﬃcer", "unknown", ""),  # a ligature in a name, and a turn without words
            TranscriptTurn("Operator", "operator", "Last.\rWords.\nEnd."),
        ),
    )

    text = call_text(transcript)

    assert text.text == (
        "Ann O’Neil (executive)\nFirst line.\nSecond line.\nOfficer (unknown)\nOperator (operator)\n"
        "Last.\nWords.\nEnd.\n"
    )
    first, empty, last = text.turns
    assert (text.text[first.start : first.end], first.speaker) == ("First line.\nSecond line.", "Ann O’Neil")
    assert (empty.start, empty.end, empty.speaker, empty.role) == (
        empty.start,
        empty.start,
        "Officer",
        "unknown",
    )
    assert text.text[last.start : last.end] == "Last.\nWords.\nEnd."


def test_a_turns_heading_is_its_speaker_then_its_role_in_parentheses():
    assert Turn(0, 10, "Lip-Bu Tan", "executive").heading == "Lip-Bu Tan (executive)"

    text = call_text(parse_transcript(transcript_body(CALL_Q2), Q2_EVENT))

    assert [text.text[: turn.start].splitlines()[-1] for turn in text.turns] == [
        turn.heading for turn in text.turns
    ]
    assert [turn.heading for turn in text.turns][:3] == [
        "Operator (operator)",
        "John Pitzer (executive)",
        f"{CEO[0]} ({CEO[1]})",
    ]


def test_every_call_of_the_default_capture_has_its_written_text():
    for call in CALLS:
        event = CallEvent(call.id, event_time(call.listed_at))
        assert call_text(parse_transcript(transcript_body(call), event)).text == written_text(call)
