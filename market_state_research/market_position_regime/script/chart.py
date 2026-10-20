"""The report of one window: a self-contained page of three charts and its Markdown twin.

``render_html`` is a pure function of a ``ChartSpec`` and the vendored library and page
template (``templates/chart.html``, read with the library by ``load_library``): the same
inputs always produce the same text. The pinned library (``common.chart``) is inlined so the
page opens offline and from ``file://`` indefinitely. The page holds three charts, each on
its own time axis and always served together: margin debt by month (FINRA's debit balances
in $ millions); S&P 500 futures positioning by week (asset managers' net long and leveraged
funds' net short, as percentiles over 52 weeks on a fixed 0–100 scale); and the VIX by XNYS
session (its close as a percentile over 252 sessions, on the same scale). Their data are
embedded as JSON, which the page's own script draws (nothing reads it back), and repeated as
static data tables. Everything the page shows beyond plotting is computed here: each point's
readout line and values, the tables, the banners and the gaps, so the page only plots
numbers and text that Python produced and tests checked. ``render_markdown`` writes the same
window, coverage and gaps as Markdown. Times are New York time: ISO text with its EDT/EST
offset in the data, and the generation time to the second with its zone in the headers.
"""

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
from market_state_research.common.times import et_display, et_isoformat

from . import cftc
from .indicators import PERCENTILE_PLACES, SESSIONS, WEEKS
from .periods import Month
from .store import FuturesRow, MarginRow, VixRow

TEMPLATE_PATH: Final = Path(__file__).resolve().parent / "templates" / "chart.html"
TITLE: Final = "US equity positioning · margin debt, S&P 500 futures and the VIX"
SOURCE_DESCRIPTION: Final = (
    "FINRA margin statistics (customer margin balances of member firms, monthly) · "
    f"CFTC Traders in Financial Futures, futures only, {cftc.MARKET} ({cftc.CONTRACT}, weekly) · "
    "Cboe VIX daily history (VIX_History.csv, daily)"
)
METHOD: Final = (
    "Margin debt is FINRA's debit balances in customers' securities margin accounts, in $ millions, as of "
    "each month's last business day, as published. Asset managers' net position is their long minus their "
    "short futures positions, and leveraged funds' net short position their short minus their long, from the "
    "CFTC's weekly report of positions as of each Tuesday (Monday in a week whose Tuesday is a holiday), in "
    f"E-mini equivalents: each count times its contract's dollars per index point ÷ {cftc.EMINI} (the CFTC "
    f"counted contracts of $250 times the index until 2023-04-25 and of ${cftc.EMINI} from 2023-05-02). A "
    f"week's percentile is 100 times the share of the other {WEEKS - 1} weeks of the {WEEKS} weeks ending "
    "with the week whose value is strictly below the week's, rounded half-even to "
    f"{PERCENTILE_PLACES} decimal place; it needs every one of the {WEEKS} weeks' reports. A session's VIX "
    f"percentile is 100 times the share of the other {SESSIONS - 1} of the {SESSIONS} XNYS sessions ending "
    "with the session whose close, in Cboe's daily history of the index, is strictly below the session's "
    f"close, rounded half-even to {PERCENTILE_PLACES} decimal place; it needs a close on every one of the "
    f"{SESSIONS} sessions, and Cboe's rows of days XNYS does not trade are not used. Values are computed "
    "exactly and rounded once."
)
MARGIN_COLUMNS: Final = (
    "Month",
    "Debit balances ($M)",
    "Free credit, cash accounts ($M)",
    "Free credit, margin accounts ($M)",
    "Source",
)
FUTURES_COLUMNS: Final = (
    "Report date",
    "Asset managers' net (E-mini eq.)",
    f"Net percentile ({WEEKS}w)",
    "Leveraged funds' net short (E-mini eq.)",
    f"Net short percentile ({WEEKS}w)",
    "Asset managers long",
    "Asset managers short",
    "Leveraged funds long",
    "Leveraged funds short",
    "Open interest",
    "Contract ($ per index point)",
    "Fetched (ET)",
    "Source",
)
VIX_COLUMNS: Final = ("Session", "VIX close", f"Close percentile ({SESSIONS}s)", "Source")
LABELS: Final = {
    "asset_mgr_net_52w_percentile": "asset managers' net percentile",
    "lev_money_net_short_52w_percentile": "leveraged funds' net short percentile",
    "close_252s_percentile": "VIX close percentile",
}
GAPS_NOTE: Final = "Points of the window without a value, per series, and why."
NO_GAPS: Final = "None: every point of the window has every value."
NO_VALUE: Final = "—"


def load_library() -> Library:
    """The vendored library, its pinned checksum verified, and this domain's page template."""
    return common_chart.load_library(TEMPLATE_PATH)


@dataclass(frozen=True)
class MonthEntry:
    """One month of the window that is stored or due: its row, or None when it is not fetched."""

    month: Month
    row: MarginRow | None


@dataclass(frozen=True)
class WeekEntry:
    """One week of the window that is stored or due: its row, or None when it is not fetched."""

    week: date
    row: FuturesRow | None

    @property
    def time(self) -> date:
        """Where the week is drawn: its report's date, or its Tuesday without a report."""
        return self.week if self.row is None else self.row.report.as_of


@dataclass(frozen=True)
class SessionEntry:
    """One XNYS session of the window that is stored or due: its row, or None when it is not fetched."""

    session: date
    row: VixRow | None


@dataclass(frozen=True)
class Gap:
    """One point's series without a value, and why."""

    date: str
    series: str
    reason: str


@dataclass(frozen=True)
class ChartSpec:
    """One window's months, weeks and sessions, what is not due yet, the files they come from and
    the tables.

    ``upcoming`` names, as text, what the window holds that its sources are not due to publish
    yet; ``csv`` names the three tables relative to the data directory.
    """

    start: date
    end: date
    generated_at: datetime
    months: tuple[MonthEntry, ...]
    weeks: tuple[WeekEntry, ...]
    sessions: tuple[SessionEntry, ...]
    upcoming: tuple[str, ...]
    workbook: str | None
    history: str | None
    csv: tuple[str, str, str]

    def __post_init__(self) -> None:
        if self.start > self.end:
            raise ValueError("the window's start is after its end")
        months = [entry.month for entry in self.months]
        weeks = [entry.week for entry in self.weeks]
        sessions = [entry.session for entry in self.sessions]
        if months != sorted(set(months)) or weeks != sorted(set(weeks)) or sessions != sorted(set(sessions)):
            raise ValueError("chart months, weeks and sessions must be unique and ascending")

    @property
    def months_fetched(self) -> int:
        return sum(1 for entry in self.months if entry.row is not None)

    @property
    def weeks_fetched(self) -> int:
        return sum(1 for entry in self.weeks if entry.row is not None)

    @property
    def sessions_fetched(self) -> int:
        return sum(1 for entry in self.sessions if entry.row is not None)

    @property
    def fetched(self) -> int:
        """The stored points of the three charts."""
        return self.months_fetched + self.weeks_fetched + self.sessions_fetched

    @property
    def missing_months(self) -> tuple[Month, ...]:
        return tuple(entry.month for entry in self.months if entry.row is None)

    @property
    def missing_weeks(self) -> tuple[date, ...]:
        return tuple(entry.week for entry in self.weeks if entry.row is None)

    @property
    def missing_sessions(self) -> tuple[date, ...]:
        return tuple(entry.session for entry in self.sessions if entry.row is None)

    @property
    def gaps(self) -> tuple[Gap, ...]:
        found = []
        for week in self.weeks:
            if week.row is None:
                continue
            for key, item in (
                ("asset_mgr_net_52w_percentile", week.row.asset_mgr),
                ("lev_money_net_short_52w_percentile", week.row.lev_money),
            ):
                if item.value is None:
                    found.append(Gap(week.time.isoformat(), key, item.reason or ""))
        for entry in self.sessions:
            if entry.row is not None and entry.row.percentile.value is None:
                found.append(
                    Gap(entry.session.isoformat(), "close_252s_percentile", entry.row.percentile.reason or "")
                )
        return tuple(found)


def _text(value: Decimal | int | None) -> str | None:
    return None if value is None else str(value)


def _shown(value: Decimal | int | None) -> str:
    return NO_VALUE if value is None else str(value)


def _count(value: int | Decimal | None) -> str:
    """A whole number with thousands separators, or ``—``."""
    return NO_VALUE if value is None else f"{value:,}"


def _close(row: VixRow) -> str:
    """The close as Cboe wrote it, without the trailing zeros beyond two places (exact), or ``—``."""
    if row.bar is None:
        return NO_VALUE
    whole, _, places = row.bar.close.partition(".")
    return f"{whole}.{places.rstrip('0').ljust(2, '0')}"


def _week_detail(entry: WeekEntry) -> str:
    if entry.row is None:
        return f"week of {entry.week.isoformat()} · not fetched"
    return f"week of {entry.week.isoformat()}"


def _detail(row: object) -> str:
    """A month's or a session's readout detail: empty, or ``not fetched``."""
    return "not fetched" if row is None else ""


def _margin_readout(entry: MonthEntry) -> tuple[str, ...]:
    return (NO_VALUE,) if entry.row is None else (_count(entry.row.balance.debit),)


def _futures_readout(entry: WeekEntry) -> tuple[str, ...]:
    row = entry.row
    if row is None:
        return (NO_VALUE,) * 5
    report = row.report
    return (
        _shown(row.asset_mgr.value),
        _shown(row.lev_money.value),
        _count(report.asset_mgr_net),
        _count(report.lev_money_net_short),
        _count(report.open_interest_emini),
    )


def _vix_readout(entry: SessionEntry) -> tuple[str, ...]:
    row = entry.row
    return (NO_VALUE,) * 2 if row is None else (_shown(row.percentile.value), _close(row))


def payload(spec: ChartSpec, library_version: str = LIBRARY_VERSION) -> dict[str, Any]:
    """The JSON embedded in the page; decimals stay strings, readout texts are given whole."""
    return {
        "start": spec.start.isoformat(),
        "end": spec.end.isoformat(),
        "generated_at": et_isoformat(spec.generated_at),
        "csv": list(spec.csv),
        "method": METHOD,
        "source": SOURCE_DESCRIPTION,
        "library": f"{LIBRARY_NAME} {library_version}",
        "margin": [
            {
                "time": entry.month.last_day().isoformat(),
                "label": entry.month.isoformat(),
                "detail": _detail(entry.row),
                "debit_balances_musd": None if entry.row is None else _text(entry.row.balance.debit),
                "readout": list(_margin_readout(entry)),
            }
            for entry in spec.months
        ],
        "futures": [
            {
                "time": entry.time.isoformat(),
                "label": entry.time.isoformat(),
                "detail": _week_detail(entry),
                "asset_mgr_net_52w_percentile": None
                if entry.row is None
                else _text(entry.row.asset_mgr.value),
                "lev_money_net_short_52w_percentile": None
                if entry.row is None
                else _text(entry.row.lev_money.value),
                "readout": list(_futures_readout(entry)),
            }
            for entry in spec.weeks
        ],
        "vix": [
            {
                "time": entry.session.isoformat(),
                "label": entry.session.isoformat(),
                "detail": _detail(entry.row),
                "close_252s_percentile": None if entry.row is None else _text(entry.row.percentile.value),
                "readout": list(_vix_readout(entry)),
            }
            for entry in spec.sessions
        ],
        "gaps": [{"date": gap.date, "series": gap.series, "reason": gap.reason} for gap in spec.gaps],
        "upcoming": list(spec.upcoming),
    }


def _margin_cells(row: MarginRow) -> list[str]:
    balance = row.balance
    return [_count(balance.debit), _count(balance.free_cash), _count(balance.free_margin), row.source]


def _futures_cells(row: FuturesRow) -> list[str]:
    report = row.report
    return [
        _count(report.asset_mgr_net),
        _shown(row.asset_mgr.value),
        _count(report.lev_money_net_short),
        _shown(row.lev_money.value),
        _count(report.asset_mgr_long),
        _count(report.asset_mgr_short),
        _count(report.lev_money_long),
        _count(report.lev_money_short),
        _count(report.open_interest),
        str(report.multiplier),
        et_isoformat(row.stored.fetched_at),
        row.stored.source,
    ]


def _vix_cells(row: VixRow) -> list[str]:
    return [_close(row), _shown(row.percentile.value), row.source]


def _table(columns: tuple[str, ...], rows: list[tuple[str, list[str] | None]]) -> str:
    head = "".join(f'<th scope="col">{escape(column)}</th>' for column in columns)
    lines = []
    for label, cells in rows:
        if cells is None:
            body = f'<td class="missing" colspan="{len(columns) - 1}">not fetched</td>'
        else:
            body = "".join(
                f'<td class="reason">{escape(cell)}</td>'
                if index == len(cells) - 1
                else f"<td>{escape(cell)}</td>"
                for index, cell in enumerate(cells)
            )
        lines.append(f'<tr><th scope="row">{escape(label)}</th>{body}</tr>')
    return (
        f'<div class="table-wrap"><table><thead><tr>{head}</tr></thead>'
        f"<tbody>\n" + "\n".join(lines) + "\n</tbody></table></div>"
    )


def _margin_rows(spec: ChartSpec) -> list[tuple[str, list[str] | None]]:
    return [
        (entry.month.isoformat(), None if entry.row is None else _margin_cells(entry.row))
        for entry in spec.months
    ]


def _futures_rows(spec: ChartSpec) -> list[tuple[str, list[str] | None]]:
    return [
        (entry.time.isoformat(), None if entry.row is None else _futures_cells(entry.row))
        for entry in spec.weeks
    ]


def _vix_rows(spec: ChartSpec) -> list[tuple[str, list[str] | None]]:
    return [
        (entry.session.isoformat(), None if entry.row is None else _vix_cells(entry.row))
        for entry in spec.sessions
    ]


def _gap_rows(spec: ChartSpec) -> str:
    if not spec.gaps:
        return f'<p class="hint">{escape(NO_GAPS)}</p>'
    rows = "\n".join(
        f'<tr><th scope="row">{escape(gap.date)}</th><td>{escape(LABELS[gap.series])}</td>'
        f'<td class="reason">{escape(gap.reason)}</td></tr>'
        for gap in spec.gaps
    )
    return (
        '<div class="table-wrap"><table class="gaps">'
        '<thead><tr><th scope="col">Point</th><th scope="col">Series</th>'
        '<th scope="col">Reason</th></tr></thead>'
        f"<tbody>\n{rows}\n</tbody></table></div>"
    )


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


def _missing_clauses(spec: ChartSpec) -> list[str]:
    clauses = []
    if spec.missing_months:
        listed = ", ".join(month.isoformat() for month in spec.missing_months)
        clauses.append(f"{_plural(len(spec.missing_months), 'month')} of FINRA's balances ({listed})")
    if spec.missing_weeks:
        listed = ", ".join(week.isoformat() for week in spec.missing_weeks)
        clauses.append(f"{_plural(len(spec.missing_weeks), 'week')} of CFTC reports (the weeks of {listed})")
    if spec.missing_sessions:
        listed = ", ".join(session.isoformat() for session in spec.missing_sessions)
        clauses.append(f"{_plural(len(spec.missing_sessions), 'session')} of Cboe's VIX ({listed})")
    return clauses


def _gap_clauses(spec: ChartSpec) -> list[str]:
    groups: dict[str, list[str]] = {}
    for gap in spec.gaps:
        groups.setdefault(gap.series, []).append(gap.date)
    return [
        f"no {LABELS[series]} on {_plural(len(dates), 'point')}: {', '.join(dates)}"
        for series, dates in groups.items()
    ]


def _banners(spec: ChartSpec) -> str:
    banners = []
    missing = _missing_clauses(spec)
    if missing:
        listed = escape("; ".join(missing))
        banners.append(
            '<p class="banner" role="status"><span class="banner-icon" aria-hidden="true">⚠</span> '
            f"<strong>Not fetched.</strong> The sources are due to have published {listed}, which raw/ "
            "does not hold: run fetch.</p>"
        )
    gaps = _gap_clauses(spec)
    if gaps:
        listed = escape("; ".join(gaps))
        banners.append(
            '<p class="banner" role="status"><span class="banner-icon" aria-hidden="true">⚠</span> '
            f"<strong>Gaps.</strong> {listed}. The gaps below the data tables give each reason.</p>"
        )
    return "\n".join(banners)


def _upcoming(spec: ChartSpec) -> str:
    return "; ".join(spec.upcoming) if spec.upcoming else "nothing"


def _newest(spec: ChartSpec) -> str:
    months = [entry.month for entry in spec.months if entry.row is not None]
    weeks = [entry.time for entry in spec.weeks if entry.row is not None]
    sessions = [entry.session for entry in spec.sessions if entry.row is not None]
    month = months[-1].isoformat() if months else "none"
    week = weeks[-1].isoformat() if weeks else "none"
    session = sessions[-1].isoformat() if sessions else "none"
    return f"month {month} · report {week} · session {session}"


def _files(spec: ChartSpec) -> str:
    return f"{spec.workbook or 'no FINRA workbook'}, {spec.history or 'no Cboe VIX file'}"


def _coverage(spec: ChartSpec) -> str:
    return (
        f"{spec.months_fetched} of {len(spec.months)} months · "
        f"{spec.weeks_fetched} of {len(spec.weeks)} weeks · "
        f"{spec.sessions_fetched} of {len(spec.sessions)} sessions"
    )


def render_html(spec: ChartSpec, library: Library) -> str:
    """Render the complete, self-contained page."""
    if spec.fetched == 0:
        raise ValueError("a report needs at least one fetched month, week or session in its window")
    latest_month = next((entry for entry in reversed(spec.months) if entry.row is not None), None)
    latest_week = next((entry for entry in reversed(spec.weeks) if entry.row is not None), None)
    latest_session = next((entry for entry in reversed(spec.sessions) if entry.row is not None), None)
    values = {
        "TITLE": escape(f"{TITLE} · {spec.start.isoformat()} to {spec.end.isoformat()}"),
        "HEADING": escape(TITLE),
        "START": escape(spec.start.isoformat()),
        "END": escape(spec.end.isoformat()),
        "GENERATED": escape(et_display(spec.generated_at)),
        "CSV": escape(" · ".join(spec.csv)),
        "FILES": escape(_files(spec)),
        "NEWEST": escape(_newest(spec)),
        "COVERAGE": escape(_coverage(spec)),
        "UPCOMING": escape(_upcoming(spec)),
        "SOURCE": escape(SOURCE_DESCRIPTION),
        "METHOD": escape(METHOD),
        "LIBRARY_VERSION": escape(library.version),
        "NOTICE": escape(library.notice),
        "BANNERS": _banners(spec),
        "MARGIN_DATE": escape(NO_VALUE if latest_month is None else latest_month.month.isoformat()),
        "MARGIN_DETAIL": escape("no month fetched" if latest_month is None else ""),
        "FUTURES_DATE": escape(NO_VALUE if latest_week is None else latest_week.time.isoformat()),
        "FUTURES_DETAIL": escape("no week fetched" if latest_week is None else _week_detail(latest_week)),
        "VIX_DATE": escape(NO_VALUE if latest_session is None else latest_session.session.isoformat()),
        "VIX_DETAIL": escape("no session fetched" if latest_session is None else ""),
        "MARGIN_TABLE": _table(MARGIN_COLUMNS, _margin_rows(spec)),
        "FUTURES_TABLE": _table(FUTURES_COLUMNS, _futures_rows(spec)),
        "VIX_TABLE": _table(VIX_COLUMNS, _vix_rows(spec)),
        "MONTHS": escape(len(spec.months)),
        "WEEKS": escape(len(spec.weeks)),
        "SESSIONS": escape(len(spec.sessions)),
        "GAP_ROWS": _gap_rows(spec),
        "PAYLOAD": embed_json(payload(spec, library.version)),
        "LIBRARY": library.script,
    }
    readouts = {
        "MARGIN": (NO_VALUE,) if latest_month is None else _margin_readout(latest_month),
        "FUTURES": (NO_VALUE,) * 5 if latest_week is None else _futures_readout(latest_week),
        "VIX": (NO_VALUE,) * 2 if latest_session is None else _vix_readout(latest_session),
    }
    for chart_name, texts in readouts.items():
        for index, text in enumerate(texts):
            values[f"{chart_name}_VALUE_{index}"] = escape(text)
    return substitute(library.template, values)


def _markdown_row(cells: list[object]) -> str:
    return "| " + " | ".join(str(cell).replace("|", "\\|") for cell in cells) + " |"


def _markdown_table(columns: tuple[str, ...], rows: list[tuple[str, list[str] | None]]) -> list[str]:
    lines = [_markdown_row(list(columns)), _markdown_row(["---"] * len(columns))]
    for label, cells in rows:
        lines.append(
            _markdown_row([label, *(cells if cells is not None else ["not fetched"] * (len(columns) - 1))])
        )
    return lines


def render_markdown(spec: ChartSpec) -> str:
    """The window as Markdown: the sources, the method, coverage, the three tables and the gaps."""
    lines = [
        f"# {TITLE} · {spec.start.isoformat()} → {spec.end.isoformat()}",
        "",
        f"Generated {et_display(spec.generated_at)} from {', '.join(spec.csv)}.",
        f"Source: {SOURCE_DESCRIPTION}.",
        f"Raw files: {_files(spec)}.",
        f"Method: {METHOD}",
        f"Coverage: {_coverage(spec)}; newest {_newest(spec)}.",
        f"Not due yet: {_upcoming(spec)}.",
    ]
    missing = _missing_clauses(spec)
    if missing:
        lines.append(f"Not fetched although due: {'; '.join(missing)}.")
    lines.extend(["", "## Margin debt, monthly", ""])
    lines.extend(_markdown_table(MARGIN_COLUMNS, _margin_rows(spec)))
    lines.extend(["", f"## S&P 500 futures positioning, weekly ({cftc.MARKET})", ""])
    lines.extend(_markdown_table(FUTURES_COLUMNS, _futures_rows(spec)))
    lines.extend(["", "## VIX, by XNYS session", ""])
    lines.extend(_markdown_table(VIX_COLUMNS, _vix_rows(spec)))
    lines.extend(["", "## Gaps", "", GAPS_NOTE, ""])
    if spec.gaps:
        lines.append(_markdown_row(["Point", "Series", "Reason"]))
        lines.append(_markdown_row(["---", "---", "---"]))
        lines.extend(_markdown_row([gap.date, LABELS[gap.series], gap.reason]) for gap in spec.gaps)
    else:
        lines.append(NO_GAPS)
    return "\n".join(lines) + "\n"
