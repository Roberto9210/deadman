# Safety Kit — especificación (v0.1, 2026-08-18)

Primitivas de seguridad de ejecución para sistemas de trading automatizados, agnósticas de broker y
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
| **Ledger firmado y encadenado** | Los registros se podían editar, y de hecho una parte de la historia se resumía con datos posteriores. Hash‑chain + firma + escritura atómica: se puede probar qué se decidió, cuándo, y que nadie lo cambió después. |
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
    kill_state:    Path      # root/"kill_state.json"       (opcional, ver §5.2)
    entry_halt:    Path      # root/"entry_halt.json"
    daily_stats:   Path      # root/"daily_stats.json"
    ledger_dir:    Path      # root/"ledger"/  -> ledger.jsonl, chain_state.json, chain_state.lock, keys/

# ---------- 1. kill switch ----------
class KillSwitch:
    def __init__(self, paths: Paths, state_key: str = "kill_switch", require_state_file: bool = False)
    def check(self) -> Verdict            # bloqueado si: sentinel existe | (require_state_file y falta/ilegible/sin clave/true)
                                          # cualquier OSError => bloqueado con code KILL_SWITCH_CHECK_FAILED
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
class DailyLimits:
    def __init__(self, paths: Paths, limits: Limits, is_exit: ExposurePredicate, clock: Clock)
    def check(self, intent: Intent, resolved: Resolved, position: PositionSnapshot | None) -> Verdict
                                                # si is_exit(intent, position): Verdict.allow("EXIT_BYPASSES_DAILY_LIMITS")
    def record_fill(self, intent: Intent, filled_usd: float) -> None    # entradas Y salidas cuentan
    def record_pnl(self, realized_pnl_usd: float) -> None
    def stats(self) -> DailyStats                                       # día UTC actual (rollover al leer)

class OrderSanity:
    def __init__(self, allowed_symbols: frozenset[str], max_latency_ms: float, max_spread_bps: float)
    def check(self, intent: Intent, resolved: Resolved, *,
              broker_status: str, latency_ms: float, bid: float, ask: float,
              size_available: float | None) -> Verdict
              # aplica a entradas Y salidas; cualquier argumento None/NaN => denegado <ARG>_MISSING
              # size_available: para BASE/CONTRACTS en salida = base disponible; para USD en entrada = quote disponible

# ---------- 5. ledger firmado ----------
@dataclass(frozen=True)
class Entry: seq: int; ts_utc: str; kind: str; actor: str; payload: Mapping; prev_hash: str; hash: str; sig: str; schema_version: int
class SignedLedger:
    def __init__(self, paths: Paths, clock: Clock, signing_key: bytes | None = None,
                 on_append: Callable[[Entry], None] | None = None)     # hook (p.ej. anchor externo); NO parte del kit
    def append(self, kind: str, payload: Mapping, actor: str = "user") -> Entry   # falla ruidoso (LedgerWriteError); el llamador decide halt
    def last_hash(self) -> str
    def verify(self, from_seq: int | None = None) -> VerifyReport                # ver §5.5 rotación
    def public_key(self) -> bytes

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
| `kill_switch.enabled` | (sin contenido) | Su existencia es la señal. Contenido ignorado. |
| `kill_state.json` (opcional) | `{schema_version, kill_switch: bool, reason: str|null, ts_utc}` | Segunda vía. Solo se consulta si `require_state_file=True`; entonces faltar/ilegible/sin clave ⇒ bloqueado. **DECISIÓN PENDIENTE A**: ¿viaja o solo el sentinel? Opción 1, solo sentinel (más simple, un solo mecanismo). Opción 2, ambos (compatibilidad con quien mira un JSON). Costo de 2: dos verdades a mantener coherentes. Recomendación: 1, y `engage()` escribe la razón en el ledger, no en un JSON. |
| `entry_halt.json` | `{schema_version, active: true, reason: str(<=300), source: str, ts_utc, auto_clear: bool}` | Presencia con `active:true` = halt. Ilegible = halt. Escritura atómica (tmp + replace). `clear()` borra el archivo. |
| `daily_stats.json` | `{schema_version, day_utc: "YYYY-MM-DD", trades: int, filled_usd: float, realized_pnl_usd: float, updated_ts_utc}` | Al leer, si `day_utc != clock.today_utc()` ⇒ se reinicia en memoria y se persiste. Ilegible ⇒ **DECISIÓN PENDIENTE B**: (1) tratar como límites agotados (fail‑closed, puede bloquear un día entero por un archivo corrupto) o (2) reiniciar y anotar `DAILY_STATS_RESET_UNREADABLE` en el ledger (fail‑open sobre contadores). Recomendación: 1 para entradas — es coherente con §2 — y el ledger avisa. |
| `ledger/chain_state.json` | `{schema_version, last_seq: int, last_hash: str}` | Solo el tip. Reemplazo atómico. Ver 5.5. |
| `ledger/ledger.jsonl` | una `Entry` por línea | Append‑only. |
| `ledger/keys/` | clave privada Ed25519 (permisos 0600) + pública | Si no existe al construir `SignedLedger` sin `signing_key`, se genera y se anota `KEY_GENERATED`. |

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
El adaptador **no** hace reintentos silenciosos: si reintenta, lo anota en `raw` y respeta G1. Un adaptador es
conforme si pasa las pruebas de §6 con estas garantías. (El primer adaptador previsto es ccxt/Kraken spot; los
`FakeExchange`/`FakeRouter` de los tests actuales son la referencia de forma.)

### 5.5 Catálogo de `kind` del ledger y rotación
Kinds mínimos: `KEY_GENERATED, KILL_ENGAGED, KILL_RELEASED, HALT_SET, HALT_CLEARED, INTENT_DENIED, ORDER_SENT,
FILL, PARTIAL_FILL, NO_FILL_CANCELED, UNKNOWN_STATE, RECONCILE_REPORT, DAILY_STATS_RESET, LEDGER_ROTATED,
USER_NOTE`. Payload mínimo por kind se fija en el test correspondiente. Todo `payload` lleva `client_id` si
existe.
**Rotación sin romper `verify`:** **DECISIÓN PENDIENTE C** — el sistema de origen rotó el archivo y dejó un
segmento cuya primera fila no encadena a génesis, con lo que `verify()` desde génesis falla y "congela".
Opciones: (1) no rotar nunca (jsonl crece; simple; verify total siempre posible); (2) rotar escribiendo
como primera entrada del segmento nuevo un `LEDGER_ROTATED{prev_segment, prev_last_hash, prev_last_seq}` y
que `verify()` acepte encadenar desde ese ancla (verify por segmento + verificación del ancla contra el
segmento anterior si está presente); (3) rotar y perder verificabilidad histórica (descartada). Recomendación:
2, con `verify(from_seq)` documentado como "desde el último ancla disponible" cuando el segmento anterior no
está.

### 5.6 Reloj UTC inyectable
`Clock` es un objeto con `now_utc() -> datetime(tz=UTC)` y `today_utc() -> "YYYY-MM-DD"`. Todas las
primitivas lo reciben en el constructor; ninguna llama a `datetime.now()`/`time.time()` directamente. Por qué:
el rollover diario, el timeout de fill, la edad de un halt y la ventana de un outcome son irreproducibles en
test sin controlar el tiempo, y un `now()` implícito ya produjo un caso no reproducible en el sistema de
origen. El reloj de producción es trivial; el de test avanza a mano.

### 5.7 Un solo escritor por archivo de estado
`entry_halt.json`, `daily_stats.json` y `kill_switch.enabled` asumen **un único proceso escritor**; las
escrituras son atómicas (tmp + `os.replace`) para que un lector concurrente nunca vea un archivo a medias, pero
dos escritores se pisan. El **ledger** es la única pieza multi‑proceso: `append()` toma un lock de SO sobre
`chain_state.lock` durante leer‑tip → escribir‑entrada → reemplazar‑tip. **DECISIÓN PENDIENTE D**: ¿el kit
impone el lock también a `entry_halt`/`daily_stats` (más lento, más seguro) o documenta "un escritor" y deja
al usuario? Costo de imponerlo: dependencia `msvcrt/fcntl` en tres archivos y latencia por escritura.
Recomendación: documentar "un escritor" en v0.1; lock opcional en v0.2 si aparece un caso.

---

## 6. Qué pruebas definen la conformidad

Un adaptador (`BrokerPort`) y una integración son **conformes** si pasan estas pruebas, ejecutadas con
`Paths(tempdir)`, reloj de test y un broker falso con las garantías de 5.4. Cada grupo conserva el patrón del
sistema de origen: **cada regla con su par** (caso que debe pasar / caso que debe fallar), y para las
comprobaciones de datos, el caso "ausente ⇒ denegado con código".

| Grupo | Origen (aserciones que viajan, reescritas) | Qué fija |
|---|---|---|
| **G1 Kill switch** (nuevo, ~8) | — | sentinel presente ⇒ todo denegado (entrada y salida); OSError al comprobar ⇒ denegado `KILL_SWITCH_CHECK_FAILED`; ausente ⇒ pasa; `engage/release` idempotentes y anotados. |
| **G2 Entry halt** (gate, ~10) | exit_tanda gate | set ⇒ entrada denegada `ENTRY_HALT_ACTIVE` y salida pasa; archivo ilegible ⇒ halt; `auto_clear` solo si el existente lo era; `clear(only_auto_clear)` no borra un halt manual. |
| **G3 Unidades** (16) | exit_tanda units | `USD`/`BASE`/`CONTRACTS` resuelven; ausente/inválido/amount≤0/price≤0 ⇒ excepción con el intent en el mensaje; salida en `BASE` vende exactamente lo pedido; nunca se infiere. |
| **G4 Límites diarios** (gate, ~10) | exit_tanda gate | pérdida diaria / nº de trades / nocional bloquean entrada y **no** salida; los fills de salida incrementan contadores; rollover UTC con reloj inyectado; stats ilegible ⇒ (según decisión B) entradas denegadas. |
| **G5 Cordura de orden** (fix5 + gate, ~12) | cleanup fix5, exit gate | broker no `connected` / latencia > máx / spread > máx / símbolo no permitido / tamaño insuficiente ⇒ denegado **también para salidas**; cualquier input `None`/`NaN` ⇒ `<ARG>_MISSING` — nunca un default. |
| **G6 Post‑fill honesto** (24) | exit_tanda postfill | fill total ⇒ `FILLED` con `filled/avg/fee`; parcial ⇒ `PARTIAL` con lo real; timeout ⇒ cancel + relectura ⇒ `NO_FILL_CANCELED` y **no** cuenta como trade; excepción en confirm ⇒ `UNKNOWN` + halt auto_clear + ledger; cancel que falla ⇒ `UNKNOWN`; cancel de orden ya llena ⇒ `FILLED`. |
| **G7 Detectar ⇒ actuar** (6) | exit_tanda detect | ledger falla al escribir `ORDER_SENT` ⇒ no se envía + halt manual; reconcile encuentra abierto desconocido que aumenta exposición ⇒ cancelado + halt auto; que reduce ⇒ dejado + reporte; libro vacío ⇒ limpia solo halt auto; error por símbolo ⇒ no limpia. |
| **G8 Snapshot de cuenta** (fix3, ~8) | cleanup fix3 | un dato de cuenta con edad > máx o status ≠ sincronizado se trata como **ausente** (denegar entrada con `ACCOUNT_SNAPSHOT_STALE`), nunca como el último valor bueno; salidas no dependen de él. |
| **G9 Todo en llamas** (13) | exit_tanda fire | con halt + límites agotados + stats corruptas + kill switch **apagado**, una salida pasa; con kill switch encendido, no; con spread fuera de rango, tampoco. Es el test de la asimetría completa. |
| **G10 Cero defaults** (nuevo, ~10) | — | por cada dato de entrada del ejecutor, el caso ausente ⇒ `DENIED/<DATO>_MISSING`; **equity/balance ausente nunca produce un tamaño** (el contraejemplo de §2 como test). |
| **G11 Ledger** (nuevo, ~10) | — | append encadena y firma; `verify()` detecta una línea alterada, borrada o reordenada; escritura concurrente desde dos procesos no rompe la cadena; rotación (según decisión C) verificable desde el ancla. |
| **G12 Reloj** (nuevo, ~4) | — | ningún módulo llama a `datetime.now/time.time` (test estático); rollover y timeout dependen solo del reloj inyectado. |

Total estimado: **~130 aserciones**, de las cuales ~97 son las que ya existen reescritas y ~35 nuevas (kill
switch, ledger, cero defaults, reloj) que hoy no tienen prueba propia. Lo que **no** viaja: risk‑exit por ATR,
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

Recomendación: **`bailout`** por la correspondencia exacta con el principio rector; segundo, `deadman`.

---

## Decisiones pendientes (resumen)
- **A** kill switch: solo sentinel (recomendado) o sentinel + JSON.
- **B** `daily_stats` ilegible: fail‑closed para entradas (recomendado) o reset con aviso.
- **C** rotación del ledger: nunca (simple) o anclada con `LEDGER_ROTATED` (recomendado).
- **D** lock también en halt/stats: no en v0.1 (recomendado, "un escritor" documentado).
