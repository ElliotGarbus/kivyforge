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
