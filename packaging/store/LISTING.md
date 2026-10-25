# SwiftCopy: Microsoft Store submission

Copy each part into the matching Partner Center page.
App: **SwiftCopy**. Store ID: 9NQM6C42CZ54. Package: `SwiftCopy-Store-<version>.msix` from the GitHub release.

---

## 1. Pricing and availability

- **Markets:** all markets (default)
- **Visibility:** Public audience (make it discoverable in the Store)
- **Pricing:** Free
- **Release:** As soon as it passes certification

## 2. Properties

- **Category:** Utilities & tools
- **Subcategory:** File managers
- **Privacy policy URL:** https://github.com/yasmanyferrerm-source/SwiftCopy/blob/main/PRIVACY.md
- **Website:** https://github.com/yasmanyferrerm-source/SwiftCopy
- **Support contact info:** https://github.com/yasmanyferrerm-source/SwiftCopy/issues
- **Product declarations:** leave all unchecked, except **"This app has been tested to meet accessibility guidelines"**, which stays unchecked too
- **System requirements:** Minimum: Windows 10 version 2004 or later, x64. Leave the rest blank.

## 3. Age ratings

Answer the questionnaire:

- Category: **Utility, productivity, communication, or other app**
- Does the app allow users to interact or exchange content with others? **No**
- Does the app share the user's physical location with others? **No**
- Does the app allow purchases of digital goods? **No**
- Does the app contain unrestricted internet access (browser/search)? **No**
- Everything else: **No**

Expected result: rated for everyone (3+).

## 4. Packages

Upload `SwiftCopy-Store-<version>.msix`. Device family: **Windows 10/11 Desktop** (checked automatically).

## 5. Store listings: English (United States)

### Description

SwiftCopy is a fast, reliable file copy manager for Windows. It takes over the slow, all-or-nothing Windows copy dialog with a queue you control: pause, resume, skip a file, and decide what happens when a file already exists, without losing everything when one file fails.

Copy files in File Explorer and press Ctrl+V as usual. SwiftCopy picks up the paste and shows clear progress: overall and per-file percentage, speed, time left and how many files are done. Add more files while a copy is running and they join the queue.

When a file already exists, choose to overwrite, overwrite only if newer, keep both, or skip, and apply your choice to every conflict at once. If a file can't be copied, SwiftCopy keeps going and lists it under Problems so you can fix the cause and retry just the failed files.

Need extra safety? Turn on verification and SwiftCopy checks every copy against the original. Moving files on the same drive is instant, and empty folders are cleaned up after a move.

Make it yours with seven themes: Midnight, Daylight, Windows XP, Windows Vista, Windows 7, Futuristic and Matrix (falling green code while you copy).

SwiftCopy works entirely on your PC. No account, no ads, no tracking, and it never connects to the internet.

### Short description

Fast file copying with a queue, pause and resume, and smart handling of existing files.

### Product features (one per line)

Copy and move queue: add more files while a copy is running
Pause, resume, skip a file, or cancel at any time
Ctrl+V in File Explorer copies with SwiftCopy
Live progress: speed, time left, per-file and overall percentage
Overwrite, overwrite if newer, keep both or skip when a file exists
Problem files are skipped and listed so you can retry them
Optional verification checks every copy against the original
Instant moves on the same drive
Speed limit for copying over a network
Seven themes, including Windows XP, Vista, 7, Futuristic and Matrix
Starts with Windows in the tray, ready when you need it
No ads, no account, no tracking, works offline

### Screenshots

Upload the five PNG screenshots (1366×768), in order:

1. 1-queue-midnight.png: "Clear progress with speed, time left and a live queue"
2. 2-queue-windows7.png: "Windows 7 theme"
3. 3-queue-matrix.png: "Matrix theme with falling code"
4. 4-settings-themes.png: "Seven themes and simple settings"
5. 5-new-transfer-futuristic.png: "Pick files and a destination, then Copy or Move"

### Search terms (up to 7)

file copy, copy manager, teracopy, supercopier, file transfer, move files, fast copy

### Copyright and trademark info

© 2026 yasmanyfmSoft

## 6. Submission options: Notes for certification

Paste this into **Notes for certification**:

> SwiftCopy is a file copy manager (similar to TeraCopy/SuperCopier) packaged as a full-trust desktop app (Python/Qt).
>
> How to test: open SwiftCopy, click "Add folder…", pick any folder, type or browse to a destination folder and click Copy. Progress and the queue appear. Pause/Resume/Skip/Cancel work during the copy.
>
> Optional Ctrl+V feature (Settings > Windows): when on, copying files in File Explorer (Ctrl+C) and pressing Ctrl+V in another Explorer folder hands the paste to SwiftCopy. It uses a low-level keyboard hook that only reacts to Ctrl+V when File Explorer or the desktop is the active window with its file list focused; every other key is passed straight through and nothing is recorded or transmitted. Users can turn it off in Settings.
>
> The app starts in the system tray at sign-in via a startup task (users can disable it in Windows Settings > Apps > Startup). No network access, no accounts, no data collection.

### Restricted capability: runFullTrust

If asked why the app needs **runFullTrust**, paste:

> SwiftCopy is a classic Win32 desktop application (Python/Qt) converted to MSIX. It needs full trust to read and write files in any folder the user chooses to copy or move (including other drives and network shares), to show a system tray icon, and to provide the optional Ctrl+V integration with File Explorer.
