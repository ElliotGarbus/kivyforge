"""status / clean / upgrade for Android (android/06)."""

from __future__ import annotations

from click.testing import CliRunner

from kivyforge.cli.clean import clean
from kivyforge.platforms.android.cli import android_status

PYPROJECT = """\
[project]
name = "verbapp"
version = "2.1.0"
dependencies = ["kivy==2.3.1", "pyjnius"]

[tool.kivy]
app_dir = "src"

[tool.kivy.android]
schema_version = 1
package = "org.example.verbapp"

[tool.kivy.android.python]
version = "3.14.6"
"""


class TestStatus:
    def test_snapshot(self, tmp_path, capsys):
        (tmp_path / "src").mkdir()
        (tmp_path / "pyproject.toml").write_text(PYPROJECT, encoding="utf-8")
        android_status(tmp_path)
        out = capsys.readouterr().out
        assert "verbapp  (org.example.verbapp)" in out
        assert "Python:     3.14.6" in out
        assert "kivy_generation 2" in out
        assert "Lock:       missing" in out
        assert "apk (debug)" in out and "not built" in out


class TestClean:
    def test_removes_android_project(self, tmp_path, monkeypatch):
        (tmp_path / "pyproject.toml").write_text(PYPROJECT, encoding="utf-8")
        generated = tmp_path / "verbapp-android"
        (generated / "app").mkdir(parents=True)
        (generated / "app" / "x.txt").write_text("stale", encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        result = CliRunner().invoke(clean, [])
        assert result.exit_code == 0
        assert not generated.exists()
        assert "verbapp-android" in result.output


class TestUpgrade:
    def test_no_lock_actionable(self, tmp_path, monkeypatch):
        from kivyforge.cli.upgrade import upgrade

        (tmp_path / "pyproject.toml").write_text(PYPROJECT, encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        result = CliRunner().invoke(upgrade, ["-p", "android"])
        assert result.exit_code != 0
        assert "pylock.android.toml not found" in result.output
