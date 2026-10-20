"""The prices raw unit: its bytes, its name, every rule a file must meet and the daily return."""

import gzip
import json
from datetime import date
from decimal import Decimal

import pytest

from market_state_research.market_regime.script.prices import (
    BAR_FIELDS,
    check_bar,
    check_prices,
    daily_return,
    dump,
    parse_bars,
    raw_name,
    read_prices,
)
from market_state_research.market_regime.script.surface import Value

from .support import FETCHED, NOW, TICKER, bar_values, edt, prices

THURSDAY, FRIDAY = date(2026, 10, 15), date(2026, 10, 16)
NAME = "prices_2026-10-16_20261017T100000EDT.json.gz"


def value_of(item) -> dict:
    return json.loads(gzip.decompress(dump(item)))


def check(value, name=NAME):
    return check_prices(value, TICKER, name, NOW)


def two_days(**options):
    return prices({THURSDAY: "95.37", FRIDAY: "89.85"}, **options)


def test_dump_is_deterministic_and_keeps_tiingos_text():
    item = two_days()
    assert dump(item) == dump(item) and dump(item)[4:8] == b"\x00\x00\x00\x00"
    value = value_of(item)
    assert list(value) == ["ticker", "start", "end", "fetched_at", "request", "bars"]
    assert value["request"] == (
        "https://api.tiingo.com/tiingo/daily/TEST/prices?startDate=2026-10-15&endDate=2026-10-16"
    )
    assert value["bars"][1] == bar_values(FRIDAY, "89.85")
    assert list(value["bars"][1]) == list(BAR_FIELDS)
    parsed = read_prices(dump(item), TICKER, NAME, NOW)
    assert parsed == item and parsed.bar(FRIDAY).adj_close == Decimal("89.85")


def test_raw_name():
    assert raw_name(FRIDAY, FETCHED) == NAME
    assert raw_name(FRIDAY, FETCHED, "_2") == "prices_2026-10-16_20261017T100000EDT_2.json.gz"


def test_the_bar_date_is_a_day_label_never_converted():
    # Midnight UTC is the evening before in New York; the label names the session itself.
    assert check_bar(bar_values(FRIDAY, "1"), 1).day == FRIDAY


def mutated(change, item=None) -> dict:
    value = value_of(item or two_days())
    change(value)
    return value


def set_bar(field, text, number=0):
    def change(value):
        value["bars"][number][field] = text

    return change


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda value: value.update(ticker="OTHER"), "the file is of OTHER, not TEST"),
        (lambda value: value.pop("request"), "the keys must be exactly"),
        (lambda value: value.update(start="2026-10-14"), "request must be https://api.tiingo.com/"),
        (lambda value: value.update(start="2026-10-17"), "start 2026-10-17 is after end 2026-10-16"),
        (lambda value: value.update(fetched_at="2026-10-17T14:00:00+00:00"), "New York time"),
        (lambda value: value.update(bars={}), "bars must be a list"),
        (lambda value: value["bars"].reverse(), "once each, in date order"),
        (lambda value: value["bars"].pop(), "the bars hold none of 2026-10-16"),
        (lambda value: value["bars"][0].pop("divCash"), "bar 1 must hold exactly date, close"),
        (set_bar("close", 95.37), "bar 1: close must be text"),
        (set_bar("date", "2026-10-15"), r"bar 1: date must be YYYY-MM-DDT00:00:00\.000Z"),
        (set_bar("date", "2026-10-14T00:00:00.000Z"), "outside 2026-10-15 to 2026-10-16"),
        (set_bar("close", "1e"), 'bar 1: close "1e" is not a decimal number'),
        (set_bar("adjClose", "0"), "bar 1: adjClose 0 must be above 0"),
        (set_bar("splitFactor", "0.0"), "bar 1: splitFactor 0.0 must be above 0"),
        (set_bar("divCash", "-0.1"), "bar 1: divCash -0.1 must be at least 0"),
    ],
)
def test_check_prices_refuses(change, message):
    with pytest.raises(ValueError, match=message):
        check(mutated(change))


def test_end_and_bars_must_be_sessions():
    with pytest.raises(ValueError, match="end 2026-10-17 is not an XNYS trading session"):
        check_prices(mutated(lambda value: value.update(end="2026-10-17")), TICKER, None, NOW)
    weekend = prices(
        {date(2026, 10, 17): "1", date(2026, 10, 19): "2"},
        start=date(2026, 10, 16),
        fetched_at=edt(2026, 10, 19, 20),
    )
    with pytest.raises(ValueError, match="2026-10-17, not an XNYS trading session"):
        check_prices(value_of(weekend), TICKER, None, edt(2026, 10, 20, 9))


def test_name_and_time_rules():
    with pytest.raises(ValueError, match="the name must be prices_2026-10-16_20261017T100000EDT.json.gz"):
        check(value_of(two_days()), "prices_2026-10-15_20261017T100000EDT.json.gz")
    early = two_days(fetched_at=edt(2026, 10, 16, 15, 59))
    with pytest.raises(ValueError, match="before the session 2026-10-16 closed"):
        check(value_of(early), "prices_2026-10-16_20261016T155900EDT.json.gz")
    future = two_days(fetched_at=edt(2026, 10, 20, 9))
    with pytest.raises(ValueError, match="later than the current time"):
        check(value_of(future), "prices_2026-10-16_20261020T090000EDT.json.gz")


def test_a_file_without_bars_is_valid():
    value = value_of(two_days())
    value["bars"] = []
    parsed = check(value)
    assert parsed.bars == ()
    assert daily_return(parsed, FRIDAY) == Value(None, "Tiingo has no prices for TEST")


def test_parse_bars_keeps_literal_numbers_and_drops_other_fields():
    body = (
        b'[{"date":"2026-10-16T00:00:00.000Z","close":89.85,"high":94.22,"low":89.19,"open":93.48,'
        b'"volume":123003084,"adjClose":89.85,"adjHigh":94.22,"adjLow":89.19,"adjOpen":93.48,'
        b'"adjVolume":123003084,"divCash":0.0,"splitFactor":1.0,"extra":true}]'
    )
    (bar,) = parse_bars(body)
    assert bar.day == FRIDAY and bar.values["divCash"] == "0.0" and "extra" not in bar.values
    assert parse_bars(b"[]") == ()
    with pytest.raises(ValueError, match="not a JSON array"):
        parse_bars(b'{"detail":"Error"}')
    with pytest.raises(ValueError, match="bar 1 lacks splitFactor"):
        parse_bars(body.replace(b',"splitFactor":1.0', b""))
    with pytest.raises(ValueError, match="more than once"):
        parse_bars(body.replace(b'"extra":true', b'"close":1'))
    with pytest.raises(ValueError, match="not a number"):
        parse_bars(body.replace(b'"extra":true', b'"x":NaN'))


def test_daily_return_by_hand():
    item = two_days()
    # 89.85 / 95.37 - 1 = -5.78798...%: rounded half-even to four places.
    assert daily_return(item, FRIDAY) == Value(Decimal("-5.7880"))
    assert daily_return(item, THURSDAY) == Value(
        None, "no bar of 2026-10-14 in the prices from 2026-10-15 to 2026-10-16"
    )
    assert daily_return(None, FRIDAY) == Value(None, "no prices are fetched")


def test_the_return_uses_adjusted_closes_of_one_file():
    # An ex-dividend Friday: Thursday's close 100 is adjusted to 99.5, Friday's is not.
    item = two_days()
    value = value_of(item)
    value["bars"][0] = bar_values(THURSDAY, "100", "99.5")
    value["bars"][1] = {**bar_values(FRIDAY, "99.6"), "divCash": "0.5"}
    parsed = check(value)
    assert parsed.bar(THURSDAY).close == Decimal("100")
    # 99.6 / 99.5 - 1 = 0.100502...%; the unadjusted closes would give -0.4 %.
    assert daily_return(parsed, FRIDAY) == Value(Decimal("0.1005"))
