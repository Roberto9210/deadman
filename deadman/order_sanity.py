"""Order sanity (SPEC §4.4). Applies to entries AND exits: together with the
kill switch it is the only thing allowed to stop an exit. It validates the
already-resolved intent against live inputs the CALLER passes in the call -
nothing is fetched, nothing is cached, nothing has a default:

  * any None/NaN input -> deny <ARG>_MISSING (SPEC §2, G10)
  * broker_status != "connected" -> BROKER_NOT_CONNECTED
  * latency_ms > max_latency_ms -> LATENCY_TOO_HIGH
  * bid/ask must be finite positive and bid < ask -> QUOTE_CROSSED otherwise; spread > max_spread_bps -> SPREAD_TOO_WIDE
  * symbol not in allowed_symbols -> SYMBOL_NOT_ALLOWED
  * size_available: for an exit it is BASE available and must cover resolved.amount_base;
    for an entry it is QUOTE (USD) available and must cover resolved.amount_usd -> INSUFFICIENT_SIZE
  * notional bounds (declared OPTIONAL: None = check omitted, said so in the verdict reason):
    min_notional_usd -> NOTIONAL_BELOW_MIN, max_notional_usd -> NOTIONAL_ABOVE_MAX
  * fat-finger (OPTIONAL): if max_ref_deviation_bps is configured, ref_price is REQUIRED in the call
    (missing -> REF_PRICE_MISSING); |mid/ref - 1| > max -> PRICE_DEVIATION

quantize(): rounds the base amount to the venue step ALWAYS towards less exposure (floor, for entries
and exits alike - an exit rounded up could sell more than the position and flip it). If flooring
leaves zero -> deny AMOUNT_BELOW_STEP. It is FORBIDDEN to grow an order to reach a venue minimum: an
order below min_notional is denied, never enlarged (the exposure_engine.py:81 pattern - turning "too
small" into "bigger than asked").

Configuration has no defaults: allowed_symbols, max_latency_ms and max_spread_bps are required and
validated at construction; the optional fields are None by declaration.
"""
import math
from dataclasses import dataclass
from typing import FrozenSet, Optional

from .intent import Intent, Resolved
from .verdict import Verdict


def _finite(x) -> bool:
    try:
        return math.isfinite(float(x))
    except (TypeError, ValueError):
        return False


@dataclass(frozen=True)
class QuantizeResult:
    verdict: Verdict
    amount_base: float          # quantized (floored) base amount; 0.0 when denied
    notional_usd: float


class OrderSanity:
    def __init__(self, allowed_symbols: FrozenSet[str], max_latency_ms: float, max_spread_bps: float,
                 min_notional_usd: Optional[float] = None, max_notional_usd: Optional[float] = None,
                 max_ref_deviation_bps: Optional[float] = None):
        if allowed_symbols is None:
            raise ValueError("ALLOWED_SYMBOLS_MISSING: pass an explicit frozenset (empty = deny all)")
        if not _finite(max_latency_ms) or float(max_latency_ms) <= 0:
            raise ValueError(f"MAX_LATENCY_MS_INVALID: {max_latency_ms!r}")
        if not _finite(max_spread_bps) or float(max_spread_bps) <= 0:
            raise ValueError(f"MAX_SPREAD_BPS_INVALID: {max_spread_bps!r}")
        for name, v in (("min_notional_usd", min_notional_usd), ("max_notional_usd", max_notional_usd),
                        ("max_ref_deviation_bps", max_ref_deviation_bps)):
            if v is not None and (not _finite(v) or float(v) <= 0):
                raise ValueError(f"{name.upper()}_INVALID: {v!r} (None = check omitted)")
        if min_notional_usd is not None and max_notional_usd is not None and float(min_notional_usd) > float(max_notional_usd):
            raise ValueError("NOTIONAL_BOUNDS_INVALID: min > max")
        self.allowed_symbols = frozenset(allowed_symbols)
        self.max_latency_ms = float(max_latency_ms)
        self.max_spread_bps = float(max_spread_bps)
        self.min_notional_usd = None if min_notional_usd is None else float(min_notional_usd)
        self.max_notional_usd = None if max_notional_usd is None else float(max_notional_usd)
        self.max_ref_deviation_bps = None if max_ref_deviation_bps is None else float(max_ref_deviation_bps)

    def check(self, intent: Intent, resolved: Resolved, *, broker_status: Optional[str], latency_ms: Optional[float],
              bid: Optional[float], ask: Optional[float], size_available: Optional[float],
              is_exit: bool, ref_price: Optional[float] = None) -> Verdict:
        tag = f"client_id={intent.client_id} {intent.symbol} {intent.side} {'EXIT' if is_exit else 'ENTRY'}"
        # --- resolved amounts must be finite positive (they are, post resolve_units, but this is a boundary) ---
        if not (_finite(resolved.amount_usd) and resolved.amount_usd > 0 and _finite(resolved.amount_base) and resolved.amount_base > 0):
            return Verdict.deny("RESOLVED_AMOUNT_INVALID", f"usd={resolved.amount_usd!r} base={resolved.amount_base!r}; {tag}")
        # --- inputs: missing is missing ---
        if broker_status is None:
            return Verdict.deny("BROKER_STATUS_MISSING", tag)
        if latency_ms is None or not _finite(latency_ms):
            return Verdict.deny("LATENCY_MISSING", f"latency_ms={latency_ms!r}; {tag}")
        if bid is None or not _finite(bid):
            return Verdict.deny("BID_MISSING", f"bid={bid!r}; {tag}")
        if ask is None or not _finite(ask):
            return Verdict.deny("ASK_MISSING", f"ask={ask!r}; {tag}")
        if size_available is None or not _finite(size_available):
            return Verdict.deny("SIZE_AVAILABLE_MISSING", f"size_available={size_available!r}; {tag}")
        # --- semantics ---
        if str(broker_status) != "connected":
            return Verdict.deny("BROKER_NOT_CONNECTED", f"broker_status={broker_status!r}; {tag}")
        if float(latency_ms) > self.max_latency_ms:
            return Verdict.deny("LATENCY_TOO_HIGH", f"{float(latency_ms):.1f}ms > {self.max_latency_ms}ms; {tag}")
        bid, ask = float(bid), float(ask)
        if bid <= 0 or ask <= 0 or bid >= ask:
            return Verdict.deny("QUOTE_CROSSED", f"bid={bid} ask={ask}; {tag}")
        mid = (bid + ask) / 2.0
        spread_bps = (ask - bid) / mid * 10_000.0
        if spread_bps > self.max_spread_bps:
            return Verdict.deny("SPREAD_TOO_WIDE", f"{spread_bps:.2f}bps > {self.max_spread_bps}bps; {tag}")
        if intent.symbol not in self.allowed_symbols:
            return Verdict.deny("SYMBOL_NOT_ALLOWED", f"{intent.symbol!r} not in allowlist; {tag}")
        need = resolved.amount_base if is_exit else resolved.amount_usd
        unit = "base" if is_exit else "quote"
        if float(size_available) < need:
            return Verdict.deny("INSUFFICIENT_SIZE", f"available {float(size_available)} {unit} < needed {need} {unit}; {tag}")
        if self.min_notional_usd is not None and resolved.amount_usd < self.min_notional_usd:
            return Verdict.deny("NOTIONAL_BELOW_MIN",
                                f"{resolved.amount_usd:.4f} USD < min {self.min_notional_usd}; NOT enlarged to reach the minimum; {tag}")
        if self.max_notional_usd is not None and resolved.amount_usd > self.max_notional_usd:
            return Verdict.deny("NOTIONAL_ABOVE_MAX", f"{resolved.amount_usd:.4f} USD > max {self.max_notional_usd}; {tag}")
        if self.max_ref_deviation_bps is not None:
            if ref_price is None or not _finite(ref_price) or float(ref_price) <= 0:
                return Verdict.deny("REF_PRICE_MISSING", f"max_ref_deviation_bps configured but ref_price={ref_price!r}; {tag}")
            dev = abs(mid / float(ref_price) - 1.0) * 10_000.0
            if dev > self.max_ref_deviation_bps:
                return Verdict.deny("PRICE_DEVIATION", f"mid {mid} deviates {dev:.1f}bps from ref {ref_price} > {self.max_ref_deviation_bps}; {tag}")
        omitted = [n for n, v in (("min_notional", self.min_notional_usd), ("max_notional", self.max_notional_usd),
                                  ("ref_deviation", self.max_ref_deviation_bps)) if v is None]
        return Verdict.allow("ORDER_SANITY_OK", ("checks omitted by config: " + ",".join(omitted)) if omitted else "")

    def quantize(self, intent: Intent, resolved: Resolved, *, amount_step: Optional[float], price: float) -> QuantizeResult:
        """Floor base amount to `amount_step` (venue lot step). Never rounds up,
        never enlarges to a minimum. amount_step None/invalid -> AMOUNT_STEP_MISSING."""
        tag = f"client_id={intent.client_id} {intent.symbol} {intent.side}"
        if amount_step is None or not _finite(amount_step) or float(amount_step) <= 0:
            return QuantizeResult(Verdict.deny("AMOUNT_STEP_MISSING", f"amount_step={amount_step!r}; {tag}"), 0.0, 0.0)
        if not _finite(price) or float(price) <= 0:
            return QuantizeResult(Verdict.deny("PRICE_INVALID", f"price={price!r}; {tag}"), 0.0, 0.0)
        step = float(amount_step)
        # floor with a tiny epsilon so 0.3/0.1 -> 3 and not 2 due to binary representation
        n = math.floor(float(resolved.amount_base) / step + 1e-9)
        q = n * step
        if n <= 0 or q <= 0:
            return QuantizeResult(Verdict.deny("AMOUNT_BELOW_STEP",
                                               f"base {resolved.amount_base} floors to 0 at step {step}; not sent, not bumped to the minimum; {tag}"), 0.0, 0.0)
        # never more than asked
        assert q <= float(resolved.amount_base) + 1e-12
        return QuantizeResult(Verdict.allow("QUANTIZED"), q, q * float(price))
