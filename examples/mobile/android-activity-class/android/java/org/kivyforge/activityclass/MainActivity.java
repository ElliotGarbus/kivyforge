package org.kivyforge.activityclass;

import android.os.Bundle;
import android.util.Log;

import org.kivy.android.PythonActivity;

/**
 * The app's launcher, named by [tool.kivy.android].main_activity.
 *
 * Code before super.onCreate() runs before the window, SDL and Python exist;
 * code after it runs with the activity created and Python starting on its own
 * thread. This is where an SDK that must be initialised in the activity's
 * onCreate goes.
 */
public class MainActivity extends PythonActivity {
    private static final String TAG = "activityclass";

    /** Set in onCreate; main.py reads it to show the subclass's code ran. */
    public static String createdBy = null;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        Log.i(TAG, "MainActivity.onCreate: before super");
        super.onCreate(savedInstanceState);
        createdBy = getClass().getName();
        Log.i(TAG, "MainActivity.onCreate: after super");
    }
}
