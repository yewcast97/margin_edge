"""The report: payload, page and Markdown twin, the domain's template and determinism.

The vendored library's pin and the page helpers are tested with ``common.chart``.
"""

import json
import re
from datetime import date
from pathlib import Path

import pytest

from market_state_research.market_position_regime.script import chart
from market_state_research.market_position_regime.script.chart import (
    TEMPLATE_PATH,
    ChartSpec,
    load_library,
    payload,
    render_html,
    render_markdown,
)
from market_state_research.market_position_regime.script.store import raw_directory
from market_state_research.market_position_regime.script.workflow import default_window, resolve

from .support import NOW, history_bytes, save_all, save_history

WINDOW = default_window(NOW.date())


@pytest.fixture
def spec(layout) -> ChartSpec:
    save_all(layout)
    return resolve(layout, WINDOW, NOW).spec(layout, NOW)


def test_the_library_comes_with_this_domains_template():
    library = load_library()
    assert library.version == "5.2.1" and "TradingView" in library.notice
    assert library.template == TEMPLATE_PATH.read_text(encoding="utf-8")
    assert Path(chart.__file__).resolve().parent / "templates" / "chart.html" == TEMPLATE_PATH


def test_the_payload_holds_the_three_charts_points_as_text(spec):
    data = payload(spec)
    assert (data["start"], data["end"], data["generated_at"]) == (
        "2023-10-20",
        "2026-10-20",
        "2026-10-20T18:00:00-04:00",
    )
    assert data["csv"] == [
        "formatted/market/margin_debt.csv",
        "formatted/market/index_futures.csv",
        "formatted/market/vix.csv",
    ]
    assert (len(data["margin"]), len(data["futures"]), len(data["vix"])) == (36, 156, 752)
    assert data["margin"][-1] == {
        "time": "2026-09-30",
        "label": "2026-09",
        "detail": "",
        "debit_balances_musd": "456000",
        "readout": ["456,000"],
    }
    newest = data["futures"][-1]
    assert (newest["time"], newest["detail"]) == ("2026-10-13", "week of 2026-10-13")
    assert newest["readout"] == ["0.0", "0.0", "800", "400", "2,000"]  # every week alike: none below
    assert data["vix"][0]["time"] == "2023-10-20"
    assert data["vix"][-1] == {
        "time": "2026-10-20",
        "label": "2026-10-20",
        "detail": "",
        "close_252s_percentile": "100.0",
        "readout": ["100.0", "77.39"],  # the closes rise every session: all 251 others are below
    }
    assert data["gaps"] == []
    assert data["upcoming"] == ["the CFTC reports of the weeks of 2026-10-20 (due 2026-10-23 15:30:00 EDT)"]


def test_the_page_is_self_contained_and_deterministic(spec):
    library = load_library()
    page = render_html(spec, library)
    assert page == render_html(spec, library)
    template = page.replace(library.script, "")
    assert "{{" not in template
    embedded = re.search(r'<script id="position-chart-data" type="application/json">(.*?)</script>', page)
    assert embedded is not None and json.loads(embedded.group(1)) == payload(spec)
    assert (
        page.count('class="chart"') == 3 and template.count("LWC.createChart(") == 1
    )  # one mount, three charts
    assert "Gaps." not in page and "Not fetched." not in page
    assert "<dt>Coverage</dt><dd>36 of 36 months · 156 of 156 weeks · 752 of 752 sessions</dd>" in page
    assert "<dt>Newest</dt><dd>month 2026-09 · report 2026-10-13 · session 2026-10-20</dd>" in page
    assert (
        "<dt>Raw files</dt><dd>finra_margin_20261020T120000EDT.xlsx, cboe_vix_20261020T170000EDT.csv.gz</dd>"
        in page
    )
    assert re.findall(r'id="margin-readout-value-(\d)">([^<]*)</span>', page) == [("0", "456,000")]
    futures = re.findall(r'id="futures-readout-value-(\d)">([^<]*)</span>', page)
    assert futures == [("0", "0.0"), ("1", "0.0"), ("2", "800"), ("3", "400"), ("4", "2,000")]
    assert re.findall(r'id="vix-readout-value-(\d)">([^<]*)</span>', page) == [("0", "100.0"), ("1", "77.39")]
    assert "Asset managers&#x27; net (E-mini eq.)" in page
    assert '<th scope="row">2026-10-20</th><td>77.39</td><td>100.0</td>' in page


def test_missing_points_are_banners_slots_and_table_rows(layout):
    save_all(layout)
    for path in raw_directory(layout).glob("finra_*"):
        path.unlink()
    spec = resolve(layout, WINDOW, NOW).spec(layout, NOW)
    assert len(spec.missing_months) == 36 and spec.months_fetched == 0
    page = render_html(spec, load_library())
    assert "<strong>Not fetched.</strong> The sources are due to have published 36 months of FINRA" in page
    span = len(chart.MARGIN_COLUMNS) - 1
    assert f'<th scope="row">2026-09</th><td class="missing" colspan="{span}">not fetched</td>' in page
    assert [point["readout"] for point in payload(spec)["margin"]][-1] == ["—"]
    for path in raw_directory(layout).glob("cboe_*"):
        path.unlink()
    spec = resolve(layout, WINDOW, NOW).spec(layout, NOW)
    assert len(spec.missing_sessions) == 752 and spec.sessions_fetched == 0
    assert "752 sessions of Cboe&#x27;s VIX (2023-10-20, 2023-10-23," in render_html(spec, load_library())
    assert payload(spec)["vix"][-1]["readout"] == ["—", "—"]


def test_a_session_without_a_close_is_a_gap_of_every_percentile_resting_on_it(layout):
    save_all(layout)
    for path in raw_directory(layout).glob("cboe_*"):
        path.unlink()
    lines = history_bytes().split(b"\n")
    save_history(layout, b"\n".join(line for line in lines if not line.startswith(b"10/14/2026,")))
    spec = resolve(layout, WINDOW, NOW).spec(layout, NOW)
    assert [(gap.date, gap.series) for gap in spec.gaps] == [
        (day, "close_252s_percentile")
        for day in ("2026-10-14", "2026-10-15", "2026-10-16", "2026-10-19", "2026-10-20")
    ]
    assert spec.gaps[0].reason == "Cboe's file holds no close of 2026-10-14"
    page = render_html(spec, load_library())
    assert (
        "<strong>Gaps.</strong> no VIX close percentile on 5 points: 2026-10-14, 2026-10-15, 2026-10-16, "
        "2026-10-19, 2026-10-20." in page
    )
    assert '<th scope="row">2026-10-14</th><td>—</td><td>—</td>' in page


def test_the_markdown_twin_states_the_same_window(spec):
    text = render_markdown(spec)
    lines = text.splitlines()
    assert lines[0] == (
        "# US equity positioning · margin debt, S&P 500 futures and the VIX · 2023-10-20 → 2026-10-20"
    )
    assert (
        "Coverage: 36 of 36 months · 156 of 156 weeks · 752 of 752 sessions; newest month 2026-09 · "
        "report 2026-10-13 · session 2026-10-20." in lines
    )
    assert any(line.startswith("Method: Margin debt is FINRA's debit balances") for line in lines)
    assert "| 2026-08 | 455,000 | 3,000 | 2,000 | finra_margin_20261020T120000EDT.xlsx |" in lines
    row = next(line for line in lines if line.startswith("| 2026-10-13 |"))
    cells = [cell.strip() for cell in row.strip("|").split(" | ")]
    assert cells[:6] == ["2026-10-13", "800", "0.0", "400", "0.0", "1,800"]
    assert len(cells) == len(chart.FUTURES_COLUMNS)
    assert "## VIX, by XNYS session" in lines
    assert "| 2026-10-20 | 77.39 | 100.0 | cboe_vix_20261020T170000EDT.csv.gz |" in lines
    assert lines[-1] == "None: every point of the window has every value."


def test_a_page_needs_a_fetched_point(spec):
    empty = ChartSpec(spec.start, spec.end, NOW, (), (), (), (), None, None, spec.csv)
    with pytest.raises(ValueError, match="at least one fetched month, week or session"):
        render_html(empty, load_library())


def test_the_spec_checks_its_order(spec):
    with pytest.raises(ValueError, match="unique and ascending"):
        ChartSpec(
            spec.start, spec.end, NOW, spec.months, spec.weeks, spec.sessions[::-1], (), None, None, spec.csv
        )
    with pytest.raises(ValueError, match="start is after its end"):
        ChartSpec(date(2026, 10, 21), spec.end, NOW, (), (), (), (), None, None, spec.csv)
