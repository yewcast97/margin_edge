# Market position regime

This domain records how the US equity market as a whole is positioned, from three public
sources: FINRA's monthly margin statistics (customers' debit balances in margin accounts),
the Federal Reserve's quarterly market value of US corporate equities (the Financial
Accounts, Z.1, served by FRED) and the CFTC's weekly Traders in Financial Futures report of
S&P 500 futures. Over a window of dates it derives four indicators and charts them. This
file says what the work aims at, what its tables and reports hold and mean, how each value
is obtained, and how the code and the raw files are built, with the source facts verified
live. The operations are in [PROCEDURE.md](PROCEDURE.md). The conventions every domain
shares (the layout, the three sections of `data/`, selection, freshness, New York time and
the API rule) are in [market_state_research/AGENTS.md](../AGENTS.md). The domain takes no
ticker and reads no watchlist: its subject is the market.

## Aim

For the market as a whole, a reproducible record of the indicators below, and a report of a
window that is read whole: two charts, margin debt by month and futures positioning by week,
served together also when one indicator is asked about, since either half alone biases the
reading. Its values are computed from the sources' published figures by the stated method,
with dates, coverage and a reason wherever a value is absent. The record names no regime,
applies no threshold and gives no advice; the analyst reads it.

## The indicators

| Indicator | Column | Meaning | Unit |
| --- | --- | --- | --- |
| Margin debt growth | `yoy_pct` | The year-over-year growth of FINRA's debit balances in customers' securities margin accounts (below). | percent |
| Margin debt to market value | `ratio_pct` | The month's debit balances as a share of the market value of US corporate equities at the latest quarter end on or before the month's last day. | percent |
| Asset managers' net percentile | `asset_mgr_net_52w_percentile` | Where the week's net long S&P 500 futures position of asset managers lies among the 52 weeks ending with it. | 0–100 |
| Leveraged funds' net short percentile | `lev_money_net_short_52w_percentile` | Where the week's net short position of leveraged funds lies among the 52 weeks ending with it. | 0–100 |

The growth, the ratio and the two percentiles are the domain's aim. Every value they rest on
is archived in the tables: the month's three balances, the market value and its quarter end;
each week's long, short and spreading positions of both groups as reported, the open
interest, the contract's unit and the two nets in E-mini equivalents.

## Method

Everything here is computed from the selected raw files (below) with exact fractions and
rounded half-even once at the end; zero is written without a sign (`indicators.py`).

- **Margin debt** of month M is FINRA's "Debit Balances in Customers' Securities Margin
  Accounts", in $ millions, as of M's last business day on a settlement-date basis.
- **Growth of month M** = (debit(M) / debit(M − 12) − 1) × 100, both from one workbook,
  rounded to one decimal place. There is none, with the reason, without M − 12 (FINRA's table
  starts in January 1997, so 1997 has none).
- **Market value at quarter end E** = the sum of the two Z.1 series at E, in $ millions:
  `NCBEILQ027S` (nonfinancial corporate business, corporate equities, liability: the Fed's
  FL103164105, the sum of public corporations' equity, FL103164115, and closely held
  corporations' equity, FL103164125) and `BOGZ1LM793164105Q` (domestic financial sectors,
  corporate equities, liability, at market value: LM793164105). It is the Fed's value of all
  equity US corporations have issued, closely held nonfinancial corporations included, not
  the capitalisation of listed shares alone.
- **Ratio of month M** = debit(M) / market value(E) × 100, E the latest quarter end on or
  before M's last day (July and August rest on June 30, September on September 30), rounded
  to two decimal places. There is none, with the reason, while either series lacks E: no
  other quarter stands in for it, so the month ending a quarter has no ratio until the Fed
  publishes that quarter, about two and a half months later.
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

## Months, weeks, quarters, window and span

- FINRA reports by month, the CFTC by week, the Fed by quarter end. The CFTC reports a
  week's positions as of its Tuesday, or of its Monday when the Tuesday is a holiday, so a
  week is named by its Tuesday whatever day its report is dated (`periods.week_of`); every
  week has one report.
- The window runs from `--from` to `--to` (New York dates, both included; by default the
  three years ending today). Its months are those whose last day lies in it, its weeks those
  whose Tuesday does, and its quarter ends those its months' ratios rest on. The span adds
  what the window's values rest on: the month twelve months before each window month and the
  51 weeks before its first week.
- A document is due from the earliest time its source publishes it: FINRA's month M from the
  15th of the month after M; the CFTC's week from its Friday at 15:30 New York time; the Z.1
  quarter ending E from the 15th of the third month after E (`periods`). A due document of
  the window or its span that `raw/` does not hold is **lacking**; one not due yet is listed
  as not due and is no gap.
- Selection: the newest valid workbook (by its fetch time, then by name) is the workbook;
  per series, the newest valid FRED answer is the series; per week, the report of the newest
  valid CFTC answer holding the week is the week's report. Nothing edits `raw/`; a file is
  withdrawn by renaming it `.rejected`.

## The formatted tables

Two tables in `formatted/market/`, rewritten from `raw/` by `record` and replaced only when
their bytes would change. Python compares them by bytes and never parses them.

`margin_debt.csv`: one row per month of the workbook, oldest first. Columns, in order:

| Column | Contents |
| --- | --- |
| `month` | The month, `YYYY-MM`. |
| `debit_balances_musd` | The debit balances, $ millions. |
| `free_credit_cash_musd` | The free credit balances in customers' cash accounts, $ millions; to January 2010, the free credit balances of cash and margin accounts together. |
| `free_credit_margin_musd` | The free credit balances in customers' securities margin accounts, $ millions, from February 2010; blank before. |
| `yoy_pct` | The growth, one decimal place, or blank. |
| `market_value_quarter_end` | The quarter end the ratio rests on, `YYYY-MM-DD`. |
| `market_value_musd` | The market value at that quarter end, $ millions as the sum of FRED's text, or blank. |
| `ratio_pct` | The ratio, two decimal places, or blank. |
| `source` | The raw file name of the workbook. |
| `market_value_sources` | The raw file names of the two FRED answers, separated by a space, or blank. |

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

## Reports

`record` writes the report `reports/market/market_{FROM}_{TO}_{TOKEN}.html` and, just before
it, its Markdown twin `.md`; `TOKEN` is the time of the `record` that wrote them, and
neither is ever overwritten. `show` prints the twin's text recomputed from `raw/`.

The report is one self-contained page (the chart library inlined; it opens offline) of one
window, and one whole: its two charts are served and read together, never one alone.

- Two charts, one above the other, each on its own time axis: margin debt by month, each
  month drawn on its last day, the growth on the right scale with a line at 0 and the ratio
  on the left scale; and S&P 500 futures positioning by week, each week drawn on its
  report's date, the two percentiles on a fixed 0–100 scale with a line at 50. A line breaks
  where a point has no value; a dot marks each value beside a break.
- A readout per chart, under the pointer or stepped with the arrow keys: the month with the
  quarter end its ratio rests on, the growth, the ratio, the debit balances and the market
  value; or the report date with its week, the two percentiles, the two nets and the open
  interest in E-mini equivalents (`—` where blank). It keeps the height of its tallest point.
- A header with the window, coverage (stored points of the due ones), the newest month and
  report, what is not due yet, the generation time, the tables' paths, the raw files and the
  sources; banners naming every point that is due and not fetched and, per series, every
  point without a value.
- Collapsible data tables, one row per month and per week (`not fetched` where due and not
  stored), followed by the gaps: each point's series without a value, with the reason.
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
| `fetch [--refresh]` | The one network command (needs `FRED_API`). Requests from each source what the window lacks (with `--refresh`, everything the window needs): FINRA's workbook, the CFTC's rows from the first lacking week to the last, each FRED series whole; writes an answer only when it holds something `raw/` does not. A source that fails does not stop the others. |
| `plan [--refresh]` | Read-only. Per source, what is lacking and the newest stored document; what is not due yet; gaps; invalid raw files; the tables and the newest report's freshness; the action. |
| `record` | Rewrites both tables from `raw/` and writes a new report of the window and its twin, naming whatever is lacking in it. Refuses while a raw file is invalid or when no month or week of the window is fetched. |
| `show` | Read-only: one status line, then the twin recomputed from `raw/`. |

`--to` defaults to today's New York date and may not be after it; `--from` defaults to the
same day three years before `--to` (29 February: the 28th) and may not be after `--to`. A
command that succeeds exits 0 and prints JSON (`show`: Markdown); a refusal exits 2 with one
`MARKET_POSITION_REGIME: ...` line on standard error. `plan`, `record` and `show` read no
setting. [PROCEDURE.md](PROCEDURE.md) gives each field and the step that follows.

## Architecture

The package `market_state_research.market_position_regime.script`:

| Module | Responsibility |
| --- | --- |
| `__main__` | The command line (`MARKET_POSITION_REGIME` label); resolves and checks the window first, then builds the client from `FRED_API` for `fetch` only. |
| `client` | HTTPS to the three fixed endpoints only (`www.finra.org`, `publicreporting.cftc.gov`, `api.stlouisfed.org`), FRED's key appended at send time and redacted from every message, statuses, bounded and whole bodies, no redirect. Its HTTP reading helpers are copies of the stock IV regime domain's (domains never import one another). |
| `periods` | Months, weeks named by their Tuesday, quarter ends and FRED's observation dates; when each source's document is due. |
| `finra` | The workbook's address, its parsing with the standard library (`zipfile`, `xml.etree`) and every rule (`parse_workbook`, `check_workbook`), its raw name. |
| `cftc` | The query (`query_url`), the rows and every rule (`check_row`, `check_answer`), the units and the E-mini conversion, the answer raw unit (`dump`, `read_answer`). |
| `fred` | The two series, their URL, FRED's answer and every rule (`check_response`, `check_answer`), the answer raw unit. |
| `indicators` | The growth, the ratio and the percentile over 52 weeks. |
| `store` | Reading and validating every raw file, the selection, the margin and futures rows over the whole archive, the two tables. |
| `chart` and `templates/chart.html` | The report (two charts on one page) and its twin, over `common.chart`: the vendored TradingView Lightweight Charts 5.2.1, pinned by SHA-256, and the page text helpers. |
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

### FRED's answers

`fred_{SERIES}_{TOKEN}.json`: one JSON object with exactly the keys `series`, `request` (the
URL without the key), `fetched_at` and `response`, FRED's answer as it came. Every read checks
every rule again (`fred.check_answer`): the keys and forms; the series one of the two and the
request its URL; the name against the series and the time; a time not after the clock and
after the newest quarter's end; FRED's answer with exactly its keys, in linear units, ordered
by date ascending, from offset 0, counted (`count` equal to the observations) and not cut at
its limit; each observation with exactly its four keys, dated a quarter's first day,
consecutive quarters ascending, its value a non-negative decimal or `.`. A newer answer is
written only when its values differ from the selected one's (FRED's realtime dates change
every day and are not compared).

## Fetching

`fetch` sends at most four requests a run (`workflow.py`): FINRA's workbook when a due month
is lacking; the CFTC's rows from the Monday of the first lacking week to the Sunday of the
last (a few hundred rows at most; the whole market since 2010 is 853); each FRED series whole
when a due quarter end is lacking from it. With `--refresh` it requests the workbook, every
due week of the span and both series again, whatever is stored. Per source it reports
`reused` (nothing lacking, no request), `new` (an answer written), `verified` (an answer that
holds nothing `raw/` lacks: nothing written) or `failed` (the request failed or the answer
failed a rule: nothing written, the reason given), and `pending`: the due documents the
source has not published yet. An answer is checked by the same rules as a raw file before it
is written.

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
  bytes); `tests/market_position_regime/fixtures/` holds the answer for 2023-04-03 to
  2025-11-16 (137 rows, across the change of unit and two Monday reports).

## FRED and Z.1 facts verified live (2026-10-20)

- `https://api.stlouisfed.org/fred/series/observations?series_id={SERIES}&file_type=json`
  needs `api_key`, FRED's 32 lowercase letters and digits: without it FRED answers HTTP 400
  `Bad Request.  Variable api_key is not set.` The keyless `fredgraph.csv` download refused
  repeated requests, so the keyed API is the route. FRED removed the Wilshire 5000 series in
  June 2024, so no listed-market capitalisation is available there.
- An answer holds `realtime_start`, `realtime_end`, `observation_start` (`1600-01-01`),
  `observation_end` (`9999-12-31`), `units` (`lin`), `output_type` (1), `file_type`,
  `order_by` (`observation_date`), `sort_order` (`asc`), `count`, `offset` (0), `limit`
  (100,000) and `observations`, each `{realtime_start, realtime_end, date, value}`; the
  realtime dates vary with the series and the day (2026-09-16 for one series and 2026-10-20
  for the other on 2026-10-20), so they are never compared.
- Both series: "Millions of U.S. Dollars", "Quarterly, End of Period", not seasonally
  adjusted, 323 observations from 1945-10-01 (Q4 1945) to 2026-04-01 (Q2 2026), last updated
  2026-09-11 (the Z.1 release of Q2 2026); values whole (`83050847`) or with one decimal
  (`48216.0`), and `.` in the first three quarters of each year from 1946 to 1951, when the
  accounts were annual.
- Q2 2026: `NCBEILQ027S` 83,050,847 and `BOGZ1LM793164105Q` 26,193,848, a market value of
  109,244,695; 2026-06's debit balances of 1,502,072 are 1.37 % of it.
- The Fed's series analyzer: FL103164105 is computed as FL103164115 (public corporate
  equities; closely held included before 1996 Q4) + FL103164125 (closely held corporate
  equities); LM793164105 is FL793164105, domestic financial sectors' corporate equities.

## Tests

`tests/market_position_regime/` runs offline: `fake_sources.py` answers the three sources
from data in memory as they do (FINRA's workbook bytes; the CFTC's rows of the `$where`
dates, the query checked to be exactly `query_url`'s; FRED's observations under the expected
key only, FRED's 400 otherwise; scripted statuses) and records every URL, the key cut from
FRED's; `support.py` builds FINRA's workbook byte by byte in its verified layout, TFF rows
and FRED answers from small numbers, and raw files as `fetch` names them; `fixtures/` holds
the CFTC answer recorded live on 2026-10-20, pinned by SHA-256 and never edited (the CFTC's
data are a US government work; no FINRA or FRED answer is kept). An autouse fixture refuses
any real request.
