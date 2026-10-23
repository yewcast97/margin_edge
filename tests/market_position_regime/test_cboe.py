"""Cboe's VIX and SKEW histories: their exact layouts, the raw units and every rule a read checks."""

import gzip
from datetime import date
from decimal import Decimal

import pytest

from market_state_research.market_position_regime.script import cboe
from market_state_research.market_position_regime.script.cboe import (
    SKEW,
    VIX,
    Row,
    check_history,
    dump,
    load,
    parse_history,
    raw_name,
    read_history,
)
from market_state_research.market_position_regime.script.periods import sessions_within

from .support import NOW, VIX_FETCHED, edt, est, history_bytes, skew_bytes

HEAD = b"DATE,OPEN,HIGH,LOW,CLOSE\n01/02/1990,17.240000,17.240000,17.240000,17.240000\n"
SKEW_HEAD = b"DATE,SKEW\n01/02/1990,126.090000\n"


def refused(data: bytes, index: cboe.Index = VIX) -> str:
    with pytest.raises(ValueError) as caught:
        parse_history(data, index)
    message = str(caught.value)
    assert "\n" not in message
    return message


def test_the_two_indices_are_read_from_fixed_addresses():
    assert VIX.url == "https://cdn-api.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv"
    assert SKEW.url == "https://cdn-api.cboe.com/api/global/us_indices/daily_prices/SKEW_History.csv"
    assert (VIX.header, SKEW.header) == ("DATE,OPEN,HIGH,LOW,CLOSE", "DATE,SKEW")
    assert (VIX.level, SKEW.level) == ("close", "skew")
    assert cboe.INDICES == (VIX, SKEW)


def test_a_vix_file_in_cboes_layout_gives_every_day_ascending():
    rows = parse_history(history_bytes(), VIX)
    sessions = sessions_within(date(2000, 1, 3), date(2026, 10, 20))
    assert len(sessions) == 6_740 and len(rows) == 1 + len(sessions)
    assert rows[0] == Row(date(1990, 1, 2), ("20.000000",) * 4)
    assert rows[1].day == date(2000, 1, 3) and rows[1].level == "10.000000"
    # The 6,740th session closes at 10.00 + 6,739 × 0.01.
    assert (rows[-1].day, rows[-1].level, rows[-1].level_value) == (
        date(2026, 10, 20),
        "77.390000",
        Decimal("77.39"),
    )


def test_a_skew_file_in_cboes_layout_gives_one_value_a_day():
    gone = date(2024, 11, 29)  # one of the sessions Cboe's SKEW file lacks
    rows = parse_history(skew_bytes(missing=[gone]), SKEW)
    assert rows[0] == Row(date(1990, 1, 2), ("20.000000",))
    assert gone not in {row.day for row in rows}
    assert (rows[-1].day, rows[-1].values, rows[-1].level_value) == (
        date(2026, 10, 20),
        ("187.39" + "0000",),
        Decimal("187.39"),
    )
    assert parse_history(SKEW_HEAD, SKEW) == (Row(date(1990, 1, 2), ("126.090000",)),)


def test_rows_of_days_xnys_does_not_trade_are_kept_as_received():
    extra = {date(2025, 11, 27): "17.210000", date(2004, 6, 11): "15.040000"}
    days = {row.day: row for row in parse_history(history_bytes(extra=extra), VIX)}
    assert days[date(2025, 11, 27)].level == "17.210000"  # Thanksgiving: Cboe's global trading hours
    assert days[date(2004, 6, 11)].level == "15.040000"


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (b"\xffDATE", "the file is not ASCII text"),
        (HEAD[:-1], "the file must end with a line feed"),
        (HEAD.replace(b"DATE,OPEN", b"Date,Open"), "the first line must be exactly DATE,OPEN,HIGH,LOW,CLOSE"),
        (HEAD.replace(b"\n", b"\r\n"), "the first line must be exactly DATE,OPEN,HIGH,LOW,CLOSE"),
        (SKEW_HEAD, "the first line must be exactly DATE,OPEN,HIGH,LOW,CLOSE"),
        (b"DATE,OPEN,HIGH,LOW,CLOSE\n", "the file holds no day"),
        (
            HEAD.replace(b"17.240000,17.240000\n", b"17.24,17.24\n"),
            "line 2 must be a MM/DD/YYYY day and four decimals with six places, separated by commas, "
            "got '01/02/1990,17.240000,17.240000,17.24,17.24'",
        ),
        (
            HEAD + b"1990-01-03,17.240000,17.240000,17.240000,17.240000\n",
            "line 3 must be a MM/DD/YYYY day",
        ),
        (HEAD + b"02/30/1990,17.240000,17.240000,17.240000,17.240000\n", "line 3: 02/30/1990 is not a day"),
        (
            HEAD + b"01/03/1990,17.240000,0.000000,17.240000,17.240000\n",
            "line 3: the high of 1990-01-03 must be above 0",
        ),
        (
            HEAD + b"01/02/1990,17.240000,17.240000,17.240000,17.240000\n",
            "line 3 is dated 1990-01-02, not after 1990-01-02: the days must ascend, once each",
        ),
        (
            b"DATE,OPEN,HIGH,LOW,CLOSE\n01/03/1990,17.240000,17.240000,17.240000,17.240000\n",
            "the first day must be 1990-01-02, got 1990-01-03",
        ),
    ],
)
def test_every_vix_rule_is_one_line(data, message):
    assert refused(data).startswith(message)


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (HEAD, "the first line must be exactly DATE,SKEW"),
        (SKEW_HEAD.replace(b"SKEW", b"Skew"), "the first line must be exactly DATE,SKEW"),
        (
            SKEW_HEAD + b"01/03/1990,126.09\n",
            "line 3 must be a MM/DD/YYYY day and one decimal with six places, separated by commas, "
            "got '01/03/1990,126.09'",
        ),
        (
            SKEW_HEAD + b"01/03/1990,126.090000,1.000000\n",
            "line 3 must be a MM/DD/YYYY day and one decimal with six places",
        ),
        (SKEW_HEAD + b"01/03/1990,0.000000\n", "line 3: the skew of 1990-01-03 must be above 0"),
        (b"DATE,SKEW\n01/03/1990,126.090000\n", "the first day must be 1990-01-02, got 1990-01-03"),
    ],
)
def test_every_skew_rule_is_one_line(data, message):
    assert refused(data, SKEW).startswith(message)


def test_no_order_among_the_four_values_is_checked():
    # Cboe's 1992-02-11: an open above the high, as received.
    row = b"02/11/1992,19.240000,18.570000,17.610000,17.700000\n"
    assert parse_history(HEAD + row, VIX)[-1].values[0] == "19.240000"


@pytest.mark.parametrize(("index", "build"), [(VIX, history_bytes), (SKEW, skew_bytes)])
def test_a_session_row_is_valid_only_once_its_values_were_due(index, build):
    data = build(date(2026, 10, 20))
    with pytest.raises(ValueError) as caught:
        check_history(data, index, edt(2026, 10, 20, 16, 14, 59), NOW)
    assert str(caught.value) == (
        "the row of 2026-10-20 was fetched at 2026-10-20T16:14:59-04:00, before the session's "
        f"{index.name} was due at 2026-10-20T16:15:00-04:00"
    )
    assert check_history(data, index, edt(2026, 10, 20, 16, 15), NOW).newest == date(2026, 10, 20)
    early = build(date(2026, 11, 27))  # an early close at 13:00: due at 13:15
    later = est(2026, 11, 27, 20, 0)
    with pytest.raises(
        ValueError, match=f"before the session's {index.name} was due at 2026-11-27T13:15:00-05:00"
    ):
        check_history(early, index, est(2026, 11, 27, 13, 14), later)
    assert check_history(early, index, est(2026, 11, 27, 13, 15), later).newest == date(2026, 11, 27)


def test_no_row_may_be_dated_after_the_fetch_and_no_fetch_after_the_clock():
    with pytest.raises(ValueError, match="the newest day, 2026-10-20, is after the day the file was fetched"):
        check_history(history_bytes(date(2026, 10, 20)), VIX, edt(2026, 10, 19, 23, 0), NOW)
    with pytest.raises(
        ValueError, match="fetched_at 2026-10-20T18:00:01-04:00 is later than the current time"
    ):
        check_history(skew_bytes(), SKEW, edt(2026, 10, 20, 18, 0, 1), NOW)
    # A holiday row of the day of the fetch is no session: it is kept and never used.
    labor_day = history_bytes(date(2026, 9, 4), extra={date(2026, 9, 7): "15.300000"})
    assert check_history(labor_day, VIX, edt(2026, 9, 7, 9, 0), NOW).newest == date(2026, 9, 7)


def test_the_raw_unit_is_the_file_as_received_in_deterministic_gzip():
    data = history_bytes()
    name = raw_name(VIX, VIX_FETCHED)
    assert name == "cboe_vix_20261020T170000EDT.csv.gz"
    assert raw_name(VIX, VIX_FETCHED, "_2") == "cboe_vix_20261020T170000EDT_2.csv.gz"
    assert raw_name(SKEW, VIX_FETCHED) == "cboe_skew_20261020T170000EDT.csv.gz"
    assert dump(data) == dump(data) and load(dump(data)) == data
    assert gzip.decompress(dump(data)) == data
    history = read_history(dump(data), name, NOW)
    assert (history.index, history.fetched_at, history.newest) == (VIX, VIX_FETCHED, date(2026, 10, 20))
    assert read_history(dump(data), "cboe_vix_20261020T170000EDT_2.csv.gz", NOW) == history
    skew = read_history(dump(skew_bytes()), "cboe_skew_20261020T170000EDT.csv.gz", NOW)
    assert (skew.index, skew.rows[-1].level) == (SKEW, "187.390000")


def test_a_file_is_read_as_the_index_its_name_gives():
    with pytest.raises(ValueError, match="the first line must be exactly DATE,SKEW"):
        read_history(dump(history_bytes()), "cboe_skew_20261020T170000EDT.csv.gz", NOW)
    with pytest.raises(ValueError, match="the first line must be exactly DATE,OPEN,HIGH,LOW,CLOSE"):
        read_history(dump(skew_bytes()), "cboe_vix_20261020T170000EDT.csv.gz", NOW)


@pytest.mark.parametrize(
    "name",
    [
        "cboe_vix_20261020T170000.csv.gz",
        "cboe_vix_20261020T170000EST.csv.gz",
        "vix_20261020T170000EDT.csv.gz",
        "cboe_spx_20261020T170000EDT.csv.gz",
    ],
)
def test_a_raw_name_must_name_an_index_and_carry_a_new_york_time(name):
    with pytest.raises(ValueError, match="the name must be cboe_vix_TOKEN.csv.gz or cboe_skew_TOKEN.csv.gz"):
        read_history(dump(history_bytes()), name, NOW)


def test_a_raw_file_must_be_bounded_gzip():
    with pytest.raises(ValueError, match="not a gzip file"):
        load(history_bytes())
    bomb = gzip.compress(b"0" * (cboe.MAX_UNCOMPRESSED + 1), mtime=0)
    with pytest.raises(ValueError, match=f"more than {cboe.MAX_UNCOMPRESSED} bytes uncompressed"):
        load(bomb)
