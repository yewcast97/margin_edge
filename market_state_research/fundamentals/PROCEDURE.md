# Fundamentals: season reports of what changed against the baselines

This procedure compares, for each stock of the watchlist (or the tickers given) and each
season whose end lies in a window of dates, the season with its baselines over the catalogue
of items, and renders one report per season. The model of seasons and calls, the items, the
quote rules, the readings' grammar and rules, the report, the sources and the file layout are
in [AGENTS.md](AGENTS.md).

Run every command from the repository root with Python 3.13+ and locked dependencies:

```sh
uv run --locked python -m market_state_research.fundamentals.script COMMAND ...
```

A run: `fetch` with the window (section 2), then `plan` with the same window (section 3),
whose `action` names the next step: `fetch` again, `derive` (section 4), `research` (section
5) or `render` (section 6). Repeat `plan` until it says `reuse` or the work cannot go on, then
`show` and report back (section 6). Run `fetch` first in every run, at least once a day while
a season's call or company facts are `waiting`: `plan` works offline and cannot see what EDGAR
or the transcript provider published since.

## 1. Parameters

| Parameter | Default | Meaning |
| --- | --- | --- |
| Ticker | `fetch`, `plan`, `show`: the tickers of the watchlist | The exact symbol: any number for `fetch`, `plan` and `show` (by default the tickers of the watchlist, in file order), one for the other commands. |
| `--watchlist PATH` | this domain's `watchlist.json`, which you maintain ([market_state_research/AGENTS.md](../AGENTS.md), Watchlists) | `fetch`, `plan` and `show` only: the watchlist read when no ticker is given, which `fetch` and `plan` print as `watchlist` (null when tickers are given). One that is missing, malformed or without a ticker stops the command with one line naming the file: write or correct the file with the tickers the user follows, report the change and run the command again. |
| `--from YYYY-MM-DD` | the same day two years before `--to` (29 February: 28 February) | `fetch` and `plan` only: the earliest season end in the window, a New York date in ASCII digits; refused when it is after `--to`. |
| `--to YYYY-MM-DD` | today's New York date | `fetch` and `plan` only: the latest season end in the window; refused when it is after today. |
| `--refresh` | off | `fetch` and `plan` only: request the span's EDGAR documents, company facts, transcripts and calls list again, whatever `raw/` holds (section 2); `plan` then says `fetch`. Use it only when the user asks, on one `fetch`, and plan afterwards without it: one EDGAR request per span document and one EarningsCalls.dev request per transcript, plus the calls list. |
| `--data-dir PATH` | this domain's `data/` | Another data directory, for offline checks; every command takes it. |

Both window dates are included and bound season ends, not filing dates; `fetch` also writes
the four seasons before the window, which its readings compare with. Give `plan` the same
window as `fetch`. The other commands take no window.

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

**Limits.** An observation: 1 to 600 characters on one line; a quote: 20 to 800 characters
after normalisation.

## 2. Fetch: write the span's documents into `raw/`

```sh
uv run --locked python -m market_state_research.fundamentals.script fetch
uv run --locked python -m market_state_research.fundamentals.script fetch INTC --from 2025-01-01 --to 2026-10-09
```

It writes the submissions JSON and the company facts when they changed, each EDGAR document
of a span season that is not in `raw/` yet, the ticker's calls list when it is due and each
span call's transcript that is not in `raw/` yet; it writes no text. A ticker's first fetch
of the default window takes about 300 EDGAR requests, a minute or more. It prints `requests`
(EDGAR), `user_agent: "set"`, `transcript_requests` (EarningsCalls.dev), `api_key: "set"`,
`window`, `refresh`, `stopped` and an entry per ticker under `tickers`; act on these:

| Field | Meaning |
| --- | --- |
| `status`, `reason` | `fetched`, or `unsupported` with the reason (EDGAR does not list the ticker, no 10-K or 10-Q, two filings for one period, an Item 2.02 8-K without a usable event date): report it and stop for that ticker; the others go on. |
| `submissions`, `companyfacts` | Each with `path` and `status`: `new` (written now) or `reused` (the same bytes as the newest file, which `path` names). |
| `truncated`, `pending_filings[]`, `skipped_filings[]` | Report them: `truncated: true` means seasons before the oldest recent filing are not read; a pending filing (with its `form`, `accession`, `dated`, `filed`, `items`) may later join a season already read; a skipped filing (with its `reason`) is never fetched. |
| `seasons[]` | Per span season, oldest first: `season`, `in_window`, its `filing` (`form`, `accession`, `filed`, `period`, `doc_id`, `path`, `status`) and its `filings[]` (`form`, `accession`, `dated`, `filed`, `items` and `files[]`, each with `path`, `doc_id`, null for an index page or a Form 4's XML, and `status`). A status is `new` (written now) or `reused` (already in `raw/`, not requested); with `--refresh`, `verified` (requested again: the same bytes) or `changed` (EDGAR now serves other bytes, and nothing was written: replace the stored file only when the user asks, by renaming it `.rejected` and running `fetch` again). |
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
| `cik`, `entity_name`, `submissions`, `companyfacts` | The issuer and the newest submissions and company facts files read. |
| `truncated`, `pending_filings[]`, `skipped_filings[]` | As in `fetch`. |
| `former_layout[]` | Folders of the layout before 2026-10-23 (section 7). |
| `invalid_files[]` | Raw files that failed validation, a moved filing or transcript included, each with `path` and `reason`. |
| `unlisted_files[]` | Filing folders and transcripts the newest listing does not hold: left out (report them). |
| `calls` | `events`: the newest calls list in `raw/` (`path`, `pages`, `fetched_at`), null when none is valid; `due`: why `fetch` asks for the list again now, or null; `pending_calls[]`. |
| `seasons[]` | Per span season, oldest first: `season`, `in_window`; `filing` and `filings[]`, each with `raw` (true once its files are in `raw/` and valid), and `listed_only[]`, the season's filings nothing fetches; `documents`: `complete`, or what is missing; `call` with `status` (`transcript`, `unavailable`, `waiting` or `missing`: AGENTS.md, Seasons, filings and calls), `due`, `as_of`, `calls[]`, `documents` (their `DOC_ID`s) and `reason`; `texts` (`documents`, the count, and `stale`, the `DOC_ID`s whose text is missing or differs); `companyfacts` (`status`: `present`, `waiting` or `absent`, and `reason`). A window season also has `measures` (`path`; `status` `fresh`, `stale` or `missing`), `readings` (`path`, where they are or go; `status` `valid`, `failing` or `missing`; the number of `problems`) and `report` (the newest report's `path`; `status` `fresh`, `stale` or `missing`). |
| `stray_files[]`, `stray_reports[]` | Files directly in `formatted/{T}/` and `reports/{T}/`, from the former layout (section 7). |

The first action that applies:

| `action` | When | Next step |
| --- | --- | --- |
| `fetch` | A former-layout folder is in `raw/`; no season is listed; a span season's 10-K, 10-Q or fetched filing is not in `raw/`; a raw file is invalid; no company facts are in `raw/`; a span season's call is `missing`; or the calls list is due (`calls.due`; with `--refresh`, whenever the window holds a listed season). | Rename each `former_layout` and `invalid_files` entry with `.rejected`, if any, then run `fetch` with the same window (and `--refresh`, when `plan` had it). When `reason` refuses the submissions (`no 10-K or 10-Q …`, two filings for one period, an 8-K's event date) or `fetch` reported the ticker or its calls `unsupported`, report it and stop for that ticker. |
| `derive` | A span document's text is missing or differs, or a window season's `measures.md` is missing or out of date. | Run `derive` (section 4). |
| `research` | A window season's `readings.status` is not `valid`. | Read the season (section 4), then write and check its readings (section 5). |
| `render` | Every window season's readings pass, and a window season's newest report is not the report rendered now. | Run `render` (section 6). |
| `reuse` | Every window season's newest report is the report rendered now. | Run `show` and report back (section 6). When `seasons` is empty, tell the user the window holds no season end. |

A `waiting` or `unavailable` call, and company facts `waiting` or `absent`, block no action:
the season's call items are `unavailable` and its missing figures not computable until a
later `fetch` brings them, which makes its measures and report stale.

## 4. Derive the texts and measures, and read the season

```sh
uv run --locked python -m market_state_research.fundamentals.script derive INTC
```

`derive` writes the derived text of every document of every listed season in `raw/` and the
`measures.md` of every listed season, whatever the window: each missing file, one that cannot
be read and one that differs from its derivation. It prints `ticker`, `documents[]` (each with
`doc_id`, `season`, `kind`, `path` and `status`: `published`, `exists` or `rewritten`),
`measures[]` (each with `season`, `path` and `status`), `stray_files[]` and `stray_reports[]`
(section 7).

Read a season from its `measures.md`, `data/formatted/{T}/{PERIOD}/measures.md`
(AGENTS.md, Derived text, figures and measures): its call line, its `## Baselines` table (per
baseline, the seasons and the `DOC_ID`s you read and name), its filings, its figures, the
Python items and the inputs of the bot's items. Each document's text is at
`data/formatted/{T}/{PERIOD}/{DOC_ID}.md`. A call's text holds, per turn, a heading line with
the speaker's name and role as the provider gives them (`David Zinsner (executive)`,
`Jane Analyst (analyst)`, `Operator (operator)`), then the turn's paragraphs, one per line; the
prepared remarks are the turns before the first analyst's, the questions and answers the
turns from it on. A `.txt` document's line is not a statement (AGENTS.md, Quotes): read the
whole sentence around every line you find.

Read each bot item's rule (AGENTS.md, The catalogue) and compare the season's documents with
those of the item's baseline:

| Section | Where to read |
| --- | --- |
| 1 Guidance | The outlook of the season's earnings release (often a table of ranges) and of its call, against the previous season's (the previous guidance). 1.7 holds the season's results (`measures.md`, Inputs) against the previous guidance for this quarter; 1.9 reads the 1.7 readings of the earlier seasons in `reports/{T}/`, where they exist. |
| 2 Financials | The segment note of the 10-K or 10-Q (2.7, 2.8) against the same quarter last year's or the previous quarter's; the items the issuer calls non-recurring, one-time or unusual in the release's reconciliations and the filing's MD&A (2.9). |
| 3 Accounting and audit | The 8-Ks with Items 4.01 and 4.02 (Inputs); in a 10-K, the auditor's report (opinion, critical audit matters), the impairment notes and the revenue recognition policy; in every filing, the controls and procedures item, the basis of presentation and accounting standards notes and any going concern statement; the release's non-GAAP reconciliation (3.10). |
| 4 Risk, legal and related parties | The risk factors (a 10-Q's Part II, Item 1A updates those of the 10-K) against the previous quarter's filing and the previous 10-K; the legal proceedings, contingencies, related-party and guarantee notes; the 10-K's concentration note (4.8). |
| 5 Governance and insiders | Each 8-K with Item 5.02 (Inputs), whole; each schedule (5.4): the subject issuer its cover names (a schedule the issuer files as another company's holder is not about the issuer) and the holder's percent of the class against its previous schedule; the proxy statement's pledging and compensation sections (5.5, 5.6). |
| 6 Capital allocation and financing | The release's dividend statement, the filing's equity note and repurchase table, the debt note (covenants, refinancing), the 8-Ks with Items 1.01, 2.01, 2.03 and 3.02, the registrations listed (6.3); for 6.4, the amount stated against the equity and total assets the Inputs give. |
| 7 Earnings call: statements | The executives' prepared remarks against the previous call's; 7.4 holds the figures they state against the filing and `measures.md`. |
| 8 Earnings call: questions and answers | The turns from the first analyst's on, against the previous call's. |
| 9 Disclosure | The operating metrics (units, customers, backlog, other indicators) the previous quarter's release and filing state (9.2). |

These searches find candidate lines; a hit is not a reading, and a statement may meet a rule
without any of these words:

```sh
grep -n -i -E "outlook|guidance|expect|forecast|range|approximately|full year|full-year|next quarter|reaffirm|withdraw" \
  market_state_research/fundamentals/data/formatted/INTC/2026-06-27/DOC_ID.md
grep -n -i -E "operating segment|reportable segment|non-recurring|nonrecurring|one-time|unusual|restructuring|impairment" \
  market_state_research/fundamentals/data/formatted/INTC/2026-06-27/DOC_ID.md
grep -n -i -E "going concern|material weakness|critical audit matter|opinion|restat|change in accounting|adopt|estimate" \
  market_state_research/fundamentals/data/formatted/INTC/2026-06-27/DOC_ID.md
grep -n -i -E "risk factor|legal proceeding|litigation|investigation|subpoena|contingen|related part|guarantee|customer" \
  market_state_research/fundamentals/data/formatted/INTC/2026-06-27/DOC_ID.md
grep -n -i -E "pledg|percent of class|aggregate amount|performance measure|metric|incentive" \
  market_state_research/fundamentals/data/formatted/INTC/2026-06-27/DOC_ID.md
grep -n -i -E "dividend|repurchase|buyback|authoriz|covenant|waiver|refinanc|notes due|credit facilit|offering|convertible|acqui|divest" \
  market_state_research/fundamentals/data/formatted/INTC/2026-06-27/DOC_ID.md
```

## 5. Write and check the readings

### 5.1 Which readings, and where

1. Write the readings of each window season whose `readings.status` is `missing`, and fix
   those that are `failing`, each from the season's documents and its baselines' alone. Never
   rewrite passing readings unless a bot item's rule changed after they were written
   (AGENTS.md, The items).
2. Write them at the season's `plan` `readings.path`, `data/reports/{T}/{PERIOD}/readings.md`,
   in the grammar of AGENTS.md (The readings): the title, then every bot item of the
   catalogue, in order, each with its three lines and its quotes. Rewrite them until `check`
   passes them (5.3).

### 5.2 Each item

- `baseline:` the `DOC_ID`s of the baseline documents you read for the item, from its baseline
  kind's row of `measures.md`'s `## Baselines`, joined by `; `; `none` for an item whose
  baseline is `none` and with the statuses `no baseline`, `not applicable` and `unavailable`.
- `level:` what the item's rule gives: `red`, `yellow` or `grey` where it triggers, `none`
  where it does not; or the status that applies (AGENTS.md, The items): `not applicable` for
  every annual item in a 10-Q season and every proxy item in a season without a `DEF 14A`
  among its filings; `unavailable` for every call item while the call line of `measures.md` is
  not `transcript`; `no baseline` only while the item's baseline row lists no document;
  `not disclosed` or `not computable` only for an item the catalogue says may be so.
- `observation:` one line of facts: the values compared with their units and periods, the
  names, counts and dates, and which way the rule went (`midpoint $63.0 billion against $61.0
  billion`, `2 departures: the CFO on 2026-02-09`); never a judgment, a cause the documents do
  not state, or valuation, forecast or advice wording.
- Quotes: the statements the observation rests on, each followed by its attribution line,
  `— DOC_ID` or, for a call, `— DOC_ID, Speaker (role)` as the turn's heading writes it. A
  `red` level quotes at least one statement of the season's own documents; a quote comes from
  the season's documents or from those its baseline line names. Which statements to quote,
  that a quote is a whole statement copied verbatim from the derived text, the whole statements
  `check` refuses and the cuts it cannot see, and the length limits are the quote rules
  (AGENTS.md, Quotes).

### 5.3 Check

```sh
uv run --locked python -m market_state_research.fundamentals.script check INTC
uv run --locked python -m market_state_research.fundamentals.script check INTC \
  market_state_research/fundamentals/data/reports/INTC/2026-06-27/draft.md
```

`check` writes nothing. Without a path it checks the `readings.md` of every listed season
that has one; a path names a draft, which lies in its season's folder
(`data/reports/{T}/{PERIOD}/`, any name). It prints `ticker` and `readings[]`, each with
`path`, `season`, `valid` and `problems[]` (each with its `line` and `message`), and exits 0
even with problems: fix what each message names and check again until every window season's
readings are `valid`. Readings also fail while a
document they name has a text file that is missing or differs from the derivation: run
`derive`, then copy again every quote the new text no longer holds. Never change a text file
to make a quote match.

## 6. Render, show and report back

```sh
uv run --locked python -m market_state_research.fundamentals.script render INTC
uv run --locked python -m market_state_research.fundamentals.script show
uv run --locked python -m market_state_research.fundamentals.script plan
```

`render` writes a new report, `data/reports/{T}/{PERIOD}/report_{TOKEN}.md`, for every listed
season whose readings pass and whose newest report is not current, and prints `ticker`,
`reports[]` (each with `season` and `path`), `current[]` (the seasons whose newest report is
current) and `skipped[]` (each with `season` and the `reason` its report cannot be rendered).
`show` writes nothing: per ticker it prints the action `plan` gives over the default window,
the newest season whose report can be rendered now with its newest report's path and
freshness, and that report rendered now (or `No season report can be rendered now.`), then the
`## Ranking` table of the tickers by score.

The final `plan`, with the tickers and the window of the run's first `plan`, must show `reuse`
for every supported ticker. A ticker that `fetch` reported `unsupported` (EDGAR does not list
it, its submissions are refused, or the provider's symbol is ambiguous) stays at `fetch`:
report it with `fetch`'s reason. One left at `fetch` because `fetch` stopped at the provider's
request limit: report it with the `stopped` line.

Report for each ticker: its newest season report's path as a link, its score line and its
triggered `red` items with their quotes and attributions, as the report writes them; the
ranking; the window, whether it is `truncated`, any `pending_filings`, `skipped_filings` and
`pending_calls`, each season whose call is `waiting` (with its `reason`) or `unavailable`
(with its `as_of`) and each whose company facts are `waiting` or `absent`; unsupported tickers
and calls with their reason, `stopped`, `invalid_files`, `unlisted_files`, the documents
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
| `calls.status: unsupported` (`EarningsCalls.dev lists N issuers for T (ambiguous): their calls cannot be told apart`) | Report it; the ticker's call items stay `unavailable`. |
| `GET URL: calls list …`, `GET URL: transcript: …`, `GET URL: …` naming a company facts or Form 4 field | The provider's or EDGAR's format changed and nothing of that body was written. Report the line and open an issue with it. |
| `filing index ACC: …` (`fetch`) | EDGAR changed the index page layout and nothing of the 8-K was written, or, when a `PATH` comes first, an index page in `raw/` no longer parses (do what the line says). Report the line and open an issue with it. |
| `INTC: no season has readings; run plan` or `INTC: no report to write: PERIOD: REASON` (`render`) | Not an error to report: do what `plan` says; the reason names what the season lacks. |
| `PATH: a readings draft lies in its season's folder, named YYYY-MM-DD` (`check`) | Move the draft into `data/reports/{T}/{PERIOD}/` and check it there. |
| `'no baseline' while the baseline is in raw/: DOC_ID; …` | Read those documents and give the item its level. |
| `DOC_ID is no document of this item's baseline (KIND: SEASONS)` | Name only documents of the seasons `measures.md` lists for the item's baseline. |
| `a quote must be whole sentences, …` | The quote cuts a statement: quote it from its start to its end (AGENTS.md, Quotes). |
| `a call's quote names its turn: '— DOC_ID, Speaker (role)', …` or `the quote lies in the turn 'HEADING', not the one its attribution names` | Attribute the quote to the turn its first occurrence lies in, exactly as that turn's heading line writes it. |
| `an observation states facts only, without valuation, forecast or advice wording; found: …` | Restate the observation as the facts alone, without that word. |
