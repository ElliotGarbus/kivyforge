# Future enhancements

Ideas that are worth doing but are **not** on the [roadmap](roadmap.md). The
roadmap is the work needed to stabilize and ship a full release; nothing here
blocks that. Each entry says what it is, why, and what would make it done, so it
can be promoted to the roadmap later without rediscovery.

## uv as an optional resolver backend

**Proposed 2026-10-01.** Findings: [`uv-lock-findings.md`](uv-lock-findings.md).

Resolution today is pip (`PipResolver`, see
[`resolver-findings.md`](resolver-findings.md)), with no way to apply a cooldown
on newly published releases. uv can resolve one target at a time with
`--python-platform` (including Android and iOS tags), emits a PEP 751 file with
hashes, and supports `--exclude-newer` (including relative durations such as
`7 days`).

**Work**

- Add a uv backend behind the existing `Resolver` protocol
  (`kivyforge/lock/resolver.py`). Optional: pip stays the default, and kivyforge
  must work without uv installed. Choose it by configuration or flag, and make
  `doctor` report whether uv is present and which version.
- Pass through `exclude-newer` and `exclude-newer-package` so a cooldown
  applies to every target.
- Binary-only (`--only-binary :all:`), matching the host-independent,
  no-source-build invariant. Without it uv quietly picked a PyPI sdist over an
  index wheel in the spike.
- Derive the Android API level (`ANDROID_API_LEVEL`) from the app's `min_sdk`;
  uv rejects wheels whose API level is above it.
- Prefer explicit per-package indexes to `--index-strategy unsafe-best-match`,
  which gives up uv's dependency-confusion protection.
- Map uv's output back to the existing lock model (URL, hashes, per-wheel
  provenance), and keep `[tool.kivyforge]` as it is.

**Dependencies outside this repo.** The kivy-mobile-wheels index publishes no
upload dates, so any `exclude-newer` makes its packages unsatisfiable. That
index needs PEP 700 JSON with `upload-time`, or the backend needs a documented
per-package exemption (`exclude-newer-package`, untested; see the findings).

**Done when** `kivyforge lock -p <target> --resolver uv --exclude-newer "7 days"`
produces a lock that `build` accepts for every desktop target and for Android,
and an iOS result is recorded (Kivy 3.0 needs CPython 3.15).

---

## Take version pins from `uv.lock`

**New 2026-10-01.** Depends on the uv resolver backend above. Findings:
[`uv-lock-findings.md`](uv-lock-findings.md).

A project that already maintains a `uv.lock` (including its cooldown and audit
policy) should not have to maintain per-target versions separately.

**Work**

- When a project has a `uv.lock`, derive version constraints from it (via
  `uv export`) and apply them when resolving each target. The per-target lock
  then differs only in the wheels chosen for that platform's tags.
- A pinned version with no wheel for a target fails `lock`, naming the package
  and the target (the existing fail-fast rule).
- Android wheels are still resolved per target: a universal `uv.lock` cannot
  cover Android in uv 0.12.21, and uv has no committed work on cross-platform
  environments ([#7957](https://github.com/astral-sh/uv/issues/7957)).
- Make the drift check include the `uv.lock` contents, so `lock --check` reports
  a stale per-target lock when the pins change. Decide which file wins when they
  disagree; the proposal is that the per-target lock is derived output.

**Revisit when** uv supports cross-platform environments or Android in
`required-environments`: then derive the Android lock directly from `uv.lock`.

**Done when** a project with a `uv.lock` locks every target from those pins, and
changing a pin makes `kivyforge lock --check` exit 4.
