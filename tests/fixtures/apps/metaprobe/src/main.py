"""The metaprobe: what ``importlib.metadata`` sees inside a built app.

Built and launched by ``tests/integration/test_app_metadata_devices.py``
(``docs/design/dev/package-metadata-proposal.md``, layer 3). Prints the report
as one line, ``METAPROBE {json}``, and once more as one short line per key,
``METAPROBE.<key> <json>``, because logcat cuts a line at about 1,000
characters and an Android release build is not debuggable, so its file cannot
be read. Writes the full line to ``metaprobe.json`` and exits.
"""

import importlib.metadata as md
import json
import os
import re
import sys
import tempfile
import traceback

#: Rewritten by the driver before every build, so a report can be matched to
#: the build that produced it, never to an app an earlier run left installed.
BUILD_MARK = "unset"

APP = "metaprobe-app"
ALIASES = ("metaprobe-app", "metaprobe_app", "Metaprobe.App")
DEPENDENCIES = ("metaprobe-dep", "metaprobe-extra")
GROUP = "metaprobe.plugins"
#: The app's top-level module and package, and an asset folder that is neither.
APP_MODULES = ("main", "metaprobe_app", "assets")


def _normalize(name):
    return re.sub(r"[-_.]+", "_", name).lower()


def _where(dist):
    path = getattr(dist, "_path", None)
    return None if path is None else str(path)


def _distribution(name):
    try:
        dist = md.distribution(name)
    except md.PackageNotFoundError:
        return None
    return {
        "name": dist.metadata["Name"],
        "version": dist.version,
        "path": _where(dist),
    }


def _report():
    out = {
        "build_mark": BUILD_MARK,
        # main.pyc in a release build that strips source.
        "main_file": os.path.basename(__file__),
        "python": sys.version.split()[0],
        "sys_path": list(sys.path),
    }
    for name in ALIASES + DEPENDENCIES:
        out["distribution:" + name] = _distribution(name)
    out["app_copies"] = sorted(
        str(_where(d))
        for d in md.distributions()
        if _normalize(d.metadata["Name"] or "") == _normalize(APP)
    )
    try:
        app = md.distribution(APP)
    except md.PackageNotFoundError:
        out["app_entry_points"] = None
        out["app_files"] = "not found"
        out["app_requires"] = "not found"
    else:
        out["app_entry_points"] = sorted(
            [ep.group, ep.name, ep.value] for ep in app.entry_points
        )
        out["app_files"] = None if app.files is None else len(app.files)
        out["app_requires"] = app.requires
    out["plugins"] = sorted(
        [ep.name, ep.value, ep.dist.metadata["Name"] if ep.dist else None]
        for ep in md.entry_points(group=GROUP)
    )
    found = md.packages_distributions()
    out["packages_distributions"] = {m: sorted(found.get(m, [])) for m in APP_MODULES}
    try:
        (ep,) = md.entry_points(group=GROUP, name="dep-plugin")
        loaded = ep.load()
        out["loaded"] = f"{loaded.__module__}.{loaded.__qualname__}"
    except Exception as exc:
        out["loaded"] = f"error: {exc!r}"
    return out


def _outputs():
    """Where the report file may go, most specific first."""
    for env in ("METAPROBE_OUT", "ANDROID_PRIVATE"):
        if os.environ.get(env):
            yield os.environ[env]
    home = os.path.expanduser("~")
    yield os.path.join(home, "Documents")
    yield home
    yield tempfile.gettempdir()


def main():
    try:
        report = _report()
    except Exception:
        report = {"build_mark": BUILD_MARK, "error": traceback.format_exc()}
    line = json.dumps(report, sort_keys=True)
    print("METAPROBE " + line, flush=True)
    for key, value in sorted(report.items()):
        print(f"METAPROBE.{key} {json.dumps(value, sort_keys=True)}", flush=True)
    for directory in _outputs():
        if not os.path.isdir(directory):
            continue
        try:
            with open(
                os.path.join(directory, "metaprobe.json"), "w", encoding="utf-8"
            ) as fh:
                fh.write(line)
        except OSError:
            continue
        break


main()
