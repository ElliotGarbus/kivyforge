"""``pylock.android.toml`` parsing error paths (android/02) not already covered
by the writer/reader round-trip test in ``test_lock.py``.

Each case hand-crafts the smallest TOML snippet that trips a single guard in
``kivyforge.platforms.android.lock.reader``, so a failure here points straight
at the broken invariant.
"""

from __future__ import annotations

import pytest

from kivyforge.platforms.android.lock import reader

_VALID_RUNTIME = """\
[[tool.kivyforge.python_android]]
version = "3.14.6"
abi = "arm64_v8a"
url = "https://example/py.tar.gz"
sha256 = "a"
min_api = 24
"""

_BASE = f"""\
lock-version = "1.0"
created-by = "kivyforge"
requires-python = ">=3.14"
extras = []
dependency-groups = []
default-groups = []

[tool.kivyforge]
schema_version = 1
kivyforge_version = "0"
generated_at = "t"
pyproject_sha256 = "a"
tool_kivy_android_schema_version = 1
sdl = 2

{_VALID_RUNTIME}"""


class TestBaseSanity:
    def test_base_text_parses_cleanly(self):
        lock = reader.loads(_BASE)
        assert lock.python_android[0].abi == "arm64_v8a"
        assert lock.sdl == 2

    def test_load_reads_from_path(self, tmp_path):
        path = tmp_path / "pylock.android.toml"
        path.write_text(_BASE, encoding="utf-8")
        lock = reader.load(path)
        assert lock.python_android[0].abi == "arm64_v8a"


class TestMalformedWrapping:
    def test_missing_required_runtime_field_wrapped_as_lockerror(self):
        # Target only the runtime's sha256 line (not pyproject_sha256, whose
        # line also contains the substring "sha256 = ...").
        text = _BASE.replace('sha256 = "a"\nmin_api = 24\n', "min_api = 24\n")
        with pytest.raises(reader.LockError, match="malformed"):
            reader.loads(text)


class TestToolTableValidation:
    def test_tool_not_a_table_rejected(self):
        text = (
            'lock-version = "1.0"\nrequires-python = ">=3.14"\ntool = "just a string"\n'
        )
        with pytest.raises(reader.LockError, match=r"\[tool\] must be a table"):
            reader.loads(text)

    def test_missing_kivyforge_subtable_rejected(self):
        text = 'lock-version = "1.0"\n\n[tool]\nfoo = 1\n'
        with pytest.raises(reader.LockError, match=r"missing the \[tool\.kivyforge\]"):
            reader.loads(text)


class TestNoRuntimes:
    def test_empty_python_android_rejected(self):
        text = _BASE.replace(_VALID_RUNTIME, "")
        with pytest.raises(
            reader.LockError, match="no \\[\\[tool.kivyforge.python_android"
        ):
            reader.loads(text)


class TestSdlValidation:
    def test_invalid_sdl_rejected(self):
        text = _BASE.replace("sdl = 2", "sdl = 5")
        with pytest.raises(reader.LockError, match="sdl 5 invalid"):
            reader.loads(text)


class TestGradleValidation:
    def test_gradle_not_a_table_rejected(self):
        text = _BASE.replace("sdl = 2", 'sdl = 2\ngradle = "notadict"')
        with pytest.raises(reader.LockError, match=r"\[tool\.kivyforge\.gradle\]"):
            reader.loads(text)


class TestLockVersionValidation:
    def test_non_string_lock_version_rejected(self):
        text = _BASE.replace('lock-version = "1.0"', "lock-version = 1.0")
        with pytest.raises(reader.LockError, match="must be a string"):
            reader.loads(text)

    def test_non_numeric_major_rejected(self):
        text = _BASE.replace('lock-version = "1.0"', 'lock-version = "abc.0"')
        with pytest.raises(reader.LockError, match="not a valid version"):
            reader.loads(text)

    def test_future_major_rejected(self):
        text = _BASE.replace('lock-version = "1.0"', 'lock-version = "99.0"')
        with pytest.raises(reader.LockError, match="newer than"):
            reader.loads(text)


class TestSchemaVersionValidation:
    def test_non_int_schema_version_rejected(self):
        text = _BASE.replace("schema_version = 1", 'schema_version = "1"')
        with pytest.raises(reader.LockError, match="must be an integer"):
            reader.loads(text)

    def test_bool_schema_version_rejected(self):
        text = _BASE.replace("schema_version = 1", "schema_version = true")
        with pytest.raises(reader.LockError, match="must be an integer"):
            reader.loads(text)

    def test_future_schema_version_rejected(self):
        text = _BASE.replace("schema_version = 1", "schema_version = 99")
        with pytest.raises(reader.LockError, match="newer than"):
            reader.loads(text)


class TestAsListValidation:
    def test_android_libs_not_a_list_rejected(self):
        text = _BASE.replace("sdl = 2", 'sdl = 2\nandroid_libs = "notalist"')
        with pytest.raises(reader.LockError, match="'android_libs' must be an array"):
            reader.loads(text)
