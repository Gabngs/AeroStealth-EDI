"""Visor en vivo: captura el juego, pasa el modelo YOLO y dibuja lo que detecta en una ventana.
Uso: python scripts/ver_deteccion.py [pesos] [confianza]
Se cierra con Q o Esc en la ventana, o con el botón de parada (controls.killswitch)."""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cv2  # noqa: E402
from ultralytics import YOLO  # noqa: E402

from src.capture import ScreenCapture  # noqa: E402
from src.config import ROOT, load_config  # noqa: E402
from src.killswitch import start_killswitch  # noqa: E402


def main() -> None:
    cfg = load_config()
    start_killswitch(cfg["controls"].get("killswitch", "xbutton2"))
    weights = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "runs" / "auto" / "weights" / "best.pt"
    conf = float(sys.argv[2]) if len(sys.argv) > 2 else 0.4
    model = YOLO(str(weights))
    cap = ScreenCapture(cfg["capture"])
    win = "AeroStealth - lo que ve el modelo"
    cv2.namedWindow(win, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(win, 1280, 720)
    fps, last = 0.0, time.time()
    try:
        while True:
            try:
                frame = cap.grab()
            except RuntimeError:
                time.sleep(0.1)
                continue
            r = model.predict(frame, conf=conf, imgsz=640, verbose=False)[0]
            out = r.plot(line_width=3)
            now = time.time()
            fps = 0.9 * fps + 0.1 / max(now - last, 1e-6)
            last = now
            n = len(r.boxes)
            cv2.putText(out, f"detecciones: {n}   {fps:.0f} fps   conf>={conf}", (20, 70),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 0), 2)
            cv2.imshow(win, out)
            if cv2.waitKey(1) & 0xFF in (ord("q"), 27):
                break
    finally:
        cap.close()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
