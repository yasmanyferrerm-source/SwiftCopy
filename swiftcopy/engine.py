"""Copy engine for SwiftCopy.

Pure Python (no Qt). All copying happens on one worker thread; the UI reads
`snapshot()` and `items` on a timer and answers questions through
`answer_prompt()`.
"""
from __future__ import annotations

import collections
import hashlib
import itertools
import os
import stat
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Optional

PART_SUFFIX = ".swcpart"


# --------------------------------------------------------------------------- enums
class Status(str, Enum):
    PENDING = "Pending"
    COPYING = "Copying"
    VERIFYING = "Verifying"
    DONE = "Done"
    SKIPPED = "Skipped"
    ERROR = "Error"
    CANCELLED = "Cancelled"


FINAL_STATES = {Status.DONE, Status.SKIPPED, Status.ERROR, Status.CANCELLED}


class Collision(str, Enum):
    ASK = "ask"
    OVERWRITE = "overwrite"
    SKIP = "skip"
    NEWER = "newer"          # overwrite only if the source is newer
    DIFFERENT = "different"  # overwrite only if size or date differ
    RENAME = "rename"        # keep both: "name (2).ext"
    CANCEL = "cancel"        # only used as an answer to a prompt


class ErrorAction(str, Enum):
    ASK = "ask"
    SKIP = "skip"
    RETRY = "retry"          # retry a few times, then skip
    CANCEL = "cancel"


@dataclass
class Settings:
    collision: Collision = Collision.ASK
    on_error: ErrorAction = ErrorAction.ASK
    retries: int = 3
    buffer_kb: int = 1024
    speed_limit_kbps: int = 0        # 0 = unlimited
    verify: bool = False
    keep_timestamps: bool = True


# ----------------------------------------------------------------------- data types
@dataclass
class TransferItem:
    id: int
    job_id: int
    src: str
    dst: str
    size: int
    move: bool
    is_dir: bool = False
    status: Status = Status.PENDING
    error: str = ""
    done: int = 0
    final_dst: str = ""


@dataclass
class Job:
    id: int
    sources: list
    dest: str
    move: bool
    prune_dirs: list = field(default_factory=list)


@dataclass
class Prompt:
    kind: str                     # "collision" or "error"
    item: TransferItem
    message: str = ""
    target: str = ""
    src_size: int = 0
    src_mtime: float = 0.0
    dst_size: int = 0
    dst_mtime: float = 0.0
    answer: Optional[str] = None
    apply_all: bool = False
    event: threading.Event = field(default_factory=threading.Event)


class _SkipFile(Exception):
    pass


class _CancelAll(Exception):
    pass


# -------------------------------------------------------------------------- helpers
def lp(path: str) -> str:
    """Return a path usable on Windows even past the 260-character limit."""
    if os.name != "nt" or path.startswith("\\\\?\\") or len(path) < 240:
        return path
    path = os.path.abspath(path)
    if path.startswith("\\\\"):
        return "\\\\?\\UNC\\" + path[2:]
    return "\\\\?\\" + path


def unique_name(path: str) -> str:
    """'C:/x/report.pdf' -> 'C:/x/report (2).pdf' (first free number)."""
    folder, name = os.path.split(path)
    stem, ext = os.path.splitext(name)
    if not stem:  # dot-files like ".env"
        stem, ext = name, ""
    for n in itertools.count(2):
        candidate = os.path.join(folder, f"{stem} ({n}){ext}")
        if not os.path.lexists(lp(candidate)):
            return candidate
    raise RuntimeError("unreachable")


def is_inside(child: str, parent: str) -> bool:
    child = os.path.normcase(os.path.abspath(child))
    parent = os.path.normcase(os.path.abspath(parent))
    try:
        return os.path.commonpath([child, parent]) == parent
    except ValueError:  # different drives
        return False


def source_name(src: str) -> str:
    name = os.path.basename(src.rstrip("\\/"))
    if not name:  # a drive root such as "D:\\"
        name = src.strip(":\\/").replace(":", "") or "root"
    return name


def _make_writable(path: str) -> None:
    try:
        mode = os.stat(lp(path)).st_mode
        if not mode & stat.S_IWRITE:
            os.chmod(lp(path), mode | stat.S_IWRITE)
    except OSError:
        pass


def _remove(path: str) -> None:
    try:
        os.remove(lp(path))
    except PermissionError:
        _make_writable(path)
        os.remove(lp(path))


def format_size(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def format_eta(seconds: Optional[float]) -> str:
    if seconds is None or seconds == float("inf"):
        return "--:--"
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


# --------------------------------------------------------------------------- engine
class CopyEngine:
    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or Settings()
        self.items: list[TransferItem] = []
        self.errors: list[tuple[str, str]] = []
        self.prompt: Optional[Prompt] = None
        # Optional synchronous prompt handler (used by tests / headless runs).
        self.prompt_handler: Optional[Callable[[Prompt], tuple]] = None
        self.on_finished: Optional[Callable[[dict], None]] = None

        self._lock = threading.RLock()
        self._jobs: collections.deque[Job] = collections.deque()
        self._finished_moves: list[Job] = []
        self._ids = itertools.count(1)
        self._job_ids = itertools.count(1)
        self._thread: Optional[threading.Thread] = None
        self._unpaused = threading.Event()
        self._unpaused.set()
        self._cancel = False
        self._skip = False
        self._current: Optional[TransferItem] = None
        self._scanning = False
        self._collision_all: Optional[Collision] = None
        self._error_all: Optional[ErrorAction] = None
        self._transferred = 0
        self._samples: collections.deque = collections.deque()
        self._throttle_start = 0.0
        self._throttle_bytes = 0
        self.last_summary: dict = {}

    # ------------------------------------------------------------- public API
    def add_job(self, sources: list, dest: str, move: bool = False) -> int:
        sources = [os.path.abspath(s) for s in sources if s]
        job = Job(next(self._job_ids), sources, os.path.abspath(dest), move)
        with self._lock:
            self._jobs.append(job)
            if not self.is_running:
                self._cancel = False
                self._skip = False
                self._thread = threading.Thread(target=self._run, name="SwiftCopy", daemon=True)
                self._thread.start()
        return job.id

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def is_paused(self) -> bool:
        return not self._unpaused.is_set()

    def pause(self) -> None:
        self._unpaused.clear()

    def resume(self) -> None:
        self._unpaused.set()

    def skip_current(self) -> None:
        if self._current is not None:
            self._skip = True
            self._unpaused.set()

    def cancel_all(self) -> None:
        with self._lock:
            self._jobs.clear()
            for it in self.items:
                if it.status == Status.PENDING:
                    it.status = Status.CANCELLED
            if self.is_running:
                self._cancel = True
            p = self.prompt
        self._unpaused.set()
        if p is not None:
            p.answer = "cancel"
            p.event.set()

    def answer_prompt(self, answer: str, apply_all: bool = False) -> None:
        p = self.prompt
        if p is not None:
            p.answer = answer
            p.apply_all = apply_all
            p.event.set()

    def wait(self, timeout: Optional[float] = None) -> bool:
        t = self._thread
        if t is not None:
            t.join(timeout)
        return not self.is_running

    def remove_items(self, ids: set) -> None:
        with self._lock:
            self.items = [it for it in self.items
                          if not (it.id in ids and it.status == Status.PENDING)]

    def items_pending(self) -> bool:
        return any(it.status == Status.PENDING for it in self.items)

    def take_failed(self) -> list[TransferItem]:
        """Remove failed file items from the list (so they can be re-queued)."""
        with self._lock:
            failed = [it for it in self.items if it.status == Status.ERROR and not it.is_dir]
            ids = {it.id for it in failed}
            self.items = [it for it in self.items if it.id not in ids]
            self.errors.clear()
        return failed

    def clear_finished(self) -> None:
        with self._lock:
            self.items = [it for it in self.items if it.status not in FINAL_STATES]
            self.errors.clear()

    def move_items(self, ids: set, direction: int) -> None:
        """Move pending items up (-1) or down (+1) in the queue."""
        with self._lock:
            idx = [i for i, it in enumerate(self.items)
                   if it.id in ids and it.status == Status.PENDING]
            order = idx if direction < 0 else list(reversed(idx))
            for i in order:
                j = i + direction
                if 0 <= j < len(self.items) and self.items[j].status == Status.PENDING \
                        and self.items[j].id not in ids:
                    self.items[i], self.items[j] = self.items[j], self.items[i]

    def snapshot(self) -> dict:
        with self._lock:
            items = list(self.items)
            cur = self._current
        total = done_bytes = 0
        files_total = files_done = 0
        for it in items:
            total += it.size
            if not it.is_dir:
                files_total += 1
            if it.status == Status.CANCELLED:
                continue  # counts toward the total but never toward "done"
            if it.status in FINAL_STATES:
                done_bytes += it.size
                if not it.is_dir:
                    files_done += 1
            else:
                done_bytes += it.done
        speed = self._speed()
        remaining = max(total - done_bytes, 0)
        eta = remaining / speed if speed > 1 else None
        if self.prompt is not None:
            state = "Waiting for you"
        elif self._scanning:
            state = "Scanning"
        elif not self.is_running:
            state = "Idle"
        elif self.is_paused:
            state = "Paused"
        else:
            state = "Copying"
        return {
            "state": state,
            "total_bytes": total,
            "done_bytes": done_bytes,
            "files_total": files_total,
            "files_done": files_done,
            "speed": speed,
            "eta": eta,
            "current": cur,
            "errors": len(self.errors),
        }

    # ---------------------------------------------------------------- worker
    def _run(self) -> None:
        start = time.monotonic()
        moved_bytes_at_start = self._transferred
        try:
            while True:
                with self._lock:
                    job = self._jobs.popleft() if self._jobs else None
                if job is not None:
                    try:
                        self._scan(job)
                    except _CancelAll:
                        self._after_cancel()
                    continue
                item = self._next_pending()
                if item is None:
                    break
                try:
                    self._process(item)
                except _CancelAll:
                    if item.status not in FINAL_STATES:
                        item.status = Status.CANCELLED
                    self._after_cancel()
                finally:
                    self._current = None
            self._prune_moved_dirs()
        finally:
            with self._lock:
                self._collision_all = None
                self._error_all = None
                self._current = None
                self._scanning = False
                self._samples.clear()
                self.last_summary = {
                    "seconds": time.monotonic() - start,
                    "bytes": self._transferred - moved_bytes_at_start,
                    "done": sum(1 for i in self.items if i.status == Status.DONE and not i.is_dir),
                    "skipped": sum(1 for i in self.items if i.status == Status.SKIPPED),
                    "errors": sum(1 for i in self.items if i.status == Status.ERROR),
                    "cancelled": sum(1 for i in self.items if i.status == Status.CANCELLED),
                }
            if self.on_finished:
                try:
                    self.on_finished(self.last_summary)
                except Exception:
                    pass

    def _after_cancel(self) -> None:
        with self._lock:
            for it in self.items:
                if it.status in (Status.PENDING, Status.COPYING, Status.VERIFYING):
                    it.status = Status.CANCELLED
            self._jobs.clear()
            self._finished_moves.clear()
            self._cancel = False
            self._skip = False
        self._unpaused.set()

    def _next_pending(self) -> Optional[TransferItem]:
        with self._lock:
            for it in self.items:
                if it.status == Status.PENDING:
                    self._current = it
                    return it
        return None

    # ------------------------------------------------------------------ scan
    def _add(self, job: Job, src: str, dst: str, size: int, is_dir=False,
             status=Status.PENDING, error="") -> None:
        it = TransferItem(next(self._ids), job.id, src, dst, size, job.move,
                          is_dir=is_dir, status=status, error=error)
        with self._lock:
            self.items.append(it)
            if status == Status.ERROR:
                self.errors.append((src, error))

    def _scan(self, job: Job) -> None:
        self._scanning = True
        try:
            for src in job.sources:
                if self._cancel:
                    raise _CancelAll
                target = os.path.join(job.dest, source_name(src))
                if not os.path.lexists(lp(src)):
                    self._add(job, src, target, 0, status=Status.ERROR, error="Source not found")
                    continue
                if os.path.isdir(lp(src)):
                    if is_inside(job.dest, src):
                        self._add(job, src, target, 0, is_dir=True, status=Status.ERROR,
                                  error="Can't copy a folder into itself")
                        continue
                    self._scan_dir(job, src, target)
                    if job.move:
                        job.prune_dirs.append(src)
                else:
                    try:
                        size = os.stat(lp(src)).st_size
                        self._add(job, src, target, size)
                    except OSError as e:
                        self._add(job, src, target, 0, status=Status.ERROR, error=e.strerror or str(e))
            if job.move and job.prune_dirs:
                self._finished_moves.append(job)
        finally:
            self._scanning = False

    def _scan_dir(self, job: Job, src: str, target: str) -> None:
        def onerror(e: OSError):
            self._add(job, e.filename or src, target, 0, status=Status.ERROR,
                      error=e.strerror or str(e))

        for root, dirs, files in os.walk(lp(src), onerror=onerror):
            if self._cancel:
                raise _CancelAll
            root_plain = root[4:] if root.startswith("\\\\?\\") and not src.startswith("\\\\?\\") else root
            rel = os.path.relpath(root_plain, src)
            troot = os.path.normpath(os.path.join(target, rel))
            dirs.sort(key=str.lower)
            if not dirs and not files:
                self._add(job, root_plain, troot, 0, is_dir=True)
            for name in sorted(files, key=str.lower):
                path = os.path.join(root_plain, name)
                if name.endswith(PART_SUFFIX):
                    continue
                try:
                    size = os.stat(lp(path)).st_size
                except OSError as e:
                    self._add(job, path, os.path.join(troot, name), 0, status=Status.ERROR,
                              error=e.strerror or str(e))
                    continue
                self._add(job, path, os.path.join(troot, name), size)

    # --------------------------------------------------------------- process
    def _process(self, item: TransferItem) -> None:
        if item.is_dir:
            try:
                os.makedirs(lp(item.dst), exist_ok=True)
                item.status = Status.DONE
                item.final_dst = item.dst
            except OSError as e:
                self._fail(item, e)
            return

        attempts = 0
        while True:
            item.status = Status.COPYING
            item.done = 0
            item.error = ""
            try:
                target = self._resolve_collision(item)
                if target is None:
                    item.status = Status.SKIPPED
                    return
                self._transfer(item, target)
                item.final_dst = target
                item.status = Status.DONE
                return
            except _SkipFile:
                item.status = Status.SKIPPED
                return
            except _CancelAll:
                raise
            except OSError as e:
                action = self._handle_error(item, e, attempts)
                attempts += 1
                if action == "retry":
                    continue
                if action == "cancel":
                    self._fail(item, e)
                    raise _CancelAll
                self._fail(item, e)
                return
            except Exception as e:  # never let the worker thread die
                self._fail(item, e)
                return

    def _fail(self, item: TransferItem, exc: BaseException) -> None:
        msg = getattr(exc, "strerror", None) or str(exc) or exc.__class__.__name__
        item.status = Status.ERROR
        item.error = msg
        with self._lock:
            self.errors.append((item.src, msg))

    def _ask(self, prompt: Prompt) -> tuple:
        if self.prompt_handler is not None:
            return self.prompt_handler(prompt)
        with self._lock:
            self.prompt = prompt
        try:
            while not prompt.event.wait(0.1):
                if self._cancel:
                    return "cancel", False
            return prompt.answer, prompt.apply_all
        finally:
            with self._lock:
                self.prompt = None

    def _resolve_collision(self, item: TransferItem) -> Optional[str]:
        dst = item.dst
        if not os.path.lexists(lp(dst)):
            return dst
        try:
            same = os.path.samefile(lp(item.src), lp(dst))
        except OSError:
            same = False
        if same:
            if item.move:
                return None  # already there
            return unique_name(dst)

        s = os.stat(lp(item.src))
        d = os.stat(lp(dst))
        policy = self._collision_all or self.settings.collision
        if policy == Collision.ASK:
            p = Prompt("collision", item, target=dst, src_size=s.st_size, src_mtime=s.st_mtime,
                       dst_size=d.st_size, dst_mtime=d.st_mtime)
            answer, apply_all = self._ask(p)
            policy = Collision(answer or "cancel")
            if apply_all and policy != Collision.CANCEL:
                self._collision_all = policy

        if policy == Collision.CANCEL:
            raise _CancelAll
        if policy == Collision.RENAME:
            return unique_name(dst)
        if os.path.isdir(lp(dst)):
            raise IsADirectoryError(21, "A folder with the same name already exists", dst)
        if policy == Collision.OVERWRITE:
            return dst
        if policy == Collision.SKIP:
            return None
        if policy == Collision.NEWER:
            return dst if s.st_mtime > d.st_mtime + 2 else None
        if policy == Collision.DIFFERENT:
            differs = s.st_size != d.st_size or abs(s.st_mtime - d.st_mtime) > 2
            return dst if differs else None
        return dst

    def _handle_error(self, item: TransferItem, exc: OSError, attempts: int) -> str:
        policy = self._error_all or self.settings.on_error
        if policy == ErrorAction.RETRY:
            if attempts < max(self.settings.retries, 0):
                try:
                    self._sleep(1.0)
                except _SkipFile:
                    return "skip"
                return "retry"
            return "skip"
        if policy == ErrorAction.ASK:
            msg = getattr(exc, "strerror", None) or str(exc)
            answer, apply_all = self._ask(Prompt("error", item, message=msg))
            answer = answer or "cancel"
            if apply_all and answer in ("skip", "cancel"):
                self._error_all = ErrorAction(answer)
            return answer
        return policy.value

    def _check(self) -> None:
        if self._cancel:
            raise _CancelAll
        if self._skip:
            self._skip = False
            raise _SkipFile
        while not self._unpaused.wait(0.1):
            if self._cancel:
                raise _CancelAll
            if self._skip:
                self._skip = False
                raise _SkipFile

    def _sleep(self, seconds: float) -> None:
        end = time.monotonic() + seconds
        while True:
            if self._cancel:
                raise _CancelAll
            if self._skip:
                self._skip = False
                raise _SkipFile
            left = end - time.monotonic()
            if left <= 0:
                return
            time.sleep(min(0.05, left))

    def _count(self, n: int) -> None:
        self._transferred += n
        now = time.monotonic()
        self._samples.append((now, self._transferred))
        while self._samples and now - self._samples[0][0] > 3.0:
            self._samples.popleft()

    def _speed(self) -> float:
        s = list(self._samples)
        if len(s) < 2:
            return 0.0
        dt = s[-1][0] - s[0][0]
        if time.monotonic() - s[-1][0] > 3.0 or dt <= 0:
            return 0.0
        return (s[-1][1] - s[0][1]) / dt

    def _throttle(self, n: int) -> None:
        limit = self.settings.speed_limit_kbps * 1024
        if limit <= 0:
            self._throttle_start = 0.0
            self._throttle_bytes = 0
            return
        now = time.monotonic()
        if not self._throttle_start or now - self._throttle_start > 2.0:
            self._throttle_start = now
            self._throttle_bytes = 0
        self._throttle_bytes += n
        wait = self._throttle_bytes / limit - (now - self._throttle_start)
        if wait > 0:
            self._sleep(wait)

    def _transfer(self, item: TransferItem, target: str) -> None:
        folder = os.path.dirname(target)
        os.makedirs(lp(folder), exist_ok=True)

        # Fast path: move on the same drive is just a rename.
        if item.move and not self.settings.verify:
            try:
                same_drive = os.stat(lp(item.src)).st_dev == os.stat(lp(folder)).st_dev
            except OSError:
                same_drive = False
            if same_drive:
                self._check()
                if os.path.lexists(lp(target)):
                    _make_writable(target)
                os.replace(lp(item.src), lp(target))
                item.done = item.size
                self._count(item.size)
                return

        part = target + PART_SUFFIX
        bufsize = max(64, self.settings.buffer_kb) * 1024
        hasher = hashlib.blake2b(digest_size=32) if self.settings.verify else None
        try:
            with open(lp(item.src), "rb") as fi, open(lp(part), "wb") as fo:
                while True:
                    self._check()
                    chunk = fi.read(bufsize)
                    if not chunk:
                        break
                    fo.write(chunk)
                    if hasher:
                        hasher.update(chunk)
                    n = len(chunk)
                    item.done += n
                    self._count(n)
                    self._throttle(n)
            if self.settings.keep_timestamps:
                try:
                    st = os.stat(lp(item.src))
                    os.utime(lp(part), ns=(st.st_atime_ns, st.st_mtime_ns))
                except OSError:
                    pass
            if os.path.lexists(lp(target)):
                _make_writable(target)
            os.replace(lp(part), lp(target))
        except BaseException:
            try:
                if os.path.lexists(lp(part)):
                    os.remove(lp(part))
            except OSError:
                pass
            raise

        if hasher:
            item.status = Status.VERIFYING
            check = hashlib.blake2b(digest_size=32)
            with open(lp(target), "rb") as f:
                while True:
                    self._check()
                    chunk = f.read(bufsize)
                    if not chunk:
                        break
                    check.update(chunk)
            if check.digest() != hasher.digest():
                try:
                    os.remove(lp(target))
                except OSError:
                    pass
                raise OSError(5, "Verification failed: the copy does not match the original")
            item.status = Status.COPYING

        if item.move:
            _remove(item.src)

    def _prune_moved_dirs(self) -> None:
        with self._lock:
            jobs = list(self._finished_moves)
            self._finished_moves.clear()
        for job in jobs:
            for top in job.prune_dirs:
                for root, _dirs, _files in os.walk(lp(top), topdown=False):
                    try:
                        os.rmdir(root)
                    except OSError:
                        pass  # not empty (something was skipped) - leave it
