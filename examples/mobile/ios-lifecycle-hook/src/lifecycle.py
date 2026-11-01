"""Kivy events for the iOS app lifecycle, fed by the LifecycleHook framework.

Copy this module and ``lifecycle-hook/`` into your own app. The framework runs
before Python and queues what it sees; this module drains that queue on Kivy's
clock and dispatches each entry as a Kivy event:

    on_url(url, cold)                    cold: the URL launched the app
    on_shortcut(shortcut_type)
    on_push_permission(granted)
    on_push_token(token)                 hex string for your push server
    on_push_token_error(error)
    on_remote_notification(user_info)    a background push
    on_notification(user_info)           shown while the app is in front
    on_notification_response(user_info, action)
    on_background_task(identifier)

Events that arrive while the app is in the background are queued and
dispatched when it is next in front, because Kivy's clock does not run in the
background. Bind before ``App.run()`` returns control to Kivy's loop (in
``build`` is fine): nothing is dispatched before the first poll, so events
from launch are not missed.

Off iOS, ``available`` is false and every call does nothing, so the app still
runs on a desktop.
"""

from __future__ import annotations

import json

from kivy.clock import Clock
from kivy.event import EventDispatcher
from kivy.logger import Logger
from kivy.utils import platform

POLL_INTERVAL = 0.25  # seconds


class Lifecycle(EventDispatcher):
    __events__ = (
        "on_url",
        "on_shortcut",
        "on_push_permission",
        "on_push_token",
        "on_push_token_error",
        "on_remote_notification",
        "on_notification",
        "on_notification_response",
        "on_background_task",
    )

    # Which event each queued "type" becomes, and which fields it passes.
    _DISPATCH = {
        "url": ("on_url", ("url", "cold")),
        "shortcut": ("on_shortcut", ("shortcut_type",)),
        "push_permission": ("on_push_permission", ("granted",)),
        "push_token": ("on_push_token", ("token",)),
        "push_token_error": ("on_push_token_error", ("error",)),
        "remote_notification": ("on_remote_notification", ("user_info",)),
        "notification": ("on_notification", ("user_info",)),
        "notification_response": ("on_notification_response", ("user_info", "action")),
        "background_task": ("on_background_task", ("identifier",)),
    }

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._hook = None
        self.status = "not on iOS"
        if platform == "ios":
            from rubicon.objc import ObjCClass

            self._hook = ObjCClass("LifecycleHook")
            # An NSString formats like a str but is not one; str() makes one.
            self.status = str(self._hook.status())
            if self.status != "ok":
                Logger.warning("Lifecycle: %s", self.status)
            Clock.schedule_interval(self._poll, POLL_INTERVAL)

    @property
    def available(self) -> bool:
        return self._hook is not None and self.status == "ok"

    def register_for_push(self) -> None:
        """Ask for notification permission, then register with APNs."""
        if self._hook is not None:
            self._hook.registerForPush()

    def submit_refresh_task(self, identifier: str) -> str:
        """Submit an app-refresh request. Returns "" or an error message."""
        if self._hook is None:
            return "not on iOS"
        return str(self._hook.submitRefreshTask(identifier))

    def schedule_test_notification(self, seconds: float) -> None:
        """Post a local notification after ``seconds``."""
        if self._hook is not None:
            self._hook.scheduleTestNotificationAfter(float(seconds))

    def _poll(self, _dt) -> None:
        for event in json.loads(str(self._hook.drainEvents())):
            name, fields = self._DISPATCH.get(event["type"], (None, ()))
            if name is None:
                Logger.warning("Lifecycle: unknown event %r", event)
                continue
            self.dispatch(name, *(event.get(field) for field in fields))

    # Default handlers; bind to the events instead of overriding these.
    def on_url(self, url, cold):
        pass

    def on_shortcut(self, shortcut_type):
        pass

    def on_push_permission(self, granted):
        pass

    def on_push_token(self, token):
        pass

    def on_push_token_error(self, error):
        pass

    def on_remote_notification(self, user_info):
        pass

    def on_notification(self, user_info):
        pass

    def on_notification_response(self, user_info, action):
        pass

    def on_background_task(self, identifier):
        pass
