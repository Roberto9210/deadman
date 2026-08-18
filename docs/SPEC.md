# deadman — especificación (v0.1, 2026-08-18)

**Nombre fijado: `deadman`** (de *dead man's switch*): la máquina se detiene cuando nadie puede dar fe de que
todo está bien. Nombra la garantía central, es término real de ingeniería de seguridad y no arrastra
connotaciones. Decidido 2026-08-18; `failclosed` queda como nombre del principio (§2), no del paquete.

`deadman`: primitivas de seguridad de ejecución para sistemas de trading automatizados, agnósticas de broker y
de estrategia. Este documento fija el contrato ANTES de escribir código. Nada de lo que sigue está
implementado. Base: `reports/safety_kit_extraction_inventory_20260818.md`.

Lector objetivo: alguien que nunca vio el sistema del que esto sale. Donde una decisión no puede
fijarse sin decidir implementación, está marcada **DECISIÓN PENDIENTE** con opciones y costo.

---

## 1. Qué es y qué no es

**Es** una capa mínima que se interpone entre "quiero ejecutar esta orden" y el broker, y garantiza
cinco cosas independientemente de la estrategia que la use:

1. Un **kill switch** externo, fail‑closed, que detiene toda ejecución nueva y toda salida.
2. Un **freno de entradas** persistente que bloquea aperturas de riesgo nuevo — y **nunca** cierres —
   cuando el sistema detecta algo de lo que no puede dar fe.
3. Un **contrato de unidades** que hace imposible ejecutar una cantidad ambigua.
4. Una **secuencia post‑fill honesta**: solo se declara éxito con fill confirmado; sin fill se cancela
   y se relee; estado incierto ⇒ freno + registro, nunca una suposición.
5. Un **ledger firmado y encadenado** donde cada decisión y cada resultado deja rastro verificable.

Más dos utilidades que la experiencia mostró inseparables de lo anterior: **límites diarios**
(pérdida, número de operaciones, nocional) que cuentan las salidas pero no las frenan, y una
**cordura mínima de orden** (broker sano, latencia, spread, símbolo permitido, tamaño disponible) que es
—junto con el kill switch— **lo único que puede frenar una salida**.

**No es** y no contiene: estrategia, señales, feed de mercado, conexión a ningún broker, sizing por
equity, contabilidad de papel, resonancia, régimen, ni bypass de diagnóstico. El usuario entrega un
adaptador (`BrokerPort`) y una intención (`Intent`); el kit devuelve permitido/denegado con motivo y,
si se le pide, ejecuta la secuencia post‑fill.

**Dos matices fijados** (aceptados en el inventario):
- La **asimetría entrada/salida** no es una primitiva: es una POLÍTICA aplicada sobre un **predicado
  inyectable** `is_exposure_reducing(intent, position)`. El default que viaja es
  `spot_long_only_is_exit: intent.side == "sell"` y se declara explícitamente **spot long‑only**. Para
  futuros, cortos o estructuras de dos patas el usuario debe pasar un predicado de posición neta; el
  kit no lo adivina.
- Los **límites diarios entran** al kit porque son genéricos (un contador con rollover). La
  **eligibilidad de estrategia** (resonancia, régimen, "política habilitada", bypass de diagnóstico)
  **queda fuera**: es del sistema que lo usa.

---

## 2. El principio, como contrato: cero defaults plausibles

**Contrato.** Toda función del kit que necesite un dato para decidir sobre riesgo nuevo y no lo tenga
—ausente, ilegible, con tipo incorrecto, stale según su propia regla— **debe denegar con un motivo
que nombre el dato faltante**, no sustituirlo por un valor. Está prohibido dentro del kit:
`x = d.get("k", 1.0)`, `except: pass`, `or 0.5`, "si no hay precio, uso el último", "si no hay
equity, asumo 1". Los tests de conformidad (§6) incluyen para cada dato de entrada un caso "ausente ⇒
denegado con motivo `<DATO>_MISSING`".

**Corolario asimétrico.** El contrato aplica a lo que **aumenta** exposición. Para lo que la reduce, la
regla se invierte: ante duda, **dejar salir** (con el dato conservador si hace falta evaluarlo, y
avisando), porque no evaluar una salida es un riesgo mayor que evaluarla mal. Ejemplo canónico: si no
hay volatilidad para calcular un stop, se evalúa con un umbral conservador declarado y se anota
`FALLBACK`; **nunca** se deja de evaluar.

**El contraejemplo que NO se importa.** En el código de origen, `core/exposure_engine.py:81` hace
`equity = max(equity, 1.0)` cuando no hay balances: sin datos de cuenta, el motor cree tener $1 de
equity, calcula un tamaño como porcentaje de eso, y la orden muere aguas abajo por
`MIN_NOTIONAL_BLOCK` con un motivo que no dice la verdad ("orden demasiado chica") en vez de la causa
("no sé cuánto dinero hay"). El default es plausible —positivo, no rompe nada— y por eso es peor que
un error: convierte un dato ausente en una decisión silenciosa y un diagnóstico falso. Ese patrón
queda fuera del kit por diseño, y el test de conformidad "equity ausente ⇒ `EQUITY_UNKNOWN`, no un
tamaño" existe para que no vuelva.

---

## 2b. Modelo de amenaza del ledger — contra qué protege, decidido

**Decisión (2026-08-18): (c) anclaje externo como garantía principal, (a) cadena de hashes como
mecanismo local; (b) firma queda OPCIONAL vía hook, no en el paquete. Se elimina `pynacl`: cero
dependencias externas.**

Fundamento, sin adornos:

- **Lo que un ledger local puede probar por sí solo es poco.** Un atacante —o un bug— con acceso al
  disco puede reescribir cualquier entrada, recomputar los hashes hasta el tip y reemplazar
  `chain_state.json`; la cadena vuelve a verificar. Una firma Ed25519 con la clave **en el mismo
  disco** no cambia nada: el atacante firma de nuevo. La firma solo agrega algo si la clave vive
  fuera del alcance de quien puede tocar el ledger (HSM, keystore del SO, otra máquina). Eso no es
  el caso de un operador individual con un proceso Python; prometerlo sería exactamente el tipo de
  garantía plausible que el kit prohíbe.
- **Lo que sí protege sin depender de la clave es un tercero con fecha.** Si el par `(seq, hash)` del
  tip se publica periódicamente en un lugar que el operador **no controla** (un remoto git ajeno, un
  servicio de sellado de tiempo RFC 3161, un canal público con timestamps del servidor), entonces
  cualquier alteración de la historia anterior al ancla contradice un registro con fecha de un
  tercero. La garantía es **la fecha del tercero**, no la firma. Es lo que hace que un ledger local
  sea evidencia de verdad, y es el patrón que el sistema de origen ya tenía a medias (espejo del
  checkpoint bajo git en `evidence/`).
- **La cadena de hashes sigue siendo necesaria**: es lo que hace que un ancla de 64 bytes cubra toda
  la historia previa, y lo que detecta corrupción accidental, escritura a medias o un proceso con
  bugs sin necesidad de red. Cubre (a) por completo.
- **Cero dependencias**: `hashlib` + `json` + `os`. Menos superficie que auditar; una razón real
  para adoptar una librería de seguridad. Quien necesite (b) pasa `signer=`/`verifier=` (dos
  callables) y guarda su clave donde quiera; el kit no genera claves ni las custodia.

**Qué previene, explícito:**
| Amenaza | Cadena sola | Cadena + ancla externa |
|---|---|---|
| Corrupción accidental, escritura a medias, bug que reescribe una línea | **Detectada** (`HASH_MISMATCH`/`CHAIN_BROKEN`) | Detectada |
| Borrado o reordenación de entradas | Detectada | Detectada |
| Rotación que rompe continuidad | Detectada (`ROTATION_LINK_BROKEN`) | Detectada |
| Reescritura deliberada de historia con acceso al disco (recompute hasta el tip) | **No detectada** | **Detectada para todo lo anterior al último ancla** (`ANCHOR_MISMATCH`) |
| Reescritura de lo posterior al último ancla | No | No — ventana = intervalo de anclaje; por eso el ancla se fuerza en los eventos que importan |
| Adulteración del propio registro de anclas local | No | El registro local es una copia; la verdad está en el tercero: `verify(anchors=…)` acepta anclas traídas de fuera |
| Pérdida total del disco | No | La existencia y la fecha del ancla sobreviven; el contenido no (para eso está el espejo/git del contenido, fuera del kit) |

**Contrato de anclaje (`§4.5` ampliado):**
- `Anchor = {schema_version, seq, hash, ts_utc, segment, external_ref}`; `external_ref` es lo que
  devuelve el publicador (sha de commit, id de token TSA, URL) — opaco para el kit.
- **Qué se publica exactamente**: el JSON canónico del `Anchor` sin `external_ref` (seq, hash, ts_utc,
  segment). Nada más: sin payloads, sin PII, 64 bytes de hash y un entero.
- **Cuándo**: (1) en **cada** `LEDGER_ROTATED`; (2) inmediatamente después de **cada** entrada de las
  clases `KILL_ENGAGED, KILL_RELEASED, HALT_SET, HALT_CLEARED, UNKNOWN_STATE, CONCURRENT_WRITER_DETECTED`
  (son las que un operador querría probar que ocurrieron cuando ocurrieron); (3) además cada
  `anchor_every_n` entradas o `anchor_every_s` segundos, lo que llegue primero (defaults 100 / 3600;
  el usuario los fija). Si el publicador falla, se anota `ANCHOR_FAILED` y **no** se detiene la
  ejecución: un ledger sin ancla reciente es evidencia más débil, no un sistema inseguro.
- **Cómo lo usa `verify(anchors=None)`**: carga `ledger/anchors.jsonl` (o la lista pasada, que
  puede venir del tercero); para cada ancla localiza `seq` en el segmento que corresponda y exige
  `hash` idéntico; el reporte lleva `anchors_checked`, `latest_anchor_seq` y `code=ANCHOR_MISMATCH`
  (`ok=False`) si alguna no coincide. `chain_complete=True` y `latest_anchor_seq=N` juntos
  significan: "todo hasta N está fechado por un tercero y nada de eso cambió".
- **El publicador es del usuario** (`Callable[[dict], str]`). El kit no habla con la red.
- **Qué cuenta como tercero — la trampa más probable al implementar el publicador:** un remoto git donde
  el operador (o cualquiera con su credencial) puede hacer `force-push` **NO es un tercero
  independiente**: puede reescribir la historia y la garantía se evapora sin aviso. Un repo propio en
  GitHub con la rama por defecto sin protección es exactamente eso. **Sí califican**: (1) una rama
  **protegida** con force‑push y borrado prohibidos **también para el owner/admin** (y, si el proveedor
  lo permite, con el commit firmado y el reflog retenido); (2) una **autoridad de sellado de tiempo
  RFC 3161** (el token lleva la fecha del TSA sobre el hash); (3) un **servicio append‑only de
  terceros** con timestamps del servidor que el operador no administra. La calidad de la evidencia es la
  del eslabón más débil: el ancla vale lo que valga la inmutabilidad del sitio donde se publicó.
- **`ANCHOR_FAILED` sostenido no es aceptable en silencio.** Cada fallo se anota; y cuando se alcanza
  **`stale_after_failures` fallos consecutivos (default 3) o `stale_after_s` segundos sin un ancla
  exitosa (default 4·`anchor_every_s`)**, el ledger escribe una entrada propia **`ANCHOR_STALE`** con
  `{consecutive_failures, seconds_since_last_ok, last_ok_seq, last_error}` y crea un **marcador visible**
  `root/anchor_stale.flag` (texto legible, mtime = cuándo). No es un halt de ejecución —la operación
  no se vuelve insegura por falta de ancla— pero es imposible de ignorar: aparece en el ledger, en el
  disco y en el log a nivel CRITICAL, y `verify()` lo reporta en `detail` mientras el marcador exista.
  El primer ancla exitosa posterior borra el marcador y anota `ANCHOR_RECOVERED`. Detectar sin actuar
  no está permitido en código nuevo.

## 3. Por qué existe cada primitiva

Cada pieza responde a un fallo real observado en el sistema de origen. Se citan como patrones.

| Primitiva | El fallo que la motivó |
|---|---|
| **Kill switch externo, fail‑closed** | El sentinel de parada dependía de un servicio que llevaba meses sin correr; un interruptor que necesita otro proceso vivo no es un interruptor. Ahora la mera existencia de un archivo detiene, y **cualquier error al comprobarlo también detiene**. |
| **Freno de entradas persistente (no de sesión)** | Un estado de orden desconocido en un ciclo se olvidaba en el siguiente. El freno vive en disco, sobrevive reinicios, y solo lo limpia una reconciliación que ve el libro vacío o un humano tras investigar. Bloquea aperturas, nunca cierres. |
| **Asimetría entrada/salida como política explícita** | Los mismos frenos (límite diario, resonancia, política deshabilitada) atrapaban posiciones abiertas: la salida "no era elegible". Y **el stop‑loss de febrero manejaba salidas de agosto**: los umbrales de salida salían de un banco de parámetros congelado meses antes. Regla: nada que no sea el kill switch o la cordura de la orden frena una salida; los umbrales de salida se calculan con datos del día o con un fallback conservador declarado. |
| **Contrato de unidades** | La cantidad viajaba en un campo `amount` sin decir si eran dólares o unidades de base; el vendedor "de toda la posición" vendía un importe en USD convertido a un precio de otro momento. Ahora `units ∈ {USD, BASE, CONTRACTS}` es obligatorio y su ausencia rechaza ruidoso. |
| **Post‑fill honesto** | El adapter marcaba éxito al enviar, no al llenar; un timeout se contaba como trade; una excepción al confirmar dejaba una orden viva sin dueño. Ahora: éxito = fill confirmado; sin fill ⇒ cancelar, releer, `NO_FILL_CANCELED` (no es trade); no se puede confirmar ⇒ estado **desconocido** ⇒ freno + registro. |
| **Reconciliación de órdenes** | Al arrancar, nadie preguntaba al broker qué había quedado abierto. Órdenes que aumentan exposición y nadie recuerda se cancelan; las que la reducen se dejan y se reportan. |
| **Ledger encadenado y anclado** | Los registros se podían editar, y de hecho una parte de la historia se resumía con datos posteriores. Hash‑chain + escritura atómica + ancla externa con fecha de un tercero (§2b): se puede probar qué se decidió, cuándo, y que nadie lo cambió después — hasta el último ancla. |
| **Cordura de orden separada de la eligibilidad** | Un chequeo de frescura del feed leía una clave que **ningún productor escribía**, así que siempre decía NOMINAL: un chequeo que existe no es un chequeo que corre. La cordura del kit solo usa datos que el propio llamador entrega en la llamada; si faltan, deniega. |
| **Cero defaults plausibles (contrato §2)** | Una clave de política de capital que no existía en el archivo se leía con default 100 ⇒ **el tope de riesgo por operación era $2 fijos** durante meses, con cualquier balance real. Y un RSI que nadie producía valía 50 siempre. Un default plausible es un bug que no falla. |
| **Límites diarios que cuentan salidas pero no las frenan** | El límite de operaciones diarias bloqueó cierres. Ahora los fills de salida **cuentan** (para que el número sea verdad) pero **no se chequean** contra el tope. |
| **Nada de gates decorativos** | Un gate emitía una acción (`ema_state`) que ningún consumidor leía y ningún productor alimentaba: costo de mantenimiento, cero protección. Regla del kit: cada comprobación tiene productor y consumidor identificados en el test que la cubre; si no, no entra. |
| **Resultado = neto, nunca bruto** | La contabilidad de una prueba de papel reportaba el ingreso bruto (+$0,29) como "resultado" mientras el neto de comisiones era negativo (−$9 / −$18). El ledger del kit registra fills con comisiones y el `ExecResult` lleva `fees_paid`; "PnL" sin comisiones no existe como campo. |
| **Reloj inyectable** | Un `now()` no reproducible hizo imposible reproducir un rollover diario en test y una ventana de outcome. Todo lo que dependa del tiempo recibe el reloj. |

---

## 4. La API (10 nombres + 2 predicados)

Pseudocódigo con firmas completas. Tipos: `Verdict(allowed: bool, reason: str, code: str)`; `code` es
un identificador estable en MAYÚSCULAS (`KILL_SWITCH_ACTIVE`, `ENTRY_HALT_ACTIVE`, `INTENT_UNITS_INVALID`,
`DAILY_LOSS_LIMIT`, `SPREAD_TOO_WIDE`, …). Toda función que deniega devuelve `code` + `reason` humano.

```
# ---------- 0. rutas ----------
class Paths:
    def __init__(self, root: PathLike)                     # ver §5.1
    kill_sentinel: Path      # root/"kill_switch.enabled"
    entry_halt:    Path      # root/"entry_halt.json"
    daily_stats:   Path      # root/"daily_stats.json"
    ledger_dir:    Path      # root/"ledger"/  -> ledger.jsonl, chain_state.json, chain_state.lock, keys/

# ---------- 1. kill switch ----------
class KillSwitch:
    def __init__(self, paths: Paths, ledger: SignedLedger | None = None)
    def check(self) -> Verdict            # bloqueado si el sentinel EXISTE (os.path.exists); el contenido NUNCA se lee ni se parsea
                                          # cualquier OSError al comprobar => bloqueado con code KILL_SWITCH_CHECK_FAILED
    def engage(self, reason: str) -> None # crea sentinel (idempotente) y anota en ledger si se le pasó uno
    def release(self, note: str) -> None  # borra el sentinel; el JSON no se toca (lo limpia un humano)

# ---------- 2. freno de entradas ----------
@dataclass(frozen=True)
class HaltRecord: active: bool; reason: str; source: str; ts_utc: str; auto_clear: bool; schema_version: int
class EntryHalt:
    def __init__(self, paths: Paths, clock: Clock, logger: Logger | None = None)
    def active(self) -> HaltRecord | None       # archivo ilegible => HaltRecord(active=True, reason="ENTRY_HALT_FILE_UNREADABLE: …")
    def set(self, reason: str, source: str, auto_clear: bool = False) -> HaltRecord
                                                # auto_clear resultante = auto_clear AND (no había halt o el existente era auto_clear)
    def clear(self, note: str, only_auto_clear: bool = False) -> bool   # True si limpió

# ---------- 3. intención y unidades ----------
@dataclass(frozen=True)
class Intent:
    symbol: str
    side: Literal["buy", "sell"]
    units: Literal["USD", "BASE", "CONTRACTS"]
    amount: float
    kind: Literal["ENTRY", "EXIT", "RISK_EXIT", "ROLL"]
    client_id: str                                  # idempotencia; lo genera el llamador
    meta: Mapping[str, Any] = {}                    # opaco para el kit; viaja al ledger
@dataclass(frozen=True)
class Resolved: amount_usd: float; amount_base: float; amount_contracts: float | None
def resolve_units(intent: Intent, price: float, contract_size: float | None = None) -> Resolved
    # levanta IntentUnitsInvalid (units fuera del conjunto / ausente), IntentAmountInvalid (amount<=0 | NaN),
    # PriceInvalid (price<=0 | NaN), ContractSizeMissing (units=CONTRACTS sin contract_size). Nunca interpreta.

# ---------- 4. asimetría: predicado + política ----------
@dataclass(frozen=True)
class PositionSnapshot: symbol: str; net_base: float; ts_utc: str      # >0 largo, <0 corto
ExposurePredicate = Callable[[Intent, PositionSnapshot | None], bool]
def spot_long_only_is_exit(intent, position) -> bool          # == (intent.side == "sell"); DEFAULT, declarado spot long-only
def net_position_is_exit(intent, position) -> bool            # True si |net + delta(intent)| < |net|; position None => False (fail-closed hacia "es entrada")

@dataclass(frozen=True)
class Limits: max_trades_per_day: int | None; max_daily_loss_usd: float | None; max_notional_usd_per_order: float | None
              worst_case_fee_bps: float | None   # fee desconocido en un fill: se carga a este peor caso; None => el día queda fees_unverified y las entradas se deniegan
class DailyLimits:
    def __init__(self, paths: Paths, limits: Limits, is_exit: ExposurePredicate, clock: Clock, ident: WriterIdentity, ledger: Ledger | None = None)
    def check(self, intent: Intent, resolved: Resolved, position: PositionSnapshot | None) -> Verdict
                                                # 1º: si is_exit(intent, position): Verdict.allow("EXIT_BYPASSES_DAILY_LIMITS") SIN leer el archivo
                                                # 2º: stats ilegible => Verdict.deny("DAILY_STATS_UNREADABLE") (solo entradas llegan acá)
                                                # 3º: día del archivo > hoy (reloj hacia atrás) => deny("DAILY_STATS_CLOCK_BACKWARDS"), nada se resetea
                                                # 4º: clave ausente => deny("DAILY_STATS_KEY_MISSING") - jamás un default
                                                # 5º: fees_unverified => deny("DAILY_FEES_UNVERIFIED"); luego notional/trades/pérdida NETA
    def record_fill(self, intent: Intent, filled_usd: float, fee_usd: float | None) -> DailyStats   # entradas Y salidas cuentan; fee None nunca es 0
    def record_pnl(self, gross_realized_pnl_usd: float) -> DailyStats                                # neto = gross - fees acumuladas por fill
    def stats(self) -> DailyStats | None                                # día UTC actual (rollover al leer, anotado como DAILY_STATS_RESET); None si ilegible

class OrderSanity:
    def __init__(self, allowed_symbols: frozenset[str], max_latency_ms: float, max_spread_bps: float,
                 min_notional_usd: float | None = None, max_notional_usd: float | None = None,   # OPCIONALES declarados: None = chequeo omitido (y dicho en el veredicto)
                 max_ref_deviation_bps: float | None = None)                                     # si se configura, ref_price es OBLIGATORIO en check()
    def check(self, intent: Intent, resolved: Resolved, *,
              broker_status: str, latency_ms: float, bid: float, ask: float,
              size_available: float | None, is_exit: bool, ref_price: float | None = None) -> Verdict
              # aplica a entradas Y salidas; cualquier argumento None/NaN => denegado <ARG>_MISSING
              # size_available: salida => base disponible vs amount_base; entrada => quote disponible vs amount_usd
              # bajo min_notional => NOTIONAL_BELOW_MIN: se DENIEGA, jamás se agranda la orden para llegar al mínimo
    def quantize(self, intent, resolved, *, amount_step: float, price: float) -> QuantizeResult
              # floor al step del venue SIEMPRE (entradas y salidas: nunca más de lo pedido); queda 0 => AMOUNT_BELOW_STEP
              # size_available: para BASE/CONTRACTS en salida = base disponible; para USD en entrada = quote disponible

# ---------- 5. ledger encadenado + anclado (§2b) ----------
@dataclass(frozen=True)
class Entry: seq: int; ts_utc: str; kind: str; actor: str; payload: Mapping; prev_hash: str; hash: str; schema_version: int; sig: str | None = None
@dataclass(frozen=True)
class Anchor: schema_version: int; seq: int; hash: str; ts_utc: str; segment: str; external_ref: str
class Ledger:
    def __init__(self, paths: Paths, clock: Clock,
                 publisher: Callable[[dict], str] | None = None,     # publica el ancla fuera; devuelve external_ref
                 anchor_every_n: int = 100, anchor_every_s: float = 3600.0,
                 stale_after_failures: int = 3, stale_after_s: float | None = None,   # None => 4*anchor_every_s
                 signer: Callable[[bytes], bytes] | None = None,     # OPCIONAL (b): firma el hash; la clave es del usuario
                 verifier: Callable[[bytes, bytes], bool] | None = None,
                 on_append: Callable[[Entry], None] | None = None)
    def append(self, kind: str, payload: Mapping, actor: str = "user") -> Entry   # falla ruidoso (LedgerWriteError); el llamador decide halt
    def last_hash(self) -> str
    def rotate(self, actor: str = "user") -> Entry                                # ver §5.5
    def anchor(self, reason: str = "manual") -> Anchor | None                     # publica el tip ahora; None si no hay publisher
    def verify(self, from_seq: int | None = None, anchors: list[Anchor] | None = None) -> VerifyReport

# ---------- 6. broker y ejecutor ----------
@dataclass(frozen=True)
class Order: id: str; symbol: str; side: str; status: Literal["open","closed","canceled","unknown"]
             filled: float; average: float | None; fee_usd: float | None; raw: Mapping
class BrokerPort(Protocol):                     # ver §5.4
    def create_order(self, symbol: str, side: str, amount_base: float, order_type: str,
                     price: float | None, client_id: str) -> Order
    def fetch_order(self, order_id: str, symbol: str) -> Order
    def cancel_order(self, order_id: str, symbol: str) -> Order
    def fetch_open_orders(self, symbol: str) -> list[Order]

@dataclass(frozen=True)
class ExecResult:
    status: Literal["FILLED","PARTIAL","NO_FILL_CANCELED","DENIED","UNKNOWN"]
    code: str; reason: str; order_id: str | None; filled_base: float; avg_price: float | None
    fees_usd: float | None; ledger_seq: int | None

class HonestExecutor:
    def __init__(self, broker: BrokerPort, kill: KillSwitch, halt: EntryHalt, limits: DailyLimits,
                 sanity: OrderSanity, ledger: SignedLedger, is_exit: ExposurePredicate, clock: Clock,
                 fill_timeout_s: float, poll_interval_s: float, logger: Logger | None = None)
    def execute(self, intent: Intent, price: float, *, broker_status: str, latency_ms: float,
                bid: float, ask: float, size_available: float | None,
                position: PositionSnapshot | None = None, contract_size: float | None = None) -> ExecResult
    def reconcile(self, symbols: Iterable[str], known_order_ids: Set[str],
                  position_of: Callable[[str], PositionSnapshot | None]) -> ReconcileReport
```

**Decisiones fail‑closed del ejecutor donde la spec callaba (2026‑08‑18, implementadas):**
- `execute()` antes de `startup()` ⇒ `DENIED/STARTUP_RECONCILE_REQUIRED`. La reconciliación corre ANTES de aceptar intents.
- **Write‑ahead**: `ORDER_SENT{stage:"write_ahead"}` con `client_order_id` **determinista** derivado del intent se
  persiste ANTES de tocar la red. Un `client_order_id` no terminal en el ledger ⇒ `DENIED/DUPLICATE_IN_FLIGHT`:
  reintentar sin estado terminal confirmado es doble exposición; la idempotencia va por `client_order_id`.
- **Timeout en el envío** (`OrderMaybeSent`) ⇒ `ORDER_SENT{stage:"sent_no_ack"}` y la orden se **presume VIVA**;
  se resuelve por `fetch_order_by_client_id` (G9): encontrada ⇒ sigue la máquina; `None` autoritativo ⇒
  `INTENT_DENIED/BROKER_NEVER_ACCEPTED`; error ⇒ `UNKNOWN_STATE`. Una excepción que NO sea `OrderMaybeSent`
  ni `BrokerRejected` no goza de G9: `None` ahí es `UNKNOWN_STATE`.
- Fill duplicado (mismo id en `raw["fills"]`) se cuenta **una vez** y queda anotado en el `FILL`
  (`duplicate_fill_ids_ignored`); `filled > requested` ⇒ `UNKNOWN_STATE`. Fee `None` viaja como `None` a
  `DailyLimits` (peor caso o día no verificable), nunca 0.
- `startup()`: cada `client_order_id` no terminal se consulta por client id y se resuelve uno a uno
  (`never_sent`, `broker_never_accepted`, cancel+re‑read para entradas abiertas, se deja una salida abierta);
  toda orden abierta en el broker que el ledger no conoce ⇒ `UNKNOWN_STATE` + halt (y cancel si añade exposición).
  Cada discrepancia es una entrada del ledger; algo encontrado ⇒ halt `auto_clear`; nada y sin errores ⇒ se
  limpia solo el halt `auto_clear`. Un halt es **pegajoso**: tras el primer `UNKNOWN_STATE` ninguna entrada
  posterior llega al broker (probado en G9).

**Orden de comprobaciones de `execute()`** (fijo; cada paso registra en el ledger su veredicto):

1. `kill.check()` — aplica a todo. Bloqueado ⇒ `DENIED/KILL_SWITCH_*`.
2. `exit = is_exit(intent, position)`.
3. Si `not exit`: `halt.active()` ⇒ `DENIED/ENTRY_HALT_ACTIVE`.
4. `resolve_units(intent, price, contract_size)` ⇒ excepción ⇒ `DENIED/INTENT_*`.
5. Si `not exit`: `limits.check(...)` ⇒ `DENIED/DAILY_*`.
6. `sanity.check(...)` — aplica a todo ⇒ `DENIED/<SANITY_CODE>`.
7. `ledger.append("ORDER_SENT", …)`; si falla ⇒ **no se envía**, `DENIED/LEDGER_WRITE_FAILED` y `halt.set(auto_clear=False)`.
8. `broker.create_order(...)`; excepción ⇒ `DENIED/BROKER_REJECTED` (nada que reconciliar: no hay id) —
   salvo que la excepción llegue **después** de tener un id ⇒ paso 10.
9. Poll `fetch_order` cada `poll_interval_s` hasta `fill_timeout_s`:
   - `closed` con `filled>0` ⇒ `FILLED` (o `PARTIAL` si `filled < pedido`; se reporta lo que hay, jamás se
     redondea hacia arriba); `limits.record_fill`; ledger `FILL`.
   - timeout con `open` ⇒ `cancel_order` ⇒ releer ⇒ `canceled` y `filled==0` ⇒ `NO_FILL_CANCELED` (no es
     trade); `canceled` con `filled>0` ⇒ `PARTIAL`.
10. Cualquier situación no cubierta por 9 (excepción en `fetch_order`/`cancel_order`, cancel no confirmado
    en la relectura, `filled` incoherente, `status="unknown"`) ⇒ **estado desconocido** (§5.3):
    `ledger UNKNOWN_STATE`, `halt.set(auto_clear=True)`, `UNKNOWN`. Nunca se declara éxito ni fracaso.

**Orden de `reconcile()`**: por símbolo, `fetch_open_orders`; para cada orden abierta cuyo `id` no esté en
`known_order_ids`: si `is_exit(Intent(side=orden.side,...), position_of(sym))` es False ⇒ cancelar (es
riesgo nuevo sin dueño) y anotar; si True ⇒ dejar y anotar. Si se encontró algo ⇒ `halt.set(auto_clear=True)`;
si no se encontró nada en ningún símbolo y hay un halt `auto_clear` ⇒ `halt.clear(only_auto_clear=True)`.
Nunca levanta; los errores por símbolo van al reporte y **cuentan como "algo encontrado"** (no se limpia un
halt con información incompleta).

---

## 5. Contratos que hay que fijar

### 5.1 `Paths(root)`
Un único `root` explícito, absoluto o relativo **al cwd en el momento de construir `Paths`** (se resuelve
con `Path(root).resolve()` una vez y se congela). Ninguna primitiva usa `os.getcwd()` ni `__file__` después.
Todos los archivos de estado cuelgan de `root`. `Paths` crea `root` y `ledger_dir` si no existen; si no
puede (permisos), levanta en construcción — el sistema no arranca sin poder escribir su estado.

### 5.2 Esquemas de los archivos de estado (todos JSON UTF‑8, con `schema_version: 1`)
| Archivo | Campos | Semántica |
|---|---|---|
| `kill_switch.enabled` | (sin contenido; puede tener texto libre para humanos) | **Su existencia es la señal. El kit no abre el archivo.** |
| (no hay `kill_state.json`) | — | **Decisión A (2026-08-18): solo sentinel.** El kill switch **no parsea nada**: cuenta la EXISTENCIA del archivo, nunca su contenido. Es la pieza que tiene que funcionar cuando todo lo demás falló, y un parse (JSON, YAML, encoding, permisos de lectura) es un modo de falla más. `engage(reason)` escribe la razón en el ledger si hay uno; si el ledger falla, el sentinel se crea igual (el sentinel manda). |
| `entry_halt.json` | `{schema_version, active: true, reason: str(<=300), source: str, ts_utc, auto_clear: bool, writer_pid, writer_started_at, write_seq}` | Presencia con `active:true` = halt. Ilegible = halt. Escritura atómica (tmp + replace). `clear()` borra el archivo. |
| `daily_stats.json` | `{schema_version, day_utc: "YYYY-MM-DD", trades: int, filled_usd: float, gross_pnl_usd: float, fees_usd: float, fees_estimated: int, fees_unverified: bool, updated_ts_utc, writer_pid, writer_started_at, write_seq}` (neto = gross − fees) | Al leer, si `day_utc != clock.today_utc()` ⇒ se reinicia en memoria y se persiste. Ilegible ⇒ **Decisión B (2026-08-18): fail‑closed SOLO para entradas**: `check()` deniega toda entrada con `DAILY_STATS_UNREADABLE` y lo anota en el ledger; **una salida pasa igual** (`is_exit` ⇒ `EXIT_BYPASSES_DAILY_LIMITS` se evalúa ANTES de leer el archivo, así que un archivo corrupto no puede atrapar una posición). No se reinicia solo: lo repara un humano (borrar el archivo ⇒ nuevo día limpio) y queda `DAILY_STATS_RESET` en el ledger. |
| `ledger/chain_state.json` | `{schema_version, last_seq: int, last_hash: str}` | Solo el tip. Reemplazo atómico. Ver 5.5. |
| `ledger/ledger.jsonl` | una `Entry` por línea | Append‑only. |
| `ledger/anchors.jsonl` | un `Anchor` por línea | Copia local de lo publicado; la verdad está en el tercero (`verify(anchors=…)` acepta la lista externa). |
| `anchor_stale.flag` | texto libre para humanos | Marcador visible de anclaje caído (§2b). Existe ⇔ hay `ANCHOR_STALE` sin `ANCHOR_RECOVERED` posterior. |
| (no hay `keys/`) | — | El kit no genera ni custodia claves (§2b). Quien firme, pasa `signer`/`verifier`. |

### 5.3 "Estado desconocido" de una orden — definición exacta
Una orden está en **estado desconocido** cuando el kit **tiene o pudo tener un `order_id` aceptado por el
broker** y se cumple cualquiera de:
1. `create_order` levantó excepción **después** de que el broker devolviera un id (o el adaptador no puede
   garantizar que no lo hizo — ver 5.4, garantía G1).
2. `fetch_order` levantó excepción o devolvió `status="unknown"` en el poll o en la relectura.
3. `cancel_order` levantó excepción, o tras cancelar la relectura no muestra `canceled` ni `closed`.
4. `filled` es negativo, mayor que lo pedido más tolerancia de redondeo del broker, o `NaN`.
5. `status="closed"` con `filled==0` y sin motivo (rechazo silencioso).
Consecuencia obligatoria: ledger `UNKNOWN_STATE` con todo lo que se sabe, `halt.set(auto_clear=True)`,
`ExecResult.UNKNOWN`. Sale del desconocido **solo** `reconcile()` (libro vacío ⇒ limpia el halt) o un humano.

### 5.4 `BrokerPort` — los callables y lo que garantiza cada uno
| Método | Garantías que el adaptador DEBE cumplir |
|---|---|
| `create_order(symbol, side, amount_base, order_type, price, client_id) -> Order` | **G1**: o devuelve un `Order` con `id`, o levanta ANTES de que el broker haya podido aceptar la orden; si no puede distinguir (timeout de red tras enviar), levanta `OrderMaybeSent(client_id)` — el kit lo trata como desconocido. **G2**: `client_id` se envía al broker si este soporta idempotencia; si no, el adaptador lo documenta. **G3**: `amount_base` está en unidades de base (el kit ya resolvió unidades). |
| `fetch_order(order_id, symbol) -> Order` | **G4**: `status` es uno de los cuatro literales; cualquier estado del broker no mapeable ⇒ `"unknown"` (nunca se inventa `closed`). **G5**: `filled` en base; `average` `None` si no hay fills; `fee_usd` `None` si el broker no lo reporta (no 0). |
| `cancel_order(order_id, symbol) -> Order` | **G6**: devuelve el estado **tras** el intento; cancelar una orden ya llena no es error (devuelve `closed`). **G7**: si el broker rechaza el cancel por "ya no existe", devuelve `status="unknown"`, no levanta. |
| `fetch_open_orders(symbol) -> list[Order]` | **G8**: lista completa para el símbolo o excepción; nunca una lista parcial silenciosa. |
| `fetch_order_by_client_id(client_id, symbol) -> Order | None` | **G9** (añadida en el tramo del ejecutor): devuelve la orden o `None`; **`None` es una afirmación AUTORITATIVA de que el broker nunca aceptó una orden con ese client id**. Un adaptador que no pueda afirmarlo debe levantar excepción. Es lo que hace sobrevivible un timeout de envío sin doble exposición: el ejecutor no reintenta a ciegas, consulta por client id. |
El adaptador **no** hace reintentos silenciosos: si reintenta, lo anota en `raw` y respeta G1. Un adaptador es
conforme si pasa las pruebas de §6 con estas garantías. (El primer adaptador previsto es ccxt/Kraken spot; los
`FakeExchange`/`FakeRouter` de los tests actuales son la referencia de forma.)

### 5.5 Catálogo de `kind` del ledger y rotación
Kinds mínimos: `ANCHOR_PUBLISHED, ANCHOR_FAILED, ANCHOR_STALE, ANCHOR_RECOVERED, KILL_ENGAGED, KILL_RELEASED, HALT_SET, HALT_CLEARED, INTENT_DENIED, ORDER_SENT,
FILL, PARTIAL_FILL, NO_FILL_CANCELED, UNKNOWN_STATE, RECONCILE_REPORT, DAILY_STATS_RESET, LEDGER_ROTATED,
CONCURRENT_WRITER_DETECTED, USER_NOTE`. Payload mínimo por kind se fija en el test correspondiente. Todo `payload` lleva `client_id` si
existe.
**Rotación — Decisión C (2026-08-18): rotación anclada, con enlace obligatorio.** El sistema de origen rotó
el archivo y dejó un segmento cuya primera fila no encadena a génesis; `verify()` desde génesis fallaba. La
rotación es el punto donde se puede falsificar historia; sin el enlace, se cae la única garantía que
justifica un ledger firmado. Por eso:

- Los segmentos se llaman `ledger.jsonl` (activo) y `ledger.<NNNN>.jsonl` (cerrados, NNNN creciente).
- `rotate()` (1) toma el lock, (2) lee el tip `(last_seq, last_hash)`, (3) renombra `ledger.jsonl` →
  `ledger.<NNNN>.jsonl`, (4) escribe como **primera** entrada del nuevo `ledger.jsonl` una `Entry` normal
  (firmada, `prev_hash` = **el hash de la última entrada del archivo anterior**) con:

      kind    = "LEDGER_ROTATED"
      payload = {
        "prev_segment":   "ledger.<NNNN>.jsonl",   # nombre del archivo cerrado
        "prev_last_seq":  <int>,                   # seq de su última entrada
        "prev_last_hash": "<hex>",                 # hash de su última entrada  (== prev_hash de esta Entry)
        "prev_first_seq": <int>,                   # seq de su primera entrada
        "prev_sha256":    "<hex>"                  # sha256 del archivo cerrado completo, tal como quedó
      }

- `verify(from_seq=None)`: recorre el segmento activo; al encontrar un `LEDGER_ROTATED`, si el
  `prev_segment` existe lo abre, verifica que su última entrada tenga exactamente `prev_last_seq`/`prev_last_hash`
  y que `sha256(archivo) == prev_sha256`, y continúa hacia atrás hasta génesis o hasta el primer segmento
  ausente. Si un segmento ausente impide llegar a génesis, el reporte dice `verified_from_seq = <seq del
  ancla más antiguo alcanzado>` y `chain_complete = False` — **nunca "OK" a secas**. Un `LEDGER_ROTATED` cuyo
  `prev_last_hash` no coincida con su propio `prev_hash`, o cuyo segmento anterior no encaje, es
  `VerifyReport.ok = False` con `code = ROTATION_LINK_BROKEN`.

### 5.6 Reloj UTC inyectable
`Clock` es un objeto con `now_utc() -> datetime(tz=UTC)` y `today_utc() -> "YYYY-MM-DD"`. Todas las
primitivas lo reciben en el constructor; ninguna llama a `datetime.now()`/`time.time()` directamente. Por qué:
el rollover diario, el timeout de fill, la edad de un halt y la ventana de un outcome son irreproducibles en
test sin controlar el tiempo, y un `now()` implícito ya produjo un caso no reproducible en el sistema de
origen. El reloj de producción es trivial; el de test avanza a mano.

### 5.7 Un solo escritor por archivo de estado
**Decisión D (2026-08-18): sin locks de SO en v0.1 para `entry_halt.json` y `daily_stats.json`, pero
"un escritor" NO se da por supuesto: se DETECTA.** El sistema de origen ya violó ese supuesto una vez (dos
adaptadores arrancados a la vez); documentarlo no alcanza. Diseño:

- Todo archivo de estado JSON lleva un **sello de escritor**: `writer_pid: int`, `writer_started_at: str`
  (ISO UTC del arranque del proceso escritor, no de la escritura) y `write_seq: int` (monótono por archivo).
- Cada escritura es atómica (tmp + `os.replace`) y sigue el ciclo **leer → decidir → escribir**. Antes de
  reemplazar, el escritor relee el archivo actual; si el sello `(writer_pid, writer_started_at, write_seq)`
  **no es el que leyó al empezar el ciclo** (otro proceso escribió en medio) ⇒ **no escribe**, levanta
  `ConcurrentWriterDetected` y el llamador (el kit mismo) hace `halt.set("CONCURRENT_WRITER_DETECTED: …",
  source=<módulo>, auto_clear=False)` y lo anota en el ledger. Si el conflicto es en el propio
  `entry_halt.json`, el halt se escribe **forzado** (última escritura gana, con el motivo) — un halt de más es
  aceptable, uno de menos no.
- El sello se compara también al **arrancar**: si `entry_halt.json`/`daily_stats.json` tienen un
  `writer_pid` distinto al propio y ese pid **sigue vivo**, es `CONCURRENT_WRITER_DETECTED` al inicio (el
  guard de instancia única del sistema de origen, pero dentro del kit y por archivo).
- No previene la carrera; la hace ruidosa. Es el contrato de toda la librería.
- El **ledger** sí usa lock de SO (`chain_state.lock`, `msvcrt`/`fcntl`) porque es multi‑proceso por diseño.
- El sentinel del kill switch no tiene sello: no tiene contenido.

---

## 6. Qué pruebas definen la conformidad

Un adaptador (`BrokerPort`) y una integración son **conformes** si pasan estas pruebas, ejecutadas con
`Paths(tempdir)`, reloj de test y un broker falso con las garantías de 5.4. Cada grupo conserva el patrón del
sistema de origen: **cada regla con su par** (caso que debe pasar / caso que debe fallar), y para las
comprobaciones de datos, el caso "ausente ⇒ denegado con código".

| Grupo | Origen (aserciones que viajan, reescritas) | Qué fija |
|---|---|---|
| **G1 Kill switch** (nuevo, ~9) | — | sentinel presente ⇒ todo denegado (entrada y salida); **sentinel con contenido basura/binario/ilegible ⇒ igual bloqueado sin excepción (no se abre)**; OSError al comprobar ⇒ `KILL_SWITCH_CHECK_FAILED`; ausente ⇒ pasa; `engage/release` idempotentes y anotados. |
| **G2 Entry halt** (gate, ~10) | exit_tanda gate | set ⇒ entrada denegada `ENTRY_HALT_ACTIVE` y salida pasa; archivo ilegible ⇒ halt; `auto_clear` solo si el existente lo era; `clear(only_auto_clear)` no borra un halt manual. |
| **G3 Unidades** (16) | exit_tanda units | `USD`/`BASE`/`CONTRACTS` resuelven; ausente/inválido/amount≤0/price≤0 ⇒ excepción con el intent en el mensaje; salida en `BASE` vende exactamente lo pedido; nunca se infiere. |
| **G4 Límites diarios** (gate, ~10) | exit_tanda gate | pérdida diaria / nº de trades / nocional bloquean entrada y **no** salida; los fills de salida incrementan contadores; rollover UTC con reloj inyectado; **stats ilegible ⇒ entrada denegada `DAILY_STATS_UNREADABLE` y salida pasa sin leer el archivo**. |
| **G5 Cordura de orden** (fix5 + gate, ~12) | cleanup fix5, exit gate | broker no `connected` / latencia > máx / spread > máx / símbolo no permitido / tamaño insuficiente ⇒ denegado **también para salidas**; cualquier input `None`/`NaN` ⇒ `<ARG>_MISSING` — nunca un default. |
| **G6 Post‑fill honesto** (24) | exit_tanda postfill | fill total ⇒ `FILLED` con `filled/avg/fee`; parcial ⇒ `PARTIAL` con lo real; timeout ⇒ cancel + relectura ⇒ `NO_FILL_CANCELED` y **no** cuenta como trade; excepción en confirm ⇒ `UNKNOWN` + halt auto_clear + ledger; cancel que falla ⇒ `UNKNOWN`; cancel de orden ya llena ⇒ `FILLED`. |
| **G7 Detectar ⇒ actuar** (6) | exit_tanda detect | ledger falla al escribir `ORDER_SENT` ⇒ no se envía + halt manual; reconcile encuentra abierto desconocido que aumenta exposición ⇒ cancelado + halt auto; que reduce ⇒ dejado + reporte; libro vacío ⇒ limpia solo halt auto; error por símbolo ⇒ no limpia. |
| **G8 Snapshot de cuenta** (fix3, ~8) | cleanup fix3 | un dato de cuenta con edad > máx o status ≠ sincronizado se trata como **ausente** (denegar entrada con `ACCOUNT_SNAPSHOT_STALE`), nunca como el último valor bueno; salidas no dependen de él. |
| **G9 Todo en llamas** (13 + propiedades) | exit_tanda fire | **implementado como propiedades sobre el ledger**: FakeBroker fallando de todas las formas a la vez + proceso real matado a mitad de envío y rearrancado con `startup()`: ningún fill perdido, ninguna orden enviada dos veces, cada estado final explicable leyendo solo el ledger, cierre en halt explícito; con halt + límites agotados + stats corruptas + kill switch **apagado**, una salida pasa; con kill switch encendido, no; con spread fuera de rango, tampoco. Es el test de la asimetría completa. |
| **G10 Cero defaults** (nuevo, ~10) | — | por cada dato de entrada del ejecutor, el caso ausente ⇒ `DENIED/<DATO>_MISSING`; **equity/balance ausente nunca produce un tamaño** (el contraejemplo de §2 como test). |
| **G11 Ledger** (nuevo, ~18) | — | append encadena; `verify()` detecta una línea alterada, borrada o reordenada; **reescritura completa con recompute hasta el tip pasa la cadena pero cae por `ANCHOR_MISMATCH` cuando hay un ancla anterior; anclaje forzado tras `HALT_SET`/`KILL_ENGAGED`/`UNKNOWN_STATE`; publisher que falla ⇒ `ANCHOR_FAILED` y la ejecución sigue; **fallos sostenidos ⇒ `ANCHOR_STALE` + `anchor_stale.flag`, y el primer éxito posterior ⇒ `ANCHOR_RECOVERED` + marcador borrado**; `signer/verifier` opcionales funcionan con cualquier par de callables**; escritura concurrente desde dos procesos no rompe la cadena; **rotación: `LEDGER_ROTATED` con `prev_last_hash == prev_hash`, `verify()` cruza al segmento anterior y prueba continuidad; segmento anterior alterado ⇒ `ROTATION_LINK_BROKEN`; segmento ausente ⇒ `chain_complete=False`, nunca OK a secas**. |
| **G13 Escritor concurrente** (nuevo, ~8) | — | dos escritores simulados sobre `entry_halt.json`/`daily_stats.json`: el segundo detecta el sello cambiado ⇒ no escribe, `ConcurrentWriterDetected`, halt `CONCURRENT_WRITER_DETECTED` manual y ledger; conflicto sobre el propio `entry_halt.json` ⇒ el halt se escribe forzado; al arrancar con `writer_pid` ajeno vivo ⇒ detectado; con pid muerto ⇒ se toma la escritura y se anota. |
| **G12 Reloj** (nuevo, ~4) | — | ningún módulo llama a `datetime.now/time.time` (test estático); rollover y timeout dependen solo del reloj inyectado. |

Total estimado: **~150 aserciones**, de las cuales ~97 son las que ya existen reescritas y ~48 nuevas (kill
switch, ledger y rotación, cero defaults, reloj, escritor concurrente) que hoy no tienen prueba propia. Lo que **no** viaja: risk‑exit por ATR,
TTL de posición, capital operativo, política de señal única, SPX, EMA, código muerto — es del sistema de origen.

---

## 7. Nombre — tres propuestas

1. **`bailout`** — corto, una palabra inglesa cotidiana; sugiere exactamente "salida de emergencia" y
   "poder salir siempre", que es la regla central (las salidas no se atrapan). Sin jerga de trading. Riesgo:
   connotación de rescate financiero.
2. **`deadman`** (de *dead man's switch*) — el mecanismo que detiene la máquina si nadie puede dar fe de que
   todo está bien: es literalmente lo que hace el kill switch fail‑closed y el estado desconocido ⇒ halt.
   Muy reconocible en seguridad industrial. Riesgo: suena sombrío; puede haber colisiones de nombre.
3. **`gatekeep`** — describe el rol (una puerta con criterios explícitos entre la intención y el broker) y
   se lee como verbo: "gatekeep the order". Neutro, corto. Riesgo: connotación social negativa de
   "gatekeeping".

**Decisión (2026-08-18): `deadman`.** `bailout` evoca rescate bancario; `gatekeep` tomó sentido coloquial
negativo. `failclosed` nombra el principio y queda reservado para el principio, no para el paquete.

---

## Decisiones tomadas (2026-08-18) — la spec queda cerrada
- **A** kill switch: solo sentinel; existencia, nunca contenido; no parsea nada.
- **B** `daily_stats` ilegible: fail‑closed SOLO para entradas; las salidas pasan sin leer el archivo.
- **C** rotación anclada: `LEDGER_ROTATED` con `prev_last_hash` (== `prev_hash`) + `prev_sha256`; `verify` cruza archivos.
- **D** sin locks de SO en halt/stats; detección de escritor concurrente por sello `(writer_pid, writer_started_at, write_seq)` ⇒ `CONCURRENT_WRITER_DETECTED`.
- **Nombre**: `deadman`.
