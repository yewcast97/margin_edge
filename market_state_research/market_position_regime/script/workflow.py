"""Plan, fetch, record and show: one window of dates over the raw files.

The window runs from ``--from`` to ``--to`` (``Window``): its months are those whose last day
lies in it and its weeks those whose Tuesday does. What its indicators rest on reaches
further back: each month's year-over-year base twelve months before, each month's quarter
end, and the 51 weeks before its first week. A document of the window or of what it rests on
is due from the time ``periods`` gives; one that is due and not stored is lacking.

``plan`` (read-only) says, per source, what is lacking, which raw files are invalid, whether
the two tables and the newest report of the window are current, and the action: ``fetch``
while a document is lacking (or with ``refresh``), ``record`` when the tables or the report
are not current, ``reuse`` otherwise. ``fetch`` requests from each source what is lacking:
FINRA's workbook whole, the CFTC's rows from the first lacking week to the last, each FRED
series whole. It writes an answer only when it holds something ``raw/`` does not (``new``),
compares it otherwise (``verified``), and names every due document the source has not
published yet (``pending``); a source that fails does not stop the others. ``record``
rewrites the two tables from ``raw/`` and writes a new report (the page and its Markdown
twin) each time it runs, naming whatever is lacking in it. ``show`` prints the twin.

A report is fresh while its twin and its page are exactly what ``record`` would write now,
at the time in the report's name. Reports are never overwritten; every time printed is New
York time.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Final

from market_state_research.common.layout import (
    DataLayout,
    FileExists,
    name_instant,
    newest,
    stamped,
    write_file,
)
from market_state_research.common.times import et_display, et_isoformat, to_eastern

from . import cftc, finra, fred
from .chart import ChartSpec, MonthEntry, WeekEntry, load_library, render_html, render_markdown
from .client import Client, SourceError
from .indicators import WEEKS
from .periods import (
    Month,
    cftc_release,
    finra_due,
    months_ending_within,
    quarter_end_of,
    week_days,
    weeks_ending,
    weeks_within,
    z1_due,
)
from .store import (
    FIRST_WEEK,
    FOLDER,
    FuturesRow,
    InvalidFile,
    MarginRow,
    SeriesFile,
    Stored,
    WorkbookFile,
    csv_paths,
    derive_futures,
    derive_margin,
    futures_text,
    margin_text,
    raw_directory,
    read_raw,
    select_reports,
    select_series,
    select_workbook,
    write_table,
)

DEFAULT_YEARS: Final = 3
REPORT_PREFIX: Final = "market"


@dataclass(frozen=True)
class Window:
    """The dates a report covers: from ``start`` to ``end``, both included."""

    start: date
    end: date

    def __post_init__(self) -> None:
        if self.start > self.end:
            raise ValueError("the window's from date is after its to date")

    @property
    def months(self) -> tuple[Month, ...]:
        return months_ending_within(self.start, self.end)

    @property
    def weeks(self) -> tuple[date, ...]:
        return weeks_within(self.start, self.end)

    @property
    def base_months(self) -> tuple[Month, ...]:
        """The months the window's growths rest on: twelve months before each."""
        return tuple(month.shifted(-12) for month in self.months)

    @property
    def quarter_ends(self) -> tuple[date, ...]:
        """The quarter ends the window's ratios rest on, ascending."""
        return tuple(sorted({quarter_end_of(month) for month in self.months}))

    @property
    def span_weeks(self) -> tuple[date, ...]:
        """The window's weeks and the ``WEEKS - 1`` before the first, which its percentiles rest on."""
        found = self.weeks
        return weeks_ending(found[-1], len(found) + WEEKS - 1) if found else ()


def default_window(today: date) -> Window:
    """The three years up to ``today``: from the same day three years earlier (29 February: the 28th)."""
    day = 28 if (today.month, today.day) == (2, 29) else today.day
    return Window(start=date(today.year - DEFAULT_YEARS, today.month, day), end=today)


@dataclass(frozen=True)
class Report:
    """The newest report of a window: ``fresh``, ``stale`` (with a reason) or ``missing``."""

    status: str
    path: Path | None = None
    reason: str | None = None

    def describe(self) -> dict[str, str | None]:
        return {
            "status": self.status,
            "path": None if self.path is None else str(self.path),
            "reason": self.reason,
        }


@dataclass(frozen=True)
class State:
    """The validated raw files, the selection and every row, for one window at one time."""

    window: Window
    now: datetime
    workbook: WorkbookFile | None
    series: dict[str, SeriesFile]
    reports: dict[date, Stored]
    invalid: tuple[InvalidFile, ...]
    margin: dict[Month, MarginRow]
    futures: dict[date, FuturesRow]
    tables: tuple[Path, Path]

    # ------------------------------------------------------------------ what is due and lacking

    def due_months(self, at: datetime) -> tuple[Month, ...]:
        """The months the window and its growths need that are due at ``at``, ascending."""
        needed = sorted(set(self.window.months) | set(self.window.base_months))
        return tuple(
            month for month in needed if month >= finra.FIRST_MONTH and finra_due(month) <= at.date()
        )

    def lacking_months(self, at: datetime | None = None) -> tuple[Month, ...]:
        newest_month = None if self.workbook is None else self.workbook.workbook.newest
        return tuple(
            month for month in self.due_months(at or self.now) if newest_month is None or month > newest_month
        )

    def due_weeks(self, at: datetime) -> tuple[date, ...]:
        """The weeks the window and its percentiles need that are due at ``at``, ascending."""
        return tuple(
            week for week in self.window.span_weeks if week >= FIRST_WEEK and cftc_release(week) <= at
        )

    def lacking_weeks(self, at: datetime | None = None) -> tuple[date, ...]:
        return tuple(week for week in self.due_weeks(at or self.now) if week not in self.reports)

    def due_quarters(self, at: datetime) -> tuple[date, ...]:
        """The quarter ends the window's ratios need that are due at ``at``, ascending."""
        return tuple(end for end in self.window.quarter_ends if z1_due(end) <= at.date())

    def _held(self, series: str) -> set[date]:
        """The quarter ends the stored answer of ``series`` holds."""
        found = self.series.get(series)
        return set() if found is None else set(found.series.by_quarter_end())

    def lacking_quarters(self, series: str, at: datetime | None = None) -> tuple[date, ...]:
        held = self._held(series)
        return tuple(end for end in self.due_quarters(at or self.now) if end not in held)

    @property
    def lacking(self) -> bool:
        return bool(
            self.lacking_months()
            or self.lacking_weeks()
            or any(self.lacking_quarters(series) for series in fred.SERIES)
        )

    # ------------------------------------------------------------------ the tables and the report

    @property
    def tables_current(self) -> bool:
        """Whether both tables hold exactly what ``record`` would write."""
        margin, futures = self.tables
        return _holds(margin, margin_text(self.margin.values())) and _holds(
            futures, futures_text(self.futures.values())
        )

    def action(self, report: Report) -> str:
        if self.lacking:
            return "fetch"
        return "reuse" if self.tables_current and report.status == "fresh" else "record"

    def upcoming(self, at: datetime) -> tuple[str, ...]:
        """What the window holds that its sources are not due to publish yet at ``at``, as text."""
        items = []
        months = [
            month for month in self.window.months if finra_due(month) > at.date() and month not in self.margin
        ]
        if months:
            listed = ", ".join(f"{month.isoformat()} (due {finra_due(month)})" for month in months)
            items.append(f"FINRA's balances of {listed}")
        late = [week for week in self.window.weeks if cftc_release(week) > at and week not in self.reports]
        if late:
            listed = ", ".join(f"{week} (due {et_display(cftc_release(week))})" for week in late)
            items.append(f"the CFTC reports of the weeks of {listed}")
        quarters = [
            end
            for end in self.window.quarter_ends
            if z1_due(end) > at.date() and any(end not in self._held(name) for name in fred.SERIES)
        ]
        if quarters:
            listed = ", ".join(f"{end} (due {z1_due(end)})" for end in quarters)
            items.append(f"the Z.1 market values of {listed}")
        return tuple(items)

    def spec(self, layout: DataLayout, at: datetime) -> ChartSpec:
        """The report of the window as rendered at ``at``: the months and weeks stored or due then."""
        due_months = set(self.due_months(at))
        due_weeks = set(self.due_weeks(at))
        months = tuple(
            MonthEntry(month, self.margin.get(month))
            for month in self.window.months
            if month in self.margin or month in due_months
        )
        entries = tuple(
            WeekEntry(week, self.futures.get(week))
            for week in self.window.weeks
            if week in self.futures or week in due_weeks
        )
        margin, futures = self.tables
        return ChartSpec(
            start=self.window.start,
            end=self.window.end,
            generated_at=at,
            months=months,
            weeks=entries,
            upcoming=self.upcoming(at),
            workbook=None if self.workbook is None else self.workbook.source,
            series=tuple(self.series[name].source for name in fred.SERIES if name in self.series),
            csv=(margin.relative_to(layout.root).as_posix(), futures.relative_to(layout.root).as_posix()),
        )

    def refuse_invalid(self) -> None:
        if self.invalid:
            listed = "; ".join(f"{item.path}: {item.reason}" for item in self.invalid)
            raise ValueError(
                f"{len(self.invalid)} raw file(s) failed validation ({listed}); "
                "rename each with the suffix .rejected, then run the command again"
            )


def _holds(path: Path, text: str) -> bool:
    return path.is_file() and path.read_bytes() == text.encode()


def _report_stem(window: Window) -> str:
    return f"{REPORT_PREFIX}_{window.start.isoformat()}_{window.end.isoformat()}"


def resolve(layout: DataLayout, window: Window, now: datetime) -> State:
    """Validate every raw file, select the documents and derive every row."""
    now = to_eastern(now, "now")
    raw = read_raw(layout, now)
    workbook = select_workbook(raw.workbooks)
    series = select_series(raw.series)
    reports = select_reports(raw.answers)
    return State(
        window=window,
        now=now,
        workbook=workbook,
        series=series,
        reports=reports,
        invalid=raw.invalid,
        margin=derive_margin(workbook, series),
        futures=derive_futures(reports),
        tables=csv_paths(layout),
    )


def _report(layout: DataLayout, state: State, now: datetime) -> Report:
    stem = _report_stem(state.window)
    path = newest(layout.reports(FOLDER), f"{stem}_", ".html", now)
    if path is None:
        return Report("missing")
    made = name_instant(path.name)
    stale = Report("stale", path, f"{path.stem} differs from the report rendered now")
    if made is None:
        return stale
    spec = state.spec(layout, made)
    if spec.months_fetched + spec.weeks_fetched == 0:
        return stale
    if not (
        _holds(path.with_suffix(".md"), render_markdown(spec))
        and _holds(path, render_html(spec, load_library()))
    ):
        return stale
    return Report("fresh", path)


def _span(items: Sequence[date] | Sequence[Month]) -> dict[str, Any]:
    """How many ``items`` (ascending) there are, and the first and last."""
    return {
        "count": len(items),
        "first": items[0].isoformat() if items else None,
        "last": items[-1].isoformat() if items else None,
    }


def _window(window: Window) -> dict[str, Any]:
    span = window.span_weeks
    starts = [window.start]
    if window.base_months:
        starts.append(window.base_months[0].first_day())
    if span:
        starts.append(week_days(span[0])[0])
    return {
        "from": window.start.isoformat(),
        "to": window.end.isoformat(),
        "months": len(window.months),
        "weeks": len(window.weeks),
        "span_start": min(starts).isoformat(),
    }


def _sources(layout: DataLayout, state: State) -> dict[str, Any]:
    workbook = state.workbook
    lacking_months = state.lacking_months()
    lacking_weeks = state.lacking_weeks()
    newest_week = max(state.reports, default=None)
    sources: dict[str, Any] = {
        "finra": {
            "status": "lacking" if lacking_months else "current",
            "path": None if workbook is None else str(raw_directory(layout) / workbook.source),
            "newest": None if workbook is None else workbook.workbook.newest.isoformat(),
            "lacking": _span(lacking_months),
        },
        "cftc": {
            "status": "lacking" if lacking_weeks else "current",
            "files": len({item.source for item in state.reports.values()}),
            "newest": None if newest_week is None else state.reports[newest_week].report.as_of.isoformat(),
            "lacking": _span(lacking_weeks),
        },
    }
    for name in fred.SERIES:
        found = state.series.get(name)
        lacking = state.lacking_quarters(name)
        sources[name] = {
            "status": "lacking" if lacking else "current",
            "path": None if found is None else str(raw_directory(layout) / found.source),
            "newest": None if found is None else found.series.observations[-1].quarter_end.isoformat(),
            "lacking": _span(lacking),
        }
    return sources


def _gaps(spec: ChartSpec) -> list[dict[str, str]]:
    return [{"date": gap.date, "series": gap.series, "reason": gap.reason} for gap in spec.gaps]


def _invalid(state: State) -> list[dict[str, str]]:
    return [{"path": str(item.path), "reason": item.reason} for item in state.invalid]


def _tables(state: State) -> dict[str, str | None]:
    margin, futures = state.tables
    return {
        "margin_debt": str(margin) if margin.is_file() else None,
        "index_futures": str(futures) if futures.is_file() else None,
    }


def plan(layout: DataLayout, window: Window, now: datetime, refresh: bool = False) -> dict[str, Any]:
    """Read-only: what each source lacks, the invalid raw files, the tables, the report and the action."""
    now = to_eastern(now, "now")
    state = resolve(layout, window, now)
    report = _report(layout, state, now)
    return {
        "generated_at": et_isoformat(now),
        "window": _window(window),
        "refresh": refresh,
        "action": "fetch" if refresh else state.action(report),
        "sources": _sources(layout, state),
        "not_due": list(state.upcoming(now)),
        "gaps": _gaps(state.spec(layout, now)),
        "invalid_files": _invalid(state),
        "tables": _tables(state),
        "report": report.describe(),
    }


# ---------------------------------------------------------------------------------------- fetch


def _write_raw(directory: Path, names: Sequence[str], data: bytes) -> Path:
    """Write ``data`` under the first free name of ``names``; the path."""
    for name in names:
        try:
            return write_file(directory / name, data)
        except FileExists:
            continue
    raise ValueError(f"{names[0]}: {len(names)} raw files of one second exist")


def _outcome(status: str, path: Path | None = None, reason: str | None = None) -> dict[str, Any]:
    return {"status": status, "path": None if path is None else str(path), "reason": reason}


def _fetch_finra(client: Client, layout: DataLayout, state: State, refresh: bool) -> dict[str, Any]:
    if not (refresh or state.lacking_months()):
        result = _outcome(
            "reused", None if state.workbook is None else raw_directory(layout) / state.workbook.source
        )
        result["pending"] = _span(())
        return result
    try:
        data = client.get(finra.URL)
        fetched_at = client.now().replace(microsecond=0)
        workbook = finra.check_workbook(data, fetched_at, fetched_at)
    except (SourceError, ValueError) as error:
        result = _outcome(
            "failed", reason=f"{finra.URL}: {error}" if isinstance(error, ValueError) else str(error)
        )
        result["pending"] = _span(state.lacking_months())
        return result
    stored = None if state.workbook is None else state.workbook.workbook.balances
    if stored == workbook.balances:
        result = _outcome(
            "verified", raw_directory(layout) / state.workbook.source if state.workbook else None
        )
    else:
        names = [finra.raw_name(fetched_at, "" if n == 0 else f"_{n}") for n in range(finra.MAX_SUFFIX + 1)]
        result = _outcome("new", _write_raw(raw_directory(layout), names, data))
    newest_month = workbook.newest
    result["pending"] = _span(tuple(month for month in state.due_months(state.now) if month > newest_month))
    return result


def _fetch_cftc(client: Client, layout: DataLayout, state: State, refresh: bool) -> dict[str, Any]:
    wanted = state.due_weeks(state.now) if refresh else state.lacking_weeks()
    if not wanted:
        result = _outcome("reused")
        result["pending"] = _span(())
        return result
    first, last = week_days(wanted[0])[0], week_days(wanted[-1])[1]
    url = cftc.query_url(first, last)
    try:
        rows = cftc.parse_rows(client.get(url))
        fetched_at = client.now().replace(microsecond=0)
        answer = None
        if rows:
            value = {
                "request": url,
                "fetched_at": et_isoformat(fetched_at),
                "first": first.isoformat(),
                "last": last.isoformat(),
                "rows": rows,
            }
            answer = cftc.check_answer(value, None, fetched_at)
    except (SourceError, ValueError) as error:
        result = _outcome("failed", reason=f"{url}: {error}" if isinstance(error, ValueError) else str(error))
        result["pending"] = _span(state.lacking_weeks())
        return result
    received = set() if answer is None else {report.week for report in answer.reports}
    changed = answer is not None and any(
        report.week not in state.reports or state.reports[report.week].report.row != report.row
        for report in answer.reports
    )
    if changed and answer is not None:
        names = [
            cftc.raw_name(first, last, fetched_at, "" if n == 0 else f"_{n}")
            for n in range(cftc.MAX_SUFFIX + 1)
        ]
        result = _outcome("new", _write_raw(raw_directory(layout), names, cftc.dump(answer)))
    else:
        result = _outcome("verified")
    result["pending"] = _span(
        tuple(week for week in wanted if week not in received and week not in state.reports)
    )
    return result


def _fetch_series(
    client: Client, layout: DataLayout, state: State, name: str, refresh: bool
) -> dict[str, Any]:
    stored = state.series.get(name)
    stored_path = None if stored is None else raw_directory(layout) / stored.source
    if not (refresh or state.lacking_quarters(name)):
        result = _outcome("reused", stored_path)
        result["pending"] = _span(())
        return result
    url = fred.observations_url(name)
    try:
        response = fred.parse_response(client.get(url))
        fetched_at = client.now().replace(microsecond=0)
        value = {"series": name, "request": url, "fetched_at": et_isoformat(fetched_at), "response": response}
        item = fred.check_answer(value, None, fetched_at)
    except (SourceError, ValueError) as error:
        result = _outcome("failed", reason=f"{url}: {error}" if isinstance(error, ValueError) else str(error))
        result["pending"] = _span(state.lacking_quarters(name))
        return result
    if stored is not None and stored.series.content() == item.content():
        result = _outcome("verified", stored_path)
    else:
        names = [
            fred.raw_name(name, fetched_at, "" if n == 0 else f"_{n}") for n in range(fred.MAX_SUFFIX + 1)
        ]
        result = _outcome("new", _write_raw(raw_directory(layout), names, fred.dump(item)))
    held = set(item.by_quarter_end())
    result["pending"] = _span(tuple(end for end in state.due_quarters(state.now) if end not in held))
    return result


def fetch(
    layout: DataLayout, window: Window, now: datetime, client: Client, refresh: bool = False
) -> dict[str, Any]:
    """Request what each source lacks (everything the window needs with ``refresh``) and write
    what is new (see the module docstring)."""
    now = to_eastern(now, "now")
    state = resolve(layout, window, now)
    sources: dict[str, Any] = {
        "finra": _fetch_finra(client, layout, state, refresh),
        "cftc": _fetch_cftc(client, layout, state, refresh),
    }
    for name in fred.SERIES:
        sources[name] = _fetch_series(client, layout, state, name, refresh)
    return {
        "generated_at": et_isoformat(now),
        "window": _window(window),
        "refresh": refresh,
        "fred_key": "set",
        "requests": client.requests,
        "sources": sources,
        "invalid_files": _invalid(state),
    }


# --------------------------------------------------------------------------------- record, show


def _month(row: MarginRow) -> dict[str, Any]:
    balance = row.balance
    return {
        "month": balance.month.isoformat(),
        "debit_balances_musd": balance.debit,
        "yoy_pct": None if row.yoy.value is None else str(row.yoy.value),
        "market_value_quarter_end": row.quarter_end.isoformat(),
        "market_value_musd": None if row.market_value.value is None else str(row.market_value.value),
        "ratio_pct": None if row.ratio.value is None else str(row.ratio.value),
    }


def _week(row: FuturesRow) -> dict[str, Any]:
    report = row.report
    return {
        "report_date": report.as_of.isoformat(),
        "asset_mgr_net": report.asset_mgr_net,
        "asset_mgr_net_52w_percentile": None if row.asset_mgr.value is None else str(row.asset_mgr.value),
        "lev_money_net_short": report.lev_money_net_short,
        "lev_money_net_short_52w_percentile": None
        if row.lev_money.value is None
        else str(row.lev_money.value),
    }


def record(layout: DataLayout, window: Window, now: datetime) -> dict[str, Any]:
    """Rewrite the two tables from ``raw/`` and write a new report of the window.

    Every raw file must be valid and the window must hold a fetched month or week. The report
    is rendered in memory before any write, and a report of the same second refuses the run.
    """
    now = to_eastern(now, "now")
    state = resolve(layout, window, now)
    state.refuse_invalid()
    spec = state.spec(layout, now.replace(microsecond=0))  # the instant its name gives
    if spec.months_fetched + spec.weeks_fetched == 0:
        raise ValueError(
            f"no month or week of the window {window.start} to {window.end} is fetched; run fetch first"
        )
    stem, directory = _report_stem(window), layout.reports(FOLDER)
    twin, page = directory / stamped(stem, now, ".md"), directory / stamped(stem, now, ".html")
    # The twin first, so a page's presence (what freshness reads) implies its twin's.
    documents = [(twin, render_markdown(spec)), (page, render_html(spec, load_library()))]
    margin, futures = state.tables
    written = {
        "margin_debt": {
            "path": str(margin),
            "rows": len(state.margin),
            "written": write_table(margin, margin_text(state.margin.values())),
        },
        "index_futures": {
            "path": str(futures),
            "rows": len(state.futures),
            "written": write_table(futures, futures_text(state.futures.values())),
        },
    }
    for path, document in documents:
        write_file(path, document)
    return {
        "generated_at": et_isoformat(now),
        "window": _window(window),
        "months": [_month(entry.row) for entry in spec.months if entry.row is not None],
        "weeks": [_week(entry.row) for entry in spec.weeks if entry.row is not None],
        "lacking": {
            "months": [month.isoformat() for month in spec.missing_months],
            "weeks": [week.isoformat() for week in spec.missing_weeks],
            **{name: [end.isoformat() for end in state.lacking_quarters(name)] for name in fred.SERIES},
        },
        "not_due": list(spec.upcoming),
        "gaps": _gaps(spec),
        "tables": written,
        "report": {"status": "written", "path": str(page), "markdown": str(twin)},
    }


def show(layout: DataLayout, window: Window, now: datetime) -> str:
    """The window as Markdown, recomputed from ``raw/``, after one status line."""
    now = to_eastern(now, "now")
    state = resolve(layout, window, now)
    state.refuse_invalid()
    report = _report(layout, state, now)
    margin, futures = state.tables
    tables = " and ".join(str(path) for path in (margin, futures) if path.is_file()) or "none"
    status = (
        f"Action: {state.action(report)}. Tables: {tables}. "
        f"Report: {report.path or 'none'} ({report.status})."
    )
    spec = state.spec(layout, now)
    if spec.months_fetched + spec.weeks_fetched == 0:
        return f"{status}\n\nNo month or week of the window {window.start} to {window.end} is fetched.\n"
    return f"{status}\n\n{render_markdown(spec)}"
