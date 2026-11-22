"""Lanza el bot con la capa superpuesta sobre el juego.
Uso: python scripts/bot.py
  controls.toggle_key: inicia/detiene el bot      controls.exit_key: cierra el programa entero"""
import ctypes
import os
import signal
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("QT_LOGGING_RULES", "qt.qpa.window=false")   # silencia el aviso de escala de Qt (inofensivo)

try:                                    # antes de crear la app: coordenadas físicas (la mira es el cursor)
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:  # noqa: BLE001
    pass

from PySide6.QtCore import QObject, QTimer, Signal  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from src.bot import Bot  # noqa: E402
from src.capture import find_hwnd  # noqa: E402
from src.config import load_config  # noqa: E402
from src.control import is_foreground  # noqa: E402
from src.killswitch import start_exit_watch  # noqa: E402
from src.overlay_widget import BotOverlay  # noqa: E402
from src.panel import ControlPanel  # noqa: E402


class _Bridge(QObject):
    state = Signal(dict)


def main() -> None:
    cfg = load_config()
    app = QApplication(sys.argv)
    overlay = BotOverlay(cfg)
    bridge = _Bridge()
    bridge.state.connect(overlay.set_state)
    bot = Bot(cfg, view_cb=bridge.state.emit)
    start_exit_watch(cfg["controls"].get("exit_key", "plus"), on_exit=bot.shutdown, log=bot.log,
                     active_if=lambda: is_foreground(find_hwnd(cfg["capture"])))       # "+" solo con el juego al frente
    th = threading.Thread(target=bot.run, daemon=True, name="bot")
    th.start()

    def quit_app(*_):
        bot.shutdown()
        sys.stdout.flush()
        os._exit(0)                                             # salida limpia: sin esperar a los hilos de fondo

    if "--auto" in sys.argv:                                      # modo de prueba: se inicia solo y se cierra a los N segundos
        secs = int(sys.argv[sys.argv.index("--auto") + 1]) if len(sys.argv) > sys.argv.index("--auto") + 1 else 40

        def auto() -> None:
            while bot.msg in ("Iniciando…", "Calentando captura y modelo…"):
                time.sleep(0.2)
            time.sleep(1.0)
            bot.toggle.running = True
            bot.log(f"[AUTO] Bot iniciado por la prueba automática ({secs} s).")
            time.sleep(secs)
            bot.toggle.running = False
            time.sleep(1.0)
            bot.log("[AUTO] Fin de la prueba automática.")
            quit_app()

        threading.Thread(target=auto, daemon=True, name="auto").start()

    if "--start" in sys.argv:                                     # arranca ya activo, sin límite de tiempo (se para con Pausar/Cerrar)
        def start() -> None:
            while bot.msg in ("Iniciando…", "Calentando captura y modelo…"):
                time.sleep(0.2)
            time.sleep(1.0)
            bot.toggle.running = True
            bot.log("[START] Bot iniciado automáticamente.")

        threading.Thread(target=start, daemon=True, name="start").start()

    panel = ControlPanel(cfg, bot, quit_app)                     # Iniciar / Pausar / Cerrar, sin robar el foco
    panel.show()

    signal.signal(signal.SIGINT, quit_app)
    QTimer(app, interval=200, timeout=lambda: None).start()      # deja que Python atienda Ctrl+C
    app.aboutToQuit.connect(lambda: (bot.shutdown(), th.join(3)))
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
