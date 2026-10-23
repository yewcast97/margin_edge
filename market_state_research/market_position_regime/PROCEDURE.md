# Market position regime: margin debt, S&P 500 futures positioning, the VIX and the SKEW

This procedure keeps FINRA's monthly margin debt, the CFTC's weekly S&P 500 futures positions
and Cboe's daily VIX and SKEW current, and writes the report of a window (three charts on one
page) with its Markdown twin. `plan` says what is missing, `fetch` writes it, `record` writes the
three tables and the report. What the values mean, how they are computed and what the raw
files hold are in [AGENTS.md](AGENTS.md). The domain takes no ticker and has no watchlist.

Run every command from the repository root:

```sh
uv run --locked python -m market_state_research.market_position_regime.script COMMAND ...
```

A command that succeeds exits 0 and prints JSON (`show`: Markdown), also when a source failed
or has not published a document yet. A command that fails exits 2 with one
`MARKET_POSITION_REGIME: ...` line on standard error and prints nothing else.

## 1. Settings and parameters

No source needs a key: no command reads `.env`.

| Parameter | Default | Meaning |
| --- | --- | --- |
| `--from YYYY-MM-DD` | the same day three years before `--to` | Every command: the window's first day, a New York date. |
| `--to YYYY-MM-DD` | today's New York date | Every command: the window's last day; never after today. |
| `--refresh` | off | `fetch` and `plan`: request everything the window needs again, whatever is stored. Use it only when the user asks, on one `fetch`, and plan afterwards without it. |
| `--data-dir PATH` | `market_state_research/market_position_regime/data` | Every command; another directory for isolated checks. |

Use the same window for every command of one run.

## 2. Plan

```sh
uv run --locked python -m market_state_research.market_position_regime.script plan
```

| Field | Meaning |
| --- | --- |
| `action` | `fetch`, `record` or `reuse` (below). |
| `window` | `{from, to, months, weeks, sessions, span_start}`: the window, its months, weeks and XNYS sessions, and the first day its values rest on. |
| `sources` | Per source (`finra`, `cftc`, `cboe_vix`, `cboe_skew`): `status` (`current` or `lacking`), the newest stored month, report date or day (`newest`), the stored file (`path`; for `cftc`, the number of `files`) and `lacking` (`{count, first, last}`: what is due and not stored). |
| `not_due` | What the window holds that its sources are not due to publish yet, with when each is due. |
| `gaps` | `{date, series, reason}` of each stored point of the window without a value. |
| `invalid_files` | `{path, reason}` of each raw file that failed validation; it counts as absent. Handle each first (section 5). |
| `tables` | The paths of `margin_debt`, `index_futures` and `vix_skew`, or null. |
| `report` | `{status, path, reason}` of the newest report of this window: `fresh`, `stale` (with a reason) or `missing`. |

| `action` | When | Next step |
| --- | --- | --- |
| `fetch` | A source lacks a due document; always with `--refresh`. | Run `fetch` (section 3), then `plan` again. |
| `record` | Nothing due is lacking, but a table or the newest report is not current. | Run `record` (section 4). |
| `reuse` | The tables and the newest report are current. | Report `report.path`; nothing to do. |

## 3. Fetch

```sh
uv run --locked python -m market_state_research.market_position_regime.script fetch
```

It prints `requests` (sent in the run, four at most), `invalid_files` and per source
(`finra`, `cftc`, `cboe_vix`, `cboe_skew`):

| Field | Meaning |
| --- | --- |
| `status` | `new` (an answer was written), `verified` (the answer held nothing new: nothing written), `reused` (nothing was lacking: no request) or `failed` (section 5). |
| `path` | The file written or kept, or null. |
| `reason` | Why the source failed, or null. |
| `pending` | `{count, first, last}` of the due documents the source has not published yet. |

The sources publish on their own calendars: the CFTC every Friday at 15:30 New York time
(the following Monday after a holiday), FINRA in the third week of each month, Cboe each
evening after a session (a session's VIX and SKEW are due from 16:15 New York time; Cboe
replaces each file on its own, the VIX's at 21:11 on 2026-10-19, and on 2026-10-22 the
SKEW's at 21:11 and the VIX's at 21:21). A document `pending` after a `fetch` is not
published yet: run `fetch` again the next day.

### A positioning request

When the user asks how the market is positioned, or about margin debt, futures positioning,
the VIX or the SKEW over a period, set `--from` and `--to` to that period (without one named, keep the
default three years). Run `fetch`, then `plan`, then `record` when the action is `record` (or
when it is still `fetch` only because documents are `pending` and `report.status` is not
`fresh`), and hand over `report.path` with its twin and the latest values (section 5). The
report is one whole: deliver its three charts, margin debt, futures positioning and the VIX
and SKEW, together, also when the user asks about one indicator, and never describe one chart
without the others.

### Weekly routine

Every Saturday (New York time), when the CFTC's Friday release and Cboe's files of Friday's
session are out, run `fetch` and then `plan`, and `record` when the action is `record`.
While `pending` is not empty (FINRA's month in the third week, a CFTC report delayed by a
holiday), run `fetch` again each day until it is.

## 4. Record and show

```sh
uv run --locked python -m market_state_research.market_position_regime.script record
```

| Field | Meaning |
| --- | --- |
| `window` | As in `plan`. |
| `months` | `{month, debit_balances_musd}` of each stored month of the window. |
| `weeks` | `{report_date, asset_mgr_net, asset_mgr_net_52w_percentile, lev_money_net_short, lev_money_net_short_52w_percentile}` of each stored week of the window, nets in E-mini equivalents. |
| `indices` | `{sessions, newest}`: how many sessions of the window are stored, and `{date, vix_close, vix_close_252s_percentile, skew, skew_252s_percentile}` of the newest (null where blank). |
| `lacking` | `{months, weeks, vix_sessions, skew_sessions}`: the window's months, weeks and sessions due and not stored, per source: each is named in the report. |
| `not_due`, `gaps` | As in `plan`. |
| `tables` | Per table `{path, rows, written}`; `written` is false when the file already held these bytes. |
| `report` | `{status, path, markdown}`: `written`, the page and its twin. |

`record` writes a report every time it runs; run it only when `plan` asks for it (section 3,
A positioning request). `show` prints one status line and the twin recomputed from `raw/`,
for reading the window without writing anything. A `formatted/market/vix.csv`, from before
the SKEW was read (until 2026-10-23), is written by no command any more: delete it.

## 5. Report back and failures

Report the window, the action taken, coverage (stored months, weeks and sessions of the due
ones), the latest values (the debit balances of the newest month, the two percentiles and
nets of the newest week, the VIX close and the SKEW of the newest session with their
percentiles), the gaps,
what is lacking or pending, and the report path. Never state a value that is not in a
command's output. What blocks you or looks wrong in a rule, a message or a tool goes into a
GitHub issue (the root [AGENTS.md](../../AGENTS.md), Feedback), never into the rule.

| Situation or message | Action |
| --- | --- |
| `failed` with HTTP 429, a 5xx status, a network failure or `the body ended after ...` | Wait some minutes and run `fetch` again. |
| `failed` with `... no longer serves this address: report it` | The source moved its file or refuses the request: open an issue and tell the user. |
| `failed` naming a rule (`the first row must be exactly ...`, `row N: contract_units must be ...`, `the first line must be exactly DATE,OPEN,HIGH,LOW,CLOSE` or `DATE,SKEW`, and the like) | The source changed its format and nothing was written: open an issue with the message; never weaken validation. |
| `failed` with `... before the session's VIX was due ...` or `... SKEW was due ...` | Cboe served a row of a session still being calculated, and nothing was written: run `fetch` again after 16:15 New York time; if it recurs, open an issue. |
| `pending` not empty | The source has not published the document yet: run `fetch` again the next day; record meanwhile only as section 3 says. |
| `invalid_files` with a reason | Rename the file with the suffix `.rejected` (never delete it) and run `fetch` again; report the reason. A `fred_*.json` file, from when the domain read FRED (until 2026-10-21), is `not a raw file name`: rename it the same way. If a newly fetched file fails the same way, stop and report. |
| `fetched_at ... is later than the current time` | The host clock is behind the file's time: report both times before renaming anything. |
| `PATH.md already exists; refusing to overwrite it` | Another `record` wrote that report in the same second: run `plan` and follow it. |
