"""The report of one window: a self-contained interactive HTML chart and its Markdown twin.

``render_html`` is a pure function of a ``ChartSpec`` and the vendored library and page
template (``templates/chart.html``, read with the library by ``load_library``): the same
inputs always produce the same text. The pinned library (``common.chart``) is inlined so a
chart opens offline and from ``file://`` indefinitely. The time series is embedded as JSON,
which the page's own script draws (nothing reads it back), and repeated as a static data
table. Everything the page shows beyond plotting is computed
here: each session's readout line (each horizon's method and bracket expiries, or why it has
no level), the readings at each bracket expiry and the strikes they were read at, the 14-DTE
call and put IVs, the daily return and the adjusted close, and the table's header, so the page only plots
numbers and text that Python produced and tests checked. The page draws two charts on one
time axis, always together, each over the adjusted close: the three percentiles (``CHARTED``)
and the two correlations. ``render_markdown`` writes the same window, coverage and gaps as
Markdown. Times are New York time: ISO text with its EDT/EST offset in the data, and the
generation time to the second with its zone in the headers.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Final

from market_state_research.common import chart as common_chart
from market_state_research.common.chart import (
    LIBRARY_NAME,
    LIBRARY_VERSION,
    Library,
    embed_json,
    escape,
    substitute,
)
from market_state_research.common.sessions import session_window
from market_state_research.common.times import et_display, et_isoformat

from .chain import WINDOW_DAYS
from .correlation import WINDOW as CORRELATION_WINDOW
from .percentile import WINDOW
from .prices import RETURN_PLACES
from .store import LABELS, PERCENTILES, REASONS, SERIES, VALUES, Row, Series
from .surface import HORIZON, TERM_HORIZON, ExpiryReading, Surface, Target, rounded

TEMPLATE_PATH = Path(__file__).resolve().parent / "templates" / "chart.html"
SOURCE_DESCRIPTION = (
    'EODHD "US Stock Options Data" (UnicornBay) · end-of-day option chains · every contract of every '
    f"expiry within {WINDOW_DAYS} days · Tiingo end-of-day prices (adjusted close)"
)
METHOD = (
    "At each expiry, the implied volatility at a target delta is read from the usable contracts of one "
    "type (IV above 0, a delta, an ask above 0), from in the money to out of the money: the IV of the "
    "first contract at that delta, or else interpolated linearly in delta between the first adjacent pair "
    f"on either side of it; nothing is extrapolated. The levels at {HORIZON} days are the call IVs at "
    f"+0.25Δ and +0.50Δ and the put IVs at −0.25Δ and −0.50Δ, and those at {TERM_HORIZON} days the call "
    "IV at +0.50Δ and the put IV at −0.50Δ (%). A horizon's levels are read at the last listed expiry 1 to "
    f"H calendar days out and the first one H or more days out (within {WINDOW_DAYS}) that give every "
    "reading of the horizon, an expiry without them being skipped and named, interpolated linearly in "
    "calendar days between the two, or at an expiry exactly H days out (exact); a session without both "
    "has none. Each level is computed exactly and rounded half-even once to two decimal places, and the "
    "indicators are computed exactly from the rounded levels and rounded half-even once to two decimal "
    f"places: the {HORIZON}-DTE 25Δ skew is the put IV at −0.25Δ minus the call IV at +0.25Δ (pp); an "
    "ATM IV is the mean of the call IV at +0.50Δ and the put IV at −0.50Δ (%); the term structure is the "
    f"{TERM_HORIZON}-DTE ATM IV minus the {HORIZON}-DTE ATM IV (pp). A percentile is 100 times the share "
    f"of the other {WINDOW - 1} sessions of the {WINDOW} XNYS sessions ending with the session whose "
    "value is strictly below the session's, among those with a value (n), rounded half-even to one "
    f"decimal place; it needs every one of the {WINDOW} sessions fetched. The daily return is (the adjusted "
    "close ÷ the previous XNYS session's adjusted close − 1) × 100, both from the newest prices file "
    f"fetched from Tiingo, rounded half-even to {RETURN_PLACES} decimal places. A correlation is the "
    f"sample Pearson correlation, over the {CORRELATION_WINDOW} XNYS sessions ending with the session, of "
    f"the daily return with the change since the previous session of the rounded {HORIZON}-DTE 25Δ call "
    "(or put) IV, computed exactly and rounded half-even to two decimal places; it needs the "
    f"{CORRELATION_WINDOW + 1} sessions to the session fetched and all {CORRELATION_WINDOW} pairs."
)
TABLE_COLUMNS = (
    "Session",
    "Skew percentile (n)",
    "ATM IV percentile (n)",
    "Term structure percentile (n)",
    f"{HORIZON}-DTE 25Δ skew (pp, put − call)",
    f"{HORIZON}-DTE ATM IV (%)",
    f"{TERM_HORIZON}-DTE ATM IV (%)",
    f"Term structure (pp, {TERM_HORIZON}-DTE − {HORIZON}-DTE ATM IV)",
    f"Return–Δ call IV correlation ({CORRELATION_WINDOW}s)",
    f"Return–Δ put IV correlation ({CORRELATION_WINDOW}s)",
    f"{HORIZON}-DTE 25Δ call IV (%)",
    f"{HORIZON}-DTE 25Δ put IV (%)",
    "Daily return (%)",
    "Adjusted close",
    "Method · bracket readings",
    "Fetched (ET)",
    "Source",
)
READINGS_NOTE = (
    "The bracket readings name, for each horizon, the method, then each bracket expiry as expiry "
    f"(calendar days out) with its values and the strikes each IV was read at: at {HORIZON} days its 25Δ "
    "skew (pp) and ATM IV (%), with c25 and p25 at the call's +0.25Δ and the put's −0.25Δ and c50 and p50 "
    f"at +0.50Δ and −0.50Δ; at {TERM_HORIZON} days its ATM IV, with c50 and p50. One strike where a "
    "contract has the target delta, two where the IV is interpolated between them. An expiry nearer to the "
    "horizon that lacks a reading of it is skipped as a bracket, and named after the brackets with why."
)
GAPS_NOTE = "Fetched window sessions without a value, a percentile or a correlation, per series, and why."
NO_GAPS = "None: every fetched window session has every value, percentile and correlation."
NO_VALUE = "—"
POINT_NAMES: Final[Mapping[Target, str]] = {"call25": "c25", "put25": "p25", "call50": "c50", "put50": "p50"}
# The series the two charts draw, in the readout's order: the percentiles, then the correlations.
# The indicators the percentiles rank are in the data table only.
CHARTED: Final[tuple[Series, ...]] = (
    "skew_14d_percentile",
    "atm_iv_14d_percentile",
    "term_structure_percentile",
    "call25_corr_15s",
    "put25_corr_15s",
)


def load_library() -> Library:
    """The vendored library, its pinned checksum verified, and this domain's page template."""
    return common_chart.load_library(TEMPLATE_PATH)


@dataclass(frozen=True)
class Gap:
    """One window session's series without a value, and why."""

    date: date
    series: Series
    reason: str


@dataclass(frozen=True)
class ChartSpec:
    """One ticker's look-back window and the rows of its fetched sessions.

    ``csv`` names the formatted CSV the rows come from, relative to the data directory.
    """

    ticker: str
    as_of: date
    lookback: int
    window: tuple[date, ...]
    rows: tuple[Row, ...]
    generated_at: datetime
    csv: str

    def __post_init__(self) -> None:
        if session_window(self.as_of, self.lookback) != self.window:
            raise ValueError("chart window must be the `lookback` XNYS sessions ending at as_of")
        dates = [row.date for row in self.rows]
        if dates != sorted(set(dates)) or not set(dates) <= set(self.window):
            raise ValueError("chart rows must be unique, ascending and inside the window")
        if any(row.capture.chain.ticker != self.ticker for row in self.rows):
            raise ValueError("chart rows must belong to the chart's ticker")

    @property
    def missing(self) -> tuple[date, ...]:
        present = {row.date for row in self.rows}
        return tuple(session for session in self.window if session not in present)

    @property
    def prices(self) -> str | None:
        """The prices file every row's return rests on (one file serves them all), or None."""
        return self.rows[-1].price_source if self.rows else None

    @property
    def gaps(self) -> tuple[Gap, ...]:
        found = []
        for row in self.rows:
            for series in SERIES:
                if VALUES[series](row) is None:
                    found.append(Gap(row.date, series, REASONS[series](row) or ""))
        return tuple(found)


def _decimal(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def _reading_text(reading: ExpiryReading, targets: tuple[Target, ...]) -> str:
    strikes = ", ".join(
        f"{POINT_NAMES[target]} {reading.points[target].describe() or NO_VALUE}" for target in targets
    )
    skew, atm = reading.skew, reading.atm
    values = f"ATM {NO_VALUE if atm is None else rounded(atm)}"
    if "put25" in targets:
        values = f"skew {NO_VALUE if skew is None else rounded(skew)}, {values}"
    return f"{reading.label()}: {values} ({strikes})"


def _horizon_text(item: Surface) -> str:
    label = f"{item.horizon}-DTE"
    if item.method == "none":
        return f"{label}: none · {item.reason}"
    text = f"{label}: {item.method} · " + " → ".join(
        _reading_text(reading, item.targets) for reading in item.readings
    )
    if item.skipped:
        text += " · skipped " + "; ".join(reading.missing(item.targets) for reading in item.skipped)
    return text


def readings_text(row: Row) -> str:
    """Each horizon's method and bracket readings, for a table cell."""
    return f"{_horizon_text(row.near)}; {_horizon_text(row.far)}"


def _percentile_text(row: Row, series: Series) -> str:
    found = PERCENTILES[series](row)
    return NO_VALUE if found.value is None else f"{found.value} (n {found.n})"


def _n(row: Row, series: Series) -> int | None:
    found = PERCENTILES[series](row)
    return None if found.value is None else found.n


def payload(spec: ChartSpec, library_version: str = LIBRARY_VERSION) -> dict[str, Any]:
    """The JSON embedded in the chart; decimals stay strings."""
    return {
        "ticker": spec.ticker,
        "as_of": spec.as_of.isoformat(),
        "lookback": spec.lookback,
        "window_start": spec.window[0].isoformat(),
        "generated_at": et_isoformat(spec.generated_at),
        "csv": spec.csv,
        "method": METHOD,
        "missing_sessions": [session.isoformat() for session in spec.missing],
        "gaps": [
            {"date": gap.date.isoformat(), "series": gap.series, "reason": gap.reason} for gap in spec.gaps
        ],
        "library": f"{LIBRARY_NAME} {library_version}",
        "source": SOURCE_DESCRIPTION,
        "prices": spec.prices,
        "rows": [
            {
                "date": row.date.isoformat(),
                **{series: _decimal(VALUES[series](row)) for series in SERIES},
                "skew_window_n": _n(row, "skew_14d_percentile"),
                "atm_window_n": _n(row, "atm_iv_14d_percentile"),
                "term_window_n": _n(row, "term_structure_percentile"),
                "call25_iv_14d_pct": _decimal(row.near.level("call25").value),
                "put25_iv_14d_pct": _decimal(row.near.level("put25").value),
                "daily_return_pct": _decimal(row.daily_return.value),
                "adj_close": None if row.bar is None else row.bar.values["adjClose"],
                "method_14d": row.near.method,
                "method_30d": row.far.method,
                "detail": row.detail,
                "readings": readings_text(row),
                "fetched_at": et_isoformat(row.fetched_at),
                "source": row.source,
                "price_source": row.price_source,
            }
            for row in spec.rows
        ],
    }


def _value(row: Row, series: Series) -> str:
    if series in PERCENTILES:
        return _percentile_text(row, series)
    value = VALUES[series](row)
    return NO_VALUE if value is None else str(value)


def _text(value: Decimal | None) -> str:
    return NO_VALUE if value is None else str(value)


def _close(row: Row) -> str:
    """The adjusted close as Tiingo wrote it, or ``—``."""
    return NO_VALUE if row.bar is None else row.bar.values["adjClose"]


def _cells(row: Row) -> list[str]:
    """The cells of a row from each series to the adjusted close."""
    return [
        *(_value(row, series) for series in SERIES),
        _text(row.near.level("call25").value),
        _text(row.near.level("put25").value),
        _text(row.daily_return.value),
        _close(row),
    ]


def _readout(row: Row) -> tuple[str, ...]:
    """The readout's values, in the page's order: the charted series, the adjusted close and the
    daily return."""
    return (*(_value(row, series) for series in CHARTED), _close(row), _text(row.daily_return.value))


def _table_head() -> str:
    cells = "".join(f'<th scope="col">{escape(column)}</th>' for column in TABLE_COLUMNS)
    return f"<thead><tr>{cells}</tr></thead>"


def _table_rows(spec: ChartSpec) -> str:
    by_date = {row.date: row for row in spec.rows}
    lines = []
    for session in spec.window:
        row = by_date.get(session)
        if row is None:
            cells = [f'<td class="missing" colspan="{len(TABLE_COLUMNS) - 1}">missing</td>']
        else:
            values = _cells(row)
            cells = [f"<td>{escape(value)}</td>" for value in values]
            cells.append(f'<td class="reason">{escape(readings_text(row))}</td>')
            cells.append(f"<td>{escape(et_isoformat(row.fetched_at))}</td>")
            cells.append(f'<td class="reason">{escape(row.source)}</td>')
        lines.append(f'<tr><th scope="row">{escape(session.isoformat())}</th>{"".join(cells)}</tr>')
    return "\n".join(lines)


def _gap_rows(spec: ChartSpec) -> str:
    if not spec.gaps:
        return f'<p class="hint">{escape(NO_GAPS)}</p>'
    rows = "\n".join(
        f'<tr><th scope="row">{escape(gap.date.isoformat())}</th><td>{escape(LABELS[gap.series])}</td>'
        f'<td class="reason">{escape(gap.reason)}</td></tr>'
        for gap in spec.gaps
    )
    return (
        '<div class="table-wrap"><table class="gaps">'
        '<thead><tr><th scope="col">Session</th><th scope="col">Series</th>'
        '<th scope="col">Reason</th></tr></thead>'
        f"<tbody>\n{rows}\n</tbody></table></div>"
    )


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


def _banners(spec: ChartSpec) -> str:
    banners = []
    missing = spec.missing
    if missing:
        listed = ", ".join(session.isoformat() for session in missing)
        banners.append(
            '<p class="banner" role="status"><span class="banner-icon" aria-hidden="true">⚠</span> '
            f"<strong>Partial chart.</strong> {len(missing)} of {spec.lookback} sessions are missing: "
            f"{escape(listed)}.</p>"
        )
    # One clause per set of series missing together, in the order the gaps list them.
    by_session: dict[date, list[Series]] = {}
    for gap in spec.gaps:
        by_session.setdefault(gap.date, []).append(gap.series)
    groups: dict[tuple[Series, ...], list[date]] = {}
    for day, series in by_session.items():
        groups.setdefault(tuple(series), []).append(day)
    if groups:
        clauses = [
            f"no {_join_labels(series)} on {_plural(len(days), 'fetched session')}: "
            + ", ".join(day.isoformat() for day in days)
            for series, days in groups.items()
        ]
        banners.append(
            '<p class="banner" role="status"><span class="banner-icon" aria-hidden="true">⚠</span> '
            f"<strong>Gaps.</strong> {escape('; '.join(clauses))}. The gaps below the data table give each "
            "reason.</p>"
        )
    return "\n".join(banners)


def _join_labels(series: tuple[Series, ...]) -> str:
    labels = [LABELS[item] for item in series]
    return labels[0] if len(labels) == 1 else f"{', '.join(labels[:-1])} or {labels[-1]}"


def _coverage(spec: ChartSpec) -> str:
    return f"{len(spec.rows)} of {spec.lookback}"


def _title(spec: ChartSpec) -> str:
    return f"{spec.ticker} · implied volatility, {HORIZON} and {TERM_HORIZON} DTE · {spec.lookback} sessions"


def render_html(spec: ChartSpec, library: Library) -> str:
    """Render the complete, self-contained chart document."""
    if not spec.rows:
        raise ValueError("a chart needs at least one fetched session in its window")
    latest = spec.rows[-1]
    values = {
        "TITLE": escape(f"{_title(spec)} to {spec.as_of.isoformat()}"),
        "TICKER": escape(spec.ticker),
        "LOOKBACK": escape(spec.lookback),
        "WINDOW_START": escape(spec.window[0].isoformat()),
        "AS_OF": escape(spec.as_of.isoformat()),
        "GENERATED": escape(et_display(spec.generated_at)),
        "CSV": escape(spec.csv),
        "PRICES": escape(spec.prices or "none fetched"),
        "SOURCE": escape(SOURCE_DESCRIPTION),
        "METHOD": escape(METHOD),
        "LIBRARY_VERSION": escape(library.version),
        "NOTICE": escape(library.notice),
        "BANNERS": _banners(spec),
        "LATEST_DATE": escape(latest.date.isoformat()),
        "LATEST_DETAIL": escape(latest.detail),
        "COVERAGE": escape(_coverage(spec)),
        "TABLE_HEAD": _table_head(),
        "TABLE_ROWS": _table_rows(spec),
        "GAP_ROWS": _gap_rows(spec),
        "PAYLOAD": embed_json(payload(spec, library.version)),
        "LIBRARY": library.script,
    }
    for index, text in enumerate(_readout(latest)):
        values[f"LATEST_VALUE_{index}"] = escape(text)
    return substitute(library.template, values)


def _markdown_row(cells: list[object]) -> str:
    return "| " + " | ".join(str(cell).replace("|", "\\|") for cell in cells) + " |"


def render_markdown(spec: ChartSpec) -> str:
    """The window as Markdown: the method, coverage, one row per session (missing ones marked) and
    the gaps."""
    by_date = {row.date: row for row in spec.rows}
    lines = [
        f"# {_title(spec)} {spec.window[0].isoformat()} → {spec.as_of.isoformat()}",
        "",
        f"Generated {et_display(spec.generated_at)} from {spec.csv}. Source: {SOURCE_DESCRIPTION}.",
        f"Prices: {spec.prices or 'none fetched'}.",
        f"Method: {METHOD}",
        f"Coverage: {len(spec.rows)} of {spec.lookback} sessions fetched; {len(spec.missing)} missing.",
        "",
        READINGS_NOTE,
        "",
        _markdown_row(list(TABLE_COLUMNS)),
        _markdown_row(["---"] * len(TABLE_COLUMNS)),
    ]
    for session in spec.window:
        row = by_date.get(session)
        if row is None:
            lines.append(_markdown_row([session.isoformat(), *["missing"] * (len(TABLE_COLUMNS) - 1)]))
            continue
        lines.append(
            _markdown_row(
                [
                    session.isoformat(),
                    *_cells(row),
                    readings_text(row),
                    et_isoformat(row.fetched_at),
                    row.source,
                ]
            )
        )
    lines.extend(["", "## Gaps", "", GAPS_NOTE, ""])
    if spec.gaps:
        lines.append(_markdown_row(["Session", "Series", "Reason"]))
        lines.append(_markdown_row(["---", "---", "---"]))
        lines.extend(
            _markdown_row([gap.date.isoformat(), LABELS[gap.series], gap.reason]) for gap in spec.gaps
        )
    else:
        lines.append(NO_GAPS)
    return "\n".join(lines) + "\n"
