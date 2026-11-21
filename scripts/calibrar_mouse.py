"""Mide cómo reacciona la cámara del juego al cursor (necesita administrador: el juego está elevado).
Mueve el cursor a posiciones desplazadas del centro y mide cuánto se desplaza la escena (correlación de fase).
Uso: python scripts/calibrar_mouse.py"""
import ctypes
import math
import sys
import time
from ctypes import wintypes
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
ctypes.windll.shcore.SetProcessDpiAwareness(2)

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from src.capture import ScreenCapture, find_hwnd  # noqa: E402
from src.config import load_config  # noqa: E402
from src.control import Controls  # noqa: E402
from src.overlay_widget import visible_rect  # noqa: E402

u = ctypes.windll.user32
pt = wintypes.POINT()


def cursor() -> tuple[int, int]:
    u.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y


def glide(dest, secs=0.25):
    x0, y0 = cursor()
    n = max(int(secs / 0.008), 4)
    for i in range(1, n + 1):
        t = i / n
        u.SetCursorPos(round(x0 + (dest[0] - x0) * t), round(y0 + (dest[1] - y0) * t))
        time.sleep(0.008)


def main() -> None:
    cfg = load_config()
    hwnd = find_hwnd(cfg["capture"])
    u.ShowWindow(hwnd, 9)
    u.SetForegroundWindow(hwnd)
    time.sleep(0.8)
    x, y, w, h = visible_rect(hwnd)
    cx, cy = x + w // 2, y + h // 2
    cap = ScreenCapture(cfg["capture"])

    def grab():
        for _ in range(60):
            try:
                return cap.grab()
            except RuntimeError:
                time.sleep(0.05)

    def gray(f):
        return cv2.cvtColor(f[150:650, 300:1600], cv2.COLOR_BGR2GRAY).astype(np.float32)

    original = cursor()
    siege = "--siege" in sys.argv
    ctl = Controls()
    if siege:                                   # activa Siege Mode (tecla 1) antes de medir
        ctl.tap(cfg["controls"].get("siege_key", "1"), 0.08)
        time.sleep(1.0)
        print("Siege Mode activado (tecla 1)", flush=True)
    print(f"ventana {w}x{h} | centro ({cx},{cy}) | cursor inicial {original}", flush=True)
    glide((cx, cy))
    time.sleep(0.4)
    results = []
    plan = [("centro (referencia)", (0, 0), 1.0), ("derecha +250", (250, 0), 1.5), ("centro", (0, 0), 1.0),
            ("izquierda -250", (-250, 0), 1.5), ("centro", (0, 0), 1.0), ("abajo +150", (0, 150), 1.5),
            ("centro", (0, 0), 1.0), ("arriba -150", (0, -150), 1.5), ("centro", (0, 0), 1.0)]
    prev = gray(grab())
    try:
        for name, (dx, dy), hold in plan:
            glide((cx + dx, cy + dy))
            shifts = []
            t_end = time.time() + hold
            while time.time() < t_end:
                time.sleep(0.1)
                g = gray(grab())
                (sx, sy), _ = cv2.phaseCorrelate(prev, g)
                prev = g
                shifts.append((sx, sy))
            c = cursor()
            mx, my = np.mean([s[0] for s in shifts]), np.mean([s[1] for s in shifts])
            tail = shifts[-3:]
            print(f"{name:22} cursor en ({c[0]-cx:+d},{c[1]-cy:+d}) | giro medio de la escena por 0.1 s: "
                  f"({mx:+.1f},{my:+.1f}) px | últimos: " + " ".join(f"({a:+.0f},{b:+.0f})" for a, b in tail), flush=True)
            results.append((name, mx, my))
    finally:
        glide(original)
        if siege:                               # lo deja como estaba: Siege desactivado
            ctl.tap(cfg["controls"].get("siege_key", "1"), 0.08)
            print("Siege Mode desactivado (tecla 1)", flush=True)
        cap.close()
    print("fin. Cursor devuelto a", cursor(), flush=True)
    print("\nINTERPRETACIÓN: si con el cursor desplazado el giro se mantiene (≠0) varias muestras seguidas, la cámara "
          "gira mientras el cursor esté fuera del centro (control por velocidad). Si el giro solo aparece al moverlo y "
          "luego vuelve a ~0, es control por posición.", flush=True)


if __name__ == "__main__":
    main()
