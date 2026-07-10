# Directory Refactor — Tier 1 (naming + symmetry)

Goal: remove the three concrete structural confusions without touching the
shared-core layers. Each platform stays where it is *conceptually*; we only
(1) give the iOS bundler an iOS name, (2) hoist the one genuinely shared module
out of it, (3) rename the misleading `platforms/` package, and (4) make the
doctor check filenames symmetric.

Everything here is a rename/move plus mechanical import updates — no logic
changes. Do it on a branch, use `git mv` to preserve history, and run the test
suite (`pytest`) + `ruff check` after **each** step.

> **Scope note / correction.** Two things I originally floated for Tier 1 are
> *not* low-risk and are deferred to Tier 2 (see bottom):
> - **`lock/ios/`** — the lock layer is a shared core (`builder`/`model`/
>   `resolver`/`reader`/`writer` + `lock/linux/`, `lock/macos/` profile dirs).
>   iOS has no profile subdir because its resolver/profile is *embedded in the
>   shared core*. Splitting it out is invasive.
> - **`cli/_ios.py`** — `cli/build.py`/`run.py`/`package.py` are iOS-first with
>   macOS/Linux early-return branches. Extracting the iOS path is invasive.

---

## Step 0 — baseline

- [ ] Branch: `git checkout -b refactor/dir-tier1`
- [ ] Green baseline: `pytest` and `ruff check .` both pass before starting.

---

## Step 1 — hoist the shared icon module out of `project/`

`kivyforge/project/icon.py` is the **only** module in `project/` used outside
iOS (it's a general PNG-size validator, despite its iOS-flavored docstring).
Move it to a shared top-level home so the `project/` → `ios/` rename in Step 2
doesn't drag a shared dependency into the iOS package.

- [ ] `git mv kivyforge/project/icon.py kivyforge/icon.py`
- [ ] `git mv tests/project/test_icon.py tests/test_icon.py`
- [ ] Reword the module docstring to be platform-neutral (it validates any
      configured icon source, not just `[tool.kivy.ios...]`).

Import updates (`..project.icon` / `.icon` → the new shared path):

| File | Old | New |
|------|-----|-----|
| `kivyforge/project/assets.py:16` | `from .icon import validate_icon_source` | `from ..icon import validate_icon_source` |
| `kivyforge/linux/icons.py:22` | `from ..project.icon import validate_icon_source` | `from ..icon import validate_icon_source` |
| `kivyforge/macos/icns.py:15` | `from ..project.icon import IconSourceError, validate_icon_source` | `from ..icon import IconSourceError, validate_icon_source` |
| `kivyforge/doctor/checks.py:12` | `from ..project.icon import APP_ICON_SIZE, icon_source_problem` | `from ..icon import APP_ICON_SIZE, icon_source_problem` |
| `kivyforge/doctor/checks_macos.py:17` | `from ..project.icon import ...` | `from ..icon import ...` |
| `kivyforge/doctor/checks_linux.py:28` | `from ..project.icon import ...` | `from ..icon import ...` |
| `kivyforge/cli/build.py:26` | `from ..project.icon import IconSourceError` | `from ..icon import IconSourceError` |
| `tests/test_icon.py` | `from kivyforge.project.icon import ...` | `from kivyforge.icon import ...` |

> Note: `assets.py` gets `.icon` → `..icon` here, then moves in Step 2 (where it
> becomes `..icon` from inside `ios/` — same relative depth, so no further edit).

- [ ] `pytest -q` + `ruff check .`

---

## Step 2 — rename the iOS bundler: `project/` → `ios/`, fold in `xcode/`

`project/` (Xcode project generation) + `xcode/` (xcodebuild wrapper) together
ARE the iOS bundler — the peer of `macos/` and `linux/`. Give them an iOS name.

- [ ] `git mv kivyforge/project kivyforge/ios`
- [ ] `git mv kivyforge/xcode kivyforge/ios/xcode`
- [ ] `git mv tests/project tests/ios`
- [ ] `git mv tests/xcode tests/ios/xcode`

Internal relative imports inside `ios/` (e.g. `from .assets import ...`,
`from .staging import ...`) are unchanged. Only the `xcode` sub-move and the
external importers below change.

External importers of `..project.*` → `..ios.*`:

| File | Old | New |
|------|-----|-----|
| `kivyforge/cli/build.py:27` | `from ..project.materialize import materialize_project` | `from ..ios.materialize import materialize_project` |
| `kivyforge/cli/build.py:28` | `from ..project.staging import StagingError, create_staging` | `from ..ios.staging import StagingError, create_staging` |

External importers of `..xcode*` → `..ios.xcode*`:

| File | Old | New |
|------|-----|-----|
| `kivyforge/cli/build.py:29` | `from ..xcode import (...)` | `from ..ios.xcode import (...)` |
| `kivyforge/cli/build.py:40` | `from ..xcode.commands import (...)` | `from ..ios.xcode.commands import (...)` |
| `kivyforge/cli/run.py:10` | `from ..xcode import (...)` | `from ..ios.xcode import (...)` |
| `kivyforge/cli/package.py:13` | `from ..xcode import CommandError, SigningError, XcodeBuild` | `from ..ios.xcode import ...` |
| `kivyforge/cli/open_cmd.py:10` | `from ..xcode import CommandError, open_command, run_command` | `from ..ios.xcode import ...` |
| `kivyforge/cli/status.py:12` | `from ..xcode.commands import default_simulator_arch, product_app_path` | `from ..ios.xcode.commands import ...` |

Test importers → `kivyforge.ios.*` / `kivyforge.ios.xcode.*`:

- [ ] `tests/ios/test_assets.py`, `test_generator.py`, `test_swift_packages.py`,
      `test_icon.py` (already moved in Step 1 — skip), `test_xcframeworks.py`,
      `test_plist_sources.py`: `kivyforge.project.*` → `kivyforge.ios.*`
- [ ] `tests/ios/xcode/test_commands.py`, `test_runner.py`:
      `kivyforge.xcode.*` → `kivyforge.ios.xcode.*`
- [ ] `tests/artifacts/test_collect.py`, `tests/cli/test_build_run_open.py`,
      `tests/cli/test_common.py`: any `kivyforge.project`/`kivyforge.xcode`
      references → `kivyforge.ios` / `kivyforge.ios.xcode`.

Packaging / config references to `project/templates`:

| File | Old | New |
|------|-----|-----|
| `MANIFEST.in:4` | `recursive-include kivyforge/project/templates *` | `recursive-include kivyforge/ios/templates *` |
| `pyproject.toml:83` (coverage omit) | `"kivyforge/project/templates/*"` | `"kivyforge/ios/templates/*"` |

Sanity sweep (should return nothing after this step):

```
rg -n "\.\.project\b|from \.\.xcode|kivyforge\.project\b|kivyforge\.xcode\b|kivyforge/project" kivyforge tests pyproject.toml MANIFEST.in
```

- [ ] `pytest -q` + `ruff check .`

> Note the deliberate non-collision: after Step 4, iOS backend *metadata* lives
> at `targets/ios/`, while the iOS *bundler* lives at `ios/`. Distinct packages,
> distinct roles. (This also pre-stages the eventual Tier 2 platform-first move.)

---

## Step 3 — symmetric doctor filenames: `checks.py` → `checks_ios.py`

`doctor/` has `checks.py` (iOS + neutral) alongside `checks_macos.py` /
`checks_linux.py`. Rename for symmetry. This is a pure rename (the neutral
helpers stay put; see optional carve-out below).

- [ ] `git mv kivyforge/doctor/checks.py kivyforge/doctor/checks_ios.py`
- [ ] (If a matching `tests/doctor/test_checks.py` exists, `git mv` it to
      `test_checks_ios.py` and update its imports.)

Import updates:

| File | Old | New |
|------|-----|-----|
| `kivyforge/doctor/runner.py:11` | `from . import checks as C` | `from . import checks_ios as C` |
| `kivyforge/doctor/checks_macos.py:18` | `from .checks import _ver_tuple` | `from .checks_ios import _ver_tuple` |
| `kivyforge/doctor/checks_linux.py:29` | `from .checks import _ver_tuple` | `from .checks_ios import _ver_tuple` |

- [ ] `pytest -q` + `ruff check .`

> **Optional refinement (small carve-out, still safe):** the platform-neutral
> checks that `checks_macos`/`checks_linux` reuse (`_ver_tuple`, the shared
> version / app-source checks) technically belong in a `checks_common.py`, so
> `checks_ios.py` holds *only* iOS checks. If you want true symmetry-over-a-base,
> extract those into `doctor/checks_common.py` and repoint the three
> `checks_<os>.py` + `runner.py` imports at it. Skip if you just want the rename.

---

## Step 4 — fix the `platforms/` misnomer: rename to `targets/`

`platforms/` only holds the `Platform` ABC + ~30-line metadata/host-capability
backends + the `resolve_target` registry. It is a *target registry*, not where
platform code lives. Rename so the name matches the role.

- [ ] `git mv kivyforge/platforms kivyforge/targets`
- [ ] `git mv tests/platforms tests/targets`

Internal relative imports inside the package (`from .base import ...`,
`from .ios import IosPlatform`, etc.) are unchanged.

Import updates:

| File | Old | New |
|------|-----|-----|
| `kivyforge/cli/_platform.py:16,21` | `from ..platforms import (...)` | `from ..targets import (...)` |
| `kivyforge/cli/doctor.py:29` | `from ..platforms import PlatformResolutionError` | `from ..targets import PlatformResolutionError` |
| `kivyforge/cli/doctor.py:30` | `from ..platforms import resolve_target as _resolve_platform` | `from ..targets import resolve_target as _resolve_platform` |
| `kivyforge/cli/_linux.py:23` | `from ..platforms import HostCapabilityError, get_platform` | `from ..targets import ...` |
| `kivyforge/cli/_macos.py:24` | `from ..platforms import HostCapabilityError, get_platform` | `from ..targets import ...` |
| `tests/cli/test_package.py:20` | `from kivyforge.platforms.ios import IosPlatform` | `from kivyforge.targets.ios import IosPlatform` |
| `tests/targets/test_platforms.py:7,13-16` | `from kivyforge.platforms...` | `from kivyforge.targets...` |

> Optional: `cli/_platform.py` is now a slightly stale name (it's the target
> selection glue). Leave it, or rename to `cli/_target.py` in the same pass and
> update `build.py`/`run.py`/`package.py`/`clean.py` importers of
> `platform_option` / `resolve_target`. Lower priority than the package rename.

Sanity sweep (should return nothing):

```
rg -n "kivyforge\.platforms|from \.\.platforms|from \.platforms|kivyforge/platforms" kivyforge tests
```

- [ ] `pytest -q` + `ruff check .`

---

## Step 5 — docs + wrap-up

- [ ] Update the "Module layout" section of
      `docs/design/platforms/linux/linux-spec.md` (lines ~372-386) and the macOS
      spec's equivalent: `kivyforge/platforms/linux/` → `kivyforge/targets/linux/`.
      (iOS docs referencing `project/`/`xcode/` → `ios/` / `ios/xcode/`.)
- [ ] Update `platforms/base.py`'s module docstring reference / any prose that
      says "platforms" registry to "targets".
- [ ] Full green run: `pytest` (coverage gate ≥ 80% still enforced) + `ruff check .`.
- [ ] Grep the whole tree once more for stragglers:
      `rg -n "kivyforge\.(project|xcode|platforms)\b|\.\.(project|platforms)\b|from \.\.xcode"`

---

## Resulting layout (Tier 1)

```
kivyforge/
  icon.py            # shared icon-source validation (was project/icon.py)
  ios/               # iOS bundler (was project/) + xcode/ (was top-level xcode/)
    xcode/
    templates/
  macos/             # unchanged
  linux/             # unchanged
  targets/           # was platforms/ — Platform ABC + backends + resolve_target
    base.py  ios/  macos/  linux/
  lock/              # unchanged (shared core + lock/macos/ + lock/linux/)
  doctor/            # checks_ios.py / checks_macos.py / checks_linux.py (+ runner)
  cli/  config/  artifacts/  tools/
```

Bundler layer now reads symmetrically (`ios/`, `macos/`, `linux/`), `project/`
is gone, and `targets/` names its actual role.

---

## Deferred to Tier 2 (separate decision — larger / higher risk)

- **`lock/ios/`**: carve the embedded iOS profile/resolver out of the shared
  `lock/` core so `lock/` = shared core + `ios/ macos/ linux/`. Invasive because
  iOS is the embedded default in `resolver.py`/`builder.py`.
- **`cli/_ios.py`**: extract the iOS path out of the iOS-first
  `build.py`/`run.py`/`package.py` verbs so all three platforms dispatch
  symmetrically.
- **Full platform-first consolidation**: fold each platform's bundler + lock +
  doctor + cli + backend into a single `targets/<os>/` (or `platforms/<os>/`)
  package. This is the end-state `platforms/base.py` foreshadowed; pursue only
  if the concern-first scatter still feels wrong after Tier 1.
```
