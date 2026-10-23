"""Command line for the market position regime pipeline; see the domain's PROCEDURE.md.

Three charts of the US equity market's positioning over a window of New York dates: FINRA's
monthly margin debt; the CFTC's weekly S&P 500 futures positions, as the percentiles over 52
weeks of asset managers' net long and leveraged funds' net short positions; and Cboe's daily
VIX and SKEW, each as a percentile over 252 XNYS sessions. Every command takes the window as
--from and --to, dates written YYYY-MM-DD (both included): --to defaults to today and must
not be after it, and --from defaults to the same day three years before --to and must not be
after --to; a refused window is one MARKET_POSITION_REGIME: line before any work.

fetch is the one command that uses the network. It reads FINRA's workbook, the CFTC's public
API and Cboe's VIX and SKEW histories, none of which needs a key, so no command reads a
setting. It
writes what is new to data/raw/market/. plan, record and show work offline: they plan the
next step, record the raw files into the three formatted tables and a report, and show the
window. The clock is read in New York time, and every time printed is New York time.
"""

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import MINYEAR, date, datetime

from market_state_research.common.cli import Parser, calendar_date, directory_path, fail
from market_state_research.common.layout import DataLayout
from market_state_research.common.times import NEW_YORK, to_eastern

from .client import Client, SourceError
from .store import DATA_DIRECTORY
from .workflow import DEFAULT_YEARS, Window, default_window, fetch, plan, record, show

PROGRAM = "python -m market_state_research.market_position_regime.script"
LABEL = "MARKET_POSITION_REGIME"


class MarketPositionRegimeParser(Parser):
    """This domain's parser: every command-line error is one ``MARKET_POSITION_REGIME: ...`` line."""

    label = LABEL


def build_parser() -> argparse.ArgumentParser:
    parser = MarketPositionRegimeParser(prog=PROGRAM, description=__doc__)
    common = MarketPositionRegimeParser(add_help=False)
    common.add_argument(
        "--data-dir",
        type=directory_path,
        default=DATA_DIRECTORY,
        metavar="PATH",
        help="runtime data directory (default: this domain's data/)",
    )
    common.add_argument(
        "--from",
        dest="window_from",
        type=calendar_date,
        metavar="YYYY-MM-DD",
        help=f"the window's first day, a New York date (default: the same day {DEFAULT_YEARS} years "
        "before --to)",
    )
    common.add_argument(
        "--to",
        dest="window_to",
        type=calendar_date,
        metavar="YYYY-MM-DD",
        help="the window's last day (default: today, New York date; never after it)",
    )
    refresh = MarketPositionRegimeParser(add_help=False)
    refresh.add_argument(
        "--refresh",
        action="store_true",
        help="request everything the window needs again, whatever raw/ holds (a newer answer that differs "
        "is written beside the stored one)",
    )
    commands = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    def command(name: str, parents: list[MarketPositionRegimeParser], summary: str) -> None:
        """A command whose summary is its line in the program's help and the description of its own."""
        commands.add_parser(name, parents=parents, help=summary, description=summary)

    command(
        "fetch",
        [common, refresh],
        "write what the window lacks from FINRA, the CFTC and Cboe to raw/market/ (uses the network)",
    )
    command(
        "plan",
        [common, refresh],
        "list what each source lacks, the tables, the report and the action (read-only)",
    )
    command("record", [common], "rewrite the three tables from raw/ and write a new report of the window")
    command("show", [common], "print one status line and the window as Markdown (read-only)")
    return parser


def _window(window_from: date | None, window_to: date | None, today: date) -> Window:
    """The window ``--from`` and ``--to`` give, with their defaults, or ``ValueError``."""
    end = today if window_to is None else window_to
    if end > today:
        raise ValueError(f"--to must not be after today ({today.isoformat()})")
    if window_from is None and end.year < MINYEAR + DEFAULT_YEARS:  # no date lies three years earlier
        raise ValueError(f"--to leaves no default --from {DEFAULT_YEARS} years before it; give --from")
    start = default_window(end).start if window_from is None else window_from
    if start > end:
        raise ValueError("--from must not be after --to")
    return Window(start, end)


def main(
    argv: Sequence[str] | None = None,
    now: datetime | None = None,
    client: Client | None = None,
) -> int:
    args = build_parser().parse_args(argv)
    try:
        moment = to_eastern(now if now is not None else datetime.now(NEW_YORK), "now")
        # The window is checked before any work: no directory or request.
        window = _window(args.window_from, args.window_to, moment.date())
        data_dir = args.data_dir.absolute()
        if data_dir.exists() and not data_dir.is_dir():
            return fail(LABEL, f"{data_dir} is not a directory")
        layout = DataLayout(data_dir)
        if args.command == "fetch":
            output = fetch(
                layout, window, moment, client if client is not None else Client(), refresh=args.refresh
            )
        elif args.command == "plan":
            output = plan(layout, window, moment, refresh=args.refresh)
        elif args.command == "record":
            output = record(layout, window, moment)
        else:
            sys.stdout.write(show(layout, window, moment))
            return 0
    except (SourceError, ValueError, OSError, OverflowError) as error:
        return fail(LABEL, str(error))
    # ASCII-only JSON: values that came from file names or the sources cannot carry control or
    # bidirectional characters to the terminal.
    print(json.dumps(output, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
