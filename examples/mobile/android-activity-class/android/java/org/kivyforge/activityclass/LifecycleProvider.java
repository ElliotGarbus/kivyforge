package org.kivyforge.activityclass;

import android.app.Activity;
import android.app.Application;
import android.content.ContentProvider;
import android.content.ContentValues;
import android.database.Cursor;
import android.net.Uri;
import android.os.Bundle;
import android.util.Log;

/**
 * Android's route for a library that needs every activity's lifecycle without
 * owning the activity: a provider, which Android creates before the first
 * activity, registering Application.ActivityLifecycleCallbacks.
 *
 * onCreate runs on the main thread at launch, so it registers and returns.
 * Declared through [tool.kivy.android.manifest].extra_application_xml.
 */
public class LifecycleProvider extends ContentProvider {
    private static final String TAG = "activityclass";

    /** The class of the last activity created, for main.py to report. */
    public static String lastCreated = null;

    @Override
    public boolean onCreate() {
        Application app = (Application) getContext().getApplicationContext();
        app.registerActivityLifecycleCallbacks(new Application.ActivityLifecycleCallbacks() {
            @Override
            public void onActivityCreated(Activity activity, Bundle state) {
                lastCreated = activity.getClass().getName();
                Log.i(TAG, "LifecycleProvider: created " + lastCreated);
            }

            @Override public void onActivityStarted(Activity activity) {}
            @Override public void onActivityResumed(Activity activity) {}
            @Override public void onActivityPaused(Activity activity) {}
            @Override public void onActivityStopped(Activity activity) {}
            @Override public void onActivitySaveInstanceState(Activity activity, Bundle state) {}
            @Override public void onActivityDestroyed(Activity activity) {}
        });
        Log.i(TAG, "LifecycleProvider: registered");
        return true;
    }

    @Override
    public Cursor query(Uri uri, String[] projection, String selection,
                        String[] selectionArgs, String sortOrder) {
        return null;
    }

    @Override
    public String getType(Uri uri) {
        return null;
    }

    @Override
    public Uri insert(Uri uri, ContentValues values) {
        return null;
    }

    @Override
    public int delete(Uri uri, String selection, String[] selectionArgs) {
        return 0;
    }

    @Override
    public int update(Uri uri, ContentValues values, String selection,
                      String[] selectionArgs) {
        return 0;
    }
}
