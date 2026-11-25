"""Aprende las plantillas de dígitos del número de distancia que sale bajo el objetivo fijado.
Uso: python scripts/aprender_distancia.py <captura.png> <numero> [x y]
  x y = centro de las flechas verdes (si se omite se detecta). Se pueden repetir capturas con otros números
  hasta tener los dígitos 0-9; se guardan en assets/dist_digits.npz (promediando si ya existían)."""
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.hud import _dist_cells, green_arrows  # noqa: E402

img, num = sys.argv[1], sys.argv[2]
frame = cv2.imread(img)
anchor = (float(sys.argv[3]), float(sys.argv[4])) if len(sys.argv) >= 5 else green_arrows(frame)
if anchor is None:
    sys.exit("No se detectaron las flechas verdes: pasa x y a mano.")
cells = _dist_cells(frame, anchor)
if len(cells) != len(num):
    sys.exit(f"Se segmentaron {len(cells)} dígitos y esperaba {len(num)} ({num}). Revisa la captura.")
p = Path(__file__).resolve().parent.parent / "assets" / "dist_digits.npz"
lib = dict(np.load(p)) if p.exists() else {}
for d, c in zip(num, cells):
    lib[d] = (lib[d] + c) / 2 if d in lib else c
np.savez(p, **lib)
print(f"Guardado. Dígitos conocidos: {''.join(sorted(lib))}")
