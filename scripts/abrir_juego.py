"""Abre el launcher, entra al juego sin pedir contraseña (la guarda el launcher) y elige A-GEAR.
Uso: python scripts/abrir_juego.py"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.capture import find_hwnd  # noqa: E402
from src.config import load_config  # noqa: E402
from src.gear_select import select_gear  # noqa: E402
from src.killswitch import start_killswitch  # noqa: E402
from src.launcher import launch_and_play  # noqa: E402


def main() -> int:
    cfg = load_config()
    start_killswitch(cfg["controls"].get("killswitch", "xbutton2"))
    if find_hwnd(cfg["capture"]):
        print("El juego ya está abierto: no abro el launcher (evita el doble ingreso).")
        return 0
    if not launch_and_play(cfg["launcher"]):
        return 1
    print("Esperando la ventana del juego…")
    end = time.time() + 300
    while not find_hwnd(cfg["capture"]) and time.time() < end:
        time.sleep(1)
    if not find_hwnd(cfg["capture"]):
        print("El juego no abrió (revisa capture.process_name).")
        return 1
    time.sleep(10)  # carga hasta la pantalla de selección
    return 0 if select_gear(cfg["gear_select"], cfg["capture"]) else 1


if __name__ == "__main__":
    sys.exit(main())
