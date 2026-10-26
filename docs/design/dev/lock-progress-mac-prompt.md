# Agent prompt — lock progress on iOS (#88)

> **Run this on a Mac with Xcode**, from a clone with the #88 change (branch
> `lock-progress`, or `main` once it is merged). `lock -p ios` runs only on
> macOS, so this is the one part of #88 the Windows and Linux hosts could not
> check. Written 2026-10-20.

## Background

`lock -p ios` used to run its slow steps with output captured, so a slow lock
looked like a hang. #88 makes it report each step, as `lock -p android` has
since #87 ([download-progress-output.md](download-progress-output.md)):

- a byte bar for the python.org `Python.xcframework` download, on a cache miss;
- `[lock] <slice>: resolving wheels`, and a bar for each wheel pip downloads
  (the kivy-mobile-wheels index has no PEP 658 metadata, so pip downloads whole
  wheels);
- `[lock] swift: resolving <names>` and the `Fetching` lines of
  `swift package resolve`;
- `[lock] <step>: still resolving (<time>)` after 30 s with nothing new shown.

In a terminal the bars redraw in place. In a pipe or a log they become a few
lines each (`0%`, a few in between, `100%`).

## Prompt

You are checking `kivyforge lock -p ios` progress output on a Mac. **Record what
you observe**, verbatim. Read `AGENTS.md` first: its rules on the results log
apply. Change no code unless a step fails; if one does, report it first.

### Step 0 — environment

```bash
sw_vers; xcodebuild -version; python3 --version; git log --oneline -1
```

### Step 1 — a cold start

Use `examples/mobile/keychain-spm`: it locks Kivy from the mobile wheel index and
declares a Swift package. Copy it so the example's tree stays untouched, and set
the cached iOS framework archive aside so it downloads again:

```bash
cp -R examples/mobile/keychain-spm /tmp/kf-progress && cd /tmp/kf-progress
mkdir -p /tmp/kf-cache-aside
mv ~/Library/Caches/kivyforge/artifacts/*iOS-XCframework* /tmp/kf-cache-aside/ 2>/dev/null
rm -f pylock.ios.toml
```

### Step 2 — in a terminal

```bash
PIP_NO_CACHE_DIR=1 kivyforge lock -p ios
```

Pass if: a bar for `Python.xcframework <version>` appears and fills; each slice
prints `resolving wheels`, followed by bars for the wheels it downloads; the
`swift:` lines appear; nothing is drawn twice, and no bar is left half-drawn
under the final `Wrote pylock.ios.toml` line. Take a screenshot or copy the
final screen.

### Step 3 — piped to a file

```bash
rm -f pylock.ios.toml
mv ~/Library/Caches/kivyforge/artifacts/*iOS-XCframework* /tmp/kf-cache-aside/ 2>/dev/null
PIP_NO_CACHE_DIR=1 kivyforge lock -p ios > out.txt 2> err.txt; echo "exit=$?"
cat out.txt; cat err.txt
```

Pass if: `out.txt` holds only the `Wrote pylock.ios.toml ...` line; `err.txt`
has the step lines, and each download as a few `NN% of <size>` lines, not a
stream of redraws.

### Step 4 — restore

```bash
mv /tmp/kf-cache-aside/* ~/Library/Caches/kivyforge/artifacts/ 2>/dev/null
rm -rf /tmp/kf-progress /tmp/kf-cache-aside
```

## Record

1. Append a row to `docs/design/dev/test-matrix.md` §7: date, `iOS lock progress
   (#88)`, `lock (local)`, the host (macOS, Xcode, Python), and the result.
2. Replace the illustrative block under "`lock -p ios` and the desktop targets"
   in `download-progress-output.md` with the real `err.txt` from Step 3, and
   delete the note that says it is illustrative.
3. Commit on the current branch with a message that says why. Do not push:
   report back, defects first.
