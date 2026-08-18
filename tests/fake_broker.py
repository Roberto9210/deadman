"""FakeBroker for conformance tests. Deterministic: every wait/timestamp comes
from the injected Clock; no time.sleep anywhere. Failures are injected per
client_id via `plan` (a dict client_id -> mode) or globally via `default_mode`.

Modes (SPEC §5.3 / G6):
  ok              accepted, fills fully on the N-th fetch (fill_after_polls)
  partial         accepted, fills partially then stays open until canceled -> PARTIAL
  never_fills     accepted, stays open -> executor cancels -> NO_FILL_CANCELED
  reject          BrokerRejected before acceptance
  timeout         order IS accepted at the broker but create_order raises OrderMaybeSent (G1)
  timeout_lost    create_order raises OrderMaybeSent and the broker never saw it (G9 None)
  garbage         fetch_order returns an unmappable status -> "unknown"
  duplicate_fill  raw["fills"] carries the same fill twice; order.filled is doubled
  overfill        broker reports more filled than requested
  disconnect      fetch_order raises ConnectionError once, then behaves as ok
  cancel_fails    cancel_order raises
  cancel_ignored  cancel_order returns "canceled" but re-read still says "open"
  silent_reject   closed with filled 0
  out_of_order    fetch returns closed(filled) first, then open (stale callback)
  fee_unknown     fills but fee_usd is None

If `store_path` is given, the broker state persists to a JSON file so a killed
process and its successor see the same book (G9 conformance across restarts).
"""
import json
import os
from typing import Optional

from deadman import Order, BrokerRejected
from deadman.errors import OrderMaybeSent


class FakeBroker:
    def __init__(self, clock, plan: Optional[dict] = None, default_mode: str = "ok", fill_after_polls: int = 1,
                 fee_bps: float = 10.0, store_path: Optional[str] = None):
        self.clock = clock
        self.plan = dict(plan or {})
        self.default_mode = default_mode
        self.fill_after_polls = fill_after_polls
        self.fee_bps = fee_bps
        self.store_path = store_path
        self.orders: dict[str, dict] = {}       # order_id -> state
        self.by_client: dict[str, str] = {}     # client_id -> order_id
        self.calls: list = []
        self._seq = 0
        self._once: dict[str, bool] = {}
        self._load()

    # ---------- persistence for cross-process tests ----------
    def _load(self):
        if self.store_path and os.path.exists(self.store_path):
            with open(self.store_path, "r", encoding="utf-8") as f:
                d = json.load(f)
            self.orders, self.by_client, self._seq = d["orders"], d["by_client"], d["seq"]

    def _save(self):
        if self.store_path:
            tmp = self.store_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"orders": self.orders, "by_client": self.by_client, "seq": self._seq}, f)
            os.replace(tmp, self.store_path)

    def mode_for(self, client_id: str) -> str:
        return self.plan.get(client_id, self.default_mode)

    # ---------- helpers ----------
    def _new(self, symbol, side, amount, price, client_id, mode):
        self._seq += 1
        oid = f"O{self._seq}"
        self.orders[oid] = {"id": oid, "symbol": symbol, "side": side, "req": float(amount), "price": float(price or 0.0),
                            "client_id": client_id, "mode": mode, "status": "open", "filled": 0.0, "polls": 0,
                            "fills": [], "created_mono": self.clock.monotonic()}
        self.by_client[client_id] = oid
        self._save()
        return oid

    def _to_order(self, st: dict) -> Order:
        fee = None if st["mode"] == "fee_unknown" else round(sum(f["qty"] * f["price"] for f in st["fills"]) * self.fee_bps / 10_000, 8)
        avg = (sum(f["qty"] * f["price"] for f in st["fills"]) / st["filled"]) if st["filled"] > 0 else None
        raw = {"fills": [dict(f, fee_usd=None if fee is None else f["qty"] * f["price"] * self.fee_bps / 10_000) for f in st["fills"]]}
        return Order(st["id"], st["symbol"], st["side"], st["status"], st["filled"], avg, fee, st["client_id"], raw)

    def _fill(self, st, qty, fill_id=None):
        fid = fill_id or f"{st['id']}-f{len(st['fills']) + 1}"
        st["fills"].append({"id": fid, "qty": qty, "price": st["price"] or 1.0})
        st["filled"] = sum(f["qty"] for f in st["fills"])

    # ---------- BrokerPort ----------
    def create_order(self, symbol, side, amount_base, order_type, price, client_id) -> Order:
        self.calls.append(("create", client_id))
        mode = self.mode_for(client_id)
        if mode == "reject":
            raise BrokerRejected(f"fake reject for {client_id}")
        if mode == "timeout_lost":
            raise OrderMaybeSent(client_id, "network timeout; broker never received it")
        oid = self._new(symbol, side, amount_base, price, client_id, mode)
        if mode == "timeout":
            raise OrderMaybeSent(client_id, "network timeout after send")
        if mode == "silent_reject":
            st = self.orders[oid]
            st["status"] = "closed"
            self._save()
        return self._to_order(self.orders[oid])

    def fetch_order(self, order_id, symbol) -> Order:
        self.calls.append(("fetch", order_id))
        st = self.orders.get(order_id)
        if st is None:
            return Order(order_id, symbol, "buy", "unknown", 0.0, None, None)
        mode = st["mode"]
        st["polls"] += 1
        if mode == "disconnect" and not self._once.get(order_id):
            self._once[order_id] = True
            self._save()
            raise ConnectionError("socket closed mid-call")
        if mode == "garbage":
            self._save()
            return Order(st["id"], st["symbol"], st["side"], "weird-status", st["filled"], None, None, st["client_id"])
        if st["status"] == "open" and st["polls"] >= self.fill_after_polls:
            if mode in ("ok", "disconnect", "fee_unknown", "timeout", "cancel_fails", "cancel_ignored"):
                if mode in ("cancel_fails", "cancel_ignored"):
                    pass  # stays open so the executor reaches the cancel path
                else:
                    self._fill(st, st["req"])
                    st["status"] = "closed"
            elif mode == "partial":
                if not st["fills"]:
                    self._fill(st, st["req"] * 0.4)
            elif mode == "duplicate_fill":
                if not st["fills"]:
                    self._fill(st, st["req"], fill_id="DUP-1")
                    st["fills"].append(dict(st["fills"][0]))          # same fill id twice
                    st["filled"] = sum(f["qty"] for f in st["fills"])   # broker double-counts too
                    st["status"] = "closed"
            elif mode == "overfill":
                self._fill(st, st["req"] * 1.5, fill_id="OVR-1")
                st["status"] = "closed"
            elif mode == "out_of_order":
                # first fetch reports closed+filled, second reports a stale "open" with 0 filled
                if st["polls"] == 1:
                    st["filled"] = st["req"]
                    st["fills"] = [{"id": "OOO-1", "qty": st["req"], "price": st["price"] or 1.0}]
                    st["status"] = "closed"
                    self._save()
                    return self._to_order(st)
                self._save()
                return Order(st["id"], st["symbol"], st["side"], "open", 0.0, None, None, st["client_id"])
        self._save()
        return self._to_order(st)

    def cancel_order(self, order_id, symbol) -> Order:
        self.calls.append(("cancel", order_id))
        st = self.orders.get(order_id)
        if st is None:
            return Order(order_id, symbol, "buy", "unknown", 0.0, None, None)   # G7
        if st["mode"] == "cancel_fails":
            raise ConnectionError("cancel rejected: gateway timeout")
        if st["mode"] == "cancel_ignored":
            return Order(st["id"], st["symbol"], st["side"], "canceled", st["filled"], None, None, st["client_id"])
        if st["status"] == "open":
            st["status"] = "canceled"
        self._save()
        return self._to_order(st)   # G6: cancelling a filled order returns closed

    def fetch_open_orders(self, symbol) -> list[Order]:
        self.calls.append(("open_orders", symbol))
        return [self._to_order(st) for st in self.orders.values() if st["symbol"] == symbol and st["status"] == "open"]

    def fetch_order_by_client_id(self, client_id, symbol) -> Optional[Order]:
        self.calls.append(("by_client", client_id))
        oid = self.by_client.get(client_id)
        return None if oid is None else self.fetch_order(oid, symbol)   # G9: None is authoritative here

    # ---------- test helpers ----------
    def inject_foreign_open_order(self, symbol, side, qty, price=1.0, client_id=None) -> str:
        oid = self._new(symbol, side, qty, price, client_id or f"foreign-{self._seq + 1}", "never_fills")
        return oid
