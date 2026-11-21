"""Comprueba si el juego corre con más permisos (administrador) que este programa.
Si es así, Windows bloquea la entrada simulada (teclas, mouse) y la lectura de teclas hacia el juego."""
import ctypes
import os
import subprocess
from ctypes import wintypes

k = ctypes.windll.kernel32
a = ctypes.windll.advapi32
k.OpenProcess.restype = wintypes.HANDLE


def nivel(pid: int) -> str:
    h = k.OpenProcess(0x1000, False, pid)                       # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return "no se puede ni consultar (acceso denegado)"
    tok = wintypes.HANDLE()
    if not a.OpenProcessToken(h, 0x0008, ctypes.byref(tok)):
        return "token inaccesible: proceso de nivel superior (elevado o protegido)"
    el, sz = wintypes.DWORD(), wintypes.DWORD()
    a.GetTokenInformation(tok, 20, ctypes.byref(el), 4, ctypes.byref(sz))   # TokenElevation
    return "ELEVADO (administrador)" if el.value else "normal (no elevado)"


def main() -> None:
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq Engine.atm", "/FO", "CSV", "/NH"],
                         capture_output=True, text=True).stdout.strip()
    print("tasklist:", out)
    for line in out.splitlines():
        if "Engine" in line:
            pid = int(line.split(",")[1].strip('"'))
            print(f"Engine.atm (pid {pid}) -> {nivel(pid)}")
    print(f"Este Python (pid {os.getpid()}) -> {nivel(os.getpid())}")


if __name__ == "__main__":
    main()
