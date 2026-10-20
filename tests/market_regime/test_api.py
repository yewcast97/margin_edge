"""EODHD's pages: the queries, the literal numbers, the record checks and one page per query."""

import json
from datetime import date
from decimal import Decimal

import pytest

from market_state_research.market_regime.script.api import (
    FIELDS,
    Page,
    Query,
    check_attributes,
    check_item,
    load_json,
    page,
    parse_occ,
    parse_page,
)
from market_state_research.market_regime.script.client import EodhdError

from .fake_eodhd import FakeEodhd
from .support import TICKER, attributes

EXPIRY = date(2026, 11, 20)


def test_query_urls_are_token_free_and_name_every_field():
    query = Query("eod", (("underlying_symbol", "AAPL"), ("exp_date_eq", "2026-11-20")), "strike")
    assert query.url() == (
        "https://eodhd.com/api/mp/unicornbay/options/eod?filter%5Bunderlying_symbol%5D=AAPL"
        "&filter%5Bexp_date_eq%5D=2026-11-20&fields%5Boptions-eod%5D=contract%2Cexp_date%2Cexpiration_type"
        "%2Ctype%2Cstrike%2Cbid%2Cask%2Cvolume%2Copen_interest%2Cvolatility%2Cdelta%2Ctradetime"
        "&sort=strike&page%5Blimit%5D=1000"
    )


def test_load_json_keeps_literal_numbers():
    assert load_json(b'{"a": 0.10, "b": 150, "c": -0.5, "d": 1e-05}') == {
        "a": "0.10",
        "b": "150",
        "c": "-0.5",
        "d": "1e-05",
    }


@pytest.mark.parametrize(
    ("body", "message"),
    [
        (b'{"a": NaN}', "NaN is not a number"),
        (b'{"a": 1, "a": 2}', 'key "a" appears more than once'),
        (b"\xff", "not UTF-8"),
        (b"{", "invalid JSON"),
    ],
)
def test_load_json_refuses(body, message):
    with pytest.raises(ValueError, match=message):
        load_json(body)


def test_parse_occ():
    contract = parse_occ("AAPL1261120C00252500")
    assert (contract.root, contract.expiry, contract.right, contract.strike) == (
        "AAPL1",
        EXPIRY,
        "call",
        Decimal("252.5"),
    )
    with pytest.raises(ValueError):
        parse_occ("AAPL261131C00250000")


def test_check_attributes_accepts_the_provider_forms():
    assert (
        check_attributes(attributes(TICKER, EXPIRY, "put", "252.5", delta="-0.25", tradetime="2026-10-16"))
        is None
    )


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"strike": "255"}, "has strike 252.5, not 255"),
        ({"type": "call"}, "is a put, not a call"),
        ({"exp_date": "2026-11-21"}, "expires 2026-11-20, not on exp_date 2026-11-21"),
        ({"delta": "-1.5"}, "delta -1.5 is outside -1 to 1"),
        ({"volatility": "-0.1"}, "volatility -0.1 is negative"),
        ({"volume": "1.5"}, 'volume "1.5" is not a whole number'),
        ({"bid": "abc"}, 'bid "abc" is not a decimal number'),
        ({"tradetime": "2026-13-01"}, "is not a date that exists"),
        ({"expiration_type": "Weekly"}, "is not a lower-case word"),
        ({"strike": None}, "strike is null"),
    ],
)
def test_check_attributes_refuses(change, message):
    values = attributes(TICKER, EXPIRY, "put", "252.5")
    values.update(change)
    problem = check_attributes(values)
    assert problem is not None and message in problem


def test_check_attributes_wants_exactly_the_fields():
    values = attributes(TICKER, EXPIRY, "call", "250")
    del values["delta"]
    values["theta"] = "0.1"
    assert check_attributes(values) == (
        f'the attributes must be exactly {", ".join(FIELDS)}: lacks delta; has "theta"'
    )


def test_check_item_ids():
    values = attributes(TICKER, EXPIRY, "call", "250")
    contract = values["contract"]
    record = check_item({"id": f"{contract}-2026-10-16", "type": "options-eod", "attributes": values}, "eod")
    assert record.date == date(2026, 10, 16)
    assert (
        check_item({"id": contract, "type": "options-contracts", "attributes": values}, "contracts").date
        is None
    )
    with pytest.raises(ValueError, match="must have the id"):
        check_item({"id": contract, "type": "options-eod", "attributes": values}, "eod")
    with pytest.raises(ValueError, match="must have type options-contracts"):
        check_item({"id": contract, "type": "options-eod", "attributes": values}, "contracts")


def test_parse_page_checks_meta():
    query = Query("contracts", (("underlying_symbol", TICKER),), "exp_date")
    body = b'{"meta":{"offset":0,"limit":1000,"fields":["contract"]},"data":[],"links":{"next":null}}'
    with pytest.raises(ValueError, match="meta.fields must be exactly none on a page without records"):
        parse_page(body, query)
    # As EODHD answers a query that matches nothing (verified live on 2026-10-19).
    empty = b'{"meta":{"offset":0,"limit":1000,"fields":[]},"data":[],"links":{"next":null}}'
    assert parse_page(empty, query) == Page((), False)
    values = attributes(TICKER, EXPIRY, "call", "250")
    item = json.dumps({"id": values["contract"], "type": "options-contracts", "attributes": values})
    unnamed = (
        b'{"meta":{"offset":0,"limit":1000,"fields":[]},"data":[%s],"links":{"next":null}}' % item.encode()
    )
    with pytest.raises(ValueError, match="meta.fields must be exactly contract,"):
        parse_page(unnamed, query)
    fields = ",".join(f'"{name}"' for name in FIELDS)
    body = (
        b'{"meta":{"offset":1000,"limit":1000,"fields":[%s]},"data":[],"links":{"next":null}}'
        % fields.encode()
    )
    with pytest.raises(ValueError, match="offset 0"):
        parse_page(body, query)


def many(count: int) -> FakeEodhd:
    fake = FakeEodhd()
    fake.listing = [attributes(TICKER, EXPIRY, "call", str(strike)) for strike in range(1, count + 1)]
    return fake


def test_one_page_answers_a_query_and_says_whether_more_matched():
    fake = many(2500)
    query = Query("contracts", (("underlying_symbol", TICKER),), "exp_date")
    answer = page(fake.client(), query)
    assert (len(answer.records), answer.more) == (1000, True)
    assert fake.calls == [query.url()] and set(fake.tokens) == {"CANARYkey0123456789"}
    assert page(many(1000).client(), query).more is False


def test_an_invalid_page_names_its_url():
    fake = many(1)
    fake.listing[0] = {**fake.listing[0], "delta": "2"}
    query = Query("contracts", (("underlying_symbol", TICKER),), "exp_date")
    with pytest.raises(
        EodhdError, match=r"page%5Blimit%5D=1000: the response is not EODHD's options page: .*delta 2"
    ):
        page(fake.client(), query)
