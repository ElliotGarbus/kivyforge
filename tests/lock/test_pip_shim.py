"""Cross-target pip invocation shim (kivyforge.lock._pip_shim)."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import subprocess
import sys
import zipfile

from kivyforge.lock import _pip_shim


class TestMissingEnvVar:
    def test_returns_2_and_warns(self, monkeypatch, capsys):
        monkeypatch.delenv(_pip_shim.MARKER_ENV_VAR, raising=False)
        rc = _pip_shim.main(["install", "foo"])
        assert rc == 2
        assert "refusing to resolve" in capsys.readouterr().err

    def test_empty_string_treated_as_unset(self, monkeypatch, capsys):
        monkeypatch.setenv(_pip_shim.MARKER_ENV_VAR, "")
        rc = _pip_shim.main(["install", "foo"])
        assert rc == 2


class TestImportErrorPaths:
    def test_missing_vendored_markers_module(self, monkeypatch, capsys):
        monkeypatch.setenv(_pip_shim.MARKER_ENV_VAR, json.dumps({"os_name": "posix"}))
        monkeypatch.setitem(sys.modules, "pip._vendor.packaging.markers", None)
        rc = _pip_shim.main(["install", "foo"])
        assert rc == 3
        assert "does not vendor packaging.markers" in capsys.readouterr().err

    def test_missing_default_environment_attr(self, monkeypatch, capsys):
        from pip._vendor.packaging import markers as real_markers

        monkeypatch.setenv(_pip_shim.MARKER_ENV_VAR, json.dumps({"os_name": "posix"}))
        monkeypatch.delattr(real_markers, "default_environment", raising=False)
        rc = _pip_shim.main(["install", "foo"])
        assert rc == 3
        assert "cannot retarget marker evaluation" in capsys.readouterr().err


class TestSuccessPath:
    def test_replaces_default_environment_and_delegates_to_pip(self, monkeypatch):
        environment = {"os_name": "posix", "platform_system": "Android"}
        monkeypatch.setenv(_pip_shim.MARKER_ENV_VAR, json.dumps(environment))

        from pip._internal.cli import main as pip_main_mod

        captured = {}

        def fake_pip_main(argv):
            from pip._vendor.packaging import markers

            captured["argv"] = argv
            captured["environment"] = markers.default_environment()
            return 0

        monkeypatch.setattr(pip_main_mod, "main", fake_pip_main)

        rc = _pip_shim.main(["install", "kivy"])

        assert rc == 0
        assert captured["argv"] == ["install", "kivy"]
        assert captured["environment"] == environment

    def test_propagates_pip_exit_code(self, monkeypatch):
        monkeypatch.setenv(_pip_shim.MARKER_ENV_VAR, json.dumps({"os_name": "posix"}))
        from pip._internal.cli import main as pip_main_mod

        monkeypatch.setattr(pip_main_mod, "main", lambda argv: 1)
        assert _pip_shim.main(["install", "does-not-exist"]) == 1


class TestHostMarkers:
    def test_host_markers_runs_without_a_target_environment(self, monkeypatch):
        monkeypatch.delenv(_pip_shim.MARKER_ENV_VAR, raising=False)
        monkeypatch.setenv(_pip_shim.HOST_MARKERS_ENV_VAR, "1")
        monkeypatch.delenv(_pip_shim.SOURCE_POLICY_ENV_VAR, raising=False)
        from pip._internal.cli import main as pip_main_mod
        from pip._vendor.packaging import markers

        before = markers.default_environment
        monkeypatch.setattr(pip_main_mod, "main", lambda argv: 0)
        assert _pip_shim.main(["install", "kivy"]) == 0
        assert markers.default_environment is before


# ---------------------------------------------------------------------------
# The source filter (#86): selection rules on fake candidates
# ---------------------------------------------------------------------------


class _Page:
    def __init__(self, url):
        self.url = url

    def __str__(self):  # pip redacts here; the shim must not rely on it
        return "redacted"


class _Link:
    def __init__(self, url, page=None):
        self.url = url
        self.comes_from = _Page(page) if page else None


class _Candidate:
    def __init__(self, name, url, page=None):
        self.name = name
        self.link = _Link(url, page)


PYPI = "https://pypi.org/simple/"


def _policy(**data):
    data.setdefault("rank", [["pypi", PYPI]])
    return _pip_shim._Policy(data)


def _names(selected):
    return [c.name for c, _source in selected]


class TestSelect:
    def test_local_name_keeps_only_find_links(self, tmp_path):
        wheels = tmp_path / "wheels"
        wheels.mkdir()
        local = _Candidate("local", (wheels / "kivy-1-py3-none-any.whl").as_uri())
        index = _Candidate("pypi", "https://files/kivy-2.whl", PYPI + "kivy/")
        policy = _policy(find_links=[str(wheels)], local_names=["kivy"])
        assert _names(policy.select("kivy", [local, index])) == ["local"]

    def test_pinned_name_keeps_only_its_index_even_over_local(self, tmp_path):
        wheels = tmp_path / "wheels"
        wheels.mkdir()
        local = _Candidate("local", (wheels / "kivy-1-py3-none-any.whl").as_uri())
        mobile = _Candidate(
            "mobile", "https://gh/kivy.whl", "https://m.example/simple/kivy/"
        )
        pypi = _Candidate("pypi", "https://files/kivy.whl", PYPI + "kivy/")
        policy = _policy(
            find_links=[str(wheels)],
            local_names=["kivy"],
            rank=[["mobile", "https://m.example/simple/"], ["pypi", PYPI]],
            pins={"kivy": "mobile"},
        )
        assert _names(policy.select("kivy", [local, mobile, pypi])) == ["mobile"]

    def test_explicit_index_serves_only_pinned_names(self):
        explicit = _Candidate(
            "x", "https://x/a.whl", "https://school.example/simple/a/"
        )
        pypi = _Candidate("pypi", "https://files/a.whl", PYPI + "a/")
        policy = _policy(explicit=[["school", "https://school.example/simple"]])
        assert _names(policy.select("a", [explicit, pypi])) == ["pypi"]

    def test_lowest_ranked_first_so_pip_takes_the_first_listed(self):
        a = _Candidate("a", "https://f/a.whl", "https://a.example/simple/p/")
        b = _Candidate("b", "https://f/b.whl", "https://b.example/simple/p/")
        pypi = _Candidate("pypi", "https://f/p.whl", PYPI + "p/")
        unknown = _Candidate("unknown", "https://f/u.whl", "https://redirected/p/")
        policy = _policy(
            rank=[
                ["extra-1", "https://a.example/simple/"],
                ["extra-2", "https://b.example/simple/"],
                ["pypi", PYPI],
            ],
        )
        # pip takes the *last* of equals, so the first-listed index goes last;
        # a candidate from no configured source is kept, ranked lowest.
        assert _names(policy.select("p", [a, pypi, unknown, b])) == [
            "unknown",
            "pypi",
            "b",
            "a",
        ]

    def test_source_uses_the_page_url_not_its_redacted_str(self):
        policy = _policy(rank=[["corp", "https://u:secret@corp/simple/"]])
        link = _Link("https://files/x.whl", "https://u:secret@corp/simple/x/")
        assert policy.source(link) == "https://u:secret@corp/simple/"


class TestExcludeFilter:
    class _Req:
        def __init__(self, project_name):
            self.project_name = project_name

    def test_drops_excluded_dependencies_only(self, monkeypatch):
        from pip._internal.resolution.resolvelib.provider import PipProvider

        reqs = [self._Req("kivy"), self._Req("pycairo"), self._Req("idna")]
        monkeypatch.setattr(
            PipProvider, "get_dependencies", lambda self, candidate: iter(reqs)
        )
        assert _pip_shim._install_exclude_filter(frozenset({"pycairo"})) == ""
        kept = PipProvider.get_dependencies(object(), "candidate")  # type: ignore[arg-type]
        assert [r.project_name for r in kept] == ["kivy", "idna"]

    def test_missing_internal_exits_97(self, monkeypatch, capsys):
        from pip._internal.index.package_finder import PackageFinder
        from pip._internal.resolution.resolvelib.provider import PipProvider

        # main() patches it first; this restores it after the test.
        monkeypatch.setattr(
            PackageFinder, "find_all_candidates", PackageFinder.find_all_candidates
        )
        monkeypatch.setenv(_pip_shim.HOST_MARKERS_ENV_VAR, "1")
        monkeypatch.setenv(
            _pip_shim.SOURCE_POLICY_ENV_VAR,
            json.dumps({"kivyforge": "9.9", "exclude": ["pycairo"]}),
        )
        monkeypatch.delattr(PipProvider, "get_dependencies")
        from pip._internal.cli import main as pip_main_mod

        monkeypatch.setattr(pip_main_mod, "main", lambda argv: 0)
        rc = _pip_shim.main(["install", "kivy"])
        assert rc == _pip_shim.SOURCE_FILTER_UNAVAILABLE
        assert "PipProvider.get_dependencies" in capsys.readouterr().err


class TestFilterUnavailable:
    def test_missing_internal_exits_97_and_says_report_it(self, monkeypatch, capsys):
        from pip._internal.index import package_finder

        monkeypatch.setenv(_pip_shim.HOST_MARKERS_ENV_VAR, "1")
        monkeypatch.setenv(
            _pip_shim.SOURCE_POLICY_ENV_VAR, json.dumps({"kivyforge": "9.9"})
        )
        monkeypatch.delattr(package_finder.PackageFinder, "find_all_candidates")
        rc = _pip_shim.main(["install", "kivy"])
        assert rc == _pip_shim.SOURCE_FILTER_UNAVAILABLE
        err = capsys.readouterr().err
        assert "kivyforge 9.9 cannot apply its source rules" in err
        assert "please report it" in err


# ---------------------------------------------------------------------------
# The canary: the filter applied by the real pip, against local file:// indexes
# whose files live in a different directory than their pages (as PyPI's live on
# files.pythonhosted.org and kivy-mobile-wheels' on GitHub releases). If a pip
# release breaks the patch, these fail instead of a user's lock.
# ---------------------------------------------------------------------------


def _make_wheel(directory, name, version, tag="py3-none-any", requires=()):
    directory.mkdir(parents=True, exist_ok=True)
    dist_info = f"{name}-{version}.dist-info"
    requires_dist = "".join(f"Requires-Dist: {r}\n" for r in requires)
    files = {
        f"{name}/__init__.py": "",
        f"{dist_info}/METADATA": (
            f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n{requires_dist}"
        ),
        f"{dist_info}/WHEEL": f"Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: {tag}\n",
    }
    record = []
    for path, text in files.items():
        digest = hashlib.sha256(text.encode()).digest()
        b64 = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
        record.append(f"{path},sha256={b64},{len(text.encode())}")
    files[f"{dist_info}/RECORD"] = "\n".join([*record, f"{dist_info}/RECORD,,"]) + "\n"
    out = directory / f"{name}-{version}-{tag}.whl"
    with zipfile.ZipFile(out, "w") as zf:
        for path, text in files.items():
            zf.writestr(path, text)
    return out


def _make_index(root, wheels):
    """A PEP 503 tree at root/simple whose links point into root/files."""
    files = root / "files"
    files.mkdir(parents=True, exist_ok=True)
    by_project: dict[str, list] = {}
    for wheel in wheels:
        target = files / wheel.name
        target.write_bytes(wheel.read_bytes())
        by_project.setdefault(wheel.name.split("-")[0].lower(), []).append(target)
    for project, items in by_project.items():
        page = root / "simple" / project
        page.mkdir(parents=True, exist_ok=True)
        links = "".join(
            f'<a href="{w.as_uri()}#sha256={hashlib.sha256(w.read_bytes()).hexdigest()}">'
            f"{w.name}</a><br/>"
            for w in items
        )
        (page / "index.html").write_text(f"<html><body>{links}</body></html>")
    return (root / "simple").as_uri() + "/"


def _resolve(tmp_path, requirement, *, index_url, policy, extras=(), find_links=()):
    report = tmp_path / "report.json"
    record = tmp_path / "record.json"
    cmd = [
        sys.executable,
        _pip_shim.__file__,
        "install",
        "--no-input",
        "--disable-pip-version-check",
        "--no-cache-dir",
        "--dry-run",
        "--ignore-installed",
        "--only-binary=:all:",
        "--quiet",
        "--report",
        str(report),
        "--index-url",
        index_url,
    ]
    for url in extras:
        cmd += ["--extra-index-url", url]
    for link in find_links:
        cmd += ["--find-links", str(link)]
    cmd.append(requirement)
    env = dict(os.environ)
    env["PIP_CONFIG_FILE"] = os.devnull
    env[_pip_shim.HOST_MARKERS_ENV_VAR] = "1"
    env[_pip_shim.SOURCE_POLICY_ENV_VAR] = json.dumps({**policy, "record": str(record)})
    proc = subprocess.run(
        cmd, capture_output=True, text=True, env=env, stdin=subprocess.DEVNULL
    )
    if proc.returncode != 0:
        return proc.returncode, None, None, None
    install = json.loads(report.read_text(encoding="utf-8"))["install"][0]
    url = install["download_info"]["url"]
    sources = json.loads(record.read_text(encoding="utf-8"))
    return 0, install["metadata"]["version"], url, sources.get(url)


class TestRealPipCanary:
    @staticmethod
    def _world(tmp_path):
        built = tmp_path / "built"
        pypi = _make_index(
            tmp_path / "pypi",
            [
                _make_wheel(built / "pypi", "demo", "1.0"),
                _make_wheel(built / "pypi", "demo", "2.0"),
            ],
        )
        a = _make_index(tmp_path / "a", [_make_wheel(built / "a", "demo", "2.0")])
        b = _make_index(tmp_path / "b", [_make_wheel(built / "b", "demo", "2.0")])
        wheels = tmp_path / "wheels"
        _make_wheel(wheels, "demo", "1.0")
        return pypi, a, b, wheels

    def test_local_wheel_wins_over_a_newer_index_version(self, tmp_path):
        pypi, _a, _b, wheels = self._world(tmp_path)
        rc, version, url, source = _resolve(
            tmp_path,
            "demo",
            index_url=pypi,
            find_links=[wheels],
            policy={
                "find_links": [str(wheels)],
                "local_names": ["demo"],
                "rank": [["pypi", pypi]],
            },
        )
        assert rc == 0
        assert version == "1.0"
        assert source == _pip_shim.FIND_LINKS
        assert url is not None
        assert "/wheels/" in url

    def test_first_listed_index_wins_a_tie_and_is_recorded(self, tmp_path):
        pypi, a, b, _wheels = self._world(tmp_path)
        for first, second in ((a, b), (b, a)):
            rc, version, url, source = _resolve(
                tmp_path,
                "demo",
                index_url=pypi,
                extras=[a, b],
                policy={"rank": [["x1", first], ["x2", second], ["pypi", pypi]]},
            )
            assert rc == 0
            assert version == "2.0"
            assert source == first
            # The file is not under its page's URL: identified by comes_from.
            assert url is not None
            assert "/files/" in url

    def test_pin_wins_over_local_and_explicit_index_serves_it(self, tmp_path):
        pypi, a, _b, wheels = self._world(tmp_path)
        rc, version, _url, source = _resolve(
            tmp_path,
            "demo",
            index_url=pypi,
            extras=[a],
            find_links=[wheels],
            policy={
                "find_links": [str(wheels)],
                "local_names": ["demo"],
                "rank": [["pypi", pypi]],
                "explicit": [["school", a]],
                "pins": {"demo": "school"},
            },
        )
        assert rc == 0
        assert version == "2.0"
        assert source == a

    def test_pin_to_an_index_without_the_package_fails(self, tmp_path):
        pypi, _a, _b, _wheels = self._world(tmp_path)
        empty = _make_index(
            tmp_path / "empty", [_make_wheel(tmp_path / "e", "other", "1.0")]
        )
        rc, *_rest = _resolve(
            tmp_path,
            "demo",
            index_url=pypi,
            extras=[empty],
            policy={
                "rank": [["pypi", pypi]],
                "explicit": [["empty", empty]],
                "pins": {"demo": "empty"},
            },
        )
        assert rc not in (0, _pip_shim.SOURCE_FILTER_UNAVAILABLE)


class TestRealPipExcludeCanary:
    """An excluded dependency is never looked for, so one that has no wheel
    for the target no longer fails the resolve (#190)."""

    @staticmethod
    def _installed(tmp_path, *, exclude):
        built = tmp_path / "built"
        index = _make_index(
            tmp_path / "pypi",
            [
                _make_wheel(built, "app", "1.0", requires=["pycairo", "kept"]),
                _make_wheel(built, "kept", "1.0"),
                # "nowhere" has no wheel at all; "cairotail" is needed only by
                # pycairo, so excluding pycairo drops it too.
                _make_wheel(built, "pycairo", "1.0", requires=["cairotail", "nowhere"]),
                _make_wheel(built, "cairotail", "1.0"),
            ],
        )
        report = tmp_path / "report.json"
        cmd = [
            sys.executable,
            _pip_shim.__file__,
            "install",
            "--no-input",
            "--disable-pip-version-check",
            "--no-cache-dir",
            "--dry-run",
            "--ignore-installed",
            "--only-binary=:all:",
            "--quiet",
            "--report",
            str(report),
            "--index-url",
            index,
            "app",
        ]
        env = dict(os.environ)
        env["PIP_CONFIG_FILE"] = os.devnull
        env[_pip_shim.HOST_MARKERS_ENV_VAR] = "1"
        env[_pip_shim.SOURCE_POLICY_ENV_VAR] = json.dumps(
            {"rank": [["pypi", index]], "exclude": exclude}
        )
        proc = subprocess.run(
            cmd, capture_output=True, text=True, env=env, stdin=subprocess.DEVNULL
        )
        if proc.returncode != 0:
            return None
        install = json.loads(report.read_text(encoding="utf-8"))["install"]
        return sorted(item["metadata"]["name"] for item in install)

    def test_without_exclude_the_missing_dependency_fails(self, tmp_path):
        assert self._installed(tmp_path, exclude=[]) is None

    def test_excluded_dependency_is_never_looked_for(self, tmp_path):
        assert self._installed(tmp_path, exclude=["pycairo"]) == ["app", "kept"]
