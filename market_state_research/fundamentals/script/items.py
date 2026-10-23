"""The items a season is read against: what each compares, with what, and how much it matters.

Pure data. Each item (``ITEMS``, in catalogue order) belongs to one of nine sections
(``SECTIONS``) and is read by one hand (``Who``): ``python`` computes it from structured data
into ``measures.md`` (``measures``), ``bot`` reads it from the documents into the season's
``readings.md`` (``readings``), and ``none`` has no source the domain reads (it stays
``no source``). An item compares the season with a ``Baseline`` (or with nothing): it states
the baseline's value (old) and the season's (new), or a status saying why one cannot be stated
(``STATUSES``). No threshold decides whether a difference counts: every item states both
values, whatever the change. Its importance (``IMPORTANCE``: ``high``, ``medium`` or ``low``)
is fixed by the catalogue, the same in every season and for every issuer, and orders the
report, which lists every item. The rule texts are the item's whole definition, changed only
here, never per ticker.

Which statuses an item may take: ``no baseline`` when its baseline is not in ``raw/``;
``not applicable`` for an annual item (``scope`` ``annual``) in a 10-Q season and a proxy
item (``proxy``) in a season without a proxy statement; ``unavailable`` for a call item
(``call``) while the season's call has no transcript; ``not disclosed`` and ``not computable``
only where the item allows them (``allows``); ``no source`` for the items of ``none``.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final, Literal

Who = Literal["python", "bot", "none"]
Scope = Literal["season", "annual", "proxy", "call"]
Baseline = Literal[
    "none",
    "previous quarter",
    "same quarter last year",
    "previous quarter and same quarter last year",
    "previous filings",
    "previous 10-K",
    "previous proxy",
    "previous guidance",
    "previous eight seasons",
    "previous four seasons",
]
Importance = Literal["high", "medium", "low"]
Status = Literal[
    "no baseline", "not applicable", "not disclosed", "unavailable", "not computable", "no source"
]

IMPORTANCE: Final[tuple[Importance, ...]] = ("high", "medium", "low")
STATUSES: Final[tuple[Status, ...]] = (
    "no baseline",
    "not applicable",
    "not disclosed",
    "unavailable",
    "not computable",
    "no source",
)
SECTIONS: Final[Mapping[int, str]] = {
    1: "Guidance",
    2: "Financials",
    3: "Accounting and audit",
    4: "Risk, legal and related parties",
    5: "Governance and insiders",
    6: "Capital allocation and financing",
    7: "Earnings call: statements",
    8: "Earnings call: questions and answers",
    9: "Disclosure",
}
# How many seasons back each baseline reaches, for the seasons fetch keeps beside the window.
BASELINE_SEASONS: Final = 4


@dataclass(frozen=True)
class Item:
    """One item: its id (``1.1``), title, who reads it, its baseline, its importance, its rule,
    its scope and the statuses it allows beyond those of its baseline and scope."""

    id: str
    title: str
    who: Who
    baseline: Baseline
    importance: Importance
    rule: str
    scope: Scope = "season"
    allows: frozenset[Status] = frozenset()

    @property
    def section(self) -> int:
        return int(self.id.split(".")[0])

    @property
    def heading(self) -> str:
        """The item's heading in a readings file and a report: ``{id} {title}``."""
        return f"{self.id} {self.title}"


_DISCLOSED: Final[frozenset[Status]] = frozenset({"not disclosed"})
_COMPUTABLE: Final[frozenset[Status]] = frozenset({"not computable"})

ITEMS: Final[tuple[Item, ...]] = (
    # 1 Guidance
    Item(
        "1.1",
        "Full-year revenue guidance",
        "bot",
        "previous guidance",
        "high",
        "The full-year revenue guidance, its range and midpoint: this season's against the previous "
        "guidance's.",
        allows=_DISCLOSED,
    ),
    Item(
        "1.2",
        "Full-year profit guidance",
        "bot",
        "previous guidance",
        "high",
        "The full-year guidance of earnings per share, net income, operating income or a margin, each "
        "range and midpoint: this season's against the previous guidance's for the same measure.",
        allows=_DISCLOSED,
    ),
    Item(
        "1.3",
        "Next-quarter guidance against consensus",
        "none",
        "none",
        "high",
        "No source: the domain reads no consensus.",
    ),
    Item(
        "1.4",
        "Guidance range width",
        "bot",
        "previous guidance",
        "medium",
        "The width (high less low) of each range the guidance gives: this season's against the previous "
        "guidance's for the same measure.",
        allows=_DISCLOSED,
    ),
    Item(
        "1.5",
        "Guidance withdrawn",
        "bot",
        "previous guidance",
        "high",
        "The measures the guidance gives: this season's against the previous guidance's, those no longer "
        "given named.",
    ),
    Item(
        "1.6",
        "Capital expenditure guidance",
        "bot",
        "previous guidance",
        "medium",
        "The capital expenditure guidance, its range and midpoint: this season's against the previous "
        "guidance's.",
        allows=_DISCLOSED,
    ),
    Item(
        "1.7",
        "Results against the previous guidance",
        "bot",
        "previous guidance",
        "high",
        "This season's revenue, net income and diluted earnings per share (the values measures.md gives) "
        "against the previous guidance's range for this quarter.",
        allows=_DISCLOSED,
    ),
    Item(
        "1.8",
        "Results against consensus",
        "none",
        "none",
        "medium",
        "No source: the domain reads no consensus.",
    ),
    Item(
        "1.9",
        "Guidance record",
        "bot",
        "previous eight seasons",
        "low",
        "The results against the previous guidance (the readings of 1.7): this season's against the "
        "previous eight seasons', counted below, within and above the range.",
    ),
    Item(
        "1.10",
        "Full-year kept, next quarter lowered",
        "bot",
        "previous guidance",
        "medium",
        "The full-year guidance midpoint and the guidance for the next quarter: this season's against "
        "the previous guidance's for the same periods.",
        allows=_DISCLOSED,
    ),
    # 2 Financials
    Item(
        "2.1",
        "Revenue and net income growth",
        "python",
        "previous quarter and same quarter last year",
        "medium",
        "The year-over-year growth of revenue and of net income: this season's against the previous "
        "quarter's.",
    ),
    Item(
        "2.2",
        "Gross and operating margins",
        "python",
        "previous quarter and same quarter last year",
        "medium",
        "The gross and operating margins: this season's against the same quarter last year's and the "
        "previous quarter's.",
    ),
    Item(
        "2.3",
        "Operating cash flow to net income",
        "python",
        "previous quarter and same quarter last year",
        "high",
        "Operating cash flow ÷ net income: this season's against the same quarter last year's and the "
        "previous quarter's; not computable where net income is 0 or below.",
    ),
    Item(
        "2.4",
        "Days of receivables, inventory and payables",
        "python",
        "same quarter last year",
        "medium",
        "Days of sales outstanding (receivables × quarter days ÷ revenue), of inventory and of payables "
        "(inventory or payables × quarter days ÷ cost of revenue): this season's against the same "
        "quarter last year's.",
    ),
    Item(
        "2.5",
        "Receivables growth against revenue growth",
        "python",
        "same quarter last year",
        "high",
        "The receivables at the period end and the quarter's revenue: this season's against the same "
        "quarter last year's, each change giving its growth.",
    ),
    Item(
        "2.6",
        "Net debt",
        "python",
        "previous quarter",
        "medium",
        "Net debt (debt less cash and cash equivalents): this season's against the previous quarter's.",
    ),
    Item(
        "2.7",
        "Segment revenue shares",
        "bot",
        "same quarter last year",
        "low",
        "Each reported segment's share of revenue: this season's against the same quarter last year's.",
        allows=_DISCLOSED,
    ),
    Item(
        "2.8",
        "Segments merged, split or renamed",
        "bot",
        "previous quarter",
        "medium",
        "The reporting segments: this season's against the previous quarter's, any merged, split, renamed "
        "or dropped named.",
        allows=_DISCLOSED,
    ),
    Item(
        "2.9",
        "Non-recurring items",
        "bot",
        "none",
        "medium",
        "The items the issuer calls non-recurring, one-time or unusual in the season, summed, and their "
        "share of net income (the value measures.md gives); not computable when net income is 0 or "
        "below.",
        allows=_DISCLOSED | _COMPUTABLE,
    ),
    Item(
        "2.10",
        "Weighted diluted shares",
        "python",
        "previous quarter",
        "low",
        "The weighted average diluted shares: this season's against the previous quarter's; not "
        "computable in a 10-K season (the annual filing reports the year's average).",
    ),
    Item(
        "2.11",
        "Goodwill added",
        "python",
        "previous quarter",
        "medium",
        "Goodwill, and goodwill as a share of stockholders' equity: this season's against the previous "
        "quarter's.",
    ),
    # 3 Accounting and audit
    Item(
        "3.1",
        "Auditor change",
        "bot",
        "none",
        "high",
        "An 8-K of the season with Item 4.01, a change of the certifying accountant: the accountant "
        "dismissed and the one engaged.",
    ),
    Item(
        "3.2",
        "Audit opinion",
        "bot",
        "previous 10-K",
        "high",
        "The auditor's opinion (unqualified, qualified, adverse or a disclaimer): this season's against "
        "the previous 10-K's.",
        scope="annual",
    ),
    Item(
        "3.3",
        "Going concern",
        "bot",
        "previous quarter",
        "high",
        "A substantial doubt about the ability to continue as a going concern: as this season's filing "
        "states it against the previous quarter's.",
    ),
    Item(
        "3.4",
        "Restatement",
        "bot",
        "none",
        "high",
        "An 8-K of the season with Item 4.02 (non-reliance on financial statements issued before), or a "
        "restatement the season's filing states.",
    ),
    Item(
        "3.5",
        "Material weakness",
        "bot",
        "previous quarter",
        "high",
        "A material weakness in internal control over financial reporting: as this season's filing states "
        "it against the previous quarter's.",
    ),
    Item(
        "3.6",
        "Accounting policy change",
        "bot",
        "previous quarter",
        "medium",
        "The changes of accounting policy or principle the filing states, the adoption of a new standard "
        "included: this season's against the previous quarter's.",
    ),
    Item(
        "3.7",
        "Accounting estimate change",
        "bot",
        "previous quarter",
        "medium",
        "The changes of accounting estimates the filing states (useful lives, reserves, allowances, "
        "assumptions): this season's against the previous quarter's.",
    ),
    Item(
        "3.8",
        "New critical audit matter",
        "bot",
        "previous 10-K",
        "medium",
        "The critical audit matters of the auditor's report: this season's against the previous 10-K's.",
        scope="annual",
    ),
    Item(
        "3.9",
        "Impairment test assumptions",
        "bot",
        "previous 10-K",
        "medium",
        "The assumptions of the impairment tests (discount rates, growth rates): this season's against "
        "the previous 10-K's.",
        scope="annual",
        allows=_DISCLOSED,
    ),
    Item(
        "3.10",
        "Non-GAAP adjustments",
        "bot",
        "previous quarter",
        "medium",
        "The non-GAAP adjustments of the earnings release, each with its amount: this season's against "
        "the previous quarter's.",
        allows=_DISCLOSED,
    ),
    Item(
        "3.11",
        "Revenue recognition wording",
        "bot",
        "previous 10-K",
        "medium",
        "The wording of the revenue recognition policy: this season's against the previous 10-K's.",
        scope="annual",
    ),
    # 4 Risk, legal and related parties
    Item(
        "4.1",
        "New risk factor",
        "bot",
        "previous filings",
        "medium",
        "The risk factors: this season's against those of the previous quarter's filing and the previous "
        "10-K, those added named.",
    ),
    Item(
        "4.2",
        "Risk wording escalated",
        "bot",
        "previous filings",
        "high",
        "The wording of the risk factors: this season's against the previous quarter's filing and the "
        "previous 10-K, any worded from possibility to fact or to a greater likelihood ('may' to 'has', "
        "'could' to 'will', 'possible' to 'likely') named.",
    ),
    Item(
        "4.3",
        "Risk factor deleted",
        "bot",
        "previous filings",
        "low",
        "The risk factors: this season's against those of the previous quarter's filing and the previous "
        "10-K, those no longer stated named.",
    ),
    Item(
        "4.4",
        "Litigation and investigations",
        "bot",
        "previous quarter",
        "high",
        "The legal proceedings and government investigations, with the amounts stated for them: this "
        "season's against the previous quarter's filing; net income (the value measures.md gives) for "
        "scale.",
    ),
    Item(
        "4.5",
        "Contingent liabilities",
        "bot",
        "previous quarter",
        "medium",
        "The contingent liabilities the filing quantifies, summed: this season's against the previous "
        "quarter's.",
        allows=_DISCLOSED,
    ),
    Item(
        "4.6",
        "Related-party transactions",
        "bot",
        "previous quarter",
        "medium",
        "The related-party transactions, their counterparties and total: this season's against the "
        "previous quarter's.",
        allows=_DISCLOSED,
    ),
    Item(
        "4.7",
        "Guarantees",
        "bot",
        "previous quarter",
        "medium",
        "The guarantees and their total: this season's against the previous quarter's; stockholders' "
        "equity (the value measures.md gives) for scale.",
        allows=_DISCLOSED,
    ),
    Item(
        "4.8",
        "Largest customers' shares",
        "bot",
        "previous 10-K",
        "medium",
        "The share of revenue of each customer the 10-K names: this season's against the previous 10-K's.",
        scope="annual",
        allows=_DISCLOSED,
    ),
    # 5 Governance and insiders
    Item(
        "5.1",
        "Chief financial officer departure",
        "bot",
        "none",
        "high",
        "An 8-K of the season with Item 5.02 reporting the departure of the chief financial officer.",
    ),
    Item(
        "5.2",
        "Chief executive or chair departure",
        "bot",
        "none",
        "high",
        "An 8-K of the season with Item 5.02 reporting the departure of the chief executive officer or of "
        "the chair of the board.",
    ),
    Item(
        "5.3",
        "Audit committee chair or director departure",
        "bot",
        "none",
        "medium",
        "An 8-K of the season with Item 5.02 reporting the departure of the audit committee's chair, or of "
        "an independent director before the end of their term.",
    ),
    Item(
        "5.4",
        "Major holder selling",
        "bot",
        "none",
        "medium",
        "The Schedule 13D and 13G amendments of the season whose subject is the issuer: each holder's "
        "percent of the class, as the amendment reports it against its previous schedule. The new value "
        "names each filing's subject issuer: the issuer may file one as another company's holder.",
    ),
    Item(
        "5.5",
        "Pledged shares",
        "bot",
        "previous proxy",
        "medium",
        "The shares pledged by directors and executive officers: this season's proxy statement against "
        "the previous one.",
        scope="proxy",
        allows=_DISCLOSED,
    ),
    Item(
        "5.6",
        "Compensation measures changed",
        "bot",
        "previous proxy",
        "medium",
        "The performance measures of the executives' incentive pay and their weights: this season's proxy "
        "statement against the previous one.",
        scope="proxy",
        allows=_DISCLOSED,
    ),
    Item(
        "5.7",
        "Officers selling",
        "python",
        "none",
        "medium",
        "The issuer's officers reporting in the season's Form 4s a sale (code S) or a disposition to the "
        "issuer (code D).",
    ),
    # 6 Capital allocation and financing
    Item(
        "6.1",
        "Dividend change",
        "bot",
        "previous quarter",
        "medium",
        "The dividend per share and its policy: this season's against the previous quarter's, any cut, "
        "suspension or start named.",
    ),
    Item(
        "6.2",
        "Buyback authorised, not executed",
        "bot",
        "previous quarter",
        "low",
        "The share repurchase authorisation and the shares repurchased under it: this season's against "
        "the previous quarter's.",
        allows=_DISCLOSED,
    ),
    Item(
        "6.3",
        "Equity or convertible issuance",
        "bot",
        "none",
        "medium",
        "Shares or convertible securities issued, or registered for sale, in the season (the 8-Ks with "
        "Items 3.02 or 1.01 and the registrations measures.md lists).",
    ),
    Item(
        "6.4",
        "Acquisition or divestiture",
        "bot",
        "none",
        "medium",
        "The acquisitions and divestitures of the season, each with its stated value; stockholders' "
        "equity and total assets (the values measures.md gives) for scale.",
    ),
    Item(
        "6.5",
        "Covenant breached or near its limit",
        "bot",
        "previous quarter",
        "high",
        "The debt covenants the filing calls breached, waived or close to their limits: this season's "
        "against the previous quarter's.",
        allows=_DISCLOSED,
    ),
    Item(
        "6.6",
        "Refinancing on worse terms",
        "bot",
        "previous quarter",
        "medium",
        "Debt refinanced or issued in the season: its rate and terms against those of the debt it replaces.",
    ),
    # 7 Earnings call: statements
    Item(
        "7.1",
        "Opening topics",
        "bot",
        "previous quarter",
        "medium",
        "The first topic of the executives' prepared remarks: this call's against the previous call's.",
        scope="call",
    ),
    Item(
        "7.2",
        "New explanation",
        "bot",
        "previous quarter",
        "medium",
        "The causes the executives give for the results: this call's against the previous call's.",
        scope="call",
    ),
    Item(
        "7.3",
        "Product, customer or market no longer named",
        "bot",
        "previous quarter",
        "medium",
        "The products, customers and markets the executives' prepared remarks name: this call's against "
        "the previous call's, those no longer named listed.",
        scope="call",
    ),
    Item(
        "7.4",
        "Statement against the filing",
        "bot",
        "none",
        "high",
        "The figures the executives state on the call against the season's filing and the values "
        "measures.md gives, any that they contradict named.",
        scope="call",
    ),
    # 8 Earnings call: questions and answers
    Item(
        "8.1",
        "Unanswered questions",
        "bot",
        "previous quarter",
        "medium",
        "The questions the executives decline or leave unanswered, counted and by topic: this call's "
        "against the previous call's.",
        scope="call",
    ),
    Item(
        "8.2",
        "Refusal to quantify",
        "bot",
        "previous quarter",
        "medium",
        "The figures the executives decline to give when an analyst asks: this call's against the "
        "previous call's, where that call gave them.",
        scope="call",
    ),
    Item(
        "8.3",
        "Answer against the previous call's",
        "bot",
        "previous quarter",
        "high",
        "The executives' answers on the topics the previous call also answered: this call's against the "
        "previous call's, any that contradicts it named.",
        scope="call",
    ),
    Item(
        "8.4",
        "New question topics",
        "bot",
        "previous quarter",
        "low",
        "The topics of the analysts' questions: this call's against the previous call's, with the share "
        "on topics it did not raise.",
        scope="call",
    ),
    Item(
        "8.5",
        "Analysts on the call",
        "python",
        "previous quarter",
        "low",
        "The distinct analysts asking questions: this call's against the previous call's, with the names "
        "on one of the two calls only.",
        scope="call",
    ),
    Item(
        "8.6",
        "Shorter answers",
        "python",
        "previous quarter",
        "low",
        "The mean words of the executives' turns after the first analyst's turn: this call's against the "
        "previous call's.",
        scope="call",
    ),
    # 9 Disclosure
    Item(
        "9.1",
        "Filing timing",
        "python",
        "previous four seasons",
        "high",
        "The days from the period end to the 10-K's or 10-Q's filing: this season's against the previous "
        "four of the same form; the earnings releases accepted after 16:00 on a day whose next XNYS "
        "session is not the next day, and the late-filing notices (NT 10-K, NT 10-Q): this season's "
        "against the previous four seasons'.",
    ),
    Item(
        "9.2",
        "Operating metric no longer disclosed",
        "bot",
        "previous quarter",
        "high",
        "The operating metrics the release and the filing state (units, customers, backlog, other "
        "indicators the issuer reports): this season's against the previous quarter's, those no longer "
        "stated named.",
    ),
    Item(
        "9.3",
        "Questions and answers compressed",
        "python",
        "previous quarter",
        "medium",
        "The call's duration and the words from the first analyst's turn to the end: this call's against "
        "the previous call's.",
        scope="call",
    ),
    Item(
        "9.4",
        "8-K count",
        "python",
        "previous four seasons",
        "low",
        "The 8-Ks placed in the season: this season's count against each of the previous four seasons'.",
    ),
    Item(
        "9.5",
        "Call cancelled",
        "python",
        "previous four seasons",
        "high",
        "The state of the season's call (transcript, unavailable, waiting, missing): this season's against "
        "each of the previous four seasons'.",
    ),
)
BY_ID: Final[Mapping[str, Item]] = {item.id: item for item in ITEMS}
BOT_ITEMS: Final[tuple[Item, ...]] = tuple(item for item in ITEMS if item.who == "bot")
PYTHON_ITEMS: Final[tuple[Item, ...]] = tuple(item for item in ITEMS if item.who == "python")


def by_importance(items: tuple[Item, ...] = ITEMS) -> tuple[Item, ...]:
    """``items`` in the report's order: high importance first, then medium, then low, each in
    catalogue order."""
    return tuple(sorted(items, key=lambda item: (IMPORTANCE.index(item.importance), ITEMS.index(item))))
