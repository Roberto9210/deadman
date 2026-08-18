"""HonestExecutor - the post-fill state machine and startup reconciliation
(SPEC §4.6, §5.3, §5.4). Every decision leaves a ledger entry; the ledger alone
explains every final state.

Fixed order of execute() (SPEC §4):
  1 kill.check()                                   -> DENIED/KILL_SWITCH_*      (entries AND exits)
  2 exit = is_exit(intent, position)
  3 not exit: halt.active()                        -> DENIED/ENTRY_HALT_ACTIVE
  4 resolve_units                                  -> DENIED/INTENT_*
  5 not exit: limits.check                         -> DENIED/DAILY_*
  6 sanity.check (+ quantize if amount_step given) -> DENIED/<SANITY_CODE>
  7 WRITE-AHEAD: ORDER_SENT{stage:"write_ahead"} with a deterministic client_order_id
    derived from the intent, BEFORE any network call. Ledger failure -> nothing is
    sent, DENIED/LEDGER_WRITE_FAILED, manual halt.
    A client_order_id already non-terminal in the ledger -> DENIED/DUPLICATE_IN_FLIGHT:
    retrying without a confirmed terminal state of the previous attempt is double
    exposure; idempotency is by client_order_id, not by hope.
  8 broker.create_order:
      Order with id          -> ORDER_SENT{stage:"acked", order_id}
      BrokerRejected (G1)    -> INTENT_DENIED{code:BROKER_REJECTED}; nothing to reconcile
      OrderMaybeSent/timeout -> ORDER_SENT{stage:"sent_no_ack"}: the order is PRESUMED ALIVE.
                                Resolved via fetch_order_by_client_id (G9): found -> continue at 9;
                                authoritative None -> INTENT_DENIED{code:BROKER_NEVER_ACCEPTED};
                                anything else -> 10.
  9 poll fetch_order every poll_interval_s until fill_timeout_s (clock + sleeper injected):
      closed & filled>0      -> FILL / PARTIAL_FILL (never rounded up; duplicate fill ids in
                                raw["fills"] are counted once and NOTED in the ledger)
      timeout while open     -> cancel_order -> re-read -> canceled&0 -> NO_FILL_CANCELED (not a trade)
                                                        -> canceled&>0 -> PARTIAL_FILL
                                                        -> closed&>0   -> FILL/PARTIAL_FILL (filled during cancel)
 10 anything not covered above (exception in fetch/cancel, status "unknown", filled > requested,
    closed with 0 and no reason, cancel not confirmed) -> UNKNOWN_STATE + EntryHalt(auto_clear=True)
    + ExecResult.UNKNOWN. Nothing is ever declared success or failure by assumption.

startup(symbols, position_of) runs BEFORE any intent is accepted (execute() denies with
STARTUP_RECONCILE_REQUIRED until it has run): every non-terminal client_order_id in the ledger is
looked up at the broker by client id and resolved one by one; every open order at the broker that
the ledger does not know is UNKNOWN_STATE + halt. Every discrepancy is a ledger entry; nothing is
healed in silence. Something found -> halt(auto_clear=True); nothing found and no errors -> the
auto-clear halt is cleared.

Fail-closed choices where the spec was silent (documented here and in SPEC §4.4):
  * execute() before startup() -> denied.
  * an in-flight duplicate client_order_id -> denied (no blind retry).
  * fetch_order_by_client_id returning None after OrderMaybeSent is trusted as "never accepted"
    ONLY because G9 makes it authoritative; an adapter that cannot promise that must raise.
  * a fill whose fee is None is reported with fees_usd=None and handed to DailyLimits as None
    (which either charges the worst case or marks the day unverified) - never 0.
"""
import hashlib
import json
import logging
import time
from dataclasses import dataclass, asdict
from typing import Callable, Iterable, Optional, Set

from .broker import BrokerPort, BrokerRejected, Order
from .clock import Clock, iso
from .daily_limits import DailyLimits
from .entry_halt import EntryHalt
from .errors import (ConcurrentWriterDetected, ContractSizeMissing, DeadmanError, IntentAmountInvalid,
                     IntentUnitsInvalid, LedgerWriteError, OrderMaybeSent, PriceInvalid)
from .intent import ExposurePredicate, Intent, PositionSnapshot, Resolved, resolve_units
from .kill_switch import KillSwitch
from .ledger import Ledger
from .order_sanity import OrderSanity
from .verdict import Verdict

TERMINAL_KINDS = ("FILL", "PARTIAL_FILL", "NO_FILL_CANCELED", "UNKNOWN_STATE")


@dataclass(frozen=True)
class ExecResult:
    status: str            # FILLED | PARTIAL | NO_FILL_CANCELED | DENIED | UNKNOWN
    code: str
    reason: str
    order_id: Optional[str]
    client_order_id: Optional[str]
    filled_base: float
    avg_price: Optional[float]
    fees_usd: Optional[float]
    ledger_seq: Optional[int]


@dataclass
class ReconcileReport:
    pending_seen: int = 0
    resolved: list = None
    unknown: list = None
    canceled: list = None
    left_open: list = None
    errors: list = None
    halt_set: bool = False
    halt_cleared: bool = False

    def __post_init__(self):
        for f in ("resolved", "unknown", "canceled", "left_open", "errors"):
            if getattr(self, f) is None:
                setattr(self, f, [])

    def as_dict(self) -> dict:
        return asdict(self)


def client_order_id_for(intent: Intent) -> str:
    """Deterministic: the same intent (same client_id) always maps to the same
    broker client id, which is what makes a retry after a crash idempotent."""
    body = json.dumps({"client_id": intent.client_id, "symbol": intent.symbol, "side": intent.side,
                       "units": intent.units, "amount": intent.amount, "kind": intent.kind}, sort_keys=True)
    return "dm-" + hashlib.sha256(body.encode("utf-8")).hexdigest()[:24]


class HonestExecutor:
    def __init__(self, broker: BrokerPort, kill: KillSwitch, halt: EntryHalt, limits: DailyLimits,
                 sanity: OrderSanity, ledger: Ledger, is_exit: ExposurePredicate, clock: Clock,
                 fill_timeout_s: float, poll_interval_s: float, sleeper: Callable[[float], None] | None = None,
                 order_type: str = "limit", logger: logging.Logger | None = None):
        self.broker, self.kill, self.halt, self.limits, self.sanity, self.ledger = broker, kill, halt, limits, sanity, ledger
        self.is_exit, self.clock = is_exit, clock
        self.fill_timeout_s, self.poll_interval_s = float(fill_timeout_s), float(poll_interval_s)
        self.sleeper = sleeper or time.sleep
        self.order_type = order_type
        self.log = logger or logging.getLogger("deadman.executor")
        self._started = False
        self._index: dict[str, dict] = {}   # client_order_id -> {stage, order_id, symbol, side, is_exit, requested_base, terminal}

    # ------------------------------------------------------------------ index from ledger
    def _rebuild_index(self) -> None:
        self._index = {}
        segs = []
        n = 1
        while self.ledger.paths.segment(n).exists():
            segs.append(self.ledger.paths.segment(n))
            n += 1
        segs.append(self.ledger.paths.ledger_file)
        for p in segs:
            if not p.exists():
                continue
            with open(p, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    e = json.loads(line)
                    pl = e.get("payload") or {}
                    coid = pl.get("client_order_id")
                    if not coid:
                        continue
                    rec = self._index.setdefault(coid, {"stage": None, "order_id": None, "symbol": pl.get("symbol"),
                                                        "side": pl.get("side"), "is_exit": pl.get("is_exit"),
                                                        "requested_base": pl.get("requested_base"), "terminal": False,
                                                        "intent": pl.get("intent")})
                    k = e.get("kind")
                    if k == "ORDER_SENT":
                        rec["stage"] = pl.get("stage")
                        rec["order_id"] = pl.get("order_id") or rec["order_id"]
                        for key in ("symbol", "side", "is_exit", "requested_base", "intent"):
                            if pl.get(key) is not None:
                                rec[key] = pl.get(key)
                    elif k in TERMINAL_KINDS:
                        rec["terminal"] = True
                        rec["order_id"] = pl.get("order_id") or rec["order_id"]
                    elif k == "INTENT_DENIED" and pl.get("terminal_for_client_order_id"):
                        rec["terminal"] = True
                    elif k == "RECONCILE_REPORT" and pl.get("resolution") and pl.get("terminal"):
                        rec["terminal"] = True

    def pending(self) -> dict[str, dict]:
        return {k: v for k, v in self._index.items() if not v["terminal"] and v["stage"] is not None}

    # ------------------------------------------------------------------ helpers
    def _led(self, kind: str, payload: dict):
        return self.ledger.append(kind, payload, actor="deadman.executor")

    def _deny(self, intent: Intent, code: str, reason: str, coid: Optional[str] = None, terminal: bool = False) -> ExecResult:
        seq = None
        try:
            pl = {"code": code, "reason": reason, "intent": intent.as_dict(), "by": "deadman.executor"}
            if coid:
                pl["client_order_id"] = coid
                pl["terminal_for_client_order_id"] = bool(terminal)
            seq = self._led("INTENT_DENIED", pl).seq
        except Exception as e:  # denial must still be reported even if the ledger is down
            self.log.critical("[EXEC] ledger append failed while denying %s: %s", code, e)
        if coid and terminal and coid in self._index:
            self._index[coid]["terminal"] = True
        return ExecResult("DENIED", code, reason, None, coid, 0.0, None, None, seq)

    def _unknown(self, intent_d: dict, coid: str, order_id: Optional[str], why: str, extra: Optional[dict] = None) -> ExecResult:
        payload = {"client_order_id": coid, "order_id": order_id, "why": why, "intent": intent_d, **(extra or {})}
        seq = None
        try:
            seq = self._led("UNKNOWN_STATE", payload).seq
        except Exception as e:
            self.log.critical("[EXEC] ledger append failed for UNKNOWN_STATE: %s", e)
        try:
            self.halt.set(f"ORDER_STATE_UNKNOWN: {coid} {order_id} - {why}", source="deadman.executor", auto_clear=True)
        except Exception as e:
            self.log.critical("[EXEC] halt.set failed: %s", e)
        if coid in self._index:
            self._index[coid]["terminal"] = True
            self._index[coid]["order_id"] = order_id or self._index[coid]["order_id"]
        self.log.critical("[EXEC] ORDER STATE UNKNOWN %s %s: %s", coid, order_id, why)
        return ExecResult("UNKNOWN", "ORDER_STATE_UNKNOWN", why, order_id, coid, 0.0, None, None, seq)

    @staticmethod
    def _effective_fill(order: Order):
        """(filled_base, avg, fee_usd, duplicate_ids). Duplicated fill ids in raw['fills']
        are counted ONCE. Returns fee None if any fill lacks it and the order lacks it."""
        fills = order.raw.get("fills") if isinstance(order.raw, dict) else None
        if isinstance(fills, list) and fills:
            seen: dict = {}
            dups = []
            for f in fills:
                fid = str(f.get("id"))
                if fid in seen:
                    dups.append(fid)
                    continue
                seen[fid] = f
            qty = sum(float(f.get("qty", 0.0)) for f in seen.values())
            notional = sum(float(f.get("qty", 0.0)) * float(f.get("price", 0.0)) for f in seen.values())
            avg = (notional / qty) if qty > 0 else None
            fee_parts = [f.get("fee_usd") for f in seen.values()]
            fee = sum(float(x) for x in fee_parts) if all(x is not None for x in fee_parts) else order.fee_usd
            return qty, avg, fee, dups
        return float(order.filled or 0.0), order.average, order.fee_usd, []

    def _record_fill(self, intent: Intent, coid: str, order: Order, filled: float, avg: Optional[float],
                     fee: Optional[float], requested: float, dups: list, via: str) -> ExecResult:
        partial = filled + 1e-12 < requested
        kind = "PARTIAL_FILL" if partial else "FILL"
        pl = {"client_order_id": coid, "order_id": order.id, "symbol": order.symbol, "side": order.side,
              "filled_base": filled, "requested_base": requested, "avg_price": avg, "fees_usd": fee,
              "fee_known": fee is not None, "duplicate_fill_ids_ignored": dups, "via": via, "final": True}
        seq = self._led(kind, pl).seq
        if coid in self._index:
            self._index[coid]["terminal"] = True
            self._index[coid]["order_id"] = order.id
        try:
            usd = filled * (avg if avg is not None else 0.0)
            self.limits.record_fill(intent, usd, fee)
        except ConcurrentWriterDetected as e:
            self.halt.set(f"CONCURRENT_WRITER_DETECTED while recording fill {coid}: {e}", source="deadman.executor", auto_clear=False)
        except Exception as e:
            self.log.critical("[EXEC] limits.record_fill failed for %s: %s", coid, e)
        return ExecResult("PARTIAL" if partial else "FILLED", kind, f"{filled} of {requested} base via {via}",
                          order.id, coid, filled, avg, fee, seq)

    # ------------------------------------------------------------------ execute
    def execute(self, intent: Intent, price: float, *, broker_status: Optional[str], latency_ms: Optional[float],
                bid: Optional[float], ask: Optional[float], size_available: Optional[float],
                position: Optional[PositionSnapshot] = None, contract_size: Optional[float] = None,
                amount_step: Optional[float] = None, ref_price: Optional[float] = None) -> ExecResult:
        if not self._started:
            return self._deny(intent, "STARTUP_RECONCILE_REQUIRED", "startup() must run before any intent is accepted")
        v = self.kill.check()                                                            # 1
        if not v.allowed:
            return self._deny(intent, v.code, v.reason)
        exit_ = bool(self.is_exit(intent, position))                                     # 2
        if not exit_:                                                                    # 3
            h = self.halt.active()
            if h is not None:
                return self._deny(intent, "ENTRY_HALT_ACTIVE", f"{h.reason} (source={h.source}, auto_clear={h.auto_clear})")
        try:                                                                             # 4
            resolved = resolve_units(intent, price, contract_size)
        except (IntentUnitsInvalid, IntentAmountInvalid, PriceInvalid, ContractSizeMissing) as e:
            return self._deny(intent, str(e).split(":")[0], str(e))
        if not exit_:                                                                    # 5
            v = self.limits.check(intent, resolved, position)
            if not v.allowed:
                return self._deny(intent, v.code, v.reason)
        v = self.sanity.check(intent, resolved, broker_status=broker_status, latency_ms=latency_ms, bid=bid, ask=ask,  # 6
                              size_available=size_available, is_exit=exit_, ref_price=ref_price)
        if not v.allowed:
            return self._deny(intent, v.code, v.reason)
        send_base = resolved.amount_base
        if amount_step is not None:
            q = self.sanity.quantize(intent, resolved, amount_step=amount_step, price=price)
            if not q.verdict.allowed:
                return self._deny(intent, q.verdict.code, q.verdict.reason)
            send_base = q.amount_base
        coid = client_order_id_for(intent)                                              # 7
        rec = self._index.get(coid)
        if rec is not None and not rec["terminal"] and rec["stage"] is not None:
            return self._deny(intent, "DUPLICATE_IN_FLIGHT",
                              f"client_order_id {coid} is non-terminal (stage={rec['stage']}, order_id={rec['order_id']}); "
                              f"no blind retry - resolve it via startup()/reconcile first")
        wa = {"stage": "write_ahead", "client_order_id": coid, "symbol": intent.symbol, "side": intent.side,
              "is_exit": exit_, "requested_base": send_base, "resolved": asdict(resolved), "intent": intent.as_dict(),
              "price": float(price), "order_type": self.order_type}
        try:
            self._led("ORDER_SENT", wa)
        except Exception as e:
            try:
                self.halt.set(f"LEDGER_WRITE_FAILED before send: {e}", source="deadman.executor", auto_clear=False)
            except Exception:
                pass
            return ExecResult("DENIED", "LEDGER_WRITE_FAILED", f"nothing was sent: {e}", None, coid, 0.0, None, None, None)
        self._index[coid] = {"stage": "write_ahead", "order_id": None, "symbol": intent.symbol, "side": intent.side,
                             "is_exit": exit_, "requested_base": send_base, "terminal": False, "intent": intent.as_dict()}
        # 8 ---- the only non-atomic step
        try:
            order = self.broker.create_order(intent.symbol, intent.side, send_base, self.order_type,
                                             float(price) if self.order_type == "limit" else None, coid)
            if not isinstance(order, Order) or not order.id:
                raise OrderMaybeSent(coid, "create_order returned no Order/id")
        except BrokerRejected as e:
            return self._deny(intent, "BROKER_REJECTED", f"{e}", coid, terminal=True)
        except OrderMaybeSent as e:
            self._led("ORDER_SENT", {"stage": "sent_no_ack", "client_order_id": coid, "symbol": intent.symbol,
                                     "side": intent.side, "is_exit": exit_, "requested_base": send_base, "why": str(e)})
            self._index[coid]["stage"] = "sent_no_ack"
            found = self._lookup_by_client_id(coid, intent.symbol)
            if found == "ERROR":
                return self._unknown(intent.as_dict(), coid, None, "OrderMaybeSent and fetch_order_by_client_id failed")
            if found is None:
                return self._deny(intent, "BROKER_NEVER_ACCEPTED",
                                  f"OrderMaybeSent, then broker authoritatively reports no order for {coid} (G9)", coid, terminal=True)
            order = found
        except Exception as e:  # any other exception: we cannot tell whether it was accepted (G1 not honoured) -> presume alive
            self._led("ORDER_SENT", {"stage": "sent_no_ack", "client_order_id": coid, "symbol": intent.symbol,
                                     "side": intent.side, "is_exit": exit_, "requested_base": send_base,
                                     "why": f"{type(e).__name__}: {e}"})
            self._index[coid]["stage"] = "sent_no_ack"
            found = self._lookup_by_client_id(coid, intent.symbol)
            if found == "ERROR" or found is None:
                # None here is NOT trusted: the adapter did not raise OrderMaybeSent, so it did not promise G9 semantics for this path
                return self._unknown(intent.as_dict(), coid, None, f"create_order raised {type(e).__name__} and lookup gave {found!r}")
            order = found
        self._led("ORDER_SENT", {"stage": "acked", "client_order_id": coid, "order_id": order.id, "symbol": intent.symbol,
                                 "side": intent.side, "is_exit": exit_, "requested_base": send_base})
        self._index[coid].update({"stage": "acked", "order_id": order.id})
        return self._settle(intent, coid, order, send_base, exit_)

    def _lookup_by_client_id(self, coid: str, symbol: str):
        try:
            return self.broker.fetch_order_by_client_id(coid, symbol)
        except Exception:
            return "ERROR"

    # ------------------------------------------------------------------ 9/10 settle
    def _settle(self, intent: Intent, coid: str, order: Order, requested: float, exit_: bool) -> ExecResult:
        t0 = self.clock.monotonic()
        last = order
        while True:
            fin = self._finalize_if_terminal(intent, coid, last, requested, via="poll")
            if fin is not None:
                return fin
            if last.status != "open":
                return self._unknown(intent.as_dict(), coid, last.id, f"status {last.status!r} not in the state machine")
            if self.clock.monotonic() - t0 >= self.fill_timeout_s:
                break
            self.sleeper(self.poll_interval_s)
            try:
                last = self.broker.fetch_order(order.id, intent.symbol)
            except Exception as e:
                return self._unknown(intent.as_dict(), coid, order.id, f"fetch_order raised {type(e).__name__}: {e}")
        # timeout while open -> cancel -> re-read
        try:
            after = self.broker.cancel_order(order.id, intent.symbol)
        except Exception as e:
            return self._unknown(intent.as_dict(), coid, order.id, f"cancel_order raised {type(e).__name__}: {e}")
        try:
            reread = self.broker.fetch_order(order.id, intent.symbol)
        except Exception as e:
            return self._unknown(intent.as_dict(), coid, order.id, f"re-read after cancel raised {type(e).__name__}: {e}")
        if reread.status == "open":
            return self._unknown(intent.as_dict(), coid, order.id, "cancel not confirmed: still open on re-read")
        fin = self._finalize_if_terminal(intent, coid, reread, requested, via="cancel_reread")
        if fin is not None:
            return fin
        return self._unknown(intent.as_dict(), coid, order.id, f"after cancel status={reread.status!r} filled={reread.filled!r} (cancel returned {after.status!r})")

    def _finalize_if_terminal(self, intent: Intent, coid: str, o: Order, requested: float, via: str) -> Optional[ExecResult]:
        """Terminal transitions of the state machine; None if still open. Anything
        outside the machine is UNKNOWN (returned as a result, not None)."""
        filled, avg, fee, dups = self._effective_fill(o)
        if filled < 0 or filled != filled:
            return self._unknown(intent.as_dict(), coid, o.id, f"filled={filled!r} invalid")
        if filled > requested * (1 + 1e-6) + 1e-12:
            return self._unknown(intent.as_dict(), coid, o.id, f"filled {filled} > requested {requested}", {"duplicate_fill_ids": dups})
        if o.status == "closed":
            if filled > 0:
                return self._record_fill(intent, coid, o, filled, avg, fee, requested, dups, via)
            return self._unknown(intent.as_dict(), coid, o.id, "closed with 0 filled and no reason (silent reject)")
        if o.status == "canceled":
            if filled > 0:
                return self._record_fill(intent, coid, o, filled, avg, fee, requested, dups, via)
            seq = self._led("NO_FILL_CANCELED", {"client_order_id": coid, "order_id": o.id, "symbol": o.symbol,
                                                 "side": o.side, "requested_base": requested, "via": via, "final": True}).seq
            if coid in self._index:
                self._index[coid]["terminal"] = True
            return ExecResult("NO_FILL_CANCELED", "TIMEOUT_NO_FILL_CANCELED", "canceled with 0 filled: not a trade",
                              o.id, coid, 0.0, None, None, seq)
        if o.status == "open":
            return None
        return self._unknown(intent.as_dict(), coid, o.id, f"status {o.status!r} outside the state machine")

    # ------------------------------------------------------------------ startup / reconcile
    def startup(self, symbols: Iterable[str], position_of: Callable[[str], Optional[PositionSnapshot]]) -> ReconcileReport:
        """Reconcile BEFORE accepting intents. See module docstring."""
        rep = ReconcileReport()
        self._rebuild_index()
        # 1) every non-terminal client_order_id in the ledger, one by one
        for coid, rec in list(self.pending().items()):
            rep.pending_seen += 1
            sym = rec.get("symbol") or ""
            intent = None
            try:
                intent = Intent.from_mapping(rec["intent"]) if rec.get("intent") else None
            except Exception:
                intent = None
            found = self._lookup_by_client_id(coid, sym)
            if found == "ERROR" and rec.get("order_id"):
                try:
                    found = self.broker.fetch_order(rec["order_id"], sym)
                except Exception:
                    found = "ERROR"
            if found == "ERROR":
                rep.errors.append({"client_order_id": coid, "error": "lookup failed"})
                self._unknown(rec.get("intent") or {}, coid, rec.get("order_id"), "reconcile: lookup failed at broker")
                rep.unknown.append(coid)
                continue
            if found is None:
                res = "never_sent" if rec["stage"] == "write_ahead" else "broker_never_accepted"
                self._led("RECONCILE_REPORT", {"client_order_id": coid, "stage_was": rec["stage"], "resolution": res, "terminal": True})
                rec["terminal"] = True
                rep.resolved.append({"client_order_id": coid, "resolution": res})
                continue
            requested = float(rec.get("requested_base") or found.filled or 0.0)
            is_exit = bool(rec.get("is_exit"))
            if intent is None:  # ledger record predates the intent payload: build the minimum needed for limits/ledger
                intent = Intent(found.symbol or sym, found.side, "BASE", max(requested, 1e-12), "EXIT" if is_exit else "ENTRY", coid)
            self._index[coid]["order_id"] = found.id
            if found.status == "open":
                if is_exit:
                    self._led("RECONCILE_REPORT", {"client_order_id": coid, "order_id": found.id, "resolution": "left_open_exit", "terminal": False})
                    rep.left_open.append(coid)
                    continue
                try:
                    self.broker.cancel_order(found.id, found.symbol or sym)
                    reread = self.broker.fetch_order(found.id, found.symbol or sym)
                except Exception as e:
                    self._unknown(intent.as_dict(), coid, found.id, f"reconcile: cancel/re-read raised {type(e).__name__}: {e}")
                    rep.unknown.append(coid)
                    continue
                if reread.status == "open":
                    self._unknown(intent.as_dict(), coid, found.id, "reconcile: cancel not confirmed")
                    rep.unknown.append(coid)
                    continue
                fin = self._finalize_if_terminal(intent, coid, reread, requested, via="reconcile_cancel")
                rep.canceled.append(coid)
                rep.resolved.append({"client_order_id": coid, "resolution": fin.status if fin else "unknown"})
                continue
            fin = self._finalize_if_terminal(intent, coid, found, requested, via="reconcile")
            rep.resolved.append({"client_order_id": coid, "resolution": fin.status if fin else "unknown"})
            if fin is not None and fin.status == "UNKNOWN":
                rep.unknown.append(coid)
        # 2) open orders at the broker that the ledger does not know
        known_ids = {r["order_id"] for r in self._index.values() if r.get("order_id")}
        for sym in symbols:
            try:
                opens = self.broker.fetch_open_orders(sym) or []
            except Exception as e:
                rep.errors.append({"symbol": sym, "error": f"{type(e).__name__}: {e}"})
                continue
            for o in opens:
                if o.id in known_ids or (o.client_id and o.client_id in self._index):
                    continue
                probe = Intent(sym, o.side, "BASE", max(float(o.filled or 0) or 1e-12, 1e-12), "ENTRY", f"unknown-{o.id}")
                reduces = bool(self.is_exit(probe, position_of(sym)))
                why = "open order at broker not in ledger" + (" (reduces exposure: left)" if reduces else " (adds exposure: canceled)")
                if not reduces:
                    try:
                        self.broker.cancel_order(o.id, sym)
                        rep.canceled.append(o.id)
                    except Exception as e:
                        why += f"; cancel raised {type(e).__name__}"
                self._unknown({"symbol": sym, "side": o.side}, f"unknown-{o.id}", o.id, why)
                rep.unknown.append(o.id)
        # 3) halt policy
        found_something = bool(rep.resolved or rep.unknown or rep.canceled or rep.left_open or rep.errors)
        self._led("RECONCILE_REPORT", {"summary": rep.as_dict(), "terminal": False, "resolution": None})
        if found_something:
            if not rep.unknown:   # unknowns already set an auto-clear halt in _unknown()
                self.halt.set(f"reconcile found: resolved={len(rep.resolved)} canceled={len(rep.canceled)} left_open={len(rep.left_open)} errors={len(rep.errors)}",
                              source="deadman.executor.startup", auto_clear=True)
            rep.halt_set = True
        else:
            rep.halt_cleared = self.halt.clear("startup reconcile: broker book empty and no pending intents", only_auto_clear=True)
        self._started = True
        return rep
