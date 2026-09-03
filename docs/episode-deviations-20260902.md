# Los desvíos, medidos contra la definición sellada

**Leído:** `deadman-guardian` commit **`05d20bb`** (2026-09-02T18:40:19-05:00), sólo lectura, nada
escrito ahí. Y `recompute_claims` de este repo.

**Orden verificable en el `git log`:** sello (`prereg-episode-20260901.md`) → ENMIENDA 1 → ENMIENDA
2 → contenido (`episode-consumer-definition.md`, `0e7e377`) → predicciones (`8f78962`) → esto.

---

## 1. Antes del cuadro: dos predicciones donde fui MÁS DURA QUE LA REALIDAD

Van primero porque son las que un informe con ganas de tener razón esconde al final.

### 1.1 Fila 2 — predije que el emisor inventa un fin para un episodio abierto. **No lo inventa.**

```csharp
// Certificate.cs:295-300
current.ToSeq = toSeq;
current.ToUtc = null;          // open: no closing timestamp exists, so none is written
```

**Se niega explícitamente a fabricar la marca de tiempo**, con el motivo escrito al lado. Yo
predije que publicaría un fin o una duración sin marcarla. **Predicción medio equivocada, y del
lado de suponer peor.**

Lo que **sí** queda como desvío es más chico de lo que dije: `ToSeq` se llena con **el final del
rango**, que no es el final del episodio, y la duración no se declara como **cota inferior**. El
`ToUtc` nulo dice «no sé cuándo terminó»; el `ToSeq` del rango dice «terminó acá». **Los dos campos
del mismo par cuentan historias distintas.**

### 1.2 Fila 7 — predije que nadie lo dijo **«porque ninguna se hizo la pregunta».** Falso.

```csharp
// Certificate.cs:690-693
// Episodes get their own table because a JSON blob in a cell is unreadable, and
// unreadable is its own kind of dishonest. Every cell below is still a value lifted
// straight out of the document: no adjective, no duration computed, no judgement of
// whether two episodes is a lot. The reader decides that; this page only shows them.
```

**El emisor sí se hizo una pregunta de presentación, y la contestó con cuidado**: no adjetiva, no
computa duración, no juzga. Mi predicción le atribuía no haber pensado en el tema. **Estaba mal.**

**El desvío sobrevive, pero es otro y más fino**, y es la parte que el eje del consumidor aporta:

> **NOTA (2026-09-02, misma tanda): la REGLA que sale de acá se promovió a `CLAUDE.md`.** No es
> una propiedad de `failClosedEpisodes` — es de **cualquier cifra que un lector vaya a ordenar**, y
> el certificado está lleno: `lockoutsTriggered`, `ordersRejectedWhileLocked`,
> `changeAttemptsWhileSealed`, `daysCovered`. En este documento se leería como el detalle de un
> campo, que es lo más transferible del ejercicio leído como lo menos.
>
> **La medición se queda acá**, donde se hizo: un documento fechado se anota, no se reescribe. Lo
> que se mudó es la regla, no el hallazgo.

> El emisor eligió **«no juzgo, juzgás vos»**. La definición del consumidor dice algo distinto:
> **«los datos no sostienen el juicio que estás por hacer»**.
>
> **Abstenerse no alcanza cuando el número mismo induce.** Un lector que ve *1 h 01 m* y *3 min*
> concluye que el primero fue peor, y no hay adjetivo que haya que quitar para que eso pase: pasa
> con los números pelados. Es la misma forma que ya está escrita en el método —una aclaración al
> lado de una afirmación autorizada compite y pierde— con el silencio en el lugar de la aclaración.

---

## 2. El cuadro

| fila de §5 | predicho | medido | ¿cuenta? |
|---|---|---|---|
| **1** inicio/fin identificados, no interpretados | sin desvío | **sin desvío** — los dos toman los límites de los eventos de frontera | — |
| **2** episodio abierto: cota inferior | desvío en los dos | **desvío parcial**, y menor que lo predicho (§1.1) | conocido a medias |
| **3** el bloque declara si el rango cubre la sesión | desvío en los dos | **desvío en los dos** — la tabla de episodios (`:694`) no lleva cobertura, y de mi lado vive en otra sección del informe | **cuenta** |
| **4** nada sobre el trader empeora | desvío, conocido | desvío, conocido (DEF-7) | no cuenta |
| **5** nada sobre la causa | desvío, conocido | desvío, conocido — `TriggerEvent = prevEv` (`:273`), y ningún documento declara que no establece causas | no cuenta |
| **6** hechos sobre personas fuera del bloque | sin desvío **por falta de ocasión** | **exactamente eso** — el cajón de `:288-292` absorbería uno; no hay ninguno todavía | — |
| **7** la duración no mide exposición | desvío en los dos | **desvío en los dos**, por otro motivo que el predicho (§1.2) | **cuenta** |
| **prohibición** un episodio no es insumo de nada adverso | desvío | desvío — `Reasons` y `limitRespected` | conocido |

## 3. La predicción arriesgada: `reasons`

**Se cumple.** Los dos lados lo tienen (`:274` lo siembra con el evento anterior, `:291` acumula),
y **ninguno lo justifica desde el lector**. Lo más cercano a una justificación está en `:237-240`:

> *«the scalar claim and the per-episode breakdown are two granularities of one event»*

O sea: **es un desglose de las cifras escalares**. Eso justifica que exista un desglose; **no
justifica que se llame `reasons`**, y ahí está el hallazgo:

> **La premisa de un episodio es que nadie estaba mirando. Un tramo ciego no puede enumerar lo que
> pasó adentro.** Lo que enumera son **los eventos que el guardián igual alcanzó a escribir**, que
> es otra cosa — y el nombre dice la primera.

Es la familia de DEF-2 con un motivo distinto y nuevo: allá el problema era *adyacencia ≠ causa*;
acá es *lo registrado durante la ceguera ≠ lo ocurrido durante la ceguera*. Un lector lee
`reasons: {ACCOUNT_UNKNOWN: 3}` como **por qué** el guardián estuvo ciego. Lo que dice es **qué
llegó a anotar mientras lo estaba**.

**Y no propongo borrarlo**: el desglose sirve. Propongo que se llame por lo que contiene, con el
mismo movimiento que `triggerEvent` → `precedingEvent`.

## 4. Veredicto sobre el método, aplicando §3 del sello tal como está escrito

**No se descarta.** La cláusula A —«si no hace aparecer la atribución por adyacencia, el método se
descarta»— **no se cumplió**: la definición la hizo aparecer sola, en la fila 5, derivada de «el
lector va a buscar una causa porque una lista de fallas sin causas se lee como negligencia».

**Y por la cláusula B, eso NO se cuenta como que el método descubre**: yo sabía la respuesta. Lo
único que queda probado es que **el método produce una definición utilizable**.

**Lo que sí cuenta, y es poco pero es limpio** — dos salidas, ninguna derivada de un defecto
anterior y ninguna que nadie me haya dicho:

1. **La duración no mide exposición** (fila 7). Ninguna implementación lo dice, y el emisor tomó
   una decisión de presentación deliberada que **igual no alcanza**, por un motivo que sólo el eje
   del consumidor produce.
2. **`reasons` nombra lo que un tramo ciego no puede contener** (§3). Predicho a ciegas, confirmado,
   y con un motivo que no existía en ninguna de las dos implementaciones.

### El veredicto, con la calibración exacta

Escribí antes que «queda probado únicamente que produce una definición utilizable». **Eso es
demasiado modesto**, y decir que descubre sería demasiado generoso. La formulación que corresponde
(operador, 2-sep):

> **El eje del consumidor produjo dos hallazgos que las dos implementaciones NO PUEDEN PRODUCIR
> DESDE DONDE PREGUNTAN.** Las dos contestan *«cómo computo esto»*; ninguna contesta *«a qué queda
> habilitado el lector»*. La duración que no mide exposición y `reasons` nombrando lo que un tramo
> ciego no puede contener salen las dos de ese hueco, **no de un defecto anterior**.

**Eso es el eje funcionando.**

**Y es n=1, con el autor contaminado y sabiendo una de las respuestas** — que es exactamente la
vara que esta casa le exige a cualquier otro número. Así que se reporta así y no mejor:
**prometedor, una observación, y el próximo caso con otro autor u otra área.**

**Y el conteo no se pareció al cuadro predicho** —dos filas salieron distintas de lo que dije, las
dos en la dirección de que el emisor lo había pensado mejor que yo— lo cual es la única evidencia
disponible de que no estaba simplemente recordando el código.

## 5. Lo que queda anotado para §6

- La fila 6 es un **acuerdo por falta de ocasión**, no por diseño (§5.11). Cuando salga el acuse, el
  cajón de `:288-292` lo absorbe salvo que el emisor lo excluya como ya lo excluye este lado.
- `ToUtc` nulo y `ToSeq` del rango, en el mismo par, dicen cosas distintas.
- **Contaminación registrada**: desde este documento quedo contaminada para cualquier caso de
  validación futuro sobre la computación de episodios del emisor (`prereg-episode-predictions`
  §0(b)). El próximo caso elige otra área u otro autor.
