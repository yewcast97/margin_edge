# Market state research principles and architecture

The research is organized by **domain**: a domain discloses one aspect of the state of the
market and holds, in one folder, its guidance, its procedure, its code when it has any, and
its data. Every domain has one `AGENTS.md`, which states the aim of the work and what its
formatted data and reports hold and mean, then how each value is obtained, the architecture,
the raw files and the facts verified live of each source it reads; and one `PROCEDURE.md`,
its operations. The code the domains share, bound to no source and no domain's data
directory, is the `common/` package.

The bot runs the domains from its own host and yields their data, as the root
[AGENTS.md](../AGENTS.md) defines (The bot): it runs the commands and follows each domain's
`PROCEDURE.md`, writes only what they let it write, never edits a rule or a script, and opens
a GitHub issue when one blocks or misleads it (Feedback). In the three scripted domains,
`stock_iv_regime`, `market_position_regime` and `fundamentals`, every source is read by
Python over HTTPS (the API rule, below), so the bot needs a shell with uv and network access,
and no browser; in `posts` the bot reads each nominated account by whatever route its host
offers and writes each of its data files by hand. Nothing the bot produces is tracked: every
`data/` directory, every poster's folder and every watchlist is ignored by Git.

## Folder structure

```text
market_state_research/
├── AGENTS.md
├── common/             shared Python package, bound to no domain
│   └── vendor/             (the chart library every report page inlines)
├── <domain>/           a scripted domain: stock_iv_regime, market_position_regime, fundamentals
│   ├── AGENTS.md
│   ├── PROCEDURE.md
│   ├── watchlist.json      (the bot's stock tickers, ignored by Git; none in market_position_regime)
│   ├── script/
│   │   └── templates/      (optional)
│   └── data/
│       ├── .gitignore
│       ├── raw/{TICKER}/       (raw/market/ in market_position_regime)
│       ├── formatted/{TICKER}/
│       └── reports/{TICKER}/
└── posts/              the domain without a script
    ├── AGENTS.md
    ├── PROCEDURE.md
    ├── watchlist.json      (the bot's: the posters, ignored by Git)
    └── <poster>/           (the bot's, ignored by Git)
        ├── profile.md
        └── data/
            ├── raw/
            ├── formatted/
            └── reports/
```

| Path | Responsibility |
| --- | --- |
| `AGENTS.md` | Shared principles of the research, the domain folder conventions and the data layout. |
| `common/` | Python shared by every domain: New York time and file-name tokens (`times`), XNYS sessions and market status for the domains that work by session (`sessions`), the three sections of a domain's `data/` with their one write rule (`layout`), ticker and one-line message text (`text`), the one-line `LABEL: ...` command-line conventions, with each domain's own label (`cli`), the reader of a ticker domain's watchlist (`watchlist`), the personal settings of the ignored repository-root `.env` (`env`), and the chart library with the page text every report page shares (`chart`, over `vendor/`). It knows no source, no raw format and no domain's data directory, and sends no network request. |
| `common/vendor/` | Third-party files copied unmodified from a pinned release, with their licence, notice and provenance: TradingView Lightweight Charts, which `common.chart` verifies and every domain's chart inlines. |
| `<domain>/AGENTS.md` | The domain's guidance: first the aim, the outputs and what they mean, the commands; then the method, the module boundaries and vendored libraries, the raw files, each source's formats and facts verified live. |
| `<domain>/PROCEDURE.md` | The domain's operations: settings, parameters, commands and their output fields (in `posts`, the steps the bot takes by hand), the routines, failure handling and the report back. |
| `<domain>/watchlist.json` | The domain's watchlist, maintained by the bot and ignored by Git (Watchlists): the stock tickers in `stock_iv_regime` and in `fundamentals`, the posters and their accounts in `posts`; `market_position_regime`, whose subject is the market, has none. |
| `<domain>/script/` | A scripted domain's Python package and supporting code; `posts` has none. |
| `<domain>/script/templates/` | Optional output templates read by the code, such as an HTML page. |
| `<domain>/data/` | Runtime files in three sections, `raw/`, `formatted/` and `reports/` (Data layout). |
| `posts/<poster>/` | One nominated poster, the bot's and ignored by Git whole: `profile.md` (who the poster is, their accounts and the count of verdicts so far) and `data/` in the three sections. |

`templates/` and `common/vendor/` hold static assets the code reads. A vendored file is
byte-identical to its upstream release, with its source and hashes beside it, and the code
verifies its pinned checksum before using it. Runtime data is ignored by Git; a scripted
domain's tracked `data/.gitignore` keeps its empty data directory in a fresh checkout (a
poster's folder in `posts` is the bot's, ignored whole, and needs none). Scripts resolve
their default data directory and their assets relative to their own domain, whatever the
working directory. Personal settings remain in the ignored repository-root `.env`; Python
reads it only through `common.env`, where the process environment takes precedence, and
never prints a value.

## Watchlists

A domain that works through a list keeps its own `watchlist.json` beside its `AGENTS.md`:
the stock tickers of `stock_iv_regime` and of `fundamentals`, and the posters of `posts`
(that domain's `AGENTS.md` gives its format). There is no shared watchlist. The bot
maintains every one (root [AGENTS.md](../AGENTS.md), The bot): it writes the file,
adds and removes entries when the user asks or by its own judgment, corrects a file
a command refuses, and reports each change. Like `.env`, each is ignored by Git, so a
checkout has none until the bot writes it. A ticker watchlist holds exactly one list of
stocks, which may be empty:

```json
{
  "stock": ["INTC", "MU", "AEHR", "AMAT", "TER", "AAOI"]
}
```

Its items are distinct US stock ticker symbols in upper or lower case; an index has no
place in it. The two ticker watchlists are independent: a stock may be on one and not on
the other. Without tickers, `plan` and `fetch` (and `fundamentals`' `show`) take the list in
file order, read through `common.watchlist`; tickers given on the command line override it
without reading it, `--watchlist PATH` reads another file, and `plan` and `fetch` print the
file they read (`watchlist`, null when tickers are given). Without tickers, a file that is
missing, malformed or without a ticker stops the command with one line naming it. The
watchlists belong to market state research alone: hypothesis exploration reads none, and
the posters of `posts` are read by the bot, never by Python.

## Data layout

Every `data/` directory, a scripted domain's or, in `posts`, a poster's, holds exactly three
sections. In the scripted domains each section has one folder per ticker
(`raw/{TICKER}/`, ...), or one folder `market/` in `market_position_regime`, whose subject is
the market, and Python writes them only through `common.layout`; in `posts` the bot writes all
three by hand, under that domain's `AGENTS.md`:

| Section | Contents | Written by |
| --- | --- | --- |
| `raw/` | What was fetched, verbatim, as the domain's `AGENTS.md` describes each file; in `posts`, every post of one account over one interval the user asked about. | `fetch`, the one network command of each scripted domain, and the bot only renames a file `.rejected`; in `posts`, the bot, once per file. |
| `formatted/` | What Python derives from `raw/`: the tables, texts or measures the domain's `AGENTS.md` names; in `posts`, the fact-check of each raw file. | `record` in `stock_iv_regime` and `market_position_regime`, `derive` in `fundamentals`; the bot in `posts`. |
| `reports/` | What the user reads. | `record`, or `render` in `fundamentals`, where the bot also writes each season's readings; the bot in `posts`, one report per request. |

- **A run keeps what is stored.** The raw files are the evidence every value rests on, and
  requesting them again costs quota and time: `fetch` requests only what the window lacks,
  never again what `raw/` holds, and leaves every stored file as it is. `--refresh` on
  `fetch` and `plan` is the one exception, used only when the user asks: it requests the
  window's data again whatever is stored and keeps every stored file (the domain's
  `AGENTS.md` says what it requests again and what becomes of an answer that differs from
  the stored copy). No command deletes or empties `raw/`. In `posts` a request reads only
  the parts of its interval that no raw file of the account covers, unless the user asks for
  a covered one to be read again.
- **`raw/` is the archive.** Python never modifies a raw file, and every command validates
  every raw file it reads, every time it reads it (the formats, the calendar and time
  rules and the other rules of the domain's `AGENTS.md`). The bot never edits a raw file
  either: it withdraws one as its `PROCEDURE.md` says (a file that failed validation) by
  renaming it with the suffix `.rejected`, which every read skips. In `posts`, where no
  validator exists, the bot writes each raw file once and withdraws one it finds wrong the
  same way.
- **`formatted/` is a function of `raw/`.** Its command (`record`, or `derive`) rebuilds it and
  overwrites it; nothing there is the only copy of anything. In `stock_iv_regime` and
  `market_position_regime` a formatted table caches the levels read from `raw/` (an implied
  volatility, a close, a balance, a position) and nothing derived from them, not even the
  difference of two levels: no net, spread, percentile, correlation or other indicator, each of
  which `record` and `show` compute again from those levels for every report, so any value
  derived later, by a report or a hypothesis, rests on the same levels. In `posts` it is not:
  the fact-check of a raw file rests on the evidence found at each check as well, is updated
  in place with a dated history, cannot be rebuilt, and is kept like `raw/`.
- **`reports/` is never overwritten.** A report name that exists fails the command, and
  older reports stay: no command deletes one, and neither does the bot. The fundamentals
  domain's readings are the bot's: it may rewrite a season's readings until `check` passes
  them, and again after an item's rule changes (the domain's `AGENTS.md`). A `posts` report
  answers one request, under a name of its own, and is never rewritten.
- **Selection replaces bookkeeping.** Per key (a session's chain, a week's report, a call's
  transcript) the newest file wins (the domain's `AGENTS.md` says what a key is), so a refresh
  writes a newer file beside the stored one, which wins from then on. Nothing records the selection: there
  are no ledgers, manifests, envelopes, version fields or lost-update guards. In `posts` an
  account's coverage is the union of the intervals its raw files' names give, and nothing
  else records it.
- **In the scripted domains, a report is fresh** while it is exactly what its command
  (`record`, or `render`) would write now, apart from its generation time, and `plan` says
  `reuse` only for a fresh report. The command writes a new report every time it runs while
  the data allow one.
  So whatever alters a report (a raw file added or withdrawn, a change of the rules or the
  code; the domain's `AGENTS.md` says which) makes `plan` ask for it again.
- **Names are ordered by instant.** A name that carries a New York time token
  (`common.times.timestamp_token`) is ordered by the instant the token names, never as
  text: 01:30 occurs twice on the fall-back day, so `…T013000EST` follows `…T015959EDT`
  (`common.layout.name_instant` and `newest`). A `posts` raw name carries three tokens, the
  interval's start and end and the time of the read.

## Principles

- Read the domain's `AGENTS.md` (what the work is, what its outputs mean and how they are
  obtained) and follow its `PROCEDURE.md`.
- Preserve source definitions and the original documents and records. Do not substitute
  invented observations, local estimates or a different statistic. A value Python derives
  is stated with its formula and kept beside the source values it comes from.
- Keep fetching, validation and persistence responsibilities explicit: `fetch` writes raw
  files, the bot withdraws one only as its procedure says, and Python's hardcoded
  validators and selection rules decide which are used (Data layout). In `posts` the bot
  does all three by hand, under that domain's rules.
- Report missing data, stale inputs and validation failures accurately. Do not bypass
  checks or silently carry values forward.
- The domains supply reproducible facts and calculations; analytical hypotheses and
  trading judgments stay outside these workflows. Hypothesis exploration
  ([explore_hypothesis/AGENTS.md](../explore_hypothesis/AGENTS.md)) is the bot's own work,
  its product like the data it yields, binding no domain: it may read and copy a domain's
  data, never changing it, or bring data from any other source, and no domain reads a
  hypothesis.
- Work as of the last completed XNYS session and never on intraday live data. The bot may
  run at any time; a domain that reads market data fetches a session's end-of-day values
  only after its close, and a raw file fetched before the close of its session is invalid:
  `stock_iv_regime` (a session's option chain, a ticker's daily prices) and, for the VIX and
  the SKEW, `market_position_regime` (Cboe's daily histories, each invalid when it holds a
  row of a session whose values were not due yet, a quarter of an hour after XNYS closes). Sessions, holidays and
  closes come from the pinned `exchange-calendars` release, which knows only closures
  announced before it was published: a raw file of a day that is not a session is invalid (a
  history of many days keeps its source's rows of other days and never uses them), and an
  unscheduled closure NYSE announces after that release is reported in an issue. A
  document that is no session's is dated by its own date, with no session logic:
  `market_position_regime`'s statistics of a month or a week, each published after it,
  the filings and earnings-call transcripts of `fundamentals` (whose one use of the sessions
  is an item's test of an earnings release accepted on the eve of a day without one), and
  the posts of `posts`.
- Python reads its sources only through APIs or public files at fixed addresses, each from a
  command of its own that `plan` names (`fetch`), only to the source's fixed hosts over
  HTTPS, with bounded bodies and no redirect followed: a public read-only API that publishes
  an access policy the client follows to the letter (SEC EDGAR, in `fundamentals`), a public
  API or file that needs no key (the CFTC's Socrata API, FINRA's margin statistics workbook
  and Cboe's daily histories of the VIX and of the SKEW, in `market_position_regime`), or a
  provider's API
  under the user's own key, kept in the ignored `.env`, sent only to its host and never
  written, printed or stored (EODHD and Tiingo in `stock_iv_regime`, EarningsCalls.dev in
  `fundamentals`). No source of a scripted domain is read in a browser, and no command
  reads a setting it does not need. This rule binds Python. `posts` has none: the bot reads
  each nominated account by the route its host offers (its own integration with the
  platform, the platform's API under the user's key, kept in `.env` as `{PLATFORM}_API`,
  or a browser on the host), names the route in every raw file, and never asks for a
  credential in the conversation.
- Use New York exchange time (America/New_York, EDT or EST) and no other time zone: stored
  timestamps, file-name timestamps, JSON, Markdown and HTML output, messages and
  documentation. Write instants as ISO 8601 with their offset (`2026-10-06T05:09:17-04:00`),
  except in text meant only for people (a chart's "Generated" header, the times a report
  page or its notes show), which shows New York time to the second with its zone
  (`2026-10-06 05:09:17 EDT`, from `common.times.et_display`); time values in data a
  program reads (embedded JSON, CSV files) stay ISO 8601. Write file-name tokens with their
  zone (`20261006T050917EDT`); Data layout says how names are ordered. Normalise every
  datetime with `common.times.to_eastern` before comparing it. A time a source gives in
  another zone is converted when it is read; a day label is not a time and is read as its
  date (Tiingo's bar date `2026-10-16T00:00:00.000Z` names the session 2026-10-16). A post
  keeps the timestamp its platform gives, verbatim, beside its New York conversion.

## Domains

| Domain | Aim | Sources |
| --- | --- | --- |
| [`stock_iv_regime`](stock_iv_regime/AGENTS.md) ([procedure](stock_iv_regime/PROCEDURE.md)) | Per session, the 14-DTE 25Δ skew, the 14-DTE ATM IV and the term structure (the 30-DTE ATM IV minus the 14-DTE) with their 252-session percentiles, and the 15-session correlations of the stock's daily return with the changes of the 14-DTE 25Δ call and put IVs, over a look-back window, in two charts read together. | EODHD options API (`EODHD_API`) and Tiingo daily prices (`TIINGO_API`). |
| [`market_position_regime`](market_position_regime/AGENTS.md) ([procedure](market_position_regime/PROCEDURE.md)) | For the US equity market over a window of dates, FINRA's margin debt by month, S&P 500 futures positioning by week (asset managers' net long and leveraged funds' net short, each as its percentile over 52 weeks) and the VIX and the SKEW by session (each as a percentile over 252 sessions), in three charts read together. | FINRA's margin statistics workbook, the CFTC's Traders in Financial Futures (Socrata API) and Cboe's daily VIX and SKEW histories, none with a key. |
| [`fundamentals`](fundamentals/AGENTS.md) ([procedure](fundamentals/PROCEDURE.md)) | Per stock issuer and season (fiscal period), what changed against stated baselines: 69 items in nine sections, 16 computed by Python from EDGAR's XBRL facts, listing and Form 4s and the calls' transcripts, 51 read by the bot from the documents with verbatim quotes, and one report per season with every item's level and a score. | SEC EDGAR (`SEC_USER_AGENT`) and the EarningsCalls.dev transcript API (`EARNINGSCALLS_API`). |
| [`posts`](posts/AGENTS.md) ([procedure](posts/PROCEDURE.md)) | Per nominated poster, every post of the intervals the user asked about, archived verbatim and fact-checked claim by claim against cited evidence (`true`, `unverified` or `fake`); a profile with the poster's background and the count of verdicts so far; a report per request. | The poster's accounts, by the route the bot's host offers (a key only when that route is a platform's API: `{PLATFORM}_API`); evidence from primary sources first. |

### stock_iv_regime

For each ticker, `fetch` first writes its daily prices from Tiingo as
`raw/{TICKER}/prices_{END}_{TOKEN}.json.gz` whenever the newest are not current, then each
XNYS session's option chain from EODHD as `raw/{TICKER}/chain_{DATE}_{TOKEN}.json.gz`
(every contract of every expiry 1 to 65 days out): the latest completed session from the
contracts listing, proved to be that session's by its traded records, and older sessions
from sweeps of each expiry's end-of-day records, until the run's budget or EODHD's daily
quota stops it cleanly. From each chain, the IVs at deltas ±0.25 and ±0.50 are read at the
last expiry 1 to 14 calendar days out and the first one 14 or more days out that give all
four readings, and those at ±0.50 likewise around 30 days (an expiry without the readings
is skipped and named), and interpolated to 14 and to 30 days; from these rounded levels
come the 25Δ skew (put minus call, pp), the 14-DTE and 30-DTE ATM IVs (%) and the term
structure (the 30-DTE ATM IV minus the 14-DTE, pp). The skew, the 14-DTE ATM IV and the
term structure are each ranked among the 252 sessions ending with them, and the stock's
daily return (from Tiingo's adjusted closes) is correlated over 15 sessions with the change
of the 14-DTE 25Δ call IV and with that of the put IV. `plan` (read-only) says `fetch`,
`record` or `reuse`; `record` rewrites `formatted/{TICKER}/volatility.csv`, a cache of the
levels alone, and writes the report
`reports/{TICKER}/{TICKER}_{AS_OF}_{N}s_{TOKEN}.html`, which inlines the vendored TradingView
Lightweight Charts library and draws two charts over the stock's adjusted close, the
percentiles and the correlations, always served together, and its Markdown twin; `show`
prints the twin recomputed from `raw/`. Nothing adds a regime label.

### market_position_regime

The domain has no ticker: its subject is the market, so each section of `data/` holds one
folder, `market/`. Over a window of New York dates (`--from`, `--to`; default the three years
ending today), `fetch` writes to `raw/market/` what the window lacks of three sources, none
with a key: FINRA's margin statistics workbook as received (`finra_margin_{TOKEN}.xlsx`, the
customers' debit and free credit balances of every month since 1997), the CFTC's Traders in
Financial Futures rows of the S&P 500 Consolidated (`cftc_tff_{FIRST}_{LAST}_{TOKEN}.json`,
one report a week since 2010) and Cboe's daily histories of the VIX and of the SKEW as
received, in gzip (`cboe_vix_{TOKEN}.csv.gz` and `cboe_skew_{TOKEN}.csv.gz`, every day since
1990). Each document is due from the time its source publishes it, and one the source has
not published yet is `pending`. Each month's margin debt is FINRA's debit balances as
published; each week gets the net long position of asset managers and the net short
position of leveraged funds, in E-mini equivalents (the CFTC changed its contract from $250
to $50 times the index on 2023-05-02), and the percentile of each among the 52 weeks ending
with it; each XNYS session gets the percentiles of its VIX close and of its SKEW among the
252 sessions ending with it. `plan` (read-only) says `fetch`, `record` or `reuse`; `record`
rewrites `formatted/market/margin_debt.csv`, `formatted/market/index_futures.csv` and
`formatted/market/vix_skew.csv`, caches of the levels alone, and writes the report
`reports/market/market_{FROM}_{TO}_{TOKEN}.html`, three charts on their own time axes,
margin debt by month, futures positioning by week and the VIX and the SKEW by session, always
served together, and its Markdown twin; `show` prints the twin recomputed from `raw/`.
Nothing adds a regime label.

### fundamentals

For each stock and each season (a fiscal period, named by its end) ending in a window of
New York dates (`--from`, `--to`; default the two years ending today), the domain compares the
season with stated baselines (the previous quarter, the same quarter last year, the previous
10-K, proxy statement or guidance, the previous four or eight seasons) over 69 items in nine
sections, from guidance and financials to the earnings call and the timing of the filings.
`fetch` writes, for the window's seasons and the four before them, each season's 10-K or 10-Q,
8-Ks with their exhibits, proxy statement, beneficial owners' schedules and Form 4s from SEC
EDGAR to `raw/{TICKER}/{PERIOD}/`, the company's XBRL facts, and the issuer's earnings-call
list and each call's transcript, with its speakers' names and roles, from EarningsCalls.dev.
`plan` names the next step; `derive` writes each document's text and each season's
`measures.md`, the 16 items Python computes; the bot writes each season's
`reports/{TICKER}/{PERIOD}/readings.md`, the 51 items read from the documents with verbatim
quotes, which `check` validates; `render` writes the season report
`report_{TOKEN}.md` beside them, each item's level (`red`, `yellow`, `grey`, `none` or a
status saying why there is no comparison) with its evidence and a score counting the triggered
items, and `show` prints the newest report of each ticker and ranks the tickers by score.
Every comparison is mechanical; no valuation, forecast or advice is added.

### posts

For each poster of `posts/watchlist.json` (the bot's: each poster with their accounts, by
platform), the bot keeps `posts/<poster>/`, a `profile.md` and the three sections of
`data/`, all by hand and with no script. When the user asks about a poster and an interval
(New York instants; "yesterday" is the previous New York calendar day), the bot reads each
account's posts over the parts of the interval no raw file of the account covers, by the
route its host offers, and writes them verbatim, whether or not they answer the question,
as `raw/{LABEL}_{START}_{END}_{TOKEN}.md`; fact-checks each post claim by claim in
`formatted/` under the same name, primary sources first, every verdict cited (a post is
`fake` when one of its claims is, `true` when one at least is and none is `fake` or still
pending, and `unverified` otherwise); and writes `reports/{SLUG}_{TOKEN}.md`, the posts that
answer the request, verbatim with their verdicts. A task the bot schedules on its host
checks again once a day every claim still pending and recounts each profile's credibility.
Nothing adds a score, a label, a ranking, a sentiment or advice.
