"""Etiqueta automáticamente el enemigo fijado: las dos flechas verdes a sus lados + el rombo naranja.

Uso: python scripts/autolabel.py data/raw/<sesion> [salida]
Escribe imágenes y labels YOLO (clase 0 = enemigo) en <salida>/images y <salida>/labels, y una hoja
de revisión con las cajas dibujadas. Solo etiqueta lo claro; los enemigos sin marca de objetivo no se tocan.
"""
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent


def find_arrows(hsv) -> list[tuple[int, int]]:
    m = cv2.inRange(hsv, (30, 150, 150), (50, 255, 255))
    m[:60] = 0
    m[900:] = 0
    m[300:380, 1740:] = 0  # el "3600" del HUD es del mismo verde
    n, _, st, c = cv2.connectedComponentsWithStats(m)
    return [(int(c[i][0]), int(c[i][1])) for i in range(1, n) if 100 <= st[i, 4] <= 600
            and 10 <= st[i, 2] <= 30 and 10 <= st[i, 3] <= 30]


def find_target(frame):
    """(x, y, w, h) del enemigo fijado, o None."""
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    pts = find_arrows(hsv)
    pairs = [(a, b) for a in pts for b in pts if a[0] < b[0] and abs(a[1] - b[1]) <= 4 and 90 <= b[0] - a[0] <= 280]
    if len(pairs) != 1:
        return None
    (ax, ay), (bx, by) = pairs[0]
    cx, cy = (ax + bx) // 2, (ay + by) // 2
    # rombo naranja del objetivo fijado, alrededor del centro
    x0, y0 = max(cx - 80, 0), max(cy - 80, 0)
    roi = hsv[y0:cy + 80, x0:cx + 80]
    om = cv2.inRange(roi, (5, 170, 190), (22, 255, 255))
    ys, xs = np.nonzero(om)
    if len(xs) < 150:
        return None
    x1, x2, y1, y2 = xs.min() + x0, xs.max() + x0, ys.min() + y0, ys.max() + y0
    w, h = x2 - x1, y2 - y1
    if not (50 <= w <= 140 and 50 <= h <= 140 and 0.75 <= w / h <= 1.35):
        return None
    return x1, y1, w, h


def main() -> None:
    src = Path(sys.argv[1])
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "data" / "auto"
    (out / "images").mkdir(parents=True, exist_ok=True)
    (out / "labels").mkdir(parents=True, exist_ok=True)
    review, kept = [], 0
    for f in sorted(src.glob("*.jpg")):
        im = cv2.imread(str(f))
        box = find_target(im)
        if box is None:
            continue
        h, w = im.shape[:2]
        x, y, bw, bh = box
        name = f"{src.name}_{f.stem}"
        cv2.imwrite(str(out / "images" / f"{name}.jpg"), im)
        (out / "labels" / f"{name}.txt").write_text(
            f"0 {(x + bw / 2) / w:.6f} {(y + bh / 2) / h:.6f} {bw / w:.6f} {bh / h:.6f}\n")
        kept += 1
        if len(review) < 24 and kept % 8 == 1:
            t = im.copy()
            cv2.rectangle(t, (x, y), (x + bw, y + bh), (0, 255, 0), 3)
            review.append(cv2.resize(t, (480, 270)))
    print(f"{kept} cuadros etiquetados de {len(list(src.glob('*.jpg')))}")
    if review:
        rows = [np.hstack(review[i:i + 4] + [np.zeros_like(review[0])] * (4 - len(review[i:i + 4])))
                for i in range(0, len(review), 4)]
        cv2.imwrite(str(out / "review.jpg"), np.vstack(rows))


if __name__ == "__main__":
    main()
