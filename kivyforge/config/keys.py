"""The keys kivyforge recognises under ``[tool.kivy]``.

The loader reads every value by name, so a key it does not know -- a typo, a
table the design specifies but no release implements yet, or a key from a
newer kivyforge -- used to be dropped without a word, and the build went ahead
as if it had never been written. This is the complete allow-list, checked
before any value is parsed, so a misspelt *required* key reports as a typo
rather than as missing.

Only the ``tool.kivy`` subtree is checked: ``[project]`` belongs to PEP 621 and
the rest of ``[tool]`` to other tools. Tables whose keys belong to someone else
-- Info.plist, entitlements, Xcode build settings, manifest attributes,
gradle.properties -- are :data:`OPEN`. Types are not checked here; the parsers
own that and say more about it.

A key the loader reads must be listed here, or every project that sets it
fails; the loader tests exercise each parser, so that drift cannot ship quietly.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass


class _Open:
    """Any key is allowed: the table is passed through to another tool."""

    def __repr__(self) -> str:
        return "OPEN"


OPEN = _Open()


@dataclass(frozen=True)
class Each:
    """A table keyed by names the user chooses, each value an ``entry`` table."""

    entry: dict[str, Spec]


@dataclass(frozen=True)
class ArrayOf:
    """An array of tables (``[[...]]``), each an ``entry`` table."""

    entry: dict[str, Spec]


#: ``None`` is a leaf: a scalar, a list, or an inline table a parser validates
#: whole (a swift ``requirement``, intent-filter ``data``).
type Spec = None | _Open | Each | ArrayOf | dict[str, Spec]

_TRI_STATE_BUILD_SETTINGS: dict[str, Spec] = {
    "byte_compile": None,
    "strip_source": None,
}
_ICONS: dict[str, Spec] = {"source": None}
_ARTIFACT: dict[str, Spec] = {"version": None, "source": None}

# Keys every platform overlay shares.
_OVERLAY_COMMON: dict[str, Spec] = {
    "schema_version": None,
    "extra_index_urls": None,
    "find_links": None,
    "exclude": None,
}

_DESKTOP_COMMON: dict[str, Spec] = {
    **_OVERLAY_COMMON,
    "archs": None,
    "python": {"version": None},
    "icons": _ICONS,
    "native": {"binaries": Each(_ARTIFACT)},
    "build_settings": _TRI_STATE_BUILD_SETTINGS,
}

IOS: dict[str, Spec] = {
    **_OVERLAY_COMMON,
    "bundle_id": None,
    "build": None,
    "deployment_target": None,
    "simulator_archs": None,
    "python": {"version": None, "build_settings": _TRI_STATE_BUILD_SETTINGS},
    "icons": _ICONS,
    "splash": {"source": None, "background": None},
    "native": {
        "xcframeworks": Each(
            {"version": None, "source": None, "link": None, "embed": None}
        ),
        "swift_packages": Each(
            {
                "url": None,
                "path": None,
                "requirement": None,
                "products": None,
                "link": None,
                "embed": None,
            }
        ),
    },
    "signing": {
        "team_id": None,
        "identity": None,
        "provisioning_profile": None,
        "auto_signing": None,
        "upload_symbols": None,
    },
    "info_plist": OPEN,
    "xcode": {"build_settings": OPEN},
    "privacy_manifest": {"source": None},
    "entitlements": OPEN,
}

MACOS: dict[str, Spec] = {
    **_DESKTOP_COMMON,
    "bundle_id": None,
    "build": None,
    "minimum_system_version": None,
    "entitlements": OPEN,
    "signing": {"identity": None, "team_id": None, "notary_profile": None},
}

LINUX: dict[str, Spec] = {
    **_DESKTOP_COMMON,
    "app_id": None,
    "glibc_floor": None,
    "desktop": {"categories": None},
}

WINDOWS: dict[str, Spec] = {
    **_DESKTOP_COMMON,
    "app_id": None,
    "signing": {"thumbprint": None, "timestamp_url": None, "store_scope": None},
}

ANDROID: dict[str, Spec] = {
    **_OVERLAY_COMMON,
    "package": None,
    "build": None,
    "version_code": None,
    "min_sdk": None,
    "target_sdk": None,
    "compile_sdk": None,
    "kivy_generation": None,
    "abis": None,
    "base_theme": None,
    "python": {"version": None},
    "permissions": {
        "uses": None,
        "features": ArrayOf({"name": None, "required": None}),
        "auto_features": None,
    },
    "icons": {"source": None, "background": None, "monochrome": None},
    "splash": {
        "source": None,
        "background": None,
        "icon_background": None,
        "animation_duration": None,
        "branding": None,
    },
    "native": {"aars": Each(_ARTIFACT), "jars": Each(_ARTIFACT)},
    "gradle": {"dependencies": None, "repositories": None},
    "include_files": ArrayOf({"dest": None, "sources": None}),
    "src": {"java": None, "kotlin": None},
    "services": ArrayOf(
        {
            "name": None,
            "entry_point": None,
            "exported": None,
            "foreground": None,
            "foreground_service_type": None,
            "notification": {
                "channel_id": None,
                "channel_name": None,
                "title": None,
                "text": None,
                "icon": None,
            },
        }
    ),
    "activities": ArrayOf({"name": None, "exported": None}),
    "intent_filters": ArrayOf({"action": None, "categories": None, "data": None}),
    "manifest": {
        "application": OPEN,
        "activity": OPEN,
        "placeholders": OPEN,
        "allow_exported": None,
        "extra_manifest_xml": None,
        "extra_application_xml": None,
        "extra_activity_xml": None,
    },
    "signing": {
        "keystore": None,
        "key_alias": None,
        "store_password_env": None,
        "key_password_env": None,
        "v1_signing": None,
        "v2_signing": None,
        "v3_signing": None,
        "v4_signing": None,
    },
    "gradle_properties": OPEN,
    "build_settings": {
        "minify": None,
        "shrink_resources": None,
        "multidex": None,
        "byte_compile": None,
        "strip_source": None,
        "strip_native_libs": None,
        "debug_symbols": None,
    },
}

TOOL_KIVY: dict[str, Spec] = {
    "app_dir": None,
    "display_name": None,
    "entry_point": None,
    "orientation": None,
    "ios": IOS,
    "macos": MACOS,
    "linux": LINUX,
    "windows": WINDOWS,
    "android": ANDROID,
}


@dataclass(frozen=True)
class UnknownKey:
    """A key under ``[tool.kivy]`` that kivyforge does not read."""

    #: Where it sits, e.g. ``tool.kivy.android.services[0]``.
    table: str
    key: str
    #: ``table`` without array indices: the dotted name a ``[header]`` spells.
    header: str
    #: The keys that *are* valid in ``table``, sorted.
    known: tuple[str, ...]

    @property
    def key_path(self) -> str:
        return f"{self.table}.{self.key}"

    @property
    def suggestion(self) -> str | None:
        matches = difflib.get_close_matches(self.key, self.known, n=1, cutoff=0.6)
        return matches[0] if matches else None


def find_unknown_keys(kivy: dict) -> list[UnknownKey]:
    """Every key in a parsed ``[tool.kivy]`` table that is not in the schema.

    An unknown *table* directly under ``[tool.kivy]`` is not reported: spec 01
    promises that an overlay for a platform this release does not implement
    breaks no current command. That stays safe because an overlay only takes
    effect when a verb targets it, and targeting a misspelt one fails as
    missing (see :func:`overlay_suggestion`).
    """
    found: list[UnknownKey] = []
    _walk(kivy, TOOL_KIVY, "tool.kivy", "tool.kivy", found)
    return [
        u
        for u in found
        if not (u.table == "tool.kivy" and isinstance(kivy.get(u.key), dict))
    ]


def overlay_suggestion(kivy: object, platform: str) -> str | None:
    """An unrecognised ``[tool.kivy.*]`` table that looks like ``platform``."""
    if not isinstance(kivy, dict):
        return None
    candidates = [
        k for k, v in kivy.items() if isinstance(v, dict) and k not in TOOL_KIVY
    ]
    matches = difflib.get_close_matches(platform, candidates, n=1, cutoff=0.6)
    return matches[0] if matches else None


def _walk(
    value: object, spec: Spec, table: str, header: str, found: list[UnknownKey]
) -> None:
    if isinstance(spec, Each):
        if isinstance(value, dict):
            for name, entry in value.items():
                _walk(entry, spec.entry, f"{table}.{name}", f"{header}.{name}", found)
    elif isinstance(spec, ArrayOf):
        if isinstance(value, list):
            for i, entry in enumerate(value):
                _walk(entry, spec.entry, f"{table}[{i}]", header, found)
    elif isinstance(spec, dict) and isinstance(value, dict):
        for key, child in value.items():
            if key in spec:
                _walk(child, spec[key], f"{table}.{key}", f"{header}.{key}", found)
            else:
                found.append(UnknownKey(table, key, header, tuple(sorted(spec))))
