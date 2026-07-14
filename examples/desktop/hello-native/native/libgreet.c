/* A tiny native dynamic library exporting greet().
 *
 * Built as libgreet.dylib on macOS and libgreet.so on Linux, staged into the
 * bundle's bin directory and loaded from the Kivy app via ctypes: by absolute
 * path on macOS (Path(sys.prefix).parent / "bin") and by soname on Linux
 * (ctypes.CDLL("libgreet.so"), via the LD_LIBRARY_PATH append). This is the
 * "vendored library" consumption path of the
 * [tool.kivy.<platform>.native.binaries] channel. */
const char *greet(void) {
    return "Hello from libgreet — a vendored native dylib!";
}
