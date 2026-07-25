package org.kivy.android;

import android.os.Bundle;
import android.system.Os;
import android.util.Log;

import org.libsdl.app.SDLActivity;

import java.io.File;
import java.io.FileNotFoundException;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;

/**
 * Kivyforge Phase-0 prototype PythonActivity.
 *
 * Load model under test (docs/design/platforms/android/05-bootstrap-android.md):
 *  - SDLActivity static init loads SDL2 family -> libpython -> libmain
 *    (getLibraries order below), so the SDL JNIEnv getter is resident before
 *    any Python runs.
 *  - The asset bundle (_python_bundle) is unpacked to app-private storage
 *    before super.onCreate(), version-stamped so a second launch skips it.
 *  - The environment contract is set before any native code runs.
 *  - libmain's SDL_main initializes CPython (site_import deferred), installs
 *    the extension-module finder from the bundle manifest, then imports main.
 */
public class PythonActivity extends SDLActivity {
    private static final String TAG = "kivyforge";

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
            File bundleDir = unpackBundle();
            File appDir = new File(bundleDir, "app");
            Os.setenv("KF_BUNDLE", bundleDir.getAbsolutePath(), true);
            Os.setenv("KF_NATIVE_DIR", getApplicationInfo().nativeLibraryDir, true);
            // pyjnius/Kivy environment contract:
            Os.setenv("ANDROID_ARGUMENT", appDir.getAbsolutePath(), true);
            Os.setenv("ANDROID_APP_PATH", appDir.getAbsolutePath(), true);
            Os.setenv("ANDROID_PRIVATE", getFilesDir().getAbsolutePath(), true);
            Os.setenv("ANDROID_UNPACK", bundleDir.getAbsolutePath(), true);
            Os.setenv("TMPDIR", getCacheDir().getAbsolutePath(), false);
        } catch (Exception e) {
            Log.e(TAG, "bundle unpack failed", e);
            throw new RuntimeException(e);
        }
        super.onCreate(savedInstanceState);
    }

    /** Unpack assets/_python_bundle to filesDir, skipped when VERSION matches. */
    private File unpackBundle() throws Exception {
        File target = new File(getFilesDir(), "_python_bundle");
        File stamp = new File(target, "VERSION");
        String wanted = readAsset("_python_bundle/VERSION");
        if (stamp.exists()) {
            String have = new String(
                Files.readAllBytes(stamp.toPath()), StandardCharsets.UTF_8);
            if (have.equals(wanted)) {
                Log.i(TAG, "bundle up to date (VERSION " + have + "), skipping unpack");
                Os.setenv("KF_UNPACK_SKIPPED", "1", true);
                return target;
            }
        }
        Log.i(TAG, "unpacking bundle...");
        long t0 = System.currentTimeMillis();
        deleteRecursive(target);
        extractAssetDir("_python_bundle", getFilesDir());
        Log.i(TAG, "bundle unpacked in " + (System.currentTimeMillis() - t0) + " ms");
        Os.setenv("KF_UNPACK_SKIPPED", "0", true);
        return target;
    }

    private String readAsset(String path) throws Exception {
        try (InputStream in = getAssets().open(path)) {
            return new String(readAll(in), StandardCharsets.UTF_8);
        }
    }

    private static byte[] readAll(InputStream in) throws Exception {
        java.io.ByteArrayOutputStream bos = new java.io.ByteArrayOutputStream();
        byte[] buf = new byte[65536];
        int n;
        while ((n = in.read(buf)) > 0) bos.write(buf, 0, n);
        return bos.toByteArray();
    }

    private void extractAssetDir(String path, File targetDir) throws Exception {
        String[] names = getAssets().list(path);
        if (names == null) throw new RuntimeException("cannot list asset " + path);
        File subdir = new File(targetDir, path);
        if (!subdir.exists() && !subdir.mkdirs())
            throw new RuntimeException("mkdirs failed: " + subdir);
        for (String name : names) {
            String subPath = path + "/" + name;
            InputStream in;
            try {
                in = getAssets().open(subPath);
            } catch (FileNotFoundException e) {
                extractAssetDir(subPath, targetDir);
                continue;
            }
            try (InputStream input = in;
                 OutputStream out = new FileOutputStream(new File(subdir, name))) {
                byte[] buf = new byte[65536];
                int n;
                while ((n = input.read(buf)) > 0) out.write(buf, 0, n);
            }
        }
    }

    private static void deleteRecursive(File f) {
        if (f.isDirectory()) {
            File[] children = f.listFiles();
            if (children != null) for (File c : children) deleteRecursive(c);
        }
        f.delete();
    }
}
