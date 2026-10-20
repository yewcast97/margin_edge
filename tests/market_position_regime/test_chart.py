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
from market_state_research.market_position_regime.script.workflow import default_window, resolve

from .support import NOW, save_all

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


def test_the_payload_holds_both_charts_points_as_text(spec):
    data = payload(spec)
    assert (data["start"], data["end"], data["generated_at"]) == (
        "2023-10-20",
        "2026-10-20",
        "2026-10-20T18:00:00-04:00",
    )
    assert data["csv"] == ["formatted/market/margin_debt.csv", "formatted/market/index_futures.csv"]
    assert len(data["margin"]) == 36 and len(data["futures"]) == 156
    august, september = data["margin"][-2:]
    assert august == {
        "time": "2026-08-31",
        "label": "2026-08",
        "detail": "market value of 2026-06-30",
        "yoy_pct": "2.7",
        "ratio_pct": "0.46",
        "readout": ["2.7", "0.46", "455,000", "100,000,000.0"],
    }
    assert (september["ratio_pct"], september["readout"][1], september["readout"][3]) == (None, "—", "—")
    newest = data["futures"][-1]
    assert (newest["time"], newest["detail"]) == ("2026-10-13", "week of 2026-10-13")
    assert newest["readout"] == ["0.0", "0.0", "800", "400", "2,000"]  # every week alike: none below
    assert data["gaps"] == [
        {
            "date": "2026-09",
            "series": "ratio_pct",
            "reason": "the stored NCBEILQ027S ends 2026-06-30, before 2026-09-30 (Z.1 due 2026-12-15)",
        }
    ]
    assert data["upcoming"] == [
        "the CFTC reports of the weeks of 2026-10-20 (due 2026-10-23 15:30:00 EDT)",
        "the Z.1 market values of 2026-09-30 (due 2026-12-15)",
    ]


def test_the_page_is_self_contained_and_deterministic(spec):
    library = load_library()
    page = render_html(spec, library)
    assert page == render_html(spec, library)
    template = page.replace(library.script, "")
    assert "{{" not in template
    embedded = re.search(r'<script id="position-chart-data" type="application/json">(.*?)</script>', page)
    assert embedded is not None and json.loads(embedded.group(1)) == payload(spec)
    assert (
        page.count('class="chart"') == 2 and template.count("LWC.createChart(") == 1
    )  # one mount, two charts
    assert "<strong>Gaps.</strong> no ratio to market value on 1 point: 2026-09." in page
    assert "Not fetched." not in page
    assert "<dt>Coverage</dt><dd>36 of 36 months · 156 of 156 weeks</dd>" in page
    assert "<dt>Newest</dt><dd>month 2026-09 · report 2026-10-13</dd>" in page
    margin = re.findall(r'id="margin-readout-value-(\d)">([^<]*)</span>', page)
    assert margin == [("0", "2.7"), ("1", "—"), ("2", "456,000"), ("3", "—")]
    futures = re.findall(r'id="futures-readout-value-(\d)">([^<]*)</span>', page)
    assert futures == [("0", "0.0"), ("1", "0.0"), ("2", "800"), ("3", "400"), ("4", "2,000")]
    assert f'<td class="missing" colspan="{len(chart.MARGIN_COLUMNS) - 1}">not fetched</td>' not in page
    assert "Asset managers&#x27; net (E-mini eq.)" in page


def test_missing_points_are_banners_slots_and_table_rows(layout):
    from market_state_research.market_position_regime.script.store import raw_directory

    save_all(layout)
    for path in raw_directory(layout).glob("finra_*"):
        path.unlink()
    spec = resolve(layout, WINDOW, NOW).spec(layout, NOW)
    assert len(spec.missing_months) == 36 and spec.months_fetched == 0
    page = render_html(spec, load_library())
    assert "<strong>Not fetched.</strong> The sources are due to have published 36 months of FINRA" in page
    span = len(chart.MARGIN_COLUMNS) - 1
    assert f'<th scope="row">2026-09</th><td class="missing" colspan="{span}">not fetched</td>' in page
    assert [point["readout"] for point in payload(spec)["margin"]][-1] == ["—", "—", "—", "—"]


def test_the_markdown_twin_states_the_same_window(spec):
    text = render_markdown(spec)
    lines = text.splitlines()
    assert lines[0] == "# US equity positioning · margin debt and S&P 500 futures · 2023-10-20 → 2026-10-20"
    assert "Coverage: 36 of 36 months · 156 of 156 weeks; newest month 2026-09 · report 2026-10-13." in lines
    assert any(line.startswith("Method: Margin debt is FINRA's debit balances") for line in lines)
    assert "| 2026-08 | 455,000 | 2.7 | 0.46 | 100,000,000.0 | 2026-06-30 | 3,000 | 2,000 |" in text
    row = next(line for line in lines if line.startswith("| 2026-10-13 |"))
    cells = [cell.strip() for cell in row.strip("|").split(" | ")]
    assert cells[:6] == ["2026-10-13", "800", "0.0", "400", "0.0", "1,800"]
    assert len(cells) == len(chart.FUTURES_COLUMNS)
    assert "| 2026-09 | ratio to market value | the stored NCBEILQ027S ends 2026-06-30" in text


def test_a_page_needs_a_fetched_point(spec):
    empty = ChartSpec(spec.start, spec.end, NOW, (), (), (), None, (), spec.csv)
    with pytest.raises(ValueError, match="at least one fetched month or week"):
        render_html(empty, load_library())


def test_the_spec_checks_its_order(spec):
    with pytest.raises(ValueError, match="unique and ascending"):
        ChartSpec(spec.start, spec.end, NOW, spec.months[::-1], spec.weeks, (), None, (), spec.csv)
    with pytest.raises(ValueError, match="start is after its end"):
        ChartSpec(date(2026, 10, 21), spec.end, NOW, (), (), (), None, (), spec.csv)
