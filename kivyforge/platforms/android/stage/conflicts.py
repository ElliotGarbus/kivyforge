"""Find an ``android`` module that the bundled ``android`` package would shadow.

The bundle's ``bootstrap/`` is ahead of the app and ``site-packages`` on
``sys.path``, so a second ``android`` would ship and never be imported. That
is never what its author meant, so the build fails instead of shipping it
unannounced.
"""

from __future__ import annotations

from pathlib import Path

#: What a top-level ``android`` looks like on disk: a package, a module, or an
#: extension module (``android.<tag>.so``).
_TOP_LEVEL = ("android", "android.py")


def _top_level_android(root: Path) -> Path | None:
    for name in _TOP_LEVEL:
        if (root / name).exists():
            return root / name
    for extension in sorted(root.glob("android.*.so")):
        return extension
    return None


def app_android_module(app_src: Path) -> Path | None:
    """``app_dir``'s own ``android.py`` or ``android/``, if it has one."""
    return _top_level_android(app_src)


def site_packages_android_provider(site_packages: Path) -> str | None:
    """The distribution that installed a top-level ``android``, if any.

    Read from each ``.dist-info/RECORD``; a module no RECORD claims is reported
    by its path instead, so the conflict is never missed for want of a name.
    """
    found = _top_level_android(site_packages)
    if found is None:
        return None
    return installed_by(site_packages, found.name) or found.name


def installed_by(site_packages: Path, prefix: str) -> str | None:
    """The first distribution whose RECORD lists *prefix* or a file below it."""
    owners = installers(site_packages, prefix)
    return owners[0] if owners else None


def installers(site_packages: Path, prefix: str) -> list[str]:
    """Every distribution whose RECORD lists *prefix* or a file below it."""
    owners: list[str] = []
    for record in sorted(site_packages.glob("*.dist-info/RECORD")):
        for line in record.read_text(encoding="utf-8", errors="replace").splitlines():
            path = line.split(",", 1)[0]
            if path == prefix or path.startswith(f"{prefix}/"):
                metadata = record.parent / "METADATA"
                owners.append(_dist_name(metadata) or record.parent.name.split("-")[0])
                break
    return owners


def _dist_name(metadata: Path) -> str | None:
    try:
        text = metadata.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    for line in text.splitlines():
        if line.startswith("Name:"):
            return line.split(":", 1)[1].strip()
        if not line:
            break
    return None
