"""Entry point: command line, single instance, window."""
from __future__ import annotations

import argparse
import getpass
import json
import os
import sys

from PySide6.QtCore import QByteArray, QSettings
from PySide6.QtGui import QIcon
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QStyleFactory

from . import APP_NAME, __version__
from . import theme
from .ui import MainWindow


def resource(*parts: str) -> str:
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(base, *parts)


def parse_args(argv):
    p = argparse.ArgumentParser(prog=APP_NAME, description="Copy or move files with a queue.")
    p.add_argument("paths", nargs="*", help="files or folders to copy")
    p.add_argument("--dest", help="destination folder (starts right away when given)")
    p.add_argument("--move", action="store_true", help="move instead of copy")
    p.add_argument("--paste", metavar="FOLDER",
                   help="paste the files copied/cut in Explorer into FOLDER")
    p.add_argument("--tray", action="store_true", help="start hidden in the tray")
    p.add_argument("--selftest", metavar="FILE", help=argparse.SUPPRESS)
    p.add_argument("--version", action="version", version=f"{APP_NAME} {__version__}")
    return p.parse_args(argv)


def server_name() -> str:
    try:
        user = getpass.getuser()
    except Exception:  # noqa: BLE001
        user = "user"
    return f"{APP_NAME}-{user}"


def send_to_running(payload: dict) -> bool:
    """Hand the request to an already-open SwiftCopy window. True if one answered."""
    sock = QLocalSocket()
    sock.connectToServer(server_name())
    if not sock.waitForConnected(300):
        return False
    sock.write(QByteArray(json.dumps(payload).encode("utf-8")))
    sock.flush()
    sock.waitForBytesWritten(1000)
    sock.disconnectFromServer()
    return True


def selftest(path: str) -> int:
    """Checks the packaged app can do the Explorer parts (used by the build)."""
    from . import integration
    out = {"version": __version__, "frozen": integration.frozen()}
    try:
        import pythoncom  # noqa: F401
        import win32com.client
        shell = win32com.client.Dispatch("Shell.Application")
        out["shell_windows"] = shell.Windows().Count
        out["pywin32"] = True
    except Exception as e:  # noqa: BLE001
        out["pywin32"] = False
        out["pywin32_error"] = repr(e)
    try:
        import ctypes
        progman = ctypes.windll.user32.FindWindowW("Progman", None)
        out["desktop_lookup"] = list(integration.explorer_folder(progman)) if progman else "no desktop"
    except Exception as e:  # noqa: BLE001
        out["desktop_lookup"] = repr(e)
    hook = integration.PasteHook(lambda hwnd: None)
    out["hook"] = hook.install()
    hook.uninstall()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
    return 0 if out["pywin32"] and out["hook"] else 1


def main(argv=None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    if args.selftest:
        return selftest(args.selftest)
    payload = {"paths": [os.path.abspath(p) for p in args.paths],
               "dest": os.path.abspath(args.dest) if args.dest else None,
               "move": args.move,
               "show": not args.tray}

    if os.name == "nt":
        try:  # own taskbar icon instead of python's
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("SwiftCopy.App")
        except Exception:  # noqa: BLE001
            pass

    app = QApplication(sys.argv[:1])
    app.setApplicationName(APP_NAME)
    app.setStyle(QStyleFactory.create("Fusion"))
    theme.apply(app, QSettings(APP_NAME, APP_NAME).value("theme", "system"))
    app.setQuitOnLastWindowClosed(False)  # the tray keeps it alive; MainWindow decides when to quit

    if args.paste:  # right-click "Paste with SwiftCopy"
        from .ui import clipboard_files
        paths, cut = clipboard_files()
        if not paths:
            return 0
        payload.update(paths=paths, dest=os.path.abspath(args.paste), move=cut)
        if cut:
            app.clipboard().clear()

    # Already running? Add these files to its queue instead of opening a second window.
    if send_to_running(payload):
        return 0

    QLocalServer.removeServer(server_name())
    server = QLocalServer()
    server.listen(server_name())

    icon = QIcon(resource("assets", "icon.ico"))
    app.setWindowIcon(icon)
    win = MainWindow(icon)

    def on_connection():
        conn = server.nextPendingConnection()
        if conn is None:
            return
        buf = bytearray()

        def read():
            buf.extend(bytes(conn.readAll()))

        def finished():
            read()
            try:
                data = json.loads(buf.decode("utf-8") or "{}")
            except ValueError:
                return
            if data.get("paths") or data.get("dest"):
                win.set_sources(data.get("paths") or [], data.get("dest"), bool(data.get("move")),
                                autostart=bool(data.get("dest")))
            elif data.get("show", True):
                win.bring_to_front()

        conn.readyRead.connect(read)
        conn.disconnected.connect(finished)

    server.newConnection.connect(on_connection)

    if payload["show"] or not win.tray:
        win.show()
    if payload["paths"] or payload["dest"]:
        win.set_sources(payload["paths"], payload["dest"], payload["move"],
                        autostart=bool(payload["dest"]))
    return app.exec()
