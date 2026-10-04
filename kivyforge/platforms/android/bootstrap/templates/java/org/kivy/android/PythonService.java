package org.kivy.android;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.os.Build;
import android.os.IBinder;
import android.os.Process;
import android.system.Os;
import android.util.Log;

import java.io.File;
import java.io.FileOutputStream;
import java.nio.charset.StandardCharsets;

/**
 * Base class for the services generated from [[tool.kivy.android.services]]
 * (docs/design/platforms/android/05 §services).
 *
 * Each declared service becomes a subclass that names its Python entry point
 * and, when it is a foreground service, its notification. The manifest gives
 * every service its own android:process, so this runs in a fresh process: it
 * unpacks the bundle, sets the same environment contract the activity does, and
 * starts one interpreter — on a background thread, because the interpreter does
 * not return until the entry point does and blocking a service's main thread is
 * an ANR.
 *
 * There is no SDL here. The service's Python does background work, so only
 * libpython and libmain are loaded; nothing creates a window or a JNIEnv-owning
 * SDL thread. pyjnius therefore finds the VM through JNI_GetCreatedJavaVMs,
 * which apps can reach only on API 31+.
 *
 * The generated subclasses carry p4a's static start/stop signatures, and
 * mService has p4a's name, so code written against p4a's services keeps
 * working once it names the kivyforge class.
 */
public class PythonService extends Service implements Runnable {
    private static final String TAG = "kivyforge";
    // The libpython soname stem, substituted at render time.
    private static final String PYTHON_LIB = "python3.14";

    private static final int NOTIFICATION_ID = 1;

    static final String EXTRA_ARGUMENT = "kivyforge_service_argument";
    static final String EXTRA_ICON = "kivyforge_notification_icon";
    static final String EXTRA_TITLE = "kivyforge_notification_title";
    static final String EXTRA_TEXT = "kivyforge_notification_text";

    /** The service running in this process, set before its Python starts. */
    public static PythonService mService = null;

    private boolean mStarted = false;
    private Thread mThread = null;
    private String mIconOverride = null;
    private String mTitleOverride = null;
    private String mTextOverride = null;

    // --- called by the generated subclasses' static start/stop ------------- #

    /**
     * Start {@code cls}. A foreground service goes through
     * startForegroundService, which Android 8+ requires for a service that
     * calls startForeground once started from the background. Null or empty
     * notification values keep the ones from pyproject.toml.
     */
    protected static void startPythonService(
            Context ctx,
            Class<? extends PythonService> cls,
            boolean foreground,
            String smallIconName,
            String contentTitle,
            String contentText,
            String pythonServiceArgument) {
        Intent intent = new Intent(ctx, cls);
        intent.putExtra(EXTRA_ARGUMENT, pythonServiceArgument);
        putIfSet(intent, EXTRA_ICON, smallIconName);
        putIfSet(intent, EXTRA_TITLE, contentTitle);
        putIfSet(intent, EXTRA_TEXT, contentText);
        if (foreground && Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            ctx.startForegroundService(intent);
        } else {
            ctx.startService(intent);
        }
    }

    protected static void stopPythonService(
            Context ctx, Class<? extends PythonService> cls) {
        ctx.stopService(new Intent(ctx, cls));
    }

    private static void putIfSet(Intent intent, String key, String value) {
        if (value != null && !value.isEmpty()) {
            intent.putExtra(key, value);
        }
    }

    // --- overridden by the generated subclass ------------------------------ #

    /** The service's [[services]] name, used for logging + the ready marker. */
    protected String getServiceName() {
        return getClass().getSimpleName();
    }

    /** The Python module this service imports (its own entry_point). */
    protected String getEntryPoint() {
        return "main";
    }

    protected boolean isForeground() {
        return false;
    }

    protected String getChannelId() {
        return "kivyforge_service";
    }

    protected String getChannelName() {
        return "Background service";
    }

    protected String getNotificationTitle() {
        return getServiceName();
    }

    protected String getNotificationText() {
        return "";
    }

    /** A drawable resource name for the notification icon, or null for none. */
    protected String getNotificationIcon() {
        return null;
    }

    // --- service lifecycle ------------------------------------------------- #

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        if (intent != null) {
            mIconOverride = intent.getStringExtra(EXTRA_ICON);
            mTitleOverride = intent.getStringExtra(EXTRA_TITLE);
            mTextOverride = intent.getStringExtra(EXTRA_TEXT);
        }
        if (isForeground()) {
            // Mandatory on Android 14+: a foreground service that does not
            // call startForeground() promptly is killed by the OS.
            startForegroundNotification();
        }
        if (!mStarted) {
            mStarted = true;
            String argument = intent == null
                ? null : intent.getStringExtra(EXTRA_ARGUMENT);
            try {
                prepare(argument);
            } catch (Exception e) {
                Log.e(TAG, "service " + getServiceName() + " failed to prepare", e);
                stopSelf();
                return START_NOT_STICKY;
            }
            mThread = new Thread(this, "python-service-" + getServiceName());
            mThread.start();
        }
        // Deliberately not sticky: a crash-looping service that the OS keeps
        // restarting is worse than one that stays down and is visible as down.
        return START_NOT_STICKY;
    }

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }

    /**
     * The interpreter thread cannot be interrupted, so stopping the service
     * ends its process (each service has its own android:process). Without
     * this, stop() would leave the Python code running.
     */
    @Override
    public void onDestroy() {
        super.onDestroy();
        if (mService == this) {
            mService = null;
        }
        Process.killProcess(Process.myPid());
    }

    /** Unpack + environment, then the ready-marker path the smoke test polls. */
    private void prepare(String argument) throws Exception {
        File bundleDir = PythonBundle.unpack(this);
        PythonBundle.setEnvironment(this, bundleDir, getEntryPoint());
        // p4a convention, kept so existing service code keeps working.
        Os.setenv("PYTHON_SERVICE_ARGUMENT", argument == null ? "" : argument, true);
        File marker = markerFile(this, getServiceName());
        marker.delete();
        Os.setenv("KF_SERVICE_MARKER", marker.getAbsolutePath(), true);
    }

    /** Where the interpreter records that it came up (android/06 --smoke). */
    public static File markerFile(Service service, String name) {
        return new File(service.getFilesDir(), "kivyforge_service_" + name + ".txt");
    }

    @Override
    public void run() {
        Log.i(TAG, "service " + getServiceName() + ": starting " + getEntryPoint());
        mService = this;
        try {
            System.loadLibrary(PYTHON_LIB);
            System.loadLibrary("main");
            int rc = nativeStart();
            Log.i(TAG, "service " + getServiceName() + " returned " + rc);
        } catch (UnsatisfiedLinkError e) {
            Log.e(TAG, "service " + getServiceName() + ": native start failed", e);
            recordFailure(e.toString());
        } finally {
            stopSelf();
        }
    }

    private void recordFailure(String detail) {
        File marker = markerFile(this, getServiceName());
        try (FileOutputStream out = new FileOutputStream(marker, true)) {
            out.write(("SERVICE_START_FAILED " + detail + "\n")
                .getBytes(StandardCharsets.UTF_8));
        } catch (Exception ignored) {
            // The marker is diagnostics; losing it must not mask the real error.
        }
    }

    private void startForegroundNotification() {
        NotificationManager manager = getSystemService(NotificationManager.class);
        Notification.Builder builder;
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            NotificationChannel channel = new NotificationChannel(
                getChannelId(), getChannelName(), NotificationManager.IMPORTANCE_LOW);
            manager.createNotificationChannel(channel);
            builder = new Notification.Builder(this, getChannelId());
        } else {
            builder = new Notification.Builder(this);
        }
        builder.setContentTitle(
            mTitleOverride != null ? mTitleOverride : getNotificationTitle());
        builder.setContentText(
            mTextOverride != null ? mTextOverride : getNotificationText());
        builder.setSmallIcon(notificationIconResource());
        startForeground(NOTIFICATION_ID, builder.build());
    }

    private int notificationIconResource() {
        String icon = mIconOverride != null ? mIconOverride : getNotificationIcon();
        if (icon != null) {
            int id = getResources().getIdentifier(icon, "drawable", getPackageName());
            if (id == 0) {
                id = getResources().getIdentifier(icon, "mipmap", getPackageName());
            }
            if (id != 0) {
                return id;
            }
            Log.w(TAG, "notification icon " + icon + " not found; using the launcher");
        }
        return getApplicationInfo().icon;
    }

    /** Implemented in libmain (cpp/main.c): brings up CPython in this process. */
    private native int nativeStart();
}
