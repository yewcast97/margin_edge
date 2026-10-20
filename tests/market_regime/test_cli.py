"""Command line contract of ``python -m market_state_research.market_regime.script``."""

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
from market_state_research.common.watchlist import WATCHLIST_PATH
from market_state_research.market_regime import script as script_package
from market_state_research.market_regime.script import client as client_module
from market_state_research.market_regime.script import tiingo as tiingo_module
from market_state_research.market_regime.script.__main__ import DOMAIN_DIRECTORY, build_parser, main
from market_state_research.market_regime.script.store import DATA_DIRECTORY

from .fake_eodhd import FakeEodhd
from .fake_tiingo import FakeTiingo
from .support import AS_OF, CANARY, NOW, TICKER, TIINGO_CANARY, save, standard

MODULE = "market_state_research.market_regime.script"
SCRIPT_DIRECTORY = Path(script_package.__file__).resolve().parent
COMMON_DIRECTORY = Path(common_package.__file__).resolve().parent


class Settings:
    """Records every setting asked for and answers with the CANARY keys."""

    def __init__(self, **values: str | None) -> None:
        self.asked: list[str] = []
        self.values = {"EODHD_API": CANARY, "TIINGO_API": TIINGO_CANARY, **values}

    def __call__(self, name: str) -> str | None:
        self.asked.append(name)
        return self.values.get(name)


def run(capsys, *argv, **options):
    code = main(list(argv), **{"now": NOW, **options})
    out, err = capsys.readouterr()
    return code, out, err


def test_parse_errors_are_one_labelled_line(capsys):
    with pytest.raises(SystemExit) as exit_info:
        main(["plan", "--lookback", "0"], now=NOW)
    out, err = capsys.readouterr()
    assert (exit_info.value.code, out) == (2, "")
    assert re.fullmatch(
        r"REGIME: .*: argument --lookback: expected a positive whole number of sessions, got '0'\n", err
    )


def test_the_default_data_directory_and_watchlist_are_the_domains():
    assert SCRIPT_DIRECTORY.parent / "data" == DATA_DIRECTORY
    assert SCRIPT_DIRECTORY.parent == DOMAIN_DIRECTORY
    own = DOMAIN_DIRECTORY / "watchlist.json"
    expected = own if own.is_file() else WATCHLIST_PATH
    assert build_parser().parse_args(["plan"]).watchlist == expected


@pytest.mark.parametrize("command", [["plan", TICKER], ["record", TICKER, "--partial"], ["show", TICKER]])
def test_offline_commands_read_no_setting(capsys, layout, command):
    save(layout, standard(AS_OF))
    settings = Settings()
    code, out, err = run(
        capsys, *command, "--data-dir", str(layout.root), "--lookback", "1", settings=settings
    )
    assert (code, err, settings.asked) == (0, "", [])


def test_fetch_never_prints_the_keys(capsys, layout, watchlist, monkeypatch):
    settings = Settings()
    fake, tiingo = FakeEodhd(statuses={1: 401}), FakeTiingo()
    # The clients are built from the settings; the fakes answer through the modules' HTTP layers.
    for client_class, stand_in in ((client_module.EodhdClient, fake), (tiingo_module.TiingoClient, tiingo)):
        defaults = client_class.__init__.__defaults__
        monkeypatch.setattr(client_class.__init__, "__defaults__", (stand_in,) + defaults[1:])
    code, out, err = run(
        capsys,
        "fetch",
        "--data-dir",
        str(layout.root),
        "--watchlist",
        str(watchlist()),
        settings=settings,
    )
    assert settings.asked == ["EODHD_API", "TIINGO_API"]
    assert (code, out) == (2, "")
    assert err.startswith("REGIME: GET https://eodhd.com/api/mp/unicornbay/options/contracts?")
    assert "check EODHD_API" in err and CANARY not in err and TIINGO_CANARY not in err
    assert (fake.tokens, tiingo.tokens) == ([CANARY], [TIINGO_CANARY])
    assert all(TIINGO_CANARY not in call for call in tiingo.calls)
    files = [path for path in layout.root.rglob("*") if path.is_file()]
    # Tiingo answered 404 for TEST: its empty prices file, fetched on the real clock, is the only file.
    assert [path.name[:18] for path in files] == ["prices_2026-10-16_"]
    for path in files:
        data = path.read_bytes()
        assert CANARY.encode() not in data and TIINGO_CANARY.encode() not in data


@pytest.mark.parametrize(
    ("values", "message"),
    [
        ({"EODHD_API": None}, 'EODHD_API is not set; add EODHD_API="..." to the repository-root .env'),
        ({"TIINGO_API": None}, 'TIINGO_API is not set; add TIINGO_API="..." to the repository-root .env'),
        ({"TIINGO_API": "bad key!"}, "TIINGO_API must be 8 to 200 ASCII letters"),
    ],
)
def test_fetch_without_both_keys_sends_nothing(capsys, layout, values, message):
    code, out, err = run(
        capsys,
        "fetch",
        "--data-dir",
        str(layout.root),
        "--watchlist",
        "missing.json",
        settings=Settings(**values),
    )
    assert (code, out) == (2, "")
    assert err.startswith(f"REGIME: {message}") and "bad key!" not in err
    assert not layout.root.exists()


def test_fetch_output_says_the_keys_are_set(capsys, layout):
    fake = FakeEodhd(statuses={1: 402})
    code, out, err = run(
        capsys,
        "fetch",
        TICKER,
        "--data-dir",
        str(layout.root),
        client=fake.client(),
        tiingo=FakeTiingo().client(),
    )
    assert (code, err) == (0, "")
    output = json.loads(out)
    assert (output["eodhd_key"], output["tiingo_key"], output["watchlist"]) == ("set", "set", None)
    assert "quota" in output["stopped"]["reason"]
    assert output["tickers"][0]["prices"]["status"] == "empty"


def test_plan_names_the_watchlist_it_read(capsys, layout, watchlist):
    path = watchlist()
    code, out, err = run(capsys, "plan", "--data-dir", str(layout.root), "--watchlist", str(path))
    assert (code, err) == (0, "")
    assert json.loads(out)["watchlist"] == str(path)


def test_a_file_as_data_directory_is_refused(capsys, tmp_path):
    target = tmp_path / "file"
    target.write_text("x")
    code, out, err = run(capsys, "plan", TICKER, "--data-dir", str(target))
    assert (code, err) == (2, f"REGIME: {target} is not a directory\n")


def snapshot(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)): path.read_bytes() for path in sorted(root.rglob("*")) if path.is_file()
    }


def test_module_entry_point_uses_its_own_data_directory_and_watchlist(tmp_path):
    root = (tmp_path / "checkout").resolve()
    domain = root / "market_state_research" / "market_regime"
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc")
    shutil.copytree(SCRIPT_DIRECTORY, domain / "script", ignore=ignore)
    shutil.copytree(COMMON_DIRECTORY, root / "market_state_research" / "common", ignore=ignore)
    (root / "market_state_research" / "__init__.py").write_text("")
    (root / "watchlist.json").write_text('{"stock": ["root"], "index": []}', encoding="utf-8")
    # The domain's own watchlist overrides the repository-root one.
    (domain / "watchlist.json").write_text('{"stock": ["test"], "index": []}', encoding="utf-8")
    # The subprocess runs on the real clock: the chain is saved as fetched a minute ago.
    now = datetime.now(UTC)
    from market_state_research.common.sessions import completed_session

    session = completed_session(now)
    save(DataLayout(domain / "data"), standard(session, fetched_at=now - timedelta(minutes=1)))
    working = tmp_path / "elsewhere"
    working.mkdir()
    before = snapshot(root)
    environment = {**os.environ, "PYTHONPATH": str(root), "PYTHONDONTWRITEBYTECODE": "1", "EODHD_API": ""}
    result = subprocess.run(
        [sys.executable, "-m", MODULE, "plan", "--lookback", "1"],
        cwd=working,
        env=environment,
        capture_output=True,
        encoding="utf-8",
        timeout=120,
        check=False,
    )
    assert (result.returncode, result.stderr) == (0, "")
    output = json.loads(result.stdout)
    (entry,) = output["tickers"]
    assert (entry["ticker"], entry["missing_sessions"], entry["action"]) == ("TEST", [], "fetch")
    assert entry["prices"]["status"] == "missing"
    assert output["watchlist"] == str(domain / "watchlist.json")
    assert list(working.iterdir()) == []
    assert snapshot(root) == before
