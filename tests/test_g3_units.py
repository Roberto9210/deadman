"""G3 - units contract: USD/BASE/CONTRACTS resolve; anything ambiguous raises
with the intent in the message; nothing is inferred. Plus the exit predicates."""
import math

import pytest

from deadman import Intent, resolve_units, PositionSnapshot, spot_long_only_is_exit, net_position_is_exit
from deadman.errors import IntentUnitsInvalid, IntentAmountInvalid, PriceInvalid, ContractSizeMissing


def mk(**kw):
    d = dict(symbol="BTC/USD", side="buy", units="USD", amount=100.0, kind="ENTRY", client_id="c1")
    d.update(kw)
    return Intent(**d)


# ---- resolve ----
def test_usd_resolves_to_base():
    r = resolve_units(mk(units="USD", amount=100.0), price=50_000.0)
    assert r.amount_usd == 100.0 and math.isclose(r.amount_base, 0.002) and r.amount_contracts is None


def test_base_resolves_to_usd_exactly_what_was_asked():
    r = resolve_units(mk(side="sell", units="BASE", amount=0.001, kind="EXIT"), price=60_000.0)
    assert r.amount_base == 0.001 and r.amount_usd == 60.0   # an exit in BASE sells exactly the base asked


def test_contracts_resolve_via_contract_size():
    r = resolve_units(mk(units="CONTRACTS", amount=2), price=64_000.0, contract_size=0.1)
    assert r.amount_contracts == 2 and math.isclose(r.amount_base, 0.2) and math.isclose(r.amount_usd, 12_800.0)


def test_contracts_without_contract_size_raise():
    with pytest.raises(ContractSizeMissing) as ei:
        resolve_units(mk(units="CONTRACTS", amount=1), price=1.0)
    assert "CONTRACT_SIZE_MISSING" in str(ei.value) and "client_id" in str(ei.value)


def test_usd_with_contract_size_also_reports_contracts():
    r = resolve_units(mk(units="USD", amount=6_400.0), price=64_000.0, contract_size=0.1)
    assert math.isclose(r.amount_contracts, 1.0)


@pytest.mark.parametrize("bad", ["usd", "", "SHARES", None])
def test_units_outside_the_set_raise_and_carry_the_intent(bad):
    with pytest.raises(IntentUnitsInvalid) as ei:
        resolve_units(mk(units=bad), price=1.0)
    assert "INTENT_UNITS_INVALID" in str(ei.value) and "BTC/USD" in str(ei.value)


@pytest.mark.parametrize("bad", [0, -1, float("nan"), float("inf")])
def test_amount_not_finite_positive_raises(bad):
    with pytest.raises(IntentAmountInvalid):
        resolve_units(mk(amount=bad), price=1.0)


@pytest.mark.parametrize("bad", [0, -5, float("nan"), None])
def test_price_invalid_raises(bad):
    with pytest.raises(PriceInvalid):
        resolve_units(mk(), price=bad)


def test_no_default_is_ever_applied_from_a_mapping():
    with pytest.raises(IntentUnitsInvalid) as ei:
        Intent.from_mapping({"symbol": "BTC/USD", "side": "buy", "amount": 5, "kind": "ENTRY", "client_id": "x"})
    assert "units" in str(ei.value)
    with pytest.raises(IntentUnitsInvalid):
        Intent.from_mapping({"symbol": "BTC/USD", "side": "buy", "units": "USD", "kind": "ENTRY", "client_id": "x"})  # no amount


def test_from_mapping_normalises_case_but_not_meaning():
    i = Intent.from_mapping({"symbol": "ETH/USD", "side": "SELL", "units": "base", "amount": "0.5", "kind": "exit", "client_id": "k"})
    assert i.side == "sell" and i.units == "BASE" and i.kind == "EXIT" and i.amount == 0.5


@pytest.mark.parametrize("field,val", [("side", "long"), ("kind", "OPEN"), ("client_id", ""), ("symbol", "")])
def test_intent_shape_is_validated_at_construction(field, val):
    with pytest.raises(IntentUnitsInvalid):
        mk(**{field: val})


# ---- exit predicates ----
def test_spot_long_only_default_is_side_sell():
    assert spot_long_only_is_exit(mk(side="sell")) is True
    assert spot_long_only_is_exit(mk(side="buy")) is False


def test_net_position_predicate_needs_a_position():
    assert net_position_is_exit(mk(side="sell"), None) is False        # fail-closed towards "entry"
    flat = PositionSnapshot("BTC/USD", 0.0, "t")
    assert net_position_is_exit(mk(side="sell"), flat) is False


def test_net_position_predicate_reduces_long_and_short():
    long = PositionSnapshot("BTC/USD", 1.0, "t")
    short = PositionSnapshot("BTC/USD", -1.0, "t")
    assert net_position_is_exit(mk(side="sell"), long) is True
    assert net_position_is_exit(mk(side="buy"), long) is False
    assert net_position_is_exit(mk(side="buy"), short) is True     # buying back a short IS an exit
    assert net_position_is_exit(mk(side="sell"), short) is False


def test_net_position_overclose_that_flips_is_not_an_exit():
    long = PositionSnapshot("BTC/USD", 1.0, "t")
    assert net_position_is_exit(mk(side="sell"), long, resolved_base=0.4) is True
    assert net_position_is_exit(mk(side="sell"), long, resolved_base=1.0) is True    # exactly flat
    assert net_position_is_exit(mk(side="sell"), long, resolved_base=3.0) is False   # flips to -2: new exposure
