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
from .support import NOW, history_bytes, save_all, skew_bytes, workbook_bytes

MODULE = "market_state_research.market_position_regime.script"
SCRIPT_DIRECTORY = Path(script_package.__file__).resolve().parent
COMMON_DIRECTORY = Path(common_package.__file__).resolve().parent


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
    target = tmp_path / "file"
    target.write_text("x")
    fake = FakeSources()
    code, out, err = run(capsys, "fetch", *argv, "--data-dir", str(target), client=fake.client())
    assert (code, out, err) == (2, "", f"{LABEL}: {message}\n")
    assert fake.calls == []


def test_the_default_window_is_three_years_to_today(capsys, layout):
    code, out, err = run(capsys, "plan", "--data-dir", str(layout.root))
    assert (code, err) == (0, "")
    window = json.loads(out)["window"]
    assert (window["from"], window["to"]) == ("2023-10-20", "2026-10-20")


def test_fetch_needs_no_key_and_asks_each_source(capsys, layout, monkeypatch):
    fake = FakeSources(workbook=workbook_bytes(), history=history_bytes(), skew=skew_bytes())
    defaults = client_module.Client.__init__.__defaults__
    # The client is built by main; the fake answers through its HTTP layer.
    monkeypatch.setattr(client_module.Client.__init__, "__defaults__", (fake, lambda: NOW) + defaults[2:])
    code, out, err = run(capsys, "fetch", "--data-dir", str(layout.root))
    assert (code, err) == (0, "")
    output = json.loads(out)
    assert output["requests"] == 4
    assert [output["sources"][name]["status"] for name in ("finra", "cftc", "cboe_vix", "cboe_skew")] == [
        "new",
        "verified",
        "new",
        "new",
    ]
    assert len(fake.calls) == 4  # the fake holds no CFTC row: nothing new from the CFTC


def test_the_package_reads_no_setting():
    for path in SCRIPT_DIRECTORY.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "common.env" not in text and "import env" not in text, path


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
    window = "the window 2023-10-20 to 2026-10-20"
    assert err == f"{LABEL}: no month, week or session of {window} is fetched; run fetch first\n"


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
    save_all(DataLayout(domain / "data"), fetched_at=fetched, vix_fetched_at=fetched)
    working = tmp_path / "elsewhere"
    working.mkdir()
    before = snapshot(root)
    environment = {**os.environ, "PYTHONPATH": str(root), "PYTHONDONTWRITEBYTECODE": "1"}
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
    assert output["sources"]["cboe_vix"]["path"].startswith(str(domain / "data" / "raw" / "market"))
    assert output["sources"]["cboe_skew"]["path"].startswith(str(domain / "data" / "raw" / "market"))
    assert output["window"]["from"] == "2026-01-01"
    assert list(working.iterdir()) == []
    assert snapshot(root) == before
