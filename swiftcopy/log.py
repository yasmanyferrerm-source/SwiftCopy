"""Small diagnostic log: %LOCALAPPDATA%\\SwiftCopy\\SwiftCopy.log (kept under ~512 KB)."""
from __future__ import annotations

import datetime as dt
import os
import tempfile
import threading

_lock = threading.Lock()
MAX_BYTES = 512 * 1024


def log_dir() -> str:
    base = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), ".local", "share")
    return os.path.join(base, "SwiftCopy")


def log_path() -> str:
    return os.path.join(log_dir(), "SwiftCopy.log")


def log(msg: str) -> None:
    line = f"{dt.datetime.now():%Y-%m-%d %H:%M:%S}  {msg}\n"
    with _lock:
        try:
            os.makedirs(log_dir(), exist_ok=True)
            path = log_path()
            if os.path.exists(path) and os.path.getsize(path) > MAX_BYTES:
                old = path + ".old"
                if os.path.exists(old):
                    os.remove(old)
                os.replace(path, old)
            with open(path, "a", encoding="utf-8") as f:
                f.write(line)
        except OSError:
            try:  # last resort so logging can never break the app
                with open(os.path.join(tempfile.gettempdir(), "SwiftCopy.log"), "a", encoding="utf-8") as f:
                    f.write(line)
            except OSError:
                pass
