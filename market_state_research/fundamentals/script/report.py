"""The ticker's time series: its periods' per-document reports compiled into one Markdown file.

``render_series`` is a pure function of a ticker's periods (each with its files and the
passing reports of its documents) and the time it is generated: the same inputs give the
same text except for the one ``Generated ...`` line, so ``same_series`` compares two
series apart from that line, and ``plan`` judges the newest series file fresh when it is
the series rendered now. A period is ``complete`` when every one of its EDGAR documents
is in ``raw/``, its earnings call is settled (its transcript in ``raw/``, or shown
unavailable by the transcript provider's list: ``documents.CallState``), and each of its
documents (its 10-K or 10-Q, every EX-99 exhibit, every call) has a report that passes
``check``. The series holds one section per complete period, newest first: its documents
(a period whose call is shown unavailable says so, with the date of the list that shows
it), then the eleven fields (``research.FIELD_TITLES``), each quote as ``> text`` followed
by ``— {document label}`` and the speaker the report names, and ``None found in the
period's documents.`` for a field without a quote. A coverage table lists every period
whose 10-K or 10-Q is in ``raw/``, complete, ``incomplete`` (naming what is missing) or
``not researched`` (no report of its documents), with its call: ``transcript``,
``unavailable (provider lists no call as of DATE)``, ``waiting`` or ``missing``. The
as-of date is the filing date of the newest filing or exhibit of the complete periods
(``report_as_of``).

The series states what the documents say and adds no valuation, forecast, rating or
investment opinion of its own; its fixed text passes ``research.WORDING``. Quotes are
shown as the reports write them, their lines joined by one space: ``check`` holds every
quote to the derived text's own characters, so the series shows the document's words.
"""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Literal

from market_state_research.common.layout import listed, name_instant, stamped
from market_state_research.common.text import printable
from market_state_research.common.times import TOKEN_PATTERN, et_display, to_eastern

from .documents import Document, PeriodFiles
from .research import FIELD_TITLES, FIELDS, Report

TITLE = "Issuer disclosures"
GENERATED = "Generated "
NONE_FOUND = "None found in the period's documents."
NO_COMPLETE_PERIOD = "no period is complete: every document of a period needs a report that passes check"
CALL_MISSING = "the earnings call's transcript is not in raw/"
CALL_WAITING = "the earnings call is not listed yet"
NOT_IN_RAW = "documents not in raw/"
UNAVAILABLE = "unavailable (provider lists no call as of {as_of})"
_NONE = "—"

PeriodStatus = Literal["complete", "incomplete", "not researched"]


@dataclass(frozen=True)
class SeriesPeriod:
    """One period whose 10-K or 10-Q is in ``raw/``: its files and the passing report of each
    of its documents that has one (by ``DOC_ID``)."""

    files: PeriodFiles
    reports: Mapping[str, Report]

    @property
    def missing(self) -> tuple[str, ...]:
        """What keeps the period from being complete: documents not in ``raw/``, an unsettled
        call and the documents without a passing report, by ``DOC_ID``; empty when complete."""
        missing = [] if self.files.missing is None else [NOT_IN_RAW]
        if self.files.call.status == "missing":
            missing.append(CALL_MISSING)
        elif self.files.call.status == "waiting":
            missing.append(CALL_WAITING)
        missing.extend(
            document.doc_id for document in self.files.documents if document.doc_id not in self.reports
        )
        return tuple(missing)

    @property
    def status(self) -> PeriodStatus:
        if not self.missing:
            return "complete"
        return "incomplete" if self.reports else "not researched"


def report_as_of(periods: Sequence[SeriesPeriod]) -> date:
    """The filing date of the newest 10-K, 10-Q or EX-99 exhibit of the complete ``periods``."""
    filed = [
        document.filed
        for period in periods
        if period.status == "complete"
        for document in period.files.documents
        if document.filed is not None
    ]
    if not filed:
        raise ValueError(NO_COMPLETE_PERIOD)
    return max(filed)


def series_name(ticker: str, as_of: date, now: datetime) -> str:
    """``{T}_{AS_OF}_{token}.md``: a series file's name."""
    return stamped(f"{ticker}_{as_of.isoformat()}", now, ".md")


def series_files(directory: Path, ticker: str) -> list[Path]:
    """The ticker's series files in ``directory`` (``reports/{T}/``), every other file left out."""
    pattern = re.compile(
        rf"{re.escape(ticker)}_[0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}}_{TOKEN_PATTERN}\.md", re.ASCII
    )
    return [path for path in listed(directory, ".md") if pattern.fullmatch(path.name)]


def newest_series(directory: Path, ticker: str, now: datetime) -> Path | None:
    """The series file whose name's token is the latest not after ``now`` (never ordered as text)."""
    limit = to_eastern(now, "now")
    named = [
        (instant, path) for path in series_files(directory, ticker) if (instant := name_instant(path.name))
    ]
    candidates = [(instant, path) for instant, path in named if instant <= limit]
    return max(candidates)[1] if candidates else None


def same_series(first: str, second: str) -> bool:
    """Whether two series texts are the same apart from their ``Generated`` line."""
    return _content(first) == _content(second)


def _content(text: str) -> list[str]:
    return [line for line in text.split("\n") if not line.startswith(GENERATED)]


# --------------------------------------------------------------------------- Markdown


def _cell(text: str) -> str:
    return printable(text).replace("|", "\\|")


def _row(*cells: str) -> str:
    return "| " + " | ".join(_cell(cell) for cell in cells) + " |"


def _call_line(document: Document) -> str:
    held = _NONE if document.call is None else document.call.day.isoformat()
    return f"Earnings call: {document.title}, held {held}, transcript (`{document.doc_id}`)"


def call_label(files: PeriodFiles) -> str:
    """The period's call as the coverage table names it."""
    call = files.call
    if call.status == "unavailable" and call.as_of is not None:
        return UNAVAILABLE.format(as_of=call.as_of.isoformat())
    return call.status


def _document_lines(files: PeriodFiles) -> list[str]:
    filing = files.period.filing
    lines = []
    if files.filing is not None:
        lines.append(f"{filing.form} {filing.accession}, filed {filing.filed} (`{files.filing.doc_id}`)")
    for release in files.releases:
        for row, document in release.exhibits:
            if document is not None:
                lines.append(
                    f"{row.exhibit} {row.document} of the 8-K {release.release.accession} dated "
                    f"{release.release.report_date}, filed {release.release.filed} (`{document.doc_id}`)"
                )
    lines.extend(_call_line(document) for document in files.calls)
    if files.call.status == "unavailable" and files.call.as_of is not None:
        lines.append(
            f"Earnings call: none listed by the transcript provider (EarningsCalls.dev) as of "
            f"{files.call.as_of.isoformat()}"
        )
    return [f"- {printable(line)}" for line in lines]


def _period_lines(period: SeriesPeriod) -> list[str]:
    files = period.files
    lines = [f"## {files.day.isoformat()}", "", *_document_lines(files), ""]
    documents = {document.doc_id: document for document in files.documents}
    for name in FIELDS:
        lines.extend([f"### {FIELD_TITLES[name]}", ""])
        quoted = [
            (documents[doc_id], quote)
            for doc_id, report in period.reports.items()
            for quote in report.field(name)
        ]
        if not quoted:
            lines.extend([NONE_FOUND, ""])
        for document, quote in quoted:
            caption = document.label if quote.speaker is None else f"{document.label}, {quote.speaker}"
            lines.extend([f"> {printable(quote.text)}", "", f"— {printable(caption)}", ""])
    return lines


def _coverage_lines(periods: Sequence[SeriesPeriod]) -> list[str]:
    header = ("Period", "Status", "Earnings call", "Documents", *(FIELD_TITLES[name] for name in FIELDS))
    rows = [_row(*header), _row(*("---" for _ in header))]
    for period in periods:
        status: str = period.status
        if period.status == "incomplete":
            status = f"incomplete: missing {', '.join(period.missing)}"
        counts = [
            str(sum(len(report.field(name)) for report in period.reports.values()))
            if period.status == "complete"
            else _NONE
            for name in FIELDS
        ]
        rows.append(
            _row(
                period.files.day.isoformat(),
                status,
                call_label(period.files),
                str(len(period.files.documents)),
                *counts,
            )
        )
    return rows


def _ordered(period: SeriesPeriod) -> SeriesPeriod:
    """The period with its reports in the order of its documents."""
    reports = {
        document.doc_id: period.reports[document.doc_id]
        for document in period.files.documents
        if document.doc_id in period.reports
    }
    return SeriesPeriod(period.files, reports)


def render_series(
    ticker: str, cik: str, entity_name: str, periods: Sequence[SeriesPeriod], generated: datetime
) -> tuple[date, str]:
    """The as-of date and the Markdown series of ``periods`` (every period whose 10-K or 10-Q is
    in ``raw/``), generated at ``generated``; ``ValueError`` when none is complete."""
    ordered = sorted(
        (_ordered(period) for period in periods), key=lambda period: period.files.day, reverse=True
    )
    as_of = report_as_of(ordered)
    complete = [period for period in ordered if period.status == "complete"]
    days = ", ".join(period.files.day.isoformat() for period in complete)
    lines = [
        f"# {ticker} · {TITLE} · as of {as_of.isoformat()}",
        "",
        f"{GENERATED}{et_display(generated)}.",
        "",
        printable(
            f"{entity_name}, CIK {cik}. {len(complete)} of {len(ordered)} periods with documents in raw/ "
            f"are complete: {days}. As of {as_of.isoformat()}, the filing date of the newest filing or "
            "exhibit of the complete periods."
        ),
        "",
    ]
    for period in complete:
        lines.extend(_period_lines(period))
    lines.extend(["## Coverage", "", *_coverage_lines(ordered), ""])
    return as_of, "\n".join(lines)
