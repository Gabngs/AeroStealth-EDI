"""Graba cómo juegas TÚ (cursor, teclas, clics) junto con lo que ve el juego (fijado, vida, quién te marca).
Necesita administrador (el juego está elevado). Uso: python scripts/grabar_manual.py [segundos] [salida.csv]"""
import csv
import ctypes
import sys
import threading
import time
from ctypes import wintypes
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
ctypes.windll.shcore.SetProcessDpiAwareness(2)

from src.capture import ScreenCapture, find_hwnd  # noqa: E402
from src.config import load_config  # noqa: E402
from src.hud import green_arrows, red_arrows, target_hp  # noqa: E402
from src.overlay_widget import visible_rect  # noqa: E402

u = ctypes.windll.user32
KEYS = {"1": 0x31, "shift": 0x10, "space": 0x20, "w": 0x57, "a": 0x41, "s": 0x53, "d": 0x44, "q": 0x51}


def down(vk: int) -> int:
    return 1 if u.GetAsyncKeyState(vk) & 0x8000 else 0


def main() -> None:
    secs = int(sys.argv[1]) if len(sys.argv) > 1 else 75
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("manual.csv")
    cfg = load_config()
    hwnd = find_hwnd(cfg["capture"])
    u.ShowWindow(hwnd, 9)
    u.SetForegroundWindow(hwnd)
    x, y, w, h = visible_rect(hwnd)
    state = {"lock": None, "hp": None, "aggro": 0}
    stop = threading.Event()

    def vision() -> None:                                   # lo que ve el juego, ~10 Hz
        cap = ScreenCapture(cfg["capture"])
        while not stop.is_set():
            try:
                f = cap.grab()
            except RuntimeError:
                time.sleep(0.05)
                continue
            a = green_arrows(f)
            state["lock"] = None if a is None else (round(a[0] * w / f.shape[1] + x), round(a[1] * h / f.shape[0] + y))
            state["hp"] = target_hp(f)
            state["aggro"] = len(red_arrows(f))
            time.sleep(0.08)
        cap.close()

    threading.Thread(target=vision, daemon=True).start()
    print(f"Grabando {secs} s: juega normal (mata las calabazas). No cierres esta ventana.", flush=True)
    pt = wintypes.POINT()
    t0 = time.time()
    with out.open("w", newline="", encoding="utf-8") as fh:
        wr = csv.writer(fh)
        wr.writerow(["t", "cx", "cy", "left", "right", *KEYS, "lock_x", "lock_y", "hp", "aggro"])
        while time.time() - t0 < secs:
            u.GetCursorPos(ctypes.byref(pt))
            lk = state["lock"]
            wr.writerow([round(time.time() - t0, 3), pt.x - x, pt.y - y, down(1), down(2), *[down(v) for v in KEYS.values()],
                         "" if lk is None else lk[0] - x, "" if lk is None else lk[1] - y,
                         "" if state["hp"] is None else round(state["hp"], 3), state["aggro"]])
            time.sleep(0.016)
    stop.set()
    print("Listo. Guardado en", out, flush=True)


if __name__ == "__main__":
    main()
