"""Tests for RealProbe methods and Mach-O binary parsing helpers."""

from __future__ import annotations

import base64
import hashlib
import socket
import struct
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from kivyforge.doctor.probe import (
    LC_BUILD_VERSION,
    PLATFORM_NAMES,
    CertificateSubject,
    RealProbe,
    _capture,
    _certificate_subject,
    _certificate_subjects,
    _macho_platforms,
    _thin_platforms,
)

# ---------------------------------------------------------------------------
# Mach-O binary builder helpers
# ---------------------------------------------------------------------------


def _make_thin_macho(
    platform: int,
    *,
    little: bool = True,
    is64: bool = True,
    add_lc_build_version: bool = True,
) -> bytes:
    """Build a minimal Mach-O binary with one optional LC_BUILD_VERSION.

    Mach-O magic constants are the *real* values (MH_MAGIC_64 = 0xFEEDFACF,
    MH_MAGIC = 0xFEEDFACE) packed in the file's own endianness.  When the
    probe code reads them back with big-endian ``struct.unpack(">I", ...)`` it
    sees 0xCFFAEDFE / 0xCEFAEDFE for little-endian files and 0xFEEDFACF /
    0xFEEDFACE for big-endian files — exactly what ``_thin_platforms`` checks.
    """
    end = "<" if little else ">"

    # Real Mach-O magic values (stored in native byte order).
    if is64:
        magic = 0xFEEDFACF  # MH_MAGIC_64
    else:
        magic = 0xFEEDFACE  # MH_MAGIC

    lc_payload = b""
    if add_lc_build_version:
        lc_payload = struct.pack(
            end + "IIIIII",
            LC_BUILD_VERSION,  # cmd
            24,  # cmdsize
            platform,  # platform
            0x000D0000,  # minos (13.0)
            0,  # sdk
            0,  # ntools
        )

    ncmds = 1 if lc_payload else 0
    sizeofcmds = len(lc_payload)

    if is64:
        header = struct.pack(
            end + "IIIIIIII",
            magic,
            0x0100000C,  # cputype ARM64
            0,  # cpusubtype
            2,  # filetype MH_EXECUTE
            ncmds,
            sizeofcmds,
            0,  # flags
            0,  # reserved
        )
    else:
        header = struct.pack(
            end + "IIIIIII",
            magic,
            12,  # cputype ARM
            0,  # cpusubtype
            2,  # filetype
            ncmds,
            sizeofcmds,
            0,  # flags
        )

    return header + lc_payload


def _make_fat_macho(*slices: bytes) -> bytes:
    """Wrap one or more thin Mach-O slices in a fat binary header."""
    nfat = len(slices)
    # Fat header: magic(4) + nfat(4) + nfat * arch_entry(20)
    header_size = 8 + nfat * 20
    offsets: list[int] = []
    current = header_size
    for s in slices:
        offsets.append(current)
        current += len(s)

    header = struct.pack(">II", 0xCAFEBABE, nfat)
    for i, s in enumerate(slices):
        # arch entry: cputype, cpusubtype, offset, size, align
        header += struct.pack(">IIIII", 0x0100000C, 0, offsets[i], len(s), 0)

    return header + b"".join(slices)


# ---------------------------------------------------------------------------
# _thin_platforms
# ---------------------------------------------------------------------------


class TestThinPlatforms:
    def test_too_short_returns_empty(self):
        assert _thin_platforms(b"\x00\x01") == set()

    def test_non_macho_magic_returns_empty(self):
        assert _thin_platforms(b"\xde\xad\xbe\xef") == set()

    def test_ios_little_endian_64bit(self):
        data = _make_thin_macho(2, little=True, is64=True)  # 2 = ios
        assert _thin_platforms(data) == {"ios"}

    def test_ios_simulator_little_endian_32bit(self):
        data = _make_thin_macho(7, little=True, is64=False)  # 7 = ios-simulator
        assert _thin_platforms(data) == {"ios-simulator"}

    def test_macos_big_endian_64bit(self):
        data = _make_thin_macho(1, little=False, is64=True)  # 1 = macos
        assert _thin_platforms(data) == {"macos"}

    def test_macos_big_endian_32bit(self):
        data = _make_thin_macho(1, little=False, is64=False)
        assert _thin_platforms(data) == {"macos"}

    def test_unknown_platform_fallback(self):
        data = _make_thin_macho(99, little=True, is64=True)
        result = _thin_platforms(data)
        assert result == {"platform-99"}
        assert 99 not in PLATFORM_NAMES

    def test_no_lc_build_version_returns_empty(self):
        data = _make_thin_macho(2, add_lc_build_version=False)
        assert _thin_platforms(data) == set()

    def test_truncated_after_header_breaks_early(self):
        # ncmds says 5 but no load command bytes follow the header
        end = "<"
        magic = 0xCFFAEDFE
        header = struct.pack(
            end + "IIIIIIII",
            magic,
            0x0100000C,  # cputype
            0,  # cpusubtype
            2,  # filetype
            5,  # ncmds — but no LC data follows
            0,  # sizeofcmds
            0,  # flags
            0,  # reserved
        )
        # The header alone is 32 bytes; offset+8 > len(data) fires immediately.
        assert _thin_platforms(header) == set()

    def test_zero_cmdsize_breaks_loop(self):
        # A load command with cmdsize=0 must terminate the loop.
        end = "<"
        magic = 0xCFFAEDFE
        lc = struct.pack(end + "II", 0x00, 0)  # cmd=0, cmdsize=0
        header = struct.pack(
            end + "IIIIIIII",
            magic,
            0x0100000C,
            0,
            2,
            1,  # ncmds
            len(lc),
            0,
            0,
        )
        assert _thin_platforms(header + lc) == set()


# ---------------------------------------------------------------------------
# _macho_platforms
# ---------------------------------------------------------------------------


class TestMachoPlatforms:
    def test_too_short_returns_empty(self):
        assert _macho_platforms(b"\x00") == set()

    def test_non_fat_non_macho_returns_empty(self):
        assert _macho_platforms(b"\x00\x01\x02\x03") == set()

    def test_thin_binary_direct(self):
        data = _make_thin_macho(2)
        assert _macho_platforms(data) == {"ios"}

    def test_fat_binary_single_slice(self):
        fat = _make_fat_macho(_make_thin_macho(2))
        assert _macho_platforms(fat) == {"ios"}

    def test_fat_binary_multiple_slices(self):
        fat = _make_fat_macho(_make_thin_macho(2), _make_thin_macho(7))
        assert _macho_platforms(fat) == {"ios", "ios-simulator"}


# ---------------------------------------------------------------------------
# _capture
# ---------------------------------------------------------------------------


class TestCapture:
    def test_success_returns_stdout(self, monkeypatch):
        result = MagicMock()
        result.returncode = 0
        result.stdout = "hello\n"
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: result)
        assert _capture(["echo", "hello"]) == "hello\n"

    def test_nonzero_returncode_returns_empty(self, monkeypatch):
        result = MagicMock()
        result.returncode = 1
        result.stdout = "ignored"
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: result)
        assert _capture(["false"]) == ""

    def test_oserror_returns_empty(self, monkeypatch):
        def raise_os(*a, **k):
            raise OSError("not found")

        monkeypatch.setattr(subprocess, "run", raise_os)
        assert _capture(["nonexistent-command"]) == ""

    def test_valueerror_returns_empty(self, monkeypatch):
        def raise_val(*a, **k):
            raise ValueError("bad")

        monkeypatch.setattr(subprocess, "run", raise_val)
        assert _capture(["bad"]) == ""


# ---------------------------------------------------------------------------
# RealProbe methods
# ---------------------------------------------------------------------------


class TestRealProbe:
    def _probe(self) -> RealProbe:
        return RealProbe()

    # --- xcode_version ---

    def test_xcode_version_parses_output(self, monkeypatch):
        monkeypatch.setattr(
            "kivyforge.doctor.probe._capture",
            lambda _: "Xcode 16.0\nBuild version 16A242d\n",
        )
        assert self._probe().xcode_version() == "16.0"

    def test_xcode_version_empty_returns_none(self, monkeypatch):
        monkeypatch.setattr("kivyforge.doctor.probe._capture", lambda _: "")
        assert self._probe().xcode_version() is None

    # --- pip_version ---

    def test_pip_version_parses_output(self, monkeypatch):
        monkeypatch.setattr(
            "kivyforge.doctor.probe._capture",
            lambda _: "pip 24.3.1 from /x/site-packages/pip (python 3.15)\n",
        )
        assert self._probe().pip_version() == "24.3.1"

    def test_pip_version_unavailable_returns_none(self, monkeypatch):
        monkeypatch.setattr("kivyforge.doctor.probe._capture", lambda _: "")
        assert self._probe().pip_version() is None

    # --- xcode_select_path ---

    def test_xcode_select_path_returns_value(self, monkeypatch):
        monkeypatch.setattr(
            "kivyforge.doctor.probe._capture",
            lambda _: "/Applications/Xcode.app/Contents/Developer\n",
        )
        result = self._probe().xcode_select_path()
        assert result == "/Applications/Xcode.app/Contents/Developer\n"

    def test_xcode_select_path_empty_returns_none(self, monkeypatch):
        monkeypatch.setattr("kivyforge.doctor.probe._capture", lambda _: "")
        assert self._probe().xcode_select_path() is None

    # --- has_xcrun_clang ---

    def test_has_xcrun_clang_true(self, monkeypatch):
        monkeypatch.setattr(
            "kivyforge.doctor.probe._capture", lambda _: "/usr/bin/clang"
        )
        assert self._probe().has_xcrun_clang() is True

    def test_has_xcrun_clang_false(self, monkeypatch):
        monkeypatch.setattr("kivyforge.doctor.probe._capture", lambda _: "")
        assert self._probe().has_xcrun_clang() is False

    # --- simulator_runtimes ---

    def test_simulator_runtimes_parses_ios_lines(self, monkeypatch):
        output = (
            "== Runtimes ==\n"
            "iOS 17.5 (17.5 - 21F79) - com.apple.CoreSimulator.SimRuntime.iOS-17-5\n"
            "iOS 18.0 (18.0 - 22A3351) - com.apple.CoreSimulator.SimRuntime.iOS-18-0\n"
            "watchOS 11.0 (11.0 - 22R5339b) - ignored\n"
        )
        monkeypatch.setattr("kivyforge.doctor.probe._capture", lambda _: output)
        assert self._probe().simulator_runtimes() == ["17.5", "18.0"]

    def test_simulator_runtimes_empty_output(self, monkeypatch):
        monkeypatch.setattr("kivyforge.doctor.probe._capture", lambda _: "")
        assert self._probe().simulator_runtimes() == []

    # --- ios_deployment_target_range ---

    def _sdk(self, monkeypatch, tmp_path, settings: str | None) -> RealProbe:
        if settings is not None:
            (tmp_path / "SDKSettings.json").write_text(settings, encoding="utf-8")
        monkeypatch.setattr(
            "kivyforge.doctor.probe._capture", lambda _: f"{tmp_path}\n"
        )
        return self._probe()

    def test_deployment_range_reads_the_sdk_settings(self, monkeypatch, tmp_path):
        # The shape of Xcode 27.0's iPhoneOS27.0.sdk/SDKSettings.json.
        settings = (
            '{"SupportedTargets": {"iphoneos": {'
            '"MinimumDeploymentTarget": "15.0", '
            '"MaximumDeploymentTarget": "27.0.99", '
            '"RecommendedDeploymentTarget": "17.0"}}}'
        )
        probe = self._sdk(monkeypatch, tmp_path, settings)
        assert probe.ios_deployment_target_range() == ("15.0", "27.0.99")

    def test_deployment_range_none_without_an_sdk(self, monkeypatch):
        monkeypatch.setattr("kivyforge.doctor.probe._capture", lambda _: "")
        assert self._probe().ios_deployment_target_range() is None

    @pytest.mark.parametrize(
        "settings",
        [
            None,  # no SDKSettings.json
            "not json",
            '{"SupportedTargets": {}}',
            '{"SupportedTargets": {"iphoneos": {"MinimumDeploymentTarget": 15}}}',
            '{"SupportedTargets": {"iphoneos": {"MinimumDeploymentTarget": "15.0",'
            ' "MaximumDeploymentTarget": 27}}}',
            "[]",
        ],
    )
    def test_deployment_range_none_on_an_unexpected_shape(
        self, monkeypatch, tmp_path, settings
    ):
        probe = self._sdk(monkeypatch, tmp_path, settings)
        assert probe.ios_deployment_target_range() is None

    # --- keychain_identities ---

    def test_keychain_identities_parses_lines(self, monkeypatch):
        output = (
            '  1) ABC123 "Apple Development: Test"\n  2) DEF456 "iPhone Distribution"\n'
        )
        monkeypatch.setattr("kivyforge.doctor.probe._capture", lambda _: output)
        ids = self._probe().keychain_identities()
        assert len(ids) == 2
        assert ids[0].startswith("1)")

    def test_keychain_identities_empty(self, monkeypatch):
        monkeypatch.setattr("kivyforge.doctor.probe._capture", lambda _: "")
        assert self._probe().keychain_identities() == []

    # --- keychain_certificates ---

    def test_keychain_certificates_joins_identities_to_certificates(self, monkeypatch):
        signing = _certificate_der(_APPLE_SUBJECT)
        other = _certificate_der([(_OID_CN, 0x0C, b"Some Root CA")])
        identities = f'  1) {_sha1(signing)} "Apple Development: Jo Doe (X83FAZ586W)"\n'
        commands = []

        def fake_capture(cmd):
            commands.append(cmd)
            if cmd[1] == "find-identity":
                return identities + "     1 valid identities found\n"
            return _pem(other) + _pem(signing)

        monkeypatch.setattr("kivyforge.doctor.probe._capture", fake_capture)
        assert self._probe().keychain_certificates() == [
            CertificateSubject(
                "Apple Development: Jo Doe (X83FAZ586W)", "R5PKSQLUZY", "Jo Doe"
            )
        ]
        # -a: without it, find-certificate stops at the first match.
        assert commands[1] == ["security", "find-certificate", "-a", "-p"]

    def test_keychain_certificates_without_identities_reads_no_certificates(
        self, monkeypatch
    ):
        commands = []
        monkeypatch.setattr(
            "kivyforge.doctor.probe._capture",
            lambda cmd: commands.append(cmd) or "     0 valid identities found\n",
        )
        assert self._probe().keychain_certificates() == []
        assert len(commands) == 1

    # --- login_keychain_identities ---

    def test_login_keychain_identities_scopes_to_login_keychain(self, monkeypatch):
        seen_cmd = {}

        def fake_capture(cmd):
            seen_cmd["cmd"] = cmd
            return '  1) ABC123 "Developer ID Application: Jane Doe (ABC1234)"\n'

        monkeypatch.setattr("kivyforge.doctor.probe._capture", fake_capture)
        ids = self._probe().login_keychain_identities()
        assert len(ids) == 1
        assert seen_cmd["cmd"][:4] == ["security", "find-identity", "-v", "-p"]
        assert seen_cmd["cmd"][-1].endswith("login.keychain-db")

    def test_login_keychain_identities_empty(self, monkeypatch):
        monkeypatch.setattr("kivyforge.doctor.probe._capture", lambda _: "")
        assert self._probe().login_keychain_identities() == []

    # --- is_root ---

    def test_is_root_true(self, monkeypatch):
        monkeypatch.setattr(
            "kivyforge.doctor.probe.os.geteuid", lambda: 0, raising=False
        )
        assert self._probe().is_root() is True

    def test_is_root_false(self, monkeypatch):
        monkeypatch.setattr(
            "kivyforge.doctor.probe.os.geteuid", lambda: 501, raising=False
        )
        assert self._probe().is_root() is False

    # --- tcp_reachable ---

    def test_tcp_reachable_success(self, monkeypatch):
        cm = MagicMock()
        cm.__enter__ = lambda s: s
        cm.__exit__ = lambda s, *a: None
        monkeypatch.setattr(socket, "create_connection", lambda *a, **k: cm)
        assert self._probe().tcp_reachable("pypi.org", 443) is True

    def test_tcp_reachable_oserror(self, monkeypatch):
        def raise_os(*a, **k):
            raise OSError("connection refused")

        monkeypatch.setattr(socket, "create_connection", raise_os)
        assert self._probe().tcp_reachable("pypi.org", 443) is False

    # --- binary_platforms ---

    def test_binary_platforms_missing_file_returns_empty(self, tmp_path):
        assert self._probe().binary_platforms(tmp_path / "nonexistent.dylib") == set()

    def test_binary_platforms_valid_macho(self, tmp_path):
        binary = tmp_path / "test.dylib"
        binary.write_bytes(_make_thin_macho(2))  # ios
        assert self._probe().binary_platforms(binary) == {"ios"}

    # --- latest_kivyforge_version ---

    def test_latest_kivyforge_version_success(self):
        fake_resp = MagicMock()
        fake_resp.__enter__ = lambda s: s
        fake_resp.__exit__ = lambda s, *a: None

        with patch("urllib.request.urlopen", return_value=fake_resp):
            with patch("json.load", return_value={"info": {"version": "3.1.0"}}):
                result = self._probe().latest_kivyforge_version()
        assert result == "3.1.0"

    def test_latest_kivyforge_version_network_error(self):
        with patch("urllib.request.urlopen", side_effect=OSError("network")):
            assert self._probe().latest_kivyforge_version() is None

    # --- build_output_locked ---

    def test_build_output_locked_none_when_absent(self, tmp_path):
        assert self._probe().build_output_locked(tmp_path / "nope") is None

    def test_build_output_locked_false_when_free(self, tmp_path):
        d = tmp_path / "App"
        d.mkdir()
        assert self._probe().build_output_locked(d) is False
        assert d.exists()  # rename round-trip restored it

    def test_build_output_locked_true_when_rename_blocked(self, tmp_path, monkeypatch):
        d = tmp_path / "App"
        d.mkdir()

        def blocked(*a, **k):
            raise PermissionError(5, "Access is denied")

        monkeypatch.setattr("kivyforge.doctor.probe.os.replace", blocked)
        assert self._probe().build_output_locked(d) is True

    def test_build_output_locked_raises_if_restore_fails(self, tmp_path, monkeypatch):
        # A diagnostic must never silently leave the build displaced: if the tree
        # moves aside but cannot be restored, it raises (naming where it landed)
        # rather than swallowing the failure.
        import kivyforge.doctor.probe as P

        d = tmp_path / "App"
        d.mkdir()
        real = P.os.replace
        calls = {"n": 0}

        def flaky(src, dst):
            calls["n"] += 1
            if calls["n"] == 1:
                return real(src, dst)  # move-aside succeeds
            raise PermissionError(5, "Access is denied")  # restore keeps failing

        monkeypatch.setattr(P, "_RESTORE_TIMEOUT_S", 0.2)
        monkeypatch.setattr(P.time, "sleep", lambda *_a, **_k: None)
        monkeypatch.setattr(P.os, "replace", flaky)
        with pytest.raises(OSError, match="could not restore it"):
            self._probe().build_output_locked(d)

    # --- filesystem_type ---

    def test_filesystem_type_str_on_windows_else_none(self, tmp_path):
        result = self._probe().filesystem_type(tmp_path)
        # POSIX has no ctypes.windll -> None; Windows returns e.g. "NTFS"/"ReFS".
        assert result is None or isinstance(result, str)


# ---------------------------------------------------------------------------
# X.509 subject parsing (keychain_certificates)
# ---------------------------------------------------------------------------

_OID_UID = b"\x09\x92\x26\x89\x93\xf2\x2c\x64\x01\x01"
_OID_CN = b"\x55\x04\x03"
_OID_OU = b"\x55\x04\x0b"
_OID_O = b"\x55\x04\x0a"
_OID_C = b"\x55\x04\x06"

# The subject of a real Apple Development certificate, in its order and string
# types: subject= /UID=.../CN=.../OU=.../O=.../C=US (LibreSSL, 2026-10-14).
_APPLE_SUBJECT = [
    (_OID_UID, 0x0C, b"LQS6DP566H"),
    (_OID_CN, 0x0C, b"Apple Development: Jo Doe (X83FAZ586W)"),
    (_OID_OU, 0x0C, b"R5PKSQLUZY"),
    (_OID_O, 0x0C, b"Jo Doe"),
    (_OID_C, 0x13, b"US"),
]


def _tlv(tag: int, content: bytes) -> bytes:
    """One DER element, with a long-form length when the content needs it."""
    size = len(content)
    if size < 0x80:
        return bytes([tag, size]) + content
    raw = size.to_bytes((size.bit_length() + 7) // 8, "big")
    return bytes([tag, 0x80 | len(raw)]) + raw + content


def _certificate_der(subject, *, version: bool = True) -> bytes:
    name = _tlv(
        0x30,
        b"".join(
            _tlv(0x31, _tlv(0x30, _tlv(0x06, oid) + _tlv(tag, value)))
            for oid, tag, value in subject
        ),
    )
    issuer = _tlv(0x30, _tlv(0x31, _tlv(0x30, _tlv(0x06, _OID_CN) + _tlv(0x0C, b"CA"))))
    fields = [
        _tlv(0xA0, _tlv(0x02, b"\x02")) if version else b"",
        _tlv(0x02, b"\x01"),
        _tlv(0x30, _tlv(0x06, b"\x2a\x86\x48\x86\xf7\x0d\x01\x01\x0b")),
        issuer,
        _tlv(0x30, _tlv(0x17, b"260101000000Z") + _tlv(0x17, b"270101000000Z")),
        name,
        _tlv(0x30, b""),
    ]
    tbs = _tlv(0x30, b"".join(fields))
    return _tlv(0x30, tbs + _tlv(0x30, b"") + _tlv(0x03, b"\x00"))


def _pem(der: bytes) -> str:
    body = base64.encodebytes(der).decode("ascii")
    return f"-----BEGIN CERTIFICATE-----\n{body}-----END CERTIFICATE-----\n"


def _sha1(der: bytes) -> str:
    return hashlib.sha1(der).hexdigest().upper()


class TestCertificateSubject:
    def test_reads_cn_ou_and_o(self):
        assert _certificate_subject(_certificate_der(_APPLE_SUBJECT)) == (
            CertificateSubject(
                "Apple Development: Jo Doe (X83FAZ586W)", "R5PKSQLUZY", "Jo Doe"
            )
        )

    def test_a_v1_certificate_has_no_version_field(self):
        subject = _certificate_subject(_certificate_der(_APPLE_SUBJECT, version=False))
        assert subject is not None
        assert subject.organizational_unit == "R5PKSQLUZY"

    def test_string_types(self):
        subject = [
            (_OID_CN, 0x13, b"Printable"),
            (_OID_OU, 0x1C, "R5PKSQLUZY".encode("utf-32-be")),
            (_OID_O, 0x1E, "Jos\u00e9 \u5c71\u7530".encode("utf-16-be")),
        ]
        assert _certificate_subject(_certificate_der(subject)) == CertificateSubject(
            "Printable", "R5PKSQLUZY", "Jos\u00e9 \u5c71\u7530"
        )

    def test_missing_fields_read_as_empty(self):
        der = _certificate_der([(_OID_CN, 0x0C, b"Only a name")])
        assert _certificate_subject(der) == CertificateSubject("Only a name", "", "")

    @pytest.mark.parametrize(
        "der",
        [
            b"",
            b"\x30",
            b"\x02\x01\x00",  # not a SEQUENCE
            b"\x30\x03\x02\x01\x00",  # a SEQUENCE holding no tbsCertificate
            b"\x30\x80\x00\x00",  # indefinite length is not DER
            b"\x30\x85\x00\x00\x00\x00\x01\x00",  # a 5-byte length
        ],
    )
    def test_malformed_der_is_none(self, der):
        assert _certificate_subject(der) is None

    def test_truncated_certificate_is_none(self):
        der = _certificate_der(_APPLE_SUBJECT)
        assert _certificate_subject(der[: len(der) // 2]) is None

    def test_too_few_tbs_fields_is_none(self):
        der = _tlv(0x30, _tlv(0x30, _tlv(0x02, b"\x01")))
        assert _certificate_subject(der) is None


class TestCertificateSubjects:
    def test_keeps_only_the_wanted_hashes_once_each(self):
        wanted = _certificate_der(_APPLE_SUBJECT)
        other = _certificate_der([(_OID_CN, 0x0C, b"Other")])
        # The same certificate in two keychains is dumped twice.
        dump = _pem(other) + _pem(wanted) + _pem(wanted)
        subjects = _certificate_subjects(dump, {_sha1(wanted)})
        assert [s.common_name for s in subjects] == [
            "Apple Development: Jo Doe (X83FAZ586W)"
        ]

    def test_undecodable_entries_are_skipped(self):
        wanted = _certificate_der(_APPLE_SUBJECT)
        junk = b"\x30\x02\x05\x00"
        dump = (
            "-----BEGIN CERTIFICATE-----\n!!!=\n-----END CERTIFICATE-----\n"
            + _pem(junk)
            + _pem(wanted)
        )
        subjects = _certificate_subjects(dump, {_sha1(junk), _sha1(wanted)})
        assert len(subjects) == 1

    def test_empty_dump(self):
        assert _certificate_subjects("", {"A" * 40}) == []
