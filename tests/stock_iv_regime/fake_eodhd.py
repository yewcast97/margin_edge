"""A recording stand-in for EODHD's options endpoints, answering from records held in memory.

It serves the two endpoints as EODHD does: the filters, ``sort`` (records of one strike or
expiry newest first), the ``fields`` selection (none named on a page without records),
``page[limit]`` and ``page[offset]`` (more than 10,000 is refused with 422), ``links.next``
and numbers written as the literal text the records hold. With ``shuffle_ties``, records that
tie on the sort key come back in a new order on every request, as EODHD's do, so a second
page may repeat some records and miss as many. ``underlying`` maps a contract to its
underlying when its OCC root differs (an adjusted series). ``statuses`` scripts the status of
a request by its number (1-based), whose body is then empty; every request's token-free URL
and token are recorded.
"""

import json
import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from urllib.parse import parse_qsl, urlencode, urlsplit

from market_state_research.stock_iv_regime.script.api import NUMBER_FIELDS, parse_occ
from market_state_research.stock_iv_regime.script.client import EodhdClient, Response

from .support import CANARY, NOW

Attributes = Mapping[str, str | None]


@dataclass
class Sleeps:
    """Records every pause instead of sleeping."""

    calls: list[float] = field(default_factory=list)

    def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)


@dataclass
class FakeEodhd:
    listing: list[Attributes] = field(default_factory=list)  # the contracts endpoint: latest values
    records: list[tuple[date, Attributes]] = field(default_factory=list)  # the eod endpoint
    underlying: dict[str, str] = field(default_factory=dict)
    statuses: dict[int, int] = field(default_factory=dict)
    headers: dict[int, dict[str, str]] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)
    tokens: list[str] = field(default_factory=list)
    shuffle_ties: bool = False

    def add_eod(self, day: date, rows: Sequence[Attributes]) -> None:
        self.records.extend((day, row) for row in rows)

    def _underlying(self, contract: str) -> str:
        return self.underlying.get(contract, parse_occ(contract).root)

    def __call__(self, url: str, headers: Mapping[str, str], limit: int) -> Response:
        parts = urlsplit(url)
        query = parse_qsl(parts.query, keep_blank_values=True)
        token = [value for name, value in query if name == "api_token"]
        public = [(name, value) for name, value in query if name != "api_token"]
        self.calls.append(f"{parts.scheme}://{parts.netloc}{parts.path}?{urlencode(public)}")
        self.tokens.append(token[0] if token else "")
        number = len(self.calls)
        if number in self.statuses:
            return Response(self.statuses[number], "Scripted", self.headers.get(number, {}), b"")
        endpoint = parts.path.rsplit("/", 1)[-1]
        parameters = dict(public)
        offset = int(parameters.get("page[offset]", "0"))
        page_limit = int(parameters.get("page[limit]", "1000"))
        if offset > 10_000:
            body = b'{"errors":{"page.offset":["The page.offset may not be greater than 10000."]}}'
            return Response(422, "Unprocessable Content", {}, body)
        if endpoint == "contracts":
            rows: list[tuple[str, Attributes]] = [(str(row["contract"]), row) for row in self.listing]
            kind = "options-contracts"
        else:
            rows = [(f"{row['contract']}-{day.isoformat()}", row) for day, row in self.records]
            kind = "options-eod"
        rows = [(identifier, row) for identifier, row in rows if self._matches(row, parameters)]
        sort = parameters.get("sort", "exp_date")

        def key(item: tuple[str, Attributes]) -> object:
            return Decimal(str(item[1]["strike"])) if sort == "strike" else str(item[1]["exp_date"])

        if self.shuffle_ties:
            random.Random(len(self.calls)).shuffle(rows)
            rows.sort(key=key)  # stable: ties keep the shuffled order
        else:
            rows.sort(key=lambda item: item[0][-10:], reverse=True)  # newest record first (stable below)
            rows.sort(key=lambda item: (key(item), str(item[1]["contract"])))
        fields = parameters.get(f"fields[{kind}]", "").split(",")
        chosen = rows[offset : offset + page_limit]
        more = offset + page_limit < len(rows)
        data = ",".join(
            '{{"id":{},"type":{},"attributes":{{{}}}}}'.format(
                json.dumps(identifier),
                json.dumps(kind),
                ",".join(f"{json.dumps(name)}:{self._literal(name, row[name])}" for name in fields),
            )
            for identifier, row in chosen
        )
        following = "null"
        if more:
            next_query = [(name, value) for name, value in public if name != "page[offset]"]
            next_query.append(("page[offset]", str(offset + page_limit)))
            following = json.dumps(f"https://eodhd.com{parts.path}?{urlencode(next_query)}")
        named = fields if chosen else []  # EODHD names no field on a page without records
        meta = f'{{"offset":{offset},"limit":{page_limit},"fields":{json.dumps(named)}}}'
        body = f'{{"meta":{meta},"data":[{data}],"links":{{"next":{following}}}}}'.encode()
        return Response(200, "OK", {"content-type": "application/json"}, body)

    @staticmethod
    def _literal(name: str, value: str | None) -> str:
        if value is None:
            return "null"
        return value if name in NUMBER_FIELDS else json.dumps(value)

    def _matches(self, row: Attributes, parameters: Mapping[str, str]) -> bool:
        for name, value in parameters.items():
            if not name.startswith("filter["):
                continue
            key = name[len("filter[") : -1]
            if key == "underlying_symbol" and self._underlying(str(row["contract"])) != value:
                return False
            if key == "contract" and row["contract"] != value:
                return False
            if key == "type" and row["type"] != value:
                return False
            for field_name in ("exp_date", "tradetime"):
                text = row[field_name]
                if key == f"{field_name}_eq" and text != value:
                    return False
                if key == f"{field_name}_from" and (text is None or text < value):
                    return False
                if key == f"{field_name}_to" and (text is None or text > value):
                    return False
            strike = Decimal(str(row["strike"]))
            if key == "strike_eq" and strike != Decimal(value):
                return False
            if key == "strike_from" and strike < Decimal(value):
                return False
            if key == "strike_to" and strike > Decimal(value):
                return False
        return True

    def client(self, budget: int | None = None, sleep: Sleeps | None = None) -> EodhdClient:
        return EodhdClient(CANARY, fetch=self, sleep=sleep or Sleeps(), clock=lambda: NOW, budget=budget)
