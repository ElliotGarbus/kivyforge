"""The generated PythonService subclasses + service probe (android/05 §services).

A manifest ``<service android:name="org.kivy.android.ServiceX">`` with no class
behind it builds cleanly and throws ClassNotFoundException the first time
anything starts it, so these tests are mostly about the manifest name and the
generated class agreeing, and about the class actually carrying the service's
Python entry point.
"""

from __future__ import annotations

import pytest

from kivyforge.config.model import AndroidNotification, AndroidService
from kivyforge.platforms.android.bootstrap.render import RenderError, render_bootstrap
from kivyforge.platforms.android.generate.manifest import service_class_name
from kivyforge.platforms.android.generate.services import (
    render_service_classes,
    render_service_contract_test,
)


def _by_path(files):
    return {f.relpath: f.content for f in files}


def _service(**kw) -> AndroidService:
    base = {"name": "Downloader", "entry_point": "service_downloader"}
    return AndroidService(**{**base, **kw})


class TestServiceBase:
    def test_base_and_helper_are_always_rendered(self):
        files = _by_path(render_bootstrap(sdl=2, python_version="3.14.6"))
        assert "java/org/kivy/android/PythonService.java" in files
        assert "java/org/kivy/android/PythonBundle.java" in files

    def test_base_loads_the_python_soname_for_its_own_process(self):
        """A service process has no SDLActivity to load libpython for it, so the
        base does it — with the stem the runtime actually ships."""
        files = _by_path(render_bootstrap(sdl=2, python_version="3.15.0"))
        service = files["java/org/kivy/android/PythonService.java"]
        assert 'PYTHON_LIB = "python3.15";' in service
        assert "python3.14" not in service
        assert 'System.loadLibrary("main")' in service

    def test_base_does_not_touch_sdl(self):
        """Services do background work; loading SDL there would create a second
        window-owning thread in a process with no Activity."""
        service = _by_path(render_bootstrap(sdl=2, python_version="3.14.6"))[
            "java/org/kivy/android/PythonService.java"
        ]
        code = [
            line
            for line in service.splitlines()
            if not line.lstrip().startswith(("*", "/*", "//"))
        ]
        assert not [line for line in code if "SDL" in line]

    def test_native_service_entry_is_exported(self):
        """PythonService.nativeStart() is resolved by JNI name from libmain."""
        main_c = _by_path(render_bootstrap(sdl=2, python_version="3.14.6"))[
            "cpp/main.c"
        ]
        assert "Java_org_kivy_android_PythonService_nativeStart" in main_c
        # Both entries must call the one launch sequence, or the service process
        # would come up with a differently-configured interpreter.
        assert main_c.count("kf_start_python()") == 2  # SDL_main + the service


class TestGeneratedServiceClasses:
    def test_class_name_matches_the_manifest(self):
        service = _service()
        rendered = render_service_classes((service,))
        assert len(rendered) == 1
        assert rendered[0].relpath == "java/org/kivy/android/ServiceDownloader.java"
        assert service_class_name(service).endswith(".ServiceDownloader")

    def test_class_carries_its_own_entry_point(self):
        source = render_service_classes((_service(entry_point="svc.worker"),))[
            0
        ].content
        assert "extends PythonService" in source
        assert 'return "svc.worker";' in source
        assert 'return "Downloader";' in source

    def test_background_service_has_no_notification_overrides(self):
        source = render_service_classes((_service(),))[0].content
        assert "isForeground" not in source
        assert "getChannelId" not in source

    def test_foreground_service_carries_its_notification(self):
        """The OS kills a foreground service that does not post a notification
        promptly, so the generated class must have one to post."""
        service = _service(
            foreground=True,
            foreground_service_type="dataSync",
            notification=AndroidNotification(
                channel_id="dl",
                channel_name="Downloads",
                title="Downloading",
                text="in progress",
                icon="ic_stat_dl",
            ),
        )
        source = render_service_classes((service,))[0].content
        assert "protected boolean isForeground() {\n        return true;" in source
        assert 'return "dl";' in source
        assert 'return "Downloads";' in source
        assert 'return "ic_stat_dl";' in source

    def test_foreground_service_without_an_icon_falls_back(self):
        service = _service(
            foreground=True,
            notification=AndroidNotification(
                channel_id="c", channel_name="C", title="T", text=""
            ),
        )
        source = render_service_classes((service,))[0].content
        assert "return null;" in source

    def test_notification_text_is_escaped(self):
        """Notification strings are free text from pyproject.toml and land in a
        Java string literal."""
        service = _service(
            foreground=True,
            notification=AndroidNotification(
                channel_id="c",
                channel_name="C",
                title='He said "hi"',
                text="a\\b",
            ),
        )
        source = render_service_classes((service,))[0].content
        assert 'return "He said \\"hi\\"";' in source
        assert 'return "a\\\\b";' in source

    def test_no_services_generates_nothing(self):
        assert render_service_classes(()) == []

    def test_every_service_gets_a_class(self):
        services = (_service(), _service(name="Uploader", entry_point="up"))
        rendered = {f.relpath for f in render_service_classes(services)}
        assert rendered == {
            "java/org/kivy/android/ServiceDownloader.java",
            "java/org/kivy/android/ServiceUploader.java",
        }


class TestServiceContractTest:
    def test_no_probe_without_services(self):
        assert render_service_contract_test(()) == []

    def test_probe_targets_the_first_service(self):
        rendered = render_service_contract_test((_service(),))
        assert len(rendered) == 1
        assert rendered[0].relpath == (
            "androidTest/java/org/kivyforge/test/KivyforgeServiceContractTest.java"
        )
        source = rendered[0].content
        assert "org.kivy.android.ServiceDownloader.class" in source
        # The marker, not a return value: a service entry point never returns.
        assert "kivyforge_service_Downloader.txt" in source
        assert "SERVICE_READY" in source
        assert "SERVICE_ENTRY_FAILED" in source


class TestLauncherServiceMarker:
    def test_launcher_stamps_and_reports(self):
        main_c = _by_path(render_bootstrap(sdl=2, python_version="3.14.6"))[
            "cpp/main.c"
        ]
        assert "KF_SERVICE_MARKER" in main_c
        assert "SERVICE_READY" in main_c
        assert "SERVICE_ENTRY_FAILED" in main_c


class TestTemplateDrift:
    def test_missing_python_lib_constant_is_caught(self, monkeypatch):
        from kivyforge.platforms.android.bootstrap import render as render_mod

        monkeypatch.setattr(render_mod, "_PROTO_SERVICE_PYTHON_LIB", "not-in-template")
        with pytest.raises(RenderError, match="PythonService.java template drifted"):
            render_bootstrap(sdl=2, python_version="3.14.6")
