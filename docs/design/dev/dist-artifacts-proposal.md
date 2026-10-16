# Proposal — `package` writes its artifact to `dist/`

> Status: **implemented 2026-10-15** on branch `dist-artifacts`, not yet
> released. The hermetic tests in section 9 pass. On 2026-10-16 real
> `package -p ios` and `package -p android` runs on this Mac passed, the
> Android one including an install from `dist/android/` on an emulator
> (`test-matrix.md` §7). The reply on #112 (section 11) is still open. Drafted on 2026-10-15, and trimmed to the
> smallest change that addresses the issue.
>
> Responds to [#112](https://github.com/ElliotGarbus/kivyforge/issues/112),
> which asks for packaged artifacts in `dist/` under versioned names. Its
> example is `dist/$APP-$VERSION-debug.apk` instead of
> `$APP-android/app/build/outputs/apk/debug/app-debug.apk`. This proposal
> covers the location and naming of release artifacts. The debug APK in that
> example is deferred (5.2), so the change does not resolve #112 on its own:
> #112 stays open until the reporter says whether they need debug builds
> (section 11).
>
> [`package-metadata-proposal.md`](package-metadata-proposal.md) §9 deferred
> this to its own change. The design was checked against the PyPA
> specifications (section 6) and compared with Briefcase (section 7). Its
> decisions were recorded on 2026-10-15 (section 4), and none is open.
>
> Two reviews the same day changed:
>
> - Q1's rule;
> - same-name files and the parent folder (3.4);
> - the CI step (step 5);
> - the tests (section 9);
> - the scope claimed for #112.

**Summary.** `package -p android` and `package -p ios` copy the file they
produce to `dist/<platform>/<slug>-<version>[-<qualifier>].<ext>`, as
`package -p linux` already does for its AppImage. The original stays where it
is. `build` writes nothing to `dist/`, and the Linux, Windows and macOS code is
not touched.

The benefit is modest: a better name and a predictable location for people
who keep or share the files. The change is kept small and additive to match.
Nothing that reads today's paths stops working.

## 1. Problem

**The file does not say what it is.** `package -p android` leaves
`app-release.apk` or `app-release.aab`. `package -p ios` leaves `<slug>.ipa`.
Neither name carries a version, and Android's carries no app name. Once a copy
has been uploaded, archived or attached to a bug report, nothing ties it to an
app or a version, and two versions overwrite each other under one name. This is
the reporter's complaint: the name is "not suitable for archiving and later
comparing behavior of previous builds". `--json` does not fix it.
`artifacts[].path` finds the file but does not name it better.

**One verb, two conventions.** `package` writes a versioned name into
`dist/<platform>/` for Linux's AppImage and Windows' folder. On Android and iOS
it leaves a name chosen by Gradle or Xcode inside a generated project, at a path
that moves when AGP's layout does (`_require_artifact` in
`platforms/android/cli.py` exists for that case).

## 2. Where artifacts land today

| Verb | `kind` | Path |
|---|---|---|
| `package -p linux` | `appimage` | `dist/linux/<slug>-<ver>-<arch>.AppImage` |
| `package -p linux -f folder` | `folder` | `build/linux/<Display Name>.AppDir` |
| `package -p windows` | `folder` | `dist/windows/<Display Name>-<ver>-<arch>/`, a copy of `build/windows/` |
| `package -p macos` | `app` | `build/macos/<Display Name>.app`, signed and notarized in place |
| `package -p android [-f aab]` | `apk`/`aab` | `<slug>-android/app/build/outputs/{apk,bundle}/release/app-release.{apk,aab}` |
| `package -p ios` | `ipa` | `<slug>-ios/build/<slug>.ipa`, with the `.xcarchive` beside it |
| `build -p android --debug` | `apk`/`aab` | `<slug>-android/app/build/outputs/{apk,bundle}/debug/app-debug.{apk,aab}` |
| `build -p ios --release` | `ipa` | `<slug>-ios/build/<slug>.ipa` |

Linux and Windows build their names from `config.version_required.filename_part`:
the normalized PEP 440 version, with a local segment's `+` replaced by `_`.
[windows-spec](../platforms/windows/windows-spec.md#init--build--run--package--status)
gives the reasoning this proposal extends: `build/` is the dev tree that changes
on every build, and `dist/` holds the clean, versioned copy that ships.

These read the in-tree Android and iOS paths, and all of them keep working
because the design copies:

- `android_run` installs `_debug_output` or `_release_output` for `run`,
  `run --release` and `run --no-build`.
- `android_status` probes the three in-tree outputs.
- In CI, the `android_gradle`, `android_bundle` and `android_windows_host` jobs
  read `app-release.apk` or `app-release.aab` after `package`.
- Users' own scripts.

## 3. Design

### 3.1 The rule

**When `package` produces a file, the file goes to `dist/<platform>/`.
`build` never writes to `dist/`.**

The rule is about the verb, not the artifact, so nobody has to judge which
outputs count. `package` is the verb whose job is the distributable. `build`'s
outputs are dev-loop products: Android's debug APK, and iOS's `--simulator` and
`--device` apps and `--release` `.ipa`. They stay in the generated project,
where `run` and Xcode expect them.

Two `package` outputs are folders that `package` finishes in the build tree
rather than files: Linux `-f folder` and macOS. This change leaves them alone
(section 5.1).

### 3.2 Names

`<slug>` is `config.app_slug` (`[project].name` as written), as Linux uses.
`<ver>` is `filename_part`, as Linux and Windows use.

| Invocation | Path |
|---|---|
| `package -p android` | `dist/android/<slug>-<ver>.apk` |
| `package -p android -f aab` | `dist/android/<slug>-<ver>.aab` |
| `package -p android --abi <abi>`, when `<abi>` is a strict subset of `abis` | `dist/android/<slug>-<ver>-<abi>.apk` (or `.aab`) |
| `package -p ios` | `dist/ios/<slug>-<ver>.ipa` |
| `package -p ios --export-method ad-hoc` | `dist/ios/<slug>-<ver>-ad-hoc.ipa` |
| `package -p ios --export-method development` | `dist/ios/<slug>-<ver>-development.ipa` |

A qualifier appears only when the artifact is not the default one. Two
artifacts of one version whose contents differ must not share a name, which is
the problem in section 1.

- **Android ABI.** By default the artifact carries every ABI in
  `[tool.kivy.android].abis`, like a macOS universal binary, so the name has
  no arch. When the packaged ABIs are a strict subset of `abis`, which only
  `--abi` can produce, the name gets that ABI in its wheel-tag spelling
  (`arm64_v8a`, `x86_64`). The rule follows the contents, not the flag:
  `--abi x86_64` with `abis = ["x86_64"]` packages the full app and gets no
  qualifier.
- **iOS export method.** The export method changes the provisioning embedded
  in the `.ipa`, so an ad-hoc and an App Store export of one version are
  different files.

Both rules are decided in section 4: Q1 (the ABI) and Q2 (the export method).

The display name is not used. Windows uses it because its `dist/` folder is
what an end user unzips and sees. Nobody sees an `.apk` or `.ipa` file name
after installing it.

### 3.3 Copy, not move

The artifact is copied out of the generated project, and the original stays.
Briefcase moves it (section 7). Here a move would break every reader listed in
section 2, and would make Gradle's and Xcode's next incremental build redo the
packaging step for nothing.

The copy does not change the file's bytes. APK and IPA signatures cover the
contents, not the file name, so signing, verification and installation behave
exactly as they do for the in-tree file.

### 3.4 Writing the copy

- **One function does the copy for both platforms**: `copy_in(src, dest)`, in
  `bundle/workdir.py` beside `swap_in`. It follows every rule in this section.
  It raises the original exception unchanged, and each backend wraps that in
  its own error type (last bullet). The keep-previous behaviour is therefore
  written, and tested, once (section 9). Android and iOS only call it.
- **Create the folder first.** `dist/<platform>/` does not exist on a clean
  checkout, so the copy starts with `mkdir(parents=True, exist_ok=True)` on
  it, as Windows' `_stage_dist_copy` already does for `dist/windows`.
- **Copy straight to the final name** (`shutil.copy2`). Writing a temporary
  file and renaming it is not safe here: `platforms/windows/fsswap.py` records
  that Windows cannot reliably rename a freshly written file while the
  antivirus scanner holds it open, and the `android_windows_host` job packages
  on Windows.
- **A same-name file from an earlier run is kept until this run's copy
  succeeds.** This is the rule Windows already follows ("a broken package never
  destroys a working one", `fsswap.py`), and what Linux does when
  `appimagetool` fails (checked on 2026-09-16, `test-matrix.md` §7).
  - A failure before the copy (signing, Lint, Gradle, Xcode) leaves the file
    untouched.
  - The copy uses `fsswap`'s reserve-and-restore pattern on one file:
    1. Rename the existing file aside (`.<name>.old-<suffix>`, as the existing
       helpers name theirs).
    2. Copy straight to the final name.
    3. On success, delete the old file.
    
    On any failure, delete the partial file and rename the old one back.
  - **Any failure includes an interruption.** The restore runs on
    `BaseException`, not only `OSError`, as `swap_in` and `fsswap` already
    do. Otherwise a Ctrl-C between steps 1 and 3 would leave the old file
    under its hidden `.old-*` name and nothing under the real one. The
    exception still propagates unchanged.
  - **Renaming the old file aside retries.** It uses `rename_with_retry`,
    which retries while Windows reports `PermissionError`, for up to 30
    seconds by default. A file written long ago renames at once. One that a
    previous `package` wrote seconds earlier may still be held by the
    antivirus scanner, and that is the case `fsswap` retries for. If the
    rename still fails, the copy stops before writing anything, and the old
    file stays in place.
  - **`rename_with_retry` moves** from `platforms/windows/fsswap.py` to
    `bundle/workdir.py`, and `fsswap` imports it from there. Android code
    importing from `platforms/windows/` would be the cross-backend coupling
    the [abstraction-leak retro](../common/abstraction-leak-retro.md) warns
    against. The function itself is not Windows-specific.
  - **The rest of `fsswap` is not reused.** `reserve_previous` raises
    `WindowsBundleError`, and `restore_previous` clears its target with
    `rmtree`; both are shaped for a Windows folder.
  - `bundle/workdir.py`'s `swap_in` (added in
    [#137](https://github.com/ElliotGarbus/kivyforge/pull/137)) also keeps the
    previous output on failure, but it does not fit. It finishes by renaming
    the freshly written result into place (`work.replace(dest)`), which is the
    rename `fsswap` records the Windows antivirus scanner can block. That is
    safe for the macOS `.app` and the Linux AppDir, whose backends never run
    on Windows. It is not safe for `package -p android`, which does.
  
  So after a failed run, `dist/` can hold a file with exactly the name this run
  would have written. It is the previous successful package, and the envelope
  does not name it (3.5). CI is unaffected: a failed `package` exits non-zero,
  which stops the job before any upload step.

  Deleting the same-name file at the start of `package` was considered and
  rejected. It would make Android and iOS behave unlike Windows and Linux, and
  a transient failure, such as a Gradle download, would destroy a good
  package.
- **Files of other versions are not touched.** Keeping them is the archive #112
  asks for.
- **A failed copy raises the backend's own error type, with its message from
  `failures.os_failure()`.** It must never be a bare `OSError`.
  `reporting()` in `cli/_output.py` catches only `ToolchainError`, and nothing
  above it catches anything, so a bare `OSError` skips the `--json` envelope
  and prints a traceback.
  - **The message:** `os_failure()` (added in
    [#136](https://github.com/ElliotGarbus/kivyforge/pull/136)) turns an
    `OSError` into one line, `could not <doing>: <why>`, and is what every
    backend's own filesystem writes now use.
  - **Android:** `AndroidBuildError(os_failure(f"copy {name} into
    dist/android", exc))`. The copy wraps its own error. `android_package`
    carries only `@user_facing`, which catches `AndroidBuildError`, not
    `OSError`. The `@writes_project` decorator that does catch `OSError` is
    on `android_build`, and its label, "write the Android project", would
    misname a copy into `dist/`, so it is not added to `android_package`.
  - **iOS:** `ToolchainError(failures.os_failure(...))`, as `ios/cli.py`
    already does for the release build folder.

  The failure is unclassified (`KF-ERROR`, exit 1). There is no new code:
  codes are contracts, and nobody has yet hit a full disk or a read-only
  `dist/`.

Windows' existing copy into `dist/windows` had the same bare-`OSError` gap.
It was fixed separately in
[#135](https://github.com/ElliotGarbus/kivyforge/pull/135), now merged, not as
part of this change.

### 3.5 What is reported

- **`artifacts` names the `dist/` path only.** The in-tree file is an
  intermediate of `package`, as the generated project already is. A failure at
  any point, including the copy, records `[]`. A file left in `dist/` by an
  earlier run is therefore never named in the envelope, even when it has the
  name this run would have written (3.4). See
  [build-package-output-proposal](build-package-output-proposal.md) §4.1b.

  iOS needs care here. `OutcomeBuilder.add` reports an artifact the moment it
  is called, and `_xcodebuild_step7` calls it right after the export. Under
  `package`, it must not record the in-tree `.ipa`; otherwise a copy that fails
  after a successful export would report that `.ipa` (step 2, tested in
  section 9).
- **Android's product line names the `dist/` path.** Today's
  `Packaged <in-tree path>` becomes `Packaged dist/android/demo-1.0.0.apk`.
- **iOS gains a line and loses none.** The `Exported <slug>-ios/build/<slug>.ipa`
  line that `_xcodebuild_step7` prints for both `build --release` and `package`
  stays as it is. Under `package`, `Packaged dist/ios/demo-1.0.0.ipa` follows
  it. An intermediate's line on stdout without an `artifacts` entry has a
  precedent: Android's `Generated <slug>-android` under `package`.
  `build -p ios --release` is unchanged.
- **`status` is unchanged.** Linux's and Windows' `status` report only the build
  tree. The `dist/` name also depends on a version that `status` does not
  resolve: resolving a dynamic version runs the build backend. Android's
  `status` keeps listing `apk (release)` at the in-tree path, so the Android
  guide says that `status` shows the build tree, not `dist/` (step 6).

### 3.6 `clean`, and two costs

`clean` adds `dist/android` and `dist/ios` to its list. It already removes
`dist/` once it is empty.

This brings two costs that are real, not just churn:

- **`dist/` grows.** With a dynamic version, every `package` leaves another
  file of a few tens of megabytes in `dist/android/` or `dist/ios/` until
  `clean` runs. With a static version, the same name is overwritten instead.
- **`clean` deletes the archive.** It removes every version in those folders,
  as it does today for `dist/linux` and `dist/windows`. Anyone who uses
  `dist/` as #112's archive has to copy the files elsewhere first. The guides
  say so.

### 3.7 What does not move

- `build -p android --debug`'s APK, and `build -p ios`'s products
  (section 3.1).
- The `.xcarchive`, whose `dSYMs/` is where
  [04-cli-ios](../platforms/ios/04-cli-ios.md) sends symbol uploaders, and
  Android's `native-debug-symbols.zip`.
- `ExportOptions.plist` and everything else in the generated projects.

## 4. Decisions (recorded 2026-10-15)

| # | Question | Decision |
|---|---|---|
| Q1 | Android: put the ABI in the name only for a subset build? | **Yes: when the packaged ABIs are a strict subset of `[tool.kivy.android].abis`.** The failure this prevents is silent: Play accepts a one-ABI AAB, and devices on the missing ABI cannot get the app. Without the qualifier, a subset package would also overwrite the full package of the same version. The rule follows the contents rather than the `--abi` flag, so an `--abi` that names every configured ABI gets no qualifier. A config that lists one ABI is unqualified too: that is the app the user chose, not an accidental subset. Always listing the ABIs (`-arm64_v8a.x86_64`) was rejected: it adds nothing for the default package, and the name would change whenever the config does. The first decision followed the flag; review changed it to follow the contents (2026-10-15). |
| Q2 | iOS: put the export method in the name for `ad-hoc` and `development`? | **Yes**, with `app-store`, the default, unqualified. This is the weakest of the naming rules, because a mix-up fails loudly: App Store Connect rejects a development or ad-hoc `.ipa`. It is kept because one version can legitimately have both an ad-hoc build for testers and an App Store build. |
| Q3 | Should `build -p ios --release`, which produces a distribution-signed `.ipa`, also copy to `dist/`? | **No.** The verb rule holds. `package -p ios` runs the same archive and export, and the iOS guide points at `package`. |
| Q4 | A debug variant of `package -p android` (Briefcase's `debug-apk`), for #112's literal example? | **Deferred** (section 5.2). Briefcase's reason for it does not apply to kivyforge. |
| Q5 | macOS and Linux `-f folder`? | **Deferred** (section 5.1). |
| Q6 | Per-platform subfolders, rather than Briefcase's flat `dist/`? | **Yes.** Linux and Windows already use them, a multi-platform CI job can upload `dist/android/*` without a filter, and the choice makes no difference to the twine problem (section 6). |

## 5. Not in this change

### 5.1 macOS, and Linux `-f folder`

`package -p macos` signs and notarizes `build/macos/<Display Name>.app` in
place. kivyforge already owns that location, and the name is already the app's;
only the version is missing. The version cannot go on the bundle itself,
because the `.app` name is what Finder shows and what lands in
`/Applications`. Adding one means either copying the bundle and signing only
the copy, which reverses the in-place decision windows-spec records, or writing
a `.app.zip` as Briefcase does, which needs a new artifact `kind`. Either costs
more than the gap. Revisit when a single-file macOS artifact is wanted for its
own sake.

Linux `-f folder` has the same shape: an AppDir finished in `build/linux/` that
is also the `run` target. It moves when macOS does, if at all.

### 5.2 A debug `package -p android`

#112's example is a debug APK. `build -p android --debug` produces it in the
generated project, and the rule in 3.1 keeps it there. The `-debug` in the
reporter's suggested name carries over from the path quoted in the issue,
which asks for a predictable location and an identifying name, not for debug
builds as such.

If it is added, it takes Briefcase's shape: a third package format,
`package -p android -f debug-apk`. That means no new option, and
`capabilities --json` lists it automatically. It runs what `build --debug`
runs (`assembleDebug`, signed with the SDK's debug keystore), skips the
release-only checks, and writes `dist/android/<slug>-<ver>-debug.apk` as an
`apk`.

It is deferred because Briefcase's reason for it does not carry over. Its
[issue #1136](https://github.com/beeware/briefcase/issues/1136) added
`debug-apk` because Briefcase's release APK was unsigned
(`app-release-unsigned.apk`), so the debug APK was the only one that would
install on another device. Its Android release signing is still an open pull
request ([#2724](https://github.com/beeware/briefcase/pull/2724)).
kivyforge's release APK is signed and installable. What remains is a user with
no release keystore. Creating one is a single `keytool` command, and after that
`package` produces a properly signed APK with every release check applied.

A debug APK would also work against #112's goal of comparing builds. Each
machine has its own debug keystore, and a fresh CI runner gets a new one, so
a debug APK built elsewhere cannot install over one already on the device.
Briefcase hit this in
[#1479](https://github.com/beeware/briefcase/issues/1479).

Revisit if the reporter, or a second user, needs debug builds specifically.

Letting `package` fall back to the debug keystore when no keystore is
configured, as `run --release` does, was also considered and rejected. It
would silently weaken what a plain `package` promises.

Whatever the location and whatever the build type, a file built from a static
version gets the same name on every build. Distinct names per build need a
dynamic version (setuptools-scm's `0.1.dev3+g1a2b3c` becomes
`0.1.dev3_g1a2b3c`) or `--app-version`. The reply on #112 should say so.

### 5.3 Also left out

- **Symbols beside archived artifacts.** An archived `.ipa` or `.aab` outlives
  the `.xcarchive` and `native-debug-symbols.zip` that symbolicate its crashes,
  because the next `package` overwrites those. A follow-up can copy them, if
  archiving in `dist/` turns out to be common.
- **A configurable output folder.** Nothing yet needs one that a `mv` in CI
  cannot do.
- **Refactoring Linux and Windows** to compute their paths through shared code.
  Their names already follow the convention this proposal uses.

## 6. Python packaging conventions

**No PyPA specification defines `dist/`.**
[PEP 517](https://peps.python.org/pep-0517/) has the frontend pass
`wheel_directory` and `sdist_directory` to the backend, and the
[binary](https://packaging.python.org/en/latest/specifications/binary-distribution-format/)
and
[source](https://packaging.python.org/en/latest/specifications/source-distribution-format/)
distribution format specs define file names only. `dist/` is a convention from
distutils, now the default of `python -m build` and `uv build`. In that
convention `dist/` holds the project's Python distributions, and the publishing
tools assume it:

| Tool | What it does with `dist/*` | With kivyforge output in `dist/` |
|---|---|---|
| `twine upload dist/*` | passes every match to `PackageFile.from_filename`, which raises `InvalidDistribution: Unknown distribution format` for anything that is not `.whl`, `.tar.gz` or `.zip` | already fails today, on `dist/linux` (a folder) |
| `pypa/gh-action-pypi-publish` | runs `twine upload <packages-dir>/*` without filtering; `packages-dir` defaults to `dist` | fails the same way |
| `uv publish` | skips folders and files that are not distributions | unaffected |

These are the tools' behaviours, not anything in a specification, and they
can change between releases. Checked on 2026-10-15:

- **twine:** at its 7.0.0 tag (released 2026-07-27), in
  `twine/commands/__init__.py` and `twine/package.py`.
- **`pypa/gh-action-pypi-publish`:** its `unstable/v1` branch, in
  `twine-upload.sh` and `action.yml`. The latest release is v1.14.2.
- **uv:** its `main` branch, in `crates/uv-publish/src/lib.rs`. The latest
  release is 0.13.1.

So a project that packages with kivyforge and publishes a wheel from the same
checkout already breaks the twine and GitHub Action uploads on Linux and
Windows. This change extends that to Android and iOS; it does not create it.
Leaving `dist/` would break the existing Linux and Windows layout for a case
that is rare among apps. Instead, the CI guide names the workarounds:
`twine upload dist/*.whl dist/*.tar.gz`, a separate
`python -m build --outdir`, or `uv publish`.

**File names.** The wheel spec escapes `-` in the distribution name to `_` so
that a file name splits on `-` without ambiguity;
`dice-roller-0.1.0-x86_64.AppImage` does not. These files are not Python
distributions, nothing parses their names, and `artifacts[].path` is the
machine interface, so this proposal keeps the Linux convention.

## 7. Comparison with Briefcase

Briefcase follows the same rule: only `package` writes to `dist/`, and
`briefcase build android` leaves `app-debug.apk` in the Gradle tree for `run`.
The differences:

- **Layout:** a flat `dist/` rather than per-platform folders.
- **Names:** `{formal_name}-{version}.{ext}`, using the formal name with its
  spaces. Only the AppImage carries an arch.
- **Android:** it moves Gradle's output rather than copying it, to `.aab`
  (default), `.apk`, or `.debug.apk` (its `debug-apk` format, which runs
  `assembleDebug`). Its release `.apk` is unsigned, which is why `debug-apk`
  exists (section 5.2).
- **iOS:** `briefcase package iOS` produces nothing and says iOS apps "must be
  published through Xcode".
- **macOS and Windows:** containers only (`.dmg`, `.pkg`, `.app.zip`; `.msi`,
  `.zip`), never a bare `.app` or folder.

Sources, read on 2026-10-15 from the `main` branch of
[beeware/briefcase](https://github.com/beeware/briefcase): `commands/base.py`
(`dist_path`), and in `platforms/`: `android/gradle.py`, `macOS/__init__.py`,
`windows/__init__.py`, `linux/appimage.py`, and `iOS/xcode.py`.

## 8. Steps

1. **The copy function, then Android.**
   - Add `copy_in` to `bundle/workdir.py`.
   - Move `rename_with_retry` there from `fsswap`, which then imports it
     (3.4).
   - `android_package` calls `copy_in` after `_check_packaged_libs`, wraps a
     failure with `os_failure()`, records the `dist/` path, and prints
     `Packaged dist/android/...`.
2. **iOS.** `ios_package` calls `copy_in` after the export, wraps a failure
   with `os_failure()`, records the `dist/` path instead of the in-tree one,
   and prints `Packaged dist/ios/...`. `_xcodebuild_step7` records the `.ipa`
   only for `build --release`.
3. **`clean`.** Add the two folders.
4. **Repository.** Add an unanchored `dist/` rule to the root `.gitignore` for
   the examples. Today's `dist/*` rule only matches at the root, and no mobile
   example's `.gitignore` lists `dist/`.
5. **CI.** In the `android_gradle`, `android_windows_host` and
   `android_bundle` jobs:
   - The `package` step runs with `--json > package.json`.
   - The check steps take the APK or AAB path from `data.artifacts[0].path`,
     instead of today's hard-coded `app-release.*` path.

   A fixed `dist/` path would not work. The first two jobs pass `--abi`, so
   under Q1 their file names carry the ABI, and all three carry the example's
   version. Reading the envelope keeps working when either changes. It also
   checks, end to end, that the envelope names a file that exists, and the
   existing artifact and signature checks then run against the copy, including
   on Windows.
6. **Docs.** Every document that states an Android or iOS output path,
   describes what `clean` removes, or lists which file names carry the version:
   - **README:** the comments on the two `package -p android` examples, which
     give Gradle's output paths.
   - **Guides:**
     - `guides/android/signing.md`: the "Verify" paths, a warning that
       `clean` deletes `dist/android/`, including older versions, and a
       sentence that `status` shows the build tree, so its `apk (release)` row
       is the in-tree file, not the one in `dist/` (3.5).
     - `guides/ios/signing.md`: the `.ipa` path, and the same `clean` warning.
       Its sentence saying `build -p ios --release` "does the same" becomes:
       the same export, but the file stays in the Xcode project (Q3).
     - `guides/cross-platform/ci-and-agents.md`: an Android or iOS path
       example, and the twine note from section 6.
     - `guides/cross-platform/versioning.md`: its opening says the version
       goes into "the Linux and Windows file names"; it now goes into the
       Android and iOS ones too.
     - `concepts/build-vs-package.md`: a short section on where each verb's
       output lands. `package` writes to `dist/<platform>/`, except the
       macOS `.app` and Linux `-f folder`; `build` leaves its output in the
       generated project. The page says nothing about locations today.
   - **Specs:**
     - `06-cli-android.md`: the `package` row of the verbs table and the
       `package` section gain the copy and the name. The `clean` section,
       which says the default removes "only the generated `<app>-android/`",
       adds `dist/android/`.
     - `04-cli-ios.md`: it has no `package` section. Step 7, the export that
       `build --release` and `package` share, gains a sentence that `package`
       then copies the `.ipa` to `dist/ios/`, with the export-method
       qualifier. The `clean` section adds `dist/ios/` in the same way as
       Android's.
   - **Dev docs:**
     - `hardware-checklist.toml`: the Play internal-track check names
       `app/build/outputs/bundle/release/app-release.aab`, which already lacks
       the `<app>-android/` prefix. The App Store check says only "the
       exported .ipa". Both name the `dist/` file instead.
     - `test-matrix.md` §7: the dated row from section 9's `package -p ios`
       run.
     - The status lines of this proposal, package-metadata-proposal §9 and
       roadmap item 13.

   Checked and unchanged:
   - `AGENTS.md` and `reference/json-output.md`, whose examples are Linux.
   - `reference/cli.md`, which lists flags only; no flag changes.
   - `07-signing-prerequisites-android.md`, which names formats, not paths.
   - The common specs 02 and 06, which describe artifact types, not
     locations.
   - `guides/ios/xcode.md` and `guides/windows/file-locking.md`, which
     describe `clean` in general terms.
   - The troubleshooting and migration guides.
7. **CHANGELOG.** An entry under `[Unreleased]`, with the migration note in
   section 10.

## 9. Test plan

The risk is small: one file copy after the artifact is built, signed and
checked, with the original left in place. The plan is sized to that.

**The copy function, in `tests/bundle/test_workdir.py`**, beside `swap_in`'s
tests. The keep-previous rules in 3.4 are tested here, once:

- **Clean start:** it creates the folder, and the copy is byte-identical to the
  source.
- **Creating the folder fails.** The folder's path is a file, so
  `mkdir(exist_ok=True)` raises `FileExistsError`: `exist_ok` only tolerates an
  existing folder. The error propagates unchanged, and nothing is renamed or
  written. The reserve-and-restore path never runs in this case, which is why
  the next case is separate.
- **The copy fails partway** (`copy2` writes part of the file, then raises):
  - a same-name file from an earlier run is back in place, byte-identical;
  - the partial file is gone, and no `.old-*` file remains;
  - the error propagates unchanged.
- **The copy is interrupted** (`copy2` raises `KeyboardInterrupt`): the same
  restore, and the `KeyboardInterrupt` propagates.
- **Renaming the old file aside is refused** (`os.replace` raises
  `PermissionError`), with a short timeout passed in:
  - refused a few times, then allowed: the copy completes;
  - refused past the timeout: the error propagates, the old file stays in
    place, and nothing is written.
- **Copying again:** the same name is replaced, with no `.old-*` file left
  behind. A file of another version is untouched.

**The CLI matrix.** These cases extend the `(command, flags) → artifacts[]`
matrix in `tests/cli/test_build_package_outcome.py`,
`test_build_package_json.py` and `test_build_package_human_output.py`. They
check how each backend uses the copy function, not the function's own rules:

- `package -p android`, `-f aab` and `--abi x86_64` each record one `apk` or
  `aab` at the path in 3.2, and stdout's product line names it. The first of
  these starts with no `dist/` folder, as on a clean checkout, as an
  end-to-end check.
- The ABI qualifier follows the contents (Q1):
  - `--abi x86_64` with `abis = ["arm64_v8a", "x86_64"]` is qualified;
  - `--abi x86_64` with `abis = ["x86_64"]` is not;
  - a default package from a one-ABI config is not.
- `package -p ios`, with the default export method, `ad-hoc` and
  `development`, records one `ipa` at the path in 3.2. stdout has the
  unchanged `Exported` line followed by the `Packaged` line.
- The in-tree file still exists after `package`, because the copy is not a
  move.
- `build -p android --debug` and `build -p ios --release` keep their paths and
  their lines.
- With a dynamic version that has a local segment, `+` becomes `_` in the name.
- **The copy fails on Android** (`copy_in` raises `OSError`):
  - the result is `ok: false`, `artifacts == []`, `KF-ERROR` and exit 1;
  - stdout is one document;
  - the message is `os_failure()`'s, `could not copy … into dist/android: …`;
  - no file in `dist/` is named.
- **The copy fails on iOS, after a successful export** (`copy_in` raises
  `OSError`). This guards the step 2 change: `_xcodebuild_step7` records the
  in-tree `.ipa` as soon as it is called (3.5).
  - In `--json` mode, stdout is one failure envelope with `artifacts == []`.
    Neither the in-tree `.ipa` nor a same-name file in `dist/ios/` is named.
  - In human mode, the `Exported …` line may appear, and no `Packaged …` line
    does. Product lines are suppressed under `--json` (`console.line`), which
    is why the two modes are checked separately.
- **`package` fails before the copy** (for example, Gradle fails): a same-name
  file in `dist/` is untouched and not named.
- `clean` removes `dist/android` and `dist/ios`, then `dist/` once it is empty.

**Backend tests in `tests/platforms/android/test_cli.py`.** Some existing tests
change and some must not:

- **These change,** because `android_package` now records the `dist/` file:
  - `TestAndroidPackage.test_success_assembles_release_apk`;
  - `TestAndroidPackage.test_success_bundles_release_aab`;
  - the manifest-policy test that asserts `out.name == "app-release.apk"`.
  
  They assert the 3.2 name, and that the in-tree `app-release.*` still exists.
- **These stay as they are,** because they cover in-tree paths this change
  keeps:
  - `TestDebugReleaseOutputPaths`, which checks the `_debug_output` and
    `_release_output` names;
  - the `run --release` and `run --no-build` tests that install
    `app-release.apk` from the generated project.
  
  A failure in these means the change moved something it should only have
  copied.

`tests/platforms/ios/xcode/test_commands.py` asserts the in-tree `ipa_path`,
which is also unchanged.

**CI.** With step 5, the existing Android jobs on Linux and on the Windows host
find the `dist/` file through the `--json` envelope, and run their artifact
and signature checks against it.

**Real toolchain, on this Mac.** No CI job runs `package -p ios`, so run it
once on an example with real signing, confirm the `.ipa` in `dist/ios/` matches
the exported one, and add a dated row to `test-matrix.md` §7.

## 10. Migration

Draft CHANGELOG note:

- **Changed:** `kivyforge package -p android` and `-p ios` also write the
  finished artifact to `dist/android/` and `dist/ios/` under a versioned name
  (`dist/android/myapp-1.2.0.apk`, `dist/ios/myapp-1.2.0.ipa`), as
  `package -p linux` already does
  ([#112](https://github.com/ElliotGarbus/kivyforge/issues/112)).
- **Migration:**
  - The in-tree files remain, so a script that reads `app-release.apk`,
    `app-release.aab` or `<app>-ios/build/<app>.ipa` after `package` keeps
    working. New scripts should read the `dist/` path, or
    `data.artifacts[].path` from `--json`, which now names the `dist/` file.
  - `kivyforge clean` now also removes `dist/android/` and `dist/ios/`,
    including older versions kept there.
  - `build`'s output is unchanged.

## 11. Done when

- The hermetic cases in section 9 pass, and CI's Android jobs check the
  `dist/` file on Linux and on a Windows host.
- `test-matrix.md` §7 has a dated row for `package -p ios` on this Mac.
- The #112 reporter has been told:
  - where release outputs now land;
  - that `package -p android` with a keystore is how to get a versioned APK in
    `dist/`;
  - why the debug APK stays in the generated project (5.2), and to say if
    they need debug builds specifically;
  - that distinct names per build need a changing version.
- The implementation's PR refers to #112 without a closing keyword ("Fixes",
  "Closes"), because this change does not cover the debug APK. #112 is closed
  only once the reporter confirms that release artifacts are enough. If they
  need debug builds, it stays open for 5.2's `-f debug-apk`.
