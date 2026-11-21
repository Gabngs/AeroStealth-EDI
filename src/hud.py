"""Lectura del HUD del juego a partir de un cuadro: vida del objetivo y si hay un enemigo fijado.
Las posiciones son relativas al cuadro, así que sirven en ventana y a pantalla completa."""
import cv2
import numpy as np

# la barra de vida del objetivo está arriba y centrada; su altura cambia entre ventana (con barra de título)
# y pantalla completa, así que se busca en toda la franja superior
HP_AREA = (0.38, 0.0, 0.62, 0.11)   # x1, y1, x2, y2 relativos
FILL_V = (110, 175)                  # brillo del rojo de la vida que queda
EMPTY_V = (30, 90)                   # brillo del rojo oscuro de la vida perdida (los topes brillantes se ignoran)


def target_hp(frame) -> float | None:
    """Fracción de vida del objetivo (0-1), o None si no hay barra (nada fijado)."""
    h, w = frame.shape[:2]
    x1, y1, x2, y2 = HP_AREA
    roi = frame[int(h * y1):int(h * y2), int(w * x1):int(w * x2)]
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    red = ((hsv[..., 0] < 8) | (hsv[..., 0] > 172)) & (hsv[..., 1] > 150) & (hsv[..., 2] > 30)
    rows = red.sum(1) > roi.shape[1] * 0.5
    if not rows.any():
        return None
    # tramo de filas más largo = la barra (así no cuentan el texto ni los bordes)
    best, start, cur = (0, 0), None, 0
    for i, r in enumerate(list(rows) + [False]):
        if r and start is None:
            start = i
        if not r and start is not None:
            if i - start > best[1] - best[0]:
                best = (start, i)
            start = None
    a, b = best
    mid = slice(a + (b - a) // 4, b - (b - a) // 4 or b)
    v = np.median(hsv[mid, :, 2], axis=0)                  # brillo por columna
    ok = red[mid].mean(0) > 0.5
    fill = ok & (v >= FILL_V[0]) & (v <= FILL_V[1])
    empty = ok & (v >= EMPTY_V[0]) & (v <= EMPTY_V[1])
    n = fill.sum() + empty.sum()
    if n < roi.shape[1] * 0.4:
        return None
    return float(fill.sum() / n)


def locked(frame) -> bool:
    """Hay enemigo fijado si hay barra de vida arriba."""
    return target_hp(frame) is not None


def green_arrows(frame):
    """Centro (x, y) del enemigo fijado: el punto medio entre las dos flechas verdes ▶ ◀ de sus costados, o None."""
    h, w = frame.shape[:2]
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    m = cv2.inRange(hsv, (30, 150, 150), (50, 255, 255))
    m[: int(0.05 * h)] = 0
    m[int(0.88 * h):] = 0
    m[int(0.28 * h):int(0.40 * h), int(0.90 * w):] = 0           # el "3600" del HUD es del mismo verde
    n, _, st, c = cv2.connectedComponentsWithStats(m)
    k = w / 1917.0
    pts = [(c[i][0], c[i][1]) for i in range(1, n)
           if 100 * k * k <= st[i, 4] <= 600 * k * k and 10 * k <= st[i, 2] <= 30 * k and 10 * k <= st[i, 3] <= 30 * k]
    pairs = [(a, b) for a in pts for b in pts if a[0] < b[0] and abs(a[1] - b[1]) <= 4 * k and 90 * k <= b[0] - a[0] <= 280 * k]
    if len(pairs) != 1:
        return None
    (ax, ay), (bx, by) = pairs[0]
    return (ax + bx) / 2, (ay + by) / 2


AGGRO_DY = 100        # el enemigo que te marca está ~100 px (a 1917 de ancho) debajo de su cartel "▶▶ nombre ◀◀"


def _double(pts, a, k: float) -> bool:
    """Cada lado del cartel tiene DOS triángulos rojos juntos (▶▶ / ◀◀): hay otro al lado, a la misma altura."""
    return any(p is not a and abs(p[1] - a[1]) <= 4 * k and 6 * k <= abs(p[0] - a[0]) <= 30 * k for p in pts)


def red_arrows(frame) -> list[tuple[float, float]]:
    """Posiciones (x, y) de los enemigos que te están marcando: cartel con flechas rojas ▶▶ nombre ◀◀,
    y el enemigo ~100 px debajo del texto. Lista vacía si nadie te marca."""
    h, w = frame.shape[:2]
    k = w / 1917.0
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    m = (((hsv[..., 0] < 6) | (hsv[..., 0] > 174)) & (hsv[..., 1] > 200) & (hsv[..., 2] > 200)).astype(np.uint8)
    m[: int(0.10 * h)] = 0                                         # barra de vida del objetivo y título
    m[:int(0.28 * h), : int(0.22 * w)] = 0                         # círculo de vida/energía
    m[:int(0.28 * h), int(0.88 * w):] = 0                          # radar
    m[int(0.86 * h):] = 0
    n, _, st, c = cv2.connectedComponentsWithStats(m)
    pts = [(c[i][0], c[i][1]) for i in range(1, n)
           if 40 * k * k <= st[i, 4] <= 400 * k * k and 6 * k <= st[i, 2] <= 26 * k and 8 * k <= st[i, 3] <= 26 * k]
    found: list[tuple[float, float]] = []
    for a in pts:
        for b in pts:
            if a[0] < b[0] and abs(a[1] - b[1]) <= 4 * k and 120 * k <= b[0] - a[0] <= 360 * k and _double(pts, a, k) and _double(pts, b, k):
                x, y = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2 + AGGRO_DY * k
                if all(abs(x - fx) > 40 * k or abs(y - fy) > 40 * k for fx, fy in found):
                    found.append((x, y))
    return found


_SIEGE_T = None


def siege_active(frame):
    """True/False según el icono de Siege activo (arriba a la izquierda, junto a la munición); None si no hay plantilla."""
    global _SIEGE_T
    from .config import ROOT
    if _SIEGE_T is None:
        t = cv2.imread(str(ROOT / "assets" / "siege_icon.png"))
        if t is None:
            return None
        _SIEGE_T = t
    h, w = frame.shape[:2]
    strip = frame[int(0.03 * h):int(0.12 * h), int(0.10 * w):int(0.32 * w)]
    k = w / 1904.0
    t = _SIEGE_T if abs(k - 1) < 0.03 else cv2.resize(_SIEGE_T, None, fx=k, fy=k, interpolation=cv2.INTER_AREA)
    if t.shape[0] >= strip.shape[0] or t.shape[1] >= strip.shape[1]:
        return None
    return bool(cv2.matchTemplate(strip, t, cv2.TM_CCOEFF_NORMED).max() >= 0.75)
