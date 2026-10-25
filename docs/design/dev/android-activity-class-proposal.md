# Proposal — an app-owned main activity: `[tool.kivy.android].main_activity`

> Status: **accepted design, 2026-10-24; not implemented.** All five
> decisions in section 5 are closed. Implementation order: #182
> (`xmlns:tools`) and the `src.java` fix (section 3.3), independently; then
> the `main_activity` key. Written for
> [issue #85](https://github.com/ElliotGarbus/kivyforge/issues/85). Code claims
> were read from `25c0483d`. Every runtime claim was measured on an emulator;
> the runs, verbatim output and two defects are in
> [`android-activity-class-spike-findings.md`](android-activity-class-spike-findings.md),
> whose §"Spike 2" covers the compile-time verifier added in this revision.
> The `ComponentActivity` half of #85 is a separate spike,
> [`android-componentactivity-spike-findings.md`](android-componentactivity-spike-findings.md),
> and is not changed by this proposal.
>
> Revision history: the first draft rendered `android.config` from the custom
> class, checked the class by scanning source files, required
> `[tool.kivy.android.src]`, rejected the explicit default, kept the base
> activity in the export allowlist, and conflated p4a's two flags. Review
> caught all six; each is corrected below with the evidence that settles it.
> A second pass against the Android reference pages the claims rest on
> changed no decision but found that the documented App Startup manifest entry
> cannot be written through `extra_application_xml` today (decision 5), and
> sharpened the `super` guidance, the `registerForActivityResult` timing, the
> `.MainActivity` shorthand, the null launch intent, and added
> `AppComponentFactory` to the declined list.

Some Android SDKs want a line of Java in the activity's `onCreate`: a payment
SDK that reads its key from the activity, an SDK that calls
`registerForActivityResult` (which Android refuses once the activity has
started), a vendor that documents "add this to your Activity". kivyforge
generates the activity and offers no way to put code there. python-for-android
and buildozer do (`--android-entrypoint`, `android.entrypoint`), and
`kivyforge init` currently tells a buildozer user that key has no equivalent.

The conclusion: **add one optional key, `[tool.kivy.android].main_activity`,
naming an app-supplied subclass of `org.kivy.android.PythonActivity` that
becomes the launcher activity; prove the class at compile time with a
generated one-method Java file; make every place that names the launcher
follow the key while the bundled `android` package keeps naming the base;
fix the `[tool.kivy.android.src]` defect it depends on; and do not invent a
kivyforge hook interface, because Android already provides the composition
mechanism library code needs and it works in a kivyforge app today.**
Section 3 is the design; sections 1 and 2 say why it has to be this one.

## 1. The problem, precisely

Python in a kivyforge app starts on SDL's thread after the surface exists. The
spike timed it: the subclass's `onCreate` returned at 39.040, the first line of
`main.py` ran at 39.820, Kivy's `on_start` at 41.302. So:

- **Nothing written in Python can run inside `onCreate`.** The bundled
  `android.activity` module (`bind`, `register_activity_lifecycle_callbacks`)
  is the right tool for everything that can wait until Python is up, and it
  already exists. This proposal is only about what cannot wait.
- **Briefcase's answer is not available to kivyforge.** Briefcase's
  `MainActivity` forwards `onCreate`, `onStart`, `onActivityResult` and the
  rest to a Python `IPythonApp` object
  ([MainActivity.java](https://github.com/beeware/briefcase-android-gradle-template/blob/main/%7B%7B%20cookiecutter.format%20%7D%7D/app/src/main/java/org/beeware/android/MainActivity.java)).
  That works because Chaquopy runs the app's Python *synchronously inside*
  `MainActivity.onCreate`, so the Python `onCreate` hook really does run during
  the activity's creation. Under SDL the activity returns from `onCreate` long
  before Python exists.

So the code has to be Java (or Kotlin), and it has to be compiled into the app.
`[tool.kivy.android.src]` is the declared place for that, and section 3.3
explains why it has never actually worked.

## 2. How the neighbours do it, and what the platform vendors recommend

### 2.1 python-for-android and buildozer: two flags for one idea

p4a's `bootstraps/common/build/build.py` has **two** options that both default
to `org.kivy.android.PythonActivity`, and they feed different things:

- `--android-entrypoint` — "which java class will be used for startup, usually
  a subclass of PythonActivity". It is the launcher's `android:name` in the
  SDL manifest template (`bootstraps/_sdl_common/build/templates/AndroidManifest.tmpl.xml`
  line 68: `<activity android:name="{{args.android_entrypoint}}"`).
- `--activity-class-name` — "the full java class name of the main activity".
  It goes into the bundled `android/config.py` as `ACTIVITY_CLASS_NAME` and,
  with dots replaced by slashes, `ACTIVITY_CLASS_NAMESPACE`
  (`recipes/android/__init__.py` lines 64-65).

buildozer exposes them one to one: `android.entrypoint` becomes
`--android-entrypoint` (`targets/android.py` line 1161) and
`android.activity_class_name` becomes `--activity-class-name` when it is not
the default (lines 118-121). Its `default.spec` says to "use that parameter
together with `android.entrypoint`". There is also `--service-class-name` for
the same trick on `PythonService`.

The second flag carries a defect this proposal must not copy. p4a's
`android.activity`, `android.permissions` and `android.darkmode` implement
Java interfaces by name as `ACTIVITY_CLASS_NAMESPACE + '$NewIntentListener'`,
`'$PermissionsCallback'`, `'$DarkModeListener'`. Nested-type binary names are
not inherited: `org/example/MainActivity$PermissionsCallback` does not exist
when `MainActivity` merely extends `PythonActivity`, so pointing
`activity_class_name` at a subclass breaks every one of those modules at the
first `bind()` or `request_permissions()`. The constant that actually needs to
follow the subclass is nothing: `autoclass(<base>).mActivity` already returns
the subclass instance (spike, section 4). kivyforge therefore has **one** key,
the launcher, and leaves `android.config` on the base class (section 3.2).

The model is still p4a's: one slot, owned by the app author, who composes as
many SDKs as they like inside their one subclass.

### 2.2 Briefcase: no key; change the template, or hook from Python

Briefcase's Android backend has no configuration key for the activity class
([Gradle project reference](https://briefcase.readthedocs.io/en/stable/reference/platforms/android/gradle.html)).
`MainActivity extends AppCompatActivity` is part of the project template; app
code receives lifecycle events in Python through `IPythonApp` (section 1), and
the sanctioned way to change the Java is a custom project template. Briefcase
does ship the manifest escape hatches kivyforge already mirrors
(`android_manifest_*_extra_content`).

### 2.3 What Android's own documentation says

Three documented mechanisms cover the two different authors involved:

- **The app author who needs code in the activity subclasses the activity.**
  That is the ordinary Android shape; there is nothing more idiomatic.
- **A library that must run before any activity uses a `ContentProvider`**,
  which Android instantiates before `Application.onCreate`, or AndroidX
  [App Startup](https://developer.android.com/topic/libraries/app-startup),
  which shares one provider among many `Initializer`s. From there, a library
  hooks every activity's lifecycle with
  [`Application.ActivityLifecycleCallbacks`](https://developer.android.com/reference/android/app/Application.ActivityLifecycleCallbacks):
  `onActivityCreated` runs inside the activity's `super.onCreate()`, and from
  API 29 `onActivityPreCreated` and `onActivityPostCreated` bracket it. No
  activity subclass, no slot to compete for.
- **Subclassing `Application` is discouraged.** The
  [`Application` reference](https://developer.android.com/reference/android/app/Application)
  says: "There is normally no need to subclass Application. In most situations,
  static singletons can provide the same functionality in a more modular way."
  kivyforge already reserves `<application android:name>`
  (`generate/manifest.py`, `RESERVED_APPLICATION_ATTRS`), for the reasons the
  native-integration contract gives (SPEC.md §2.4, §11).
- **`registerForActivityResult` "must be called before the fragment or
  activity is created"** — a field initialiser or `onCreate`, in the words of
  [Get a result from an activity](https://developer.android.com/training/basics/intents/result);
  the registry enforces it by throwing once the activity is `STARTED` — and it
  exists only on `androidx.activity.ComponentActivity`. An SDK that
  needs it needs both this proposal (code in `onCreate`) and the
  `ComponentActivity` change (a base class that has the method). The two
  combine; the subclass inherits whatever base the bootstrap has.

The spike confirmed the second point in a kivyforge app with no change to
kivyforge: a provider declared through `extra_application_xml` ran at 38.194,
before the first activity callback at 38.246, and its
`ActivityLifecycleCallbacks` saw every lifecycle step of the launcher and
reached `PythonActivity.registerNewIntentListener` from `onActivityCreated`.
App Startup's `startup-runtime` happens to be on every kivyforge app's
classpath today (Material 1.11.0 -> emoji2 -> lifecycle-process), but a
transitive dependency is not a contract: the guide tells a library author to
declare `androidx.startup:startup-runtime:1.2.0` (the version the App Startup
page names) explicitly in `[tool.kivy.android.gradle].dependencies`, and to
make their `Initializer` discoverable with the manifest entry the page
documents:

```xml
<provider android:name="androidx.startup.InitializationProvider"
    android:authorities="${applicationId}.androidx-startup"
    android:exported="false"
    tools:node="merge">
    <meta-data android:name="com.example.MyInitializer" android:value="androidx.startup" />
</provider>
```

**That snippet cannot be pasted into `extra_application_xml` today.** The
generated manifest declares only `xmlns:android` (`generate/manifest.py`
line 188), and `tests/test_artifact_checks.py` pins, on purpose, that a
`tools:`-prefixed attribute fails well-formedness at generation time. The
documented library route therefore depends on a decision about the `tools`
namespace that is wider than this key; it is decision 5 in section 5, with
the two workable answers. The `ContentProvider` route needs no `tools:` and
is what the spike ran; it works today. Either way, the `ContentProvider`
reference says `onCreate` "is called for all registered content providers on
the application main thread at application launch time" and "must not
perform lengthy operations" — the guide tells a library to register its
callbacks there and do nothing else.

### 2.4 The iOS counterpart, for symmetry

kivyforge's iOS bootstrap has the same gap. `kivyforge_main` calls
`SDL_RunApp`, which calls `UIApplicationMain` with SDL's own
`SDLUIKitDelegate`, and Python starts in SDL's main callback — after
`application(_:didFinishLaunchingWithOptions:)` has returned. Apple's
documented routes map onto Android's: the **app author** puts launch code in
the `UIApplicationDelegate`, which under SDL means a subclass of
`SDLUIKitDelegate` named through a category overriding
`+getAppDelegateClassName` (the subclassing notice in SDL's
`SDL_uikitappdelegate.m`); a **library** observes
`UIApplication.didFinishLaunchingNotification` from `+load` or
`+initialize` and needs no app code. Method swizzling of the delegate is
the discouraged third route.

This proposal does not design the iOS key. It does keep the Android key
platform-scoped (`[tool.kivy.android].main_activity`, not `[tool.kivy]`) so
an iOS sibling — `[tool.kivy.ios].app_delegate_class`, if ever asked for —
is a parallel key, not a retrofit, and it documents the library-side route on
both platforms as the same idea: the vendor's lifecycle broadcast, not a
kivyforge interface.

### 2.5 What this means for #85's two options

The issue offers two shapes: (1) replace the launcher with a subclass, or (2) a
kivyforge-defined plugin interface for the `on...` methods. The spike says:

- (1) is cheap, needs no bootstrap change, and is what a buildozer migrant
  expects.
- (2) would duplicate `ActivityLifecycleCallbacks` with a kivyforge-private
  vocabulary, and the composition problem it exists to solve belongs to
  *library* code, which Android already serves. For library code shipped as a
  Python package, the native-integration contract explicitly defers startup
  hooks (SPEC.md §11) and omits `provider` from its component vocabulary (§6.6)
  until a real case forces the decision; a kivyforge-only hook now would make
  that decision by accident. The things `ActivityLifecycleCallbacks` does not
  cover — `onActivityResult`, `onNewIntent`, `onRequestPermissionsResult` — have
  p4a-compatible registries on `PythonActivity` that a hook can reach from
  `onActivityCreated`, and the AndroidX registry once the base is a
  `ComponentActivity`.

So: do (1) now; decline (2); document how library code hooks in without it.

## 3. The design

### 3.1 The key

```toml
[tool.kivy.android]
main_activity = "org.example.myapp.MainActivity"   # default: the generated org.kivy.android.PythonActivity

[tool.kivy.android.src]
java = ["android/java"]          # android/java/org/example/myapp/MainActivity.java
```

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `main_activity` | string | no | `org.kivy.android.PythonActivity` | Fully qualified name of the app's launcher activity, a concrete public subclass of the generated `org.kivy.android.PythonActivity` with a public no-argument constructor. Written as the main `<activity android:name>`; `kivyforge run`, `run --smoke`, the release manifest policy and the T3 artifact checks follow it. The bundled `android` package keeps naming the base class and reaches the subclass through `mActivity`. |

Named `main_activity` for the role it sets, in the words Android's own
documentation uses for this activity ("the main activity", the one with
`action.MAIN` + `category.LAUNCHER`; Android Studio's template calls the class
`MainActivity`), and matching the name the repo already uses internally
(`generate/manifest.py`'s `MAIN_ACTIVITY`, "the main `<activity>`" in the
design docs) and the sibling list `[[tool.kivy.android.activities]]`. It is
the counterpart of buildozer's `android.entrypoint`, not of
`android.activity_class_name` (section 2.1); `init`'s key table says so
(section 3.5). Not a lock input: like `src`, it is
read on every build, and changing it never stales a lock
(`kivyforge/lock/inputs.py`).

**Loader rule 22** (android/01 §validation). `main_activity`, when present:

- must be a string of two or more dot-separated Java identifiers. The
  `<activity>` element's documented shorthand `.MainActivity` (relative to
  the Gradle namespace) fails this rule; the hint says to write the full
  name, since kivyforge writes the manifest and nothing else resolves the
  dot;
- **the exact default, `org.kivy.android.PythonActivity`, is accepted and
  normalised to "unset"** — writing the documented default must never be an
  error, and this is the only value under a bootstrap namespace that is;
- any other value under a kivyforge bootstrap namespace — `org.kivy.android`,
  `org.libsdl.app`, `org.jnius`, `org.renpy.android`, the four prefixes
  android/04's shrinker keep list already treats as bootstrap-owned, checked by
  dot-segment containment — is rejected with a hint to use the app's own
  package. (This is kivyforge's own list, the "namespaces the consumer's own
  bootstrap occupies" that native-integration §6.1 adds to its six; it is not
  §6.1's list, which also names Chaquopy's and Briefcase's prefixes.)

Rule 22 does **not** require `[tool.kivy.android.src]`. The first draft did,
on the claim that the class can only come from the app's source. That is too
strong: `include_files` can stage Java under `app/src/main/java`, and an
`.aar` can be compiled against a copy of `PythonActivity`'s API. kivyforge
does not need to know where the class comes from, because the next check
proves it exists wherever it came from.

**Compile-time verifier.** When `main_activity` is set, generation emits one
file next to the bootstrap, `app/src/main/java/org/kivy/android/KivyforgeLauncherCheck.java`
(pruned by `_prune_stale` when the key is unset):

```java
// Generated by kivyforge; do not edit. Compiles only if
// [tool.kivy.android].main_activity names a concrete public subclass of
// PythonActivity with a public no-argument constructor.
package org.kivy.android;

final class KivyforgeLauncherCheck {
    private KivyforgeLauncherCheck() {}

    static PythonActivity launcher() {
        return new org.example.myapp.MainActivity();
    }
}
```

One expression, `PythonActivity x = new <configured>()`, is exactly the set of
facts Android needs of a launcher, and javac decides each one. The second
spike ran it against eight classes in the scratch project; every wrong one
failed `compileDebugJavaWithJavac` on line 10 of this file with a one-line
message naming the class:

| Class | javac |
|---|---|
| a correct subclass | compiles |
| name not in any source root | `cannot find symbol ... class DoesNotExist, location: package org.example.spike` |
| package does not exist | `package org.nowhere does not exist` |
| `extends android.app.Activity` | `incompatible types: WrongBase cannot be converted to PythonActivity` |
| abstract | `AbstractAct is abstract; cannot be instantiated` |
| only a one-argument constructor | `constructor NoDefaultCtor in class NoDefaultCtor cannot be applied to given types` |
| private constructor | `PrivateCtor() has private access in PrivateCtor` |
| package-private class | `NotPublic is not public in org.example.spike; cannot be accessed from outside package` |

It replaces the first draft's source-file scan, which could prove only that a
file existed at `<package>/<Simple>.java`, not that it declared that class,
and had nothing for Kotlin. A Kotlin subclass is covered the same way:
AGP compiles Kotlin before Java in a mixed module and javac sees the Kotlin
classes, so `new MainActivity()` resolves. (Standard Kotlin Gradle behaviour;
listed under verification, not spiked.)

What the user sees: Gradle output is streamed, not parsed
(`gradlew.py run_gradle`), so this is `GradleFailed` — `KF-BUILD-TOOL-FAILED`,
exit 5 — with the javac line above visible in the log and the file's header
comment saying what the line means. It is not exit 1. That is acceptable: the
message names the configured class and the one property it lacks, and the fix
is always in the user's Java. The verifier class is package-private and
unreferenced; it is a few hundred bytes in a debug APK and R8 removes it from a
minified release.

**Runtime check.** The instrumented contract test resolves the package's
launcher with `getLaunchIntentForPackage` — asserting it is non-null first,
since the `PackageManager` reference returns null for a package with no
`LAUNCHER` activity — and, before launching, asserts
`PythonActivity.class.isAssignableFrom(Class.forName(launcherName))`, so
`run --smoke` says "launcher X does not extend PythonActivity" instead of
timing out after 90 s. The in-app self-test (`_kivyforge_selftest.py`) gains
an `EXPECTED_LAUNCHER` constant and asserts
`android.mActivity.getClass().getName()` equals it — the positive proof that
the configured class is the one running.

### 3.2 Every place that names the launcher, and what each does

The spike's Defect 2 is the list. Each site either follows the key, is
rewritten not to need a name, or is pinned to the base class on purpose.

| Site | Today | Change |
|---|---|---|
| `generate/manifest.py` `MAIN_ACTIVITY` | constant string | `main_activity(android) -> str` returning the configured key or the default. `android:name` stays a **managed** activity attribute (`MANAGED_ANDROID_ACTIVITY_ATTRS`): the controlling field is now `main_activity`, and the rule-15 hint names it. The rest of the `<activity>` element — `configChanges`, `screenOrientation`, theme, intent filters — is unchanged. |
| `generate/project.py` | — | emits `KivyforgeLauncherCheck.java` when the key is set (section 3.1). |
| `platforms/android/cli.py` `run` | `adb_mod.launch(device, package, "org.kivy.android.PythonActivity")` | pass `main_activity(android)`. Spike: the old command fails with `Error type 3 ... does not exist`. |
| `templates/androidtest/KivyforgeContractTest.java` | `new Intent(ctx, org.kivy.android.PythonActivity.class)` | `getLaunchIntentForPackage(ctx.getPackageName())` plus the `kivyforge_selftest` extra. No class name in the test at all, so it cannot drift again; plus the `isAssignableFrom` assertion. |
| `templates/bootstrap_py/_kivyforge_selftest.py` | `getDeclaredMethods()` on `android.config.ACTIVITY_CLASS_NAME` | **unchanged in that respect**, because `ACTIVITY_CLASS_NAME` stays the base class (next rows), on which the methods *are* declared. Had the constant followed the subclass, `getDeclaredMethods()` would have reported every inherited method missing and failed a valid subclass. Gains the `EXPECTED_LAUNCHER` assertion (section 3.1). |
| `platforms/android/policy.py` `BOOTSTRAP_EXPORTED` | set containing the base class and `ProfileInstallReceiver` | `check_release_manifest` takes `launcher: str`. The baseline is **the configured launcher plus the profile receiver** — the base class is *not* kept when a subclass is configured, because an exported `PythonActivity` alongside a custom launcher is an entry point that bypasses the custom `onCreate`. Check 3 asserts not only that exactly one `LAUNCHER` activity exists but that its name equals `launcher`. |
| `tests/artifact_checks.py` merged-manifest check | imports `MAIN_ACTIVITY` | uses `main_activity(android)`, so the T3 check asserts the configured launcher is the one with the `LAUNCHER` category. A new T3 check scans `classes*.dex` for the launcher's **descriptor** `L<package/path/Simple>;` — the form the dex string table holds, not the dotted name. |
| `templates/android_pkg/config.py` `ACTIVITY_CLASS_NAME`, `ACTIVITY_CLASS_NAMESPACE` | fixed to the base class | **unchanged, deliberately.** `ACTIVITY_CLASS_NAMESPACE` builds nested-interface names (`$NewIntentListener`, `$ActivityResultListener`, `$PermissionsCallback`, `$DarkModeListener`) that exist only under the base class's binary name; rendering it from a subclass breaks `bind()`, `request_permissions()` and `set_dark_mode_listener()` at the first proxy creation (section 2.1). `ACTIVITY_CLASS_NAME` stays with it for consistency: every use in the bundled package is `autoclass(...).mActivity`, which returns the subclass instance either way (spike, section 4). The template gets a comment saying both stay on the base and why. |
| `templates/bootstrap_py/_kivy_bootstrap.py` `_ACTIVITY_CLASS` | base class | **unchanged.** Reads the inherited static; the spike shows `get_activity()` returns the subclass instance. One sentence in its docstring saying so. |
| `smoke.py`, `adb.py` | no class name | unchanged. |

R8 needs nothing: a class named in the manifest is a root AGP keeps. Statics
on the subclass reached only from pyjnius are the app's business under
`[tool.kivy.android.proguard]`, which is still "specified, not implemented";
the existing advice (leave `minify` off) stands.

### 3.3 Prerequisite: `[tool.kivy.android.src]` has never compiled anything

The spike's Defect 1. `generate/project.py` writes

```
java.srcDirs += 'android/java'
```

into `app/build.gradle`, and Gradle resolves that against the module directory
`<slug>-android/app/`, where no such path exists; a missing `srcDir` is silently
empty. The only test pins the literal, no example uses the key, and
`test-matrix.md` §7 has no run of it. The docs describe it as working.

Two fixes are possible:

- **(a) Write the path relative to the module.** `write_app_build_gradle`
  gains `project_root` (its sibling `write_resources` already has it) and
  emits `java.srcDirs += ` + `_groovy_str(relpath)` where `relpath` is
  `os.path.relpath(project_root / p, dest / "app")` with `dest` the actual
  generated project directory (`project_dir_for(project_root, config)`),
  posix-spelled — `'../../android/java'` for the default layout. `_groovy_str`
  rather than a hand-quoted f-string, so a path with a quote or backslash
  survives. The generated project then compiles the user's tree in place, so an
  edit-and-`gradlew` loop sees changes without restaging. Both paths are under
  the project root, so `relpath` cannot cross drives.
- **(b) Copy the roots into `app/src/main/java/` at stage time**, with the
  delete-previous bookkeeping `include_files` already has, and pin each
  file's SHA-256 in the lock as `include_files` and `proguard.rules_files` do.
  Self-contained project; more machinery; and the user's sources would then
  be lock inputs, which `src` is not today.

**Decided 2026-10-24: (a), with two guardrails.** The failure mode this bug
had — a green build with the classes missing — is why neither guardrail is
optional. Gradle treats a missing `srcDir` as empty by design, so a typo in a
root, or a root that was renamed, reproduces the original defect exactly even
after the path is right.

1. **The loader validates every configured root exists and is a directory.**
   `_parse_android_src` already receives the project root (through
   `_parse_android`) and already rejects a root that is absolute or escapes
   the project; it gains: `<project_root>/<p>` must exist and be a directory,
   failing as `ConfigError` with the line and a hint ("the path is relative
   to the project root; Gradle would compile nothing from a missing one").
   Rule 21 is the precedent — a splash image path is checked for existence at
   load time for the same reason. `load_config_from_text` with no
   `project_root` (the hermetic tests' path) skips the existence check, as
   the other path checks do.
2. **A T3 fixture with known marker classes, checked by dex descriptor.**
   `tests/artifact_checks.py` gains a check that, for a project whose
   `[tool.kivy.android.src]` declares the fixture roots, `classes*.dex`
   contains `Lorg/kivyforge/t3/JavaMarker;` and `Lorg/kivyforge/t3/KotlinMarker;`
   — one Java and one Kotlin class the fixture ships for this purpose, so the
   Kotlin plugin path is proved too. The check does **not** try to enumerate
   the classes a user's source tree declares: parsing Java or Kotlin text for
   class names is brittle and is not what the check is for. The fixture's
   markers prove the srcDirs wiring; the compile-time verifier (section 3.1)
   proves the one user class that matters.

The hermetic test's pinned literal changes to the relative form through
`_groovy_str`. android/04 gets one sentence saying the generated project
reaches outside its own directory for `src` roots, as it already does for the
staged runtime via `PYTHON_PREFIX_DIR`. Land it as its own PR with its own
CHANGELOG line before the key (decision 3), so a user who only wants
`src.java` gets it fixed independently.

### 3.4 What the user is promised

For the guide, and so the implementation has a target:

- The class extends `org.kivy.android.PythonActivity`, in Java or Kotlin,
  is public and concrete, has a public no-argument constructor, and is not in
  a bootstrap namespace. Put it in a `[tool.kivy.android.src]` root; the
  build fails at `compileDebugJavaWithJavac` on `KivyforgeLauncherCheck.java`
  if any of that is untrue, naming the class.
- **Before `super.onCreate()`**: nothing of kivyforge's exists yet —
  `mActivity` is `null`, the bundle is not unpacked, SDL and libpython are not
  loaded. **After `super.onCreate()` returns**: `mActivity` is your instance,
  the native libraries are loaded, and Python has not started; it starts on
  SDL's thread after the surface is created, about 0.8 s later in the spike.
  Anything you do after `super.onCreate()` is therefore guaranteed to precede
  the first line of your Python.
- Call `super` in every override, and know which ones Android will not
  remind you about. The `Activity` reference marks nine methods "derived
  classes must call through to the super class's implementation" — `onCreate`,
  `onStart`, `onRestart`, `onResume`, `onPause`, `onStop`, `onDestroy`,
  `onPostCreate`, `onPostResume` — and the system throws
  `SuperNotCalledException` if you forget. It says nothing of the kind for
  `onNewIntent`, `onActivityResult` and `onRequestPermissionsResult`, which
  are exactly the three whose `super` dispatches to the p4a registries: forget
  one of those and Python's `bind()` and `request_permissions()` callbacks
  silently never fire. The spike shows the permission result reaching the
  subclass override, then `PythonActivity`, then the Python callback, in that
  order.
- From Java you may use the p4a registries `PythonActivity` already exposes:
  `registerActivityResultListener`, `registerNewIntentListener`. Two are
  single slots consumed by the bundled Python modules —
  `addPermissionsCallback` (by `android.permissions`) and
  `setDarkModeListener` (by `android.darkmode`) — so taking them from Java
  breaks those modules; override the method and call `super` instead.
- `autoclass("org.kivy.android.PythonActivity").mActivity`,
  `autoclass("<your class>").mActivity`, `_kivy_bootstrap.get_activity()` and
  `android.mActivity` all return your instance.
  `android.config.ACTIVITY_CLASS_NAME` stays `org.kivy.android.PythonActivity`;
  to reach a static you added, `autoclass` your class by its own name.
- `kivyforge run`, `kivyforge run --smoke` and `kivyforge package`'s release
  policy follow the key; nothing else to declare. With a subclass configured,
  an exported `PythonActivity` in the merged manifest is a policy failure
  like any other stray export.
- It is one class. Several SDKs that each want `onCreate` are composed by you
  inside it, in the order you choose. Library code that must not depend on your
  subclass has Android's own route — a `ContentProvider` registering
  `Application.ActivityLifecycleCallbacks` and doing nothing else in
  `onCreate` — which works in a kivyforge app today with no key at all
  (section 2.3), and the guide shows it next to the subclass. The App Startup
  form of the same route (`androidx.startup:startup-runtime:1.2.0` in
  `gradle.dependencies`, an `Initializer`, and the documented `<provider
  ... tools:node="merge">` entry) is shown too once decision 5 settles how a
  `tools:` attribute reaches the manifest.

### 3.5 Diagnostics, docs, changelog

- No new `KF-*` code. Loader failures use the existing `ConfigError` path
  (exit 1); the verifier fails the Gradle step (exit 5) with the javac line in
  the log. The first draft's `KF-ANDROID-ACTIVITY-CLASS-MISSING` is withdrawn:
  the compile check subsumes it and classifying one javac error specially
  would mean parsing Gradle output, which nothing else does.
- `kivyforge init`'s buildozer table (`cli/init.py`): split the current entry.
  `android.entrypoint` maps to `tool.kivy.android.main_activity` (same
  meaning: the launcher class). `android.activity_class_name` stays in the
  dropped list with a new explanation — kivyforge's bundled `android` package
  reaches your subclass through `PythonActivity.mActivity`, so its config
  stays on the base and there is nothing to set; if your spec sets it to a
  different class from `android.entrypoint`, the launcher is what
  `android.entrypoint` named. (`init` prints the table; it does not rewrite
  configuration, so "reconcile" is a sentence, not code.)
- android/01: the field, rule 22, the managed-keys row for the main
  `<activity android:name>` (source becomes `main_activity`).
  android/04: the tree listing (line 41, the launcher may be the app's class;
  `KivyforgeLauncherCheck.java`), the "main `<activity>` is the generated
  `PythonActivity`" sentence (line 265), the namespace-preservation paragraph
  (line 59, `android.config` stays on the base), the escape-hatch list (line
  378). android/05 §namespace preservation: a paragraph on the subclass and
  why `ACTIVITY_CLASS_NAMESPACE` cannot follow it. android/06: the policy
  baseline wording (lines 162, 361: "the configured launcher" not
  "`PythonActivity`"), the `am start -n` line (192), the smoke "Launch" step
  (206) and the new launcher assertions. The reference page
  `docs/guides/reference/pyproject/android.md`; a guide section "Run Java when
  the activity is created" (in `java-libraries.md`, or its own page) showing
  the subclass and the provider side by side; `migrate.md`'s key table.
- `CHANGELOG.md` `[Unreleased]`: one entry for the `src.java` fix (bug; no
  migration), one for `main_activity` (feature).

### 3.6 Verification

- Hermetic: loader rule 22 (each rejection, and the explicit default
  normalising to unset); manifest emission with and without the key;
  `KivyforgeLauncherCheck.java` emitted with the configured class and pruned
  without it; `android.config` rendering unchanged; `check_release_manifest`
  with `launcher` set (base class exported -> FAIL; launcher name mismatch ->
  FAIL); `run` launches the configured class; the androidTest template
  contains no `PythonActivity.class`; the srcDirs relative path through
  `_groovy_str`.
- T3 (`tests/artifact_checks.py`): merged manifest's `LAUNCHER` activity is
  the configured class; the dex contains its descriptor; the `src.java`
  classes' descriptors are present even when `main_activity` is unset; the
  verifier's negative cases as a Gradle-compile matrix (the second spike's
  script, made a test) on a kivyforge-generated project, including one Kotlin
  subclass.
- T4: `run --smoke` on the gate example below, both generations, on the
  `x86_64` emulator; then the Pixel 8a. A `hardware-checklist.toml` item
  (`android-activity-class`) so the device pass is recorded in `test-matrix.md`
  §7 by `scripts/hardware_pass.py record`.
- **A persistent on-device gate example, `examples/mobile/android-activity-class`,
  is part of the feature, not optional.** `run --smoke` imports the bundled
  modules but never instantiates a listener proxy, and proxy creation is
  exactly where a wrong `ACTIVITY_CLASS_NAMESPACE` would fail — so the smoke
  cannot catch a regression of section 3.2's most important row. The example's
  `main.py` therefore calls `android.activity.bind(on_new_intent=...)` and
  `unbind`, `android.permissions.request_permissions`, and
  `android.darkmode.set_dark_mode_listener`, and reports each; its Java is a
  subclass that logs in `onCreate` and a provider registering lifecycle
  callbacks. Its lock is tracked like the other on-device gate examples, so
  `examples/verify-android.ps1` keeps the path exercised.

## 4. Deliberately out of scope

- **A kivyforge hook interface** (#85 option 2). Section 2.5. Revisit only
  if the native-integration contract adopts startup hooks; its stated shape is
  a static dispatcher generated by the consumer, which this key does not
  preclude and the reserved `<application android:name>` keeps room for.
- **`application_class`.** The slot stays reserved. The spike shows the
  application class is `android.app.Application` today; a generated
  `PythonApplication` may arrive as that dispatcher, independently.
- **`service_class`** (buildozer's `android.service_class_name`). Services are
  generated per `[[tool.kivy.android.services]]` entry; nobody has asked.
- **An iOS `app_delegate_class`.** Section 2.4 records the shape so the two
  keys would be siblings; nobody has asked.
- **Making the bootstrap a `ComponentActivity`.** Tracked by its own spike;
  doing this key first costs nothing toward it, and an SDK that needs
  `registerForActivityResult` needs both.
- **Parsing Gradle output to reclassify the verifier's javac error as exit 1.**
  Nothing else parses it; the message is already specific.
- **`android:appComponentFactory`.** API 28's
  [`AppComponentFactory`](https://developer.android.com/reference/android/app/AppComponentFactory)
  is Android's documented hook for *instantiating* activities and could
  substitute a subclass without naming it in the manifest. Declined: it is an
  attribute of the reserved `<application>` element; AndroidX core already
  occupies it (`androidx.core.app.CoreComponentFactory`), so an app value
  needs `tools:replace`; and the reference says it "does not provide earlier
  access to the Activity object" — it cannot run code in `onCreate`, which is
  the whole request. Its `throws IllegalAccessException,
  InstantiationException` is, though, the platform's own statement of what
  the verifier checks: the launcher is instantiated by reflection through its
  public no-argument constructor.

## 5. Decisions

All closed 2026-10-24, worked through in order with the owner. Each entry
keeps the alternatives and why they lost, so the reasoning survives the
people who had it.

1. **Key name. Decided 2026-10-24: `main_activity`.** Three candidates were
   weighed. `activity_class_name` is buildozer's spelling, but in buildozer
   that key feeds p4a's `android.config` constants, which kivyforge keeps on
   the base class; a same-named key that behaves differently would mislead
   exactly the audience it is meant to help. `activity_class` (the first
   draft's name) names the type of the value, which the string already
   implies. `main_activity` names the role, in the noun Android's
   documentation uses for the launcher, and is what the repo already calls
   it internally (`MAIN_ACTIVITY`, `main_activity()`), beside the sibling
   list `[[activities]]`. Mapped from buildozer's `android.entrypoint` by
   `init`.
2. **`src.java` fix. Decided 2026-10-24: (a), relative srcDir, with two
   guardrails** — the loader checks every root exists and is a directory,
   and a T3 fixture with one Java and one Kotlin marker class is checked by
   dex descriptor (no enumeration of classes from source text). (b), a
   stage-time copy with lock pins, was declined: it would make the user's
   Java a lock input, which `src` has never been and `main.py` is not, and
   it slows the edit-and-`gradlew` loop. Section 3.3.
3. **Sequencing. Decided 2026-10-24: two PRs, the `src.java` fix first.**
   It is a defect on its own, documented as working today, so a user who
   only wants a helper class compiled gets it without waiting on a feature
   review; its CHANGELOG entry is a bug entry with no migration, the key's a
   feature entry; and the key's tests can then assume working `src` plumbing
   rather than carry a workaround. The fix PR is also the first real build
   of the Kotlin plugin path (decision 2's `KotlinMarker`), which is a
   reason to take it alone. Order: #182 (`xmlns:tools`) and the `src.java`
   fix, independent of each other; then the `main_activity` key, which
   depends on both.
4. **Gate example. Decided 2026-10-24: a persistent on-device example**,
   `examples/mobile/android-activity-class`, with its lock tracked like the
   four existing on-device gate examples, a `hardware-checklist.toml` item,
   and a line in `examples/verify-android.ps1`. A scratch-project T4 run was
   declined because nothing re-runs it: `run --smoke` never instantiates a
   listener proxy, so the invariant that `ACTIVITY_CLASS_NAMESPACE` stays on
   the base class (section 3.2) would be guarded by a comment alone. The
   example's `main.py` exercises `android.activity.bind`/`unbind`,
   `android.permissions.request_permissions` and
   `android.darkmode.set_dark_mode_listener`; its Java is the subclass and
   the provider side by side, which is also the guide's worked example. The
   Pixel 8a pass is recorded through `scripts/hardware_pass.py` before the
   feature counts as done; if the device is unavailable in the window, the
   key may merge on the emulator pass with the device row left
   known-unverified in `test-matrix.md` §7, stated up front.
5. **How a `tools:` attribute reaches the generated manifest**, so the App
   Startup entry Android documents (section 2.3) can be written. Wider than
   this key, and the repo has a position: the generated `<manifest>` declares
   only `xmlns:android`, and `tests/test_artifact_checks.py` pins that a
   `tools:`-prefixed passthrough attribute fails well-formedness at
   generation, "which is the right place". **Decided 2026-10-24: (b)**,
   implemented on its own branch (`manifest-tools-namespace`) ahead of this
   key. The two answers that were weighed:

   - **(a) Document the inline declaration.** A fragment writes
     `<provider xmlns:tools="http://schemas.android.com/tools" tools:node="merge" ...>`.
     Valid XML; `ET.fromstring` accepts it; the manifest merger matches the
     `tools` namespace by URI, so prefix placement is irrelevant. No code
     change and the existing position stands, at the cost of an attribute no
     Android page shows and a "not well-formed" error for anyone who pastes
     the documented snippet unchanged.
   - **(b) Declare `xmlns:tools` on the generated root** (recommended), one
     attribute on line 188 of `manifest.py`, shipped as its own small PR
     before the guide text that needs it. Documented snippets paste verbatim;
     every merger directive — `tools:node="merge|remove|replace"`,
     `tools:replace`, `tools:overrideLibrary` — becomes available in
     `extra_*_xml`, which is the standard remedy when a library's manifest
     contributes something the app does not want. Today
     `[tool.kivy.android.manifest].allow_exported` is the *only* remedy for an
     unwanted exported library component ("a library's component cannot be
     edited out of pyproject.toml", `policy.py`); with `tools:node="remove"`
     it can be, which is the safer posture. The declaration itself changes
     nothing in the APK: the merger consumes `tools:` attributes and emits
     none. To keep the existing position where it was actually aimed — the
     attribute passthrough dicts `manifest.application` and
     `manifest.activity` — a loader rule rejects any non-`android:` key there
     with an explicit message, so a `tools:replace` passthrough still fails
     at the same place, now with a reason instead of an XML parse error. The
     pinned test flips from "not well-formed" to that rule; the merged-manifest
     T3 check (`artifact_checks.py`, `tools:` "never reaches here") is
     unchanged because the merger has already removed them.

   Whether `tools:node="merge"` is strictly required for the App Startup
   entry is beside the point: the merger does merge same-key `<provider>`
   elements by default, so the entry may well work without it, but the page
   says to include it and `tools:node="remove"` has no substitute at all.
