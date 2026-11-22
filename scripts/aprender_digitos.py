"""Aprende los dígitos del contador de munición a partir de capturas con valores conocidos.
Uso: py scripts/aprender_digitos.py captura.png:01936:07616 otra.png:04630:07620 ...  -> assets/digits.npz"""
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.hud import _ammo_cells  # noqa: E402

acc: dict[str, list] = {}
for arg in sys.argv[1:]:
    path, *vals = arg.rsplit(":", 2)
    frame = cv2.imread(path)
    cells = _ammo_cells(frame)
    if cells is None:
        sys.exit(f"{path}: no encuentro los contadores")
    for five, val in zip(cells, vals):
        for c, ch in zip(five, val):
            acc.setdefault(ch, []).append(c)
out = {ch: np.mean(v, axis=0) for ch, v in acc.items()}
np.savez(Path(__file__).resolve().parent.parent / "assets" / "digits.npz", **out)
print("dígitos aprendidos:", "".join(sorted(out)), "| faltan:", "".join(sorted(set("0123456789") - set(out))))
