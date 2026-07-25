"""Kivyforge extension-module finder (Phase-0 prototype).

Android exposes native libraries only from the flat nativeLibraryDir; Python
extension modules are imported by dotted name from nested paths. The build
flattens every extension .so into jniLibs/<abi>/ as ``libpy.<dotted>.so`` and
records the mapping in ``ext_manifest.json``; this finder resolves imports
through that manifest with a stock ExtensionFileLoader.

See docs/design/platforms/android/05-bootstrap-android.md, "Extension-module
finder".
"""

import json
import os
import sys
from importlib.machinery import ExtensionFileLoader, ModuleSpec


class KivyforgeExtensionFinder:
    def __init__(self, mapping, native_dir):
        self._mapping = mapping
        self._native_dir = native_dir

    def find_spec(self, fullname, path=None, target=None):
        filename = self._mapping.get(fullname)
        if filename is None:
            return None
        location = os.path.join(self._native_dir, filename)
        if not os.path.exists(location):
            raise ImportError(
                f"kivyforge: manifest maps {fullname!r} to {filename!r}, "
                f"but it is not present in {self._native_dir!r} — "
                "the APK native-library extraction did not deliver it"
            )
        loader = ExtensionFileLoader(fullname, location)
        spec = ModuleSpec(fullname, loader, origin=location)
        # Submodule extensions (e.g. jnius.jnius) need is_package=False, which
        # ModuleSpec already defaults to for ExtensionFileLoader.
        return spec

    def __repr__(self):
        return (f"<KivyforgeExtensionFinder {len(self._mapping)} modules "
                f"at {self._native_dir!r}>")


def install(manifest_path, native_dir):
    with open(manifest_path, encoding="utf-8") as f:
        mapping = json.load(f)
    finder = KivyforgeExtensionFinder(mapping, native_dir)
    sys.meta_path.insert(0, finder)
    print(f"kivyforge bootstrap: finder installed ({len(mapping)} extensions)")
    return finder
