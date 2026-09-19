/*
 * kivyforge_bootstrap.m — dual-mode iOS bootstrap.
 *
 * When SDL3 is available (Kivy wheel embedded in Frameworks/) SDL_RunApp
 * drives the UIKit lifecycle.  When SDL3 is absent (pure-Python / no-Kivy
 * apps) Python runs without SDL.  The path is chosen at compile time by
 * __has_include so the same source file works in both configurations.
 *
 * Python headers  → Python.xcframework (always present)
 * SDL3 headers    → Frameworks/SDL3.xcframework (only for Kivy apps)
 *
 * HEADER_SEARCH_PATHS is managed by `kivyforge build`; it adds SDL3 paths
 * only when SDL3.xcframework is present, which is exactly the condition
 * __has_include tests.
 *
 * Build flags (set by `kivyforge build` via GCC_PREPROCESSOR_DEFINITIONS):
 *
 *   KIVYFORGE_REQUIRES_SDL=1
 *       Set for Kivy apps.  If SDL3 headers are missing the build FAILS
 *       instead of silently falling back to the headless path (which would
 *       produce an app that launches but can never open a window).
 *
 *   KIVYFORGE_HEADLESS_UIKIT=1
 *       Headless path only.  Runs Python from a minimal UIApplicationDelegate
 *       after launch completes, instead of directly from main().  Default is
 *       0 (direct run).  See the comment on the headless path for the trade-off.
 */

/* ── common ─────────────────────────────────────────────────────────────── */
#import <Foundation/Foundation.h>
#import <UIKit/UIKit.h>
#include <Python.h>
#include "kivyforge_bootstrap.h"
#include "kivyforge_native_modules.h"

#ifndef KIVYFORGE_HEADLESS_UIKIT
#define KIVYFORGE_HEADLESS_UIKIT 0
#endif

#if defined(KIVYFORGE_REQUIRES_SDL) && !__has_include(<SDL3/SDL_main.h>)
#error "Kivy app selected (KIVYFORGE_REQUIRES_SDL) but SDL3 headers were not found. Check that SDL3.xcframework is embedded and HEADER_SEARCH_PATHS includes it."
#endif

typedef struct {
    const char *entry_module;
    const char *app_dir;
    const char *python_ver;
} _BootstrapArgs;

static _BootstrapArgs _g_args;

__attribute__((noreturn))
static void _crash(NSString *message) {
    NSLog(@"kivyforge bootstrap fatal: %@", message);
    exit(1);
}

/* Convert a C string to NSString, crashing with a clear message if it is
 * NULL or not valid UTF-8 (stringWithUTF8String: returns nil in that case,
 * and stringByAppendingPathComponent:nil would throw). */
static NSString *_ns(const char *s, const char *what) {
    NSString *r = s ? [NSString stringWithUTF8String:s] : nil;
    if (r == nil) {
        _crash([NSString stringWithFormat:
            @"missing or invalid UTF-8 string for %s", what]);
    }
    return r;
}

/* Abort with the interpreter's own error message when a PyStatus is bad. */
static void _check(PyStatus status, const char *what) {
    if (PyStatus_Exception(status)) {
        _crash([NSString stringWithFormat:@"%s failed: %s", what,
                status.err_msg ? status.err_msg : "unknown error"]);
    }
}

/* Add every package-contributed native module to the interpreter's inittab.
 * Failing loudly here is deliberate: the alternative is an app that starts,
 * imports a same-named typing stub the package ships for off-device editing,
 * and returns None from every call.
 *
 * kivyforge_native_modules MUST be terminated by a {NULL, NULL} sentinel,
 * even when no package contributes a module (the generator has to emit it). */
static void kivyforge_register_native_modules(void) {
    for (const KivyforgeNativeModule *m = kivyforge_native_modules; m->name; ++m) {
        if (PyImport_AppendInittab(m->name, m->initfunc) == -1) {
            _crash([NSString stringWithFormat:
                @"PyImport_AppendInittab failed for native module \"%s\"", m->name]);
        }
    }
}

/* site.addsitedir(path) through the C API — no source-string interpolation,
 * so quotes or backslashes in the path cannot break it. */
static void _add_site_dir(NSString *path) {
    PyObject *site = PyImport_ImportModule("site");
    PyObject *result = site
        ? PyObject_CallMethod(site, "addsitedir", "s", [path UTF8String])
        : NULL;
    if (result == NULL) {
        PyErr_Print();
        _crash(@"failed to add pip-deps as a site directory");
    }
    Py_DECREF(result);
    Py_DECREF(site);
}

/* Run the entry module the way `python -m <module>` would, i.e. with
 * __name__ == "__main__", so `if __name__ == "__main__": App().run()`
 * blocks execute.  Plain PyImport_ImportModule would never trigger them. */
static void _run_entry_module(const char *name) {
    if (name == NULL) _crash(@"entry module name is NULL");

    PyObject *runpy  = PyImport_ImportModule("runpy");
    PyObject *fn     = runpy ? PyObject_GetAttrString(runpy, "run_module") : NULL;
    PyObject *args   = fn ? Py_BuildValue("(s)", name) : NULL;
    PyObject *kwargs = args
        ? Py_BuildValue("{s:s,s:O}", "run_name", "__main__",
                                     "alter_sys", Py_True)
        : NULL;
    PyObject *result = kwargs ? PyObject_Call(fn, args, kwargs) : NULL;

    if (result == NULL) {
        PyErr_Print();  /* a SystemExit raised by the app exits here, as usual */
        _crash([NSString stringWithFormat:
            @"failed to run entry module \"%s\"", name]);
    }

    Py_DECREF(result);
    Py_XDECREF(kwargs);
    Py_XDECREF(args);
    Py_XDECREF(fn);
    Py_XDECREF(runpy);
}

/* Shared Python initialisation — no SDL dependency. */
static void _run_python(void) {
    NSString *resourcePath = [[NSBundle mainBundle] resourcePath];
    if (resourcePath == nil) _crash(@"main bundle has no resourcePath");

    NSString *pythonHome = [resourcePath stringByAppendingPathComponent:@"python"];
    NSString *appPath    = [resourcePath stringByAppendingPathComponent:
                               _ns(_g_args.app_dir, "app_dir")];
    NSString *pipDeps    = [resourcePath stringByAppendingPathComponent:@"pip-deps"];
    NSString *pyVer      = _ns(_g_args.python_ver, "python_ver");

    setenv("PYTHONHOME", [pythonHome UTF8String], 1);
    /* Force Kivy's platform detection to iOS. */
    setenv("KIVY_BUILD", "ios", 1);

    NSString *stdlib   = [pythonHome stringByAppendingPathComponent:
                              [@"lib/python" stringByAppendingString:pyVer]];
    NSString *dynload  = [stdlib stringByAppendingPathComponent:@"lib-dynload"];
    /* stdlib deliberately comes before appPath: an app module named after a
     * stdlib module (types.py, code.py, ...) must not break interpreter startup. */
    NSString *pythonPath = [@[stdlib, dynload, appPath]
                                componentsJoinedByString:@":"];
    setenv("PYTHONPATH", [pythonPath UTF8String], 1);

    PyPreConfig preconfig;
    PyPreConfig_InitIsolatedConfig(&preconfig);
    preconfig.utf8_mode = 1;
    _check(Py_PreInitialize(&preconfig), "Py_PreInitialize");

    /* Register package-contributed native modules into the inittab. This must
     * happen after Py_PreInitialize and before Py_InitializeFromConfig: these
     * modules are compiled into the app target rather than loaded from a
     * shared object, so `import` cannot find them any other way. The table is
     * empty unless packages declared modules (SPEC.md §7.7). */
    kivyforge_register_native_modules();

    PyConfig config;
    PyConfig_InitPythonConfig(&config);
    config.buffered_stdio          = 0;
    config.write_bytecode          = 0;
    config.install_signal_handlers = 1;
    config.use_environment         = 1;

    PyStatus status = PyConfig_SetBytesString(&config, &config.home,
                                              [pythonHome UTF8String]);
    if (PyStatus_Exception(status)) {
        PyConfig_Clear(&config);
        _check(status, "PyConfig_SetBytesString(home)");
    }

    status = Py_InitializeFromConfig(&config);
    PyConfig_Clear(&config);
    _check(status, "Py_InitializeFromConfig");

    _add_site_dir(pipDeps);
    _run_entry_module(_g_args.entry_module);

    Py_Finalize();
}

/* ── SDL3 path — Kivy apps ──────────────────────────────────────────────── */
#if __has_include(<SDL3/SDL_main.h>)

#define SDL_MAIN_HANDLED
#include <SDL3/SDL_main.h>
#include <SDL3/SDL.h>

static int _sdl_callback(int argc, char *argv[]) {
    @autoreleasepool { _run_python(); }
    return 0;
}

int kivyforge_main(
    int         argc,
    char       *argv[],
    const char *entry_module,
    const char *app_dir,
    const char *python_ver)
{
    _g_args.entry_module = entry_module;
    _g_args.app_dir      = app_dir;
    _g_args.python_ver   = python_ver;
    return SDL_RunApp(argc, argv, _sdl_callback, NULL);
}

/* ── headless path — pure-Python / no-Kivy apps ─────────────────────────── */
#else

#if KIVYFORGE_HEADLESS_UIKIT

/*
 * Opt-in mode (KIVYFORGE_HEADLESS_UIKIT=1).  UIApplicationMain owns the
 * process, so iOS sees a normal launch and the launch watchdog is satisfied.
 * Python is deferred to the next main-queue turn so that
 * didFinishLaunching returns immediately, and the process exits when
 * Python finishes.
 *
 * Trade-off: this brings back the "UIScene lifecycle will soon be required"
 * log and CoreAnimation launch measurements that the default mode avoids.
 */
@interface KFHeadlessDelegate : UIResponder <UIApplicationDelegate>
@end

@implementation KFHeadlessDelegate
- (BOOL)application:(UIApplication *)application
    didFinishLaunchingWithOptions:(NSDictionary *)launchOptions
{
    dispatch_async(dispatch_get_main_queue(), ^{
        @autoreleasepool { _run_python(); }
        exit(0);
    });
    return YES;
}
@end

int kivyforge_main(
    int         argc,
    char       *argv[],
    const char *entry_module,
    const char *app_dir,
    const char *python_ver)
{
    _g_args.entry_module = entry_module;
    _g_args.app_dir      = app_dir;
    _g_args.python_ver   = python_ver;
    @autoreleasepool {
        return UIApplicationMain(argc, argv, nil,
                                 NSStringFromClass([KFHeadlessDelegate class]));
    }
}

#else /* default: run Python directly from main() */

/*
 * Default mode.  Python runs directly on the main thread and UIApplicationMain
 * is NOT called, which avoids the UIScene warning and the CoreAnimation
 * app-launch measurements that can never complete for an app that never
 * presents a first frame.
 *
 * Caveat: the process never completes an iOS launch.  That is fine for short
 * console-style runs on the simulator or in test harnesses, but on a physical
 * device the launch watchdog may kill a long-running app.  Long-running
 * headless apps should build with KIVYFORGE_HEADLESS_UIKIT=1.
 */
int kivyforge_main(
    int         argc,
    char       *argv[],
    const char *entry_module,
    const char *app_dir,
    const char *python_ver)
{
    (void)argc;
    (void)argv;
    _g_args.entry_module = entry_module;
    _g_args.app_dir      = app_dir;
    _g_args.python_ver   = python_ver;
    @autoreleasepool { _run_python(); }
    return 0;
}

#endif /* KIVYFORGE_HEADLESS_UIKIT */

#endif /* __has_include(<SDL3/SDL_main.h>) */
