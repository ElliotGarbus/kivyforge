---
title: Drive kivyforge from CI or an agent
sources:
  - AGENTS.md
  - kivyforge/cli/lock.py
  - kivyforge/cli/capabilities.py
  - kivyforge/cli/doctor.py
  - kivyforge/cli/status.py
  - kivyforge/cli/run.py
  - kivyforge/report/exit_codes.py
  - kivyforge/report/diagnostics.py
  - .github/workflows/kivyforge.yml
  - docs/design/common/02-cli-and-platform-resolution.md
---

# Drive kivyforge from CI or an agent

kivyforge is designed to run unattended. Every verb except `run` can print a
single JSON document on stdout, every failure has a stable exit code and a `KF-*`
diagnostic code, and no verb waits for input. This page shows the tools that
make that work, a complete GitHub Actions workflow that uses them, and how to
instruct a coding agent so it builds your app the same way.

## Before you begin

- [Install kivyforge](../../get-started/install.md) in the CI environment, or
  on the machine where the agent runs.
- Commit the `pylock.<platform>.toml` for each target you build in CI. See
  [Lockfiles](../../concepts/lockfiles.md).
- Use a CI runner or a machine whose operating system can build the target.
  See [Which host builds which target](../../get-started/hosts.md).

## The tools for automated callers

| Tool | What it answers | Why CI needs it | Why an agent needs it |
|---|---|---|---|
| `kivyforge capabilities --json` | Which targets, formats and verbs this version has, and which hosts build each target. | Fails fast when a matrix entry asks for a target the runner can't build. | Tells the agent what it can do on this machine before it tries. |
| `--json` on every verb but `run` | One envelope on stdout with `ok`, `data` and `diagnostics`. | Reads the produced files from `data.artifacts` and turns diagnostics into annotations. | Gives the agent facts to act on instead of log text to guess at. |
| Exit codes and `KF-*` codes | The kind of failure, then its exact cause. | Tells a config error from a missing tool, a stale lock, or a failed build. | Maps each failure to one next action, such as re-locking. |
| `kivyforge lock --check` | Whether the committed lock still matches `pyproject.toml`. | Fails a pull request that changed dependencies without re-locking. | Confirms a dependency edit is complete before the agent builds. |
| `kivyforge doctor --json` | Whether this machine and project are ready to build the target. | Fails the job early, with the missing tool named, before a long build. | Lists what is missing and the command that fixes it, under `remediation`. |
| `kivyforge status --json` | The app's identity, Python version and lock state. | Records what the job is about to build. | Gives the agent a cheap first look at the project. |
| `run --no-follow`, `run --smoke` | A launch that returns on Android, and a contract smoke test. | Runs the app on an emulator and passes or fails. | Lets the agent check the app on a device without a command that never ends. |

The rest of this page covers each tool, then puts them together.

## Ask what this version can do

Run `capabilities` before you assume anything about the host or the installed
version. It needs no project, lock, or network access.

```bash
kivyforge capabilities --json
```

The envelope's `data` lists:

- `platforms`: each target's architectures, package formats, default format,
  which host operating systems can build it, and, as `verbose`, whether it acts
  on `-v`.
- `verbs`: every verb, and whether it accepts `--json` and `-v` (`json`,
  `verbose`). See [Verbose output](../../reference/cli.md#verbose-output).
- `exit_codes` and `diagnostic_codes`: the full vocabularies.

## Get machine-readable output

Add `--json` to any verb except `run`. stdout then contains exactly one JSON
envelope. Progress and tool logs stay on stderr.

```bash
kivyforge package -p android --json > package.json
```

Read the produced files from `data.artifacts` instead of guessing the output
layout. Each entry has a `path`, relative to the project root with forward
slashes, and a `kind`. See [JSON output](../../reference/json-output.md).

## Branch on the exit code, then the diagnostic code

The exit code tells you the kind of failure. `diagnostics[].code` names the
specific cause.

| Exit code | Meaning | What to do |
|---|---|---|
| `0` | Success | Continue. Check `diagnostics` for warnings. |
| `1` | Configuration or user error | Fix `pyproject.toml` or the command, then retry. |
| `3` | Toolchain or host missing | Install the named tool, or use a host that can build the target, then retry unchanged. For `KF-HOST-PYTHON-FETCH`, retry with network access. |
| `4` | Lock missing, unreadable, or out of date | Re-lock with `kivyforge lock -p PLATFORM`. |
| `5` | Build failed | Read the build log on stderr. |

Replace `PLATFORM` with the target, for example `android`.

Exit code `2` is a command-line usage error, such as a mistyped flag. kivyforge
never uses it for its own failures. For every `KF-*` code, see
[Exit and diagnostic codes](../../reference/codes.md).

!!! note
    Diagnostics on an `ok: true` run are warnings, not failures. For example, a
    package that shipped unsigned, or a byte-compile step that fell back to
    shipping source. Don't treat them as a failed build.

## Check the lock before you build

`lock --check` re-resolves the dependencies, compares the result with the
committed lock, and writes nothing:

```bash
kivyforge lock -p linux --check
```

It exits `4` if the lock is out of date (`KF-LOCK-DRIFT`), missing
(`KF-LOCK-MISSING`), or unreadable (`KF-LOCK-UNREADABLE`). Because it resolves
again, it needs network access. It keeps the locked versions while it does, so a
new upstream release alone doesn't fail the check. The check is meaningful only
against a committed lock.

With `--json`, `data.diff` lists what changed:

```json
{
  "command": "lock",
  "platform": "android",
  "ok": false,
  "data": {
    "lockfile": "pylock.android.toml",
    "action": "checked",
    "in_sync": false,
    "diff": ["  + humanize 4.17.0 (added)"]
  },
  "diagnostics": [
    {
      "code": "KF-LOCK-DRIFT",
      "severity": "error",
      "message": "lock is stale; run `kivyforge lock`.",
      "remediation": "kivyforge lock -p android"
    }
  ]
}
```

`build` and `package` also refuse a lock that no longer matches
`pyproject.toml`. `--no-verify-lock` skips that check. Use it only when a CI step
deliberately edits `pyproject.toml` after the lock was resolved.

## Run kivyforge in CI

In CI, each tool replaces something you would otherwise script by hand:

- **`lock --check`** keeps the lock honest. A pull request that edits
  dependencies without re-locking fails in seconds with `KF-LOCK-DRIFT` and
  the diff, instead of building something nobody reviewed.
- **`doctor`** turns a missing JDK or SDK package into a short, named failure
  before a long build starts. It exits `3` only when a check reports FAIL.
  WARN results, such as no display or no attached device on a headless runner,
  don't change its exit code.
- **The exit code** tells you who has to act. Exit `1` and `4` need a commit,
  exit `3` needs a runner change, and only exit `5` needs someone to read the
  build log.
- **`data.artifacts`** names exactly what this run produced, so the upload step
  never depends on how kivyforge names files. That matters for names that carry
  more than the version, such as the ABI of an Android package made with `--abi`.
- **`diagnostics`** become annotations on the pull request. Warnings, such as
  an unsigned Windows bundle, stay visible without failing the build.

### Example: a GitHub Actions workflow

This workflow packages a Linux AppImage and a Windows bundle on every push and
pull request. For Android, it packages a debug APK on pull requests and a
signed release App Bundle (AAB) on pushes, where the signing secrets are
available.

It runs every packaging step through one small script, `ci/kf.py`. Commit it
next to your `pyproject.toml`:

```python
"""Run a kivyforge verb in GitHub Actions.

Usage: python ci/kf.py build|package [ARGS...]

Runs the verb with --json, turns its diagnostics into annotations, writes the
artifact paths to the step output "artifacts", and exits with kivyforge's own
exit code.
"""

import json
import os
import subprocess
import sys

NEXT_STEP = {
    1: "kivyforge rejected the configuration or the command.",
    2: "The command line has a usage error, such as a mistyped flag.",
    3: "This runner is missing a tool, or can't build this target.",
    4: "The committed lock is out of date. Re-lock locally and commit it.",
    5: "The platform build tool failed. Read its log above.",
}


def escape(text):
    return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def main(args):
    # stdout is the envelope. stderr, the build log, goes straight to the job log.
    proc = subprocess.run(
        ["kivyforge", *args, "--json"], stdout=subprocess.PIPE, text=True
    )
    with open(f"kf-{args[0]}.json", "w", encoding="utf-8") as f:
        f.write(proc.stdout)
    try:
        envelope = json.loads(proc.stdout)
    except ValueError:  # exit 2, a usage error, prints no envelope
        envelope = {"data": {}, "diagnostics": []}

    for diag in envelope["diagnostics"]:
        level = {"error": "error", "warning": "warning"}.get(diag["severity"], "notice")
        text = diag["message"]
        if "remediation" in diag:
            text += " Fix: " + diag["remediation"]
        print(f"::{level} title={diag['code']}::{escape(text)}")

    if "GITHUB_OUTPUT" in os.environ:
        paths = [a["path"] for a in envelope["data"].get("artifacts", [])]
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as f:
            f.write("artifacts<<KF_EOF\n")
            f.writelines(path + "\n" for path in paths)
            f.write("KF_EOF\n")

    if proc.returncode:
        reason = NEXT_STEP.get(proc.returncode, "kivyforge failed.")
        print(f"::error::{reason} (exit {proc.returncode})")
    return proc.returncode


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
```

Then add the workflow as `.github/workflows/app.yml`:

```yaml
name: app

on:
  push:
    branches: [main]
  pull_request:

permissions:
  contents: read

defaults:
  run:
    shell: bash

env:
  # Raises the GitHub API rate limit for `lock`.
  GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}

jobs:
  desktop:
    name: Package ${{ matrix.platform }}
    runs-on: ${{ matrix.os }}
    strategy:
      fail-fast: false
      matrix:
        include:
          - platform: linux
            os: ubuntu-latest
          - platform: windows
            os: windows-latest
    env:
      PLATFORM: ${{ matrix.platform }}
    steps:
      - uses: actions/checkout@v6
      - uses: actions/setup-python@v6
        with:
          python-version: '3.13'
      - run: pip install kivyforge
      - name: Fail early if this runner can't build the target
        run: |
          kivyforge capabilities --json > capabilities.json
          python - <<'EOF'
          import json, os, platform, sys
          data = json.load(open("capabilities.json"))["data"]
          [target] = [p for p in data["platforms"] if p["name"] == os.environ["PLATFORM"]]
          if not target["hosts"][platform.system()]:
              sys.exit(f"{target['name']} can't be built on {platform.system()}")
          EOF
      - name: Restore the kivyforge download cache
        uses: actions/cache@v4
        with:
          path: |
            ~/.cache/kivyforge/artifacts
            ~/AppData/Local/kivyforge/Cache/artifacts
          key: kivyforge-${{ matrix.platform }}-${{ hashFiles(format('pylock.{0}.toml', matrix.platform)) }}
      - run: kivyforge doctor -p "$PLATFORM"
      - run: kivyforge lock -p "$PLATFORM" --check
      - name: Package
        id: package
        run: python ci/kf.py package -p "$PLATFORM"
      - uses: actions/upload-artifact@v6
        with:
          name: app-${{ matrix.platform }}
          path: ${{ steps.package.outputs.artifacts }}
      - name: Keep the JSON envelope for triage
        if: always()
        uses: actions/upload-artifact@v6
        with:
          name: kivyforge-${{ matrix.platform }}-json
          path: kf-*.json

  android:
    name: Package android
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v6
      - uses: actions/setup-python@v6
        with:
          python-version: '3.13'
      - uses: actions/setup-java@v5
        with:
          distribution: temurin
          java-version: '17'
      - uses: android-actions/setup-android@v4
        with:
          packages: platform-tools
      - run: pip install kivyforge
      - name: Restore the kivyforge download cache
        uses: actions/cache@v4
        with:
          path: ~/.cache/kivyforge/artifacts
          key: kivyforge-android-${{ hashFiles('pylock.android.toml') }}
      - run: kivyforge doctor -p android
      - run: kivyforge lock -p android --check
      - name: Package
        id: package
        env:
          ANDROID_KEYSTORE_B64: ${{ secrets.ANDROID_KEYSTORE_B64 }}
          KIVYFORGE_KEYSTORE_PASSWORD: ${{ secrets.ANDROID_KEYSTORE_PASSWORD }}
          KIVYFORGE_KEY_PASSWORD: ${{ secrets.ANDROID_KEY_PASSWORD }}
        run: |
          if [ "$GITHUB_EVENT_NAME" = pull_request ]; then
            python ci/kf.py package -p android --debug
          else
            keystore="$RUNNER_TEMP/upload.keystore"
            echo "$ANDROID_KEYSTORE_B64" | base64 -d > "$keystore"
            python ci/kf.py package -p android -f aab --keystore "$keystore"
          fi
      - uses: actions/upload-artifact@v6
        with:
          name: app-android
          path: ${{ steps.package.outputs.artifacts }}
      - name: Keep the JSON envelope for triage
        if: always()
        uses: actions/upload-artifact@v6
        with:
          name: kivyforge-android-json
          path: kf-*.json
```

Create three repository secrets for the Android release: `ANDROID_KEYSTORE_B64`
(your upload keystore, base64-encoded), `ANDROID_KEYSTORE_PASSWORD`, and
`ANDROID_KEY_PASSWORD`. The key alias comes from
`[tool.kivy.android.signing].key_alias` in `pyproject.toml`. See
[Sign an Android app](../android/signing.md).

### How the workflow works

1. **The capabilities step** checks the matrix against kivyforge itself. If
   someone adds `ios` to the matrix on an Ubuntu runner, the job fails at
   once, instead of after the download.
2. **The cache** keeps downloaded runtimes and wheels between runs. Its key is
   the lockfile's hash, so a re-lock starts a fresh cache.
3. **`doctor`** fails the job only for a FAIL. On a headless runner it warns
   about the missing display or device, and continues.
4. **`lock --check`** fails a pull request whose dependencies changed without a
   new lock. The fix is to run `kivyforge lock -p PLATFORM` locally and commit
   the result.
5. **`ci/kf.py package`** packages the app. Every diagnostic becomes an
   annotation titled with its `KF-*` code, and the step ends with one line that
   says who has to act, based on the exit code.
6. **The upload step** reads the paths from the `artifacts` output, which came
   from `data.artifacts`. A failed run lists only what it produced before it
   failed, so the upload never picks up a file left over from an earlier run.
7. **The JSON envelope** is kept on success and failure, so you can read the
   full diagnostics, with their `context`, after the run.

On pull requests from forks, GitHub doesn't pass secrets, which is why the
Android job packages a debug APK there. A debug APK needs no keystore.

`ci/kf.py` needs only the Python that runs kivyforge. On another CI system,
change the two places that use GitHub's syntax: the `::error::` annotation
lines and the `GITHUB_OUTPUT` file.

!!! note
    `upload-artifact` doesn't keep file permissions. Mark a downloaded AppImage
    executable with `chmod +x` before you run it.

To extend the workflow:

- **macOS:** add `{ platform: macos, os: macos-latest }` to the matrix. A
  `.app` is a folder with symlinks and executable bits, so zip it with
  `ditto -c -k --keepParent` before you upload it. See
  [Sign and notarize a macOS app](../macos/signing.md).
- **iOS:** use a macOS runner and configure signing first. See
  [Sign an iOS app](../ios/signing.md).
- **Release versions:** set the version from a tag with `--app-version` or
  `KIVYFORGE_APP_VERSION`. See [Set the app version](versioning.md).
- **Android smoke test:** on a runner with an emulator, run
  `kivyforge run -p android --smoke --release` to install the app and run the
  generated contract test. See [Run on Android](../android/run.md).

A job that packages for iOS, Android or a Linux `aarch64` target byte-compiles
with the CPython the lock pins for the runner's host; the first release build
downloads it, so the runner needs no Python of its own. A committed lock
written before kivyforge pinned it makes `lock --check` fail with
`KF-LOCK-INCOMPLETE`: run `kivyforge lock -p PLATFORM` once and commit the
result. For a runner that must build without network access, see
`KIVYFORGE_HOST_PYTHON_DOWNLOADS` in
[Environment variables](../../reference/environment.md).

!!! tip "Avoid GitHub API rate limits"
    Resolving the desktop Python runtime queries the GitHub API, which allows 60
    unauthenticated requests per hour per IP address. Set `GH_TOKEN` or
    `GITHUB_TOKEN` on the `lock` step to raise the limit, as the workflow above
    does. See [Environment variables](../../reference/environment.md).

### Upload Python distributions from a separate folder

`package` writes into platform folders under `dist/`, such as `dist/linux/`
and `dist/windows/`. `python -m build` and `uv build` write wheels and source
distributions to the same `dist/`. If one checkout does both, `twine upload
dist/*` and the `pypa/gh-action-pypi-publish` action fail on the platform
folders, because twine accepts only wheels and source distributions.

Upload the Python distributions one of these ways instead:

- Name them: `twine upload dist/*.whl dist/*.tar.gz`.
- Build them elsewhere with `python -m build --outdir wheels`, and point the
  action's `packages-dir` at `wheels`.
- Use `uv publish`, which skips anything that is not a distribution.

`package -p android` and `package -p ios` also write into `dist/`, as
`dist/android/` and `dist/ios/`.

## Drive kivyforge from a coding agent

A coding agent, such as Claude Code, Codex or Cursor, runs the same commands a
CI job runs. The difference is that it decides what to do next. The JSON
envelope and the codes give it facts to decide with, but only if it knows to
ask for them. Tell it once, in its instructions file, and keep each task
prompt short.

### Give the agent standing instructions

Add this section to the instructions file your agent reads in your app's
repository, such as `AGENTS.md` or `CLAUDE.md`:

```markdown
## Building this app

This app is built with kivyforge. Use it for every build, package, and run step.

- Start with `kivyforge capabilities --json`. It says which targets this
  machine can build. If it can't build the one I asked for, tell me which host
  can, instead of trying.
- Pass `--json` to every kivyforge verb except `run`. Read stdout as one JSON
  envelope; progress and tool logs are on stderr.
- Branch on the exit code, then on `diagnostics[].code`. Never on the message.
  - 1: fix pyproject.toml or the command.
  - 3: a tool is missing. Show me the `remediation`; don't install SDKs yourself.
  - 4: run `kivyforge lock -p PLATFORM`, then retry.
  - 5: read the end of the build log on stderr and report the cause.
- After you change dependencies in pyproject.toml, run
  `kivyforge lock -p PLATFORM` and commit the lock with the change.
  Never pass `--no-verify-lock`, and never edit `pylock.*.toml` by hand.
- A packaged desktop app started without a terminal writes Kivy's log,
  including the traceback of an uncaught exception, to the newest
  `kivy_*.txt` in the `logs` folder of Kivy's home directory. That is
  `~/.kivy/logs` (`%USERPROFILE%\.kivy\logs` on Windows), unless the app sets
  `KIVY_DESKTOP_PATH_ID` on Kivy 3.0 (`%APPDATA%\PATH_ID\.kivy\logs` on
  Windows) or sets `KIVY_HOME`. Read it before you add logging of your own.
- Diagnostics on an `ok: true` run are warnings. Report them; don't treat
  them as failures.
- Take output paths from `data.artifacts`. Don't guess them.
- `kivyforge run -p android` follows the app's log until the app exits.
  Always add `--no-follow`. On desktop, `run` opens the app's window, so use
  it only when I ask to see the app.
- Signing passwords are in my environment. Never ask me for them, print them,
  or write them to a file.
```

Replace `PLATFORM` with the target the agent is working on. To give the agent
fewer choices, name your targets in the section, for example "This app ships
for Android and Windows."

### Prompt the agent

With those instructions in place, a task prompt says only what you want:

```text
Add humanize to the app's dependencies, then build a signed release APK for
Android. Tell me where the APK is and whether kivyforge reported any warnings.
```

Before you start the agent, set the signing passwords in the shell it runs in,
for example `KIVYFORGE_KEYSTORE_PASSWORD`. See
[Environment variables](../../reference/environment.md#signing).

### What the agent does

A run of that prompt on a Windows machine looks like this. The envelopes are
trimmed to the fields the agent acts on.

1. **It checks what this machine can build.**

    ```bash
    kivyforge capabilities --json
    ```

    In `data.platforms`, the `android` entry has `"Windows": true` under
    `hosts`, and `"apk"` as its `default_package_format`. If you had asked for
    an iOS build, the `ios` entry's `"Windows": false` would tell the agent to
    stop and say that iOS needs a Mac.

1. **It looks at the project.**

    ```bash
    kivyforge status -p android --json
    ```

    ```json
    {
      "ok": true,
      "data": {
        "app": { "name": "hello-android", "id": "org.kivyforge.helloandroid" },
        "python": "3.14.6",
        "lock": {
          "state": "in sync",
          "in_sync": true,
          "relock_command": "kivyforge lock -p android"
        }
      }
    }
    ```

    The lock is in sync, and `relock_command` is the exact command to run when
    it isn't.

1. **It adds the dependency and checks the lock.** The agent adds
   `humanize>=4.12` to `[project].dependencies`, then runs:

    ```bash
    kivyforge lock -p android --check --json
    ```

    This exits `4` with `KF-LOCK-DRIFT`, `data.diff` set to
    `["  + humanize 4.17.0 (added)"]`, and `remediation` set to
    `kivyforge lock -p android`. The agent runs that command. Its envelope has
    `"ok": true` and `"action": "wrote"`.

    An agent that skips this step finds out anyway: `package` exits `4` with
    the same code, and the agent re-locks and retries.

1. **It checks the machine.**

    ```bash
    kivyforge doctor -p android --json
    ```

    ```json
    {
      "ok": true,
      "data": {
        "mode": "project",
        "summary": { "PASS": 18, "WARN": 1, "FAIL": 0, "SKIP": 6 }
      },
      "diagnostics": [
        {
          "code": "KF-DOCTOR-CHECK",
          "severity": "warning",
          "message": "adb: C:\\Android\\Sdk\\platform-tools\\adb.exe; no device or emulator attached",
          "remediation": "attach a device (USB debugging on) or boot an AVD; `kivyforge run` and `run --smoke` need one.",
          "context": { "check": "adb" }
        }
      ]
    }
    ```

    `ok` is `true`, so the agent continues. The warning matters only for
    `run`, which this task doesn't need. A FAIL would make `doctor` exit `3`,
    and the agent would show you its `remediation`.

1. **It packages the app.**

    ```bash
    kivyforge package -p android --json
    ```

    The envelope has `"ok": true` and one entry in `data.artifacts`:
    `{ "path": "dist/android/hello-android-1.0.0.apk", "kind": "apk" }`.

1. **It reports back.** The agent names the APK from `data.artifacts`, lists
   any warnings from `diagnostics`, and shows the change to `pyproject.toml`
   and `pylock.android.toml`.

If you ask the agent to try the APK on your phone, it runs
`kivyforge run -p android --device --no-build --no-follow`. That installs the
APK it just built, launches it, prints the app's log once, and returns.

!!! warning
    An agent that has to make a build pass may reach for `--no-verify-lock`
    when it sees `KF-LOCK-DRIFT`, because the human-readable message mentions
    it. That builds dependencies the lock doesn't record. The standing instructions above forbid it. Check for it when you
    review the agent's commands.

## Verify

Your pipeline is wired correctly when:

- `kf-package.json` parses as JSON and its `ok` field is `true`.
- `data.artifacts` names the file you expect, for example
  `dist/linux/APP_NAME-VERSION-x86_64.AppImage`, and the workflow run lists it
  under **Artifacts**.
- A pull request that adds a dependency without re-locking fails at the
  `lock --check` step.

`APP_NAME` and `VERSION` are your `[project].name` and `[project].version`.
Read the path from `data.artifacts` rather than building it yourself: some
names carry more than the version, such as the ABI of an Android package made
with `--abi`.

Your agent is set up correctly when its commands, as it reports them, carry
`--json`, and it re-locks on exit code `4` instead of passing
`--no-verify-lock`.

## What's next

- [JSON output](../../reference/json-output.md)
- [Exit and diagnostic codes](../../reference/codes.md)
- [Environment variables](../../reference/environment.md)
