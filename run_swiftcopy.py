"""Start SwiftCopy (also the PyInstaller entry script)."""
import sys

if __name__ == "__main__":
    if "--hook-helper" in sys.argv:
        # The small Ctrl+V helper process: no window, no Qt.
        from swiftcopy.hookhelper import main as helper_main
        sys.exit(helper_main())
    from swiftcopy.app import main
    sys.exit(main())
