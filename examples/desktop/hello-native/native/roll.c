/* A tiny helper executable: print a single die roll (1..6) to stdout.
 *
 * Staged into the .app's Contents/Resources/bin and invoked by name from the
 * Kivy app via subprocess — which only works because the launcher prepends that
 * bin directory to PATH. This is the "helper executable" consumption path of
 * the [tool.kivy.macos.native.binaries] channel. */
#include <stdio.h>
#include <stdlib.h>
#include <time.h>
#include <unistd.h>

int main(void) {
    srand((unsigned)time(NULL) ^ (unsigned)getpid());
    printf("%d\n", (rand() % 6) + 1);
    return 0;
}
