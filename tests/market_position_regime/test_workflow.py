"""plan, fetch, record and show over a window, against the fake sources."""

from datetime import date
from pathlib import Path

import pytest

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
    NEWEST_WEEK,
    NOW,
    balances,
    edt,
    history_bytes,
    save_all,
    save_answer,
    save_history,
    save_skew,
    skew_bytes,
    tff_row,
    vix_close,
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
        history=history_bytes(date(2026, 10, 20)),
        skew=skew_bytes(date(2026, 10, 20)),
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
    assert (window.sessions[0], window.sessions[-1], len(window.sessions)) == (
        date(2023, 10, 20),
        date(2026, 10, 20),
        752,
    )
    assert window.span_sessions[0] == date(2022, 10, 20) and len(window.span_sessions) == 752 + 251
    early = Window(date(2000, 3, 1), date(2000, 3, 31))  # the calendar holds 40 sessions before it
    assert early.span_sessions[0] == date(2000, 1, 3) and len(early.span_sessions) == 40 + len(early.sessions)
    assert Window(date(1999, 1, 1), date(1999, 12, 31)).span_sessions == ()
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
        "sessions": 752,
        "span_start": "2022-10-20",
    }
    found = planned["sources"]
    assert found["finra"]["lacking"] == {"count": 36, "first": "2023-10", "last": "2026-09"}
    assert found["cftc"]["lacking"] == {"count": 207, "first": "2022-11-01", "last": "2026-10-13"}
    for name in ("cboe_vix", "cboe_skew"):
        assert found[name]["lacking"] == {"count": 1003, "first": "2022-10-20", "last": "2026-10-20"}
        assert found[name]["status"] == "lacking" and found[name]["path"] is None
    assert list(found) == ["finra", "cftc", "cboe_vix", "cboe_skew"]
    assert planned["not_due"] == ["the CFTC reports of the weeks of 2026-10-20 (due 2026-10-23 15:30:00 EDT)"]
    assert planned["tables"] == {"margin_debt": None, "index_futures": None, "vix_skew": None}
    assert planned["report"] == {"status": "missing", "path": None, "reason": None}
    assert not (layout.root).exists()  # plan writes nothing


def test_the_sessions_vix_and_skew_are_not_due_before_a_quarter_past_four(layout):
    planned = plan(layout, WINDOW, edt(2026, 10, 20, 16, 14))
    assert planned["sources"]["cboe_vix"]["lacking"]["last"] == "2026-10-19"
    assert planned["sources"]["cboe_skew"]["lacking"]["last"] == "2026-10-19"
    assert "Cboe's VIX and SKEW of 2026-10-20 (due 2026-10-20 16:15:00 EDT)" in planned["not_due"]


def test_fetch_writes_each_source_once_then_requests_nothing(layout):
    fake = sources()
    fetched = fetch(layout, WINDOW, NOW, fake.client())
    assert fetched["requests"] == 4 and "fred_key" not in fetched
    assert {name: entry["status"] for name, entry in fetched["sources"].items()} == {
        "finra": "new",
        "cftc": "new",
        "cboe_vix": "new",
        "cboe_skew": "new",
    }
    assert all(entry["pending"]["count"] == 0 for entry in fetched["sources"].values())
    assert raw_names(layout) == [
        "cboe_skew_20261020T180000EDT.csv.gz",
        "cboe_vix_20261020T180000EDT.csv.gz",
        "cftc_tff_2022-10-31_2026-10-18_20261020T180000EDT.json",
        "finra_margin_20261020T180000EDT.xlsx",
    ]
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
    revised = history_bytes(date(2026, 10, 20), close=lambda index: vix_close(index + (index == 6_000)))
    newer = fetch(layout, WINDOW, later, sources(history=revised).client(later), refresh=True)
    assert newer["sources"]["cboe_vix"]["status"] == "new"
    assert newer["sources"]["cboe_vix"]["path"].endswith("cboe_vix_20261020T190000EDT.csv.gz")
    assert (newer["sources"]["finra"]["status"], newer["sources"]["cboe_skew"]["status"]) == (
        "verified",
        "verified",
    )
    assert len(raw_names(layout)) == 5
    assert plan(layout, WINDOW, later, refresh=True)["action"] == "fetch"


def test_a_due_document_the_source_has_not_published_is_pending(layout):
    fake = sources(
        workbook=workbook_bytes(balances(Month(2026, 8))),
        history=history_bytes(date(2026, 10, 19)),
        skew=skew_bytes(date(2026, 10, 19)),
    )
    fetched = fetch(layout, WINDOW, NOW, fake.client())
    assert fetched["sources"]["finra"]["status"] == "new"
    assert fetched["sources"]["finra"]["pending"] == {"count": 1, "first": "2026-09", "last": "2026-09"}
    for name in ("cboe_vix", "cboe_skew"):
        assert fetched["sources"][name]["status"] == "new"
        assert fetched["sources"][name]["pending"] == {
            "count": 1,
            "first": "2026-10-20",
            "last": "2026-10-20",
        }
    planned = plan(layout, WINDOW, NOW)
    assert planned["action"] == "fetch"
    assert planned["sources"]["finra"]["lacking"] == {"count": 1, "first": "2026-09", "last": "2026-09"}
    assert planned["sources"]["cboe_skew"]["lacking"] == {
        "count": 1,
        "first": "2026-10-20",
        "last": "2026-10-20",
    }
    # The same answers again are verified, and still pending.
    again = fetch(layout, WINDOW, NOW, fake.client())
    assert [
        (again["sources"][name]["status"], again["sources"][name]["pending"]["count"])
        for name in ("finra", "cboe_vix", "cboe_skew")
    ] == [
        ("verified", 1),
        ("verified", 1),
        ("verified", 1),
    ]
    assert len(raw_names(layout)) == 4


def test_cftc_is_asked_only_for_the_lacking_weeks(layout):
    save_all(layout)
    week = date(2026, 10, 20)
    later = edt(2026, 10, 23, 16, 0)  # the week of 2026-10-20 is due from 15:30
    fake = sources(rows=[tff_row(week)])
    fetched = fetch(layout, WINDOW, later, fake.client(later))
    assert fetched["requests"] == 1  # the window ends 2026-10-20: neither FINRA nor Cboe lacks anything
    assert (
        fake.calls[0].count(
            "between%20%272026-10-19T00%3A00%3A00.000%27%20and%20%272026-10-25T00%3A00%3A00.000%27"
        )
        == 1
    )
    assert [fetched["sources"][name]["status"] for name in ("finra", "cftc", "cboe_vix", "cboe_skew")] == [
        "reused",
        "new",
        "reused",
        "reused",
    ]
    nothing_new = fetch(layout, WINDOW, later, sources(rows=[]).client(later))
    assert nothing_new["sources"]["cftc"]["status"] == "reused"
    assert nothing_new["requests"] == 0


def test_an_unpublished_week_is_pending_and_nothing_is_written(layout):
    save_all(layout)
    later = edt(2026, 10, 23, 16, 0)
    stored = len(raw_names(layout))
    fetched = fetch(layout, WINDOW, later, sources(rows=[]).client(later))
    assert fetched["sources"]["cftc"]["status"] == "verified"
    assert fetched["sources"]["cftc"]["pending"] == {"count": 1, "first": "2026-10-20", "last": "2026-10-20"}
    assert len(raw_names(layout)) == stored


def test_a_session_after_the_newest_is_lacking_until_cboe_publishes_it(layout):
    save_all(layout)
    window = Window(date(2026, 1, 2), date(2026, 10, 23))
    later = edt(2026, 10, 23, 16, 0)  # the VIX of 2026-10-21 and 2026-10-22 is due, that of 10-23 is not
    for name in ("cboe_vix", "cboe_skew"):
        assert plan(layout, window, later)["sources"][name]["lacking"] == {
            "count": 2,
            "first": "2026-10-21",
            "last": "2026-10-22",
        }
    fetched = fetch(layout, window, later, sources(rows=[]).client(later))  # Cboe has not published them
    for name in ("cboe_vix", "cboe_skew"):
        assert (fetched["sources"][name]["status"], fetched["sources"][name]["pending"]["count"]) == (
            "verified",
            2,
        )
    assert (
        "Cboe's VIX and SKEW of 2026-10-23 (due 2026-10-23 16:15:00 EDT)"
        in plan(layout, window, later)["not_due"]
    )
    # Cboe replaces the two files separately in the evening: the SKEW's came first on 2026-10-22.
    published = sources(rows=[], skew=skew_bytes(date(2026, 10, 22)))
    fetched = fetch(layout, window, later, published.client(later))
    assert (fetched["sources"]["cboe_vix"]["status"], fetched["sources"]["cboe_skew"]["status"]) == (
        "verified",
        "new",
    )
    planned = plan(layout, window, later)
    assert (
        planned["sources"]["cboe_vix"]["lacking"]["count"],
        planned["sources"]["cboe_skew"]["lacking"]["count"],
    ) == (
        2,
        0,
    )
    published = sources(
        rows=[], history=history_bytes(date(2026, 10, 22)), skew=skew_bytes(date(2026, 10, 22))
    )
    fetched = fetch(layout, window, later, published.client(later))
    assert (fetched["sources"]["cboe_vix"]["status"], fetched["sources"]["cboe_skew"]["status"]) == (
        "new",
        "reused",
    )
    assert plan(layout, window, later)["sources"]["cboe_vix"]["lacking"]["count"] == 0


def test_a_failing_source_does_not_stop_the_others(layout):
    fake = sources(statuses={1: 503})
    fetched = fetch(layout, WINDOW, NOW, fake.client())
    finra = fetched["sources"]["finra"]
    assert finra["status"] == "failed"
    assert finra["reason"].endswith("HTTP 503 Scripted; FINRA is unavailable: wait and run fetch again")
    assert finra["pending"] == {"count": 36, "first": "2023-10", "last": "2026-09"}
    assert [fetched["sources"][name]["status"] for name in ("cftc", "cboe_vix", "cboe_skew")] == ["new"] * 3


def test_an_answer_that_fails_validation_is_reported_and_never_written(layout):
    rows = weekly_rows(weeks_back(NEWEST_WEEK, 220))
    rows[-3] = dict(rows[-3], contract_units="(S&P 500 INDEX X $5.00)")  # the week of 2026-09-29
    changed = history_bytes().replace(b"DATE,OPEN,HIGH,LOW,CLOSE", b"Date,Open,High,Low,Close")
    fetched = fetch(layout, WINDOW, NOW, sources(rows=rows, history=changed).client())
    cftc_entry, cboe_entry = fetched["sources"]["cftc"], fetched["sources"]["cboe_vix"]
    assert cftc_entry["status"] == "failed" and "row 205: contract_units must be" in cftc_entry["reason"]
    assert cboe_entry["status"] == "failed"
    assert cboe_entry["reason"].endswith(
        "VIX_History.csv: the first line must be exactly DATE,OPEN,HIGH,LOW,CLOSE"
    )
    assert cboe_entry["pending"]["count"] == 1003
    assert raw_names(layout) == [
        "cboe_skew_20261020T180000EDT.csv.gz",
        "finra_margin_20261020T180000EDT.xlsx",
    ]


def test_record_writes_the_tables_and_a_report_that_plan_then_calls_fresh(layout):
    save_all(layout)
    recorded = record(layout, WINDOW, NOW)
    assert {name: table["rows"] for name, table in recorded["tables"].items()} == {
        "margin_debt": 357,
        "index_futures": 220,
        "vix_skew": 6_740,
    }
    assert all(table["written"] is True for table in recorded["tables"].values())
    page = recorded["report"]["path"]
    assert page.endswith("reports/market/market_2023-10-20_2026-10-20_20261020T180000EDT.html")
    assert recorded["report"]["markdown"] == page.removesuffix(".html") + ".md"
    assert recorded["months"][-1] == {"month": "2026-09", "debit_balances_musd": 456_000}
    assert recorded["weeks"][-1]["report_date"] == "2026-10-13"
    assert recorded["indices"] == {
        "sessions": 752,
        "newest": {
            "date": "2026-10-20",
            "vix_close": "77.390000",
            "vix_close_252s_percentile": "100.0",
            "skew": "187.390000",
            "skew_252s_percentile": "100.0",
        },
    }
    assert recorded["lacking"] == {"months": [], "weeks": [], "vix_sessions": [], "skew_sessions": []}
    assert recorded["gaps"] == []
    later = edt(2026, 10, 20, 19, 0)
    planned = plan(layout, WINDOW, later)
    assert (planned["action"], planned["report"]["status"], planned["report"]["path"]) == (
        "reuse",
        "fresh",
        page,
    )
    again = record(layout, WINDOW, later)
    assert {table["written"] for table in again["tables"].values()} == {False}
    with pytest.raises(FileExistsError):
        record(layout, WINDOW, later)  # a report of the same second exists


def test_a_new_raw_file_makes_the_report_stale(layout):
    save_all(layout)
    record(layout, WINDOW, NOW)
    later = edt(2026, 10, 20, 19, 0)
    revised = history_bytes(date(2026, 10, 20), close=lambda index: vix_close(index + (index == 6_738)))
    save_history(layout, revised, edt(2026, 10, 20, 18, 30))
    planned = plan(layout, WINDOW, later)
    assert planned["action"] == "record"
    assert planned["report"]["status"] == "stale"


def test_record_names_a_session_one_cboe_file_lacks(layout):
    save_all(layout)
    for path in raw_directory(layout).glob("cboe_skew_*"):
        path.unlink()
    save_skew(layout, skew_bytes(date(2026, 10, 19)), edt(2026, 10, 20, 9, 0))
    assert plan(layout, WINDOW, NOW)["action"] == "fetch"
    recorded = record(layout, WINDOW, NOW)
    assert (recorded["lacking"]["vix_sessions"], recorded["lacking"]["skew_sessions"]) == ([], ["2026-10-20"])
    newest = recorded["indices"]["newest"]
    assert (newest["vix_close"], newest["skew"], newest["skew_252s_percentile"]) == ("77.390000", None, None)
    markdown = Path(recorded["report"]["markdown"]).read_text(encoding="utf-8")
    assert "Not fetched although due: 1 session of Cboe's SKEW (2026-10-20)." in markdown


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
    (raw_directory(layout) / "cboe_vix_20261020T130000EDT.csv.gz").write_text("{}")
    for command in (record, show):
        with pytest.raises(ValueError) as caught:
            command(layout, WINDOW, NOW)
        assert "1 raw file(s) failed validation" in str(caught.value)
        assert "rename each with the suffix .rejected" in str(caught.value)
    assert plan(layout, WINDOW, NOW)["invalid_files"][0]["reason"].startswith("not a gzip file")


def test_record_refuses_a_window_without_a_fetched_month_week_or_session(layout):
    with pytest.raises(
        ValueError, match="no month, week or session of the window 2023-10-20 to 2026-10-20 is fetched"
    ):
        record(layout, WINDOW, NOW)
    assert show(layout, WINDOW, NOW).endswith(
        "No month, week or session of the window 2023-10-20 to 2026-10-20 is fetched.\n"
    )


def test_show_prints_a_status_line_and_the_twin(layout):
    save_all(layout)
    text = show(layout, WINDOW, NOW)
    status, _, twin = text.partition("\n\n")
    assert status == "Action: record. Tables: none. Report: none (missing)."
    assert twin.startswith(
        "# US equity positioning · margin debt, S&P 500 futures, the VIX and the SKEW · "
        "2023-10-20 → 2026-10-20"
    )
    recorded = record(layout, WINDOW, NOW)
    assert show(layout, WINDOW, NOW).split("\n\n", 1)[0].startswith("Action: reuse. Tables: ")
    assert (
        Path(recorded["report"]["markdown"]).read_text(encoding="utf-8")
        == show(layout, WINDOW, NOW).split("\n\n", 1)[1]
    )
