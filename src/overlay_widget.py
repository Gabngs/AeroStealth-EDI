"""Capa transparente sobre el juego: cajas del detector, mira, objetivo elegido y estado del bot.
No roba el foco ni captura clics."""
import ctypes
from ctypes import wintypes

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QWidget

from .capture import find_hwnd

user32 = ctypes.windll.user32
dwmapi = ctypes.windll.dwmapi


def visible_rect(hwnd) -> tuple[int, int, int, int]:
    """Rectángulo visible de la ventana (sin los bordes invisibles de Windows), en píxeles físicos."""
    r = wintypes.RECT()
    if dwmapi.DwmGetWindowAttribute(hwnd, 9, ctypes.byref(r), ctypes.sizeof(r)) != 0:
        user32.GetWindowRect(hwnd, ctypes.byref(r))
    return r.left, r.top, r.right - r.left, r.bottom - r.top


class BotOverlay(QWidget):
    def __init__(self, cfg: dict):
        super().__init__()
        self.cfg = cfg
        self.s: dict = {"boxes": [], "fw": 1, "fh": 1, "fps": 0.0, "active": False, "msg": "Iniciando…",
                        "target": None, "reticle": None}
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
                            | Qt.WindowTransparentForInput | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.follow_game)
        self.timer.start(100)

    def follow_game(self) -> None:
        hwnd = find_hwnd(self.cfg["capture"])
        if not hwnd or user32.IsIconic(hwnd):
            self.hide()
            return
        x, y, w, h = visible_rect(hwnd)
        dpr = self.screen().devicePixelRatio()
        self.setGeometry(round(x / dpr), round(y / dpr), round(w / dpr), round(h / dpr))
        if not self.isVisible():
            self.show()

    def set_state(self, state: dict) -> None:
        self.s = state
        self.update()

    def paintEvent(self, _) -> None:
        s = self.s
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        sx, sy = self.width() / max(s["fw"], 1), self.height() / max(s["fh"], 1)
        p.setFont(QFont("Segoe UI", 10, QFont.Bold))
        tgt = s.get("target")
        for x1, y1, x2, y2, conf in s["boxes"]:
            chosen = tgt is not None and abs((x1 + x2) / 2 - tgt[0]) < 2 and abs((y1 + y2) / 2 - tgt[1]) < 2
            col = QColor(255, 60, 220) if chosen else (QColor(0, 255, 120) if conf >= 0.6 else QColor(255, 210, 0))
            p.setPen(QPen(col, 4 if chosen else 2))
            p.setBrush(Qt.NoBrush)
            p.drawRect(QRectF(x1 * sx, y1 * sy, (x2 - x1) * sx, (y2 - y1) * sy))
            p.setPen(col)
            p.drawText(QRectF(x1 * sx, y1 * sy - 22, 200, 20), ("OBJETIVO " if chosen else "") + f"{conf:.2f}")
        ret = s.get("reticle")
        if ret:
            p.setPen(QPen(QColor(0, 220, 255), 2))
            c = QPointF(ret[0] * sx, ret[1] * sy)
            p.drawEllipse(c, 34, 34)
            if tgt and s["active"]:
                p.drawLine(c, QPointF(tgt[0] * sx, tgt[1] * sy))
        # cartel de estado, arriba al centro
        on = s["active"]
        w, x0 = 380, (self.width() - 380) / 2
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 150, 70, 210) if on else QColor(150, 40, 40, 210))
        p.drawRoundedRect(QRectF(x0, 100, w, 52), 10, 10)
        p.setPen(QColor(255, 255, 255))
        p.setFont(QFont("Segoe UI", 12, QFont.Bold))
        p.drawText(QRectF(x0, 102, w, 26), Qt.AlignCenter, "● BOT ACTIVO" if on else "■ BOT DETENIDO  (pulsa el botón)")
        p.setFont(QFont("Segoe UI", 9))
        p.drawText(QRectF(x0, 128, w, 22), Qt.AlignCenter, f"{s['msg']}   ·   {s['fps']:.0f} fps")
