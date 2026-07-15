"""rcedit resource-patch command construction + execution (host-agnostic)."""

from __future__ import annotations

from pathlib import Path

import pytest

from kivyforge.platforms.windows import WindowsBundleError
from kivyforge.platforms.windows import rcedit as R
from kivyforge.platforms.windows.rcedit import ResourcePatch, build_rcedit_args

RCEDIT = Path("C:/tools/rcedit-x64.exe")
EXE = Path("C:/app/MyApp.exe")


class TestResourcePatch:
    def test_empty_by_default(self):
        assert ResourcePatch().is_empty

    def test_not_empty_with_any_field(self):
        assert not ResourcePatch(product_name="X").is_empty
        assert not ResourcePatch(icon=Path("i.ico")).is_empty


class TestBuildArgs:
    def test_empty_patch_is_noop_args(self):
        args = build_rcedit_args(RCEDIT, EXE, ResourcePatch())
        assert args == [str(RCEDIT), str(EXE)]

    def test_icon(self):
        args = build_rcedit_args(RCEDIT, EXE, ResourcePatch(icon=Path("i.ico")))
        assert "--set-icon" in args
        assert args[args.index("--set-icon") + 1] == "i.ico"

    def test_numeric_versions(self):
        patch = ResourcePatch(file_version="1.2.3.0", product_version="1.2.0.0")
        args = build_rcedit_args(RCEDIT, EXE, patch)
        assert args[args.index("--set-file-version") + 1] == "1.2.3.0"
        assert args[args.index("--set-product-version") + 1] == "1.2.0.0"

    def test_string_fields(self):
        patch = ResourcePatch(
            product_name="My App",
            file_description="My App launcher",
            product_version_string="1.2.3rc1",
            legal_copyright="(c) 2026 Me",
            company_name="Me Inc",
        )
        args = build_rcedit_args(RCEDIT, EXE, patch)
        joined = " ".join(args)
        for key in (
            "ProductName",
            "FileDescription",
            "ProductVersion",
            "LegalCopyright",
            "CompanyName",
        ):
            assert key in args
        assert "My App" in args
        assert "1.2.3rc1" in joined

    def test_exe_is_first_operand(self):
        args = build_rcedit_args(RCEDIT, EXE, ResourcePatch(product_name="X"))
        assert args[0] == str(RCEDIT)
        assert args[1] == str(EXE)


class TestPatchResources:
    def test_empty_patch_skips_execution(self, monkeypatch):
        called = False

        def _fail(*a, **k):
            nonlocal called
            called = True
            raise AssertionError("should not run")

        monkeypatch.setattr(R.subprocess, "run", _fail)
        R.patch_resources(EXE, ResourcePatch(), rcedit=RCEDIT)
        assert called is False

    def test_runs_rcedit(self, monkeypatch):
        seen = {}

        class _Proc:
            returncode = 0
            stdout = ""
            stderr = ""

        def _run(args, **kw):
            seen["args"] = args
            return _Proc()

        monkeypatch.setattr(R.subprocess, "run", _run)
        R.patch_resources(EXE, ResourcePatch(product_name="X"), rcedit=RCEDIT)
        assert seen["args"][0] == str(RCEDIT)
        assert "--set-version-string" in seen["args"]

    def test_nonzero_exit_raises(self, monkeypatch):
        class _Proc:
            returncode = 1
            stdout = "boom"
            stderr = ""

        monkeypatch.setattr(R.subprocess, "run", lambda *a, **k: _Proc())
        with pytest.raises(WindowsBundleError, match="rcedit failed"):
            R.patch_resources(EXE, ResourcePatch(product_name="X"), rcedit=RCEDIT)

    def test_oserror_raises(self, monkeypatch):
        def _raise(*a, **k):
            raise OSError("not found")

        monkeypatch.setattr(R.subprocess, "run", _raise)
        with pytest.raises(WindowsBundleError, match="failed to run rcedit"):
            R.patch_resources(EXE, ResourcePatch(icon=Path("i.ico")), rcedit=RCEDIT)
