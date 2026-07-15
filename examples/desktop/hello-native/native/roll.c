/* A tiny helper executable: print a single die roll (1..6) to stdout.
 *
 * Staged into the bundle's bin directory (macOS: Contents/Resources/bin; Linux:
 * usr/bin) and invoked by name from the Kivy app via subprocess — which only
 * works because the launcher prepends that bin directory to PATH. This is the
 * "helper executable" consumption path of the
 * [tool.kivy.<platform>.native.binaries] channel. */
#include <stdio.h>
#include <stdlib.h>
#include <time.h>
#if defined(_WIN32)
#include <process.h> /* _getpid (MSVC has no POSIX unistd.h) */
#define getpid _getpid
#else
#include <unistd.h>
#endif

int main(void) {
    srand((unsigned)time(NULL) ^ (unsigned)getpid());
    printf("%d\n", (rand() % 6) + 1);
    return 0;
}
