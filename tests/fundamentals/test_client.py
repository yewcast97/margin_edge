"""script/client.py: EDGAR URLs, the checked User-Agent, pacing, limits and every refusal.

``EdgarClient`` is driven through ``FakeEdgar``; ``urllib_fetch`` runs urllib's real
opener (redirect handling, error processing) over ``transport_support.FakeTransport``,
which replaces the HTTPS handler, while plain HTTP and socket connections fail loudly. A
``Raw`` route has http.client itself read the bytes a server sent before closing the
connection, so a body cut short reaches the client as it would from EDGAR. Nothing here
reaches the network or reads a setting: the User-Agent values are test literals.
"""

import http.client
import json
import socket
import urllib.error
from datetime import UTC, datetime, timedelta

import pytest

from market_state_research.common.times import to_eastern
from market_state_research.fundamentals.script.client import (
    ALLOWED_HOSTS,
    COMPANY_TICKERS_URL,
    DOCUMENT_ACCEPT,
    DOCUMENT_LIMIT,
    INDEX_LIMIT,
    JSON_LIMIT,
    MAX_USER_AGENT,
    PACING,
    REDIRECT_NOT_FOLLOWED,
    REDIRECT_WITHIN,
    TIMEOUT,
    USER_AGENT_MALFORMED,
    USER_AGENT_UNSET,
    EdgarClient,
    EdgarError,
    Fetched,
    Response,
    allowed_url,
    archive_url,
    check_user_agent,
    decode_document,
    index_url,
    submissions_url,
    urllib_fetch,
)

from .fake_edgar import USER_AGENT, FakeEdgar, RecordingSleep, edgar_client, ok, ok_json, status
from .support import NOW, edt, est
from .transport_support import Network, Raw, RawSocket, Served, offline_network

CIK = "0000050863"
ACCESSION = "0000050863-26-000123"
DOCUMENT_NAME = "intc-20260627.htm"
SUBMISSIONS = "https://data.sec.gov/submissions/CIK0000050863.json"
DOCUMENT = "https://www.sec.gov/Archives/edgar/data/50863/000005086326000123/intc-20260627.htm"
INDEX_PAGE = "https://www.sec.gov/Archives/edgar/data/50863/000005086326000123/0000050863-26-000123-index.htm"
FULLWIDTH_ZERO = "０"  # a Unicode decimal digit that int() accepts
SECRET = "SECRETNAME"  # marks a User-Agent value that must never be echoed
REFUSED = "only HTTPS requests to https://www.sec.gov, https://data.sec.gov are allowed"


def every_url_served(body: bytes = b"{}") -> FakeEdgar:
    return FakeEdgar({url: ok(body) for url in (COMPANY_TICKERS_URL, SUBMISSIONS, DOCUMENT, INDEX_PAGE)})


# --------------------------------------------------------------------------- URLs and limits


def test_constants_follow_edgars_fair_access_policy():
    assert COMPANY_TICKERS_URL == "https://www.sec.gov/files/company_tickers.json"
    assert JSON_LIMIT == 20 * 1024 * 1024
    assert DOCUMENT_LIMIT == 50 * 1024 * 1024
    assert INDEX_LIMIT == 20 * 1024 * 1024
    assert TIMEOUT == 60
    assert PACING == 0.2  # half of EDGAR's ten requests a second
    assert ALLOWED_HOSTS == ("www.sec.gov", "data.sec.gov")
    assert DOCUMENT_ACCEPT == "text/html, text/plain;q=0.9, */*;q=0.1"


def test_submissions_url_names_the_zero_padded_cik():
    assert submissions_url(CIK) == SUBMISSIONS
    assert allowed_url(SUBMISSIONS)


@pytest.mark.parametrize(
    "cik",
    ["50863", "00000508630", "", "000005086a", "000005086" + FULLWIDTH_ZERO, "0000050863\n", 50863, None],
    ids=["unpadded", "eleven-digits", "empty", "letter", "fullwidth-digit", "newline", "int", "none"],
)
def test_url_builders_refuse_a_malformed_cik(cik):
    with pytest.raises(ValueError, match="^CIK must be 10 ASCII digits$"):
        submissions_url(cik)
    with pytest.raises(ValueError, match="^CIK must be 10 ASCII digits$"):
        archive_url(cik, ACCESSION, DOCUMENT_NAME)
    with pytest.raises(ValueError, match="^CIK must be 10 ASCII digits$"):
        index_url(cik, ACCESSION)


def test_archive_url_drops_the_ciks_zeros_and_the_accessions_hyphens():
    assert archive_url(CIK, ACCESSION, DOCUMENT_NAME) == DOCUMENT
    assert archive_url("0000320193", "0000320193-25-000079", "aapl-20250927.htm") == (
        "https://www.sec.gov/Archives/edgar/data/320193/000032019325000079/aapl-20250927.htm"
    )
    # A filing agent's accession prefix never replaces the company's CIK as the folder.
    assert archive_url(CIK, "0001193125-26-000001", "d123456d8k.htm") == (
        "https://www.sec.gov/Archives/edgar/data/50863/000119312526000001/d123456d8k.htm"
    )
    assert allowed_url(DOCUMENT)


MALFORMED_ACCESSIONS = {
    "no-hyphens": "000005086326000123",
    "short": "0000050863-26-00012",
    "long": "0000050863-26-0001234",
    "underscores": "0000050863_26_000123",
    "empty": "",
    "fullwidth-digit": "0000050863-26-00012" + FULLWIDTH_ZERO,
    "newline": "0000050863-26-000123\n",
    "path": "0000050863-26-000123/../x",
    "none": None,
}


@pytest.mark.parametrize("accession", MALFORMED_ACCESSIONS.values(), ids=MALFORMED_ACCESSIONS.keys())
def test_archive_url_refuses_a_malformed_accession(accession):
    with pytest.raises(ValueError, match="^accession must be 10, 2 and 6 ASCII digits joined by hyphens$"):
        archive_url(CIK, accession, DOCUMENT_NAME)


@pytest.mark.parametrize(
    "name",
    ["", ".htm", "../x.htm", "a..b.htm", "a/b.htm", "a\\b.htm", "a?b=1", "a#b", "a%2fb", "a b.htm", "é.htm"]
    + ["a" * 201],
    ids=[
        "empty",
        "hidden",
        "parent",
        "double-dot",
        "slash",
        "backslash",
        "query",
        "fragment",
        "escape",
        "space",
        "non-ascii",
        "too-long",
    ],
)
def test_archive_url_refuses_a_primary_document_that_could_act_as_a_path(name):
    with pytest.raises(ValueError, match="^primary document must be a plain file name$"):
        archive_url(CIK, ACCESSION, name)


def test_archive_url_accepts_the_longest_plain_document_name():
    name = "a" * 196 + ".htm"
    assert archive_url(CIK, ACCESSION, name).endswith(f"/000005086326000123/{name}")


def test_filing_index_url_names_the_accession_index_page_of_its_folder():
    url = index_url(CIK, "0000050863-26-000155")
    assert url == (
        "https://www.sec.gov/Archives/edgar/data/50863/000005086326000155/0000050863-26-000155-index.htm"
    )
    assert allowed_url(url)
    assert index_url(CIK, ACCESSION) == INDEX_PAGE
    # A filing agent's accession prefix never replaces the company's CIK as the folder.
    assert index_url(CIK, "0001193125-26-000001") == (
        "https://www.sec.gov/Archives/edgar/data/50863/000119312526000001/0001193125-26-000001-index.htm"
    )
    # The index page sits in the folder of the filing's documents, beside them.
    assert INDEX_PAGE.rpartition("/")[0] == archive_url(CIK, ACCESSION, DOCUMENT_NAME).rpartition("/")[0]


@pytest.mark.parametrize("accession", MALFORMED_ACCESSIONS.values(), ids=MALFORMED_ACCESSIONS.keys())
def test_filing_index_url_refuses_a_malformed_accession(accession):
    with pytest.raises(ValueError, match="^accession must be 10, 2 and 6 ASCII digits joined by hyphens$"):
        index_url(CIK, accession)


# --------------------------------------------------------------------------- the User-Agent


@pytest.mark.parametrize("value", [None, ""], ids=["missing", "empty"])
def test_a_missing_user_agent_names_the_setting_and_where_to_add_it(value):
    with pytest.raises(EdgarError) as caught:
        check_user_agent(value)
    assert str(caught.value) == (
        'SEC_USER_AGENT is not set; add SEC_USER_AGENT="Name contact@example.com" to the repository-root .env'
    )
    assert str(caught.value) == USER_AGENT_UNSET


@pytest.mark.parametrize(
    "value",
    [
        "margin_edge tests@example.com",
        "Sample Company Name AdminContact@sample.example.com",
        "A b@c",
        "Name  contact@example.com",  # a run of spaces inside the name part
        "x" * (MAX_USER_AGENT - len(" a@example.com")) + " a@example.com",  # exactly the longest
    ],
    ids=["name-and-address", "sec-sample", "shortest", "two-spaces", "longest"],
)
def test_a_name_and_an_email_address_is_returned_unchanged(value):
    assert check_user_agent(value) == value


@pytest.mark.parametrize(
    "value",
    [
        f"{SECRET}@example.com",
        f"{SECRET}",
        f"{SECRET} contact",
        f"{SECRET} contact@",
        f"{SECRET} @example.com",
        f"{SECRET} contact@ex@ample.com",
        f"{SECRET} contact@example.com ",
        f" {SECRET} contact@example.com",
        f"{SECRET}\tcontact@example.com",
        f"{SECRET} contact@example.com\n",
        f"{SECRET} contact@example.com\x7f",
        f"{SECRET}é contact@example.com",
        f"{SECRET} contact@example.com",
        f"{SECRET} " + "x" * MAX_USER_AGENT + "@example.com",
    ],
    ids=[
        "no-name",
        "no-at",
        "no-at-in-address",
        "no-domain",
        "no-local-part",
        "two-at",
        "trailing-space",
        "leading-space",
        "tab",
        "newline",
        "delete",
        "non-ascii",
        "no-break-space",
        "too-long",
    ],
)
def test_a_malformed_user_agent_is_refused_without_echoing_it(value):
    with pytest.raises(EdgarError) as caught:
        check_user_agent(value)
    assert str(caught.value) == (
        'SEC_USER_AGENT must be a name and an email address, such as "Name contact@example.com"'
    )
    assert str(caught.value) == USER_AGENT_MALFORMED
    assert SECRET not in str(caught.value)


@pytest.mark.parametrize("value", [None, "", f"{SECRET}"], ids=["missing", "empty", "malformed"])
def test_a_client_checks_the_user_agent_before_any_request(value):
    edgar = every_url_served()
    with pytest.raises(EdgarError) as caught:
        EdgarClient(value, fetch=edgar, sleep=RecordingSleep())
    assert edgar.calls == []
    assert SECRET not in str(caught.value)


def test_the_user_agent_appears_in_no_message_and_no_representation():
    edgar = FakeEdgar({COMPANY_TICKERS_URL: status(403, "Forbidden"), SUBMISSIONS: status(429, "Too Many")})
    client = edgar_client(edgar)
    messages = []
    for request in (client.company_tickers, lambda: client.submissions(CIK)):
        with pytest.raises(EdgarError) as caught:
            request()
        messages.append(str(caught.value))
    assert all(USER_AGENT not in message for message in messages)
    assert USER_AGENT not in repr(client)
    assert repr(client) == "EdgarClient(requests=2)"


# --------------------------------------------------------------------------- headers, pacing, counter


def test_each_request_sends_exactly_the_user_agent_and_the_accepted_type():
    edgar = every_url_served()
    client = edgar_client(edgar)
    client.company_tickers()
    client.submissions(CIK)
    client.document(DOCUMENT)
    client.index_page(INDEX_PAGE)
    json_headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    document_headers = {"User-Agent": USER_AGENT, "Accept": DOCUMENT_ACCEPT}
    assert edgar.calls == [
        (COMPANY_TICKERS_URL, json_headers, JSON_LIMIT),
        (SUBMISSIONS, json_headers, JSON_LIMIT),
        (DOCUMENT, document_headers, DOCUMENT_LIMIT),
        (INDEX_PAGE, document_headers, INDEX_LIMIT),
    ]
    # No Accept-Encoding: EDGAR's bodies are taken as sent, never compressed.
    assert all(set(headers) == {"User-Agent", "Accept"} for _, headers, _ in edgar.calls)


def test_no_sleep_before_the_first_request_and_pacing_before_each_later_one():
    events: list[tuple[str, object]] = []
    edgar = every_url_served()

    def fetch(url, headers, limit):
        events.append(("GET", url))
        return edgar(url, headers, limit)

    client = EdgarClient(USER_AGENT, fetch=fetch, sleep=lambda seconds: events.append(("sleep", seconds)))
    client.company_tickers()
    client.submissions(CIK)
    client.document(DOCUMENT)
    client.index_page(INDEX_PAGE)
    assert events == [
        ("GET", COMPANY_TICKERS_URL),
        ("sleep", 0.2),
        ("GET", SUBMISSIONS),
        ("sleep", 0.2),
        ("GET", DOCUMENT),
        ("sleep", 0.2),
        ("GET", INDEX_PAGE),
    ]


def test_the_counter_includes_failed_requests_which_also_pace_the_next():
    edgar = FakeEdgar(
        {
            COMPANY_TICKERS_URL: status(503, "Service Unavailable"),
            SUBMISSIONS: EdgarError(f"GET {SUBMISSIONS}: Connection refused"),
            DOCUMENT: ok(b"<html></html>", "text/html"),
            INDEX_PAGE: status(404, "Not Found"),
        }
    )
    sleep = RecordingSleep()
    client = edgar_client(edgar, sleep)
    assert client.requests == 0
    with pytest.raises(EdgarError):
        client.company_tickers()
    assert client.requests == 1
    with pytest.raises(EdgarError, match="Connection refused"):
        client.submissions(CIK)
    assert client.requests == 2
    client.document(DOCUMENT)
    assert client.requests == 3
    with pytest.raises(EdgarError, match="HTTP 404 Not Found$"):
        client.index_page(INDEX_PAGE)
    assert client.requests == 4
    assert sleep.calls == [PACING, PACING, PACING]


def test_the_counter_is_read_only():
    client = edgar_client(every_url_served())
    with pytest.raises(AttributeError):
        client.requests = 5


def test_each_client_paces_only_its_own_requests():
    edgar = every_url_served()
    first, second = RecordingSleep(), RecordingSleep()
    edgar_client(edgar, first).company_tickers()
    edgar_client(edgar, second).company_tickers()
    assert first.calls == second.calls == []


# --------------------------------------------------------------------------- what is accepted


def test_a_fetched_body_carries_its_url_content_type_and_new_york_time():
    edgar = FakeEdgar({SUBMISSIONS: ok(b'{"cik": "0000050863"}', "application/json; charset=utf-8")})
    fetched = edgar_client(edgar).submissions(CIK)
    assert fetched == Fetched(SUBMISSIONS, NOW, "application/json; charset=utf-8", b'{"cik": "0000050863"}')


def test_a_body_without_a_content_type_has_an_empty_one():
    edgar = FakeEdgar({DOCUMENT: Response(200, "OK", {}, b"text")})
    assert edgar_client(edgar).document(DOCUMENT).content_type == ""


def test_fetched_at_is_read_from_the_clock_after_the_response(clock):
    def fetch(url, headers, limit):
        clock.tick(7)  # the response takes seven seconds
        return ok(b"{}")

    client = EdgarClient(USER_AGENT, fetch=fetch, sleep=RecordingSleep(), clock=lambda: clock.now)
    assert client.company_tickers().fetched_at == NOW + timedelta(seconds=7)


@pytest.mark.parametrize(
    "reading, expected",
    [
        (datetime(2026, 10, 8, 10, 0, 0, 123456, tzinfo=UTC), edt(2026, 10, 8, 6, 0, 0, 123456)),
        (datetime(2026, 12, 1, 17, 30, tzinfo=UTC), est(2026, 12, 1, 12, 30)),
    ],
    ids=["daylight", "standard"],
)
def test_fetched_at_is_new_york_time_whatever_zone_the_clock_reads(reading, expected):
    fetched = edgar_client(every_url_served(), clock=lambda: reading).company_tickers()
    assert fetched.fetched_at == expected
    assert fetched.fetched_at.tzname() == expected.tzname()
    assert fetched.fetched_at.utcoffset() == expected.utcoffset()


def test_a_naive_clock_reading_is_refused():
    client = edgar_client(every_url_served(), clock=lambda: datetime(2026, 10, 8, 6, 0))
    with pytest.raises(ValueError, match="^fetched_at must include a timezone$"):
        client.company_tickers()


def test_the_default_clock_reads_new_york_time():
    before = datetime.now(UTC)
    fetched = EdgarClient(USER_AGENT, fetch=every_url_served(), sleep=RecordingSleep()).company_tickers()
    after = datetime.now(UTC)
    assert before <= fetched.fetched_at <= after
    assert fetched.fetched_at.tzname() in ("EDT", "EST")
    assert fetched.fetched_at == to_eastern(fetched.fetched_at)


# --------------------------------------------------------------------------- what is refused

STATUS_PROBLEMS = {
    "forbidden": (
        status(403, "Forbidden"),
        f"GET {SUBMISSIONS}: HTTP 403 Forbidden; EDGAR refused the request: check SEC_USER_AGENT "
        "(a name and an email address) and EDGAR's fair-access policy",
    ),
    "rate-limited": (
        status(429, "Too Many Requests"),
        f"GET {SUBMISSIONS}: HTTP 429 Too Many Requests; "
        "EDGAR's rate limit: wait ten minutes and run fetch again",
    ),
    "internal-error": (
        status(500, "Internal Server Error"),
        f"GET {SUBMISSIONS}: HTTP 500 Internal Server Error; EDGAR is unavailable: wait and run fetch again",
    ),
    "unavailable": (
        status(503, "Service Unavailable"),
        f"GET {SUBMISSIONS}: HTTP 503 Service Unavailable; EDGAR is unavailable: wait and run fetch again",
    ),
    "last-server-status": (
        status(599, "Network Timeout"),
        f"GET {SUBMISSIONS}: HTTP 599 Network Timeout; EDGAR is unavailable: wait and run fetch again",
    ),
    "not-found": (status(404, "Not Found"), f"GET {SUBMISSIONS}: HTTP 404 Not Found"),
    "client-error": (status(499, "Client Closed"), f"GET {SUBMISSIONS}: HTTP 499 Client Closed"),
    "beyond-server-errors": (status(600, "Odd"), f"GET {SUBMISSIONS}: HTTP 600 Odd"),
    "no-content": (Response(204, "No Content", {}, b""), f"GET {SUBMISSIONS}: HTTP 204 No Content"),
    "redirect-not-followed": (
        status(302, REDIRECT_NOT_FOLLOWED),
        f"GET {SUBMISSIONS}: HTTP 302 redirect not followed",
    ),
    "no-reason": (
        status(503),
        f"GET {SUBMISSIONS}: HTTP 503; EDGAR is unavailable: wait and run fetch again",
    ),
    "reason-on-two-lines": (status(404, "Not\nFound"), f"GET {SUBMISSIONS}: HTTP 404 Not\\nFound"),
}


@pytest.mark.parametrize("response, message", STATUS_PROBLEMS.values(), ids=STATUS_PROBLEMS.keys())
def test_any_status_but_200_is_one_line_naming_the_url_status_and_next_step(response, message):
    client = edgar_client(FakeEdgar({SUBMISSIONS: response}))
    with pytest.raises(EdgarError) as caught:
        client.submissions(CIK)
    assert str(caught.value) == message
    assert "\n" not in str(caught.value)


@pytest.mark.parametrize(
    "headers",
    [
        {"content-encoding": "gzip"},
        {"content-encoding": "br"},
        {"content-encoding": "gzip, identity"},  # a repeated header, joined as urllib_fetch joins it
        {"content-encoding": ""},
        {"Content-Encoding": "deflate"},  # a fetch that did not lower-case its header names
    ],
    ids=["gzip", "brotli", "repeated", "empty", "capitalised-name"],
)
def test_an_encoded_body_is_refused(headers):
    client = edgar_client(FakeEdgar({DOCUMENT: Response(200, "OK", headers, b"\x1f\x8b")}))
    with pytest.raises(EdgarError) as caught:
        client.document(DOCUMENT)
    assert str(caught.value) == (
        f"GET {DOCUMENT}: the body is encoded (Content-Encoding); only identity is accepted"
    )


@pytest.mark.parametrize("encoding", ["identity", "Identity", " identity "], ids=["plain", "case", "spaces"])
def test_an_identity_encoding_is_accepted(encoding):
    client = edgar_client(FakeEdgar({DOCUMENT: ok(b"<p>x</p>", "text/html", content_encoding=encoding)}))
    assert client.document(DOCUMENT).body == b"<p>x</p>"


def test_a_body_of_exactly_the_limit_is_accepted_and_one_more_byte_is_refused():
    url = DOCUMENT
    assert edgar_client(FakeEdgar({url: ok(b"x" * 10)})).get(url, "text/html", 10).body == b"x" * 10
    with pytest.raises(EdgarError) as caught:
        edgar_client(FakeEdgar({url: ok(b"x" * 11)})).get(url, "text/html", 10)
    assert str(caught.value) == f"GET {url}: more than 10 bytes"


def test_the_named_requests_apply_their_own_limits():
    oversized_json = b"x" * (JSON_LIMIT + 1)
    client = edgar_client(FakeEdgar({COMPANY_TICKERS_URL: ok(oversized_json)}))
    with pytest.raises(EdgarError) as caught:
        client.company_tickers()
    assert str(caught.value) == f"GET {COMPANY_TICKERS_URL}: more than {JSON_LIMIT} bytes"
    # The same body is within a document's limit.
    client = edgar_client(FakeEdgar({DOCUMENT: ok(oversized_json, "text/html")}))
    assert len(client.document(DOCUMENT).body) == JSON_LIMIT + 1


def test_the_index_page_is_requested_as_a_document():
    edgar = FakeEdgar({INDEX_PAGE: ok(b"x" * INDEX_LIMIT, "text/html")})
    fetched = edgar_client(edgar).index_page(INDEX_PAGE)
    assert (fetched.url, fetched.fetched_at, fetched.content_type) == (INDEX_PAGE, NOW, "text/html")
    assert len(fetched.body) == INDEX_LIMIT  # exactly the limit is accepted
    assert edgar.calls == [(INDEX_PAGE, {"User-Agent": USER_AGENT, "Accept": DOCUMENT_ACCEPT}, INDEX_LIMIT)]
    client = edgar_client(FakeEdgar({INDEX_PAGE: ok(b"x" * (INDEX_LIMIT + 1), "text/html")}))
    with pytest.raises(EdgarError) as caught:
        client.index_page(INDEX_PAGE)
    assert str(caught.value) == f"GET {INDEX_PAGE}: more than {INDEX_LIMIT} bytes"


TEN_BYTES = b"0123456789"


def cut_short(url: str, received: int, declared: object) -> str:
    """The refusal of a body that ended after ``received`` of ``declared`` bytes."""
    return f"GET {url}: the body ended after {received} of {declared} bytes; run fetch again"


def test_a_body_of_exactly_its_content_length_is_accepted_and_one_byte_short_is_refused():
    client = edgar_client(FakeEdgar({DOCUMENT: ok(TEN_BYTES, "text/html", content_length="10")}))
    assert client.document(DOCUMENT).body == TEN_BYTES
    client = edgar_client(FakeEdgar({DOCUMENT: ok(TEN_BYTES, "text/html", content_length="11")}))
    with pytest.raises(EdgarError) as caught:
        client.document(DOCUMENT)
    assert str(caught.value) == f"GET {DOCUMENT}: the body ended after 10 of 11 bytes; run fetch again"
    assert client.requests == 1


CUT_SHORT = {
    "empty-body": ("10", b"", "10"),
    "fewer-digits": ("10", b"x" * 9, "10"),  # numerically shorter, though "9" sorts after "10" as text
    "fewer-digits-again": ("100", b"x" * 99, "100"),
    "leading-zeros": ("0011", TEN_BYTES, "11"),
    "spaces-around": (" 11\t", TEN_BYTES, "11"),
    "repeated": ("11, 11", TEN_BYTES, "11"),  # a repeated header, joined as urllib_fetch joins it
    "repeated-smaller-first": ("10, 11", TEN_BYTES, "11"),  # http.client reads by the first
    "repeated-larger-first": ("11, 10", TEN_BYTES, "11"),  # the largest value counts, not the last
    "repeated-more-digits-first": ("10, 9", b"x" * 9, "10"),  # largest by number: "9" sorts after "10"
    "repeated-beside-another-value": ("ten, 11", TEN_BYTES, "11"),
    "far-beyond-the-body": ("1000000", TEN_BYTES, "1000000"),
}


@pytest.mark.parametrize("declared, body, count", CUT_SHORT.values(), ids=CUT_SHORT.keys())
def test_a_body_shorter_than_a_content_length_of_ascii_digits_is_refused_as_cut_short(declared, body, count):
    client = edgar_client(FakeEdgar({DOCUMENT: ok(body, "text/html", content_length=declared)}))
    with pytest.raises(EdgarError) as caught:
        client.document(DOCUMENT)
    assert str(caught.value) == cut_short(DOCUMENT, len(body), count)
    assert "\n" not in str(caught.value)


@pytest.mark.parametrize(
    "declared, body",
    [
        ("10", TEN_BYTES),
        ("0010", TEN_BYTES),
        ("\t10 ", TEN_BYTES),
        ("10, 10", TEN_BYTES),
        ("0", b""),
        ("00", b""),
    ],
    ids=["exact", "leading-zeros", "spaces-around", "repeated", "zero", "zero-padded-zero"],
)
def test_a_body_that_reaches_its_content_length_is_accepted(declared, body):
    client = edgar_client(FakeEdgar({DOCUMENT: ok(body, "text/html", content_length=declared)}))
    assert client.document(DOCUMENT).body == body


@pytest.mark.parametrize(
    "declared", ["", "twenty", "20.0", "-20", "0x14"], ids=["empty", "word", "decimal", "negative", "hex"]
)
def test_a_content_length_that_is_not_ascii_digits_is_left_to_http_client(declared):
    # http.client reads none of these as a length either, so it reads such a body until the close.
    client = edgar_client(FakeEdgar({DOCUMENT: ok(TEN_BYTES, "text/html", content_length=declared)}))
    assert client.document(DOCUMENT).body == TEN_BYTES


def test_a_content_length_of_thousands_of_digits_is_compared_as_text():
    # int() refuses a decimal string of more than 4300 digits by default; no such value can break the check.
    huge = "1" + "0" * 5000
    client = edgar_client(FakeEdgar({DOCUMENT: ok(TEN_BYTES, "text/html", content_length=huge)}))
    with pytest.raises(EdgarError) as caught:
        client.document(DOCUMENT)
    assert str(caught.value) == cut_short(DOCUMENT, 10, huge)
    padded = "0" * 5000 + "10"
    client = edgar_client(FakeEdgar({DOCUMENT: ok(TEN_BYTES, "text/html", content_length=padded)}))
    assert client.document(DOCUMENT).body == TEN_BYTES


def test_a_status_an_encoding_or_an_oversized_body_is_reported_before_a_body_cut_short():
    # urllib_fetch returns an HTTP error with an empty body, while its headers keep the error page's length.
    error = Response(503, "Service Unavailable", {"content-length": "1234"}, b"")
    with pytest.raises(EdgarError) as caught:
        edgar_client(FakeEdgar({DOCUMENT: error})).document(DOCUMENT)
    assert str(caught.value) == (
        f"GET {DOCUMENT}: HTTP 503 Service Unavailable; EDGAR is unavailable: wait and run fetch again"
    )
    encoded = Response(200, "OK", {"content-encoding": "gzip", "content-length": "1234"}, b"\x1f\x8b")
    with pytest.raises(EdgarError) as caught:
        edgar_client(FakeEdgar({DOCUMENT: encoded})).document(DOCUMENT)
    assert str(caught.value) == (
        f"GET {DOCUMENT}: the body is encoded (Content-Encoding); only identity is accepted"
    )
    oversized = ok(b"x" * 11, "text/html", content_length="100")
    with pytest.raises(EdgarError) as caught:
        edgar_client(FakeEdgar({DOCUMENT: oversized})).get(DOCUMENT, "text/html", 10)
    assert str(caught.value) == f"GET {DOCUMENT}: more than 10 bytes"
    # Within the limit, a body short of a length beyond it is cut short all the same.
    short = ok(b"x" * 5, "text/html", content_length="100")
    with pytest.raises(EdgarError) as caught:
        edgar_client(FakeEdgar({DOCUMENT: short})).get(DOCUMENT, "text/html", 10)
    assert str(caught.value) == cut_short(DOCUMENT, 5, 100)


def test_every_request_refuses_a_body_cut_short_whatever_the_header_names_case():
    urls = (COMPANY_TICKERS_URL, SUBMISSIONS, DOCUMENT, INDEX_PAGE)
    # A fetch that did not lower-case its header names.
    edgar = FakeEdgar({url: Response(200, "OK", {"Content-Length": "3"}, b"{}") for url in urls})
    sleep = RecordingSleep()
    client = edgar_client(edgar, sleep)
    requests = (
        client.company_tickers,
        lambda: client.submissions(CIK),
        lambda: client.document(DOCUMENT),
        lambda: client.index_page(INDEX_PAGE),
    )
    for url, request in zip(urls, requests, strict=True):
        with pytest.raises(EdgarError) as caught:
            request()
        assert str(caught.value) == cut_short(url, 2, 3)
    # Each refused request is counted and paces the next, like any other failure.
    assert client.requests == 4 and sleep.calls == [PACING, PACING, PACING]


REFUSED_URLS = {
    "plain-http": "http://www.sec.gov/files/company_tickers.json",
    "bare-domain": "https://sec.gov/files/company_tickers.json",
    "look-alike-host": "https://www.sec.gov.example.com/files/company_tickers.json",
    "other-host": "https://efts.sec.gov/LATEST/search-index",
    "credentials": "https://user@www.sec.gov/files/company_tickers.json",
    "explicit-port": "https://www.sec.gov:443/files/company_tickers.json",
    "upper-case-host": "https://WWW.SEC.GOV/files/company_tickers.json",
    "ftp": "ftp://www.sec.gov/files/company_tickers.json",
    "file": "file:///etc/hosts",
    "relative": "/files/company_tickers.json",
    "space": "https://www.sec.gov/files/company tickers.json",
    "control": "https://www.sec.gov/files/\r\nX-Injected: 1",
    "non-ascii": "https://www.sec.gov/files/café.json",
    "empty": "",
}


@pytest.mark.parametrize("url", REFUSED_URLS.values(), ids=REFUSED_URLS.keys())
def test_only_https_urls_on_edgars_hosts_are_requested(url):
    assert not allowed_url(url)
    for request in (EdgarClient.document, EdgarClient.index_page):
        edgar = FakeEdgar({})
        sleep = RecordingSleep()
        client = edgar_client(edgar, sleep)
        with pytest.raises(EdgarError) as caught:
            request(client, url)
        assert str(caught.value).endswith(f": {REFUSED}")
        assert "\n" not in str(caught.value) and "\r" not in str(caught.value)
        assert edgar.calls == [] and sleep.calls == [] and client.requests == 0


# --------------------------------------------------------------------------- decoding


@pytest.mark.parametrize(
    "body, text, encoding",
    [
        ("Café – Intel’s AI".encode(), "Café – Intel’s AI", "utf-8"),
        (b"plain ASCII", "plain ASCII", "utf-8"),
        (b"", "", "utf-8"),
        (b"\xef\xbb\xbfwith a byte-order mark", "﻿with a byte-order mark", "utf-8"),
        (b"caf\xe9 \x96 10\xa0000", "café \x96 10 000", "latin-1"),
        (b"\xed\xa0\x80 an encoded surrogate", "í \u0080 an encoded surrogate", "latin-1"),
        (b"truncated \xe2\x80", "truncated â\u0080", "latin-1"),
    ],
    ids=["utf-8", "ascii", "empty", "bom", "windows-1252-bytes", "surrogate", "truncated-sequence"],
)
def test_decode_document_prefers_strict_utf8_then_latin1(body, text, encoding):
    assert decode_document(body) == (text, encoding)
    assert text.encode(encoding) == body  # lossless either way


def test_latin1_decoding_round_trips_every_byte():
    body = bytes(range(256))
    text, encoding = decode_document(body)
    assert encoding == "latin-1"
    assert text.encode(encoding) == body


# --------------------------------------------------------------------------- the fake itself


def test_the_fake_fails_loudly_on_a_url_it_does_not_serve():
    edgar = FakeEdgar({})
    with pytest.raises(AssertionError, match="serves no response"):
        edgar_client(edgar).company_tickers()
    assert edgar.urls == [COMPANY_TICKERS_URL]  # the call is recorded all the same


def test_the_fake_serves_json_bodies():
    edgar = FakeEdgar({COMPANY_TICKERS_URL: ok_json({"0": {"cik_str": 50863}})})
    assert json.loads(edgar_client(edgar).company_tickers().body) == {"0": {"cik_str": 50863}}


# --------------------------------------------------------------------------- urllib_fetch, offline


@pytest.fixture
def network(monkeypatch) -> Network:
    """urllib with ``FakeTransport`` in place of HTTPS; plain HTTP and sockets fail loudly."""
    return offline_network(monkeypatch)


JSON_HEADERS = {"User-Agent": USER_AGENT, "Accept": "application/json"}


def test_urllib_fetch_sends_exactly_the_given_headers_with_the_timeout(network):
    network.transport.routes[SUBMISSIONS] = Served(body=b'{"cik": 1}')
    response = urllib_fetch(SUBMISSIONS, JSON_HEADERS, JSON_LIMIT)
    assert response == Response(200, "OK", {"content-type": "application/json"}, b'{"cik": 1}')
    [sent] = network.transport.sent
    assert sent.url == SUBMISSIONS
    assert sent.method == "GET"
    assert sent.timeout == TIMEOUT
    # urllib adds Host only: no Accept-Encoding, and its own User-Agent is replaced.
    assert sent.headers == {"User-agent": USER_AGENT, "Accept": "application/json", "Host": "data.sec.gov"}


def test_urllib_fetch_lower_cases_header_names_and_joins_repeated_ones(network):
    network.transport.routes[DOCUMENT] = Served(
        headers=(
            ("Content-Type", "text/html"),
            ("Content-Encoding", "gzip"),
            ("CONTENT-ENCODING", "identity"),
        )
    )
    response = urllib_fetch(DOCUMENT, JSON_HEADERS, DOCUMENT_LIMIT)
    assert response.headers == {"content-type": "text/html", "content-encoding": "gzip, identity"}


@pytest.mark.parametrize("step", [None, 3], ids=["whole-reads", "short-reads"])
def test_urllib_fetch_reads_at_most_one_byte_more_than_the_limit(network, step):
    network.transport.routes[DOCUMENT] = Served(body=bytes(range(100)), step=step)
    response = urllib_fetch(DOCUMENT, JSON_HEADERS, 10)
    assert response.body == bytes(range(11))
    [body] = network.transport.bodies
    assert all(size is not None and 0 <= size <= 11 for size in body.asked)
    assert body.consumed == 11  # nothing beyond limit + 1 was read
    assert body.closed  # the response is closed once read


def test_urllib_fetch_returns_a_short_body_whole(network):
    network.transport.routes[DOCUMENT] = Served(body=b"0123456789")
    assert urllib_fetch(DOCUMENT, JSON_HEADERS, 10).body == b"0123456789"


@pytest.mark.parametrize(
    "code, reason",
    [(403, "Forbidden"), (404, "Not Found"), (429, "Too Many Requests"), (503, "Service Unavailable")],
)
def test_urllib_fetch_returns_an_http_error_status_with_an_empty_body(network, code, reason):
    network.transport.routes[SUBMISSIONS] = Served(
        status=code, reason=reason, headers=(("Retry-After", "600"),), body=b"<html>denied</html>"
    )
    assert urllib_fetch(SUBMISSIONS, JSON_HEADERS, JSON_LIMIT) == Response(
        code, reason, {"retry-after": "600"}, b""
    )


def test_an_http_error_reaches_the_client_as_its_status_message(network):
    network.transport.routes[SUBMISSIONS] = Served(status=403, reason="Forbidden")
    client = EdgarClient(USER_AGENT, sleep=RecordingSleep(), clock=lambda: NOW)  # the default fetch
    with pytest.raises(EdgarError, match=r"^GET \S+: HTTP 403 Forbidden; EDGAR refused the request"):
        client.submissions(CIK)
    assert network.transport.sent[0].headers["User-agent"] == USER_AGENT


@pytest.mark.parametrize(
    "location",
    [
        "https://data.sec.gov/submissions/CIK0000050863.json",
        "/cgi-bin/browse-edgar",
        "https://www.sec.gov/maintenance.htm",
        DOCUMENT,  # a redirect to itself, which urllib would follow until it saw the loop
    ],
    ids=["other-allowed-host", "relative", "same-host", "itself"],
)
@pytest.mark.parametrize("code", [301, 302, 303, 307, 308])
def test_a_redirect_within_edgar_is_refused_because_raw_keeps_the_url_requested(network, location, code):
    """A body served from another URL would be kept in raw/ under the URL requested: never followed."""
    network.transport.routes[DOCUMENT] = Served(
        status=code, reason="Moved", headers=(("Location", location),)
    )
    with pytest.raises(EdgarError) as caught:
        urllib_fetch(DOCUMENT, JSON_HEADERS, 100)
    assert str(caught.value) == f"GET {DOCUMENT}: HTTP {code} {REDIRECT_WITHIN}"
    assert "cgi-bin" not in str(caught.value) and "maintenance" not in str(caught.value)
    assert [sent.url for sent in network.transport.sent] == [DOCUMENT]  # the target is never requested
    assert all(body.closed for body in network.transport.bodies)


def test_a_redirected_filing_reaches_no_raw_file(network):
    """The client's default fetch refuses the redirect, so nothing is fetched to keep."""
    network.transport.routes[DOCUMENT] = Served(
        status=301, reason="Moved Permanently", headers=(("Location", "https://www.sec.gov/maintenance.htm"),)
    )
    network.transport.routes["https://www.sec.gov/maintenance.htm"] = Served(body=b"<html>maintenance</html>")
    client = EdgarClient(USER_AGENT, sleep=RecordingSleep(), clock=lambda: NOW)
    with pytest.raises(EdgarError, match=r"^GET \S+: HTTP 301 redirect to another EDGAR URL refused; "):
        client.document(DOCUMENT)
    assert client.requests == 1
    assert [sent.url for sent in network.transport.sent] == [DOCUMENT]


@pytest.mark.parametrize(
    "location",
    [
        "http://www.sec.gov/Archives/edgar/data/50863/x.htm",
        "https://evil.example.com/x.htm",
        "https://www.sec.gov.evil.example.com/x.htm",
        "https://user@www.sec.gov/x.htm",
        "https://www.sec.gov:8443/x.htm",
        "ftp://www.sec.gov/x.htm",
        "//evil.example.com/x.htm",
    ],
    ids=["plain-http", "other-host", "look-alike-host", "credentials", "port", "ftp", "scheme-relative"],
)
def test_a_redirect_leaving_edgar_or_https_is_refused_without_naming_the_target(network, location):
    network.transport.routes[DOCUMENT] = Served(status=302, reason="Found", headers=(("Location", location),))
    with pytest.raises(EdgarError) as caught:
        urllib_fetch(DOCUMENT, JSON_HEADERS, 100)
    assert str(caught.value) == (
        f"GET {DOCUMENT}: HTTP 302 redirect to a URL outside "
        "https://www.sec.gov, https://data.sec.gov refused"
    )
    assert "example" not in str(caught.value) and "8443" not in str(caught.value)
    assert [sent.url for sent in network.transport.sent] == [DOCUMENT]  # the target is never requested


@pytest.mark.parametrize(
    "headers",
    [(("Location", "file:///etc/hosts"),), (("Location", "javascript:alert(1)"),), ()],
    ids=["file-scheme", "script-scheme", "no-location"],
)
def test_a_redirect_urllib_declines_comes_back_as_not_followed(network, headers):
    network.transport.routes[DOCUMENT] = Served(status=302, reason="Found", headers=headers)
    response = urllib_fetch(DOCUMENT, JSON_HEADERS, 100)
    assert (response.status, response.reason, response.body) == (302, REDIRECT_NOT_FOLLOWED, b"")
    assert [sent.url for sent in network.transport.sent] == [DOCUMENT]


@pytest.mark.parametrize("url", REFUSED_URLS.values(), ids=REFUSED_URLS.keys())
def test_urllib_fetch_refuses_a_url_off_edgar_before_opening_anything(network, url):
    with pytest.raises(EdgarError) as caught:
        urllib_fetch(url, JSON_HEADERS, 100)
    assert str(caught.value).endswith(f": {REFUSED}")
    assert network.openers == 0 and network.transport.sent == []


NETWORK_FAILURES = {
    "refused": (
        urllib.error.URLError(ConnectionRefusedError(61, "Connection refused")),
        "Connection refused",
    ),
    "unresolved": (
        urllib.error.URLError(socket.gaierror(8, "nodename nor servname provided, or not known")),
        "nodename nor servname provided, or not known",
    ),
    "text-reason": (urllib.error.URLError("unknown url type: x"), "unknown url type: x"),
    "connect-timeout": (urllib.error.URLError(TimeoutError("timed out")), "no response within 60 seconds"),
    "timeout": (TimeoutError("timed out"), "no response within 60 seconds"),
    "socket-error": (OSError(50, "Network is down"), "Network is down"),
    "bare-os-error": (OSError(), "OSError"),
    "two-line-reason": (urllib.error.URLError("first\nsecond"), "first\\nsecond"),
}


@pytest.mark.parametrize("failure, reason", NETWORK_FAILURES.values(), ids=NETWORK_FAILURES.keys())
def test_a_network_failure_is_one_line_naming_the_url_and_reason(network, failure, reason):
    network.transport.routes[SUBMISSIONS] = failure
    with pytest.raises(EdgarError) as caught:
        urllib_fetch(SUBMISSIONS, JSON_HEADERS, JSON_LIMIT)
    assert str(caught.value) == f"GET {SUBMISSIONS}: {reason}"


@pytest.mark.parametrize(
    "failure, reason",
    [
        (TimeoutError("timed out"), "no response within 60 seconds"),
        (ConnectionResetError(54, "Connection reset by peer"), "Connection reset by peer"),
        (http.client.IncompleteRead(b"x", 10), "IncompleteRead(1 bytes read, 10 more expected)"),
    ],
    ids=["timeout", "reset", "incomplete"],
)
def test_a_failure_while_reading_the_body_is_one_line_too(network, failure, reason):
    network.transport.routes[SUBMISSIONS] = Served(failure=failure)
    with pytest.raises(EdgarError) as caught:
        urllib_fetch(SUBMISSIONS, JSON_HEADERS, JSON_LIMIT)
    assert str(caught.value) == f"GET {SUBMISSIONS}: {reason}"


def raw_response(headers: bytes, body: bytes = TEN_BYTES) -> Raw:
    """A status 200 HTML response with extra ``headers`` (each line ending in CRLF), then ``body``."""
    return Raw(b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n" + headers + b"\r\n" + body)


def test_urllib_fetch_returns_a_body_cut_short_for_the_client_to_refuse(network):
    network.transport.routes[DOCUMENT] = Served(
        headers=(("Content-Type", "text/html"), ("Content-Length", "11")), body=TEN_BYTES
    )
    response = urllib_fetch(DOCUMENT, JSON_HEADERS, DOCUMENT_LIMIT)
    assert response == Response(200, "OK", {"content-type": "text/html", "content-length": "11"}, TEN_BYTES)
    client = EdgarClient(USER_AGENT, sleep=RecordingSleep(), clock=lambda: NOW)  # the default fetch
    with pytest.raises(EdgarError) as caught:
        client.document(DOCUMENT)
    assert str(caught.value) == cut_short(DOCUMENT, 10, 11)


def test_http_client_returns_a_body_a_clean_close_cut_short_without_raising():
    """Why the body's length is checked: ``read(amt)`` stops at the close silently, still owing bytes."""
    parsed = http.client.HTTPResponse(RawSocket(raw_response(b"Content-Length: 11\r\n").data), method="GET")
    parsed.begin()
    assert (parsed.read(100), parsed.read(100), parsed.length) == (TEN_BYTES, b"", 1)


def test_urllib_fetch_refuses_a_body_that_ended_before_http_clients_length(network):
    network.transport.routes[DOCUMENT] = raw_response(b"Content-Length: 11\r\n")
    with pytest.raises(EdgarError) as caught:
        urllib_fetch(DOCUMENT, JSON_HEADERS, DOCUMENT_LIMIT)
    assert str(caught.value) == cut_short(DOCUMENT, 10, 11)
    network.transport.routes[DOCUMENT] = raw_response(b"Content-Length: 10\r\n")
    assert urllib_fetch(DOCUMENT, JSON_HEADERS, DOCUMENT_LIMIT).body == TEN_BYTES


@pytest.mark.parametrize(
    "headers",
    [b"Content-Length: 10\r\n", b"Content-Length: 10\r\nContent-Length: 10\r\n", b""],
    ids=["exact", "repeated", "no-length"],  # without a length, http.client reads until the close
)
def test_a_body_that_reaches_its_content_length_through_http_client_is_accepted(network, headers):
    network.transport.routes[DOCUMENT] = raw_response(headers)
    client = EdgarClient(USER_AGENT, sleep=RecordingSleep(), clock=lambda: NOW)
    assert client.document(DOCUMENT).body == TEN_BYTES


@pytest.mark.parametrize(
    "headers",
    [
        b"Content-Length: 11\r\n",
        b"Content-Length: 11 \r\n",  # http.client's int() reads the trailing space too
        b"Content-Length: 11\r\nContent-Length: 10\r\n",  # http.client reads by the first
        b"Content-Length: 10\r\nContent-Length: 11\r\n",  # the body must reach the larger
    ],
    ids=["one-byte-short", "trailing-space", "repeated-larger-first", "repeated-larger-second"],
)
def test_a_server_closing_before_its_content_length_is_refused_through_http_client(network, headers):
    network.transport.routes[DOCUMENT] = raw_response(headers)
    client = EdgarClient(USER_AGENT, sleep=RecordingSleep(), clock=lambda: NOW)
    with pytest.raises(EdgarError) as caught:
        client.document(DOCUMENT)
    assert str(caught.value) == cut_short(DOCUMENT, 10, 11)
    assert client.requests == 1 and [sent.url for sent in network.transport.sent] == [DOCUMENT]


# Values http.client's int() reads as 11, though they are not ASCII digits with spaces or tabs around them.
LENGTHS_ONLY_HTTP_CLIENT_READS = {
    "plus-sign": b"+11",
    "underscore": b"1_1",
    "vertical-tab": b"11\x0b",
    "form-feed": b"\x0c11",
    "no-break-space": b"11\xa0",
}


@pytest.mark.parametrize(
    "value", LENGTHS_ONLY_HTTP_CLIENT_READS.values(), ids=LENGTHS_ONLY_HTTP_CLIENT_READS.keys()
)
def test_a_body_short_of_a_length_only_http_client_reads_is_refused(network, value):
    # get reads no byte count from such a value; urllib_fetch checks the length http.client frames it by.
    served = ok(TEN_BYTES, "text/html", content_length=value.decode("latin-1"))
    assert edgar_client(FakeEdgar({DOCUMENT: served})).document(DOCUMENT).body == TEN_BYTES
    network.transport.routes[DOCUMENT] = raw_response(b"Content-Length: " + value + b"\r\n")
    client = EdgarClient(USER_AGENT, sleep=RecordingSleep(), clock=lambda: NOW)
    with pytest.raises(EdgarError) as caught:
        client.document(DOCUMENT)
    assert str(caught.value) == cut_short(DOCUMENT, 10, 11)
    assert client.requests == 1 and [sent.url for sent in network.transport.sent] == [DOCUMENT]


@pytest.mark.parametrize(
    "value", LENGTHS_ONLY_HTTP_CLIENT_READS.values(), ids=LENGTHS_ONLY_HTTP_CLIENT_READS.keys()
)
def test_a_body_that_reaches_a_length_only_http_client_reads_is_accepted(network, value):
    network.transport.routes[DOCUMENT] = raw_response(b"Content-Length: " + value + b"\r\n", TEN_BYTES + b"!")
    client = EdgarClient(USER_AGENT, sleep=RecordingSleep(), clock=lambda: NOW)
    assert client.document(DOCUMENT).body == TEN_BYTES + b"!"


def test_an_oversized_body_framed_by_http_client_is_reported_as_too_large_not_cut_short(network):
    network.transport.routes[DOCUMENT] = raw_response(b"Content-Length: +100\r\n", b"x" * 50)
    assert urllib_fetch(DOCUMENT, JSON_HEADERS, 10).body == b"x" * 11  # limit + 1, still owing the rest
    client = EdgarClient(USER_AGENT, sleep=RecordingSleep(), clock=lambda: NOW)
    with pytest.raises(EdgarError) as caught:
        client.get(DOCUMENT, "text/html", 10)
    assert str(caught.value) == f"GET {DOCUMENT}: more than 10 bytes"
    # A body of exactly the limit that then ended is cut short.
    network.transport.routes[DOCUMENT] = raw_response(b"Content-Length: +100\r\n", b"x" * 10)
    with pytest.raises(EdgarError) as caught:
        client.get(DOCUMENT, "text/html", 10)
    assert str(caught.value) == cut_short(DOCUMENT, 10, 100)


def test_a_length_too_long_for_http_client_is_still_compared_by_the_client(network):
    # int() refuses more than 4300 digits, so http.client reads the body until the close; get compares text.
    huge = b"1" + b"0" * 5000
    network.transport.routes[DOCUMENT] = raw_response(b"Content-Length: " + huge + b"\r\n")
    assert urllib_fetch(DOCUMENT, JSON_HEADERS, DOCUMENT_LIMIT).body == TEN_BYTES
    client = EdgarClient(USER_AGENT, sleep=RecordingSleep(), clock=lambda: NOW)
    with pytest.raises(EdgarError) as caught:
        client.document(DOCUMENT)
    assert str(caught.value) == cut_short(DOCUMENT, 10, huge.decode())


def test_http_client_fails_a_chunked_body_cut_short_itself(network):
    # http.client frames a chunked body by its chunks, and raises IncompleteRead for a missing last one.
    network.transport.routes[DOCUMENT] = raw_response(
        b"Transfer-Encoding: chunked\r\n", b"a\r\n0123456789\r\n"
    )
    with pytest.raises(EdgarError) as caught:
        urllib_fetch(DOCUMENT, JSON_HEADERS, DOCUMENT_LIMIT)
    assert str(caught.value) == f"GET {DOCUMENT}: IncompleteRead(10 bytes read)"
