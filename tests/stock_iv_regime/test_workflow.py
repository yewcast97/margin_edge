"""plan, fetch, record and show over raw files in a temporary data directory."""

from datetime import timedelta

import pytest

from market_state_research.common.sessions import session_window
from market_state_research.stock_iv_regime.script import workflow
from market_state_research.stock_iv_regime.script.workflow import fetch, plan, record, show

from .fake_eodhd import FakeEodhd
from .fake_tiingo import FakeTiingo
from .support import AS_OF, FETCHED, NOW, TICKER, prices, quotes, rising, save, save_prices, standard

LOOKBACK = 3
SPAN = session_window(AS_OF, LOOKBACK + 251)
PRICED = session_window(AS_OF, LOOKBACK + 252)  # the span and the session before it


def fill(layout, sessions=SPAN, ticker=TICKER):
    for index, day in enumerate(sessions):
        save(layout, standard(day, f"0.000{index % 10}", ticker=ticker))
    save_prices(layout, prices(rising(PRICED), ticker=ticker))


def entry(output, ticker=TICKER):
    (found,) = [item for item in output["tickers"] if item["ticker"] == ticker]
    return found


def test_plan_lists_what_to_fetch(layout, watchlist):
    save(layout, standard(AS_OF))
    output = plan(layout, [], LOOKBACK, NOW, watchlist=watchlist())
    item = entry(output)
    assert (output["as_of"], item["action"]) == ("2026-10-16", "fetch")
    assert item["missing_sessions"] == ["2026-10-15", "2026-10-14"]
    assert item["missing_history"] == {
        "sessions": 251,
        "first": SPAN[0].isoformat(),
        "last": SPAN[250].isoformat(),
    }
    assert item["window"] == {
        "start": "2026-10-14",
        "end": "2026-10-16",
        "sessions": 3,
        "span_start": SPAN[0].isoformat(),
    }
    assert (item["csv"], item["report"]["status"]) == (None, "missing")
    assert item["prices"] == {
        "status": "missing",
        "path": None,
        "start": None,
        "end": None,
        "bars": None,
        "reason": "no prices are fetched",
    }
    refreshed = entry(plan(layout, [TICKER], LOOKBACK, NOW, refresh=True))
    assert refreshed["missing_sessions"] == ["2026-10-16", "2026-10-15", "2026-10-14"]


def test_plan_says_whether_the_prices_are_current(layout):
    for day in SPAN:
        save(layout, standard(day))
    stale = save_prices(layout, prices(rising(PRICED[:-1])))
    item = entry(plan(layout, [TICKER], LOOKBACK, NOW))
    assert item["action"] == "fetch" and item["missing_sessions"] == []
    assert item["prices"] == {
        "status": "stale",
        "path": str(layout.raw(TICKER) / stale),
        "start": PRICED[0].isoformat(),
        "end": "2026-10-15",
        "bars": len(PRICED) - 1,
        "reason": "the prices end 2026-10-15, before the latest completed session 2026-10-16",
    }
    short = save_prices(layout, prices(rising(PRICED[2:]), fetched_at=FETCHED + timedelta(minutes=1)))
    item = entry(plan(layout, [TICKER], LOOKBACK, NOW))
    assert (item["prices"]["path"], item["prices"]["reason"]) == (
        str(layout.raw(TICKER) / short),
        f"the prices start {PRICED[2]}, after {PRICED[0]}, the first day the rows need",
    )
    save_prices(layout, prices(rising(PRICED), fetched_at=FETCHED + timedelta(minutes=2)))
    item = entry(plan(layout, [TICKER], LOOKBACK, NOW))
    assert (item["action"], item["prices"]["status"], item["prices"]["reason"]) == ("record", "current", None)


def test_older_chains_widen_the_range_the_prices_need(layout):
    fill(layout)
    older = session_window(SPAN[0], 3)[0]
    save(layout, standard(older))
    item = entry(plan(layout, [TICKER], LOOKBACK, NOW))
    assert item["prices"]["status"] == "stale"
    assert item["prices"]["reason"].endswith(
        f"after {session_window(older, 2)[0]}, the first day the rows need"
    )


def test_record_then_reuse(layout, clock):
    fill(layout)
    assert entry(plan(layout, [TICKER], LOOKBACK, NOW))["action"] == "record"
    output = record(layout, TICKER, LOOKBACK, clock.now)
    assert output["report"]["status"] == "written"
    assert output["csv"] == {
        "path": str(layout.formatted(TICKER) / "volatility.csv"),
        "rows": len(SPAN),
        "written": True,
    }
    assert [session["date"] for session in output["sessions"]] == ["2026-10-14", "2026-10-15", "2026-10-16"]
    latest = output["sessions"][-1]
    assert latest["skew_14d_percentile"] is not None
    assert (latest["call25_iv_14d_pct"], latest["put25_iv_14d_pct"]) == ("27.25", "34.53")  # bump 0.0003
    # Closes rise by 1 from 100 over the 255 priced sessions: 354 / 353 - 1.
    assert latest["daily_return_pct"] == "0.2833"
    assert latest["call25_corr_15s"] is None and latest["put25_corr_15s"] is not None
    later = clock.tick()
    item = entry(plan(layout, [TICKER], LOOKBACK, later))
    assert (item["action"], item["report"]["status"]) == ("reuse", "fresh")
    again = record(layout, TICKER, LOOKBACK, clock.tick())
    assert again["csv"]["written"] is False
    assert len(list(layout.reports(TICKER).glob("*.html"))) == 2


def test_record_is_pending_without_the_span_unless_partial(layout, clock):
    save(layout, standard(AS_OF))
    pending = record(layout, TICKER, LOOKBACK, clock.now)
    assert pending["report"]["status"] == "pending"
    assert pending["report"]["reason"] == (
        "2 of 3 window sessions are not fetched; 251 of the 251 sessions before the window the percentiles "
        "need are not fetched; no prices are fetched; run fetch or pass --partial"
    )
    partial = record(layout, TICKER, LOOKBACK, clock.tick(), partial=True)
    assert partial["report"]["status"] == "written"
    assert {gap["series"] for gap in partial["gaps"]} == {
        "skew_14d_percentile",
        "atm_iv_14d_percentile",
        "call25_corr_15s",
        "put25_corr_15s",
    }


def test_record_waits_for_current_prices(layout, clock):
    for day in SPAN:
        save(layout, standard(day))
    save_prices(layout, prices(rising(PRICED[:-1])))
    pending = record(layout, TICKER, LOOKBACK, clock.now)
    assert pending["report"]["reason"] == (
        "the prices end 2026-10-15, before the latest completed session 2026-10-16; "
        "run fetch or pass --partial"
    )


def test_invalid_files_block_record_and_show(layout, clock):
    save(layout, standard(AS_OF))
    (layout.raw(TICKER) / "chain_2026-10-15_20261017T100000EDT.json.gz").write_bytes(b"x")
    assert entry(plan(layout, [TICKER], LOOKBACK, NOW))["invalid_files"][0]["reason"].startswith(
        "not a gzip file"
    )
    with pytest.raises(ValueError, match="rename each with the suffix .rejected"):
        record(layout, TICKER, LOOKBACK, clock.now, partial=True)
    with pytest.raises(ValueError, match="failed validation"):
        show(layout, TICKER, LOOKBACK, clock.now)


def test_record_needs_a_window_session(layout, clock):
    with pytest.raises(ValueError, match="has a raw chain"):
        record(layout, TICKER, LOOKBACK, clock.now, partial=True)


def test_show_prints_the_status_and_the_twin(layout, clock):
    fill(layout)
    text = show(layout, TICKER, LOOKBACK, clock.now)
    assert text.startswith(
        "Action: record. CSV: none. Report: none (missing).\n\n# TEST · 14-DTE implied volatility"
    )
    assert "| 2026-10-16 |" in text


def market(fake, sessions, expiries, ticker=TICKER):
    latest_day = max(sessions)
    for day in sessions:
        for expiry in expiries:
            if day < expiry <= day + timedelta(days=65):
                rows = quotes(ticker, expiry)
                if day == latest_day:
                    rows[0] = {**rows[0], "tradetime": day.isoformat()}
                fake.add_eod(day, rows)
    for expiry in expiries:
        rows = quotes(ticker, expiry)
        if latest_day < expiry <= latest_day + timedelta(days=65):
            rows[0] = {**rows[0], "tradetime": latest_day.isoformat()}
        fake.listing.extend(rows)


def priced(tickers=(TICKER,), sessions=6):
    """Tiingo's bars of the ``sessions`` sessions to AS_OF for each ticker."""
    fake = FakeTiingo()
    for ticker in tickers:
        fake.add(ticker, rising(session_window(AS_OF, sessions)))
    return fake


def test_fetch_takes_the_prices_then_the_latest_session_then_sweeps(layout, monkeypatch):
    monkeypatch.setattr(workflow, "WINDOW", 3)  # a short span keeps the market small
    sessions = list(session_window(AS_OF, 5))
    expiries = [AS_OF + timedelta(days=days) for days in (-3, 4, 11, 32, 39)]
    fake = FakeEodhd()
    market(fake, sessions, expiries)
    tiingo = priced()
    output = fetch(layout, [TICKER], LOOKBACK, NOW, fake.client(), tiingo.client())
    item = entry(output)
    assert item["fetched"] == {"sessions": 5, "first": sessions[0].isoformat(), "last": "2026-10-16"}
    assert (item["pending"], item["fallbacks"], item["remaining"]["sessions"], output["stopped"]) == (
        [],
        [],
        0,
        None,
    )
    assert output["requests"] == item["requests"] == len(fake.calls)
    assert (output["eodhd_key"], output["tiingo_key"], output["price_requests"]) == ("set", "set", 1)
    # The prices start at the session before the span's first, whose bar its return needs.
    assert tiingo.calls == [
        "https://api.tiingo.com/tiingo/daily/TEST/prices?startDate=2026-10-09&endDate=2026-10-16"
    ]
    path = layout.raw(TICKER) / "prices_2026-10-16_20261019T090000EDT.json.gz"
    assert item["prices"] == {"status": "new", "path": str(path), "reason": None}
    assert "contracts" in fake.calls[0] and "tradetime_eq" in fake.calls[1]
    names = sorted(path.name for path in layout.raw(TICKER).iterdir())
    assert len(names) == 6
    assert entry(plan(layout, [TICKER], LOOKBACK, NOW))["action"] == "record"


def test_every_tiingo_outcome_leaves_the_chains_to_run(layout, monkeypatch):
    monkeypatch.setattr(workflow, "WINDOW", 3)
    tickers = ["AAA", "BBB", "CCC", "DDD"]
    for ticker in tickers[1:]:  # AAA's chains are still to fetch
        for day in session_window(AS_OF, 5):
            save(layout, standard(day, ticker=ticker))
    tiingo = priced(tickers=["BBB"])
    tiingo.add("CCC", rising(session_window(AS_OF, 6)[:-1]))  # the latest session is not published
    tiingo.statuses = {1: 503}
    eodhd = FakeEodhd()
    output = fetch(layout, tickers, LOOKBACK, NOW, eodhd.client(), tiingo.client())
    statuses = {item["ticker"]: item["prices"]["status"] for item in output["tickers"]}
    assert statuses == {"AAA": "failed", "BBB": "new", "CCC": "pending", "DDD": "empty"}
    assert eodhd.calls and entry(output, "AAA")["fetched"]["sessions"] == 5  # empty chains: none listed
    assert entry(output, "AAA")["prices"]["reason"].endswith(
        "HTTP 503 Scripted; Tiingo is unavailable: run fetch again later"
    )
    assert (
        entry(output, "CCC")["prices"]["reason"]
        == "Tiingo has not published 2026-10-16 yet; run fetch again later"
    )
    assert output["stopped"] is None and output["price_requests"] == 4


def test_a_tiingo_stop_asks_nothing_more_of_tiingo(layout, monkeypatch):
    monkeypatch.setattr(workflow, "WINDOW", 3)
    tiingo = priced(tickers=["AAA", "BBB"])
    tiingo.statuses = {1: 429}
    eodhd = FakeEodhd()
    output = fetch(layout, ["AAA", "BBB"], LOOKBACK, NOW, eodhd.client(), tiingo.client())
    first, second = (entry(output, ticker)["prices"] for ticker in ("AAA", "BBB"))
    assert first["status"] == "stopped" and "HTTP 429" in first["reason"]
    assert second == {
        "status": "stopped",
        "path": None,
        "reason": "not requested: Tiingo stopped the run at AAA",
    }
    assert len(tiingo.calls) == 1 and output["price_requests"] == 1
    assert (
        eodhd.calls and entry(output, "AAA")["fetched"]["sessions"] == 5
    )  # empty chains: no contract listed


def test_fetch_reports_pending_and_stops_cleanly(layout, monkeypatch):
    monkeypatch.setattr(workflow, "WINDOW", 3)
    sessions = list(session_window(AS_OF, 5))
    expiries = [AS_OF + timedelta(days=days) for days in (4, 11, 32, 39)]
    fake = FakeEodhd()
    market(fake, sessions[:-1], expiries)  # the latest session is not published
    fake.listing = [row for row in fake.listing]
    output = fetch(layout, [TICKER], LOOKBACK, NOW, fake.client(budget=3), priced().client())
    item = entry(output)
    assert item["pending"] == ["2026-10-16"]
    assert output["stopped"] == {
        "ticker": TICKER,
        "reason": "the run's budget of 3 requests is spent; run fetch again",
    }
    assert item["remaining"]["sessions"] == 5 - item["fetched"]["sessions"]


def test_fetch_with_a_quota_stop(layout, monkeypatch):
    monkeypatch.setattr(workflow, "WINDOW", 3)
    fake = FakeEodhd(statuses={1: 402})
    output = fetch(layout, [TICKER], LOOKBACK, NOW, fake.client(), priced().client())
    assert output["stopped"]["reason"].startswith(
        "GET https://eodhd.com/api/mp/unicornbay/options/contracts?"
    )
    assert "quota" in output["stopped"]["reason"]
    assert entry(output)["fetched"]["sessions"] == 0


def interrupt() -> None:
    raise KeyboardInterrupt


def test_an_interrupted_fetch_reports_what_it_wrote_and_the_next_one_resumes(layout, monkeypatch):
    monkeypatch.setattr(workflow, "WINDOW", 3)
    sessions = list(session_window(AS_OF, 5))
    expiries = [AS_OF + timedelta(days=days) for days in (-3, 4, 11, 32, 39)]
    fake, tiingo = FakeEodhd(), priced()
    market(fake, sessions, expiries)
    fake.interruptions = {3: interrupt}  # Ctrl-C at the first sweep, after the latest session's two requests
    output = fetch(layout, [TICKER], LOOKBACK, NOW, fake.client(), tiingo.client())
    item = entry(output)
    assert output["stopped"] == {"ticker": TICKER, "reason": workflow.INTERRUPTED}
    assert item["fetched"] == {"sessions": 1, "first": "2026-10-16", "last": "2026-10-16"}
    assert item["remaining"] == {
        "sessions": 4,
        "first": sessions[0].isoformat(),
        "last": sessions[3].isoformat(),
    }
    assert output["requests"] == item["requests"] == 3
    # The next run requests only the sessions still missing, and no session gets a second chain.
    fake.interruptions = {}
    again = fetch(layout, [TICKER], LOOKBACK, NOW, fake.client(), tiingo.client())
    assert again["stopped"] is None and entry(again)["fetched"]["sessions"] == 4
    chains = sorted(path.name for path in layout.raw(TICKER).glob("chain_*"))
    assert [name[6:16] for name in chains] == [day.isoformat() for day in sessions]
    assert entry(plan(layout, [TICKER], LOOKBACK, NOW))["action"] == "record"


def test_a_stop_in_the_latest_session_counts_its_requests(layout, monkeypatch):
    monkeypatch.setattr(workflow, "WINDOW", 3)
    fake = FakeEodhd()
    market(fake, list(session_window(AS_OF, 5)), [AS_OF + timedelta(days=days) for days in (4, 11, 32, 39)])
    # The listing is sent; the budget stops the request for the records traded on the session.
    output = fetch(layout, [TICKER], LOOKBACK, NOW, fake.client(budget=1), priced().client())
    assert output["stopped"]["ticker"] == TICKER and "budget of 1 requests" in output["stopped"]["reason"]
    assert output["requests"] == entry(output)["requests"] == 1


def test_fetch_skips_what_is_stored(layout, monkeypatch):
    monkeypatch.setattr(workflow, "WINDOW", 3)
    for day in session_window(AS_OF, 5):
        save(layout, standard(day, fetched_at=FETCHED))
    name = save_prices(layout, prices(rising(session_window(AS_OF, 6))))
    fake, tiingo = FakeEodhd(), priced()
    output = fetch(layout, [TICKER], LOOKBACK, NOW, fake.client(), tiingo.client())
    assert (fake.calls, tiingo.calls, entry(output)["fetched"]["sessions"]) == ([], [], 0)
    assert entry(output)["prices"] == {
        "status": "reused",
        "path": str(layout.raw(TICKER) / name),
        "reason": None,
    }
    refreshed = fetch(layout, [TICKER], LOOKBACK, NOW, FakeEodhd().client(), tiingo.client(), refresh=True)
    assert entry(refreshed)["prices"]["status"] == "new" and len(tiingo.calls) == 1
