# `uv.lock` as the central lock — findings

**Question (from a user):** is one lockfile per target a necessary design? Would
a central `uv.lock` — which also carries supply-chain tooling such as cooldown
periods on new releases — be better, or at least a source the per-target locks
could be derived from?

Run with `uv 0.12.21` in a throwaway venv on Windows, 2026-10-01, against the
real [kivy-mobile-wheels](https://github.com/ElliotGarbus/kivy-mobile-wheels)
index. Nothing in the repo was changed. Background:
[`03-lockfile-concept.md`](../common/03-lockfile-concept.md) ("Prior art: uv"),
[`resolver-findings.md`](resolver-findings.md).

## Result

`uv.lock` is **not a replacement** for `pylock.<platform>.toml`, but uv is a
good **resolver backend and a good source of version pins**. The per-target
files stay; what changes is how they are produced and what feeds them.

| Need | Result |
|---|---|
| Resolve Android wheels for one target | **Works.** `uv pip compile --python-platform aarch64-linux-android --python-version 3.14 --only-binary :all:` with `ANDROID_API_LEVEL=24` selected the Kivy 2.3.1 and pyjnius `android_24_arm64_v8a` wheels. |
| Emit PEP 751 with hashes | **Works.** `--format pylock.toml` writes a URL and sha256 per wheel. uv requires the filename `pylock.<name>.toml` with no dots in `<name>`, so kivyforge's `pylock.<platform>.toml` names are accepted. |
| Android in a universal `uv.lock` | **Fails.** `tool.uv.required-environments = ["sys_platform == 'android' and platform_machine == 'aarch64'"]` reports "no compatible wheels" for `kivy==2.3.1` and also for `pyjnius==1.8.0`, whose Android wheel is on PyPI. Android wheels are selected by an API-level tag (`android_24_*`), which a marker-based environment cannot express **in uv 0.12.21**. This is a current limitation of uv's universal mode, not of Android support generally: `--python-platform` already handles Android, so the gap may close. |
| iOS in a universal `uv.lock` | **Partly.** `sys_platform == 'ios' and platform_machine == 'arm64'` resolved a trivial `numpy` project. Not tested with Kivy (needs Python 3.15, not installed on the test host). |
| Cooldown on PyPI | **Works.** `--exclude-newer "7 days"` is accepted; PyPI entries carry `upload-time`. |
| Cooldown on the kivy-mobile-wheels index | **Fails.** Under any `--exclude-newer`, `kivy==2.3.1` is unsatisfiable: "has no publish time". The index is a static PEP 503 page of links plus a hash, with no upload dates, and uv warns that each wheel "is missing an upload date". |
| Runtime pin, native artifacts, device vs simulator | Not modeled by `uv.lock`; this is what `[tool.kivyforge]` holds. |

### Detail worth keeping

- The first `uv pip compile` run (without `--only-binary`) "worked" for Android
  by quietly choosing the PyPI sdist for pyjnius 1.8.0 over the index's wheel.
  Binary-only is required, which matches kivyforge's existing host-independent,
  no-source-build invariant.
- With `ANDROID_API_LEVEL=21`, uv rejected the `android_24_*` wheels and
  listed the platforms that were available. The level must be at least the
  wheel's, so a `uv` backend must pass kivyforge's `min_sdk`-derived level, not
  a default.
- `--index-strategy unsafe-best-match` was needed to see the index's Kivy
  version alongside PyPI's. By default uv uses only the first index that
  contains a package (a dependency-confusion defence), so a backend should
  prefer explicit per-package indexes over `unsafe-best-match`.

## Upstream status (checked 2026-10-01)

There is no published uv roadmap for mobile platforms; the signal is in the
issue tracker (`astral-sh/uv`) and the docs.

- **Platform tags: shipped.** iOS tags were added in
  [#15640](https://github.com/astral-sh/uv/pull/15640) (merged 2025-09-03, for
  [#8029](https://github.com/astral-sh/uv/issues/8029), now closed). The
  `--python-platform` list includes `aarch64-linux-android`,
  `x86_64-linux-android`, `arm64-apple-ios`, `arm64-apple-ios-simulator`, and
  `x86_64-apple-ios-simulator` (seen in `uv pip compile --help`, 0.12.21). This
  is what the per-target `uv pip compile` result above relies on.
- **Running uv on Android (Termux): in progress, separate from our need.**
  Python 3.13+ on Android was fixed in
  [#18301](https://github.com/astral-sh/uv/pull/18301), an `aarch64-linux-android`
  CI build was added ([#18333](https://github.com/astral-sh/uv/pull/18333)),
  and a `lock_android` test exists (see
  [#20602](https://github.com/astral-sh/uv/pull/20602)). Those cover uv as a
  tool on an Android host, not locking for Android from another host. Android
  host builds as a release target are tracked in
  [#14574](https://github.com/astral-sh/uv/issues/14574) (open).
- **Cross-platform environments: open, no commitment.**
  [#7957](https://github.com/astral-sh/uv/issues/7957) (opened by the BeeWare
  maintainer) asks for what a mobile cross-build needs: an environment that
  resolves for the target but is built from the host. A uv maintainer replied
  in 2024 that they would be surprised if they had time to build it soon and
  asked about demand. The issue was last active 2025-06-02, and its latest
  discussion proposes PEP 739 `build-details.json` as the mechanism.
- **Docs: nothing on mobile in the project configuration.** The
  `environments` / `required-environments` documentation shows only desktop
  `sys_platform` examples and does not mention Android or iOS.
- **Not found:** an issue or PR for Android (or iOS) support in the universal
  lock's `required-environments`. The failure I saw has no tracking issue that I
  could find. It is worth filing, with the reproduction from the Result table.

**Reading:** per-target resolution (`--python-platform`) is supported now and
unlikely to regress. Universal-lock coverage of mobile has no owner or date, so
plan on the per-target path and do not depend on it arriving.

## Recommendation

1. **uv as an optional resolver backend.** Implement it behind the existing
   `Resolver` protocol (`kivyforge/lock/resolver.py`). Pass through
   `exclude-newer` and `exclude-newer-package` so a cooldown applies to every
   target. This is the smallest change with the most value and keeps the lock
   format unchanged.
2. **`uv.lock` as a version-pin input.** When a project has a `uv.lock`, derive
   constraints from it (via `uv export`) when resolving each target. The user
   maintains versions in one place, and the per-target locks differ only in the
   wheels chosen for that platform's tags. Until uv's universal lock can cover Android, this
   supplies versions only; Android wheels are still resolved per target. If uv
   gains Android support in `uv.lock`, revisit this and consider deriving the
   Android lock from it directly. If a pinned version has no wheel for a target, `lock` fails and names
   the package and target (the existing fail-fast rule).
3. **Give the kivy-mobile-wheels index upload times** (PEP 700 JSON). Until it
   does, anyone who sets a cooldown cannot resolve Kivy from it.

## Not tested

- `exclude-newer-package` as a per-package exemption for index packages that
  lack upload dates.
- iOS with Kivy 3.0 (CPython 3.15), and whether uv's iOS platform tags cover the
  device versus simulator split for the mobile wheels.
- Whether `uv export` produces usable constraints from a `uv.lock` that was
  resolved only for desktop environments.
- Other hosts. This ran on Windows only.
- Newer uv releases. The Android limitation is specific to 0.12.21; re-run the
  universal `required-environments` test when uv adds Android support.

## Open design points

- **Which wins when `uv.lock` and the per-target lock disagree?** Proposed: the
  per-target lock is derived output, regenerated by `kivyforge lock`; `--check`
  reports it stale when `uv.lock` or `pyproject.toml` changes. This needs the
  lock's drift hash to include the `uv.lock` contents when one is used.
- **Dependency on uv.** It should stay optional ([`future_enhancements.md`](future_enhancements.md)). The pip backend remains the
  default so kivyforge works without uv installed.
