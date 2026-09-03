# Pre-registro sellado — definición de EPISODIO desde el lado del consumidor

**Sellado:** 2026-09-01, antes de escribir una línea del contenido.
**Autor:** la sesión de `deadman` (Ventana B).
**Estado:** SELLO. Este documento no contiene la definición. Contiene **qué se va a hacer y qué va
a significar cada resultado**, fijado antes de conocer el resultado.

---

## 1. Por qué existe este documento

`triggerEvent` se deriva por **adyacencia** en los dos lados: el verificador toma el evento
anterior (`verify_certificate.py:974-982`) y el emisor también (`Certificate.cs:238`, leído en
`deadman-guardian` commit `66dee69`). Los dos coinciden **porque comparten el error**, y esa
coincidencia se lee como corroboración (§5.11).

La salida propuesta para §6 es escribir la especificación desde una **pregunta generadora
distinta**:

> Las implementaciones contestaron **«cómo computo este campo»**.
> §6 tiene que contestar **«qué queda habilitado a concluir un lector de este campo, y qué tiene
> que ser verdad para que esa conclusión se sostenga»**.

«Qué cuenta como episodio» es el primer campo **porque tiene respuesta conocida**: la adyacencia
vive adentro de esa computación. Eso lo vuelve un **control del método**, no sólo un campo.

## 2. El problema del autor, declarado antes y no después

**Yo ya encontré la atribución por adyacencia.** Mi propia medición me dio la respuesta. Por lo
tanto:

> **Un autor que sabe la respuesta NO PUEDE producir un resultado positivo válido, pero SÍ puede
> producir un negativo válido.**

No hay autor virgen disponible: Ventana A también conoce la adyacencia y la escribió en su propio
documento de literales. Los dos lados saben. Este pre-registro se corre **aceptando eso**, con la
asimetría declarada de antemano.

## 3. EL COMPROMISO — qué va a significar cada resultado

Esto es lo que se sella, y es lo que no se puede reinterpretar después:

> **A. Si la definición escrita desde el lado del consumidor NO hace aparecer la atribución por
> adyacencia, el método del punto 3 NO SIRVE Y SE DESCARTA.**
>
> Falló en el caso más fácil posible — el único campo con respuesta conocida, con el autor mejor
> informado que existe. No se le buscan atenuantes, no se reintenta con otro campo «mejor
> elegido», no se ajusta la pregunta generadora hasta que funcione. Se descarta, y §6 se escribe
> de otra manera.
>
> **B. Si SÍ la hace aparecer, NO se concluye que el método descubre.** Se concluye únicamente lo
> que un negativo no puede refutar: que el método **produce una definición utilizable**. La
> capacidad de descubrimiento queda **sin demostrar**, porque el autor sabía la respuesta.
>
> **C. Cualquier hallazgo ADICIONAL que la definición produzca —algo que yo no sabía de antemano—
> sí es evidencia de la capacidad generadora**, y es la única que este ejercicio puede producir a
> favor. Se cuenta aparte y se nombra.

**El conteo de desvíos es el control**, no la meta: **cero desvíos sería la alarma** — la señal de
que se escribió mirando el código.

## 4. El procedimiento, en orden, y el orden es parte del compromiso

1. **Este sello se commitea** antes de escribir el contenido. El repositorio lo fecha.
2. Se escribe `docs/episode-consumer-definition.md`: qué queda habilitado a concluir un lector de
   `failClosedEpisodes`, y qué tiene que ser verdad para que esa conclusión se sostenga. **Sin
   abrir `recompute_claims` ni `Certificate.cs` mientras se escribe.**
3. Se commitea el contenido, **antes** de compararlo con nada.
4. Recién entonces se abren las dos implementaciones y se anota, campo por campo, cada desvío.
5. Se aplica §3 tal como está escrito arriba.

## 5. Lo que NO se puede prometer, dicho ahora

No puedo prometer no haber usado lo que sé. **Puedo prometer el orden de los commits**, que es
verificable por un tercero en el `git log`, y **puedo prometer no reinterpretar el resultado**,
que es lo que este documento sella.

Esa es toda la garantía que hay, y es menos de la que tendría un autor virgen. Está escrita acá
para que nadie la cobre como más.

---

## ENMIENDA 1 — 2026-09-01, antes de escribir el contenido

**El texto de §3 no se toca.** Esta enmienda se agrega debajo, fechada y en su propio commit, para
que un tercero vea en el `git log` qué decía el sello original y qué se le añadió. Un sello que se
edita en su lugar no es un sello.

**La cláusula C queda ETIQUETADA** (operador, 1-sep):

> El hallazgo adicional de C **se cuenta aparte y se marca AUTO-ATESTIGUADA, no medida.**

**El motivo:** quien certifica que yo no sabía algo de antemano **soy yo**, y este ejercicio existe
precisamente porque desconfiamos de eso. La cláusula sigue valiendo — es la única evidencia
positiva que el ejercicio puede producir — pero **no es del mismo tipo que el negativo de A**, que
sí es limpio: A no depende de mi palabra sobre mi propio estado mental, sólo de si la adyacencia
aparece o no en un texto que ya está escrito.

**Cómo se reporta**, para que nadie las cobre como lo mismo:

| resultado | tipo | qué lo sostiene |
|---|---|---|
| **A** (negativo: no aparece la adyacencia) | **medido** | el texto escrito, verificable por cualquiera |
| **B** (aparece) | **medido, pero no concluyente** | el texto, y la limitación declarada del autor |
| **C** (hallazgo adicional) | **AUTO-ATESTIGUADA** | mi palabra de que no lo sabía — nada más |

---

---

## ENMIENDA 2 — 2026-09-02, todavía antes de escribir el contenido

**Nada de lo sellado se toca.** Se agrega debajo, fechada y en su propio commit, como la ENMIENDA 1.

### El autor queda fallado: lo escribo yo, sabiendo la respuesta

§2 dejaba tres salidas y recomendaba la (2) —otro campo cuya respuesta el operador conociera y yo
no—. **El operador falla por la (3), y con el argumento correcto:**

> **La asimetría se sostiene.** Un autor que sabe la respuesta **no puede** producir un positivo
> válido, pero **sí puede** producir un **negativo válido**. Si la escribo sabiéndola y **aun así**
> la atribución por adyacencia no aparece, el método se murió ahí — barato, y en el caso más fácil
> posible.

La (2) además **no estaba disponible**: no hay ningún defecto medido en otro campo cuya respuesta
él conozca y yo no. Lo que se pierde queda dicho, no descontado: **este ejercicio puede matar el
método y no puede consagrarlo.**

### Y hay que declarar algo que supe DESPUÉS del sello y ANTES del contenido

El 2026-09-02, al fallar la cola, el operador me pasó un hecho que **no salió de este repositorio**
y que no tenía cuando se selló §3:

> El **26-ago el guardián intentó aplanar 167 veces y nadie contestó**. Disparó, fue correcto, y no
> cambió nada. **Un freno desoído es, en resultado, un freno que no disparó.**

**Se declara acá porque el sello no sirve si lo que entra a la cabeza del autor entre el sello y el
contenido queda sin registrar.** Concretamente, esto acota la cláusula C:

> **Si la definición del consumidor hace aparecer «el registro de un intento no es el registro de
> un resultado», eso NO cuenta como hallazgo adicional bajo C.** Me lo dijeron antes de escribir.
> Cuenta como parte de lo que ya sabía, igual que la adyacencia.

Es exactamente lo que la ENMIENDA 1 le hizo a C —etiquetarla en vez de creerle— aplicado a un
segundo insumo. **La lista de lo que sabía de antemano se escribe antes, no se recuerda después.**

Lo que sabía al empezar el contenido, completo:

1. La atribución por adyacencia de `triggerEvent` (medida por mí el 1-sep).
2. El cajón de sastre de `reasons`, y que un evento cualquiera durante un episodio entra ahí.
3. Que `limitRespected` colapsa «no pude ver» con «incumplió» (DEF-7).
4. Que un episodio abierto al final del rango es alcanzable y dura (1 h 01 m medido).
5. **Los 167 aplanados desoídos del 26-ago** — reportado, no medido por mí.

**Cualquier cosa de esas cinco que aparezca en la definición no es descubrimiento.**

---

*Relacionado: `docs/ledger-extension-rule.md` §5.11 (dos implementaciones que adivinaron igual no
se corroboran), §6.2 (la pregunta generadora), §6.2b (este ejercicio como control del método).*
