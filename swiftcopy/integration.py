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
# in the address bar, search box or a rename box.
FILE_VIEW_FOCUS = {"DirectUIHWND", "SysListView32"}


def explorer_folder(root_hwnd: int) -> str | None:
    """Folder shown in the Explorer window (active tab), or None if it isn't a real folder."""
    if not IS_WIN:
        return None
    import ctypes
    cls = _class_name(root_hwnd)
    if cls in DESKTOP_CLASSES:
        return desktop_dir()
    try:
        import win32com.client  # pywin32
    except ImportError:
        return None
    title_buf = ctypes.create_unicode_buffer(512)
    ctypes.windll.user32.GetWindowTextW(root_hwnd, title_buf, 512)
    title = title_buf.value
    matches = []
    try:
        for w in win32com.client.Dispatch("Shell.Application").Windows():
            try:
                if int(w.HWND) != int(root_hwnd):
                    continue
                matches.append((str(w.LocationName), str(w.Document.Folder.Self.Path)))
            except Exception:  # noqa: BLE001 - non-folder views, closing windows
                continue
    except Exception:  # noqa: BLE001
        return None
    if not matches:
        return None
    path = matches[0][1]
    if len(matches) > 1:  # Windows 11 tabs share one window; the title names the active tab
        for name, p in matches:
            if title == name or title.startswith(name + " - "):
                path = p
                break
    return path if os.path.isdir(path) else None


def _class_name(hwnd) -> str:
    import ctypes
    buf = ctypes.create_unicode_buffer(256)
    ctypes.windll.user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


class PasteHook:
    """Low-level keyboard hook that catches Ctrl+V in File Explorer / on the desktop
    when the clipboard holds files, and hands the paste to `on_paste(root_hwnd)`.

    `on_paste` runs later on the Qt thread (via `schedule`). If SwiftCopy can't
    handle the paste it calls `send_native_paste()` so Explorer pastes as usual.
    Must be installed from the GUI thread (it needs that thread's message loop).
    """

    def __init__(self, on_paste, schedule):
        self.on_paste = on_paste
        self.schedule = schedule
        self._hook = None
        self._proc = None
        self._holding_v = False

    @property
    def active(self) -> bool:
        return self._hook is not None

    def install(self) -> bool:
        if not IS_WIN or self._hook:
            return bool(self._hook)
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
        kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
        kernel32.GetModuleHandleW.restype = wintypes.HMODULE

        WH_KEYBOARD_LL, WM_KEYDOWN, WM_KEYUP, WM_SYSKEYDOWN = 13, 0x100, 0x101, 0x104
        VK_V, LLKHF_INJECTED, CF_HDROP = 0x56, 0x10, 15
        VK_CONTROL, VK_SHIFT, VK_MENU, VK_LWIN, VK_RWIN = 0x11, 0x10, 0x12, 0x5B, 0x5C

        def down(vk):
            return user32.GetAsyncKeyState(vk) & 0x8000

        def cls(hwnd):
            buf = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, buf, 256)
            return buf.value

        def wants_paste():
            fg = user32.GetForegroundWindow()
            if not fg:
                return None
            root = user32.GetAncestor(fg, 2) or fg  # GA_ROOT
            root_cls = cls(root)
            if root_cls not in EXPLORER_CLASSES and root_cls not in DESKTOP_CLASSES:
                return None
            info = GUITHREADINFO()
            info.cbSize = ctypes.sizeof(GUITHREADINFO)
            tid = user32.GetWindowThreadProcessId(fg, None)
            if not user32.GetGUIThreadInfo(tid, ctypes.byref(info)) or not info.hwndFocus:
                return None
            if cls(info.hwndFocus) not in FILE_VIEW_FOCUS:
                return None
            if not user32.IsClipboardFormatAvailable(CF_HDROP):
                return None
            return int(root)

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
                                root = wants_paste()
                                if root:
                                    self._holding_v = True
                                    self.schedule(lambda r=root: self.on_paste(r))
                                    return 1  # Explorer never sees this Ctrl+V
                        elif w_param == WM_KEYUP and self._holding_v:
                            self._holding_v = False
            except Exception:  # noqa: BLE001 - a hook must never raise
                pass
            return user32.CallNextHookEx(None, n_code, w_param, l_param)

        self._proc = HOOKPROC(proc)  # keep a reference or it gets garbage-collected
        self._user32 = user32
        self._hook = user32.SetWindowsHookExW(WH_KEYBOARD_LL, self._proc,
                                              kernel32.GetModuleHandleW(None), 0)
        if not self._hook:
            self._proc = None
            return False
        return True

    def uninstall(self) -> None:
        if self._hook:
            self._user32.UnhookWindowsHookEx(self._hook)
            self._hook = None
            self._proc = None


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
