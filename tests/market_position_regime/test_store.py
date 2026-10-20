"""Reading raw/market/, selection by newest file, the derived rows and the two tables."""

from datetime import date
from decimal import Decimal

from market_state_research.market_position_regime.script import fred
from market_state_research.market_position_regime.script.cftc import check_answer
from market_state_research.market_position_regime.script.periods import Month
from market_state_research.market_position_regime.script.store import (
    FUTURES_COLUMNS,
    MARGIN_COLUMNS,
    Stored,
    csv_paths,
    derive_futures,
    derive_margin,
    futures_text,
    margin_text,
    raw_directory,
    read_raw,
    select_reports,
    select_series,
    select_workbook,
    write_table,
)

from .support import (
    FETCHED,
    NOW,
    TWO_FIFTY,
    answer_value,
    balances,
    edt,
    quarter_values,
    save_answer,
    save_series,
    save_workbook,
    tff_row,
    weekly_rows,
    weeks_back,
    workbook_bytes,
)


def test_every_raw_file_is_validated_and_a_failure_is_named_never_skipped(layout):
    save_workbook(layout)
    directory = raw_directory(layout)
    (directory / "notes.txt").write_text("hello")
    (directory / "finra_margin_20261020T130000EDT.xlsx").write_bytes(b"not a workbook")
    (directory / "fred_NCBEILQ027S_20261020T130000EDT.json.rejected").write_text("withdrawn")
    raw = read_raw(layout, NOW)
    assert len(raw.workbooks) == 1
    reasons = {item.path.name: item.reason for item in raw.invalid}
    assert reasons == {
        "notes.txt": "not a raw file name (finra_margin_TOKEN.xlsx, cftc_tff_FIRST_LAST_TOKEN.json or "
        "fred_SERIES_TOKEN.json)",
        "finra_margin_20261020T130000EDT.xlsx": "not an Excel workbook (a zip archive)",
    }


def test_the_newest_valid_file_wins(layout):
    save_workbook(layout, workbook_bytes(balances(Month(2026, 8))), edt(2026, 9, 20, 9, 0))
    save_workbook(layout, fetched_at=FETCHED)
    save_series(layout, fred.NONFINANCIAL, quarter_values(value="1"), edt(2026, 9, 20, 9, 0))
    save_series(layout, fred.NONFINANCIAL, quarter_values(value="2"), FETCHED)
    raw = read_raw(layout, NOW)
    assert select_workbook(raw.workbooks).workbook.newest == Month(2026, 9)  # type: ignore[union-attr]
    chosen = select_series(raw.series)[fred.NONFINANCIAL].series
    assert chosen.by_quarter_end()[date(2026, 6, 30)].value == Decimal(2)


def test_each_week_is_taken_from_the_newest_answer_holding_it(layout):
    weeks = weeks_back(date(2026, 10, 13), 3)
    save_answer(layout, weekly_rows(weeks, lambda week: 100), fetched_at=edt(2026, 10, 17, 9, 0))
    save_answer(layout, weekly_rows(weeks[1:2], lambda week: 999), fetched_at=FETCHED)
    reports = select_reports(read_raw(layout, NOW).answers)
    assert [week for week in reports] == weeks
    assert [stored.report.asset_mgr_net for stored in reports.values()] == [100, 999, 100]
    assert reports[weeks[1]].source == "cftc_tff_2026-10-05_2026-10-11_20261020T120000EDT.json"


def test_margin_rows_carry_growth_and_the_ratio_to_their_quarter_ends_market_value(layout):
    save_workbook(layout)
    save_series(layout, fred.NONFINANCIAL, quarter_values(value="80000000"))
    save_series(layout, fred.FINANCIAL, quarter_values(value="20000000.0"))
    raw = read_raw(layout, NOW)
    rows = derive_margin(select_workbook(raw.workbooks), select_series(raw.series))
    august = rows[Month(2026, 8)]
    # debit(2026-08) = 455,000 and debit(2025-08) = 443,000: (455,000 / 443,000 − 1) × 100 = 2.708...
    assert (august.balance.debit, august.yoy.value) == (455_000, Decimal("2.7"))
    assert (august.quarter_end, august.market_value.value) == (date(2026, 6, 30), Decimal("100000000.0"))
    assert august.ratio.value == Decimal("0.46")  # 455,000 / 100,000,000 × 100 = 0.455: half-even, 0.46
    september = rows[Month(2026, 9)]
    assert september.ratio.value is None and september.ratio.reason == (
        "the stored NCBEILQ027S ends 2026-06-30, before 2026-09-30 (Z.1 due 2026-12-15)"
    )
    first = rows[Month(1997, 1)]
    assert first.yoy.reason == "no balance of 1996-01 (FINRA's table starts 1997-01)"
    assert first.ratio.reason == "the stored NCBEILQ027S starts 2019-12-31, after 1996-12-31"


def test_a_market_value_needs_both_series(layout):
    save_workbook(layout)
    save_series(layout, fred.NONFINANCIAL)
    raw = read_raw(layout, NOW)
    rows = derive_margin(select_workbook(raw.workbooks), select_series(raw.series))
    assert rows[Month(2026, 8)].ratio.reason == "no FRED answer of BOGZ1LM793164105Q is stored"
    values = quarter_values() | {date(2026, 6, 30): "."}
    save_series(layout, fred.FINANCIAL, values, edt(2026, 10, 20, 13, 0))
    raw = read_raw(layout, NOW)
    rows = derive_margin(select_workbook(raw.workbooks), select_series(raw.series))
    assert rows[Month(2026, 8)].ratio.reason == "FRED gives no value of BOGZ1LM793164105Q for 2026-06-30"
    assert rows[Month(2026, 3)].ratio.value is not None


def test_futures_rows_rank_nets_in_e_mini_equivalents_across_the_unit_change():
    weeks = weeks_back(date(2023, 5, 2), 52)
    rows = [
        tff_row(week, asset_mgr=(300, 100, 0), lev_money=(0, 0, 0), units=TWO_FIFTY) for week in weeks[:-1]
    ] + [tff_row(weeks[-1], asset_mgr=(1_100, 100, 0), lev_money=(0, 0, 0))]
    answer = check_answer(answer_value(rows, date(2022, 5, 9), date(2023, 5, 7)), None, NOW)
    reports = {report.week: Stored(report, FETCHED, "x.json") for report in answer.reports}
    found = derive_futures(reports)
    # Every earlier week nets (300 − 100) × 5 = 1,000 E-mini contracts, the newest 1,000 as well:
    # none is strictly below, so the percentile is 0.0, not 100 as raw counts (200 < 1,000) would give.
    newest = found[weeks[-1]]
    assert (newest.report.asset_mgr_net, newest.asset_mgr.value, newest.asset_mgr.n) == (
        1_000,
        Decimal("0.0"),
        51,
    )


def test_the_tables_hold_every_row_in_date_order(layout):
    save_workbook(layout)
    save_series(layout, fred.NONFINANCIAL)
    save_series(layout, fred.FINANCIAL)
    save_answer(layout, weekly_rows(weeks_back(date(2026, 10, 13), 2)))
    raw = read_raw(layout, NOW)
    margin = margin_text(derive_margin(select_workbook(raw.workbooks), select_series(raw.series)).values())
    lines = margin.splitlines()
    assert lines[0] == ",".join(MARGIN_COLUMNS)
    assert lines[1] == "1997-01,100000,3000,,,1996-12-31,,,finra_margin_20261020T120000EDT.xlsx,"
    assert lines[-1] == "2026-09,456000,3000,2000,2.7,2026-09-30,,,finra_margin_20261020T120000EDT.xlsx,"
    assert lines[-2] == (
        "2026-08,455000,3000,2000,2.7,2026-06-30,100000000.0,0.46,finra_margin_20261020T120000EDT.xlsx,"
        "fred_NCBEILQ027S_20261020T120000EDT.json fred_BOGZ1LM793164105Q_20261020T120000EDT.json"
    )
    futures = futures_text(derive_futures(select_reports(raw.answers)).values()).splitlines()
    assert futures[0] == ",".join(FUTURES_COLUMNS)
    assert futures[2] == (
        "2026-10-13,(S&P 500 INDEX X $50.00),50,2000,1800,1000,50,100,500,20,800,400,,,"
        "2026-10-20T12:00:00-04:00,cftc_tff_2026-10-05_2026-10-18_20261020T120000EDT.json"
    )


def test_a_table_is_written_only_when_its_bytes_change(layout):
    path = csv_paths(layout)[0]
    assert write_table(path, "a\n") is True
    before = path.stat().st_mtime_ns
    assert write_table(path, "a\n") is False and path.stat().st_mtime_ns == before
    assert write_table(path, "b\n") is True and path.read_text() == "b\n"
