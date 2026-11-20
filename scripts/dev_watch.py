"""Auto-restart: relanza run.py cuando cambia algún .py/.yaml del proyecto.

Si cierras la ventana a mano, el vigilante termina también.
"""
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WATCH_DIRS = [ROOT / "src"]
WATCH_FILES = [ROOT / "run.py", ROOT / "config.yaml"]
EXTS = {".py", ".yaml"}


def snapshot() -> dict:
    files = list(WATCH_FILES)
    for d in WATCH_DIRS:
        files += [p for p in d.rglob("*") if p.suffix in EXTS and "__pycache__" not in p.parts]
    snap = {}
    for p in files:
        try:
            snap[p] = p.stat().st_mtime
        except OSError:
            pass
    return snap


def launch() -> subprocess.Popen:
    print("[dev_watch] iniciando interfaz…", flush=True)
    return subprocess.Popen([sys.executable, str(ROOT / "run.py")], cwd=str(ROOT))


def stop(proc: subprocess.Popen):
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


def main():
    proc, last = launch(), snapshot()
    try:
        while True:
            time.sleep(0.7)
            if proc.poll() is not None:
                print("[dev_watch] la ventana se cerró; saliendo.", flush=True)
                return
            now = snapshot()
            if now != last:
                last = now
                print("[dev_watch] cambio detectado, reiniciando…", flush=True)
                stop(proc)
                proc = launch()
    except KeyboardInterrupt:
        pass
    finally:
        stop(proc)


if __name__ == "__main__":
    main()
