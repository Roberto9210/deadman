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
5. **Las enmiendas se agregan DEBAJO, fechadas y en su propio commit; el texto sellado NO se
   toca.** Un sello que se edita en su lugar no es un sello. Vale incluso cuando quien pide el
   cambio es quien lo aprobó: un tercero tiene que poder leer en el `git log` qué decía el
   original y qué se le añadió, sin confiar en el relato de ninguno de los dos.

Ejemplo vivo: `docs/prereg-episode-20260901.md`.

## Un test sirve cuando mide la propiedad, no un proxy de ella

**Antes de escribir un chequeo, preguntar: ¿esto mide el daño, o mide algo que suele acompañarlo?**
Un proxy se puede creer durante años mientras es falso, porque nadie lo mide — es la propiedad la
que duele, y nadie revisa el proxy hasta que el daño ocurre igual.

**Caso que la originó (2026-09-01):** `.gitattributes` protegía «este repo es uniformemente CRLF».
Medido, era falso el día que se escribió (21 de 46 blobs lo contradecían) y sigue siéndolo (23
solo-LF y 4 mezclados de 67). El daño real nunca fue la falta de uniformidad: es **que una
modificación cambie los finales de línea de un archivo que no venía a tocar**, con lo que un cambio
de un renglón aterriza como un diff del archivo entero y mueve su `git blame`. La uniformidad era
un proxy; el chequeo que la reemplaza (`scripts/check_line_endings.py`) mide la propiedad, sobre el
único objeto donde es visible: el diff.

**La prueba para aplicarla:** describir el daño en una frase que empiece con un verbo. Si el
chequeo no puede fallar exactamente cuando esa frase es cierta, está midiendo otra cosa.

**Y por qué un proxy sobrevive años, que es la parte sin la cual la regla suena obvia y no lo es:**

> **Es la PROPIEDAD la que duele, así que nadie revisa el PROXY hasta que el daño ocurre igual.**

Mientras el daño no pasa, el proxy no da señal de estar mal — se ve exactamente como un proxy que
funciona. Y cuando el daño pasa, la atención va al daño, no al proxy que no lo evitó. Por eso no se
descubren solos: hay que ir a medirlos **sin motivo**, que es justo lo que nadie hace.

## Un arreglo que depende del lector no es un arreglo

Un aviso, una salvedad, un comentario honesto: todo eso protege sólo a quien lo lee, y el daño
ocurre en quien no lo leyó. **Si la protección requiere que alguien lea algo, no es protección: es
documentación.**

El mismo día (2026-09-01) la lección llegó por tres caminos, en tres dominios, sin que ninguna
ventana supiera de las otras:

| dónde | la forma que tomó |
|---|---|
| **acá** (`deadman`) | un proxy en `.gitattributes` que se creyó hasta que dolió |
| **ALAYA** | una salvedad sobre 13 afirmaciones, que dependía de que alguien la leyera |
| **`deadman-guardian`** | un comentario honesto en el código mientras el dato emitido miente |

**Qué licencia esa convergencia, y qué no** — porque aceptarla sin más sería exactamente lo que
§5.11 de `docs/ledger-extension-rule.md` existe para impedir, y aceptarla *porque halaga* es la
señal de la conveniencia:

- **Los DOMINIOS sí son independientes**: tres repositorios, tres artefactos, ninguna derivación
  común entre ellos. Eso es evidencia fuerte de que el patrón es **frecuente**, y es lo contrario
  del caso de §5.11, donde la coincidencia venía de un supuesto compartido.
- **El OBSERVADOR no lo es.** Las tres ventanas son el mismo modelo, con el mismo método cargado de
  la misma memoria. Son tres *sesiones* distintas, no tres *instrumentos* distintos. Así que la
  convergencia es evidencia **débil** de que el patrón sea real y no un artefacto de cómo este
  observador mira.

**Las dos cosas a la vez, y la segunda no anula la primera.** Lo que queda en pie: el patrón
aparece en dominios que no se hablan, lo cual vale. Lo que no queda probado: que un observador
distinto lo hubiera visto. Un tercer camino independiente **de observador** — alguien que no sea
esta casa encontrando la misma forma — es lo que cerraría eso, y no lo tenemos.

## Un control que no dispara invalida la SECCIÓN, no el HALLAZGO

**Es la diferencia entre una medición que se DESCARTA y una que se REHACE**, y sin la distinción
escrita un control fallado se lee como que el hallazgo era falso.

Cuando el par control/caso no diverge, lo que quedó probado es que **el instrumento no estaba
apuntando**: no se aprendió nada, ni a favor ni en contra. El hallazgo sigue exactamente donde
estaba — ni confirmado ni refutado — y lo que hay que hacer es **construir el control bien**, no
retirar la afirmación.

**Y el control fallado se reporta.** Esconderlo deja una sección que se lee como medida cuando no
lo está.

**Los dos casos del mismo día (2026-09-01):**

- Renombré `payload.dayKey` esperando que el veredicto cambiara y no cambió. **El control estaba
  mal armado**: el rango declarado dejaba `DAY_OPENED` adentro, así que la clave no se consultaba
  nunca. Rehecho sobre `certificate-truncated.json`, donde sí se consulta, disparó — de
  `RANGE_TRUNCATED` exit 1 a exit 0 limpio.
- En DEF-6, el control se construyó a propósito para separar cuatro casos (cortado, adulterado,
  cortado *y* adulterado, hueco en el medio) **antes** de tocar el código.

**Corolario sobre la forma más fuerte de control:** cuando un arreglo tiene que cambiar una
conducta y **preservar** otra, los tests de la conducta preservada deben pasar en **las dos**
versiones, y sólo los que afirman el arreglo deben fallar contra la vieja. Eso prueba que el
cambio tocó lo que quería **y nada más** — es más fuerte que «todo verde después».

## La cadena no se puede truncar por adelante

**Un prefijo que encadena entero es una historia real que termina antes de tiempo. Un eslabón roto
en el medio es otra cosa.**

Es una propiedad estructural de cualquier log append-only encadenado, y **separa PÉRDIDA de
MANIPULACIÓN sin costar nada**: no hace falta un campo nuevo, no toca ningún contrato, ya está en
los datos. Es el único discriminador gratis que tenemos.

**Cómo se usa:** si faltan entradas y las que faltan forman un **sufijo**, y lo presente verifica
hasta génesis, el archivo se cortó — no lo falsificaron. Eso es *no pude mirar* (exit 2), no *te
agarré mintiendo* (exit 1). Un hueco en el **medio**, o un eslabón que no recomputa, es la otra
historia y se sigue leyendo como tal.

**Caso que la originó (2026-09-01):** dos cortes de luz en 48 horas. El ledger hace `fsync` por
línea, así que un corte deja el archivo cortado en un límite de línea — filas enteras, JSON válido,
sólo que menos. El verificador lo llamaba `CONTRADICTED` y, con tres filas perdidas, publicaba que
el trader **se pasó de su límite**. Todos los demás defectos de esta casa eran la herramienta
**afirmando de más**; ése era la herramienta **acusando a un inocente**, y el certificado existe
para mostrárselo a un tercero que va a actuar sobre él.

**Y el control que va con ella, porque es el que importa:** al enseñarle a un verificador a
reconocer la pérdida, **la detección de manipulación tiene que seguir intacta**. Si el arreglo del
caso benigno también apaga el caso malicioso, se cambió un daño por otro peor. Se prueba con el
archivo adulterado, y con uno que esté cortado **y** adulterado a la vez.

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
