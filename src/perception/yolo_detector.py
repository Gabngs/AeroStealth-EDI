import cv2
import numpy as np

from ..config import ROOT
from .base import Detection


class YoloDetector:
    """Detector neuronal (ultralytics). Guarda activaciones de capas con forward hooks."""

    def __init__(self, cfg: dict):
        d = cfg["detector"]
        self.weights = ROOT / d["yolo_weights"]
        self.layer_ids = d.get("layer_ids", [0, 2, 4, 6])
        self.max_det = d.get("max_det", 10)
        self.model = None
        self._acts: dict[int, np.ndarray] = {}

    def available(self) -> bool:
        return self.weights.exists()

    def reload(self):
        self.model = None
        self._acts = {}

    def _load(self):
        from ultralytics import YOLO

        self.model = YOLO(str(self.weights))
        seq = self.model.model.model
        for i in self.layer_ids:
            if i < len(seq):
                seq[i].register_forward_hook(self._hook(i))

    def _hook(self, i):
        def fn(_m, _inp, out):
            try:
                self._acts[i] = out[0].detach().float().cpu().numpy()
            except Exception:
                pass

        return fn

    def detect(self, frame, conf: float = 0.4) -> list[Detection]:
        if self.model is None:
            self._load()
        r = self.model.predict(frame, conf=conf, verbose=False, imgsz=640, max_det=self.max_det)[0]
        dets = []
        for b in r.boxes:
            x1, y1, x2, y2 = b.xyxy[0].tolist()
            dets.append(Detection(int(b.cls[0]), float(b.conf[0]), x1, y1, x2, y2))
        return dets

    def layer_images(self) -> list[np.ndarray]:
        """Una imagen RGB por capa: mosaico 4x2 de los 8 canales con más varianza."""
        out = []
        for i in sorted(self._acts):
            act = self._acts[i]
            if act.ndim != 3:
                continue
            order = np.argsort(act.reshape(act.shape[0], -1).var(axis=1))[::-1][:8]
            tiles = []
            for ch in order:
                a = act[ch]
                a = (a - a.min()) / (a.max() - a.min() + 1e-6)
                a = cv2.resize((a * 255).astype(np.uint8), (80, 80))
                tiles.append(cv2.applyColorMap(a, cv2.COLORMAP_VIRIDIS))
            while len(tiles) < 8:
                tiles.append(np.zeros((80, 80, 3), np.uint8))
            grid = np.vstack([np.hstack(tiles[:4]), np.hstack(tiles[4:])])
            out.append(cv2.cvtColor(grid, cv2.COLOR_BGR2RGB))
        return out
