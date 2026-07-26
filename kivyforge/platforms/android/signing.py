"""Release signing preflight + Gradle signingConfig values (android/06, 07).

Android signing is **mandatory** and kivyforge owns it via Gradle's signing
config. The preflight resolves the effective keystore/alias (overlay or CLI
override), confirms the passwords are present in the configured env vars, and
verifies the alias exists — failing fast **before** Gradle, with the android/06
remediation text. Passwords are read by Gradle at build time from the env;
kivyforge never writes them to disk.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from kivyforge.config.model import AndroidSigningConfig


class SigningError(Exception):
    pass


@dataclass(frozen=True)
class ResolvedSigning:
    """The effective, verified signing identity for a release build."""

    keystore: Path
    key_alias: str
    store_password_env: str
    key_password_env: str
    v1_signing: bool
    v2_signing: bool
    v3_signing: bool
    v4_signing: bool


def resolve_signing(
    config: AndroidSigningConfig,
    *,
    project_root: Path,
    keystore_override: str | None = None,
    key_alias_override: str | None = None,
) -> ResolvedSigning:
    """Resolve + verify the signing identity; raise ``SigningError`` if unusable."""
    keystore = keystore_override or config.keystore
    key_alias = key_alias_override or config.key_alias
    if not keystore or not key_alias:
        raise SigningError(
            "code signing required to package a release, but no keystore is "
            "resolved.\n"
            "  Set it one of these ways:\n"
            "    • [tool.kivy.android.signing] keystore/key_alias in "
            "pyproject.toml, then re-lock\n"
            "    • kivyforge package --keystore release.keystore "
            "--key-alias upload\n"
            "  And export the passwords:\n"
            "    • export KIVYFORGE_KEYSTORE_PASSWORD=...   "
            "(and KIVYFORGE_KEY_PASSWORD if different)"
        )

    keystore_path = Path(keystore)
    if not keystore_path.is_absolute():
        keystore_path = (project_root / keystore_path).resolve()
    if not keystore_path.is_file():
        raise SigningError(
            f"signing keystore not found: {keystore_path}\n"
            "  Provide a valid keystore path (repo-relative or absolute)."
        )

    store_pw = os.environ.get(config.store_password_env)
    if not store_pw:
        raise SigningError(
            f"the keystore password env var ${config.store_password_env} is not "
            "set.\n  export "
            f"{config.store_password_env}=... before packaging a release."
        )
    # The key password is optional: if its env var is unset, Gradle's signing
    # config falls back to the store password (keytool convention, android/01).

    _verify_alias(keystore_path, key_alias, store_pw)

    return ResolvedSigning(
        keystore=keystore_path,
        key_alias=key_alias,
        store_password_env=config.store_password_env,
        key_password_env=config.key_password_env,
        v1_signing=config.v1_signing,
        v2_signing=config.v2_signing,
        v3_signing=config.v3_signing,
        v4_signing=config.v4_signing,
    )


def _verify_alias(keystore: Path, alias: str, store_password: str) -> None:
    keytool = shutil.which("keytool")
    if keytool is None:
        # Non-fatal: a JDK is a doctor prerequisite; Gradle will surface a
        # clear error if the alias is truly wrong. Don't block on tool absence.
        return
    proc = subprocess.run(
        [
            keytool,
            "-list",
            "-keystore",
            str(keystore),
            "-alias",
            alias,
            "-storepass",
            store_password,
        ],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise SigningError(
            f"key alias {alias!r} not found in {keystore.name} (or the keystore "
            "password is wrong).\n"
            f"  keytool said:\n    {(proc.stderr or proc.stdout).strip()}"
        )


def signing_config_gradle(signing: ResolvedSigning) -> str:
    """The ``signingConfigs { release { … } }`` block for app/build.gradle.

    Reads passwords from the env at Gradle time via ``System.getenv`` — never
    written to disk. The v1–v4 scheme toggles apply to ``.apk`` outputs.
    """
    keystore = str(signing.keystore).replace("\\", "/")
    return f"""\
    signingConfigs {{
        release {{
            storeFile file('{keystore}')
            storePassword System.getenv('{signing.store_password_env}')
            keyAlias '{signing.key_alias}'
            keyPassword System.getenv('{signing.key_password_env}') \
?: System.getenv('{signing.store_password_env}')
            enableV1Signing {str(signing.v1_signing).lower()}
            enableV2Signing {str(signing.v2_signing).lower()}
            enableV3Signing {str(signing.v3_signing).lower()}
            enableV4Signing {str(signing.v4_signing).lower()}
        }}
    }}"""
