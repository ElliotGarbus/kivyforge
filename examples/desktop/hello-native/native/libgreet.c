/* A tiny native dynamic library exporting greet().
 *
 * Staged into the .app's Contents/Resources/bin and loaded by absolute path
 * from the Kivy app via ctypes (Path(sys.prefix).parent / "bin"). This is the
 * "vendored dylib" consumption path of the [tool.kivy.macos.native.binaries]
 * channel. */
const char *greet(void) {
    return "Hello from libgreet — a vendored native dylib!";
}
