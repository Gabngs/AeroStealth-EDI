"""Ubica la mira del juego: anillo blanco con 4 puntas naranjas que forman un cuadrado de ~47 px."""
import cv2
import numpy as np

SIDE = 47.0          # separación entre puntas (a 1917 px de ancho de ventana)
TOL = 0.25           # tolerancia relativa de la forma
RING_R = (19.0, 33.0)    # radio del anillo blanco alrededor del centro (a 1917 px)
RING_MIN = 0.12         # fracción mínima de píxeles blancos en el anillo


def _masks(frame):
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    orange = ((hsv[..., 0] >= 8) & (hsv[..., 0] <= 26) & (hsv[..., 1] > 120) & (hsv[..., 2] > 150)).astype(np.uint8)
    white = ((hsv[..., 1] < 80) & (hsv[..., 2] > 190)).astype(np.uint8)
    h, w = orange.shape
    orange[: int(0.045 * h)] = 0                          # barra de título de la ventana
    orange[int(0.86 * h):] = 0                            # barra de habilidades
    orange[int(0.72 * h):, : int(0.22 * w)] = 0           # chat (texto rojo/naranja)
    return orange, white


def _spikes(orange) -> np.ndarray:
    n, _, st, c = cv2.connectedComponentsWithStats(orange)
    idx = [i for i in range(1, n) if 15 <= st[i, 4] <= 400 and max(st[i, 2], st[i, 3]) <= 40]
    idx = sorted(idx, key=lambda i: -st[i, 4])[:400]
    return c[idx] if idx else np.zeros((0, 2))


def _ring_fraction(white, cx: float, cy: float, scale: float) -> float:
    r0, r1 = RING_R[0] * scale, RING_R[1] * scale
    x0, y0 = int(cx - r1) - 1, int(cy - r1) - 1
    x1, y1 = int(cx + r1) + 2, int(cy + r1) + 2
    if x0 < 0 or y0 < 0 or x1 > white.shape[1] or y1 > white.shape[0]:
        return 0.0
    yy, xx = np.mgrid[y0:y1, x0:x1]
    d = np.hypot(xx - cx, yy - cy)
    ann = (d >= r0) & (d <= r1)
    return float(white[y0:y1, x0:x1][ann].mean())


def find_reticle(frame):
    """(x, y, puntas) del centro de la mira, o None. Exige 3-4 puntas en cuadrado Y el anillo blanco alrededor,
    así no se confunde con texto naranja del HUD."""
    scale = frame.shape[1] / 1917.0
    orange, white = _masks(frame)
    pts = _spikes(orange)
    if len(pts) < 3:
        return None
    side, tol = SIDE * scale, SIDE * scale * TOL
    ideal = side * 0.7071                                  # distancia de cada punta al centro
    d = np.linalg.norm(pts[:, None, :] - pts[None, :, :], axis=2)
    ii, jj = np.nonzero(np.triu(np.abs(d - side * 1.4142) < tol * 1.5, 1))   # pares en diagonal
    best = None
    for i, j in zip(ii, jj):
        c = (pts[i] + pts[j]) / 2
        r = np.linalg.norm(pts - c, axis=1)
        on = np.abs(r - ideal) < tol
        k = int(on.sum())
        if k < 3:
            continue
        centre = pts[on].mean(0) if k >= 4 else c
        ring = _ring_fraction(white, centre[0], centre[1], scale)
        if ring < RING_MIN:
            continue
        score = ring * min(k, 4)
        if best is None or score > best[0]:
            best = (score, centre, min(k, 4))
    if best is None:
        return None
    return float(best[1][0]), float(best[1][1]), best[2]
