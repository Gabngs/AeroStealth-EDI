"""Lista las ventanas abiertas con el nombre de su proceso, para rellenar
capture.process_name en config.yaml (abre el juego y ejecuta esto)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.capture import list_windows  # noqa: E402

if __name__ == "__main__":
    for w in sorted(list_windows(), key=lambda w: w["exe"].lower()):
        print(f"{w['exe']:<28} {w['w']}x{w['h']:<6} {w['title'][:60]}")
