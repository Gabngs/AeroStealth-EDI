import shutil
import subprocess
import sys

from PySide6.QtCore import QThread, Signal

from .config import ROOT

_SCRIPT = """
import sys
from ultralytics import YOLO
base, data, epochs, imgsz, project = sys.argv[1:6]
YOLO(base).train(data=data, epochs=int(epochs), imgsz=int(imgsz), project=project,
                 name="run", exist_ok=True, plots=False)
"""


class Trainer(QThread):
    """Ajusta YOLO con las correcciones guardadas. Parte de best.pt si ya existe."""

    line = Signal(str)
    finished_ok = Signal(bool)

    def __init__(self, cfg: dict, data_yaml):
        super().__init__()
        self.cfg, self.data_yaml = cfg, data_yaml

    def run(self):
        t = self.cfg["train"]
        best = ROOT / self.cfg["detector"]["yolo_weights"]
        base = str(best) if best.exists() else t["base_model"]
        project = ROOT / "runs"
        cmd = [sys.executable, "-c", _SCRIPT, base, str(self.data_yaml),
               str(t["epochs"]), str(t["imgsz"]), str(project)]
        try:
            p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                 text=True, encoding="utf-8", errors="replace",
                                 cwd=str(ROOT), env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"})
            for ln in p.stdout:
                ln = ln.strip()
                if ln:
                    self.line.emit(ln[-200:])
            p.wait()
            out = project / "run" / "weights" / "best.pt"
            if p.returncode == 0 and out.exists():
                best.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(out, best)
                self.finished_ok.emit(True)
                return
        except Exception as e:  # noqa: BLE001
            self.line.emit(f"Error al entrenar: {e}")
        self.finished_ok.emit(False)
