"""Command line for the fundamentals pipeline; see the domain's PROCEDURE.md.

For each season (a fiscal period, named by its end) in a window, the pipeline keeps the
season's documents in data/raw/ (its 10-K or 10-Q, its 8-Ks with their exhibits, its proxy
statement, the beneficial owners' schedules and the insiders' Form 4s, its earnings calls'
transcripts) and the company's XBRL facts; their derived text and each season's
mechanical comparison (measures.md) in data/formatted/; and the bot's readings of each
season and the season's report of what changed against its baselines in data/reports/.
fetch and plan take the window as --from and --to, New York calendar dates written
YYYY-MM-DD that bound the season ends (both included): --to defaults to today and must not
be after it, and --from defaults to the same day two years before --to and must not be after
--to; a refused window is one FUNDAMENTALS: line before any work. Only when the user asks,
fetch --refresh requests the window's documents, facts, transcripts and calls list again,
whatever raw/ holds, and rewrites nothing: an EDGAR document is compared with its stored
file, and a transcript whose bytes changed is written beside the stored one; plan --refresh
plans that fetch.

fetch is the one command that uses the network, under two settings (from the environment
or the ignored repository-root .env), which no other command reads and fetch never
prints: SEC_USER_AGENT (a name and an email address) for SEC EDGAR, and EARNINGSCALLS_API,
the user's own EarningsCalls.dev key, for the earnings calls' transcripts. Both are
checked before the watchlist is read or any request is sent. Without tickers, fetch, plan
and show read this domain's watchlist.json. The other commands work offline: they plan the
next step, derive the texts and measures, check the bot's readings, render the season
reports and show them. The clock is read in New York time, and every time printed is New
York time.
"""

import argparse
import json
import sys
from collections.abc import Callable, Sequence
from datetime import MINYEAR, date, datetime
from pathlib import Path

from market_state_research.common.cli import Parser, calendar_date, directory_path, fail, file_path
from market_state_research.common.env import setting
from market_state_research.common.layout import DataLayout
from market_state_research.common.times import NEW_YORK, to_eastern

from .client import EdgarClient, EdgarError
from .earningscalls import API_KEY_SETTING, EarningsCallsClient, EarningsCallsError
from .filings import Window, default_window
from .workflow import WATCHLIST, check, derive, fetch, plan, render, show

PROGRAM = "python -m market_state_research.fundamentals.script"
LABEL = "FUNDAMENTALS"
USER_AGENT_SETTING = "SEC_USER_AGENT"
CALLS_SETTING = API_KEY_SETTING
WINDOWED = ("fetch", "plan")  # the commands that take --from and --to
DOMAIN_DIRECTORY = Path(__file__).resolve().parent.parent
DATA_DIRECTORY = DOMAIN_DIRECTORY / "data"


class FundamentalsParser(Parser):
    """This domain's parser: every command-line error is one ``FUNDAMENTALS: ...`` line."""

    label = LABEL


def build_parser() -> argparse.ArgumentParser:
    parser = FundamentalsParser(prog=PROGRAM, description=__doc__)
    storage = FundamentalsParser(add_help=False)
    storage.add_argument(
        "--data-dir",
        type=directory_path,
        default=DATA_DIRECTORY,
        metavar="PATH",
        help="runtime data directory (default: this domain's data/)",
    )
    listed = FundamentalsParser(add_help=False, parents=[storage])
    listed.add_argument(
        "tickers", nargs="*", metavar="TICKER", help="default: the stock section of the watchlist"
    )
    listed.add_argument(
        "--watchlist",
        type=file_path,
        default=WATCHLIST,
        metavar="PATH",
        help="watchlist read when no ticker is given (default: this domain's watchlist.json)",
    )
    selection = FundamentalsParser(add_help=False, parents=[listed])
    selection.add_argument(
        "--refresh",
        action="store_true",
        help=(
            "request the window's EDGAR documents, company facts, transcripts and calls list again, "
            "whatever raw/ holds: an EDGAR document is compared with its stored file, never rewritten "
            "(verified or changed); a transcript whose bytes changed is written beside the stored one "
            "(refreshed)"
        ),
    )
    window = FundamentalsParser(add_help=False)
    window.add_argument(
        "--from",
        dest="window_from",
        type=calendar_date,
        metavar="YYYY-MM-DD",
        help="the earliest season end in the window, a New York calendar date "
        "(default: the same day two years before --to)",
    )
    window.add_argument(
        "--to",
        dest="window_to",
        type=calendar_date,
        metavar="YYYY-MM-DD",
        help="the latest season end in the window (default: today, New York date; never after it)",
    )
    commands = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    def command(name: str, parents: list[FundamentalsParser], summary: str) -> FundamentalsParser:
        """A command whose summary is its line in the program's help and the description of its own."""
        return commands.add_parser(name, parents=parents, help=summary, description=summary)

    command(
        "fetch",
        [selection, window],
        "write each ticker's EDGAR submissions and, for each season of the window and the four before it, "
        "the documents of its 10-K or 10-Q, 8-Ks, proxy statement, beneficial owners' schedules and Form 4s "
        "that are not in raw/ yet and its company facts, then its earnings calls list from EarningsCalls.dev "
        "when due and the transcripts of those seasons' calls (uses the network; needs SEC_USER_AGENT and "
        "EARNINGSCALLS_API)",
    )
    command(
        "plan",
        [selection, window],
        "list each season's documents, call, texts, measures, readings and report in the window and the next "
        "action (read-only)",
    )
    derive_command = command(
        "derive",
        [storage],
        "write the derived text of every document in raw/ and the measures.md of every season, each when it "
        "is missing or differs from its derivation",
    )
    derive_command.add_argument("ticker", metavar="TICKER")
    check_command = command(
        "check",
        [storage],
        "check the bot's readings of each season against the documents' derived text (writes nothing)",
    )
    check_command.add_argument("ticker", metavar="TICKER")
    check_command.add_argument(
        "readings",
        nargs="*",
        type=file_path,
        metavar="READINGS_PATH",
        help="default: every season's readings.md in reports/TICKER/; a draft lies in its season's folder",
    )
    render_command = command(
        "render",
        [storage],
        "write the report of every season whose readings pass and whose report is not current",
    )
    render_command.add_argument("ticker", metavar="TICKER")
    command(
        "show",
        [listed],
        "print each ticker's newest season report (read-only)",
    )
    return parser


def _window(window_from: date | None, window_to: date | None, today: date) -> Window:
    """The window ``--from`` and ``--to`` give, with their defaults, or ``ValueError``.

    ``--to`` defaults to ``today`` (New York) and must not be after it; ``--from`` defaults
    to the same day two years before ``--to`` and must not be after it.
    """
    end = today if window_to is None else window_to
    if end > today:
        raise ValueError(f"--to must not be after today ({today.isoformat()})")
    if window_from is None and end.year < MINYEAR + 2:  # no calendar date lies two years earlier
        raise ValueError("--to leaves no default --from two years before it; give --from")
    start = default_window(end).start if window_from is None else window_from
    if start > end:
        raise ValueError("--from must not be after --to")
    return Window(start, end)


def main(
    argv: Sequence[str] | None = None,
    now: datetime | None = None,
    client: EdgarClient | None = None,
    settings: Callable[[str], str | None] = setting,
    calls: EarningsCallsClient | None = None,
) -> int:
    args = build_parser().parse_args(argv)
    try:
        moment = to_eastern(now if now is not None else datetime.now(NEW_YORK), "now")
        # The window is checked before any work: no directory, setting, watchlist or request.
        window = (
            _window(args.window_from, args.window_to, moment.date()) if args.command in WINDOWED else None
        )
        data_dir = args.data_dir.absolute()
        if data_dir.exists() and not data_dir.is_dir():
            return fail(LABEL, f"{data_dir} is not a directory")
        layout = DataLayout(data_dir)
        if window is not None:  # fetch or plan
            if args.command == "fetch":
                # The settings are checked here, before the watchlist and the first request; their
                # values are never printed.
                edgar = client if client is not None else EdgarClient(settings(USER_AGENT_SETTING))
                provider = calls if calls is not None else EarningsCallsClient(settings(CALLS_SETTING))
                output = fetch(
                    layout,
                    args.tickers,
                    edgar,
                    provider,
                    window,
                    moment,
                    refresh=args.refresh,
                    watchlist=args.watchlist,
                )
            else:
                output = plan(
                    layout, args.tickers, moment, window, refresh=args.refresh, watchlist=args.watchlist
                )
        elif args.command == "derive":
            output = derive(layout, args.ticker, moment)
        elif args.command == "check":
            output = check(layout, args.ticker, moment, args.readings)
        elif args.command == "render":
            output = render(layout, args.ticker, moment)
        else:
            sys.stdout.write(show(layout, args.tickers, moment, watchlist=args.watchlist))
            return 0
    except (EdgarError, EarningsCallsError, ValueError, OSError, OverflowError) as error:
        return fail(LABEL, str(error))
    if args.command in WINDOWED:
        output["watchlist"] = None if args.tickers else str(args.watchlist)
    # ASCII-only JSON: values that came from file names, EDGAR or EarningsCalls.dev cannot carry
    # control or bidirectional characters to the terminal.
    print(json.dumps(output, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
