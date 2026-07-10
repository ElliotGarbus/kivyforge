"""Notarize + staple the signed ``.app`` (macos-spec, Developer ID workstream).

The distribution path since macOS 10.15 is **sign + notarize + staple**: zip the
Developer-ID-signed ``.app`` (``ditto -c -k --keepParent`` preserves the bundle
metadata Gatekeeper checks), submit it with ``xcrun notarytool submit --wait``,
and on acceptance ``xcrun stapler staple`` the ticket into the bundle so
Gatekeeper trusts it offline.

Credentials come from a **keychain profile** created once with::

    xcrun notarytool store-credentials <profile> \
        --apple-id <you@example.com> --team-id <TEAMID> --password <app-specific>

so nothing secret ever lives in ``pyproject.toml`` (CI keychains work the same
way). ``.dmg``-level notarization stays external — kivyforge never builds
``.dmg`` files (see common packaging scope).
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

import click

from . import AppBundleError


def notarize_and_staple(app: Path, *, profile: str, echo=click.echo) -> None:
    """Submit *app* to Apple's notary service and staple the ticket.

    Blocks until the notary service responds (``--wait``; typically a couple of
    minutes). On rejection, fetches the notary log and surfaces the per-file
    issues in the error message.
    """
    with tempfile.TemporaryDirectory(prefix="kivyforge-notarize-") as tmp:
        archive = Path(tmp) / f"{app.stem}.zip"
        echo(f"Zipping {app.name} for notarization ...")
        _run(["ditto", "-c", "-k", "--keepParent", str(app), str(archive)])

        echo("Submitting to the Apple notary service (this can take minutes) ...")
        proc = _run(
            [
                "xcrun",
                "notarytool",
                "submit",
                str(archive),
                "--keychain-profile",
                profile,
                "--wait",
                "--output-format",
                "json",
            ],
            check=False,
        )
        submission_id, status = _parse_submission(proc.stdout)
        if proc.returncode != 0 and status is None:
            raise AppBundleError(
                f"notarytool submit failed ({proc.returncode}): "
                f"{(proc.stderr or proc.stdout).strip()}\n"
                f"  Check the keychain profile: `xcrun notarytool history "
                f"--keychain-profile {profile}`."
            )
        if status != "Accepted":
            raise AppBundleError(_rejection_message(submission_id, status, profile))
        echo(f"Notarization accepted (submission {submission_id}).")

    echo("Stapling the notarization ticket ...")
    _run(["xcrun", "stapler", "staple", str(app)])


def _parse_submission(stdout: str) -> tuple[str | None, str | None]:
    """(submission id, status) from ``notarytool --output-format json`` output."""
    try:
        data = json.loads(stdout or "{}")
    except json.JSONDecodeError:
        return None, None
    return data.get("id"), data.get("status")


def _rejection_message(
    submission_id: str | None, status: str | None, profile: str
) -> str:
    lines = [f"notarization was not accepted (status: {status or 'unknown'})."]
    if submission_id:
        log = _notary_log(submission_id, profile)
        if log:
            lines.append(f"  Notary log issues:\n{log}")
        else:
            lines.append(
                f"  Fetch the log: `xcrun notarytool log {submission_id} "
                f"--keychain-profile {profile}`."
            )
    lines.append(
        "  Common causes: a binary missed Hardened Runtime / timestamp signing, "
        "or the identity is not a Developer ID Application certificate."
    )
    return "\n".join(lines)


def _notary_log(submission_id: str, profile: str) -> str:
    """The notary log's per-file issues, indented; empty string on any failure."""
    proc = _run(
        [
            "xcrun",
            "notarytool",
            "log",
            submission_id,
            "--keychain-profile",
            profile,
        ],
        check=False,
    )
    if proc.returncode != 0:
        return ""
    try:
        issues = json.loads(proc.stdout).get("issues") or []
    except json.JSONDecodeError:
        return ""
    lines = [
        f"    {issue.get('severity', '?')}: {issue.get('path', '?')}: "
        f"{issue.get('message', '?')}"
        for issue in issues
    ]
    return "\n".join(lines)


def _run(cmd: list[str], *, check: bool = True) -> subprocess.CompletedProcess:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise AppBundleError(
            f"required macOS tool {cmd[0]!r} not found.\n"
            "  Install the Xcode command-line tools: xcode-select --install"
        ) from exc
    if check and proc.returncode != 0:
        raise AppBundleError(
            f"{cmd[0]} failed ({proc.returncode}): "
            f"{(proc.stderr or proc.stdout).strip()}"
        )
    return proc
