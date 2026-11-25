# Diseño de la red de decisión y del entrenamiento en vivo

Estado: **diseño, sin implementar**. Complementa `plan_mejora_bot.md` (Fases 3 y 4).
Este documento sirve para retomar el trabajo en otra PC / otra sesión: contiene lo decidido y lo que falta por responder.

## 1. Objetivo

1. **Percepción** separada de la **decisión**. YOLO y el HUD dicen *qué hay*; una red neuronal mediana decide *qué hacer* (a quién atacar, Siege, recarga, buffs, moverse/buscar).
2. Entrenamiento **en vivo y guiado por humano**, no autónomo (ver sección 4).
3. Ir por partes: el mapa de calabazas (marcar, disparar, buscar) ya funciona con reglas y se queda así. La red empieza por una decisión acotada y se amplía.

## 2. Percepción: un solo detector de «enemigo»

No se cataloga cada especie. El juego da la etiqueta: si la mira se posa sobre algo y aparecen flechas verdes + barra de vida, es un enemigo.

- Un **generador de candidatos** propone objetos que se mueven o destacan (el movimiento es solo una pista; hay que restar el movimiento global por cámara/personaje).
- El bot lleva la mira a cada candidato. Si se fija → recorte etiquetado «enemigo»; si no → «no enemigo».
- YOLO se reentrena con **una clase** («enemigo») usando esos recortes, con revisión humana en la interfaz.

## 3. Entradas y salidas de la red

Los **pesos** de la red los aprende el entrenamiento. Lo que se define aquí son las **entradas** (indicadores) y las **salidas**.

### Entradas por enemigo candidato
| Entrada | Valores | Fuente |
|---|---|---|
| distancia a la mira | px normalizados | YOLO + mira |
| ángulo a la mira | -1..1 | YOLO + mira |
| velocidad del objetivo | px/s | tracker / flechas verdes |
| fijado | 0/1 | flechas verdes + barra de vida |
| **agro sobre mí** | 0 = nada, 0,5 = una flecha (duda), 1 = dos flechas | **por definir (hud.py)** |
| vida del objetivo | 0..1 | barra de vida |
| tipo de daño que hace | por definir | por definir |

### Entradas del estado propio
- Munición (estándar y avanzada) y munición vacía.
- Calor del arma.
- Skills listas / en reuso (Fase 1c).
- Vida propia y su caída reciente (= daño recibido).
- Número de enemigos con agro sobre mí.
- Tiempo sin objetivo; Siege activo.

### Salidas
- Puntuación por candidato (a quién atacar).
- Activar/desactivar Siege.
- Recargar.
- Lanzar buff (cuál).
- Moverse / buscar (dirección).

### Regla del agro
Con **una sola flecha** no se descarta: se trata como duda (0,5) y la red debe priorizar **validarlo** (vigilarlo o fijarlo) antes de ignorarlo. Con dos flechas (1) se prioriza para que no haga daño.

## 4. Entrenamiento en vivo con humano en el bucle

Sí es posible. Es *imitación interactiva* (human-in-the-loop, estilo DAgger), no aprendizaje por refuerzo autónomo.

**Ciclo de sesión (2 a 5 min):**
1. **Sesión.** El bot juega y registra por cada ciclo: entradas, decisión tomada y **latencia de decisión** (cuánto tardó en decidir).
2. **Pausa.** Se detiene. Se revisa la sesión en la interfaz (línea de tiempo con las decisiones).
3. **Corrección.** El humano marca decisiones erróneas y la correcta («aquí debía atacar a este», «aquí tocaba recargar», «este tenía agro»).
4. **Entrenamiento corto.** La red se reentrena con los datos acumulados (la primera vez, imitando a las reglas actuales).
5. **Nueva sesión** con la red actualizada. Se repite.

**Reglas del proceso**
- La red **no entrena sola**: solo entrena tras una corrección humana.
- Las reglas actuales actúan de **red de seguridad** (killswitch, calor, anti-AFK, límites) y de **maestro inicial**.
- Se guardan versiones de pesos por sesión; si una sesión empeora, se vuelve a la anterior.
- Se compara cada sesión con las anteriores (kills/min, daño recibido, latencia de decisión) con `metrics.py`.

**Límites a tener en cuenta**
- Pocos minutos de datos por sesión: la red empieza **pequeña/mediana** y crece cuando haya datos suficientes; con poca data una red grande memoriza.
- El primer entrenamiento solo puede igualar a las reglas; la mejora real viene de las correcciones y luego del ajuste por fitness.
- Las salidas de «moverse/buscar» son las más difíciles; se dejan para el final.

## 5. Orden de trabajo

1. Registrar en `metrics.py` el vector de entradas + decisión + latencia en cada ciclo (sin cambiar el comportamiento).
2. Leer el **agro** en `hud.py` (necesita las capturas de la sección 6).
3. Interfaz: línea de tiempo de la sesión + botones de corrección (ya existe el flujo de «congelar / corregir / guardar» para YOLO; reutilizarlo).
4. `src/decision_net.py` (numpy, pesos en `.npz`) + visor de nodos y pesos en la interfaz.
5. Primera decisión acotada: **a quién atacar primero según agro y distancia**.
6. Generador de candidatos + clase «enemigo» para el segundo mapa (enemigos repartidos y en movimiento).

## 6. Preguntas abiertas (responder en la otra PC)

**Capturas que hacen falta**
- [ ] Una captura con **una** flecha de agro junto al nombre.
- [ ] Una captura con **dos** flechas de agro.
- [ ] Una captura de un enemigo **fijado** (flechas verdes + barra) para comparar con las de agro.
- [ ] Una captura de la barra de vida propia, antes y después de recibir daño.
- [ ] Una captura del segundo mapa (enemigos en movimiento y repartidos).

**Datos**
1. ¿Las flechas de agro se distinguen de las flechas verdes de fijado por **color** o por **forma/posición**? ¿De qué color son?
2. ¿Qué indica «una flecha» frente a «dos flechas»: nivel de agro, tipo de ataque, o que está cargando?
3. ¿Cómo se sabe que un enemigo hizo daño: barra de vida propia, números flotantes, o ambos?
4. ¿Cada tipo de enemigo hace un daño distinto (el «x daño»)? ¿Se puede leer de algún sitio o hay que aprenderlo?
5. ¿La barra de vida propia está siempre visible? ¿En qué región?
6. En el segundo mapa: ¿los enemigos atacan a distancia o cuerpo a cuerpo? ¿Hay que moverse para esquivar?
7. ¿La escena de pruebas del primer mapa va a ser siempre la misma para poder comparar sesiones?

**Decisiones**
8. ¿Qué cuenta como «mala decisión» al corregir: tardar demasiado, elegir al equivocado, no reaccionar al agro, recargar tarde?
9. ¿Se quiere medir la latencia de decisión como tiempo entre «aparece el estímulo» y «ejecuta la acción»?

## 7. Seguimiento y velocidad (notas de la sesión del 2026-11-25)

**Hechos aportados por el usuario**
- Los enemigos siguen un **patrón fijo**: avanzar y girar suavemente (círculos, ochos, con distintas alturas). El patrón cambia solo cuando se les ataca: entonces **orbitan alrededor de su objetivo** para atacarlo.
- El HUD ya da el **fijado** y el **rango** (número bajo la mira fijada; ver `aprender_distancia.py` / `assets/dist_digits.npz`).
- **Siege hace zoom sobre toda la pantalla** (salto de escala, no solo de posición) y **cambia la sensibilidad del mouse**: más sensible, pero se queda pegado al objetivo fijado.

**Consecuencias de diseño**
1. **Tracker con predicción de movimiento** (Kalman con velocidad y giro, p. ej. modelo de giro constante). Entre detecciones de YOLO la caja se mueve sola con su trayectoria. El patrón curvo es justo lo que ese modelo predice bien.
2. **Dos estados de movimiento por enemigo**: *patrulla* (trayectoria regular) y *agro/orbita* (gira alrededor de mí). Cambiar de uno a otro es una señal de agro adicional para la red (se suma a las flechas).
3. **Salto de Siege**: no reiniciar el tracker. Estimar la transformación global (escala + desplazamiento) entre el cuadro anterior y el nuevo con el fondo (correlación de fase / puntos de interés) o con la mira, y **aplicarla a todas las pistas** antes de asociar. Hace falta una captura justo antes y justo después del cambio.
4. **Ganancia del mouse por modo**: calibrar por separado normal y Siege (`calibrar_mouse.py`). En Siege el mismo movimiento de mouse gira más; el bot debe escalar sus pasos.
5. **YOLO** queda para descubrir enemigos y relanzar pistas perdidas, no para seguirlos cuadro a cuadro. El seguimiento lo hacen el tracker y el HUD (fijado + rango).

**Entradas nuevas para la red:** rango (número bajo la mira), curvatura/giro de la trayectoria, ¿orbita?, escala de cámara actual (normal / Siege).

**Capturas extra necesarias:** justo antes y justo después de activar Siege (para medir el zoom), y la escena con el número de rango visible.
