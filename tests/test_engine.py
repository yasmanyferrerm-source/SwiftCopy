import os
import sys
import threading
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from swiftcopy.engine import (  # noqa: E402
    Collision, CopyEngine, ErrorAction, Settings, Status, unique_name,
)


def write(path, data=b"hello", mtime=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


def run(engine, sources, dest, move=False):
    engine.add_job([str(s) for s in sources], str(dest), move=move)
    assert engine.wait(30)
    return engine


@pytest.fixture
def tree(tmp_path):
    src = tmp_path / "src"
    write(str(src / "a.txt"), b"A" * 1000)
    write(str(src / "sub" / "b.bin"), os.urandom(300_000))
    os.makedirs(src / "empty")
    return src


def test_copy_folder(tree, tmp_path):
    dest = tmp_path / "dest"
    e = run(CopyEngine(), [tree], dest)
    assert (dest / "src" / "a.txt").read_bytes() == (tree / "a.txt").read_bytes()
    assert (dest / "src" / "sub" / "b.bin").read_bytes() == (tree / "sub" / "b.bin").read_bytes()
    assert (dest / "src" / "empty").is_dir()
    assert all(i.status == Status.DONE for i in e.items)
    snap = e.snapshot()
    assert snap["files_done"] == snap["files_total"] == 2
    assert snap["done_bytes"] == snap["total_bytes"]
    assert not list(dest.rglob("*.swcpart"))


def test_timestamps_kept(tmp_path):
    f = write(str(tmp_path / "s" / "old.txt"), mtime=1_000_000_000)
    run(CopyEngine(), [f], tmp_path / "d")
    assert int(os.stat(tmp_path / "d" / "old.txt").st_mtime) == 1_000_000_000


def test_move_folder_removes_source(tree, tmp_path):
    dest = tmp_path / "dest"
    data = (tree / "sub" / "b.bin").read_bytes()
    run(CopyEngine(), [tree], dest, move=True)
    assert (dest / "src" / "sub" / "b.bin").read_bytes() == data
    assert not tree.exists()


def test_move_with_verify_uses_copy_path(tree, tmp_path):
    dest = tmp_path / "dest"
    run(CopyEngine(Settings(verify=True)), [tree], dest, move=True)
    assert (dest / "src" / "a.txt").exists()
    assert not tree.exists()


@pytest.mark.parametrize("policy,expected", [
    (Collision.OVERWRITE, b"NEW"),
    (Collision.SKIP, b"OLD"),
])
def test_collision_simple(tmp_path, policy, expected):
    s = write(str(tmp_path / "s" / "f.txt"), b"NEW")
    write(str(tmp_path / "d" / "f.txt"), b"OLD")
    run(CopyEngine(Settings(collision=policy)), [s], tmp_path / "d")
    assert (tmp_path / "d" / "f.txt").read_bytes() == expected


def test_collision_rename(tmp_path):
    s = write(str(tmp_path / "s" / "f.txt"), b"NEW")
    write(str(tmp_path / "d" / "f.txt"), b"OLD")
    run(CopyEngine(Settings(collision=Collision.RENAME)), [s], tmp_path / "d")
    assert (tmp_path / "d" / "f.txt").read_bytes() == b"OLD"
    assert (tmp_path / "d" / "f (2).txt").read_bytes() == b"NEW"


def test_collision_newer(tmp_path):
    now = time.time()
    s1 = write(str(tmp_path / "s" / "newer.txt"), b"NEW", mtime=now)
    s2 = write(str(tmp_path / "s" / "older.txt"), b"NEW", mtime=now - 1000)
    write(str(tmp_path / "d" / "newer.txt"), b"OLD", mtime=now - 500)
    write(str(tmp_path / "d" / "older.txt"), b"OLD", mtime=now - 500)
    run(CopyEngine(Settings(collision=Collision.NEWER)), [s1, s2], tmp_path / "d")
    assert (tmp_path / "d" / "newer.txt").read_bytes() == b"NEW"
    assert (tmp_path / "d" / "older.txt").read_bytes() == b"OLD"


def test_collision_ask_apply_all(tmp_path):
    srcs = [write(str(tmp_path / "s" / f"{n}.txt"), b"NEW") for n in range(3)]
    for n in range(3):
        write(str(tmp_path / "d" / f"{n}.txt"), b"OLD")
    asked = []

    def handler(p):
        asked.append(p.kind)
        return "overwrite", True

    e = CopyEngine()
    e.prompt_handler = handler
    run(e, srcs, tmp_path / "d")
    assert asked == ["collision"]
    assert all((tmp_path / "d" / f"{n}.txt").read_bytes() == b"NEW" for n in range(3))


def test_copy_into_same_folder_makes_copy(tmp_path):
    s = write(str(tmp_path / "f.txt"), b"X")
    run(CopyEngine(Settings(collision=Collision.OVERWRITE)), [s], tmp_path)
    assert (tmp_path / "f (2).txt").read_bytes() == b"X"


def test_folder_into_itself_is_rejected(tree):
    e = run(CopyEngine(), [tree], tree / "sub")
    assert e.items[0].status == Status.ERROR
    assert "itself" in e.items[0].error


def test_missing_source_is_error(tmp_path):
    e = run(CopyEngine(), [tmp_path / "nope.txt"], tmp_path / "d")
    assert e.items[0].status == Status.ERROR
    assert e.errors


def test_error_prompt_skip(tmp_path, monkeypatch):
    s = write(str(tmp_path / "s" / "f.txt"))
    e = CopyEngine()
    seen = []

    def handler(p):
        seen.append((p.kind, p.message))
        return "skip", False

    e.prompt_handler = handler
    real_open = open

    def bad_open(path, mode="r", *a, **k):
        if str(path).endswith(".swcpart"):
            raise PermissionError(13, "Access is denied")
        return real_open(path, mode, *a, **k)

    monkeypatch.setattr("builtins.open", bad_open)
    run(e, [s], tmp_path / "d")
    assert seen and seen[0][0] == "error"
    assert e.items[0].status == Status.ERROR


def test_error_retry_then_succeeds(tmp_path, monkeypatch):
    s = write(str(tmp_path / "s" / "f.txt"), b"ok")
    e = CopyEngine(Settings(on_error=ErrorAction.RETRY, retries=3))
    real_open = open
    fails = {"n": 2}

    def flaky(path, mode="r", *a, **k):
        if str(path).endswith(".swcpart") and fails["n"]:
            fails["n"] -= 1
            raise OSError(5, "Device busy")
        return real_open(path, mode, *a, **k)

    monkeypatch.setattr("builtins.open", flaky)
    run(e, [s], tmp_path / "d")
    assert e.items[0].status == Status.DONE
    assert (tmp_path / "d" / "f.txt").read_bytes() == b"ok"


def test_pause_resume_and_cancel(tmp_path):
    s = write(str(tmp_path / "s" / "big.bin"), os.urandom(4 * 1024 * 1024))
    e = CopyEngine(Settings(buffer_kb=64, speed_limit_kbps=1024))
    e.add_job([s], str(tmp_path / "d"))
    time.sleep(0.5)
    e.pause()
    time.sleep(0.3)
    done = e.items[0].done
    time.sleep(0.4)
    assert e.items[0].done == done  # nothing moves while paused
    assert e.snapshot()["state"] == "Paused"
    e.resume()
    time.sleep(0.3)
    e.cancel_all()
    assert e.wait(10)
    assert e.items[0].status == Status.CANCELLED
    assert not (tmp_path / "d" / "big.bin").exists()
    assert not (tmp_path / "d" / "big.bin.swcpart").exists()
    # engine works again after a cancel
    s2 = write(str(tmp_path / "s" / "small.txt"))
    run(e, [s2], tmp_path / "d")
    assert (tmp_path / "d" / "small.txt").exists()


def test_skip_current(tmp_path):
    big = write(str(tmp_path / "s" / "1big.bin"), os.urandom(2 * 1024 * 1024))
    small = write(str(tmp_path / "s" / "2small.txt"))
    e = CopyEngine(Settings(buffer_kb=64, speed_limit_kbps=512))
    e.add_job([big, small], str(tmp_path / "d"))
    time.sleep(0.4)
    e.skip_current()
    e.settings.speed_limit_kbps = 0
    assert e.wait(10)
    assert e.items[0].status == Status.SKIPPED
    assert e.items[1].status == Status.DONE
    assert not (tmp_path / "d" / "1big.bin").exists()


def test_speed_limit(tmp_path):
    s = write(str(tmp_path / "s" / "f.bin"), os.urandom(600 * 1024))
    e = CopyEngine(Settings(buffer_kb=64, speed_limit_kbps=1024))
    t = time.monotonic()
    run(e, [s], tmp_path / "d")
    assert time.monotonic() - t >= 0.45


def test_queue_reorder_and_remove(tmp_path):
    srcs = [write(str(tmp_path / "s" / f"{n}.txt")) for n in range(4)]
    e = CopyEngine()
    e.pause()
    e.add_job(srcs, str(tmp_path / "d"))
    deadline = time.time() + 5
    while len(e.items) < 4 and time.time() < deadline:
        time.sleep(0.02)
    time.sleep(0.2)  # first item is already "in progress" (paused)
    pending = [i for i in e.items if i.status == Status.PENDING]
    names = [os.path.basename(i.src) for i in pending]
    assert names == ["1.txt", "2.txt", "3.txt"]
    e.move_items({pending[-1].id}, -1)
    assert [os.path.basename(i.src) for i in e.items[1:]] == ["1.txt", "3.txt", "2.txt"]
    e.remove_items({pending[0].id})
    assert len(e.items) == 3
    e.resume()
    assert e.wait(10)
    assert not (tmp_path / "d" / "1.txt").exists()
    assert (tmp_path / "d" / "3.txt").exists()


def test_queue_second_job_while_running(tmp_path):
    a = write(str(tmp_path / "s" / "a.bin"), os.urandom(512 * 1024))
    b = write(str(tmp_path / "s2" / "b.txt"))
    e = CopyEngine(Settings(buffer_kb=64, speed_limit_kbps=2048))
    e.add_job([a], str(tmp_path / "d"))
    time.sleep(0.1)
    e.add_job([b], str(tmp_path / "d2"), move=True)
    assert e.wait(10)
    assert (tmp_path / "d" / "a.bin").exists()
    assert (tmp_path / "d2" / "b.txt").exists()
    assert not os.path.exists(b)


def test_unique_name(tmp_path):
    write(str(tmp_path / "r.pdf"))
    write(str(tmp_path / "r (2).pdf"))
    assert unique_name(str(tmp_path / "r.pdf")).endswith("r (3).pdf")


def _totals_by_walking(e):
    """What snapshot() used to compute by walking every item (the slow way)."""
    tb = tf = db = df = 0
    for it in e.items:
        tb += it.size
        tf += 0 if it.is_dir else 1
        if it.status in (Status.DONE, Status.SKIPPED, Status.ERROR):
            db += it.size
            df += 0 if it.is_dir else 1
    return tb, tf, db, df


def test_running_totals_match_after_changes(tmp_path):
    srcs = [write(str(tmp_path / "s" / f"{n}.txt"), b"x" * (n + 1)) for n in range(30)]
    write(str(tmp_path / "d" / "3.txt"), b"old")
    e = CopyEngine(Settings(collision=Collision.SKIP))
    e.pause()
    e.add_job(srcs + [str(tmp_path / "missing.txt")], str(tmp_path / "d"))
    deadline = time.time() + 5
    while len(e.items) < 31 and time.time() < deadline:
        time.sleep(0.02)
    pending = [i for i in e.items if i.status == Status.PENDING]
    e.move_items({pending[-1].id}, -1)
    e.remove_items({pending[2].id, pending[5].id})
    e.resume()
    assert e.wait(10)
    s = e.snapshot()
    tb, tf, db, df = _totals_by_walking(e)
    assert (s["total_bytes"], s["files_total"], s["done_bytes"], s["files_done"]) == (tb, tf, db, df)
    assert s["files_done"] == s["files_total"] == 29  # 28 copied/skipped + 1 missing (error)
    assert e.pending_count() == 0
    e.clear_finished()
    s = e.snapshot()
    assert (s["total_bytes"], s["files_total"], s["done_bytes"]) == (0, 0, 0)


def test_totals_after_cancel(tmp_path):
    srcs = [write(str(tmp_path / "s" / f"{n}.bin"), os.urandom(200_000)) for n in range(10)]
    e = CopyEngine(Settings(buffer_kb=64, speed_limit_kbps=800))
    e.add_job(srcs, str(tmp_path / "d"))
    time.sleep(0.5)
    e.cancel_all()
    assert e.wait(10)
    s = e.snapshot()
    tb, tf, db, df = _totals_by_walking(e)
    assert (s["total_bytes"], s["files_total"], s["done_bytes"], s["files_done"]) == (tb, tf, db, df)
    assert s["files_done"] < s["files_total"]
    assert e.pending_count() == 0


def test_big_queue_stays_fast(tmp_path):
    """Thousands of small files: the per-file cost must not grow with the list (it froze the app)."""
    src = tmp_path / "many"
    for d in range(10):
        (src / f"d{d}").mkdir(parents=True)
    for i in range(6000):
        (src / f"d{i % 10}" / f"f{i}.txt").write_bytes(b"x")
    e = CopyEngine()
    t = time.monotonic()
    e.add_job([str(src)], str(tmp_path / "out"))
    calls = []
    while e.is_running:
        t0 = time.perf_counter()
        e.snapshot()
        e.pending_count()
        calls.append(time.perf_counter() - t0)
        time.sleep(0.01)
    assert e.wait(60)
    took = time.monotonic() - t
    assert e.snapshot()["files_done"] == 6000
    assert took < 30, took
    assert max(calls) < 0.05, max(calls)  # progress figures stay instant
