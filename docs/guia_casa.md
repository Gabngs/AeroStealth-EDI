# Guía paso a paso para la PC del juego (leer con Claude al empezar la sesión)

**Cómo usar este archivo:** abre una sesión de Claude en el repo, dile «lee `docs/guia_casa.md`, `docs/diseno_red.md` y `docs/plan_mejora_bot.md` y empecemos por el paso 0». Claude debe ir paso a paso, confirmando cada resultado antes de seguir.

## Contexto en 10 líneas
- Bot de AceOnline: YOLO detecta calabazas, el HUD confirma el fijado, el bot dispara y mata. **Sin Siege funciona bien**; con Siege la cámara hace zoom/salto y el seguimiento se pierde (1-2 s para reubicar).
- Plan en `plan_mejora_bot.md`: ya implementado y **sin probar contra el juego**: `src/metrics.py` (Fase 0), histéresis en `_choose` (1a), recarga a 0 (1b), sección `tuning:`/`metrics:` en `config.yaml` (Fase 2).
- Diseño de la red de decisión y del entrenamiento en vivo con humano: `diseno_red.md`.
- Decisiones ya tomadas: no hay entrenamiento autónomo (sesiones de 2-5 min, tú corriges, se reentrena); red modular (una red pequeña por decisión + árbitro con reglas de seguridad); YOLO de una sola clase «enemigo» a futuro; tracker con predicción (Kalman) y compensación del zoom de Siege.
- **Hallazgo del código (verificar):** `src/hud.py` ya tiene `red_arrows()` (que parece ser el agro: flechas rojas) y `scripts/grabar_manual.py` ya registra `aggro = len(red_arrows)` junto a tu cursor, teclas y fijado. Hay que **validar** que `red_arrows` realmente detecta las flechas de agro (una vs dos) antes de usarlo como entrada.
- `logs/`, `data/`, `models/` y `*.pt` están en `.gitignore`: **no viajan por git**. Copia a mano lo que quieras traer de vuelta.

## Prerrequisitos (5 min)
1. `git pull` en la PC del juego y revisar que `git log` muestre el commit `3dc46a7` (o posterior).
2. Python con las dependencias: `py -m pip install -r requirements.txt` (incluye ultralytics/torch).
3. Comprobar GPU y modelo:
   ```
   py -c "import torch;print(torch.__version__, torch.cuda.is_available(), torch.cuda.get_device_name(0) if torch.cuda.is_available() else '-')"
   dir models\best.pt
   ```
   Anota: modelo de GPU (o «solo CPU») y si existe `models/best.pt`.
4. Juego abierto, personaje en el mapa de calabazas, HUD visible. El bot y los scripts de captura necesitan **administrador** (el juego va elevado). `iniciar_bot.bat` ya lo pide.

---

## Paso 0 — Humo: que lo nuevo no rompa nada (10 min)
Objetivo: confirmar que lo implementado el 24/11 arranca y registra métricas.
1. `iniciar_bot.bat 5` (se inicia y se cierra solo a los 5 min). Registro en `logs\bot.log` (codificación UTF-16 por el `Tee-Object`; si se ve raro, abrirlo como UTF-16).
2. Comprobar que existe `logs\etapas\<fecha>\events.jsonl` y `stage_summary.jsonl` (el resumen se escribe al cerrar la etapa; con `stage_s: 300` hace falta llegar a 5 min).
3. Si hay errores/trazas: pegarlos a Claude y corregir **antes** de seguir. No avanzar con el bot roto.

## Paso 1 — Línea base (3 etapas de 5 min, ~20 min)
Objetivo: números de referencia **sin cambiar nada** (es lo que decide todo lo demás).
1. Misma escena siempre (calabazas en árboles), sin Siege si es posible, mismas skills activas.
2. Lanzar 3 veces `iniciar_bot.bat 5` (o una de 15 min = 3 etapas).
3. Copiar `logs\etapas\<fecha>\stage_summary.jsonl` (y `events.jsonl`) a la PC de desarrollo / pegar su contenido a Claude.
4. Claude debe resumir: kills/min, % tiempo fijado, tiempo sin objetivo, cambios de objetivo por kill, reclics/unsticks, recargas, y **latencia por paso (media y p95 de `grab`, `hp`, `detect`, `step`, `loop`)**.
5. Preguntas que responde este paso: ¿`detect` es el cuello de botella? ¿YOLO corre en GPU? ¿la indecisión (cambios de objetivo por kill) es real o ya la corrigió la histéresis 1a?

Para comparar la histéresis 1a: repetir una etapa con `tuning: {switch_ratio: 1.0, min_dwell_s: 0}` en `config.yaml` (equivale a la lógica vieja) y otra con los valores nuevos. Misma duración, misma escena.

## Paso 2 — Capturas para los indicadores
Guardar todas en `data/capturas_indicadores/` con nombres claros. Capturas **a resolución completa del juego** (no recortadas), con el HUD visible. Usa la tecla de captura de Windows (Win+Shift+S → guardar) o la que prefieras; lo importante es el nombre y que no haya otras ventanas encima.

| Nº | Qué capturar | Nombre sugerido | Para qué sirve |
|---|---|---|---|
| 1 | Enemigo **fijado** (flechas verdes + barra de vida + número de rango bajo la mira) | `fijado_01.png` (varias, rangos distintos) | confirmar fijado y completar dígitos del rango |
| 2 | Un enemigo con **una** flecha de agro junto al nombre | `agro_1flecha_01.png` | caso «duda» (0,5) |
| 3 | Un enemigo con **dos** flechas de agro | `agro_2flechas_01.png` | caso confirmado (1) |
| 4 | Dos o más enemigos con agro a la vez | `agro_varios_01.png` | entrada «nº de enemigos con agro» |
| 5 | **Justo antes** de activar Siege (enemigo bien visible, anota si está fijado) | `siege_antes_01.png` | medir el zoom |
| 6 | **Justo después** de activar Siege, **mismo enemigo, sin mover el mouse** | `siege_despues_01.png` | medir escala y centro del zoom |
| 7 | Barra de vida propia antes y después de recibir daño | `vida_antes.png`, `vida_despues.png` | entrada «daño recibido» |
| 8 | Skills de la barra: una lista y una en reuso con texto de tiempo (p. ej. «4min») | `skill_lista.png`, `skill_reuso.png` | Fase 1c (cooldown real) |
| 9 | El **segundo mapa**: enemigos repartidos y en movimiento | `mapa2_01.png`… (3-5) | clase «enemigo» y candidatos |
| 10 | Un enemigo **atacándote** (orbitando) vs el mismo en **patrulla** (varios cuadros seguidos si puedes) | `orbita_*.png`, `patrulla_*.png` | estado de movimiento (agro por comportamiento) |

Apunta junto a cada captura (en `data/capturas_indicadores/notas.txt`): qué enemigo es, qué indica cada cosa (p. ej. «una flecha = está cargando»), el rango mostrado y qué estaba pasando.

**Respuestas a anotar** (preguntas abiertas del `diseno_red.md`, sección 6): color/forma de las flechas de agro frente a las de fijado; qué significa una vs dos flechas; cómo se sabe que hizo daño; si el daño varía por tipo de enemigo; dónde está la barra de vida propia; si en el mapa 2 atacan a distancia o cuerpo a cuerpo.

## Paso 3 — Validar `red_arrows` (agro) con las capturas
1. Claude carga `agro_1flecha_*`, `agro_2flechas_*` y `fijado_*` y ejecuta `red_arrows()` y `green_arrows()` de `src/hud.py` sobre cada una.
2. Resultado esperado: `fijado` → verdes sí / rojas 0; `agro_1flecha` → rojas = 1 punto; `agro_2flechas` → rojas = 2 puntos (o la lógica de `_double`). Si no coincide, **calibrar los umbrales HSV** con las capturas (el criterio de aceptación es acertar todas las capturas sin falsos positivos en las de fijado).
3. Definir la **señal de agro 0 / 0,5 / 1** (ninguna / una flecha / dos) y dejarla como función en `hud.py`.
4. Si hace falta, completar los dígitos del rango con `scripts/aprender_distancia.py <captura.png> <numero> [x y]` (repetir con capturas de rangos distintos hasta tener 0-9).

## Paso 4 — Grabar cómo juegas tú (datos de imitación)
`scripts/grabar_manual.py` (como administrador):
```
py scripts/grabar_manual.py 120 data/manual_01.csv
```
Juega 2 minutos como lo harías normalmente (matar calabazas, recargar, usar skills). Guarda `t, cursor, clics, teclas (1, shift, space, w, a, s, d, q), lock_x/lock_y, hp, aggro`. Repetir 3-5 veces, y una vez en el **mapa 2**. Es la primera materia prima para que la red imite decisiones humanas. Claude debe revisar que `aggro` no esté siempre en 0 y que `lock` coincida con lo que viste.

## Paso 5 — Medir el zoom y la sensibilidad de Siege
1. Con `siege_antes_01` / `siege_despues_01`, Claude estima escala y desplazamiento (correlación de fase / puntos de interés) y comprueba si el zoom está centrado en la mira o en el centro de la pantalla.
2. Calibrar la ganancia del mouse **por modo**: `py scripts/calibrar_mouse.py` en modo normal y de nuevo con Siege activo. Guardar ambos valores (la ganancia de Siege será mayor).
3. Resultado: dos números (escala de zoom, ganancia por modo) que irán al tracker y al control del mouse.

## Paso 6 — Implementación (Claude, con lo anterior)
En este orden; después de cada paso, una etapa de 5 min y comparar contra la línea base:
1. **Registro del vector de entradas** en `metrics.py` (agro 0/0,5/1, rango, velocidad del objetivo, fijado, munición, calor, skills, vida, tiempo sin objetivo…) + decisión tomada + latencia de decisión, por ciclo. Sin cambiar el comportamiento.
2. **Tracker con predicción** (Kalman con velocidad y giro) y **compensación del zoom de Siege** (no reiniciar pistas). Aceptar la caja con `age>=1` cuando el HUD ya confirma el fijado.
3. **Velocidad de YOLO** según lo que muestre el Paso 1: modelo nano, `imgsz` 480-640, `half=True`, `device=` explícito; en CPU exportar a OpenVINO/ONNX; detección en hilo aparte; detectar en una región.
4. **Cooldown real por skill** (Fase 1c) con las capturas 8.
5. `src/decision_net.py` (numpy, pesos en `.npz`) con **un solo módulo al principio: «a quién atacar primero» (agro + distancia)**, entrenado por imitación con los CSV del Paso 4 y las reglas actuales como maestro.
6. **Visor de la red** en la interfaz (nodos y pesos coloreados) y panel de sesión con línea de tiempo y botones de corrección.
7. Bucle en vivo: sesión de 2-5 min → pausa → corregir → reentrenar → siguiente sesión; versiones de pesos por sesión y vuelta atrás si empeora.
8. Más adelante: módulos de Siege, recarga, buffs; clase única «enemigo» con candidatos por movimiento para el mapa 2.

## Criterios de «hecho» por paso
- Paso 0: el bot corre 5 min sin trazas y escribe `stage_summary.jsonl`.
- Paso 1: 3 resúmenes de etapa guardados y tiempos por paso conocidos.
- Paso 3: `red_arrows`/agro acierta todas las capturas de agro y no da falsos positivos en las de fijado.
- Paso 5: escala de zoom y ganancias por modo medidas y anotadas.
- Paso 6.2: con Siege, la caja se recupera en **< 0,5 s** (hoy 1-2 s) y los kills/min no bajan.
- Paso 6.5: la red igual o supera a las reglas en «a quién atacar» sobre una etapa de 5 min.

## Seguridad y reglas fijas
- No tocar teclas, anti-AFK, killswitch, límites (`MAX_FAILS`, calor). Siempre debe poder detenerse con el killswitch.
- Cualquier cambio de comportamiento se prueba en etapas de 5 min contra la línea base; si cae por debajo del 70 % de los kills/min base, se revierte.
- Los commits no llevan atribución de IA (instrucción del usuario).

## Plantilla para anotar resultados
```
Fecha:            GPU:            Modelo (best.pt):
Etapa  kills/min  %fijado  s sin objetivo  cambios obj/kill  detect p95 ms  loop p95 ms  notas
base1
base2
base3
```
