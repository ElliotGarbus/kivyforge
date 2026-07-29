/* Kivyforge native launcher (libmain.so), from the Phase-0 prototype.
 *
 * Two callers, one sequence:
 *  - SDL calls SDL_main() on its own thread after SDLActivity has loaded the
 *    SDL family + libpython + this library. By that point PythonActivity has
 *    unpacked the bundle and set the environment contract.
 *  - PythonService calls nativeStart() from its own background thread, in its
 *    own process, after doing the same unpack + environment setup. No SDL is
 *    loaded there; nothing below needs it.
 *
 * This implements the 05-bootstrap-android.md launch sequence steps 4-6:
 * PyConfig with site_import deferred and explicit module search paths,
 * finder installation from the bundle manifest, site + addsitedir, then
 * the entry-point import. Everything is read from the environment, so these
 * sources carry no project-specific values.
 */
#include <android/log.h>
#include <jni.h>
#include <Python.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define TAG "kivyforge"
#define LOGI(...) __android_log_print(ANDROID_LOG_INFO, TAG, __VA_ARGS__)
#define LOGE(...) __android_log_print(ANDROID_LOG_ERROR, TAG, __VA_ARGS__)

static int fail_status(const char *where, PyStatus status) {
    LOGE("%s failed: %s", where, status.err_msg ? status.err_msg : "(no message)");
    return 1;
}

/* Initialize CPython from the unpacked bundle and import the entry point.
 * Returns 0 on success. Shared by SDL_main and the service entry. */
static int kf_start_python(void) {
    const char *bundle = getenv("KF_BUNDLE");
    const char *native_dir = getenv("KF_NATIVE_DIR");
    if (!bundle || !native_dir) {
        LOGE("KF_BUNDLE / KF_NATIVE_DIR not set");
        return 1;
    }
    LOGI("launcher: bundle=%s native=%s", bundle, native_dir);

    char stdlib_path[1024], bootstrap_path[1024], app_path[1024], sp_path[1024];
    snprintf(stdlib_path, sizeof stdlib_path, "%s/stdlib", bundle);
    snprintf(bootstrap_path, sizeof bootstrap_path, "%s/bootstrap", bundle);
    snprintf(app_path, sizeof app_path, "%s/app", bundle);
    snprintf(sp_path, sizeof sp_path, "%s/site-packages", bundle);

    PyPreConfig pre;
    PyPreConfig_InitPythonConfig(&pre);
    pre.utf8_mode = 1;
    PyStatus status = Py_PreInitialize(&pre);
    if (PyStatus_Exception(status)) return fail_status("Py_PreInitialize", status);

    PyConfig config;
    PyConfig_InitPythonConfig(&config);
    config.buffered_stdio = 0;
    config.install_signal_handlers = 1;
    config.site_import = 0;             /* deferred: finder first, then site */
    /* No use_system_logger field on the 3.14 Android build: CPython redirects
     * the Python-level sys.stdout/stderr to logcat itself (per the runtime
     * testbed). Finding for the docs: this is automatic on Android. */
    /* Explicit search paths: bypass getpath landmark discovery entirely.
     * The kivyforge bundle is its own layout, not a prefix. */
    config.module_search_paths_set = 1;
    wchar_t *wpaths[3];
    const char *paths[3] = { stdlib_path, bootstrap_path, app_path };
    for (int i = 0; i < 3; i++) {
        wpaths[i] = Py_DecodeLocale(paths[i], NULL);
        status = PyWideStringList_Append(&config.module_search_paths, wpaths[i]);
        if (PyStatus_Exception(status))
            return fail_status("module_search_paths", status);
    }
    status = PyConfig_SetBytesString(&config, &config.home, bundle);
    if (PyStatus_Exception(status)) return fail_status("home", status);
    status = PyConfig_SetBytesString(&config, &config.prefix, bundle);
    if (PyStatus_Exception(status)) return fail_status("prefix", status);
    status = PyConfig_SetBytesString(&config, &config.exec_prefix, bundle);
    if (PyStatus_Exception(status)) return fail_status("exec_prefix", status);
    status = PyConfig_SetBytesString(&config, &config.program_name, "kivyforge-app");
    if (PyStatus_Exception(status)) return fail_status("program_name", status);

    status = Py_InitializeFromConfig(&config);
    PyConfig_Clear(&config);
    if (PyStatus_Exception(status))
        return fail_status("Py_InitializeFromConfig", status);
    LOGI("launcher: interpreter up");

    /* Step 5: finder, then site, then pip-deps site dir, then the entry point
     * named by KF_ENTRY_POINT. When KIVYFORGE_SELFTEST is set (the instrumented
     * contract test's intent extra, forwarded to the env by PythonActivity),
     * run the inert self-test hook instead of the app entry point.
     *
     * KF_SERVICE_MARKER, when set, names a file the interpreter stamps once it
     * is up and stamps again if the entry-point import raises — the signal the
     * generated service contract test polls (a service entry point normally
     * never returns, so there is nothing else to wait for). */
    const char *selftest = getenv("KIVYFORGE_SELFTEST");
    char code[4096];
    snprintf(code, sizeof code,
        "import _kivyforge_bootstrap\n"
        "_kivyforge_bootstrap.install(%s'%s/ext_manifest.json', %s'%s')\n"
        "import site\n"
        "site.main()\n"
        "site.addsitedir(%s'%s')\n"
        "import importlib, os, traceback\n"
        "_marker = os.environ.get('KF_SERVICE_MARKER')\n"
        "if _marker:\n"
        "    with open(_marker, 'w') as _f:\n"
        "        _f.write('SERVICE_READY\\n')\n"
        "try:\n"
        "    if %d:\n"
        "        import _kivyforge_selftest\n"
        "        _kivyforge_selftest.run()\n"
        "    else:\n"
        "        importlib.import_module(os.environ.get('KF_ENTRY_POINT') or 'main')\n"
        "except Exception:\n"
        "    traceback.print_exc()\n"
        "    if _marker:\n"
        "        with open(_marker, 'a') as _f:\n"
        "            _f.write('SERVICE_ENTRY_FAILED\\n')\n"
        "    raise SystemExit(1)\n",
        "r", bootstrap_path, "r", native_dir, "r", sp_path,
        (selftest && selftest[0] == '1') ? 1 : 0);
    int rc = PyRun_SimpleString(code);
    LOGI("launcher: entry-point import returned %d", rc);

    /* Keep the process alive briefly so instrumentation/logcat settle, then
     * finalize. A real app never reaches here while Kivy runs its loop. */
    Py_Finalize();
    return rc == 0 ? 0 : 1;
}

/* SDL's Java glue dlopens libmain.so and dlsyms "SDL_main" — the symbol must
 * be exported regardless of compiler visibility defaults. */
__attribute__((visibility("default")))
int SDL_main(int argc, char *argv[]) {
    return kf_start_python();
}

/* org.kivy.android.PythonService.nativeStart(): the same sequence for a
 * generated service's process. Resolved by JNI name, so it must be exported. */
__attribute__((visibility("default")))
JNIEXPORT jint JNICALL
Java_org_kivy_android_PythonService_nativeStart(JNIEnv *env, jobject thiz) {
    (void)env;
    (void)thiz;
    return (jint)kf_start_python();
}
