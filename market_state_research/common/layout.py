"""The three sections of every domain's ``data/`` directory and the one write rule.

``raw/{TICKER}/`` holds what was fetched, verbatim: each domain's ``fetch`` writes there.
Python never modifies a raw file. A raw file that fails validation is renamed with the
suffix ``.rejected`` by the bot and is skipped by every read.

``formatted/{TICKER}/`` holds what Python derives from ``raw/``: tables and text that a
later run rebuilds, so they are overwritten.

``reports/{TICKER}/`` holds what the user reads. Python never overwrites or deletes a report:
a name that exists fails the command, and older reports stay.

Names that carry a New York time token (``common.times.timestamp_token``) are ordered by
the instant the token names, never as text: on the fall-back day ``...T010000EST``
follows ``...T015959EDT``.
"""

import os
import re
import secrets
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .times import TOKEN_PATTERN, parse_timestamp_token, timestamp_token, to_eastern

RAW = "raw"
FORMATTED = "formatted"
REPORTS = "reports"
REJECTED_SUFFIX = ".rejected"

# A name's trailing token: ``..._{TOKEN}`` before the extension, optionally followed by
# ``_N`` (two files of one second), e.g. ``INTC_2026-10-05_5s_20261006T141246EDT.html``.
_TRAILING_TOKEN = re.compile(rf"_(?P<token>{TOKEN_PATTERN})(?:_[0-9]+)?(?:\.[A-Za-z0-9]+)+$", re.ASCII)


class FileExists(FileExistsError):
    """``write_file`` without ``overwrite`` found the target already present."""


@dataclass(frozen=True)
class DataLayout:
    """One domain's ``data/`` directory, or another directory given with ``--data-dir``."""

    root: Path

    def raw(self, ticker: str) -> Path:
        return self.root / RAW / ticker

    def formatted(self, ticker: str) -> Path:
        return self.root / FORMATTED / ticker

    def reports(self, ticker: str) -> Path:
        return self.root / REPORTS / ticker


def write_file(path: Path, data: bytes | str, *, overwrite: bool = False) -> Path:
    """Write ``data`` (text as UTF-8) to ``path`` atomically and return ``path``.

    The bytes go to a temporary sibling first, so a reader never sees a partial file.
    Without ``overwrite`` the temporary file is linked to ``path``, which fails with
    ``FileExists`` when ``path`` exists; with ``overwrite`` it replaces ``path``. Parent
    directories are created. The temporary name is always removed. The file gets the
    permissions the umask gives any new file, as with ``open``.
    """
    payload = data.encode("utf-8") if isinstance(data, str) else data
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f".{path.name}.{secrets.token_hex(8)}.tmp"
    try:
        with open(temporary, "xb") as handle:
            handle.write(payload)
        if overwrite:
            os.replace(temporary, path)
        else:
            try:
                os.link(temporary, path)
            except FileExistsError:
                raise FileExists(f"{path} already exists; refusing to overwrite it") from None
    finally:
        temporary.unlink(missing_ok=True)
    return path


def listed(directory: Path, suffix: str = "") -> list[Path]:
    """The regular files directly in ``directory`` whose names end with ``suffix``, by name.

    Dotfiles (temporary files among them) and names ending in ``.rejected`` are left out;
    a missing directory lists nothing.
    """
    if not directory.is_dir():
        return []
    return sorted(
        path
        for path in directory.iterdir()
        if not path.name.startswith(".")
        and not path.name.endswith(REJECTED_SUFFIX)
        and path.name.endswith(suffix)
        and path.is_file()
    )


def rejected(directory: Path) -> list[Path]:
    """The files directly in ``directory`` that the bot renamed with ``.rejected``, by name."""
    if not directory.is_dir():
        return []
    return sorted(
        path for path in directory.iterdir() if path.name.endswith(REJECTED_SUFFIX) and path.is_file()
    )


def stamped(stem: str, moment: datetime, suffix: str) -> str:
    """``{stem}_{token}{suffix}``, the token naming ``moment`` in New York time to the second."""
    return f"{stem}_{timestamp_token(moment)}{suffix}"


def name_instant(name: str) -> datetime | None:
    """The New York instant named by the token at the end of ``name``, or None without one."""
    match = _TRAILING_TOKEN.search(name)
    return None if match is None else parse_timestamp_token(match["token"])


def newest(directory: Path, prefix: str, suffix: str, now: datetime) -> Path | None:
    """The file ``{prefix}{token}{suffix}`` in ``directory`` whose token is the latest not after ``now``.

    Names whose middle is not exactly one valid token are ignored, so another window's or
    ticker's files never match a prefix that ends where the token begins.
    """
    limit = to_eastern(now, "now")
    best: tuple[datetime, Path] | None = None
    for path in listed(directory, suffix):
        name = path.name
        if not name.startswith(prefix):
            continue
        instant = parse_timestamp_token(name[len(prefix) : len(name) - len(suffix)])
        if instant is None or instant > limit:
            continue
        if best is None or instant > best[0]:
            best = (instant, path)
    return None if best is None else best[1]
