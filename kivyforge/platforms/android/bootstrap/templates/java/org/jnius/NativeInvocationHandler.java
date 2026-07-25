package org.jnius;
import java.lang.reflect.InvocationHandler;
import java.lang.reflect.Method;

// SPIKE item 1 / kivyforge bootstrap-template simulation.
//
// This file is delivered APP-SIDE (via `android.add_src` in buildozer.spec), NOT
// from the pyjnius wheel. It mirrors how kivyforge will ship
// NativeInvocationHandler.java as a generated bootstrap template alongside
// MainActivity.java / PythonActivity.java, compiled + dex'd by the app's Gradle.
//
// MATCHED-PAIR COUPLING: the `native Object invoke0(...)` signature below is bound
// at runtime (RegisterNatives) by the pyjnius wheel. This class and the wheel's
// invoke0 native-method contract MUST be updated together -- nothing enforces this
// now that the glue no longer ships in the wheel. Keep in sync with
// jnius/jnius_proxy.pxi in the pyjnius source.
public class NativeInvocationHandler implements InvocationHandler {
    static boolean DEBUG = false;
    private long ptr;

    public NativeInvocationHandler(long ptr) {
        this.ptr = ptr;
    }

    public Object invoke(Object proxy, Method method, Object[] args) {
        if ( DEBUG ) {
            String message = "+ java:invoke(<proxy>, " + method + ", " + args;
            System.out.print(message);
            System.out.println(")");
            System.out.flush();
        }

        Object ret = invoke0(proxy, method, args);

        if ( DEBUG ) {
            System.out.print("+ java:invoke returned: ");
            System.out.println(ret);
        }

        return ret;
    }

    public long getPythonObjectPointer() {
        return ptr;
    }

    native Object invoke0(Object proxy, Method method, Object[] args);
}
