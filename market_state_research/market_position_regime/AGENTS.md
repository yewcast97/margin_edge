# Market position regime

This domain records how the US equity market as a whole is positioned, from three public
sources: FINRA's monthly margin statistics (customers' debit balances in margin accounts),
the CFTC's weekly Traders in Financial Futures report of S&P 500 futures, and Cboe's daily
history of the VIX. Over a window of dates it charts four indicators. This file says what the
work aims at, what its tables and reports hold and mean, how each value is obtained, and how
the code and the raw files are built, with the source facts verified live. The operations
are in [PROCEDURE.md](PROCEDURE.md). The conventions every domain shares (the layout, the
three sections of `data/`, selection, freshness, New York time, sessions and the API rule)
are in [market_state_research/AGENTS.md](../AGENTS.md). The domain takes no ticker and reads
no watchlist: its subject is the market.

## Aim

For the market as a whole, a reproducible record of the indicators below, and a report of a
window that is read whole: three charts, margin debt by month, futures positioning by week
and the VIX by session, served together also when one indicator is asked about, since one
chart alone biases the reading. Its values are the sources' published figures and what the
stated method computes from them, with dates, coverage and a reason wherever a value is
absent. The record names no regime, applies no threshold and gives no advice: its reading is
the user's.

## The indicators

| Indicator | Column | Meaning | Unit |
| --- | --- | --- | --- |
| Margin debt | `debit_balances_musd` | FINRA's debit balances in customers' securities margin accounts, as published (below). | $ millions |
| Asset managers' net percentile | `asset_mgr_net_52w_percentile` | Where the week's net long S&P 500 futures position of asset managers lies among the 52 weeks ending with it. | 0–100 |
| Leveraged funds' net short percentile | `lev_money_net_short_52w_percentile` | Where the week's net short position of leveraged funds lies among the 52 weeks ending with it. | 0–100 |
| VIX close percentile | `close_252s_percentile` | Where the session's VIX close lies among the 252 XNYS sessions ending with it. | 0–100 |

Every value the indicators rest on is archived in the tables: the month's three balances;
each week's long, short and spreading positions of both groups as reported, the open
interest, the contract's unit and the two nets in E-mini equivalents; each session's VIX
close as Cboe wrote it.

## Method

Everything here is computed from the selected raw files (below) with exact fractions and
rounded half-even once at the end; zero is written without a sign (`indicators.py`).

- **Margin debt** of month M is FINRA's "Debit Balances in Customers' Securities Margin
  Accounts", in $ millions, as of M's last business day on a settlement-date basis, charted
  as published: no growth, ratio or other value is derived from it. (No denominator is
  read: the Fed's quarterly market value of corporate equities counts closely held
  corporations, not listed shares alone.)
- **Nets of week W**, from W's report: asset managers' net position = long − short, and
  leveraged funds' net short position = short − long, each in **E-mini equivalents**, contracts
  of $50 times the S&P 500: the CFTC's count × its contract's dollars per index point ÷ 50.
  The CFTC counted contracts of $250 times the index until 2023-04-25 and of $50 from
  2023-05-02 without restating the earlier weeks (the open interest went from 453,159 to
  2,304,633), so only converted counts can be compared across that week.
- **Percentile of week W**: over the 52 consecutive weeks ending with W, 100 × the number of
  the other 51 weeks whose value is strictly below W's / n, n being the number of those weeks
  with a value; equal values are not counted. It is rounded to one decimal place. There is
  none when any of the 52 weeks has no stored report (the reason counts them and names the
  first), or when the 52 weeks begin before the market's first report (2010-06-15), so the
  market's first 51 weeks have none.
- **Percentile of session D**: over the 252 consecutive XNYS sessions ending with D, 100 ×
  the number of the other 251 sessions whose VIX close is strictly below D's / 251; equal
  closes are not counted. It is rounded to one decimal place. There is none when any of the
  252 sessions has no close in Cboe's file (the reason counts them and names the first), or
  when the 252 sessions begin before 2000-01-03, the first session of the XNYS calendar the
  domain uses (`common.sessions`), so the first 251 sessions of 2000 have none. Cboe's rows
  of days XNYS does not trade are kept in the raw file and never ranked.

## Months, weeks, sessions, window and span

- FINRA reports by month, the CFTC by week, Cboe by day. The CFTC reports a week's
  positions as of its Tuesday, or of its Monday when the Tuesday is a holiday, so a week is
  named by its Tuesday whatever day its report is dated (`periods.week_of`); every week has
  one report. The VIX is read by XNYS session, and a session's close is the index at the end
  of Cboe's calculation of the day, a quarter of an hour after XNYS closes.
- The window runs from `--from` to `--to` (New York dates, both included; by default the
  three years ending today). Its months are those whose last day lies in it, its weeks those
  whose Tuesday does, and its sessions the XNYS sessions in it, from 2000-01-03 on. The span
  adds what the window's percentiles rest on: the 51 weeks before its first week and the 251
  sessions before its first session.
- A document is due from the earliest time its source publishes it: FINRA's month M from the
  15th of the month after M; the CFTC's week from its Friday at 15:30 New York time; a
  session's VIX from a quarter of an hour after the session's XNYS close, 16:15 New York time
  on a full day (`periods`). A due document of the window or its span that `raw/` does not
  hold is **lacking**: for the VIX, a due session after the newest day of the stored file
  (Cboe's file holds every day it published, so an earlier session without a close is a gap,
  not lacking). One not due yet is listed as not due and is no gap.
- For the VIX the domain works as of the last completed session: a file holding a row of a
  session whose VIX was not due when the file was fetched is invalid, so no value of a
  session still being calculated is stored. FINRA's months and the CFTC's weeks are dated by
  their own periods.
- Selection: the newest valid workbook (by its fetch time, then by name) is the workbook; the
  newest valid VIX file, likewise, is the VIX history; per week, the report of the newest
  valid CFTC answer holding the week is the week's report. Nothing edits `raw/`; a file is
  withdrawn by renaming it `.rejected`.

## The formatted tables

Three tables in `formatted/market/`, rewritten from `raw/` by `record` and replaced only when
their bytes would change. Python compares them by bytes and never parses them.

`margin_debt.csv`: one row per month of the workbook, oldest first. Columns, in order:

| Column | Contents |
| --- | --- |
| `month` | The month, `YYYY-MM`. |
| `debit_balances_musd` | The debit balances, $ millions. |
| `free_credit_cash_musd` | The free credit balances in customers' cash accounts, $ millions; to January 2010, the free credit balances of cash and margin accounts together. |
| `free_credit_margin_musd` | The free credit balances in customers' securities margin accounts, $ millions, from February 2010; blank before. |
| `source` | The raw file name of the workbook. |

`index_futures.csv`: one row per stored week, oldest first. Columns, in order:

| Column | Contents |
| --- | --- |
| `report_date` | The day the positions are as of, `YYYY-MM-DD`. |
| `contract_units` | The CFTC's unit, as written. |
| `multiplier` | Its dollars per index point: 250 or 50. |
| `open_interest` | The open interest, in the report's contracts. |
| `asset_mgr_long`, `asset_mgr_short`, `asset_mgr_spread` | Asset managers' positions, in the report's contracts. |
| `lev_money_long`, `lev_money_short`, `lev_money_spread` | Leveraged funds' positions, in the report's contracts. |
| `asset_mgr_net_emini`, `lev_money_net_short_emini` | The two nets in E-mini equivalents. |
| `asset_mgr_net_52w_percentile`, `lev_money_net_short_52w_percentile` | The percentiles, one decimal place, or blank. |
| `fetched_at` | When the week's answer was fetched, ISO 8601 with its New York offset. |
| `source` | The raw file name of the week's answer. |

`vix.csv`: one row per XNYS session from 2000-01-03 to the newest day of the VIX history,
oldest first. Columns, in order:

| Column | Contents |
| --- | --- |
| `date` | The session, `YYYY-MM-DD`. |
| `close` | The VIX close as Cboe wrote it (six decimal places), or blank where Cboe's file holds no row of the session. |
| `close_252s_percentile` | The percentile, one decimal place, or blank. |
| `source` | The raw file name of the VIX history. |

## Reports

`record` writes the report `reports/market/market_{FROM}_{TO}_{TOKEN}.html` and, just before
it, its Markdown twin `.md`; `TOKEN` is the time of the `record` that wrote them, and
neither is ever overwritten. `show` prints the twin's text recomputed from `raw/`.

The report is one self-contained page (the chart library inlined; it opens offline) of one
window, and one whole: its three charts are served and read together, never one alone.

- Three charts, one above the other, each on its own time axis and one scale: margin debt by
  month, each month drawn on its last day, in $ millions; S&P 500 futures positioning by
  week, each week drawn on its report's date, the two percentiles on a fixed 0–100 scale with
  a line at 50; and the VIX by session, the close percentile on a fixed 0–100 scale with a
  line at 50. A line breaks where a point has no value; a dot marks each value beside a
  break.
- A readout per chart, under the pointer or stepped with the arrow keys: the month and its
  debit balances; the report date with its week, the two percentiles, the two nets and the
  open interest in E-mini equivalents; or the session, its percentile and its close (`—`
  where blank). It keeps the height of its tallest point.
- A header with the window, coverage (stored points of the due ones), the newest month,
  report and session, what is not due yet, the generation time, the tables' paths, the
  workbook and the VIX file read and the sources; banners naming every point that is due and
  not fetched and, per series, every point without a value.
- Collapsible data tables, one row per month, week and session (`not fetched` where due and
  not stored), followed by the gaps: each point's series without a value, with the reason.
- A footer stating the method and the chart library's attribution.

The twin holds the same statements and tables as Markdown text.

## Freshness, missing data and what is never added

- A report is fresh while it is exactly what `record` would write now, apart from its
  generation time (the shared rule): it is rendered again at the time in its name and
  compared byte for byte. A raw file added or withdrawn that changes what the window shows,
  and a change of the method, the rendering code, the template or the chart library each make
  the newest report stale; `plan` then says `record`.
- Three absences are kept apart and each is named: a point due and not fetched (lacking), a
  point not due yet, and a gap (a stored point without a value, with its reason).
- Validation is never weakened to admit a file; a raw file that fails it counts as absent
  until it is renamed `.rejected`, and `record` and `show` refuse while one exists.
- No regime label, threshold, moving average, ranking or trading advice is added anywhere.

## Commands

Run from the repository root as
`uv run --locked python -m market_state_research.market_position_regime.script COMMAND`,
each taking `--from DATE`, `--to DATE` and `--data-dir PATH`:

| Command | Does |
| --- | --- |
| `fetch [--refresh]` | The one network command. Requests from each source what the window lacks (with `--refresh`, everything the window needs): FINRA's workbook, the CFTC's rows from the first lacking week to the last, Cboe's VIX history; writes an answer only when it holds something `raw/` does not. A source that fails does not stop the others. |
| `plan [--refresh]` | Read-only. Per source, what is lacking and the newest stored document; what is not due yet; gaps; invalid raw files; the tables and the newest report's freshness; the action. |
| `record` | Rewrites the three tables from `raw/` and writes a new report of the window and its twin, naming whatever is lacking in it. Refuses while a raw file is invalid or when no month, week or session of the window is fetched. |
| `show` | Read-only: one status line, then the twin recomputed from `raw/`. |

`--to` defaults to today's New York date and may not be after it; `--from` defaults to the
same day three years before `--to` (29 February: the 28th) and may not be after `--to`. A
command that succeeds exits 0 and prints JSON (`show`: Markdown); a refusal exits 2 with one
`MARKET_POSITION_REGIME: ...` line on standard error. No source needs a key, so no command
reads a setting. [PROCEDURE.md](PROCEDURE.md) gives each field and the step that follows.

## Architecture

The package `market_state_research.market_position_regime.script`, through which a hypothesis
script reads this domain's `raw/` ([explore_hypothesis/AGENTS.md](../../explore_hypothesis/AGENTS.md)):

| Module | Responsibility |
| --- | --- |
| `__main__` | The command line (`MARKET_POSITION_REGIME` label); resolves and checks the window first. |
| `client` | HTTPS to the three fixed endpoints only (`www.finra.org`, `publicreporting.cftc.gov`, `cdn-api.cboe.com`), no key, statuses, bounded and whole bodies, no redirect. |
| `periods` | Months, weeks named by their Tuesday, the XNYS sessions of a span; when each source's document is due. |
| `finra` | The workbook's address, its parsing with the standard library (`zipfile`, `xml.etree`) and every rule (`parse_workbook`, `check_workbook`), its raw name. |
| `cftc` | The query (`query_url`), the rows and every rule (`check_row`, `check_answer`), the units and the E-mini conversion, the answer raw unit (`dump`, `read_answer`). |
| `cboe` | The VIX file's address, its parsing and every rule (`parse_history`, `check_history`), the gzip raw unit (`dump`, `load`, `read_history`). |
| `indicators` | The percentiles over 52 weeks and over 252 sessions. |
| `store` | Reading and validating every raw file, the selection, the margin, futures and VIX rows over the whole archive, the three tables. |
| `chart` and `templates/chart.html` | The report (three charts on one page) and its twin, over `common.chart`: the vendored TradingView Lightweight Charts 5.2.1, pinned by SHA-256, and the page text helpers. |
| `workflow` | `Window` and its span, what is due and lacking, `plan`, `fetch`, `record`, `show`. |

## The raw units

Every raw file lies in `raw/market/`, is written only by `fetch` and never overwritten (`_N`
before the extension for a second file of one second). `TOKEN` names the time the answer
arrived, New York time to the second with its zone.

### FINRA's workbook

`finra_margin_{TOKEN}.xlsx`: the workbook's bytes as received. Every read checks the whole
workbook again (`finra.parse_workbook`, `check_workbook`): a zip archive whose
`xl/workbook.xml` lists exactly one sheet, `Customer Margin Balances`, at
`xl/worksheets/sheet1.xml` (a part unpacked to at most 8 MiB and declaring no document type
or entity); the first row exactly the four headers as inline strings in A1 to D1; then one
row per month, newest first, every month down to 1997-01 once and in order: the month as an
inline `YYYY-MM` string in A, whole numbers of $ millions in B and C, and in D from February
2010 on, never before; the newest month ended before the month the file was fetched in; the
fetch time, which the name gives, not after the clock. A newer workbook is written only when
its balances differ from the selected one's.

### The CFTC's answers

`cftc_tff_{FIRST}_{LAST}_{TOKEN}.json`: one JSON object with exactly these keys, in this
order:

| Key | Contents |
| --- | --- |
| `request` | The key-free URL requested: `cftc.query_url` of `first` and `last`. |
| `fetched_at` | When the answer arrived, New York ISO time with its offset; `TOKEN` names it to the second. |
| `first`, `last` | The report dates asked for, `YYYY-MM-DD`, both included: a lacking week's Monday to a lacking week's Sunday. |
| `rows` | The answer's rows as the API wrote them, each with exactly the selected fields, every value text. |

Every read checks every rule again (`cftc.check_answer`): the keys and forms; the request
rebuilt from `first` and `last`; the name against them and the time; a time not after the
clock and later than the newest row's date; at least one row and fewer than a full page;
each row the market's (`id` `{YYMMDD}13874+F`, the code `13874+`, the market's name, futures
only), dated a weekday from `first` to `last`, its unit one of the three the market has
used, every position a whole number of contracts; one row per week, in date order. A newer
answer is written only when it holds a week `raw/` lacks or a row that differs from the
selected one.

### Cboe's VIX files

`cboe_vix_{TOKEN}.csv.gz`: the file's bytes as received, in deterministic gzip (level 9, no
name or time in its header), since the whole history (about 0.5 MB, about 0.1 MB packed) is
fetched again each time a session is lacking. Every read unpacks it (at most 16 MiB) and
checks the whole file again (`cboe.check_history`): ASCII lines, each ended by a line feed;
the first exactly `DATE,OPEN,HIGH,LOW,CLOSE`; then one row per day, in date order, the first
of 1990-01-02: the day written `MM/DD/YYYY`, then the open, high, low and close, each a
decimal above 0 with six places (no order among the four is checked); no row dated after
the day of the fetch, which the name gives, nor a row of an XNYS session whose VIX was not
due yet then; the fetch time not after the clock. Rows of days XNYS does not trade are valid
and kept. A newer file is written only when its rows differ from the selected one's.

## Fetching

`fetch` sends at most three requests a run (`workflow.py`): FINRA's workbook when a due month
is lacking; the CFTC's rows from the Monday of the first lacking week to the Sunday of the
last (a few hundred rows at most; the whole market since 2010 is 853); Cboe's VIX file when a
due session is lacking. With `--refresh` it requests the workbook, every due week of the span
and the VIX file again, whatever is stored. Per source it reports `reused` (nothing lacking,
no request), `new` (an answer written), `verified` (an answer that holds nothing `raw/`
lacks: nothing written) or `failed` (the request failed or the answer failed a rule: nothing
written, the reason given), and `pending`: the due documents the source has not published
yet. An answer is checked by the same rules as a raw file before it is written.

## FINRA facts verified live (2026-10-20)

- `GET https://www.finra.org/sites/default/files/2021-03/margin-statistics.xlsx` answers 200
  without a redirect, a key or a particular user agent (Python's urllib default is served),
  `content-type: application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`, 20,499
  bytes, `last-modified: Fri, 16 Oct 2026 14:12:54 GMT`, no content encoding. The address's
  `2021-03` is fixed: FINRA replaces the file in place.
- The workbook is an export of Microsoft Access (created 2026-10-15T13:26:43Z): one sheet,
  `Customer Margin Balances`; no shared-strings part, every text an inline string; row 1 reads
  `Year-Month`, `Debit Balances in Customers' Securities Margin Accounts`, `Free Credit
  Balances in Customers' Cash Accounts`, `Free Credit Balances in Customers' Securities
  Margin Accounts`; rows 2 to 358 hold 2026-09 down to 1997-01, plain whole numbers.
- Column D holds 200 months, 2010-02 to 2026-09, and is absent from the 157 before: 2010-01
  reads 266,455 and 281,035 (free credits together), 2010-02 263,657, 106,131 and 164,624.
  2026-09 reads 1,480,054, 215,328 and 218,581.
- FINRA's page: member firms report under Rule 4521(d), as of the last business day of the
  month on a settlement-date basis; the statistics aggregate all member firms carrying margin
  accounts from February 2010; FINRA updates them "on the third week of the month following
  the reference month" (2026-09 appeared 2026-10-15/16).

## CFTC facts verified live (2026-10-20)

- `https://publicreporting.cftc.gov/resource/gpe5-46if.json` (Socrata, "TFF - Futures
  Only"; metadata at `/api/views/gpe5-46if.json`) answers SoQL `$select`, `$where`, `$order`
  and `$limit` without a key: `application/json;charset=utf-8`, no `Content-Length`
  (chunked), `X-SODA2-Fields` and `X-SODA2-Types` naming the selection. The contract code's
  `+` must be sent encoded (`%2B`). The dataset was last updated Friday 2026-10-16 19:30:08
  UTC (15:30:08 EDT), the release time.
- Dates are floating timestamps (`2026-10-13T00:00:00.000`) and numbers come as JSON strings;
  a row's `id` is `{YYMMDD}{code}F`.
- `13874+`, "S&P 500 Consolidated - CHICAGO MERCANTILE EXCHANGE": 853 reports from 2010-06-15
  to 2026-10-13, one in every week, none missing; eight dated a Monday (2012-12-24,
  2012-12-31, 2017-07-03, 2018-12-24, 2018-12-31, 2020-12-21, 2023-07-03, 2025-11-10).
  Every row holds all the selected fields as whole numbers.
- Its unit reads `'(S&P 500 INDEX X $250.00)'` (quotes included) to 2014-12-30,
  `(S&P 500 INDEX X $250.00)` from 2015-01-06 to 2023-04-25 and `(S&P 500 INDEX X $50.00)`
  from 2023-05-02; the open interest went from 453,159 to 2,304,633 across the change, so the
  counts were not restated.
- 2026-10-13: open interest 1,948,056; asset managers 1,112,656 long, 194,559 short, 96,050
  spreading (net 918,097); leveraged funds 121,198 long, 531,716 short, 53,147 spreading (net
  short 410,518). The E-mini (`13874A`) and the futures-and-options dataset (`yw9f-hn96`) are
  reported too and not read.
- A `fetch` on 2026-10-20 asked for 2022-10-31 to 2026-10-18 and stored 207 rows (108,836
  bytes).

## Cboe facts verified live (2026-10-20)

- `GET https://cdn-api.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv` answers
  200 without a key, a cookie or a particular user agent (Python's urllib default is served),
  through Cloudflare and CloudFront: `content-type: text/csv`, chunked (no `Content-Length`),
  no content encoding, `cache-control: max-age=60, s-maxage=900`, 473,890 bytes,
  `last-modified: Tue, 20 Oct 2026 01:11:01 GMT` (21:11 EDT on 2026-10-19). The same path on
  `cdn.cboe.com` answers 307 to it, so the domain asks for the target directly.
- The file is ASCII with line feeds and a final one; its header reads
  `DATE,OPEN,HIGH,LOW,CLOSE`, and 9,297 rows follow, from `01/02/1990` to `10/19/2026` (at
  19:14 EDT on 2026-10-20 the row of 2026-10-20 was not in it yet); every value has six
  decimal places, of which only the first two are ever other than zero. In 47 rows, from
  1992-02-11 to 2006-02-08, the high or the low does not bound the open and the close.
- Every XNYS session from 2000-01-03 to 2026-10-19 has a row. 34 rows are of days XNYS was
  closed: 2004-06-11 (the national day of mourning for President Reagan, a flat row at the
  day before's close) and 33 since 2022-05-30, the US holidays on which Cboe calculated the
  index in its global trading hours (Memorial Day, Juneteenth, Independence Day, Labor Day,
  Thanksgiving, Martin Luther King Jr. Day, Washington's Birthday, and 2025-01-09, the
  national day of mourning for President Carter). The other days XNYS was closed, New Year's
  Day, Good Friday and Christmas among them, have none.
- Cboe's VIX options specifications: "The VIX Index is calculated between 2:15 a.m. CT and
  8:25 a.m. CT and between 8:30 a.m. CT and 3:15 p.m. CT", 16:15 New York time.
- 2026-10-19: open 18.37, high 18.93, low 17.39, close 18.44; 172 of the 251 sessions before
  it closed below 18.44, a percentile of 68.5.
- EODHD's `VIX.INDX` (its end-of-day API, under `EODHD_API`) is not read: on the key's
  free plan it serves one year only (the answer's last bar carries `"warning": "Data is
  limited by one year as you have free subscription"`), it holds flat bars on 2025-12-25,
  2026-01-01 and 2026-04-03, of which Cboe's file has no row, and its bar of 2026-02-06
  (low 19.99, close 20.37) differs from Cboe's (17.27, 17.76).
