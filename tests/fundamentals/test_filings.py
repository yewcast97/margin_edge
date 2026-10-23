"""script/filings.py: EDGAR's ticker map, the submissions JSON subset, seasons and their filings, index pages.

Bodies come from ``edgar_support``, laid out as EDGAR serves them (every column of
``filings.recent``, newest filing first; filing index pages with both ``tableFile``
tables). Every rejected body raises one ``ValueError`` line that names the field, row or
accession and never echoes a value read from the body; ``PRIVATE`` stands in for such a
value. Nothing here writes a file or uses the network.
"""

import json
import re
import traceback
from dataclasses import FrozenInstanceError, replace
from datetime import date, timedelta

import pytest

from market_state_research.fundamentals.script.filings import (
    ACCESSION_PATTERN,
    CIK_PATTERN,
    EXHIBIT_PATTERN,
    EXHIBIT_PREFIX,
    INDEX_COLUMNS,
    INDEX_TABLE,
    MAX_DESCRIPTION,
    PENDING,
    PRIMARY_DOCUMENT,
    RECENT_COLUMNS,
    Dated,
    ExhibitRow,
    Filing,
    FilingIndex,
    NoPeriodicFilings,
    RecentRow,
    Season,
    Seasons,
    Skipped,
    Submissions,
    Window,
    default_window,
    is_primary_document,
    lookup_cik,
    parse_filing_index,
    parse_submissions,
    release_items,
    rendered_document,
    select_seasons,
)
from market_state_research.fundamentals.script.text import html_text

from .edgar_support import (
    CIK,
    COMMENTARY_BULLET,
    COMMENTARY_CAPEX,
    COMMENTARY_COLON,
    COMMENTARY_DEMAND,
    COMMENTARY_ITEMS,
    COMMENTARY_LEAD_IN,
    COMMENTARY_SUPPLY,
    COMMENTARY_TITLE,
    COMPANY,
    DATA_FILES,
    EIGHT_K_OTHER,
    EIGHT_K_Q1,
    EIGHT_K_Q2,
    ENTITY_NAME,
    EXHIBITS,
    FORM_4,
    GRAPHIC_ROWS,
    HIDDEN_DIV_TEXT,
    HIDDEN_FACT,
    INDEX_HEADER,
    OLD_TEN_K,
    OLD_TEN_Q,
    PROXY,
    Q1_EXHIBITS,
    Q2_EXHIBITS,
    RECENT,
    RELEASE_BOUNDARIES,
    RELEASE_CAPEX,
    RELEASE_DEMAND,
    RELEASE_GUIDANCE,
    RELEASE_OUTLOOK,
    RELEASE_OUTLOOK_LINES,
    RELEASE_RAMP,
    RELEASE_SUPPLY,
    RELEASE_TITLES,
    SCRIPT_TEXT,
    SEGMENTS,
    STYLE_TEXT,
    TEN_K,
    TEN_K_CAPEX,
    TEN_K_CUSTOMERS,
    TEN_K_DEMAND,
    TEN_K_FINANCING,
    TEN_K_PERIOD,
    TEN_K_PRICING,
    TEN_K_SPLIT,
    TEN_K_SUPPLY,
    TEN_Q_1,
    TEN_Q_2,
    TEN_Q_CAPEX,
    TEN_Q_DEMAND,
    TEN_Q_PERIOD,
    TEN_Q_SPLIT,
    TEN_Q_SUPPLY,
    IndexRow,
    Row,
    accepted_at,
    commentary_html,
    exhibit_html,
    filing_index_html,
    plain_page,
    submissions_document,
    submissions_json,
    ten_k_html,
    ten_q_html,
    tickers_json,
)
from .support import TODAY

PRIVATE = "private-value"  # stands in for a body value that must never be echoed
FULLWIDTH_ZERO = "０"  # FULLWIDTH DIGIT ZERO: a Unicode decimal digit that int() accepts
PREFIX = f"submissions CIK{CIK}: "
# Row indices of edgar_support.RECENT (newest first).
(
    FORM_4_ROW,
    LATEST_TEN_Q,
    Q2_RELEASE,
    FIRST_TEN_Q,
    Q1_RELEASE,
    PROXY_ROW,
    OTHER_8K,
    CURRENT_TEN_K,
    EARLIER_TEN_Q,
    EARLIER_TEN_K,
) = range(10)
# The workflow tests' window: their three periods.
WINDOW = Window(date(2025, 12, 1), TODAY)
# A later history: the third quarter's release, filed before its 10-Q, then the 10-Q itself.
EIGHT_K_Q3 = Row(
    "8-K", "0000050863-26-000089", date(2026, 10, 6), date(2026, 10, 6), "intc-20261006.htm", "2.02,9.01"
)
TEN_Q_3 = Row("10-Q", "0000050863-26-000090", date(2026, 10, 7), date(2026, 9, 26), "intc-20260926.htm")
PENDING_RECENT = (EIGHT_K_Q3, *RECENT)
LATER_RECENT = (TEN_Q_3, EIGHT_K_Q3, *RECENT)
# The 8-K of EDGAR's verified index page, and the page's two document tables (both formDiv
# blocks) copied from it byte for byte; only the long lines are split across string pieces.
LIVE_ACCESSION = "0000050863-26-000155"
LIVE_PAGE = "\n".join(
    (
        '<div class="formDiv">',
        (
            '   <div style="padding: 0px 0px 4px 0px; font-size: 12px; margin: 0px 2px 0px 5px; width: '
            '100%; overflow:hidden">'
        ),
        "      <p>Document Format Files</p>",
        '      <table class="tableFile" summary="Document Format Files">',
        "         <tr>",
        (
            '            <th scope="col" style="width: 5%;"><acronym title="Sequence Number">Seq</acronym>'
            "</th>"
        ),
        '            <th scope="col" style="width: 40%;">Description</th>',
        '            <th scope="col" style="width: 20%;">Document</th>',
        '            <th scope="col" style="width: 10%;">Type</th>',
        '            <th scope="col">Size</th>',
        "         </tr>",
        "         <tr>",
        '            <td scope="row">1</td>',
        '            <td scope="row">8-K</td>',
        (
            '            <td scope="row"><a href="/ix?doc=/Archives/edgar/data/50863/000005086326000155/'
            'intc-20260723.htm">intc-20260723.htm</a> &nbsp;&nbsp;<span style="color: green">iXBRL</span>'
            "</td>"
        ),
        '            <td scope="row">8-K</td>',
        '            <td scope="row">26721</td>',
        "         </tr>",
        '         <tr class="evenRow">',
        '            <td scope="row">2</td>',
        '            <td scope="row">EX-99.1</td>',
        (
            '            <td scope="row"><a href="/Archives/edgar/data/50863/000005086326000155/'
            'q226earningsrelease.htm">q226earningsrelease.htm</a></td>'
        ),
        '            <td scope="row">EX-99.1</td>',
        '            <td scope="row">410408</td>',
        "         </tr>",
        "         <tr>",
        '            <td scope="row">6</td>',
        '            <td scope="row"></td>',
        (
            '            <td scope="row"><a href="/Archives/edgar/data/50863/000005086326000155/'
            'intc-20260723_g1.jpg">intc-20260723_g1.jpg</a></td>'
        ),
        '            <td scope="row">GRAPHIC</td>',
        '            <td scope="row">5170</td>',
        "         </tr>",
        '         <tr class="evenRow">',
        '            <td scope="row">7</td>',
        '            <td scope="row"></td>',
        (
            '            <td scope="row"><a href="/Archives/edgar/data/50863/000005086326000155/'
            'unboxedlogo_20202a.jpg">unboxedlogo_20202a.jpg</a></td>'
        ),
        '            <td scope="row">GRAPHIC</td>',
        '            <td scope="row">24502</td>',
        "         </tr>",
        "         <tr>",
        '            <td scope="row">&nbsp;</td>',
        '            <td scope="row">Complete submission text file</td>',
        (
            '            <td scope="row"><a href="/Archives/edgar/data/50863/000005086326000155/'
            '0000050863-26-000155.txt">0000050863-26-000155.txt</a></td>'
        ),
        '            <td scope="row">&nbsp;</td>',
        '            <td scope="row">632944</td>',
        "         </tr>",
        "      </table>\t",
        "   </div>",
        "</div>",
        '<div class="formDiv">',
        (
            '   <div style="padding: 0px 0px 4px 0px; font-size: 12px; margin: 0px 2px 0px 5px; width: '
            '100%; overflow:hidden">'
        ),
        "      <p>Data Files</p>",
        '      <table class="tableFile" summary="Data Files">',
        "         <tr>",
        (
            '            <th scope="col" style="width: 5%;"><acronym title="Sequence Number">Seq</acronym>'
            "</th>"
        ),
        '            <th scope="col" style="width: 40%;">Description</th>',
        '            <th scope="col" style="width: 20%;">Document</th>',
        '            <th scope="col" style="width: 10%;">Type</th>',
        '            <th scope="col">Size</th>',
        "         </tr>",
        "         <tr>",
        '            <td scope="row">3</td>',
        '            <td scope="row">XBRL TAXONOMY EXTENSION SCHEMA DOCUMENT</td>',
        (
            '            <td scope="row"><a href="/Archives/edgar/data/50863/000005086326000155/'
            'intc-20260723.xsd">intc-20260723.xsd</a></td>'
        ),
        '            <td scope="row">EX-101.SCH</td>',
        '            <td scope="row">1789</td>',
        "         </tr>",
        '         <tr class="evenRow">',
        '            <td scope="row">4</td>',
        '            <td scope="row">XBRL TAXONOMY EXTENSION LABEL LINKBASE DOCUMENT</td>',
        (
            '            <td scope="row"><a href="/Archives/edgar/data/50863/000005086326000155/'
            'intc-20260723_lab.xml">intc-20260723_lab.xml</a></td>'
        ),
        '            <td scope="row">EX-101.LAB</td>',
        '            <td scope="row">21885</td>',
        "         </tr>",
        "         <tr>",
        '            <td scope="row">5</td>',
        '            <td scope="row">XBRL TAXONOMY EXTENSION PRESENTATION LINKBASE DOCUMENT</td>',
        (
            '            <td scope="row"><a href="/Archives/edgar/data/50863/000005086326000155/'
            'intc-20260723_pre.xml">intc-20260723_pre.xml</a></td>'
        ),
        '            <td scope="row">EX-101.PRE</td>',
        '            <td scope="row">12516</td>',
        "         </tr>",
        '         <tr class="evenRow">',
        '            <td scope="row">17</td>',
        '            <td scope="row"><b>EXTRACTED</b> XBRL INSTANCE DOCUMENT</td>',
        (
            '            <td scope="row"><a href="/Archives/edgar/data/50863/000005086326000155/'
            'intc-20260723_htm.xml">intc-20260723_htm.xml</a></td>'
        ),
        '            <td scope="row">XML</td>',
        '            <td scope="row">2721</td>',
        "         </tr>",
        "      </table>\t",
        "   </div>",
        "</div>",
    )
)


def full_traceback(error: BaseException) -> str:
    return "".join(traceback.format_exception(error))


def failure(call, *arguments) -> str:
    """The one-line ``ValueError`` message ``call`` rejects its body with; it never echoes ``PRIVATE``."""
    with pytest.raises(ValueError) as caught:
        call(*arguments)
    message = str(caught.value)
    assert "\n" not in message
    assert PRIVATE not in full_traceback(caught.value)
    return message


def filing(row: Row) -> Filing:
    assert row.period is not None
    return Filing(row.form, row.accession, row.filed, row.period, row.primary_document)


def dated(row: Row) -> Dated:
    """The filing ``row`` as Rule B dates it: an 8-K or a Form 4 by its report date, any other form
    by its filing date."""
    day = row.period if row.form in ("8-K", "4") else row.filed
    assert day is not None
    return Dated(row.form, row.accession, row.filed, day, row.items, row.primary_document)


def recent_row(row: Row) -> RecentRow:
    return RecentRow(row.form, row.accession, row.filed, row.period, row.primary_document, row.items)


def parsed_row(row: Row) -> RecentRow:
    """The row as ``parse_submissions`` reads it from ``submissions_json``: with its acceptance time."""
    return replace(recent_row(row), accepted=accepted_at(row))


def submissions(*rows: Row) -> Submissions:
    return Submissions(cik=CIK, entity_name=ENTITY_NAME, recent=tuple(recent_row(row) for row in rows))


def seasons_of(*rows: Row) -> Seasons:
    return select_seasons(submissions(*rows))


def placed(seasons: Seasons) -> dict[date, tuple[Dated, ...]]:
    return {season.period: season.filings for season in seasons.seasons}


def eight_k(number: int, filed: date, event: date | None, items: str = "2.02,9.01", form: str = "8-K") -> Row:
    return Row(form, f"0000050863-26-{number:06d}", filed, event, f"intc-8k-{number}.htm", items)


def entry(cik: object = 50863, ticker: object = "INTC", title: object = "INTEL CORP") -> dict:
    return {"cik_str": cik, "ticker": ticker, "title": title}


def tickers_body(*entries: object) -> str:
    return json.dumps({str(position): item for position, item in enumerate(entries)})


def changed(change) -> str:
    """The default submissions body after ``change`` edits its dict in place."""
    document = submissions_document()
    change(document)
    return json.dumps(document)


def with_cell(column: str, index: int, value: object) -> str:
    def change(document: dict) -> None:
        document["filings"]["recent"][column][index] = value

    return changed(change)


def q2_page(exhibits=Q2_EXHIBITS, **options) -> str:
    return filing_index_html(EIGHT_K_Q2, exhibits, **options)


def exhibit_row(seq: str = "2", document: str = "q226earningsrelease.htm", **changes) -> IndexRow:
    return replace(IndexRow(seq, "EX-99.1", document, "EX-99.1", "410408"), **changes)


def read_index(body: str, accession: str = EIGHT_K_Q2.accession) -> FilingIndex:
    return parse_filing_index(body, CIK, accession)


def index_failure(body: str, accession: str = EIGHT_K_Q2.accession) -> str:
    """The message a page is refused with, after its accession prefix."""
    message = failure(parse_filing_index, body, CIK, accession)
    prefix = f"filing index {accession}: "
    assert message.startswith(prefix)
    return message.removeprefix(prefix)


# --------------------------------------------------------------------------- patterns


@pytest.mark.parametrize(
    ("pattern", "value", "matches"),
    [
        (CIK_PATTERN, CIK, True),
        (CIK_PATTERN, "50863", False),
        (CIK_PATTERN, "00000508630", False),
        (CIK_PATTERN, FULLWIDTH_ZERO * 10, False),
        (ACCESSION_PATTERN, "0000050863-26-000012", True),
        (ACCESSION_PATTERN, "000005086326000012", False),
        (ACCESSION_PATTERN, "0000050863-26-00012", False),
        (ACCESSION_PATTERN, "0000050863-26-" + FULLWIDTH_ZERO * 6, False),
    ],
)
def test_cik_and_accession_patterns_admit_ascii_digits_in_edgar_grouping(pattern, value, matches):
    assert (re.fullmatch(pattern, value, re.ASCII) is not None) is matches


@pytest.mark.parametrize(
    ("name", "valid"),
    [
        ("intc-20251227.htm", True),
        ("d123456d10k.htm", True),
        ("0000050863-26-000012.txt", True),
        ("a" * 200, True),
        ("a" * 201, False),
        ("", False),
        (".intc.htm", False),
        ("-intc.htm", False),
        ("../intc.htm", False),
        ("intc..htm", False),
        ("xslF345X05/form4.xml", False),
        ("intc\\x.htm", False),
        ("intc 2025.htm", False),
        ("intc.htm\n", False),
        ("intç.htm", False),
        (None, False),
        (5, False),
    ],
)
def test_primary_documents_are_plain_ascii_file_names(name, valid):
    assert is_primary_document(name) is valid
    if isinstance(name, str) and ".." not in name:
        assert (PRIMARY_DOCUMENT.fullmatch(name) is not None) is valid


# --------------------------------------------------------------------------- company_tickers.json


def test_lookup_returns_the_ten_digit_cik_of_the_listed_ticker():
    body = tickers_json()
    assert lookup_cik(body, "INTC") == CIK
    assert lookup_cik(body, "AAPL") == "0000320193"
    assert lookup_cik(body, "NVDA") == "0001045810"


@pytest.mark.parametrize("ticker", ["intc", "Intc", "iNTC", "INTC"])
def test_lookup_matches_tickers_without_regard_to_case(ticker):
    assert lookup_cik(tickers_json(), ticker) == CIK
    assert lookup_cik(tickers_json([(50863, "intc", "INTEL CORP")]), "INTC") == CIK


@pytest.mark.parametrize(
    ("cik", "expected"),
    [(1, "0000000001"), (50863, "0000050863"), (1045810, "0001045810"), (9_999_999_999, "9999999999")],
)
def test_lookup_pads_the_cik_to_ten_digits(cik, expected):
    assert lookup_cik(tickers_json([(cik, "EXMP", "EXAMPLE")]), "EXMP") == expected


@pytest.mark.parametrize(
    "ticker",
    [
        pytest.param("MSFT", id="not-listed"),
        pytest.param("INT", id="prefix"),
        pytest.param("INTCX", id="longer"),
        pytest.param("BRK.B", id="dot-is-not-hyphen"),
        # "ı".upper() is "I": a match after non-ASCII case folding is no match
        pytest.param("ıntc", id="dotless-i"),
    ],
)
def test_lookup_returns_none_for_a_ticker_that_is_not_listed(ticker):
    body = tickers_json([*((50863, "INTC", "INTEL CORP"),), (1067983, "BRK-B", "BERKSHIRE HATHAWAY INC")])
    assert lookup_cik(body, ticker) is None


def test_a_listed_non_ascii_ticker_never_matches_by_case_folding():
    assert lookup_cik(tickers_json([(1, "ıNTC", "DOTLESS")]), "INTC") is None


def test_repeated_entries_that_agree_on_the_cik_are_one_answer():
    body = tickers_json([(50863, "INTC", "INTEL CORP"), (50863, "intc", "INTEL CORP")])
    assert lookup_cik(body, "INTC") == CIK


@pytest.mark.parametrize("repeat", ["INTC", "intc"])
def test_entries_that_disagree_on_the_cik_are_refused(repeat):
    body = tickers_json([(50863, "INTC", "INTEL CORP"), (1, "AAA", "A"), (50864, repeat, PRIVATE)])
    assert failure(lookup_cik, body, "INTC") == (
        "company_tickers.json: the ticker matches entries with 2 different CIKs"
    )
    assert lookup_cik(body, "AAA") == "0000000001"  # other tickers are unaffected


TRAILING = tickers_body(entry()) + " " + PRIVATE  # a valid map followed by stray text


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        pytest.param("", "invalid JSON: Expecting value (line 1, column 1)", id="empty"),
        pytest.param(
            "{",
            "invalid JSON: Expecting property name enclosed in double quotes (line 1, column 2)",
            id="cut",
        ),
        pytest.param(
            TRAILING,
            f"invalid JSON: Extra data (line 1, column {len(TRAILING) - len(PRIVATE) + 1})",
            id="trailing",
        ),
        pytest.param("[]", "expected a JSON object of company entries", id="array"),
        pytest.param(json.dumps(PRIVATE), "expected a JSON object of company entries", id="string"),
        pytest.param("{}", "lists no companies", id="no-entries"),
        pytest.param(tickers_body(entry(), PRIVATE), "entry 1 must be an object", id="string-entry"),
        pytest.param(tickers_body(entry(), [PRIVATE]), "entry 1 must be an object", id="list-entry"),
        pytest.param(
            json.dumps({PRIVATE: {"cik_str": 1}}),
            "entry 0 must have exactly the keys cik_str, ticker and title",
            id="missing-keys",
        ),
        pytest.param(
            tickers_body(entry(), {**entry(), "exchange": PRIVATE}),
            "entry 1 must have exactly the keys cik_str, ticker and title",
            id="unknown-key",
        ),
        pytest.param(
            tickers_body(entry(), {**entry(), PRIVATE: 1}),
            "entry 1 must have exactly the keys cik_str, ticker and title",
            id="unknown-private-key",
        ),
        *(
            pytest.param(
                tickers_body(entry(), entry(cik=cik)),
                "entry 1: cik_str must be an integer from 1 to 9999999999",
                id=f"cik-{name}",
            )
            for name, cik in (
                ("text", "50863"),
                ("private-text", PRIVATE),
                ("fraction", 50863.0),
                ("boolean", True),
                ("null", None),
                ("zero", 0),
                ("negative", -50863),
                ("eleven-digits", 10**10),
            )
        ),
        pytest.param(
            tickers_body(entry(), entry()).replace("50863", "1" * 5000, 1),
            "entry 0: cik_str must be an integer from 1 to 9999999999",
            id="cik-longer-than-int-allows",
        ),
        pytest.param(
            tickers_body(entry(), entry(cik=None)).replace("null", "5e4"),
            "entry 1: cik_str must be an integer from 1 to 9999999999",
            id="cik-exponent",
        ),
        pytest.param(
            tickers_body(entry(), entry(ticker=5)), "entry 1: ticker must be a string", id="number-ticker"
        ),
        pytest.param(
            tickers_body(entry(), entry(ticker=None)), "entry 1: ticker must be a string", id="null-ticker"
        ),
        pytest.param(
            tickers_body(entry(), entry(title=[PRIVATE])), "entry 1: title must be a string", id="list-title"
        ),
        pytest.param(
            '{"0": {"cik_str": NaN, "ticker": "X", "title": "Y"}}', "invalid JSON: NaN is not JSON", id="nan"
        ),
        pytest.param('{"0": {"cik_str": Infinity}}', "invalid JSON: Infinity is not JSON", id="infinity"),
        pytest.param(
            '{"0": {"cik_str": 1, "ticker": "A", "title": "B", "ticker": "INTC"}}',
            "invalid JSON: an object repeats a key",
            id="repeated-key",
        ),
        pytest.param("[" * 100_000, "invalid JSON: nested too deeply", id="deep"),
    ],
)
def test_malformed_ticker_maps_are_refused_without_echoing_values(body, expected):
    assert failure(lookup_cik, body, "INTC") == f"company_tickers.json: {expected}"


def test_the_whole_ticker_map_is_checked_even_after_the_ticker_is_found():
    body = tickers_body(entry(), entry(), entry(cik=PRIVATE))
    assert failure(lookup_cik, body, "INTC") == (
        "company_tickers.json: entry 2: cik_str must be an integer from 1 to 9999999999"
    )


def test_entry_keys_never_need_to_count_from_zero():
    body = json.dumps({"7": entry(), "x": entry(1, "AAA", "A")})
    assert lookup_cik(body, "INTC") == CIK
    assert lookup_cik(body, "AAA") == "0000000001"


# --------------------------------------------------------------------------- submissions JSON


def test_parse_keeps_every_recent_row_in_edgar_order():
    parsed = parse_submissions(submissions_json(), CIK)
    assert parsed == Submissions(cik=CIK, entity_name=ENTITY_NAME, recent=tuple(map(parsed_row, RECENT)))
    assert parsed.recent[PROXY_ROW].period is None  # an empty reportDate
    assert parsed.recent[FORM_4_ROW].primary_document == "xslF345X05/wk-form4_1754251234.xml"


def test_columns_and_keys_the_domain_does_not_read_are_ignored():
    def change(document: dict) -> None:
        recent = document["filings"]["recent"]
        recent["size"] = PRIVATE
        recent["isXBRL"] = [None]
        del recent["core_type"]
        recent[PRIVATE] = {PRIVATE: [1.5, None, 10**40]}
        del document["filings"]["files"]
        document["tickers"] = PRIVATE
        del document["sic"]

    assert parse_submissions(changed(change), CIK).recent == tuple(map(parsed_row, RECENT))


def test_empty_recent_columns_give_no_rows():
    assert parse_submissions(submissions_json(rows=()), CIK).recent == ()


@pytest.mark.parametrize(
    "value",
    [
        pytest.param("50863", id="edgar-text"),
        pytest.param(CIK, id="padded-text"),
        pytest.param(50863, id="integer"),
    ],
)
def test_the_body_cik_may_be_text_or_an_integer_naming_the_requested_cik(value):
    body = changed(lambda document: document.update(cik=value))
    assert parse_submissions(body, CIK).cik == CIK


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        pytest.param("50864", "cik is not the requested CIK", id="other-text"),
        pytest.param(50864, "cik is not the requested CIK", id="other-integer"),
        pytest.param(-50863, "cik is not the requested CIK", id="negative"),
        pytest.param(10**10 + 50863, "cik is not the requested CIK", id="eleven-digit-integer"),
        pytest.param("00000508630", "cik must be a string of digits or an integer", id="eleven-digit-text"),
        pytest.param("", "cik must be a string of digits or an integer", id="empty"),
        pytest.param(" 50863", "cik must be a string of digits or an integer", id="space"),
        pytest.param("+50863", "cik must be a string of digits or an integer", id="sign"),
        pytest.param("5086" + FULLWIDTH_ZERO, "cik must be a string of digits or an integer", id="fullwidth"),
        pytest.param(PRIVATE, "cik must be a string of digits or an integer", id="private-text"),
        pytest.param(50863.0, "cik must be a string of digits or an integer", id="fraction"),
        pytest.param(True, "cik must be a string of digits or an integer", id="boolean"),
        pytest.param(None, "cik must be a string of digits or an integer", id="null"),
        pytest.param([50863], "cik must be a string of digits or an integer", id="list"),
    ],
)
def test_a_body_for_another_or_no_cik_is_refused(value, expected):
    body = changed(lambda document: document.update(cik=value))
    assert failure(parse_submissions, body, CIK) == PREFIX + expected


@pytest.mark.parametrize("cik", ["50863", "00000508630", FULLWIDTH_ZERO * 10, "", 50863, None])
def test_the_requested_cik_must_be_ten_ascii_digits(cik):
    assert failure(parse_submissions, submissions_json(), cik) == "submissions: the CIK must be ten digits"


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        pytest.param(lambda d: d.pop("cik"), "cik is missing", id="no-cik"),
        pytest.param(lambda d: d.pop("name"), "name must be a non-empty printable string", id="no-name"),
        pytest.param(
            lambda d: d.update(name=""), "name must be a non-empty printable string", id="empty-name"
        ),
        pytest.param(
            lambda d: d.update(name="   "), "name must be a non-empty printable string", id="blank-name"
        ),
        pytest.param(
            lambda d: d.update(name=f"{PRIVATE}\nCORP"),
            "name must be a non-empty printable string",
            id="two-lines",
        ),
        pytest.param(
            lambda d: d.update(name=[PRIVATE]), "name must be a non-empty printable string", id="list-name"
        ),
        pytest.param(lambda d: d.pop("filings"), "filings is missing", id="no-filings"),
        pytest.param(lambda d: d.update(filings=[PRIVATE]), "filings must be an object", id="list-filings"),
        pytest.param(lambda d: d["filings"].pop("recent"), "filings.recent is missing", id="no-recent"),
        pytest.param(
            lambda d: d["filings"].update(recent=PRIVATE),
            "filings.recent must be an object",
            id="text-recent",
        ),
    ],
)
def test_top_level_fields_are_required_with_their_types(change, expected):
    assert failure(parse_submissions, changed(change), CIK) == PREFIX + expected


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        pytest.param("", "invalid JSON: Expecting value (line 1, column 1)", id="empty"),
        pytest.param(submissions_json()[:-1], "invalid JSON: Expecting ',' delimiter", id="cut"),
        pytest.param("[]", "expected a JSON object", id="array"),
        pytest.param(json.dumps(PRIVATE), "expected a JSON object", id="string"),
        pytest.param(
            submissions_json().replace('"sic":"3674"', '"sic":NaN'), "invalid JSON: NaN is not JSON", id="nan"
        ),
        pytest.param(
            submissions_json().replace('"sic":"3674"', '"name":"OTHER"'),
            "invalid JSON: an object repeats a key",
            id="repeated-key",
        ),
        pytest.param('{"a":' * 100_000, "invalid JSON: nested too deeply", id="deep"),
    ],
)
def test_bodies_that_are_not_one_strict_json_object_are_refused(body, expected):
    assert failure(parse_submissions, body, CIK).startswith(PREFIX + expected)


@pytest.mark.parametrize("column", RECENT_COLUMNS)
def test_every_read_column_is_required(column):
    body = changed(lambda document: document["filings"]["recent"].pop(column))
    assert failure(parse_submissions, body, CIK) == f"{PREFIX}filings.recent.{column} is missing"


@pytest.mark.parametrize("column", RECENT_COLUMNS)
@pytest.mark.parametrize("value", [PRIVATE, {PRIVATE: PRIVATE}, None])
def test_every_read_column_must_be_a_list(column, value):
    body = changed(lambda document: document["filings"]["recent"].update({column: value}))
    assert failure(parse_submissions, body, CIK) == f"{PREFIX}filings.recent.{column} must be a list"


@pytest.mark.parametrize("column", RECENT_COLUMNS)
@pytest.mark.parametrize("value", [None, 20260724, [PRIVATE], {"text": PRIVATE}, True])
def test_every_read_cell_must_be_a_string(column, value):
    body = with_cell(column, Q2_RELEASE, value)
    assert (
        failure(parse_submissions, body, CIK)
        == f"{PREFIX}filings.recent.{column}[{Q2_RELEASE}] must be a string"
    )


@pytest.mark.parametrize("column", RECENT_COLUMNS)
def test_read_columns_must_have_one_length(column):
    body = changed(lambda document: document["filings"]["recent"][column].pop())
    rows = len(RECENT)
    counts = ", ".join(f"{name} {rows - 1 if name == column else rows}" for name in RECENT_COLUMNS)
    assert failure(parse_submissions, body, CIK) == (
        f"{PREFIX}filings.recent columns must have one length; lengths: {counts}"
    )


@pytest.mark.parametrize(
    "value",
    [
        pytest.param("000005086326000062", id="no-dashes"),
        pytest.param("0000050863-26-00062", id="short-sequence"),
        pytest.param("50863-26-000062", id="unpadded-filer"),
        pytest.param(" 0000050863-26-000062", id="space"),
        pytest.param("0000050863-26-00006" + FULLWIDTH_ZERO, id="fullwidth"),
        pytest.param("", id="empty"),
        pytest.param(PRIVATE, id="private-text"),
    ],
)
def test_accession_numbers_must_be_ten_two_six_digits_on_every_row(value):
    assert failure(parse_submissions, with_cell("accessionNumber", Q2_RELEASE, value), CIK) == (
        f"{PREFIX}filings.recent.accessionNumber[{Q2_RELEASE}] must be an accession number (10-2-6 digits)"
    )


def test_an_accession_number_may_appear_only_once():
    body = with_cell("accessionNumber", PROXY_ROW, TEN_Q_2.accession)
    assert failure(parse_submissions, body, CIK) == (
        f"{PREFIX}filings.recent.accessionNumber[{PROXY_ROW}] repeats row {LATEST_TEN_Q}"
    )


@pytest.mark.parametrize(
    "value",
    [
        pytest.param("20260723", id="basic-format"),
        pytest.param("2026-W30-4", id="week-date"),
        pytest.param("2026-7-23", id="unpadded"),
        pytest.param("2026-02-30", id="no-such-day"),
        pytest.param("2026-07-23T00:00:00", id="date-time"),
        pytest.param("2026-07-2" + FULLWIDTH_ZERO, id="fullwidth"),
        pytest.param("", id="empty"),
        pytest.param(PRIVATE, id="private-text"),
    ],
)
def test_filing_dates_must_be_iso_dates_on_every_row(value):
    assert failure(parse_submissions, with_cell("filingDate", Q2_RELEASE, value), CIK) == (
        f"{PREFIX}filings.recent.filingDate[{Q2_RELEASE}] must be a YYYY-MM-DD date"
    )


@pytest.mark.parametrize("value", ["2026/07/23", "20260723", "2026-13-01", PRIVATE])
def test_report_dates_must_be_iso_dates_or_empty_on_every_row(value):
    assert failure(parse_submissions, with_cell("reportDate", FORM_4_ROW, value), CIK) == (
        f"{PREFIX}filings.recent.reportDate[{FORM_4_ROW}] must be a YYYY-MM-DD date or empty"
    )


@pytest.mark.parametrize(
    ("index", "form"), [(LATEST_TEN_Q, "10-Q"), (CURRENT_TEN_K, "10-K"), (EARLIER_TEN_K, "10-K")]
)
def test_a_ten_k_or_ten_q_must_name_its_period(index, form):
    assert failure(parse_submissions, with_cell("reportDate", index, ""), CIK) == (
        f"{PREFIX}filings.recent.reportDate[{index}] is empty; a {form} must name its period"
    )


@pytest.mark.parametrize(("index", "form"), [(LATEST_TEN_Q, "10-Q"), (CURRENT_TEN_K, "10-K")])
def test_a_ten_k_or_ten_q_cannot_report_a_period_after_its_filing(index, form):
    filed = RECENT[index].filed
    assert parse_submissions(with_cell("reportDate", index, filed.isoformat()), CIK)  # the same day is fine
    late = date.fromordinal(filed.toordinal() + 1).isoformat()
    assert failure(parse_submissions, with_cell("reportDate", index, late), CIK) == (
        f"{PREFIX}filings.recent.reportDate[{index}] is after the {form}'s filing date"
    )


@pytest.mark.parametrize(
    "value",
    [
        pytest.param("", id="empty"),
        pytest.param("../intc-20260627.htm", id="parent"),
        pytest.param("intc..htm", id="dot-dot"),
        pytest.param("2026q2/intc-20260627.htm", id="path"),
        pytest.param("intc\\20260627.htm", id="backslash"),
        pytest.param(".intc-20260627.htm", id="hidden"),
        pytest.param("intc 20260627.htm", id="space"),
        pytest.param("intc-2026062" + FULLWIDTH_ZERO + ".htm", id="fullwidth"),
        pytest.param("a" * 201, id="too-long"),
        pytest.param(PRIVATE + "?.htm", id="query"),
    ],
)
@pytest.mark.parametrize(("index", "form"), [(LATEST_TEN_Q, "10-Q"), (CURRENT_TEN_K, "10-K")])
def test_a_ten_k_or_ten_q_needs_a_plain_primary_document_name(value, index, form):
    assert failure(parse_submissions, with_cell("primaryDocument", index, value), CIK) == (
        f"{PREFIX}filings.recent.primaryDocument[{index}] must be a plain document file name for a {form}"
    )


def test_other_forms_keep_any_primary_document_and_period():
    rows = (
        Row("10-K/A", "0000050863-26-000070", date(2026, 8, 1), None, "amendment/intc.htm"),
        Row("10-KT", "0000050863-26-000071", date(2026, 8, 2), date(2026, 9, 30), ""),
        Row("8-K", "0000050863-26-000072", date(2026, 8, 3), date(2026, 8, 4), "../x"),
        TEN_K,
    )
    assert parse_submissions(submissions_json(rows=rows), CIK).recent == tuple(map(parsed_row, rows))


def test_the_items_column_is_read_and_kept_as_edgar_writes_it():
    parsed = parse_submissions(submissions_json(), CIK)
    assert [row.items for row in parsed.recent] == [row.items for row in RECENT]
    assert parsed.recent[Q2_RELEASE].items == "2.02,9.01"
    assert parsed.recent[OTHER_8K].items == "5.02,9.01"
    assert parsed.recent[LATEST_TEN_Q].items == ""
    spaced = parse_submissions(with_cell("items", FORM_4_ROW, " 2.02 , 9.01 "), CIK)
    assert spaced.recent[FORM_4_ROW].items == " 2.02 , 9.01 "  # verbatim, never normalised
    longest = parse_submissions(with_cell("items", Q2_RELEASE, "9" * 200), CIK)
    assert longest.recent[Q2_RELEASE].items == "9" * 200


@pytest.mark.parametrize(
    "value",
    [
        pytest.param(PRIVATE + "\n", id="line-break"),
        pytest.param(PRIVATE + "\t2.02", id="tab"),
        pytest.param(PRIVATE + "\x7f", id="delete"),
        pytest.param(PRIVATE + " ", id="no-break-space"),
        pytest.param(PRIVATE + "é", id="non-ascii"),
        pytest.param(PRIVATE + "２.０２", id="fullwidth"),
        pytest.param(PRIVATE + "x" * (201 - len(PRIVATE)), id="one-too-many"),
        pytest.param(PRIVATE * 16, id="too-long"),
    ],
)
@pytest.mark.parametrize("index", [Q2_RELEASE, FORM_4_ROW, CURRENT_TEN_K])
def test_items_must_be_printable_ascii_on_every_row_and_are_never_echoed(value, index):
    assert failure(parse_submissions, with_cell("items", index, value), CIK) == (
        f"{PREFIX}filings.recent.items[{index}] must be printable ASCII of at most 200 characters"
    )


@pytest.mark.parametrize(
    ("column", "index", "value"),
    [
        ("accessionNumber", FORM_4_ROW, PRIVATE),
        ("filingDate", CURRENT_TEN_K, PRIVATE),
        ("reportDate", Q2_RELEASE, PRIVATE),
        ("primaryDocument", FIRST_TEN_Q, f"../{PRIVATE}"),
        ("items", Q2_RELEASE, PRIVATE + "\n"),
    ],
)
def test_rejected_cells_are_named_by_column_and_row_but_never_echoed(column, index, value):
    message = failure(parse_submissions, with_cell(column, index, value), CIK)
    assert message.startswith(f"{PREFIX}filings.recent.{column}[{index}] ")


# --------------------------------------------------------------------------- seasons


def test_every_exact_10_k_and_10_q_is_a_season_oldest_first_with_its_filings():
    seasons = select_seasons(parse_submissions(submissions_json(), CIK))
    assert [season.filing.accession for season in seasons.seasons] == [
        row.accession for row in (OLD_TEN_K, OLD_TEN_Q, TEN_K, TEN_Q_1, TEN_Q_2)
    ]
    assert [season.period for season in seasons.seasons] == [
        date(2024, 12, 28),
        date(2025, 9, 27),
        TEN_K_PERIOD,
        date(2026, 3, 28),
        TEN_Q_PERIOD,
    ]
    by_season = {day: [item.accession for item in items] for day, items in placed(seasons).items()}
    # The 8-K of 2026-02-09 and the proxy filed 2026-03-27 fall after the 10-K's period end and
    # before the first quarter's; each release in its quarter; the Form 4 dated 2026-07-30 after
    # the newest 10-Q was filed (2026-07-24) is pending.
    assert by_season == {
        date(2024, 12, 28): [],
        date(2025, 9, 27): [],
        TEN_K_PERIOD: [EIGHT_K_OTHER.accession, PROXY.accession],
        date(2026, 3, 28): [EIGHT_K_Q1.accession],
        TEN_Q_PERIOD: [EIGHT_K_Q2.accession],
    }
    assert [item.accession for item in seasons.pending] == [FORM_4.accession]
    assert seasons.skipped == () and seasons.oldest_filed == OLD_TEN_K.filed


def test_the_seasons_from_hand_built_rows_are_exact_values():
    assert seasons_of(*RECENT) == Seasons(
        seasons=(
            Season(filing(OLD_TEN_K), ()),
            Season(filing(OLD_TEN_Q), ()),
            Season(filing(TEN_K), (dated(EIGHT_K_OTHER), dated(PROXY))),
            Season(filing(TEN_Q_1), (dated(EIGHT_K_Q1),)),
            Season(filing(TEN_Q_2), (dated(EIGHT_K_Q2),)),
        ),
        pending=(dated(FORM_4),),
        skipped=(),
        oldest_filed=OLD_TEN_K.filed,
    )


def test_row_order_does_not_change_the_selected_seasons():
    expected = seasons_of(*RECENT)
    assert seasons_of(*reversed(RECENT)) == expected
    assert seasons_of(*RECENT[3:], *RECENT[:3]) == expected
    assert seasons_of(*LATER_RECENT) == seasons_of(*reversed(LATER_RECENT))


@pytest.mark.parametrize(
    "form",
    [
        "10-K/A",
        "10-KT",
        "10-KT/A",
        "10-K405",
        "10-Q/A",
        "10-QT",
        "NT 10-Q",
        "NT 10-K",
        "10-k",
        "10-q",
        " 10-K",
        "10-Q ",
    ],
)
def test_only_exact_10_k_and_10_q_rows_are_seasons(form):
    same = Row(form, "0000050863-26-000080", date(2026, 8, 10), TEN_Q_PERIOD, "intc-amend.htm")
    new = Row(form, "0000050863-26-000081", date(2026, 8, 11), date(2026, 7, 31), "intc-other.htm")
    found = seasons_of(same, new, *RECENT)
    assert [season.filing for season in found.seasons] == [
        season.filing for season in seasons_of(*RECENT).seasons
    ]


@pytest.mark.parametrize(
    "repeat",
    [
        pytest.param(Row("10-Q", "0000050863-26-000070", date(2026, 8, 7), TEN_Q_PERIOD, "x.htm"), id="10-q"),
        pytest.param(Row("10-K", "0000050863-26-000070", date(2026, 8, 7), TEN_Q_PERIOD, "x.htm"), id="10-k"),
        pytest.param(replace(OLD_TEN_Q, accession="0000050863-25-000202", filed=date(2025, 11, 3)), id="old"),
    ],
)
def test_two_filings_for_one_season_are_refused_wherever_they_are_listed(repeat):
    assert repeat.period is not None
    message = failure(select_seasons, submissions(repeat, *RECENT))
    assert message == f"{PREFIX}two filings report the period {repeat.period.isoformat()}"


def test_of_several_repeated_periods_the_oldest_is_named():
    repeats = (
        replace(TEN_Q_2, accession="0000050863-26-000070", filed=date(2026, 8, 7)),
        replace(OLD_TEN_K, accession="0000050863-25-000010", filed=date(2025, 2, 3)),
    )
    for rows in ((*repeats, *RECENT), (*RECENT, *reversed(repeats))):
        assert (
            failure(select_seasons, submissions(*rows)) == f"{PREFIX}two filings report the period 2024-12-28"
        )


def test_no_periodic_filing_names_the_count_and_the_forms_seen():
    rows = (
        EIGHT_K_Q2,
        Row("10-K/A", "0000050863-26-000020", date(2026, 2, 2), TEN_K_PERIOD, "intc-a.htm"),
        Row("10-Q/A", "0000050863-26-000021", date(2026, 2, 3), date(2025, 9, 27), "intc-b.htm"),
        Row("NT 10-Q", "0000050863-26-000022", date(2026, 2, 4), date(2025, 9, 27), "intc-c.htm"),
        EIGHT_K_Q1,
    )
    with pytest.raises(NoPeriodicFilings) as caught:
        seasons_of(*rows)
    assert isinstance(caught.value, ValueError)
    assert str(caught.value) == (
        "no 10-K or 10-Q among the 5 recent filings; forms seen: 10-K/A, 10-Q/A, 8-K, NT 10-Q"
    )


def test_no_periodic_filing_among_no_filings():
    with pytest.raises(NoPeriodicFilings) as caught:
        seasons_of()
    assert str(caught.value) == "no 10-K or 10-Q among the 0 recent filings; forms seen: none"


def test_the_forms_seen_are_cut_to_two_hundred_characters_on_one_line():
    rows = [
        Row(f"FORM-{number:03d}\n", f"0000050863-26-{number:06d}", date(2026, 1, 1), None, "x.htm")
        for number in range(60)
    ]
    with pytest.raises(NoPeriodicFilings) as caught:
        seasons_of(*rows)
    message = str(caught.value)
    assert "\n" not in message
    listed = ", ".join(sorted(row.form for row in rows))[:200]
    assert message == (
        f"no 10-K or 10-Q among the 60 recent filings; forms seen: {listed.replace(chr(10), chr(92) + 'n')}"
    )


def test_a_hand_built_filing_row_without_a_period_is_refused():
    with pytest.raises(ValueError) as caught:
        seasons_of(replace(TEN_K, period=None))
    assert str(caught.value) == "a season's filing must be a 10-K or 10-Q row with a period"


def test_a_season_is_found_by_its_end_date_and_its_predecessors_newest_first():
    seasons = seasons_of(*RECENT)
    found = seasons.get(date(2026, 3, 28))
    assert found is not None and found.filing == filing(TEN_Q_1) and found.period == TEN_Q_1.period
    assert seasons.get(date(2026, 3, 27)) is None
    assert seasons.get(TEN_Q_1.filed) is None  # a filing date is not a season
    assert seasons.index(TEN_Q_PERIOD) == 4 and seasons.index(date(2026, 3, 27)) is None
    newest = seasons.seasons[-1]
    assert [season.period for season in seasons.before(newest, 2)] == [date(2026, 3, 28), TEN_K_PERIOD]
    assert seasons.before(seasons.seasons[0], 4) == ()
    assert len(seasons.before(newest, 10)) == 4


# --------------------------------------------------------------------------- windows


@pytest.mark.parametrize(
    ("day", "admitted"),
    [
        (date(2025, 11, 30), False),
        (date(2025, 12, 1), True),
        (TEN_K_PERIOD, True),
        (TODAY, True),
        (TODAY + timedelta(days=1), False),
    ],
)
def test_a_window_admits_the_days_between_its_dates_both_included(day, admitted):
    assert WINDOW.admits(day) is admitted


def test_a_window_cannot_end_before_it_starts():
    assert Window(TODAY, TODAY).admits(TODAY)  # one day is a window
    with pytest.raises(ValueError) as caught:
        Window(TODAY, TODAY - timedelta(days=1))
    assert str(caught.value) == "the window's from date is after its to date"


@pytest.mark.parametrize(
    ("today", "start"),
    [
        pytest.param(date(2026, 10, 8), date(2024, 10, 8), id="today"),
        pytest.param(date(2026, 10, 9), date(2024, 10, 9), id="plan-day"),
        pytest.param(date(2028, 2, 29), date(2026, 2, 28), id="leap-day"),
        pytest.param(date(2026, 2, 28), date(2024, 2, 28), id="before-a-leap-day"),
        pytest.param(date(2026, 3, 1), date(2024, 3, 1), id="after-a-leap-day"),
        pytest.param(date(2027, 1, 1), date(2025, 1, 1), id="new-year"),
    ],
)
def test_the_default_window_is_the_two_years_up_to_today(today, start):
    assert default_window(today) == Window(start, today)


def test_the_window_selects_seasons_by_their_end_date_oldest_first():
    seasons = seasons_of(*RECENT)
    assert [season.filing for season in seasons.within(WINDOW)] == [
        filing(TEN_K),
        filing(TEN_Q_1),
        filing(TEN_Q_2),
    ]
    assert seasons.within(default_window(TODAY)) == seasons.seasons  # 2024-10-08 to 2026-10-08


@pytest.mark.parametrize(
    ("window", "expected"),
    [
        pytest.param(Window(TEN_K_PERIOD, TODAY), (TEN_K, TEN_Q_1, TEN_Q_2), id="from-the-period-end"),
        pytest.param(
            Window(TEN_K_PERIOD + timedelta(days=1), TODAY), (TEN_Q_1, TEN_Q_2), id="from-the-day-after"
        ),
        pytest.param(Window(WINDOW.start, date(2026, 3, 28)), (TEN_K, TEN_Q_1), id="to-the-period-end"),
        pytest.param(Window(WINDOW.start, date(2026, 3, 27)), (TEN_K,), id="to-the-day-before"),
        pytest.param(Window(date(2026, 3, 28), date(2026, 3, 28)), (TEN_Q_1,), id="one-day"),
    ],
)
def test_the_window_boundaries_are_inclusive(window, expected):
    assert [season.filing for season in seasons_of(*RECENT).within(window)] == [
        filing(row) for row in expected
    ]


@pytest.mark.parametrize(
    ("start", "truncated"),
    [
        pytest.param(OLD_TEN_K.filed - timedelta(days=1), True, id="before-the-oldest-filing"),
        pytest.param(OLD_TEN_K.filed, False, id="on-the-oldest-filing"),
        pytest.param(OLD_TEN_K.filed + timedelta(days=1), False, id="after-the-oldest-filing"),
        pytest.param(date(2024, 10, 8), True, id="default-window"),
    ],
)
def test_a_window_before_the_oldest_recent_filing_is_reported_truncated(start, truncated):
    seasons = seasons_of(*RECENT)
    assert seasons.oldest_filed == OLD_TEN_K.filed
    assert seasons.truncated(Window(start, TODAY)) is truncated


def test_the_oldest_recent_filing_of_any_form_bounds_the_listing():
    old = Row("13F-HR", "0001209191-24-000001", date(2024, 6, 3), None, "form.xml")
    seasons = seasons_of(*RECENT, old)
    assert seasons.oldest_filed == date(2024, 6, 3)
    assert not seasons.truncated(Window(date(2024, 10, 8), TODAY))
    assert Seasons(seasons=(), pending=(), skipped=(), oldest_filed=None).truncated(WINDOW)


# --------------------------------------------------------------------------- the filings of a season


@pytest.mark.parametrize(
    ("items", "parts"),
    [
        ("2.02,9.01", ("2.02", "9.01")),
        (" 2.02 , 9.01 ", ("2.02", "9.01")),
        ("2.02", ("2.02",)),
        ("", ()),
        (",,", ()),
        ("5.02,,9.01", ("5.02", "9.01")),
    ],
)
def test_release_items_are_split_on_commas_stripped_and_never_empty(items, parts):
    assert release_items(items) == parts


@pytest.mark.parametrize(
    ("items", "is_release"),
    [
        ("2.02,9.01", True),
        ("9.01, 2.02", True),
        ("2.02", True),
        ("12.02,9.01", False),
        ("2.021", False),
        ("5.02", False),
    ],
)
def test_an_8_k_is_a_release_only_when_its_items_name_item_2_02_exactly(items, is_release):
    season = seasons_of(TEN_K, TEN_Q_1, eight_k(30, date(2026, 2, 10), date(2026, 2, 10), items)).seasons[0]
    assert [item.release for item in season.filings] == [is_release]
    assert len(season.releases) == int(is_release) and len(season.eight_ks) == 1


def test_an_8_k_and_a_form_4_are_dated_by_their_report_date_every_other_form_by_its_filing_date():
    proxy = Row("DEF 14A", "0000050863-26-000061", date(2026, 3, 23), date(2026, 5, 13), "proxy2026.htm")
    holder = Row(
        "SCHEDULE 13G/A",
        "0000102909-26-000197",
        date(2026, 1, 30),
        None,
        "xslSCHEDULE_13G_X01/primary_doc.xml",
    )
    old_holder = Row("SC 13G/A", "0001104659-26-021208", date(2026, 2, 13), None, "tv01202-intelcorp.htm")
    insider = Row("4", "0000050863-26-000086", date(2026, 2, 3), date(2026, 1, 30), "xslF345X05/form4.xml")
    notice = Row("NT 10-Q", "0000050863-26-000099", date(2026, 5, 7), None, "nt10q.htm")
    shelf = Row("S-3ASR", "0000050863-26-000023", date(2026, 1, 23), None, "forms-3asr.htm")
    ignored = Row("13F-HR", "0000050863-26-000024", date(2026, 2, 14), None, "form13f.xml")
    seasons = seasons_of(TEN_K, TEN_Q_1, TEN_Q_2, proxy, holder, old_holder, insider, notice, shelf, ignored)
    found = {
        item.accession: (item.dated, season.period) for season in seasons.seasons for item in season.filings
    }
    assert found == {
        proxy.accession: (
            date(2026, 3, 23),
            TEN_K_PERIOD,
        ),  # its reportDate is the meeting's: after its filing
        holder.accession: (date(2026, 1, 30), TEN_K_PERIOD),
        old_holder.accession: (date(2026, 2, 13), TEN_K_PERIOD),
        insider.accession: (date(2026, 1, 30), TEN_K_PERIOD),
        notice.accession: (date(2026, 5, 7), date(2026, 3, 28)),
        shelf.accession: (date(2026, 1, 23), TEN_K_PERIOD),
    }
    season = seasons.get(TEN_K_PERIOD)
    assert season is not None
    assert [item.form for item in season.fetched] == ["SCHEDULE 13G/A", "4", "SC 13G/A", "DEF 14A"]
    assert [item.form for item in season.of_forms(("S-3ASR", "DEF 14A"))] == ["S-3ASR", "DEF 14A"]


def test_an_item_2_02_8_k_without_its_event_date_makes_the_ticker_unsupported():
    message = failure(select_seasons, submissions(eight_k(30, date(2026, 2, 10), None), *RECENT))
    assert message == (
        f"{PREFIX}filings.recent.reportDate[0] is empty; an 8-K with Item 2.02 must name its event date"
    )
    late = eight_k(31, date(2026, 2, 10), date(2026, 2, 11))
    assert failure(select_seasons, submissions(late, *RECENT)) == (
        f"{PREFIX}filings.recent.reportDate[0] is after the 8-K's filing date; an 8-K with Item 2.02 "
        "must name its event date"
    )


def test_a_row_without_the_date_or_document_it_needs_is_skipped_and_listed():
    undated = eight_k(30, date(2026, 2, 10), None, "5.02,9.01")
    late_form4 = Row("4", "0000050863-26-000087", date(2026, 2, 3), date(2026, 2, 4), "xslF345X05/form4.xml")
    pathlike = Row("DEF 14A", "0000050863-26-000088", date(2026, 3, 1), None, "../proxy.htm")
    seasons = seasons_of(undated, late_form4, pathlike, *RECENT)
    assert seasons.skipped == (
        Skipped("8-K", undated.accession, undated.filed, "its reportDate is empty"),
        Skipped("4", late_form4.accession, late_form4.filed, "its reportDate is after the 4's filing date"),
        Skipped(
            "DEF 14A", pathlike.accession, pathlike.filed, "its primaryDocument is no file fetch can request"
        ),
    )
    assert placed(seasons) == placed(seasons_of(*RECENT))


@pytest.mark.parametrize(
    ("primary", "raw"),
    [
        ("intc-20260627.htm", "intc-20260627.htm"),
        ("xslF345X06/form4.xml", "form4.xml"),
        ("xslSCHEDULE_13G_X02/primary_doc.xml", "primary_doc.xml"),
        ("wk-form4_1754251234.xml", "wk-form4_1754251234.xml"),
        ("xslF345X06/../form4.xml", None),
        ("other/form4.xml", None),
        ("xslF345X06/sub/form4.xml", None),
        ("", None),
    ],
)
def test_a_rendered_primary_document_names_the_raw_file_in_the_filings_folder(primary, raw):
    assert rendered_document(primary) == raw


def test_a_dated_filing_names_its_raw_document():
    item = dated(FORM_4)
    assert item.document == "wk-form4_1754251234.xml" and item.fetched and not item.release
    with pytest.raises(ValueError, match="no primary document"):
        _ = replace(item, primary_document="a/b/c").document


# --------------------------------------------------------------------------- Rule B


def test_a_filing_is_placed_in_the_latest_season_ending_before_its_date():
    seasons = seasons_of(*RECENT)
    assert seasons.place(date(2026, 3, 29)) == seasons.get(date(2026, 3, 28))
    assert seasons.place(date(2026, 3, 28)) == seasons.get(TEN_K_PERIOD)  # a period end belongs before it
    assert seasons.place(TEN_Q_2.filed) == seasons.get(TEN_Q_PERIOD)  # the newest, up to its filing date
    assert seasons.place(TEN_Q_2.filed + timedelta(days=1)) == PENDING
    assert seasons.place(OLD_TEN_K.period) is None  # on or before the oldest listed season end: dropped


def test_a_pending_filing_joins_its_season_once_a_later_one_is_listed():
    seasons = seasons_of(*PENDING_RECENT)
    assert [item.accession for item in seasons.pending] == [FORM_4.accession, EIGHT_K_Q3.accession]
    later = seasons_of(*LATER_RECENT)
    # The Form 4 of 2026-07-30 now belongs to the second quarter; the release of 2026-10-06 to the third.
    assert [item.accession for item in placed(later)[TEN_Q_PERIOD]] == [
        EIGHT_K_Q2.accession,
        FORM_4.accession,
    ]
    assert [item.accession for item in placed(later)[date(2026, 9, 26)]] == [EIGHT_K_Q3.accession]
    assert later.pending == ()


@pytest.mark.parametrize(
    "window",
    [
        pytest.param(WINDOW, id="window"),
        pytest.param(Window(TEN_Q_PERIOD, TEN_Q_PERIOD), id="on-the-newest-end"),
    ],
)
def test_every_pending_filing_is_listed_for_a_window_ending_on_or_after_the_newest_season_end(window):
    seasons = seasons_of(*PENDING_RECENT)
    assert seasons.pending_in(window) == seasons.pending


def test_no_pending_filing_is_listed_for_a_window_ending_before_the_newest_season_end():
    seasons = seasons_of(*PENDING_RECENT)
    assert seasons.pending_in(Window(WINDOW.start, TEN_Q_PERIOD - timedelta(days=1))) == ()
    assert Seasons(seasons=(), pending=(), skipped=(), oldest_filed=None).pending_in(WINDOW) == ()


def test_the_filings_of_a_season_are_ordered_by_date_filing_date_and_accession():
    rows = (
        eight_k(33, date(2026, 2, 12), date(2026, 2, 10), "8.01"),
        eight_k(32, date(2026, 2, 11), date(2026, 2, 10), "7.01"),
        eight_k(31, date(2026, 2, 11), date(2026, 2, 10), "5.02"),
        eight_k(30, date(2026, 2, 11), date(2026, 2, 9), "5.07"),
    )
    season = seasons_of(TEN_K, TEN_Q_1, *rows).seasons[0]
    assert [item.accession[-2:] for item in season.filings] == ["30", "31", "32", "33"]


def test_selected_seasons_are_immutable_values():
    seasons = seasons_of(*RECENT)
    with pytest.raises(FrozenInstanceError):
        seasons.seasons[0].filing.period = TODAY  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        seasons.pending = ()  # type: ignore[misc]


# --------------------------------------------------------------------------- acceptance times


def test_the_acceptance_time_is_read_as_new_york_time():
    rows = parse_submissions(
        with_cell("acceptanceDateTime", Q2_RELEASE, "2026-07-23T20:09:00.000Z"), CIK
    ).recent
    accepted = rows[Q2_RELEASE].accepted
    assert accepted is not None and accepted.isoformat() == "2026-07-23T16:09:00-04:00"
    winter = parse_submissions(
        with_cell("acceptanceDateTime", Q2_RELEASE, "2026-01-22T21:10:56.000Z"), CIK
    ).recent
    assert str(winter[Q2_RELEASE].accepted) == "2026-01-22 16:10:56-05:00"
    empty = parse_submissions(with_cell("acceptanceDateTime", Q2_RELEASE, ""), CIK).recent
    assert empty[Q2_RELEASE].accepted is None


@pytest.mark.parametrize(
    ("value", "problem"),
    [
        ("2026-07-23T20:09:00Z", "must be empty or a UTC time YYYY-MM-DDTHH:MM:SS.fffZ"),
        ("2026-07-23 20:09:00.000Z", "must be empty or a UTC time YYYY-MM-DDTHH:MM:SS.fffZ"),
        ("2026-07-23T20:09:00.000+00:00", "must be empty or a UTC time YYYY-MM-DDTHH:MM:SS.fffZ"),
        ("2026-02-30T20:09:00.000Z", "is not a time that exists"),
        ("2026-07-23T24:09:00.000Z", "is not a time that exists"),
    ],
)
def test_an_acceptance_time_outside_its_grammar_is_refused_without_echo(value, problem):
    message = failure(parse_submissions, with_cell("acceptanceDateTime", Q2_RELEASE, value), CIK)
    assert message == f"{PREFIX}filings.recent.acceptanceDateTime[{Q2_RELEASE}] {problem}"


# --------------------------------------------------------------------------- filing index pages


def test_the_index_page_lists_each_exhibit_with_its_sequence_description_document_and_type():
    assert read_index(q2_page()) == FilingIndex(
        exhibits=(
            ExhibitRow(
                sequence=2, description="EX-99.1", document="q226earningsrelease.htm", exhibit="EX-99.1"
            ),
            ExhibitRow(
                sequence=3, description="EX-99.2", document="q226cfocommentary.htm", exhibit="EX-99.2"
            ),
        )
    )
    q1 = filing_index_html(EIGHT_K_Q1, Q1_EXHIBITS)
    assert read_index(q1, EIGHT_K_Q1.accession) == FilingIndex(
        exhibits=(ExhibitRow(2, "EX-99.1", "q126earningsrelease.htm", "EX-99.1"),)
    )


def test_the_tables_copied_from_edgars_verified_page_are_read_as_verified():
    # Its graphics, its complete submission and its Data Files table hold no exhibit.
    assert read_index(LIVE_PAGE, LIVE_ACCESSION) == FilingIndex(
        exhibits=(ExhibitRow(2, "EX-99.1", "q226earningsrelease.htm", "EX-99.1"),)
    )


def test_exhibits_are_the_ex_99_rows_in_seq_order_whatever_the_page_order():
    rows = (
        exhibit_row("10", "ten.htm", type="EX-99.10"),
        exhibit_row("3", "three.htm", type="EX-99.3"),
        exhibit_row("9", "nine.htm", type="EX-99.9"),
        exhibit_row("2", "two.htm"),
    )
    exhibits = read_index(q2_page(rows)).exhibits
    assert [(row.sequence, row.document, row.exhibit) for row in exhibits] == [
        (2, "two.htm", "EX-99.1"),
        (3, "three.htm", "EX-99.3"),
        (9, "nine.htm", "EX-99.9"),
        (10, "ten.htm", "EX-99.10"),
    ]


@pytest.mark.parametrize(
    "kind", ["EX-99", "EX-99.1", "EX-99.01", "EX-99.1A", "EX-99.1.2", "EX-99.CHARTER", "EX-99." + "9" * 16]
)
def test_exhibit_types_are_copied_verbatim(kind):
    (row,) = read_index(q2_page((exhibit_row(type=kind, description=kind),))).exhibits
    assert (row.exhibit, row.description) == (kind, kind)
    assert re.fullmatch(EXHIBIT_PATTERN, kind)  # what the index page reader admits


@pytest.mark.parametrize(
    "kind", ["EX-10.1", "ex-99", "ex-99.1", "Ex-99.1", "EX-9.1", "EX-101.SCH", "GRAPHIC", "", "XML"]
)
def test_only_types_starting_with_ex_99_are_exhibits(kind):
    path_like = exhibit_row("4", "../not-read.htm", type=kind, linked=False)
    assert read_index(q2_page((*Q2_EXHIBITS, path_like))) == read_index(q2_page())
    assert EXHIBIT_PREFIX == "EX-99"


def test_an_exhibit_typed_ex_99_without_a_suffix_is_read_like_any_other():
    bare = exhibit_row("4", "q226presentation.htm", type="EX-99", description="Investor presentation")
    copy = exhibit_row("5", "q226presentation.pdf", type="EX-99")
    assert read_index(q2_page((*Q2_EXHIBITS, bare, copy))) == FilingIndex(
        exhibits=(
            *read_index(q2_page()).exhibits,
            ExhibitRow(4, "Investor presentation", "q226presentation.htm", "EX-99"),
        )
    )
    (only,) = read_index(q2_page((exhibit_row(type="EX-99"),))).exhibits
    assert (only.sequence, only.document, only.exhibit) == (2, "q226earningsrelease.htm", "EX-99")


@pytest.mark.parametrize(
    "kind",
    [
        pytest.param("EX-99.", id="dot-without-suffix"),
        pytest.param("EX-99.1 " + PRIVATE, id="two-words"),
        pytest.param("EX-99 " + PRIVATE, id="bare-then-a-word"),
        pytest.param("EX-99.(a)", id="brackets"),
        pytest.param("EX-99." + "9" * 17, id="too-long"),
        pytest.param("EX-99.1é", id="non-ascii"),
        pytest.param("EX-99-1", id="hyphen"),
        pytest.param("EX-99A", id="letter-without-dot"),
        pytest.param("EX-990", id="digit-without-dot"),
        pytest.param("EX-99_1", id="underscore"),
    ],
)
def test_a_type_starting_with_ex_99_outside_the_exhibit_grammar_is_refused(kind):
    assert index_failure(q2_page((exhibit_row(type=kind),))) == (
        "row 3: Type must be EX-99, or EX-99. followed by 1 to 16 letters, digits or dots"
    )
    assert kind.startswith(EXHIBIT_PREFIX) and not re.fullmatch(EXHIBIT_PATTERN, kind)


def test_the_exhibit_grammar():
    assert f"^{EXHIBIT_PATTERN}$" == r"^EX-99(?:\.[0-9A-Za-z.]{1,16})?$"


def test_a_release_without_an_ex_99_row_has_no_exhibits():
    assert read_index(q2_page(())) == FilingIndex(exhibits=())
    bare = q2_page((), graphics=(), data_files=(), complete_submission=False)
    assert 'summary="Data Files"' not in bare
    assert read_index(bare) == FilingIndex(exhibits=())


def test_the_cover_graphic_and_complete_submission_rows_are_not_exhibits():
    graphics = (
        IndexRow("8", PRIVATE, "../" + PRIVATE + ".jpg", "GRAPHIC", "5170", href="https://example.com/x"),
        IndexRow("9", "", "logo.jpg", "GRAPHIC", "x", linked=False),
        IndexRow(PRIVATE, "", "", "EX-10.1", ""),
    )
    page = q2_page(graphics=graphics)
    assert "/ix?doc=" in page and "Complete submission text file" in page
    assert read_index(page) == read_index(q2_page())


def test_the_data_files_table_is_never_read_for_exhibits():
    data_files = (
        *DATA_FILES,
        IndexRow(PRIVATE, PRIVATE, "../" + PRIVATE, "EX-99.9", "1", href="https://example.com/"),
    )
    page = q2_page(data_files=data_files).replace('<td scope="row">1789</td>', "")  # a four-cell row too
    assert read_index(page) == read_index(q2_page())


def test_an_ex_99_row_linked_through_the_ix_viewer_still_names_its_plain_document():
    folder = "/Archives/edgar/data/50863/000005086326000062"
    viewer = exhibit_row(href=f"/ix?doc={folder}/q226earningsrelease.htm")
    (row,) = read_index(q2_page((viewer,))).exhibits
    assert row.document == "q226earningsrelease.htm"
    labelled = q2_page((exhibit_row(),)).replace(
        ">q226earningsrelease.htm</a></td>",
        '>q226earningsrelease.htm</a> &nbsp;&nbsp;<span style="color: green">iXBRL</span></td>',
    )
    (row,) = read_index(labelled).exhibits
    assert row.document == "q226earningsrelease.htm"


@pytest.mark.parametrize(
    "document",
    [
        pytest.param(f"../{PRIVATE}.htm", id="parent"),
        pytest.param(f"{PRIVATE}/b.htm", id="path"),
        pytest.param("", id="empty"),
        pytest.param(f".{PRIVATE}.htm", id="hidden"),
        pytest.param(f"{PRIVATE}..htm", id="dot-dot"),
        pytest.param("..", id="parent-only"),
        pytest.param(PRIVATE * 16, id="too-long"),
        pytest.param(f"{PRIVATE}é.htm", id="non-ascii"),
        pytest.param(f"{PRIVATE}?.htm", id="query"),
    ],
)
def test_an_exhibit_document_that_could_act_as_a_path_is_refused_without_echo(document):
    assert index_failure(q2_page((exhibit_row(document=document),))) == (
        "row 3: the document must be a plain file name"
    )


LINK_ERROR = "row 3: the Document cell must link only to its document in the filing's folder"


@pytest.mark.parametrize(
    "href",
    [
        pytest.param(
            "/Archives/edgar/data/50863/000005086326000040/q226earningsrelease.htm", id="other-filing"
        ),
        pytest.param("/Archives/edgar/data/50864/000005086326000062/q226earningsrelease.htm", id="other-cik"),
        pytest.param(
            "/Archives/edgar/data/0000050863/000005086326000062/q226earningsrelease.htm", id="padded-cik"
        ),
        pytest.param(
            "https://www.sec.gov/Archives/edgar/data/50863/000005086326000062/q226earningsrelease.htm",
            id="absolute",
        ),
        pytest.param(f"/Archives/edgar/data/50863/000005086326000062/{PRIVATE}.htm", id="other-document"),
        pytest.param("/Archives/edgar/data/50863/000005086326000062/q226earningsrelease.htm?x=1", id="query"),
        pytest.param(
            "/Archives/edgar/data/50863/000005086326000062/../q226earningsrelease.htm", id="dot-dot"
        ),
        pytest.param("/ix?doc=/Archives/edgar/data/50863/000005086326000062/other.htm", id="viewer-other"),
        pytest.param(
            "/ix?doc=/Archives/edgar/data/50863/000005086326000040/q226earningsrelease.htm",
            id="viewer-other-filing",
        ),
        pytest.param(
            "/ix?doc=/Archives/edgar/data/50864/000005086326000062/q226earningsrelease.htm",
            id="viewer-other-cik",
        ),
        pytest.param(
            "/ix?doc=/Archives/edgar/data/0000050863/000005086326000062/q226earningsrelease.htm",
            id="viewer-padded-cik",
        ),
        pytest.param(
            "/ix?doc=/Archives/edgar/data/50863/000005086326000062/q226earningsrelease.htm?x=1",
            id="viewer-query",
        ),
        pytest.param(
            "/ix?doc=https://www.sec.gov/Archives/edgar/data/50863/000005086326000062/q226earningsrelease.htm",
            id="viewer-absolute",
        ),
        pytest.param("q226earningsrelease.htm", id="relative"),
        pytest.param("", id="empty"),
    ],
)
def test_an_exhibit_link_that_does_not_name_its_document_in_the_filings_folder_is_refused(href):
    assert index_failure(q2_page((exhibit_row(href=href),))) == LINK_ERROR


def test_an_exhibit_needs_exactly_one_link_with_a_target():
    folder = "/Archives/edgar/data/50863/000005086326000062"
    one = f'<a href="{folder}/q226earningsrelease.htm">q226earningsrelease.htm</a>'
    page = q2_page((exhibit_row(),))
    assert index_failure(q2_page((exhibit_row(linked=False),))) == LINK_ERROR
    assert index_failure(
        page.replace(one, one + f' <a href="{folder}/q226earningsrelease.htm">copy</a>')
    ) == (LINK_ERROR)
    assert index_failure(page.replace(one, "<a>q226earningsrelease.htm</a>")) == LINK_ERROR
    # A space-separated name is cut at its first word, which the link does not name.
    assert index_failure(q2_page((exhibit_row(document="x y.htm"),))) == LINK_ERROR


@pytest.mark.parametrize("seq", ["2", "999999999", " 2 ", "\n2\n"])
def test_an_exhibit_seq_is_a_whole_number(seq):
    (row,) = read_index(q2_page((exhibit_row(seq=seq),))).exhibits
    assert row.sequence == int(seq)


@pytest.mark.parametrize(
    "seq",
    [
        pytest.param("", id="empty"),
        pytest.param(" ", id="no-break-space"),
        pytest.param("0", id="zero"),
        pytest.param("02", id="leading-zero"),
        pytest.param("-2", id="negative"),
        pytest.param("1.5", id="fraction"),
        pytest.param(FULLWIDTH_ZERO + "2", id="fullwidth"),
        pytest.param("1234567890", id="ten-digits"),
        pytest.param(PRIVATE, id="private-text"),
    ],
)
def test_an_exhibit_seq_that_is_not_a_whole_number_from_1_is_refused(seq):
    assert (
        index_failure(q2_page((exhibit_row(seq=seq),)))
        == "row 3: Seq must be a whole number from 1 in ASCII digits"
    )


def test_exhibit_seqs_and_documents_must_not_repeat():
    repeated_seq = (exhibit_row("2", "one.htm"), exhibit_row("2", "two.htm"))
    assert index_failure(q2_page(repeated_seq)) == "row 4: Seq repeats row 3"
    repeated_document = (exhibit_row("2", "one.htm"), exhibit_row("3", "one.htm", type="EX-99.2"))
    assert index_failure(q2_page(repeated_document)) == "row 4: the document repeats row 3"


@pytest.mark.parametrize(
    ("description", "expected"),
    [
        ("", ""),
        ("Earnings release", "Earnings release"),
        ("Earnings\n   release & outlook", "Earnings release & outlook"),
        ("x" * MAX_DESCRIPTION, "x" * MAX_DESCRIPTION),
        ("Résultats « trimestriels » 第二季度", "Résultats « trimestriels » 第二季度"),
    ],
)
def test_an_exhibit_description_is_kept_collapsed_and_may_be_empty(description, expected):
    (row,) = read_index(q2_page((exhibit_row(description=description),))).exhibits
    assert row.description == expected


@pytest.mark.parametrize(
    "description",
    [
        pytest.param("x" * (MAX_DESCRIPTION + 1), id="too-long"),
        pytest.param(PRIVATE + "\x07", id="control"),
        pytest.param(PRIVATE + "​", id="zero-width-space"),
        pytest.param(PRIVATE * 16, id="private-too-long"),
    ],
)
def test_an_exhibit_description_must_be_printable_and_at_most_200_characters(description):
    assert index_failure(q2_page((exhibit_row(description=description),))) == (
        "row 3: Description must be printable text of at most 200 characters"
    )


def test_a_pdf_copy_of_an_exhibit_is_checked_then_skipped():
    copies = (
        *Q2_EXHIBITS,
        exhibit_row("4", "q226earningsrelease.pdf"),
        exhibit_row("5", "q226cfocommentary.PDF", type="EX-99.2"),
    )
    assert read_index(q2_page(copies)) == read_index(q2_page())
    bad_copy = (*Q2_EXHIBITS, exhibit_row("4", f"../{PRIVATE}.pdf"))
    assert index_failure(q2_page(bad_copy)) == "row 5: the document must be a plain file name"
    repeated = (*Q2_EXHIBITS, exhibit_row("3", "q226earningsrelease.pdf"))
    assert index_failure(q2_page(repeated)) == "row 5: Seq repeats row 4"


def test_cells_are_read_with_references_decoded_and_whitespace_collapsed():
    page = (
        q2_page((exhibit_row(),))
        .replace(">Description</th>", ">\n  Description&#32;\n</th>")
        .replace(
            '<td scope="row">EX-99.1</td>\n            <td scope="row">410408',
            '<td scope="row">EX&#45;99.1</td>\n            <td scope="row">410408',
        )
    )
    assert read_index(page) == FilingIndex(
        exhibits=(ExhibitRow(2, "EX-99.1", "q226earningsrelease.htm", "EX-99.1"),)
    )


def test_omitted_end_tags_are_implied_as_a_browser_implies_them():
    page = q2_page().replace("</td>", "").replace("</th>", "").replace("</tr>", "")
    assert read_index(page) == read_index(q2_page())


@pytest.mark.parametrize("line_break", ["<br>", "<br/>", "<br />", "<BR>"])
def test_a_line_break_in_a_cell_reads_as_a_space(line_break):
    page = q2_page((exhibit_row(description="Press release"),))
    assert page.count(">Press release</td>") == 1
    broken = page.replace(">Press release</td>", f">Press{line_break}release</td>")
    (row,) = read_index(broken).exhibits
    assert row.description == "Press release"


def test_text_and_links_after_a_cells_end_are_ignored():
    base = q2_page()
    folder = "/Archives/edgar/data/50863/000005086326000062"
    description = '<td scope="row">EX-99.1</td>'  # the first exhibit's Description cell
    document = 'q226earningsrelease.htm">q226earningsrelease.htm</a></td>'
    # No whitespace after </td>, which collapsing would otherwise hide.
    page = base.replace(description, description + f'stray<a href="{folder}/x.htm">y</a>', 1).replace(
        document, document + f'stray<a href="{folder}/other.htm">other.htm</a>', 1
    )
    assert page.count("stray") == 2
    assert read_index(page) == read_index(base)


def test_the_table_class_may_carry_other_classes():
    page = q2_page().replace(
        'class="tableFile" summary="Document Format Files"',
        'class="wide tableFile" summary="Document Format Files"',
    )
    assert read_index(page) == read_index(q2_page())


NO_TABLE = 'no tableFile table with the summary "Document Format Files"'
FIRST_ROW = "the Document Format Files table's first row is not Seq, Description, Document, Type, Size"
EXHIBIT_SIZE = '<td scope="row">410408</td>'


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        pytest.param(plain_page(), NO_TABLE, id="no-table"),
        pytest.param("", NO_TABLE, id="empty"),
        pytest.param(json.dumps({"directory": {"item": [PRIVATE]}}), NO_TABLE, id="json"),
        pytest.param(
            q2_page().replace('summary="Document Format Files"', f'summary="{PRIVATE}"'),
            NO_TABLE,
            id="other-summary",
        ),
        pytest.param(
            q2_page().replace('summary="Document Format Files"', 'summary="Document Format Files (draft)"'),
            NO_TABLE,
            id="longer-summary",
        ),
        pytest.param(
            q2_page().replace('summary="Document Format Files"', 'summary=" Document Format Files "'),
            NO_TABLE,
            id="spaced-summary",
        ),
        pytest.param(
            q2_page().replace('summary="Document Format Files"', 'summary="document format files"'),
            NO_TABLE,
            id="lowercase-summary",
        ),
        pytest.param(
            q2_page().replace(
                'class="tableFile" summary="Document Format Files"',
                'class="tableFile2" summary="Document Format Files"',
            ),
            NO_TABLE,
            id="other-class",
        ),
        pytest.param(
            q2_page().replace(
                'class="tableFile" summary="Document Format Files"', 'summary="Document Format Files"'
            ),
            NO_TABLE,
            id="no-class",
        ),
        pytest.param(
            q2_page().replace('summary="Data Files"', 'summary="Document Format Files"'),
            '2 tableFile tables have the summary "Document Format Files"; expected one',
            id="two-tables",
        ),
        pytest.param(
            q2_page(header=("Seq", "Description", "Document", "Size")), FIRST_ROW, id="no-type-column"
        ),
        pytest.param(
            q2_page(header=("Seq", "Document", "Description", "Type", "Size")),
            FIRST_ROW,
            id="reordered-columns",
        ),
        pytest.param(
            q2_page(header=("seq", "description", "document", "type", "size")),
            FIRST_ROW,
            id="lowercase-columns",
        ),
        pytest.param(q2_page(header=(*INDEX_HEADER, PRIVATE)), FIRST_ROW, id="extra-column"),
        pytest.param(q2_page(header=()), FIRST_ROW, id="empty-header-row"),
        pytest.param(
            '<table class="tableFile" summary="Document Format Files"></table>', FIRST_ROW, id="no-rows"
        ),
        pytest.param(q2_page().replace(EXHIBIT_SIZE, ""), "row 3 has 4 cells; expected 5", id="four-cells"),
        pytest.param(
            q2_page().replace(EXHIBIT_SIZE, EXHIBIT_SIZE + f"<td>{PRIVATE}</td>"),
            "row 3 has 6 cells; expected 5",
            id="six-cells",
        ),
        pytest.param(
            q2_page().replace("</tr>", "</tr><tr></tr>", 1),
            "row 2 has 0 cells; expected 5",
            id="empty-row",
        ),
        pytest.param(
            q2_page().replace(
                EXHIBIT_SIZE, f'<td scope="row"><table><tr><td>{PRIVATE}</td></tr></table></td>'
            ),
            "the Document Format Files table holds another table",
            id="nested-table",
        ),
        pytest.param(
            q2_page().replace(
                '<table class="tableFile" summary="Document Format Files">',
                f'<table class="tableFile" summary="Document Format Files"><td>{PRIVATE}</td>',
            ),
            "the Document Format Files table has a cell outside a row",
            id="cell-outside-a-row",
        ),
        pytest.param(
            q2_page().replace("</tr>", f"</tr><td>{PRIVATE}</td>", 1),
            "the Document Format Files table has a cell outside a row",
            id="cell-after-a-row-end",
        ),
        pytest.param(
            # The exhibit row's Size cell moved past its own </tr>: read into the row, the page would pass.
            q2_page().replace(EXHIBIT_SIZE, "</tr>" + EXHIBIT_SIZE, 1),
            "the Document Format Files table has a cell outside a row",
            id="exhibit-cell-after-its-row-end",
        ),
    ],
)
def test_an_unexpected_index_layout_fails_loudly_without_echoing_the_page(body, expected):
    assert index_failure(body) == expected
    assert INDEX_TABLE == "Document Format Files" and INDEX_COLUMNS == INDEX_HEADER


def cut_after(page: str, marker: str, start: str = "") -> str:
    """``page`` cut short just after the first ``marker`` that follows ``start``."""
    end = page.index(marker, page.index(start)) + len(marker)
    return page[:end]


@pytest.mark.parametrize(
    ("body", "accession"),
    [
        pytest.param(cut_after(q2_page(), "</tr>", "EX-99.1"), EIGHT_K_Q2.accession, id="after-an-exhibit"),
        pytest.param(
            cut_after(q2_page(), "</tr>", "Complete submission"), EIGHT_K_Q2.accession, id="every-row"
        ),
        pytest.param(cut_after(q2_page(), "EX-99.2"), EIGHT_K_Q2.accession, id="inside-a-cell"),
        pytest.param(cut_after(q2_page(), "<tr", "EX-99.1"), EIGHT_K_Q2.accession, id="inside-a-tag"),
        pytest.param(q2_page().replace("</table>", "", 1), EIGHT_K_Q2.accession, id="end-tag-missing"),
        pytest.param(cut_after(LIVE_PAGE, "</tr>", "EX-99.1"), LIVE_ACCESSION, id="live-page"),
    ],
)
def test_an_index_page_cut_before_its_table_ends_is_refused_rather_than_read_for_fewer_exhibits(
    body, accession
):
    assert index_failure(body, accession) == "the Document Format Files table is not closed"


def test_index_problems_name_the_accession_and_row_never_a_cell():
    rows = (*Q1_EXHIBITS, IndexRow("3", PRIVATE, f"{PRIVATE}/x.htm", "EX-99.2", PRIVATE))
    page = filing_index_html(EIGHT_K_Q1, rows)
    message = failure(parse_filing_index, page, CIK, EIGHT_K_Q1.accession)
    assert message == f"filing index {EIGHT_K_Q1.accession}: row 4: the document must be a plain file name"


@pytest.mark.parametrize(
    ("cik", "accession", "expected"),
    [
        ("50863", EIGHT_K_Q2.accession, "filing index: the CIK must be ten digits"),
        (FULLWIDTH_ZERO * 10, EIGHT_K_Q2.accession, "filing index: the CIK must be ten digits"),
        (CIK, "000005086326000062", "filing index: the accession number must be 10-2-6 digits"),
        (CIK, PRIVATE, "filing index: the accession number must be 10-2-6 digits"),
    ],
)
def test_the_cik_and_accession_must_be_well_formed(cik, accession, expected):
    assert failure(parse_filing_index, q2_page(), cik, accession) == expected


def test_the_cik_and_accession_determine_the_exhibit_folder():
    other_cik = filing_index_html(EIGHT_K_Q2, Q2_EXHIBITS, cik="0000000123")
    assert parse_filing_index(other_cik, "0000000123", EIGHT_K_Q2.accession) == read_index(q2_page())
    assert index_failure(q2_page(), EIGHT_K_Q1.accession).endswith(
        "the Document cell must link only to its document in the filing's folder"
    )


# --------------------------------------------------------------------------- edgar_support builders


@pytest.mark.parametrize("build", [ten_k_html, ten_q_html])
def test_synthetic_documents_are_small_inline_xbrl_pages_with_every_feature(build):
    document = build()
    assert 2048 <= len(document.encode()) <= 4096
    for feature in (
        '<div style="display:none"><ix:header>',
        "</ix:header></div>",
        "<title>",
        "<style",
        "<script",
        "<td>",
        "&nbsp;",
        "&#160;",
        "&shy;",
        "&amp;",
        "&#8217;",
        "&#x2014;",
        '<div style="DISPLAY: None">',
        '<div style="page-break-after:always"></div>',
    ):
        assert feature in document, feature
    for hidden in (HIDDEN_DIV_TEXT, SCRIPT_TEXT, STYLE_TEXT, HIDDEN_FACT):
        assert hidden in document


@pytest.mark.parametrize(
    ("build", "sentences", "split"),
    [
        (
            ten_k_html,
            (*TEN_K_DEMAND, *TEN_K_CUSTOMERS, *TEN_K_PRICING, *TEN_K_SUPPLY, *TEN_K_CAPEX, *TEN_K_FINANCING),
            TEN_K_SPLIT,
        ),
        (ten_q_html, (*TEN_Q_DEMAND, *TEN_Q_SUPPLY, *TEN_Q_CAPEX), TEN_Q_SPLIT),
    ],
)
def test_synthetic_documents_carry_their_parameters(build, sentences, split):
    document = build()
    for text in (COMPANY, *SEGMENTS, *sentences):
        assert text in document
    assert all(f"<span>{half}</span>" in document for half in split)
    lines = html_text(document).splitlines()
    assert all(sentence in lines for sentence in sentences)  # each a whole line of the derived text
    custom = build(
        company="Example & Sons <Holdings>",
        segments=("Widgets & Gadgets",),
        demand=("Customers ordered more widgets <and> gadgets this year.",),
        supply=(),
        capex=(),
    )
    assert "Example &amp; Sons &lt;Holdings&gt;" in custom
    assert "<td>Widgets &amp; Gadgets</td>" in custom
    assert "<p>Customers ordered more widgets &lt;and&gt; gadgets this year.</p>" in custom


def test_submissions_bodies_carry_edgar_columns_beyond_those_read():
    recent = submissions_document()["filings"]["recent"]
    assert set(RECENT_COLUMNS) < set(recent)
    assert {
        "acceptanceDateTime",
        "act",
        "fileNumber",
        "size",
        "isInlineXBRL",
        "primaryDocDescription",
    } <= set(recent)
    assert {len(column) for column in recent.values()} == {len(RECENT)}
    assert recent["items"] == [row.items for row in RECENT]
    assert json.loads(submissions_json())["cik"] == "50863"
    assert RECENT == (
        FORM_4,
        TEN_Q_2,
        EIGHT_K_Q2,
        TEN_Q_1,
        EIGHT_K_Q1,
        PROXY,
        EIGHT_K_OTHER,
        TEN_K,
        OLD_TEN_Q,
        OLD_TEN_K,
    )
    assert [row.filed for row in RECENT] == sorted((row.filed for row in RECENT), reverse=True)


def test_synthetic_index_pages_reproduce_edgars_document_format_files_layout():
    page = q2_page()
    folder = "/Archives/edgar/data/50863/000005086326000062"
    for feature in (
        '<div class="infoHead">Filing Date</div>\n         <div class="info">2026-07-23</div>',
        '<div class="infoHead">Period of Report</div>\n         <div class="info">2026-07-23</div>',
        "Item 2.02: Results of Operations and Financial Condition<br />"
        "Item 9.01: Financial Statements and Exhibits<br />",
        "<p>Document Format Files</p>",
        '<table class="tableFile" summary="Document Format Files">',
        '<th scope="col" style="width: 5%;"><acronym title="Sequence Number">Seq</acronym></th>',
        '<th scope="col">Size</th>',
        f'<td scope="row"><a href="/ix?doc={folder}/intc-20260723.htm">intc-20260723.htm</a> '
        '&nbsp;&nbsp;<span style="color: green">iXBRL</span></td>',
        "\n            ".join(
            (
                '<tr class="evenRow">',
                '<td scope="row">2</td>',
                '<td scope="row">EX-99.1</td>',
                f'<td scope="row"><a href="{folder}/q226earningsrelease.htm">'
                "q226earningsrelease.htm</a></td>",
                '<td scope="row">EX-99.1</td>',
                '<td scope="row">410408</td>',
            )
        ),
        f'<td scope="row"><a href="{folder}/intc-20260723_g1.jpg">intc-20260723_g1.jpg</a></td>',
        '<td scope="row">&nbsp;</td>\n            <td scope="row">Complete submission text file</td>',
        f'<a href="{folder}/0000050863-26-000062.txt">0000050863-26-000062.txt</a>',
        '<table class="tableFile" summary="Data Files">',
        f'<a href="{folder}/intc-20260723.xsd">intc-20260723.xsd</a>',
    ):
        assert feature in page, feature
    assert page.count('class="tableFile"') == 2
    assert EXHIBITS == {"index_1": Q1_EXHIBITS, "index_2": Q2_EXHIBITS}
    assert all(row.type == "GRAPHIC" for row in GRAPHIC_ROWS)
    assert "<table" not in plain_page()
    other = filing_index_html(EIGHT_K_OTHER, ())
    assert "Item 5.02: Departure of Directors or Certain Officers;" in other
    assert '<div class="info">2026-02-09</div>' in other


WHOLE_SENTENCES = (
    *TEN_K_DEMAND,
    *TEN_K_CUSTOMERS,
    *TEN_K_PRICING,
    *TEN_K_SUPPLY,
    *TEN_K_CAPEX,
    *TEN_K_FINANCING,
    *TEN_Q_DEMAND,
    *TEN_Q_SUPPLY,
    *TEN_Q_CAPEX,
    *RELEASE_GUIDANCE,
    *RELEASE_CAPEX,
    *RELEASE_DEMAND,
    *RELEASE_SUPPLY,
    *RELEASE_RAMP,
    *COMMENTARY_CAPEX,
    *COMMENTARY_SUPPLY,
    *COMMENTARY_DEMAND,
)


@pytest.mark.parametrize("sentence", WHOLE_SENTENCES)
def test_every_sentence_constant_is_one_whole_sentence(sentence):
    assert sentence[0].isupper()
    assert sentence[-1] in ".!?…"
    assert " " not in (sentence[0], sentence[-2])
    assert all(mark not in sentence[:-1] for mark in "!?…")
    assert ". " not in sentence  # no second sentence (the decimals stay inside numbers)


def test_synthetic_exhibits_carry_their_sentences_and_outlook_rows():
    release = exhibit_html(TEN_Q_PERIOD, title=RELEASE_TITLES["q226earningsrelease.htm"])
    commentary = commentary_html(TEN_Q_PERIOD)
    for document in (release, commentary):
        assert document.isascii()
        assert document.count("&nbsp;") == 1
        assert f'<div style="display:none">{HIDDEN_DIV_TEXT}</div>' in document
    lines = html_text(release).splitlines()
    assert lines[:2] == [
        "Intel Reports Second-Quarter 2026 Financial Results",
        f"{COMPANY} results for the quarter ended June 27, 2026",
    ]
    for line in (
        *RELEASE_DEMAND,
        *RELEASE_SUPPLY,
        *RELEASE_RAMP,
        *RELEASE_CAPEX,
        *RELEASE_GUIDANCE,
        *RELEASE_OUTLOOK_LINES,
        RELEASE_BOUNDARIES,
    ):
        assert lines.count(line) == 1, line
    assert RELEASE_OUTLOOK_LINES == (
        "Revenue $12.6 billion to $13.6 billion",
        "Gross margin approximately 36 percent",
        "Earnings per share $0.01",
    )
    assert len(RELEASE_OUTLOOK) == release.count("<tr><td>")
    assert HIDDEN_DIV_TEXT not in html_text(release)
    commentary_lines = html_text(commentary).splitlines()
    assert commentary_lines[0] == COMMENTARY_TITLE
    assert all(
        commentary_lines.count(line) == 1
        for line in (*COMMENTARY_CAPEX, COMMENTARY_COLON, *COMMENTARY_SUPPLY, *COMMENTARY_DEMAND)
    )
    # The list: its lead-in, then each item as the glyph attached to its text (two spans, no space).
    lead_in = commentary_lines.index(COMMENTARY_LEAD_IN)
    assert commentary_lines[lead_in + 1 : lead_in + 3] == [
        f"{COMMENTARY_BULLET}{item}" for item in COMMENTARY_ITEMS
    ]
    assert COMMENTARY_BULLET == "\u25aa" and "&#9642;</span><span" in commentary
    q1 = exhibit_html(date(2026, 3, 28), title=RELEASE_TITLES["q126earningsrelease.htm"])
    assert q1 != release and "March&nbsp;28, 2026" in q1
    custom = exhibit_html(
        TEN_Q_PERIOD, title="T & U", guidance=("Revenue will be “flat”.",), outlook=(), boundaries=""
    )
    assert "<h1>T &amp; U</h1>" in custom and "&#8220;flat&#8221;" in custom and "<tr>" not in custom
    assert "Revenue will be “flat”." in html_text(custom).splitlines()


def test_the_boundaries_paragraph_holds_every_sentence_end_and_closing_mark_case():
    for case in (
        "strong.” Will",
        "it? Lead",
        "fell… (Capital",
        "rise.) Shipments",
        "U.S. market!",
        "market! Capital",
        "“Project Alpha” and it continues.",
        "said that “demand",
    ):
        assert case in RELEASE_BOUNDARIES, case
    assert "\n" not in RELEASE_BOUNDARIES
