"""Themes for SwiftCopy: modern dark/light, Windows XP, Vista, 7, Futuristic and Matrix.

Each theme is a dict of tokens. Keys ending in `_bg` may hold a QSS gradient; every
other colour key is a plain colour (used for the palette and custom painting).
"""
from __future__ import annotations

import os
import tempfile

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPainter, QPalette, QPen, QPixmap


def _lg(*stops, vertical=True) -> str:
    """QSS linear gradient from (position, colour) pairs."""
    coords = "x1:0, y1:0, x2:0, y2:1" if vertical else "x1:0, y1:0, x2:1, y2:0"
    return "qlineargradient(%s, %s)" % (coords, ", ".join(f"stop:{p} {c}" for p, c in stops))


def _gloss(top: str, mid_hi: str, mid_lo: str, bottom: str) -> str:
    """Aero-style glossy fill: light top half, hard edge in the middle."""
    return _lg((0, top), (0.49, mid_hi), (0.5, mid_lo), (1, bottom))


BASE = dict(
    font="Segoe UI", display="Segoe UI Semibold", size=10.0, radius=8, mono=False,
    segmented=False, decor="none", dark=True,
)

THEMES: dict[str, dict] = {}

THEMES["dark"] = dict(BASE, label="Midnight", dark=True,
    bg="#131B2C", bg_bg="#131B2C",
    side_bg="#0E1522", side_text="#E7EDF7", side_muted="#8D9BB4",
    side_hover_bg="#1C2740", side_checked_bg="#1D3157", side_checked_text="#FFFFFF",
    panel="#1A2438", panel_bg="#1A2438", hero_bg="#1A2438", border="#2B3954",
    text="#E7EDF7", muted="#8D9BB4", faint="#5D6B86", line="#2B3954", input="#152035",
    btn_bg="#223049", btn_hover_bg="#2A3A57", btn_border="#33435F", btn_text="#E7EDF7",
    copy="#4C8DFF", copy_bg="#4C8DFF", copy_hover_bg="#3B7BEF",
    move="#F0A23B", move_bg="#F0A23B", move_hover_bg="#DC8F27", accent_text="#FFFFFF",
    track_bg="#26334D", chunk_copy_bg="#4C8DFF", chunk_move_bg="#F0A23B", chunk_done_bg="#2CC49F",
    sel="#24406E", sel_text="#FFFFFF", ok="#2CC49F", bad="#FF6B6B", header_bg="#1A2438",
)

THEMES["light"] = dict(BASE, label="Daylight", dark=False,
    bg="#F3F5F9", bg_bg="#F3F5F9",
    side_bg="#E8ECF3", side_text="#18212F", side_muted="#5E6B80",
    side_hover_bg="#DCE2EC", side_checked_bg="#D6E4FF", side_checked_text="#0F2A66",
    panel="#FFFFFF", panel_bg="#FFFFFF", hero_bg="#FFFFFF", border="#DCE2EC",
    text="#18212F", muted="#5E6B80", faint="#98A3B6", line="#DCE2EC", input="#FFFFFF",
    btn_bg="#FFFFFF", btn_hover_bg="#F1F4F9", btn_border="#CFD7E3", btn_text="#18212F",
    copy="#2F6FEB", copy_bg="#2F6FEB", copy_hover_bg="#245FD6",
    move="#D9831A", move_bg="#D9831A", move_hover_bg="#C27313", accent_text="#FFFFFF",
    track_bg="#E3E8F0", chunk_copy_bg="#2F6FEB", chunk_move_bg="#D9831A", chunk_done_bg="#12A07D",
    sel="#D6E4FF", sel_text="#0F2A66", ok="#12A07D", bad="#E04848", header_bg="#FFFFFF",
)

THEMES["xp"] = dict(BASE, label="Windows XP", dark=False, font="Tahoma", display="Trebuchet MS",
    size=9.0, radius=3, segmented=True,
    bg="#ECE9D8", bg_bg="#ECE9D8",
    side_bg=_lg((0, "#7BA2E7"), (1, "#6375D6")), side_text="#FFFFFF", side_muted="#DCE6FB",
    side_hover_bg="rgba(255,255,255,40)", side_checked_bg=_lg((0, "#FFFFFF"), (1, "#C6D3F7")),
    side_checked_text="#215DC6",
    panel="#FFFFFF", panel_bg="#FFFFFF", hero_bg=_lg((0, "#FFFFFF"), (1, "#E3EBFB")),
    border="#7A96DF",
    text="#000000", muted="#4B4B4B", faint="#8E8F8F", line="#ACA899", input="#FFFFFF",
    btn_bg=_lg((0, "#FFFFFF"), (0.86, "#ECEBE6"), (1, "#D6D0C5")),
    btn_hover_bg=_lg((0, "#FFF0CF"), (0.15, "#FFFFFF"), (0.86, "#ECEBE6"), (1, "#E5A01A")),
    btn_border="#003C74", btn_text="#000000",
    copy="#215DC6", copy_bg=_lg((0, "#3D95FF"), (1, "#1E5FCB")),
    copy_hover_bg=_lg((0, "#5AA7FF"), (1, "#2A6FE0")),
    move="#E57B12", move_bg=_lg((0, "#FFB54D"), (1, "#E2700E")),
    move_hover_bg=_lg((0, "#FFC56E"), (1, "#EE7F1B")), accent_text="#FFFFFF",
    track_bg="#FFFFFF",
    chunk_copy_bg=_lg((0, "#BAF0B7"), (0.5, "#37D445"), (1, "#2BB73A")),
    chunk_move_bg=_lg((0, "#FFE0A6"), (0.5, "#F5A623"), (1, "#E2890F")),
    chunk_done_bg=_lg((0, "#BAF0B7"), (0.5, "#37D445"), (1, "#2BB73A")),
    sel="#316AC5", sel_text="#FFFFFF", ok="#2BA33A", bad="#CC0000",
    header_bg=_lg((0, "#FFFFFF"), (1, "#EBEADB")),
)

THEMES["vista"] = dict(BASE, label="Windows Vista", dark=True, radius=4, decor="gloss",
    bg="#14202A", bg_bg=_lg((0, "#22343F"), (1, "#0B1218")),
    side_bg=_gloss("rgba(255,255,255,46)", "rgba(255,255,255,14)", "rgba(0,0,0,40)", "rgba(0,0,0,90)"),
    side_text="#FFFFFF", side_muted="#A9C1CF",
    side_hover_bg=_gloss("rgba(140,220,255,70)", "rgba(80,170,230,40)", "rgba(30,110,170,50)",
                         "rgba(40,150,210,80)"),
    side_checked_bg=_gloss("#5FC4F0", "#2D97D4", "#1777B9", "#2A9DE0"), side_checked_text="#FFFFFF",
    panel="#1C2B36", panel_bg="rgba(20,32,42,210)",
    hero_bg=_lg((0, "#2C4351"), (1, "#14212B")), border="#3E5D70",
    text="#EAF4FA", muted="#9DB6C4", faint="#62798A", line="#355062", input="#101A22",
    btn_bg=_gloss("#4E6A7B", "#2F4859", "#1B3141", "#2D4C60"),
    btn_hover_bg=_gloss("#7CCBF0", "#3A9ED6", "#1E7DBD", "#36A6E2"),
    btn_border="#0E161C", btn_text="#FFFFFF",
    copy="#3CC8FF", copy_bg=_gloss("#9BE3FF", "#3FB4EC", "#1690D2", "#38B5F0"),
    copy_hover_bg=_gloss("#B7ECFF", "#5BC3F2", "#25A0DE", "#4CC2F5"),
    move="#FFB13B", move_bg=_gloss("#FFE0A0", "#FFB23F", "#E88A0F", "#FFAA32"),
    move_hover_bg=_gloss("#FFEBC0", "#FFC160", "#F29A20", "#FFB848"), accent_text="#FFFFFF",
    track_bg=_lg((0, "#0B1218"), (1, "#22303A")),
    chunk_copy_bg=_gloss("#B9F6A4", "#5CD84A", "#28B022", "#4CD33A"),
    chunk_move_bg=_gloss("#FFE7A6", "#FFC24A", "#E8940F", "#FFB430"),
    chunk_done_bg=_gloss("#B9F6A4", "#5CD84A", "#28B022", "#4CD33A"),
    sel="#1F6E9E", sel_text="#FFFFFF", ok="#5CD84A", bad="#FF6060",
    header_bg=_gloss("#3A5466", "#253B4A", "#162733", "#203543"),
)

THEMES["win7"] = dict(BASE, label="Windows 7", dark=False, radius=3, decor="gloss",
    bg="#DCE9F7", bg_bg=_lg((0, "#E9F1FB"), (1, "#C9DCF2")),
    side_bg=_lg((0, "#A9CBEE"), (0.5, "#8BB6E6"), (1, "#6E9FD8")),
    side_text="#0B2E59", side_muted="#244C7A",
    side_hover_bg=_lg((0, "rgba(255,255,255,140)"), (1, "rgba(255,255,255,60)")),
    side_checked_bg=_lg((0, "#FFFFFF"), (0.49, "#EAF6FD"), (0.5, "#D9F0FC"), (1, "#BEE6FD")),
    side_checked_text="#0B2E59",
    panel="#FFFFFF", panel_bg="rgba(255,255,255,235)",
    hero_bg=_lg((0, "#FFFFFF"), (1, "#EEF5FD")), border="#8DB2E3",
    text="#1E395B", muted="#4E6C8F", faint="#8EA4BF", line="#B9D1EA", input="#FFFFFF",
    btn_bg=_lg((0, "#F2F2F2"), (0.49, "#EBEBEB"), (0.5, "#DDDDDD"), (1, "#CFCFCF")),
    btn_hover_bg=_lg((0, "#EAF6FD"), (0.49, "#D9F0FC"), (0.5, "#BEE6FD"), (1, "#A7D9F5")),
    btn_border="#707070", btn_text="#000000",
    copy="#2C7BD8", copy_bg=_gloss("#8BC3F7", "#4A97E8", "#2A73CF", "#3F8FE6"),
    copy_hover_bg=_gloss("#A6D3FA", "#62A9EF", "#3A86DC", "#55A2EE"),
    move="#E58A1F", move_bg=_gloss("#FFD18A", "#F7A642", "#E07F12", "#F49A30"),
    move_hover_bg=_gloss("#FFDDA6", "#F9B65E", "#EA8E22", "#F7A845"), accent_text="#FFFFFF",
    track_bg=_lg((0, "#E6E6E6"), (1, "#F5F5F5")),
    chunk_copy_bg=_gloss("#C8F7B6", "#47D03A", "#06B025", "#2FCB2B"),
    chunk_move_bg=_gloss("#FFE5A8", "#FFBE45", "#EE9A0E", "#FFB02E"),
    chunk_done_bg=_gloss("#C8F7B6", "#47D03A", "#06B025", "#2FCB2B"),
    sel="#CCE8FF", sel_text="#000000", ok="#06B025", bad="#D21F1F",
    header_bg=_lg((0, "#FFFFFF"), (1, "#F1F5FB")),
)

THEMES["future"] = dict(BASE, label="Futuristic", dark=True, font="Bahnschrift",
    display="Bahnschrift SemiBold", radius=2, decor="grid", size=10.0,
    bg="#060A16", bg_bg=_lg((0, "#0A1024"), (1, "#04060E")),
    side_bg=_lg((0, "rgba(0,229,255,18)"), (1, "rgba(255,43,214,14)")),
    side_text="#D8FBFF", side_muted="#6FA3B5",
    side_hover_bg="rgba(0,229,255,28)",
    side_checked_bg=_lg((0, "rgba(0,229,255,70)"), (1, "rgba(0,229,255,10)"), vertical=False),
    side_checked_text="#FFFFFF",
    panel="#0B1226", panel_bg="rgba(10,18,38,220)", hero_bg="rgba(8,14,32,235)", border="#00B8D9",
    text="#D8FBFF", muted="#7FB4C6", faint="#3F6577", line="#16405A", input="#070D1C",
    btn_bg="rgba(0,229,255,14)", btn_hover_bg="rgba(0,229,255,40)", btn_border="#00B8D9",
    btn_text="#D8FBFF",
    copy="#00E5FF", copy_bg=_lg((0, "#00E5FF"), (1, "#00A3FF"), vertical=False),
    copy_hover_bg=_lg((0, "#5DF2FF"), (1, "#33B8FF"), vertical=False),
    move="#FF2BD6", move_bg=_lg((0, "#FF2BD6"), (1, "#9D3BFF"), vertical=False),
    move_hover_bg=_lg((0, "#FF63E2"), (1, "#B466FF"), vertical=False), accent_text="#04060E",
    track_bg="#0E1B33",
    chunk_copy_bg=_lg((0, "#00A3FF"), (1, "#00F0FF"), vertical=False),
    chunk_move_bg=_lg((0, "#9D3BFF"), (1, "#FF2BD6"), vertical=False),
    chunk_done_bg=_lg((0, "#00FFA3"), (1, "#00E5FF"), vertical=False),
    sel="#0B4A66", sel_text="#FFFFFF", ok="#00FFA3", bad="#FF3366", header_bg="#0B1226",
)

THEMES["matrix"] = dict(BASE, label="Matrix", dark=True, font="Consolas", display="Consolas",
    mono=True, radius=0, segmented=True, decor="rain", size=10.0,
    bg="#000000", bg_bg="#000000",
    side_bg="#000000", side_text="#00FF41", side_muted="#008F11",
    side_hover_bg="#001A06", side_checked_bg="#003B0E", side_checked_text="#C8FFD2",
    panel="#000000", panel_bg="#010801", hero_bg="#000000", border="#00802A",
    text="#00FF41", muted="#00B32D", faint="#006B1B", line="#00451A", input="#000000",
    btn_bg="#000000", btn_hover_bg="#002A0B", btn_border="#00B32D", btn_text="#00FF41",
    copy="#00FF41", copy_bg="#00C832", copy_hover_bg="#00FF41",
    move="#C6FF00", move_bg="#9ACD00", move_hover_bg="#C6FF00", accent_text="#000000",
    track_bg="#001505", chunk_copy_bg="#00FF41", chunk_move_bg="#C6FF00", chunk_done_bg="#7DFF9A",
    sel="#00451A", sel_text="#C8FFD2", ok="#7DFF9A", bad="#FF3B3B", header_bg="#000000",
)

ORDER = ["dark", "light", "xp", "vista", "win7", "future", "matrix"]

current: dict = dict(THEMES["dark"], key="dark")


def system_is_dark() -> bool:
    try:
        return QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark
    except AttributeError:  # Qt < 6.5
        return QGuiApplication.palette().window().color().lightness() < 128


def resolve(key: str) -> tuple[str, dict]:
    if key not in THEMES:  # "system" (or unknown) follows Windows light/dark
        key = "dark" if system_is_dark() else "light"
    return key, THEMES[key]


def _font_stack(name: str, mono: bool) -> str:
    fallbacks = ['"Consolas"', '"Cascadia Mono"', '"DejaVu Sans Mono"', "monospace"] if mono else \
        ['"Segoe UI"', '"Noto Sans"', '"DejaVu Sans"', "sans-serif"]
    return ", ".join([f'"{name}"'] + fallbacks)


def palette(t: dict) -> QPalette:
    p = QPalette()
    c = QColor
    for g in (QPalette.Active, QPalette.Inactive):
        p.setColor(g, QPalette.Window, c(t["bg"]))
        p.setColor(g, QPalette.WindowText, c(t["text"]))
        p.setColor(g, QPalette.Base, c(t["input"]))
        p.setColor(g, QPalette.AlternateBase, c(t["panel"]))
        p.setColor(g, QPalette.Text, c(t["text"]))
        p.setColor(g, QPalette.Button, c(t["panel"]))
        p.setColor(g, QPalette.ButtonText, c(t["btn_text"]))
        p.setColor(g, QPalette.Highlight, c(t["sel"]))
        p.setColor(g, QPalette.HighlightedText, c(t["sel_text"]))
        p.setColor(g, QPalette.ToolTipBase, c(t["panel"]))
        p.setColor(g, QPalette.ToolTipText, c(t["text"]))
        p.setColor(g, QPalette.PlaceholderText, c(t["faint"]))
        p.setColor(g, QPalette.Link, c(t["copy"]))
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        p.setColor(QPalette.Disabled, role, c(t["faint"]))
    return p


# ------------------------------------------------- small images for QSS (no SVG plugin needed)
def _icons(t: dict, key: str) -> dict:
    folder = os.path.join(tempfile.gettempdir(), "SwiftCopy-theme", key)
    os.makedirs(folder, exist_ok=True)

    def make(name, draw, w=14, h=14):
        path = os.path.join(folder, name + ".png").replace("\\", "/")
        pm = QPixmap(w * 2, h * 2)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        p.scale(2, 2)
        draw(p)
        p.end()
        pm.save(path)
        return path

    def check(p):
        pen = QPen(QColor(t["accent_text"] if not t["segmented"] else t["copy"]), 2.2)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        p.drawPolyline([QPointF(3, 7.5), QPointF(6, 10.5), QPointF(11, 4)])

    def arrow(p):
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(t["muted"]))
        p.drawPolygon([QPointF(3, 5), QPointF(11, 5), QPointF(7, 10)])

    return {"check": make("check", check), "arrow": make("arrow", arrow)}


def stylesheet(t: dict, icons: dict) -> str:
    r = t["radius"]
    r2 = max(r * 2 - 2, r)  # larger containers get a slightly larger radius
    font = _font_stack(t["font"], t["mono"])
    display = _font_stack(t["display"], t["mono"])
    seg = "width: 9px; margin: 1px;" if t["segmented"] else ""
    check_bg = t["input"] if t["segmented"] else t["copy"]
    return f"""
* {{ font-family: {font}; font-size: {t['size']}pt; color: {t['text']}; outline: 0; }}
QMainWindow, QDialog, QMessageBox {{ background: {t['bg_bg']}; }}
QWidget#central {{ background: {t['bg_bg']}; }}
QWidget#page, QStackedWidget, QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; }}
QToolTip {{ background: {t['panel']}; color: {t['text']}; border: 1px solid {t['border']}; padding: 4px 6px; }}

QFrame#sidebar {{ background: {t['side_bg']}; border-right: 1px solid {t['border']}; }}
QLabel#brand {{ font-family: {display}; font-size: {t['size'] + 3}pt; color: {t['side_text']};
    background: transparent; }}
QLabel#sideNote {{ color: {t['side_muted']}; font-size: {t['size'] - 1}pt; background: transparent; }}
QLabel#hookOn {{ color: {t['ok'] if not t['segmented'] or t['dark'] else '#FFFFFF'};
    font-size: {t['size'] - 1}pt; background: transparent; font-weight: 600; }}
QPushButton#nav {{ text-align: left; padding: 9px 12px; border: 1px solid transparent; border-radius: {r2}px;
    background: transparent; color: {t['side_text']}; }}
QPushButton#nav:hover {{ background: {t['side_hover_bg']}; }}
QPushButton#nav:checked {{ background: {t['side_checked_bg']}; color: {t['side_checked_text']};
    font-weight: 600; border-color: {t['border'] if t['decor'] in ('grid', 'rain') else 'transparent'}; }}
QLabel#badge {{ background: rgba(127,127,127,60); color: {t['side_text']}; border-radius: 9px;
    padding: 0px 8px; min-height: 18px; max-height: 18px; font-size: {t['size'] - 1.5}pt; font-weight: 600; }}
QLabel#badge[tone="bad"] {{ background: {t['bad']}; color: #FFFFFF; }}

QFrame#hero {{ background: {t['hero_bg']}; border: 1px solid {t['border']}; border-radius: {r2 + 4}px; }}
QFrame#hero QLabel {{ background: transparent; }}
QLabel#bigPct {{ font-family: {display}; font-size: {t['size'] + 20}pt; color: {t['copy']}; }}
QLabel#bigPct[mode="move"] {{ color: {t['move']}; }}
QLabel#bigPct[mode="done"] {{ color: {t['ok']}; }}
QLabel#heroTitle {{ font-family: {display}; font-size: {t['size'] + 4}pt; }}
QLabel#heroSub, QLabel#statLabel, QLabel#laneLabel {{ color: {t['muted']}; }}
QLabel#statLabel, QLabel#laneLabel {{ font-size: {t['size'] - 1}pt; }}
QLabel#statValue {{ font-size: {t['size'] + 1.5}pt; font-weight: 600; }}
QLabel#fileName {{ font-weight: 600; }}

QLabel#h1 {{ font-family: {display}; font-size: {t['size'] + 6}pt; }}
QLabel#h2 {{ font-family: {display}; font-size: {t['size'] + 1.5}pt; color: {t['text']}; }}
QLabel#muted {{ color: {t['muted']}; }}
QLabel#error {{ color: {t['bad']}; }}
QFrame#group {{ background: {t['panel_bg']}; border: 1px solid {t['border']}; border-radius: {r2 + 2}px; }}
QFrame#group QLabel, QFrame#group QCheckBox {{ background: transparent; }}
QFrame#dropZone {{ background: {t['panel_bg']}; border: 1px solid {t['border']}; border-radius: {r2 + 2}px; }}

QPushButton {{ background: {t['btn_bg']}; border: 1px solid {t['btn_border']}; border-radius: {r}px;
    padding: 6px 14px; color: {t['btn_text']}; min-height: 18px; }}
QPushButton:hover {{ background: {t['btn_hover_bg']}; }}
QPushButton:disabled {{ color: {t['faint']}; border-color: {t['line']}; background: transparent; }}
QPushButton#primary, QPushButton#copyBtn {{ background: {t['copy_bg']}; border-color: {t['copy']};
    color: {t['accent_text']}; font-weight: 600; }}
QPushButton#primary:hover, QPushButton#copyBtn:hover {{ background: {t['copy_hover_bg']}; }}
QPushButton#moveBtn {{ background: {t['move_bg']}; border-color: {t['move']}; color: {t['accent_text']};
    font-weight: 600; }}
QPushButton#moveBtn:hover {{ background: {t['move_hover_bg']}; }}
QPushButton#copyBtn, QPushButton#moveBtn {{ padding: 9px 28px; font-size: {t['size'] + 0.5}pt; }}
QPushButton#copyBtn:disabled, QPushButton#moveBtn:disabled {{ background: transparent;
    border-color: {t['line']}; color: {t['faint']}; }}
QPushButton#danger {{ color: {t['bad']}; }}
QPushButton#danger:disabled {{ color: {t['faint']}; }}
QPushButton#themeCard {{ background: transparent; border: 2px solid transparent; border-radius: {r2 + 2}px;
    padding: 0; min-height: 108px; max-height: 108px; min-width: 146px; max-width: 146px; }}
QPushButton#themeCard:checked {{ border-color: {t['copy']}; }}
QPushButton#themeCard:hover {{ border-color: {t['faint']}; }}

QComboBox, QSpinBox, QLineEdit {{ background: {t['input']}; border: 1px solid {t['line']};
    border-radius: {r}px; padding: 5px 9px; min-height: 20px; selection-background-color: {t['sel']}; }}
QComboBox:focus, QSpinBox:focus, QLineEdit:focus {{ border-color: {t['copy']}; }}
QComboBox::drop-down {{ border: none; width: 24px; }}
QComboBox::down-arrow {{ image: url({icons['arrow']}); width: 14px; height: 14px; }}
QComboBox QAbstractItemView {{ background: {t['input']}; border: 1px solid {t['border']};
    selection-background-color: {t['sel']}; selection-color: {t['sel_text']}; padding: 3px; }}
QSpinBox::up-button, QSpinBox::down-button {{ width: 0; border: none; }}
QCheckBox {{ spacing: 10px; padding: 3px 0; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border: 1px solid {t['btn_border']};
    border-radius: {min(r, 4)}px; background: {t['input']}; }}
QCheckBox::indicator:checked {{ background: {check_bg}; border-color: {t['copy']};
    image: url({icons['check']}); }}
QCheckBox::indicator:disabled {{ border-color: {t['line']}; }}

QListWidget#sources {{ background: transparent; border: none; }}
QListWidget#sources::item {{ padding: 5px 8px; border-radius: {r}px; }}
QListWidget#sources::item:selected {{ background: {t['sel']}; color: {t['sel_text']}; }}
QTableView, QTableWidget {{ background: {t['panel_bg']}; border: 1px solid {t['border']};
    border-radius: {r2 + 2}px; gridline-color: transparent; selection-background-color: {t['sel']};
    selection-color: {t['sel_text']}; alternate-background-color: rgba(127,127,127,14); }}
QHeaderView {{ background: transparent; }}
QHeaderView::section {{ background: {t['header_bg']}; color: {t['muted']}; border: none;
    border-bottom: 1px solid {t['line']}; padding: 7px 8px; font-weight: 600; }}
QTableCornerButton::section {{ background: transparent; border: none; }}

QProgressBar {{ background: {t['track_bg']}; border: 1px solid {t['line'] if (t['segmented'] or not t['dark']) else 'transparent'};
    border-radius: {min(r, 3)}px; max-height: 8px; min-height: 8px; color: transparent; }}
QProgressBar#totalBar {{ border-radius: {min(r, 7)}px; max-height: 16px; min-height: 16px; }}
QProgressBar::chunk {{ background: {t['chunk_copy_bg']}; border-radius: {min(r, 3)}px; {seg} }}
QProgressBar#totalBar::chunk {{ border-radius: {min(r, 6)}px; }}
QProgressBar[mode="move"]::chunk {{ background: {t['chunk_move_bg']}; }}
QProgressBar[mode="done"]::chunk {{ background: {t['chunk_done_bg']}; }}

QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {t['line']}; border-radius: {min(r, 4)}px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {t['faint']}; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {t['line']}; border-radius: {min(r, 4)}px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

QMenu {{ background: {t['panel']}; border: 1px solid {t['border']}; padding: 4px; }}
QMenu::item {{ padding: 6px 18px; border-radius: {r}px; }}
QMenu::item:selected {{ background: {t['sel']}; color: {t['sel_text']}; }}
QMenu::separator {{ height: 1px; background: {t['line']}; margin: 4px 6px; }}
QStatusBar {{ background: transparent; color: {t['muted']}; }}
QStatusBar QLabel {{ background: transparent; }}
"""


def apply(app, key: str) -> dict:
    key, t = resolve(key)
    current.clear()
    current.update(t)
    current["key"] = key
    app.setPalette(palette(t))
    app.setStyleSheet(stylesheet(t, _icons(t, key)))
    f = QFont(t["font"])
    f.setPointSizeF(t["size"])
    if t["mono"]:
        f.setStyleHint(QFont.Monospace)
    app.setFont(f)
    for w in app.topLevelWidgets():
        dark_title_bar(w, t["dark"])
    return current


def dark_title_bar(widget, dark: bool) -> None:
    """Make the Windows title bar match light/dark (Windows 10 20H1+ / 11)."""
    if os.name != "nt" or not widget.isWindow():
        return
    try:
        import ctypes
        hwnd = int(widget.winId())
        val = ctypes.c_int(1 if dark else 0)
        for attr in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE (current id, older id)
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(val),
                                                         ctypes.sizeof(val)) == 0:
                break
    except Exception:  # noqa: BLE001
        pass
