"""Abre el launcher del juego y pulsa JUGAR (fase 6, auto-login).

No maneja contraseÃ±as: el launcher las recuerda ("Recordar mis datos" marcado) y deja
usuario/clave rellenos. Solo se abre, se espera a que termine de actualizar y se pulsa JUGAR.
"""
import ctypes
import subprocess
import time
from ctypes import wintypes

import mss
import numpy as np

from .capture import find_hwnd, list_windows
from .mouse import click

user32 = ctypes.windll.user32


def _rect(hwnd) -> tuple[int, int, int, int]:
    r = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    return r.left, r.top, r.right - r.left, r.bottom - r.top


def _button_point(hwnd, cfg: dict) -> tuple[int, int]:
    x, y, w, h = _rect(hwnd)
    rx, ry = cfg["play_button"]
    return int(x + w * rx), int(y + h * ry)


def _button_ready(hwnd, cfg: dict) -> bool:
    """El botÃ³n JUGAR estÃ¡ activo cuando su color es el azul brillante (en actualizaciÃ³n se apaga)."""
    px, py = _button_point(hwnd, cfg)
    with mss.mss() as sct:
        shot = np.array(sct.grab({"left": px - 30, "top": py - 10, "width": 60, "height": 20}))
    b, g, r = (float(np.median(shot[..., i])) for i in range(3))  # mediana: ignora el texto "JUGAR"
    lo, hi = np.array(cfg["play_rgb_low"]), np.array(cfg["play_rgb_high"])
    return bool(np.all((np.array([r, g, b]) >= lo) & (np.array([r, g, b]) <= hi)))


def _wait_window(cfg: dict, timeout: float):
    key = {"source": "window", "window_title": cfg["window_title"]}
    end = time.time() + timeout
    while time.time() < end:
        hwnd = find_hwnd(key)
        if hwnd:
            return hwnd
        time.sleep(0.5)
    return None


def _checkbox_on(hwnd, cfg: dict) -> bool:
    """La casilla marcada es azul; sin marcar es casi negra."""
    x, y, w, h = _rect(hwnd)
    rx, ry = cfg["window_checkbox"]
    px, py = int(x + w * rx), int(y + h * ry)
    with mss.mss() as sct:
        shot = np.array(sct.grab({"left": px - 4, "top": py - 4, "width": 9, "height": 9}))
    return float(np.median(shot[..., 1])) > 70  # canal verde


def ensure_window_mode(hwnd, cfg: dict, log=print) -> None:
    """Marca "Ventana" en el launcher para que el juego abra en ventana y no a pantalla completa."""
    if not cfg.get("window_mode") or _checkbox_on(hwnd, cfg):
        return
    x, y, w, h = _rect(hwnd)
    rx, ry = cfg["window_checkbox"]
    click(int(x + w * rx), int(y + h * ry))
    time.sleep(0.4)
    log("Modo ventana activado." if _checkbox_on(hwnd, cfg) else "No pude marcar 'Ventana'.")


def game_running(game_process: str) -> bool:
    key = game_process.lower().removesuffix(".exe")
    return any(key in w["exe"].lower() for w in list_windows())


def launch_and_play(cfg: dict, log=print) -> bool:
    """Abre el launcher (o reutiliza el abierto) y pulsa JUGAR. True si se pulsÃ³."""
    hwnd = find_hwnd({"source": "window", "window_title": cfg["window_title"]})
    if not hwnd:
        log(f"Abriendo launcher: {cfg['exe']}")
        subprocess.Popen([cfg["exe"]], cwd=cfg.get("cwd") or None)
        hwnd = _wait_window(cfg, cfg.get("open_timeout", 60))
        if not hwnd:
            log("No apareciÃ³ la ventana del launcher.")
            return False

    user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    user32.SetForegroundWindow(hwnd)

    end = time.time() + cfg.get("ready_timeout", 600)
    while time.time() < end:
        if _button_ready(hwnd, cfg):
            break
        time.sleep(1)
    else:
        log("JUGAR no se activÃ³ a tiempo (Â¿actualizando o pidiendo datos?).")
        return False

    time.sleep(cfg.get("settle_delay", 1.0))
    user32.SetForegroundWindow(hwnd)
    ensure_window_mode(hwnd, cfg, log)
    click(*_button_point(hwnd, cfg))
    log("JUGAR pulsado.")
    return True
