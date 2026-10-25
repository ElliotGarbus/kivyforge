---
title: Add Java libraries to your Android app
sources:
  - docs/design/platforms/android/01-pyproject-android.md
  - docs/design/platforms/android/02-pylock-android-spec.md
  - docs/design/platforms/android/03-artifact-distribution-android.md
  - docs/design/platforms/android/04-gradle-project-generation.md
  - docs/design/dev/test-matrix.md
  - kivyforge/config/loader.py
  - kivyforge/platforms/android/generate/project.py
  - kivyforge/platforms/android/generate/launcher.py
  - docs/design/dev/android-activity-class-proposal.md
  - docs/design/dev/android-androidx-subclass-spike-findings.md
  - examples/mobile/qr-maven/pyproject.toml
  - examples/mobile/android-activity-class/pyproject.toml
---

# Add Java libraries to your Android app

You can add Java or Kotlin code to your app in three ways: a Maven dependency, a
local or downloadable archive (`.aar` or `.jar`), or your own source files.
kivyforge adds them to the generated Gradle project, and you call them from
Python with [pyjnius](pyjnius.md).

Maven dependencies can also take their versions from a BOM, and some libraries
need a Gradle plugin too. Firebase needs both; see [Add Firebase](#add-firebase).

## Before you begin

- [Configure your Android app](configure.md).
- For Maven dependencies, have a JDK on the computer that runs
  `kivyforge lock`. Locking runs Gradle once to resolve the dependency graph.

## Add a Maven dependency

1. Declare the coordinate under `[tool.kivy.android.gradle]`. This example,
   from the `qr-maven` example project, adds ZXing, a QR code library:

    ```toml
    [tool.kivy.android.gradle]
    dependencies = [
        "com.google.zxing:core:3.5.3",
    ]
    ```

    Each coordinate must be a full `group:artifact:version`. Dynamic versions
    such as `3.+` are rejected. To resolve from a repository other than Google's
    Maven repository and Maven Central, list its URL in `repositories`.

2. Lock:

    ```bash
    kivyforge lock -p android
    ```

    kivyforge resolves the full dependency graph and records each artifact with
    its SHA-256 hash in `pylock.android.toml`.

## Use a BOM

A BOM (bill of materials) is a published list of library versions that are
tested together. Firebase, Jetpack Compose, and OkHttp publish one. List the BOM
under `platforms`, then leave the version off each library it covers:

```toml
[tool.kivy.android.gradle]
platforms = ["com.google.firebase:firebase-bom:34.15.0"]
dependencies = [
    "com.google.firebase:firebase-analytics",
    "com.google.firebase:firebase-messaging",
]
```

The BOM itself needs an exact version. A `dependencies` entry without a version
is rejected unless a BOM is listed. You can still give a library an explicit
version alongside a BOM; Gradle then uses the higher of that version and the
BOM's. `kivyforge lock` records the version Gradle chose for each library, and
the BOM file itself, with their SHA-256 hashes.

## Add a Gradle plugin

Some libraries need a Gradle plugin as well as a dependency. List each plugin
under `[tool.kivy.android.gradle.plugins]` with an exact version:

```toml
[tool.kivy.android.gradle.plugins]
"com.google.gms.google-services" = "4.4.2"
```

Quote each plugin ID. TOML splits a bare key on its dots, and kivyforge rejects
the result. kivyforge applies the plugins after the Android plugin, in the order
you list them.

!!! warning
    A plugin runs code during your build. kivyforge pins its version, but the
    lock does not record a hash for it, just as for the Android Gradle plugin
    itself. Add plugins only from sources you trust.

## Add Firebase

Firebase needs three things: the Firebase BOM, the Google Services plugin, and
your Firebase project's `google-services.json` file. The plugin reads that file
during the build and turns it into resources Firebase reads when it starts.

1. In the Firebase console, add an Android app whose package name matches
   `[tool.kivy.android].package`, and download its `google-services.json`. Save
   it in your project, for example as `config/google-services.json`.

2. Declare the BOM, the libraries you use, the plugin, and the file:

    ```toml
    [tool.kivy.android.gradle]
    platforms = ["com.google.firebase:firebase-bom:34.15.0"]
    dependencies = ["com.google.firebase:firebase-analytics"]

    [tool.kivy.android.gradle.plugins]
    "com.google.gms.google-services" = "4.4.2"

    [[tool.kivy.android.include_files]]
    dest = "app"
    sources = ["config/google-services.json"]
    ```

    `dest = "app"` puts the file in the `app/` folder of the generated project,
    where the plugin looks for it.

3. Lock and build:

    ```bash
    kivyforge lock -p android
    kivyforge build -p android --debug --abi x86_64
    ```

Firebase starts itself when your app launches. To confirm, run the app and look
for `FirebaseApp initialization successful` in `adb logcat`. Call Firebase APIs
from Python with [pyjnius](pyjnius.md).

Some Firebase products need more:

- **Crashlytics** needs its own plugin as well. List it after Google Services,
  because kivyforge applies plugins in the order you list them:
  `"com.google.firebase.crashlytics" = "VERSION"`.
- **Cloud Messaging** delivers push messages to a subclass of
  `FirebaseMessagingService`, which you write in Java or Kotlin. Add it with
  [your own source files](#add-your-own-java-or-kotlin-source) and declare the
  service with `extra_application_xml` in
  [`[tool.kivy.android.manifest]`](../../reference/pyproject/android.md).

`google-services.json` changes are lock drift like any other `include_files`
source: after you replace the file, run `kivyforge lock -p android` again.

## Add an .aar or .jar archive

1. Declare each archive by name under `[tool.kivy.android.native.aars]` or
   `[tool.kivy.android.native.jars]`, with its version and source:

    ```toml
    [tool.kivy.android.native.aars]
    LocalWidget = { version = "0.2.0", source = "libs/LocalWidget-0.2.0.aar" }

    [tool.kivy.android.native.jars]
    legacyutil = { version = "1.4.0", source = "libs/legacyutil-1.4.0.jar" }
    ```

    `source` is a download URL or a path relative to your project. An `.aar`
    can carry resources and manifest entries; a `.jar` contains only compiled
    classes.

2. Lock, so kivyforge records each archive's SHA-256 hash:

    ```bash
    kivyforge lock -p android
    ```

## Add your own Java or Kotlin source

List your source directories under `[tool.kivy.android.src]`, relative to
the project root:

```toml
[tool.kivy.android.src]
java = ["android/java"]
```

Lay the files out by package, as `javac` expects: a class
`org.example.myapp.Bridge` lives at `android/java/org/example/myapp/Bridge.java`.
A non-empty `kotlin` list also works, and enables the Kotlin Gradle plugin.

Each directory must exist; a missing one fails the configuration check rather
than building an app without your classes.

## Run Java when the activity is created

Some SDKs must be set up in the activity's `onCreate`, before your Python code
runs. Android gives two ways to do that, and kivyforge supports both. The
`android-activity-class` example project uses both.

**If the code is yours, subclass the activity.** Write a public subclass of
`org.kivy.android.PythonActivity` in your app's package, and make it the
launcher with `main_activity`:

```java
// android/java/org/example/myapp/MainActivity.java
package org.example.myapp;

import android.os.Bundle;
import org.kivy.android.PythonActivity;

public class MainActivity extends PythonActivity {
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        // The activity exists; Python is starting on its own thread.
    }
}
```

```toml
[tool.kivy.android]
main_activity = "org.example.myapp.MainActivity"

[tool.kivy.android.src]
java = ["android/java"]
```

Call `super.onCreate()`: it starts SDL and Python. A Kotlin subclass works the
same way, from a `kotlin` source root. The class must not be in
`org.kivy.android` or another package kivyforge generates.

kivyforge checks the class when it builds. If the class is missing, abstract,
not a `PythonActivity`, or has no public constructor without arguments, the
build fails with `javac`'s error, which names the class and the problem.

Python sees your subclass where it always sees the activity:
`android.mActivity` and
`autoclass("org.kivy.android.PythonActivity").mActivity` both return the running
`MainActivity`. The bundled `android` package works unchanged. Don't change
your `autoclass` calls to the subclass's name: the listener interfaces that
`android.activity.bind` and `request_permissions` use belong to
`PythonActivity`.

**If the code is a library's, use a provider.** A library that needs every
activity's lifecycle, but does not own the activity, registers
`Application.ActivityLifecycleCallbacks` from a `ContentProvider`. Android
creates providers before the first activity, so the callbacks see the
launcher's `onCreate`. No `main_activity` is needed, and two libraries do not
compete for it. Declare the provider with `extra_application_xml`:

```toml
[tool.kivy.android.manifest]
extra_application_xml = """
<provider android:name="org.example.mylib.LifecycleProvider"
          android:authorities="${applicationId}.mylib-lifecycle"
          android:exported="false" />
"""
```

In the provider's `onCreate`, register the callbacks and return. Android runs
it on the main thread at launch, so it must not do slow work.

**App Startup is the same route, the AndroidX way.** AndroidX's App Startup
library runs `Initializer` classes from one shared provider before the first
activity. Every kivyforge app contains it, but only at run time, so declare it
to compile against it. The manifest entry is the one Android's App Startup
documentation shows, unchanged:

```toml
[tool.kivy.android.gradle]
dependencies = ["androidx.startup:startup-runtime:1.2.0"]

[tool.kivy.android.manifest]
extra_application_xml = """
<provider android:name="androidx.startup.InitializationProvider"
          android:authorities="${applicationId}.androidx-startup"
          android:exported="false"
          tools:node="merge">
    <meta-data android:name="org.example.mylib.MyInitializer"
               android:value="androidx.startup" />
</provider>
"""
```

## What your activity subclass can use

Your subclass is a plain Android `Activity`. `PythonActivity` extends SDL's
activity, which extends `android.app.Activity`, so your subclass can't also be
an `AppCompatActivity`, a `FragmentActivity` or a `ComponentActivity`. That
holds even though every kivyforge app is built with AndroidX and Material.

AndroidX helpers that take a `Context` or an `Activity` work on it:

- `ContextCompat` and `ActivityCompat`
- `WindowCompat` and `WindowInsetsControllerCompat`
- `NotificationCompat` and `NotificationManagerCompat`
- App Startup, and `ProcessLifecycleOwner` for whether the app is in the
  foreground. Declare `androidx.lifecycle:lifecycle-process` to use it; like
  App Startup, it is in the app but not available to your code until you do.

These need the activity to be a lifecycle owner, and don't compile against
your subclass:

- `registerForActivityResult`
- `getLifecycle()` and lifecycle observers on the activity
- `ViewModelProvider(this)`
- `getOnBackPressedDispatcher()`
- SDKs that need a `FragmentActivity` or an `AppCompatActivity`, such as
  `BiometricPrompt`, or anything that shows a `DialogFragment`

The build fails with `javac`'s error, which names the type that was needed,
for example `MainActivity cannot be converted to FragmentActivity`. All of
these work in a second activity of your own; see
[Host an SDK that needs an AndroidX activity](#host-an-sdk-that-needs-an-androidx-activity).
For a plain activity result, you can also call `startActivityForResult` and
receive the result with `registerActivityResultListener` in Java, or with
`android.activity.bind(on_activity_result=...)` in Python.

**Use your own permission request codes.** `ActivityCompat.requestPermissions`
works from the subclass, and the result reaches your
`onRequestPermissionsResult` override; call `super` there so Python's requests
still get theirs. `android.permissions` numbers its requests 2, 3, 4 and so
on, and runs its callback for any result with one of those codes, so use codes
well above that, such as 1000 and up. Make one request at a time: Android
cancels a request made while another is in progress and reports it with empty
results.

## Host an SDK that needs an AndroidX activity

Some SDKs need their activity to be a `ComponentActivity`, a
`FragmentActivity` or an `AppCompatActivity`: Stripe's PaymentSheet,
`BiometricPrompt`, anything that shows a `DialogFragment` or calls
`registerForActivityResult`. Your app's main activity can't be one of those,
but a second activity of your own can. Kivy keeps running in the main
activity underneath it. Python starts the second activity and reads its
result. You don't need `main_activity` for this.

In that activity, everything from the
[list above](#what-your-activity-subclass-can-use) works:
`registerForActivityResult` (permission requests included), lifecycle
observers, `ViewModelProvider(this)` and `getOnBackPressedDispatcher()`.

This example presents Stripe's PaymentSheet and returns the outcome to Python.

1. Write the activity. Extend `ComponentActivity`, or `AppCompatActivity` if
   the SDK asks for a `FragmentActivity` or an `AppCompatActivity`:

    ```java
    // android/java/org/example/myapp/PayActivity.java
    package org.example.myapp;

    import android.content.Intent;
    import android.os.Bundle;
    import androidx.activity.ComponentActivity;
    import com.stripe.android.PaymentConfiguration;
    import com.stripe.android.paymentsheet.PaymentSheet;
    import com.stripe.android.paymentsheet.PaymentSheetResult;

    public class PayActivity extends ComponentActivity {
        private PaymentSheet paymentSheet;

        @Override
        protected void onCreate(Bundle savedInstanceState) {
            super.onCreate(savedInstanceState);
            Intent in = getIntent();
            PaymentConfiguration.init(this, in.getStringExtra("publishableKey"));
            paymentSheet = new PaymentSheet.Builder(this::onResult).build(this);
            if (savedInstanceState == null) {
                paymentSheet.presentWithPaymentIntent(
                        in.getStringExtra("clientSecret"),
                        new PaymentSheet.Configuration.Builder("My shop").build());
            }
        }

        private void onResult(PaymentSheetResult result) {
            String outcome = "failed";
            if (result instanceof PaymentSheetResult.Completed) {
                outcome = "completed";
            } else if (result instanceof PaymentSheetResult.Canceled) {
                outcome = "canceled";
            }
            setResult(RESULT_OK, new Intent().putExtra("outcome", outcome));
            finish();
        }
    }
    ```

    Create the SDK's objects and call `registerForActivityResult` in `onCreate`
    or in a field initializer. Android refuses to register them once the
    activity has started.

2. Declare the activity, its source directory and the SDK:

    ```toml
    [tool.kivy.android]
    compile_sdk = 36

    [tool.kivy.android.gradle]
    dependencies = ["com.stripe:paymentsheet:23.25.0"]

    [tool.kivy.android.src]
    java = ["android/java"]

    [tool.kivy.android.manifest]
    extra_application_xml = """
    <activity android:name="org.example.myapp.PayActivity"
              android:exported="false" />
    """
    ```

    `android:exported="false"` stops other apps from starting the activity.
    It doesn't need a theme of its own: the app's theme is a Material 3 theme,
    which `AppCompatActivity` also accepts. `ComponentActivity` itself comes
    with every kivyforge app.

    PaymentSheet needs `compile_sdk = 36`. Without it, the build fails at
    `checkDebugAarMetadata` with `requires libraries and applications that
    depend on it to compile against version 36 or later`. Other SDKs may need
    the same; the error names the version.

    Then lock:

    ```bash
    kivyforge lock -p android
    ```

3. Start the activity from Python and read its result:

    ```python
    from jnius import autoclass

    import android
    from android import activity

    Intent = autoclass("android.content.Intent")
    String = autoclass("java.lang.String")
    PAY_REQUEST = 1001


    def on_activity_result(request_code, result_code, data):
        if request_code == PAY_REQUEST and data is not None:
            print("payment:", data.getStringExtra("outcome"))


    def pay(publishable_key, client_secret):
        activity.bind(on_activity_result=on_activity_result)
        intent = Intent()
        intent.setClassName(
            android.mActivity.getPackageName(), "org.example.myapp.PayActivity"
        )
        intent.putExtra("publishableKey", String(publishable_key))
        intent.putExtra("clientSecret", String(client_secret))
        android.mActivity.startActivityForResult(intent, PAY_REQUEST)
    ```

    Two pyjnius details matter here:

    - **Wrap strings in `java.lang.String`** before `putExtra`. pyjnius passes
      a Python `str` as a `char[]`, so `getStringExtra` in Java returns null.
    - **Pass the package name to `setClassName`**, not the activity. pyjnius
      picks the two-string form, and passing `android.mActivity` raises a
      `TypeError`.

    `on_activity_result` sees every activity result your app receives, so
    check the request code. It runs on Android's UI thread, not Kivy's: use
    `Clock.schedule_once` to update widgets from it.

## Verify

Build the app:

```bash
kivyforge build -p android --debug --abi x86_64
```

A Maven coordinate or BOM that cannot be resolved, or an archive source that
cannot be read, fails `kivyforge lock`. Gradle plugins are fetched only by the
build, so a plugin ID or version that does not exist fails `kivyforge build`.

## What's next

- [Call Android APIs with pyjnius](pyjnius.md) to use the library you added.
- [Add a background service](services.md).
- [Android overlay reference](../../reference/pyproject/android.md).
