---
title: Exit and diagnostic codes
sources:
  - kivyforge/report/exit_codes.py
  - kivyforge/report/diagnostics.py
  - docs/hooks/kf_generated.py
  - docs/design/common/02-cli-and-platform-resolution.md
---

# Exit and diagnostic codes

kivyforge reports a failure in two ways that a script can branch on: the process
**exit code**, and, with `--json`, **diagnostics** that each carry a stable `KF-*`
code. The codes are a contract. The human-readable messages can change in any
release, so never match on them.

Both tables on this page are generated from kivyforge's source. To read the same
vocabularies at run time, run `kivyforge capabilities --json`.

## Exit codes

Branch on the exit code first. It tells you the kind of failure without parsing
any text.

<!-- kf:exit-codes -->

Exit code `2` belongs to the command-line parser: it means a mistyped flag or
argument. kivyforge never uses `2` for its own failures, so a usage error stays
distinct from a missing toolchain.

## Diagnostic codes

With `--json`, each entry in the envelope's `diagnostics` array has a `code`,
`severity`, and `message`, and optionally `remediation` and `context`. See
[JSON output](json-output.md) for the full shape. A diagnostic on an `ok: true`
run is a warning, not a failure.

<!-- kf:diagnostic-codes -->

## What's next

- [JSON output](json-output.md)
- [Drive kivyforge from CI or an agent](../guides/cross-platform/ci-and-agents.md)
- [Diagnose a failing build](../troubleshooting/index.md)
