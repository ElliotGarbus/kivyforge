#import <Foundation/Foundation.h>

/// App-lifecycle events captured before and after Python starts.
///
/// Every method is a class method that takes and returns strings or numbers,
/// so pyobjus can call it with `autoclass("LifecycleHook")`.
@interface LifecycleHook : NSObject

/// "ok", or why the hook could not install itself.
+ (NSString *)status;

/// The events queued since the last call, as a JSON array, oldest first.
/// Each event is an object with a "type" key; see LifecycleHook.m.
+ (NSString *)drainEvents;

/// Ask for notification permission, then register with APNs. The device
/// token arrives later as a "push_token" event.
+ (void)registerForPush;

/// Submit an app-refresh request for one of the identifiers listed in
/// BGTaskSchedulerPermittedIdentifiers. Returns "" or an error message.
+ (NSString *)submitRefreshTask:(NSString *)identifier;

/// Post a local notification after `seconds`, to try the notification
/// events without a push server.
+ (void)scheduleTestNotificationAfter:(double)seconds;

@end
