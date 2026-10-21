# The bot's manual: principles and layout

This repository is the manual of an AI agent with a shell, Grok Bot, Muse Bot or another (the
bot), and the bot is its reader: its `AGENTS.md` and `PROCEDURE.md` files state, for the bot,
the rules it obeys (the procedures address it as you), and its scripts do the fixed work
those rules name. The bot obeys them from its own host and yields data for the people it
serves to read. Git tracks the rules and the scripts, never the data.

## The bot

The bot runs the commands, follows each domain's `PROCEDURE.md`, reports back what they
yield, and adds no value, label or judgment the rules do not ask of it. In the scripted
domains Python reads every source over HTTPS, through an API or a public file at a fixed
address, so no step needs a browser; in `posts` the bot reads each nominated account, and
in hypothesis exploration any other source, by whatever route its host offers. It writes
only what a rule lets it write, and Git ignores all of it:

- in a `data/` directory, what a procedure names;
- the watchlists, `market_state_research/<domain>/watchlist.json` (the stock tickers of
  `stock_iv_regime` and of `fundamentals`, the posters of `posts`), adding and removing
  entries when the user asks or by its own judgment and reporting each change;
- in `posts`, each poster's folder `market_state_research/posts/<poster>/` (the profile and
  its `data/`);
- in the repository-root `.env`, only a line a procedure lets it add with the user's
  agreement (`fundamentals`' `SEC_USER_AGENT`); every key there is the user's to set on the
  host;
- in hypothesis exploration, its own work under `explore_hypothesis/<name>/` (the thesis, its
  script, its `procedure.md` and its data, from the domains or from any other source, under
  the conventions of [explore_hypothesis/AGENTS.md](explore_hypothesis/AGENTS.md)). That
  work is the bot's product, like its data: it binds only the reruns of its own hypothesis,
  nothing tracked reads it, and it is never a rule of the repository.

It never writes or edits a tracked file (a rule, a script, a template, a test, the lock),
never edits by hand a value a command stored, never commits or pushes, and never runs
`uv lock`.

The bot serves people: the owner, and whoever the owner lets ask it. Whoever asks is the
user, in every file here: the user asks for data and reads it. A request settles what a
procedure leaves open (a window, tickers, a poster, an interval, a refresh). A request that
only a change to a tracked file could meet is not the bot's to meet: it says so and, when
asked, opens an issue with it (Feedback), and never meets it with a workaround of its own.

## Feedback

When a rule, a message, a validator or a tool blocks or misleads the bot, it does not work
around it: it opens a GitHub issue, at https://github.com/yewcast97/margin_edge/issues for
this repository or https://github.com/yewcast97/seikan/issues for seikan, giving the
command, `git rev-parse HEAD`, the output verbatim with every key redacted, what it expected
and what it suggests; an issue on seikan also gives the seikan commit `uv.lock` pins, as the
lines `grep -A2 '^name = "seikan"' uv.lock` prints. The bot is encouraged to open one
whenever it sees how either could be better, giving likewise the commands it ran,
`git rev-parse HEAD` and the output its case rests on. Before opening an issue, it searches
the open ones and comments on one that already covers its case instead. The issue ends its
part in the problem: it reports the issue's link back and goes on with what the rules allow.

## Working rules

Use shell commands for local files and calculations when they fit the task. Personal
configuration and secrets stay in the ignored repository-root `.env`: name a setting by its
variable, never by its value, and never copy a private value into a raw file, a report, a
message or an issue.

For market state research, follow [market_state_research/AGENTS.md](market_state_research/AGENTS.md),
the domain's `AGENTS.md` and its `PROCEDURE.md`. For hypothesis tests with seikan, follow
[explore_hypothesis/AGENTS.md](explore_hypothesis/AGENTS.md).
Never invent observations, edit stored values directly or weaken validation to
admit a failed file. Market data of a session (`stock_iv_regime`'s chains and prices,
`market_position_regime`'s VIX) is read as of the last completed XNYS session, and no
intraday live value is stored; a document that is no session's (`market_position_regime`'s
months and weeks, `fundamentals`, `posts`) has no session logic and is dated by its own date
(see [market_state_research/AGENTS.md](market_state_research/AGENTS.md)).

## Repository layout

| Path | Responsibility |
| --- | --- |
| `README.md` | The manual's overview, for the bot: the purpose, the domains, setup and use. It states no rule: it links to the `AGENTS.md` and `PROCEDURE.md` files that hold them. |
| `market_state_research/AGENTS.md` | Research principles, the domain layout, the watchlists, the data layout and the API rule. |
| `market_state_research/<domain>/` | One domain: its guidance (`AGENTS.md`: the aim and the meaning of the outputs, then the method, architecture and facts verified live), its operations (`PROCEDURE.md`), its Python package (`script/`, in the scripted domains), its runtime data (`data/`) and, in a domain that works through a list, its `watchlist.json`. |
| `market_state_research/<domain>/watchlist.json` | A domain's watchlist, maintained by the bot (The bot) and ignored by Git like `.env`, so a checkout has none until the bot writes it: in `stock_iv_regime` and in `fundamentals` the stock tickers, `{"stock": [...]}`, which `plan` and `fetch` default to and tickers given on the command line override ([market_state_research/AGENTS.md](market_state_research/AGENTS.md), Watchlists); in `posts` the posters and their accounts. There is no shared watchlist, and hypothesis exploration reads none. |
| `market_state_research/posts/` | The domain without a script: what nominated posters say, archived verbatim per poster, fact-checked and answered by reports, all by the bot's hand under its `AGENTS.md` and `PROCEDURE.md`, the domain's only tracked files; its `watchlist.json` (the posters) and every poster's folder (`<poster>/`: `profile.md` and `data/`) are ignored by Git. |
| `explore_hypothesis/` | Hypothesis exploration with seikan, the bot's own work and free of the watchlists: one folder per hypothesis (`<name>/` with the thesis, `procedure.md`, `script/` and `data/`), written by the bot on its host and ignored by Git, under a module `AGENTS.md` bound to no domain, its only tracked file, which sets the conventions of that work; a hypothesis reads or copies the domains' data, never changing it, and reads any other source by whatever route the bot's host offers. |
| `market_state_research/common/` | Shared package bound to no domain: New York time, XNYS sessions and market status, the `raw/`, `formatted/` and `reports/` sections of a domain's `data/` with their one write rule (`layout`), text, the CLI conventions labelled per domain, the reader of a ticker domain's watchlist, the `.env` settings, and the vendored chart library with the page text every report page shares (`chart`, `vendor/`). |
| `tests/` | The scripts' offline tests, which no procedure runs: they reach no source and change no domain's or hypothesis's data. |
| `pyproject.toml`, `uv.lock` | Python 3.13 or newer and the dependencies, seikan among them (one commit of its GitHub `main` branch), locked: `uv sync --locked` installs them, and every command runs with `uv run --locked`. |

The domains are [stock_iv_regime](market_state_research/stock_iv_regime/AGENTS.md)
(EODHD's options API and Tiingo's daily prices),
[market_position_regime](market_state_research/market_position_regime/AGENTS.md) (FINRA's
margin statistics, the CFTC's Traders in Financial Futures and Cboe's VIX history),
[fundamentals](market_state_research/fundamentals/AGENTS.md) (SEC EDGAR and the
EarningsCalls.dev transcript API) and [posts](market_state_research/posts/AGENTS.md) (what
nominated posters say, read by the bot's own route and fact-checked by hand). Each domain's
`AGENTS.md` defines the aim and the meaning of its outputs, then its method, architecture and
source facts; its sibling `PROCEDURE.md` describes the operational workflow.
