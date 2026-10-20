"""Raw files: reading and validation, selection, derivation and the two tables.

The domain has one subject, the market, so each section of ``data/`` holds one folder,
``market/``, where a ticker domain holds one per ticker. ``fetch`` writes FINRA's workbooks
(``finra``), the CFTC's answers (``cftc``) and FRED's answers (``fred``) to ``raw/market/``.
Every read validates every listed raw file; a file that fails is reported, never skipped
silently, until it is renamed with ``.rejected``, after which every read skips it.

Selection: the newest valid workbook (by ``fetched_at``, then by name) is the workbook; per
series, the newest valid FRED answer is the series; per week, the report of the newest valid
CFTC answer holding that week is the week's report. Nothing else records what was fetched.

``derive_margin`` gives every month of the workbook its row (the balances, the
year-over-year growth, the market value of its quarter end and the ratio, ``indicators``),
and ``derive_futures`` every stored week its row (the positions, the two nets and their
percentiles over 52 weeks), so a row rests on the whole archive, not on a report's window.
``formatted/market/margin_debt.csv`` and ``formatted/market/index_futures.csv`` hold them in
date order and are rewritten from ``raw/`` by ``record``, each only when its bytes change.
"""

import csv
import io
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Final

from market_state_research.common.layout import DataLayout, listed, write_file
from market_state_research.common.times import et_isoformat

from . import cftc, finra, fred
from .cftc import Answer, Report
from .finra import Balance, Workbook
from .indicators import Percentile, Value, growth, percentile, ratio
from .periods import Month, quarter_end_of, week_of, z1_due

DATA_DIRECTORY: Final = Path(__file__).resolve().parent.parent / "data"
FOLDER: Final = "market"  # the one folder of each section
MARGIN_CSV: Final = "margin_debt.csv"
FUTURES_CSV: Final = "index_futures.csv"
RAW_NAMES: Final = "finra_margin_TOKEN.xlsx, cftc_tff_FIRST_LAST_TOKEN.json or fred_SERIES_TOKEN.json"
FIRST_WEEK: Final = week_of(cftc.FIRST_REPORT)
MARGIN_COLUMNS: Final = (
    "month",
    "debit_balances_musd",
    "free_credit_cash_musd",
    "free_credit_margin_musd",
    "yoy_pct",
    "market_value_quarter_end",
    "market_value_musd",
    "ratio_pct",
    "source",
    "market_value_sources",
)
FUTURES_COLUMNS: Final = (
    "report_date",
    "contract_units",
    "multiplier",
    "open_interest",
    "asset_mgr_long",
    "asset_mgr_short",
    "asset_mgr_spread",
    "lev_money_long",
    "lev_money_short",
    "lev_money_spread",
    "asset_mgr_net_emini",
    "lev_money_net_short_emini",
    "asset_mgr_net_52w_percentile",
    "lev_money_net_short_52w_percentile",
    "fetched_at",
    "source",
)


@dataclass(frozen=True)
class WorkbookFile:
    workbook: Workbook
    source: str


@dataclass(frozen=True)
class AnswerFile:
    answer: Answer
    source: str


@dataclass(frozen=True)
class SeriesFile:
    series: fred.Series
    source: str


@dataclass(frozen=True)
class InvalidFile:
    path: Path
    reason: str


@dataclass(frozen=True)
class Raw:
    """Every listed raw file, validated: the workbooks, the CFTC and FRED answers and the invalid files."""

    workbooks: tuple[WorkbookFile, ...]
    answers: tuple[AnswerFile, ...]
    series: tuple[SeriesFile, ...]
    invalid: tuple[InvalidFile, ...]


@dataclass(frozen=True)
class Stored:
    """One week's report, the time its answer arrived and the answer's file name."""

    report: Report
    fetched_at: datetime
    source: str


@dataclass(frozen=True)
class MarginRow:
    """One month of the workbook: its balances, its growth and its ratio to the market value."""

    balance: Balance
    yoy: Value
    quarter_end: date
    market_value: Value
    ratio: Value
    source: str
    market_value_sources: tuple[str, ...]


@dataclass(frozen=True)
class FuturesRow:
    """One stored week: its report, the percentiles of its two nets, and where it came from."""

    stored: Stored
    asset_mgr: Percentile
    lev_money: Percentile

    @property
    def report(self) -> Report:
        return self.stored.report


def raw_directory(layout: DataLayout) -> Path:
    return layout.raw(FOLDER)


def csv_paths(layout: DataLayout) -> tuple[Path, Path]:
    """The margin debt table and the index futures table."""
    return layout.formatted(FOLDER) / MARGIN_CSV, layout.formatted(FOLDER) / FUTURES_CSV


def read_raw(layout: DataLayout, now: datetime) -> Raw:
    """Every listed raw file, validated (see the module docstring)."""
    workbooks: list[WorkbookFile] = []
    answers: list[AnswerFile] = []
    series: list[SeriesFile] = []
    invalid: list[InvalidFile] = []
    for path in listed(raw_directory(layout)):
        name = path.name
        try:
            if finra.RAW_NAME.fullmatch(name):
                workbooks.append(WorkbookFile(finra.read_workbook(path.read_bytes(), name, now), name))
            elif cftc.RAW_NAME.fullmatch(name):
                answers.append(AnswerFile(cftc.read_answer(path.read_bytes(), name, now), name))
            elif fred.RAW_NAME.fullmatch(name):
                series.append(SeriesFile(fred.read_answer(path.read_bytes(), name, now), name))
            else:
                invalid.append(InvalidFile(path, f"not a raw file name ({RAW_NAMES})"))
        except ValueError as error:
            invalid.append(InvalidFile(path, str(error)))
    return Raw(tuple(workbooks), tuple(answers), tuple(series), tuple(invalid))


def select_workbook(files: Iterable[WorkbookFile]) -> WorkbookFile | None:
    """The newest workbook (by ``fetched_at``, then by name), or None."""
    return max(files, key=lambda item: (item.workbook.fetched_at, item.source), default=None)


def select_series(files: Iterable[SeriesFile]) -> dict[str, SeriesFile]:
    """Per series, its newest answer (by ``fetched_at``, then by name)."""
    chosen: dict[str, SeriesFile] = {}
    for item in sorted(files, key=lambda item: (item.series.fetched_at, item.source)):
        chosen[item.series.series] = item  # ascending: the newest wins
    return chosen


def select_reports(files: Iterable[AnswerFile]) -> dict[date, Stored]:
    """Per week, the report of the newest answer holding it (by ``fetched_at``, then by name),
    by the Tuesday naming the week, ascending."""
    weeks: dict[date, Stored] = {}
    for item in sorted(files, key=lambda item: (item.answer.fetched_at, item.source)):
        for report in item.answer.reports:
            weeks[report.week] = Stored(report, item.answer.fetched_at, item.source)
    return dict(sorted(weeks.items()))


def _market_value(quarter_end: date, series: Mapping[str, SeriesFile]) -> tuple[Value, tuple[str, ...]]:
    """The market value at ``quarter_end``: the sum of the two series, or None and why."""
    total = Decimal(0)
    for name in fred.SERIES:
        found = series.get(name)
        if found is None:
            return Value(None, f"no FRED answer of {name} is stored"), ()
        observations = found.series.observations
        observation = found.series.by_quarter_end().get(quarter_end)
        if observation is None and quarter_end < observations[0].quarter_end:
            return Value(
                None, f"the stored {name} starts {observations[0].quarter_end}, after {quarter_end}"
            ), ()
        if observation is None:
            due = z1_due(quarter_end)
            last = observations[-1].quarter_end
            return Value(None, f"the stored {name} ends {last}, before {quarter_end} (Z.1 due {due})"), ()
        if observation.value is None:
            return Value(None, f"FRED gives no value of {name} for {quarter_end}"), ()
        total += observation.value
    if total <= 0:
        return Value(None, f"the market value of {quarter_end} is not positive"), ()
    return Value(total), tuple(series[name].source for name in fred.SERIES)


def derive_margin(workbook: WorkbookFile | None, series: Mapping[str, SeriesFile]) -> dict[Month, MarginRow]:
    """Every month of the workbook's row, by month, ascending (see the module docstring)."""
    if workbook is None:
        return {}
    balances = workbook.workbook.by_month()
    values: dict[date, tuple[Value, tuple[str, ...]]] = {}
    rows: dict[Month, MarginRow] = {}
    for month, balance in balances.items():
        earlier = month.shifted(-12)
        base = balances.get(earlier)
        if base is None:
            start = finra.FIRST_MONTH.isoformat()
            yoy = Value(None, f"no balance of {earlier.isoformat()} (FINRA's table starts {start})")
        elif base.debit <= 0:
            yoy = Value(None, f"the debit balance of {earlier.isoformat()} is not positive")
        else:
            yoy = Value(growth(balance.debit, base.debit))
        quarter_end = quarter_end_of(month)
        if quarter_end not in values:
            values[quarter_end] = _market_value(quarter_end, series)
        market_value, sources = values[quarter_end]
        share = (
            Value(None, market_value.reason)
            if market_value.value is None
            else Value(ratio(balance.debit, market_value.value))
        )
        rows[month] = MarginRow(balance, yoy, quarter_end, market_value, share, workbook.source, sources)
    return rows


def derive_futures(reports: Mapping[date, Stored]) -> dict[date, FuturesRow]:
    """Every stored week's row, by the Tuesday naming it, ascending (see the module docstring)."""
    nets = {week: item.report.asset_mgr_net for week, item in reports.items()}
    shorts = {week: item.report.lev_money_net_short for week, item in reports.items()}

    def stored(week: date) -> bool:
        return week in reports

    return {
        week: FuturesRow(
            stored=item,
            asset_mgr=percentile(week, nets, stored, FIRST_WEEK),
            lev_money=percentile(week, shorts, stored, FIRST_WEEK),
        )
        for week, item in sorted(reports.items())
    }


def _text(value: Decimal | int | None) -> str:
    return "" if value is None else str(value)


def margin_text(rows: Iterable[MarginRow]) -> str:
    """The margin debt table of ``rows`` in the given order."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(MARGIN_COLUMNS)
    for row in rows:
        balance = row.balance
        writer.writerow(
            [
                balance.month.isoformat(),
                balance.debit,
                balance.free_cash,
                _text(balance.free_margin),
                _text(row.yoy.value),
                row.quarter_end.isoformat(),
                _text(row.market_value.value),
                _text(row.ratio.value),
                row.source,
                " ".join(row.market_value_sources),
            ]
        )
    return buffer.getvalue()


def futures_text(rows: Iterable[FuturesRow]) -> str:
    """The index futures table of ``rows`` in the given order."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(FUTURES_COLUMNS)
    for row in rows:
        report = row.report
        writer.writerow(
            [
                report.as_of.isoformat(),
                report.row["contract_units"],
                report.multiplier,
                report.open_interest,
                report.asset_mgr_long,
                report.asset_mgr_short,
                report.asset_mgr_spread,
                report.lev_money_long,
                report.lev_money_short,
                report.lev_money_spread,
                report.asset_mgr_net,
                report.lev_money_net_short,
                _text(row.asset_mgr.value),
                _text(row.lev_money.value),
                et_isoformat(row.stored.fetched_at),
                row.stored.source,
            ]
        )
    return buffer.getvalue()


def write_table(path: Path, text: str) -> bool:
    """Write ``text`` to ``path`` unless it already holds exactly it; whether it wrote."""
    data = text.encode("utf-8")
    if path.is_file() and path.read_bytes() == data:
        return False
    write_file(path, data, overwrite=True)
    return True
