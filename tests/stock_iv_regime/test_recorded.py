"""The latest-session path over two pages recorded live from EODHD (AEP, 2026-10-16).

The fixtures are the bodies EODHD returned to the two queries ``fetch.latest`` sends, byte
for byte, pinned by SHA-256 and never edited; they hold no key (EODHD's next links carry
none).
"""

import hashlib
from datetime import date
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit

from market_state_research.stock_iv_regime.script.chain import check_chain, dump, load
from market_state_research.stock_iv_regime.script.client import EodhdClient, Response
from market_state_research.stock_iv_regime.script.fetch import latest
from market_state_research.stock_iv_regime.script.surface import surface

from .fake_eodhd import Sleeps
from .support import CANARY, NOW

FIXTURES = Path(__file__).resolve().parent / "fixtures"
PINNED = {
    "aep_2026-10-16_contracts.json": "258e45ac15b5b55880733414b88e03d43f4c31ba8f2bed10da9123fc12b57077",
    "aep_2026-10-16_traded.json": "e081b0919991d4c657e13366e2b4820420a1a36939e117d79249e17f9ffaee0d",
}
SESSION = date(2026, 10, 16)


def recorded(url: str, headers, limit) -> Response:
    parts = urlsplit(url)
    query = parse_qsl(parts.query)
    assert ("api_token", CANARY) in query
    public = urlencode([(name, value) for name, value in query if name != "api_token"])
    name = "aep_2026-10-16_traded.json" if "tradetime_eq" in public else "aep_2026-10-16_contracts.json"
    return Response(200, "OK", {"content-type": "application/json"}, (FIXTURES / name).read_bytes())


def test_the_fixtures_are_the_recorded_bytes():
    for name, digest in PINNED.items():
        data = (FIXTURES / name).read_bytes()
        assert hashlib.sha256(data).hexdigest() == digest
        assert b"api_token" not in data


def test_latest_proves_the_recorded_listing_and_keeps_literal_numbers():
    client = EodhdClient(CANARY, fetch=recorded, sleep=Sleeps(), clock=lambda: NOW)
    found = latest(client, "AEP", SESSION)
    assert found.chain is not None, found.reason
    item = found.chain
    assert [(expiry.exp_date.isoformat(), expiry.contracts) for expiry in item.expiries] == [
        ("2026-11-20", 46),
        ("2026-12-18", 54),
    ]
    # Every contract of both expiries is kept; neither lies 1 to 14 days out, so there is no value.
    assert {row.expiry for row in item.rows} == {date(2026, 11, 20), date(2026, 12, 18)}
    assert len(item.rows) == 100
    first = next(row for row in item.rows if row.contract == "AEP261120C00080000")
    assert (first.attributes["volatility"], first.attributes["delta"]) == ("0.8291", "0.973923")
    assert item.traded and all(record.date == SESSION for record in item.traded)
    assert check_chain(load(dump(item)), "AEP", None, NOW).source == "contracts"
    assert surface(SESSION, item.listed, item.rows).reason == (
        "no expiry is listed 1 to 14 days out (2026-10-17 to 2026-10-30)"
    )
