"""Raw files: reading and validation, selection, derivation and the CSV.

``fetch`` writes each ticker-session's chain (``chain``) and the ticker's daily prices
(``prices``) to ``raw/{TICKER}/``. Every read validates every listed raw file of the
ticker; a file that fails is reported, never skipped silently, until it is renamed with
``.rejected``, after which every read skips it. Per session, the newest valid chain (by
``fetched_at``, then by name) is the session's chain; a session without one is not
fetched. The newest valid prices file is the ticker's prices; older ones are validated and
never read. After validation a chain keeps in memory only what the derivation reads, the
rows of the expiries its levels rest on at either horizon (its brackets and any expiry
passed over before them), however many expiries its file holds.

``derive`` gives each fetched session its row: its levels at 14 and 30 days (``surface``);
the indicators computed from those rounded levels (``indicators``), the 14-DTE skew and ATM
IV, the 30-DTE ATM IV and the term structure; the percentiles of the skew, the 14-DTE ATM IV
and the term structure over the ``percentile.WINDOW`` sessions ending with it; the stock's
daily return (``prices``); and the correlations of the return with the changes of the
14-DTE 25Δ call and put IVs over the ``correlation.WINDOW`` sessions ending with it
(``correlation``), so a row rests on the whole archive, not only on a report's window.
``formatted/{TICKER}/volatility.csv`` caches every fetched session's levels in date order,
and nothing derived from them: the closes, the seven IV levels, the bracket expiries and the
sources, from which every indicator, percentile, return and correlation is computed again.
``record`` rewrites it from ``raw/``. ``SERIES`` names the nine series of a row that a
report states, each with its label, its value and the reason it is blank.
"""

import csv
import io
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import date, datetime
from decimal import Decimal
from functools import partial
from pathlib import Path
from typing import Final, Literal

from market_state_research.common.layout import DataLayout, listed, write_file
from market_state_research.common.sessions import previous_session, session_window
from market_state_research.common.times import et_isoformat

from . import chain, indicators, prices
from .chain import Chain, read_chain
from .correlation import correlation, iv_change
from .percentile import WINDOW, Percentile, percentile
from .prices import Bar, Prices, daily_return, read_prices
from .surface import HORIZON, HORIZONS, REQUIRED, TERM_HORIZON, Surface, Value, surface

DATA_DIRECTORY = Path(__file__).resolve().parent.parent / "data"
CSV_NAME = "volatility.csv"
RAW_NAMES = "chain_DATE_TOKEN.json.gz or prices_DATE_TOKEN.json.gz"
CALL_LABEL = f"{HORIZON}-DTE call IV"
PUT_LABEL = f"{HORIZON}-DTE put IV"
CSV_COLUMNS = (
    "date",
    "close",
    "adj_close",
    "previous_adj_close",
    *(f"{target}_iv_{HORIZON}d_pct" for target in REQUIRED[HORIZON]),
    *(f"{target}_iv_{TERM_HORIZON}d_pct" for target in REQUIRED[TERM_HORIZON]),
    f"expiry_{HORIZON}d_1",
    f"expiry_{HORIZON}d_2",
    f"skipped_{HORIZON}d",
    f"expiry_{TERM_HORIZON}d_1",
    f"expiry_{TERM_HORIZON}d_2",
    f"skipped_{TERM_HORIZON}d",
    "fetched_at",
    "source",
    "price_source",
)


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
    """One fetched session: its chain, its levels at 14 days (``near``) and at 30 (``far``),
    the indicators computed from them and their percentiles, the stock's bars and daily
    return, and the two correlations."""

    capture: Capture
    near: Surface
    far: Surface
    skew: Value
    atm: Value
    far_atm: Value
    term: Value
    skew_percentile: Percentile
    atm_percentile: Percentile
    term_percentile: Percentile
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

    @property
    def detail(self) -> str:
        """One line for people: how each horizon's levels were read, or why there are none."""
        return f"{self.near.detail()}; {self.far.detail()}"


Series = Literal[
    "skew_14d_percentile",
    "atm_iv_14d_percentile",
    "term_structure_percentile",
    "skew_14d_pp",
    "atm_iv_14d_pct",
    "atm_iv_30d_pct",
    "term_structure_pp",
    "call25_corr_15s",
    "put25_corr_15s",
]
SERIES: Final[tuple[Series, ...]] = (
    "skew_14d_percentile",
    "atm_iv_14d_percentile",
    "term_structure_percentile",
    "skew_14d_pp",
    "atm_iv_14d_pct",
    "atm_iv_30d_pct",
    "term_structure_pp",
    "call25_corr_15s",
    "put25_corr_15s",
)
LABELS: Final[Mapping[Series, str]] = {
    "skew_14d_percentile": "skew percentile",
    "atm_iv_14d_percentile": "ATM IV percentile",
    "term_structure_percentile": "term structure percentile",
    "skew_14d_pp": "14-DTE skew",
    "atm_iv_14d_pct": "14-DTE ATM IV",
    "atm_iv_30d_pct": "30-DTE ATM IV",
    "term_structure_pp": "term structure",
    "call25_corr_15s": "return–call IV correlation",
    "put25_corr_15s": "return–put IV correlation",
}
# The percentile series, each with the percentile it states.
PERCENTILES: Final[Mapping[Series, Callable[[Row], Percentile]]] = {
    "skew_14d_percentile": lambda row: row.skew_percentile,
    "atm_iv_14d_percentile": lambda row: row.atm_percentile,
    "term_structure_percentile": lambda row: row.term_percentile,
}
_OTHERS: Final[Mapping[Series, Callable[[Row], Value]]] = {
    "skew_14d_pp": lambda row: row.skew,
    "atm_iv_14d_pct": lambda row: row.atm,
    "atm_iv_30d_pct": lambda row: row.far_atm,
    "term_structure_pp": lambda row: row.term,
    "call25_corr_15s": lambda row: row.call25_correlation,
    "put25_corr_15s": lambda row: row.put25_correlation,
}


def _value(series: Series, row: Row) -> Decimal | None:
    return PERCENTILES[series](row).value if series in PERCENTILES else _OTHERS[series](row).value


def _reason(series: Series, row: Row) -> str | None:
    return PERCENTILES[series](row).reason if series in PERCENTILES else _OTHERS[series](row).reason


VALUES: Final[Mapping[Series, Callable[[Row], Decimal | None]]] = {
    series: partial(_value, series) for series in SERIES
}
REASONS: Final[Mapping[Series, Callable[[Row], str | None]]] = {
    series: partial(_reason, series) for series in SERIES
}


def csv_path(layout: DataLayout, ticker: str) -> Path:
    return layout.formatted(ticker) / CSV_NAME


def trimmed(item: Chain) -> Chain:
    """``item`` with the rows and traded records of the expiries its levels read only (at each
    horizon, its brackets and the expiries passed over before them), from which ``surface``
    gives the same levels as from the whole chain."""
    kept = {
        expiry
        for horizon in HORIZONS
        for expiry in surface(item.session, item.listed, item.rows, horizon).read
    }
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


def _valued(values: Mapping[date, Value]) -> dict[date, Decimal]:
    """The sessions of ``values`` that have a value, with it."""
    return {day: item.value for day, item in values.items() if item.value is not None}


def derive(sessions: Mapping[date, Capture], prices_file: PriceFile | None = None) -> dict[date, Row]:
    """Each fetched session's row, by date (see the module docstring)."""
    ordered = sorted(sessions.items())
    near = {day: surface(day, capture.chain.listed, capture.chain.rows, HORIZON) for day, capture in ordered}
    far = {
        day: surface(day, capture.chain.listed, capture.chain.rows, TERM_HORIZON) for day, capture in ordered
    }
    skews = {day: indicators.skew(item) for day, item in near.items()}
    atms = {day: indicators.atm(item) for day, item in near.items()}
    far_atms = {day: indicators.atm(item) for day, item in far.items()}
    terms = {day: indicators.term(near[day], far[day]) for day in near}
    found = None if prices_file is None else prices_file.prices
    returns = {day: daily_return(found, day) for day in near}
    calls = {day: item.level("call25").value for day, item in near.items()}
    puts = {day: item.level("put25").value for day, item in near.items()}
    call_changes = {day: iv_change(calls, day, CALL_LABEL) for day in near}
    put_changes = {day: iv_change(puts, day, PUT_LABEL) for day in near}
    ranked = {"skew": _valued(skews), "atm": _valued(atms), "term": _valued(terms)}

    def fetched(day: date) -> bool:
        return day in sessions

    rows: dict[date, Row] = {}
    for day in near:
        window = session_window(day, WINDOW)
        rows[day] = Row(
            capture=sessions[day],
            near=near[day],
            far=far[day],
            skew=skews[day],
            atm=atms[day],
            far_atm=far_atms[day],
            term=terms[day],
            skew_percentile=percentile(window, fetched, ranked["skew"]),
            atm_percentile=percentile(window, fetched, ranked["atm"]),
            term_percentile=percentile(window, fetched, ranked["term"]),
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


def _bar_text(bar: Bar | None, name: str) -> str:
    return "" if bar is None else bar.values[name]


def _brackets(item: Surface) -> list[str]:
    """The bracket expiries (the second blank for ``exact``, both for ``none``) and the expiries
    skipped, separated by spaces."""
    expiries = [expiry.isoformat() for expiry in item.expiries]
    return [
        *expiries,
        *[""] * (2 - len(expiries)),
        " ".join(reading.expiry.isoformat() for reading in item.skipped),
    ]


def csv_text(rows: Iterable[Row]) -> str:
    """The CSV of ``rows`` in the given order, levels only: Tiingo's closes as it wrote them, the
    rounded IV levels, the bracket expiries, New York ISO times and the sources."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(CSV_COLUMNS)
    for row in rows:
        writer.writerow(
            [
                row.date.isoformat(),
                _bar_text(row.bar, "close"),
                _bar_text(row.bar, "adjClose"),
                _bar_text(row.previous_bar, "adjClose"),
                *(_text(row.near.level(target).value) for target in row.near.targets),
                *(_text(row.far.level(target).value) for target in row.far.targets),
                *_brackets(row.near),
                *_brackets(row.far),
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
