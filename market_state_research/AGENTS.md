# Market state research principles and architecture

Organize the research by **domain**: a domain discloses one aspect of the state of the market
and holds, in one folder, its guidance, its procedure, its code when it has any, and its
data. Every domain has one `AGENTS.md`, which
states the aim of the work and what its formatted data and reports hold and mean, then how
each value is obtained, the architecture, the raw files and the facts verified live of each
source it reads; and one `PROCEDURE.md`, its operations. Code that does not depend on a
source or a domain's data directory lives once in the shared `common/` package.

The domains are operated by the bot under rules the maintainer makes, as the root
[AGENTS.md](../AGENTS.md) defines both (Who does what): from its own host the bot runs the
commands and follows each domain's `PROCEDURE.md`, never edits a rule, and opens a GitHub
issue when one blocks or misleads it. In the two scripted domains, `stock_iv_regime` and
`fundamentals`, every source is read by Python through an API, so the bot needs a shell with
uv and network access, and no browser; in `posts` the bot reads each nominated account by
whatever route its host offers and writes every file itself. Nothing the bot produces is
tracked: every `data/` directory, every poster's folder and every watchlist is ignored by
Git.

## Folder structure

```text
market_state_research/
├── AGENTS.md
├── TODO.md             (the maintainer's backlog, ignored by Git)
├── common/             shared Python package, bound to no domain
├── <domain>/           a scripted domain: stock_iv_regime, fundamentals
│   ├── AGENTS.md
│   ├── PROCEDURE.md
│   ├── watchlist.json      (optional; the user's own, ignored by Git)
│   ├── script/
│   │   ├── templates/      (optional)
│   │   └── vendor/         (optional)
│   └── data/
│       ├── .gitignore
│       ├── raw/{TICKER}/
│       ├── formatted/{TICKER}/
│       └── reports/{TICKER}/
└── posts/              the domain without a script
    ├── AGENTS.md
    ├── PROCEDURE.md
    ├── watchlist.json      (the user's posters, ignored by Git)
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
| `TODO.md` | The maintainer's research scope and backlog, ignored by Git. |
| `common/` | Python shared by every domain: New York time and file-name tokens (`times`), XNYS sessions and market status for the domains that work by session (`sessions`), the three sections of a domain's `data/` with their one write rule (`layout`), ticker and one-line message text (`text`), the one-line `LABEL: ...` command-line conventions, with each domain's own label (`cli`), the watchlists, the repository-root one and a domain's own (`watchlist`), and the personal settings of the ignored repository-root `.env` (`env`). It knows no source, no raw format and no domain's data directory, and sends no network request. |
| `<domain>/AGENTS.md` | The domain's guidance: first the aim, the outputs and what they mean, the commands; then the method, the module boundaries, the raw files, each source's formats and facts verified live, the fixtures and vendored libraries. |
| `<domain>/PROCEDURE.md` | The domain's operations: settings, parameters, commands and their output fields (in `posts`, the steps the bot takes by hand), the routines, failure handling and the report back. |
| `<domain>/watchlist.json` | Optional: the domain's own watchlist, the user's and ignored by Git; it replaces the repository-root one for this domain (Watchlists). In `posts` it is required and lists posters, not tickers. |
| `<domain>/script/` | A scripted domain's Python package and supporting code; `posts` has none. |
| `<domain>/script/templates/` | Optional output templates read by the code, such as an HTML page. |
| `<domain>/script/vendor/` | Optional third-party files copied unmodified from a pinned release, with their licence, notice and provenance. |
| `<domain>/data/` | Runtime files in three sections, `raw/`, `formatted/` and `reports/` (Data layout). |
| `posts/<poster>/` | One nominated poster, the bot's and ignored by Git whole: `profile.md` (who the poster is, their accounts and the count of verdicts so far) and `data/` in the three sections. |

Domains import shared code from `market_state_research.common` instead of copying it, never
import one another, and `common` never imports from a domain. Keep generated data out of
`script/`, `common/` and documentation directories. `templates/` and `vendor/` hold static
assets owned by the code: change them together with the code and tests that use them. Keep
vendored files byte-identical to their upstream release, record their source and hashes
beside them, and have the code verify a pinned checksum before using a vendored library.
Ignore runtime data in Git; retain a `data/.gitignore` so a scripted domain's empty data
directory is present in fresh checkouts (a poster's folder in `posts` is the bot's, ignored
whole, and needs none). Scripts resolve their default data directory and their assets
relative to their own domain, independently of the current working directory. Tests live
in `tests/common/` and `tests/<domain>/` (`posts` has no code and none); synthetic test
data, watchlists included, belongs in isolated temporary directories, and the
repository-root `tests/conftest.py` fails the run if any test changes a domain's `data/`
directory or a poster's folder. Personal settings remain in the ignored repository-root
`.env`; Python reads it only through `common.env`, where the process environment takes
precedence, and never prints a value.

## Watchlists

The repository-root `watchlist.json` lists the user's default tickers for market state
research. Like `.env`, it is the user's own and ignored by Git, so a checkout has none until
the user writes it, and only the user edits it:

```json
{
  "stock": ["INTC", "MU", "AEHR", "AMAT", "TER", "AAOI"],
  "index": ["SPX"]
}
```

It holds exactly these two lists, each of distinct US ticker symbols in upper or lower case,
and no symbol is in both; either list may be empty. In the scripted domains, the
ticker-taking commands (`plan` and `fetch`) default to the `stock` section, in file order,
of the domain's own `watchlist.json` (beside its `AGENTS.md`, in the same format, also the
user's and ignored by Git) when it exists, else of the repository-root one; both are read
through `common.watchlist`, and a domain's file replaces the root one whole (nothing is
merged). Tickers given on the command line override both without reading either,
`--watchlist PATH` reads another file, and `plan` and `fetch` print the file they read
(`watchlist`, null when tickers are given). Without tickers, a file that is missing,
malformed or without a `stock` ticker stops either command with one line naming it. The
`index` section is reserved for index workflows. The watchlists belong to market state
research alone: hypothesis exploration reads none, and the list of posters in `posts` (its
`AGENTS.md`) is read by the bot, never by Python.

## Data layout

Every `data/` directory, a scripted domain's or, in `posts`, a poster's, holds exactly three
sections. In the scripted domains each section has one folder per ticker
(`raw/{TICKER}/`, ...), and Python writes them only through `common.layout`; in `posts` the
bot writes all three by hand, under that domain's `AGENTS.md`:

| Section | Contents | Written by |
| --- | --- | --- |
| `raw/` | What was fetched, verbatim, as the domain's `AGENTS.md` describes each file; in `posts`, every post of one account over one interval a human asked about. | `fetch`, the one network command of each scripted domain, and the bot only renames a file `.rejected`; in `posts`, the bot, once per file. |
| `formatted/` | What Python derives from `raw/`: the tables or texts the domain's `AGENTS.md` names; in `posts`, the fact-check of each raw file. | `record` in `stock_iv_regime`, `text` in `fundamentals`; the bot in `posts`. |
| `reports/` | What people read. | `record`, or `render` in `fundamentals`, where the bot also writes one report per document; the bot in `posts`, one report per request. |

- **A run keeps what is stored.** The raw files are the evidence every value rests on, and
  requesting them again costs quota and time: `fetch` requests only what the window lacks,
  never again what `raw/` holds, and leaves every stored file as it is. `--refresh` on
  `fetch` and `plan` is the one exception, used only when the user asks: it requests the
  window's data again whatever is stored and keeps every stored file (the domain's
  `AGENTS.md` says what it requests again and what becomes of an answer that differs from
  the stored copy). No command deletes or empties `raw/`. In `posts` a request reads only
  the parts of its interval that no raw file of the account covers, unless a human asks for
  a covered one to be read again.
- **`raw/` is the archive.** Python never modifies a raw file, and every command validates
  every raw file it reads, every time it reads it (the formats, the calendar and time
  rules and the other rules of the domain's `AGENTS.md`). The bot never edits a raw file
  either: it withdraws one as its `PROCEDURE.md` says (a file that failed validation) by
  renaming it with the suffix `.rejected`, which every read skips. In `posts`, where no
  validator exists, the bot writes each raw file once and withdraws one it finds wrong the
  same way.
- **`formatted/` is a function of `raw/`.** Its command (`record`, or `text`) rebuilds it and
  overwrites it; nothing there is the only copy of anything. In `posts` it is not: the
  fact-check of a raw file rests on the evidence found at each check as well, is updated in
  place with a dated history, cannot be rebuilt, and is kept like `raw/`.
- **`reports/` is never overwritten.** A report name that exists fails the command, and
  older reports stay until someone deletes them by hand. The fundamentals domain's
  per-document reports are the bot's: it may rewrite one until `check` passes it, and again
  after a field's definition changes (the domain's `AGENTS.md`). A `posts` report answers
  one request, under a name of its own, and is never rewritten.
- **Selection replaces bookkeeping.** Per key (a session's chain, a call's transcript) the
  newest file wins (the domain's `AGENTS.md` says what a key is), so a refresh writes a newer
  file beside the stored one, which wins from then on. Nothing records the selection: there
  are no ledgers, manifests, envelopes, version fields or lost-update guards. In `posts` an
  account's coverage is the union of the intervals its raw files' names give, and nothing
  else records it.
- **In the scripted domains, a report is fresh** while it is exactly what its command
  (`record`, or `render`) would write now, apart from its generation time, and `plan` says
  `reuse` only for a fresh report (the fundamentals `plan` also when no period is
  complete). The command writes a new report every time it runs while the data allow one.
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
  ([explore_hypothesis/AGENTS.md](../explore_hypothesis/AGENTS.md)) is the bot's own work:
  it may read and copy a domain's data, never changes it, and no domain reads a hypothesis.
- Work as of the last completed XNYS session and never on intraday live data. The bot may
  run at any time; a domain that reads market data fetches a session's end-of-day values
  only after its close, and a raw file fetched before the close of its session is invalid.
  Sessions, holidays and closes come from the pinned `exchange-calendars` release, which
  knows only closures announced before it was published: a raw file of a day that is not a
  session is invalid, and the pin is raised (with `uv lock`) when NYSE announces an
  unscheduled closure. A domain that reads no market data (`fundamentals`: filings,
  earnings releases and earnings-call transcripts; `posts`: what people say in public) has
  no session logic and dates its documents by their own dates.
- Python reads its sources only through APIs, each from a command of its own that `plan`
  names (`fetch`), only to the source's fixed hosts over HTTPS, with bounded bodies and no
  redirect followed: a public read-only API that publishes an access policy the client
  follows to the letter (SEC EDGAR, in `fundamentals`), or a provider's API under the
  user's own key, kept in the ignored `.env`, sent only to its host and never written,
  printed or stored (EODHD and Tiingo in `stock_iv_regime`, EarningsCalls.dev in
  `fundamentals`). No source of a scripted domain is read in a browser, and no command
  reads a setting it does not need. This rule binds Python. `posts` has none: the bot reads
  each nominated account by the route its host offers (its own integration with the
  platform, the platform's API under the user's key, kept in `.env` as `{PLATFORM}_API`,
  or a browser on the host), names the route in every raw file, and never asks for a
  credential in the conversation.
- Use New York exchange time (America/New_York, EDT or EST) and no other time zone: stored
  timestamps, file-name timestamps, JSON, Markdown and HTML output, messages, documentation
  and tests. Write instants as ISO 8601 with their offset (`2026-10-06T05:09:17-04:00`),
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
| [`stock_iv_regime`](stock_iv_regime/AGENTS.md) ([procedure](stock_iv_regime/PROCEDURE.md)) | Per session, the 14-DTE 25Δ skew and ATM IV and their 252-session percentiles, and the 15-session correlations of the stock's daily return with the changes of the 14-DTE 25Δ call and put IVs, over a look-back window, in two charts read together. | EODHD options API (`EODHD_API`) and Tiingo daily prices (`TIINGO_API`). |
| [`fundamentals`](fundamentals/AGENTS.md) ([procedure](fundamentals/PROCEDURE.md)) | What each stock issuer's own documents of each fiscal period say, in eleven fields of verbatim quotes, compiled into a time series. | SEC EDGAR (`SEC_USER_AGENT`) and the EarningsCalls.dev transcript API (`EARNINGSCALLS_API`). |
| [`posts`](posts/AGENTS.md) ([procedure](posts/PROCEDURE.md)) | Per nominated poster, every post of the intervals a human asked about, archived verbatim and fact-checked claim by claim against cited evidence (`true`, `unverified` or `fake`); a profile with the poster's background and the count of verdicts so far; a report per request. | The poster's accounts, by the route the bot's host offers (a key only when that route is a platform's API: `{PLATFORM}_API`); evidence from primary sources first. |

### stock_iv_regime

For each ticker, `fetch` first writes its daily prices from Tiingo as
`raw/{TICKER}/prices_{END}_{TOKEN}.json.gz` whenever the newest are not current, then each
XNYS session's option chain from EODHD as `raw/{TICKER}/chain_{DATE}_{TOKEN}.json.gz`
(every contract of every expiry 1 to 65 days out): the latest completed session from the
contracts listing, proved to be that session's by its traded records, and older sessions
from sweeps of each expiry's end-of-day records, until the run's budget or EODHD's daily
quota stops it cleanly. From each chain, the IV at deltas ±0.25 and ±0.50 is read at the
last expiry 1 to 14 calendar days out and the first one 14 or more days out that give all
four readings (an expiry that does not is skipped and named), and the 25Δ
skew (put minus call, pp), the ATM IV (%) and the 25Δ call and put IVs (%) are
interpolated to 14 days; the skew and the ATM IV are each ranked among the 252 sessions
ending with them, and the stock's daily return (from Tiingo's adjusted closes) is
correlated over 15 sessions with the change of the 14-DTE call IV and with that of the put
IV. `plan` (read-only) says `fetch`, `record` or `reuse`; `record` rewrites
`formatted/{TICKER}/volatility.csv` and writes the report
`reports/{TICKER}/{TICKER}_{AS_OF}_{N}s_{TOKEN}.html`, which inlines the vendored TradingView
Lightweight Charts library and draws two charts over the stock's adjusted close, the
percentiles and the correlations, always served together, and its Markdown twin; `show`
prints the twin recomputed from `raw/`. Nothing adds a regime label.

### fundamentals

For each stock and each fiscal period ending in a window of New York dates (`--from`,
`--to`; default the two years ending today), the domain records what each of the period's
documents says in eleven fields of verbatim quotes: `upstream_shortage`,
`capacity_shortfall`, `capex_plans`, `capacity_expansion`, `earnings_guidance`, `pricing`,
`backlog_contracts`, `product_ramp`, `margin_drivers`, `financing_methods` and
`customer_concentration`. `fetch` writes the submissions JSON, each period's 10-K or 10-Q
and its Item 2.02 8-Ks' filing index pages and EX-99 exhibits from SEC EDGAR to
`raw/{TICKER}/edgar/`, and the issuer's earnings-call list and each call's transcript, with
its speakers' names and roles, from EarningsCalls.dev to `raw/{TICKER}/calls/`. `plan` names
the next step; `text` writes each document's text to `formatted/{TICKER}/{DOC_ID}.md`; the
bot writes `reports/{TICKER}/{DOC_ID}.md`, which `check` validates (a call is quoted only
from its executives); `render` writes the time series `{TICKER}_{AS_OF}_{TOKEN}.md` beside
them, and `show` prints it. Nothing is paraphrased; no valuation, forecast or advice is
added. The watchlist's `index` section plays no part in it.

### posts

For each poster of `posts/watchlist.json` (the user's: each poster with their accounts, by
platform), the bot keeps `posts/<poster>/`, a `profile.md` and the three sections of
`data/`, all by hand and with no script. When a human asks about a poster and an interval
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
