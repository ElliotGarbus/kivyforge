# iOS lifecycle hook — app-delegate code for a kivyforge iOS app

Some iOS features need code in the app delegate, and some need it before your
Python code starts: the push device token, background pushes, a
notification-center delegate, background-task registration, and the URL or
notification tap that launched the app. In a kivyforge app the delegate belongs
to SDL3, so there is no `AppDelegate` file to edit.

This example ships a small local package, `lifecycle-hook/`, whose Objective-C
`+load` runs before Python. It adds the missing delegate methods to SDL's
delegate class, queues what they receive, and `src/lifecycle.py` turns the
queue into Kivy events. No kivyforge change is involved: the package is
declared like any other Swift package.

The user guide, [Run code in the iOS app lifecycle](../../../docs/guides/guides/ios/lifecycle-hooks.md),
explains how to adapt it.

## What's here

| Path | Purpose |
|------|---------|
| `pyproject.toml` | App config: the hook package, plus the `Info.plist` keys and entitlement it needs |
| `lifecycle-hook/Package.swift` | Local package, one Objective-C target, a dynamic product |
| `lifecycle-hook/Sources/LifecycleHook/LifecycleHook.m` | `+load`, the delegate methods it installs, and the event queue |
| `lifecycle-hook/Sources/LifecycleHook/include/LifecycleHook.h` | The class methods Python calls |
| `src/lifecycle.py` | `Lifecycle`, a Kivy `EventDispatcher`; copy it into your app |
| `src/main.py` | Demo UI that logs every event |

## Prerequisites

- macOS with Xcode, and kivyforge installed from this repo
  (`pip install -e ".[dev]"`).
- Network access to `elliotgarbus.github.io` the first time you lock: Kivy and
  pyobjus iOS wheels come from the
  [`kivy-mobile-wheels`](https://github.com/ElliotGarbus/kivy-mobile-wheels)
  index.
- For push on a device: a paid Apple Developer team, so automatic signing can
  add the Push Notifications capability.

## Lock, build, run

```bash
cd examples/mobile/ios-lifecycle-hook
kivyforge lock -p ios
kivyforge build -p ios --simulator
kivyforge run -p ios --simulator
```

For a phone, set `[tool.kivy.ios.signing].team_id` (or pass `--team-id`) and
use `--device`.

## Try it

| Do this | You see |
|---------|---------|
| Quit the app, then `xcrun simctl openurl booted kflifecycle://hello` | `on_url("kflifecycle://hello", true)`: the URL that launched the app, which Kivy's `on_drop_file` never receives |
| Open the same URL with the app running | `on_url(..., false)` |
| Tap **Register for push**, then Allow | `on_push_permission(true)`, then `on_push_token("...")` |
| Tap **Test notification** and stay in the app | `on_notification({"source": "test"})` after 5 s, and a banner |
| Tap **Test notification**, press Home, tap the notification | `on_notification_response({"source": "test"}, "com.apple.UNNotificationDefaultActionIdentifier")` |
| Tap **Refresh task** on a device | `submitted`; when iOS runs the task, `on_background_task(...)` the next time the app is in front |

On the Simulator, **Refresh task** reports that `BGTaskScheduler` is not
available: submitting a background task needs a device. A background push
also needs a device, and a push server or Apple's
[Push Notifications Console](https://icloud.developer.apple.com/dashboard/notifications),
sent to the token the app shows.

## What was verified

On an iOS 27 Simulator: every row above except the notification tap and
**Refresh task**. On an iPhone, with the spike this example was built from:
the device token, a background push from Apple's console, BGTask launches,
URLs, and a cold launch from a notification tap.

## Limits

- The hook finds SDL's delegate by its class name, `SDLUIKitSceneDelegate`. If
  a future SDL renames it, the status line says so and nothing is installed.
- Kivy's clock stops while the app is in the background, so events received
  then reach Python only when the app is next in front. Work that must happen
  in the background (finishing a BGTask, acting on a background push) belongs
  in the native handlers in `LifecycleHook.m`.
- The hook sets the app's `UNUserNotificationCenter` delegate. Another library
  that sets it too replaces this one; only one delegate can be active.
- `aps-environment = "development"` suits Debug builds. An App Store or
  TestFlight build needs `"production"`.
