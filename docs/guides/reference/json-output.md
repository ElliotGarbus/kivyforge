---
title: JSON output
sources:
  - kivyforge/report/envelope.py
  - kivyforge/report/diagnostics.py
  - kivyforge/report/console.py
  - kivyforge/build_outcome.py
  - tests/cli/test_build_package_json.py
  - docs/design/common/02-cli-and-platform-resolution.md
---

# JSON output

Every verb except `run` accepts `--json`. With `--json`, stdout carries exactly
one JSON document, the *envelope*, and nothing else, on success and on every
failure. Progress and tool logs stay on stderr, so you can capture a build log
and a parseable result from the same run.

## Envelope

```json
{
  "schema": 1,
  "kivyforge": "3.0.0.dev0",
  "command": "doctor",
  "platform": "linux",
  "ok": true,
  "data": {},
  "diagnostics": []
}
```

| Field | Type | Description |
|---|---|---|
| `schema` | integer | Envelope schema version. It changes only for a change that is not purely additive; a new key inside `data` does not change it. |
| `kivyforge` | string | The kivyforge version that produced the envelope. |
| `command` | string | The verb, for example `build`. |
| `platform` | string or null | The resolved target platform. `null` when the verb has no single target (`capabilities`, `clean`, `init` with several `-p`) or when the run failed before the target was resolved. |
| `ok` | boolean | `true` if the run succeeded. |
| `data` | object | Verb-specific payload. Always present, possibly empty. |
| `diagnostics` | array | Diagnostic entries. Always present, possibly empty. |

Keys appear in the order shown. Non-ASCII characters are escaped as `\uXXXX`, so
the envelope is safe to write to a stream of any encoding.

## `data.artifacts`

For `build` and `package`, `data.artifacts` lists what this run produced and
verified. Each entry is an object with two keys:

| Key | Description |
|---|---|
| `path` | Path relative to the project root, with forward slashes on every host. |
| `kind` | One of `appimage`, `apk`, `aab`, `app`, `ipa`, `folder`, or `project`. |

```json
{
  "data": {
    "artifacts": [
      { "path": "dist/linux/dice-roller-0.1.0-x86_64.AppImage", "kind": "appimage" }
    ]
  }
}
```

`folder` is a Windows onedir bundle or a Linux AppDir. `app` is a macOS `.app`
bundle, or an iOS `.app` built for the simulator or a device. `project` is a
generated Xcode or Gradle project, which is not runnable by itself.

A failed run lists only what it produced before it failed. For example, a
failed iOS `build` still lists the generated Xcode project. It never lists output
left on disk by an earlier run, so `[]` means this run produced nothing.

## Diagnostics

Each entry in `diagnostics` has these keys:

| Key | Presence | Description |
|---|---|---|
| `code` | always | A stable `KF-*` code. See [Exit and diagnostic codes](codes.md). |
| `severity` | always | `error`, `warning`, or `info`. |
| `message` | always | Human-readable text. It can change between releases. |
| `remediation` | optional | What to do about it. Omitted when there is nothing to say. |
| `context` | optional | An object of code-specific details, string to string. |

```json
{
  "code": "KF-BUILD-TOOL-FAILED",
  "severity": "error",
  "message": "Gradle assembleRelease failed.",
  "context": { "tool": "gradle", "task": "assembleRelease" }
}
```

This example is illustrative; the exact `message` text varies.

Branch on `code`, never on `message`. A diagnostic on an `ok: true` run is a
warning, not a failure: for example, an unsigned package or a byte-compile step
that fell back to shipping source.

## Colour

Colour applies to human-readable output only; the envelope never contains escape
codes. To turn off colour and other terminal styling in a log file or CI
transcript, pass `--no-color` or set `NO_COLOR`. See
[Environment variables](environment.md).

## What's next

- [Exit and diagnostic codes](codes.md)
- [Drive kivyforge from CI or an agent](../guides/cross-platform/ci-and-agents.md)
- [CLI reference](cli.md)
