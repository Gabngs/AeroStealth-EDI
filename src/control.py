"""Entrada al juego: teclas por scancode, mouse relativo suave y clics. Todo se suelta con release_all()."""
import ctypes
import time
from ctypes import wintypes

user32 = ctypes.windll.user32

KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_SCANCODE = 0x0008
MOUSEEVENTF_MOVE = 0x0001

SCAN = {"w": 0x11, "a": 0x1E, "s": 0x1F, "d": 0x20, "q": 0x10, "space": 0x39, "tab": 0x0F, "shift": 0x2A,
        "0": 0x0B, **{str(i): 0x01 + i for i in range(1, 10)}}


class _KBD(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class _MOU(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class _INPUT(ctypes.Structure):
    class _U(ctypes.Union):
        _fields_ = [("ki", _KBD), ("mi", _MOU)]
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _U)]


class Controls:
    def __init__(self):
        self.keys_down: set[str] = set()
        self.buttons_down: set[str] = set()

    # ---- teclado ----
    def _key(self, key: str, up: bool) -> None:
        flags = KEYEVENTF_SCANCODE | (KEYEVENTF_KEYUP if up else 0)
        inp = _INPUT(type=1, ki=_KBD(0, SCAN[key], flags, 0, 0))
        user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))

    def key_down(self, key: str) -> None:
        if key not in self.keys_down:
            self._key(key, False)
            self.keys_down.add(key)

    def key_up(self, key: str) -> None:
        if key in self.keys_down:
            self._key(key, True)
            self.keys_down.discard(key)

    def tap(self, key: str, hold: float = 0.08) -> None:
        self.key_down(key)
        time.sleep(hold)
        self.key_up(key)

    # ---- mouse ----
    def move_rel(self, dx: int, dy: int, steps: int = 3, total: float = 0.03) -> None:
        """Mueve el mouse (movimiento relativo) en varios pasos pequeños, no de golpe."""
        sx = sy = 0
        for i in range(1, steps + 1):
            tx, ty = round(dx * i / steps), round(dy * i / steps)
            ddx, ddy = tx - sx, ty - sy
            sx, sy = tx, ty
            inp = _INPUT(type=0, mi=_MOU(ddx, ddy, 0, MOUSEEVENTF_MOVE, 0, 0))
            user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))
            time.sleep(total / steps)

    def button_down(self, which: str = "left") -> None:
        if which not in self.buttons_down:
            user32.mouse_event(0x0002 if which == "left" else 0x0008, 0, 0, 0, 0)
            self.buttons_down.add(which)

    def button_up(self, which: str = "left") -> None:
        if which in self.buttons_down:
            user32.mouse_event(0x0004 if which == "left" else 0x0010, 0, 0, 0, 0)
            self.buttons_down.discard(which)

    def release_all(self) -> None:
        for k in list(self.keys_down):
            self.key_up(k)
        for b in list(self.buttons_down):
            self.button_up(b)


def is_foreground(hwnd) -> bool:
    return bool(hwnd) and user32.GetForegroundWindow() == hwnd
