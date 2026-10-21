# Posts: what nominated posters say, archived, fact-checked and reported

This procedure collects, for the posters of the watchlist, every post of the intervals a human
asks about; fact-checks every post; answers each request with a report; keeps each poster's
profile; and checks again, once a day, every claim still pending. The posters and routes, the
intervals and their coverage, every file's grammar, the rules of claims, evidence and verdicts,
the profile and the reports are in [AGENTS.md](AGENTS.md).

No script does this work: you read each account by a route your host offers and write every
file yourself, under `market_state_research/posts/`, with your file tools or the shell. A
request is section 4. Before your first request, and whenever a poster has no folder or the
daily task is missing from your host, set up first (section 3); the daily task runs section 5.

## 1. The watchlist, routes and a request's parameters

**The watchlist.** Read `market_state_research/posts/watchlist.json` at the start of every
routine (AGENTS.md, Posters, accounts and routes). You maintain it: add or remove a poster or an
account when the user asks or your judgment calls for it, write the file when it is missing and
correct it when it is malformed, and report every change. When a request names a poster it does
not list, add them with the accounts the user gives, or ask for them, and set them up (section
3) before the request.

**Routes and keys.** Read each account by a route your host offers: your own integration with
the platform, the platform's API under the user's key, or a browser on your host (AGENTS.md,
Routes); where you have a choice, take the one that shows every post and reply with its
absolute time. A platform's key is a line of the repository-root `.env`, `{PLATFORM}_API="..."`
(`X_API="..."`), which you read for that platform alone. Never print, repeat or write its value;
name it by its variable. When a route needs a key or a sign-in that is not there, ask the user
to set it up on the host themselves; never ask for a key or a password in the conversation, and
never open an account.

**A request's parameters.**

| Parameter | Default | Meaning |
| --- | --- | --- |
| Posters | every poster of the watchlist | The posters the request names, by their watchlist name or by a name or handle that matches exactly one account; ask when it matches none or several. |
| Interval | none: ask | A pair of New York instants, the start included, the end excluded, cut at the time of the read. "Yesterday" is the previous New York calendar day, 00:00 to 00:00; "today" runs from today's 00:00 to the read; a date is that day; "from D1 to D2" runs from D1 00:00 to the day after D2, 00:00; "the past N hours" or "days" end at the read; "last week" is the seven days ending today at 00:00; "so far" or "in the archive" is every interval already archived, and nothing is read. Any other wording: take its plainest reading and state it. |
| Subject | none | What the request asks about, kept verbatim for its report. A request without a subject, to archive an interval, writes no report. |

## 2. Rules every routine keeps

- Verbatim or nothing (AGENTS.md, The raw file): write what the route shows, never what you
  infer; what it does not show is not written.
- Cite everything: every piece of evidence and every line of a profile's Background names its
  source, its URL and its date. Nothing comes from memory.
- Primary sources first (AGENTS.md, Claims, evidence and verdicts). The repository's own domain
  data counts as primary: read the `formatted/` and `reports/` files of `stock_iv_regime` and
  `fundamentals`, and never write there.
- Keep every file: never delete one, never edit a raw file and never rewrite a report; change a
  fact-check or a profile only where AGENTS.md says it is rewritten in place, and otherwise
  append. Withdraw a wrong raw file only by renaming it and its fact-check twin with
  `.rejected`.
- New York time everywhere: instants as ISO 8601 with their offset
  (`2026-10-20T09:15:00-04:00`), headings for people with the zone
  (`2026-10-20 09:15:00 EDT`), name tokens as `20261020T091500EDT`, each with the zone in force
  at that instant (on the fall-back day 01:30 occurs twice, first `EDT`, then `EST`); keep the
  platform's own timestamp verbatim beside it.
- One routine per poster at a time: the daily re-check and a request never work on one
  poster's files together.
- What blocks you, or looks wrong in a rule, goes into a GitHub issue (the root
  [AGENTS.md](../../AGENTS.md), Feedback), never into the rule.

## 3. Set up

This adds what is missing and changes nothing else.

1. For each poster of the watchlist without a folder, create `<poster>/data/raw/`,
   `<poster>/data/formatted/` and `<poster>/data/reports/` under `market_state_research/posts/`.
2. Open each account its profile does not list yet by the account's route, and read its
   profile page only: its name, bio and links, the date it joined, and whether it is public.
   Nothing is archived at set-up.
3. Write `profile.md` (AGENTS.md, The profile), or add the new accounts' rows to its Accounts
   table: each account's route and status; Background from the profile pages and the sources
   they link to, each line cited; Credibility with zero counts and its as-of time; a Notes line
   saying what was set up.
4. When your host has no daily task for this domain yet, create a recurring task that, every
   day at 06:00 New York time (or at the hour and cadence the user names), opens this checkout,
   reads this file and runs section 5, and append a Notes line naming its hour to each profile.
   At the start of every later routine, check that the task still exists, and create it again
   when it does not, with a Notes line. When your host cannot schedule a task, say so in the
   report back and open an issue; until it can, run section 5 at the start of every request.
5. Report back (section 6).

## 4. A request

1. Read the request into posters, interval and subject (section 1), and state them in your
   reply.
2. For each poster and account, find from the names in `raw/` the parts of the interval that no
   raw file covers (AGENTS.md, Intervals and coverage). A covered part is not read again unless
   the request asks for it; then write a supplement.
3. Read each uncovered part by the account's route and write its raw file once the read is
   done, a part without posts included (AGENTS.md, The raw file).
4. Write each new raw file's fact-check in `formatted/`, under the same name: every claim of
   every post, checked against evidence you cite, every post's verdict and its first `checks`
   line (AGENTS.md, Claims, evidence and verdicts; The fact-check file).
5. Recount the Credibility of each profile whose fact-checks you wrote (AGENTS.md, The
   profile).
6. When the request has a subject, read every post of the interval, from the raw files read now
   and those already archived, select the posts that relate to it, and write the report in each
   poster's folder, all under one name (AGENTS.md, Reports).
7. Report back (section 6). State no verdict that is not in a fact-check file, and no post that
   is not in `raw/`.

## 5. The daily re-check

Read nothing new into `raw/`. For each poster of the watchlist:

1. In each fact-check file, for each post `unverified (pending)`, check again every `pending`
   claim whose `check after` date has passed or that has none: look for evidence again, primary
   sources first, and append what you find.
2. Rewrite each claim's status and the post's verdict where the evidence now settles them,
   append one `checks` line to each post you checked, changed or not, and rewrite the file's
   `last_check`. A post you find gone gains its `deleted` line.
3. Recount the profile's Credibility, and append a Notes line for each verdict that changed and
   for each check that failed.
4. Report back (section 6), as your host delivers a scheduled task's result.

## 6. Report back

- After set-up: the folders and profiles written, each account's route and status, and the
  daily task's hour, or that the host cannot schedule it, with the issue's link.
- After a request: the posters, the interval and the subject as you read them; per account the
  raw files read now, or `already archived`, with their coverage, and every part left uncovered,
  with why; each report as a link, with `related: N of M posts`; the related posts' verdicts by
  count, the pending claims with their check-after dates, and every caveat of the report.
- After the daily re-check: per poster, the posts checked, each changed verdict with its
  permalink and the source that settled it, the new counts, and every failure.

Point to the report or the fact-check rather than restating the posts; invent nothing; name a
key, never its value.

## 7. Failure handling

| Situation | Action |
| --- | --- |
| A route fails, or the platform is unavailable | Try once more later the same day. Write no raw file for a part not read whole: it stays uncovered. Report it. |
| An account is private, with no route the user set up for it, or gone | Date its status in the Accounts table, append a Notes line, collect nothing for it and report it; the poster's other accounts go on. |
| A rate limit stops a read partway | Write the raw file of the part read whole, with its `asked` line, and report the rest as uncovered. |
| The route cannot show every post of the interval | Write the raw file with `coverage: partial: REASON`, and report it. |
| A route shows no absolute time for a post | Use another route; when none shows it, leave the interval uncovered and report it. |
| Sources of the same weight conflict | Keep the claim `pending`, cite both, and never choose between them. |
| A claim's words are only in an image or a video | They are not a claim (AGENTS.md, Claims, evidence and verdicts): name the post in the report's caveats when it relates to the request. |
| A post is in another language | Copy it verbatim; a translation goes only into the fact-check, beside the claim, marked as yours. |
| A raw file is found wrong (another account's posts, a wrong interval) | Rename it and its fact-check twin with `.rejected`, append a Notes line, recount the Credibility, and read the interval again. |
| A request's interval ends after now | Cut it at the time of the read, and say so. |
| A report's name already exists | Take a new token. |
| A name you wrote carries a token in the wrong zone | Rename the file before anything reads it: no validator will catch it. |
| The host cannot schedule the daily task | Section 3, step 4. |
