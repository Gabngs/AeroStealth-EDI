"""Bot de farmeo en tierra: elige una calabaza, desliza el cursor (que es la mira del juego) hasta ella,
dispara con el arma estándar y la mata; si no hay daño se mueve para despejar la línea.
Se inicia/detiene con el botón (toggle_key). Detecta y dibuja siempre; solo actúa cuando está activo.
Si sale la verificación anti-AFK se detiene y avisa; no la resuelve."""
import atexit
import ctypes
import math
import threading
import time
import winsound
from ctypes import wintypes

from .afk_guard import afk_dialog_visible
from .capture import ScreenCapture, find_hwnd
from .config import ROOT
from .control import Controls, is_foreground, user32
from .hud import green_arrows, red_arrows, target_hp
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
SIEGE_SETTLE_S = 0.9     # tiempo que tarda Siege en activarse o apagarse del todo; sin mover el mouse durante ese tiempo
ON_TARGET_PX = 70        # el cursor está sobre el fijado si está a menos de esto del centro de las flechas verdes
SIEGE_SPEED = 0.3        # con Siege el mouse mueve la cámara: a 0.3 de velocidad para que no gire y gire
KNOWN_TTL_S = 25.0       # tiempo que se recuerda una calabaza que ya no se ve (casi no se mueven)
DEAD_S = 4.0             # tras matar una, no volver a su sitio durante este tiempo (reaparece)
NUDGE_EVERY_S = 0.03     # tiempo mínimo entre empujes (la cámara tarda en moverse)
NUDGE_PX = 110            # con Siege activo: empuje máximo del mouse por ciclo hacia el siguiente enemigo
LOST_TICKS = 4          # ciclos sin barra de vida antes de dar el objetivo por muerto o soltado
HOVER_S = 2.5            # cursor sobre un enemigo sin que se fije en este tiempo: no se deja (lejos u obstáculo), elegir otro
MAX_FAILS = 3            # objetivos seguidos sin daño: parar y avisar (probablemente sin munición)
USER_PAUSE_S = 0.6      # si el usuario mueve el mouse, el bot deja de apuntar durante este tiempo
USER_MOVE_PX = 25        # movimiento entre dos pasos del bot (8 ms) que se toma como "lo movió el usuario"


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
                    step = min(max(d * 0.12, 2.0), 20.0)      # ease-out: rápido lejos, suave cerca
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
        self.nudge_t = 0.0
        self.aggro = []                         # enemigos que me marcan (flechas rojas): prioridad
        self.aim_block_until = 0.0              # con Siege el mouse mueve la CÁMARA: sin tocarlo mientras está activo o cambiando
        self.siege_on = False                   # Siege Mode (tecla 1): más daño; detiene la nave y hay que apagarlo para ir al siguiente
        self.siege_t = 0.0
        self.none_ticks = 0                     # ciclos seguidos sin leer la barra de vida (evita dar por muerto por un parpadeo)
        self.fails = 0                          # objetivos seguidos soltados sin haberles hecho daño
        self.hover_t = None                     # desde cuándo el cursor está sobre un enemigo sin que se fije

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
        return [(t["c"][0] - t["wh"][0] / 2, t["c"][1] - t["wh"][1] / 2, t["c"][0] + t["wh"][0] / 2,
                 t["c"][1] + t["wh"][1] / 2, t["conf"]) for t in stable]

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
                boxes = self._track(self._detect(frame))                   # cajas estables, sin temblor ni falsos de un cuadro
                cur = self.cursor_in_frame(frame)
                hp = target_hp(frame)
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
        self.aggro = red_arrows(frame)                               # quién me marca (el enemigo está ~100 px bajo el cartel)
        arrows = green_arrows(frame)                                 # fijado = flechas verdes a los costados (+ barra de vida)
        seen = hp is not None or arrows is not None
        self.none_ticks = 0 if seen else self.none_ticks + 1
        locked = seen or (self.last_hp is not None and self.none_ticks < LOST_TICKS)   # un parpadeo no cuenta como "murió"
        on_lock = arrows is not None and cur is not None and math.hypot(arrows[0] - cur[0], arrows[1] - cur[1]) < ON_TARGET_PX
        if locked and (time.time() >= self.release_until or on_lock):    # el cursor sobre un fijado manda: no ir a otro
            self.attack(hp if hp is not None else (self.last_hp if self.last_hp is not None else 1.0), arrows, cur)
        else:                                                        # sin objetivo, o recién soltado: buscar otro
            self.search(frame, boxes, cur)

    # ---------- ataque ----------
    def siege(self, on: bool) -> None:
        """Activa o desactiva Siege Mode (tecla 1). Es un interruptor: solo se pulsa si hay que cambiar de estado."""
        if self.siege_on == on or time.time() - self.siege_t < 0.8:
            return
        self.ctl.tap(self.cfg["controls"].get("siege_key", "1"), 0.08)
        self.siege_on, self.siege_t = on, time.time()
        self.aim_block_until = time.time() + SIEGE_SETTLE_S          # mientras cambia el modo, no se toca el mouse
        self.log("Siege Mode ACTIVADO (más daño)." if on else "Siege Mode desactivado.")

    def attack(self, hp: float, arrows=None, cur=None) -> None:
        """Enemigo fijado (el juego lo fija solo al pasar el cursor): disparar y usar Siege hasta que muera."""
        now = time.time()
        self.aim.set_target(None)                                    # fijado: el juego mantiene la mira en el objetivo
        self.hover_t = None
        on_target = arrows is not None and cur is not None and math.hypot(arrows[0] - cur[0], arrows[1] - cur[1]) < ON_TARGET_PX
        if on_target:                                                # solo con la mira justo sobre el fijado: Siege y disparo
            self.ctl.button_down("left")
            self.siege(True)
        else:
            self.ctl.button_up("left")                               # fijado pero el cursor no está encima: no disparar
        if self.last_hp is None:
            self.last_hp, self.hp_t, self.stuck = hp, now, 0
            self.log(f"Enemigo fijado, vida {hp:.0%}. Disparo.")
        if hp < self.last_hp - 0.004:
            self.last_hp, self.hp_t, self.stuck, self.fails = hp, now, 0, 0
        elif now - self.hp_t > NO_DAMAGE_S:
            self.unstick()
            self.hp_t = now
        self.say("vida", f"Disparando · vida del objetivo {hp:.0%}")

    def unstick(self) -> None:
        """Fijado pero sin daño (no lo ve, hay un obstáculo o no hay munición): apagar Siege, soltar con shift y
        elegir otro. Si pasa varias veces seguidas, parar y avisar."""
        self.stuck += 1
        self.fails += 1
        self.ctl.button_up("left")
        if not self.toggle.running:
            return
        self.log(f"Fijado sin daño en {NO_DAMAGE_S:.0f} s: apago Siege, suelto con shift y busco otro objetivo.")
        self.siege(False)
        time.sleep(0.3)
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
            self.last_hp = None
            self.target_c = None
            self.fails = 0
        self.ctl.button_up("left")
        now = time.time()
        self.dead = [d for d in self.dead if now - d[1] < DEAD_S]
        for kx, ky, _ in self.known:                                 # calabazas recordadas que ahora no se ven (efectos, etc.)
            if all(math.hypot(kx - (b[0] + b[2]) / 2, ky - (b[1] + b[3]) / 2) > 60 for b in boxes)                     and all(math.hypot(kx - d[0][0], ky - d[0][1]) > 70 for d in self.dead):
                boxes = boxes + [(kx - 40, ky - 55, kx + 40, ky + 55, 0.5)]
        boxes = [b for b in boxes if all(math.hypot((b[0] + b[2]) / 2 - d[0][0], (b[1] + b[3]) / 2 - d[0][1]) > 70 for d in self.dead)]
        if self.aggro:                                               # los que me marcan van primero, aunque el modelo no los vea
            boxes = [(x - 50, y - 60, x + 50, y + 60, 1.0) for x, y in self.aggro]
            self.say("aggro", f"{len(boxes)} enemigo(s) me marcan (flechas rojas): prioridad.", 2.0)
        if not boxes:
            self.target_c = None
            self.aim.set_target(None)
            self.say("nada", "Sin enemigos a la vista.", 3)
            return
        x1, y1, x2, y2, c = self._choose(boxes, cur)
        tx, ty = (x1 + x2) / 2, (y1 + y2) / 2
        self.target_c = (tx, ty)
        if not self.toggle.running:
            return
        if self.siege_on:                                            # Siege sigue activo: el mouse mueve la cámara; basta
            self.aim.set_target(None)                                # empujarlo un poco hacia el siguiente y se autofija al morir el actual
            now = time.time()
            if cur is not None and math.hypot(tx - cur[0], ty - cur[1]) >= LOCK_PX and now - self.nudge_t >= NUDGE_EVERY_S:
                self.nudge_t = now                                   # un empuje corto cada poco: que la cámara se asiente
                dist = math.hypot(tx - cur[0], ty - cur[1])
                gain = 0.6 if dist > 160 else 0.22                   # como tú: salto rápido si está lejos, ajuste fino al llegar
                nx = int(max(-NUDGE_PX, min(NUDGE_PX, (tx - cur[0]) * gain)) * SIEGE_SPEED)
                ny = int(max(-NUDGE_PX, min(NUDGE_PX, (ty - cur[1]) * gain)) * SIEGE_SPEED)
                self.ctl.move_rel(nx, ny, steps=3, total=0.03)
                self.say("empujo", f"Siege activo: empujo el mouse ({nx:+d},{ny:+d}) hacia el siguiente enemigo.", 1.0)
            return
        self.aim.set_target(self.to_screen(tx, ty, frame))           # el hilo desliza el cursor hasta allí
        dist = math.hypot(tx - cur[0], ty - cur[1]) if cur is not None else None
        if dist is not None and dist < LOCK_PX:
            # el cursor ya está sobre el enemigo: el juego lo fija solo. Si no se fija, no se deja (lejos u obstáculo)
            now = time.time()
            self.hover_t = self.hover_t or now
            self.say("fijar", f"Cursor sobre el enemigo (conf {c:.2f}): esperando que el juego lo fije.")
            if now - self.hover_t > HOVER_S:
                self.log("No se fija (¿lejos u obstáculo?): elijo otro enemigo.")
                self.avoid = ((tx, ty), now + AVOID_S)
                self.target_c = None
                self.hover_t = None
        else:
            self.hover_t = None
            err = "" if dist is None else f", a {dist:.0f} px"
            self.say("apunto", f"Apunto a enemigo (conf {c:.2f}){err}.", 1.0)

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
