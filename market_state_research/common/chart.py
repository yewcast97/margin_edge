"""What every domain's chart page shares: the vendored chart library and the page text.

TradingView Lightweight Charts is vendored once, in ``vendor/``, unmodified from its pinned
release; ``load_library`` verifies the bundle's SHA-256 before every use and pairs it with a
domain's own page template, so each page inlines the library and opens offline. A page is
filled in one pass (``substitute``): its shown text through ``escape``, the data its script
draws through ``embed_json``.
"""

import hashlib
import html
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

LIBRARY_NAME = "lightweight-charts"
LIBRARY_VERSION = "5.2.1"
LIBRARY_SHA256 = "e21cc5caa0226ef30bd8549c50b9ef926615f2a4ee6b4e486353477a55f598cf"
VENDOR_DIRECTORY = Path(__file__).resolve().parent / "vendor" / LIBRARY_NAME / LIBRARY_VERSION
LIBRARY_PATH = VENDOR_DIRECTORY / "lightweight-charts.standalone.production.js"
NOTICE_PATH = VENDOR_DIRECTORY / "NOTICE"

_UNSAFE_IN_SCRIPT = re.compile(r"</script|<script|<!--", re.IGNORECASE)
_PLACEHOLDER = re.compile(r"\{\{([A-Z_0-9]+)\}\}")


@dataclass(frozen=True)
class Library:
    """The vendored chart library, the attribution its licence requires and the page template."""

    script: str
    notice: str
    template: str
    version: str = LIBRARY_VERSION


def load_library(template_path: Path) -> Library:
    """Read the vendored library (verifying the pinned checksum) and the page template at
    ``template_path``, a domain's own."""
    raw = LIBRARY_PATH.read_bytes()
    if hashlib.sha256(raw).hexdigest() != LIBRARY_SHA256:
        raise ValueError(f"{LIBRARY_PATH.name} differs from the pinned {LIBRARY_NAME} {LIBRARY_VERSION}")
    script = raw.decode("utf-8")
    if _UNSAFE_IN_SCRIPT.search(script):
        raise ValueError(f"{LIBRARY_PATH.name} contains markup that would end its script element")
    return Library(
        script=script,
        notice=NOTICE_PATH.read_text(encoding="utf-8").strip(),
        template=template_path.read_text(encoding="utf-8"),
    )


def embed_json(value: object) -> str:
    """JSON that cannot terminate or comment out its ``<script>`` element."""
    text = json.dumps(value, ensure_ascii=True, allow_nan=False, separators=(",", ":"))
    return text.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def escape(value: object) -> str:
    """Text for an element's content or a quoted attribute."""
    return html.escape(str(value), quote=True)


def substitute(template: str, values: Mapping[str, str]) -> str:
    """Replace every ``{{NAME}}`` of ``template`` with ``values[NAME]``.

    One pass over the template: substituted values are never rescanned for placeholders, so a
    value that contains ``{{...}}`` (the library, a reason) stays as it is. A placeholder
    without a value raises ``KeyError``.
    """
    return _PLACEHOLDER.sub(lambda match: values[match.group(1)], template)
