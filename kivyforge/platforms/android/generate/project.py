"""Generate the Gradle/AGP project files (android/04).

Everything here is regenerated on every build (``<app>-android/`` is a
managed artifact); emission is deterministic — sorted dependency and property
lines, stable attribute order — so re-runs are byte-identical.
"""

from __future__ import annotations

import shutil
import stat
from pathlib import Path

from kivyforge.config.model import AndroidConfig, Config

from .. import toolchain
from ..lock.model import AndroidLockfile

# Wheel-tag ABI spelling -> Android's dashed directory/filter names.
ABI_TO_ANDROID = {"arm64_v8a": "arm64-v8a", "x86_64": "x86_64"}

# Wheel-tag ABI spelling -> the NDK target triplet (CMAKE_LIBRARY_ARCHITECTURE);
# the runtime staging area is keyed by triplet so CMake's {{triplet}}
# substitution (see the CMakeLists template) finds each ABI's own prefix.
ABI_TO_TRIPLET = {
    "arm64_v8a": "aarch64-linux-android",
    "x86_64": "x86_64-linux-android",
}

_WRAPPER_DIR = Path(__file__).parent.parent / "gradle_wrapper"


class ProjectGenError(Exception):
    pass


def android_abi(abi: str) -> str:
    return ABI_TO_ANDROID[abi]


def write_settings_gradle(dest: Path) -> None:
    _write(
        dest / "settings.gradle",
        'pluginManagement {\n'
        "    repositories { google(); mavenCentral(); gradlePluginPortal() }\n"
        "}\n"
        "dependencyResolutionManagement {\n"
        "    repositories { google(); mavenCentral() }\n"
        "}\n"
        'rootProject.name = "kivyforge-app"\n'
        'include ":app"\n',
    )


def write_root_build_gradle(dest: Path, android: AndroidConfig) -> None:
    lines = [
        "plugins {",
        f"    id 'com.android.application' version '{toolchain.AGP_VERSION}' "
        "apply false",
    ]
    if android.src.kotlin:
        lines.append(
            f"    id 'org.jetbrains.kotlin.android' version "
            f"'{toolchain.KOTLIN_VERSION}' apply false"
        )
    lines.append("}")
    _write(dest / "build.gradle", "\n".join(lines) + "\n")


def write_gradle_properties(dest: Path, android: AndroidConfig) -> None:
    managed = {
        "android.useAndroidX": "true",
        "org.gradle.jvmargs": "-Xmx2048m -Dfile.encoding=UTF-8",
    }
    merged = dict(managed)
    for key, value in android.gradle_properties.items():
        # Reserved keys were rejected at config time (rule 15).
        merged[str(key)] = _prop_str(value)
    lines = [f"{k}={v}" for k, v in sorted(merged.items())]
    _write(dest / "gradle.properties", "\n".join(lines) + "\n")


def stage_gradle_wrapper(dest: Path) -> None:
    """Stage the vendored wrapper + the pinned distribution properties."""
    wrapper_dir = dest / "gradle" / "wrapper"
    wrapper_dir.mkdir(parents=True, exist_ok=True)
    jar = _WRAPPER_DIR / "gradle-wrapper.jar"
    if not jar.is_file():
        raise ProjectGenError(
            f"vendored gradle-wrapper.jar missing at {jar}; the kivyforge "
            "installation is incomplete."
        )
    shutil.copy2(jar, wrapper_dir / "gradle-wrapper.jar")
    _write(
        wrapper_dir / "gradle-wrapper.properties",
        "distributionBase=GRADLE_USER_HOME\n"
        "distributionPath=wrapper/dists\n"
        f"distributionUrl={toolchain.GRADLE_DISTRIBUTION_URL}\n"
        "zipStoreBase=GRADLE_USER_HOME\n"
        "zipStorePath=wrapper/dists\n",
    )
    for script in ("gradlew", "gradlew.bat"):
        source = _WRAPPER_DIR / script
        target = dest / script
        shutil.copy2(source, target)
        if script == "gradlew":
            target.chmod(target.stat().st_mode | stat.S_IEXEC)


def write_app_build_gradle(
    dest: Path,
    config: Config,
    android: AndroidConfig,
    *,
    python_version: str,
    runtime_root: Path,
    staged_libs: list[str],
    abis: tuple[str, ...] | None = None,
    signing_config_block: str = "",
) -> None:
    """Emit ``app/build.gradle``.

    ``abis`` is the *effective* ABI set for this build (a ``--abi`` restriction
    must narrow the Gradle abiFilters too, or AGP builds ABIs whose runtime was
    never staged); defaults to the full configured set.

    ``runtime_root`` is the staging directory holding one extracted runtime
    per target triplet (``<runtime_root>/<triplet>/prefix``). AGP invokes
    CMake once per ABI; the ``{{triplet}}`` placeholder in ``PYTHON_PREFIX_DIR``
    is resolved *inside* CMake via ``CMAKE_LIBRARY_ARCHITECTURE`` (the
    python.org testbed's mechanism), so each ABI's launcher links its own
    libpython — a Gradle-side lookup cannot do this for plain ``gradlew``
    builds (``android.injected.build.abi`` is Studio-only).
    """
    effective = abis if abis is not None else tuple(android.abis)
    abis_filter = ", ".join(f"'{android_abi(a)}'" for a in effective)
    stem = "python" + ".".join(python_version.split(".")[:2])
    prefix_arg = _gradle_path(runtime_root) + "/{{triplet}}/prefix"

    deps: list[str] = [
        "    implementation 'com.google.android.material:material:1.11.0'",
        # The generated contract smoke test (android/06 --smoke).
        "    androidTestImplementation 'androidx.test.ext:junit:1.1.5'",
        "    androidTestImplementation 'androidx.test:core:1.5.0'",
        "    androidTestImplementation 'androidx.test:runner:1.5.2'",
    ]
    if android.splash.source:
        deps.append(
            f"    implementation '{toolchain.CORE_SPLASHSCREEN_COORDINATE}'"
        )
    for lib in sorted(staged_libs):
        deps.append(f"    implementation files('libs/{lib}')")
    for coordinate in sorted(android.gradle.dependencies):
        deps.append(f"    implementation '{coordinate}'")

    plugins = ["    id 'com.android.application'"]
    if android.src.kotlin:
        plugins.append("    id 'org.jetbrains.kotlin.android'")

    src_dirs = "".join(
        f"            java.srcDirs += '{_gradle_path(Path(p))}'\n"
        for p in [*android.src.java, *android.src.kotlin]
    )

    bs = android.build_settings
    strip = _release_flag(bs.strip_native_libs)
    minify = "true" if bs.minify else "false"
    shrink = "true" if (bs.shrink_resources and bs.minify) else "false"
    # Keep .so debug symbols unless a stripped release is configured (AGP does
    # the strip, tracking the toolchain + preserving 16 KB alignment).
    keep_symbols_line = (
        "" if strip else "            keepDebugSymbols += ['**/*.so']\n"
    )
    debug_symbol_level = {
        "symbol_table": "SYMBOL_TABLE",
        "full": "FULL",
        "none": "NONE",
    }[bs.debug_symbols]
    release_signing = (
        "            signingConfig signingConfigs.release\n"
        if signing_config_block
        else ""
    )

    text = f"""\
plugins {{
{chr(10).join(plugins)}
}}

android {{
    namespace '{android.package}'
    compileSdk {android.compile_sdk}
    ndkVersion '{toolchain.NDK_VERSION}'

    defaultConfig {{
        applicationId '{android.package}'
        minSdk {android.min_sdk}
        targetSdk {android.target_sdk}
        versionCode {android.version_code}
        versionName '{config.project.version}'
        testInstrumentationRunner 'androidx.test.runner.AndroidJUnitRunner'
        ndk {{ abiFilters {abis_filter} }}
        externalNativeBuild {{
            cmake {{
                arguments '-DPYTHON_VERSION={stem[6:]}',
                          '-DANDROID_SUPPORT_FLEXIBLE_PAGE_SIZES=ON',
                          '-DPYTHON_PREFIX_DIR={prefix_arg}'
            }}
        }}
    }}

    externalNativeBuild {{
        cmake {{ path 'src/main/cpp/CMakeLists.txt' }}
    }}

    // AAPT's default ignore pattern drops asset dirs starting with '_', which
    // would silently exclude _python_bundle (loadmodel findings #4).
    aaptOptions.ignoreAssetsPattern = 'kivyforge-dont-ignore-anything'

    packagingOptions {{
        jniLibs {{
            // Extract native libs so dlopen-by-path works for the flattened
            // extension modules (android/04 §load model).
            useLegacyPackaging = true
{keep_symbols_line}        }}
    }}

{signing_config_block}
    buildTypes {{
        release {{
            minifyEnabled {minify}
            shrinkResources {shrink}
{release_signing}            ndk {{ debugSymbolLevel '{debug_symbol_level}' }}
            proguardFiles getDefaultProguardFile('proguard-android-optimize.txt'), \
'proguard-rules.pro'
        }}
    }}

    sourceSets {{
        main {{
{src_dirs}        }}
    }}

    compileOptions {{
        sourceCompatibility JavaVersion.VERSION_1_8
        targetCompatibility JavaVersion.VERSION_1_8
    }}
}}

dependencies {{
{chr(10).join(deps)}
}}
"""
    _write(dest / "app" / "build.gradle", text)
    _write(
        dest / "app" / "proguard-rules.pro",
        "# kivyforge keep-rules: pyjnius reflects into these at runtime.\n"
        "-keep class org.jnius.** {{ *; }}\n".replace("{{", "{").replace("}}", "}")
        + "-keep class org.kivy.android.** { *; }\n"
        "-keep class org.renpy.android.** { *; }\n"
        "-keep class org.libsdl.app.** { *; }\n",
    )


def _release_flag(value: bool | str) -> bool:
    """A build_settings tri-state -> whether it applies to a release build."""
    from kivyforge.config.model import ANDROID_RELEASE_ONLY

    return value is True or value == ANDROID_RELEASE_ONLY


def write_resources(dest: Path, config: Config, android: AndroidConfig) -> None:
    res = dest / "app" / "src" / "main" / "res"
    values = res / "values"
    values.mkdir(parents=True, exist_ok=True)
    _write(
        values / "strings.xml",
        '<resources><string name="app_name">'
        f"{_xml_escape(config.display_name)}</string></resources>\n",
    )
    _write(
        values / "styles.xml",
        "<resources>\n"
        f'    <style name="Theme.Kivyforge" parent="{android.base_theme}" />\n'
        "</resources>\n",
    )
    # Default launcher icon when no [tool.kivy.android.icons] is configured
    # (android/01: "kivyforge emits a plain default launcher icon"). The full
    # adaptive-icon pipeline from a 1024x1024 source is the icons.py work item.
    if not android.icons.source:
        mipmap = res / "mipmap-mdpi"
        mipmap.mkdir(parents=True, exist_ok=True)
        (mipmap / "ic_launcher.png").write_bytes(_default_icon_png())


def _default_icon_png() -> bytes:
    """A valid 48x48 solid-color PNG, generated without any imaging library."""
    import struct
    import zlib

    size = 48
    # Kivy-ish blue-grey, RGBA.
    pixel = bytes((52, 73, 94, 255))
    raw = b"".join(b"\x00" + pixel * size for _ in range(size))

    def chunk(kind: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + kind
            + payload
            + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


def write_gradle_pins(dest: Path, lock: AndroidLockfile) -> None:
    """Materialize the committed Maven-graph record into the project (android/02).

    Only when Maven coordinates are declared. The app's declared coordinates are
    version-pinned in ``app/build.gradle`` (``implementation 'g:a:v'``), and the
    **full resolved transitive graph with a per-artifact SHA-256 is the committed
    audit record in ``pylock.android.toml``** (``[[tool.kivyforge.gradle.resolved]]``);
    `write_gradle_pins` mirrors that record into ``app/gradle.lockfile`` for
    reference.

    > **Scoped in v1.** Gradle's ``verification-metadata.xml`` enforces SHA-256
    > over the *entire* build classpath (AGP, androidx, transforms), not just the
    > app's Maven deps — which the lock does not resolve. Emitting a partial
    > metadata file makes Gradle reject every unlisted build artifact, so v1
    > records the app-dep hashes in the lock (the auditable source of truth) and
    > defers Gradle-*enforced* verification to a future full-classpath resolve.
    > See docs/design/platforms/android/02 §Gradle pins (realized-vs-designed).
    """
    # Remove any stale strict metadata a prior kivyforge emitted (it would make
    # Gradle verify the entire build classpath and fail) — the generated project
    # is regenerated every build, so leftovers must be swept.
    stale = dest / "gradle" / "verification-metadata.xml"
    if stale.exists():
        stale.unlink()
    if not lock.gradle.declared:
        return
    lock_lines = [
        "# Generated by kivyforge from pylock.android.toml — the resolved Maven",
        "# graph (per-artifact SHA-256) is committed in pylock.android.toml.",
    ]
    for module in sorted(lock.gradle.resolved, key=lambda m: m.coordinate):
        for artifact in module.artifacts:
            lock_lines.append(f"# {module.coordinate}  {artifact.name}  "
                              f"sha256:{artifact.sha256}")
    _write(dest / "app" / "gradle.lockfile", "\n".join(lock_lines) + "\n")


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def _gradle_path(path: Path) -> str:
    return str(path).replace("\\", "/")


def _prop_str(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _xml_escape(text: str) -> str:
    from xml.sax.saxutils import escape

    return escape(text)
