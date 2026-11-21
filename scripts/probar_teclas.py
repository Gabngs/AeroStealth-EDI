"""Comprueba qué métodos ven las teclas y botones con el juego al frente (3 métodos a la vez).
Uso: python scripts/probar_teclas.py [segundos]   -> trae el juego al frente y escucha; pulsa . + w espacio"""
import ctypes
import sys
import threading
import time
import winsound
from ctypes import wintypes
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.capture import find_hwnd  # noqa: E402
from src.config import load_config  # noqa: E402

u = ctypes.windll.user32
k32 = ctypes.windll.kernel32
HOOKPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
u.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD]
u.SetWindowsHookExW.restype = wintypes.HHOOK
u.CallNextHookEx.argtypes = [wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
u.CallNextHookEx.restype = ctypes.c_ssize_t
u.CreateWindowExW.restype = wintypes.HWND
u.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_int,
                              ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HWND, wintypes.HMENU,
                              wintypes.HINSTANCE, wintypes.LPVOID]


class KB(ctypes.Structure):
    _fields_ = [("vk", wintypes.DWORD), ("scan", wintypes.DWORD), ("flags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("extra", ctypes.c_size_t)]


class RID(ctypes.Structure):
    _fields_ = [("page", wintypes.USHORT), ("usage", wintypes.USHORT), ("flags", wintypes.DWORD), ("target", wintypes.HWND)]


class RIH(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("size", wintypes.DWORD), ("dev", wintypes.HANDLE), ("wp", wintypes.WPARAM)]


class RKB(ctypes.Structure):
    _fields_ = [("make", wintypes.USHORT), ("flags", wintypes.USHORT), ("res", wintypes.USHORT),
                ("vk", wintypes.USHORT), ("msg", wintypes.UINT), ("extra", wintypes.ULONG)]


class RIN(ctypes.Structure):
    _fields_ = [("h", RIH), ("kb", RKB)]


PITCH = {"async": 700, "raw": 1300, "hook": 2000}     # cada método suena distinto
IMPORTANT = {0xBE, 0xBB, 0x6E, 0x6B, 0x57, 0x20}       # . + (numéricos) w espacio


def say(method: str, vk: int) -> None:
    print(f"{time.strftime('%H:%M:%S')}  [{method:5}] vk=0x{vk:02X}", flush=True)
    if vk in IMPORTANT:                                  # pitido, para saber sin mirar la pantalla que llegó
        threading.Thread(target=lambda: winsound.Beep(PITCH[method], 140), daemon=True).start()


def ll_hook() -> None:
    def proc(n, w, lp):
        if n == 0 and w in (0x100, 0x104):
            say("hook", ctypes.cast(lp, ctypes.POINTER(KB)).contents.vk)
        return u.CallNextHookEx(None, n, w, lp)
    cb = HOOKPROC(proc)
    u.SetWindowsHookExW(13, cb, k32.GetModuleHandleW(None), 0)
    m = wintypes.MSG()
    while u.GetMessageW(ctypes.byref(m), None, 0, 0) > 0:
        u.DispatchMessageW(ctypes.byref(m))


def raw_input() -> None:
    hwnd = u.CreateWindowExW(0, "STATIC", "raw", 0, 0, 0, 0, 0, wintypes.HWND(-3), None, k32.GetModuleHandleW(None), None)
    rid = RID(1, 6, 0x100, hwnd)
    u.RegisterRawInputDevices(ctypes.byref(rid), 1, ctypes.sizeof(rid))
    m = wintypes.MSG()
    while u.GetMessageW(ctypes.byref(m), None, 0, 0) > 0:
        if m.message == 0x00FF:
            r = RIN()
            sz = wintypes.UINT(ctypes.sizeof(r))
            if u.GetRawInputData(m.lParam, 0x10000003, ctypes.byref(r), ctypes.byref(sz), ctypes.sizeof(RIH)) != -1 \
                    and r.h.type == 1 and not r.kb.flags & 1:
                say("raw", r.kb.vk)
        u.DispatchMessageW(ctypes.byref(m))


def main() -> None:
    secs = int(sys.argv[1]) if len(sys.argv) > 1 else 90
    threading.Thread(target=ll_hook, daemon=True).start()
    threading.Thread(target=raw_input, daemon=True).start()
    time.sleep(0.5)
    hwnd = find_hwnd(load_config()["capture"])
    if hwnd:
        u.ShowWindow(hwnd, 9)
        u.SetForegroundWindow(hwnd)
    print(f"Escuchando {secs} s con 3 métodos. Con el juego al frente pulsa:  .   +   w   espacio", flush=True)
    prev, end = set(), time.time() + secs
    while time.time() < end:
        cur = {k for k in range(8, 255) if u.GetAsyncKeyState(k) & 0x8000 and k not in (1, 2)}
        for k in cur - prev:
            say("async", k)
        prev = cur
        time.sleep(0.005)
    print("fin", flush=True)


if __name__ == "__main__":
    main()
