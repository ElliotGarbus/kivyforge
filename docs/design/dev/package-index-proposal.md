# Proposal — choose which index, or local wheelhouse, each package comes from

> Status: **proposed 2026-10-21**, decisions taken with the maintainer the same
> day and revised on 2026-10-22 after the reporter's feedback on
> [#86](https://github.com/ElliotGarbus/kivyforge/issues/86) (§2). Nothing here
> is implemented yet. Both parts are planned before the release (§9). §1
> describes the code as of `2aefa0e4`, with no line numbers, because the files
> move.

## Summary

- **Problem.** `extra_index_urls` and `find_links` are all-or-nothing: every
  package can come from every source, and pip picks among them by version,
  then wheel tag, then an accident of ordering. A wheel in the user's own
  wheelhouse loses to an index wheel of the **same version** (§1.2), and of two
  extra indexes that ship the same version, the **last listed** wins. That
  last-listed rule is the "reverse order" kengoon reported.
- **Decisions.**
  1. **Source precedence: a pin, then local wheels, then indexes.** A package
     pinned in `sources` comes only from its index. Otherwise, a package name
     that has any wheel in a `find_links` directory comes only from
     `find_links`, on every variant, even when an index has a newer version
     or a better tag. Otherwise it comes from the indexes.
  2. **Source selection is separate from version selection.** `lock --update`
     picks newer versions within a package's source and never changes the
     source. A package changes source only when the config or the wheelhouse
     changes.
  3. **Named indexes and per-package sources**, on the uv model:
     `[[tool.kivy.index]]` (`name`, `url`, `explicit`) and
     `[tool.kivy.sources]`, which a platform overlay can extend or override.
  4. **On a tie between indexes, the first listed wins**, with PyPI last.
  5. **Enforcement is a candidate filter in `_pip_shim.py`**, which all three
     resolvers run pip through. pip still does the whole resolution; the
     filter only removes candidates from sources a package may not use, and
     orders the rest so that ties go to the first-listed index.
  6. **The lock records where each package came from**, in PEP 751's
     `packages.index`.
  7. **Both parts land before the release.**
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
- **The tie rule is incidental**, and kengoon found it backwards. kivyforge
  replaces it with "first listed wins" (§3.4), which the filter does by
  ordering candidates (§4.1).

### 1.3 Prior art

| Tool | Name an index | Index only for packages pinned to it | Pin a package | Local wheels |
|---|---|---|---|---|
| uv | `[[tool.uv.index]]` `name` | `explicit = true` | `[tool.uv.sources] x = { index = "n" }` | an index with `format = "flat"`; the default `first-index` strategy limits a package to the first index that has it |
| PDM | `[[tool.pdm.source]]` `name` | `include_packages` globs | `include_packages` / `exclude_packages` | `type = "find_links"` |
| Poetry | `[[tool.poetry.source]]` `name` | `priority = "explicit"` | `x = { version = "…", source = "n" }` | — |
| Briefcase | — | — | — | `requirement_installer_args = ["--find-links", …]`, passed through to pip unvalidated |

kivyforge follows uv's shape, because kengoon already uses it and it maps onto
pip one-to-one. The exception is find_links, which keeps its own key and takes
priority over every index unless a pin says otherwise, much as uv gives
priority to a first-listed flat index.

## 2. Decisions

Taken with the maintainer on 2026-10-21:

| Question | Decision | Rejected |
|---|---|---|
| How strong is "local first"? | **Exclusive**, per package name, across all variants (§3.1) | Tie-break only (a newer PyPI upload silently replaces a local build); opt-in flag (keeps the surprising default) |
| How is it enforced? | **Candidate filter in `_pip_shim.py`** (§4) | Two pip passes with direct-URL constraints (§10.1) |
| Where does the config live? | **Shared, with overlay sources** (§3.2) | Indexes and sources per overlay only |
| What lands before release? | **Both parts** (§9) | Local-first only; docs only |

Revised on 2026-10-22, after kengoon's feedback on #86. He wants to pick up an
upstream Kivy fix with `lock --update` without deleting his patched wheel. The
maintainer proposed, and kengoon agreed, that a pin should outrank the
wheelhouse, so switching sources is an explicit config change and never a side
effect of a version bump:

| Question | Decision | Rejected |
|---|---|---|
| A package is pinned and also has a local wheel | **The pin wins**, and `lock` warns that the local wheels are ignored (§3.1) | A config error, `KF-SOURCE-CONFLICT` (the 2026-10-21 draft, §10.5): it forced deleting the wheel to switch; staying silent: a forgotten pin or stale wheel would go unnoticed |
| Which index wins a tie? | **The first listed** (§3.4) | pip's last-listed rule, which kengoon found backwards |
| The order of indexes | **The platform's `extra_index_urls`, then non-explicit `[[tool.kivy.index]]` entries, then PyPI** (§3.4) | Shared before overlay; PyPI first (changes existing locks) |

## 3. Behaviour and config

### 3.1 Local wheelhouse: exclusive unless pinned

A **local name** is the canonical project name parsed from any `*.whl`
filename in the platform's `find_links` directories, whatever its tags.

- An unpinned local name gets candidates **only** from `find_links`, for every
  variant, whether or not an index has a newer version or a better-tagged
  wheel. `lock --update` moves it to a newer version only when a newer wheel
  is in the directory.
- If no wheel there fits a variant, that variant fails with
  `KF-LOCK-SOURCE-UNAVAILABLE` (§6). It does **not** fall back to an index: a
  lock with the local Kivy on arm64 and PyPI's on x86_64 would be worse than
  an error.
- **A pin outranks the wheelhouse.** A local name that is also pinned in
  `sources` comes only from its pinned index, and its local wheels are
  ignored. `lock` succeeds with a `KF-LOCK-WARNING` that names the package,
  the index and the wheels it ignored (§6), so a forgotten pin or a stale
  wheel does not go unnoticed. To return to the local wheel, remove the pin
  and re-lock.

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
| `url` | string | yes | PEP 503/691 simple index base URL, `http(s)://` only. A URL with credentials in it is refused (§3.6). |
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

For each project pip asks about, the first rule that applies decides:

1. **Pinned** (`sources` names it): that index only. Local wheels for it are
   ignored, with a warning (§3.1).
2. **Local name** (§3.1): `find_links` only.
3. **Otherwise**: every `extra_index_urls` entry, every non-explicit named
   index, and PyPI. Explicit indexes are excluded. pip chooses the newest
   version, then the best-matching tag; on a full tie the first-listed index
   wins (§3.4).

A pin applies to the package wherever it appears in the graph, direct or
transitive. That differs from Poetry, whose `source` does not reach a
package's own dependencies, and matches uv.

Source and version are chosen independently. These rules fix which sources a
package may use; within them pip chooses the version, and `lock --update`
only ever changes the version.

### 3.4 Index order and ties

For rule 3, the indexes are ranked in this order, highest first:

1. the platform's `extra_index_urls`, in the order listed;
2. non-explicit `[[tool.kivy.index]]` entries, in the order declared;
3. PyPI.

The order only breaks ties. A newer version, or the same version with a
better-matching wheel tag, wins whatever its index's rank (experiments C5 and
C6, §4.7). When two indexes offer the same version with equally good tags, the
higher-ranked index wins (C1 to C4).

PyPI ranks last, as uv's default index does. That also keeps today's result
for the common case: a package on both PyPI and kivy-mobile-wheels at the same
version comes from kivy-mobile-wheels today (pip's last-listed rule, §1.2),
and it still does. Only a project with two extra indexes that tie changes, and
it changes to the order kengoon expected.

### 3.5 Example: from a patched wheel to the upstream release

kengoon's case on #86: he patches Kivy locally while waiting for an upstream
Android fix, and wants to switch to the upstream release when it ships
without deleting his wheel.

**Step 1.** The patched wheel is in `wheels/`:

```toml
[[tool.kivy.index]]
name = "mobile-wheels"
url = "https://elliotgarbus.github.io/kivy-mobile-wheels/simple/"

[tool.kivy.android]
find_links = ["wheels"]
```

Kivy is a local name, so it comes from `wheels/`, even if mobile-wheels has a
newer version. `kivyforge lock -p android --update` keeps the patched wheel.

**Step 2.** The fix is released. Add a pin and re-lock:

```toml
[tool.kivy.android.sources]
kivy = { index = "mobile-wheels" }
```

```bash
kivyforge lock -p android --update
```

Kivy now comes only from mobile-wheels, at the newest version its specifier
allows. The wheel in `wheels/` is ignored, and `lock` says so with a warning.
A plain `kivyforge lock` would also switch Kivy, because its locked pin is
dropped when its source changes (§5.2); `--update` additionally moves every
other package to its newest version.

**Step 3.** To go back to the patched wheel, remove the pin and re-lock.

### 3.6 Validation (config errors, exit 1)

- duplicate index `name`, the reserved `pypi`, or an invalid name;
- a `url` that is not `http(s)://`, or that contains `user:pass@`. The URL is
  written into the lock (§5.4), and credentials must not be. Authenticated
  indexes are an open question (§11);
- a `sources` entry naming an unknown index, or using a key other than `index`;
- `explicit` set on an index that no platform's sources refer to: a warning
  (`KF-LOCK-WARNING`), not an error, since a platform may simply not be
  configured yet.

The warning for a pinned local name (§3.1) comes from `lock`, not from the
loader, because it depends on the contents of the `find_links` directories.

## 4. Mechanics: the filter in `_pip_shim.py`

### 4.1 What it patches

The shim already replaces one pip internal, the vendored
`packaging.markers.default_environment`, and then calls pip's `main()`
unchanged. A second, independent patch wraps
`pip._internal.index.package_finder.PackageFinder.find_all_candidates(project_name)`.
That function returns every file pip found for a project, from the index
URLs, extra index URLs and find-links, after link evaluation has dropped
files whose tags do not fit the target.

The wrapper does two things to that list, and replaces pip's per-project cache
entry so every later lookup sees the result:

- **It removes** the candidates §3.3 disallows.
- **It orders** the rest lowest-ranked source first (§3.4). pip sorts
  candidates stably by version and tag and takes the last of equals (§1.2),
  so after this ordering the highest-ranked index wins a full tie, and
  nothing else about pip's choice changes (experiments C1 to C6).

Version selection, backtracking and the dependency graph are untouched.

### 4.2 The policy

kivyforge builds the policy per resolve and passes it as JSON in
`KIVYFORGE_SOURCE_POLICY`, the same way the marker environment travels in
`KIVYFORGE_TARGET_MARKER_ENV`:

```json
{
  "find_links": ["C:/…/wheels"],
  "local_names": ["kivy"],
  "indexes": {"extra-1": "https://…/simple/", "mobile": "https://…/simple/",
              "pypi": "https://pypi.org/simple/"},
  "rank": ["extra-1", "pypi"],
  "explicit": ["mobile"],
  "sources": {"pyjnius": "pypi"},
  "record": "C:/…/kivy-lock-xyz/sources.json"
}
```

`rank` is the §3.4 order of the indexes rule 3 may use, highest first; an
`extra_index_urls` entry gets a generated name. kivyforge computes
`local_names` from the directory listings, not the shim, so it can leave
pinned names out and emit the §3.1 warning before pip starts.

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

With no `find_links`, no `sources`, and at most one index besides PyPI, there
is nothing to filter and no tie to order differently, so kivyforge does not
set `KIVYFORGE_SOURCE_POLICY`; the shim then patches nothing and pip behaves
exactly as it does today, which experiment B10 confirms. With one extra index,
pip's last-listed rule already lets it win a tie with PyPI, the same result as
§3.4.

### 4.6 Failure modes

- **A pip that lacks `PackageFinder.find_all_candidates`,
  `InstallationCandidate.link` or `Link.comes_from`**: the shim exits with a
  distinct status. It never resolves unfiltered: a silent fallback would bring
  back the wrong-source lock this exists to prevent. This is the marker
  shim's rule.

  This is a kivyforge bug, not a user error. The user never chooses this pip:
  kivyforge depends on `pip>=25.1` and runs its own interpreter's pip
  (`sys.executable`). The only way the patch can break is a pip release newer
  than this kivyforge, since the dependency has no upper bound. So the
  failure gets no `KF-*` code of its own; it is the unclassified `KF-ERROR`
  (exit 1), and the message says so plainly: "kivyforge X cannot apply its
  source rules with pip Y; please report this. Until it is fixed, install
  `pip<Y` in kivyforge's environment." The shim canary in the normal test
  suite (§8) is what keeps users from seeing it: CI installs the newest pip
  on every run, so a pip release that breaks the patch fails CI first.

  An upper bound on pip (`pip>=25.1,<N`) would prevent the failure, but it
  would also hold every user back from pip fixes until kivyforge releases,
  and the marker shim has never had one. That is an open question (§11).
- **A filtered-out package**, that is, a pinned package its index does not
  have, or a local name with no wheel for this variant: pip says "Could not
  find a version that satisfies the requirement" (experiments B8, B9). The
  resolver recognizes the package (`unresolved_requirement()` already
  extracts it) and, when that package is pinned or local, raises
  `KF-LOCK-SOURCE-UNAVAILABLE` (§6) instead of the generic message.

### 4.7 Prototype results

A 40-line prototype of the filter in §4.1 was run with the same harness as
§1.2 (2026-10-21). It matched on file URLs, which is enough for local
`file://` indexes; §4.3 corrects that for real ones. Rows B1 to B4 test an
unpinned local name, which the 2026-10-22 revision did not change.

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

A second prototype, of the ordering in §4.1, ranked candidates by
`comes_from` (2026-10-22):

| # | Indexes and rank | Result |
|---|---|---|
| C1 | same version on extras `a` and `b`; rank `a, b` | `a` |
| C2 | the same; rank `b, a` | `b` |
| C3 | same version on PyPI, `a` and `b`; rank `a, b, pypi` | `a` |
| C4 | the same; rank `pypi, a, b` | PyPI |
| C5 | first-ranked `d` has the same version as PyPI, with a worse tag | PyPI (tag beats rank) |
| C6 | first-ranked `d` has an older version than PyPI | PyPI (version beats rank) |

## 5. Lock interactions

### 5.1 Lock inputs

Each platform's `LOCK_INPUTS` (`kivyforge/lock/inputs.py`) gains
`<platform>.indexes` and `<platform>.sources`, the effective values from
§3.2. Adding a pin for Android does not stale the iOS lock, and an explicit
index that only Android uses is not an iOS input. The order of
`extra_index_urls` and of `[[tool.kivy.index]]` is part of these values, as
it must be now that it breaks ties. `tests/lock/test_lock_inputs.py` already
fails if a builder reads a field that is missing from the projection.

The **contents** of `find_links` directories stay outside the projection, as
they are today. Adding a wheel with a new name makes that name local; the
lock is not marked stale, but `lock --check` sees the difference (§5.3) and
`lock` or `lock --update` applies it. This is the existing rule for vendored
wheels.

### 5.2 Pin preference

`preferred_pins()` drops, before resolving, the pin of any locked package
whose recorded source the policy no longer allows. This mirrors the existing
rule for a direct requirement whose specifier has moved:

- the locked wheels are `url`s, but the name is now an unpinned local name;
- the locked wheels are `path`s, but the name is no longer local, or is now
  pinned (§3.5, step 2);
- the name is pinned, and the lock's `index` for it is a different URL, or is
  missing (a lock written before this change).

Without this, the old pin and the new source collide and the user gets
`KF-LOCK-PINS-CONFLICT` with advice to run `--update`, which moves every
other package too (experiment B5). With it, only the package whose source
changed moves.

### 5.3 `lock --check`

It builds its candidate with the same policy and pin preference, so a project
whose config and wheelhouse have not changed still checks clean. A wheelhouse
that gained an unpinned local name makes `--check` fail with `KF-LOCK-DRIFT`,
which is correct: the next `lock` would produce a different file.

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

One new code in `kivyforge/report/diagnostics.py`:

| Code | Exit | When | `context` |
|---|---|---|---|
| `KF-LOCK-SOURCE-UNAVAILABLE` | 1 | A pinned or local package has no candidate on its only allowed source for a variant | `distribution`, `source` (index name or `find_links`), `variant` |

Example message:

```
error: pyjnius is pinned to index 'pypi' (https://pypi.org/simple/) in
[tool.kivy.android.sources], and that index has no wheel for android_24_x86_64.
  Fix: pin it to an index that has one, remove the pin, or add the wheel to a
  find_links directory.
```

A pinned local name (§3.1) is not a failure. It is a `KF-LOCK-WARNING` on a
successful `lock`, with `context` `distribution`, `index` and `ignored` (the
wheel paths):

```
warning: kivy is pinned to index 'mobile-wheels' in [tool.kivy.android.sources],
so its wheels in find_links are ignored:
  wheels/Kivy-2.3.1-cp314-cp314-android_24_arm64_v8a.whl
  wheels/Kivy-2.3.1-cp314-cp314-android_24_x86_64.whl
  Remove the pin to use them again.
```

A pip the shim cannot patch is a kivyforge bug and stays the unclassified
`KF-ERROR` (§4.6). Config errors (§3.6) are the loader's existing
`ConfigError`, with `key_path` and line.

## 7. Docs

- `docs/guides/concepts/runtimes-and-wheels.md` gains a "Where packages come
  from" section: the three rules of §3.3, in order; that the source and the
  version are chosen separately; the index order of §3.4, and that it only
  breaks ties; and the §3.5 example of switching from a patched wheel to the
  upstream release.
- `docs/guides/reference/pyproject/tool-kivy.md` documents `[[tool.kivy.index]]`,
  `[tool.kivy.sources]` and `pypi`; each platform page there documents its
  `sources` table.
- The `find_links` and `extra_index_urls` rows in the platform specs
  (`android/01`, `ios/01`, macOS, Linux and Windows specs) link to that section
  and state that `find_links` wins over every index unless the package is
  pinned, and that `extra_index_urls` order breaks ties.
- `docs/guides/reference/lockfile.md` documents `packages.index`.
- `docs/guides/reference/codes.md` gains the new code, and `capabilities`
  lists it (its code vocabulary comes from `diagnostics.py`).
- Reply on #86 when each PR lands.

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
  referenced explicit ones, in declaration order.
- `keys.py` allow-list: the new tables are accepted, and a typo in them is
  reported.

**Shim (`tests/lock/test_pip_shim.py`, running the real shim and real pip)**
- The canary: the filter applies with the installed pip, so a pip upgrade that
  breaks the patch fails CI rather than resolving unfiltered.
- Each row of both §4.7 tables, with candidates identified by `comes_from`
  from an index page whose files are hosted under a **different** directory
  than the page, which stands in for files.pythonhosted.org and GitHub
  releases.
- A pinned local name: the pinned index's wheel is chosen even though
  find_links has a newer version of it.
- No policy set: the shim patches nothing (pip output matches `-m pip`).
- Neither marker variable set: refuses; `KIVYFORGE_HOST_MARKERS=1`: runs.
- The patched symbol is missing (monkeypatched away): distinct exit status,
  and the resolver raises `KF-ERROR` with the "please report" message; it
  never falls back to an unfiltered resolve.
- `record` maps each surviving file URL to the right index name.

**Resolvers and builders (`tests/lock/`, `tests/platforms/*/lock/`)**
- All three resolvers pass the policy and set `source_index` from the record;
  the desktop resolver now invokes the shim.
- The policy's `rank` is the overlay's `extra_index_urls`, then the
  non-explicit named indexes, then PyPI.
- A local name with no wheel for one ABI raises `KF-LOCK-SOURCE-UNAVAILABLE`
  naming that ABI; there is no fallback to an index.
- A local name that is also pinned resolves from its index and emits one
  `KF-LOCK-WARNING` listing the ignored wheels; an unpinned local name emits
  none.
- The §3.5 sequence: `lock --update` keeps an unpinned local name local while
  an index has a newer version; adding a pin moves it to the index; removing
  the pin moves it back.
- `preferred_pins()` drops a pin for each of the three source-change cases in
  §5.2 and keeps the others.
- `test_lock_inputs.py` covers `indexes` and `sources` for every platform; a
  shared pin used only by Android leaves the iOS hash unchanged; reordering
  `extra_index_urls` changes the hash.

**Lock file (`tests/lock/test_pep751*.py`)**
- `index` is written for index packages and omitted for `path` packages;
  `source_index` is read but not written; a round trip is stable.

**CLI**
- `lock --check` is clean on an unchanged project with a policy, and reports
  drift after a wheel with a new name is added to `find_links`.
- `--json`: the new code, and the pinned-local warning, appear in
  `diagnostics[]` with their `context`.

## 9. Delivery and migration

Both parts land before the release, as **two PRs** in this order, so the
first can ship alone if the second slips:

1. **Shim, local-first and index order.** The shim filter (§4) with the
   `find_links` rule and the §3.4 ordering of `extra_index_urls` and PyPI;
   the desktop resolver moves to the shim; `packages.index` recorded (§5.4);
   the pin-dropping rule for `url`/`path` changes (§5.2);
   `KF-LOCK-SOURCE-UNAVAILABLE`; docs for `find_links` and index order.
2. **Named indexes and sources.** Config (§3.2, §3.6), `LOCK_INPUTS` (§5.1),
   the pinned and explicit rules in the policy, named indexes in the rank,
   the pinned-local warning, and the rest of the docs.

Until PR 2 lands there are no pins, so in PR 1 an unpinned local name is the
only kind there is, and the way to take an index version is to remove the
wheel.

**Migration: none in code**, following #126's policy:

- PR 1 changes lock *output* (a new `index` key on every index package) for
  unchanged inputs, so `lock --check` fails once on every existing lock.
- PR 2 adds lock-input paths, which changes every `lock_inputs_sha256`, so
  every lock reads stale once.
- In both cases the `CHANGELOG.md` migration note says to run `kivyforge lock`
  once per platform; the pin preference keeps every version.
- Two behaviours change, and the changelog says so:
  - **Local-first.** A project whose wheelhouse holds an older version of a
    package that an index also ships now gets the local one. To take the
    index version, pin the package to its index (after PR 2) or remove the
    wheel. In this repo, only the `tests/fixtures/apps/metaprobe` fixture has
    both `find_links` and an extra index.
  - **Tie order.** A project with two or more `extra_index_urls` that ship the
    same version of a package now gets it from the first listed, not the
    last. No project in this repo has two extra indexes.
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
fragment). It was rejected because:

- **no backtracking across passes**: pass 1 chooses a version without seeing
  transitive specifiers, so a resolvable graph can fail in pass 2;
- pass 1 has to decide which specifier applies to each package, which is
  resolver logic kivyforge does not own;
- it doubles the pip runs per variant, and Android and iOS already run one per
  ABI or slice;
- it does not answer "which index served this?" for unpinned packages, so
  `packages.index` would stay empty for most of the lock;
- it cannot change the tie order among unpinned packages.

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
`unsafe-best-match`. With extra indexes first, a newer release on PyPI would
be hidden behind an older one on any extra index that has the name. Explicit
indexes and pins give the same protection where a user asks for it, so the
default stays best-match, and the index order of §3.4 only breaks ties.

### 10.5 The wheelhouse outranks a pin (the 2026-10-21 draft)

The first draft made a local name exclusive even over `sources`, and made a
pinned local name a config error, `KF-SOURCE-CONFLICT`. Switching to an
upstream release then meant deleting the local wheel, and switching back meant
restoring it. kengoon asked for a way to pick up an upstream fix without that.
Letting `lock --update` take a newer index version over the local wheel was
considered and rejected: a version bump would silently change a package's
source. The adopted rule (§3.1) makes the switch an explicit pin instead.

## 11. Open questions

- **Authenticated indexes.** URLs with credentials are refused because the URL
  goes into the lock. Supporting them means credentials from the environment
  or keyring at lock time, and a credential-free URL in the lock. This waits
  until someone asks.
- **An upper bound on pip.** kivyforge's `pip>=25.1` dependency is
  unbounded, so a future pip can break both shim patches until kivyforge
  releases a fix (§4.6). The CI canary catches it first; a bound would
  prevent it but delay pip fixes for everyone. The marker shim has lived
  without one so far.
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
  `sources` to `[tool.uv.sources]`. The pin-over-local rule maps to uv's
  sources taking precedence; an unpinned local name becomes a first-listed
  flat index. Nothing here blocks it.
