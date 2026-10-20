"""A recording stand-in for the domain's three sources, answering from data held in memory.

It serves, as each source does (verified live; see the domain's ``AGENTS.md``): FINRA's
workbook at its fixed address, its bytes as given; the CFTC's Socrata API, the rows whose
report date lies in the ``$where`` clause's ``between`` dates, in date order, numbers as text
(the clause and the other parameters are checked to be exactly what ``cftc.query_url``
writes); and FRED's observations of a series, only with the ``api_key`` it expects, a wrong
or missing key getting FRED's HTTP 400. ``statuses`` scripts the status of a request by its
number (1-based); every request's URL is recorded, the key cut from FRED's.
"""

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from urllib.parse import parse_qsl, urlsplit

from market_state_research.market_position_regime.script import cftc, finra, fred
from market_state_research.market_position_regime.script.client import Client, Response

from .support import KEY, NOW, fred_response

JSON = {"content-type": "application/json;charset=utf-8"}


@dataclass
class FakeSources:
    workbook: bytes | None = None
    rows: list[dict[str, str]] = field(default_factory=list)  # CFTC rows, ascending
    series: dict[str, dict[date, str]] = field(default_factory=dict)  # FRED values by quarter end
    statuses: dict[int, int] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)
    keys: list[str | None] = field(default_factory=list)  # the api_key each FRED request carried

    def __call__(self, url: str, headers: Mapping[str, str], limit: int) -> Response:
        parts = urlsplit(url)
        parameters = parse_qsl(parts.query, keep_blank_values=True)
        key = dict(parameters).get("api_key")
        self.calls.append(url.replace(f"&api_key={key}", "") if key is not None else url)
        number = len(self.calls)
        if number in self.statuses:
            return Response(self.statuses[number], "Scripted", JSON, b"")
        if url == finra.URL:
            if self.workbook is None:
                return Response(404, "Not Found", {}, b"")
            kind = {"content-type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}
            return Response(200, "OK", kind, self.workbook)
        if parts.netloc == cftc.HOST:
            return self._cftc(url, dict(parameters))
        if parts.netloc == fred.HOST:
            self.keys.append(key)
            if key != KEY:
                body = (
                    b'{"error_code":400,"error_message":"Bad Request.  '
                    b'The value for variable api_key is not registered."}'
                )
                return Response(400, "Bad Request", JSON, body)
            values = self.series.get(dict(parameters).get("series_id", ""))
            if values is None:
                return Response(400, "Bad Request", JSON, b'{"error_code":400}')
            return Response(200, "OK", JSON, json.dumps(fred_response(values)).encode())
        return Response(404, "Not Found", {}, b"")

    def _cftc(self, url: str, parameters: dict[str, str]) -> Response:
        where = parameters["$where"]
        first = date.fromisoformat(where.split("between '")[1][:10])
        last = date.fromisoformat(where.split("and '")[1][:10])
        assert url == cftc.query_url(first, last), "the query must be exactly what query_url writes"
        chosen = [row for row in self.rows if first <= date.fromisoformat(row[cftc.DATE_FIELD][:10]) <= last]
        return Response(200, "OK", JSON, json.dumps(chosen).encode())

    def client(self, clock: datetime = NOW) -> Client:
        return Client(KEY, fetch=self, clock=lambda: clock)
