"""``build_launcher verify``: a missed re-vendor fails, toolchain drift warns.

GitHub's win25-vs2026/20261021 image built different launcher bytes from the
same launcher.c, flags and MSVC/SDK version pin (the SDK was serviced in place),
which failed the reproducibility job on every PR that landed on it, 2026-10.
The vendored binary now records the inputs it was built from, so ``verify``
fails only when those changed; unchanged inputs with different bytes are this
runner's toolchain, reported as a GitHub warning. The compiler is faked: these
run anywhere, with no MSVC.
"""

from __future__ import annotations

import hashlib

import pytest

from kivyforge.platforms.windows.launcher import build_launcher as bl

PIN = bl.ToolsetPin("14.51.36231", "10.0.26100.0")
VENDORED = b"MZ vendored launcher bytes"
DRIFTED = b"MZ same source, other toolchain"


@pytest.fixture
def vendor(tmp_path, monkeypatch):
    """A vendor directory holding a launcher, its manifest and its pin."""
    source = tmp_path / "launcher.c"
    source.write_bytes(b"int main(void) { return 0; }\n")  # LF, on any host
    monkeypatch.setattr(bl, "SOURCE", source)
    monkeypatch.setattr(bl, "VENDORED_LAUNCHER", tmp_path / bl.LAUNCHER_NAME)
    monkeypatch.setattr(bl, "MANIFEST", tmp_path / "SHA256SUMS")
    monkeypatch.setattr(bl, "TOOLSET_FILE", tmp_path / "TOOLSET.txt")
    monkeypatch.setattr(
        bl,
        "_vcvars_env",
        lambda *a, **k: {
            "VCTOOLSVERSION": PIN.vc_tools,
            "WINDOWSSDKVERSION": "10.0.26100.0\\",
        },
    )
    bl.VENDORED_LAUNCHER.write_bytes(VENDORED)
    bl._write_manifest({bl.LAUNCHER_NAME: hashlib.sha256(VENDORED).hexdigest()})
    return tmp_path


def _record(pin: bl.ToolsetPin, *, inputs: bool = True) -> None:
    digest = bl.launcher_inputs_sha256(pin) if inputs else None
    bl.write_toolset_pin(bl.ToolsetPin(pin.vc_tools, pin.winsdk, digest))


def _rebuild_as(monkeypatch, data: bytes) -> None:
    def compile_launcher(dest, **_kw):
        dest.write_bytes(data)
        return dest

    monkeypatch.setattr(bl, "compile_launcher", compile_launcher)


class TestToolsetFile:
    def test_the_inputs_round_trip(self, vendor):
        _record(PIN)
        pin = bl.pinned_toolset()
        assert pin == bl.ToolsetPin(
            PIN.vc_tools, PIN.winsdk, bl.launcher_inputs_sha256(PIN)
        )

    def test_a_file_without_inputs_still_parses(self, vendor):
        bl.TOOLSET_FILE.write_text(
            "# old\n14.51.36231\n10.0.26100.0\n", encoding="utf-8"
        )
        assert bl.pinned_toolset() == PIN


class TestInputsHash:
    def test_line_endings_do_not_count(self, vendor):
        before = bl.launcher_inputs_sha256(PIN)
        bl.SOURCE.write_bytes(bl.SOURCE.read_bytes().replace(b"\n", b"\r\n"))
        assert bl.launcher_inputs_sha256(PIN) == before

    def test_the_source_counts(self, vendor):
        before = bl.launcher_inputs_sha256(PIN)
        bl.SOURCE.write_text("int main(void) { return 1; }\n", encoding="utf-8")
        assert bl.launcher_inputs_sha256(PIN) != before

    def test_the_flags_count(self, vendor, monkeypatch):
        before = bl.launcher_inputs_sha256(PIN)
        monkeypatch.setattr(bl, "_CL_FLAGS", [*bl._CL_FLAGS, "/O2"])
        assert bl.launcher_inputs_sha256(PIN) != before

    def test_the_pin_counts(self, vendor):
        other = bl.ToolsetPin("14.51.36232", PIN.winsdk)
        assert bl.launcher_inputs_sha256(other) != bl.launcher_inputs_sha256(PIN)


class TestVerify:
    def test_a_byte_match_passes(self, vendor, monkeypatch, capsys):
        _record(PIN)
        _rebuild_as(monkeypatch, VENDORED)
        assert bl.do_verify() == 0
        assert "is reproducible" in capsys.readouterr().out

    def test_drift_with_unchanged_inputs_warns_and_passes(
        self, vendor, monkeypatch, capsys
    ):
        _record(PIN)
        _rebuild_as(monkeypatch, DRIFTED)
        assert bl.do_verify() == 0
        out = capsys.readouterr().out
        assert out.startswith("::warning title=Launcher toolchain drift::")
        assert "revendor_launcher" in out
        out.encode("cp1252")  # reaches a redirected Windows console

    def test_changed_source_without_a_re_vendor_fails(self, vendor, monkeypatch):
        _record(PIN)
        bl.SOURCE.write_text("int main(void) { return 2; }\n", encoding="utf-8")
        _rebuild_as(monkeypatch, DRIFTED)
        with pytest.raises(
            bl.LauncherBuildError, match="recorded inputs no longer match"
        ):
            bl.do_verify()

    def test_no_recorded_inputs_stays_strict(self, vendor, monkeypatch):
        _record(PIN, inputs=False)
        _rebuild_as(monkeypatch, DRIFTED)
        with pytest.raises(bl.LauncherBuildError, match="does not byte-match"):
            bl.do_verify()

    def test_drift_still_checks_the_manifest_pin(self, vendor, monkeypatch):
        _record(PIN)
        bl._write_manifest({bl.LAUNCHER_NAME: "0" * 64})
        _rebuild_as(monkeypatch, DRIFTED)
        with pytest.raises(bl.LauncherBuildError, match="does not match the manifest"):
            bl.do_verify()


class TestBuildRecordsInputs:
    def test_build_writes_the_inputs_hash(self, vendor, monkeypatch):
        _rebuild_as(monkeypatch, VENDORED)
        bl.TOOLSET_FILE.write_text("14.51.36231\n10.0.26100.0\n", encoding="utf-8")
        assert bl.do_build() == 0
        pin = bl.pinned_toolset()
        assert pin is not None and pin.inputs == bl.launcher_inputs_sha256(PIN)
