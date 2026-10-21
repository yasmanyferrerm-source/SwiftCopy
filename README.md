# SwiftCopy

A file copy manager for Windows, in the spirit of SuperCopier / TeraCopy. One portable `SwiftCopy.exe` — no installer, no admin rights.

## What it does

- **Queue** — add as many copy or move jobs as you like; they run one after another. Reorder or remove waiting files.
- **Pause / Resume / Skip file / Cancel all** at any time. A cancelled or skipped file never leaves a half-written copy behind (files are written as `name.swcpart` and renamed when complete).
- **Live progress** — current file and overall progress, speed, time left, files and bytes done.
- **File already exists?** Ask me, Overwrite, Overwrite if newer, Overwrite if size/date differ, Keep both (`name (2).ext`), or Skip — with "do this for all".
- **Errors don't stop the whole transfer** — Ask, Retry then skip, Skip and log, or Cancel. Failed files show on the Errors tab; retry them in one click or save the log.
- **Verify** (optional) — re-reads every copy and compares it with the original (BLAKE2 hash).
- **Move** — instant rename on the same drive; copy-then-delete across drives; empty source folders are cleaned up.
- **Speed limit** and copy buffer size.
- Keeps original modified dates; handles long paths (over 260 characters).
- **Explorer integration** — drag and drop onto the window, paste files you copied in Explorer (Ctrl+V), and an optional **Send to → SwiftCopy** entry (Settings tab).
- Single window: sending more files while it's open adds them to the running queue.

## Command line

```
SwiftCopy.exe [files/folders ...] [--dest FOLDER] [--move]
```

With `--dest` the transfer starts right away; without it the files are loaded and you pick the destination.

## Building

Run the **Build SwiftCopy** workflow (Actions tab → Run workflow, or the PC Build Tool). It runs the tests on Windows and publishes a GitHub Release with:

- `SwiftCopy-Setup-<version>.exe` — installer: installs for your user only (no admin rights), adds a Start menu shortcut, optional desktop shortcut and "Send to" entry, and an uninstaller in Settings → Apps. Running a newer Setup upgrades in place and keeps your settings.
- `SwiftCopy-Portable.exe` — single file, runs without installing.

Run from source: `pip install -r requirements.txt` then `python run_swiftcopy.py`. Tests: `pip install pytest` then `python -m pytest tests`.
