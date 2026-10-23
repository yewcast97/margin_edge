# margin_edge

This repository is the manual of an AI agent with a shell, such as Grok Bot or Muse Bot (the
bot), and the bot is its reader. The rules the bot obeys are in the `AGENTS.md` and
`PROCEDURE.md` files, beginning with the root [AGENTS.md](AGENTS.md): what the bot does and
writes, whom it serves and how it gives feedback. This overview states no rule: it says where
each one is.

The bot runs market state research from its own host: each domain discloses one aspect of the
state of the market as reproducible facts and calculations, kept beside the source documents
and records they rest on, for the people the bot serves to read; investment calls and
publication stay with them. In [`explore_hypothesis/`](explore_hypothesis/AGENTS.md) it
tests the user's hypotheses with [seikan](https://github.com/yewcast97/seikan), as its own
work within that module's conventions: everything there but its `AGENTS.md`, the scripts
included, is the bot's, and a hypothesis's data come from the domains or from any other
source.

## Domains

| Domain | What it discloses | Sources |
| --- | --- | --- |
| [`stock_iv_regime`](market_state_research/stock_iv_regime/AGENTS.md) ([procedure](market_state_research/stock_iv_regime/PROCEDURE.md)) | Per ticker and session, option-implied volatility percentiles (the 14-DTE 25-delta skew, the 14-DTE ATM IV and the term structure from 14 to 30 days) and return–IV correlations, in one interactive report of two charts. | EODHD's options API, Tiingo's daily prices |
| [`market_position_regime`](market_state_research/market_position_regime/AGENTS.md) ([procedure](market_state_research/market_position_regime/PROCEDURE.md)) | For the US equity market over a window of dates, margin debt by month, S&P 500 futures positioning by week (asset managers' net long and leveraged funds' net short as percentiles over 52 weeks) and the VIX and the SKEW by session (each as a percentile over 252 sessions), in one interactive report of three charts. | FINRA's margin statistics, the CFTC's Traders in Financial Futures, Cboe's VIX and SKEW histories |
| [`fundamentals`](market_state_research/fundamentals/AGENTS.md) ([procedure](market_state_research/fundamentals/PROCEDURE.md)) | Per issuer and season (fiscal period), what changed against stated baselines (68 items: figures from the filings, the issuer's statements, insiders' trades, the earnings call, the filings' timing), each item's old and new values with verbatim evidence, one report per season listing every item by importance. | SEC EDGAR, EarningsCalls.dev |
| [`posts`](market_state_research/posts/AGENTS.md) ([procedure](market_state_research/posts/PROCEDURE.md)) | What nominated social-media posters say, archived verbatim, fact-checked as `true`, `unverified` or `fake` with cited evidence, and reported on request, all by the bot's hand. | Each account, by the route the bot's host offers |

Each domain's `AGENTS.md` says what its outputs mean and how they are obtained, and its
`PROCEDURE.md` how the bot runs it; what the domains share (New York time, the `raw/`,
`formatted/` and `reports/` sections of their data, the API rule, the watchlists) is in
[market_state_research/AGENTS.md](market_state_research/AGENTS.md).

## Setup

The host needs [uv](https://docs.astral.sh/uv/) and Python 3.13 or newer. From the repository
root:

```sh
uv sync --locked
```

The settings are lines of the repository-root `.env`, which Git ignores (a variable of the
process environment takes precedence). Each domain's `PROCEDURE.md` says which it reads and
what to do while one is missing. `market_position_regime` reads none, and `posts` reads a
platform's key, `{PLATFORM}_API`, only where the bot reads that platform through its API:

```sh
EODHD_API="..."                            # stock_iv_regime: EODHD's "US Stock Options Data" (UnicornBay)
TIINGO_API="..."                           # stock_iv_regime: Tiingo's daily prices
SEC_USER_AGENT="Name contact@example.com"  # fundamentals: whom EDGAR's requests are made for
EARNINGSCALLS_API="..."                    # fundamentals: EarningsCalls.dev's transcripts
X_API="..."                                # posts: X's API, where the bot reads X through it
```

The watchlists are the bot's to keep, and Git ignores them too, so a checkout has none until
the bot writes them: each ticker domain's own `watchlist.json`
([format](market_state_research/AGENTS.md#watchlists)) and the posters in
`market_state_research/posts/watchlist.json`
([format](market_state_research/posts/AGENTS.md#posters-accounts-and-routes)), holding the
stocks and posters the user names or the bot judges worth following.

## Use

The bot runs each domain by its `PROCEDURE.md`. A scripted domain is a command line whose
`plan` says what comes next:

```sh
uv run --locked python -m market_state_research.stock_iv_regime.script plan
uv run --locked python -m market_state_research.market_position_regime.script plan
uv run --locked python -m market_state_research.fundamentals.script plan
```

`posts` has no command: the user asks in their own words, such as "Did some_analyst say
anything about the semiconductor supply chain yesterday?", and the bot does the work by hand.

## Feedback

The bot can open an issue for any problem it finds or improvement it sees: on
[yewcast97/margin_edge](https://github.com/yewcast97/margin_edge/issues) for this repository,
and on [yewcast97/seikan](https://github.com/yewcast97/seikan/issues) for seikan. The root
[AGENTS.md](AGENTS.md#feedback) says when it must open one and what an issue gives.
