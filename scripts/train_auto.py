"""Entrena YOLO con data/auto (+ data/labeled si existe). Parte las imágenes por bloques contiguos
(los cuadros seguidos son casi iguales; mezclarlos inflaría la validación).
Uso: python scripts/train_auto.py [epochs] [carpeta en data/, por defecto auto] [imgsz] [nombre]"""
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DST = ROOT / "data" / "train_set"


def main() -> None:
    epochs = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    src = ROOT / "data" / (sys.argv[2] if len(sys.argv) > 2 else "auto")
    imgsz = int(sys.argv[3]) if len(sys.argv) > 3 else 640
    run = sys.argv[4] if len(sys.argv) > 4 else "auto"
    if DST.exists():
        shutil.rmtree(DST)
    imgs = sorted((src / "images").glob("*.jpg"))
    block = 20
    for i, f in enumerate(imgs):
        split = "val" if (i // block) % 6 == 5 else "train"
        for kind, ext in (("images", ".jpg"), ("labels", ".txt")):
            d = DST / kind / split
            d.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src / kind / (f.stem + ext), d / (f.stem + ext))
    (DST / "data.yaml").write_text(
        f"path: {DST.as_posix()}\ntrain: images/train\nval: images/val\nnames:\n  0: enemigo\n", encoding="utf-8")
    from ultralytics import YOLO
    YOLO("yolov8n.pt").train(data=str(DST / "data.yaml"), epochs=epochs, imgsz=imgsz, batch=4 if imgsz > 700 else 8,
                             project=str(ROOT / "runs"), name=run, exist_ok=True, plots=False, workers=2)


if __name__ == "__main__":
    main()
