"""Shared fixtures: an isolated data directory, the host time zone, and a guard that refuses
any real network request.

The production-data guard for every domain lives in the repository's ``tests/conftest.py``.
"""

from time import tzset

import pytest

from market_state_research.common.layout import DataLayout
from market_state_research.market_position_regime.script import client as client_module


@pytest.fixture
def layout(tmp_path) -> DataLayout:
    return DataLayout(tmp_path / "data")


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
    """No test reaches FINRA, the CFTC or Cboe: the real HTTP layer refuses every request."""

    def refuse(url, headers, limit):
        raise AssertionError("a test tried to reach the network")

    monkeypatch.setattr(client_module, "urllib_fetch", refuse)
    defaults = client_module.Client.__init__.__defaults__
    monkeypatch.setattr(client_module.Client.__init__, "__defaults__", (refuse,) + defaults[1:])
