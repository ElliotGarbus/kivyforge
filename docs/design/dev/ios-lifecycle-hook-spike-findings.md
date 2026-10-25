# Findings — iOS app-lifecycle hooks through a Swift package

> 2026-10-25, macOS host, iOS Simulator only. Follow-up to issue #85, which
> asked for a way to run code in Android's `PythonActivity.onCreate`. The
> iOS counterpart is the `UIApplicationDelegate`, which in a kivyforge app
> belongs to SDL3, not to kivyforge or the user. The question: can a Swift
> package the user declares in `[tool.kivy.ios.native.swift_packages]` run
> code before Python starts and receive the delegate callbacks some SDKs
> need, **with no kivyforge change**?

**Short answer: yes, on the Simulator.** A source package with an
Objective-C `+load` runs before `main()`, can add or wrap methods on SDL's
delegate class, and UIKit calls them. That held for a dynamic product and a
static one. Push-token delivery and background-push delivery could not be
tested on the Simulator at all (finding 8), so those need a device pass.

## Environment

| | |
|---|---|
| Host | macOS 26.6.2, Xcode 27.0 (27A266a), iPhoneSimulator SDK 27.0 |
| Simulator | iPhone Air, iOS 27.0 |
| kivyforge | branch `macos-native-binaries-placement` at `90aceda0`, `.venv` editable install |
| App | scratch project (not in the repo): Kivy `3.0.0.dev202610051055`, pyobjus 1.2.4, CPython 3.15.0b4, all from kivy-mobile-wheels |
| SDL | `SDL3.framework` current version 401.2.0, i.e. 3.4.2; behaviour read from a local SDL 3.4.2 source tree, `src/video/uikit/SDL_uikitappdelegate.m` |
| Hook | local `path` package `LifecycleHook`, one Objective-C target, no dependencies |

The app's `pyproject.toml` added, beyond a normal Kivy app:

```toml
[tool.kivy.ios.info_plist]
BGTaskSchedulerPermittedIdentifiers = ["org.kivy.lifecycle-spike.load", "...didfinish", "...late", "...python"]
UIBackgroundModes = ["fetch", "processing", "remote-notification"]
CFBundleURLTypes = [{ CFBundleURLName = "org.kivy.lifecycle-spike", CFBundleURLSchemes = ["kfspike"] }]

[tool.kivy.ios.entitlements]
aps-environment = "development"

[tool.kivy.ios.native.swift_packages]
LifecycleHook = { path = "hook", products = ["LifecycleHook"] }   # static run: embed = false
```

All four keys passed through to the built `Info.plist` and the simulator
entitlements section unchanged.

## What the hook does

`+[KFLifecycleHook load]` records a timestamped log, then:

- looks up `SDLUIKitSceneDelegate` by name and, with
  `class_replaceMethod`, **adds** `application:didFinishLaunchingWithOptions:`,
  `application:didRegisterForRemoteNotificationsWithDeviceToken:`,
  `…didFailToRegister…`, `…didReceiveRemoteNotification:fetchCompletionHandler:`
  and `scene:continueUserActivity:`, and **wraps** SDL's own
  `scene:willConnectToSession:options:` and `scene:openURLContexts:`,
  calling the original IMP afterwards;
- registers a `BGTaskScheduler` handler;
- observes `UIApplicationDidFinishLaunchingNotification`,
  `UISceneWillConnectNotification`, `…DidBecomeActive` and
  `…DidEnterBackground`.

The added `didFinishLaunching` registers a second BGTask, calls
`registerForRemoteNotifications`, sets a `UNUserNotificationCenter`
delegate and requests authorization. Python reads the log with
`autoclass("KFLifecycleHook").report()` and can call `registerLateTask()`
to register a BGTask after launch.

The wrap helper is the whole trick:

```objc
static void kf_wrap(Class cls, SEL sel, const char *types, id (^make)(IMP orig)) {
    Method m = class_getInstanceMethod(cls, sel);
    IMP orig = m ? method_getImplementation(m) : NULL;
    class_replaceMethod(cls, sel, imp_implementationWithBlock(make(orig)), types);
}
```

## Findings

1. **Under UIScene, SDL's app delegate is `SDLUIKitSceneDelegate`.**
   `SDL_RunApp` passes `[SDLUIKitSceneDelegate getSceneDelegateClassName]`
   to `UIApplicationMain` as the *app* delegate class, and the same object
   then sets itself as the window scene's delegate. That class implements
   no `application:didFinishLaunchingWithOptions:`: SDL starts `SDL_main`
   from `scene:willConnectToSession:options:`. At runtime,
   `UIApplication.delegate` was `SDLUIKitSceneDelegate`. A hook aimed at
   `SDLUIKitDelegate`, SDL's pre-scene class, would install cleanly and
   never be called.

2. **`+load` runs before `main()`, for a dynamic and a static product.**
   The dynamic run embedded `LifecycleHook.framework` and linked it from
   the app. The static run (`type: .static`, `embed = false`) put no
   framework in the bundle, and `+load` still ran: Xcode links an SPM
   source target as one prelinked object
   (`Products/Debug-iphonesimulator/LifecycleHook.o`), not as a `.a`, so the
   linker never decides whether to pull an unreferenced class out of an
   archive. Nothing in the app references the class at link time. The
   `-ObjC` concern raised earlier applies only to a *binary* package that
   ships a static archive; that was not tested (finding 10).

   Timing on every launch: `SDLUIKitSceneDelegate` was already registered
   when `+load` ran, so `objc_getClass` found it. Hooks were installed at
   +0.005 s, and the added `didFinishLaunching` ran at +0.023 s.
   `willConnect` ran at +0.04 s, and Python's first call into the hook came
   at +0.57 s warm or +3.7 s on the first launch after install.

3. **UIKit calls methods added to SDL's class, and wrapping SDL's methods
   keeps SDL working.** The added `didFinishLaunchingWithOptions:` ran on
   every launch. With the app running, `simctl openurl booted
   kfspike://warm/test?x=1` went through the wrapped
   `scene:openURLContexts:` to SDL, and **Kivy's `on_drop_file` received
   `kfspike://warm/test?x=1`**. The added methods were installed before
   `UIApplicationMain`, so any check UIKit makes when it sets the delegate
   already saw them. Adding them later was not tried.

4. **Defect, upstream of kivyforge: a URL that cold-launches the app never
   reaches Kivy.** After terminating the app, `simctl openurl booted
   kfspike://cold/launch` launched it. The hook's `willConnect` wrapper saw
   the URL in `connectionOptions.URLContexts`, and SDL's
   `willConnect` passes it to `handleURL:` → `SDL_SendDropFile`. Yet Kivy's
   `on_drop_file` never fired, checked again 8 s later. SDL calls
   `handleURL:` before `SDL_main` (and therefore Kivy) has started, so the
   likely cause is SDL sending the drop event before its event queue
   exists. That is an inference: SDL's event code was not traced. The
   same path carries a universal link's `webpageURL`, so cold-start deep
   links of both kinds are likely lost. A hook can capture the URL and hand
   it to Python, which is the workaround until SDL or Kivy fixes it.

5. **Launch context is not where Android habits look for it.** Under the
   scene lifecycle the delegate's `launchOptions` were empty on every
   launch, including the URL cold launch. The
   `UIApplicationDidFinishLaunchingNotification` and
   `UISceneWillConnectNotification` `userInfo` were empty too. The URL,
   user activities, shortcut item and notification response all arrive
   only in `scene:willConnectToSession:options:`'s `connectionOptions`. So
   **observing notifications is not enough to capture launch context**;
   the hook has to wrap SDL's `willConnect`.

6. **`BGTaskScheduler` registration succeeded everywhere, including from
   Python 36 s after launch.** It returned `YES` from `+load`, from the
   added `didFinishLaunching`, from the `DidFinishLaunching` observer and
   from Python via pyobjus. Apple documents that handlers must be
   registered before launch finishes, and that rule is the reason this
   spike exists. The iOS 27 Simulator did not enforce it, so **this spike
   does not show a late registration to be safe**: that needs a device. A
   task launch was not simulated (`_simulateLaunchForTaskWithIdentifier:`
   needs a debugger attached).

7. **A `UNUserNotificationCenter` delegate set from the hook works.** After
   authorization (granted by tapping Allow in the system prompt), a
   foreground `simctl push` of an alert reached the hook's `willPresent`
   with `userInfo` keys `aps, kf, Simulator Target Bundle`, and the banner
   showed. Apple requires this delegate to be set before launch finishes if
   the app is to receive the response for a notification tap that
   launched it, which is another before-Python requirement the hook meets.
   A cold launch from a notification tap was attempted, but the tap missed
   the banner, so `connectionOptions.notificationResponse` was not observed.

8. **The Simulator does not deliver background pushes or device tokens to
   the app delegate, even in a plain UIKit app.** For an alert push with
   `content-available: 1`, the spike's log shows UIKit receiving
   `UIFetchContentInBackgroundAction` each time, but the added
   `didReceiveRemoteNotification:fetchCompletionHandler:` never ran. To
   tell an injection failure from a Simulator limit, a control app was
   built: plain UIKit, no SDL, no kivyforge, with the same method compiled
   into its own `AppDelegate`, the same background modes, entitlement and
   payload. It received the same action, and its method did not run either.
   Neither app got `didRegisterForRemoteNotifications…` or
   `didFailToRegister…`. Both push paths are **unverified, not failed**,
   and need a device.

9. **A background launch runs the whole Kivy app.** With the app
   terminated, the `content-available` push launched it in the background:
   `+load`, `didFinishLaunching` and `willConnect` ran, and Python called
   the hook at +0.57 s, while `DidBecomeActive` did not come until the app
   was brought forward 31 s later. So a background launch (push, and
   presumably BGTask) runs `main.py`, window creation included, in the
   background. Nothing failed here, but app code that assumes the user can
   see it at start is wrong on iOS too.

10. **What this coupling costs.** The hook finds SDL's class **by name**,
    which ties it to SDL's internals. SDL documents
    `getSceneDelegateClassName` and `getAppDelegateClassName` as the
    override points, so they are reasonably stable, but a future SDL could
    rename the class and the hook would quietly install nothing. A sturdier
    hook would swizzle `-[UIApplication setDelegate:]` and patch whatever
    class arrives, which is GoogleUtilities' approach for Firebase; this
    spike did not try it. Two kivyforge-side limits were seen and not
    exercised: `OTHER_LDFLAGS` is a managed setting, so a user cannot add
    `-ObjC` for a binary package shipping a static archive, and no Release
    or device build was made, so `-dead_strip` was not tested.

## What this means for issue #85 on iOS

The need is real and larger than on Android. Push tokens, push delivery
and the notification-center delegate, background-task registration, and
any cold-start URL all have to be handled before Python runs, or (for
launch context) only arrive at a time Python cannot see. But kivyforge does
not need a "replace the app delegate" feature to unblock users: the
existing `swift_packages` channel already carries a hook that works, with
either linkage.

Suggested follow-ups, roughly in order:

1. **A device pass** for findings 6–8: device token, background-push
   delivery to an added delegate method, late BGTask registration, and a
   real BGTask launch. It belongs in `hardware-checklist.toml`.
2. **A guide and an example** (`examples/mobile/ios-lifecycle-hook`): the
   wrap helper, wrapping `willConnect` for launch context, and the pyobjus
   read-back, with finding 1's class-name warning.
3. **Report finding 4 upstream** (SDL, or Kivy if Kivy can drain it). Until
   then the guide's hook is the workaround for cold-start deep links.
4. Only if users find the hook too hard to write: a small kivyforge-owned
   hook that records launch context and push tokens for Python. That is a
   product decision, not something this spike shows is needed.

## Not tested

Universal links (need an associated domain), quick actions, a cold launch
from a notification tap (finding 7), a real BGTask launch, `-[UIApplication
setDelegate:]` swizzling, a binary static package, Release builds, devices,
and Python's own stdout in the unified log (the hook's `NSLog` lines were
used throughout).
