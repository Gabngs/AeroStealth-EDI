"""Pantalla "Seleccionar nave": cambia con las flechas hasta el personaje deseado y pulsa Aceptar.

Los personajes se distinguen por el nombre de la barra inferior (NeoryuGS = I-GEAR,
NeoryuAgs = A-GEAR, ...Mgs = M-GEAR, ...Bgs = B-GEAR). El bot solo entra con A-GEAR.
Se compara el recorte del nombre con una plantilla guardada en assets/ (sin OCR).
"""
import ctypes
import time
from ctypes import wintypes

import cv2

from .capture import ScreenCapture, find_hwnd
from .config import ROOT
from .mouse import click

user32 = ctypes.windll.user32

KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_SCANCODE = 0x0008
SCANCODES = {"right": 0x4D, "left": 0x4B, "up": 0x48, "down": 0x50}  # flechas = teclas extendidas

REF_W = 1920  # resolución en la que se tomaron las coordenadas/plantillas


class _KBD(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class _INPUT(ctypes.Structure):
    class _U(ctypes.Union):
        _fields_ = [("ki", _KBD), ("pad", ctypes.c_byte * 32)]
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _U)]


def _press(key: str, hold: float = 0.08) -> None:
    """Pulsa una flecha con scancode (los juegos suelen ignorar las teclas virtuales)."""
    sc = SCANCODES[key]
    for flags in (KEYEVENTF_SCANCODE | KEYEVENTF_EXTENDEDKEY,
                  KEYEVENTF_SCANCODE | KEYEVENTF_EXTENDEDKEY | KEYEVENTF_KEYUP):
        inp = _INPUT(type=1, ki=_KBD(0, sc, flags, 0, 0))
        user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))
        if not flags & KEYEVENTF_KEYUP:
            time.sleep(hold)


def _click_rel(hwnd, rx: float, ry: float) -> None:
    r = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    click(int(r.left + (r.right - r.left) * rx), int(r.top + (r.bottom - r.top) * ry))


def _name_score(frame, template, cfg: dict) -> float:
    """Parecido (0-1) entre el nombre en pantalla y la plantilla, buscando cerca de su sitio."""
    scale = REF_W / frame.shape[1]
    if scale != 1:
        frame = cv2.resize(frame, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    # el nombre está abajo y centrado; se busca en toda esa franja (en ventana la imagen cambia de tamaño)
    h, w = frame.shape[:2]
    roi = frame[int(h * 0.72):, int(w * 0.25):int(w * 0.75)]
    return float(cv2.matchTemplate(roi[..., :3], template, cv2.TM_CCOEFF_NORMED).max())


def _grab(cap, timeout: float = 20.0):
    """La captura por proceso tarda un momento en entregar el primer cuadro: reintenta."""
    end = time.time() + timeout
    while True:
        try:
            return cap.grab()
        except RuntimeError:
            if time.time() > end:
                raise
            time.sleep(0.3)


def select_gear(cfg: dict, capture_cfg: dict, log=print) -> bool:
    """Cambia de nave con la flecha hasta que el nombre coincida con cfg['target']. True si entró."""
    ref = {k: cv2.imread(str(ROOT / p)) for k, p in cfg["templates"].items()}
    target = cfg["target"]
    if ref.get(target) is None:
        log(f"Falta la plantilla de {target}.")
        return False

    cap = ScreenCapture(capture_cfg)
    try:
        hwnd = find_hwnd(capture_cfg)
        if not hwnd:
            log("No encuentro la ventana del juego.")
            return False
        user32.SetForegroundWindow(hwnd)
        time.sleep(0.5)

        for attempt in range(cfg.get("max_presses", 8) + 1):
            time.sleep(cfg.get("settle_delay", 1.0))  # deja terminar la animación de cambio
            frame = _grab(cap)
            scores = {k: _name_score(frame, t, cfg) for k, t in ref.items() if t is not None}
            best = max(scores, key=scores.get)
            log(f"Nave actual: {best} ({scores[best]:.2f})")
            others = [v for k, v in scores.items() if k != best]
            margin = scores[best] - max(others, default=0.0)
            if best == target and scores[best] >= cfg.get("threshold", 0.8) and margin >= cfg.get("margin", 0.08):
                _click_rel(hwnd, *cfg["accept_button"])
                log(f"{target} aceptada.")
                return True
            _press(cfg.get("key", "right"))
        log(f"No encontré {target} tras {cfg.get('max_presses', 8)} pulsaciones.")
        return False
    finally:
        cap.close()
