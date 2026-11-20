import json
import time
from pathlib import Path

import cv2
import numpy as np
import yaml

from .config import ROOT


class Dataset:
    """Sesiones de grabación (data/raw/<fecha_hora>/) y correcciones etiquetadas (data/labeled).

    Cada sesión contiene: frames <ms>.jpg, inputs.jsonl y meta.json. Los "ms" de los frames y de
    inputs.jsonl salen del mismo reloj (ms desde el inicio de la sesión), así que se pueden alinear.
    `data/` está en .gitignore.
    """

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.classes = cfg["classes"]
        self.q = cfg["record"].get("jpg_quality", 85)
        self.min_change = cfg["record"].get("min_change", 0.02)
        self.idle_fps = cfg["record"].get("idle_fps", 1)
        self._last_save = 0.0
        self.lab_img = ROOT / "data" / "labeled" / "images" / "train"
        self.lab_txt = ROOT / "data" / "labeled" / "labels" / "train"
        self.lab_img.mkdir(parents=True, exist_ok=True)
        self.lab_txt.mkdir(parents=True, exist_ok=True)
        self.labeled_count = len(list(self.lab_img.glob("*.jpg")))
        self.session = ""
        self.session_dir: Path | None = None
        self.raw_count = 0
        self.start_session()
        self._write_yaml()

    @property
    def yaml_path(self) -> Path:
        return ROOT / "data" / "labeled" / "data.yaml"

    def _write_yaml(self):
        data = {
            "path": str((ROOT / "data" / "labeled").resolve()),
            "train": "images/train",
            "val": "images/train",  # con pocas imágenes se valida sobre lo mismo; separar luego
            "names": {i: n for i, n in enumerate(self.classes)},
        }
        self.yaml_path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")

    # ---------- sesiones ----------
    def start_session(self) -> Path:
        self.session = time.strftime("%Y%m%d_%H%M%S")
        self.session_dir = ROOT / "data" / "raw" / self.session
        self.t0 = time.perf_counter()
        self.raw_count = 0
        self._prev = None
        self._meta_written = False
        return self.session_dir

    def elapsed_ms(self) -> int:
        return int((time.perf_counter() - self.t0) * 1000)

    def _write_meta(self, frame: np.ndarray):
        self.session_dir.mkdir(parents=True, exist_ok=True)
        meta = {
            "session": self.session,
            "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "frame_size": [frame.shape[1], frame.shape[0]],
            "capture": self.cfg.get("capture"),
            "record": self.cfg.get("record"),
            "classes": self.classes,
            "controls": self.cfg.get("controls"),
            "clock": "ms desde el inicio de la sesión (frames: nombre del .jpg; entradas: campo t)",
        }
        (self.session_dir / "meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        self._meta_written = True

    # ---------- capturas crudas ----------
    def save_raw(self, frame: np.ndarray) -> bool:
        now = time.perf_counter()
        if self.min_change > 0:
            small = cv2.cvtColor(cv2.resize(frame, (64, 36)), cv2.COLOR_BGR2GRAY).astype(np.float32)
            still = self._prev is not None and np.abs(small - self._prev).mean() / 255 < self.min_change
            # Quieto: se guarda más espaciado (idle_fps), pero nunca se deja de guardar.
            if still and now - self._last_save < 1 / max(self.idle_fps, 0.05):
                return False
            self._prev = small
        self._last_save = now
        if not self._meta_written:
            self._write_meta(frame)
        cv2.imwrite(str(self.session_dir / f"{self.elapsed_ms():09d}.jpg"), frame,
                    [cv2.IMWRITE_JPEG_QUALITY, self.q])
        self.raw_count += 1
        return True

    # ---------- correcciones ----------
    def save_labeled(self, frame: np.ndarray, boxes: list[dict]) -> str:
        """boxes: [{'cls': int, 'xyxy': [x1,y1,x2,y2]}]. Lista vacía = muestra negativa."""
        h, w = frame.shape[:2]
        stem = f"{time.strftime('%Y%m%d_%H%M%S')}_{int(time.time() * 1000) % 1000:03d}"
        cv2.imwrite(str(self.lab_img / f"{stem}.jpg"), frame, [cv2.IMWRITE_JPEG_QUALITY, 95])
        lines = []
        for b in boxes:
            x1, y1, x2, y2 = b["xyxy"]
            cx, cy = (x1 + x2) / 2 / w, (y1 + y2) / 2 / h
            bw, bh = abs(x2 - x1) / w, abs(y2 - y1) / h
            lines.append(f"{b['cls']} {cx:.6f} {cy:.6f} {bw:.6f} {bh:.6f}")
        (self.lab_txt / f"{stem}.txt").write_text("\n".join(lines), encoding="utf-8")
        self.labeled_count += 1
        return stem
