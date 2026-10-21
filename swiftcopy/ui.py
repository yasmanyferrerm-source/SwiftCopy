"""Main window for SwiftCopy."""
from __future__ import annotations

import os
import random
import struct

from PySide6.QtCore import (
    QAbstractTableModel, QModelIndex, QPointF, QRectF, QSettings, QSize, Qt, QTimer, Signal,
)
from PySide6.QtGui import (
    QAction, QColor, QFont, QIcon, QKeySequence, QLinearGradient, QPainter, QPainterPath, QPen,
)
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QButtonGroup, QCheckBox, QComboBox, QFileDialog, QFrame,
    QGridLayout, QHBoxLayout, QHeaderView, QLabel, QListWidget, QMainWindow, QMenu, QMessageBox,
    QProgressBar, QPushButton, QScrollArea, QSizePolicy, QSpinBox, QStackedWidget,
    QStyledItemDelegate, QSystemTrayIcon, QTableView, QTableWidget, QTableWidgetItem, QVBoxLayout,
    QWidget,
)

from . import APP_NAME, __version__, integration, shell, theme
from .dialogs import CollisionDialog, ErrorDialog
from .engine import (
    Collision, CopyEngine, ErrorAction, FINAL_STATES, Settings, Status, format_eta, format_size,
)


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


def repolish(w: QWidget) -> None:
    w.style().unpolish(w)
    w.style().polish(w)
    w.update()


def label(text: str = "", name: str | None = None, wrap=False) -> QLabel:
    lb = QLabel(text)
    if name:
        lb.setObjectName(name)
    lb.setWordWrap(wrap)
    return lb


def status_color(st: Status) -> QColor:
    t = theme.current
    return QColor({
        Status.PENDING: t["faint"], Status.COPYING: t["copy"], Status.VERIFYING: t["copy"],
        Status.DONE: t["ok"], Status.SKIPPED: t["move"], Status.ERROR: t["bad"],
        Status.CANCELLED: t["faint"],
    }.get(st, t["text"]))


# --------------------------------------------------------------------- widgets
class ElideLabel(QLabel):
    """Label that shortens long paths in the middle instead of stretching the window."""

    def __init__(self, text="", name=None, mode=Qt.ElideMiddle):
        super().__init__()
        if name:
            self.setObjectName(name)
        self._full = text
        self._mode = mode
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.setText(text)

    def setText(self, text):  # noqa: N802
        self._full = text or ""
        self.setToolTip(self._full)
        super().setText(self.fontMetrics().elidedText(self._full, self._mode, max(self.width(), 40)))

    def resizeEvent(self, e):
        super().setText(self.fontMetrics().elidedText(self._full, self._mode, max(self.width(), 40)))
        super().resizeEvent(e)


class SourceList(QListWidget):
    """Files and folders waiting to be copied; accepts drops from Explorer."""

    changed = Signal()

    def __init__(self):
        super().__init__()
        self.setObjectName("sources")
        self.setAcceptDrops(True)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setMinimumHeight(150)

    def paths(self) -> list[str]:
        return [self.item(i).data(Qt.UserRole) for i in range(self.count())]

    def add_paths(self, paths) -> None:
        existing = {os.path.normcase(p) for p in self.paths()}
        for p in paths:
            p = os.path.normpath(p)
            if not p or os.path.normcase(p) in existing:
                continue
            existing.add(os.path.normcase(p))
            kind = "Folder" if os.path.isdir(p) else "File"
            self.addItem(f"{os.path.basename(p) or p}    —    {os.path.dirname(p)}")
            it = self.item(self.count() - 1)
            it.setData(Qt.UserRole, p)
            it.setToolTip(f"{kind}: {p}")
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
        if self.count():
            return
        t = theme.current
        p = QPainter(self.viewport())
        p.setRenderHint(QPainter.Antialiasing)
        r = self.viewport().rect().adjusted(10, 10, -10, -10)
        pen = QPen(QColor(t["faint"]), 1.4, Qt.DashLine)
        p.setPen(pen)
        p.drawRoundedRect(QRectF(r), t["radius"] * 1.5, t["radius"] * 1.5)
        # tray-with-arrow glyph
        cx, cy = r.center().x(), r.center().y() - 20
        p.setPen(QPen(QColor(t["copy"]), 2.2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.drawLine(QPointF(cx, cy - 14), QPointF(cx, cy + 4))
        p.drawPolyline([QPointF(cx - 7, cy - 3), QPointF(cx, cy + 4), QPointF(cx + 7, cy - 3)])
        p.drawPolyline([QPointF(cx - 14, cy + 2), QPointF(cx - 14, cy + 10),
                        QPointF(cx + 14, cy + 10), QPointF(cx + 14, cy + 2)])
        p.setPen(QColor(t["text"]))
        f = QFont(self.font())
        f.setPointSizeF(f.pointSizeF() + 1)
        f.setBold(True)
        p.setFont(f)
        p.drawText(QRectF(r.left(), cy + 18, r.width(), 24), Qt.AlignCenter, "Drop files and folders here")
        p.setFont(self.font())
        p.setPen(QColor(t["muted"]))
        p.drawText(QRectF(r.left(), cy + 42, r.width(), 22), Qt.AlignCenter,
                   "or use the buttons below — Ctrl+V pastes files you copied in Explorer")


class HeroPanel(QFrame):
    """The progress panel. Paints a little theme decoration behind its contents:
    Aero gloss, a neon grid, or falling Matrix code."""

    GLYPHS = "ｱｲｳｴｵｶｷｸｹｺｻｼｽｾｿﾀﾁﾂﾃﾄﾅﾆﾇﾈﾉﾊﾋﾌﾍﾎﾏﾐﾑﾒﾓﾔﾕﾖﾗﾘﾙﾚﾛﾜ0123456789Z:.=*+-<>¦"

    def __init__(self):
        super().__init__()
        self.setObjectName("hero")
        self._drops: list[list] = []
        self._rain = QTimer(self)
        self._rain.timeout.connect(self._step_rain)
        self.busy = False

    def theme_changed(self):
        self._drops = []
        if theme.current["decor"] == "rain":
            self._rain.start(70)
        else:
            self._rain.stop()
        self.update()

    def _step_rain(self):
        if not self.isVisible():
            return
        col_w = 14
        cols = max(1, self.width() // col_w)
        if len(self._drops) != cols:
            self._drops = [[random.uniform(-self.height(), 0), random.uniform(2.5, 6.5),
                            [random.choice(self.GLYPHS) for _ in range(18)]] for _ in range(cols)]
        speed = 1.6 if self.busy else 0.6  # rains harder while copying
        for d in self._drops:
            d[0] += d[1] * speed
            if random.random() < 0.08:
                d[2][random.randrange(len(d[2]))] = random.choice(self.GLYPHS)
            if d[0] - len(d[2]) * 14 > self.height():
                d[0] = random.uniform(-80, 0)
                d[1] = random.uniform(2.5, 6.5)
        self.update()

    def paintEvent(self, e):
        super().paintEvent(e)
        decor = theme.current["decor"]
        if decor == "none":
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        rad = theme.current["radius"] * 2 + 2
        clip = QPainterPath()
        clip.addRoundedRect(r, rad, rad)
        p.setClipPath(clip)
        if decor == "gloss":
            g = QLinearGradient(0, 0, 0, r.height() * 0.5)
            g.setColorAt(0, QColor(255, 255, 255, 70 if theme.current["dark"] else 150))
            g.setColorAt(1, QColor(255, 255, 255, 8))
            p.fillRect(QRectF(r.left(), r.top(), r.width(), r.height() * 0.45), g)
        elif decor == "grid":
            c = QColor(theme.current["copy"])
            horizon = r.height() * 0.42
            for i in range(1, 9):  # receding horizontal lines
                y = horizon + (r.height() - horizon) * (i / 8) ** 1.8
                c.setAlpha(18 + i * 5)
                p.setPen(QPen(c, 1))
                p.drawLine(QPointF(r.left(), y), QPointF(r.right(), y))
            cx = r.center().x()
            c.setAlpha(34)
            p.setPen(QPen(c, 1))
            for i in range(-14, 15):  # lines converging on the horizon
                p.drawLine(QPointF(cx + i * 12, horizon), QPointF(cx + i * 110, r.bottom()))
            m = QColor(theme.current["move"])
            m.setAlpha(60)
            p.setPen(QPen(m, 1.2))
            p.drawLine(QPointF(r.left(), horizon), QPointF(r.right(), horizon))
        elif decor == "rain":
            f = QFont("Consolas")
            f.setPixelSize(13)
            p.setFont(f)
            base = QColor(theme.current["copy"])
            for i, (y, _speed, chars) in enumerate(self._drops):
                x = i * 14 + 2
                for j, ch in enumerate(chars):
                    cy = y - j * 14
                    if cy < -14 or cy > r.height() + 14:
                        continue
                    if j == 0:
                        col = QColor(200, 255, 210, 80)
                    else:
                        col = QColor(base)
                        col.setAlpha(max(0, 48 - j * 3))
                    p.setPen(col)
                    p.drawText(QPointF(x, cy), ch)
        p.end()


class NavButton(QPushButton):
    def __init__(self, text: str):
        super().__init__()
        self.setObjectName("nav")
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 0, 10, 0)
        self.text_lbl = QLabel(text)
        self.text_lbl.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.text_lbl.setStyleSheet("background: transparent; color: inherit;")
        self.badge = QLabel("")
        self.badge.setObjectName("badge")
        self.badge.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.badge.hide()
        lay.addWidget(self.text_lbl)
        lay.addStretch(1)
        lay.addWidget(self.badge, 0, Qt.AlignVCenter)
        self.setMinimumHeight(38)
        self.toggled.connect(lambda _: self._sync())

    def _sync(self):
        t = theme.current
        on = self.isChecked()
        self.text_lbl.setStyleSheet(
            f"background: transparent; color: {t['side_checked_text'] if on else t['side_text']};"
            f"font-weight: {600 if on else 400};")

    def set_badge(self, n: int, bad: bool = False):
        self.badge.setVisible(n > 0)
        self.badge.setText(f"{n:,}")
        tone = "bad" if bad else ""
        if self.badge.property("tone") != tone:
            self.badge.setProperty("tone", tone)
            repolish(self.badge)


class ThemeCard(QPushButton):
    """A small preview of a theme for the picker."""

    def __init__(self, key: str):
        super().__init__()
        self.key = key
        self.setObjectName("themeCard")
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(150, 112)
        self.setToolTip(theme.THEMES[key]["label"] if key in theme.THEMES else "Match Windows")

    def paintEvent(self, e):
        super().paintEvent(e)
        key = self.key if self.key in theme.THEMES else theme.resolve(self.key)[0]
        t = theme.THEMES[key]
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        box = QRectF(6, 6, self.width() - 12, 68)
        rad = min(t["radius"], 6)
        path = QPainterPath()
        path.addRoundedRect(box, rad, rad)
        p.setClipPath(path)
        p.fillRect(box, QColor(t["bg"]))
        side = QRectF(box.left(), box.top(), 34, box.height())
        sc = QColor(t["side_text"]) if self.key == "xp" else QColor(t["side_text"])
        p.fillRect(side, QColor("#6F8EDF") if key == "xp" else
                   QColor("#8BB6E6") if key == "win7" else
                   QColor("#0A1A24") if key == "vista" else QColor(t["bg"]).darker(115))
        p.fillRect(QRectF(side.left() + 5, side.top() + 10, 24, 6), sc)
        p.fillRect(QRectF(side.left() + 5, side.top() + 22, 18, 4), QColor(t["side_muted"]))
        panel = QRectF(box.left() + 40, box.top() + 8, box.width() - 46, box.height() - 16)
        p.setPen(QPen(QColor(t["border"]), 1))
        p.setBrush(QColor(t["panel"]) if key not in ("matrix",) else QColor("#000000"))
        p.drawRoundedRect(panel, rad, rad)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(t["copy"]))
        p.drawRect(QRectF(panel.left() + 6, panel.top() + 8, 26, 9))
        tr = QRectF(panel.left() + 6, panel.bottom() - 16, panel.width() - 12, 7)
        p.setBrush(QColor(t["line"]))
        p.drawRect(tr)
        p.setBrush(QColor(t["ok"] if key in ("xp", "vista", "win7") else t["copy"]))
        p.drawRect(QRectF(tr.left(), tr.top(), tr.width() * 0.62, tr.height()))
        p.setClipping(False)
        p.setPen(QColor(theme.current["text"]))
        f = QFont(self.font())
        f.setBold(self.isChecked())
        p.setFont(f)
        name = "Match Windows" if self.key == "system" else t["label"]
        p.drawText(QRectF(0, 80, self.width(), 24), Qt.AlignCenter, name)
        p.end()


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
            if col == 4:
                return os.path.dirname(it.src)
            if col == 5:
                return os.path.dirname(it.final_dst or it.dst)
        if role == Qt.UserRole:
            return it
        if role == Qt.ToolTipRole:
            tip = f"{it.src}\n→ {it.final_dst or it.dst}"
            return tip + (f"\n\n{it.error}" if it.error else "")
        if role == Qt.TextAlignmentRole and col == 2:
            return int(Qt.AlignRight | Qt.AlignVCenter)
        return None


class StatusDelegate(QStyledItemDelegate):
    def initStyleOption(self, opt, index):
        super().initStyleOption(opt, index)
        it = index.data(Qt.UserRole)
        if it is not None:
            opt.text = "●  " + it.status.value
            opt.palette.setColor(opt.palette.ColorRole.Text, status_color(it.status))
            opt.palette.setColor(opt.palette.ColorRole.HighlightedText, status_color(it.status))


class ProgressDelegate(QStyledItemDelegate):
    def paint(self, p, opt, index):
        super().paint(p, opt, index)
        it = index.data(Qt.UserRole)
        if it is None or it.is_dir or it.status in (Status.PENDING, Status.CANCELLED):
            return
        if it.status == Status.DONE:
            frac = 1.0
        elif it.status in (Status.COPYING, Status.VERIFYING):
            frac = it.done / it.size if it.size else 1.0
        else:
            return
        t = theme.current
        r = QRectF(opt.rect).adjusted(8, opt.rect.height() / 2 - 3, -8, -(opt.rect.height() / 2 - 3))
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(t["line"]))
        rad = min(t["radius"], 3)
        p.drawRoundedRect(r, rad, rad)
        fill = QColor(t["ok"] if it.status == Status.DONE else (t["move"] if it.move else t["copy"]))
        p.setBrush(fill)
        p.drawRoundedRect(QRectF(r.left(), r.top(), max(r.width() * frac, 3), r.height()), rad, rad)
        p.restore()


# ----------------------------------------------------------------- main window
def group(title: str | None = None, sub: str | None = None) -> tuple[QFrame, QVBoxLayout]:
    f = QFrame()
    f.setObjectName("group")
    lay = QVBoxLayout(f)
    lay.setContentsMargins(18, 14, 18, 16)
    lay.setSpacing(8)
    if title:
        lay.addWidget(label(title, "h2"))
    if sub:
        lay.addWidget(label(sub, "muted", wrap=True))
    return f, lay


class MainWindow(QMainWindow):
    PAGES = ["New transfer", "Queue", "Problems", "Settings"]

    def __init__(self, icon: QIcon):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(icon)
        self.icon = icon
        self.resize(1080, 780)
        self.setMinimumSize(QSize(900, 640))

        self.store = QSettings(APP_NAME, APP_NAME)
        self.engine = CopyEngine(self._load_settings())
        self._showing_prompt = False
        self._was_running = False
        self._error_rows = 0
        self._quitting = False
        self._tray_hint_shown = False
        self._last_cur = None

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
        central.setObjectName("central")
        outer = QHBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.setCentralWidget(central)

        outer.addWidget(self._build_sidebar())
        main = QWidget()
        main.setObjectName("page")
        ml = QVBoxLayout(main)
        ml.setContentsMargins(22, 20, 22, 14)
        ml.setSpacing(18)
        ml.addWidget(self._build_hero())
        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_new_page())
        self.stack.addWidget(self._build_queue_page())
        self.stack.addWidget(self._build_problems_page())
        self.stack.addWidget(self._build_settings_page())
        ml.addWidget(self.stack, 1)
        outer.addWidget(main, 1)
        self.go(0)

        paste = QAction(self)
        paste.setShortcut(QKeySequence.Paste)
        paste.triggered.connect(self.paste_from_clipboard)
        self.addAction(paste)

        self.theme_changed()
        try:  # follow Windows light/dark when "Match Windows" is picked
            QApplication.styleHints().colorSchemeChanged.connect(self._system_scheme_changed)
        except AttributeError:
            pass

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(200)
        self.tick()

    # ---------------------------------------------------------------- sidebar
    def _build_sidebar(self) -> QWidget:
        side = QFrame()
        side.setObjectName("sidebar")
        side.setFixedWidth(220)
        lay = QVBoxLayout(side)
        lay.setContentsMargins(14, 18, 14, 16)
        lay.setSpacing(4)
        brand = QHBoxLayout()
        logo = QLabel()
        logo.setPixmap(self.icon.pixmap(30, 30))
        logo.setStyleSheet("background: transparent;")
        brand.addWidget(logo)
        brand.addWidget(label(APP_NAME, "brand"))
        brand.addStretch(1)
        lay.addLayout(brand)
        lay.addSpacing(18)

        self.nav_group = QButtonGroup(self)
        self.nav: list[NavButton] = []
        for i, name in enumerate(self.PAGES):
            b = NavButton(name)
            b.clicked.connect(lambda _=False, i=i: self.go(i))
            self.nav_group.addButton(b, i)
            self.nav.append(b)
            lay.addWidget(b)
        lay.addStretch(1)
        self.hook_lbl = label("", "hookOn", wrap=True)
        lay.addWidget(self.hook_lbl)
        lay.addSpacing(4)
        lay.addWidget(label(f"Version {__version__}", "sideNote"))
        return side

    def go(self, i: int):
        self.stack.setCurrentIndex(i)
        self.nav[i].setChecked(True)
        for b in self.nav:
            b._sync()

    # ------------------------------------------------------------------- hero
    def _build_hero(self) -> QWidget:
        self.hero = HeroPanel()
        lay = QVBoxLayout(self.hero)
        lay.setContentsMargins(24, 18, 24, 20)
        lay.setSpacing(10)

        top = QHBoxLayout()
        top.setSpacing(18)
        self.pct_lbl = label("", "bigPct")
        self.pct_lbl.setProperty("mode", "copy")
        top.addWidget(self.pct_lbl, 0, Qt.AlignVCenter)
        titles = QVBoxLayout()
        titles.setSpacing(2)
        self.title_lbl = label("Ready", "heroTitle")
        self.sub_lbl = ElideLabel("", "heroSub", Qt.ElideRight)
        self.sub_lbl.setMinimumWidth(220)
        titles.addWidget(self.title_lbl)
        titles.addWidget(self.sub_lbl)
        top.addLayout(titles, 1)

        btns = QHBoxLayout()
        btns.setSpacing(6)
        self.pause_btn = QPushButton("Pause")
        self.pause_btn.clicked.connect(self.toggle_pause)
        self.skip_btn = QPushButton("Skip file")
        self.skip_btn.clicked.connect(self.engine.skip_current)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setObjectName("danger")
        self.cancel_btn.clicked.connect(self.cancel_all)
        for b in (self.pause_btn, self.skip_btn, self.cancel_btn):
            btns.addWidget(b)
        top.addLayout(btns)
        lay.addLayout(top)

        self.stats = {}
        stats_box = QHBoxLayout()
        stats_box.setContentsMargins(0, 0, 0, 0)
        stats_box.setSpacing(34)
        for key, name in (("speed", "Speed"), ("eta", "Time left"), ("size", "Copied"),
                          ("files", "Files")):
            col = QVBoxLayout()
            col.setSpacing(0)
            col.addWidget(label(name, "statLabel"))
            v = label("–", "statValue")
            col.addWidget(v)
            self.stats[key] = v
            stats_box.addLayout(col)
        stats_box.addStretch(1)
        self.stats_widget = QWidget()
        self.stats_widget.setStyleSheet("background: transparent;")
        self.stats_widget.setLayout(stats_box)
        lay.addWidget(self.stats_widget)

        self.detail = QWidget()
        self.detail.setStyleSheet("background: transparent;")
        dl = QVBoxLayout(self.detail)
        dl.setContentsMargins(0, 4, 0, 0)
        dl.setSpacing(8)
        lane = QHBoxLayout()
        lane.setSpacing(8)
        lane.addWidget(label("From", "laneLabel"))
        self.from_lbl = ElideLabel("", "lanePath")
        lane.addWidget(self.from_lbl, 1)
        lane.addWidget(label("→", "laneLabel"))
        lane.addWidget(label("To", "laneLabel"))
        self.to_lbl = ElideLabel("", "lanePath")
        lane.addWidget(self.to_lbl, 1)
        dl.addLayout(lane)
        frow = QHBoxLayout()
        self.file_lbl = ElideLabel("", "fileName")
        frow.addWidget(self.file_lbl, 1)
        self.file_pct = label("", "statLabel")
        frow.addWidget(self.file_pct)
        dl.addLayout(frow)
        self.file_bar = QProgressBar()
        self.file_bar.setObjectName("fileBar")
        self.file_bar.setRange(0, 1000)
        dl.addWidget(self.file_bar)
        lay.addWidget(self.detail)

        self.total_bar = QProgressBar()
        self.total_bar.setObjectName("totalBar")
        self.total_bar.setRange(0, 1000)
        lay.addWidget(self.total_bar)
        return self.hero

    # ------------------------------------------------------------------ pages
    def _page(self, title: str, sub: str) -> tuple[QWidget, QVBoxLayout]:
        w = QWidget()
        w.setObjectName("page")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)
        head = QVBoxLayout()
        head.setSpacing(2)
        head.addWidget(label(title, "h1"))
        head.addWidget(label(sub, "muted"))
        lay.addLayout(head)
        return w, lay

    def _build_new_page(self) -> QWidget:
        w, lay = self._page("New transfer", "Pick what to copy and where it goes.")
        zone = QFrame()
        zone.setObjectName("dropZone")
        zl = QVBoxLayout(zone)
        zl.setContentsMargins(8, 8, 8, 8)
        zl.setSpacing(6)
        self.sources = SourceList()
        self.sources.changed.connect(self._update_buttons)
        zl.addWidget(self.sources, 1)
        tools = QHBoxLayout()
        tools.setSpacing(6)
        for text, slot in [("Add files…", self.add_files), ("Add folder…", self.add_folder),
                           ("Paste", self.paste_from_clipboard)]:
            b = QPushButton(text)
            b.clicked.connect(slot)
            tools.addWidget(b)
        tools.addStretch(1)
        self.remove_btn = QPushButton("Remove selected")
        self.remove_btn.clicked.connect(lambda: self.sources.remove_selected())
        self.clear_btn = QPushButton("Clear list")
        self.clear_btn.clicked.connect(lambda: self.sources.clear_all())
        tools.addWidget(self.remove_btn)
        tools.addWidget(self.clear_btn)
        zl.addLayout(tools)
        lay.addWidget(zone, 1)

        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(label("Copy into", "h2"))
        self.dest = QComboBox()
        self.dest.setEditable(True)
        self.dest.setInsertPolicy(QComboBox.NoInsert)
        self.dest.lineEdit().setPlaceholderText("Choose a destination folder")
        for d in self.store.value("recent_destinations", [], list) or []:
            self.dest.addItem(d)
        self.dest.setCurrentText("")
        self.dest.editTextChanged.connect(self._update_buttons)
        row.addWidget(self.dest, 1)
        browse = QPushButton("Browse…")
        browse.clicked.connect(self.browse_dest)
        row.addWidget(browse)
        row.addSpacing(10)
        self.move_btn = QPushButton("Move")
        self.move_btn.setObjectName("moveBtn")
        self.move_btn.clicked.connect(lambda: self.start(move=True))
        self.copy_btn = QPushButton("Copy")
        self.copy_btn.setObjectName("copyBtn")
        self.copy_btn.clicked.connect(lambda: self.start(move=False))
        row.addWidget(self.move_btn)
        row.addWidget(self.copy_btn)
        lay.addLayout(row)
        return w

    def _build_queue_page(self) -> QWidget:
        w, lay = self._page("Queue", "Everything SwiftCopy is doing or has done. "
                                     "Double-click a file to show it in Explorer.")
        self.model = QueueModel(self.engine)
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(30)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        self.table.setWordWrap(False)
        self.table.setTextElideMode(Qt.ElideMiddle)
        self.table.setItemDelegateForColumn(0, StatusDelegate(self.table))
        self.table.setItemDelegateForColumn(3, ProgressDelegate(self.table))
        hh = self.table.horizontalHeader()
        hh.setHighlightSections(False)
        hh.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        for col, width in enumerate([110, 220, 80, 120, 200]):
            self.table.setColumnWidth(col, width)
        hh.setStretchLastSection(True)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.queue_menu)
        self.table.doubleClicked.connect(self._open_row)
        lay.addWidget(self.table, 1)
        qb = QHBoxLayout()
        for text, slot in [("Move up", lambda: self._move_sel(-1)),
                           ("Move down", lambda: self._move_sel(1)),
                           ("Remove from queue", self._remove_sel)]:
            b = QPushButton(text)
            b.clicked.connect(slot)
            qb.addWidget(b)
        qb.addStretch(1)
        clear = QPushButton("Clear finished")
        clear.clicked.connect(self._clear_finished)
        qb.addWidget(clear)
        lay.addLayout(qb)
        return w

    def _build_problems_page(self) -> QWidget:
        w, lay = self._page("Problems", "Files that couldn't be copied. Fix the cause, then retry them.")
        self.err_table = QTableWidget(0, 2)
        self.err_table.setHorizontalHeaderLabels(["File", "What went wrong"])
        self.err_table.verticalHeader().hide()
        self.err_table.verticalHeader().setDefaultSectionSize(30)
        self.err_table.setShowGrid(False)
        self.err_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.err_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.err_table.horizontalHeader().setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.err_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.err_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.err_empty = label("No problems. Files that can't be copied will show up here.", "muted")
        self.err_empty.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.err_table, 1)
        lay.addWidget(self.err_empty, 1)
        eb = QHBoxLayout()
        self.retry_btn = QPushButton("Retry failed files")
        self.retry_btn.setObjectName("primary")
        self.retry_btn.clicked.connect(self.retry_failed)
        self.save_err_btn = QPushButton("Save list…")
        self.save_err_btn.clicked.connect(self.save_errors)
        eb.addWidget(self.retry_btn)
        eb.addWidget(self.save_err_btn)
        eb.addStretch(1)
        lay.addLayout(eb)
        return w

    def _build_settings_page(self) -> QWidget:
        outer_w, outer = self._page("Settings", "Saved automatically.")
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        body = QWidget()
        body.setObjectName("page")
        lay = QVBoxLayout(body)
        lay.setContentsMargins(0, 0, 10, 10)
        lay.setSpacing(14)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)
        s = self.engine.settings

        # Appearance
        g, gl = group("Look", "Pick a theme. It changes right away.")
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(10)
        self.theme_group = QButtonGroup(self)
        self.theme_cards = []
        current_key = self.store.value("theme", "system")
        for i, key in enumerate(["system"] + theme.ORDER):
            card = ThemeCard(key)
            card.setChecked(key == current_key)
            card.clicked.connect(lambda _=False, k=key: self.set_theme(k))
            self.theme_group.addButton(card)
            self.theme_cards.append(card)
            grid.addWidget(card, i // 4, i % 4)
        grid.setColumnStretch(4, 1)
        gl.addLayout(grid)
        lay.addWidget(g)

        # Copying
        g, gl = group("Copying")
        form = QGridLayout()
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(10)
        self.set_collision = QComboBox()
        for text, val in [("Ask me", Collision.ASK), ("Overwrite", Collision.OVERWRITE),
                          ("Overwrite if newer", Collision.NEWER),
                          ("Overwrite if size or date differ", Collision.DIFFERENT),
                          ("Keep both (rename the new one)", Collision.RENAME), ("Skip it", Collision.SKIP)]:
            self.set_collision.addItem(text, val.value)
        self.set_collision.setCurrentIndex(self.set_collision.findData(s.collision.value))
        self.set_error = QComboBox()
        for text, val in [("Ask me", ErrorAction.ASK), ("Retry, then skip", ErrorAction.RETRY),
                          ("Skip it and list it under Problems", ErrorAction.SKIP),
                          ("Stop everything", ErrorAction.CANCEL)]:
            self.set_error.addItem(text, val.value)
        self.set_error.setCurrentIndex(self.set_error.findData(s.on_error.value))
        self.set_retries = QSpinBox()
        self.set_retries.setRange(1, 20)
        self.set_retries.setValue(s.retries)
        self.set_buffer = QComboBox()
        for kb in (256, 512, 1024, 4096, 8192, 16384):
            self.set_buffer.addItem(f"{kb // 1024} MB" if kb >= 1024 else f"{kb} KB", kb)
        idx = self.set_buffer.findData(s.buffer_kb)
        self.set_buffer.setCurrentIndex(idx if idx >= 0 else 2)
        self.set_speed = QSpinBox()
        self.set_speed.setRange(0, 10_000_000)
        self.set_speed.setSingleStep(1024)
        self.set_speed.setSuffix(" KB/s")
        self.set_speed.setSpecialValueText("No limit")
        self.set_speed.setValue(s.speed_limit_kbps)
        self.set_finish = QComboBox()
        self.set_finish.addItems(["Show a notification", "Do nothing", "Close the window"])
        self.set_finish.setCurrentIndex(int(self.store.value("when_finished", 0)))
        rows = [("When a file already exists", self.set_collision),
                ("When a file can't be copied", self.set_error),
                ("Retries", self.set_retries), ("Copy buffer", self.set_buffer),
                ("Speed limit", self.set_speed), ("When everything is done", self.set_finish)]
        for r, (text, wdg) in enumerate(rows):
            form.addWidget(label(text), r, 0)
            form.addWidget(wdg, r, 1)
        form.setColumnStretch(2, 1)
        gl.addLayout(form)
        self.set_verify = QCheckBox("Check every copy against the original (slower, catches bad copies)")
        self.set_verify.setChecked(s.verify)
        self.set_times = QCheckBox("Keep the original modified dates")
        self.set_times.setChecked(s.keep_timestamps)
        gl.addWidget(self.set_verify)
        gl.addWidget(self.set_times)
        lay.addWidget(g)
        for wdg in (self.set_collision, self.set_error, self.set_buffer, self.set_finish):
            wdg.currentIndexChanged.connect(self._apply_settings)
        for wdg in (self.set_retries, self.set_speed):
            wdg.valueChanged.connect(self._apply_settings)
        for wdg in (self.set_verify, self.set_times):
            wdg.toggled.connect(self._apply_settings)

        # Windows
        g, gl = group("Windows", "These only affect your user account. No admin rights needed.")
        win = integration.IS_WIN
        self.int_paste = QCheckBox("Use SwiftCopy when I press Ctrl+V in File Explorer or on the desktop")
        self.int_paste.setChecked(win and self.paste_hook.active)
        self.int_menu = QCheckBox("Show “Paste with SwiftCopy” when I right-click a folder")
        self.int_menu.setChecked(integration.context_menu_enabled())
        self.int_sendto = QCheckBox("Show SwiftCopy in the right-click “Send to” menu")
        self.int_sendto.setChecked(shell.is_installed())
        self.int_startup = QCheckBox("Start SwiftCopy when Windows starts (in the tray)")
        self.int_startup.setChecked(integration.autostart_enabled())
        self.int_tray = QCheckBox("Keep SwiftCopy running in the tray when I close the window")
        self.int_tray.setChecked(_truthy(self.store.value("keep_in_tray", True)))
        for cb in (self.int_paste, self.int_menu, self.int_sendto, self.int_startup, self.int_tray):
            cb.setEnabled(win if cb is not self.int_tray else self.tray is not None)
            gl.addWidget(cb)
        self.int_paste.toggled.connect(self._toggle_paste_hook)
        self.int_menu.toggled.connect(lambda on: self._apply_integration(integration.set_context_menu, on))
        self.int_sendto.toggled.connect(self._toggle_sendto)
        self.int_startup.toggled.connect(lambda on: self._apply_integration(integration.set_autostart, on))
        self.int_tray.toggled.connect(lambda on: self.store.setValue("keep_in_tray", on))
        gl.addWidget(label("Ctrl+V only goes through SwiftCopy while it's running. Dragging files "
                           "with the mouse still uses Windows' own copy.", "muted", wrap=True))
        lay.addWidget(g)
        lay.addStretch(1)
        return outer_w

    # ----------------------------------------------------------------- theming
    def set_theme(self, key: str):
        self.store.setValue("theme", key)
        for c in getattr(self, "theme_cards", []):
            c.setChecked(c.key == key)
        theme.apply(QApplication.instance(), key)
        self.theme_changed()

    def _system_scheme_changed(self, *_):
        if self.store.value("theme", "system") == "system":
            self.set_theme("system")

    def theme_changed(self):
        for b in self.nav:
            b._sync()
        self.hero.theme_changed()
        for c in getattr(self, "theme_cards", []):
            c.update()
        for w in (self.pct_lbl, self.file_bar, self.total_bar):
            repolish(w)
        theme.dark_title_bar(self, theme.current["dark"])
        self.table.viewport().update()
        self.sources.viewport().update()

    def showEvent(self, e):
        super().showEvent(e)
        theme.dark_title_bar(self, theme.current["dark"])

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
        return Settings(
            collision=collision,
            on_error=on_error,
            retries=get("retries", d.retries, int),
            buffer_kb=get("buffer_kb", d.buffer_kb, int),
            speed_limit_kbps=get("speed_limit_kbps", d.speed_limit_kbps, int),
            verify=_truthy(st.value("verify", d.verify)),
            keep_timestamps=_truthy(st.value("keep_timestamps", d.keep_timestamps)),
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
            self.statusBar().showMessage("Nothing to paste. Copy files in File Explorer first (Ctrl+C).", 4000)
            return
        self.go(0)
        self.sources.add_paths(paths)
        if cut:
            self.statusBar().showMessage("These files were cut in Explorer, so Move is probably what you want.", 6000)

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
        self.go(1)
        self.showNormal()
        self.raise_()

    def set_sources(self, paths, dest=None, move=False, autostart=False):
        self.go(0)
        self.sources.add_paths(paths)
        if dest:
            self.dest.setCurrentText(dest)
        if autostart and dest and self.sources.count():
            self.start(move=move)
        self.bring_to_front()

    def _update_buttons(self, *_):
        ok = self.sources.count() > 0 and bool(self.dest.currentText().strip())
        self.copy_btn.setEnabled(ok)
        self.move_btn.setEnabled(ok)
        has = self.sources.count() > 0
        self.remove_btn.setEnabled(has)
        self.clear_btn.setEnabled(has)

    # --------------------------------------------------------------- transfers
    def start(self, move: bool):
        dest = self.dest.currentText().strip().strip('"')
        srcs = self.sources.paths()
        if not srcs or not dest:
            return
        if not os.path.isdir(dest):
            r = QMessageBox.question(self, APP_NAME, f"This folder doesn't exist yet:\n{dest}\n\nCreate it?")
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
        self.go(1)

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
        if QMessageBox.question(self, APP_NAME, "Stop all remaining copies?") == QMessageBox.Yes:
            self.engine.cancel_all()

    def retry_failed(self):
        failed = self.engine.take_failed()
        groups: dict = {}
        for it in failed:
            if os.path.exists(it.src):  # each file goes back to its own folder
                groups.setdefault((os.path.dirname(it.dst), it.move), []).append(it.src)
        for (dest, move), srcs in groups.items():
            self.engine.add_job(srcs, dest, move=move)
        if groups:
            self.go(1)

    def save_errors(self):
        if not self.engine.errors:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Save list", "SwiftCopy problems.txt",
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
            m.addAction("Show the original in Explorer",
                        lambda: shell.open_in_explorer(it.src) if os.path.exists(it.src) else None)
            if it.status == Status.DONE:
                m.addAction("Show the copy in Explorer", lambda: shell.open_in_explorer(it.final_dst))
            m.addSeparator()
        m.addAction("Move up", lambda: self._move_sel(-1))
        m.addAction("Move down", lambda: self._move_sel(1))
        m.addAction("Remove from queue", self._remove_sel)
        m.addSeparator()
        m.addAction("Clear finished", self._clear_finished)
        m.exec(self.table.viewport().mapToGlobal(pos))

    # ------------------------------------------------------------------- tick
    def _set_mode(self, mode: str):
        for w in (self.pct_lbl, self.file_bar, self.total_bar):
            if w.property("mode") != mode:
                w.setProperty("mode", mode)
                repolish(w)

    def tick(self):
        snap = self.engine.snapshot()
        self.model.refresh()
        running = self.engine.is_running
        summary = self.engine.last_summary or {}
        total, done = snap["total_bytes"], snap["done_bytes"]
        frac = done / total if total else 0.0
        cur = snap["current"]
        pending = sum(1 for it in self.model._rows if it.status == Status.PENDING)
        self.hero.busy = running and not self.engine.is_paused

        if running:
            moving = cur is not None and cur.move
            self._set_mode("move" if moving else "copy")
            self.pct_lbl.setText(f"{frac * 100:.0f}%")
            self.pct_lbl.show()
            state = snap["state"]
            verb = "Moving" if moving else "Copying"
            if state == "Copying":
                state = verb
            self.title_lbl.setText(f"{state} {snap['files_done'] + 1 if cur else snap['files_done']:,} "
                                   f"of {snap['files_total']:,} files" if state in ("Copying", "Moving")
                                   else state)
            self.sub_lbl.setText((f"Into {os.path.basename(os.path.dirname(cur.dst)) or cur.dst}"
                                  if cur is not None else "")
                                 + (f"   ({snap['errors']} problem(s) so far)" if snap["errors"] else ""))
            self.stats["speed"].setText(f"{format_size(snap['speed'])}/s" if snap["speed"] else "–")
            self.stats["eta"].setText(format_eta(snap["eta"]))
            self.stats["size"].setText(f"{format_size(done)} of {format_size(total)}")
            self.stats["files"].setText(f"{snap['files_done']:,} of {snap['files_total']:,}")
            self.stats_widget.show()
            self.total_bar.show()
            self.total_bar.setValue(int(frac * 1000))
            if cur is not None:
                self.detail.show()
                self.from_lbl.setText(os.path.dirname(cur.src))
                self.to_lbl.setText(os.path.dirname(cur.dst))
                self.file_lbl.setText(os.path.basename(cur.src))
                f = cur.done / cur.size if cur.size else 1.0
                self.file_bar.setValue(int(f * 1000))
                self.file_pct.setText(f"{format_size(cur.done)} of {format_size(cur.size)}")
                if cur is not self._last_cur:
                    self._last_cur = cur
                    if not self.table.selectionModel().hasSelection():
                        for r, it in enumerate(self.model._rows):
                            if it is cur:
                                self.table.scrollTo(self.model.index(r, 0))
                                break
            else:
                self.detail.hide()
        else:
            self.detail.hide()
            self.stats_widget.hide()
            if snap["files_total"]:
                self.total_bar.show()
                self.total_bar.setValue(int(frac * 1000))
                if summary.get("cancelled"):
                    self._set_mode("copy")
                    self.pct_lbl.setText(f"{frac * 100:.0f}%")
                    self.title_lbl.setText("Stopped")
                    self.sub_lbl.setText(f"{snap['files_done']:,} of {snap['files_total']:,} files finished "
                                         "before you cancelled.")
                elif snap["errors"]:
                    self._set_mode("move")
                    self.pct_lbl.setText(f"{frac * 100:.0f}%")
                    self.title_lbl.setText("Finished with problems")
                    self.sub_lbl.setText(f"{snap['errors']} file(s) couldn't be copied. "
                                         "Open Problems to see why and retry.")
                else:
                    self._set_mode("done")
                    self.pct_lbl.setText("100%")
                    self.title_lbl.setText("All done")
                    self.sub_lbl.setText(f"{snap['files_done']:,} files, {format_size(total)}.")
                self.pct_lbl.show()
            else:
                self.total_bar.hide()
                self.pct_lbl.hide()
                self.title_lbl.setText("Ready")
                self.sub_lbl.setText("Copy files in File Explorer and press Ctrl+V, or add them below."
                                     if self.paste_hook.active else
                                     "Add files below, or right-click a folder → Paste with SwiftCopy.")

        self.pause_btn.setText("Resume" if self.engine.is_paused else "Pause")
        for b in (self.pause_btn, self.skip_btn, self.cancel_btn):
            b.setVisible(running)
        self.skip_btn.setEnabled(cur is not None)
        if self.tray:
            self.tray_pause.setText(self.pause_btn.text())
            self.tray_pause.setEnabled(running)
            self.tray.setToolTip(f"{APP_NAME}: {frac * 100:.0f}%" if running else APP_NAME)
        self._update_buttons()

        self.nav[1].set_badge(pending + (1 if running and cur is not None else 0))
        self.nav[2].set_badge(snap["errors"], bad=True)
        if integration.IS_WIN:
            self.hook_lbl.setObjectName("hookOn" if self.paste_hook.active else "sideNote")
            self.hook_lbl.setText("● Ctrl+V in Explorer uses SwiftCopy" if self.paste_hook.active
                                  else "Ctrl+V takeover is off")
            repolish(self.hook_lbl)
        else:
            self.hook_lbl.hide()

        self.setWindowTitle(f"{frac * 100:.0f}% · {APP_NAME}" if running else APP_NAME)
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
        has = bool(errs)
        self.err_table.setVisible(has)
        self.err_empty.setVisible(not has)
        self.retry_btn.setEnabled(has)
        self.save_err_btn.setEnabled(has)

    def _show_prompt(self):
        p = self.engine.prompt
        if p is None:
            return
        self._showing_prompt = True
        try:
            self.bring_to_front()
            QApplication.alert(self)
            dlg = CollisionDialog(p, self) if p.kind == "collision" else ErrorDialog(p, self)
            theme.dark_title_bar(dlg, theme.current["dark"])
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
            r = QMessageBox.question(self, APP_NAME, "Copies are still running. Stop them and quit?")
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
