# Market position regime: margin debt and S&P 500 futures positioning

This procedure keeps FINRA's monthly margin debt, the Fed's quarterly market value of US
corporate equities (from FRED) and the CFTC's weekly S&P 500 futures positions current, and
writes the report of a window (two charts on one page) with its Markdown twin. `plan` says
what is missing, `fetch` writes it, `record` writes the two tables and the report. What the
values mean, how they are computed and what the raw files hold are in
[AGENTS.md](AGENTS.md). The domain takes no ticker and has no watchlist.

Run every command from the repository root:

```sh
uv run --locked python -m market_state_research.market_position_regime.script COMMAND ...
```

A command that succeeds exits 0 and prints JSON (`show`: Markdown), also when a source failed
or has not published a document yet. A command that fails exits 2 with one
`MARKET_POSITION_REGIME: ...` line on standard error and prints nothing else.

## 1. Settings and parameters

`fetch` needs one key, in the environment or the repository-root `.env`: `FRED_API`, the
user's FRED API key (32 lowercase letters and digits). FINRA and the CFTC need none. Never
print, copy or write the key; `fetch` reports it only as `"fred_key": "set"`.

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
| `window` | `{from, to, months, weeks, span_start}`: the window, its months and weeks, and the first day its values rest on. |
| `sources` | Per source (`finra`, `cftc`, `NCBEILQ027S`, `BOGZ1LM793164105Q`): `status` (`current` or `lacking`), the newest stored month, report date or quarter end (`newest`), the stored file (`path`; for `cftc`, the number of `files`) and `lacking` (`{count, first, last}`: what is due and not stored). |
| `not_due` | What the window holds that its sources are not due to publish yet, with the day each is due. |
| `gaps` | `{date, series, reason}` of each stored point of the window without a value. |
| `invalid_files` | `{path, reason}` of each raw file that failed validation; it counts as absent. Handle each first (section 5). |
| `tables` | The paths of `margin_debt` and `index_futures`, or null. |
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

It prints `fred_key` (`set`), `requests` (sent in the run, four at most), `invalid_files`
and per source (`finra`, `cftc`, `NCBEILQ027S`, `BOGZ1LM793164105Q`):

| Field | Meaning |
| --- | --- |
| `status` | `new` (an answer was written), `verified` (the answer held nothing new: nothing written), `reused` (nothing was lacking: no request) or `failed` (section 5). |
| `path` | The file written or kept, or null. |
| `reason` | Why the source failed, or null. |
| `pending` | `{count, first, last}` of the due documents the source has not published yet. |

The sources publish on their own calendars: the CFTC every Friday at 15:30 New York time
(the following Monday after a holiday), FINRA in the third week of each month, the Fed's Z.1
in the second week of March, June, September and December. A document `pending` after a
`fetch` is not published yet: run `fetch` again the next day.

### A positioning request

When the user asks how the market is positioned, or about margin debt or futures positioning
over a period, set `--from` and `--to` to that period (without one named, keep the default
three years). Run `fetch`, then `plan`, then `record` when the action is `record` (or when it
is still `fetch` only because documents are `pending` and `report.status` is not `fresh`),
and hand over `report.path` with its twin and the latest values (section 5). The report is
one whole: deliver its two charts, margin debt and futures positioning, together, also when
the user asks about one indicator, and never describe one chart without the other.

### Weekly routine

Every Friday after 16:00 New York time, run `fetch` and then `plan`, and `record` when the
action is `record`. While `pending` is not empty (FINRA's month in the third week, the Fed's
quarter in the second week of its month, a CFTC report delayed by a holiday), run `fetch`
again each day until it is.

## 4. Record and show

```sh
uv run --locked python -m market_state_research.market_position_regime.script record
```

| Field | Meaning |
| --- | --- |
| `window` | As in `plan`. |
| `months` | `{month, debit_balances_musd, yoy_pct, market_value_quarter_end, market_value_musd, ratio_pct}` of each stored month of the window. |
| `weeks` | `{report_date, asset_mgr_net, asset_mgr_net_52w_percentile, lev_money_net_short, lev_money_net_short_52w_percentile}` of each stored week of the window, nets in E-mini equivalents. |
| `lacking` | The window's months and weeks due and not stored, and per FRED series the quarter ends lacking: each is named in the report. |
| `not_due`, `gaps` | As in `plan`. |
| `tables` | Per table `{path, rows, written}`; `written` is false when the file already held these bytes. |
| `report` | `{status, path, markdown}`: `written`, the page and its twin. |

`record` writes a report every time it runs; run it only when `plan` asks for it (section 3,
A positioning request). `show` prints one status line and the twin recomputed from `raw/`,
for reading the window without writing anything.

## 5. Report back and failures

Report the window, the action taken, coverage (stored months and weeks of the due ones), the
latest values (the growth and the ratio of the newest month with its quarter end, the two
percentiles and nets of the newest week), the gaps, what is lacking or pending, and the
report path. Never state a value that is not in a command's output. What blocks you or looks
wrong in a rule, a message or a tool goes into a GitHub issue (the root
[AGENTS.md](../../AGENTS.md), Who does what), never into the rule.

| Situation or message | Action |
| --- | --- |
| `FRED_API is not set ...` or `FRED_API must be 32 lowercase ASCII letters or digits` | Nothing was sent. Ask the user to set the key in `.env`; never ask for its value in the conversation. |
| `failed` with `FRED refused the request: check FRED_API` | The key is wrong or revoked: tell the user. FINRA and the CFTC were still read. |
| `failed` with HTTP 429, a 5xx status, a network failure or `the body ended after ...` | Wait some minutes and run `fetch` again. |
| `failed` with `... no longer serves this address: report it` | The source moved its file: open an issue and tell the user. |
| `failed` naming a rule (`the first row must be exactly ...`, `row N: contract_units must be ...`, `FRED's units must be ...`, and the like) | The source changed its format and nothing was written: open an issue with the message; never weaken validation. |
| `pending` not empty | The source has not published the document yet: run `fetch` again the next day; record meanwhile only as section 3 says. |
| `invalid_files` with a reason | Rename the file with the suffix `.rejected` (never delete it) and run `fetch` again; report the reason. If a newly fetched file fails the same way, stop and report. |
| `fetched_at ... is later than the current time` | The host clock is behind the file's time: report both times before renaming anything. |
| `PATH.md already exists; refusing to overwrite it` | Another `record` wrote that report in the same second: run `plan` and follow it. |
