"""``linux_byte_compile_need`` — what ``kivyforge bytecompiler`` reads for Linux.

Linux is the one desktop target whose build can need a host interpreter: an
``aarch64`` target built on x86_64, where the staged runtime can't run.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from kivyforge.lock.wheelruntime.model import (
    PythonRuntime,
    RuntimeArtifact,
    WheelRuntimeLock,
)
from kivyforge.platforms import get_platform
from kivyforge.platforms.linux import cli as _linux
from kivyforge.platforms.linux.lock import dumps
from kivyforge.report import diagnostics
from tests.lock_hash import inputs_sha


def _pyproject(archs: tuple[str, ...], byte_compile: str = '"release"') -> str:
    return (
        "[project]\nname='myapp'\nversion='1.0.0'\nrequires-python='>=3.15'\n"
        "dependencies=[]\n"
        "[tool.kivy]\ndisplay_name='My App'\napp_dir='src'\nentry_point='main'\n"
        "[tool.kivy.linux]\nschema_version=1\napp_id='org.example.myapp'\n"
        f"archs={list(archs)!r}\n"
        "[tool.kivy.linux.python]\nversion='3.15.2'\n"
        f"[tool.kivy.linux.build_settings]\nbyte_compile={byte_compile}\n"
    )


def _project(root: Path, archs=("x86_64",), *, in_sync=True, lock=True, **kw) -> Path:
    text = _pyproject(archs, **kw)
    (root / "pyproject.toml").write_text(text)
    (root / "src").mkdir()
    (root / "src" / "main.py").write_text("print('hi')\n")
    if lock:
        (root / "pylock.linux.toml").write_text(
            dumps(
                WheelRuntimeLock(
                    platform="linux",
                    requires_python=">=3.15",
                    packages=(),
                    python_runtime=PythonRuntime(
                        provider="python-build-standalone",
                        version="3.15.2",
                        artifacts=tuple(
                            RuntimeArtifact(arch=a, url=f"https://e/{a}", sha256="x")
                            for a in archs
                        ),
                        floor="2.17",
                    ),
                    archs=tuple(archs),
                    kivyforge_version="3.0.0",
                    generated_at="2026-01-01T00:00:00Z",
                    lock_inputs_sha256=(
                        inputs_sha(text, "linux") if in_sync else "0" * 64
                    ),
                    tool_kivyforge_schema_version=1,
                )
            )
        )
    return root


@pytest.fixture(autouse=True)
def x86_64_host(monkeypatch):
    monkeypatch.setattr(_linux, "host_runs_natively", lambda arch: arch == "x86_64")


def test_a_native_build_needs_no_host_interpreter(tmp_path):
    need = get_platform("linux").byte_compile_need(_project(tmp_path))
    assert need.host_compiler is False
    assert need.python_version == "3.15.2"
    assert need.byte_compile == "release"


def test_an_aarch64_target_needs_one(tmp_path):
    need = get_platform("linux").byte_compile_need(
        _project(tmp_path, ("x86_64", "aarch64"))
    )
    assert need.host_compiler is True
    assert need.python_version == "3.15.2"
    assert need.lock_problem is None


def test_byte_compile_off_is_reported(tmp_path):
    need = get_platform("linux").byte_compile_need(
        _project(tmp_path, ("aarch64",), byte_compile="false")
    )
    assert need.byte_compile is False


def test_a_stale_lock_is_a_lock_problem(tmp_path):
    need = get_platform("linux").byte_compile_need(
        _project(tmp_path, ("aarch64",), in_sync=False)
    )
    assert need.python_version is None
    assert need.lock_problem is not None
    assert need.lock_problem.code == diagnostics.LOCK_DRIFT


def test_a_missing_lock_is_a_lock_problem(tmp_path):
    need = get_platform("linux").byte_compile_need(
        _project(tmp_path, ("aarch64",), lock=False)
    )
    assert need.lock_problem is not None
    assert need.lock_problem.code == diagnostics.LOCK_MISSING
