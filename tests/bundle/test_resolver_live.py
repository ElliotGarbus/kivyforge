"""The interpreter resolver against a *real* host, not a mocked ``subprocess``.

``tests/bundle/test_pycompile.py`` covers :func:`find_interpreter`'s logic with
``subprocess`` stubbed out. What it cannot cover is the round trip through a
real PEP 397 ``py`` launcher — the Windows-only mechanism roadmap item 1's bug
lived in — and CI never reached it either: ``android_windows_host`` ran under
the same 3.14 the project ships, so the resolver returned at its "use the
running interpreter" fast path before the candidate list was even built
(test-matrix.md §5.2).

So these tests take the minors as options and skip without them; the
``android_windows_host`` job runs kivyforge under 3.13 while installing a 3.14
final and a 3.15 pre-release, and passes both. Each test first checks its own
precondition and **fails** — never skips — when the host is not set up the way
the assertion needs, because a resolver test that passes against a host where
the search never ran is the exact silent hole this file exists to close.
"""

from __future__ import annotations

import os
import subprocess
import sys

import pytest

from kivyforge.bundle.pycompile import find_interpreter

pytestmark = pytest.mark.integration


def _launcher_reports(minor: str) -> tuple[str, str] | None:
    """``(version, releaselevel)`` that ``py -<minor>`` resolves to, or ``None``."""
    try:
        proc = subprocess.run(
            [
                "py",
                f"-{minor}",
                "-c",
                "import sys;print(sys.version.split()[0], sys.version_info.releaselevel)",
            ],
            capture_output=True,
            stdin=subprocess.DEVNULL,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    parts = proc.stdout.split()
    if proc.returncode != 0 or len(parts) != 2:
        return None
    return parts[0], parts[1]


def _require_search(minor: str) -> None:
    running = f"{sys.version_info.major}.{sys.version_info.minor}"
    if running == minor:
        pytest.fail(
            f"running under {running}, the minor being resolved, so "
            "find_interpreter would return at its fast path and never search. "
            "Run this under a different minor."
        )


@pytest.fixture
def found_minor(pytestconfig) -> str:
    minor = pytestconfig.getoption("--resolver-found-minor")
    if not minor:
        pytest.skip("no --resolver-found-minor given; needs a prepared host")
    return minor


@pytest.fixture
def prerelease_minor(pytestconfig) -> str:
    minor = pytestconfig.getoption("--resolver-prerelease-minor")
    if not minor:
        pytest.skip("no --resolver-prerelease-minor given; needs a prepared host")
    return minor


def test_a_final_of_the_shipped_minor_is_found_by_searching(found_minor):
    _require_search(found_minor)
    picked = find_interpreter(f"{found_minor}.0")
    print(f"resolver picked for {found_minor}: {picked}")
    if os.name == "nt":
        # The launcher is first in the Windows candidate list, and the one the
        # dev-box measurement found; anything else means that branch was not
        # the one exercised, which is the whole point of the test.
        assert picked == ("py", f"-{found_minor}"), (
            f"expected the py launcher to win, got {picked}; "
            f"py -{found_minor} reports {_launcher_reports(found_minor)}"
        )
    else:
        assert picked, f"no final CPython {found_minor} found by searching"
        assert picked != (), "fast path taken; _require_search should have failed"
    assert picked is not None
    assert _run_version(picked) == (found_minor, "final")


def test_a_prerelease_of_the_right_minor_is_rejected(prerelease_minor):
    # Item 1's trap, on a real launcher: 3.14.0a7 answered "3.14" to a version
    # check and wrote bytecode the shipped 3.14.6 refused to import.
    _require_search(prerelease_minor)
    if os.name == "nt":
        reported = _launcher_reports(prerelease_minor)
        # Without this, "None" below could mean "nothing installed", which
        # would pass without the rejection ever running.
        assert reported is not None, (
            f"py -{prerelease_minor} found nothing; the host must have a "
            f"{prerelease_minor} pre-release installed for this to test anything"
        )
        version, level = reported
        assert version.startswith(f"{prerelease_minor}.") and level != "final", (
            f"py -{prerelease_minor} is {version} ({level}), not a pre-release; "
            "the test would not exercise the rejection. If a final of this "
            "minor now exists on the host (a runner image update), pin a "
            "pre-release of a minor that has none, and pass that minor."
        )
        print(f"py -{prerelease_minor} offers {version} ({level})")
    assert find_interpreter(f"{prerelease_minor}.0") is None


def _run_version(argv: tuple[str, ...]) -> tuple[str, str]:
    out = subprocess.run(
        [
            *argv,
            "-c",
            "import sys;print('%d.%d' % sys.version_info[:2], sys.version_info.releaselevel)",
        ],
        capture_output=True,
        stdin=subprocess.DEVNULL,
        text=True,
        timeout=60,
        check=True,
    ).stdout.split()
    return out[0], out[1]
