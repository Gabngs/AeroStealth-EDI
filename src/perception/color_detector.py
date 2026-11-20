import cv2
import numpy as np

from .base import Detection


class ColorDetector:
    """Arranque rápido: detecta la marca del enemigo por rango de color HSV."""

    def __init__(self, cfg: dict):
        c = cfg["detector"]["color"]
        self.low = np.array(c["hsv_low"], dtype=np.uint8)
        self.high = np.array(c["hsv_high"], dtype=np.uint8)
        self.min_area = c.get("min_area", 150)
        self.kernel = np.ones((5, 5), np.uint8)

    def detect(self, frame, conf: float = 0.0) -> list[Detection]:
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, self.low, self.high)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, self.kernel)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        dets = []
        for c in contours:
            if cv2.contourArea(c) < self.min_area:
                continue
            x, y, w, h = cv2.boundingRect(c)
            dets.append(Detection(0, 1.0, x, y, x + w, y + h))
        return dets
