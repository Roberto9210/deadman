"""Tests for the freqtrade integration that need neither freqtrade nor an
exchange: the gate is plain Python, and the callbacks are driven with the
smallest objects that carry the fields the code actually reads.

    python -m pytest -q examples/freqtrade/tests

What is NOT covered here, and is covered by `demo.py` instead: that freqtrade
really calls these callbacks, with these arguments, in this order. No fake can
prove that - only a run can.
"""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))  # deadman checkout
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # the example

from deadman import Limits, Paths, Ledger, SystemClock  # noqa: E402
from deadman_freqtrade import (  # noqa: E402
    DeadmanGate,
    DeadmanGuardMixin,
    DeclaredSpreadQuotes,
    FreqtradeClock,
    Quotes,
    QuotesNotConfigured,
)

PAIR = "BTC/USDT"
T0 = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


# --------------------------------------------------------------------------
# the smallest fakes that carry what the code reads
# --------------------------------------------------------------------------
class FakeOrder:
    def __init__(self, side, filled, price, amount=None, order_id="o1", status="closed",
                 order_type="limit", ft_fee_base=None):
        self.ft_order_side = side          # "buy" | "sell"
        self.safe_filled = filled
        self.safe_price = price
        self.safe_amount = amount if amount is not None else filled
        self.order_id = order_id
        self.status = status
        self.order_type = order_type
        self.ft_fee_base = ft_fee_base     # None unless the fee was paid in base


class FakeTrade:
    def __init__(self, pair=PAIR, open_rate=30_000.0, amount=0.003, fee_open=0.001, fee_close=0.001):
        self.pair = pair
        self.entry_side = "buy"
        self.exit_side = "sell"
        self.open_rate = open_rate
        self.amount = amount
        self.fee_open = fee_open
        self.fee_close = fee_close
        self.is_open = True
        self.exit_reason = "exit_signal"
        self.safe_base_currency = "BTC"


class FakeWallets:
    def __init__(self, free=None):
        self._free = free or {"USDT": 10_000.0, "BTC": 1.0}

    def get_free(self, currency):
        return self._free.get(currency, 0)   # freqtrade returns 0, not None


class FakeDp:
    runmode = "backtest"


class Strat(DeadmanGuardMixin):
    """A stand-in for `class X(DeadmanGuardMixin, IStrategy)` with only the
    attributes the mixin touches."""

    def __init__(self, gate, wallets=None):
        self._gate = gate
        self.config = {"stake_currency": "USDT"}
        self.wallets = wallets if wallets is not None else FakeWallets()
        self.dp = FakeDp()

    def deadman_build_gate(self):
        return self._gate


# --------------------------------------------------------------------------
def make_gate(tmp_path, **kw):
    kw.setdefault("limits", Limits(max_trades_per_day=10, max_daily_loss_usd=50.0,
                                   max_notional_usd_per_order=500.0, worst_case_fee_bps=80.0))
    kw.setdefault("allowed_pairs", [PAIR])
    kw.setdefault("quotes", DeclaredSpreadQuotes(spread_bps=4.0, latency_ms=25.0))
    kw.setdefault("max_latency_ms", 2000.0)
    kw.setdefault("max_spread_bps", 50.0)
    kw.setdefault("min_notional_usd", 10.0)
    clock = kw.pop("clock", None) or FreqtradeClock()
    if isinstance(clock, FreqtradeClock):
        clock.set(T0)          # as freqtrade would, from the callback's current_time
    return DeadmanGate(tmp_path / "state", clock=clock, **kw)


def ledger_rows(gate):
    f = gate.paths.ledger_file
    if not f.exists():
        return []
    return [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines() if x.strip()]


def kinds(gate):
    return [r["kind"] for r in ledger_rows(gate)]


def deny_codes(gate):
    return [r["payload"].get("code") for r in ledger_rows(gate) if r["kind"] == "INTENT_DENIED"]


# --------------------------------------------------------------------------
# construction
# --------------------------------------------------------------------------
def test_quotes_are_not_optional(tmp_path):
    """There is no default bid/ask. Refusing to build is the whole point."""
    with pytest.raises(QuotesNotConfigured):
        DeadmanGate(tmp_path / "s", limits=Limits(), allowed_pairs=[PAIR], quotes=None,
                    max_latency_ms=100.0, max_spread_bps=10.0)


def test_declared_spread_requires_both_numbers():
    with pytest.raises(TypeError):
        DeclaredSpreadQuotes(spread_bps=4.0)          # latency must be declared too
    with pytest.raises(ValueError):
        DeclaredSpreadQuotes(spread_bps=0.0, latency_ms=1.0)
    q = DeclaredSpreadQuotes(spread_bps=4.0, latency_ms=25.0)(PAIR, 100.0)
    assert q.source == "declared_spread_simulation"   # it says so in every ledger entry
    assert q.bid < 100.0 < q.ask


# --------------------------------------------------------------------------
# entries
# --------------------------------------------------------------------------
def test_clean_entry_is_allowed_and_ledgered(tmp_path):
    gate = make_gate(tmp_path)
    v = gate.entry_verdict(pair=PAIR, amount_base=0.003, rate=30_000.0,
                           size_available_quote=10_000.0, client_id="c1")
    assert v.allowed and v.code == "DEADMAN_ENTRY_OK"
    rows = ledger_rows(gate)
    assert [r["kind"] for r in rows] == ["ORDER_SENT"]
    pl = rows[0]["payload"]
    assert pl["stage"] == "gate_passed" and pl["is_exit"] is False
    # the checks that actually ran travel with the entry - a check that exists
    # is not a check that runs
    assert pl["checks_run"] == ["kill_switch", "entry_halt", "units", "daily_limits", "order_sanity"]
    assert pl["quote_source"] == "declared_spread_simulation"
    assert pl["placed_by"] == "freqtrade"       # deadman sent nothing


def test_sentinel_denies_entries(tmp_path):
    gate = make_gate(tmp_path)
    gate.kill.engage("test", actor="test")
    v = gate.entry_verdict(pair=PAIR, amount_base=0.003, rate=30_000.0,
                           size_available_quote=10_000.0, client_id="c1")
    assert not v.allowed and v.code == "KILL_SWITCH_ACTIVE"
    assert deny_codes(gate) == ["KILL_SWITCH_ACTIVE"]
    assert "ORDER_SENT" not in kinds(gate)


def test_entry_halt_denies_entries(tmp_path):
    gate = make_gate(tmp_path)
    gate.halt.set("unknown order state", source="test", auto_clear=True)
    v = gate.entry_verdict(pair=PAIR, amount_base=0.003, rate=30_000.0,
                           size_available_quote=10_000.0, client_id="c1")
    assert not v.allowed and v.code == "ENTRY_HALT_ACTIVE"


def test_missing_quote_input_denies_the_entry(tmp_path):
    """OrderSanity denies on a missing input; that is deadman's contract."""
    gate = make_gate(tmp_path, quotes=lambda pair, rate: Quotes(None, None, 5.0, "connected", "broken_feed"))
    v = gate.entry_verdict(pair=PAIR, amount_base=0.003, rate=30_000.0,
                           size_available_quote=10_000.0, client_id="c1")
    assert not v.allowed and v.code == "BID_MISSING"


def test_notional_below_minimum_is_denied_not_enlarged(tmp_path):
    gate = make_gate(tmp_path, min_notional_usd=100.0)
    v = gate.entry_verdict(pair=PAIR, amount_base=0.0001, rate=30_000.0,   # 3 USD
                           size_available_quote=10_000.0, client_id="c1")
    assert not v.allowed and v.code == "NOTIONAL_BELOW_MIN"


def test_unknown_pair_is_denied(tmp_path):
    gate = make_gate(tmp_path)
    v = gate.entry_verdict(pair="DOGE/USDT", amount_base=1.0, rate=1.0,
                           size_available_quote=10_000.0, client_id="c1")
    assert not v.allowed and v.code == "SYMBOL_NOT_ALLOWED"


def test_daily_limit_denies_and_is_ledgered_exactly_once(tmp_path):
    """DailyLimits writes its own INTENT_DENIED; the gate must not write a
    second one for the same denial."""
    gate = make_gate(tmp_path, limits=Limits(max_trades_per_day=1, worst_case_fee_bps=80.0))
    gate.record_fill(pair=PAIR, side="buy", is_exit=False, filled_base=0.003, price=30_000.0,
                     fee_usd=0.09, fee_source="test", requested_base=0.003, order_id="o1", client_id="c1")
    v = gate.entry_verdict(pair=PAIR, amount_base=0.003, rate=30_000.0,
                           size_available_quote=10_000.0, client_id="c2")
    assert not v.allowed and v.code == "DAILY_MAX_TRADES"
    assert deny_codes(gate) == ["DAILY_MAX_TRADES"]   # exactly one, not two


# --------------------------------------------------------------------------
# exits: the asymmetry
# --------------------------------------------------------------------------
def test_exit_is_not_blocked_by_halt_or_daily_limits(tmp_path):
    """The one that matters. Halt set, limit exhausted, stats file corrupted:
    the exit still goes."""
    gate = make_gate(tmp_path, limits=Limits(max_trades_per_day=1, worst_case_fee_bps=80.0))
    gate.record_fill(pair=PAIR, side="buy", is_exit=False, filled_base=0.003, price=30_000.0,
                     fee_usd=0.09, fee_source="test", requested_base=0.003, order_id="o1", client_id="c1")
    gate.halt.set("something unknown happened", source="test", auto_clear=False)
    gate.paths.daily_stats.write_text("{ this is not json", encoding="utf-8")

    assert not gate.entry_verdict(pair=PAIR, amount_base=0.003, rate=30_000.0,
                                  size_available_quote=10_000.0, client_id="c2").allowed
    v = gate.exit_verdict(pair=PAIR, amount_base=0.003, rate=30_100.0, exit_reason="exit_signal",
                          size_available_base=0.003, client_id="c3")
    assert v.allowed and v.code == "DEADMAN_EXIT_OK"
    sent = [r for r in ledger_rows(gate) if r["kind"] == "ORDER_SENT" and r["payload"]["is_exit"]]
    assert sent and sent[-1]["payload"]["not_consulted"] == ["entry_halt", "daily_limits", "order_sanity"]


def test_kill_switch_does_stop_exits_too(tmp_path):
    """deadman's decision A, stated rather than softened: the sentinel stops
    everything, and in freqtrade that means an open trade stays open."""
    gate = make_gate(tmp_path)
    gate.kill.engage("operator takes over", actor="test")
    v = gate.exit_verdict(pair=PAIR, amount_base=0.003, rate=30_100.0, exit_reason="stop_loss",
                          size_available_base=0.003, client_id="c1")
    assert not v.allowed and v.code == "KILL_SWITCH_ACTIVE"


def test_exit_sanity_is_opt_in(tmp_path):
    gate = make_gate(tmp_path, exit_sanity=True,
                     quotes=lambda pair, rate: Quotes(None, None, 5.0, "connected", "broken_feed"))
    v = gate.exit_verdict(pair=PAIR, amount_base=0.003, rate=30_100.0, exit_reason="exit_signal",
                          size_available_base=0.003, client_id="c1")
    assert not v.allowed and v.code == "BID_MISSING"     # opted in, so it can deny


# --------------------------------------------------------------------------
# fees and P&L
# --------------------------------------------------------------------------
def test_unknown_fee_is_never_zero(tmp_path):
    """No worst-case rate configured + a fill with no fee => the day is
    unverified and entries stop. The fee is not quietly 0."""
    gate = make_gate(tmp_path, limits=Limits(max_trades_per_day=10, worst_case_fee_bps=None))
    gate.record_fill(pair=PAIR, side="buy", is_exit=False, filled_base=0.003, price=30_000.0,
                     fee_usd=None, fee_source="unavailable", requested_base=0.003,
                     order_id="o1", client_id="c1")
    assert gate.stats().fees_unverified is True
    v = gate.entry_verdict(pair=PAIR, amount_base=0.003, rate=30_000.0,
                           size_available_quote=10_000.0, client_id="c2")
    assert not v.allowed and v.code == "DAILY_FEES_UNVERIFIED"


def test_worst_case_fee_is_charged_when_the_fee_is_unknown(tmp_path):
    gate = make_gate(tmp_path, limits=Limits(max_trades_per_day=10, worst_case_fee_bps=80.0))
    gate.record_fill(pair=PAIR, side="buy", is_exit=False, filled_base=0.003, price=30_000.0,
                     fee_usd=None, fee_source="unavailable", requested_base=0.003,
                     order_id="o1", client_id="c1")
    st = gate.stats()
    assert st.fees_unverified is False and st.fees_estimated == 1
    assert st.fees_usd == pytest.approx(90.0 * 80.0 / 10_000.0)


def test_ft_fee_base_none_maps_to_none_not_zero():
    """`Order.safe_fee_base` would return 0.0 here (trade_model.py:160). The
    fee this integration reports comes from the trade's fee RATE, and is None
    when there is no rate."""
    trade = FakeTrade(fee_open=0.001)
    order = FakeOrder("buy", 0.003, 30_000.0, ft_fee_base=None)
    fee, src = DeadmanGuardMixin._deadman_fee(trade, order, 0.003, 30_000.0, is_entry=True)
    assert fee == pytest.approx(0.09) and src == "trade.fee_open"

    trade_no_rate = FakeTrade(fee_open=None)
    fee, src = DeadmanGuardMixin._deadman_fee(trade_no_rate, order, 0.003, 30_000.0, is_entry=True)
    assert fee is None and src == "unavailable"


def test_round_trip_net_equals_freqtrades_own_number(tmp_path):
    """The double-counting trap, closed with arithmetic.

    freqtrade's profit already includes fees (trade_model.py:1156). deadman
    wants GROSS in record_pnl and the fees per fill. The two must land on the
    same net, or one of them is counting fees twice.

    The numbers are from a real backtest run of DeadmanDemoStrategy.
    """
    amount, open_rate, close_rate, fee = 0.0033204, 30116.825502693, 30262.678565943, 0.001
    # freqtrade: _calc_open_trade_value / _calc_base_close (spot long)
    ft_net = (amount * close_rate) * (1 - fee) - (amount * open_rate) * (1 + fee)

    gate = make_gate(tmp_path, limits=Limits(max_trades_per_day=10, worst_case_fee_bps=80.0))
    strat = Strat(gate)
    strat.bot_start()
    entry_order = FakeOrder("buy", amount, open_rate)
    trade = FakeTrade(open_rate=open_rate, amount=amount, fee_open=fee, fee_close=fee)
    strat.order_filled(PAIR, trade, entry_order, T0)
    exit_order = FakeOrder("sell", amount, close_rate, order_id="o2")
    strat.order_filled(PAIR, trade, exit_order, T0 + timedelta(minutes=50))

    st = gate.stats()
    assert st.trades == 2                       # entry and exit both counted
    assert st.net_pnl_usd == pytest.approx(ft_net, abs=1e-9)
    assert st.gross_pnl_usd == pytest.approx(amount * (close_rate - open_rate), abs=1e-12)
    assert st.gross_pnl_usd > 0 > st.net_pnl_usd or st.net_pnl_usd <= st.gross_pnl_usd


def test_partial_exit_pnl_is_not_attributed(tmp_path):
    gate = make_gate(tmp_path)
    strat = Strat(gate)
    strat.bot_start()
    trade = FakeTrade(open_rate=30_000.0, amount=0.003)
    strat.order_filled(PAIR, trade, FakeOrder("sell", 0.001, 30_100.0, amount=0.001), T0)
    notes = [r["payload"]["note"] for r in ledger_rows(gate) if r["kind"] == "USER_NOTE"]
    assert notes == ["PARTIAL_EXIT_PNL_NOT_ATTRIBUTED"]
    assert gate.stats().gross_pnl_usd == 0.0          # nothing invented
    assert gate.stats().trades == 1                   # the fill itself is still counted


# --------------------------------------------------------------------------
# the callbacks: what happens when deadman itself breaks
# --------------------------------------------------------------------------
class Boom(DeadmanGate):
    def entry_verdict(self, **kw):
        raise RuntimeError("gate exploded")

    def exit_verdict(self, **kw):
        raise RuntimeError("gate exploded")


def test_entry_is_denied_when_the_gate_raises(tmp_path):
    """freqtrade would return True (default_retval=True). The mixin must not."""
    gate = Boom(tmp_path / "state", limits=Limits(), allowed_pairs=[PAIR],
                quotes=DeclaredSpreadQuotes(spread_bps=4.0, latency_ms=25.0),
                max_latency_ms=2000.0, max_spread_bps=50.0)
    strat = Strat(gate)
    strat.bot_start()
    ok = strat.confirm_trade_entry(PAIR, "limit", 0.003, 30_000.0, "GTC", T0, None, "long")
    assert ok is False
    assert strat.deadman_broken is True
    assert gate.halt.active() is not None          # new exposure stopped


def test_exit_is_allowed_when_the_gate_raises(tmp_path):
    """The mirror image: an internal failure must never trap a position."""
    gate = Boom(tmp_path / "state", limits=Limits(), allowed_pairs=[PAIR],
                quotes=DeclaredSpreadQuotes(spread_bps=4.0, latency_ms=25.0),
                max_latency_ms=2000.0, max_spread_bps=50.0)
    strat = Strat(gate)
    strat.bot_start()
    ok = strat.confirm_trade_exit(PAIR, FakeTrade(), "limit", 0.003, 30_100.0, "GTC", "stop_loss", T0)
    assert ok is True
    assert gate.halt.active() is not None          # entries halted, exit allowed


def test_shorts_are_refused_by_the_spot_long_only_gate(tmp_path):
    gate = make_gate(tmp_path)
    strat = Strat(gate)
    strat.bot_start()
    assert strat.confirm_trade_entry(PAIR, "limit", 0.003, 30_000.0, "GTC", T0, None, "short") is False
    assert deny_codes(gate) == ["SHORT_NOT_SUPPORTED"]


def test_entry_denied_without_a_gate(tmp_path):
    strat = Strat(None)
    strat.deadman = None
    assert strat.confirm_trade_entry(PAIR, "limit", 0.003, 30_000.0, "GTC", T0, None, "long") is False
    # ...and the exit still goes, because there is nothing to consult
    assert strat.confirm_trade_exit(PAIR, FakeTrade(), "limit", 0.003, 30_100.0, "GTC", "roi", T0) is True


# --------------------------------------------------------------------------
# the clock
# --------------------------------------------------------------------------
def test_the_day_follows_freqtrades_time_not_the_wall_clock(tmp_path):
    """This is why deadman takes an injectable clock: in a backtest the daily
    counter must roll over on BACKTEST days."""
    clock = FreqtradeClock()
    gate = make_gate(tmp_path, clock=clock, limits=Limits(max_trades_per_day=1, worst_case_fee_bps=80.0))
    clock.set(datetime(2026, 3, 1, 10, 0, tzinfo=timezone.utc))
    gate.record_fill(pair=PAIR, side="buy", is_exit=False, filled_base=0.003, price=30_000.0,
                     fee_usd=0.09, fee_source="test", requested_base=0.003, order_id="o1", client_id="c1")
    assert gate.stats().day_utc == "2026-03-01"
    assert not gate.entry_verdict(pair=PAIR, amount_base=0.003, rate=30_000.0,
                                  size_available_quote=10_000.0, client_id="c2").allowed

    clock.set(datetime(2026, 3, 2, 10, 0, tzinfo=timezone.utc))    # next backtest day
    v = gate.entry_verdict(pair=PAIR, amount_base=0.003, rate=30_000.0,
                           size_available_quote=10_000.0, client_id="c3")
    assert v.allowed
    assert gate.stats().day_utc == "2026-03-02" and gate.stats().trades == 0
    assert "DAILY_STATS_RESET" in kinds(gate)         # never a silent reset


def test_clock_refuses_a_naive_datetime():
    with pytest.raises(ValueError):
        FreqtradeClock().set(datetime(2026, 1, 1, 12, 0))


# --------------------------------------------------------------------------
# the ledger
# --------------------------------------------------------------------------
def test_the_ledger_verifies_after_a_full_session(tmp_path):
    gate = make_gate(tmp_path)
    strat = Strat(gate)
    strat.bot_start()
    trade = FakeTrade(open_rate=30_000.0, amount=0.003)
    assert strat.confirm_trade_entry(PAIR, "limit", 0.003, 30_000.0, "GTC", T0, None, "long") is True
    strat.order_filled(PAIR, trade, FakeOrder("buy", 0.003, 30_000.0), T0)
    assert strat.confirm_trade_exit(PAIR, trade, "limit", 0.003, 30_100.0, "GTC", "exit_signal", T0) is True
    strat.order_filled(PAIR, trade, FakeOrder("sell", 0.003, 30_100.0, order_id="o2"), T0)

    rep = gate.verify()
    assert rep.ok and rep.chain_complete and rep.entries_checked == len(ledger_rows(gate))
    assert kinds(gate) == ["ORDER_SENT", "FILL", "ORDER_SENT", "FILL", "USER_NOTE"]


def test_an_edited_ledger_does_not_verify(tmp_path):
    gate = make_gate(tmp_path)
    gate.entry_verdict(pair=PAIR, amount_base=0.003, rate=30_000.0,
                       size_available_quote=10_000.0, client_id="c1")
    f = gate.paths.ledger_file
    rows = [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines() if x.strip()]
    rows[0]["payload"]["amount_base"] = 999.0
    f.write_text(json.dumps(rows[0], sort_keys=True) + "\n", encoding="utf-8")
    rep = Ledger(Paths(gate.paths.root), SystemClock()).verify()
    assert not rep.ok and rep.code == "HASH_MISMATCH"
