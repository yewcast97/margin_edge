"""Code shared by every domain and bound to none.

New York exchange time, XNYS sessions, the three sections of a domain's ``data/``
directory with their one write rule (``layout``), ticker and message text, the labelled
one-line command-line conventions, the watchlists (the repository-root one, which a
domain's own overrides) and the personal settings of the ignored repository-root ``.env``.
Nothing here knows a source, a raw format or a domain's default data directory.
"""

from pathlib import Path

# The package sits at <root>/market_state_research/common: the one copy of that layout assumption.
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
