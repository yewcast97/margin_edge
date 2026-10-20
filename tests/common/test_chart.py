"""common/chart.py: the pinned chart library, a domain's template beside it, and the page text."""

import hashlib
import json
import re

import pytest

from market_state_research import common as common_package
from market_state_research.common import chart
from market_state_research.common.chart import (
    LIBRARY_PATH,
    LIBRARY_SHA256,
    NOTICE_PATH,
    VENDOR_DIRECTORY,
    embed_json,
    escape,
    load_library,
    substitute,
)


@pytest.fixture
def template(tmp_path):
    path = tmp_path / "chart.html"
    path.write_text("<title>{{TITLE}}</title>\n<script>{{LIBRARY}}</script>\n", encoding="utf-8")
    return path


def test_the_library_is_vendored_once_in_common_and_pinned(template):
    package = common_package.__file__.removesuffix("__init__.py")
    assert str(VENDOR_DIRECTORY).startswith(package) and VENDOR_DIRECTORY.name == "5.2.1"
    assert hashlib.sha256(LIBRARY_PATH.read_bytes()).hexdigest() == LIBRARY_SHA256
    for name in ("LICENSE", "NOTICE", "PROVENANCE.md"):
        assert (VENDOR_DIRECTORY / name).is_file()
    library = load_library(template)
    assert library.version == "5.2.1" and "TradingView" in library.notice
    assert library.notice == NOTICE_PATH.read_text(encoding="utf-8").strip()
    assert library.script == LIBRARY_PATH.read_text(encoding="utf-8")
    assert library.template == template.read_text(encoding="utf-8")


def test_a_tampered_library_is_refused(monkeypatch, tmp_path, template):
    copy = tmp_path / "lightweight-charts.js"
    copy.write_bytes(LIBRARY_PATH.read_bytes() + b"\n")
    monkeypatch.setattr(chart, "LIBRARY_PATH", copy)
    with pytest.raises(ValueError, match="differs from the pinned lightweight-charts 5.2.1"):
        load_library(template)


@pytest.mark.parametrize("markup", ["</script>", "<SCRIPT src=x>", "<!--"])
def test_a_library_that_would_end_its_script_element_is_refused(monkeypatch, tmp_path, template, markup):
    copy = tmp_path / "lightweight-charts.js"
    copy.write_text(f"var a = '{markup}';", encoding="utf-8")
    monkeypatch.setattr(chart, "LIBRARY_PATH", copy)
    monkeypatch.setattr(chart, "LIBRARY_SHA256", hashlib.sha256(copy.read_bytes()).hexdigest())
    with pytest.raises(ValueError, match="markup that would end its script element"):
        load_library(template)


def test_embedded_json_cannot_end_or_comment_out_its_script():
    value = {"reason": "</script><!-- & -->", "number": "1.50", "none": None}
    text = embed_json(value)
    assert re.search(r"[<>&]", text) is None
    assert text.isascii() and text.startswith('{"reason":"\\u003c/script\\u003e')  # compact separators
    assert json.loads(text) == value


def test_embedded_json_refuses_a_value_json_cannot_hold():
    with pytest.raises(ValueError):
        embed_json({"value": float("nan")})


def test_escape_covers_content_and_quoted_attributes():
    assert escape("a < b & \"c\" 'd'") == "a &lt; b &amp; &quot;c&quot; &#x27;d&#x27;"
    assert escape(42) == "42"


def test_substitute_fills_in_one_pass_and_names_a_missing_value():
    template = "<h1>{{TITLE}}</h1><p>{{BODY}}</p><p>{{TITLE}}</p>"
    # A value holding a placeholder is never rescanned.
    assert substitute(template, {"TITLE": "{{BODY}}", "BODY": "x"}) == (
        "<h1>{{BODY}}</h1><p>x</p><p>{{BODY}}</p>"
    )
    assert substitute("{{lower}} {{ NAME }}", {}) == "{{lower}} {{ NAME }}"
    with pytest.raises(KeyError, match="BODY"):
        substitute(template, {"TITLE": "t"})
