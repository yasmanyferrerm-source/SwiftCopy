"""Windows integration: start with Windows, right-click "Paste with SwiftCopy",
and taking over Ctrl+V in File Explorer so SwiftCopy does the copying.

Everything here is per-user (HKCU) and needs no admin rights. On other systems
the functions are harmless no-ops so the app and tests still run.
"""
from __future__ import annotations

import os
import sys

from . import shell

IS_WIN = os.name == "nt"

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE = "SwiftCopy"
MENU_VERB = "SwiftCopy.Paste"
MENU_KEYS = [  # (key under Software\Classes, placeholder Explorer passes)
    ("Directory\\Background\\shell\\" + MENU_VERB, "%V"),
    ("Directory\\shell\\" + MENU_VERB, "%1"),
    ("Drive\\shell\\" + MENU_VERB, "%1"),
]


def app_command(*extra: str) -> str:
    target, args = shell.launch_command()
    parts = [f'"{target}"']
    if args:
        parts.append(args)
    parts.extend(extra)
    return " ".join(parts)


def app_icon() -> str:
    target, _ = shell.launch_command()
    return f'"{target}",0'


# ------------------------------------------------------------- registry helpers
if IS_WIN:
    import winreg

    def _get(root, key, name=""):
        try:
            with winreg.OpenKey(root, key) as k:
                return winreg.QueryValueEx(k, name)[0]
        except OSError:
            return None

    def _set(root, key, name, value):
        with winreg.CreateKeyEx(root, key, 0, winreg.KEY_SET_VALUE) as k:
            winreg.SetValueEx(k, name, 0, winreg.REG_SZ, value)

    def _delete_tree(root, key):
        try:
            with winreg.OpenKey(root, key, 0, winreg.KEY_ALL_ACCESS) as k:
                while True:
                    try:
                        sub = winreg.EnumKey(k, 0)
                    except OSError:
                        break
                    _delete_tree(root, key + "\\" + sub)
            winreg.DeleteKey(root, key)
        except FileNotFoundError:
            pass


# ------------------------------------------------------------------ autostart
def autostart_enabled() -> bool:
    return IS_WIN and _get(winreg.HKEY_CURRENT_USER, RUN_KEY, RUN_VALUE) is not None


def set_autostart(on: bool) -> None:
    if not IS_WIN:
        return
    if on:
        _set(winreg.HKEY_CURRENT_USER, RUN_KEY, RUN_VALUE, app_command("--tray"))
    else:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
                winreg.DeleteValue(k, RUN_VALUE)
        except FileNotFoundError:
            pass


# --------------------------------------------------------------- context menu
def context_menu_enabled() -> bool:
    return IS_WIN and _get(winreg.HKEY_CURRENT_USER,
                           "Software\\Classes\\" + MENU_KEYS[0][0]) is not None


def set_context_menu(on: bool) -> None:
    if not IS_WIN:
        return
    hk = winreg.HKEY_CURRENT_USER
    for key, placeholder in MENU_KEYS:
        full = "Software\\Classes\\" + key
        if on:
            _set(hk, full, "", "Paste with SwiftCopy")
            _set(hk, full, "MUIVerb", "Paste with SwiftCopy")
            _set(hk, full, "Icon", app_icon())
            _set(hk, full + r"\command", "", app_command("--paste", f'"{placeholder}"'))
        else:
            _delete_tree(hk, full)


def refresh_registered_paths() -> None:
    """Re-point existing entries at this exe (after an update moves it)."""
    if autostart_enabled():
        set_autostart(True)
    if context_menu_enabled():
        set_context_menu(True)


# ------------------------------------------------------------ desktop folder
def desktop_dir() -> str:
    if IS_WIN:
        import ctypes
        from ctypes import wintypes
        buf = ctypes.create_unicode_buffer(wintypes.MAX_PATH)
        # CSIDL_DESKTOPDIRECTORY = 0x10 (follows OneDrive redirection)
        if ctypes.windll.shell32.SHGetFolderPathW(None, 0x10, None, 0, buf) == 0:
            return buf.value
    return os.path.join(os.path.expanduser("~"), "Desktop")


# ------------------------------------------------- Explorer Ctrl+V takeover
EXPLORER_CLASSES = {"CabinetWClass", "ExploreWClass"}
DESKTOP_CLASSES = {"Progman", "WorkerW"}
# Only take over when the focus is on the file list itself - never while typing
# in the address bar, search box or a rename box (those are Edit / XAML windows).
FILE_VIEW_FOCUS = {"DirectUIHWND", "SysListView32", "SHELLDLL_DefView"}

# explorer_folder() results
FOLDER_OK = "ok"            # a normal folder - SwiftCopy handles it
NOT_A_FOLDER = "special"    # This PC, Recycle Bin, a phone, a zip... - let Windows do it
LOOKUP_FAILED = "failed"    # couldn't ask Explorer - SwiftCopy asks the user instead


def explorer_folder(root_hwnd: int) -> tuple[str | None, str, str]:
    """(folder, result, detail) for the folder shown in an Explorer window's active tab."""
    if not IS_WIN:
        return None, LOOKUP_FAILED, "not Windows"
    import ctypes
    cls = _class_name(root_hwnd)
    if cls in DESKTOP_CLASSES:
        return desktop_dir(), FOLDER_OK, "desktop"
    try:
        import pythoncom
        import win32com.client  # pywin32
    except Exception as e:  # noqa: BLE001
        return None, LOOKUP_FAILED, f"pywin32 not available: {e!r}"
    try:
        pythoncom.CoInitialize()
    except Exception:  # noqa: BLE001 - already initialised on this thread
        pass
    title_buf = ctypes.create_unicode_buffer(512)
    ctypes.windll.user32.GetWindowTextW(root_hwnd, title_buf, 512)
    title = title_buf.value
    matches, seen = [], 0
    try:
        windows = win32com.client.Dispatch("Shell.Application").Windows()
        for i in range(windows.Count):
            try:
                w = windows.Item(i)
                if w is None:
                    continue
                seen += 1
                if int(w.HWND) != int(root_hwnd):
                    continue
                try:
                    path = str(w.Document.Folder.Self.Path)
                except Exception:  # noqa: BLE001 - not a folder view
                    path = ""
                matches.append((str(w.LocationName), path))
            except Exception:  # noqa: BLE001 - a window closing while we look
                continue
    except Exception as e:  # noqa: BLE001
        return None, LOOKUP_FAILED, f"Shell.Application error: {e!r}"
    if not matches:
        return None, LOOKUP_FAILED, f"window not found among {seen} Explorer windows (title {title!r})"
    name, path = matches[0]
    if len(matches) > 1:  # Windows 11 tabs share one window; the title names the active tab
        for n, p in matches:
            if title == n or title.startswith(n + " - "):
                name, path = n, p
                break
    if path and os.path.isdir(path):
        return path, FOLDER_OK, f"tab {name!r}"
    return None, NOT_A_FOLDER, f"tab {name!r} is not a normal folder ({path!r})"


def _class_name(hwnd) -> str:
    import ctypes
    buf = ctypes.create_unicode_buffer(256)
    ctypes.windll.user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


class PasteHook:
    """Catches Ctrl+V in File Explorer / on the desktop when the clipboard holds files
    and calls `notify(root_hwnd)` (from the hook thread - make it thread-safe, e.g. a Qt
    signal). Explorer never sees that Ctrl+V.

    The hook lives on its own thread with its own message loop, so a busy SwiftCopy
    window can never make Windows time it out, and it is re-armed every 30 seconds in
    case Windows dropped it anyway (it does that silently, e.g. after sleep).
    """

    REARM_MS = 30_000

    def __init__(self, notify):
        self.notify = notify
        self._thread = None
        self._thread_id = 0
        self._ready = None
        self._ok = False
        self._holding_v = False
        self.last_decision = ""
        self.armed_count = 0

    @property
    def active(self) -> bool:
        return self._ok and self._thread is not None and self._thread.is_alive()

    def install(self) -> bool:
        if not IS_WIN:
            return False
        if self.active:
            return True
        import threading
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._run, name="SwiftCopy-PasteHook", daemon=True)
        self._thread.start()
        self._ready.wait(3)
        return self.active

    def uninstall(self) -> None:
        if self._thread is not None and self._thread.is_alive() and self._thread_id:
            import ctypes
            ctypes.windll.user32.PostThreadMessageW(self._thread_id, 0x0012, 0, 0)  # WM_QUIT
            self._thread.join(2)
        self._thread = None
        self._ok = False

    def _decide(self, msg: str) -> None:
        self.last_decision = msg
        _log(msg)

    def _run(self) -> None:  # noqa: C901 - one self-contained Win32 thread
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        LRESULT = ctypes.c_ssize_t
        HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)

        class KBDLLHOOKSTRUCT(ctypes.Structure):
            _fields_ = [("vkCode", wintypes.DWORD), ("scanCode", wintypes.DWORD),
                        ("flags", wintypes.DWORD), ("time", wintypes.DWORD),
                        ("dwExtraInfo", ctypes.c_size_t)]

        class GUITHREADINFO(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.DWORD), ("flags", wintypes.DWORD),
                        ("hwndActive", wintypes.HWND), ("hwndFocus", wintypes.HWND),
                        ("hwndCapture", wintypes.HWND), ("hwndMenuOwner", wintypes.HWND),
                        ("hwndMoveSize", wintypes.HWND), ("hwndCaret", wintypes.HWND),
                        ("rcCaret", wintypes.RECT)]

        user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD]
        user32.SetWindowsHookExW.restype = wintypes.HHOOK
        user32.CallNextHookEx.argtypes = [wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
        user32.CallNextHookEx.restype = LRESULT
        user32.UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]
        user32.GetForegroundWindow.restype = wintypes.HWND
        user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
        user32.GetAncestor.restype = wintypes.HWND
        user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.c_void_p]
        user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        user32.GetGUIThreadInfo.argtypes = [wintypes.DWORD, ctypes.POINTER(GUITHREADINFO)]
        user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
        user32.GetAsyncKeyState.restype = ctypes.c_short
        user32.IsClipboardFormatAvailable.argtypes = [wintypes.UINT]
        user32.SetTimer.argtypes = [wintypes.HWND, ctypes.c_size_t, wintypes.UINT, ctypes.c_void_p]
        user32.SetTimer.restype = ctypes.c_size_t
        user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
        kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
        kernel32.GetModuleHandleW.restype = wintypes.HMODULE

        WH_KEYBOARD_LL, WM_KEYDOWN, WM_KEYUP, WM_SYSKEYDOWN, WM_TIMER = 13, 0x100, 0x101, 0x104, 0x113
        VK_V, LLKHF_INJECTED, CF_HDROP = 0x56, 0x10, 15
        VK_CONTROL, VK_SHIFT, VK_MENU, VK_LWIN, VK_RWIN = 0x11, 0x10, 0x12, 0x5B, 0x5C

        def down(vk):
            return user32.GetAsyncKeyState(vk) & 0x8000

        def cls(hwnd):
            buf = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, buf, 256)
            return buf.value

        def check_target():
            """(root_hwnd or None, reason)."""
            fg = user32.GetForegroundWindow()
            if not fg:
                return None, "no foreground window"
            root = user32.GetAncestor(fg, 2) or fg  # GA_ROOT
            root_cls = cls(root)
            if root_cls not in EXPLORER_CLASSES and root_cls not in DESKTOP_CLASSES:
                return None, None  # not Explorer - not our business, don't log
            info = GUITHREADINFO()
            info.cbSize = ctypes.sizeof(GUITHREADINFO)
            tid = user32.GetWindowThreadProcessId(fg, None)
            focus_cls = ""
            if user32.GetGUIThreadInfo(tid, ctypes.byref(info)) and info.hwndFocus:
                focus_cls = cls(info.hwndFocus)
            if focus_cls not in FILE_VIEW_FOCUS:
                return None, f"Explorer focus is on {focus_cls or 'nothing'!r} (not the file list) - left to Windows"
            if not user32.IsClipboardFormatAvailable(CF_HDROP):
                return None, "clipboard has no files - left to Windows"
            return int(root), f"taken: Explorer window {root_cls}, focus {focus_cls}"

        def proc(n_code, w_param, l_param):
            try:
                if n_code == 0:
                    kb = ctypes.cast(l_param, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
                    if kb.vkCode == VK_V and not kb.flags & LLKHF_INJECTED:
                        if w_param in (WM_KEYDOWN, WM_SYSKEYDOWN):
                            if self._holding_v:
                                return 1  # auto-repeat of a paste we already took
                            if (down(VK_CONTROL) and not down(VK_SHIFT) and not down(VK_MENU)
                                    and not down(VK_LWIN) and not down(VK_RWIN)):
                                root, why = check_target()
                                if why:
                                    self._decide("Ctrl+V " + why)
                                if root:
                                    self._holding_v = True
                                    self.notify(root)
                                    return 1  # Explorer never sees this Ctrl+V
                        elif w_param == WM_KEYUP and self._holding_v:
                            self._holding_v = False
            except Exception as e:  # noqa: BLE001 - a hook must never raise
                _log(f"hook error: {e!r}")
            return user32.CallNextHookEx(None, n_code, w_param, l_param)

        cb = HOOKPROC(proc)  # must stay referenced for the life of the hook
        hmod = kernel32.GetModuleHandleW(None)

        def arm(old):
            if old:
                user32.UnhookWindowsHookEx(old)
            h = user32.SetWindowsHookExW(WH_KEYBOARD_LL, cb, hmod, 0)
            if not h:
                _log(f"SetWindowsHookEx failed, error {ctypes.get_last_error()}")
            else:
                self.armed_count += 1
            return h

        self._thread_id = kernel32.GetCurrentThreadId()
        hook = arm(None)
        self._ok = bool(hook)
        if self._ok:
            _log("Ctrl+V takeover is on")
        self._ready.set()
        if not hook:
            return
        user32.SetTimer(None, 0, self.REARM_MS, None)
        msg = wintypes.MSG()
        try:
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message == WM_TIMER:
                    hook = arm(hook) or hook  # Windows may have dropped it silently
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
        finally:
            if hook:
                user32.UnhookWindowsHookEx(hook)
            self._ok = False
            _log("Ctrl+V takeover is off")


def _log(msg: str) -> None:
    from .log import log
    log(msg)


def send_native_paste() -> None:
    """Let Explorer do the paste itself (used when SwiftCopy can't, e.g. 'This PC')."""
    if not IS_WIN:
        return
    import ctypes
    kbd = ctypes.windll.user32.keybd_event
    VK_CONTROL, VK_V, KEYUP = 0x11, 0x56, 0x2
    kbd(VK_CONTROL, 0, 0, 0)
    kbd(VK_V, 0, 0, 0)
    kbd(VK_V, 0, KEYUP, 0)
    kbd(VK_CONTROL, 0, KEYUP, 0)


def frozen() -> bool:
    return bool(getattr(sys, "frozen", False))
