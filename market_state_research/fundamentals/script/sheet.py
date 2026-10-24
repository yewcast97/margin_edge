"""A season's sheet, ``formatted/{T}/{PERIOD}/season.md``: what the bot reads a season from.

``season_sheet`` renders one season of a ticker's ``raw/`` (``documents.RawState``), a pure
function of ``raw/`` and this code, with no time of its own: ``derive`` writes it, and it is
fresh while equal to what it renders now. Under the title ``# {T} · {PERIOD} · season`` it
states the season's 10-K or 10-Q and its call; then ``## Comparisons``, each comparison of the
season (``aspects.comparisons``) with its baseline season and that season's documents in
``raw/``, the ``DOC_ID``s a reading's ``baseline:`` lines name; ``## Filings of the season``,
every filing Rule B places in it, with its form, dates, acceptance time, accession, items and
documents (a listed-only form marked so); and ``## Inputs for the bot``, the season's documents
by what they are: its 10-K or 10-Q, its earnings releases (8-Ks with Item 2.02), its 8-Ks with
Items 1.01 or 2.03 (an agreement or a direct financial obligation), its other 8-Ks, its call and
the filings listed but not fetched. Python reads no document's words and computes no figure:
the sheet lists. Its fixed text passes ``readings.WORDING``.
"""

from collections.abc import Iterable, Sequence

from market_state_research.common.times import et_display

from .aspects import Comparison, comparisons
from .documents import CallState, RawState, SeasonFiles
from .filings import AMENDMENTS, ITEM_RESULTS, ITEMS_FINANCING, NOTICES, REGISTRATIONS, Dated, Season

NONE = "none"
NOT_IN_RAW = "not in raw/"
NONE_LISTED = "none listed"
SHEET = "season.md"


def season_name(season: Season) -> str:
    """``2026-03-28 (10-Q)``: a season's period end and its form."""
    return f"{season.period} ({season.filing.form})"


def baseline_documents(raw: RawState, found: Comparison) -> tuple[str, ...]:
    """The ``DOC_ID``s of the comparison's baseline season's documents in ``raw/``: none when no
    baseline season is listed."""
    held = None if found.baseline is None else raw.season(found.baseline.period)
    return () if held is None else tuple(document.doc_id for document in held.documents)


def call_line(call: CallState) -> str:
    """The season's call: its state, the calls of a transcript, or the date of the calls list a
    verdict of ``unavailable`` or ``waiting`` rests on."""
    events = ", ".join(f"call {event.id} of {event.day}" for event in call.events)
    as_of = (
        "" if call.status == "transcript" or call.as_of is None else f" as of the calls list of {call.as_of}"
    )
    return f"Call: {call.status}{as_of}" + (f" ({events})." if events else ".")


def _table_row(cells: Iterable[object]) -> str:
    return "| " + " | ".join(str(cell).replace("|", "\\|") for cell in cells) + " |"


def _season_line(files: SeasonFiles) -> str:
    own = files.season.filing
    accepted = "not given" if own.accepted is None else et_display(own.accepted)
    return (
        f"Season: the {own.form} for the period ended {own.period}, accession {own.accession}, filed "
        f"{own.filed}, accepted {accepted}."
    )


def _comparisons(raw: RawState, files: SeasonFiles) -> list[str]:
    listing = raw.listing
    lines = [
        _table_row(["Comparison", "Baseline season", "Its documents in raw/ (DOC_ID)"]),
        _table_row(["---"] * 3),
    ]
    for found in () if listing is None else comparisons(listing, files.season):
        documents = baseline_documents(raw, found)
        lines.append(
            _table_row(
                [
                    found.kind,
                    NONE_LISTED if found.baseline is None else season_name(found.baseline),
                    "; ".join(documents) or NONE,
                ]
            )
        )
    return lines


def _filings(files: SeasonFiles) -> list[str]:
    own = files.season.filing
    by_accession = {held.item.accession: held for held in files.filings}
    lines = [
        _table_row(["Form", "Dated", "Filed", "Accepted", "Accession", "Items", "Documents (DOC_ID)"]),
        _table_row(["---"] * 7),
    ]
    accepted = "—" if own.accepted is None else et_display(own.accepted)
    own_documents = NOT_IN_RAW if files.filing is None else files.filing.doc_id
    lines.append(_table_row([own.form, own.period, own.filed, accepted, own.accession, "", own_documents]))
    for item in files.season.filings:
        held = by_accession.get(item.accession)
        if not item.fetched:
            shown = "listed only"
        elif held is None or not held.documents:
            shown = NOT_IN_RAW
        else:
            shown = "; ".join(document.doc_id for document in held.documents)
        when = "—" if item.accepted is None else et_display(item.accepted)
        lines.append(_table_row([item.form, item.dated, item.filed, when, item.accession, item.items, shown]))
    return lines


def _listed(items: Sequence[Dated]) -> str:
    return ", ".join(f"{item.form} {item.accession} filed {item.filed}" for item in items) or NONE


def _inputs(files: SeasonFiles) -> list[str]:
    season = files.season
    by_accession = {held.item.accession: held for held in files.filings}

    def eight_ks(chosen: Iterable[Dated]) -> str:
        found = [
            "; ".join(document.doc_id for document in held.documents)
            if (held := by_accession.get(item.accession)) is not None and held.documents
            else f"{item.accession} ({NOT_IN_RAW})"
            for item in chosen
        ]
        return ", ".join(found) or NONE

    def naming(*items: str) -> list[Dated]:
        return [item for item in season.eight_ks if any(number in item.item_list for number in items)]

    named = {*ITEMS_FINANCING, ITEM_RESULTS}
    others = [item for item in season.eight_ks if not named & set(item.item_list)]
    own = season.filing
    calls = "; ".join(document.doc_id for document in files.call.documents) or f"{NONE} ({files.call.status})"
    return [
        f"- The {own.form}: {NOT_IN_RAW if files.filing is None else files.filing.doc_id}.",
        f"- Earnings releases, the 8-Ks with Item {ITEM_RESULTS}: {eight_ks(naming(ITEM_RESULTS))}.",
        f"- Agreements and direct financial obligations, the 8-Ks with Items {' or '.join(ITEMS_FINANCING)}: "
        f"{eight_ks(naming(*ITEMS_FINANCING))}.",
        f"- Other 8-Ks: {eight_ks(others)}.",
        f"- The call: {calls}.",
        f"- Registrations and prospectuses, listed, not fetched: {_listed(season.of_forms(REGISTRATIONS))}.",
        f"- Amendments, listed, not fetched: {_listed(season.of_forms(AMENDMENTS))}.",
        f"- Late-filing notices, listed, not fetched: {_listed(season.of_forms(NOTICES))}.",
    ]


def season_sheet(raw: RawState, files: SeasonFiles) -> str:
    """``season.md`` of one season (module docstring)."""
    lines = [
        f"# {raw.ticker} · {files.day} · season",
        "",
        _season_line(files),
        call_line(files.call),
        "",
        "## Comparisons",
        "",
        "Each comparison of the season, its baseline season and that season's documents in raw/: a "
        "reading's baseline lines name some of these DOC_IDs.",
        "",
        *_comparisons(raw, files),
        "",
        "## Filings of the season",
        "",
        *_filings(files),
        "",
        "## Inputs for the bot",
        "",
        *_inputs(files),
    ]
    return "\n".join(lines) + "\n"
