"""Command line for the stock IV regime pipeline; see the domain's PROCEDURE.md.

Per ticker and XNYS session, from EODHD's end-of-day option chains and Tiingo's daily
prices: the 14-DTE 25-delta skew (put IV minus call IV), the 14-DTE ATM IV and the term
structure (the 30-DTE ATM IV minus the 14-DTE), with each one's percentile over the 252
sessions ending at it, and the 15-session correlations of the stock's daily return with the
changes of the 14-DTE 25-delta call and put IVs. fetch is the
one command that uses the network: it reads Tiingo's daily prices under TIINGO_API and
EODHD's options API under EODHD_API (from the environment or the ignored repository-root
.env), both checked before it reads the watchlist or sends any request and never printed,
and writes each ticker's prices and each session's chain to data/raw/. plan, record and
show work offline: they plan the next step, record the raw files into the formatted CSV and
a report and show the window. Without tickers, fetch and plan read this domain's
watchlist.json. While fetch runs, SIGTERM (a host ending a command that ran too long) is
turned into the KeyboardInterrupt of Ctrl-C, so a run interrupted while it fetches chains
stops cleanly and prints what it did; any other interrupted command fails with one line. The
clock is read in New York time, and every time printed is New York time.
"""

import argparse
import json
import signal
import sys
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from datetime import datetime
from types import FrameType
from typing import NoReturn

from market_state_research.common.cli import Parser, directory_path, fail, file_path, positive_integer
from market_state_research.common.env import setting
from market_state_research.common.layout import DataLayout
from market_state_research.common.times import NEW_YORK, to_eastern

from .client import API_KEY_SETTING, EodhdClient, EodhdError
from .store import DATA_DIRECTORY
from .tiingo import API_KEY_SETTING as TIINGO_KEY_SETTING
from .tiingo import TiingoClient, TiingoError
from .workflow import DEFAULT_BUDGET, DEFAULT_LOOKBACK, WATCHLIST, fetch, plan, record, show

PROGRAM = "python -m market_state_research.stock_iv_regime.script"
LABEL = "STOCK_IV_REGIME"
COMMAND_INTERRUPTED = "the command was interrupted; run plan to see what is stored"


class StockIvRegimeParser(Parser):
    """This domain's parser: every command-line error is one ``STOCK_IV_REGIME: ...`` line."""

    label = LABEL


def build_parser() -> argparse.ArgumentParser:
    parser = StockIvRegimeParser(prog=PROGRAM, description=__doc__)
    data = StockIvRegimeParser(add_help=False)
    data.add_argument(
        "--data-dir",
        type=directory_path,
        default=DATA_DIRECTORY,
        metavar="PATH",
        help="runtime data directory (default: this domain's data/)",
    )
    common = StockIvRegimeParser(add_help=False, parents=[data])
    common.add_argument(
        "--lookback",
        type=positive_integer("sessions"),
        default=DEFAULT_LOOKBACK,
        metavar="N",
        help=f"trading sessions ending at the latest completed session (default: {DEFAULT_LOOKBACK})",
    )
    selection = StockIvRegimeParser(add_help=False)
    selection.add_argument(
        "tickers", nargs="*", metavar="TICKER", help="default: the stock section of the watchlist"
    )
    selection.add_argument(
        "--refresh",
        action="store_true",
        help="treat every window session as missing, whatever is stored (the newest chain of a session wins)",
    )
    selection.add_argument(
        "--watchlist",
        type=file_path,
        default=WATCHLIST,
        metavar="PATH",
        help="watchlist read when no ticker is given (default: this domain's watchlist.json)",
    )
    commands = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    fetch_command = commands.add_parser(
        "fetch",
        parents=[common, selection],
        help=(
            "write the prices from Tiingo when they are not current, then the chain of every session the "
            "window and its percentiles need that raw/ lacks, the latest session first (uses the network; "
            "needs TIINGO_API and EODHD_API)"
        ),
    )
    fetch_command.add_argument(
        "--budget",
        type=positive_integer("requests"),
        default=DEFAULT_BUDGET,
        metavar="R",
        help=(
            f"the most requests this run sends to EODHD (default: {DEFAULT_BUDGET}; EODHD allows 10,000 "
            "a day)"
        ),
    )
    commands.add_parser(
        "plan",
        parents=[common, selection],
        help="list the sessions to fetch (newest first), invalid raw files and the action (read-only)",
    )
    record_command = commands.add_parser(
        "record", parents=[common], help="rewrite the CSV from the raw files and write a new report"
    )
    record_command.add_argument("ticker", metavar="TICKER")
    record_command.add_argument(
        "--partial",
        action="store_true",
        help="write the report although sessions are not fetched (shown as gaps and listed in it)",
    )
    show_command = commands.add_parser("show", parents=[common], help="print the window as Markdown")
    show_command.add_argument("ticker", metavar="TICKER")
    return parser


def _interrupt(signum: int, frame: FrameType | None) -> NoReturn:
    raise KeyboardInterrupt


@contextmanager
def _terminate_as_interrupt() -> Iterator[None]:
    """While the block runs, SIGTERM raises ``KeyboardInterrupt`` as Ctrl-C does; the previous
    handler is restored afterwards."""
    previous = signal.signal(signal.SIGTERM, _interrupt)
    try:
        yield
    finally:
        signal.signal(signal.SIGTERM, signal.SIG_DFL if previous is None else previous)


def main(
    argv: Sequence[str] | None = None,
    now: datetime | None = None,
    client: EodhdClient | None = None,
    settings: Callable[[str], str | None] = setting,
    tiingo: TiingoClient | None = None,
) -> int:
    args = build_parser().parse_args(argv)
    try:
        moment = to_eastern(now if now is not None else datetime.now(NEW_YORK), "now")
        data_dir = args.data_dir.absolute()
        if data_dir.exists() and not data_dir.is_dir():
            return fail(LABEL, f"{data_dir} is not a directory")
        layout = DataLayout(data_dir)
        if args.command == "fetch":
            # The keys are checked here, before the watchlist or any raw file is read; they are never
            # printed.
            eodhd = (
                client if client is not None else EodhdClient(settings(API_KEY_SETTING), budget=args.budget)
            )
            prices = tiingo if tiingo is not None else TiingoClient(settings(TIINGO_KEY_SETTING))
            with _terminate_as_interrupt():
                output = fetch(
                    layout,
                    args.tickers,
                    args.lookback,
                    moment,
                    eodhd,
                    prices,
                    refresh=args.refresh,
                    watchlist=args.watchlist,
                )
        elif args.command == "plan":
            output = plan(
                layout, args.tickers, args.lookback, moment, refresh=args.refresh, watchlist=args.watchlist
            )
        elif args.command == "record":
            output = record(layout, args.ticker, args.lookback, moment, partial=args.partial)
        else:
            sys.stdout.write(show(layout, args.ticker, args.lookback, moment))
            return 0
    except (EodhdError, TiingoError, ValueError, OSError, OverflowError) as error:
        return fail(LABEL, str(error))
    except KeyboardInterrupt:
        return fail(LABEL, COMMAND_INTERRUPTED)
    if args.command in ("fetch", "plan"):
        output["watchlist"] = None if args.tickers else str(args.watchlist)
    # ASCII-only JSON: values that came from file names or EODHD cannot carry control or
    # bidirectional characters to the terminal.
    print(json.dumps(output, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
