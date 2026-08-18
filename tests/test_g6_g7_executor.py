"""G6 - honest post-fill state machine; G7 - detect => act (halts, reconcile).
Every wait goes through FakeClock via the injected sleeper. No time.sleep."""
import json

import pytest

from deadman import (HonestExecutor, KillSwitch, EntryHalt, DailyLimits, Limits, OrderSanity, Ledger,
                     Intent, spot_long_only_is_exit, client_order_id_for, WriterIdentity, PositionSnapshot)
from deadman.errors import ConcurrentWriterDetected
from fake_broker import FakeBroker

MKT = dict(broker_status="connected", latency_ms=20.0, bid=99.9, ask=100.1, size_available=10_000.0)


def mk(side="buy", cid="c1", amount=100.0, units="USD"):
    return Intent("BTC/USD", side, units, amount, "ENTRY" if side == "buy" else "EXIT", cid)


def rows(paths):
    return [json.loads(l) for l in open(paths.ledger_file, encoding="utf-8") if l.strip()]


def kinds(paths):
    return [r["kind"] for r in rows(paths)]


def build(paths, clock, ident, broker, *, ledger=None, limits=None, sanity=None, fill_timeout=5.0, poll=1.0, started=True):
    ledger = ledger or Ledger(paths, clock)
    kill = KillSwitch(paths, ledger)
    halt = EntryHalt(paths, clock, ident, ledger)
    limits = limits or DailyLimits(paths, Limits(max_trades_per_day=100, max_daily_loss_usd=10_000.0, worst_case_fee_bps=100.0),
                                   spot_long_only_is_exit, clock, ident, ledger)
    sanity = sanity or OrderSanity(frozenset({"BTC/USD"}), max_latency_ms=500.0, max_spread_bps=100.0)
    ex = HonestExecutor(broker, kill, halt, limits, sanity, ledger, spot_long_only_is_exit, clock,
                        fill_timeout_s=fill_timeout, poll_interval_s=poll, sleeper=lambda s: clock.advance(seconds=s))
    if started:
        ex.startup(["BTC/USD"], lambda s: None)
    return ex, kill, halt, limits, ledger


# ======================= G6 =======================

def test_g6_1_full_fill_is_filled_with_fee_and_ledgered(paths, clock, ident):
    br = FakeBroker(clock, fill_after_polls=2)
    ex, *_ = build(paths, clock, ident, br)
    r = ex.execute(mk(), 100.0, **MKT)
    assert r.status == "FILLED" and r.filled_base == pytest.approx(1.0) and r.avg_price == 100.0
    assert r.fees_usd == pytest.approx(0.1) and r.order_id and r.client_order_id == client_order_id_for(mk())
    ks = kinds(paths)
    i_wa = ks.index("ORDER_SENT")
    assert ks[i_wa:] == ["ORDER_SENT", "ORDER_SENT", "FILL"]  # write_ahead, acked, fill
    stages = [r_["payload"]["stage"] for r_ in rows(paths) if r_["kind"] == "ORDER_SENT"]
    assert stages == ["write_ahead", "acked"]


def test_g6_2_write_ahead_precedes_the_network(paths, clock, ident):
    br = FakeBroker(clock)
    seen = {}
    real_create = br.create_order

    def spy(*a, **k):
        seen["ledger_at_send"] = kinds(paths)
        return real_create(*a, **k)
    br.create_order = spy
    ex, *_ = build(paths, clock, ident, br)
    ex.execute(mk(), 100.0, **MKT)
    assert seen["ledger_at_send"][-1] == "ORDER_SENT"
    assert [r_ for r_ in rows(paths) if r_["kind"] == "ORDER_SENT"][0]["payload"]["stage"] == "write_ahead"


def test_g6_3_partial_fill_is_partial_never_rounded_up(paths, clock, ident):
    br = FakeBroker(clock, default_mode="partial")
    ex, *_ = build(paths, clock, ident, br, fill_timeout=3.0, poll=1.0)
    r = ex.execute(mk(), 100.0, **MKT)
    assert r.status == "PARTIAL" and r.code == "PARTIAL_FILL" and r.filled_base == pytest.approx(0.4)
    fill = [x for x in rows(paths) if x["kind"] == "PARTIAL_FILL"][0]["payload"]
    assert fill["filled_base"] == pytest.approx(0.4) and fill["requested_base"] == pytest.approx(1.0) and fill["via"] == "cancel_reread"


def test_g6_4_timeout_no_fill_is_canceled_and_not_a_trade(paths, clock, ident):
    br = FakeBroker(clock, default_mode="never_fills")
    ex, _, _, limits, _ = build(paths, clock, ident, br, fill_timeout=3.0, poll=1.0)
    r = ex.execute(mk(), 100.0, **MKT)
    assert r.status == "NO_FILL_CANCELED" and r.code == "TIMEOUT_NO_FILL_CANCELED" and r.filled_base == 0
    assert ("cancel", r.order_id) in br.calls
    assert limits.stats().trades == 0                       # not a trade
    assert "NO_FILL_CANCELED" in kinds(paths)


def test_g6_5_broker_reject_before_acceptance_is_denied_nothing_to_reconcile(paths, clock, ident):
    br = FakeBroker(clock, default_mode="reject")
    ex, _, halt, _, _ = build(paths, clock, ident, br)
    r = ex.execute(mk(), 100.0, **MKT)
    assert r.status == "DENIED" and r.code == "BROKER_REJECTED"
    assert halt.active() is None and ex.pending() == {}


def test_g6_6_timeout_on_send_presumes_alive_and_recovers_by_client_id(paths, clock, ident):
    """The real bug: order alive with no owner after a timeout. Presumed ALIVE."""
    br = FakeBroker(clock, default_mode="timeout", fill_after_polls=1)
    ex, *_ = build(paths, clock, ident, br)
    r = ex.execute(mk(), 100.0, **MKT)
    assert r.status == "FILLED"
    stages = [x["payload"]["stage"] for x in rows(paths) if x["kind"] == "ORDER_SENT"]
    assert stages == ["write_ahead", "sent_no_ack", "acked"]
    assert br.calls.count(("create", client_order_id_for(mk()))) == 1   # never re-sent


def test_g6_7_timeout_lost_authoritative_none_is_denied_not_unknown(paths, clock, ident):
    br = FakeBroker(clock, default_mode="timeout_lost")
    ex, _, halt, _, _ = build(paths, clock, ident, br)
    r = ex.execute(mk(), 100.0, **MKT)
    assert r.status == "DENIED" and r.code == "BROKER_NEVER_ACCEPTED" and halt.active() is None


def test_g6_8_unexpected_exception_on_send_with_no_lookup_is_unknown(paths, clock, ident):
    br = FakeBroker(clock)
    br.create_order = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("weird gateway"))
    ex, _, halt, _, _ = build(paths, clock, ident, br)
    r = ex.execute(mk(), 100.0, **MKT)
    assert r.status == "UNKNOWN" and halt.active() is not None and halt.active().auto_clear is True
    assert "UNKNOWN_STATE" in kinds(paths)


@pytest.mark.parametrize("mode", ["garbage", "silent_reject", "cancel_fails", "cancel_ignored", "overfill"])
def test_g6_9_out_of_machine_responses_are_unknown_plus_auto_halt(paths, clock, ident, mode):
    br = FakeBroker(clock, default_mode=mode)
    ex, _, halt, _, _ = build(paths, clock, ident, br, fill_timeout=2.0, poll=1.0)
    r = ex.execute(mk(), 100.0, **MKT)
    assert r.status == "UNKNOWN", mode
    h = halt.active()
    assert h is not None and h.auto_clear is True and "ORDER_STATE_UNKNOWN" in h.reason
    assert kinds(paths).count("UNKNOWN_STATE") == 1
    # entries now blocked, exits still pass through the halt gate (they may hit sanity later)
    r2 = ex.execute(mk(cid="c2"), 100.0, **MKT)
    assert r2.code == "ENTRY_HALT_ACTIVE"


def test_g6_10_disconnect_mid_fetch_is_unknown_not_retried_blindly(paths, clock, ident):
    br = FakeBroker(clock, default_mode="disconnect", fill_after_polls=2)
    ex, _, halt, _, _ = build(paths, clock, ident, br)
    r = ex.execute(mk(), 100.0, **MKT)
    assert r.status == "UNKNOWN" and halt.active() is not None
    assert br.calls.count(("create", client_order_id_for(mk()))) == 1


def test_g6_11_duplicate_fill_counted_once_and_noted(paths, clock, ident):
    br = FakeBroker(clock, default_mode="duplicate_fill")
    ex, _, _, limits, _ = build(paths, clock, ident, br)
    r = ex.execute(mk(), 100.0, **MKT)
    assert r.status == "FILLED" and r.filled_base == pytest.approx(1.0)
    fill = [x for x in rows(paths) if x["kind"] == "FILL"][0]["payload"]
    assert fill["duplicate_fill_ids_ignored"] == ["DUP-1"] and fill["filled_base"] == pytest.approx(1.0)
    assert limits.stats().filled_usd == pytest.approx(100.0)


def test_g6_12_out_of_order_stale_callback_does_not_unfill(paths, clock, ident):
    br = FakeBroker(clock, default_mode="out_of_order")
    ex, *_ = build(paths, clock, ident, br)
    r = ex.execute(mk(), 100.0, **MKT)
    assert r.status == "FILLED" and r.filled_base == pytest.approx(1.0)


def test_g6_13_fee_unknown_is_reported_none_and_day_marked(paths, clock, ident):
    br = FakeBroker(clock, default_mode="fee_unknown")
    lim = DailyLimits(paths, Limits(max_daily_loss_usd=1000.0), spot_long_only_is_exit, clock, ident)   # no worst case
    ex, *_ = build(paths, clock, ident, br, limits=lim)
    r = ex.execute(mk(), 100.0, **MKT)
    assert r.status == "FILLED" and r.fees_usd is None
    assert lim.stats().fees_unverified is True
    assert ex.execute(mk(cid="c2"), 100.0, **MKT).code == "DAILY_FEES_UNVERIFIED"


def test_g6_14_duplicate_in_flight_is_denied_no_blind_retry(paths, clock, ident):
    br = FakeBroker(clock, default_mode="cancel_fails")
    ex, *_ = build(paths, clock, ident, br, fill_timeout=1.0, poll=1.0)
    r1 = ex.execute(mk(), 100.0, **MKT)
    assert r1.status == "UNKNOWN"
    # same intent again: terminal (UNKNOWN is terminal for the executor) but the halt blocks entries;
    # use an exit-side intent to bypass the halt and prove idempotency on a NON-terminal record
    ex._index[client_order_id_for(mk(side="sell", cid="s1"))] = {"stage": "acked", "order_id": "O9", "terminal": False, "symbol": "BTC/USD",
                                                                 "side": "sell", "is_exit": True, "requested_base": 1.0, "intent": None}
    r2 = ex.execute(mk(side="sell", cid="s1"), 100.0, **MKT)
    assert r2.status == "DENIED" and r2.code == "DUPLICATE_IN_FLIGHT"
    assert ("create", client_order_id_for(mk(side="sell", cid="s1"))) not in br.calls


def test_g6_15_fixed_order_of_checks(paths, clock, ident):
    br = FakeBroker(clock)
    ex, kill, halt, _, _ = build(paths, clock, ident, br)
    kill.engage("test")
    assert ex.execute(mk(side="sell"), 100.0, **MKT).code == "KILL_SWITCH_ACTIVE"      # 1: exits too
    kill.release("t")
    halt.set("x", "t")
    assert ex.execute(mk(), 100.0, **MKT).code == "ENTRY_HALT_ACTIVE"                   # 3
    assert ex.execute(mk(side="sell", units="BASE", amount=0.5), 100.0, **MKT).status == "FILLED"  # exit passes the halt
    halt.clear("t")
    assert ex.execute(mk(cid="c9", units="CONTRACTS", amount=1), 100.0, **MKT).code == "CONTRACT_SIZE_MISSING"   # 4
    bad = dict(MKT, broker_status="down")
    assert ex.execute(mk(cid="c8"), 100.0, **bad).code == "BROKER_NOT_CONNECTED"        # 6
    sent_cids = {r_["payload"].get("intent", {}).get("client_id") for r_ in rows(paths) if r_["kind"] == "ORDER_SENT" and r_["payload"].get("stage") == "write_ahead"}
    assert not ({"c8", "c9"} & sent_cids)   # denied before write-ahead: nothing sent


def test_g6_16_execute_before_startup_is_denied(paths, clock, ident):
    br = FakeBroker(clock)
    ex, *_ = build(paths, clock, ident, br, started=False)
    assert ex.execute(mk(), 100.0, **MKT).code == "STARTUP_RECONCILE_REQUIRED"


def test_g6_17_ledger_failure_before_send_sends_nothing_and_halts_manually(paths, clock, ident):
    br = FakeBroker(clock)
    ex, _, halt, _, ledger = build(paths, clock, ident, br)
    real = ledger.append

    def failing(kind, payload, actor="user"):
        if kind == "ORDER_SENT":
            raise OSError("disk full")
        return real(kind, payload, actor)
    ledger.append = failing
    r = ex.execute(mk(), 100.0, **MKT)
    assert r.status == "DENIED" and r.code == "LEDGER_WRITE_FAILED"
    assert not any(c[0] == "create" for c in br.calls)
    h = halt.active()
    assert h is not None and h.auto_clear is False


# ======================= G7 =======================

def test_g7_1_startup_resolves_write_ahead_never_sent(paths, clock, ident):
    br = FakeBroker(clock)
    ledger = Ledger(paths, clock)
    coid = client_order_id_for(mk())
    ledger.append("ORDER_SENT", {"stage": "write_ahead", "client_order_id": coid, "symbol": "BTC/USD", "side": "buy",
                                 "is_exit": False, "requested_base": 1.0, "intent": mk().as_dict()}, actor="deadman.executor")
    ex, _, halt, _, _ = build(paths, clock, ident, br, ledger=ledger, started=False)
    rep = ex.startup(["BTC/USD"], lambda s: None)
    assert rep.pending_seen == 1 and rep.resolved == [{"client_order_id": coid, "resolution": "never_sent"}]
    assert rep.halt_set and halt.active().auto_clear is True
    assert ex.pending() == {}
    # second startup with a clean book clears the auto halt
    rep2 = ex.startup(["BTC/USD"], lambda s: None)
    assert rep2.pending_seen == 0 and rep2.halt_cleared and halt.active() is None


def test_g7_2_startup_finds_acked_open_entry_and_cancels_it(paths, clock, ident):
    br = FakeBroker(clock, default_mode="never_fills")
    ledger = Ledger(paths, clock)
    coid = client_order_id_for(mk())
    br.create_order("BTC/USD", "buy", 1.0, "limit", 100.0, coid)       # exists at the broker
    oid = br.by_client[coid]
    ledger.append("ORDER_SENT", {"stage": "acked", "client_order_id": coid, "order_id": oid, "symbol": "BTC/USD", "side": "buy",
                                 "is_exit": False, "requested_base": 1.0, "intent": mk().as_dict()}, actor="deadman.executor")
    ex, *_ = build(paths, clock, ident, br, ledger=ledger, started=False)
    rep = ex.startup(["BTC/USD"], lambda s: None)
    assert coid in rep.canceled and ("cancel", oid) in br.calls
    assert "NO_FILL_CANCELED" in kinds(paths) and rep.halt_set


def test_g7_3_startup_leaves_open_exit_alone(paths, clock, ident):
    br = FakeBroker(clock, default_mode="never_fills")
    ledger = Ledger(paths, clock)
    coid = client_order_id_for(mk(side="sell"))
    br.create_order("BTC/USD", "sell", 1.0, "limit", 100.0, coid)
    ledger.append("ORDER_SENT", {"stage": "acked", "client_order_id": coid, "order_id": br.by_client[coid], "symbol": "BTC/USD",
                                 "side": "sell", "is_exit": True, "requested_base": 1.0, "intent": mk(side="sell").as_dict()}, actor="deadman.executor")
    ex, *_ = build(paths, clock, ident, br, ledger=ledger, started=False)
    rep = ex.startup(["BTC/USD"], lambda s: None)
    assert rep.left_open == [coid] and not any(c[0] == "cancel" for c in br.calls)
    assert coid in ex.pending()      # still live, still tracked


def test_g7_4_foreign_open_order_is_unknown_and_halts(paths, clock, ident):
    br = FakeBroker(clock)
    oid = br.inject_foreign_open_order("BTC/USD", "buy", 2.0)
    ex, _, halt, _, _ = build(paths, clock, ident, br, started=False)
    rep = ex.startup(["BTC/USD"], lambda s: None)
    assert oid in rep.unknown and oid in rep.canceled            # adds exposure -> canceled AND unknown
    h = halt.active()
    assert h is not None and h.auto_clear is True
    assert "UNKNOWN_STATE" in kinds(paths)


def test_g7_4b_foreign_open_exit_is_left_but_still_unknown(paths, clock, ident):
    br = FakeBroker(clock)
    oid = br.inject_foreign_open_order("BTC/USD", "sell", 2.0)
    ex, *_ = build(paths, clock, ident, br, started=False)
    rep = ex.startup(["BTC/USD"], lambda s: PositionSnapshot(s, 5.0, "t"))
    assert oid in rep.unknown and oid not in rep.canceled


def test_g7_5_startup_error_per_symbol_does_not_clear_halt(paths, clock, ident):
    br = FakeBroker(clock)
    ex, _, halt, _, _ = build(paths, clock, ident, br, started=False)
    halt.set("prior", "t", auto_clear=True)
    br.fetch_open_orders = lambda s: (_ for _ in ()).throw(ConnectionError("down"))
    rep = ex.startup(["BTC/USD"], lambda s: None)
    assert rep.errors and not rep.halt_cleared and halt.active() is not None


def test_g7_6_startup_pending_lookup_failure_is_unknown(paths, clock, ident):
    br = FakeBroker(clock)
    ledger = Ledger(paths, clock)
    coid = client_order_id_for(mk())
    ledger.append("ORDER_SENT", {"stage": "sent_no_ack", "client_order_id": coid, "symbol": "BTC/USD", "side": "buy",
                                 "is_exit": False, "requested_base": 1.0, "intent": mk().as_dict()}, actor="deadman.executor")
    br.fetch_order_by_client_id = lambda c, s: (_ for _ in ()).throw(ConnectionError("down"))
    ex, _, halt, _, _ = build(paths, clock, ident, br, ledger=ledger, started=False)
    rep = ex.startup(["BTC/USD"], lambda s: None)
    assert coid in rep.unknown and halt.active() is not None and "UNKNOWN_STATE" in kinds(paths)


def test_g7_7_concurrent_writer_on_stats_during_fill_escalates_to_manual_halt(paths, clock, ident):
    br = FakeBroker(clock)
    ex, _, halt, limits, _ = build(paths, clock, ident, br)
    other = WriterIdentity(clock, pid=2000, pid_alive=lambda p: True)
    lim2 = DailyLimits(paths, Limits(), spot_long_only_is_exit, clock, other)
    snap = limits._load()
    limits._load = lambda: snap
    lim2.record_fill(mk(cid="x"), 1.0, 0.0)
    r = ex.execute(mk(), 100.0, **MKT)
    assert r.status == "FILLED"                                # the fill is never hidden
    h = halt.active()
    assert h is not None and h.auto_clear is False and "CONCURRENT_WRITER_DETECTED" in h.reason
