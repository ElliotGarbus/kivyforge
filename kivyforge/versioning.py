"""Resolve the version a build uses (docs/design/dev/dynamic-version-proposal.md).

In order: ``--app-version`` or ``KIVYFORGE_APP_VERSION`` (the flag wins), then a
static ``[project].version``, then -- for ``"version"`` in ``[project].dynamic``
-- the project's own build backend, run by pip:

    pip install --dry-run --ignore-installed --no-deps --report - <project>

pip, not a hook library called in kivyforge's interpreter, because under
``uv tool``, pipx or ``uv run`` that interpreter does not have the backend; pip
installs ``[build-system].requires`` into an isolated build environment and runs
it there, for any backend. Isolation is the default and only an explicit
``--no-build-isolation`` turns it off: chosen automatically, it reports a silent
``0.0.0`` for a project that gets setuptools-scm through ``setup_requires``.

Only the verbs that build an artifact resolve (``build``, ``package``, ``run``),
once per invocation. Nothing here prints: callers report what it returns.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from collections.abc import Callable, Mapping
from pathlib import Path

from .config.model import DeclaredVersion, DynamicVersion, ResolvedVersion
from .config.version import normalized
from .report import diagnostics
from .report.diagnostics import Diagnostic
from .report.failures import ClassifiedError, spawn_failure

#: The environment's spelling of ``--app-version``.
ENV_OVERRIDE = "KIVYFORGE_APP_VERSION"
FLAG_OVERRIDE = "--app-version"

#: How many lines of pip's stderr a failure quotes, at most.
_STDERR_TAIL = 15

#: The lines of pip's stderr that say what went wrong: pip's own ``ERROR:``
#: lines and the exception a backend raised (``LookupError: setuptools-scm was
#: unable to detect version ...``, ``BackendUnavailable: Cannot import ...``).
#: The traceback around them is noise to anyone reading the failure.
_PIP_SIGNAL = re.compile(
    r"^(ERROR: (?!Exception:$)|[\w.]*(Error|Exception|Unavailable): )"
)

#: What App Store Connect accepts at upload (ITMS-90060): one to three
#: dot-separated integers. Apple's documentation says "three", but enforcing
#: that would reject every ``1.0``.
_APPLE_VERSION = re.compile(r"[0-9]+(\.[0-9]+){0,2}")

Runner = Callable[..., "subprocess.CompletedProcess[str]"]

#: The process runner, a seam for tests that drive the verbs end to end.
_run: Runner = subprocess.run


class VersionUnresolved(ClassifiedError):
    """pip could not report the version the build backend computes."""

    code = diagnostics.VERSION_UNRESOLVED


class AppleVersionRejected(ClassifiedError):
    """An App Store export whose version App Store Connect would refuse."""

    code = diagnostics.VERSION_APPLE_FORMAT


def override(flag: str | None, env: Mapping[str, str]) -> tuple[str, str] | None:
    """``(value, where it came from)`` for an override, the flag first."""
    if flag:
        return flag, FLAG_OVERRIDE
    value = env.get(ENV_OVERRIDE, "").strip()
    if value:
        return value, ENV_OVERRIDE
    return None


def resolve_version(
    declared: DeclaredVersion,
    project_root: Path,
    *,
    flag: str | None,
    env: Mapping[str, str],
    isolated: bool = True,
    runner: Runner | None = None,
) -> ResolvedVersion:
    """The version this invocation builds with.

    Raises ``ConfigError`` for an override that is not PEP 440 (naming the flag
    or the variable, which have no file line) and :class:`VersionUnresolved`
    when pip cannot produce a version. The declaration has already been
    validated by the loader: an override replaces the value, not that check.
    """
    given = override(flag, env)
    if given is not None:
        value, origin = given
        return ResolvedVersion(normalized(value, what=origin), source="override")
    if not isinstance(declared, DynamicVersion):
        return ResolvedVersion(declared.value, source="static")
    value = _from_backend(
        project_root, declared, isolated=isolated, runner=runner or _run
    )
    return ResolvedVersion(value, source="backend")


def pip_command(project_root: Path, *, isolated: bool) -> list[str]:
    cmd = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--dry-run",
        # Under `uv run` the project is usually installed, often editable and
        # often stale, in this very interpreter; the tree is what is built.
        "--ignore-installed",
        "--no-deps",
        "--quiet",
        "--disable-pip-version-check",
        "--report",
        "-",
    ]
    if not isolated:
        cmd.append("--no-build-isolation")
    cmd.append(str(project_root))
    return cmd


def _from_backend(
    project_root: Path, declared: DynamicVersion, *, isolated: bool, runner: Runner
) -> str:
    context = {"backend": declared.backend, "isolated": "true" if isolated else "false"}
    if isolated:
        fix = (
            "  Fix: check the project builds (`pip wheel --no-deps .`): a "
            "setuptools-scm project needs a git checkout with tags (in CI, "
            "fetch-depth: 0), and pip needs to reach the package index to fetch "
            f"the build backend. Or pass {FLAG_OVERRIDE} to skip the backend."
        )
    else:
        fix = (
            "  Fix: with --no-build-isolation the build backend must be installed "
            "alongside kivyforge (for example `uv tool install kivyforge --with "
            "setuptools-scm`); or drop --no-build-isolation, or pass "
            f"{FLAG_OVERRIDE}."
        )
    try:
        # The child inherits this environment on purpose: PIP_INDEX_URL and
        # SETUPTOOLS_SCM_PRETEND_VERSION only work because it does.
        proc = runner(
            pip_command(project_root, isolated=isolated),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        raise VersionUnresolved(
            f"could not run pip to resolve the dynamic version: {exc}",
            **spawn_failure("pip", exc),
        ) from exc
    if proc.returncode != 0:
        tail = "\n".join("    " + line for line in pip_failure_summary(proc.stderr))
        raise VersionUnresolved(
            f"could not resolve the dynamic [project].version: pip exited with "
            f"status {proc.returncode} preparing the metadata "
            f"({declared.backend}).\n{tail}\n{fix}",
            context=context,
        )
    try:
        report = json.loads(proc.stdout)
        version = report["install"][0]["metadata"]["version"]
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise VersionUnresolved(
            "could not resolve the dynamic [project].version: pip's report has "
            f"no version ({declared.backend}).\n{fix}",
            context=context,
        ) from exc
    if not isinstance(version, str) or not version:
        raise VersionUnresolved(
            "could not resolve the dynamic [project].version: pip's report has "
            f"no version ({declared.backend}).\n{fix}",
            context=context,
        )
    return normalized(version, what=f"the version {declared.backend} reported")


def pip_failure_summary(stderr: str | None) -> list[str]:
    """The lines of a failed pip run worth showing; its tail if none stand out."""
    lines = [line.strip() for line in (stderr or "").splitlines() if line.strip()]
    signal = [line for line in lines if _PIP_SIGNAL.match(line)]
    return (signal or lines)[-_STDERR_TAIL:]


def announcement(
    version: ResolvedVersion, declared: DeclaredVersion, *, flag: str | None
) -> str | None:
    """The stderr line naming a version the user did not type, if any.

    A static version is in ``pyproject.toml`` for anyone to read, so it is not
    announced: that keeps every existing project's output unchanged.
    """
    if version.source == "backend":
        backend = declared.backend if isinstance(declared, DynamicVersion) else "?"
        return f"Version {version.value} (from {backend}, via pip)"
    if version.source == "override":
        origin = FLAG_OVERRIDE if flag else ENV_OVERRIDE
        return f"Version {version.value} (from {origin})"
    return None


def apple_conforms(value: str) -> bool:
    return _APPLE_VERSION.fullmatch(value) is not None


def check_apple_version(
    version: ResolvedVersion,
    *,
    platform: str,
    exports: bool,
    export_method: str | None,
) -> Diagnostic | None:
    """The App Store Connect check (ITMS-90060) for where this build goes.

    *exports* is true when the build produces a distributable: an iOS archive
    and export (``build --release``, ``package``) or a macOS ``package``.
    Debug builds say nothing, since nothing local rejects the value. Raises
    :class:`AppleVersionRejected` for an iOS ``app-store`` export, where upload
    is certain to fail; returns a warning for other exports.
    """
    if platform not in ("ios", "macos") or not exports or apple_conforms(version.value):
        return None
    context = {"version": version.value, "export_method": export_method or ""}
    if platform == "ios" and export_method == "app-store":
        raise AppleVersionRejected(
            f"version {version.value!r} cannot be uploaded to App Store Connect, "
            "which accepts one to three dot-separated integers in "
            "CFBundleShortVersionString and rejects anything else (ITMS-90060).\n"
            f"  Fix: build from a release tag, pass {FLAG_OVERRIDE} 1.2.3, or "
            "export with --export-method ad-hoc or development.",
            context=context,
        )
    return Diagnostic(
        code=diagnostics.VERSION_APPLE_FORMAT,
        severity=diagnostics.WARNING,
        message=f"version {version.value!r} is written to CFBundleShortVersionString "
        "as is; App Store Connect will refuse it (ITMS-90060), since it accepts "
        "one to three dot-separated integers.",
        context=context,
    )


def check_version_file(
    version: ResolvedVersion, scm_version_file: str | None
) -> Diagnostic | None:
    """Warn when a setuptools-scm ``version_file`` was not rewritten."""
    path = scm_version_file
    if path is None or version.source == "backend":
        return None
    return Diagnostic(
        code=diagnostics.VERSION_FILE_NOT_REFRESHED,
        severity=diagnostics.WARNING,
        message=f"{path} was not rewritten: the version came from "
        f"{'an override' if version.source == 'override' else 'pyproject.toml'}, "
        "so the build backend did not run, and an app reading that file may "
        "report another version.",
        remediation="to pin a version and refresh the file, set "
        "SETUPTOOLS_SCM_PRETEND_VERSION instead of --app-version.",
        context={"path": path},
    )
