"""Gradle/Maven channel resolution for the lock (android/02, channel 4).

``kivyforge lock`` emits the declared coordinates into a **scratch** Gradle
project, runs Gradle with dependency verification metadata generation
(``--write-verification-metadata sha256``) against a task that force-resolves
the runtime classpath, and parses the resulting
``gradle/verification-metadata.xml`` into ``[[tool.kivyforge.gradle.resolved]]``
pins. The values live **in the lock**; ``kivyforge build`` later materializes
``app/gradle.lockfile`` + ``gradle/verification-metadata.xml`` into the
generated project from these pins (android/02 §gradle pins).

The Gradle invocation is behind the ``GradleMavenResolver`` protocol so unit
tests inject a fake and stay hermetic; the metadata parser is pure and tested
against recorded XML. A JDK is required only when Maven dependencies are
actually declared (android/06 §lock).
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Protocol

from kivyforge.config.model import AndroidGradleConfig

from .model import GradleArtifact, GradlePins, GradleResolvedModule

_VERIFICATION_NS = "{https://schema.gradle.org/dependency-verification}"


class MavenResolverError(Exception):
    pass


class GradleMavenResolver(Protocol):
    def resolve(
        self, gradle: AndroidGradleConfig, *, offline: bool = False
    ) -> tuple[GradleResolvedModule, ...]: ...


def resolve_gradle_pins(
    gradle: AndroidGradleConfig,
    *,
    resolver: GradleMavenResolver | None = None,
    offline: bool = False,
) -> GradlePins:
    """Resolve the declared coordinates into hash-pinned modules.

    Skipped entirely (empty pins) when no dependencies are declared — the
    common Kivy case never needs a JDK at lock time.
    """
    if not gradle.dependencies:
        return GradlePins()
    backend = resolver or ScratchProjectResolver()
    resolved = backend.resolve(gradle, offline=offline)
    return GradlePins(
        dependencies=tuple(gradle.dependencies),
        repositories=tuple(gradle.repositories),
        resolved=resolved,
    )


def parse_verification_metadata(xml_text: str) -> tuple[GradleResolvedModule, ...]:
    """Parse Gradle's ``verification-metadata.xml`` into resolved-module pins.

    The document shape (Gradle dependency-verification schema):
    ``<verification-metadata><components><component group= name= version=>
    <artifact name=...><sha256 value=.../></artifact>...`` — one component per
    resolved module, one artifact per downloaded file.
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise MavenResolverError(
            f"could not parse Gradle verification-metadata.xml: {exc}"
        ) from exc
    modules: list[GradleResolvedModule] = []
    for component in root.iter(f"{_VERIFICATION_NS}component"):
        group = component.get("group", "")
        name = component.get("name", "")
        version = component.get("version", "")
        artifacts: list[GradleArtifact] = []
        for artifact in component.findall(f"{_VERIFICATION_NS}artifact"):
            sha = artifact.find(f"{_VERIFICATION_NS}sha256")
            value = sha.get("value", "") if sha is not None else ""
            if value:
                artifacts.append(
                    GradleArtifact(name=artifact.get("name", ""), sha256=value)
                )
        modules.append(
            GradleResolvedModule(
                coordinate=f"{group}:{name}:{version}",
                artifacts=tuple(sorted(artifacts, key=lambda a: a.name)),
            )
        )
    modules.sort(key=lambda m: m.coordinate)
    return tuple(modules)


# --------------------------------------------------------------------------- #
# Default backend: a scratch Gradle project.
# --------------------------------------------------------------------------- #

_SETTINGS_GRADLE = """\
dependencyResolutionManagement {
    repositories {
        google()
        mavenCentral()
%(extra_repos)s
    }
}
rootProject.name = "kivyforge-maven-lock"
"""

# A plain JVM project with an Android-attribute-tolerant configuration: the
# lenient artifact view lets .aar-packaged AndroidX modules resolve without
# AGP, since the lock only needs the *graph + bytes*, not a compiled classpath.
_BUILD_GRADLE = """\
plugins { id 'java-library' }

configurations {
    kivyforgeLock {
        canBeConsumed = false
        canBeResolved = true
        attributes {
            attribute(Attribute.of('artifactType', String), 'jar')
        }
    }
}

dependencies {
%(dependencies)s
}

// Force full artifact download so verification metadata covers every file.
tasks.register('kivyforgeResolveAll') {
    doLast {
        def seen = configurations.kivyforgeLock.incoming.artifactView {
            lenient = true
        }.files.files
        println "kivyforge: resolved ${seen.size()} artifact files"
    }
}
"""


class ScratchProjectResolver:
    """Run Gradle in a temp project and harvest verification metadata.

    Uses a standalone ``gradle`` if one is on PATH; otherwise stages kivyforge's
    vendored Gradle wrapper into the scratch project and runs it (the same
    wrapper `build` uses), so a project only needs a JDK — not a separate Gradle
    install — for the Maven lock.
    """

    _WRAPPER_DIR = Path(__file__).parent.parent / "gradle_wrapper"

    def __init__(self, gradle_executable: str | None = None) -> None:
        self._gradle = gradle_executable

    def resolve(
        self, gradle: AndroidGradleConfig, *, offline: bool = False
    ) -> tuple[GradleResolvedModule, ...]:
        with tempfile.TemporaryDirectory(prefix="kivyforge-maven-") as tmp:
            root = Path(tmp)
            extra = "\n".join(
                f"        maven {{ url = uri({_groovy_str(u)}) }}"
                for u in gradle.repositories
            )
            deps = "\n".join(
                f"    kivyforgeLock {_groovy_str(c)}" for c in gradle.dependencies
            )
            (root / "settings.gradle").write_text(
                _SETTINGS_GRADLE % {"extra_repos": extra}, encoding="utf-8"
            )
            (root / "build.gradle").write_text(
                _BUILD_GRADLE % {"dependencies": deps}, encoding="utf-8"
            )
            exe = self._gradle_command(root)
            cmd = [
                *exe,
                "--no-daemon",
                "--console=plain",
                "--write-verification-metadata",
                "sha256",
                "kivyforgeResolveAll",
            ]
            if offline:
                cmd.append("--offline")
            proc = subprocess.run(
                cmd, cwd=root, capture_output=True, text=True
            )
            if proc.returncode != 0:
                raise MavenResolverError(
                    "Gradle could not resolve the declared Maven coordinates.\n"
                    f"  Gradle said:\n{_indent(proc.stderr or proc.stdout)}"
                )
            metadata = root / "gradle" / "verification-metadata.xml"
            if not metadata.is_file():
                raise MavenResolverError(
                    "Gradle wrote no verification-metadata.xml; cannot pin the "
                    "resolved Maven graph."
                )
            return parse_verification_metadata(
                metadata.read_text(encoding="utf-8")
            )

    def _gradle_command(self, root: Path) -> list[str]:
        """A standalone gradle if present, else the vendored wrapper in ``root``."""
        if self._gradle:
            return [self._gradle]
        standalone = shutil.which("gradle")
        if standalone:
            return [standalone]
        jar = self._WRAPPER_DIR / "gradle-wrapper.jar"
        if not jar.is_file():
            raise MavenResolverError(
                "[tool.kivy.android.gradle].dependencies is declared, but "
                "neither a standalone `gradle` nor the vendored wrapper is "
                "available (a JDK is still required for this channel; "
                "android/06 §lock)."
            )
        import os as _os

        wrapper = root / "gradle" / "wrapper"
        wrapper.mkdir(parents=True, exist_ok=True)
        shutil.copy2(jar, wrapper / "gradle-wrapper.jar")
        (wrapper / "gradle-wrapper.properties").write_text(
            "distributionBase=GRADLE_USER_HOME\n"
            "distributionPath=wrapper/dists\n"
            "distributionUrl=https\\://services.gradle.org/distributions/"
            "gradle-8.11.1-bin.zip\n"
            "zipStoreBase=GRADLE_USER_HOME\n"
            "zipStorePath=wrapper/dists\n",
            encoding="utf-8",
        )
        for script in ("gradlew", "gradlew.bat"):
            src = self._WRAPPER_DIR / script
            if src.is_file():
                dst = root / script
                shutil.copy2(src, dst)
                if script == "gradlew":
                    dst.chmod(dst.stat().st_mode | 0o111)
        return [str(root / ("gradlew.bat" if _os.name == "nt" else "gradlew"))]


def _groovy_str(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("'", "\\'")
    return f"'{escaped}'"


def _indent(text: str) -> str:
    return "\n".join(f"    {line}" for line in (text or "").splitlines())
