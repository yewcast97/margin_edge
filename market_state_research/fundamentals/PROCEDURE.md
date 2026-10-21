# Fundamentals: eleven fields of verbatim quotes from filings, releases and earnings calls

This procedure records, for each stock of the watchlist (or the tickers given) and each
fiscal period whose end lies in a window of dates, what each of the issuer's own
documents of that period says, as one report per document of eleven fields of verbatim
quotes. The fields, the model of periods and calls, the quote rules, the report grammar,
the time series, the sources and the file layout are in [AGENTS.md](AGENTS.md).

Run every command from the repository root with Python 3.13+ and locked dependencies:

```sh
uv run --locked python -m market_state_research.fundamentals.script COMMAND ...
```

A run: `fetch` with the window (section 2), then `plan` with the same window (section 3),
whose `action` names the next step: `fetch` again, `text` (section 4), research (section
5) or `render` (section 6). Repeat `plan` until it says `reuse` or the work cannot go on,
then report back (section 6). Run `fetch` first in every run, at least once a day while a
period's call is `waiting`: `plan` works offline and cannot see what EDGAR or the
transcript provider published since.

## 1. Parameters

| Parameter | Default | Meaning |
| --- | --- | --- |
| Ticker | `fetch`, `plan`: the tickers of the watchlist | The exact symbol: any number for `fetch` and `plan` (by default the tickers of the watchlist, in file order), one for the other commands. |
| `--watchlist PATH` | this domain's `watchlist.json`, which you maintain ([market_state_research/AGENTS.md](../AGENTS.md), Watchlists) | `fetch` and `plan` only: the watchlist read when no ticker is given, which both print as `watchlist` (null when tickers are given). One that is missing, malformed or without a ticker stops either command with one line naming the file: write or correct the file with the tickers the user follows, report the change and run the command again. |
| `--from YYYY-MM-DD` | the same day two years before `--to` (29 February: 28 February) | `fetch` and `plan` only: the earliest period end in the window, a New York date in ASCII digits; refused when it is after `--to`. |
| `--to YYYY-MM-DD` | today's New York date | `fetch` and `plan` only: the latest period end in the window; refused when it is after today. |
| `--refresh` | off | `fetch` and `plan` only: request the window's EDGAR documents, transcripts and calls list again, whatever `raw/` holds (section 2); `plan` then says `fetch`. Use it only when the user asks, on one `fetch`, and plan afterwards without it: one EDGAR request per window document and one EarningsCalls.dev request per transcript, plus the calls list. |
| `--data-dir PATH` | this domain's `data/` | Another data directory, for offline checks; every command takes it. |

Both window dates are included and bound period ends, not filing dates. Give `plan` the
same window as `fetch`. The other commands take no window.

**Settings.** `fetch` reads two lines of the repository-root `.env` (the process
environment takes precedence); no other command reads a setting. Never print or repeat a
value, and write it nowhere but where it is used.

- `SEC_USER_AGENT` names the person running `fetch` to EDGAR: a name, a space and an
  email address, printable ASCII, at most 200 characters, such as
  `SEC_USER_AGENT="Name contact@example.com"`. When it is missing or malformed, ask the
  user for the name and contact address to use and, with their agreement, add the line
  to `.env`.
- `EARNINGSCALLS_API` is the user's own EarningsCalls.dev key: printable ASCII without
  spaces, at most 200 characters, as `EARNINGSCALLS_API="..."`. Its plan allows 3,000
  requests a month and 20 a minute; `fetch` asks for a ticker's calls list only when it
  is due and for each transcript once, unless `--refresh` asks again, so filling the
  default two-year window of six tickers takes about 600 requests, and keeping it current
  a few hundred a month. When the key is missing or malformed, ask the user to add or
  correct the line themselves; never ask for the key in the conversation or open an
  account.

**Limits.** A speaker name in a report: at most 120 characters; a quote: 20 to 800
characters after normalisation.

## 2. Fetch: write the documents of the window's periods into `raw/`

```sh
uv run --locked python -m market_state_research.fundamentals.script fetch
uv run --locked python -m market_state_research.fundamentals.script fetch INTC --from 2025-01-01 --to 2026-10-09
```

It writes the submissions JSON when it changed, each EDGAR document of a window period
that is not in `raw/` yet, the ticker's calls list when it is due and each window call's
transcript that is not in `raw/` yet; it writes no text. It prints `requests` (EDGAR),
`user_agent: "set"`, `transcript_requests` (EarningsCalls.dev), `api_key: "set"`,
`window`, `refresh`, `stopped` and an entry per ticker under `tickers`; act on these:

| Field | Meaning |
| --- | --- |
| `status`, `reason` | `fetched`, or `unsupported` with the reason (EDGAR does not list the ticker, no 10-K or 10-Q, two filings for one period, an 8-K without a usable event date): report it and stop for that ticker; the others go on. |
| `truncated`, `pending_releases[]` | Report them: `truncated: true` means periods before the oldest recent filing are not read; a pending release may later join a period already researched, whose new exhibit then needs a report. |
| `periods[]` | Per window period, its `filing` and each release's `index` and `exhibits[]`, each with `path` and `status`: `new` (written now) or `reused` (already in `raw/`, not requested); with `--refresh`, `verified` (requested again: the same bytes) or `changed` (EDGAR now serves other bytes, and nothing was written: replace the stored file only when the user asks, by renaming it `.rejected` and running `fetch` again). |
| `calls` | `status`: `fetched`; `unsupported` with the `reason` (the provider's symbol names several issuers): report it and stop for that ticker's calls; or `stopped` with the `reason` (below). `events`: the calls list kept, with its `path`, `pages`, `fetched_at`, `status` (`new`, asked for now with the `reason` it was due, or `reused`); null when none is in `raw/`. `transcripts[]`: each window call's (and each pending call's) `id`, `date`, `fiscal_year`, `fiscal_quarter`, `period` and `doc_id` (null for a pending call), `path` and `status` (`new` or `reused`; with `--refresh`, `verified`, or `refreshed`: the provider served other bytes, now written beside the stored copy at `path`, the copy every later read takes). |
| `stopped` | Null, or the `ticker` and `reason` where EarningsCalls.dev's request limit stopped every later request to it in this run (exit 0): the later tickers' EDGAR files were still fetched, and their `calls.status` is `stopped`. Report it with the reset the line names, and run `fetch` again only after it. |

A failed request or a body that does not read aborts the run with one `FUNDAMENTALS:`
line; nothing of that document is written, and what was written before stays. Run
`fetch` again once the cause is gone, never in a loop.

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
| `calls` | `events`: the newest calls list in `raw/` (`path`, `pages`, `fetched_at`), null when none is valid; `due`: why `fetch` asks for the list again now, or null; `pending_calls[]`: calls dated after the newest period's filing, which a later period will take; `unlisted_files[]`: transcripts of calls the newest list does not list, left out (report them). |
| `periods[]` | Per window period, oldest first: `period`; `status` (`complete`, `incomplete` or `not researched`); `filing`, `releases[]` with their `index` and `exhibits[]`, each with `raw` (true once its file is in `raw/` and valid); `call` with `status` (`transcript`, `unavailable`, `waiting` or `missing`: AGENTS.md, Periods, releases and calls), `due` (the date the call is expected by), `as_of` (the date of the list its status rests on), `calls[]` (the calls placed in the period), `documents` (their `DOC_ID`s) and `reason` (why a `waiting` or `missing` call is not settled); `documents[]`, every document of the period in `raw/`, each with `doc_id`, `kind` (`filing`, `exhibit` or `call`), `text` (`path`; `status` `present`, `missing` or `differs`) and `report` (`path`, where the report is or goes; `status` `valid`, `failing` or `missing`; the number of `problems`). |
| `truncated`, `pending_releases[]` | As in `fetch`. |
| `invalid_files[]` | Raw files that failed validation, with `path` and `reason`. |
| `failing_reports[]` | Reports of any period that fail `check`, with `path`, `document` and the number of `problems`. |
| `series` | The newest series file: `status` (`fresh`, `stale` or `missing`) and `path`; `as_of` of the series rendered now (null when none can be). |

The first action that applies:

| `action` | When | Next step |
| --- | --- | --- |
| `fetch` | No period is listed; a window period's 10-K, 10-Q, index page or EX-99 exhibit is not in `raw/` or is invalid; a raw file is invalid; a window period's call is `missing`; or the calls list is due (`calls.due`; with `--refresh`, whenever the window holds a listed period). | Rename each `invalid_files` entry with `.rejected`, if any, then run `fetch` with the same window (and `--refresh`, when `plan` had it). When `reason` refuses the submissions (`no 10-K or 10-Q …`, two filings for one period, an 8-K's event date) or `fetch` reported the ticker or its calls `unsupported`, report it and stop for that ticker. |
| `text` | A window document's `text.status` is `missing` or `differs`. | Run `text` (section 4). |
| `research` | A window document's `report.status` is not `valid`, or `failing_reports` is not empty. | Read the documents (section 4), then write and check their reports (section 5). |
| `render` | Every window document's report passes, and the newest series is not the series rendered now. | Run `render` (section 6). |
| `reuse` | The newest series is the series rendered now, or no period is complete. | Return `series.path`. When `periods` is empty, tell the user the window holds no period end. |

A `waiting` call blocks no action: research the period's other documents; the period
stays incomplete until a later `fetch` finds its call or, 7 days after its due date,
shows it `unavailable`.

## 4. Write and read the derived text

```sh
uv run --locked python -m market_state_research.fundamentals.script text INTC
```

`text` writes the derived text of every document of every listed period in `raw/`,
whatever the window: each missing text file, one that cannot be read and one that differs
from its derivation. It prints `ticker` and `documents[]`, each with `doc_id`, `period`,
`kind`, `path` and `status` (`published`, `exists` or `rewritten`).

A period's documents are its `plan` entry's `documents[]`; each one's text is at its
`text.path`, `data/formatted/{T}/{DOC_ID}.md`. A call's text holds, per turn, a heading
line with the speaker's name and role as the transcript provider gives them
(`David Zinsner (executive)`, `Jane Analyst (analyst)`, `Operator (operator)`), then the
turn's paragraphs, one per line. A `.txt` document's line is not a statement (AGENTS.md,
the sentence rule): read the whole sentence around every line you find.

Read with the file tools and `grep`. These eleven searches, one per field in the fields'
order (`upstream_shortage` first, `customer_concentration` last), find candidate lines; a
hit is not a quote, and a statement may pass a field's test (AGENTS.md, The eleven
fields) without any of these words:

```sh
grep -n -i -E "supplier|supply|sole source|single source|limited number|component|material|substrate|wafer|foundry|equipment|lead time|shortage|constrain|allocat|sufficien|tariff|input cost|purchase (obligation|commitment)|prepay" \
  market_state_research/fundamentals/data/formatted/INTC/DOC_ID.md
grep -n -i -E "demand|customer|order|booking|backlog|design win|end market|inventor|channel|pricing|average selling price|shipment|deliver|sold out|capacity" \
  market_state_research/fundamentals/data/formatted/INTC/DOC_ID.md
grep -n -i -E "capital expenditure|capital spending|capital investment|capex|gross capital|net capital|property and equipment|construction|fab|factory|capacity|return on invested|ROIC|payback" \
  market_state_research/fundamentals/data/formatted/INTC/DOC_ID.md
grep -n -i -E "capacity|fab|factory|facility|site|line|expan|ramp|utiliz|utilis|headcount|wafer start" \
  market_state_research/fundamentals/data/formatted/INTC/DOC_ID.md
grep -n -i -E "outlook|guidance|expect|forecast|anticipate|target|project|approximately|next quarter|full year|full-year|fiscal year|long-term|reaffirm|withdraw" \
  market_state_research/fundamentals/data/formatted/INTC/DOC_ID.md
grep -n -i -E "pric|ASP|average selling|surcharge|discount|rebate|renewal" \
  market_state_research/fundamentals/data/formatted/INTC/DOC_ID.md
grep -n -i -E "backlog|booking|book-to-bill|remaining performance|deferred revenue|contract liabilit|supply agreement|purchase agreement|framework|reservation|design win|prepay" \
  market_state_research/fundamentals/data/formatted/INTC/DOC_ID.md
grep -n -i -E "ramp|sampl|qualif|certif|approval|design-in|pilot|volume production|launch|yield|generation|transition|delay|node" \
  market_state_research/fundamentals/data/formatted/INTC/DOC_ID.md
grep -n -i -E "margin|mix|cost|yield|utiliz|utilis|scale|depreciation|amortiz|useful li|one-time|non-recurring|nonrecurring|impairment|restructuring|settlement|gain|loss" \
  market_state_research/fundamentals/data/formatted/INTC/DOC_ID.md
grep -n -i -E "financ|fund|liquidity|debt|notes|term loan|commercial paper|credit facilit|borrow|equity|offering|shelf|convertible|partner|contribution|grant|incentive|lease|repurchase|dividend|monetiz|at-the-market|dilut" \
  market_state_research/fundamentals/data/formatted/INTC/DOC_ID.md
grep -n -i -E "customer|concentrat|largest|accounted for|% of|percent of|distributor|OEM|dependen|significant portion" \
  market_state_research/fundamentals/data/formatted/INTC/DOC_ID.md
```

Read in full: in a 10-K, Item 1 (Business, with its customers), Item 1A (Risk Factors),
Item 7 (MD&A, with its outlook and liquidity and capital resources, where capital
expenditures, purchase commitments and financing are discussed) and the notes on
borrowings, non-controlling interests, equity and major customers or concentration of
credit risk; in a 10-Q, Part I, Item 2 (MD&A, with its outlook and liquidity and capital
resources), the same notes, Part II, Item 1A (risk-factor updates) and Part II, Item 2
(unregistered sales of equity securities, use of proceeds and repurchases); in an
earnings release, its highlights, executives' remarks, business outlook (often a table
of ranges) and any financing announcement, and any other EX-99 document (a CFO
commentary, say) as a whole; in a call, the whole transcript: the executives' prepared
remarks, the CFO's balance-sheet and financing remarks included, and their answers in the
question-and-answer session (an analyst's question only tells what an answer is about).
Elsewhere, read the whole paragraph or table around every line the searches find.

## 5. Write and check the reports

### 5.1 Which reports, and where

1. Write a report for each window document whose `report.status` is `missing`, and fix
   each report that `failing_reports` names, each from its own document alone. Complete
   each period you start: a period enters the series only when every one of its
   documents has a passing report. Never rewrite a passing report unless a field's
   definition changed after it was written (AGENTS.md, The eleven fields).
2. Write each report at its `plan` `documents[].report.path`,
   `data/reports/{T}/{DOC_ID}.md`, in the grammar of AGENTS.md (The per-document report),
   and rewrite it until `check` passes it (5.2).
3. Which statements belong to each field, that a quote is a whole statement copied
   verbatim from the derived text of the report's own document, the whole statements
   `check` refuses and the cuts it cannot see, the length limits and the `Speaker:` line
   are the research rules (AGENTS.md, Quotes: the research rules): quote a statement
   `check` refuses with its neighbour, verbatim, never cut one where the rule cannot see
   it, and name in the report back each statement left out for its length. In a call,
   quote only turns whose heading names the role `executive`, each with the `Speaker:`
   line its heading writes.

### 5.2 Check

```sh
uv run --locked python -m market_state_research.fundamentals.script check INTC
uv run --locked python -m market_state_research.fundamentals.script check INTC PATH/TO/call_2026-06-27_248001.md
```

`check` writes nothing. Without a path it checks every report in `reports/{T}/` but the
series and those of a period older than every listed one; a path may name a draft
anywhere, whose file name without `.md` names its document. It prints `ticker` and
`reports[]`, each with `path`, `document`, `valid` and `problems[]` (each with its `line`
and `message`), and exits 0 even with problems: fix what each message names and check
again until every report is `valid`. A report also fails while its document's text file
is missing or differs from the derivation: run `text`, then copy again every quote the
new text no longer holds. Never change a text file to make a quote match.

## 6. Render, show and report back

```sh
uv run --locked python -m market_state_research.fundamentals.script render INTC
uv run --locked python -m market_state_research.fundamentals.script show INTC
uv run --locked python -m market_state_research.fundamentals.script plan
```

`render` writes a new time series, `data/reports/{T}/{T}_{AS_OF}_{TOKEN}.md`, from the
reports of every complete period, whatever the window, and prints `ticker`, `as_of`,
`path` and `periods[]`, newest first, each with `period`, `status` and what is `missing`
(`documents not in raw/`, `the earnings call's transcript is not in raw/`, `the earnings
call is not listed yet`, the `DOC_ID`s without a passing report). `show` writes nothing:
it prints `plan`'s action over the default window, a line each on the periods, the
reports and the series, a line per invalid file and per failing report, then a blank line
and the series rendered now (or why none can be).

The final `plan`, with the tickers and the window of the run's first `plan`, must show
`reuse` for every supported ticker. A ticker that `fetch` reported `unsupported` (EDGAR
does not list it, its submissions are refused, or the provider's symbol is ambiguous)
stays at `fetch`: report it with `fetch`'s reason. One left at `fetch` because `fetch`
stopped at the provider's request limit: report it with the `stopped` line.

Report for each ticker: the series path as a link, its as-of date and its coverage
table; the window, whether it is `truncated`, any `pending_releases` and
`pending_calls`, and each period whose call is `waiting` (with its `reason`) or
`unavailable` (with its `as_of`); unsupported tickers and calls with their reason,
`stopped`, `invalid_files`, `unlisted_files`, the documents `fetch --refresh` found
`changed` and the transcripts it `refreshed`, files renamed `.rejected` with their
messages, and statements left out for their length (AGENTS.md, Quotes: the research
rules). Never restate, summarise or interpret the quotes: point to the series. What blocks
you or looks wrong in a rule, a message or a tool goes into a GitHub issue (the root
[AGENTS.md](../../AGENTS.md), Feedback), never into the rule.

## Failure handling

Every failure exits 2 with one `FUNDAMENTALS:` line on standard error; exit 0 means
success, including a `check` that lists problems, a `plan` or `fetch` that leaves work to
do, a ticker or its calls reported `unsupported` and a `fetch` that the provider's request
limit stopped. A usage error (`… invalid choice: …`, `… unrecognized arguments: …`,
`… expected a YYYY-MM-DD date, got '…'`) did nothing: run the command again with valid
arguments. Any other message, `reason`,
`invalid_files` entry or `problems[]` message says what to do: do it, or report it
verbatim. Never weaken validation; withdraw a raw file by renaming it `.rejected`. These
need more:

| Message | Action |
| --- | --- |
| `INTC: N files in raw/ failed validation; first: PATH: REASON; run plan for the list and rename each with .rejected` (`text`, `check`, `render`) | Read `plan`'s `invalid_files`, rename each entry with `.rejected`, then run `fetch`. |
| `SEC_USER_AGENT is not set; …` or `SEC_USER_AGENT must be a name and an email address, …` | Nothing was sent: section 1, then run `fetch` again. |
| `EARNINGSCALLS_API is not set; add EARNINGSCALLS_API="..." to the repository-root .env` or `EARNINGSCALLS_API must be printable ASCII without spaces` | Nothing was sent: ask the user to add or correct the line (section 1), then run `fetch` again. |
| `…: HTTP 401 …; EarningsCalls.dev refused the key: check EARNINGSCALLS_API` | The key is wrong or revoked: ask the user to check it, and run `fetch` again only once they have. |
| `…: HTTP 403 …; EarningsCalls.dev refused the request: the key's plan does not include it …` | Tell the user their EarningsCalls.dev plan does not cover full transcripts, and stop the calls until they say so. |
| `…: HTTP 404 …; EarningsCalls.dev serves nothing at this address` | The provider lists a call whose transcript it does not serve: run `fetch` once more after a day; when it fails the same way, report the line and stop for that ticker. |
| `stopped` in `fetch`'s output (`…: HTTP 429; EarningsCalls.dev's request limit is reached …; run fetch again once it resets`) | Report it with the reset date the line names; run `fetch` again only after it. EDGAR's files of every ticker were still fetched. |
| `…; EarningsCalls.dev is unavailable: wait and run fetch again`, `…; EDGAR is unavailable: …`, `…; EDGAR's rate limit: …` or `…: the body ended after N of M bytes; run fetch again` | Wait some minutes (ten for EDGAR's rate limit), then run `fetch` once more. When it fails the same way again, report it and stop for that ticker. |
| `calls.status: unsupported` (`EarningsCalls.dev lists N issuers for T (ambiguous): their calls cannot be told apart`) | Report it; the ticker's periods cannot be completed. |
| `GET URL: calls list …`, `GET URL: transcript: …` | The provider's format changed and nothing of that body was written. Report the line and open an issue with it. |
| `filing index ACC: …` (`fetch`) | EDGAR changed the index page layout and nothing of the release was written, or, when a `PATH` comes first, an index page in `raw/` no longer parses (do what the line says). Report the line and open an issue with it. |
| `INTC: no period is complete: every document of a period needs a report that passes check` (`render`) | Not an error to report: research at least one period completely, its call settled and every document's report passing. |
| `the report names no document of a listed period in raw/ …` (`check`) | The file name is not a `DOC_ID` of `plan`'s `documents[]`: rename the report to the right one, or, when its document was withdrawn or its `DOC_ID` changed, with `.rejected`. |
| `a quote must be whole sentences, …` | The quote cuts a statement: quote it from its start to its end (AGENTS.md, Quotes: the research rules). |
| `a call quote needs a 'Speaker:' line …`, `the quote lies in a turn whose role is ROLE, not executive …`, `the quote lies in another speaker's turn …` or `a call quote must lie within the words of one speaker's turn …` | Quote only an executive's turn, within it, under the `Speaker:` line its heading writes; remove a quote of any other speaker. |
| `names state facts only, without valuation, forecast or advice wording; found: …` | Copy a speaker name the document writes without such a word; if it writes none, stop and ask the user. Never respell a name. |
