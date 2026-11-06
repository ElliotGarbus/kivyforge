"""kivyforge.lock.host_python — the host CPython pinned in the lock.

Hermetic: resolution runs against a fake fetcher; the real fetcher's release
scanning is tested against canned listings in
``tests/platforms/macos/test_pbs_github.py``.
"""

from __future__ import annotations

import pytest

from kivyforge.lock import host_python as hp
from kivyforge.lock.wheelruntime.runtime import ReleaseAsset, RuntimeProviderError
from kivyforge.report import diagnostics, exit_codes

ALL = tuple(sorted((hp.MACOS_ARM64, hp.LINUX_X86_64, hp.WINDOWS_AMD64)))


def _pinned(triple, version="3.15.2", sha="a" * 64):
    return hp.HostPython(
        triple,
        hp.PINNED,
        hp.minor_of(version),
        version=version,
        variant="install_only_stripped",
        url=f"https://pbs.invalid/{version}/{triple}.tar.gz",
        sha256=sha,
    )


class _Fetcher:
    """Answers with *version* for *have* (default: every triple asked for)."""

    def __init__(self, version="3.15.2", have=None, error=None):
        self.version, self.have, self.error = version, have, error
        self.calls = []

    def find_common_install_only(self, minor, triples, *, prefer=None, variants=()):
        self.calls.append((minor, triples, prefer))
        if self.error is not None:
            raise self.error
        have = triples if self.have is None else self.have
        if not have:
            return None, {}
        return self.version, {
            t: ("install_only_stripped", ReleaseAsset(url=f"u/{t}", sha256=t[:8] * 8))
            for t in have
        }


class TestNeededTriples:
    def test_ios_builds_only_on_a_mac(self):
        assert hp.needed_triples("ios") == (hp.MACOS_ARM64,)

    def test_android_builds_on_all_three_hosts(self):
        assert hp.needed_triples("android") == ALL

    def test_linux_only_for_aarch64(self):
        assert hp.needed_triples("linux", ("x86_64",)) == ()
        assert hp.needed_triples("linux", ("x86_64", "aarch64")) == (hp.LINUX_X86_64,)

    @pytest.mark.parametrize("platform", ["macos", "windows"])
    def test_desktops_compile_with_their_own_runtime(self, platform):
        assert hp.needed_triples(platform, ("arm64", "amd64")) == ()


class TestVersions:
    def test_minor_of(self):
        assert hp.minor_of("3.15.2") == "3.15"
        assert hp.minor_of("3.16.0b2") == "3.16"

    def test_is_final(self):
        assert hp.is_final("3.15.2")
        assert not hp.is_final("3.15.0rc1")
        assert not hp.is_final("3.16.0b2")


class TestResolve:
    def test_pins_every_triple_at_one_version(self):
        fetcher = _Fetcher("3.15.2")
        entries = hp.resolve("3.15.2", ALL, fetcher=fetcher)
        assert entries is not None
        assert {e.state for e in entries} == {hp.PINNED}
        assert {e.version for e in entries} == {"3.15.2"}
        assert [e.triple for e in entries] == list(ALL)
        assert fetcher.calls == [("3.15", ALL, "3.15.2")]

    def test_a_triple_without_a_build_is_no_build(self):
        entries = hp.resolve(
            "3.15.2", ALL, fetcher=_Fetcher(have=(hp.MACOS_ARM64, hp.LINUX_X86_64))
        )
        assert entries is not None
        assert {e.triple: e.state for e in entries} == {
            hp.MACOS_ARM64: hp.PINNED,
            hp.LINUX_X86_64: hp.PINNED,
            hp.WINDOWS_AMD64: hp.NO_BUILD,
        }

    def test_a_pre_release_pins_nothing_and_asks_nobody(self):
        fetcher = _Fetcher()
        entries = hp.resolve("3.16.0b2", ALL, fetcher=fetcher)
        assert entries is not None
        assert {e.state for e in entries} == {hp.NO_BUILD}
        assert {e.minor for e in entries} == {"3.16"}
        assert fetcher.calls == []

    def test_no_triples_means_no_table(self):
        assert hp.resolve("3.15.2", ()) is None

    def test_existing_pins_are_kept_without_a_lookup(self):
        """lock and lock --check stay off the GitHub API (Q8)."""
        kept = tuple(_pinned(t, "3.15.0") for t in ALL)
        fetcher = _Fetcher("3.15.2")
        assert hp.resolve("3.15.2", ALL, prefer=kept, fetcher=fetcher) == kept
        assert fetcher.calls == []

    def test_a_missing_triple_re_resolves_all_at_the_kept_version(self):
        """One version for every host (Q3), so a filled gap matches the rest."""
        kept = (_pinned(hp.MACOS_ARM64, "3.15.0"),)
        fetcher = _Fetcher("3.15.0")
        hp.resolve("3.15.2", ALL, prefer=kept, fetcher=fetcher)
        assert fetcher.calls == [("3.15", ALL, "3.15.0")]

    def test_pins_of_another_minor_are_not_kept(self):
        kept = tuple(_pinned(t, "3.14.6") for t in ALL)
        fetcher = _Fetcher("3.15.2")
        entries = hp.resolve("3.15.2", ALL, prefer=kept, fetcher=fetcher)
        assert entries is not None
        assert {e.version for e in entries} == {"3.15.2"}

    def test_offline_keeps_pins_and_marks_the_rest(self):
        kept = (_pinned(hp.MACOS_ARM64),)
        entries = hp.resolve(
            "3.15.2",
            ALL,
            prefer=kept,
            offline=True,
            fetcher=_Fetcher(error=AssertionError()),
        )
        assert entries is not None
        assert {e.triple: e.state for e in entries} == {
            hp.MACOS_ARM64: hp.PINNED,
            hp.LINUX_X86_64: hp.UNRESOLVED_OFFLINE,
            hp.WINDOWS_AMD64: hp.UNRESOLVED_OFFLINE,
        }

    def test_a_no_build_entry_is_looked_up_again(self):
        held = (hp.HostPython(hp.MACOS_ARM64, hp.NO_BUILD, "3.15"),)
        fetcher = _Fetcher("3.15.2")
        entries = hp.resolve("3.15.2", (hp.MACOS_ARM64,), prefer=held, fetcher=fetcher)
        assert entries is not None and entries[0].state == hp.PINNED
        assert fetcher.calls

    def test_a_failed_lookup_is_a_fetch_failure(self):
        with pytest.raises(hp.HostPythonLockError) as exc:
            hp.resolve(
                "3.15.2", ALL, fetcher=_Fetcher(error=RuntimeProviderError("403"))
            )
        assert exc.value.code == diagnostics.HOST_PYTHON_FETCH
        assert exc.value.exit_code == exit_codes.ENVIRONMENT_ERROR
        assert "GITHUB_TOKEN" in str(exc.value)


class TestIncomplete:
    def test_complete(self):
        entries = tuple(_pinned(t) for t in ALL)
        assert hp.incomplete(entries, ALL, "3.15") is None

    def test_no_table(self):
        assert "predates" in (hp.incomplete(None, ALL, "3.15") or "")

    def test_a_missing_triple(self):
        entries = (_pinned(hp.MACOS_ARM64),)
        assert "no host CPython entry for" in (
            hp.incomplete(entries, ALL, "3.15") or ""
        )

    def test_unresolved_offline(self):
        entries = (hp.HostPython(hp.MACOS_ARM64, hp.UNRESOLVED_OFFLINE, "3.15"),)
        assert "offline" in (hp.incomplete(entries, (hp.MACOS_ARM64,), "3.15") or "")

    def test_no_build_is_complete(self):
        """Nothing a re-lock could pin yet."""
        entries = (hp.HostPython(hp.MACOS_ARM64, hp.NO_BUILD, "3.15"),)
        assert hp.incomplete(entries, (hp.MACOS_ARM64,), "3.15") is None

    def test_another_minor(self):
        entries = (_pinned(hp.MACOS_ARM64, "3.14.6"),)
        assert "3.14" in (hp.incomplete(entries, (hp.MACOS_ARM64,), "3.15") or "")

    def test_a_platform_that_needs_none(self):
        assert hp.incomplete(None, (), "3.15") is None


class TestTable:
    def test_round_trip(self):
        import tomllib

        entries = (
            _pinned(hp.MACOS_ARM64),
            hp.HostPython(hp.WINDOWS_AMD64, hp.NO_BUILD, "3.15"),
            hp.HostPython(hp.LINUX_X86_64, hp.UNRESOLVED_OFFLINE, "3.15"),
        )
        lines: list[str] = ["[tool.kivyforge]"]
        hp.emit(lines, entries)
        tool = tomllib.loads("\n".join(lines))["tool"]["kivyforge"]
        assert hp.parse(tool) == tuple(sorted(entries, key=lambda e: e.triple))

    def test_only_a_pinned_entry_records_a_build(self):
        lines: list[str] = []
        hp.emit(lines, (hp.HostPython(hp.MACOS_ARM64, hp.NO_BUILD, "3.16"),))
        text = "\n".join(lines)
        assert 'state = "no-build"' in text
        assert "url" not in text and "sha256" not in text

    def test_absent_table_parses_as_none(self):
        assert hp.parse({}) is None

    @pytest.mark.parametrize(
        "item",
        [
            {"triple": hp.MACOS_ARM64, "state": "lost", "minor": "3.15"},
            {"triple": hp.MACOS_ARM64, "state": "pinned", "minor": "3.15"},
            {"state": "pinned", "minor": "3.15"},
        ],
    )
    def test_an_invalid_entry_is_refused(self, item):
        with pytest.raises(ValueError, match="host_python"):
            hp.parse({"host_python": [item]})


class TestShippedVersion:
    def test_reads_each_lock_family(self):
        from types import SimpleNamespace as NS

        assert (
            hp.shipped_version(NS(python_xcframework=NS(version="3.15.2"))) == "3.15.2"
        )
        assert (
            hp.shipped_version(NS(python_android=(NS(version="3.14.6"),))) == "3.14.6"
        )
        assert hp.shipped_version(NS(python_runtime=NS(version="3.15.0"))) == "3.15.0"
