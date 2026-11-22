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


# ---------- munición (arriba a la izquierda): 5 dígitos azul claro bajo cada barra naranja ----------
_DIGITS = None
CELL = (10, 14)                 # tamaño normalizado de cada dígito (ancho, alto)


def _ammo_cells(frame):
    """[(celdas_std, celdas_avanzada)]: cada una son 5 recortes binarios normalizados de dígitos; None si no se ve el HUD."""
    h, w = frame.shape[:2]
    k = w / 1920.0
    roi = frame[: int(0.10 * h), : int(0.30 * w)]
    hsv = cv2.cvtColor(roi[: int(0.062 * h)], cv2.COLOR_BGR2HSV)       # solo la franja de las barras (el círculo de vida es del mismo color)
    m = ((hsv[..., 0] < 18) | (hsv[..., 0] > 170)) & (hsv[..., 1] > 150) & (hsv[..., 2] > 150)
    rows = np.where(m.sum(1) >= 40 * k)[0]
    if not len(rows):
        return None
    cols = np.where(m[rows[0]:rows[-1] + 1].sum(0) >= 2)[0]
    runs, s, p = [], cols[0], cols[0]
    for c in list(cols[1:]) + [10 ** 6]:
        if c - p > 6 * k:
            runs.append((s, p))
            s = c
        p = c
    bars = [r for r in runs if r[1] - r[0] >= 60 * k][:2]
    if len(bars) < 2:
        return None
    y0, y1 = int(rows[-1] + 6 * k), int(rows[-1] + 22 * k)
    out = []
    for a, b in bars:
        x0, x1 = int(a + 22 * k), int(b + 8 * k)
        sub = cv2.cvtColor(roi[y0:y1, x0:x1], cv2.COLOR_BGR2HSV)
        mk = ((sub[..., 2] > 170) & (sub[..., 1] < 170)).astype(np.uint8)
        cs, rs = np.where(mk.any(0))[0], np.where(mk.any(1))[0]
        if len(cs) < 10 * k or not len(rs):
            return None
        n, lab, st, _ = cv2.connectedComponentsWithStats(mk)           # cada dígito es una mancha; se ordenan de izquierda a derecha
        blobs = sorted((i for i in range(1, n) if st[i, 4] >= 6 * k * k), key=lambda i: st[i, 0])
        if len(blobs) != 5:
            return None
        cells = []
        for i in blobs:
            x, y, bw, bh = st[i, :4]
            crop = (lab[rs[0]:rs[-1] + 1, x:x + bw] == i).astype(np.float32)      # alto común de la fila: la forma no cambia
            cells.append(cv2.resize(crop, CELL, interpolation=cv2.INTER_AREA))
        out.append(cells)
    return out


def _load_digits():
    global _DIGITS
    if _DIGITS is None:
        from .config import ROOT
        p = ROOT / "assets" / "digits.npz"
        _DIGITS = dict(np.load(p)) if p.exists() else {}
    return _DIGITS


def ammo_counts(frame):
    """(munición estándar, munición avanzada) leídas de la pantalla; cada una es un int o None si no se pudo leer."""
    cells, lib = _ammo_cells(frame), _load_digits()
    if cells is None or not lib:
        return None, None
    vals = []
    for five in cells:
        digits = []
        for c in five:
            d, best = None, 1e9
            for name, t in lib.items():
                e = float(np.abs(c - t).mean())
                if e < best:
                    d, best = name, e
            digits.append(d if best < 0.25 else None)
        vals.append(int("".join(digits)) if None not in digits else None)
    return vals[0], vals[1]


# ---------- barra de habilidades (abajo al centro) y buffs activos (arriba a la izquierda) ----------
_ICONS: dict = {}


def _icon(name: str):
    if name not in _ICONS:
        from .config import ROOT
        _ICONS[name] = cv2.imread(str(ROOT / "assets" / "skills" / f"{name}.png"))
    return _ICONS[name]


def _bar_match(strip, name: str, k: float):
    t = _icon(name)
    if t is None:
        return 0.0, 0
    if abs(k - 1) > 0.03:
        t = cv2.resize(t, None, fx=k, fy=k, interpolation=cv2.INTER_AREA)
    if t.shape[0] >= strip.shape[0] or t.shape[1] >= strip.shape[1]:
        return 0.0, 0
    _, mx, _, loc = cv2.minMaxLoc(cv2.matchTemplate(strip, t, cv2.TM_CCOEFF_NORMED))
    return float(mx), loc[0]


def skill_key(frame, name: str, thr: float = 0.8):
    """Tecla (1-9, 0 = décimo) del icono `name` en la barra de habilidades visible, o None si esta barra no lo tiene.
    Siege va siempre en el slot 1 de todas las barras: sirve de ancla para calcular el slot."""
    h, w = frame.shape[:2]
    k = w / 1920.0
    strip = frame[int(0.86 * h):int(0.98 * h), int(0.38 * w):int(0.64 * w)]
    ms, xs = _bar_match(strip, "siege_mode", k)
    if ms < 0.85:
        return None
    m, x = _bar_match(strip, name, k)
    if m < thr:
        return None
    slot = round((x - xs) / (31.0 * k)) + 1
    return None if not 1 <= slot <= 10 else str(slot % 10)


def buff_count(frame):
    """Cuántos buffs temporales hay activos: iconos de ~20 px que aparecen en la fila de arriba a la izquierda tras los 3
    permanentes (que terminan a ~295 px de la barra naranja de munición, a 1920 de ancho). None si no se ve el HUD."""
    h, w = frame.shape[:2]
    k = w / 1920.0
    bx = _ammo_bar_x(frame)
    if bx is None:
        return None
    strip = cv2.cvtColor(frame[int(0.035 * h):int(0.061 * h), bx:int(bx + 420 * k)], cv2.COLOR_BGR2HSV)
    cols = np.where((strip[..., 2] > 70).sum(0) >= 6 * k)[0]
    if not len(cols):
        return 0
    runs, st, p = [], cols[0], cols[0]
    for x in list(cols[1:]) + [10 ** 6]:
        if x - p > 4 * k:
            runs.append((st, p))
            st = x
        p = x
    return sum(1 for a, b in runs if 296 * k <= a < 350 * k and 14 * k <= b - a + 1 <= 28 * k)


def _ammo_bar_x(frame):
    """Columna donde empieza la barra naranja de munición estándar (ancla de la fila de iconos), o None."""
    h, w = frame.shape[:2]
    k = w / 1920.0
    hsv = cv2.cvtColor(frame[: int(0.062 * h), : int(0.30 * w)], cv2.COLOR_BGR2HSV)
    m = ((hsv[..., 0] < 18) | (hsv[..., 0] > 170)) & (hsv[..., 1] > 150) & (hsv[..., 2] > 150)
    rows = np.where(m.sum(1) >= 40 * k)[0]
    if not len(rows):
        return None
    cols = np.where(m[rows[0]:rows[-1] + 1].sum(0) >= 2)[0]
    cols = cols[cols > 20 * k]
    return int(cols[0]) if len(cols) else None


# ---------- estado del arma estándar: icono rojo (sin munición) y barra naranja (calor) ----------
def ammo_empty(frame) -> bool:
    """Sin munición estándar: el icono de balas de la izquierda del contador se pone rojo (normalmente es azul) y los
    dígitos también; así se detecta aunque no se puedan leer."""
    h, w = frame.shape[:2]
    k = w / 1920.0
    roi = cv2.cvtColor(frame[int(0.044 * h):int(0.062 * h), :int(0.040 * w)], cv2.COLOR_BGR2HSV)
    red = ((roi[..., 0] < 6) | (roi[..., 0] > 174)) & (roi[..., 1] > 200) & (roi[..., 2] > 200)
    return int(red.sum()) >= 50 * k * k


def heat_bar(frame):
    """Fracción (0-1) que queda de la barra naranja sobre la munición estándar (se vacía al recalentarse el arma),
    o None si no se ve. La barra mide ~88 px y la de la munición avanzada (siempre llena) sirve de ancla."""
    h, w = frame.shape[:2]
    k = w / 1920.0
    y0, y1 = int(0.0385 * h), int(0.0425 * h)
    hsv = cv2.cvtColor(frame[y0:y1, : int(0.30 * w)], cv2.COLOR_BGR2HSV)
    m = (((hsv[..., 0] < 18) | (hsv[..., 0] > 170)) & (hsv[..., 1] > 150) & (hsv[..., 2] > 150)).any(0)
    cols = np.where(m)[0]
    if not len(cols):
        return None
    runs, st, p = [], cols[0], cols[0]
    for x in list(cols[1:]) + [10 ** 6]:
        if x - p > 6 * k:
            runs.append((st, p))
            st = x
        p = x
    big = [r for r in runs if r[1] - r[0] >= 60 * k and r[0] > 100 * k]
    if not big:
        return None
    left = big[-1][0] - 124 * k                                     # la barra estándar empieza 124 px antes que la avanzada
    end = left
    for x in range(int(left), int(left + 95 * k)):
        if m[x]:
            end = x
    return float(max(0.0, min(1.0, (end - left + 1) / (88 * k))))
