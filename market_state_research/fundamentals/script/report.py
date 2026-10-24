"""A comparison's report: every item the bot found of each aspect, its new and old values side by
side with their difference, and the evidence they rest on.

``render_report`` is a pure function of a season (its files and the raw tree's listing), one of
its comparisons, the bot's passing readings of it and the time it is generated: the same inputs
give the same text but for the one ``Generated ...`` line, so ``same_report`` compares two
reports apart from that line, and ``plan`` judges the newest report of a comparison fresh when
it is the report rendered now. ``render`` writes it as
``reports/{T}/{PERIOD}/report_{KIND}_{TOKEN}.md`` and never overwrites one.

The report states, under its title, the issuer, the season and its call, the comparison (its
kind and its baseline season), the documents of each side in ``raw/`` and, for the newest
listed season, the filings and calls dated after its 10-K or 10-Q was filed, which Rule B
places once the next season is listed; then how many items it lists and the aspects without
one; then one section per aspect, in the aspects' order (``aspects.ASPECTS``): a table of its
items in the readings' order, each row the item's title, its new value with the season's
documents it rests on, its old value with the baseline's and the difference, or the line
``na``; then ``## Evidence``, per item in the same order, the documents of each side and the
quotes. No threshold, weight, score or rank applies, and no item is left out. Its fixed text
passes ``readings.WORDING``.
"""

import re
from datetime import datetime
from pathlib import Path
from typing import Final

from market_state_research.common.layout import listed, name_instant, stamped
from market_state_research.common.times import TOKEN_PATTERN, et_display, to_eastern

from .aspects import ASPECTS, KINDS, Comparison, Kind
from .documents import RawState, SeasonFiles
from .readings import NA, NO_BASELINE, Item, Readings
from .sheet import baseline_documents, call_line, season_name

GENERATED: Final = "Generated "
REPORT_PREFIX: Final = "report"
NONE: Final = "none"
_REPORT_NAME = re.compile(
    rf"{REPORT_PREFIX}_(?P<kind>{'|'.join(KINDS)})_(?P<token>{TOKEN_PATTERN})\.md", re.ASCII
)


def _cell(text: str) -> str:
    return text.replace("|", "\\|")


def _side(value: str | None, documents: tuple[str, ...] | None) -> str:
    """A value and the documents it rests on; ``na`` and ``no baseline`` stand alone."""
    shown = value or NA
    if shown in (NA, NO_BASELINE) or not documents:
        return shown
    return f"{shown} · {'; '.join(documents)}"


def _comparison_line(found: Comparison) -> str:
    if found.kind == "quarter":
        against = "this season against the previous season"
        baseline = None if found.baseline is None else season_name(found.baseline)
    else:
        against = "this 10-K season against the previous 10-K season"
        baseline = None if found.baseline is None else str(found.baseline.period)
    return f"Comparison: {found.kind}: {against}" + (
        ": none is listed." if baseline is None else f", {baseline}."
    )


def _pending_line(raw: RawState, files: SeasonFiles) -> list[str]:
    """The filings and calls dated after the newest listed season's 10-K or 10-Q was filed, for that
    season's report alone."""
    listing = raw.listing
    if listing is None or not listing.seasons or listing.seasons[-1].period != files.day:
        return []
    found = [f"the {item.form} {item.accession} dated {item.dated}" for item in listing.pending]
    found += [f"the call {event.id} of {event.day}" for event in raw.pending_calls]
    form = files.season.filing.form
    return [f"Pending, dated after the season's {form} was filed: {'; '.join(found) or NONE}."]


def _counts_line(readings: Readings) -> str:
    count = len(readings.items)
    without = [
        aspect.title
        for aspect in ASPECTS
        if (section := readings.section(aspect.key)) is None or not section.items
    ]
    noun = "item" if count == 1 else "items"
    return f"{count} {noun} in {len(ASPECTS)} aspects; aspects without an item: {', '.join(without) or NONE}."


def _table(items: tuple[Item, ...]) -> list[str]:
    lines = ["| Item | New | Old | Difference |", "| --- | --- | --- | --- |"]
    for item in items:
        cells = (
            item.title,
            _side(item.new, item.season),
            _side(item.old, item.baseline),
            item.difference or NA,
        )
        lines.append("| " + " | ".join(_cell(cell) for cell in cells) + " |")
    return lines


def _aspects(readings: Readings) -> list[str]:
    lines: list[str] = []
    for aspect in ASPECTS:
        section = readings.section(aspect.key)
        items = () if section is None else section.items
        lines.extend([f"## {aspect.title}", "", *(_table(items) if items else [NA]), ""])
    return lines


def _evidence(readings: Readings) -> list[str]:
    lines = ["## Evidence", ""]
    if not readings.items:
        return [*lines, NA]
    for aspect, item in readings.items:
        lines.extend(
            [
                f"### {aspect.title} · {item.title}",
                "",
                f"season: {'; '.join(item.season or ()) or NONE}",
                f"baseline: {'; '.join(item.baseline or ()) or NONE}",
            ]
        )
        for quote in item.quotes:
            attribution = quote.doc_id if quote.speaker is None else f"{quote.doc_id}, {quote.speaker}"
            lines.extend(["", f"> {quote.text}", f"— {attribution}"])
        lines.append("")
    return lines[:-1]


def render_report(
    raw: RawState, files: SeasonFiles, found: Comparison, readings: Readings, generated_at: datetime
) -> str:
    """The report of ``found``, a comparison of ``files``' season (module docstring)."""
    own = files.season.filing
    season_documents = "; ".join(document.doc_id for document in files.documents) or NONE
    baseline = "; ".join(baseline_documents(raw, found)) or f"{NONE} in raw/"
    lines = [
        f"# {raw.ticker} · {files.day} · {found.kind} report",
        "",
        f"{GENERATED}{et_display(to_eastern(generated_at, 'generated_at'))}.",
        "",
        f"Issuer: {raw.entity_name} (CIK {raw.cik}). Season: the {own.form} for the period ended "
        f"{own.period} (accession {own.accession}, filed {own.filed}). {call_line(files.call)}",
        _comparison_line(found),
        f"The season's documents: {season_documents}.",
        f"The baseline's documents: {baseline}.",
        *_pending_line(raw, files),
        "",
        _counts_line(readings),
        "",
        *_aspects(readings),
        *_evidence(readings),
    ]
    return "\n".join(lines) + "\n"


def report_name(kind: Kind, moment: datetime) -> str:
    """A report's file name: ``report_{KIND}_{TOKEN}.md``, the token naming ``moment``."""
    return stamped(f"{REPORT_PREFIX}_{kind}", moment, ".md")


def report_files(directory: Path, kind: Kind) -> list[Path]:
    """The reports of ``kind`` in ``directory``, whatever their token."""
    return [
        path
        for path in listed(directory, ".md")
        if (match := _REPORT_NAME.fullmatch(path.name)) is not None and match["kind"] == kind
    ]


def newest_report(directory: Path, kind: Kind, now: datetime) -> Path | None:
    """The report of ``kind`` whose token names the latest instant not after ``now``, or None."""
    moment = to_eastern(now, "now")
    best: tuple[datetime, Path] | None = None
    for path in report_files(directory, kind):
        instant = name_instant(path.name)
        if instant is None or instant > moment:
            continue
        if best is None or instant > best[0]:
            best = (instant, path)
    return None if best is None else best[1]


def _without_generated(text: str) -> list[str]:
    return [line for line in text.splitlines() if not line.startswith(GENERATED)]


def same_report(held: str, rendered: str) -> bool:
    """Whether two reports are equal apart from their ``Generated`` line."""
    return _without_generated(held) == _without_generated(rendered)
