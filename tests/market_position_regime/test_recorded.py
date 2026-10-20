"""An answer recorded live from the CFTC (2026-10-20): the S&P 500 Consolidated's rows from
2023-04-03 to 2025-11-16.

The fixture is the body the CFTC's API returned to ``cftc.query_url`` of those dates, byte
for byte, pinned by SHA-256 and never edited; the CFTC's data are a US government work. It
spans the change of the standard contract on 2023-05-02 and two weeks reported as of a
Monday (2023-07-03 and 2025-11-10, the Tuesdays being holidays).
"""

import hashlib
import json
from datetime import date
from decimal import Decimal
from pathlib import Path

from market_state_research.market_position_regime.script import cftc
from market_state_research.market_position_regime.script.cftc import (
    check_answer,
    dump,
    parse_rows,
    read_answer,
)
from market_state_research.market_position_regime.script.periods import weeks_within
from market_state_research.market_position_regime.script.store import Stored, derive_futures

from .support import FETCHED, NOW

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "cftc_tff_2023-04-03_2025-11-16.json"
PINNED = "00a1760a173844d671a8240553058118c586ab41b24b248ce18718c0272a1e94"
FIRST, LAST = date(2023, 4, 3), date(2025, 11, 16)


def recorded():
    value = {
        "request": cftc.query_url(FIRST, LAST),
        "fetched_at": FETCHED.isoformat(),
        "first": FIRST.isoformat(),
        "last": LAST.isoformat(),
        "rows": parse_rows(FIXTURE.read_bytes()),
    }
    return check_answer(value, None, NOW)


def test_the_fixture_is_the_recorded_bytes():
    assert hashlib.sha256(FIXTURE.read_bytes()).hexdigest() == PINNED


def test_every_recorded_row_passes_and_every_week_has_one_report():
    answer = recorded()
    assert len(answer.reports) == 137
    assert [report.week for report in answer.reports] == list(
        weeks_within(date(2023, 4, 4), date(2025, 11, 11))
    )
    mondays = [report.as_of for report in answer.reports if report.as_of.weekday() == 0]
    assert mondays == [date(2023, 7, 3), date(2025, 11, 10)]
    name = cftc.raw_name(FIRST, LAST, FETCHED)
    assert read_answer(dump(answer), name, NOW) == answer
    assert [report.row for report in answer.reports] == json.loads(FIXTURE.read_bytes())


def test_the_contract_change_is_converted_to_e_mini_equivalents():
    by_date = {report.as_of: report for report in recorded().reports}
    before, after = by_date[date(2023, 4, 25)], by_date[date(2023, 5, 2)]
    assert (before.row["contract_units"], before.multiplier, before.open_interest) == (
        "(S&P 500 INDEX X $250.00)",
        250,
        453_159,
    )
    assert (after.row["contract_units"], after.multiplier, after.open_interest) == (
        "(S&P 500 INDEX X $50.00)",
        50,
        2_304_633,
    )
    assert (before.asset_mgr_net, after.asset_mgr_net) == (584_475, 594_746)
    assert (before.lev_money_net_short, after.lev_money_net_short) == (475_070, 457_123)


def test_percentiles_rest_on_the_52_weeks_once_they_are_all_recorded():
    answer = recorded()
    rows = derive_futures({report.week: Stored(report, FETCHED, FIXTURE.name) for report in answer.reports})
    weeks = list(rows)
    assert all(rows[week].asset_mgr.value is None for week in weeks[:51])
    first = rows[weeks[51]]
    assert first.asset_mgr.n == 51 and first.asset_mgr.value is not None
    assert all(Decimal(0) <= (row.asset_mgr.value or Decimal(0)) <= Decimal(100) for row in rows.values())
