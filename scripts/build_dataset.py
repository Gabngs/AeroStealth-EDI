"""Arma data/auto2: etiquetas a mano (data/propuestas) + propuestas del modelo provisional + objetivo fijado.
Uso: python scripts/build_dataset.py
Los cuadros de la sesión de calabazas (212050) usan propuestas con conf >= 0.45; la sesión de vuelo (213018)
solo el objetivo fijado más propuestas con conf >= 0.6. Algunos cuadros sin nada se guardan como negativos."""
import glob
import os
import random
import shutil
import sys
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parent))
from autolabel import find_target  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "auto2"
random.seed(1)


def iou(a, b) -> float:
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    ua = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / ua if ua else 0.0


def read_labels(path: Path, w: int, h: int):
    out = []
    for ln in path.read_text().splitlines():
        _, x, y, bw, bh = map(float, ln.split())
        out.append(((x - bw / 2) * w, (y - bh / 2) * h, (x + bw / 2) * w, (y + bh / 2) * h))
    return out


def main() -> None:
    from ultralytics import YOLO
    model = YOLO(str(ROOT / "runs" / "boot" / "weights" / "best.pt"))
    if OUT.exists():
        shutil.rmtree(OUT)
    (OUT / "images").mkdir(parents=True)
    (OUT / "labels").mkdir(parents=True)
    stats = {"manual": 0, "modelo": 0, "fijado": 0, "negativos": 0}
    for sess, min_conf in (("20261120_212050", 0.45), ("20261120_213018", 0.6)):
        for f in sorted(glob.glob(str(ROOT / "data" / "raw" / sess / "*.jpg"))):
            stem = os.path.basename(f)[:-4]
            name = f"{sess}_{stem}"
            im = cv2.imread(f)
            h, w = im.shape[:2]
            manual = ROOT / "data" / "propuestas" / "labels" / f"{name}.txt"
            clean = False                                 # cuadro sin ninguna propuesta, ni dudosa
            if manual.exists():
                boxes = read_labels(manual, w, h)
                stats["manual"] += 1
            else:
                r = model.predict(im, conf=0.15, imgsz=960, max_det=10, verbose=False)[0]
                cand = [(*b.xyxy[0].tolist(), float(b.conf[0])) for b in r.boxes]
                boxes = [c[:4] for c in cand if c[4] >= min_conf]
                stats["modelo"] += len(boxes)
                if cand and not boxes:
                    continue                              # solo propuestas dudosas: no se usa
                clean = not cand
            lock = find_target(im)
            if lock:
                lb = (lock[0], lock[1], lock[0] + lock[2], lock[1] + lock[3])
                if all(iou(lb, b) < 0.3 for b in boxes):
                    boxes.append(lb)
                    stats["fijado"] += 1
            if not boxes:
                if not (clean and random.random() < 0.25):
                    continue
                stats["negativos"] += 1                   # cuadro limpio guardado como negativo
            cv2.imwrite(str(OUT / "images" / f"{name}.jpg"), im)
            (OUT / "labels" / f"{name}.txt").write_text("".join(
                f"0 {(b[0] + b[2]) / 2 / w:.6f} {(b[1] + b[3]) / 2 / h:.6f} {(b[2] - b[0]) / w:.6f} {(b[3] - b[1]) / h:.6f}\n"
                for b in boxes))
    n = len(list((OUT / "images").glob("*.jpg")))
    print(f"{n} cuadros | {stats}")


if __name__ == "__main__":
    main()
