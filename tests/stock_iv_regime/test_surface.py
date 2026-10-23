"""The levels at 14 and 30 days from a session's own chain, worked by hand."""

from datetime import date, timedelta
from decimal import Decimal
from fractions import Fraction

import pytest

from market_state_research.stock_iv_regime.script.surface import (
    REQUIRED,
    TERM_HORIZON,
    Value,
    difference,
    interpolate,
    iv_at,
    read_expiry,
    rounded,
    surface,
    usable,
)

from .support import TICKER, attributes, eod, quotes

SESSION = date(2026, 10, 16)
E1 = SESSION + timedelta(days=9)
E2 = SESSION + timedelta(days=19)


def rows(expiry: date, bump: str = "0", **extra):
    return [eod(SESSION, values) for values in quotes(TICKER, expiry, bump, **extra)]


def one_strike(expiry: date):
    """A stray listing: one far strike, a call and a put, like INTC's 2026-10-19 on EODHD."""
    return [
        eod(SESSION, attributes(TICKER, expiry, right, "190", delta=delta, iv="1.38"))
        for right, delta in (("call", "0.05"), ("put", "-0.99"))
    ]


def unread(
    expiry: date, days: int, deltas=(("call", "+0.25"), ("put", "-0.25"), ("call", "+0.50"), ("put", "-0.50"))
) -> str:
    """Why an expiry of ``one_strike`` gives no reading at ``deltas``."""
    return f"at {expiry} ({days}d) " + "; ".join(
        f"{right} {delta}: no usable {right} has delta {delta} and no two adjacent ones bracket it"
        for right, delta in deltas
    )


def levels(item):
    """The levels of ``item`` as text, by target, None where blank."""
    return {
        target: None if value.value is None else str(value.value) for target, value in item.levels.items()
    }


def test_iv_at_interpolates_in_delta_from_the_money_side():
    chain = rows(E1)
    calls50 = iv_at(chain, "call", Fraction(1, 2))
    assert (calls50.iv, calls50.strikes) == (Fraction("0.29"), (Decimal(150), Decimal(155)))
    calls25 = iv_at(chain, "call", Fraction(1, 4))
    assert (calls25.iv, calls25.describe()) == (Fraction("0.2725"), "155–160")
    puts50 = iv_at(chain, "put", Fraction(-1, 2))
    assert (puts50.iv, puts50.describe()) == (Fraction("0.345"), "150–155")


def test_iv_at_takes_a_contract_at_the_target_delta_exactly():
    point = iv_at(rows(E1), "put", Fraction(-1, 4))
    assert (point.iv, point.describe()) == (Fraction("0.345"), "145")


def test_one_third_weight_is_kept_exact():
    chain = [
        eod(SESSION, attributes(TICKER, E1, "call", "150", delta="0.60", iv="0.30")),
        eod(SESSION, attributes(TICKER, E1, "call", "155", delta="0.30", iv="0.31")),
    ]
    point = iv_at(chain, "call", Fraction(1, 2))
    assert point.iv == Fraction(3, 10) + Fraction(1, 100) / 3
    assert rounded(point.iv * 100) == Decimal("30.33")


def test_nothing_is_extrapolated():
    chain = [
        eod(SESSION, attributes(TICKER, E1, "call", "160", delta="0.20", iv="0.27")),
        eod(SESSION, attributes(TICKER, E1, "call", "165", delta="0.10", iv="0.26")),
    ]
    point = iv_at(chain, "call", Fraction(1, 2))
    assert point.iv is None
    assert point.reason == "no usable call has delta +0.50 and no two adjacent ones bracket it"
    assert iv_at([], "put", Fraction(-1, 4)).reason == "no usable put"


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        ({"iv": "0"}, False),
        ({"ask": "0"}, False),
        ({"delta": None}, False),
        ({"ask": None}, False),
        ({}, True),
    ],
)
def test_usable_quotes(change, expected):
    values = attributes(TICKER, E1, "call", "150", **change)
    assert usable(eod(SESSION, values)) is expected


def test_unusable_contracts_are_skipped():
    chain = rows(E1) + [eod(SESSION, attributes(TICKER, E1, "call", "152.5", delta="0.50", iv="0", ask="0"))]
    assert iv_at(chain, "call", Fraction(1, 2)).iv == Fraction("0.29")


def test_expiry_reading_gives_each_value():
    reading = read_expiry(rows(E1), E1, SESSION)
    assert (reading.days, reading.skew, reading.atm) == (9, Fraction("7.25"), Fraction("31.75"))
    assert reading.gives(REQUIRED[14]) and reading.gives(REQUIRED[30])
    assert not read_expiry(one_strike(E1), E1, SESSION).gives(REQUIRED[30])


def test_the_brackets_are_the_nearest_expiries_on_either_side_of_14_days():
    early, late = SESSION + timedelta(days=5), SESSION + timedelta(days=30)
    every = rows(early) + rows(E1) + rows(E2) + rows(late)
    item = surface(SESSION, [SESSION, early, E1, E2, late], every)
    assert (item.expiries, item.skipped, item.read) == ((E1, E2), (), (E1, E2))
    exact = SESSION + timedelta(days=14)
    assert surface(SESSION, [E1, exact, E2], rows(E1) + rows(exact) + rows(E2)).expiries == (exact,)


def test_interpolated_value_is_rounded_once_half_even():
    assert interpolate(Fraction("7.25"), 9, Fraction("8.65"), 19) == Fraction("7.95")
    assert rounded(interpolate(Fraction("1.00"), 13, Fraction("1.01"), 15)) == Decimal("1.00")
    assert rounded(interpolate(Fraction("1.01"), 13, Fraction("1.02"), 15)) == Decimal("1.02")
    assert str(rounded(Fraction(-1, 1000))) == "0.00"
    assert interpolate(Fraction(29), 19, Fraction(31), 40, TERM_HORIZON) == Fraction(29) + Fraction(22, 21)
    with pytest.raises(ValueError, match="either side of 14 days"):
        interpolate(Fraction(1), 15, Fraction(2), 40)
    with pytest.raises(ValueError, match="either side of 30 days"):
        interpolate(Fraction(1), 9, Fraction(2), 19, TERM_HORIZON)


def test_difference_is_exact_and_zero_has_no_sign():
    assert str(difference(Decimal("7.25"), Decimal("7.25"))) == "0.00"
    assert str(difference(Decimal("7.2"), Decimal("7.25"))) == "-0.05"
    assert str(difference(Decimal("-1.20"), Decimal("-1.20"))) == "0.00"


def test_surface_interpolates_between_the_brackets():
    item = surface(SESSION, [E1, E2], rows(E1) + rows(E2, "0.014"))
    assert (item.horizon, item.method, item.targets) == (14, "interpolated", REQUIRED[14])
    # The call IVs are equal at both; the put IVs 34.50 at 9 days and 35.90 at 19: 35.20.
    assert levels(item) == {"call25": "27.25", "put25": "35.20", "call50": "29.00", "put50": "35.20"}
    assert item.level("put25") == Value(Decimal("35.20"))
    assert item.detail() == "14-DTE: interpolated · 2026-10-25 (9d) → 2026-11-04 (19d)"


def test_surface_reads_an_expiry_exactly_14_days_out():
    exact = SESSION + timedelta(days=14)
    item = surface(SESSION, [E1, exact, E2], rows(exact))
    assert item.method == "exact"
    assert levels(item) == {"call25": "27.25", "put25": "34.50", "call50": "29.00", "put50": "34.50"}
    assert item.detail() == "14-DTE: exact · 2026-10-30 (14d)"


def test_surface_without_brackets_has_no_value():
    item = surface(SESSION, [E2], rows(E2))
    assert item.method == "none"
    assert levels(item) == dict.fromkeys(REQUIRED[14])
    assert item.reason == "no expiry is listed 1 to 14 days out (2026-10-17 to 2026-10-30)"
    assert item.level("call25").reason == item.reason
    assert item.detail() == "14-DTE: none · no expiry is listed 1 to 14 days out (2026-10-17 to 2026-10-30)"
    late = surface(SESSION, [E1], rows(E1))
    assert late.reason == "no expiry is listed 14 to 65 days out (2026-10-30 to 2026-12-20)"


def test_an_expiry_without_every_reading_is_skipped_and_named():
    stray = SESSION + timedelta(days=12)
    item = surface(SESSION, [E1, stray, E2], rows(E1) + one_strike(stray) + rows(E2))
    assert (item.method, item.expiries) == ("interpolated", (E1, E2))
    assert ([reading.expiry for reading in item.skipped], item.read) == ([stray], (E1, stray, E2))
    assert levels(item)["put25"] == "34.50"
    assert (
        item.detail()
        == "14-DTE: interpolated · 2026-10-25 (9d) → 2026-11-04 (19d) · skipped 2026-10-28 (12d)"
    )
    assert item.skipped[0].missing() == unread(stray, 12)


def test_a_stray_expiry_14_days_out_is_skipped_on_both_sides():
    stray = SESSION + timedelta(days=14)
    item = surface(SESSION, [E1, stray, E2], rows(E1) + one_strike(stray) + rows(E2))
    assert (item.method, item.expiries) == ("interpolated", (E1, E2))
    assert [reading.expiry for reading in item.skipped] == [stray]


def test_without_a_readable_expiry_on_a_side_there_is_no_value():
    stray = SESSION + timedelta(days=12)
    item = surface(SESSION, [stray, E2], one_strike(stray) + rows(E2))
    assert (item.method, levels(item)["put25"]) == ("none", None)
    assert item.reason == (
        "no expiry listed 1 to 14 days out (2026-10-17 to 2026-10-30) gives all four readings: "
        + unread(stray, 12)
    )
    assert item.read == (stray,)  # E2 is sought only once E1 is found
    assert item.detail() == f"14-DTE: none · {item.reason}"


def test_an_expiry_lacking_one_reading_is_skipped_too():
    # E2 lists no put out of the money beyond -0.45: nothing brackets -0.25 there.
    partial = [row for row in rows(E2) if row.right == "call" or row.strike >= 150]
    item = surface(SESSION, [E1, E2], rows(E1) + partial)
    assert (item.method, levels(item)["call50"]) == ("none", None)
    assert item.reason == (
        "no expiry listed 14 to 65 days out (2026-10-30 to 2026-12-20) gives all four readings: at "
        "2026-11-04 (19d) put -0.25: no usable put has delta -0.25 and no two adjacent ones bracket it"
    )
    later = SESSION + timedelta(days=40)
    found = surface(SESSION, [E1, E2, later], rows(E1) + partial + rows(later))
    assert found.expiries == (E1, later) and [reading.expiry for reading in found.skipped] == [E2]
    assert levels(found)["put25"] == "34.50"


def test_at_30_days_an_expiry_needs_only_the_two_50_delta_readings():
    # E2 lacks the put at -0.25 but gives both 50-delta readings: a 30-DTE bracket, not a 14-DTE one.
    partial = [row for row in rows(E2) if row.right == "call" or row.strike >= 150]
    later = SESSION + timedelta(days=40)
    item = surface(SESSION, [E1, E2, later], rows(E1) + partial + rows(later, level="0.021"), TERM_HORIZON)
    assert (item.horizon, item.method, item.expiries, item.skipped) == (30, "interpolated", (E2, later), ())
    assert item.targets == ("call50", "put50")
    # 29.00 and 31.10 at 19 and 40 days: 29.00 + 2.10 x 11/21 = 30.10; the put 34.50 and 36.60: 35.60.
    assert levels(item) == {"call50": "30.10", "put50": "35.60"}
    assert item.detail() == "30-DTE: interpolated · 2026-11-04 (19d) → 2026-11-25 (40d)"
    exact = SESSION + timedelta(days=30)
    assert surface(SESSION, [E2, exact, later], rows(exact), TERM_HORIZON).method == "exact"


def test_at_30_days_a_stray_expiry_is_skipped_for_its_50_delta_readings_alone():
    stray = SESSION + timedelta(days=26)
    later = SESSION + timedelta(days=40)
    item = surface(SESSION, [E2, stray, later], rows(E2) + one_strike(stray) + rows(later), TERM_HORIZON)
    assert (item.expiries, [reading.expiry for reading in item.skipped]) == ((E2, later), [stray])
    assert item.skipped[0].missing(item.targets) == unread(stray, 26, (("call", "+0.50"), ("put", "-0.50")))
    alone = surface(SESSION, [stray, later], one_strike(stray) + rows(later), TERM_HORIZON)
    assert alone.reason == (
        "no expiry listed 1 to 30 days out (2026-10-17 to 2026-11-15) gives both 50Δ readings: "
        + unread(stray, 26, (("call", "+0.50"), ("put", "-0.50")))
    )
    none = surface(SESSION, [E1, E2], rows(E1) + rows(E2), TERM_HORIZON)
    assert none.reason == "no expiry is listed 30 to 65 days out (2026-11-15 to 2026-12-20)"
    assert levels(none) == {"call50": None, "put50": None}


def test_a_horizon_is_14_or_30_days():
    with pytest.raises(ValueError, match="the horizon must be one of 14, 30 days"):
        surface(SESSION, [E1, E2], rows(E1) + rows(E2), 21)
