# Proposal — choose which index, or local wheelhouse, each package comes from

> Status: **proposed 2026-10-21**, decisions taken with the maintainer the same
> day (§2), for
> [#86](https://github.com/ElliotGarbus/kivyforge/issues/86). Nothing here is
> implemented yet. Both parts are planned before the release (§9). §1 describes
> the code as of `2aefa0e4`, with no line numbers, because the files move.

## Summary

- **Problem.** `extra_index_urls` and `find_links` are all-or-nothing: every
  package can come from every source, and pip picks among them by version,
  then wheel tag, then an accident of ordering. A wheel in the user's own
  wheelhouse loses to an index wheel of the **same version** (§1.2), and of two
  extra indexes that ship the same version, the **last listed** wins. That
  last-listed rule is the "reverse order" kengoon reported.
- **Decisions.**
  1. **The local wheelhouse is exclusive.** A package name that has any wheel
     in a `find_links` directory comes only from `find_links`, on every
     variant, even when an index has a newer version or a better tag.
  2. **Named indexes and per-package sources**, on the uv model:
     `[[tool.kivy.index]]` (`name`, `url`, `explicit`) and
     `[tool.kivy.sources]`, which a platform overlay can extend or override.
  3. **Enforcement is a candidate filter in `_pip_shim.py`**, which all three
     resolvers run pip through. pip still does the whole resolution; the
     filter only removes candidates from sources a package may not use.
  4. **The lock records where each package came from**, in PEP 751's
     `packages.index`.
  5. **Both parts land before the release.**
- **pip will not do this itself.** It deliberately does not rank candidates by
  source ([pypa/pip#9959](https://github.com/pypa/pip/issues/9959)), and it has
  no per-package index option.

## 1. What happens today

### 1.1 How sources reach pip

Every platform overlay has `extra_index_urls` and `find_links`
(`kivyforge/config/keys.py`, `_OVERLAY_COMMON`). The loader keeps them per
platform (`IosConfig.extra_index_urls` and so on in `kivyforge/config/model.py`).
`find_links` entries must be repo-relative directories
(`kivyforge/lock/find_links.py`). Each resolver passes them to
`pip install --dry-run --report` unchanged:

| Resolver | Runs pip as | Per |
|---|---|---|
| `kivyforge/lock/wheelruntime/resolver.py` (macOS, Linux, Windows) | `python -m pip` | variant (arch and its tag ladder) |
| `kivyforge/platforms/android/lock/resolver.py` | `python _pip_shim.py` | ABI |
| `kivyforge/platforms/ios/lock/resolver.py` | `python _pip_shim.py` | slice |

Each `extra_index_urls` entry becomes `--extra-index-url` (PyPI stays the
`--index-url`), each `find_links` entry becomes `--find-links`, and `lock
--offline` adds `--no-index`. The pin preference from #126
(`kivyforge/lock/prefer.py`) adds a `-c` constraints file of `name==version`.

A wheel found through `find_links` is written to the lock as a repo-relative
`path`; any other wheel as a `url`. `build` installs from the lock and never
consults an index or `find_links`. So the source of a package is decided once,
by `lock`, and then fixed.

`LockedPackage.source_index` and its `[packages.tool.kivyforge] source_index`
serialization exist, but no resolver ever sets them. The standard PEP 751
`packages.index` key is never written.

### 1.2 What pip chooses: experiment

The setup is hermetic, with pip 26.1.2 on Windows on 2026-10-21. Every "index"
is a local PEP 503 tree reached through a `file://` URL, and `--index-url`
points at a local stand-in for PyPI. The flags are the Android resolver's
(`--dry-run --report --only-binary=:all: --python-version 3.14 --platform
android_24_arm64_v8a --abi cp314 ...`). The scripts and their output are kept
with the session notes for #86. The results:

| # | Case | pip picked |
|---|---|---|
| 1 | Same version, same tag, in find_links and on the index | **index** |
| 2 | Index has a newer version | index (newest) |
| 3 | Same as 2, with constraint `==1.0` | 1.0, **from the index** |
| 4 | Index wheel's tag is more specific (`cp314-cp314-android_24_arm64_v8a`) than the local `py3-none-any` | index (tag priority) |
| 5 | Local wheel carries a build tag | find_links (the build tag sorts higher) |
| 6 | `--no-index`, find_links only | find_links |
| 7 | Constraint `name @ file:///…/name-1.0-py3-none-any.whl` | find_links |
| 8 | Same version on the primary and on one extra index | the extra |
| 9 | Same version on the primary and two extras `a, b` | `b` |
| 10, 11 | Same version on extras only, listed `a, b`, then `b, a` | the last listed each time |
| 12 | The two indexes swapped between primary and extra | the extra |

**Why.** `PackageFinder.find_all_candidates` returns find_links files before
index pages ("an intentional priority ordering"). `find_best_candidate` then
sorts them stably by (hash, yanked, version, tag priority, build tag), and
the resolvelib factory walks that list in **reverse** and keeps the first
candidate per version. Among equals, the source listed last wins: an index
beats find_links, and a later extra index beats an earlier one. pip's
maintainers treat the absence of a source preference as policy, as a defence
against dependency confusion ([pypa/pip#9959](https://github.com/pypa/pip/issues/9959)).

Two consequences for the design:

- **A version constraint cannot make find_links win** (case 3). Only removing
  the other candidates (case 6, or the filter in §4) or a direct-URL constraint
  (case 7) does.
- **The tie rule is incidental.** It is documented in §7 as today's behaviour,
  and nothing new depends on it.

### 1.3 Prior art

| Tool | Name an index | Index only for packages pinned to it | Pin a package | Local wheels |
|---|---|---|---|---|
| uv | `[[tool.uv.index]]` `name` | `explicit = true` | `[tool.uv.sources] x = { index = "n" }` | an index with `format = "flat"`; the default `first-index` strategy limits a package to the first index that has it |
| PDM | `[[tool.pdm.source]]` `name` | `include_packages` globs | `include_packages` / `exclude_packages` | `type = "find_links"` |
| Poetry | `[[tool.poetry.source]]` `name` | `priority = "explicit"` | `x = { version = "…", source = "n" }` | — |
| Briefcase | — | — | — | `requirement_installer_args = ["--find-links", …]`, passed through to pip unvalidated |

kivyforge follows uv's shape, because kengoon already uses it and it maps onto
pip one-to-one. The exception is find_links, which keeps its own key and gains
the exclusivity that uv gives a first-listed flat index.

## 2. Decisions (2026-10-21)

| Question | Decision | Rejected |
|---|---|---|
| How strong is "local first"? | **Exclusive**, per package name, across all variants (§3.1) | Tie-break only (a newer PyPI upload silently replaces a local build); opt-in flag (keeps the surprising default) |
| How is it enforced? | **Candidate filter in `_pip_shim.py`** (§4) | Two pip passes with direct-URL constraints (§10.1) |
| Where does the config live? | **Shared, with overlay sources** (§3.2) | Indexes and sources per overlay only |
| What lands before release? | **Both parts** (§9) | Local-first only; docs only |

## 3. Behaviour and config

### 3.1 Local wheelhouse: exclusive

A **local name** is the canonical project name parsed from any `*.whl`
filename in the platform's `find_links` directories, whatever its tags.

- A local name gets candidates **only** from `find_links`, for every variant,
  whether or not an index has a newer version or a better-tagged wheel.
- If no wheel there fits a variant, that variant fails with
  `KF-LOCK-SOURCE-UNAVAILABLE` (§6). It does **not** fall back to an index: a
  lock with the local Kivy on arm64 and PyPI's on x86_64 would be worse than
  an error.
- `find_links` overrides `sources`. A package that both has a local wheel and
  is pinned to an index is a config error (`KF-SOURCE-CONFLICT`, §6), because
  silently picking one would hide the other.
- To use the index version again, remove the wheel from the directory.

Presence is decided by name rather than by "a compatible candidate exists",
for the reason in the second bullet: per-variant fallback would quietly mix
sources across ABIs.

### 3.2 Named indexes and sources

```toml
# Shared: declared once, for every platform.
[[tool.kivy.index]]
name = "mobile"
url = "https://elliotgarbus.github.io/kivy-mobile-wheels/simple/"
explicit = true            # serves only the packages pinned to it

[[tool.kivy.index]]
name = "corp"
url = "https://pypi.example.com/simple/"   # not explicit: a normal extra index

[tool.kivy.sources]
mycorp-utils = { index = "corp" }

# Per platform: adds pins or overrides shared ones, by name.
[tool.kivy.android.sources]
kivy = { index = "mobile" }
pyjnius = { index = "pypi" }

[tool.kivy.ios.sources]
kivy = { index = "mobile" }
```

**`[[tool.kivy.index]]`** is an array of tables:

| Key | Type | Required | Meaning |
|---|---|---|---|
| `name` | string | yes | Unique, `[A-Za-z0-9._-]+`. `pypi` is reserved. |
| `url` | string | yes | PEP 503/691 simple index base URL, `http(s)://` only. A URL with credentials in it is refused (§3.4). |
| `explicit` | bool | no, default `false` | `true`: only packages pinned to this index may come from it. `false`: it is also an extra index for every platform. |

**`pypi`** is a built-in name for `https://pypi.org/simple/`, the `--index-url`
kivyforge already uses, so a package can be pinned to PyPI without declaring
anything.

**`[tool.kivy.sources]` and `[tool.kivy.<platform>.sources]`** map a package
name, compared in canonical form, to `{ index = "<name>" }`. The inline table
matches uv, so a `[tool.uv.sources]` line of that form can be copied as is.
Any other key, such as uv's `git`, `url`, `path` or `marker`, is refused with
a message: kivyforge locks wheels only, and a platform overlay already plays
the role of uv's `marker` for platform splits. A name that resolves to no
declared index is a config error that suggests the closest name.

**The effective configuration for a platform** is computed by the loader and
stored on that platform's config, which also keeps the lock-input projection
precise (§5.1):

- `sources`: the shared map, overlaid name by name with the platform's map.
- `indexes`: every non-explicit named index, plus the explicit indexes that
  this platform's `sources` refer to.

**Non-explicit named indexes apply to every platform.** An index that serves
one platform only either stays in that overlay's `extra_index_urls`, as the
mobile examples do today, or is declared `explicit` and pinned per overlay, as
above. `extra_index_urls` keeps working unchanged: unnamed, non-explicit,
platform-local.

### 3.3 Which sources a package may use

For each project pip asks about, in this order:

1. **Local name** (§3.1): `find_links` only.
2. **Pinned** (`sources` names it): that index only.
3. **Otherwise**: PyPI, every non-explicit named index and every
   `extra_index_urls` entry. Explicit indexes are excluded. Among those
   sources pip chooses as it does today (newest version, then tag, then the
   tie rule in §1.2).

A pin applies to the package wherever it appears in the graph, direct or
transitive. That differs from Poetry, whose `source` does not reach a
package's own dependencies, and matches uv.

### 3.4 Validation (config errors, exit 1)

- duplicate index `name`, the reserved `pypi`, or an invalid name;
- a `url` that is not `http(s)://`, or that contains `user:pass@`. The URL is
  written into the lock (§5.4), and credentials must not be. Authenticated
  indexes are an open question (§11);
- a `sources` entry naming an unknown index, or using a key other than `index`;
- `explicit` set on an index that no platform's sources refer to: a warning
  (`KF-LOCK-WARNING`), not an error, since a platform may simply not be
  configured yet.

`KF-SOURCE-CONFLICT` (§3.1) is raised by `lock`, not by the loader, because
it depends on the contents of the `find_links` directories.

## 4. Mechanics: the filter in `_pip_shim.py`

### 4.1 What it patches

The shim already replaces one pip internal, the vendored
`packaging.markers.default_environment`, and then calls pip's `main()`
unchanged. A second, independent patch wraps
`pip._internal.index.package_finder.PackageFinder.find_all_candidates(project_name)`.
That function returns every file pip found for a project, from the index
URLs, extra index URLs and find-links, after link evaluation has dropped
files whose tags do not fit the target. The wrapper removes the candidates
§3.3 disallows and returns the rest; it also replaces pip's per-project cache
entry, so the filtered list is what every later lookup sees. Version
selection, backtracking and the dependency graph are untouched.

### 4.2 The policy

kivyforge builds the policy per resolve and passes it as JSON in
`KIVYFORGE_SOURCE_POLICY`, the same way the marker environment travels in
`KIVYFORGE_TARGET_MARKER_ENV`:

```json
{
  "find_links": ["C:/…/wheels"],
  "local_names": ["kivy"],
  "indexes": {"pypi": "https://pypi.org/simple/", "mobile": "https://…/simple/"},
  "explicit": ["mobile"],
  "sources": {"pyjnius": "pypi"},
  "record": "C:/…/kivy-lock-xyz/sources.json"
}
```

kivyforge computes `local_names` from the directory listings, not the shim,
so that `KF-SOURCE-CONFLICT` can be raised before pip starts.

### 4.3 Identifying a candidate's source

A candidate is identified by `candidate.link.comes_from`, the page its link
was found on, **not** by its file URL. Index pages link to files on other
hosts: PyPI's link to `files.pythonhosted.org`, and kivy-mobile-wheels' to
`github.com/…/releases/download/…` (checked 2026-10-21). A page belongs to the
configured index whose base URL it starts with, after normalizing a trailing
slash. A `file:` link whose path lies under a `find_links` directory is local.
A candidate whose source matches nothing configured is dropped, so the filter
fails closed.

### 4.4 Recording the source

When the run succeeds, the shim writes `record`: a JSON map from every
surviving candidate's file URL to its index name, or `"find_links"`. The
resolver reads it next to pip's `--report`, looks up each installed item's
`download_info.url`, and sets `ResolvedPackage.source_index` to the index
**URL** (§5.4). This is the only way to learn it: `--report` does not include
`comes_from`.

### 4.5 One shim for all three resolvers

The desktop resolver moves from `python -m pip` to the shim. The shim keeps
its refusal to fall back silently to host markers, and gains one explicit way
to say "host markers on purpose":

- `KIVYFORGE_TARGET_MARKER_ENV` set: retarget markers (Android, iOS, as now);
- `KIVYFORGE_HOST_MARKERS=1` set: leave markers alone (desktop, which is the
  behaviour today, including its known cross-host marker bug, §11);
- neither set: refuse, as now.

With no `find_links`, `sources` or explicit index, kivyforge does not set
`KIVYFORGE_SOURCE_POLICY`; the shim then patches nothing and pip behaves
exactly as it does today, which experiment B10 confirms.

### 4.6 Failure modes

- **A pip that lacks `PackageFinder.find_all_candidates`,
  `InstallationCandidate.link` or `Link.comes_from`**: the shim exits with a
  distinct status, and the resolver raises `KF-PIP-UNSUPPORTED` (§6) naming the
  pip version. It never resolves unfiltered: a silent fallback would bring
  back the wrong-source lock this exists to prevent. This is the marker
  shim's rule.
- **A filtered-out package**, that is, a pinned package its index does not
  have, or a local name with no wheel for this variant: pip says "Could not
  find a version that satisfies the requirement" (experiments B8, B9). The
  resolver recognizes the package (`unresolved_requirement()` already
  extracts it) and, when that package is pinned or local, raises
  `KF-LOCK-SOURCE-UNAVAILABLE` (§6) instead of the generic message.

### 4.7 Prototype results

A 40-line prototype of §4.1 was run with the same harness as §1.2. It
matched on file URLs, which is enough for local `file://` indexes; §4.3
corrects that for real ones.

| # | Policy | Result |
|---|---|---|
| B1 | local `same 1.0`, index `same 1.0` | find_links |
| B2 | local `1.0`, index `1.1` | find_links 1.0 |
| B3 | local `py3-none-any`, index android-tagged | find_links |
| B4 | local `app` whose dependencies are split across find_links and an extra index | each from its own source |
| B5 | local `1.0`, with a lock pin `==1.1` | conflict (handled by §5.2) |
| B6 | package pinned to explicit index `a`, extras `a, b` | `a` |
| B7 | package not pinned, `a` explicit, extras `a, b` | `b` |
| B8 | package not pinned, `a` and `b` both explicit | no candidates |
| B9 | package pinned to an index that does not have it | no candidates |
| B10 | empty policy | unchanged from pip |

## 5. Lock interactions

### 5.1 Lock inputs

Each platform's `LOCK_INPUTS` (`kivyforge/lock/inputs.py`) gains
`<platform>.indexes` and `<platform>.sources`, the effective values from
§3.2. Adding a pin for Android does not stale the iOS lock, and an explicit
index that only Android uses is not an iOS input.
`tests/lock/test_lock_inputs.py` already fails if a builder reads a field that
is missing from the projection.

The **contents** of `find_links` directories stay outside the projection, as
they are today. Adding a wheel with a new name makes that name local; the
lock is not marked stale, but `lock --check` sees the difference (§5.3) and
`lock` or `lock --update` applies it. This is the existing rule for vendored
wheels.

### 5.2 Pin preference

`preferred_pins()` drops, before resolving, the pin of any locked package
whose recorded source the policy no longer allows. This mirrors the existing
rule for a direct requirement whose specifier has moved:

- the locked wheels are `url`s, but the name is now local;
- the locked wheels are `path`s, but the name is no longer local;
- the name is pinned, and the lock's `index` for it is a different URL, or is
  missing (a lock written before this change).

Without this, the old pin and the new source collide and the user gets
`KF-LOCK-PINS-CONFLICT` with advice to run `--update`, which moves every
other package too (experiment B5). With it, only the package whose source
changed moves.

### 5.3 `lock --check`

It builds its candidate with the same policy and pin preference, so a project
whose config and wheelhouse have not changed still checks clean. A wheelhouse
that gained a local name makes `--check` fail with `KF-LOCK-DRIFT`, which is
correct: the next `lock` would produce a different file.

### 5.4 The PEP 751 lock

- Each package that came from an index gets the standard `index = "<base
  URL>"` key, which the spec says "SHOULD" be recorded. It makes the bug in
  #86, a pyjnius from the wrong index, visible in a lock diff. Packages from
  `find_links` keep their `path` and get no `index`.
- The URL is written, not the index name. The lock describes what was
  resolved, and names belong to the config.
- `[packages.tool.kivyforge] source_index`, which was never populated, is no
  longer written. The parser keeps reading it, for any lock that has it.
- `build` behaviour is unchanged. It installs the recorded `url` or `path`,
  and does not use `index`. PEP 751 allows an installer to fall back to it
  when a URL is dead; kivyforge does not, and that is an open question (§11).

## 6. Failure classification

New codes in `kivyforge/report/diagnostics.py`:

| Code | Exit | When | `context` |
|---|---|---|---|
| `KF-SOURCE-CONFLICT` | 1 | A local name is also pinned in `sources` (§3.1) | `distribution`, `index`, `find_links` |
| `KF-LOCK-SOURCE-UNAVAILABLE` | 1 | A pinned or local package has no candidate on its only allowed source for a variant | `distribution`, `source` (index name or `find_links`), `variant` |
| `KF-PIP-UNSUPPORTED` | 3 | The shim cannot apply its patch to this pip (§4.6); the fix is the machine's pip | `pip_version`, `missing` (the internal not found) |

`KF-TOOLCHAIN-UNUSABLE` is not reused for the third: it means a tool that
cannot be executed at all, and a code is never repurposed (AGENTS.md).

Example message for the second:

```
error: pyjnius is pinned to index 'pypi' (https://pypi.org/simple/) in
[tool.kivy.android.sources], and that index has no wheel for android_24_x86_64.
  Fix: pin it to an index that has one, remove the pin, or add the wheel to a
  find_links directory.
```

Config errors (§3.4) are the loader's existing `ConfigError`, with `key_path`
and line.

## 7. Docs

- `docs/guides/concepts/runtimes-and-wheels.md` gains a "Where packages come
  from" section: the three rules of §3.3; that `find_links` is exclusive; and
  how pip chooses among non-explicit indexes, newest version, then best tag,
  then **the last listed index** on a tie, with a note that this tie rule is
  pip's and may change.
- `docs/guides/reference/pyproject/tool-kivy.md` documents `[[tool.kivy.index]]`,
  `[tool.kivy.sources]` and `pypi`; each platform page there documents its
  `sources` table.
- The `find_links` and `extra_index_urls` rows in the platform specs
  (`android/01`, `ios/01`, macOS, Linux and Windows specs) link to that section
  and state that `find_links` is exclusive.
- `docs/guides/reference/lockfile.md` documents `packages.index`.
- `docs/guides/reference/codes.md` gains the three new codes, and `capabilities`
  lists them (its code vocabulary comes from `diagnostics.py`).
- Reply on #86 with kengoon's case written in the new config.

## 8. Tests to write

All hermetic. The pip-level tests use local `file://` indexes and wheels built
in `tmp_path`, as in the §1.2 harness, and no network.

**Config (`tests/config/`)**
- `[[tool.kivy.index]]` parses; duplicate name, `pypi`, a bad name, a
  non-http URL and a URL with credentials each fail with `key_path` and line.
- `sources` with an unknown index fails with a closest-name hint; uv's `git`,
  `path` and `marker` keys fail with the wheels-only message.
- Effective merge: an overlay entry overrides the shared one by canonical
  name; effective `indexes` contains the non-explicit indexes plus only the
  referenced explicit ones.
- `keys.py` allow-list: the new tables are accepted, and a typo in them is
  reported.

**Shim (`tests/lock/test_pip_shim.py`, running the real shim and real pip)**
- The canary: the filter applies with the installed pip, so a pip upgrade that
  breaks the patch fails CI rather than resolving unfiltered.
- Each row of §4.7, with candidates identified by `comes_from` from an index
  page whose files are hosted under a **different** directory than the page,
  which stands in for files.pythonhosted.org and GitHub releases.
- No policy set: the shim patches nothing (pip output matches `-m pip`).
- Neither marker variable set: refuses; `KIVYFORGE_HOST_MARKERS=1`: runs.
- The patched symbol is missing (monkeypatched away): distinct exit status,
  and the resolver maps it to `KF-PIP-UNSUPPORTED`.
- `record` maps each surviving file URL to the right index name.

**Resolvers and builders (`tests/lock/`, `tests/platforms/*/lock/`)**
- All three resolvers pass the policy and set `source_index` from the record;
  the desktop resolver now invokes the shim.
- A local name with no wheel for one ABI raises `KF-LOCK-SOURCE-UNAVAILABLE`
  naming that ABI; there is no fallback to an index.
- A local name that is also pinned raises `KF-SOURCE-CONFLICT` before pip runs.
- `preferred_pins()` drops a pin for each of the three source-change cases in
  §5.2 and keeps the others.
- `test_lock_inputs.py` covers `indexes` and `sources` for every platform; a
  shared pin used only by Android leaves the iOS hash unchanged.

**Lock file (`tests/lock/test_pep751*.py`)**
- `index` is written for index packages and omitted for `path` packages;
  `source_index` is read but not written; a round trip is stable.

**CLI**
- `lock --check` is clean on an unchanged project with a policy, and reports
  drift after a wheel with a new name is added to `find_links`.
- `--json`: the new codes appear in `diagnostics[].code` with their `context`.

## 9. Delivery and migration

Both parts land before the release, as **two PRs** in this order, so the
first can ship alone if the second slips:

1. **Shim and local-first.** The shim filter (§4) with only `find_links`
   rules; the desktop resolver moves to the shim; `packages.index` recorded
   (§5.4); the pin-dropping rule for `url`/`path` changes (§5.2);
   `KF-LOCK-SOURCE-UNAVAILABLE` and `KF-PIP-UNSUPPORTED`; docs for
   `find_links` and today's index order.
2. **Named indexes and sources.** Config (§3.2–3.4), `LOCK_INPUTS` (§5.1),
   the pinned and explicit rules in the policy, `KF-SOURCE-CONFLICT`, the
   rest of the docs, and the reply on #86.

**Migration: none in code**, following #126's policy:

- PR 1 changes lock *output* (a new `index` key on every index package) for
  unchanged inputs, so `lock --check` fails once on every existing lock.
- PR 2 adds lock-input paths, which changes every `lock_inputs_sha256`, so
  every lock reads stale once.
- In both cases the `CHANGELOG.md` migration note says to run `kivyforge lock`
  once per platform; the pin preference keeps every version.
- The one behaviour change is local-first. A project whose wheelhouse holds
  an older version of a package that an index also ships now gets the local
  one. The changelog says so, and how to undo it (remove the wheel). In this
  repo, only the `tests/fixtures/apps/metaprobe` fixture has both `find_links`
  and an extra index.
- The four tracked example locks (`hello-android`, `hello-sdl3`, `hello-kivy`,
  `android-services`) are re-locked in each PR. Each diff should be the hash,
  `generated_at` and the new `index` lines only; any other change is reported,
  not committed (AGENTS.md). `hello-kivy`'s iOS lock needs a Mac, as in #126.

## 10. Alternatives considered

### 10.1 Two pip passes with direct-URL constraints

The first pass resolves each pinned or local package alone, with `--no-deps`
and only its allowed source (`--index-url <pinned>` or `--no-index
--find-links`), and takes the chosen file. The second pass resolves everything
with a `name @ <url>` constraint per package. It works with public pip
behaviour only (experiments A1 to A7: an unused URL constraint is harmless,
and a file URL taken from an index page works with or without its `#sha256`
fragment). It was
rejected because:

- **no backtracking across passes**: pass 1 chooses a version without seeing
  transitive specifiers, so a resolvable graph can fail in pass 2;
- pass 1 has to decide which specifier applies to each package, which is
  resolver logic kivyforge does not own;
- it doubles the pip runs per variant, and Android and iOS already run one per
  ABI or slice;
- it does not answer "which index served this?" for unpinned packages, so
  `packages.index` would stay empty for most of the lock.

### 10.2 Version constraints pinned to the local versions

Writing `name==<local version>` into the constraints file does not work: pip
still takes the index file of that version (experiment case 3).

### 10.3 `--no-index` for local-only packages

`--no-index` is global, so it would also cut off every package that only an
index has. It is a separate pass, which is §10.1 again.

### 10.4 uv's `first-index` strategy for unpinned packages

Limiting each package to the first source that has it is uv's
dependency-confusion defence. With PyPI first it breaks the mobile examples:
Kivy is on PyPI (as an sdist and desktop wheels), so its Android wheel on
kivy-mobile-wheels would never be seen. That is the failure
[`uv-lock-findings.md`](uv-lock-findings.md) hit, which needed
`unsafe-best-match`. With extra indexes first it would change existing
resolutions. Explicit indexes and pins give the same protection where a user
asks for it, so the default stays pip's best-match (§11).

## 11. Open questions

- **Tie order among non-explicit indexes.** It is documented as pip's "last
  listed wins". The filter could make it "first listed wins" deterministically,
  which reads more naturally, but that changes existing locks for no reported
  bug. Revisit if users trip on it.
- **Authenticated indexes.** URLs with credentials are refused because the URL
  goes into the lock. Supporting them means credentials from the environment
  or keyring at lock time, and a credential-free URL in the lock. This waits
  until someone asks.
- **Desktop marker retargeting.** Moving the desktop resolver onto the shim
  makes the cross-host marker bug noted in
  [`lock-inputs-proposal.md`](lock-inputs-proposal.md) §2.3 a small step away
  from fixed (a desktop marker environment), but that fix is not part of this
  work.
- **Index fallback in `build`.** PEP 751 allows an installer to use
  `packages.index` when a recorded URL returns 404. kivyforge pins by hash, so
  this would be safe, but nothing has asked for it.
- **`doctor`.** It could list each platform's effective sources and check
  that the explicit indexes are reachable. That is useful, but not needed
  for the feature.
- **A future uv backend** ([`uv-lock-findings.md`](uv-lock-findings.md)) maps
  the config directly: `[[tool.kivy.index]]` to `--index` with `explicit`, and
  `sources` to `[tool.uv.sources]`. `find_links` exclusivity becomes a
  first-listed flat index. Nothing here blocks it.
