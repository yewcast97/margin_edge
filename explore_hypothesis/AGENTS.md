# Hypothesis exploration: conventions

This is where hypotheses are tested with [seikan](https://github.com/yewcast97/seikan), a
stateless forward-return event-study engine: it reads a thesis (JSON) and strict CSV feeds,
measures every parameter × horizon cell the thesis declares, writes the files the caller names
and selects no winner. seikan is a dependency from its GitHub `main` branch, pinned by `uv.lock`
to one commit; `uv lock --upgrade-package seikan` moves the pin to the branch's newest commit, and
the maintainer checks for a newer one every week (Keeping seikan current, below). The repository's
principles, and who makes the rules (the maintainer) and who follows them (the bot), are in the
root [AGENTS.md](../AGENTS.md). This file is bound to no domain, and it is the only tracked file
of this module.

## Who does what here

Market state research discloses the state of the market, one aspect per domain, under each
domain's procedure: two domains by fixed scripts that the maintainer makes and tests, which the
bot only runs, and `posts` by the bot's own hand. Hypothesis exploration tests the bot's theses
against that picture, and welcomes creativity: for each hypothesis the user states, the bot
does the whole work on its own host, the thesis, its own script that prepares seikan's feeds,
the procedure it follows, the feeds, the seikan runs and the report back. The maintainer writes
none of it and only this file, whose conventions keep the bot's work maintainable: whoever
opens a hypothesis's folder later, the bot included, can read what was tested, from which data,
and run it again. Nothing under `explore_hypothesis/<name>/` is tracked: the root `.gitignore`
ignores everything here but this file. When a convention or seikan blocks the bot, it opens an
issue (root [AGENTS.md](../AGENTS.md), Who does what).

## Independence

A hypothesis's data are its own, independent of market state research's.

- It reads a domain's `data/` and never changes it: `raw/` through the domain's own `script`
  package (its validation, selection and derivation, never a parser of the bot's), or the
  domain's `formatted/` tables; `posts`, which has no package, is read as the Markdown files
  its `AGENTS.md` defines, in each poster's folder. It may copy such files into its own
  `data/source/` and adapt them there, through its script.
- It writes only under its own folder, and no domain reads it: nothing a hypothesis does
  changes a domain's data, outputs or freshness.
- Nothing here fetches. A source no domain supplies is asked of the maintainer, in an issue,
  as a domain under `market_state_research`; the stocks' daily prices, for one, are
  `stock_iv_regime`'s, from Tiingo.
- No watchlist applies: a hypothesis names its tickers.

## Layout

```text
explore_hypothesis/
├── AGENTS.md                  this file
└── <name>/                    the bot's, ignored by Git
    ├── <name>.json            the seikan thesis
    ├── procedure.md           how the feeds are built and seikan is run, step by step
    ├── script/                the bot's Python package that prepares the feeds
    └── data/
        ├── source/            copies of domain files, as copied
        ├── formatted/         the feeds, one folder per ticker
        └── reports/           what seikan writes
```

| Part | Convention |
| --- | --- |
| `<name>` | Lowercase ASCII letters, digits and underscores, a letter first: the folder's and the package's name. |
| `<name>.json` | The thesis in seikan's DSL. It names its series (targets, external feeds, the benchmark) and never locates them; `seikan hash` validates it and lists the data keys a run must bind. No script writes or edits it. |
| `procedure.md` | The steps in order, so that another run repeats them: the thesis in one sentence; the domain data it reads (domains, sections, tickers, dates) and the domain procedure that supplies them; the files copied into `data/source/`; the script's command and what it writes; `seikan check-data` on each feed; `seikan hash`; the `seikan run` command with every binding and output path; what to report back. It changes whenever the steps change. |
| `script/` | A package run from the repository root as `uv run --locked python -m explore_hypothesis.<name>.script …` (Conventions of a script). |
| `data/source/` | Files copied from a domain's `data/`, byte for byte, under the domain's own path (`stock_iv_regime/formatted/INTC/volatility.csv`). A copy is never edited; a newer one replaces it only by being copied again. |
| `data/formatted/{TICKER}/{SOURCE}.csv` | One feed per ticker and source in seikan's strict contract, rewritten by the script. |
| `data/reports/` | seikan's outputs (`--report-out`, `--trades-out`, `--root-series-out`, `--entry-flags-out`), each name carrying a New York time token (`common.times.timestamp_token`) so that no report is overwritten. |

The repository-root `tests/conftest.py` fails the test run if a test changes any
`explore_hypothesis/*/data` directory.

## Conventions of a script

The script is the bot's and is not checked by mypy or pytest: `seikan check-data` on every
feed it writes is the gate. These conventions make it readable and repeatable.

- Its `__main__.py` opens with a docstring stating the thesis in one sentence, the data it
  reads (domain, section, file names) and every column it writes, with the formula of any
  value it derives.
- It is deterministic: the same inputs give the same bytes. It sends no request and reads no
  watchlist.
- It runs from the repository root with locked dependencies, takes its tickers on the command
  line (at least one), `--source-dir PATH` (where it reads) and `--data-dir PATH` (the
  hypothesis's `data/`), and prints JSON: one entry per ticker with the feed's path, its rows,
  its first and last dates, the unfetched sessions inside it and the sessions whose value cells
  are empty.
- Every failure is one `LABEL: …` line on standard error with exit status 2 and no feed
  written; `LABEL` is the hypothesis's own (`market_state_research.common.cli.Parser`). Every
  ticker is read before anything is written, so one refused ticker leaves every feed as it was.
- It uses `market_state_research.common` for the parser, the data layout, New York time and
  ticker text, and a domain's `script` package to read that domain's raw files. It refuses
  while the domain lists an invalid raw file (the fix is the domain's procedure), never
  weakens a domain's check and imports nothing from another hypothesis.

## Principles of a feed

- A feed is seikan's strict CSV: a `datetime` column of timezone-naive ISO 8601 timestamps,
  unique and ascending; every other column numeric, named in lowercase ASCII letters, digits and
  underscores; an empty cell is a hole that seikan never fills. Values are written in plain
  decimal notation: a domain's values exactly as it derives them, or the script's own
  derivation of them, stated in its docstring. Nothing is invented, estimated or carried
  forward.
- A row's timestamp is when its values became available. seikan anchors a value on the first
  bar stamped at or after it and fills a bar where the entry condition holds at the next bar's
  open. A value as of a session's close is stamped with the session's date, the date of that
  session's daily price bar, so it is exactly as available as that bar's close.
- A value fetched after its session is what the provider serves at the time of the fetch.
  Whether it served the same at the session's close cannot be checked, and seikan leaves such
  vintages to the caller, so a report built on such feeds says so.
- Missing data stays explicit. Where the domain gives no value, the cell is empty. A session the
  domain did not fetch has no row, so seikan carries the previous row over it: the script
  reports how many such sessions lie inside each feed, and a thesis that reads the feed bounds
  the value's age with `days_since`.
- Feeds hold values only: no regime labels, thresholds, rankings or trading advice. seikan
  selects no best cell, and nobody summarises its cells into a verdict: the report back quotes
  the cells and their checklist as they stand, with the grid size they were measured in.
- Every time written, named or printed is New York time
  ([market_state_research/AGENTS.md](../market_state_research/AGENTS.md)).

## seikan

```sh
uv run --locked seikan schema                                                   # the whole contract, machine-readable
uv run --locked seikan hash explore_hypothesis/<name>/<name>.json              # the thesis's identity and the data keys to bind
uv run --locked seikan check-data explore_hypothesis/<name>/data/formatted/INTC/<source>.csv
uv run --locked seikan run explore_hypothesis/<name>/<name>.json --data KEY=PATH --report-out explore_hypothesis/<name>/data/reports/<name>_<TOKEN>.json
```

Exit status 0 means the command completed and every nominated output was written, never that
the evidence looked good; 2 means a feed failed the strict data contract (`check-data` says
which rule), 3 an invalid request (the thesis, a threshold or an output path), 4 an internal
error. A failing `check-data` is fixed in the script or at its source, never by editing a feed
by hand. Run `seikan check-data` on every feed and `seikan hash` on the thesis before every
`seikan run`.

### Keeping seikan current

Once a week, the maintainer compares seikan's newest commit with the one `uv.lock` pins:

```sh
git ls-remote https://github.com/yewcast97/seikan main      # the branch's newest commit
grep -A2 '^name = "seikan"' uv.lock                          # the pinned commit, after the '#'
```

When they differ, the maintainer runs `uv lock --upgrade-package seikan`, then the four
verification commands of the root [AGENTS.md](../AGENTS.md). When all pass, they commit
`uv.lock` alone (`seikan: <old commit> → <new commit>`); when any fails, they restore `uv.lock`
(`git checkout -- uv.lock`), commit nothing, and open an issue on seikan when the failure is
seikan's. A failing suite is fixed, never worked around. The bot plays no part: it runs the
pinned seikan and reports what seikan does wrong as an issue on
https://github.com/yewcast97/seikan/issues.

## Starting a hypothesis

1. Create `<name>/` with `<name>.json`, `procedure.md`, `script/` (`__init__.py` and
   `__main__.py`) and `data/`.
2. Read or copy the domain data the thesis needs; write the feeds with the script; run
   `seikan check-data` on each feed and `seikan hash` on the thesis, then `seikan run`.
3. Report back the cells as seikan states them, and keep `procedure.md` as the steps were run.
