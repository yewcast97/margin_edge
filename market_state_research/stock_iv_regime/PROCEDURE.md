# Stock IV regime: 14-DTE skew and ATM IV percentiles, return–IV correlations

This procedure keeps each ticker's 14-DTE indicators, their 252-session percentiles and the
15-session correlations of its daily return with the changes of its 14-DTE 25Δ call and put
IVs current from EODHD's options API and Tiingo's daily prices, and writes the report (two
charts on one page) with its Markdown twin. `plan` says what is missing, `fetch` writes it,
`record` writes the table and the report. What the values mean, how they are computed and
what the raw files hold are in [AGENTS.md](AGENTS.md).

Run every command from the repository root:

```sh
uv run --locked python -m market_state_research.stock_iv_regime.script COMMAND ...
```

A command that succeeds exits 0 and prints JSON (`show`: Markdown), also when sessions are
missing, when `fetch` stopped at its budget or EODHD's quota, and when Tiingo refused or
failed to give a ticker's prices. A command that fails exits 2 with one
`STOCK_IV_REGIME: ...` line on standard error and prints nothing else.

## 1. Settings and parameters

`fetch` needs two keys, in the environment or the repository-root `.env`: `EODHD_API`, the
user's EODHD key with the marketplace product "US Stock Options Data" (UnicornBay), and
`TIINGO_API`, the user's Tiingo key. Never print, copy or write either value; `fetch`
reports them only as `"eodhd_key": "set"` and `"tiingo_key": "set"`.

| Parameter | Default | Meaning |
| --- | --- | --- |
| `--lookback N` | 50 | The window's length in sessions. Use the same N for every command of one run. |
| `TICKER ...` | the tickers of the watchlist | `fetch` and `plan` take any number; `record` and `show` take one. |
| `--watchlist PATH` | this domain's `watchlist.json`, which you maintain ([market_state_research/AGENTS.md](../AGENTS.md), Watchlists) | `fetch` and `plan`: the file read when no ticker is given, which both print as `watchlist` (null when tickers are given). |
| `--refresh` | off | `fetch` and `plan`: treat every window session as missing, whatever is stored, and request the prices again. Use it only when the user asks, on one `fetch`, and plan afterwards without it. |
| `--budget R` | 9000 | `fetch`: the most requests the run sends to EODHD. |
| `--partial` | off | `record`: write the report although sessions are not fetched or the prices are not current (section 4). |
| `--data-dir PATH` | `market_state_research/stock_iv_regime/data` | Every command; another directory for isolated checks. |

## 2. Plan

```sh
uv run --locked python -m market_state_research.stock_iv_regime.script plan --lookback 50
```

Per ticker:

| Field | Meaning |
| --- | --- |
| `action` | `fetch`, `record` or `reuse` (below). |
| `as_of` | The latest completed session. |
| `window` | `{start, end, sessions, span_start}`: the window, and the first session the percentiles need. |
| `missing_sessions` | Window sessions without a fetched chain, newest first; with `--refresh`, every window session. |
| `missing_history` | `{sessions, first, last}` of the sessions before the window, within the span, without a fetched chain. |
| `prices` | `{status, path, start, end, bars, reason}` of the newest prices file: `current`, `stale` (the `reason` says why) or `missing`. |
| `gaps` | `{date, series, reason}` of each fetched window session's series without a value, a percentile or a correlation. |
| `invalid_files` | `{path, reason}` of each raw file that failed validation; it counts as absent. Handle each first (section 5). |
| `csv` | The table's path, or null. |
| `report` | `{status, path, reason}` of the newest report of this window: `fresh`, `stale` (with a reason) or `missing`. |

| `action` | When | Next step |
| --- | --- | --- |
| `fetch` | A window session (`missing_sessions`) or a session before the window that the percentiles need (`missing_history`) has no chain, or the prices are not current; always with `--refresh`. | Run `fetch` (section 3), then `plan` again. |
| `record` | Everything is fetched, but the table is missing or differs from what `raw/` gives, or the newest report is not fresh. | Run `record` (section 4). |
| `reuse` | The table matches `raw/` and the newest report is fresh. | Report `report.path`; nothing to do. |

## 3. Fetch

```sh
uv run --locked python -m market_state_research.stock_iv_regime.script fetch --lookback 50
```

The run first asks Tiingo for the prices of every ticker whose prices are not current, one
request each; then it fetches the latest session of every ticker from EODHD (2 to 7
requests each), then the older sessions ticker by ticker. It prints `eodhd_key` and
`tiingo_key` (`set`), `budget`, `requests` (sent to EODHD in the run), `price_requests`
(sent to Tiingo), `stopped` (null, or `{ticker, reason}`: EODHD only), `watchlist` and per
ticker:

| Field | Meaning |
| --- | --- |
| `prices` | `{status, path, reason}`: `new` (written), `reused` (current already), `empty` (Tiingo has no prices for the ticker: an empty file is written, and the correlations stay gaps), `pending` (Tiingo has not published the latest session yet), `failed` or `stopped` (section 5). |
| `fetched` | `{sessions, first, last}` written in this run. |
| `empty` | Sessions written with an empty chain: EODHD lists no contract for them (before the ticker's options were listed, for one). They count as fetched and have no value. |
| `pending` | The latest session when EODHD has not published it yet. Run `fetch` again later; once a newer session completes, the sweeps fetch it. |
| `fallbacks` | `{date, reason}` where the contracts listing could not supply the latest session; the sweeps of the same run fetch it. Report the reasons. |
| `remaining` | `{sessions, first, last}` of the span sessions still without a chain. |
| `requests` | Requests this ticker took from EODHD. |
| `invalid_files` | As in `plan`. |

`stopped` names why the run ended early, every file already written being kept:

- `the run's budget of R requests is spent`: run `fetch` again (the next day when the daily
  quota is near: a run of 9,000 requests leaves about 1,000 of the day's 10,000).
- `EODHD's daily quota ... is spent`: run `fetch` again after 24 hours.

Each EODHD request takes 1.5 to 4 s (a full page of 1,000 records the longest), so a run of
9,000 requests takes four hours or more.
Every command validates every raw file of a ticker: once a span is filled, a name with
Monday, Wednesday and Friday expiries (MU) takes about 20 seconds per command, one with
Friday expiries (INTC) a few seconds.

### A regime request

When the user asks for a ticker's regime over a window, N is the window in sessions (three
weeks: `--lookback 15`); without a window named, keep the default 50. Run
`fetch TICKER --lookback N`, which requests only what the span lacks, then
`plan TICKER --lookback N`, then `record TICKER --lookback N` when the action is `record`,
and hand over `report.path` with its twin and the latest values (section 5). The report is
one whole: deliver its two charts, the percentiles and the correlations, together, also when
the user asks about one indicator, and never describe one chart without the other. A ticker
new to `raw/` needs its whole span first (backfill, below); until then, record with
`--partial` only when the user asks for a report now.

### Daily routine

Once a day, after 8 PM New York time (Tiingo publishes a session's prices from 5:30 PM and
takes corrections until 8 PM), run `fetch` and then `plan`, and `record` each ticker whose
action is `record`. A ticker whose latest session or prices are `pending` is not published
yet: run `fetch` again later. A day's latest sessions cost about 250 EODHD requests and one
Tiingo request per ticker for the whole watchlist.

### Filling the history (backfill)

A ticker new to `raw/` lacks its whole span (301 sessions with the default window): a few
hundred requests for a name with monthly expiries only (AEP's 271 sessions took 268), several
thousand for one with weekly or Monday, Wednesday and Friday expiries; the default watchlist
likely takes one to two weeks of daily runs. Run `fetch` once a day without tickers until `plan` says
`record` for every ticker, keeping the default budget; `remaining` shrinks each day. Do not
split one ticker's history across budgets smaller than about 1,000 requests: the sweeps in
progress when a run stops are fetched again.

### Chains of the former 30-day rule (2026-10-19)

Chains fetched before 2026-10-19 kept only the two expiries bracketing 30 days; every read
now refuses them with `this chain was cut by the former 30-day horizon rule; rename it
.rejected and fetch the session again`, so `plan` lists each under `invalid_files` (about
301 per filled ticker). Rename each such file with `.rejected` (never delete one), then fill
the span again as for a new ticker (backfill, above).

## 4. Record

```sh
uv run --locked python -m market_state_research.stock_iv_regime.script record TICKER --lookback 50
```

| Field | Meaning |
| --- | --- |
| `window`, `missing_sessions`, `missing_history`, `gaps` | As in `plan`. |
| `sessions` | `{date, fetched_at, source, method, expiries, skew_14d_percentile, atm_iv_14d_percentile, skew_14d_pp, atm_iv_14d_pct, call25_corr_15s, put25_corr_15s, call25_iv_14d_pct, put25_iv_14d_pct, daily_return_pct}` of each fetched window session. |
| `csv` | `{path, rows, written}`; `written` is false when the file already held these bytes. |
| `report` | `{status, path, markdown, reason}`: `written` (the report and its twin) or `pending` (no report; the `reason` names what is not fetched or not current). |

Without `--partial`, the report waits until every span session is fetched and the prices
are current. Pass `--partial` only when the user asks for a report now or a session or the
prices cannot be fetched (section 5); its banners and gaps then name every absence.

`show TICKER` prints one status line and the twin recomputed from `raw/`, for reading the
window without writing anything.

## 5. Report back and failures

Report per ticker the action taken, `as_of`, coverage (fetched window sessions of N), the
latest values with their percentiles and correlations, the prices' status, the gaps and the
report path; report `pending`, `fallbacks`, `empty`, `stopped` and every prices status but
`new` and `reused` as they appear. Never state a value that is not in a command's output.
What blocks you or looks wrong in a rule, a message or a tool goes into a GitHub issue (the
root [AGENTS.md](../../AGENTS.md), Feedback), never into the rule.

| Situation or message | Action |
| --- | --- |
| `EODHD_API is not set ...`, `TIINGO_API is not set ...` or `... must be 8 to 200 ASCII letters ...` | Nothing was sent. Ask the user to set the key in `.env`; never ask for its value in the conversation. |
| `HTTP 401 ...; EODHD refused the key: check EODHD_API` | The key is wrong or revoked: tell the user. |
| `HTTP 403 ...; the account needs the marketplace product ...` | The account lacks the product: tell the user. |
| `HTTP 429 ...` after the retry, a 5xx status, a network failure, `the body ended after ...` | Wait some minutes and run `fetch` again. |
| `... the response is not EODHD's options page: ...`, `EODHD returned the record ... twice`, `... more than 11000 records` | EODHD answered in a way the code does not accept. Report the message; never weaken validation. |
| `prices.status` `stopped` with `HTTP 401` or `403 ...; Tiingo refused the key or the request` | The Tiingo key is wrong or its plan lacks daily prices: tell the user. The chains were fetched. |
| `prices.status` `stopped` with `HTTP 429 ...; Tiingo's request limit ...` | Run `fetch` again after an hour (the Starter plan allows 50 requests an hour), or the next day when its 1,000 a day are spent. Later tickers say `not requested: Tiingo stopped the run at T`. |
| `prices.status` `failed` | A 5xx status, a network failure, or an answer the code does not accept (`the response is not Tiingo's daily prices: ...`, or a rule of `check_prices`). Run `fetch` again later; when it fails the same way the next day, report the reason and record with `--partial` only when the user asks. |
| `prices.status` `pending` on two consecutive days | Tiingo lists the ticker but serves no bar of the latest session: report it; record with `--partial` only when the user asks. |
| `prices.status` `empty` | Tiingo has no prices for the ticker (a class share written with a dot, such as `BRK.B`, among them): report it; its returns and correlations stay gaps. |
| `invalid_files` with a reason | Rename the file with the suffix `.rejected` (never delete it) and run `fetch` again; report the reason. If a newly fetched file fails the same way, stop and report. |
| `fetched_at ... is later than the current time` | The host clock is behind the file's time: report both times before renaming anything. |
| A ticker EODHD does not cover | Every session gets an empty chain: report it as uncovered. |
| `PATH.md already exists; refusing to overwrite it` | Another `record` wrote that report in the same second: run `plan` and follow it. |
| A watchlist message (`file not found`, `lists no stock tickers`, ...) | Write or correct this domain's `watchlist.json` with the tickers the user follows, report the change and run the command again. |
