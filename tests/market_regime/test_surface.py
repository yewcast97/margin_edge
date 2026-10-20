"""The 14-DTE values from a session's own chain, worked by hand."""

from datetime import date, timedelta
from decimal import Decimal
from fractions import Fraction

import pytest

from market_state_research.market_regime.script.surface import (
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


def unread(expiry: date, days: int) -> str:
    """Why an expiry of ``one_strike`` gives no reading."""
    return f"at {expiry} ({days}d) " + "; ".join(
        f"{right} {delta}: no usable {right} has delta {delta} and no two adjacent ones bracket it"
        for right, delta in (("call", "+0.25"), ("put", "-0.25"), ("call", "+0.50"), ("put", "-0.50"))
    )


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
    assert (reading.call25, reading.put25) == (Fraction("27.25"), Fraction("34.5"))


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
    with pytest.raises(ValueError, match="either side of 14 days"):
        interpolate(Fraction(1), 15, Fraction(2), 40)


def test_difference_is_exact_and_zero_has_no_sign():
    assert str(difference(Decimal("7.25"), Decimal("7.25"))) == "0.00"
    assert str(difference(Decimal("7.2"), Decimal("7.25"))) == "-0.05"
    assert str(difference(Decimal("-1.20"), Decimal("-1.20"))) == "0.00"


def test_surface_interpolates_between_the_brackets():
    item = surface(SESSION, [E1, E2], rows(E1) + rows(E2, "0.014"))
    assert item.method == "interpolated"
    # 7.25 at 9 days, 8.65 at 19: 7.25 + 1.4 x 5/10 = 7.95; ATM 31.75 and 32.45: 32.10; the
    # call IV 27.25 at both; the put IV 34.50 and 35.90: 35.20.
    assert (item.skew.value, item.atm.value) == (Decimal("7.95"), Decimal("32.10"))
    assert (item.call25.value, item.put25.value) == (Decimal("27.25"), Decimal("35.20"))
    assert item.detail() == "interpolated · 2026-10-25 (9d) → 2026-11-04 (19d)"


def test_surface_reads_an_expiry_exactly_14_days_out():
    exact = SESSION + timedelta(days=14)
    item = surface(SESSION, [E1, exact, E2], rows(exact))
    assert (item.method, item.skew.value, item.atm.value) == ("exact", Decimal("7.25"), Decimal("31.75"))
    assert (item.call25.value, item.put25.value) == (Decimal("27.25"), Decimal("34.50"))
    assert item.detail() == "exact · 2026-10-30 (14d)"


def test_surface_without_brackets_has_no_value():
    item = surface(SESSION, [E2], rows(E2))
    assert (item.method, item.skew.value, item.atm.value) == ("none", None, None)
    assert (item.call25.value, item.put25.value) == (None, None)
    assert item.reason == "no expiry is listed 1 to 14 days out (2026-10-17 to 2026-10-30)"
    assert item.call25.reason == item.reason
    assert (
        item.detail() == "no 14-DTE value · no expiry is listed 1 to 14 days out (2026-10-17 to 2026-10-30)"
    )
    late = surface(SESSION, [E1], rows(E1))
    assert late.reason == "no expiry is listed 14 to 65 days out (2026-10-30 to 2026-12-20)"


def test_an_expiry_without_every_reading_is_skipped_and_named():
    stray = SESSION + timedelta(days=12)
    item = surface(SESSION, [E1, stray, E2], rows(E1) + one_strike(stray) + rows(E2))
    assert (item.method, item.expiries) == ("interpolated", (E1, E2))
    assert ([reading.expiry for reading in item.skipped], item.read) == ([stray], (E1, stray, E2))
    assert (item.skew.value, item.atm.value) == (Decimal("7.25"), Decimal("31.75"))
    assert item.detail() == "interpolated · 2026-10-25 (9d) → 2026-11-04 (19d) · skipped 2026-10-28 (12d)"
    assert item.skipped[0].missing() == unread(stray, 12)


def test_a_stray_expiry_14_days_out_is_skipped_on_both_sides():
    stray = SESSION + timedelta(days=14)
    item = surface(SESSION, [E1, stray, E2], rows(E1) + one_strike(stray) + rows(E2))
    assert (item.method, item.expiries) == ("interpolated", (E1, E2))
    assert [reading.expiry for reading in item.skipped] == [stray]


def test_without_a_readable_expiry_on_a_side_there_is_no_value():
    stray = SESSION + timedelta(days=12)
    item = surface(SESSION, [stray, E2], one_strike(stray) + rows(E2))
    assert (item.method, item.skew.value, item.put25.value) == ("none", None, None)
    assert item.reason == (
        "no expiry listed 1 to 14 days out (2026-10-17 to 2026-10-30) gives all four readings: "
        + unread(stray, 12)
    )
    assert item.read == (stray,)  # E2 is sought only once E1 is found
    assert item.detail() == f"no 14-DTE value · {item.reason}"


def test_an_expiry_lacking_one_reading_is_skipped_too():
    # E2 lists no put out of the money beyond -0.45: nothing brackets -0.25 there.
    partial = [row for row in rows(E2) if row.right == "call" or row.strike >= 150]
    item = surface(SESSION, [E1, E2], rows(E1) + partial)
    assert (item.method, item.atm.value, item.call25.value) == ("none", None, None)
    assert item.reason == (
        "no expiry listed 14 to 65 days out (2026-10-30 to 2026-12-20) gives all four readings: at "
        "2026-11-04 (19d) put -0.25: no usable put has delta -0.25 and no two adjacent ones bracket it"
    )
    later = SESSION + timedelta(days=40)
    found = surface(SESSION, [E1, E2, later], rows(E1) + partial + rows(later))
    assert found.expiries == (E1, later) and [reading.expiry for reading in found.skipped] == [E2]
    assert found.skew.value == Decimal("7.25")
