package org.kivy.android;

import android.os.Bundle;
import android.system.Os;
import android.util.Log;

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
        } catch (Exception e) {
            Log.e(TAG, "bundle unpack failed", e);
            throw new RuntimeException(e);
        }
        super.onCreate(savedInstanceState);
    }
}
