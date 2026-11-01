"""Windows-only checks for startup, right-click menu and the Ctrl+V hook (run on the CI runner)."""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows only")


def test_autostart_roundtrip():
    from swiftcopy import integration as i
    i.set_autostart(True)
    try:
        assert i.autostart_enabled()
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, i.RUN_KEY) as k:
            cmd = winreg.QueryValueEx(k, i.RUN_VALUE)[0]
        assert cmd.endswith("--tray")
    finally:
        i.set_autostart(False)
    assert not i.autostart_enabled()


def test_context_menu_roundtrip():
    from swiftcopy import integration as i
    i.set_context_menu(True)
    try:
        assert i.context_menu_enabled()
        import winreg
        key = "Software\\Classes\\" + i.MENU_KEYS[0][0] + "\\command"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as k:
            cmd = winreg.QueryValueEx(k, "")[0]
        assert '--paste "%V"' in cmd
    finally:
        i.set_context_menu(False)
    assert not i.context_menu_enabled()


def test_paste_hook_installs():
    from swiftcopy import integration as i
    hook = i.PasteHook(lambda hwnd: None)
    assert hook.install()
    assert hook.active
    assert hook.armed_count == 1
    hook.uninstall()
    assert not hook.active
    assert hook.install()  # can be turned on again
    hook.uninstall()


def test_desktop_dir_exists():
    from swiftcopy import integration as i
    assert os.path.isdir(i.desktop_dir())


def test_pywin32_shell_available():
    import win32com.client
    shell = win32com.client.Dispatch("Shell.Application")
    list(shell.Windows())  # must not raise


def test_explorer_folder_desktop_and_bad_window():
    import ctypes
    from swiftcopy import integration as i
    progman = ctypes.windll.user32.FindWindowW("Progman", None)
    if progman:
        folder, result, _ = i.explorer_folder(progman)
        assert result == i.FOLDER_OK and os.path.isdir(folder)
    folder, result, detail = i.explorer_folder(0x7FFFFFF0)  # not an Explorer window
    assert result == i.LOOKUP_FAILED and folder is None, detail


def test_log_writes(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    from swiftcopy import log
    log.log("hello")
    assert "hello" in open(log.log_path(), encoding="utf-8").read()


def test_helper_process_starts_and_stops():
    from swiftcopy.helperproc import HelperProcess
    h = HelperProcess("SwiftCopy-test-helper")
    assert h.install()
    import time
    time.sleep(2)
    assert h.active, "helper closed by itself"
    h.uninstall()
    assert not h.active


def test_helper_restarts_after_being_killed():
    import time
    from swiftcopy.helperproc import HelperProcess
    h = HelperProcess("SwiftCopy-test-helper2")
    assert h.install()
    h.proc.kill()
    h.proc.wait(5)
    h.check()
    time.sleep(1.5)
    assert h.active and h.restarts == 1
    h.uninstall()


def test_helper_exits_when_parent_closes():
    import subprocess, sys, time
    from swiftcopy import helperproc
    parent = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(1)"])
    cmd = helperproc.helper_command("SwiftCopy-test-helper3")
    cmd[cmd.index("--parent") + 1] = str(parent.pid)
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env = dict(os.environ, PYTHONPATH=root)
    helper = subprocess.Popen(cmd, env=env)
    parent.wait()
    try:
        helper.wait(25)  # checks every 15 s
    except subprocess.TimeoutExpired:
        helper.kill()
        raise AssertionError("helper kept running after SwiftCopy closed")


def test_helper_message_reaches_pipe():
    import json, threading
    import win32file, win32pipe
    from swiftcopy import hookhelper
    name = "SwiftCopy-test-pipe"
    got = {}
    pipe = win32pipe.CreateNamedPipe(r"\\.\pipe" + "\\" + name, win32pipe.PIPE_ACCESS_INBOUND,
                                     win32pipe.PIPE_TYPE_BYTE | win32pipe.PIPE_WAIT, 1, 65536, 65536, 0, None)

    def serve():
        win32pipe.ConnectNamedPipe(pipe, None)
        data = b""
        while True:
            try:
                _, chunk = win32file.ReadFile(pipe, 65536)
            except Exception:  # noqa: BLE001 - writer closed
                break
            data += chunk
        got["msg"] = json.loads(data.decode("utf-8"))

    t = threading.Thread(target=serve)
    t.start()
    assert hookhelper.send_to_app(name, {"type": "helper_status", "text": "hello"})
    t.join(5)
    win32file.CloseHandle(pipe)
    assert got["msg"] == {"type": "helper_status", "text": "hello"}


def test_clipboard_files_round_trip(tmp_path):
    import struct
    import pytest
    import win32clipboard
    from swiftcopy import hookhelper
    f = tmp_path / "a.txt"
    f.write_text("x")
    files = (str(f) + "\0").encode("utf-16-le") + b"\0\0"
    dropfiles = struct.pack("<IiiII", 20, 0, 0, 0, 1) + files
    try:
        win32clipboard.OpenClipboard()
    except Exception:  # noqa: BLE001
        pytest.skip("no clipboard on this machine")
    try:
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardData(hookhelper.CF_HDROP, dropfiles)
        effect = win32clipboard.RegisterClipboardFormat("Preferred DropEffect")
        win32clipboard.SetClipboardData(effect, struct.pack("<I", 2))  # "cut"
    finally:
        win32clipboard.CloseClipboard()
    paths, cut = hookhelper.read_clipboard_files()
    assert [os.path.normcase(p) for p in paths] == [os.path.normcase(str(f))]
    assert cut is True
