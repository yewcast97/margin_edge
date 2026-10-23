"""A season's mechanical comparison: the Python items and ``measures.md``.

``season_measures`` reads one season of a ticker's ``raw/`` (``documents.RawState``) and
computes every Python item of the catalogue (``items.PYTHON_ITEMS``) from structured data
alone: the figures of EDGAR's company facts (``facts``), the listing's filings, the Form 4s
and the call transcripts' turns and durations. An item is one or more rows, each stating one
value of a baseline season (old), the same value of the season (new) and the change between
them; no threshold judges, marks or leaves out a row. Each value is computed exactly and
rounded half-even once: percentages and ratios to two places, days and mean words to one; each
change is computed from the rounded values: percentage points between two percentages, the
difference between two ratios or two counts of days, and between two amounts the difference
and, over an old amount above 0, the percent change. A cell that cannot hold a value holds a
status: ``no baseline`` (the season it needs is not listed, or its call has no transcript),
``not computable`` (a figure is missing or ambiguous) or ``unavailable`` (the season's call
has no transcript); an old value of an item without a baseline is ``—``.

``render_measures`` writes the result as ``formatted/{T}/{PERIOD}/measures.md``, a pure
function of ``raw/`` and this code: the season and its baselines (``baseline_seasons``, the
seasons each baseline of the catalogue names, with their documents' ``DOC_ID``s), the filings
of the season, the figures, the Python items (each its ``rule:`` line, a table of its rows and,
where there is one, a ``note:``) and the inputs the bot's items name. ``derive`` writes it; it
is fresh while equal to what it renders now. Its fixed text passes ``readings.WORDING``: it
states figures and comparisons, never a valuation.
"""

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, time, timedelta
from decimal import Decimal
from fractions import Fraction
from typing import Final, Literal

from market_state_research.common.sessions import next_session
from market_state_research.common.times import et_display

from .documents import RawState, SeasonFiles
from .earningscalls import Transcript
from .facts import MEASURES, CompanyFacts, Figure, figure, quarter_days, year_ago
from .filings import HOLDER_FORMS, NOTICES, REGISTRATIONS, Season, Seasons
from .form4 import officers_selling
from .items import BY_ID, ITEMS, PYTHON_ITEMS, Baseline, Item

LATE: Final = time(16, 0)  # 9.1: New York time
RECORD_SEASONS: Final = 4  # 9.1, 9.4, 9.5
ANALYST: Final = "analyst"
EXECUTIVE: Final = "executive"
NONE: Final = "none"
NOTHING: Final = "—"  # the old value of an item without a baseline, and a change not stated
NO_BASELINE: Final = "no baseline"
NOT_COMPUTABLE: Final = "not computable"
UNAVAILABLE: Final = "unavailable"
NO_FACTS: Final = "no company facts are in raw/"
NOT_TRANSCRIBED: Final = "the call has no transcript in raw/ ({status})"
# How a row's change is stated: percentage points, a plain difference, or a difference with
# its percent change.
Kind = Literal["percent", "difference", "amount"]
Value = Decimal | int | str  # a str is a status or a text value


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
        return NOTHING
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
class Row:
    """One comparison of a Python item: what it compares, the season it compares with, the old
    value (the baseline's), the new value (the season's) and the change, each as written."""

    compared: str
    baseline: str
    old: str
    new: str
    change: str


@dataclass(frozen=True)
class Reading:
    """One Python item of a season: its rows and a note (the facts its rows rest on beyond their
    values, or why a cell holds a status; empty when there is none)."""

    item: Item
    rows: tuple[Row, ...]
    note: str = ""


def _cell(value: Value) -> str:
    return value if isinstance(value, str) else f"{value:,}"


def _difference(old: Value, new: Value, kind: Kind) -> str:
    """The change from ``old`` to ``new``, or ``—`` when either is not a number."""
    if isinstance(old, str) or isinstance(new, str):
        return NOTHING
    moved = new - old
    if kind == "percent":
        return f"{moved:+,} pp"
    if kind == "difference" or old <= 0:
        return f"{moved:+,}"
    return f"{moved:+,} ({_rounded(Fraction(new) / Fraction(old) * 100 - 100, 2):+}%)"


def _row(compared: str, baseline: str, old: Value, new: Value, kind: Kind) -> Row:
    return Row(compared, baseline, _cell(old), _cell(new), _difference(old, new, kind))


def _reading(identifier: str, rows: Iterable[Row], *notes: str) -> Reading:
    return Reading(BY_ID[identifier], tuple(rows), "; ".join(note for note in notes if note))


@dataclass
class _Context:
    """One season's inputs, the seasons it compares with and each figure read once."""

    raw: RawState
    listing: Seasons
    files: SeasonFiles
    cache: dict[tuple[date, str], Figure]

    @property
    def season(self) -> Season:
        return self.files.season

    @property
    def facts(self) -> CompanyFacts | None:
        return self.raw.facts

    @property
    def facts_note(self) -> str:
        return NO_FACTS if self.facts is None else ""

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
    return "none listed" if season is None else f"{season.period} ({season.filing.form})"


def _named(kind: str, season: Season | None) -> str:
    return f"{kind} {_season_name(season)}"


def _of(season: Season | None, compute: Callable[[Season], Decimal | None]) -> Value:
    """``compute`` of ``season``: ``no baseline`` when it is not listed, ``not computable`` when
    a figure is missing."""
    if season is None:
        return NO_BASELINE
    found = compute(season)
    return NOT_COMPUTABLE if found is None else found


def _growth(context: _Context, season: Season | None, measure: str) -> Value:
    """The growth of ``measure`` over the season a year before ``season``, in percent."""
    ago = context.ago(season)
    if season is None or ago is None:
        return NO_BASELINE
    now, before = context.value(season, measure), context.value(ago, measure)
    found = None if now is None or before is None else _change(now, before)
    return NOT_COMPUTABLE if found is None else found


def _growth_item(context: _Context) -> Reading:
    season, previous = context.season, context.previous()
    baseline = _named("previous quarter", previous)
    rows = [
        _row(
            f"{label} growth on the same quarter a year before (%)",
            baseline,
            _growth(context, previous, measure),
            _growth(context, season, measure),
            "percent",
        )
        for measure, label in (("revenue", "revenue"), ("net_income", "net income"))
    ]
    years = (
        f"the year before this season: {_season_name(context.ago(season))}; the year before the previous "
        f"quarter: {_season_name(context.ago(previous))}; not computable where a figure is missing or the "
        f"year-ago figure is 0 or below"
    )
    return _reading("2.1", rows, context.facts_note, years)


def _margin(context: _Context, measure: str) -> Callable[[Season], Decimal | None]:
    def margin(season: Season) -> Decimal | None:
        revenue, part = context.value(season, "revenue"), context.value(season, measure)
        if revenue is None or part is None or revenue <= 0:
            return None
        return _rounded(Fraction(part) / Fraction(revenue) * 100, 2)

    return margin


def _margins_item(context: _Context) -> Reading:
    season, previous = context.season, context.previous()
    ago = context.ago(season)
    rows = []
    for measure, label in (
        ("gross_profit", "gross margin (%)"),
        ("operating_income", "operating margin (%)"),
    ):
        margin = _margin(context, measure)
        for kind, other in (("same quarter last year", ago), ("previous quarter", previous)):
            rows.append(_row(label, _named(kind, other), _of(other, margin), _of(season, margin), "percent"))
    return _reading("2.2", rows, context.facts_note)


def _cash_ratio(context: _Context, season: Season) -> Decimal | None:
    cash, income = context.value(season, "operating_cash_flow"), context.value(season, "net_income")
    if cash is None or income is None or income <= 0:
        return None
    return _rounded(Fraction(cash) / Fraction(income), 2)


def _cash_item(context: _Context) -> Reading:
    season, previous = context.season, context.previous()
    ago = context.ago(season)

    def ratio(other: Season) -> Decimal | None:
        return _cash_ratio(context, other)

    rows = [
        _row(
            "operating cash flow ÷ net income",
            _named(kind, other),
            _of(other, ratio),
            _of(season, ratio),
            "difference",
        )
        for kind, other in (("same quarter last year", ago), ("previous quarter", previous))
    ]
    return _reading("2.3", rows, context.facts_note)


def _days(context: _Context, balance: str, flow: str) -> Callable[[Season], Decimal | None]:
    def days(season: Season) -> Decimal | None:
        held, moved, length = (
            context.value(season, balance),
            context.value(season, flow),
            quarter_days(context.listing, season),
        )
        if held is None or moved is None or length is None or moved <= 0:
            return None
        return _rounded(Fraction(held) * length / Fraction(moved), 1)

    return days


def _days_item(context: _Context) -> Reading:
    season, ago = context.season, context.ago(context.season)
    baseline = _named("same quarter last year", ago)
    rows = []
    for name, balance, flow in (
        ("days of sales outstanding", "receivables", "revenue"),
        ("days of inventory", "inventory", "cost_of_revenue"),
        ("days of payables", "payables", "cost_of_revenue"),
    ):
        days = _days(context, balance, flow)
        rows.append(_row(name, baseline, _of(ago, days), _of(season, days), "difference"))
    return _reading("2.4", rows, context.facts_note)


def _figure_of(context: _Context, measure: str) -> Callable[[Season], Decimal | None]:
    return lambda season: context.value(season, measure)


def _receivables_item(context: _Context) -> Reading:
    season, ago = context.season, context.ago(context.season)
    baseline = _named("same quarter last year", ago)
    rows = [
        _row(
            label,
            baseline,
            _of(ago, _figure_of(context, measure)),
            _of(season, _figure_of(context, measure)),
            "amount",
        )
        for measure, label in (
            ("receivables", "receivables at the period end (USD)"),
            ("revenue", "revenue of the quarter (USD)"),
        )
    ]
    return _reading("2.5", rows, context.facts_note)


def _net_debt(context: _Context, season: Season) -> Decimal | None:
    debt, cash = context.value(season, "debt"), context.value(season, "cash")
    return None if debt is None or cash is None else debt - cash


def _net_debt_item(context: _Context) -> Reading:
    season, previous = context.season, context.previous()

    def net_debt(other: Season) -> Decimal | None:
        return _net_debt(context, other)

    row = _row(
        "net debt (USD)",
        _named("previous quarter", previous),
        _of(previous, net_debt),
        _of(season, net_debt),
        "amount",
    )
    return _reading("2.6", [row], context.facts_note)


def _shares_item(context: _Context) -> Reading:
    season, previous = context.season, context.previous()

    def shares(other: Season) -> Decimal | None:  # a 10-K reports the year's average
        return None if other.filing.form == "10-K" else context.value(other, "diluted_shares")

    row = _row(
        "weighted average diluted shares",
        _named("previous quarter", previous),
        _of(previous, shares),
        _of(season, shares),
        "amount",
    )
    annual = (
        "a 10-K reports the year's average, so a 10-K season has no quarter's value"
        if season.filing.form == "10-K" or (previous is not None and previous.filing.form == "10-K")
        else ""
    )
    return _reading("2.10", [row], context.facts_note, annual)


def _goodwill_share(context: _Context, season: Season) -> Decimal | None:
    goodwill, equity = context.value(season, "goodwill"), context.value(season, "equity")
    if goodwill is None or equity is None or equity <= 0:
        return None
    return _rounded(Fraction(goodwill) / Fraction(equity) * 100, 2)


def _goodwill_item(context: _Context) -> Reading:
    season, previous = context.season, context.previous()
    baseline = _named("previous quarter", previous)
    goodwill = _figure_of(context, "goodwill")

    def share(other: Season) -> Decimal | None:
        return _goodwill_share(context, other)

    rows = [
        _row("goodwill (USD)", baseline, _of(previous, goodwill), _of(season, goodwill), "amount"),
        _row(
            "goodwill ÷ stockholders' equity (%)",
            baseline,
            _of(previous, share),
            _of(season, share),
            "percent",
        ),
    ]
    return _reading("2.11", rows, context.facts_note)


def _sellers_item(context: _Context) -> Reading:
    files, cik = context.files, context.raw.cik or ""
    forms = files.form4s()
    others = sum(1 for _, form in forms if form.issuer != cik)
    sellers = officers_selling(forms, cik)
    listed = "; ".join(
        f"{seller.name} ({seller.title or 'officer'}, {', '.join(seller.accessions)})" for seller in sellers
    )
    row = Row(
        "officers reporting a sale (S) or a disposition to the issuer (D)",
        NONE,
        NOTHING,
        f"{len(sellers)}{': ' + listed if listed else ''}",
        NOTHING,
    )
    return _reading("5.7", [row], f"{_count(len(forms), 'Form 4')} read, {others} of another issuer left out")


def _turns(transcripts: Sequence[Transcript]) -> list[tuple[str, str, int]]:
    """Each turn as (speaker, role, words), the season's calls in order."""
    return [
        (turn.speaker, turn.role, len(turn.text.split()))
        for transcript in transcripts
        for turn in transcript.turns
    ]


def _call_pair(
    context: _Context, identifier: str, compared: Sequence[str]
) -> tuple[Sequence[Transcript], Sequence[Transcript] | None, str] | Reading:
    """The season's and the previous season's transcripts (None when it has none), or the reading
    of a season whose call has no transcript: every cell ``unavailable``."""
    baseline = _named("previous quarter", context.previous())
    call = context.files.call
    if call.status != "transcript":
        rows = [Row(label, baseline, UNAVAILABLE, UNAVAILABLE, NOTHING) for label in compared]
        return _reading(identifier, rows, NOT_TRANSCRIBED.format(status=call.status))
    previous = context.previous()
    before = None if previous is None else context.files_of(previous)
    held = None if before is None or before.call.status != "transcript" else before.call.transcripts
    return call.transcripts, held, baseline


_PREVIOUS_CALL: Final = "the previous season's call has no transcript in raw/"


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
    compared = ("distinct analysts asking questions", "analysts on one of the two calls only")
    pair = _call_pair(context, "8.5", compared)
    if isinstance(pair, Reading):
        return pair
    now, before, baseline = pair
    current = _analysts(now)
    if before is None:
        rows = [
            _row(compared[0], baseline, NO_BASELINE, len(current), "amount"),
            Row(compared[1], baseline, NO_BASELINE, NO_BASELINE, NOTHING),
        ]
        return _reading("8.5", rows, _PREVIOUS_CALL)
    earlier = _analysts(before)
    gone = ", ".join(name for name in earlier if name not in current) or NONE
    new = ", ".join(name for name in current if name not in earlier) or NONE
    rows = [
        _row(compared[0], baseline, len(earlier), len(current), "amount"),
        Row(compared[1], baseline, gone, new, NOTHING),
    ]
    return _reading("8.5", rows)


def _answers(transcripts: Sequence[Transcript]) -> Decimal | None:
    """The mean words of the executives' turns after the first analyst's turn, or None."""
    turns = _turns(transcripts)
    first = next((index for index, (_, role, _) in enumerate(turns) if role == ANALYST), None)
    if first is None:
        return None
    answers = [words for _, role, words in turns[first:] if role == EXECUTIVE]
    return None if not answers else _rounded(Fraction(sum(answers), len(answers)), 1)


def _measured(found: Decimal | int | None) -> Value:
    return NOT_COMPUTABLE if found is None else found


def _answers_item(context: _Context) -> Reading:
    compared = ("mean words of an executive's turn after the first analyst's",)
    pair = _call_pair(context, "8.6", compared)
    if isinstance(pair, Reading):
        return pair
    now, before, baseline = pair
    old = NO_BASELINE if before is None else _measured(_answers(before))
    row = _row(compared[0], baseline, old, _measured(_answers(now)), "amount")
    return _reading("8.6", [row], _PREVIOUS_CALL if before is None else "")


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
    measured = (
        ("call duration (seconds)", _duration),
        ("words from the first analyst's turn to the end", _questions_words),
    )
    pair = _call_pair(context, "9.3", [label for label, _ in measured])
    if isinstance(pair, Reading):
        return pair
    now, before, baseline = pair
    rows = [
        _row(
            label,
            baseline,
            NO_BASELINE if before is None else _measured(compute(before)),
            _measured(compute(now)),
            "amount",
        )
        for label, compute in measured
    ]
    return _reading("9.3", rows, _PREVIOUS_CALL if before is None else "")


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


def _listed(found: Sequence[str]) -> str:
    return ", ".join(found) or NONE


def _record(record: Sequence[Season]) -> str:
    return "previous four seasons: " + (", ".join(str(other.period) for other in record) or "none listed")


def _timing_item(context: _Context) -> Reading:
    season = context.season
    form = season.filing.form
    earlier = context.listing.before(season, 16)
    same = [other for other in earlier if other.filing.form == form][:RECORD_SEASONS]
    record = list(earlier[:RECORD_SEASONS])
    lags = ", ".join(str(_lag(other)) for other in same) or NO_BASELINE
    before = [item for other in record for item in _late(other)]
    notices = [f"{item.form} {item.accession}" for other in record for item in other.of_forms(NOTICES)]
    rows = [
        Row(
            f"days from the period end to the {form}'s filing",
            f"previous four {form}s: " + (", ".join(str(other.period) for other in same) or "none listed"),
            lags,
            str(_lag(season)),
            NOTHING,
        ),
        Row(
            "earnings releases accepted after 16:00 on a day whose next XNYS session is not the next day",
            _record(record),
            _listed(before) if record else NO_BASELINE,
            _listed(_late(season)),
            NOTHING,
        ),
        Row(
            "late-filing notices (NT 10-K, NT 10-Q)",
            _record(record),
            _listed(notices) if record else NO_BASELINE,
            _listed([f"{item.form} {item.accession}" for item in season.of_forms(NOTICES)]),
            NOTHING,
        ),
    ]
    return _reading("9.1", rows, "the old values are newest first")


def _count_item(context: _Context) -> Reading:
    season = context.season
    record = context.listing.before(season, RECORD_SEASONS)
    counts = ", ".join(str(len(other.eight_ks)) for other in record) or NO_BASELINE
    row = Row("8-Ks placed in the season", _record(record), counts, str(len(season.eight_ks)), NOTHING)
    return _reading("9.4", [row], "the old values are newest first")


def _cancelled_item(context: _Context) -> Reading:
    record = context.listing.before(context.season, RECORD_SEASONS)
    states = [
        "not in raw/" if (files := context.files_of(other)) is None else files.call.status for other in record
    ]
    row = Row(
        "the season's call",
        _record(record),
        ", ".join(states) or NO_BASELINE,
        context.files.call.status,
        NOTHING,
    )
    return _reading("9.5", [row], "the old values are newest first")


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
    "9.4": _count_item,
    "9.5": _cancelled_item,
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

    def reading(self, identifier: str) -> Reading:
        return next(reading for reading in self.readings if reading.item.id == identifier)


def season_measures(raw: RawState, files: SeasonFiles) -> Measures:
    """Every Python item of ``files``' season and ``measures.md``'s text (module docstring)."""
    if raw.listing is None:
        raise ValueError(f"{raw.ticker}: no season is listed")
    context = _Context(raw, raw.listing, files, {})
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


def _table_row(cells: Iterable[object]) -> str:
    return "| " + " | ".join(str(cell).replace("|", "\\|") for cell in cells) + " |"


def _rows_table(rows: Sequence[Row]) -> list[str]:
    """A Python item's rows as a table: what each compares, its baseline, old, new and change."""
    lines = [_table_row(["Compared", "Baseline", "Old", "New", "Change"]), _table_row(["---"] * 5)]
    lines.extend(_table_row([row.compared, row.baseline, row.old, row.new, row.change]) for row in rows)
    return lines


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
    lines = [_table_row(["Baseline", "Seasons", "Documents in raw/ (DOC_ID)"]), _table_row(["---"] * 3)]
    for kind in kinds:
        seasons = baseline_seasons(listing, files.season, kind)
        documents = [
            document.doc_id
            for other in seasons
            if (held := raw.season(other.period)) is not None
            for document in held.documents
        ]
        lines.append(
            _table_row(
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
        _table_row(["Form", "Dated", "Filed", "Accepted", "Accession", "Items", "Documents (DOC_ID)"]),
        _table_row(["---"] * 7),
    ]
    own_documents = files.filing.doc_id if files.filing is not None else "not in raw/"
    accepted = "—" if own.accepted is None else et_display(own.accepted)
    lines.append(_table_row([own.form, own.period, own.filed, accepted, own.accession, "", own_documents]))
    for item in files.season.filings:
        held = documents.get(item.accession)
        if not item.fetched:
            shown = "listed only"
        elif held is None or not held.documents:
            shown = "Form 4 XML (read by Python)" if item.form == "4" else "not in raw/"
        else:
            shown = "; ".join(document.doc_id for document in held.documents)
        when = "—" if item.accepted is None else et_display(item.accepted)
        lines.append(_table_row([item.form, item.dated, item.filed, when, item.accession, item.items, shown]))
    return lines


def _figures(figures: Sequence[Figure]) -> list[str]:
    lines = [
        _table_row(
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
        _table_row(["---"] * 9),
    ]
    for found in figures:
        lines.append(
            _table_row(
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
        lines.extend(["", f"### {reading.item.heading}", "", f"rule: {reading.item.rule}", ""])
        lines.extend(_rows_table(reading.rows))
        if reading.note:
            lines.extend(["", f"note: {reading.note}"])
    lines.extend(["", "## Inputs for the bot's items", "", *_inputs(raw, files, figures)])
    return "\n".join(lines) + "\n"
