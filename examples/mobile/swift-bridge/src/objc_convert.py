"""Convert pyobjus proxies to Python values. Copy this file into your app.

pyobjus hands back Foundation objects as proxies. A Swift ``String``,
``[String]`` or ``[String: Any]`` reaches Python as an ``NSString``,
``NSArray`` or ``NSDictionary`` proxy, and a number inside a collection as an
``NSNumber`` proxy. ``to_py`` turns a whole tree of them into ``str``,
``int``, ``float``, ``bool``, ``list`` and ``dict``.

Import this module only on iOS: it needs pyobjus.
"""

from __future__ import annotations

from pyobjus import autoclass

# isKindOfClass_ needs the class object. Passing the autoclass proxy itself
# returns False for every value, so take .oclass() once here.
_NSString = autoclass("NSString").oclass()
_NSNumber = autoclass("NSNumber").oclass()
_NSArray = autoclass("NSArray").oclass()
_NSDictionary = autoclass("NSDictionary").oclass()


def nsstr(value) -> str | None:
    """An NSString proxy as ``str``; ``None`` stays ``None``."""
    if value is None or isinstance(value, str):
        return value
    raw = value.UTF8String()
    return raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)


def _count(collection) -> int:
    # Swift's bridged arrays expose count as an int attribute; Foundation's
    # own arrays expose it as a method. Accept both.
    n = collection.count
    return n if isinstance(n, int) else n()


def to_py(value):
    """Convert a Foundation proxy, and everything inside it, to Python."""
    if value is None or isinstance(value, (str, bytes, bool, int, float)):
        return value
    if value.isKindOfClass_(_NSString):
        return nsstr(value)
    if value.isKindOfClass_(_NSNumber):
        code = value.objCType()
        code = code.decode() if isinstance(code, bytes) else str(code)
        if code in ("c", "B"):  # a Swift Bool arrives as 'c'
            return bool(value.boolValue())
        if code in ("f", "d"):
            return value.doubleValue()
        return value.longLongValue()
    if value.isKindOfClass_(_NSArray):
        return [to_py(value.objectAtIndex_(i)) for i in range(_count(value))]
    if value.isKindOfClass_(_NSDictionary):
        keys = value.allKeys()
        result = {}
        for i in range(_count(keys)):
            key = keys.objectAtIndex_(i)
            result[to_py(key)] = to_py(value.objectForKey_(key))
        return result
    return value  # any other object stays a proxy
