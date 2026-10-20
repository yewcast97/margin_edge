"""The report of one window: a self-contained page of two charts and its Markdown twin.

``render_html`` is a pure function of a ``ChartSpec`` and the vendored library and page
template (``templates/chart.html``, read with the library by ``load_library``): the same
inputs always produce the same text. The pinned library (``common.chart``) is inlined so the
page opens offline and from ``file://`` indefinitely. The page holds two charts, each on its
own time axis and always served together: margin debt by month (its year-over-year growth on
the right scale, its ratio to the market value of US corporate equities on the left) and S&P
500 futures positioning by week (asset managers' net long and leveraged funds' net short, as
percentiles over 52 weeks on a fixed 0–100 scale). Their data are embedded as JSON, which the
page's own script draws (nothing reads it back), and repeated as static data tables.
Everything the page shows beyond plotting is computed here: each point's readout line and
values, the tables, the banners and the gaps, so the page only plots numbers and text that
Python produced and tests checked. ``render_markdown`` writes the same window, coverage and
gaps as Markdown. Times are New York time: ISO text with its EDT/EST offset in the data, and
the generation time to the second with its zone in the headers.
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

from . import cftc, fred
from .indicators import PERCENTILE_PLACES, RATIO_PLACES, WEEKS, YOY_PLACES
from .periods import Month
from .store import FuturesRow, MarginRow

TEMPLATE_PATH: Final = Path(__file__).resolve().parent / "templates" / "chart.html"
TITLE: Final = "US equity positioning · margin debt and S&P 500 futures"
SOURCE_DESCRIPTION: Final = (
    "FINRA margin statistics (customer margin balances of member firms, monthly) · "
    f"CFTC Traders in Financial Futures, futures only, {cftc.MARKET} ({cftc.CONTRACT}, weekly) · "
    f"Federal Reserve Z.1 through FRED: {fred.NONFINANCIAL} + {fred.FINANCIAL} (quarterly)"
)
METHOD: Final = (
    "Margin debt is FINRA's debit balances in customers' securities margin accounts, in $ millions, as of "
    "each month's last business day. Its year-over-year growth is (the month's debit balances ÷ those of "
    f"the same month a year before − 1) × 100, rounded half-even to {YOY_PLACES} decimal place. Its ratio "
    "to market value is the month's debit balances ÷ the market value of US corporate equities at the latest "
    "quarter end on or before the month's last day × 100, rounded half-even to "
    f"{RATIO_PLACES} decimal places; the market value is the sum of the Federal Reserve's Z.1 series "
    f"{fred.NONFINANCIAL} (nonfinancial corporate business, public and closely held) and {fred.FINANCIAL} "
    "(domestic financial sectors), in $ millions, and a month whose quarter end is not published yet has "
    "no ratio. Asset managers' net position is their long minus their short futures positions, and "
    "leveraged funds' net short position their short minus their long, from the CFTC's weekly report of "
    "positions as of each Tuesday (Monday in a week whose Tuesday is a holiday), in E-mini equivalents: "
    f"each count times its contract's dollars per index point ÷ {cftc.EMINI} (the CFTC counted contracts "
    f"of $250 times the index until 2023-04-25 and of ${cftc.EMINI} from 2023-05-02). A percentile is 100 "
    f"times the share of the other {WEEKS - 1} weeks of the {WEEKS} weeks ending with the week whose value "
    "is strictly below the week's, rounded half-even to "
    f"{PERCENTILE_PLACES} decimal place; it needs every one of the {WEEKS} weeks' reports. Values are "
    "computed exactly and rounded once."
)
MARGIN_COLUMNS: Final = (
    "Month",
    "Debit balances ($M)",
    "Year-over-year growth (%)",
    "Ratio to market value (%)",
    "Market value ($M)",
    "Quarter end",
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
LABELS: Final = {
    "yoy_pct": "year-over-year growth",
    "ratio_pct": "ratio to market value",
    "asset_mgr_net_52w_percentile": "asset managers' net percentile",
    "lev_money_net_short_52w_percentile": "leveraged funds' net short percentile",
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
class Gap:
    """One point's series without a value, and why."""

    date: str
    series: str
    reason: str


@dataclass(frozen=True)
class ChartSpec:
    """One window's months and weeks, what is not due yet, the files they come from and the tables.

    ``upcoming`` names, as text, what the window holds that its sources are not due to publish
    yet; ``csv`` names the two tables relative to the data directory.
    """

    start: date
    end: date
    generated_at: datetime
    months: tuple[MonthEntry, ...]
    weeks: tuple[WeekEntry, ...]
    upcoming: tuple[str, ...]
    workbook: str | None
    series: tuple[str, ...]
    csv: tuple[str, str]

    def __post_init__(self) -> None:
        if self.start > self.end:
            raise ValueError("the window's start is after its end")
        months = [entry.month for entry in self.months]
        weeks = [entry.week for entry in self.weeks]
        if months != sorted(set(months)) or weeks != sorted(set(weeks)):
            raise ValueError("chart months and weeks must be unique and ascending")

    @property
    def months_fetched(self) -> int:
        return sum(1 for entry in self.months if entry.row is not None)

    @property
    def weeks_fetched(self) -> int:
        return sum(1 for entry in self.weeks if entry.row is not None)

    @property
    def missing_months(self) -> tuple[Month, ...]:
        return tuple(entry.month for entry in self.months if entry.row is None)

    @property
    def missing_weeks(self) -> tuple[date, ...]:
        return tuple(entry.week for entry in self.weeks if entry.row is None)

    @property
    def gaps(self) -> tuple[Gap, ...]:
        found = []
        for entry in self.months:
            if entry.row is None:
                continue
            for key, value in (("yoy_pct", entry.row.yoy), ("ratio_pct", entry.row.ratio)):
                if value.value is None:
                    found.append(Gap(entry.month.isoformat(), key, value.reason or ""))
        for week in self.weeks:
            if week.row is None:
                continue
            for key, item in (
                ("asset_mgr_net_52w_percentile", week.row.asset_mgr),
                ("lev_money_net_short_52w_percentile", week.row.lev_money),
            ):
                if item.value is None:
                    found.append(Gap(week.time.isoformat(), key, item.reason or ""))
        return tuple(found)


def _text(value: Decimal | int | None) -> str | None:
    return None if value is None else str(value)


def _shown(value: Decimal | int | None) -> str:
    return NO_VALUE if value is None else str(value)


def _count(value: int | Decimal | None) -> str:
    """A whole number with thousands separators, or ``—``."""
    return NO_VALUE if value is None else f"{value:,}"


def _month_detail(entry: MonthEntry) -> str:
    if entry.row is None:
        return "not fetched"
    return f"market value of {entry.row.quarter_end.isoformat()}"


def _week_detail(entry: WeekEntry) -> str:
    if entry.row is None:
        return f"week of {entry.week.isoformat()} · not fetched"
    return f"week of {entry.week.isoformat()}"


def _margin_readout(entry: MonthEntry) -> tuple[str, ...]:
    row = entry.row
    if row is None:
        return (NO_VALUE,) * 4
    return (
        _shown(row.yoy.value),
        _shown(row.ratio.value),
        _count(row.balance.debit),
        _count(row.market_value.value),
    )


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
                "detail": _month_detail(entry),
                "yoy_pct": None if entry.row is None else _text(entry.row.yoy.value),
                "ratio_pct": None if entry.row is None else _text(entry.row.ratio.value),
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
        "gaps": [{"date": gap.date, "series": gap.series, "reason": gap.reason} for gap in spec.gaps],
        "upcoming": list(spec.upcoming),
    }


def _margin_cells(row: MarginRow) -> list[str]:
    balance = row.balance
    return [
        _count(balance.debit),
        _shown(row.yoy.value),
        _shown(row.ratio.value),
        _count(row.market_value.value),
        row.quarter_end.isoformat(),
        _count(balance.free_cash),
        _count(balance.free_margin),
        row.source,
    ]


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
    month = months[-1].isoformat() if months else "none"
    week = weeks[-1].isoformat() if weeks else "none"
    return f"month {month} · report {week}"


def _files(spec: ChartSpec) -> str:
    files = [spec.workbook or "no FINRA workbook", *(spec.series or ("no FRED answer",))]
    return ", ".join(files)


def _coverage(spec: ChartSpec) -> str:
    return (
        f"{spec.months_fetched} of {len(spec.months)} months · "
        f"{spec.weeks_fetched} of {len(spec.weeks)} weeks"
    )


def render_html(spec: ChartSpec, library: Library) -> str:
    """Render the complete, self-contained page."""
    if spec.months_fetched + spec.weeks_fetched == 0:
        raise ValueError("a report needs at least one fetched month or week in its window")
    latest_month = next((entry for entry in reversed(spec.months) if entry.row is not None), None)
    latest_week = next((entry for entry in reversed(spec.weeks) if entry.row is not None), None)
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
        "MARGIN_DETAIL": escape("no month fetched" if latest_month is None else _month_detail(latest_month)),
        "FUTURES_DATE": escape(NO_VALUE if latest_week is None else latest_week.time.isoformat()),
        "FUTURES_DETAIL": escape("no week fetched" if latest_week is None else _week_detail(latest_week)),
        "MARGIN_TABLE": _table(MARGIN_COLUMNS, _margin_rows(spec)),
        "FUTURES_TABLE": _table(FUTURES_COLUMNS, _futures_rows(spec)),
        "MONTHS": escape(len(spec.months)),
        "WEEKS": escape(len(spec.weeks)),
        "GAP_ROWS": _gap_rows(spec),
        "PAYLOAD": embed_json(payload(spec, library.version)),
        "LIBRARY": library.script,
    }
    margin = (NO_VALUE,) * 4 if latest_month is None else _margin_readout(latest_month)
    futures = (NO_VALUE,) * 5 if latest_week is None else _futures_readout(latest_week)
    for index, text in enumerate(margin):
        values[f"MARGIN_VALUE_{index}"] = escape(text)
    for index, text in enumerate(futures):
        values[f"FUTURES_VALUE_{index}"] = escape(text)
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
    """The window as Markdown: the sources, the method, coverage, the two tables and the gaps."""
    lines = [
        f"# {TITLE} · {spec.start.isoformat()} → {spec.end.isoformat()}",
        "",
        f"Generated {et_display(spec.generated_at)} from {' and '.join(spec.csv)}.",
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
    lines.extend(["", "## Gaps", "", GAPS_NOTE, ""])
    if spec.gaps:
        lines.append(_markdown_row(["Point", "Series", "Reason"]))
        lines.append(_markdown_row(["---", "---", "---"]))
        lines.extend(_markdown_row([gap.date, LABELS[gap.series], gap.reason]) for gap in spec.gaps)
    else:
        lines.append(NO_GAPS)
    return "\n".join(lines) + "\n"
