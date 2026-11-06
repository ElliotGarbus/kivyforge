"""Each backend's ``byte_compile_need``, read from a real project and lock.

``hello-kivy`` (iOS) and ``hello-android`` track their locks on purpose, so
copying the example gives a project whose lock is in sync without locking
here. Linux's arch-dependent answer is in ``linux/test_byte_compile_need.py``.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from kivyforge.platforms import get_platform
from kivyforge.report import diagnostics

EXAMPLES = Path(__file__).resolve().parents[2] / "examples" / "mobile"


def _copy(example: str, dest: Path, *, lock: bool = True) -> Path:
    src = EXAMPLES / example
    for name in ("pyproject.toml", "src", "assets"):
        if (src / name).is_dir():
            shutil.copytree(src / name, dest / name)
        elif (src / name).is_file():
            shutil.copy2(src / name, dest / name)
    if lock:
        for path in src.glob("pylock.*.toml"):
            shutil.copy2(path, dest / path.name)
    return dest


@pytest.mark.parametrize(
    ("example", "platform", "version"),
    [("hello-kivy", "ios", "3.15.0"), ("hello-android", "android", "3.14.6")],
)
def test_mobile_always_needs_a_host_interpreter(tmp_path, example, platform, version):
    need = get_platform(platform).byte_compile_need(_copy(example, tmp_path))
    assert need.platform == platform
    assert need.host_compiler is True
    assert need.python_version == version
    assert need.lock_problem is None


@pytest.mark.parametrize(
    ("example", "platform"), [("hello-kivy", "ios"), ("hello-android", "android")]
)
def test_a_missing_lock_is_reported_not_guessed(tmp_path, example, platform):
    need = get_platform(platform).byte_compile_need(
        _copy(example, tmp_path, lock=False)
    )
    assert need.python_version is None
    assert need.lock_problem is not None
    assert need.lock_problem.code == diagnostics.LOCK_MISSING


_DESKTOP = {
    "macos": (
        "[tool.kivy.macos]\nschema_version=1\nbundle_id='org.example.myapp'\n"
        "archs=['arm64']\n[tool.kivy.macos.python]\nversion='3.14.5'\n"
    ),
    "windows": (
        "[tool.kivy.windows]\nschema_version=1\napp_id='Acme.MyApp'\n"
        "[tool.kivy.windows.python]\nversion='3.13'\n"
    ),
}


@pytest.mark.parametrize("platform", sorted(_DESKTOP))
def test_macos_and_windows_compile_with_their_own_runtime(tmp_path, platform):
    """Each ships only the arch it builds on, so its staged runtime always runs
    here and nothing is needed from the host, lock or no lock."""
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='myapp'\nversion='1.0.0'\nrequires-python='>=3.13'\n"
        "dependencies=[]\n"
        "[tool.kivy]\ndisplay_name='My App'\napp_dir='src'\nentry_point='main'\n"
        + _DESKTOP[platform]
    )
    (tmp_path / "src").mkdir()
    need = get_platform(platform).byte_compile_need(tmp_path)
    assert need.host_compiler is False
    assert need.lock_problem is not None
    assert need.lock_problem.code == diagnostics.LOCK_MISSING
