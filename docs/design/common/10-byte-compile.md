# 10 — Byte-compiling: which interpreter writes the `.pyc`

Every backend can ship its Python payload as `.pyc`. The mechanics are shared
(`kivyforge/bundle/pycompile.py`); what differs per platform is which trees are
compiled, which the platform specs list. This page is the one description of
how the compiler is chosen. The platform specs link here rather than repeating
it, so a change to the search updates this page alone.

## The settings

Each platform has `byte_compile` and `strip_source` in its `build_settings`
table: `[tool.kivy.ios.python.build_settings]`,
`[tool.kivy.android.build_settings]`, and `[tool.kivy.<macos|linux|windows>.build_settings]`.
Each is `"release"` (the default: release builds only, as each platform defines
them) or an explicit `true` / `false`. `strip_source` is ignored while
`byte_compile` is off, because stripping sources with no `.pyc` beside them
would ship a payload that imports nothing.

The two spellings of "on" mean different things, and the difference decides
what happens when no interpreter is found (below):

- `"release"` means *when it makes sense*. A build nobody configured is never
  broken by the absence of an interpreter nobody asked for.
- `true` means *I insist*. Silently shipping source would leave the user
  believing the payload was compiled.

## What a compiler must be

A `.pyc` loads only in the CPython whose magic number wrote it. The magic number
is fixed per **minor version** from the first release candidate on, and does
not depend on architecture or OS. So a compiler must be:

- **the same minor** as the runtime the platform ships, read from that
  platform's lock (any patch release will do: a host 3.15.0 compiles for a
  shipped 3.15.2);
- **a final release** (`sys.version_info.releaselevel == "final"`). Alphas and
  betas change the magic number, so their output fails to import once
  `strip_source` has removed the source. Release candidates are excluded too:
  the freeze makes them safe in principle, but the margin isn't worth it when
  the fallback is shipping readable source.

## The search

`select_compiler()`, then `find_interpreter()`, try in order:

1. **The staged interpreter** the bundle ships, on desktop only, and only when
   it runs natively on this host (target arch == host arch; kivyforge never
   depends on emulation). iOS's `Python.xcframework` is a library with no
   executable, and Android's runtime is built for the device, so neither has
   this step.
2. **kivyforge's own interpreter**, if it is a final release of the minor.
3. **`py -3.X`**, Windows only. The PEP 397 launcher is the reliable way to
   reach a specific version there.
4. **`python3.X`, `python3`, then `python` on `PATH`.**
5. **`uv python find --no-project --no-python-downloads 3.X`**, only when uv is
   installed. A uv-managed Python is often not on `PATH`. `--no-project` keeps
   the project's `.python-version` and `requires-python` out of the answer, and
   `--no-python-downloads` keeps the search off the network. uv is never
   required: without it, this step leaves no trace.

Steps 3 to 5 each run the candidate once (`stdin=DEVNULL`, 30 s timeout) and
read its `sys.version_info`. The first that is the right minor and final is
used.

In practice, iOS and Android always use steps 2 to 5. Desktop reaches them only
when the staged interpreter can't run here: a Linux `aarch64` target built on an
x86_64 host, the one cross-arch desktop build (macOS ships only arm64 and
Windows only amd64), or a missing staged interpreter.

A final CPython of the right minor that the search misses (pyenv, conda, a
python.org framework that isn't linked, `/opt/python/3.15` in a CI image) is
found by putting its directory first on `PATH`:

```bash
PATH=/opt/python/3.15/bin:$PATH kivyforge package -p ios
```

## When nothing qualifies

Every candidate looked at is recorded, so the failure can say what was searched
(`pycompile.no_interpreter()`, one wording for every call site and `doctor`):

```
Error: [tool.kivy.ios.python.build_settings].byte_compile = true, but no final CPython 3.15 found (this project ships 3.15.0).
  The .pyc files must be written by a final CPython 3.15 on this machine. Looked at:
    this interpreter (/path/to/.venv/bin/python3.14): 3.14.7
    python3.15: not found
    python3: 3.9.6
    python: not found
  Fix: install any final CPython 3.15.x (for example `uv python install 3.15`, or python.org) so python3.15 is on PATH, or set byte_compile = false in [tool.kivy.ios.python.build_settings].
```

A pre-release of the right minor, if one was found, gets its own line saying
why it doesn't count; otherwise pre-releases aren't mentioned.

| Setting | Outcome | Code | Exit |
|---|---|---|---|
| `"release"` | The build ships source, prints the message on stderr, and finishes `ok` with a warning. | `KF-BYTECOMPILE-NO-INTERP` (warning) | 0 |
| `true` | The build fails. | `KF-BYTECOMPILE-NO-INTERP` (error), `context.tool` = `python3.X` | 3 |

Exit 3 because what's missing is on the machine, not in the config
(`report/exit_codes.py`).

`doctor` runs the same search through its probe, so it can't disagree with the
build. Its byte-compile check passes and names the interpreter, or reports
`FAIL` (`true`) or `WARN` (`"release"`) with the same list and `Fix:` line as
its hint, and the same code.

## What is written

Fixed for every platform (`pycompile.py`'s module docstring has the reasons):

- **Hash-based, unchecked invalidation** (PEP 552), so importing doesn't `stat`
  the source, and no mtime goes into a `.pyc`.
- **Payload-relative paths**, so no host path leaks into the artifact and
  identical inputs give identical output on any machine.
- **Optimization level 0.**
- **Layout.** Keeping sources, `.pyc` go in `__pycache__/`. Stripping sources,
  they go beside where the `.py` was (the legacy layout), because sourceless
  imports never look in `__pycache__/`.

## Code

- `kivyforge/bundle/pycompile.py`: `select_compiler`, `find_interpreter`,
  `no_interpreter`, `byte_compile`.
- The call sites, one per payload: `platforms/ios/staging.py` (app sources),
  `artifacts/collect.py` (iOS pip-deps), `platforms/android/cli.py`, and the
  `bundle.py` of macOS, Linux and Windows.
- `doctor/checks_common.py::check_byte_compile`.

A proposed change to this search, a command that installs a host CPython for
byte-compiling, is in
[`host-python-download-proposal.md`](../dev/host-python-download-proposal.md).
It is not implemented; when it is, this page gains its step.
