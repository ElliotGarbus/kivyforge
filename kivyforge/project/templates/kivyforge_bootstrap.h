/*
 * kivyforge bootstrap — public header.
 *
 * Generated projects include this in main.m to call kivyforge_main().
 * All SDL and CPython implementation details live in kivyforge_bootstrap.m,
 * keeping the generated main.m stable across Kivy dependency changes.
 */
#ifndef KIVYFORGE_BOOTSTRAP_H
#define KIVYFORGE_BOOTSTRAP_H

/**
 * Start a kivyforge application.
 *
 * Sets up CPython using the bundle layout created by `kivyforge build` and
 * imports @p entry_module.  When SDL3 is available (Kivy apps) the UIKit
 * lifecycle is driven by SDL_RunApp; otherwise Python runs directly on the
 * main thread (headless) — selected at compile time, transparent to the caller.
 *
 * @param argc          Forwarded from main().
 * @param argv          Forwarded from main().
 * @param entry_module  Python module to import (e.g. "myapp.main").
 * @param app_dir       Bundle-relative name of the app directory ("app").
 * @param python_ver    Python major.minor version string (e.g. "3.15").
 * @return              Exit status.
 */
int kivyforge_main(
    int         argc,
    char       *argv[],
    const char *entry_module,
    const char *app_dir,
    const char *python_ver
);

#endif /* KIVYFORGE_BOOTSTRAP_H */
