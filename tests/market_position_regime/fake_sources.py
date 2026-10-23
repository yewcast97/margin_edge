"""A recording stand-in for the domain's three sources, answering from data held in memory.

It serves, as each source does (verified live; see the domain's ``AGENTS.md``): FINRA's
workbook at its fixed address, its bytes as given; the CFTC's Socrata API, the rows whose
report date lies in the ``$where`` clause's ``between`` dates, in date order, numbers as text
(the clause and the other parameters are checked to be exactly what ``cftc.query_url``
writes); and Cboe's VIX and SKEW histories at their fixed addresses, their bytes as given. ``statuses``
scripts the status of a request by its number (1-based); every request's URL is recorded.
"""

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from urllib.parse import parse_qsl, urlsplit

from market_state_research.market_position_regime.script import cboe, cftc, finra
from market_state_research.market_position_regime.script.client import Client, Response

from .support import NOW

JSON = {"content-type": "application/json;charset=utf-8"}


@dataclass
class FakeSources:
    workbook: bytes | None = None
    rows: list[dict[str, str]] = field(default_factory=list)  # CFTC rows, ascending
    history: bytes | None = None  # Cboe's VIX file
    skew: bytes | None = None  # Cboe's SKEW file
    statuses: dict[int, int] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)

    def __call__(self, url: str, headers: Mapping[str, str], limit: int) -> Response:
        self.calls.append(url)
        number = len(self.calls)
        if number in self.statuses:
            return Response(self.statuses[number], "Scripted", JSON, b"")
        parts = urlsplit(url)
        if url == finra.URL:
            if self.workbook is None:
                return Response(404, "Not Found", {}, b"")
            kind = {"content-type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}
            return Response(200, "OK", kind, self.workbook)
        if url in (cboe.VIX.url, cboe.SKEW.url):
            body = self.history if url == cboe.VIX.url else self.skew
            if body is None:
                return Response(404, "Not Found", {}, b"")
            return Response(200, "OK", {"content-type": "text/csv"}, body)
        if parts.netloc == cftc.HOST:
            return self._cftc(url, dict(parse_qsl(parts.query, keep_blank_values=True)))
        return Response(404, "Not Found", {}, b"")

    def _cftc(self, url: str, parameters: dict[str, str]) -> Response:
        where = parameters["$where"]
        first = date.fromisoformat(where.split("between '")[1][:10])
        last = date.fromisoformat(where.split("and '")[1][:10])
        assert url == cftc.query_url(first, last), "the query must be exactly what query_url writes"
        chosen = [row for row in self.rows if first <= date.fromisoformat(row[cftc.DATE_FIELD][:10]) <= last]
        return Response(200, "OK", JSON, json.dumps(chosen).encode())

    def client(self, clock: datetime = NOW) -> Client:
        return Client(fetch=self, clock=lambda: clock)
