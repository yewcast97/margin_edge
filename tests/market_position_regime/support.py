"""Clock readings and builders for the offline market_position_regime tests.

Expected instants are written with fixed ``EDT``/``EST`` offsets, independently of
``zoneinfo`` and of the code under test. FINRA's workbook is built byte by byte in the layout
verified live (inline strings, whole numbers, the free credits split from February 2010),
CFTC rows and Cboe's VIX file from small numbers, so every expected value in a test can be
worked out by hand. No FINRA or Cboe answer is recorded; one CFTC answer is (``fixtures/``).
"""

import io
import json
import zipfile
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import date, datetime, timedelta, timezone
from xml.sax.saxutils import escape

from market_state_research.common.layout import DataLayout
from market_state_research.common.sessions import completed_session
from market_state_research.market_position_regime.script import cboe, cftc, finra
from market_state_research.market_position_regime.script.periods import (
    VIX_SETTLE,
    Month,
    sessions_within,
    week_of,
)
from market_state_research.market_position_regime.script.store import raw_directory

EDT = timezone(timedelta(hours=-4), "EDT")
EST = timezone(timedelta(hours=-5), "EST")


def edt(*fields: int) -> datetime:
    return datetime(*fields, tzinfo=EDT)


def est(*fields: int) -> datetime:
    return datetime(*fields, tzinfo=EST)


# Tuesday evening: FINRA's 2026-09 is due (since 2026-10-15), the CFTC week of 2026-10-13 is
# due (since Friday 2026-10-16 15:30) and that of 2026-10-20 is not, and the VIX of the session
# 2026-10-20 is due (since 16:15). The VIX file is fetched after that, the other sources before.
NOW = edt(2026, 10, 20, 18, 0)
FETCHED = edt(2026, 10, 20, 12, 0)
VIX_FETCHED = edt(2026, 10, 20, 17, 0)
NEWEST_MONTH = Month(2026, 9)
NEWEST_WEEK = date(2026, 10, 13)
NEWEST_SESSION = date(2026, 10, 20)

# --------------------------------------------------------------------------------------- FINRA


def debit(month: Month) -> int:
    """Synthetic debit balances: 100,000 in 1997-01, rising by 1,000 a month."""
    return 100_000 + 1_000 * ((month.year - 1997) * 12 + month.month - 1)


def balances(
    newest: Month = NEWEST_MONTH, value: Callable[[Month], int] = debit
) -> list[tuple[str, int, int, int | None]]:
    """Every month from ``newest`` down to 1997-01: (month, debit, free cash, free margin or None)."""
    rows = []
    month = newest
    while month >= finra.FIRST_MONTH:
        margin = 2_000 if month >= finra.SPLIT_MONTH else None
        rows.append((month.isoformat(), value(month), 3_000, margin))
        month = month.shifted(-1)
    return rows


def _inline(reference: str, text: str, style: str = "4") -> str:
    return f'<c r="{reference}" s="{style}" t="inlineStr"><is><t>{escape(text)}</t></is></c>'


def _number(reference: str, value: object) -> str:
    return f'<c r="{reference}" s="5"><v>{value}</v></c>'


def sheet_xml(
    rows: Sequence[tuple[str, object, object, object | None]],
    headers: Sequence[str] = finra.HEADERS,
    extra: str = "",
) -> str:
    """FINRA's worksheet: the header row, then one row per entry of ``rows``, newest first."""
    cells = "".join(_inline(f"{column}1", text, "2") for column, text in zip("ABCD", headers, strict=True))
    lines = [f'<row outlineLevel="0" r="1">{cells}</row>']
    for number, (month, debit_value, cash, margin) in enumerate(rows, start=2):
        row = _inline(f"A{number}", month) + _number(f"B{number}", debit_value) + _number(f"C{number}", cash)
        if margin is not None:
            row += _number(f"D{number}", margin)
        lines.append(f'<row outlineLevel="0" r="{number}">{row}</row>')
    return (
        f'{extra}<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f'<dimension ref="A1:D{len(rows) + 1}"/><sheetData>{"".join(lines)}</sheetData></worksheet>'
    )


def workbook_xml(names: Sequence[str] = (finra.SHEET,)) -> str:
    sheets = "".join(
        f'<sheet sheetId="{number}" r:id="rId{number}" name="{escape(name)}"/>'
        for number, name in enumerate(names, start=1)
    )
    return (
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f"<sheets>{sheets}</sheets></workbook>"
    )


RELATIONSHIPS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId3" '
    'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
    '<Relationship Id="rId1" '
    'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
    'Target="worksheets/sheet1.xml"/></Relationships>'
)


def workbook_bytes(
    rows: Sequence[tuple[str, object, object, object | None]] | None = None,
    *,
    sheet: str | None = None,
    workbook: str | None = None,
    relationships: str = RELATIONSHIPS,
    parts: Mapping[str, str] | None = None,
) -> bytes:
    """An xlsx in FINRA's layout; each part can be replaced to break one rule."""
    contents = {
        "[Content_Types].xml": '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<Types/>',
        "xl/workbook.xml": workbook if workbook is not None else workbook_xml(),
        "xl/_rels/workbook.xml.rels": relationships,
        "xl/worksheets/sheet1.xml": sheet
        if sheet is not None
        else sheet_xml(balances() if rows is None else rows),
        **(parts or {}),
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, text in contents.items():
            archive.writestr(name, text)
    return buffer.getvalue()


def save_workbook(layout: DataLayout, data: bytes | None = None, fetched_at: datetime = FETCHED) -> str:
    """Write a workbook raw file as ``fetch`` names it; its name."""
    name = finra.raw_name(fetched_at)
    directory = raw_directory(layout)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / name).write_bytes(workbook_bytes() if data is None else data)
    return name


# ---------------------------------------------------------------------------------------- CFTC

FIFTY = "(S&P 500 INDEX X $50.00)"
TWO_FIFTY = "(S&P 500 INDEX X $250.00)"


def tff_row(
    day: date,
    asset_mgr: tuple[int, int, int] = (1_000, 200, 50),
    lev_money: tuple[int, int, int] = (100, 500, 20),
    open_interest: int = 2_000,
    units: str = FIFTY,
) -> dict[str, str]:
    """One TFF row of the S&P 500 Consolidated, as the API writes it."""
    return {
        "id": f"{day:%y%m%d}{cftc.CONTRACT}F",
        cftc.DATE_FIELD: f"{day.isoformat()}T00:00:00.000",
        "market_and_exchange_names": cftc.MARKET,
        "cftc_contract_market_code": cftc.CONTRACT,
        "futonly_or_combined": cftc.FUTURES_ONLY,
        "contract_units": units,
        "open_interest_all": str(open_interest),
        "asset_mgr_positions_long": str(asset_mgr[0]),
        "asset_mgr_positions_short": str(asset_mgr[1]),
        "asset_mgr_positions_spread": str(asset_mgr[2]),
        "lev_money_positions_long": str(lev_money[0]),
        "lev_money_positions_short": str(lev_money[1]),
        "lev_money_positions_spread": str(lev_money[2]),
    }


def weekly_rows(weeks: Iterable[date], net: Callable[[date], int] = lambda week: 800) -> list[dict[str, str]]:
    """One row per week (dated its Tuesday), asset managers' net long ``net(week)`` and leveraged
    funds' net short 400."""
    return [
        tff_row(week, asset_mgr=(1_000 + net(week), 1_000, 50), lev_money=(100, 500, 20)) for week in weeks
    ]


def answer_value(
    rows: Sequence[Mapping[str, str]], first: date, last: date, fetched_at: datetime = FETCHED
) -> dict[str, object]:
    return {
        "request": cftc.query_url(first, last),
        "fetched_at": fetched_at.isoformat(),
        "first": first.isoformat(),
        "last": last.isoformat(),
        "rows": [dict(row) for row in rows],
    }


def save_answer(
    layout: DataLayout,
    rows: Sequence[Mapping[str, str]],
    first: date | None = None,
    last: date | None = None,
    fetched_at: datetime = FETCHED,
) -> str:
    """Write a CFTC answer raw file as ``fetch`` names it; its name."""
    days = [date.fromisoformat(row[cftc.DATE_FIELD][:10]) for row in rows]
    first = first or week_of(days[0]) - timedelta(days=1)
    last = last or week_of(days[-1]) + timedelta(days=5)
    value = answer_value(rows, first, last, fetched_at)
    name = cftc.raw_name(first, last, fetched_at)
    directory = raw_directory(layout)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / name).write_bytes(json.dumps(value, ensure_ascii=True, separators=(",", ":")).encode())
    return name


def weeks_back(newest: date, count: int) -> list[date]:
    """``count`` consecutive Tuesdays ending with ``newest``, ascending."""
    return [newest - timedelta(weeks=offset) for offset in range(count - 1, -1, -1)]


# ---------------------------------------------------------------------------------------- Cboe


def vix_close(index: int) -> str:
    """Synthetic closes as Cboe writes them: 10.00 on the first session, rising by 0.01 a session."""
    cents = 1_000 + index
    return f"{cents // 100}.{cents % 100:02d}0000"


def history_bytes(
    newest: date = date(2026, 10, 20),
    close: Callable[[int], str] = vix_close,
    extra: Mapping[date, str] | None = None,
) -> bytes:
    """Cboe's file in its verified layout: a row of 1990-01-02, then one row per XNYS session from
    2000-01-03 to ``newest``, the ``index``-th session's values all ``close(index)``; ``extra``
    adds rows of other days (a holiday Cboe calculated the index on) with the close given."""
    rows = {cboe.FIRST_DAY: "20.000000"}
    rows |= {session: close(index) for index, session in enumerate(sessions_within(date(2000, 1, 3), newest))}
    rows |= dict(extra or {})
    lines = [
        cboe.HEADER,
        *(f"{day:%m/%d/%Y},{value},{value},{value},{value}" for day, value in sorted(rows.items())),
    ]
    return ("\n".join(lines) + "\n").encode("ascii")


def save_history(layout: DataLayout, data: bytes | None = None, fetched_at: datetime = VIX_FETCHED) -> str:
    """Write a Cboe raw file as ``fetch`` names and compresses it; its name. By default the file
    holds every session whose VIX was due at ``fetched_at``."""
    if data is None:
        data = history_bytes(completed_session(fetched_at, VIX_SETTLE))
    name = cboe.raw_name(fetched_at)
    directory = raw_directory(layout)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / name).write_bytes(cboe.dump(data))
    return name


def save_all(
    layout: DataLayout, fetched_at: datetime = FETCHED, vix_fetched_at: datetime = VIX_FETCHED
) -> None:
    """A complete archive as of ``NOW``: the workbook, 220 weeks of reports and the VIX history."""
    save_workbook(layout, fetched_at=fetched_at)
    save_answer(layout, weekly_rows(weeks_back(NEWEST_WEEK, 220)), fetched_at=fetched_at)
    save_history(layout, fetched_at=vix_fetched_at)
