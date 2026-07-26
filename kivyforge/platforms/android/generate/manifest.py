"""Generate ``AndroidManifest.xml`` (android/04 §manifest generation).

Deterministic emission from ``AndroidConfig``: permissions (bare names
auto-prefixed; nothing force-added beyond a foreground service's
``FOREGROUND_SERVICE*`` pair), implied non-required ``<uses-feature>``
synthesis (android/01 §auto_features), services/activities/intent filters,
attribute passthrough, and substituted raw-XML fragments (well-formedness was
already enforced at config time; fragments are re-parsed here as a belt).
"""

from __future__ import annotations

from xml.sax.saxutils import escape, quoteattr

from kivyforge.config.model import AndroidConfig, AndroidService

ANDROID_NS = "http://schemas.android.com/apk/res/android"
MAIN_ACTIVITY = "org.kivy.android.PythonActivity"
GENERATED_THEME = "@style/Theme.Kivyforge"

# Google's permission -> implied-hardware-feature table (android/01
# §implied features), including the two documented deliberate extras
# (USE_BIOMETRIC mirroring USE_FINGERPRINT; the API-31 Bluetooth pair).
IMPLIED_FEATURES: dict[str, tuple[str, ...]] = {
    "android.permission.CAMERA": (
        "android.hardware.camera",
        "android.hardware.camera.autofocus",
    ),
    "android.permission.RECORD_AUDIO": ("android.hardware.microphone",),
    "android.permission.ACCESS_FINE_LOCATION": (
        "android.hardware.location",
        "android.hardware.location.gps",
    ),
    "android.permission.ACCESS_COARSE_LOCATION": (
        "android.hardware.location",
        "android.hardware.location.network",
    ),
    "android.permission.BLUETOOTH": ("android.hardware.bluetooth",),
    "android.permission.BLUETOOTH_CONNECT": ("android.hardware.bluetooth",),
    "android.permission.BLUETOOTH_SCAN": (
        "android.hardware.bluetooth",
        "android.hardware.bluetooth_le",
    ),
    "android.permission.NFC": ("android.hardware.nfc",),
    "android.permission.USE_BIOMETRIC": ("android.hardware.fingerprint",),
    "android.permission.USE_FINGERPRINT": ("android.hardware.fingerprint",),
}

# [tool.kivy].orientation -> android:screenOrientation. A single value maps
# directly; the portrait pair / landscape pair map to their sensor variants;
# any wider mix means "let the sensor decide".
_ORIENTATION_MAP = {
    ("portrait",): "portrait",
    ("portrait-upside-down",): "reversePortrait",
    ("landscape-left",): "reverseLandscape",
    ("landscape-right",): "landscape",
}


class ManifestError(Exception):
    pass


def qualified_permissions(uses: tuple[str, ...]) -> list[str]:
    """Bare names get the ``android.permission.`` prefix; dotted pass verbatim."""
    return [p if "." in p else f"android.permission.{p}" for p in uses]


def implied_features(permissions: list[str]) -> list[str]:
    out: list[str] = []
    for permission in permissions:
        for feature in IMPLIED_FEATURES.get(permission, ()):
            if feature not in out:
                out.append(feature)
    return sorted(out)


def screen_orientation(orientation: tuple[str, ...]) -> str:
    key = tuple(sorted(orientation))
    if len(orientation) == 1:
        return _ORIENTATION_MAP[tuple(orientation)]
    if key == ("landscape-left", "landscape-right"):
        return "sensorLandscape"
    if key == ("portrait", "portrait-upside-down"):
        return "sensorPortrait"
    return "fullSensor"


def service_class_name(service: AndroidService) -> str:
    """The generated PythonService subclass FQCN (namespace preserved)."""
    return f"org.kivy.android.Service{service.name}"


def generate_manifest(android: AndroidConfig, *, orientation: tuple[str, ...]) -> str:
    permissions = qualified_permissions(android.permissions.uses)
    # A declared foreground service auto-adds FOREGROUND_SERVICE + the typed
    # permission — the ONLY implicit permissions (android/01 §managed keys).
    for service in android.services:
        if service.foreground:
            _add_unique(permissions, "android.permission.FOREGROUND_SERVICE")
            fstype = service.foreground_service_type or ""
            typed = "android.permission.FOREGROUND_SERVICE_" + _snake_upper(fstype)
            _add_unique(permissions, typed)

    lines: list[str] = []
    lines.append('<?xml version="1.0" encoding="utf-8"?>')
    lines.append(f'<manifest xmlns:android="{ANDROID_NS}">')

    for permission in permissions:
        lines.append(f"    <uses-permission android:name={quoteattr(permission)} />")

    # Explicit features override the synthesized entry for the same name.
    explicit = {f.name: f.required for f in android.permissions.features}
    synthesized = (
        [f for f in implied_features(permissions) if f not in explicit]
        if android.permissions.auto_features
        else []
    )
    for name in synthesized:
        lines.append(
            f"    <uses-feature android:name={quoteattr(name)} "
            'android:required="false" />'
        )
    for feature in android.permissions.features:
        required = "true" if feature.required else "false"
        lines.append(
            f"    <uses-feature android:name={quoteattr(feature.name)} "
            f'android:required="{required}" />'
        )

    if android.manifest.extra_manifest_xml.strip():
        lines.append(_substitute(android.manifest.extra_manifest_xml, android))

    app_attrs: dict[str, str] = {
        "android:label": "@string/app_name",
        "android:icon": "@mipmap/ic_launcher",
        "android:theme": GENERATED_THEME,
        # extractNativeLibs is controlled via app/build.gradle's
        # packaging.jniLibs.useLegacyPackaging (AGP warns if set in the
        # manifest); the gradle setting is the toolchain-managed source.
    }
    for key, value in sorted(android.manifest.application.items()):
        app_attrs[key] = _attr_str(value)
    lines.append(f"    <application {_attrs(app_attrs)}>")

    activity_attrs: dict[str, str] = {
        "android:name": MAIN_ACTIVITY,
        "android:exported": "true",
        "android:configChanges": "keyboardHidden|orientation|screenSize",
        "android:screenOrientation": screen_orientation(orientation),
        "android:theme": GENERATED_THEME,
    }
    for key, value in sorted(android.manifest.activity.items()):
        activity_attrs[key] = _attr_str(value)
    lines.append(f"        <activity {_attrs(activity_attrs)}>")
    lines.append("            <intent-filter>")
    lines.append('                <action android:name="android.intent.action.MAIN" />')
    lines.append(
        '                <category android:name="android.intent.category.LAUNCHER" />'
    )
    lines.append("            </intent-filter>")

    for entry in android.intent_filters:
        lines.append("            <intent-filter>")
        lines.append(
            f"                <action android:name={quoteattr(entry.action)} />"
        )
        for category in entry.categories:
            lines.append(
                f"                <category android:name={quoteattr(category)} />"
            )
        for data in entry.data:
            attrs = " ".join(
                f"android:{k}={quoteattr(v)}" for k, v in sorted(data.items())
            )
            lines.append(f"                <data {attrs} />")
        lines.append("            </intent-filter>")

    if android.manifest.extra_activity_xml.strip():
        lines.append(_substitute(android.manifest.extra_activity_xml, android))
    lines.append("        </activity>")

    for extra in android.activities:
        lines.append(
            f"        <activity android:name={quoteattr(extra.name)} "
            f'android:exported="{_b(extra.exported)}" />'
        )

    for service in android.services:
        attrs = {
            "android:name": service_class_name(service),
            "android:process": f":service_{service.name.lower()}",
            "android:exported": _b(service.exported),
        }
        if service.foreground:
            attrs["android:foregroundServiceType"] = (
                service.foreground_service_type or ""
            )
        lines.append(f"        <service {_attrs(attrs)} />")

    if android.manifest.extra_application_xml.strip():
        lines.append(_substitute(android.manifest.extra_application_xml, android))

    lines.append("    </application>")
    lines.append("</manifest>")
    text = "\n".join(lines) + "\n"
    _assert_well_formed(text)
    return text


def _substitute(fragment: str, android: AndroidConfig) -> str:
    out = fragment.replace("${applicationId}", android.package)
    for key, value in android.manifest.placeholders.items():
        out = out.replace("${" + key + "}", value)
    return "\n".join(f"    {line}" for line in out.strip().splitlines())


def _assert_well_formed(text: str) -> None:
    import xml.etree.ElementTree as ET

    try:
        ET.fromstring(text)
    except ET.ParseError as exc:  # pragma: no cover - config validation upstream
        raise ManifestError(
            f"generated AndroidManifest.xml is not well-formed: {exc}"
        ) from exc


def _attrs(attrs: dict[str, str]) -> str:
    return " ".join(f"{k}={quoteattr(v)}" for k, v in attrs.items())


def _attr_str(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return escape(str(value))


def _b(value: bool) -> str:
    return "true" if value else "false"


def _snake_upper(camel: str) -> str:
    out: list[str] = []
    for ch in camel:
        if ch.isupper():
            out.append("_")
        out.append(ch.upper())
    return "".join(out)


def _add_unique(items: list[str], value: str) -> None:
    if value not in items:
        items.append(value)
