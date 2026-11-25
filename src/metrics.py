"""Métricas por etapas (Fase 0 del plan): eventos en JSONL + un resumen por etapa con KPIs normalizados por minuto.
No cambia el comportamiento del bot: solo observa. Salida: logs/etapas/<fecha>/{events,stage_summary}.jsonl"""
import json
import statistics
import time
from contextlib import contextmanager
from pathlib import Path

TIMERS = ("grab", "hp", "detect", "step", "loop")


class Metrics:
    def __init__(self, root: Path, enabled: bool = True, stage_s: float = 300.0, meta: dict | None = None):
        self.enabled = enabled
        self.stage_s = stage_s
        self.meta = meta or {}
        self.dir = root / "logs" / "etapas" / time.strftime("%Y%m%d_%H%M%S")
        self.stage = 0
        self._active = False
        self._reset_stage()

    # ---------- ciclo de vida ----------
    def _reset_stage(self) -> None:
        self.t0 = time.time()
        self.c: dict[str, float] = {}                 # contadores y tiempos acumulados
        self.timers: dict[str, list[float]] = {k: [] for k in TIMERS}
        self._last_tick = self.t0
        self.switches_since_kill = 0
        self.kill_t = None                            # cuándo se fijó el objetivo actual (para tiempo medio por kill)

    def start(self) -> None:
        """Al activar el bot: abre una etapa nueva (la anterior, incompleta, se descarta)."""
        if not self.enabled:
            return
        self.dir.mkdir(parents=True, exist_ok=True)
        self._active = True
        self._reset_stage()
        self.event("start", stage=self.stage, **self.meta)

    def stop(self) -> None:
        if self.enabled and self._active:
            if self.c.get("active_s", 0) >= 5:                # una etapa recién abierta y casi vacía no se guarda
                self._close_stage(partial=True)
            self._active = False

    # ---------- registro ----------
    def event(self, kind: str, **data) -> None:
        if not (self.enabled and self._active):
            return
        rec = {"t": round(time.time(), 3), "stage": self.stage, "e": kind, **data}
        try:
            with open(self.dir / "events.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except OSError:
            pass

    def count(self, key: str, n: float = 1) -> None:
        if self.enabled and self._active:
            self.c[key] = self.c.get(key, 0) + n

    @contextmanager
    def timer(self, name: str):
        if not (self.enabled and self._active):
            yield
            return
        t = time.perf_counter()
        try:
            yield
        finally:
            self.timers[name].append(time.perf_counter() - t)

    def tick(self, locked: bool, siege_on: bool, ammo_low: bool) -> None:
        """Se llama una vez por paso con el bot activo: reparte el tiempo transcurrido entre los estados."""
        if not (self.enabled and self._active):
            return
        now = time.time()
        dt = min(now - self._last_tick, 0.5)
        self._last_tick = now
        self.c["active_s"] = self.c.get("active_s", 0) + dt
        if locked:
            self.c["locked_s"] = self.c.get("locked_s", 0) + dt
        else:
            self.c["no_target_s"] = self.c.get("no_target_s", 0) + dt
            if siege_on:
                self.c["siege_no_target_s"] = self.c.get("siege_no_target_s", 0) + dt
        if ammo_low:
            self.c["ammo_low_s"] = self.c.get("ammo_low_s", 0) + dt
        if now - self.t0 >= self.stage_s:
            self._close_stage()

    # ---------- eventos con semántica ----------
    def locked_on(self) -> None:
        self.kill_t = time.time()

    def kill(self, **extra) -> None:
        self.count("kills")
        dur = None
        if self.kill_t is not None:
            dur = time.time() - self.kill_t
            self.count("kill_time_s", dur)
        self.count("switches_total", self.switches_since_kill)
        self.event("kill", dur=None if dur is None else round(dur, 2), switches=self.switches_since_kill, **extra)
        self.switches_since_kill, self.kill_t = 0, None

    def switch(self) -> None:
        self.count("switches")
        self.switches_since_kill += 1

    # ---------- resumen ----------
    def summary(self, partial: bool = False) -> dict:
        dur = max(time.time() - self.t0, 1e-6)
        mins = dur / 60
        c = self.c
        kills = c.get("kills", 0)
        act = max(c.get("active_s", 0), 1e-6)
        s = {
            "stage": self.stage, "partial": partial, "dur_s": round(dur, 1),
            "kills": int(kills), "kills_min": round(kills / mins, 3),
            "locked_pct": round(100 * c.get("locked_s", 0) / act, 1),
            "no_target_s_min": round(c.get("no_target_s", 0) / mins, 2),
            "siege_no_target_s_min": round(c.get("siege_no_target_s", 0) / mins, 2),
            "switches_per_kill": round(c.get("switches", 0) / kills, 2) if kills else None,
            "kill_time_avg_s": round(c.get("kill_time_s", 0) / kills, 2) if kills else None,
            "reclics_min": round(c.get("reclics", 0) / mins, 2),
            "unsticks_min": round(c.get("unsticks", 0) / mins, 2),
            "heats": int(c.get("heats", 0)),
            "reloads": int(c.get("reloads", 0)),
            "ammo_low_s": round(c.get("ammo_low_s", 0), 1),
            "buff_casts": int(c.get("buff_casts", 0)),
            "no_fix": int(c.get("no_fix", 0)),
        }
        s["fitness"] = self.fitness(s)
        lat = {}
        for k, v in self.timers.items():
            if v:
                v = sorted(v)
                lat[k] = {"mean_ms": round(1000 * statistics.fmean(v), 2),
                          "p95_ms": round(1000 * v[min(len(v) - 1, int(0.95 * len(v)))], 2), "n": len(v)}
        s["latency"] = lat
        return s

    @staticmethod
    def fitness(s: dict, a: float = 0.05, b: float = 0.1, c: float = 0.3, d: float = 0.2) -> float:
        """kills/min - a·sin_objetivo - b·Siege_sin_objetivo - c·cambios_por_kill - d·(reclics+unsticks)/min (plan, Fase 3)."""
        return round(s["kills_min"] - a * s["no_target_s_min"] - b * s["siege_no_target_s_min"]
                     - c * (s["switches_per_kill"] or 0) - d * (s["reclics_min"] + s["unsticks_min"]), 3)

    def _close_stage(self, partial: bool = False) -> dict | None:
        s = self.summary(partial)
        try:
            with open(self.dir / "stage_summary.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps(s, ensure_ascii=False) + "\n")
        except OSError:
            pass
        if not partial:
            self.stage += 1
            self._reset_stage()
        return s
