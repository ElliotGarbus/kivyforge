# CI fixture apps

Minimal, buildable projects that exist **only** to be built by a CI job and
inspected by the T3 artifact checks. They are not examples: nothing here is
written to be read as a demonstration of how to use kivyforge, and nothing
here should grow features to show something off. `examples/` is where that
belongs.

The distinction is load-bearing for one reason — **these commit their
`pylock.*.toml`, and `examples/**` deliberately does not.**

[`common/03-lockfile-concept.md`](../../../docs/design/common/03-lockfile-concept.md)
§"Example-repo lock policy" gitignores example locks because
`pyproject_sha256` hashes the whole `pyproject.toml`, so any overlay edit —
a signing identity, a bundle id, an icon path — regenerates the lock and
churns the diff with no pinned package having changed. That reasoning is
about files maintainers edit for cosmetic reasons. Nobody edits a fixture's
overlay to change an icon, because a fixture has no audience to impress, so
the churn the policy objects to does not arise here.

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
committed lock records `pyproject_sha256`, and `core.autocrlf` rewrites line
endings on checkout, so it is natural to assume a Windows checkout would
change the digest and make `kivyforge lock --check` disagree across hosts.

It does not. `compute_pyproject_sha256` hashes
`pyproject.read_text(encoding="utf-8")` — **text mode**, so Python's universal
newlines translate `\r\n` to `\n` before the hash is taken. CRLF and LF produce
the same digest. Verified against the committed `hello-android` lock, which
matches either form of its `pyproject.toml`.

So these fixtures need no `.gitattributes` treatment, and neither do the three
committed mobile gate locks. Recorded here so the concern is not rediscovered
and "fixed" again.

## Updating a lock

Deliberately, as its own reviewable change:

```bash
cd tests/fixtures/apps/<name> && kivyforge lock -p <platform> --update
```

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
