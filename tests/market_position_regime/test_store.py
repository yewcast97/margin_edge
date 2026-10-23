"""Reading raw/market/, selection by newest file, the derived rows and the three tables."""

from datetime import date
from decimal import Decimal

from market_state_research.market_position_regime.script.cboe import SKEW, VIX
from market_state_research.market_position_regime.script.cftc import check_answer
from market_state_research.market_position_regime.script.finra import Balance
from market_state_research.market_position_regime.script.indicators import Percentile
from market_state_research.market_position_regime.script.periods import Month
from market_state_research.market_position_regime.script.store import (
    FUTURES_COLUMNS,
    INDICES_COLUMNS,
    MARGIN_COLUMNS,
    Stored,
    csv_paths,
    derive_futures,
    derive_indices,
    derive_margin,
    futures_text,
    indices_text,
    margin_text,
    raw_directory,
    read_raw,
    select_history,
    select_reports,
    select_workbook,
    write_table,
)

from .support import (
    FETCHED,
    NOW,
    TWO_FIFTY,
    VIX_FETCHED,
    answer_value,
    balances,
    edt,
    history_bytes,
    save_answer,
    save_history,
    save_skew,
    save_workbook,
    skew_bytes,
    tff_row,
    weekly_rows,
    weeks_back,
    workbook_bytes,
)


def test_every_raw_file_is_validated_and_a_failure_is_named_never_skipped(layout):
    save_workbook(layout)
    save_history(layout)
    directory = raw_directory(layout)
    (directory / "notes.txt").write_text("hello")
    (directory / "fred_NCBEILQ027S_20261020T120000EDT.json").write_text("{}")  # FRED is no longer read
    (directory / "finra_margin_20261020T130000EDT.xlsx").write_bytes(b"not a workbook")
    (directory / "cboe_vix_20261020T130000EDT.csv.gz").write_bytes(b"not gzip")
    (directory / "cboe_vix_20261020T140000EDT.csv.gz.rejected").write_text("withdrawn")
    raw = read_raw(layout, NOW)
    assert (len(raw.workbooks), len(raw.histories)) == (1, 1)
    names = (
        "finra_margin_TOKEN.xlsx, cftc_tff_FIRST_LAST_TOKEN.json, cboe_vix_TOKEN.csv.gz or "
        "cboe_skew_TOKEN.csv.gz"
    )
    reasons = {item.path.name: item.reason for item in raw.invalid}
    assert reasons.pop("cboe_vix_20261020T130000EDT.csv.gz").startswith("not a gzip file: ")
    assert reasons == {
        "notes.txt": f"not a raw file name ({names})",
        "fred_NCBEILQ027S_20261020T120000EDT.json": f"not a raw file name ({names})",
        "finra_margin_20261020T130000EDT.xlsx": "not an Excel workbook (a zip archive)",
    }


def test_the_newest_valid_file_wins(layout):
    save_workbook(layout, workbook_bytes(balances(Month(2026, 8))), edt(2026, 9, 20, 9, 0))
    save_workbook(layout, fetched_at=FETCHED)
    save_history(layout, history_bytes(date(2026, 10, 19)), edt(2026, 10, 20, 9, 0))
    save_history(layout, fetched_at=VIX_FETCHED)
    save_skew(layout, skew_bytes(date(2026, 10, 19)), edt(2026, 10, 20, 18, 0))  # newer, of the SKEW
    raw = read_raw(layout, NOW)
    assert select_workbook(raw.workbooks).workbook.newest == Month(2026, 9)  # type: ignore[union-attr]
    chosen = select_history(raw.histories, VIX)
    assert chosen is not None and chosen.history.newest == date(2026, 10, 20)
    assert chosen.source == "cboe_vix_20261020T170000EDT.csv.gz"
    skew = select_history(raw.histories, SKEW)
    assert skew is not None and skew.source == "cboe_skew_20261020T180000EDT.csv.gz"
    assert select_history([], VIX) is None and select_workbook([]) is None


def test_each_week_is_taken_from_the_newest_answer_holding_it(layout):
    weeks = weeks_back(date(2026, 10, 13), 3)
    save_answer(layout, weekly_rows(weeks, lambda week: 100), fetched_at=edt(2026, 10, 17, 9, 0))
    save_answer(layout, weekly_rows(weeks[1:2], lambda week: 999), fetched_at=FETCHED)
    reports = select_reports(read_raw(layout, NOW).answers)
    assert [week for week in reports] == weeks
    assert [stored.report.asset_mgr_net for stored in reports.values()] == [100, 999, 100]
    assert reports[weeks[1]].source == "cftc_tff_2026-10-05_2026-10-11_20261020T120000EDT.json"


def test_margin_rows_carry_the_workbooks_balances_as_published(layout):
    save_workbook(layout)
    rows = derive_margin(select_workbook(read_raw(layout, NOW).workbooks))
    assert len(rows) == 357 and list(rows) == sorted(rows)
    assert rows[Month(2026, 9)].balance == Balance(Month(2026, 9), 456_000, 3_000, 2_000)
    assert rows[Month(1997, 1)].balance == Balance(Month(1997, 1), 100_000, 3_000, None)
    assert rows[Month(2026, 9)].source == "finra_margin_20261020T120000EDT.xlsx"
    assert derive_margin(None) == {}


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


def indices(layout):
    raw = read_raw(layout, NOW)
    return derive_indices(select_history(raw.histories, VIX), select_history(raw.histories, SKEW))


def test_vix_rows_rank_every_session_from_2000_and_skip_other_days(layout):
    holiday = date(2026, 9, 7)  # Labor Day: a row Cboe calculated in its global trading hours
    save_history(layout, history_bytes(extra={holiday: "99.000000"}))
    rows = indices(layout)
    sessions = list(rows)
    assert (sessions[0], sessions[-1], len(sessions)) == (date(2000, 1, 3), date(2026, 10, 20), 6_740)
    assert holiday not in rows
    newest = rows[date(2026, 10, 20)]
    assert newest.skew is None  # no SKEW file is stored
    assert newest.vix is not None
    # The closes rise every session, the holiday's 99.00 is not among them: all 251 others are below.
    assert (newest.vix.value, newest.vix.percentile) == (Decimal("77.39"), Percentile(Decimal("100.0"), 251))
    assert rows[date(2000, 12, 28)].vix.percentile.reason == (  # type: ignore[union-attr]
        "the 252 sessions to 2000-12-28 begin before 2000-01-03, the first session of the XNYS calendar the "
        "domain uses"
    )
    assert rows[date(2000, 12, 29)].vix.percentile.value == Decimal("100.0")  # type: ignore[union-attr]
    assert derive_indices(None, None) == {}


def test_a_session_cboe_has_no_row_of_has_no_value_and_lowers_the_n_after_it(layout):
    lines = history_bytes().split(b"\n")
    save_history(layout, b"\n".join(line for line in lines if not line.startswith(b"10/14/2026,")))
    save_skew(layout, skew_bytes(missing=[date(2024, 11, 29)]))
    rows = indices(layout)
    gone = rows[date(2026, 10, 14)].vix
    assert gone is not None and (gone.row, gone.value, gone.percentile) == (
        None,
        None,
        Percentile(None, None, "Cboe's file holds no VIX close of 2026-10-14"),
    )
    newest = rows[date(2026, 10, 20)]
    assert newest.vix.percentile == Percentile(Decimal("100.0"), 250)  # type: ignore[union-attr]
    assert rows[date(2026, 10, 13)].vix.percentile == Percentile(Decimal("100.0"), 251)  # type: ignore[union-attr]
    skew = rows[date(2024, 11, 29)].skew
    assert skew is not None and skew.percentile.reason == "Cboe's file holds no SKEW of 2024-11-29"
    # The SKEW of the next session ranks among the 250 others of its 252 that have one.
    assert rows[date(2024, 12, 2)].skew.percentile == Percentile(Decimal("100.0"), 250)  # type: ignore[union-attr]
    assert newest.skew.percentile == Percentile(Decimal("100.0"), 251)  # type: ignore[union-attr]


def test_a_history_reaches_only_the_sessions_up_to_its_newest_day(layout):
    save_history(layout)
    save_skew(layout, skew_bytes(date(2026, 10, 19)), edt(2026, 10, 20, 9, 0))
    rows = indices(layout)
    newest = rows[date(2026, 10, 20)]
    assert newest.vix is not None and newest.skew is None
    assert rows[date(2026, 10, 19)].skew.value == Decimal("187.38")  # type: ignore[union-attr]


def test_the_tables_hold_every_row_in_date_order(layout):
    save_workbook(layout)
    save_answer(layout, weekly_rows(weeks_back(date(2026, 10, 13), 2)))
    save_history(layout)
    save_skew(layout)
    raw = read_raw(layout, NOW)
    margin = margin_text(derive_margin(select_workbook(raw.workbooks)).values()).splitlines()
    assert margin[0] == ",".join(MARGIN_COLUMNS)
    assert margin[1] == "1997-01,100000,3000,,finra_margin_20261020T120000EDT.xlsx"
    assert margin[-1] == "2026-09,456000,3000,2000,finra_margin_20261020T120000EDT.xlsx"
    futures = futures_text(derive_futures(select_reports(raw.answers)).values()).splitlines()
    assert (
        futures[0]
        == ",".join(FUTURES_COLUMNS)
        == (
            "report_date,contract_units,multiplier,open_interest,asset_mgr_long,asset_mgr_short,asset_mgr_spread,"
            "lev_money_long,lev_money_short,lev_money_spread,asset_mgr_net_emini,lev_money_net_short_emini,"
            "fetched_at,source"
        )
    )
    assert futures[2] == (
        "2026-10-13,(S&P 500 INDEX X $50.00),50,2000,1800,1000,50,100,500,20,800,400,"
        "2026-10-20T12:00:00-04:00,cftc_tff_2026-10-05_2026-10-18_20261020T120000EDT.json"
    )
    table = indices_text(indices(layout).values()).splitlines()
    assert table[0] == ",".join(INDICES_COLUMNS) == "date,vix_close,skew,vix_source,skew_source"
    vix_name, skew_name = "cboe_vix_20261020T170000EDT.csv.gz", "cboe_skew_20261020T170000EDT.csv.gz"
    assert table[1] == f"2000-01-03,10.000000,120.000000,{vix_name},{skew_name}"
    assert table[-1] == f"2026-10-20,77.390000,187.390000,{vix_name},{skew_name}"
    assert len(table) == 1 + 6_740


def test_the_indices_table_tells_a_session_without_a_row_from_one_not_reached(layout):
    save_history(layout)
    save_skew(layout, skew_bytes(date(2026, 10, 19), missing=[date(2024, 11, 29)]), edt(2026, 10, 20, 9, 0))
    lines = {line[:10]: line for line in indices_text(indices(layout).values()).splitlines()[1:]}
    skew_name = "cboe_skew_20261020T090000EDT.csv.gz"
    assert lines["2024-11-29"].endswith(f",,cboe_vix_20261020T170000EDT.csv.gz,{skew_name}")
    assert lines["2026-10-20"] == "2026-10-20,77.390000,,cboe_vix_20261020T170000EDT.csv.gz,"


def test_a_table_is_written_only_when_its_bytes_change(layout):
    path = csv_paths(layout)[0]
    assert write_table(path, "a\n") is True
    before = path.stat().st_mtime_ns
    assert write_table(path, "a\n") is False and path.stat().st_mtime_ns == before
    assert write_table(path, "b\n") is True and path.read_text() == "b\n"
