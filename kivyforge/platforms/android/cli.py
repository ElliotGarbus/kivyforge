"""``kivyforge build`` — Android behavior (android/06 steps 1-8).

Steps 1-7 (verify, collect, stage, generate) always run; step 8 (Gradle
``assembleDebug``) only with ``--debug``. Signed releases are ``package``'s
job (Phase 6).
"""

from __future__ import annotations

import shutil
from pathlib import Path

import click

from kivyforge.artifacts.download import fetch_artifact
from kivyforge.config import ConfigError, load_config
from kivyforge.config.model import AndroidConfig, Config
from kivyforge.lock.reader import LockError, is_in_sync

from . import AndroidBuildError
from .bootstrap.contract import (
    ContractError,
    check_pyjnius_contract,
    check_sdl_generation,
    check_sdl_glue_contract,
    sdl_library_name,
)
from .bootstrap.render import (
    androidtest_files,
    finder_source,
    kivy_bootstrap_source,
    python_stem,
    render_bootstrap,
    selftest_source,
)
from .generate.manifest import generate_manifest
from .generate.project import (
    ABI_TO_TRIPLET,
    ProjectGenError,
    android_abi,
    stage_gradle_wrapper,
    write_app_build_gradle,
    write_gradle_pins,
    write_gradle_properties,
    write_resources,
    write_root_build_gradle,
    write_settings_gradle,
)
from .generate.services import render_service_classes, render_service_contract_test
from .gradlew import GradleError, run_gradle
from .lock import reader as lock_reader
from .lock.model import AndroidLockfile
from .stage.bundle import BUNDLE_DIRNAME, BundleError, assemble_bundle
from .stage.jnilibs import (
    JniLibsError,
    JniLibsStager,
    stage_runtime_libs,
    stage_site_packages_extensions,
    stage_wheel_libs_dir,
)
from .stage.runtime import RuntimeStageError, extract_runtime, stdlib_dir
from .stage.wheels import WheelStageError, install_wheels, select_wheel


def project_dir_for(project_root: Path, config: Config) -> Path:
    return project_root / f"{config.app_slug}-android"


def _prune_stale(directory: Path, pattern: str, *, keep: set[str]) -> None:
    """Delete generated sources that this build no longer produces.

    The project dir is incremental, so a class generated for a service that has
    since been removed from pyproject.toml would keep being compiled into the
    APK — and, for the service probe, would stop the test source compiling at
    all once its target class is gone.
    """
    if not directory.is_dir():
        return
    for path in directory.glob(pattern):
        if path.name not in keep:
            path.unlink()


def _setting_applies(value: bool | str, *, release: bool) -> bool:
    """A ``build_settings`` tri-state resolved for the build being produced."""
    if isinstance(value, bool):
        return value
    return release  # ANDROID_RELEASE_ONLY


def _target_minor(python_version: str) -> tuple[int, int]:
    parts = python_version.split(".")[:2]
    return (int(parts[0].split("rc")[0]), int(parts[1].split("rc")[0]))


def _byte_compile_interpreter(python_version: str) -> tuple[str, ...] | None:
    """Find an interpreter that can write ``.pyc`` for the target runtime.

    A ``.pyc`` is keyed to one exact CPython magic number, and that number is
    frozen at each minor's first **release candidate** — so any *final*
    ``3.x.z`` will do, but a different minor will not: its output is silently
    ignored when the source ships alongside, and fails outright once the source
    is stripped.

    A pre-release of the *right* minor is the trap. CPython bumps the magic
    number repeatedly through the alpha/beta cycle, so 3.14.0a7 (magic 3621)
    writes bytecode that shipped 3.14.6 (magic 3627) refuses to import —
    while still answering "3.14" to a version check. Candidates must therefore
    report ``releaselevel == "final"``, not merely the right minor.

    kivyforge is installed under whatever Python the user has, which is usually
    *not* the version being shipped to the device, so this looks for a matching
    one rather than insisting on being run under it. Returns ``()`` for "this
    interpreter", an argv prefix for another one, or ``None`` when there is no
    match to be found.
    """
    import os
    import sys

    from kivyforge.bundle.pycompile import is_final_release

    target = _target_minor(python_version)
    if sys.version_info[:2] == target and is_final_release():
        return ()
    tag = f"{target[0]}.{target[1]}"
    candidates: list[tuple[str, ...]] = []
    if os.name == "nt":
        # The PEP 397 launcher is the reliable way to reach a specific version
        # on Windows; versioned executables are usually not on PATH there.
        candidates.append(("py", f"-{tag}"))
    candidates += [(f"python{tag}",), (f"python{target[0]}",), ("python",)]
    for candidate in candidates:
        if _reports_version(candidate, tag):
            return candidate
    return None


def _reports_version(argv: tuple[str, ...], tag: str) -> bool:
    """Whether *argv* is a **final** release of CPython minor *tag*.

    The releaselevel half is load-bearing, not belt-and-braces: an alpha of the
    right minor passes a bare version check and then writes ``.pyc`` the
    shipped runtime cannot import (see :func:`_byte_compile_interpreter`).
    """
    import subprocess

    try:
        proc = subprocess.run(
            [
                *argv,
                "-c",
                "import sys;print('%d.%d %s' % (sys.version_info[0],"
                " sys.version_info[1], sys.version_info.releaselevel))",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    if proc.returncode != 0:
        return False
    parts = proc.stdout.split()
    return len(parts) == 2 and parts[0] == tag and parts[1] == "final"


def _resolve_byte_compile(
    android: AndroidConfig, *, python_version: str, debug: bool
) -> tuple[tuple[str, ...] | None, bool]:
    """Decide whether to byte-compile, and with which interpreter.

    Returns ``(compiler_argv_or_None, strip_source)``; ``None`` means do not
    byte-compile. ``byte_compile = true`` is read as "I insist", so a missing
    interpreter is an error; the default ``"release"`` is read as "when it makes
    sense", so it degrades to shipping source with a warning rather than
    breaking a build the user never configured.
    """
    settings = android.build_settings
    if not _setting_applies(settings.byte_compile, release=not debug):
        return None, False
    compiler = _byte_compile_interpreter(python_version)
    if compiler is None:
        target = ".".join(str(p) for p in _target_minor(python_version))
        message = (
            f"this project ships CPython {python_version}, and no *final* "
            f"release of CPython {target} was found to byte-compile with (a "
            "pre-release of the right minor is not enough — CPython only "
            "freezes the .pyc magic number at the first release candidate, so "
            f"e.g. {target}.0a7 writes bytecode {python_version} refuses to "
            "import)"
        )
        if settings.byte_compile is True:
            raise AndroidBuildError(
                "[tool.kivy.android.build_settings].byte_compile = true but "
                f"{message}.\n"
                f"  Install a final CPython {target} release (kivyforge will "
                "find it), or set byte_compile = false."
            )
        click.echo(f"[stage] not byte-compiling: {message}.")
        return None, False
    # Documented as "ignored when byte_compile is off": stripping sources with
    # no .pyc beside them would ship a bundle that imports nothing.
    strip = _setting_applies(settings.strip_source, release=not debug)
    return compiler, strip


def android_build(
    project_root: Path,
    *,
    debug: bool = False,
    fmt: str = "apk",
    abi: str | None = None,
    no_verify_lock: bool = False,
    no_cache: bool = False,
    signing_config_block: str = "",
    release_signing_config: str | None = None,
    test_build_type: str | None = None,
) -> Path:
    """Steps 1-7 (+8 with ``debug``); returns the generated project dir.

    ``debug`` also selects which side of the ``"release"`` build settings the
    staged bundle gets: the payload is baked into ``assets/`` at generate time,
    so the tri-state has to be resolved here rather than per Gradle build type.
    Generating without ``--debug`` stages the release payload, which is what
    ``kivyforge package`` then assembles.
    """
    config, lock = _load(project_root, no_verify_lock=no_verify_lock)
    android = config.android_required
    abis = _select_abis(android, abi)

    dest = project_dir_for(project_root, config)
    app_main = dest / "app" / "src" / "main"

    # Step 7 pre-check (hard gate BEFORE any generation): the pyjnius/bootstrap
    # invoke0 matched pair (android/05).
    locked_pyjnius = _locked_version(lock, "pyjnius")
    if locked_pyjnius is not None:
        try:
            check_pyjnius_contract(locked_pyjnius)
        except ContractError as exc:
            raise AndroidBuildError(str(exc)) from exc

    python_version = lock.python_android[0].version
    stem = python_stem(python_version)

    # --- Step 2: collect + extract the runtime per targeted ABI ---
    runtime_root = dest / "python-runtime"
    prefixes: dict[str, Path] = {}
    for runtime in lock.python_android:
        if runtime.abi not in abis:
            continue
        click.echo(f"[collect] python.org runtime {runtime.version} ({runtime.abi})")
        tarball = fetch_artifact(
            name=f"python-android-{runtime.abi}",
            sha256=runtime.sha256,
            filename=(runtime.url or runtime.path or "").rsplit("/", 1)[-1],
            url=runtime.url,
            path=runtime.path,
            project_root=project_root,
            no_cache=no_cache,
        )
        triplet = ABI_TO_TRIPLET[runtime.abi]
        prefixes[runtime.abi] = _stage(
            lambda: extract_runtime(Path(tarball), runtime_root / triplet),
            RuntimeStageError,
        )

    # --- Step 3: collect .aar/.jar into app/libs ---
    libs_dir = dest / "app" / "libs"
    staged_libs: list[str] = []
    for lib in lock.android_libs:
        click.echo(f"[collect] {lib.kind} {lib.name} {lib.version}")
        archive = fetch_artifact(
            name=lib.name,
            sha256=lib.sha256,
            filename=(lib.url or lib.path or "").rsplit("/", 1)[-1],
            url=lib.url,
            path=lib.path,
            project_root=project_root,
            no_cache=no_cache,
        )
        libs_dir.mkdir(parents=True, exist_ok=True)
        target = libs_dir / Path(archive).name
        shutil.copy2(archive, target)
        staged_libs.append(target.name)

    # --- Step 4: install wheels per ABI ---
    site_packages: dict[str, Path] = {}
    for abi_name in abis:
        target = dest / "pip-deps" / abi_name
        if target.exists():
            shutil.rmtree(target)
        # The artifact cache stores files as {sha256}-{name}; pip validates
        # wheel FILENAMES, so each fetched wheel is staged under its true name.
        wheel_stage = dest / "pip-deps" / f"_wheels-{abi_name}"
        if wheel_stage.exists():
            shutil.rmtree(wheel_stage)
        wheel_stage.mkdir(parents=True)
        files = []
        for package in lock.packages:
            wheel = select_wheel(package, abi=abi_name, min_sdk=android.min_sdk)
            fetched = Path(
                fetch_artifact(
                    name=package.name,
                    sha256=wheel.sha256,
                    filename=wheel.name,
                    url=wheel.url,
                    path=wheel.path,
                    project_root=project_root,
                    no_cache=no_cache,
                )
            )
            staged = wheel_stage / wheel.name
            if fetched.name != wheel.name:
                shutil.copy2(fetched, staged)
            else:
                staged = fetched
            files.append(staged)
        click.echo(f"[stage] installing {len(files)} wheels for {abi_name}")
        _stage(
            lambda: install_wheels(files, target, python_version=python_version),
            WheelStageError,
        )
        site_packages[abi_name] = target

    # --- Step 5: jniLibs per ABI (runtime split + wheel exts + .libs) ---
    ext_manifest_json = ""
    for abi_name in abis:
        jni = app_main / "jniLibs" / android_abi(abi_name)
        if jni.exists():
            shutil.rmtree(jni)
        stager = JniLibsStager(dest=jni)

        def _stage_all() -> None:
            prefix = prefixes[abi_name]
            stage_runtime_libs(stager, prefix / "lib", python_stem=stem)
            sp = site_packages[abi_name]
            for package in lock.packages:
                wheel_name = package.name
                libs = sp / ".libs"
                if libs.is_dir():
                    stage_wheel_libs_dir(stager, libs, wheel_name=wheel_name)
                    break  # one flat .libs per staging tree
            stage_site_packages_extensions(stager, sp, wheel_name="site-packages")

        _stage(_stage_all, JniLibsError)
        manifest = stager.manifest()
        import json as _json

        ext_manifest_json = _json.dumps(manifest, indent=1, sort_keys=True) + "\n"
        click.echo(
            f"[stage] jniLibs/{android_abi(abi_name)}: "
            f"{len(manifest)} extensions flattened"
        )

    # --- Step 6: the ABI-independent asset bundle ---
    canonical = abis[0]
    compiler, strip_source = _resolve_byte_compile(
        android, python_version=python_version, debug=debug
    )
    if compiler is not None:
        with_what = " ".join(compiler) if compiler else "this interpreter"
        click.echo(
            f"[stage] byte-compiling the Python payload with {with_what}"
            + (" (.pyc only)" if strip_source else "")
        )
    stamp = _stage(
        lambda: assemble_bundle(
            app_main / "assets" / BUNDLE_DIRNAME,
            stdlib_src=stdlib_dir(prefixes[canonical], stem),
            site_packages_by_abi={a: site_packages[a] for a in abis},
            canonical_abi=canonical,
            app_src=project_root / config.kivy.app_dir,
            entry_point=config.kivy.entry_point,
            service_entry_points={s.name: s.entry_point for s in android.services},
            finder_source=finder_source(),
            kivy_bootstrap_source=kivy_bootstrap_source(),
            ext_manifest_json=ext_manifest_json,
            selftest_source=selftest_source(),
            byte_compile=compiler,
            strip_source=strip_source,
        ),
        BundleError,
    )
    click.echo(f"[stage] asset bundle assembled (stamp {stamp})")

    # --- Step 7: (re)generate the Gradle project ---
    sdl_activity_java = ""
    for rendered in render_bootstrap(
        sdl=android.kivy_generation,
        python_version=python_version,
        entry_point=config.kivy.entry_point,
    ):
        out = app_main / rendered.relpath
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(rendered.content, encoding="utf-8", newline="\n")
        if rendered.relpath.endswith("org/libsdl/app/SDLActivity.java"):
            sdl_activity_java = rendered.content

    # 7b. The classes the manifest's <service> entries name. Written after the
    # bootstrap so they land next to the PythonService base they extend, and
    # pruned so a service removed from pyproject.toml stops being compiled in.
    service_classes = render_service_classes(android.services)
    for rendered in service_classes:
        out = app_main / rendered.relpath
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(rendered.content, encoding="utf-8", newline="\n")
    _prune_stale(
        app_main / "java" / "org" / "kivy" / "android",
        "Service*.java",
        keep={Path(r.relpath).name for r in service_classes},
    )
    if service_classes:
        click.echo(f"[generate] {len(service_classes)} service class(es)")

    # The SDL glue and the wheel's libSDL<N>.so are a matched pair: SDLActivity
    # aborts onCreate silently when their versions disagree, and dies in its
    # static initializer when the generations disagree — so catch both here
    # rather than as an unexplained black screen on-device.
    for abi_name in abis:
        jni = app_main / "jniLibs" / android_abi(abi_name)
        staged = [p.name for p in jni.glob("libSDL*.so")] if jni.is_dir() else []
        try:
            check_sdl_generation(generation=android.kivy_generation, staged=staged)
        except ContractError as exc:
            raise AndroidBuildError(str(exc)) from exc
        so = jni / sdl_library_name(android.kivy_generation)
        if not sdl_activity_java or not so.is_file():
            continue
        try:
            check_sdl_glue_contract(java_source=sdl_activity_java, so_path=so)
        except ContractError as exc:
            raise AndroidBuildError(str(exc)) from exc
    service_tests = render_service_contract_test(android.services)
    for rendered in androidtest_files() + service_tests:
        out = dest / "app" / "src" / rendered.relpath
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(rendered.content, encoding="utf-8", newline="\n")
    if not service_tests:
        # No service declared: the probe from a previous build would fail to
        # compile now that its target class is gone.
        _prune_stale(
            dest
            / "app"
            / "src"
            / "androidTest"
            / "java"
            / "org"
            / "kivyforge"
            / "test",
            "KivyforgeServiceContractTest.java",
            keep=set(),
        )
    (app_main / "AndroidManifest.xml").write_text(
        generate_manifest(android, orientation=tuple(config.kivy.orientation)),
        encoding="utf-8",
        newline="\n",
    )

    def _generate_project_files() -> None:
        write_settings_gradle(dest, android)
        write_root_build_gradle(dest, android)
        write_gradle_properties(dest, android)
        stage_gradle_wrapper(dest)
        write_app_build_gradle(
            dest,
            config,
            android,
            python_version=python_version,
            runtime_root=runtime_root,
            staged_libs=staged_libs,
            abis=abis,
            signing_config_block=signing_config_block,
            release_signing_config=release_signing_config,
            test_build_type=test_build_type,
        )
        write_resources(dest, config, android, project_root=project_root)

    _stage(_generate_project_files, ProjectGenError)
    write_gradle_pins(dest, lock)
    _write_local_properties(dest)
    _copy_include_files(project_root, dest, android, lock, verify=not no_verify_lock)
    click.echo(f"[generate] {dest.name}/ regenerated")

    # --- Step 8: assembleDebug (only with --debug) ---
    if debug:
        task = "assembleDebug" if fmt == "apk" else "bundleDebug"
        click.echo(f"[gradle] {task}")
        try:
            run_gradle(dest, [task])
        except GradleError as exc:
            raise AndroidBuildError(str(exc)) from exc
        out = _require_artifact(_debug_output(dest, fmt), task)
        click.echo(f"Built {out}")
    return dest


def _require_artifact(path: Path, task: str) -> Path:
    """Confirm Gradle actually produced the artifact we are about to announce."""
    if not path.is_file():
        raise AndroidBuildError(
            f"Gradle reported success for {task} but no artifact is at {path}.\n"
            "  This usually means AGP's output layout moved under a new plugin "
            "version; check app/build/outputs/ and file a kivyforge issue."
        )
    return path


def android_package(
    project_root: Path,
    *,
    fmt: str = "apk",
    abi: str | None = None,
    keystore: str | None = None,
    key_alias: str | None = None,
    no_verify_lock: bool = False,
    no_cache: bool = False,
) -> Path:
    """Produce the signed release distributable (android/06 §package)."""
    from .policy import ManifestPolicyError, enforce_release_manifest
    from .signing import SigningError, resolve_signing, signing_config_gradle

    config, _lock = _load(project_root, no_verify_lock=no_verify_lock)
    android = config.android_required

    # Signing pre-flight (fail fast, BEFORE staging/generation).
    try:
        signing = resolve_signing(
            android.signing,
            project_root=project_root,
            keystore_override=keystore,
            key_alias_override=key_alias,
        )
    except SigningError as exc:
        raise AndroidBuildError(str(exc)) from exc

    # Stage + generate (steps 1-7), injecting the release signing config.
    signing_block = signing_config_gradle(signing)
    dest = android_build(
        project_root,
        debug=False,
        abi=abi,
        no_verify_lock=no_verify_lock,
        no_cache=no_cache,
        signing_config_block=signing_block,
    )

    # Manifest policy, pass 1: the GENERATED manifest, so an own-goal (placeholder
    # applicationId, a passthrough that forces debuggable) costs no Gradle time.
    manifest_xml = (dest / "app" / "src" / "main" / "AndroidManifest.xml").read_text(
        encoding="utf-8"
    )
    try:
        infos = enforce_release_manifest(
            manifest_xml,
            package=android.package,
            allow_exported=android.manifest.allow_exported,
        )
    except ManifestPolicyError as exc:
        raise AndroidBuildError(str(exc)) from exc
    for info in infos:
        click.echo(f"[policy] INFO: {info.message}")

    # Manifest policy, pass 2: Lint's curated subset plus the same checks over
    # AGP's MERGED manifest — the one that is actually packaged, including what
    # library (.aar/Maven) manifests contribute. Still before signing.
    _enforce_merged_manifest(dest, android)

    task = "assembleRelease" if fmt == "apk" else "bundleRelease"
    click.echo(f"[gradle] {task}")
    try:
        run_gradle(dest, [task])
    except GradleError as exc:
        raise AndroidBuildError(str(exc)) from exc
    out = _require_artifact(_release_output(dest, fmt), task)
    click.echo(f"Packaged {out}")
    return out


def _enforce_merged_manifest(dest: Path, android: AndroidConfig) -> None:
    """Run lintRelease + the merged-manifest policy pass, before signing."""
    from .generate.project import MERGED_MANIFEST_RELPATH, MERGED_MANIFEST_TASK
    from .policy import LINT_CHECKS, ManifestPolicyError, enforce_release_manifest

    click.echo(f"[gradle] lintRelease ({len(LINT_CHECKS)} curated checks)")
    try:
        run_gradle(dest, ["lintRelease", MERGED_MANIFEST_TASK])
    except GradleError as exc:
        raise AndroidBuildError(
            f"{exc}\n"
            "  A lintRelease finding blocks the release (android/06 §package). "
            "The curated subset is "
            f"{', '.join(LINT_CHECKS)}; see the report under "
            "app/build/reports/lint-results-release.html."
        ) from exc

    merged = dest / MERGED_MANIFEST_RELPATH
    if not merged.is_file():
        raise AndroidBuildError(
            f"{MERGED_MANIFEST_TASK} produced no manifest at {merged}; the "
            "release policy cannot check what would actually be packaged."
        )
    click.echo("[policy] merged release manifest")
    try:
        infos = enforce_release_manifest(
            merged.read_text(encoding="utf-8"),
            package=android.package,
            allow_exported=android.manifest.allow_exported,
        )
    except ManifestPolicyError as exc:
        raise AndroidBuildError(str(exc)) from exc
    for info in infos:
        click.echo(f"[policy] INFO (merged): {info.message}")


def _release_output(dest: Path, fmt: str) -> Path:
    outputs = dest / "app" / "build" / "outputs"
    if fmt == "apk":
        return outputs / "apk" / "release" / "app-release.apk"
    return outputs / "bundle" / "release" / "app-release.aab"


def android_run(
    project_root: Path,
    *,
    no_build: bool = False,
    abi: str | None = None,
    serial: str | None = None,
    avd: str | None = None,
    prefer_emulator: bool = False,
    require_physical: bool = False,
    wait_sec: int = 25,
) -> str:
    """Build (unless ``--no-build``), install, launch, echo + return app logcat."""
    from . import adb as adb_mod

    config, _lock = _load(project_root, no_verify_lock=False)
    android = config.android_required

    # The target comes first, even though the build is the long step: it decides
    # which ABI the dev loop needs, and an emulator boots while Gradle works.
    try:
        device = adb_mod.resolve_device(
            prefer_emulator=prefer_emulator,
            require_physical=require_physical,
            serial=serial,
            avd=avd,
        )
    except adb_mod.AdbError as exc:
        raise AndroidBuildError(str(exc)) from exc
    click.echo(f"[run] device {device}")
    if not no_build:
        android_build(
            project_root,
            debug=True,
            fmt="apk",
            abi=abi or _abi_for_device(device, android),
        )
    dest = project_dir_for(project_root, config)
    apk = _debug_output(dest, "apk")
    if not apk.is_file():
        raise AndroidBuildError(f"no debug APK at {apk}; run without --no-build first.")

    try:
        adb_mod.install_apk(device, apk)
        adb_mod.logcat_clear(device)
        adb_mod.launch(device, android.package, "org.kivy.android.PythonActivity")
        click.echo(f"[run] launched {android.package}; capturing logcat...")
        import time as _time

        _time.sleep(wait_sec)
        log = adb_mod.logcat_dump(device)
        for line in log.splitlines():
            if any(tag in line for tag in ("kivyforge", "python.std", "SDL")):
                click.echo(line)
        return log
    except adb_mod.AdbError as exc:
        raise AndroidBuildError(str(exc)) from exc


def _abi_for_device(device: str, android: AndroidConfig) -> str:
    """The ABI to restrict a `run` build to, asked of the target itself.

    android/06 §run documents `--abi`'s default as the target's architecture;
    reading it off the device is the accurate form of that, and lets a locked-ABI
    mismatch fail here with a name rather than later as
    ``INSTALL_FAILED_NO_MATCHING_ABIS``.
    """
    from . import adb as adb_mod

    abi = adb_mod.device_abi(device)
    if abi is None:
        abi = adb_mod.host_abi()
        click.echo(
            f"[run] {device} reports no ABI kivyforge builds for; assuming the "
            f"host's {abi}."
        )
    if abi not in android.abis:
        raise AndroidBuildError(
            f"{device} needs the {abi} ABI, but this project locks "
            f"{', '.join(android.abis)}.\n"
            f"  Add {abi!r} to [tool.kivy.android].abis and re-run "
            "`kivyforge lock -p android`, or target a device/AVD matching a "
            "locked ABI. Installing the wrong ABI fails as "
            "INSTALL_FAILED_NO_MATCHING_ABIS."
        )
    click.echo(f"[run] building for {abi} (the target's ABI)")
    return abi


def android_smoke(
    project_root: Path,
    *,
    release: bool = False,
    abi: str | None = None,
    serial: str | None = None,
    avd: str | None = None,
    prefer_emulator: bool = True,
    require_physical: bool = False,
) -> None:
    """Generate the project for the target variant, ensure a device, run the test."""
    from . import adb as adb_mod
    from .smoke import SmokeError, run_smoke

    config, _lock = _load(project_root, no_verify_lock=False)
    # As in `android_run`: resolve the target first so the probe builds for the
    # ABI it will actually be installed on.
    try:
        device = adb_mod.resolve_device(
            prefer_emulator=prefer_emulator,
            require_physical=require_physical,
            serial=serial,
            avd=avd,
        )
    except adb_mod.AdbError as exc:
        raise AndroidBuildError(str(exc)) from exc
    click.echo(f"[smoke] device {device}; building the probe...")
    abi = abi or _abi_for_device(device, config.android_required)
    # The release probe exists to exercise byte-compilation, stripping and R8,
    # so it must build the *release* variant — which needs both a signing config
    # (AGP refuses to assemble an unsigned release, and the app and test APKs
    # must share a key) and testBuildType, since AGP only generates
    # connectedReleaseAndroidTest when the tests target that variant.
    signing_block, signing_name = (
        _release_smoke_signing(config.android_required, project_root)
        if release
        else ("", None)
    )
    android_build(
        project_root,
        debug=False,
        abi=abi,
        signing_config_block=signing_block,
        release_signing_config=signing_name,
        test_build_type="release" if release else None,
    )
    dest = project_dir_for(project_root, config)

    click.echo(f"[smoke] running the contract test on {device}...")
    try:
        run_smoke(dest, release=release)
    except (adb_mod.AdbError, SmokeError) as exc:
        raise AndroidBuildError(str(exc)) from exc
    click.echo("Contract smoke test PASSED.")


def _release_smoke_signing(
    android: AndroidConfig, project_root: Path
) -> tuple[str, str]:
    """The signing config the release smoke test builds against.

    The project's real release identity when it is configured *and* usable — the
    probe then exercises exactly what ships. Otherwise the debug keystore, which
    Android Studio and the SDK create unattended: a smoke test is a test, and
    requiring release secrets to run it would keep the gate out of reach of the
    hosts that most need it (android/06 §--smoke, "test-instrumentation signing
    config").
    """
    from .signing import SigningError, resolve_signing, signing_config_gradle

    if android.signing.configured:
        try:
            signing = resolve_signing(android.signing, project_root=project_root)
        except SigningError as exc:
            click.echo(
                f"[smoke] release signing is configured but unusable ({exc}); "
                "falling back to the debug keystore for the probe."
            )
        else:
            return signing_config_gradle(signing), "release"
    click.echo("[smoke] signing the release probe with the debug keystore.")
    return "", "debug"


def _copy_include_files(
    project_root: Path,
    dest: Path,
    android: AndroidConfig,
    lock: AndroidLockfile,
    *,
    verify: bool = True,
) -> None:
    """Stage ``include_files`` into the generated project, checking the pins.

    ``kivyforge lock`` records a SHA-256 per staged file
    (``[[tool.kivyforge.include_files]]``) precisely so that content drift is
    detectable, and until now nothing read them back: an edited vendored asset
    shipped silently, with a lock that claimed otherwise. Verification is
    checked-in drift detection, not supply-chain integrity — these are the
    user's own repo files — so the fix is always "re-run lock".
    """
    generated = {
        "app/src/main/AndroidManifest.xml",
        "app/build.gradle",
        "build.gradle",
        "settings.gradle",
        "gradle.properties",
    }
    pins = {(p.dest, p.source): p.sha256 for p in lock.include_files}
    staged: set[tuple[str, str]] = set()
    for entry in android.include_files:
        target_dir = dest / entry.dest
        for source in entry.sources:
            src = project_root / source
            targets = (
                [
                    (
                        child,
                        target_dir / child.relative_to(src),
                        (Path(source) / child.relative_to(src)).as_posix(),
                    )
                    for child in sorted(src.rglob("*"))
                    if child.is_file()
                ]
                if src.is_dir()
                else [(src, target_dir / src.name, source)]
            )
            for file_src, file_dest, rel_source in targets:
                rel = file_dest.relative_to(dest).as_posix()
                if rel in generated:
                    raise AndroidBuildError(
                        f"include_files entry would overwrite the generated "
                        f"{rel}; use the manifest/gradle passthroughs instead "
                        f"(android/01 §include_files)."
                    )
                if verify:
                    _verify_include_file(file_src, rel_source, entry.dest, pins)
                    staged.add((entry.dest, rel_source))
                file_dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(file_src, file_dest)
    if verify:
        # A pin with nothing behind it: a file the lock recorded has since been
        # deleted from a directory source, which the per-file loop cannot see.
        missing = sorted(pins.keys() - staged)
        if missing:
            names = ", ".join(source for _dest, source in missing)
            raise AndroidBuildError(
                f"include_files drift: the lock records {names}, which no longer "
                "exists.\n"
                "  Re-run `kivyforge lock -p android` to re-record what the "
                "project actually ships."
            )


def _verify_include_file(
    file_src: Path, rel_source: str, dest: str, pins: dict[tuple[str, str], str]
) -> None:
    from kivyforge.artifacts.verify import sha256_file

    recorded = pins.get((dest, rel_source))
    if recorded is None:
        raise AndroidBuildError(
            f"include_files drift: {rel_source} would be staged into {dest} but "
            "the lock records no hash for it.\n"
            "  Re-run `kivyforge lock -p android` to record it."
        )
    actual = sha256_file(file_src)
    if actual != recorded:
        raise AndroidBuildError(
            f"include_files drift: {rel_source} has changed since the lock was "
            "written.\n"
            f"  locked:  {recorded}\n"
            f"  on disk: {actual}\n"
            "  Re-run `kivyforge lock -p android` to accept the new content."
        )


def android_status(project_root: Path) -> None:
    """Read-only project snapshot (android/06 §status)."""
    from kivyforge.lock.model import canonical_name
    from kivyforge.lock.reader import LockError, is_in_sync

    config, _ = _load_config_only(project_root)
    android = config.android_required
    click.echo(f"App:        {config.project.name}  ({android.package})")
    click.echo(f"Python:     {android.python_required.version}")

    lock_path = project_root / "pylock.android.toml"
    kivy_ver = "?"
    lock_state = "missing"
    if lock_path.is_file():
        try:
            lock = lock_reader.load(lock_path)
            kivy = next(
                (p for p in lock.packages if canonical_name(p.name) == "kivy"), None
            )
            kivy_ver = kivy.version if kivy else "—"
            lock_state = (
                "in sync"
                if is_in_sync(
                    lock, (project_root / "pyproject.toml").read_text("utf-8")
                )
                else "out of date"
            )
        except LockError:
            lock_state = "unreadable"
    click.echo(
        f"Kivy/SDL:   kivy {kivy_ver}  (kivy_generation {android.kivy_generation})"
    )
    click.echo(f"ABIs:       {', '.join(android.abis)}")
    click.echo(f"Lock:       {lock_state}")

    dest = project_dir_for(project_root, config)
    click.echo("Build:")
    for label, path in (
        ("apk (debug)", _debug_output(dest, "apk")),
        ("apk (release)", _release_output(dest, "apk")),
        ("aab (release)", _release_output(dest, "aab")),
    ):
        if path.is_file():
            import datetime

            mtime = datetime.datetime.fromtimestamp(path.stat().st_mtime)
            click.echo(f"  {label:<16} built {mtime:%Y-%m-%d %H:%M}")
        else:
            click.echo(f"  {label:<16} not built")


def android_open(project_root: Path) -> None:
    """Open the generated project in Android Studio (android/06 §open)."""
    config, _ = _load_config_only(project_root)
    dest = project_dir_for(project_root, config)
    if not dest.is_dir():
        raise AndroidBuildError(
            f"{dest.name}/ does not exist yet; run `kivyforge build -p android` first."
        )
    studio = shutil.which("studio") or shutil.which("studio.sh")
    if studio:
        import subprocess

        subprocess.Popen([studio, str(dest)])
        click.echo(f"Opening {dest.name}/ in Android Studio...")
        return
    click.echo(
        f"Android Studio launcher not found on PATH.\n"
        f"  Open this project manually: {dest}"
    )


def _load_config_only(project_root: Path):
    pyproject = project_root / "pyproject.toml"
    try:
        return (
            load_config(pyproject, require_ios=False, require_android=True),
            pyproject,
        )
    except ConfigError as exc:
        raise AndroidBuildError(exc.format()) from exc


def _write_local_properties(dest: Path) -> None:
    """Point Gradle at the detected SDK when ANDROID_HOME is not exported.

    ``local.properties`` is machine-local by convention and lives inside the
    regenerated (gitignored) project, so writing it here is safe and matches
    what Android Studio itself does. The env var still wins when set.
    """
    import os

    if os.environ.get("ANDROID_HOME") or os.environ.get("ANDROID_SDK_ROOT"):
        return
    from .doctor import RealAndroidProbe

    sdk = RealAndroidProbe().sdk_root()
    if sdk is None:
        return  # gradle will surface the standard actionable error
    escaped = str(sdk).replace("\\", "\\\\").replace(":", "\\:")
    (dest / "local.properties").write_text(
        f"sdk.dir={escaped}\n", encoding="utf-8", newline="\n"
    )


def _debug_output(dest: Path, fmt: str) -> Path:
    if fmt == "apk":
        return dest / "app" / "build" / "outputs" / "apk" / "debug" / "app-debug.apk"
    return dest / "app" / "build" / "outputs" / "bundle" / "debug" / "app-debug.aab"


def _select_abis(android: AndroidConfig, abi: str | None) -> tuple[str, ...]:
    if abi is None:
        return tuple(android.abis)
    if abi not in android.abis:
        raise AndroidBuildError(
            f"--abi {abi!r} is not in [tool.kivy.android].abis "
            f"({', '.join(android.abis)})."
        )
    return (abi,)


def _locked_version(lock: AndroidLockfile, name: str) -> str | None:
    from kivyforge.lock.model import canonical_name

    for package in lock.packages:
        if canonical_name(package.name) == name:
            return package.version
    return None


def _load(project_root: Path, *, no_verify_lock: bool):
    pyproject = project_root / "pyproject.toml"
    try:
        config = load_config(pyproject, require_ios=False, require_android=True)
    except ConfigError as exc:
        raise AndroidBuildError(exc.format()) from exc
    lock_path = project_root / "pylock.android.toml"
    if not lock_path.is_file():
        raise AndroidBuildError(
            "pylock.android.toml not found. Run `kivyforge lock -p android` first."
        )
    try:
        lock = lock_reader.load(lock_path)
    except LockError as exc:
        raise AndroidBuildError(str(exc)) from exc
    if not no_verify_lock and not is_in_sync(
        lock, pyproject.read_text(encoding="utf-8")
    ):
        raise AndroidBuildError(
            "pyproject.toml has changed since pylock.android.toml was "
            "generated.\n  Run: kivyforge lock -p android\n"
            "  Or:  kivyforge build --no-verify-lock   (not recommended)"
        )
    return config, lock


def _stage(fn, error_type):
    try:
        return fn()
    except error_type as exc:
        raise AndroidBuildError(str(exc)) from exc
