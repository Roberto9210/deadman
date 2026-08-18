"""Intent, the units contract and the exit predicates (SPEC §4.3, §4.4).

The units contract exists because a quantity once travelled in a bare
`amount` field with no unit; the "sell the whole position" path sold a USD
figure converted at a stale price. `units` is mandatory and resolve_units()
never interprets: missing/invalid => exception carrying the intent.

The exit predicate is a POLICY over an injectable callable. The default that
ships is spot long-only (side == "sell"); futures/shorts/two-leg structures
must pass net_position_is_exit or their own predicate. The kit never guesses.
"""
import math
from dataclasses import dataclass, field
from typing import Any, Callable, Literal, Mapping, Optional

from .errors import ContractSizeMissing, IntentAmountInvalid, IntentUnitsInvalid, PriceInvalid

UNITS = ("USD", "BASE", "CONTRACTS")
SIDES = ("buy", "sell")
KINDS = ("ENTRY", "EXIT", "RISK_EXIT", "ROLL")


@dataclass(frozen=True)
class Intent:
    symbol: str
    side: str                       # "buy" | "sell"
    units: str                      # "USD" | "BASE" | "CONTRACTS"
    amount: float
    kind: str                       # "ENTRY" | "EXIT" | "RISK_EXIT" | "ROLL"
    client_id: str                  # idempotency key; caller-generated
    meta: Mapping[str, Any] = field(default_factory=dict)  # opaque; travels to the ledger

    def __post_init__(self):
        # Shape validation is loud at construction; unit/amount semantics are
        # validated again in resolve_units() because an Intent may be built
        # from untrusted dicts (e.g. a signal file) via Intent.from_mapping().
        if not isinstance(self.symbol, str) or not self.symbol:
            raise IntentUnitsInvalid(f"INTENT_SYMBOL_INVALID: {self.symbol!r}")
        if self.side not in SIDES:
            raise IntentUnitsInvalid(f"INTENT_SIDE_INVALID: {self.side!r} (expected one of {SIDES})")
        if self.kind not in KINDS:
            raise IntentUnitsInvalid(f"INTENT_KIND_INVALID: {self.kind!r} (expected one of {KINDS})")
        if not isinstance(self.client_id, str) or not self.client_id:
            raise IntentUnitsInvalid("INTENT_CLIENT_ID_MISSING")

    @classmethod
    def from_mapping(cls, d: Mapping[str, Any]) -> "Intent":
        """Build from a plain dict WITHOUT defaults: every required key must be
        present. A missing key is IntentUnitsInvalid naming the key."""
        missing = [k for k in ("symbol", "side", "units", "amount", "kind", "client_id") if k not in d]
        if missing:
            raise IntentUnitsInvalid(f"INTENT_FIELDS_MISSING: {missing} in {dict(d)!r}")
        try:
            amount = float(d["amount"])
        except (TypeError, ValueError):
            raise IntentAmountInvalid(f"INTENT_AMOUNT_INVALID: {d.get('amount')!r}")
        return cls(str(d["symbol"]), str(d["side"]).lower(), str(d["units"]).upper(), amount,
                   str(d["kind"]).upper(), str(d["client_id"]), dict(d.get("meta") or {}))

    def as_dict(self) -> dict:
        return {"symbol": self.symbol, "side": self.side, "units": self.units, "amount": self.amount,
                "kind": self.kind, "client_id": self.client_id, "meta": dict(self.meta)}


@dataclass(frozen=True)
class Resolved:
    amount_usd: float
    amount_base: float
    amount_contracts: Optional[float]   # None unless units == CONTRACTS or contract_size given


def _finite_positive(x: Any) -> bool:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return False
    return math.isfinite(v) and v > 0


def resolve_units(intent: Intent, price: float, contract_size: float | None = None) -> Resolved:
    """USD -> base at `price`; BASE -> usd at `price`; CONTRACTS -> base via
    `contract_size` (base units per contract) then usd. Never interprets a
    missing unit; every failure names what is missing and carries the intent."""
    if intent.units not in UNITS:
        raise IntentUnitsInvalid(f"INTENT_UNITS_INVALID: units={intent.units!r} not in {UNITS}; intent={intent.as_dict()!r}")
    if not _finite_positive(intent.amount):
        raise IntentAmountInvalid(f"INTENT_AMOUNT_INVALID: amount={intent.amount!r}; intent={intent.as_dict()!r}")
    if not _finite_positive(price):
        raise PriceInvalid(f"PRICE_INVALID: price={price!r}; intent={intent.as_dict()!r}")
    price = float(price)
    if intent.units == "USD":
        usd = float(intent.amount)
        base = usd / price
        contracts = base / float(contract_size) if contract_size is not None and _finite_positive(contract_size) else None
    elif intent.units == "BASE":
        base = float(intent.amount)
        usd = base * price
        contracts = base / float(contract_size) if contract_size is not None and _finite_positive(contract_size) else None
    else:  # CONTRACTS
        if contract_size is None or not _finite_positive(contract_size):
            raise ContractSizeMissing(f"CONTRACT_SIZE_MISSING: units=CONTRACTS needs contract_size>0, got {contract_size!r}; intent={intent.as_dict()!r}")
        contracts = float(intent.amount)
        base = contracts * float(contract_size)
        usd = base * price
    if not (_finite_positive(usd) and _finite_positive(base)):
        raise IntentAmountInvalid(f"INTENT_AMOUNT_INVALID: resolved usd={usd} base={base}; intent={intent.as_dict()!r}")
    return Resolved(usd, base, contracts)


# ---------------- exit predicates (SPEC §4.4) ----------------

@dataclass(frozen=True)
class PositionSnapshot:
    symbol: str
    net_base: float        # >0 long, <0 short, 0 flat
    ts_utc: str


ExposurePredicate = Callable[[Intent, Optional[PositionSnapshot]], bool]


def spot_long_only_is_exit(intent: Intent, position: Optional[PositionSnapshot] = None) -> bool:
    """DEFAULT, declared SPOT LONG-ONLY: on a spot venue with no shorting a
    sell can only reduce or close a long. Do not use for futures or shorts."""
    return intent.side == "sell"


def net_position_is_exit(intent: Intent, position: Optional[PositionSnapshot], resolved_base: Optional[float] = None) -> bool:
    """True iff the order reduces |net position|. With no position snapshot the
    answer is False (fail-closed towards 'this is an entry'): an exit needs a
    position to be an exit of. `resolved_base` is the order size in base; if
    not given, only the direction is judged (any opposite-side order counts as
    reducing, which is the conservative reading for letting exits out)."""
    if position is None:
        return False
    net = float(position.net_base)
    if net == 0:
        return False
    if resolved_base is None:
        return (net > 0) == (intent.side == "sell")
    delta = (1.0 if intent.side == "buy" else -1.0) * float(resolved_base)
    return abs(net + delta) < abs(net)   # an over-close that flips the sign is NEW exposure -> False
