"""common/cli.py: argument types, the labelled one-line error format and exit status 2.

Domain command-line tests cover each command; these cover the shared conventions
with small parsers built here, labelled ``EXAMPLE`` and ``OTHER``.
"""

import argparse
import sys
from datetime import date
from pathlib import Path
from typing import ClassVar, get_type_hints

import pytest

from market_state_research.common.cli import (
    Parser,
    calendar_date,
    directory_path,
    fail,
    file_path,
    positive_integer,
)

PROGRAM = "python -m example"


class ExampleParser(Parser):
    label = "EXAMPLE"


class OtherParser(Parser):
    label = "OTHER"


def build(parser_class: type[Parser] = ExampleParser) -> Parser:
    parser = parser_class(prog=PROGRAM, description="An example command line.")
    parser.add_argument("--lookback", type=positive_integer("sessions"), default=50, metavar="N")
    parser.add_argument("--data-dir", type=directory_path, metavar="PATH")
    parser.add_argument("--as-of", type=calendar_date, metavar="YYYY-MM-DD")
    commands = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")
    show = commands.add_parser("show")
    show.add_argument("ticker", metavar="TICKER")
    show.add_argument("--pages", type=positive_integer("pages"), default=1)
    show.add_argument("--list", type=file_path, metavar="PATH")
    show.add_argument("--from", dest="start", type=calendar_date, metavar="YYYY-MM-DD")
    return parser


def rejected(capsys, *argv: str, parser_class: type[Parser] = ExampleParser) -> str:
    """Parse a command line the parser refuses: exit 2, one labelled line, no usage block."""
    prefix = f"{parser_class.label}: "
    capsys.readouterr()
    with pytest.raises(SystemExit) as raised:
        build(parser_class).parse_args(list(argv))
    out, err = capsys.readouterr()
    assert raised.value.code == 2
    assert out == ""
    assert "usage:" not in err
    assert err.startswith(prefix) and err.endswith("\n")
    assert err.count("\n") == 1, f"expected a single line on stderr, got {err!r}"
    return err.removeprefix(prefix).removesuffix("\n")


# --- positive_integer ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "value"),
    [("1", 1), ("2", 2), ("50", 50), ("007", 7), ("10000000000000000000000", 10**22)],
    ids=["one", "two", "fifty", "leading-zeros", "beyond-64-bits"],
)
def test_positive_integer_reads_ascii_digits(text, value):
    parsed = positive_integer("sessions")(text)

    assert type(parsed) is int
    assert parsed == value


@pytest.mark.parametrize(
    "text",
    [
        pytest.param("0", id="zero"),
        pytest.param("00", id="double-zero"),
        pytest.param("-3", id="negative"),
        pytest.param("abc", id="word"),
        pytest.param("1.5", id="fraction"),
        pytest.param("1e3", id="exponent"),
        pytest.param("", id="empty"),
        pytest.param(" 5", id="leading-space"),
        pytest.param("5 ", id="trailing-space"),
        pytest.param("+5", id="plus-sign"),
        pytest.param("1_000", id="digit-separator"),
        pytest.param("1,000", id="thousands-separator"),
        pytest.param("\uff15", id="fullwidth-digit"),
        pytest.param("\u0665", id="arabic-indic-digit"),
        pytest.param("\u00b2", id="superscript-two"),
        pytest.param("5\n", id="line-break"),
    ],
)
def test_positive_integer_rejects_anything_but_a_positive_ascii_whole_number(text):
    with pytest.raises(argparse.ArgumentTypeError) as caught:
        positive_integer("sessions")(text)
    assert str(caught.value) == f"expected a positive whole number of sessions, got {text!r}"


def test_positive_integer_names_what_is_counted():
    with pytest.raises(argparse.ArgumentTypeError) as caught:
        positive_integer("pages")("0")
    assert str(caught.value) == "expected a positive whole number of pages, got '0'"
    assert positive_integer("pages")("3") == 3


def test_a_value_beyond_the_integer_digit_limit_gets_the_same_message():
    limit = sys.get_int_max_str_digits()
    if limit == 0:
        pytest.skip("the interpreter converts integer strings of any length")
    assert positive_integer("sessions")("9" * limit) == int("9" * limit)
    text = "9" * (limit + 1)
    with pytest.raises(argparse.ArgumentTypeError) as caught:
        positive_integer("sessions")(text)
    assert str(caught.value) == f"expected a positive whole number of sessions, got {text!r}"
    assert caught.value.__cause__ is None and caught.value.__suppress_context__


# --- calendar_date ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("2026-10-09", date(2026, 10, 9)),
        ("2024-02-29", date(2024, 2, 29)),
        ("0001-01-01", date(1, 1, 1)),
        ("9999-12-31", date(9999, 12, 31)),
    ],
    ids=["ordinary", "leap-day", "earliest", "latest"],
)
def test_calendar_date_reads_a_yyyy_mm_dd_date_written_with_ascii_digits(text, value):
    parsed = calendar_date(text)

    assert type(parsed) is date
    assert parsed == value


@pytest.mark.parametrize(
    "text",
    [
        pytest.param("2026-13-01", id="month-thirteen"),
        pytest.param("2026-00-09", id="month-zero"),
        pytest.param("2026-10-00", id="day-zero"),
        pytest.param("2026-02-30", id="thirtieth-of-february"),
        pytest.param("2025-02-29", id="leap-day-of-a-common-year"),
        pytest.param("2026-04-31", id="thirty-first-of-april"),
        pytest.param("0000-01-01", id="year-zero"),
        pytest.param("20261009", id="basic-format"),
        pytest.param("2026-W41-5", id="week-date"),
        pytest.param("2026-282", id="ordinal-date"),
        pytest.param("2026-1-09", id="one-digit-month"),
        pytest.param("2026-10-9", id="one-digit-day"),
        pytest.param("26-10-09", id="two-digit-year"),
        pytest.param("12026-10-09", id="five-digit-year"),
        pytest.param("", id="empty"),
        pytest.param(" 2026-10-09", id="leading-space"),
        pytest.param("2026-10-09 ", id="trailing-space"),
        pytest.param("2026-10-09\n", id="line-break"),
        pytest.param("2026-10-09T00:00", id="with-a-time"),
        pytest.param("2026-10-09 00:00", id="with-a-spaced-time"),
        pytest.param("2026/10/09", id="slashes"),
        pytest.param("2026.10.09", id="dots"),
        pytest.param("2026\u201010\u201009", id="unicode-hyphens"),
        pytest.param("+2026-10-09", id="plus-sign"),
        pytest.param("-2026-10-09", id="minus-sign"),
        pytest.param("\uff12\uff10\uff12\uff16-\uff11\uff10-\uff10\uff19", id="fullwidth-digits"),
        pytest.param("2026-10-0\uff19", id="one-fullwidth-digit"),
        pytest.param("\u0662\u0660\u0662\u0666-\u0661\u0660-\u0660\u0669", id="arabic-indic-digits"),
        pytest.param("yyyy-mm-dd", id="placeholder"),
    ],
)
def test_calendar_date_rejects_anything_but_an_existing_yyyy_mm_dd_ascii_date(text):
    with pytest.raises(argparse.ArgumentTypeError) as caught:
        calendar_date(text)
    assert str(caught.value) == f"expected a YYYY-MM-DD date, got {text!r}"


def test_a_well_formed_date_that_does_not_exist_gets_the_same_message_without_its_cause():
    with pytest.raises(argparse.ArgumentTypeError) as caught:
        calendar_date("2026-02-30")
    assert str(caught.value) == "expected a YYYY-MM-DD date, got '2026-02-30'"
    assert caught.value.__cause__ is None and caught.value.__suppress_context__


# --- directory_path -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text", ["data", ".", "/tmp/my data", " "], ids=["relative", "dot", "spaces", "space"]
)
def test_directory_path_keeps_any_non_empty_path(text):
    assert directory_path(text) == Path(text)


def test_directory_path_refuses_an_empty_value_rather_than_reading_the_working_directory():
    with pytest.raises(argparse.ArgumentTypeError) as caught:
        directory_path("")
    assert str(caught.value) == "expected a directory path, got an empty value"


# --- file_path ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    ["watchlist.json", "/tmp/my lists/watchlist.json", "../watchlist.json", " "],
    ids=["relative", "spaces", "parent", "space"],
)
def test_file_path_keeps_any_non_empty_path(text):
    assert file_path(text) == Path(text)


def test_file_path_refuses_an_empty_value_rather_than_reading_the_working_directory():
    with pytest.raises(argparse.ArgumentTypeError) as caught:
        file_path("")
    assert str(caught.value) == "expected a file path, got an empty value"


# --- Parser -------------------------------------------------------------------------------------


def test_parser_accepts_a_valid_command_line():
    args = build().parse_args(
        [
            "--lookback",
            "5",
            "--data-dir",
            "data",
            "--as-of",
            "2026-10-08",
            "show",
            "SPX",
            "--pages",
            "2",
            "--list",
            "list.json",
            "--from=2024-10-08",
        ]
    )

    assert (
        args.lookback,
        args.data_dir,
        args.as_of,
        args.command,
        args.ticker,
        args.pages,
        args.list,
        args.start,
    ) == (5, Path("data"), date(2026, 10, 8), "show", "SPX", 2, Path("list.json"), date(2024, 10, 8))


def test_date_options_are_absent_unless_given():
    args = build().parse_args(["show", "SPX"])

    assert (args.as_of, args.start) == (None, None)


@pytest.mark.parametrize(
    ("argv", "message"),
    [
        pytest.param(
            ["--lookback", "0", "show", "SPX"],
            f"{PROGRAM}: argument --lookback: expected a positive whole number of sessions, got '0'",
            id="lookback-zero",
        ),
        pytest.param(
            ["--lookback=-3", "show", "SPX"],
            f"{PROGRAM}: argument --lookback: expected a positive whole number of sessions, got '-3'",
            id="lookback-negative-inline",
        ),
        pytest.param(
            ["--data-dir", "", "show", "SPX"],
            f"{PROGRAM}: argument --data-dir: expected a directory path, got an empty value",
            id="empty-data-dir",
        ),
        pytest.param(
            ["--as-of", "2026-13-01", "show", "SPX"],
            f"{PROGRAM}: argument --as-of: expected a YYYY-MM-DD date, got '2026-13-01'",
            id="date-that-does-not-exist",
        ),
        pytest.param(
            ["--as-of=20261009", "show", "SPX"],
            f"{PROGRAM}: argument --as-of: expected a YYYY-MM-DD date, got '20261009'",
            id="date-basic-format-inline",
        ),
        pytest.param(
            ["--as-of", "", "show", "SPX"],
            f"{PROGRAM}: argument --as-of: expected a YYYY-MM-DD date, got ''",
            id="empty-date",
        ),
        pytest.param(
            ["--as-of", "2026-10-09\nforged", "show", "SPX"],
            f"{PROGRAM}: argument --as-of: expected a YYYY-MM-DD date, got '2026-10-09\\nforged'",
            id="date-line-break-escaped",
        ),
        pytest.param(
            ["--as-of", "show", "SPX"],
            f"{PROGRAM}: argument --as-of: expected a YYYY-MM-DD date, got 'show'",
            id="date-option-swallows-the-command",
        ),
        pytest.param([], f"{PROGRAM}: the following arguments are required: COMMAND", id="no-command"),
        pytest.param(
            ["show"],
            f"{PROGRAM} show: the following arguments are required: TICKER",
            id="subcommand-names-itself",
        ),
        pytest.param(
            ["show", "SPX", "--pages", "0"],
            f"{PROGRAM} show: argument --pages: expected a positive whole number of pages, got '0'",
            id="subcommand-count",
        ),
        pytest.param(
            ["show", "SPX", "--list", ""],
            f"{PROGRAM} show: argument --list: expected a file path, got an empty value",
            id="empty-file-path",
        ),
        pytest.param(
            ["show", "SPX", "--from", "2025-02-29"],
            f"{PROGRAM} show: argument --from: expected a YYYY-MM-DD date, got '2025-02-29'",
            id="subcommand-date",
        ),
        pytest.param(
            ["show", "SPX", "--from"],
            f"{PROGRAM} show: argument --from: expected one argument",
            id="date-without-value",
        ),
        pytest.param(
            ["show", "SPX", "--list"],
            f"{PROGRAM} show: argument --list: expected one argument",
            id="file-path-without-value",
        ),
        pytest.param(
            ["show", "SPX", "--x\nforged"],
            f"{PROGRAM}: unrecognized arguments: --x\\nforged",
            id="line-break-escaped",
        ),
        pytest.param(
            ["show", "SPX", "--x\x1b[2J"],
            f"{PROGRAM}: unrecognized arguments: --x\\x1b[2J",
            id="escape-sequence-escaped",
        ),
    ],
)
def test_parser_errors_are_one_labelled_line_with_exit_status_2(capsys, argv, message):
    assert rejected(capsys, *argv) == message


def test_parser_escapes_a_program_name_with_control_characters(capsys):
    parser = ExampleParser(prog="prog\nname")
    capsys.readouterr()
    with pytest.raises(SystemExit) as raised:
        parser.parse_args(["extra"])
    assert raised.value.code == 2
    assert capsys.readouterr().err == "EXAMPLE: prog\\nname: unrecognized arguments: extra\n"


def test_the_base_parser_has_no_label_so_every_domain_names_itself():
    assert not hasattr(Parser, "label")
    assert get_type_hints(Parser)["label"] == ClassVar[str]
    assert (ExampleParser.label, OtherParser.label) == ("EXAMPLE", "OTHER")


@pytest.mark.parametrize(
    ("parser_class", "argv", "message"),
    [
        pytest.param(
            ExampleParser, [], f"{PROGRAM}: the following arguments are required: COMMAND", id="example"
        ),
        pytest.param(
            OtherParser, [], f"{PROGRAM}: the following arguments are required: COMMAND", id="other"
        ),
        pytest.param(
            OtherParser,
            ["show"],
            f"{PROGRAM} show: the following arguments are required: TICKER",
            id="other-subcommand",
        ),
        pytest.param(
            OtherParser,
            ["show", "SPX", "--list", ""],
            f"{PROGRAM} show: argument --list: expected a file path, got an empty value",
            id="other-subcommand-type",
        ),
        pytest.param(
            OtherParser,
            ["--as-of", "2026/10/09", "show", "SPX"],
            f"{PROGRAM}: argument --as-of: expected a YYYY-MM-DD date, got '2026/10/09'",
            id="other-date",
        ),
        pytest.param(
            OtherParser,
            ["show", "SPX", "--from", "2026-10-09T00:00"],
            f"{PROGRAM} show: argument --from: expected a YYYY-MM-DD date, got '2026-10-09T00:00'",
            id="other-subcommand-date",
        ),
    ],
)
def test_each_domain_parser_reports_its_own_label(capsys, parser_class, argv, message):
    assert rejected(capsys, *argv, parser_class=parser_class) == message


@pytest.mark.parametrize("parser_class", [ExampleParser, OtherParser], ids=["example", "other"])
def test_subcommand_parsers_are_built_with_the_domain_parser_class(parser_class):
    show = parser_class(prog=PROGRAM).add_subparsers(dest="command").add_parser("show")

    assert type(show) is parser_class
    assert show.label == parser_class.label


def test_help_is_ordinary_argparse_help_with_exit_status_0(capsys, monkeypatch):
    monkeypatch.setenv("COLUMNS", "200")
    with pytest.raises(SystemExit) as raised:
        build().parse_args(["--help"])
    out, err = capsys.readouterr()
    assert raised.value.code == 0
    assert err == ""
    assert out.startswith(
        f"usage: {PROGRAM} [-h] [--lookback N] [--data-dir PATH] [--as-of YYYY-MM-DD] COMMAND ..."
    )


# --- fail ---------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("label", "message", "line"),
    [
        pytest.param("REGIME", "SPX: datasets changed", "REGIME: SPX: datasets changed\n", id="plain"),
        pytest.param("EDGAR", "SPX: datasets changed", "EDGAR: SPX: datasets changed\n", id="other-label"),
        pytest.param("REGIME", "bad\nname", "REGIME: bad\\nname\n", id="line-break"),
        pytest.param("EDGAR", "bad\nname", "EDGAR: bad\\nname\n", id="other-label-line-break"),
        pytest.param("REGIME", "a\u202eb", "REGIME: a\\u202eb\n", id="right-to-left-override"),
        pytest.param("REGIME", "Δ — fine", "REGIME: Δ — fine\n", id="printable-unicode"),
    ],
)
def test_fail_prints_one_labelled_line_on_standard_error_and_returns_2(capsys, label, message, line):
    capsys.readouterr()

    code = fail(label, message)

    out, err = capsys.readouterr()
    assert code == 2
    assert out == ""
    assert err == line
