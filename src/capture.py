"""Captura de pantalla.

source: process  → ventana del proceso indicado (Windows Graphics Capture). Funciona aunque esté
                   tapada por otras ventanas o estés en otra app. No funciona minimizada ni en
                   pantalla completa exclusiva.
source: window   → igual, buscando la ventana por parte del título.
source: monitor  → todo el monitor (lo que se ve en pantalla).
"""
import ctypes
import threading
import time
from ctypes import wintypes

import cv2
import mss
import numpy as np
import psutil

user32 = ctypes.windll.user32


# ---------- búsqueda de ventanas ----------
def list_windows() -> list[dict]:
    """Ventanas visibles con título: [{hwnd, pid, exe, title, w, h}]."""
    out = []
    enum_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def cb(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            n = user32.GetWindowTextLengthW(hwnd)
            rect = wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            w, h = rect.right - rect.left, rect.bottom - rect.top
            if n and w > 100 and h > 100:
                buf = ctypes.create_unicode_buffer(n + 1)
                user32.GetWindowTextW(hwnd, buf, n + 1)
                pid = wintypes.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                try:
                    exe = psutil.Process(pid.value).name()
                except psutil.Error:
                    exe = "?"
                out.append({"hwnd": hwnd, "pid": pid.value, "exe": exe, "title": buf.value, "w": w, "h": h})
        return True

    user32.EnumWindows(enum_proc(cb), 0)
    return out


def find_hwnd(cfg: dict):
    """hwnd de la ventana más grande que cumpla con el proceso o título configurado."""
    wins = list_windows()
    if cfg.get("source") == "process":
        key = str(cfg.get("process_name", "")).lower().removesuffix(".exe")
        wins = [w for w in wins if key and key in w["exe"].lower()]
    else:
        key = str(cfg.get("window_title", "")).lower()
        wins = [w for w in wins if key and key in w["title"].lower()]
    return max(wins, key=lambda w: w["w"] * w["h"])["hwnd"] if wins else None


def _target_desc(cfg: dict) -> str:
    if cfg.get("source") == "process":
        return f"el proceso '{cfg.get('process_name', '')}'"
    return f"la ventana '{cfg.get('window_title', '')}'"


# ---------- captura ----------
class ScreenCapture:
    """Se usa desde el hilo del worker; la captura por ventana corre en su propio hilo interno."""

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.sct = None
        self._ctl = None
        self._hwnd = None
        self._latest: np.ndarray | None = None
        self._closed = False
        self._lock = threading.Lock()
        self._next_try = 0.0

    # --- monitor ---
    def _grab_monitor(self) -> np.ndarray:
        if self.sct is None:
            self.sct = mss.mss()
        mons = self.sct.monitors
        shot = np.asarray(self.sct.grab(mons[min(self.cfg.get("monitor", 1), len(mons) - 1)]))
        return np.ascontiguousarray(shot[:, :, :3])

    # --- proceso / ventana ---
    def _start_window_capture(self):
        from windows_capture import WindowsCapture

        hwnd = find_hwnd(self.cfg)
        if hwnd is None:
            raise RuntimeError(f"No encuentro {_target_desc(self.cfg)}. ¿Está abierto el juego? "
                               "(scripts/listar_ventanas.py muestra los nombres)")
        def on_frame_arrived(frame, _control):
            bgr = np.ascontiguousarray(frame.frame_buffer[:, :, :3])
            with self._lock:
                self._latest = bgr

        def on_closed():
            with self._lock:
                self._closed = True

        with self._lock:
            self._latest, self._closed = None, False
        self._hwnd = hwnd
        last_err = None
        # Primero sin borde amarillo; algunos Windows no lo permiten y se reintenta con borde.
        for hide_border in (False, None):
            try:
                cap = WindowsCapture(cursor_capture=False, draw_border=hide_border, window_hwnd=hwnd)
                cap.event(on_frame_arrived)
                cap.event(on_closed)
                self._ctl = cap.start_free_threaded()
                return
            except Exception as e:  # noqa: BLE001
                last_err = e
        raise RuntimeError(f"No se pudo capturar esa ventana ({last_err}). "
                           "Si es una app de la Tienda de Windows no es compatible.")

    def _grab_window(self) -> np.ndarray:
        now = time.monotonic()
        if (self._ctl is None or self._closed or self._ctl.is_finished()) and now >= self._next_try:
            self._next_try = now + 1.5
            self._ctl = None
            self._start_window_capture()
        if self._hwnd and user32.IsIconic(self._hwnd):
            raise RuntimeError("La ventana del juego está minimizada: no se puede capturar así.")
        with self._lock:
            frame = self._latest
        if frame is None:
            raise RuntimeError(f"Esperando imagen de {_target_desc(self.cfg)}…")
        return frame

    def grab(self) -> np.ndarray:
        if self.cfg.get("source") in ("process", "window"):
            frame = self._grab_window()
        else:
            frame = self._grab_monitor()
        max_w = self.cfg.get("max_width")
        if max_w and frame.shape[1] > max_w:
            h = int(frame.shape[0] * max_w / frame.shape[1])
            frame = cv2.resize(frame, (max_w, h), interpolation=cv2.INTER_AREA)
        return frame

    def close(self):
        if self._ctl is not None:
            try:
                self._ctl.stop()
            except Exception:  # noqa: BLE001
                pass
            self._ctl = None
