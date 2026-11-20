import time

from PySide6.QtCore import QThread, Signal

from .capture import ScreenCapture
from .perception.color_detector import ColorDetector
from .perception.yolo_detector import YoloDetector


class CaptureWorker(QThread):
    """Captura continua + detección + grabación automática del dataset."""

    result = Signal(object, object, object, float)  # frame BGR, detecciones, imágenes de capas, fps
    message = Signal(str)

    def __init__(self, cfg: dict, dataset):
        super().__init__()
        self.cfg = cfg
        self.dataset = dataset
        self.recording = False
        self.record_fps = cfg["record"]["fps"]
        self.kind = cfg["detector"]["kind"]
        self.conf = cfg["detector"]["conf"]
        self._running = True
        self.color = ColorDetector(cfg)
        self.yolo = YoloDetector(cfg)
        self._last_warn = 0.0

    def stop(self):
        self._running = False
        self.wait(2000)

    def _detector(self):
        if self.kind == "color":
            return self.color
        if self.kind == "yolo":
            if not self.yolo.available():
                self.kind = "none"
                self.message.emit("No hay models/best.pt todavía: entrena primero con tus correcciones.")
                return None
            return self.yolo
        return None

    def _warn(self, text: str):
        now = time.time()
        if now - self._last_warn > 5:
            self._last_warn = now
            self.message.emit(text)

    def run(self):
        cap = ScreenCapture(self.cfg["capture"])
        period = 1 / self.cfg["capture"]["view_fps"]
        last_rec, fps = 0.0, 0.0
        while self._running:
            t0 = time.perf_counter()
            try:
                frame = cap.grab()
            except Exception as e:  # noqa: BLE001
                self._warn(f"Error de captura: {e}")
                self.msleep(500)
                continue

            black = frame.mean() < 2
            if black:
                self._warn("Captura negra: ¿pantalla completa exclusiva o bloqueo de pantalla?")
            elif self.recording and t0 - last_rec >= 1 / max(self.record_fps, 1):
                last_rec = t0
                self.dataset.save_raw(frame)

            dets, layers = [], None
            try:
                det = self._detector()
                if det is not None and not black:
                    dets = det.detect(frame, self.conf)
                    if det is self.yolo:
                        layers = self.yolo.layer_images()
            except Exception as e:  # noqa: BLE001
                self.kind = "none"
                self.message.emit(f"Detector desactivado por error: {e}")

            dt = time.perf_counter() - t0
            fps = 0.9 * fps + 0.1 / max(dt, 1e-3) if fps else 1 / max(dt, 1e-3)
            self.result.emit(frame, dets, layers, fps)
            self.msleep(max(0, int((period - dt) * 1000)))
        cap.close()
