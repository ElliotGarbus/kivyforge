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
    check_sdl_glue_contract,
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
    android_abi,
    stage_gradle_wrapper,
    write_app_build_gradle,
    write_gradle_pins,
    write_gradle_properties,
    write_resources,
    write_root_build_gradle,
    write_settings_gradle,
)
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


def android_build(
    project_root: Path,
    *,
    debug: bool = False,
    fmt: str = "apk",
    abi: str | None = None,
    no_verify_lock: bool = False,
    no_cache: bool = False,
    signing_config_block: str = "",
) -> Path:
    """Steps 1-7 (+8 with ``debug``); returns the generated project dir."""
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
    stamp = _stage(
        lambda: assemble_bundle(
            app_main / "assets" / BUNDLE_DIRNAME,
            stdlib_src=stdlib_dir(prefixes[canonical], stem),
            site_packages_by_abi={a: site_packages[a] for a in abis},
            canonical_abi=canonical,
            app_src=project_root / config.kivy.app_dir,
            finder_source=finder_source(),
            kivy_bootstrap_source=kivy_bootstrap_source(),
            ext_manifest_json=ext_manifest_json,
            selftest_source=selftest_source(),
        ),
        BundleError,
    )
    click.echo(f"[stage] asset bundle assembled (stamp {stamp})")

    # --- Step 7: (re)generate the Gradle project ---
    sdl_activity_java = ""
    for rendered in render_bootstrap(sdl=android.sdl, python_version=python_version):
        out = app_main / rendered.relpath
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(rendered.content, encoding="utf-8", newline="\n")
        if rendered.relpath.endswith("org/libsdl/app/SDLActivity.java"):
            sdl_activity_java = rendered.content

    # The SDL glue and the wheel's libSDL2.so are a matched pair: SDLActivity
    # aborts onCreate silently when they disagree, so catch it here rather than
    # as an unexplained black screen on-device.
    for abi_name in abis:
        so = app_main / "jniLibs" / android_abi(abi_name) / "libSDL2.so"
        if not sdl_activity_java or not so.is_file():
            continue
        try:
            check_sdl_glue_contract(java_source=sdl_activity_java, so_path=so)
        except ContractError as exc:
            raise AndroidBuildError(str(exc)) from exc
    for rendered in androidtest_files():
        out = dest / "app" / "src" / rendered.relpath
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(rendered.content, encoding="utf-8", newline="\n")
    (app_main / "AndroidManifest.xml").write_text(
        generate_manifest(android, orientation=tuple(config.kivy.orientation)),
        encoding="utf-8",
        newline="\n",
    )
    write_settings_gradle(dest)
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
    )
    write_resources(dest, config, android)
    write_gradle_pins(dest, lock)
    _write_local_properties(dest)
    _copy_include_files(project_root, dest, android)
    click.echo(f"[generate] {dest.name}/ regenerated")

    # --- Step 8: assembleDebug (only with --debug) ---
    if debug:
        task = "assembleDebug" if fmt == "apk" else "bundleDebug"
        click.echo(f"[gradle] {task}")
        try:
            run_gradle(dest, [task])
        except GradleError as exc:
            raise AndroidBuildError(str(exc)) from exc
        out = _debug_output(dest, fmt)
        click.echo(f"Built {out}")
    return dest


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

    # Manifest policy pre-flight on the GENERATED manifest (fail before Gradle).
    manifest_xml = (
        dest / "app" / "src" / "main" / "AndroidManifest.xml"
    ).read_text(encoding="utf-8")
    try:
        infos = enforce_release_manifest(manifest_xml, package=android.package)
    except ManifestPolicyError as exc:
        raise AndroidBuildError(str(exc)) from exc
    for info in infos:
        click.echo(f"[policy] INFO: {info.message}")

    task = "assembleRelease" if fmt == "apk" else "bundleRelease"
    click.echo(f"[gradle] {task}")
    try:
        run_gradle(dest, [task])
    except GradleError as exc:
        raise AndroidBuildError(str(exc)) from exc
    out = _release_output(dest, fmt)
    click.echo(f"Packaged {out}")
    return out


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
    wait_sec: int = 25,
) -> str:
    """Build (unless ``--no-build``), install, launch, echo + return app logcat."""
    from . import adb as adb_mod

    config, _lock = _load(project_root, no_verify_lock=False)
    android = config.android_required

    if not no_build:
        android_build(project_root, debug=True, fmt="apk", abi=abi)
    dest = project_dir_for(project_root, config)
    apk = _debug_output(dest, "apk")
    if not apk.is_file():
        raise AndroidBuildError(
            f"no debug APK at {apk}; run without --no-build first."
        )

    try:
        device = adb_mod.resolve_device(
            prefer_emulator=prefer_emulator, serial=serial, avd=avd
        )
        click.echo(f"[run] device {device}")
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


def android_smoke(
    project_root: Path,
    *,
    release: bool = False,
    abi: str | None = None,
    serial: str | None = None,
    avd: str | None = None,
    prefer_emulator: bool = True,
) -> None:
    """Build the debug variant, ensure a device, run the contract smoke test."""
    from . import adb as adb_mod
    from .smoke import SmokeError, run_smoke

    config, _lock = _load(project_root, no_verify_lock=False)
    android_build(project_root, debug=False, abi=abi)
    dest = project_dir_for(project_root, config)

    try:
        device = adb_mod.resolve_device(
            prefer_emulator=prefer_emulator, serial=serial, avd=avd
        )
        click.echo(f"[smoke] device {device}; running the contract test...")
        run_smoke(dest, release=release)
    except (adb_mod.AdbError, SmokeError) as exc:
        raise AndroidBuildError(str(exc)) from exc
    click.echo("Contract smoke test PASSED.")


def _copy_include_files(
    project_root: Path, dest: Path, android: AndroidConfig
) -> None:
    generated = {
        "app/src/main/AndroidManifest.xml",
        "app/build.gradle",
        "build.gradle",
        "settings.gradle",
        "gradle.properties",
    }
    for entry in android.include_files:
        target_dir = dest / entry.dest
        for source in entry.sources:
            src = project_root / source
            targets = (
                [(child, target_dir / child.relative_to(src))
                 for child in src.rglob("*") if child.is_file()]
                if src.is_dir()
                else [(src, target_dir / src.name)]
            )
            for file_src, file_dest in targets:
                rel = file_dest.relative_to(dest).as_posix()
                if rel in generated:
                    raise AndroidBuildError(
                        f"include_files entry would overwrite the generated "
                        f"{rel}; use the manifest/gradle passthroughs instead "
                        f"(android/01 §include_files)."
                    )
                file_dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(file_src, file_dest)


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
    click.echo(f"Kivy/SDL:   kivy {kivy_ver}  (sdl {android.sdl})")
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
            f"{dest.name}/ does not exist yet; run `kivyforge build -p android` "
            "first."
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
