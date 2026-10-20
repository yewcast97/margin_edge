# Repository principles and architecture

## Who does what

Two parties work here, and only the first changes the repository.

- **The maintainer** (the owner, working with Claude Code) makes the rules: every
  `AGENTS.md` and `PROCEDURE.md`, the scripts of market state research and their tests, the
  dependencies and their lock, and the tools the repository nominates (seikan, for
  hypothesis tests). The maintainer alone commits and pushes.
- **The bot** (Grok Bot, a ChatGPT agent or another AI agent with a shell) follows the rules
  from its own host: it runs the commands and follows each domain's `PROCEDURE.md`. In the
  scripted domains every source is read through an API, so no step needs a browser; in
  `posts` the bot reads each nominated account by whatever route its host offers. It writes
  only what a procedure lets it write under a `data/` directory, in `posts` each poster's
  folder `market_state_research/posts/<poster>/` (the profile and its `data/`) and, in
  hypothesis exploration, its own work under `explore_hypothesis/<name>/` (the thesis, its
  script, its `procedure.md` and its data, under the conventions of
  [explore_hypothesis/AGENTS.md](explore_hypothesis/AGENTS.md)). It never edits a rule, a
  tracked script, a test, a tracked file or a stored value; it commits and pushes nothing
  and never runs `uv lock`.

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
admit a failed file. The market-data domains work as of the last completed XNYS session:
they never store intraday live values; a domain that reads no market data (`fundamentals`,
`posts`) has no session logic and dates its documents by their own dates (see
[market_state_research/AGENTS.md](market_state_research/AGENTS.md)). Detailed procedures
belong to their domain.

## Repository layout

| Path | Responsibility |
| --- | --- |
| `README.md` | A brief overview for people: the purpose, the domains, setup, use and verification. It states no rule: it links to the `AGENTS.md` and `PROCEDURE.md` files that hold them. |
| `market_state_research/AGENTS.md` | Research principles, the domain layout, the data layout and the API rule. |
| `market_state_research/TODO.md` | The maintainer's research scope and backlog, ignored by Git: a checkout has none. |
| `market_state_research/<domain>/` | One domain: its guidance (`AGENTS.md`: the aim and the meaning of the outputs, then the method, architecture and facts verified live), its operations (`PROCEDURE.md`), its Python package (`script/`, in the scripted domains), its runtime data (`data/`) and, optionally, its own `watchlist.json`. |
| `market_state_research/posts/` | The domain without a script: what nominated posters say, archived verbatim per poster, fact-checked and answered by reports, all by the bot's hand under its `AGENTS.md` and `PROCEDURE.md`, the domain's only tracked files; its `watchlist.json` (the user's posters) and every poster's folder (`<poster>/`: `profile.md` and `data/`) are ignored by Git. |
| `explore_hypothesis/` | Hypothesis exploration with seikan, the bot's own work and free of the watchlists: one folder per hypothesis (`<name>/` with the thesis, `procedure.md`, `script/` and `data/`), written by the bot on its host and ignored by Git, under a module `AGENTS.md` bound to no domain, its only tracked file, which sets the conventions of that work; a hypothesis reads or copies the domains' data, never changes it, and fetches nothing. |
| `market_state_research/common/` | Shared package bound to no domain: New York time, XNYS sessions and market status, the `raw/`, `formatted/` and `reports/` sections of a domain's `data/` with their one write rule (`layout`), text, the CLI conventions labelled per domain, the watchlist reader (the repository-root watchlist and a domain's own) and the `.env` settings. |
| `tests/conftest.py` | Repository-wide guard: the run fails if any test changes a `market_state_research/*/data` directory, a poster's folder `market_state_research/posts/*/` or an `explore_hypothesis/*/data` directory, and every test fails when no `market_state_research/*/data` directory is found, so that a rename cannot switch the guard off. |
| `tests/common/` | Offline pytest suite for the shared package; host time-zone fixture in `conftest.py`; New York clock readings, foreign-digit text (`foreign_digits`), a zone without an offset (`OffsetlessZone`) and file-tree helpers (`tree`, `snapshot`, `leftovers`, `mode`) in `support.py`. |
| `tests/market_regime/` | Offline pytest suite for the market regime domain; clock, data-directory, watchlist-file and host time-zone fixtures and a guard refusing any real request (EODHD or Tiingo) in `conftest.py`; clock readings, record builders from strike, delta and IV text (the hand-worked quotes `CALLS` and `PUTS`), chain builders and daily-bar and prices builders in `support.py`; a recording stand-in for EODHD's two options endpoints answering from records in memory in `fake_eodhd.py` and one for Tiingo's daily prices endpoint in `fake_tiingo.py` (no Tiingo answer is recorded: its data may not be redistributed); two pages recorded live from EODHD in `fixtures/`, pinned by SHA-256 and never edited. |
| `tests/fundamentals/` | Offline pytest suite for the fundamentals domain; clock, data-directory and host time-zone fixtures in `conftest.py`; EDGAR JSON, synthetic inline-XBRL filings, 8-K filing index pages and earnings-release exhibits in `edgar_support.py`; a recording fake of the EDGAR HTTP layer in `fake_edgar.py`; a recording fake of EarningsCalls.dev's HTTP layer in `fake_earningscalls.py`; call lists and transcripts in the provider's verified layout with synthetic turns of known speakers in `calls_support.py`; urllib driven offline over a fake HTTPS handler in `transport_support.py`; workflow fixtures in `workflow_support.py`. No test reaches the network or reads the real `.env`. |
| `watchlist.json` | The user's default watchlist of tickers for market state research, ignored by Git like `.env`: the `stock` tickers are each scripted domain's `plan` and `fetch` default, unless the domain has its own `watchlist.json` beside its `AGENTS.md`, which then replaces it for that domain; tickers given on the command line override both; `index` is reserved for index workflows. Hypothesis exploration reads no watchlist, and `posts` reads only its own, `market_state_research/posts/watchlist.json`, which lists posters. A checkout has none until the user writes it ([market_state_research/AGENTS.md](market_state_research/AGENTS.md), Watchlists, gives its format). |
| `pyproject.toml`, `uv.lock` | Python 3.13 or newer, the dependencies (seikan from its GitHub `main` branch, pinned to one commit by the lock), the `dev` group (pytest, Ruff, mypy), their configuration and the reproducible lock. |

The implemented domains are [market_regime](market_state_research/market_regime/AGENTS.md)
(EODHD's options API and Tiingo's daily prices),
[fundamentals](market_state_research/fundamentals/AGENTS.md) (SEC EDGAR and the
EarningsCalls.dev transcript API) and [posts](market_state_research/posts/AGENTS.md) (what
nominated posters say, read by the bot's own route and fact-checked by hand). Each domain's
`AGENTS.md` defines the aim and
the meaning of its outputs, then its method, architecture and source facts; its sibling
`PROCEDURE.md` describes the operational workflow.

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
