"""Reading, selecting and deriving the raw files, and the CSV."""

import csv
import io
import itertools
import statistics
from datetime import date, timedelta
from decimal import Decimal
from fractions import Fraction

from market_state_research.common.sessions import session_window
from market_state_research.stock_iv_regime.script.store import (
    CSV_COLUMNS,
    csv_text,
    derive,
    read_raw,
    select,
    select_prices,
)
from market_state_research.stock_iv_regime.script.surface import HORIZONS, Value, surface

from .support import (
    AS_OF,
    FETCHED,
    NOW,
    TICKER,
    attributes,
    chain,
    prices,
    quotes,
    rising,
    save,
    save_prices,
    standard,
)


def rows_of(layout):
    raw = read_raw(layout, TICKER, NOW)
    return derive(select(raw.captures), select_prices(raw.prices))


def test_invalid_files_are_reported_and_rejected_ones_skipped(layout):
    save(layout, standard(AS_OF))
    directory = layout.raw(TICKER)
    (directory / "notes.txt").write_text("x")
    (directory / "chain_2026-10-15_20261017T100000EDT.json.gz").write_bytes(b"broken")
    (directory / "chain_2026-10-14_20261017T100000EDT.json.gz.rejected").write_bytes(b"broken")
    (directory / "prices_2026-10-16_20261017T100000EDT.json.gz").write_bytes(b"broken")
    raw = read_raw(layout, TICKER, NOW)
    assert [capture.date for capture in raw.captures] == [AS_OF] and raw.prices == ()
    assert sorted((item.path.name, item.reason) for item in raw.invalid) == [
        ("chain_2026-10-15_20261017T100000EDT.json.gz", "not a gzip file: Not a gzipped file (b'br')"),
        ("notes.txt", "not a raw file name (chain_DATE_TOKEN.json.gz or prices_DATE_TOKEN.json.gz)"),
        ("prices_2026-10-16_20261017T100000EDT.json.gz", "not a gzip file: Not a gzipped file (b'br')"),
    ]


def test_the_newest_chain_of_a_session_wins(layout):
    older = save(layout, standard(AS_OF, "0.01"))
    newer = save(layout, standard(AS_OF, "0.02", fetched_at=FETCHED + timedelta(hours=1)))
    same_second = save(layout, standard(AS_OF, "0.03", fetched_at=FETCHED + timedelta(hours=1)))
    assert same_second == newer.replace(".json.gz", "_1.json.gz")
    chosen = select(read_raw(layout, TICKER, NOW).captures)
    assert chosen[AS_OF].source == same_second
    assert older != chosen[AS_OF].source


def test_derive_gives_values_and_percentiles_over_252_sessions(layout):
    sessions = session_window(AS_OF, 253)
    for index, day in enumerate(sessions):
        # The skew rises by 0.01 pp a session and the term structure by 0.011 pp (the 30-DTE 50Δ
        # levels by 100 x 0.00021 x 11/21): the latest is above every other.
        far = str(Decimal("0.021") + Decimal(index) * Decimal("0.00021"))
        save(layout, standard(day, str(Decimal(index) / 10000), far=far))
    raw = read_raw(layout, TICKER, NOW)
    assert raw.invalid == ()
    rows = derive(select(raw.captures))
    latest = rows[AS_OF]
    assert latest.skew.value == Decimal("7.25") + Decimal("2.52")
    assert (latest.atm.value, latest.far_atm.value) == (Decimal("33.01"), Decimal("36.88"))
    assert latest.term == Value(Decimal("3.87"))  # 1.10 + 252 x 0.011
    assert (latest.skew_percentile.value, latest.skew_percentile.n) == (Decimal("100.0"), 251)
    assert (latest.atm_percentile.value, latest.atm_percentile.n) == (Decimal("100.0"), 251)
    assert (latest.term_percentile.value, latest.term_percentile.n) == (Decimal("100.0"), 251)
    first = rows[sessions[0]]
    assert first.skew_percentile.value is None
    start = session_window(sessions[0], 252)[0]
    assert first.skew_percentile.reason == (
        f"251 of the 252 sessions to {sessions[0]} are not fetched, the first {start}"
    )
    second = rows[sessions[1]]
    start = session_window(sessions[1], 252)[0]
    assert second.skew_percentile.reason == (
        f"250 of the 252 sessions to {sessions[1]} are not fetched, the first {start}"
    )


def test_a_capture_keeps_the_rows_its_levels_read_only(layout):
    expiries = [AS_OF + timedelta(days=days) for days in (9, 19, 40, 55)]
    save(layout, chain(AS_OF, {expiry: quotes(TICKER, expiry) for expiry in expiries}))  # 7 rows each
    (capture,) = read_raw(layout, TICKER, NOW).captures
    assert len(capture.chain.listed) == 4
    # 9 and 19 days out at 14 days, 19 and 40 at 30: the expiry 55 days out is read at neither.
    assert {row.expiry for row in capture.chain.rows} == set(expiries[:3])


def test_a_capture_keeps_a_skipped_expiry_and_derives_as_the_whole_chain(layout):
    e1, stray, e2, far, beyond = (AS_OF + timedelta(days=days) for days in (9, 12, 19, 40, 50))
    stray_rows = [attributes(TICKER, stray, "call", "190", delta="0.05")]
    by_expiry = {expiry: quotes(TICKER, expiry) for expiry in (e1, e2, far, beyond)}
    whole = chain(AS_OF, {**by_expiry, stray: stray_rows})
    save(layout, whole)
    (capture,) = read_raw(layout, TICKER, NOW).captures
    assert {row.expiry for row in capture.chain.rows} == {e1, stray, e2, far}
    for horizon in HORIZONS:
        assert surface(AS_OF, capture.chain.listed, capture.chain.rows, horizon) == surface(
            AS_OF, whole.listed, whole.rows, horizon
        )
    (row,) = rows_of(layout).values()
    cells = csv_text([row]).splitlines()[1].split(",")
    assert cells[CSV_COLUMNS.index("skipped_14d")] == stray.isoformat()
    assert cells[CSV_COLUMNS.index("skipped_30d")] == ""


def test_csv_of_one_session(layout):
    save(layout, standard(AS_OF))
    text = csv_text(rows_of(layout).values())
    header, line = text.splitlines()
    assert header == (
        "date,close,adj_close,previous_adj_close,call25_iv_14d_pct,put25_iv_14d_pct,call50_iv_14d_pct,"
        "put50_iv_14d_pct,call50_iv_30d_pct,put50_iv_30d_pct,expiry_14d_1,expiry_14d_2,skipped_14d,"
        "expiry_30d_1,expiry_30d_2,skipped_30d,fetched_at,source,price_source"
    )
    assert header == ",".join(CSV_COLUMNS)
    e1, e2, far = (AS_OF + timedelta(days=days) for days in (9, 19, 40))
    # Levels only: the 30-DTE 50Δ levels lie 11/21 of the way from 19 days out to 40.
    assert line == (
        f"2026-10-16,,,,27.25,34.50,29.00,34.50,30.10,35.60,{e1},{e2},,{e2},{far},,2026-10-17T10:00:00-04:00,"
        "chain_2026-10-16_20261017T100000EDT.json.gz,"
    )


def test_csv_of_a_session_with_its_bars(layout):
    thursday = date(2026, 10, 15)
    save(layout, standard(thursday))
    save(layout, standard(AS_OF, "0.01"))
    name = save_prices(layout, prices({date(2026, 10, 14): "99", thursday: "100", AS_OF: "101"}))
    rows = rows_of(layout)
    latest = rows[AS_OF]
    assert latest.daily_return == Value(Decimal("1.0000"))  # 101 / 100 - 1
    assert rows[thursday].daily_return == Value(Decimal("1.0101"))  # 100 / 99 - 1 = 1.010101...%
    assert (latest.skew, latest.atm) == (Value(Decimal("8.25")), Value(Decimal("32.25")))
    assert (latest.far_atm, latest.term) == (Value(Decimal("33.35")), Value(Decimal("1.10")))
    line = csv_text([latest]).splitlines()[1]
    assert line.startswith("2026-10-16,101,101,100,27.25,35.50,29.00,35.50,30.10,36.60,")
    assert line.endswith(f",2026-10-17T10:00:00-04:00,chain_2026-10-16_20261017T100000EDT.json.gz,{name}")
    assert latest.call25_correlation.reason == (
        "14 of the 16 sessions to 2026-10-16 are not fetched, the first 2026-09-25"
    )


def test_the_newest_prices_file_is_the_tickers(layout):
    days = session_window(AS_OF, 3)
    older = save_prices(layout, prices(rising(days, "50")))
    newer = save_prices(layout, prices(rising(days), fetched_at=FETCHED + timedelta(minutes=1)))
    raw = read_raw(layout, TICKER, NOW)
    assert sorted(item.source for item in raw.prices) == sorted([older, newer])
    chosen = select_prices(raw.prices)
    assert chosen is not None and chosen.source == newer
    assert chosen.prices.bar(AS_OF).close == Decimal("102")
    assert select_prices(()) is None


def test_csv_of_a_session_without_brackets(layout):
    day = date(2026, 10, 15)
    expiry = day + timedelta(days=35)
    save(layout, chain(day, {expiry: quotes(TICKER, expiry)}))
    (row,) = rows_of(layout).values()
    assert (row.near.method, row.far.method) == ("none", "none")
    assert row.far.reason == "no expiry is listed 1 to 30 days out (2026-10-16 to 2026-11-14)"
    line = csv_text([row]).splitlines()[1]
    # The closes, every level, the bracket expiries and the skipped ones are blank.
    assert line.startswith("2026-10-15" + "," * 16 + "2026-10-17T10:00:00-04:00,")


def test_the_correlations_rest_on_the_archived_values(layout):
    days = session_window(AS_OF, 17)
    for index, day in enumerate(days):
        save(layout, standard(day, str(Decimal(index % 3) / 100)))  # put IVs 34.50, 35.50, 36.50, ...
    save_prices(layout, prices({day: str(100 + (index * 7) % 5) for index, day in enumerate(days)}))
    rows = rows_of(layout)
    latest = rows[AS_OF]
    assert latest.call25_correlation == Value(
        None, "the return or the 14-DTE call IV change is constant over the 15 sessions to 2026-10-16"
    )
    # Recomputed from the CSV's levels alone, as anyone can: the returns from the adjusted closes
    # (rounded half-even to four places) and the changes of the put IVs.
    table = list(csv.DictReader(io.StringIO(csv_text(rows.values()))))
    returns = [
        float(round((Fraction(line["adj_close"]) / Fraction(line["previous_adj_close"]) - 1) * 100, 4))
        for line in table[-15:]
    ]
    assert [Decimal(str(value)) for value in returns] == [rows[day].daily_return.value for day in days[-15:]]
    puts = [float(line["put25_iv_14d_pct"]) for line in table[-16:]]
    changes = [after - before for before, after in itertools.pairwise(puts)]
    expected = round(statistics.correlation(returns, changes), 2)
    assert latest.put25_correlation == Value(Decimal(str(expected)))
    assert "put25_corr_15s" not in table[-1]
    assert rows[days[15]].put25_correlation.value is not None  # its 16 sessions are the first fetched
    assert rows[days[14]].put25_correlation.reason == (
        "1 of the 16 sessions to 2026-10-14 is not fetched, the first 2026-09-23"
    )
