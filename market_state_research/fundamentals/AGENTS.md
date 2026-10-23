# Fundamentals

This domain keeps, per stock issuer and per season (one fiscal period, named by its end) in a
window, the issuer's own documents of the season verbatim with the company's XBRL facts,
derives their text, compares the season with stated baselines over a catalogue of 69 items,
and renders one report per season: every item's level, a score, and the evidence of every
item that triggered. Python computes the 16 items it can read from structured data into the
season's `measures.md`; the bot reads the documents for 51 others and writes the season's
readings, which `check` holds to their rules; 2 items have no source. Its default tickers are
those of this domain's own watchlist. This file says first what the work aims at, the model
of seasons, filings and calls, the items, the quote rules, the derived text and measures, the
readings, the season report and the commands; then the sources and why Python may read them,
the module boundaries, the runtime files and the formats verified live. The operations the
bot carries out (settings, `fetch`, `plan`, `derive`, reading the documents, writing and
checking readings, `render`, `show`, failures) are in the sibling [PROCEDURE.md](PROCEDURE.md);
the conventions every domain shares (the domain layout, the three sections of `data/`, New
York time, the API rule) are in [market_state_research/AGENTS.md](../AGENTS.md). This domain
reads no market data: its documents are dated by their own dates, and its one use of XNYS
sessions is item 9.1's test of an earnings release accepted after 16:00 on a day whose next
session is not the next day.

## Aim

For each issuer, season by season, what changed against explicit baselines (the previous
quarter, the same quarter a year before, the previous 10-K or proxy statement, the previous
guidance, the previous four or eight seasons), each comparison made mechanically, at scale and
without judgment: a fixed rule, applied alike to every issuer and season, sets its level from
figures the filings report or statements the documents make, and its evidence stays beside it
(values with their XBRL concepts and accessions, or quotes copied verbatim with their
documents). Judgment is the user's: a report says what moved and where the words are, never
what that means. Its score counts the comparisons that triggered, weighted red 10, yellow 3
and grey 1; it is not a valuation, and `show`'s order of the tickers by score says where more
comparisons triggered, nothing of a company's worth. Every original document is kept as
served. No valuation, forecast, rating, recommendation or advice is added by the measures,
the readings, the reports or the bot.

## Seasons, filings and calls

- A season is one exact `10-K` or `10-Q` of EDGAR's `filings.recent`, named by its
  `reportDate`, the fiscal year or quarter end it reports (its period). Amendments and
  transition reports (`10-K/A`, `10-KT`, `10-Q/A`, `10-QT`, `NT 10-Q` ...) are not seasons.
  Two filings that report one period, no exact 10-K or 10-Q at all (a 20-F filer, say) and an
  Item 2.02 8-K without an event date, or dated after its filing date, make the ticker
  `unsupported` with the reason instead of one reading being chosen.
- The other filings the domain reads are dated, placed in a season and either fetched or only
  listed, by form:

  | Forms | Dated by | `fetch` writes |
  | --- | --- | --- |
  | `8-K`, whatever its items | `reportDate`, the event's date | its filing index page, its primary document and the EX-99 exhibits the page lists |
  | `4` | `reportDate`, the earliest transaction's date | its XML, which Python reads |
  | `DEF 14A` | `filingDate` (its `reportDate` is the meeting's date, after the filing) | its primary document |
  | `SC 13D/A`, `SC 13G/A`, `SCHEDULE 13D/A`, `SCHEDULE 13G/A` (EDGAR's two spellings of the beneficial owners' schedule amendments) | `filingDate` | its primary document |
  | `NT 10-K`, `NT 10-Q`, `S-3`, `S-3ASR`, `424B2`, `424B3`, `424B4`, `424B5`, `424B7`, `8-K/A`, `4/A`, `10-K/A`, `10-Q/A` | `filingDate` | nothing: `measures.md` lists them |

  A form dated by its `reportDate` must have one, not after its filing date, and a fetched
  form's `primaryDocument` must be a file the archive serves: a plain name, or EDGAR's
  rendering prefix `xsl…/` before an XML file's name, which is stripped
  (`filings.rendered_document`). A row that breaks either rule (but an Item 2.02 8-K, above)
  is skipped: listed with its reason as `skipped_filings`, never fetched.
- Rule B places a filing dated D in the latest listed season ending before D (P). When a later
  season is listed, the filing belongs to P; when P is the newest listed season, it belongs to
  P only when D is not after the filing date of P's own 10-K or 10-Q, and is otherwise
  pending: dated after the newest season's report was filed. Once EDGAR lists a later season,
  Rule B places it again: it joins the latest season ending before D, which is P itself when
  the later season ends on or after D (an 8-K furnished after P's 10-Q, say), or stays pending
  when that is the new newest season and D is after its filing date. `fetch` and `plan` list
  every pending filing as `pending_filings` when the window ends on or after the newest listed
  season end, and none when it ends before it; nothing of a pending filing is fetched. A
  filing dated on or before the oldest listed season end is dropped, its season not being
  listed. A season's filings are ordered by date, filing date and accession. Rule B uses
  EDGAR's own dates only.
- A filing's documents are kept in the folder of the season Rule B placed it in when `fetch`
  wrote them. Every read places it again, and one the newest listing places in another season,
  or leaves pending, is *moved*: an invalid file (Freshness). This happens only when EDGAR
  lists a season out of its order, a late 10-Q, say.
- An earnings call is a call the transcript provider, EarningsCalls.dev, lists for the ticker
  as an `earnings` event, dated by the New York date of its `event_date_time`. Rule B places
  it as it places a filing: in the latest listed season ending before its date, pending while
  it is dated after the newest season's 10-K or 10-Q was filed (`pending_calls`, listed under
  the same window rule as pending filings), dropped when dated on or before the oldest listed
  season end. A season's call is the transcript of every call placed in it, normally one: the
  annual report's season holds the fourth-quarter call, each quarterly report's its quarter's
  call.
- A season's call is in one of four states, from the provider's newest list in `raw/` (each
  request of the list is kept, so the newest one says when the provider last showed it):
  - `transcript`: the list places one or more calls in the season, and each one's transcript
    is in `raw/`;
  - `missing`: there is no valid list in `raw/`, or a call placed in the season has no valid
    transcript in `raw/`; `fetch` acts on both;
  - `unavailable`: the list places no call in the season, and it was fetched 7 days or more
    after the season's *due date*: the date of its latest earnings release (an 8-K with Item
    2.02), else the filing date of its 10-K or 10-Q. The provider shows no transcript of the
    call: an observation dated by that list (`unavailable as of the calls list of DATE`),
    never a judgment, and a later list that places a call in the season supersedes it;
  - `waiting`: the list places no call in the season yet and was fetched less than 7 days
    after its due date.

  A `waiting` or `unavailable` call blocks nothing: the season's call items are
  `unavailable`, and a transcript that arrives later makes the season's measures, readings and
  report stale. The list is asked for again (`plan` says `fetch`) when there is none, or while
  a window season's call is `waiting` or `unavailable` and the newest list is 7 days old or
  more, or, for a `waiting` call, was fetched on or before the season's due date and that date
  has passed: a call lands within hours, a permanently missing one costs about four requests a
  month.
- The documents of a season, each with its derived text and its `DOC_ID`, are its 10-K or
  10-Q primary document; each 8-K's primary document and every EX-99 exhibit its filing index
  page (`{accession}-index.htm`, the one EDGAR page that names each document's exhibit type)
  lists, in Seq order, except EDGAR's unofficial `.pdf` copies, whose official `.htm` or
  `.txt` is listed too (an EX-99 exhibit is a row whose Type is `EX-99` alone or `EX-99.` and
  a suffix, such as `EX-99.1`; any other Type that starts with `EX-99`, such as `EX-99-1` or
  `EX-99A`, is refused loudly rather than read or ignored); each proxy statement's and
  schedule's primary document; and each call's transcript. An 8-K's earnings release is its
  EX-99 exhibits when it names Item 2.02. The index pages, the Form 4s' XML, the company facts
  and the calls list are kept in `raw/` too and read by Python alone: they have no derived
  text, and no reading quotes them.
- Nothing a read needs lives only in a file name: each filing's form, accession, dates and
  season come from the newest submissions file (Rule B included) on every read, an exhibit's
  type and Seq from its index page, parsed again on every read, a Form 4's issuer, owners and
  transactions from its XML, and each call's id, date and season from the newest calls list,
  with the transcript read against the call it lists.
- The window is a pair of New York calendar dates, `--from` and `--to`, bounding the season
  ends, both included (`--to` defaults to today and may not be after it; `--from` defaults to
  the same day two years before `--to`). Its readings compare each window season with seasons
  before it, so `fetch` writes the *span*: the window's seasons and the four listed before them
  (`items.BASELINE_SEASONS`). `plan` weighs the span's documents, texts and calls and the
  window's measures, readings and reports; `show` weighs the default window. Only
  `filings.recent` is read (EDGAR's latest year or 1,000 filings at least; the older pages
  under `filings.files` are not), so a window whose `--from` precedes the oldest filing date
  it lists is reported `truncated: true`: seasons before that are not seen. As EDGAR's list
  moves on, a later submissions file may no longer list a season: every file of a season older
  than the oldest listed one is then left out, as if it were not in `raw/`, and blocks nothing.
  `derive`, `check` and `render` take no window: they work on every listed season in `raw/`.

## The items

The catalogue below is the whole definition of what a season is read against (`items.py`).
Each item belongs to one of nine sections, is read by one hand and compares the season with
one baseline:

- Read by `Python`, from structured data into `measures.md` (16 items: the company facts, the
  listing, the Form 4s, the call transcripts' turns and durations, the derived texts'
  lengths); by the `bot`, from the documents into the season's readings (51 items); or by no
  one, `no source`, for the two items the domain has no source for (consensus estimates).
- The baseline names the seasons the item compares with:

  | Baseline | Seasons |
  | --- | --- |
  | `previous quarter` | the listed season before |
  | `same quarter last year` | the listed season of the same form ending 350 to 380 days before |
  | `previous quarter and same quarter last year` | both |
  | `previous guidance` | the season before, whose earnings release and call gave the guidance this season is held to |
  | `previous filings` | the season before and the latest earlier 10-K season |
  | `previous 10-K` | the latest earlier 10-K season |
  | `previous proxy` | the latest earlier season holding a proxy statement |
  | `previous four seasons`, `previous eight seasons` | the four or eight listed seasons before |
  | `none` | none: the item reads the season alone |

  The 10-K and proxy baselines look back eight seasons. `measures.md` names, per baseline, its
  seasons and their documents in `raw/` with their `DOC_ID`s; since `fetch` keeps the four
  seasons before the window, an eight-season baseline is read from what `raw/` holds.
- The level is `red`, `yellow` or `grey` where the item's rule triggers and `none` where it
  does not, or a status saying why there is no comparison:
  - `no baseline`: none of the baseline seasons' documents is in `raw/` (for a Python item, a
    season its comparison needs is not listed);
  - `not applicable`: an annual item (scope `annual`) in a 10-Q season, or a proxy item
    (`proxy`) in a season without a proxy statement;
  - `unavailable`: a call item (`call`) while the season's call is not `transcript`;
  - `not disclosed`: the documents do not state what a bot item compares, where the item
    allows it;
  - `not computable`: a figure a Python item needs is missing or ambiguous, or its rule cannot
    apply (a 10-K season's diluted shares, say); for a bot item, only where the item allows
    it;
  - `no source`: the items without a source.
- The score of a season is the sum over its items of 10 per `red`, 3 per `yellow` and 1 per
  `grey` (`items.SCORES`).

The rules, their thresholds included, are code: `items.py` states each, and `measures.py`'s
constants hold the Python items' thresholds. They are starting points, the same for every
issuer, changed only there (`git log -p` dates each change). A changed rule or threshold
changes the measures and the reports rendered after it (`plan` says `derive`, then `render`);
a reading written under an earlier rule keeps passing `check`: apply a changed bot item's rule
by reading the affected seasons again and rewriting that item's readings.

### The catalogue

#### 1 Guidance

- **1.1 Full-year revenue guidance** (bot; baseline: previous guidance; may be `not disclosed`): The midpoint of this season's full-year revenue guidance against the previous guidance's: lowered → red; raised by more than 5% → yellow.
- **1.2 Full-year profit guidance** (bot; baseline: previous guidance; may be `not disclosed`): The midpoint of this season's full-year guidance of earnings per share, net income, operating income or a margin against the previous guidance's for the same measure: lowered → red.
- **1.3 Next-quarter guidance against consensus** (no source; baseline: none): No source: the domain reads no consensus.
- **1.4 Guidance range width** (bot; baseline: previous guidance; may be `not disclosed`): The width (high less low) of a range this season's guidance gives against the previous guidance's for the same measure: wider by more than 50% → yellow.
- **1.5 Guidance withdrawn** (bot; baseline: previous guidance): A measure the previous guidance gave that this season's guidance no longer gives → red.
- **1.6 Capital expenditure guidance** (bot; baseline: previous guidance; may be `not disclosed`): The midpoint of this season's capital expenditure guidance against the previous guidance's: a change of more than 20% either way → yellow.
- **1.7 Results against the previous guidance** (bot; baseline: previous guidance; may be `not disclosed`): This season's revenue, net income or diluted earnings per share (the values measures.md gives) against the previous guidance for this quarter: below the low end → red.
- **1.8 Results against consensus** (no source; baseline: none): No source: the domain reads no consensus.
- **1.9 Guidance record** (bot; baseline: previous eight seasons): The previous eight seasons' results against their previous guidance (their readings of 1.7): the count below the low end, a record → grey; this season's 1.7 red after at least six of those eight at or above the low end → red.
- **1.10 Full-year kept, next quarter lowered** (bot; baseline: previous guidance; may be `not disclosed`): The full-year guidance midpoint kept or raised while the guidance for the next quarter is below the previous guidance for that quarter → yellow.

#### 2 Financials

- **2.1 Revenue and net income growth** (Python; baseline: previous quarter and same quarter last year): The year-over-year growth of revenue or of net income down by more than 10 percentage points on the previous quarter's year-over-year growth → yellow.
- **2.2 Gross and operating margins** (Python; baseline: previous quarter and same quarter last year): The gross or operating margin more than 200 basis points from the same quarter last year's or the previous quarter's, either way → yellow.
- **2.3 Operating cash flow to net income** (Python; baseline: previous quarter and same quarter last year): Operating cash flow ÷ net income below 0.7 after above 1 in the same quarter last year, or below 1 in this season and the previous one while each one's year-ago ratio was 1 or more → red.
- **2.4 Days of receivables, inventory and payables** (Python; baseline: same quarter last year): Days of sales outstanding (receivables × quarter days ÷ revenue), of inventory and of payables (inventory or payables × quarter days ÷ cost of revenue): any up by more than 15 days on the same quarter last year → yellow.
- **2.5 Receivables growth against revenue growth** (Python; baseline: same quarter last year): The year-over-year growth of receivables less that of revenue above 20 percentage points → red.
- **2.6 Net debt** (Python; baseline: previous quarter): Net debt (debt less cash and cash equivalents) more than 25% from the previous quarter's, either way → yellow; not computable when its sign changed or the previous quarter's is under 1% of that quarter's stockholders' equity.
- **2.7 Segment revenue shares** (bot; baseline: same quarter last year; may be `not disclosed`): A reported segment's share of revenue more than 5 percentage points from the same quarter last year's, either way → grey.
- **2.8 Segments merged, split or renamed** (bot; baseline: previous quarter; may be `not disclosed`): A reporting segment of the previous quarter merged, split, renamed or dropped → yellow.
- **2.9 Non-recurring items** (bot; baseline: none; may be `not computable` or `not disclosed`): The items the issuer calls non-recurring, one-time or unusual, summed, above 30% of net income (the value measures.md gives) → yellow; not computable when net income is 0 or below.
- **2.10 Weighted diluted shares** (Python; baseline: previous quarter): The weighted average diluted shares more than 2% from the previous quarter's, either way → grey; not computable in a 10-K season (the annual filing reports the year's average).
- **2.11 Goodwill added** (Python; baseline: previous quarter): Goodwill up on the previous quarter by more than 10% of stockholders' equity → yellow.

#### 3 Accounting and audit

- **3.1 Auditor change** (bot; baseline: none): An 8-K of the season with Item 4.01, a change of the certifying accountant → red.
- **3.2 Audit opinion** (bot; baseline: previous 10-K; annual item): The auditor's opinion other than unqualified (qualified, adverse, a disclaimer) → red.
- **3.3 Going concern** (bot; baseline: previous quarter): Substantial doubt about the ability to continue as a going concern, stated now and not in the previous quarter → red.
- **3.4 Restatement** (bot; baseline: none): An 8-K of the season with Item 4.02 (non-reliance on financial statements issued before), or a restatement the season's filing states → red.
- **3.5 Material weakness** (bot; baseline: previous quarter): A material weakness in internal control over financial reporting, stated now and not in the previous quarter → red.
- **3.6 Accounting policy change** (bot; baseline: previous quarter): A change of accounting policy or principle the season's filing states, the adoption of a new standard included → yellow.
- **3.7 Accounting estimate change** (bot; baseline: previous quarter): A change of an accounting estimate the season's filing states (useful lives, reserves, allowances, assumptions) → yellow.
- **3.8 New critical audit matter** (bot; baseline: previous 10-K; annual item): A critical audit matter of the auditor's report not in the previous 10-K's → yellow.
- **3.9 Impairment test assumptions** (bot; baseline: previous 10-K; annual item; may be `not disclosed`): An assumption of an impairment test moved in the issuer's favour from the previous 10-K's (a lower discount rate, a higher growth rate) → yellow.
- **3.10 Non-GAAP adjustments** (bot; baseline: previous quarter; may be `not disclosed`): A non-GAAP adjustment of the season's earnings release that the previous quarter's did not make, or one more than 50% larger → yellow.
- **3.11 Revenue recognition wording** (bot; baseline: previous 10-K; annual item): The revenue recognition policy worded otherwise than in the previous 10-K → yellow.

#### 4 Risk, legal and related parties

- **4.1 New risk factor** (bot; baseline: previous filings): A risk factor the previous quarter's filing and the previous 10-K did not have → yellow.
- **4.2 Risk wording escalated** (bot; baseline: previous filings): A risk factor worded from possibility to fact or to a greater likelihood ('may' to 'has', 'could' to 'will', 'possible' to 'likely') → red.
- **4.3 Risk factor deleted** (bot; baseline: previous filings): A risk factor of the previous quarter's filing or the previous 10-K no longer stated → grey.
- **4.4 Litigation and investigations** (bot; baseline: previous quarter): A legal proceeding or government investigation not in the previous quarter's filing, or an amount stated for one above 10% of net income (the value measures.md gives) → red.
- **4.5 Contingent liabilities** (bot; baseline: previous quarter; may be `not disclosed`): The contingent liabilities the filing quantifies, summed, more than 50% from the previous quarter's, either way → yellow.
- **4.6 Related-party transactions** (bot; baseline: previous quarter; may be `not disclosed`): A related-party transaction not in the previous quarter's filing, or their total up by more than 50% → yellow.
- **4.7 Guarantees** (bot; baseline: previous quarter; may be `not disclosed`): A guarantee not in the previous quarter's filing, or guarantees above 20% of stockholders' equity (the value measures.md gives) → yellow.
- **4.8 Largest customers' shares** (bot; baseline: previous 10-K; annual item; may be `not disclosed`): The share of revenue of a customer the 10-K names more than 5 percentage points from the previous 10-K's, either way → yellow.

#### 5 Governance and insiders

- **5.1 Chief financial officer departure** (bot; baseline: none): An 8-K of the season with Item 5.02 reporting the departure of the chief financial officer → red.
- **5.2 Chief executive or chair departure** (bot; baseline: none): An 8-K of the season with Item 5.02 reporting the departure of the chief executive officer or of the chair of the board → red.
- **5.3 Audit committee chair or director departure** (bot; baseline: none): An 8-K of the season with Item 5.02 reporting the departure of the audit committee's chair, or of an independent director before the end of their term → yellow.
- **5.4 Major holder selling** (bot; baseline: none): A Schedule 13D or 13G amendment of the season whose subject is the issuer, reporting a holder's stake down by more than 1 percentage point of the class → yellow. The observation names each filing's subject issuer: the issuer may file one as another company's holder.
- **5.5 Pledged shares** (bot; baseline: previous proxy; proxy item; may be `not disclosed`): Shares pledged by a director or executive officer that the previous proxy statement did not state, or the shares pledged up on the previous proxy statement's → yellow.
- **5.6 Compensation measures changed** (bot; baseline: previous proxy; proxy item; may be `not disclosed`): A performance measure of the executives' incentive pay added, removed or reweighted from the previous proxy statement's → yellow.
- **5.7 Officers selling** (Python; baseline: none): Two or more of the issuer's officers reporting in the season's Form 4s a sale (code S) or a disposition to the issuer (code D) → yellow.

#### 6 Capital allocation and financing

- **6.1 Dividend change** (bot; baseline: previous quarter): A dividend cut, suspended or begun against the previous quarter → yellow.
- **6.2 Buyback authorised, not executed** (bot; baseline: previous quarter; may be `not disclosed`): A share repurchase authorisation under which no share was repurchased in this season and in the previous one → grey.
- **6.3 Equity or convertible issuance** (bot; baseline: none): Shares or convertible securities issued, or registered for sale, in the season (the 8-Ks with Items 3.02 or 1.01 and the registrations measures.md lists) → yellow.
- **6.4 Acquisition or divestiture** (bot; baseline: none; may be `not computable`): An acquisition or divestiture whose stated value would be compared with 5% of the market value: not computable, the domain reads no market value; the observation gives its amount against stockholders' equity and total assets (the values measures.md gives).
- **6.5 Covenant breached or near its limit** (bot; baseline: previous quarter; may be `not disclosed`): A debt covenant the filing calls breached, waived or close to its limit, not so in the previous quarter → red.
- **6.6 Refinancing on worse terms** (bot; baseline: previous quarter): Debt refinanced or issued at a higher rate or with tighter terms than the debt it replaces → yellow.

#### 7 Earnings call: statements

- **7.1 Opening topics** (bot; baseline: previous quarter; call item): The first topic of the executives' prepared remarks other than the previous call's → yellow.
- **7.2 New explanation** (bot; baseline: previous quarter; call item): A cause the executives give for a result that the previous call did not give → yellow.
- **7.3 Product, customer or market no longer named** (bot; baseline: previous quarter; call item): A product, customer or market the previous call's prepared remarks named and this call's do not → yellow.
- **7.4 Statement against the filing** (bot; baseline: none; call item): An executive's statement of a figure that the season's filing or the values measures.md gives contradict → red.

#### 8 Earnings call: questions and answers

- **8.1 Unanswered questions** (bot; baseline: previous quarter; call item): Questions the executives decline or leave unanswered: twice the previous call's count or more, or three or more on one topic → yellow.
- **8.2 Refusal to quantify** (bot; baseline: previous quarter; call item): An executive declining to give a figure an analyst asks for that the previous call gave → yellow.
- **8.3 Answer against the previous call's** (bot; baseline: previous quarter; call item): An answer that contradicts what an executive answered on the same topic in the previous call → red.
- **8.4 New question topics** (bot; baseline: previous quarter; call item): More than 30% of the analysts' questions on topics the previous call's questions did not raise → grey.
- **8.5 Analysts on the call** (Python; baseline: previous quarter; call item): The distinct analysts asking questions down by more than 30% on the previous call's → grey; the names gone and new are listed.
- **8.6 Shorter answers** (Python; baseline: previous quarter; call item): The mean words of the executives' turns after the first analyst's turn down by more than 30% on the previous call's → grey.

#### 9 Disclosure

- **9.1 Filing timing** (Python; baseline: previous four seasons): The days from the period end to the 10-K's or 10-Q's filing above each of the previous four of the same form; or an earnings release accepted after 16:00 on a day whose next XNYS session is not the next day while none of the previous four seasons' releases was; or a late-filing notice (NT 10-K, NT 10-Q) in the season → red.
- **9.2 Operating metric no longer disclosed** (bot; baseline: previous quarter): An operating metric (units, customers, backlog, another indicator the issuer reports) the previous quarter's release or filing stated and the season's do not → red.
- **9.3 Questions and answers compressed** (Python; baseline: previous quarter; call item): The call's duration, or the words from the first analyst's turn to the end, down by more than 30% on the previous call's → yellow.
- **9.4 Text length** (Python; baseline: previous quarter): The derived text of the 10-K or 10-Q against the previous filing of the same form, of the earnings releases' exhibits and of the call against the previous season's: any more than 20% longer or shorter → grey.
- **9.5 8-K count** (Python; baseline: previous four seasons): The season's 8-Ks more than twice the mean of the previous four seasons' → grey.
- **9.6 Call cancelled** (Python; baseline: previous four seasons): The season's call unavailable while the provider lists a call in each of the previous four seasons → red.

## Quotes

- Report facts, not ideas, and never distort a statement. A quote is the evidence an item's
  reading rests on: a verbatim span of its own document's derived text, spelt with the text's
  own characters (only the whitespace between words may differ, so a quote holds no soft
  hyphen, zero-width character or ligature the text does not). Nothing in a quote is
  paraphrased, summarised, translated, trimmed, merged, completed or inferred. A quote that is
  invented, reworded, filled in from memory, the web, another document or inference, or
  retyped from anywhere but the derived text is a failed run.
- A quote is whole sentences, or whole lines of an HTML or XML document or a call transcript,
  so that no quote cuts a statement (`text.sentence_bounded`, sentence rule v2, checked at the
  quote's first occurrence in the derived text; its normalised length is 20 to 800
  characters). The rule reads a line break in one of two modes, chosen by the document's kind
  and name alone, never its contents (`documents.layout_mode`):
  - *layout* mode, for a filing or exhibit whose document name ends in `.txt` (any case): a
    line break is ordinary whitespace. These lines wrap where the page ran out, as often inside
    a sentence as at its end, so they carry no structure and a quote runs from a sentence start
    to a sentence end across them; a whole line is not a statement;
  - *block* mode, for HTML, iXBRL and XML documents and a call's transcript: a line break ends
    a block, and a whole line (a table row, a bullet, a heading, a paragraph of a speaker's
    turn) is a quote of its own unless the next line starts in lowercase and so continues it.

  In both modes a quote never starts in lowercase, whatever opening marks and list markers
  come first (`text.BULLETS`: "▪", "•" and the other glyphs issuers set before an item, with
  the spaces and line breaks after them; dashes and asterisks are not among them): such a start
  continues a sentence, as "market" after "U.S." does, or a lead-in, as the item "▪we received
  …;" does. It starts at the text's start, at a block's start (block mode), or after a sentence
  end (`.`, `!`, `?` or `…`, closing marks allowed after it) and whitespace. It starts after a
  colon only where the colon ends a line (a heading) or, in a call only, where the colon is
  that of the quote's own speaker label ("Chief Executive Officer: Thank you."): the whole text
  of the colon's line before it is exactly the name of the quote's speaker, and that line
  itself starts where a quote may. Any other colon is inside its sentence, so "Excluding the
  divestiture: we expect …" can be quoted only from "Excluding". A quote ends
  at the text's end, at a block's end (block mode) before a line that does not start in
  lowercase, or with a sentence end followed by whitespace and text that does not start in
  lowercase (opening marks and list markers before it skipped), so "U.S." before "market",
  "$8." cut from "$8.0" (the next character is "0") and a lead-in before a lowercase item end
  no quote; neither does a quote that starts after `said that “` or ends with `“Project Alpha”`
  where the sentence goes on. A quote may omit the opening and closing marks around it, never a
  list marker it starts after: a bullet is quoted with its glyph.

  The rule sees characters, not grammar, and refuses only the cuts it can see: some cuts pass
  it (an abbreviation's full stop before a capital reads as a sentence end, say), and it
  refuses some whole statements rather than risk a cut (a sentence after a heading without
  punctuation in a `.txt` document, say). It cannot by itself keep a statement's conditions,
  ranges and qualifiers in its quote: the bot keeps them, by never cutting a statement where
  the rule cannot see it and by quoting a refused statement with its neighbours, verbatim (the
  list below names both kinds of case).
- A quote's attribution names its document by `DOC_ID`. In a call, the transcript names each
  turn's speaker and role, and a quote also names its turn as the turn's heading writes it,
  `{Speaker} ({role})`, and lies within that turn's words, below its heading (never across two
  turns or in a heading). Any turn may be quoted, an analyst's question included; a sentence a
  question repeats before an executive says it is found first in the question, so it is
  attributed to the question's turn. A quote of a filing or an exhibit names no speaker.
- An observation states facts only: the figures, names, counts and dates the comparison rests
  on and the rule's outcome. It carries no valuation, forecast or advice wording
  (`readings.WORDING`); quotes are the issuer's words and are never checked against that rule.

Applied to every document, these rules follow:

1. **Evidence.** Quote the statements an observation rests on; a `red` level quotes at least
   one from a document of the season itself.
2. **Whole statements.** Copy every quote from the derived text of its own document; adjacent
   sentences or lines may form one quote. `check` refuses these whole statements rather than
   risk a cut, so quote each with its neighbour, verbatim:
   - in a `.txt` document, a sentence after a heading or page header without punctuation with
     that heading, one that a page header interrupts with the header inside it, and a table
     row or bullet without a full stop through the next sentence end;
   - a bullet with its glyph (`▪`, `•`); a list item that starts in lowercase or is lettered
     (`▪we received …;`, `(a) the issuance of …;`, `(iv)`) with its lead-in and every other
     item;
   - a sentence that starts in lowercase (a brand such as "iPhone") with the one before; a
     sentence or HTML line followed by one that starts in lowercase (`x86 Architecture`) with
     it; two sentences joined by a footnote digit after the full stop (`website.1 We …`)
     together, with the digit;
   - a clause before an inline colon with what follows ("Excluding X: we expect …" is quoted
     from "Excluding").
3. **Never cut a statement here.** The rule sees characters, not grammar, so these cuts pass
   `check` and are still distortions:
   - at an abbreviation's full stop before a capital, a digit or an opening mark
     (`U.S. Government`, `2 p.m. PT`, `2025 vs. 2024`, `15 U.S.C. 7262`, `N.V. (NXP)`, `Inc.`),
     whether ending a quote or starting one;
   - where a line break splits an HTML sentence before a capital letter, such as between a
     lead-in ending in `;`, `; and` or `,` and its capitalised items;
   - in a `.txt` document, after a colon inside a sentence that happens to end a line;
   - between a lead-in and a lowercase item after a dash or an asterisk;
   - before a statement's conditions, ranges or qualifiers ("assuming …", "excluding …", "on a
     non-GAAP basis"), which stay inside its quote.
4. **Length.** Quote a statement shorter than 20 characters (a short table row, say) with the
   line or sentence right before or after it. Leave out a statement that is whole only in more
   than 800 characters (a long sentence, a lowercase list with its lead-in): the observation
   names its document and gives its figures. A quote is given once per item.
5. **Turns.** Give a call's quote the turn its first occurrence lies in, as the heading writes
   it.

## Derived text, figures and measures

Derived text is one deterministic function of a document's raw bytes (`text.py`,
`earningscalls.call_text`): the visible text of an HTML or iXBRL filing or exhibit, the
line-normalised text of a `.txt` filing or exhibit, one line `{name}: {text}` per element
holding text of an XML document (a schedule EDGAR renders from XML), the name without its
namespace, or a call's transcript laid out per turn, in order, as a heading line
`{speaker_name} ({speaker_type})` and then the turn's text, whose `\r\n` paragraph breaks
become line breaks, each line normalised as plain text. `derive` writes it as
`formatted/{T}/{PERIOD}/{DOC_ID}.md`, with no markup added, for the bot to read and quote; it
is derived again from `raw/` on every read, so a text file that differs from its derivation,
or cannot be read, is reported and rewritten by `derive`, and `check` passes a reading only
against text files equal to the derivation. A quote is located in the text case-sensitively,
whitespace runs matching any whitespace, smart quotes and dashes matching only themselves. The
sentence rule is a rule over located quotes, not part of the derivation: it changes no derived
text.

The derived-text rules are module code and constants in `text.py` and `earningscalls.py`: the
HTML, plain-text and XML derivations, the character clean-up and the layout of a call. A
change of them, or a Python release whose standard library changes `html.parser` or the
Unicode database, makes every affected text file differ from its derivation: `plan` says
`derive`, and `check` fails each reading that names such a document until `derive` has
rewritten its text file, then names each quote the new text no longer holds. The quote rules
(`text.sentence_bounded`, the turn, wording and length rules in `readings.py`) are applied by
every `check`: tightening one fails every reading that breaks it, and `plan` says `research`
until the readings are fixed.

**Figures.** The Python items read EDGAR's XBRL company facts (`facts.py`), one file per
company holding every fact EDGAR extracted from its filings. Every figure of a season comes
from that season's own 10-K or 10-Q (its accession), as the filing first reported it; EDGAR's
`frame`, which marks the value it deems latest for a calendar period, is never used. Per
measure, the first concept of its list the filing reports is read:

| Measure | Concepts, in order |
| --- | --- |
| revenue | `Revenues`, `RevenueFromContractWithCustomerExcludingAssessedTax`, `SalesRevenueNet` |
| cost of revenue | `CostOfRevenue`, `CostOfGoodsAndServicesSold` |
| gross profit | `GrossProfit`, else revenue less cost of revenue |
| operating income | `OperatingIncomeLoss` |
| net income | `NetIncomeLoss`, `ProfitLoss` |
| operating cash flow | `NetCashProvidedByUsedInOperatingActivities` |
| receivables | `AccountsReceivableNetCurrent`, `ReceivablesNetCurrent` |
| inventory | `InventoryNet` |
| payables | `AccountsPayableCurrent`, `AccountsPayableTradeCurrent` |
| debt | `LongTermDebtNoncurrent` plus `DebtCurrent`, else plus `LongTermDebtCurrent`, `ShortTermBorrowings` and `CommercialPaper`; an absent part counts 0, and none reported, or a part with two values, leaves no figure |
| cash | `CashAndCashEquivalentsAtCarryingValue` |
| weighted diluted shares | `WeightedAverageNumberOfDilutedSharesOutstanding` |
| goodwill | `Goodwill` |
| stockholders' equity | `StockholdersEquity` |
| total assets | `Assets` |
| diluted earnings per share | `EarningsPerShareDiluted` |

A balance is the entry at the season's period end. A flow is the quarter's entry (ending at
the period end, 80 to 100 days long); else, when the previous listed season ends 80 to 100
days before, in a 10-Q the year to date (101 to 290 days) less the previous season's own year
to date from the same start (operating cash flow is reported for the year to date alone), and
in a 10-K the year (350 to 380 days) less the third quarter's nine months from the same start;
when the previous listed season ends otherwise (a quarter missing from the listing), the
difference is no quarter and the figure has no value. Diluted earnings per share and the
weighted diluted shares are not additive and are read for the quarter only, so a 10-K season
has neither. Two distinct values of one concept, filing and span make the figure ambiguous: it
has no value, and every figure without one says why. A season's quarter days are the days
from the previous listed season's end to its own; its year-ago season is the listed season of
the same form ending 350 to 380 days before. Each value is computed exactly and rounded
half-even once (percentages and percentage points to two places, days to one; basis points
from the rounded margins), and each rule compares the rounded values, so the file lets anyone
redo it.

**`measures.md`** is the season's mechanical comparison, `formatted/{T}/{PERIOD}/measures.md`,
a pure function of `raw/` and the code (`measures.py`), with no time of its own: a
season's measures are fresh while equal to what `derive` would write now. Under the title
`# {T} · {PERIOD} · measures` it holds the season's 10-K or 10-Q (accession, filing date,
acceptance time), its call's state and the company facts file it reads (`present`; `waiting`
while that file predates the filing; `absent` when a later file still lacks it); `## Baselines`,
each baseline of the catalogue with its seasons and their documents' `DOC_ID`s; `## Filings of
the season`, every filing Rule B places in it with its form, dates, acceptance time, accession,
items and documents (a listed-only form marked so); `## Figures`, every figure of the season
and of the seasons its Python items compare with: the measure, season, value, unit, concept,
accession, start, end and formula, or why there is none; `## Python items`, per item its
`baseline:`, `values:`, `rule:` and `level:` lines; and `## Inputs for the bot's items`: the
figures items 1.7, 2.9, 4.4, 4.7 and 6.4 compare with, the 8-Ks of the season by the items they
name (4.01 for 3.1, 4.02 for 3.4, 5.02 for 5.1 to 5.3, 3.02 and 1.01 for 6.3), the beneficial
owners' schedules with their filer's CIK prefix (5.4), the registrations (6.3) and the
amendments listed. Its fixed text states figures and comparisons and passes `readings.WORDING`.

## The readings

The bot's readings of a season are UTF-8 Markdown at `reports/{T}/{PERIOD}/readings.md`,
rewritten until `check` passes them (`readings.py`). Line by line:

- G1: the first non-blank line is `# {T} · {PERIOD} · readings`;
- G2: then one section per bot item of the catalogue, each once, in catalogue order, headed
  `## {id} {title}` as the catalogue writes it;
- G3: a section's first three lines are `baseline:`, `level:` and `observation:`, in that
  order;
- G4: `baseline:` is `none` or the `DOC_ID`s of the documents read as the baseline, joined by
  `; `;
- G5: `level:` is `red`, `yellow`, `grey`, `none` or a status (`no baseline`,
  `not applicable`, `not disclosed`, `unavailable`, `not computable`);
- G6: `observation:` is 1 to 600 printable characters on its one line;
- G7: then zero or more quotes, each a run of `> TEXT` lines, whose texts are joined by one
  space (so wrap a long quote at any space), followed by one attribution line, `— {DOC_ID}`,
  or `— {DOC_ID}, {Speaker} ({role})` for a call's quote; blank lines may separate quotes.

Any other line is an error; trailing spaces, CRLF line ends and a leading byte order mark are
accepted. `check` then holds each section to these rules:

- R1: every `DOC_ID` named is a document of a listed season in `raw/` whose text file equals
  its derivation;
- R2: the baseline names documents of the item's baseline seasons only, and at least one for a
  level of an item that has a baseline; it is `none` for an item without a baseline and for
  the statuses `no baseline`, `not applicable` and `unavailable`;
- R3: a quote comes from a document of the season or from one its baseline line names;
- R4: `red` needs a quote from a document of the season itself;
- R5: `no baseline` only while no document of the item's baseline seasons is in `raw/` (the
  message names those that are);
- R6: `not applicable` exactly for an annual item in a 10-Q season and a proxy item in a season
  without a proxy statement;
- R7: `unavailable` exactly for a call item while the season's call is not `transcript`;
- R8: `not disclosed` and `not computable` only where the item allows them;
- R9: a quote keeps the quote rules (Quotes): 20 to 800 characters once normalised, found
  verbatim and spelt as the derived text writes it, whole sentences or lines at its first
  occurrence; a call's quote names its turn's heading exactly and lies within that turn; a
  quote of another document names no speaker;
- R10: an observation carries no valuation, forecast or advice wording, and no quote is given
  twice in one item.

Two sections of Intel's readings of the season ended 2026-06-27, whose 10-Q renames a
segment the previous quarter's 10-Q lists as `▪Client Computing Group (CCG)`:

```markdown
## 2.8 Segments merged, split or renamed
baseline: 10-Q_2026-03-28_0000050863-26-000079_intc-20260328
level: yellow
observation: The 10-Q names the Client Computing Group (CCG) of the previous 10-Q the Client Computing and Physical AI Group (CCPG); DCAI, Intel Foundry and All Other keep their names.
> ▪Client Computing and Physical AI Group (CCPG), formerly the Client Computing Group (CCG)
— 10-Q_2026-06-27_0000050863-26-000157_intc-20260627

## 3.3 Going concern
baseline: 10-Q_2026-03-28_0000050863-26-000079_intc-20260328
level: none
observation: Neither 10-Q states a substantial doubt about the ability to continue as a going concern.
```

## The season report and `show`

`render` writes, for every listed season whose readings pass `check`, whose texts and measures
are fresh and whose newest report is not the report rendered now, a new report
`reports/{T}/{PERIOD}/report_{TOKEN}.md`, and never overwrites one (`report.py`). Under the
title `# {T} · {PERIOD} · season report` and its `Generated` line, it names the issuer (its
EDGAR name and CIK), the season (its 10-K or 10-Q, accession and filing date), the call's
state and the seasons of its main baselines; then the score line, `Score: N (r red, y yellow,
g grey) over 69 items: 16 read by Python, 51 by the bot, 2 without a source;` with the count
of each status; then `## Triggered`, every item at `red`, then `yellow`, then `grey`, in
catalogue order within each level, each with its baseline, its values or observation, its rule
and its quotes with their attributions (`None of the items triggered.` when none did); then
the nine sections, each a table of its items with the level, who read it, the baseline and
the values or observation. A report is a pure function of the season's files, its measures
and its readings, but for its `Generated` line: the newest report is fresh while it equals the
report rendered now apart from that line (the shared rule), and a new transcript, a changed
measure or a rewritten reading makes it stale.

`show` prints, per ticker (by default those of the watchlist), the action `plan` gives over
the default window and the newest season whose report can be rendered now, its newest
report's path and freshness, and that report rendered now (or why none can be); then
`## Ranking`, one row per ticker shown: its season, score, red, yellow and grey counts and
report, the highest score first. The ranking orders counts of triggered comparisons; it ranks
no company.

## Freshness, missing data and what is never added

- A pending filing or call is listed by `fetch` and `plan` and may later join a season already
  read, whose new documents then change its measures and need its readings checked again. A
  call the provider never lists leaves its season `unavailable` once the list says so, 7 days
  after the season's due date; a call it lists later turns the season back to `transcript`.
- The company facts are requested on every `fetch` and written when their bytes changed. A
  window season whose filing they lack is `waiting` while the newest file was fetched on or
  before that filing's date (the figures come with a later `fetch`, which makes the measures
  stale) and `absent` once a file fetched after that date still lacks it (its figures stay not
  computable). Neither blocks the season.
- Every raw file is validated on every read; an invalid one, a *moved* filing or transcript
  included, is listed and blocks `derive`, `check` and `render` until it is withdrawn by
  renaming it `.rejected`, after which `fetch` writes it again where it belongs. The folders
  `raw/{T}/edgar/` and `raw/{T}/calls/` hold the former layout (until 2026-10-23): never read,
  they make `plan` say `fetch` until each is renamed `.rejected`, and `fetch` then writes the
  window again in seasons. The former layout's derived texts and reports, files directly in
  `formatted/{T}/` and `reports/{T}/`, are listed as `stray_files` and `stray_reports`: a stray
  text file is rebuilt by no command and may be deleted; a stray report is left as it is.
- A tightened quote rule fails every reading that breaks it, and `plan` says `research` until
  the readings are rewritten; a changed derivation makes the text files differ, `plan` says
  `derive`, and `check` then names each quote the new text no longer holds. Validation is never
  weakened, and no text file is changed to make a quote match.
- Nothing is paraphrased, summarised, translated, trimmed, merged, completed or inferred;
  nothing comes from memory, the web or another document; and the report back points to the
  reports instead of restating them.

## Commands

Run from the repository root as
`uv run --locked python -m market_state_research.fundamentals.script COMMAND`, each taking
`--data-dir PATH` (default: this domain's `data/`, whatever the working directory):

| Command | Does |
| --- | --- |
| `fetch [TICKER ...] [--from DATE] [--to DATE] [--refresh] [--watchlist PATH]` | The one network command. Writes the span's filings from EDGAR into `raw/`, each document only while it is not there yet, and the company facts when they changed; then the ticker's calls list from EarningsCalls.dev when it is due, and the transcript of every call placed in a span season that is not in `raw/` yet. With `--refresh`, only when the user asks, it requests all of these again, whatever `raw/` holds, and rewrites nothing: each EDGAR document is compared with its stored file (`verified`, or `changed`: reported, never written), and a transcript whose bytes changed is written beside the stored one as `transcript_{ID}_{TOKEN}.json` (`refreshed`), the copy every later read takes. Reports `unsupported` tickers and calls, `truncated` windows, pending and skipped filings and `stopped` when the provider's request limit is reached. |
| `plan [TICKER ...] [--from DATE] [--to DATE] [--refresh] [--watchlist PATH]` | Read-only. Per ticker, the span's seasons with their filings, call, texts and company facts, and per window season its measures, readings and report; the calls list and whether it is due; pending, skipped and unlisted items, the former layout, the invalid and stray files; and the first action that applies: `fetch`, `derive`, `research`, `render` or `reuse`; with `--refresh`, `fetch` while the window holds a listed season. |
| `derive TICKER` | Writes each document's derived text and each season's `measures.md` that is missing, unreadable or differs from its derivation. |
| `check TICKER [PATH ...]` | Read-only: checks every season's readings (or the drafts named, each in its season's folder) and prints each problem. |
| `render TICKER` | Writes the report of every season whose readings pass and whose newest report is not current. |
| `show [TICKER ...] [--watchlist PATH]` | Read-only: per ticker the action, the newest season report rendered now, then the ranking. |

The bot writes only the readings, which it may rewrite until `check` passes them and again
after a rule changes, and withdraws a raw file with `.rejected`; Python writes everything
else. A command that succeeds exits 0 and prints JSON (`show`: Markdown), also with work left
to do and when the provider's limit stopped `fetch`; a refusal exits 2 with one
`FUNDAMENTALS: ...` line on standard error. PROCEDURE.md gives each field, each message and
the step that follows it.

## Sources

Python reads two sources, both from `fetch` and only from it, each under its own setting from
the process environment or the ignored repository-root `.env` through `common.env`; no other
command reads either, and neither is ever written to `data/` or a tracked file or printed
(`fetch` prints `"user_agent": "set"` and `"api_key": "set"`). Both are checked after the
window and the data directory and before the watchlist and the first request. Nothing else is
evidence: no news, data vendor, consensus, company product page, investor-relations
presentation, search result or other transcript.

- **SEC EDGAR** is a public, read-only API that needs no account, sign-in or key and publishes
  a fair-access policy, which the client (`client.py`) follows exactly for every request (the
  ticker map, the submissions JSON, the company facts, the filings' documents, the filing
  index pages and the Form 4s' XML alike): every request names in `User-Agent` whom it is made
  for (`SEC_USER_AGENT`, a name and an email address the user gives), requests are paced 0.2 s
  apart (half EDGAR's ten a second), only `https://www.sec.gov` and `https://data.sec.gov` are
  contacted, no redirect is followed (a document is kept only as served from the URL
  requested), no compressed body is accepted, every body has a size limit (20 MiB for the
  submissions JSON and for an index page, 64 MiB for the company facts, 50 MiB for a document)
  and a body shorter than its `Content-Length` is refused as cut short, so a truncated document
  is never written. A season takes 20 to 40 requests (its Form 4s are most of them), so a
  ticker's default window with the four seasons before it takes about 300 the first time and a
  few a day after.
- **EarningsCalls.dev** serves the transcripts of issuers' earnings calls with each turn's
  speaker and role, under the user's own key (`EARNINGSCALLS_API`, a Pro plan: full
  transcripts and speaker segments, 3,000 requests a month, 20 a minute). Many issuers, Intel
  among them, publish no transcript of their call; the provider's transcript, kept verbatim,
  with each speaker's role and the call's duration, is what the call items read and quote. The
  client (`earningscalls.py`) contacts only `https://earningscalls.dev`, sends the key only in
  the `X-API-Key` header, paces its requests 3.1 s apart (under 20 a minute), follows no
  redirect, accepts no compressed body, bounds every body (8 MiB) and refuses one cut short.
  HTTP 429, the request limit, stops every later request to the provider in the run, which goes
  on with EDGAR alone, and `fetch` exits 0 with `stopped` naming the line (the provider's own
  message is repeated, escaped, cut and with the key removed, since it says when the limit
  resets); every other failure is one line.

A failed request, or a body that does not read (an index page `filings.parse_filing_index`
refuses, a Form 4 `form4.parse_form4` refuses, company facts `facts.read_companyfacts` refuses,
a calls page or a transcript that breaks the provider's subset below), aborts the run with one
line: nothing of that document is written, the files written before it stay, and a run again
requests nothing that is already in `raw/` but the ticker map, each ticker's submissions JSON
and company facts (written only when their bytes changed) and the calls list when it is due;
only `--refresh` requests the span's documents, transcripts and calls list again (Commands).

## Module boundaries

The domain's files and the package `market_state_research.fundamentals.script`, through which a
hypothesis script reads this domain's `raw/` ([explore_hypothesis/AGENTS.md](../../explore_hypothesis/AGENTS.md)):

| Path | Responsibility |
| --- | --- |
| `AGENTS.md` | This file: the domain's aim, model, items, rules and outputs, then its sources, architecture and formats. |
| `PROCEDURE.md` | The bot's workflow: settings and parameters, `fetch`, `plan`, `derive` and reading the documents, writing and checking readings, `render`, `show`, failures, the former layout. |
| `script/__main__.py` | Command line: `fetch`, `plan`, `derive`, `check`, `render`, `show`; `LABEL = "FUNDAMENTALS"`, `FundamentalsParser` and `DATA_DIRECTORY`; `fetch`, `plan` and `show` default to the tickers of this domain's `watchlist.json` (`workflow.WATCHLIST`; `--watchlist PATH`); `fetch` and `plan` print the file they read (`watchlist`) and take `--refresh` and the window (`--from`, `--to`), which `main` resolves from the New York date and checks before the data directory, the settings or any request; builds the EDGAR client from `SEC_USER_AGENT` and the EarningsCalls.dev client from `EARNINGSCALLS_API` (`CALLS_SETTING`) for `fetch` only, before the watchlist is read; ASCII-only JSON output, `show`'s Markdown; exit codes. |
| `script/workflow.py` | The commands over `raw/`, `formatted/` and `reports/`: `fetch` (the CIK, the submissions JSON, then for each span season, oldest first, its 10-K or 10-Q and each filing Rule B places in it, then the company facts, the calls list when due and the transcripts; `--refresh`; `unsupported`, `truncated`, pending and skipped filings, `stopped`), `plan` (each season's state and the next action), `derive`, `check`, `render` and `show` with its ranking. |
| `script/client.py` | EDGAR over HTTPS: URL builders (`submissions_url`, `companyfacts_url`, `archive_url`, `index_url`), `User-Agent` check, pacing, status, encoding and size rules (`JSON_LIMIT`, `COMPANYFACTS_LIMIT`, `DOCUMENT_LIMIT`, `INDEX_LIMIT`), the refusal of a body cut short of its `Content-Length`, no redirect followed, `EdgarError`; `decode_document` (strict UTF-8, else Latin-1); the HTTP reading `earningscalls` shares. |
| `script/earningscalls.py` | EarningsCalls.dev over HTTPS: the key check (`check_api_key`, `API_KEY_SETTING`), `HOST` only (`allowed_url`), pacing, status, encoding and size rules (`BODY_LIMIT`), no redirect followed, `EarningsCallsError` and `LimitReached` (HTTP 429); `EarningsCallsClient` (`events_page`, `transcript`); the strict reading of a calls page (`parse_events_page`), of a capture (`check_capture`, `check_issuer`, `Ambiguous`) and of a transcript against its listed call (`parse_transcript`, with its optional `duration_seconds`); a call's derived text and turns (`call_text`, `CallText`, `Turn` with its `heading`). |
| `script/filings.py` | Pure: the strict reading of `company_tickers.json`, of the submissions JSON's `filings.recent` (`RECENT_COLUMNS`, `items` and `acceptanceDateTime` included) and of an 8-K's filing index page (`parse_filing_index`); the forms read (`FETCHED_FORMS`, `LISTED_FORMS`, `NOTICES`, `REGISTRATIONS`, `AMENDMENTS`, `HOLDER_FORMS`, `DATED_BY_REPORT`, `FORM_TOKENS`, `rendered_document`); the window (`Window`, `default_window`); the seasons and their filings by Rule B (`select_seasons` → `Seasons` of `Season` and `Dated`, the pending and `Skipped` filings, `truncated`; `NoPeriodicFilings`), and Rule B for any dated item (`rule_b`, `Seasons.place`, `PENDING`). |
| `script/facts.py` | Pure: the strict reading of EDGAR's company facts (`read_companyfacts` → `CompanyFacts`), a season's figures (`figure`, `Figure`, `MEASURES`, `TAGS`), its quarter days (`quarter_days`) and its year-ago season (`year_ago`). |
| `script/form4.py` | Pure: the strict reading of a Form 4's XML (`parse_form4` → `Form4`, `Owner`, `Transaction`) and the issuer's officers selling (`officers_selling`). |
| `script/documents.py` | One ticker's `raw/` tree read into its listed seasons and their documents (`season_documents` → `RawState` of `SeasonFiles` and `FilingFiles`), every raw file it reads validated and each invalid one, moved one or former-layout folder listed with its reason; the newest company facts (`RawState.facts_status`), the newest calls capture (`Capture`), each call placed by Rule B, each season's call (`CallState`: `transcript`, `missing`, `unavailable`, `waiting`; `due_date`, `CALL_WAIT`), the pending and unlisted calls, and when the list is due again (`RawState.events_due`); the names (`season_folder`, `filing_folder`, `doc_id`, `call_doc_id`, `calls_name`, `transcript_name`, `Document.text_name`), the sentence rule's mode (`layout_mode`) and each document's derived text (`derive_text`, `derive_call`). |
| `script/text.py` | Pure: derived text of HTML, plain text and XML (a Latin-1 filing or exhibit read as windows-1252; `xml_text`); `normalise` and `locate`; the rule `sentence_bounded` (sentence rule v2: `SENTENCE_ENDS`, `CLOSERS`, `OPENERS`, `BULLETS`; layout or block mode). |
| `script/items.py` | Pure data: the catalogue (`ITEMS`, `Item`, `BY_ID`, `BOT_ITEMS`, `PYTHON_ITEMS`), the sections (`SECTIONS`), baselines, levels and statuses, the score (`SCORES`, `score`) and `BASELINE_SEASONS`. |
| `script/measures.py` | Pure: the Python items of a season (`season_measures` → `Measures` of `Reading`; the thresholds as constants), the seasons each baseline names (`baseline_seasons`) and `measures.md` (`render_measures`). |
| `script/readings.py` | Pure: the readings grammar (`parse_readings`), the rules each reading keeps (`readings_problems`, R1 to R10, with `Source` and `Season` giving what they need) and the wording rule (`WORDING`). |
| `script/report.py` | Pure: the season report in Markdown (`render_report`, `entries`, `score_line`), its file names (`report_name`, `report_files`, `newest_report`), its freshness (`same_report`) and `show`'s ranking (`ranking`). |
| `data/` | Runtime files (below); ignored by Git except `data/.gitignore`. |

## Runtime files

All paths are relative to this domain and ignored by `data/.gitignore`. `{T}` is the ticker,
`{PERIOD}` a season's period end (`YYYY-MM-DD`).

| Path | Writer | Content |
| --- | --- | --- |
| `data/raw/{T}/submissions_{TOKEN}.json` | `fetch` | EDGAR's submissions JSON, written only when its bytes differ from the newest such file's. The newest one lists the seasons on every read; older ones are never read. |
| `data/raw/{T}/companyfacts_{TOKEN}.json` | `fetch` | EDGAR's XBRL company facts, written only when their bytes differ from the newest such file's; the newest one is read. |
| `data/raw/{T}/calls_{TOKEN}_{PAGE}.json` | `fetch` | One page of the ticker's earnings calls as EarningsCalls.dev served it, verbatim; the pages of one request share `TOKEN`, the New York time page 1 arrived, and every request writes its pages, so the newest capture's time is when the provider last showed its list. Only the newest capture is read. |
| `data/raw/{T}/{PERIOD}/{FORM}_{DATE}_{ACCESSION}/{DOCUMENT}` | `fetch` | A filing's documents as EDGAR served them, in the season Rule B placed it in: `FORM` the form without spaces or slashes (`10-K`, `10-Q`, `8-K`, `DEF14A`, `SC13GA`, `SCHEDULE13GA`, `4` ...), `DATE` the date the filing is placed by (the period end for the season's own 10-K or 10-Q), `DOCUMENT` the archive's file name (an XML one without EDGAR's `xsl…/` prefix): a 10-K's or 10-Q's primary document; an 8-K's index page `{ACCESSION}-index.htm`, primary document and EX-99 exhibits; a proxy statement's or schedule's primary document; a Form 4's XML. |
| `data/raw/{T}/{PERIOD}/transcript_{ID}.json`, `transcript_{ID}_{TOKEN}.json` | `fetch` | The transcript of the call `ID` placed in the season, as EarningsCalls.dev served it (`GET /transcripts/{ID}/components`), verbatim: `transcript_{ID}.json`, written once, then from `fetch --refresh` each copy whose bytes differ from the newest one's, named by the New York time it arrived. The newest copy is read (the one without a token is the oldest). A transcript of a call the newest capture does not list is unlisted: left out, never invalid. |
| `data/formatted/{T}/{PERIOD}/{DOC_ID}.md` | `derive` | A document's derived text, UTF-8, what the bot reads and quotes. Rewritten when its derivation differs or the file cannot be read. |
| `data/formatted/{T}/{PERIOD}/measures.md` | `derive` | The season's figures, Python items and inputs for the bot (Derived text, figures and measures). |
| `data/reports/{T}/{PERIOD}/readings.md` | the bot | The season's readings (The readings). |
| `data/reports/{T}/{PERIOD}/report_{TOKEN}.md` | `render` | The season report. |

`DOC_ID` names a document's text file and is how a reading cites it. An EDGAR document's is
its folder name, `_` and its file name without the extension
(`10-Q_2026-06-27_0000050863-26-000157_intc-20260627`,
`8-K_2026-07-23_0000050863-26-000155_q226earningsrelease`); a call's is `call_{PERIOD}_{ID}`
(`call_2026-06-27_248001`). An index page, a Form 4's XML, the company facts and a calls list
have no `DOC_ID`. Two documents whose `DOC_ID`s collide, letter case aside, make the later one
invalid. A file or folder of `raw/{T}/` or of a season folder named otherwise than the forms
above is invalid, but for a name ending in `.rejected`, a season folder older than the oldest
listed season, a filing folder or transcript the newest listing does not hold (unlisted) and
the former layout's `edgar/` and `calls/`. `{TOKEN}` is the New York time of the command that
wrote the file, to the second, with its zone (`20261008T025725EDT`); a name whose token is
after the command's clock is ignored.

## Formats verified live

- EDGAR's bodies are read as a strict subset of their documented or verified layout:
  `company_tickers.json`, the submissions JSON's `filings.recent` (`filings.RECENT_COLUMNS`),
  the filing index page, a Form 4's XML and the company facts. Every value read must have its
  type and grammar, other keys or elements are ignored, and repeated keys, `NaN`, `Infinity`
  and XML document type or entity declarations are refused. When EDGAR changes a field or a
  layout, `fetch` fails loudly with one line naming the field or element and the rule, never a
  value read, and writes nothing of that body; a body in `raw/` is read again on every read, so
  a reader change that refuses it makes it an invalid file, never silently.
- Intel's `filings.recent` on 2026-10-23 (1,000 rows, back to 2019-03): 617 Form `4`, 123
  `8-K` (items 9.01 ×96, 7.01 ×52, 5.02 ×43, 2.02 ×31, 8.01 ×25, 1.01 ×9, 5.07 ×8, 3.02 ×5,
  2.01 ×3, 2.05 ×3, 5.03 ×2), 23 `10-Q`, 7 `10-K`, 8 `DEF 14A`, 19 `DEFA14A`, 17 `SC 13G/A` and
  3 `SCHEDULE 13G/A` (EDGAR's newer spelling), 5 `SC 13G`, 4 `S-3ASR`, 18 `424B5`, 3 `8-K/A`
  and 3 `4/A`. Every row has `acceptanceDateTime`, a UTC time written
  `YYYY-MM-DDTHH:MM:SS.000Z` (the Item 2.02 8-K of 2026-07-23 was accepted at
  `2026-07-23T20:09:00.000Z`, 16:09 New York time); a filing accepted after 17:30 New York time
  carries the next business day's `filingDate` (the 10-Q accepted at
  `2026-07-23T22:44:23.000Z` was filed 2026-07-24). A `DEF 14A`'s `reportDate` is its meeting's
  date (2026-05-13 for the proxy statement filed 2026-03-23). Intel's own `SC 13G/A`s of 2024
  report it as a holder of other issuers' shares (Mobileye, Joby, MariaDB): a schedule's
  subject is read from the schedule itself.
- A Form 4's `primaryDocument` is EDGAR's rendering of an XML file in the filing's folder
  (`xslF345X05/form4.xml`, `xslF345X06/form4.xml`, `xslF345X03/…`; other filers' agents name
  theirs `wk-form4_….xml` or `doc4.xml`); the raw XML is the same name without the prefix
  (`…/000005086326000177/form4.xml`: 200, `text/xml`, 4,402 bytes, schema `X0609`, with
  `reportingOwner/reportingOwnerRelationship/{isDirector,isOfficer,officerTitle}` and
  `nonDerivativeTable/nonDerivativeTransaction/{transactionDate,transactionCoding/transactionCode,
  transactionAmounts/{transactionShares,transactionPricePerShare,transactionAcquiredDisposedCode}/value}`).
  A `SCHEDULE 13G/A`'s primary document is likewise `xslSCHEDULE_13G_X02/primary_doc.xml`,
  read as XML text; an `SC 13G/A`'s is HTML or text.
- `https://data.sec.gov/api/xbrl/companyfacts/CIK0000050863.json` answered 200 with 4,311,809
  bytes: `cik`, `entityName` and `facts` (`dei`, `invest`, `us-gaap`, `ffd`; 684 `us-gaap`
  concepts), each concept's `units` mapping a unit to entries `{start?, end, val, accn, fy, fp,
  form, filed, frame?}`. Intel reports `RevenueFromContractWithCustomerExcludingAssessedTax`
  (no `Revenues`), `CostOfGoodsAndServicesSold` (no `CostOfRevenue`), and `DebtCurrent`
  (commercial paper included) with `LongTermDebtNoncurrent`. A 10-Q (accession
  0000050863-26-000157) reports the quarter (2026-03-29 to 2026-06-27), the year to date and
  the prior year's comparative quarter and year to date; operating cash flow comes as the year
  to date alone (2025-12-28 to 2026-06-27). `frame` marks the value EDGAR deems latest for a
  calendar period (the comparative of the newest filing carries it), so figures are selected
  by the season's own accession and the entries' spans instead.
- An 8-K's filing index page, verified on Intel's 8-K 0000050863-26-000155: exactly one
  `<table class="tableFile" summary="Document Format Files">`, closed by its own `</table>`
  and holding no other table, whose first row's cells are Seq, Description, Document, Type and
  Size and whose other rows have five cells; an exhibit row's Document cell links only to its
  document in the filing's folder, directly or through EDGAR's `/ix?doc=` viewer, and its Type
  is `EX-99` alone or `EX-99.` and 1 to 16 letters, digits or dots. An 8-K's primary document
  with Item 5.02 is about 25 KB; Intel's proxy statement is 2.85 MB.
- EarningsCalls.dev, verified live on 2026-10-19 (OpenAPI at
  `https://earningscalls.dev/openapi.json`): `GET /api/v1/me` reports the key's tier and
  usage, and the headers `x-ratelimit-limit` and `x-ratelimit-remaining` count the month; every
  answer with status 200, 400 or 404 counts against the 3,000, 401, 403 and 429 do not. The
  archive holds about 256,000 transcripts of 12,900 companies from 2020-01-02 on, US names of
  the watchlist among them; coverage has gaps (Intel's list lacks its July 2025 call), and a
  symbol listed elsewhere resolves to that listing (ASML's calls are `ASML:NL`'s: none with
  `country=US`). Transcripts land within hours of a call.
  - `GET /api/v1/earnings/?ticker={T}&event_type=earnings&country=US&limit=100&sort=date_desc&page={N}`
    answers `{"data": [...], "pagination": {"page", "limit", "total", "total_pages"},
    "ambiguous": false, "issuer_count": 1}` (an empty list: `total` 0, `total_pages` 0,
    `issuer_count` 0). A row holds `id` (the call's stable id), `event_type`, `event_date_time`
    (UTC, `2026-07-23T21:00:00.000Z`), `stock_symbol` (`INTC`), `company_ticker` (`INTC:US`),
    `country`, `issuer_id` (32 hex digits, null on some legacy rows), `fiscal_year` and
    `fiscal_quarter` (read from the title, null when absent), `matched_alias` and descriptive
    keys (`company_name`, `transcript_title`, `sector`, `exchange`, `mic`, `isin`, `timezone`
    ...). Of these the subset read is `id`, `event_type` (`earnings`), `event_date_time`,
    `stock_symbol` (the ticker's own), `country` (`US`), `issuer_id` (one issuer across the
    capture), `fiscal_year`, `fiscal_quarter`, the pagination and `ambiguous` (false) with
    `issuer_count` (at most 1). A list that is `ambiguous` makes the ticker's calls
    `unsupported`, nothing written.
  - `GET /api/v1/transcripts/{id}/components` answers `{"data": {"company_name",
    "transcript_title", "event_type", "duration_seconds", "header": {"title",
    "event_date_time", "announced_date", "duration", "created_at", ...}, "components":
    [...]}}`; each component is `{"order", "speaker_name", "speaker_type", "text"}`, in call
    order from 0, `speaker_type` one of `executive`, `analyst`, `operator`, `attendee`,
    `shareholder` and `unknown`, and paragraph breaks inside `text` are `\r\n`. The header
    writes the call's time without milliseconds (`2026-07-23T21:00:00Z`), the same instant the
    list gives. The subset read is `data.event_type` (`earnings`), `data.duration_seconds` (a
    whole number of seconds, when present), `data.header.title`, `data.header.event_date_time`
    (the listed call's instant) and every component's four keys. Intel's call of 2026-07-23
    (id 248001) has 61 turns; its executives are John Pitzer, Lip-Bu Tan and David Zinsner.
    `GET /api/v1/transcripts/{id}?format=full` (one string) and `GET /api/v1/speakers/{id}`
    (turns by 50) carry the same and are not used.

  A body that breaks the subset is refused with the field and the rule, never its text, and
  nothing is written; a page or transcript in `raw/` is validated again on every read, so a
  tightened rule makes it an invalid file.
