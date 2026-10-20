"""Command line contract of ``python -m market_state_research.market_position_regime.script``."""

import json
import os
import re
import shutil
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from market_state_research import common as common_package
from market_state_research.common.layout import DataLayout
from market_state_research.common.times import to_eastern
from market_state_research.market_position_regime import script as script_package
from market_state_research.market_position_regime.script import client as client_module
from market_state_research.market_position_regime.script.__main__ import (
    LABEL,
    PROGRAM,
    MarketPositionRegimeParser,
    build_parser,
    main,
)
from market_state_research.market_position_regime.script.store import DATA_DIRECTORY

from .fake_sources import FakeSources
from .support import KEY, NOW, save_all, workbook_bytes

MODULE = "market_state_research.market_position_regime.script"
SCRIPT_DIRECTORY = Path(script_package.__file__).resolve().parent
COMMON_DIRECTORY = Path(common_package.__file__).resolve().parent


class Settings:
    """Records every setting asked for and answers with the canary key."""

    def __init__(self, **values: str | None) -> None:
        self.asked: list[str] = []
        self.values = {"FRED_API": KEY, **values}

    def __call__(self, name: str) -> str | None:
        self.asked.append(name)
        return self.values.get(name)


def run(capsys, *argv, **options):
    code = main(list(argv), **{"now": NOW, **options})
    out, err = capsys.readouterr()
    return code, out, err


def test_the_parser_names_the_domain_and_its_defaults():
    parser = build_parser()
    assert isinstance(parser, MarketPositionRegimeParser) and LABEL == "MARKET_POSITION_REGIME"
    assert f"python -m {MODULE}" == PROGRAM
    assert SCRIPT_DIRECTORY.parent / "data" == DATA_DIRECTORY
    for command in ("fetch", "plan", "record", "show"):
        parsed = parser.parse_args([command])
        assert (parsed.data_dir, parsed.window_from, parsed.window_to) == (DATA_DIRECTORY, None, None)
    assert parser.parse_args(["plan", "--refresh", "--from", "2024-01-31"]).refresh is True
    with pytest.raises(SystemExit):
        parser.parse_args(["record", "--refresh"])  # only fetch and plan request anything again


def test_parse_errors_are_one_labelled_line(capsys):
    with pytest.raises(SystemExit) as exit_info:
        main(["plan", "--from", "2026-02-30"], now=NOW)
    out, err = capsys.readouterr()
    assert (exit_info.value.code, out) == (2, "")
    assert re.fullmatch(
        r"MARKET_POSITION_REGIME: .*: argument --from: expected a YYYY-MM-DD date, got '2026-02-30'\n", err
    )


@pytest.mark.parametrize(
    ("argv", "message"),
    [
        (["--to", "2026-10-21"], "--to must not be after today (2026-10-20)"),
        (["--from", "2026-10-21", "--to", "2026-10-20"], "--from must not be after --to"),
        (["--to", "0002-01-01"], "--to leaves no default --from 3 years before it; give --from"),
    ],
)
def test_a_refused_window_is_one_line_before_any_work(capsys, tmp_path, argv, message):
    settings = Settings()
    target = tmp_path / "file"
    target.write_text("x")
    code, out, err = run(capsys, "fetch", *argv, "--data-dir", str(target), settings=settings)
    assert (code, out, err) == (2, "", f"{LABEL}: {message}\n")
    assert settings.asked == []


def test_the_default_window_is_three_years_to_today(capsys, layout):
    code, out, err = run(capsys, "plan", "--data-dir", str(layout.root))
    assert (code, err) == (0, "")
    window = json.loads(out)["window"]
    assert (window["from"], window["to"]) == ("2023-10-20", "2026-10-20")


@pytest.mark.parametrize(
    ("values", "message"),
    [
        ({"FRED_API": None}, 'FRED_API is not set; add FRED_API="..." to the repository-root .env'),
        ({"FRED_API": "bad key!"}, "FRED_API must be 32 lowercase ASCII letters or digits"),
    ],
)
def test_fetch_without_a_valid_key_sends_nothing(capsys, layout, values, message):
    code, out, err = run(capsys, "fetch", "--data-dir", str(layout.root), settings=Settings(**values))
    assert (code, out, err) == (2, "", f"{LABEL}: {message}\n")
    assert not layout.root.exists()


def test_fetch_never_prints_or_stores_the_key(capsys, layout, monkeypatch):
    fake = FakeSources(workbook=workbook_bytes())
    defaults = client_module.Client.__init__.__defaults__
    # The client is built from the settings; the fake answers through its HTTP layer.
    monkeypatch.setattr(client_module.Client.__init__, "__defaults__", (fake, lambda: NOW) + defaults[2:])
    settings = Settings()
    code, out, err = run(capsys, "fetch", "--data-dir", str(layout.root), settings=settings)
    assert (code, err) == (0, "")
    assert settings.asked == ["FRED_API"]
    output = json.loads(out)
    assert output["fred_key"] == "set" and KEY not in out
    assert output["sources"]["finra"]["status"] == "new"
    assert output["sources"]["NCBEILQ027S"]["status"] == "failed"  # the fake has no FRED series
    assert fake.keys == [KEY, KEY] and all(KEY not in call for call in fake.calls)
    for path in layout.root.rglob("*"):
        assert path.is_dir() or KEY.encode() not in path.read_bytes()


@pytest.mark.parametrize("command", [["plan"], ["record"], ["show"]])
def test_offline_commands_read_no_setting(capsys, layout, command):
    save_all(layout)
    settings = Settings()
    code, out, err = run(capsys, *command, "--data-dir", str(layout.root), settings=settings)
    assert (code, err, settings.asked) == (0, "", [])


def test_show_prints_markdown_and_the_others_ascii_json(capsys, layout):
    save_all(layout)
    code, out, err = run(capsys, "show", "--data-dir", str(layout.root))
    assert (code, err) == (0, "")
    assert out.startswith("Action: record.") and "\n\n# US equity positioning" in out
    code, out, err = run(capsys, "record", "--data-dir", str(layout.root))
    assert code == 0 and out.isascii() and json.loads(out)["report"]["status"] == "written"


def test_a_file_as_data_directory_is_refused(capsys, tmp_path):
    target = tmp_path / "file"
    target.write_text("x")
    code, out, err = run(capsys, "plan", "--data-dir", str(target))
    assert (code, err) == (2, f"{LABEL}: {target} is not a directory\n")


def test_record_without_data_is_one_line(capsys, layout):
    code, out, err = run(capsys, "record", "--data-dir", str(layout.root))
    assert (code, out) == (2, "")
    assert (
        err
        == f"{LABEL}: no month or week of the window 2023-10-20 to 2026-10-20 is fetched; run fetch first\n"
    )


def snapshot(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)): path.read_bytes() for path in sorted(root.rglob("*")) if path.is_file()
    }


def test_module_entry_point_uses_its_own_data_directory(tmp_path):
    root = (tmp_path / "checkout").resolve()
    domain = root / "market_state_research" / "market_position_regime"
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc")
    shutil.copytree(SCRIPT_DIRECTORY, domain / "script", ignore=ignore)
    shutil.copytree(COMMON_DIRECTORY, root / "market_state_research" / "common", ignore=ignore)
    (root / "market_state_research" / "__init__.py").write_text("")
    # The subprocess runs on the real clock: the raw files are saved as fetched a minute ago.
    fetched = to_eastern(datetime.now(UTC) - timedelta(minutes=1)).replace(microsecond=0)
    save_all(DataLayout(domain / "data"), fetched_at=fetched)
    working = tmp_path / "elsewhere"
    working.mkdir()
    before = snapshot(root)
    environment = {**os.environ, "PYTHONPATH": str(root), "PYTHONDONTWRITEBYTECODE": "1", "FRED_API": ""}
    result = subprocess.run(
        [sys.executable, "-m", MODULE, "plan", "--from", "2026-01-01"],
        cwd=working,
        env=environment,
        capture_output=True,
        encoding="utf-8",
        timeout=120,
        check=False,
    )
    assert (result.returncode, result.stderr) == (0, "")
    output = json.loads(result.stdout)
    assert output["invalid_files"] == []
    assert output["sources"]["finra"]["path"].startswith(str(domain / "data" / "raw" / "market"))
    assert output["window"]["from"] == "2026-01-01"
    assert list(working.iterdir()) == []
    assert snapshot(root) == before
