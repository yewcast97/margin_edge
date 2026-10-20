"""Raw files: reading and validation, selection, derivation and the three tables.

The domain has one subject, the market, so each section of ``data/`` holds one folder,
``market/``, where a ticker domain holds one per ticker. ``fetch`` writes FINRA's workbooks
(``finra``), the CFTC's answers (``cftc``) and Cboe's VIX files (``cboe``) to
``raw/market/``. Every read validates every listed raw file; a file that fails is reported,
never skipped silently, until it is renamed with ``.rejected``, after which every read skips
it.

Selection: the newest valid workbook (by ``fetched_at``, then by name) is the workbook; the
newest valid VIX file, likewise, is the VIX history; per week, the report of the newest
valid CFTC answer holding that week is the week's report. Nothing else records what was
fetched.

``derive_margin`` gives every month of the workbook its row (its balances as FINRA
published them), ``derive_futures`` every stored week its row (the positions, the two nets
and their percentiles over 52 weeks) and ``derive_vix`` every XNYS session from the first of
the calendar the domain uses to the newest day of the VIX history its row (the close and its
percentile over 252 sessions), so a row rests on the whole archive, not on a report's
window. ``formatted/market/margin_debt.csv``, ``formatted/market/index_futures.csv`` and
``formatted/market/vix.csv`` hold them in date order and are rewritten from ``raw/`` by
``record``, each only when its bytes change.
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
from market_state_research.common.sessions import FIRST_SUPPORTED_DATE
from market_state_research.common.times import et_isoformat

from . import cboe, cftc, finra
from .cboe import Bar, History
from .cftc import Answer, Report
from .finra import Balance, Workbook
from .indicators import Percentile, percentile, session_percentile
from .periods import Month, sessions_within, week_of

DATA_DIRECTORY: Final = Path(__file__).resolve().parent.parent / "data"
FOLDER: Final = "market"  # the one folder of each section
MARGIN_CSV: Final = "margin_debt.csv"
FUTURES_CSV: Final = "index_futures.csv"
VIX_CSV: Final = "vix.csv"
RAW_NAMES: Final = "finra_margin_TOKEN.xlsx, cftc_tff_FIRST_LAST_TOKEN.json or cboe_vix_TOKEN.csv.gz"
FIRST_WEEK: Final = week_of(cftc.FIRST_REPORT)
MARGIN_COLUMNS: Final = (
    "month",
    "debit_balances_musd",
    "free_credit_cash_musd",
    "free_credit_margin_musd",
    "source",
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
VIX_COLUMNS: Final = ("date", "close", "close_252s_percentile", "source")


@dataclass(frozen=True)
class WorkbookFile:
    workbook: Workbook
    source: str


@dataclass(frozen=True)
class AnswerFile:
    answer: Answer
    source: str


@dataclass(frozen=True)
class HistoryFile:
    history: History
    source: str


@dataclass(frozen=True)
class InvalidFile:
    path: Path
    reason: str


@dataclass(frozen=True)
class Raw:
    """Every listed raw file, validated: the workbooks, the CFTC answers, the VIX files and the
    invalid files."""

    workbooks: tuple[WorkbookFile, ...]
    answers: tuple[AnswerFile, ...]
    histories: tuple[HistoryFile, ...]
    invalid: tuple[InvalidFile, ...]


@dataclass(frozen=True)
class Stored:
    """One week's report, the time its answer arrived and the answer's file name."""

    report: Report
    fetched_at: datetime
    source: str


@dataclass(frozen=True)
class MarginRow:
    """One month of the workbook: its balances and the workbook's file name."""

    balance: Balance
    source: str


@dataclass(frozen=True)
class FuturesRow:
    """One stored week: its report, the percentiles of its two nets, and where it came from."""

    stored: Stored
    asset_mgr: Percentile
    lev_money: Percentile

    @property
    def report(self) -> Report:
        return self.stored.report


@dataclass(frozen=True)
class VixRow:
    """One XNYS session the VIX history reaches: its bar (None when Cboe's file holds none), the
    percentile of its close over 252 sessions, and the file's name."""

    session: date
    bar: Bar | None
    percentile: Percentile
    source: str

    @property
    def close(self) -> Decimal | None:
        return None if self.bar is None else self.bar.close_value


def raw_directory(layout: DataLayout) -> Path:
    return layout.raw(FOLDER)


def csv_paths(layout: DataLayout) -> tuple[Path, Path, Path]:
    """The margin debt table, the index futures table and the VIX table."""
    directory = layout.formatted(FOLDER)
    return directory / MARGIN_CSV, directory / FUTURES_CSV, directory / VIX_CSV


def read_raw(layout: DataLayout, now: datetime) -> Raw:
    """Every listed raw file, validated (see the module docstring)."""
    workbooks: list[WorkbookFile] = []
    answers: list[AnswerFile] = []
    histories: list[HistoryFile] = []
    invalid: list[InvalidFile] = []
    for path in listed(raw_directory(layout)):
        name = path.name
        try:
            if finra.RAW_NAME.fullmatch(name):
                workbooks.append(WorkbookFile(finra.read_workbook(path.read_bytes(), name, now), name))
            elif cftc.RAW_NAME.fullmatch(name):
                answers.append(AnswerFile(cftc.read_answer(path.read_bytes(), name, now), name))
            elif cboe.RAW_NAME.fullmatch(name):
                histories.append(HistoryFile(cboe.read_history(path.read_bytes(), name, now), name))
            else:
                invalid.append(InvalidFile(path, f"not a raw file name ({RAW_NAMES})"))
        except ValueError as error:
            invalid.append(InvalidFile(path, str(error)))
    return Raw(tuple(workbooks), tuple(answers), tuple(histories), tuple(invalid))


def select_workbook(files: Iterable[WorkbookFile]) -> WorkbookFile | None:
    """The newest workbook (by ``fetched_at``, then by name), or None."""
    return max(files, key=lambda item: (item.workbook.fetched_at, item.source), default=None)


def select_history(files: Iterable[HistoryFile]) -> HistoryFile | None:
    """The newest VIX file (by ``fetched_at``, then by name), or None."""
    return max(files, key=lambda item: (item.history.fetched_at, item.source), default=None)


def select_reports(files: Iterable[AnswerFile]) -> dict[date, Stored]:
    """Per week, the report of the newest answer holding it (by ``fetched_at``, then by name),
    by the Tuesday naming the week, ascending."""
    weeks: dict[date, Stored] = {}
    for item in sorted(files, key=lambda item: (item.answer.fetched_at, item.source)):
        for report in item.answer.reports:
            weeks[report.week] = Stored(report, item.answer.fetched_at, item.source)
    return dict(sorted(weeks.items()))


def derive_margin(workbook: WorkbookFile | None) -> dict[Month, MarginRow]:
    """Every month of the workbook's row, by month, ascending."""
    if workbook is None:
        return {}
    return {
        month: MarginRow(balance, workbook.source) for month, balance in workbook.workbook.by_month().items()
    }


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


def derive_vix(history: HistoryFile | None) -> dict[date, VixRow]:
    """Every XNYS session's row from the first of the calendar the domain uses to the newest
    day of the VIX history, ascending (see the module docstring)."""
    if history is None:
        return {}
    bars = history.history.by_day()
    sessions = sessions_within(FIRST_SUPPORTED_DATE, history.history.newest)
    closes = {session: bars[session].close_value for session in sessions if session in bars}
    return {
        session: VixRow(
            session, bars.get(session), session_percentile(sessions, index, closes), history.source
        )
        for index, session in enumerate(sessions)
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
                row.source,
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


def vix_text(rows: Iterable[VixRow]) -> str:
    """The VIX table of ``rows`` in the given order: the close as Cboe wrote it."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(VIX_COLUMNS)
    for row in rows:
        close = "" if row.bar is None else row.bar.close
        writer.writerow([row.session.isoformat(), close, _text(row.percentile.value), row.source])
    return buffer.getvalue()


def write_table(path: Path, text: str) -> bool:
    """Write ``text`` to ``path`` unless it already holds exactly it; whether it wrote."""
    data = text.encode("utf-8")
    if path.is_file() and path.read_bytes() == data:
        return False
    write_file(path, data, overwrite=True)
    return True
