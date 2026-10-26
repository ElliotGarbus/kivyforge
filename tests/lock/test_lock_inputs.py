"""The lock-inputs projection (#126, docs/design/dev/lock-inputs-proposal.md).

The central test runs each platform's real lock builder on a config that
records every leaf it reads, and fails when a read is not covered by
``LOCK_INPUTS[platform]``: a forgotten input would ship a stale dependency
graph with no error.
"""

from __future__ import annotations

import dataclasses
import textwrap
import types
from pathlib import Path
from typing import cast

import pytest

from kivyforge.config.loader import load_config_from_text
from kivyforge.config.model import Config
from kivyforge.lock.inputs import LOCK_INPUTS, is_in_sync, lock_inputs_sha256
from tests.platforms.android.lock import test_lock as android_lock_tests
from tests.platforms.ios.lock.conftest import FakePythonProvider, FakeResolver
from tests.platforms.linux.lock.conftest import FakeLinuxResolver
from tests.platforms.linux.lock.conftest import (
    FakeRuntimeProvider as LinuxRuntimeProvider,
)
from tests.platforms.macos.lock.conftest import FakeMacosResolver
from tests.platforms.macos.lock.conftest import (
    FakeRuntimeProvider as MacosRuntimeProvider,
)
from tests.platforms.windows.lock.conftest import (
    FakeRuntimeProvider as WindowsRuntimeProvider,
)
from tests.platforms.windows.lock.conftest import FakeWindowsResolver

PROJECT = """
[project]
name = "myapp"
version = "1.0.0"
requires-python = ">=3.13"
dependencies = ["kivy>=3.0,<4", "more-itertools>=10.5"]

[tool.kivy]
app_dir = "src"
display_name = "My App"
"""

DESKTOP = {
    "macos": """
[tool.kivy.macos]
schema_version = 1
bundle_id = "org.example.myapp"
minimum_system_version = "12.0"
extra_index_urls = ["https://example.invalid/simple/"]
find_links = ["wheels"]
exclude = ["docutils"]

[tool.kivy.macos.python]
version = "3.13.14"
""",
    "linux": """
[tool.kivy.linux]
schema_version = 1
app_id = "org.example.myapp"
glibc_floor = "2.28"
extra_index_urls = ["https://example.invalid/simple/"]
find_links = ["wheels"]
exclude = ["docutils"]

[tool.kivy.linux.python]
version = "3.13.14"
""",
    "windows": """
[tool.kivy.windows]
schema_version = 1
app_id = "Example.MyApp"
extra_index_urls = ["https://example.invalid/simple/"]
find_links = ["wheels"]
exclude = ["docutils"]

[tool.kivy.windows.python]
version = "3.13.14"
""",
}

IOS = """
[tool.kivy.ios]
schema_version = 1
bundle_id = "org.example.myapp"
extra_index_urls = ["https://example.invalid/simple/"]
find_links = ["wheels"]
exclude = ["docutils"]

[tool.kivy.ios.python]
version = "3.15.0"
"""


# --------------------------------------------------------------------------- #
# A config that records what is read from it
# --------------------------------------------------------------------------- #


class _Recorder:
    """Wraps a config dataclass; records each leaf attribute path read.

    Properties and methods run against the recorder, so what they read is
    recorded too (``config.macos_required`` reads ``macos``).
    """

    def __init__(self, target, path: str, reads: set[str]) -> None:
        object.__setattr__(self, "_target", target)
        object.__setattr__(self, "_path", path)
        object.__setattr__(self, "_reads", reads)

    def __getattr__(self, name: str):
        target = object.__getattribute__(self, "_target")
        prefix = object.__getattribute__(self, "_path")
        reads = object.__getattribute__(self, "_reads")
        path = f"{prefix}.{name}" if prefix else name
        declared = getattr(type(target), name, None)
        if isinstance(declared, property) and declared.fget is not None:
            return declared.fget(self)
        if isinstance(declared, types.FunctionType):
            return types.MethodType(declared, self)
        value = getattr(target, name)
        if dataclasses.is_dataclass(value) and not isinstance(value, type):
            return _Recorder(value, path, reads)
        reads.add(path)
        return value


def _uncovered(reads: set[str], platform: str) -> list[str]:
    inputs = LOCK_INPUTS[platform]
    return sorted(
        read
        for read in reads
        if not any(read == p or read.startswith(p + ".") for p in inputs)
    )


def _config(text: str, platform: str, root: Path) -> Config:
    return load_config_from_text(
        textwrap.dedent(text),
        require_ios=platform == "ios",
        require_macos=platform == "macos",
        require_linux=platform == "linux",
        require_windows=platform == "windows",
        require_android=platform == "android",
        project_root=root,
    )


def _recorded(config: Config) -> tuple[Config, set[str]]:
    """``config`` behind a recorder, typed as what the builders accept."""
    reads: set[str] = set()
    return cast(Config, _Recorder(config, "", reads)), reads


@dataclasses.dataclass(frozen=True)
class _Lock:
    lock_inputs_sha256: str


@pytest.fixture
def root(tmp_path, monkeypatch):
    (tmp_path / "wheels").mkdir()
    (tmp_path / "wheels" / "vendored-1.0-py3-none-any.whl").write_bytes(b"")
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture
def unhashed(monkeypatch):
    """Each builder hashes the projection last, which reads every input by
    definition; stubbed so the recorder sees only what the builder itself uses."""
    import kivyforge.lock.wheelruntime.builder as desktop
    import kivyforge.platforms.android.lock.builder as android
    import kivyforge.platforms.ios.lock.builder as ios

    for module in (desktop, android, ios):
        monkeypatch.setattr(module, "lock_inputs_sha256", lambda *_: "f" * 64)


# --------------------------------------------------------------------------- #
# Every read is a lock input
# --------------------------------------------------------------------------- #


@pytest.mark.usefixtures("unhashed")
class TestBuildersReadOnlyLockInputs:
    def test_macos(self, root):
        from kivyforge.platforms.macos.lock import build_macos_lockfile

        proxy, reads = _recorded(_config(PROJECT + DESKTOP["macos"], "macos", root))
        build_macos_lockfile(
            proxy,
            project_root=root,
            resolver=FakeMacosResolver(),
            runtime_provider=MacosRuntimeProvider(),
        )
        assert reads
        assert _uncovered(reads, "macos") == []

    def test_linux(self, root):
        from kivyforge.platforms.linux.lock import build_linux_lockfile

        proxy, reads = _recorded(_config(PROJECT + DESKTOP["linux"], "linux", root))
        build_linux_lockfile(
            proxy,
            project_root=root,
            resolver=FakeLinuxResolver(),
            runtime_provider=LinuxRuntimeProvider(),
        )
        assert reads
        assert _uncovered(reads, "linux") == []

    def test_windows(self, root):
        from kivyforge.platforms.windows.lock import build_windows_lockfile

        text = PROJECT + DESKTOP["windows"]
        proxy, reads = _recorded(_config(text, "windows", root))
        build_windows_lockfile(
            proxy,
            project_root=root,
            resolver=FakeWindowsResolver(),
            runtime_provider=WindowsRuntimeProvider(),
        )
        assert reads
        assert _uncovered(reads, "windows") == []

    def test_ios(self, root):
        from kivyforge.platforms.ios.lock import build_lockfile

        proxy, reads = _recorded(
            _config(PROJECT.replace("3.13", "3.15") + IOS, "ios", root)
        )
        build_lockfile(
            proxy,
            project_root=root,
            resolver=FakeResolver(),
            python_provider=FakePythonProvider(),
        )
        assert reads
        assert _uncovered(reads, "ios") == []

    def test_android(self, root):
        from kivyforge.platforms.android.lock.builder import build_lockfile

        config = _config(android_lock_tests.PYPROJECT, "android", root)
        proxy, reads = _recorded(config)
        build_lockfile(
            proxy,
            project_root=root,
            resolver=android_lock_tests.FakeResolver([android_lock_tests._pkg()]),
            python_provider=android_lock_tests.FakeProvider(),
        )
        assert reads
        assert _uncovered(reads, "android") == []

    def test_the_recorder_catches_an_uncovered_read(self, root, monkeypatch):
        """The check above is only worth something if it can fail."""
        monkeypatch.setitem(
            LOCK_INPUTS,
            "macos",
            tuple(p for p in LOCK_INPUTS["macos"] if p != "macos.exclude"),
        )
        from kivyforge.platforms.macos.lock import build_macos_lockfile

        proxy, reads = _recorded(_config(PROJECT + DESKTOP["macos"], "macos", root))
        build_macos_lockfile(
            proxy,
            project_root=root,
            resolver=FakeMacosResolver(),
            runtime_provider=MacosRuntimeProvider(),
        )
        assert _uncovered(reads, "macos") == ["macos.exclude"]


# --------------------------------------------------------------------------- #
# What changes the hash, and what does not
# --------------------------------------------------------------------------- #


def _sha(text: str, platform: str, root: Path) -> str:
    return lock_inputs_sha256(_config(text, platform, root), platform)


class TestHash:
    def test_comments_whitespace_and_key_order_do_not_count(self, root):
        base = PROJECT + DESKTOP["linux"]
        reordered = base.replace(
            'app_id = "org.example.myapp"\nglibc_floor = "2.28"',
            'glibc_floor = "2.28"\n\n# moved\napp_id = "org.example.myapp"',
        )
        assert reordered != base
        assert _sha(reordered, "linux", root) == _sha(base, "linux", root)

    def test_fields_outside_the_projection_do_not_count(self, root):
        base = PROJECT + DESKTOP["windows"]
        renamed = base.replace('display_name = "My App"', 'display_name = "Other"')
        bumped = base.replace('version = "1.0.0"', 'version = "2.0.0"')
        assert _sha(renamed, "windows", root) == _sha(base, "windows", root)
        assert _sha(bumped, "windows", root) == _sha(base, "windows", root)

    def test_another_platforms_overlay_does_not_count(self, root):
        """Editing iOS must not stale pylock.android.toml (#126)."""
        android = textwrap.dedent(android_lock_tests.PYPROJECT)
        with_ios = android + textwrap.dedent(IOS)
        signed = with_ios + '\n[tool.kivy.ios.signing]\nteam_id = "ABCDE12345"\n'
        assert _sha(with_ios, "android", root) == _sha(android, "android", root)
        assert _sha(signed, "android", root) == _sha(android, "android", root)

    @pytest.mark.parametrize(
        ("old", "new"),
        [
            ('"more-itertools>=10.5"', '"more-itertools>=11"'),
            ('requires-python = ">=3.13"', 'requires-python = ">=3.13.1"'),
            ('glibc_floor = "2.28"', 'glibc_floor = "2.31"'),
            ('exclude = ["docutils"]', 'exclude = ["docutils", "pygments"]'),
            ('find_links = ["wheels"]', "find_links = []"),
            ('version = "3.13.14"', 'version = "3.13.13"'),
        ],
    )
    def test_each_lock_input_counts(self, root, old, new):
        base = PROJECT + DESKTOP["linux"]
        assert old in base
        changed = base.replace(old, new)
        assert _sha(changed, "linux", root) != _sha(base, "linux", root)

    def test_every_projected_path_exists(self):
        """A misspelled path would raise here, not hash as a constant."""
        import kivyforge.config.model as model

        # Annotations are strings ("MacosConfig | None"): the owner is the first.
        owners = {
            f.name: getattr(model, str(f.type).split("|")[0].strip())
            for f in dataclasses.fields(model.Config)
            if f.name in {"project", *LOCK_INPUTS}
        }
        for platform, paths in LOCK_INPUTS.items():
            for path in paths:
                head, field = path.split(".", 1)
                names = {f.name for f in dataclasses.fields(owners[head])}
                assert field in names, f"{platform}: {path}"


class TestIsInSync:
    def test_a_lock_written_before_inputs_were_hashed_is_stale(self, root):
        config = _config(PROJECT + DESKTOP["macos"], "macos", root)
        legacy = _Lock(lock_inputs_sha256="")
        assert not is_in_sync(legacy, config, "macos")

    def test_the_current_hash_is_in_sync(self, root):
        config = _config(PROJECT + DESKTOP["macos"], "macos", root)
        lock = _Lock(lock_inputs_sha256=lock_inputs_sha256(config, "macos"))
        assert is_in_sync(lock, config, "macos")
