# Proposal — macOS native binaries out of `Contents/Resources/bin`

> Status: **proposed 2026-10-23, revised after review the same day**. Written
> for [#174](https://github.com/ElliotGarbus/kivyforge/issues/174).
> Code claims were read from the source at `8611f4b1`.
> The dyld and ad-hoc signing results in section 2 come from local spikes on
> 2026-10-23 (macOS 26.6.2, Xcode 27.0, Apple clang 21.0.0, arm64), the
> second using the bundled CPython 3.13.14 from a `hello-native` build.
> A clean break: with two beta users and no installed base, the bundle keeps
> no compatibility symlinks and `Resources/bin/` goes away.
> The review changed section 3: links are checked per loading process rather
> than with every helper's run paths pooled; absolute and bare-name links to
> a declared library are checked too; only `MH_EXECUTE` and `MH_DYLIB` are
> accepted; weak links warn; bundles are found by structure as well as by
> suffix; collisions are checked case-insensitively, per location and before
> anything is written; unsupported code has its own failure code.

## 1. Problem

`[tool.kivy.macos.native.binaries]` stages every file into
`Contents/Resources/bin/` (`native_stage.py`, through the shared
`artifacts/native_stage_util.py`). Apple reserves `Contents/Resources/` for
data. Its
[placement table](https://developer.apple.com/documentation/bundleresources/placing-content-in-a-bundle)
puts a dynamic library in `Contents/Frameworks/`, a helper tool in
`Contents/MacOS/` or `Contents/Helpers/`, and a plug-in in
`Contents/PlugIns/`, and warns that misplaced code "might work during
day-to-day development, but might cause problems during notarization".
[TN2206](https://developer.apple.com/library/archive/technotes/tn2206/_index.html)
says code anywhere else is "sealed as data (resource) files" and sealed twice.
Issue #174 has the full quotes and the evidence that it works today (a
notarized `dice-roller`, and spike 6 of the `include_files` work notarizing a
Mach-O at `Contents/Resources/helper`).

The channel also does two jobs. Besides code, it carries whatever else an
archive holds (headers, licences, config) and single-file scripts, all into
one directory on `PATH`. `include_files` now handles data and `app_dir`
handles scripts, so after this change the channel carries native code only.

## 2. What the spikes found

### 2.1 Helpers

A scratch `Spike.app` held a library `libx.dylib` and four helpers that link
it in four ways. It was built twice: once in today's layout (everything under
`Resources/bin/`) and once in the proposed one (helpers in
`Contents/Helpers/`, the library in `Contents/Frameworks/`). All Mach-O files
were ad-hoc signed, then the bundle.

| Helper links the library as | Today's layout | Proposed layout |
|---|---|---|
| A: `@executable_path/libx.dylib` | runs | **fails** |
| B: `@rpath/libx.dylib`, rpath `@executable_path` | runs | **fails** |
| C: `@rpath/libx.dylib`, rpath `@executable_path/../Frameworks` (Apple's form) | **fails** | runs |
| D: `@loader_path/libx.dylib` | runs | **fails** |

A helper that expects its library in its own directory (A, B, D) works today
only because everything shares one directory. Apple's form (C), from
[Embedding nonstandard code structures in a bundle](https://developer.apple.com/documentation/xcode/embedding-nonstandard-code-structures-in-a-bundle),
works only in the proposed layout. `codesign --verify --deep --strict` passed
for the proposed layout. dyld resolves `@executable_path` and `@loader_path`
from a binary's real path, so a symlink at the old location would not have
helped.

### 2.2 Libraries loaded from Python

> **Superseded in part, 2026-10-31 (#201).** The launcher now runs CPython in
> its own process instead of `execv`ing `python3`, so for a `ctypes` load the
> main executable is `Contents/MacOS/<app>`: `@executable_path` is
> `Contents/MacOS/`, and the run path is the launcher's
> `@executable_path/../Resources/python/lib` — the same directory `python3`'s
> run path named. A3 to A8 are unchanged. A1 now **resolves**
> (`test_a1_resolves_in_the_apps_process` runs it under dyld). The
> measurements below are kept as taken.

The launcher does not stay running: it `execv`s the bundled interpreter
(`launcher.py`). So for a library the app loads with `ctypes`, the process's
main executable is `Contents/Resources/python/bin/python3.13` (`python3` is a
symlink to it), not `Contents/MacOS/<app>`. Its only run path is
`@executable_path/../lib`. Library `libA*` links `libB`; each was loaded by
absolute path with `ctypes.CDLL` from that interpreter.

| `libA` links `libB` as | Loaded alone | After `ctypes.CDLL(<libB path>)` |
|---|---|---|
| A1: `@executable_path/../Frameworks/libB.dylib` | **fails**, tried `Resources/python/Frameworks/` | not run |
| A2: `@rpath/libB.dylib`, rpath `@loader_path` | runs | — |
| A3: `@rpath/libB.dylib`, no rpath of its own | **fails**, tried `Resources/python/lib/` (the interpreter's rpath) | runs |
| A4: `/usr/local/lib/libB.dylib`, which is `libB`'s install name | **fails** | runs |
| A5: `libB.dylib` (bare), `libB`'s install name is `@rpath/libB.dylib` | **fails** | **fails** |
| A6: `/usr/local/lib/libB.dylib`, `libB`'s install name is `@rpath/libB.dylib` | **fails** | **fails** |
| A7: `libB.dylib` (bare), which is `libB`'s install name | not run | runs |
| A8: weak `@rpath/libB.dylib`, unresolvable | loads | — |

Four things follow:

- `@executable_path` in a library means the main executable of whichever
  process loaded it. The same library resolves it to `Contents/Helpers/` in a
  helper and to `Contents/Resources/python/bin/` under `ctypes`, so it has to
  be judged per process.
- `@rpath` searches the run paths of the loading chain up to the main
  executable. A3 failed in the interpreter's `lib/`, not in any helper's
  directory, so pooling run paths across unrelated processes would be wrong.
- A library the app has already loaded satisfies a later link whose text is
  exactly that library's install name, whatever the path says (A3, A4, A7).
  If the text is anything else, it does not (A5, A6). Python code that loads
  a vendor SDK's libraries in dependency order relies on this.
- A missing weak link does not stop the library loading (A8).

`hello-native` would not have caught any of this: `roll` does not link
`libgreet` (`otool -L` lists only `libSystem`).

## 3. Proposal

### 3.1 What is accepted and where it goes

| Staged file | Location |
|---|---|
| Mach-O, file type `MH_EXECUTE` | `Contents/Helpers/<basename>` |
| Mach-O, file type `MH_DYLIB` | `Contents/Frameworks/<basename>` |
| Any other Mach-O file type (`MH_BUNDLE`, `MH_OBJECT`, `MH_DYLINKER`, `MH_KEXT_BUNDLE`, ...) | refused, `KF-MACOS-NATIVE-UNSUPPORTED` |
| Not a Mach-O | refused or skipped, `KF-MACOS-NATIVE-NOT-CODE` (section 3.3) |

`MH_BUNDLE` is a plug-in, which Apple places in `Contents/PlugIns/`, and
plug-ins are out of scope. `Contents/Resources/bin/` is no longer created.

**Universal files.** The header reader handles `FAT_MAGIC` and
`FAT_MAGIC_64` in both byte orders, checks every slice's offset and size
against the file length, and refuses (`KF-MACOS-NATIVE-UNSUPPORTED`) a file
whose slices disagree on file type. A file without a slice for the target
arch fails the build; today only `doctor` notices that. `machotools.py`
parses thin 64-bit headers only today, so this is new.

**Staging.** `native_stage.py` calls the shared `stage_binaries()` into a
temporary directory, which keeps the download, SHA-256 check, archive
extraction and path-traversal guards in their one audited place. It then
plans every file's destination, runs the checks in sections 3.3 to 3.5
against the plan, and only then copies into the bundle.

### 3.2 How the app reaches them

- **Helpers run by name.** The launcher prepends `Contents/Helpers` to the
  child `PATH`, in place of `Resources/bin`.
- **Libraries load by absolute path,** as now. Under the Hardened Runtime
  (Developer ID builds) dyld scrubs `DYLD_*` variables unless the app has
  `com.apple.security.cs.allow-dyld-environment-variables`, which kivyforge
  does not grant by default, so loading by name cannot be relied on. The
  recipe becomes `Path(sys.prefix).parents[1] / "Frameworks" / "libgreet.dylib"`:
  `sys.prefix` is `Contents/Resources/python` (the launcher's `PYTHONHOME`),
  so `parents[1]` is `Contents/`. The cross-platform guide already shows the
  `ctypes` call per platform, so macOS getting its own path there costs
  nothing. No environment variable or helper function is added.

### 3.3 Native code only

- A **single-file source that is not a Mach-O** fails the build with
  **`KF-MACOS-NATIVE-NOT-CODE`**, exit 1. The message points at
  `include_files` for data and `app_dir` for scripts. `doctor` checks
  vendored sources for this before a build; URL sources are only seen at
  build time.
- **Archive members that are not Mach-O** (headers, licences, `README`s,
  static archives, the text files `zipfile` writes in place of zip symlinks)
  are skipped. The build reports them as a warning with the same code,
  naming up to ten. Refusing them would force users to repack vendor SDK
  archives they download by URL.
- **A bundle inside an archive** fails the build with
  **`KF-MACOS-NATIVE-UNSUPPORTED`**, exit 1: a bundle is code, but not code
  this channel can place, and pulling its binary out into a flat directory
  would break it. A Mach-O member is inside a bundle when any directory above
  it has a bundle suffix (`.app`, `.appex`, `.bundle`, `.dext`, `.framework`,
  `.kext`, `.mdimporter`, `.plugin`, `.prefPane`, `.qlgenerator`, `.saver`,
  `.service`, `.systemextension`, `.xpc`) or contains `Info.plist`,
  `Contents/Info.plist` or `Resources/Info.plist`. The structural test catches
  bundle types the list misses. A dot alone is not enough: archives often
  have a versioned top directory such as `ffmpeg-7.1/`.

### 3.4 Flat names, checked before anything is written

"Each code location must contain a flat list of code content", so an archive
member at `sdk/lib/libsdk.dylib` lands at `Contents/Frameworks/libsdk.dylib`.
`Helpers/` and `Frameworks/` are separate namespaces: Apple requires each to
be flat, not their names to differ from each other's.

Names are compared case-insensitively, because the default APFS volume is
case-insensitive and `Tool` and `tool` would land on the same file. Today's
check cannot catch that inside one archive: the shared extractor writes all
members into the temporary directory first, so a case-only clash has already
overwritten one file before `_claim` sees the result. The same gap exists on
Windows, which passes `casefold=True`. The fix belongs in
`native_stage_util.py`: when `casefold` is set, claim the archive's member
names (`namelist()`, `getnames()`) before extracting. macOS then passes
`casefold=True`, and checks the flattened destination names per location
before copying. Collisions keep today's message and stay unclassified
(`KF-ERROR`).

`doctor`'s static check compares vendored single-file sources whose
basenames match case-insensitively and that land in the same location (read
from their Mach-O type). URL sources are left to the build.

`Helpers/` rather than `MacOS/`: Apple allows a helper in either, and
`Helpers/` keeps `MacOS/` holding only the launcher, whose name comes from
the app (`config.app_slug`), so no user binary can collide with it.

### 3.5 Links to declared libraries must resolve

kivyforge does not rewrite load commands (macos-spec §Native binaries, "The
boundary"). It can refuse to ship a binary that will fail to load, which is
what this section does.

**What is read.** For every accepted Mach-O, from the target-arch slice: the
dependency load commands (`LC_LOAD_DYLIB`, `LC_LOAD_WEAK_DYLIB`,
`LC_REEXPORT_DYLIB`, `LC_LOAD_UPWARD_DYLIB`, `LC_LAZY_LOAD_DYLIB`), the
`LC_RPATH` entries, and a library's own install name (`LC_ID_DYLIB`).
The parser is pure Python over the header bytes, like `read_macho_cpu_type`,
so the hermetic suite can test it on synthetic headers.

**Which links are checked.** A dependency refers to a declared library when
its text is that library's install name, or when its leaf name is the
library's file name, compared case-insensitively. Every form is checked:
`@executable_path/`, `@loader_path/`, `@rpath/`, absolute and bare. The one
exception is an absolute path under `/usr/lib/` or `/System/`, which the
dyld shared cache satisfies even if the app also ships a library with that
leaf name. Links to libraries this channel did not stage (system libraries,
`libpython`, undeclared libraries) are not checked: kivyforge does not own
them.

**Processes.** Each link is resolved in every process that can reach it,
separately, never with run paths pooled across processes:

- **Each helper** is a process of its own. `@executable_path` is
  `Contents/Helpers/`.
- **The interpreter**, for libraries the app loads with `ctypes`.
  `@executable_path` is the staged interpreter's real directory,
  `Contents/Resources/python/bin/`, and its own run paths (read from the
  staged binary, `@executable_path/../lib` today) are at the bottom of every
  chain. A library is treated as loaded from Python when no helper links it.
  A library that a helper links is judged only in that helper's process; one
  used both ways is checked for the helper path only, a gap stated in the
  docs.

Within a process, the check walks each dependency chain from the root. For a
link in image `I` reached through `root, ..., I`:

- `@loader_path` is `I`'s own directory.
- `@rpath/X` tries `I`'s run paths, then each loader's back to the root,
  in that order, each expanded with its own image's `@loader_path` and the
  process's `@executable_path`.
- A cycle ends the walk.

**Outcome.**

| Link does not resolve to the declared library, and | Result |
|---|---|
| it is weak (`LC_LOAD_WEAK_DYLIB`) | warning |
| the process is the interpreter, and the link text is the library's install name | warning: it loads only if the app loads that library first (A3, A4, A7) |
| otherwise | build fails, `KF-MACOS-NATIVE-LOAD-PATH`, exit 1 |

Errors and warnings use the same code. The message names the binary, the
process it was resolved in, the load command and every path tried, and gives
Apple's fix for the binary's kind: an `@rpath/` install name, plus
`install_name_tool -add_rpath @executable_path/../Frameworks` for a helper or
`@loader_path` for a library. An absolute or bare link gets the
`install_name_tool -change` step from the same Apple article.

### 3.6 Other parts of the macOS backend

- **Signing:** `_machos_inside_out` walks the bundle by file magic, so
  `Helpers/` and `Frameworks/` are swept like everything else, inside out.
  One change, found by the first real `hello-native` build: `Helpers/roll` is
  no deeper than `MacOS/<exe>`, and `codesign` refuses the main executable
  while `Helpers/` or `Frameworks/` holds unsigned code ("code object is not
  signed at all / In subcomponent"). `Resources/bin` never triggered this
  because it is not a code location. `Contents/MacOS/` now signs after every
  other Mach-O and before the bundle seal.
- **`doctor`:** the arch check walks `Contents/Helpers/` and
  `Contents/Frameworks/` instead of `Resources/bin/`, and the not-code and
  collision checks cover vendored single-file sources.
- **`include_files`:** `Resources/bin` comes off the reserved list
  (`includes.py`, macos-spec §Data files), since the bundler no longer writes
  it. `Helpers/` and `Frameworks/` are already outside the allowed roots
  (`Resources`, `SharedSupport`). The `KF-INCLUDE-NATIVE-CODE` message still
  points at `[tool.kivy.macos.native.binaries]`, which now places code where
  Apple says.

## 4. What changes for users

`CHANGELOG.md` gets a **breaking** entry with this migration note:

- Native binaries declared in `[tool.kivy.macos.native.binaries]` now live in
  `Contents/Helpers/` (executables) and `Contents/Frameworks/` (dynamic
  libraries). `Contents/Resources/bin/` no longer exists.
- Helpers still run by name. Load a library from
  `Path(sys.prefix).parents[1] / "Frameworks"` instead of
  `Path(sys.prefix).parent / "bin"`.
- A single-file source that is not a Mach-O is refused
  (`KF-MACOS-NATIVE-NOT-CODE`): move scripts to `app_dir` and data to
  `include_files`. Archive members that are not Mach-O are skipped with a
  warning.
- Plug-ins (`MH_BUNDLE`), other non-executable Mach-O types and bundles
  inside archives are refused (`KF-MACOS-NATIVE-UNSUPPORTED`).
- A binary whose link to a declared library will not resolve fails the build
  (`KF-MACOS-NATIVE-LOAD-PATH`). Relink it as the message says.
- Two executables, or two libraries, whose names differ only in case collide.

Docs to update: macos-spec §Native binaries (including the cross-platform
`Path(sys.prefix).parent / "bin"` claim) and §Data files, the macOS row and
`ctypes` tab in `guides/cross-platform/native-binaries.md`,
`reference/pyproject/macos.md`, `signing-prerequisites-macos.md`, the template
comment in `cli/init_writer.py`, the comment in
`examples/desktop/hello-native/pyproject.toml`, and `hello-native`'s
`native_bin_dir()` in `src/main.py`.

## 5. Not in scope

- **`Resources/lib/` and `Resources/python/`.** In `hello-native`, 55 of the
  58 Mach-O files live there (extension modules and the runtime). Moving them
  is the PyInstaller 6 change and touches `sys.path`, `PYTHONHOME` and
  byte-compilation. It deserves its own issue. If it lands,
  `Contents/Frameworks/` becomes shared with the runtime and needs a naming
  rule, and the interpreter's location in section 3.5 moves.
- **Rewriting load commands.** Still the vendor's job (or the user's, with
  `install_name_tool`). Section 3.5 makes a bad link a build error; it does
  not fix it.
- **Plug-ins and bundles** (`Contents/PlugIns/`, `.framework`). Refused for
  now.
- **Per-helper entitlements.** Unchanged from macos-spec's "Two edges of the
  sweep".

## 6. Decisions for review

1. The channel is native code only: single-file non-code sources are refused,
   and non-code archive members are skipped with a warning rather than
   refused (section 3.3).
2. Only `MH_EXECUTE` and `MH_DYLIB` are accepted (section 3.1).
3. `Contents/Helpers/` over `Contents/MacOS/`, with separate case-insensitive
   name sets per location (section 3.4).
4. A library no helper links is judged as loaded from Python; one a helper
   links is judged only in that helper's process (section 3.5). Judging every
   library from Python as well would warn on correct helper-only libraries
   that use Apple's `@executable_path/../Frameworks` form, which is A1.
5. An unresolved link from Python whose text is the library's install name is
   a warning, because loading in dependency order makes it work (section 2.2).
6. Three new codes, each with one meaning and one fix, all exit 1 when they
   fail the build: `KF-MACOS-NATIVE-NOT-CODE` (not code: use `include_files`
   or `app_dir`), `KF-MACOS-NATIVE-UNSUPPORTED` (code this channel cannot
   place), `KF-MACOS-NATIVE-LOAD-PATH` (relink).
7. No environment variable or helper API for the `Frameworks` path; the
   documented recipe is enough (section 3.2).

## 7. Verification

1. **Hermetic tests:**
   - The header reader: thin, `FAT_MAGIC` and `FAT_MAGIC_64` in both byte
     orders, slices out of bounds, slices disagreeing on file type, and no
     slice for the target arch.
   - Classification and refusal of every non-accepted file type.
   - Bundle detection by suffix and by structure, and no false positive on a
     versioned directory such as `ffmpeg-7.1/`.
   - Case-insensitive name clashes inside one archive, across archives, and
     across single files, each caught before anything is written. This
     includes the Windows path through the shared extractor.
   - The resolver on synthetic headers: section 2.1's A to D in a helper's
     process; section 2.2's A1 to A8 in the interpreter's; a library reached
     through two helpers, where it resolves through one and not the other;
     cycles; and the `/usr/lib/` exception.
   - `doctor`'s arch, not-code and collision checks, and the launcher source
     naming `Helpers`.
2. **A `requires_toolchain` test** that compiles section 2's libraries and
   helpers with `clang`, stages them through `stage_native_binaries` into a
   bundle with a real staged interpreter, ad-hoc signs with
   `sign_bundle_adhoc`, verifies with `codesign --verify --deep --strict`,
   runs helper C by name with the launcher's `PATH`, loads A2 with `ctypes`
   from the documented path, and checks that the build refuses A, B, D and A1
   and warns on A3. The `Integration (macOS)` CI job runs `pytest` with
   `KIVYFORGE_REQUIRE_TOOLCHAIN=1`, so this runs on every push instead of
   skipping. `macos-gate` cannot carry native binaries: its lock is committed
   and checked with `lock --check`, and a `clang` build is not byte-for-byte
   reproducible across runner images.
3. **Hardware checklist:** `desktop-macos` (which includes `hello-native`) and
   `macos-notarize` on a build of this branch, recorded in test-matrix §7.
   Notarizing helpers in `Contents/Helpers/` and libraries in
   `Contents/Frameworks/` is the case Apple documents, so this confirms
   rather than settles a question.

## 8. Order of work

1. The header reader (fat, file type, load commands) in `machotools.py`, with
   its tests.
2. Claiming archive member names before extraction in `native_stage_util.py`
   when `casefold` is set, with tests on both platforms' paths.
3. Classification, bundle detection, planning, per-location collision sets
   and copying in `native_stage.py`, with `KF-MACOS-NATIVE-NOT-CODE` and
   `KF-MACOS-NATIVE-UNSUPPORTED`.
4. The resolver and `KF-MACOS-NATIVE-LOAD-PATH`.
5. The launcher's `PATH`, `doctor`, and the `include_files` reserved list.
6. The `requires_toolchain` test.
7. Docs, `hello-native`, `CHANGELOG.md`, then section 7 step 3.

Each new code goes in `report/diagnostics.py`, with its meaning and
remediation in `docs/hooks/kf_generated.py`, which validates that every code
has one.

## Appendix: reproducing section 2

### Helpers (section 2.1)

Run from an empty directory on a Mac with the Xcode command-line tools. C
prints `greet=42`; A, B and D fail with `Library not loaded`.

```bash
set -e
cat > lib.c <<'EOF'
int greet(void) { return 42; }
EOF
cat > helper.c <<'EOF'
#include <stdio.h>
int greet(void);
int main(void) { printf("greet=%d\n", greet()); return 0; }
EOF
echo 'int main(void){return 0;}' > main.c
clang -dynamiclib -install_name @rpath/libx.dylib -o libx.dylib lib.c
clang -o helperA helper.c libx.dylib
install_name_tool -change @rpath/libx.dylib @executable_path/libx.dylib helperA
clang -o helperB helper.c libx.dylib -Wl,-rpath,@executable_path
clang -o helperC helper.c libx.dylib -Wl,-rpath,@executable_path/../Frameworks
clang -o helperD helper.c libx.dylib
install_name_tool -change @rpath/libx.dylib @loader_path/libx.dylib helperD
clang -o App main.c

C=Spike.app/Contents
mkdir -p $C/MacOS $C/Helpers $C/Frameworks
cp App $C/MacOS/
cp helperA helperB helperC helperD $C/Helpers/
cp libx.dylib $C/Frameworks/
plutil -create xml1 $C/Info.plist
plutil -insert CFBundleExecutable -string App $C/Info.plist
plutil -insert CFBundleIdentifier -string org.example.spike174 $C/Info.plist
plutil -insert CFBundlePackageType -string APPL $C/Info.plist

for f in $C/Helpers/helper? $C/Frameworks/libx.dylib $C/MacOS/App; do
    codesign --force --sign - --timestamp=none "$f"
done
codesign --force --sign - --timestamp=none Spike.app
codesign --verify --deep --strict --verbose=2 Spike.app
for h in helperA helperB helperC helperD; do
    printf '%s: ' $h; $C/Helpers/$h 2>&1 | head -1 || true
done
```

To see today's layout instead, copy all five Mach-O files into
`$C/Resources/bin/` and run the helpers from there: A, B and D run and C fails.

### Libraries loaded from Python (section 2.2)

Set `APP` to any `.app` built by kivyforge, then run from an empty directory.
Each line prints `42` or the end of dyld's `Library not loaded` message.

```bash
set -e
APP="$HOME/path/to/Your App.app"
PYHOME="$APP/Contents/Resources/python"
py() { PYTHONHOME="$PYHOME" "$PYHOME/bin/python3" -c "import ctypes; $1" 2>&1 | tail -1; }
mkdir -p F
echo 'int b(void){return 7;}' > b.c
echo 'int b(void); int a(void){return b()*6;}' > a.c
clang -dynamiclib -install_name @rpath/libB.dylib -o F/libB.dylib b.c
clang -dynamiclib -install_name /usr/local/lib/libB4.dylib -o F/libB4.dylib b.c
clang -dynamiclib -install_name @rpath/libB6.dylib -o F/libB6.dylib b.c
clang -dynamiclib -install_name libB7.dylib -o F/libB7.dylib b.c
lib() { clang -dynamiclib -install_name @rpath/$1.dylib -o F/$1.dylib a.c "${@:2}"; }
lib libA1 F/libB.dylib
install_name_tool -change @rpath/libB.dylib @executable_path/../Frameworks/libB.dylib F/libA1.dylib
lib libA2 F/libB.dylib -Wl,-rpath,@loader_path
lib libA3 F/libB.dylib
lib libA4 F/libB4.dylib
lib libA5 F/libB.dylib
install_name_tool -change @rpath/libB.dylib libB.dylib F/libA5.dylib
lib libA6 F/libB6.dylib
install_name_tool -change @rpath/libB6.dylib /usr/local/lib/libB6.dylib F/libA6.dylib
lib libA7 F/libB7.dylib
lib libA8 -Wl,-weak_library,F/libB.dylib

D=$PWD/F
for i in 1 2 3 4 5 6; do printf "A$i alone: "; py "print(ctypes.CDLL('$D/libA$i.dylib').a())"; done
printf "A3 after libB: ";  py "ctypes.CDLL('$D/libB.dylib'); print(ctypes.CDLL('$D/libA3.dylib').a())"
printf "A4 after libB4: "; py "ctypes.CDLL('$D/libB4.dylib'); print(ctypes.CDLL('$D/libA4.dylib').a())"
printf "A5 after libB: ";  py "ctypes.CDLL('$D/libB.dylib'); print(ctypes.CDLL('$D/libA5.dylib').a())"
printf "A6 after libB6: "; py "ctypes.CDLL('$D/libB6.dylib'); print(ctypes.CDLL('$D/libA6.dylib').a())"
printf "A7 after libB7: "; py "ctypes.CDLL('$D/libB7.dylib'); print(ctypes.CDLL('$D/libA7.dylib').a())"
printf "A8 alone: ";       py "ctypes.CDLL('$D/libA8.dylib'); print('loaded')"
```
