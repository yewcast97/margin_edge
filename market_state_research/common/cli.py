"""Command-line conventions shared by every domain.

Every failure, including a malformed command line, is one ``LABEL: ...`` line on standard
error with exit status 2, where the label names the domain (for example ``REGIME``), so the
bot can read it the same way whatever went wrong.
"""

import argparse
import re
import sys
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import ClassVar, NoReturn

from .text import printable


def positive_integer(what: str) -> Callable[[str], int]:
    """An argparse type for a count of ``what`` written with ASCII digits only.

    No sign, spaces, separators or other Unicode digits are accepted, so the value the
    command uses is exactly the one typed.
    """

    def parse(text: str) -> int:
        problem = argparse.ArgumentTypeError(f"expected a positive whole number of {what}, got {text!r}")
        if not (text.isascii() and text.isdigit()):
            raise problem
        try:
            value = int(text)
        except ValueError:  # longer than Python's integer-string conversion limit
            raise problem from None
        if value < 1:
            raise problem
        return value

    return parse


def calendar_date(text: str) -> date:
    """An argparse type for a calendar date written ``YYYY-MM-DD`` with ASCII digits only.

    No other ISO 8601 form (basic, week or ordinal dates, a time), sign, spaces or other
    Unicode digits are accepted, and the date must exist, so the value the command uses is
    exactly the one typed.
    """
    problem = argparse.ArgumentTypeError(f"expected a YYYY-MM-DD date, got {text!r}")
    if re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", text, re.ASCII) is None:
        raise problem
    try:
        return date.fromisoformat(text)
    except ValueError:  # a month, day or year that does not exist
        raise problem from None


def directory_path(text: str) -> Path:
    """A data directory. An empty value (such as an unset shell variable) is refused rather
    than read as the current directory."""
    if not text:
        raise argparse.ArgumentTypeError("expected a directory path, got an empty value")
    return Path(text)


def file_path(text: str) -> Path:
    """A file to read. An empty value (such as an unset shell variable) is refused rather
    than read as the current directory."""
    if not text:
        raise argparse.ArgumentTypeError("expected a file path, got an empty value")
    return Path(text)


class Parser(argparse.ArgumentParser):
    """Report command-line errors like every other failure: one ``LABEL: ...`` line, exit 2.

    Each domain subclasses it with its own ``label``; there is no default, so every
    domain names itself. ``add_subparsers`` builds subcommand parsers of the same class,
    so they report the same label.
    """

    label: ClassVar[str]

    def error(self, message: str) -> NoReturn:
        self.exit(2, f"{self.label}: {printable(self.prog)}: {printable(message)}\n")


def fail(label: str, message: str) -> int:
    """Print ``message`` as one ``{label}: ...`` line on standard error; return exit status 2."""
    print(f"{label}: {printable(message)}", file=sys.stderr)
    return 2
