package org.kivyforge.test;

import static org.junit.Assert.assertTrue;
import static org.junit.Assert.fail;

import android.content.Context;
import android.content.Intent;
import androidx.test.core.app.ApplicationProvider;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import org.junit.Test;
import org.junit.runner.RunWith;

/**
 * The kivyforge contract smoke test (android/06 --smoke).
 *
 * Launches PythonActivity, which runs the app in self-test mode (the
 * KIVYFORGE_SELFTEST flag makes the bootstrap import a known stdlib + wheel
 * extension through the sys.meta_path finder, fire an invoke0 proxy
 * round-trip, and pull the Activity through Kivy's bootstrap contract), then
 * asserts the on-device result markers. No app-specific test code — this
 * validates the load-bearing runtime mechanisms (extension-module finder,
 * invoke0 glue, and the Kivy 3 Activity contract) on a real device/emulator.
 */
@RunWith(AndroidJUnit4.class)
public class KivyforgeContractTest {

    private static final int TIMEOUT_MS = 90_000;
    private static final String RESULT_FILE = "kivyforge_selftest.txt";

    @Test
    public void contractSelfTestPasses() throws Exception {
        Context ctx = ApplicationProvider.getApplicationContext();
        File result = new File(ctx.getFilesDir(), RESULT_FILE);
        if (result.exists() && !result.delete()) {
            fail("could not clear stale self-test result " + result);
        }

        Intent intent = new Intent(ctx, org.kivy.android.PythonActivity.class);
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        intent.putExtra("kivyforge_selftest", true);
        ctx.startActivity(intent);

        long deadline = System.currentTimeMillis() + TIMEOUT_MS;
        String contents = "";
        while (System.currentTimeMillis() < deadline) {
            if (result.exists()) {
                contents = new String(
                    Files.readAllBytes(result.toPath()), StandardCharsets.UTF_8);
                if (contents.contains("SELFTEST_DONE")) {
                    break;
                }
            }
            Thread.sleep(500);
        }

        assertTrue(
            "self-test did not complete within " + TIMEOUT_MS + "ms; got: "
                + contents,
            contents.contains("SELFTEST_DONE"));
        assertTrue(
            "extension-module finder check failed: " + contents,
            contents.contains("EXT_OK"));
        assertTrue(
            "pyjnius invoke0 proxy round-trip failed: " + contents,
            contents.contains("PROXY_OK"));
        assertTrue(
            "Kivy's Android bootstrap contract failed: " + contents,
            contents.contains("KIVY_CONTRACT_OK"));
        assertTrue(
            "self-test reported a failure: " + contents,
            contents.contains("SELFTEST_ALL_OK"));
    }
}
