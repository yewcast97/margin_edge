"""A recording stand-in for Tiingo's daily prices endpoint, answering from bars held in memory.

It serves ``/tiingo/daily/{TICKER}/prices`` as Tiingo does (verified live; see the domain's
``AGENTS.md``): the bars of ``startDate`` to ``endDate``, both included, as a JSON array
whose numbers are literal (``"close":102.81``) and whose dates read
``2026-10-16T00:00:00.000Z``; an unknown ticker gets 404 with ``{"detail": ...}``.
``statuses`` scripts the status of a request by its number (1-based), whose body is then
Tiingo's ``detail`` object; every request's URL and the token of its ``Authorization``
header are recorded.
"""

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from urllib.parse import parse_qsl, urlsplit

from market_state_research.stock_iv_regime.script.client import Response
from market_state_research.stock_iv_regime.script.prices import BAR_FIELDS
from market_state_research.stock_iv_regime.script.tiingo import TiingoClient

from .support import NOW, TIINGO_CANARY, bar_values


@dataclass
class FakeTiingo:
    bars: dict[str, list[dict[str, str]]] = field(default_factory=dict)  # by ticker, ascending
    statuses: dict[int, int] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)
    tokens: list[str] = field(default_factory=list)

    def add(self, ticker: str, closes: Mapping[date, str]) -> None:
        """Bars of ``closes`` for ``ticker`` (adjusted close equal to close)."""
        found = self.bars.setdefault(ticker, [])
        found.extend(bar_values(day, closes[day]) for day in sorted(closes))
        found.sort(key=lambda bar: bar["date"])

    def __call__(self, url: str, headers: Mapping[str, str], limit: int) -> Response:
        self.calls.append(url)
        authorization = headers.get("Authorization", "")
        self.tokens.append(authorization.removeprefix("Token "))
        number = len(self.calls)
        if number in self.statuses:
            body = b'{"detail":"Scripted."}'
            return Response(self.statuses[number], "Scripted", {"content-type": "application/json"}, body)
        parts = urlsplit(url)
        ticker = parts.path.split("/")[3]
        parameters = dict(parse_qsl(parts.query))
        if ticker not in self.bars:
            detail = json.dumps({"detail": f"Error: Ticker '{ticker}' not found"})
            return Response(404, "Not Found", {"content-type": "application/json"}, detail.encode())
        start, end = parameters["startDate"], parameters["endDate"]
        chosen = [bar for bar in self.bars[ticker] if start <= bar["date"][:10] <= end]
        body = "[" + ",".join(self._bar(bar) for bar in chosen) + "]"
        return Response(200, "OK", {"content-type": "application/json"}, body.encode())

    @staticmethod
    def _bar(bar: Mapping[str, str]) -> str:
        fields = [f'"date":{json.dumps(bar["date"])}']
        fields += [f'"{name}":{bar[name]}' for name in BAR_FIELDS[1:]]  # numbers, not strings
        return "{" + ",".join(fields) + "}"

    def client(self, clock: datetime = NOW) -> TiingoClient:
        return TiingoClient(TIINGO_CANARY, fetch=self, clock=lambda: clock)
