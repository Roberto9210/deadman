# Cómo se extiende el ledger — dos defectos vivos, y la regla que va encima

**De:** la sesión de `deadman` (la librería)
**Asunto:** dos defectos en la verificación de evidencia, y la regla de extensión del ledger
**Estado:** los defectos son hallazgos medidos, no propuestas. **Todo lo marcado RULING está
DECIDIDO por el operador el 2026-08-31** — la salida de DEF-1, la de DEF-2, la regla de extensión
(§5) y el orden de trabajo (§8). Nada está implementado todavía, en ningún lado.

Sale de tres pedidos del lado del guardián — un evento nuevo (acuse de recibo), el `buildHash` en
`GUARDIAN_STARTED`, y el `dayKey` en `CONFIG_LOADED`. Buscando si el formato los admitía
aparecieron dos defectos que no dependen de esos pedidos y que hay que arreglar antes.

Todo se midió contra el código real y el ejemplo empaquetado (`deadman/examples/certificate/`),
cada caso con su control, para que un resultado que pasa se sepa capaz de fallar. Donde no
verifiqué, lo digo.

**Lo que no pude verificar:** el repositorio `deadman-guardian` no es mío y no lo leí. Todo lo que
digo del emisor sale del ejemplo empaquetado en *este* repo y de
`docs/request-to-guardian-emitter.md`.

---

# PARTE I — LOS DOS DEFECTOS

Ambos van **antes** de la regla de extensión. Tienen prioridad por ejes distintos y conviene no
fingir un único orden:

| | eje | ¿necesita un atacante? | ¿bloquea la regla? |
|---|---|---|---|
| **DEF-2** atribución de causa por adyacencia | emite afirmaciones falsas **hoy**, en operación normal | **no** | no, pero bloquea el pedido 1 |
| **DEF-1** el campo top-level que nadie firma | rompe la propiedad que da valor al producto entero | sí (acceso a disco) | **sí** |

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

## 7. Estado de los tres pedidos

| pedido | ¿rompe algo? | estado |
|---|---|---|
| **2 — `buildHash` en `GUARDIAN_STARTED`** | no | **adelante**, dentro de `payload`. Se **omite** si no se puede determinar — nunca `"example"`, que es el caso que parió la regla 5. **Verificar antes que no se pierda `fresh`**: el ejemplo empaquetado lleva `{"fresh": true, "state": "DISARMED"}`, y `fresh` está entre las cuatro cosas que `request-to-guardian-emitter.md` §5 dice que no deben cambiar. No pude verificarlo contra el emisor real |
| **3 — `dayKey` en `CONFIG_LOADED`** | no | **CONDICIONADO** a que cert-1 lo consuma — en espera, no retirado. Hoy nadie lo leería: `dayKey` sólo se mira en `DAY_OPENED`/`DAY_CLOSED` (`:621-622`), y uno que nombre otro día pasa sin comentario (medido). Un campo sin lector no se escribe (§5.2.3) |
| **1 — evento de acuse** | **sí, hoy** | **bloqueado por DEF-2**. No se puede emitir hasta cerrar el cajón de sastre y la atribución posicional, o el primer acuse durante un fail-closed se publica como su causa |

## 8. — RULING — Orden de trabajo

1. **DEF-2** — renombrar a `precedingEvent`/`precedingSeq`, **empezar a compararlo**, y la
   limitación de causas (emisor primero, verificador después: §DEF-2 ruling parte 3).
2. **DEF-1**, opción A — lista negra `{hash, sig}` en `_kit_body` y `_entry_hash`, con el test de
   inyección top-level como control.
3. La exclusión `HUMAN_*` en `recompute_claims`, con D2 como control.
4. El marcado `UNKNOWN_EVENT_KIND` como `cannot_verify`.
5. Escribir §5 donde se decida en §6.
6. Recién entonces, el evento de acuse.

**DEF-2 va primero porque NO NECESITA ADVERSARIO:** emite falsedades hoy, en operación normal, sin
que nadie haga nada. DEF-1 es un agujero que alguien tendría que usar.

> **Un documento que ya está equivocado es peor que un agujero que nadie abrió.**

**Y en paralelo, ya: el aviso al lado del guardián** — `docs/request-to-guardian-causes-and-unknown.md`,
antes de que implementen el ítem 4b.

---

## Apéndice — cómo se produjo

Los ejemplos (`certificate.json`, `ledger.jsonl`) se **copiaron** al scratchpad de la sesión y se
trabajaron ahí; no se escribió nada dentro de `deadman/` salvo este documento. Cada caso se
construyó mutando el ejemplo, re-encadenando honestamente con las reglas reales de hash, y
corriendo `verify_certificate` / `Ledger.verify` sobre el resultado. Todos los pares tienen control.

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
