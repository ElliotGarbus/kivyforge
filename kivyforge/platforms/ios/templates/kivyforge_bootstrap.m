/*
 * kivyforge_bootstrap.m — dual-mode iOS bootstrap.
 *
 * When SDL3 is available (Kivy wheel embedded in Frameworks/) SDL_RunApp
 * drives the UIKit lifecycle.  When SDL3 is absent, the no-SDL path below
 * runs the entry module and exits.  That path is the smoke-test scaffold
 * used to prove the generated Xcode project before a Kivy dependency was
 * wired up — not a supported headless or console app mode.  The right path
 * is chosen at compile time by __has_include so the same source file works
 * in both configurations without any ifdef noise in generated projects.
 *
 * Python headers  → Python.xcframework (always present)
 * SDL3 headers    → Frameworks/SDL3.xcframework (only for Kivy apps)
 *
 * HEADER_SEARCH_PATHS is managed by `kivyforge build`; it adds SDL3 paths
 * only when SDL3.xcframework is present, which is exactly the condition
 * __has_include tests.
 *
 * Build flag (set by `kivyforge build` via GCC_PREPROCESSOR_DEFINITIONS,
 * platforms/ios/buildsettings.py):
 *
 *   KIVYFORGE_REQUIRES_SDL=1
 *       Set whenever this project stages SDL3.xcframework (i.e. it depends on
 *       Kivy). If SDL3 headers are then missing at compile time — a broken
 *       vendoring step, a manually edited HEADER_SEARCH_PATHS — the build
 *       FAILS with an actionable error instead of silently falling back to
 *       the no-SDL path below, which runs Python and exits and can never
 *       open a window. Credit: PR #1 (kengoon).
 */

/* ── common ─────────────────────────────────────────────────────────────── */
#import <Foundation/Foundation.h>
#import <UIKit/UIKit.h>
#include <Python.h>
#include "kivyforge_bootstrap.h"
#include "kivyforge_native_modules.h"

#if defined(KIVYFORGE_REQUIRES_SDL) && !__has_include(<SDL3/SDL_main.h>)
#error "Kivy app selected (KIVYFORGE_REQUIRES_SDL) but SDL3 headers were not found. Check that SDL3.xcframework is embedded and HEADER_SEARCH_PATHS includes it."
#endif

typedef struct {
    const char *entry_module;
    const char *app_dir;
    const char *python_ver;
} _BootstrapArgs;

static _BootstrapArgs _g_args;

static void _crash(NSString *message) {
    NSLog(@"kivyforge bootstrap fatal: %@", message);
    exit(1);
}

/* Run the entry module the way `python -m <module>` would, i.e. with
 * __name__ == "__main__", so `if __name__ == "__main__": App().run()` blocks
 * execute — the ordinary Python idiom, and the same contract Linux/macOS/
 * Windows already give (docs/design/common/01-pyproject-kivy-spec.md). Plain
 * PyImport_ImportModule (the previous approach here) leaves __name__ as the
 * module's own dotted name and never triggers those blocks. Approach credited
 * to PR #1 (kengoon), which caught this for iOS first. */
static void _run_entry_module(const char *name) {
    PyObject *runpy = PyImport_ImportModule("runpy");
    PyObject *result = runpy
        ? PyObject_CallMethod(runpy, "run_module", "sOsO",
                               name, Py_None, "__main__", Py_True)
        : NULL;

    if (result == NULL) {
        PyErr_Print();  /* a SystemExit raised by the app exits here, as usual */
        _crash([NSString stringWithFormat:
            @"failed to run entry module \"%s\"", name]);
    }

    Py_DECREF(result);
    Py_XDECREF(runpy);
}

/* Add every package-contributed native module to the interpreter's inittab.
 * Failing loudly here is deliberate: the alternative is an app that starts,
 * imports a same-named typing stub the package ships for off-device editing,
 * and returns None from every call. */
static void kivyforge_register_native_modules(void) {
    for (const KivyforgeNativeModule *m = kivyforge_native_modules; m->name; ++m) {
        if (PyImport_AppendInittab(m->name, m->initfunc) == -1) {
            _crash([NSString stringWithFormat:
                @"PyImport_AppendInittab failed for native module \"%s\"", m->name]);
        }
    }
}

/* Shared Python initialisation — no SDL dependency. */
static void _run_python(void) {
    NSString *resourcePath = [[NSBundle mainBundle] resourcePath];
    NSString *pythonHome   = [resourcePath stringByAppendingPathComponent:@"python"];
    NSString *appPath      = [resourcePath stringByAppendingPathComponent:
                                  [NSString stringWithUTF8String:_g_args.app_dir]];
    NSString *pipDeps      = [resourcePath stringByAppendingPathComponent:@"pip-deps"];
    NSString *pyVer        = [NSString stringWithUTF8String:_g_args.python_ver];

    setenv("PYTHONHOME", [pythonHome UTF8String], 1);
    /* sys.platform == "ios" triggers Kivy's iOS code paths. */
    setenv("KIVY_BUILD", "ios", 1);

    NSString *stdlib   = [pythonHome stringByAppendingPathComponent:
                              [@"lib/python" stringByAppendingString:pyVer]];
    NSString *dynload  = [stdlib stringByAppendingPathComponent:@"lib-dynload"];
    NSString *pythonPath = [@[stdlib, dynload, appPath]
                                componentsJoinedByString:@":"];
    setenv("PYTHONPATH", [pythonPath UTF8String], 1);

    PyStatus status;
    PyPreConfig preconfig;
    PyPreConfig_InitIsolatedConfig(&preconfig);
    preconfig.utf8_mode = 1;
    status = Py_PreInitialize(&preconfig);
    if (PyStatus_Exception(status)) _crash(@"Py_PreInitialize failed");

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
    PyConfig_SetBytesString(&config, &config.home, [pythonHome UTF8String]);

    status = Py_InitializeFromConfig(&config);
    PyConfig_Clear(&config);
    if (PyStatus_Exception(status)) _crash(@"Py_InitializeFromConfig failed");

    NSString *addsite = [NSString stringWithFormat:
        @"import site; site.addsitedir(\"%@\")", pipDeps];
    if (PyRun_SimpleString([addsite UTF8String]) != 0)
        _crash(@"failed to add pip-deps as a site directory");

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

/* ── no-SDL path — smoke-test scaffold, not a supported app mode ────────── */
#else

/*
 * Smoke-test scaffold.  While the Xcode project generator was coming
 * together, this path was how a project with no Kivy/SDL dependency could
 * still compile, launch, run the entry module, and exit — proving the
 * project, not offering a headless or console app.
 *
 * Python runs on the main thread, and UIApplicationMain is not called.
 * Calling it starts a UIKit lifecycle this path has no scene and no first
 * frame for, which logs "UIScene lifecycle will soon be required" and
 * leaves a CoreAnimation launch measurement that never completes.  A Kivy
 * app takes the SDL path above, where SDL_RunApp owns that lifecycle.
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

#endif /* __has_include(<SDL3/SDL_main.h>) */
