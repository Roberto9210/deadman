# deadman — instrucciones de sesión

Este repositorio es la **librería de primitivas de seguridad** y el **verificador de certificados**
(`deadman/verify_certificate.py`). Es el artefacto que juzga evidencia, así que las reglas de abajo
no son estilo: son la diferencia entre un veredicto y una opinión.

## Dos fuentes de calidad distinta no se suman

**Cuando cites dos lados de algo, cada lado va con su procedencia pegada, y la palabra
«confirmado» se reserva para cuando LOS DOS son mediciones.**

Una medición propia más una afirmación ajena no verificada no se promedian: el resultado hereda la
calidad de la **peor** de las dos. La palabra «confirmado» hace exactamente lo contrario —hereda la
de la mejor— y borra la juntura donde estaba la duda.

Se escribe así, siempre:

> *«Medido acá: X. Reportado por el otro lado, no verificado por nosotros: Y.»*

Y la conclusión conjunta se marca con la calidad de la peor mitad.

### La señal de alarma es la CONVENIENCIA

**La afirmación que asciende un hallazgo a urgencia, o que produce un paso 0, es la que hay que
releer con la procedencia delante.**

Ése es el criterio de dónde mirar, y es lo que hace a esta regla usable en vez de sólo cierta. No
se releen todas las afirmaciones con la misma sospecha: se relee **la que te conviene**. Una
afirmación mitad medida no se ve como una afirmación a medias — se ve como una afirmación **con
evidencia**, porque todo lo comprobable en ella comprueba. Lo que no aguanta es la mitad que nadie
verificó, y suele ser justo la mitad que aportaba la urgencia.

**Caso que la originó (2026-09-01):** se publicó en `docs/ledger-extension-rule.md` un bloque
titulado «CONFIRMADO DESDE LOS DOS LADOS» sobre `session.timezone: ""`. La mitad propia era una
medición real (`""` da exit 1 con `DECORATIVE_FIELD`). La mitad ajena —que el emisor producía `""`
hoy— era falsa. Sobre esa falsa confirmación un defecto de estilo se ascendió a «falla funcional en
ruta alcanzable» y se le inventó un paso 0 al orden de trabajo. El mismo documento etiquetaba la
procedencia de **todas** las demás afirmaciones ajenas; la etiqueta se soltó exactamente una vez,
en la más conveniente.

Al retractarse, la retractación se escribe **en el lugar donde estaba la afirmación**, no se borra.

## Un campo impreso dentro de un veredicto hereda la autoridad del veredicto

**No importa que el campo no se haya verificado: al estar en la misma línea que `VALID`, un lector
razonable lo lee como parte de lo verificado.**

Por eso **el arreglo no es agregar una advertencia — es sacarlo de esa línea.** Una aclaración al
lado de una afirmación autorizada compite con la autoridad y pierde.

Aplica a cualquier artefacto que mezcle **lo comprobado** con **lo transcripto**: el informe del
verificador, el certificado emitido, cualquier resumen que ponga las dos cosas en la misma tabla.

**Caso que la originó (2026-09-01):** `verify_certificate.py:1091` imprimía
`VALID (keyId=<issuer.keyId>)`. Medido: firmado por una clave, con `issuer.keyId` nombrando otra,
verificado contra la primera — el informe decía `VALID (keyId=<la que no firmó>)`. El campo nunca
se comprobó; la línea lo publicaba con el peso de un veredicto. Y en `--json` es peor: viaja como
la misma cadena (`:1524`), donde un consumidor automático la parsea como dato.

**La prueba para aplicarla:** de cada cosa impresa junto a un veredicto, preguntar *¿esto lo
comprobé, o lo estoy transcribiendo?* Lo transcripto va en otro lado, o no va.

## Dos implementaciones que adivinaron igual no se corroboran

**Dos implementaciones independientes de la misma regla equivocada siempre coinciden, y su
coincidencia se lee como corroboración.**

La coincidencia entre dos implementaciones **sólo es evidencia si fueron derivadas
independientemente**. Cuando no hay documento del cual derivarlas, lo único que comparten es el
supuesto — y cruzarlas prueba que las dos leyeron lo mismo, no que el mundo sea así.

**Caso que la originó (2026-09-01):** el certificado publica `triggerEvent` como la causa de un
episodio. El verificador la deriva tomando el evento anterior (`verify_certificate.py:974-982`) y
el emisor **también** (`deadman-guardian` `Certificate.cs:238`, leído en el commit `66dee69`). Un
test que compare los dos pasaría siempre, sobre todo certificado, sin comprobar nada sobre la
causa real.

**Cómo se aplica:** antes de usar «los dos lados coinciden» como evidencia, preguntar *¿de qué
documento derivó cada uno?* Si es «de ninguno», el acuerdo es un hecho sobre las implementaciones,
no sobre el mundo. Mientras no exista la especificación compartida, todo acuerdo entre este repo y
`deadman-guardian` se reporta como **consistente**, nunca como **corroborado**.

## La forma que tiene que tener todo pre-registro

No es de un caso: es la forma, de acá en más.

1. **El compromiso va en su PROPIO commit, antes del contenido.** No se sella sólo qué se espera:
   se sella **qué va a significar cada resultado**, para que un nulo no se pueda explicar después
   ni un positivo celebrar. Sin eso, es como no medir.
2. **El orden de los commits ES la garantía**, y es lo que la vuelve mejor que una promesa: un
   tercero la lee en el `git log` sin confiar en nadie. Es la primera forma de pre-registro de esta
   casa con **verificación externa en vez de palabra**.
3. **Se declara explícitamente lo que NO se puede prometer.** Un autor que ya conoce la respuesta
   no puede producir un positivo válido, pero **sí puede producir un negativo válido**; eso se
   escribe antes, no después. Decir el límite es lo que vuelve creíble el resto.
4. **Cada resultado se etiqueta por lo que lo sostiene**: *medido* (verificable por un tercero) o
   *auto-atestiguado* (mi palabra sobre mi propio estado). Los dos pueden servir; **no se cobran
   como lo mismo.**
5. **Las enmiendas se agregan debajo, fechadas y en su propio commit.** El texto sellado no se
   edita en su lugar — un sello que se reescribe no es un sello.

Ejemplo vivo: `docs/prereg-episode-20260901.md`.

## Método, en corto

- **Verificar contra el código real antes de afirmar.** Un hallazgo no verificado no es un hecho, y
  se dice «no verificado» en vez de construir encima.
- **Toda medición incluye un caso que DEBE dar distinto.** Si el control y el caso dan lo mismo, el
  instrumento está contestando, no el sistema. Para propiedades, **generar** entradas adversariales;
  el conjunto real sirve como caso de humo, nunca como la garantía.
- **Se documenta lo que se descartó, con su motivo** — «se consideró X y se descartó porque Y»— o
  vuelve dentro de un año.
- **Una decisión de producto se escribe como pregunta**, con sus opciones y el costo de cada una,
  en vez de tomarse.

El razonamiento largo y las decisiones tomadas viven en `docs/ledger-extension-rule.md`; el estado
del formato de evidencia y los pedidos abiertos al emisor, en `docs/request-to-guardian-*.md`.
