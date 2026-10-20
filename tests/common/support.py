"""Clock readings, file-tree helpers and odd tzinfos for the offline ``common`` tests.

Expected instants are written with fixed ``EDT``/``EST`` offsets, independently of
``zoneinfo`` and of the code under test. Tests write only below pytest's temporary
directories; nothing in ``common`` knows a domain's ``data/`` directory.
"""

import os
import stat
from datetime import date, datetime, timedelta, timezone, tzinfo
from pathlib import Path
from zoneinfo import ZoneInfo

NEW_YORK = ZoneInfo("America/New_York")
EDT = timezone(timedelta(hours=-4), "EDT")
EST = timezone(timedelta(hours=-5), "EST")
TOKYO = timezone(timedelta(hours=9), "JST")
MICROSECOND = timedelta(microseconds=1)


def edt(*fields: int) -> datetime:
    """A New York daylight-time wall clock reading with a fixed -04:00 offset."""
    return datetime(*fields, tzinfo=EDT)


def est(*fields: int) -> datetime:
    """A New York standard-time wall clock reading with a fixed -05:00 offset."""
    return datetime(*fields, tzinfo=EST)


END = date(2026, 10, 2)  # Friday session
FRIDAY_CLOSE = edt(2026, 10, 2, 16)
NOW = edt(2026, 10, 2, 20)  # Friday evening, after the close
MONDAY = date(2026, 10, 5)
MONDAY_CLOSE = edt(2026, 10, 5, 16)
FIRST_SESSION = date(2000, 1, 3)  # first XNYS session of the supported range; 2000-01-01 is a Saturday
LAST_SESSION = date(2099, 12, 31)  # last XNYS session of the supported range, a Thursday

FULLWIDTH_ZERO = 0xFF10  # FULLWIDTH DIGIT ZERO: Unicode decimal digit, matched by an unrestricted \d
ARABIC_INDIC_ZERO = 0x0660  # ARABIC-INDIC DIGIT ZERO
ROOT_USER = os.geteuid() == 0


def foreign_digits(text: str, zero: int) -> str:
    """``text`` with its ASCII digits replaced by the decimal digits of another script."""
    return "".join(
        chr(zero + int(character)) if character in "0123456789" else character for character in text
    )


class OffsetlessZone(tzinfo):
    """A tzinfo whose ``utcoffset`` is None: datetimes using it are naive by definition."""

    def utcoffset(self, dt):
        return None

    def dst(self, dt):
        return None

    def tzname(self, dt):
        return None


def mode(path: Path) -> int:
    return stat.S_IMODE(path.lstat().st_mode)


def tree(root: Path) -> dict[str, bytes]:
    """Every file below ``root`` as relative path -> bytes, for no-overwrite assertions."""
    if not root.exists():
        return {}
    return {
        str(path.relative_to(root)): path.read_bytes() for path in sorted(root.rglob("*")) if path.is_file()
    }


def leftovers(root: Path) -> list[Path]:
    """Hidden or temporary entries anywhere below ``root`` (pathlib globbing includes dotfiles)."""
    return sorted(path for path in root.rglob("*") if path.name.startswith(".") or path.name.endswith(".tmp"))


def snapshot(root: Path) -> dict[str, tuple]:
    """Every entry below ``root`` with its type, permissions and content, without following links."""
    entries = {}
    for path in sorted(root.rglob("*")):
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode):
            content: object = os.readlink(path)
        elif stat.S_ISREG(info.st_mode):
            content = path.read_bytes()
        else:
            content = None
        entries[str(path.relative_to(root))] = (
            stat.S_IFMT(info.st_mode),
            stat.S_IMODE(info.st_mode),
            content,
        )
    return entries
