---
title: Declare permissions on Android and iOS
sources:
  - docs/design/platforms/android/01-pyproject-android.md
  - kivyforge/config/loader.py
  - kivyforge/platforms/android/generate/manifest.py
  - kivyforge/platforms/ios/plist.py
---

# Declare permissions on Android and iOS

An app that uses the camera, the microphone, location, Bluetooth, or the photo
library must declare it on each platform. The two platforms declare it
differently:

- **Android** lists permissions in the app manifest. You write them in
  `[tool.kivy.android.permissions].uses`.
- **iOS** needs a *usage description* in `Info.plist`: the sentence iOS shows
  when it asks the user for access. You write it in `[tool.kivy.ios.info_plist]`.

kivyforge has no shared permissions table, because the names, version rules and
flags differ between the platforms. This page lists what to write in each
overlay for the common capabilities.

## Before you begin

- A configured [Android](../android/configure.md) or [iOS](../ios/configure.md)
  app.

## Common capabilities

| Capability | Android `uses` entries | iOS `info_plist` keys |
|---|---|---|
| Camera | `"CAMERA"` | `NSCameraUsageDescription` |
| Microphone | `"RECORD_AUDIO"` | `NSMicrophoneUsageDescription` |
| Approximate location | `"ACCESS_COARSE_LOCATION"` | `NSLocationWhenInUseUsageDescription`, and `NSLocationDefaultAccuracyReduced = true` |
| Precise location | `"ACCESS_FINE_LOCATION"` and `"ACCESS_COARSE_LOCATION"` | `NSLocationWhenInUseUsageDescription` |
| Location in the background | Add `"ACCESS_BACKGROUND_LOCATION"` to one of the location rows above | `NSLocationWhenInUseUsageDescription`, `NSLocationAlwaysAndWhenInUseUsageDescription`, and `UIBackgroundModes = ["location"]` |
| Bluetooth | See [Bluetooth](#bluetooth) | `NSBluetoothAlwaysUsageDescription` |
| Contacts | `"READ_CONTACTS"` | `NSContactsUsageDescription` |
| Notifications | `"POST_NOTIFICATIONS"` | Nothing to declare |
| Internet | `"INTERNET"` | Nothing to declare |

For photos, see [Photos](#photos): which entries you need depends on whether
your app picks, reads, or saves photos.

An app that uses the camera and precise location declares:

```toml
[tool.kivy.android.permissions]
uses = ["CAMERA", "ACCESS_FINE_LOCATION", "ACCESS_COARSE_LOCATION"]

[tool.kivy.ios.info_plist]
NSCameraUsageDescription = "Scan the QR code on your ticket."
NSLocationWhenInUseUsageDescription = "Show your position on the map."
```

Write each iOS description as the reason your app needs access, not as a
description of the permission. App Review rejects vague descriptions, and an
app that uses a protected API without its description key is stopped by iOS
when it calls the API. Android shows its own fixed text and has no
description to set.

## Location

On Android 12 and later, an app that asks for precise location must also ask for
approximate location, because the user can choose to grant only approximate
location. Declare both.

iOS has one location usage description for both accuracies.
`NSLocationDefaultAccuracyReduced = true` makes approximate location the
default.

Location in the background needs extra review on both platforms:

- On Android, `ACCESS_BACKGROUND_LOCATION` does nothing without one of the
  foreground location permissions. Your app must request it separately, after
  the foreground permission is granted. Google Play also requires a declaration
  explaining why your app needs it.
- On iOS, `UIBackgroundModes = ["location"]` is needed only for continuous
  location updates while the app is in the background. Region monitoring and
  significant-change updates work without it.

## Bluetooth

Android 12 (API 31) replaced the old Bluetooth permissions with new ones. An app
that supports earlier versions declares the old ones with `max_sdk_version`, so
they are requested only on the versions that use them:

```toml
[tool.kivy.android.permissions]
uses = [
    { name = "BLUETOOTH", max_sdk_version = 30 },
    { name = "BLUETOOTH_ADMIN", max_sdk_version = 30 },
    { name = "ACCESS_FINE_LOCATION", max_sdk_version = 30 },
    "BLUETOOTH_CONNECT",
    { name = "BLUETOOTH_SCAN", uses_permission_flags = "neverForLocation" },
]

[tool.kivy.ios.info_plist]
NSBluetoothAlwaysUsageDescription = "Connect to your heart-rate monitor."
```

- `neverForLocation` tells Android 12 and later that your app never uses
  Bluetooth scans to find the user's location, so scanning works without a
  location permission. If your app does derive location from scans, leave the
  flag out and declare location permissions without a cap.
- Android 11 and earlier need location permission for any Bluetooth scan, which
  is what the capped `ACCESS_FINE_LOCATION` entry is for.
- Leave out `BLUETOOTH_SCAN` and the location entry if your app only connects to
  devices that are already paired. Add `"BLUETOOTH_ADVERTISE"` if your app makes
  the device discoverable to others.

`uses_permission_flags` needs `compile_sdk` 31 or higher. kivyforge rejects a
`max_sdk_version` below `min_sdk`, because no device the app installs on would
receive that permission.

## Photos

| What your app does | Android `uses` entries | iOS `info_plist` keys |
|---|---|---|
| Lets the user pick photos with the system picker | Nothing to declare | Nothing to declare |
| Saves photos to the library | `{ name = "WRITE_EXTERNAL_STORAGE", max_sdk_version = 28 }` | `NSPhotoLibraryAddUsageDescription` |
| Reads the whole library | `"READ_MEDIA_IMAGES"`, `"READ_MEDIA_VISUAL_USER_SELECTED"`, and `{ name = "READ_EXTERNAL_STORAGE", max_sdk_version = 32 }` | `NSPhotoLibraryUsageDescription` |

Prefer the system picker when you can. On Android, Google Play allows
`READ_MEDIA_IMAGES` only for apps whose core purpose needs broad photo access.
`READ_MEDIA_VISUAL_USER_SELECTED` lets Android 14 and later users grant access
to only some photos. Add `"READ_MEDIA_VIDEO"` if your app also reads videos.

## Ask at run time

A declaration only makes a permission available to ask for. Your app still has
to ask for the permissions Android calls *dangerous*, such as the camera,
microphone, location, contacts and the Bluetooth permissions, while it runs:

- On Android, use `request_permissions` from the bundled `android` package. See
  [Use the android package](../android/android-package.md).
- On iOS, the system asks the first time your app uses the protected API.

## Verify

Build the app and check the generated declarations:

=== "Android"
    ```bash
    kivyforge build -p android --debug
    ```

    Open `<app>-android/app/src/main/AndroidManifest.xml`, where `<app>` is your
    `[project].name`, and check the `<uses-permission>` elements, including
    their `android:maxSdkVersion` and `android:usesPermissionFlags` attributes.

=== "iOS"
    ```bash
    kivyforge build -p ios --simulator
    ```

    Open `<app>-ios/<app>-Info.plist` and check the usage description keys.

Then run the app and use each capability once, to confirm that the system asks
for access.

## What's next

- [Configure your Android app](../android/configure.md) or
  [configure your iOS app](../ios/configure.md)
- [`[tool.kivy.android]` reference](../../reference/pyproject/android.md) and
  [`[tool.kivy.ios]` reference](../../reference/pyproject/ios.md)
