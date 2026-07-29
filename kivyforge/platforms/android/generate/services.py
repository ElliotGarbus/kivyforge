"""Generate the ``PythonService`` subclasses for ``[[services]]`` (android/05).

The manifest declares ``org.kivy.android.Service<Name>`` for every configured
service; a manifest entry with no class behind it compiles and links fine and
then throws ``ClassNotFoundException`` the first time anything starts the
service. These are the classes behind those names: each one is a few overrides
naming its Python entry point and, for a foreground service, the notification
the OS requires.

The instrumented service contract test is generated alongside them (and only
when a service exists — there is nothing to test otherwise). It starts the first
declared service and waits for the ready marker the interpreter stamps, which is
what proves the whole chain: the manifest name resolves, the service process
starts, the bundle unpacks in a second process, and the interpreter comes up.
"""

from __future__ import annotations

from kivyforge.config.model import AndroidService

from ..bootstrap.render import RenderedFile

SERVICE_PACKAGE = "org.kivy.android"


def service_class_simple_name(service: AndroidService) -> str:
    """``Downloader`` -> ``ServiceDownloader`` (matches the manifest emitter)."""
    return f"Service{service.name}"


def render_service_classes(services: tuple[AndroidService, ...]) -> list[RenderedFile]:
    """One ``PythonService`` subclass per declared service."""
    out: list[RenderedFile] = []
    for service in services:
        name = service_class_simple_name(service)
        out.append(
            RenderedFile(
                f"java/org/kivy/android/{name}.java",
                _service_source(service, class_name=name),
            )
        )
    return out


def _service_source(service: AndroidService, *, class_name: str) -> str:
    overrides = [
        _override("String", "getServiceName", _java_string(service.name)),
        _override("String", "getEntryPoint", _java_string(service.entry_point)),
    ]
    if service.foreground:
        overrides.append(_override("boolean", "isForeground", "true"))
        note = service.notification
        if note is not None:
            overrides += [
                _override("String", "getChannelId", _java_string(note.channel_id)),
                _override("String", "getChannelName", _java_string(note.channel_name)),
                _override("String", "getNotificationTitle", _java_string(note.title)),
                _override("String", "getNotificationText", _java_string(note.text)),
                _override(
                    "String",
                    "getNotificationIcon",
                    _java_string(note.icon) if note.icon else "null",
                ),
            ]
    return (
        f"package {SERVICE_PACKAGE};\n"
        "\n"
        "/**\n"
        f" * Generated from [[tool.kivy.android.services]] entry {service.name!r}\n"
        " * (android/05 §services). Regenerated on every build — edit\n"
        " * pyproject.toml, not this file.\n"
        " */\n"
        f"public class {class_name} extends PythonService {{\n"
        + "\n".join(overrides)
        + "}\n"
    )


def _override(return_type: str, method: str, value: str) -> str:
    return (
        "    @Override\n"
        f"    protected {return_type} {method}() {{\n"
        f"        return {value};\n"
        "    }\n"
    )


def _java_string(value: str) -> str:
    escaped = (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
    )
    return f'"{escaped}"'


def render_service_contract_test(
    services: tuple[AndroidService, ...],
) -> list[RenderedFile]:
    """The instrumented service probe, or nothing when no service is declared."""
    if not services:
        return []
    service = services[0]
    class_name = service_class_simple_name(service)
    source = f"""\
package org.kivyforge.test;

import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import android.content.Context;
import android.content.Intent;
import androidx.test.core.app.ApplicationProvider;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import org.junit.Test;
import org.junit.runner.RunWith;

/**
 * The kivyforge service contract test, generated for [[services]] entry
 * {service.name!r} (android/05 §services, android/06 --smoke).
 *
 * A declared service is only real if its manifest name resolves to a class, its
 * process starts, and an interpreter comes up there. The service's Python
 * normally never returns, so the probe waits for the marker the launcher stamps
 * once the interpreter is up and the finder installed.
 */
@RunWith(AndroidJUnit4.class)
public class KivyforgeServiceContractTest {{

    private static final int TIMEOUT_MS = 90_000;
    private static final String MARKER = "kivyforge_service_{service.name}.txt";

    @Test
    public void declaredServiceStartsAnInterpreter() throws Exception {{
        Context ctx = ApplicationProvider.getApplicationContext();
        File marker = new File(ctx.getFilesDir(), MARKER);
        marker.delete();

        Intent intent = new Intent(ctx, org.kivy.android.{class_name}.class);
        ctx.startService(intent);

        long deadline = System.currentTimeMillis() + TIMEOUT_MS;
        String contents = "";
        while (System.currentTimeMillis() < deadline) {{
            if (marker.exists()) {{
                contents = new String(
                    Files.readAllBytes(marker.toPath()), StandardCharsets.UTF_8);
                if (contents.contains("SERVICE_READY")) {{
                    break;
                }}
            }}
            Thread.sleep(500);
        }}
        assertTrue(
            "service {service.name} did not start an interpreter within "
                + TIMEOUT_MS + "ms; got: " + contents,
            contents.contains("SERVICE_READY"));

        // The entry-point import happens right after the marker, so give it a
        // moment and confirm it did not blow up.
        Thread.sleep(2000);
        if (marker.exists()) {{
            contents = new String(
                Files.readAllBytes(marker.toPath()), StandardCharsets.UTF_8);
        }}
        assertFalse(
            "service entry point {service.entry_point} raised on import: "
                + contents,
            contents.contains("SERVICE_ENTRY_FAILED"));
        assertFalse(
            "service native start failed: " + contents,
            contents.contains("SERVICE_START_FAILED"));

        ctx.stopService(intent);
    }}
}}
"""
    return [
        RenderedFile(
            "androidTest/java/org/kivyforge/test/KivyforgeServiceContractTest.java",
            source,
        )
    ]
