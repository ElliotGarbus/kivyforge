package org.kivy.android;

import android.content.Context;
import android.system.Os;
import android.util.Log;

import java.io.File;
import java.io.FileNotFoundException;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.io.RandomAccessFile;
import java.nio.channels.FileChannel;
import java.nio.channels.FileLock;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;

/**
 * The asset-bundle unpack + environment contract, shared by every process that
 * starts a kivyforge interpreter (docs/design/platforms/android/05).
 *
 * PythonActivity and PythonService both need exactly this sequence, and a
 * service runs in its own process (android:process=":service_*"), so it unpacks
 * and configures independently rather than inheriting the activity's state.
 * Keeping one implementation is deliberate: the environment contract is the
 * most delicate part of the load model, and two copies would drift.
 */
public class PythonBundle {
    private static final String TAG = "kivyforge";

    /** Unpack assets/_python_bundle to filesDir, skipped when VERSION matches.
     *
     * Serialized across processes: a service starts in its own process and may
     * race the activity here, and two unpacks into the same directory would
     * leave a half-written bundle behind whichever finished first.
     */
    public static File unpack(Context ctx) throws Exception {
        File lock = new File(ctx.getFilesDir(), "_python_bundle.lock");
        try (RandomAccessFile raf = new RandomAccessFile(lock, "rw");
             FileChannel channel = raf.getChannel();
             FileLock held = channel.lock()) {
            return unpackLocked(ctx);
        }
    }

    private static File unpackLocked(Context ctx) throws Exception {
        File target = new File(ctx.getFilesDir(), "_python_bundle");
        File stamp = new File(target, "VERSION");
        String wanted = readAsset(ctx, "_python_bundle/VERSION");
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
        extractAssetDir(ctx, "_python_bundle", ctx.getFilesDir());
        Log.i(TAG, "bundle unpacked in " + (System.currentTimeMillis() - t0) + " ms");
        Os.setenv("KF_UNPACK_SKIPPED", "0", true);
        return target;
    }

    /**
     * Set the environment contract the native launcher and Kivy/pyjnius read.
     * Must run before any native code in the process.
     */
    public static void setEnvironment(Context ctx, File bundleDir, String entryPoint)
            throws Exception {
        File appDir = new File(bundleDir, "app");
        Os.setenv("KF_BUNDLE", bundleDir.getAbsolutePath(), true);
        Os.setenv("KF_NATIVE_DIR", ctx.getApplicationInfo().nativeLibraryDir, true);
        Os.setenv("KF_ENTRY_POINT", entryPoint, true);
        // pyjnius/Kivy environment contract:
        Os.setenv("ANDROID_ARGUMENT", appDir.getAbsolutePath(), true);
        Os.setenv("ANDROID_APP_PATH", appDir.getAbsolutePath(), true);
        Os.setenv("ANDROID_PRIVATE", ctx.getFilesDir().getAbsolutePath(), true);
        Os.setenv("ANDROID_UNPACK", bundleDir.getAbsolutePath(), true);
        Os.setenv("TMPDIR", ctx.getCacheDir().getAbsolutePath(), false);
    }

    private static String readAsset(Context ctx, String path) throws Exception {
        try (InputStream in = ctx.getAssets().open(path)) {
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

    private static void extractAssetDir(Context ctx, String path, File targetDir)
            throws Exception {
        String[] names = ctx.getAssets().list(path);
        if (names == null) throw new RuntimeException("cannot list asset " + path);
        File subdir = new File(targetDir, path);
        if (!subdir.exists() && !subdir.mkdirs())
            throw new RuntimeException("mkdirs failed: " + subdir);
        for (String name : names) {
            String subPath = path + "/" + name;
            InputStream in;
            try {
                in = ctx.getAssets().open(subPath);
            } catch (FileNotFoundException e) {
                extractAssetDir(ctx, subPath, targetDir);
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
