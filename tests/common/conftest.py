"""Shared fixtures for the ``common`` tests: control of the host process time zone."""

from time import tzset

import pytest


@pytest.fixture
def host_time_zone(monkeypatch):
    """Set the process time zone to a POSIX TZ string for one test, restoring the host's afterwards."""

    def set_zone(zone: str) -> None:
        monkeypatch.setenv("TZ", zone)
        tzset()

    yield set_zone
    monkeypatch.undo()
    tzset()
