"""Detecta la ventana "Verificación anti-AFK". El bot solo se detiene y avisa: no la resuelve."""
import cv2
import numpy as np

from .config import ROOT

_T = None


def afk_dialog_visible(frame, threshold: float = 0.7) -> bool:
    """Título amarillo "Verificación anti-AFK" + el recuadro blanco del código justo debajo."""
    global _T
    if _T is None:
        _T = cv2.imread(str(ROOT / "assets" / "afk_title.png"))
    h, w = frame.shape[:2]
    x0, y0 = int(w * 0.5), int(h * 0.3)           # la ventana sale abajo a la derecha
    roi = frame[y0:, x0:]
    base = w / 1917.0
    for s in (0.9, 1.0, 1.1):
        k = base * s
        t = cv2.resize(_T, None, fx=k, fy=k, interpolation=cv2.INTER_AREA)
        if t.shape[0] >= roi.shape[0] or t.shape[1] >= roi.shape[1]:
            continue
        res = cv2.matchTemplate(roi, t, cv2.TM_CCOEFF_NORMED)
        for _ in range(3):                         # los mejores candidatos
            _, mx, _, loc = cv2.minMaxLoc(res)
            if mx < threshold:
                break
            x, y = x0 + loc[0], y0 + loc[1]
            # recuadro del código: ~285x55 px, empieza ~20 px bajo el título (a escala 1917)
            box = frame[int(y + 22 * k):int(y + 75 * k), int(x):int(x + 285 * k)]
            if box.size:
                hsv = cv2.cvtColor(box, cv2.COLOR_BGR2HSV)
                white = ((hsv[..., 1] < 50) & (hsv[..., 2] > 190)).mean()
                if white > 0.5:
                    return True
            res[max(loc[1] - 5, 0):loc[1] + 5, max(loc[0] - 5, 0):loc[0] + 5] = -1
    return False
