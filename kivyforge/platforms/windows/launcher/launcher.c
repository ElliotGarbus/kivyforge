/*
 * kivyforge Windows onedir launcher (bootloader).
 *
 * A prebuilt, windowed-subsystem native launcher. One binary serves every app:
 * everything app-specific lives in the generated bootstrap module, and the only
 * per-app change to the binary is its icon/version *resources* (patched with
 * rcedit at package time). See docs/design/platforms/windows/bootloader-windows.md.
 *
 * Behavior (spawn-and-wait, NOT exec):
 *   1. Self-locate via GetModuleFileNameW (loop on ERROR_INSUFFICIENT_BUFFER;
 *      never a fixed MAX_PATH); derive the bundle layout from the launcher's own
 *      directory (never trust the CWD).
 *   2. Set a Unicode child environment: PYTHONHOME=<bundle>\python,
 *      PYTHONPATH=<bundle>\app, PYTHONNOUSERSITE=1.
 *   3. Build the child command line
 *      (<bundle>\python\python.exe <bundle>\_kivyforge_bootstrap.py <argv...>)
 *      with the correct CommandLineToArgvW-inverse quoting algorithm.
 *   4. Console handoff: AttachConsole(ATTACH_PARENT_PROCESS). If a parent console
 *      exists (the `kivyforge run` path), inherit its std handles so the child's
 *      output/tracebacks reach the terminal. Otherwise (Explorer double-click),
 *      spawn with CREATE_NO_WINDOW so no console flashes.
 *   5. CreateProcessW with CREATE_SUSPENDED, assign to a kill-on-close Job
 *      object, THEN ResumeThread (so no grandchild escapes the job).
 *   6. WaitForSingleObject -> GetExitCodeProcess -> exit with the child's code.
 *      Close every handle on every path.
 *
 * Linked /SUBSYSTEM:WINDOWS (windowed only; console apps are out of scope).
 */

#ifndef UNICODE
#define UNICODE
#endif
#ifndef _UNICODE
#define _UNICODE
#endif

#include <windows.h>
#include <shellapi.h>
#include <stddef.h>

/* Fixed convention names (see bootloader-windows.md / windows-spec). */
static const wchar_t *PYTHON_REL = L"\\python\\python.exe";
static const wchar_t *BOOTSTRAP_REL = L"\\_kivyforge_bootstrap.py";
static const wchar_t *PYTHONHOME_REL = L"\\python";
static const wchar_t *PYTHONPATH_REL = L"\\app";

/* Exit code for a launcher-internal failure (distinct from any app exit code).
 * 71 == EX_OSERR, matching the macOS/Linux launchers. */
#define LAUNCHER_EX_OSERR 71

/* ----------------------------------------------------------------------------
 * Small heap helpers. On OOM we fail hard with the OS-error exit code; there is
 * no meaningful recovery for a launcher.
 * ------------------------------------------------------------------------- */
static void *xalloc(size_t bytes) {
    void *p = HeapAlloc(GetProcessHeap(), 0, bytes);
    return p;
}

static void xfree(void *p) {
    if (p != NULL) {
        HeapFree(GetProcessHeap(), 0, p);
    }
}

/* ----------------------------------------------------------------------------
 * Self-location: GetModuleFileNameW into a growable buffer. Returns a
 * heap-allocated wide string (caller frees) or NULL on failure.
 * ------------------------------------------------------------------------- */
static wchar_t *module_path(void) {
    DWORD cap = MAX_PATH;
    for (;;) {
        wchar_t *buf = (wchar_t *)xalloc(cap * sizeof(wchar_t));
        if (buf == NULL) {
            return NULL;
        }
        DWORD n = GetModuleFileNameW(NULL, buf, cap);
        if (n == 0) {
            xfree(buf);
            return NULL;
        }
        if (n < cap && GetLastError() != ERROR_INSUFFICIENT_BUFFER) {
            /* n < cap means the name fit (and is NUL-terminated). */
            return buf;
        }
        xfree(buf);
        if (cap > (1 << 20)) {
            /* Runaway guard: no sane path is a million wchars. */
            return NULL;
        }
        cap *= 2;
    }
}

/* Return the length of *path up to (not including) the final backslash — i.e.
 * the directory portion. If there is no backslash, returns 0. */
static size_t dir_len(const wchar_t *path) {
    size_t last = 0;
    for (size_t i = 0; path[i] != L'\0'; i++) {
        if (path[i] == L'\\') {
            last = i;
        }
    }
    return last;
}

/* Concatenate dir[0..dir_count) + suffix into a fresh heap string. */
static wchar_t *join(const wchar_t *dir, size_t dir_count, const wchar_t *suffix) {
    size_t slen = 0;
    while (suffix[slen] != L'\0') {
        slen++;
    }
    wchar_t *out = (wchar_t *)xalloc((dir_count + slen + 1) * sizeof(wchar_t));
    if (out == NULL) {
        return NULL;
    }
    for (size_t i = 0; i < dir_count; i++) {
        out[i] = dir[i];
    }
    for (size_t i = 0; i < slen; i++) {
        out[dir_count + i] = suffix[i];
    }
    out[dir_count + slen] = L'\0';
    return out;
}

/* ----------------------------------------------------------------------------
 * Argv quoting — the exact inverse of CommandLineToArgvW (Daniel Colascione's
 * documented algorithm). Naive double-quoting corrupts paths ending in `\` and
 * any argument containing a `"`. Appends the quoted form of *arg to the buffer.
 * ------------------------------------------------------------------------- */

typedef struct {
    wchar_t *data;
    size_t len;
    size_t cap;
    int oom;
} WBuf;

static void wbuf_init(WBuf *b) {
    b->cap = 256;
    b->len = 0;
    b->oom = 0;
    b->data = (wchar_t *)xalloc(b->cap * sizeof(wchar_t));
    if (b->data == NULL) {
        b->oom = 1;
    }
}

static void wbuf_push(WBuf *b, wchar_t c) {
    if (b->oom) {
        return;
    }
    if (b->len + 1 >= b->cap) {
        size_t ncap = b->cap * 2;
        wchar_t *nd = (wchar_t *)xalloc(ncap * sizeof(wchar_t));
        if (nd == NULL) {
            b->oom = 1;
            return;
        }
        for (size_t i = 0; i < b->len; i++) {
            nd[i] = b->data[i];
        }
        xfree(b->data);
        b->data = nd;
        b->cap = ncap;
    }
    b->data[b->len++] = c;
}

static void wbuf_push_str(WBuf *b, const wchar_t *s) {
    for (size_t i = 0; s[i] != L'\0'; i++) {
        wbuf_push(b, s[i]);
    }
}

/* Append *arg, quoted iff necessary, to *b (per CommandLineToArgvW rules). */
static void append_quoted(WBuf *b, const wchar_t *arg) {
    int needs_quotes = (arg[0] == L'\0');
    for (size_t i = 0; arg[i] != L'\0'; i++) {
        if (arg[i] == L' ' || arg[i] == L'\t' || arg[i] == L'"') {
            needs_quotes = 1;
            break;
        }
    }
    if (!needs_quotes) {
        wbuf_push_str(b, arg);
        return;
    }
    wbuf_push(b, L'"');
    for (size_t i = 0;; i++) {
        size_t backslashes = 0;
        while (arg[i] == L'\\') {
            i++;
            backslashes++;
        }
        if (arg[i] == L'\0') {
            /* Escape all backslashes, but let the terminating quote be added
             * after; the backslashes must not eat that quote. */
            for (size_t k = 0; k < backslashes * 2; k++) {
                wbuf_push(b, L'\\');
            }
            break;
        } else if (arg[i] == L'"') {
            /* Escape all backslashes and the following quote. */
            for (size_t k = 0; k < backslashes * 2 + 1; k++) {
                wbuf_push(b, L'\\');
            }
            wbuf_push(b, arg[i]);
        } else {
            /* Backslashes are not special here. */
            for (size_t k = 0; k < backslashes; k++) {
                wbuf_push(b, L'\\');
            }
            wbuf_push(b, arg[i]);
        }
    }
    wbuf_push(b, L'"');
}

/* ----------------------------------------------------------------------------
 * Entry point. /SUBSYSTEM:WINDOWS with the Unicode CRT startup calls wWinMain.
 * We ignore its args and pull the real command line via GetCommandLineW so we
 * get wide-char argv regardless.
 * ------------------------------------------------------------------------- */
int WINAPI wWinMain(HINSTANCE hInstance, HINSTANCE hPrevInstance,
                    LPWSTR lpCmdLine, int nCmdShow) {
    (void)hInstance;
    (void)hPrevInstance;
    (void)lpCmdLine;
    (void)nCmdShow;

    wchar_t *exe = module_path();
    if (exe == NULL) {
        return LAUNCHER_EX_OSERR;
    }
    size_t bundle_len = dir_len(exe); /* index of the last backslash */

    wchar_t *python = join(exe, bundle_len, PYTHON_REL);
    wchar_t *bootstrap = join(exe, bundle_len, BOOTSTRAP_REL);
    wchar_t *pyhome = join(exe, bundle_len, PYTHONHOME_REL);
    wchar_t *pypath = join(exe, bundle_len, PYTHONPATH_REL);
    if (python == NULL || bootstrap == NULL || pyhome == NULL || pypath == NULL) {
        return LAUNCHER_EX_OSERR;
    }

    /* Child environment: inherit ours, then override the Python isolation vars.
     * SetEnvironmentVariableW mutates this process's block, which the child
     * inherits (we pass a NULL environment to CreateProcessW). */
    SetEnvironmentVariableW(L"PYTHONHOME", pyhome);
    SetEnvironmentVariableW(L"PYTHONPATH", pypath);
    SetEnvironmentVariableW(L"PYTHONNOUSERSITE", L"1");

    /* Reconstruct the child command line: python.exe, the bootstrap, then every
     * forwarded argument (argv[1..]) quoted correctly. */
    int argc = 0;
    LPWSTR *argv = CommandLineToArgvW(GetCommandLineW(), &argc);
    if (argv == NULL) {
        return LAUNCHER_EX_OSERR;
    }
    WBuf cmd;
    wbuf_init(&cmd);
    append_quoted(&cmd, python);
    wbuf_push(&cmd, L' ');
    append_quoted(&cmd, bootstrap);
    for (int i = 1; i < argc; i++) {
        wbuf_push(&cmd, L' ');
        append_quoted(&cmd, argv[i]);
    }
    wbuf_push(&cmd, L'\0');
    LocalFree(argv);
    if (cmd.oom) {
        return LAUNCHER_EX_OSERR;
    }

    /* Console handoff. A windowed-subsystem process does not reliably inherit a
     * parent console's std handles; make the handoff explicit. */
    BOOL attached = AttachConsole(ATTACH_PARENT_PROCESS);
    DWORD creation_flags = CREATE_SUSPENDED;
    STARTUPINFOW si;
    ZeroMemory(&si, sizeof(si));
    si.cb = sizeof(si);
    BOOL inherit_handles = FALSE;
    if (attached) {
        /* Pass the attached terminal's std handles to the console-subsystem
         * child so prints/tracebacks land where the developer is looking. */
        HANDLE hin = GetStdHandle(STD_INPUT_HANDLE);
        HANDLE hout = GetStdHandle(STD_OUTPUT_HANDLE);
        HANDLE herr = GetStdHandle(STD_ERROR_HANDLE);
        si.dwFlags |= STARTF_USESTDHANDLES;
        si.hStdInput = hin;
        si.hStdOutput = hout;
        si.hStdError = herr;
        SetHandleInformation(hin, HANDLE_FLAG_INHERIT, HANDLE_FLAG_INHERIT);
        SetHandleInformation(hout, HANDLE_FLAG_INHERIT, HANDLE_FLAG_INHERIT);
        SetHandleInformation(herr, HANDLE_FLAG_INHERIT, HANDLE_FLAG_INHERIT);
        inherit_handles = TRUE;
    } else {
        /* No parent console (Explorer double-click): suppress the console flash
         * that a console-subsystem python.exe would otherwise create.
         *
         * Why CREATE_NO_WINDOW on python.exe rather than launching pythonw.exe:
         * a single code path serves both entry points. On the `kivyforge run`
         * path we WANT the console-subsystem python.exe so its stdout/stderr and
         * tracebacks attach to the parent terminal (above). Using pythonw.exe for
         * double-click would mean detecting the mode and choosing a different
         * child, and pythonw.exe forfeits that attach-for-diagnostics story. One
         * child + CREATE_NO_WINDOW gives silent double-click AND visible `run`. */
        creation_flags |= CREATE_NO_WINDOW;
    }

    /* A Job object with kill-on-close guarantees the whole child process tree
     * dies with the launcher (Ctrl-C, task kill, crash) — no orphaned python. */
    HANDLE job = CreateJobObjectW(NULL, NULL);
    if (job != NULL) {
        JOBOBJECT_EXTENDED_LIMIT_INFORMATION jeli;
        ZeroMemory(&jeli, sizeof(jeli));
        jeli.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
        SetInformationJobObject(job, JobObjectExtendedLimitInformation, &jeli,
                                sizeof(jeli));
    }

    PROCESS_INFORMATION pi;
    ZeroMemory(&pi, sizeof(pi));
    BOOL ok = CreateProcessW(python,        /* application: the bundled python */
                             cmd.data,      /* full command line */
                             NULL, NULL,    /* default security */
                             inherit_handles,
                             creation_flags,
                             NULL,          /* inherit our (mutated) environment */
                             NULL,          /* inherit CWD; bootstrap sets its own */
                             &si, &pi);
    if (!ok) {
        if (job != NULL) {
            CloseHandle(job);
        }
        return LAUNCHER_EX_OSERR;
    }

    /* Assign to the job while still suspended (closes the grandchild-escape
     * race), THEN resume the main thread. */
    if (job != NULL) {
        AssignProcessToJobObject(job, pi.hProcess);
    }
    ResumeThread(pi.hThread);

    WaitForSingleObject(pi.hProcess, INFINITE);
    DWORD code = LAUNCHER_EX_OSERR;
    GetExitCodeProcess(pi.hProcess, &code);

    CloseHandle(pi.hThread);
    CloseHandle(pi.hProcess);
    if (job != NULL) {
        CloseHandle(job);
    }
    return (int)code;
}
