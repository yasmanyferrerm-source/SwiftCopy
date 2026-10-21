"""Main window for SwiftCopy."""
from __future__ import annotations

import os
import struct

from PySide6.QtCore import (
    QAbstractTableModel, QModelIndex, QSettings, QSize, Qt, QTimer, Signal,
)
from PySide6.QtGui import QAction, QColor, QIcon, QKeySequence, QPainter
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QFileDialog, QFormLayout,
    QFrame, QHBoxLayout, QHeaderView, QLabel, QListWidget, QMainWindow, QMenu,
    QMessageBox, QProgressBar, QPushButton, QScrollArea, QSpinBox, QSystemTrayIcon, QTableView,
    QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget,
)

from . import APP_NAME, __version__, integration, shell
from .dialogs import CollisionDialog, ErrorDialog
from .engine import (
    Collision, CopyEngine, ErrorAction, FINAL_STATES, Settings, Status, format_eta, format_size,
)

STATUS_COLORS = {
    Status.PENDING: "#6b7280",
    Status.COPYING: "#2563eb",
    Status.VERIFYING: "#7c3aed",
    Status.DONE: "#15803d",
    Status.SKIPPED: "#b45309",
    Status.ERROR: "#dc2626",
    Status.CANCELLED: "#6b7280",
}

STYLE = """
QMainWindow, QDialog { background: #f5f7fa; }
QWidget { font-size: 10pt; color: #1f2937; }
QFrame#card { background: #ffffff; border: 1px solid #e3e7ee; border-radius: 10px; }
QLabel#h { font-size: 11pt; font-weight: 600; }
QLabel#muted { color: #6b7280; }
QLabel#error { color: #dc2626; }
QLabel#big { font-size: 10.5pt; font-weight: 600; }
QPushButton { background: #ffffff; border: 1px solid #cfd6e0; border-radius: 6px; padding: 6px 14px; }
QPushButton:hover { background: #eef2f7; }
QPushButton:disabled { color: #a0a7b4; background: #f3f4f6; }
QPushButton#primary { background: #2563eb; color: white; border: 1px solid #1d4ed8; font-weight: 600; }
QPushButton#primary:hover { background: #1d4ed8; }
QPushButton#primary:disabled { background: #93b4f5; border-color: #93b4f5; }
QPushButton#danger { color: #b91c1c; }
QPushButton#danger:disabled { color: #a0a7b4; }
QScrollArea { border: none; background: #ffffff; }
QWidget#page { background: #ffffff; }
QListWidget, QTableView, QTableWidget, QComboBox, QSpinBox {
    background: #ffffff; border: 1px solid #d5dbe4; border-radius: 6px; }
QComboBox, QSpinBox { padding: 4px 6px; }
QHeaderView::section { background: #f3f5f8; border: none; border-bottom: 1px solid #e3e7ee;
    padding: 5px 6px; font-weight: 600; color: #4b5563; }
QTableView { gridline-color: transparent; selection-background-color: #dbeafe; selection-color: #111827; }
QProgressBar { background: #e8edf4; border: none; border-radius: 5px; text-align: center;
    height: 12px; color: transparent; }
QProgressBar::chunk { background: #2563eb; border-radius: 5px; }
QProgressBar#overall::chunk { background: #16a34a; }
QTabWidget::pane { border: 1px solid #e3e7ee; border-radius: 8px; background: #ffffff; top: -1px; }
QTabBar::tab { padding: 7px 16px; color: #4b5563; }
QTabBar::tab:selected { color: #1d4ed8; font-weight: 600; border-bottom: 2px solid #2563eb; }
"""


def clipboard_files() -> tuple[list[str], bool]:
    """Files copied (or cut) in Explorer: (paths, was_cut)."""
    md = QApplication.clipboard().mimeData()
    if md is None:
        return [], False
    paths = [u.toLocalFile() for u in md.urls() if u.isLocalFile()]
    cut = False
    for fmt in md.formats():  # Explorer marks Ctrl+X with "Preferred DropEffect" = 2
        if "Preferred DropEffect" in fmt:
            raw = bytes(md.data(fmt))
            if len(raw) >= 4 and struct.unpack("<I", raw[:4])[0] & 2:
                cut = True
    return paths, cut


def _truthy(v) -> bool:
    return str(v).lower() in ("1", "true", "yes")


# ------------------------------------------------------------------- drop list
class SourceList(QListWidget):
    """List of sources; accepts files dragged from Explorer."""

    changed = Signal()

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setMinimumHeight(90)
        self.setMaximumHeight(150)

    def paths(self) -> list[str]:
        return [self.item(i).data(Qt.UserRole) for i in range(self.count())]

    def add_paths(self, paths) -> None:
        existing = {os.path.normcase(p) for p in self.paths()}
        for p in paths:
            p = os.path.normpath(p)
            if not p or os.path.normcase(p) in existing:
                continue
            existing.add(os.path.normcase(p))
            icon = "📁" if os.path.isdir(p) else "📄"
            self.addItem(f"{icon}  {p}")
            self.item(self.count() - 1).setData(Qt.UserRole, p)
        self.changed.emit()

    def remove_selected(self) -> None:
        for it in self.selectedItems():
            self.takeItem(self.row(it))
        self.changed.emit()

    def clear_all(self) -> None:
        self.clear()
        self.changed.emit()

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dragMoveEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        self.add_paths(u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile())
        e.acceptProposedAction()

    def paintEvent(self, e):
        super().paintEvent(e)
        if self.count() == 0:
            p = QPainter(self.viewport())
            p.setPen(QColor("#9ca3af"))
            p.drawText(self.viewport().rect(), Qt.AlignCenter,
                       "Drag files and folders here\nor use Add files / Add folder / Paste (Ctrl+V)")


# ----------------------------------------------------------------- queue model
class QueueModel(QAbstractTableModel):
    HEADERS = ["Status", "Name", "Size", "Progress", "From", "To"]

    def __init__(self, engine: CopyEngine):
        super().__init__()
        self.engine = engine
        self._rows: list = []

    def refresh(self) -> None:
        items = list(self.engine.items)
        if len(items) != len(self._rows) or any(a is not b for a, b in zip(items, self._rows)):
            self.beginResetModel()
            self._rows = items
            self.endResetModel()
        elif items:
            self.dataChanged.emit(self.index(0, 0), self.index(len(items) - 1, len(self.HEADERS) - 1))

    def item_at(self, row: int):
        return self._rows[row] if 0 <= row < len(self._rows) else None

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent=QModelIndex()):
        return len(self.HEADERS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return self.HEADERS[section]
        return None

    def data(self, index, role=Qt.DisplayRole):
        it = self.item_at(index.row())
        if it is None:
            return None
        col = index.column()
        if role == Qt.DisplayRole:
            if col == 0:
                return it.status.value
            if col == 1:
                return os.path.basename(it.src) + ("\\" if it.is_dir else "")
            if col == 2:
                return "" if it.is_dir else format_size(it.size)
            if col == 3:
                if it.is_dir or it.status in (Status.PENDING, Status.CANCELLED):
                    return ""
                if it.status in FINAL_STATES:
                    return "100%" if it.status == Status.DONE else ""
                return f"{(it.done / it.size * 100) if it.size else 100:.0f}%"
            if col == 4:
                return os.path.dirname(it.src)
            if col == 5:
                return os.path.dirname(it.final_dst or it.dst)
        if role == Qt.ForegroundRole and col == 0:
            return QColor(STATUS_COLORS.get(it.status, "#111827"))
        if role == Qt.ToolTipRole:
            tip = f"{it.src}\n→ {it.final_dst or it.dst}"
            return tip + (f"\n\n{it.error}" if it.error else "")
        if role == Qt.TextAlignmentRole and col in (2, 3):
            return int(Qt.AlignRight | Qt.AlignVCenter)
        return None


# ----------------------------------------------------------------- main window
def card() -> tuple[QFrame, QVBoxLayout]:
    f = QFrame()
    f.setObjectName("card")
    lay = QVBoxLayout(f)
    lay.setContentsMargins(14, 12, 14, 14)
    lay.setSpacing(8)
    return f, lay


class MainWindow(QMainWindow):
    def __init__(self, icon: QIcon):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(icon)
        self.resize(980, 760)
        self.setMinimumSize(QSize(760, 600))

        self.store = QSettings(APP_NAME, APP_NAME)
        self.engine = CopyEngine(self._load_settings())
        self._showing_prompt = False
        self._was_running = False
        self._error_rows = 0
        self._quitting = False
        self._tray_hint_shown = False

        self.tray = QSystemTrayIcon(icon, self) if QSystemTrayIcon.isSystemTrayAvailable() else None
        if self.tray:
            self.tray.setToolTip(APP_NAME)
            self.tray.activated.connect(self._tray_clicked)
            menu = QMenu(self)
            menu.addAction("Open SwiftCopy", self.bring_to_front)
            self.tray_pause = menu.addAction("Pause", self.toggle_pause)
            menu.addSeparator()
            menu.addAction("Quit SwiftCopy", self.quit_app)
            self.tray.setContextMenu(menu)
            self.tray.show()

        # Ctrl+V in File Explorer goes through SwiftCopy
        self.paste_hook = integration.PasteHook(
            self.explorer_paste, lambda fn: QTimer.singleShot(0, fn))
        if integration.IS_WIN and _truthy(self.store.value("intercept_paste", True)):
            self.paste_hook.install()
        if integration.IS_WIN and integration.frozen():
            try:  # keep startup / right-click entries pointing at this copy of the app
                integration.refresh_registered_paths()
            except OSError:
                pass

        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(12)
        self.setCentralWidget(central)

        root.addWidget(self._build_new_transfer())
        root.addWidget(self._build_progress())
        root.addWidget(self._build_tabs(), 1)

        paste = QAction(self)
        paste.setShortcut(QKeySequence.Paste)
        paste.triggered.connect(self.paste_from_clipboard)
        self.addAction(paste)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(200)
        self.tick()

    # ---------------------------------------------------------------- layout
    def _build_new_transfer(self) -> QWidget:
        f, lay = card()
        head = QHBoxLayout()
        h = QLabel("New transfer")
        h.setObjectName("h")
        head.addWidget(h)
        head.addStretch(1)
        for label, slot in [("Add files…", self.add_files), ("Add folder…", self.add_folder),
                            ("Paste", self.paste_from_clipboard), ("Remove", None), ("Clear", None)]:
            b = QPushButton(label)
            if label == "Remove":
                b.clicked.connect(lambda: self.sources.remove_selected())
            elif label == "Clear":
                b.clicked.connect(lambda: self.sources.clear_all())
            else:
                b.clicked.connect(slot)
            head.addWidget(b)
        lay.addLayout(head)

        self.sources = SourceList()
        self.sources.changed.connect(self._update_buttons)
        lay.addWidget(self.sources)

        row = QHBoxLayout()
        row.addWidget(QLabel("Destination"))
        self.dest = QComboBox()
        self.dest.setEditable(True)
        self.dest.setInsertPolicy(QComboBox.NoInsert)
        self.dest.lineEdit().setPlaceholderText("Choose the folder to copy into")
        for d in self.store.value("recent_destinations", [], list) or []:
            self.dest.addItem(d)
        self.dest.setCurrentText("")
        self.dest.editTextChanged.connect(self._update_buttons)
        row.addWidget(self.dest, 1)
        browse = QPushButton("Browse…")
        browse.clicked.connect(self.browse_dest)
        row.addWidget(browse)
        self.copy_btn = QPushButton("Copy")
        self.copy_btn.setObjectName("primary")
        self.copy_btn.setMinimumWidth(90)
        self.copy_btn.clicked.connect(lambda: self.start(move=False))
        self.move_btn = QPushButton("Move")
        self.move_btn.setObjectName("primary")
        self.move_btn.setMinimumWidth(90)
        self.move_btn.clicked.connect(lambda: self.start(move=True))
        row.addWidget(self.copy_btn)
        row.addWidget(self.move_btn)
        lay.addLayout(row)
        return f

    def _build_progress(self) -> QWidget:
        f, lay = card()
        top = QHBoxLayout()
        self.state_lbl = QLabel("Idle")
        self.state_lbl.setObjectName("h")
        top.addWidget(self.state_lbl)
        top.addStretch(1)
        self.pause_btn = QPushButton("Pause")
        self.pause_btn.clicked.connect(self.toggle_pause)
        self.skip_btn = QPushButton("Skip file")
        self.skip_btn.clicked.connect(self.engine.skip_current)
        self.cancel_btn = QPushButton("Cancel all")
        self.cancel_btn.setObjectName("danger")
        self.cancel_btn.clicked.connect(self.cancel_all)
        for b in (self.pause_btn, self.skip_btn, self.cancel_btn):
            top.addWidget(b)
        lay.addLayout(top)

        self.file_lbl = QLabel("Nothing to copy yet")
        self.file_lbl.setObjectName("big")
        lay.addWidget(self.file_lbl)
        self.file_path_lbl = QLabel("")
        self.file_path_lbl.setObjectName("muted")
        lay.addWidget(self.file_path_lbl)
        self.file_bar = QProgressBar()
        self.file_bar.setRange(0, 1000)
        lay.addWidget(self.file_bar)

        lay.addSpacing(4)
        orow = QHBoxLayout()
        ol = QLabel("Overall")
        ol.setObjectName("big")
        orow.addWidget(ol)
        orow.addStretch(1)
        self.pct_lbl = QLabel("0%")
        self.pct_lbl.setObjectName("big")
        orow.addWidget(self.pct_lbl)
        lay.addLayout(orow)
        self.total_bar = QProgressBar()
        self.total_bar.setObjectName("overall")
        self.total_bar.setRange(0, 1000)
        lay.addWidget(self.total_bar)

        self.stats_lbl = QLabel("")
        self.stats_lbl.setObjectName("muted")
        lay.addWidget(self.stats_lbl)
        return f

    def _build_tabs(self) -> QWidget:
        self.tabs = QTabWidget()

        # Queue
        qw = QWidget()
        ql = QVBoxLayout(qw)
        ql.setContentsMargins(8, 8, 8, 8)
        self.model = QueueModel(self.engine)
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(24)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        self.table.setStyleSheet("alternate-background-color: #f8fafc;")
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.Interactive)
        for col, w in enumerate([80, 220, 80, 70, 220]):
            self.table.setColumnWidth(col, w)
        hh.setStretchLastSection(True)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.queue_menu)
        self.table.doubleClicked.connect(self._open_row)
        ql.addWidget(self.table)
        qb = QHBoxLayout()
        for label, slot in [("Move up", lambda: self._move_sel(-1)),
                            ("Move down", lambda: self._move_sel(1)),
                            ("Remove from queue", self._remove_sel),
                            ("Clear finished", self._clear_finished)]:
            b = QPushButton(label)
            b.clicked.connect(slot)
            qb.addWidget(b)
        qb.addStretch(1)
        ql.addLayout(qb)
        self.tabs.addTab(qw, "Queue")

        # Errors
        ew = QWidget()
        el = QVBoxLayout(ew)
        el.setContentsMargins(8, 8, 8, 8)
        self.err_table = QTableWidget(0, 2)
        self.err_table.setHorizontalHeaderLabels(["File", "Problem"])
        self.err_table.verticalHeader().hide()
        self.err_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.err_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.err_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.err_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        el.addWidget(self.err_table)
        eb = QHBoxLayout()
        retry = QPushButton("Retry failed files")
        retry.clicked.connect(self.retry_failed)
        save = QPushButton("Save error log…")
        save.clicked.connect(self.save_errors)
        eb.addWidget(retry)
        eb.addWidget(save)
        eb.addStretch(1)
        el.addLayout(eb)
        self.tabs.addTab(ew, "Errors")

        # Settings (scrolls when the window is short)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self._build_settings())
        self.tabs.addTab(scroll, "Settings")
        return self.tabs

    def _build_settings(self) -> QWidget:
        w = QWidget()
        w.setObjectName("page")
        outer = QVBoxLayout(w)
        outer.setContentsMargins(16, 14, 16, 14)
        form = QFormLayout()
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(10)
        s = self.engine.settings

        self.set_collision = QComboBox()
        for label, val in [("Ask me", Collision.ASK), ("Overwrite", Collision.OVERWRITE),
                           ("Overwrite if newer", Collision.NEWER),
                           ("Overwrite if size or date differ", Collision.DIFFERENT),
                           ("Keep both (rename)", Collision.RENAME), ("Skip", Collision.SKIP)]:
            self.set_collision.addItem(label, val.value)
        self.set_collision.setCurrentIndex(self.set_collision.findData(s.collision.value))
        form.addRow("When a file already exists", self.set_collision)

        self.set_error = QComboBox()
        for label, val in [("Ask me", ErrorAction.ASK), ("Retry, then skip", ErrorAction.RETRY),
                           ("Skip and log it", ErrorAction.SKIP), ("Cancel everything", ErrorAction.CANCEL)]:
            self.set_error.addItem(label, val.value)
        self.set_error.setCurrentIndex(self.set_error.findData(s.on_error.value))
        form.addRow("When a file can't be copied", self.set_error)

        self.set_retries = QSpinBox()
        self.set_retries.setRange(1, 20)
        self.set_retries.setValue(s.retries)
        form.addRow("Retries", self.set_retries)

        self.set_buffer = QComboBox()
        for kb in (256, 512, 1024, 4096, 8192, 16384):
            self.set_buffer.addItem(f"{kb // 1024} MB" if kb >= 1024 else f"{kb} KB", kb)
        idx = self.set_buffer.findData(s.buffer_kb)
        self.set_buffer.setCurrentIndex(idx if idx >= 0 else 2)
        form.addRow("Copy buffer", self.set_buffer)

        self.set_speed = QSpinBox()
        self.set_speed.setRange(0, 10_000_000)
        self.set_speed.setSingleStep(1024)
        self.set_speed.setSuffix(" KB/s")
        self.set_speed.setSpecialValueText("Unlimited")
        self.set_speed.setValue(s.speed_limit_kbps)
        form.addRow("Speed limit", self.set_speed)

        self.set_verify = QCheckBox("Verify every file after copying (slower, catches bad copies)")
        self.set_verify.setChecked(s.verify)
        form.addRow("", self.set_verify)
        self.set_times = QCheckBox("Keep original modified dates")
        self.set_times.setChecked(s.keep_timestamps)
        form.addRow("", self.set_times)

        self.set_finish = QComboBox()
        self.set_finish.addItems(["Show a notification", "Do nothing", "Close the window"])
        self.set_finish.setCurrentIndex(int(self.store.value("when_finished", 0)))
        form.addRow("When everything is done", self.set_finish)
        outer.addLayout(form)

        for wdg in (self.set_collision, self.set_error, self.set_buffer, self.set_finish):
            wdg.currentIndexChanged.connect(self._apply_settings)
        for wdg in (self.set_retries, self.set_speed):
            wdg.valueChanged.connect(self._apply_settings)
        for wdg in (self.set_verify, self.set_times):
            wdg.toggled.connect(self._apply_settings)

        outer.addSpacing(10)
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color: #e5e7eb;")
        outer.addWidget(sep)
        ex = QLabel("Windows integration")
        ex.setObjectName("h")
        outer.addWidget(ex)
        hint = QLabel("All of these are for your user only — no admin rights needed.")
        hint.setObjectName("muted")
        outer.addWidget(hint)

        win = integration.IS_WIN
        self.int_paste = QCheckBox("Use SwiftCopy as the default copier — Ctrl+V in File Explorer "
                                   "and on the desktop copies with SwiftCopy")
        self.int_paste.setChecked(win and self.paste_hook.active)
        self.int_menu = QCheckBox("Add “Paste with SwiftCopy” to the right-click menu")
        self.int_menu.setChecked(integration.context_menu_enabled())
        self.int_sendto = QCheckBox("Add SwiftCopy to the right-click “Send to” menu")
        self.int_sendto.setChecked(shell.is_installed())
        self.int_startup = QCheckBox("Start SwiftCopy with Windows (in the tray, next to the clock)")
        self.int_startup.setChecked(integration.autostart_enabled())
        self.int_tray = QCheckBox("Keep running in the tray when the window is closed")
        self.int_tray.setChecked(_truthy(self.store.value("keep_in_tray", True)))
        for cb in (self.int_paste, self.int_menu, self.int_sendto, self.int_startup, self.int_tray):
            cb.setEnabled(win if cb is not self.int_tray else self.tray is not None)
            outer.addWidget(cb)
        self.int_paste.toggled.connect(self._toggle_paste_hook)
        self.int_menu.toggled.connect(lambda on: self._apply_integration(integration.set_context_menu, on))
        self.int_sendto.toggled.connect(self._toggle_sendto)
        self.int_startup.toggled.connect(lambda on: self._apply_integration(integration.set_autostart, on))
        self.int_tray.toggled.connect(lambda on: self.store.setValue("keep_in_tray", on))
        note = QLabel("The Ctrl+V takeover works while SwiftCopy is running, so keep “Start with "
                      "Windows” on. Dragging files with the mouse still uses Windows’ own copy — "
                      "right-click → Paste with SwiftCopy covers that.")
        note.setObjectName("muted")
        note.setWordWrap(True)
        outer.addWidget(note)
        outer.addStretch(1)
        ver = QLabel(f"{APP_NAME} {__version__}")
        ver.setObjectName("muted")
        outer.addWidget(ver)
        return w

    # --------------------------------------------------------------- settings
    def _load_settings(self) -> Settings:
        st = self.store
        d = Settings()

        def get(key, default, typ):
            try:
                return typ(st.value(key, default))
            except (TypeError, ValueError):
                return default

        try:
            collision = Collision(st.value("collision", d.collision.value))
            on_error = ErrorAction(st.value("on_error", d.on_error.value))
        except ValueError:
            collision, on_error = d.collision, d.on_error
        truthy = lambda v: str(v).lower() in ("1", "true", "yes")  # noqa: E731
        return Settings(
            collision=collision,
            on_error=on_error,
            retries=get("retries", d.retries, int),
            buffer_kb=get("buffer_kb", d.buffer_kb, int),
            speed_limit_kbps=get("speed_limit_kbps", d.speed_limit_kbps, int),
            verify=truthy(st.value("verify", d.verify)),
            keep_timestamps=truthy(st.value("keep_timestamps", d.keep_timestamps)),
        )

    def _apply_settings(self, *_):
        s = self.engine.settings
        s.collision = Collision(self.set_collision.currentData())
        s.on_error = ErrorAction(self.set_error.currentData())
        s.retries = self.set_retries.value()
        s.buffer_kb = int(self.set_buffer.currentData())
        s.speed_limit_kbps = self.set_speed.value()
        s.verify = self.set_verify.isChecked()
        s.keep_timestamps = self.set_times.isChecked()
        st = self.store
        st.setValue("collision", s.collision.value)
        st.setValue("on_error", s.on_error.value)
        st.setValue("retries", s.retries)
        st.setValue("buffer_kb", s.buffer_kb)
        st.setValue("speed_limit_kbps", s.speed_limit_kbps)
        st.setValue("verify", s.verify)
        st.setValue("keep_timestamps", s.keep_timestamps)
        st.setValue("when_finished", self.set_finish.currentIndex())

    def _apply_integration(self, fn, on: bool):
        try:
            fn(on)
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, APP_NAME, f"Couldn't change that setting:\n{e}")

    def _toggle_sendto(self, on: bool):
        self._apply_integration(lambda v: shell.install_sendto() if v else shell.uninstall_sendto(), on)

    def _toggle_paste_hook(self, on: bool):
        self.store.setValue("intercept_paste", on)
        if on:
            if not self.paste_hook.install():
                QMessageBox.warning(self, APP_NAME, "Windows didn't allow SwiftCopy to watch for "
                                    "Ctrl+V. Right-click → Paste with SwiftCopy still works.")
                self.int_paste.blockSignals(True)
                self.int_paste.setChecked(False)
                self.int_paste.blockSignals(False)
                self.store.setValue("intercept_paste", False)
            elif not self.int_tray.isChecked():
                self.int_tray.setChecked(True)  # the takeover needs SwiftCopy to stay running
        else:
            self.paste_hook.uninstall()

    # ---------------------------------------------------------------- sources
    def add_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Add files")
        self.sources.add_paths(files)

    def add_folder(self):
        d = QFileDialog.getExistingDirectory(self, "Add folder")
        if d:
            self.sources.add_paths([d])

    def browse_dest(self):
        d = QFileDialog.getExistingDirectory(self, "Copy into", self.dest.currentText())
        if d:
            self.dest.setCurrentText(os.path.normpath(d))

    def paste_from_clipboard(self):
        paths, cut = clipboard_files()
        if not paths:
            self.statusBar().showMessage("Nothing to paste — copy files in Explorer first (Ctrl+C).", 4000)
            return
        self.sources.add_paths(paths)
        if cut:
            self.statusBar().showMessage("Files were cut in Explorer — use Move.", 5000)

    def explorer_paste(self, root_hwnd: int):
        """Ctrl+V caught in File Explorer: copy the clipboard files into that folder."""
        folder = integration.explorer_folder(root_hwnd)
        paths, cut = clipboard_files()
        if not folder or not paths:
            integration.send_native_paste()  # not a normal folder - let Explorer do it
            return
        self.engine.add_job(paths, folder, move=cut)
        if cut:
            QApplication.clipboard().clear()  # same as Explorer: cut files paste once
        self.tabs.setCurrentIndex(0)
        self.showNormal()
        self.raise_()

    def set_sources(self, paths, dest=None, move=False, autostart=False):
        self.sources.add_paths(paths)
        if dest:
            self.dest.setCurrentText(dest)
        if autostart and dest and self.sources.count():
            self.start(move=move)
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _update_buttons(self, *_):
        ok = self.sources.count() > 0 and bool(self.dest.currentText().strip())
        self.copy_btn.setEnabled(ok)
        self.move_btn.setEnabled(ok)

    # --------------------------------------------------------------- transfers
    def start(self, move: bool):
        dest = self.dest.currentText().strip().strip('"')
        srcs = self.sources.paths()
        if not srcs or not dest:
            return
        if not os.path.isdir(dest):
            r = QMessageBox.question(self, APP_NAME, f"The folder doesn't exist:\n{dest}\n\nCreate it?")
            if r != QMessageBox.Yes:
                return
            try:
                os.makedirs(dest, exist_ok=True)
            except OSError as e:
                QMessageBox.warning(self, APP_NAME, f"Couldn't create the folder:\n{e}")
                return
        self._remember_dest(dest)
        self.engine.add_job(srcs, dest, move=move)
        self.sources.clear_all()
        self.tabs.setCurrentIndex(0)

    def _remember_dest(self, dest: str):
        recent = [dest] + [d for d in (self.store.value("recent_destinations", [], list) or [])
                           if os.path.normcase(d) != os.path.normcase(dest)]
        recent = recent[:10]
        self.store.setValue("recent_destinations", recent)
        self.dest.blockSignals(True)
        self.dest.clear()
        self.dest.addItems(recent)
        self.dest.setCurrentText(dest)
        self.dest.blockSignals(False)

    def toggle_pause(self):
        if self.engine.is_paused:
            self.engine.resume()
        else:
            self.engine.pause()
        self.tick()

    def cancel_all(self):
        if not self.engine.is_running:
            return
        if QMessageBox.question(self, APP_NAME, "Cancel all remaining transfers?") == QMessageBox.Yes:
            self.engine.cancel_all()

    def retry_failed(self):
        failed = self.engine.take_failed()
        groups: dict = {}
        for it in failed:
            if os.path.exists(it.src):  # each file goes back to its own folder
                groups.setdefault((os.path.dirname(it.dst), it.move), []).append(it.src)
        for (dest, move), srcs in groups.items():
            self.engine.add_job(srcs, dest, move=move)

    def save_errors(self):
        if not self.engine.errors:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Save error log", "SwiftCopy errors.txt",
                                              "Text files (*.txt)")
        if path:
            with open(path, "w", encoding="utf-8") as f:
                for src, msg in self.engine.errors:
                    f.write(f"{src}\t{msg}\n")

    # ------------------------------------------------------------------ queue
    def _selected_ids(self) -> set:
        rows = {i.row() for i in self.table.selectionModel().selectedRows()}
        return {self.model.item_at(r).id for r in rows if self.model.item_at(r)}

    def _move_sel(self, direction):
        self.engine.move_items(self._selected_ids(), direction)
        self.model.refresh()

    def _remove_sel(self):
        self.engine.remove_items(self._selected_ids())
        self.model.refresh()

    def _clear_finished(self):
        self.engine.clear_finished()
        self.model.refresh()

    def _open_row(self, index):
        it = self.model.item_at(index.row())
        if it:
            target = it.final_dst if it.status == Status.DONE else it.src
            if os.path.exists(target):
                shell.open_in_explorer(target)

    def queue_menu(self, pos):
        index = self.table.indexAt(pos)
        it = self.model.item_at(index.row()) if index.isValid() else None
        m = QMenu(self)
        if it:
            m.addAction("Open source folder", lambda: shell.open_in_explorer(it.src)
                        if os.path.exists(it.src) else None)
            if it.status == Status.DONE:
                m.addAction("Open destination", lambda: shell.open_in_explorer(it.final_dst))
            m.addSeparator()
        m.addAction("Move up", lambda: self._move_sel(-1))
        m.addAction("Move down", lambda: self._move_sel(1))
        m.addAction("Remove from queue", self._remove_sel)
        m.addSeparator()
        m.addAction("Clear finished", self._clear_finished)
        m.exec(self.table.viewport().mapToGlobal(pos))

    # ------------------------------------------------------------------- tick
    def tick(self):
        snap = self.engine.snapshot()
        self.model.refresh()
        running = self.engine.is_running

        total, done = snap["total_bytes"], snap["done_bytes"]
        frac = done / total if total else (1.0 if snap["files_total"] and not running else 0.0)
        self.total_bar.setValue(int(frac * 1000))
        self.pct_lbl.setText(f"{frac * 100:.0f}%")

        cur = snap["current"]
        if cur is not None and running:
            self.file_lbl.setText(os.path.basename(cur.src))
            self.file_path_lbl.setText(f"{os.path.dirname(cur.src)}  →  {os.path.dirname(cur.dst)}")
            self.file_bar.setValue(int((cur.done / cur.size if cur.size else 1) * 1000))
            if cur is not getattr(self, "_last_cur", None):  # keep the active file in view
                self._last_cur = cur
                if not self.table.selectionModel().hasSelection():
                    for r, it in enumerate(self.model._rows):
                        if it is cur:
                            self.table.scrollTo(self.model.index(r, 0))
                            break
        elif not running:
            summary = self.engine.last_summary or {}
            if snap["files_total"]:
                if summary.get("cancelled"):
                    self.file_lbl.setText(f"Cancelled — {snap['files_done']:,} of "
                                          f"{snap['files_total']:,} files were finished")
                elif snap["errors"]:
                    self.file_lbl.setText(f"Finished with {snap['errors']} problem(s) — see Errors")
                else:
                    self.file_lbl.setText("All done")
            else:
                self.file_lbl.setText("Nothing to copy yet")
            self.file_path_lbl.setText("")
            self.file_bar.setValue(0)

        state = snap["state"]
        verb = "Moving" if cur is not None and cur.move else "Copying"
        self.state_lbl.setText(verb if state == "Copying" else state)
        speed = snap["speed"]
        parts = [f"Files {snap['files_done']:,} / {snap['files_total']:,}",
                 f"{format_size(done)} of {format_size(total)}"]
        if running:
            parts.append(f"{format_size(speed)}/s")
            parts.append(f"{format_eta(snap['eta'])} left")
        if snap["errors"]:
            parts.append(f"{snap['errors']} error(s)")
        self.stats_lbl.setText("   ·   ".join(parts))

        self.pause_btn.setText("Resume" if self.engine.is_paused else "Pause")
        if self.tray:
            self.tray_pause.setText(self.pause_btn.text())
            self.tray_pause.setEnabled(running)
            self.tray.setToolTip(f"{APP_NAME} — {frac * 100:.0f}% {self.state_lbl.text()}"
                                 if running else APP_NAME)
        self.pause_btn.setEnabled(running)
        self.skip_btn.setEnabled(running and cur is not None)
        self.cancel_btn.setEnabled(running)
        self._update_buttons()

        title = APP_NAME
        if running:
            title = f"{frac * 100:.0f}% {self.state_lbl.text()} — {APP_NAME}"
        self.setWindowTitle(title)
        self.tabs.setTabText(1, f"Errors ({snap['errors']})" if snap["errors"] else "Errors")
        if len(self.engine.errors) != self._error_rows:
            self._fill_errors()

        if self.engine.prompt is not None and not self._showing_prompt:
            self._show_prompt()

        if self._was_running and not running:
            self._finished()
        self._was_running = running

    def _fill_errors(self):
        errs = list(self.engine.errors)
        self._error_rows = len(errs)
        self.err_table.setRowCount(len(errs))
        for r, (src, msg) in enumerate(errs):
            self.err_table.setItem(r, 0, QTableWidgetItem(src))
            self.err_table.setItem(r, 1, QTableWidgetItem(msg))

    def _show_prompt(self):
        p = self.engine.prompt
        if p is None:
            return
        self._showing_prompt = True
        try:
            self.showNormal()
            self.raise_()
            self.activateWindow()
            QApplication.alert(self)
            dlg = CollisionDialog(p, self) if p.kind == "collision" else ErrorDialog(p, self)
            dlg.exec()
            if self.engine.prompt is p:
                self.engine.answer_prompt(*dlg.result_tuple())
        finally:
            self._showing_prompt = False

    def _finished(self):
        s = self.engine.last_summary
        if not s:
            return
        msg = f"{s['done']:,} file(s) finished"
        if s["skipped"]:
            msg += f", {s['skipped']} skipped"
        if s["errors"]:
            msg += f", {s['errors']} failed"
        if s["cancelled"]:
            msg += f", {s['cancelled']} cancelled"
        self.statusBar().showMessage(msg, 15000)
        choice = self.set_finish.currentIndex()
        if choice == 0 and self.tray and not self.isActiveWindow():
            self.tray.showMessage(APP_NAME, msg, QSystemTrayIcon.Information, 6000)
        elif choice == 2 and not s["errors"] and not self.engine.items_pending():
            self.close()

    # ------------------------------------------------------------------ close
    def bring_to_front(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _tray_clicked(self, reason):
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            if self.isVisible() and not self.isMinimized():
                self.hide()
            else:
                self.bring_to_front()

    def keeps_running_in_tray(self) -> bool:
        return self.tray is not None and _truthy(self.store.value("keep_in_tray", True))

    def quit_app(self):
        self._quitting = True
        if self.close():
            QApplication.quit()
        else:
            self._quitting = False

    def closeEvent(self, e):
        if not self._quitting and self.keeps_running_in_tray():
            # Closing the window just hides it; copies keep going and Ctrl+V keeps working.
            e.ignore()
            self.hide()
            if not self._tray_hint_shown:
                self._tray_hint_shown = True
                self.tray.showMessage(APP_NAME, "SwiftCopy is still running in the tray. "
                                      "Right-click its icon to quit.",
                                      QSystemTrayIcon.Information, 4000)
            return
        if self.engine.is_running:
            r = QMessageBox.question(self, APP_NAME,
                                     "Transfers are still running. Cancel them and quit?")
            if r != QMessageBox.Yes:
                e.ignore()
                return
            self.engine.cancel_all()
            self.engine.wait(5)
        self.paste_hook.uninstall()
        if self.tray:
            self.tray.hide()
        e.accept()
        QApplication.quit()
