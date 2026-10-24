# Fundamentals: six aspects of each season against its baseline

This procedure compares, for each stock of the watchlist (or the tickers given) and each
season whose end lies in a window of dates, the season with its baseline over six aspects, in
one comparison per kind that applies to it (the quarter against the season before, and for a
10-K season the year against the previous 10-K season), and renders one report per comparison.
The model of seasons and calls, the aspects and the comparisons, the quote rules, the readings'
grammar and rules, the reports, the sources and the file layout are in [AGENTS.md](AGENTS.md).

Run every command from the repository root with Python 3.13+ and locked dependencies:

```sh
uv run --locked python -m market_state_research.fundamentals.script COMMAND ...
```

A run: `fetch` with the window (section 2), then `plan` with the same window (section 3),
whose `action` names the next step: `fetch` again, `derive` (section 4), `research` (section
5) or `render` (section 6). Repeat `plan` until it says `reuse` or the work cannot go on, then
`show` and report back (section 6). Run `fetch` first in every run, at least once a day while
a season's call is `waiting`: `plan` works offline and cannot see what EDGAR or the transcript
provider published since.

## 1. Parameters

| Parameter | Default | Meaning |
| --- | --- | --- |
| Ticker | `fetch`, `plan`, `show`: the tickers of the watchlist | The exact symbol: any number for `fetch`, `plan` and `show` (by default the tickers of the watchlist, in file order), one for the other commands. |
| `--watchlist PATH` | this domain's `watchlist.json`, which you maintain ([market_state_research/AGENTS.md](../AGENTS.md), Watchlists) | `fetch`, `plan` and `show` only: the watchlist read when no ticker is given, which `fetch` and `plan` print as `watchlist` (null when tickers are given). One that is missing, malformed or without a ticker stops the command with one line naming the file: write or correct the file with the tickers the user follows, report the change and run the command again. |
| `--from YYYY-MM-DD` | the same day two years before `--to` (29 February: 28 February) | `fetch` and `plan` only: the earliest season end in the window, a New York date in ASCII digits; refused when it is after `--to`. |
| `--to YYYY-MM-DD` | today's New York date | `fetch` and `plan` only: the latest season end in the window; refused when it is after today. |
| `--refresh` | off | `fetch` and `plan` only: request the span's EDGAR documents, transcripts and calls list again, whatever `raw/` holds (section 2); `plan` then says `fetch`. Use it only when the user asks, on one `fetch`, and plan afterwards without it: one EDGAR request per span document and one EarningsCalls.dev request per transcript, plus the calls list. |
| `--data-dir PATH` | this domain's `data/` | Another data directory, for offline checks; every command takes it. |

Both window dates are included and bound season ends, not filing dates; `fetch` also writes
the four seasons before the window, the baselines of its comparisons. Give `plan` the same
window as `fetch`. The other commands take no window. A long window yields many reports: one
per season, two for each 10-K season.

**Settings.** `fetch` reads two lines of the repository-root `.env` (the process environment
takes precedence); no other command reads a setting. Never print or repeat a value, and write
it nowhere but where it is used.

- `SEC_USER_AGENT` tells EDGAR whom `fetch`'s requests are made for: a name, a space and an
  email address, printable ASCII, at most 200 characters, such as
  `SEC_USER_AGENT="Name contact@example.com"`. When it is missing or malformed, ask the user
  for the name and contact address to use and, with their agreement, add the line to `.env`.
- `EARNINGSCALLS_API` is the user's own EarningsCalls.dev key: printable ASCII without spaces,
  at most 200 characters, as `EARNINGSCALLS_API="..."`. Its plan allows 3,000 requests a month
  and 20 a minute; `fetch` asks for a ticker's calls list only when it is due and for each
  transcript once, unless `--refresh` asks again, so filling the default window and the four
  seasons before it takes about 15 requests per ticker, and keeping it current a few a month.
  When the key is missing or malformed, ask the user to add or correct the line themselves;
  never ask for the key in the conversation or open an account.

**Limits.** An item's title: 1 to 120 characters; a value or a difference: 1 to 600 characters
on one line; a quote: 20 to 800 characters after normalisation.

## 2. Fetch: write the span's documents into `raw/`

```sh
uv run --locked python -m market_state_research.fundamentals.script fetch
uv run --locked python -m market_state_research.fundamentals.script fetch INTC --from 2025-01-01 --to 2026-10-09
```

It writes the submissions JSON when it changed, each EDGAR document of a span season that is
not in `raw/` yet (the 10-K or 10-Q and each 8-K's index page, primary document and EX-99
exhibits), the ticker's calls list when it is due and each span call's transcript that is not
in `raw/` yet; it writes no text. A ticker's first fetch of the default window takes about 100
EDGAR requests, half a minute or more. It prints `requests` (EDGAR), `user_agent: "set"`,
`transcript_requests` (EarningsCalls.dev), `api_key: "set"`, `window`, `refresh`, `stopped` and
an entry per ticker under `tickers`; act on these:

| Field | Meaning |
| --- | --- |
| `status`, `reason` | `fetched`, or `unsupported` with the reason (EDGAR does not list the ticker, no 10-K or 10-Q, two filings for one period, an Item 2.02 8-K without a usable event date): report it and stop for that ticker; the others go on. |
| `submissions` | With `path` and `status`: `new` (written now) or `reused` (the same bytes as the newest file, which `path` names). |
| `truncated`, `pending_filings[]`, `skipped_filings[]` | Report them: `truncated: true` means seasons before the oldest recent filing are not read; a pending filing (with its `form`, `accession`, `dated`, `filed`, `items`) may later join a season already read; a skipped filing (with its `reason`) is never fetched. |
| `seasons[]` | Per span season, oldest first: `season`, `in_window`, its `filing` (`form`, `accession`, `filed`, `period`, `doc_id`, `path`, `status`) and its `filings[]`, the 8-Ks (`form`, `accession`, `dated`, `filed`, `items` and `files[]`, each with `path`, `doc_id`, null for an index page, and `status`). A status is `new` (written now) or `reused` (already in `raw/`, not requested); with `--refresh`, `verified` (requested again: the same bytes) or `changed` (EDGAR now serves other bytes, and nothing was written: replace the stored file only when the user asks, by renaming it `.rejected` and running `fetch` again). |
| `calls` | `status`: `fetched`; `unsupported` with the `reason` (the provider's symbol names several issuers): report it and stop for that ticker's calls; or `stopped` with the `reason` (below). `events`: the calls list kept, with its `path`, `pages`, `fetched_at`, `status` (`new`, asked for now with the `reason` it was due, or `reused`); null when none is in `raw/`. `transcripts[]`: each span call's `id`, `date`, `fiscal_year`, `fiscal_quarter`, `season`, `doc_id`, `path` and `status` (`new` or `reused`; with `--refresh`, `verified`, or `refreshed`: the provider served other bytes, now written beside the stored copy at `path`, the copy every later read takes). `pending_calls[]`: calls dated after the newest season's filing. |
| `stopped` | Null, or the `ticker` and `reason` where EarningsCalls.dev's request limit stopped every later request to it in this run (exit 0): the later tickers' EDGAR files were still fetched, and their `calls.status` is `stopped`. Report it with the reset the line names, and run `fetch` again only after it. |

A failed request or a body that does not read aborts the run with one `FUNDAMENTALS:` line;
nothing of that document is written, and what was written before stays. Run `fetch` again
once the cause is gone, never in a loop.

## 3. Plan: decide what comes next

```sh
uv run --locked python -m market_state_research.fundamentals.script plan
uv run --locked python -m market_state_research.fundamentals.script plan INTC --from 2025-01-01 --to 2026-10-09
```

`plan` is read-only and never fails for a ticker without raw files. It prints
`generated_at`, `window`, `refresh` and an entry per ticker under `tickers`; act on these
fields:

| Field | Meaning |
| --- | --- |
| `action`, `reason` | What to do next (table below) and why (`reason` is null for `reuse`). |
| `cik`, `entity_name`, `submissions` | The issuer and the newest submissions file read. |
| `truncated`, `pending_filings[]`, `skipped_filings[]` | As in `fetch`. |
| `former_layout[]` | Folders of the layout before 2026-10-23 (section 7). |
| `invalid_files[]` | Raw files that failed validation, a moved filing or transcript included, each with `path` and `reason`. |
| `unlisted_files[]` | Filing folders and transcripts the newest listing does not hold, and what `fetch` wrote until 2026-10-24 and no longer writes (section 7): left out (report them). |
| `calls` | `events`: the newest calls list in `raw/` (`path`, `pages`, `fetched_at`), null when none is valid; `due`: why `fetch` asks for the list again now, or null; `pending_calls[]`. |
| `seasons[]` | Per span season, oldest first: `season`, `in_window`; `filing` and `filings[]`, each with `raw` (true once its files are in `raw/` and valid), and `listed_only[]`, the season's filings nothing fetches; `documents`: `complete`, or what is missing; `call` with `status` (`transcript`, `unavailable`, `waiting` or `missing`: AGENTS.md, Seasons, filings and calls), `due`, `as_of`, `calls[]`, `documents` (their `DOC_ID`s) and `reason`; `texts` (`documents`, the count, and `stale`, the `DOC_ID`s whose text is missing or differs). A window season also has `sheet` (`path` of its `season.md`; `status` `fresh`, `stale` or `missing`) and `comparisons[]`, one per comparison of the season: `kind` (`quarter`, `year`), `baseline` (its `season` and `form`, null when none is listed), `readings` (`path`, where they are or go; `status` `valid`, `failing` or `missing`; the number of `problems`; `unnamed_documents`, the season's `DOC_ID`s no line of the readings names, null without readings) and `report` (the newest report's `path`; `status` `fresh`, `stale` or `missing`). |
| `stray_files[]`, `stray_reports[]` | Files directly in `formatted/{T}/` and `reports/{T}/`, from the former layout (section 7). |

The first action that applies:

| `action` | When | Next step |
| --- | --- | --- |
| `fetch` | A former-layout folder is in `raw/`; no season is listed; a span season's 10-K, 10-Q or 8-K is not in `raw/`; a raw file is invalid; a span season's call is `missing`; or the calls list is due (`calls.due`; with `--refresh`, whenever the window holds a listed season). | Rename each `former_layout` and `invalid_files` entry with `.rejected`, if any, then run `fetch` with the same window (and `--refresh`, when `plan` had it). When `reason` refuses the submissions (`no 10-K or 10-Q …`, two filings for one period, an 8-K's event date) or `fetch` reported the ticker or its calls `unsupported`, report it and stop for that ticker. |
| `derive` | A span document's text is missing or differs, or a window season's `season.md` is missing or out of date. | Run `derive` (section 4). |
| `research` | The `readings.status` of a window comparison is not `valid`. | Read the season and its baselines (section 4), then write and check the readings (section 5). |
| `render` | Every window comparison's readings pass, and one's newest report is not the report rendered now. | Run `render` (section 6). |
| `reuse` | Every window comparison's newest report is the report rendered now. | Run `show` and report back (section 6). When `seasons` is empty, tell the user the window holds no season end. |

A `waiting` or `unavailable` call blocks no action: the season is read without its call until a
later `fetch` brings the transcript, which makes its sheet and reports stale and its call a
document the readings do not name yet (`unnamed_documents`).

## 4. Derive the texts and sheets, and read the season

```sh
uv run --locked python -m market_state_research.fundamentals.script derive INTC
```

`derive` writes the derived text of every document of every listed season in `raw/` and the
`season.md` of every listed season, whatever the window: each missing file, one that cannot be
read and one that differs from its derivation. It prints `ticker`, `documents[]` (each with
`doc_id`, `season`, `kind`, `path` and `status`: `published`, `exists` or `rewritten`),
`sheets[]` (each with `season`, `path` and `status`), `stray_files[]` and `stray_reports[]`
(section 7).

Read a season from its sheet, `data/formatted/{T}/{PERIOD}/season.md` (AGENTS.md, Derived text
and the season's sheet): its call line, its `## Comparisons` table (per comparison, the
baseline season and the `DOC_ID`s of its documents, the ones a `baseline:` line names), its
filings and its inputs (the season's documents by what they are). Each document's text is at
`data/formatted/{T}/{PERIOD}/{DOC_ID}.md`, a baseline season's in that season's folder. A
call's text holds, per turn, a heading line with the speaker's name and role as the provider
gives them (`David Zinsner (executive)`, `Jane Analyst (analyst)`, `Operator (operator)`), then
the turn's paragraphs, one per line; the prepared remarks are the turns before the first
analyst's, the questions and answers the turns from it on. A `.txt` document's line is not a
statement (AGENTS.md, Quotes): read the whole sentence around every line you find.

Read every document of the season and of the comparison's baseline season, whole, for each
aspect (AGENTS.md, The aspects and the comparisons), in this order: the 10-K or 10-Q, then the
8-Ks by date (an earnings release's exhibits with them), then the call. Where to look first:

| Aspect | Where to read |
| --- | --- |
| Guidance | The outlook of each earnings release (often a table of ranges and points) and of its call; for a quarter, the results of the quarter in the season's release against the guidance the baseline's release and call gave for it. |
| Capital expenditure | The release's capital spending lines (gross, net of partners' contributions), the filing's liquidity section and cash flow statement, the projects the filing and the call name (fabs, plants, equipment) and their timing. |
| Upstream supply | The filing's risk factors and its discussion of operations (suppliers, components, materials, capacity, lead times, prices), the inventory note, the release's and the call's statements on supply. |
| Downstream demand | The release's and the call's statements on demand, orders, backlog, bookings and pricing; the filing's revenue discussion, its customers' inventory and its concentration of revenue (a 10-K's major customers note). |
| Debt structure | The filing's debt note and liquidity section (notes, rates, maturities, credit facilities, commercial paper, covenants), the 8-Ks with Items 1.01 and 2.03, and the registrations and prospectuses the sheet lists; the interest expense the filing states. |
| Product roadmap | The release's business highlights, the filing's discussion of products and technologies, and the call's statements on products, process nodes, launches, ramps and delays. |

These searches find candidate lines; a hit is not a reading, and a statement may belong to an
aspect without any of these words:

```sh
grep -n -i -E "outlook|guidance|expect|forecast|range|approximately|full year|full-year|next quarter|reaffirm|withdraw" \
  market_state_research/fundamentals/data/formatted/INTC/2026-06-27/DOC_ID.md
grep -n -i -E "capital expenditure|capital spending|capital investment|capex|construction|fab|factory|facilit|equipment" \
  market_state_research/fundamentals/data/formatted/INTC/2026-06-27/DOC_ID.md
grep -n -i -E "supplier|supply|substrate|wafer|component|material|capacity|lead time|shortage|constrain|inventor" \
  market_state_research/fundamentals/data/formatted/INTC/2026-06-27/DOC_ID.md
grep -n -i -E "demand|customer|order|backlog|booking|pricing|price|end market|concentration|percent of revenue" \
  market_state_research/fundamentals/data/formatted/INTC/2026-06-27/DOC_ID.md
grep -n -i -E "notes due|senior notes|debt|loan|credit facilit|commercial paper|covenant|borrow|refinanc|repay|interest expense" \
  market_state_research/fundamentals/data/formatted/INTC/2026-06-27/DOC_ID.md
grep -n -i -E "launch|ramp|roadmap|process node|node|introduc|milestone|delay|discontinu|next-generation|product" \
  market_state_research/fundamentals/data/formatted/INTC/2026-06-27/DOC_ID.md
```

## 5. Write and check the readings

### 5.1 Which readings, and where

1. Write the readings of each window comparison whose `readings.status` is `missing`, and fix
   those that are `failing`, each from the documents of the season and of its comparison's
   baseline season alone. Never rewrite passing readings unless an aspect changed after they
   were written (AGENTS.md, The aspects and the comparisons), or a document their
   `unnamed_documents` lists (a call transcript that arrived later, say) states items they
   lack.
2. Write them at the comparison's `plan` `readings.path`,
   `data/reports/{T}/{PERIOD}/readings_{KIND}.md`, in the grammar of AGENTS.md (The readings):
   the title, then the six aspects, in order, each `na` or its items. A 10-Q season has one
   file, `readings_quarter.md`. A 10-K season has two: `readings_quarter.md`, the fourth
   quarter's items against the documents of the third quarter's season, and `readings_year.md`,
   the fiscal year's items against those of the previous 10-K season. Rewrite them until
   `check` passes them (5.3).

### 5.2 Each item

- One item per subject: a guided measure for one period, a capital project, an input, a
  customer or end market, a note or facility, a product or process node. Statements on one
  subject in several documents of either side are one item with several quotes; statements on
  different subjects are different items. List every item you find, in the order its first
  statement comes in the documents (5.1), the items only the baseline states last; title each
  with the subject in your own words (`Full-year revenue guidance, fiscal year`), facts only.
- `season:` the `DOC_ID`s of the season's documents the new value rests on, joined by `; `;
  `baseline:` those of the baseline season's documents the old value rests on, from the
  comparison's row of the sheet's `## Comparisons`; `none` beside a value that is `na` or
  `no baseline`.
- `new:` the value as the season's documents state it and `old:` the same value as the
  baseline's documents state it, each one line of facts that names its period, its basis and
  its unit (`old: fiscal 2025 revenue $50.0 to $54.0 billion, GAAP` and `new: fiscal 2026
  revenue $52.0 to $56.0 billion, GAAP`), written alike on both lines so that the two read side
  by side; `na` when the documents of that side state nothing of the item, and `no baseline`
  as the old value when the comparison's `baseline` is null or the sheet lists none of its
  documents. State both values whatever the size of the change, and never a judgment, a cause
  the documents do not state, or valuation, forecast or advice wording. An item no side states
  is no item: an aspect whose documents state nothing of it is the line `na`.
- `difference:` the difference between the two values in facts (`$2.0 billion higher at both
  ends of the range`, `a point of approximately $9 billion in place of a range of $8.0 to
  $11.0 billion`); `none` when the two values are written alike; `na` beside a value that is
  `na` or `no baseline`. Compute nothing the documents do not state but the arithmetic between
  the two values as written.
- Quotes: the statements each value rests on, each followed by its attribution line,
  `— DOC_ID` or, for a call, `— DOC_ID, Speaker (role)` as the turn's heading writes it. Quote
  every document a `season:` or `baseline:` line names at least once, and only those. Which
  statements to quote, that a quote is a whole statement copied verbatim from the derived text,
  the whole statements `check` refuses and the cuts it cannot see, and the length limits are
  the quote rules (AGENTS.md, Quotes).

### 5.3 Check

```sh
uv run --locked python -m market_state_research.fundamentals.script check INTC
uv run --locked python -m market_state_research.fundamentals.script check INTC \
  market_state_research/fundamentals/data/reports/INTC/2026-06-27/draft.md
```

`check` writes nothing. Without a path it checks every readings file of every listed season
that has one; a path names a draft, which lies in its season's folder
(`data/reports/{T}/{PERIOD}/`, any name) and is read as the comparison its title names. It
prints `ticker` and `readings[]`, each with `path`, `season`, `kind`, `valid` and
`problems[]` (each with its `line` and `message`), and exits 0 even with problems: fix what
each message names and check again until every window comparison's readings are `valid`.
Readings also fail while a document they name has a text file that is missing or differs from
the derivation: run `derive`, then copy again every quote the new text no longer holds. Never
change a text file to make a quote match.

## 6. Render, show and report back

```sh
uv run --locked python -m market_state_research.fundamentals.script render INTC
uv run --locked python -m market_state_research.fundamentals.script show
uv run --locked python -m market_state_research.fundamentals.script plan
```

`render` writes a new report, `data/reports/{T}/{PERIOD}/report_{KIND}_{TOKEN}.md`, for every
comparison whose readings pass and whose newest report is not current, and prints `ticker`,
`reports[]` (each with `season`, `kind` and `path`), `current[]` (each `season` and `kind` whose
newest report is current) and `skipped[]` (each with `season`, `kind` and the `reason` its
report cannot be rendered). `show` writes nothing: per ticker it prints the action `plan` gives
over the default window, the newest season one of whose reports can be rendered now with each
of its newest reports' path and freshness, and those reports rendered now (or `No season report
can be rendered now.`).

The final `plan`, with the tickers and the window of the run's first `plan`, must show `reuse`
for every supported ticker. A ticker that `fetch` reported `unsupported` (EDGAR does not list
it, its submissions are refused, or the provider's symbol is ambiguous) stays at `fetch`:
report it with `fetch`'s reason. One left at `fetch` because `fetch` stopped at the provider's
request limit: report it with the `stopped` line.

Report for each ticker: each window comparison's newest report path as a link (the report lists
every item of each aspect with its new and old values and their difference: point to it rather
than picking items from it); the window, whether it is `truncated`, any `pending_filings`,
`skipped_filings` and `pending_calls`, each season whose call is `waiting` (with its `reason`)
or `unavailable` (with its `as_of`), and each comparison with `unnamed_documents`; unsupported
tickers and calls with their reason, `stopped`, `invalid_files`, `unlisted_files`, the documents
`fetch --refresh` found `changed` and the transcripts it `refreshed`, files renamed `.rejected`
with their messages, and the `stray_reports` left in place. Never add a judgment, a cause or a
summary the report does not state: point to the reports. What blocks you or looks wrong in a
rule, a message or a tool goes into a GitHub issue (the root [AGENTS.md](../../AGENTS.md),
Feedback), never into the rule.

## 7. The former layout

A data directory fetched before 2026-10-23 holds `raw/{T}/edgar/` and `raw/{T}/calls/`, derived
texts directly in `formatted/{T}/` and per-document reports and time series directly in
`reports/{T}/`. `plan` lists the two raw folders as `former_layout` and says `fetch`, and
`derive`, `check` and `render` refuse while they are there: rename each with `.rejected`
(`raw/INTC/edgar.rejected`), then run `fetch` with the window, which writes the span again in
seasons. `derive` and `plan` list the old texts as `stray_files`: delete them, since no
command reads them. The old reports are `stray_reports`: leave them where they are and name
them in the report back.

A data directory fetched from 2026-10-23 to 2026-10-24 also holds the company facts
(`raw/{T}/companyfacts_{TOKEN}.json`) and, in its season folders, the folders of the Form 4s,
proxy statements and beneficial owners' schedules (`4_…`, `DEF14A_…`, `SC13GA_…`,
`SCHEDULE13GA_…` …): `plan` lists them as `unlisted_files`, and they block nothing. A season
folder may hold that catalogue's `measures.md`, `readings.md` and `report_{TOKEN}.md`: no
command reads them; leave them in place.

## Failure handling

Every failure exits 2 with one `FUNDAMENTALS:` line on standard error; exit 0 means success,
including a `check` that lists problems, a `plan` or `fetch` that leaves work to do, a ticker
or its calls reported `unsupported` and a `fetch` that the provider's request limit stopped. A
usage error (`… invalid choice: …`, `… unrecognized arguments: …`, `… expected a YYYY-MM-DD
date, got '…'`) did nothing: run the command again with valid arguments. Any other message,
`reason`, `invalid_files` entry or `problems[]` message says what to do: do it, or report it
verbatim. Never weaken validation; withdraw a raw file by renaming it `.rejected`. These need
more:

| Message | Action |
| --- | --- |
| `INTC: N files in raw/ failed validation; first: PATH: REASON; run plan for the list and rename each with .rejected` (`derive`, `check`, `render`) | Read `plan`'s `invalid_files`, rename each entry with `.rejected`, then run `fetch`. |
| `… the newest submissions place this filing in …, not in this season; rename it with .rejected and run fetch` (an `invalid_files` reason) | EDGAR listed a season out of order: rename the folder with `.rejected`, then run `fetch`, which writes the filing in its season. |
| `INTC: PATH is the former layout (until 2026-10-23): rename it with .rejected, then run fetch` | Section 7. |
| `SEC_USER_AGENT is not set; …` or `SEC_USER_AGENT must be a name and an email address, …` | Nothing was sent: section 1, then run `fetch` again. |
| `EARNINGSCALLS_API is not set; add EARNINGSCALLS_API="..." to the repository-root .env` or `EARNINGSCALLS_API must be printable ASCII without spaces` | Nothing was sent: ask the user to add or correct the line (section 1), then run `fetch` again. |
| `…: HTTP 401 …; EarningsCalls.dev refused the key: check EARNINGSCALLS_API` | The key is wrong or revoked: ask the user to check it, and run `fetch` again only once they have. |
| `…: HTTP 403 …; EarningsCalls.dev refused the request: the key's plan does not include it …` | Tell the user their EarningsCalls.dev plan does not cover full transcripts, and stop the calls until they say so. |
| `…: HTTP 404 …; EarningsCalls.dev serves nothing at this address` | The provider lists a call whose transcript it does not serve: run `fetch` once more after a day; when it fails the same way, report the line and stop for that ticker. |
| `stopped` in `fetch`'s output (`…: HTTP 429; EarningsCalls.dev's request limit is reached …; run fetch again once it resets`) | Report it with the reset date the line names; run `fetch` again only after it. EDGAR's files of every ticker were still fetched. |
| `…; EarningsCalls.dev is unavailable: wait and run fetch again`, `…; EDGAR is unavailable: …`, `…; EDGAR's rate limit: …` or `…: the body ended after N of M bytes; run fetch again` | Wait some minutes (ten for EDGAR's rate limit), then run `fetch` once more. When it fails the same way again, report it and stop for that ticker. |
| `calls.status: unsupported` (`EarningsCalls.dev lists N issuers for T (ambiguous): their calls cannot be told apart`) | Report it; the ticker's seasons are read without their calls. |
| `GET URL: calls list …`, `GET URL: transcript: …` | The provider's format changed and nothing of that body was written. Report the line and open an issue with it. |
| `filing index ACC: …` (`fetch`) | EDGAR changed the index page layout and nothing of the 8-K was written, or, when a `PATH` comes first, an index page in `raw/` no longer parses (do what the line says). Report the line and open an issue with it. |
| `INTC: no season has readings; run plan` or `INTC: no report to write: PERIOD KIND: REASON` (`render`) | Not an error to report: do what `plan` says; the reason names what the comparison lacks. |
| `PATH: a readings draft lies in its season's folder, named YYYY-MM-DD` (`check`) | Move the draft into `data/reports/{T}/{PERIOD}/` and check it there. |
| `only a 10-K season has year readings: …` | A 10-Q season has the quarter comparison alone: write its items in `readings_quarter.md`, titled `quarter readings`. |
| `'no baseline' while the baseline is in raw/: DOC_ID; …` | Read those documents and give the item its old value, or `na`. |
| `DOC_ID is no document of the season PERIOD` or `DOC_ID is no document of the baseline season PERIOD` | Name on `season:` only the season's documents and on `baseline:` only those the sheet's `## Comparisons` row of the comparison lists. |
| `DOC_ID is named on this line but quoted nowhere in this item` | Quote the statement of that document the value rests on, or take the document off the line. |
| `a quote must be whole sentences, …` | The quote cuts a statement: quote it from its start to its end (AGENTS.md, Quotes). |
| `a call's quote names its turn: '— DOC_ID, Speaker (role)', …` or `the quote lies in the turn 'HEADING', not the one its attribution names` | Attribute the quote to the turn its first occurrence lies in, exactly as that turn's heading line writes it. |
| `an item's title, values and difference state facts only, without valuation, forecast or advice wording; found: …` | Restate them as the facts alone, without that word. |
