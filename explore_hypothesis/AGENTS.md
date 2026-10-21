# Hypothesis exploration: conventions

This is where the bot tests hypotheses with [seikan](https://github.com/yewcast97/seikan), a
stateless forward-return event-study engine: it reads a thesis (JSON) and strict CSV feeds,
measures every parameter × horizon cell the thesis declares, writes the files the caller names
and selects no winner. seikan is a dependency pinned by `uv.lock` to one commit of its GitHub
`main` branch, the commit every `uv run --locked seikan` runs. The repository's principles and
the bot's part are in the root [AGENTS.md](../AGENTS.md). This file is bound to no domain, and
it is the only tracked file of this module.

## The bot's work here

Market state research discloses the state of the market, one aspect per domain, under each
domain's procedure: three domains by fixed scripts, which the bot only runs, and `posts` by
the bot's own hand under that domain's rules. Hypothesis exploration tests the user's
hypotheses (the root [AGENTS.md](../AGENTS.md), The bot, says who the user is) against that
picture or against data from any other source, and welcomes creativity: for each one, the
bot does the whole work on its own host, the thesis, its own script that gathers the data and
prepares seikan's feeds, the procedure it follows, the feeds, the seikan runs and the report
back. That work is the bot's product, like the data it yields in the domains: it binds only
the reruns of its own hypothesis, nothing tracked reads it, no domain or other hypothesis
depends on it, and it is never a rule of the repository, so a convention the bot needs
changed is asked for in an issue, never set aside in its `procedure.md`. This file's
conventions are the rules of that work and keep it readable: a later run, by this bot or
another, can read what was tested, from which data, and run it again. Nothing under
`explore_hypothesis/<name>/` is tracked: the root `.gitignore` ignores everything here but
this file. When a convention or seikan blocks the bot, it opens an issue (root
[AGENTS.md](../AGENTS.md), Feedback).

## Independence

A hypothesis's data are its own, independent of market state research's, and come from the
domains or from any other source.

- It reads a domain's `data/` and never changes it: `raw/` through the domain's own `script`
  package (its validation, selection and derivation, never a parser of the bot's), or the
  domain's `formatted/` tables; `posts`, which has no package, is read as the Markdown files
  its `AGENTS.md` defines, in each poster's folder. It may copy such files into its own
  `data/source/` and adapt them there, through its script.
- It reads any other source by whatever route the bot's host offers: an API (under a key the
  user sets in the repository-root `.env` as `{SOURCE}_API`), a public file, a platform the
  host is part of, a browser. What a read receives goes into its own `data/source/` as
  received and is never edited; a later read is written beside the earlier one. A source
  worth a domain of market state research is proposed in an issue (root
  [AGENTS.md](../AGENTS.md), Feedback).
- It writes only under its own folder, and no domain reads it: nothing a hypothesis does
  changes a domain's data, outputs or freshness.
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
        ├── source/            copies of domain files, reads of other sources
        ├── formatted/         the feeds, one folder per ticker
        └── reports/           what seikan writes
```

| Part | Convention |
| --- | --- |
| `<name>` | Lowercase ASCII letters, digits and underscores, a letter first: the folder's and the package's name. |
| `<name>.json` | The thesis in seikan's DSL. It names its series (targets, external feeds, the benchmark) and never locates them; `seikan hash` validates it and lists the data keys a run must bind. No script writes or edits it. |
| `procedure.md` | The steps in order, so that another run repeats them: the thesis in one sentence; the domain data it reads (domains, sections, tickers, dates) and the domain procedure that supplies them; each other source it reads, by which route and command or steps, and the `.env` variable of any key it needs; the files copied or read into `data/source/`; the script's commands and what each writes; `seikan check-data` on each feed; `seikan hash`; the `seikan run` command with every binding and output path; what to report back. It changes whenever the steps change. |
| `script/` | A package run from the repository root as `uv run --locked python -m explore_hypothesis.<name>.script …` (Conventions of a script). |
| `data/source/` | Files copied from a domain's `data/`, byte for byte, under the domain's own path (`stock_iv_regime/formatted/INTC/volatility.csv`): a copy is never edited, and a newer one replaces it only by being copied again. What a read of another source received, as received, under the source's name, each file named with the New York time of the read (`common.times.timestamp_token`), as in `fred/DGS10_<TOKEN>.json`: never edited, a later read written beside it. |
| `data/formatted/{TICKER}/{SOURCE}.csv` | One feed per ticker and source in seikan's strict contract, rewritten by the script. |
| `data/reports/` | seikan's outputs (`--report-out`, `--trades-out`, `--root-series-out`, `--entry-flags-out`), each name carrying a New York time token (`common.times.timestamp_token`) so that no report is overwritten. |

## Conventions of a script

The script is the bot's, and nothing tracked checks it: `seikan check-data` on every feed it
writes is the gate. These conventions make it readable and repeatable.

- Its `__main__.py` opens with a docstring stating the thesis in one sentence, the data it
  reads (domain, section, file names; for another source, what it is and its route) and
  every column it writes, with the formula of any value it derives.
- Another source is read by a command of its own, or by the bot's route where no script can
  read it, into `data/source/` only. The command that writes the feeds sends no request and
  is deterministic: the same inputs give the same bytes. No command reads a watchlist.
- The command that writes the feeds runs from the repository root with locked dependencies,
  takes its tickers on the command line (at least one), `--source-dir PATH` (where it reads)
  and `--data-dir PATH` (the hypothesis's `data/`), and prints JSON: one entry per ticker
  with the feed's path, its rows, its first and last dates, the sessions inside it without a
  row and the sessions whose value cells are empty.
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
  decimal notation: a domain's values exactly as it derives them, another source's exactly
  as received, or the script's own derivation of them, stated in its docstring. Nothing is
  invented, estimated or carried forward.
- A row's timestamp is when its values became available. seikan anchors a value on the first
  bar stamped at or after it and fills a bar where the entry condition holds at the next bar's
  open. A value as of a session's close is stamped with the session's date, the date of that
  session's daily price bar, so it is exactly as available as that bar's close.
- A value fetched after its session is what the provider serves at the time of the fetch.
  Whether it served the same at the session's close cannot be checked, and seikan leaves such
  vintages to the caller, so a report built on such feeds says so.
- Missing data stays explicit. Where the domain or the source gives no value, the cell is
  empty. A session the domain did not fetch, or the source does not cover, has no row, so
  seikan carries the previous row over it: the script reports how many such sessions lie
  inside each feed, and a thesis that reads the feed bounds the value's age with
  `days_since`.
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
`seikan run`. What seikan does wrong goes into an issue on
https://github.com/yewcast97/seikan/issues (root [AGENTS.md](../AGENTS.md), Feedback).

## Starting a hypothesis

1. Create `<name>/` with `<name>.json`, `procedure.md`, `script/` (`__init__.py` and
   `__main__.py`) and `data/`.
2. Read or copy the domain data the thesis needs, and read any other source into
   `data/source/`; write the feeds with the script; run `seikan check-data` on each feed and
   `seikan hash` on the thesis, then `seikan run`.
3. Report back the cells as seikan states them, and keep `procedure.md` as the steps were run.
