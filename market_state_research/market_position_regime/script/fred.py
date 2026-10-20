"""FRED's observations of the Fed's market value of US corporate equities: the raw file and its rules.

The Federal Reserve's Financial Accounts of the United States (Z.1) value the corporate
equities US corporations have issued at the end of each quarter; FRED, the St. Louis Fed's
data service, serves them through its API under the user's own key (``client``). The
market value is the sum of two series (``SERIES``), both in millions of US dollars,
quarterly, end of period, not seasonally adjusted: ``NCBEILQ027S``, nonfinancial corporate
business, corporate equities, liability (the Fed's FL103164105: public and closely held
corporations), and ``BOGZ1LM793164105Q``, domestic financial sectors, corporate equities,
liability, at market value (the Fed's LM793164105). FRED dates a quarter's value by the
quarter's first day (``2026-04-01`` is the value as of 2026-06-30) and writes a missing
value as ``.``.

``observations_url`` asks for a series' whole history as JSON. ``fetch`` writes an answer to
``raw/market/fred_{SERIES}_{TOKEN}.json``: one JSON object with exactly the keys ``series``,
``request`` (the URL without the key), ``fetched_at`` (New York ISO time with its offset;
``TOKEN`` names it to the second) and ``response``, FRED's answer as it came. Every read
checks every rule again (``check_answer``): the keys and forms; the series one of
``SERIES`` and the request its URL; the name against the series and the time; a time not
after the clock and after the newest quarter's end; FRED's answer with exactly its keys, in
linear units, ordered by date ascending, counted and not cut; at least one observation; each
with exactly its four keys, dated a quarter's first day, consecutive quarters ascending, its
value a non-negative decimal or ``.``.
"""

import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Final

from market_state_research.common.text import printable
from market_state_research.common.times import TOKEN_PATTERN, et_isoformat, timestamp_token, to_eastern

from .periods import Month, quarter_end_at

HOST: Final = "api.stlouisfed.org"
ENDPOINT: Final = f"https://{HOST}/fred/series/observations"
NONFINANCIAL: Final = "NCBEILQ027S"
FINANCIAL: Final = "BOGZ1LM793164105Q"
SERIES: Final = (NONFINANCIAL, FINANCIAL)
MISSING: Final = "."
RAW_NAME: Final = re.compile(
    rf"fred_(?P<series>{'|'.join(SERIES)})_(?P<token>{TOKEN_PATTERN})(?:_[0-9]+)?\.json", re.ASCII
)
MAX_SUFFIX: Final = 99

_KEYS: Final = ("series", "request", "fetched_at", "response")
_RESPONSE_KEYS: Final = frozenset(
    {
        "realtime_start",
        "realtime_end",
        "observation_start",
        "observation_end",
        "units",
        "output_type",
        "file_type",
        "order_by",
        "sort_order",
        "count",
        "offset",
        "limit",
        "observations",
    }
)
# What FRED answers a request that names only the series and the JSON file type.
_DEFAULTS: Final = {
    "observation_start": "1600-01-01",
    "observation_end": "9999-12-31",
    "units": "lin",
    "output_type": 1,
    "file_type": "json",
    "order_by": "observation_date",
    "sort_order": "asc",
    "offset": 0,
}
_OBSERVATION_KEYS: Final = ("realtime_start", "realtime_end", "date", "value")
_DAY = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", re.ASCII)
_VALUE = re.compile(r"(?:0|[1-9][0-9]{0,15})(?:\.[0-9]{1,6})?", re.ASCII)


@dataclass(frozen=True)
class Observation:
    """One quarter's value in $ millions as FRED wrote it, or None where FRED writes ``.``."""

    quarter_end: date
    value: Decimal | None
    text: str


@dataclass(frozen=True)
class Series:
    """One valid answer of a series: when it arrived and its observations, ascending."""

    series: str
    request: str
    fetched_at: datetime
    response: dict[str, object]
    observations: tuple[Observation, ...]

    def by_quarter_end(self) -> dict[date, Observation]:
        return {item.quarter_end: item for item in self.observations}

    def content(self) -> tuple[tuple[date, str], ...]:
        """What a newer answer is compared by: each quarter's value as written (FRED's realtime
        dates change every day and are left out)."""
        return tuple((item.quarter_end, item.text) for item in self.observations)


def observations_url(series: str) -> str:
    """The key-free URL of ``series``'s whole history as JSON."""
    if series not in SERIES:
        raise ValueError(f"the domain reads only the series {', '.join(SERIES)}")
    return f"{ENDPOINT}?series_id={series}&file_type=json"


def raw_name(series: str, fetched_at: datetime, suffix: str = "") -> str:
    """The name of an answer of ``series`` fetched at ``fetched_at``; ``suffix`` is ``""`` or ``_N``."""
    return f"fred_{series}_{timestamp_token(fetched_at)}{suffix}.json"


def _day(value: object, name: str) -> date:
    if not isinstance(value, str) or not _DAY.fullmatch(value):
        raise ValueError(f"{name} must be a YYYY-MM-DD date")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ValueError(f"{name} must be a YYYY-MM-DD date that exists") from None


def _observation(item: object, number: int) -> Observation:
    where = f"observation {number}"
    if not isinstance(item, dict) or tuple(item) != _OBSERVATION_KEYS:
        raise ValueError(f"{where} must hold exactly the keys {', '.join(_OBSERVATION_KEYS)}, in that order")
    for key in ("realtime_start", "realtime_end"):
        _day(item[key], f"{where}: {key}")
    day = _day(item["date"], f"{where}: date")
    try:
        quarter_end = quarter_end_at(day)
    except ValueError:
        raise ValueError(f"{where} is dated {day}, not the first day of a quarter") from None
    text = item["value"]
    if not isinstance(text, str) or not (text == MISSING or _VALUE.fullmatch(text)):
        shown = printable(str(text))
        raise ValueError(f"{where}: the value must be a non-negative decimal or '.', got {shown!r}")
    return Observation(quarter_end, None if text == MISSING else Decimal(text), text)


def check_response(value: object) -> tuple[Observation, ...]:
    """The observations of FRED's answer ``value``; every rule on the answer, one ``ValueError``
    line each."""
    if not isinstance(value, dict) or set(value) != _RESPONSE_KEYS:
        raise ValueError("the answer is not FRED's series observations (its keys differ)")
    for key, expected in _DEFAULTS.items():
        if value[key] != expected or type(value[key]) is not type(expected):
            raise ValueError(f"FRED's {key} must be {expected!r}, got {printable(repr(value[key]))}")
    items = value["observations"]
    if not isinstance(items, list) or not items:
        raise ValueError("FRED's answer holds no observation")
    count, limit = value["count"], value["limit"]
    if type(count) is not int or count != len(items):
        raise ValueError(f"FRED counts {printable(repr(count))} observations but sent {len(items)}")
    if type(limit) is not int or count > limit:
        raise ValueError("FRED's answer is cut at its limit")
    observations = tuple(_observation(item, number) for number, item in enumerate(items, start=1))
    for number in range(1, len(observations)):
        before, after = observations[number - 1].quarter_end, observations[number].quarter_end
        if Month.of(after) != Month.of(before).shifted(3):
            raise ValueError(f"observation {number + 1} does not follow the quarter of {before}")
    return observations


def parse_response(data: bytes) -> dict[str, object]:
    """FRED's answer ``data`` as a JSON object; ``check_answer`` checks it."""
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError):
        raise ValueError("the answer is not FRED's JSON") from None
    if not isinstance(value, dict):
        raise ValueError("the answer is not FRED's series observations (a JSON object)")
    return value


def check_answer(value: object, name: str | None, now: datetime) -> Series:
    """``value`` as a valid ``Series`` named ``name`` (None: not named yet); every problem raises
    one ``ValueError`` line."""
    if not isinstance(value, dict):
        raise ValueError("a FRED answer file must hold one JSON object")
    if tuple(value) != _KEYS:
        raise ValueError(f"the keys must be exactly {', '.join(_KEYS)}, in that order")
    series = value["series"]
    if series not in SERIES:
        raise ValueError(f"series must be one of {', '.join(SERIES)}")
    if value["request"] != observations_url(series):
        raise ValueError(f"request must be {observations_url(series)}")
    fetched_text = value["fetched_at"]
    try:
        fetched_at = to_eastern(datetime.fromisoformat(fetched_text), "fetched_at")
    except (TypeError, ValueError):
        raise ValueError("fetched_at must be an ISO time with an offset") from None
    if et_isoformat(fetched_at) != fetched_text:
        raise ValueError("fetched_at must be written in New York time with its offset")
    if name is not None:
        match = RAW_NAME.fullmatch(name)
        if match is None or match["series"] != series or match["token"] != timestamp_token(fetched_at):
            raise ValueError(f"the name must be {raw_name(series, fetched_at)} (or end _N.json)")
    if fetched_at > to_eastern(now, "now"):
        raise ValueError(f"fetched_at {et_isoformat(fetched_at)} is later than the current time")
    response = value["response"]
    observations = check_response(response)
    if fetched_at.date() <= observations[-1].quarter_end:
        raise ValueError(
            f"fetched at {et_isoformat(fetched_at)}, before the newest quarter, "
            f"{observations[-1].quarter_end}, ended"
        )
    return Series(series, value["request"], fetched_at, response, observations)


def dump(item: Series) -> bytes:
    """The bytes ``fetch`` writes: compact ASCII JSON, FRED's answer as it came."""
    value = {
        "series": item.series,
        "request": item.request,
        "fetched_at": et_isoformat(item.fetched_at),
        "response": item.response,
    }
    return json.dumps(value, ensure_ascii=True, allow_nan=False, separators=(",", ":")).encode("ascii")


def read_answer(data: bytes, name: str, now: datetime) -> Series:
    """Validate one raw FRED file's bytes; every problem raises a one-line ``ValueError``."""
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError):
        raise ValueError("not a JSON document") from None
    return check_answer(value, name, now)
