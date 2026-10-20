# margin_edge

Market state research: each domain discloses one aspect of the state of the market as
reproducible facts and calculations, kept beside the source documents and records they rest
on. Hypotheses, investment calls and publication stay with the analyst: nothing here adds
regime or sentiment labels, rankings or trading advice.

Two parties work here ([AGENTS.md](AGENTS.md), Who does what). The maintainer (the owner,
working with Claude Code) makes the rules: every `AGENTS.md` and `PROCEDURE.md`, the scripts
and their tests, and the tools the repository nominates. An AI bot with a shell, such as Grok
Bot or a ChatGPT agent, follows them from its own host, keeps the watchlists, never edits a
rule, and opens an issue on
[yewcast97/margin_edge](https://github.com/yewcast97/margin_edge/issues) when one blocks it or
could be better. Nothing the bot produces is tracked.

## Domains

| Domain | What it discloses | Sources |
| --- | --- | --- |
| [`stock_iv_regime`](market_state_research/stock_iv_regime/AGENTS.md) ([procedure](market_state_research/stock_iv_regime/PROCEDURE.md)) | Per ticker and session, option-implied volatility percentiles (the 14-DTE 25-delta skew and ATM IV) and return–IV correlations, in one interactive report of two charts. | EODHD's options API, Tiingo's daily prices |
| [`fundamentals`](market_state_research/fundamentals/AGENTS.md) ([procedure](market_state_research/fundamentals/PROCEDURE.md)) | Per issuer and fiscal period, what its filings, earnings releases and earnings calls say, in eleven fields of verbatim quotes compiled into a time series. | SEC EDGAR, EarningsCalls.dev |
| [`posts`](market_state_research/posts/AGENTS.md) ([procedure](market_state_research/posts/PROCEDURE.md)) | What the social-media posters you nominate say, archived verbatim, fact-checked as `true`, `unverified` or `fake` with cited evidence, and reported on request, all by the bot's hand. | Each account, by the route the bot's host offers |

Each domain's `AGENTS.md` says what its outputs mean and how they are obtained, and its
`PROCEDURE.md` how the bot runs it; what the domains share (New York time, the `raw/`,
`formatted/` and `reports/` sections of their data, the API rule, the watchlists) is in
[market_state_research/AGENTS.md](market_state_research/AGENTS.md). Apart from them,
[`explore_hypothesis/`](explore_hypothesis/AGENTS.md) is where the bot tests the hypotheses
you state against the domains' data with [seikan](https://github.com/yewcast97/seikan), as its
own work.

## Setup

Requires [uv](https://docs.astral.sh/uv/) and Python 3.13 or newer. From the repository root:

```sh
uv sync --locked
```

The keys go in the repository-root `.env`, which Git ignores; each domain's `PROCEDURE.md`
says what its keys need:

```sh
EODHD_API="..."                            # stock_iv_regime: EODHD's "US Stock Options Data" (UnicornBay)
TIINGO_API="..."                           # stock_iv_regime: Tiingo's daily prices
SEC_USER_AGENT="Name contact@example.com"  # fundamentals: who runs the EDGAR client
EARNINGSCALLS_API="..."                    # fundamentals: EarningsCalls.dev's transcripts
```

`posts` needs a key only where the bot reads a platform through its API (`X_API="..."`).
The bot keeps the watchlists, which Git ignores: each ticker domain's own `watchlist.json`
([format](market_state_research/AGENTS.md#watchlists)) and the posters in
`market_state_research/posts/watchlist.json`
([format](market_state_research/posts/AGENTS.md#posters-accounts-and-routes)). Tell it which
stocks and posters to follow, or let it judge.

## Use

The bot runs each domain by its `PROCEDURE.md`. A scripted domain is a command line whose
`plan` says what comes next:

```sh
uv run --locked python -m market_state_research.stock_iv_regime.script plan
uv run --locked python -m market_state_research.fundamentals.script plan
```

`posts` has no command: ask the bot in your own words, such as "Did some_analyst say anything
about the semiconductor supply chain yesterday?"

## Verification

```sh
uv run --locked pytest
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked mypy
```

The tests run offline; [AGENTS.md](AGENTS.md) (Verification) says what each check covers.

## License

[MIT](LICENSE).
