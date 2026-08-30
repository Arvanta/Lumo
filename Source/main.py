#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Lumo — a lightweight, YouTube-like video player for Windows.

Features
--------
* Lightweight playback of local files and online streams (MP4 / MKV / WebM ...)
* Full codec support (x264 / x265 / AV1 ...) via libmpv (mpv engine)
* Online streams: mpv caches ONLY a bounded amount starting from the current
  position (not the whole file) - the buffered amount is drawn on the seek bar.
* Frameless window with a custom title bar (min / max / close) combined with
  the player toolbar; resizable via window edges.
* Dark and Light themes.
* Portable settings (stored in lumo_settings.ini next to the program) with a
  "Reset to defaults" button.
* Playlist (multi-open, next/previous, auto-advance),
  recent-files list, remember window size/position/volume/speed.
* Subtitles: font / weight / outline / shadow / color / size, background box,
  and ,/. subtitle-sync keys (reset with /).
* Volume OSD (top-left, configurable font/color/opacity) and an optional
  seek OSD (time display while seeking).
* Middle click -> fullscreen, double click -> pause/play, wheel -> volume.
* Keyboard: ←/→ seek ±step, ↑/↓ volume ±step, J/L ±10s, ,/. sub sync (±0.1s),
  / reset sub sync, Space/K pause, F/Enter fullscreen, M mute, S stop,
  N/P playlist prev/next.

Dependencies: PyQt5, python-mpv, and libmpv-2.dll (mpv library).
"""

import os
import sys
import math
import time
import ctypes
import struct
import tempfile
from pathlib import Path

try:
    import mpv as _mpv
    MPV_AVAILABLE = True
    MPV_IMPORT_ERROR = ""
except Exception as _e:
    _mpv = None
    MPV_AVAILABLE = False
    MPV_IMPORT_ERROR = str(_e)

from PyQt5.QtCore import (
    Qt, QTimer, QPoint, QRectF, QSettings, pyqtSignal, QObject, QEvent, QSize,
)
from PyQt5.QtGui import (
    QColor, QPainter, QPen, QBrush, QPolygon, QPixmap, QIcon, QCursor,
    QFontDatabase,
)
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QLabel, QToolButton, QSlider,
    QHBoxLayout, QVBoxLayout, QSizePolicy, QMenu, QDialog, QSpinBox,
    QDoubleSpinBox, QComboBox, QFormLayout, QDialogButtonBox, QFileDialog,
    QMessageBox, QColorDialog, QCheckBox, QFrame, QLineEdit, QPushButton,
    QTabWidget, QListWidget, QListWidgetItem,
)


def pe_machine(path):
    """Return the CPU machine value from a PE (.dll/.exe) file header,
    or None if it is not a valid PE file."""
    try:
        with open(path, "rb") as f:
            if f.read(2) != b"MZ":
                return None
            f.seek(0x3C)
            pe_off = struct.unpack("<I", f.read(4))[0]
            f.seek(pe_off)
            if f.read(4) != b"PE\x00\x00":
                return None
            return struct.unpack("<H", f.read(2))[0]
    except Exception:
        return None


PE_X86 = 0x014C    # 32-bit
PE_X64 = 0x8664    # 64-bit
PE_ARM64 = 0xAA64

# ----------------------------------------------------------------------------
# Constants
# ----------------------------------------------------------------------------
APP_NAME = "Lumo"
VERSION = "1.0"
GITHUB_URL = "https://github.com/Arvanta/Lumo"

VIDEO_EXTS = {
    ".mp4", ".mkv", ".webm", ".avi", ".mov", ".flv", ".wmv", ".m4v",
    ".ts", ".m2ts", ".mpg", ".mpeg", ".3gp", ".ogv", ".m3u8",
}
SUB_EXTS = {".srt", ".ass", ".ssa", ".sub", ".vtt", ".lrc", ".txt"}

RED = "#ff0000"

DEFAULT_CFG = {
    "seek_step": 2.0,
    "vol_step": 5,
    "hide_delay": 3,
    "cache_mb": 80,
    "back_mb": 16,
    "theme": "dark",
    "sub_font": "",
    "sub_scale": 100,
    "sub_color": "#ffffff",
    "sub_weight": "regular",
    "sub_border_size": 1.5,
    "sub_shadow_offset": 0.0,
    "sub_back_enabled": False,
    "sub_back_color": "#000000",
    "sub_back_opacity": 60,
    "osd_font_size": 14,
    "osd_opacity": 85,
    "osd_color": "#ffffff",
    "osd_background_enabled": False,
    "seek_osd_enabled": True,
}

PALETTES = {
    "dark": {
        "window": "#0f0f0f", "panel": "#161616", "panel2": "#212121",
        "text": "#e8e8e8", "dim": "#9a9a9a", "hover": "#2a2a2a",
        "pressed": "#3a3a3a", "red": "#ff0000", "accent": "#3ea6ff",
        "track": "#4d4d4d", "buffer": "#7a7a7a", "thumb": "#ffffff",
        "field_bg": "#0a0a0a", "field_border": "#3a3a3a", "input_bg": "#1c1c1c",
        "ghost": "#2a2a2a", "ghost_hover": "#3a3a3a",
        "tab_bg": "#232323", "tab_hover": "#2e2e2e", "tab_sel": "#161616",
        "osd_bg": "#161616", "osd_text": "#ffffff", "panel_border": "#2e2e2e",
    },
    "light": {
        "window": "#f9f9f9", "panel": "#ffffff", "panel2": "#f1f1f1",
        "text": "#0f0f0f", "dim": "#606060", "hover": "#e8e8e8",
        "pressed": "#d9d9d9", "red": "#ff0000", "accent": "#0b57d0",
        "track": "#d5d5d5", "buffer": "#b6b6b6", "thumb": "#0f0f0f",
        "field_bg": "#ffffff", "field_border": "#c9c9c9", "input_bg": "#ffffff",
        "ghost": "#e8e8e8", "ghost_hover": "#dcdcdc",
        "tab_bg": "#ececec", "tab_hover": "#e2e2e2", "tab_sel": "#ffffff",
        "osd_bg": "#ffffff", "osd_text": "#0f0f0f", "panel_border": "#d4d4d4",
    },
}


def _app_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def _settings_file():
    """Portable settings: an .ini next to the program; fall back to %APPDATA%
    if that location is not writable."""
    base = _app_dir()
    path = os.path.join(base, "lumo_settings.ini")
    try:
        with open(path, "a", encoding="utf-8"):
            pass
        return path
    except OSError:
        appdata = os.environ.get("APPDATA") or tempfile.gettempdir()
        d = os.path.join(appdata, "Lumo")
        os.makedirs(d, exist_ok=True)
        return os.path.join(d, "settings.ini")


# ----------------------------------------------------------------------------
# Signal bridge (mpv event thread -> Qt main thread)
# ----------------------------------------------------------------------------
class MpvBridge(QObject):
    time_changed = pyqtSignal(float, float)      # pos, duration
    duration_changed = pyqtSignal(float)
    pause_changed = pyqtSignal(bool)
    buffering_changed = pyqtSignal(bool)
    cache_changed = pyqtSignal(float, float, float)   # fw-bytes, file-size, cache-time
    ranges_changed = pyqtSignal(list)            # [(start,end), ...]
    eof_changed = pyqtSignal(bool)
    file_loaded = pyqtSignal(int)                # load generation
    load_error = pyqtSignal(str)
    ended = pyqtSignal(int, str)                 # load generation, end-file reason

    single_click = pyqtSignal()
    dbl_click = pyqtSignal()
    middle_click = pyqtSignal()


# ----------------------------------------------------------------------------
# Vector icons drawn with QPainter (crisp, YouTube-like)
# ----------------------------------------------------------------------------
def make_icon(kind, color="#e8e8e8", size=24):
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    pen = QPen(QColor(color))
    pen.setWidthF(2.0)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(QBrush(QColor(color)))
    s = size

    if kind == "play":
        pts = QPolygon([
            QPoint(int(s * 0.30), int(s * 0.20)),
            QPoint(int(s * 0.30), int(s * 0.80)),
            QPoint(int(s * 0.80), int(s * 0.50)),
        ])
        p.drawPolygon(pts)
    elif kind == "pause":
        p.drawRect(QRectF(s * 0.30, s * 0.20, s * 0.13, s * 0.60))
        p.drawRect(QRectF(s * 0.57, s * 0.20, s * 0.13, s * 0.60))
    elif kind == "stop":
        p.drawRoundedRect(QRectF(s * 0.26, s * 0.26, s * 0.48, s * 0.48), 2, 2)
    elif kind == "replay":
        r = QRectF(s * 0.20, s * 0.20, s * 0.60, s * 0.60)
        p.drawArc(r, 30 * 16, 300 * 16)
        pts = QPolygon([
            QPoint(int(s * 0.78), int(s * 0.24)),
            QPoint(int(s * 0.80), int(s * 0.44)),
            QPoint(int(s * 0.60), int(s * 0.40)),
        ])
        p.drawPolygon(pts)
    elif kind == "prev":
        pts = QPolygon([
            QPoint(int(s * 0.68), int(s * 0.20)),
            QPoint(int(s * 0.68), int(s * 0.80)),
            QPoint(int(s * 0.22), int(s * 0.50)),
        ])
        p.drawPolygon(pts)
        p.drawRect(QRectF(s * 0.10, s * 0.20, s * 0.09, s * 0.60))
    elif kind == "next":
        pts = QPolygon([
            QPoint(int(s * 0.32), int(s * 0.20)),
            QPoint(int(s * 0.32), int(s * 0.80)),
            QPoint(int(s * 0.78), int(s * 0.50)),
        ])
        p.drawPolygon(pts)
        p.drawRect(QRectF(s * 0.81, s * 0.20, s * 0.09, s * 0.60))
    elif kind == "volume":
        p.drawPolygon(QPolygon([
            QPoint(int(s * 0.16), int(s * 0.40)),
            QPoint(int(s * 0.28), int(s * 0.40)),
            QPoint(int(s * 0.42), int(s * 0.26)),
            QPoint(int(s * 0.42), int(s * 0.74)),
            QPoint(int(s * 0.28), int(s * 0.60)),
            QPoint(int(s * 0.16), int(s * 0.60)),
        ]))
        p.drawArc(QRectF(s * 0.48, s * 0.30, s * 0.16, s * 0.40), -60 * 16, 120 * 16)
        p.drawArc(QRectF(s * 0.48, s * 0.18, s * 0.34, s * 0.64), -60 * 16, 120 * 16)
    elif kind == "muted":
        p.drawPolygon(QPolygon([
            QPoint(int(s * 0.16), int(s * 0.40)),
            QPoint(int(s * 0.28), int(s * 0.40)),
            QPoint(int(s * 0.42), int(s * 0.26)),
            QPoint(int(s * 0.42), int(s * 0.74)),
            QPoint(int(s * 0.28), int(s * 0.60)),
            QPoint(int(s * 0.16), int(s * 0.60)),
        ]))
        p.drawLine(QPoint(int(s * 0.50), int(s * 0.36)), QPoint(int(s * 0.84), int(s * 0.64)))
        p.drawLine(QPoint(int(s * 0.50), int(s * 0.64)), QPoint(int(s * 0.84), int(s * 0.36)))
    elif kind == "fullscreen":
        p.setBrush(Qt.NoBrush)
        m = int(s * 0.22)
        L = int(s * 0.34)
        p.drawPolyline([QPoint(m, m + L), QPoint(m, m), QPoint(m + L, m)])
        p.drawPolyline([QPoint(s - m - L, m), QPoint(s - m, m), QPoint(s - m, m + L)])
        p.drawPolyline([QPoint(s - m, s - m - L), QPoint(s - m, s - m), QPoint(s - m - L, s - m)])
        p.drawPolyline([QPoint(m + L, s - m), QPoint(m, s - m), QPoint(m, s - m - L)])
    elif kind == "fullscreen_exit":
        p.setBrush(Qt.NoBrush)
        m = int(s * 0.14)
        L = int(s * 0.34)
        p.drawPolyline([QPoint(m, m), QPoint(m + L, m), QPoint(m + L, m + L)])
        p.drawPolyline([QPoint(s - m, m), QPoint(s - m - L, m), QPoint(s - m - L, m + L)])
        p.drawPolyline([QPoint(s - m, s - m), QPoint(s - m - L, s - m), QPoint(s - m - L, s - m - L)])
        p.drawPolyline([QPoint(m, s - m), QPoint(m + L, s - m), QPoint(m + L, s - m - L)])
    elif kind == "settings":
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QRectF(s * 0.24, s * 0.24, s * 0.52, s * 0.52))
        cx, cy = s / 2, s / 2
        for i in range(8):
            a = i * math.pi / 4
            x1 = cx + math.cos(a) * s * 0.30
            y1 = cy + math.sin(a) * s * 0.30
            x2 = cx + math.cos(a) * s * 0.42
            y2 = cy + math.sin(a) * s * 0.42
            p.drawLine(QPoint(int(x1), int(y1)), QPoint(int(x2), int(y2)))
        p.setBrush(QBrush(QColor(color)))
        p.drawEllipse(QRectF(s * 0.40, s * 0.40, s * 0.20, s * 0.20))
    elif kind == "cc":
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(QRectF(s * 0.08, s * 0.22, s * 0.84, s * 0.56), 4, 4)
        f = p.font()
        f.setBold(True)
        f.setPixelSize(int(s * 0.34))
        p.setFont(f)
        p.drawText(QRectF(0, 0, s, s), Qt.AlignCenter, "CC")
    elif kind == "open":
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(QRectF(s * 0.10, s * 0.28, s * 0.80, s * 0.52), 3, 3)
        p.drawPolyline([QPoint(int(s * 0.10), int(s * 0.40)), QPoint(int(s * 0.38), int(s * 0.40)),
                        QPoint(int(s * 0.48), int(s * 0.30)), QPoint(int(s * 0.60), int(s * 0.30))])
    elif kind == "min":
        p.drawLine(QPoint(int(s * 0.24), int(s * 0.62)), QPoint(int(s * 0.76), int(s * 0.62)))
    elif kind == "list":
        p.setBrush(Qt.NoBrush)
        for i in range(3):
            y = int(s * (0.30 + i * 0.20))
            p.drawLine(QPoint(int(s * 0.22), y), QPoint(int(s * 0.78), y))
    elif kind == "max":
        p.setBrush(Qt.NoBrush)
        p.drawRect(QRectF(s * 0.24, s * 0.24, s * 0.52, s * 0.52))
    elif kind == "restore":
        p.setBrush(Qt.NoBrush)
        p.drawRect(QRectF(s * 0.28, s * 0.26, s * 0.46, s * 0.46))
        p.drawRect(QRectF(s * 0.22, s * 0.30, s * 0.46, s * 0.46))
    elif kind == "close":
        p.drawLine(QPoint(int(s * 0.28), int(s * 0.28)), QPoint(int(s * 0.72), int(s * 0.72)))
        p.drawLine(QPoint(int(s * 0.72), int(s * 0.28)), QPoint(int(s * 0.28), int(s * 0.72)))

    p.end()
    return QIcon(pm)


def make_app_pixmap(size=64):
    """Red rounded square with a white play triangle — the Lumo logo."""
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("#ff0000"))
    p.drawRoundedRect(QRectF(0.05 * size, 0.05 * size, 0.9 * size, 0.9 * size),
                      0.2 * size, 0.2 * size)
    p.setBrush(QColor("#ffffff"))
    pts = QPolygon([
        QPoint(int(size * 0.38), int(size * 0.30)),
        QPoint(int(size * 0.38), int(size * 0.70)),
        QPoint(int(size * 0.74), int(size * 0.50)),
    ])
    p.drawPolygon(pts)
    p.end()
    return pm


def make_app_icon():
    return QIcon(make_app_pixmap(64))


# ----------------------------------------------------------------------------
# Frameless-window resize support.
#
# The main window is frameless, and its top / seek / controls bars plus the mpv
# video surface are *native child windows* (WA_NativeWindow) so they can stack
# above mpv's Direct3D output. A native child window receives WM_NCHITTEST
# itself, which would stop the top-level window's nativeEvent from ever firing
# and thus break edge/corner resizing. So every native child answers
# WM_NCHITTEST with HTTRANSPARENT, passing the hit test through to the
# top-level window, which then returns the proper resize code.
# ----------------------------------------------------------------------------
RESIZE_BORDER = 6


def _win_msg(message):
    try:
        import ctypes.wintypes as wintypes
        return wintypes.MSG.from_address(int(message))
    except Exception:
        return None


def _frameless_hittest(top_hwnd):
    """Return a WM_NCHITTEST hit code for a frameless window border/corner, or
    0 when the cursor is inside the window. Uses physical-pixel coordinates so
    it stays correct on scaled (High-DPI) displays."""
    if sys.platform != "win32":
        return 0
    try:
        user32 = ctypes.windll.user32

        class POINT(ctypes.Structure):
            _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

        class RECT(ctypes.Structure):
            _fields_ = [
                ("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long),
            ]

        pt = POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        rect = RECT()
        user32.GetWindowRect(int(top_hwnd), ctypes.byref(rect))
        b = RESIZE_BORDER
        left = pt.x < rect.left + b
        right = pt.x >= rect.right - b
        top = pt.y < rect.top + b
        bottom = pt.y >= rect.bottom - b
        if top and left:
            return 13      # HTTOPLEFT
        if top and right:
            return 14      # HTTOPRIGHT
        if bottom and left:
            return 16      # HTBOTTOMLEFT
        if bottom and right:
            return 17      # HTBOTTOMRIGHT
        if left:
            return 10      # HTLEFT
        if right:
            return 11      # HTRIGHT
        if top:
            return 12      # HTTOP
        if bottom:
            return 15      # HTBOTTOM
    except Exception:
        pass
    return 0


class FramelessHostMixin:
    """Native child windows: let WM_NCHITTEST fall through (HTTRANSPARENT) to
    the top-level window ONLY when the cursor is inside the top-level window's
    resize border. Everywhere else the child keeps normal mouse handling, so
    buttons, drag and click still work (see module comment)."""

    def nativeEvent(self, eventType, message):
        if sys.platform == "win32":
            msg = _win_msg(message)
            if msg is not None and msg.message == 0x0084:  # WM_NCHITTEST
                try:
                    win = self.window()
                    if (win is not None and not win.isMaximized()
                            and not win.isFullScreen()):
                        if _frameless_hittest(int(win.winId())):
                            return True, -1  # HTTRANSPARENT -> top-level resizes
                except Exception:
                    pass
        return super().nativeEvent(eventType, message)


class ThemedBar(FramelessHostMixin, QWidget):
    """A bar (top / controls) that reliably paints its themed background even
    though it is a native child window (stylesheet backgrounds are not always
    painted on native children)."""

    def __init__(self, parent=None, border_at_bottom=True):
        super().__init__(parent)
        self._pal = None
        self._border_bottom = border_at_bottom
        self.setAttribute(Qt.WA_StyledBackground, True)

    def set_palette(self, pal):
        self._pal = pal
        self.update()

    def paintEvent(self, e):
        pal = self._pal
        if pal is None:
            super().paintEvent(e)
            return
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(pal["window"]))
        p.setPen(QColor(pal["panel_border"]))
        if self._border_bottom:
            p.drawLine(0, self.height() - 1, self.width(), self.height() - 1)
        else:
            p.drawLine(0, 0, self.width(), 0)
        p.end()


class NativeHost(FramelessHostMixin, QWidget):
    """Plain native child (e.g. the mpv video surface)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_NativeWindow, True)


class NativeFrame(FramelessHostMixin, QFrame):
    """Native frame used for floating panels (URL panel, playlist sidebar)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_NativeWindow, True)


# ----------------------------------------------------------------------------
# Custom seek bar (paints buffered ranges, played portion, hover tooltip)
# ----------------------------------------------------------------------------
class SeekBar(FramelessHostMixin, QWidget):
    seekRequested = pyqtSignal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setFixedHeight(16)
        self._duration = 0.0
        self._pos = 0.0
        self._ranges = []
        self._hover_x = -1
        self._dragging = False
        self._tip = None
        self._pal = PALETTES["dark"]

    def set_palette(self, pal):
        self._pal = pal
        self.update()

    def set_duration(self, d):
        self._duration = max(0.0, float(d or 0.0))
        self.update()

    def set_position(self, p):
        self._pos = max(0.0, float(p or 0.0))
        self.update()

    def set_ranges(self, ranges):
        self._ranges = [(float(a), float(b)) for a, b in (ranges or [])]
        self.update()

    def _ensure_tip(self):
        if self._tip is None:
            parent = self.parentWidget() or self.window()
            self._tip = QLabel(parent)
            self._tip.setAttribute(Qt.WA_NativeWindow, True)
            self._tip.setStyleSheet(
                "background:#1f1f1f;color:#eee;border-radius:3px;padding:2px 6px;"
                "font-size:11px;")
        return self._tip

    def _fmt(self, sec):
        if sec is None or sec < 0:
            return "--:--"
        sec = int(sec)
        h, m, s = sec // 3600, (sec % 3600) // 60, sec % 60
        if h:
            return f"{h}:{m:02d}:{s:02d}"
        return f"{m}:{s:02d}"

    def _show_tip(self, x):
        if self._duration <= 0:
            return
        frac = min(max(x / max(1, self.width()), 0.0), 1.0)
        tip = self._ensure_tip()
        tip.setText(self._fmt(frac * self._duration))
        tip.adjustSize()
        w = tip.width()
        gx = self.mapTo(tip.parentWidget(), QPoint(x - w // 2, -tip.height() - 8))
        tip.move(gx)
        tip.show()
        tip.raise_()

    def _hide_tip(self):
        if self._tip:
            self._tip.hide()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        bar_h = 4
        bar_y = (h - bar_h) // 2
        r = bar_h / 2
        pal = self._pal

        p.fillRect(self.rect(), QColor(pal["window"]))

        p.setPen(Qt.NoPen)
        p.setBrush(QColor(pal["track"]))
        p.drawRoundedRect(QRectF(0, bar_y, w, bar_h), r, r)

        if self._duration > 0:
            p.setBrush(QColor(pal["buffer"]))
            for (s0, s1) in self._ranges:
                x0 = max(0.0, s0 / self._duration * w)
                x1 = min(w, s1 / self._duration * w)
                if x1 > x0:
                    p.drawRoundedRect(QRectF(x0, bar_y, x1 - x0, bar_h), r, r)

        if self._duration > 0:
            xp = min(w, max(0.0, self._pos / self._duration * w))
            p.setBrush(QColor(RED))
            p.drawRoundedRect(QRectF(0, bar_y, xp, bar_h), r, r)

            if self._hover_x >= 0 or self._dragging:
                cx = self._hover_x if self._dragging else xp
                cx = min(w, max(0, cx))
                p.setPen(QPen(QColor(pal["thumb"]), 0))
                p.setBrush(QColor(pal["thumb"]))
                p.drawEllipse(QPoint(int(cx), h // 2), 6, 6)
        p.end()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and self._duration > 0:
            self._dragging = True
            self._hover_x = e.x()
            self._seek(e.x())
            self.update()

    def mouseMoveEvent(self, e):
        self._hover_x = e.x()
        if self._dragging:
            self._seek(e.x())
        else:
            self._show_tip(e.x())
        self.update()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._dragging = False
            self.update()

    def leaveEvent(self, e):
        self._hover_x = -1
        self._hide_tip()
        self.update()

    def _seek(self, x):
        frac = min(max(x / max(1, self.width()), 0.0), 1.0)
        self.seekRequested.emit(frac * self._duration)
        self._show_tip(x)


# ----------------------------------------------------------------------------
# Custom title bar (frameless window): drag to move, double-click to maximize
# ----------------------------------------------------------------------------
class TitleBar(ThemedBar):
    doubleClicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent, border_at_bottom=True)
        self._drag_pos = None

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag_pos = e.globalPos() - self.window().pos()

    def mouseMoveEvent(self, e):
        if self._drag_pos is not None and (e.buttons() & Qt.LeftButton):
            w = self.window()
            if not w.isMaximized() and not w.isFullScreen():
                w.move(e.globalPos() - self._drag_pos)

    def mouseReleaseEvent(self, e):
        self._drag_pos = None

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.doubleClicked.emit()


# ----------------------------------------------------------------------------
# Settings dialog (three tabs + Apply/Reset)
# ----------------------------------------------------------------------------
class SettingsDialog(QDialog):
    applied = pyqtSignal(dict)

    def __init__(self, parent, fonts, current):
        super().__init__(parent)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setWindowTitle("Settings")
        self.setMinimumWidth(470)
        self._pal = getattr(parent, "pal", PALETTES["dark"])

        # ---- General -------------------------------------------------------
        self.seek_step = QDoubleSpinBox()
        self.seek_step.setRange(0.1, 60.0)
        self.seek_step.setDecimals(1)
        self.seek_step.setSuffix(" s")
        self.seek_step.setValue(current["seek_step"])

        self.vol_step = QSpinBox()
        self.vol_step.setRange(1, 25)
        self.vol_step.setSuffix(" %")
        self.vol_step.setValue(current["vol_step"])

        self.hide_delay = QSpinBox()
        self.hide_delay.setRange(1, 30)
        self.hide_delay.setSuffix(" s")
        self.hide_delay.setValue(current["hide_delay"])

        self.cache_mb = QSpinBox()
        self.cache_mb.setRange(8, 2048)
        self.cache_mb.setSuffix(" MB")
        self.cache_mb.setValue(current["cache_mb"])

        self.back_mb = QSpinBox()
        self.back_mb.setRange(4, 512)
        self.back_mb.setSuffix(" MB")
        self.back_mb.setValue(current["back_mb"])

        self.theme_combo = QComboBox()
        self.theme_combo.addItem("Dark", "dark")
        self.theme_combo.addItem("Light", "light")
        tidx = self.theme_combo.findData(str(current.get("theme", "dark")))
        self.theme_combo.setCurrentIndex(tidx if tidx >= 0 else 0)

        # ---- Subtitles -----------------------------------------------------
        self.sub_font = QComboBox()
        self.sub_font.setEditable(True)
        self.sub_font.addItem("Default")
        for f in fonts:
            self.sub_font.addItem(f)
        idx = self.sub_font.findText(current["sub_font"])
        self.sub_font.setCurrentIndex(idx if idx >= 0 else 0)

        self.sub_scale = QSlider(Qt.Horizontal)
        self.sub_scale.setRange(40, 250)
        self.sub_scale.setSingleStep(5)
        self.sub_scale.setPageStep(5)
        self.sub_scale.setValue(current["sub_scale"])
        self.sub_scale_label = QLabel(f"{current['sub_scale'] / 100.0:.2f}x")
        self.sub_scale.valueChanged.connect(
            lambda v: self.sub_scale_label.setText(f"{v / 100.0:.2f}x"))

        self.sub_color = QColor(current["sub_color"])
        self.color_btn = QToolButton()
        self.color_btn.setFixedSize(44, 22)
        self.color_btn.setStyleSheet(
            f"background:{current['sub_color']};border:1px solid #555;border-radius:3px;")
        self.color_btn.clicked.connect(lambda: self._pick_color("text"))

        self.sub_weight = QComboBox()
        self.sub_weight.addItem("Regular", "regular")
        self.sub_weight.addItem("Medium", "medium")
        self.sub_weight.addItem("SemiBold", "semibold")
        self.sub_weight.addItem("Bold", "bold")
        widx = self.sub_weight.findData(str(current.get("sub_weight", "regular")))
        self.sub_weight.setCurrentIndex(widx if widx >= 0 else 0)

        self.sub_border_size = QDoubleSpinBox()
        self.sub_border_size.setRange(0.0, 10.0)
        self.sub_border_size.setDecimals(1)
        self.sub_border_size.setSingleStep(0.5)
        self.sub_border_size.setSuffix(" px")
        self.sub_border_size.setValue(float(current["sub_border_size"]))

        self.sub_shadow_offset = QDoubleSpinBox()
        self.sub_shadow_offset.setRange(0.0, 10.0)
        self.sub_shadow_offset.setDecimals(1)
        self.sub_shadow_offset.setSingleStep(0.5)
        self.sub_shadow_offset.setSuffix(" px")
        self.sub_shadow_offset.setValue(float(current["sub_shadow_offset"]))

        self.sub_back_enabled = QCheckBox("Show background box")
        self.sub_back_enabled.setChecked(bool(current["sub_back_enabled"]))

        self.sub_back_color = QColor(current["sub_back_color"])
        self.back_color_btn = QToolButton()
        self.back_color_btn.setFixedSize(44, 22)
        self.back_color_btn.setStyleSheet(
            f"background:{current['sub_back_color']};border:1px solid #555;border-radius:3px;")
        self.back_color_btn.clicked.connect(lambda: self._pick_color("back"))

        self.sub_back_opacity = QSlider(Qt.Horizontal)
        self.sub_back_opacity.setRange(0, 100)
        self.sub_back_opacity.setSingleStep(5)
        self.sub_back_opacity.setPageStep(5)
        self.sub_back_opacity.setValue(int(current["sub_back_opacity"]))
        self.back_opacity_label = QLabel(f"{int(current['sub_back_opacity'])}%")
        self.sub_back_opacity.valueChanged.connect(
            lambda v: self.back_opacity_label.setText(f"{v}%"))

        # ---- OSD -----------------------------------------------------------
        self.osd_font_size = QSpinBox()
        self.osd_font_size.setRange(6, 36)
        self.osd_font_size.setSuffix(" px")
        self.osd_font_size.setValue(int(current["osd_font_size"]))

        self.osd_opacity = QSlider(Qt.Horizontal)
        self.osd_opacity.setRange(10, 100)
        self.osd_opacity.setSingleStep(5)
        self.osd_opacity.setPageStep(5)
        self.osd_opacity.setValue(int(current["osd_opacity"]))
        self.osd_opacity_label = QLabel(f"{int(current['osd_opacity'])}%")
        self.osd_opacity.valueChanged.connect(
            lambda v: self.osd_opacity_label.setText(f"{v}%"))

        self.osd_color = QColor(current["osd_color"])
        self.osd_color_btn = QToolButton()
        self.osd_color_btn.setFixedSize(44, 22)
        self.osd_color_btn.setStyleSheet(
            f"background:{current['osd_color']};border:1px solid #555;border-radius:3px;")
        self.osd_color_btn.clicked.connect(lambda: self._pick_color("osd"))

        self.seek_osd_enabled = QCheckBox("Show seek OSD (time while seeking)")
        self.seek_osd_enabled.setChecked(bool(current["seek_osd_enabled"]))

        self.osd_background = QCheckBox("Show OSD background")
        self.osd_background.setChecked(bool(current["osd_background_enabled"]))

        # ---- assemble (three tabs) ----------------------------------------
        tabs = QTabWidget()

        gen = QWidget()
        gform = QFormLayout(gen)
        gform.setSpacing(10)
        gform.addRow("Theme:", self.theme_combo)
        gform.addRow("Seek step (←/→):", self.seek_step)
        gform.addRow("Volume step (↑/↓ / wheel):", self.vol_step)
        gform.addRow("Hide controls after:", self.hide_delay)
        gform.addRow("Stream cache size:", self.cache_mb)
        gform.addRow("Backward cache:", self.back_mb)
        tabs.addTab(gen, "General")

        sub = QWidget()
        sform = QFormLayout(sub)
        sform.setSpacing(10)
        sform.addRow("Font:", self.sub_font)

        h = QHBoxLayout()
        h.addWidget(self.sub_scale, 1)
        h.addWidget(self.sub_scale_label)
        sform.addRow("Size:", h)

        sform.addRow("Weight:", self.sub_weight)
        sform.addRow("Outline width:", self.sub_border_size)
        sform.addRow("Shadow depth:", self.sub_shadow_offset)

        h2 = QHBoxLayout()
        h2.addWidget(self.color_btn)
        h2.addStretch(1)
        sform.addRow("Text color:", h2)

        sform.addRow(self.sub_back_enabled)

        h3 = QHBoxLayout()
        h3.addWidget(self.back_color_btn)
        h3.addStretch(1)
        sform.addRow("Box color:", h3)

        h4 = QHBoxLayout()
        h4.addWidget(self.sub_back_opacity, 1)
        h4.addWidget(self.back_opacity_label)
        sform.addRow("Box opacity:", h4)

        hint = QLabel("Note: the background box replaces outline/shadow while it is on.")
        hint.setStyleSheet("color:#8a8a8a;font-size:11px;")
        hint.setWordWrap(True)
        sform.addRow(hint)
        tabs.addTab(sub, "Subtitles")

        osd = QWidget()
        oform = QFormLayout(osd)
        oform.setSpacing(10)
        oform.addRow("OSD font size:", self.osd_font_size)

        h5 = QHBoxLayout()
        h5.addWidget(self.osd_opacity, 1)
        h5.addWidget(self.osd_opacity_label)
        oform.addRow("OSD opacity:", h5)

        h6 = QHBoxLayout()
        h6.addWidget(self.osd_color_btn)
        h6.addStretch(1)
        oform.addRow("OSD color:", h6)

        oform.addRow(self.seek_osd_enabled)
        oform.addRow(self.osd_background)
        tabs.addTab(osd, "OSD")

        # ---- Shortcuts tab (read-only reference) ---------------------------
        keys = QWidget()
        klay = QVBoxLayout(keys)
        klay.setContentsMargins(14, 12, 14, 12)
        klabel = QLabel(self._shortcuts_html(self._pal))
        klabel.setTextFormat(Qt.RichText)
        klabel.setWordWrap(True)
        klabel.setTextInteractionFlags(Qt.TextSelectableByMouse)
        klabel.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        klay.addWidget(klabel)
        tabs.addTab(keys, "Shortcuts")

        # ---- About tab ------------------------------------------------------
        about = QWidget()
        alay = QVBoxLayout(about)
        alay.setContentsMargins(14, 16, 14, 16)
        alay.setSpacing(10)

        brand_row = QHBoxLayout()
        brand_row.setSpacing(12)
        self.about_logo = QLabel()
        self.about_logo.setPixmap(make_app_pixmap(48))
        brand_row.addWidget(self.about_logo, 0, Qt.AlignVCenter)
        brand_box = QVBoxLayout()
        brand_box.setSpacing(0)
        self.about_name = QLabel(APP_NAME)
        self.about_name.setStyleSheet("font-size:20px;font-weight:700;")
        self.about_version = QLabel(f"Version {VERSION}")
        self.about_version.setStyleSheet("font-size:12px;")
        brand_box.addWidget(self.about_name)
        brand_box.addWidget(self.about_version)
        brand_row.addLayout(brand_box)
        brand_row.addStretch(1)
        alay.addLayout(brand_row)

        alay.addSpacing(4)
        about_label = QLabel(self._about_html(self._pal))
        about_label.setTextFormat(Qt.RichText)
        about_label.setWordWrap(True)
        about_label.setTextInteractionFlags(Qt.TextBrowserInteraction)
        about_label.setOpenExternalLinks(True)
        about_label.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        alay.addWidget(about_label)
        alay.addStretch(1)
        tabs.addTab(about, "About")

        tabs.setCurrentIndex(0)

        # custom header (drag to move) — no help "?" and no close button
        header = TitleBar(self)
        header.setObjectName("dlgHeader")
        header.setFixedHeight(38)
        hl = QHBoxLayout(header)
        hl.setContentsMargins(16, 0, 16, 0)
        self.dlg_title = QLabel("Settings")
        self.dlg_title.setObjectName("dlgTitle")
        hl.addWidget(self.dlg_title)
        hl.addStretch(1)

        btns = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel | QDialogButtonBox.Apply)
        btns.button(QDialogButtonBox.Apply).setText("Apply")
        reset_btn = btns.addButton("Reset to defaults", QDialogButtonBox.ResetRole)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        btns.button(QDialogButtonBox.Apply).clicked.connect(
            lambda: self.applied.emit(self.values()))
        reset_btn.clicked.connect(self._reset_to_defaults)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(header)
        inner = QVBoxLayout()
        inner.setContentsMargins(14, 6, 14, 12)
        inner.setSpacing(10)
        inner.addWidget(tabs)
        inner.addWidget(btns)
        lay.addLayout(inner)

    @staticmethod
    def _shortcuts_html(pal):
        chip_bg = pal["ghost"]
        chip_fg = pal["text"]
        val_fg = pal["text"]
        key_fg = pal["dim"]
        rows = [
            ("Space / K", "Play / Pause"),
            ("F / Enter", "Fullscreen"),
            ("M", "Mute"),
            ("S", "Stop"),
            ("← / →", "Seek ±step (default 2s)"),
            ("↑ / ↓", "Volume ±step (default 5%)"),
            ("J / L", "Seek ±10s"),
            (", / .", "Subtitle sync ±0.10s"),
            ("/", "Reset subtitle sync"),
            ("N / P", "Playlist previous / next"),
            ("Ctrl+O", "Open file"),
            ("Esc", "Exit fullscreen"),
            ("Middle click", "Fullscreen"),
            ("Double click", "Play / Pause"),
            ("Mouse wheel", "Volume"),
            ("Double-click title bar", "Maximize / Restore"),
        ]
        html = "<table cellspacing='6'>"
        for k, v in rows:
            html += (
                f"<tr><td style='color:{key_fg};'>"
                f"<span style='background:{chip_bg};color:{chip_fg};padding:2px 8px;"
                f"border-radius:4px;font-weight:600;'>{k}</span></td>"
                    f"<td style='color:{val_fg};'>{v}</td></tr>")
        html += "</table>"
        return html

    @staticmethod
    def _about_html(pal):
        link_fg = pal["accent"]
        dim = pal["dim"]
        return (
            "<p style='font-size:13px;'>A lightweight, YouTube-like video "
            "player for Windows, powered by Python + Qt and the mpv engine "
            "(libmpv).</p>"
            f"<p style='font-size:12px;color:{dim};'>"
            "Full codec support (x264 / x265 / AV1 …), local files and online "
            "streams, custom theming, subtitles and a playlist.</p>"
            f"<p style='font-size:12px;'>"
            f"<a href='{GITHUB_URL}' style='color:{link_fg};'>"
            f"GitHub: {GITHUB_URL}</a></p>"
        )

    def _pick_color(self, which):
        initial = {
            "text": self.sub_color,
            "back": self.sub_back_color,
            "osd": self.osd_color,
        }.get(which, self.sub_color)
        title = {
            "text": "Subtitle text color",
            "back": "Subtitle box color",
            "osd": "Volume OSD color",
        }.get(which, "Color")
        c = QColorDialog.getColor(initial, self, title)
        if c.isValid():
            if which == "text":
                self.sub_color = c
                self.color_btn.setStyleSheet(
                    f"background:{c.name()};border:1px solid #555;border-radius:3px;")
            elif which == "back":
                self.sub_back_color = c
                self.back_color_btn.setStyleSheet(
                    f"background:{c.name()};border:1px solid #555;border-radius:3px;")
            else:
                self.osd_color = c
                self.osd_color_btn.setStyleSheet(
                    f"background:{c.name()};border:1px solid #555;border-radius:3px;")

    def _reset_to_defaults(self):
        d = DEFAULT_CFG
        self.seek_step.setValue(d["seek_step"])
        self.vol_step.setValue(d["vol_step"])
        self.hide_delay.setValue(d["hide_delay"])
        self.cache_mb.setValue(d["cache_mb"])
        self.back_mb.setValue(d["back_mb"])
        ti = self.theme_combo.findData(d["theme"])
        self.theme_combo.setCurrentIndex(ti if ti >= 0 else 0)
        self.sub_font.setCurrentIndex(0)
        self.sub_scale.setValue(d["sub_scale"])
        self.sub_color = QColor(d["sub_color"])
        self.color_btn.setStyleSheet(
            f"background:{d['sub_color']};border:1px solid #555;border-radius:3px;")
        wi = self.sub_weight.findData(d["sub_weight"])
        self.sub_weight.setCurrentIndex(wi if wi >= 0 else 0)
        self.sub_border_size.setValue(d["sub_border_size"])
        self.sub_shadow_offset.setValue(d["sub_shadow_offset"])
        self.sub_back_enabled.setChecked(d["sub_back_enabled"])
        self.sub_back_color = QColor(d["sub_back_color"])
        self.back_color_btn.setStyleSheet(
            f"background:{d['sub_back_color']};border:1px solid #555;border-radius:3px;")
        self.sub_back_opacity.setValue(d["sub_back_opacity"])
        self.osd_font_size.setValue(d["osd_font_size"])
        self.osd_opacity.setValue(d["osd_opacity"])
        self.osd_color = QColor(d["osd_color"])
        self.osd_color_btn.setStyleSheet(
            f"background:{d['osd_color']};border:1px solid #555;border-radius:3px;")
        self.seek_osd_enabled.setChecked(d["seek_osd_enabled"])
        self.osd_background.setChecked(d["osd_background_enabled"])
        self.applied.emit(self.values())

    def values(self):
        font = self.sub_font.currentText()
        return {
            "seek_step": self.seek_step.value(),
            "vol_step": self.vol_step.value(),
            "hide_delay": self.hide_delay.value(),
            "cache_mb": self.cache_mb.value(),
            "back_mb": self.back_mb.value(),
            "theme": self.theme_combo.currentData(),
            "sub_font": "" if font == "Default" else font,
            "sub_scale": self.sub_scale.value(),
            "sub_color": self.sub_color.name(),
            "sub_weight": self.sub_weight.currentData(),
            "sub_border_size": self.sub_border_size.value(),
            "sub_shadow_offset": self.sub_shadow_offset.value(),
            "sub_back_enabled": self.sub_back_enabled.isChecked(),
            "sub_back_color": self.sub_back_color.name(),
            "sub_back_opacity": self.sub_back_opacity.value(),
            "osd_font_size": self.osd_font_size.value(),
            "osd_opacity": self.osd_opacity.value(),
            "osd_color": self.osd_color.name(),
            "osd_background_enabled": self.osd_background.isChecked(),
            "seek_osd_enabled": self.seek_osd_enabled.isChecked(),
        }


# ----------------------------------------------------------------------------
# Main window
# ----------------------------------------------------------------------------
class PlayerWindow(QMainWindow):
    TOP_H = 44
    CTRL_H = 48
    SEEK_H = 16
    RESIZE_BORDER = 6

    def __init__(self):
        super().__init__()
        self.setWindowFlags(self.windowFlags() | Qt.FramelessWindowHint)
        self.setWindowIcon(make_app_icon())
        self.setWindowTitle(APP_NAME)
        self.setMinimumSize(680, 400)
        self.resize(1120, 660)

        self.mpv = None
        self._conf_path = None
        self._current_url = ""

        # playback state
        self._loaded = False
        self._paused = False
        self._buffering = False
        self._eof = False
        self._duration = 0.0
        self._time_pos = 0.0
        self._fw_bytes = 0
        self._file_size = 0
        self._cache_time = 0.0

        # playlist / recent
        self.playlist = []
        self._pl_index = -1
        self._load_gen = 0

        # portable settings
        self._settings_path = _settings_file()
        self.settings = QSettings(self._settings_path, QSettings.IniFormat)
        self._recent = self._load_recent()
        self.cfg = {}
        for k, v in DEFAULT_CFG.items():
            sv = self.settings.value(k, v)
            if isinstance(v, bool):
                self.cfg[k] = self._bool_setting(k, v)
            elif isinstance(v, int):
                try:
                    self.cfg[k] = int(sv)
                except (TypeError, ValueError):
                    self.cfg[k] = v
            elif isinstance(v, float):
                try:
                    self.cfg[k] = float(sv)
                except (TypeError, ValueError):
                    self.cfg[k] = v
            else:
                self.cfg[k] = str(sv) if sv is not None else v

        self.theme = self.cfg.get("theme", "dark")
        self.pal = PALETTES.get(self.theme, PALETTES["dark"])

        self._start_volume = int(self.settings.value("volume", 100))
        self._start_speed = float(self.settings.value("speed", 1.0))

        self.bridge = MpvBridge()
        self._controls_hidden = False
        self._controls_visible = True
        self._cursor_blanked = False
        self._edge_cursor_set = False
        self._last_cursor = QCursor.pos()
        self._last_activity = time.monotonic()

        self._build_ui()
        self._connect_bridge()

        self.setAcceptDrops(True)
        self.setFocusPolicy(Qt.StrongFocus)

        # activity poller (auto-hide in fullscreen)
        self.activity_timer = QTimer(self)
        self.activity_timer.setInterval(300)
        self.activity_timer.timeout.connect(self._poll_activity)
        self.activity_timer.start()

        # single vs double click + de-duplication
        self._click_timer = QTimer(self)
        self._click_timer.setSingleShot(True)
        self._click_timer.setInterval(250)
        self._click_timer.timeout.connect(self._do_single)
        self._last_evt = {}

        # App-wide filter: sees mouse events on ALL widgets (window + native
        # children), used for frameless edge-resize detection and for the
        # click/wheel handling on the mpv surface.
        QApplication.instance().installEventFilter(self)

        self._apply_theme()
        self._position_overlays()

        # restore window geometry / state
        geo = self.settings.value("geometry")
        restored = False
        if geo is not None:
            try:
                restored = self.restoreGeometry(geo)
            except Exception:
                restored = False
        if not restored:
            self._center()
        if self._bool_setting("maximized", False):
            QTimer.singleShot(0, self.showMaximized)

        QTimer.singleShot(0, self._init_mpv)

    # ------------------------------------------------------------- settings
    def _bool_setting(self, key, default):
        v = self.settings.value(key, default)
        if isinstance(v, bool):
            return v
        return str(v).lower() in ("1", "true", "yes", "on")

    def _load_recent(self):
        v = self.settings.value("recent", [])
        if isinstance(v, str):
            v = [v]
        return [x for x in (v or []) if x][:10]

    def _add_recent(self, url):
        self._recent = [u for u in self._recent if u != url]
        self._recent.insert(0, url)
        self._recent = self._recent[:10]
        self.settings.setValue("recent", self._recent)

    def _clear_recent(self):
        self._recent = []
        self.settings.remove("recent")

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        self._central = QWidget(self)
        self.setCentralWidget(self._central)

        lay = QVBoxLayout(self._central)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self.video_host = QWidget(self._central)
        self.video_host.setStyleSheet("background:#000000;")
        lay.addWidget(self.video_host)

        vlay = QVBoxLayout(self.video_host)
        vlay.setContentsMargins(0, 0, 0, 0)
        self.mpv_widget = NativeHost(self.video_host)
        vlay.addWidget(self.mpv_widget)

        self.top_bar = self._build_top_bar(self._central)
        self.seek_bar = SeekBar(self._central)
        self.seek_bar.seekRequested.connect(self._on_seek_requested)
        self.controls_bar = self._build_controls_bar(self._central)

        self.url_panel = self._build_url_panel(self._central)

        # OSD is rendered by mpv itself (show-text) — no Qt overlay, so no
        # black-box issues over the video surface.

        # playlist sidebar (docked right)
        self.playlist_panel = self._build_playlist_panel(self._central)

        for w in (self.top_bar, self.seek_bar, self.controls_bar):
            w.setAttribute(Qt.WA_NativeWindow, True)

    def _build_playlist_panel(self, parent):
        panel = NativeFrame(parent)
        panel.setObjectName("playlistPanel")
        panel.setAttribute(Qt.WA_NativeWindow, True)
        panel.setFixedWidth(300)

        lay = QVBoxLayout(panel)
        lay.setContentsMargins(10, 12, 10, 10)
        lay.setSpacing(8)

        self.playlist_title = QLabel("Playlist")
        self.playlist_title.setStyleSheet("font-weight:700;font-size:13px;")
        lay.addWidget(self.playlist_title)

        self.playlist_list = QListWidget()
        self.playlist_list.setFocusPolicy(Qt.NoFocus)
        self.playlist_list.itemClicked.connect(
            lambda it: self._load_index(int(it.data(Qt.UserRole))))
        lay.addWidget(self.playlist_list)

        panel.hide()
        return panel

    def _build_top_bar(self, parent):
        bar = TitleBar(parent)
        bar.setObjectName("topBar")
        bar.setFixedHeight(self.TOP_H)
        tb = QHBoxLayout(bar)
        tb.setContentsMargins(12, 0, 4, 0)
        tb.setSpacing(6)

        self.logo = QLabel()
        self.logo.setPixmap(make_app_pixmap(18))
        tb.addWidget(self.logo)

        self.brand = QLabel(APP_NAME)
        tb.addWidget(self.brand)

        self.filename_label = QLabel("")
        tb.addWidget(self.filename_label, 1)

        self.drop_banner = QLabel("⬇  Drop a video / subtitle file here")
        self.drop_banner.hide()
        tb.addWidget(self.drop_banner)

        self.buffer_label = QLabel("")
        tb.addWidget(self.buffer_label)

        self.open_btn = QToolButton()
        self.open_btn.setObjectName("noArrow")
        self.open_btn.setIcon(make_icon("open"))
        self.open_btn.setToolTip("Open (Ctrl+O)")
        self.open_btn.setFocusPolicy(Qt.NoFocus)
        self.open_btn.setPopupMode(QToolButton.InstantPopup)
        self._open_menu = QMenu(self)
        self._open_menu.addAction("Open file…", self.open_file)
        self._open_menu.addAction("Open URL…", self._focus_url)
        self._recent_menu = self._open_menu.addMenu("Recent")
        self._open_menu.addSeparator()
        self._open_menu.addAction("Clear recent", self._clear_recent)
        self._open_menu.aboutToShow.connect(self._refresh_recent_menu)
        self.open_btn.setMenu(self._open_menu)
        tb.addWidget(self.open_btn)

        self.cc_btn = QToolButton()
        self.cc_btn.setObjectName("ccBtn")
        self.cc_btn.setIcon(make_icon("cc"))
        self.cc_btn.setToolTip("Subtitles")
        self.cc_btn.setFocusPolicy(Qt.NoFocus)
        self.cc_btn.setPopupMode(QToolButton.InstantPopup)
        self.cc_btn.setMenu(self._build_cc_menu())
        tb.addWidget(self.cc_btn)

        self.settings_btn = QToolButton()
        self.settings_btn.setIcon(make_icon("settings"))
        self.settings_btn.setToolTip("Settings")
        self.settings_btn.setFocusPolicy(Qt.NoFocus)
        self.settings_btn.clicked.connect(self.open_settings)
        tb.addWidget(self.settings_btn)

        tb.addSpacing(10)

        self.min_btn = QToolButton()
        self.min_btn.setIcon(make_icon("min"))
        self.min_btn.setToolTip("Minimize")
        self.min_btn.setFocusPolicy(Qt.NoFocus)
        self.min_btn.clicked.connect(self.showMinimized)
        tb.addWidget(self.min_btn)

        self.max_btn = QToolButton()
        self.max_btn.setIcon(make_icon("max"))
        self.max_btn.setToolTip("Maximize / Restore")
        self.max_btn.setFocusPolicy(Qt.NoFocus)
        self.max_btn.clicked.connect(self._toggle_max)
        tb.addWidget(self.max_btn)

        self.close_btn = QToolButton()
        self.close_btn.setObjectName("winClose")
        self.close_btn.setIcon(make_icon("close"))
        self.close_btn.setToolTip("Close")
        self.close_btn.setFocusPolicy(Qt.NoFocus)
        self.close_btn.clicked.connect(self.close)
        tb.addWidget(self.close_btn)

        bar.doubleClicked.connect(self._toggle_max)
        return bar

    def _build_controls_bar(self, parent):
        bar = ThemedBar(parent, border_at_bottom=False)
        bar.setObjectName("controlsBar")
        bar.setFixedHeight(self.CTRL_H)
        cb = QHBoxLayout(bar)
        cb.setContentsMargins(12, 0, 12, 0)
        cb.setSpacing(10)

        self.prev_btn = QToolButton()
        self.prev_btn.setIcon(make_icon("prev"))
        self.prev_btn.setToolTip("Previous (N)")
        self.prev_btn.setFocusPolicy(Qt.NoFocus)
        self.prev_btn.clicked.connect(self._playlist_prev)
        cb.addWidget(self.prev_btn)

        self.play_btn = QToolButton()
        self.play_btn.setIcon(make_icon("play"))
        self.play_btn.setToolTip("Play / Pause (Space)")
        self.play_btn.setFocusPolicy(Qt.NoFocus)
        self.play_btn.clicked.connect(self.toggle_pause)
        cb.addWidget(self.play_btn)

        self.next_btn = QToolButton()
        self.next_btn.setIcon(make_icon("next"))
        self.next_btn.setToolTip("Next (P)")
        self.next_btn.setFocusPolicy(Qt.NoFocus)
        self.next_btn.clicked.connect(self._playlist_next)
        cb.addWidget(self.next_btn)

        self.stop_btn = QToolButton()
        self.stop_btn.setIcon(make_icon("stop"))
        self.stop_btn.setToolTip("Stop (S)")
        self.stop_btn.setFocusPolicy(Qt.NoFocus)
        self.stop_btn.clicked.connect(self.stop)
        cb.addWidget(self.stop_btn)

        self.volume_btn = QToolButton()
        self.volume_btn.setIcon(make_icon("volume"))
        self.volume_btn.setToolTip("Mute (M)")
        self.volume_btn.setFocusPolicy(Qt.NoFocus)
        self.volume_btn.clicked.connect(self.toggle_mute)
        cb.addWidget(self.volume_btn)

        self.volume_slider = QSlider(Qt.Horizontal)
        self.volume_slider.setObjectName("volume")
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(100)
        self.volume_slider.setFixedWidth(90)
        self.volume_slider.setFocusPolicy(Qt.NoFocus)
        self.volume_slider.valueChanged.connect(self._on_volume_slider)
        cb.addWidget(self.volume_slider)

        self.volume_label = QLabel("100%")
        cb.addWidget(self.volume_label)

        self.time_label = QLabel("0:00 / 0:00")
        cb.addWidget(self.time_label)

        cb.addStretch(1)

        self.speed_btn = QToolButton()
        self.speed_btn.setObjectName("speedBtn")
        self.speed_btn.setText("1x")
        self.speed_btn.setFixedSize(31, 31)
        self.speed_btn.setToolTip("Playback speed")
        self.speed_btn.setFocusPolicy(Qt.NoFocus)
        self.speed_btn.setPopupMode(QToolButton.InstantPopup)
        self.speed_btn.setMenu(self._build_speed_menu())
        cb.addWidget(self.speed_btn)

        self.playlist_btn = QToolButton()
        self.playlist_btn.setIcon(make_icon("list"))
        self.playlist_btn.setIconSize(QSize(16, 16))
        self.playlist_btn.setFixedSize(31, 31)
        self.playlist_btn.setToolTip("Playlist")
        self.playlist_btn.setFocusPolicy(Qt.NoFocus)
        self.playlist_btn.clicked.connect(self.toggle_playlist)
        cb.addWidget(self.playlist_btn)

        self.fullscreen_btn = QToolButton()
        self.fullscreen_btn.setIcon(make_icon("fullscreen"))
        self.fullscreen_btn.setIconSize(QSize(16, 16))
        self.fullscreen_btn.setFixedSize(31, 31)
        self.fullscreen_btn.setToolTip("Fullscreen (F / Enter)")
        self.fullscreen_btn.setFocusPolicy(Qt.NoFocus)
        self.fullscreen_btn.clicked.connect(self.toggle_fullscreen)
        cb.addWidget(self.fullscreen_btn)

        self._update_pl_buttons()
        return bar

    def _build_url_panel(self, parent):
        panel = NativeFrame(parent)
        panel.setObjectName("urlPanel")
        panel.setAttribute(Qt.WA_NativeWindow, True)
        panel.setFixedSize(560, 250)

        lay = QVBoxLayout(panel)
        lay.setContentsMargins(28, 24, 28, 20)
        lay.setSpacing(12)

        title_row = QHBoxLayout()
        logo = QLabel()
        logo.setPixmap(make_app_pixmap(22))
        title_row.addWidget(logo)
        self.url_title = QLabel(APP_NAME)
        title_row.addWidget(self.url_title)
        title_row.addStretch(1)
        lay.addLayout(title_row)

        self.url_hint = QLabel("Paste a video link (MP4 / MKV / …) or drop a file anywhere")
        lay.addWidget(self.url_hint)

        self.url_edit = QLineEdit()
        self.url_edit.setObjectName("urlEdit")
        self.url_edit.setPlaceholderText("https://example.com/video.mp4")
        self.url_edit.returnPressed.connect(self._url_play)
        lay.addWidget(self.url_edit)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.paste_btn = QPushButton("📋 Paste")
        self.paste_btn.setObjectName("urlGhost")
        self.paste_btn.setCursor(Qt.PointingHandCursor)
        self.paste_btn.clicked.connect(self._url_paste)
        row.addWidget(self.paste_btn)

        self.url_play_btn = QPushButton("▶  Play")
        self.url_play_btn.setObjectName("urlPlay")
        self.url_play_btn.setCursor(Qt.PointingHandCursor)
        self.url_play_btn.clicked.connect(self._url_play)
        row.addWidget(self.url_play_btn)

        self.url_open_btn = QPushButton("📂 Open file…")
        self.url_open_btn.setObjectName("urlGhost")
        self.url_open_btn.setCursor(Qt.PointingHandCursor)
        self.url_open_btn.clicked.connect(self.open_file)
        row.addWidget(self.url_open_btn)

        row.addStretch(1)
        lay.addLayout(row)
        return panel

    def _qss(self, p):
        return f"""
        QMainWindow, QWidget {{ background: {p['window']}; color: {p['text']}; }}
        QToolButton {{
            border: none; border-radius: 4px; padding: 6px; background: transparent;
        }}
        QToolButton:hover {{ background: {p['hover']}; }}
        QToolButton:pressed {{ background: {p['pressed']}; }}
        QToolButton::menu-indicator {{ image: none; width: 0px; }}
        QToolButton#winClose:hover {{ background: #e81123; }}
        QToolButton#speedBtn {{ padding: 2px; font-size: 10px; font-weight: 600; }}
        QWidget#topBar, QWidget#controlsBar {{ background: {p['window']}; }}
        QWidget#topBar {{ border-bottom: 1px solid {p['panel_border']}; }}
        QWidget#controlsBar {{ border-top: 1px solid {p['panel_border']}; }}
        QWidget#dlgHeader {{ background: {p['panel']}; border-bottom: 1px solid {p['panel_border']}; }}
        QLabel#dlgTitle {{ color: {p['text']}; font-weight: 700; font-size: 14px; }}
        QPushButton {{
            background: {p['ghost']}; color: {p['text']}; border: none;
            border-radius: 4px; padding: 7px 14px;
        }}
        QPushButton:hover {{ background: {p['ghost_hover']}; }}
        QPushButton:pressed {{ background: {p['pressed']}; }}
        QSlider::groove:horizontal {{
            height: 4px; background: {p['track']}; border-radius: 2px;
        }}
        QSlider::sub-page:horizontal {{ background: {p['text']}; border-radius: 2px; }}
        QSlider::handle:horizontal {{
            width: 12px; height: 12px; margin: -4px 0;
            background: {p['thumb']}; border-radius: 6px;
        }}
        QSlider::handle:horizontal:hover {{ background: {p['text']}; }}
        QMenu {{ background: {p['panel2']}; border: 1px solid {p['panel_border']}; padding: 4px; }}
        QMenu::item {{ padding: 6px 22px; border-radius: 4px; font-size: 12px; }}
        QMenu::item:selected {{ background: {p['hover']}; }}
        QMenu::separator {{ height: 1px; background: {p['panel_border']}; margin: 4px 8px; }}
        QDialog {{ background: {p['window']}; color: {p['text']}; }}
        QComboBox, QSpinBox, QDoubleSpinBox {{
            background: {p['input_bg']}; color: {p['text']}; border: 1px solid {p['field_border']};
            border-radius: 4px; padding: 4px 6px;
        }}
        QComboBox QAbstractItemView {{
            background: {p['input_bg']}; color: {p['text']};
            selection-background-color: {p['hover']};
            selection-color: {p['text']};
        }}
        QCheckBox {{ spacing: 6px; }}
        QLabel {{ background: transparent; }}
        QTabWidget::pane {{
            border: 1px solid {p['panel_border']}; background: {p['panel']};
            border-radius: 6px; top: -1px;
        }}
        QTabBar::tab {{
            background: {p['tab_bg']}; color: {p['dim']};
            padding: 8px 20px; border: none;
            border-top-left-radius: 6px; border-top-right-radius: 6px; margin-right: 2px;
        }}
        QTabBar::tab:hover {{ background: {p['tab_hover']}; color: {p['text']}; }}
        QTabBar::tab:selected {{
            background: {p['tab_sel']}; color: {p['text']};
            border-top: 2px solid {p['red']};
        }}
        QFrame#urlPanel {{
            background: {p['panel']}; border: 1px solid {p['panel_border']}; border-radius: 10px;
        }}
        QFrame#playlistPanel {{
            background: {p['panel']}; border-left: 1px solid {p['panel_border']};
        }}
        QListWidget {{
            background: transparent; color: {p['text']}; border: none;
            font-size: 12px; outline: none;
        }}
        QListWidget::item {{ padding: 8px 10px; border-radius: 4px; }}
        QListWidget::item:hover {{ background: {p['hover']}; }}
        QListWidget::item:selected {{ background: {p['ghost']}; color: {p['text']}; }}
        QLineEdit#urlEdit {{
            background: {p['field_bg']}; border: 1px solid {p['field_border']};
            border-radius: 4px; padding: 8px 10px; color: {p['text']}; font-size: 13px;
        }}
        QLineEdit#urlEdit:focus {{ border: 1px solid {p['accent']}; }}
        QPushButton#urlPlay {{
            background: {p['red']}; color: #ffffff; border: none; border-radius: 4px;
            padding: 8px 18px; font-weight: 700;
        }}
        QPushButton#urlPlay:hover {{ background: #d60000; }}
        QPushButton#urlGhost {{
            background: {p['ghost']}; color: {p['text']}; border: none; border-radius: 4px;
            padding: 8px 14px;
        }}
        QPushButton#urlGhost:hover {{ background: {p['ghost_hover']}; }}
        """

    # -------------------------------------------------------------- menus
    def _build_cc_menu(self):
        m = QMenu(self)
        m.addAction("Add subtitle file…", self._add_subtitle_dialog)
        m.addSeparator()
        m.addAction("Turn subtitles off", lambda: self._select_sid(None))
        m.addSeparator()
        self._cc_track_menu = m.addMenu("Subtitle track")
        m.aboutToShow.connect(self._refresh_cc_menu)
        return m

    def _refresh_cc_menu(self):
        self._cc_track_menu.clear()
        if self.mpv is None:
            return
        try:
            tracks = [t for t in (self.mpv.track_list or []) if t.get("type") == "sub"]
        except Exception:
            tracks = []
        if not tracks:
            a = self._cc_track_menu.addAction("(no embedded subtitles)")
            a.setEnabled(False)
            return
        for t in tracks:
            title = t.get("title") or t.get("lang") or f"Track {t.get('id')}"
            self._cc_track_menu.addAction(title, lambda _id=t["id"]: self._select_sid(_id))

    def _refresh_recent_menu(self):
        self._recent_menu.clear()
        if not self._recent:
            a = self._recent_menu.addAction("(empty)")
            a.setEnabled(False)
            return
        for u in self._recent:
            self._recent_menu.addAction(self._display_name(u), lambda x=u: self.load(x))

    def _build_speed_menu(self):
        m = QMenu(self)
        for sp in [0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0]:
            m.addAction(f"{sp:g}x", lambda s=sp: self._set_speed(s))
        return m

    # ----------------------------------------------------------- bridge
    def _connect_bridge(self):
        b = self.bridge
        b.time_changed.connect(self._on_time_changed)
        b.duration_changed.connect(self._on_duration_changed)
        b.pause_changed.connect(self._on_pause_changed)
        b.buffering_changed.connect(self._on_buffering_changed)
        b.cache_changed.connect(self._on_cache_changed)
        b.ranges_changed.connect(self.seek_bar.set_ranges)
        b.eof_changed.connect(self._on_eof_changed)
        b.file_loaded.connect(self._on_file_loaded)
        b.load_error.connect(self._on_load_error)
        b.ended.connect(self._on_ended)
        b.single_click.connect(self._on_single_click)
        b.dbl_click.connect(self._on_dbl_click)
        b.middle_click.connect(self._on_middle_click)

    # ------------------------------------------------------- mpv engine
    def _write_input_conf(self):
        content = (
            "# Lumo input bindings (mouse -> Qt via script-message)\n"
            "MBTN_LEFT      script-message qt-click\n"
            "MBTN_LEFT_DBL  script-message qt-dblclick\n"
            "MBTN_MID       script-message qt-middle\n"
        )
        try:
            path = Path(tempfile.gettempdir()) / "lumo_input.conf"
            path.write_text(content, encoding="utf-8")
            return str(path)
        except Exception:
            path = Path.cwd() / "lumo_input.conf"
            path.write_text(content, encoding="utf-8")
            return str(path)

    def _init_mpv(self):
        if not MPV_AVAILABLE:
            self._show_engine_error(
                MPV_IMPORT_ERROR or "python-mpv is not installed "
                "(run:  pip install python-mpv)")
            return

        search_dirs = [os.path.dirname(os.path.abspath(__file__))]
        if getattr(sys, "frozen", False):
            search_dirs.append(getattr(sys, "_MEIPASS", ""))
            search_dirs.append(os.path.dirname(sys.executable))
        dll_path = None
        for _d in search_dirs:
            if not _d:
                continue
            _p = os.path.join(_d, "libmpv-2.dll")
            if os.path.exists(_p):
                dll_path = _p
                break
        if dll_path:
            dll_dir = os.path.dirname(dll_path)
            os.environ["MPV_LIBRARY"] = dll_path
            try:
                os.add_dll_directory(dll_dir)
            except Exception:
                pass
            try:
                ctypes.CDLL(dll_path)
            except OSError as e:
                self._show_engine_error(self._describe_load_error(e, dll_path))
                return

        hwnd = int(self.mpv_widget.winId())
        self._conf_path = self._write_input_conf()

        try:
            self.mpv = _mpv.MPV(
                wid=hwnd,
                osc=False,
                osd_level=1,
                input_default_bindings=False,
                input_vo_keyboard=False,
                input_conf=self._conf_path,
                config="no",
                load_scripts="no",
                idle="yes",
                keep_open="yes",
                cache="yes",
                demuxer_max_bytes=f"{self.cfg['cache_mb']}MiB",
                demuxer_max_back_bytes=f"{self.cfg['back_mb']}MiB",
                hwdec="auto-safe",
                ytdl="no",
                sub_auto="fuzzy",
                sub_visibility=True,
                volume=100,
            )
        except Exception as e:
            self._show_engine_error(str(e))
            return

        # Let mouse events pass through mpv's window to the Qt widget below.
        try:
            self.mpv.input_cursor_passthrough = True
        except Exception:
            pass

        # mouse -> Qt (backup path)
        self.mpv.register_message_handler("qt-click", lambda *a: self.bridge.single_click.emit())
        self.mpv.register_message_handler("qt-dblclick", lambda *a: self.bridge.dbl_click.emit())
        self.mpv.register_message_handler("qt-middle", lambda *a: self.bridge.middle_click.emit())

        # property observation
        self.mpv.observe_property("time-pos", self._ob_time_pos)
        self.mpv.observe_property("duration", self._ob_duration)
        self.mpv.observe_property("pause", self._ob_pause)
        self.mpv.observe_property("paused-for-cache", self._ob_pfc)
        self.mpv.observe_property("demuxer-cache-state", self._ob_cache_state)
        self.mpv.observe_property("file-size", self._ob_file_size)
        self.mpv.observe_property("demuxer-cache-time", self._ob_cache_time)
        self.mpv.observe_property("eof-reached", self._ob_eof)

        try:
            @self.mpv.event_callback("file-loaded")
            def _file_loaded(ev):
                self.bridge.file_loaded.emit(self._load_gen)

            @self.mpv.event_callback("end-file")
            def _end_file(ev):
                reason = ""
                try:
                    d = ev.as_dict() if hasattr(ev, "as_dict") else {}
                    reason = str((d or {}).get("reason", "") or "")
                except Exception:
                    try:
                        r = int(getattr(ev.data, "reason", -1))
                        reason = {0: "eof", 1: "restarted", 2: "aborted",
                                  3: "quit", 4: "error", 5: "redirect"}.get(r, "unknown")
                    except Exception:
                        reason = ""
                self.bridge.ended.emit(self._load_gen, reason)
        except Exception:
            pass

        self._apply_sub_style()

        # restore remembered volume / speed
        try:
            self.mpv.volume = self._start_volume
            self.mpv.speed = self._start_speed
        except Exception:
            pass
        self.volume_slider.blockSignals(True)
        self.volume_slider.setValue(self._start_volume)
        self.volume_slider.blockSignals(False)
        self.volume_label.setText(f"{self._start_volume}%")
        self.speed_btn.setText(f"{self._start_speed:g}x")
        self._update_volume_icon()

        self._raise_overlays()

    @staticmethod
    def _describe_load_error(e, dll_path):
        we = getattr(e, "winerror", None)
        py_bits = struct.calcsize("P") * 8
        dll_bits = pe_machine(dll_path)
        if dll_bits in (PE_X64, PE_X86) and (
            (dll_bits == PE_X64 and py_bits == 32) or
            (dll_bits == PE_X86 and py_bits == 64)):
            return ("Bitness mismatch: Python is {py}-bit but libmpv-2.dll is "
                    "{dll}-bit.\nYou need the "
                    "{need} build.".format(
                        py=py_bits,
                        dll=64 if dll_bits == PE_X64 else 32,
                        need="i686 (32-bit)" if py_bits == 32 else "x86_64 (64-bit)"))
        if we == 193:
            return ("Error 193: the DLL architecture does not match Python "
                    "(check whether Python is 32- or 64-bit).")
        if we == 126:
            return ("Error 126: libmpv-2.dll was found, but one of its "
                    "dependencies is missing.\nInstall the latest Microsoft "
                    "Visual C++ Redistributable (vc_redist.x64.exe) and retry.")
        return f"{e} (winerror {we})" if we else str(e)

    def _show_engine_error(self, reason=""):
        msg = "The mpv engine (libmpv-2.dll) could not be loaded.\n\n"
        if reason:
            msg += f"Reason: {reason}\n\n"
        msg += (
            "Quick fixes:\n"
            "  1) Run  check_engine.py  to see exactly what is wrong.\n"
            "  2) Run  get_libmpv.bat  to download a matching libmpv-2.dll.\n"
            "  3) Make sure python-mpv is installed:\n"
            "        pip install python-mpv\n\n"
            "Manual download (the dev build contains libmpv-2.dll):\n"
            "  https://sourceforge.net/projects/mpv-player-windows/files/libmpv/\n"
            "  -> for 64-bit Python:  mpv-dev-x86_64-*.7z\n"
            "  -> for 32-bit Python:  mpv-dev-i686-*.7z\n\n"
            "Extract it and copy libmpv-2.dll next to this program."
        )
        QMessageBox.critical(self, "mpv engine not loaded", msg)

    # --------------------------------------------- mpv observers (mpv thread)
    def _ob_time_pos(self, name, value):
        self.bridge.time_changed.emit(value or 0.0, self._duration)

    def _ob_duration(self, name, value):
        self.bridge.duration_changed.emit(value or 0.0)

    def _ob_pause(self, name, value):
        self.bridge.pause_changed.emit(bool(value))

    def _ob_pfc(self, name, value):
        self.bridge.buffering_changed.emit(bool(value))

    def _ob_cache_state(self, name, value):
        ranges = []
        try:
            for r in (value or {}).get("seekable-ranges", []) or []:
                ranges.append((float(r.get("start", 0)), float(r.get("end", 0))))
        except Exception:
            pass
        fw = 0
        try:
            fw = int((value or {}).get("fw-bytes", 0) or 0)
        except Exception:
            pass
        self.bridge.ranges_changed.emit(ranges)
        self.bridge.cache_changed.emit(float(fw), float(self._file_size), float(self._cache_time))

    def _ob_file_size(self, name, value):
        self.bridge.cache_changed.emit(float(self._fw_bytes), float(value or 0), float(self._cache_time))

    def _ob_cache_time(self, name, value):
        self.bridge.cache_changed.emit(float(self._fw_bytes), float(self._file_size), float(value or 0))

    def _ob_eof(self, name, value):
        self.bridge.eof_changed.emit(bool(value))

    # --------------------------------------------- main-thread UI slots
    def _on_time_changed(self, pos, dur):
        self._time_pos = pos
        self._duration = dur
        self.seek_bar.set_position(pos)
        self.seek_bar.set_duration(dur)
        if dur > 0:
            self.time_label.setText(f"{self._fmt(pos)} / {self._fmt(dur)}")
        else:
            self.time_label.setText(f"{self._fmt(pos)} / --:--")

    def _on_duration_changed(self, dur):
        self._duration = dur
        self.seek_bar.set_duration(dur)

    def _on_pause_changed(self, paused):
        self._paused = paused
        self._update_play_icon()

    def _on_buffering_changed(self, buffering):
        self._buffering = buffering
        self.buffer_label.setText("Buffering…" if buffering else "")

    def _on_cache_changed(self, fw, fsize, cache_time):
        self._fw_bytes = fw
        self._file_size = fsize
        self._cache_time = cache_time
        if self._loaded and not self._buffering and fsize > 0 and fw > 0:
            pct = min(100.0, fw / fsize * 100.0)
            self.buffer_label.setText(f"Buffered {pct:.0f}%  ({fw / 1048576:.1f} MB)")
        elif self._loaded and not self._buffering and cache_time > 0:
            self.buffer_label.setText(f"Buffered {int(cache_time)}s")
        else:
            if not self._buffering:
                self.buffer_label.setText("")

    def _on_eof_changed(self, eof):
        self._eof = eof
        self._update_play_icon()
        if eof and self._pl_index + 1 < len(self.playlist):
            gen = self._load_gen
            QTimer.singleShot(0, lambda: self._advance_playlist(gen))

    def _advance_playlist(self, gen):
        if gen != self._load_gen:
            return
        if not self._eof:
            return
        if self._pl_index + 1 < len(self.playlist):
            self._load_index(self._pl_index + 1)

    def _on_file_loaded(self, gen):
        if gen != self._load_gen:
            return  # stale load event from a previous file
        self._loaded = True
        self._eof = False
        self._hide_url_panel()
        self.mpv_widget.show()
        self._update_play_icon()
        self._mark_activity()

    def _on_load_error(self, url):
        self._loaded = False
        self._show_url_panel()
        if url:
            self.url_edit.setText(url)
        self._update_play_icon()
        QMessageBox.warning(self, "Load failed", f"Could not play:\n{url}")

    def _on_ended(self, gen, reason):
        if gen != self._load_gen:
            return  # stale load event from a previous file
        if reason in ("error", "unknown"):
            self._on_load_error(self._current_url)

    # ------------------------------------------------- mouse -> actions
    def _dedup(self, key, ms):
        now = time.monotonic()
        last = self._last_evt.get(key, 0.0)
        if now - last < ms / 1000.0:
            return True
        self._last_evt[key] = now
        return False

    def _schedule_single(self):
        self._click_timer.start()

    def _do_single(self):
        self._mark_activity()
        self.setFocus()

    def _do_double(self):
        self._click_timer.stop()
        if self._dedup("dbl", 250):
            return
        self._mark_activity()
        self.toggle_pause()

    def _do_middle(self):
        self._click_timer.stop()
        if self._dedup("mid", 250):
            return
        self._mark_activity()
        self.toggle_fullscreen()

    def _on_single_click(self):
        self._schedule_single()

    def _on_dbl_click(self):
        self._do_double()

    def _on_middle_click(self):
        self._do_middle()

    def _on_wheel(self, direction):
        if self._dedup("wheel", 90):
            return
        self.change_volume(self.cfg["vol_step"] * direction)

    def _resize_edges(self):
        """Return the Qt.Edges for the window border under the cursor, or 0 if
        the cursor is not on a resize border. Uses Qt logical coordinates, so
        it is correct on scaled (High-DPI) displays."""
        if self.isFullScreen() or self.isMaximized():
            return Qt.Edges(0)
        try:
            g = self.frameGeometry()
            p = QCursor.pos()
            b = RESIZE_BORDER
            left = p.x() <= g.left() + b
            right = p.x() >= g.right() - b
            top = p.y() <= g.top() + b
            bottom = p.y() >= g.bottom() - b
            edges = Qt.Edges(0)
            if left:
                edges |= Qt.LeftEdge
            if right:
                edges |= Qt.RightEdge
            if top:
                edges |= Qt.TopEdge
            if bottom:
                edges |= Qt.BottomEdge
            return edges
        except Exception:
            return Qt.Edges(0)

    def _restore_edge_cursor(self):
        if self._edge_cursor_set:
            try:
                QApplication.restoreOverrideCursor()
            except Exception:
                pass
            self._edge_cursor_set = False

    def _update_edge_cursor(self):
        if self.isFullScreen() or self.isMaximized():
            return
        edges = self._resize_edges()
        if edges:
            if edges == (Qt.LeftEdge | Qt.TopEdge) or edges == (Qt.RightEdge | Qt.BottomEdge):
                shape = Qt.SizeFDiagCursor
            elif edges == (Qt.RightEdge | Qt.TopEdge) or edges == (Qt.LeftEdge | Qt.BottomEdge):
                shape = Qt.SizeBDiagCursor
            elif edges & (Qt.LeftEdge | Qt.RightEdge):
                shape = Qt.SizeHorCursor
            else:
                shape = Qt.SizeVerCursor
            if not self._edge_cursor_set:
                QApplication.setOverrideCursor(shape)
                self._edge_cursor_set = True
        else:
            self._restore_edge_cursor()

    def eventFilter(self, obj, ev):
        t = ev.type()
        # Frameless edge/corner resize: a left-button press on the window's
        # resize border starts a system resize, no matter which widget
        # (native or not) received the press.
        if t == QEvent.MouseButtonPress and ev.button() == Qt.LeftButton:
            edges = self._resize_edges()
            if edges:
                try:
                    wh = self.windowHandle()
                    if wh is not None:
                        wh.startSystemResize(edges)
                        return True  # consume
                except Exception:
                    pass
        elif t == QEvent.MouseMove:
            self._update_edge_cursor()

        if obj is self.mpv_widget:
            if t == QEvent.MouseButtonPress:
                if ev.button() == Qt.MiddleButton:
                    self._do_middle()
                elif ev.button() == Qt.LeftButton:
                    self._schedule_single()
            elif t == QEvent.MouseButtonDblClick:
                if ev.button() == Qt.LeftButton:
                    self._do_double()
            elif t == QEvent.Wheel:
                d = ev.angleDelta().y()
                if d > 0:
                    self._on_wheel(1)
                elif d < 0:
                    self._on_wheel(-1)
        return super().eventFilter(obj, ev)

    def _on_seek_requested(self, seconds):
        if self.mpv is not None:
            try:
                self.mpv.seek(seconds, reference="absolute")
            except Exception:
                pass

    # ---------------------------------------------------------- URL panel
    def _focus_url(self):
        self._show_url_panel()
        self.url_edit.setFocus()

    def _show_url_panel(self):
        self.url_panel.show()
        self._raise_overlays()

    def _hide_url_panel(self):
        self.url_panel.hide()

    def _url_paste(self):
        clip = QApplication.clipboard().text().strip()
        if clip:
            self.url_edit.setText(clip)
            self.url_edit.setFocus()

    def _url_play(self):
        u = self.url_edit.text().strip()
        if u:
            self.load(u)

    # ------------------------------------------------- playlist / load
    def _update_pl_buttons(self):
        self.prev_btn.setEnabled(self._pl_index > 0)
        self.next_btn.setEnabled(self._pl_index + 1 < len(self.playlist))
        self._refresh_playlist_list()

    def _refresh_playlist_list(self):
        if not hasattr(self, "playlist_list"):
            return
        self.playlist_list.clear()
        for i, u in enumerate(self.playlist):
            it = QListWidgetItem(self._display_name(u))
            it.setData(Qt.UserRole, i)
            self.playlist_list.addItem(it)
        if 0 <= self._pl_index < self.playlist_list.count():
            self.playlist_list.setCurrentRow(self._pl_index)

    def toggle_playlist(self):
        if self.playlist_panel.isVisible():
            self.playlist_panel.hide()
        else:
            self._refresh_playlist_list()
            self.playlist_panel.show()
            self._raise_overlays()

    def _playlist_next(self):
        if self._pl_index + 1 < len(self.playlist):
            self._load_index(self._pl_index + 1)

    def _playlist_prev(self):
        if self._pl_index - 1 >= 0:
            self._load_index(self._pl_index - 1)

    def _load_index(self, i):
        if 0 <= i < len(self.playlist):
            self._pl_index = i
            self._load_one(self.playlist[i])

    def open_file(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Open video(s)",
            "",
            "Video files (*.mp4 *.mkv *.webm *.avi *.mov *.flv *.wmv *.m4v *.ts *.m2ts "
            "*.mpg *.mpeg *.3gp *.ogv);;All files (*.*)")
        if not paths:
            return
        if len(paths) == 1:
            self.load(paths[0])
        else:
            self.playlist = list(paths)
            self._pl_index = -1
            self._load_index(0)

    def load(self, url, sub=None):
        self.playlist = [url]
        self._pl_index = 0
        self._load_one(url, sub)

    def _load_one(self, url, sub=None):
        if self.mpv is None:
            self._show_engine_error()
            return
        self._load_gen += 1
        self._current_url = url
        # reset per-file state so stale values from the previous playback
        # cannot leak into the new one (wrong labels, seek state, etc.).
        self._duration = 0.0
        self._time_pos = 0.0
        self._eof = False
        self._buffering = False
        self.seek_bar.set_duration(0)
        self.seek_bar.set_position(0)
        self.seek_bar.set_ranges([])
        self.time_label.setText("0:00 / 0:00")
        try:
            self.mpv.demuxer_max_bytes = f"{self.cfg['cache_mb']}MiB"
            self.mpv.demuxer_max_back_bytes = f"{self.cfg['back_mb']}MiB"
            self.mpv.sub_delay = 0.0
        except Exception:
            pass
        # Fully unload the engine before EVERY load. Re-opening a file that was
        # previously loaded/played is unreliable with keep-open=yes: loadfile()
        # of such a URL can leave libmpv stuck, with a black picture, or with a
        # stale/blank seek bar on Windows. The reliable sequence is the exact
        # manual workaround the user found — Stop -> Play — so we always
        # stop() first and then load from a clean idle state.
        self._engine_stop()
        try:
            self.mpv.loadfile(url)
        except Exception:
            self._on_load_error(url)
            return

        # A newly loaded file must always start playing, even if the player
        # was paused when it was requested (mpv keeps `pause` across loads).
        try:
            self.mpv.pause = False
        except Exception:
            pass
        self._paused = False

        self._loaded = True
        self._hide_url_panel()
        self.mpv_widget.show()
        self.filename_label.setText(self._display_name(url))
        self.setWindowTitle(f"{self._display_name(url)} — {APP_NAME}")
        if sub:
            self._add_subtitle_path(sub)
        self._add_recent(url)
        self._update_pl_buttons()
        self._mark_activity()

    # ---------------------------------------------------------- actions
    def add_subtitle(self, path):
        if self.mpv is None:
            self._show_engine_error()
            return
        self._add_subtitle_path(path)

    def _add_subtitle_path(self, path):
        try:
            self.mpv.sub_add(path, "select")
        except Exception as e:
            QMessageBox.warning(self, "Subtitle", f"Could not load subtitle:\n{path}\n\n{e}")

    def _add_subtitle_dialog(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open subtitle", "",
            "Subtitle files (*.srt *.ass *.ssa *.vtt *.sub *.lrc);;All files (*.*)")
        if path:
            self.add_subtitle(path)

    def _select_sid(self, sid):
        if self.mpv is None:
            return
        try:
            self.mpv.sid = "no" if sid is None else sid
        except Exception:
            pass

    def toggle_pause(self):
        if self.mpv is None or not self._loaded:
            return
        if self._eof:
            try:
                self.mpv.seek(0, reference="absolute")
                self.mpv.pause = False
            except Exception:
                pass
            return
        try:
            self.mpv.pause = not bool(self.mpv.pause)
        except Exception:
            pass

    def _engine_stop(self):
        """Fully unload whatever mpv is playing and return it to idle state.
        Used both by the user-facing Stop and before reloading a file that is
        already loaded (see _load_one)."""
        if self.mpv is None:
            return
        try:
            self.mpv.stop()
        except Exception:
            try:
                self.mpv.command("stop")
            except Exception:
                pass

    def stop(self):
        self._load_gen += 1
        self._engine_stop()
        self._loaded = False
        self._eof = False
        self._paused = False
        self._duration = 0.0
        self._time_pos = 0.0
        self._fw_bytes = 0
        self._file_size = 0
        self._cache_time = 0.0
        # NOTE: the playlist is deliberately kept (not cleared) on Stop, so the
        # user can re-play an item from it. Only playback state is reset.
        self.seek_bar.set_duration(0)
        self.seek_bar.set_position(0)
        self.seek_bar.set_ranges([])
        self.time_label.setText("0:00 / 0:00")
        self.buffer_label.setText("")
        self.filename_label.setText("")
        self.setWindowTitle(APP_NAME)
        self._update_play_icon()
        self._update_pl_buttons()
        self._show_url_panel()
        self._mark_activity()

    def toggle_mute(self):
        if self.mpv is None:
            return
        try:
            self.mpv.mute = not bool(self.mpv.mute)
        except Exception:
            pass
        self._update_volume_icon()
        self._show_volume_osd()

    def _apply_volume(self, v):
        v = min(100, max(0, int(round(v))))
        if self.mpv is not None:
            try:
                self.mpv.volume = v
            except Exception:
                pass
        self.volume_slider.blockSignals(True)
        self.volume_slider.setValue(v)
        self.volume_slider.blockSignals(False)
        self.volume_label.setText(f"{v}%")
        self._update_volume_icon()
        self._show_volume_osd()

    def _on_volume_slider(self, v):
        self._apply_volume(v)

    def change_volume(self, delta):
        if self.mpv is None:
            return
        try:
            cur = int(self.mpv.volume)
        except Exception:
            return
        self._apply_volume(cur + delta)

    def _update_volume_icon(self):
        try:
            muted = bool(self.mpv.mute)
            vol = int(self.mpv.volume)
        except Exception:
            return
        self.volume_btn.setIcon(self._ic("muted" if (muted or vol == 0) else "volume"))

    def seek_relative(self, delta):
        if self.mpv is None or not self._loaded:
            return
        try:
            self.mpv.seek(delta, reference="relative", precision="exact")
        except Exception:
            pass
        self._show_seek_osd(self._time_pos + delta)

    def _sub_sync(self, delta):
        if self.mpv is None:
            return
        try:
            cur = float(self.mpv.sub_delay or 0.0)
        except Exception:
            cur = 0.0
        nv = cur + delta
        try:
            self.mpv.sub_delay = nv
        except Exception:
            pass
        self._flash_osd(f"Subtitle sync: {nv:+.2f}s")

    def _reset_sub_sync(self):
        if self.mpv is None:
            return
        try:
            self.mpv.sub_delay = 0.0
        except Exception:
            pass
        self._flash_osd("Subtitle sync: +0.00s")

    def _set_speed(self, sp):
        if self.mpv is not None:
            try:
                self.mpv.speed = sp
            except Exception:
                pass
        self.speed_btn.setText(f"{sp:g}x")

    def toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
        else:
            self._restore_edge_cursor()
            self.showFullScreen()
        self._update_fs_icon()
        self._show_controls()
        self._mark_activity()

    # ------------------------------------------------- window controls
    def _toggle_max(self):
        if self.isMaximized():
            self.showNormal()
        else:
            self._restore_edge_cursor()
            self.showMaximized()
        self.max_btn.setIcon(self._ic("restore" if self.isMaximized() else "max"))
        self._position_overlays()

    def _update_fs_icon(self):
        self.fullscreen_btn.setIcon(
            self._ic("fullscreen_exit" if self.isFullScreen() else "fullscreen"))

    # ------------------------------------------------------------- OSD
    def _apply_osd_style(self):
        # OSD text is drawn by mpv itself (show-text), so we configure the
        # mpv OSD style options. No Qt overlay -> no black-box artifacts.
        if self.mpv is None:
            return
        try:
            fs = min(36, max(6, int(self.cfg.get("osd_font_size", 14))))
            scaled = int(round(fs * 55.0 / 30.0))
            op = min(100, max(10, int(self.cfg.get("osd_opacity", 85))))
            a = int(round(op / 100.0 * 255))
            c = QColor(self.cfg.get("osd_color", "#ffffff"))

            self.mpv.osd_font_size = scaled
            self.mpv.osd_color = f"#{a:02X}{c.red():02X}{c.green():02X}{c.blue():02X}"
            self.mpv.osd_outline_color = "#66000000"
            self.mpv.osd_border_size = 2.0
            self.mpv.osd_align_x = "left"
            self.mpv.osd_align_y = "top"

            if self.cfg.get("osd_background_enabled", False):
                bg = QColor(self.pal["osd_bg"])
                self.mpv.osd_back_color = f"#{a:02X}{bg.red():02X}{bg.green():02X}{bg.blue():02X}"
                self.mpv.osd_border_style = "background-box"
            else:
                self.mpv.osd_back_color = "#00000000"
                self.mpv.osd_border_style = "outline-and-shadow"

            self._update_osd_margin()
        except Exception:
            pass

    def _update_osd_margin(self):
        if self.mpv is None:
            return
        try:
            self.mpv.osd_margin_x = 24
            self.mpv.osd_margin_y = (self.TOP_H if self._controls_visible else 0) + 16
        except Exception:
            pass

    def _show_osd(self, text):
        if self.mpv is not None:
            try:
                self.mpv.command("show-text", text, 1200)
            except Exception:
                pass

    def _show_volume_osd(self):
        muted = False
        vol = 100
        try:
            if self.mpv is not None:
                muted = bool(self.mpv.mute)
                vol = int(self.mpv.volume)
        except Exception:
            pass
        self._show_osd("Muted" if muted else f"Volume  {vol}%")

    def _flash_osd(self, text):
        self._show_osd(text)

    def _show_seek_osd(self, target=None):
        if not self.cfg.get("seek_osd_enabled", True):
            return
        if not self._loaded:
            return
        pos = self._time_pos if target is None else target
        self._show_osd(f"{self._fmt(pos)} / {self._fmt(self._duration)}")

    # ------------------------------------------- controls auto-hide logic
    def _mark_activity(self, show=True):
        self._last_activity = time.monotonic()
        if show:
            self._show_controls()

    def _raise_overlays(self):
        self.url_panel.raise_()
        self.playlist_panel.raise_()
        self.seek_bar.raise_()
        self.top_bar.raise_()
        self.controls_bar.raise_()

    def _update_sub_pos(self):
        if self.mpv is None:
            return
        try:
            self.mpv.sub_pos = 92 if self._controls_visible else 100
        except Exception:
            pass

    def _show_controls(self):
        self._controls_visible = True
        if self._controls_hidden:
            for w in (self.top_bar, self.seek_bar, self.controls_bar):
                w.show()
        self._controls_hidden = False
        self._raise_overlays()
        self._update_sub_pos()
        self._update_osd_margin()
        if self._cursor_blanked:
            QApplication.restoreOverrideCursor()
            self._cursor_blanked = False

    def _hide_controls(self):
        if self._controls_hidden:
            return
        self._controls_hidden = True
        self._controls_visible = False
        for w in (self.top_bar, self.seek_bar, self.controls_bar):
            w.hide()
        self._update_sub_pos()
        self._update_osd_margin()
        if not self._cursor_blanked:
            QApplication.setOverrideCursor(Qt.BlankCursor)
            self._cursor_blanked = True

    def _poll_activity(self):
        cur = QCursor.pos()
        if cur != self._last_cursor:
            self._last_cursor = cur
            self._last_activity = time.monotonic()
            if self._controls_hidden:
                self._show_controls()
            return

        playing = self._loaded and not self._paused and not self._buffering
        if self.isFullScreen() and playing and not self._controls_hidden:
            if time.monotonic() - self._last_activity >= self.cfg["hide_delay"]:
                self._hide_controls()
        elif not self.isFullScreen() and self._controls_hidden:
            self._show_controls()

    # --------------------------------------------- theme / subtitle style
    def _ic(self, kind, size=24):
        return make_icon(kind, self.pal["text"], size)

    def _update_play_icon(self):
        if not self._loaded:
            self.play_btn.setIcon(self._ic("play"))
        elif self._eof:
            self.play_btn.setIcon(self._ic("replay"))
        elif self._paused:
            self.play_btn.setIcon(self._ic("play"))
        else:
            self.play_btn.setIcon(self._ic("pause"))

    def _refresh_icons(self):
        self.logo.setPixmap(make_app_pixmap(18))
        self._update_play_icon()
        self.stop_btn.setIcon(self._ic("stop"))
        self.prev_btn.setIcon(self._ic("prev"))
        self.next_btn.setIcon(self._ic("next"))
        try:
            muted = bool(self.mpv.mute)
            vol = int(self.mpv.volume)
        except Exception:
            muted, vol = False, 100
        self.volume_btn.setIcon(self._ic("muted" if (muted or vol == 0) else "volume"))
        self.open_btn.setIcon(self._ic("open"))
        self.cc_btn.setIcon(self._ic("cc"))
        self.settings_btn.setIcon(self._ic("settings"))
        self.min_btn.setIcon(self._ic("min"))
        self.max_btn.setIcon(self._ic("restore" if self.isMaximized() else "max"))
        self.close_btn.setIcon(self._ic("close"))
        self.playlist_btn.setIcon(self._ic("list"))
        self._update_fs_icon()

    def _restyle_labels(self):
        p = self.pal
        self.brand.setStyleSheet(f"color:{p['text']};font-weight:700;font-size:14px;")
        self.filename_label.setStyleSheet(f"color:{p['dim']};font-size:12px;")
        self.buffer_label.setStyleSheet(f"color:{p['dim']};font-size:11px;")
        self.time_label.setStyleSheet(f"color:{p['text']};font-size:12px;")
        self.volume_label.setStyleSheet(f"color:{p['text']};font-size:12px;min-width:40px;")
        self.drop_banner.setStyleSheet(
            f"color:{p['accent']};font-weight:600;font-size:13px;padding:3px 10px;"
            f"border:1px solid {p['accent']};border-radius:4px;")
        self.url_title.setStyleSheet(f"color:{p['red']};font-size:20px;font-weight:700;")
        self.url_hint.setStyleSheet(f"color:{p['dim']};font-size:12px;")

    def _apply_theme(self):
        self.pal = PALETTES.get(self.theme, PALETTES["dark"])
        self.setStyleSheet(self._qss(self.pal))
        self.seek_bar.set_palette(self.pal)
        self.top_bar.set_palette(self.pal)
        self.controls_bar.set_palette(self.pal)
        self._refresh_icons()
        self._restyle_labels()
        self.playlist_title.setStyleSheet(
            f"color:{self.pal['dim']};font-weight:700;font-size:13px;")
        self._apply_osd_style()
        self._raise_overlays()

    def _resolve_weight_font(self, base, weight):
        if not base:
            return None
        variants = {
            "medium": ["Medium", "Semibold", "SemiBold", "Semi Bold"],
            "semibold": ["Semibold", "SemiBold", "Semi Bold", "Medium", "Bold"],
        }
        try:
            families = QFontDatabase().families()
            families_lower = {f.lower() for f in families}
        except Exception:
            return None
        for v in variants.get(weight, []):
            cand = f"{base} {v}".lower()
            if cand in families_lower:
                for f in families:
                    if f.lower() == cand:
                        return f
        return None

    def _apply_sub_style(self):
        if self.mpv is None:
            return
        try:
            base = self.cfg.get("sub_font", "")
            weight = self.cfg.get("sub_weight", "regular")

            if weight == "bold":
                bold = True
                font_name = base or None
            elif weight in ("medium", "semibold"):
                variant = self._resolve_weight_font(base, weight)
                if variant:
                    bold = False
                    font_name = variant
                elif weight == "semibold":
                    bold = True
                    font_name = base or None
                else:
                    bold = False
                    font_name = base or None
            else:
                bold = False
                font_name = base or None

            if font_name:
                self.mpv.sub_font = font_name
            self.mpv.sub_scale = self.cfg["sub_scale"] / 100.0
            self.mpv.sub_color = self.cfg["sub_color"]
            self.mpv.sub_bold = bool(bold)
            self.mpv.sub_border_size = float(self.cfg["sub_border_size"])
            self.mpv.sub_shadow_offset = float(self.cfg["sub_shadow_offset"])
            self.mpv.sub_outline_color = "#000000"

            if self.cfg["sub_back_enabled"]:
                c = QColor(self.cfg["sub_back_color"])
                a = int(round(self.cfg["sub_back_opacity"] / 100.0 * 255))
                self.mpv.sub_back_color = f"#{a:02X}{c.red():02X}{c.green():02X}{c.blue():02X}"
                self.mpv.sub_border_style = "background-box"
            else:
                self.mpv.sub_back_color = ("#C0000000"
                                           if float(self.cfg["sub_shadow_offset"]) > 0.01
                                           else "#00000000")
                self.mpv.sub_border_style = "outline-and-shadow"
        except Exception:
            pass
        self._update_sub_pos()

    # ----------------------------------------------------------- settings
    def open_settings(self):
        fonts = set(QFontDatabase().families())
        try:
            if self.mpv is not None:
                for f in (self.mpv.fonts or []):
                    fonts.add(f)
        except Exception:
            pass
        fonts = sorted(fonts)
        dlg = SettingsDialog(self, fonts, self.cfg)
        dlg.applied.connect(self._apply_cfg)
        if dlg.exec_() == QDialog.Accepted:
            self._apply_cfg(dlg.values())

    def _apply_cfg(self, cfg):
        self.cfg = cfg
        for k, v in self.cfg.items():
            self.settings.setValue(k, v)
        self.theme = self.cfg.get("theme", "dark")
        self._apply_theme()
        self._apply_sub_style()
        self._apply_osd_style()
        self._mark_activity()

    # -------------------------------------------------------- drag & drop
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
            self.drop_banner.show()

    def dragLeaveEvent(self, e):
        self.drop_banner.hide()

    def dropEvent(self, e):
        self.drop_banner.hide()
        urls = e.mimeData().urls()
        videos = []
        subs = []
        for u in urls:
            p = u.toLocalFile() or u.toString()
            ext = os.path.splitext(u.path() if u.isLocalFile() else u.toString().split("?")[0])[1].lower()
            if ext in SUB_EXTS:
                subs.append(p)
            else:
                videos.append(p)
        if videos:
            if len(videos) == 1:
                self.load(videos[0])
            else:
                self.playlist = list(videos)
                self._pl_index = -1
                self._load_index(0)
            for s in subs:
                self._add_subtitle_path(s)
        elif subs:
            for s in subs:
                self._add_subtitle_path(s)

    # ----------------------------------------------------------- keyboard
    def keyPressEvent(self, e):
        k = e.key()
        if k in (Qt.Key_Space, Qt.Key_K):
            self.toggle_pause()
        elif k == Qt.Key_Left:
            self.seek_relative(-self.cfg["seek_step"])
        elif k == Qt.Key_Right:
            self.seek_relative(self.cfg["seek_step"])
        elif k == Qt.Key_Up:
            self.change_volume(self.cfg["vol_step"])
        elif k == Qt.Key_Down:
            self.change_volume(-self.cfg["vol_step"])
        elif k == Qt.Key_J:
            self.seek_relative(-10)
        elif k == Qt.Key_L:
            self.seek_relative(10)
        elif k == Qt.Key_Comma:
            self._sub_sync(-0.10)
        elif k == Qt.Key_Period:
            self._sub_sync(0.10)
        elif k == Qt.Key_Slash:
            self._reset_sub_sync()
        elif k == Qt.Key_N:
            self._playlist_next()
        elif k == Qt.Key_P:
            self._playlist_prev()
        elif k == Qt.Key_F:
            self.toggle_fullscreen()
        elif k in (Qt.Key_Return, Qt.Key_Enter):
            self.toggle_fullscreen()
        elif k == Qt.Key_M:
            self.toggle_mute()
        elif k == Qt.Key_S:
            self.stop()
        elif k == Qt.Key_O and (e.modifiers() & Qt.ControlModifier):
            self.open_file()
        elif k == Qt.Key_Escape:
            if self.isFullScreen():
                self.showNormal()
                self._update_fs_icon()
                self._show_controls()
        else:
            super().keyPressEvent(e)

    def wheelEvent(self, e):
        if self.mpv is None:
            e.ignore()
            return
        d = e.angleDelta().y()
        if d > 0:
            self._on_wheel(1)
        elif d < 0:
            self._on_wheel(-1)
        e.accept()

    # ------------------------------------------------------------- helpers
    def _fmt(self, sec):
        if sec is None or sec < 0:
            return "0:00"
        sec = int(sec)
        h, m, s = sec // 3600, (sec % 3600) // 60, sec % 60
        if h:
            return f"{h}:{m:02d}:{s:02d}"
        return f"{m}:{s:02d}"

    def _display_name(self, url):
        try:
            if "://" in url:
                from urllib.parse import urlparse, unquote
                p = urlparse(url)
                name = unquote(os.path.basename(p.path)) or p.netloc
                return name
            return os.path.basename(url)
        except Exception:
            return url

    def _center(self):
        screen = QApplication.primaryScreen().availableGeometry()
        self.move(screen.center() - self.rect().center())

    def changeEvent(self, e):
        if e.type() == QEvent.WindowDeactivate:
            self._restore_edge_cursor()
            if self._cursor_blanked:
                QApplication.restoreOverrideCursor()
                self._cursor_blanked = False
                self._show_controls()
        super().changeEvent(e)

    def nativeEvent(self, eventType, message):
        # frameless window: enable edge/corner resizing via WM_NCHITTEST. The
        # native child windows answer HTTRANSPARENT (FramelessHostMixin), so
        # this handler is reached for every point of the window.
        if sys.platform == "win32" and not self.isMaximized() and not self.isFullScreen():
            msg = _win_msg(message)
            if msg is not None and msg.message == 0x0084:  # WM_NCHITTEST
                hit = _frameless_hittest(int(self.winId()))
                if hit:
                    return True, hit
        return super().nativeEvent(eventType, message)

    def _position_overlays(self):
        cw = self._central.width()
        ch = self._central.height()
        self.top_bar.setGeometry(0, 0, cw, self.TOP_H)
        self.controls_bar.setGeometry(0, ch - self.CTRL_H, cw, self.CTRL_H)
        self.seek_bar.setGeometry(0, ch - self.CTRL_H - self.SEEK_H, cw, self.SEEK_H)
        pw, ph = self.url_panel.width(), self.url_panel.height()
        self.url_panel.move((cw - pw) // 2, (ch - ph) // 2)

        plw = self.playlist_panel.width()
        self.playlist_panel.setGeometry(
            cw - plw, self.TOP_H,
            plw, ch - self.TOP_H - self.CTRL_H - self.SEEK_H)
        self._raise_overlays()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.mpv is not None and self.mpv_widget is not None:
            try:
                self.mpv.wid = int(self.mpv_widget.winId())
            except Exception:
                pass
        if hasattr(self, "_central"):
            self._position_overlays()

    def closeEvent(self, e):
        self.activity_timer.stop()
        if self._cursor_blanked:
            QApplication.restoreOverrideCursor()
            self._cursor_blanked = False
        # remember window state / volume / speed
        try:
            if not self.isFullScreen() and not self.isMaximized():
                self.settings.setValue("geometry", self.saveGeometry())
            self.settings.setValue("maximized", self.isMaximized())
            if self.mpv is not None:
                self.settings.setValue("volume", int(self.mpv.volume or 100))
                self.settings.setValue("speed", float(self.mpv.speed or 1.0))
        except Exception:
            pass
        try:
            self.settings.sync()
        except Exception:
            pass
        if self.mpv is not None:
            try:
                self.mpv.terminate()
            except Exception:
                pass
        if self._conf_path:
            try:
                os.remove(self._conf_path)
            except Exception:
                pass
        e.accept()


def main():
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setWindowIcon(make_app_icon())
    win = PlayerWindow()
    win.show()
    win.setFocus()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
