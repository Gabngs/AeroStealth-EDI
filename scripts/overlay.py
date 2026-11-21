"""Capa transparente sobre la ventana del juego que dibuja lo que detecta el modelo.
No roba el foco ni captura clics: sigues jugando normal. Se detiene con el botón de parada (controls.killswitch).
Uso: python scripts/overlay.py [pesos] [confianza]"""
import ctypes
import sys
import time
from ctypes import wintypes
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QRectF, Qt, QThread, QTimer, Signal  # noqa: E402
from PySide6.QtGui import QColor, QFont, QPainter, QPen  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from src.capture import ScreenCapture, find_hwnd  # noqa: E402
from src.config import ROOT, load_config  # noqa: E402
from src.killswitch import start_killswitch  # noqa: E402

user32 = ctypes.windll.user32
dwmapi = ctypes.windll.dwmapi


def visible_rect(hwnd) -> tuple[int, int, int, int]:
    """Rectángulo visible de la ventana (sin los bordes invisibles de Windows), en píxeles físicos."""
    r = wintypes.RECT()
    if dwmapi.DwmGetWindowAttribute(hwnd, 9, ctypes.byref(r), ctypes.sizeof(r)) != 0:
        user32.GetWindowRect(hwnd, ctypes.byref(r))
    return r.left, r.top, r.right - r.left, r.bottom - r.top


class Detector(QThread):
    result = Signal(list, int, int, float)   # cajas, ancho, alto del cuadro, fps

    def __init__(self, cfg, weights, conf):
        super().__init__()
        self.cfg, self.weights, self.conf = cfg, weights, conf
        self.running = True

    def run(self):
        from ultralytics import YOLO
        model = YOLO(str(self.weights))
        cap = ScreenCapture(self.cfg["capture"])
        fps, last = 0.0, time.time()
        try:
            while self.running:
                try:
                    frame = cap.grab()
                except RuntimeError:
                    time.sleep(0.1)
                    continue
                r = model.predict(frame, conf=self.conf, imgsz=640, max_det=self.cfg["detector"].get("max_det", 10), verbose=False)[0]
                boxes = [(*map(float, b.xyxy[0].tolist()), float(b.conf[0]), int(b.cls[0])) for b in r.boxes]
                now = time.time()
                fps = 0.9 * fps + 0.1 / max(now - last, 1e-6)
                last = now
                self.result.emit(boxes, frame.shape[1], frame.shape[0], fps)
        finally:
            cap.close()


class Overlay(QWidget):
    def __init__(self, cfg, names):
        super().__init__()
        self.cfg, self.names = cfg, names
        self.boxes, self.fw, self.fh, self.fps = [], 1, 1, 0.0
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
                            | Qt.WindowTransparentForInput | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.follow_game)
        self.timer.start(100)

    def follow_game(self):
        hwnd = find_hwnd(self.cfg["capture"])
        if not hwnd or user32.IsIconic(hwnd):
            self.hide()
            return
        x, y, w, h = visible_rect(hwnd)
        dpr = self.screen().devicePixelRatio()
        self.setGeometry(round(x / dpr), round(y / dpr), round(w / dpr), round(h / dpr))
        if not self.isVisible():
            self.show()

    def update_boxes(self, boxes, fw, fh, fps):
        self.boxes, self.fw, self.fh, self.fps = boxes, fw, fh, fps
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        sx, sy = self.width() / self.fw, self.height() / self.fh
        p.setFont(QFont("Segoe UI", 10, QFont.Bold))
        for x1, y1, x2, y2, conf, cls in self.boxes:
            col = QColor(0, 255, 120) if conf >= 0.6 else QColor(255, 210, 0)
            p.setPen(QPen(col, 3))
            p.setBrush(Qt.NoBrush)
            p.drawRect(QRectF(x1 * sx, y1 * sy, (x2 - x1) * sx, (y2 - y1) * sy))
            p.setPen(col)
            p.drawText(QRectF(x1 * sx, y1 * sy - 22, 200, 20), f"{self.names.get(cls, cls)} {conf:.2f}")
        p.setPen(QColor(0, 255, 120))
        p.drawText(12, self.height() - 14, f"modelo: {len(self.boxes)} detecciones · {self.fps:.0f} fps")


def main() -> None:
    cfg = load_config()
    start_killswitch(cfg["controls"].get("killswitch", "xbutton2"))
    weights = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "models" / "best.pt"
    conf = float(sys.argv[2]) if len(sys.argv) > 2 else cfg["detector"]["conf"]
    app = QApplication(sys.argv)
    ov = Overlay(cfg, {0: "enemigo", 1: "drop"})
    th = Detector(cfg, weights, conf)
    th.result.connect(ov.update_boxes)
    th.start()
    app.aboutToQuit.connect(lambda: (setattr(th, "running", False), th.wait(2000)))
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
