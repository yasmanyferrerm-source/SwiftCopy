"""SwiftCopy's Ctrl+V helper: a tiny separate process that owns the keyboard hook.

Why a separate process: Windows gives a low-level keyboard hook less than a second to
answer each key press and silently removes the hook if it is late even once. Inside the
main app the hook had to share Python with the window and the copy engine, so on a busy
PC it was sometimes late and Windows dropped it ("Ctrl+V stops working after a few
minutes"). Here the hook thread does nothing else, so it always answers instantly.

It also checks itself: every CHECK_MS it sends an invisible F24 key press to itself. If the
hook doesn't see it, Windows removed the hook, so it is installed again straight away.

Started by SwiftCopy as:  SwiftCopy.exe --hook-helper --parent <pid> --pipe <name>
It exits by itself when SwiftCopy closes. No Qt here: only ctypes and pywin32.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time

from . import integration
from .log import log

WM_TIMER, WM_APP = 0x113, 0x8000
WM_KEYDOWN, WM_KEYUP, WM_SYSKEYDOWN, WM_SYSKEYUP = 0x100, 0x101, 0x104, 0x105
VK_V, VK_F24 = 0x56, 0x87
VK_CONTROL, VK_SHIFT, VK_MENU, VK_LWIN, VK_RWIN = 0x11, 0x10, 0x12, 0x5B, 0x5C
LLKHF_INJECTED = 0x10
CF_HDROP = 15
CANARY_FAMILY = 0x5357_0000  # "SW" + this helper's process id: marks our own F24 check presses
CHECK_MS = 5_000
WM_PASSED = WM_APP + 1  # a Ctrl+V in Explorer we left to Windows (logged outside the hook)
REASONS = {1: "no focused control", 2: "focus wasn't on the file list", 3: "clipboard had no files"}
NAV_PANE_FOCUS = {"SysTreeView32"}  # Explorer's left-hand folder tree


# --------------------------------------------------------------------- talking to SwiftCopy
def send_to_app(pipe: str, message: dict) -> bool:
    """Send one JSON message to the main SwiftCopy window (its QLocalServer named pipe)."""
    path = r"\\.\pipe" + "\\" + pipe
    data = json.dumps(message).encode("utf-8")
    for _ in range(40):
        try:
            with open(path, "wb", buffering=0) as f:
                f.write(data)
            return True
        except OSError:
            time.sleep(0.05)  # pipe busy (another message in flight) - try again
    log(f"helper: couldn't reach SwiftCopy on pipe {pipe}")
    return False


def read_clipboard_files() -> tuple[list[str], bool]:
    """Files copied/cut in Explorer: (paths, was_cut)."""
    import win32clipboard
    for _ in range(20):
        try:
            win32clipboard.OpenClipboard()
            break
        except Exception:  # noqa: BLE001 - another app has the clipboard open
            time.sleep(0.05)
    else:
        return [], False
    try:
        if not win32clipboard.IsClipboardFormatAvailable(CF_HDROP):
            return [], False
        paths = list(win32clipboard.GetClipboardData(CF_HDROP))
        cut = False
        fmt = win32clipboard.RegisterClipboardFormat("Preferred DropEffect")
        if win32clipboard.IsClipboardFormatAvailable(fmt):
            raw = win32clipboard.GetClipboardData(fmt)
            if isinstance(raw, (bytes, bytearray)) and len(raw) >= 4:
                cut = bool(int.from_bytes(raw[:4], "little") & 2)
        return paths, cut
    finally:
        win32clipboard.CloseClipboard()


def clear_clipboard() -> None:
    import win32clipboard
    try:
        win32clipboard.OpenClipboard()
        try:
            win32clipboard.EmptyClipboard()
        finally:
            win32clipboard.CloseClipboard()
    except Exception:  # noqa: BLE001
        pass


def handle_paste(pipe: str, root_hwnd: int, status) -> None:
    """Runs on a worker thread so the hook thread stays free."""
    try:
        paths, cut = read_clipboard_files()
        if not paths:
            status("clipboard had no files after all - left to Windows")
            integration.send_native_paste()
            return
        folder, result, detail = integration.explorer_folder(root_hwnd)
        if result == integration.NOT_A_FOLDER:
            status(f"{detail} - left to Windows")
            integration.send_native_paste()  # This PC, a phone, a zip... Windows handles those
            return
        if result == integration.LOOKUP_FAILED:
            status(f"couldn't read Explorer's folder ({detail}) - asked in SwiftCopy")
            send_to_app(pipe, {"type": "explorer_paste", "paths": paths, "dest": None, "move": cut})
            return
        if send_to_app(pipe, {"type": "explorer_paste", "paths": paths, "dest": folder, "move": cut}):
            status(f"{len(paths)} item(s) {'moved' if cut else 'copied'} into {folder} ({detail})")
            if cut:
                clear_clipboard()  # same as Explorer: cut files paste once
        else:
            status("SwiftCopy didn't answer - left to Windows")
            integration.send_native_paste()
    except Exception as e:  # noqa: BLE001
        status(f"error: {e!r} - left to Windows")
        integration.send_native_paste()


# ---------------------------------------------------------------------------- the hook loop
class HookLoop:
    def __init__(self, pipe: str, parent_pid: int):
        self.pipe = pipe
        self.parent_pid = parent_pid
        self.canary_sent = 0.0
        self.canary_seen = True
        self.holding_v = False
        self.rearms = 0
        self.tag = CANARY_FAMILY | (os.getpid() & 0xFFFF)
        self.passed_focus = ""

    def status(self, text: str) -> None:
        log("Ctrl+V " + text)
        threading.Thread(target=send_to_app, args=(self.pipe, {"type": "helper_status", "text": text}),
                         daemon=True).start()

    def run(self) -> int:  # noqa: C901 - one self-contained Win32 loop
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

        class KEYBDINPUT(ctypes.Structure):
            _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                        ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]

        class MOUSEINPUT(ctypes.Structure):  # only here so the INPUT union has the right size
            _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                        ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                        ("dwExtraInfo", ctypes.c_size_t)]

        class _U(ctypes.Union):
            _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT)]

        class INPUT(ctypes.Structure):
            _fields_ = [("type", wintypes.DWORD), ("u", _U)]

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
        user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
        kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
        kernel32.GetModuleHandleW.restype = wintypes.HMODULE
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]

        tid = kernel32.GetCurrentThreadId()
        keep_responsive(kernel32)
        parent = kernel32.OpenProcess(0x00100000, False, self.parent_pid) if self.parent_pid else None  # SYNCHRONIZE

        def down(vk):
            return user32.GetAsyncKeyState(vk) & 0x8000

        def cls(hwnd):
            buf = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, buf, 256)
            return buf.value

        def target():
            """(root Explorer/desktop window, 0) if Ctrl+V should go to SwiftCopy,
            else (None, reason) - reason 0 means 'not Explorer at all'."""
            fg = user32.GetForegroundWindow()
            if not fg:
                return None, 0
            root = user32.GetAncestor(fg, 2) or fg  # GA_ROOT
            root_cls = cls(root)
            if root_cls not in integration.EXPLORER_CLASSES and root_cls not in integration.DESKTOP_CLASSES:
                return None, 0
            info = GUITHREADINFO()
            info.cbSize = ctypes.sizeof(GUITHREADINFO)
            ftid = user32.GetWindowThreadProcessId(fg, None)
            if not user32.GetGUIThreadInfo(ftid, ctypes.byref(info)) or not info.hwndFocus:
                return None, 1
            focus = cls(info.hwndFocus)
            if focus not in integration.FILE_VIEW_FOCUS and focus not in NAV_PANE_FOCUS:
                self.passed_focus = focus
                return None, 2  # typing in the address bar, search box or a rename box
            if not user32.IsClipboardFormatAvailable(CF_HDROP):
                return None, 3
            return int(root), 0

        # The hook callback must be quick and must never do I/O: it only looks at the
        # key and posts a message; everything else happens outside it.
        def proc(n_code, w_param, l_param):
            try:
                if n_code == 0:
                    kb = ctypes.cast(l_param, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
                    if kb.vkCode == VK_F24 and kb.dwExtraInfo == self.tag:
                        self.canary_seen = True
                        return 1  # our own check press - nobody else needs to see it
                    if kb.vkCode == VK_V and not kb.flags & LLKHF_INJECTED:
                        if w_param in (WM_KEYDOWN, WM_SYSKEYDOWN):
                            if self.holding_v:
                                return 1  # key repeat of a paste we already took
                            if (down(VK_CONTROL) and not down(VK_SHIFT) and not down(VK_MENU)
                                    and not down(VK_LWIN) and not down(VK_RWIN)):
                                root, reason = target()
                                if root:
                                    self.holding_v = True
                                    user32.PostThreadMessageW(tid, WM_APP, root, 0)
                                    return 1  # Explorer never sees this Ctrl+V
                                if reason:
                                    user32.PostThreadMessageW(tid, WM_PASSED, reason, 0)
                        elif w_param in (WM_KEYUP, WM_SYSKEYUP) and self.holding_v:
                            self.holding_v = False
            except Exception:  # noqa: BLE001 - a hook must never raise
                pass
            return user32.CallNextHookEx(None, n_code, w_param, l_param)

        cb = HOOKPROC(proc)  # keep a reference for the life of the hook
        hmod = kernel32.GetModuleHandleW(None)

        def arm(old):
            if old:
                user32.UnhookWindowsHookEx(old)
            h = user32.SetWindowsHookExW(13, cb, hmod, 0)  # WH_KEYBOARD_LL
            if not h:
                log(f"helper: SetWindowsHookEx failed, error {ctypes.get_last_error()}")
            return h

        def send_canary():
            inputs = (INPUT * 2)()
            for i, flags in enumerate((0, 2)):  # key down, KEYEVENTF_KEYUP
                inputs[i].type = 1  # INPUT_KEYBOARD
                inputs[i].u.ki = KEYBDINPUT(VK_F24, 0, flags, 0, self.tag)
            self.canary_seen = False
            self.canary_sent = time.monotonic()
            return user32.SendInput(2, inputs, ctypes.sizeof(INPUT)) == 2

        hook = arm(None)
        if not hook:
            return 2
        log(f"Ctrl+V takeover is on (helper process {os.getpid()})")
        user32.SetTimer(None, 0, CHECK_MS, None)
        sent_ok = send_canary()
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_APP:
                threading.Thread(target=handle_paste, args=(self.pipe, int(msg.wParam), self.status),
                                 name="SwiftCopy-Paste", daemon=True).start()
                continue
            if msg.message == WM_PASSED:
                why = REASONS.get(int(msg.wParam), "unknown")
                if int(msg.wParam) == 2 and self.passed_focus:
                    why += f" ({self.passed_focus})"
                self.status(f"left to Windows: {why}")
                continue
            if msg.message == WM_TIMER:
                if parent and kernel32.WaitForSingleObject(parent, 0) == 0:  # SwiftCopy has closed
                    break
                # Self-check: if our last F24 check press never reached the hook,
                # Windows removed the hook - put it back now.
                if sent_ok and not self.canary_seen:
                    self.rearms += 1
                    log(f"helper: check press wasn't seen - keyboard watcher turned back on (#{self.rearms})")
                    hook = arm(hook) or hook
                elif not sent_ok:
                    hook = arm(hook) or hook  # can't self-check (e.g. a locked screen) - re-arm anyway
                sent_ok = send_canary()
                continue
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        user32.UnhookWindowsHookEx(hook)
        log("Ctrl+V takeover is off (helper closed)")
        return 0


def keep_responsive(kernel32) -> None:
    """Stop Windows 11 putting this windowless background process into efficiency mode
    (EcoQoS), which delays it enough for Windows to drop the keyboard hook, and run it at
    high priority so it always answers a key press in time."""
    import ctypes
    from ctypes import wintypes

    class PROCESS_POWER_THROTTLING_STATE(ctypes.Structure):
        _fields_ = [("Version", wintypes.ULONG), ("ControlMask", wintypes.ULONG),
                    ("StateMask", wintypes.ULONG)]

    try:
        proc = kernel32.GetCurrentProcess()
        state = PROCESS_POWER_THROTTLING_STATE(1, 0x1 | 0x4, 0)  # EXECUTION_SPEED | IGNORE_TIMER_RESOLUTION: off
        kernel32.SetProcessInformation(proc, 4, ctypes.byref(state), ctypes.sizeof(state))  # ProcessPowerThrottling
        kernel32.SetPriorityClass(proc, 0x80)  # HIGH_PRIORITY_CLASS
        kernel32.SetThreadPriority(kernel32.GetCurrentThread(), 15)  # THREAD_PRIORITY_TIME_CRITICAL
    except Exception as e:  # noqa: BLE001
        log(f"helper: couldn't raise priority: {e!r}")


def single_helper():
    """Only one helper may watch Ctrl+V. Returns a mutex handle to keep, or None if one is already running."""
    import ctypes
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    handle = kernel32.CreateMutexW(None, False, "Local\\SwiftCopy-CtrlV-helper")
    if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
        return None
    return handle


def main(argv=None) -> int:
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--hook-helper", action="store_true")
    p.add_argument("--parent", type=int, default=0)
    p.add_argument("--pipe", required=True)
    args = p.parse_args(sys.argv[1:] if argv is None else argv)
    if not integration.IS_WIN:
        return 1
    mutex = single_helper()
    if mutex is None:
        log("helper: another SwiftCopy helper is already watching Ctrl+V - this one isn't needed")
        return 3
    try:
        import pythoncom
        pythoncom.CoInitialize()
    except Exception:  # noqa: BLE001
        pass
    return HookLoop(args.pipe, args.parent).run()


if __name__ == "__main__":
    sys.exit(main())
