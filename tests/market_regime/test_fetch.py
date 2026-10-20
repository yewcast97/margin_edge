"""Fetching chains (the latest session from the listing, older ones by sweeps, and the stops) and
fetching prices."""

from datetime import date, timedelta

import pytest

from market_state_research.common.sessions import session_window
from market_state_research.market_regime.script import api
from market_state_research.market_regime.script import fetch as fetch_module
from market_state_research.market_regime.script.chain import read_chain
from market_state_research.market_regime.script.client import BudgetSpent, EodhdError, QuotaExceeded, Response
from market_state_research.market_regime.script.fetch import Outcome, fetch_prices, history, latest, months
from market_state_research.market_regime.script.prices import read_prices
from market_state_research.market_regime.script.tiingo import Stopped, TiingoClient, TiingoError

from .fake_eodhd import FakeEodhd
from .fake_tiingo import FakeTiingo
from .support import AS_OF, NOW, TICKER, TIINGO_CANARY, attributes, edt, quotes, rising

E1, E2, E3 = (AS_OF + timedelta(days=days) for days in (9, 19, 40))


def market(fake: FakeEodhd, sessions, expiries, *, ticker=TICKER, traded_on_latest=True) -> None:
    """Every session lists every expiry 1 to 65 days after it with the hand-worked quotes; on the
    latest session the first contract of each expiry trades, and the listing holds its values."""
    latest_day = max(sessions)
    for day in sessions:
        for expiry in expiries:
            if not day < expiry <= day + timedelta(days=65):
                continue
            rows = quotes(ticker, expiry)
            if day == latest_day and traded_on_latest:
                rows[0] = {**rows[0], "tradetime": day.isoformat(), "volume": "5"}
            fake.add_eod(day, rows)
            if day == latest_day:
                fake.listing.extend(rows)


def test_latest_reads_the_listing_and_proves_it():
    fake = FakeEodhd()
    market(fake, [AS_OF], [E1, E2, E3])
    found = latest(fake.client(), TICKER, AS_OF)
    assert found.chain is not None and not found.pending
    item = found.chain
    assert (item.source, item.listed, {row.expiry for row in item.rows}) == (
        "contracts",
        (E1, E2, E3),
        {E1, E2, E3},
    )
    assert len(item.rows) == 21
    assert len(item.traded or ()) == 3
    assert len(fake.calls) == 2 and item.requests == tuple(fake.calls)


def test_latest_is_pending_until_the_session_is_published():
    fake = FakeEodhd()
    market(fake, [AS_OF], [E1, E2], traded_on_latest=False)
    assert latest(fake.client(), TICKER, AS_OF).pending


def test_later_dated_copies_are_not_proof():
    fake = FakeEodhd()
    market(fake, [AS_OF], [E1, E2], traded_on_latest=False)
    copy = {**quotes(TICKER, E1)[0], "tradetime": AS_OF.isoformat()}
    fake.add_eod(AS_OF + timedelta(days=3), [copy])
    assert latest(fake.client(), TICKER, AS_OF).pending


def test_a_listing_that_is_not_the_sessions_is_left_to_the_sweeps():
    fake = FakeEodhd()
    market(fake, [AS_OF], [E1, E2])
    fake.listing[0] = {**fake.listing[0], "volatility": "0.99"}
    found = latest(fake.client(), TICKER, AS_OF)
    assert found.chain is None and not found.pending
    assert "the contracts listing's volatility differs" in (found.reason or "")
    assert latest(FakeEodhd().client(), TICKER, AS_OF).reason == (
        "the contracts listing names no contract expiring within the window"
    )


def test_months_run_latest_first():
    assert months(date(2026, 9, 20), date(2026, 11, 3)) == [
        (date(2026, 11, 1), date(2026, 11, 3)),
        (date(2026, 10, 1), date(2026, 10, 31)),
        (date(2026, 9, 20), date(2026, 9, 30)),
    ]


def sweep_market(fake: FakeEodhd, sessions, expiries) -> None:
    """Every session lists every expiry after it within 65 days; the listing names them all."""
    for day in sessions:
        for expiry in expiries:
            if day < expiry <= day + timedelta(days=65):
                fake.add_eod(day, quotes(TICKER, expiry))
    for expiry in expiries:
        fake.listing.extend(quotes(TICKER, expiry))


def test_history_writes_each_session_newest_first(layout):
    sessions = list(session_window(AS_OF, 4))
    expiries = [AS_OF + timedelta(days=days) for days in (-1, 6, 13, 34, 41)]
    fake = FakeEodhd()
    sweep_market(fake, sessions, expiries)
    fake.add_eod(date(2026, 10, 12), [])  # nothing
    outcome = Outcome()
    history(fake.client(), layout, TICKER, sessions, outcome)
    assert outcome.written == sorted(sessions, reverse=True)
    assert outcome.empty == []
    for path in outcome.files:
        item = read_chain(path.read_bytes(), TICKER, path.name, NOW)
        assert {row.expiry for row in item.rows} == set(item.listed)  # every expiry is kept whole
        assert len(item.rows) == 7 * len(item.listed)
        assert all(row.date == item.session for row in item.rows)
        assert item.listed == tuple(expiry for expiry in expiries if item.session < expiry)


def test_holiday_copies_other_dates_and_adjusted_series_are_dropped(layout):
    session = date(2026, 9, 8)  # the Tuesday after Labor Day
    expiry = session + timedelta(days=30)
    fake = FakeEodhd()
    fake.add_eod(session, quotes(TICKER, expiry))
    fake.add_eod(date(2026, 9, 7), quotes(TICKER, expiry))  # the holiday's stale copy
    adjusted = attributes("TEST1", expiry, "call", "150")
    fake.underlying[str(adjusted["contract"])] = TICKER
    fake.add_eod(session, [adjusted])
    fake.listing.extend(quotes(TICKER, expiry) + [adjusted])
    outcome = Outcome()
    history(fake.client(), layout, TICKER, [session], outcome)
    (path,) = outcome.files
    item = read_chain(path.read_bytes(), TICKER, path.name, NOW)
    assert (item.listed, len(item.rows)) == ((expiry,), 7)
    assert all(row.root == TICKER for row in item.rows)


def test_a_session_without_contracts_gets_an_empty_chain(layout):
    outcome = Outcome()
    fake = FakeEodhd()
    history(fake.client(), layout, TICKER, [AS_OF], outcome)
    assert (outcome.written, outcome.empty) == ([AS_OF], [AS_OF])
    (path,) = outcome.files
    item = read_chain(path.read_bytes(), TICKER, path.name, NOW)
    assert (item.expiries, item.rows, item.source) == ((), (), "eod")
    assert len(item.requests) == 3  # the three months of listings its window meets


@pytest.fixture
def small_pages(monkeypatch):
    """Pages of 10 records, so narrowing shows on small markets."""
    monkeypatch.setattr(api, "PAGE_LIMIT", 10)
    monkeypatch.setattr(fetch_module, "PAGE_LIMIT", 10)


def strike_market(fake: FakeEodhd, sessions, expiry, strikes, ticker=TICKER) -> None:
    for day in sessions:
        fake.add_eod(
            day,
            [attributes(ticker, expiry, right, strike) for right in ("call", "put") for strike in strikes],
        )
    fake.listing.extend(
        attributes(ticker, expiry, right, strike) for right in ("call", "put") for strike in strikes
    )


def contracts_per_session(layout, outcome) -> dict:
    counts = {}
    for path in outcome.files:
        item = read_chain(path.read_bytes(), TICKER, path.name, NOW)
        counts[item.session] = item.expiries[0].contracts if item.expiries else 0
    return counts


def test_full_pages_are_used_up_to_their_last_strike(layout, small_pages):
    sessions = list(session_window(AS_OF, 8))
    expiry = AS_OF + timedelta(days=20)
    fake = FakeEodhd()
    strike_market(fake, sessions, expiry, [str(strike) for strike in range(100, 106)])
    outcome = Outcome()
    history(fake.client(), layout, TICKER, sessions, outcome)
    assert sorted(outcome.written) == sessions
    assert set(contracts_per_session(layout, outcome).values()) == {12}
    starts = [call.split("strike_from%5D=")[1].split("&")[0] for call in fake.calls if "strike_from" in call]
    assert starts[:4] == ["101", "102", "103", "104"]  # each page of 10 holds one whole strike of 8 records
    assert not any("page%5Boffset%5D" in call for call in fake.calls)


def test_a_page_of_one_strike_is_read_by_its_contract(layout, small_pages):
    sessions = list(session_window(AS_OF, 8))
    expiry = AS_OF + timedelta(days=20)
    fake = FakeEodhd()
    strike_market(fake, sessions, expiry, ["100", "101"])
    # An adjusted series at the same strikes fills a page of 10 with strike 100 alone.
    strike_market(fake, sessions, expiry, ["100", "101"], ticker="TEST1")
    for values in fake.listing:
        if str(values["contract"]).startswith("TEST1"):
            fake.underlying[str(values["contract"])] = TICKER
    for _, values in fake.records:
        if str(values["contract"]).startswith("TEST1"):
            fake.underlying[str(values["contract"])] = TICKER
    outcome = Outcome()
    history(fake.client(), layout, TICKER, sessions, outcome)
    assert set(contracts_per_session(layout, outcome).values()) == {4}
    assert any("filter%5Bcontract%5D=TEST261105C00100000" in call for call in fake.calls)


def test_shuffled_ties_change_nothing(layout, small_pages):
    sessions = list(session_window(AS_OF, 6))
    expiries = [AS_OF + timedelta(days=days) for days in (6, 34)]
    results = []
    for shuffle in (False, True):
        fake = FakeEodhd(shuffle_ties=shuffle)
        for expiry in expiries:
            strike_market(
                fake, [day for day in sessions if day < expiry], expiry, [str(s) for s in range(100, 104)]
            )
        target = layout.__class__(layout.root / str(shuffle))
        outcome = Outcome()
        history(fake.client(), target, TICKER, sessions, outcome)
        chains = {}
        for path in outcome.files:
            item = read_chain(path.read_bytes(), TICKER, path.name, NOW)
            chains[item.session] = (item.expiries, sorted(row.id for row in item.rows))
        results.append(chains)
    assert results[0] == results[1] and len(results[0]) == 6


def test_a_duplicate_record_is_refused(layout):
    expiry = AS_OF + timedelta(days=30)
    fake = FakeEodhd()
    fake.add_eod(AS_OF, quotes(TICKER, expiry) + quotes(TICKER, expiry)[:1])
    fake.listing.extend(quotes(TICKER, expiry))
    with pytest.raises(EodhdError, match="twice"):
        history(fake.client(), layout, TICKER, [AS_OF], Outcome())


def test_a_stop_keeps_the_sessions_already_written(layout):
    sessions = [date(2026, 8, 14), date(2026, 9, 15), AS_OF]
    expiries = [
        date(2026, 8, 21),
        date(2026, 9, 18),
        date(2026, 10, 16),
        date(2026, 11, 20),
        date(2026, 12, 18),
    ]
    fake = FakeEodhd()
    sweep_market(fake, sessions, expiries)
    complete = Outcome()
    history(fake.client(), layout.__class__(layout.root / "complete"), TICKER, sessions, complete)
    assert complete.written == sorted(sessions, reverse=True)
    total = len(fake.calls)
    fake.calls.clear()
    fake.statuses = {total - 1: 402}  # the call sweep of the oldest expiry
    outcome = Outcome()
    with pytest.raises(QuotaExceeded):
        history(fake.client(), layout, TICKER, sessions, outcome)
    assert outcome.written == [AS_OF, date(2026, 9, 15)]
    with pytest.raises(BudgetSpent):
        history(
            FakeEodhd(listing=list(fake.listing), records=list(fake.records)).client(budget=2),
            layout,
            TICKER,
            sessions,
            Outcome(),
        )


# --------------------------------------------------------------------------- the prices

START = date(2026, 10, 12)


def test_fetch_prices_writes_the_bars_of_the_range(layout):
    fake = FakeTiingo()
    fake.add(TICKER, rising(session_window(AS_OF, 10)))
    found = fetch_prices(fake.client(), layout, TICKER, START, AS_OF)
    assert found.status == "new" and found.path is not None
    assert found.path.name == "prices_2026-10-16_20261019T090000EDT.json.gz"
    item = read_prices(found.path.read_bytes(), TICKER, found.path.name, NOW)
    assert [bar.day for bar in item.bars] == list(session_window(AS_OF, 5))
    assert item.request == fake.calls[0] and fake.tokens == [TIINGO_CANARY]
    assert (item.start, item.end, item.fetched_at) == (START, AS_OF, NOW)


def test_fetch_prices_without_the_last_bar_is_pending(layout):
    fake = FakeTiingo()
    fake.add(TICKER, rising(session_window(AS_OF, 10)[:-1]))  # 2026-10-16 is not published
    assert fetch_prices(fake.client(), layout, TICKER, START, AS_OF).status == "pending"
    assert not layout.raw(TICKER).exists()


def test_an_uncovered_ticker_gets_an_empty_file(layout):
    found = fetch_prices(FakeTiingo().client(), layout, TICKER, START, AS_OF)
    assert found.status == "empty" and found.path is not None
    assert read_prices(found.path.read_bytes(), TICKER, found.path.name, NOW).bars == ()


def test_refusals_and_failures_raise(layout):
    fake = FakeTiingo(statuses={1: 429, 2: 500})
    fake.add(TICKER, rising(session_window(AS_OF, 10)))
    with pytest.raises(Stopped, match="HTTP 429"):
        fetch_prices(fake.client(), layout, TICKER, START, AS_OF)
    with pytest.raises(TiingoError, match="HTTP 500"):
        fetch_prices(fake.client(), layout, TICKER, START, AS_OF)


def test_an_answer_that_fails_the_rules_is_a_failure(layout):
    fake = FakeTiingo()
    fake.add(TICKER, {date(2026, 10, 10): "1", AS_OF: "2"})  # a Saturday bar
    with pytest.raises(TiingoError, match="2026-10-10, not an XNYS trading session"):
        fetch_prices(fake.client(), layout, TICKER, START - timedelta(days=5), AS_OF)
    early = FakeTiingo()
    early.add(TICKER, rising([AS_OF]))
    with pytest.raises(TiingoError, match="before the session 2026-10-16 closed"):
        fetch_prices(early.client(edt(2026, 10, 16, 15)), layout, TICKER, START, AS_OF)

    def garbage(url, headers, limit):
        return Response(200, "OK", {}, b"<html>")

    client = TiingoClient(TIINGO_CANARY, fetch=garbage, clock=lambda: NOW)
    with pytest.raises(TiingoError, match="the response is not Tiingo's daily prices: invalid JSON"):
        fetch_prices(client, layout, TICKER, START, AS_OF)
    assert not layout.raw(TICKER).exists()
