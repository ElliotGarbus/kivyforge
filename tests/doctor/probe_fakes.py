"""A configurable fake :class:`~kivyforge.doctor.probe.Probe` shared by the
platform doctor tests (iOS, macOS, Linux)."""

from __future__ import annotations


class FakeProbe:
    """A Probe whose every answer is set per test."""

    def __init__(self, **overrides):
        self._xcode = overrides.get("xcode", "16.0")
        self._select = overrides.get("select", "/Applications/Xcode.app")
        self._clang = overrides.get("clang", True)
        self._swift = overrides.get("swift", True)
        self._runtimes = overrides.get("runtimes", ["18.0"])
        self._latest = overrides.get("latest", None)
        self._identities = overrides.get("identities", [])
        self._login_identities = overrides.get("login_identities", [])
        self._reachable = overrides.get("reachable", True)
        self._platforms = overrides.get("platforms", {})
        self._pip = overrides.get("pip", "24.3.1")
        self._host = overrides.get("host", "Darwin")
        self._codesign = overrides.get("codesign", True)
        self._notarytool = overrides.get("notarytool", True)
        self._root = overrides.get("root", False)
        self._libc = overrides.get("libc", "glibc")
        self._libraries = overrides.get("libraries", {"libGL.so.1", "libEGL.so.1"})
        self._sessions = overrides.get("sessions", {"x11"})
        self._desktop_validate = overrides.get("desktop_validate", True)
        self._desktop_errors = overrides.get("desktop_errors", None)
        self._long_paths = overrides.get("long_paths", True)
        self._signtool = overrides.get("signtool", True)
        self._thumbprints = overrides.get("thumbprints", [])
        self._output_locked = overrides.get("output_locked", None)
        self._filesystem = overrides.get("filesystem", "NTFS")

    def host_system(self):
        return self._host

    def has_codesign(self):
        return self._codesign

    def has_notarytool(self):
        return self._notarytool

    def is_root(self):
        return self._root

    def xcode_version(self):
        return self._xcode

    def pip_version(self):
        return self._pip

    def xcode_select_path(self):
        return self._select

    def has_xcrun_clang(self):
        return self._clang

    def has_swift_toolchain(self):
        return self._swift

    def simulator_runtimes(self):
        return list(self._runtimes)

    def latest_kivyforge_version(self):
        return self._latest

    def keychain_identities(self):
        return list(self._identities)

    def login_keychain_identities(self):
        return list(self._login_identities)

    def tcp_reachable(self, host, port):
        if isinstance(self._reachable, dict):
            return self._reachable.get(host, True)
        return self._reachable

    def binary_platforms(self, path):
        return set(self._platforms.get(path.name, set()))

    def linux_libc(self):
        return self._libc

    def shared_libraries(self):
        return frozenset(self._libraries)

    def display_session(self):
        return set(self._sessions)

    def has_desktop_file_validate(self):
        return self._desktop_validate

    def desktop_file_errors(self, path):
        return self._desktop_errors

    def long_paths_enabled(self):
        return self._long_paths

    def has_signtool(self):
        return self._signtool

    def code_signing_thumbprints(self, store_scope):
        if isinstance(self._thumbprints, dict):
            return list(self._thumbprints.get(store_scope, []))
        return list(self._thumbprints)

    def build_output_locked(self, path):
        if isinstance(self._output_locked, BaseException):
            raise self._output_locked
        return self._output_locked

    def filesystem_type(self, path):
        return self._filesystem
