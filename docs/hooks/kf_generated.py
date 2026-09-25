"""MkDocs hook: inject facts derived from kivyforge's own code.

Markers in a page are replaced during ``on_page_markdown``, so the published
tables can never drift from the tool that produced them:

    <!-- kf:host-matrix -->        which host builds which target
    <!-- kf:exit-codes -->         the reserved exit-code taxonomy
    <!-- kf:diagnostic-codes -->   the published ``KF-*`` vocabulary

The host matrix and the two code vocabularies come straight from
``kivyforge.capabilities`` and ``kivyforge.report`` -- the same sources
``kivyforge capabilities`` publishes. The "typical reaction" / "remediation"
columns are the one hand-written part, and they are validated here against the
live vocabulary, so a newly added code fails ``mkdocs build --strict`` instead
of shipping undocumented.
"""

from __future__ import annotations

import re
from pathlib import Path

from kivyforge.capabilities import HOSTS, collect, host_label

HOST_MATRIX = "<!-- kf:host-matrix -->"
EXIT_CODES = "<!-- kf:exit-codes -->"
DIAGNOSTIC_CODES = "<!-- kf:diagnostic-codes -->"
CHANGELOG = "<!-- kf:changelog -->"
FAQ = "<!-- kf:faq -->"

# Repo root, so root-level docs (CHANGELOG.md, FAQ.md) can be inlined.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_REPO = "https://github.com/ElliotGarbus/kivyforge"
# Markdown-link matcher: capture the target of ``](target)``.
_LINK = re.compile(r"\]\(([^)]+)\)")

# Hand-written "typical reaction" per reserved exit code, keyed by number.
_EXIT_REACTION = {
    0: "Continue.",
    1: "Fix `pyproject.toml` and retry.",
    2: "Fix the command line. This is click's usage error; kivyforge never raises it deliberately.",
    3: "Install the missing tool, then retry the same command.",
    4: "Re-lock with `kivyforge lock -p <platform>`.",
    5: "Read the build log on stderr; the toolchain ran and reported an error.",
}

# Hand-written meaning + remediation per KF-* code. Validated below against the
# live vocabulary: if these keys and the published codes ever differ, the hook
# raises and the strict build fails.
_DIAGNOSTIC = {
    "KF-LOCK-DRIFT": (
        "error",
        "The committed lock no longer matches `pyproject.toml`.",
        "Run `kivyforge lock -p <platform>`.",
    ),
    "KF-LOCK-MISSING": (
        "error",
        "No `pylock.<platform>.toml` exists for the target.",
        "Run `kivyforge lock -p <platform>`.",
    ),
    "KF-LOCK-UNREADABLE": (
        "error",
        "A lock exists but could not be parsed (a bad merge or a truncated write).",
        "Re-create it with `kivyforge lock -p <platform>`.",
    ),
    "KF-LOCK-WARNING": (
        "warning",
        "Resolution made a judgement call worth surfacing. The lock is usable and the run is `ok`.",
        "Read the note; no action is required unless it surprises you.",
    ),
    "KF-BYTECOMPILE-NO-INTERP": (
        "warning",
        "`byte_compile` is on but no compatible host interpreter was found, so source shipped instead.",
        "Install a CPython matching the target's minor version, or set `byte_compile = false`.",
    ),
    "KF-SIGNING-UNCONFIGURED": (
        "warning",
        "The package shipped unsigned or ad-hoc signed where real signing is available.",
        "Configure signing for the platform, or ship unsigned deliberately.",
    ),
    "KF-PATH-DEPTH": (
        "warning",
        "A Windows onedir bundle nests so deep it only runs from a short folder "
        "while long paths are off (the Windows default). The artifact is fine; "
        "where it is unpacked is the constraint.",
        "Install to a short folder, or enable long paths on the target machines.",
    ),
    "KF-MANIFEST-POLICY": (
        "info",
        "The Android release-manifest policy passed with an informational finding.",
        "Review the finding; no action is required.",
    ),
    "KF-ENTITLEMENTS-UNGRANTED": (
        "warning",
        "Retired: no longer emitted. It warned that a profile pinned under iOS "
        "automatic signing lacked a declared entitlement; Xcode refuses any pin "
        "under automatic signing, so that build now fails before `xcodebuild`.",
        "None. The code stays reserved and will not be reused.",
    ),
    "KF-BUILD-TOOL-FAILED": (
        "error",
        "A build tool (Gradle, xcodebuild, appimagetool) ran and exited non-zero.",
        "Read the build log on stderr; `context` names the `tool` and `task`.",
    ),
    "KF-ARTIFACT-MISSING": (
        "error",
        "A build tool reported success but the product is not where it should be.",
        "Read the build log; this usually points at a broken toolchain step.",
    ),
    "KF-TOOLCHAIN-MISSING": (
        "error",
        "A required tool is not installed.",
        "Install the named tool and retry.",
    ),
    "KF-TOOLCHAIN-UNUSABLE": (
        "error",
        "A tool is present but could not be executed.",
        "Fix the file's permissions or executability; `context.errno` says why.",
    ),
    "KF-DEPENDENCY-DRIFT": (
        "warning",
        "An installed dependency sits outside the specifier `pyproject.toml` declares.",
        "Align the installed version, or widen the specifier. Nothing was modified.",
    ),
    "KF-IDE-NOT-FOUND": (
        "warning",
        "`open` found no IDE launcher on PATH. The project exists and can be opened by hand.",
        "Install the platform IDE, or open the generated project manually.",
    ),
    "KF-HOST-INCAPABLE": (
        "error",
        "This host cannot build this target at all (for example iOS from Windows).",
        "Build on a supported host; see the host matrix.",
    ),
    "KF-ERROR": (
        "error",
        "An expected failure with no more specific code assigned yet.",
        "Read the diagnostic's `message` and `remediation`.",
    ),
    "KF-DOCTOR-CHECK": (
        "warning",
        "A doctor check reported WARN or FAIL and has no specific code yet.",
        "See `data.checks`, keyed by the check name.",
    ),
}


def _host_matrix_md() -> str:
    caps = collect()
    labels = [host_label(h) for h in HOSTS]
    header = "| Target | " + " | ".join(labels) + " |"
    sep = "|" + "---|" * (len(labels) + 1)
    rows = [header, sep]
    for platform in caps.platforms:
        cells = ["Yes" if platform.hosts.get(h) else "No" for h in HOSTS]
        rows.append(f"| `{platform.name}` | " + " | ".join(cells) + " |")
    return "\n".join(rows)


def _exit_codes_md() -> str:
    caps = collect()
    rows = ["| Code | Meaning | Typical reaction |", "|---|---|---|"]
    for code, meaning in sorted(caps.exit_codes.items()):
        reaction = _EXIT_REACTION.get(code, "")
        rows.append(f"| `{code}` | {meaning} | {reaction} |")
    return "\n".join(rows)


def _diagnostic_codes_md() -> str:
    caps = collect()
    published = set(caps.diagnostic_codes)
    documented = set(_DIAGNOSTIC)
    if published != documented:
        missing = published - documented
        extra = documented - published
        raise ValueError(
            "kf_generated: KF-* code table is out of sync with kivyforge.\n"
            f"  Undocumented codes (add to _DIAGNOSTIC): {sorted(missing)}\n"
            f"  Stale codes (remove from _DIAGNOSTIC):    {sorted(extra)}"
        )
    rows = ["| Code | Severity | Meaning | Remediation |", "|---|---|---|---|"]
    for code in sorted(caps.diagnostic_codes):
        severity, meaning, remediation = _DIAGNOSTIC[code]
        rows.append(f"| `{code}` | {severity} | {meaning} | {remediation} |")
    return "\n".join(rows)


def _repo_blob_base(config) -> str:
    """`.../blob/main/` for the configured repo, so inlined links keep working.

    Derived from ``repo_url`` rather than hardcoded, so the base follows the
    repo when it moves (for example on the transfer to the kivy org).
    """
    repo = (getattr(config, "repo_url", None) or _DEFAULT_REPO).rstrip("/")
    return f"{repo}/blob/main/"


def _absolutise_links(text: str, base: str) -> str:
    """Rewrite repo-relative links in inlined root docs to absolute URLs.

    ``CHANGELOG.md`` and ``FAQ.md`` live at the repo root and link to files
    that are not part of the site (``docs/design/...``, ``README.md``). Left
    relative, those links resolve against the including page and break
    ``mkdocs build --strict``. Absolute URLs to the repo keep them working and
    keep the strict link check meaningful for genuinely authored pages.
    """

    def repl(match: re.Match[str]) -> str:
        target = match.group(1)
        if target.startswith(("http://", "https://", "#", "mailto:")):
            return match.group(0)
        return f"]({base}{target})"

    return _LINK.sub(repl, text)


def _inline_root_doc(name: str, config) -> str:
    text = (_REPO_ROOT / name).read_text(encoding="utf-8")
    # Drop the file's own top-level H1; the including page supplies the title,
    # so the page has exactly one H1 and a clean table of contents.
    text = re.sub(r"\A\s*#[^#\n].*\n", "", text)
    return _absolutise_links(text, _repo_blob_base(config))


def on_page_markdown(markdown: str, *, page=None, config=None, files=None) -> str:
    if HOST_MATRIX in markdown:
        markdown = markdown.replace(HOST_MATRIX, _host_matrix_md())
    if EXIT_CODES in markdown:
        markdown = markdown.replace(EXIT_CODES, _exit_codes_md())
    if DIAGNOSTIC_CODES in markdown:
        markdown = markdown.replace(DIAGNOSTIC_CODES, _diagnostic_codes_md())
    if CHANGELOG in markdown:
        markdown = markdown.replace(CHANGELOG, _inline_root_doc("CHANGELOG.md", config))
    if FAQ in markdown:
        markdown = markdown.replace(FAQ, _inline_root_doc("FAQ.md", config))
    return markdown
