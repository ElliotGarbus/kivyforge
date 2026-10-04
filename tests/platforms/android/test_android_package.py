"""The bundled ``android`` package and the Java it calls (issue #72).

The Python half is python-for-android's modules, unchanged; the Java half is
kivyforge's PythonActivity. Nothing compiles or runs either here, so these
tests tie the two together by name: every activity member and nested interface
the modules use must be declared by the rendered activity, for both
generations. The on-device half is the self-test's ANDROID_PKG_OK marker.
"""

from __future__ import annotations

import ast
import copy
import importlib
import re
import sys
import types
import webbrowser
from typing import Any
from unittest import mock

import pytest

from kivyforge.platforms.android.bootstrap.render import (
    P4A_DIR,
    TEMPLATES_DIR,
    RenderError,
    android_package_sources,
    render_bootstrap,
    selftest_source,
)

# android.app.Activity's own API, which the modules also call; everything else
# they call on the activity must come from kivyforge's PythonActivity.
_ACTIVITY_API = {
    "getApplication",
    "getApplicationContext",
    "registerActivityLifecycleCallbacks",
    "runOnUiThread",
    "unregisterActivityLifecycleCallbacks",
}
_ACTIVITY_CALL = re.compile(r"\b(?:mActivity|_activity)\.([A-Za-z_]\w*)\(")
_NESTED_INTERFACE = re.compile(r"ACTIVITY_CLASS_NAMESPACE \+ '\$(\w+)'")
_JNI_CLASS = re.compile(r"JNI_NAMESPACE \+ '/(\w+)'")
_JAVA_CLASS = re.compile(r"JAVA_NAMESPACE \+ '\.(\w+)'")


def _vendored_modules() -> dict[str, str]:
    return {
        p.name: p.read_text(encoding="utf-8")
        for p in sorted((P4A_DIR / "android").glob("*.py"))
    }


def _rendered(sdl: int) -> dict[str, str]:
    return {
        f.relpath: f.content for f in render_bootstrap(sdl=sdl, python_version="3.14.6")
    }


def _activity(sdl: int) -> str:
    return _rendered(sdl)["java/org/kivy/android/PythonActivity.java"]


def _declares_method(java: str, name: str) -> bool:
    return (
        re.search(rf"^\s+(public|protected)\b[^;=]*\b{name}\(", java, re.M) is not None
    )


@pytest.mark.parametrize("sdl", [2, 3])
class TestJavaContract:
    def test_every_activity_member_the_modules_call_is_declared(self, sdl):
        java = _activity(sdl)
        called = set()
        for source in _vendored_modules().values():
            called |= set(_ACTIVITY_CALL.findall(source))
        assert called - _ACTIVITY_API, "the pattern found nothing to check"
        missing = sorted(
            name for name in called - _ACTIVITY_API if not _declares_method(java, name)
        )
        assert missing == []

    def test_every_nested_interface_the_modules_implement_is_declared(self, sdl):
        java = _activity(sdl)
        wanted = set()
        for source in _vendored_modules().values():
            wanted |= set(_NESTED_INTERFACE.findall(source))
        assert wanted == {
            "ActivityResultListener",
            "DarkModeListener",
            "NewIntentListener",
            "PermissionsCallback",
        }
        for name in wanted:
            assert f"public interface {name} {{" in java

    def test_every_namespace_class_the_modules_use_is_rendered(self, sdl):
        rendered = _rendered(sdl)
        wanted = set()
        for source in _vendored_modules().values():
            wanted |= set(_JNI_CLASS.findall(source)) | set(_JAVA_CLASS.findall(source))
        assert wanted == {
            "GenericBroadcastReceiver",
            "GenericBroadcastReceiverCallback",
        }
        for name in wanted:
            assert f"java/org/kivy/android/{name}.java" in rendered

    def test_change_keyboard_is_declared_once(self, sdl):
        java = _activity(sdl)
        assert java.count("public static void changeKeyboard(int inputType) {") == 1

    def test_result_and_intent_overrides_reach_sdl(self, sdl):
        # SDLActivity takes results through these (SDL3's file dialog), so the
        # listener dispatch must not end the call before super.
        java = _activity(sdl)
        assert "super.onActivityResult(requestCode, resultCode, intent);" in java
        assert "super.onNewIntent(intent);" in java

    def test_configuration_changes_reach_sdl(self, sdl):
        # SDL3 forwards theme changes to native code from its own override.
        assert "super.onConfigurationChanged(newConfig);" in _activity(sdl)


class TestChangeKeyboard:
    def test_sdl2_sets_the_glue_field(self):
        java = _activity(2)
        assert "SDLActivity.keyboardInputType = inputType;" in java
        assert "imm.restartInput(mTextEdit);" in java

    def test_the_sdl2_glue_has_the_field_it_sets(self):
        glue = (TEMPLATES_DIR / "sdl2/org/libsdl/app/SDLActivity.java").read_text(
            encoding="utf-8"
        )
        assert "public static int keyboardInputType" in glue
        assert "outAttrs.inputType = SDLActivity.keyboardInputType;" in glue
        assert "protected static DummyEdit mTextEdit;" in glue

    def test_sdl3_gets_the_commented_out_member(self):
        # SDL3's glue has no keyboardInputType; Kivy 3 never calls this.
        java = _activity(3)
        start = java.index("public static void changeKeyboard(int inputType) {")
        body = java[start : java.index("// END p4a change-keyboard")]
        code = re.sub(r"/\*.*?\*/", "", body, flags=re.S)
        assert "keyboardInputType" not in code
        assert "keyboardInputType" in body

    def test_a_missing_fence_is_a_render_error(self, monkeypatch):
        from kivyforge.platforms.android.bootstrap import render

        monkeypatch.setattr(render, "_CHANGE_KEYBOARD_END", "    // nowhere\n")
        with pytest.raises(RenderError, match="change-keyboard"):
            render_bootstrap(sdl=2, python_version="3.14.6")


class TestPackageSources:
    def test_contents(self):
        sources = android_package_sources(2)
        assert sorted(sources) == [
            "android/__init__.py",
            "android/activity.py",
            "android/broadcast.py",
            "android/config.py",
            "android/darkmode.py",
            "android/loadingscreen.py",
            "android/permissions.py",
            "android/runnable.py",
            "android/storage.py",
        ]
        for path, source in sources.items():
            compile(source, path, "exec")

    @pytest.mark.parametrize("sdl", [2, 3])
    def test_config_matches_python_for_android_for_the_generation(self, sdl):
        namespace: dict[str, object] = {}
        exec(android_package_sources(sdl)["android/config.py"], namespace)
        config = {k: v for k, v in namespace.items() if k.isupper()}
        assert config == {
            "BOOTSTRAP": f"sdl{sdl}",
            "IS_SDL2": int(sdl == 2),
            "IS_SDL3": int(sdl == 3),
            "PY2": 0,
            "ANDROID_LIBS_DIR": "",
            "JAVA_NAMESPACE": "org.kivy.android",
            "JNI_NAMESPACE": "org/kivy/android",
            "ACTIVITY_CLASS_NAME": "org.kivy.android.PythonActivity",
            "ACTIVITY_CLASS_NAMESPACE": "org/kivy/android/PythonActivity",
            "SERVICE_CLASS_NAME": "org.kivy.android.PythonService",
        }

    def test_the_exported_names_are_pinned(self):
        """``from android import *`` must not grow by accident: a name exported
        once is a name someone imports and that cannot be taken back."""
        tree = ast.parse(android_package_sources(2)["android/__init__.py"])
        (exported,) = [
            node.value
            for node in tree.body
            if isinstance(node, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets)
        ]
        assert ast.literal_eval(exported) == [
            "AndroidBrowser",
            "PythonJavaClass",
            "api_version",
            "autoclass",
            "cast",
            "java_method",
            "mActivity",
            "open_url",
            "python_act",
            "remove_presplash",
            "version_codes",
        ]

    def test_the_selftest_checks_the_package_on_device(self):
        source = selftest_source()
        assert "ANDROID_PKG_OK" in source
        java = (TEMPLATES_DIR / "androidtest/KivyforgeContractTest.java").read_text(
            encoding="utf-8"
        )
        assert "ANDROID_PKG_OK" in java


class _FakeJavaClass:
    pass


@pytest.fixture
def device(tmp_path, monkeypatch):
    """The rendered package importable as on a device, over a fake jnius and a
    fake _kivy_bootstrap whose activity the test can swap."""
    for rel, source in android_package_sources(2).items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))

    classes: dict[str, mock.MagicMock] = {}

    def autoclass(name):
        return classes.setdefault(name, mock.MagicMock(name=name))

    jnius = types.ModuleType("jnius")
    jnius.autoclass = autoclass  # type: ignore[attr-defined]
    jnius.cast = lambda _name, obj: obj  # type: ignore[attr-defined]
    jnius.PythonJavaClass = _FakeJavaClass  # type: ignore[attr-defined]
    jnius.java_method = lambda *_a, **_k: lambda f: f  # type: ignore[attr-defined]
    bootstrap = types.ModuleType("_kivy_bootstrap")
    state = types.SimpleNamespace(activity=mock.MagicMock(name="activity-1"))
    bootstrap.get_activity = lambda: state.activity  # type: ignore[attr-defined]
    # The package registers a browser on import; keep it out of other tests.
    for registry in ("_browsers", "_tryorder"):
        value = getattr(webbrowser, registry)
        monkeypatch.setattr(webbrowser, registry, copy.copy(value))
    monkeypatch.setitem(sys.modules, "jnius", jnius)
    monkeypatch.setitem(sys.modules, "_kivy_bootstrap", bootstrap)
    for name in _android_modules():
        monkeypatch.delitem(sys.modules, name)
    android: Any = importlib.import_module("android")
    yield types.SimpleNamespace(android=android, state=state, classes=classes)
    for name in _android_modules():
        del sys.modules[name]


def _android_modules() -> list[str]:
    return [m for m in sys.modules if m == "android" or m.startswith("android.")]


class TestPackageRuntime:
    def test_mactivity_is_read_on_each_access(self, device):
        assert device.android.mActivity is device.state.activity
        device.state.activity = mock.MagicMock(name="activity-2")
        assert device.android.mActivity is device.state.activity

    def test_from_import_binds_the_current_activity(self, device):
        namespace: dict[str, object] = {}
        exec("from android import mActivity", namespace)
        assert namespace["mActivity"] is device.state.activity

    def test_unknown_names_raise_attribute_error(self, device):
        with pytest.raises(AttributeError, match="no attribute 'vibrate'"):
            device.android.vibrate  # noqa: B018

    def test_star_import_gives_exactly_all(self, device):
        namespace: dict[str, object] = {}
        exec("from android import *", namespace)
        names = sorted(k for k in namespace if k != "__builtins__")
        assert names == sorted(device.android.__all__)

    def test_presplash_and_loading_screen_are_no_ops(self, device):
        loadingscreen: Any = importlib.import_module("android.loadingscreen")
        assert device.android.remove_presplash() is None
        assert loadingscreen.hide_loading_screen() is None
        device.state.activity.removeLoadingScreen.assert_not_called()

    def test_open_url_starts_a_view_intent(self, device):
        assert device.android.open_url("https://kivy.org") is True
        intent = device.classes["android.content.Intent"].return_value
        intent.setAction.assert_called_once()
        device.state.activity.startActivity.assert_called_once_with(intent)

    def test_registers_a_webbrowser(self, device):
        assert isinstance(webbrowser.get("android"), device.android.AndroidBrowser)

    def test_every_vendored_module_imports(self, device):
        """Import-time failures (a renamed config key, a missing module) are
        what this catches; the Java calls themselves only run on a device."""
        for rel in android_package_sources(2):
            module = rel.removesuffix(".py").removesuffix("/__init__")
            importlib.import_module(module.replace("/", "."))
