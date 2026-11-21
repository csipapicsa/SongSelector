"""Find the app's main window on an X display and close it like its close button would (scripts/verify_release.sh).

    python3 scripts/x11_window.py wait PREFIX SECONDS   prints the id of a mapped top-level window whose title starts
                                                        with PREFIX, once there is one (exit 1 after SECONDS)
    python3 scripts/x11_window.py close WINDOW_ID       sends it WM_DELETE_WINDOW

Plain ctypes on libX11, so it runs with the system's Python and needs no window manager (Xvfb has none). Without one
the app's windows are direct children of the root window.
"""
import ctypes
import ctypes.util
import sys
import time

Window = Atom = ctypes.c_ulong
IS_VIEWABLE, CLIENT_MESSAGE, ANY_PROPERTY_TYPE = 2, 33, 0


class XWindowAttributes(ctypes.Structure):
    _fields_ = [('x', ctypes.c_int), ('y', ctypes.c_int), ('width', ctypes.c_int), ('height', ctypes.c_int),
                ('border_width', ctypes.c_int), ('depth', ctypes.c_int), ('visual', ctypes.c_void_p),
                ('root', Window), ('class_', ctypes.c_int), ('bit_gravity', ctypes.c_int),
                ('win_gravity', ctypes.c_int), ('backing_store', ctypes.c_int), ('backing_planes', ctypes.c_ulong),
                ('backing_pixel', ctypes.c_ulong), ('save_under', ctypes.c_int), ('colormap', ctypes.c_ulong),
                ('map_installed', ctypes.c_int), ('map_state', ctypes.c_int), ('all_event_masks', ctypes.c_long),
                ('your_event_mask', ctypes.c_long), ('do_not_propagate_mask', ctypes.c_long),
                ('override_redirect', ctypes.c_int), ('screen', ctypes.c_void_p)]


class XClientMessageEvent(ctypes.Structure):
    _fields_ = [('type', ctypes.c_int), ('serial', ctypes.c_ulong), ('send_event', ctypes.c_int),
                ('display', ctypes.c_void_p), ('window', Window), ('message_type', Atom), ('format', ctypes.c_int),
                ('data', ctypes.c_long * 5)]


class XEvent(ctypes.Union):
    _fields_ = [('xclient', XClientMessageEvent), ('pad', ctypes.c_long * 24)]


x11 = ctypes.cdll.LoadLibrary(ctypes.util.find_library('X11') or 'libX11.so.6')
x11.XOpenDisplay.restype = ctypes.c_void_p
x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
x11.XDefaultRootWindow.restype = Window
x11.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
x11.XInternAtom.restype = Atom
x11.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
x11.XQueryTree.argtypes = [ctypes.c_void_p, Window, ctypes.POINTER(Window), ctypes.POINTER(Window),
                           ctypes.POINTER(ctypes.POINTER(Window)), ctypes.POINTER(ctypes.c_uint)]
x11.XGetWindowAttributes.argtypes = [ctypes.c_void_p, Window, ctypes.POINTER(XWindowAttributes)]
x11.XGetWindowProperty.argtypes = [ctypes.c_void_p, Window, Atom, ctypes.c_long, ctypes.c_long, ctypes.c_int, Atom,
                                   ctypes.POINTER(Atom), ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_ulong),
                                   ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.POINTER(ctypes.c_ubyte))]
x11.XSendEvent.argtypes = [ctypes.c_void_p, Window, ctypes.c_int, ctypes.c_long, ctypes.POINTER(XEvent)]
x11.XFree.argtypes = [ctypes.c_void_p]
x11.XFlush.argtypes = [ctypes.c_void_p]


def title(display, window):
    """_NET_WM_NAME (Qt sets it, UTF-8), else WM_NAME; '' without either."""
    for name in (b'_NET_WM_NAME', b'WM_NAME'):
        kind, form, count, after = Atom(), ctypes.c_int(), ctypes.c_ulong(), ctypes.c_ulong()
        data = ctypes.POINTER(ctypes.c_ubyte)()
        status = x11.XGetWindowProperty(display, window, x11.XInternAtom(display, name, False), 0, 1024, False,
                                        ANY_PROPERTY_TYPE, ctypes.byref(kind), ctypes.byref(form),
                                        ctypes.byref(count), ctypes.byref(after), ctypes.byref(data))
        if status == 0 and data:
            text = ctypes.string_at(data, count.value).decode('utf-8', 'replace') if form.value == 8 else ''
            x11.XFree(data)
            if text:
                return text
    return ''


def find(display, prefix):
    root, parent = Window(), Window()
    children, count = ctypes.POINTER(Window)(), ctypes.c_uint()
    if not x11.XQueryTree(display, x11.XDefaultRootWindow(display), ctypes.byref(root), ctypes.byref(parent),
                          ctypes.byref(children), ctypes.byref(count)):
        return None
    try:
        for index in range(count.value):
            window = children[index]
            attributes = XWindowAttributes()
            if (x11.XGetWindowAttributes(display, window, ctypes.byref(attributes))
                    and attributes.map_state == IS_VIEWABLE and title(display, window).startswith(prefix)):
                return window
    finally:
        if children:
            x11.XFree(children)
    return None


def main(argv):
    display = x11.XOpenDisplay(None)
    if not display:
        sys.exit('Cannot open the X display (DISPLAY is not set? run under xvfb-run).')
    if argv[1] == 'wait':
        prefix, deadline = argv[2], time.monotonic() + float(argv[3])
        while time.monotonic() < deadline:
            window = find(display, prefix)
            if window:
                print(window)
                return 0
            time.sleep(0.2)
        return 1
    if argv[1] == 'close':
        event = XEvent()
        event.xclient.type = CLIENT_MESSAGE
        event.xclient.window = int(argv[2])
        event.xclient.message_type = x11.XInternAtom(display, b'WM_PROTOCOLS', False)
        event.xclient.format = 32
        event.xclient.data[0] = x11.XInternAtom(display, b'WM_DELETE_WINDOW', False)
        x11.XSendEvent(display, int(argv[2]), False, 0, ctypes.byref(event))
        x11.XFlush(display)
        return 0
    sys.exit(__doc__)


if __name__ == '__main__':
    sys.exit(main(sys.argv))
