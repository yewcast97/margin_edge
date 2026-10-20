"""FINRA's workbook: its exact layout, and every rule a read checks."""

import io
import zipfile

import pytest

from market_state_research.market_position_regime.script import finra
from market_state_research.market_position_regime.script.finra import (
    Balance,
    check_workbook,
    parse_workbook,
    raw_name,
    read_workbook,
)
from market_state_research.market_position_regime.script.periods import Month

from .support import (
    FETCHED,
    NOW,
    balances,
    edt,
    est,
    sheet_xml,
    workbook_bytes,
    workbook_xml,
)


def refused(data: bytes) -> str:
    with pytest.raises(ValueError) as caught:
        parse_workbook(data)
    message = str(caught.value)
    assert "\n" not in message
    return message


def test_a_workbook_in_finras_layout_gives_every_month_ascending():
    found = parse_workbook(workbook_bytes())
    assert len(found) == 357  # 1997-01 to 2026-09
    assert found[0] == Balance(Month(1997, 1), 100_000, 3_000, None)
    assert found[-1] == Balance(Month(2026, 9), 456_000, 3_000, 2_000)
    by_month = {balance.month: balance for balance in found}
    assert by_month[Month(2010, 1)].free_margin is None
    assert by_month[Month(2010, 2)].free_margin == 2_000


def test_the_newest_month_must_have_ended_before_the_fetch():
    data = workbook_bytes()
    assert check_workbook(data, FETCHED, NOW).newest == Month(2026, 9)
    with pytest.raises(ValueError, match="the newest month, 2026-09, had not ended"):
        check_workbook(data, edt(2026, 9, 30, 23, 0), NOW)
    with pytest.raises(
        ValueError, match="fetched_at 2026-10-20T18:00:01-04:00 is later than the current time"
    ):
        check_workbook(data, edt(2026, 10, 20, 18, 0, 1), NOW)


def test_a_raw_name_carries_the_fetch_time():
    assert raw_name(FETCHED) == "finra_margin_20261020T120000EDT.xlsx"
    assert raw_name(est(2026, 11, 2, 9, 0), "_1") == "finra_margin_20261102T090000EST_1.xlsx"
    workbook = read_workbook(workbook_bytes(), raw_name(FETCHED), NOW)
    assert workbook.fetched_at == FETCHED
    for name in (
        "finra_margin.xlsx",
        "finra_margin_20261020T120000.xlsx",
        "finra_margin_20260701T120000EST.xlsx",
    ):
        with pytest.raises(ValueError, match="the name must be finra_margin_TOKEN.xlsx"):
            read_workbook(workbook_bytes(), name, NOW)


def test_bytes_that_are_not_a_workbook_are_refused():
    assert refused(b"PK not a zip") == "not an Excel workbook (a zip archive)"
    assert refused(b"") == "not an Excel workbook (a zip archive)"
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("readme.txt", "hello")
    assert refused(buffer.getvalue()) == "the workbook has no xl/workbook.xml"


def test_the_workbook_must_list_exactly_the_one_sheet():
    assert "exactly one sheet" in refused(
        workbook_bytes(workbook=workbook_xml(("Customer Margin Balances", "Notes")))
    )
    assert "must be named 'Customer Margin Balances', got 'Margin'" in refused(
        workbook_bytes(workbook=workbook_xml(("Margin",)))
    )
    moved = workbook_bytes(relationships=finra_relationships("worksheets/sheet2.xml"))
    assert refused(moved) == "the sheet 'Customer Margin Balances' must be the part xl/worksheets/sheet1.xml"


def finra_relationships(target: str) -> str:
    return (
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
        f'Target="{target}"/></Relationships>'
    )


def test_a_part_declaring_a_document_type_or_an_entity_is_refused():
    declared = '<!DOCTYPE worksheet [<!ENTITY a "x">]>'
    assert refused(workbook_bytes(sheet=sheet_xml(balances(), extra=declared))) == (
        "xl/worksheets/sheet1.xml declares a document type or an entity"
    )


def test_the_first_row_must_be_finras_four_headers():
    headers = list(finra.HEADERS)
    headers[1] = "Debit Balances"
    assert "the first row must be exactly Year-Month | Debit Balances in Customers'" in refused(
        workbook_bytes(sheet=sheet_xml(balances(), headers=headers))
    )


def test_the_months_must_run_down_one_by_one_to_1997_01():
    rows = balances()
    swapped = [rows[1], rows[0], *rows[2:]]
    assert refused(workbook_bytes(swapped)) == (
        "row 3 is 2026-09; the months must run down one by one from the newest, so it must be 2026-07"
    )
    gap = [rows[0], *rows[2:]]
    assert refused(workbook_bytes(gap)).startswith("row 3 is 2026-07;")
    assert refused(workbook_bytes(rows[:-1])) == "the oldest month must be 1997-01, got 1997-02"
    assert refused(workbook_bytes([])) == "the sheet holds no month"


def test_column_d_is_present_from_february_2010_and_never_before():
    rows = balances()
    split = next(index for index, row in enumerate(rows) if row[0] == "2010-02")
    without = [*rows[:split], (rows[split][0], rows[split][1], rows[split][2], None), *rows[split + 1 :]]
    assert refused(workbook_bytes(without)) == "row 201 must hold exactly the cells A201, B201, C201, D201"
    early = [
        *rows[: split + 1],
        (rows[split + 1][0], rows[split + 1][1], rows[split + 1][2], 7),
        *rows[split + 2 :],
    ]
    assert refused(workbook_bytes(early)) == "row 202 must hold exactly the cells A202, B202, C202"


@pytest.mark.parametrize("value", ["12.5", "-3", "01", "1e3", "", "1 000"])
def test_balances_must_be_whole_numbers_of_millions(value):
    rows = balances()
    rows[0] = (rows[0][0], value, rows[0][2], rows[0][3])
    assert refused(workbook_bytes(rows)) == f"B2 must be a whole number of $ millions, got {value!r}"


@pytest.mark.parametrize("month", ["2026-9", "Sep 2026", "2026-13", ""])
def test_a_month_must_be_written_yyyy_mm(month):
    rows = balances()
    rows[0] = (month, *rows[0][1:])
    assert refused(workbook_bytes(rows)) == f"A2 must be a YYYY-MM month, got {month!r}"


def test_a_month_written_as_a_number_is_refused():
    sheet = sheet_xml(balances()).replace(
        '<c r="A2" s="4" t="inlineStr"><is><t>2026-09</t></is></c>', '<c r="A2" s="4"><v>46280</v></c>'
    )
    assert refused(workbook_bytes(sheet=sheet)) == "A2 must be an inline string"


def test_rich_text_is_refused_where_a_plain_string_is_expected():
    sheet = sheet_xml(balances()).replace(
        "<is><t>2026-09</t></is>", "<is><r><t>2026</t></r><r><t>-09</t></r></is>"
    )
    assert refused(workbook_bytes(sheet=sheet)) == "A2 must hold one plain inline string"


def test_an_oversized_part_is_refused_before_it_is_parsed():
    huge = workbook_bytes(sheet=" " * (finra.PART_LIMIT + 1))
    assert refused(huge) == f"xl/worksheets/sheet1.xml unpacks to more than {finra.PART_LIMIT} bytes"
