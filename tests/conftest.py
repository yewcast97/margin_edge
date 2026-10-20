"""Repository-wide guard: no test may change any production runtime data.

Every ``market_state_research/<domain>/data`` directory, every poster's folder
``market_state_research/posts/<poster>/`` and every ``explore_hypothesis/<hypothesis>/data``
directory are snapshotted before the session and compared after it, so a domain, poster or
hypothesis added later is covered automatically. Every checkout tracks a scripted domain's
``data/.gitignore``, so the first pattern always matches: when it does not, the patterns no
longer name the package (a rename left them behind), and every test fails instead of the
guard watching nothing.
"""

import hashlib
import stat
from pathlib import Path

import pytest

REPOSITORY = Path(__file__).resolve().parent.parent
# A pattern ending in "/" matches directories only: a poster's folder, not the domain's own files.
DATA_PATTERNS = (
    "market_state_research/*/data",
    "market_state_research/posts/*/",
    "explore_hypothesis/*/data",
)


def production_snapshot() -> dict[str, tuple]:
    """Type, inode, size, mtime and content hash of every path below every production data directory."""
    snapshot = {}
    for directory in sorted(path for pattern in DATA_PATTERNS for path in REPOSITORY.glob(pattern)):
        for path in [directory, *sorted(directory.rglob("*"))]:
            info = path.lstat()
            digest = hashlib.sha256(path.read_bytes()).hexdigest() if stat.S_ISREG(info.st_mode) else None
            snapshot[str(path.relative_to(REPOSITORY))] = (
                info.st_mode,
                info.st_ino,
                info.st_size,
                info.st_mtime_ns,
                digest,
            )
    return snapshot


@pytest.fixture(autouse=True, scope="session")
def production_data_untouched():
    """Fail the run if any test creates, removes, renames or changes production runtime files."""
    assert any(REPOSITORY.glob(DATA_PATTERNS[0])), (
        f"no {DATA_PATTERNS[0]} directory: the guard would watch nothing"
    )
    before = production_snapshot()
    yield
    assert production_snapshot() == before, "tests must not change any production data directory"
