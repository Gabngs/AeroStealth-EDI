import os
import sys
import time

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QKeySequence, QPainter, QPen, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel,
    QMainWindow, QPlainTextEdit, QPushButton, QSpinBox, QSplitter, QVBoxLayout, QWidget,
)

from ..config import load_config
from ..dataset import Dataset
from ..input_recorder import InputRecorder
from ..trainer import Trainer
from ..worker import CaptureWorker

STYLE = """
QWidget { background: #14171c; color: #d8dee9; font-size: 13px; }
QGroupBox { border: 1px solid #2b313b; border-radius: 6px; margin-top: 10px; padding: 8px; }
QGroupBox::title { subcontrol-origin: margin; left: 10px; color: #7aa2f7; }
QPushButton { background: #232a35; border: 1px solid #343c4a; border-radius: 4px; padding: 6px 10px; }
QPushButton:hover { background: #2d3644; }
QPushButton:checked { background: #b5403a; }
QPlainTextEdit { background: #0e1115; border: 1px solid #2b313b; font-family: Consolas, monospace; }
QComboBox, QSpinBox, QDoubleSpinBox { background: #232a35; border: 1px solid #343c4a; padding: 3px; }
"""


def to_qimage(frame: np.ndarray) -> QImage:
    h, w = frame.shape[:2]
    return QImage(frame.data, w, h, 3 * w, QImage.Format_BGR888).copy()


def rgb_to_qimage(img: np.ndarray) -> QImage:
    h, w = img.shape[:2]
    return QImage(img.data, w, h, 3 * w, QImage.Format_RGB888).copy()


class FrameView(QWidget):
    """Muestra el frame con cajas. Congelado: arrastrar = caja nueva, clic derecho = quitar falsa."""

    freezeRequested = Signal()

    def __init__(self, class_names):
        super().__init__()
        self.class_names = class_names
        self.current_class = 0
        self.image: QImage | None = None
        self.boxes: list[dict] = []
        self.frozen = False
        self._start = self._now = None
        self.setMinimumSize(480, 270)

    def set_frame(self, qimg, boxes):
        self.image, self.boxes = qimg, boxes
        self.update()

    def _geom(self):
        iw, ih = self.image.width(), self.image.height()
        s = min(self.width() / iw, self.height() / ih)
        return s, (self.width() - iw * s) / 2, (self.height() - ih * s) / 2

    def _to_img(self, p: QPointF):
        s, ox, oy = self._geom()
        return (p.x() - ox) / s, (p.y() - oy) / s

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.fillRect(self.rect(), QColor("#0e1115"))
        if self.image is None:
            p.setPen(QColor("#6b7380"))
            p.drawText(self.rect(), Qt.AlignCenter, "Esperando captura…")
            return
        s, ox, oy = self._geom()
        p.drawImage(QRectF(ox, oy, self.image.width() * s, self.image.height() * s), self.image)
        for b in self.boxes:
            x1, y1, x2, y2 = b["xyxy"]
            color = QColor("#9ece6a") if b["src"] == "model" else QColor("#2ac3de")
            p.setPen(QPen(color, 2))
            r = QRectF(ox + x1 * s, oy + y1 * s, (x2 - x1) * s, (y2 - y1) * s)
            p.drawRect(r)
            name = self.class_names[b["cls"]] if b["cls"] < len(self.class_names) else str(b["cls"])
            label = name if b["src"] == "user" else f"{name} {b['conf']:.0%}"
            p.drawText(r.topLeft() + QPointF(2, -4), label)
        cx, cy = ox + self.image.width() * s / 2, oy + self.image.height() * s / 2
        p.setPen(QPen(QColor("#f7768e"), 1))
        p.drawLine(QPointF(cx - 8, cy), QPointF(cx + 8, cy))
        p.drawLine(QPointF(cx, cy - 8), QPointF(cx, cy + 8))
        if self._start and self._now:
            p.setPen(QPen(QColor("#e0af68"), 2, Qt.DashLine))
            p.drawRect(QRectF(self._start, self._now).normalized())
        if self.frozen:
            p.setPen(QPen(QColor("#e0af68"), 3))
            p.drawRect(self.rect().adjusted(1, 1, -2, -2))
            p.drawText(10, 20, "CONGELADO · arrastra = caja correcta · clic der. = falso positivo · Enter = guardar · Esc = descartar")

    def mousePressEvent(self, e):
        if self.image is None:
            return
        if not self.frozen:
            self.freezeRequested.emit()
            return
        if e.button() == Qt.LeftButton:
            self._start = self._now = e.position()
        elif e.button() == Qt.RightButton:
            x, y = self._to_img(e.position())
            for b in reversed(self.boxes):
                x1, y1, x2, y2 = b["xyxy"]
                if x1 <= x <= x2 and y1 <= y <= y2:
                    self.boxes.remove(b)
                    self.update()
                    break

    def mouseMoveEvent(self, e):
        if self._start:
            self._now = e.position()
            self.update()

    def mouseReleaseEvent(self, e):
        if self._start and e.button() == Qt.LeftButton:
            x1, y1 = self._to_img(self._start)
            x2, y2 = self._to_img(e.position())
            self._start = self._now = None
            x1, x2 = sorted((x1, x2))
            y1, y2 = sorted((y1, y2))
            iw, ih = self.image.width(), self.image.height()
            x1, x2 = max(0, x1), min(iw, x2)
            y1, y2 = max(0, y1), min(ih, y2)
            if x2 - x1 > 5 and y2 - y1 > 5:
                self.boxes.append({"cls": self.current_class, "conf": 1.0,
                                   "xyxy": [x1, y1, x2, y2], "src": "user"})
            self.update()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.cfg = load_config()
        self.classes = self.cfg["classes"]
        self.dataset = Dataset(self.cfg)
        self.setWindowTitle("AeroStealth-EDI · Agente de visión")
        self.resize(1400, 860)

        self.last_frame = None
        self.frozen_frame = None
        self.frozen_model_boxes: list[dict] = []
        self.trainer: Trainer | None = None
        self._was_locked = False
        self._prev_count = 0

        # ---------- Columna izquierda: modelo (arriba) + log (abajo) ----------
        self.view = FrameView(self.classes)
        self.view.freezeRequested.connect(self.freeze)
        self.layer_labels = [QLabel("") for _ in range(4)]
        layers_row = QHBoxLayout()
        for lb in self.layer_labels:
            lb.setAlignment(Qt.AlignCenter)
            lb.setMinimumHeight(90)
            layers_row.addWidget(lb)
        self.layers_hint = QLabel("Capas de la red: aparecerán al usar el detector YOLO entrenado.")
        self.layers_hint.setStyleSheet("color:#6b7380")
        top = QWidget()
        tl = QVBoxLayout(top)
        tl.setContentsMargins(0, 0, 0, 0)
        tl.addWidget(self.view, 1)
        tl.addWidget(self.layers_hint)
        tl.addLayout(layers_row)

        self.log = QPlainTextEdit(readOnly=True)
        self.log.setMaximumBlockCount(2000)
        left = QSplitter(Qt.Vertical)
        left.addWidget(top)
        left.addWidget(self.log)
        left.setStretchFactor(0, 4)
        left.setStretchFactor(1, 1)

        # ---------- Columna derecha: detalles ----------
        right = QWidget()
        rl = QVBoxLayout(right)

        g = QGroupBox("Estado")
        f = QFormLayout(g)
        self.lbl_fps, self.lbl_raw, self.lbl_lab = QLabel("-"), QLabel("0"), QLabel(str(self.dataset.labeled_count))
        self.lbl_det, self.lbl_inp = QLabel("0"), QLabel("0")
        f.addRow("FPS", self.lbl_fps)
        f.addRow("Detecciones", self.lbl_det)
        f.addRow("Capturas de la sesión", self.lbl_raw)
        f.addRow("Eventos teclado/mouse", self.lbl_inp)
        f.addRow("Correcciones", self.lbl_lab)
        rl.addWidget(g)

        g = QGroupBox("Captura automática")
        v = QVBoxLayout(g)
        self.btn_rec = QPushButton("● Grabar sesión (F9)")
        self.btn_rec.setCheckable(True)
        self.btn_rec.toggled.connect(self.toggle_rec)
        self.btn_folder = QPushButton("Abrir carpeta de la sesión")
        self.btn_folder.clicked.connect(self.open_session_folder)
        self.spin_fps = QSpinBox(minimum=1, maximum=30, value=self.cfg["record"]["fps"])
        self.spin_fps.valueChanged.connect(lambda x: setattr(self.worker, "record_fps", x))
        row = QHBoxLayout()
        row.addWidget(QLabel("Capturas/seg"))
        row.addWidget(self.spin_fps)
        v.addWidget(self.btn_rec)
        v.addWidget(self.btn_folder)
        v.addLayout(row)
        rl.addWidget(g)

        g = QGroupBox("Detector")
        f = QFormLayout(g)
        self.cmb_det = QComboBox()
        self.cmb_det.addItems(["none", "color", "yolo"])
        self.cmb_det.setCurrentText(self.cfg["detector"]["kind"])
        self.cmb_det.currentTextChanged.connect(self.set_detector)
        self.spin_conf = QDoubleSpinBox(minimum=0.05, maximum=0.95, singleStep=0.05,
                                        value=self.cfg["detector"]["conf"])
        self.spin_conf.valueChanged.connect(lambda x: setattr(self.worker, "conf", x))
        f.addRow("Tipo", self.cmb_det)
        f.addRow("Confianza", self.spin_conf)
        rl.addWidget(g)

        g = QGroupBox("Corrección (tú le enseñas)")
        v = QVBoxLayout(g)
        self.cmb_cls = QComboBox()
        self.cmb_cls.addItems(self.classes)
        self.cmb_cls.currentIndexChanged.connect(lambda i: setattr(self.view, "current_class", i))
        self.btn_freeze = QPushButton("Congelar (Espacio)")
        self.btn_freeze.clicked.connect(self.toggle_freeze)
        self.btn_save = QPushButton("Guardar corrección (Enter)")
        self.btn_save.clicked.connect(self.save_correction)
        self.btn_discard = QPushButton("Descartar (Esc)")
        self.btn_discard.clicked.connect(self.unfreeze)
        v.addWidget(QLabel("Clase a dibujar"))
        v.addWidget(self.cmb_cls)
        for b in (self.btn_freeze, self.btn_save, self.btn_discard):
            v.addWidget(b)
        rl.addWidget(g)

        g = QGroupBox("Entrenamiento")
        v = QVBoxLayout(g)
        self.btn_train = QPushButton("Entrenar con mis correcciones")
        self.btn_train.clicked.connect(self.start_training)
        v.addWidget(self.btn_train)
        rl.addWidget(g)
        rl.addStretch(1)

        split = QSplitter(Qt.Horizontal)
        split.addWidget(left)
        split.addWidget(right)
        split.setStretchFactor(0, 4)
        split.setStretchFactor(1, 1)
        self.setCentralWidget(split)

        # ---------- Atajos ----------
        for key, fn in (("Space", self.toggle_freeze), ("Return", self.save_correction),
                        ("Esc", self.unfreeze)):
            QShortcut(QKeySequence(key), self, activated=fn)
        for i in range(min(len(self.classes), 9)):
            QShortcut(QKeySequence(str(i + 1)), self, activated=lambda i=i: self.cmb_cls.setCurrentIndex(i))

        # ---------- Worker ----------
        self.worker = CaptureWorker(self.cfg, self.dataset)
        self.worker.result.connect(self.on_result)
        self.worker.message.connect(self.say)
        self.worker.start()

        # ---------- Registro de teclado/mouse (Raw Input) ----------
        self.input_rec = InputRecorder(int(self.winId()), self.cfg.get("controls", {}),
                                       self.dataset.elapsed_ms, self.btn_rec.toggle)
        QApplication.instance().installNativeEventFilter(self.input_rec)
        self.say(f"Interfaz lista. Detector: {self.worker.kind}.")
        self.say("Registro teclado/mouse: " + ("OK" if self.input_rec.ok else "FALLÓ")
                 + " · Atajo global F9: " + ("OK" if self.input_rec.hotkey_ok else "no disponible (¿otra app lo usa?)"))

    # ---------- utilidades ----------
    def say(self, text: str):
        self.log.appendPlainText(f"[{time.strftime('%H:%M:%S')}] {text}")

    def toggle_rec(self, on: bool):
        if on:
            folder = self.dataset.start_session()
            self.input_rec.start(folder / "inputs.jsonl")
            self.worker.recording = True
            self.say(f"GRABANDO sesión {self.dataset.session} → {folder}")
        else:
            self.worker.recording = False
            self.input_rec.stop()
            self.say(f"Grabación detenida: {self.dataset.raw_count} capturas, "
                     f"{self.input_rec.count} eventos de teclado/mouse")
        self.btn_rec.setText("■ Detener grabación (F9)" if on else "● Grabar sesión (F9)")

    def open_session_folder(self):
        folder = self.dataset.session_dir
        if folder and folder.exists():
            os.startfile(folder)
        else:
            self.say("La sesión actual aún no tiene archivos.")

    def set_detector(self, kind: str):
        self.worker.kind = kind
        if kind == "yolo":
            self.worker.yolo.reload()
        self.say(f"Detector → {kind}")

    # ---------- flujo en vivo ----------
    def on_result(self, frame, dets, layers, fps):
        self.last_frame = frame
        self.lbl_fps.setText(f"{fps:.0f}")
        self.lbl_raw.setText(str(self.dataset.raw_count))
        self.lbl_inp.setText(str(self.input_rec.count))
        if self.view.frozen:
            return
        boxes = [d.to_box() for d in dets]
        self.view.set_frame(to_qimage(frame), boxes)
        self.lbl_det.setText(str(len(boxes)))
        self._track_events(boxes, frame.shape[1], frame.shape[0])
        self._show_layers(layers)

    def _track_events(self, boxes, w, h):
        n = len(boxes)
        if n and not self._prev_count:
            self.say(f"Enemigo detectado ({n})")
        elif not n and self._prev_count:
            self.say("Enemigo perdido de vista")
        self._prev_count = n
        cx, cy = w / 2, h / 2
        locked = any(b["xyxy"][0] <= cx <= b["xyxy"][2] and b["xyxy"][1] <= cy <= b["xyxy"][3] for b in boxes)
        if locked != self._was_locked:
            self.say("Enemigo fijado (en la mira)" if locked else "Fijado liberado")
            self._was_locked = locked

    def _show_layers(self, layers):
        if not layers:
            return
        self.layers_hint.setText("Capas de la red (canales con más actividad)")
        for lb, img in zip(self.layer_labels, layers):
            pm = QPixmap.fromImage(rgb_to_qimage(img)).scaledToWidth(220, Qt.SmoothTransformation)
            lb.setPixmap(pm)

    # ---------- corrección ----------
    def toggle_freeze(self):
        self.unfreeze() if self.view.frozen else self.freeze()

    def freeze(self):
        if self.view.frozen or self.last_frame is None:
            return
        self.frozen_frame = self.last_frame.copy()
        self.frozen_model_boxes = [dict(b) for b in self.view.boxes if b["src"] == "model"]
        self.view.frozen = True
        self.view.update()
        self.say("Cuadro congelado: corrige y pulsa Enter")

    def unfreeze(self):
        if not self.view.frozen:
            return
        self.view.frozen = False
        self.frozen_frame = None

    def save_correction(self):
        if not self.view.frozen or self.frozen_frame is None:
            return
        kept = [b for b in self.view.boxes if b["src"] == "model"]
        added = [b for b in self.view.boxes if b["src"] == "user"]
        removed = len(self.frozen_model_boxes) - len(kept)
        self.dataset.save_labeled(self.frozen_frame, self.view.boxes)
        self.lbl_lab.setText(str(self.dataset.labeled_count))
        self.say(f"Corrección guardada: +{len(added)} cajas tuyas, −{removed} falsos positivos, "
                 f"{len(kept)} aciertos del modelo")
        self.unfreeze()

    # ---------- entrenamiento ----------
    def start_training(self):
        if self.trainer and self.trainer.isRunning():
            return
        if self.dataset.labeled_count < 10:
            self.say(f"Pocas correcciones ({self.dataset.labeled_count}); se recomiendan 100+ para algo útil.")
        self.btn_train.setEnabled(False)
        self.say("Entrenando… (puede tardar; el log muestra el avance)")
        self.trainer = Trainer(self.cfg, self.dataset.yaml_path)
        self.trainer.line.connect(self.say)
        self.trainer.finished_ok.connect(self._train_done)
        self.trainer.start()

    def _train_done(self, ok: bool):
        self.btn_train.setEnabled(True)
        if ok:
            self.worker.yolo.reload()
            self.cmb_det.setCurrentText("yolo")
            self.say("Entrenamiento terminado: modelo nuevo en models/best.pt (detector → yolo)")
        else:
            self.say("El entrenamiento falló; revisa el log.")

    def closeEvent(self, e):
        self.input_rec.stop()
        self.worker.stop()
        super().closeEvent(e)


def main():
    app = QApplication(sys.argv)
    app.setStyleSheet(STYLE)
    w = MainWindow()
    w.show()
    sys.exit(app.exec())
