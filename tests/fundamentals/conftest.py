"""Shared fixtures: a controllable New York clock, an isolated data directory and the host zone.

The production-data guard for every domain lives in the repository's ``tests/conftest.py``.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from time import tzset

import pytest

from market_state_research.common.layout import DataLayout

from .support import NOW


@dataclass
class Clock:
    """A fake clock; artifact names have one-second resolution, so tick between writes."""

    now: datetime = NOW

    def tick(self, seconds: float = 1) -> datetime:
        self.now += timedelta(seconds=seconds)
        return self.now

    def set(self, moment: datetime) -> datetime:
        self.now = moment
        return self.now


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def layout(tmp_path) -> DataLayout:
    return DataLayout(tmp_path / "data")


@pytest.fixture
def host_time_zone(monkeypatch):
    """Set the process time zone (an IANA name or POSIX TZ string) for one test, restoring it afterwards."""

    def set_zone(zone: str) -> None:
        monkeypatch.setenv("TZ", zone)
        tzset()

    yield set_zone
    monkeypatch.undo()
    tzset()
