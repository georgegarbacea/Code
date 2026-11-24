"""Premium dark theme (colours, fonts and the global Qt stylesheet)."""
from __future__ import annotations

import sys

from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette

BG = "#07080d"
BG2 = "#0b0d14"
SURFACE = "#10131c"
SURFACE2 = "#161a27"
SURFACE3 = "#1d2233"
BORDER = "#232a3d"
BORDER2 = "#2e3650"
TEXT = "#eef0f7"
MUTED = "#8b91a8"
DIM = "#5d6378"
A1 = "#7c5cff"   # violet
A2 = "#22d3ee"   # cyan
A3 = "#ff4fa3"   # pink
OK = "#3ddc97"
WARN = "#ffb547"
DANGER = "#ff5c6c"
PORT_COLORS = ["#ff5c6c", "#3ddc97", "#4f8bff", "#ffb547"]


def font_family() -> str:
    fams = set(QFontDatabase.families())
    for f in ("Segoe UI Variable Display", "Segoe UI Variable Text", "Segoe UI", "Inter", "SF Pro Display",
              "Ubuntu", "Noto Sans", "DejaVu Sans"):
        if f in fams:
            return f
    return QFont().defaultFamily()


def _arrow_images() -> tuple[str, str]:
    """Render small chevrons for combo/spin boxes (QSS cannot draw them reliably)."""
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QImage, QPainter, QPen
    from ..core.config import app_data_dir
    d = app_data_dir() / "ui"
    d.mkdir(exist_ok=True)
    paths = []
    for name, pts in (("down", [(3, 6), (8, 11), (13, 6)]), ("up", [(3, 10), (8, 5), (13, 10)])):
        img = QImage(16, 16, QImage.Format_ARGB32)
        img.fill(Qt.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing)
        pen = QPen(QColor(MUTED), 1.8)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        p.drawPolyline([QPointF(x, y) for x, y in pts])
        p.end()
        path = d / f"arrow_{name}.png"
        img.save(str(path))
        paths.append(str(path).replace("\\", "/"))
    return paths[0], paths[1]


def apply(app) -> None:
    fam = font_family()
    f = QFont(fam, 10)
    f.setHintingPreference(QFont.PreferNoHinting)
    app.setFont(f)
    pal = QPalette()
    pal.setColor(QPalette.Window, QColor(BG))
    pal.setColor(QPalette.WindowText, QColor(TEXT))
    pal.setColor(QPalette.Base, QColor(SURFACE))
    pal.setColor(QPalette.AlternateBase, QColor(SURFACE2))
    pal.setColor(QPalette.Text, QColor(TEXT))
    pal.setColor(QPalette.Button, QColor(SURFACE2))
    pal.setColor(QPalette.ButtonText, QColor(TEXT))
    pal.setColor(QPalette.Highlight, QColor(A1))
    pal.setColor(QPalette.HighlightedText, QColor("#ffffff"))
    pal.setColor(QPalette.ToolTipBase, QColor(SURFACE3))
    pal.setColor(QPalette.ToolTipText, QColor(TEXT))
    pal.setColor(QPalette.PlaceholderText, QColor(DIM))
    app.setPalette(pal)
    try:
        down, up = _arrow_images()
    except Exception:
        down = up = ""
    app.setStyleSheet(stylesheet(fam, down, up))


def stylesheet(fam: str, down: str = "", up: str = "") -> str:
    return f"""
* {{ font-family: "{fam}"; color: {TEXT}; outline: none; }}
QMainWindow, QWidget#root {{ background: {BG}; }}
QToolTip {{ background: {SURFACE3}; color: {TEXT}; border: 1px solid {BORDER2}; padding: 6px 8px; border-radius: 6px; }}
QLabel {{ background: transparent; }}
QLabel[role="h1"] {{ font-size: 22px; font-weight: 600; letter-spacing: 0.2px; }}
QLabel[role="h2"] {{ font-size: 15px; font-weight: 600; }}
QLabel[role="section"] {{ font-size: 11px; font-weight: 700; color: {MUTED}; letter-spacing: 1.6px; }}
QLabel[role="muted"] {{ color: {MUTED}; }}
QLabel[role="dim"] {{ color: {DIM}; font-size: 11px; }}
QLabel[role="value"] {{ color: {TEXT}; font-weight: 600; }}
QLabel[role="warn"] {{ color: {WARN}; }}
QLabel[role="error"] {{ color: {DANGER}; }}
QLabel[role="ok"] {{ color: {OK}; }}

QFrame[card="true"] {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 14px; }}
QFrame[card="flat"] {{ background: {SURFACE2}; border: 1px solid {BORDER}; border-radius: 12px; }}

QPushButton {{ background: {SURFACE2}; border: 1px solid {BORDER2}; border-radius: 10px; padding: 8px 14px;
  font-weight: 600; }}
QPushButton:hover {{ background: {SURFACE3}; border-color: #3a4462; }}
QPushButton:pressed {{ background: {BORDER}; }}
QPushButton:disabled {{ color: {DIM}; border-color: {BORDER}; }}
QPushButton:checked {{ background: #2a2450; border-color: {A1}; }}
QPushButton[kind="primary"] {{ border: 0; color: white;
  background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {A1}, stop:1 {A3}); }}
QPushButton[kind="primary"]:hover {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #8f73ff, stop:1 #ff6db4); }}
QPushButton[kind="accent"] {{ border: 0; color: #031015; background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {A2}, stop:1 #6ee7f9); }}
QPushButton[kind="danger"] {{ border: 1px solid #5a2430; background: #2a1219; color: #ffb3bc; }}
QPushButton[kind="ghost"] {{ background: transparent; border: 1px solid transparent; color: {MUTED}; }}
QPushButton[kind="ghost"]:hover {{ color: {TEXT}; background: {SURFACE2}; }}
QPushButton[kind="chip"] {{ border-radius: 14px; padding: 5px 12px; font-weight: 500; font-size: 12px; }}
QPushButton[kind="chip"]:checked {{ background: #1c2a3a; border-color: {A2}; color: white; }}

QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit, QTextEdit {{
  background: {BG2}; border: 1px solid {BORDER2}; border-radius: 8px; padding: 6px 8px; selection-background-color: {A1}; }}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{ border-color: {A1}; }}
QComboBox::drop-down {{ border: 0; width: 22px; }}
QComboBox::down-arrow {{ image: url("{down}"); width: 14px; height: 14px; margin-right: 6px; }}
QComboBox QAbstractItemView {{ background: {SURFACE2}; border: 1px solid {BORDER2}; selection-background-color: #2a2450; padding: 4px; }}
QSpinBox, QDoubleSpinBox {{ padding-right: 18px; }}
QSpinBox::up-button, QDoubleSpinBox::up-button {{ subcontrol-origin: border; subcontrol-position: top right; width: 18px; border: 0; background: transparent; }}
QSpinBox::down-button, QDoubleSpinBox::down-button {{ subcontrol-origin: border; subcontrol-position: bottom right; width: 18px; border: 0; background: transparent; }}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{ image: url("{up}"); width: 11px; height: 11px; }}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{ image: url("{down}"); width: 11px; height: 11px; }}

QSlider::groove:horizontal {{ height: 6px; background: {SURFACE3}; border-radius: 3px; }}
QSlider::sub-page:horizontal {{ height: 6px; border-radius: 3px;
  background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {A1}, stop:1 {A2}); }}
QSlider::handle:horizontal {{ width: 16px; height: 16px; margin: -6px 0; border-radius: 8px; background: white;
  border: 3px solid #3b2f7a; }}
QSlider::handle:horizontal:hover {{ border-color: {A1}; }}
QSlider[warm="true"]::groove:horizontal {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #ff8a1a, stop:0.5 #ffe2bd, stop:1 #d6e6ff); }}
QSlider[warm="true"]::sub-page:horizontal {{ background: transparent; }}

QScrollArea {{ background: transparent; border: 0; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {BORDER2}; border-radius: 4px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: #46507a; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {BORDER2}; border-radius: 4px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{ height: 0; width: 0; background: none; }}

QTableWidget {{ background: {BG2}; border: 1px solid {BORDER}; border-radius: 10px; gridline-color: {BORDER};
  selection-background-color: #241f45; }}
QHeaderView::section {{ background: {SURFACE2}; color: {MUTED}; border: 0; border-bottom: 1px solid {BORDER};
  padding: 6px; font-weight: 600; font-size: 11px; }}
QTableCornerButton::section {{ background: {SURFACE2}; border: 0; }}
QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{ width: 18px; height: 18px; border-radius: 5px; border: 1px solid {BORDER2}; background: {BG2}; }}
QCheckBox::indicator:checked {{ background: {A1}; border-color: {A1}; image: none; }}
QTabWidget::pane {{ border: 0; }}
QTabBar::tab {{ background: transparent; color: {MUTED}; padding: 8px 14px; border: 0; border-bottom: 2px solid transparent; font-weight: 600; }}
QTabBar::tab:selected {{ color: {TEXT}; border-bottom: 2px solid {A2}; }}
QMenu {{ background: {SURFACE2}; border: 1px solid {BORDER2}; padding: 6px; border-radius: 8px; }}
QMenu::item {{ padding: 6px 18px; border-radius: 6px; }}
QMenu::item:selected {{ background: #2a2450; }}
QMessageBox {{ background: {SURFACE}; }}
QSplitter::handle {{ background: {BG}; }}
QListWidget {{ background: {BG2}; border: 1px solid {BORDER}; border-radius: 10px; padding: 4px; }}
QListWidget::item {{ padding: 8px; border-radius: 6px; }}
QListWidget::item:selected {{ background: #241f45; }}
"""


def dark_titlebar(widget) -> None:
    """Windows 11 dark title bar + rounded corners (DWM)."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        hwnd = int(widget.winId())
        val = ctypes.c_int(1)
        for attr in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE (new / old)
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(val), ctypes.sizeof(val)) == 0:
                break
        cap = ctypes.c_int(0x0014080D)   # caption colour BGR (#0d0814 -> near BG)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 35, ctypes.byref(cap), ctypes.sizeof(cap))
    except Exception:
        pass
