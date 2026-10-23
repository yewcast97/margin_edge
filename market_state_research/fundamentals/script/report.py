"""A season's report: every item's level, the score, and the triggered items with their evidence.

``render_report`` is a pure function of a season (its files, its Python items in
``measures.md`` and the bot's passing readings) and the time it is generated: the same inputs
give the same text but for the one ``Generated ...`` line, so ``same_report`` compares two
reports apart from that line, and ``plan`` judges the newest report of a season fresh when it
is the report rendered now. ``render`` writes it as ``reports/{T}/{PERIOD}/report_{TOKEN}.md``
and never overwrites one.

The report states, under its title, the issuer, the season, its call and the seasons its
baselines name, then the score: red counts 10, yellow 3, grey 1 (``items.SCORES``), a weighted
count of the comparisons that triggered against the stated baselines, never a valuation;
then every triggered item, red first, then yellow, then grey, each with what it compared, its
values or observation, its rule and its quotes with their documents; then the nine sections
(``items.SECTIONS``) with every item's level. Its fixed text passes ``readings.WORDING``.
"""

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Final

from market_state_research.common.layout import listed, name_instant, stamped
from market_state_research.common.times import TOKEN_PATTERN, et_display, to_eastern

from .documents import SeasonFiles
from .filings import Seasons
from .items import ITEMS, SECTIONS, Baseline, Item, score
from .measures import Measures, Reading, baseline_seasons
from .readings import ItemReading, Readings

GENERATED: Final = "Generated "
REPORT_PREFIX: Final = "report"
NONE_TRIGGERED: Final = "None of the items triggered."
TRIGGER_ORDER: Final = ("red", "yellow", "grey")
_REPORT_NAME = re.compile(rf"{REPORT_PREFIX}_(?P<token>{TOKEN_PATTERN})\.md", re.ASCII)


@dataclass(frozen=True)
class Entry:
    """One item of the season as the report states it: its level, who read it, what it compared
    with, its values or observation, and the quotes (text, attribution) of a bot item."""

    item: Item
    level: str
    who: str
    baseline: str
    detail: str
    quotes: tuple[tuple[str, str], ...] = ()


def entries(measures: Measures, readings: Readings) -> tuple[Entry, ...]:
    """Every item of the catalogue, in order, from the Python items and the passing readings."""
    computed: Mapping[str, Reading] = {reading.item.id: reading for reading in measures.readings}
    read: Mapping[str, ItemReading] = {reading.item.id: reading for reading in readings.items}
    found: list[Entry] = []
    for item in ITEMS:
        if item.who == "none":
            found.append(Entry(item, "no source", "no source", "none", item.rule))
        elif item.who == "python":
            reading = computed[item.id]
            found.append(Entry(item, reading.level, "Python", reading.baseline, reading.values))
        else:
            bot = read[item.id]
            baseline = "; ".join(bot.baseline or ()) or "none"
            quotes = tuple(
                (quote.text, quote.doc_id if quote.speaker is None else f"{quote.doc_id}, {quote.speaker}")
                for quote in bot.quotes
            )
            found.append(Entry(item, bot.level or "", "bot", baseline, bot.observation or "", quotes))
    return tuple(found)


def season_score(found: Sequence[Entry]) -> int:
    return score({entry.item.id: entry.level for entry in found})


def _counts(found: Sequence[Entry]) -> str:
    levels = [entry.level for entry in found]
    statuses = ("not applicable", "not disclosed", "not computable", "no baseline", "unavailable")
    return ", ".join(f"{levels.count(status)} {status}" for status in statuses)


def score_line(found: Sequence[Entry]) -> str:
    """The report's score line."""
    levels = [entry.level for entry in found]
    who = [entry.item.who for entry in found]
    return (
        f"Score: {season_score(found)} ({levels.count('red')} red, {levels.count('yellow')} yellow, "
        f"{levels.count('grey')} grey) over {len(found)} items: {who.count('python')} read by Python, "
        f"{who.count('bot')} by the bot, {who.count('none')} without a source; {_counts(found)}."
    )


def _cell(text: str) -> str:
    return text.replace("|", "\\|")


def _triggered(found: Sequence[Entry]) -> list[str]:
    ordered = sorted(
        (entry for entry in found if entry.level in TRIGGER_ORDER),
        key=lambda entry: (TRIGGER_ORDER.index(entry.level), ITEMS.index(entry.item)),
    )
    if not ordered:
        return [NONE_TRIGGERED]
    lines: list[str] = []
    for entry in ordered:
        label = "values" if entry.who == "Python" else "observation"
        lines.extend(
            [
                f"### {entry.item.heading} · {entry.level}",
                "",
                f"baseline: {entry.baseline}",
                f"{label}: {entry.detail}",
                f"rule: {entry.item.rule}",
            ]
        )
        for text, attribution in entry.quotes:
            lines.extend(["", f"> {text}", f"— {attribution}"])
        lines.append("")
    return lines[:-1]


def _section(number: int, found: Sequence[Entry]) -> list[str]:
    lines = [
        f"## {number} {SECTIONS[number]}",
        "",
        "| Item | Level | Read by | Baseline | Values or observation |",
        "| --- | --- | --- | --- | --- |",
    ]
    for entry in found:
        if entry.item.section == number:
            lines.append(
                f"| {_cell(entry.item.heading)} | {entry.level} | {entry.who} | {_cell(entry.baseline)} | "
                f"{_cell(entry.detail)} |"
            )
    return lines


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
    found = entries(measures, readings)
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
        score_line(found),
        "",
        "## Triggered",
        "",
        *_triggered(found),
    ]
    for number in SECTIONS:
        lines.extend(["", *_section(number, found)])
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


def ranking(rows: Iterable[tuple[str, str, Sequence[Entry], str]]) -> list[str]:
    """The ranking ``show`` prints: per ticker its newest season's score, highest first; ``rows``
    are (ticker, season, entries, report path)."""
    ordered = sorted(rows, key=lambda row: (-season_score(row[2]), row[0]))
    lines = [
        "| Ticker | Season | Score | red | yellow | grey | Report |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for ticker, season, found, path in ordered:
        levels = [entry.level for entry in found]
        lines.append(
            f"| {ticker} | {season} | {season_score(found)} | {levels.count('red')} | "
            f"{levels.count('yellow')} | {levels.count('grey')} | {path} |"
        )
    return lines
