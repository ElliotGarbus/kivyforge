// LifecycleHook: app-delegate code for a Kivy app whose delegate belongs to SDL.
//
// kivyforge's iOS bootstrap hands control to SDL3, and on iOS 13+ SDL passes
// its SDLUIKitSceneDelegate class to UIApplicationMain as the *app* delegate
// (the same object is also the window scene's delegate). An SDK that needs
// application:didFinishLaunchingWithOptions:, the push-token callback or a
// notification-center delegate set before launch ends has nowhere to go, and
// Python starts too late to provide it.
//
// This framework's +load runs before main(). It adds the missing delegate
// methods to SDL's class, wraps the two scene methods SDL does implement
// (calling SDL's version afterwards), and registers BGTask handlers. Each
// callback queues an event; Python collects them with +drainEvents.
//
// Events (every one has a "type"):
//   url                    {url, cold}  cold is true for the URL that launched
//                                       the app, which SDL loses before Kivy
//                                       starts
//   shortcut               {shortcut_type}
//   push_permission        {granted}
//   push_token             {token}      hex, for your push server
//   push_token_error       {error}
//   remote_notification    {user_info}  a background (content-available) push
//   notification           {user_info}  shown while the app is in front
//   notification_response  {user_info, action}  the user tapped a notification,
//                                       including one that launched the app
//   background_task        {identifier}
#import "LifecycleHook.h"

@import BackgroundTasks;
@import UIKit;
@import UserNotifications;
#import <objc/runtime.h>

static NSMutableArray<NSDictionary *> *gEvents;
static NSString *gStatus = @"LifecycleHook +load has not run";

static id lh_jsonable(id value) {
    if (!value) {
        return [NSNull null];
    }
    return [NSJSONSerialization isValidJSONObject:@[ value ]] ? value : [value description];
}

static void lh_emit(NSString *type, NSDictionary *fields) {
    NSMutableDictionary *event = [NSMutableDictionary dictionaryWithDictionary:fields ?: @{}];
    event[@"type"] = type;
    @synchronized(gEvents) {
        [gEvents addObject:event];
    }
    NSLog(@"LifecycleHook: %@", type);
}

// Replace or add `sel` on `cls`. `make` receives the previous implementation
// (NULL when SDL has none) and returns the block to install.
static void lh_install(Class cls, SEL sel, const char *types, id (^make)(IMP orig)) {
    Method m = class_getInstanceMethod(cls, sel);
    IMP orig = m ? method_getImplementation(m) : NULL;
    class_replaceMethod(cls, sel, imp_implementationWithBlock(make(orig)), types);
}

@interface LifecycleNotificationDelegate : NSObject <UNUserNotificationCenterDelegate>
@end

@implementation LifecycleNotificationDelegate

- (void)userNotificationCenter:(UNUserNotificationCenter *)center
       willPresentNotification:(UNNotification *)notification
         withCompletionHandler:(void (^)(UNNotificationPresentationOptions))done {
    lh_emit(@"notification",
            @{@"user_info" : lh_jsonable(notification.request.content.userInfo)});
    done(UNNotificationPresentationOptionBanner | UNNotificationPresentationOptionList |
         UNNotificationPresentationOptionSound);
}

- (void)userNotificationCenter:(UNUserNotificationCenter *)center
    didReceiveNotificationResponse:(UNNotificationResponse *)response
             withCompletionHandler:(void (^)(void))done {
    lh_emit(@"notification_response", @{
        @"user_info" : lh_jsonable(response.notification.request.content.userInfo),
        @"action" : response.actionIdentifier,
    });
    done();
}

@end

static void lh_install_app_delegate(Class cls) {
    lh_install(cls, @selector(application:didFinishLaunchingWithOptions:), "B@:@@", ^id(IMP orig) {
      return ^BOOL(id self, UIApplication *app, NSDictionary *options) {
        // Set before launch ends, or a tap that launched the app is never
        // delivered. The center keeps only a weak reference.
        static LifecycleNotificationDelegate *delegate;
        delegate = [LifecycleNotificationDelegate new];
        [UNUserNotificationCenter currentNotificationCenter].delegate = delegate;
        if (!orig) {
          return YES;
        }
        return ((BOOL (*)(id, SEL, id, id))orig)(
            self, @selector(application:didFinishLaunchingWithOptions:), app, options);
      };
    });

    lh_install(cls, @selector(application:didRegisterForRemoteNotificationsWithDeviceToken:),
               "v@:@@", ^id(IMP orig) {
                 return ^(id self, UIApplication *app, NSData *token) {
                   NSMutableString *hex = [NSMutableString stringWithCapacity:token.length * 2];
                   const unsigned char *bytes = token.bytes;
                   for (NSUInteger i = 0; i < token.length; i++) {
                     [hex appendFormat:@"%02x", bytes[i]];
                   }
                   lh_emit(@"push_token", @{@"token" : hex});
                 };
               });

    lh_install(cls, @selector(application:didFailToRegisterForRemoteNotificationsWithError:),
               "v@:@@", ^id(IMP orig) {
                 return ^(id self, UIApplication *app, NSError *error) {
                   lh_emit(@"push_token_error", @{@"error" : error.localizedDescription});
                 };
               });

    lh_install(cls, @selector(application:didReceiveRemoteNotification:fetchCompletionHandler:),
               "v@:@@@?", ^id(IMP orig) {
                 return ^(id self, UIApplication *app, NSDictionary *info,
                          void (^done)(UIBackgroundFetchResult)) {
                   lh_emit(@"remote_notification", @{@"user_info" : lh_jsonable(info)});
                   // Kivy's clock does not run in the background, so Python
                   // sees this event only when the app is next in front. Any
                   // work that must happen now belongs here, in native code.
                   done(UIBackgroundFetchResultNoData);
                 };
               });
}

static void lh_install_scene_delegate(Class cls) {
    lh_install(cls, @selector(scene:willConnectToSession:options:), "v@:@@@", ^id(IMP orig) {
      return ^(id self, UIScene *scene, UISceneSession *session, UISceneConnectionOptions *options) {
        // Launch context arrives only here under the scene lifecycle: the
        // app delegate's launchOptions are empty. SDL forwards these URLs
        // before Kivy is running, and they are lost, so record them first.
        for (UIOpenURLContext *context in options.URLContexts) {
          lh_emit(@"url", @{@"url" : context.URL.absoluteString, @"cold" : @YES});
        }
        for (NSUserActivity *activity in options.userActivities) {
          if (activity.webpageURL) {
            lh_emit(@"url", @{@"url" : activity.webpageURL.absoluteString, @"cold" : @YES});
          }
        }
        if (options.shortcutItem) {
          lh_emit(@"shortcut", @{@"shortcut_type" : options.shortcutItem.type});
        }
        if (orig) {
          ((void (*)(id, SEL, id, id, id))orig)(
              self, @selector(scene:willConnectToSession:options:), scene, session, options);
        }
      };
    });

    lh_install(cls, @selector(scene:openURLContexts:), "v@:@@", ^id(IMP orig) {
      return ^(id self, UIScene *scene, NSSet<UIOpenURLContext *> *contexts) {
        for (UIOpenURLContext *context in contexts) {
          lh_emit(@"url", @{@"url" : context.URL.absoluteString, @"cold" : @NO});
        }
        if (orig) {
          ((void (*)(id, SEL, id, id))orig)(self, @selector(scene:openURLContexts:), scene,
                                            contexts);
        }
      };
    });

    lh_install(cls, @selector(scene:continueUserActivity:), "v@:@@", ^id(IMP orig) {
      return ^(id self, UIScene *scene, NSUserActivity *activity) {
        if (activity.webpageURL) {
          lh_emit(@"url", @{@"url" : activity.webpageURL.absoluteString, @"cold" : @NO});
        }
        if (orig) {
          ((void (*)(id, SEL, id, id))orig)(self, @selector(scene:continueUserActivity:), scene,
                                            activity);
        }
      };
    });
}

// Handlers must be registered before launch ends, so register one for every
// identifier the app declares.
static void lh_register_background_tasks(void) {
    NSArray *identifiers =
        [NSBundle.mainBundle objectForInfoDictionaryKey:@"BGTaskSchedulerPermittedIdentifiers"];
    for (NSString *identifier in identifiers) {
        [[BGTaskScheduler sharedScheduler]
            registerForTaskWithIdentifier:identifier
                               usingQueue:nil
                            launchHandler:^(BGTask *task) {
                              lh_emit(@"background_task", @{@"identifier" : task.identifier});
                              // Do the task's work here, natively: Kivy's
                              // clock is stopped while the app is in the
                              // background.
                              [task setTaskCompletedWithSuccess:YES];
                            }];
    }
}

@implementation LifecycleHook

+ (void)load {
    gEvents = [NSMutableArray array];

    // SDL's override point for this name is +getSceneDelegateClassName, so
    // it is stable across SDL 3 releases, but it is SDL's, not ours. If it
    // ever changes, status says so instead of the hook silently doing nothing.
    Class sdl = objc_getClass("SDLUIKitSceneDelegate");
    if (!sdl) {
        gStatus = @"SDLUIKitSceneDelegate not found: this SDL version names its delegate differently";
        NSLog(@"LifecycleHook: %@", gStatus);
    } else {
        lh_install_app_delegate(sdl);
        lh_install_scene_delegate(sdl);
        gStatus = @"ok";
    }
    lh_register_background_tasks();
}

+ (NSString *)status {
    return gStatus;
}

+ (NSString *)drainEvents {
    NSArray *events;
    @synchronized(gEvents) {
        events = [gEvents copy];
        [gEvents removeAllObjects];
    }
    NSData *json = [NSJSONSerialization dataWithJSONObject:events options:0 error:nil];
    return [[NSString alloc] initWithData:json encoding:NSUTF8StringEncoding];
}

+ (void)registerForPush {
    UNAuthorizationOptions options =
        UNAuthorizationOptionAlert | UNAuthorizationOptionBadge | UNAuthorizationOptionSound;
    [[UNUserNotificationCenter currentNotificationCenter]
        requestAuthorizationWithOptions:options
                      completionHandler:^(BOOL granted, NSError *error) {
                        lh_emit(@"push_permission", @{@"granted" : @(granted)});
                        dispatch_async(dispatch_get_main_queue(), ^{
                          [[UIApplication sharedApplication] registerForRemoteNotifications];
                        });
                      }];
}

+ (NSString *)submitRefreshTask:(NSString *)identifier {
    NSError *error = nil;
    BGAppRefreshTaskRequest *request = [[BGAppRefreshTaskRequest alloc] initWithIdentifier:identifier];
    if (![[BGTaskScheduler sharedScheduler] submitTaskRequest:request error:&error]) {
        return error.localizedDescription ?: @"submitTaskRequest failed";
    }
    return @"";
}

+ (void)scheduleTestNotificationAfter:(double)seconds {
    UNMutableNotificationContent *content = [UNMutableNotificationContent new];
    content.title = @"Lifecycle hook";
    content.body = @"Tap to open the app";
    content.userInfo = @{@"source" : @"test"};
    UNNotificationRequest *request = [UNNotificationRequest
        requestWithIdentifier:@"lifecycle-hook-test"
                      content:content
                      trigger:[UNTimeIntervalNotificationTrigger triggerWithTimeInterval:seconds
                                                                                 repeats:NO]];
    [[UNUserNotificationCenter currentNotificationCenter] addNotificationRequest:request
                                                           withCompletionHandler:nil];
}

@end
