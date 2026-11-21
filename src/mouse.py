"""Movimiento de mouse humano: el cursor se desliza hasta el destino en vez de teletransportarse."""
import ctypes
import math
import random
import time
from ctypes import wintypes

user32 = ctypes.windll.user32


def _pos() -> tuple[int, int]:
    p = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(p))
    return p.x, p.y


def glide_to(x: int, y: int, duration: float = 0.6) -> None:
    """Mueve el cursor en una curva suave (aceleración y frenado) con una leve desviación lateral."""
    x0, y0 = _pos()
    dx, dy = x - x0, y - y0
    dist = math.hypot(dx, dy)
    if dist < 2:
        return
    duration = min(max(duration, dist / 2500), 1.5)
    steps = max(int(duration * 120), 8)
    nx, ny = -dy / dist, dx / dist                  # perpendicular al recorrido
    bend = random.uniform(-0.06, 0.06) * dist
    for i in range(1, steps + 1):
        t = i / steps
        e = t * t * (3 - 2 * t)                      # smoothstep
        off = math.sin(math.pi * t) * bend
        user32.SetCursorPos(int(x0 + dx * e + nx * off), int(y0 + dy * e + ny * off))
        time.sleep(duration / steps)
    user32.SetCursorPos(x, y)


def click(x: int, y: int) -> None:
    glide_to(x, y)
    time.sleep(random.uniform(0.12, 0.25))
    user32.mouse_event(0x0002, 0, 0, 0, 0)
    time.sleep(random.uniform(0.05, 0.10))
    user32.mouse_event(0x0004, 0, 0, 0, 0)
