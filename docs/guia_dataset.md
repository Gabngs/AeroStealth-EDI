# Guía del dataset: qué capturar y qué etiquetar

Base de partida (v0.1, se afina con las capturas reales).

## Clases

| id | clase | qué es | cómo etiquetarlo |
|----|-------|--------|------------------|
| 0 | `enemigo` | Enemigo con su marca de objetivo | Caja ajustada al enemigo (o a la marca si es lo único visible) |
| 1 | `drop` | Ítem soltado, con letras amarillas, a veces flotando en el aire | Caja sobre el texto/ítem |

Pendiente de decidir con capturas: si la marca de "objetivo fijado" y el radar merecen clase propia.

## Reglas de etiquetado

- Si un enemigo es tan pequeño o lejano que tú no lo distingues, **no lo etiquetes**. Es mejor no enseñar nada que enseñar ruido.
- Caja ajustada, sin mucho margen.
- Un cuadro sin ningún enemigo ni drop también vale: se guarda sin cajas (muestra negativa). Hacen falta para que no vea enemigos donde no hay.
- Un enemigo parcialmente tapado o cortado por el borde sí se etiqueta si lo reconoces.

## Qué capturar (variedad antes que cantidad)

- Enemigos cerca, lejos, varios a la vez, y uno solo.
- En tierra y en vuelo (inclinado a izquierda y derecha).
- Distintos fondos, horas/zonas y efectos (disparos, explosiones).
- Drops en el suelo y en el aire.
- Momentos sin enemigos (negativos).
- Meta inicial: 200–300 cuadros corregidos para un primer detector útil.

## Mecánicas del juego (contexto para las fases de control)

- Nave que puede ir en tierra o volar. En vuelo, A/D inclinan; la orientación es con el mouse. Inclinar a un lado y llevar el mouse al contrario da un giro más cerrado.
- Habilidades 1–9; Tab cambia entre 3 barras; Shift suelta la mira.
- Clic izquierdo = arma estándar. Clic derecho = arma avanzada, solo hace daño si el objetivo está dentro del rango (hay radar).
- La mira se puede fijar a distancia, pero el arma avanzada necesita estar cerca.
- Ciclo de farmeo: matar en un punto → los drops caen o quedan en el aire → despegar (Espacio), volar y recoger con Q sin chocar → volver al punto.
