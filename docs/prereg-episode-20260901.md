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

*Relacionado: `docs/ledger-extension-rule.md` §5.11 (dos implementaciones que adivinaron igual no
se corroboran), §6.2 (la pregunta generadora), §6.2b (este ejercicio como control del método).*
