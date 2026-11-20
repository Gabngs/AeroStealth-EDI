Agente de visión para AceOnline (farmeo en tierra)

Documento de contexto del proyecto. Versión 0.1 · 2026-11-20

1. Objetivo

Un agente que ve la pantalla del juego en vivo y actúa según lo que ve:

Detecta enemigos marcados.
Apunta moviendo el mouse (fija la mira y la suelta cuando conviene).
Usa habilidades para destruirlos.
Se desplaza con W/A/S/D (versión 1: solo en tierra; el modo aire con mouse queda para después).
Ciclo de sesión: juega 2–3 h → cierra el juego → espera 1–2 h → lo reabre.

Alcance de la v1: solo modo tierra.

3. Cómo "aprende": tres enfoques
Enfoque	Cómo aprende	Estado en este proyecto
Reglas	No aprende; se programa "si ves X, haz Y"	Fase inicial (decisión)
Imitación (behavior cloning)	Te ve jugar y copia tus acciones	Fase 4 (objetivo principal de aprendizaje)
Refuerzo / evolución (como el carro en la pista)	Prueba, recibe recompensa, mejora por generaciones	Solo como métrica y ajuste fino (ver 3.1)
3.1 Sobre el refuerzo sin reinicios

El ejemplo clásico del carro necesita reiniciar miles de veces. Aquí no se puede, pero sí se puede tomar qué tanto hace el agente como señal de calidad, sin reiniciar:

Enemigos eliminados por minuto, XP por minuto, drops, veces que usa habilidades, vida perdida.
Se leen de la pantalla (barra de XP/vida por color, contadores por OCR).
Usos:
Evaluar versiones del agente (¿la v2 mata más por minuto que la v1?).
Ajustar parámetros (orden de habilidades, distancia de ataque, ganancia del mouse) probando variantes por bloques de tiempo y quedándose con la mejor (un enfoque tipo bandit, no una red entrenada desde cero).
Más adelante, afinar la red de imitación con esa recompensa.

Entrenar una red profunda desde cero solo con refuerzo en vivo sería demasiado lento y arriesgado (morir muchas veces), por eso no es el camino principal.

4. Arquitectura
Captura (mss)
   ↓
Percepción (YOLO + color/plantillas)  → enemigos, marcas, vida, maná, cooldowns
   ↓
Decisión (reglas → luego red de imitación)  → estado: BUSCAR / APUNTAR / ATACAR / SOLTAR
   ↓
Control (pydirectinput)  → W/A/S/D, habilidades, mouse relativo con control proporcional
   ↓
Supervisor  → temporizador de sesión, kill switch, cerrar/abrir juego
Percepción con red neuronal: detector (YOLO nano) entrenado con capturas etiquetadas. Al inicio se puede usar detección por color de la marca para arrancar rápido.
Mouse: movimiento relativo (el juego captura el cursor). Se calcula el error entre la marca y el centro de la mira y se mueve proporcionalmente; es más preciso que dejar que una red lo adivine.
Máquina de estados: BUSCAR (moverse) → APUNTAR (centrar la marca) → ATACAR (habilidades según cooldown) → SOLTAR (enemigo muerto).
5. Lenguaje y herramientas

Python 3.10+ (el ecosistema de visión y aprendizaje está ahí).

Función	Librería
Captura de pantalla	mss
Visión clásica	opencv-python, numpy
Detector neuronal	ultralytics (YOLO) + PyTorch
Teclado/mouse hacia el juego	pydirectinput (los juegos suelen ignorar pyautogui)
Hotkeys / grabar input	keyboard, pynput
Cerrar/abrir procesos	psutil, subprocess
OCR de contadores (opcional)	easyocr o pytesseract
Interfaz gráfica	PySide6 + pyqtgraph (ver sección 6)
Seguimiento de entrenamiento	TensorBoard

Sistema: Windows, juego en modo ventana o ventana sin bordes (la pantalla completa exclusiva rompe la captura).

6. Interfaz gráfica (GUI)

Se quiere una interfaz para ver datos y cómo se comporta la red.

Recomendación: PySide6 + pyqtgraph (tiempo real, fluido). Alternativa más sencilla: Dear PyGui. Streamlit sirve para revisar resultados, pero no para tiempo real.

Paneles propuestos:

Vista en vivo: pantalla capturada con las detecciones dibujadas (cajas, confianza, objetivo actual).
Estado del agente: estado de la máquina, última acción, cooldowns, FPS, tiempo de sesión.
Métricas: kills/min, XP/min, vida, historial de la sesión.
Capas de la red: mapas de activación de las capas convolucionales (se obtienen con forward hooks de PyTorch) y mapa de calor Grad-CAM de "qué mira el modelo".
Controles: botón iniciar/pausar, kill switch visible, parámetros ajustables (ganancia del mouse, umbral de detección).
7. Datos: grabación de partidas

Para entrenar el detector y, más adelante, la imitación, se graba mientras el autor juega normalmente.

Capturas a ~5–10 fps, guardadas como .jpg reducidas.
Un registro .jsonl con: marca de tiempo, teclas presionadas, movimiento del mouse (dx, dy), clics.
Se etiquetan a mano unas 200–300 capturas (Roboflow o LabelImg) para el detector.
Nota técnica: si el juego captura el cursor, los deltas del mouse deben registrarse como movimiento relativo (entrada en bruto), no como posición absoluta.
8. Fases del proyecto
Fase	Entregable	Tiempo orientativo
0	Entorno listo, capturas de ejemplo, resolución y teclas definidas	20 min
1	Detector solo visual: dibuja las marcas sobre la pantalla, sin tocar nada	1 sesión
2	Control de mira + habilidades + W/A/S/D (máquina de estados)	1–2 sesiones
3	Supervisor: temporizador, kill switch, cerrar/abrir el juego	1 sesión
4	Grabador + GUI con capas de la red	2 sesiones
5	Imitación: red que aprende de las partidas grabadas	varias sesiones
6	Auto-login y regreso a la zona de farmeo tras reabrir	al final (frágil)

Primer paso inmediato: Fase 1 con capturas de enemigos marcados.

9. Seguridad y robustez
Kill switch global (ej. F12) que suelte todas las teclas y detenga el programa al instante.
Si no se reconoce nada en pantalla durante unos minutos, el agente se detiene solo (evita enviar teclas a ciegas).
El PC debe quedar sin suspensión ni bloqueo de pantalla (un bloqueo devuelve capturas negras).
Duraciones de sesión y espera aleatorias dentro de los rangos (2–3 h de juego, 1–2 h de pausa).
Antes de cerrar el juego, llevar al personaje a una zona segura.
La contraseña nunca se guarda en el script; que el launcher guarde la sesión.
10. Estructura sugerida del repositorio
aceonline-agent/
├── README.md
├── CONTEXTO.md
├── requirements.txt
├── config.yaml              # resolución, teclas, cooldowns, hotkeys
├── src/
│   ├── capture.py           # captura con mss
│   ├── perception/
│   │   ├── color_detector.py
│   │   └── yolo_detector.py
│   ├── decision/
│   │   ├── state_machine.py
│   │   └── imitation_policy.py   # fase 5
│   ├── control/
│   │   ├── input.py         # pydirectinput
│   │   └── aim.py           # control proporcional del mouse
│   ├── supervisor.py        # sesiones, cerrar/abrir juego
│   ├── recorder.py          # grabador de partidas
│   └── gui/
│       ├── main_window.py
│       └── layer_viewer.py  # activaciones y Grad-CAM
├── data/
│   ├── raw/                 # capturas + jsonl
│   └── labeled/
├── models/
└── tests/
11. Pendientes / información por reunir
[ ] Capturas con enemigos marcados (cerca, lejos, varios a la vez).
[ ] Resolución y modo de ventana.
[ ] Teclas de habilidades y sus cooldowns.
[ ] Cómo se fija la mira: ¿botón mantenido, clic o tecla?
[ ] Ruta del .exe/launcher y qué pantallas aparecen al abrir (login, servidor, personaje).
[ ] Confirmación por escrito del staff del servidor.
[ ] Qué datos del HUD servirán como recompensa (contador de kills, barra de XP, etc.).