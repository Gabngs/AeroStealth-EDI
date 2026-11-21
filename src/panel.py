"""Mini panel de control del bot: Iniciar / Pausar / Cerrar. Va sobre la barra de título del juego (no tapa nada)
y NO roba el foco al hacer clic, así el juego sigue al frente."""
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QWidget

from .capture import find_hwnd
from .control import user32
from .overlay_widget import visible_rect

_STYLE = """
QWidget#panel { background: rgba(20, 24, 32, 235); border: 1px solid #3a4150; border-radius: 8px; }
QPushButton { color: white; border: 0; border-radius: 6px; padding: 4px 12px; font: bold 10pt 'Segoe UI'; }
QPushButton#start { background: #1f9d55; } QPushButton#start:hover { background: #27b866; }
QPushButton#pause { background: #c98a12; } QPushButton#pause:hover { background: #e0a020; }
QPushButton#close { background: #b3362f; } QPushButton#close:hover { background: #cf463e; }
QPushButton:disabled { background: #444b58; color: #9aa3b2; }
"""


class ControlPanel(QWidget):
    def __init__(self, cfg: dict, bot, quit_cb):
        super().__init__()
        self.cfg, self.bot, self.quit_cb = cfg, bot, quit_cb
        self.setObjectName("panel")
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setStyleSheet(_STYLE)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(6, 4, 6, 4)
        lay.setSpacing(6)
        self.b_start = self._button("▶ Iniciar", "start", self.on_start)
        self.b_pause = self._button("⏸ Pausar", "pause", self.on_pause)
        self.b_close = self._button("✕ Cerrar", "close", self.on_close)
        for b in (self.b_start, self.b_pause, self.b_close):
            lay.addWidget(b)
        self.resize(300, 36)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(100)

    def _button(self, text: str, name: str, slot) -> QPushButton:
        b = QPushButton(text)
        b.setObjectName(name)
        b.setFocusPolicy(Qt.NoFocus)                      # el clic no activa el panel: el foco sigue en el juego
        b.clicked.connect(slot)
        return b

    # ---- acciones ----
    def on_start(self) -> None:
        self.bot.toggle.running = True
        self.bot.log("[PANEL] Bot INICIADO")

    def on_pause(self) -> None:
        self.bot.toggle.running = False
        self.bot.log("[PANEL] Bot DETENIDO")

    def on_close(self) -> None:
        self.bot.log("[PANEL] Cerrando el programa.")
        self.quit_cb()

    # ---- seguimiento de la ventana del juego ----
    def tick(self) -> None:
        hwnd = find_hwnd(self.cfg["capture"])
        if not hwnd or user32.IsIconic(hwnd):
            self.hide()
            self.bot.panel_rect = None
            return
        x, y, w, h = visible_rect(hwnd)
        dpr = self.screen().devicePixelRatio()
        # centrado sobre la barra de título del juego (los ~38 px de arriba)
        self.move(round((x + w / 2) / dpr - self.width() / 2), round((y + 2) / dpr))
        if not self.isVisible():
            self.show()
        g = self.geometry()
        self.bot.panel_rect = (g.x() * dpr, g.y() * dpr, (g.x() + g.width()) * dpr, (g.y() + g.height()) * dpr)
        running = self.bot.toggle.running
        self.b_start.setEnabled(not running)
        self.b_pause.setEnabled(running)
