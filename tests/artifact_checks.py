"""Post-build assertions on a produced artifact — tier T3 in ``test-matrix.md``.

Everything here is a **file read on a finished artifact**: no device, no human,
no toolchain beyond the build that already happened. That is the whole appeal.
Roadmap item 1 shipped a `strip_source` that had never once run on a mobile
target, and CI was building the affected artifact the entire time and throwing
it away unexamined — a single pass over the zip would have caught it on day one.

The functions return **lists of problem strings rather than asserting**, so one
run reports every fault instead of stopping at the first, and so they can be
unit-tested against synthetic artifacts without a build. Same shape as
``scripts/check_sdl_glue_sync.py``.

ELF headers are parsed from the 20 bytes read straight out of the zip rather
than via ``platforms/android/elf.py``'s :func:`read_elf`, which takes a
``Path``: extracting 120 shared objects to disk to look at six bytes of each is
not worth it. The *constants* are imported from that module even so, so the
machine codes asserted here cannot drift from the ones the build uses.

The Linux half works on a **directory**, not an archive: a type-2 AppImage is an
ELF with a squashfs filesystem appended, so ``zipfile`` cannot read it and there
is no stdlib squashfs reader. The driver extracts it (``--appimage-extract`` on
a native-arch image, ``unsquashfs`` at the squashfs offset when the type2
runtime is foreign) and points these at the resulting tree; the AppDir is also
directly buildable via ``kivyforge package -f folder``. Checks that can only be
made on the single file — that it is an AppImage at all, and for which arch —
live in :func:`linux_appimage_file_problems` so the container itself is covered
rather than assumed.

Paths *inside* an artifact are always rendered with ``as_posix()``, never by
interpolating a ``Path``. The artifact is a Linux or Apple bundle whatever host
is reading it, so ``usr/app/main.py`` is the only correct spelling — inspecting
an extracted AppDir from Windows must not start reporting ``usr\\app\\main.py``.

**The no-toolchain rule has one shape of exception, and it is kept at arm's
length.** Signature verification genuinely needs a tool (``apksigner``,
``signtool``, ``codesign``) — there is no reading a signature out of a file by
hand. So the *spawn* stays in the platform's driver module, where it can skip
or fail on the tool's absence like any other toolchain test, and only the pure
**parse** of that tool's report lives here (:func:`apksigner_report_problems`).
That keeps every function in this module hermetically testable, which is the
property the rule was protecting.
"""

from __future__ import annotations

import os
import plistlib
import posixpath
import re
import shlex
import struct
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from kivyforge.config.model import AndroidConfig, Config
from kivyforge.platforms.android.elf import EM_AARCH64, EM_X86_64, machine_name
from kivyforge.platforms.android.generate.manifest import (
    GENERATED_THEME,
    MAIN_ACTIVITY,
    effective_features,
    effective_permissions,
    screen_orientation,
    service_class_name,
)
from kivyforge.platforms.ios.plist import build_info_plist as ios_build_info_plist
from kivyforge.platforms.linux.elftools import (
    ARCH_ELF,
    ELF_MAGIC,
    ElfError,
    describe,
    elf_machine,
    is_elf,
)
from kivyforge.platforms.macos.machotools import (
    CPU_TYPE_ARM64,
    CPU_TYPE_X86_64,
    MachoError,
    cpu_type_name,
    read_macho_cpu_type,
)
from kivyforge.platforms.macos.plist import build_info_plist
from kivyforge.platforms.windows.launcher import BOOTSTRAP_NAME
from kivyforge.platforms.windows.pathdepth import (
    MIN_FOLDER_HEADROOM,
    deepest_relative_path,
    folder_headroom,
)
from kivyforge.platforms.windows.petools import (
    IMAGE_FILE_MACHINE_AMD64,
    IMAGE_FILE_MACHINE_ARM64,
    read_pe_machine,
)
from kivyforge.platforms.windows.petools import machine_name as pe_machine_name

BUNDLE_ROOT = "assets/_python_bundle/"

_LIBPYTHON = re.compile(r"^lib/[^/]+/libpython(\d+\.\d+)\.so$")

# Android's dashed ABI directory names (the wheel-tag spelling with underscores
# is what pyproject uses; the generator maps between them) to the ELF e_machine
# every shared object under lib/<abi>/ must report. 64-bit only, permanently:
# the python.org Android runtime ships no 32-bit build.
ABI_MACHINES = {"arm64-v8a": EM_AARCH64, "x86_64": EM_X86_64}

ELFCLASS64 = 2


def shipped_python_tags(apk: Path) -> list[str]:
    """The CPython minor(s) whose runtime *apk* actually ships, e.g. ``["3.14"]``.

    Read out of the artifact rather than passed in, so the expected ``.pyc``
    magic is anchored to the runtime that will do the importing. Passing the
    version in would let a caller assert an APK against the wrong runtime and
    get a green result, which is the shape of bug these checks exist to catch.
    """
    with zipfile.ZipFile(apk) as zf:
        found = {m.group(1) for m in map(_LIBPYTHON.match, zf.namelist()) if m}
    return sorted(found)


def android_apk_problems(
    apk: Path,
    *,
    abi: str,
    stripped: bool,
    expected_magic: bytes,
) -> list[str]:
    """Every way *apk* fails to be the artifact the build promised.

    ``abi`` is the dashed Android name (``arm64-v8a``), ``stripped`` whether
    ``strip_source`` applied to this build, and ``expected_magic`` the first four
    bytes a ``.pyc`` the shipped runtime can import must carry — see
    :func:`shipped_python_tags` for choosing it.
    """
    if abi not in ABI_MACHINES:
        return [f"unknown ABI {abi!r}; expected one of {sorted(ABI_MACHINES)}"]

    with zipfile.ZipFile(apk) as zf:
        names = zf.namelist()
        problems = _required_entry_problems(names, abi=abi)
        problems += _payload_problems(names, stripped=stripped)
        problems += _native_lib_problems(zf, names, abi=abi)
        if stripped:
            problems += _pyc_magic_problems(zf, names, expected_magic=expected_magic)
        return problems


def _required_entry_problems(names: list[str], *, abi: str) -> list[str]:
    """The three things without which the app cannot start at all."""
    problems = []
    if f"lib/{abi}/libmain.so" not in names:
        problems.append(f"lib/{abi}/libmain.so is missing from the APK")

    runtimes = sorted(n for n in names if _LIBPYTHON.match(n))
    if not runtimes:
        problems.append(
            f"no libpython3.X.so under lib/{abi}/ — the APK ships no runtime"
        )
    elif len(runtimes) > 1:
        problems.append(
            f"APK ships {len(runtimes)} CPython runtimes ({runtimes}); the "
            "bootstrap loads exactly one and the rest are dead weight"
        )

    if not any(n.startswith(BUNDLE_ROOT) for n in names):
        problems.append(f"{BUNDLE_ROOT} is missing from the APK")
    return problems


def _payload_problems(names: list[str], *, stripped: bool) -> list[str]:
    """Whether the Python payload is source or bytecode, and nothing in between.

    The mixed case is the interesting one. A ``.pyc`` sitting next to its
    ``.py`` is silently ignored by the import system, so a half-stripped bundle
    looks fine on device while shipping every source file the setting was meant
    to remove.
    """
    bundle = [n for n in names if n.startswith(BUNDLE_ROOT) and not n.endswith("/")]
    if not bundle:
        return []  # _required_entry_problems already reported the empty bundle

    sources = [n for n in bundle if n.endswith(".py")]
    compiled = [n for n in bundle if n.endswith(".pyc")]
    problems = []

    if stripped:
        if sources:
            problems.append(
                f"strip_source was applied but {len(sources)} .py file(s) "
                f"remain in the payload, e.g. {sources[:3]}"
            )
        if not compiled:
            problems.append(
                "strip_source was applied but the payload contains no .pyc at "
                "all — the build degraded to shipping source"
            )
        # PEP 3147 puts a .pyc in __pycache__ *beside* its source; sourceless
        # imports need it in the legacy location instead, so a __pycache__ dir
        # here means the stripping step moved nothing.
        cached = [n for n in bundle if "__pycache__" in n]
        if cached:
            problems.append(
                f"payload has {len(cached)} __pycache__ entrie(s), e.g. "
                f"{cached[:3]} — sourceless imports need .pyc in the legacy "
                "location, not beside a source file that is no longer there"
            )
        if f"{BUNDLE_ROOT}app/main.pyc" not in names:
            problems.append(
                f"{BUNDLE_ROOT}app/main.pyc is missing; the entry point must be "
                "compiled in the legacy sourceless layout"
            )
    else:
        if f"{BUNDLE_ROOT}app/main.py" not in names:
            problems.append(
                f"{BUNDLE_ROOT}app/main.py is missing from an unstripped build"
            )

    # Extension modules are hoisted to lib/<abi>/ because Android's loader will
    # not open a .so from inside the unpacked assets tree. One left behind is a
    # staging bug that surfaces as an ImportError on device.
    stranded = [n for n in bundle if n.endswith(".so")]
    if stranded:
        problems.append(
            f"{len(stranded)} shared object(s) left inside the payload instead "
            f"of hoisted to lib/, e.g. {stranded[:3]}"
        )
    return problems


def _pyc_magic_problems(
    zf: zipfile.ZipFile, names: list[str], *, expected_magic: bytes
) -> list[str]:
    """Every ``.pyc`` must carry the magic the shipped runtime imports.

    This is roadmap item 1's actual bug. CPython bumps the magic number through
    the alpha/beta cycle and freezes it at the first release candidate, so a
    pre-release of the *right* minor writes bytecode a release runtime refuses —
    while answering the same "3.14" to any version check. When the source has
    been stripped there is nothing to fall back to, so the app dies on import.
    """
    pycs = [n for n in names if n.startswith(BUNDLE_ROOT) and n.endswith(".pyc")]
    seen: dict[bytes, list[str]] = {}
    for name in pycs:
        with zf.open(name) as handle:
            magic = handle.read(4)
        seen.setdefault(magic, []).append(name)

    problems = []
    for magic, members in sorted(seen.items()):
        if magic != expected_magic:
            problems.append(
                f"{len(members)} .pyc file(s) carry magic "
                f"{_magic_int(magic)} but the shipped runtime imports "
                f"{_magic_int(expected_magic)}, e.g. "
                f"{[posixpath.basename(m) for m in members[:3]]} — these were "
                "written by an interpreter of a different CPython build and "
                "cannot be imported"
            )
    return problems


def _magic_int(magic: bytes) -> int:
    """The human-readable half of a ``.pyc`` header (the trailing ``\\r\\n``)."""
    return struct.unpack("<H", magic[:2])[0] if len(magic) >= 2 else -1


def _native_lib_problems(
    zf: zipfile.ZipFile, names: list[str], *, abi: str
) -> list[str]:
    """Every shared object under ``lib/`` must be 64-bit ELF for exactly *abi*.

    The failure this exists for is a cross-build that picked up a host-arch
    binary — it installs, and then dlopen fails on device with a message that
    names the file but not the reason. A stray *second* ABI directory is the
    related bug: it doubles the APK and ships code the manifest never claimed.
    """
    expected = ABI_MACHINES[abi]
    libs = [n for n in names if n.startswith("lib/") and n.endswith(".so")]
    problems = []

    strays = sorted({n.split("/")[1] for n in libs} - {abi})
    if strays:
        problems.append(
            f"APK carries shared objects for unrequested ABI(s) {strays}; "
            f"only {abi} was built"
        )

    for name in libs:
        if name.split("/")[1] != abi:
            continue  # already reported as a stray ABI
        with zf.open(name) as handle:
            header = handle.read(20)
        if header[:4] != b"\x7fELF":
            problems.append(f"{name} is not an ELF file")
            continue
        if header[4] != ELFCLASS64:
            problems.append(f"{name} is 32-bit ELF; every Android ABI is 64-bit")
        machine = struct.unpack("<H", header[18:20])[0]
        if machine != expected:
            problems.append(
                f"{name} is {machine_name(machine)} but {abi} requires "
                f"{machine_name(expected)} — a host binary leaked into a "
                "cross-build"
            )
    return problems


# --- Android: merged-manifest content vs. what config declared ---------------
#
# Everything above proves the APK's *shape*. This proves its *manifest
# content*: that what pyproject.toml declared survived AGP's manifest merge
# into the manifest that actually ships. Nothing else covers that.
# ``platforms/android/policy.py`` also lints the merged manifest, but for a
# dangerous *posture* — an exported component, a debuggable release, the
# ``org.example.*`` placeholder — and it would pass, happily, a manifest that
# had silently lost every permission the project asked for.
#
# **Presence, never equality.** A real merged manifest legitimately carries
# components and permissions no pyproject.toml mentions, because a library
# manifest contributed them: androidx.startup's ``InitializationProvider``,
# profileinstaller's receiver, the generated
# ``DYNAMIC_RECEIVER_NOT_EXPORTED_PERMISSION`` pair. Asserting that the merged
# set *equals* the declared set would fail on every real build, and a check
# that always fails gets deleted rather than fixed.
#
# Expectations are derived by importing the generator's own
# ``effective_permissions`` / ``effective_features`` / ``screen_orientation``
# / ``service_class_name`` rather than restating the auto-add, implied-feature
# and orientation rules here — the same reasoning as the imported ELF and PE
# constants at the top of this module. That does mean this check cannot catch
# a generator that emits the wrong thing *consistently*; the hermetic
# generation tests (T1) own that, and this owns the merge.
#
# The raw-XML passthrough fields (``extra_manifest_xml`` and friends) are
# deliberately **not** matched element-by-element: they are arbitrary XML whose
# merged shape is not predictable from config. What is checked instead is that
# no ``${placeholder}`` survived anywhere in the merged file, which is the
# failure those fields actually produce.

ANDROID_MANIFEST_NS = "{http://schemas.android.com/apk/res/android}"

_UNRESOLVED_PLACEHOLDER = re.compile(r"\$\{[A-Za-z_][A-Za-z0-9_.]*\}")

_LAUNCHER_CATEGORY = "android.intent.category.LAUNCHER"


def android_manifest_problems(
    manifest_xml: str,
    *,
    android: AndroidConfig,
    orientation: tuple[str, ...],
    version_name: str,
) -> list[str]:
    """Every way AGP's *merged* manifest fails to carry what config declared.

    ``manifest_xml`` is the text of the merged manifest — the artifact the
    generated ``exportKivyforgeReleaseManifest`` task copies to
    ``MERGED_MANIFEST_RELPATH``, not the manifest kivyforge generated as input
    to the merge. Checking the input would prove nothing about the merge.

    ``version_name`` is ``[project].version``, which reaches the manifest
    through ``app/build.gradle``'s ``versionName`` rather than through the
    generated manifest, so it is passed in rather than read off
    ``AndroidConfig``.
    """
    try:
        root = ET.fromstring(manifest_xml)
    except ET.ParseError as exc:
        return [f"the merged manifest does not parse: {exc}"]
    if root.tag != "manifest":
        return [f"the merged manifest's root element is <{root.tag}>, not <manifest>"]

    problems = _manifest_identity_problems(
        root, android=android, version_name=version_name
    )
    problems += _manifest_permission_problems(root, android=android)
    problems += _manifest_feature_problems(root, android=android)

    app = root.find("application")
    if app is None:
        # Every remaining check reads through <application>; saying so once is
        # more useful than repeating "not found" for each of them.
        return [*problems, "the merged manifest has no <application> element"]

    problems += _manifest_application_problems(app, android=android)
    problems += _manifest_main_activity_problems(
        app, android=android, orientation=orientation
    )
    problems += _manifest_component_problems(app, android=android)
    problems += _manifest_placeholder_problems(manifest_xml)
    return problems


def _android_attr(elem: ET.Element, name: str) -> str | None:
    return elem.get(f"{ANDROID_MANIFEST_NS}{name}")


def _attr_lookup_key(key: str) -> str | None:
    """A config passthrough attribute key as :mod:`xml.etree` will spell it.

    ``None`` for anything not in the ``android:`` namespace. A ``tools:``
    attribute is an *instruction to the merger* and is consumed and removed by
    it, so looking for one in the output is a guaranteed false positive; any
    other prefix would need an ``xmlns`` this generator does not emit.
    """
    if key.startswith("android:"):
        return f"{ANDROID_MANIFEST_NS}{key.removeprefix('android:')}"
    return None


def _expected_attr_value(value: object) -> str:
    """The config value as a *parsed* attribute reads back.

    Deliberately not ``generate.manifest._attr_str``: that escapes for
    serialization, and ElementTree has already un-escaped on the way in, so
    reusing it would compare ``"a &amp; b"`` against ``"a & b"`` and report a
    fault on any value containing an ampersand.
    """
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _manifest_identity_problems(
    root: ET.Element, *, android: AndroidConfig, version_name: str
) -> list[str]:
    """applicationId, version, and the SDK floor/target.

    None of these four come from the generated manifest — AGP injects all of
    them into the merged one out of ``app/build.gradle``'s ``defaultConfig``.
    That makes them the part of this check with the least overlap with the
    generation tests, and the part that would catch a build.gradle template
    regression every hermetic manifest test would pass.
    """
    problems = []
    if root.get("package") != android.package:
        problems.append(
            f"merged manifest package is {root.get('package')!r}, but config "
            f"declares {android.package!r}"
        )

    expected_code = str(android.version_code)
    if _android_attr(root, "versionCode") != expected_code:
        problems.append(
            f"merged manifest android:versionCode is "
            f"{_android_attr(root, 'versionCode')!r}, expected {expected_code!r}"
        )
    if _android_attr(root, "versionName") != version_name:
        problems.append(
            f"merged manifest android:versionName is "
            f"{_android_attr(root, 'versionName')!r}, expected {version_name!r}"
        )

    uses_sdk = root.find("uses-sdk")
    if uses_sdk is None:
        problems.append(
            "merged manifest has no <uses-sdk>, so min_sdk/target_sdk cannot be "
            "confirmed to have reached the artifact"
        )
        return problems
    for attr, expected in (
        ("minSdkVersion", android.min_sdk),
        ("targetSdkVersion", android.target_sdk),
    ):
        actual = _android_attr(uses_sdk, attr)
        if actual != str(expected):
            problems.append(
                f"merged manifest <uses-sdk> android:{attr} is {actual!r}, "
                f"expected {str(expected)!r}"
            )
    return problems


def _manifest_permission_problems(
    root: ET.Element, *, android: AndroidConfig
) -> list[str]:
    declared = {_android_attr(p, "name") for p in root.iter("uses-permission")}
    return [
        f"<uses-permission android:name={name!r}> is declared in config but "
        "missing from the merged manifest"
        for name in effective_permissions(android)
        if name not in declared
    ]


def _manifest_feature_problems(
    root: ET.Element, *, android: AndroidConfig
) -> list[str]:
    merged = {
        _android_attr(f, "name"): _android_attr(f, "required")
        for f in root.iter("uses-feature")
    }
    problems = []
    for name, required in effective_features(android):
        if name not in merged:
            problems.append(
                f"<uses-feature android:name={name!r}> is declared in config "
                "(or implied by a declared permission) but missing from the "
                "merged manifest"
            )
            continue
        # A library may contribute the same feature as required="true", and the
        # merger takes the stronger claim — so a *stronger* requirement than
        # config asked for is the merger working, not a fault. Only a weaker
        # one loses something the project declared.
        if required and merged[name] != "true":
            problems.append(
                f"<uses-feature android:name={name!r}> is android:required="
                f"{merged[name]!r} in the merged manifest, but config declares "
                "it required"
            )
    return problems


def _manifest_application_problems(
    app: ET.Element, *, android: AndroidConfig
) -> list[str]:
    """The generated <application> attributes, plus config's passthrough.

    Built the way the generator builds them — defaults first, then
    ``[tool.kivy.android.manifest.application]`` on top. Today those two sets
    are disjoint, because every generated default is in
    ``MANAGED_ANDROID_APPLICATION_ATTRS`` and the loader rejects a pyproject
    that sets one. Layering them anyway costs nothing and means this check
    cannot start disagreeing with the generator if a managed attribute is
    ever released to passthrough.
    """
    expected: dict[str, str] = {
        "android:label": "@string/app_name",
        "android:icon": "@mipmap/ic_launcher",
        "android:theme": GENERATED_THEME,
    }
    if android.icons.source:
        expected["android:roundIcon"] = "@mipmap/ic_launcher_round"
    for key, value in android.manifest.application.items():
        expected[key] = _expected_attr_value(value)
    return _attr_problems(app, expected, where="<application>")


def _manifest_main_activity_problems(
    app: ET.Element, *, android: AndroidConfig, orientation: tuple[str, ...]
) -> list[str]:
    main = None
    for activity in app.iter("activity"):
        if _android_attr(activity, "name") == MAIN_ACTIVITY:
            main = activity
            break
    if main is None:
        return [
            f"the merged manifest has no <activity android:name={MAIN_ACTIVITY!r}>, "
            "so the app has no launcher"
        ]

    expected: dict[str, str] = {
        "android:exported": "true",
        "android:configChanges": "keyboardHidden|orientation|screenSize",
        "android:screenOrientation": screen_orientation(orientation),
        "android:theme": GENERATED_THEME,
    }
    for key, value in android.manifest.activity.items():
        expected[key] = _expected_attr_value(value)
    problems = _attr_problems(main, expected, where=f"<activity {MAIN_ACTIVITY}>")

    filters = list(main.iter("intent-filter"))
    if not any(
        _LAUNCHER_CATEGORY in {_android_attr(c, "name") for c in f.iter("category")}
        for f in filters
    ):
        problems.append(
            f"{MAIN_ACTIVITY} has no intent-filter carrying the "
            f"{_LAUNCHER_CATEGORY} category"
        )
    problems += _intent_filter_problems(filters, android=android)
    return problems


def _intent_filter_problems(
    filters: list[ET.Element], *, android: AndroidConfig
) -> list[str]:
    """Each declared filter must be *contained in* some merged filter.

    Containment rather than equality: the merger is free to add categories to
    a filter it also received from a library, so matching exactly would make
    this check a hostage to whatever androidx ships next.
    """
    problems = []
    for declared in android.intent_filters:
        wanted_categories = set(declared.categories)
        wanted_data = [dict(sorted(d.items())) for d in declared.data]
        if not any(
            _filter_contains(f, declared.action, wanted_categories, wanted_data)
            for f in filters
        ):
            problems.append(
                f"no intent-filter on {MAIN_ACTIVITY} carries the declared "
                f"action {declared.action!r} with categories "
                f"{sorted(wanted_categories)} and data {wanted_data}"
            )
    return problems


def _filter_contains(
    filter_elem: ET.Element,
    action: str,
    categories: set[str],
    data: list[dict[str, str]],
) -> bool:
    actions = {_android_attr(a, "name") for a in filter_elem.iter("action")}
    if action not in actions:
        return False
    # An <action>/<category> with no android:name is malformed rather than a
    # match for anything, so the Nones are dropped instead of being compared.
    present = {
        name
        for c in filter_elem.iter("category")
        if (name := _android_attr(c, "name")) is not None
    }
    if not categories <= present:
        return False
    merged_data = [
        {
            k.removeprefix(ANDROID_MANIFEST_NS): v
            for k, v in d.attrib.items()
            if k.startswith(ANDROID_MANIFEST_NS)
        }
        for d in filter_elem.iter("data")
    ]
    return all(
        any(wanted.items() <= have.items() for have in merged_data) for wanted in data
    )


def _manifest_component_problems(
    app: ET.Element, *, android: AndroidConfig
) -> list[str]:
    """Declared services and extra activities survived the merge."""
    problems = []

    services = {_android_attr(s, "name"): s for s in app.iter("service")}
    for service in android.services:
        fqcn = service_class_name(service)
        elem = services.get(fqcn)
        if elem is None:
            problems.append(
                f"declared service {service.name!r} is missing from the merged "
                f"manifest (expected <service android:name={fqcn!r}>)"
            )
            continue
        expected = {
            "android:process": f":service_{service.name.lower()}",
            "android:exported": "true" if service.exported else "false",
        }
        if service.foreground:
            expected["android:foregroundServiceType"] = (
                service.foreground_service_type or ""
            )
        problems += _attr_problems(elem, expected, where=f"<service {fqcn}>")

    activities = {_android_attr(a, "name"): a for a in app.iter("activity")}
    for extra in android.activities:
        elem = activities.get(extra.name)
        if elem is None:
            problems.append(
                f"declared activity {extra.name!r} is missing from the merged manifest"
            )
            continue
        problems += _attr_problems(
            elem,
            {"android:exported": "true" if extra.exported else "false"},
            where=f"<activity {extra.name}>",
        )
    return problems


def _attr_problems(
    elem: ET.Element, expected: dict[str, str], *, where: str
) -> list[str]:
    problems = []
    for key, want in sorted(expected.items()):
        lookup = _attr_lookup_key(key)
        if lookup is None:
            continue
        actual = elem.get(lookup)
        if actual != want:
            problems.append(
                f"{where} {key} is {actual!r} in the merged manifest, expected {want!r}"
            )
    return problems


def _manifest_placeholder_problems(manifest_xml: str) -> list[str]:
    """No ``${placeholder}`` may survive into the shipped manifest.

    This is the one check that covers the raw-XML passthrough fields, and it
    covers the failure they actually cause: a fragment referencing a
    placeholder that ``[tool.kivy.android.manifest].placeholders`` never
    defined ships the literal text ``${whatever}`` as a class name, an
    authority or a permission, and the app breaks at runtime rather than at
    build time. AGP resolves ``${applicationId}`` itself, so anything left
    here is genuinely unresolved.
    """
    left = sorted(set(_UNRESOLVED_PLACEHOLDER.findall(manifest_xml)))
    if not left:
        return []
    return [
        f"the merged manifest still contains unresolved placeholder(s) {left} "
        "— declare them in [tool.kivy.android.manifest].placeholders"
    ]


# --- Android: the signature, as apksigner reports it ------------------------
#
# The spawn lives in ``tests/platforms/android/test_apk_signature.py``; this is
# only the parse, so it stays hermetic like everything else here (see the
# module docstring).
#
# ``apksigner verify -v`` prints one line per signing scheme:
#
#     Verifies
#     Verified using v1 scheme (JAR signing): false
#     Verified using v2 scheme (APK Signature Scheme v2): true
#     Verified using v3 scheme (APK Signature Scheme v3): true
#
# Both halves matter, and neither alone is enough. "Verifies" says the
# signature is *intact*; the scheme lines say *which* signature, and that is
# the half tied to config: ``[tool.kivy.android.signing].v1_signing`` defaults
# off because the min_sdk floor is 24, where the platform verifies v2+. An APK
# that verified only under v1 would install and would also mean that setting
# had quietly stopped being honoured.

_SCHEME_LINE = re.compile(
    r"^Verified using (v\d) scheme [^:]*:\s*(true|false)\s*$", re.MULTILINE
)

MODERN_SIGNING_SCHEMES = ("v2", "v3", "v4")


def apksigner_report_problems(report: str, *, v1_signing: bool) -> list[str]:
    """Every way an ``apksigner verify -v`` report falls short of the config.

    *report* is apksigner's combined stdout; the caller has already decided
    what a non-zero exit means, because a tool that would not start is a
    different failure from an artifact that does not verify.
    """
    schemes = {m.group(1): m.group(2) == "true" for m in _SCHEME_LINE.finditer(report)}
    if not schemes:
        return [
            "apksigner reported no 'Verified using vN scheme' lines, so nothing "
            "about the signature can be concluded from its output:\n" + report.strip()
        ]

    problems = []
    if "Verifies" not in report.splitlines():
        problems.append(
            "apksigner did not print 'Verifies': the signature is not intact:\n"
            + report.strip()
        )

    if schemes.get("v1", False) != v1_signing:
        problems.append(
            f"v1 (JAR) signing is {'on' if schemes.get('v1') else 'off'} in the "
            f"APK, but config declares v1_signing = {str(v1_signing).lower()}"
        )

    if not any(schemes.get(scheme, False) for scheme in MODERN_SIGNING_SCHEMES):
        signed = sorted(k for k, v in schemes.items() if v)
        problems.append(
            "the APK carries no modern signature block — apksigner verified "
            f"only {signed or 'nothing'}, and one of "
            f"{list(MODERN_SIGNING_SCHEMES)} is required at min_sdk 24+"
        )
    return problems


# --- Windows: the signature, as signtool reports it -------------------------
#
# The spawn lives in ``tests/platforms/windows/test_authenticode.py``; same
# split, and for the same reason, as the apksigner parse above.
#
# ``signtool verify /pa /v`` on a good binary ends with:
#
#     The signature is timestamped: Sat Sep 30 02:08:11 2023
#     Successfully verified: C:\\...\\signtool.exe
#     Number of files successfully Verified: 1
#     Number of errors: 0
#
# and on an unsigned one with:
#
#     Number of files successfully Verified: 0
#     Number of errors: 1
#     SignTool Error: No signature found.
#
# The counts are what this reads, not the exit code (the caller has that) and
# not the word "verified" on its own — a signed-but-untrusted binary prints a
# full certificate chain and "The signature is timestamped", and only the
# counts and the ``SignTool Error`` lines distinguish it from a pass. That
# exact case was used to develop this parser: a python.org ``python.exe``
# whose signing certificate had since been revoked, which prints almost
# everything a passing verification does.
#
# The timestamp assertion is config-tied rather than cosmetic:
# ``SigntoolSigner.command`` always passes ``/tr`` + ``/td SHA256``, so a
# kivyforge-signed artifact is always RFC3161-timestamped, and an
# untimestamped signature silently stops validating the day the certificate
# expires.

_VERIFIED_COUNT = re.compile(
    r"^Number of files successfully Verified:\s*(\d+)\s*$", re.MULTILINE
)
_ERROR_COUNT = re.compile(r"^Number of errors:\s*(\d+)\s*$", re.MULTILINE)

_TIMESTAMPED = "The signature is timestamped:"


def _signtool_error_lines(report: str) -> list[str]:
    """``SignTool Error:`` lines, each with its indented continuation.

    signtool puts the code on the ``SignTool Error`` line and the human
    explanation on the tab-indented line beneath it — "WinVerifyTrust returned
    error: 0x800B010C" followed by "A certificate was explicitly revoked by
    its issuer." Reporting only the first line hands the reader a hex code and
    makes them go looking for the sentence signtool already wrote.

    Blank lines do not end a continuation: signtool separates **every** line
    of its output with one, so ``\\n\\n`` sits between the code and its
    explanation. Treating a blank line as a terminator silently dropped the
    explanation on real output while passing a hand-written fixture that
    lacked the double spacing.
    """
    out: list[str] = []
    collecting = False
    for line in report.splitlines():
        if line.strip().startswith("SignTool Error"):
            out.append(line.strip())
            collecting = True
        elif not line.strip():
            continue
        elif collecting and line[:1] in (" ", "\t"):
            out[-1] += " " + line.strip()
        else:
            collecting = False
    return out


def signtool_report_problems(
    report: str, *, require_timestamp: bool = True
) -> list[str]:
    """Every way a ``signtool verify /pa /v`` report falls short of a pass.

    *report* is signtool's combined output. ``require_timestamp`` is a
    parameter rather than a constant only so the check can be pointed at a
    third-party binary that was signed without one; for anything kivyforge
    signed it must stay ``True``.
    """
    verified = _VERIFIED_COUNT.search(report)
    errors = _ERROR_COUNT.search(report)
    if verified is None or errors is None:
        return [
            "signtool printed no verification counts, so nothing about the "
            "signature can be concluded from its output:\n" + report.strip()
        ]

    problems = []
    signtool_errors = _signtool_error_lines(report)
    if int(verified.group(1)) != 1:
        problems.append(
            f"signtool verified {verified.group(1)} file(s), expected 1"
            + (f"; it reported: {signtool_errors}" if signtool_errors else "")
        )
    if int(errors.group(1)) != 0:
        problems.append(
            f"signtool reported {errors.group(1)} error(s): {signtool_errors}"
        )
    if require_timestamp and _TIMESTAMPED not in report:
        problems.append(
            "the signature carries no RFC3161 timestamp, so it will stop "
            "validating when the signing certificate expires (kivyforge always "
            "signs with /tr, so this should be impossible)"
        )
    return problems


# --- macOS ------------------------------------------------------------------
#
# The macOS ``.app`` is a real directory tree, not a zip, so these walk the
# filesystem directly rather than a ``zipfile.ZipFile``. Payload-stripping scope
# is narrower than Android's: per the settled decision in
# docs/design/dev/macos-x86-removal-and-desktop-stripping.md ("Strip scope: app
# + site-packages only. stdlib is not stripped."), only ``Contents/Resources/app``
# (the developer's own sources) and ``Contents/Resources/lib`` (third-party
# deps — the macos-spec analogue of "site-packages") are ever byte-compiled;
# ``Contents/Resources/python`` (the embedded CPython framework's own stdlib,
# which ships pip) is deliberately left as source and must not be checked as
# if it were part of the same policy.

MACOS_ARCH_MACHINES = {"arm64": CPU_TYPE_ARM64, "x86_64": CPU_TYPE_X86_64}

_MACOS_STRIP_SCOPE = ("Contents/Resources/app", "Contents/Resources/lib")


def macos_expected_plist(config: Config) -> dict[str, object]:
    """The ``Info.plist`` keys a project's config decides, for comparison.

    Produced by calling the **production** builder rather than restating its
    key list: ``build_info_plist`` is the definition of what the bundle should
    carry, and a second copy here would drift the first time a key was added.

    Two keys are then dropped, because a driver holding only the config cannot
    know them:

    * ``CFBundleExecutable`` — the launcher's filename, decided at build time.
      It is still checked, by the cross-reference in
      :func:`_macos_plist_problems` that it names a real file in
      ``Contents/MacOS/``.
    * ``CFBundleIconFile`` — omitted by passing ``icon_file=None``, since
      whether an icon was staged is a build-time outcome.
    """
    plist = build_info_plist(config, executable="", icon_file=None)
    plist.pop("CFBundleExecutable", None)
    return plist


def macos_app_problems(
    app: Path,
    *,
    arch: str,
    stripped: bool,
    expected_magic: bytes,
    expected_plist: dict[str, object] | None = None,
    executable: str | None = None,
) -> list[str]:
    """Every way *app* fails to be the artifact the build promised.

    ``arch`` is the Mach-O arch name (``"arm64"``, the only one macOS builds
    produce post-Phase-A), ``stripped`` whether ``strip_source`` applied to
    this build, and ``expected_magic`` the first four bytes a ``.pyc`` the
    bundle's own shipped runtime can import must carry (see Android's
    ``shipped_python_tags`` for the reasoning; on macOS the equivalent is
    running the bundle's own ``Contents/Resources/python/bin/python3``).

    ``expected_plist`` is the config-derived ``Info.plist`` keys the bundle
    must carry — the macOS half of test-matrix.md §5.1's "manifest and
    ``Info.plist`` contain what config asked for". Keys not named in it are
    ignored, because the plist legitimately holds build-time values
    (``CFBundleIconFile``, ``CFBundleExecutable``) and fixed ones
    (``CFBundlePackageType``) that config does not decide. Omitted, only the
    plist's internal shape is checked — present, parses, required keys
    non-empty.

    It replaces an earlier ``bundle_id`` parameter, which covered one key and
    which no driver ever passed: an expectation nothing supplies is a check
    that never runs, which is this tier's own failure mode.
    """
    if arch not in MACOS_ARCH_MACHINES:
        return [f"unknown arch {arch!r}; expected one of {sorted(MACOS_ARCH_MACHINES)}"]

    problems = _macos_required_entry_problems(app)
    if problems:
        # Nothing else below can be trusted to mean anything on a bundle
        # that is missing its basic shape.
        return problems

    problems += _macos_plist_problems(
        app, expected_plist=expected_plist, executable=executable
    )
    problems += _macos_arch_problems(app, arch=arch)
    problems += _macos_payload_problems(app, stripped=stripped)
    if stripped:
        problems += _macos_pyc_magic_problems(app, expected_magic=expected_magic)
    return problems


def _macos_required_entry_problems(app: Path) -> list[str]:
    """The handful of things without which this is not a launchable ``.app``."""
    problems = []
    if not (app / "Contents" / "Info.plist").is_file():
        problems.append("Contents/Info.plist is missing")
    macos_dir = app / "Contents" / "MacOS"
    if not macos_dir.is_dir() or not any(
        p.is_file() for p in macos_dir.iterdir() if not p.name.startswith(".")
    ):
        problems.append("Contents/MacOS/ has no executable")
    if not (app / "Contents" / "Resources" / "python").is_dir():
        problems.append("Contents/Resources/python (the embedded runtime) is missing")
    if not (app / "Contents" / "Resources" / "app").is_dir():
        problems.append("Contents/Resources/app (the app payload) is missing")
    return problems


def _macos_plist_problems(
    app: Path, *, expected_plist: dict[str, object] | None, executable: str | None
) -> list[str]:
    plist_path = app / "Contents" / "Info.plist"
    try:
        with plist_path.open("rb") as fh:
            plist = plistlib.load(fh)
    except Exception as exc:  # noqa: BLE001 - report, don't crash the check
        return [f"Contents/Info.plist does not parse: {exc}"]

    problems = []
    required_keys = (
        "CFBundleIdentifier",
        "CFBundleExecutable",
        "CFBundleShortVersionString",
        "CFBundleVersion",
    )
    for key in required_keys:
        if not plist.get(key):
            problems.append(f"Info.plist is missing (or has an empty) {key}")

    for key, want in sorted((expected_plist or {}).items()):
        if plist.get(key) != want:
            problems.append(
                f"Info.plist {key} is {plist.get(key)!r}, but config declares {want!r}"
            )
    if executable is not None and plist.get("CFBundleExecutable") != executable:
        problems.append(
            f"Info.plist CFBundleExecutable is {plist.get('CFBundleExecutable')!r}, "
            f"expected {executable!r}"
        )
    elif executable is None and "CFBundleExecutable" in plist:
        exe = plist["CFBundleExecutable"]
        if not (app / "Contents" / "MacOS" / exe).is_file():
            problems.append(
                f"Info.plist CFBundleExecutable {exe!r} does not name a file "
                "in Contents/MacOS/"
            )
    return problems


def _macos_arch_problems(app: Path, *, arch: str) -> list[str]:
    """Every Mach-O under the bundle must be *arch*, and only *arch*.

    Walks ``Contents/MacOS`` (the launcher) and ``Contents/Resources`` (the
    embedded runtime + every staged wheel's compiled extensions) — a
    host-arch binary leaking into a cross-build is exactly the item-1-shaped
    bug this exists to catch, on the one platform where it would otherwise
    surface only as a Gatekeeper/Rosetta failure on a real Mac.
    """
    expected = MACOS_ARCH_MACHINES[arch]
    problems: list[str] = []
    for path in sorted(app.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        try:
            head = path.read_bytes()[:8]
        except OSError:
            continue
        try:
            cpu_type = read_macho_cpu_type(head)
        except MachoError:
            continue  # not a Mach-O (or a 32-bit/fat one we don't parse) — skip
        if cpu_type != expected:
            rel = path.relative_to(app).as_posix()
            problems.append(
                f"{rel} is {cpu_type_name(cpu_type)} but this build is {arch} — "
                "a host or cross-arch binary leaked into the bundle"
            )
    return problems


def _macos_payload_problems(app: Path, *, stripped: bool) -> list[str]:
    """Whether the app + third-party payload is source or bytecode.

    Scoped to ``Contents/Resources/{app,lib}`` only — see the module-level
    note on why the embedded stdlib is excluded by design, not by omission.
    """
    problems: list[str] = []
    for scope in _MACOS_STRIP_SCOPE:
        base = app / scope
        if not base.is_dir():
            continue
        sources = sorted(p for p in base.rglob("*.py"))
        compiled = sorted(p for p in base.rglob("*.pyc"))
        cached = sorted(p for p in base.rglob("__pycache__") if p.is_dir())

        if stripped:
            if sources:
                rels = [p.relative_to(app).as_posix() for p in sources[:3]]
                problems.append(
                    f"strip_source was applied but {len(sources)} .py file(s) "
                    f"remain under {scope}, e.g. {rels}"
                )
            if not compiled:
                problems.append(
                    f"strip_source was applied but {scope} contains no .pyc at "
                    "all — the build degraded to shipping source"
                )
            if cached:
                rels = [p.relative_to(app).as_posix() for p in cached[:3]]
                problems.append(
                    f"{scope} has {len(cached)} __pycache__ dir(s), e.g. "
                    f"{rels} — sourceless imports need .pyc in the legacy "
                    "location, not beside a source file that is no longer there"
                )
        elif scope == "Contents/Resources/app" and not sources and not compiled:
            problems.append(
                f"{scope} has neither .py nor .pyc — the app has no entry point"
            )
    return problems


def _macos_pyc_magic_problems(app: Path, *, expected_magic: bytes) -> list[str]:
    """Every ``.pyc`` under the stripped scope must carry the shipped magic.

    Mirrors Android's ``_pyc_magic_problems`` / roadmap item 1's bug, adapted
    to a directory tree: read straight from disk rather than a zip member.
    """
    problems: list[str] = []
    for scope in _MACOS_STRIP_SCOPE:
        base = app / scope
        if not base.is_dir():
            continue
        seen: dict[bytes, list[Path]] = {}
        for pyc in sorted(base.rglob("*.pyc")):
            magic = pyc.read_bytes()[:4]
            seen.setdefault(magic, []).append(pyc)
        for magic, members in sorted(seen.items()):
            if magic != expected_magic:
                rels = [p.relative_to(app).as_posix() for p in members[:3]]
                problems.append(
                    f"{len(members)} .pyc file(s) under {scope} carry magic "
                    f"{_magic_int(magic)} but the bundle's own runtime imports "
                    f"{_magic_int(expected_magic)}, e.g. {rels} — these were "
                    "written by an interpreter of a different CPython build "
                    "and cannot be imported"
                )
    return problems


# --------------------------------------------------------------------------
# iOS
# --------------------------------------------------------------------------
#
# Spec'd in ios-t3-checks-prompt.md (2026-09-23): iOS was the one platform
# with no T3 tier at all, and `ios_simulator` had built a real `.app` on every
# push since the day before this was written without anything inspecting it.
#
# **Scope is narrower than the other four platforms', and deliberately so.**
# iOS `strip_source` cannot be exercised honestly yet: every iOS example pins
# a CPython 3.15 *pre-release* (`3.15.0b4`), `_compile_app_copy` /
# `_compile_pip_deps` both degrade to shipping source with "no final CPython
# 3.15 found" (confirmed against a real build the day this was written — see
# ios-t3-checks-findings.md Step 0), and python.org publishes no iOS
# `Python.xcframework` below `3.15.0b1` — so there is no "pin an
# already-final minor" escape the way desktop has. Writing a stripped/`.pyc`-
# magic check with nothing to run it against would be exactly the
# never-exercised-code-path shape roadmap item 1 already cost this project
# once; the parameter is omitted entirely rather than carried unused, and iOS
# has no `*_STRIP_SCOPE` constant to show for it. Revisit if a final CPython
# 3.15 iOS xcframework is ever published.
#
# **The bundle is flat — no `Contents/`.** Read off a real
# `kivyforge build -p ios --simulator` of `examples/mobile/hello-kivy`
# (ios-t3-checks-findings.md Step 0): the executable and `Info.plist` sit
# directly at the bundle root, `app/` is the developer's own payload,
# `pip-deps/` is the third-party-wheel payload (macOS's `Contents/Resources/
# {app,lib}` equivalents), and `python/lib/` is the embedded runtime's own
# stdlib (macOS's `Contents/Resources/python` equivalent — never stripped,
# same as every other platform).
#
# **Every compiled extension module is hoisted into its own
# `Frameworks/<name>.framework/`** — Apple requires dynamic libraries to live
# under `Frameworks/`, so python-apple-support's `install_python` (run as an
# Xcode "Build Python" script phase) moves each one out of `app/`/`pip-deps/`/
# `python/lib/.../lib-dynload/` and leaves a `.fwork` text stub (a relative
# path back to itself, not a Mach-O) at the original location — a real build
# of `hello-kivy` alone produces 121 frameworks, one per Kivy/CPython compiled
# module, plus `Python.framework` (the runtime itself), `SDL3*.framework`,
# `KivyThorVG.framework`, `libEGL.framework`/`libGLESv2.framework`. That is
# *why* the arch sweep below walks the whole tree rather than a `lib/`-style
# subdirectory the way Android's does: on iOS, `Frameworks/` is where every
# binary already is.

IOS_ARCH_MACHINES = {"arm64": CPU_TYPE_ARM64, "x86_64": CPU_TYPE_X86_64}


def ios_expected_plist(config: Config) -> dict[str, object]:
    """The ``Info.plist`` keys a project's config decides, for comparison.

    Mirrors :func:`macos_expected_plist`: produced by calling the
    **production** ``platforms.ios.plist.build_info_plist`` builder rather
    than restating its key list, so this cannot drift from what a real build
    actually writes.

    ``CFBundleExecutable`` is dropped: ``ios.plist`` writes it as the literal
    build-setting placeholder ``"$(EXECUTABLE_NAME)"``, which only Xcode
    resolves, so comparing it to config would fail on every real bundle. It
    is still checked — by the cross-reference in :func:`_ios_plist_problems`
    that whatever the *built* plist says names a real file at the bundle
    root.
    """
    plist = ios_build_info_plist(config)
    plist.pop("CFBundleExecutable", None)
    return plist


def ios_app_problems(
    app: Path,
    *,
    arch: str,
    expected_plist: dict[str, object] | None = None,
) -> list[str]:
    """Every way *app* fails to be the artifact the build promised.

    ``arch`` is the Mach-O arch name (``"arm64"``, the default simulator arch
    on Apple Silicon and the only device arch; ``"x86_64"`` is still accepted
    the way ``macos_app_problems`` accepts it, for the same Intel-host-relic
    reasons — see ``xcode/commands.py::default_simulator_arch``).
    ``expected_plist`` is config-derived via :func:`ios_expected_plist`;
    omitted, only the plist's internal shape is checked.

    No ``stripped``/``expected_magic`` parameters — see the module-level note
    above on why that check cannot be written honestly yet. The code
    signature is likewise not here: ``codesign`` is a real tool, so that
    verification stays in the driver
    (``tests/platforms/ios/test_app_artifact.py``), the same split as
    macOS's ``codesign_verify``.
    """
    if arch not in IOS_ARCH_MACHINES:
        return [f"unknown arch {arch!r}; expected one of {sorted(IOS_ARCH_MACHINES)}"]

    problems = _ios_required_entry_problems(app)
    if problems:
        # Nothing else below can be trusted to mean anything on a bundle
        # that is missing its basic shape.
        return problems

    problems += _ios_plist_problems(app, expected_plist=expected_plist)
    problems += _ios_arch_problems(app, arch=arch)
    return problems


def _ios_required_entry_problems(app: Path) -> list[str]:
    """The handful of things without which this is not a launchable ``.app``.

    All at the bundle root or one level down — see the module-level layout
    note above. ``pip-deps/`` is checked for existence, not contents: the
    Build Python run script always creates it (even for a project with no
    third-party dependencies beyond Kivy), and its absence means that script
    never ran at all.
    """
    problems = []
    if not (app / "Info.plist").is_file():
        problems.append("Info.plist is missing")
    if not (app / "Frameworks" / "Python.framework" / "Python").is_file():
        problems.append(
            "Frameworks/Python.framework/Python (the embedded CPython "
            "runtime) is missing"
        )
    if not (app / "python" / "lib").is_dir():
        problems.append("python/lib (the embedded runtime's own stdlib) is missing")
    if not (app / "app").is_dir():
        problems.append("app/ (the app payload) is missing")
    if not (app / "pip-deps").is_dir():
        problems.append(
            "pip-deps/ is missing; the Build Python run script did not stage it"
        )
    return problems


def _ios_plist_problems(
    app: Path, *, expected_plist: dict[str, object] | None
) -> list[str]:
    plist_path = app / "Info.plist"
    try:
        with plist_path.open("rb") as fh:
            plist = plistlib.load(fh)
    except Exception as exc:  # noqa: BLE001 - report, don't crash the check
        return [f"Info.plist does not parse: {exc}"]

    problems = []
    required_keys = (
        "CFBundleIdentifier",
        "CFBundleExecutable",
        "CFBundleShortVersionString",
        "CFBundleVersion",
    )
    for key in required_keys:
        if not plist.get(key):
            problems.append(f"Info.plist is missing (or has an empty) {key}")

    executable = plist.get("CFBundleExecutable")
    if executable and not (app / executable).is_file():
        problems.append(
            f"Info.plist CFBundleExecutable {executable!r} does not name a "
            "file at the bundle root"
        )

    for key, want in sorted((expected_plist or {}).items()):
        if plist.get(key) != want:
            problems.append(
                f"Info.plist {key} is {plist.get(key)!r}, but config declares {want!r}"
            )
    return problems


def _ios_arch_problems(app: Path, *, arch: str) -> list[str]:
    """Every Mach-O under the bundle must be *arch*, and only *arch*.

    Walks the whole tree, same breadth as ``_macos_arch_problems`` — the root
    executable, ``Frameworks/Python.framework``, and every one of the (often
    100+) per-extension-module frameworks ``install_python`` hoisted out of
    ``app/``/``pip-deps/``/``python/lib`` (see the module-level note). The
    ``.fwork`` stubs those hoists leave behind are plain text, not Mach-O, so
    they fall out through the same ``MachoError`` skip as any other non-binary
    file. A host-arch binary leaking into a cross-build is the item-1-shaped
    bug this exists to catch, on the one platform where the *default*
    simulator arch already varies by host.
    """
    expected = IOS_ARCH_MACHINES[arch]
    problems: list[str] = []
    for path in sorted(app.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        try:
            head = path.read_bytes()[:8]
        except OSError:
            continue
        try:
            cpu_type = read_macho_cpu_type(head)
        except MachoError:
            continue  # not a Mach-O (or a 32-bit/fat one we don't parse) — skip
        if cpu_type != expected:
            rel = path.relative_to(app).as_posix()
            problems.append(
                f"{rel} is {cpu_type_name(cpu_type)} but this build is {arch} — "
                "a host or cross-arch binary leaked into the bundle"
            )
    return problems


# --------------------------------------------------------------------------
# Linux: AppDir / AppImage
# --------------------------------------------------------------------------

# The Python payload, and *only* it. ``bundle.build_appdir`` byte-compiles
# exactly ``usr/app`` and ``usr/lib``, so the interpreter's own stdlib under
# ``usr/python`` keeps its source in a stripped build — 1037 ``.py`` and six
# ``__pycache__`` in a real dice-roller release. That is correct (strip_source
# is about the app's code, and the stdlib is public CPython), but a check that
# swept the whole tree would report every one of them as a fault.
PAYLOAD_DIRS = ("usr/app", "usr/lib")
RUNTIME_DIR = "usr/python"

# ``libpython3.13.so``, ``libpython3.13.so.1.0`` — but not ``libpython3.so``,
# which carries no minor and is the ABI-stable stub.
_LIBPYTHON_SO = re.compile(r"^libpython(\d+\.\d+)\.so(\.\d+\.\d+)?$")

# Offset 8 of a type-2 AppImage: ELF e_ident padding repurposed as the format
# marker (``AI`` + version 2). Type 1 is ``AI\x01`` and ISO9660-based.
APPIMAGE_TYPE2_MAGIC = b"AI\x02"


def shipped_python_tags_appdir(appdir: Path) -> list[str]:
    """The CPython minor(s) whose runtime *appdir* ships, e.g. ``["3.13"]``.

    The AppDir analog of :func:`shipped_python_tags`, and it exists for the same
    reason: the expected ``.pyc`` magic has to be anchored to the runtime that
    will do the importing, read out of the artifact. Taking the version from
    config instead would let a build be checked against a runtime it does not
    ship and pass.
    """
    lib = appdir / RUNTIME_DIR / "lib"
    if not lib.is_dir():
        return []
    found = {
        m.group(1)
        for m in map(_LIBPYTHON_SO.match, (p.name for p in lib.iterdir()))
        if m
    }
    return sorted(found)


def linux_appdir_problems(
    appdir: Path,
    *,
    arch: str,
    stripped: bool,
    expected_magic: bytes,
) -> list[str]:
    """Every way the AppDir at *appdir* fails to be the artifact the build promised.

    ``arch`` is a kivyforge arch name (``x86_64``), ``stripped`` whether
    ``strip_source`` applied to this build, and ``expected_magic`` the first four
    bytes a ``.pyc`` the shipped runtime can import must carry — see
    :func:`shipped_python_tags_appdir` for choosing it.
    """
    if arch not in ARCH_ELF:
        return [f"unknown arch {arch!r}; expected one of {sorted(ARCH_ELF)}"]
    if not appdir.is_dir():
        return [f"{appdir} is not a directory"]

    problems = _linux_required_problems(appdir)
    problems += _apprun_target_problems(appdir)
    problems += _linux_payload_problems(appdir, stripped=stripped)
    problems += _linux_elf_problems(appdir, arch=arch)
    if stripped:
        problems += _linux_pyc_magic_problems(appdir, expected_magic=expected_magic)
    return problems


def _payload_files(appdir: Path) -> list[Path]:
    files: list[Path] = []
    for rel in PAYLOAD_DIRS:
        root = appdir / rel
        if root.is_dir():
            files += [p for p in root.rglob("*") if p.is_file() and not p.is_symlink()]
    return files


def _linux_required_problems(appdir: Path) -> list[str]:
    """The pieces without which it is not an AppDir, or cannot start."""
    problems = []

    apprun = appdir / "AppRun"
    if not apprun.is_file():
        problems.append("AppRun is missing; AppImage requires it at the AppDir root")
    elif os.name == "posix" and not apprun.stat().st_mode & 0o111:
        # Only asked where it can be answered. NTFS records no execute bit, so
        # ``st_mode`` is 0o100666 for every file on Windows however it was
        # written -- the honest answer there is "unknown", and reporting "not
        # executable" would be a false positive on every AppDir inspected from
        # a Windows host, synthetic or real. The assertion still runs on every
        # host that can actually build an AppImage.
        problems.append("AppRun is not executable; appimagetool will refuse the AppDir")

    if not list(appdir.glob("*.desktop")):
        problems.append("no .desktop entry at the AppDir root")

    runtimes = sorted(shipped_python_tags_appdir(appdir))
    if not runtimes:
        problems.append(
            f"no libpython3.X.so under {RUNTIME_DIR}/lib — the AppDir ships no runtime"
        )
    elif len(runtimes) > 1:
        problems.append(
            f"AppDir ships {len(runtimes)} CPython runtimes ({runtimes}); AppRun "
            "starts exactly one and the rest are dead weight"
        )

    if not (appdir / "usr" / "app").is_dir():
        problems.append("usr/app is missing from the AppDir")
    return problems


def _apprun_target_problems(appdir: Path) -> list[str]:
    """Whatever ``AppRun`` promises to execute has to exist in the AppDir.

    This is the Linux shape of roadmap item 1, and it is a real shipped bug
    rather than a hypothetical: ``AppRun`` is rendered from a template that
    hardcodes ``usr/app/<entry>.py`` and is never told whether the payload was
    stripped, so ``kivyforge package`` (which applies ``strip_source`` by
    default) emits an AppImage whose first act is to open a file the same build
    deleted. It exits 2 before Python starts.

    The target is parsed out of the artifact rather than rebuilt from config, so
    this asserts the promise the AppDir actually makes. Both launcher shapes are
    understood — a script path, and ``-m <module>`` — so the check stays correct
    once the launcher is fixed rather than starting to fail in the other
    direction.
    """
    apprun = appdir / "AppRun"
    if not apprun.is_file():
        return []  # already reported

    exec_line = next(
        (
            line
            for line in apprun.read_text("utf-8", errors="replace").splitlines()
            if line.strip().startswith("exec ")
        ),
        None,
    )
    if exec_line is None:
        return ["AppRun contains no exec line; nothing starts the interpreter"]

    try:
        argv = shlex.split(exec_line)
    except ValueError as exc:
        return [f"AppRun exec line does not parse as shell: {exc}"]

    if "-m" in argv:
        module = argv[argv.index("-m") + 1] if argv.index("-m") + 1 < len(argv) else ""
        if not module:
            return ["AppRun passes -m with no module name"]
        rel = Path("usr/app") / Path(*module.split("."))
        if (
            not (appdir / rel.with_suffix(".py")).is_file()
            and not (appdir / rel.with_suffix(".pyc")).is_file()
        ):
            return [
                f"AppRun runs `-m {module}`, but neither {rel.as_posix()}.py nor "
                f"{rel.as_posix()}.pyc exists in the payload"
            ]
        return []

    # Positional form: the second "$HERE/..." token is the script, the first
    # being the interpreter.
    here = [a for a in argv if a.startswith("$HERE/")]
    if len(here) < 2:
        return [f"AppRun exec line names no script to run: {exec_line.strip()!r}"]
    rel = here[1].removeprefix("$HERE/")
    if not (appdir / rel).is_file():
        sibling = ""
        if rel.endswith(".py") and (appdir / (rel + "c")).is_file():
            sibling = (
                f" — {rel}c is there, so the payload was byte-compiled and "
                "stripped while AppRun kept pointing at the source"
            )
        return [
            f"AppRun execs {rel}, which does not exist in the AppDir{sibling}; "
            "the app cannot start"
        ]
    return []


def _linux_payload_problems(appdir: Path, *, stripped: bool) -> list[str]:
    """Whether the Python payload is source or bytecode, and nothing in between.

    Same reasoning as the Android version — a ``.pyc`` beside its ``.py`` is
    silently ignored, so a half-stripped payload looks fine while shipping every
    source file the setting existed to remove.
    """
    payload = _payload_files(appdir)
    if not payload:
        return ["usr/app and usr/lib are both empty — the AppDir has no payload"]

    def rel(paths):
        return [p.relative_to(appdir).as_posix() for p in paths[:3]]

    sources = [p for p in payload if p.suffix == ".py"]
    compiled = [p for p in payload if p.suffix == ".pyc"]
    cached = [p for p in payload if "__pycache__" in p.parts]
    problems = []

    if stripped:
        if sources:
            problems.append(
                f"strip_source was applied but {len(sources)} .py file(s) remain "
                f"in the payload, e.g. {rel(sources)}"
            )
        if not compiled:
            problems.append(
                "strip_source was applied but the payload contains no .pyc at "
                "all — the build degraded to shipping source"
            )
        if cached:
            problems.append(
                f"payload has {len(cached)} __pycache__ entrie(s), e.g. "
                f"{rel(cached)} — sourceless imports need .pyc in the legacy "
                "location, not beside a source file that is no longer there"
            )
    else:
        if not sources:
            problems.append(
                "strip_source was not applied but the payload contains no .py at all"
            )
        if cached:
            # Normal in a working tree, never in a freshly staged AppDir: the
            # build writes the payload with compileall or not at all, so a
            # __pycache__ here means something *ran* from this artifact
            # afterwards and wrote into it. That is what the launcher's
            # PYTHONDONTWRITEBYTECODE exists to prevent, and it matters because
            # the folder form of an AppDir is also what these checks inspect.
            problems.append(
                f"payload has {len(cached)} __pycache__ entrie(s), e.g. "
                f"{rel(cached)} — a freshly built AppDir has none, so this "
                "artifact was written to after the build, most likely by "
                "launching it"
            )

    return problems


def _linux_pyc_magic_problems(appdir: Path, *, expected_magic: bytes) -> list[str]:
    """Every payload ``.pyc`` must carry the magic the shipped runtime imports.

    Roadmap item 1's actual bug. Note the Linux build reaches it down a
    different road than Android: a Linux x86_64 build on a Linux host is
    *native*, so ``select_compiler()`` hands the payload to the **staged**
    interpreter and never calls ``find_interpreter()``. The magic here is
    therefore the AppDir's own runtime's, which is why the driver reads it from
    that runtime rather than from the interpreter running pytest.
    """
    seen: dict[bytes, list[Path]] = {}
    for path in _payload_files(appdir):
        if path.suffix != ".pyc":
            continue
        with path.open("rb") as fh:
            seen.setdefault(fh.read(4), []).append(path)

    problems = []
    for magic, members in sorted(seen.items()):
        if magic != expected_magic:
            problems.append(
                f"{len(members)} .pyc file(s) carry magic {_magic_int(magic)} but "
                f"the shipped runtime imports {_magic_int(expected_magic)}, e.g. "
                f"{[p.name for p in members[:3]]} — these were written by an "
                "interpreter of a different CPython build and cannot be imported"
            )
    return problems


def _linux_elf_problems(appdir: Path, *, arch: str) -> list[str]:
    """Every ELF in the AppDir must be the target's class + machine.

    Deliberately the **whole tree**, which is the coverage that does not exist
    today: ``doctor.check_linux_native_binaries`` looks only under ``usr/bin``
    and SKIPs entirely unless ``[tool.kivy.linux.native.binaries]`` is declared,
    so the staged CPython, its ``lib-dynload`` extension modules, and every
    compiled wheel in site-packages are currently unchecked. A foreign-arch
    object there fails at ``dlopen`` with a message naming the file but not the
    reason.

    Unlike Android there is no hoisting rule to enforce: the Linux loader is
    happy to open a ``.so`` from anywhere the rpath reaches, so a shared object
    living in site-packages is correct rather than stranded.
    """
    expected = ARCH_ELF[arch]
    problems = []
    for path in sorted(appdir.rglob("*")):
        if not is_elf(path):
            continue
        try:
            found = elf_machine(path)
        except ElfError as exc:
            problems.append(f"{path.relative_to(appdir).as_posix()}: {exc}")
            continue
        if found != expected:
            problems.append(
                f"{path.relative_to(appdir).as_posix()} is {describe(*found)} but "
                f"{arch} requires {describe(*expected)}"
            )
    return problems


def linux_appimage_file_problems(appimage: Path, *, arch: str) -> list[str]:
    """The checks that can only be made on the ``.AppImage`` file itself.

    Extracting and inspecting the tree says nothing about the container
    ``appimagetool`` wrapped it in, and that tool had never run in this project
    before this artifact existed. A type-2 AppImage is an ELF whose e_ident
    padding carries ``AI\\x02`` at offset 8, with a squashfs filesystem appended
    — so this reads the header and nothing more.
    """
    if arch not in ARCH_ELF:
        return [f"unknown arch {arch!r}; expected one of {sorted(ARCH_ELF)}"]
    if not appimage.is_file():
        return [f"{appimage} is not a file"]

    with appimage.open("rb") as fh:
        header = fh.read(12)
    if header[:4] != ELF_MAGIC:
        return [f"{appimage.name} is not an ELF file; AppImage runtimes are ELF"]

    problems = []
    if header[8:11] != APPIMAGE_TYPE2_MAGIC:
        problems.append(
            f"{appimage.name} carries {header[8:11]!r} at offset 8, not the "
            f"type-2 AppImage marker {APPIMAGE_TYPE2_MAGIC!r} — appimagetool "
            "did not produce this, or produced a type-1 image"
        )
    try:
        found = elf_machine(appimage)
    except ElfError as exc:
        return [*problems, str(exc)]
    if found != ARCH_ELF[arch]:
        problems.append(
            f"{appimage.name} runtime is {describe(*found)} but {arch} requires "
            f"{describe(*ARCH_ELF[arch])} — the wrong type2-runtime was fetched"
        )
    return problems


# --------------------------------------------------------------------------
# Windows: onedir bundle
# --------------------------------------------------------------------------
#
# A real directory tree, like macOS's ``.app`` — not an archive. Strip scope is
# narrower than the whole bundle, same shape as macOS/Linux: only ``app`` (the
# developer's own sources) and ``python/Lib/site-packages`` (third-party deps)
# are ever byte-compiled (windows/bundle.py's ``byte_compile()`` call). The rest
# of ``python/`` — the embedded PBS prefix's own stdlib — is deliberately left
# as source (item 9) and must not be checked as if it were part of the same
# policy. ``_kivyforge_bootstrap.py`` lives at the bundle root: it is generated
# *after* byte-compilation runs (windows/bundle.py's ``write_bootstrap()`` call
# comes last), so it was never a candidate for stripping and a correctly scoped
# sweep does not even reach it.

WINDOWS_ARCH_MACHINES = {
    "amd64": IMAGE_FILE_MACHINE_AMD64,
    "arm64": IMAGE_FILE_MACHINE_ARM64,
}

_WINDOWS_STRIP_SCOPE = ("app", "python/Lib/site-packages")


def windows_onedir_problems(
    bundle: Path,
    *,
    arch: str,
    stripped: bool,
    expected_magic: bytes,
) -> list[str]:
    """Every way the onedir bundle at *bundle* fails to be the artifact the
    build promised.

    ``arch`` is a kivyforge Windows arch name (``amd64``), ``stripped`` whether
    ``strip_source`` applied to this build, and ``expected_magic`` the first
    four bytes a ``.pyc`` the bundle's own shipped runtime can import must
    carry — see the driver's ``_expected_magic()``, which asks the bundle's own
    ``python\\python.exe`` directly (same reasoning as the macOS/Linux drivers).
    """
    if arch not in WINDOWS_ARCH_MACHINES:
        return [
            f"unknown arch {arch!r}; expected one of {sorted(WINDOWS_ARCH_MACHINES)}"
        ]
    if not bundle.is_dir():
        return [f"{bundle} is not a directory"]

    problems = _windows_required_problems(bundle)
    problems += _windows_payload_problems(bundle, stripped=stripped)
    problems += _windows_pe_problems(bundle, arch=arch)
    problems += _windows_path_depth_problems(bundle)
    if stripped:
        problems += _windows_pyc_magic_problems(bundle, expected_magic=expected_magic)
    return problems


def _windows_path_depth_problems(bundle: Path) -> list[str]:
    """Whether the bundle still fits in a normal install folder, long paths off.

    Long paths are off on a default Windows install, so the bundle's deepest
    relative path decides how long a folder it can live in (test-matrix.md
    §5.6). The product warns about this at package time; asserting it here
    catches a kivyforge layout change that deepens every bundle, which the
    warning alone would only report.
    """
    deepest = deepest_relative_path(bundle)
    headroom = folder_headroom(deepest)
    if headroom >= MIN_FOLDER_HEADROOM:
        return []
    return [
        f"deepest path is {len(deepest)} characters ({deepest}), leaving only "
        f"{headroom} for the install folder with long paths off; need at least "
        f"{MIN_FOLDER_HEADROOM}"
    ]


def _windows_required_problems(bundle: Path) -> list[str]:
    """The handful of things without which this is not a launchable onedir bundle.

    ``bin/`` is deliberately not checked here: ``windows/bundle.py`` only
    creates it when ``lock.native_binaries`` is non-empty, so its absence is
    normal and must not be a fault (mirrors how the Linux checker treats
    optional native-binary staging).
    """
    problems = []
    exes = sorted(p for p in bundle.glob("*.exe") if p.is_file())
    if not exes:
        problems.append("no <Name>.exe launcher at the bundle root")
    elif len(exes) > 1:
        problems.append(
            f"{len(exes)} .exe files at the bundle root "
            f"({[p.name for p in exes]}); expected exactly one launcher"
        )
    if not (bundle / BOOTSTRAP_NAME).is_file():
        problems.append(f"{BOOTSTRAP_NAME} is missing from the bundle root")
    if not (bundle / "app").is_dir():
        problems.append("app/ (the app payload) is missing")
    if not (bundle / "python").is_dir():
        problems.append("python/ (the embedded runtime) is missing")
    return problems


def _windows_payload_problems(bundle: Path, *, stripped: bool) -> list[str]:
    """Whether the app + third-party payload is source or bytecode.

    Scoped to ``app``/``python/Lib/site-packages`` only — see the module-level
    note on why the embedded stdlib and the bootstrap module are excluded by
    design, not by omission.
    """
    problems: list[str] = []
    for scope in _WINDOWS_STRIP_SCOPE:
        base = bundle / scope
        if not base.is_dir():
            continue
        sources = sorted(p for p in base.rglob("*.py"))
        compiled = sorted(p for p in base.rglob("*.pyc"))
        cached = sorted(p for p in base.rglob("__pycache__") if p.is_dir())

        if stripped:
            if sources:
                rels = [p.relative_to(bundle).as_posix() for p in sources[:3]]
                problems.append(
                    f"strip_source was applied but {len(sources)} .py file(s) "
                    f"remain under {scope}, e.g. {rels}"
                )
            if not compiled:
                problems.append(
                    f"strip_source was applied but {scope} contains no .pyc at "
                    "all — the build degraded to shipping source"
                )
            if cached:
                rels = [p.relative_to(bundle).as_posix() for p in cached[:3]]
                problems.append(
                    f"{scope} has {len(cached)} __pycache__ dir(s), e.g. "
                    f"{rels} — sourceless imports need .pyc in the legacy "
                    "location, not beside a source file that is no longer there"
                )
        elif scope == "app" and not sources and not compiled:
            problems.append(f"{scope} has neither .py nor .pyc — no entry point")
    return problems


# distlib (vendored by pip, and in turn staged into every python-build-standalone
# prefix) ships six prebuilt launcher *templates* under a ``distlib/`` directory —
# one per (bitness, console/windowed) combination — that its own ScriptMaker
# patches at entry-point-install time to produce a real launcher on whatever host
# runs it. They are inert template payloads, never spawned or dlopen'd by the
# shipped app, and every pip install anywhere ships all six regardless of host or
# target arch — confirmed 2026-09-17 against this dev box's own venv pip, not
# just the built artifact. Real arch mismatches everywhere else in the tree are
# still caught; this is the one place "PE with a foreign machine type" does not
# mean "wrong binary leaked in". TestWindowsPeArch's distlib test is the
# regression guard for this exclusion.
_DISTLIB_LAUNCHER_STUBS = frozenset(
    {"t32.exe", "t64.exe", "t64-arm.exe", "w32.exe", "w64.exe", "w64-arm.exe"}
)


def _is_distlib_launcher_stub(path: Path) -> bool:
    return path.parent.name == "distlib" and path.name in _DISTLIB_LAUNCHER_STUBS


def _windows_pe_problems(bundle: Path, *, arch: str) -> list[str]:
    """Every PE image under the bundle must be *arch*, and only *arch*.

    Walks the whole tree — the launcher, the embedded runtime's own DLLs, every
    compiled wheel's extension modules, and any declared native binaries under
    ``bin/`` — same breadth as the macOS/Linux equivalents. A host-arch binary
    leaking into a cross-build is exactly the item-1-shaped bug this exists to
    catch, on the one platform where it would otherwise surface only as a
    cryptic ``OSError: [WinError 193]`` at import/load time. Distlib's own
    multi-arch launcher templates are excluded — see
    :func:`_is_distlib_launcher_stub`.
    """
    expected = WINDOWS_ARCH_MACHINES[arch]
    problems: list[str] = []
    for path in sorted(bundle.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        if _is_distlib_launcher_stub(path):
            continue
        machine = read_pe_machine(path)
        if machine is None:
            continue  # not a PE image — skip
        if machine != expected:
            rel = path.relative_to(bundle).as_posix()
            problems.append(
                f"{rel} is {pe_machine_name(machine)} but this build is {arch} "
                "— a host or cross-arch binary leaked into the bundle"
            )
    return problems


def _windows_pyc_magic_problems(bundle: Path, *, expected_magic: bytes) -> list[str]:
    """Every ``.pyc`` under the stripped scope must carry the shipped magic.

    Mirrors Android's ``_pyc_magic_problems`` / macOS's
    ``_macos_pyc_magic_problems`` / roadmap item 1's bug.
    """
    problems: list[str] = []
    for scope in _WINDOWS_STRIP_SCOPE:
        base = bundle / scope
        if not base.is_dir():
            continue
        seen: dict[bytes, list[Path]] = {}
        for pyc in sorted(base.rglob("*.pyc")):
            magic = pyc.read_bytes()[:4]
            seen.setdefault(magic, []).append(pyc)
        for magic, members in sorted(seen.items()):
            if magic != expected_magic:
                rels = [p.relative_to(bundle).as_posix() for p in members[:3]]
                problems.append(
                    f"{len(members)} .pyc file(s) under {scope} carry magic "
                    f"{_magic_int(magic)} but the bundle's own runtime imports "
                    f"{_magic_int(expected_magic)}, e.g. {rels} — these were "
                    "written by an interpreter of a different CPython build "
                    "and cannot be imported"
                )
    return problems
