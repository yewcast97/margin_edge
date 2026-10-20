"""The CFTC's TFF rows: the query, the raw file, the E-mini conversion and every rule a read checks."""

import json
from datetime import date
from urllib.parse import parse_qsl, urlsplit

import pytest

from market_state_research.market_position_regime.script import cftc
from market_state_research.market_position_regime.script.cftc import (
    check_answer,
    dump,
    parse_rows,
    query_url,
    raw_name,
    read_answer,
)

from .support import FETCHED, FIFTY, NOW, TWO_FIFTY, answer_value, edt, tff_row

FIRST, LAST = date(2026, 9, 28), date(2026, 10, 18)
ROWS = [tff_row(date(2026, 9, 29)), tff_row(date(2026, 10, 6)), tff_row(date(2026, 10, 13))]


def refused(rows=ROWS, first_day=FIRST, last_day=LAST, at=FETCHED, name=None, **changes) -> str:
    """The message refusing the answer of ``rows``, with ``changes`` written over its keys."""
    value = {**answer_value(rows, first_day, last_day, at), **changes}
    with pytest.raises(ValueError) as caught:
        check_answer(value, name, NOW)
    assert "\n" not in str(caught.value)
    return str(caught.value)


def test_the_query_asks_for_the_market_alone_in_one_ascending_page():
    url = query_url(FIRST, LAST)
    parts = urlsplit(url)
    assert (
        f"{parts.scheme}://{parts.netloc}{parts.path}"
        == "https://publicreporting.cftc.gov/resource/gpe5-46if.json"
    )
    assert parse_qsl(parts.query) == [
        ("$select", ",".join(cftc.FIELDS)),
        (
            "$where",
            "cftc_contract_market_code = '13874+' AND report_date_as_yyyy_mm_dd between "
            "'2026-09-28T00:00:00.000' and '2026-10-18T00:00:00.000'",
        ),
        ("$order", "report_date_as_yyyy_mm_dd ASC"),
        ("$limit", "5000"),
    ]
    assert "%2B" in url and "+" not in parts.query  # the contract's '+' is encoded, never a space
    with pytest.raises(ValueError):
        query_url(LAST, FIRST)


def test_a_valid_answer_gives_one_report_per_week():
    answer = check_answer(answer_value(ROWS, FIRST, LAST), None, NOW)
    assert [report.as_of for report in answer.reports] == [
        date(2026, 9, 29),
        date(2026, 10, 6),
        date(2026, 10, 13),
    ]
    report = answer.reports[-1]
    assert (report.asset_mgr_long, report.asset_mgr_short, report.asset_mgr_spread) == (1_000, 200, 50)
    assert (report.asset_mgr_net, report.lev_money_net_short, report.open_interest_emini) == (800, 400, 2_000)
    assert report.row == ROWS[-1]


def test_positions_in_contracts_of_250_dollars_are_converted_to_e_mini_equivalents():
    old = tff_row(
        date(2023, 4, 25),
        asset_mgr=(205_911, 89_016, 47_028),
        lev_money=(28_488, 123_502, 12_286),
        open_interest=453_159,
        units=TWO_FIFTY,
    )
    new = tff_row(
        date(2023, 5, 2),
        asset_mgr=(1_026_371, 431_625, 232_651),
        lev_money=(131_734, 588_857, 78_566),
        open_interest=2_304_633,
        units=FIFTY,
    )
    quoted = tff_row(date(2014, 12, 30), units="'(S&P 500 INDEX X $250.00)'")
    answer = check_answer(answer_value([quoted, old, new], date(2014, 12, 29), date(2023, 5, 7)), None, NOW)
    first, before, after = answer.reports
    assert (first.multiplier, before.multiplier, after.multiplier) == (250, 250, 50)
    assert (before.asset_mgr_net, after.asset_mgr_net) == (584_475, 594_746)  # (205,911 − 89,016) × 5
    assert (before.lev_money_net_short, after.lev_money_net_short) == (475_070, 457_123)
    assert before.open_interest_emini == 2_265_795


def test_a_monday_report_counts_for_its_week():
    rows = [tff_row(date(2025, 11, 4)), tff_row(date(2025, 11, 10)), tff_row(date(2025, 11, 18))]
    answer = check_answer(answer_value(rows, date(2025, 11, 3), date(2025, 11, 23)), None, NOW)
    assert [report.week for report in answer.reports] == [
        date(2025, 11, 4),
        date(2025, 11, 11),
        date(2025, 11, 18),
    ]
    two = [tff_row(date(2025, 11, 10)), tff_row(date(2025, 11, 11))]
    assert refused(two, date(2025, 11, 3), date(2025, 11, 23)) == "rows must be one per week, in date order"


def test_dump_and_read_round_trip_under_the_raw_name():
    answer = check_answer(answer_value(ROWS, FIRST, LAST), None, NOW)
    name = raw_name(FIRST, LAST, FETCHED)
    assert name == "cftc_tff_2026-09-28_2026-10-18_20261020T120000EDT.json"
    assert read_answer(dump(answer), name, NOW) == answer
    assert json.loads(dump(answer))["rows"] == ROWS
    with pytest.raises(
        ValueError, match="the name must be cftc_tff_2026-09-28_2026-10-18_20261020T120000EDT.json"
    ):
        read_answer(dump(answer), raw_name(FIRST, date(2026, 10, 17), FETCHED), NOW)
    with pytest.raises(ValueError, match="not a JSON document"):
        read_answer(b"\xff", name, NOW)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        (
            "cftc_contract_market_code",
            "13874A",
            "row 1: cftc_contract_market_code must be '13874+', got '13874A'",
        ),
        ("market_and_exchange_names", "S&P 500", "row 1: market_and_exchange_names must be"),
        ("futonly_or_combined", "Combined", "row 1: futonly_or_combined must be 'FutOnly', got 'Combined'"),
        ("id", "26092913874+C", "row 1: id must be '26092913874+F', got '26092913874+C'"),
        ("contract_units", "(S&P 500 INDEX X $5.00)", "row 1: contract_units must be"),
        (
            "asset_mgr_positions_long",
            "1.5",
            "row 1: asset_mgr_positions_long must be a whole number of contracts",
        ),
        ("open_interest_all", "-1", "row 1: open_interest_all must be a whole number of contracts"),
        ("lev_money_positions_short", "007", "row 1: lev_money_positions_short must be a whole number"),
        (cftc.DATE_FIELD, "2026-09-29", "row 1: report_date_as_yyyy_mm_dd must be YYYY-MM-DDT00:00:00.000"),
        (cftc.DATE_FIELD, "2026-09-27T00:00:00.000", "row 1: the report date 2026-09-27 is not a weekday"),
    ],
)
def test_a_row_must_be_the_markets_with_whole_positions(field, value, message):
    rows = [dict(ROWS[0], **{field: value}), *ROWS[1:]]
    assert refused(rows).startswith(message)


def test_a_row_must_hold_exactly_the_fields_as_strings():
    missing = {key: value for key, value in ROWS[0].items() if key != "asset_mgr_positions_spread"}
    assert refused([missing, *ROWS[1:]]).startswith("row 1 must hold exactly the fields id,")
    extra = dict(ROWS[0], dealer_positions_long="1")
    assert refused([extra, *ROWS[1:]]).startswith("row 1 must hold exactly the fields")
    number = dict(ROWS[0], open_interest_all=2000)
    assert refused([number, *ROWS[1:]]) == "row 1: every value must be a JSON string"


def test_the_file_must_hold_its_keys_in_order_and_agree_with_its_request_and_name():
    value = answer_value(ROWS, FIRST, LAST)
    reordered = {key: value[key] for key in ("fetched_at", "request", "first", "last", "rows")}
    with pytest.raises(ValueError, match="the keys must be exactly request, fetched_at, first, last, rows"):
        check_answer(reordered, None, NOW)
    assert (
        refused(request=query_url(FIRST, date(2026, 10, 17))) == "request must be the query of first to last"
    )
    assert refused(first="2026-10-19") == "first 2026-10-19 is after last 2026-10-18"
    assert refused(first="2026-02-30").startswith("first must be a YYYY-MM-DD date that exists")
    assert refused(name="cftc_tff_x.json").startswith("the name must be cftc_tff_2026-09-28_2026-10-18_")


def test_the_time_must_be_new_york_and_between_the_newest_report_and_the_clock():
    assert refused(at=edt(2026, 10, 20, 18, 0, 1)).endswith("is later than the current time")
    assert refused(at=edt(2026, 10, 13, 23, 0)) == (
        "fetched at 2026-10-13T23:00:00-04:00, not after the newest report date 2026-10-13"
    )
    assert (
        refused(fetched_at="2026-10-20T16:00:00+00:00")
        == "fetched_at must be written in New York time with its offset"
    )
    assert refused(fetched_at="yesterday") == "fetched_at must be an ISO time with an offset"


def test_rows_must_lie_in_the_range_and_fill_no_page():
    assert (
        refused(first_day=date(2026, 9, 30)) == "row 1 is dated 2026-09-29, outside 2026-09-30 to 2026-10-18"
    )
    assert refused(rows=[]) == "rows must be a list of at least one row"
    with pytest.raises(ValueError, match="filled a page of 5000 rows"):
        parse_rows(json.dumps([{}] * cftc.PAGE_ROWS).encode())
    with pytest.raises(ValueError, match="not the CFTC's JSON rows"):
        parse_rows(b'{"error": true}')
    assert parse_rows(b"[]") == []
