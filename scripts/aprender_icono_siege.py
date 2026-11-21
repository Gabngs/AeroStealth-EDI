"""Aprende cómo se ve el icono de "Siege activo" (arriba a la izquierda, junto a la munición).
Alterna Siege con la tecla 1, compara los cuadros y guarda lo que aparece en assets/siege_icon.png. Requiere administrador."""
import ctypes
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
ctypes.windll.shcore.SetProcessDpiAwareness(2)

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from src.capture import ScreenCapture, find_hwnd  # noqa: E402
from src.config import ROOT, load_config  # noqa: E402
from src.control import Controls  # noqa: E402

u = ctypes.windll.user32


def main() -> None:
    cfg = load_config()
    hwnd = find_hwnd(cfg["capture"])
    u.ShowWindow(hwnd, 9)
    u.SetForegroundWindow(hwnd)
    time.sleep(0.8)
    cap, ctl = ScreenCapture(cfg["capture"]), Controls()

    def grab():
        for _ in range(60):
            try:
                return cap.grab()
            except RuntimeError:
                time.sleep(0.05)

    a = grab()
    ctl.tap("1", 0.08)
    time.sleep(1.4)
    b = grab()
    ctl.tap("1", 0.08)                                   # lo deja como estaba
    time.sleep(1.2)
    c = grab()
    cap.close()
    h, w = a.shape[:2]
    y1, y2, x1, x2 = 38, int(0.10 * h), 240, int(0.30 * w)           # franja de iconos de estado
    d = np.abs(a[y1:y2, x1:x2].astype(int) - b[y1:y2, x1:x2].astype(int)).sum(2)
    d2 = np.abs(c[y1:y2, x1:x2].astype(int) - b[y1:y2, x1:x2].astype(int)).sum(2)
    d3 = np.abs(a[y1:y2, x1:x2].astype(int) - c[y1:y2, x1:x2].astype(int)).sum(2)
    if (d3 > 90).mean() > 0.02:                                       # el antes y el después (ambos sin Siege) no coinciden: hubo movimiento
        print("La pantalla se movió durante la prueba (¿cámara o mouse en uso?). Repite sin tocar nada.")
        return
    mask = ((d > 90) & (d2 > 90) & (d3 < 40)).astype(np.uint8)       # cambia al activar y vuelve al apagar
    n, _, st, _ = cv2.connectedComponentsWithStats(cv2.dilate(mask, np.ones((3, 3), np.uint8)))
    if n < 2:
        print("No encontré ningún cambio en la franja: ¿Siege se activó? Revisa que la tecla 1 sea Siege.")
        return
    i = 1 + int(np.argmax(st[1:, 4]))
    if st[i, 2] < 10 or st[i, 3] < 10 or st[i, 4] < 60:
        print("Lo que cambió es demasiado pequeño para ser un icono: no lo guardo.")
        return
    bx, by, bw, bh = st[i, 0] + x1, st[i, 1] + y1, st[i, 2], st[i, 3]
    pad = 2
    sat = lambda f: cv2.cvtColor(f[by:by + bh, bx:bx + bw], cv2.COLOR_BGR2HSV)[..., 1].mean()   # noqa: E731
    on = b if sat(b) >= sat(a) else a
    icon = on[max(by - pad, 0):by + bh + pad, max(bx - pad, 0):bx + bw + pad]
    (ROOT / "assets").mkdir(exist_ok=True)
    cv2.imwrite(str(ROOT / "assets" / "siege_icon.png"), icon)
    print(f"Icono guardado: assets/siege_icon.png | posición en el cuadro x={bx}, y={by}, tamaño {bw}x{bh}", flush=True)


if __name__ == "__main__":
    main()
