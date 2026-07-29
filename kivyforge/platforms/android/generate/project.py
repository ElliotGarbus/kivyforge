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

from .. import policy, toolchain
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

# The generated task that copies AGP's merged release manifest somewhere stable,
# and where it lands (relative to the generated project root). `kivyforge
# package` runs the task, then lints the copy.
MERGED_MANIFEST_TASK = "exportKivyforgeReleaseManifest"
MERGED_MANIFEST_RELPATH = Path(
    "app", "build", "kivyforge", "AndroidManifest-merged-release.xml"
)


class ProjectGenError(Exception):
    pass


def android_abi(abi: str) -> str:
    return ABI_TO_ANDROID[abi]


def write_settings_gradle(dest: Path, android: AndroidConfig | None = None) -> None:
    """Emit ``settings.gradle``, including any declared extra Maven repos.

    ``[tool.kivy.android.gradle].repositories`` has to be honored here as well
    as at lock time: the lock resolves the graph in a scratch project, so a
    coordinate that only exists in a private repo would lock fine and then fail
    to resolve in the generated build (android/01 §gradle).
    """
    extra = tuple(android.gradle.repositories) if android is not None else ()
    repos = ["        google()", "        mavenCentral()"]
    repos += [f"        maven {{ url = uri({_groovy_str(url)}) }}" for url in extra]
    _write(
        dest / "settings.gradle",
        "pluginManagement {\n"
        "    repositories { google(); mavenCentral(); gradlePluginPortal() }\n"
        "}\n"
        "dependencyResolutionManagement {\n"
        "    repositories {\n" + "\n".join(repos) + "\n    }\n"
        "}\n"
        'rootProject.name = "kivyforge-app"\n'
        'include ":app"\n',
    )


def _groovy_str(value: str) -> str:
    """A single-quoted Groovy string literal."""
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


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
    release_signing_config: str | None = None,
    test_build_type: str | None = None,
) -> None:
    """Emit ``app/build.gradle``.

    ``abis`` is the *effective* ABI set for this build (a ``--abi`` restriction
    must narrow the Gradle abiFilters too, or AGP builds ABIs whose runtime was
    never staged); defaults to the full configured set.

    ``release_signing_config`` names the signing config the release build type
    uses (default: ``release`` when a ``signing_config_block`` was supplied,
    otherwise unsigned). ``test_build_type`` selects which variant the
    instrumented tests run against — AGP only generates
    ``connected<Variant>AndroidTest`` for that one variant, so the release smoke
    test needs it set to ``release``.

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
    keep_symbols_line = "" if strip else "            keepDebugSymbols += ['**/*.so']\n"
    debug_symbol_level = {
        "symbol_table": "SYMBOL_TABLE",
        "full": "FULL",
        "none": "NONE",
    }[bs.debug_symbols]
    # At minSdk 21+ the platform loads multiple dex files natively, so this is
    # only about whether AGP is *allowed* to split: left on, the bundled .aars
    # plus the bootstrap can exceed the 64K method limit without failing the
    # build; turned off, an over-limit project fails at dexing.
    multidex = "true" if bs.multidex else "false"
    signing_name = release_signing_config or ("release" if signing_config_block else "")
    release_signing = (
        f"            signingConfig signingConfigs.{signing_name}\n"
        if signing_name
        else ""
    )
    test_build_type_line = (
        f"    testBuildType '{test_build_type}'\n" if test_build_type else ""
    )

    lint_checks = ", ".join(f"'{check}'" for check in policy.LINT_CHECKS)
    merged_manifest_name = MERGED_MANIFEST_RELPATH.name

    text = f"""\
import com.android.build.api.artifact.SingleArtifact

plugins {{
{chr(10).join(plugins)}
}}

android {{
    namespace '{android.package}'
    compileSdk {android.compile_sdk}
    ndkVersion '{toolchain.NDK_VERSION}'
{test_build_type_line}
    defaultConfig {{
        applicationId '{android.package}'
        minSdk {android.min_sdk}
        targetSdk {android.target_sdk}
        versionCode {android.version_code}
        versionName '{config.project.version}'
        multiDexEnabled {multidex}
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

    // The release policy's delegated half (android/06 §package). checkOnly
    // narrows the run to the curated subset and `fatal` raises exactly those to
    // build-breaking, so a future Lint's new checks can never spuriously block a
    // release (and a stale id stays a warning instead of failing every build).
    // `kivyforge package` runs lintRelease before it assembles, so a finding
    // blocks before signing.
    lint {{
        checkOnly.addAll([{lint_checks}])
        fatal.addAll([{lint_checks}])
        abortOnError = true
        checkReleaseBuilds = true
        htmlReport = true
        xmlReport = true
    }}
}}

// kivyforge's own half of the policy lints the *merged* release manifest, so
// export it to a stable path (AGP's intermediates layout is not a contract).
androidComponents {{
    onVariants(selector().withName('release')) {{ variant ->
        tasks.register('{MERGED_MANIFEST_TASK}', Copy) {{
            from(variant.artifacts.get(SingleArtifact.MERGED_MANIFEST.INSTANCE))
            into(layout.buildDirectory.dir('kivyforge'))
            rename {{ '{merged_manifest_name}' }}
        }}
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


def write_resources(
    dest: Path, config: Config, android: AndroidConfig, *, project_root: Path
) -> None:
    res = dest / "app" / "src" / "main" / "res"
    values = res / "values"
    values.mkdir(parents=True, exist_ok=True)
    _write(
        values / "strings.xml",
        '<resources><string name="app_name">'
        f"{_xml_escape(config.display_name)}</string></resources>\n",
    )
    # The generated manifest names @mipmap/ic_launcher unconditionally, so the
    # icon set is written on every build — the default one when no source is
    # configured, the full adaptive set when there is.
    from ..icons import IconError, write_icons
    from ..splash import SplashError, write_splash

    try:
        write_icons(res, config, android, project_root)
    except IconError as exc:
        raise ProjectGenError(str(exc)) from exc
    try:
        splash = write_splash(res, android, project_root)
    except SplashError as exc:
        raise ProjectGenError(str(exc)) from exc
    _write(values / "styles.xml", _styles_xml(android, splash, v31=False))
    if splash.configured:
        # A values-v31 resource replaces the same-named one wholesale, so the
        # override repeats the whole style rather than adding to it.
        v31 = res / "values-v31"
        v31.mkdir(parents=True, exist_ok=True)
        _write(v31 / "styles.xml", _styles_xml(android, splash, v31=True))


def _styles_xml(android: AndroidConfig, splash, *, v31: bool) -> str:
    """The app theme, with the splash items the given API level understands."""
    items: list[tuple[str, str]] = []
    if splash.window_background is not None:
        items.append(("android:windowBackground", splash.window_background))
    if v31:
        items += list(splash.v31_items)
    if not items:
        return (
            "<resources>\n"
            f'    <style name="Theme.Kivyforge" parent="{android.base_theme}" />\n'
            "</resources>\n"
        )
    body = "".join(
        f'        <item name="{name}">{value}</item>\n' for name, value in items
    )
    return (
        "<resources>\n"
        f'    <style name="Theme.Kivyforge" parent="{android.base_theme}">\n'
        f"{body}"
        "    </style>\n"
        "</resources>\n"
    )


def write_gradle_pins(dest: Path, lock: AndroidLockfile) -> None:
    """Materialize the committed Maven-graph record into the project (android/02).

    Only when Maven coordinates are declared. The app's declared coordinates are
    version-pinned in ``app/build.gradle`` (``implementation 'g:a:v'``), and the
    **full resolved transitive graph with a per-artifact SHA-256 is the committed
    audit record in ``pylock.android.toml``** (``[[tool.kivyforge.gradle.resolved]]``);
    `write_gradle_pins` mirrors that record into ``app/gradle.lockfile`` as
    comments, for reference. Neither Gradle dependency locking nor Gradle artifact
    verification is enabled, so this channel's hashes are audited, not enforced —
    the docs say so in those words (android/02 §Gradle pins).

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
        "#",
        "# INFORMATIONAL. Gradle dependency locking is not enabled in this project,",
        "# so this file gates nothing: it mirrors the lock's audit record at the",
        "# path a Gradle lock would live. Declared coordinates are version-pinned",
        "# in app/build.gradle. See docs/design/platforms/android/02 §Gradle pins.",
    ]
    for module in sorted(lock.gradle.resolved, key=lambda m: m.coordinate):
        for artifact in module.artifacts:
            lock_lines.append(
                f"# {module.coordinate}  {artifact.name}  sha256:{artifact.sha256}"
            )
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
