"""common/env.py: the strict ``KEY=VALUE`` settings file and the environment-first lookup.

Every settings file read here is written below pytest's ``tmp_path``. ``ENV_PATH`` is
only compared, never read: ``read_env`` has no default path, and every ``setting`` call
passes a temporary one.
"""

import inspect
from pathlib import Path

import pytest

from market_state_research.common import REPOSITORY_ROOT
from market_state_research.common.env import ENV_PATH, read_env, setting

NAME = "MARGIN_EDGE_TEST_SETTING"
SECRET = "s3cr3t-value"


def written(directory: Path, content: str | bytes, name: str = ".env") -> Path:
    """A settings file below ``directory`` holding ``content`` (text is written as UTF-8)."""
    path = directory / name
    path.write_bytes(content.encode() if isinstance(content, str) else content)
    return path


@pytest.fixture
def unset(monkeypatch):
    """``NAME`` absent from the process environment for one test."""
    monkeypatch.delenv(NAME, raising=False)


# --- location -----------------------------------------------------------------------------------


def test_the_settings_file_is_the_ignored_dotenv_at_the_repository_root():
    assert (REPOSITORY_ROOT / "pyproject.toml").is_file()
    assert ENV_PATH == REPOSITORY_ROOT / ".env"


def test_read_env_has_no_default_path_so_no_caller_reads_the_real_file_by_accident():
    assert inspect.signature(read_env).parameters["path"].default is inspect.Parameter.empty
    assert inspect.signature(setting).parameters["path"].default == ENV_PATH


# --- read_env -----------------------------------------------------------------------------------


def test_a_missing_file_has_no_settings(tmp_path):
    assert read_env(tmp_path / ".env") == {}


@pytest.mark.parametrize(
    "content",
    ["", "\n", "\n\n\n", "   \n\t\n", "# only a comment\n", "\r\n"],
    ids=["empty", "one-blank-line", "blank-lines", "whitespace", "comment", "crlf-blank"],
)
def test_a_file_without_assignments_has_no_settings(tmp_path, content):
    assert read_env(written(tmp_path, content)) == {}


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        pytest.param("KEY=value", {"KEY": "value"}, id="no-final-newline"),
        pytest.param("KEY=value\n", {"KEY": "value"}, id="plain"),
        pytest.param("A=1\nB_2=two\n_C=3\n", {"A": "1", "B_2": "two", "_C": "3"}, id="several"),
        pytest.param("export KEY=value\n", {"KEY": "value"}, id="export"),
        pytest.param("export\tKEY=value\n", {"KEY": "value"}, id="export-tab"),
        pytest.param("export  KEY=value\n", {"KEY": "value"}, id="export-two-spaces"),
        pytest.param("KEY=a=b==c\n", {"KEY": "a=b==c"}, id="inner-equals"),
        pytest.param("KEY=\n", {"KEY": ""}, id="empty-value"),
        pytest.param("KEY=a b  c\n", {"KEY": "a b  c"}, id="inner-spaces"),
        pytest.param("KEY=a\tb\n", {"KEY": "a\tb"}, id="inner-tab"),
        pytest.param("KEY=a # not a comment\n", {"KEY": "a # not a comment"}, id="hash-in-value"),
        pytest.param("KEY=$HOME\\n\n", {"KEY": "$HOME\\n"}, id="no-expansion-or-escapes"),
        pytest.param("  KEY=value \t\n", {"KEY": "value"}, id="surrounding-whitespace"),
        pytest.param("KEY=café — Δ\n", {"KEY": "café — Δ"}, id="unicode-value"),
    ],
)
def test_assignments_are_read_as_written(tmp_path, content, expected):
    assert read_env(written(tmp_path, content)) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        pytest.param('"a b"', "a b", id="double"),
        pytest.param("'a b'", "a b", id="single"),
        pytest.param('""', "", id="empty-double"),
        pytest.param("''", "", id="empty-single"),
        pytest.param('"Name contact@example.com"', "Name contact@example.com", id="user-agent"),
        pytest.param('"it\'s"', "it's", id="other-quote-inside"),
        pytest.param('""a""', '"a"', id="one-pair-only"),
        pytest.param('"a"b"', 'a"b', id="inner-quote-kept"),
        pytest.param("\"a b'", "\"a b'", id="mismatched-kept"),
        pytest.param('"a b', '"a b', id="unclosed-kept"),
        pytest.param('a b"', 'a b"', id="closing-only-kept"),
        pytest.param('"', '"', id="lone-quote-kept"),
        pytest.param('"a" # note', '"a" # note', id="quoted-then-text-kept"),
    ],
)
def test_one_pair_of_matching_quotes_is_removed(tmp_path, value, expected):
    assert read_env(written(tmp_path, f"KEY={value}\n")) == {"KEY": expected}


def test_comments_and_blank_lines_are_skipped_wherever_they_are(tmp_path):
    content = "# settings\n\nFIRST=1\n   # indented comment\n\t\nSECOND=2\n#THIRD=3\n\n"

    assert read_env(written(tmp_path, content)) == {"FIRST": "1", "SECOND": "2"}


def test_crlf_line_ends_are_accepted(tmp_path):
    content = '# settings\r\nFIRST=1\r\n\r\nSECOND="two"\r\nTHIRD=\r\n'

    assert read_env(written(tmp_path, content)) == {"FIRST": "1", "SECOND": "two", "THIRD": ""}


def test_the_last_assignment_of_a_key_wins(tmp_path):
    content = "KEY=first\nOTHER=x\nexport KEY=second\nKEY='third'\n"

    assert read_env(written(tmp_path, content)) == {"KEY": "third", "OTHER": "x"}


def test_reading_leaves_the_file_unchanged(tmp_path):
    content = b"KEY=value\r\n"
    path = written(tmp_path, content)

    read_env(path)

    assert path.read_bytes() == content
    assert sorted(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize(
    "line",
    [
        pytest.param(f"key={SECRET}", id="lowercase-key"),
        pytest.param(f"Key={SECRET}", id="mixed-case-key"),
        pytest.param(f"KEY = {SECRET}", id="spaces-around-equals"),
        pytest.param(f"KEY ={SECRET}", id="space-before-equals"),
        pytest.param(f"KEY= {SECRET}", id="space-after-equals"),
        pytest.param(f"KEY=\t{SECRET}", id="tab-after-equals"),
        pytest.param(f'KEY= "{SECRET}"', id="space-before-quoted-value"),
        pytest.param(f"KEY {SECRET}", id="no-equals"),
        pytest.param("KEY", id="key-only"),
        pytest.param(f"={SECRET}", id="no-key"),
        pytest.param(f"1KEY={SECRET}", id="leading-digit"),
        pytest.param(f"KEY-NAME={SECRET}", id="hyphen"),
        pytest.param(f"KEY.NAME={SECRET}", id="dot"),
        pytest.param(f"KÉY={SECRET}", id="non-ascii-key"),
        pytest.param(f"ＫEY={SECRET}", id="fullwidth-letter"),
        pytest.param(f"export={SECRET}", id="export-as-key"),
        pytest.param(f"exportKEY={SECRET}", id="export-without-space"),
        pytest.param(f"EXPORT KEY={SECRET}", id="export-uppercase"),
        pytest.param(f"export KEY {SECRET}", id="export-no-equals"),
        pytest.param("export", id="export-alone"),
        pytest.param(f"﻿KEY={SECRET}", id="byte-order-mark"),
        pytest.param(f"set KEY={SECRET}", id="other-command"),
        pytest.param(f"KEY={SECRET}\rOTHER=1", id="bare-carriage-return"),
        pytest.param(f"KEY=a\x1b{SECRET}", id="escape"),
        pytest.param(f"KEY={SECRET}\x00", id="nul"),
        pytest.param(f"KEY={SECRET}\x0b", id="vertical-tab"),
        pytest.param(f"KEY={SECRET}\x0c", id="form-feed"),
        pytest.param(f"KEY={SECRET}\x7f", id="delete"),
        pytest.param(f"KEY={SECRET}\x85", id="c1-next-line"),
        pytest.param(f"\x1bKEY={SECRET}", id="escape-before-key"),
        pytest.param(f"# note\rKEY={SECRET}", id="carriage-return-in-comment"),
        pytest.param("# note\x1b[2J", id="escape-in-comment"),
    ],
)
def test_a_malformed_line_is_named_by_its_number_only(tmp_path, line):
    path = written(tmp_path, f"# settings\n\nGOOD=1\n{line}\nLATER=2\n")

    with pytest.raises(ValueError) as caught:
        read_env(path)

    assert str(caught.value) == f"{path}: line 4 is not KEY=VALUE"
    assert SECRET not in str(caught.value)


@pytest.mark.parametrize(
    "line",
    [
        pytest.param(b"KEY=caf\xe9", id="latin-1-value"),
        pytest.param(b"# caf\xe9", id="latin-1-comment"),
        pytest.param(b"KEY=\xff\xfe", id="invalid-bytes"),
        pytest.param(b"KEY=\xed\xa0\x80", id="encoded-surrogate"),
    ],
)
def test_a_line_that_is_not_utf8_is_named_by_its_number_only(tmp_path, line):
    path = written(tmp_path, b"FIRST=1\r\n" + line + b"\r\nLATER=2\r\n")

    with pytest.raises(ValueError) as caught:
        read_env(path)

    assert str(caught.value) == f"{path}: line 2 is not KEY=VALUE"


@pytest.mark.parametrize(
    "content",
    [
        pytest.param(b"A=1\rB=2\r\n", id="assignments"),
        pytest.param(f"KEY={SECRET}\rOTHER=1\r".encode(), id="no-newline-at-all"),
        pytest.param(b"# settings\rA=1\rB=2\r", id="comment-first"),
        pytest.param(b"\rA=1\r", id="blank-first"),
    ],
)
def test_cr_only_line_ends_are_refused_rather_than_read_as_one_line(tmp_path, content):
    path = written(tmp_path, content)

    with pytest.raises(ValueError) as caught:
        read_env(path)

    assert str(caught.value) == f"{path}: line 1 is not KEY=VALUE"
    assert SECRET not in str(caught.value)


def test_the_first_malformed_line_is_reported(tmp_path):
    path = written(tmp_path, "A=1\nbad one\nbad two\n")

    with pytest.raises(ValueError) as caught:
        read_env(path)

    assert str(caught.value) == f"{path}: line 2 is not KEY=VALUE"


@pytest.mark.parametrize(
    ("name", "escaped"),
    [
        pytest.param("env\nforged", "env\\nforged", id="line-break"),
        pytest.param("env\x1b[2J", "env\\x1b[2J", id="escape-sequence"),
        pytest.param("env‮vne", "env\\u202evne", id="right-to-left-override"),
    ],
)
def test_control_characters_in_the_path_are_escaped(tmp_path, name, escaped):
    path = written(tmp_path, "bad line\n", name)

    with pytest.raises(ValueError) as caught:
        read_env(path)

    assert str(caught.value) == f"{tmp_path}/{escaped}: line 1 is not KEY=VALUE"


def test_other_filesystem_errors_propagate_unchanged(tmp_path):
    with pytest.raises(IsADirectoryError):
        read_env(tmp_path)


# --- setting ------------------------------------------------------------------------------------


def test_the_environment_wins_over_the_file(tmp_path, monkeypatch):
    path = written(tmp_path, f"{NAME}=from-file\n")
    monkeypatch.setenv(NAME, "from-environment")

    assert setting(NAME, path) == "from-environment"


def test_an_empty_environment_value_still_wins(tmp_path, monkeypatch):
    path = written(tmp_path, f"{NAME}=from-file\n")
    monkeypatch.setenv(NAME, "")

    assert setting(NAME, path) == ""


@pytest.mark.usefixtures("unset")
def test_the_file_is_the_fallback(tmp_path):
    path = written(tmp_path, f'# private\nexport {NAME}="Name contact@example.com"\n')

    assert setting(NAME, path) == "Name contact@example.com"


@pytest.mark.usefixtures("unset")
@pytest.mark.parametrize(
    "content",
    [None, "", "OTHER=1\n", f"# {NAME}=commented\n"],
    ids=["missing-file", "empty-file", "other-key", "commented-out"],
)
def test_an_unset_name_is_none(tmp_path, content):
    path = tmp_path / ".env" if content is None else written(tmp_path, content)

    assert setting(NAME, path) is None


@pytest.mark.usefixtures("unset")
def test_an_empty_file_value_is_returned_as_empty(tmp_path):
    assert setting(NAME, written(tmp_path, f"{NAME}=\n")) == ""


@pytest.mark.usefixtures("unset")
def test_a_malformed_file_fails_the_lookup(tmp_path):
    path = written(tmp_path, f"{NAME}=ok\n{SECRET}\n")

    with pytest.raises(ValueError) as caught:
        setting(NAME, path)

    assert str(caught.value) == f"{path}: line 2 is not KEY=VALUE"


def test_the_file_is_not_opened_when_the_environment_has_the_name(tmp_path, monkeypatch):
    malformed = written(tmp_path, f"{SECRET}\n")
    monkeypatch.setenv(NAME, "from-environment")
    opened: list[Path] = []
    read_bytes = Path.read_bytes

    def recording(path: Path) -> bytes:
        opened.append(path)
        return read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", recording)

    # Reading either path would raise: a directory, and a file with a malformed line.
    assert setting(NAME, tmp_path) == "from-environment"
    assert setting(NAME, malformed) == "from-environment"
    assert opened == []

    monkeypatch.delenv(NAME)
    with pytest.raises(IsADirectoryError):
        setting(NAME, tmp_path)
    with pytest.raises(ValueError):
        setting(NAME, malformed)
    assert opened == [tmp_path, malformed]
