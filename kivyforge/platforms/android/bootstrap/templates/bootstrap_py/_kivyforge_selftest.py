"""kivyforge contract self-test (android/05 §contract smoke-test hook).

Inert in a normal launch: the native launcher imports and runs this only when
KIVYFORGE_SELFTEST is set (the instrumented KivyforgeContractTest sets it via
an intent extra the Activity forwards to the environment). It exercises the two
novel, load-bearing runtime mechanisms on-device — the flattened-extension
sys.meta_path finder and the pyjnius invoke0 glue — and writes a result file
the instrumentation polls.

Adds no attack surface or startup cost to a shipped app: it never runs unless
the test flag is present.
"""

import os
import traceback

#: The app's own package metadata as kivyforge generated it
#: (docs/design/dev/package-metadata-proposal.md): ``name``, ``version`` and
#: sorted ``[group, name, value]`` entry points. Rendered in at build time;
#: ``None`` when kivyforge generated none (entry points in ``dynamic``).
EXPECTED_APP_METADATA = None

#: The launcher class the manifest names: ``[tool.kivy.android].main_activity``
#: or the generated ``org.kivy.android.PythonActivity``. Rendered in at build
#: time; ``None`` skips the check.
EXPECTED_LAUNCHER = None


def _result_path() -> str:
    private = os.environ.get("ANDROID_PRIVATE", ".")
    return os.path.join(private, "kivyforge_selftest.txt")


def run() -> bool:
    lines: list[str] = []
    ok = True

    # 1. A stdlib lib-dynload extension AND a wheel extension, both resolved
    #    through the kivyforge finder (flattened .so + manifest).
    try:
        import _ssl  # noqa: F401  (stdlib, DT_NEEDEDs libssl_python.so)

        import jnius  # noqa: F401  (wheel extension: jnius.jnius)

        lines.append("EXT_OK")
    except Exception:
        ok = False
        lines.append("EXT_FAIL")
        lines.append(traceback.format_exc())

    # 2. pyjnius invoke0 round-trip: a Python-implemented Java interface driven
    #    from Java (the NativeInvocationHandler matched pair).
    try:
        from jnius import PythonJavaClass, autoclass, java_method

        class _Cmp(PythonJavaClass):
            __javainterfaces__ = ["java/util/Comparator"]
            __javacontext__ = "app"

            @java_method("(Ljava/lang/Object;Ljava/lang/Object;)I")
            def compare(self, a, b):
                sa, sb = str(a), str(b)
                return -1 if sa < sb else (1 if sa > sb else 0)

        ArrayList = autoclass("java.util.ArrayList")
        Collections = autoclass("java.util.Collections")
        lst = ArrayList()
        for item in ("cherry", "apple", "banana"):
            lst.add(item)
        Collections.sort(lst, _Cmp())
        ordered = [lst.get(i) for i in range(lst.size())]
        assert ordered == ["apple", "banana", "cherry"], ordered
        lines.append("PROXY_OK")
    except Exception:
        ok = False
        lines.append("PROXY_FAIL")
        lines.append(traceback.format_exc())

    # 3. Kivy 3's Android bootstrap contract: Kivy names no activity class of
    #    its own, it imports _kivy_bootstrap and pulls the Activity from there.
    #    Checked on-device because this is kivyforge's side of an interface
    #    another project relies on, and the failure it guards against — a
    #    bundle that starts fine and dies when Kivy first needs the Activity —
    #    is invisible to a unit test of the staging code.
    try:
        import _kivy_bootstrap

        activity = _kivy_bootstrap.get_activity()
        assert activity is not None, "no Activity while the Activity is running"
        # Prove it is the live Activity rather than some retained husk.
        assert activity.getPackageName(), "Activity did not answer as a Context"
        lines.append("KIVY_CONTRACT_OK")
    except Exception:
        ok = False
        lines.append("KIVY_CONTRACT_FAIL")
        lines.append(traceback.format_exc())

    # 4. The bundled android package: every module imports, and the Java
    #    members it calls exist on the activity. A missing member only fails
    #    when the app first calls it, so it is looked up here instead.
    try:
        import android
        import android.activity
        import android.broadcast
        import android.darkmode
        import android.loadingscreen
        import android.permissions
        import android.runnable
        import android.storage  # noqa: F401
        from jnius import autoclass

        assert android.mActivity is not None, "android.mActivity is None"
        assert android.api_version > 0, android.api_version
        granted = android.mActivity.checkCurrentPermission(
            "android.permission.INTERNET"
        )
        assert granted in (True, False), granted
        cls = autoclass("java.lang.Class").forName(android.config.ACTIVITY_CLASS_NAME)
        declared = {m.getName() for m in cls.getDeclaredMethods()}
        missing = {
            "addPermissionsCallback",
            "changeKeyboard",
            "registerActivityResultListener",
            "registerNewIntentListener",
            "requestPermissionsWithRequestCode",
            "setDarkModeListener",
            "unregisterActivityResultListener",
            "unregisterNewIntentListener",
        } - declared
        assert not missing, f"PythonActivity lacks {sorted(missing)}"
        lines.append("ANDROID_PKG_OK")
    except Exception:
        ok = False
        lines.append("ANDROID_PKG_FAIL")
        lines.append(traceback.format_exc())

    # 5. The app's own package metadata: importlib.metadata finds what kivyforge
    #    generated from [project] -- the name, the version every other artifact
    #    carries, and the entry points a plugin-based app looks itself up by.
    try:
        expected = EXPECTED_APP_METADATA
        if expected is not None:
            import importlib.metadata as md

            dist = md.distribution(expected["name"])
            assert dist.metadata["Name"] == expected["name"], dist.metadata["Name"]
            assert dist.version == expected["version"], dist.version
            found = sorted([e.group, e.name, e.value] for e in dist.entry_points)
            assert found == expected["entry_points"], found
        lines.append("APP_METADATA_OK")
    except Exception:
        ok = False
        lines.append("APP_METADATA_FAIL")
        lines.append(traceback.format_exc())

    # 6. The running activity is the configured launcher. android.mActivity is
    #    the base class's static, which holds the subclass instance when the
    #    app supplies one.
    try:
        if EXPECTED_LAUNCHER is not None:
            import android

            running = android.mActivity.getClass().getName()
            assert running == EXPECTED_LAUNCHER, (
                f"running activity is {running}, expected {EXPECTED_LAUNCHER}"
            )
        lines.append("LAUNCHER_OK")
    except Exception:
        ok = False
        lines.append("LAUNCHER_FAIL")
        lines.append(traceback.format_exc())

    if ok:
        lines.append("SELFTEST_ALL_OK")
    lines.append("SELFTEST_DONE")

    try:
        with open(_result_path(), "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    except Exception:
        traceback.print_exc()
    print("kivyforge selftest:", " ".join(lines[:1] + ["…"]), flush=True)
    return ok
