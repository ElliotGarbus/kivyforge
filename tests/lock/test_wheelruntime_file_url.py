"""The desktop lock records a ``find_links`` wheel relative to the project.

pip reports a local wheel as a ``file:`` URL. On Windows its path is
``/C:/...``, which plain ``unquote`` + ``Path`` turned into a drive-relative
path, so ``pylock.windows.toml`` recorded ``Users/...`` and the build could not
find the wheel. The iOS and Android builders already converted with
``url2pathname``; this pins the shared desktop builder to the same result.
"""

from __future__ import annotations

from kivyforge.lock.wheelruntime.builder import _normalize_wheel_source


def test_file_url_inside_the_project_is_project_relative(tmp_path):
    wheel = tmp_path / "wheels" / "dep-1.0-py3-none-any.whl"
    wheel.parent.mkdir()
    wheel.write_bytes(b"")

    url, path = _normalize_wheel_source(
        None,  # type: ignore[arg-type]  # read only on the error path
        wheel.as_uri(),
        project_root=tmp_path,
    )

    assert (url, path) == (None, "wheels/dep-1.0-py3-none-any.whl")
