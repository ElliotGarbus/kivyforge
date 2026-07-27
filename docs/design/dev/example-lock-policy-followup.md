# Follow-up: example lock policy has drifted from what's documented

> **RESOLVED** — the "wider" option below was chosen and applied.
> `common/03-lockfile-concept.md` now exempts the two on-device **gate**
> examples (`hello-android`, `hello-kivy`) on the grounds that their locks are
> validation evidence; `pyjnius-deviceinfo` and `qr-maven` were untracked and
> gitignored to match the policy. Both gate examples carry a `.gitignore`
> comment explaining why their lock is tracked, so it does not read as an
> oversight.
>
> **Correction (2026-07-27):** this note originally claimed "every mobile
> example now resolves from the index" and that `examples/wheels/ios/*.whl`
> were unused-but-undeleted. Neither was true at the time — Phase 6 as
> scoped had only repointed `hello-kivy` and `pyobjus-*`; `keychain-spm`,
> `mobile-geometry`, and `svg-explorer` were still on local `find_links`
> against that directory. Both gaps are now closed (see the addendum in
> [`mobile-wheels-phase6-ios-findings.md`](mobile-wheels-phase6-ios-findings.md)):
> all six iOS examples resolve from the index, and
> `examples/wheels/ios/` has been deleted.
>
> **Still open:** no example demonstrates the local `path`-wheel shape (item
> 1). That gap was flagged *before* the deletion above as a reason to
> possibly keep one example deliberately on `find_links` — the deletion
> proceeded anyway once all six examples were validated against the index,
> so the gap is now real rather than hypothetical. See below.

Raised while completing Phase 6 of the mobile-wheels plan. **Not urgent, and
not a bug** — but three things no longer line up, and one of them was caused
by Phase 6 itself.

The policy is stated in
[`common/03-lockfile-concept.md` §"Example-repo lock policy"](../common/03-lockfile-concept.md):
`examples/**/pylock.*.toml` is gitignored, because `pyproject_sha256` hashes
the whole `pyproject.toml` and so any overlay edit churns `generated_at` with
no package change; a lock kept "for reference" can also go stale unnoticed.
One deliberate exception is carved out.

## 1. The stated reason for the exception is now false

> `examples/mobile/hello-kivy/pylock.ios.toml` stays committed as the single
> canonical, checked-in reference lock (**it exercises the local `path`-wheel
> case**, the shape most worth seeing "for real").

Phase 6 repointed that example at the `kivy-mobile-wheels` index, so its lock
now records `url` + `sha256`. It no longer demonstrates the `path` case — and
**no example does**, since every mobile example now resolves from the index.

So either the exception's rationale needs rewriting (the canonical lock is
still worth having; it just demonstrates the `url` shape now), or a
`path`-based example needs to be kept deliberately to cover that case. The
`path` shape is still supported and still what a user vendoring their own
wheels would produce, so it going undemonstrated is a real gap.

## 2. The Android examples don't follow the policy

`hello-android`, `pyjnius-deviceinfo` and `qr-maven` have **tracked**
`pylock.android.toml` and no per-example `.gitignore`. They were created
during the Android backend work without picking up the convention the seven
iOS examples follow. Nothing is broken, but the tree currently says two
different things.

Either bring them in line (add the `.gitignore`, untrack the locks) or widen
the exception deliberately — see the next point before deciding.

## 3. `verify-android.ps1` depends on tracked locks

```powershell
& $kivyforge lock -p android --check
if ($LASTEXITCODE -ne 0) {
    Write-Host "  lock out of date; re-locking"
    & $kivyforge lock -p android
}
```

`lock --check` is a CI pre-flight that compares a *committed* lock against
`pyproject.toml`. With a gitignored lock there is nothing to compare, so the
check can only ever report "out of date" and fall through to the re-lock
branch — a permanent no-op. It works today only because the Android examples
happen to violate the policy.

If the policy is applied uniformly, that step should be dropped from the
verifier rather than left as a check that cannot fail meaningfully.

## A consideration the policy predates

Committed locks in the two gate examples (`hello-android`, `hello-kivy`) are
now also *evidence*: they record the exact wheel hashes that passed the
on-device contract smoke test on the emulator, the Pixel 8a and the iOS
simulator. If those regenerate, the artifact tying a validation result to
specific binaries is gone.

That argues for keeping a committed lock on whichever examples serve as
on-device gates, regardless of what the rest do — which is close to the
existing exception, just with a different justification and a second example
in scope.

## Suggested resolution

Pick one and make the tree match it:

- **Narrow**: keep the exception at one canonical lock, fix its stated reason,
  gitignore the three Android locks, and drop `lock --check` from
  `verify-android.ps1`.
- **Wider**: commit locks for the gate examples specifically
  (`hello-android` + `hello-kivy`), justify it as validation evidence, keep
  the rest ignored, and keep `lock --check` working for those.

The second is closer to how the tree already behaves and keeps the verifier
honest; the first is closer to what is written down. Either is fine — the
current state is neither.

## Remaining work — done (2026-07-27)

Phase 6 first repointed only the six examples that were being actively
validated, leaving `keychain-spm`, `mobile-geometry`, and `svg-explorer` on
local wheels (`find_links = ["../../wheels/ios"]`) — flagged here as a gap
found by an independent survey of `examples/**/pyproject.toml`, run
concurrently with the fix on the Mac.

All three have since been repointed at
`extra_index_urls = ["https://elliotgarbus.github.io/kivy-mobile-wheels/simple/"]`,
re-locked, and re-validated on the simulator (`keychain-spm` first, since it
is the only example that also exercises `swift package resolve`). Package
sets and wheel hashes were confirmed unchanged via `tomllib`, not by eye —
only `path` → `url`. Full detail in the addendum to
[`mobile-wheels-phase6-ios-findings.md`](mobile-wheels-phase6-ios-findings.md).
`hello-world` (no dependencies) and the desktop examples (PyPI, never used
`find_links`) were correctly out of scope and untouched.

### The cleanup, and the question it depended on

With all six-plus-three examples on the index, nothing in the repo resolved
from `examples/wheels/ios/` any more, and it was deleted — along with the
`find_links` convention it supported for these examples.

That was flagged here as depending on a prior, still-unresolved decision:
`path` pins are a supported lock shape and what a user vendoring their own
wheels would produce, and once this cleanup lands **no example demonstrates
that shape**. Keeping one example deliberately on `find_links` would have
been the cheapest way to preserve coverage of it. The deletion went ahead
without that example being kept, so the gap is now real, not hypothetical —
see item 1 above and the correction note at the top of this file. If that
coverage matters, the fix is to reintroduce local `path` wheels (which
requires rebuilding or re-vendoring at least one wheel — `kivy-mobile-wheels`
Releases only serve `url` sources) on one example, not to reverse the
`examples/wheels/ios/` deletion for all of them.

## Where the work runs

`kivyforge lock -p ios` is macOS-gated (`IosPlatform.check_host_capability`),
and resolving Swift packages shells out to `swift package resolve`, so all
iOS-side work above needed a Mac. The Android side was already complete.
