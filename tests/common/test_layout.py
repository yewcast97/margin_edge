"""common/layout.py: the three data sections, atomic writes and names ordered by their token."""

import os
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

from market_state_research.common import layout
from market_state_research.common.layout import (
    DataLayout,
    FileExists,
    listed,
    name_instant,
    newest,
    rejected,
    stamped,
    write_file,
)

EDT = timezone(timedelta(hours=-4), "EDT")
EST = timezone(timedelta(hours=-5), "EST")


def test_the_layout_names_three_sections_per_ticker(tmp_path):
    data = DataLayout(tmp_path / "data")
    assert data.raw("INTC") == tmp_path / "data" / "raw" / "INTC"
    assert data.formatted("INTC") == tmp_path / "data" / "formatted" / "INTC"
    assert data.reports("INTC") == tmp_path / "data" / "reports" / "INTC"


@pytest.mark.parametrize("data", [b"", b"bytes\n", bytes(range(256)) * 64, "text ✓ – ’\n"])
def test_write_file_creates_parents_and_writes_bytes_or_utf8_text(tmp_path, data):
    target = tmp_path / "a" / "b" / "file.txt"
    assert write_file(target, data) == target
    expected = data.encode("utf-8") if isinstance(data, str) else data
    assert target.read_bytes() == expected
    assert sorted(path.name for path in target.parent.iterdir()) == ["file.txt"]


def test_write_file_refuses_an_existing_file_and_leaves_it_unchanged(tmp_path):
    target = write_file(tmp_path / "report.html", "first")
    with pytest.raises(FileExists, match="already exists; refusing to overwrite it"):
        write_file(target, "second")
    assert target.read_text() == "first"
    assert sorted(path.name for path in tmp_path.iterdir()) == ["report.html"]
    assert issubclass(FileExists, FileExistsError)


def test_write_file_with_overwrite_replaces_the_file(tmp_path):
    target = write_file(tmp_path / "table.csv", "old\n")
    write_file(target, "new\n", overwrite=True)
    assert target.read_text() == "new\n"
    assert sorted(path.name for path in tmp_path.iterdir()) == ["table.csv"]


@pytest.mark.parametrize("overwrite", [False, True])
@pytest.mark.parametrize("umask", [0o022, 0o077])
def test_written_files_get_the_umask_permissions(tmp_path, overwrite, umask):
    target = tmp_path / "report.html"
    if overwrite:
        target.write_text("old")
    previous = os.umask(umask)
    try:
        write_file(target, "data", overwrite=overwrite)
    finally:
        os.umask(previous)
    assert target.stat().st_mode & 0o777 == 0o666 & ~umask


@pytest.mark.parametrize("overwrite", [False, True])
def test_a_failed_write_leaves_no_temporary_file(tmp_path, monkeypatch, overwrite):
    def fail(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(layout.os, "replace" if overwrite else "link", fail)
    with pytest.raises(OSError, match="disk full"):
        write_file(tmp_path / "file.txt", "data", overwrite=overwrite)
    assert list(tmp_path.iterdir()) == []


def test_listed_skips_dotfiles_rejected_files_directories_and_other_suffixes(tmp_path):
    for name in ["b.json", "a.json", ".a.json.tmp", "c.json.rejected", "d.txt"]:
        (tmp_path / name).write_text("x")
    (tmp_path / "e.json").mkdir()
    assert [path.name for path in listed(tmp_path, ".json")] == ["a.json", "b.json"]
    assert [path.name for path in listed(tmp_path)] == ["a.json", "b.json", "d.txt"]
    assert [path.name for path in rejected(tmp_path)] == ["c.json.rejected"]
    assert listed(tmp_path / "missing") == []
    assert rejected(tmp_path / "missing") == []


def test_stamped_names_a_moment_by_its_new_york_token():
    moment = datetime(2026, 10, 6, 18, 12, 30, 586000, tzinfo=UTC)
    assert stamped("INTC_2026-10-05_5s", moment, ".html") == "INTC_2026-10-05_5s_20261006T141230EDT.html"


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("INTC_2026-10-05_5s_20261006T141246EDT.html", datetime(2026, 10, 6, 14, 12, 46, tzinfo=EDT)),
        ("INTC_2026-10-05_5s_20261006T141246EDT.md", datetime(2026, 10, 6, 14, 12, 46, tzinfo=EDT)),
        ("flow_2026-10-06_20261006T224749EDT_2.json", datetime(2026, 10, 6, 22, 47, 49, tzinfo=EDT)),
        ("overview_20261212T170000EST.json.rejected", datetime(2026, 12, 12, 17, 0, tzinfo=EST)),
        ("INTC_2026-10-05.html", None),
        ("INTC_20261006T141246Z.html", None),
        ("INTC_20260701T120000EST.html", None),  # the zone in force in July is EDT
        ("INTC_20261006T141246EDT", None),  # no extension
    ],
)
def test_name_instant_reads_the_trailing_token(name, expected):
    assert name_instant(name) == expected


def test_names_order_by_instant_on_the_fall_back_day():
    first = name_instant("SPX_20261101T015959EDT.html")
    second = name_instant("SPX_20261101T010000EST.html")
    assert first is not None and second is not None
    assert first < second
    assert sorted(["SPX_20261101T010000EST.html", "SPX_20261101T015959EDT.html"]) == [
        "SPX_20261101T010000EST.html",
        "SPX_20261101T015959EDT.html",
    ]  # text order is the wrong order


def test_newest_takes_the_latest_token_not_after_now(tmp_path):
    names = [
        "SPX_2026-10-30_5s_20261101T015959EDT.html",
        "SPX_2026-10-30_5s_20261101T010000EST.html",  # an hour later than the EDT name
        "SPX_2026-10-30_5s_20261102T090000EST.html",  # after now
        "SPX_2026-10-30_3s_20261101T020000EST.html",  # another window
        "SPX_2026-10-30_5s_20261101T020000EST.html.rejected",
        "SPX_2026-10-30_5s_20261101T020000EST.md",
        "SPX_2026-10-30_5s_garbage.html",
    ]
    for name in names:
        (tmp_path / name).write_text("x")
    now = datetime(2026, 11, 1, 3, 0, tzinfo=EST)
    found = newest(tmp_path, "SPX_2026-10-30_5s_", ".html", now)
    assert found == tmp_path / "SPX_2026-10-30_5s_20261101T010000EST.html"
    assert newest(tmp_path, "SPX_2026-10-30_5s_", ".md", now) == tmp_path / names[5]
    assert newest(tmp_path, "INTC_", ".html", now) is None
    assert newest(tmp_path / "missing", "SPX_", ".html", now) is None


def test_newest_needs_an_aware_now(tmp_path):
    with pytest.raises(ValueError, match="now must include a timezone"):
        newest(tmp_path, "SPX_", ".html", datetime(2026, 11, 1))


def test_write_file_never_follows_through_to_a_dangling_link(tmp_path):
    target = tmp_path / "report.html"
    os.symlink(tmp_path / "elsewhere.html", target)
    with pytest.raises(FileExists):
        write_file(target, "data")
    assert not (tmp_path / "elsewhere.html").exists()
    assert Path(os.readlink(target)) == tmp_path / "elsewhere.html"
