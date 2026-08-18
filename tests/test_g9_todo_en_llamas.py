"""G9 - "todo en llamas": the FakeBroker failing every way at once, plus a REAL
process killed mid-send and restarted with startup() reconcile. Properties, not
steps: no fill lost, no order sent twice, every final state explicable from the
ledger alone, and the run ends in an explicit halt - never a guess."""
import json
import os
import subprocess
import sys

import pytest

from deadman import (HonestExecutor, KillSwitch, EntryHalt, DailyLimits, Limits, OrderSanity, Ledger,
                     Intent, spot_long_only_is_exit, client_order_id_for, WriterIdentity, Paths, FakeClock)
from fake_broker import FakeBroker

MKT = dict(broker_status="connected", latency_ms=20.0, bid=99.9, ask=100.1, size_available=10_000.0)
TERMINAL = ("FILL", "PARTIAL_FILL", "NO_FILL_CANCELED", "UNKNOWN_STATE")


def rows(paths):
    out = []
    n = 1
    segs = []
    while paths.segment(n).exists():
        segs.append(paths.segment(n)); n += 1
    segs.append(paths.ledger_file)
    for p in segs:
        out += [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]
    return out


def mk(side, cid, amount=100.0):
    return Intent("BTC/USD", side, "USD", amount, "ENTRY" if side == "buy" else "EXIT", cid)


def explain(rws):
    """Rebuild per-client_order_id state from the ledger alone."""
    st = {}
    for r in rws:
        pl = r.get("payload") or {}
        coid = pl.get("client_order_id")
        if not coid:
            continue
        s = st.setdefault(coid, {"stages": [], "terminals": [], "order_id": None, "filled": 0.0})
        if r["kind"] == "ORDER_SENT":
            s["stages"].append(pl["stage"])
            s["order_id"] = pl.get("order_id") or s["order_id"]
        elif r["kind"] in TERMINAL:
            s["terminals"].append(r["kind"])
            s["order_id"] = pl.get("order_id") or s["order_id"]
            s["filled"] += float(pl.get("filled_base") or 0.0)
        elif r["kind"] == "INTENT_DENIED" and pl.get("terminal_for_client_order_id"):
            s["terminals"].append("INTENT_DENIED:" + pl["code"])
        elif r["kind"] == "RECONCILE_REPORT" and pl.get("terminal"):
            s["terminals"].append("RECONCILE:" + str(pl.get("resolution")))
    return st


# ---------------------------------------------------------------- A: everything at once, in-process
def test_g9_1_everything_fails_at_once_properties(paths, clock, ident):
    modes = ["ok", "partial", "never_fills", "reject", "timeout", "timeout_lost", "duplicate_fill",
             "out_of_order", "fee_unknown", "disconnect", "garbage", "cancel_fails", "overfill",
             "cancel_ignored", "silent_reject", "ok"]
    intents = [mk("buy", f"e{i}") for i in range(len(modes))]
    plan = {client_order_id_for(it): m for it, m in zip(intents, modes)}
    br = FakeBroker(clock, plan=plan, fill_after_polls=1)
    br.inject_foreign_open_order("BTC/USD", "buy", 3.0)          # somebody else's live order
    ledger = Ledger(paths, clock, publisher=lambda d: "ref")     # anchoring on, forced after halts
    kill = KillSwitch(paths, ledger)
    halt = EntryHalt(paths, clock, ident, ledger)
    limits = DailyLimits(paths, Limits(max_trades_per_day=1000, max_daily_loss_usd=1e9, worst_case_fee_bps=100.0),
                         spot_long_only_is_exit, clock, ident, ledger)
    sanity = OrderSanity(frozenset({"BTC/USD"}), 500.0, 100.0)
    ex = HonestExecutor(br, kill, halt, limits, sanity, ledger, spot_long_only_is_exit, clock,
                        fill_timeout_s=3.0, poll_interval_s=1.0, sleeper=lambda s: clock.advance(seconds=s))
    rep = ex.startup(["BTC/USD"], lambda s: None)
    assert rep.unknown and halt.active() is not None            # the foreign order already halted entries
    # entries are halted by the foreign order: to exercise the machine we clear it explicitly (ledgered) once
    assert halt.clear("test: operator acknowledged foreign order")
    results = []
    for it in intents:
        results.append((it, ex.execute(it, 100.0, **MKT)))
        # sprinkle exits between failures: they must keep passing the halt gate
        results.append((mk("sell", "x" + it.client_id, 10.0), ex.execute(mk("sell", "x" + it.client_id, 10.0), 100.0, **MKT)))
    # then corrupt the stats file and pull the kill switch: the world is on fire
    paths.daily_stats.write_text("{corrupt", encoding="utf-8")
    assert ex.execute(mk("buy", "after-corrupt"), 100.0, **MKT).code in ("ENTRY_HALT_ACTIVE", "DAILY_STATS_UNREADABLE")
    kill.engage("fire drill")
    assert ex.execute(mk("sell", "after-kill", 10.0), 100.0, **MKT).code == "KILL_SWITCH_ACTIVE"

    rws = rows(paths)
    st = explain(rws)
    # P1: every order that reached the broker (acked or sent_no_ack) has EXACTLY ONE terminal, explicable from the ledger
    reached = {c for c, s in st.items() if any(x in ("acked", "sent_no_ack") for x in s["stages"])}
    assert reached, "nothing reached the broker?"
    for c in reached:
        assert len(st[c]["terminals"]) == 1, (c, st[c])
    # P2: no order sent twice - one create per client id at the broker, one 'acked' per coid in the ledger
    creates = [c for k, c in br.calls if k == "create"]
    assert len(creates) == len(set(creates))
    for c, s in st.items():
        assert s["stages"].count("acked") <= 1, (c, s)
    # P3: no fill lost, none double counted: ledger fills == broker's UNIQUE fills for the same orders
    ledger_filled = {s["order_id"]: s["filled"] for s in st.values() if s["order_id"] and s["filled"] > 0}
    for oid, filled in ledger_filled.items():
        bs = br.orders[oid]
        uniq = {f["id"]: f["qty"] for f in bs["fills"]}
        assert filled == pytest.approx(sum(uniq.values())), (oid, filled, bs["fills"])
    broker_filled_orders = {oid for oid, s_ in br.orders.items() if s_["filled"] > 0 and s_["mode"] not in ("overfill",)}
    known_terminal_orders = {s["order_id"] for s in st.values() if s["terminals"]}
    assert broker_filled_orders <= known_terminal_orders | {oid for oid, s_ in br.orders.items() if s_["client_id"].startswith("foreign")}
    # P4: every ExecResult is explicable from the ledger
    for it, r in results:
        coid = client_order_id_for(it)
        if r.status in ("FILLED", "PARTIAL"):
            assert st[coid]["terminals"] == [("FILL" if r.status == "FILLED" else "PARTIAL_FILL")], (it.client_id, r)
            assert st[coid]["filled"] == pytest.approx(r.filled_base)
        elif r.status == "NO_FILL_CANCELED":
            assert st[coid]["terminals"] == ["NO_FILL_CANCELED"]
        elif r.status == "UNKNOWN":
            assert st[coid]["terminals"] == ["UNKNOWN_STATE"]
        elif r.status == "DENIED":
            assert any(x["kind"] == "INTENT_DENIED" and x["payload"]["intent"]["client_id"] == it.client_id and x["payload"]["code"] == r.code for x in rws), (it.client_id, r)
    # P5: partial is partial, duplicate counted once, out-of-order filled once
    by_cid = {it.client_id: r for it, r in results}
    assert by_cid["e1"].status == "PARTIAL" and by_cid["e1"].filled_base == pytest.approx(0.4)
    assert by_cid["e6"].status in ("FILLED", "DENIED") and (by_cid["e6"].status == "DENIED" or by_cid["e6"].filled_base == pytest.approx(1.0))
    # P6: it ends in an explicit halt, never a guess: entry halt active with a reason, kill sentinel present,
    #     and the last unknown is anchored (forced) - the ledger says why
    h = halt.active()
    assert h is not None and "ORDER_STATE_UNKNOWN" in h.reason
    assert paths.kill_sentinel.exists()
    ks = [r_["kind"] for r_ in rws]
    # the halt is STICKY: after the first UNKNOWN (disconnect, e9) no later entry reaches the broker -
    # garbage/cancel_fails/overfill/cancel_ignored/silent_reject were all denied ENTRY_HALT_ACTIVE, never created
    assert ks.count("UNKNOWN_STATE") == 2          # foreign order at startup + the disconnect
    for cid in ("e10", "e11", "e12", "e13", "e14", "e15"):
        assert by_cid[cid].status == "DENIED" and by_cid[cid].code == "ENTRY_HALT_ACTIVE", (cid, by_cid[cid])
        assert ("create", client_order_id_for(mk("buy", cid))) not in br.calls
    assert "KILL_ENGAGED" in ks and "HALT_SET" in ks
    assert "ANCHOR_PUBLISHED" in ks and ledger.verify().ok
    # P7: exits kept flowing while entries were halted (at least one sell filled after the first UNKNOWN)
    first_unknown = ks.index("UNKNOWN_STATE")
    sells_after = [x for x in rws[first_unknown:] if x["kind"] == "FILL" and x["payload"]["side"] == "sell"]
    assert sells_after, "exits must not be trapped by the halt"


# ---------------------------------------------------------------- B: real process killed mid-send, restart, reconcile
WORKER = r'''
import os, sys, json
sys.path.insert(0, sys.argv[1]); sys.path.insert(0, os.path.join(sys.argv[1], "tests"))
from datetime import datetime, timezone
from deadman import *
from fake_broker import FakeBroker
root, store = sys.argv[2], sys.argv[3]
clock = FakeClock(datetime(2026, 8, 18, 12, 0, tzinfo=timezone.utc))
paths = Paths(root); ident = WriterIdentity(clock)
class HangingBroker(FakeBroker):
    def create_order(self, symbol, side, amount_base, order_type, price, client_id):
        o = super().create_order(symbol, side, amount_base, order_type, price, client_id)   # accepted at the broker
        st = self.orders[o.id]; self._fill(st, st["req"] * 0.4); self._save()               # partially filled already
        print("SENT " + o.id, flush=True)
        while not os.path.exists(store + ".release"):   # hang mid-send until killed (no sleep: busy wait)
            pass
        return o
br = HangingBroker(clock, default_mode="never_fills", store_path=store)
ledger = Ledger(paths, clock); kill = KillSwitch(paths, ledger); halt = EntryHalt(paths, clock, ident, ledger)
limits = DailyLimits(paths, Limits(worst_case_fee_bps=100.0), spot_long_only_is_exit, clock, ident, ledger)
sanity = OrderSanity(frozenset({"BTC/USD"}), 500.0, 100.0)
ex = HonestExecutor(br, kill, halt, limits, sanity, ledger, spot_long_only_is_exit, clock, 5.0, 1.0, sleeper=lambda s: clock.advance(seconds=s))
ex.startup(["BTC/USD"], lambda s: None)
ex.execute(Intent("BTC/USD", "buy", "USD", 100.0, "ENTRY", "killed-mid-send"), 100.0, broker_status="connected", latency_ms=1.0, bid=99.9, ask=100.1, size_available=1e6)
'''


def test_g9_2_real_process_killed_mid_send_then_restart_reconciles(tmp_path):
    root = str(tmp_path / "state")
    store = str(tmp_path / "broker.json")
    pkg = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    script = tmp_path / "worker.py"
    script.write_text(WORKER, encoding="utf-8")
    p = subprocess.Popen([sys.executable, str(script), pkg, root, store], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    line = p.stdout.readline()          # blocks until the worker has persisted the order at the broker
    assert line.startswith("SENT "), (line, p.stderr.read())
    oid = line.split()[1]
    p.kill(); p.wait(timeout=60)        # killed with the order alive and partially filled, ledger at write_ahead

    paths = Paths(root)
    clock = FakeClock()
    ident = WriterIdentity(clock, pid=4242, pid_alive=lambda pid: False)   # the killed pid is dead
    ledger = Ledger(paths, clock)
    before = rows(paths)
    stages = [r["payload"]["stage"] for r in before if r["kind"] == "ORDER_SENT"]
    assert stages == ["write_ahead"]                        # crashed between write-ahead and ack
    br = FakeBroker(clock, default_mode="never_fills", store_path=store)   # same book, seen by the successor
    assert br.orders[oid]["filled"] == pytest.approx(0.4) and br.orders[oid]["status"] == "open"
    kill = KillSwitch(paths, ledger); halt = EntryHalt(paths, clock, ident, ledger)
    halt.startup_check()
    limits = DailyLimits(paths, Limits(worst_case_fee_bps=100.0), spot_long_only_is_exit, clock, ident, ledger)
    ex = HonestExecutor(br, kill, halt, limits, OrderSanity(frozenset({"BTC/USD"}), 500.0, 100.0), ledger,
                        spot_long_only_is_exit, clock, 5.0, 1.0, sleeper=lambda s: clock.advance(seconds=s))
    rep = ex.startup(["BTC/USD"], lambda s: None)
    coid = client_order_id_for(Intent("BTC/USD", "buy", "USD", 100.0, "ENTRY", "killed-mid-send"))
    # properties
    assert rep.pending_seen == 1 and coid in rep.canceled and rep.halt_set
    st = explain(rows(paths))[coid]
    assert st["terminals"] == ["PARTIAL_FILL"] and st["filled"] == pytest.approx(0.4)   # the fill was NOT lost
    assert br.orders[oid]["status"] == "canceled"
    assert not any(k == "create" for k, _ in br.calls)                                     # never re-sent
    assert limits.stats().filled_usd == pytest.approx(0.4 * 100.0) and limits.stats().trades == 1
    h = halt.active()
    assert h is not None and h.auto_clear is True                                          # explicit halt, not a guess
    # and the run is explicable from the ledger alone: write_ahead -> RECONCILE via reconcile_cancel -> PARTIAL_FILL -> HALT_SET
    ks = [r["kind"] for r in rows(paths)]
    assert ks.index("PARTIAL_FILL") > ks.index("ORDER_SENT") and "HALT_SET" in ks and "RECONCILE_REPORT" in ks
    fill = [r for r in rows(paths) if r["kind"] == "PARTIAL_FILL"][0]["payload"]
    assert fill["via"] == "reconcile_cancel" and fill["order_id"] == oid
    assert ledger.verify().ok
    # a second startup with the book now clean clears the auto halt and accepts intents again
    rep2 = ex.startup(["BTC/USD"], lambda s: None)
    assert rep2.pending_seen == 0 and rep2.halt_cleared and halt.active() is None
