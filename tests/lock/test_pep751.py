"""Direct tests for the shared PEP 751 ``[[packages]]`` serialization helpers.

These primitives (``kivyforge.lock.pep751``) are the single source of truth for
the wheels section emitted/parsed by every backend. They were previously only
exercised transitively through platform round-trips; here we cover the string
escaping, url/path exclusivity, optional fields, dependency markers, the
``[packages.tool.kivyforge]`` extension, and emit -> parse fidelity directly.
"""

from __future__ import annotations

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python < 3.11
    import tomli as tomllib

import pytest

from kivyforge.lock.model import LockedPackage, LockedWheel, PackageDep
from kivyforge.lock.pep751 import (
    arr,
    b,
    emit_package,
    emit_wheel,
    parse_package,
    parse_wheel,
    s,
)


class TestScalarHelpers:
    def test_s_plain(self):
        assert s("hello") == '"hello"'

    def test_s_escapes_backslash_quote_newline_tab(self):
        assert s('a\\b"c\nd\te') == '"a\\\\b\\"c\\nd\\te"'

    def test_s_output_is_valid_toml(self):
        value = 'weird "value"\twith\nstuff \\ end'
        parsed = tomllib.loads(f"x = {s(value)}\n")
        assert parsed["x"] == value

    def test_b(self):
        assert b(True) == "true"
        assert b(False) == "false"

    def test_arr_empty(self):
        assert arr([]) == "[]"
        assert arr(()) == "[]"

    def test_arr_values(self):
        assert arr(["a", "b"]) == '["a", "b"]'

    def test_arr_escapes_members(self):
        parsed = tomllib.loads(f'x = {arr(["a\\b", "c"])}\n')
        assert parsed["x"] == ["a\\b", "c"]


class TestEmitWheel:
    def _emit(self, wheel: LockedWheel) -> dict:
        lines: list[str] = []
        emit_wheel(lines, wheel)
        # emit_wheel writes a [[packages.wheels]] header; wrap under a package.
        text = "[[packages]]\nname = \"p\"\nversion = \"1\"\n\n" + "\n".join(lines)
        return tomllib.loads(text)["packages"][0]["wheels"][0]

    def test_url_wheel(self):
        w = self._emit(
            LockedWheel(
                name="foo-1-py3-none-any.whl",
                sha256="a" * 64,
                url="https://example/foo.whl",
                upload_time="2026-01-01T00:00:00Z",
                size=1234,
            )
        )
        assert w["name"] == "foo-1-py3-none-any.whl"
        assert w["url"] == "https://example/foo.whl"
        assert w["hashes"]["sha256"] == "a" * 64
        assert w["upload-time"] == "2026-01-01T00:00:00Z"
        assert w["size"] == 1234
        assert "path" not in w

    def test_path_wheel(self):
        w = self._emit(LockedWheel(name="foo.whl", sha256="b" * 64, path="wheels/foo.whl"))
        assert w["path"] == "wheels/foo.whl"
        assert "url" not in w

    def test_optional_fields_omitted(self):
        w = self._emit(LockedWheel(name="foo.whl", sha256="c" * 64, url="https://x/f.whl"))
        assert "upload-time" not in w
        assert "size" not in w

    def test_size_zero_is_emitted(self):
        w = self._emit(LockedWheel(name="f.whl", sha256="d" * 64, url="https://x/f", size=0))
        assert w["size"] == 0


class TestEmitPackage:
    def _emit(self, pkg: LockedPackage) -> dict:
        lines: list[str] = []
        emit_package(lines, pkg)
        return tomllib.loads("\n".join(lines))["packages"][0]

    def test_minimal_package(self):
        p = self._emit(LockedPackage(name="foo", version="1.2.3", wheels=()))
        assert p["name"] == "foo"
        assert p["version"] == "1.2.3"
        assert "requires-python" not in p
        assert "marker" not in p

    def test_full_metadata(self):
        pkg = LockedPackage(
            name="foo",
            version="1.0",
            wheels=(),
            requires_python=">=3.11",
            marker="sys_platform == 'darwin'",
            dependencies=(
                PackageDep(name="bar"),
                PackageDep(name="baz", marker="python_version < '3.12'"),
            ),
        )
        p = self._emit(pkg)
        assert p["requires-python"] == ">=3.11"
        assert p["marker"] == "sys_platform == 'darwin'"
        assert p["dependencies"][0] == {"name": "bar"}
        assert p["dependencies"][1] == {
            "name": "baz",
            "marker": "python_version < '3.12'",
        }

    def test_tool_kivyforge_extension(self):
        pkg = LockedPackage(
            name="foo",
            version="1.0",
            wheels=(),
            direct_requirement=True,
            source_index="https://pypi.org/simple",
        )
        p = self._emit(pkg)
        tool = p["tool"]["kivyforge"]
        assert tool["direct_requirement"] is True
        assert tool["source_index"] == "https://pypi.org/simple"

    def test_no_tool_table_when_defaults(self):
        p = self._emit(LockedPackage(name="foo", version="1.0", wheels=()))
        assert "tool" not in p

    def test_wheels_sorted_by_name(self):
        pkg = LockedPackage(
            name="foo",
            version="1.0",
            wheels=(
                LockedWheel(name="z.whl", sha256="a" * 64, url="https://x/z"),
                LockedWheel(name="a.whl", sha256="b" * 64, url="https://x/a"),
            ),
        )
        p = self._emit(pkg)
        assert [w["name"] for w in p["wheels"]] == ["a.whl", "z.whl"]


class TestParse:
    def test_parse_wheel_url(self):
        w = parse_wheel(
            {
                "name": "foo.whl",
                "url": "https://x/foo",
                "hashes": {"sha256": "a" * 64},
                "upload-time": "t",
                "size": 5,
            }
        )
        assert w == LockedWheel(
            name="foo.whl",
            sha256="a" * 64,
            url="https://x/foo",
            upload_time="t",
            size=5,
        )

    def test_parse_wheel_path(self):
        w = parse_wheel({"name": "f.whl", "path": "w/f.whl", "hashes": {"sha256": "b" * 64}})
        assert w.path == "w/f.whl"
        assert w.url is None

    def test_parse_wheel_missing_hash_defaults_empty(self):
        # A wheel with neither url nor path violates the model invariant.
        w = parse_wheel({"name": "f.whl", "url": "https://x/f"})
        assert w.sha256 == ""

    def test_parse_package_full(self):
        pkg = parse_package(
            {
                "name": "foo",
                "version": "1.0",
                "requires-python": ">=3.11",
                "marker": "m",
                "dependencies": [
                    {"name": "bar"},
                    {"name": "baz", "marker": "python_version < '3.12'"},
                ],
                "wheels": [
                    {"name": "f.whl", "url": "https://x/f", "hashes": {"sha256": "c" * 64}}
                ],
                "tool": {"kivyforge": {"direct_requirement": True, "source_index": "idx"}},
            }
        )
        assert pkg.requires_python == ">=3.11"
        assert pkg.marker == "m"
        assert pkg.dependencies == (
            PackageDep(name="bar"),
            PackageDep(name="baz", marker="python_version < '3.12'"),
        )
        assert pkg.direct_requirement is True
        assert pkg.source_index == "idx"
        assert pkg.wheels[0].name == "f.whl"

    def test_parse_package_minimal_defaults(self):
        pkg = parse_package({"name": "foo", "version": "1.0"})
        assert pkg.dependencies == ()
        assert pkg.wheels == ()
        assert pkg.direct_requirement is False
        assert pkg.source_index is None

    def test_parse_package_missing_name_raises(self):
        with pytest.raises(KeyError):
            parse_package({"version": "1.0"})


class TestRoundTrip:
    def _round_trip(self, pkg: LockedPackage) -> LockedPackage:
        lines: list[str] = []
        emit_package(lines, pkg)
        raw = tomllib.loads("\n".join(lines))["packages"][0]
        return parse_package(raw)

    def test_url_package_round_trips(self):
        pkg = LockedPackage(
            name="foo",
            version="1.2.3",
            requires_python=">=3.11",
            marker="sys_platform == 'linux'",
            dependencies=(PackageDep(name="bar", marker="extra == 'x'"),),
            direct_requirement=True,
            source_index="https://pypi.org/simple",
            wheels=(
                LockedWheel(
                    name="foo-1.2.3-py3-none-any.whl",
                    sha256="a" * 64,
                    url="https://example/foo.whl",
                    upload_time="2026-01-01T00:00:00Z",
                    size=999,
                ),
            ),
        )
        assert self._round_trip(pkg) == pkg

    def test_path_package_round_trips(self):
        pkg = LockedPackage(
            name="local",
            version="0.1",
            wheels=(
                LockedWheel(name="local-0.1-py3-none-any.whl", sha256="e" * 64, path="wheels/local.whl"),
            ),
        )
        assert self._round_trip(pkg) == pkg

    def test_names_with_special_characters_round_trip(self):
        pkg = LockedPackage(
            name="foo",
            version="1.0",
            marker='python_version >= "3.11" and os_name == "posix"',
            wheels=(),
        )
        assert self._round_trip(pkg) == pkg
