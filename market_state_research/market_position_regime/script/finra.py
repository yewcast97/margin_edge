"""FINRA's margin statistics: the workbook, its raw file and every rule a read checks.

FINRA publishes its member firms' customer margin balances (FINRA Rule 4521(d)) as one
Excel workbook at a fixed address (``URL``), replaced in place each month, about the third
week of the month after the month it reports. ``fetch`` writes the workbook's bytes as
received to ``raw/market/finra_margin_{TOKEN}.xlsx``, ``TOKEN`` naming the time it arrived.

Every read checks the workbook whole (``parse_workbook``): a zip archive of bounded size
whose ``xl/workbook.xml`` lists exactly one sheet, ``SHEET``, at ``xl/worksheets/sheet1.xml``
(no document type or entity declaration in any part read); its first row exactly the four
``HEADERS``, as inline strings in A1 to D1; then one row per month, newest first, every
month from the newest to ``FIRST_MONTH`` once and in order, each with the month as an
inline ``YYYY-MM`` string in column A and whole numbers of $ millions in B and C, and in D
from ``SPLIT_MONTH`` on, never before (until January 2010 FINRA reported the free credit
balances of cash and margin accounts together, in C). The newest month must end before the
month the file was fetched in, and the file may not be dated after the clock.
"""

import io
import re
import zipfile
from dataclasses import dataclass
from datetime import datetime
from typing import Final
from xml.etree import ElementTree

from market_state_research.common.times import (
    TOKEN_PATTERN,
    et_isoformat,
    parse_timestamp_token,
    timestamp_token,
    to_eastern,
)

from .periods import Month

URL: Final = "https://www.finra.org/sites/default/files/2021-03/margin-statistics.xlsx"
SHEET: Final = "Customer Margin Balances"
SHEET_PART: Final = "xl/worksheets/sheet1.xml"
HEADERS: Final = (
    "Year-Month",
    "Debit Balances in Customers' Securities Margin Accounts",
    "Free Credit Balances in Customers' Cash Accounts",
    "Free Credit Balances in Customers' Securities Margin Accounts",
)
FIRST_MONTH: Final = Month(1997, 1)
SPLIT_MONTH: Final = Month(2010, 2)  # the first month with column D
PART_LIMIT: Final = 8 * 1024 * 1024  # bytes of one unpacked part read
RAW_NAME: Final = re.compile(rf"finra_margin_(?P<token>{TOKEN_PATTERN})(?:_[0-9]+)?\.xlsx", re.ASCII)
MAX_SUFFIX: Final = 99

_MAIN: Final = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_RELATIONSHIPS: Final = "{http://schemas.openxmlformats.org/package/2006/relationships}"
_RELATIONSHIP_ID: Final = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
_WORKSHEET_TYPE: Final = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet"
_WHOLE_NUMBER = re.compile(r"0|[1-9][0-9]{0,14}", re.ASCII)
_DECLARATION = re.compile(rb"<!(?:DOCTYPE|ENTITY)", re.IGNORECASE)


@dataclass(frozen=True)
class Balance:
    """One month's balances in $ millions, as of its last business day (settlement date)."""

    month: Month
    debit: int  # debit balances in customers' securities margin accounts
    free_cash: int  # free credit balances in customers' cash accounts (all free credits before SPLIT_MONTH)
    free_margin: int | None  # free credit balances in securities margin accounts; None before SPLIT_MONTH


@dataclass(frozen=True)
class Workbook:
    """One valid workbook: when it was fetched and its balances, ascending by month."""

    fetched_at: datetime
    balances: tuple[Balance, ...]

    @property
    def newest(self) -> Month:
        return self.balances[-1].month

    def by_month(self) -> dict[Month, Balance]:
        return {balance.month: balance for balance in self.balances}


def raw_name(fetched_at: datetime, suffix: str = "") -> str:
    """The name of a workbook fetched at ``fetched_at``; ``suffix`` is ``""`` or ``_N``."""
    return f"finra_margin_{timestamp_token(fetched_at)}{suffix}.xlsx"


def _part(archive: zipfile.ZipFile, name: str) -> ElementTree.Element:
    """The parsed XML part ``name`` of ``archive``; a missing, oversized or declaring part raises."""
    try:
        info = archive.getinfo(name)
    except KeyError:
        raise ValueError(f"the workbook has no {name}") from None
    if info.file_size > PART_LIMIT:
        raise ValueError(f"{name} unpacks to more than {PART_LIMIT} bytes")
    try:
        with archive.open(info) as handle:
            data = handle.read(PART_LIMIT + 1)
    except (zipfile.BadZipFile, OSError, EOFError, RuntimeError, NotImplementedError) as error:
        raise ValueError(f"{name} cannot be unpacked: {type(error).__name__}") from None
    if len(data) > PART_LIMIT:
        raise ValueError(f"{name} unpacks to more than {PART_LIMIT} bytes")
    if _DECLARATION.search(data):
        raise ValueError(f"{name} declares a document type or an entity")
    try:
        return ElementTree.fromstring(data)
    except ElementTree.ParseError as error:
        raise ValueError(f"{name} is not well-formed XML: {error}") from None


def _sheet_target(archive: zipfile.ZipFile) -> None:
    """Check that the workbook lists exactly the one sheet, at ``SHEET_PART``."""
    workbook = _part(archive, "xl/workbook.xml")
    container = workbook.find(f"{_MAIN}sheets")
    sheets = [] if container is None else list(container)
    if len(sheets) != 1 or sheets[0].tag != f"{_MAIN}sheet":
        raise ValueError(f"the workbook must list exactly one sheet, {SHEET!r}")
    sheet = sheets[0]
    if sheet.get("name") != SHEET:
        raise ValueError(f"the workbook's sheet must be named {SHEET!r}, got {sheet.get('name')!r}")
    relationships = _part(archive, "xl/_rels/workbook.xml.rels")
    targets = [
        item.get("Target")
        for item in relationships.findall(f"{_RELATIONSHIPS}Relationship")
        if item.get("Id") == sheet.get(_RELATIONSHIP_ID) and item.get("Type") == _WORKSHEET_TYPE
    ]
    if targets != ["worksheets/sheet1.xml"]:
        raise ValueError(f"the sheet {SHEET!r} must be the part {SHEET_PART}")


def _inline_text(cell: ElementTree.Element, where: str) -> str:
    if cell.get("t") != "inlineStr":
        raise ValueError(f"{where} must be an inline string")
    children = list(cell)
    texts = list(children[0]) if len(children) == 1 and children[0].tag == f"{_MAIN}is" else []
    if len(texts) != 1 or texts[0].tag != f"{_MAIN}t" or len(texts[0]):
        raise ValueError(f"{where} must hold one plain inline string")
    return texts[0].text or ""


def _whole_number(cell: ElementTree.Element, where: str) -> int:
    if cell.get("t") not in (None, "n"):
        raise ValueError(f"{where} must be a number")
    children = list(cell)
    if len(children) != 1 or children[0].tag != f"{_MAIN}v" or len(children[0]):
        raise ValueError(f"{where} must hold one value")
    text = children[0].text or ""
    if not _WHOLE_NUMBER.fullmatch(text):
        raise ValueError(f"{where} must be a whole number of $ millions, got {text!r}")
    return int(text)


def _cells(row: ElementTree.Element, number: int, columns: str) -> list[ElementTree.Element]:
    cells = list(row)
    references = [cell.get("r") for cell in cells]
    expected = [f"{column}{number}" for column in columns]
    if any(cell.tag != f"{_MAIN}c" for cell in cells) or references != expected:
        raise ValueError(f"row {number} must hold exactly the cells {', '.join(expected)}")
    return cells


def parse_workbook(data: bytes) -> tuple[Balance, ...]:
    """The balances of the workbook ``data``, ascending by month; every rule of the module
    docstring but the time checks, each problem one ``ValueError`` line."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except (zipfile.BadZipFile, OSError, EOFError, ValueError):
        raise ValueError("not an Excel workbook (a zip archive)") from None
    with archive:
        _sheet_target(archive)
        sheet = _part(archive, SHEET_PART)
    rows_element = sheet.find(f"{_MAIN}sheetData")
    rows = [] if rows_element is None else list(rows_element)
    if not rows:
        raise ValueError("the sheet holds no rows")
    for number, row in enumerate(rows, start=1):
        if row.tag != f"{_MAIN}row" or row.get("r") != str(number):
            raise ValueError(f"row {number} is missing or out of order")
    header = tuple(_inline_text(cell, cell.get("r") or "?") for cell in _cells(rows[0], 1, "ABCD"))
    if header != HEADERS:
        raise ValueError(f"the first row must be exactly {' | '.join(HEADERS)}")
    balances: list[Balance] = []
    for number, row in enumerate(rows[1:], start=2):
        first = list(row)[:1]
        month_text = _inline_text(first[0], f"A{number}") if first else ""
        try:
            month = Month.parse(month_text)
        except ValueError:
            raise ValueError(f"A{number} must be a YYYY-MM month, got {month_text!r}") from None
        if balances and month != balances[-1].month.shifted(-1):
            expected = balances[-1].month.shifted(-1).isoformat()
            raise ValueError(
                f"row {number} is {month.isoformat()}; the months must run down one by one from the "
                f"newest, so it must be {expected}"
            )
        cells = _cells(row, number, "ABCD" if month >= SPLIT_MONTH else "ABC")
        balances.append(
            Balance(
                month=month,
                debit=_whole_number(cells[1], f"B{number}"),
                free_cash=_whole_number(cells[2], f"C{number}"),
                free_margin=_whole_number(cells[3], f"D{number}") if len(cells) == 4 else None,
            )
        )
    if not balances:
        raise ValueError("the sheet holds no month")
    if balances[-1].month != FIRST_MONTH:
        raise ValueError(
            f"the oldest month must be {FIRST_MONTH.isoformat()}, got {balances[-1].month.isoformat()}"
        )
    return tuple(reversed(balances))


def check_workbook(data: bytes, fetched_at: datetime, now: datetime) -> Workbook:
    """The valid workbook ``data`` fetched at ``fetched_at``; every rule of the module docstring."""
    fetched_at = to_eastern(fetched_at, "fetched_at")
    if fetched_at > to_eastern(now, "now"):
        raise ValueError(f"fetched_at {et_isoformat(fetched_at)} is later than the current time")
    balances = parse_workbook(data)
    if balances[-1].month >= Month.of(fetched_at.date()):
        raise ValueError(
            f"the newest month, {balances[-1].month.isoformat()}, had not ended when the workbook was "
            f"fetched ({et_isoformat(fetched_at)})"
        )
    return Workbook(fetched_at, balances)


def read_workbook(data: bytes, name: str, now: datetime) -> Workbook:
    """Validate one raw workbook file named ``name``; every problem raises a one-line ``ValueError``."""
    match = RAW_NAME.fullmatch(name)
    instant = None if match is None else parse_timestamp_token(match["token"])
    if instant is None:
        raise ValueError("the name must be finra_margin_TOKEN.xlsx (or end _N.xlsx), TOKEN a New York time")
    return check_workbook(data, instant, now)
