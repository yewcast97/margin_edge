"""script/facts.py: the strict reading of EDGAR's company facts and a season's figures from them.

Bodies are built here in EDGAR's layout: each concept's ``units`` maps a unit to its entries,
each ``{start?, end, val, accn, fy, fp, form, filed, frame?}`` (``fact``). The seasons are
INTC's fiscal calendar from the year ended 2024-12-28 to the quarter ended 2026-06-27, each
quarter 91 days long; values are in millions, for reading. Every rejected body raises one
``ValueError`` line that names the field and never echoes a value read from the body
(``PRIVATE`` stands in for one). Nothing here writes a file or uses the network.
"""

import json
import traceback
from collections.abc import Mapping
from datetime import date, timedelta
from decimal import Decimal

import pytest

from market_state_research.fundamentals.script.facts import (
    CompanyFacts,
    Entry,
    Figure,
    figure,
    quarter_days,
    read_companyfacts,
    season_figures,
    year_ago,
)
from market_state_research.fundamentals.script.filings import Filing, Season, Seasons

CIK = "0000050863"
PRIVATE = "private-value"  # stands in for a body value that must never be echoed
REFUSED = f"companyfacts CIK{CIK}: "

K24 = Filing("10-K", "0000050863-25-000009", date(2025, 1, 31), date(2024, 12, 28), "intc-20241228.htm")
Q1_25 = Filing("10-Q", "0000050863-25-000080", date(2025, 4, 25), date(2025, 3, 29), "intc-20250329.htm")
Q2_25 = Filing("10-Q", "0000050863-25-000140", date(2025, 7, 25), date(2025, 6, 28), "intc-20250628.htm")
Q3_25 = Filing("10-Q", "0000050863-25-000201", date(2025, 10, 31), date(2025, 9, 27), "intc-20250927.htm")
K25 = Filing("10-K", "0000050863-26-000012", date(2026, 1, 30), date(2025, 12, 27), "intc-20251227.htm")
Q1_26 = Filing("10-Q", "0000050863-26-000041", date(2026, 4, 24), date(2026, 3, 28), "intc-20260328.htm")
Q2_26 = Filing("10-Q", "0000050863-26-000064", date(2026, 7, 24), date(2026, 6, 27), "intc-20260627.htm")
FILINGS = (K24, Q1_25, Q2_25, Q3_25, K25, Q1_26, Q2_26)
END = date(2026, 6, 27)  # the season of Q2_26
QUARTER = date(2026, 3, 29)  # its quarter's first day
YEAR = date(2025, 12, 28)  # its fiscal year's first day
REVENUE = "RevenueFromContractWithCustomerExcludingAssessedTax"
CASH_FLOW = "NetCashProvidedByUsedInOperatingActivities"
SHARES = "WeightedAverageNumberOfDilutedSharesOutstanding"


def listing(*filings: Filing) -> Seasons:
    """The seasons of ``filings`` (``FILINGS`` by default), oldest first, holding no other filing."""
    chosen = filings or FILINGS
    return Seasons(tuple(Season(filing, ()) for filing in chosen), (), (), chosen[0].filed)


SEASONS = listing()


def season(filing: Filing, seasons: Seasons = SEASONS) -> Season:
    found = seasons.get(filing.period)
    assert found is not None
    return found


def fact(
    filing: Filing, end: date, value: object, start: date | None = None, **extra: object
) -> dict[str, object]:
    """One entry as EDGAR lists it, reported in ``filing``: a flow from ``start`` to ``end``, or a
    balance at ``end`` without ``start``; ``extra`` adds keys."""
    entry: dict[str, object] = {
        "end": end.isoformat(),
        "val": value,
        "accn": filing.accession,
        "fy": 2026,
        "fp": "Q2",
        "form": filing.form,
        "filed": filing.filed.isoformat(),
    }
    if start is not None:
        entry = {"start": start.isoformat(), **entry}
    return {**entry, **extra}


def concept(*entries: object, unit: str = "USD") -> dict[str, object]:
    return {"label": "A concept", "description": "What it measures.", "units": {unit: list(entries)}}


def document(us_gaap: Mapping[str, object] | None = None, **top: object) -> dict[str, object]:
    """INTC's company facts holding the ``us-gaap`` concepts given; ``top`` replaces top-level keys."""
    value: dict[str, object] = {
        "cik": 50863,
        "entityName": "INTEL CORP",
        "facts": {
            "dei": {
                "EntityCommonStockSharesOutstanding": {
                    "units": {"shares": [fact(Q2_26, date(2026, 7, 17), 4_400)]}
                }
            },
            "us-gaap": dict(us_gaap or {}),
        },
    }
    return {**value, **top}


def without(value: Mapping[str, object], key: str) -> dict[str, object]:
    return {name: item for name, item in value.items() if name != key}


def body(value: object) -> bytes:
    return json.dumps(value).encode()


def goodwill_body(entry: str) -> bytes:
    """A body whose one read entry is the JSON text ``entry``, Goodwill's in USD."""
    return (
        '{"cik": 50863, "entityName": "INTEL CORP", "facts": {"us-gaap": {"Goodwill": {"units": {"USD": ['
        + entry
        + "]}}}}}"
    ).encode()


def read(us_gaap: Mapping[str, object] | None = None) -> CompanyFacts:
    return read_companyfacts(body(document(us_gaap)), CIK)


def full_traceback(error: BaseException) -> str:
    return "".join(traceback.format_exception(error))


def failure(data: bytes) -> str:
    """The one-line message ``read_companyfacts`` refuses ``data`` with; it never echoes ``PRIVATE``."""
    with pytest.raises(ValueError) as caught:
        read_companyfacts(data, CIK)
    message = str(caught.value)
    assert "\n" not in message
    assert PRIVATE not in full_traceback(caught.value)
    return message


ACCN = f'"accn": "{Q2_26.accession}"'


# --------------------------------------------------------------------------- reading the body


def test_a_body_is_read_as_the_entries_of_the_catalogues_concepts_in_their_units():
    facts = read(
        {
            "Revenues": {
                "label": "Revenues",
                "units": {
                    "USD": [
                        fact(Q2_26, END, 16_100, QUARTER, frame="CY2026Q2"),
                        fact(Q2_26, END, 29_700, YEAR),
                    ],
                    "EUR": [PRIVATE],  # a unit revenue is not read in
                },
            },
            "EarningsPerShareDiluted": concept(fact(Q2_26, END, 0.2, QUARTER), unit="USD/shares"),
            SHARES: concept(fact(Q2_26, END, 5_100, QUARTER), unit="shares"),
            "IncomeTaxExpenseBenefit": concept(PRIVATE),  # a concept no measure reads
        }
    )

    assert facts == CompanyFacts(
        CIK,
        "INTEL CORP",
        {
            ("Revenues", "USD"): (
                Entry(QUARTER, END, Decimal(16_100), Q2_26.accession),
                Entry(YEAR, END, Decimal(29_700), Q2_26.accession),
            ),
            ("EarningsPerShareDiluted", "USD/shares"): (
                Entry(QUARTER, END, Decimal("0.2"), Q2_26.accession),
            ),
            (SHARES, "shares"): (Entry(QUARTER, END, Decimal(5_100), Q2_26.accession),),
        },
    )


def test_everything_outside_the_catalogues_concepts_is_ignored():
    goodwill = concept(fact(Q2_26, END, 20_400, frame="CY2026Q2I", note=PRIVATE))
    value = document(
        facts={"dei": [PRIVATE], "invest": PRIVATE, "us-gaap": {"Goodwill": goodwill, "Other": PRIVATE}},
        listedAt=PRIVATE,
    )

    facts = read_companyfacts(body(value), CIK)

    assert facts.entries == {("Goodwill", "USD"): (Entry(None, END, Decimal(20_400), Q2_26.accession),)}


@pytest.mark.parametrize(
    "value",
    [
        pytest.param(document(facts={}), id="no-us-gaap"),
        pytest.param(without(document(), "facts"), id="no-facts"),
    ],
)
def test_a_company_without_us_gaap_facts_has_no_entries(value):
    assert read_companyfacts(body(value), CIK) == CompanyFacts(CIK, "INTEL CORP", {})


@pytest.mark.parametrize(
    ("written", "value"),
    [
        pytest.param("16100", Decimal(16_100), id="integer"),
        pytest.param("0.1", Decimal("0.1"), id="decimal"),
        pytest.param("-2.25", Decimal("-2.25"), id="negative"),
        pytest.param("1e3", Decimal(1_000), id="exponent"),
        pytest.param("123456789012345678901234567890", Decimal("123456789012345678901234567890"), id="long"),
    ],
)
def test_values_are_read_as_exact_decimals(written, value):
    facts = read_companyfacts(goodwill_body(f'{{"end": "2026-06-27", "val": {written}, {ACCN}}}'), CIK)

    (entry,) = facts.entries[("Goodwill", "USD")]
    assert entry.value == value
    assert isinstance(entry.value, Decimal)


def test_of_and_accessions_name_the_filings_the_entries_come_from():
    facts = read(
        {
            "Goodwill": concept(fact(Q1_26, date(2026, 3, 28), 20_400), fact(Q2_26, END, 20_400)),
            "Assets": concept(fact(Q2_26, END, 202_000)),
        }
    )

    assert facts.of("Goodwill", "USD", Q1_26.accession) == (
        Entry(None, date(2026, 3, 28), Decimal(20_400), Q1_26.accession),
    )
    assert facts.of("Goodwill", "shares", Q2_26.accession) == ()
    assert facts.of("Assets", "USD", Q1_26.accession) == ()
    assert facts.accessions == {Q1_26.accession, Q2_26.accession}


def test_an_entrys_days_count_both_its_first_and_last_day():
    assert Entry(QUARTER, END, Decimal(1), Q2_26.accession).days == 91
    assert Entry(YEAR, END, Decimal(1), Q2_26.accession).days == 182
    assert Entry(None, END, Decimal(1), Q2_26.accession).days is None


@pytest.mark.parametrize(
    ("data", "message"),
    [
        pytest.param(b"", "invalid JSON: Expecting value (line 1, column 1)", id="empty"),
        pytest.param(b"\xff" + PRIVATE.encode(), "the body is not UTF-8", id="not-utf-8"),
        pytest.param(b"[" * 100_000 + b"]" * 100_000, "invalid JSON: nested too deeply", id="nested"),
        pytest.param(body([PRIVATE]), "expected a JSON object", id="list"),
        pytest.param(
            b'{"cik": 50863, "cik": 50863, "entityName": "INTEL CORP"}',
            "invalid JSON: an object repeats a key",
            id="repeated-key",
        ),
        pytest.param(
            b'{"cik": 50863, "entityName": "INTEL CORP", '
            b'"facts": {"us-gaap": {"Other": {"units": {}, "units": {}}}}}',
            "invalid JSON: an object repeats a key",
            id="repeated-key-in-a-concept-not-read",
        ),
        pytest.param(
            goodwill_body(f'{{"end": "2026-06-27", "val": NaN, {ACCN}}}'),
            "invalid JSON: NaN is not JSON",
            id="nan",
        ),
        pytest.param(
            goodwill_body(f'{{"end": "2026-06-27", "val": Infinity, {ACCN}}}'),
            "invalid JSON: Infinity is not JSON",
            id="infinity",
        ),
        pytest.param(
            goodwill_body(f'{{"end": "2026-06-27", "val": -Infinity, {ACCN}}}'),
            "invalid JSON: -Infinity is not JSON",
            id="negative-infinity",
        ),
        pytest.param(body(document(cik=50864)), "cik is not the requested CIK", id="other-cik"),
        pytest.param(
            body(document(cik=CIK)), "cik must be a whole number of at most ten digits", id="cik-as-text"
        ),
        pytest.param(
            body(without(document(), "cik")), "cik must be a whole number of at most ten digits", id="no-cik"
        ),
        pytest.param(
            body(without(document(), "entityName")),
            "entityName must be a non-empty printable string",
            id="no-name",
        ),
        pytest.param(
            body(document(entityName="")), "entityName must be a non-empty printable string", id="empty-name"
        ),
        pytest.param(
            body(document(entityName=" \t ")),
            "entityName must be a non-empty printable string",
            id="blank-name",
        ),
        pytest.param(
            body(document(entityName=f"INTEL\n{PRIVATE}")),
            "entityName must be a non-empty printable string",
            id="name-with-a-line-break",
        ),
        pytest.param(
            body(document(entityName=50863)),
            "entityName must be a non-empty printable string",
            id="name-number",
        ),
        pytest.param(body(document(facts=[PRIVATE])), "facts must be an object", id="facts-list"),
        pytest.param(
            body(document(facts={"us-gaap": [PRIVATE]})), "facts.us-gaap must be an object", id="us-gaap-list"
        ),
        pytest.param(
            body(document({"Revenues": PRIVATE})),
            "facts.us-gaap.Revenues.units must be an object",
            id="concept-text",
        ),
        pytest.param(
            body(document({"Revenues": {"label": "Revenues"}})),
            "facts.us-gaap.Revenues.units must be an object",
            id="no-units",
        ),
        pytest.param(
            body(document({"Revenues": {"units": [PRIVATE]}})),
            "facts.us-gaap.Revenues.units must be an object",
            id="units-list",
        ),
        pytest.param(
            body(document({"Revenues": {"units": {"USD": PRIVATE}}})),
            "facts.us-gaap.Revenues.units.USD must be a list",
            id="unit-not-a-list",
        ),
        pytest.param(
            body(document({"Revenues": concept(PRIVATE)})),
            "facts.us-gaap.Revenues.units.USD[0] must be an object",
            id="entry-text",
        ),
        pytest.param(
            body(document({"Revenues": concept(fact(Q2_26, END, 1, QUARTER), [PRIVATE])})),
            "facts.us-gaap.Revenues.units.USD[1] must be an object",
            id="second-entry-list",
        ),
        pytest.param(
            goodwill_body(f'{{"val": 1, {ACCN}}}'),
            "facts.us-gaap.Goodwill.units.USD[0].end is missing",
            id="no-end",
        ),
        pytest.param(
            goodwill_body(f'{{"end": "2026-06-27", {ACCN}}}'),
            "facts.us-gaap.Goodwill.units.USD[0].val is missing",
            id="no-val",
        ),
        pytest.param(
            goodwill_body('{"end": "2026-06-27", "val": 1}'),
            "facts.us-gaap.Goodwill.units.USD[0].accn is missing",
            id="no-accn",
        ),
        pytest.param(
            body(document({"Revenues": concept({**fact(Q2_26, END, 1), "start": f"2026-03-29{PRIVATE}"})})),
            "facts.us-gaap.Revenues.units.USD[0].start must be a YYYY-MM-DD date",
            id="start-text",
        ),
        pytest.param(
            body(document({"Revenues": concept({**fact(Q2_26, END, 1), "start": 20260329})})),
            "facts.us-gaap.Revenues.units.USD[0].start must be a YYYY-MM-DD date",
            id="start-number",
        ),
        pytest.param(
            body(document({"Revenues": concept(fact(Q2_26, END, 1, date(2026, 6, 28)))})),
            "facts.us-gaap.Revenues.units.USD[0]: start is after end",
            id="start-after-end",
        ),
        pytest.param(
            goodwill_body(f'{{"end": "2026-6-27", "val": 1, {ACCN}}}'),
            "facts.us-gaap.Goodwill.units.USD[0].end must be a YYYY-MM-DD date",
            id="end-without-padding",
        ),
        pytest.param(
            goodwill_body(f'{{"end": "20260627", "val": 1, {ACCN}}}'),
            "facts.us-gaap.Goodwill.units.USD[0].end must be a YYYY-MM-DD date",
            id="end-basic-format",
        ),
        pytest.param(
            goodwill_body(f'{{"end": "2026-02-30", "val": 1, {ACCN}}}'),
            "facts.us-gaap.Goodwill.units.USD[0].end must be a YYYY-MM-DD date",
            id="end-not-a-day",
        ),
        pytest.param(
            goodwill_body(f'{{"end": "06/27/2026", "val": 1, {ACCN}}}'),
            "facts.us-gaap.Goodwill.units.USD[0].end must be a YYYY-MM-DD date",
            id="end-us-format",
        ),
        pytest.param(
            goodwill_body(f'{{"end": "2026-06-27", "val": "{PRIVATE}", {ACCN}}}'),
            "facts.us-gaap.Goodwill.units.USD[0].val must be a number",
            id="val-text",
        ),
        pytest.param(
            goodwill_body(f'{{"end": "2026-06-27", "val": "16100", {ACCN}}}'),
            "facts.us-gaap.Goodwill.units.USD[0].val must be a number",
            id="val-digits-as-text",
        ),
        pytest.param(
            goodwill_body(f'{{"end": "2026-06-27", "val": true, {ACCN}}}'),
            "facts.us-gaap.Goodwill.units.USD[0].val must be a number",
            id="val-boolean",
        ),
        pytest.param(
            goodwill_body(f'{{"end": "2026-06-27", "val": null, {ACCN}}}'),
            "facts.us-gaap.Goodwill.units.USD[0].val must be a number",
            id="val-null",
        ),
        pytest.param(
            goodwill_body('{"end": "2026-06-27", "val": 1, "accn": "000005086326000064"}'),
            "facts.us-gaap.Goodwill.units.USD[0].accn must be an accession number",
            id="accn-without-dashes",
        ),
        pytest.param(
            goodwill_body(f'{{"end": "2026-06-27", "val": 1, "accn": "{PRIVATE}"}}'),
            "facts.us-gaap.Goodwill.units.USD[0].accn must be an accession number",
            id="accn-text",
        ),
        pytest.param(
            goodwill_body('{"end": "2026-06-27", "val": 1, "accn": 50863}'),
            "facts.us-gaap.Goodwill.units.USD[0].accn must be an accession number",
            id="accn-number",
        ),
    ],
)
def test_a_body_breaking_the_subset_is_refused_naming_the_field(data, message):
    assert failure(data) == REFUSED + message


def test_a_week_date_is_no_yyyy_mm_dd_date():
    assert failure(goodwill_body(f'{{"end": "2026-W26-6", "val": 1, {ACCN}}}')) == (
        REFUSED + "facts.us-gaap.Goodwill.units.USD[0].end must be a YYYY-MM-DD date"
    )


@pytest.mark.parametrize("encoding", ["utf-16", "utf-32"])
def test_a_body_in_another_unicode_encoding_is_not_utf_8(encoding):
    assert failure(json.dumps(document()).encode(encoding)) == REFUSED + "the body is not UTF-8"


# --------------------------------------------------------------------------- flows


def test_a_10q_flow_is_the_entry_of_its_quarter():
    facts = read(
        {
            REVENUE: concept(
                fact(Q2_26, END, 29_700, YEAR),  # the half year
                fact(Q2_26, END, 16_100, QUARTER),
                fact(Q2_26, date(2025, 6, 28), 12_900, date(2025, 3, 30)),  # the quarter a year earlier
            )
        }
    )

    assert figure(facts, SEASONS, "revenue", season(Q2_26)) == Figure(
        "revenue",
        END,
        Decimal(16_100),
        "USD",
        REVENUE,
        Q2_26.accession,
        QUARTER,
        END,
        "reported for the quarter",
    )


@pytest.mark.parametrize(("days", "read_as_quarter"), [(79, False), (80, True), (100, True), (101, False)])
def test_the_quarters_entry_is_80_to_100_days_long(days, read_as_quarter):
    facts = read({"OperatingIncomeLoss": concept(fact(Q2_26, END, 1_800, END - timedelta(days=days - 1)))})

    found = figure(facts, SEASONS, "operating_income", season(Q2_26))

    assert found.value == (Decimal(1_800) if read_as_quarter else None)


def test_a_flow_reported_for_the_year_to_date_only_is_its_difference_from_the_previous_seasons():
    facts = read(
        {
            CASH_FLOW: concept(
                fact(Q1_26, date(2026, 3, 28), 1_100, YEAR),
                fact(Q2_26, END, 8_100, YEAR),
                fact(Q2_26, date(2025, 6, 28), 9_000, date(2024, 12, 29)),  # the half year a year earlier
            )
        }
    )

    assert figure(facts, SEASONS, "operating_cash_flow", season(Q2_26)) == Figure(
        "operating_cash_flow",
        END,
        Decimal(7_000),
        "USD",
        CASH_FLOW,
        Q2_26.accession,
        QUARTER,
        END,
        "the year to date 2025-12-28 to 2026-06-27 less the year to date 2025-12-28 to 2026-03-28 of the "
        "filing 0000050863-26-000041",
    )


def test_a_third_quarters_flow_is_its_nine_months_less_the_half_year():
    facts = read(
        {
            CASH_FLOW: concept(
                fact(Q2_25, date(2025, 6, 28), 4_000, date(2024, 12, 29)),
                fact(Q3_25, date(2025, 9, 27), 6_500, date(2024, 12, 29)),
            )
        }
    )

    found = figure(facts, SEASONS, "operating_cash_flow", season(Q3_25))

    assert (found.value, found.start, found.end, found.formula) == (
        Decimal(2_500),
        date(2025, 6, 29),
        date(2025, 9, 27),
        "the year to date 2024-12-29 to 2025-09-27 less the year to date 2024-12-29 to 2025-06-28 of the "
        "filing 0000050863-25-000140",
    )


def test_a_10k_flow_is_its_year_less_the_third_quarters_nine_months():
    facts = read(
        {
            REVENUE: concept(
                fact(Q3_25, date(2025, 9, 27), 13_000, date(2025, 6, 29)),
                fact(Q3_25, date(2025, 9, 27), 39_000, date(2024, 12, 29)),
                fact(K25, date(2025, 12, 27), 52_500, date(2024, 12, 29)),
                fact(K25, date(2024, 12, 28), 53_100, date(2023, 12, 31)),  # the year before, compared
            )
        }
    )

    assert figure(facts, SEASONS, "revenue", season(K25)) == Figure(
        "revenue",
        date(2025, 12, 27),
        Decimal(13_500),
        "USD",
        REVENUE,
        K25.accession,
        date(2025, 9, 28),
        date(2025, 12, 27),
        "the year 2024-12-29 to 2025-12-27 less the nine months 2024-12-29 to 2025-09-27 of the filing "
        "0000050863-25-000201",
    )


def test_a_10k_that_reports_its_fourth_quarter_gives_that_entry():
    facts = read(
        {
            REVENUE: concept(
                fact(Q3_25, date(2025, 9, 27), 39_000, date(2024, 12, 29)),
                fact(K25, date(2025, 12, 27), 52_500, date(2024, 12, 29)),
                fact(K25, date(2025, 12, 27), 13_400, date(2025, 9, 28)),
            )
        }
    )

    found = figure(facts, SEASONS, "revenue", season(K25))

    assert (found.value, found.formula) == (Decimal(13_400), "reported for the quarter")


@pytest.mark.parametrize(
    ("days", "computed"), [(349, False), (350, True), (371, True), (380, True), (381, False)]
)
def test_a_10ks_year_is_350_to_380_days_long(days, computed):
    start = date(2025, 12, 27) - timedelta(days=days - 1)
    facts = read(
        {
            "NetIncomeLoss": concept(
                fact(Q3_25, date(2025, 9, 27), 1_200, start),
                fact(K25, date(2025, 12, 27), 1_700, start),
            )
        }
    )

    found = figure(facts, SEASONS, "net_income", season(K25))

    assert found.value == (Decimal(500) if computed else None)


def test_a_10k_after_a_season_that_is_no_third_quarter_has_no_quarter_figure():
    seasons = listing(K24, Q1_25, Q2_25, K25)  # the third quarter's 10-Q is not listed
    facts = read(
        {
            REVENUE: concept(
                fact(Q2_25, date(2025, 6, 28), 26_000, date(2024, 12, 29)),
                fact(K25, date(2025, 12, 27), 52_500, date(2024, 12, 29)),
            )
        }
    )

    assert figure(facts, seasons, "revenue", season(K25, seasons)).value is None


@pytest.mark.parametrize(
    "entries",
    [
        pytest.param(
            (fact(Q2_26, END, 8_100, YEAR), fact(Q2_26, date(2026, 3, 28), 1_100, YEAR)),
            id="in-the-seasons-own-filing",
        ),
        pytest.param(
            (fact(Q2_26, END, 8_100, YEAR), fact(K25, date(2026, 3, 28), 1_100, YEAR)),
            id="in-another-filing",
        ),
        pytest.param(
            (fact(Q2_26, END, 8_100, YEAR), fact(Q1_26, date(2026, 3, 28), 1_100, date(2025, 12, 29))),
            id="from-another-start",
        ),
        pytest.param((fact(Q2_26, END, 8_100, YEAR),), id="none"),
    ],
)
def test_the_year_to_date_is_differenced_only_with_the_previous_seasons_own(entries):
    facts = read({CASH_FLOW: concept(*entries)})

    found = figure(facts, SEASONS, "operating_cash_flow", season(Q2_26))

    assert (found.value, found.reason) == (
        None,
        f"the filing 0000050863-26-000064 reports no {CASH_FLOW} for the quarter",
    )


def test_the_oldest_listed_season_has_no_previous_year_to_date():
    seasons = listing(Q2_25, Q3_25)
    facts = read({CASH_FLOW: concept(fact(Q2_25, date(2025, 6, 28), 4_000, date(2024, 12, 29)))})

    assert figure(facts, seasons, "operating_cash_flow", season(Q2_25, seasons)).value is None


def test_per_share_figures_and_share_counts_are_read_for_the_quarter_only():
    facts = read(
        {
            SHARES: concept(
                fact(Q3_25, date(2025, 9, 27), 4_400, date(2025, 6, 29)),
                fact(Q3_25, date(2025, 9, 27), 4_390, date(2024, 12, 29)),
                fact(K25, date(2025, 12, 27), 4_410, date(2024, 12, 29)),
                unit="shares",
            ),
            "EarningsPerShareDiluted": concept(
                fact(Q3_25, date(2025, 9, 27), 0.12, date(2024, 12, 29)),
                fact(K25, date(2025, 12, 27), 0.2, date(2024, 12, 29)),
                unit="USD/shares",
            ),
        }
    )

    quarter = figure(facts, SEASONS, "diluted_shares", season(Q3_25))
    shares = figure(facts, SEASONS, "diluted_shares", season(K25))
    per_share = figure(facts, SEASONS, "diluted_eps", season(K25))

    assert (quarter.value, quarter.unit, quarter.formula) == (
        Decimal(4_400),
        "shares",
        "reported for the quarter",
    )
    assert (shares.value, shares.unit, shares.reason) == (
        None,
        "shares",
        f"the filing 0000050863-26-000012 reports no {SHARES} for the quarter",
    )
    assert (per_share.value, per_share.unit, per_share.reason) == (
        None,
        "USD/shares",
        "the filing 0000050863-26-000012 reports no EarningsPerShareDiluted for the quarter",
    )


# --------------------------------------------------------------------------- balances


def test_a_balance_is_the_entry_at_the_period_end_in_the_seasons_own_filing():
    facts = read(
        {
            "AccountsReceivableNetCurrent": concept(
                fact(Q2_26, date(2025, 12, 27), 3_800),  # the fiscal year end the 10-Q compares with
                fact(Q2_26, END, 4_000),
                fact(Q1_26, date(2026, 3, 28), 4_100),
            )
        }
    )

    assert figure(facts, SEASONS, "receivables", season(Q2_26)) == Figure(
        "receivables",
        END,
        Decimal(4_000),
        "USD",
        "AccountsReceivableNetCurrent",
        Q2_26.accession,
        None,
        END,
        "the balance at the period end",
    )


def test_a_balance_is_an_entry_without_a_start():
    facts = read({"InventoryNet": concept(fact(Q2_26, END, 12_500, QUARTER))})

    found = figure(facts, SEASONS, "inventory", season(Q2_26))

    assert (found.value, found.reason) == (
        None,
        "the filing 0000050863-26-000064 reports no InventoryNet at 2026-06-27",
    )


def test_every_value_comes_from_the_seasons_own_filing_as_first_reported():
    restated = fact(Q2_26, date(2025, 6, 28), 24_500, frame="CY2025Q2I")  # framed: the latest filed value
    first = read({"Goodwill": concept(fact(Q2_25, date(2025, 6, 28), 24_700), restated)})
    later_only = read({"Goodwill": concept(restated)})

    found = figure(first, SEASONS, "goodwill", season(Q2_25))
    missing = figure(later_only, SEASONS, "goodwill", season(Q2_25))

    assert (found.value, found.accession) == (Decimal(24_700), Q2_25.accession)
    assert (missing.value, missing.reason) == (
        None,
        "the filing 0000050863-25-000140 reports no Goodwill at 2025-06-28",
    )


def test_a_concept_is_read_in_its_measures_unit_only():
    facts = read(
        {
            "Revenues": concept(fact(Q2_26, END, 15_000, QUARTER), unit="EUR"),
            SHARES: concept(fact(Q2_26, END, 5_100, QUARTER), unit="USD"),
        }
    )

    assert facts.entries == {}
    assert figure(facts, SEASONS, "revenue", season(Q2_26)).value is None
    assert figure(facts, SEASONS, "diluted_shares", season(Q2_26)).value is None


# --------------------------------------------------------------------------- concepts, gross profit, debt


@pytest.mark.parametrize(
    ("measure", "first", "second"),
    [
        ("revenue", "Revenues", REVENUE),
        ("revenue", REVENUE, "SalesRevenueNet"),
        ("cost_of_revenue", "CostOfRevenue", "CostOfGoodsAndServicesSold"),
        ("net_income", "NetIncomeLoss", "ProfitLoss"),
        ("receivables", "AccountsReceivableNetCurrent", "ReceivablesNetCurrent"),
        ("payables", "AccountsPayableCurrent", "AccountsPayableTradeCurrent"),
    ],
)
def test_the_first_concept_the_filing_reports_is_read(measure, first, second):
    start = None if measure in ("receivables", "payables") else QUARTER
    both = read({first: concept(fact(Q2_26, END, 100, start)), second: concept(fact(Q2_26, END, 200, start))})
    second_only = read({second: concept(fact(Q2_26, END, 200, start))})
    first_elsewhere = read(
        {
            first: concept(fact(Q2_26, date(2025, 6, 28), 100, None if start is None else date(2025, 3, 30))),
            second: concept(fact(Q2_26, END, 200, start)),
        }
    )

    for facts, tag, value in ((both, first, 100), (second_only, second, 200), (first_elsewhere, second, 200)):
        found = figure(facts, SEASONS, measure, season(Q2_26))
        assert (found.tag, found.value) == (tag, Decimal(value))


def test_gross_profit_is_reported_else_revenue_less_cost_of_revenue():
    revenue = concept(fact(Q2_26, END, 16_100, QUARTER))
    cost = concept(fact(Q2_26, END, 9_600, QUARTER))
    reported = read(
        {"GrossProfit": concept(fact(Q2_26, END, 6_400, QUARTER)), "Revenues": revenue, "CostOfRevenue": cost}
    )
    derived = read({"Revenues": revenue, "CostOfGoodsAndServicesSold": cost})
    revenue_only = read({"Revenues": revenue})

    found = figure(reported, SEASONS, "gross_profit", season(Q2_26))
    missing = figure(revenue_only, SEASONS, "gross_profit", season(Q2_26))

    assert (found.value, found.tag) == (Decimal(6_400), "GrossProfit")
    assert figure(derived, SEASONS, "gross_profit", season(Q2_26)) == Figure(
        "gross_profit",
        END,
        Decimal(6_500),
        "USD",
        "Revenues − CostOfGoodsAndServicesSold",
        Q2_26.accession,
        QUARTER,
        END,
        "revenue less cost of revenue",
    )
    assert (missing.value, missing.reason) == (
        None,
        "the filing 0000050863-26-000064 reports no GrossProfit for the quarter",
    )


def test_debt_is_the_noncurrent_debt_plus_the_current_debt():
    facts = read(
        {
            "LongTermDebtNoncurrent": concept(fact(Q2_26, END, 46_000)),
            "DebtCurrent": concept(fact(Q2_26, END, 4_500)),
        }
    )

    assert figure(facts, SEASONS, "debt", season(Q2_26)) == Figure(
        "debt",
        END,
        Decimal(50_500),
        "USD",
        "LongTermDebtNoncurrent, DebtCurrent",
        Q2_26.accession,
        None,
        END,
        "LongTermDebtNoncurrent + DebtCurrent (an absent part counts 0)",
    )


@pytest.mark.parametrize(
    ("balances", "value", "tags"),
    [
        pytest.param(
            {"LongTermDebtNoncurrent": 46_000, "LongTermDebtCurrent": 2_000, "ShortTermBorrowings": 500}
            | {"CommercialPaper": 1_200},
            49_700,
            "LongTermDebtNoncurrent, LongTermDebtCurrent, ShortTermBorrowings, CommercialPaper",
            id="current-parts",
        ),
        pytest.param(
            {"LongTermDebtNoncurrent": 46_000, "DebtCurrent": 3_700, "LongTermDebtCurrent": 2_000}
            | {"CommercialPaper": 1_200},
            49_700,
            "LongTermDebtNoncurrent, DebtCurrent",
            id="debt-current-before-its-parts",
        ),
        pytest.param(
            {"LongTermDebtNoncurrent": 46_000}, 46_000, "LongTermDebtNoncurrent", id="noncurrent-alone"
        ),
        pytest.param({"CommercialPaper": 1_200}, 1_200, "CommercialPaper", id="commercial-paper-alone"),
        pytest.param({"DebtCurrent": 0}, 0, "DebtCurrent", id="zero-is-a-value"),
    ],
)
def test_an_absent_debt_part_counts_zero(balances, value, tags):
    facts = read({tag: concept(fact(Q2_26, END, amount)) for tag, amount in balances.items()})

    found = figure(facts, SEASONS, "debt", season(Q2_26))

    assert (found.value, found.tag) == (Decimal(value), tags)


def test_without_any_debt_part_debt_has_no_value():
    found = figure(read({"Goodwill": concept(fact(Q2_26, END, 20_400))}), SEASONS, "debt", season(Q2_26))

    assert (found.value, found.tag, found.reason) == (None, None, "the filing reports no debt balance")


def test_an_ambiguous_debt_part_leaves_the_debt_without_a_value():
    facts = read(
        {
            "LongTermDebtNoncurrent": concept(fact(Q2_26, END, 46_000), fact(Q2_26, END, 45_000)),
            "DebtCurrent": concept(fact(Q2_26, END, 4_500)),
        }
    )

    assert figure(facts, SEASONS, "debt", season(Q2_26)).value is None


# --------------------------------------------------------------------------- ambiguity


@pytest.mark.parametrize(
    ("concepts", "measure", "reason"),
    [
        pytest.param(
            {"Goodwill": concept(fact(Q2_26, END, 20_400), fact(Q2_26, END, 20_500))},
            "goodwill",
            "Goodwill: two values in the filing 0000050863-26-000064",
            id="balance",
        ),
        pytest.param(
            {"NetIncomeLoss": concept(fact(Q2_26, END, 900, QUARTER), fact(Q2_26, END, 950, QUARTER))},
            "net_income",
            "NetIncomeLoss: two values for the quarter in the filing 0000050863-26-000064",
            id="quarter",
        ),
        pytest.param(
            {
                "NetIncomeLoss": concept(
                    fact(Q2_26, END, 900, QUARTER), fact(Q2_26, END, 950, date(2026, 3, 30))
                )
            },
            "net_income",
            "NetIncomeLoss: two values for the quarter in the filing 0000050863-26-000064",
            id="two-quarter-spans",
        ),
        pytest.param(
            {
                CASH_FLOW: concept(
                    fact(Q1_26, date(2026, 3, 28), 1_100, YEAR),
                    fact(Q2_26, END, 8_100, YEAR),
                    fact(Q2_26, END, 8_200, YEAR),
                )
            },
            "operating_cash_flow",
            f"{CASH_FLOW}: two values for one span",
            id="year-to-date",
        ),
        pytest.param(
            {
                CASH_FLOW: concept(
                    fact(Q1_26, date(2026, 3, 28), 1_100, YEAR),
                    fact(Q1_26, date(2026, 3, 28), 1_000, YEAR),
                    fact(Q2_26, END, 8_100, YEAR),
                )
            },
            "operating_cash_flow",
            f"{CASH_FLOW}: two values for one span",
            id="previous-year-to-date",
        ),
        pytest.param(
            {
                "Revenues": concept(fact(Q2_26, END, 16_100, QUARTER), fact(Q2_26, END, 16_200, QUARTER)),
                REVENUE: concept(fact(Q2_26, END, 16_100, QUARTER)),
            },
            "revenue",
            "Revenues: two values for the quarter in the filing 0000050863-26-000064",
            id="not-replaced-by-the-next-concept",
        ),
    ],
)
def test_two_values_of_one_concept_filing_and_span_leave_the_figure_without_a_value(
    concepts, measure, reason
):
    found = figure(read(concepts), SEASONS, measure, season(Q2_26))

    assert (found.value, found.reason) == (None, reason)


def test_one_value_listed_twice_is_not_ambiguous():
    facts = read({"Goodwill": concept(fact(Q2_26, END, 20_400), fact(Q2_26, END, 20_400, frame="CY2026Q2I"))})

    assert figure(facts, SEASONS, "goodwill", season(Q2_26)).value == Decimal(20_400)


# --------------------------------------------------------------------------- a season's figures


def quarter_facts() -> CompanyFacts:
    """The facts of the quarters ended 2026-03-28 and 2026-06-27 as their 10-Qs report them."""
    return read(
        {
            REVENUE: concept(
                fact(Q2_26, END, 16_100, QUARTER),
                fact(Q2_26, END, 29_700, YEAR),
                fact(Q2_26, date(2025, 6, 28), 12_900, date(2025, 3, 30)),
            ),
            "CostOfGoodsAndServicesSold": concept(
                fact(Q2_26, END, 9_600, QUARTER), fact(Q2_26, END, 17_800, YEAR)
            ),
            "OperatingIncomeLoss": concept(fact(Q2_26, END, 1_800, QUARTER)),
            "NetIncomeLoss": concept(fact(Q2_26, END, 900, QUARTER)),
            CASH_FLOW: concept(fact(Q1_26, date(2026, 3, 28), 1_100, YEAR), fact(Q2_26, END, 8_100, YEAR)),
            "AccountsReceivableNetCurrent": concept(
                fact(Q2_26, END, 4_000), fact(Q2_26, date(2025, 12, 27), 3_800)
            ),
            "InventoryNet": concept(fact(Q2_26, END, 12_500)),
            "AccountsPayableCurrent": concept(fact(Q2_26, END, 8_700)),
            "LongTermDebtNoncurrent": concept(fact(Q2_26, END, 46_000)),
            "DebtCurrent": concept(fact(Q2_26, END, 4_500)),
            "CashAndCashEquivalentsAtCarryingValue": concept(fact(Q2_26, END, 12_800)),
            SHARES: concept(fact(Q2_26, END, 5_100, QUARTER), unit="shares"),
            "Goodwill": concept(fact(Q2_26, END, 20_400)),
            "StockholdersEquity": concept(fact(Q2_26, END, 87_500)),
            "Assets": concept(fact(Q2_26, END, 202_000)),
            "EarningsPerShareDiluted": concept(fact(Q2_26, END, 0.2, QUARTER), unit="USD/shares"),
        }
    )


def test_a_seasons_figures_are_every_measure_in_the_facts_tables_order():
    figures = season_figures(quarter_facts(), SEASONS, season(Q2_26))

    assert list(figures) == [
        "revenue",
        "cost_of_revenue",
        "gross_profit",
        "operating_income",
        "net_income",
        "operating_cash_flow",
        "receivables",
        "inventory",
        "payables",
        "debt",
        "cash",
        "diluted_shares",
        "goodwill",
        "equity",
        "assets",
        "diluted_eps",
    ]
    assert [found.value for found in figures.values()] == [
        Decimal(16_100),
        Decimal(9_600),
        Decimal(6_500),
        Decimal(1_800),
        Decimal(900),
        Decimal(7_000),
        Decimal(4_000),
        Decimal(12_500),
        Decimal(8_700),
        Decimal(50_500),
        Decimal(12_800),
        Decimal(5_100),
        Decimal(20_400),
        Decimal(87_500),
        Decimal(202_000),
        Decimal("0.2"),
    ]
    assert [found.unit for found in figures.values()] == ["USD"] * 11 + ["shares"] + ["USD"] * 3 + [
        "USD/shares"
    ]
    assert {found.season for found in figures.values()} == {END}


def test_a_season_without_facts_has_every_figure_without_a_value_and_its_reason():
    figures = season_figures(read(), SEASONS, season(Q2_26))

    assert all(
        found.value is None and found.tag is None and found.formula == "" for found in figures.values()
    )
    assert (figures["revenue"].reason, figures["receivables"].reason, figures["debt"].reason) == (
        f"the filing 0000050863-26-000064 reports no Revenues or {REVENUE} or SalesRevenueNet for the "
        "quarter",
        "the filing 0000050863-26-000064 reports no AccountsReceivableNetCurrent or ReceivablesNetCurrent at "
        "2026-06-27",
        "the filing reports no debt balance",
    )


# --------------------------------------------------------------------------- year ago and quarter days


@pytest.mark.parametrize(
    ("filing", "expected"),
    [
        pytest.param(Q2_26, Q2_25, id="second-quarter"),
        pytest.param(Q1_26, Q1_25, id="first-quarter"),
        pytest.param(K25, K24, id="fiscal-year"),
        pytest.param(Q3_25, None, id="not-listed"),
        pytest.param(K24, None, id="oldest"),
    ],
)
def test_the_year_ago_season_is_the_listed_season_of_the_same_form_a_year_before(filing, expected):
    found = year_ago(SEASONS, season(filing))

    assert found == (None if expected is None else season(expected))


@pytest.mark.parametrize(
    ("days", "found"), [(349, False), (350, True), (364, True), (371, True), (380, True), (381, False)]
)
def test_the_year_ago_season_ends_350_to_380_days_before(days, found):
    newer = Filing("10-Q", "0000050863-26-000064", date(2026, 7, 24), END, "intc-20260627.htm")
    older = Filing("10-Q", "0000050863-25-000140", date(2025, 7, 25), END - timedelta(days=days), "older.htm")
    seasons = listing(older, newer)

    assert year_ago(seasons, season(newer, seasons)) == (season(older, seasons) if found else None)


def test_a_season_of_another_form_is_no_year_ago_season():
    annual = Filing("10-K", "0000050863-25-000140", date(2025, 8, 20), date(2025, 6, 28), "annual.htm")
    seasons = listing(annual, Q2_26)

    assert year_ago(seasons, season(Q2_26, seasons)) is None


def test_quarter_days_run_from_the_previous_listed_seasons_end():
    assert quarter_days(SEASONS, season(Q2_26)) == 91
    assert quarter_days(SEASONS, season(K25)) == 91
    assert quarter_days(SEASONS, season(K24)) is None
    gap = listing(Q2_25, Q2_26)
    assert quarter_days(gap, season(Q2_26, gap)) == 364
    assert quarter_days(listing(K24), Season(Q2_26, ())) is None  # a season not listed
