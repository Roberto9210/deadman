# Cómo se extiende el ledger — siete defectos vivos, y la regla que va encima

> **POR QUÉ HAY QUE ESCRIBIR LA ESPECIFICACIÓN** (§6) — el argumento entero, en una frase:
>
> ### Un documento faltante no produce un hueco visible. Produce dos decisiones locales coherentes, incompatibles entre sí, y ninguna reconocible como el error.
>
> ### Sin especificación, los dos lados adivinaron. Adivinaron igual. Y su acuerdo parece confirmación.
>
> Por eso una especificación ausente **no se detecta revisando código**: no hay nada mal escrito de
> ningún lado. Los dos tratamientos opuestos de `keyId` eran razonables, y ninguno de los dos lados
> se equivocó. **El error no vive en ninguna de las dos decisiones — vive entre ellas, y sólo se ve
> cuando alguien las mira juntas.** Ésta es la primera línea del documento de la spec cuando se
> escriba.

---

> **La pregunta tiene dos mitades y este documento contesta las dos.** La aditiva —¿admite el
> formato un campo o un evento que no conoce?— es §5.1-§5.6. La **sustractiva** —¿admite que una
> clave que sí conoce FALTE?— es §5.8, y la respuesta es distinta, porque **un campo desconocido es
> inerte y una clave ausente puede APAGAR UN CHEQUEO.**

**De:** la sesión de `deadman` (la librería)
**Asunto:** siete defectos en la verificación de evidencia, y la regla de extensión del ledger
(mitad aditiva y mitad sustractiva)
**Estado:** los defectos son hallazgos medidos, no propuestas. **Todo lo marcado RULING está
DECIDIDO por el operador** — la salida de DEF-1, la de DEF-2, §5.3, §5.4, §5.6, §5.7 y el orden de
trabajo (§8), el 2026-08-31; §5.8, la mitad sustractiva, con su corolario, el 2026-09-01. Nada
está implementado, en ningún lado.

Sale de cuatro pedidos del lado del guardián. Tres son ADITIVOS — un evento nuevo (acuse de
recibo), el `buildHash` en `GUARDIAN_STARTED`, el `dayKey` en `CONFIG_LOADED` — y el cuarto va en
dirección contraria: **seis sitios con `?? ""` cuyo arreglo correcto es OMITIR la clave.**
Buscando si el formato los admitía aparecieron cinco defectos que no dependen de esos pedidos y
que hay que arreglar antes.

Todo se midió contra el código real y el ejemplo empaquetado (`deadman/examples/certificate/`),
cada caso con su control, para que un resultado que pasa se sepa capaz de fallar. Donde no
verifiqué, lo digo.

**Lo que no pude verificar:** el repositorio `deadman-guardian` no es mío y no lo leí. Todo lo que
digo del emisor sale del ejemplo empaquetado en *este* repo y de
`docs/request-to-guardian-emitter.md`.

---

# PARTE I — LOS SIETE DEFECTOS

Los cuatro van **antes** de la regla de extensión. Tienen prioridad por ejes distintos y conviene
no fingir un único orden:

| | eje | ¿necesita un atacante? | ¿bloquea la regla? |
|---|---|---|---|
| **DEF-2** atribución de causa por adyacencia | emite afirmaciones falsas **hoy**, en operación normal | **no** | no, pero bloquea el pedido 1 |
| **DEF-1** el campo top-level que nadie firma | rompe la propiedad que da valor al producto entero | sí (acceso a disco) | **sí** |
| **DEF-4** omitir `session.dayKey` apaga el chequeo de truncamiento | **desactiva en silencio** la protección contra la mentira más peligrosa del formato | no — basta con **omitir** | no, pero decide §5.8 |
| **DEF-3** la regla 5 lee claves de datos como nombres de campo | acusa en falso a contenido honesto | no — basta con **nombrar** un evento | no |
| **DEF-5** la línea `VALID` nombra una clave que no verificó | publica como comprobado algo que nadie miró | no | no, pero **exige** §6 |
| **DEF-6** un corte de luz vuelve acusatorio a un certificado honesto | afirma que el trader se pasó del límite | **no — lo hace la red eléctrica** | no |
| **DEF-7** `limitRespected` dice «incumplió» cuando el guardián no pudo ver | acusa sobre una jornada impecable | **no — es el arranque por defecto de NT8** | sí, y el defecto es de los dos lados |

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

### LEÍDO EN LA FUENTE (2026-09-01): el emisor infiere la causa por adyacencia TAMBIÉN

Leído directamente en `deadman-guardian`, commit **`66dee69`** (sólo lectura, nada escrito ahí):

```csharp
// src/GuardianCore/Certificate.cs:238
current.TriggerEvent = prevEv;
```

**El emisor deriva la causa igual que nosotros: tomando el evento anterior.** Después la emite
(`:464`, sólo si no es nula) y la vuelve a leer (`:685`).

Eso cambia la gravedad de DEF-2, y no en la dirección cómoda:

> **No es «el verificador infiere causalidad». Son DOS implementaciones independientes de la misma
> regla equivocada, que por eso siempre COINCIDEN — y su coincidencia se lee como corroboración.**

Un emisor y un verificador que derivan el mismo campo con la misma regla errónea nunca se
contradicen. La comparación que pide el ruling de DEF-2 parte 2 **pasaría siempre**, y pasaría por
el motivo equivocado: no comprobaría que la causa es cierta, sólo que los dos cometen el mismo
error. **Es verificación cómplice en su forma más pura: dos partes que se confirman porque
comparten la premisa, no porque la premisa sea verdadera.**

**Consecuencia para el orden de trabajo:** comparar `precedingEvent` sigue siendo necesario —evita
que el campo sea texto libre— pero **NO es suficiente y no hay que venderlo como si lo fuera.** Lo
que hace verdadero al documento es el renombre y la limitación de causas, no la comparación.

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

> **CORRECCIÓN DEL RULING (2026-09-01), después de leer la fuente primaria.** Este ruling decía
> «renombrar Y comparar» y presentaba la comparación como lo que vuelve verdadero el documento.
> **Era insuficiente.** `Certificate.cs:238` del guardián hace `current.TriggerEvent = prevEv`: el
> emisor deriva la causa por adyacencia **con la misma regla que el verificador**.
>
> **La comparación PASARÍA HOY, sobre todos los certificados, y eso no significa nada.** No
> comprobaría que la causa es cierta: comprobaría que los dos lados cometen el mismo error. Un
> emisor y un verificador que computan el mismo campo con la misma regla equivocada **nunca se
> contradicen**.
>
> **La comparación se queda — es necesaria**, porque impide que el campo sea texto libre y cierra
> la mitad «cualquiera puede escribir cualquier cosa». **Pero NO es lo que hace verdadero al
> documento y no se vende como si lo fuera.** Lo que lo hace verdadero es el **renombre a
> `precedingEvent`** —que deja de afirmar causalidad— y la **limitación que declara que el
> certificado no establece causas** (parte 3).
>
> **Anotado explícitamente para quien implemente:** cuando el test de comparación pase, eso **no**
> es evidencia de nada hasta que las dos derivaciones sean independientes. Ver §5.11.

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

## DEF-7 — `limitRespected` dice «incumplió» cuando lo que pasó es que el guardián no pudo ver

Llegó como consulta del emisor: pasar `limitRespected` de booleano a tres valores
(*respected* / *breached* / *undetermined*). Medido con el método de §5.12, y la respuesta tiene
dos partes que conviene no mezclar.

### Sí cae bajo el contrato — y no por precaución

| pregunta | medido |
|---|---|
| ¿el verificador lo **lee**, o sólo lo transcribe? | **Lo lee.** Lo compara contra su propio recomputo (`:1182`): puesto en `False` cuando el ledger dice `True` ⇒ `CLAIM_MISMATCH`, exit 1 |
| ¿alguna afirmación recomputada **depende** de él? | **No.** `recompute_claims` recibe sólo `(entries, dialect, lo, hi, chain_ok)`; el certificado no entra al cálculo |
| ¿un valor que no sea `true`/`false` falla? | **Falla.** `'undetermined'`, `'respected'` y `'breached'` dan `CLAIM_MISMATCH`, exit 1 |

**Un emisor que pase a tres estados solo sería llamado mentiroso en todos sus certificados.** Así
que sí es del contrato, por el criterio de §5.12: es un campo que leo y comparo.

*(Dos rarezas menores del comparador, de paso: `None` sale por `CLAIM_ABSENT` y da exit 0, que es
correcto por §5.8; y el entero `1` **pasa como `True`**, porque en Python `1 == True`. Es una
tolerancia accidental, no una decisión.)*

### Pero «cae bajo el contrato» acá no significa «bloqueado». El defecto es MÍO también

Medido sobre un episodio al que le falta su `FAIL_CLOSED_CLEARED` — el guardián no pudo ver, y
**cero** `LIMIT_BREACHED`:

```
open = True    lockoutsTriggered = 0    limitRespected = False
```

`limit_respected = (lockouts == 0 and not any(e["open"]) and chain_ok)`. **Mi recomputo colapsa
«no pude ver» con «se pasó del límite» exactamente igual que el emisor.** El emisor no está
pidiendo que yo acomode un cambio suyo: encontró un defecto que existe idéntico de este lado, y el
lado que tiene que definir el recomputo soy yo.

### Y es la TERCERA vez que este verificador publica una ausencia como cargo

No es un caso más. Es una clase, tres de tres en el artefacto cuyo propósito entero es que un
tercero lo lea y actúe:

| | la ausencia | lo que publicaba |
|---|---|---|
| **§6bis** | el archivo entregado no es el que el certificado declara | `CONTRADICTED` |
| **DEF-6** | el ledger llegó cortado | `CONTRADICTED` + «se pasó del límite» |
| **DEF-7** | el guardián no pudo ver la cuenta | `limitRespected: false` |

> **UNA AUSENCIA DE EVIDENCIA PUBLICADA COMO EVIDENCIA ADVERSA.** Las tres veces la herramienta
> tenía la información para saber que no sabía, y las tres veces eligió el valor que acusa. No es
> un descuido repetido: es lo que pasa cuando el tipo del campo no tiene lugar para «no sé», y
> entonces el «no sé» se guarda en el casillero del «no».

**El tipo del campo es la causa.** Un booleano no tiene dónde poner un tercer estado, así que el
tercer estado se disfraza del peor de los dos. Eso da la regla general, que es lo que hay que
recordar del caso:

> **Un campo cuyo tipo no puede expresar «no sé» va a expresarlo como «no», y «no» es la respuesta
> que acusa.** Antes de elegir un booleano para un hecho observado, preguntar qué pasa cuando el
> observador no pudo mirar.

### Urgencia: la condición es el ARRANQUE POR DEFECTO, no un borde

Dato del otro lado, **reportado y no medido por mí**: los episodios fail-closed pararon en esa
máquina porque se activó *connect-on-startup* el 22-ago, y NT8 **no se conecta al arrancar por
defecto**. Si es así, **toda instalación nueva arranca en la condición que dispara esto**, y el
primer usuario que no sea el operador lo ve el primer día, sobre una jornada impecable. Medido de
este lado: hubo un episodio de 1 h 01 m y tres de más de 30 min, así que el estado es alcanzable y
duradero.

Por el criterio del operador para DEF-6 —la herramienta **acusando a un inocente** pesa distinto
que la herramienta **afirmando de más**— esto es de la misma clase, y encima con alcance de
*todos los usuarios nuevos* en vez de *este equipo*.

### El diseño, para que el emisor pueda moverse

Los tres estados, derivados de lo que ya se recomputa:

| estado | condición |
|---|---|
| **breached** | hay al menos un `LIMIT_BREACHED` |
| **undetermined** | sin `LIMIT_BREACHED`, pero **un episodio quedó abierto** — o la cadena no verifica, o el ledger llegó truncado |
| **respected** | sin `LIMIT_BREACHED`, ningún episodio abierto, y la evidencia está completa |

**Migración, igual que `precedingEvent`:** el verificador acepta las dos formas mientras el emisor
migra — `true` contra `respected` y `false` contra `breached` **sólo cuando el recomputo también
dice `breached`**. Un `false` viejo contra un recomputo `undetermined` **no es contradicción**: es
el defecto de origen, y el certificado viejo no mintió, dijo lo único que su tipo le permitía.

**Pendiente de decisión del operador**: si esto entra antes que 6b. No lo asumo — es la clase que
él mismo priorizó por encima del resto, pero la cola es suya.

---

## DEF-6 — Un corte de luz hace que un certificado honesto diga que el trader se pasó del límite

**Segundo corte de energía en 48 horas.** Deja de ser accidente y pasa a ser **condición de
operación de esta máquina** (operador, 1-sep). Así que la conducta ante un ledger **truncado** —no
adulterado, cortado— deja de ser hipotética: es un caso que esta casa produce sola, dos veces por
semana. Medido el día que volvió a pasar.

### Lo medido

| el ledger | veredicto |
|---|---|
| **CONTROL** entero | exit **0**, `VERIFIED at L1` |
| truncado **a mitad de línea** | exit **2** — correcto, `_read_ledger_lines` levanta y el CLI lo trata como «no pude mirar» |
| truncado **en un límite de línea**, falta 1 fila | exit **1**, `RANGE_INCOMPLETE` |
| truncado en un límite, faltan 3 filas | exit **1**, `RANGE_INCOMPLETE` **+ `CLAIM_MISMATCH`: `limitRespected` certificado `True`, «los eventos dicen `False`» + el episodio pasa a `open`** |
| **CONTROL** adulterado (JSON válido, hash mal) | exit **1**, `CHAIN_BROKEN` + `CLAIM_MISMATCH` |

### Por qué el caso malo es el PROBABLE, no el raro

El corte a mitad de línea da exit 2 y está bien. **Pero es el caso improbable**: el ledger hace
`flush()` + `fsync()` después de **cada línea completa** (`deadman/ledger.py:267-268`), así que un
corte deja casi siempre un archivo **cortado en un límite de línea** — el caso que da exit 1.

**La protección funciona en el escenario que casi no ocurre y falla en el que ocurre.**

### Y lo que publica no es sólo «incompleto»

Con tres filas perdidas, el verificador afirma que **`limitRespected` es falso** y que un episodio
de fail-closed **quedó abierto**. El mecanismo es directo: perder el `FAIL_CLOSED_CLEARED` deja el
episodio abierto, y `limit_respected` exige que ninguno lo esté.

> **Un corte de luz no vuelve al certificado inevaluable: lo vuelve ACUSATORIO.** Fabrica
> exactamente la afirmación más dañina que el documento puede hacer sobre su portador — que se pasó
> del límite — sin que nadie toque nada.

Es la misma forma que §6bis (difamar con el archivo equivocado), con una diferencia que la empeora:
allí hacía falta que alguien entregara el archivo equivocado; acá **lo produce la red eléctrica.**

### El discriminador existe y el verificador ya tiene todo para usarlo

**Un truncamiento no puede romper la cadena.** La cadena se construye hacia adelante, así que
quitar un **sufijo** deja un **prefijo válido que verifica entero hasta génesis**. Confirmado en la
medición: en el caso truncado **no aparece `CHAIN_BROKEN`** — sólo `RANGE_INCOMPLETE`. En el
adulterado sí aparece, en la fila exacta.

> **Un prefijo cuya cadena verifica entera, con el rango declarado excediéndolo por el FINAL, es la
> firma de un TRUNCAMIENTO, no de una adulteración. La cadena no se puede truncar por adelante.**

O sea: la información para distinguir «este archivo está corto» de «este certificado mintió» **ya
está en la mesa**, y la severidad no la usa.

### PRIMERA MITAD APLICADA (2026-09-01) — y por qué se adelantó

**Se adelantó a 6b, y no por el criterio de §8.** Todos los demás defectos de este verificador
son la herramienta **afirmando de más**; éste es la herramienta **acusando a un inocente**
(operador, 1-sep). Una herramienta que promete de más decepciona; una que fabrica una acusación
contra su portador lo **daña** — y el certificado existe justamente para mostrárselo a un
tercero que va a actuar sobre él. Hay 12 certificados emitidos y una página pública que invita
a verificar con esta herramienta.

**Partido en dos, porque el daño no está en el cómputo sino en lo que se publica como
veredicto.** Aplicada la primera mitad: cuando la firma del truncamiento está presente
—cadena verifica hasta génesis **y** las faltantes forman un sufijo— el veredicto pasa a
**exit 2 `LEDGER_TRUNCATED`**, y cualquier desacuerdo de claims sale como
`CLAIM_MISMATCH_OVER_TRUNCATED_RANGE` en el bloque de *no verificado*, nunca como cargo.
**No cambia cuándo se recomputa nada**: cambia cómo se presenta y con qué código sale.

Medido, con el control que tenía que sobrevivir:

| caso | antes | después |
|---|---|---|
| entero | exit 0 | exit 0 |
| cortado limpio, 1 fila | **exit 1** `RANGE_INCOMPLETE` | **exit 2** `LEDGER_TRUNCATED` |
| cortado limpio, 3 filas | **exit 1** + «`limitRespected` los eventos dicen False» | **exit 2**, sin cargo |
| **CONTROL adulterado** | exit 1 `CHAIN_BROKEN` | **exit 1 `CHAIN_BROKEN`** — intacto |
| **CONTROL cortado Y adulterado** | — | **exit 1 `CHAIN_BROKEN`** — la manipulación gana |
| **CONTROL hueco en el MEDIO** | — | **exit 1 `CHAIN_BROKEN`** — no es truncamiento |

Cinco tests nuevos. Contra el código viejo fallan **exactamente los dos que afirman el
arreglo**, y los **tres controles de conducta preservada pasan en las dos versiones** — que es
la forma que prueba que el cambio tocó lo que quería y nada más.

### Segunda mitad, pendiente, y puede ir detrás de 6b

**No recomputar afirmaciones sobre un rango que no se tiene.** Hoy `recompute_claims`
   corre igual sobre las filas presentes y publica el resultado como si fuera el del rango
   declarado. Eso es computar sobre evidencia ausente, que es justo lo que §5.8 escalón 4 manda
   declarar en vez de calcular. Sin esto, arreglar sólo el código de salida deja el `CLAIM_MISMATCH`
   acusatorio en el cuerpo del informe.

**No lo aplico en esta tanda** porque el punto 2 cambia cuándo se recomputan las afirmaciones, que
es más que un código mal ruteado, y la cola tiene 6b adelante. Entra como **DEF-6**, y por el
criterio de §8 —cuántos tienen que hacer algo mal— es **tier cero**: nadie se equivoca, se corta la
luz.

**Nota para §6**: la conducta ante un archivo truncado es un caso que la especificación tiene que
cubrir explícitamente, y ahora tiene evidencia de frecuencia en vez de ser un supuesto.

---

## DEF-5 — La línea VALID nombra una clave que no verificó

### La pregunta que llegó, y la respuesta es medible

Del lado del guardián, `CertificateRequest.KeyId` tiene **una fuente y dos consumidores tratados al
revés, a 17 líneas**: `issuer.keyId` se omite si viene vacío, `signature.keyId` lo vacía. Ventana A
fue a buscar el papel de cada uno y **ningún documento de ese repo los define**; los comentarios
citan un `CERT_SPEC` que vive de este lado — y que acá tampoco existe (§6).

*(Procedencia, §5.9: lo del lado del guardián es **reportado por Ventana A, no medido por
nosotros**. Todo lo que sigue sobre el verificador **sí** es medición propia, con controles.)*

La pregunta *«¿el verificador lo consume?»* se contesta sin que nadie decida nada:

| medición | resultado |
|---|---|
| `signature.keyId` **borrado entero** | exit 0, `VALID (keyId=key-ALPHA)` — **sin cambio** |
| `signature.keyId` reemplazado por una fabricación | exit 0, **sin cambio** |
| **CONTROL** ambos presentes, clave correcta | exit 0, `VALID (keyId=key-ALPHA)` |

**`signature.keyId` no se lee nunca.** Aparece 0 veces en el código del verificador.

`issuer.keyId` **sí** se lee — en un solo lugar, `:1091`, y **sólo para interpolarlo en la cadena
de estado**, únicamente en la rama VALID. No selecciona clave, no la busca, no la comprueba: la
clave la aporta el receptor con `--pubkey`.

### El defecto

| medición | resultado |
|---|---|
| firmado por la clave **OTHER**, `issuer.keyId` dice `'key-ALPHA'`, verificado contra la pública de OTHER | exit 0, **`VALID (keyId=key-ALPHA)`** |
| `issuer.keyId` = `null` o ausente | `VALID (keyId=None)` |

> **El informe imprime VALID y nombra una clave que no firmó nada.**

Es la familia de DEF-2 otra vez, y en el peor lugar posible: **un campo que nadie verificó,
impreso adentro de un veredicto, heredando la autoridad del veredicto.** Un lector razonable lee
`VALID (keyId=key-ALPHA)` como «esto lo firmó key-ALPHA y lo comprobé». Lo comprobado es sólo que
*la clave que me diste* firmó esto. Quién es esa clave, el verificador no lo sabe ni lo mira.

Detalle menor de la misma línea: ausente o `null` imprimen literalmente `keyId=None` — un `repr`
de Python filtrándose a un informe que lee una persona.

### Por qué no lo arreglo acá y qué hay que decidir

La respuesta del operador era condicional: *si el verificador lo consume, es alcance y
`signature.keyId` debe rehusar cuando falta; si lo ignora, hoy es decorativo y la pregunta cambia.*
**Medido: no lo consume.** Así que la pregunta cambia — pero no a «es decorativo y da igual», sino
a algo peor: **es decorativo Y se publica en el veredicto.**

Los dos papeles coherentes, para la especificación de §6:

1. **`keyId` es ALCANCE.** Nombra qué clave debe verificar; el verificador compara la clave
   suministrada contra él y **rehúsa si falta** — una firma que no nombra su clave es media firma.
   **Costo medido:** un PEM **no lleva identificador propio** (comprobado: no hay tal campo; lo
   único derivable es un fingerprint, p. ej. SHA-256 del SPKI DER). Así que esta opción **no es
   implementable hasta que la especificación DEFINA qué denota un `keyId`**. Hoy no lo define nadie,
   que es exactamente cómo llegamos acá.
2. **`keyId` es una PISTA para encontrar la clave, no una afirmación.** Entonces **no puede
   aparecer en la línea del veredicto**, porque aparecer ahí lo convierte en afirmación.

**Lo que no es defendible es el estado de hoy**, que toma prestado de las dos: se comporta como
pista y se publica como afirmación.

### POR QUÉ ESTE SUBE EN LA COLA: hay un tercero mandando lectores a esa línea

Leído en fuente primaria (`deadman-guardian`, commit **`e42b948`**, sólo lectura). El emisor
**escribe el puntero a nuestra herramienta dentro del propio certificado**:

```csharp
// src/GuardianCore/Certificate.cs:543-545
.Set("tool", "deadman-kit")
.Set("install", "pip install deadman-kit")
.Set("command", "python -m deadman.verify_certificate certificate.json ledger.jsonl")
```

y también en la interfaz del AddOn (`nt/addon/DeadmanGuardianAddOn.cs:969`). No es sólo el HTML:
**`verifyInstructions` es un campo del documento que viaja con él** — y nuestro verificador ni
siquiera lo lee, es puramente para el lector humano.

**La asimetría que lo vuelve peor de nuestro lado que del suyo** (planteada por el operador,
1-sep):

> La tabla del emisor es **la palabra del emisor sobre sí mismo**, y un lector puede descontarla.
> La línea `VALID` es **la segunda opinión independiente**, y un campo impreso adentro se lee como
> que **sobrevivió a la verificación**. Misma clase de defecto, autoridad más alta.

Y hay una vuelta más, que es la que ordena el ítem:

> **El descargo del emisor FABRICA la autoridad que nuestra línea después usa mal.** El certificado
> dice, en su propio cuerpo, «no me creas: instalá esto y corrélo». Eso es el emisor **cediendo**
> autoridad. Cuanto más honesto es el emisor al mandar al lector a verificar, **más peso cae sobre
> la única línea que carga un campo que nadie comprobó.**

Es la peor combinación posible: la humildad de un lado creando la credibilidad que el defecto del
otro lado gasta.

**Reordenado por el criterio ya ratificado** (§8: *cuántos tienen que hacer algo mal*): **cero.**
Nadie tiene que equivocarse — un lector que sigue las instrucciones **impresas en el documento que
recibió** llega a una línea que nombra una clave no verificada. Deja de ser un camino hipotético:
está publicitado en la evidencia. Por eso 6b pasa del sexto puesto al segundo, detrás sólo de
DEF-3, que sigue primero por la excepción de rechazar trabajo honesto.

*(No es un pedido de arreglo inmediato del otro lado y no lo tratamos como tal: 6b es nuestro y no
necesita nada de ellos.)*

### El arreglo mínimo — APROBADO, y la decisión sobre qué poner en su lugar

**Se saca `keyId` de la cadena `VALID`.** No elige papel, así que puede ir antes de la
especificación; sólo deja de afirmar lo que no se midió. Aplica también a `--json`, que hoy
transporta la misma cadena (`:1524`) — y ahí es peor, porque un consumidor automático la parsea
como dato en vez de leerla como prosa.

**Decisión mía, con la medición que la sostiene: NO se reemplaza por el fingerprint de la clave
suministrada. Se saca y punto.**

Medido primero, porque era el argumento a favor: **el informe no nombra la clave en ningún otro
lado** — ni la ruta, ni nada. `signature_status` es la única línea que habla de la firma, en el
render (`:463`) y en el JSON (`:1524`). Así que un informe reenviado hoy no dice con qué se
verificó, y el fingerprint llenaría ese hueco.

**Aun así va afuera, por tres motivos en orden de peso:**

1. **Imprimir un fingerprint donde estaba `keyId` invita a la comparación que la especificación
   todavía no autorizó.** Nadie va a ver esos dos valores sin preguntarse si coinciden — y
   *responder eso* es exactamente lo que la spec tiene que definir. No prejuzga definiendo `keyId`;
   prejuzga **creando la pregunta**.
2. **Elegiría una definición de identidad de clave sin decirlo.** Hay al menos cuatro derivaciones
   plausibles (clave cruda de 32 bytes, SPKI DER, thumbprint RFC 7638, formato OpenSSH). Publicar
   una la vuelve la de facto. Es el mismo error que §6 documenta, mudado del comentario de código
   al formato de salida.
3. **No tiene lector nombrado hoy** (§5.2 obligación 3). Quien corre el verificador **eligió** la
   clave: la escribió en `--pubkey`. El lector que ganaría algo es el de un informe reenviado, y el
   artefacto que se reenvía es el **certificado**, no el informe.

**Y lo que se pierde, dicho sin maquillar:** `signature VALID` a secas significa «la clave que
aportaste verificó esto». Es menos de lo que parecía y **es exactamente lo que el verificador
sabe**. Si mañana hace falta que el informe sea autoportante —y puede hacer falta— eso entra por
la especificación, con el nombre de la derivación adentro, no por una línea de salida.

*(Propuesta retirada, con su motivo, según la norma de la casa: «reemplazar `keyId` por el
fingerprint de la clave suministrada». Se consideró, se midió el hueco que llenaría, y se descartó
por los tres motivos de arriba. No hace falta volver a medirlo.)*

**Y los dos papeles van a la especificación, no a un comentario de código.** Definirlos en un
comentario es exactamente cómo se llegó a que un mismo campo tenga dos tratamientos opuestos a 17
líneas sin que nadie esté equivocado.

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

> **RETRACTACIÓN (2026-09-01), y la afirmación retirada es mía.** Escribí acá un bloque titulado
> «CONFIRMADO DESDE LOS DOS LADOS» que decía que `session.timezone` **sale vacío hoy** por la ruta
> LT-2, y de ahí lo ascendí a «falla funcional en ruta alcanzable» y lo puse como paso 0 del orden
> de trabajo. **La mitad del guardián era falsa.** Medido por Ventana A:
>
> - `sessionResetTimeZone` está en `GuardianConfig.RequiredKeys`: un config que no lo trae **no
>   parsea**, así que nunca llega a ser un sello;
> - el emisor lee la zona del **snapshot sellado**, la misma fuente que Core;
> - los 6 certificados emitidos en esa máquina traen `America/Chicago`. Ninguno vacío.
>
> **Ese emisor no puede producir `""` en ese campo.** El paso 0 no existía.
>
> **Qué sobrevive, re-medido:** `""` da exit 1 con `DECORATIVE_FIELD`, `null` y ausente dan exit 0.
> Eso está bien y **no se toca `DECORATIVE_FILLER` por esto**. Simplemente hoy no lo gatilla nadie
> en ese emisor. El `?? ""` sigue siendo un defecto de honestidad —§5.6 manda ausente o `null`—
> y vuelve a ser eso y nada más.
>
> **Y el error de método fue mío antes que de nadie.** Este documento etiqueta la procedencia de
> cada afirmación del guardián —«no pude verificarlo, ese repositorio no es mío»— en todos lados
> menos acá. La solté exactamente una vez, en la afirmación que era más conveniente: la que
> convertía un hallazgo de estilo en una urgencia y me daba un paso 0. **Una medición mía más una
> afirmación ajena no es una confirmación** (§5.9).

#### Qué pasó realmente con ese `?? ""` — SÍNTESIS, no medición

**Procedencia, pegada como manda §5.9:** lo que sigue es **síntesis del operador sobre dos
reportes de Ventana A**. No es medición nuestra, no es medición suya, y **está pendiente de
confirmación** por Ventana A. Hasta que llegue, no se construye encima.

Según esa síntesis, las dos cosas son ciertas a la vez:

- Ventana A enumeró **siete** sitios `?? ""` e incluyó `session.timezone` entre ellos;
- y midió después que `sessionResetTimeZone` es `RequiredKey`, así que el config no parsea sin él
  y **esa rama nunca se toma**.

O sea: **el `?? ""` existe en el código y su caso es inalcanzable.**

Eso lo convierte en un hallazgo chico y de otra naturaleza:

> **Un `?? ""` que guarda un caso imposible es código defensivo que le hace creer al lector que el
> caso PUEDE ocurrir. No es una falla: es una pista falsa.**

Y es la pista falsa que nos costó el paso 0 a los dos lados. No hay nada roto que arreglar ahí;
hay una afirmación implícita en el código que contradice a la configuración, y el arreglo honesto
es borrar el `??` —no cambiar el `""` por `null`— porque el valor por defecto no puede darse.

*(Nota menor pendiente de la misma confirmación: **seis** o **siete** sitios. El pedido original
decía seis; la enumeración de Ventana A dice siete. Es exactamente el tipo de detalle que el ítem
1b del aviso existe para cerrar.)*
Pero `dayKey` vive en el mismo objeto `session`, y ahí omitir desarma una protección. **El mismo
patrón de arreglo, aplicado a dos campos vecinos, da un resultado correcto y un desastre.**

### APLICADO (2026-09-02)

**La severidad dejó de depender de que el campo esté.** El daño se establece primero —eventos
materiales fuera del rango— y `dayKey` sólo hace el ancla más precisa. Medido sobre el ejemplo
propio del repo:

| `certificate-truncated.json` | antes | ahora |
|---|---|---|
| como se publica | exit 1 `RANGE_TRUNCATED` | exit 1 `RANGE_TRUNCATED` |
| **sin `dayKey`** | **exit 0** | **exit 1 `RANGE_TRUNCATED`** + `SCOPE_MISSING` |
| **`dayKey` = `null`** | **exit 0** | **exit 1** |
| **sin el bloque `session`** | **exit 0** | **exit 1** |
| **CONTROL** día limpio sin `dayKey` | exit 0 | **exit 0** + `SCOPE_MISSING` |

Y `SCOPE_MISSING` dice lo que §5.8 escalón 4 exige: *el chequeo no corrió*, no que haya pasado.

#### Una precisión sobre el ruling, medida antes de defenderla

El ruling decía: *si hay eventos materiales fuera del rango, es contradicción con `dayKey` y sin
él*. **Aplicado tal cual acusaría a todo export honesto de mitad de sesión** — una sesión que
sigue corriendo tiene eventos materiales después de cualquier export que se le tome, porque eso es
lo que *sigue corriendo* significa. Es exactamente la clase de daño que este archivo lleva toda la
tanda quitando.

Así que el ancla sin `dayKey` **no es «hay material afuera» sino «una sesión CERRÓ pasado el
rango»**: un `DAY_CLOSED` después de `toSeq` prueba que el registro siguió y terminó. Eso cierra
la brecha del ejemplo truncado —que tiene su `DAY_CLOSED` en seq 16— sin cargar contra nadie
honesto. Control medido: con el `DAY_CLOSED` quitado del ledger, un export temprano con material
después queda en `POST_RANGE_MATERIAL_EVENTS` (`cannot_verify`), con y sin `dayKey`.

#### Y el mensaje explicaba la brecha con la causa equivocada

Decía *«with no DAY_CLOSED for this session»* incluso cuando el motivo real era que el certificado
**no nombra ningún día**. Corregido: ahora dice cuál de las dos cosas pasó. Era el mismo defecto
que este verificador le viene encontrando a los artefactos ajenos, en su propia salida.

*(La salida original decía:)*

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
`payload` da `DIALECT_MISMATCH` más `NOTHING_ELSE_CHECKED`. *(Medido entonces como exit 1; **hoy es exit 2** — ver §6bis: la ruta se re-ruteó a `cannot_evaluate` el 1-sep, y es el único cambio de código de esta tanda.)*

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
5. **SU TIPO PUEDE EXPRESAR «NO SÉ».**

   > **Un campo cuyo tipo no puede expresar «no sé» lo va a expresar como «no», y «no» es la
   > respuesta que acusa.**

   Antes de elegir un booleano para un hecho **observado**, preguntar qué pasa cuando el
   observador **no pudo mirar**. Si la respuesta es «sale `false`», el tipo está mal elegido: el
   tercer estado no desaparece por no tener casillero, se disfraza del peor de los dos que hay.

   No es una regla sobre este verificador. Es sobre la **forma** de cualquier campo, y va acá
   —entre las obligaciones de todo campo nuevo— y no entre los defectos, porque su valor es
   **prevenir el próximo**, no explicar los tres que ya pasaron: §6bis, DEF-6 y DEF-7 son la misma
   forma con tres disfraces. Las tres veces la herramienta tenía la información para saber que no
   sabía, y eligió el valor que acusa.

   **Hace pareja con la regla del NOMBRE** (DEF-2: `triggerEvent` prometía una causa y entregaba
   adyacencia). Nombre y tipo son las dos formas en que **un campo promete una capacidad que no
   tiene** — el nombre promete saber *qué*, el tipo promete poder decir *cuánto sabe*.

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

## 5.11 — RULING — dos implementaciones que adivinaron igual no se corroboran

> **DOS IMPLEMENTACIONES INDEPENDIENTES DE LA MISMA REGLA EQUIVOCADA SIEMPRE COINCIDEN, Y SU
> COINCIDENCIA SE LEE COMO CORROBORACIÓN.**

Es la **verificación cómplice un piso más arriba**: allá un test compartía la idea de quien lo
escribió; acá **dos SISTEMAS comparten un malentendido**. Cruzarlos no prueba nada sobre el mundo
— prueba que los dos leyeron lo mismo.

> **La coincidencia entre dos implementaciones sólo es evidencia si fueron derivadas
> INDEPENDIENTEMENTE. Cuando no hay documento del cual derivarlas, lo único que comparten es el
> supuesto.**

Y de ahí el enlace con §6, que es la parte que cambia cómo se lee todo acuerdo entre los dos lados:

> **Sin especificación, los dos lados adivinaron. Adivinaron igual. Y su acuerdo parece
> confirmación.**

**Cómo se aplica.** Antes de usar «los dos lados coinciden» como evidencia, preguntar: *¿de qué
documento derivó cada uno su implementación?* Si la respuesta es «de ninguno» o «uno miró al otro»,
el acuerdo es un hecho sobre las dos implementaciones, **no sobre el mundo**, y se reporta así.
Un test de conformidad entre emisor y verificador vale exactamente lo que valga la independencia de
sus derivaciones — y esa independencia la produce la especificación, no el cuidado de quien
programa.

**Corolario incómodo:** mientras §6 no exista, **todo acuerdo entre `deadman` y `deadman-guardian`
tiene este descuento aplicado.** No los invalida; los degrada de «corroborado» a «consistente», que
es una palabra distinta y más chica.

---

## 5.9 — RULING — dos fuentes de calidad distinta no se suman

> **Cuando se citen dos lados de algo, cada lado va con su procedencia pegada, y «confirmado» se
> reserva para cuando LOS DOS son mediciones.**

Adoptada 2026-09-01 después de que este documento publicara un bloque titulado «CONFIRMADO DESDE
LOS DOS LADOS» cuya mitad ajena era falsa (§DEF-4, retractación).

**El modo de falla es distinto de los anteriores y por eso va escrito aparte.** No fue inventar un
dato, ni el instrumento contestando por el sujeto:

> **Fue combinar una MEDICIÓN con una AFIRMACIÓN y llamar al resultado CONFIRMACIÓN.**

Una medición propia y una afirmación ajena no verificada no se promedian: el resultado hereda la
calidad de la **peor** de las dos, no de la mejor. Y la palabra «confirmado» hace exactamente lo
contrario — hereda la calidad de la mejor, y borra la juntura donde estaba la duda.

**Por qué es especialmente traicionero:** la mitad medida es verdadera. `""` **sí** da exit 1. Todo
lo que se puede comprobar de la afirmación compuesta, comprueba. Lo que no aguanta es la parte que
nadie verificó, y es justo la parte que aportaba la urgencia. **Una afirmación mitad medida no se
ve como una afirmación a medias: se ve como una afirmación con evidencia.**

**Cómo se aplica.** Cada afirmación de dos fuentes se escribe con las dos procedencias visibles:
*«medido acá: X. Reportado por el otro lado, no verificado por nosotros: Y.»* La conclusión
conjunta se marca con la calidad de la peor mitad. **«Confirmado» es una palabra reservada**, no un
sinónimo de «coincide con lo que esperaba». Y la señal de alarma es la conveniencia: la afirmación
que asciende un hallazgo a urgencia, o que produce un paso 0, es la que hay que releer con la
procedencia delante.

---

## 5.12 — LA SUPERFICIE DEL CONTRATO, enumerada y medida

**Un bloqueo cuyos límites nadie midió empieza a bloquear más de lo que le toca** (operador,
1-sep). «Toca el contrato con la librería» se venía usando como bloqueo general sin que nadie
probara dónde termina. Acá termina, medido.

> **El contrato cubre lo que el verificador LEE, o lo que cambia una afirmación RECOMPUTADA.
> Todo lo demás del payload es del emisor y no necesita acuerdo.**

### Lo que el verificador lee de una fila del ledger — la lista completa

| qué | dónde | por qué importa |
|---|---|---|
| `seq`, `tsUtc`, `event`, `prev`, `hash`, `schemaVersion` | dialecto y cadena | estructura; `_check_dialect` exige que estén, `hash_of` los hashea |
| **el `payload` ENTERO** | `hash_of` | está dentro del cuerpo hasheado, así que cualquier cambio cambia el hash **de esa entrada** |
| `payload.dayKey` | `:670` | ancla el chequeo de cobertura del día |
| `payload.orderId` | `:1020` | distingue reintentos del mismo rechazo |
| `payload.basis` (en `SEAL_EXPIRED`) | `:832` | `sealExpiryBasis`, una garantía positiva cuando dice monotonic |
| `payload.fresh` (en `GUARDIAN_STARTED`) | `:873` | separa un primer arranque real de un segmento rotado |

**Son CUATRO claves de payload, no dos.** El relevamiento que me llegó decía «`seq`, `tsUtc`,
`event`, `payload.dayKey`, `payload.orderId`»: **le faltaban `basis` y `fresh`**, y `fresh` es
justamente del evento que el ítem 3 quiere tocar.

**Y son claves que muerden**, con el control construido en un escenario donde efectivamente se
consultan (el primero que armé no disparó, porque el rango dejaba a `DAY_OPENED` adentro y la clave
nunca se miraba — el control fallado se reporta, no se esconde):

| | veredicto |
|---|---|
| `certificate-truncated.json` con `dayKey` intacto | **`RANGE_TRUNCATED`, exit 1** |
| el mismo, con `dayKey` **renombrado** en el ledger | **exit 0, limpio** |
| `fresh` presente | `indeterminateStarts: 0`, `coverageIsLowerBound: false` |
| `fresh` renombrado o ausente | **`indeterminateStarts: 1`, `coverageIsLowerBound: true`** |

Renombrar `dayKey` **apaga el chequeo de truncamiento** — la misma familia que DEF-4, por otra
puerta.

### Los cuatro pedidos en cola, clasificados

| pedido | ¿cae bajo el contrato? | medido |
|---|---|---|
| **1. evento de acuse** | **SÍ** | un evento nuevo **no es inerte**: entra en `reasons` y puede quedar como `triggerEvent`. Insertado antes del `FAIL_CLOSED_ENTERED` da `triggerEvent: "HUMAN_ACK"` |
| **2. `dayKey` en `CONFIG_LOADED`** | **NO** | agregarlo verifica limpio y no cambia ninguna afirmación. `dayKey` sólo se consulta en `DAY_OPENED`/`DAY_CLOSED` |
| **3. `buildHash` en `GUARDIAN_STARTED`** | **NO para agregarlo — SÍ una condición** | agregarlo verifica limpio. Pero `fresh` vive en ese payload y **yo lo leo** (`:873`), y el evento se emite desde **dos sitios** con payloads distintos (`Guardian.cs:185` con `fresh`, `:214` sin él) |
| **4. renombrar `exhausted` en `LOCKOUT_INCOMPLETE`** | **NO** | claims recomputados **idénticos**, continuidad **idéntica**, exit 0 con los dos nombres, y **los hashes de las entradas ya escritas no cambian** |

**Tres de los cuatro salen.** El único que el contrato bloquea de verdad es el acuse, y lo bloquea
por un motivo medido y no por precaución.

### Sobre el hash, que es la pregunta que suele confundir

Un campo de payload está **dentro** del cuerpo hasheado, así que renombrarlo cambia el hash **de
las entradas que se escriban de ahí en adelante**. Las ya escritas **no se tocan**: conservan sus
bytes y sus hashes, la cadena sigue verificando, y un ancla publicada antes sigue cubriendo su
historia. Medido: 16 entradas viejas con hash idéntico, sólo la nueva difiere.

**Eso no es un problema del contrato: es la cadena funcionando.** Un ledger cuyo esquema de payload
evoluciona no necesita `schema_version` nuevo mientras el **cuerpo hasheado** —qué campos entran—
no cambie (§5.1). Renombrar una clave *dentro* del payload no cambia qué entra: entra el payload.

### La regla que queda, para el próximo caso

**Antes de bloquear algo por «toca el contrato», medir si lo toca.** Concretamente: ¿el verificador
lee esa clave, o el cambio altera una afirmación recomputada? Si ninguna de las dos, **no es del
contrato** — puede seguir siendo mala idea por reglas del propio emisor (un campo sin lector es
decorativo, §5.2.3), pero **eso lo decide el emisor solo y no espera a nadie.**

Un bloqueo sin límites medidos es del mismo género que un proxy sin medir: **se cree porque nunca
costó nada creerlo**, y el costo aparece como trabajo detenido que nadie atribuye al bloqueo.

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

### El segundo caso, que lo convierte de anécdota en requisito (2026-09-01)

El hallazgo llegó por otra puerta y con otro campo, y **el segundo caso es lo que lo asciende**:

*(Procedencia, §5.9: la mitad del guardián es **reportada por Ventana A, no medida por nosotros**.)*

- `CertificateRequest.KeyId` tiene una fuente y **dos consumidores tratados al revés, a 17 líneas**:
  `issuer.keyId` se omite si viene vacío, `signature.keyId` lo vacía.
- Ventana A buscó el papel de cada uno: **ni `SPEC.md`, ni `CERT_CONFORMANCE.md`, ni
  `AMENDMENTS.md`** de ese repo los definen. Los comentarios citan un `CERT_SPEC` que vive de este
  lado.
- Y de este lado, medido: `CERT_SPEC` **tampoco existe**.

> **La especificación que definiría esos papeles no existe en NINGÚN lado. Los dos repositorios
> citan un documento que nunca se versionó, y por eso el mismo campo tiene dos tratamientos
> opuestos SIN QUE NADIE ESTÉ EQUIVOCADO.**

Esa última parte es la que hay que retener. No es un bug de nadie: es la consecuencia exacta de una
referencia compartida a un documento ausente. Cada lado eligió un tratamiento razonable para un
campo cuyo papel nadie escribió, y los dos tenían igual derecho.

**Un documento faltante no produce un hueco visible. Produce dos decisiones locales coherentes,
incompatibles entre sí, y ninguna reconocible como el error.**

Por eso §6 deja de ser una observación y pasa a ser un requisito con dos casos que lo esperan: la
regla de extensión (§5) y los papeles de `keyId` (DEF-5).

### 6.1 Los supuestos compartidos, ordenados por CONSECUENCIA y no por dependencia

El descuento de §5.11 («consistente», no «corroborado») es **uniforme**. El riesgo **no**. La
pregunta *¿hay un tercero que dependa de este acuerdo hoy?* es **necesaria y no suficiente**: hay
que cruzarla con *¿un desvío entre los dos lados sería RUIDOSO o SILENCIOSO?* **Un desvío ruidoso
se vigila solo** — no puede esconderse, así que no necesita §6 para protegerlo.

| supuesto compartido | ¿tercero hoy? | un desvío sería… | riesgo |
|---|---|---|---|
| **qué cuenta como EPISODIO** | sí, el lector del certificado | **SILENCIOSO** — medido: emisor y verificador con la misma regla dan exit 0, cero hallazgos | **el más alto** |
| cuerpo hasheado de la entrada | sí, quien verifica la cadena | ruidoso entre dialectos (`CHAIN_BROKEN`); **silencioso para una EXCLUSIÓN compartida dentro de uno** — que es DEF-1 | medio, y ya atendido |
| preimage de `certHash` | sí | **RUIDOSO** — medido, ver abajo | **bajo** |
| orden canónico | sí | ruidoso; es *un componente* de los dos de arriba, no un cuarto ítem | bajo |

**Desmiento el candidato a encabezar.** La hipótesis era que el preimage de `certHash` iba primero
porque un supuesto no examinado ahí haría decir `VALID` por la razón equivocada en todos los
certificados sin que nadie lo viera. **Medido, es al revés: es el más autovigilado de los cuatro.**

| prueba | resultado |
|---|---|
| campo top-level desconocido agregado al certificado | **entra** en el preimage; sin recomputar ⇒ `CERTHASH_MISMATCH`, exit 1 |
| el emisor usando otra canonicalización (separadores distintos) | `CERTHASH_MISMATCH`, exit 1 |

Dos motivos, y el segundo pesa más que el primero:

1. **Un desvío falla en cada corrida, de inmediato y ruidosamente.** Los dos lados no *pueden*
   compartir en silencio un supuesto equivocado ahí: el acuerdo se re-testea entero cada vez que
   alguien verifica un certificado. Es el único de los cuatro con una prueba continua encima.
2. **Sus dos exclusiones —`certHash` y `signature`— no son un supuesto: están FORZADAS por el
   orden.** La firma se computa sobre el hash, así que no puede estar adentro. Los dos lados lo
   derivaron de una restricción real, no de haber leído lo mismo. **Eso sí es una derivación
   independiente**, que es exactamente lo que §5.11 pide y casi nunca hay.

#### La autovigilancia de `certHash` es ELLA MISMA un acuerdo no examinado

`certHash` está abajo porque el verificador lo recomputa en cada corrida. **Eso no es una propiedad
del CAMPO: es una propiedad de la CONDUCTA DE ESTA VERSIÓN DEL VERIFICADOR** (operador, 1-sep). Si
una versión futura cachea, agrega un modo rápido, o deja de recomputar por rendimiento, el ruido
desaparece y el supuesto de la canonicalización se vuelve silencioso. **Y la pérdida de una
comprobación es ella misma silenciosa: nadie recibe un aviso cuando deja de mirarse algo.**

**Y no es un riesgo futuro: ya es un hecho presente.** Medido, con un `certHash` deliberadamente
falso en los seis casos:

| ruta | exit | ¿se recomputó `certHash`? |
|---|---|---|
| **CONTROL** certificado sano por lo demás | 1 | **SÍ** |
| sin `ledgerDialect` | 2 | **NO** |
| `ledgerDialect` desconocido | 2 | **NO** |
| sin `claims.ledgerRange` | 2 | **NO** |
| `ledgerRange` con `fromSeq > toSeq` | 2 | **NO** |
| dialecto declarado ≠ el del archivo | **1** ⇒ **2** (arreglado, §6bis) | **NO** |

**Cinco de seis rutas ya lo saltean**, y una de ellas emite un **veredicto** (exit 1) sin haberlo
comprobado nunca.

**La sexta fila resultó ser un código de salida mal ruteado, no sólo un salteo, y se arregló** (§6bis). En descargo del resto: **todas esas rutas declaran que se detuvieron** — `cannot_evaluate` en las
de exit 2, y `NOTHING_ELSE_CHECKED` explícito en la de exit 1 (`:1129`). Es §5.8 escalón 4 bien
hecho, ya. **Pero declarar que un chequeo no corrió no es lo mismo que garantizar que corre**, y el
ranking bajo de `certHash` depende de la garantía, no de la declaración.

**Por eso va a §6, y no como definición de campo sino como CONDUCTA EXIGIDA:**

> **Un verificador conforme DEBE recomputar `certHash`.**

Sin esa línea, su ranking bajo es un dato sobre esta versión del verificador, no sobre el formato.
Es la misma clase que §5.11 en otro plano: **una medición sobre la instancia actual leída como
propiedad de la cosa.**

#### Y «forzadas por el orden» explica QUÉ SE EXCLUYE, no QUÉ SE INCLUYE NI CÓMO

Precisión que refina y no refuta (operador, 1-sep). Que la firma se compute sobre el hash fuerza
las **dos exclusiones**, y eso sigue siendo derivación independiente genuina. Pero **el orden de
claves, el formato de números, la normalización unicode y los espacios no los fuerza ninguna
restricción.** Esa mitad del preimage está protegida por **ruido**, no por derivación.

**Mi propia medición lo mostraba sin que yo lo viera:** «el emisor usando otra canonicalización da
`CERTHASH_MISMATCH`» prueba que **el desvío es ruidoso**, no que la regla sea derivada. Son cosas
distintas y yo las había cobrado como una sola.

Así que `certHash` está abajo por **dos motivos de calidad distinta**, y **sólo uno sobrevive a un
verificador que deje de comprobar**: la derivación de las exclusiones sobrevive; el ruido de la
canonicalización no. Eso es lo que vuelve a «un verificador conforme DEBE recomputar» una línea que
carga peso y no un adorno.

**El que encabeza es «qué cuenta como episodio»**, y por los dos ejes a la vez: el lector del
certificado depende de él (es el relato de lo que pasó), un supuesto compartido ahí **no produce
ningún hallazgo** — medido, exit 0 —, y **ya se sabe equivocado**, porque la atribución por
adyacencia de DEF-2 vive adentro de esa misma computación. No es «consistente a la espera de §6»:
es el único donde el descuento ya tiene consecuencia viva.

### 6.2 Cómo se escribe §6 sin reproducir el supuesto — pre-registro por campo

Mi propuesta era «decidir cada campo por lo que debe significar y después medir qué implementación
se aparta». **Tenía el instinto y le faltaba el control**, y el hueco es real: quien escriba §6 ya
conoce las dos implementaciones y **no puede desconocerlas**. La hoja en blanco no purga el
supuesto, sólo esconde de dónde vino — §6 podría reproducirlo palabra por palabra y **el resultado
se vería igual que un éxito**.

Lo que sí se puede conseguir no es ignorancia: es **una pregunta generadora distinta** (operador,
1-sep).

> Las dos implementaciones se escribieron contestando **«cómo computo este campo»**.
> §6 tiene que contestar otra: **«qué queda habilitado a concluir un lector de este campo, y qué
> tiene que ser verdad para que esa conclusión se sostenga»**.

Se deriva del lado del **CONSUMIDOR**, no del productor — y es un eje donde las dos
implementaciones **están mudas**: ninguna codifica en ningún lado a qué tiene derecho el lector.

**El mecanismo, que es maquinaria que esta casa ya usa: pre-registro, campo por campo.** Se escribe
a qué tiene derecho el lector, **se sella**, recién después se abren las dos implementaciones, y se
anota el desvío. Sin el sello previo, **la convergencia inconsciente no se puede distinguir del
acuerdo genuino.** Campo por campo, no documento por documento.

**Y trae su propio control, que es lo que a mi versión le faltaba:**

> **SI §6 ESCRITA ASÍ REPRODUCE LAS DOS IMPLEMENTACIONES EXACTAMENTE, CAMPO POR CAMPO, SIN NINGÚN
> DESVÍO, ESO NO ES ÉXITO: ES LA SEÑAL DE QUE SE ESCRIBIÓ MIRANDO EL CÓDIGO.**

**Cero desvíos es la alarma, no la meta.** Es la regla de la casa —toda medición incluye un control
que DEBE dar distinto— aplicada a la escritura de una especificación: **el control es el propio
conteo de desvíos.** Y cada desvío se trata como hallazgo, nunca como error de transcripción: es la
única evidencia de que la pregunta generadora fue de verdad distinta.

### 6.2b El primer campo de §6 es un CONTROL DEL MÉTODO, y ya lo tenemos

«Qué cuenta como episodio» encabeza la lista **y además tiene un error conocido adentro**: la
atribución por adyacencia de DEF-2 vive en esa misma computación. **Eso no es una desgracia, es un
regalo: el primer campo de §6 tiene respuesta conocida.**

**El procedimiento, y se corre como control antes que como campo:** escribir la definición de
episodio desde el lado del consumidor, pre-registrada y **sellada**, sin mirar ninguna de las dos
implementaciones. Después abrir las dos.

> **SI EL PROCESO ES REAL, TIENE QUE ENCONTRAR LA ATRIBUCIÓN POR ADYACENCIA SIN QUE NADIE SE LA
> HAYA DICHO.**

Si la encuentra, el método sirve **y se sabe sobre un caso con respuesta**. Si no la encuentra, el
método no sirve y **se sabe barato**, en el único campo donde el fracaso es reconocible. Cualquier
otro campo primero deja sin saber si cero desvíos fue éxito o convergencia inconsciente.

#### La objeción que tengo que poner: yo soy el peor autor posible de ese pre-registro

**Yo ya encontré la atribución por adyacencia.** El control pide que el proceso la descubra sin que
nadie se la haya dicho, y **a mí me la dijo mi propia medición de ayer.** Si yo escribo el
pre-registro sellado de episodios y «descubre» la adyacencia, eso no prueba que la pregunta
generadora sea distinta: prueba que sé la respuesta. **Es el instrumento contestando por el sujeto
(§ apéndice), en el lugar exacto donde el método se está validando a sí mismo.**

No lo puedo neutralizar con cuidado. Tres salidas, y la elección es del operador:

1. **Otro autor escribe ese pre-registro** — alguien que no haya visto `Certificate.cs:238` ni
   `verify_certificate.py:974-982`. Es la única que preserva el control entero.
2. **Se elige otro campo de validación**: uno cuya respuesta el operador conozca y yo no. El
   fracaso sigue siendo reconocible —por él— y mi ignorancia es genuina.
3. **Se acepta degradado y se dice:** yo escribo el pre-registro, y vale como prueba de que el
   método **produce una definición utilizable**, no de que **descubra** lo que nadie le dijo. Es
   estrictamente menos, y habría que no venderlo como más.

**Mi recomendación es (2)**, porque conserva el control y no depende de conseguir un autor virgen:
el valor del ejercicio está en que el fracaso sea reconocible, y para eso alcanza con que **alguien**
sepa la respuesta — no hace falta que sea quien escribe.

### 6.3 El modelo ya probado en casa: los dialectos nombrados

**Confirmado, medido literalmente.** El ledger tiene **dos dialectos NOMBRADOS** con reglas de hash
distintas:

| | cuerpo hasheado | genesis | ¿entra un campo top-level nuevo? |
|---|---|---|---|
| `guardian-core-v1` | **todo menos `hash`** | `"genesis"` | **sí** |
| `deadman-kit-v1` | **siete campos nombrados** | 64 ceros | **no** |

Y la lectura del operador es correcta y es el punto:

> **No es que los dos lados se pusieran de acuerdo: es que dejaron de fingir que había una sola
> regla.** Donde la casa se tomó el trabajo de NOMBRAR las dos reglas, la diferencia quedó
> **visible** en vez de coincidente.

**Pero el mecanismo tiene tres partes, no una, y §6 necesita las tres:**

1. **Nombrar** las reglas. Solo eso dejaría al lector adivinando cuál aplica.
2. **DECLARAR** cuál aplica: el certificado lleva `ledgerDialect`, y el comentario del archivo dice
   por qué no se olfatea — *«sniffing the shape would let a forger hand over a ledger built in
   whichever schema suits the lie»* (`:93-96`).
3. **Hacerla cumplir**: `_check_dialect` falla cerrado en **cada entrada**, no sólo en la primera.

**Y su límite, que hay que decir para no sobreextender el modelo:** los dialectos funcionan porque
la pluralidad era **legítima** — dos productores, dos esquemas. Para «qué cuenta como episodio» hay
**una sola** regla, compartida y no examinada; ahí no hay dos dialectos que declarar. **El patrón
de los dialectos sirve para la pluralidad genuina; el pre-registro de §6.2 sirve para la regla
única que nadie miró.** §6 necesita los dos, y saber cuál aplica a cada campo es parte de
escribirla.

#### Orden de gravedad: DESVÍO, y por encima, NECESITA-DIALECTO

Para cuando aparezca el primer caso ambiguo (operador, 1-sep):

| hallazgo | qué dice |
|---|---|
| **desvío** | un lado se equivocó |
| **necesita-dialecto** | **los dos lados nunca estuvieron computando lo mismo**, y el acuerdo de hoy es un artefacto de que un lado nunca ejercitó el caso del otro |

**El segundo es más fuerte.** Un desvío se corrige. Un «necesita dialecto» descubierto escribiendo
§6 desde el lado del consumidor significa que la coincidencia observada hasta hoy **no era acuerdo
sino falta de ocasión** — y ésa es exactamente la forma que §5.11 no puede distinguir desde afuera,
porque desde afuera se ve idéntica al acuerdo genuino.

## 6bis. Dos invariantes documentados que no se cumplían

### El que se arregló: `DIALECT_MISMATCH` devolvía «te agarré mintiendo»

La doc pública lo dice normativamente, y es la regla que el propio repo se puso
(`docs/verify-certificate.md`):

> **«1 and 2 are kept apart on purpose.»** *«I caught you lying»* y *«I could not look»* son
> hechos distintos, **y una herramienta que los colapsa se puede deshabilitar entregándole un
> archivo roto.**

`DIALECT_MISMATCH` devolvía **1**. Nada se había medido: el verificador se **negó a mirar** un
archivo que no es el que el certificado declara.

**Y el argumento decisivo no es la simetría sino la dirección del daño**, medido:

| | veredicto |
|---|---|
| certificado **honesto**, con **su** ledger | exit 0 |
| **el mismo certificado honesto**, con el archivo **equivocado** | **exit 1, `DIALECT_MISMATCH`** |

**Nadie tocó el certificado.** Alcanzaba con entregar otro archivo para que el veredicto publicado
fuera `CONTRADICTED` sobre un documento honesto — y quien automatiza esto escribe
`if exit != 0: rechazar`, así que la declaración `NOTHING_ELSE_CHECKED` que sí estaba **vive en la
prosa mientras el veredicto vive en el código de salida**. Es la advertencia de la propia tabla,
apuntada al tenedor del documento en vez de a la herramienta.

**Arreglado** (único cambio de código de esta tanda): `rep.contradict(...)` → `rep.cannot_evaluate(...)`.

**El precio, nombrado y no escondido:** un certificado que **sí** miente sobre su dialecto ya no
se llama mentiroso, porque **el verificador no puede distinguirlo de un certificado honesto al que
le dieron el archivo equivocado** — los dos producen la misma entrada. Se paga a propósito: §5.3
dice que acusar a un documento honesto es catastrófico.

Y salió un test que faltaba: `test_c17_an_honest_certificate_cannot_be_smeared_with_the_wrong_ledger`,
con su control (el mismo certificado con su propio ledger, que debe seguir pasando). La
meta-garantía de que *«un verificador que sólo dice OK es un sello de goma»* quedó **más fuerte**:
ahora exige que todo ataque sea rechazado **y nombre algo**, y separa los cuatro que son mentiras
del que es indistinguible.

*(No fue «de un renglón», y por qué no lo fue es informativo: la decisión vieja estaba codificada
en **tres** lugares del test suite, uno de ellos la meta-garantía. Un cambio de una línea que toca
tres aserciones es un cambio de contrato disfrazado de typo.)*

### El que sigue sin cumplirse: `.gitattributes` dice que todos los blobs son CRLF

Encontrado **por romperlo**: mi primer intento de parche reescribió `verify_certificate.py` entero
(3.075 líneas de diff para un cambio de una) porque `write_text` normalizó los finales de línea.

El `.gitattributes` del repo dice, textualmente:

> *«Every blob in this repo is CRLF; `* -text` stops git converting endings, so an edit that keeps
> them no longer rewrites the file and moves its blame.»*

**Medido contra los blobs almacenados: 26 de 71 archivos tienen líneas LF**, incluido
`deadman/verify_certificate.py` — **entero**, 1.535 líneas. Y **cuatro archivos de test están
mezclados adentro**: `test_c_certificate_example.py` (206 CRLF + 38 LF), `test_c_continuity.py`
(372 + 28), `test_g11_ledger.py` (294 + 49), `test_g12_clock_and_paths.py` (49 + 45).

**La afirmación es falsa, y su falsedad produce exactamente el daño que el archivo existe para
evitar**: la premisa de `* -text` es que todo es CRLF, así que una herramienta que normaliza
reescribe el archivo y mueve el blame — que es lo que me acaba de pasar.

**No lo arreglo**: re-normalizar 26 archivos es precisamente el commit que ese comentario dice que
no quiere. Es una decisión, no una tarea. Queda anotado con sus números para que se decida:
corregir los blobs, o corregir la frase.

## 7. Estado de los pedidos del emisor

| pedido | ¿rompe algo? | estado |
|---|---|---|
| **2 — `buildHash` en `GUARDIAN_STARTED`** | no | **adelante**, dentro de `payload`. Se **omite** si no se puede determinar — nunca `"example"`, que es el caso que parió la regla 5. **Verificar antes que no se pierda `fresh`**: el ejemplo empaquetado lleva `{"fresh": true, "state": "DISARMED"}`, y `fresh` está entre las cuatro cosas que `request-to-guardian-emitter.md` §5 dice que no deben cambiar. No pude verificarlo contra el emisor real |
| **3 — `dayKey` en `CONFIG_LOADED`** | no | **CONDICIONADO** a que cert-1 lo consuma — en espera, no retirado. Hoy nadie lo leería: `dayKey` sólo se mira en `DAY_OPENED`/`DAY_CLOSED` (`:621-622`), y uno que nombre otro día pasa sin comentario (medido). Un campo sin lector no se escribe (§5.2.3) |
| **1 — evento de acuse** | **sí, hoy** | **bloqueado por DEF-2**. No se puede emitir hasta cerrar el cajón de sastre y la atribución posicional, o el primer acuse durante un fail-closed se publica como su causa |

## 8. — RULING — Orden de trabajo

1. ~~**DEF-3, las dos mitades**~~ — **HECHO (2026-09-01, )**: la inversión **y** la procedencia, con el barrido escrito como propiedad (144 nombres generados) y el backup como control: con el código viejo y los tests nuevos fallan exactamente los dos que afirman el arreglo. Suite 317. Arrancaba acá, que es donde
   su propio argumento ya lo ponía antes de que yo inventara un paso 0: es lo único que hoy hace
   **rechazar certificados honestos**, ya está probado y pasa 100/100. Los otros tres defectos
   dejan pasar algo malo; éste rechaza algo bueno, que es lo que enseña a apagar el verificador.
   *(El paso 0 que había acá —`session.timezone`— se retiró: ver la retractación en §DEF-4.)*
2. ~~**DEF-5, arreglo mínimo (6b)**~~ — **HECHO (2026-09-01)**: `keyId` fuera de la línea `VALID`,
   sin reemplazo. **Sube del sexto puesto al segundo** (1-sep): el emisor imprime el puntero a
   nuestra herramienta **dentro del certificado** (`Certificate.cs:543-545`), así que hay un
   tercero mandando lectores a esa línea exacta. Por el criterio de §8 es tier **cero** — nadie
   tiene que equivocarse. Es un cambio de una línea y no necesita la especificación.
3. ~~**DEF-2**~~ — **HECHO (2026-09-01, `d51395c`)**: renombrado a `precedingEvent`/`precedingSeq`,
   comparado, y con la exclusión `HUMAN_*` que resultó ser la mitad que de verdad bloqueaba el
   acuse. Falta sólo la limitación de causas, que espera al emisor. Era: y la
   limitación de causas (emisor primero, verificador después: §DEF-2 ruling parte 3). La
   comparación es además lo que reemplaza al chequeo de forma que la procedencia acaba de quitar.
4. **DEF-6 primera mitad** — **HECHO (2026-09-01, `514205c`)**: el truncamiento deja de acusar.
5. ~~**DEF-4**~~ — **HECHO (2026-09-02)**: la severidad sigue al daño y ya no depende de que `dayKey` esté. Era: con
   `certificate-truncated.json` sin `dayKey` como control. **Por calendario**: el emisor está por
   limpiar los seis `?? ""` y la regla tiene que existir antes que la limpieza.
5. **DEF-1**, opción A — lista negra `{hash, sig}` en `_kit_body` y `_entry_hash`, con el test de
   inyección top-level como control.
6. La exclusión `HUMAN_*` en `recompute_claims`, con D2 como control.
7. El marcado `UNKNOWN_EVENT_KIND` como `cannot_verify`.
8. El papel de `keyId` en sí — espera §6. El arreglo mínimo ya salió en el paso 2.
9. Escribir §5 donde se decida en §6.
10. Recién entonces, el evento de acuse.

### — RULING — el criterio de orden

> **EL ORDEN VA POR CUÁNTA GENTE TIENE QUE HACER ALGO MAL PARA QUE EL DEFECTO DUELA.**

| cuántos | qué significa | quién cae acá |
|---|---|---|
| **cero** | se dispara solo, en operación normal | *(vacío hoy — el candidato que puse acá se retiró, ver §DEF-4)* |
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
