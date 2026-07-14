# The runtime-provider pattern (desktop platforms)

iOS has a clean runtime story: python.org publishes an official, ready-to-embed
`Python.xcframework`, so the iOS backend just pins and downloads it (see
[iOS artifact distribution](../platforms/ios/artifact-distribution-ios.md)).
The desktop platforms — macOS, Linux, and Windows — don't all have that luxury
today, and even where an official artifact exists its fitness varies. Rather
than let each platform spec invent (and duplicate) its own bridging story,
kivyforge's desktop backends share one abstraction: the **`RuntimeProvider`**.

## The problem

A desktop `.app` / folder / launcher-exe bundle needs a **relocatable,
embeddable** CPython — one that doesn't hard-code absolute install paths and
that kivyforge can drop into an app bundle and re-sign. Whether python.org
ships such an artifact today differs per platform:

| Platform | Official python.org relocatable artifact today? |
|----------|---------------------------------------------------|
| macOS | No. The only macOS build is the "universal2 installer" `.pkg`, which installs a `Python.framework` hard-coded to `/Library/Frameworks` (absolute link references) — not embeddable without rewriting `install_name`/`@rpath`, re-signing, and trimming. |
| Linux | No official prebuilt relocatable CPython from python.org (distros rely on system packages or manylinux-style container images, neither of which is a drop-in bundleable artifact). |
| Windows | **Yes, but rejected** — the [Windows embeddable package](https://docs.python.org/3/using/windows.html#the-embeddable-package) is an official, purpose-built, relocatable ZIP distribution. The [Windows spec](../platforms/windows/windows-spec.md#python-runtime-acquisition) settled on `python-build-standalone` anyway: it is not a normal prefix (no `share/` data-scheme target for wheel-installed DLLs, zipped stdlib, no headers/import lib), and its `._pth` isolation changes `sys.prefix` semantics — which Kivy's Windows DLL discovery keys off. These are permanent, structural gaps, not fixable configuration. PBS's normal prefix layout is load-bearing for the Windows bundle (wheel data installs to `<prefix>\share\<dep>\bin`, where `kivy_deps.*` self-registration looks). |

For the desktop platforms — macOS, Linux, and Windows —
**[`python-build-standalone`](https://github.com/astral-sh/python-build-standalone)
(PBS)** is the bridge: purpose-built to be relocatable/embeddable, actively
maintained (Astral-stewarded, tracks CPython releases closely), and its
patches are being upstreamed into CPython — the pragmatic choice today and
directly on the path to an eventual official artifact (see "Watch item"
below).

## The `RuntimeProvider` abstraction

The source of the runtime is an implementation detail hidden behind one seam,
so a future switch (adopting an official artifact, or changing bundling
strategy) is a **re-lock, not a rewrite**:

- **`RuntimeProvider` interface** (per platform backend). A provider resolves
  a CPython version to a concrete, pinned artifact and normalizes it to a
  **canonical relocatable layout** that platform's bundler consumes. A
  platform may ship multiple implementations — e.g. macOS's
  `PythonBuildStandaloneProvider` today and a future
  `PythonOrgFrameworkProvider` once python.org's relocatable macOS framework
  lands. The bundler, launcher, signing, and `doctor` code depend only on the
  canonical layout — **never** on the provider.
- **The lock records the provider, not just the version.** `[tool.kivyforge]`
  in `pylock.<platform>.toml` pins `provider` + `version` + per-artifact
  `url` + `sha256`, exactly the URL+SHA-256 discipline used for the iOS
  `python_xcframework` pin. Switching providers is therefore just
  `kivyforge lock` regenerating the pin; the built artifact is
  provider-agnostic and nothing downstream changes.
- **User config stays provider-neutral.** `[tool.kivy.<platform>.python].version`
  is just the CPython version. An optional advanced `provider` key may
  override the default, but the default is chosen by kivyforge. When a
  platform's default provider changes, flipping it requires **no change to
  anyone's `pyproject.toml`** — only a re-lock.

Each platform spec documents its own concrete decision and provider
implementations (see [macOS spec §"Python runtime acquisition"](../platforms/macos/macos-spec.md#python-runtime-acquisition)).

## Watch item: official prebuilt CPython (`python/prebuilt-cpython`)

**[python/prebuilt-cpython](https://github.com/python/prebuilt-cpython)** is
the PSF's effort to distribute official, prebuilt, **relocatable** CPython
builds from python.org (signed by official keys), unblocked by upstreaming
PBS patches; a PEP is imminent. This is the intended long-term end-state for
the platforms that bridge via PBS (macOS, Linux, Windows). When it lands for
a given platform, that platform's backend adds the corresponding
`PythonOrgFrameworkProvider`-equivalent, makes it the default, and existing
projects pick it up on their next `kivyforge lock` — no rewrite, per the
abstraction above.

Platform-specific upstream tracking (e.g. macOS's
[cpython#86680](https://github.com/python/cpython/issues/86680) /
[cpython#144305](https://github.com/python/cpython/pull/144305) for the
relocatable macOS framework specifically) lives in that platform's own spec,
since it's not shared across platforms.
