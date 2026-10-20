"""Raw files: reading and validation, selection, derivation and the CSV.

``fetch`` writes each ticker-session's chain (``chain``) and the ticker's daily prices
(``prices``) to ``raw/{TICKER}/``. Every read validates every listed raw file of the
ticker; a file that fails is reported, never skipped silently, until it is renamed with
``.rejected``, after which every read skips it. Per session, the newest valid chain (by
``fetched_at``, then by name) is the session's chain; a session without one is not
fetched. The newest valid prices file is the ticker's prices; older ones are validated and
never read. After validation a chain keeps in memory only what the derivation reads, the
rows of its two bracket expiries and of any expiry passed over before them, however many
expiries its file holds.

``derive`` gives each fetched session its row: the 14-DTE values (``surface``), the
percentiles of the skew and the ATM IV over the ``percentile.WINDOW`` sessions ending with
it, the stock's daily return (``prices``), and the correlations of the return with the
changes of the 14-DTE 25Δ call and put IVs over the ``correlation.WINDOW`` sessions ending
with it (``correlation``), so a row rests on the whole archive, not only on a report's
window. ``formatted/{TICKER}/volatility.csv`` holds every fetched session in date order,
with every value the percentiles and correlations rest on, and is rewritten from ``raw/``
by ``record``. ``SERIES`` names the six series of a row that a report states, each with its
label, its value and the reason it is blank.
"""

import csv
import io
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import date, datetime
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from typing import Final, Literal

from market_state_research.common.layout import DataLayout, listed, write_file
from market_state_research.common.sessions import previous_session, session_window
from market_state_research.common.times import et_isoformat

from . import chain, prices
from .chain import Chain, read_chain
from .correlation import correlation, iv_change
from .percentile import WINDOW, Percentile, percentile
from .prices import Bar, Prices, daily_return, read_prices
from .surface import HORIZON, ExpiryReading, Surface, Target, Value, rounded, surface

DATA_DIRECTORY = Path(__file__).resolve().parent.parent / "data"
CSV_NAME = "volatility.csv"
RAW_NAMES = "chain_DATE_TOKEN.json.gz or prices_DATE_TOKEN.json.gz"
CALL_LABEL = f"{HORIZON}-DTE call IV"
PUT_LABEL = f"{HORIZON}-DTE put IV"
_BRACKET_COLUMNS = (
    "expiry_{k}",
    "days_to_expiry_{k}",
    "call25_iv_{k}_pct",
    "put25_iv_{k}_pct",
    "call50_iv_{k}_pct",
    "put50_iv_{k}_pct",
    "skew_{k}_pp",
    "atm_iv_{k}_pct",
)
CSV_COLUMNS = (
    "date",
    "skew_14d_pp",
    "atm_iv_14d_pct",
    "skew_14d_percentile",
    "atm_iv_14d_percentile",
    "call25_iv_14d_pct",
    "put25_iv_14d_pct",
    "daily_return_pct",
    "call25_corr_15s",
    "put25_corr_15s",
    "method",
    *(column.format(k=1) for column in _BRACKET_COLUMNS),
    *(column.format(k=2) for column in _BRACKET_COLUMNS),
    "skipped_expiries",
    "skew_window_n",
    "atm_window_n",
    "adj_close",
    "previous_adj_close",
    "fetched_at",
    "source",
    "price_source",
)
_POINTS: tuple[Target, ...] = ("call25", "put25", "call50", "put50")


@dataclass(frozen=True)
class Capture:
    """One valid chain file: its chain, kept in memory with the rows of the expiries its
    values read only (``trimmed``), and its name."""

    chain: Chain
    source: str

    @property
    def date(self) -> date:
        return self.chain.session


@dataclass(frozen=True)
class PriceFile:
    """One valid prices file and its name."""

    prices: Prices
    source: str


@dataclass(frozen=True)
class InvalidFile:
    path: Path
    reason: str


@dataclass(frozen=True)
class Raw:
    """Every listed raw file of a ticker, validated: the chains, the prices files and the invalid files."""

    captures: tuple[Capture, ...]
    prices: tuple[PriceFile, ...]
    invalid: tuple[InvalidFile, ...]


@dataclass(frozen=True)
class Row:
    """One fetched session: its chain, its 14-DTE values, their percentiles, the stock's bars
    and daily return, and the two correlations."""

    capture: Capture
    surface: Surface
    skew_percentile: Percentile
    atm_percentile: Percentile
    bar: Bar | None
    previous_bar: Bar | None
    daily_return: Value
    call25_correlation: Value
    put25_correlation: Value
    price_source: str | None

    @property
    def date(self) -> date:
        return self.capture.date

    @property
    def fetched_at(self) -> datetime:
        return self.capture.chain.fetched_at

    @property
    def source(self) -> str:
        return self.capture.source


Series = Literal[
    "skew_14d_percentile",
    "atm_iv_14d_percentile",
    "skew_14d_pp",
    "atm_iv_14d_pct",
    "call25_corr_15s",
    "put25_corr_15s",
]
SERIES: Final[tuple[Series, ...]] = (
    "skew_14d_percentile",
    "atm_iv_14d_percentile",
    "skew_14d_pp",
    "atm_iv_14d_pct",
    "call25_corr_15s",
    "put25_corr_15s",
)
LABELS: Final[Mapping[Series, str]] = {
    "skew_14d_percentile": "skew percentile",
    "atm_iv_14d_percentile": "ATM IV percentile",
    "skew_14d_pp": "14-DTE skew",
    "atm_iv_14d_pct": "14-DTE ATM IV",
    "call25_corr_15s": "return–call IV correlation",
    "put25_corr_15s": "return–put IV correlation",
}
VALUES: Final[Mapping[Series, Callable[[Row], Decimal | None]]] = {
    "skew_14d_percentile": lambda row: row.skew_percentile.value,
    "atm_iv_14d_percentile": lambda row: row.atm_percentile.value,
    "skew_14d_pp": lambda row: row.surface.skew.value,
    "atm_iv_14d_pct": lambda row: row.surface.atm.value,
    "call25_corr_15s": lambda row: row.call25_correlation.value,
    "put25_corr_15s": lambda row: row.put25_correlation.value,
}
REASONS: Final[Mapping[Series, Callable[[Row], str | None]]] = {
    "skew_14d_percentile": lambda row: row.skew_percentile.reason,
    "atm_iv_14d_percentile": lambda row: row.atm_percentile.reason,
    "skew_14d_pp": lambda row: row.surface.skew.reason,
    "atm_iv_14d_pct": lambda row: row.surface.atm.reason,
    "call25_corr_15s": lambda row: row.call25_correlation.reason,
    "put25_corr_15s": lambda row: row.put25_correlation.reason,
}


def csv_path(layout: DataLayout, ticker: str) -> Path:
    return layout.formatted(ticker) / CSV_NAME


def trimmed(item: Chain) -> Chain:
    """``item`` with the rows and traded records of the expiries its values read only (its
    brackets and the expiries passed over before them), from which ``surface`` gives the same
    values as from the whole chain."""
    kept = set(surface(item.session, item.listed, item.rows).read)
    return replace(
        item,
        rows=tuple(row for row in item.rows if row.expiry in kept),
        traded=None if item.traded is None else tuple(row for row in item.traded if row.expiry in kept),
    )


def read_raw(layout: DataLayout, ticker: str, now: datetime) -> Raw:
    """Every listed raw file of ``ticker``, validated (see the module docstring)."""
    captures: list[Capture] = []
    found: list[PriceFile] = []
    invalid: list[InvalidFile] = []
    for path in listed(layout.raw(ticker)):
        try:
            if chain.RAW_NAME.fullmatch(path.name):
                captures.append(
                    Capture(trimmed(read_chain(path.read_bytes(), ticker, path.name, now)), path.name)
                )
            elif prices.RAW_NAME.fullmatch(path.name):
                found.append(PriceFile(read_prices(path.read_bytes(), ticker, path.name, now), path.name))
            else:
                invalid.append(InvalidFile(path, f"not a raw file name ({RAW_NAMES})"))
        except ValueError as error:
            invalid.append(InvalidFile(path, str(error)))
    return Raw(tuple(captures), tuple(found), tuple(invalid))


def select(captures: Iterable[Capture]) -> dict[date, Capture]:
    """Per session, its newest capture (by ``fetched_at``, then by name), by date."""
    sessions: dict[date, Capture] = {}
    for capture in sorted(captures, key=lambda item: (item.chain.fetched_at, item.source)):
        sessions[capture.date] = capture  # ascending: the newest wins
    return dict(sorted(sessions.items()))


def select_prices(files: Iterable[PriceFile]) -> PriceFile | None:
    """The newest prices file (by ``fetched_at``, then by name), or None."""
    return max(files, key=lambda item: (item.prices.fetched_at, item.source), default=None)


def derive(sessions: Mapping[date, Capture], prices_file: PriceFile | None = None) -> dict[date, Row]:
    """Each fetched session's row, by date (see the module docstring)."""
    surfaces = {
        day: surface(day, capture.chain.listed, capture.chain.rows)
        for day, capture in sorted(sessions.items())
    }
    skews = {day: item.skew.value for day, item in surfaces.items() if item.skew.value is not None}
    atms = {day: item.atm.value for day, item in surfaces.items() if item.atm.value is not None}
    found = None if prices_file is None else prices_file.prices
    returns = {day: daily_return(found, day) for day in surfaces}
    calls = {day: item.call25.value for day, item in surfaces.items()}
    puts = {day: item.put25.value for day, item in surfaces.items()}
    call_changes = {day: iv_change(calls, day, CALL_LABEL) for day in surfaces}
    put_changes = {day: iv_change(puts, day, PUT_LABEL) for day in surfaces}

    def fetched(day: date) -> bool:
        return day in sessions

    rows: dict[date, Row] = {}
    for day, item in surfaces.items():
        window = session_window(day, WINDOW)
        rows[day] = Row(
            capture=sessions[day],
            surface=item,
            skew_percentile=percentile(window, fetched, skews),
            atm_percentile=percentile(window, fetched, atms),
            bar=None if found is None else found.bar(day),
            previous_bar=None if found is None else found.bar(previous_session(day)),
            daily_return=returns[day],
            call25_correlation=correlation(day, fetched, returns, call_changes, CALL_LABEL),
            put25_correlation=correlation(day, fetched, returns, put_changes, PUT_LABEL),
            price_source=None if prices_file is None else prices_file.source,
        )
    return rows


def _text(value: Decimal | None) -> str:
    return "" if value is None else str(value)


def _percent(value: Fraction | None) -> str:
    return "" if value is None else str(rounded(value * 100))


def _adjusted(bar: Bar | None) -> str:
    return "" if bar is None else bar.values["adjClose"]


def _reading_cells(reading: ExpiryReading | None) -> list[str]:
    if reading is None:
        return [""] * len(_BRACKET_COLUMNS)
    skew, atm = reading.skew, reading.atm
    return [
        reading.expiry.isoformat(),
        str(reading.days),
        *(_percent(reading.points[target].iv) for target in _POINTS),
        "" if skew is None else str(rounded(skew)),
        "" if atm is None else str(rounded(atm)),
    ]


def csv_text(rows: Iterable[Row]) -> str:
    """The CSV of ``rows`` in the given order: rounded decimals, Tiingo's adjusted closes as it
    wrote them, New York ISO times."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(CSV_COLUMNS)
    for row in rows:
        item = row.surface
        readings = list(item.readings) + [None] * (2 - len(item.readings))
        writer.writerow(
            [
                row.date.isoformat(),
                _text(item.skew.value),
                _text(item.atm.value),
                _text(row.skew_percentile.value),
                _text(row.atm_percentile.value),
                _text(item.call25.value),
                _text(item.put25.value),
                _text(row.daily_return.value),
                _text(row.call25_correlation.value),
                _text(row.put25_correlation.value),
                item.method,
                *_reading_cells(readings[0]),
                *_reading_cells(readings[1]),
                " ".join(reading.expiry.isoformat() for reading in item.skipped),
                "" if row.skew_percentile.value is None else str(row.skew_percentile.n),
                "" if row.atm_percentile.value is None else str(row.atm_percentile.n),
                _adjusted(row.bar),
                _adjusted(row.previous_bar),
                et_isoformat(row.fetched_at),
                row.source,
                row.price_source or "",
            ]
        )
    return buffer.getvalue()


def write_csv(path: Path, rows: Iterable[Row]) -> bool:
    """Write the CSV of ``rows`` unless ``path`` already holds exactly it; whether it wrote."""
    data = csv_text(rows).encode("utf-8")
    if path.is_file() and path.read_bytes() == data:
        return False
    write_file(path, data, overwrite=True)
    return True
