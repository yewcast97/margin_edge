# Fundamentals

This domain keeps, per stock issuer and per fiscal period in a window, the issuer's own
documents of the period verbatim, derives their text, records what each document says in
eleven fields of verbatim quotes, and compiles the complete periods into a time series.
Its default tickers are those of this domain's own watchlist. This file says first what
the work aims at, the model of periods, releases and calls, the eleven fields, the rules a
quote keeps, the report grammar, what the series holds and the commands; then the sources
and why Python may read them, the module boundaries, the runtime files and the formats
verified live. The operations the bot carries out (settings, `fetch`, `plan`, reading,
writing and checking reports, `render`, `show`, failures) are in the sibling
[PROCEDURE.md](PROCEDURE.md); the conventions every domain shares (the domain layout, the
three sections of `data/`, New York time, the API rule) are in
[market_state_research/AGENTS.md](../AGENTS.md). This domain reads no market data, so it
has no session logic, and its documents are dated by their own dates.

## Aim

For each issuer, a record of what it disclosed, period by period, with every original
document kept: the filings and earnings releases as the regulator's archive serves them,
each earnings call's transcript as the transcript provider serves it, one report per
document in eleven fields of quotes copied verbatim from the document's derived text, and
a time series compiled from the complete periods. No valuation, forecast, rating, ranking
or advice is added by the reports, the series or the bot; the analyst reads the issuer's
words.

## Periods, releases and calls

- A period is one exact `10-K` or `10-Q` of EDGAR's `filings.recent`, named by its
  `reportDate`, the fiscal year or quarter end it reports. Amendments and transition
  reports (`10-K/A`, `10-KT`, `10-Q/A`, `10-QT`, `NT 10-Q` ...) are not periods. Two
  filings that report one period, no exact 10-K or 10-Q at all (a 20-F filer, say) and
  an Item 2.02 8-K without an event date, or dated after its filing date, make the
  ticker `unsupported` with the reason instead of one reading being chosen.
- An earnings release is an exact `8-K` whose `items` name Item 2.02, dated by its
  `reportDate`, the date of the event it reports. Rule B takes, for a release dated D,
  the latest listed period end P before D: when a later period is listed, the release
  belongs to P; when P is the newest listed period, the release belongs to P only when D
  is not after the filing date of P's own 10-K or 10-Q, and is otherwise pending: a
  release dated after the newest period's 10-K or 10-Q was filed. Once EDGAR lists a
  later period, Rule B places it again: it joins the latest period ending before D,
  which is P itself when the later period ends on or after D (a release furnished after
  P's 10-Q, a mid-quarter update), or stays pending when that is the new newest period
  and D is after its filing date. A pending release so concerns the newest listed period
  or a later one: `fetch` and `plan` list every pending release as `pending_releases`
  when the window ends on or after the newest listed period end, and none when it ends
  before it; the release's own date does not bound the listing. A release dated on or
  before the oldest listed period end is dropped, and `8-K/A` amendments and 8-Ks
  without Item 2.02 are neither attached nor pending. A period may have several releases
  (a preliminary-results 8-K, say), ordered by report date, filing date and accession.
  Rule B uses EDGAR's own dates only: an issuer that furnishes its release after its
  10-Q stays visibly pending until its next period is listed.
- An earnings call is a call the transcript provider, EarningsCalls.dev, lists for the
  ticker as an `earnings` event, dated by the New York date of its `event_date_time`.
  Rule B places it as it places a release: in the latest listed period ending before
  its date, pending while it is dated after the newest period's 10-K or 10-Q was filed
  (`pending_calls`, listed under the same window rule as pending releases), dropped when
  dated on or before the oldest listed period end. A period's call is the transcript of
  every call placed in it, normally one: the annual report's period end is the
  fourth-quarter call, each quarterly report's its quarter's call.
- A period's call is in one of four states, from the provider's newest list in `raw/`
  (each request of the list is kept, so the newest one says when the provider last
  showed it):
  - `transcript`: the list places one or more calls in the period, and each one's
    transcript is in `raw/`;
  - `missing`: there is no valid list in `raw/`, or a call placed in the period has no
    valid transcript in `raw/`; `fetch` acts on both;
  - `unavailable`: the list places no call in the period, and it was fetched 7 days or
    more after the period's *due date*: the report date of its latest release, else the
    filing date of its 10-K or 10-Q. The provider shows no transcript of the call: an
    observation dated by that list (`unavailable (provider lists no call as of DATE)`),
    never a judgment, and a later list that places a call in the period supersedes it;
  - `waiting`: the list places no call in the period yet and was fetched less than 7 days
    after its due date.

  A period is settled by `transcript` or `unavailable`; `waiting` and `missing` keep it
  incomplete. The list is asked for again (`plan` says `fetch`) when there is none, or
  while a window period's call is `waiting` or `unavailable` and the newest list is 7
  days old or more, or, for a `waiting` call, was fetched on or before the period's due
  date and that date has passed: a call lands within hours, a permanently missing one
  costs about four requests a month.
- The documents of a period are its 10-K or 10-Q primary document; for each release,
  every EX-99 exhibit that the 8-K's filing index page (`{accession}-index.htm`, the one
  EDGAR page that names each document's exhibit type) lists, in Seq order, except
  EDGAR's unofficial `.pdf` copies, whose official `.htm` or `.txt` is listed too (an
  EX-99 exhibit is a row whose Type is `EX-99` alone or `EX-99.` and a suffix, such as
  `EX-99.1`; any other Type that starts with `EX-99`, such as `EX-99-1` or `EX-99A`, is
  refused loudly rather than read or ignored, and a release without an EX-99 row has no
  exhibit); and each call's transcript. The index page and the calls list are kept in
  `raw/` so that a period's documents are read from `raw/` alone: they have no derived
  text and no report. Every document needs its own report.
- Nothing a read needs lives only in a file name: each EDGAR document's form,
  accession, dates and period come from the newest submissions file (Rule B included)
  on every read, an exhibit's type and Seq from its index page, parsed again on every
  read, and each call's id, date and period from the newest calls list, with the
  transcript read against the call it lists.
- The window is a pair of New York calendar dates, `--from` and `--to`, bounding the
  fiscal period ends, both included (`--to` defaults to today and may not be after it;
  `--from` defaults to the same day two years before `--to`). `fetch` writes, and `plan`
  weighs, only the window's periods, and `show` reports over the default window. Only
  `filings.recent` is read (EDGAR's latest year or 1,000 filings at least; the older
  pages under `filings.files` are not), so a window whose `--from` precedes the oldest
  filing date it lists is reported `truncated: true`: periods before that are not seen.
  As EDGAR's list moves on, a later submissions file may no longer list a period: every
  file and report of a period older than the oldest listed one is then left out, as if
  it were not in `raw/`, and blocks nothing. The other commands take no window: `text`
  and `check` work on every document of every listed period in `raw/`, and `render` and
  `show` cover every listed period whose 10-K or 10-Q is in `raw/`.

## The eleven fields

A statement is recorded in every field whose definition it fits. A financial statement
line item (a row of a balance sheet, income statement or cash-flow statement, of a table
in their notes or of an earnings release's statements and reconciliations: a caption with
its amounts) or a footnote to such a row is not a statement of any field unless the
field's definition admits it; the issuer's narrative about such a row may be. The
fields, in the order the reports keep them:

1. `upstream_shortage` (Upstream shortage): the issuer's statements on a shortage of
   what it buys: raw materials, components, purchased manufacturing capacity (foundry
   wafers, substrates, packaging, equipment) or services (outsourced production,
   assembly and test, logistics, energy): constraints, allocation, lead times,
   availability, sole or limited sources, purchases from competitors or other sources
   to cover a gap, supply reserved or locked up by others, the issuer's own long-term
   supply agreements, capacity reservations and prepayments to suppliers, input prices
   only where the statement ties them to such a shortage, and the easing or absence of
   any of these. A financial statement line item (property, plant and equipment, its
   additions or impairments, raw materials) is not one, nor is a footnote to such a
   row.
2. `capacity_shortfall` (Capacity shortfall): the issuer's statements on downstream
   demand and how it compares with the production capacity or output of the company or
   its industry: demand exceeding available supply, capacity limits on shipments,
   allocation of output among customers, lead times or delivery dates quoted to
   customers, demand the issuer reports from its customers or end markets (ahead of
   plan, above its guidance, beyond what it can serve), and the opposite (excess
   capacity, demand below output, customer or channel inventory corrections). The size
   and terms of backlog belong to `backlog_contracts`; backlog is cited here only
   where the statement uses it to compare supply with demand.
3. `capex_plans` (Capex plans): the issuer's statements of planned, expected, budgeted
   or targeted capital expenditure (amount, range, direction or timing), its stated
   purpose or allocation among uses, the stated cause of a change in it (equipment
   prices, capacity added, timing) and the return the issuer expects from it (return
   on invested capital, payback). A statement of spending already made is not one. The
   resulting capacity belongs to `capacity_expansion`.
4. `capacity_expansion` (Capacity expansion): the issuer's statements of planned or
   targeted changes to its own production, service or delivery capacity: the capacity
   to be added, reduced or reached (units, output, revenue capacity, sites, lines,
   headcount), its timing and milestones, utilisation targets, and delays,
   cancellations or accelerations of such plans. A statement of capacity already in
   place is one only where it compares that capacity with a stated target.
5. `earnings_guidance` (Earnings guidance): the issuer's statements of expected,
   forecast or targeted financial or operating results for a period not yet ended
   (revenue, gross margin, operating expenses, tax rate, earnings per share,
   non-controlling interest, cash flow, unit shipments and the like), with their
   stated conditions; multi-year and long-term targets; and any raise, cut,
   reaffirmation or withdrawal of prior guidance. A row of an outlook table, or of a
   reconciliation of outlook figures, is a statement of this field, quoted whole (the
   caption with its amounts, from its line or, where the derived text splits the row,
   its consecutive lines).
6. `pricing` (Pricing): the issuer's statements on the prices it charges: average
   selling prices, price increases or cuts, pricing at contract renewal, contract
   pricing terms, surcharges, discounts and rebates, and pricing power or pressure,
   with their stated amounts, timing and causes. Prices the issuer pays are not
   pricing: see `upstream_shortage` and `margin_drivers`.
7. `backlog_contracts` (Backlog and contracts): the issuer's statements on business
   its customers have contracted or committed: backlog, orders and bookings,
   book-to-bill, remaining performance obligations, deferred revenue or contract
   liabilities, long-term supply or purchase agreements with customers, framework
   agreements, capacity reservations by customers, design wins with a stated value,
   and their amounts, duration, conversion timing, renewals, cancellations, deferrals
   and pushouts. A row of a note's table of remaining performance obligations or
   contract liabilities is a statement of this field, quoted whole (as in field 5).
   The issuer's own commitments to its suppliers belong to `upstream_shortage`.
8. `product_ramp` (Product ramp): the issuer's statements on the commercial progress
   of new products, services, process technologies or sites: development milestones,
   sampling, customer qualification or certification, regulatory approvals,
   design-ins, the timing of pilot production, volume production or launch, yields,
   transitions between product generations, and delays or failures in any of these.
9. `margin_drivers` (Margin drivers): the issuer's statements explaining changes or
   expected changes in its gross, operating or net margins or in earnings per share:
   product or customer mix, pricing, input costs, yields, utilisation, scale, start-up
   costs, depreciation and amortisation policy (the useful lives of its assets and
   changes to them, which are statements of this field on their own) and items the
   issuer identifies as one-time, non-recurring or non-operating (gains, losses,
   settlements, impairments, restructuring), with their amounts. A financial statement
   line item is not one; the issuer's explanation of its effect on a margin or on
   earnings per share is.
10. `financing_methods` (Financing methods): the issuer's statements of how it funds
    or plans to fund its operations, investments and obligations, returns capital and
    changes its share count: cash from operations, debt (notes, term loans, commercial
    paper, credit facilities), equity (share or convertible issuances, at-the-market
    programs with the amounts sold and still available, government or strategic equity
    stakes), share-based compensation named as a source of dilution, partner or
    minority-interest capital in facilities, government grants, loans and incentives,
    customer prepayments, asset sales and leases, the repayment or refinancing of
    debt, share repurchases and dividends, with the amounts, terms and purposes
    stated. A statement of the cash balance alone, or a financial statement line item,
    is not one.
11. `customer_concentration` (Customer concentration): the issuer's statements on how
    concentrated its revenue, orders or receivables are among its customers: the share
    of revenue or receivables from its largest customers or from any customer above a
    stated threshold (named or anonymised), the number of customers making up a large
    share, dependence on a few customers, distributors or end markets, changes in that
    concentration, and the loss, cancellation, reduction or deferral of business from
    a customer the issuer calls major, significant or among its largest. A row of a
    note's customer table (a customer and its share) is a statement of this field,
    quoted whole (the customer with its shares, from its line or, where the derived
    text splits the row, its consecutive lines).

The definitions are stated here alone, and the bot alone applies them: no code does, so a
report written under an earlier definition keeps passing `check`. To apply a changed
definition, read the affected documents again and rewrite their reports, removing the
quotes the change excludes and adding those it admits; then `check` and `render`. The
fields' names, number and order are code: a change of them fails every report written
before it, and `plan` says `research` until each has been rewritten from its document under
the new fields.

## Quotes: the research rules

- Report facts, not ideas, and never distort a statement. Every quote is a verbatim span
  of its own document's derived text, spelt with the text's own characters (only the
  whitespace between words may differ, so a quote holds no soft hyphen, zero-width
  character or ligature the text does not). Nothing is paraphrased, summarised,
  translated, scored, rated, trimmed, merged, completed or inferred; the only choice the
  bot makes is which field a statement belongs to. Quotes are the issuer's own words:
  its filings and exhibits and, in a call, its executives' turns, never an analyst's
  question, an operator's line or words the document attributes to anyone outside the
  company. A field without a quote holds `None found.`: an observation of absence, not a
  judgment. A quote that is invented, reworded, filled in from memory, the web, another
  document or inference, or retyped from anywhere but the derived text is a failed run.
- A quote is whole sentences, or whole lines of an HTML document or a call transcript, so
  that no quote cuts a statement (`text.sentence_bounded`, sentence rule v2, checked at
  the quote's first occurrence in the derived text; its normalised length is 20 to 800
  characters). The rule reads a line break in one of two modes, chosen by the
  document's kind and name alone, never its contents (`documents.layout_mode`):
  - *layout* mode, for a filing or exhibit whose document name ends in `.txt` (any case):
    a line break is ordinary whitespace. These lines wrap where the page ran out, as
    often inside a sentence as at its end, so they carry no structure and a quote runs
    from a sentence start to a sentence end across them; a whole line is not a statement;
  - *block* mode, for HTML and iXBRL filings and exhibits and a call's transcript: a line
    break ends a block, and a whole line (a table row, a bullet, a heading, a paragraph
    of a speaker's turn) is a quote of its own unless the next line starts in lowercase
    and so continues it.

  In both modes a quote never starts in lowercase, whatever opening marks and list
  markers come first (`text.BULLETS`: "▪", "•" and the other glyphs issuers set before
  an item, with the spaces and line breaks after them; dashes and asterisks are not
  among them): such a start continues a sentence, as "market" after "U.S." does, or a
  lead-in, as the item "▪we received …;" does. It starts at the text's start, at a
  block's start (block mode), or after a sentence end (`.`, `!`, `?` or `…`, closing
  marks allowed after it) and whitespace. It starts after a colon only where the colon
  ends a line (a heading) or, in a call only, where the colon is that of the quote's own
  speaker label ("Chief Executive Officer: Thank you."): the whole text of the colon's
  line before it is exactly the quote's speaker, and that line itself starts where a
  quote may. Any other colon is inside its sentence, so "Excluding the divestiture: we
  expect …" can be quoted only from "Excluding". A quote ends at the text's end, at a
  block's end (block mode) before a line that does not start in lowercase, or with a
  sentence end followed by whitespace and text that does not start in lowercase (opening
  marks and list markers before it skipped), so "U.S." before "market", "$8." cut from
  "$8.0" (the next character is "0") and a lead-in before a lowercase item end no quote;
  neither does a quote that starts after `said that “` or ends with `“Project Alpha”`
  where the sentence goes on. A quote may omit the opening and closing marks around it,
  never a list marker it starts after: a bullet is quoted with its glyph.

  The rule sees characters, not grammar, and refuses only the cuts it can see: some
  cuts pass it (an abbreviation's full stop before a capital reads as a sentence end,
  say), and it refuses some whole statements rather than risk a cut (a sentence after a
  heading without punctuation in a `.txt` document, say). It cannot by itself keep a
  statement's conditions, ranges and qualifiers in its quote: the bot keeps them, by
  never cutting a statement where the rule cannot see it and by quoting a refused
  statement with its neighbours, verbatim (the research rules below list both kinds of
  case).
- A quote's speaker names who says it, copied exactly as the derived text of the quote's
  own document writes the name before the quote (only the whitespace between its words
  may differ, where a line break splits the name); its first occurrence in that document
  must start before the quote does. In a filing or an exhibit the rule does not check
  that the name introduces the quote, and a name found only in another document of the
  period is not found; a quote whose document names no one for it has no speaker (a
  filing or an exhibit, as a rule). A name spelt otherwise than the derived text shows it
  (a ligature the text writes as letters, say) is refused.
- In a call, the transcript names each turn's speaker and role, and `check` holds every
  quote to them (`research.Turn`): the quote has a `Speaker:` line; it lies within the
  words of one turn, below its heading (never across two turns or in a heading); that
  turn's role is `executive`, the issuer's own executives as the provider marks them
  (never `analyst`, `operator`, `attendee`, `shareholder` or `unknown`); and its
  `Speaker:` line is exactly the name the turn's heading writes. A sentence an analyst's
  question repeats before an executive says it is found first in the question, where it
  can never be quoted.
- The reports and the series state what the issuer's filings, earnings releases and
  calls say and add no valuation, forecast, rating, ranking or investment opinion of
  their own (earnings guidance is the issuer's statement, quoted as it stands), and
  neither does the bot. The names the bot writes, the speakers, carry no valuation,
  forecast or advice wording (`research.WORDING`); quotes are the issuer's own words and
  are never checked against that rule.

Applied to every document, these rules follow:

1. **Fields.** Record every statement that passes a field's test (the eleven fields
   above) in that field.
2. **Whole statements.** Copy every quote from the derived text of the report's own
   document; adjacent sentences or lines may form one quote. `check` refuses these whole
   statements rather than risk a cut, so quote each with its neighbour, verbatim:
   - in a `.txt` document, a sentence after a heading or page header without punctuation
     with that heading, one that a page header interrupts with the header inside it, and
     a table row or bullet without a full stop through the next sentence end;
   - a bullet with its glyph (`▪`, `•`); a list item that starts in lowercase or is
     lettered (`▪we received …;`, `(a) the issuance of …;`, `(iv)`) with its lead-in and
     every other item;
   - a sentence that starts in lowercase (a brand such as "iPhone") with the one before;
     a sentence or HTML line followed by one that starts in lowercase
     (`x86 Architecture`) with it; two sentences joined by a footnote digit after the
     full stop (`website.1 We …`) together, with the digit;
   - a clause before an inline colon with what follows ("Excluding X: we expect …" is
     quoted from "Excluding").
3. **Never cut a statement here.** The rule sees characters, not grammar, so these cuts
   pass `check` and are still distortions:
   - at an abbreviation's full stop before a capital, a digit or an opening mark
     (`U.S. Government`, `2 p.m. PT`, `2025 vs. 2024`, `15 U.S.C. 7262`, `N.V. (NXP)`,
     `Inc.`), whether ending a quote or starting one;
   - where a line break splits an HTML sentence before a capital letter, such as between
     a lead-in ending in `;`, `; and` or `,` and its capitalised items;
   - in a `.txt` document, after a colon inside a sentence that happens to end a line;
   - between a lead-in and a lowercase item after a dash or an asterisk;
   - at an inline colon whose clause is written as the speaker (item 5);
   - before a statement's conditions, ranges or qualifiers ("assuming …", "excluding …",
     "on a non-GAAP basis"), which stay inside its quote.
4. **Length.** Quote a statement shorter than 20 characters (a short table row, say) with
   the line or sentence right before or after it. Leave out a statement that is whole
   only in more than 800 characters (a long sentence, a lowercase list with its lead-in)
   and name it in the report back. A sentence repeated in one document is quoted once.
5. **Speaker.** In a call, give every quote the `Speaker:` line its turn's heading
   writes, and quote only turns whose heading names the role `executive`. In a filing or
   an exhibit, give a `Speaker:` line only when the document names the speaker before the
   quote (an executive an earnings release quotes by name), and name only the person the
   document shows speaking, never another name that happens to occur earlier.

## Derived text

Derived text is one deterministic function of a document's raw bytes (`text.py`,
`earningscalls.call_text`): the visible text of an HTML or iXBRL filing or exhibit, the
line-normalised text of a `.txt` filing or exhibit, or a call's transcript laid out per
turn, in order, as a heading line `{speaker_name} ({speaker_type})` and then the turn's
text, whose `\r\n` paragraph breaks become line breaks, each line normalised as plain
text. A filing index page and a calls list have none. `text` writes it as
`formatted/{T}/{DOC_ID}.md`, with no markup added, for the bot to read and quote; it is
derived again from `raw/` on every read, so a text file that differs from its
derivation, or cannot be read, is reported and rewritten by `text`, and `check` passes a
report only against a text file equal to the derivation. A quote is located in the text
case-sensitively, whitespace runs matching any whitespace, smart quotes and dashes
matching only themselves. A `.txt` document's lines are where the page wrapped (layout
mode); an HTML document's and a call's are its blocks (block mode). The sentence rule is a
research rule over located quotes, not part of the derivation: it changes no derived text.

The derived-text rules are module code and constants in `text.py` and
`earningscalls.py`: the HTML and plain-text derivations, the character clean-up and the
layout of a call. A change of them, or a Python release whose standard library changes
`html.parser` or the Unicode database, makes every affected text file differ from its
derivation: `plan` says `text`, and `check` fails each report until `text` has rewritten
its text file, then names each quote the new text no longer holds. The research rules
(`text.sentence_bounded`, the speaker, call and wording rules and the quote length and
spelling in `research.py`) are applied by every `check`: tightening one fails every report
that breaks it, and `plan` says `research` until the reports are fixed.

## The per-document report

A report is UTF-8 Markdown at the path `plan` gives for its document
(`reports/{T}/{DOC_ID}.md`), rewritten until `check` passes it. Line by line:

- the first non-blank line is `# {DOC_ID}`, the file's name without `.md`;
- then the eleven sections `## upstream_shortage`, `## capacity_shortfall`,
  `## capex_plans`, `## capacity_expansion`, `## earnings_guidance`, `## pricing`,
  `## backlog_contracts`, `## product_ramp`, `## margin_drivers`, `## financing_methods`
  and `## customer_concentration`, each once, in that order;
- a section holds either the one line `None found.` or quotes separated by blank lines;
- a quote is an optional `Speaker: NAME` line followed by consecutive `> TEXT` lines,
  whose texts are joined by one space, so wrap a long quote at any space;
- an empty `>` line, a `Speaker:` line without its `>` lines, two quotes without a blank
  line between them, or any other line is an error. Trailing spaces, CRLF line ends and
  a leading byte order mark are accepted.

An excerpt of the report of Intel's Q2 2026 earnings release, at most one quote per field:

```markdown
# 8-K_2026-07-23_0000050863-26-000155_q226earningsrelease

## upstream_shortage

None found.

## capacity_shortfall

> “We delivered a strong second quarter, exceeding our financial guidance on robust demand and
> improved execution, including volume upside driven by higher factory yields and improved cycle
> times,” said Dave Zinsner, Intel CFO.

## capex_plans

Speaker: Dave Zinsner
> AI-driven compute continues to strengthen, and to support expected growth this year and next across
> products and foundry, we are meaningfully increasing our investments in equipment, clean room space,
> and substrates.

## capacity_expansion

> ▪Intel announced a €5 billion investment to expand manufacturing capacity and increase production of
> Intel® Xeon® 6 and next-generation Intel® Xeon® processors built on Intel 3.

## earnings_guidance

> ▪Forecasting third-quarter 2026 revenue of $15.8 billion to $16.8 billion; expecting third-quarter
> EPS attributable to Intel of $0.31 and non-GAAP EPS attributable to Intel of $0.38.

## pricing

None found.

## backlog_contracts

None found.

## product_ramp

> ▪Intel Foundry advanced the Intel 18A family as Intel 18A-P entered risk production, meeting the
> timeline shared with customers and partners last year while extending the platform with enhanced
> performance, power, and thermal resistance.

## margin_drivers

> Q2 2026 charges represent the net change in fair value of both Escrowed Shares released during the
> quarter and Escrowed Shares still held in escrow at quarter end. We exclude these non-operating gains
> and losses for purposes of calculating certain non-GAAP measures to provide better comparability
> between periods.

## financing_methods

> In the second quarter, the company generated $7.0 billion in cash from operations.

## customer_concentration

None found.
```


## The time series and `show`

`render` writes `reports/{T}/{T}_{AS_OF}_{TOKEN}.md` from the reports of every
complete period, whatever the window, and never overwrites one. Under a title naming the
ticker and the as-of date, and the issuer's EDGAR name and CIK, it holds one section per
complete period, newest first: its documents (a call as its transcript's title, the date
it was held and its `DOC_ID`; a period whose call is unavailable says that the transcript
provider lists none, as of the list's date), then `### Upstream shortage`,
`### Capacity shortfall`, `### Capex plans`, `### Capacity expansion`,
`### Earnings guidance`, `### Pricing`, `### Backlog and contracts`, `### Product ramp`,
`### Margin drivers`, `### Financing methods` and `### Customer concentration`, each quote
as the report writes it (its words joined by one space) followed by its document's label
and speaker, and `None found in the period's documents.` for a field without a quote;
then a coverage table of every listed period whose 10-K or 10-Q is in `raw/`: its status,
`complete` (every EDGAR document in `raw/`, the call settled, every document's report
passing `check`), `incomplete` (naming what is missing: `documents not in raw/`,
`the earnings call's transcript is not in raw/`, `the earnings call is not listed yet`,
the `DOC_ID`s without a passing report) or `not researched` (no passing report); its
call, `transcript`, `unavailable (provider lists no call as of DATE)`, `waiting` or
`missing`; and its documents and quotes per field. `AS_OF` is the filing date of the
newest 10-K, 10-Q or EX-99 exhibit of the complete periods. `render` refuses while no
period is listed, a raw file is invalid, a report fails `check` or no period is complete.
`show` prints the action `plan` gives over the default window, a line each on the
periods, the reports and the series, a line per invalid file and per failing report, then
the series rendered now (or why none can be).

## Freshness, missing data and what is never added

- The newest series is fresh while it equals the series rendered now apart from its
  `Generated` line (the shared rule); `plan` says `reuse` then, or when no period is
  complete.
- A pending release or call is listed by `fetch` and `plan` and may later join a period
  already researched, whose new document then needs a report. A call the provider never
  lists leaves its period `unavailable` once the list says so, 7 days after the period's
  due date; a call it lists later turns the period back to `transcript`, with one more
  document to report.
- Every raw file is validated on every read; an invalid one is listed and blocks `text`,
  `check` and `render` until it is withdrawn by renaming it `.rejected`, after which
  `fetch` writes it again where it can. A tightened research rule fails every report that
  breaks it, and `plan` says `research` until the reports are rewritten; a changed
  derivation makes the text files differ, `plan` says `text`, and `check` then names each
  quote the new text no longer holds. Validation is never weakened, and no text file is
  changed to make a quote match.
- Nothing is paraphrased, summarised, translated, scored, rated, trimmed, merged,
  completed or inferred; nothing comes from memory, the web or another document; and the
  report back points to the series instead of restating the quotes.

## Commands

Run from the repository root as
`uv run --locked python -m market_state_research.fundamentals.script COMMAND`, each
taking `--data-dir PATH` (default: this domain's `data/`, whatever the working directory):

| Command | Does |
| --- | --- |
| `fetch [TICKER ...] [--from DATE] [--to DATE] [--refresh] [--watchlist PATH]` | The one network command. Writes the window's filings and releases from EDGAR into `raw/`, each only while it is not there yet; then the ticker's calls list from EarningsCalls.dev when it is due, and the transcript of every call placed in a window period (and every pending call, when the window reaches the newest period) that is not in `raw/` yet. With `--refresh`, only when the user asks, it requests all of these again, whatever `raw/` holds, and rewrites nothing: each EDGAR document is compared with its stored file (`verified`, or `changed`: reported, never written), and a transcript whose bytes changed is written beside the stored one as `transcript_{ID}_{TOKEN}.json` (`refreshed`), the copy every later read takes. Reports `unsupported` tickers and calls, `truncated` windows, pending releases and `stopped` when the provider's request limit is reached. |
| `plan [TICKER ...] [--from DATE] [--to DATE] [--refresh] [--watchlist PATH]` | Read-only. Per ticker, the window's periods with their documents, calls, texts and reports, the calls list and whether it is due, pending and unlisted calls, the invalid files, the failing reports, the series' freshness and the first action that applies: `fetch`, `text`, `research`, `render` or `reuse`; with `--refresh`, `fetch` while the window holds a listed period. |
| `text TICKER` | Writes each document's derived text that is missing, unreadable or differs from its derivation. |
| `check TICKER [PATH ...]` | Read-only: validates every report (or the drafts named) against its document's derived text, and a call's against its turns, and prints each problem. |
| `render TICKER` | Writes the time series from the complete periods. |
| `show TICKER` | Read-only: the action, the periods, the reports, the series, then the series rendered now. |

The bot writes only the per-document reports, which it may rewrite until `check` passes
them and again after a field's definition changes, and withdraws a raw file with
`.rejected`; Python writes everything else. A command that succeeds exits 0 and prints
JSON (`show`: Markdown), also with work left to do and when the provider's limit stopped
`fetch`; a refusal exits 2 with one `FUNDAMENTALS: ...` line on standard error.
PROCEDURE.md gives each field, each message and the step that follows it.

## Sources

Python reads two sources, both from `fetch` and only from it, each under its own
setting from the process environment or the ignored repository-root `.env` through
`common.env`; no other command reads either, and neither is ever written to `data/` or a
tracked file or printed (`fetch` prints `"user_agent": "set"` and `"api_key": "set"`).
Both are checked after the window and the data directory and before the watchlist and the
first request. Nothing else is evidence: no news, data vendor, company product page,
investor-relations presentation, search result or other transcript.

- **SEC EDGAR** is a public, read-only API that needs no account, sign-in or key and
  publishes a fair-access policy, which the client (`client.py`) follows exactly for
  every request (the ticker map, the submissions JSON, the 10-K and 10-Q documents, the
  filing index pages and the exhibits alike): every request names the person running it
  in `User-Agent` (`SEC_USER_AGENT`, a name and an email address), requests are paced
  0.2 s apart (half EDGAR's ten a second), only `https://www.sec.gov` and
  `https://data.sec.gov` are contacted, no redirect is followed (a document is kept only
  as served from the URL requested), no compressed body is accepted, every body has a
  size limit (20 MiB for JSON and for an index page, 50 MiB for a document) and a body
  shorter than its `Content-Length` is refused as cut short, so a truncated document is
  never written.
- **EarningsCalls.dev** serves the transcripts of issuers' earnings calls with each turn's
  speaker and role, under the user's own key (`EARNINGSCALLS_API`, a Pro plan: full
  transcripts and speaker segments, 3,000 requests a month, 20 a minute). Many issuers,
  Intel among them, publish no transcript of their call, and its question-and-answer
  session is where executives say most; the provider's transcript, kept verbatim, with
  each speaker's role, is what research quotes, and only the executives' turns are
  quoted. The client (`earningscalls.py`) contacts only `https://earningscalls.dev`,
  sends the key only in the `X-API-Key` header, paces its requests 3.1 s apart (under 20
  a minute), follows no redirect, accepts no compressed body, bounds every body (8 MiB)
  and refuses one cut short. HTTP 429, the request limit, stops every later request to
  the provider in the run, which goes on with EDGAR alone, and `fetch` exits 0 with
  `stopped` naming the line (the provider's own message is repeated, escaped, cut and
  with the key removed, since it says when the limit resets); every other failure is one
  line.

A failed request, a body that does not read (an EDGAR index page `filings.parse_filing_index`
refuses, a calls page or a transcript that breaks the provider's subset below) aborts the
run with one line: nothing of that document is written, the files written before it
stay, and a run again requests nothing that is already in `raw/` but the ticker map, each
ticker's submissions JSON (written only when its bytes changed) and the calls list when
it is due; only `--refresh` requests the window's documents, transcripts and calls list
again (Commands).

## Module boundaries

| Path | Responsibility |
| --- | --- |
| `AGENTS.md` | This file: the domain's aim, model, rules and outputs, then its sources, architecture and formats. |
| `PROCEDURE.md` | The bot's workflow: settings and parameters, `fetch`, `plan`, reading the derived text, writing and checking reports, `render`, `show`, failures. |
| `script/__main__.py` | Command line: `fetch`, `plan`, `text`, `check`, `render`, `show`; `LABEL = "FUNDAMENTALS"`, `FundamentalsParser` and `DATA_DIRECTORY`; `fetch` and `plan` default to the tickers of this domain's `watchlist.json` (`workflow.WATCHLIST`; `--watchlist PATH`), print the file they read (`watchlist`) and take `--refresh` and the window (`--from`, `--to`), which `main` resolves from the New York date and checks before the data directory, the settings or any request; builds the EDGAR client from `SEC_USER_AGENT` and the EarningsCalls.dev client from `EARNINGSCALLS_API` (`CALLS_SETTING`) for `fetch` only, before the watchlist is read; ASCII-only JSON output, `show`'s Markdown; exit codes. |
| `script/workflow.py` | The commands over `raw/`, `formatted/` and `reports/`: `fetch` (CIK lookup, the submissions JSON, then for each window period, oldest first, its 10-K or 10-Q, each release's filing index page and its EX-99 exhibits in Seq order, each only while it is not in `raw/`, or, with `--refresh`, requested again and compared with its file (`verified`, `changed`), never rewritten; `truncated` and the pending releases; then the calls list when due, or always with `--refresh`, and the transcripts, one whose bytes changed written beside the stored copy with `--refresh` (`refreshed`); `unsupported` and `stopped` calls), `plan` (the window periods' documents, calls, texts and reports, the series' freshness and the next action), `text`, `check` (`check_report`, with a call's turns), `render` and `show`. |
| `script/client.py` | EDGAR over HTTPS: URL builders (`submissions_url`, `archive_url`, `index_url`), `User-Agent` check, pacing, status, encoding and size rules (`JSON_LIMIT`, `DOCUMENT_LIMIT`, `INDEX_LIMIT`), the refusal of a body cut short of its `Content-Length`, no redirect followed, `EdgarError`; an injectable `Fetch`, `sleep` and clock; `decode_document` (strict UTF-8, else Latin-1); the HTTP reading `earningscalls` shares (`Response`, `read_body`, `lower_headers`, `declared_length`, `count_order`, `failure_reason`). |
| `script/earningscalls.py` | EarningsCalls.dev over HTTPS: the key check (`check_api_key`, `API_KEY_SETTING`), `HOST` only (`allowed_url`), pacing, status, encoding and size rules (`BODY_LIMIT`), no redirect followed, `EarningsCallsError` and `LimitReached` (HTTP 429); `EarningsCallsClient` (`events_page`, `transcript`) with an injectable `Fetch` (`urllib_fetch`), `sleep` and clock; the strict reading of a calls page (`parse_events_page`), of a capture (`check_capture`, `check_issuer`, `Ambiguous`) and of a transcript against its listed call (`parse_transcript`); a call's derived text and turns (`call_text`, `CallText`). |
| `script/filings.py` | Pure: the strict reading of `company_tickers.json`, of the submissions JSON's `filings.recent` (`RECENT_COLUMNS`, `items` included) and of an 8-K's filing index page (`parse_filing_index`: the `EX-99` and `EX-99.*` rows of the `Document Format Files` table, `EXHIBIT_PATTERN`, `.pdf` copies skipped); the window (`Window`, `default_window`); the periods and their releases by Rule B (`select_periods` → `Periods` of `Period` and `Release`, the pending releases, `truncated`; `NoPeriodicFilings`), and Rule B for any dated item (`rule_b`, `Periods.place`, `PENDING`). |
| `script/documents.py` | One ticker's `raw/` tree read into its listed periods and their documents (`period_documents` → `RawState` of `PeriodFiles`), every raw file it reads validated and each invalid one listed with its reason; the newest calls capture (`Capture`), the newest copy of each call's transcript (`RawState.transcript_files`), each call placed by Rule B, each period's call (`CallState`: `transcript`, `missing`, `unavailable`, `waiting`; `due_date`, `CALL_WAIT`), the pending and unlisted calls, and when the list is due again (`RawState.events_due`); what a period older than every listed one leaves out (`RawState.before_listing`); the names (`edgar_folder`, `doc_id`, `call_doc_id`, `events_name`, `transcript_name`, `Document.text_name`), the sentence rule's mode (`layout_mode`) and each document's derived text (`derive_text`, `derive_call`). |
| `script/text.py` | Pure: derived text of HTML and plain text (a Latin-1 filing or exhibit read as windows-1252); `normalise` and `locate`; the research rule `sentence_bounded` (sentence rule v2: `SENTENCE_ENDS`, `CLOSERS`, `OPENERS`, `BULLETS`; layout or block mode, and the speaker label). |
| `script/research.py` | Pure: the eleven fields (`FIELDS`, `FIELD_TITLES`), the wording rule (`WORDING`), the per-document report grammar (`parse_report`) and the rules each quote keeps against its document's derived text (`quote_problems`: length, location and spelling, sentence rule, speaker, wording, and a call's turns: `Turn`, `EXECUTIVE`). |
| `script/report.py` | Pure: the time series in Markdown (`render_series`; `SeriesPeriod` with each period's status and what it misses, `CALL_MISSING`, `CALL_WAITING`; `call_label`, `UNAVAILABLE`), its as-of date (`report_as_of`), its file names (`series_name`, `series_files`, `newest_series`) and freshness (`same_series`). |
| `data/` | Runtime files (below); ignored by Git except `data/.gitignore`. |

Dependencies point one way: `__main__` uses `workflow`, `client` and `earningscalls` (the
clients and their errors) and `filings` (`Window` and `default_window`); `workflow` uses
`client`, `documents`, `earningscalls`, `filings`, `report` and `research`; `report` uses
`documents` and `research`; `documents` uses `client` (limits and `decode_document`),
`earningscalls`, `filings` and `text`; `earningscalls` uses `client` (`Response`, `Fetch`
and the HTTP reading it shares), `research` (`Turn`) and `text`; `research` uses `text`.
`client`, `filings` and `text` depend on nothing else in the package. From
`market_state_research.common`, `__main__` takes its parser, argument types and `fail`
(`cli`), the settings (`env`) and `DataLayout` (`layout`); `workflow` names the domain's
watchlist and reads it (`watchlist`) and normalises tickers (`text`);
`documents`, `report` and `workflow` use `layout`; `client`, `earningscalls`, `filings`,
`report`, `research` and `workflow` keep messages on one line with `text.printable`; and
the modules read the clock and convert times through `times`. This domain imports
nothing from `stock_iv_regime`; EDGAR and EarningsCalls.dev are its only network peers.

## Runtime files

All paths are relative to this domain and ignored by `data/.gitignore`. `{T}` is the
ticker.

| Path | Writer | Content |
| --- | --- | --- |
| `data/raw/{T}/edgar/submissions_{TOKEN}.json` | `fetch` | EDGAR's submissions JSON, written only when its bytes differ from the newest such file's. The newest one lists the periods on every read; older ones are never read. |
| `data/raw/{T}/edgar/{FORM}_{DATE}_{ACCESSION}/{DOCUMENT}` | `fetch` | A document as EDGAR served it: a 10-K's or 10-Q's primary document (`FORM` `10-K` or `10-Q`, `DATE` its period end), or an Item 2.02 8-K's filing index page `{ACCESSION}-index.htm` and the EX-99 exhibits it lists (`FORM` `8-K`, `DATE` its report date, so a folder never moves when Rule B places a release again). |
| `data/raw/{T}/calls/events_{TOKEN}_{PAGE}.json` | `fetch` | One page of the ticker's earnings calls as EarningsCalls.dev served it, verbatim; the pages of one request share `TOKEN`, the New York time page 1 arrived, and every request writes its pages, so the newest capture's time is when the provider last showed its list. Only the newest capture is read. |
| `data/raw/{T}/calls/transcript_{ID}.json`, `transcript_{ID}_{TOKEN}.json` | `fetch` | The transcript of the call `ID` as EarningsCalls.dev served it (`GET /transcripts/{ID}/components`), verbatim: `transcript_{ID}.json`, written once, then from `fetch --refresh` each copy whose bytes differ from the newest one's, named by the New York time it arrived. The newest copy is read (the one without a token is the oldest); older ones are never read. A transcript of a call the newest capture does not list is unlisted: left out, never invalid. |
| `data/formatted/{T}/{DOC_ID}.md` | `text` | The document's derived text, UTF-8, what the bot reads and quotes. Rewritten when its derivation differs or the file cannot be read. |
| `data/reports/{T}/{DOC_ID}.md` | the bot | The eleven-field report of one document (The per-document report). |
| `data/reports/{T}/{T}_{AS_OF}_{TOKEN}.md` | `render` | The time series. |

`DOC_ID` names a document's text file and its report. An EDGAR document's is its folder
name, `_` and its file name without the extension
(`10-Q_2026-06-27_0000050863-26-000157_intc-20260627`,
`8-K_2026-07-23_0000050863-26-000155_q226earningsrelease`); a call's is `call_{PERIOD}_{ID}`
(`call_2026-06-27_248001`). An index page and a calls list have no `DOC_ID`, no text and
no report. Two documents whose `DOC_ID`s collide, letter case aside, make the later one
invalid. A file in `calls/` named otherwise than the three forms above is invalid. `{TOKEN}` is the New
York time of the command that wrote the file, to the second, with its zone
(`20261008T025725EDT`); a name whose token is after the command's clock is ignored.

## Formats verified live

- EDGAR's bodies are read as a strict subset of their documented or verified layout
  (`filings.py`: `RECENT_COLUMNS` and `parse_filing_index`): `company_tickers.json`, the
  submissions JSON's `filings.recent` (`RECENT_COLUMNS`, `items` included) and the filing
  index page. The index page's layout is a provider format, verified on Intel's 8-K
  0000050863-26-000155: exactly one `<table class="tableFile" summary="Document Format
  Files">`, closed by its own `</table>` and holding no other table, whose first row's
  cells are Seq, Description, Document, Type and Size and whose other rows have five
  cells; an exhibit row's Document cell links only to its document in the filing's
  folder, directly or through EDGAR's `/ix?doc=` viewer, and its Type is `EX-99` alone or
  `EX-99.` and 1 to 16 letters, digits or dots. When EDGAR changes a field or this
  layout, `fetch` fails loudly with one line naming the field and row (for an index page,
  `filing index {accession}: ...` with the row position and the rule, never a cell's
  text) instead of guessing, and writes nothing of that document. An index page in `raw/`
  is parsed again on every read, so a reader change that refuses it makes it an invalid
  file, and one that reads other exhibits from it changes its period's documents, never
  silently.
- EarningsCalls.dev, verified live on 2026-10-19 (OpenAPI at
  `https://earningscalls.dev/openapi.json`): `GET /api/v1/me` reports the key's tier and
  usage, and the headers `x-ratelimit-limit` and `x-ratelimit-remaining` count the month;
  every answer with status 200, 400 or 404 counts against the 3,000, 401, 403 and 429 do
  not. The archive holds about 256,000 transcripts of 12,900 companies from 2020-01-02
  on, US names of the watchlist among them; coverage has gaps (Intel's list lacks its
  July 2025 call), and a symbol listed elsewhere resolves to that listing (ASML's calls
  are `ASML:NL`'s: none with `country=US`). Transcripts land within hours of a call.
  - `GET /api/v1/earnings/?ticker={T}&event_type=earnings&country=US&limit=100&sort=date_desc&page={N}`
    answers `{"data": [...], "pagination": {"page", "limit", "total", "total_pages"},
    "ambiguous": false, "issuer_count": 1}` (an empty list: `total` 0, `total_pages` 0,
    `issuer_count` 0). A row holds `id` (the call's stable id), `event_type`,
    `event_date_time` (UTC, `2026-07-23T21:00:00.000Z`), `stock_symbol` (`INTC`),
    `company_ticker` (`INTC:US`), `country`, `issuer_id` (32 hex digits, null on some
    legacy rows), `fiscal_year` and `fiscal_quarter` (read from the title, null when
    absent), `matched_alias` and descriptive keys (`company_name`, `transcript_title`,
    `sector`, `exchange`, `mic`, `isin`, `timezone` ...). Of these the subset read is
    `id`, `event_type` (`earnings`), `event_date_time`, `stock_symbol` (the ticker's own),
    `country` (`US`), `issuer_id` (one issuer across the capture), `fiscal_year`,
    `fiscal_quarter`, the pagination and `ambiguous` (false) with `issuer_count` (at most
    1). A list that is `ambiguous` makes the ticker's calls `unsupported`, nothing
    written.
  - `GET /api/v1/transcripts/{id}/components` answers `{"data": {"company_name",
    "transcript_title", "event_type", "duration_seconds", "header": {"title",
    "event_date_time", "announced_date", "duration", "created_at", ...}, "components":
    [...]}}`; each component is `{"order", "speaker_name", "speaker_type", "text"}`, in
    call order from 0, `speaker_type` one of `executive`, `analyst`, `operator`,
    `attendee`, `shareholder` and `unknown`, and paragraph breaks inside `text` are
    `\r\n`. The header writes the call's time without milliseconds
    (`2026-07-23T21:00:00Z`), the same instant the list gives. The subset read is
    `data.event_type` (`earnings`), `data.header.title`, `data.header.event_date_time`
    (the listed call's instant) and every component's four keys. Intel's call of
    2026-07-23 (id 248001) has 61 turns; its executives are John Pitzer, Lip-Bu Tan and
    David Zinsner. `GET /api/v1/transcripts/{id}?format=full` (one string) and
    `GET /api/v1/speakers/{id}` (turns by 50) carry the same and are not used.

  Every value read must have its type and grammar, other keys are ignored, and repeated
  keys, `NaN` and `Infinity` are refused. A body that breaks the subset is refused with
  the field and the rule, never its text, and nothing is written; a page or transcript in
  `raw/` is validated again on every read, so a tightened rule makes it an invalid file.
