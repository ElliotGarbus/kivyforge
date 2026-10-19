# CI fixture apps

Minimal, buildable projects that exist **only** to be built by a CI job and
inspected by the T3 artifact checks. They are not examples: nothing here is
written to be read as a demonstration of how to use kivyforge, and nothing
here should grow features to show something off. `examples/` is where that
belongs.

The distinction is load-bearing for one reason — **these commit their
`pylock.*.toml`, and `examples/**` deliberately does not.**

[`common/03-lockfile-concept.md`](../../../docs/design/common/03-lockfile-concept.md)
§"Example-repo lock policy" gitignores example locks because an edit to a
lock input (a dependency, a deployment target, an index) regenerates the
lock and churns the diff even when no pinned package changed. That
reasoning is about files maintainers edit often. A fixture's inputs change
only when a gate is meant to test something new, so the churn the policy
objects to does not arise here.

The policy's other objection — that a committed lock "can go silently
stale" — also does not apply, and for a sharper reason: that risk is about a
lock kept for *reference*, checked in and never built from. A CI job
downloads these exact pinned artifacts on **every push**, so a wheel or
runtime that disappears from its URL fails the next run. Nothing about it is
silent.

What a committed lock buys is the property a gate needs: the job builds the
same inputs every time, so a red run means kivyforge changed, not that PyPI
did. Re-resolving on every push would mean a Kivy release or a bad
transitive dep could turn the gate red with nothing in the repo having
changed — and a gate that goes red for reasons you did not cause is one
people learn to ignore.

## Line endings are not a concern here

Worth stating, because it looks like one and was briefly treated as one. A
committed lock records a hash, and `core.autocrlf` rewrites line endings on
checkout, so it is natural to assume a Windows checkout would change the
digest and make `kivyforge lock --check` disagree across hosts.

It does not. `lock_inputs_sha256` hashes the *parsed* values of the lock
inputs (`kivyforge/lock/inputs.py`), not the file's bytes, so line endings,
comments and whitespace cannot reach it.

So these fixtures need no `.gitattributes` treatment, and neither do the three
committed mobile gate locks. Recorded here so the concern is not rediscovered
and "fixed" again.

## Updating a lock

Deliberately, as its own reviewable change:

```bash
cd tests/fixtures/apps/<name> && kivyforge lock -p <platform> --update
```

A plain `kivyforge lock` after an input change keeps the pinned versions and
moves only what the change requires; `--update` takes the newest of
everything. Lock `linux-gate` and `macos-gate` from a Linux or macOS host: from
Windows, pip evaluates Kivy's dependency markers for the Windows host and asks
for `kivy-deps.angle`.

Testing against newer dependencies is a thing you decide to do, not
something that happens to you between pushes.

## Keep them minimal

Each fixture is one target's smallest interesting app. Per roadmap item 5,
the set is "one minimal app per target plus one that exercises native
binaries, wheels with extension modules, icons, and `strip_source`" — the
richer case is a *separate* fixture, not this one growing.

`tests/` is pruned from the sdist (`MANIFEST.in`), so none of this ships.

| Fixture | Target | What its job proves |
|---|---|---|
| `linux-gate` | Linux `x86_64` | `kivyforge package -p linux` end to end on a real `appimagetool`, then the full Linux T3 pass over the AppDir it produced |
| `macos-gate` | macOS `arm64` | `kivyforge package -p macos` end to end ad-hoc signed (no certificate needed), then the full macOS T3 pass — including the `Info.plist`-vs-config comparison — over the `.app` it produced |
| `windows-gate` | Windows `amd64` | `kivyforge package -p windows` end to end, the full Windows T3 pass over the onedir bundle, then signing that bundle's launcher with a throwaway cert and verifying it — the built-app signature check `windows_signing` cannot do on a vendored binary |
| `metaprobe` | macOS, iOS simulator, Android emulator | What `importlib.metadata` sees inside the built app: its own name, version, entry points and modules, and its dependencies' entry points. Driven by `tests/integration/test_app_metadata_devices.py` (`--metaprobe`), not by a gate job ([package-metadata-proposal.md](../../../docs/design/dev/package-metadata-proposal.md), layer 3) |

## `metaprobe` commits no lock

It is the exception to the rule above. Its two dependencies are wheels the
driver builds from `deps/` on every run, and a lock records their hashes, so a
committed lock would be stale after one run. The driver copies the fixture to a
temporary directory, builds the wheels and locks there, and the fixture's
`.gitignore` covers the same outputs for anyone who runs kivyforge in it by hand.
