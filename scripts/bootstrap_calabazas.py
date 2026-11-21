"""Modelo provisional con pocas etiquetas a mano (data/propuestas) para proponer cajas en el resto de cuadros.
Uso: python scripts/bootstrap_calabazas.py [epocas]
Salida: runs/boot/weights/best.pt"""
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data" / "propuestas"
DST = ROOT / "data" / "boot_set"


def main() -> None:
    epochs = int(sys.argv[1]) if len(sys.argv) > 1 else 120
    if DST.exists():
        shutil.rmtree(DST)
    for kind in ("images", "labels"):
        (DST / kind / "train").mkdir(parents=True)
        for f in (SRC / kind).iterdir():
            shutil.copy2(f, DST / kind / "train" / f.name)
    (DST / "data.yaml").write_text(
        f"path: {DST.as_posix()}\ntrain: images/train\nval: images/train\nnames:\n  0: enemigo\n", encoding="utf-8")
    from ultralytics import YOLO
    YOLO("yolov8n.pt").train(data=str(DST / "data.yaml"), epochs=epochs, imgsz=960, batch=4,
                             project=str(ROOT / "runs"), name="boot", exist_ok=True, plots=False, workers=2,
                             degrees=0, fliplr=0.5, scale=0.5, mosaic=1.0, hsv_v=0.4)


if __name__ == "__main__":
    main()
