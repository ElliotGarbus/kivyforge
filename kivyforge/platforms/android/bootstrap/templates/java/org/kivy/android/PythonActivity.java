package org.kivy.android;

import android.graphics.Color;
import android.graphics.Insets;
import android.os.Build;
import android.os.Bundle;
import android.system.Os;
import android.util.Log;
import android.view.View;
import android.view.Window;
import android.view.WindowInsets;
import android.view.WindowInsetsController;

import org.libsdl.app.SDLActivity;

import java.io.File;

/**
 * Kivyforge PythonActivity.
 *
 * Generation-agnostic: the SDL family named in getLibraries() below is
 * substituted at render time (SDL2 for Kivy 2.x, SDL3 for Kivy 3.x), and the
 * matching org/libsdl/app glue is vendored alongside it.
 *
 * Load model (docs/design/platforms/android/05-bootstrap-android.md):
 *  - SDLActivity static init loads the SDL family -> libpython -> libmain
 *    (getLibraries order below), so the SDL JNIEnv getter is resident before
 *    any Python runs.
 *  - The asset bundle (_python_bundle) is unpacked to app-private storage
 *    before super.onCreate(), version-stamped so a second launch skips it.
 *  - The environment contract is set before any native code runs.
 *  - libmain's SDL_main initializes CPython (site_import deferred), installs
 *    the extension-module finder from the bundle manifest, then imports the
 *    entry-point module named by KF_ENTRY_POINT.
 */
public class PythonActivity extends SDLActivity {
    private static final String TAG = "kivyforge";

    // [tool.kivy].entry_point, substituted at render time. The launcher reads
    // it from the environment, so the native sources stay project-independent.
    private static final String ENTRY_POINT = "main";

    // [tool.kivy.android].fullscreen, substituted at render time. On Android
    // Kivy ignores its own graphics.fullscreen when it creates the window and
    // reads P4A_IS_WINDOWED instead (named for python-for-android, which set
    // it first); a fullscreen SDL window is what hides the system bars, since
    // SDLActivity.onCreate clears any fullscreen flag the theme set.
    private static final boolean FULLSCREEN = false;

    // [tool.kivy].orientation as SDL hint names, substituted at render time.
    // Kivy passes KIVY_ORIENTATION to SDL; with no hint, SDL requests
    // FULL_USER for a resizable window and the manifest's orientation is lost.
    private static final String ORIENTATION = "Portrait";

    // True for kivy_generation = 2, substituted at render time. Kivy 2.3.1 has
    // no safe-area API, so an edge-to-edge window would put its content under
    // the system bars; generation 2 pads the content clear of them instead,
    // with black behind the bars. Kivy 3 apps stay edge-to-edge and pad
    // themselves with kivy.mobile.get_safe_area().
    private static final boolean PAD_SYSTEM_BARS = true;

    // Kivy-compatibility: kivy.app / kivy.metrics reach the activity through
    // autoclass('org.kivy.android.PythonActivity').mActivity, and
    // org.renpy.android.Hardware.getDPI() reads it too. Preserving this static
    // is what keeps unmodified Kivy-Android code working (android/05
    // §namespace preservation).
    public static PythonActivity mActivity = null;

    @Override
    protected String getMainFunction() {
        return "SDL_main";
    }

    @Override
    protected String[] getLibraries() {
        return new String[] {
            "SDL2", "SDL2_image", "SDL2_mixer", "SDL2_ttf",
            "python3.14",
            "main",
        };
    }

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        mActivity = this;
        try {
            // Contract smoke-test hook (android/05): the instrumented test
            // passes this extra so the launcher runs the inert self-test.
            if (getIntent() != null
                    && getIntent().getBooleanExtra("kivyforge_selftest", false)) {
                Os.setenv("KIVYFORGE_SELFTEST", "1", true);
            }
            File bundleDir = PythonBundle.unpack(this);
            PythonBundle.setEnvironment(this, bundleDir, ENTRY_POINT);
            Os.setenv("P4A_IS_WINDOWED", FULLSCREEN ? "False" : "True", true);
            Os.setenv("KIVY_ORIENTATION", ORIENTATION, true);
        } catch (Exception e) {
            Log.e(TAG, "bundle unpack failed", e);
            throw new RuntimeException(e);
        }
        super.onCreate(savedInstanceState);
        if (PAD_SYSTEM_BARS && Build.VERSION.SDK_INT >= 30) {
            padForSystemBars();
        }
    }

    // Edge-to-edge is forced only for targetSdk 35+ on Android 15+; opting in
    // on every API 30+ device gives one layout, whatever the device or target.
    // The bar insets go to zero when the bars hide (fullscreen), so only the
    // cutout stays padded. The keyboard's insets are left to Kivy.
    @SuppressWarnings("deprecation")
    private void padForSystemBars() {
        View content = findViewById(android.R.id.content);
        if (content == null) {
            return;
        }
        Window window = getWindow();
        window.setDecorFitsSystemWindows(false);
        // Ignored from API 35, where the black content background shows through.
        window.setStatusBarColor(Color.BLACK);
        window.setNavigationBarColor(Color.BLACK);
        content.setBackgroundColor(Color.BLACK);
        content.setOnApplyWindowInsetsListener((view, insets) -> {
            Insets bars = insets.getInsets(
                    WindowInsets.Type.systemBars() | WindowInsets.Type.displayCutout());
            view.setPadding(bars.left, bars.top, bars.right, bars.bottom);
            return WindowInsets.CONSUMED;
        });
        WindowInsetsController controller = window.getInsetsController();
        if (controller != null) {
            // Light icons, readable on black.
            controller.setSystemBarsAppearance(0,
                    WindowInsetsController.APPEARANCE_LIGHT_STATUS_BARS
                    | WindowInsetsController.APPEARANCE_LIGHT_NAVIGATION_BARS);
        }
    }
}
