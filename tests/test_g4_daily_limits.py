"""G4 - daily limits (SPEC §4.4, decision B) + the G10 zero-default cases that
belong to it. Every test names the assertion it covers."""
import json

import pytest

from deadman import DailyLimits, Limits, Intent, Resolved, spot_long_only_is_exit, Ledger
from deadman.errors import ConcurrentWriterDetected


def mk(side="buy", client_id="c1", **kw):
    d = dict(symbol="BTC/USD", side=side, units="USD", amount=100.0, kind="ENTRY" if side == "buy" else "EXIT", client_id=client_id)
    d.update(kw)
    return Intent(**d)


R = Resolved(100.0, 0.002, None)


def limits(paths, clock, ident, ledger=None, **kw):
    return DailyLimits(paths, Limits(**kw), spot_long_only_is_exit, clock, ident, ledger=ledger)


def kinds(paths):
    return [json.loads(l)["kind"] for l in open(paths.ledger_file, encoding="utf-8") if l.strip()]


# ---- G4.1 no file: fresh day, entries allowed ----
def test_g4_1_absent_file_is_a_fresh_day(paths, clock, ident):
    dl = limits(paths, clock, ident, max_trades_per_day=2)
    assert dl.check(mk(), R).allowed
    st = dl.stats()
    assert st.trades == 0 and st.day_utc == clock.today_utc()


# ---- G4.2/G4.3 max trades blocks entry, not exit; exit fills count ----
def test_g4_2_max_trades_blocks_entry_but_never_exit(paths, clock, ident, ledger):
    dl = limits(paths, clock, ident, ledger, max_trades_per_day=2)
    dl.record_fill(mk(), 100.0, fee_usd=0.1)
    dl.record_fill(mk(side="sell"), 100.0, fee_usd=0.1)   # G4.3: the exit fill COUNTS
    assert dl.stats().trades == 2
    v = dl.check(mk(), R)
    assert not v.allowed and v.code == "DAILY_MAX_TRADES" and "client_id=c1" in v.reason
    assert dl.check(mk(side="sell"), R).code == "EXIT_BYPASSES_DAILY_LIMITS"
    assert "INTENT_DENIED" in kinds(paths)      # limit reached is in the ledger


# ---- G4.4 daily loss, NET of fees (mirror of "+$0.29 gross, negative net") ----
def test_g4_4_loss_limit_uses_net_pnl_gross_positive_net_negative(paths, clock, ident, ledger):
    dl = limits(paths, clock, ident, ledger, max_daily_loss_usd=5.0)
    dl.record_fill(mk(), 1000.0, fee_usd=4.20)          # entry fee
    dl.record_fill(mk(side="sell"), 1000.0, fee_usd=4.20)  # exit fee
    dl.record_pnl(0.29)                                    # gross funding/PnL +0.29
    st = dl.stats()
    assert st.gross_pnl_usd == pytest.approx(0.29) and st.fees_usd == pytest.approx(8.40)
    assert st.net_pnl_usd == pytest.approx(-8.11)
    v = dl.check(mk(client_id="c2"), R)
    assert not v.allowed and v.code == "DAILY_LOSS_LIMIT" and "net P&L today -8.11" in v.reason
    assert dl.check(mk(side="sell"), R).allowed  # exits still pass


# ---- G4.5 unknown fee never counts as zero ----
def test_g4_5_unknown_fee_without_worst_case_marks_day_unverified_and_blocks_entries(paths, clock, ident, ledger):
    dl = limits(paths, clock, ident, ledger, max_daily_loss_usd=1000.0)
    dl.record_fill(mk(), 100.0, fee_usd=None)
    st = dl.stats()
    assert st.fees_unverified is True and st.fees_usd == 0.0
    v = dl.check(mk(client_id="c2"), R)
    assert not v.allowed and v.code == "DAILY_FEES_UNVERIFIED"
    assert dl.check(mk(side="sell"), R).allowed


def test_g4_5b_unknown_fee_with_worst_case_is_charged_at_worst_case(paths, clock, ident):
    dl = limits(paths, clock, ident, max_daily_loss_usd=1000.0, worst_case_fee_bps=80.0)  # 0.80% taker
    st = dl.record_fill(mk(), 1000.0, fee_usd=None)
    assert st.fees_usd == pytest.approx(8.0) and st.fees_estimated == 1 and st.fees_unverified is False
    assert dl.check(mk(client_id="c2"), R).allowed


# ---- G4.6 decision B: unreadable file -> entry denied, exit passes without reading ----
def test_g4_6_corrupt_stats_blocks_entry_but_exit_passes_without_reading(paths, clock, ident, ledger, monkeypatch):
    dl = limits(paths, clock, ident, ledger, max_trades_per_day=5)
    paths.daily_stats.write_text("{corrupt", encoding="utf-8")
    real_read = dl.file.read
    reads = {"n": 0}

    def counting_read():
        reads["n"] += 1
        return real_read()
    monkeypatch.setattr(dl.file, "read", counting_read)
    assert dl.check(mk(side="sell"), R).code == "EXIT_BYPASSES_DAILY_LIMITS"
    assert reads["n"] == 0                       # the file was NOT read for the exit
    v = dl.check(mk(), R)
    assert not v.allowed and v.code == "DAILY_STATS_UNREADABLE" and reads["n"] == 1
    assert dl.stats() is None                    # nothing is silently reset
    assert paths.daily_stats.read_text(encoding="utf-8") == "{corrupt"


# ---- G4.7 / G10: missing key never takes a default (mirror of "default 100 -> $2 cap") ----
def test_g4_7_missing_key_blocks_entries_naming_the_key(paths, clock, ident, ledger):
    dl = limits(paths, clock, ident, ledger, max_trades_per_day=5)
    dl.record_fill(mk(), 10.0, 0.0)
    d = json.loads(paths.daily_stats.read_text(encoding="utf-8"))
    del d["fees_usd"]
    paths.daily_stats.write_text(json.dumps(d), encoding="utf-8")
    v = dl.check(mk(client_id="c2"), R)
    assert not v.allowed and v.code == "DAILY_STATS_KEY_MISSING" and "fees_usd" in v.reason and "no default" in v.reason
    assert dl.check(mk(side="sell"), R).allowed


# ---- G4.8 rollover: UTC boundary from the injected clock, ledgered, never silent ----
def test_g4_8_rollover_resets_counters_and_is_ledgered(paths, clock, ident, ledger):
    dl = limits(paths, clock, ident, ledger, max_trades_per_day=1)
    dl.record_fill(mk(), 10.0, 0.0)
    assert dl.check(mk(client_id="c2"), R).code == "DAILY_MAX_TRADES"
    clock.advance(hours=13)          # 12:00 -> 01:00 next day UTC
    v = dl.check(mk(client_id="c3"), R)
    assert v.allowed
    st = dl.stats()
    assert st.day_utc == clock.today_utc() and st.trades == 0
    ks = kinds(paths)
    assert "DAILY_STATS_RESET" in ks
    reset = [json.loads(l) for l in open(paths.ledger_file, encoding="utf-8") if '"DAILY_STATS_RESET"' in l][0]
    assert reset["payload"]["previous"]["trades"] == 1 and reset["payload"]["to_day"] == clock.today_utc()


def test_g4_8b_no_rollover_before_the_utc_boundary(paths, clock, ident):
    dl = limits(paths, clock, ident, max_trades_per_day=1)
    dl.record_fill(mk(), 10.0, 0.0)
    clock.advance(hours=11, minutes=59)   # 23:59 same day
    assert dl.check(mk(client_id="c2"), R).code == "DAILY_MAX_TRADES"


# ---- G4.9 clock going backwards: fail-closed, an exhausted limit is not reopened ----
def test_g4_9_clock_backwards_blocks_entries_and_resets_nothing(paths, clock, ident, ledger):
    dl = limits(paths, clock, ident, ledger, max_trades_per_day=1)
    clock.advance(days=1)
    dl.record_fill(mk(), 10.0, 0.0)                     # exhausted on day D+1
    clock.advance(days=-1)                              # clock jumps back to day D
    v = dl.check(mk(client_id="c2"), R)
    assert not v.allowed and v.code == "DAILY_STATS_CLOCK_BACKWARDS"
    assert dl.check(mk(side="sell"), R).allowed
    d = json.loads(paths.daily_stats.read_text(encoding="utf-8"))
    assert d["trades"] == 1                             # untouched
    assert "DAILY_STATS_RESET" not in kinds(paths)
    # a fill that happens anyway is still recorded (never lose a fill), against the file's day
    st = dl.record_fill(mk(side="sell"), 5.0, 0.0)
    assert st.trades == 2 and st.day_utc == d["day_utc"]


# ---- G4.10 notional per order ----
def test_g4_10_max_notional_per_order_blocks_entry_not_exit(paths, clock, ident):
    dl = limits(paths, clock, ident, max_notional_usd_per_order=50.0)
    v = dl.check(mk(), Resolved(100.0, 0.002, None))
    assert v.code == "DAILY_MAX_NOTIONAL"
    assert dl.check(mk(side="sell"), Resolved(100.0, 0.002, None)).allowed


# ---- G4.11 the state file carries the writer seal; concurrent writer surfaces ----
def test_g4_11_state_is_sealed_and_concurrent_writer_raises(paths, clock, ident, ledger):
    from deadman import WriterIdentity
    dl = limits(paths, clock, ident, ledger, max_trades_per_day=5)
    dl.record_fill(mk(), 10.0, 0.0)
    d = json.loads(paths.daily_stats.read_text(encoding="utf-8"))
    assert d["writer_pid"] == 1000 and d["schema_version"] == 1
    other = WriterIdentity(clock, pid=2000, pid_alive=lambda p: True)
    dl2 = DailyLimits(paths, Limits(max_trades_per_day=5), spot_long_only_is_exit, clock, other, ledger=ledger)
    # dl reads, dl2 writes in between, dl writes -> detected
    real_load = dl._load
    snap = real_load()

    def stale_load():
        return snap
    dl._load = stale_load
    dl2.record_fill(mk(client_id="x"), 1.0, 0.0)
    with pytest.raises(ConcurrentWriterDetected):
        dl.record_fill(mk(client_id="y"), 1.0, 0.0)
    assert "CONCURRENT_WRITER_DETECTED" in kinds(paths)


# ---- G10: invalid inputs to record_* are loud, never coerced ----
@pytest.mark.parametrize("bad", [-1.0, float("nan"), None])
def test_g10_record_fill_rejects_invalid_filled_usd(paths, clock, ident, bad):
    dl = limits(paths, clock, ident)
    with pytest.raises((ValueError, TypeError)):
        dl.record_fill(mk(), bad, 0.0)
