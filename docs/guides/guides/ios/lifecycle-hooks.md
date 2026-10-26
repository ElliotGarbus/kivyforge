---
title: Run code in the iOS app lifecycle
sources:
  - docs/design/dev/ios-lifecycle-hook-spike-findings.md
  - examples/mobile/ios-lifecycle-hook/lifecycle-hook/Sources/LifecycleHook/LifecycleHook.m
  - examples/mobile/ios-lifecycle-hook/src/lifecycle.py
  - examples/mobile/ios-lifecycle-hook/pyproject.toml
---

# Run code in the iOS app lifecycle

Some iOS features only work through the app delegate, or only if code runs
before launch finishes: the push device token, background pushes, a
notification-center delegate, background-task registration, and the URL or
notification tap that launched your app. A kivyforge app has no `AppDelegate`
for you to edit, because SDL3 provides the delegate, and your Python code
starts too late. This page shows you how to add a small local package whose
Objective-C `+load` runs before Python, installs the delegate methods you
need, and hands what they receive to Python as Kivy events.

## Before you begin

- [Add a Swift package](swift-packages.md) explains how local packages are
  declared. This page uses a `path` package.
- [Call iOS APIs with pyobjus](pyobjus.md): add `pyobjus` to your
  dependencies. Python reads the hook through it.
- Have the `ios-lifecycle-hook` example from the kivyforge repository at hand
  (`examples/mobile/ios-lifecycle-hook`). You copy two pieces from it.
- For push notifications on a device, you need a paid Apple Developer team.

## Add the hook to your app

1. Copy `lifecycle-hook/` from the example into your project root, and
   `src/lifecycle.py` into your app directory.

2. Declare the package:

    ```toml
    [tool.kivy.ios.native.swift_packages]
    LifecycleHook = { path = "lifecycle-hook", products = ["LifecycleHook"] }
    ```

3. Add the `Info.plist` keys and entitlement for the features you use:

    | Feature | Add |
    |---|---|
    | Push token and notifications | `aps-environment` under `[tool.kivy.ios.entitlements]`: `"development"` for Debug builds, `"production"` for App Store and TestFlight |
    | Background pushes | `"remote-notification"` in `UIBackgroundModes` |
    | Background app-refresh tasks | `"fetch"` in `UIBackgroundModes`, and each task identifier in `BGTaskSchedulerPermittedIdentifiers` |
    | Your own URL scheme | `CFBundleURLTypes` |

    For example:

    ```toml
    [tool.kivy.ios.info_plist]
    BGTaskSchedulerPermittedIdentifiers = ["com.example.myapp.refresh"]
    UIBackgroundModes = ["fetch", "remote-notification"]
    CFBundleURLTypes = [{ CFBundleURLName = "com.example.myapp", CFBundleURLSchemes = ["myapp"] }]

    [tool.kivy.ios.entitlements]
    aps-environment = "development"
    ```

    The hook registers a background-task handler for every identifier in
    `BGTaskSchedulerPermittedIdentifiers`, before launch ends, as iOS
    requires.

4. Lock the project:

    ```bash
    kivyforge lock -p ios
    ```

5. Create a `Lifecycle` and bind to the events you need. Create it before
   Kivy's loop starts, in `build()` for example. Events from launch wait in
   the queue until the first poll, so none are missed:

    ```python
    from lifecycle import Lifecycle

    class MyApp(App):
        def build(self):
            self.lifecycle = Lifecycle()
            self.lifecycle.bind(
                on_url=self.on_url,
                on_push_token=self.on_push_token,
                on_notification_response=self.on_notification_response,
            )
            self.lifecycle.register_for_push()
            return MyRoot()

        def on_url(self, _lifecycle, url, cold):
            print("opened with", url, "at launch" if cold else "while running")

        def on_push_token(self, _lifecycle, token):
            print("send this to your push server:", token)

        def on_notification_response(self, _lifecycle, user_info, action):
            print("notification tapped:", user_info)
    ```

    `lifecycle.py` lists every event and its arguments. Off iOS,
    `Lifecycle().available` is `False` and its methods do nothing, so the app
    still runs on a desktop.

## Add a delegate method of your own

To handle another callback, install it in `LifecycleHook.m` with the
`lh_install` helper, next to the existing ones in `lh_install_app_delegate`
or `lh_install_scene_delegate`. Pass the selector, its Objective-C type
encoding, and a block that takes `self` and the method's arguments. If SDL
already implements the method, `orig` is SDL's version: call it, or SDL stops
doing its part.

```objc
lh_install(cls, @selector(applicationDidReceiveMemoryWarning:), "v@:@", ^id(IMP orig) {
  return ^(id self, UIApplication *app) {
    lh_emit(@"memory_warning", @{});
    if (orig) {
      ((void (*)(id, SEL, id))orig)(self, @selector(applicationDidReceiveMemoryWarning:), app);
    }
  };
});
```

Then add the new type to `_DISPATCH` and `__events__` in `lifecycle.py`.

## Verify

Build and run on the Simulator:

```bash
kivyforge build -p ios --simulator
kivyforge run -p ios --simulator
```

`Lifecycle().status` is `"ok"` when the hook installed itself. Otherwise the
app's log shows a `Lifecycle:` warning with the reason. Then quit the app and
open a URL with your scheme:

```bash
xcrun simctl openurl booted myapp://hello
```

Your `on_url` handler receives `myapp://hello` with `cold` set to `True`.

## Things to know

!!! warning "Python does not run in the background"
    Kivy's clock stops while your app is in the background, so events that
    arrive then reach Python only when the app is next in front. Work that
    must happen in the background, such as a background task's job or the
    response to a background push, belongs in the native handlers in
    `LifecycleHook.m`.

- **Launch context arrives only through the hook.** Under iOS's scene
  lifecycle, the URL, notification tap or quick action that launched the app
  is not in `launchOptions`. SDL forwards a launch URL before Kivy is
  running, and Kivy's `Window.on_drop_file` never receives it. A URL that
  arrives while the app is running reaches both `on_drop_file` and the
  hook's `on_url`.
- **One notification-center delegate.** The hook sets the app's
  `UNUserNotificationCenter` delegate. A library that sets its own replaces
  the hook's, and the notification events stop.
- **The hook depends on SDL's class name.** It installs its methods on
  `SDLUIKitSceneDelegate`. If a future SDL renames that class, `status`
  reports it and nothing is installed.
- **The Simulator has limits.** It delivers a push token and local
  notifications, but not background pushes, and it refuses to submit
  background tasks. Test those on a device. To send a test push, use Apple's
  [Push Notifications Console](https://icloud.developer.apple.com/dashboard/notifications)
  with the token from `on_push_token`.
- **Static or dynamic.** The example's product is dynamic. A static product
  works too, because Xcode links a local package's source as one object
  file, so `+load` is never dropped. Declare a static product with
  `embed = false`.

## What's next

- [Sign the app](signing.md) to run push and background tasks on a device.
- [Add a Swift package](swift-packages.md) to wrap an SDK the hook calls.
- [`[tool.kivy.ios]` reference](../../reference/pyproject/ios.md).
