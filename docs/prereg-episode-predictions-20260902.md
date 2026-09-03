# Predicciones selladas — dónde espero encontrar desvíos, antes de abrir nada

**Sellado:** 2026-09-02, **antes** de abrir `recompute_claims` y `Certificate.cs` para comparar.
**Autor:** la sesión de `deadman` (Ventana B).

**Por qué existe** (operador, 2-sep): sin esto, después de leer, *«yo habría predicho eso»* es
**infalsificable** — y es la única forma que le queda a este ejercicio de arruinarse ahora. Va en
su propio commit, como el sello y sus dos enmiendas.

**Qué se compara**: las siete filas de `docs/episode-consumer-definition.md` §5, más la
prohibición final.

---

## 0. Dos declaraciones de honestidad, antes de las predicciones

**(a) Mis predicciones sobre MI PROPIO lado no son predicciones.** Leí `recompute_claims` varias
veces esta semana; sobre él estoy **recordando**, no prediciendo. Van marcadas `RECUERDO`. Sólo las
del emisor son predicción genuina, marcadas `PREDICCIÓN`.

**(b) CONTAMINACIÓN FUTURA, declarada ahora y no cuando haga falta.**

> **A partir de leer `Certificate.cs` para esta comparación, quedo CONTAMINADA para cualquier caso
> de validación futuro que toque la computación de episodios del emisor.** El próximo caso elige
> **otra área u otro autor**.

Es la ENMIENDA 1 del sello aplicada por adelantado: la lista de lo que uno sabía se escribe antes,
no se recuerda después. El costo se acepta porque la alternativa —que otra ventana midiera el lado
del emisor contra una definición que no escribió— **contaminaría el instrumento en vez del
siguiente**: todo desacuerdo sobre qué significa la definición se contaría como desvío, e inflaría
exactamente la señal que declaramos como éxito.

---

## 1. Las predicciones, fila por fila

### Fila 1 — «hubo un tramo sin observación»: inicio y fin identificados, no interpretados

**SIN DESVÍO en los dos lados.** Los dos toman los límites de los eventos de frontera, sin
inferirlos. `RECUERDO` mi lado, `PREDICCIÓN` el suyo.

### Fila 2 — «duró tanto»: si sigue abierto, **cota inferior**, no duración

**DESVÍO en los dos.** `RECUERDO`: mi lado cierra un episodio abierto poniéndole el **final del
rango** como fin, no una cota declarada. `PREDICCIÓN`: el emisor publica un fin o una duración para
episodios abiertos, sin marcarla como cota.

### Fila 3 — «fuera de esos tramos hubo observación»: el bloque declara si el rango cubre la sesión

**DESVÍO en los dos.** `RECUERDO`: de mi lado la cobertura existe pero **vive en otro lado** del
informe, no pegada a la lista. `PREDICCIÓN`: en el certificado tampoco cuelga del bloque de
episodios. **La conclusión que el lector más quiere es la que ninguno sostiene donde él la lee.**

### Fila 4 — «nada sobre el trader»: ninguna afirmación empeora por un episodio

**DESVÍO en los dos, y YA CONOCIDO (DEF-7): no cuenta como hallazgo.** `RECUERDO`: `limitRespected`
se vuelve falso con un episodio abierto — arreglado hoy de mi lado, a medias. `PREDICCIÓN`: el
emisor sigue haciéndolo.

### Fila 5 — «nada sobre la causa»: el campo se llama por lo que es, y el documento lo declara

**DESVÍO en los dos, y YA CONOCIDO (DEF-2): no cuenta.** `RECUERDO`: renombrado hoy de mi lado.
`PREDICCIÓN`: el emisor sigue escribiendo `triggerEvent`, y **ninguno de los dos documentos declara
que no establece causas** — esa limitación todavía no salió.

### Fila 6 — «nada sobre si alguien se enteró»: fuera del bloque

**SIN DESVÍO HOY, y predigo que por el motivo equivocado.** No hay hechos sobre personas todavía,
así que nada los mezcla. `RECUERDO`: el cajón de sastre de `reasons` habría absorbido uno.
**Predigo que el acuerdo acá es por falta de ocasión y no por diseño** — la forma que §5.11 no
puede distinguir desde afuera.

### Fila 7 — «nada sobre exposición»: se declara que la duración no la mide

**DESVÍO en los dos, y ES LA FILA LIMPIA.** `PREDICCIÓN` fuerte: **ninguna de las dos
implementaciones dice esto en ningún lado**, porque ninguna se hizo la pregunta. No sale de ningún
defecto anterior y nadie me lo dijo.

### La prohibición — un episodio no puede ser insumo de ninguna afirmación adversa

**DESVÍO en los dos.** `RECUERDO`: el cajón de `reasons` y `limitRespected` hacen las dos cosas.
Parcialmente conocido.

---

## 2. La predicción que NO sale de las siete filas, y me parece la más arriesgada

**Mi definición del consumidor nunca produjo un campo `reasons`.** No apareció: de la pregunta
«qué queda habilitado a concluir el lector» no se deriva ninguna necesidad de enumerar qué eventos
ocurrieron dentro del tramo ciego.

> **PREDICCIÓN: las dos implementaciones tienen `reasons`, y la definición del consumidor no lo
> justifica.**

Si se cumple, es un desvío de una clase distinta a todas las de arriba: **no un campo mal hecho,
sino un campo que existe en los dos lados y que ninguno puede justificar desde el lector.** Y
encaja con lo que ya sabemos de él —absorbe cualquier evento del tramo— pero **la razón por la que
no debería existir es nueva**: un tramo ciego no puede enumerar lo que pasó adentro, porque la
premisa del tramo es que nadie estaba mirando. Lo que enumera son los eventos que el guardián
igual escribió, que es otra cosa.

**Si me equivoco y `reasons` sí se justifica al mirarlo, lo digo.** Es la predicción con más
chances de salir mal y por eso vale más que las otras.

---

## 3. Conteo esperado

| | |
|---|---|
| desvíos que espero | **5 de 7 filas + la prohibición + `reasons`** |
| de esos, ya conocidos y que **no cuentan** | filas 4 y 5, y parte de la prohibición |
| **desvíos que contarían como salida limpia del método** | **fila 7 (exposición) y `reasons`** |
| filas sin desvío esperado | 1 y 6 — y la 6 «por falta de ocasión», que no es lo mismo que por diseño |

**Cero desvíos sigue siendo la alarma, no la meta.** Y si el conteo real se parece demasiado a este
cuadro, eso tampoco es éxito: sería que estoy recordando el código, que es lo que la sección 0 (a)
ya declara para mi propio lado.
