"""Android ``include_files`` on the shared module: what the move changed.

The behaviour is pinned by ``test_cli.py``, untouched by the move; the one
deliberate change is the overwrite refusal's code (include-files-proposal §4.7).
"""

from __future__ import annotations

import pytest

from kivyforge.artifacts.include_files import hash_pins
from kivyforge.build_outcome import BuildEvents
from kivyforge.config.model import AndroidConfig, IncludeFile
from kivyforge.platforms.android import AndroidBuildError, cli
from kivyforge.platforms.android.lock.model import AndroidLockfile
from kivyforge.report import diagnostics, exit_codes

_EVENTS = BuildEvents(
    lambda _s: None, lambda _s: None, lambda _a: None, lambda *_a: None
)


def _lock(pins) -> AndroidLockfile:
    return AndroidLockfile(
        requires_python=">=3.14",
        packages=(),
        python_android=(),
        kivyforge_version="0",
        generated_at="",
        lock_inputs_sha256="",
        tool_kivy_android_schema_version=1,
        kivy_generation=3,
        include_files=tuple(pins),
    )


@pytest.mark.parametrize("dest", [".", "./"])
def test_overwriting_a_generated_file_is_include_reserved(tmp_path, dest):
    (tmp_path / "evil").mkdir()
    (tmp_path / "evil" / "settings.gradle").write_text("x", encoding="utf-8")
    entries = (IncludeFile(dest=dest, sources=("evil/settings.gradle",)),)
    android = AndroidConfig(
        schema_version=1, package="org.example.x", include_files=entries
    )
    with pytest.raises(AndroidBuildError) as exc:
        cli._copy_include_files(
            tmp_path,
            tmp_path / "out",
            android,
            _lock(hash_pins(entries, tmp_path)),
            _EVENTS,
        )
    assert exc.value.code == diagnostics.INCLUDE_RESERVED
    assert exc.value.exit_code == exit_codes.CONFIG_ERROR
    assert exc.value.context == {
        "path": "settings.gradle",
        "source": "evil/settings.gradle",
    }
    assert not (tmp_path / "out" / "settings.gradle").exists()


def test_drift_keeps_its_code_through_the_backend(tmp_path):
    (tmp_path / "a.json").write_text("{}", encoding="utf-8")
    entries = (IncludeFile(dest="app", sources=("a.json",)),)
    android = AndroidConfig(
        schema_version=1, package="org.example.x", include_files=entries
    )
    with pytest.raises(AndroidBuildError) as exc:
        cli._copy_include_files(tmp_path, tmp_path / "out", android, _lock(()), _EVENTS)
    assert exc.value.code == diagnostics.LOCK_DRIFT
    assert exc.value.exit_code == exit_codes.LOCK_DRIFT
    assert not (tmp_path / "out").exists(), "nothing is copied before the checks pass"
