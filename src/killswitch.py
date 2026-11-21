"""Teclas/botones globales: parada de emergencia, interruptor del bot y cierre del programa.
Solo cuentan los flancos de bajada (tecla que pasa de suelta a pulsada); lo que ya estuviera pulsado o
pulsado antes de arrancar se ignora. Opcionalmente solo responden con el juego al frente (active_if)."""
import ctypes
import os
import threading
import time

user32 = ctypes.windll.user32

VK = {"f9": 0x78, "f10": 0x79, "f11": 0x7A, "f12": 0x7B, "f18": 0x81, "f19": 0x82, "end": 0x23, "pause": 0x13,
      "xbutton1": 0x05, "xbutton2": 0x06,  # xbutton = botones laterales del mouse
      "period": 0xBE, "numpad_dot": 0x6E, "plus": 0xBB, "numpad_plus": 0x6B}  # "." y "+" (teclado normal y numérico)


def _as_list(keys) -> list[str]:
    return [keys] if isinstance(keys, str) else list(keys)


def _down(vk: int) -> bool:
    return bool(user32.GetAsyncKeyState(vk) & 0x8000)


def _release_mouse() -> None:
    for vk_btn, up in ((0x01, 0x0004), (0x02, 0x0010)):                 # solo suelta lo que esté pulsado
        if _down(vk_btn):
            user32.mouse_event(up, 0, 0, 0, 0)


class _EdgeWatcher:
    """Llama a on_press(nombre) cuando una de las teclas pasa de suelta a pulsada."""

    def __init__(self, keys, on_press, active_if=None, interval: float = 0.01, debounce: float = 0.0):
        self.keys = _as_list(keys)
        self.vks = {k: VK[k.lower()] for k in self.keys}
        self.on_press, self.active_if = on_press, active_if
        self.interval, self.debounce = interval, debounce
        self._t_last = 0.0
        threading.Thread(target=self._loop, daemon=True, name="keys").start()

    def _loop(self) -> None:
        was = {k: _down(v) for k, v in self.vks.items()}          # lo ya pulsado al arrancar no cuenta
        while True:
            for name, vk in self.vks.items():
                now_down = _down(vk)
                if now_down and not was[name] and (self.active_if is None or self.active_if()):
                    t = time.time()
                    if t - self._t_last >= self.debounce:
                        self._t_last = t
                        self.on_press(name)
                was[name] = now_down
            time.sleep(self.interval)


def start_killswitch(keys="f12", log=print) -> None:
    """Cualquiera de las teclas cierra el programa al instante."""
    def stop(name: str) -> None:
        _release_mouse()
        log(f"\n[{name.upper()}] Detenido por el usuario.")
        os._exit(130)

    _EdgeWatcher(keys, stop, interval=0.03)
    log("Para detener: " + " o ".join(k.upper() for k in _as_list(keys)))


class Toggle:
    """Interruptor: inicia el bot si está detenido y lo detiene si está funcionando."""

    def __init__(self, keys="xbutton2", log=print, debounce: float = 1.0, active_if=None):
        self.log = log
        self.running = False
        self.last_press = ""
        _EdgeWatcher(keys, self._pressed, active_if=active_if, debounce=debounce)

    def _pressed(self, name: str) -> None:
        self.running = not self.running
        self.last_press = name
        self.log(f"[{name.upper()}] Bot {'INICIADO' if self.running else 'DETENIDO'}")

    def release_inputs(self) -> None:
        _release_mouse()


def start_exit_watch(keys, on_exit, log=print, active_if=None) -> None:
    """Tecla que cierra el programa entero: llama a on_exit() (suelta todo) y sale."""
    def close(name: str) -> None:
        log(f"[{name.upper()}] Cerrando el programa.")
        try:
            on_exit()
        finally:
            os._exit(0)

    _EdgeWatcher(keys, close, active_if=active_if, interval=0.02)
    log("Para cerrar el programa: " + " o ".join(k.upper() for k in _as_list(keys)) + " (con el juego al frente)")
