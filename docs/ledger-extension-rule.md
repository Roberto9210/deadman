# Cómo se extiende el ledger — cuatro defectos vivos, y la regla que va encima

> **La pregunta tiene dos mitades y este documento contesta las dos.** La aditiva —¿admite el
> formato un campo o un evento que no conoce?— es §5.1-§5.6. La **sustractiva** —¿admite que una
> clave que sí conoce FALTE?— es §5.8, y la respuesta es distinta, porque **un campo desconocido es
> inerte y una clave ausente puede APAGAR UN CHEQUEO.**

**De:** la sesión de `deadman` (la librería)
**Asunto:** cuatro defectos en la verificación de evidencia, y la regla de extensión del ledger
(mitad aditiva y mitad sustractiva)
**Estado:** los defectos son hallazgos medidos, no propuestas. **Todo lo marcado RULING está
DECIDIDO por el operador** — la salida de DEF-1, la de DEF-2, §5.3, §5.4, §5.6, §5.7 y el orden de
trabajo (§8), el 2026-08-31; §5.8, la mitad sustractiva, con su corolario, el 2026-09-01. Nada
está implementado, en ningún lado.

Sale de cuatro pedidos del lado del guardián. Tres son ADITIVOS — un evento nuevo (acuse de
recibo), el `buildHash` en `GUARDIAN_STARTED`, el `dayKey` en `CONFIG_LOADED` — y el cuarto va en
dirección contraria: **seis sitios con `?? ""` cuyo arreglo correcto es OMITIR la clave.**
Buscando si el formato los admitía aparecieron cuatro defectos que no dependen de esos pedidos y
que hay que arreglar antes.

Todo se midió contra el código real y el ejemplo empaquetado (`deadman/examples/certificate/`),
cada caso con su control, para que un resultado que pasa se sepa capaz de fallar. Donde no
verifiqué, lo digo.

**Lo que no pude verificar:** el repositorio `deadman-guardian` no es mío y no lo leí. Todo lo que
digo del emisor sale del ejemplo empaquetado en *este* repo y de
`docs/request-to-guardian-emitter.md`.

---

# PARTE I — LOS CUATRO DEFECTOS

Los cuatro van **antes** de la regla de extensión. Tienen prioridad por ejes distintos y conviene
no fingir un único orden:

| | eje | ¿necesita un atacante? | ¿bloquea la regla? |
|---|---|---|---|
| **DEF-2** atribución de causa por adyacencia | emite afirmaciones falsas **hoy**, en operación normal | **no** | no, pero bloquea el pedido 1 |
| **DEF-1** el campo top-level que nadie firma | rompe la propiedad que da valor al producto entero | sí (acceso a disco) | **sí** |
| **DEF-4** omitir `session.dayKey` apaga el chequeo de truncamiento | **desactiva en silencio** la protección contra la mentira más peligrosa del formato | no — basta con **omitir** | no, pero decide §5.8 |
| **DEF-3** la regla 5 lee claves de datos como nombres de campo | acusa en falso a contenido honesto | no — basta con **nombrar** un evento | no |

DEF-3 hoy **no muerde**: barrí el vocabulario entero y no hay colisiones. Pero no muerde por
suerte, no por diseño, y la suerte no escala. Va con prioridad menor y con la prueba que la cierra.

**DEF-4 es urgente por coincidencia de calendario**, no por gravedad intrínseca: el emisor está por
limpiar seis `?? ""` reemplazándolos por omisión, y **uno de los campos de ese mismo objeto no se
puede omitir sin desarmar una protección.** Si la limpieza sale antes que la regla, sale mal.

**Si sólo se puede uno primero: DEF-2.** No necesita adversario, ya está produciendo atribuciones
falsas, y es el más barato de arreglar. DEF-1 es el que impide *escribir* la regla, porque la regla
dice «ignorar un campo desconocido» y eso sólo es seguro si el campo está dentro del cuerpo hasheado.

---

## DEF-1 — El campo top-level que nadie firma

### Qué es

`deadman/verify_certificate.py:122-125` (`_kit_body`) y `deadman/ledger.py:107-110` (`_entry_hash`)
computan el hash sobre **siete campos nombrados**. Un campo top-level fuera de esa lista no entra
en el hash: se puede agregar, editar o borrar con acceso a disco y `verify()` sigue diciendo `OK`.

Medido por dos caminos independientes, con control:

| caso | dialecto | veredicto |
|---|---|---|
| campo top-level inyectado, **hash sin tocar**, vía `Ledger.verify()` | kit | `ok=True`, code `OK` |
| campo top-level inyectado, **hash sin tocar**, vía `verify_certificate` | kit | exit **0**, `chain_ok=True` |
| **CONTROL** el mismo valor dentro de `payload` | kit | `HASH_MISMATCH` / `CHAIN_BROKEN`, exit **1** |
| **CONTROL** lo mismo en el dialecto del guardián | guardian | `CHAIN_BROKEN` en seq 1, exit **1** |

`guardian-core-v1` no lo tiene: hashea **todo menos `hash`** (`:117-119`). El agujero es sólo del
dialecto del kit — el de esta librería.

Hoy el único campo fuera de los siete es `sig` (`deadman/ledger.py:66,70-72`), excluido a propósito
porque firma el hash y no puede estar adentro. Esa excepción es una decisión escrita. El agujero es
que **cualquier otro campo hereda la exclusión sin la decisión.**

### Las dos salidas, con el costo medido

> **Corrección al enunciado del ruling, y la traigo al frente porque es mía.** Escribí en la sonda
> el print «todo ancla publicada se convierte en `ANCHOR_MISMATCH`» **antes** de correrla. La
> medición lo desmintió: el ancla no cambió. La opción A **no rompe compatibilidad de hashes**.
> Dejo el error visible porque el resultado correcto salió de una sonda con una conclusión
> pre-escrita adentro, y eso es exactamente la forma que la casa vigila.

**Opción A — el cuerpo cubre todo menos el propio hash.**

Primero, un límite que no se puede saltear: **«todo menos `hash`» es imposible.** `sig` se deriva
del hash — medido: `signer(hash) == sig` → `True`. Si el cuerpo incluyera `sig`, el hash dependería
de `sig` y `sig` de él. Así que la opción A es necesariamente una **lista negra de dos nombres**
(`hash`, `sig`), no la ausencia de nombres.

Eso no la debilita; es lo que la hace valer. **Invierte el default**: hoy un campo nuevo nace
*fuera* del hash, con A nace *adentro*.

| costo | medido |
|---|---|
| hashes existentes | **CERO**. Para toda entrada que el kit escribe, lista-negra ≡ lista-blanca, byte por byte: `Entry` es un dataclass congelado con exactamente esos 8 campos + `sig` opcional (`ledger.py:56-72`), y `sig` es el único extra (medido) |
| anclas ya publicadas a un tercero | **CERO**. El `(seq, hash)` anclado no cambia (medido) |
| `schema_version` | **no sube** para adoptarla. Por la regla de §3.1 sube sólo si un verificador recomputara un hash *distinto* sobre los mismos bytes — y sobre bytes válidos computa el mismo |
| tests con hashes fijados | ninguno (no hay hashes del kit pinneados en `tests/`) |
| entradas que **sí** cambian de veredicto | exactamente las que llevan un campo top-level extra — o sea, hoy, exactamente las manipuladas. Eso es el arreglo funcionando |

Costos reales que sí tiene, y no son de compatibilidad hacia atrás sino hacia adelante:

- **Un verificador viejo rechaza un ledger que use de verdad un campo top-level nuevo.** El viejo
  usa lista blanca, computa otro hash, da `CHAIN_BROKEN`. Por eso *escribir* uno de esos campos
  —no adoptar A— es lo que obliga a `schema_version: 2` con despacho por versión. Medido que
  funciona: un ledger mixto v1+v2 recomputa entero, las entradas v1 **conservan el hash con el que
  se escribieron**, el campo extra de la v2 queda dentro de su hash, y manipularlo lo rompe.
- **El hash pasa a depender de campos que ningún esquema restringe.** Es el punto —es lo que hace
  seguro ignorar— pero significa que un bug del productor que escriba basura top-level queda
  grabado como evidencia hasheada y permanente.
- **No puedo descartar** que un ledger de terceros escrito por código ajeno al kit lleve campos
  extra top-level y hoy verifique OK; bajo A pasaría a `HASH_MISMATCH`. El kit **no puede**
  producir uno (el dataclass congelado lo impide), así que el riesgo es sólo para productores de
  fuera. No lo verifiqué: no tengo esos ledgers.

**Opción B — rechazo duro del campo top-level desconocido.**

| costo | medido |
|---|---|
| hashes | cero, obviamente |
| lista de nombres | **no la elimina, la duplica**: hay que permitir `sig` explícitamente, así que quedan **dos** listas que mantener sincronizadas — los siete que se hashean y los ocho que se permiten |
| el dialecto | queda con dos clases de campo para siempre, y la frontera entre clases **no se ve en los datos** |
| extensión futura | el dialecto del kit no puede llevar nunca un campo top-level nuevo; todo va dentro de `payload` |

Y el costo que la vuelve incoherente con el ruling de §3.3: **B es un rechazo.** El ruling reserva
el rechazo porque un verificador viejo declarando inválido un ledger legítimo es catastrófico. Bajo
B ese caso se evita sólo mientras nadie viole una regla que hoy vive en un documento que **no
existe** (§6). Es seguridad apoyada en un papel que falta.

### — RULING — Opción A, aprobada

**El cuerpo hasheado pasa a ser lista negra de dos nombres: `hash` y `sig`.**

La razón, escrita como corresponde y no como «es más limpia»:

> **A no es «la ausencia de nombres» — `sig` se deriva del hash, así que es una lista negra de dos.
> Pero INVIERTE EL DEFAULT. Hoy un campo nuevo nace fuera de la firma; con A nace adentro. Eso es
> todo lo que importa.**

No rompe compatibilidad de hashes: ninguna, medido. El costo hacia adelante —`schema_version: 2`
con despacho por versión, cuando alguien escriba de verdad un campo top-level nuevo— **es el
momento correcto para pagarlo**, y está medido funcionando sobre un ledger mixto v1+v2.

Y satisface la condición del ruling §5.3 de forma nativa: con A **todo** campo desconocido está
dentro del cuerpo hasheado, así que «ignorar» es seguro sin excepciones que recordar.

**B queda descartada.** No elimina la lista de nombres: la duplica. Y es un rechazo, que §5.3
reserva para lo catastrófico.

---

## DEF-2 — La causa atribuida por adyacencia

### Qué es

`deadman/verify_certificate.py:974-982` toma el evento **inmediatamente anterior** al
`FAIL_CLOSED_ENTERED` y lo publica como `triggerEvent` — la causa. La única exclusión es
`_BOUNDARY`. Todo lo demás califica.

**No hace falta un evento nuevo para que produzca una causa falsa.** Medido, insertando eventos que
ya existen en el vocabulario del guardián justo antes del `FAIL_CLOSED_ENTERED`:

| evento insertado (todos existentes hoy) | `triggerEvent` resultante |
|---|---|
| `PNL_CHECKPOINT` | `"PNL_CHECKPOINT"` |
| `CONFIG_LOADED` | `"CONFIG_LOADED"` |
| `DAY_OPENED` | `"DAY_OPENED"` |
| `SEAL_CREATED` | `"SEAL_CREATED"` |
| *(control, sin insertar nada)* | `"ACCOUNT_UNKNOWN"` |

Un chequeo de P&L de rutina que casualmente caiga antes de la desconexión queda publicado como su
causa. El acuse de recibo no crea el defecto: lo vuelve vistoso, porque «el guardián se quedó ciego
porque una persona miró el aviso» es imposible de leer sin notarlo.

### La segunda capa, que es peor

`triggerEvent` y `triggerSeq` **nunca se comparan contra el ledger.** La comparación de episodios
(`:1200-1209`) sólo mira `reasons` y `open`. Medido, con control:

| caso | veredicto |
|---|---|
| `triggerEvent` y `triggerSeq` del certificado reemplazados por una fabricación | exit **0**, cero contradicciones |
| **CONTROL** `reasons` falsificado (ese sí se compara) | `CLAIM_MISMATCH`, exit **1** |

Un certificado puede afirmar **cualquier** causa. El campo que asigna culpa es el único del bloque
de episodios que nadie verifica.

### Por qué es la clase madre de la casa

El código conoce su propia regla y la defiende, en `:963-967`:

> *«The rule is positional and published — `triggerSeq` names the exact entry counted, so nothing
> is inferred from the text of `reason`.»*

La defensa es real y es insuficiente. Publicar la regla evita inferir de un texto libre; **no
convierte adyacencia en causalidad.** Y el nombre del campo hace la afirmación que el cómputo no
respalda.

Es la regla 5 del propio verificador, aplicada a su propia salida. La pregunta de la regla 5 es
*¿qué distingue?*: `triggerEvent` promete «lo que disparó el episodio» y entrega «lo que pasó
justo antes». Dos cosas que deberían diferir —una causa y una coincidencia— producen el mismo
valor. Por el criterio que este repo le exige al emisor, el campo **se omite o se renombra**.

### — RULING — Tres partes, y las tres hacen falta

Arreglan **defectos distintos**. Ninguna sustituye a otra.

**1. Renombrar `triggerEvent`/`triggerSeq` → `precedingEvent`/`precedingSeq`.**
Arregla **la mentira**: el nombre promete causa y entrega adyacencia. No pierde información — un
lector que quiera investigar sigue teniendo el `seq`.

*(Derivar la causa de verdad exigiría que `FAIL_CLOSED_ENTERED` llevara su motivo en el payload —
ítem 4 de `request-to-guardian-emitter.md`, ya pedido y ya respondido: no alcanzable sin I/O nueva
en el camino peligroso. Por eso renombrar es la corrección disponible, no un parche provisional.)*

**2. Compararlo contra el ledger.**
Arregla **la falta de evidencia**: el único campo del bloque de episodios que nadie verifica es
justamente el que asigna culpa. **Eso es indefendible en un artefacto de evidencia.**

**3. El certificado tiene que DECLARAR que no establece causas.**

Con el campo renombrado y verificado seguimos publicando el evento anterior — que es útil para
reconstruir una línea de tiempo, y es **exactamente la inferencia equivocada que un lector va a
hacer solo**. Hoy la hace el código; mañana la haría el lector, con los mismos datos.

Va en el bloque de limitaciones, donde ya vive la ausencia del ancla: mismo patrón y por el mismo
motivo. **Decir qué se observó, nunca qué se concluyó.**

Texto propuesto, para el quinto elemento de `REQUIRED_LIMITATIONS`
(`deadman/verify_certificate.py:154-162`):

> *"This does not say what caused anything. Events are recorded in the order they happened; the
> order is not a cause."*

**La secuencia está forzada por una medición, y hay que respetarla:**

| paso | medido |
|---|---|
| **primero** el emisor empieza a escribirla | un certificado con una quinta limitación que el verificador **no** exige verifica **limpio, exit 0** — los extras están permitidos (`:1220-1221` sólo comprueba que estén los requeridos) |
| **después** el verificador la exige | al agregarla a `REQUIRED_LIMITATIONS`, **todo certificado ya emitido pasa a `LIMITATIONS_ALTERED`, exit 1** — medido sobre los cuatro ejemplos empaquetados, los cuatro |

Invertir el orden contradice una decisión vigente: `request-to-guardian-emitter.md` §«What we are
not asking for» dice explícitamente **«No re-issue of existing certificates»**. Exigirla antes de
que el emisor la escriba convertiría en inválidos documentos honestos, que es el mismo error que
§5.3 llama catastrófico.

El texto canónico vive sólo en `verify_certificate.py` y los tests lo derivan de ahí
(`tests/test_c_certificate.py:134`), así que el paso 2 no arrastra ediciones dispersas. Los cuatro
JSON de ejemplo sí llevan copia congelada y se regeneran con `make_example.py`.

---

## DEF-4 — Omitir una clave conocida puede apagar un chequeo, en silencio

### El caso, sobre el ejemplo que el propio repo publica

`certificate-truncated.json` es el ejemplo empaquetado de lo que el código llama *«the most
dangerous lie the format allows»* (`:592`): un rango declarado corto para que la parte incómoda del
día quede afuera. **No contiene ninguna afirmación falsa** — por eso es peligroso.

| el MISMO certificado mentiroso | veredicto |
|---|---|
| tal como se publica | **`RANGE_TRUNCATED`, exit 1** |
| con `session.dayKey` **omitido** | **exit 0** — baja a `POST_RANGE_MATERIAL_EVENTS`, que no falla |
| con `session.dayKey = null` | **exit 0** |
| con el bloque `session` entero omitido | **exit 0** |

El mecanismo está a la vista: `_check_range_covers_its_day` abre con
`day = (cert.get("session") or {}).get("dayKey")` y todo el chequeo vive dentro de
`if day is not None:` (`:604`, `:620`). **Sin `dayKey` no hay contra qué anclar, así que no se
chequea — y no se dice que no se chequeó.**

### Por qué esto contesta la mitad sustractiva y no la aditiva

Es la diferencia entera entre las dos preguntas, en un solo caso:

> **Un campo que el verificador no conoce es INERTE: no puede apagar nada. Una clave conocida que
> falta puede apagar un chequeo — y el documento que resulta es MÁS SILENCIOSO, no más ruidoso.**

Por eso «ignorar lo desconocido» (§5.3) es seguro y «ignorar lo ausente» no lo es. Son reglas
opuestas para casos que se parecen.

### El agravante: la limpieza de los `?? ""` está por salir

El emisor tiene seis lugares con `?? ""` y el arreglo correcto es omitir la clave. Medido, sobre
`session.timezone`, que es uno de los seis:

| | veredicto |
|---|---|
| `timezone = ""` (lo que hace hoy el `?? ""`) | **exit 1, `DECORATIVE_FIELD`** |
| `timezone = null` | exit 0, limpio |
| `timezone` **ausente** | exit 0, limpio |

Así que el `?? ""` **ya está produciendo certificados que fallan** — la corrección no es cosmética.

> **CONFIRMADO DESDE LOS DOS LADOS (2026-09-01).** Nosotros medimos que `""` da exit 1 con
> `DECORATIVE_FIELD`; el lado del guardián confirma que `session.timezone` **sale vacío hoy** por
> la ruta de LT-2 — el reinicio que restaura `ARMED` desde el sello. Es decir: no es un borde
> teórico ni un descuido de estilo, es **un camino que el producto recorre normalmente**.
>
> Eso lo cambia de categoría: de **defecto de honestidad** a **falla funcional en ruta
> alcanzable**, y por eso sube en el orden de trabajo (§8). Un certificado emitido después de un
> reinicio normal falla la verificación.
Pero `dayKey` vive en el mismo objeto `session`, y ahí omitir desarma una protección. **El mismo
patrón de arreglo, aplicado a dos campos vecinos, da un resultado correcto y un desastre.**

### La salida

`session.dayKey` ausente tiene que pasar de **silencio** a **`cannot_verify`**: el chequeo de
cobertura no corrió, y eso se dice. No a contradicción — un certificado sin `dayKey` no es falso,
es menos verificable, y §5.3 ya fijó que acusar a un documento honesto es catastrófico.

La regla general que lo cubre, y el resto de los casos, es §5.8.

---

## DEF-3 — La regla 5 lee claves de datos como si fueran nombres de campo

### Qué preguntó Ventana A, y la respuesta

`ACCOUNT_UNKNOWN` es un nombre de evento legítimo (`Ledger.cs:28`) y llega al certificado como
valor de `triggerEvent` y como **clave** en `reasons`. La pregunta: ¿`DECORATIVE_FILLER` lo atrapa?

**No. Riesgo cerrado, y no por argumento — ya está en la superficie de regresión del repo.** El
certificado de ejemplo empaquetado lleva hoy mismo `"triggerEvent": "ACCOUNT_UNKNOWN"` y
`"reasons": {"ACCOUNT_UNKNOWN": 3}`, y verifica **limpio, exit 0**.

Las tres propiedades, medidas una por una:

| propiedad | ¿se cumple? | medido |
|---|---|---|
| **comparación por valor completo, no subcadena** | **SÍ** | `ACCOUNT_UNKNOWN`, `UNKNOWN_STATE`, `unknown_account`, `the state is unknown` → todos limpios. Sólo `unknown` exacto dispara |
| **sobre VALORES, no claves** | **SÍ** | las claves de `reasons` van al *path*, no al valor; los valores son enteros y el chequeo exige `isinstance(value, str)` |
| **sensible a mayúsculas** | **NO** — normaliza con `.lower()` y `.strip()` | `UNKNOWN`, `Unknown`, `NONE`, `None`, `TBD`, `N/A`, `" unknown "` → todos disparan |

### Sobre la tercera: hacerla sensible a mayúsculas la DEBILITARÍA

Es la única de las tres que no se cumple, y creo que la regla propuesta es la equivocada, por un
motivo que se ve al mirar la lista: **`TODO`, `TBD`, `XXX` y `N/A` son relleno que en la vida real
se escribe en MAYÚSCULAS.** Una comparación sensible a mayúsculas los dejaría pasar a todos —
perdería contra su blanco principal para protegerse de una colisión que hay que demostrar que
existe.

La propiedad que hace falta no es la sensibilidad a mayúsculas. Es **no colisionar con el
vocabulario legítimo, probado.** Y eso se demuestra con un barrido, no con una regla de
comparación. Lo hice (abajo): cero colisiones hoy.

Queda un residuo honesto que **no puedo cerrar solo**: si el guardián tiene un literal de estado
`"UNKNOWN"` o `"NONE"` —no un evento, un *estado*— dispararía. No puedo leer ese repositorio. Es
el ítem 6 del aviso: que nos manden el conjunto enumerado de literales.

### El defecto que sí encontré, que es la misma familia un piso más abajo

El **otro** chequeo de la regla 5, `_promise_violations` (`:194-237`), no mira el valor: deriva un
nombre de campo del **último segmento del path** (`:213-214`). Y las claves de `reasons` y de
`clockAnomalies.byType` **son nombres de evento**. Es decir: la regla 5 lee un nombre de evento
como si fuera un nombre de campo del esquema.

Medido, con el valor siendo el contador entero:

| clave de `reasons` | veredicto |
|---|---|
| `SEAL_HASH` | `FIELD_BELIES_ITS_NAME` — «named for a cryptographic hash but holds 1» |
| `CONFIG_HASH` | `FIELD_BELIES_ITS_NAME` |
| `DAILY_LOSS`, `LOSS_LIMIT`, `SOFT_LIMIT` | `FIELD_BELIES_ITS_NAME` — «named for money but holds 1» |
| `EXPIRES_AT_UTC` | `FIELD_BELIES_ITS_NAME` — «the name promises a point in time» |

**Hoy no muerde**, barrido completo: los 27 nombres de evento del guardián visibles desde este repo
y los 19 `KINDS` del kit, por `reasons` y por `clockAnomalies.byType` — **cero colisiones**.

Pero es por suerte. `SEAL_MISMATCH` se salva porque termina en `match` y no en `hash`;
`LIMIT_BREACHED` porque termina en `breached` y no en `limit`. **Basta con que alguien nombre un
evento `CONFIG_HASH` —y `CONFIG_LOADED` ya lleva un `configHash` en su payload— para que todo
certificado que lo cuente entre sus razones falle acusando al trader de un campo decorativo que
nunca escribió.**

### La clase, nombrada

**Derivar un nombre de campo del último segmento de un path y aplicarlo a claves que son nombres de
evento es una regla cierta sobre un conjunto, aplicada a otro.** La ausencia de colisiones hoy
prueba suerte, no diseño. Tiene que volverse estructural.

### La salida, prototipada y medida

Descarté una de las tres candidatas **con un test que ya existe**, no por opinión:

- **Chequear sólo valores de tipo cadena** (así una cuenta entera nunca se acusa). **Descartada:**
  `tests/test_c_rule_five.py:68-76` fija a propósito que `personalDailyLossLimit = 600` —un
  entero— dispare `FIELD_BELIES_ITS_NAME`, con su motivo escrito: *«a float here is a rounding bug
  waiting for a bad day»*. Esta salida rompería esa protección.
- **Declarar los contenedores de claves libres** (`reasons`, `byType`) y no usar sus claves como
  nombres. Correcta, pero su modo de falla es el malo: el día que aparezca un contenedor nuevo y
  alguien olvide declararlo, **vuelve la acusación falsa.**
- **INVERTIR: las promesas se aplican sólo a nombres que el ESQUEMA DEL CERTIFICADO posee.**
  Un nombre que no está en el conjunto no se acusa.

**La inversión es la que va**, y el argumento decisivo es el modo de falla. Si alguien agrega un
campo de esquema con promesa y olvida declararlo, el chequeo **calla**. Si alguien agrega un
contenedor de datos y olvida declararlo, el chequeo **acusa**. El propio archivo ya eligió esa
dirección, por escrito, en `:198-200`: *«the cost of a false accusation here is a certificate
wrongly refused, so the checks err toward silence.»* Hoy la regla 5 viola su propia calibración; la
inversión la restituye.

Y contesta la objeción que yo misma había puesto —«convierte la regla 5 en una lista que hay que
mantener»—: sí es una lista, pero es **nuestra y cerrada** (los nombres del esquema del
certificado), no la del guardián (abierta, creciente y ajena), y **omitir de ella produce silencio,
no una acusación.**

La regla general que sale de haber elegido así, y que vale más que este arreglo:

> **ENTRE DOS ARREGLOS CORRECTOS, GANA AQUEL CUYO MODO DE FALLA COINCIDE CON LA CALIBRACIÓN QUE EL
> MÓDULO YA DECLARÓ.**

No se eligió por elegante ni por más chica. Se eligió porque declarar contenedores **falla
acusando** y la inversión **falla callando**, y el archivo dice por escrito que una acusación falsa
cuesta un certificado injustamente rechazado. La calibración ya estaba tomada; el arreglo sólo
tenía que no contradecirla.

**Prototipada y corrida contra la suite real** (parche en el scratchpad, nada aplicado al repo):

| | resultado |
|---|---|
| `tests/test_c_rule_five.py` | **12/12 pasan** (baseline sin parche: 12/12) |
| suite entera del certificado (4 archivos) | **88/88 pasan** |
| `reasons` con `CONFIG_HASH`, `SEAL_HASH`, `DAILY_LOSS`, `SOFT_LIMIT`, `EXPIRES_AT_UTC` | de `FIELD_BELIES_ITS_NAME` a **limpio**, los cinco |
| `buildHash: "example"` / `"latest"`, `sealHash: "abc123"`, `armedAtUtc: "this morning"`, `personalDailyLossLimit: 600`, `version: "1.0.0.0"` | **se siguen atrapando**, los seis |

### La inversión es NECESARIA y NO ALCANZA — corrección, con lo que la destapó

Escribí que «con la inversión aplicada ese test pasa por construcción». **Medido, es falso**, y lo
que lo destapó vino del lado del guardián: `triggerEvent` es un **pasamanos** (`Certificate.cs:223`),
copia lo que la fila diga sin validar contra ningún enum. O sea que un nombre de evento no llega
sólo como **clave** de `reasons` — llega también como **valor** de un campo de cadena. Y
`DECORATIVE_FILLER` chequea **todos** los valores de cadena, por cualquier path.

La inversión arregla `_promise_violations`, que es la mitad de las claves. No toca la otra mitad.
Medido sobre 144 nombres generados adversarialmente:

| | hoy | con la inversión sola | con la inversión + procedencia |
|---|---|---|---|
| como **clave** de `reasons` | **31 fallan** | 0 | 0 |
| como **valor** de `triggerEvent` | **44 fallan** | **44 fallan** | 0 |

Los 44 son nombres como `UNKNOWN`, `NONE`, `TBD`, `CHANGEME`, `BAR`, `1.0.0.0`. Ninguno existe hoy;
todos son nombres que alguien puede elegir mañana. **Sin el aporte del otro lado habría entregado
medio arreglo con un test que pasaba** — y pasaba por el motivo equivocado, que es verificación
cómplice otra vez.

**Y lo que la hizo visible fue el generador, no el ojo.** Los 144 nombres son **generados
adversarialmente** —cada sufijo al que reaccionan las promesas cruzado con cada palabra de la lista
de relleno cruzado con los prefijos que un vocabulario real produce—, no cosechados del vocabulario
que existe. **Un barrido sobre los 37 nombres reales habría dado verde**, y el verde habría
certificado el arreglo a medias. Cosechar el conjunto real y barrerlo es exactamente el instrumento
contestando por el sujeto, un piso más arriba: el conjunto de hoy no falla porque nadie eligió
todavía un nombre que falle.

### — RULING — la regla 5 se aplica según la PROCEDENCIA del campo

> **El chequeo de relleno se aplica a los campos que llena el PRODUCTOR. Nunca a los que aporta una
> PERSONA.**
>
> Un productor que escribe `"unknown"` está tapando un hueco. Una persona que escribe `"unknown"`
> está diciendo su nombre. Es la misma cadena y son cosas distintas, y lo que las distingue es **de
> dónde vino**.

La taxonomía completa que hace falta para escribir el arreglo, con la tercera procedencia que sale
del pasamanos:

| procedencia | ejemplos | qué chequeo corresponde |
|---|---|---|
| **el productor la redacta** | `buildHash`, `version`, `sealHash`, `session.timezone` | **relleno SÍ.** Es su palabra, y un relleno ahí tapa un hueco |
| **una persona la aporta** | `subject.alias` | **relleno NO.** Su alias es su nombre. Que el producto le diga a un usuario que su nombre es inválido sería absurdo, y el riesgo de excluirlo es nulo: el chequeo sólo rechaza, no se lo puede engañar para que apruebe |
| **se copia de la evidencia** | `triggerEvent`/`precedingEvent`, claves de `reasons` y de `byType` | **relleno NO — se COMPARA contra el ledger**, que es estrictamente más fuerte. Juzgar su forma es juzgar el vocabulario ajeno; compararlo prueba que el certificado dice lo que la evidencia dice |

La tercera fila es la que cierra los 44, y el principio que hay debajo vale más que el caso:

> **COMPARACIÓN Y FORMA SON VERIFICACIONES ALTERNATIVAS, NO COMPLEMENTARIAS.**
>
> Si un campo se puede comparar contra su fuente, **se compara** — y entonces chequearle la forma
> sólo puede producir falsos positivos, porque su forma **la decide otro**. Si no se puede
> comparar, ahí sí la forma es lo único que queda.

Encaja con el ruling de DEF-2 parte 2 sin forzarlo: `precedingEvent` deja de juzgarse por forma
**justamente porque empieza a compararse**. Los dos cambios son el mismo cambio visto de los dos
lados — no dos arreglos que hay que acordarse de aplicar juntos.

### La prueba: una PROPIEDAD, no un conjunto

**El barrido no debe probar «estos 37 no colisionan». Eso probaría un resultado.** Producción ya
tiene 24 `buildHash` distintos en 8.027 entradas, y un ledger real puede traer nombres de builds
viejos o futuros. El conjunto de hoy no es una propiedad — es la lección de toda la tanda.

El test se escribe así:

> **Ningún nombre de evento, sea cual sea, puede hacer que un certificado falle la regla 5 — ni
> como clave de `reasons`, ni como valor de `precedingEvent`.**

y se corre contra nombres **generados adversarialmente**: cada sufijo al que reaccionan las
promesas (`HASH`, `LOSS`, `LIMIT`, `UTC`, …) cruzado con cada palabra de `DECORATIVE_FILLER`,
cruzado con los prefijos que un vocabulario real produce. Los 144 de la tabla de arriba son ese
generador. La enumeración del guardián sigue siendo útil —como caso de humo y para no confundir una
fixtura con relleno— pero **no es lo que el test asegura.**

**Nota para quien lo escriba:** los C-tests del guardián emiten `buildHash: "test"`. Eso **debe**
seguir disparando `DECORATIVE_FIELD` — `"test"` en un campo que el productor redacta es relleno de
verdad. Lo que no hay que hacer es cosechar valores de la salida de esos tests como si fueran
vocabulario de producción.

### Medido, todo junto

| | resultado |
|---|---|
| propiedad 1, 144 nombres adversariales, clave y valor | **0 fallan** (hoy: 31 y 44) |
| `subject.alias` = `"unknown"` / `"example"` / `"none"` | **limpio** (hoy: `DECORATIVE_FIELD`) |
| `buildHash` = `"example"` / `"test"`, `timezone` = `""`, `version` = `"1.0.0.0"` | **se siguen atrapando**, los cuatro |
| suite entera del certificado, 5 archivos | **100/100 pasan** |

---

# PARTE II — LOS HALLAZGOS SOBRE EL FORMATO

## 1. Qué hace hoy el verificador ante un campo desconocido

**Nada.** Sólo existe un chequeo de **presencia**: `_check_dialect` (`:520-538`) exige que estén
los campos de `dialect.required` en **todas** las entradas. Sobre las claves de más no dice nada,
porque nunca las mira. Que el chequeo de presencia muerde, medido: una entrada nueva **sin**
`payload` da `DIALECT_MISMATCH`, exit **1**, más `NOTHING_ELSE_CHECKED`.

**La regla 5 no protege el ledger.** `check_rule_five` se llama sólo sobre el certificado (`:1212`,
`:1476`). El receptor exige que el certificado no tenga campos decorativos, y no exige nada de la
evidencia de la que ese certificado se deriva.

## 2. Qué hace ante un tipo de evento desconocido

**No existe lista blanca de eventos.** Los nombres se comparan literalmente uno por uno (`:570`,
`:574-578`, `:694`, y comparaciones sueltas en `:621,622,634`). Un nombre que no figura no coincide
con nada, y `_verify_chain` (`:541-563`) nunca mira el nombre ⇒ **un evento desconocido se verifica
en la cadena como cualquier otro.**

Del lado que **escribe** es al revés: `deadman/ledger.py:246-247` rechaza un kind fuera de `KINDS`
salvo `allow_unknown_kinds=True`.

**Pero un evento desconocido no es inerte**, por el cajón de sastre de `:989-990` (cualquier evento
durante un episodio entra en sus `reasons`) y por DEF-2. Medido: un acuse dentro del episodio
aparece en `reasons`; justo antes, queda como `triggerEvent`; y el certificado resultante verifica
**limpio, exit 0**.

## 3. ¿Está escrita como decisión, o es accidental?

**Accidental, con una media decisión escrita de un solo lado.**

Escrito: `docs/SPEC.md:415` dice «**Kinds mínimos**» — el vocabulario es un piso, no un techo. Y
`ledger.py:247` dice `pass allow_unknown_kinds=True to extend`, una puerta declarada en el texto de
una excepción.

No escrito, verificado por grep: `allow_unknown_kinds` aparece en **4 lugares, los cuatro dentro de
`deadman/ledger.py`** (`:129,138,246,247`) — **cero** en `docs/`, **cero** en `tests/`.
`tests/test_g11_ledger.py:35` prueba únicamente el rechazo. `docs/SPEC.md` no tiene sección de
extensión ni de compatibilidad. Del lado del verificador **no hay nada**; lo más cercano (`:690-694`)
trata de un evento **ausente** en un dialecto, no de uno **desconocido**.

Nadie decidió tolerar; nadie decidió rechazar. El verificador tolera porque `json.loads` tolera.
Ver §6 para la razón de fondo.

## 4. Qué le pasa a `Verify()`

Hay **dos**: `deadman/ledger.py:404-500` (recomputa con `_entry_hash`, `:448`) y
`verify_certificate.py:541-563` (recomputa con `dialect.hash_of`).

**La presunción del enunciado es correcta para `payload`, y no en general.** El hash no se computa
sobre el registro completo sino sobre un *cuerpo*, y cada dialecto lo define distinto (§DEF-1).

Para un campo dentro de `payload` —donde caen los pedidos 2 y 3— se cumple exacta, medido:

| caso | resultado |
|---|---|
| `buildHash` en el `payload` de `GUARDIAN_STARTED`, re-encadenado | limpio, exit **0** |
| **CONTROL** el mismo campo, hash **sin** recomputar | `CHAIN_BROKEN` en seq 1, exit **1** |
| `dayKey` en el `payload` de `CONFIG_LOADED`, re-encadenado | limpio, exit **0** |

Los hashes pasados **no cambian**, el de la entrada modificada cambia, y los futuros encadenan
desde el nuevo. Un ancla previa sigue válida sobre la historia anterior. No hay ruptura, ni
re-emisión, ni migración.

---

# PARTE III — LA REGLA, DECIDIDA

## 5.1 Qué se puede agregar, y dónde

| quiero agregar… | ¿se puede? | condición |
|---|---|---|
| un campo a `payload` de un evento existente | **sí** | las cuatro obligaciones de §5.2 |
| un campo top-level en `guardian-core-v1` | **sí, pero no** | queda hasheado, pero sin ganancia sobre `payload` |
| un campo top-level en `deadman-kit-v1` | **NO hasta que DEF-1/A esté implementado** | hoy quedaría fuera del hash. Con la opción A ya aplicada pasa a **sí, con `schema_version: 2`** y despacho por versión |
| un tipo de evento nuevo | **sí** | §5.2, §5.4 y §5.5 |
| un campo nuevo al certificado | **sí** | entra en `certHash` y en la regla 5; nunca un valor de relleno (§5.6) |

**`schema_version` sube sólo si cambia el cuerpo hasheado o la canonicalización** — es decir, si un
verificador recomputara un hash *distinto* sobre los **mismos bytes**. Ninguno de los tres pedidos
lo hace. Adoptar la opción A tampoco (computa idéntico sobre bytes válidos). *Escribir* un campo
top-level nuevo en el kit sí, y ahí el cuerpo despacha por versión (medido en §DEF-1).

Decirlo importa: subir la versión «por las dudas» obliga a todo verificador desplegado a conocer la
versión nueva para no fallar, que es justo el costo que la regla existe para evitar.

## 5.2 Las cuatro obligaciones de todo campo o evento nuevo

1. **Se hashea.** Va dentro de `payload`, o dentro del cuerpo que el dialecto hashea. Un campo de
   evidencia fuera del hash no es evidencia.
2. **Distingue algo.** La regla 5 aplicada al ledger: si dos situaciones que deberían diferir dan
   el mismo valor, el campo no mide lo que su nombre dice y **se omite**. Hoy la regla 5 sólo corre
   sobre el certificado; esta obligación la extiende al ledger por escrito aunque nadie la chequee
   todavía.
3. **Tiene un lector nombrado.** Un campo que nadie consume es decorativo por la regla 5. Antes de
   escribirlo hay que decir **quién** lo lee.
4. **Se prueba con su control.** Un caso que pasa y un caso mutado que falla.

## 5.3 — RULING — Verificador viejo ante algo que no conoce

**MARCAR para eventos desconocidos. IGNORAR para campos desconocidos.**

- **Rechazar es catastrófico.** Un verificador viejo declararía inválido un ledger legítimo, y un
  tipo de evento futuro invalidaría todos los certificados ya emitidos.
- **Ignorar un evento es una mentira silenciosa.** Dice «todo bien» sobre un registro que contiene
  cosas que no entendió.
- **Marcar dice «verifiqué lo que pude y hay contenido que no comprendo»** — la única honesta, y la
  misma forma que todo lo demás en este verificador: la ausencia habla. Va como `cannot_verify`
  (exit 0, dicho en la cara del informe), la categoría que ya existe para «los bordes de mi propio
  alcance» (`:291-292`), la misma de `NO_EXTERNAL_ANCHOR` y `TRADES_OBSERVED`.

**CONDICIÓN, que ata este ruling a DEF-1:** ignorar un campo desconocido **sólo es seguro si ese
campo está DENTRO del cuerpo hasheado**. Fuera del cuerpo hasheado no se ignora — **no se permite
existir**. Por eso DEF-1 va antes: hoy, en el dialecto del kit, la condición no se cumple.

Riesgo asumido, nombrado: si el formato avanza mucho, la línea de marcado puede volverse rutina y
dejar de leerse — el mismo defecto que la regla 5 combate, un piso más arriba. Se mitiga nombrando
los tipos concretos que no se entendieron, no con un aviso genérico.

## 5.4 — RULING — El acuse no es material, y se hace cumplir por estructura

**Prefijo reservado `HUMAN_*`** para todo hecho sobre la interacción con una persona. Nombre y no
campo, porque `guardian-core-v1` no tiene `actor` (§5.5) y el nombre es lo único que los dos
dialectos comparten.

**La ley:** *ningún evento `HUMAN_*` es insumo de ninguna afirmación recomputada.* No cuenta en
`reasons`, no puede ser `triggerEvent`/`precedingEvent`, no entra en `_MATERIAL`, no toca
`limitRespected` ni la continuidad. **Exclusión explícita en `recompute_claims`, no cuidado** —
cierre por construcción, con su test, y el control es el caso D2 de arriba: hoy pasa y debe pasar
a fallar.

**No es material.** Material significa «su ausencia cambia lo que el documento dice del trader»;
hacerlo material permitiría que un acuse faltante se lea como cargo contra la persona. Un acuse es
**testimonio sobre una persona, no evidencia sobre la cuenta. No cambia un solo número.**

Consecuencia aceptada, medida: un acuse fuera del rango declarado no produce ningún hallazgo,
mientras un `LIMIT_BREACHED` afuera sí produce `POST_RANGE_MATERIAL_EVENTS`. (Nota: los dos dan
**exit 0** — `POST_RANGE_MATERIAL_EVENTS` es `cannot_verify`, no contradicción; la diferencia se ve
en el cuerpo del informe, no en el código de salida.)

**En el certificado viven aparte.** No dentro de `claims` — `claims` es lo que el guardián afirma
de la cuenta. Un bloque propio, p. ej. `acknowledgements`. Un lector no debería tener que conocer
el prefijo para no confundirse.

**Payload mínimo:** el estado acusado y el instante. Nada de identidad de la persona — la SPEC §4.3
y el chequeo `PRIVACY_LEAK` (`:1226-1232`) ya lo excluyen, y «quién exactamente» no hace falta para
el hecho «alguien vio esto».

## 5.5 La frontera, escrita para dentro de un año

> **Toda entrada del ledger afirma que algo OCURRIÓ. Ninguna entrada puede modificar, anular,
> excusar ni reinterpretar el significado de otra. Un evento `HUMAN_*` dice "alguien vio esto";
> nunca "por lo tanto esto no cuenta". Si un evento propuesto sólo tiene sentido leído junto a otro
> al que le cambia el valor, ese evento no se agrega.**

Esta es la frontera que va a tentar a alguien. La tentación tiene forma de campo administrativo:
`"resolved": true`, `"acknowledged": true`, `"waived"`, `"reviewed"`, `"expected": true`,
`"benign": true`, `"falsePositive": true`.

`"falsePositive": true` es el caso límite y conviene mirarlo de frente: es **exactamente** «esto no
cuenta» escrito como si fuera un dato. En el ledger del guardián sería indistinguible de un hecho,
porque nadie firma un juicio sobre qué es un hecho.

**La prueba para el que aplique la regla:** *¿este campo cambia lo que un lector concluye de OTRA
entrada? Entonces no va.*

**Y el corolario, porque es el error del que ya se salió una vez:** la contraparte legítima de
«esto fue un falso positivo» **no es una entrada nueva** — es que el evento original haya llevado
desde el principio el campo que lo distingue. Es la lección del ítem 4b de
`request-to-guardian-emitter.md`: se escribe en el productor, no se infiere después.

**Dos trampas ya presentes**, para que no se copien al diseñar `HUMAN_*`:

- `Ledger.append` tiene `actor: str = "user"` por defecto (`ledger.py:245`). Un append de la máquina
  que se olvide de pasar `actor` **queda registrado como acto de una persona** — un default
  plausible en el campo que decide la categoría, justo lo que la SPEC §2 prohíbe.
- `USER_NOTE` está en `KINDS` (`:49`) y el ejemplo de freqtrade lo usa para notas de la **máquina**
  (`examples/freqtrade/deadman_freqtrade.py:421,473,635,678`). El nombre ya miente sobre quién
  escribió.

Y el material para distinguir está reparado de forma despareja: `deadman-kit-v1` tiene `actor`
(`ledger.py:62`, hasheado en `:109`); `guardian-core-v1` **no** (`verify_certificate.py:132`). **El
dialecto del guardián no puede decir quién hizo algo.**

## 5.6 — RULING — `unknown` se resuelve en el emisor, no en el verificador

**El verificador tiene razón.** `"unknown"` como **cadena** es un default plausible vestido de
honestidad: ocupa el lugar de un valor, se parece a un dato, y un lector distraído lo cuenta como
tal. Una ausencia honesta no se escribe — **se omite, o se declara `null` explícito. El tipo del
campo decide cuál de las dos puede.**

Es la regla de la casa: un default plausible miente, una ausencia dice la verdad callándose.
`DECORATIVE_FILLER` (`:184`) la está haciendo cumplir sin saberlo, y aflojarla sería quitarle al
producto una protección que funciona.

Medido: un `"unknown"` honesto en un certificado da `DECORATIVE_FIELD`, exit **1**.

**Lo que está mal es el pedido 4b**, que pide «un `unknown` explícito, expresable». Tomado
literalmente produce un certificado que rebota. Campo **ausente** o **`null` explícito**, nunca la
cadena.

**Enviado por dos canales, y no es redundancia** (2026-08-31): el documento
`docs/request-to-guardian-causes-and-unknown.md` es el canal durable —sobrevive a esta sesión y a
que alguien se olvide— y el operador se lo pasa a Ventana A en el momento, que es el canal rápido.
El motivo es una lección que vino del otro lado y aplica a nuestro propio proceso:

> **Un documento en un repo que nadie está leyendo es la pestaña Log del guardián. Verdadero,
> escrito, y sin llegar a nadie. El documento no reemplaza el aviso; el aviso no reemplaza el
> documento.**

---

## 5.7 — RULING — Toda contención léxica se prueba contra lo que podría atrapar

> **Una contención léxica tiene que coincidir EXACTAMENTE con lo que prohíbe, y se prueba contra
> los valores legítimos que podría atrapar.**

**Un filtro que prohíbe de más falla ruidosamente sobre contenido honesto, que es peor que no
tenerlo: enseña a desactivarlo.** Ése es el costo real — no el falso positivo suelto, sino que la
primera vez que un filtro acusa a un documento verdadero, alguien aprende que el filtro se puede
apagar, y a partir de ahí no protege de nada.

Nació de que **el mismo error apareció dos veces el mismo día, en los dos lados del sistema**:

- **Lado del guardián:** la contención de los mensajes iba a prohibir la palabra `"cancelled"`, y
  `"0 orders cancelled"` es el reporte cierto de un barrido que sí ocurrió. Se resolvió prohibiendo
  **construcciones**, no palabras.
- **Este lado:** prohibir `"unknown"` atraparía `ACCOUNT_UNKNOWN`. No lo atrapa —la comparación es
  por valor completo (§DEF-3)— pero eso se supo **midiendo**, no diseñando.

Dos sistemas distintos, la misma tentación: escribir la prohibición sobre el fragmento en vez de
sobre la unidad que tiene significado.

**Obligaciones que quedan, para cualquier filtro léxico presente o futuro:**

1. **La unidad de comparación es la unidad de significado.** Valor completo, no subcadena. Campo,
   no fragmento. Construcción, no palabra.
2. **Se prueba contra el vocabulario legítimo**, enumerado, con un test que barre todo el conjunto
   y exige cero hallazgos. No basta con revisar los casos que se le ocurrieron a alguien.

   > **Una lista de relleno se prueba contra el VOCABULARIO REAL, y su requisito es NO-COLISIÓN
   > DEMOSTRADA, no una regla sobre la forma de las cadenas.**

   Esto se decidió después de descartar una regla sobre la forma. La propuesta era exigir
   comparación **sensible a mayúsculas**, razonando desde `ACCOUNT_UNKNOWN`. Se retiró porque la
   generalización es peor que el ejemplo: **`TODO`, `TBD` y `XXX` son relleno que en la vida real
   se escribe en mayúsculas**, y una comparación sensible los deja pasar a los tres. La
   normalización se queda; lo que hace falta es la prueba de no-colisión, que es esta misma regla
   un piso más arriba aplicada a sí misma.
3. **La normalización se justifica o no se hace.** `.lower()` en `DECORATIVE_FILLER` está bien
   —`TODO`/`TBD`/`XXX` son relleno en mayúsculas— pero está bien *porque se puede argumentar*, y
   el argumento va escrito al lado. Una normalización sin motivo escrito es superficie de colisión
   gratis.
4. **El filtro se aplica donde vive el esquema, no donde viven los datos.** DEF-3 es esta
   obligación incumplida: la regla 5 lee claves de `reasons` —que son datos— como si fueran nombres
   de campo.

## 5.8 La mitad sustractiva: ¿admite el formato que una clave FALTE?

**Sí, y ya lo hace con un gradiente de cuatro escalones que está casi bien.** No hace falta
inventarlo: hace falta escribirlo y corregir los casos mal clasificados.

Medido, quitando cada clave conocida del certificado de ejemplo:

| ausencia | veredicto | escalón |
|---|---|---|
| `ledgerDialect`, `claims.ledgerRange` | **exit 2**, `DIALECT_MISSING` / `RANGE_MISSING` | *no puedo mirar* |
| `limitations` | **exit 1**, `LIMITATIONS_MISSING` | *el documento pierde integridad* |
| `trustLevel` | **exit 1**, `TRUST_LEVEL_INVALID` | *ídem* |
| `certHash` | **exit 1**, `CERTHASH_MISMATCH` | *ídem* |
| `claims.limitRespected`, `failClosedEpisodes`, `changeAttemptsWhileSealed` | **exit 0** + `CLAIM_ABSENT` | *no puedo juzgar esta afirmación* |
| `session.dayKey`, `continuity`, `issuer`, `subject`, `previousCertHash` | **exit 0**, silencio | *no cambia nada* ← **y para `dayKey` es falso: DEF-4** |

> *(Corrección: en una primera corrida anoté `certHash` ausente como exit 0. Estaba mal — mi
> helper de re-sellado lo reponía después de borrarlo. Medido de nuevo sin re-sellar: exit 1,
> `CERTHASH_MISMATCH`, que es lo correcto. Lo dejo escrito porque el instrumento tapó el resultado
> y ésa es la falla que importa, no la fila.)*

### — RULING — cómo se clasifica una clave ausente

> **Una clave conocida que falta se clasifica por lo que su ausencia APAGA, no por lo que deja de
> decir.**
>
> 1. Sin ella el verificador **no puede mirar** ⇒ `cannot_evaluate`, exit 2.
> 2. Sin ella el documento **pierde integridad** —no se puede saber qué documento es, ni qué
>    promete— ⇒ contradicción, exit 1.
> 3. Sin ella **una afirmación no se puede juzgar** ⇒ `cannot_verify`, exit 0, dicho.
> 4. **Sin ella UN CHEQUEO NO CORRE** ⇒ `cannot_verify`, exit 0, **dicho — nunca silencio.**
> 5. Silencio **sólo** si su ausencia no cambia nada de lo que el documento afirma ni de lo que el
>    verificador comprobó.
>
> **El escalón 4 es el que hoy falta**, y es el que hace de la ausencia un arma. Un chequeo que no
> corrió es información; callarlo convierte un documento menos verificado en uno indistinguible de
> uno más verificado.

**Nunca contradicción por ausencia sola.** Una clave ausente no es una afirmación falsa. Acusar a
un documento honesto de incompleto es el error que §5.3 llama catastrófico, y aplica igual acá.

### — COROLARIO RATIFICADO — un campo de ALCANCE ausente nunca es un salto silencioso

> **Para un campo de alcance, la ausencia no puede ser un salto silencioso. O es fallo duro, o el
> verificador declara explícitamente que ese chequeo NO CORRIÓ. Las dos son defendibles; el
> silencio no.**

**Antes de elegir, una corrección a mi propio reporte.** Dije que al sacar `dayKey` «nadie se
entera». Medido con el informe completo delante, es más preciso y más feo que eso: **no es
silencio, es un DOWNGRADE, y el mensaje que queda atribuye mal la causa.**

| el certificado truncado | qué dice el verificador |
|---|---|
| con `dayKey` | **contradicción** `RANGE_TRUNCATED`, exit 1 — nombra los 3 eventos materiales escondidos |
| sin `dayKey` | **`cannot_verify`** `POST_RANGE_MATERIAL_EVENTS`, exit 0 — nombra los mismos 3 eventos |

Así que algo sí se dice. Lo que **no** se dice es que el chequeo de cobertura no corrió. Y el
mensaje de reemplazo lo explica con la causa equivocada: dice *«with no DAY_CLOSED for this
session»* cuando **sí hay un `DAY_CLOSED`** — lo que falta es que le digan a qué sesión pertenece.
Es DEF-2 otra vez, un piso más abajo: **un mensaje que afirma más de lo que su código comprobó.**

**La salida que propongo no es ninguna de las dos puras, sino el principio que el propio código ya
declara** en `:642-644` — *«Severity follows the harm, not the shape»*:

1. **Decir que el chequeo no corrió.** `cannot_verify` con código propio (`SCOPE_MISSING`) y el
   motivo correcto: «el certificado no nombra un día, así que la cobertura de la sesión no se
   verificó» — no «no hay DAY_CLOSED».
2. **Y que la severidad no dependa de si `dayKey` está.** Si hay eventos materiales fuera del rango
   declarado, el daño es idéntico con `dayKey` y sin él, así que **es contradicción en los dos
   casos.** Eso cierra el downgrade: el truncado sin `dayKey` vuelve a exit 1, por la razón que
   corresponde.

Por qué no el fallo duro puro: acusaría a un certificado honesto que simplemente no nombra un día,
sin que nada material esté escondido — el error que §5.3 llama catastrófico. Por qué no el
«declarar» puro: deja el truncado en exit 0, y un consumidor automático que sólo lee el código de
salida ve «bien». **La severidad atada al daño da las dos cosas bien**, y no inventa un criterio
nuevo: es el que ya está escrito ocho líneas más arriba en el mismo archivo.

### Por qué el downgrade es PEOR que el silencio, y por qué esto es una superficie de ataque

La corrección empeora el defecto en vez de suavizarlo, y conviene decirlo entero:

> **Un silencio no afirma nada. Un downgrade produce un documento que dice «no pude verificar»
> donde la verdad era «verifiqué y está mal».** Un lector archiva un `cannot_verify` como
> inconcluso — y era concluyente y feo.

Y de ahí sale la forma general, que convierte un olor de diseño en algo con nombre:

> **UNA SEVERIDAD QUE DEPENDE DE LA PRESENCIA DE UN CAMPO, EN VEZ DE DEPENDER DEL DAÑO, SE PUEDE
> COMPRAR OMITIENDO DATOS.**

Sacás `dayKey` y tu contradicción se convierte en un inconcluso. **Nadie tiene que falsificar
nada: alcanza con no escribir una clave.** Es más barato que cualquier ataque del modelo de
amenaza del §2b de la SPEC, no deja rastro en la cadena, y hoy funciona sobre el ejemplo que el
propio repositorio publica como «la mentira más peligrosa que el formato permite».

Por eso el arreglo no es cosmético ni de mensajería: **mientras la severidad dependa de qué campos
están presentes, omitir es una palanca.**

### La frontera que esto le agrega al ruling de §5.6

§5.6 dijo «desconocido se omite, nunca se defaultea». Sigue en pie y queda **acotado**:

> **Se omite un campo que lleva un VALOR. Nunca uno que lleva un ALCANCE.**

`session.timezone` lleva un valor: omitirlo pierde un dato. `session.dayKey` lleva el alcance
contra el cual se juzga el rango: omitirlo apaga el juicio. Son vecinos en el mismo objeto y la
misma receta de arreglo produce lo correcto en uno y un desastre en el otro.

**Antes de omitir una clave hay que preguntar: ¿alguien la usa como puerta?** Si la respuesta es
sí, se declara `null` explícito —que preserva «no lo sé» sin desarmar nada— o se deja de tratar
como opcional.

### La puerta sustractiva de §5.5

La contención de §5.5 está escrita toda del lado aditivo: «ninguna entrada puede anular a otra».
Tiene una gemela que hay que cerrar con ella:

> **Tampoco se omite una clave para que un chequeo no corra.** Agregar un evento que dice «esto no
> cuenta» y quitar una clave para que nadie cuente son el mismo daño por puertas opuestas — y la
> segunda es más barata, no deja rastro, y hoy **funciona** (DEF-4).

La prueba para el que aplique la regla, en su forma completa: *¿este cambio —agregar o quitar—
hace que algo se verifique MENOS y el documento no lo diga? Entonces no va.*

---

# PARTE IV — LO QUE FALTA DEBAJO DE TODO

## 6. El verificador de la evidencia cita una especificación que nunca se versionó

`deadman/verify_certificate.py` cita `SPEC §A.1`, `§A.2`, `§A.3`, `§A.4`, `CERT_SPEC v0.2` y
`CERT_STEP1.md`. **Ninguno existe en este repositorio**, verificado:

- `docs/SPEC.md` no tiene apéndice A — 0 coincidencias de `A.1`; las secciones llegan a la 7 más
  «Decisiones tomadas».
- `CERT_SPEC.md` y `CERT_STEP1.md` no están ni estuvieron nunca versionados aquí
  (`git log --all --diff-filter=A`).

Es la misma forma que «una familia cerrada sin documento no está cerrada»: **el documento donde va
a vivir la regla de extensión no existe todavía, y eso es parte de por qué la tolerancia salió
accidental.** Nadie escribió la decisión porque no había dónde.

Va como ítem propio, y hay que decidir dónde vive la regla de §5: en `docs/SPEC.md` de este repo, o
en el `CERT_SPEC` que hay que crear. Si es lo segundo, este repo tiene que apuntar a dónde vive,
porque hoy cita cuatro secciones de un documento que no tiene.

## 7. Estado de los pedidos del emisor

| pedido | ¿rompe algo? | estado |
|---|---|---|
| **2 — `buildHash` en `GUARDIAN_STARTED`** | no | **adelante**, dentro de `payload`. Se **omite** si no se puede determinar — nunca `"example"`, que es el caso que parió la regla 5. **Verificar antes que no se pierda `fresh`**: el ejemplo empaquetado lleva `{"fresh": true, "state": "DISARMED"}`, y `fresh` está entre las cuatro cosas que `request-to-guardian-emitter.md` §5 dice que no deben cambiar. No pude verificarlo contra el emisor real |
| **3 — `dayKey` en `CONFIG_LOADED`** | no | **CONDICIONADO** a que cert-1 lo consuma — en espera, no retirado. Hoy nadie lo leería: `dayKey` sólo se mira en `DAY_OPENED`/`DAY_CLOSED` (`:621-622`), y uno que nombre otro día pasa sin comentario (medido). Un campo sin lector no se escribe (§5.2.3) |
| **1 — evento de acuse** | **sí, hoy** | **bloqueado por DEF-2**. No se puede emitir hasta cerrar el cajón de sastre y la atribución posicional, o el primer acuse durante un fail-closed se publica como su causa |

## 8. — RULING — Orden de trabajo

0. **`session.timezone: ""`, del lado del emisor** — es la única falla **funcional** de la lista y
   ya se dispara sola por la ruta LT-2. No depende de nosotros y no hay que esperar a nada: campo
   ausente o `null`. Va en cero porque cada certificado emitido tras un reinicio normal está
   fallando mientras esto no salga.
1. **DEF-3, las dos mitades** — la inversión **y** la procedencia. Sube de sexto a primero: es lo
   único que hoy hace **rechazar certificados honestos**, ya está probado y pasa 100/100. Los otros
   tres defectos dejan pasar algo malo; éste rechaza algo bueno, que es lo que enseña a apagar el
   verificador.
2. **DEF-2** — renombrar a `precedingEvent`/`precedingSeq`, **empezar a compararlo**, y la
   limitación de causas (emisor primero, verificador después: §DEF-2 ruling parte 3). La
   comparación es además lo que reemplaza al chequeo de forma que la procedencia acaba de quitar.
3. **DEF-4** — `session.dayKey` ausente pasa a `cannot_verify`, y la severidad sigue al daño, con
   `certificate-truncated.json` sin `dayKey` como control. **Por calendario**: el emisor está por
   limpiar los seis `?? ""` y la regla tiene que existir antes que la limpieza.
4. **DEF-1**, opción A — lista negra `{hash, sig}` en `_kit_body` y `_entry_hash`, con el test de
   inyección top-level como control.
5. La exclusión `HUMAN_*` en `recompute_claims`, con D2 como control.
6. El marcado `UNKNOWN_EVENT_KIND` como `cannot_verify`.
7. Escribir §5 donde se decida en §6.
8. Recién entonces, el evento de acuse.

### — RULING — el criterio de orden

> **EL ORDEN VA POR CUÁNTA GENTE TIENE QUE HACER ALGO MAL PARA QUE EL DEFECTO DUELA.**

| cuántos | qué significa | quién cae acá |
|---|---|---|
| **cero** | se dispara solo, en operación normal | `session.timezone: ""` (ruta LT-2) |
| **uno** | el productor se equivoca y el documento sale falso | DEF-2, DEF-4 |
| **dos** | alguien tiene que ir a usar el agujero | DEF-1 |

**Y DEF-3 se adelanta a todo por un motivo distinto y más caro: es el único que RECHAZA
CERTIFICADOS HONESTOS.**

Un defecto que castiga el uso correcto no sólo falla — **entrena a la gente a esquivar la
protección.** Es la regla de §5.7 del otro lado del espejo: un freno cuyo arreglo habitual es
«desactivalo» ya dejó de ser un freno, y **un verificador que rechaza documentos honestos se gana
ese arreglo solo.** No hace falta que nadie decida ignorarlo; basta con que falle sobre trabajo
legítimo las veces suficientes.

Por eso el eje no es «gravedad» sino **cuánta acción humana equivocada hace falta**, con esa
excepción arriba de todo: los defectos que dañan sin que nadie se equivoque, y el que daña
justamente a quien no se equivocó.

> **Un documento que ya está equivocado es peor que un agujero que nadie abrió.**

**Y en paralelo, ya: el aviso al lado del guardián** — `docs/request-to-guardian-causes-and-unknown.md`,
antes de que implementen el ítem 4b.

---

## Apéndice — cómo se produjo

Los ejemplos (`certificate.json`, `ledger.jsonl`) se **copiaron** al scratchpad de la sesión y se
trabajaron ahí; no se escribió nada dentro de `deadman/` salvo este documento. Cada caso se
construyó mutando el ejemplo, re-encadenando honestamente con las reglas reales de hash, y
corriendo `verify_certificate` / `Ledger.verify` sobre el resultado. Todos los pares tienen control.

### La práctica que lo atrapa, adoptada para toda sonda futura

> **Toda medición incluye un caso que DEBE dar distinto. Si el control y el caso dan lo mismo, el
> instrumento está contestando.**

No es una nota de esta tanda: es la defensa que funcionó las **tres** veces que mi aparato tapó el
resultado, no es sofisticada, y se aplica a cualquier sonda en cualquiera de los tres
repositorios. Cada tabla de este documento la cumple — por eso están todas escritas en pares.

**El aparato no es sólo el código de la sonda: es también la capa de presentación.** La tercera vez
fue la consola de Git Bash renderizando `—` (U+2014) como `?` en cp1252. Lo leí como archivo
corrupto, dije que un heredoc lo había roto, y era falso: el archivo estaba perfecto. Se descubrió
porque «arreglé» el archivo y la pantalla **siguió** mostrando lo mismo. Si el arreglo hubiera
cambiado el render por casualidad, la conclusión falsa habría quedado escrita. **Cuando lo que está
en duda es cómo se VE algo, se verifica por valor — ordinal, bytes, aserción — nunca por pantalla.**

### La clase que apareció dos veces: mi herramienta contestó por el sujeto

Las dos veces que me equivoqué en esta tanda fueron **la misma falla**, y merece nombre propio
porque no es la del doble de prueba:

> **En el doble de prueba, el MODELO DEL MUNDO simplifica. Acá el APARATO DE MEDICIÓN produce la
> respuesta en lugar del sistema.** «Mi herramienta contestó por el sujeto.»

- El `print` de la sonda de anclas llevaba la conclusión escrita **antes** de correr: informaba
  `ANCHOR_MISMATCH` porque yo lo había tipeado, no porque el ancla hubiera cambiado.
- El helper `reseal()` reponía `certHash` **después** de que yo lo borrara, así que la fila
  «`certHash` ausente» medía un certificado con `certHash`.

**Lo que las hace peligrosas es que las dos se veían como un resultado cómodo, no como un error.**
Una confirmaba lo que yo esperaba; la otra daba exit 0 en una fila donde exit 0 era plausible.
Ninguna se presenta como fallo: se presentan como respuesta.

La defensa que funcionó las dos veces fue la misma y no es sofisticada: **un control que tiene que
fallar.** Cuando el par control/caso da lo mismo, el instrumento está contestando. Y por eso las
dos quedan escritas acá en vez de corregidas en silencio — el modo de falla vale más que las dos
filas que arregló.

### Chequeos sobre mí misma

Cuatro cosas que fueron chequeos sobre mí misma más que sobre el código:

- **La sonda de las anclas traía la conclusión pre-escrita en su `print`** y la medición la
  desmintió: la opción A no rompe hashes. Está al frente de §DEF-1 en vez de corregida en silencio,
  porque el modo de falla —un resultado correcto saliendo de un instrumento que ya sabía qué
  contestar— importa más que el número.
- Primero anoté que un acuse fuera del rango pasa «en silencio» y un `LIMIT_BREACHED` no. Los dos
  dan **exit 0**; la diferencia está en `unverified`. Lo había leído mal porque en la primera
  corrida sólo imprimí contradicciones.
- El agujero del campo top-level lo probé **dos veces** por caminos distintos (`Ledger.verify` y
  `verify_certificate`) porque el resultado me pareció demasiado cómodo para el argumento que
  estaba armando.
- La afirmación «`GUARDIAN_STARTED` sólo lleva `state`» venía en el enunciado y **no la verifiqué
  contra el emisor real**, porque ese repo no es mío. Contra el ejemplo publicado es falsa. Queda
  como discrepancia a resolver, no resuelta.
