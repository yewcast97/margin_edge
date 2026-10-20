"""Command line contract of ``python -m market_state_research.fundamentals.script``.

``main(argv, now, client, settings, calls)`` runs against a data directory below
``tmp_path`` with a fake clock. ``fetch`` reaches EDGAR only through the recording fake of
``workflow_support`` and EarningsCalls.dev only through the recording fake of
``fake_earningscalls``: each passed in (``client``, ``calls``), or served to the client
that ``main`` builds from a ``settings`` callable the test supplies, so no test reads the
real ``.env``. By default every call gets a provider client over the default fake
provider. Every other command gets a ``settings`` callable that fails the test if it is
ever called, and any request through urllib fails the test, so nothing reaches the
network.

Output is checked the way an agent consumes it: exit 0 with ASCII-only JSON (Markdown for
``show``) on standard output, or exit 2 with exactly one ``FUNDAMENTALS: ...`` line on
standard error and nothing on standard output. ``fetch`` and ``plan`` without tickers read
a watchlist written below ``tmp_path``; the repository-root ``watchlist.json`` is never
read. The module entry point runs ``plan`` and ``check`` in a subprocess from a copy of
``script/`` beside a copy of ``market_state_research/common``, with a ``watchlist.json`` at
the copy's root and the domain's own beside its ``script/``, so its default ``data/``
directory and watchlists are temporary as well.
"""

import inspect
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from market_state_research import common as common_package
from market_state_research.common.env import setting
from market_state_research.common.layout import DataLayout
from market_state_research.common.watchlist import default_watchlist
from market_state_research.fundamentals import script as script_package
from market_state_research.fundamentals.script import __main__ as cli_module
from market_state_research.fundamentals.script import workflow
from market_state_research.fundamentals.script.__main__ import (
    DATA_DIRECTORY,
    LABEL,
    PROGRAM,
    FundamentalsParser,
    build_parser,
    main,
)
from market_state_research.fundamentals.script.client import (
    PACING,
    USER_AGENT_MALFORMED,
    USER_AGENT_UNSET,
    EdgarClient,
)
from market_state_research.fundamentals.script.earningscalls import (
    API_KEY_MALFORMED,
    API_KEY_UNSET,
    EarningsCallsClient,
    events_url,
    transcript_url,
)
from market_state_research.fundamentals.script.earningscalls import PACING as CALLS_PACING

from .calls_support import CALL_OLD_Q, CALL_Q1, CALL_Q2
from .edgar_support import TICKER
from .fake_earningscalls import CANARY, FakeEarningsCalls, calls_client, provider
from .fake_earningscalls import status as provider_status
from .fake_edgar import FakeEdgar, RecordingSleep, status
from .support import NOW, edt, est
from .workflow_support import (
    CALLS_TIMES,
    DEFAULT_WINDOW,
    DOC_IDS,
    FETCH_TIMES,
    FETCH_URLS,
    FILINGS,
    OLD_DOCUMENTS,
    REFRESH_TIMES,
    SAMPLES,
    WINDOW,
    FetchClock,
    calls_directory,
    client,
    edgar,
    fetch,
    place,
    report_file,
    report_text,
    research,
    snapshot,
    write_report,
    write_watchlist,
)

MODULE = "market_state_research.fundamentals.script"
SCRIPT_DIRECTORY = Path(script_package.__file__).resolve().parent
COMMON_DIRECTORY = Path(common_package.__file__).resolve().parent
DOMAIN_PARTS = ("market_state_research", "fundamentals")
USER_AGENT = "Example Tester tester@example.com"  # a test value, never a private setting
COMMANDS = ("fetch", "plan", "text", "check", "render", "show")
TICKER_COMMANDS = ("text", "check", "render", "show")  # one TICKER, no window
WINDOW_ARGS = ("--from", "2025-12-01", "--to", "2026-10-08")
WINDOW_JSON = {"from": "2025-12-01", "to": "2026-10-08"}
DEFAULT_WINDOW_JSON = {"from": "2024-10-08", "to": "2026-10-08"}
SERIES = f"{TICKER}_2026-07-24_20261008T060000EDT.md"
# Every URL a first fetch of WINDOW asks the provider for, in order.
CALLS_URLS = (events_url(TICKER, 1), transcript_url(CALL_Q1.id), transcript_url(CALL_Q2.id))
SETTINGS = {"SEC_USER_AGENT": USER_AGENT, "EARNINGSCALLS_API": CANARY}


@dataclass(frozen=True)
class Outcome:
    """Exit code and captured streams of one ``main`` call."""

    code: int
    out: str
    err: str

    def text(self) -> str:
        """Standard output of a successful command."""
        assert (self.code, self.err) == (0, ""), self.err
        assert self.out.endswith("\n")
        return self.out

    def json(self) -> dict:
        """The JSON output of a successful command; non-ASCII characters arrive as ``\\u`` escapes."""
        text = self.text()
        assert text.isascii(), "JSON output must escape every non-ASCII character"
        return json.loads(text)

    def error(self) -> str:
        """The message of a failed command: exit 2, one ``FUNDAMENTALS:`` line, no traceback."""
        assert self.code == 2, self.out
        assert self.out == ""
        assert "Traceback" not in self.err
        assert self.err.startswith("FUNDAMENTALS: "), self.err
        assert self.err.endswith("\n") and self.err.count("\n") == 1, repr(self.err)
        return self.err.removeprefix("FUNDAMENTALS: ").removesuffix("\n")


@dataclass
class Settings:
    """A ``settings`` callable over ``values`` that records every name it is asked for."""

    values: dict[str, str] = field(default_factory=dict)
    asked: list[str] = field(default_factory=list)

    def __call__(self, name: str) -> str | None:
        self.asked.append(name)
        return self.values.get(name)


def unread_settings(name: str) -> str | None:
    """The ``settings`` of every command but ``fetch`` without its clients: it must never be called."""
    raise AssertionError(f"the setting {name} was read")


class Provider:
    """The ``cli`` fixture's default ``calls``: a new client over the default fake provider, its
    clock reading ``CALLS_TIMES``. Pass ``calls=None`` for the client ``main`` builds from
    ``settings``."""

    @staticmethod
    def client(fake: FakeEarningsCalls | None = None) -> EarningsCallsClient:
        return calls_client(provider() if fake is None else fake, clock=FetchClock(CALLS_TIMES))


@pytest.fixture(autouse=True)
def no_network(monkeypatch) -> None:
    """Any request through urllib fails the test: only fakes of EDGAR and EarningsCalls.dev may answer."""

    def refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError("a test reached the network")

    monkeypatch.setattr(urllib.request.OpenerDirector, "open", refuse)


@pytest.fixture
def cli(capsys, layout, clock) -> Callable[..., Outcome]:
    """Run ``main`` against the temporary data directory at the fake clock's time."""

    def run(
        *argv: str,
        now: datetime | None = None,
        client: EdgarClient | None = None,
        settings: Callable[[str], str | None] = unread_settings,
        calls: EarningsCallsClient | type[Provider] | None = Provider,
    ) -> Outcome:
        capsys.readouterr()
        code = main(
            [*argv, "--data-dir", str(layout.root)],
            now=now or clock.now,
            client=client,
            settings=settings,
            calls=Provider.client() if calls is Provider else calls,
        )
        captured = capsys.readouterr()
        return Outcome(code, captured.out, captured.err)

    return run


@pytest.fixture
def served(monkeypatch) -> FakeEdgar:
    """The fake EDGAR behind the ``EdgarClient`` that ``main`` builds from the setting itself."""
    fake = edgar()
    real = EdgarClient

    def build(user_agent: str | None) -> EdgarClient:
        return real(user_agent, fetch=fake, sleep=RecordingSleep(), clock=FetchClock())

    monkeypatch.setattr(cli_module, "EdgarClient", build)
    return fake


@pytest.fixture
def answering(monkeypatch) -> FakeEarningsCalls:
    """The fake provider behind the ``EarningsCallsClient`` that ``main`` builds from the setting."""
    fake = provider()
    real = EarningsCallsClient

    def build(api_key: str | None) -> EarningsCallsClient:
        return real(api_key, fetch=fake, sleep=RecordingSleep(), clock=FetchClock(CALLS_TIMES))

    monkeypatch.setattr(cli_module, "EarningsCallsClient", build)
    return fake


def rejected(capsys, *argv: str) -> str:
    """Run a command line argparse rejects: exit 2 with one ``FUNDAMENTALS:`` line and no usage block."""
    capsys.readouterr()
    with pytest.raises(SystemExit) as raised:
        main(list(argv), now=NOW, settings=unread_settings)
    out, err = capsys.readouterr()
    assert "usage:" not in err
    return Outcome(int(raised.value.code or 0), out, err).error()


def normalised(text: str) -> str:
    """``text`` with every whitespace run as one space: help wraps at the terminal's width."""
    return " ".join(text.split())


# --------------------------------------------------------------------------- argument parsing


def test_parser_defaults_follow_the_procedure():
    parser = build_parser()
    assert isinstance(parser, FundamentalsParser) and LABEL == FundamentalsParser.label == "FUNDAMENTALS"
    assert f"python -m {MODULE}" == PROGRAM
    for command in ("fetch", "plan"):
        parsed = parser.parse_args([command])
        assert (parsed.command, parsed.tickers) == (command, [])
        assert parsed.watchlist == default_watchlist(SCRIPT_DIRECTORY.parent)
        assert parsed.data_dir == DATA_DIRECTORY == SCRIPT_DIRECTORY.parent / "data"
        assert (parsed.window_from, parsed.window_to) == (None, None)  # main resolves them from the clock
        assert parsed.refresh is False
        listed = parser.parse_args(
            [command, "intc", "AMD", "--watchlist", "list.json", "--from", "2025-12-01", "--to=2026-10-08"]
        )
        assert (listed.tickers, listed.watchlist) == (["intc", "AMD"], Path("list.json"))
        assert (listed.window_from, listed.window_to) == (date(2025, 12, 1), date(2026, 10, 8))
        assert parser.parse_args([command, "INTC", "--refresh"]).refresh is True
    parsed = parser.parse_args(["check", "INTC"])
    assert (parsed.ticker, parsed.reports) == ("INTC", [])
    assert parser.parse_args(["check", "INTC", "a.md", "b.md"]).reports == [Path("a.md"), Path("b.md")]
    for command in TICKER_COMMANDS:
        parsed = parser.parse_args([command, "INTC", "--data-dir", "elsewhere"])
        assert (parsed.command, parsed.ticker, parsed.data_dir) == (command, "INTC", Path("elsewhere"))
        assert not hasattr(parsed, "watchlist") and not hasattr(parsed, "window_from")
        assert not hasattr(parsed, "refresh")


def test_main_reads_the_real_settings_by_default():
    parameters = inspect.signature(main).parameters
    assert list(parameters) == ["argv", "now", "client", "settings", "calls"]
    assert parameters["settings"].default is setting
    assert parameters["client"].default is parameters["calls"].default is None  # built from settings


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        (
            ["--help"],
            [
                f"usage: {PROGRAM} [-h] COMMAND ...",
                "PROCEDURE.md",
                "SEC_USER_AGENT",
                "EARNINGSCALLS_API",
                "data/raw/",
                "fetch is the one command that uses the network",
            ],
        ),
        (
            ["fetch", "--help"],
            [
                "(uses the network; needs SEC_USER_AGENT and EARNINGSCALLS_API)",
                "--watchlist PATH",
                "--refresh",
                "an EDGAR document is compared with its stored file, never rewritten (verified or changed)",
            ],
        ),
        (
            ["plan", "--help"],
            [
                "the series and the next action (read-only)",
                "--from YYYY-MM-DD",
                "--to YYYY-MM-DD",
                "--refresh",
            ],
        ),
        (["text", "--help"], ["whose text differs from its derivation", "TICKER"]),
        (["check", "--help"], ["[REPORT_PATH ...]", "default: every per-document report in reports/TICKER/"]),
        (["render", "--help"], ["write a new time series of every complete period"]),
        (["show", "--help"], ["print the action plan gives over its default window"]),
    ],
)
def test_help_exits_0_and_describes_every_command(capsys, monkeypatch, argv, expected):
    monkeypatch.setenv("COLUMNS", "200")
    with pytest.raises(SystemExit) as raised:
        main(argv, settings=unread_settings)
    assert raised.value.code == 0
    out, err = capsys.readouterr()
    assert err == ""
    for text in expected:
        assert text in normalised(out), text
    for gone in ("transcribe", "AssemblyAI", "OCR", "--rebuild", "Chrome"):
        assert gone not in out


@pytest.mark.parametrize(
    ("argv", "prog", "detail"),
    [
        pytest.param([], PROGRAM, "the following arguments are required: COMMAND", id="no-command"),
        pytest.param(["record"], PROGRAM, "argument COMMAND: invalid choice: 'record'", id="record-is-gone"),
        pytest.param(
            ["transcribe", "INTC"],
            PROGRAM,
            "argument COMMAND: invalid choice: 'transcribe'",
            id="transcribe-is-gone",
        ),
        pytest.param(["text"], f"{PROGRAM} text", "the following arguments are required: TICKER", id="text"),
        pytest.param(
            ["text", "INTC", "--rebuild"], PROGRAM, "unrecognized arguments: --rebuild", id="rebuild-is-gone"
        ),
        pytest.param(
            ["check"], f"{PROGRAM} check", "the following arguments are required: TICKER", id="check"
        ),
        pytest.param(
            ["check", "INTC", ""],
            f"{PROGRAM} check",
            "argument REPORT_PATH: expected a file path, got an empty value",
            id="check-empty-path",
        ),
        pytest.param(
            ["render"], f"{PROGRAM} render", "the following arguments are required: TICKER", id="render"
        ),
        pytest.param(["show", "INTC", "AMD"], PROGRAM, "unrecognized arguments: AMD", id="show-two-tickers"),
        pytest.param(
            ["text", "INTC", "--from", "2026-01-01"],
            PROGRAM,
            "unrecognized arguments: --from 2026-01-01",
            id="text-window",
        ),
        pytest.param(
            ["plan", "INTC", "--to", "20261008"],
            f"{PROGRAM} plan",
            "argument --to: expected a YYYY-MM-DD date, got '20261008'",
            id="basic-date",
        ),
        pytest.param(
            ["fetch", "INTC", "--api-key", "x"],
            PROGRAM,
            "unrecognized arguments: --api-key x",
            id="no-key-option",
        ),
        pytest.param(
            ["plan", "INTC", "--x\nforged"], PROGRAM, "unrecognized arguments: --x\\nforged", id="line-break"
        ),
    ],
)
def test_malformed_command_lines_exit_2_before_touching_data(capsys, layout, argv, prog, detail):
    data = ["--data-dir", str(layout.root)] if argv and argv[0] != "record" else []
    message = rejected(capsys, *argv, *data)
    assert message.startswith(f"{prog}: {detail}"), message
    assert not layout.root.exists()


# --------------------------------------------------------------------------- the window


def test_the_window_defaults_to_the_two_years_ending_today_and_may_be_truncated(cli, layout):
    served = edgar(documents=(*OLD_DOCUMENTS, *FILINGS.values()))
    answering = provider(transcripts=(CALL_Q2, CALL_Q1, CALL_OLD_Q))  # the window holds 2025-09-27 too

    output = cli("fetch", "INTC", client=client(served), calls=Provider.client(answering)).json()

    (entry,) = output["tickers"]
    assert (output["window"], entry["truncated"]) == (DEFAULT_WINDOW_JSON, True)
    assert len(entry["periods"]) == 5
    planned = cli("plan", "INTC").json()
    # The command line adds the watchlist it read: none, as a ticker was given.
    assert planned == {**workflow.plan(layout, [TICKER], NOW, DEFAULT_WINDOW), "watchlist": None}


@pytest.mark.parametrize(
    ("now", "zone", "window"),
    [
        pytest.param(
            datetime(2026, 10, 9, 3, 30, tzinfo=UTC),
            "Asia/Tokyo",
            {"from": "2024-10-08", "to": "2026-10-08"},
            id="evening",
        ),
        pytest.param(
            est(2028, 2, 29, 12, 0), "UTC", {"from": "2026-02-28", "to": "2028-02-29"}, id="leap-day"
        ),
    ],
)
def test_the_window_defaults_to_the_two_years_ending_today_in_new_york(
    cli, layout, host_time_zone, now, zone, window
):
    host_time_zone(zone)
    tomorrow = (date.fromisoformat(window["to"]) + timedelta(days=1)).isoformat()

    assert cli("plan", "INTC", now=now).json()["window"] == window
    assert (
        cli("plan", "INTC", "--to", tomorrow, now=now).error()
        == f"--to must not be after today ({window['to']})"
    )
    assert not layout.root.exists()


@pytest.mark.parametrize("command", ["fetch", "plan"])
def test_a_refused_window_exits_2_before_the_setting_watchlist_or_data_directory(
    cli, layout, tmp_path, command
):
    settings = Settings({"SEC_USER_AGENT": USER_AGENT})
    layout.root.write_bytes(b"a file where the data directory should be")
    missing = ["--watchlist", str(tmp_path / "missing.json")]

    assert cli(
        command, *missing, "--from", "2026-06-28", "--to", "2026-06-27", settings=settings
    ).error() == ("--from must not be after --to")
    assert cli(command, *missing, "--to", "2026-10-09", settings=settings).error() == (
        "--to must not be after today (2026-10-08)"
    )
    assert settings.asked == []
    assert layout.root.read_bytes() == b"a file where the data directory should be"


# --------------------------------------------------------------------------- fetch: the settings


@pytest.mark.parametrize("value", [None, ""], ids=["absent", "empty"])
def test_fetch_without_the_user_agent_refuses_before_any_request(cli, layout, tmp_path, value):
    settings = Settings({"EARNINGSCALLS_API": CANARY} if value is None else {"SEC_USER_AGENT": value})

    message = cli(
        "fetch", "--watchlist", str(tmp_path / "missing.json"), settings=settings, calls=None
    ).error()

    assert message == USER_AGENT_UNSET
    assert settings.asked == ["SEC_USER_AGENT"]
    assert not layout.root.exists()


@pytest.mark.parametrize(
    "value",
    ["private-value", "private-value@example.com", "Private Name private-value@example.com\n"],
    ids=["no-address", "no-name", "line-break"],
)
def test_a_malformed_user_agent_is_refused_without_echoing_it(cli, layout, value):
    outcome = cli("fetch", "INTC", settings=Settings({"SEC_USER_AGENT": value}))

    assert outcome.error() == USER_AGENT_MALFORMED
    assert "private" not in outcome.err.casefold()
    assert not layout.root.exists()


@pytest.mark.parametrize("value", [None, ""], ids=["absent", "empty"])
def test_fetch_without_the_key_refuses_before_any_request(cli, layout, tmp_path, served, answering, value):
    settings = Settings(
        {"SEC_USER_AGENT": USER_AGENT} if value is None else {**SETTINGS, "EARNINGSCALLS_API": value}
    )

    message = cli(
        "fetch", "--watchlist", str(tmp_path / "missing.json"), settings=settings, calls=None
    ).error()

    assert message == API_KEY_UNSET
    assert settings.asked == ["SEC_USER_AGENT", "EARNINGSCALLS_API"]
    assert (served.calls, answering.calls) == ([], [])
    assert not layout.root.exists()


@pytest.mark.parametrize(
    "value",
    [f"{CANARY} private", f"{CANARY}\n", f"{CANARY}é"],
    ids=["space", "line-break", "non-ascii"],
)
def test_a_malformed_key_is_refused_before_any_request_without_echoing_it(
    cli, layout, served, answering, value
):
    outcome = cli("fetch", "INTC", settings=Settings({**SETTINGS, "EARNINGSCALLS_API": value}), calls=None)

    assert outcome.error() == API_KEY_MALFORMED
    assert CANARY not in outcome.err and "private" not in outcome.err
    assert (served.calls, answering.calls) == ([], [])
    assert not layout.root.exists()


def test_fetch_builds_its_clients_from_the_settings_and_prints_only_that_they_are_set(
    cli, layout, served, answering
):
    settings = Settings({**SETTINGS, "OTHER": "unused"})

    outcome = cli("fetch", "intc", *WINDOW_ARGS, settings=settings, calls=None)

    output = outcome.json()
    assert (output["requests"], output["user_agent"], output["window"]) == (
        len(FETCH_URLS),
        "set",
        WINDOW_JSON,
    )
    assert (output["transcript_requests"], output["api_key"], output["stopped"]) == (3, "set", None)
    assert settings.asked == ["SEC_USER_AGENT", "EARNINGSCALLS_API"]
    assert served.urls == list(FETCH_URLS)
    assert answering.urls == list(CALLS_URLS)
    assert [headers["User-Agent"] for _, headers, _ in served.calls] == [USER_AGENT] * len(FETCH_URLS)
    assert [headers["X-API-Key"] for _, headers, _ in answering.calls] == [CANARY] * 3
    for secret in ("tester@example.com", CANARY):
        assert secret not in outcome.out + outcome.err
        assert all(
            secret.encode() not in path.read_bytes() for path in layout.root.rglob("*") if path.is_file()
        )


def test_fetch_reads_the_settings_through_common_env(cli, tmp_path, monkeypatch, served, answering):
    monkeypatch.delenv("SEC_USER_AGENT", raising=False)
    monkeypatch.delenv("EARNINGSCALLS_API", raising=False)
    env = tmp_path / "settings.env"
    env.write_text(
        f'# personal settings\nexport SEC_USER_AGENT="{USER_AGENT}"\nEARNINGSCALLS_API={CANARY}\n',
        encoding="utf-8",
    )

    output = cli("fetch", "INTC", *WINDOW_ARGS, settings=lambda name: setting(name, env), calls=None).json()

    assert (output["user_agent"], output["api_key"]) == ("set", "set")
    assert [headers["X-API-Key"] for _, headers, _ in answering.calls] == [CANARY] * 3


def test_fetch_with_its_clients_never_reads_the_settings_and_paces_its_requests(cli, layout):
    sleep, calls_sleep = RecordingSleep(), RecordingSleep()
    provided = calls_client(provider(), calls_sleep, clock=FetchClock(CALLS_TIMES))

    output = cli("fetch", "INTC", *WINDOW_ARGS, client=client(edgar(), sleep), calls=provided).json()

    assert (output["requests"], output["transcript_requests"]) == (len(FETCH_URLS), 3)
    assert sleep.calls == [PACING] * 9
    assert calls_sleep.calls == [CALLS_PACING] * 2


@pytest.mark.parametrize("command", [command for command in COMMANDS if command != "fetch"])
def test_no_other_command_reads_a_setting(cli, layout, command):
    research(layout)
    settings = Settings(SETTINGS)

    outcome = cli(command, "INTC", settings=settings)

    assert outcome.code == 0, outcome.err
    assert settings.asked == []


# --------------------------------------------------------------------------- fetch: output and failures


def test_an_edgar_refusal_exits_2_with_one_line_and_keeps_the_files_written_before_it(cli, layout):
    served = edgar()
    failing = FETCH_URLS[6]  # the second 10-Q
    served.responses[failing] = status(503, "Service Unavailable")

    message = cli("fetch", "INTC", *WINDOW_ARGS, client=client(served)).error()

    assert (
        message
        == f"GET {failing}: HTTP 503 Service Unavailable; EDGAR is unavailable: wait and run fetch again"
    )
    assert (layout.raw(TICKER) / "edgar/10-K_2025-12-27_0000050863-26-000012/intc-20251227.htm").is_file()


def test_a_provider_refusal_exits_2_with_one_line_and_keeps_edgars_files(cli, layout):
    refusing = provider()
    refusing.responses[CALLS_URLS[0]] = provider_status(401, "Unauthorized")

    message = cli(
        "fetch", "INTC", *WINDOW_ARGS, client=client(edgar()), calls=Provider.client(refusing)
    ).error()

    assert message == (
        f"GET {CALLS_URLS[0]}: HTTP 401 Unauthorized; EarningsCalls.dev refused the key: "
        "check EARNINGSCALLS_API"
    )
    assert (layout.raw(TICKER) / "edgar/10-K_2025-12-27_0000050863-26-000012/intc-20251227.htm").is_file()
    assert not calls_directory(layout).exists()


def test_the_providers_request_limit_exits_0_with_the_run_stopped(cli, layout):
    limited = provider()
    limited.responses[CALLS_URLS[0]] = provider_status(429, "Too Many Requests", retry_after="60")

    output = cli("fetch", "INTC", *WINDOW_ARGS, client=client(edgar()), calls=Provider.client(limited)).json()

    reason = (
        f"GET {CALLS_URLS[0]}: HTTP 429; EarningsCalls.dev's request limit is reached (the key's 3,000 "
        "requests a month or 20 a minute); retry after 60 seconds; run fetch again once it resets"
    )
    assert output["stopped"] == {"ticker": TICKER, "reason": reason}
    assert output["tickers"][0]["calls"]["status"] == "stopped"
    assert cli("plan", "INTC", *WINDOW_ARGS).json()["tickers"][0]["action"] == "fetch"


def test_refresh_reaches_fetch_and_plan(cli, layout):
    cli("fetch", "INTC", *WINDOW_ARGS, client=client(edgar()))
    served, answering = edgar(), provider()

    refreshed = cli(
        "fetch",
        "INTC",
        *WINDOW_ARGS,
        "--refresh",
        client=client(served),
        calls=calls_client(answering, clock=FetchClock(REFRESH_TIMES)),
    ).json()

    assert refreshed["refresh"] is True
    assert (served.urls, answering.urls) == (list(FETCH_URLS), list(CALLS_URLS))
    (entry,) = refreshed["tickers"]
    assert {period["filing"]["status"] for period in entry["periods"]} == {"verified"}
    assert [item["status"] for item in entry["calls"]["transcripts"]] == ["verified", "verified"]
    planned = cli("plan", "INTC", *WINDOW_ARGS, "--refresh").json()
    assert planned["refresh"] is True
    (ticker,) = planned["tickers"]
    assert (ticker["action"], ticker["reason"]) == ("fetch", workflow.REFRESH_REASON)
    unrefreshed = cli("plan", "INTC", *WINDOW_ARGS).json()
    assert (unrefreshed["refresh"], unrefreshed["tickers"][0]["action"]) == (False, "text")


def test_fetch_and_plan_without_tickers_take_the_stock_section_of_the_watchlist(cli, layout, tmp_path):
    watchlist = str(write_watchlist(tmp_path, ("intc",), ("SPX",)))

    fetched = cli("fetch", "--watchlist", watchlist, *WINDOW_ARGS, client=client(edgar())).json()
    planned = cli("plan", "--watchlist", watchlist, *WINDOW_ARGS).json()

    assert [entry["ticker"] for entry in fetched["tickers"]] == [TICKER]
    assert [entry["ticker"] for entry in planned["tickers"]] == [TICKER]


def test_a_missing_watchlist_exits_2(cli, layout, tmp_path):
    missing = tmp_path / "missing.json"

    assert cli("plan", "--watchlist", str(missing)).error() == f"{missing}: file not found"


# --------------------------------------------------------------------------- the pipeline


def test_the_pipeline_end_to_end_through_the_command_line(cli, layout, clock):
    fetched = cli("fetch", "INTC", *WINDOW_ARGS, client=client(edgar())).json()
    assert fetched["tickers"][0]["status"] == "fetched"
    assert fetched["tickers"][0]["calls"]["status"] == "fetched"
    assert cli("plan", "INTC", *WINDOW_ARGS).json()["tickers"][0]["action"] == "text"

    texts = cli("text", "INTC").json()
    assert {document["status"] for document in texts["documents"]} == {"published"}
    assert cli("plan", "INTC", *WINDOW_ARGS).json()["tickers"][0]["action"] == "research"

    for role in SAMPLES:
        write_report(layout, role)
    checked = cli("check", "INTC").json()
    assert [report["valid"] for report in checked["reports"]] == [True] * len(SAMPLES)
    assert cli("plan", "INTC", *WINDOW_ARGS).json()["tickers"][0]["action"] == "render"

    rendered = cli("render", "INTC").json()
    assert rendered["path"] == str(layout.reports(TICKER) / SERIES)
    later = clock.tick(60)
    planned = cli("plan", "INTC", *WINDOW_ARGS, now=later).json()["tickers"][0]
    assert (planned["action"], planned["series"]["status"]) == ("reuse", "fresh")

    again = cli(
        "fetch", "INTC", *WINDOW_ARGS, client=client(edgar()), calls=Provider.client(FakeEarningsCalls())
    )
    assert again.json()["transcript_requests"] == 0  # nothing due: the provider is not asked

    shown = cli("show", "INTC", now=later).text()
    assert shown.startswith("Action: fetch (default window 2024-10-08 to 2026-10-08): the 10-K ")
    assert f"Series: {layout.reports(TICKER) / SERIES} (fresh)." in shown
    assert "\n\n# INTC · Issuer disclosures · as of 2026-07-24\n" in shown


def test_check_with_problems_exits_0_and_lists_them(cli, layout):
    research(layout)
    write_report(
        layout,
        "ten_k",
        report_text(DOC_IDS["ten_k"], upstream_shortage=["Not a sentence of the 10-K at all."]),
    )

    output = cli("check", "INTC", str(report_file(layout, "ten_k"))).json()

    assert output == {
        "ticker": TICKER,
        "reports": [
            {
                "path": str(report_file(layout, "ten_k")),
                "document": DOC_IDS["ten_k"],
                "valid": False,
                "problems": [{"line": 5, "message": "quote not found in the document's derived text"}],
            }
        ],
    }


def test_render_refusals_exit_2_with_one_line(cli, layout):
    fetch(layout)

    assert cli("render", "INTC").error() == (
        f"{TICKER}: no period is complete: every document of a period needs a report that passes check"
    )
    research(layout)
    assert cli("render", "INTC").code == 0
    assert cli("render", "INTC").error().endswith(f"{SERIES} already exists; refusing to overwrite it")


def test_an_invalid_raw_file_refuses_text_check_and_render(cli, layout):
    research(layout)
    place(calls_directory(layout) / "stray.pdf", b"%PDF-1.6\n")

    for command in ("text", "check", "render"):
        message = cli(command, "INTC").error()
        assert message.startswith(f"{TICKER}: 1 file in raw/ failed validation; first: ")
    assert cli("plan", "INTC", *WINDOW_ARGS).json()["tickers"][0]["action"] == "fetch"
    assert "Invalid file: " in cli("show", "INTC").text()


def test_json_output_escapes_non_ascii_values(cli, layout, tmp_path):
    research(layout)
    draft = place(tmp_path / "résumé.md", "# résumé\n")

    output = cli("check", "INTC", str(draft)).json()

    assert output["reports"][0]["document"] == "résumé"


@pytest.mark.parametrize("command", TICKER_COMMANDS)
@pytest.mark.parametrize("ticker", ["../INTC", "INTC/x", "ÎNTC"])
def test_unsafe_tickers_exit_2_before_any_write(cli, layout, command, ticker):
    assert cli(command, ticker).error() == "ticker must be a US symbol without path or query characters"
    assert not layout.root.exists()


@pytest.mark.parametrize("command", COMMANDS)
def test_a_data_dir_that_is_a_file_exits_2_before_any_work(cli, layout, command):
    layout.root.parent.mkdir(parents=True, exist_ok=True)
    layout.root.write_bytes(b"not a directory")
    argv = [command, "INTC"]

    assert cli(*argv, client=client(edgar())).error() == f"{layout.root} is not a directory"


def test_a_clock_without_a_time_zone_exits_2(cli):
    assert cli("plan", "INTC", now=datetime(2026, 10, 8, 6, 0)).error().startswith("now")


def test_plan_prints_the_clock_in_new_york_time(cli):
    assert (
        cli("plan", "INTC", now=edt(2026, 10, 8, 6, 0)).json()["generated_at"] == "2026-10-08T06:00:00-04:00"
    )


def test_main_reads_the_system_clock_when_now_is_omitted(capsys, layout):
    code = main(["plan", "INTC", "--data-dir", str(layout.root)], settings=unread_settings)

    out, _ = capsys.readouterr()
    assert code == 0
    generated = datetime.fromisoformat(json.loads(out)["generated_at"])
    assert abs(generated - datetime.now(UTC)) < timedelta(minutes=5)


# --------------------------------------------------------------------------- module entry point


def run_module(root: Path, working: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    environment = {**os.environ, "PYTHONPATH": str(root), "PYTHONDONTWRITEBYTECODE": "1"}
    return subprocess.run(
        [sys.executable, "-m", MODULE, *arguments],
        cwd=working,
        env=environment,
        capture_output=True,
        encoding="utf-8",
        timeout=120,
        check=False,
    )


def test_module_entry_point_uses_its_own_data_directory_and_watchlist(tmp_path):
    root = (tmp_path / "checkout").resolve()
    domain = root.joinpath(*DOMAIN_PARTS)
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc")
    shutil.copytree(SCRIPT_DIRECTORY, domain / "script", ignore=ignore)
    shutil.copytree(COMMON_DIRECTORY, root / "market_state_research" / "common", ignore=ignore)
    data = DataLayout(domain / "data")
    # The subprocess runs on the real clock: the raw files are written just before it, through
    # the public path, so no stored time is later than the real now.
    start = datetime.now(UTC) - timedelta(minutes=10)
    fetch(
        data,
        times=tuple(start + timedelta(seconds=second) for second in range(len(FETCH_TIMES))),
        calls_times=tuple(start + timedelta(seconds=30 + second) for second in range(len(CALLS_TIMES))),
        now=start,
    )
    (root / "watchlist.json").write_text('{"stock": ["amd"], "index": ["SPX"]}', encoding="utf-8")
    # The domain's own watchlist overrides the repository-root one.
    (domain / "watchlist.json").write_text('{"stock": ["intc"], "index": ["SPX"]}', encoding="utf-8")
    working = tmp_path / "elsewhere"
    working.mkdir()
    before = snapshot(root)

    planned = run_module(root, working, "plan", *WINDOW_ARGS)
    assert (planned.returncode, planned.stderr) == (0, "")
    assert planned.stdout.isascii()
    assert json.loads(planned.stdout)["watchlist"] == str(domain / "watchlist.json")
    (entry,) = json.loads(planned.stdout)["tickers"]
    assert (entry["ticker"], entry["action"]) == (TICKER, "text")
    assert [period["period"] for period in entry["periods"]] == ["2025-12-27", "2026-03-28", "2026-06-27"]

    checked = run_module(root, working, "check", "INTC")
    assert (checked.returncode, checked.stderr, json.loads(checked.stdout)) == (
        0,
        "",
        {"ticker": TICKER, "reports": []},
    )

    refused = run_module(root, working, "check", "INTC", str(tmp_path / "missing.md"))
    assert (refused.returncode, refused.stderr) == (0, "")
    assert json.loads(refused.stdout)["reports"][0]["problems"][0]["message"] == (
        "the report cannot be read: file not found"
    )

    future = run_module(root, working, "plan", "--to", "2999-01-01")
    assert (future.returncode, future.stdout) == (2, "")
    assert re.fullmatch(
        r"FUNDAMENTALS: --to must not be after today \([0-9]{4}-[0-9]{2}-[0-9]{2}\)\n", future.stderr
    )

    assert list(working.iterdir()) == []
    assert snapshot(root) == before  # plan and check write nothing
    assert WINDOW.start == date(2025, 12, 1)
