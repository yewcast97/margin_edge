"""plan, fetch, record and show over a window, against the fake sources."""

import json
from datetime import date
from pathlib import Path

import pytest

from market_state_research.market_position_regime.script import fred
from market_state_research.market_position_regime.script.periods import Month
from market_state_research.market_position_regime.script.store import raw_directory
from market_state_research.market_position_regime.script.workflow import (
    Window,
    default_window,
    fetch,
    plan,
    record,
    show,
)

from .fake_sources import FakeSources
from .support import (
    KEY,
    NEWEST_WEEK,
    NOW,
    balances,
    edt,
    quarter_values,
    save_all,
    save_answer,
    save_series,
    tff_row,
    weekly_rows,
    weeks_back,
    workbook_bytes,
)

WINDOW = default_window(NOW.date())


def sources(**changes) -> FakeSources:
    """Every source with everything published as of ``NOW``."""
    fake = FakeSources(
        workbook=workbook_bytes(),
        rows=weekly_rows(weeks_back(NEWEST_WEEK, 220)),
        series={
            fred.NONFINANCIAL: quarter_values(value="80000000"),
            fred.FINANCIAL: quarter_values(value="20000000"),
        },
    )
    for name, value in changes.items():
        setattr(fake, name, value)
    return fake


def raw_names(layout) -> list[str]:
    directory = raw_directory(layout)
    return sorted(path.name for path in directory.iterdir()) if directory.is_dir() else []


def test_the_default_window_is_the_three_years_to_today():
    assert default_window(date(2026, 10, 20)) == Window(date(2023, 10, 20), date(2026, 10, 20))
    assert default_window(date(2028, 2, 29)) == Window(date(2025, 2, 28), date(2028, 2, 29))
    window = Window(date(2023, 10, 20), date(2026, 10, 20))
    assert (window.months[0], window.months[-1], len(window.months)) == (Month(2023, 10), Month(2026, 9), 36)
    assert (window.weeks[0], window.weeks[-1], len(window.weeks)) == (
        date(2023, 10, 24),
        date(2026, 10, 20),
        157,
    )
    assert window.span_weeks[0] == date(2022, 11, 1) and len(window.span_weeks) == 208
    assert window.base_months[0] == Month(2022, 10)
    assert (window.quarter_ends[0], window.quarter_ends[-1]) == (date(2023, 9, 30), date(2026, 9, 30))
    with pytest.raises(ValueError):
        Window(date(2026, 10, 21), date(2026, 10, 20))


def test_plan_on_an_empty_directory_lists_everything_due_and_says_fetch(layout):
    planned = plan(layout, WINDOW, NOW)
    assert planned["action"] == "fetch"
    assert planned["window"] == {
        "from": "2023-10-20",
        "to": "2026-10-20",
        "months": 36,
        "weeks": 157,
        "span_start": "2022-10-01",
    }
    sources_ = planned["sources"]
    assert sources_["finra"]["lacking"] == {"count": 48, "first": "2022-10", "last": "2026-09"}
    assert sources_["cftc"]["lacking"] == {"count": 207, "first": "2022-11-01", "last": "2026-10-13"}
    for name in fred.SERIES:
        assert sources_[name]["lacking"] == {"count": 12, "first": "2023-09-30", "last": "2026-06-30"}
        assert sources_[name]["status"] == "lacking" and sources_[name]["path"] is None
    assert planned["not_due"] == [
        "the CFTC reports of the weeks of 2026-10-20 (due 2026-10-23 15:30:00 EDT)",
        "the Z.1 market values of 2026-09-30 (due 2026-12-15)",
    ]
    assert planned["tables"] == {"margin_debt": None, "index_futures": None}
    assert planned["report"] == {"status": "missing", "path": None, "reason": None}
    assert not (layout.root).exists()  # plan writes nothing


def test_fetch_writes_each_source_once_then_requests_nothing(layout):
    fake = sources()
    fetched = fetch(layout, WINDOW, NOW, fake.client())
    assert (fetched["fred_key"], fetched["requests"]) == ("set", 4)
    assert {name: entry["status"] for name, entry in fetched["sources"].items()} == {
        "finra": "new",
        "cftc": "new",
        fred.NONFINANCIAL: "new",
        fred.FINANCIAL: "new",
    }
    assert all(entry["pending"]["count"] == 0 for entry in fetched["sources"].values())
    assert raw_names(layout) == [
        "cftc_tff_2022-10-31_2026-10-18_20261020T180000EDT.json",
        "finra_margin_20261020T180000EDT.xlsx",
        "fred_BOGZ1LM793164105Q_20261020T180000EDT.json",
        "fred_NCBEILQ027S_20261020T180000EDT.json",
    ]
    assert fake.keys == [KEY, KEY]
    assert KEY not in json.dumps(fetched) and all(KEY not in call for call in fake.calls)
    assert plan(layout, WINDOW, NOW)["action"] == "record"
    again = fetch(layout, WINDOW, NOW, fake.client())
    assert again["requests"] == 0
    assert {entry["status"] for entry in again["sources"].values()} == {"reused"}


def test_refresh_requests_again_and_writes_only_what_differs(layout):
    fake = sources()
    fetch(layout, WINDOW, NOW, fake.client())
    later = edt(2026, 10, 20, 19, 0)
    refreshed = fetch(layout, WINDOW, later, fake.client(later), refresh=True)
    assert refreshed["requests"] == 4
    assert {entry["status"] for entry in refreshed["sources"].values()} == {"verified"}
    assert len(raw_names(layout)) == 4
    fake.series[fred.FINANCIAL] = quarter_values(value="20000001")
    newer = fetch(layout, WINDOW, later, fake.client(later), refresh=True)
    assert newer["sources"][fred.FINANCIAL]["status"] == "new"
    assert newer["sources"][fred.NONFINANCIAL]["status"] == "verified"
    assert len(raw_names(layout)) == 5
    assert plan(layout, WINDOW, later, refresh=True)["action"] == "fetch"


def test_a_due_document_the_source_has_not_published_is_pending(layout):
    fake = sources(workbook=workbook_bytes(balances(Month(2026, 8))))
    fetched = fetch(layout, WINDOW, NOW, fake.client())
    assert fetched["sources"]["finra"]["status"] == "new"
    assert fetched["sources"]["finra"]["pending"] == {"count": 1, "first": "2026-09", "last": "2026-09"}
    planned = plan(layout, WINDOW, NOW)
    assert planned["action"] == "fetch"
    assert planned["sources"]["finra"]["lacking"] == {"count": 1, "first": "2026-09", "last": "2026-09"}
    # The same answer again is verified, and still pending.
    again = fetch(layout, WINDOW, NOW, fake.client())
    assert (again["sources"]["finra"]["status"], again["sources"]["finra"]["pending"]["count"]) == (
        "verified",
        1,
    )


def test_cftc_is_asked_only_for_the_lacking_weeks(layout):
    save_all(layout)
    week = date(2026, 10, 20)
    later = edt(2026, 10, 23, 16, 0)  # the week of 2026-10-20 is due from 15:30
    fake = sources(rows=[tff_row(week)])
    fetched = fetch(layout, WINDOW, later, fake.client(later))
    assert fetched["requests"] == 1
    assert (
        fake.calls[0].count(
            "between%20%272026-10-19T00%3A00%3A00.000%27%20and%20%272026-10-25T00%3A00%3A00.000%27"
        )
        == 1
    )
    assert fetched["sources"]["cftc"]["status"] == "new"
    pending = fetch(layout, WINDOW, later, sources(rows=[]).client(later))  # nothing new published
    assert pending["sources"]["cftc"]["status"] == "reused"


def test_an_unpublished_week_is_pending_and_nothing_is_written(layout):
    save_all(layout)
    later = edt(2026, 10, 23, 16, 0)
    fetched = fetch(layout, WINDOW, later, sources(rows=[]).client(later))
    assert fetched["sources"]["cftc"]["status"] == "verified"
    assert fetched["sources"]["cftc"]["pending"] == {"count": 1, "first": "2026-10-20", "last": "2026-10-20"}
    assert len(raw_names(layout)) == 4


def test_a_failing_source_does_not_stop_the_others(layout):
    fake = sources(statuses={1: 503})
    fetched = fetch(layout, WINDOW, NOW, fake.client())
    finra = fetched["sources"]["finra"]
    assert finra["status"] == "failed"
    assert finra["reason"].endswith("HTTP 503 Scripted; FINRA is unavailable: wait and run fetch again")
    assert finra["pending"] == {"count": 48, "first": "2022-10", "last": "2026-09"}
    assert [fetched["sources"][name]["status"] for name in ("cftc", *fred.SERIES)] == ["new", "new", "new"]


def test_an_answer_that_fails_validation_is_reported_and_never_written(layout):
    rows = weekly_rows(weeks_back(NEWEST_WEEK, 220))
    rows[-3] = dict(rows[-3], contract_units="(S&P 500 INDEX X $5.00)")  # the week of 2026-09-29
    fetched = fetch(layout, WINDOW, NOW, sources(rows=rows).client())
    cftc_entry = fetched["sources"]["cftc"]
    assert cftc_entry["status"] == "failed" and "row 205: contract_units must be" in cftc_entry["reason"]
    assert not any(name.startswith("cftc_") for name in raw_names(layout))


def test_a_wrong_fred_key_fails_fred_alone(layout):
    from market_state_research.market_position_regime.script.client import Client

    fake = sources()
    other = "0" * 32
    fetched = fetch(layout, WINDOW, NOW, Client(other, fetch=fake, clock=lambda: NOW))
    for name in fred.SERIES:
        assert fetched["sources"][name]["status"] == "failed"
        assert fetched["sources"][name]["reason"].endswith("FRED refused the request: check FRED_API")
        assert other not in fetched["sources"][name]["reason"]
    assert fetched["sources"]["finra"]["status"] == "new"


def test_record_writes_the_tables_and_a_report_that_plan_then_calls_fresh(layout):
    save_all(layout)
    recorded = record(layout, WINDOW, NOW)
    assert recorded["tables"]["margin_debt"]["rows"] == 357
    assert recorded["tables"]["index_futures"]["rows"] == 220
    assert recorded["tables"]["margin_debt"]["written"] is True
    page = recorded["report"]["path"]
    assert page.endswith("reports/market/market_2023-10-20_2026-10-20_20261020T180000EDT.html")
    assert recorded["report"]["markdown"] == page.removesuffix(".html") + ".md"
    assert recorded["months"][-1]["month"] == "2026-09" and recorded["months"][-1]["ratio_pct"] is None
    assert recorded["weeks"][-1]["report_date"] == "2026-10-13"
    assert recorded["lacking"] == {"months": [], "weeks": [], fred.NONFINANCIAL: [], fred.FINANCIAL: []}
    assert recorded["gaps"] == [
        {
            "date": "2026-09",
            "series": "ratio_pct",
            "reason": "the stored NCBEILQ027S ends 2026-06-30, before 2026-09-30 (Z.1 due 2026-12-15)",
        }
    ]
    later = edt(2026, 10, 20, 19, 0)
    planned = plan(layout, WINDOW, later)
    assert (planned["action"], planned["report"]["status"], planned["report"]["path"]) == (
        "reuse",
        "fresh",
        page,
    )
    again = record(layout, WINDOW, later)
    assert again["tables"]["margin_debt"]["written"] is False
    with pytest.raises(FileExistsError):
        record(layout, WINDOW, later)  # a report of the same second exists


def test_a_new_raw_file_makes_the_report_stale(layout):
    save_all(layout)
    record(layout, WINDOW, NOW)
    later = edt(2026, 10, 20, 19, 0)
    save_series(layout, fred.FINANCIAL, quarter_values(value="30000000"), edt(2026, 10, 20, 18, 30))
    planned = plan(layout, WINDOW, later)
    assert planned["action"] == "record"
    assert planned["report"]["status"] == "stale"


def test_record_names_what_is_lacking_in_the_report(layout):
    save_all(layout)
    save_answer(layout, weekly_rows([date(2026, 10, 6)]), fetched_at=edt(2026, 10, 20, 13, 0))
    raw = raw_directory(layout)
    for path in raw.glob("cftc_tff_2022*"):
        path.unlink()  # only the week of 2026-10-06 is stored now
    recorded = record(layout, WINDOW, NOW)
    assert len(recorded["lacking"]["weeks"]) == 155  # 156 due in the window, 2026-10-06 stored
    markdown = Path(recorded["report"]["markdown"]).read_text(encoding="utf-8")
    assert "Not fetched although due: 155 weeks of CFTC reports (the weeks of 2023-10-24," in markdown
    assert "| 2026-10-13 | not fetched |" in markdown


def test_record_and_show_refuse_while_a_raw_file_is_invalid(layout):
    save_all(layout)
    (raw_directory(layout) / "fred_NCBEILQ027S_20261020T130000EDT.json").write_text("{}")
    for command in (record, show):
        with pytest.raises(ValueError) as caught:
            command(layout, WINDOW, NOW)
        assert "1 raw file(s) failed validation" in str(caught.value)
        assert "rename each with the suffix .rejected" in str(caught.value)
    assert plan(layout, WINDOW, NOW)["invalid_files"][0]["reason"].startswith("the keys must be exactly")


def test_record_refuses_a_window_without_a_fetched_month_or_week(layout):
    with pytest.raises(
        ValueError, match="no month or week of the window 2023-10-20 to 2026-10-20 is fetched"
    ):
        record(layout, WINDOW, NOW)
    assert show(layout, WINDOW, NOW).endswith(
        "No month or week of the window 2023-10-20 to 2026-10-20 is fetched.\n"
    )


def test_show_prints_a_status_line_and_the_twin(layout):
    save_all(layout)
    text = show(layout, WINDOW, NOW)
    status, _, twin = text.partition("\n\n")
    assert status == "Action: record. Tables: none. Report: none (missing)."
    assert twin.startswith(
        "# US equity positioning · margin debt and S&P 500 futures · 2023-10-20 → 2026-10-20"
    )
    recorded = record(layout, WINDOW, NOW)
    assert show(layout, WINDOW, NOW).split("\n\n", 1)[0].startswith("Action: reuse. Tables: ")
    assert (
        Path(recorded["report"]["markdown"]).read_text(encoding="utf-8")
        == show(layout, WINDOW, NOW).split("\n\n", 1)[1]
    )
