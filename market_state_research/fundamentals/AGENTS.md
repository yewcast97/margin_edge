# Fundamentals

This domain keeps, per stock issuer and per season (one fiscal period, named by its end) in a
window, the issuer's own documents of the season verbatim, derives their text, and compares the
season with its baseline over six aspects: guidance, capital expenditure, upstream supply,
downstream demand, debt structure and the product roadmap. Each season is read in one
comparison per kind that applies to it: every season against the season before it (`quarter`),
and a 10-K season also against the previous 10-K season (`year`). For each comparison the bot
lists every item it finds of each aspect in the documents of both sides, with the season's
value, the baseline's value and the difference between them, each resting on verbatim quotes,
and `check` holds those readings to their rules; `render` writes one report per comparison.
Python lists the documents and computes no figure. Its default tickers are those of this
domain's own watchlist. This file says first what the work aims at, the model of seasons,
filings and calls, the aspects and the comparisons, the quote rules, the derived text and the
season's sheet, the readings, the reports and the commands; then the sources and why Python may
read them, the module boundaries, the runtime files and the formats verified live. The
operations the bot carries out (settings, `fetch`, `plan`, `derive`, reading the documents,
writing and checking readings, `render`, `show`, failures) are in the sibling
[PROCEDURE.md](PROCEDURE.md); the conventions every domain shares (the domain layout, the three
sections of `data/`, New York time, the API rule) are in
[market_state_research/AGENTS.md](../AGENTS.md). This domain reads no market data: its
documents are dated by their own dates, and it uses no XNYS session.

## Aim

For each issuer, season by season, what the issuer's documents state of six aspects against
what the documents of the season before stated (and, for the fiscal year, those of the previous
fiscal year): every item found, listed as found, at scale and without judgment. An item is one
subject the documents state (a guided measure for a period, a capital project, an input, a
customer or end market, a note or facility, a product), with its value in the season (new) and
in the baseline (old) side by side and the difference between them in facts, each value resting
on quotes copied verbatim from its own side's documents. Where a side states nothing of an
item, its value is `na`; where neither side states anything of an aspect, the aspect is `na`.
No threshold decides whether a change counts and no item is left out, scored, weighed or
ranked: the report lists every item in the order the readings give it. Judgment is the user's:
a report says what each side states and where the words are, never what that means. Every
original document is kept as served. No valuation, forecast, rating, recommendation or advice
is added by the readings, the reports or the bot.

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
  | `NT 10-K`, `NT 10-Q`, `S-3`, `S-3ASR`, `424B2`, `424B3`, `424B4`, `424B5`, `424B7`, `8-K/A`, `10-K/A`, `10-Q/A` | `filingDate` | nothing: the season's sheet lists them |

  No other form is read: a Form `4`, a proxy statement (`DEF 14A`) or a beneficial owner's
  schedule (`SC 13D/A` ...) is neither listed nor fetched. An 8-K must have a `reportDate`, not
  after its filing date, and a `primaryDocument` that is a plain file name the archive serves.
  An 8-K that breaks either rule (but an Item 2.02 8-K, above) is skipped: listed with its
  reason as `skipped_filings`, never fetched.
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

  A `waiting` or `unavailable` call blocks nothing: the season's documents are read without a
  call, and a transcript that arrives later makes the season's sheet and reports stale and is a
  document its readings do not name yet. The list is asked for again (`plan` says `fetch`) when
  there is none, or while a window season's call is `waiting` or `unavailable` and the newest
  list is 7 days old or more, or, for a `waiting` call, was fetched on or before the season's
  due date and that date has passed: a call lands within hours, a permanently missing one costs
  about four requests a month.
- The documents of a season, each with its derived text and its `DOC_ID`, are its 10-K or
  10-Q primary document; each 8-K's primary document and every EX-99 exhibit its filing index
  page (`{accession}-index.htm`, the one EDGAR page that names each document's exhibit type)
  lists, in Seq order, except EDGAR's unofficial `.pdf` copies, whose official `.htm` or
  `.txt` is listed too (an EX-99 exhibit is a row whose Type is `EX-99` alone or `EX-99.` and
  a suffix, such as `EX-99.1`; any other Type that starts with `EX-99`, such as `EX-99-1` or
  `EX-99A`, is refused loudly rather than read or ignored); and each call's transcript. An
  8-K's earnings release is its EX-99 exhibits when it names Item 2.02. The index pages and the
  calls list are kept in `raw/` too and read by Python alone: they have no derived text, and no
  reading quotes them.
- Nothing a read needs lives only in a file name: each filing's form, accession, dates and
  season come from the newest submissions file (Rule B included) on every read, an exhibit's
  type and Seq from its index page, parsed again on every read, and each call's id, date and
  season from the newest calls list, with the transcript read against the call it lists.
- The window is a pair of New York calendar dates, `--from` and `--to`, bounding the season
  ends, both included (`--to` defaults to today and may not be after it; `--from` defaults to
  the same day two years before `--to`). Its comparisons reach back to seasons before it, so
  `fetch` writes the *span*: the window's seasons and the four listed before them
  (`aspects.BASELINE_SEASONS`). `plan` weighs the span's documents, texts and calls and the
  window's sheets, readings and reports; `show` weighs the default window. Only
  `filings.recent` is read (EDGAR's latest year or 1,000 filings at least; the older pages
  under `filings.files` are not), so a window whose `--from` precedes the oldest filing date
  it lists is reported `truncated: true`: seasons before that are not seen. As EDGAR's list
  moves on, a later submissions file may no longer list a season: every file of a season older
  than the oldest listed one is then left out, as if it were not in `raw/`, and blocks nothing.
  `derive`, `check` and `render` take no window: they work on every listed season in `raw/`.

## The aspects and the comparisons

The six aspects below are the whole definition of what a season is read against
(`aspects.py`), in the order every readings file and report follows; each covers, as the
documents state them:

| Key | Aspect | Covers |
| --- | --- | --- |
| `guidance` | Guidance | Every measure the issuer guides (revenue, margins, earnings per share, expenses, tax rate, cash flow, share count and any other), each with its period, its range or point and its basis, and the results of a period set against the guidance given for it. |
| `capex` | Capital expenditure | Capital expenditure as guided and as spent, gross and net of partners' contributions, grants and other offsets, and the projects it funds (fabs, plants, equipment) with their timing. |
| `supply` | Upstream supply | The inputs the issuer buys or makes: suppliers, components, materials, wafers, substrates, equipment and capacity, with their availability, constraints, lead times and prices, and the issuer's own inventory. |
| `demand` | Downstream demand | Customers and end markets: demand, orders, backlog, bookings, pricing, customers' inventory and the share of revenue from the largest customers. |
| `debt` | Debt structure | Notes and loans with their rates and maturities, credit facilities and what they leave available, commercial paper, covenants, issuance, repayment and refinancing, and interest expense. |
| `roadmap` | Product roadmap | Products, process nodes, technologies and services: launches, ramps, timelines, milestones, delays and discontinuations. |

- A season is read in one comparison per kind that applies to it (`aspects.comparisons`):

  | Kind | Seasons | Baseline |
  | --- | --- | --- |
  | `quarter` | every season | the previous listed season: a 10-Q season is compared with the quarter before it, the first quarter with the 10-K season (the fourth quarter), and a 10-K season with the third quarter |
  | `year` | a 10-K season | the latest 10-K season among the four listed before it: the previous fiscal year's |

  A comparison's baseline is every document of its baseline season: the 10-K or 10-Q, the
  8-Ks Rule B places in it and its call. Its sheet (`season.md`) names both sides' `DOC_ID`s.
  A long window therefore yields many reports: one per season, two for each 10-K season.
- An item is one subject an aspect covers, found in the documents of one side or both: a
  guided measure for one period, a capital project, an input, a customer or end market, a note
  or facility, a product or process node. Statements on one subject, in the season's documents
  or the baseline's, are one item with several quotes; statements on different subjects are
  different items. There is no fixed list of items: the bot lists every one it finds, its title
  its own words.
- An item states the season's value (new) and the baseline's (old), each one line of facts
  that names its period, its basis and its unit (`fiscal 2026 revenue $52.0 to $56.0 billion,
  non-GAAP`), written alike on both sides so that the two read side by side, and the
  difference between them in facts. A value is `na` when the documents of its side state
  nothing of the item (an item only one side states has `na` on the other); the old value is
  `no baseline` when the baseline season is not listed or none of its documents is in `raw/`;
  the difference is `na` beside a value that is `na` or `no baseline` and `none` when the two
  values are written alike. An aspect the documents of neither side state anything of is `na`.
  An item of no value on either side is no item.
- Nothing ranks, weighs or scores an aspect or an item, and no threshold applies: every item
  found is listed, whatever its difference.

The aspects are code: `aspects.py` states each, the same for every issuer, changed only there
(`git log -p` dates each change). A changed aspect changes the readings written after it; a
reading written before it keeps passing `check`: apply a changed aspect by reading the affected
seasons again and rewriting that aspect's items.

## Quotes

- Report facts, not ideas, and never distort a statement. A quote is the evidence an item's
  value rests on: a verbatim span of its own document's derived text, spelt with the text's
  own characters (only the whitespace between words may differ, so a quote holds no soft
  hyphen, zero-width character or ligature the text does not). Nothing in a quote is
  paraphrased, summarised, translated, trimmed, merged, completed or inferred. A quote that is
  invented, reworded, filled in from memory, the web, another document or inference, or
  retyped from anywhere but the derived text is a failed run.
- A quote is whole sentences, or whole lines of an HTML document or a call transcript, so that
  no quote cuts a statement (`text.sentence_bounded`, sentence rule v2, checked at the quote's
  first occurrence in the derived text; its normalised length is 20 to 800 characters). The
  rule reads a line break in one of two modes, chosen by the document's kind and name alone,
  never its contents (`documents.layout_mode`):
  - *layout* mode, for a filing or exhibit whose document name ends in `.txt` (any case): a
    line break is ordinary whitespace. These lines wrap where the page ran out, as often inside
    a sentence as at its end, so they carry no structure and a quote runs from a sentence start
    to a sentence end across them; a whole line is not a statement;
  - *block* mode, for HTML and iXBRL documents and a call's transcript: a line break ends a
    block, and a whole line (a table row, a bullet, a heading, a paragraph of a speaker's turn)
    is a quote of its own unless the next line starts in lowercase and so continues it.

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
- An item's title, its values and its difference state facts only: the figures with their
  units and periods, the names, counts and dates the comparison rests on. They carry no
  valuation, forecast or advice wording (`readings.WORDING`); quotes are the issuer's words and
  are never checked against that rule.

Applied to every document, these rules follow:

1. **Evidence.** Quote the statements each value rests on, from its own side's documents:
   every document an item's `season:` or `baseline:` line names is quoted at least once in the
   item, and every quote comes from a document one of those lines names.
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
   line or sentence right before or after it. A statement that is whole only in more than 800
   characters (a long sentence, a lowercase list with its lead-in) cannot be quoted: quote
   another whole statement of its document that gives the same value (a table row, a
   heading's line). A quote is given once per item.
5. **Turns.** Give a call's quote the turn its first occurrence lies in, as the heading writes
   it.

## Derived text and the season's sheet

Derived text is one deterministic function of a document's raw bytes (`text.py`,
`earningscalls.call_text`): the visible text of an HTML or iXBRL filing or exhibit, the
line-normalised text of a `.txt` filing or exhibit, or a call's transcript laid out per turn,
in order, as a heading line `{speaker_name} ({speaker_type})` and then the turn's text, whose
`\r\n` paragraph breaks become line breaks, each line normalised as plain text. `derive` writes
it as `formatted/{T}/{PERIOD}/{DOC_ID}.md`, with no markup added, for the bot to read and
quote; it is derived again from `raw/` on every read, so a text file that differs from its
derivation, or cannot be read, is reported and rewritten by `derive`, and `check` passes a
reading only against text files equal to the derivation. A quote is located in the text
case-sensitively, whitespace runs matching any whitespace, smart quotes and dashes matching
only themselves. The sentence rule is a rule over located quotes, not part of the derivation:
it changes no derived text.

The derived-text rules are module code and constants in `text.py` and `earningscalls.py`: the
HTML and plain-text derivations, the character clean-up and the layout of a call. A change of
them, or a Python release whose standard library changes `html.parser` or the Unicode database,
makes every affected text file differ from its derivation: `plan` says `derive`, and `check`
fails each reading that names such a document until `derive` has rewritten its text file, then
names each quote the new text no longer holds. The quote rules (`text.sentence_bounded`, the
turn, wording and length rules in `readings.py`) are applied by every `check`: tightening one
fails every reading that breaks it, and `plan` says `research` until the readings are fixed.

**`season.md`** is the season's sheet, `formatted/{T}/{PERIOD}/season.md`, what the bot reads a
season from: a pure function of `raw/` and the code (`sheet.py`), with no time of its own, so a
season's sheet is fresh while equal to what `derive` would write now. Under the title
`# {T} · {PERIOD} · season` it holds the season's 10-K or 10-Q (accession, filing date,
acceptance time) and its call's state (the calls of a transcript, or the date of the calls list
an `unavailable` or `waiting` call rests on); `## Comparisons`, each comparison of the season
with its baseline season and that season's documents in `raw/` with their `DOC_ID`s;
`## Filings of the season`, every filing Rule B places in it with its form, dates, acceptance
time, accession, items and documents (a listed-only form marked so); and `## Inputs for the
bot`, the season's documents by what they are: its 10-K or 10-Q, its earnings releases (the
8-Ks with Item 2.02), its 8-Ks with Items 1.01 or 2.03 (a material agreement, a direct financial
obligation), its other 8-Ks, its call, and the registrations and prospectuses, amendments and
late-filing notices listed but not fetched. Python reads no document's words and computes no
figure: the sheet lists. Its fixed text passes `readings.WORDING`.

## The readings

The bot's readings of a comparison are UTF-8 Markdown at
`reports/{T}/{PERIOD}/readings_{KIND}.md` (`readings_quarter.md` for every season,
`readings_year.md` for a 10-K season too), rewritten until `check` passes them
(`readings.py`). Line by line:

- G1: the first non-blank line is `# {T} · {PERIOD} · {KIND} readings`, `KIND` the
  comparison's, `quarter` or `year`;
- G2: then one section per aspect, each once, in the aspects' order, headed `## {Aspect}` as
  the table above writes it;
- G3: a section is the one line `na`, when the documents of neither side state anything of the
  aspect, or its items, each headed `### {title}` (1 to 120 printable characters, no two alike
  in one aspect, letter case aside) and followed by five lines in this order: `season:`,
  `new:`, `baseline:`, `old:` and `difference:`;
- G4: `season:` and `baseline:` are `none` or distinct `DOC_ID`s joined by `; `: the documents
  of the season, and of the baseline season, that the new value, and the old one, rest on;
- G5: `new:` is the season's value and `old:` the baseline's, each `na` or the value in facts
  (`no baseline`, an old value only, while the baseline is not in `raw/`); `difference:` is
  `na`, `none` or the difference in facts; each is 1 to 600 printable characters on its line;
- G6: then zero or more quotes, each a run of `> TEXT` lines, whose texts are joined by one
  space (so wrap a long quote at any space), followed by one attribution line, `— {DOC_ID}`,
  or `— {DOC_ID}, {Speaker} ({role})` for a call's quote; blank lines may separate quotes.

Any other line is an error; trailing spaces, CRLF line ends and a leading byte order mark are
accepted. `check` then holds each item to these rules:

- R0: `year` readings are a 10-K season's only;
- R1: every `DOC_ID` named is a document of a listed season in `raw/` whose text file equals
  its derivation;
- R2: `season:` names documents of the season only, `baseline:` documents of the
  comparison's baseline season only;
- R3: `season:` is `none` exactly when `new:` is `na`, and `baseline:` exactly when `old:` is
  `na` or `no baseline`, so that a value in facts names the documents it rests on; every
  document either line names is quoted in the item; `none` is no value;
- R4: `no baseline` is an old value only, and exactly while the baseline season is not listed or
  none of its documents is in `raw/`; an item states a value on one side at least;
- R5: `difference:` is `na` exactly when a value is `na` or `no baseline`, and `none` exactly
  when the two values are written alike, the runs of whitespace between their words aside;
- R6: a quote comes from a document its item's `season:` or `baseline:` line names and keeps the
  quote rules (Quotes): 20 to 800 characters once normalised, found verbatim and spelt as the
  derived text writes it, whole sentences or lines at its first occurrence; a call's quote
  names its turn's heading exactly and lies within that turn; a quote of another document
  names no speaker; no quote is given twice in one item;
- R7: an item's title, values and difference carry no valuation, forecast or advice wording.

`check` checks every readings file of every listed season, or the drafts named, each in its
season's folder and read as the comparison its title names. Two aspects of the readings of a
10-K season's `year` comparison, for illustration (the figures and `DOC_ID`s are invented):

```markdown
# INTC · 2025-12-27 · year readings

## Guidance

### Full-year revenue guidance, fiscal year
season: 8-K_2026-01-22_0000050863-26-000009_q425earningsrelease
new: fiscal 2026 revenue $52.0 to $56.0 billion, GAAP
baseline: 8-K_2025-01-30_0000050863-25-000004_q424earningsrelease
old: fiscal 2025 revenue $50.0 to $54.0 billion, GAAP
difference: $2.0 billion higher at both ends of the range
> We expect fiscal 2026 revenue of $52.0 billion to $56.0 billion.
— 8-K_2026-01-22_0000050863-26-000009_q425earningsrelease
> We expect fiscal 2025 revenue of $50.0 billion to $54.0 billion.
— 8-K_2025-01-30_0000050863-25-000004_q424earningsrelease

## Upstream supply

na
```

## The reports and `show`

`render` writes, for every comparison of a listed season whose readings pass `check`, whose
season's and baseline's texts and the season's sheet are fresh and whose newest report is not
the report rendered now, a new report `reports/{T}/{PERIOD}/report_{KIND}_{TOKEN}.md`, and never
overwrites one (`report.py`). Under the title `# {T} · {PERIOD} · {KIND} report` and its
`Generated` line, it names the issuer (its EDGAR name and CIK), the season (its 10-K or 10-Q,
accession and filing date) and its call's state, the comparison (`quarter: this season against
the previous season, 2025-09-27 (10-Q).`, or `year: this 10-K season against the previous 10-K
season, 2024-12-28.`, or `none is listed`), the season's documents and the baseline's in `raw/`
by `DOC_ID`, and, in the newest listed season's report alone, the filings and calls pending:
dated after its 10-K or 10-Q was filed, which Rule B places once the next season is listed;
then the count line, `12 items in 6 aspects; aspects without an item: Upstream supply.`; then
one section per aspect, in the aspects' order, holding a table `| Item | New | Old | Difference |`
of its items in the readings' order, each value followed by ` · ` and the `DOC_ID`s it rests on
(`na` and `no baseline` stand alone), or the line `na`; then `## Evidence`, per item in the
same order, `### {Aspect} · {Item}`, the documents of each side and the quotes with their
attributions. A report is a pure function of the season's files, its comparison's baseline and
the readings, but for its `Generated` line: the newest report of a comparison is fresh while it
equals the report rendered now apart from that line (the shared rule), and a new transcript, a
new pending filing of the newest season or a rewritten reading makes it stale.

`show` prints, per ticker (by default those of the watchlist), the action `plan` gives over
the default window and the newest season one of whose reports can be rendered now, each of its
comparisons' newest report's path and freshness, and those reports rendered now (two for a 10-K
season), or why none can be. It orders the tickers as given, or as the watchlist lists them,
and ranks nothing.

## Freshness, missing data and what is never added

- A pending filing or call is listed by `fetch` and `plan` and may later join a season already
  read, whose new documents then change its sheet and need its readings checked again. A call
  the provider never lists leaves its season `unavailable` once the list says so, 7 days after
  the season's due date; a call it lists later turns the season back to `transcript`.
- Every raw file is validated on every read; an invalid one, a *moved* filing or transcript
  included, is listed and blocks `derive`, `check` and `render` until it is withdrawn by
  renaming it `.rejected`, after which `fetch` writes it again where it belongs. The folders
  `raw/{T}/edgar/` and `raw/{T}/calls/` hold the former layout (until 2026-10-23): never read,
  they make `plan` say `fetch` until each is renamed `.rejected`, and `fetch` then writes the
  window again in seasons. The former layout's derived texts and reports, files directly in
  `formatted/{T}/` and `reports/{T}/`, are listed as `stray_files` and `stray_reports`: a stray
  text file is rebuilt by no command and may be deleted; a stray report is left as it is.
- What `fetch` wrote until 2026-10-24 and no longer writes is left out and listed as unlisted,
  never invalid: the company facts (`raw/{T}/companyfacts_{TOKEN}.json`) and the folders of the
  forms no longer read (`4_…`, `DEF14A_…`, `SC13DA_…`, `SC13GA_…`, `SCHEDULE13DA_…`,
  `SCHEDULE13GA_…`). A season folder's `readings.md`, `measures.md` and `report_{TOKEN}.md`
  of the catalogue before 2026-10-24 are read by no command.
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
| `fetch [TICKER ...] [--from DATE] [--to DATE] [--refresh] [--watchlist PATH]` | The one network command. Writes the span's 10-Ks, 10-Qs and 8-Ks from EDGAR into `raw/`, each document only while it is not there yet; then the ticker's calls list from EarningsCalls.dev when it is due, and the transcript of every call placed in a span season that is not in `raw/` yet. With `--refresh`, only when the user asks, it requests all of these again, whatever `raw/` holds, and rewrites nothing: each EDGAR document is compared with its stored file (`verified`, or `changed`: reported, never written), and a transcript whose bytes changed is written beside the stored one as `transcript_{ID}_{TOKEN}.json` (`refreshed`), the copy every later read takes. Reports `unsupported` tickers and calls, `truncated` windows, pending and skipped filings and `stopped` when the provider's request limit is reached. |
| `plan [TICKER ...] [--from DATE] [--to DATE] [--refresh] [--watchlist PATH]` | Read-only. Per ticker, the span's seasons with their filings, call and texts, and per window season its sheet and its comparisons, each with its baseline, readings and report; the calls list and whether it is due; pending, skipped and unlisted items, the former layout, the invalid and stray files; and the first action that applies: `fetch`, `derive`, `research`, `render` or `reuse`; with `--refresh`, `fetch` while the window holds a listed season. |
| `derive TICKER` | Writes each document's derived text and each season's `season.md` that is missing, unreadable or differs from its derivation. |
| `check TICKER [PATH ...]` | Read-only: checks every readings file of every season (or the drafts named, each in its season's folder) and prints each problem. |
| `render TICKER` | Writes the report of every comparison whose readings pass and whose newest report is not current. |
| `show [TICKER ...] [--watchlist PATH]` | Read-only: per ticker the action and the newest season's reports rendered now. |

The bot writes only the readings, which it may rewrite until `check` passes them and again
after an aspect changes, and withdraws a raw file with `.rejected`; Python writes everything
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
  ticker map, the submissions JSON, the filings' documents and the filing index pages alike):
  every request names in `User-Agent` whom it is made for (`SEC_USER_AGENT`, a name and an
  email address the user gives), requests are paced 0.2 s apart (half EDGAR's ten a second),
  only `https://www.sec.gov` and `https://data.sec.gov` are contacted, no redirect is followed
  (a document is kept only as served from the URL requested), no compressed body is accepted,
  every body has a size limit (20 MiB for the submissions JSON and for an index page, 50 MiB for
  a document) and a body shorter than its `Content-Length` is refused as cut short, so a
  truncated document is never written. A season takes 5 to 15 requests (its 10-K or 10-Q, and
  per 8-K its index page, primary document and exhibits), so a ticker's default window with the
  four seasons before it takes about 100 the first time and two a run after, besides the new
  filings' documents.
- **EarningsCalls.dev** serves the transcripts of issuers' earnings calls with each turn's
  speaker and role, under the user's own key (`EARNINGSCALLS_API`, a Pro plan: full
  transcripts and speaker segments, 3,000 requests a month, 20 a minute). Many issuers, Intel
  among them, publish no transcript of their call; the provider's transcript, kept verbatim,
  with each speaker's role, is the call the readings read and quote. The client
  (`earningscalls.py`) contacts only `https://earningscalls.dev`, sends the key only in the
  `X-API-Key` header, paces its requests 3.1 s apart (under 20 a minute), follows no redirect,
  accepts no compressed body, bounds every body (8 MiB) and refuses one cut short. HTTP 429,
  the request limit, stops every later request to the provider in the run, which goes on with
  EDGAR alone, and `fetch` exits 0 with `stopped` naming the line (the provider's own message
  is repeated, escaped, cut and with the key removed, since it says when the limit resets);
  every other failure is one line.

A failed request, or a body that does not read (an index page `filings.parse_filing_index`
refuses, a calls page or a transcript that breaks the provider's subset below), aborts the run
with one line: nothing of that document is written, the files written before it stay, and a run
again requests nothing that is already in `raw/` but the ticker map, each ticker's submissions
JSON (written only when its bytes changed) and the calls list when it is due; only `--refresh`
requests the span's documents, transcripts and calls list again (Commands).

## Module boundaries

The domain's files and the package `market_state_research.fundamentals.script`, through which a
hypothesis script reads this domain's `raw/` ([explore_hypothesis/AGENTS.md](../../explore_hypothesis/AGENTS.md)):

| Path | Responsibility |
| --- | --- |
| `AGENTS.md` | This file: the domain's aim, model, aspects, rules and outputs, then its sources, architecture and formats. |
| `PROCEDURE.md` | The bot's workflow: settings and parameters, `fetch`, `plan`, `derive` and reading the documents, writing and checking readings, `render`, `show`, failures, the former layout. |
| `script/__main__.py` | Command line: `fetch`, `plan`, `derive`, `check`, `render`, `show`; `LABEL = "FUNDAMENTALS"`, `FundamentalsParser` and `DATA_DIRECTORY`; `fetch`, `plan` and `show` default to the tickers of this domain's `watchlist.json` (`workflow.WATCHLIST`; `--watchlist PATH`); `fetch` and `plan` print the file they read (`watchlist`) and take `--refresh` and the window (`--from`, `--to`), which `main` resolves from the New York date and checks before the data directory, the settings or any request; builds the EDGAR client from `SEC_USER_AGENT` and the EarningsCalls.dev client from `EARNINGSCALLS_API` (`CALLS_SETTING`) for `fetch` only, before the watchlist is read; ASCII-only JSON output, `show`'s Markdown; exit codes. |
| `script/workflow.py` | The commands over `raw/`, `formatted/` and `reports/`: `fetch` (the CIK, the submissions JSON, then for each span season, oldest first, its 10-K or 10-Q and each 8-K Rule B places in it, then the calls list when due and the transcripts; `--refresh`; `unsupported`, `truncated`, pending and skipped filings, `stopped`), `plan` (each season's state, its comparisons and the next action), `derive`, `check`, `render` and `show`. |
| `script/client.py` | EDGAR over HTTPS: URL builders (`submissions_url`, `archive_url`, `index_url`), `User-Agent` check, pacing, status, encoding and size rules (`JSON_LIMIT`, `DOCUMENT_LIMIT`, `INDEX_LIMIT`), the refusal of a body cut short of its `Content-Length`, no redirect followed, `EdgarError`; `decode_document` (strict UTF-8, else Latin-1); the HTTP reading `earningscalls` shares. |
| `script/earningscalls.py` | EarningsCalls.dev over HTTPS: the key check (`check_api_key`, `API_KEY_SETTING`), `HOST` only (`allowed_url`), pacing, status, encoding and size rules (`BODY_LIMIT`), no redirect followed, `EarningsCallsError` and `LimitReached` (HTTP 429); `EarningsCallsClient` (`events_page`, `transcript`); the strict reading of a calls page (`parse_events_page`), of a capture (`check_capture`, `check_issuer`, `Ambiguous`) and of a transcript against its listed call (`parse_transcript`, with its optional `duration_seconds`); a call's derived text and turns (`call_text`, `CallText`, `Turn` with its `heading`). |
| `script/filings.py` | Pure: the strict reading of `company_tickers.json`, of the submissions JSON's `filings.recent` (`RECENT_COLUMNS`, `items` and `acceptanceDateTime` included) and of an 8-K's filing index page (`parse_filing_index`); the forms read (`FETCHED_FORMS`, `LISTED_FORMS`, `NOTICES`, `REGISTRATIONS`, `AMENDMENTS`, `DATED_BY_REPORT`, `FORM_TOKENS`) and the 8-K items the sheet groups by (`ITEM_RESULTS`, `ITEMS_FINANCING`); the window (`Window`, `default_window`); the seasons and their filings by Rule B (`select_seasons` → `Seasons` of `Season` and `Dated`, the pending and `Skipped` filings, `truncated`; `NoPeriodicFilings`), and Rule B for any dated item (`rule_b`, `Seasons.place`, `PENDING`). |
| `script/documents.py` | One ticker's `raw/` tree read into its listed seasons and their documents (`season_documents` → `RawState` of `SeasonFiles` and `FilingFiles`), every raw file it reads validated and each invalid one, moved one or former-layout folder listed with its reason, and what `fetch` no longer writes left out as unlisted (`RETIRED_PREFIX`, `RETIRED_FORMS`); the newest calls capture (`Capture`), each call placed by Rule B, each season's call (`CallState`: `transcript`, `missing`, `unavailable`, `waiting`; `due_date`, `CALL_WAIT`), the pending and unlisted calls, and when the list is due again (`RawState.events_due`); the names (`season_folder`, `filing_folder`, `doc_id`, `call_doc_id`, `calls_name`, `transcript_name`, `Document.text_name`), the sentence rule's mode (`layout_mode`) and each document's derived text (`derive_text`, `derive_call`). |
| `script/text.py` | Pure: derived text of HTML and plain text (a Latin-1 filing or exhibit read as windows-1252); `normalise` and `locate`; the rule `sentence_bounded` (sentence rule v2: `SENTENCE_ENDS`, `CLOSERS`, `OPENERS`, `BULLETS`; layout or block mode). |
| `script/aspects.py` | Pure data: the aspects (`ASPECTS`, `Aspect`), the comparisons of a season (`comparisons`, `comparison`, `Comparison`, `Kind`, `KINDS`) and `BASELINE_SEASONS`. |
| `script/sheet.py` | Pure: a season's sheet, `season.md` (`season_sheet`, `SHEET`), each comparison's baseline documents (`baseline_documents`) and the call's line (`call_line`). |
| `script/readings.py` | Pure: the readings grammar (`parse_readings`, `readings_name`), the rules each item keeps (`readings_problems`, R0 to R7, with `Source` and `Comparison` giving what they need) and the wording rule (`WORDING`). |
| `script/report.py` | Pure: a comparison's report in Markdown (`render_report`), its file names (`report_name`, `report_files`, `newest_report`) and its freshness (`same_report`). |
| `data/` | Runtime files (below); ignored by Git except `data/.gitignore`. |

## Runtime files

All paths are relative to this domain and ignored by `data/.gitignore`. `{T}` is the ticker,
`{PERIOD}` a season's period end (`YYYY-MM-DD`), `{KIND}` a comparison's kind (`quarter`,
`year`).

| Path | Writer | Content |
| --- | --- | --- |
| `data/raw/{T}/submissions_{TOKEN}.json` | `fetch` | EDGAR's submissions JSON, written only when its bytes differ from the newest such file's. The newest one lists the seasons on every read; older ones are never read. |
| `data/raw/{T}/calls_{TOKEN}_{PAGE}.json` | `fetch` | One page of the ticker's earnings calls as EarningsCalls.dev served it, verbatim; the pages of one request share `TOKEN`, the New York time page 1 arrived, and every request writes its pages, so the newest capture's time is when the provider last showed its list. Only the newest capture is read. |
| `data/raw/{T}/{PERIOD}/{FORM}_{DATE}_{ACCESSION}/{DOCUMENT}` | `fetch` | A filing's documents as EDGAR served them, in the season Rule B placed it in: `FORM` the form (`10-K`, `10-Q`, `8-K`), `DATE` the date the filing is placed by (the period end for the season's own 10-K or 10-Q), `DOCUMENT` the archive's file name: a 10-K's or 10-Q's primary document; an 8-K's index page `{ACCESSION}-index.htm`, primary document and EX-99 exhibits. |
| `data/raw/{T}/{PERIOD}/transcript_{ID}.json`, `transcript_{ID}_{TOKEN}.json` | `fetch` | The transcript of the call `ID` placed in the season, as EarningsCalls.dev served it (`GET /transcripts/{ID}/components`), verbatim: `transcript_{ID}.json`, written once, then from `fetch --refresh` each copy whose bytes differ from the newest one's, named by the New York time it arrived. The newest copy is read (the one without a token is the oldest). A transcript of a call the newest capture does not list is unlisted: left out, never invalid. |
| `data/formatted/{T}/{PERIOD}/{DOC_ID}.md` | `derive` | A document's derived text, UTF-8, what the bot reads and quotes. Rewritten when its derivation differs or the file cannot be read. |
| `data/formatted/{T}/{PERIOD}/season.md` | `derive` | The season's sheet: its comparisons, filings and inputs for the bot (Derived text and the season's sheet). |
| `data/reports/{T}/{PERIOD}/readings_{KIND}.md` | the bot | The readings of the season's comparison of `KIND` (The readings). |
| `data/reports/{T}/{PERIOD}/report_{KIND}_{TOKEN}.md` | `render` | The report of the season's comparison of `KIND`. |

`DOC_ID` names a document's text file and is how a reading cites it. An EDGAR document's is
its folder name, `_` and its file name without the extension
(`10-Q_2026-06-27_0000050863-26-000157_intc-20260627`,
`8-K_2026-07-23_0000050863-26-000155_q226earningsrelease`); a call's is `call_{PERIOD}_{ID}`
(`call_2026-06-27_248001`). An index page and a calls list have no `DOC_ID`. Two documents
whose `DOC_ID`s collide, letter case aside, make the later one invalid. A file or folder of
`raw/{T}/` or of a season folder named otherwise than above is invalid, but for a name ending in
`.rejected`, a season folder older than the oldest listed season, a filing folder or transcript
the newest listing does not hold, the company facts and the folders of the forms no longer read
(all unlisted), and the former layout's `edgar/` and `calls/`. `{TOKEN}` is the New York time of
the command that wrote the file, to the second, with its zone (`20261008T025725EDT`); a name
whose token is after the command's clock is ignored.

## Formats verified live

- EDGAR's bodies are read as a strict subset of their documented or verified layout:
  `company_tickers.json`, the submissions JSON's `filings.recent` (`filings.RECENT_COLUMNS`)
  and the filing index page. Every value read must have its type and grammar, other keys or
  elements are ignored, and repeated keys, `NaN` and `Infinity` are refused. When EDGAR changes
  a field or a layout, `fetch` fails loudly with one line naming the field or element and the
  rule, never a value read, and writes nothing of that body; a body in `raw/` is read again on
  every read, so a reader change that refuses it makes it an invalid file, never silently.
- Intel's `filings.recent` on 2026-10-23 (1,000 rows, back to 2019-03): 617 Form `4`, 123
  `8-K` (items 9.01 ×96, 7.01 ×52, 5.02 ×43, 2.02 ×31, 8.01 ×25, 1.01 ×9, 5.07 ×8, 3.02 ×5,
  2.01 ×3, 2.05 ×3, 5.03 ×2), 23 `10-Q`, 7 `10-K`, 8 `DEF 14A`, 19 `DEFA14A`, 17 `SC 13G/A` and
  3 `SCHEDULE 13G/A`, 5 `SC 13G`, 4 `S-3ASR`, 18 `424B5`, 3 `8-K/A` and 3 `4/A`: of these the
  domain reads the 10-Ks, 10-Qs and 8-Ks and lists the registrations, prospectuses and
  amendments. Every row has `acceptanceDateTime`, a UTC time written
  `YYYY-MM-DDTHH:MM:SS.000Z` (the Item 2.02 8-K of 2026-07-23 was accepted at
  `2026-07-23T20:09:00.000Z`, 16:09 New York time); a filing accepted after 17:30 New York time
  carries the next business day's `filingDate` (the 10-Q accepted at
  `2026-07-23T22:44:23.000Z` was filed 2026-07-24).
- An 8-K's filing index page, verified on Intel's 8-K 0000050863-26-000155: exactly one
  `<table class="tableFile" summary="Document Format Files">`, closed by its own `</table>`
  and holding no other table, whose first row's cells are Seq, Description, Document, Type and
  Size and whose other rows have five cells; an exhibit row's Document cell links only to its
  document in the filing's folder, directly or through EDGAR's `/ix?doc=` viewer, and its Type
  is `EX-99` alone or `EX-99.` and 1 to 16 letters, digits or dots. An 8-K's primary document
  with Item 5.02 is about 25 KB.
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
