"""Starts and looks after the Ctrl+V helper process (see hookhelper.py)."""
from __future__ import annotations

import os
import subprocess
import sys
import time

from . import integration
from .log import log


def helper_command(pipe: str) -> list[str]:
    args = ["--hook-helper", "--parent", str(os.getpid()), "--pipe", pipe]
    if getattr(sys, "frozen", False):
        return [sys.executable] + args  # SwiftCopy.exe --hook-helper ...
    return [sys.executable, "-m", "swiftcopy.hookhelper"] + args


class HelperProcess:
    """Same interface the window used for the old in-app hook: install / uninstall /
    active / last_decision - plus check(), called regularly to restart a helper that died."""

    def __init__(self, pipe: str):
        self.pipe = pipe
        self.proc: subprocess.Popen | None = None
        self.enabled = False
        self.last_decision = ""
        self.restarts = 0
        self._next_try = 0.0
        self._fast_failures = 0
        self._started_at = 0.0
        self.elsewhere = False  # another SwiftCopy's helper is already watching Ctrl+V

    @property
    def active(self) -> bool:
        if self.proc is not None and self.proc.poll() is None:
            return True
        return self.elsewhere and self.enabled

    def _start(self) -> bool:
        self._stop()
        env = dict(os.environ)
        if not getattr(sys, "frozen", False):
            root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            env["PYTHONPATH"] = root + os.pathsep + env.get("PYTHONPATH", "")
        try:
            self.proc = subprocess.Popen(
                helper_command(self.pipe), env=env, close_fds=True,
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except OSError as e:
            log(f"couldn't start the Ctrl+V helper: {e!r}")
            self.proc = None
            return False
        self._started_at = time.monotonic()
        return True

    def _stop(self) -> None:
        p, self.proc = self.proc, None
        if p is not None and p.poll() is None:
            p.terminate()
            try:
                p.wait(2)
            except subprocess.TimeoutExpired:
                p.kill()

    def install(self) -> bool:
        if not integration.IS_WIN:
            return False
        self.enabled = True
        self._fast_failures = 0
        if not self._start():
            return False
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:  # give it a moment: it exits at once if the hook fails
            if self.proc.poll() is not None:
                if self.proc.returncode == 3:  # another helper is already on duty
                    self.elsewhere = True
                    self._next_try = time.monotonic() + 30
                    return True
                log(f"Ctrl+V helper stopped right away (code {self.proc.returncode})")
                return False
            if time.monotonic() - self._started_at > 0.8:
                return True
            time.sleep(0.05)
        return True

    def uninstall(self) -> None:
        self.enabled = False
        self._stop()

    def check(self) -> None:
        """Restart the helper if it closed unexpectedly (with a back-off if it keeps failing)."""
        running = self.proc is not None and self.proc.poll() is None
        if not self.enabled or running or time.monotonic() < self._next_try:
            return
        code = self.proc.returncode if self.proc is not None else None
        if code == 3:  # another SwiftCopy's helper is on duty - look again in 30 s
            self.elsewhere = True
            self._next_try = time.monotonic() + 30
            self._start()  # takes over if that one has gone, otherwise exits with 3 again
            return
        self.elsewhere = False
        lived = time.monotonic() - self._started_at
        self._fast_failures = self._fast_failures + 1 if lived < 10 else 0
        delay = min(60, 2 ** self._fast_failures) if self._fast_failures else 0
        self._next_try = time.monotonic() + delay
        self.restarts += 1
        log(f"Ctrl+V helper had stopped (code {code}) - restarting it (#{self.restarts})")
        self._start()
