# Repository principles and architecture

## Who does what

Two parties work here, and only the first changes the repository.

- **The maintainer** (the owner, working with Claude Code) makes the rules: every
  `AGENTS.md` and `PROCEDURE.md`, the scripts of market state research and their tests, the
  dependencies and their lock, and the tools the repository nominates (seikan, for
  hypothesis tests). The maintainer alone commits and pushes.
- **The bot** (Grok Bot, a ChatGPT agent or another AI agent with a shell) follows the rules
  from its own host: it runs the commands and follows each domain's `PROCEDURE.md`. In the
  scripted domains Python reads every source over HTTPS, through an API or a public file at a
  fixed address, so no step needs a browser; in `posts` the bot reads each nominated account
  by whatever route its host offers. It
  maintains the watchlists, `market_state_research/<domain>/watchlist.json`: the stock
  tickers of `stock_iv_regime` and of `fundamentals`, and the posters of `posts`. It adds and
  removes entries on the owner's instruction or by its own judgment, and reports each change
  it makes. Besides the watchlists, it writes only what a procedure lets it write under a
  `data/` directory, in `posts` each poster's folder `market_state_research/posts/<poster>/`
  (the profile and its `data/`) and, in hypothesis exploration, its own work under
  `explore_hypothesis/<name>/` (the thesis, its script, its `procedure.md` and its data,
  under the conventions of [explore_hypothesis/AGENTS.md](explore_hypothesis/AGENTS.md)). It
  never edits a rule, a tracked script, a test, a tracked file or a stored value; it commits
  and pushes nothing and never runs `uv lock`.

When a rule, a message, a validator or a tool blocks or misleads the bot, it does not work
around it: it opens a GitHub issue, at https://github.com/yewcast97/margin_edge/issues for
this repository or https://github.com/yewcast97/seikan/issues for seikan, giving the
command, `git rev-parse HEAD`, the output verbatim with every key redacted, what it expected
and what it suggests. The bot is encouraged to open one whenever it sees how either could
be better. The maintainer decides and changes the rules.

The repository tracks no dynamic data: what the bot produces stays on its host. Every
`data/` directory is ignored by Git (a scripted domain's `.gitignore` alone is tracked), and
so are every poster's folder, every hypothesis's folder, the watchlists and `.env`.

## Working rules

Use shell commands for local files, calculations and tests when they fit the task.
Keep personal configuration and secrets in the ignored repository-root `.env`.
Tracked instructions and fixtures may name environment variables, never their
private values. Do not copy private settings into raw files, reports or messages.

For market state research, follow [market_state_research/AGENTS.md](market_state_research/AGENTS.md),
the domain's `AGENTS.md` and its `PROCEDURE.md`. For hypothesis tests with seikan, follow
[explore_hypothesis/AGENTS.md](explore_hypothesis/AGENTS.md).
Never invent observations, edit stored values directly or weaken validation to
admit a failed file. Market data of a session (`stock_iv_regime`'s chains and prices,
`market_position_regime`'s VIX) is read as of the last completed XNYS session, and no
intraday live value is stored; a document that is no session's (`market_position_regime`'s
months and weeks, `fundamentals`, `posts`) has no session logic and is dated by its own date
(see [market_state_research/AGENTS.md](market_state_research/AGENTS.md)). Detailed
procedures belong to their domain.

## Repository layout

| Path | Responsibility |
| --- | --- |
| `README.md` | A brief overview for people: the purpose, the domains, setup, use and verification. It states no rule: it links to the `AGENTS.md` and `PROCEDURE.md` files that hold them. |
| `market_state_research/AGENTS.md` | Research principles, the domain layout, the data layout and the API rule. |
| `market_state_research/TODO.md` | The maintainer's research scope and backlog, ignored by Git: a checkout has none. |
| `market_state_research/<domain>/` | One domain: its guidance (`AGENTS.md`: the aim and the meaning of the outputs, then the method, architecture and facts verified live), its operations (`PROCEDURE.md`), its Python package (`script/`, in the scripted domains), its runtime data (`data/`) and, in a domain that works through a list, its `watchlist.json`. |
| `market_state_research/<domain>/watchlist.json` | A domain's watchlist, maintained by the bot (Who does what) and ignored by Git like `.env`, so a checkout has none until the bot writes it: in `stock_iv_regime` and in `fundamentals` the stock tickers, `{"stock": [...]}`, which `plan` and `fetch` default to and tickers given on the command line override ([market_state_research/AGENTS.md](market_state_research/AGENTS.md), Watchlists); in `posts` the posters and their accounts. There is no shared watchlist, and hypothesis exploration reads none. |
| `market_state_research/posts/` | The domain without a script: what nominated posters say, archived verbatim per poster, fact-checked and answered by reports, all by the bot's hand under its `AGENTS.md` and `PROCEDURE.md`, the domain's only tracked files; its `watchlist.json` (the posters) and every poster's folder (`<poster>/`: `profile.md` and `data/`) are ignored by Git. |
| `explore_hypothesis/` | Hypothesis exploration with seikan, the bot's own work and free of the watchlists: one folder per hypothesis (`<name>/` with the thesis, `procedure.md`, `script/` and `data/`), written by the bot on its host and ignored by Git, under a module `AGENTS.md` bound to no domain, its only tracked file, which sets the conventions of that work; a hypothesis reads or copies the domains' data, never changes it, and fetches nothing. |
| `market_state_research/common/` | Shared package bound to no domain: New York time, XNYS sessions and market status, the `raw/`, `formatted/` and `reports/` sections of a domain's `data/` with their one write rule (`layout`), text, the CLI conventions labelled per domain, the reader of a ticker domain's watchlist, the `.env` settings, and the vendored chart library with the page text every report page shares (`chart`, `vendor/`). |
| `tests/conftest.py` | Repository-wide guard: the run fails if any test changes a `market_state_research/*/data` directory, a poster's folder `market_state_research/posts/*/` or an `explore_hypothesis/*/data` directory, and every test fails when no `market_state_research/*/data` directory is found, so that a rename cannot switch the guard off. |
| `tests/common/` | Offline pytest suite for the shared package; host time-zone fixture in `conftest.py`; New York clock readings, foreign-digit text (`foreign_digits`), a zone without an offset (`OffsetlessZone`) and file-tree helpers (`tree`, `snapshot`, `leftovers`, `mode`) in `support.py`. |
| `tests/stock_iv_regime/` | Offline pytest suite for the stock IV regime domain; clock, data-directory, watchlist-file and host time-zone fixtures and a guard refusing any real request (EODHD or Tiingo) in `conftest.py`; clock readings, record builders from strike, delta and IV text (the hand-worked quotes `CALLS` and `PUTS`), chain builders and daily-bar and prices builders in `support.py`; a recording stand-in for EODHD's two options endpoints answering from records in memory in `fake_eodhd.py` and one for Tiingo's daily prices endpoint in `fake_tiingo.py` (no Tiingo answer is recorded: its data may not be redistributed); two pages recorded live from EODHD in `fixtures/`, pinned by SHA-256 and never edited. |
| `tests/market_position_regime/` | Offline pytest suite for the market position regime domain; data-directory and host time-zone fixtures and a guard refusing any real request (FINRA, the CFTC or Cboe) in `conftest.py`; clock readings, FINRA's workbook built byte by byte in its verified layout, TFF rows, Cboe's VIX file and raw-file savers in `support.py`; a recording stand-in for the three sources answering from data in memory in `fake_sources.py`; one CFTC answer recorded live in `fixtures/`, pinned by SHA-256 and never edited (no FINRA or Cboe answer is kept). |
| `tests/fundamentals/` | Offline pytest suite for the fundamentals domain; clock, data-directory and host time-zone fixtures in `conftest.py`; EDGAR JSON, synthetic inline-XBRL filings, 8-K filing index pages and earnings-release exhibits in `edgar_support.py`; a recording fake of the EDGAR HTTP layer in `fake_edgar.py`; a recording fake of EarningsCalls.dev's HTTP layer in `fake_earningscalls.py`; call lists and transcripts in the provider's verified layout with synthetic turns of known speakers in `calls_support.py`; urllib driven offline over a fake HTTPS handler in `transport_support.py`; workflow fixtures in `workflow_support.py`. No test reaches the network or reads the real `.env`. |
| `pyproject.toml`, `uv.lock` | Python 3.13 or newer, the dependencies (seikan from its GitHub `main` branch, pinned to one commit by the lock), the `dev` group (pytest, Ruff, mypy), their configuration and the reproducible lock. |

The implemented domains are [stock_iv_regime](market_state_research/stock_iv_regime/AGENTS.md)
(EODHD's options API and Tiingo's daily prices),
[market_position_regime](market_state_research/market_position_regime/AGENTS.md) (FINRA's
margin statistics, the CFTC's Traders in Financial Futures and Cboe's VIX history),
[fundamentals](market_state_research/fundamentals/AGENTS.md) (SEC EDGAR and the
EarningsCalls.dev transcript API) and [posts](market_state_research/posts/AGENTS.md) (what
nominated posters say, read by the bot's own route and fact-checked by hand). Each domain's
`AGENTS.md` defines the aim and the meaning of its outputs, then its method, architecture and
source facts; its sibling `PROCEDURE.md` describes the operational workflow.

## Verification

Run from the repository root after changing code, templates, tests or dependencies:

```sh
uv run --locked pytest
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked mypy
```

All four must pass. Tests run offline and write only to temporary directories; the
suite fails if a test changes production runtime data. pytest cannot execute a chart's
JavaScript or show a page's layout, so also inspect a rendered chart or report in a browser
after changing its template or a vendored library. Ruff skips vendored files. mypy checks
the `common` package and every scripted domain's `script/` package in strict mode, not the
tests. exchange-calendars and pandas ship no type information, so their values enter as
`Any`; give such a value an explicit type where it leaves the function that read it rather
than loosening the configuration.

## Maintenance

Once a week the maintainer checks whether seikan's `main` branch has moved past the commit
`uv.lock` pins, and upgrades the pin when the suite passes on it
([explore_hypothesis/AGENTS.md](explore_hypothesis/AGENTS.md), Keeping seikan current). The
bot plays no part in it.
