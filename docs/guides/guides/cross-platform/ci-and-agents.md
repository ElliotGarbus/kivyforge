---
title: Drive kivyforge from CI or an agent
sources:
  - AGENTS.md
  - kivyforge/cli/lock.py
  - kivyforge/cli/capabilities.py
  - kivyforge/report/exit_codes.py
  - kivyforge/report/diagnostics.py
  - .github/workflows/kivyforge.yml
  - docs/design/common/02-cli-and-platform-resolution.md
---

# Drive kivyforge from CI or an agent

kivyforge is designed to run unattended. Every verb except `run` can print a
single JSON document on stdout, every failure has a stable exit code and a `KF-*`
diagnostic code, and no verb waits for input. This page shows how to query what
kivyforge can do, check a committed lock, and branch on the result of a build.

## Before you begin

- [Install kivyforge](../../get-started/install.md) in the CI environment.
- Commit the `pylock.<platform>.toml` for each target you build in CI. See
  [Lockfiles](../../concepts/lockfiles.md).
- Use a CI runner whose operating system can build the target. See
  [Which host builds which target](../../get-started/hosts.md).

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
| `3` | Toolchain or host missing | Install the named tool, or use a host that can build the target, then retry unchanged. |
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
again, it needs network access, and a range specifier fails the check when a
newer match is published.
[Pin a package version](dependencies.md#pin-a-package-version) to keep the
check stable. The check is meaningful only against a committed lock.

`build` and `package` also refuse a lock that no longer matches
`pyproject.toml`. `--no-verify-lock` skips that check. Use it only when a CI step
deliberately edits `pyproject.toml` after the lock was resolved.

## Example: a GitHub Actions job

This job checks the committed lock and packages a Linux AppImage:

```yaml
jobs:
  linux:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v6
      - uses: actions/setup-python@v6
        with:
          python-version: '3.13'
      - run: pip install kivyforge
      - run: kivyforge doctor -p linux
      - run: kivyforge lock -p linux --check
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
      - run: kivyforge package -p linux --json > package.json
```

`doctor` fails the step only when a check reports FAIL; WARN results, such as
no display on a headless runner, don't change its exit code.

!!! tip "Avoid GitHub API rate limits"
    Resolving the desktop Python runtime queries the GitHub API, which allows 60
    unauthenticated requests per hour per IP address. Set `GH_TOKEN` or
    `GITHUB_TOKEN` on the `lock` step to raise the limit. See
    [Environment variables](../../reference/environment.md).

## Upload Python distributions from a separate folder

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

!!! note "Preview"
    This describes behavior that is on `main` but not yet in a released
    version. It will ship in a future release. `package -p android` and
    `package -p ios` also write into `dist/`, as `dist/android/` and
    `dist/ios/`.

## Verify

Your pipeline is wired correctly when:

- `package.json` parses as JSON and its `ok` field is `true`.
- `data.artifacts` names the file you expect, for example
  `dist/linux/APP_NAME-VERSION-x86_64.AppImage`.

`APP_NAME` and `VERSION` are your `[project].name` and `[project].version`.
Read the path from `data.artifacts` rather than building it yourself: some
names carry more than the version, such as the ABI of an Android package made
with `--abi`.

## What's next

- [JSON output](../../reference/json-output.md)
- [Exit and diagnostic codes](../../reference/codes.md)
- [Environment variables](../../reference/environment.md)
