"""Shared fixtures: a controllable New York clock, an isolated data directory, a watchlist
file, the host time zone, and a guard that refuses any real network request.

The production-data guard for every domain lives in the repository's ``tests/conftest.py``.
"""

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from time import tzset

import pytest

from market_state_research.common.layout import DataLayout
from market_state_research.market_regime.script import client as client_module
from market_state_research.market_regime.script import tiingo as tiingo_module

from .support import NOW


@dataclass
class Clock:
    """A fake clock; artifact names have one-second resolution, so tick between writes."""

    now: datetime = NOW

    def tick(self, seconds: float = 1) -> datetime:
        self.now += timedelta(seconds=seconds)
        return self.now


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def layout(tmp_path) -> DataLayout:
    return DataLayout(tmp_path / "data")


@pytest.fixture
def watchlist(tmp_path) -> Callable[..., Path]:
    """Write a watchlist to ``tmp_path / "watchlist.json"``; the repository's own is never read."""

    def write(stock: Sequence[str] = ("TEST",), index: Sequence[str] = ()) -> Path:
        path = tmp_path / "watchlist.json"
        path.write_text(json.dumps({"stock": list(stock), "index": list(index)}), encoding="utf-8")
        return path

    return write


@pytest.fixture
def host_time_zone(monkeypatch):
    """Set the process time zone (an IANA name or POSIX TZ string) for one test."""

    def set_zone(zone: str) -> None:
        monkeypatch.setenv("TZ", zone)
        tzset()

    yield set_zone
    monkeypatch.undo()
    tzset()


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """No test reaches EODHD or Tiingo: the real HTTP layer refuses every request."""

    def refuse(url, headers, limit):
        raise AssertionError("a test tried to reach the network")

    monkeypatch.setattr(client_module, "urllib_fetch", refuse)
    monkeypatch.setattr(tiingo_module, "urllib_fetch", refuse)
    for client_class in (client_module.EodhdClient, tiingo_module.TiingoClient):
        monkeypatch.setattr(
            client_class.__init__, "__defaults__", (refuse,) + client_class.__init__.__defaults__[1:]
        )
