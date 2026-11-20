"""Registro de teclado y mouse con Raw Input de Windows (sin librerías extra).

- El mouse se registra como movimiento RELATIVO (dx, dy), válido aunque el juego capture el cursor.
- Funciona con el juego en primer plano (RIDEV_INPUTSINK).
- Privacidad: solo se guardan las teclas listadas en `controls` del config (WASD, habilidades,
  Tab, Shift, Espacio, Q…). Cualquier otra tecla (por ejemplo una contraseña) se ignora.
- Solo escribe mientras la grabación está activa.
- F9 (global) alterna la grabación sin tener que volver a esta ventana.
"""
import ctypes
import json
import time
from ctypes import wintypes

from PySide6.QtCore import QAbstractNativeEventFilter, QTimer

WM_INPUT, WM_HOTKEY = 0x00FF, 0x0312
RID_INPUT, RIDEV_INPUTSINK = 0x10000003, 0x00000100
MOD_NOREPEAT, VK_F9, HOTKEY_ID = 0x4000, 0x78, 1

user32 = ctypes.windll.user32


class RAWINPUTDEVICE(ctypes.Structure):
    _fields_ = [("usUsagePage", ctypes.c_ushort), ("usUsage", ctypes.c_ushort),
                ("dwFlags", wintypes.DWORD), ("hwndTarget", wintypes.HWND)]


class RAWINPUTHEADER(ctypes.Structure):
    _fields_ = [("dwType", wintypes.DWORD), ("dwSize", wintypes.DWORD),
                ("hDevice", wintypes.HANDLE), ("wParam", wintypes.WPARAM)]


class RAWMOUSE(ctypes.Structure):
    _fields_ = [("usFlags", ctypes.c_ushort), ("_pad", ctypes.c_ushort),
                ("usButtonFlags", ctypes.c_ushort), ("usButtonData", ctypes.c_ushort),
                ("ulRawButtons", ctypes.c_ulong), ("lLastX", ctypes.c_long),
                ("lLastY", ctypes.c_long), ("ulExtraInformation", ctypes.c_ulong)]


class RAWKEYBOARD(ctypes.Structure):
    _fields_ = [("MakeCode", ctypes.c_ushort), ("Flags", ctypes.c_ushort),
                ("Reserved", ctypes.c_ushort), ("VKey", ctypes.c_ushort),
                ("Message", ctypes.c_uint), ("ExtraInformation", ctypes.c_ulong)]


user32.RegisterRawInputDevices.argtypes = [ctypes.POINTER(RAWINPUTDEVICE), wintypes.UINT, wintypes.UINT]
user32.RegisterRawInputDevices.restype = wintypes.BOOL
user32.GetRawInputData.argtypes = [ctypes.c_void_p, wintypes.UINT, ctypes.c_void_p,
                                   ctypes.POINTER(wintypes.UINT), wintypes.UINT]
user32.GetRawInputData.restype = wintypes.UINT

_VK_NAMES = {0x20: "space", 0x09: "tab", 0x10: "shift", 0x11: "ctrl", 0x12: "alt", 0x1B: "esc",
             0x0D: "enter"}
_BTN = [(0x1, "left", "down"), (0x2, "left", "up"), (0x4, "right", "down"), (0x8, "right", "up"),
        (0x10, "middle", "down"), (0x20, "middle", "up")]


def _name_to_vk(name: str):
    n = str(name).lower()
    if n.startswith("mouse"):
        return None
    for vk, nm in _VK_NAMES.items():
        if nm == n:
            return vk
    if len(n) == 1 and n.isalnum():
        return ord(n.upper())
    return None


def _walk(v):
    if isinstance(v, dict):
        for x in v.values():
            yield from _walk(x)
    elif isinstance(v, (list, tuple)):
        for x in v:
            yield from _walk(x)
    else:
        yield v


def allowed_vks(controls: dict) -> dict[int, str]:
    out = {}
    for v in _walk(controls or {}):
        vk = _name_to_vk(v)
        if vk:
            out[vk] = _VK_NAMES.get(vk, chr(vk).lower())
    return out


class InputRecorder(QAbstractNativeEventFilter):
    def __init__(self, hwnd: int, controls: dict, clock, on_hotkey):
        super().__init__()
        self.allowed = allowed_vks(controls)
        self.clock, self.on_hotkey = clock, on_hotkey
        self.active = False
        self.count = 0
        self.ok = False
        self._file = None
        self._last_hotkey = 0.0
        self._pressed: set[int] = set()
        self._dx = self._dy = 0
        self._buf = ctypes.create_string_buffer(64)
        self._timer = QTimer()
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._flush_mouse)

        h = wintypes.HWND(hwnd)
        devs = (RAWINPUTDEVICE * 2)(RAWINPUTDEVICE(1, 2, RIDEV_INPUTSINK, h),
                                    RAWINPUTDEVICE(1, 6, RIDEV_INPUTSINK, h))
        self.ok = bool(user32.RegisterRawInputDevices(devs, 2, ctypes.sizeof(RAWINPUTDEVICE)))
        self.hotkey_ok = bool(user32.RegisterHotKey(h, HOTKEY_ID, MOD_NOREPEAT, VK_F9))

    # ---------- control ----------
    def start(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._file = open(path, "a", encoding="utf-8", buffering=1)
        self._pressed.clear()
        self._dx = self._dy = 0
        self.count = 0
        self.active = True
        self._timer.start()

    def stop(self):
        self.active = False
        self._timer.stop()
        if self._file:
            self._flush_mouse()
            self._file.close()
            self._file = None

    def _write(self, **ev):
        if self._file:
            self._file.write(json.dumps({"t": self.clock(), **ev}) + "\n")
            self.count += 1

    def _flush_mouse(self):
        if self._dx or self._dy:
            self._write(type="mouse_move", dx=self._dx, dy=self._dy)
            self._dx = self._dy = 0

    # ---------- eventos nativos ----------
    def nativeEventFilter(self, eventType, message):
        try:
            if bytes(eventType) != b"windows_generic_MSG":
                return False, 0
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == WM_HOTKEY and msg.wParam == HOTKEY_ID:
                now = time.monotonic()
                if now - self._last_hotkey > 0.5:  # el mensaje puede llegar duplicado
                    self._last_hotkey = now
                    self.on_hotkey()
            elif msg.message == WM_INPUT and self.active:
                self._handle(msg.lParam)
        except Exception:  # noqa: BLE001 - nunca romper el bucle de eventos de Qt
            import traceback
            traceback.print_exc()
        return False, 0

    def _handle(self, lparam):
        size = wintypes.UINT(ctypes.sizeof(self._buf))
        hdr_size = ctypes.sizeof(RAWINPUTHEADER)
        if user32.GetRawInputData(ctypes.c_void_p(lparam), RID_INPUT, self._buf,
                                  ctypes.byref(size), hdr_size) == 0xFFFFFFFF:
            return
        hdr = RAWINPUTHEADER.from_buffer_copy(self._buf)
        if hdr.dwType == 0:  # mouse
            m = RAWMOUSE.from_buffer_copy(self._buf, hdr_size)
            if not (m.usFlags & 1):  # movimiento relativo
                self._dx += m.lLastX
                self._dy += m.lLastY
            for flag, btn, state in _BTN:
                if m.usButtonFlags & flag:
                    self._flush_mouse()
                    self._write(type="mouse_btn", btn=btn, state=state)
            if m.usButtonFlags & 0x400:  # rueda
                self._write(type="wheel", delta=ctypes.c_short(m.usButtonData).value)
        elif hdr.dwType == 1:  # teclado
            k = RAWKEYBOARD.from_buffer_copy(self._buf, hdr_size)
            name = self.allowed.get(k.VKey)
            if not name:
                return
            up = bool(k.Flags & 1)
            if up:
                self._pressed.discard(k.VKey)
            elif k.VKey in self._pressed:
                return  # auto-repetición
            else:
                self._pressed.add(k.VKey)
            self._write(type="key", key=name, state="up" if up else "down")
