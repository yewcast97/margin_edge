# Market regime

This domain records, per ticker and per XNYS session, option-implied volatility indicators
from EODHD's end-of-day option chains, the percentiles of two of them over the 252 sessions
ending at each session, and the correlations of the stock's daily return (from Tiingo's
end-of-day prices) with the day-over-day changes of two of them, over a look-back window,
and charts them. This file says what the work aims at, what its table and reports hold and
mean, how each value is obtained, and how the code and the raw files are built, with the
provider facts verified live. The operations are in [PROCEDURE.md](PROCEDURE.md). The
conventions every domain shares (the layout, the three sections of `data/`, selection,
freshness, New York time, the session calendar and the API rule) are in
[market_state_research/AGENTS.md](../AGENTS.md).

## Aim

For each ticker, a reproducible record of the indicators below as of each session's close,
and a report of the window that is read whole: two charts, the percentiles and the
correlations, each over the stock's adjusted close, served together also when one indicator
is asked about, since either half alone biases the reading. Its values are computed from the
providers' quotes and prices by the stated method, with dates, coverage and a reason
wherever a value is absent. The record names no regime, applies no threshold and gives no
advice; the analyst reads it.

## The indicators

| Indicator | Column | Meaning | Unit |
| --- | --- | --- | --- |
| Skew percentile | `skew_14d_percentile` | Where the session's 14-DTE skew lies among the 252 XNYS sessions ending with it (below). | 0–100 |
| ATM IV percentile | `atm_iv_14d_percentile` | Where the session's 14-DTE ATM IV lies among the 252 XNYS sessions ending with it. | 0–100 |
| 14-DTE 25Δ skew | `skew_14d_pp` | The implied volatility of the put at delta −0.25 minus that of the call at +0.25, at 14 calendar days to expiry, sign kept: positive where puts are dearer. | percentage points (pp) |
| 14-DTE ATM IV | `atm_iv_14d_pct` | The mean of the implied volatility of the call at delta +0.50 and of the put at −0.50, at 14 calendar days to expiry. | percent |
| Return–call IV correlation | `call25_corr_15s` | The correlation, over the 15 XNYS sessions ending with the session, of the stock's daily return with the change of the 14-DTE 25Δ call IV since the previous session (below). | −1 to 1 |
| Return–put IV correlation | `put25_corr_15s` | The same with the 14-DTE 25Δ put IV. | −1 to 1 |

The percentiles and the correlations are the domain's aim; the two values are what the
percentiles rank. Every value they rest on is archived in the table: the 14-DTE 25Δ call
IV (`call25_iv_14d_pct`) and put IV (`put25_iv_14d_pct`), the IV at +0.25Δ and −0.25Δ in
percent, interpolated to 14 days like the skew; the daily return (`daily_return_pct`); and
the two adjusted closes it is computed from.

## Method

Everything here is computed from one session's own chain (the raw unit below) and the
newest prices file, with exact fractions, and rounded half-even once at the end; zero is
written without a sign (`surface.py`, `percentile.py`, `prices.py`, `correlation.py`).

- **A quote is usable** when its `volatility` (IV) is above 0, its `delta` is given and its
  `ask` is above 0.
- **IV at a target delta, at one expiry**: the usable contracts of one type are ordered from
  in the money to out of the money (calls by rising strike, puts by falling strike). The IV
  is that of the first contract whose delta equals the target, or else interpolated
  linearly in delta between the first adjacent pair whose deltas lie on either side of it.
  Nothing is extrapolated: without such a contract or pair there is no reading, and the
  reason says which type and target lack one.
- **At one expiry**, the 25Δ skew is (put IV at −0.25 − call IV at +0.25) × 100, the ATM IV
  is (call IV at +0.50 + put IV at −0.50) / 2 × 100, and the 25Δ call and put IVs are the
  IVs at +0.25 and −0.25 × 100.
- **At 14 days**: the brackets are expiries that give all four readings (call +0.25, put
  −0.25, call +0.50, put −0.50). E1 is the last such expiry the session lists 1 to 14
  calendar days out and E2 the first such one it lists 14 or more days out (within 65
  days, the window a raw file keeps). An expiry nearer to 14 days that lacks a reading (a
  stray listing of one strike, a side without usable quotes) is skipped, and the report
  names it with why. An expiry exactly 14 days out that gives every reading is both
  brackets and gives its own values (`exact`); otherwise each value is interpolated
  linearly in calendar days between E1's and E2's (`interpolated`). A session without E1
  or E2 has no value (`none`, with the reason, which names any expiry skipped); a session
  with both has all four. Nothing is extrapolated or carried forward. Every value is rounded to two decimal places;
  the per-expiry readings in the table are rounded the same way, for reading only (the
  14-DTE value is computed from the exact readings).
- **Percentile of session D**: over the 252 XNYS sessions ending with D, 100 × the number
  of the other 251 sessions whose value is strictly below D's / n, n being the number of
  those sessions that have a value; equal values are not counted. It compares the rounded
  values, is rounded to one decimal place, and is shown with n. There is none when D has no
  value, when any of the 252 sessions has no fetched chain (the reason counts them and names
  the first), or when n is 0. A session whose chain is fetched but empty (EODHD lists no
  contract then, such as before a listing) counts as fetched and has no value.
- **Daily return of session D** = (adjClose(D) / adjClose(P) − 1) × 100, P being the XNYS
  session before D, both bars from the newest prices file (one adjustment for splits and
  dividends), exact from Tiingo's text and rounded to four decimal places. There is none,
  with the reason, where either bar is absent.
- **IV change of session D** = the rounded 14-DTE call IV of D − that of P (likewise the
  put IV), exact, at the finer of the two values' precisions, zero without a sign. There is
  none, with the reason, where P is not fetched or either session has no value: nothing
  crosses a gap.
- **Correlation of session D**: the sample Pearson coefficient of the 15 pairs (return(t),
  IV change(t)) of the 15 XNYS sessions t ending with D, contemporaneous, computed exactly
  from the archived (rounded) values, one square root included, and rounded to two
  decimal places. There is none, with the reason, when any of the 16 sessions to D (the
  15 and the one before them, which the first return and change rest on) has no fetched
  chain, when a pair session lacks its return or its change (the reason counts them and
  names the first, with its own reason), or when either series is constant over the 15.
  The correlations have no percentile.

A name with monthly expiries only (AEP; possibly others) lists an expiry 1 to 14 days out
only in the ten or so sessions before each monthly expiry, so its 14-DTE values exist on
those sessions alone: its percentiles then rest on few sessions, and it never has the 16
consecutive valued sessions a correlation needs. Every other session is a gap with the
reason `no expiry is listed 1 to 14 days out (…)`, which the chart's banner lists.

## Sessions, chains, prices, window and span

- The unit of time is the XNYS session of the pinned exchange calendar. A chain holds
  session D's quotes as of D's close; it is fetched after that close, and a chain fetched
  before the close, dated later than the command's clock, or of a day that is not a
  session, is invalid.
- Of a session's valid chains the newest (by `fetched_at`, then by name) is its chain; a
  session without one is not fetched. Nothing edits `raw/`; a chain is withdrawn by renaming
  it `.rejected`.
- The window is N sessions ending at the latest completed session, `as_of`
  (`--lookback N`, default 50); the span adds the 251 sessions before it that the window's
  percentiles need. Reports carry N in their names and state how many of the N are fetched.
- The ticker's prices are its newest valid prices file. They are **current** when that file
  ends at `as_of` and starts no later than the session before the earliest session a row
  needs (the span's first, or an older fetched one), so every row's return has both its
  bars. Each `fetch` writes a new file of that whole range while the newest is not current:
  Tiingo re-adjusts every earlier bar at each split or dividend, and one file gives every
  return one adjustment.

## The formatted table

`formatted/{TICKER}/volatility.csv`, rewritten from `raw/` by `record` and replaced only when
its bytes would change: one row per fetched session, those before the window included,
ascending by date, holding every value the percentiles and the correlations rest on. Python
compares it by bytes and never parses it. Columns, in order:

| Column | Contents |
| --- | --- |
| `date` | The session, `YYYY-MM-DD`. |
| `skew_14d_pp`, `atm_iv_14d_pct` | The 14-DTE skew and ATM IV, two decimal places, or blank. |
| `skew_14d_percentile`, `atm_iv_14d_percentile` | The percentiles, one decimal place, or blank. |
| `call25_iv_14d_pct`, `put25_iv_14d_pct` | The 14-DTE 25Δ call and put IVs, two decimal places, or blank: the values whose changes the correlations take. |
| `daily_return_pct` | The daily return, four decimal places, or blank. |
| `call25_corr_15s`, `put25_corr_15s` | The correlations, two decimal places, or blank. |
| `method` | `exact`, `interpolated` or `none`. |
| `expiry_k`, `days_to_expiry_k` (k = 1, 2) | E1 and E2 and their calendar days out; bracket 2 is blank for `exact`, both for `none`. |
| `call25_iv_k_pct`, `put25_iv_k_pct`, `call50_iv_k_pct`, `put50_iv_k_pct` | The IV readings at bracket k, in percent, or blank. |
| `skew_k_pp`, `atm_iv_k_pct` | The two values at bracket k, or blank. |
| `skipped_expiries` | The expiries skipped as brackets for lacking a reading, ascending, separated by spaces, or blank. |
| `skew_window_n`, `atm_window_n` | The n each percentile rests on, or blank without a percentile. |
| `adj_close`, `previous_adj_close` | The adjusted closes of the session and of the XNYS session before it, as Tiingo wrote them, or blank. |
| `fetched_at` | When the chain was fetched, ISO 8601 with its New York offset. |
| `source` | The raw file name of the session's chain. |
| `price_source` | The raw file name of the prices the row's bars come from, or blank. |

## Reports

`record` writes the report `reports/{TICKER}/{TICKER}_{AS_OF}_{N}s_{TOKEN}.html` and, just
before it, its Markdown twin `.md`; `TOKEN` is the time of the `record` that wrote them, and
neither is ever overwritten. `show` prints the twin's text recomputed from `raw/`.

The report is one self-contained page (the chart library inlined; it opens offline) of one
window, and one whole: its two charts are served and read together, never one alone.

- Two charts on one time axis, one above the other (the line between them can be dragged):
  the skew percentile and the ATM IV percentile on a fixed 0–100 scale, and the return–call
  and return–put IV correlations on a fixed −1 to 1 scale with a line at 0. Each draws the
  stock's adjusted close under its two series, dotted, on a left scale of its own: the
  context the indicators are read against, never compared with them by height, as the two
  scales are aligned by nothing. A line breaks where a session has no value; a dot marks
  each value beside a break. The 14-DTE skew and ATM IV that the percentiles rank are in the
  data table, not charted.
- A readout, under the pointer or stepped with the arrow keys, naming the session, its
  method and bracket expiries (`interpolated · 2026-10-16 (11d) → 2026-10-23 (18d) ·
  skipped 2026-10-19 (14d)`) or why it has none, and six values (`—` where blank): the two
  percentiles with their n, the two correlations, the adjusted close and the daily return.
  It keeps the height of its tallest session, so the chart never moves as the session shown
  changes. Fit all shows the whole window again.
- A header with the ticker, `as_of`, coverage (fetched sessions of the N), the generation
  time, the table's path, the prices file and the sources; banners listing the missing
  sessions and, per series, the fetched sessions without a value.
- A collapsible data table with one row per window session (the six series, the 14-DTE call
  and put IVs, the daily return and the adjusted close, the method with each bracket's
  readings and the strikes each IV was read at, the fetch time and the raw file; `missing`
  where absent), its header generated with the rows, followed by the gaps: each fetched
  window session's series without a value, with the reason.
- A footer stating the method and the chart library's attribution.

The twin holds the same statements and tables as Markdown text.

## Freshness, missing data and what is never added

- A report is fresh while it is exactly what `record` would write now, apart from its
  generation time (the shared rule). A chain added or withdrawn for any session that changes
  what the report shows (one before the window included, since the percentiles rest on 252
  sessions and the correlations on 16), a new prices file, and a change of the method, the
  rendering code, the template or the chart library each make the newest report stale;
  `plan` then says `record`.
- Two absences are kept apart and each is named: a session not fetched
  (`missing_sessions` in the window, `missing_history` before it) and a gap (a fetched
  session without a value, a percentile or a correlation, with its reason: `gaps`).
- Validation is never weakened to admit a file; a raw file that fails it counts as absent
  until it is renamed `.rejected`, and `record` and `show` refuse while one exists.
- No regime label, threshold, moving average, ranking or trading advice is added anywhere.

## Commands

Run from the repository root as
`uv run --locked python -m market_state_research.market_regime.script COMMAND`, each taking
`--lookback N` (default 50) and `--data-dir PATH`:

| Command | Does |
| --- | --- |
| `fetch [TICKER ...] [--refresh] [--budget R] [--watchlist PATH]` | The one network command (needs `TIINGO_API` and `EODHD_API`). First, for every ticker whose prices are not current, one request to Tiingo; then the chain of every span session `raw/` lacks: the latest session of every ticker, then the older sessions ticker by ticker. Stops cleanly, keeping every file written, at EODHD's daily quota or after R requests to EODHD (default 9,000); no answer of Tiingo stops the chains. |
| `plan [TICKER ...] [--refresh] [--watchlist PATH]` | Read-only. Per ticker: `action` (`fetch`, `record` or `reuse`), the window sessions not fetched, the sessions before the window not fetched, the prices, gaps, invalid raw files, the table and the newest report's freshness. |
| `record TICKER [--partial]` | Rewrites the table from `raw/`; writes the report and its twin when every span session is fetched and the prices are current, or with `--partial` when a window session is fetched. Refuses while a raw file of the ticker is invalid. |
| `show TICKER` | Read-only: one status line, then the twin recomputed from `raw/`. |

Without tickers, `fetch` and `plan` take the `stock` section of this domain's
`watchlist.json` when it exists, else of the repository-root one, and print the file they
read. A command that succeeds exits 0 and prints JSON (`show`: Markdown); a refusal exits 2
with one `REGIME: ...` line on standard error. `plan`, `record` and `show` read no setting.
[PROCEDURE.md](PROCEDURE.md) gives each field and the step that follows.

## Architecture

The package `market_state_research.market_regime.script`:

| Module | Responsibility |
| --- | --- |
| `__main__` | The command line (`REGIME` label); builds the EODHD client from `EODHD_API` and the Tiingo client from `TIINGO_API` for `fetch` only, before the watchlist is read. |
| `client` | HTTPS to `eodhd.com` only, the key appended at send time and redacted from every message, pacing, the budget, statuses (402 `QuotaExceeded`, 429 retried once after `Retry-After`), bounded and whole bodies. Its HTTP reading helpers are copies of the fundamentals domain's (domains never import one another); `tiingo` shares them. |
| `tiingo` | HTTPS to `api.tiingo.com` only, the key only in the `Authorization` header, never in a URL; statuses (404 `NotCovered`, 401, 403 and 429 `Stopped`); bounded and whole bodies. |
| `api` | The EODHD queries and their URLs, one page per query (never a second page), page parsing with numbers kept as literal text, the record checks (OCC symbol against expiry, type and strike; number, date and word forms). |
| `chain` | The chain raw unit: its bytes (`dump`, `load`), its name, its window (`WINDOW_DAYS`), every rule (`check_chain`) and the proof that a contracts listing is a session's (`proof_problem`). |
| `prices` | The prices raw unit: its bytes, its name, Tiingo's bars (`parse_bars`, `check_bar`), every rule (`check_prices`) and the daily return. |
| `surface` | The method: IV at a target delta, the per-expiry values, the brackets (expiries without every reading skipped), the 14-DTE values. |
| `percentile` | The 252-session percentile. |
| `correlation` | The IV change and the 15-session correlation. |
| `store` | Reading and validating every raw file of a ticker, the selection of each session's chain and of the prices, the rows (values, percentiles, returns and correlations over the whole archive), the six series a report states (`SERIES`), the CSV. |
| `chart` and `templates/chart.html` | The report (two charts on one page) and its twin; the vendored TradingView Lightweight Charts 5.2.1 in `vendor/`, pinned by SHA-256. |
| `fetch` | The two ways a chain is fetched (below), writing each chain as it completes, and the prices request. |
| `workflow` | `plan`, `fetch`, `record`, `show`. |

## The raw units

### Chains

`raw/{TICKER}/chain_{DATE}_{TOKEN}.json.gz` (`_N` before `.json.gz` for a second file of one
second), written only by `fetch`: gzip (level 9, mtime 0, so equal content gives equal bytes)
of one JSON object with exactly these keys, in this order:

| Key | Contents |
| --- | --- |
| `session` | The session `DATE`. |
| `ticker` | The ticker. |
| `fetched_at` | When the chain was completed, New York ISO time with its offset; `TOKEN` names it to the second. |
| `source` | `contracts` (the latest session, from the contracts listing) or `eod` (from sweeps of `eod` records). |
| `window_days` | 65: the rule the file was cut by. A file of another window is refused, so changing it means fetching again. |
| `requests` | The token-free queries whose pages supplied the file. |
| `expiries` | Every expiry the session lists 1 to 65 days out, ascending, each `{exp_date, contracts}`. |
| `rows` | Every contract of every listed expiry, usable or not, as the provider's items (`id`, `type`, `attributes`), numbers as the provider's literal text in JSON strings (`"0.2751"`). |
| `traded` | `contracts` only: the `eod` records dated the session of the contracts last traded on it, within the window; else null. |

Every expiry within the window is kept, so the horizon (`surface.HORIZON`, 14) is a rule
of the derivation, not of the file, and can move without a new fetch. The cost is size and
time, measured on 2026-10-19: MU's chain of 2026-10-16 (Monday, Wednesday and Friday
expiries) holds 11 expiries, 4,696 contracts and 2,485 traded records, 0.2 MB gzipped,
validated in 0.07 s; INTC's (Friday expiries, and one stray Monday) 8 expiries, 1,070
contracts and 812 traded records, 55 KB, 0.02 s. A filled 301-session span of a name like MU
is thus about 60 MB, and every command validates it for about 20 seconds (`plan` over 301
synthetic chains of 5,400 contracts each took 15 s and 240 MB of memory). After validation
each chain keeps in memory only the rows of the expiries its values read, its brackets and
any expiry skipped before them (`store.trimmed`). The attributes kept are exactly `contract`, `exp_date`,
`expiration_type`, `type`, `strike`, `bid`, `ask`, `volume`, `open_interest`, `volatility`,
`delta` and `tradetime` (the `fields[...]` selection of every query).

Every read checks every rule again (`chain.check_chain`): the keys and forms; the name
against the session and the time; a session of the calendar, fetched after its close and
not after the clock; each record's OCC symbol against its expiry, type and strike, its root
equal to the ticker; rows only of listed expiries, as many per expiry as `expiries` lists,
each contract once, dated the session (`eod`), none traded after it; and for `contracts`
the proof below. A file that still holds a `horizon_days` key was cut by the former rule (a
30-day horizon, the two bracket expiries only) and is refused with `this chain was cut by
the former 30-day horizon rule; rename it .rejected and fetch the session again`.

### Prices

`raw/{TICKER}/prices_{END}_{TOKEN}.json.gz` (`_N` before `.json.gz` for a second file of one
second), written only by `fetch`: gzip, as a chain, of one JSON object with exactly these
keys, in this order:

| Key | Contents |
| --- | --- |
| `ticker` | The ticker. |
| `start`, `end` | The first and last day requested; `end` is the XNYS session `END`. |
| `fetched_at` | When the answer arrived, New York ISO time with its offset; `TOKEN` names it to the second. |
| `request` | The key-free URL requested (`tiingo.prices_url` of the ticker, `start` and `end`). |
| `bars` | Tiingo's daily bars from `start` to `end`, ascending, each with exactly `date`, `close`, `high`, `low`, `open`, `volume`, `adjClose`, `adjHigh`, `adjLow`, `adjOpen`, `adjVolume`, `divCash` and `splitFactor`, numbers as Tiingo's literal text in JSON strings. |

A bar's `date` (`2026-10-16T00:00:00.000Z`) is a day label: its `YYYY-MM-DD` names the
session and is never converted to New York time, which would name the day before. A file
holds either no bar (Tiingo has no prices for the ticker: written on its 404 or an empty
answer, so the ticker's prices count as current for that `end`) or a bar of `end`, the proof
that Tiingo has published that session. Every read checks every rule again
(`prices.check_prices`): the keys and forms; the request rebuilt from the ticker, `start`
and `end`; the name against `end` and the time; `end` a session not before `start`, fetched
after its close and not after the clock; every bar a session from `start` to `end`,
ascending, once each, with `close`, `adjClose` and `splitFactor` above 0 and its other
numbers not negative; no bar, or one of `end`. Every prices file is validated on every read
like a chain, and only the newest is read (by `fetched_at`, then by name). A file covers
the span and every older fetched session (INTC's 253 bars on 2026-10-19: 63,679 bytes,
10,787 gzipped); one is written a day per ticker.

## Fetching

EODHD offers no filter on a record's date, so a session's chain is reached one of two ways
(`fetch.py`):

- **The latest completed session** reads the contracts listing of the expiries 1 to 65 days
  out (every contract with its latest values) and the `eod` records of the contracts last
  traded on the session (`tradetime_eq`); a few requests a ticker. Those dated the session
  prove the listing is its: at least one, each equal (numbers as decimals) to its
  contract's listing row, which must exist, and no listing row traded after the session.
  None dated the session: the session is `pending` (not published yet) and nothing is
  written. A listing that fails the proof or lists no contract is left to the sweeps
  (`fallbacks`).
- **Older sessions** are reached by sweeps. The contracts listing names every expiry from the
  first session's next day to 65 days after the last, one calendar month at a time. From the
  latest expiry down, each expiry is swept whole per type: all its `eod` records, by strike.
  Each record goes to the session its `id` dates when that session is being fetched and the
  expiry lies 1 to 65 days after it; records of other dates (holiday copies among them) are
  dropped. A session is written, with every expiry's records, once every expiry after it
  within the window is swept, so sessions are written newest first and a stop loses only
  the sweeps in progress. A session no expiry lists gets an empty chain.

Every query is answered by its first page alone: EODHD orders records only by the sort key,
so records tying on it across a page boundary come back in another order on the next page
(facts below). A full page (`links.next` set) is used up to its last key: a listing is sorted
by expiry and a sweep by strike, so every record of a key below the page's last one is on it,
and the next query starts at that last key (`exp_date_from`, `strike_from`). A page holding
a single key is narrowed instead: one expiry to each type, one strike to its contract
(`filter[contract]`). Contracts whose OCC root is not the ticker (adjusted series such as
`AAPL1`) are dropped on arrival. A run takes the latest session of every ticker first, then
each ticker's older sessions. Costs measured live on 2026-10-18/19: 1.5 to 4 s a request;
AEP's span of 271 sessions (monthly expiries only) took 268 requests; one older session of MU
(Monday, Wednesday and Friday expiries) took 309 by sweeps, and the latest session about 4.
Sweeps of one expiry serve every session that lists it, so a whole span costs far less per
session than one session alone, but a dense name's span still takes several thousand. Both
ways gave identical chains on the sessions checked (AEP and MU on 2026-10-16: the same
expiries and contract counts and no field differing). With whole chains, the proof held on
2026-10-16 for every traded record: INTC's 812 and MU's 2,485 each equal their listing row.
On 2026-10-19 INTC's latest session took 3 requests by the listing (MU's 9), and 147 sweep
requests wrote the 17 INTC sessions before it (150 requests in 6 minutes, 2.5 s each; MU's
40 took 3.9 s each, full pages of 1,000 records taking the longest).

**The prices** take one request per ticker and run, before any chain, and only while the
ticker's prices are not current (or with `--refresh`): Tiingo's bars from the session
before the earliest one a row needs to `as_of`. They are written when they hold the bar of
`as_of`, or no bar at all (`empty`); without that bar the session is `pending` and nothing
is written. A refused key or the plan's request limit (`stopped`) leaves every later
ticker's prices unrequested; any other failure (`failed`) concerns that ticker alone. The
chains are fetched whatever Tiingo answered.

## EODHD facts verified live (2026-10-19)

- The marketplace product "US Stock Options Data" by UnicornBay:
  `https://eodhd.com/api/mp/unicornbay/options/{contracts,eod,underlying-symbols}`, GET, the
  key only as the `api_token` query parameter; OpenAPI files `paths/mp_unicornbay_options_*.yaml`
  at github.com/EodHistoricalData/eodhd-openapi. A wrong or missing key gets HTTP 401
  `Unauthenticated`.
- Pages: `{"meta": {"offset", "limit", "fields"}, "data": [{"id", "type", "attributes"}],
  "links": {"next": url | null}}`; `meta.fields` lists the attributes in the provider's own
  order, and is empty on a page without records; `links.next` never carries the key.
  `page[limit]` up to 1,000, `page[offset]` up to 10,000 (HTTP 422 beyond). Records are
  ordered only by the sort key, and records tying on it are not in a stable order between
  requests: MU's `tradetime_eq` query of 2026-10-16, sorted by expiry, returned 2,485 records
  in three pages, 51 of them on both page 1 and page 2, so 51 others were never returned.
  Hence no second page is ever requested. `compact=1` did not change the shape with a
  `fields` selection and is not used.
- Filters: `underlying_symbol`, `contract`, `exp_date_eq|from|to`, `tradetime_eq|from|to`,
  `type` (`call`, `put`), `strike_eq|from|to` (inclusive, decimal strikes such as `302.5`
  match); `sort` by `exp_date` or `strike` (records of one strike newest first).
- `eod` records: `id` `{OCC}-{YYYY-MM-DD}`, the session the record is for; one per contract
  per weekday, holidays included (Labor Day 2026-09-07 repeated 2026-09-04's values).
  `tradetime` is the contract's last trade date, at or before the record's date, null for a
  contract never traded; the `tradetime` filters select on it, never on the record's date,
  so they reach only traded contracts (AEP: 20 of 100 contracts within 65 days traded on
  2026-10-16). Never-traded contracts are reachable only by contract, expiry or strike
  filters, which return every date.
- `contracts` lists every contract ever (expired included) with its latest values; on the
  latest session its rows equal the `eod` records dated that session field for field.
- Numbers are JSON numbers: `volatility` a decimal IV to 4 places (0.2751 = 27.51 %), `delta`
  to 6, puts negative; `dte` and `moneyness` are not kept (`dte` counted the days to expiry
  minus one on the latest record and the full days on older ones).
- Quota: the product has its own 100,000 API calls per rolling 24 hours from its first
  request, ten calls per request (10,000 requests a day), apart from the main plan (on this
  key the free tier: no other EODHD endpoint may be used); HTTP 402 when spent. 1,000
  requests a minute (`X-RateLimit-Limit: 1200`); HTTP 429 with `Retry-After` beyond.
- History from 2023-10-02 (AAPL). Expiries: AAPL lists Monday, Wednesday and Friday expiries
  (11 within 65 days, about 1,900 contracts); a weekly expiry's contracts live about 40
  weekdays, a monthly about 240, a LEAPS-born monthly about 540; AEP lists only monthly
  expiries.
- A listed expiry may hold a stray contract or two: INTC lists Monday 2026-10-19 with one
  strike (190, a call with open interest 2 and a put). It is the last expiry 1 to 14 days
  out on 2026-10-05 to 2026-10-08 but gives no reading, which left those sessions without a
  14-DTE value and the correlations of the 16 sessions after them blank; since 2026-10-19
  the bracket rule skips it, and those sessions read 2026-10-16 and 2026-10-23. INTC's
  first live correlations followed (2026-10-16: 0.09 with the call IV change, −0.11 with
  the put's, as recomputed from the CSV alone).

## Tiingo facts verified live (2026-10-19)

- `GET https://api.tiingo.com/tiingo/daily/{TICKER}/prices?startDate=YYYY-MM-DD&endDate=YYYY-MM-DD`
  with the header `Authorization: Token {key}` answers 200 with a JSON array of daily bars,
  ascending, both dates included (an `endDate` of 2026-10-16 returned that session's bar on
  2026-10-19). A range without a session (a weekend) is `[]`.
- Each bar's keys, in order: `date`, `close`, `high`, `low`, `open`, `volume`, `adjClose`,
  `adjHigh`, `adjLow`, `adjOpen`, `adjVolume`, `divCash`, `splitFactor`; `date` reads
  `2026-10-16T00:00:00.000Z`; every other value is a JSON number (`102.81`, `98.225`,
  `88252043`, `0.0`, `1.0`), adjusted prices to as many as ten decimals
  (`182.2027894923`). No value was null in the answers read (INTC, AMAT, AAOI, NVDA).
- Adjustment: a dividend's ex-date carries `divCash` (AMAT 0.46 on 2025-08-21) and every
  earlier bar's adjusted prices are scaled down (AMAT 2025-07-01: `close` 183.76, `adjClose`
  182.2027894923), so `adjClose` equals `close` from the latest ex-date on; a split's date
  carries `splitFactor` (NVDA 10.0 on 2024-06-10) and every earlier bar's adjusted prices
  and volumes are scaled (2024-06-05: `close` 1224.4, `adjClose` 122.0923218538, `volume`
  52840178, `adjVolume` 528401780).
- An unknown ticker gets HTTP 404 `{"detail":"Error: Ticker 'ZZZZQQ' not found"}`; so does
  a class share written with a dot (`BRK.B`; Tiingo writes `BRK-B`). An invalid key gets
  HTTP 403 `{"detail":"Invalid token."}`.
- Size: AMAT's bars from 2025-07-01 to 2026-10-16, 327 of them, are 84,027 bytes; INTC's
  253 bars from 2025-10-15, as `fetch` wrote them, 63,679 bytes and 10,787 gzipped; MU's,
  17,502 gzipped.
- `fetch` on 2026-10-19 wrote INTC's and MU's prices in one request each, every rule of
  `check_prices` passing, and their returns agree with the closes (INTC 2026-10-16:
  89.85 / 95.37 − 1 = −5.7880 %).
- Documented, not observed: "Most US Equity prices are available at 5:30 PM EST, however
  exchanges may send corrections until 8 PM EST"; the Starter plan allows 50 requests an
  hour, 1,000 a day and 500 unique symbols a month; data of the Basic and Power plans is for
  internal and personal use and may not be redistributed, so no Tiingo answer is kept in
  `tests/`.

## Tests

`tests/market_regime/` runs offline: `fake_eodhd.py` answers both EODHD endpoints from
records in memory as EODHD does (filters, sort, fields, pages, the offset cap and, on
request, ties shuffled between requests; scripted statuses) and records every URL and
token; `fake_tiingo.py` answers Tiingo's prices endpoint from bars in memory as Tiingo does
(the date range, literal numbers, 404 for an unknown ticker; scripted statuses) and records
every URL and header token; `support.py` builds records from strike, delta and IV text (the
hand-worked quotes of `CALLS` and `PUTS`), chains, and bars and prices files from closes;
`fixtures/` holds the two pages recorded live for AEP on 2026-10-16, pinned by SHA-256 and
never edited. An autouse fixture refuses any real request.
