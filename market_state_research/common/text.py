"""Ticker symbols and single-line message text shared by every domain."""

import re

TICKER_PATTERN = re.compile(r"[A-Z][A-Z0-9.\-]{0,14}")


def ticker_symbol(value: str) -> str:
    """Normalise a US ticker; reject anything that could act as a path or query."""
    # Check ASCII first: str.upper() folds some non-ASCII letters into ASCII ("ß" -> "SS").
    symbol = value.upper() if isinstance(value, str) and value.isascii() else ""
    if not TICKER_PATTERN.fullmatch(symbol):
        raise ValueError("ticker must be a US symbol without path or query characters")
    return symbol


def printable(text: str) -> str:
    """Escape control and other non-printable characters so a message stays on one line."""
    return "".join(
        char if char.isprintable() else char.encode("unicode_escape").decode("ascii") for char in text
    )
