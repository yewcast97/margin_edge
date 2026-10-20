"""Personal settings: the process environment first, then the ignored repository-root ``.env``.

The file holds private values, so Python reads it only through this module and reports
a malformed line by its number alone, never by its text. Values are never printed,
archived or written to a tracked file by the code here.

The format is a strict subset of the usual dotenv syntax: one ``KEY=VALUE`` per line,
optionally preceded by ``export``, with keys of ASCII capitals, digits and underscores
(not starting with a digit) and no spaces around ``=``. The value is the rest of the
line; one pair of matching surrounding quotes (``"`` or ``'``) is removed, and nothing
else is interpreted: no escapes, inline comments or variable expansion. Blank lines and
lines starting with ``#`` are skipped, CRLF line ends are accepted, and the last
assignment of a key wins. Any other control character but tab, such as a bare carriage
return or an escape, makes its line malformed, a comment included, so a file with
CR-only line ends is refused rather than read as one line.
"""

import os
import re
from pathlib import Path

from . import REPOSITORY_ROOT
from .text import printable

ENV_PATH = REPOSITORY_ROOT / ".env"
# Every Unicode control character (C0, DEL and C1) except tab.
_CONTROL = r"\x00-\x08\x0a-\x1f\x7f-\x9f"
# A blank line or a comment.
_SKIPPED = re.compile(rf"(?:#[^{_CONTROL}]*)?")
# Explicit ASCII classes: str.isupper() or \w would also accept other scripts' letters.
# The value may not start with whitespace: the line is already stripped, so that is a space after "=".
_ASSIGNMENT = re.compile(rf"(?:export[ \t]+)?([A-Z_][A-Z0-9_]*)=(?![ \t])([^{_CONTROL}]*)")
_QUOTES = ('"', "'")


def _unquoted(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in _QUOTES:
        return value[1:-1]
    return value


def read_env(path: Path) -> dict[str, str]:
    """The settings assigned in ``path``; ``{}`` when the file does not exist.

    There is no default path, so a caller (such as a test) can never read the real file
    by accident. A line that is not UTF-8 or not ``KEY=VALUE`` raises ``ValueError``
    naming the printable path and the line number only, so a private value cannot reach
    the message. Other filesystem errors (for example permissions) propagate unchanged.
    """
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return {}
    settings: dict[str, str] = {}
    for number, line in enumerate(raw.split(b"\n"), start=1):
        try:
            text = line.removesuffix(b"\r").decode("utf-8").strip(" \t")
        except UnicodeDecodeError:
            match = None
        else:
            if _SKIPPED.fullmatch(text):
                continue
            match = _ASSIGNMENT.fullmatch(text)
        if match is None:
            raise ValueError(f"{printable(str(path))}: line {number} is not KEY=VALUE")
        settings[match[1]] = _unquoted(match[2])
    return settings


def setting(name: str, path: Path = ENV_PATH) -> str | None:
    """The value of ``name`` from the process environment, else from ``path``; ``None`` if unset.

    Presence wins: a variable set in the environment, even to an empty value, is returned
    as it is, and ``path`` is then not opened.
    """
    if name in os.environ:
        return os.environ[name]
    return read_env(path).get(name)
