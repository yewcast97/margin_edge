"""A season's report: every item's old and new values, listed by importance, with its evidence.

``render_report`` is a pure function of a season (its files, its Python items in
``measures.md`` and the bot's passing readings) and the time it is generated: the same inputs
give the same text but for the one ``Generated ...`` line, so ``same_report`` compares two
reports apart from that line, and ``plan`` judges the newest report of a season fresh when it
is the report rendered now. ``render`` writes it as ``reports/{T}/{PERIOD}/report_{TOKEN}.md``
and never overwrites one.

The report states, under its title, the issuer, the season, its call and the seasons its
baselines name, then how many items it lists by importance and by hand; then ``## Items``, one
table of every item of the catalogue, none left out: the ``high`` items first, then ``medium``,
then ``low`` (``items.by_importance``), in catalogue order within each, one row per comparison
(a Python item may have several), each with its importance, item, baseline, old value, new
value and change; then ``## Evidence``, per item in the same order, its rule and what its
values rest on: the documents the bot read and its quotes, or Python's note. No threshold
judges, marks or leaves out a row. Its fixed text passes ``readings.WORDING``.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Final

from market_state_research.common.layout import listed, name_instant, stamped
from market_state_research.common.times import TOKEN_PATTERN, et_display, to_eastern

from .documents import SeasonFiles
from .filings import Season, Seasons
from .items import IMPORTANCE, ITEMS, Baseline, Item, by_importance
from .measures import NOTHING, Measures, Row, baseline_seasons
from .readings import Readings

GENERATED: Final = "Generated "
REPORT_PREFIX: Final = "report"
NO_SOURCE: Final = "no source"
HANDS: Final = {"python": "Python (measures.md)", "bot": "the bot (readings.md)", "none": "no source"}
_REPORT_NAME = re.compile(rf"{REPORT_PREFIX}_(?P<token>{TOKEN_PATTERN})\.md", re.ASCII)


@dataclass(frozen=True)
class Entry:
    """One item of the season as the report states it: its rows (one for a bot item or an item
    without a source), what the bot's baseline line names (``none``), the quotes (text,
    attribution) of a bot item and Python's note."""

    item: Item
    rows: tuple[Row, ...]
    documents: str = "none"
    quotes: tuple[tuple[str, str], ...] = ()
    note: str = ""


def _seasons(listing: Seasons, season: Season, kind: Baseline) -> str:
    """The item's baseline as the report's table names it: the kind and its listed seasons."""
    if kind == "none":
        return "none"
    found = baseline_seasons(listing, season, kind)
    return f"{kind} " + (
        ", ".join(f"{other.period} ({other.filing.form})" for other in found) or "none listed"
    )


def entries(
    listing: Seasons, files: SeasonFiles, measures: Measures, readings: Readings
) -> tuple[Entry, ...]:
    """Every item of the catalogue, in catalogue order, from the Python items and the passing
    readings."""
    found: list[Entry] = []
    for item in ITEMS:
        baseline = _seasons(listing, files.season, item.baseline)
        if item.who == "none":
            found.append(Entry(item, (Row("", baseline, NO_SOURCE, NO_SOURCE, NOTHING),)))
        elif item.who == "python":
            computed = measures.reading(item.id)
            found.append(Entry(item, computed.rows, note=computed.note))
        else:
            bot = readings.get(item.id)
            if bot is None:
                raise ValueError(f"the readings lack item {item.id}")
            quotes = tuple(
                (quote.text, quote.doc_id if quote.speaker is None else f"{quote.doc_id}, {quote.speaker}")
                for quote in bot.quotes
            )
            row = Row("", baseline, bot.old or "", bot.new or "", NOTHING)
            found.append(Entry(item, (row,), "; ".join(bot.baseline or ()) or "none", quotes))
    return tuple(found)


def ordered(found: Sequence[Entry]) -> tuple[Entry, ...]:
    """``found`` in the report's order (``items.by_importance``)."""
    by_item = {entry.item: entry for entry in found}
    return tuple(by_item[item] for item in by_importance(tuple(by_item)))


def counts_line(found: Sequence[Entry]) -> str:
    """The report's line counting its items by importance and by hand."""
    importance = [entry.item.importance for entry in found]
    who = [entry.item.who for entry in found]
    levels = ", ".join(f"{importance.count(level)} {level}" for level in IMPORTANCE)
    return (
        f"{len(found)} items, every one listed by importance ({levels}): {who.count('python')} read by "
        f"Python, {who.count('bot')} by the bot, {who.count('none')} without a source."
    )


def _cell(text: str) -> str:
    return text.replace("|", "\\|")


def _table(found: Sequence[Entry]) -> list[str]:
    lines = [
        "| Importance | Item | Baseline | Old | New | Change |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for entry in found:
        for row in entry.rows:
            item = entry.item.heading + (f" · {row.compared}" if row.compared else "")
            cells = (entry.item.importance, item, row.baseline, row.old, row.new, row.change)
            lines.append("| " + " | ".join(_cell(cell) for cell in cells) + " |")
    return lines


def _evidence(found: Sequence[Entry]) -> list[str]:
    lines: list[str] = []
    for entry in found:
        item = entry.item
        lines.extend(
            [
                f"### {item.heading}",
                "",
                f"importance: {item.importance}; read by {HANDS[item.who]}",
                f"rule: {item.rule}",
            ]
        )
        if item.who == "bot":
            lines.append(f"baseline: {entry.documents}")
        if entry.note:
            lines.append(f"note: {entry.note}")
        for text, attribution in entry.quotes:
            lines.extend(["", f"> {text}", f"— {attribution}"])
        lines.append("")
    return lines[:-1]


def _baselines_line(listing: Seasons, files: SeasonFiles) -> str:
    named = []
    kinds: tuple[Baseline, ...] = (
        "previous quarter",
        "same quarter last year",
        "previous 10-K",
        "previous proxy",
    )
    for kind in kinds:
        seasons = baseline_seasons(listing, files.season, kind)
        named.append(f"{kind} {seasons[0].period if seasons else 'none listed'}")
    return "Baselines: " + "; ".join(named) + "."


def render_report(
    ticker: str,
    cik: str,
    entity_name: str,
    listing: Seasons,
    files: SeasonFiles,
    measures: Measures,
    readings: Readings,
    generated_at: datetime,
) -> str:
    """The season's report (module docstring)."""
    own = files.season.filing
    found = ordered(entries(listing, files, measures, readings))
    call = files.call
    as_of = "" if call.as_of is None else f" as of the calls list of {call.as_of}"
    lines = [
        f"# {ticker} · {files.day} · season report",
        "",
        f"{GENERATED}{et_display(to_eastern(generated_at, 'generated_at'))}.",
        "",
        f"Issuer: {entity_name} (CIK {cik}). Season: the {own.form} for the period ended {own.period} "
        f"(accession {own.accession}, filed {own.filed}). Call: {call.status}{as_of}.",
        _baselines_line(listing, files),
        "",
        counts_line(found),
        "",
        "## Items",
        "",
        *_table(found),
        "",
        "## Evidence",
        "",
        *_evidence(found),
    ]
    return "\n".join(lines) + "\n"


def report_name(moment: datetime) -> str:
    """A report's file name: ``report_{TOKEN}.md``, the token naming ``moment``."""
    return stamped(REPORT_PREFIX, moment, ".md")


def report_files(directory: Path) -> list[Path]:
    """The season's report files in ``directory``, whatever their token."""
    return [path for path in listed(directory, ".md") if _REPORT_NAME.fullmatch(path.name)]


def newest_report(directory: Path, now: datetime) -> Path | None:
    """The report whose token names the latest instant not after ``now``, or None."""
    moment = to_eastern(now, "now")
    best: tuple[datetime, Path] | None = None
    for path in report_files(directory):
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
