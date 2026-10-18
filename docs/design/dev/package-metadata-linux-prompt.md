# Agent prompt — the app's own package metadata on Linux

> **Run this on Linux or WSL2**, from a clone on the Linux filesystem. Written
> 2026-10-18. Closes the last platform in layer 5 of
> [`package-metadata-proposal.md`](package-metadata-proposal.md) (Q7, "Done
> when"). Needs the metaprobe driver's Windows changes, so it needs PR #142:
> start from `main` if #142 is merged, otherwise from branch
> `windows-metaprobe`.
>
> Point the agent at this file, or copy the "Prompt" section.

## Background — what is proven, and what is not

kivyforge writes the app's own `<name>-<version>.dist-info` into every bundle,
so `importlib.metadata` inside a packaged app finds the app's name, version and
entry points (#122). Layer 3 of the proposal is a probe app,
`tests/fixtures/apps/metaprobe/`, and a driver,
`tests/integration/test_app_metadata_devices.py`, which locks, builds,
launches the app and checks what it reports.

| Platform | Status |
|---|---|
| macOS, iOS simulator, Android emulator | layer 3 passes on a Mac, 2026-10-14 |
| iOS device, release archive | passes, 2026-10-14 (proposal I8) |
| Windows | passes, 2026-10-17 (proposal I9), after two Windows bugs were fixed |
| **Linux** | **never run**: only layer 1's hermetic tests cover where the metadata is copied |

The Windows run is the model for this one, and a warning. Commit `dd51c18c`
added the `windows` target, and its first two runs failed on real kivyforge
bugs, not on the metadata step: a lock path that lost its drive letter, and
the launcher putting `app` on `sys.path` twice so the app's distribution was
found twice. Linux's `AppRun` sets up `sys.path` the way macOS does, and macOS
passes, but nobody has checked.

---

## Prompt

You are running the package-metadata layer 3 probe on Linux for the first
time. That means adding a `linux` target to the driver, running every variant,
fixing what fails, and logging the result. **Record what you observe**, with
commands and output verbatim. Read `AGENTS.md` first: its rules on commits,
tests and the results log apply.

**Work on the Linux filesystem, not `/mnt/c`.** Under WSL2, a checkout on a
Windows drive has the wrong permission bits and is slow. Record whether this is
WSL2 or a native Linux host. The probe opens no window, so WSLg does not matter.

### Step 0 — environment

```bash
git fetch origin && git status
git switch -c linux-metaprobe origin/main      # or origin/windows-metaprobe if #142 is not merged
grep -n '"windows"' tests/integration/test_app_metadata_devices.py | head -3   # must find the windows target
python3 -m venv .venv && . .venv/bin/activate && pip install -e ".[dev]"
uname -a; head -2 /etc/os-release; grep -qi microsoft /proc/version && echo WSL2 || echo native
python --version; git --version
```

Record the output. The run needs the network (the CPython runtime, wheels,
setuptools for the dev install) and `git`.

### Step 1 — add the `linux` target

Follow how `dd51c18c` added `windows`. Change only what Linux needs:

1. **Fixture** (`tests/fixtures/apps/metaprobe/pyproject.toml`): add an
   overlay. No Kivy is needed: the probe runs a script and exits, like macOS
   and Windows.

   ```toml
   [tool.kivy.linux]
   schema_version = 1
   app_id = "org.kivyforge.metaprobe"
   archs = ["x86_64"]
   find_links = ["wheels"]

   [tool.kivy.linux.python]
   version = "3.13.14"
   ```

   Update the dependency comment that names the platforms needing no Kivy.

2. **Driver** (`tests/integration/test_app_metadata_devices.py`):
   - Add `"linux"` to `PLATFORMS`, `LOCK_PLATFORM` and `RELEASE_PLATFORMS`, and
     to the module docstring.
   - **Collecting the report.** `run -p linux` runs `AppRun` in the foreground
     with stdout inherited, so read it as macOS does: `_kf(project, "run", "-p",
     "linux", [--release], env=...)`, then `_report_from_lines(proc.stdout)`.
     Set `METAPROBE_OUT` to a directory beside the project, as `_macos_env`
     does, so the probe does not write into the home directory. If stdout turns
     out not to carry the `METAPROBE` line, fall back to reading the file, as
     Windows does, and say why in a comment.
   - **`_built_with_json`.** Run `build -p linux --json`, take the `folder`
     artifact (the AppDir), and launch its `AppRun` directly, as `_macos_launch`
     runs the `.app`'s executable.
   - **Dynamic version.** A Linux build records the version nowhere inside the
     AppDir: only the packaged `.AppImage` file name carries it. So for
     `linux`, check the report's version against `data.version`, which
     `_assert_generated` already does, and skip the "shipped" comparison, with
     a comment saying why. Do not invent a version file to compare against.
   - **Host check** in `platform_project`: fail with "`--metaprobe linux needs a
     Linux host`" unless `sys.platform.startswith("linux")`.
3. **`tests/conftest.py`**: add `linux` to the `--metaprobe` help text.

Then check the hermetic suite still passes:

```bash
ruff check kivyforge tests && ruff format --check kivyforge tests && pyright
pytest -q
```

### Step 2 — run the variants

```bash
pytest tests/integration/test_app_metadata_devices.py --metaprobe linux \
  --no-cov -p no:cacheprovider -rA --tb=short 2>&1 | tee /tmp/metaprobe-linux.log
```

Expect six `linux` cases: dev-install `egg-info`, no `egg-info`, stale
`egg-info`, release (`main.pyc`), dynamic version, dynamic entry points. Every
other platform's case skips. On failure, the driver prints the app's full
report above the traceback: keep it.

### Step 3 — when something fails

Decide whether the probe or kivyforge is wrong, and say which in the report.

- **A driver bug** (wrong path, wrong artifact kind): fix the driver.
- **A kivyforge bug**: fix it in `kivyforge/`, and add a hermetic regression
  test that **fails without the fix**. Show that it fails: stash the fix, run
  the test, restore. On Windows these were
  `tests/lock/test_wheelruntime_file_url.py` and
  `test_app_is_on_sys_path_once_and_first`.
- **Never loosen an assertion to make a run pass.** If an assertion is wrong
  for Linux, as the "shipped" version check is, say why in a comment and keep
  every other platform's check intact.

Rerun Step 2 after each fix, until all six pass or you are blocked. Keep every
run's result for the log.

### Step 4 — record and commit

1. **`docs/design/dev/test-matrix.md` §7:** append one row in the table's
   format: date, `Linux x86_64 (the app's own package metadata, #122)`,
   `T2 + T4 (local), package-metadata layer 5`, the host (distro, WSL2 or
   native, Python, kivyforge commit), and the result. A run that failed first
   is logged as "FAIL, then PASS", with each failure and its fix.
2. **`docs/design/dev/package-metadata-proposal.md`:** add an `I10` row after
   `I9` in section 11. In section 10, update Q7 to say Linux is done. Update
   layer 5 in section 5 and the status note at the top. Only the #122
   reporter's own app should remain open.
3. **`CHANGELOG.md`:** only if you fixed a bug a user could hit, under
   `[Unreleased]`, with a migration note.
4. **Commit** on `linux-metaprobe`, with a message that explains why. Do not
   commit build output or a lock. **Do not push**: report back instead.

### Report

Start with the defects, then:

- an environment table;
- each step's command and verbatim output (trim long logs, keep the failures);
- the final per-variant results;
- the commit hash, and anything you could not do and why.
