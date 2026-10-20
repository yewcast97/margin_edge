"""The raw unit: its bytes, its name and every rule a raw chain must meet."""

import gzip
import json
from datetime import date, timedelta

import pytest

from market_state_research.market_regime.script.chain import (
    FORMER_HORIZON,
    MAX_UNCOMPRESSED,
    check_chain,
    dump,
    load,
    proof_problem,
    raw_name,
    read_chain,
)

from .support import FETCHED, NOW, TICKER, attributes, chain, edt, eod, listed, quotes, standard

SESSION = date(2026, 10, 16)
E1, E2, E3 = (SESSION + timedelta(days=days) for days in (9, 19, 40))
NAME = "chain_2026-10-16_20261017T100000EDT.json.gz"


def value_of(item) -> dict:
    return json.loads(gzip.decompress(dump(item)))


def check(value, name=NAME, ticker=TICKER):
    return check_chain(value, ticker, name, NOW)


def test_dump_is_deterministic_and_keeps_literal_text():
    item = chain(SESSION, {E1: [attributes(TICKER, E1, "call", "150", delta="-0.5", iv="0.10", bid="150")]})
    first, second = dump(item), dump(item)
    assert first == second
    assert first[4:8] == b"\x00\x00\x00\x00"  # mtime 0
    stored = value_of(item)["rows"][0]["attributes"]
    assert (stored["volatility"], stored["bid"], stored["delta"]) == ("0.10", "150", "-0.5")
    assert read_chain(first, TICKER, NAME, NOW).rows[0].attributes["volatility"] == "0.10"


def test_raw_name():
    assert raw_name(SESSION, FETCHED) == NAME
    assert raw_name(SESSION, FETCHED, "_2") == "chain_2026-10-16_20261017T100000EDT_2.json.gz"


def test_a_standard_chain_is_valid():
    item = standard(SESSION)
    parsed = check(value_of(item))
    assert parsed.listed == (E1, E2, E3)
    assert {row.expiry for row in parsed.rows} == {E1, E2, E3} and len(parsed.rows) == 21
    assert check(value_of(item), "chain_2026-10-16_20261017T100000EDT_3.json.gz").session == SESSION


def test_load_refuses_what_is_not_a_raw_file():
    with pytest.raises(ValueError, match="not a gzip file"):
        load(b"plain")
    with pytest.raises(ValueError, match="uncompressed"):
        load(gzip.compress(b" " * (MAX_UNCOMPRESSED + 1)))
    with pytest.raises(ValueError, match="never does"):
        load(gzip.compress(b'{"a": 1.5}'))
    with pytest.raises(ValueError, match="more than once"):
        load(gzip.compress(b'{"a": 1, "a": 1}'))


def mutated(change, item=None) -> dict:
    value = value_of(item or standard(SESSION))
    change(value)
    return value


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda value: value.update(ticker="OTHER"), "the file is of OTHER, not TEST"),
        (lambda value: value.update(horizon_days=30), FORMER_HORIZON),
        (lambda value: value.update(window_days=60), "window_days must be 65"),
        (lambda value: value.update(source="api"), "source must be contracts or eod"),
        (lambda value: value.update(fetched_at="2026-10-17T10:00:00+00:00"), "New York time"),
        (lambda value: value.update(requests=[]), "requests must list"),
        (
            lambda value: value.update(
                requests=["https://eodhd.com/api/mp/unicornbay/options/eod?api_token=x"]
            ),
            "requests must list",
        ),
        (lambda value: value.update(traded=[]), "traded must be a list for the contracts source"),
        (lambda value: value["expiries"].reverse(), "in date order"),
        (lambda value: value["expiries"][0].update(contracts=0), "lists no contract"),
        (lambda value: value["expiries"][0].update(contracts=True), "must be a whole number"),
        (
            lambda value: value["expiries"].append({"exp_date": "2026-12-25", "contracts": 1}),
            "1 to 65 days after",
        ),
        (lambda value: value["rows"].pop(), "lists 7 contracts but rows hold 6"),
        (lambda value: value["rows"].append(value["rows"][0]), "more than once"),
        (
            lambda value: value["rows"][0]["attributes"].update(volatility=0.3),
            "must be text, a number or null",
        ),
        (lambda value: value.pop("traded"), "the keys must be exactly"),
    ],
)
def test_check_chain_refuses(change, message):
    with pytest.raises(ValueError, match=message):
        check(mutated(change))


def test_a_chain_of_the_former_horizon_rule_is_refused_whatever_else_it_holds():
    def former(value):
        value.clear()
        value.update(session="2026-10-16", horizon_days=30, window_days=65)

    with pytest.raises(ValueError, match="^this chain was cut by the former 30-day horizon rule; rename it"):
        check(mutated(former))


def test_rows_must_be_of_listed_expiries_and_the_session():
    unlisted = SESSION + timedelta(days=50)
    far = [eod(SESSION, values) for values in quotes(TICKER, unlisted)]

    def add_far(value):
        value["rows"].extend(record.item() for record in far)

    with pytest.raises(ValueError, match="expires 2026-12-05, not a listed expiry"):
        check(mutated(add_far))

    def redate(value):
        row = value["rows"][0]
        row["id"] = row["id"][:-10] + "2026-10-15"

    with pytest.raises(ValueError, match="is not dated 2026-10-16"):
        check(mutated(redate))


def test_rows_of_another_root_or_traded_later_are_refused():
    adjusted = standard(SESSION, ticker="TEST1")

    def rename(value):
        value["ticker"] = TICKER

    with pytest.raises(ValueError, match="is not a contract of TEST"):
        check(mutated(rename, adjusted))
    late = chain(SESSION, {E1: quotes(TICKER, E1, tradetime="2026-10-19"), E2: quotes(TICKER, E2)})
    with pytest.raises(ValueError, match="last traded on 2026-10-19, after 2026-10-16"):
        check(value_of(late))


def test_name_session_and_time_rules():
    with pytest.raises(ValueError, match="the name must be chain_2026-10-16_20261017T100000EDT.json.gz"):
        check(value_of(standard(SESSION)), "chain_2026-10-15_20261017T100000EDT.json.gz")
    with pytest.raises(ValueError, match="is not an XNYS trading session"):
        check(value_of(standard(date(2026, 10, 17))), "chain_2026-10-17_20261017T100000EDT.json.gz")
    early = standard(SESSION, fetched_at=edt(2026, 10, 16, 15, 59))
    with pytest.raises(ValueError, match="before the session closed"):
        check(value_of(early), "chain_2026-10-16_20261016T155900EDT.json.gz")
    future = standard(SESSION, fetched_at=edt(2026, 10, 20, 9))
    with pytest.raises(ValueError, match="later than the current time"):
        check(value_of(future), "chain_2026-10-16_20261020T090000EDT.json.gz")


def contracts_chain(traded, by_expiry=None):
    by_expiry = by_expiry or {E1: quotes(TICKER, E1), E2: quotes(TICKER, E2), E3: quotes(TICKER, E3)}
    return chain(SESSION, by_expiry, source="contracts", traded=traded)


def test_contracts_source_needs_the_proof():
    traded = [quotes(TICKER, E1)[0]]
    assert check(value_of(contracts_chain(traded))).traded is not None
    with pytest.raises(ValueError, match="no eod record dated 2026-10-16 proves"):
        check(value_of(contracts_chain([])))
    changed = [{**quotes(TICKER, E1)[0], "volatility": "0.31"}]
    with pytest.raises(ValueError, match="the contracts listing's volatility differs"):
        check(value_of(contracts_chain(changed)))


def test_the_proof_compares_numbers_as_decimals_over_every_expiry():
    row = quotes(TICKER, E1)[0]
    same = [{**row, "volatility": "0.300"}]
    assert check(value_of(contracts_chain(same))).source == "contracts"
    far = quotes(TICKER, E3)[0]  # the expiry after the brackets: its traded record is proved too
    assert check(value_of(contracts_chain([far]))).source == "contracts"
    with pytest.raises(ValueError, match="the contracts listing's bid differs"):
        check(value_of(contracts_chain([{**far, "bid": "2"}])))


def test_proof_problem_cases():
    rows = [listed(values) for values in quotes(TICKER, E1)]
    dated = [eod(SESSION, quotes(TICKER, E1)[0])]
    assert proof_problem(SESSION, rows, dated) is None
    later = [eod(SESSION + timedelta(days=3), quotes(TICKER, E1)[0])]
    assert proof_problem(SESSION, rows, later) == f"traded record {later[0].id} is not dated 2026-10-16"
    unlisted = [eod(SESSION, quotes(TICKER, E2)[0])]
    assert proof_problem(SESSION, rows, unlisted) == (
        f"{unlisted[0].contract} traded on 2026-10-16, but the contracts listing does not list it"
    )
    rows[1] = listed({**quotes(TICKER, E1)[1], "tradetime": "2026-10-19"})
    assert "after 2026-10-16" in (proof_problem(SESSION, rows, dated) or "")
