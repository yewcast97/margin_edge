"""The report: payload, HTML and Markdown, the pinned library and determinism."""

import hashlib
import json
import re
from datetime import timedelta

import pytest

from market_state_research.common.sessions import session_window
from market_state_research.stock_iv_regime.script import chart
from market_state_research.stock_iv_regime.script.chart import (
    LIBRARY_PATH,
    LIBRARY_SHA256,
    ChartSpec,
    load_library,
    payload,
    render_html,
    render_markdown,
)
from market_state_research.stock_iv_regime.script.workflow import resolve

from .support import AS_OF, NOW, TICKER, attributes, chain, prices, quotes, save, save_prices, standard

LOOKBACK = 3
SESSIONS = session_window(AS_OF, 254)


@pytest.fixture
def state(layout):
    for index, day in enumerate(SESSIONS):
        if day != session_window(AS_OF, 2)[0]:  # 2026-10-15 is missing
            save(layout, standard(day, f"0.00{index % 10}"))
    # Closes 100 to 104 in a cycle of five: 2026-10-15 closed at 104 and 2026-10-16 at 101.
    save_prices(layout, prices({day: str(100 + (index * 7) % 5) for index, day in enumerate(SESSIONS)}))
    return resolve(layout, TICKER, LOOKBACK, NOW)


PRICES = "prices_2026-10-16_20261017T100000EDT.json.gz"
CONSTANT_CALL = "the return or the 14-DTE call IV change is constant over the 15 sessions to 2026-10-14"


def test_the_library_is_pinned():
    assert hashlib.sha256(LIBRARY_PATH.read_bytes()).hexdigest() == LIBRARY_SHA256
    library = load_library()
    assert library.version == "5.2.1" and "TradingView" in library.notice


def test_payload(state, layout):
    data = payload(state.spec(layout, NOW))
    assert data["missing_sessions"] == ["2026-10-15"]
    assert [row["date"] for row in data["rows"]] == ["2026-10-14", "2026-10-16"]
    first, latest = data["rows"]
    # 2026-10-16 is the 254th session saved: its put IVs are raised by 0.003.
    assert latest["skew_14d_pp"] == "7.55" and latest["atm_iv_14d_pct"] == "31.90"
    assert (latest["call25_iv_14d_pct"], latest["put25_iv_14d_pct"]) == ("27.25", "34.80")
    # 101 / 104 - 1 = -2.884615...%.
    assert (latest["daily_return_pct"], latest["adj_close"]) == ("-2.8846", "101")
    assert latest["price_source"] == data["prices"] == PRICES
    assert (latest["skew_14d_percentile"], latest["skew_window_n"], latest["method"]) == (
        None,
        None,
        "interpolated",
    )
    assert first["skew_window_n"] == 251 and first["skew_14d_percentile"] is not None
    assert first["put25_corr_15s"] is not None and first["call25_corr_15s"] is None
    assert "changes" not in latest
    assert latest["readings"].startswith(
        "interpolated · 2026-10-25 (9d): skew 7.55, ATM 31.90 (c25 155–160, p25 145,"
    )
    assert {
        "date": "2026-10-16",
        "series": "skew_14d_percentile",
        "reason": ("1 of the 252 sessions to 2026-10-16 is not fetched, the first 2026-10-15"),
    } in data["gaps"]
    assert {"date": "2026-10-14", "series": "call25_corr_15s", "reason": CONSTANT_CALL} in data["gaps"]
    assert {
        "date": "2026-10-16",
        "series": "put25_corr_15s",
        "reason": "1 of the 16 sessions to 2026-10-16 is not fetched, the first 2026-10-15",
    } in data["gaps"]


def test_html_is_self_contained_and_deterministic(state, layout):
    spec = state.spec(layout, NOW)
    library = load_library()
    page = render_html(spec, library)
    assert page == render_html(spec, library)
    assert "{{" not in page.replace(library.script, "")
    assert "Partial chart.</strong> 1 of 3 sessions are missing: 2026-10-15." in page
    assert (
        "<strong>Gaps.</strong> no return–call IV correlation on 1 fetched session: 2026-10-14; no skew "
        "percentile, ATM IV percentile, return–call IV correlation or return–put IV correlation on 1 "
        "fetched session: 2026-10-16. The gaps below the data table give each reason." in page
    )
    embedded = re.search(r'<script id="regime-chart-data" type="application/json">(.*?)</script>', page)
    assert embedded is not None
    assert json.loads(embedded.group(1)) == payload(spec)
    assert f'<td class="missing" colspan="{len(chart.TABLE_COLUMNS) - 1}">missing</td>' in page
    assert len(chart.TABLE_COLUMNS) == 14
    head = "".join(f'<th scope="col">{column}</th>' for column in chart.TABLE_COLUMNS)
    assert f"<thead><tr>{head}</tr></thead>" in page
    assert '<th scope="col">Return–Δ put IV correlation (15s)</th>' in page
    assert f"<dt>Prices</dt><dd>{PRICES}</dd>" in page
    # The readout of the latest session: the two percentiles, the two correlations, the close, the return.
    readout = re.findall(r'id="readout-value-(\d)">([^<]*)</span>', page)
    assert readout == [("0", "—"), ("1", "—"), ("2", "—"), ("3", "—"), ("4", "101"), ("5", "-2.8846")]
    # Two charts, always together: the percentiles and the correlations, each over the close.
    assert "14-DTE 25Δ skew and ATM IV · percentiles over 252 sessions (0–100)" in page
    assert "Daily return vs Δ 14-DTE 25Δ call and put IV · correlations over 15 sessions (−1 to 1)" in page
    assert page.count("LWC.createChart(") == 1
    template = page.replace(library.script, "")
    assert "30-DTE" not in template
    assert not any(gone in template for gone in ("Show changes", "readout-change", "(Δ ", "HistogramSeries"))


def test_markdown_twin(state, layout):
    text = render_markdown(state.spec(layout, NOW))
    lines = text.splitlines()
    assert lines[0] == "# TEST · 14-DTE implied volatility · 3 sessions 2026-10-14 → 2026-10-16"
    assert "Coverage: 2 of 3 sessions fetched; 1 missing." in text
    assert f"Prices: {PRICES}." in lines
    row = next(line for line in lines if line.startswith("| 2026-10-16 |"))
    cells = [cell.strip() for cell in row.strip("|").split(" | ")]
    assert cells[1:7] == ["—", "—", "7.55", "31.90", "—", "—"]
    assert cells[7:11] == ["27.25", "34.80", "-2.8846", "101"]
    assert len(cells) == len(chart.TABLE_COLUMNS)
    first = next(line for line in lines if line.startswith("| 2026-10-14 |"))
    assert first.split(" | ")[1].endswith("(n 251)")
    assert "| 2026-10-15 | missing |" in text
    assert "| 2026-10-16 | ATM IV percentile | 1 of the 252 sessions to 2026-10-16 is not fetched" in text
    assert f"| 2026-10-14 | return–call IV correlation | {CONSTANT_CALL} |" in text


def test_a_chart_needs_a_window_row(state, layout):
    spec = state.spec(layout, NOW)
    empty = ChartSpec(spec.ticker, spec.as_of, spec.lookback, spec.window, (), spec.generated_at, spec.csv)
    with pytest.raises(ValueError, match="at least one fetched session"):
        render_html(empty, load_library())


def test_spec_checks(state, layout):
    spec = state.spec(layout, NOW)
    with pytest.raises(ValueError, match="window"):
        ChartSpec(spec.ticker, spec.as_of, spec.lookback, spec.window[1:], spec.rows, NOW, spec.csv)
    with pytest.raises(ValueError, match="unique, ascending"):
        ChartSpec(spec.ticker, spec.as_of, spec.lookback, spec.window, spec.rows[::-1], NOW, spec.csv)


def test_a_tampered_library_is_refused(monkeypatch, tmp_path):
    copy = tmp_path / "lightweight-charts.js"
    copy.write_bytes(LIBRARY_PATH.read_bytes() + b"\n")
    monkeypatch.setattr(chart, "LIBRARY_PATH", copy)
    with pytest.raises(ValueError, match="differs from the pinned"):
        load_library()


def test_gaps_are_listed_per_series(layout):
    save(layout, standard(AS_OF))
    state = resolve(layout, TICKER, 1, NOW)
    text = render_markdown(state.spec(layout, NOW))
    assert "| 2026-10-16 | skew percentile | 251 of the 252 sessions to 2026-10-16 are not fetched" in text


def test_a_skipped_expiry_is_named_with_why(layout):
    e1, stray, e2 = (AS_OF + timedelta(days=days) for days in (9, 12, 19))
    lone = [attributes(TICKER, stray, "call", "190", delta="0.05")]
    save(layout, chain(AS_OF, {e1: quotes(TICKER, e1), stray: lone, e2: quotes(TICKER, e2)}))
    (row,) = payload(resolve(layout, TICKER, 1, NOW).spec(layout, NOW))["rows"]
    assert row["detail"] == "interpolated · 2026-10-25 (9d) → 2026-11-04 (19d) · skipped 2026-10-28 (12d)"
    assert row["readings"].endswith(
        " · skipped at 2026-10-28 (12d) call +0.25: no usable call has delta +0.25 and no two adjacent ones "
        "bracket it; put -0.25: no usable put; call +0.50: no usable call has delta +0.50 and no two "
        "adjacent ones bracket it; put -0.50: no usable put"
    )
    assert row["skew_14d_pp"] == "7.25"
