# AGENTS.md — working on kivyforge

For an agent (or a new contributor) writing code **in this repo**. Driving
kivyforge **as a tool** is the last section.

This file points at the authoritative source for each fact rather than
restating it, because a second copy is a copy that goes stale — the rule
[`test-matrix.md`](docs/design/dev/test-matrix.md) states and this repo has
already been bitten by twice.

## The loop

```bash
pip install -e ".[dev]"
pytest                          # coverage gate: fails under 80% (currently ~93%)
ruff check kivyforge tests
ruff format --check kivyforge tests
pyright                         # zero errors; scope in pyrightconfig.json
```

CI runs exactly these four, so a green local run is a green lint job. Settings
live in `pyproject.toml` (`[tool.pytest.ini_options]`, `[tool.ruff]`) and
`pyrightconfig.json` — read them there.

`pythonPlatform: All` in `pyrightconfig.json` is load-bearing: pyright otherwise
infers the platform from the *host* and narrows the stdlib stubs, so the
Windows-only registry probe is clean on Windows and an error on the ubuntu lint
job. A gate whose result depends on which host ran it is not a gate.

## Where to look first

| Question | File |
|---|---|
| What is being built, in what order, and why | [`docs/design/dev/roadmap.md`](docs/design/dev/roadmap.md) |
| What has actually been *exercised*, on which host | [`docs/design/dev/test-matrix.md`](docs/design/dev/test-matrix.md) |
| How a platform backend is structured | `docs/design/common/05-platform-architecture.md` |
| Per-platform specs | `docs/design/platforms/<os>/` |

Design decisions live in `docs/design/dev/*.md` as proposals and findings. When
a decision's *reason* matters later, it belongs there, not in a commit message
nobody greps.

## Rules that are easy to break without noticing

**Product goes to stdout; everything else goes to stderr.** Under `--json`,
stdout is exactly one envelope and nothing else. Backends never print: they
report through the callbacks in `kivyforge/build_outcome.py`, and the verb
renders. `kivyforge/report/console.py` states the rule; the tests that enforce
it are `tests/cli/test_build_package_human_output.py` (text and order unchanged,
stdout content pinned) and `test_build_package_json.py` (stdout parses as one
document, on success *and* every failure class).

**A failure's code is a contract; its message is not.** Reword messages freely;
never reuse or repurpose a code. Codes live in `kivyforge/report/diagnostics.py`,
exit statuses in `kivyforge/report/exit_codes.py`, and the classification
plumbing in `kivyforge/report/failures.py` — `ClassifiedError` so a raise site *can* classify,
`spawn_failure()` for a tool that would not start, `reclassify()` when
re-raising one layer down, `ToolchainError.wrap()` at the CLI boundary. An
unclassified failure is `KF-ERROR`/exit 1: unspecific, never wrong.

**Only report what this run produced.** `artifacts` in a `build`/`package`
envelope lists what *this invocation* finalised and verified, including on
failure. Naming a previous run's artifact is worse than saying nothing, because
it is indistinguishable from success output. See
`build-package-output-proposal.md` §4.1b.

**User-facing strings must encode in cp1252.** Not for the console — for a
*redirected* stream, where Python falls back to the locale encoding and an
unencodable character raises from inside the print, turning a cosmetic problem
into a crashed build. Em dashes and `§` are fine; arrows, box drawing and maths
symbols are not. `tests/test_message_encoding.py` enforces it over every
non-docstring literal in the package, and explains why the scope is that wide.

**Nothing may wait for input.** No verb prompts, and every spawned tool gets
`stdin=DEVNULL` so an unexpectedly interactive one fails fast instead of hanging
a CI job. The deliberate exception is `run`'s app launch: that process is the
user's program and keeps the user's stdin.

**A test that skips silently is indistinguishable from one that passed.** That
is how a two-release bug survived (roadmap item 1). Host- and toolchain-dependent
tests use the markers registered in `tests/conftest.py` — `requires_symlinks`,
`requires_windows`, `requires_posix`, `requires_toolchain`, `requires_device`,
`integration` — and the CI job that exists to run them sets the matching
`KIVYFORGE_REQUIRE_*` variable, so on that runner absence fails instead of
skipping.

**The hermetic suite touches no network and no toolchain.** Real-toolchain work
belongs in a CI job or a dated local run — and then in `test-matrix.md` §7,
because an unlogged manual test did not happen.

## Cross-host work

Windows, macOS and Linux each reach targets the others cannot, so verification
that needs a real toolchain is written as a *prompt* for whoever has that host,
and its results come back as a *findings* doc. See
`build-package-output-{mac,linux}-prompt.md` and their findings files for the
shape: environment table, per-step commands and verbatim output, defects first.

## Committing

- Work on the current feature branch; **ask before pushing**.
- Never commit a generated example lock, build output, or an edit made to an
  example just to reproduce something. Most examples gitignore `pylock.*.toml`;
  three on-device gate examples (`hello-android`, `hello-sdl3`, `hello-kivy`)
  track theirs on purpose and say so in their own `.gitignore`. If re-locking
  one of those would change it, diff and report rather than committing —
  `docs/design/common/03-lockfile-concept.md` §"Example-repo lock policy".
- User-visible changes get a `CHANGELOG.md` entry under `[Unreleased]`, with the
  migration note when behaviour changes.
- Commit messages explain *why*. The diff already shows what.

## Driving kivyforge from an agent

- **Ask first:** `kivyforge capabilities --json` lists the platforms, their
  archs and package formats, **which hosts can build which targets**, every
  verb and whether it takes `--json`, and the exit-code and `KF-*` vocabularies.
  It needs no project, lock or network.
- **Every verb but `run` takes `--json`.** stdout is one envelope:
  `{"schema", "kivyforge", "command", "platform", "ok", "data", "diagnostics"}`.
  Progress stays on stderr, so a build log and a parseable document coexist.
- **Branch on `exit_code` first, then `diagnostics[].code`**: `1` fix the
  config, `3` fix the machine, `4` re-lock, `5` read the build log. `2` is
  click's usage error and kivyforge never raises it.
- **`diagnostics` on an `ok: true` run are warnings**, not failures — an
  unsigned package, a byte-compile that degraded, a policy note.
- **Build outputs are in `data.artifacts`** as `{"path", "kind"}`, relative to
  the project root and posix-spelled. Read that instead of guessing the layout.
