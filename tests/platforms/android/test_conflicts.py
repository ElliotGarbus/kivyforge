"""Finding an `android` that the bundled package would shadow."""

from __future__ import annotations

from kivyforge.platforms.android.stage.conflicts import (
    app_android_module,
    site_packages_android_provider,
)


def _dist(sp, name, dirname, record_lines):
    info = sp / f"{dirname}.dist-info"
    info.mkdir(parents=True)
    (info / "METADATA").write_text(f"Metadata-Version: 2.1\nName: {name}\n\nbody\n")
    (info / "RECORD").write_text("".join(f"{line},,\n" for line in record_lines))


class TestApp:
    def test_none(self, tmp_path):
        (tmp_path / "main.py").write_text("")
        (tmp_path / "android_helpers.py").write_text("")
        assert app_android_module(tmp_path) is None

    def test_module_and_package(self, tmp_path):
        (tmp_path / "android.py").write_text("")
        assert app_android_module(tmp_path) == tmp_path / "android.py"
        (tmp_path / "android.py").unlink()
        (tmp_path / "android").mkdir()
        assert app_android_module(tmp_path) == tmp_path / "android"

    def test_extension_module(self, tmp_path):
        (tmp_path / "android.cpython-314-aarch64-linux-android.so").write_bytes(b"")
        found = app_android_module(tmp_path)
        assert found is not None
        assert found.name.startswith("android.cpython")


class TestSitePackages:
    def test_missing_directory_is_clean(self, tmp_path):
        assert site_packages_android_provider(tmp_path / "absent") is None

    def test_other_packages_are_clean(self, tmp_path):
        (tmp_path / "jnius").mkdir()
        _dist(tmp_path, "pyjnius", "pyjnius-1.7.0", ["jnius/__init__.py"])
        assert site_packages_android_provider(tmp_path) is None

    def test_names_the_distribution_from_its_record(self, tmp_path):
        (tmp_path / "android").mkdir()
        _dist(tmp_path, "pyjnius", "pyjnius-1.7.0", ["jnius/__init__.py"])
        _dist(tmp_path, "Android", "android-1.0", ["android/__init__.py"])
        assert site_packages_android_provider(tmp_path) == "Android"

    def test_a_single_module(self, tmp_path):
        (tmp_path / "android.py").write_text("")
        _dist(tmp_path, "shim", "shim-2.0", ["android.py"])
        assert site_packages_android_provider(tmp_path) == "shim"

    def test_unclaimed_falls_back_to_the_path(self, tmp_path):
        (tmp_path / "android").mkdir()
        assert site_packages_android_provider(tmp_path) == "android"
