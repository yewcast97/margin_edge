"""EDGAR JSON bodies, filing index pages and synthetic filing and exhibit documents for the issuer tests.

``tickers_json`` writes ``company_tickers.json`` as EDGAR serves it: one object of
positional entries ``{"cik_str", "ticker", "title"}`` with compact separators.
``submissions_json`` writes a submissions body with EDGAR's top-level keys and its full
column layout under ``filings.recent`` (the columns the domain never reads included,
newest filing first, the CIK as unpadded text, ``items`` as each row gives it);
``submissions_document`` returns the same body as a dict, for tests that break one field.
``RECENT`` is a default history for INTC with five periods: the 10-K for the fiscal year
ended 2025-12-27 (no earnings release is listed for it; an 8-K naming items 5.02 and 9.01
is, and is no release), the 10-Qs for the quarters ended 2026-03-28 and 2026-06-27, each
with its Item 2.02 8-K dated and filed the day before the 10-Q (``RELEASES``), and an older
10-K and 10-Q, plus a proxy statement without a report date, which the domain no longer
reads, and an 8-K dated after the last 10-Q was filed, which Rule B leaves pending.
``FORM_4`` is a Form 4 whose primary document is EDGAR's rendering of its XML, for the
tests that list one: no form the domain reads.

``filing_index_html`` lays out an 8-K's filing index page as EDGAR serves it (verified on
Intel's 8-K 0000050863-26-000155): the ``formHeader`` and ``formGrouping`` blocks with the
filing date, the period of report and the items, the ``tableFile`` table
``summary="Document Format Files"`` (the Seq header inside an ``<acronym>``; the cover
row linked through ``/ix?doc=`` with its "iXBRL" label; one row per exhibit, graphic and
the complete submission text file) and the ``summary="Data Files"`` table of XBRL files.
``EXHIBITS`` gives the exhibit rows of each release; ``IndexRow`` fields are cell texts,
written HTML-escaped, and a test passes its own rows, header or table parts to break one
rule. ``plain_page`` is a page without any table.

``ten_k_html`` and ``ten_q_html`` lay a document out like EDGAR's inline-XBRL primary
documents, in 2-4 KB: an XML declaration and a comment, ``<title>``, ``<style>`` and
``<script>`` in the head, the ``<ix:header>`` inside a ``display:none`` div, a cover with
inline facts, a segment table of ``td`` cells, NBSP entities (``&nbsp;``, ``&#160;``), a
soft hyphen, the character references ``&amp;``, ``&#8217;`` and ``&#x2014;``, a
``display: none`` div whose text must disappear and one sentence split across two block
elements by a page-break div. The company name, the segment names and the demand, supply
and capex sentences are parameters, inserted HTML-escaped and each contiguous within one
block element, so a test can quote any of them verbatim (the 10-K's customer and pricing
sentences too, after its demand sentences, and its financing sentences, after its capex
sentences); the split sentence is ``" ".join(split)``. ``HIDDEN_TEXTS`` lists text that
the documents carry only in hidden content.

``exhibit_html`` (an earnings release, ``EX-99.1``) and ``commentary_html`` (a CFO
commentary, ``EX-99.2``) are plain HTML in ASCII bytes (other characters as numeric
references): each sentence in one ``<p>``, the release's outlook a ``<table>`` of one
two-cell row per line (``RELEASE_OUTLOOK_LINES`` is each row as the derived text writes
it), one ``&nbsp;`` and one ``display:none`` div holding ``HIDDEN_DIV_TEXT``.
``RELEASE_BOUNDARIES`` is one paragraph holding every sentence-end and closing-mark case
the whole-sentence rule must decide. The commentary also holds a paragraph with a colon
inside its line (``COMMENTARY_COLON``) and a list set as Intel's filings set one, each item
a span holding the glyph "▪" and a padded span holding its text, so the derived line is the
glyph attached to the item (``COMMENTARY_LEAD_IN``, ``COMMENTARY_ITEMS``). Every other
sentence constant is one whole sentence ending with ".", "!", "?" or "…", except the halves
of a split sentence.

Every sentence is synthetic, written for these tests; none is quoted from a real filing.
The identity (INTC, CIK 0000050863, INTEL CORP), the fiscal period ends and the index
page's layout are EDGAR's public metadata.
"""

import html
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime

from market_state_research.common.times import to_eastern

TICKER = "INTC"
CIK = "0000050863"
ENTITY_NAME = "INTEL CORP"  # EDGAR's entity name
COMPANY = "Intel Corporation"  # the name the documents use
TICKERS = (
    (320193, "AAPL", "Apple Inc."),
    (1045810, "NVDA", "NVIDIA CORP"),
    (50863, "INTC", "INTEL CORP"),
)
SEGMENTS = ("Client Computing Group", "Data Center and AI", "Intel Foundry")

TEN_K_PERIOD = date(2025, 12, 27)
TEN_K_DEMAND = (
    "Demand from device manufacturers for our Core Ultra notebook and desktop processors rose this year.",
    "Cloud service providers and enterprises bought more Xeon processors and AI accelerators than before.",
    "External customers placed more orders for our wafer fabrication and advanced packaging services.",
)
TEN_K_SUPPLY = (
    "Our manufacturing processes use silicon wafers, specialty gases, chemicals and photoresists.",
    "Some substrates and photomasks are available from only one or a limited number of suppliers.",
)
TEN_K_CAPEX = (
    "We plan capital expenditures of approximately $20 billion in 2026, mainly for new process nodes.",
    "We intend to fund part of the construction of our new fabrication facilities with partner capital.",
)
TEN_K_CUSTOMERS = ("Our three largest customers accounted for 41% of our net revenue in 2025.",)
TEN_K_PRICING = ("We raised the prices of our Xeon processors at contract renewals in the fourth quarter.",)
TEN_K_FINANCING = (
    "We expect to fund our expansion with cash from operations, senior notes and contributions from our "
    "Arizona partner.",
)
TEN_K_SPLIT = (
    "Energy and water prices at our fabrication facilities in Arizona, Oregon, Ireland and Israel",
    "affect the cost of producing each wafer.",
)

TEN_Q_PERIOD = date(2026, 6, 27)
TEN_Q_DEMAND = (
    "Demand for Core Ultra processors built on the Intel 18A process exceeded our expectations.",
    "Data Center and AI revenue reflected higher demand for Xeon processors from cloud customers.",
)
TEN_Q_SUPPLY = ("Supply of substrates and certain specialty chemicals remained tight during the quarter.",)
TEN_Q_CAPEX = ("We lowered our planned capital expenditures for the year as we slowed construction in Ohio.",)
TEN_Q_SPLIT = (
    "Higher prices for memory and other components purchased from third parties",
    "reduced the gross margin of our client products.",
)

# Text the documents carry only where the derived text must drop it.
HIDDEN_DIV_TEXT = "This paragraph is hidden from readers and never part of the derived text."
SCRIPT_TEXT = 'window.reportViewer = "script text that is never derived";'
STYLE_TEXT = "body { font-family: 'Times New Roman'; } .note { color: gray; }"
HIDDEN_FACT = "--12-27"  # dei:CurrentFiscalYearEndDate, inside ix:hidden
HIDDEN_TEXTS = (HIDDEN_DIV_TEXT, SCRIPT_TEXT, STYLE_TEXT, HIDDEN_FACT)
# The visible sentence that carries the soft hyphen and the character references, as derived.
REFERENCES_SENTENCE = "Research & development and the company’s manufacturing network support every segment."

# The sentences of the earnings releases (EX-99.1) and the CFO commentary (EX-99.2).
RELEASE_GUIDANCE = (
    "For the coming quarter, we expect revenue of $12.6 billion to $13.6 billion.",
    "We expect a gross margin of approximately 36 percent and earnings per share of $0.01.",
)
RELEASE_OUTLOOK = (
    ("Revenue", "$12.6 billion to $13.6 billion"),
    ("Gross margin", "approximately 36 percent"),
    ("Earnings per share", "$0.01"),
)
# Each outlook table row as the derived text writes it: its two cells joined by one space.
RELEASE_OUTLOOK_LINES = tuple(f"{label} {value}" for label, value in RELEASE_OUTLOOK)
RELEASE_CAPEX = (
    "We expect gross capital investments of approximately $18 billion in 2026.",
    "Net capital spending is expected to be between $8.0 billion and $11.0 billion.",
)
RELEASE_DEMAND = (
    "Demand for AI PC processors was stronger than we expected during the quarter.",
    "Customer inventory levels in the data center market remained elevated.",
)
RELEASE_SUPPLY = ("Supply of advanced packaging capacity remained constrained during the quarter.",)
RELEASE_RAMP = ("Intel 18A entered high-volume production at our Arizona factory during the quarter.",)
# One paragraph, so one derived line: every sentence-end and closing-mark case of the whole-sentence rule.
RELEASE_BOUNDARIES = (
    "Our chief executive said that “demand in the data center market remains strong.” "
    "Will supply keep pace with it? Lead times for substrates fell… "
    "(Capital spending is expected to rise.) Shipments grew in the U.S. market! "
    "Capital spending rose there as well. We call this plan “Project Alpha” and it continues."
)
COMMENTARY_CAPEX = ("We now expect net capital spending of approximately $9 billion for the full year.",)
COMMENTARY_SUPPLY = ("Lead times for substrates improved compared with the prior quarter.",)
COMMENTARY_DEMAND = ("Bookings for the fourth quarter are tracking ahead of our prior view.",)
COMMENTARY_TITLE = "CFO Commentary on Financial Results"
# A paragraph with a colon inside its line, before a capital: no speaker the agent writes opens it.
COMMENTARY_COLON = "Our priorities are clear: We will add capacity for Intel 18A in 2027."
# A list as Intel's filings set one: the glyph "▪" in a span of its own and the item in a padded
# span, so the derived line is the glyph attached to the item ("▪higher…"). The lead-in ends with a
# colon, the first item continues it in lowercase, the second is capitalised and holds two sentences.
COMMENTARY_LEAD_IN = "Our outlook for the fourth quarter reflects the following:"
COMMENTARY_BULLET = "▪"
COMMENTARY_ITEMS = (
    "higher demand for Xeon processors from cloud customers; and",
    "Supply of substrates remains tight. We expect lead times to improve in 2027.",
)

# English names, independent of the host locale (strftime's %B is not).
MONTHS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)


# --------------------------------------------------------------------------- EDGAR JSON


@dataclass(frozen=True)
class Row:
    """One filing as EDGAR lists it under ``filings.recent``; ``period`` is its ``reportDate``."""

    form: str
    accession: str
    filed: date
    period: date | None
    primary_document: str
    items: str = ""
    accepted: str | None = None  # EDGAR's acceptanceDateTime text; None: 20:05 UTC on ``filed``


OLD_TEN_K = Row("10-K", "0000050863-25-000009", date(2025, 1, 31), date(2024, 12, 28), "intc-20241228.htm")
OLD_TEN_Q = Row("10-Q", "0000050863-25-000201", date(2025, 10, 31), date(2025, 9, 27), "intc-20250927.htm")
TEN_K = Row("10-K", "0000050863-26-000012", date(2026, 1, 30), TEN_K_PERIOD, "intc-20251227.htm")
TEN_Q_1 = Row("10-Q", "0000050863-26-000041", date(2026, 4, 24), date(2026, 3, 28), "intc-20260328.htm")
TEN_Q_2 = Row("10-Q", "0000050863-26-000064", date(2026, 7, 24), TEN_Q_PERIOD, "intc-20260627.htm")
# The earnings releases: an exact 8-K naming Item 2.02, dated by its event (reportDate).
EIGHT_K_Q1 = Row(
    "8-K", "0000050863-26-000040", date(2026, 4, 23), date(2026, 4, 23), "intc-20260423.htm", "2.02,9.01"
)
EIGHT_K_Q2 = Row(
    "8-K", "0000050863-26-000062", date(2026, 7, 23), date(2026, 7, 23), "intc-20260723.htm", "2.02,9.01"
)
# An 8-K without Item 2.02 (a change of officers), listed after the 10-K's period: never a release.
EIGHT_K_OTHER = Row(
    "8-K", "0000050863-26-000020", date(2026, 2, 10), date(2026, 2, 9), "intc-20260209.htm", "5.02,9.01"
)
FORM_4 = Row(
    "4", "0001209191-26-061234", date(2026, 8, 3), date(2026, 7, 30), "xslF345X05/wk-form4_1754251234.xml"
)
PROXY = Row("DEF 14A", "0001193125-26-112233", date(2026, 3, 27), None, "d123456ddef14a.htm")
# An 8-K dated after the 10-Q for the quarter ended 2026-06-27 was filed: pending.
PENDING_8K = Row(
    "8-K", "0000050863-26-000066", date(2026, 8, 3), date(2026, 7, 30), "intc-20260730.htm", "8.01"
)
RECENT = (  # newest first, as EDGAR lists them
    PENDING_8K,
    TEN_Q_2,
    EIGHT_K_Q2,
    TEN_Q_1,
    EIGHT_K_Q1,
    PROXY,
    EIGHT_K_OTHER,
    TEN_K,
    OLD_TEN_Q,
    OLD_TEN_K,
)
# The release of each of the workflow tests' periods that has one, by the role of its index page.
RELEASES: dict[str, Row] = {"index_1": EIGHT_K_Q1, "index_2": EIGHT_K_Q2}

_ISSUER_FORMS = frozenset({"10-K", "10-Q", "8-K", "10-K/A", "10-Q/A", "10-KT"})


def tickers_json(entries: Sequence[tuple[int, str, str]] = TICKERS) -> str:
    """``company_tickers.json`` listing ``(cik_str, ticker, title)`` entries in order."""
    body = {
        str(position): {"cik_str": cik, "ticker": ticker, "title": title}
        for position, (cik, ticker, title) in enumerate(entries)
    }
    return json.dumps(body, separators=(",", ":"))


def accepted_text(row: Row) -> str:
    """The row's ``acceptanceDateTime`` as EDGAR writes it: its own, else 20:05 UTC on its filing date."""
    if row.accepted is not None:
        return row.accepted
    return f"{row.filed.isoformat()}T20:05:00.000Z"


def accepted_at(row: Row) -> datetime:
    """The New York time the row's ``acceptanceDateTime`` names."""
    return to_eastern(datetime.fromisoformat(accepted_text(row)[:-1]).replace(tzinfo=UTC), "accepted")


def _recent(rows: Sequence[Row]) -> dict[str, list[object]]:
    """EDGAR's ``filings.recent`` columns, in EDGAR's column order."""
    issuer = [row.form in _ISSUER_FORMS for row in rows]
    return {
        "accessionNumber": [row.accession for row in rows],
        "filingDate": [row.filed.isoformat() for row in rows],
        "reportDate": [row.period.isoformat() if row.period else "" for row in rows],
        "acceptanceDateTime": [accepted_text(row) for row in rows],
        "act": ["34" if flag else "" for flag in issuer],
        "form": [row.form for row in rows],
        "fileNumber": ["000-06217" if flag else "" for flag in issuer],
        "filmNumber": [str(261000000 + index) if flag else "" for index, flag in enumerate(issuer)],
        "items": [row.items for row in rows],
        "core_type": [row.form for row in rows],
        "size": [1_000_000 + 7919 * index for index in range(len(rows))],
        "isXBRL": [1 if flag else 0 for flag in issuer],
        "isInlineXBRL": [1 if flag else 0 for flag in issuer],
        "primaryDocument": [row.primary_document for row in rows],
        "primaryDocDescription": [row.form for row in rows],
    }


def submissions_document(
    cik: str = CIK, name: str = ENTITY_NAME, rows: Sequence[Row] = RECENT
) -> dict[str, object]:
    """A submissions body as a dict, with every top-level key EDGAR sends."""
    address = {
        "street1": "1 EXAMPLE WAY",
        "street2": None,
        "city": "SANTA CLARA",
        "stateOrCountry": "CA",
        "zipCode": "95054",
        "stateOrCountryDescription": "CA",
    }
    return {
        "cik": str(int(cik)),
        "entityType": "operating",
        "sic": "3674",
        "sicDescription": "Semiconductors & Related Devices",
        "ownerOrg": "04 Manufacturing",
        "insiderTransactionForOwnerExists": 0,
        "insiderTransactionForIssuerExists": 1,
        "name": name,
        "tickers": [TICKER],
        "exchanges": ["Nasdaq"],
        "ein": "000000000",
        "lei": None,
        "description": "",
        "website": "",
        "investorWebsite": "",
        "category": "Large Accelerated Filer",
        "fiscalYearEnd": "1227",
        "stateOfIncorporation": "DE",
        "stateOfIncorporationDescription": "DE",
        "addresses": {"mailing": address, "business": address},
        "phone": "000-000-0000",
        "flags": "",
        "formerNames": [],
        "filings": {
            "recent": _recent(rows),
            "files": [
                {
                    "name": f"CIK{cik}-submissions-001.json",
                    "filingCount": 1250,
                    "filingFrom": "1994-01-26",
                    "filingTo": "2015-02-13",
                }
            ],
        },
    }


def submissions_json(cik: str = CIK, name: str = ENTITY_NAME, rows: Sequence[Row] = RECENT) -> str:
    """The submissions body of ``cik`` (ten digits) as EDGAR serves it."""
    return json.dumps(submissions_document(cik, name, rows), separators=(",", ":"))


# --------------------------------------------------------------------------- filing index pages


@dataclass(frozen=True)
class IndexRow:
    """One row of an index page's "Document Format Files" table: its five cell texts.

    The Document cell links to ``href``, by default the document in the filing's folder
    (``/Archives/edgar/data/{cik}/{accession without hyphens}/{document}``); ``linked``
    False writes the document name without a link. ``{stem}`` in a document name stands
    for the 8-K's primary document without its extension, as EDGAR names XBRL files.
    """

    seq: str
    description: str
    document: str
    type: str
    size: str
    href: str | None = None
    linked: bool = True


INDEX_HEADER = ("Seq", "Description", "Document", "Type", "Size")
Q1_EXHIBITS = (IndexRow("2", "EX-99.1", "q126earningsrelease.htm", "EX-99.1", "398211"),)
Q2_EXHIBITS = (
    IndexRow("2", "EX-99.1", "q226earningsrelease.htm", "EX-99.1", "410408"),
    IndexRow("3", "EX-99.2", "q226cfocommentary.htm", "EX-99.2", "88120"),
)
# The exhibit rows of each release, by the role of its index page.
EXHIBITS: dict[str, tuple[IndexRow, ...]] = {"index_1": Q1_EXHIBITS, "index_2": Q2_EXHIBITS}
GRAPHIC_ROWS = (
    IndexRow("8", "", "{stem}_g1.jpg", "GRAPHIC", "5170"),
    IndexRow("9", "", "unboxedlogo_20202a.jpg", "GRAPHIC", "24502"),
)
DATA_FILES = (
    IndexRow("5", "XBRL TAXONOMY EXTENSION SCHEMA DOCUMENT", "{stem}.xsd", "EX-101.SCH", "1789"),
    IndexRow("6", "XBRL TAXONOMY EXTENSION LABEL LINKBASE DOCUMENT", "{stem}_lab.xml", "EX-101.LAB", "21885"),
    IndexRow(
        "7", "XBRL TAXONOMY EXTENSION PRESENTATION LINKBASE DOCUMENT", "{stem}_pre.xml", "EX-101.PRE", "12516"
    ),
    IndexRow("17", "EXTRACTED XBRL INSTANCE DOCUMENT", "{stem}_htm.xml", "XML", "2721"),
)
# EDGAR's names of the items an 8-K's index page lists.
ITEM_TITLES = {
    "2.02": "Results of Operations and Financial Condition",
    "5.02": (
        "Departure of Directors or Certain Officers; Election of Directors; "
        "Appointment of Certain Officers; Compensatory Arrangements of Certain Officers"
    ),
    "7.01": "Regulation FD Disclosure",
    "9.01": "Financial Statements and Exhibits",
}


def _folder(row: Row, cik: str) -> str:
    return f"/Archives/edgar/data/{int(cik)}/{row.accession.replace('-', '')}"


def _cell(text: str) -> str:
    return f'<td scope="row">{html.escape(text, quote=False)}</td>'


def _document_cell(index_row: IndexRow, folder: str, stem: str) -> str:
    document = index_row.document.replace("{stem}", stem)
    if not index_row.linked:
        return _cell(document)
    href = index_row.href if index_row.href is not None else f"{folder}/{document}"
    return f'<td scope="row"><a href="{html.escape(href)}">{html.escape(document, quote=False)}</a></td>'


def _table_row(position: int, cells: str) -> str:
    """A table row; every second one carries EDGAR's ``evenRow`` class."""
    opening = '<tr class="evenRow">' if position % 2 else "<tr>"
    return f"         {opening}\n            {cells}\n         </tr>"


def _file_row(position: int, index_row: IndexRow, folder: str, stem: str) -> str:
    cells = "\n            ".join(
        (
            _cell(index_row.seq),
            _cell(index_row.description),
            _document_cell(index_row, folder, stem),
            _cell(index_row.type),
            _cell(index_row.size),
        )
    )
    return _table_row(position, cells)


def _header_row(header: Sequence[str]) -> str:
    widths = ('style="width: 5%;"', 'style="width: 40%;"', 'style="width: 20%;"', 'style="width: 10%;"')
    cells = []
    for position, text in enumerate(header):
        width = f" {widths[position]}" if position < len(widths) else ""
        label = (
            '<acronym title="Sequence Number">Seq</acronym>'
            if text == "Seq"
            else html.escape(text, quote=False)
        )
        cells.append(f'<th scope="col"{width}>{label}</th>')
    return "         <tr>\n            " + "\n            ".join(cells) + "\n         </tr>"


def _items_info(items: str) -> str:
    codes = [part.strip() for part in items.split(",") if part.strip()]
    return "".join(
        f"Item {html.escape(code, quote=False)}: {html.escape(ITEM_TITLES.get(code, ''), quote=False)}<br />"
        for code in codes
    )


def filing_index_html(
    row: Row,
    exhibits: Sequence[IndexRow],
    *,
    graphics: Sequence[IndexRow] = GRAPHIC_ROWS,
    data_files: Sequence[IndexRow] = DATA_FILES,
    complete_submission: bool = True,
    header: Sequence[str] = INDEX_HEADER,
    cik: str = CIK,
) -> str:
    """The filing index page of the 8-K ``row`` listing ``exhibits``, laid out as EDGAR serves it.

    The "Document Format Files" table holds ``header``, the cover row (Seq 1, the 8-K's
    primary document through the ``/ix?doc=`` viewer), the exhibit rows, the graphic rows
    and, with ``complete_submission``, the complete submission text file; the "Data Files"
    table holds ``data_files`` (none: no such table).
    """
    folder = _folder(row, cik)
    stem = row.primary_document.rsplit(".", 1)[0]
    document = html.escape(row.primary_document, quote=False)
    cover = "\n            ".join(
        (
            _cell("1"),
            _cell(row.form),
            f'<td scope="row"><a href="/ix?doc={html.escape(folder)}/{html.escape(row.primary_document)}">'
            f'{document}</a> &nbsp;&nbsp;<span style="color: green">iXBRL</span></td>',
            _cell(row.form),
            _cell("26721"),
        )
    )
    rows = [_header_row(header), _table_row(0, cover)]
    for index_row in (*exhibits, *graphics):
        rows.append(_file_row(len(rows) - 1, index_row, folder, stem))
    if complete_submission:
        submission = "\n            ".join(
            (
                '<td scope="row">&nbsp;</td>',
                _cell("Complete submission text file"),
                f'<td scope="row"><a href="{folder}/{row.accession}.txt">{row.accession}.txt</a></td>',
                '<td scope="row">&nbsp;</td>',
                _cell("632944"),
            )
        )
        rows.append(_table_row(len(rows) - 1, submission))
    documents_table = "\n".join(rows)
    data_table = ""
    if data_files:
        data_rows = [_header_row(INDEX_HEADER)]
        for index_row in data_files:
            data_rows.append(_file_row(len(data_rows) - 1, index_row, folder, stem))
        data_rows_html = "\n".join(data_rows)
        data_table = f"""<div class="formDiv">
   <div style="padding: 0px 0px 4px 0px; font-size: 12px; width: 100%; overflow:hidden">
      <p>Data Files</p>
      <table class="tableFile" summary="Data Files">
{data_rows_html}
      </table>\t
   </div>
</div>
"""
    count = 1 + len(exhibits) + len(graphics) + len(data_files)
    period = row.period.isoformat() if row.period else ""
    return f"""<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 4.01 Transitional//EN" "http://www.w3.org/TR/html4/loose.dtd">
<html xmlns="http://www.w3.org/1999/xhtml">
<head>
<meta http-equiv="Content-Type" content="text/html; charset=utf-8" />
<title>EDGAR Filing Documents for {row.accession}</title>
</head>
<body style="margin: 0; font-size: 16px; ">
<div id="contentDiv">
<!-- START FILING DIV -->
<div class="formDiv">
   <div id="formHeader">
      <div id="formName">
         <strong>Form {html.escape(row.form, quote=False)}</strong> - Current report:
      </div>
      <div id="secNum">
         <strong><acronym title="Securities and Exchange Commission">SEC</acronym> Accession \
<acronym title="Number">No.</acronym></strong> {row.accession}
      </div>
   </div>
   <div class="formContent">
      <div class="formGrouping">
         <div class="infoHead">Filing Date</div>
         <div class="info">{row.filed.isoformat()}</div>
         <div class="infoHead">Documents</div>
         <div class="info">{count}</div>
      </div>
      <div class="formGrouping">
         <div class="infoHead">Period of Report</div>
         <div class="info">{period}</div>
      </div>
      <div class="formGrouping">
         <div class="infoHead">Items</div>
         <div class="info">{_items_info(row.items)}</div>
      </div>
      <div style="clear:both"></div>
   </div>
</div>
<!-- END FILING DIV -->
<!-- START DOCUMENT DIV -->
<div class="formDiv">
   <div style="padding: 0px 0px 4px 0px; font-size: 12px; width: 100%; overflow:hidden">
      <p>Document Format Files</p>
      <table class="tableFile" summary="Document Format Files">
{documents_table}
      </table>\t
   </div>
</div>
{data_table}<!-- END DOCUMENT DIV -->
<div class="companyInfo">
  <span class="companyName">{ENTITY_NAME} (Filer)
 <acronym title="Central Index Key">CIK</acronym>: {cik} (see all company filings)</span>
</div>
</div>
</body>
</html>
"""


def plain_page() -> str:
    """A page without any table."""
    return "<html><body><p>No tables</p></body></html>"


# --------------------------------------------------------------------------- filing documents


def long_date(day: date) -> str:
    """``December 27, 2025``, as the documents' cover pages write a date."""
    return f"{MONTHS[day.month - 1]} {day.day}, {day.year}"


def _paragraphs(sentences: Sequence[str]) -> str:
    return "\n".join(f"<p>{html.escape(sentence, quote=False)}</p>" for sentence in sentences)


def _document(
    *,
    form: str,
    period_line: str,
    company: str,
    period: date,
    ticker: str,
    segments: Sequence[str],
    demand: Sequence[str],
    supply: Sequence[str],
    capex: Sequence[str],
    customers: Sequence[str],
    pricing: Sequence[str],
    financing: Sequence[str],
    split: tuple[str, str],
    items: tuple[str, str, str],
) -> str:
    name = f"{ticker.lower()}-{period.strftime('%Y%m%d')}"
    rows = "\n".join(
        f"<tr><td>{html.escape(segment, quote=False)}</td><td>$&#160;"
        f'<ix:nonFraction name="us-gaap:Revenues" contextRef="c-{position + 2}" unitRef="usd" '
        f'decimals="-6" scale="6">{12_000 + 1_111 * position:,}</ix:nonFraction></td></tr>'
        for position, segment in enumerate(segments)
    )
    business, risks, analysis = items
    return f"""<?xml version="1.0" encoding="utf-8"?>
<!-- Synthetic inline XBRL document for offline tests -->
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:ix="http://www.xbrl.org/2013/inlineXBRL">
<head>
<meta http-equiv="Content-Type" content="text/html; charset=utf-8"/>
<title>{name}</title>
<style type="text/css">{STYLE_TEXT}</style>
<script type="text/javascript">{SCRIPT_TEXT}</script>
</head>
<body>
<div style="display:none"><ix:header><ix:hidden>
<ix:nonNumeric name="dei:CurrentFiscalYearEndDate" contextRef="c-1">{HIDDEN_FACT}</ix:nonNumeric>
</ix:hidden><ix:resources><xbrli:context id="c-1"><xbrli:entity>
<xbrli:identifier scheme="http://www.sec.gov/CIK">{CIK}</xbrli:identifier>
</xbrli:entity><xbrli:period><xbrli:endDate>{period.isoformat()}</xbrli:endDate></xbrli:period>
</xbrli:context></ix:resources></ix:header></div>
<div style="text-align:center">
<p>UNITED STATES SECURITIES AND EXCHANGE COMMISSION</p>
<p>FORM&nbsp;<ix:nonNumeric name="dei:DocumentType" contextRef="c-1">{form}</ix:nonNumeric></p>
<p>{period_line} {MONTHS[period.month - 1]}&nbsp;{period.day},&#160;{period.year}</p>
<p><ix:nonNumeric name="dei:EntityRegistrantName" contextRef="c-1">{html.escape(company, quote=False)}\
</ix:nonNumeric></p>
</div>
<p>PART&nbsp;I &#x2014; Item&nbsp;{business}</p>
{_paragraphs((*demand, *customers, *pricing))}
<table>
<tr><th>Operating segment</th><th>Net revenue (in millions)</th></tr>
{rows}
</table>
<p>Item&nbsp;{risks}</p>
{_paragraphs(supply)}
<div><span>{html.escape(split[0], quote=False)}</span></div>
<div style="page-break-after:always"></div>
<div><span>{html.escape(split[1], quote=False)}</span></div>
<p>Item&nbsp;{analysis}</p>
{_paragraphs((*capex, *financing))}
<p>Research &amp; development and the company&#8217;s manu&shy;facturing network support every segment.</p>
<div style="DISPLAY: None">{HIDDEN_DIV_TEXT}</div>
</body>
</html>
"""


def ten_k_html(
    company: str = COMPANY,
    segments: Sequence[str] = SEGMENTS,
    demand: Sequence[str] = TEN_K_DEMAND,
    supply: Sequence[str] = TEN_K_SUPPLY,
    capex: Sequence[str] = TEN_K_CAPEX,
    customers: Sequence[str] = TEN_K_CUSTOMERS,
    pricing: Sequence[str] = TEN_K_PRICING,
    financing: Sequence[str] = TEN_K_FINANCING,
    split: tuple[str, str] = TEN_K_SPLIT,
    period: date = TEN_K_PERIOD,
    ticker: str = TICKER,
) -> str:
    """A synthetic annual report: business (demand, customers, pricing, segment table), risk factors
    (supply), MD&A (capex, financing)."""
    return _document(
        form="10-K",
        period_line="For the fiscal year ended",
        company=company,
        period=period,
        ticker=ticker,
        segments=segments,
        demand=demand,
        supply=supply,
        capex=capex,
        customers=customers,
        pricing=pricing,
        financing=financing,
        split=split,
        items=("1. Business", "1A. Risk Factors", "7. Management&#8217;s Discussion and Analysis"),
    )


def ten_q_html(
    company: str = COMPANY,
    segments: Sequence[str] = SEGMENTS,
    demand: Sequence[str] = TEN_Q_DEMAND,
    supply: Sequence[str] = TEN_Q_SUPPLY,
    capex: Sequence[str] = TEN_Q_CAPEX,
    split: tuple[str, str] = TEN_Q_SPLIT,
    period: date = TEN_Q_PERIOD,
    ticker: str = TICKER,
) -> str:
    """A synthetic quarterly report: financial statements (demand), risk factors (supply), MD&A (capex)."""
    return _document(
        form="10-Q",
        period_line="For the quarterly period ended",
        company=company,
        period=period,
        ticker=ticker,
        segments=segments,
        demand=demand,
        supply=supply,
        capex=capex,
        customers=(),
        pricing=(),
        financing=(),
        split=split,
        items=(
            "1. Financial Statements",
            "1A. Risk Factors",
            "2. Management&#8217;s Discussion and Analysis",
        ),
    )


# --------------------------------------------------------------------------- exhibit documents

RELEASE_TITLES = {
    "q126earningsrelease.htm": "Intel Reports First-Quarter 2026 Financial Results",
    "q226earningsrelease.htm": "Intel Reports Second-Quarter 2026 Financial Results",
}


def _ascii(text: str) -> str:
    """``text`` HTML-escaped, every character beyond ASCII as a numeric character reference."""
    return html.escape(text, quote=False).encode("ascii", "xmlcharrefreplace").decode("ascii")


def _ascii_paragraphs(sentences: Sequence[str]) -> str:
    return "\n".join(f"<p>{_ascii(sentence)}</p>" for sentence in sentences)


def _quarter_line(lead: str, period: date) -> str:
    """The dateline: the one ``&nbsp;`` of an exhibit, inside its period's date."""
    return (
        f"<p>{_ascii(lead)} the quarter ended {MONTHS[period.month - 1]}&nbsp;{period.day}, {period.year}</p>"
    )


def _exhibit_page(title: str, body: str) -> str:
    return f"""<!DOCTYPE html>
<html>
<head>
<meta http-equiv="Content-Type" content="text/html; charset=utf-8">
<title>{_ascii(title)}</title>
</head>
<body>
<h1>{_ascii(title)}</h1>
{body}
<div style="display:none">{HIDDEN_DIV_TEXT}</div>
</body>
</html>
"""


def exhibit_html(
    period: date,
    *,
    title: str,
    company: str = COMPANY,
    guidance: Sequence[str] = RELEASE_GUIDANCE,
    outlook: Sequence[tuple[str, str]] = RELEASE_OUTLOOK,
    capex: Sequence[str] = RELEASE_CAPEX,
    demand: Sequence[str] = RELEASE_DEMAND,
    supply: Sequence[str] = RELEASE_SUPPLY,
    ramp: Sequence[str] = RELEASE_RAMP,
    boundaries: str = RELEASE_BOUNDARIES,
) -> str:
    """A synthetic earnings release (``EX-99.1``) for the quarter ended ``period``.

    The title, the dateline, the demand, supply and ramp paragraphs, the capex paragraphs, the
    business outlook (the guidance sentences, then its table of one two-cell row per
    line) and the ``boundaries`` paragraph, in that order.
    """
    table = "\n".join(
        f"<tr><td>{_ascii(label)}</td><td>{_ascii(value)}</td></tr>" for label, value in outlook
    )
    body = f"""{_quarter_line(f"{company} results for", period)}
<p>Business highlights</p>
{_ascii_paragraphs(demand)}
{_ascii_paragraphs(supply)}
{_ascii_paragraphs(ramp)}
<p>Capital investments</p>
{_ascii_paragraphs(capex)}
<p>Business outlook</p>
{_ascii_paragraphs(guidance)}
<table>
{table}
</table>
<p>{_ascii(boundaries)}</p>"""
    return _exhibit_page(title, body)


def commentary_html(
    period: date,
    *,
    title: str = COMMENTARY_TITLE,
    company: str = COMPANY,
    capex: Sequence[str] = COMMENTARY_CAPEX,
    supply: Sequence[str] = COMMENTARY_SUPPLY,
    demand: Sequence[str] = COMMENTARY_DEMAND,
) -> str:
    """A synthetic CFO commentary (``EX-99.2``) for the quarter ended ``period``: capex, the
    priorities paragraph (``COMMENTARY_COLON``), supply, the outlook list (``COMMENTARY_LEAD_IN``
    and ``COMMENTARY_ITEMS``, each item a glyph span and a padded text span), demand."""
    items = "\n".join(
        f'<div><span style="font-family:Arial">{_ascii(COMMENTARY_BULLET)}</span>'
        f'<span style="padding-left:14.81pt">{_ascii(item)}</span></div>'
        for item in COMMENTARY_ITEMS
    )
    body = f"""{_quarter_line(f"{company} commentary on", period)}
{_ascii_paragraphs(capex)}
<p>{_ascii(COMMENTARY_COLON)}</p>
{_ascii_paragraphs(supply)}
<p>{_ascii(COMMENTARY_LEAD_IN)}</p>
{items}
{_ascii_paragraphs(demand)}"""
    return _exhibit_page(title, body)
