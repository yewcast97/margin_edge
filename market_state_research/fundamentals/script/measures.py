"""A season's mechanical comparison: the Python items and ``measures.md``.

``season_measures`` reads one season of a ticker's ``raw/`` (``documents.RawState``) and
computes every Python item of the catalogue (``items.PYTHON_ITEMS``) from structured data
alone: the figures of EDGAR's company facts (``facts``), the listing's filings, the Form 4s,
the call transcripts' turns and durations and the derived texts' lengths. Each value is
computed exactly and rounded half-even once: percentages and percentage points to two
places, days to one, basis points from the rounded margins; each rule compares the rounded
values, so a reader can redo it from the file. The thresholds are this module's constants,
starting points changed only here.

``render_measures`` writes the result as ``formatted/{T}/{PERIOD}/measures.md``, a pure
function of ``raw/`` and this code: the season and its baselines (``baseline_seasons``, the
seasons each baseline of the catalogue names, with their documents' ``DOC_ID``s), the filings
of the season, the figures, the Python items (``baseline:``, ``values:``, ``rule:`` and
``level:`` lines) and the inputs the bot's items name. ``derive`` writes it; it is fresh while
equal to what it renders now. Its fixed text passes ``readings.WORDING``: it states figures
and comparisons, never a valuation.
"""

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, time, timedelta
from decimal import Decimal
from fractions import Fraction
from typing import Final

from market_state_research.common.sessions import next_session
from market_state_research.common.times import et_display

from .documents import Document, RawState, SeasonFiles
from .earningscalls import Transcript
from .facts import MEASURES, CompanyFacts, Figure, figure, quarter_days, year_ago
from .filings import HOLDER_FORMS, NOTICES, REGISTRATIONS, Season, Seasons
from .form4 import officers_selling
from .items import BY_ID, ITEMS, PYTHON_ITEMS, Baseline, Item

GROWTH_DROP: Final = Decimal(10)  # 2.1: percentage points
MARGIN_MOVE: Final = 200  # 2.2: basis points
CASH_RATIO_LOW: Final = Decimal("0.7")  # 2.3
CASH_RATIO_ONE: Final = Decimal(1)  # 2.3
DAYS_RISE: Final = Decimal(15)  # 2.4: days
RECEIVABLES_GAP: Final = Decimal(20)  # 2.5: percentage points
NET_DEBT_MOVE: Final = Decimal(25)  # 2.6: percent
NET_DEBT_FLOOR: Final = Decimal(1)  # 2.6: percent of equity
SHARES_MOVE: Final = Decimal(2)  # 2.10: percent
GOODWILL_ADDED: Final = Decimal(10)  # 2.11: percent of equity
SELLERS: Final = 2  # 5.7: officers
ANALYSTS_DROP: Final = Decimal(30)  # 8.5: percent
ANSWERS_DROP: Final = Decimal(30)  # 8.6: percent
CALL_DROP: Final = Decimal(30)  # 9.3: percent
LENGTH_MOVE: Final = Decimal(20)  # 9.4: percent
EIGHT_K_MULTIPLE: Final = 2  # 9.5
LATE: Final = time(16, 0)  # 9.1: New York time
RECORD_SEASONS: Final = 4  # 9.1, 9.5, 9.6
ANALYST: Final = "analyst"
EXECUTIVE: Final = "executive"
NONE: Final = "none"
NO_FACTS: Final = "no company facts are in raw/"
NOT_TRANSCRIBED: Final = "the call has no transcript in raw/ ({status})"


def _rounded(value: Fraction, places: int) -> Decimal:
    """``value`` rounded half-even to ``places`` decimal places, exactly; zero without a sign."""
    exact = round(value, places)  # Fraction rounding is half-even and exact
    result = (Decimal(exact.numerator) / Decimal(exact.denominator)).quantize(Decimal(1).scaleb(-places))
    return result.copy_abs() if result.is_zero() else result


def _change(now: Decimal, before: Decimal) -> Decimal | None:
    """``now`` against ``before`` in percent, two places; None when ``before`` is 0 or below."""
    if before <= 0:
        return None
    return _rounded((Fraction(now) / Fraction(before) - 1) * 100, 2)


def _number(value: Decimal | int | None, unit: str = "") -> str:
    if value is None:
        return "—"
    return f"{value:,} {unit}".rstrip()


def _count(count: int, noun: str, plural: str | None = None) -> str:
    return f"{count} {noun if count == 1 else plural or noun + 's'}"


# --------------------------------------------------------------------------- baselines


def baseline_seasons(listing: Seasons, season: Season, kind: Baseline) -> tuple[Season, ...]:
    """The listed seasons the baseline ``kind`` names for ``season``, newest first."""
    earlier = listing.before(season, 8)
    previous = earlier[:1]
    ago = year_ago(listing, season)
    annual = tuple(item for item in earlier if item.filing.form == "10-K")[:1]
    proxy = tuple(item for item in earlier if item.of_forms(("DEF 14A",)))[:1]
    found: tuple[Season, ...]
    if kind in ("previous quarter", "previous guidance"):
        found = previous
    elif kind == "same quarter last year":
        found = () if ago is None else (ago,)
    elif kind == "previous quarter and same quarter last year":
        found = previous + (() if ago is None else (ago,))
    elif kind == "previous 10-K":
        found = annual
    elif kind == "previous filings":
        found = previous + annual
    elif kind == "previous proxy":
        found = proxy
    elif kind == "previous eight seasons":
        found = earlier
    elif kind == "previous four seasons":
        found = earlier[:RECORD_SEASONS]
    else:
        found = ()
    return tuple(dict.fromkeys(found))


# --------------------------------------------------------------------------- readings


@dataclass(frozen=True)
class Reading:
    """One Python item of a season: what it compared with, the values, its rule and its level
    (a level or a status)."""

    item: Item
    baseline: str
    values: str
    level: str


def _reading(identifier: str, baseline: str, values: str, level: str) -> Reading:
    return Reading(BY_ID[identifier], baseline, values, level)


@dataclass
class _Context:
    """One season's inputs, the seasons it compares with and each figure read once."""

    raw: RawState
    listing: Seasons
    files: SeasonFiles
    derived: Callable[[Document], str]
    cache: dict[tuple[date, str], Figure]

    @property
    def season(self) -> Season:
        return self.files.season

    @property
    def facts(self) -> CompanyFacts | None:
        return self.raw.facts

    def previous(self) -> Season | None:
        earlier = self.listing.before(self.season, 1)
        return earlier[0] if earlier else None

    def ago(self, season: Season | None = None) -> Season | None:
        return None if season is None else year_ago(self.listing, season)

    def figure(self, season: Season | None, measure: str) -> Figure | None:
        """The figure, or None when the season is not listed or no company facts are read."""
        if season is None or self.facts is None:
            return None
        key = (season.period, measure)
        if key not in self.cache:
            self.cache[key] = figure(self.facts, self.listing, measure, season)
        return self.cache[key]

    def value(self, season: Season | None, measure: str) -> Decimal | None:
        found = self.figure(season, measure)
        return None if found is None else found.value

    def files_of(self, season: Season) -> SeasonFiles | None:
        return self.raw.season(season.period)


def _season_name(season: Season | None) -> str:
    return "none" if season is None else f"{season.period} ({season.filing.form})"


def _pair(label: str, now: Decimal | None, before: Decimal | None, unit: str) -> str:
    return f"{label} {_number(now, unit)} against {_number(before, unit)}"


def _growth_item(context: _Context) -> Reading:
    season, previous = context.season, context.previous()
    ago, previous_ago = context.ago(season), context.ago(previous)
    baseline = (
        f"same quarter last year {_season_name(ago)}; previous quarter {_season_name(previous)} "
        f"and its year-ago {_season_name(previous_ago)}"
    )
    if context.facts is None:
        return _reading("2.1", baseline, NO_FACTS, "not computable")
    if ago is None or previous is None or previous_ago is None:
        return _reading("2.1", baseline, "a season the comparison needs is not listed", "no baseline")
    parts, drops = [], []
    for measure, label in (("revenue", "revenue"), ("net_income", "net income")):
        now = _growth(context, season, ago, measure)
        before = _growth(context, previous, previous_ago, measure)
        if now is None or before is None:
            parts.append(f"{label}: not computable (a figure is missing, or a year-ago figure is 0 or below)")
            continue
        drops.append(before - now)
        parts.append(f"{label}: growth {now}% against {before}% a quarter earlier ({now - before:+} pp)")
    if not drops:
        return _reading("2.1", baseline, "; ".join(parts), "not computable")
    level = "yellow" if any(drop > GROWTH_DROP for drop in drops) else NONE
    return _reading("2.1", baseline, "; ".join(parts), level)


def _growth(context: _Context, season: Season, ago: Season, measure: str) -> Decimal | None:
    now, before = context.value(season, measure), context.value(ago, measure)
    return None if now is None or before is None else _change(now, before)


def _margin(context: _Context, season: Season | None, measure: str) -> Decimal | None:
    revenue, part = context.value(season, "revenue"), context.value(season, measure)
    if revenue is None or part is None or revenue <= 0:
        return None
    return _rounded(Fraction(part) / Fraction(revenue) * 100, 2)


def _margins_item(context: _Context) -> Reading:
    season, previous = context.season, context.previous()
    ago = context.ago(season)
    baseline = f"same quarter last year {_season_name(ago)}; previous quarter {_season_name(previous)}"
    if context.facts is None:
        return _reading("2.2", baseline, NO_FACTS, "not computable")
    if ago is None and previous is None:
        return _reading("2.2", baseline, "no baseline season is listed", "no baseline")
    parts, moves = [], []
    for measure, label in (("gross_profit", "gross margin"), ("operating_income", "operating margin")):
        now = _margin(context, season, measure)
        if now is None:
            parts.append(f"{label}: not computable")
            continue
        compared = False
        for name, other in (("a year ago", ago), ("a quarter ago", previous)):
            before = _margin(context, other, measure)
            if other is None or before is None:
                continue
            compared = True
            move = int((now - before) * 100)
            moves.append(abs(move))
            parts.append(f"{label} {now}% against {before}% {name} ({move:+d} bps)")
        if not compared:
            parts.append(f"{label} {now}%; no baseline margin is computable")
    if not moves:
        return _reading("2.2", baseline, "; ".join(parts), "not computable")
    level = "yellow" if any(move > MARGIN_MOVE for move in moves) else NONE
    return _reading("2.2", baseline, "; ".join(parts), level)


def _cash_ratio(context: _Context, season: Season | None) -> Decimal | None:
    cash, income = context.value(season, "operating_cash_flow"), context.value(season, "net_income")
    if cash is None or income is None or income <= 0:
        return None
    return _rounded(Fraction(cash) / Fraction(income), 2)


def _cash_item(context: _Context) -> Reading:
    season, previous = context.season, context.previous()
    ago, previous_ago = context.ago(season), context.ago(previous)
    baseline = (
        f"same quarter last year {_season_name(ago)}; previous quarter {_season_name(previous)} "
        f"and its year-ago {_season_name(previous_ago)}"
    )
    if context.facts is None:
        return _reading("2.3", baseline, NO_FACTS, "not computable")
    if ago is None:
        return _reading("2.3", baseline, "the same quarter last year is not listed", "no baseline")
    ratios = {name: _cash_ratio(context, other) for name, other in (("now", season), ("year ago", ago))}
    ratios |= {
        "previous": _cash_ratio(context, previous),
        "previous year ago": _cash_ratio(context, previous_ago),
    }
    values = "; ".join(
        f"{name} {'not computable' if ratio is None else ratio}" for name, ratio in ratios.items()
    )
    values = f"operating cash flow ÷ net income (none where net income is 0 or below): {values}"
    now, ago_ratio = ratios["now"], ratios["year ago"]
    if now is None or ago_ratio is None:
        return _reading("2.3", baseline, values, "not computable")
    fell = ago_ratio > CASH_RATIO_ONE and now < CASH_RATIO_LOW
    before, before_ago = ratios["previous"], ratios["previous year ago"]
    twice = (
        before is not None
        and before_ago is not None
        and now < CASH_RATIO_ONE
        and before < CASH_RATIO_ONE
        and ago_ratio >= CASH_RATIO_ONE
        and before_ago >= CASH_RATIO_ONE
    )
    return _reading("2.3", baseline, values, "red" if fell or twice else NONE)


def _days(context: _Context, season: Season, balance: str, flow: str) -> Decimal | None:
    held, moved, days = (
        context.value(season, balance),
        context.value(season, flow),
        quarter_days(context.listing, season),
    )
    if held is None or moved is None or days is None or moved <= 0:
        return None
    return _rounded(Fraction(held) * days / Fraction(moved), 1)


def _days_item(context: _Context) -> Reading:
    season, ago = context.season, context.ago(context.season)
    baseline = f"same quarter last year {_season_name(ago)}"
    if context.facts is None:
        return _reading("2.4", baseline, NO_FACTS, "not computable")
    if ago is None:
        return _reading("2.4", baseline, "the same quarter last year is not listed", "no baseline")
    parts, rises = [], []
    for name, balance, flow in (
        ("days of sales outstanding", "receivables", "revenue"),
        ("days of inventory", "inventory", "cost_of_revenue"),
        ("days of payables", "payables", "cost_of_revenue"),
    ):
        now, before = _days(context, season, balance, flow), _days(context, ago, balance, flow)
        if now is None or before is None:
            parts.append(f"{name}: not computable")
            continue
        rises.append(now - before)
        parts.append(f"{name} {now} against {before} ({now - before:+} days)")
    if not rises:
        return _reading("2.4", baseline, "; ".join(parts), "not computable")
    return _reading(
        "2.4", baseline, "; ".join(parts), "yellow" if any(rise > DAYS_RISE for rise in rises) else NONE
    )


def _receivables_item(context: _Context) -> Reading:
    season, ago = context.season, context.ago(context.season)
    baseline = f"same quarter last year {_season_name(ago)}"
    if context.facts is None:
        return _reading("2.5", baseline, NO_FACTS, "not computable")
    if ago is None:
        return _reading("2.5", baseline, "the same quarter last year is not listed", "no baseline")
    receivables, revenue = (
        _growth(context, season, ago, "receivables"),
        _growth(context, season, ago, "revenue"),
    )
    if receivables is None or revenue is None:
        return _reading("2.5", baseline, "receivables or revenue growth not computable", "not computable")
    gap = receivables - revenue
    values = f"receivables growth {receivables}% less revenue growth {revenue}%: {gap} pp"
    return _reading("2.5", baseline, values, "red" if gap > RECEIVABLES_GAP else NONE)


def _net_debt(context: _Context, season: Season | None) -> Decimal | None:
    debt, cash = context.value(season, "debt"), context.value(season, "cash")
    return None if debt is None or cash is None else debt - cash


def _net_debt_item(context: _Context) -> Reading:
    season, previous = context.season, context.previous()
    baseline = f"previous quarter {_season_name(previous)}"
    if context.facts is None:
        return _reading("2.6", baseline, NO_FACTS, "not computable")
    if previous is None:
        return _reading("2.6", baseline, "the previous quarter is not listed", "no baseline")
    now, before, equity = (
        _net_debt(context, season),
        _net_debt(context, previous),
        context.value(previous, "equity"),
    )
    values = (
        f"net debt {_number(now, 'USD')} against {_number(before, 'USD')}; previous quarter's equity "
        f"{_number(equity, 'USD')}"
    )
    if now is None or before is None or equity is None or equity <= 0:
        return _reading("2.6", baseline, values, "not computable")
    if (now < 0) != (before < 0) or abs(Fraction(before)) < Fraction(equity) * Fraction(NET_DEBT_FLOOR) / 100:
        return _reading("2.6", baseline, values + " (sign changed, or under 1% of equity)", "not computable")
    move = _rounded((Fraction(now) / Fraction(before) - 1) * 100, 2)
    return _reading("2.6", baseline, f"{values}; {move:+}%", "yellow" if abs(move) > NET_DEBT_MOVE else NONE)


def _shares_item(context: _Context) -> Reading:
    season, previous = context.season, context.previous()
    baseline = f"previous quarter {_season_name(previous)}"
    if context.facts is None:
        return _reading("2.10", baseline, NO_FACTS, "not computable")
    if season.filing.form == "10-K":
        return _reading("2.10", baseline, "a 10-K reports the year's average", "not computable")
    if previous is None:
        return _reading("2.10", baseline, "the previous quarter is not listed", "no baseline")
    now, before = context.value(season, "diluted_shares"), context.value(previous, "diluted_shares")
    values = _pair("weighted diluted shares", now, before, "shares")
    move = None if now is None or before is None else _change(now, before)
    if move is None:
        return _reading("2.10", baseline, values, "not computable")
    return _reading("2.10", baseline, f"{values} ({move:+}%)", "grey" if abs(move) > SHARES_MOVE else NONE)


def _goodwill_item(context: _Context) -> Reading:
    season, previous = context.season, context.previous()
    baseline = f"previous quarter {_season_name(previous)}"
    if context.facts is None:
        return _reading("2.11", baseline, NO_FACTS, "not computable")
    if previous is None:
        return _reading("2.11", baseline, "the previous quarter is not listed", "no baseline")
    now, before, equity = (
        context.value(season, "goodwill"),
        context.value(previous, "goodwill"),
        context.value(season, "equity"),
    )
    values = f"{_pair('goodwill', now, before, 'USD')}; equity {_number(equity, 'USD')}"
    if now is None or before is None or equity is None or equity <= 0:
        return _reading("2.11", baseline, values, "not computable")
    added = _rounded((Fraction(now) - Fraction(before)) / Fraction(equity) * 100, 2)
    return _reading(
        "2.11", baseline, f"{values}; added {added}% of equity", "yellow" if added > GOODWILL_ADDED else NONE
    )


def _sellers_item(context: _Context) -> Reading:
    files, cik = context.files, context.raw.cik or ""
    forms = files.form4s()
    others = sum(1 for _, form in forms if form.issuer != cik)
    sellers = officers_selling(forms, cik)
    listed = "; ".join(
        f"{seller.name} ({seller.title or 'officer'}, {', '.join(seller.accessions)})" for seller in sellers
    )
    values = (
        f"{_count(len(forms), 'Form 4')} read, {others} of another issuer left out; officers selling: "
        f"{len(sellers)}{': ' + listed if listed else ''}"
    )
    return _reading("5.7", NONE, values, "yellow" if len(sellers) >= SELLERS else NONE)


def _turns(transcripts: Sequence[Transcript]) -> list[tuple[str, str, int]]:
    """Each turn as (speaker, role, words), the season's calls in order."""
    return [
        (turn.speaker, turn.role, len(turn.text.split()))
        for transcript in transcripts
        for turn in transcript.turns
    ]


def _call_pair(
    context: _Context, identifier: str
) -> tuple[Sequence[Transcript], Sequence[Transcript], str] | Reading:
    """The season's and the previous season's transcripts, or the reading that says why not."""
    previous = context.previous()
    baseline = f"previous quarter {_season_name(previous)}"
    call = context.files.call
    if call.status != "transcript":
        return _reading(identifier, baseline, NOT_TRANSCRIBED.format(status=call.status), "unavailable")
    before = None if previous is None else context.files_of(previous)
    if before is None or before.call.status != "transcript":
        return _reading(
            identifier, baseline, "the previous season's call has no transcript in raw/", "no baseline"
        )
    return call.transcripts, before.call.transcripts, baseline


def _analysts(transcripts: Sequence[Transcript]) -> list[str]:
    return list(
        dict.fromkeys(
            " ".join(turn.speaker.split())
            for transcript in transcripts
            for turn in transcript.turns
            if turn.role == ANALYST
        )
    )


def _analysts_item(context: _Context) -> Reading:
    pair = _call_pair(context, "8.5")
    if isinstance(pair, Reading):
        return pair
    now, before, baseline = pair
    current, earlier = _analysts(now), _analysts(before)
    gone = [name for name in earlier if name not in current]
    new = [name for name in current if name not in earlier]
    values = (
        f"{_count(len(current), 'analyst')} against {len(earlier)}; gone: {', '.join(gone) or 'none'}; new: "
        f"{', '.join(new) or 'none'}"
    )
    if not earlier:
        return _reading("8.5", baseline, values, "not computable")
    move = _rounded((Fraction(len(current), len(earlier)) - 1) * 100, 2)
    return _reading("8.5", baseline, f"{values} ({move:+}%)", "grey" if -move > ANALYSTS_DROP else NONE)


def _answers(transcripts: Sequence[Transcript]) -> Decimal | None:
    """The mean words of the executives' turns after the first analyst's turn, or None."""
    turns = _turns(transcripts)
    first = next((index for index, (_, role, _) in enumerate(turns) if role == ANALYST), None)
    if first is None:
        return None
    answers = [words for _, role, words in turns[first:] if role == EXECUTIVE]
    return None if not answers else _rounded(Fraction(sum(answers), len(answers)), 1)


def _answers_item(context: _Context) -> Reading:
    pair = _call_pair(context, "8.6")
    if isinstance(pair, Reading):
        return pair
    now, before, baseline = pair
    current, earlier = _answers(now), _answers(before)
    values = f"mean words of an executive's answer {_number(current)} against {_number(earlier)}"
    if current is None or earlier is None or earlier <= 0:
        return _reading("8.6", baseline, values, "not computable")
    move = _rounded((Fraction(current) / Fraction(earlier) - 1) * 100, 2)
    return _reading("8.6", baseline, f"{values} ({move:+}%)", "grey" if -move > ANSWERS_DROP else NONE)


def _questions_words(transcripts: Sequence[Transcript]) -> int | None:
    turns = _turns(transcripts)
    first = next((index for index, (_, role, _) in enumerate(turns) if role == ANALYST), None)
    return None if first is None else sum(words for _, _, words in turns[first:])


def _duration(transcripts: Sequence[Transcript]) -> int | None:
    found = [transcript.duration_seconds for transcript in transcripts]
    return (
        None
        if not found or any(seconds is None for seconds in found)
        else sum(seconds or 0 for seconds in found)
    )


def _call_item(context: _Context) -> Reading:
    pair = _call_pair(context, "9.3")
    if isinstance(pair, Reading):
        return pair
    now, before, baseline = pair
    parts, drops = [], []
    for name, current, earlier in (
        ("duration (seconds)", _duration(now), _duration(before)),
        ("words from the first analyst's turn", _questions_words(now), _questions_words(before)),
    ):
        if current is None or earlier is None or earlier <= 0:
            parts.append(f"{name}: not computable")
            continue
        move = _rounded((Fraction(current, earlier) - 1) * 100, 2)
        drops.append(-move)
        parts.append(f"{name} {current:,} against {earlier:,} ({move:+}%)")
    if not drops:
        return _reading("9.3", baseline, "; ".join(parts), "not computable")
    return _reading(
        "9.3", baseline, "; ".join(parts), "yellow" if any(drop > CALL_DROP for drop in drops) else NONE
    )


def _lag(season: Season) -> int:
    return (season.filing.filed - season.period).days


def _late(season: Season) -> list[str]:
    """The season's earnings releases accepted after ``LATE`` on a day whose next XNYS session is
    not the next day, as ``accession (accepted time)``."""
    late = []
    for release in season.releases:
        accepted = release.accepted
        if accepted is None or accepted.timetz().replace(tzinfo=None) <= LATE:
            continue  # "after 16:00": 16:00:00 itself is not
        day = accepted.date()
        if next_session(day) != day + timedelta(days=1):
            late.append(f"{release.accession} ({et_display(accepted)})")
    return late


def _timing_item(context: _Context) -> Reading:
    season = context.season
    earlier = context.listing.before(season, 16)
    same = [other for other in earlier if other.filing.form == season.filing.form][:RECORD_SEASONS]
    record = list(earlier[:RECORD_SEASONS])
    baseline = (
        f"previous four {season.filing.form}s: {', '.join(str(other.period) for other in same) or 'none'}; "
        f"previous four seasons: {', '.join(str(other.period) for other in record) or 'none'}"
    )
    parts, triggers, compared = [], [], False
    lag = _lag(season)
    if same:
        compared = True
        most = max(_lag(other) for other in same)
        parts.append(f"filed {lag} days after the period end; the previous four at most {most}")
        triggers.append(lag > most)
    else:
        parts.append(f"filed {lag} days after the period end; no earlier {season.filing.form} is listed")
    late = _late(season)
    if record:
        compared = True
        before = [item for other in record for item in _late(other)]
        parts.append(
            f"releases accepted after 16:00 before a day without a session: {', '.join(late) or 'none'}; "
            f"in the previous four seasons: {', '.join(before) or 'none'}"
        )
        triggers.append(bool(late) and not before)
    notices = season.of_forms(NOTICES)
    parts.append(
        "late-filing notices: " + (", ".join(f"{item.form} {item.accession}" for item in notices) or "none")
    )
    triggers.append(bool(notices))
    if any(triggers):
        return _reading("9.1", baseline, "; ".join(parts), "red")
    return _reading("9.1", baseline, "; ".join(parts), NONE if compared else "no baseline")


def _lengths(context: _Context, files: SeasonFiles | None) -> dict[str, int | None]:
    """The derived text lengths of a season's 10-K or 10-Q, its releases' exhibits and its calls."""
    if files is None:
        return {"filing": None, "exhibits": None, "call": None}
    filing = None if files.filing is None else len(context.derived(files.filing))
    releases = [item for item in files.filings if item.item.release]
    exhibits = [document for item in releases for document in item.documents if document.kind == "exhibit"]
    calls = files.call.documents
    return {
        "filing": filing,
        "exhibits": sum(len(context.derived(document)) for document in exhibits) if exhibits else None,
        "call": sum(len(context.derived(document)) for document in calls) if calls else None,
    }


def _length_item(context: _Context) -> Reading:
    season, previous = context.season, context.previous()
    same = next(
        (other for other in context.listing.before(season, 8) if other.filing.form == season.filing.form),
        None,
    )
    baseline = f"previous {season.filing.form} {_season_name(same)}; previous season {_season_name(previous)}"
    now = _lengths(context, context.files)
    before = {
        "filing": _lengths(context, None if same is None else context.files_of(same))["filing"],
        **{
            name: value
            for name, value in _lengths(
                context, None if previous is None else context.files_of(previous)
            ).items()
            if name != "filing"
        },
    }
    parts, moves = [], []
    for name, label in (("filing", season.filing.form), ("exhibits", "release exhibits"), ("call", "call")):
        current, earlier = now[name], before[name]
        if current is None or earlier is None or earlier <= 0:
            parts.append(
                f"{label}: {'not in raw/' if current is None else f'{current:,} characters, no baseline'}"
            )
            continue
        move = _rounded((Fraction(current, earlier) - 1) * 100, 2)
        moves.append(abs(move))
        parts.append(f"{label} {current:,} characters against {earlier:,} ({move:+}%)")
    if not moves:  # no baseline when the season's own texts are there; else they are not computable
        level = "no baseline" if any(value is not None for value in now.values()) else "not computable"
        return _reading("9.4", baseline, "; ".join(parts), level)
    return _reading(
        "9.4", baseline, "; ".join(parts), "grey" if any(move > LENGTH_MOVE for move in moves) else NONE
    )


def _count_item(context: _Context) -> Reading:
    season = context.season
    record = context.listing.before(season, RECORD_SEASONS)
    baseline = f"previous four seasons: {', '.join(str(other.period) for other in record) or 'none'}"
    count = len(season.eight_ks)
    shown = _count(count, "8-K")
    if not record:
        return _reading("9.5", baseline, shown, "no baseline")
    counts = [len(other.eight_ks) for other in record]
    mean = _rounded(Fraction(sum(counts), len(counts)), 2)
    values = f"{shown} against a mean of {mean} ({', '.join(map(str, counts))})"
    return _reading("9.5", baseline, values, "grey" if count > EIGHT_K_MULTIPLE * mean else NONE)


def _cancelled_item(context: _Context) -> Reading:
    record = context.listing.before(context.season, RECORD_SEASONS)
    baseline = f"previous four seasons: {', '.join(str(other.period) for other in record) or 'none'}"
    status = context.files.call.status
    held = [bool(files.call.events) for other in record if (files := context.files_of(other)) is not None]
    values = f"the season's call: {status}; listed in the previous seasons: {sum(held)} of {len(record)}"
    if status != "unavailable":
        return _reading("9.6", baseline, values, NONE)
    if len(record) < RECORD_SEASONS:
        return _reading("9.6", baseline, values, "no baseline")
    return _reading("9.6", baseline, values, "red" if all(held) and len(held) == RECORD_SEASONS else NONE)


_COMPUTED: Final[Mapping[str, Callable[[_Context], Reading]]] = {
    "2.1": _growth_item,
    "2.2": _margins_item,
    "2.3": _cash_item,
    "2.4": _days_item,
    "2.5": _receivables_item,
    "2.6": _net_debt_item,
    "2.10": _shares_item,
    "2.11": _goodwill_item,
    "5.7": _sellers_item,
    "8.5": _analysts_item,
    "8.6": _answers_item,
    "9.1": _timing_item,
    "9.3": _call_item,
    "9.4": _length_item,
    "9.5": _count_item,
    "9.6": _cancelled_item,
}


# --------------------------------------------------------------------------- the season


@dataclass(frozen=True)
class Measures:
    """One season's mechanical comparison: its Python items in catalogue order, the figures of the
    seasons they compare and ``measures.md``'s text."""

    files: SeasonFiles
    readings: tuple[Reading, ...]
    figures: tuple[Figure, ...]
    text: str

    def level(self, identifier: str) -> str:
        return next(reading.level for reading in self.readings if reading.item.id == identifier)


def season_measures(raw: RawState, files: SeasonFiles, derived: Callable[[Document], str]) -> Measures:
    """Every Python item of ``files``' season and ``measures.md``'s text (module docstring)."""
    if raw.listing is None:
        raise ValueError(f"{raw.ticker}: no season is listed")
    context = _Context(raw, raw.listing, files, derived, {})
    readings = tuple(_COMPUTED[item.id](context) for item in PYTHON_ITEMS)
    seasons = [files.season]
    previous = context.previous()
    for other in (context.ago(files.season), previous, context.ago(previous)):
        if other is not None and other not in seasons:
            seasons.append(other)
    figures = tuple(
        found
        for season in seasons
        for measure in MEASURES
        if (found := context.figure(season, measure)) is not None
    )
    return Measures(files, readings, figures, render_measures(raw, files, readings, figures))


# --------------------------------------------------------------------------- measures.md


def _row(cells: Iterable[object]) -> str:
    return "| " + " | ".join(str(cell).replace("|", "\\|") for cell in cells) + " |"


def _season_line(raw: RawState, files: SeasonFiles) -> str:
    own = files.season.filing
    accepted = "not given" if own.accepted is None else et_display(own.accepted)
    return (
        f"Season: the {own.form} for the period ended {own.period}, accession {own.accession}, filed "
        f"{own.filed}, accepted {accepted}."
    )


def _call_line(files: SeasonFiles) -> str:
    call = files.call
    events = ", ".join(f"call {event.id} of {event.day}" for event in call.events)
    as_of = "" if call.as_of is None else f" as of the calls list of {call.as_of}"
    return f"Call: {call.status}{as_of}" + (f" ({events})." if events else ".")


def _baselines(raw: RawState, files: SeasonFiles) -> list[str]:
    listing = raw.listing
    if listing is None:
        return []
    kinds = list(dict.fromkeys(item.baseline for item in ITEMS if item.baseline != "none"))
    lines = [_row(["Baseline", "Seasons", "Documents in raw/ (DOC_ID)"]), _row(["---"] * 3)]
    for kind in kinds:
        seasons = baseline_seasons(listing, files.season, kind)
        documents = [
            document.doc_id
            for other in seasons
            if (held := raw.season(other.period)) is not None
            for document in held.documents
        ]
        lines.append(
            _row(
                [
                    kind,
                    ", ".join(f"{other.period} ({other.filing.form})" for other in seasons) or "none listed",
                    "; ".join(documents) or "none",
                ]
            )
        )
    return lines


def _filings(raw: RawState, files: SeasonFiles) -> list[str]:
    own = files.season.filing
    documents = {item.item.accession: item for item in files.filings}
    lines = [
        _row(["Form", "Dated", "Filed", "Accepted", "Accession", "Items", "Documents (DOC_ID)"]),
        _row(["---"] * 7),
    ]
    own_documents = files.filing.doc_id if files.filing is not None else "not in raw/"
    accepted = "—" if own.accepted is None else et_display(own.accepted)
    lines.append(_row([own.form, own.period, own.filed, accepted, own.accession, "", own_documents]))
    for item in files.season.filings:
        held = documents.get(item.accession)
        if not item.fetched:
            shown = "listed only"
        elif held is None or not held.documents:
            shown = "Form 4 XML (read by Python)" if item.form == "4" else "not in raw/"
        else:
            shown = "; ".join(document.doc_id for document in held.documents)
        when = "—" if item.accepted is None else et_display(item.accepted)
        lines.append(_row([item.form, item.dated, item.filed, when, item.accession, item.items, shown]))
    return lines


def _figures(figures: Sequence[Figure]) -> list[str]:
    lines = [
        _row(
            [
                "Measure",
                "Season",
                "Value",
                "Unit",
                "Concept",
                "Accession",
                "Start",
                "End",
                "Formula or reason",
            ]
        ),
        _row(["---"] * 9),
    ]
    for found in figures:
        lines.append(
            _row(
                [
                    found.measure,
                    found.season,
                    _number(found.value),
                    found.unit,
                    found.tag or "—",
                    found.accession or "—",
                    found.start or "—",
                    found.end or "—",
                    found.formula if found.value is not None else found.reason,
                ]
            )
        )
    return lines


def _inputs(raw: RawState, files: SeasonFiles, figures: Sequence[Figure]) -> list[str]:
    season = files.season
    own = {found.measure: found for found in figures if found.season == season.period}

    def shown(measure: str) -> str:
        found = own.get(measure)
        return "not computable" if found is None or found.value is None else f"{found.value:,} {found.unit}"

    by_accession = {item.item.accession: item for item in files.filings}

    def eight_ks(*items: str) -> str:
        found = [
            "; ".join(document.doc_id for document in by_accession[item.accession].documents)
            if item.accession in by_accession and by_accession[item.accession].documents
            else f"{item.accession} (not in raw/)"
            for item in season.eight_ks
            if any(number in item.item_list for number in items)
        ]
        return ", ".join(found) or "none"

    holders = [
        f"{held.documents[0].doc_id} ({item.form}, filer prefix {item.accession[:10]})"
        if (held := by_accession.get(item.accession)) is not None and held.documents
        else f"{item.form} {item.accession} (not in raw/)"
        for item in season.of_forms(HOLDER_FORMS)
    ]
    registrations = [
        f"{item.form} {item.accession} filed {item.filed}" for item in season.of_forms(REGISTRATIONS)
    ]
    amendments = [
        f"{item.form} {item.accession} filed {item.filed}"
        for item in season.filings
        if item.form.endswith("/A") and not item.fetched
    ]
    return [
        f"- 1.7: revenue {shown('revenue')}; net income {shown('net_income')}; diluted earnings per share "
        f"{shown('diluted_eps')}.",
        f"- 2.9, 4.4: net income {shown('net_income')}.",
        f"- 4.7: stockholders' equity {shown('equity')}.",
        f"- 6.4: stockholders' equity {shown('equity')}; total assets {shown('assets')}.",
        f"- 3.1: the 8-Ks with Item 4.01: {eight_ks('4.01')}.",
        f"- 3.4: the 8-Ks with Item 4.02: {eight_ks('4.02')}.",
        f"- 5.1, 5.2, 5.3: the 8-Ks with Item 5.02: {eight_ks('5.02')}.",
        f"- 5.4: the beneficial owners' schedules: {', '.join(holders) or 'none'}.",
        f"- 6.3: the 8-Ks with Items 3.02 or 1.01: {eight_ks('3.02', '1.01')}; the registrations listed: "
        f"{', '.join(registrations) or 'none'}.",
        f"- Amendments listed: {', '.join(amendments) or 'none'}.",
    ]


def render_measures(
    raw: RawState, files: SeasonFiles, readings: Sequence[Reading], figures: Sequence[Figure]
) -> str:
    """``measures.md`` of one season (module docstring)."""
    facts = "none" if raw.companyfacts is None else raw.companyfacts.name
    status, reason = raw.facts_status(files)
    lines = [
        f"# {raw.ticker} · {files.day} · measures",
        "",
        _season_line(raw, files),
        _call_line(files),
        f"Company facts: {facts} ({status}{'' if reason is None else ': ' + reason}).",
        "",
        "## Baselines",
        "",
        "Each baseline of the catalogue, the listed seasons it names and their documents in raw/: a "
        "reading's baseline line names some of these DOC_IDs.",
        "",
        *_baselines(raw, files),
        "",
        "## Filings of the season",
        "",
        *_filings(raw, files),
        "",
        "## Figures",
        "",
        *_figures(figures),
        "",
        "## Python items",
    ]
    for reading in readings:
        lines.extend(
            [
                "",
                f"### {reading.item.heading}",
                "",
                f"baseline: {reading.baseline}",
                f"values: {reading.values}",
                f"rule: {reading.item.rule}",
                f"level: {reading.level}",
            ]
        )
    lines.extend(["", "## Inputs for the bot's items", "", *_inputs(raw, files, figures)])
    return "\n".join(lines) + "\n"
