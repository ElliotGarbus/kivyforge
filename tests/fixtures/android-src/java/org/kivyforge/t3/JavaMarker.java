package org.kivyforge.t3;

/**
 * Exists only to be found in a built APK's dex. The T3 check asserts this
 * class is defined there, which proves a [tool.kivy.android.src].java root
 * reached the compiler. Nothing references it.
 */
public final class JavaMarker {
    private JavaMarker() {}
}
