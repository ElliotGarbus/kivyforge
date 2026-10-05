package org.kivy.android;

import android.annotation.TargetApi;
import android.app.Activity;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.content.res.Configuration;
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
import android.view.inputmethod.InputMethodManager;

import org.libsdl.app.SDLActivity;

import java.io.File;
import java.lang.reflect.InvocationTargetException;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Iterator;
import java.util.List;

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
    @TargetApi(30)
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

    // The members the bundled `android` package calls (android.activity,
    // android.permissions, android.darkmode; Kivy 2.3.1's TextInput calls
    // changeKeyboard). Each BEGIN/END p4a block is python-for-android's own
    // code at the revision in templates/p4a/P4A_VENDOR.toml: change it only
    // with scripts/sync_p4a.py, which CI checks.

    // BEGIN p4a new-intent-listener
    public interface NewIntentListener {
        void onNewIntent(Intent intent);
    }

    private List<NewIntentListener> newIntentListeners = null;

    public void registerNewIntentListener(NewIntentListener listener) {
        if (this.newIntentListeners == null)
            this.newIntentListeners =
                    Collections.synchronizedList(new ArrayList<NewIntentListener>());
        this.newIntentListeners.add(listener);
    }

    public void unregisterNewIntentListener(NewIntentListener listener) {
        if (this.newIntentListeners == null) return;
        this.newIntentListeners.remove(listener);
    }
    // END p4a new-intent-listener

    // p4a's onNewIntent and onActivityResult return without calling super;
    // these dispatch the same way and then call it, because SDLActivity
    // receives results there (SDL3's file dialog, for one).
    @Override
    protected void onNewIntent(Intent intent) {
        if (this.newIntentListeners != null) {
            this.onResume();
            synchronized (this.newIntentListeners) {
                Iterator<NewIntentListener> iterator = this.newIntentListeners.iterator();
                while (iterator.hasNext()) {
                    (iterator.next()).onNewIntent(intent);
                }
            }
        }
        super.onNewIntent(intent);
    }

    // BEGIN p4a activity-result-listener
    public interface ActivityResultListener {
        void onActivityResult(int requestCode, int resultCode, Intent data);
    }

    private List<ActivityResultListener> activityResultListeners = null;

    public void registerActivityResultListener(ActivityResultListener listener) {
        if (this.activityResultListeners == null)
            this.activityResultListeners =
                    Collections.synchronizedList(new ArrayList<ActivityResultListener>());
        this.activityResultListeners.add(listener);
    }

    public void unregisterActivityResultListener(ActivityResultListener listener) {
        if (this.activityResultListeners == null) return;
        this.activityResultListeners.remove(listener);
    }
    // END p4a activity-result-listener

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent intent) {
        if (this.activityResultListeners != null) {
            this.onResume();
            synchronized (this.activityResultListeners) {
                Iterator<ActivityResultListener> iterator =
                        this.activityResultListeners.iterator();
                while (iterator.hasNext())
                    (iterator.next()).onActivityResult(requestCode, resultCode, intent);
            }
        }
        super.onActivityResult(requestCode, resultCode, intent);
    }

    // BEGIN p4a permissions
    public interface PermissionsCallback {
        void onRequestPermissionsResult(int requestCode, String[] permissions, int[] grantResults);
    }

    private PermissionsCallback permissionCallback;
    private boolean havePermissionsCallback = false;

    public void addPermissionsCallback(PermissionsCallback callback) {
        permissionCallback = callback;
        havePermissionsCallback = true;
        Log.v(TAG, "addPermissionsCallback(): Added callback for onRequestPermissionsResult");
    }

    @Override
    public void onRequestPermissionsResult(
            int requestCode, String[] permissions, int[] grantResults) {
        Log.v(TAG, "onRequestPermissionsResult()");
        if (havePermissionsCallback) {
            Log.v(TAG, "onRequestPermissionsResult passed to callback");
            permissionCallback.onRequestPermissionsResult(requestCode, permissions, grantResults);
        }
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
    }

    /** Used by android.permissions p4a module to check a permission */
    public boolean checkCurrentPermission(String permission) {
        if (android.os.Build.VERSION.SDK_INT < 23) return true;

        try {
            java.lang.reflect.Method methodCheckPermission =
                    Activity.class.getMethod("checkSelfPermission", String.class);
            Object resultObj = methodCheckPermission.invoke(this, permission);
            int result = Integer.parseInt(resultObj.toString());
            if (result == PackageManager.PERMISSION_GRANTED) return true;
        } catch (IllegalAccessException | NoSuchMethodException | InvocationTargetException e) {
        }
        return false;
    }

    /** Used by android.permissions p4a module to request runtime permissions */
    public void requestPermissionsWithRequestCode(String[] permissions, int requestCode) {
        if (android.os.Build.VERSION.SDK_INT < 23) return;
        try {
            java.lang.reflect.Method methodRequestPermission =
                    Activity.class.getMethod("requestPermissions", String[].class, int.class);
            methodRequestPermission.invoke(this, permissions, requestCode);
        } catch (IllegalAccessException | NoSuchMethodException | InvocationTargetException e) {
        }
    }

    public void requestPermissions(String[] permissions) {
        requestPermissionsWithRequestCode(permissions, 1);
    }
    // END p4a permissions

    // BEGIN p4a dark-mode
    public interface DarkModeListener {
        void onDarkModeChanged(boolean isDarkMode);
    }

    private DarkModeListener darkModeListener = null;

    public void setDarkModeListener(DarkModeListener listener) {
        darkModeListener = listener;
    }

    @Override
    public void onConfigurationChanged(Configuration newConfig) {
        int currentNightMode = newConfig.uiMode & Configuration.UI_MODE_NIGHT_MASK;
        boolean isDarkMode = currentNightMode == Configuration.UI_MODE_NIGHT_YES;

        if (darkModeListener != null) {
            darkModeListener.onDarkModeChanged(isDarkMode);
        }

        super.onConfigurationChanged(newConfig);
    }
    // END p4a dark-mode

    // BEGIN p4a change-keyboard
    public static void changeKeyboard(int inputType) {
        if (SDLActivity.keyboardInputType != inputType) {
            SDLActivity.keyboardInputType = inputType;
            InputMethodManager imm =
                    (InputMethodManager)
                            getContext().getSystemService(Context.INPUT_METHOD_SERVICE);
            imm.restartInput(mTextEdit);
        }
    }
    // END p4a change-keyboard
}
