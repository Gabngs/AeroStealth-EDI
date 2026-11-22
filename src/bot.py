"""Bot de farmeo en tierra: elige una calabaza, desliza el cursor (que es la mira del juego) hasta ella,
dispara con el arma estándar y la mata; si no hay daño se mueve para despejar la línea.
Se inicia/detiene con el botón (toggle_key). Detecta y dibuja siempre; solo actúa cuando está activo.
Si sale la verificación anti-AFK se detiene y avisa; no la resuelve."""
import atexit
import ctypes
import math
import random
import threading
import time
import winsound
from ctypes import wintypes

from .afk_guard import afk_dialog_visible
from .capture import ScreenCapture, find_hwnd
from .config import ROOT
from .control import Controls, is_foreground, user32
from .hud import _bar_match, ammo_counts, ammo_empty, buff_count, heat_bar, green_arrows, red_arrows, skill_key, target_hp
from .killswitch import Toggle
from .overlay_widget import visible_rect

try:                                    # coordenadas físicas: la mira es el cursor y Windows escala al 125 %
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:  # noqa: BLE001
    pass

NO_DAMAGE_S = 3.0        # mira fijada pero sin bajar la vida del objetivo durante este tiempo: soltarla con shift
AVOID_S = 6.0            # tras soltar un objetivo que no se deja matar, no se vuelve a elegir durante este tiempo
LOCK_PX = 40             # el cursor está "sobre" el enemigo si está a menos de estos píxeles de su centro
AFK_CHECK_S = 1.0        # la comprobación anti-AFK es cara: una vez por segundo
ON_TARGET_PX = 70        # el cursor está sobre el fijado si está a menos de esto del centro de las flechas verdes
KNOWN_TTL_S = 25.0       # tiempo que se recuerda una calabaza que ya no se ve (casi no se mueven)
DEAD_S = 4.0             # tras matar una, no volver a su sitio durante este tiempo (reaparece)
LOST_TICKS = 4          # ciclos sin barra de vida antes de dar el objetivo por muerto o soltado
HOVER_S = 2.5            # cursor sobre un enemigo sin que se fije en este tiempo: no se deja (lejos u obstáculo), elegir otro
MAX_FAILS = 3            # objetivos seguidos sin daño: parar y avisar (probablemente sin munición)
USER_PAUSE_S = 0.6      # si el usuario mueve el mouse, el bot deja de apuntar durante este tiempo
USER_MOVE_PX = 25        # movimiento entre dos pasos del bot (8 ms) que se toma como "lo movió el usuario"
SIEGE_SETTLE_S = 0.9     # tiempo que tarda Siege en apagarse del todo; sin mover el mouse durante ese tiempo
MOVE_WINDOW_S = 0.8      # ventana en la que se mide si las flechas verdes (el enemigo) se desplazan
MOVE_PX = 18             # desplazamiento en esa ventana que se toma como "el enemigo se mueve"
DOUBT_CONF = 0.4         # por debajo: detección dudosa; la mira va a comprobarla y si no se fija en HOVER_DOUBT_S se descarta
HOVER_DOUBT_S = 1.2
AMMO_LOW = 100           # munición estándar por debajo de esto: recargar (caja de recarga, slot 0 de la barra 1)
MAINT_EVERY_S = 2.0      # cada cuánto se revisan munición y buffs (solo sin enemigo fijado)
BUFF_RETRY_S = 45.0      # tras lanzar buffs no se reintenta antes de esto: las habilidades tienen tiempo de reuso
AMMO_RETRY_S = 45.0
HEAT_LOW, HEAT_OK = 0.2, 0.6   # barra naranja sobre la munición: bajo HEAT_LOW se suelta el clic hasta que suba de HEAT_OK
BAR_SETTLE_S = 0.5       # tiempo que tarda en cambiar la barra con tab
HEAT_COOL_S = 4.0        # el arma se recalienta si se mantiene el clic: soltar este tiempo (la munición no es el problema)
MAX_HEAT = 2             # recalentamientos seguidos antes de dar el objetivo por imposible
SIEGE_SPEED = 0.3        # con Siege el mouse mueve la cámara: a 0.3 de velocidad para que no gire y gire
NUDGE_EVERY_S = 0.04     # tiempo mínimo entre empujes del mouse hacia el siguiente enemigo
NUDGE_PX = 110           # empuje máximo del mouse por ciclo
NUDGE_MIN_PX = 9         # empuje mínimo (cerca del objetivo)
CHAIN_EXCLUDE_PX = 55    # solo el propio fijado (a menos de esto de las flechas verdes) no cuenta como "siguiente"; los vecinos sí
SIEGE_EMPTY_S = 1.0      # en Siege sin ningún enemigo a la vista durante este tiempo: apagar Siege
SIEGE_TRANSIT_MAX_S = 2.5   # en Siege sin fijar a nadie durante este tiempo: apagar Siege (evita quedarse dando vueltas)
SIEGE_NO_DAMAGE_S = 2.0     # en Siege, fijado sin daño durante este tiempo: soltarlo (puede ser una escoba lejana que arrastra la cámara)
RECLICK_S = 1.2             # fijado sin bajarle vida: soltar y volver a pulsar el clic (Siege o el recalentamiento pueden cortar el disparo)
MANEUVER_MIN_S = 360.0   # reposicionarse cada 6-8 min: w x3, s x3, a x2, d x2 (queda en el mismo sitio)
MANEUVER_MAX_S = 480.0
TICK_HOLD_S = 0.25       # un "tic" de tecla
TICK_GAP_S = 0.15
SCAN_AFTER_S = 1.5       # sin enemigos detectados durante este tiempo: barrer la pantalla con la mira
SCAN_POINTS = [(0.5, 0.45), (0.25, 0.4), (0.15, 0.55), (0.35, 0.3), (0.5, 0.3), (0.65, 0.3), (0.85, 0.55), (0.75, 0.4),
               (0.65, 0.55), (0.5, 0.55), (0.35, 0.55)]   # fracciones del cuadro; evita el HUD de las esquinas y la nave
SCAN_STEP_S = 1.2        # tiempo en cada punto del barrido
STATS_EVERY_S = 60.0     # resumen en el log (sesiones largas)


class Aim(threading.Thread):
    """Desliza el cursor hacia un destino (en píxeles de pantalla) a ~120 Hz, frenando al llegar."""

    def __init__(self):
        super().__init__(daemon=True, name="aim")
        self.target: tuple[float, float] | None = None
        self.stop = False
        self.user_until = 0.0
        self.last_delta = 0.0

    @property
    def user_active(self) -> bool:
        return time.time() < self.user_until

    def set_target(self, xy) -> None:
        self.target = xy

    def run(self) -> None:
        pt = wintypes.POINT()
        last = None                                              # dónde dejó el cursor este hilo la última vez
        while not self.stop:
            tgt = self.target
            if tgt is not None:
                user32.GetCursorPos(ctypes.byref(pt))
                moved = math.hypot(pt.x - last[0], pt.y - last[1]) if last is not None else 0.0
                if moved > USER_MOVE_PX:
                    self.user_until = time.time() + USER_PAUSE_S      # el usuario movió el mouse: le cedo el control
                    self.last_delta = moved
                if time.time() < self.user_until:
                    last = (pt.x, pt.y)
                    time.sleep(0.02)
                    continue
                dx, dy = tgt[0] - pt.x, tgt[1] - pt.y
                d = math.hypot(dx, dy)
                if d > 1.5:
                    step = min(max(d * 0.2, 3.0), 45.0)       # ease-out: rápido lejos, suave cerca
                    step = min(step, d)
                    last = (round(pt.x + dx / d * step), round(pt.y + dy / d * step))
                    user32.SetCursorPos(*last)
            else:
                last = None
            time.sleep(0.008)


class Bot:
    def __init__(self, cfg: dict, view_cb=None):
        from ultralytics import YOLO
        self.cfg = cfg
        d = cfg["detector"]
        self.model = YOLO(str(ROOT / d["yolo_weights"]))
        self.conf, self.max_det = d["conf"], d.get("max_det", 10)
        self.cap = ScreenCapture(cfg["capture"])
        self.ctl = Controls()
        atexit.register(self.ctl.release_all)                       # nunca dejar un clic o tecla pegados
        self.toggle = Toggle(cfg["controls"].get("toggle_key", "period"), log=self.log,
                             active_if=lambda: is_foreground(find_hwnd(cfg["capture"])))   # "." solo con el juego al frente
        self.aim = Aim()
        self.aim.start()
        self.panel_rect = None                                       # (x1, y1, x2, y2) del panel en píxeles de pantalla
        self.view_cb = view_cb
        self._last_boxes: list = []
        self.stop = False
        self.msg = "Iniciando…"
        self.fps = 0.0
        self._afk_next, self._afk = 0.0, False
        self._last_msg: dict[str, float] = {}
        self._reset()

    # ---------- utilidades ----------
    def log(self, msg: str) -> None:
        print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)

    def say(self, key: str, msg: str, every: float = 1.5) -> None:
        """Log con límite de frecuencia por tipo de mensaje; también va al cartel de la capa."""
        self.msg = msg
        now = time.time()
        if now - self._last_msg.get(key, 0) >= every:
            self._last_msg[key] = now
            self.log(msg)

    def _reset(self) -> None:
        self.known = []                         # mapa de calabazas: [x, y, última vez vista]; no se mueven casi nunca
        self.dead = []                          # ((x, y), cuándo) de las que acabo de matar
        self.tracks = []                        # seguimiento de enemigos entre cuadros (estabiliza las cajas)
        self.last_hp = None
        self.hp_t = time.time()
        self.stuck = 0
        self.kills = 0
        self.target_c = None
        self.avoid = None                       # ((x, y), hasta cuándo): objetivo soltado por no dejarse matar
        self.release_until = 0.0                # tras soltar la mira: sin disparar, para que apunte a otro y no re-fije el mismo
        self.aggro = []                         # enemigos que me marcan (flechas rojas): prioridad
        self.none_ticks = 0                     # ciclos seguidos sin leer la barra de vida (evita dar por muerto por un parpadeo)
        self.fails = 0                          # objetivos seguidos soltados sin haberles hecho daño
        self.hover_t = None                     # desde cuándo el cursor está sobre un enemigo sin que se fije
        self.siege_on, self.siege_t, self.siege_hold = False, 0.0, 0.0   # Siege solo si el enemigo se mueve
        self.ammo_empty, self.heat, self.hot = False, None, False
        self._diag_saved = False
        self.use_siege = self.cfg["controls"].get("use_siege", True)
        self.fresh_boxes: list = []
        self.ammo = (None, None)                # (estándar, avanzada) leídas del HUD
        self.ammo_t, self.maint_t = 0.0, 0.0
        self.buff_cool = self.ammo_cool = 0.0
        self.cool_until, self.heat_tries = 0.0, 0   # arma recalentada: sin disparar hasta entonces
        self.on_target_t = 0.0                  # última vez que el cursor estuvo sobre el fijado
        self.reclick_at, self.click_t = 0.0, 0.0
        self.transit_t, self.nudge_t = None, 0.0   # desde cuándo está en Siege buscando el siguiente sin fijar a nadie
        self.arrow_hist = []                    # posiciones recientes de las flechas verdes (detecta enemigo en movimiento)
        now = time.time()
        self.next_maneuver = now + random.uniform(MANEUVER_MIN_S, MANEUVER_MAX_S)
        self.empty_since = None                 # desde cuándo no hay ningún enemigo a la vista
        self.scan_i, self.scan_t = 0, 0.0       # barrido de la mira cuando no hay detecciones
        self.t_start, self.stats_t = now, now + STATS_EVERY_S

    def shutdown(self) -> None:
        self.stop = True
        self.aim.stop = True
        self.aim.set_target(None)
        self.ctl.release_all()

    def _grab(self, timeout: float = 20.0):
        end = time.time() + timeout
        while True:
            try:
                return self.cap.grab()
            except RuntimeError:
                if time.time() > end or self.stop:
                    raise
                time.sleep(0.1)

    def _detect(self, frame) -> list:
        r = self.model.predict(frame, conf=self.conf, imgsz=800, max_det=self.max_det, verbose=False)[0]
        return [(*b.xyxy[0].tolist(), float(b.conf[0])) for b in r.boxes]

    def _track(self, boxes: list) -> list:
        """Asocia las detecciones con enemigos ya vistos (<80 px), suaviza su posición y solo devuelve los que se
        ven en 3 cuadros o más: así la caja no tiembla y un falso de un solo cuadro no manda el cursor al aire."""
        a = 0.35
        for t in self.tracks:
            t["seen"] = False
        for b in boxes:
            cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
            best, bd = None, 80.0
            for t in self.tracks:
                d = math.hypot(t["c"][0] - cx, t["c"][1] - cy)
                if not t["seen"] and d < bd:
                    best, bd = t, d
            if best is not None:
                best["c"] = (best["c"][0] * (1 - a) + cx * a, best["c"][1] * (1 - a) + cy * a)
                best["wh"] = (best["wh"][0] * (1 - a) + (b[2] - b[0]) * a, best["wh"][1] * (1 - a) + (b[3] - b[1]) * a)
                best.update(age=best["age"] + 1, miss=0, seen=True, conf=b[4])
            else:
                self.tracks.append({"c": (cx, cy), "wh": (b[2] - b[0], b[3] - b[1]), "age": 1, "miss": 0, "seen": True, "conf": b[4]})
        for t in self.tracks:
            if not t["seen"]:
                t["miss"] += 1
        self.tracks = [t for t in self.tracks if t["miss"] <= 5]
        stable = [t for t in self.tracks if t["age"] >= 3 and t["miss"] <= 2]
        now = time.time()
        for t in stable:                                             # actualiza el mapa de ubicaciones
            for k in self.known:
                if math.hypot(k[0] - t["c"][0], k[1] - t["c"][1]) < 60:
                    k[0], k[1], k[2] = k[0] * 0.8 + t["c"][0] * 0.2, k[1] * 0.8 + t["c"][1] * 0.2, now
                    break
            else:
                self.known.append([t["c"][0], t["c"][1], now])
        self.known = [k for k in self.known if now - k[2] < KNOWN_TTL_S]
        def box(t):
            return (t["c"][0] - t["wh"][0] / 2, t["c"][1] - t["wh"][1] / 2, t["c"][0] + t["wh"][0] / 2,
                    t["c"][1] + t["wh"][1] / 2, t["conf"])
        self.fresh_boxes = [box(t) for t in stable if t["miss"] == 0]    # vistos en este cuadro (en Siege la cámara se mueve)
        return [box(t) for t in stable]

    def warmup(self) -> None:
        """Calienta la captura y el modelo para que el primer ciclo con el bot activo ya responda."""
        self.msg = "Calentando captura y modelo…"
        frame = self._grab()
        self._detect(frame)
        self._detect(frame)
        afk_dialog_visible(frame)
        self.msg = "Listo"
        self.log("Listo. Pulsa el botón de inicio/parada para empezar.")

    # ---------- coordenadas: cuadro <-> pantalla ----------
    def _win(self):
        hwnd = find_hwnd(self.cfg["capture"])
        return (hwnd, *visible_rect(hwnd)) if hwnd else (None, 0, 0, 1, 1)

    def to_screen(self, fx: float, fy: float, frame) -> tuple[float, float]:
        _, x, y, w, h = self._win()
        return x + fx * w / frame.shape[1], y + fy * h / frame.shape[0]

    def cursor_in_frame(self, frame):
        """Posición del cursor (= la mira) en coordenadas del cuadro."""
        _, x, y, w, h = self._win()
        pt = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        fx, fy = (pt.x - x) * frame.shape[1] / w, (pt.y - y) * frame.shape[0] / h
        return (fx, fy) if 0 <= fx < frame.shape[1] and 0 <= fy < frame.shape[0] else None

    # ---------- bucle ----------
    def run(self) -> None:
        active, t_prev = False, time.time()
        try:
            self.warmup()
            while not self.stop:
                try:
                    frame = self._grab(2.0)
                except RuntimeError:
                    continue
                hp = target_hp(frame)
                if active and self.last_hp is not None and hp is not None and not self.siege_on:    # disparando a uno fijado: sin YOLO (más fps, el clic no se corta)
                    boxes = self._last_boxes
                else:
                    boxes = self._last_boxes = self._track(self._detect(frame))   # cajas estables, sin temblor ni falsos de un cuadro
                cur = self.cursor_in_frame(frame)
                now = time.time()
                self.fps = 0.9 * self.fps + 0.1 / max(now - t_prev, 1e-6)
                t_prev = now

                if self.toggle.running and not active:
                    active = True
                    self._reset()
                    self.log("Bot ACTIVO.")
                    hwnd = find_hwnd(self.cfg["capture"])
                    if hwnd:
                        user32.SetForegroundWindow(hwnd)
                        time.sleep(0.3)
                elif not self.toggle.running and active:
                    active = False
                    self.aim.set_target(None)
                    self.ctl.release_all()
                    self.msg = f"Detenido · calabazas eliminadas: {self.kills}"
                    self.log(f"Bot detenido. Calabazas eliminadas: {self.kills}")
                if active:
                    self.step(frame, boxes, cur, hp)
                elif not self.msg.startswith("Detenido"):
                    self.msg = "Esperando el botón de inicio"
                self.publish(frame, boxes, cur, active)
        finally:
            self.shutdown()

    def publish(self, frame, boxes, cur, active: bool) -> None:
        if self.view_cb:
            self.view_cb({"boxes": boxes, "fw": frame.shape[1], "fh": frame.shape[0], "fps": self.fps,
                          "active": active, "msg": self.msg, "target": self.target_c, "reticle": cur})

    # ---------- un paso con el bot activo ----------
    def _cursor_on_panel(self) -> bool:
        if not self.panel_rect:
            return False
        pt = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        x1, y1, x2, y2 = self.panel_rect
        return x1 - 6 <= pt.x <= x2 + 6 and y1 - 6 <= pt.y <= y2 + 6

    def _afk_dialog(self, frame) -> bool:
        now = time.time()
        if now >= self._afk_next:
            self._afk_next = now + AFK_CHECK_S
            self._afk = afk_dialog_visible(frame)
        return self._afk

    def step(self, frame, boxes, cur, hp) -> None:
        hwnd = find_hwnd(self.cfg["capture"])
        if not is_foreground(hwnd):
            self.aim.set_target(None)
            self.ctl.release_all()
            self.say("foco", "El juego no tiene el foco: en pausa (haz clic en su ventana).", 3)
            return
        if self._cursor_on_panel() or self.aim.user_active:
            self.ctl.button_up("left")                               # el usuario está usando el mouse (p. ej. el panel)
            why = "cursor sobre el panel" if self._cursor_on_panel() else f"movimiento de {self.aim.last_delta:.0f} px"
            self.say("usuario", f"Mouse en uso ({why}): el bot espera.", 3)
            return
        if self._afk_dialog(frame):
            self.aim.set_target(None)
            self.ctl.release_all()
            self.toggle.running = False
            self.msg = "VERIFICACIÓN ANTI-AFK: resuélvela tú"
            self.log("VERIFICACIÓN ANTI-AFK en pantalla: bot detenido. Resuélvela tú y vuelve a iniciarlo.")
            for _ in range(3):
                winsound.Beep(1200, 250)
            return
        if time.time() - self.ammo_t >= 1.0:
            self.ammo_t = time.time()
            self.ammo = ammo_counts(frame)
            self.ammo_empty = ammo_empty(frame)                      # icono rojo: sin munición aunque no se lean los dígitos
        self.heat = heat_bar(frame)
        self.aggro = red_arrows(frame)                               # quién me marca (el enemigo está ~100 px bajo el cartel)
        arrows = green_arrows(frame)                                 # fijado = flechas verdes a los costados (+ barra de vida)
        seen = hp is not None or arrows is not None
        self.none_ticks = 0 if seen else self.none_ticks + 1
        locked = seen or (self.last_hp is not None and self.none_ticks < LOST_TICKS)   # un parpadeo no cuenta como "murió"
        on_lock = arrows is not None and cur is not None and math.hypot(arrows[0] - cur[0], arrows[1] - cur[1]) < ON_TARGET_PX
        if not locked:
            self._periodic(frame)
        if locked and (time.time() >= self.release_until or on_lock):    # el cursor sobre un fijado manda: no ir a otro
            self.attack(frame, hp if hp is not None else (self.last_hp if self.last_hp is not None else 1.0), arrows, cur)
        else:                                                        # sin objetivo, o recién soltado: buscar otro
            self.search(frame, boxes, cur)

    # ---------- mantenimiento ----------
    def _periodic(self, frame) -> None:
        """Resumen en el log y, cada 6-8 min, el vaivén de reposicionamiento (solo sin enemigo fijado)."""
        now = time.time()
        if now >= self.stats_t:
            self.stats_t = now + STATS_EVERY_S
            mins = (now - self.t_start) / 60
            self.log(f"[{mins:.1f} min] eliminados: {self.kills} ({self.kills / max(mins, 1e-6):.1f}/min), fps {self.fps:.0f}")
        if now >= self.next_maneuver and self.last_hp is None and not self.siege_on:
            self.maneuver()
        elif self.last_hp is None:
            self.maintain(frame)

    def maintain(self, frame) -> None:
        """Sin enemigo fijado: recarga munición si se acaba y renueva los buffs (6 y 7 de la barra 3) si caducaron."""
        now = time.time()
        if now < self.maint_t or self.siege_on or now < self.siege_hold:
            return
        self.maint_t = now + MAINT_EVERY_S
        if self._ammo_low() and now >= self.ammo_cool:
            self.ammo_cool = now + AMMO_RETRY_S
            self.log(f"Munición estándar en {self.ammo[0]}: uso la caja de recarga.")
            self.cast([("ammo_recharge_box", 0.45)])
            return
        bc = buff_count(frame)
        if bc is not None and bc < 2 and now >= self.buff_cool:
            self.buff_cool = now + BUFF_RETRY_S
            self.log(f"Buffs activos: {bc}. Los renuevo (fire_shot y concentration).")
            self.cast([("fire_shot", 0.6), ("concentration", 0.6)])   # en reuso el icono sale oscuro: 0.6-0.7

    def _ammo_low(self) -> bool:
        std = self.ammo[0]
        return self.ammo_empty or (std is not None and std <= AMMO_LOW)

    def cast(self, skills) -> None:
        """Busca cada habilidad por su icono recorriendo las 3 barras con tab y pulsa su tecla (el slot sale de la posición)."""
        self.aim.set_target(None)
        self.ctl.button_up("left")
        for name, thr in skills:
            for _ in range(3):
                if not self.toggle.running or self.stop:
                    return
                try:
                    fr = self._grab(2.0)
                except RuntimeError:
                    return
                key = skill_key(fr, name, thr)
                if not key:                                          # diagnóstico: puntuaciones y captura de lo que ve el bot
                    h, w = fr.shape[:2]
                    strip = fr[int(0.86 * h):int(0.98 * h), int(0.38 * w):int(0.64 * w)]
                    sg, sx = _bar_match(strip, "siege_mode", w / 1920.0)
                    sc, sxx = _bar_match(strip, name, w / 1920.0)
                    self.log(f"[diag] {name}: marco {w}x{h}, siege {sg:.2f}@{sx}, {name} {sc:.2f}@{sxx} (umbral {thr})")
                    if not self._diag_saved:
                        self._diag_saved = True
                        import cv2
                        cv2.imwrite(str(ROOT / "logs" / "diag_barra.png"), fr)
                if key:
                    self.ctl.tap(key, 0.08)
                    self.log(f"{name}: tecla {key}.")
                    time.sleep(0.5)
                    break
                self.ctl.tap("tab", 0.08)                            # esta barra no la tiene: la siguiente (1 -> 2 -> 3 -> 1)
                time.sleep(BAR_SETTLE_S)
            else:
                self.log(f"No encontré {name} en ninguna barra (¿en reuso?): lo intento más tarde.")

    def _ticks(self, key: str, n: int) -> bool:
        for _ in range(n):
            if not self.toggle.running or self.stop:
                return False
            self.ctl.tap(key, TICK_HOLD_S)
            time.sleep(TICK_GAP_S)
        return True

    def maneuver(self) -> None:
        """w x3, s x3 (vuelve al mismo sitio) y a x2, d x2 (la misma vista): cambia un poco la escena sin desplazarse."""
        self.log("Reposicionamiento: w x3, s x3, a x2, d x2.")
        self.msg = "Reposicionando…"
        self.aim.set_target(None)
        self.ctl.button_up("left")
        self._ticks("w", 3) and self._ticks("s", 3) and self._ticks("a", 2) and self._ticks("d", 2)
        self.ctl.release_all()
        self.known, self.tracks, self.dead = [], [], []                # la escena cambió un poco: se vuelve a aprender
        self.next_maneuver = time.time() + random.uniform(MANEUVER_MIN_S, MANEUVER_MAX_S)

    # ---------- ataque ----------
    def attack(self, frame, hp: float, arrows=None, cur=None) -> None:
        """Enemigo fijado (el juego lo fija solo al pasar el cursor): disparar con el arma estándar hasta que muera.
        Sin Siege el cursor se mueve libre: si no está sobre el fijado, se desliza hasta las flechas verdes."""
        now = time.time()
        self.hover_t = None
        if now < self.cool_until:                                    # arma recalentada: clic suelto hasta que se enfríe
            self.ctl.button_up("left")
            self.hp_t = now
            self.say("calor", "Arma recalentada: espero a que se enfríe.", 2.0)
            return
        if self.heat is not None:                                    # barra naranja casi vacía: el arma se recalienta, soltar el clic
            self.hot = self.heat < HEAT_LOW or (self.hot and self.heat < HEAT_OK)
        if self.hot:
            self.ctl.button_up("left")
            self.hp_t = now
            self.say("calor", f"Barra de calor baja ({self.heat:.0%}): suelto el clic hasta que se recupere.", 2.0)
            return
        if self._ammo_low():                                         # sin munición: no esperar 3 s para soltar y recargar
            self.hp_t = 0.0
        on_target = arrows is not None and cur is not None and math.hypot(arrows[0] - cur[0], arrows[1] - cur[1]) < ON_TARGET_PX
        if self.siege_on:                                            # Siege: la mira queda atada al fijado; se sigue disparando y el
            self.aim.set_target(None)                                # mouse se va empujando hacia el siguiente enemigo (se libera al morir)
            self.ctl.button_down("left")
            if (self.reclick_at and now >= self.reclick_at) or (now - self.hp_t > RECLICK_S and now - self.click_t > RECLICK_S):
                self.reclick_at, self.click_t = 0.0, now             # sin daño: soltar y volver a pulsar (el clic pudo cortarse)
                self.ctl.button_up("left")
                time.sleep(0.05)
                self.ctl.button_down("left")
                self.log("Reclic: sigue fijado y no baja la vida.")
            self.transit_t = None
            if arrows is not None:
                self.target_c = arrows                               # el fijado de ahora (para anotarlo como muerto)
                self._siege_push(cur, self._candidates(arrows))
        elif on_target or now - self.on_target_t < 1.5:              # un parpadeo de las flechas no suelta el clic: se mantiene
            self.aim.set_target(None)
            self.ctl.button_down("left")
            if on_target:
                self.on_target_t = now
                self._watch_motion(arrows, now)
                if not self.siege_on and self._candidates(arrows):       # hay más enemigos: Siege en cadena (mata uno y ya va al siguiente)
                    self.log("Hay más enemigos a la vista: Siege en cadena.")
                    self.siege(True)
        else:
            self.ctl.button_up("left")                               # fijado pero el cursor no está encima: no disparar
            self.aim.set_target(self.to_screen(*arrows, frame) if arrows is not None else None)
        if self.last_hp is None:
            self.last_hp, self.hp_t, self.stuck = hp, now, 0
            self.log(f"Enemigo fijado, vida {hp:.0%}. Disparo.")
        if hp < self.last_hp - 0.004:
            self.last_hp, self.hp_t, self.stuck, self.fails, self.heat_tries = hp, now, 0, 0, 0
        elif now - self.hp_t > (SIEGE_NO_DAMAGE_S if self.siege_on else NO_DAMAGE_S):
            self.unstick()
            self.hp_t = now
        self.say("vida", f"Disparando · vida del objetivo {hp:.0%}")

    def _candidates(self, exclude=None) -> list:
        """Enemigos detectados a los que ir después: sin los recién muertos ni el que está fijado (`exclude`)."""
        now = time.time()
        out = []
        for b in self.fresh_boxes:
            cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
            if exclude is not None and math.hypot(cx - exclude[0], cy - exclude[1]) < CHAIN_EXCLUDE_PX:
                continue
            if any(now - d[1] < DEAD_S and math.hypot(cx - d[0][0], cy - d[0][1]) < 70 for d in self.dead):
                continue
            if self.avoid and now < self.avoid[1] and math.hypot(cx - self.avoid[0][0], cy - self.avoid[0][1]) < CHAIN_EXCLUDE_PX:
                continue                                             # el que no se dejó matar (obstáculo, fuera de alcance)
            out.append(b)
        return out

    def _siege_push(self, cur, cands) -> bool:
        """Con Siege el mouse mueve la cámara: empujes cortos en línea recta hacia el siguiente enemigo (el más cercano
        a la mira). Con uno fijado la mira no cede, así que el empuje queda listo para cuando muera."""
        now = time.time()
        if not cands or cur is None:
            return False
        b = min(cands, key=lambda c: math.hypot((c[0] + c[2]) / 2 - cur[0], (c[1] + c[3]) / 2 - cur[1]))
        tx, ty = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
        dist = math.hypot(tx - cur[0], ty - cur[1])
        if dist >= LOCK_PX and now - self.nudge_t >= NUDGE_EVERY_S:
            self.nudge_t = now
            gain = 0.6 if dist > 160 else 0.22                       # salto rápido si está lejos, ajuste fino al llegar
            nx = int(max(-NUDGE_PX, min(NUDGE_PX, (tx - cur[0]) * gain)) * SIEGE_SPEED)
            ny = int(max(-NUDGE_PX, min(NUDGE_PX, (ty - cur[1]) * gain)) * SIEGE_SPEED)
            mag = math.hypot(nx, ny)
            if mag < NUDGE_MIN_PX:                                   # cerca el empuje se hacía diminuto y no llegaba nunca: mínimo
                nx, ny = round((tx - cur[0]) / dist * NUDGE_MIN_PX), round((ty - cur[1]) / dist * NUDGE_MIN_PX)
            self.ctl.move_rel(nx, ny, steps=3, total=0.03)
            self.say("cadena", f"Siege en cadena: empujo ({nx:+d},{ny:+d}) hacia el siguiente, a {dist:.0f} px.", 1.0)
        return True

    def _siege_off(self, why: str) -> None:
        """Apaga Siege (y espera a que se asiente) cuando ya no hay a quién ir: nunca dejar la cámara girando sin objetivo."""
        self.aim.set_target(None)
        if self.siege_on:
            self.log(f"Apago Siege: {why}.")
            self.siege(False)
        if not self.siege_on:
            self.siege_hold = time.time() + SIEGE_SETTLE_S
            self.known, self.tracks = [], []                         # la perspectiva cambió con Siege: reaprender
            self.transit_t = self.empty_since = None

    def _watch_motion(self, arrows, now: float) -> None:
        """Los enemigos casi no se mueven y la cámara está quieta: si las flechas verdes se desplazan, el enemigo se
        mueve y cuesta darle; se activa Siege (más daño y la mira se queda en él) hasta matarlo."""
        self.arrow_hist = [h for h in self.arrow_hist if now - h[0] < MOVE_WINDOW_S] + [(now, arrows[0], arrows[1])]
        t0, x0, y0 = self.arrow_hist[0]
        if now - t0 >= MOVE_WINDOW_S * 0.7 and math.hypot(arrows[0] - x0, arrows[1] - y0) > MOVE_PX:
            self.log("El enemigo se mueve: activo Siege hasta matarlo.")
            self.siege(True)

    def siege(self, on: bool) -> None:
        """Siege Mode (tecla 1) es un interruptor: solo se pulsa si hay que cambiar de estado."""
        if self.siege_on == on or time.time() - self.siege_t < 0.8 or (on and not self.use_siege):
            return
        self.ctl.tap(self.cfg["controls"].get("siege_key", "1"), 0.08)
        self.siege_on, self.siege_t = on, time.time()
        self.reclick_at = self.siege_t + 0.7                         # al cambiar de modo el juego corta el disparo: volver a pulsar
        self.arrow_hist = []
        self.log("Siege Mode ACTIVADO." if on else "Siege Mode desactivado.")

    def unstick(self) -> None:
        """Fijado pero sin daño (no lo ve, hay un obstáculo o no hay munición): soltar con shift y
        elegir otro. Si pasa varias veces seguidas, parar y avisar."""
        self.ctl.button_up("left")
        if not self.toggle.running:
            return
        std = self.ammo[0]
        ammo_low = self._ammo_low()
        hot_bar = self.heat is not None and self.heat < HEAT_OK
        if not ammo_low and hot_bar and self.heat_tries < MAX_HEAT:  # recalentada de verdad (barra naranja baja): soltar el clic y esperar
            self.heat_tries += 1
            self.cool_until = time.time() + HEAT_COOL_S
            self.log(f"Sin daño con munición ({std}) y barra de calor al {self.heat:.0%}: suelto el clic {HEAT_COOL_S:.0f} s.")
            return
        self.stuck += 1
        if ammo_low:
            self.ammo_cool = 0.0                                     # recargar en cuanto no haya enemigo fijado
            self.log("Sin munición estándar: suelto el objetivo para recargar.")
        else:
            self.fails += 1
        self.log(f"Fijado sin daño en {NO_DAMAGE_S:.0f} s: suelto con shift y busco otro objetivo.")
        if self.siege_on and not self._candidates(self.target_c):   # en cadena y quedan otros: Siege se queda, solo se suelta este
            self.siege(False)
            self.transit_t = None
            time.sleep(0.5)
        self.ctl.tap("shift", 0.1)
        self.release_until = time.time() + 1.5
        if self.target_c is not None:
            self.avoid = (self.target_c, time.time() + AVOID_S)      # que no vuelva a elegir ese mismo enseguida
        if self.fails >= MAX_FAILS:
            self.toggle.running = False
            self.msg = "Sin daño repetido: ¿sin munición?"
            self.log(f"{MAX_FAILS} objetivos seguidos sin daño: me detengo. Revisa la munición del arma estándar (arriba a la izquierda).")
            for _ in range(3):
                winsound.Beep(900, 250)
        elif self.stuck >= 2:
            self.log("Sigue sin daño: avanzo un poco para despejar la línea.")
            self.ctl.tap("w", 0.6)
        self.last_hp = None

    # ---------- búsqueda y puntería ----------
    def search(self, frame, boxes, cur) -> None:
        if self.last_hp is not None:                                 # había uno fijado y ya no hay barra: murió y la mira se soltó sola
            self.kills += 1
            self.log(f"Enemigo eliminado (total {self.kills}).")
            if self.target_c is not None:
                self.dead.append((self.target_c, time.time()))
                tc = self.target_c                                   # y borrarla del mapa: si no, volvía como "fantasma"
                self.known = [k for k in self.known if math.hypot(k[0] - tc[0], k[1] - tc[1]) > 90]
            self.last_hp = None
            self.target_c = None
            self.fails = 0
        self.ctl.button_up("left")
        now = time.time()
        if now < self.siege_hold:
            return
        self.dead = [d for d in self.dead if now - d[1] < DEAD_S]
        for kx, ky, _ in self.known if not boxes and not self.siege_on else []:            # recordadas solo si no veo ninguna real (nunca antes que una detectada)
            if all(math.hypot(kx - (b[0] + b[2]) / 2, ky - (b[1] + b[3]) / 2) > 60 for b in boxes)                     and all(math.hypot(kx - d[0][0], ky - d[0][1]) > 70 for d in self.dead):
                boxes = boxes + [(kx - 40, ky - 55, kx + 40, ky + 55, 0.5)]
        boxes = [b for b in boxes if all(math.hypot((b[0] + b[2]) / 2 - d[0][0], (b[1] + b[3]) / 2 - d[0][1]) > 70 for d in self.dead)]
        if self.siege_on:                                            # Siege en cadena: sin soltarlo entre enemigos, pero sin quedarse girando
            self.transit_t = self.transit_t or now
            boxes = [b for b in boxes if b in self.fresh_boxes]        # solo lo visto ahora: la cámara se mueve
            if boxes:
                self.empty_since = None
                self._siege_push(cur, boxes)
                if now - self.transit_t > SIEGE_TRANSIT_MAX_S:
                    self._siege_off(f"{SIEGE_TRANSIT_MAX_S:.0f} s sin fijar a nadie")
            else:
                self.empty_since = self.empty_since or now
                if now - self.empty_since > SIEGE_EMPTY_S:
                    self._siege_off("no quedan enemigos a la vista")
            return
        if not boxes:
            self.target_c = None
            self.scan(frame)
            return
        self.empty_since = None
        x1, y1, x2, y2, c = self._choose(boxes, cur)
        tx, ty = (x1 + x2) / 2, (y1 + y2) / 2
        self.target_c = (tx, ty)
        if not self.toggle.running:
            return
        self.aim.set_target(self.to_screen(tx, ty, frame))           # el hilo desliza el cursor hasta allí
        dist = math.hypot(tx - cur[0], ty - cur[1]) if cur is not None else None
        if dist is not None and dist < LOCK_PX:
            # el cursor ya está sobre el enemigo: el juego lo fija solo. Si no se fija, no se deja (lejos u obstáculo)
            now = time.time()
            self.hover_t = self.hover_t or now
            self.say("fijar", f"Cursor sobre el enemigo (conf {c:.2f}): esperando que el juego lo fije.")
            if now - self.hover_t > (HOVER_DOUBT_S if c < DOUBT_CONF else HOVER_S):
                self.log("No se fija (¿lejos u obstáculo?): elijo otro enemigo.")
                self.avoid = ((tx, ty), now + AVOID_S)
                self.target_c = None
                self.hover_t = None
        else:
            self.hover_t = None
            err = "" if dist is None else f", a {dist:.0f} px"
            self.say("apunto", f"Apunto a enemigo (conf {c:.2f}){err}.", 1.0)

    def scan(self, frame) -> None:
        """El modelo no ve nada: pasear la mira por la escena. Los enemigos no se mueven y todo lo que la mira marque
        (flechas verdes) se ataca, aunque el modelo no lo conozca."""
        now = time.time()
        self.empty_since = self.empty_since or now
        if now - self.empty_since < SCAN_AFTER_S:
            self.aim.set_target(None)
            self.say("nada", "Sin enemigos a la vista.", 3)
            return
        if now - self.scan_t >= SCAN_STEP_S:
            self.scan_t = now
            self.scan_i = (self.scan_i + 1) % len(SCAN_POINTS)
        fx, fy = SCAN_POINTS[self.scan_i]
        self.aim.set_target(self.to_screen(fx * frame.shape[1], fy * frame.shape[0], frame))
        self.say("barrido", "Sin detecciones: barro la escena con la mira para que marque lo que haya.", 3)

    def _choose(self, boxes, cur=None):
        """El más CERCANO al cursor (así recorre los enemigos en línea); si ya había uno elegido, se queda con ese."""
        def center(b):
            return (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
        if self.avoid and time.time() < self.avoid[1]:               # descarta el objetivo soltado, si hay otros
            ax, ay = self.avoid[0]
            others = [b for b in boxes if math.hypot(center(b)[0] - ax, center(b)[1] - ay) > 120]
            boxes = others or boxes
        if self.target_c is not None:
            near = min(boxes, key=lambda b: math.hypot(center(b)[0] - self.target_c[0], center(b)[1] - self.target_c[1]))
            if math.hypot(center(near)[0] - self.target_c[0], center(near)[1] - self.target_c[1]) < 150:
                return near
        if cur is not None:
            return min(boxes, key=lambda b: math.hypot(center(b)[0] - cur[0], center(b)[1] - cur[1]))
        return max(boxes, key=lambda b: (b[2] - b[0]) * (b[3] - b[1]))
