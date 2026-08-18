"""G5 - order sanity (SPEC §4.4) + the G10 zero-default cases that belong to it.
Applies to entries AND exits. Every test names its assertion."""
import math

import pytest

from deadman import OrderSanity, Intent, Resolved


def mk(side="buy", symbol="BTC/USD", client_id="c1"):
    return Intent(symbol=symbol, side=side, units="USD", amount=100.0, kind="ENTRY" if side == "buy" else "EXIT", client_id=client_id)


R = Resolved(100.0, 0.002, None)
GOOD = dict(broker_status="connected", latency_ms=50.0, bid=49_990.0, ask=50_010.0, size_available=1000.0)


def sanity(**kw):
    base = dict(allowed_symbols=frozenset({"BTC/USD"}), max_latency_ms=500.0, max_spread_bps=20.0)
    base.update(kw)
    return OrderSanity(**base)


# ---- G5.1 happy path, and the omitted-checks are declared ----
def test_g5_1_passes_and_declares_omitted_optional_checks():
    v = sanity().check(mk(), R, is_exit=False, **GOOD)
    assert v.allowed and v.code == "ORDER_SANITY_OK" and "omitted" in v.reason and "min_notional" in v.reason


# ---- G5.2 each brake denies ENTRIES AND EXITS alike ----
@pytest.mark.parametrize("field,val,code", [
    ("broker_status", "degraded", "BROKER_NOT_CONNECTED"),
    ("latency_ms", 900.0, "LATENCY_TOO_HIGH"),
    ("bid", 49_800.0, "SPREAD_TOO_WIDE"),      # 42 bps
    ("size_available", 0.0, "INSUFFICIENT_SIZE"),
])
@pytest.mark.parametrize("is_exit", [False, True])
def test_g5_2_brakes_apply_to_entries_and_exits(field, val, code, is_exit):
    args = dict(GOOD)
    args[field] = val
    intent = mk(side="sell" if is_exit else "buy")
    v = sanity().check(intent, R, is_exit=is_exit, **args)
    assert not v.allowed and v.code == code and "client_id=c1" in v.reason


def test_g5_2b_symbol_not_allowed_denies_exits_too():
    v = sanity().check(mk(side="sell", symbol="DOGE/USD"), R, is_exit=True, **GOOD)
    assert v.code == "SYMBOL_NOT_ALLOWED"


def test_g5_2c_empty_allowlist_denies_everything():
    v = sanity(allowed_symbols=frozenset()).check(mk(), R, is_exit=False, **GOOD)
    assert v.code == "SYMBOL_NOT_ALLOWED"


# ---- G5.3 size semantics: exit needs BASE, entry needs QUOTE ----
def test_g5_3_size_available_is_base_for_exits_and_quote_for_entries():
    s = sanity()
    args = dict(GOOD, size_available=0.0015)                       # 0.0015 base < 0.002 needed
    assert s.check(mk(side="sell"), R, is_exit=True, **args).code == "INSUFFICIENT_SIZE"
    args = dict(GOOD, size_available=0.0025)
    assert s.check(mk(side="sell"), R, is_exit=True, **args).allowed
    args = dict(GOOD, size_available=99.0)                         # 99 USD < 100 needed
    assert s.check(mk(), R, is_exit=False, **args).code == "INSUFFICIENT_SIZE"


# ---- G5.4 crossed / bad quotes ----
@pytest.mark.parametrize("bid,ask", [(50_010.0, 49_990.0), (50_000.0, 50_000.0), (-1.0, 5.0)])
def test_g5_4_crossed_or_nonpositive_quote_denies(bid, ask):
    args = dict(GOOD, bid=bid, ask=ask)
    assert sanity().check(mk(), R, is_exit=False, **args).code == "QUOTE_CROSSED"


# ---- G10: any None/NaN input -> <ARG>_MISSING, never a default ----
@pytest.mark.parametrize("field,code", [
    ("broker_status", "BROKER_STATUS_MISSING"), ("latency_ms", "LATENCY_MISSING"),
    ("bid", "BID_MISSING"), ("ask", "ASK_MISSING"), ("size_available", "SIZE_AVAILABLE_MISSING"),
])
@pytest.mark.parametrize("val", [None, float("nan")])
def test_g10_missing_or_nan_input_denies_naming_the_arg(field, code, val):
    if field == "broker_status" and isinstance(val, float):
        pytest.skip("status is a string; None is its missing form")
    args = dict(GOOD)
    args[field] = val
    v = sanity().check(mk(), R, is_exit=False, **args)
    assert not v.allowed and v.code == code


def test_g10_config_has_no_defaults():
    with pytest.raises(TypeError):
        OrderSanity(allowed_symbols=frozenset({"BTC/USD"}))       # max_latency/max_spread required
    with pytest.raises(ValueError):
        OrderSanity(allowed_symbols=None, max_latency_ms=1, max_spread_bps=1)
    with pytest.raises(ValueError):
        sanity(max_latency_ms=float("nan"))
    with pytest.raises(ValueError):
        sanity(min_notional_usd=10, max_notional_usd=5)


# ---- G5.5 notional bounds; NEVER enlarge to reach the venue minimum (exposure_engine.py:81 mirror) ----
def test_g5_5_below_min_notional_is_denied_not_enlarged():
    s = sanity(min_notional_usd=10.0)
    small = Resolved(4.0, 0.00008, None)
    v = s.check(mk(), small, is_exit=False, **GOOD)
    assert not v.allowed and v.code == "NOTIONAL_BELOW_MIN" and "NOT enlarged" in v.reason
    # and there is no API that returns a bigger amount
    q = s.quantize(mk(), small, amount_step=0.00001, price=50_000.0)
    assert q.verdict.allowed and q.amount_base <= small.amount_base


def test_g5_5b_above_max_notional_denied():
    s = sanity(max_notional_usd=50.0)
    assert s.check(mk(), R, is_exit=False, **GOOD).code == "NOTIONAL_ABOVE_MAX"


# ---- G5.6 fat-finger deviation; configured => ref_price required ----
def test_g5_6_ref_deviation_requires_ref_and_denies_far_mid():
    s = sanity(max_ref_deviation_bps=50.0)
    assert s.check(mk(), R, is_exit=False, **GOOD).code == "REF_PRICE_MISSING"
    assert s.check(mk(), R, is_exit=False, ref_price=50_000.0, **GOOD).allowed
    v = s.check(mk(), R, is_exit=False, ref_price=52_000.0, **GOOD)   # ~385 bps away
    assert v.code == "PRICE_DEVIATION"


# ---- G5.7 quantize: floor towards less exposure; zero -> deny; never round up ----
def test_g5_7_quantize_floors_never_rounds_up():
    s = sanity()
    q = s.quantize(mk(), Resolved(100.0, 0.00259, None), amount_step=0.001, price=50_000.0)
    assert q.verdict.allowed and q.amount_base == pytest.approx(0.002) and q.notional_usd == pytest.approx(100.0)
    q = s.quantize(mk(), Resolved(15.0, 0.0003, None), amount_step=0.001, price=50_000.0)   # 0.0003 -> 0
    assert not q.verdict.allowed and q.verdict.code == "AMOUNT_BELOW_STEP" and q.amount_base == 0.0
    assert "not bumped to the minimum" in q.verdict.reason


def test_g5_7b_quantize_floors_exits_too_never_sells_more_than_asked():
    s = sanity()
    q = s.quantize(mk(side="sell"), Resolved(0.0, 0.0029, None), amount_step=0.001, price=50_000.0)
    assert q.amount_base == pytest.approx(0.002)      # not 0.003


def test_g5_7c_quantize_exact_multiples_are_kept():
    s = sanity()
    q = s.quantize(mk(), Resolved(0.0, 0.3, None), amount_step=0.1, price=1.0)
    assert q.amount_base == pytest.approx(0.3)


@pytest.mark.parametrize("step", [None, 0.0, -1.0, float("nan")])
def test_g10_quantize_step_missing_denies(step):
    q = sanity().quantize(mk(), R, amount_step=step, price=50_000.0)
    assert q.verdict.code == "AMOUNT_STEP_MISSING"


def test_g10_resolved_amount_invalid_is_caught_at_the_boundary():
    v = sanity().check(mk(), Resolved(0.0, 0.0, None), is_exit=False, **GOOD)
    assert v.code == "RESOLVED_AMOUNT_INVALID"
