# Plan de mejora del bot: decisiones más naturales, ágiles y medibles

**Implementado (2026-11-24, sin probar contra el juego):** Fase 0 (`src/metrics.py`), 1a (histéresis en `_choose`), 1b (recarga a 0 y salida de Siege para recargar) y Fase 2 (`tuning:` y `metrics:` en `config.yaml`). **Pendiente:** 1c (cooldown por skill con OCR), Fase 3 (tuner), Fase 4 (red).

Estado original: **propuesta**. Todo lo de abajo sale de leer `src/bot.py`, `config.yaml`, `src/hud.py` y `logs/`.
No se ha ejecutado ni medido nada todavía (ver «Qué no se pudo comprobar»).

## 1. Lo que ya existe (y que cambia el punto de partida)

El bot **no** parte de cero. Ya tiene una máquina de estados implícita en `Bot.step()` / `attack()` / `search()`:

| Pieza | Dónde | Qué hace hoy |
|---|---|---|
| Percepción YOLO | `_detect` (`bot.py:202`) | `predict(imgsz=800, conf=0.2)` en cada ciclo; se salta solo mientras dispara a un fijado sin Siege |
| Tracker casero | `_track` (`bot.py:206`) | Asocia por distancia (<80 px), suaviza posición, exige `age>=3`. **Sin ID estable ni velocidad**; mantiene un mapa `known` de calabazas |
| Confirmación por mira | `green_arrows`, `target_hp` (`hud.py`) | Fijado = flechas verdes + barra de vida (la señal fiable que ya usas) |
| Siege si se mueve | `_watch_motion` (`bot.py:563`) | Si las flechas verdes se desplazan >18 px en 0,8 s → Siege |
| Siege en cadena | `_siege_push`, `_siege_off` | Empuja el mouse al siguiente; se apaga a 1 s sin enemigos o 2,5 s sin fijar |
| Elegir objetivo | `_choose` (`bot.py:699`) | Se queda con el actual si hay otro a <150 px; si no, el más cercano al cursor |
| Mantenimiento | `maintain` (`bot.py:387`) | Recarga y buffs, **solo** sin enemigo fijado y sin Siege |
| Recuperación | `unstick`, calor, reclic, `maneuver` | Soltar con shift, enfriar, reposicionar cada 6-8 min |
| Métricas | `_periodic` | Solo una línea de texto cada 60 s (kills y kills/min) |

Conclusión: el trabajo no es «añadir inteligencia», es **(a) medir, (b) pulir tres decisiones concretas, (c) exponer los umbrales como parámetros** para poder optimizarlos por etapas.

## 2. Problemas detectados

1. **No hay medición.** Todo va al log de texto (`logs/bot.log`, además con codificación UTF-16 por el `Tee-Object` de PowerShell). Sin KPIs estructurados no se puede comparar una etapa con otra ni graficar.
2. **Indecisión al elegir objetivo.** `_choose` solo es «pegajoso» mientras `target_c` está definido y hay una caja a <150 px. `target_c` se pone a `None` al fallar `HOVER_S`, al apagar Siege y tras cada kill, y la caja se recalcula cada ciclo a partir de un cursor que se está moviendo. Resultado probable: el «más cercano al cursor» cambia mientras el cursor se desplaza. *(Hipótesis: hay que confirmarla con el contador «cambios de objetivo por kill».)*
3. **Recarga por umbral, no por cero.** `AMMO_LOW = 100` recarga con 100 balas; tú quieres recargar al llegar a 0 (`00000` en rojo). `ammo_empty()` (`hud.py:271`) ya detecta el icono rojo, así que la señal existe.
4. **Recarga y buffs solo «sin enemigo fijado».** Con Siege en cadena casi nunca hay un hueco, así que la recarga puede tardar. Cuando se queda sin munición pasa por `unstick` tras ~2-3 s de «sin daño».
5. **Cooldowns de skills por tiempo fijo.** `BUFF_RETRY_S = 45` y el proxy `buff_count() < 2`. No lee el estado real de cada skill (icono oscuro / texto «4min» en la barra).
6. **Rendimiento sin medir.** YOLO a 800 px en cada ciclo (salvo mientras dispara). `predict()` no recibe `device=`; Ultralytics usa GPU solo si PyTorch tiene CUDA. No hay temporizadores por etapa (captura / YOLO / HUD / acción).

## 3. Plan por fases

### Fase 0 — Medir sin cambiar el comportamiento (primero, imprescindible)

- Nuevo `src/metrics.py`: registra **eventos** (timestamp + tipo + datos) en `logs/etapas/<fecha>/events.jsonl` y un resumen por etapa en `stage_summary.jsonl`.
- Una **etapa** = ventana fija de tiempo (propuesta: 5 min) dentro de `Bot.run`. Al cerrarla se calcula el resumen, se guarda y se empieza otra.
- Temporizadores por paso del bucle: `grab`, `_detect`, `_track`, lectura de HUD, `step`. Resumen con media y p95 en cada etapa. Con esto se responde «¿va lento y por qué?» (CPU/GPU, captura o lógica).
- Al arrancar, registrar `torch.cuda.is_available()` y el dispositivo real del modelo.
- Sacar 3-5 etapas **con la lógica actual** = **línea base** para comparar todo lo demás.

### Fase 1 — Tres mejoras concretas (con la métrica de la Fase 0 ya activa)

**1a. Histéresis en `_choose`.** Regla: cambiar de objetivo solo si el candidato nuevo está a menos de `0.7 ×` la distancia al cursor que el actual (≈30 % mejor), y no antes de `MIN_DWELL_S` (~0,6 s) desde la última elección. Se reinicia al matar, al soltar por «no se deja» o al perder el objetivo. Parámetros: `switch_ratio`, `min_dwell_s`.

**1b. Recarga al llegar a 0.** `_ammo_low()` pasa a usar `ammo_empty or std == 0` (umbral configurable, `AMMO_LOW = 0` por defecto). Permitir la recarga también **en medio de una cadena de Siege**: al detectar 0, soltar el clic, recargar y volver, en lugar de esperar al `unstick`. A confirmar: ¿el rojo aparece solo en el contador estándar o también en el avanzado?

**1c. Cooldown real por skill.** Sustituir `BUFF_RETRY_S` fijo por un estado por skill: `ready / activo / en reuso`, leído de (i) el icono en la barra (oscuro = en reuso, ya se usa 0.6-0.7 como umbral) y/o (ii) el texto de tiempo sobre el icono (OCR con las plantillas de dígitos que ya existen en `assets/digits.npz`), y (iii) el icono activo arriba a la izquierda. Con eso `maintain` solo lanza lo que esté listo y necesario.

### Fase 2 — Parámetros expuestos

Mover las constantes de comportamiento de `bot.py` a una sección `tuning:` de `config.yaml` con rango permitido. Candidatas (las que afectan a «agilidad y naturalidad»):

| Parámetro | Hoy | Efecto |
|---|---|---|
| `switch_ratio`, `min_dwell_s` | (nuevo) | indecisión al elegir |
| `HOVER_S`, `HOVER_DOUBT_S`, `DOUBT_CONF` | 2.5 / 1.2 / 0.4 | cuánto esperar a que se fije |
| `MOVE_PX`, `MOVE_WINDOW_S` | 18 / 0.8 | cuándo se considera que el enemigo se mueve (Siege) |
| `SIEGE_TRANSIT_MAX_S`, `SIEGE_EMPTY_S`, `SIEGE_NO_DAMAGE_S` | 2.5 / 1.0 / 2.0 | tiempo perdido en Siege sin objetivo |
| `SCAN_AFTER_S`, `SCAN_STEP_S` | 1.5 / 1.2 | búsqueda cuando no hay nada |
| `NUDGE_PX`, `NUDGE_MIN_PX` | 110 / 9 | rapidez del giro en cadena |
| `DEAD_S`, `KNOWN_TTL_S` | 4 / 25 | memoria de calabazas |

**No se tocan automáticamente**: teclas, anti-AFK, killswitch, límites de seguridad (`MAX_FAILS`, calor).

### Fase 3 — Optimización por etapas (el «aprendizaje por generaciones»)

- Algoritmo sencillo **(1+1)-ES**: un padre (mejores parámetros hasta ahora) y un hijo con mutación pequeña y acotada. Cada generación = 1 etapa de 5 min.
- **Fitness** de la etapa (solo KPIs controlables; drops fuera):
  `kills/min − a·tiempo_sin_objetivo − b·tiempo_Siege_sin_objetivo − c·cambios_de_objetivo_por_kill − d·reclics_y_unsticks`
- Ruido: se normaliza por minuto, y un hijo solo reemplaza al padre si gana **dos veces** (o por margen mínimo).
- Salvaguardas: parámetros acotados, el killswitch actual sigue mandando, y si una etapa cae por debajo del 70 % de la línea base se vuelve al padre.
- Reparto: **«premio» = el número del fitness**; la red/optimizador no recibe nada más. Lo que sobrevive es lo que puntúa más.

### Fase 4 — Red de decisión (opcional, para la presentación)

- MLP pequeña (p. ej. 8 entradas → 6 ocultas → 4 salidas) que sustituye una decisión acotada: **qué objetivo elegir / cuándo activar Siege / hacia dónde buscar si no hay nada**.
  - Entradas candidatas: nº de enemigos, distancia al más cercano, ángulo a la mira, ¿fijado?, velocidad del objetivo (flechas verdes), tiempo sin objetivo, Siege activo, munición vacía.
  - Primero se entrena por **imitación** con los eventos de la Fase 0 (que copie a las reglas) y luego se mejora con el mismo (1+1)-ES.
- `scripts/graficar_etapas.py`: fitness y KPIs por generación (matplotlib) y un dibujo de la red por generación (nodos y pesos coloreados, estilo del vídeo) para montar un GIF.
- Comparativa final **reglas vs. parámetros optimizados vs. red**, con las mismas etapas y KPIs.

## 4. KPIs de la Fase 1 y cómo se obtienen con el código actual

| KPI | Fuente |
|---|---|
| kills/min | `self.kills` (`search`, al desaparecer la barra) |
| % tiempo con objetivo fijado | `step`: `locked` |
| tiempo sin objetivo (búsqueda) | `empty_since` / `scan` |
| tiempo en Siege sin objetivo | `transit_t` y `_siege_off` |
| cambios de objetivo por kill | cambios de `target_c` > 150 px en `_choose` |
| tiempo medio por kill | de «Enemigo fijado» a «eliminado» |
| disparos en vacío / reclics | eventos `Reclic`, `unstick` |
| recalentamientos | `cool_until` |
| recargas y munición mínima | `maintain`, `_ammo_low` |
| buffs lanzados y su reuso | `cast` |
| latencia por paso | temporizadores nuevos (Fase 0) |

Drops: **no entran en el fitness** (aleatorios). Solo se registra como evento cuando se pulsa `q`.

## 5. Orden recomendado y archivos a tocar

1. `src/metrics.py` (nuevo) + ganchos en `bot.py` (`run`, `step`, `search`, `attack`, `unstick`, `cast`) → **Fase 0**.
2. Etapas de línea base (3-5) → comprobar si el 7/10 sube o baja con cada cambio.
3. `_choose` (1a), `_ammo_low` y `maintain` (1b), estado por skill en `hud.py`/`bot.py` (1c).
4. Sección `tuning:` en `config.yaml` (Fase 2).
5. `src/tuner.py` + `scripts/graficar_etapas.py` (Fase 3).
6. `src/decision_net.py` (Fase 4), solo si el resto está estable.

## 6. Qué no se pudo comprobar

- **GPU/CPU**: el Python por defecto de esta máquina no tiene `torch` instalado (¿hay un venv distinto?) y no existe `models/best.pt` en el repo (está fuera de git). Por eso no se pudo verificar si YOLO corre en GPU ni cuánto tarda cada paso. La Fase 0 lo mide.
- **La causa exacta de la indecisión** (punto 2) es una hipótesis hasta tener el contador de cambios de objetivo.
- No se ejecutó el bot ni se modificó ningún archivo salvo este documento.

## 7. Decisiones ya tomadas (respuestas del usuario)

1. **Texto «4min» sobre el icono de la barra**: es el tiempo que falta para poder volver a activar la skill (el buff dura mientras tanto). Se trata como **cuenta atrás de reuso**: skill lista = sin texto / icono normal; en reuso = texto con tiempo. Se lee por OCR de la franja del icono y se combina con el icono oscuro y el icono activo de arriba a la izquierda. Si el OCR falla, se usa el último lanzamiento + tiempo conocido como respaldo.
2. **Munición `00000` en rojo**: cada arma tiene su **propio contador** (estándar y avanzada) y se pone en rojo cuando **esa** arma se queda a 0. El bot hoy dispara con el arma estándar, así que la recarga se dispara con el contador estándar en 0 (`ammo_empty` o `std == 0`). Si en el futuro usa la avanzada, se añade la misma regla para su contador (`ammo[1]`), con su icono/recarga correspondiente.
3. **Duración de etapa: 5 a 10 min, adaptable** (no fija):
   - Mínimo 5 min.
   - Si al cierre la etapa es **claramente peor** que el padre (< 70 % de su fitness) se descarta ahí mismo.
   - Si queda **dentro del margen de ruido** del padre, se **alarga hasta 10 min** para decidir con más datos.
   - Los KPIs se normalizan por minuto para que etapas de distinta duración sean comparables.

## 8. Preguntas abiertas

1. ¿La escena de pruebas va a ser siempre la misma (calabazas en árboles) para que las etapas sean comparables?
2. «Tontear» (moverse/girar sin objetivo) queda para después de la Fase 3: es buen candidato para que lo aprenda la red.
