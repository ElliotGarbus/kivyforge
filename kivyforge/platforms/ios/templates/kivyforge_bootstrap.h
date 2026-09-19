/*
 * kivyforge bootstrap — public header.
 *
 * Generated projects include this in main.m to call kivyforge_main().
 * All SDL and CPython implementation details live in kivyforge_bootstrap.m,
 * keeping the generated main.m stable across Kivy dependency changes.
 */
#ifndef KIVYFORGE_BOOTSTRAP_H
#define KIVYFORGE_BOOTSTRAP_H

/*
 * extern "C" guards: added so the header also works if someone includes it
 * from an .mm (Objective-C++) or C++ file.  Without them the C++ compiler
 * mangles the name kivyforge_main and the link against the C implementation
 * in kivyforge_bootstrap.m fails.  main.m doesn't need them, but they cost
 * nothing.
 */
#ifdef __cplusplus
extern "C" {
#endif

/**
 * Start a kivyforge application.
 *
 * Sets up CPython using the bundle layout created by `kivyforge build` and
 * runs @p entry_module the way `python -m <module>` would, i.e. with
 * __name__ == "__main__".  Consequences:
 *   - `if __name__ == "__main__":` blocks in the entry module execute.
 *   - Pass a module (e.g. "myapp.main").  If you pass a package, Python runs
 *     that package's __main__.py, and the call fails if it has none.
 *
 * When SDL3 is available (Kivy apps) the UIKit lifecycle is driven by
 * SDL_RunApp.  Otherwise Python runs without SDL (headless).  By default it
 * runs directly on the main thread from main(); building with
 * KIVYFORGE_HEADLESS_UIKIT=1 runs it from a minimal UIApplicationDelegate
 * instead.  The choice is made at compile time and is transparent to the
 * caller.  If the build defines KIVYFORGE_REQUIRES_SDL and the SDL3 headers
 * are missing, compilation fails rather than falling back to headless.
 *
 * Fatal bootstrap errors (bad bundle layout, interpreter init failure, an
 * exception escaping the entry module) are logged and end the process with
 * exit(1) rather than returning.
 *
 * @param argc          Forwarded from main().
 * @param argv          Forwarded from main().
 * @param entry_module  Python module to run (e.g. "myapp.main").
 * @param app_dir       Bundle-relative name of the app directory ("app").
 * @param python_ver    Python major.minor version string (e.g. "3.15").
 * @return              Exit status when it returns: SDL_RunApp's result on the
 *                      Kivy path, or 0 after Python finishes in the default
 *                      headless mode.  With KIVYFORGE_HEADLESS_UIKIT=1 it
 *                      never returns; the process exits when Python finishes.
 */
int kivyforge_main(
    int         argc,
    char       *argv[],
    const char *entry_module,
    const char *app_dir,
    const char *python_ver
);

#ifdef __cplusplus
}
#endif

#endif /* KIVYFORGE_BOOTSTRAP_H */