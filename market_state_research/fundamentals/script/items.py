"""The items a season is read against: what each compares, with what, and the level it gives.

Pure data. Each item (``ITEMS``, in catalogue order) belongs to one of nine sections
(``SECTIONS``) and is read by one hand (``Who``): ``python`` computes it from structured data
into ``measures.md`` (``measures``), ``bot`` reads it from the documents into the season's
``readings.md`` (``readings``), and ``none`` has no source the domain reads (it stays
``no source``). An item compares the season with a ``Baseline`` (or with nothing) and gives
a level: ``red``, ``yellow`` or ``grey`` where its rule triggers, ``none`` where it does not,
or a status saying why there is no comparison (``STATUSES``). The rule texts are the item's
whole definition; the thresholds in them are starting points, changed only here (and in
``measures`` for the Python items), never per ticker.

Which statuses an item may take: ``no baseline`` when its baseline is not in ``raw/``;
``not applicable`` for an annual item (``scope`` ``annual``) in a 10-Q season and a proxy
item (``proxy``) in a season without a proxy statement; ``unavailable`` for a call item
(``call``) while the season's call has no transcript; ``not disclosed`` and ``not computable``
only where the item allows them (``allows``); ``no source`` for the items of ``none``.

The score of a season is ``SCORES`` summed over its items' levels: red 10, yellow 3, grey 1;
a count of triggered comparisons, not a valuation.
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
Level = Literal["red", "yellow", "grey", "none"]
Status = Literal[
    "no baseline", "not applicable", "not disclosed", "unavailable", "not computable", "no source"
]

LEVELS: Final[tuple[Level, ...]] = ("red", "yellow", "grey", "none")
STATUSES: Final[tuple[Status, ...]] = (
    "no baseline",
    "not applicable",
    "not disclosed",
    "unavailable",
    "not computable",
    "no source",
)
SCORES: Final[Mapping[str, int]] = {"red": 10, "yellow": 3, "grey": 1}
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
    """One item: its id (``1.1``), title, section, who reads it, its baseline, its scope, the
    statuses it allows beyond those of its baseline and scope, and its rule."""

    id: str
    title: str
    who: Who
    baseline: Baseline
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
        "The midpoint of this season's full-year revenue guidance against the previous guidance's: lowered "
        "→ red; raised by more than 5% → yellow.",
        allows=_DISCLOSED,
    ),
    Item(
        "1.2",
        "Full-year profit guidance",
        "bot",
        "previous guidance",
        "The midpoint of this season's full-year guidance of earnings per share, net income, operating "
        "income or a margin against the previous guidance's for the same measure: lowered → red.",
        allows=_DISCLOSED,
    ),
    Item(
        "1.3",
        "Next-quarter guidance against consensus",
        "none",
        "none",
        "No source: the domain reads no consensus.",
    ),
    Item(
        "1.4",
        "Guidance range width",
        "bot",
        "previous guidance",
        "The width (high less low) of a range this season's guidance gives against the previous guidance's "
        "for the same measure: wider by more than 50% → yellow.",
        allows=_DISCLOSED,
    ),
    Item(
        "1.5",
        "Guidance withdrawn",
        "bot",
        "previous guidance",
        "A measure the previous guidance gave that this season's guidance no longer gives → red.",
    ),
    Item(
        "1.6",
        "Capital expenditure guidance",
        "bot",
        "previous guidance",
        "The midpoint of this season's capital expenditure guidance against the previous guidance's: a "
        "change of more than 20% either way → yellow.",
        allows=_DISCLOSED,
    ),
    Item(
        "1.7",
        "Results against the previous guidance",
        "bot",
        "previous guidance",
        "This season's revenue, net income or diluted earnings per share (the values measures.md gives) "
        "against the previous guidance for this quarter: below the low end → red.",
        allows=_DISCLOSED,
    ),
    Item("1.8", "Results against consensus", "none", "none", "No source: the domain reads no consensus."),
    Item(
        "1.9",
        "Guidance record",
        "bot",
        "previous eight seasons",
        "The previous eight seasons' results against their previous guidance (their readings of 1.7): the "
        "count below the low end, a record → grey; this season's 1.7 red after at least six of those "
        "eight at or above the low end → red.",
    ),
    Item(
        "1.10",
        "Full-year kept, next quarter lowered",
        "bot",
        "previous guidance",
        "The full-year guidance midpoint kept or raised while the guidance for the next quarter is below "
        "the previous guidance for that quarter → yellow.",
        allows=_DISCLOSED,
    ),
    # 2 Financials
    Item(
        "2.1",
        "Revenue and net income growth",
        "python",
        "previous quarter and same quarter last year",
        "The year-over-year growth of revenue or of net income down by more than 10 percentage points on "
        "the previous quarter's year-over-year growth → yellow.",
    ),
    Item(
        "2.2",
        "Gross and operating margins",
        "python",
        "previous quarter and same quarter last year",
        "The gross or operating margin more than 200 basis points from the same quarter last year's or "
        "the previous quarter's, either way → yellow.",
    ),
    Item(
        "2.3",
        "Operating cash flow to net income",
        "python",
        "previous quarter and same quarter last year",
        "Operating cash flow ÷ net income below 0.7 after above 1 in the same quarter last year, or below "
        "1 in this season and the previous one while each one's year-ago ratio was 1 or more → red.",
    ),
    Item(
        "2.4",
        "Days of receivables, inventory and payables",
        "python",
        "same quarter last year",
        "Days of sales outstanding (receivables × quarter days ÷ revenue), of inventory and of payables "
        "(inventory or payables × quarter days ÷ cost of revenue): any up by more than 15 days on the "
        "same quarter last year → yellow.",
    ),
    Item(
        "2.5",
        "Receivables growth against revenue growth",
        "python",
        "same quarter last year",
        "The year-over-year growth of receivables less that of revenue above 20 percentage points → red.",
    ),
    Item(
        "2.6",
        "Net debt",
        "python",
        "previous quarter",
        "Net debt (debt less cash and cash equivalents) more than 25% from the previous quarter's, either "
        "way → yellow; not computable when its sign changed or the previous quarter's is under 1% of "
        "that quarter's stockholders' equity.",
    ),
    Item(
        "2.7",
        "Segment revenue shares",
        "bot",
        "same quarter last year",
        "A reported segment's share of revenue more than 5 percentage points from the same quarter last "
        "year's, either way → grey.",
        allows=_DISCLOSED,
    ),
    Item(
        "2.8",
        "Segments merged, split or renamed",
        "bot",
        "previous quarter",
        "A reporting segment of the previous quarter merged, split, renamed or dropped → yellow.",
        allows=_DISCLOSED,
    ),
    Item(
        "2.9",
        "Non-recurring items",
        "bot",
        "none",
        "The items the issuer calls non-recurring, one-time or unusual, summed, above 30% of net income "
        "(the value measures.md gives) → yellow; not computable when net income is 0 or below.",
        allows=_DISCLOSED | _COMPUTABLE,
    ),
    Item(
        "2.10",
        "Weighted diluted shares",
        "python",
        "previous quarter",
        "The weighted average diluted shares more than 2% from the previous quarter's, either way → grey; "
        "not computable in a 10-K season (the annual filing reports the year's average).",
    ),
    Item(
        "2.11",
        "Goodwill added",
        "python",
        "previous quarter",
        "Goodwill up on the previous quarter by more than 10% of stockholders' equity → yellow.",
    ),
    # 3 Accounting and audit
    Item(
        "3.1",
        "Auditor change",
        "bot",
        "none",
        "An 8-K of the season with Item 4.01, a change of the certifying accountant → red.",
    ),
    Item(
        "3.2",
        "Audit opinion",
        "bot",
        "previous 10-K",
        "The auditor's opinion other than unqualified (qualified, adverse, a disclaimer) → red.",
        scope="annual",
    ),
    Item(
        "3.3",
        "Going concern",
        "bot",
        "previous quarter",
        "Substantial doubt about the ability to continue as a going concern, stated now and not in the "
        "previous quarter → red.",
    ),
    Item(
        "3.4",
        "Restatement",
        "bot",
        "none",
        "An 8-K of the season with Item 4.02 (non-reliance on financial statements issued before), or a "
        "restatement the season's filing states → red.",
    ),
    Item(
        "3.5",
        "Material weakness",
        "bot",
        "previous quarter",
        "A material weakness in internal control over financial reporting, stated now and not in the "
        "previous quarter → red.",
    ),
    Item(
        "3.6",
        "Accounting policy change",
        "bot",
        "previous quarter",
        "A change of accounting policy or principle the season's filing states, the adoption of a new "
        "standard included → yellow.",
    ),
    Item(
        "3.7",
        "Accounting estimate change",
        "bot",
        "previous quarter",
        "A change of an accounting estimate the season's filing states (useful lives, reserves, "
        "allowances, assumptions) → yellow.",
    ),
    Item(
        "3.8",
        "New critical audit matter",
        "bot",
        "previous 10-K",
        "A critical audit matter of the auditor's report not in the previous 10-K's → yellow.",
        scope="annual",
    ),
    Item(
        "3.9",
        "Impairment test assumptions",
        "bot",
        "previous 10-K",
        "An assumption of an impairment test moved in the issuer's favour from the previous 10-K's (a "
        "lower discount rate, a higher growth rate) → yellow.",
        scope="annual",
        allows=_DISCLOSED,
    ),
    Item(
        "3.10",
        "Non-GAAP adjustments",
        "bot",
        "previous quarter",
        "A non-GAAP adjustment of the season's earnings release that the previous quarter's did not make, "
        "or one more than 50% larger → yellow.",
        allows=_DISCLOSED,
    ),
    Item(
        "3.11",
        "Revenue recognition wording",
        "bot",
        "previous 10-K",
        "The revenue recognition policy worded otherwise than in the previous 10-K → yellow.",
        scope="annual",
    ),
    # 4 Risk, legal and related parties
    Item(
        "4.1",
        "New risk factor",
        "bot",
        "previous filings",
        "A risk factor the previous quarter's filing and the previous 10-K did not have → yellow.",
    ),
    Item(
        "4.2",
        "Risk wording escalated",
        "bot",
        "previous filings",
        "A risk factor worded from possibility to fact or to a greater likelihood ('may' to 'has', "
        "'could' to 'will', 'possible' to 'likely') → red.",
    ),
    Item(
        "4.3",
        "Risk factor deleted",
        "bot",
        "previous filings",
        "A risk factor of the previous quarter's filing or the previous 10-K no longer stated → grey.",
    ),
    Item(
        "4.4",
        "Litigation and investigations",
        "bot",
        "previous quarter",
        "A legal proceeding or government investigation not in the previous quarter's filing, or an "
        "amount stated for one above 10% of net income (the value measures.md gives) → red.",
    ),
    Item(
        "4.5",
        "Contingent liabilities",
        "bot",
        "previous quarter",
        "The contingent liabilities the filing quantifies, summed, more than 50% from the previous "
        "quarter's, either way → yellow.",
        allows=_DISCLOSED,
    ),
    Item(
        "4.6",
        "Related-party transactions",
        "bot",
        "previous quarter",
        "A related-party transaction not in the previous quarter's filing, or their total up by more "
        "than 50% → yellow.",
        allows=_DISCLOSED,
    ),
    Item(
        "4.7",
        "Guarantees",
        "bot",
        "previous quarter",
        "A guarantee not in the previous quarter's filing, or guarantees above 20% of stockholders' equity "
        "(the value measures.md gives) → yellow.",
        allows=_DISCLOSED,
    ),
    Item(
        "4.8",
        "Largest customers' shares",
        "bot",
        "previous 10-K",
        "The share of revenue of a customer the 10-K names more than 5 percentage points from the previous "
        "10-K's, either way → yellow.",
        scope="annual",
        allows=_DISCLOSED,
    ),
    # 5 Governance and insiders
    Item(
        "5.1",
        "Chief financial officer departure",
        "bot",
        "none",
        "An 8-K of the season with Item 5.02 reporting the departure of the chief financial officer → red.",
    ),
    Item(
        "5.2",
        "Chief executive or chair departure",
        "bot",
        "none",
        "An 8-K of the season with Item 5.02 reporting the departure of the chief executive officer or of "
        "the chair of the board → red.",
    ),
    Item(
        "5.3",
        "Audit committee chair or director departure",
        "bot",
        "none",
        "An 8-K of the season with Item 5.02 reporting the departure of the audit committee's chair, or of "
        "an independent director before the end of their term → yellow.",
    ),
    Item(
        "5.4",
        "Major holder selling",
        "bot",
        "none",
        "A Schedule 13D or 13G amendment of the season whose subject is the issuer, reporting a holder's "
        "stake down by more than 1 percentage point of the class → yellow. The observation names each "
        "filing's subject issuer: the issuer may file one as another company's holder.",
    ),
    Item(
        "5.5",
        "Pledged shares",
        "bot",
        "previous proxy",
        "Shares pledged by a director or executive officer that the previous proxy statement did not "
        "state, or the shares pledged up on the previous proxy statement's → yellow.",
        scope="proxy",
        allows=_DISCLOSED,
    ),
    Item(
        "5.6",
        "Compensation measures changed",
        "bot",
        "previous proxy",
        "A performance measure of the executives' incentive pay added, removed or reweighted from the "
        "previous proxy statement's → yellow.",
        scope="proxy",
        allows=_DISCLOSED,
    ),
    Item(
        "5.7",
        "Officers selling",
        "python",
        "none",
        "Two or more of the issuer's officers reporting in the season's Form 4s a sale (code S) or a "
        "disposition to the issuer (code D) → yellow.",
    ),
    # 6 Capital allocation and financing
    Item(
        "6.1",
        "Dividend change",
        "bot",
        "previous quarter",
        "A dividend cut, suspended or begun against the previous quarter → yellow.",
    ),
    Item(
        "6.2",
        "Buyback authorised, not executed",
        "bot",
        "previous quarter",
        "A share repurchase authorisation under which no share was repurchased in this season and in the "
        "previous one → grey.",
        allows=_DISCLOSED,
    ),
    Item(
        "6.3",
        "Equity or convertible issuance",
        "bot",
        "none",
        "Shares or convertible securities issued, or registered for sale, in the season (the 8-Ks with "
        "Items 3.02 or 1.01 and the registrations measures.md lists) → yellow.",
    ),
    Item(
        "6.4",
        "Acquisition or divestiture",
        "bot",
        "none",
        "An acquisition or divestiture whose stated value would be compared with 5% of the market "
        "value: not computable, the domain reads no market value; the observation gives its amount "
        "against stockholders' equity and total assets (the values measures.md gives).",
        allows=_COMPUTABLE,
    ),
    Item(
        "6.5",
        "Covenant breached or near its limit",
        "bot",
        "previous quarter",
        "A debt covenant the filing calls breached, waived or close to its limit, not so in the previous "
        "quarter → red.",
        allows=_DISCLOSED,
    ),
    Item(
        "6.6",
        "Refinancing on worse terms",
        "bot",
        "previous quarter",
        "Debt refinanced or issued at a higher rate or with tighter terms than the debt it replaces → "
        "yellow.",
    ),
    # 7 Earnings call: statements
    Item(
        "7.1",
        "Opening topics",
        "bot",
        "previous quarter",
        "The first topic of the executives' prepared remarks other than the previous call's → yellow.",
        scope="call",
    ),
    Item(
        "7.2",
        "New explanation",
        "bot",
        "previous quarter",
        "A cause the executives give for a result that the previous call did not give → yellow.",
        scope="call",
    ),
    Item(
        "7.3",
        "Product, customer or market no longer named",
        "bot",
        "previous quarter",
        "A product, customer or market the previous call's prepared remarks named and this call's do not → "
        "yellow.",
        scope="call",
    ),
    Item(
        "7.4",
        "Statement against the filing",
        "bot",
        "none",
        "An executive's statement of a figure that the season's filing or the values measures.md gives "
        "contradict → red.",
        scope="call",
    ),
    # 8 Earnings call: questions and answers
    Item(
        "8.1",
        "Unanswered questions",
        "bot",
        "previous quarter",
        "Questions the executives decline or leave unanswered: twice the previous call's count or more, "
        "or three or more on one topic → yellow.",
        scope="call",
    ),
    Item(
        "8.2",
        "Refusal to quantify",
        "bot",
        "previous quarter",
        "An executive declining to give a figure an analyst asks for that the previous call gave → yellow.",
        scope="call",
    ),
    Item(
        "8.3",
        "Answer against the previous call's",
        "bot",
        "previous quarter",
        "An answer that contradicts what an executive answered on the same topic in the previous call → red.",
        scope="call",
    ),
    Item(
        "8.4",
        "New question topics",
        "bot",
        "previous quarter",
        "More than 30% of the analysts' questions on topics the previous call's questions did not raise → "
        "grey.",
        scope="call",
    ),
    Item(
        "8.5",
        "Analysts on the call",
        "python",
        "previous quarter",
        "The distinct analysts asking questions down by more than 30% on the previous call's → grey; the "
        "names gone and new are listed.",
        scope="call",
    ),
    Item(
        "8.6",
        "Shorter answers",
        "python",
        "previous quarter",
        "The mean words of the executives' turns after the first analyst's turn down by more than 30% on "
        "the previous call's → grey.",
        scope="call",
    ),
    # 9 Disclosure
    Item(
        "9.1",
        "Filing timing",
        "python",
        "previous four seasons",
        "The days from the period end to the 10-K's or 10-Q's filing above each of the previous four of "
        "the same form; or an earnings release accepted after 16:00 on a day whose next XNYS session is "
        "not the next day while none of the previous four seasons' releases was; or a late-filing notice "
        "(NT 10-K, NT 10-Q) in the season → red.",
    ),
    Item(
        "9.2",
        "Operating metric no longer disclosed",
        "bot",
        "previous quarter",
        "An operating metric (units, customers, backlog, another indicator the issuer reports) the "
        "previous quarter's release or filing stated and the season's do not → red.",
    ),
    Item(
        "9.3",
        "Questions and answers compressed",
        "python",
        "previous quarter",
        "The call's duration, or the words from the first analyst's turn to the end, down by more than 30% "
        "on the previous call's → yellow.",
        scope="call",
    ),
    Item(
        "9.4",
        "Text length",
        "python",
        "previous quarter",
        "The derived text of the 10-K or 10-Q against the previous filing of the same form, of the "
        "earnings releases' exhibits and of the call against the previous season's: any more than 20% "
        "longer or shorter → grey.",
    ),
    Item(
        "9.5",
        "8-K count",
        "python",
        "previous four seasons",
        "The season's 8-Ks more than twice the mean of the previous four seasons' → grey.",
    ),
    Item(
        "9.6",
        "Call cancelled",
        "python",
        "previous four seasons",
        "The season's call unavailable while the provider lists a call in each of the previous four "
        "seasons → red.",
    ),
)
BY_ID: Final[Mapping[str, Item]] = {item.id: item for item in ITEMS}
BOT_ITEMS: Final[tuple[Item, ...]] = tuple(item for item in ITEMS if item.who == "bot")
PYTHON_ITEMS: Final[tuple[Item, ...]] = tuple(item for item in ITEMS if item.who == "python")


def score(levels: Mapping[str, str]) -> int:
    """The score of a season's levels, by item id: red 10, yellow 3, grey 1."""
    return sum(SCORES.get(level, 0) for level in levels.values())
