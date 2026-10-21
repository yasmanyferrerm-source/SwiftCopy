"""Windows Explorer integration that needs no admin rights.

Adds a "SwiftCopy" shortcut to the user's Send To menu
(%APPDATA%\\Microsoft\\Windows\\SendTo). Right-click files -> Send to -> SwiftCopy.
"""
from __future__ import annotations

import os
import subprocess
import sys


def sendto_folder() -> str:
    return os.path.join(os.environ.get("APPDATA", ""), "Microsoft", "Windows", "SendTo")


def shortcut_path() -> str:
    return os.path.join(sendto_folder(), "SwiftCopy.lnk")


def launch_command() -> tuple[str, str]:
    """(target, arguments) that start this app."""
    if getattr(sys, "frozen", False):
        return sys.executable, ""
    script = os.path.abspath(sys.argv[0])
    pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    return (pythonw if os.path.exists(pythonw) else sys.executable), f'"{script}"'


def is_installed() -> bool:
    return os.name == "nt" and os.path.exists(shortcut_path())


def install_sendto() -> None:
    if os.name != "nt":
        raise OSError("Send To is only available on Windows")
    target, args = launch_command()
    ps = (
        "$s=(New-Object -ComObject WScript.Shell).CreateShortcut($env:LNK);"
        "$s.TargetPath=$env:TGT;$s.Arguments=$env:ARGS;$s.IconLocation=$env:TGT+',0';"
        "$s.Description='Copy or move with SwiftCopy';$s.Save()"
    )
    env = dict(os.environ, LNK=shortcut_path(), TGT=target, ARGS=args)
    subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
        env=env, check=True, capture_output=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def uninstall_sendto() -> None:
    if os.path.exists(shortcut_path()):
        os.remove(shortcut_path())


def open_in_explorer(path: str) -> None:
    if os.name == "nt":
        if os.path.isfile(path):
            subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
        else:
            os.startfile(path)  # type: ignore[attr-defined]
    else:
        subprocess.Popen(["xdg-open", path if os.path.isdir(path) else os.path.dirname(path)])
