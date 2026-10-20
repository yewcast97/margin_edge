"""FRED's observations of the two Z.1 series: the raw file and every rule a read checks."""

from datetime import date
from decimal import Decimal

import pytest

from market_state_research.market_position_regime.script import fred
from market_state_research.market_position_regime.script.fred import (
    check_answer,
    dump,
    observations_url,
    raw_name,
    read_answer,
)

from .support import FETCHED, NOW, edt, fred_response, quarter_values, series_value

VALUES = quarter_values(value="83050847") | {date(2020, 3, 31): "48216.0", date(2020, 6, 30): "."}


def refused(value: object, name: str | None = None) -> str:
    with pytest.raises(ValueError) as caught:
        check_answer(value, name, NOW)
    assert "\n" not in str(caught.value)
    return str(caught.value)


def changed_response(**changes: object) -> dict[str, object]:
    value = series_value(fred.NONFINANCIAL, VALUES)
    value["response"] = {**fred_response(VALUES), **changes}
    return value


def test_the_url_names_the_series_and_never_the_key():
    assert observations_url(fred.NONFINANCIAL) == (
        "https://api.stlouisfed.org/fred/series/observations?series_id=NCBEILQ027S&file_type=json"
    )
    assert fred.SERIES == ("NCBEILQ027S", "BOGZ1LM793164105Q")
    with pytest.raises(ValueError):
        observations_url("SP500")


def test_a_valid_answer_gives_each_quarter_end_its_value():
    item = check_answer(series_value(fred.NONFINANCIAL, VALUES), None, NOW)
    by_end = item.by_quarter_end()
    assert by_end[date(2026, 6, 30)].value == Decimal("83050847")
    assert by_end[date(2020, 3, 31)].value == Decimal("48216.0")
    assert by_end[date(2020, 6, 30)].value is None and by_end[date(2020, 6, 30)].text == "."
    assert item.observations[0].quarter_end == date(2019, 12, 31)


def test_a_newer_answer_is_compared_by_its_values_alone():
    first = check_answer(series_value(fred.NONFINANCIAL, VALUES), None, NOW)
    value = series_value(fred.NONFINANCIAL, VALUES, edt(2026, 10, 20, 13, 0))
    for item in value["response"]["observations"]:  # type: ignore[index]
        item["realtime_start"] = item["realtime_end"] = "2026-10-21"
    second = check_answer(value, None, NOW)
    assert first.content() == second.content()
    third = check_answer(series_value(fred.NONFINANCIAL, VALUES | {date(2026, 6, 30): "83050848"}), None, NOW)
    assert third.content() != first.content()


def test_dump_and_read_round_trip_under_the_raw_name():
    item = check_answer(series_value(fred.FINANCIAL, VALUES), None, NOW)
    name = raw_name(fred.FINANCIAL, FETCHED)
    assert name == "fred_BOGZ1LM793164105Q_20261020T120000EDT.json"
    assert read_answer(dump(item), name, NOW) == item
    assert refused(series_value(fred.FINANCIAL, VALUES), raw_name(fred.NONFINANCIAL, FETCHED)).startswith(
        "the name must be fred_BOGZ1LM793164105Q_20261020T120000EDT.json"
    )


def test_the_file_must_hold_its_keys_and_agree_with_its_series_and_request():
    value = series_value(fred.NONFINANCIAL, VALUES)
    assert refused({**value, "series": "SP500"}) == "series must be one of NCBEILQ027S, BOGZ1LM793164105Q"
    assert refused({**value, "request": observations_url(fred.FINANCIAL)}).startswith(
        "request must be https://"
    )
    assert refused({**value, "request": value["request"] + "&api_key=x"}).startswith("request must be")
    reordered = {key: value[key] for key in ("request", "series", "fetched_at", "response")}
    assert (
        refused(reordered) == "the keys must be exactly series, request, fetched_at, response, in that order"
    )


def test_the_time_must_be_after_the_newest_quarter_and_not_after_the_clock():
    assert refused(series_value(fred.NONFINANCIAL, VALUES, edt(2026, 10, 20, 18, 1))).endswith(
        "is later than the current time"
    )
    assert refused(series_value(fred.NONFINANCIAL, VALUES, edt(2026, 6, 30, 12, 0))) == (
        "fetched at 2026-06-30T12:00:00-04:00, before the newest quarter, 2026-06-30, ended"
    )


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"units": "pch"}, "FRED's units must be 'lin', got 'pch'"),
        ({"sort_order": "desc"}, "FRED's sort_order must be 'asc'"),
        ({"offset": 1}, "FRED's offset must be 0"),
        ({"output_type": "1"}, "FRED's output_type must be 1"),
        ({"count": 999}, "FRED counts 999 observations but sent"),
        ({"limit": 3}, "FRED's answer is cut at its limit"),
        ({"observations": []}, "FRED's answer holds no observation"),
        ({"extra": 1}, "the answer is not FRED's series observations (its keys differ)"),
    ],
)
def test_freds_answer_must_be_the_whole_series_in_linear_units(changes, message):
    response = changed_response(**changes)
    if "observations" in changes:
        response["response"]["count"] = 0  # type: ignore[index]
    assert refused(response).startswith(message)


def test_observations_must_be_consecutive_quarters_with_decimal_values():
    def with_observations(edit) -> dict[str, object]:
        value = series_value(fred.NONFINANCIAL, VALUES)
        observations = value["response"]["observations"]  # type: ignore[index]
        edit(observations)
        value["response"]["count"] = len(observations)  # type: ignore[index]
        return value

    gap = with_observations(lambda items: items.pop(3))
    assert refused(gap).startswith("observation 4 does not follow the quarter of")
    middle = with_observations(lambda items: items[0].update(date="2019-11-01"))
    assert refused(middle) == "observation 1 is dated 2019-11-01, not the first day of a quarter"
    negative = with_observations(lambda items: items[0].update(value="-5"))
    assert refused(negative) == "observation 1: the value must be a non-negative decimal or '.', got '-5'"
    number = with_observations(lambda items: items[0].update(value=5))
    assert refused(number) == "observation 1: the value must be a non-negative decimal or '.', got '5'"
    keys = with_observations(lambda items: items[0].pop("realtime_end"))
    assert refused(keys).startswith(
        "observation 1 must hold exactly the keys realtime_start, realtime_end, date, value"
    )
