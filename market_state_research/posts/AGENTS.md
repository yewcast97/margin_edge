# Posts

This domain keeps, per poster the user nominates, every post of the intervals a human asks
about, archived verbatim per account whether or not it answers the question; fact-checks each
post claim by claim against cited evidence, as `true`, `unverified` or `fake`; answers each
request with a report of the posts that relate to it; and keeps a profile of each poster: who
they are, their accounts and the count of verdicts so far. Its watchlist lists posters, not
tickers. This file says first what the work aims at; then the posters, their accounts and the
routes they are read by, the intervals and their coverage, the raw file, the rules of claims,
evidence and verdicts, the fact-check file, the profile, the reports and the runtime files. The
operations the bot carries out (the settings, set-up and the daily task, a request, the daily
re-check, the report back, failures) are in the sibling [PROCEDURE.md](PROCEDURE.md); the
conventions every domain shares (the domain layout, the three sections of `data/`, New York
time) are in [market_state_research/AGENTS.md](../AGENTS.md).

Three things set this domain apart from the scripted ones. It has no `script/`: the bot writes
every file by hand under this file's grammars, and no Python reads, writes or checks one. It
nominates no source: the bot reads each account by whatever route its host offers. And it reads
no market data, so it has no session logic: a post is dated by its platform's timestamp,
converted to New York time.

## Aim

For each nominated poster, a record of what they said in public, kept whole and verbatim over
every interval a human asked about, so that the archive answers later questions too; a
fact-check of every post that settles each checkable claim against cited evidence, primary
sources first, and keeps every claim not settled yet open, with what would settle it; a profile
that says who the poster is and counts the verdicts so far; and, per request, a report that
hands over what the poster said about the subject asked, verbatim, with its verdicts. The bot
chooses only which posts relate to a request and what the evidence it cites shows; no score,
grade, ranking, sentiment, prediction or advice is added.

## Posters, accounts and routes

- **The watchlist.** `watchlist.json`, beside this file, is the user's own and ignored by Git:
  only the user edits it, the bot reads it, and no Python does (the ticker watchlists, the
  repository-root one included, play no part here). It names each poster once, under a name the
  user chooses, with their accounts, each under a label naming its platform and given by the
  URL of its profile:

  ```json
  {
    "posters": {
      "some_analyst": {"accounts": {"x": "https://x.com/some_analyst"}},
      "some_fund": {
        "accounts": {"x": "https://x.com/some_fund", "threads": "https://www.threads.net/@some_fund"}
      }
    }
  }
  ```

  A poster's name and an account's label are lowercase ASCII letters, digits and underscores, a
  letter first: the name is the poster's folder, and the label begins the name of every file of
  that account (`x`, `x_2` for a second account on X, `threads`). A poster's accounts are one
  person's or one body's: a claim repeated on two of them is checked once (the second entry may
  copy the first's evidence), and the profile counts the verdicts across all of them.
- **A poster's folder.** `<poster>/` holds `profile.md` and `data/`, in the three sections
  `raw/`, `formatted/` and `reports/`. It is the bot's, written on its host and ignored by Git
  whole. A poster is set up (PROCEDURE.md, section 3) before their first request; one the user
  removes from the watchlist keeps their folder as it is.
- **Routes.** The bot reads each account by one of three routes, whichever its host offers, and
  names it, in one of these forms, in the profile and in every raw file:
  - `integration, NAME`: the host's own integration with the platform, named as the host names
    it (Grok's with X, say);
  - `api, {PLATFORM}_API`: the platform's API under the user's own key, kept in the ignored
    repository-root `.env` as `{PLATFORM}_API` (`X_API`), read for that platform alone, named by
    its variable and never printed or written;
  - `browser`: a browser on the host.

  A route must show each post's absolute time, since a relative time ("3h") places no post in an
  interval: a route that cannot is not used. An account shown only to approved followers is read
  only through a route the user set up for it; the bot never asks for a key or a password in the
  conversation. An account that no route on the host can read is reported, and the poster's
  other accounts go on; `private` and `gone` (deleted or suspended) are statuses the profile
  dates, not failures.

## Intervals and coverage

- An interval is a pair of New York instants, the start included and the end excluded, the end
  never after the time of the read. "Yesterday" is the previous New York calendar day, from
  00:00 to 00:00 (PROCEDURE.md, section 1, reads the other ways a request names one).
- A raw file covers its account over the interval its name gives, whatever it holds: an
  interval without posts is covered by a file that says so. An account's coverage is the union
  of the intervals of its raw files, those renamed `.rejected` left out, and nothing else
  records it. A request reads, per account, only the parts of its interval that are not
  covered, one raw file per part; a covered part is read again only when a human asks for it
  (below).
- A read cut short (a rate limit, a timeline that stops loading) writes the part it read whole,
  named by that part's bounds, and its header gives the interval asked for: the rest stays
  uncovered for a later read. A raw file never names a part it did not read whole.
- `coverage: complete` says the route showed every post and reply the account published over
  the interval. `coverage: partial: REASON` says it could not, and why (a search that may miss
  posts, replies the platform hides); a partial file covers its interval like a complete one.
  When a human asks for a covered interval to be read again, the bot writes a supplement: a raw
  file over the interval asked for, holding only the posts the stored files over it lack (or
  `No new posts.`), its header naming those files.

## The raw file

`data/raw/{LABEL}_{START}_{END}_{TOKEN}.md` holds every post one account published in one
interval, verbatim, as the route showed it at the read: `{LABEL}` is the account's label,
`{START}` and `{END}` are the interval's bounds and `{TOKEN}` is the time the read finished,
each a New York time token (`x_20261019T000000EDT_20261020T000000EDT_20261020T091500EDT.md`).
A UTF-8 Markdown file:

```markdown
# some_analyst / x: posts from 2026-10-19 00:00:00 EDT to 2026-10-20 00:00:00 EDT

- poster: some_analyst
- account: x, https://x.com/some_analyst
- route: integration, Grok's X integration
- read_at: 2026-10-20T09:15:00-04:00
- interval: 2026-10-19T00:00:00-04:00 to 2026-10-20T00:00:00-04:00
- coverage: complete
- count: 2 (post 1, reply 0, repost 0, quote 1)

## 1 — https://x.com/some_analyst/status/1001

- platform_time: 2026-10-19T14:03:11.000Z
- new_york_time: 2026-10-19T10:03:11-04:00
- kind: post
- media: none

> ExampleCo raised its wafer prices 10% this month.
> ExampleCo ships its 2 nm part in volume by the fourth quarter.

## 2 — https://x.com/some_analyst/status/1002

- platform_time: 2026-10-19T20:41:05.000Z
- new_york_time: 2026-10-19T16:41:05-04:00
- kind: quote of https://x.com/other_desk/status/999
- media: none

> This matches what I hear from suppliers.

### quoted — https://x.com/other_desk/status/999

- author: Other Desk, https://x.com/other_desk
- platform_time: 2026-10-19T18:00:00.000Z
- new_york_time: 2026-10-19T14:00:00-04:00
- media: https://example.com/media/999.jpg (image), alt: none

> Substrate lead times are back above 30 weeks.
```

The header lines, in this order: `poster`; `account`, its label and URL; `route` (Routes);
`read_at`, the instant `{TOKEN}` names; `interval`, the bounds the name gives;
`asked: START to END, REASON`, only in a file that stops short of the interval the request
asked for; `supplements: FILE, …`, only in a supplement; `coverage` (Intervals and coverage);
and `count: N (post P, reply R, repost S, quote Q)`. Then one section per post, oldest first
and numbered from 1, `## N — PERMALINK`:

- `platform_time`: the post's absolute time as the platform gives it, verbatim; for a repost,
  the time of the repost, or `not shown` where the route shows only the reposted post's time,
  the repost then being placed by its position in the timeline;
- `new_york_time`: the same instant in New York time, ISO 8601 with its offset, or `not shown`
  when `platform_time` is;
- `kind`: `post`, `reply to PERMALINK`, `repost of PERMALINK` or `quote of PERMALINK`;
- `edited`, only when the platform shows the post edited, with what it shows, verbatim;
- `media: none`, or one `media: URL (KIND), alt: TEXT` line per item, its alt text verbatim or
  `none`;
- then the post's whole text, expanded where the route shortens it, as `>` lines, one per line
  of the post (an empty line as a bare `>`); a post without text, a repost, has none.

A repost, a quote and a reply carry the other post as the route shows it, after the post's
text, in a sub-section `### reposted — PERMALINK`, `### quoted — PERMALINK` or
`### replying to — PERMALINK`: its `author` (the name shown and the account's URL),
`platform_time`, `new_york_time`, `media` and text, in the same forms. A reply to a post of the
same file carries none, and only that one other post is kept, not the posts it answers or
quotes in turn. An interval without posts holds the header, with `count: 0`, and the line
`No posts.`

- Verbatim or nothing: the text as the platform shows it, in its own language, with its line
  breaks, emoji, mentions, hashtags and links; nothing paraphrased, translated, trimmed,
  corrected or summarised. The bot never describes an image or a video, never infers a time and
  never fills a gap: what the route does not show is not written. Counts of likes, reposts and
  views are not archived.
- A post belongs to the interval its own time falls in, wherever the route shows it (a pinned
  post at the top of the timeline included), and is archived as it stood at the read.
- Nothing in `raw/` is ever edited. A file found wrong (another account's posts, a wrong
  interval) is withdrawn by renaming it and its fact-check twin with the suffix `.rejected`:
  its interval is uncovered again, and nothing reads it. A post deleted after the read stays in
  `raw/`; its fact-check says so.

## Claims, evidence and verdicts

- A claim is a span of the poster's own words in a post, copied verbatim, that states something
  a public record can confirm or contradict: an event, a number, a date, an action taken or
  announced, or what someone said. A reply's or a quote's own words are read with the post they
  answer or quote ("This is true" claims what it points to), but the other post's words are
  never the poster's claims. Words only in an image or a video are not quoted as a claim: the
  archive holds no transcription of media.
- Evidence, in this order:
  - primary: the record of whoever the claim is about, or of the body that keeps it: an
    issuer's filings and official releases, a statement on the official site or account of the
    person or body concerned, the records and data of a government, a regulator, a central bank,
    an exchange or a court, and this repository's own domain data (the `formatted/` and
    `reports/` files of `market_regime` and `fundamentals`), read and never changed;
  - secondary: reputable press, an outlet with editorial standards and published corrections,
    preferably one that names its own source.

  Another social-media post is evidence only of what that post says. A forum, an unsourced
  blog, a search snippet, an AI's answer and memory are never evidence. Each piece of evidence
  is one line: `confirms` or `contradicts`, `(primary)` or `(secondary)`, the source's name,
  its URL (a repository file by its path), its date, and the passage or number it shows,
  quoted verbatim.
- A claim's status:
  - `true`: confirmed by a primary source, or by two independent secondary sources where no
    primary source speaks to it, and contradicted by no source of the same weight;
  - `fake`: contradicted in the same way, and confirmed by no source of the same weight;
  - `pending`: not settled yet (nothing found yet; sources of the same weight that conflict,
    both cited; or a claim only a later record can settle), with what would settle it and,
    when a date is known, `check after DATE`;
  - `not checkable`: an opinion, a joke, a question, a prediction that names no date, or a
    claim no public record can reach (what the poster says they did in private, say).
- A post's verdict:
  - `fake` when any of its claims is `fake`;
  - `true` when none is `fake` or `pending` and at least one is `true`;
  - `unverified (pending)` when none is `fake` and at least one is `pending`;
  - `unverified (no checkable claim)` when it has none, or every one is `not checkable`.

  A bare repost says nothing in the poster's own words: its verdict is
  `unverified (no checkable claim: repost)`, and it is not checked.
- A claim in another language is quoted in its own; its fact-check may give the bot's
  translation beside it, marked `translation (the bot's):`, never in `raw/`.

## The fact-check file

`data/formatted/{LABEL}_{START}_{END}_{TOKEN}.md` is the fact-check of the raw file of the same
name, one entry per post in the raw file's order and numbering:

```markdown
# x_20261019T000000EDT_20261020T000000EDT_20261020T091500EDT

- raw: ../raw/x_20261019T000000EDT_20261020T000000EDT_20261020T091500EDT.md
- poster: some_analyst
- last_check: 2026-10-21T06:02:00-04:00

## 1 — https://x.com/some_analyst/status/1001

- verdict: fake
- claims:
  1. > ExampleCo raised its wafer prices 10% this month.
     - status: fake
     - evidence:
       - contradicts (primary): ExampleCo, Form 8-K, Exhibit 99.1, https://www.example.com/ir/8-k-2026-10-16.htm, 2026-10-16: "PASSAGE"
  2. > ExampleCo ships its 2 nm part in volume by the fourth quarter.
     - status: pending, check after 2027-01-31: ExampleCo's fourth-quarter results
     - evidence: none yet
- checks:
  - 2026-10-20T09:40:11-04:00: unverified (pending); claim 1 pending (nothing found yet), claim 2 pending (check after 2027-01-31)
  - 2026-10-21T06:02:00-04:00: fake; claim 1 fake (ExampleCo's 8-K of 2026-10-16), claim 2 pending (check after 2027-01-31)

## 2 — https://x.com/some_analyst/status/1002

- verdict: unverified (pending)
- claims:
  1. > This matches what I hear from suppliers.
     - status: pending: an issuer's or a supplier's own statement of its substrate lead times
     - evidence: none yet
- checks:
  - 2026-10-20T09:40:11-04:00: unverified (pending); claim 1 pending (nothing found yet)
  - 2026-10-21T06:02:00-04:00: unverified (pending); claim 1 pending (nothing found yet)
```

- The header gives the raw twin's path, the poster and `last_check`, the time of the file's
  latest check. Each entry, `## N — PERMALINK` as in the raw file, holds `verdict`; `claims`,
  each claim's verbatim span as `>` lines with its `status` (`true`, `fake`,
  `pending: WHAT WOULD SETTLE IT`, `pending, check after DATE: WHAT WOULD SETTLE IT` or
  `not checkable: WHY`), its `evidence` (`none yet`, or one line per piece) and any
  translation; and `checks`, one line per check of the post: its time, the verdict and each
  claim's status with what decided it. A post without a claim holds `verdict` and `checks`
  alone.
- It is written with its raw file, in the same request, every post checked. After that,
  `last_check`, each `verdict` and each claim's `status` are rewritten in place when a check
  changes them; evidence and `checks` lines are only appended, never changed or removed, so
  every earlier verdict and its grounds stay readable, and a correction is a new line. A post
  found deleted gains `- deleted: seen gone on DATE (route: ROUTE)`, and its verdict stands.
- It holds no counts: the profile does. Resting on the evidence found at each check as well as
  on `raw/`, it cannot be rebuilt, so it is kept like `raw/`: never deleted, and withdrawn only
  with its raw twin.

## The profile

`profile.md` says who the poster is and what their archived posts came to:

```markdown
# some_analyst

## Accounts

| Label | Account | Platform | Route | Status | First read |
| --- | --- | --- | --- | --- | --- |
| x | https://x.com/some_analyst | X | integration, Grok's X integration | public, as of 2026-10-20 | 2026-10-20 |

## Background

- Semiconductor equity analyst at Example Securities, by the account's bio (https://x.com/some_analyst, read 2026-10-20).

## Credibility

As of 2026-10-21T06:02:00-04:00, from 1 fact-check file, over intervals from 2026-10-19 00:00:00 EDT to 2026-10-20 00:00:00 EDT.

| Posts | Count |
| --- | --- |
| true | 0 |
| fake | 1 |
| unverified (pending) | 1 |
| unverified (no checkable claim) | 0 |
| unverified (no checkable claim: repost) | 0 |
| all | 2 |

| Claims | Count |
| --- | --- |
| true | 0 |
| fake | 1 |
| pending | 2 |
| not checkable | 0 |
| all | 3 |

Settled posts found true: true ÷ (true + fake) = 0 ÷ 1 = 0.00.

## Notes

- 2026-10-20: set up; the daily re-check is scheduled at 06:00 New York time on the bot's host.
- 2026-10-21: https://x.com/some_analyst/status/1001 went from unverified (pending) to fake: ExampleCo's 8-K of 2026-10-16.
```

- `## Accounts`: one row per account of the watchlist: its label, URL and platform, its route
  (Routes), its status (`public`, `private` or `gone`) with the date it was last seen so, and
  the date it was first read (`not yet` until then).
- `## Background`: who the poster is, their roles and affiliations, what they post about, and
  any interest that bears on what they say (an employer, holdings they disclose), each line
  with its source's URL and the date it was read, the account's own bio and links first.
  Nothing from memory, and nothing beyond the poster's public role: no private detail, such as
  a home or a family.
- `## Credibility`: rewritten whole at every recount, from every fact-check file of the poster
  (`.rejected` ones left out), never adjusted from the one before: a line with the as-of time,
  the number of fact-check files and the earliest start and latest end of their intervals; the
  posts by verdict and the claims by status, each with its total; and the share of settled
  posts found true, `true ÷ (true + fake)`, with its two counts, to two decimals, or
  `none settled yet` while no post is `true` or `fake`. A deleted post still counts: the poster
  said it. The counts cover only the intervals humans asked about, and they are not a rating.
- `## Notes`: dated lines, only ever appended: the set-up and the daily task's hour; an
  account's change of status or route; each verdict that changed, with its permalink, from what
  to what and the source; each run that failed. A correction is a new line.

The profile is written at set-up. Accounts and Credibility are rewritten in place, Background
grows, and Notes only grows. Evidence lives in `formatted/`, never only here.

## Reports

`data/reports/{SLUG}_{TOKEN}.md` answers one request about the poster: `{SLUG}` names the
request's subject in at most 40 lowercase ASCII letters, digits and underscores
(`semiconductor_supply_chain`), and `{TOKEN}` is the time it was written. A request about
several posters writes one report in each poster's folder, all under one name. A report is
never rewritten: a verdict that changes later changes in `formatted/` alone, and a later
request writes a new report.

A post relates to a request when it speaks to the subject, in its text, its media or the post
it reposts, quotes or answers; when in doubt, it is included. The report draws on every post of
the interval, from the raw files read for the request and from those already archived:

```markdown
# some_analyst: the semiconductor supply chain

- request: "Did some_analyst say anything about the semiconductor supply chain yesterday?" (asked 2026-10-20T09:12:00-04:00)
- interval: 2026-10-19T00:00:00-04:00 to 2026-10-20T00:00:00-04:00 ("yesterday")
- files: x_20261019T000000EDT_20261020T000000EDT_20261020T091500EDT.md (read now, complete)
- related: 2 of 2 posts
- profile: ../../profile.md; at writing, posts true 0, fake 0, unverified (pending) 2, unverified (no checkable claim) 0
- written: 2026-10-20T09:45:00-04:00

## 1 — https://x.com/some_analyst/status/1001

- account: x
- platform_time: 2026-10-19T14:03:11.000Z
- new_york_time: 2026-10-19T10:03:11-04:00
- verdict: unverified (pending), checked 2026-10-20T09:40:11-04:00 (../formatted/x_20261019T000000EDT_20261020T000000EDT_20261020T091500EDT.md, post 1)
- evidence: claim 1, nothing found yet; claim 2, check after 2027-01-31 (ExampleCo's fourth-quarter results)

> ExampleCo raised its wafer prices 10% this month.
> ExampleCo ships its 2 nm part in volume by the fourth quarter.

## 2 — https://x.com/some_analyst/status/1002

- account: x
- platform_time: 2026-10-19T20:41:05.000Z
- new_york_time: 2026-10-19T16:41:05-04:00
- verdict: unverified (pending), checked 2026-10-20T09:40:11-04:00 (../formatted/x_20261019T000000EDT_20261020T000000EDT_20261020T091500EDT.md, post 2)
- evidence: claim 1, nothing found yet

> This matches what I hear from suppliers.

Quoting Other Desk (https://x.com/other_desk/status/999):

> Substrate lead times are back above 30 weeks.

## Not related

None.

## Caveats

None.
```

The head lines: `request`, the request verbatim, with the time it was asked; `interval`, the
interval used, with the words of the request it was read from; `files`, each raw file drawn on,
`read now` or `already archived`, with its coverage, and every part of the interval left
uncovered, with why; `related: N of M posts`; `profile`, the poster's posts by verdict at
writing; `written`. Then each related post, oldest first across the accounts: its account, its
two times, its verdict as its fact-check gives it at writing, with that check's time and the
entry it comes from, a one-line summary of its evidence, and its text verbatim, a reposted,
quoted or replied-to post following as the line `Reposting`, `Quoting` or `Replying to`, then
`AUTHOR (PERMALINK):`, and its text. Then `## Not related`, every other post of the interval by
permalink, account and New York time, so that the selection can be checked, or `None.`; and
`## Caveats`: partial files, parts left uncovered, accounts private or gone, deleted posts and
media the verdicts do not cover, or `None.` Nothing is summarised beyond the verdicts and their
evidence.

## What is never added

No score, grade, label, ranking, sentiment, prediction or advice; no observation the route did
not show; no verdict without its cited evidence; nothing from memory; nothing about a poster
beyond their public role. A post's wording is never corrected, and every post of an interval
asked for is archived, whatever it says.

## Runtime files

All paths are relative to this domain and ignored by Git through the root `.gitignore`, which
tracks only this file and [PROCEDURE.md](PROCEDURE.md) here: a fresh checkout has no poster's
folder, and no `data/.gitignore` is needed.

| Path | Writer | Content |
| --- | --- | --- |
| `watchlist.json` | the user | The posters and their accounts (Posters, accounts and routes). |
| `<poster>/profile.md` | the bot | The profile (The profile). |
| `<poster>/data/raw/{LABEL}_{START}_{END}_{TOKEN}.md` | the bot | Every post of one account over one interval, verbatim (The raw file); written once, never edited. |
| `<poster>/data/formatted/{LABEL}_{START}_{END}_{TOKEN}.md` | the bot | The fact-check of its raw twin (The fact-check file), kept current in place with its dated history. |
| `<poster>/data/reports/{SLUG}_{TOKEN}.md` | the bot | The answer to one request (Reports); never rewritten. |

`{START}`, `{END}` and `{TOKEN}` are New York times to the second with their zone, as
`common.times.timestamp_token` writes them (`20261020T091500EDT`): the zone is the one in force
at that instant, and names are ordered by the instants their tokens name, never as text
(market_state_research/AGENTS.md, Data layout). No test covers this domain beyond the
repository-wide guard, which fails the test run if a test changes a poster's folder.
