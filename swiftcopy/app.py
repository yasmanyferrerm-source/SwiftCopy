"""Entry point: command line, single instance, window."""
from __future__ import annotations

import argparse
import getpass
import json
import os
import sys

from PySide6.QtCore import QByteArray
from PySide6.QtGui import QIcon
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QStyleFactory

from . import APP_NAME, __version__
from .ui import STYLE, MainWindow


def resource(*parts: str) -> str:
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(base, *parts)


def parse_args(argv):
    p = argparse.ArgumentParser(prog=APP_NAME, description="Copy or move files with a queue.")
    p.add_argument("paths", nargs="*", help="files or folders to copy")
    p.add_argument("--dest", help="destination folder (starts right away when given)")
    p.add_argument("--move", action="store_true", help="move instead of copy")
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


def main(argv=None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    payload = {"paths": [os.path.abspath(p) for p in args.paths],
               "dest": os.path.abspath(args.dest) if args.dest else None,
               "move": args.move}

    if os.name == "nt":
        try:  # own taskbar icon instead of python's
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("SwiftCopy.App")
        except Exception:  # noqa: BLE001
            pass

    app = QApplication(sys.argv[:1])
    app.setApplicationName(APP_NAME)
    app.setStyle(QStyleFactory.create("Fusion"))
    app.setStyleSheet(STYLE)
    app.setQuitOnLastWindowClosed(True)

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
            win.set_sources(data.get("paths") or [], data.get("dest"), bool(data.get("move")),
                            autostart=bool(data.get("dest")))

        conn.readyRead.connect(read)
        conn.disconnected.connect(finished)

    server.newConnection.connect(on_connection)

    win.show()
    if payload["paths"] or payload["dest"]:
        win.set_sources(payload["paths"], payload["dest"], payload["move"],
                        autostart=bool(payload["dest"]))
    return app.exec()
