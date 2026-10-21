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
    hook = i.PasteHook(lambda hwnd: None, lambda fn: fn())
    assert hook.install()
    assert hook.active
    hook.uninstall()
    assert not hook.active


def test_desktop_dir_exists():
    from swiftcopy import integration as i
    assert os.path.isdir(i.desktop_dir())


def test_pywin32_shell_available():
    import win32com.client
    shell = win32com.client.Dispatch("Shell.Application")
    list(shell.Windows())  # must not raise
