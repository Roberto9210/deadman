"""deadman <-> freqtrade: the gate, the fill recorder and the clock.

This module holds everything that does NOT need freqtrade imported. It is
plain Python against the `deadman` API plus duck-typed freqtrade objects, so
the whole thing is testable without freqtrade and without an exchange
(`tests/test_deadman_freqtrade.py` imports only this file).

The freqtrade glue is `DeadmanGuardMixin` at the bottom: five callbacks, each
one wrapped so that an exception inside deadman can never decide a trade by
accident. That wrapping is not decoration - it is the reason the file exists;
see "the fail-open hole" below.

--------------------------------------------------------------------------
What this integration wires, and what it deliberately does not
--------------------------------------------------------------------------
Used:      KillSwitch, EntryHalt, Intent/resolve_units, DailyLimits,
           OrderSanity, Ledger, injectable Clock.
NOT used:  BrokerPort, HonestExecutor.

freqtrade already owns order placement, polling, the unfilled timeout, the
cancel and the reconciliation of open orders at startup. Running
HonestExecutor next to it would mean two write-ahead records, two client
order ids and two reconcilers for one order. So the post-fill state machine
here is FREQTRADE'S, not deadman's, and this integration does not give you
deadman's guarantees G1-G9. That is a real loss and it is stated in the
README, not hidden in a docstring.

--------------------------------------------------------------------------
The fail-open hole in freqtrade's callback contract (verified, not assumed)
--------------------------------------------------------------------------
freqtrade calls the confirm_* callbacks through `strategy_safe_wrapper(...,
default_retval=True)` (freqtrade/strategy/strategy_wrapper.py, call sites
freqtradebot.py:934 and :2142, backtesting.py:1193 and :915). The wrapper
catches EVERY exception and returns the default - which is True. So a
strategy whose risk check raises does not stop the trade: it places it.

Therefore every callback in the mixin catches its own exceptions:
  * entry  -> False on any internal failure (fail-closed: no new exposure),
  * exit   -> True on any internal failure (fail-open: an internal error must
              never trap a position - deadman SPEC 4.4, the asymmetry), and
              an EntryHalt is set so no NEW exposure is taken while broken.
`order_filled` is wrapped with `supress_error=True` (freqtradebot.py:2384,
backtesting.py:813): a failure there is swallowed by freqtrade and would
leave the day's numbers wrong in silence, so a failure to record a fill sets
the EntryHalt too.

--------------------------------------------------------------------------
Units, currencies and the one honest lie
--------------------------------------------------------------------------
deadman says "USD"; freqtrade says "stake currency". This module maps the
stake currency onto deadman's USD fields verbatim. If your stake currency is
USDT then every "usd" number here is USDT, and USDT is not USD. deadman
cannot know your stake currency's peg; naming it is the caller's job.
"""
import logging
import math
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Optional, Protocol

from deadman import (
    DailyLimits,
    EntryHalt,
    Intent,
    KillSwitch,
    Ledger,
    Limits,
    OrderSanity,
    Paths,
    SystemClock,
    Verdict,
    WriterIdentity,
    resolve_units,
    spot_long_only_is_exit,
)
from deadman.errors import (
    ContractSizeMissing,
    IntentAmountInvalid,
    IntentUnitsInvalid,
    PriceInvalid,
)

log = logging.getLogger("deadman.freqtrade")

__all__ = [
    "FreqtradeClock",
    "Quotes",
    "QuotesProvider",
    "TickerQuotes",
    "DeclaredSpreadQuotes",
    "QuotesNotConfigured",
    "DeadmanGate",
    "DeadmanGuardMixin",
]


# --------------------------------------------------------------------------
# clock
# --------------------------------------------------------------------------
class FreqtradeClock:
    """deadman's injectable Clock (SPEC 5.6) driven by freqtrade's own
    `current_time`, which every callback receives.

    In live and dry-run `current_time` is `datetime.now(UTC)`, so this is the
    wall clock. In a backtest it is the candle's timestamp, which is what
    makes DailyLimits roll over on BACKTEST days instead of on the day the
    backtest happens to be run. That is the whole point of the Clock protocol.

    Before the first callback there is no freqtrade time to use, so `now_utc`
    falls back to the system clock and says so through `using_fallback`. The
    mixin sets the time in every callback that receives one, so the only
    unclocked window is `bot_start` itself, where nothing is written.

    `monotonic()` is the real process monotonic clock: it is used for anchor
    cadence, which is wall-clock work and must not follow backtest time.
    """

    def __init__(self, fallback=None):
        self._fallback = fallback or SystemClock()
        self._now: Optional[datetime] = None

    def set(self, t: Optional[datetime]) -> None:
        if t is None:
            return
        if t.tzinfo is None:
            raise ValueError("FreqtradeClock.set requires a timezone-aware datetime")
        self._now = t.astimezone(timezone.utc)

    @property
    def using_fallback(self) -> bool:
        return self._now is None

    def now_utc(self) -> datetime:
        return self._now if self._now is not None else self._fallback.now_utc()

    def today_utc(self) -> str:
        return self.now_utc().strftime("%Y-%m-%d")

    def monotonic(self) -> float:
        return time.monotonic()


# --------------------------------------------------------------------------
# quotes: the inputs OrderSanity needs and freqtrade does not hand you
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Quotes:
    """What OrderSanity requires in the call. Any field left None denies the
    ENTRY with `<ARG>_MISSING` - that is deadman's contract, not a bug.
    `source` travels to the ledger on every single entry so a reader can tell
    a real venue quote from a declared simulation without trusting prose."""

    bid: Optional[float]
    ask: Optional[float]
    latency_ms: Optional[float]
    broker_status: Optional[str]
    source: str


class QuotesProvider(Protocol):
    def __call__(self, pair: str, rate: float) -> Quotes: ...


class QuotesNotConfigured(Exception):
    """Raised at construction. There is no default quote source: inventing a
    bid/ask around the rate is exactly the "plausible default" the kit exists
    to refuse, so the caller must name where quotes come from."""


class TickerQuotes:
    """Real quotes for live and dry-run: `dp.ticker(pair)` is a network call
    (freqtrade/data/dataprovider.py:565-577), so the time it takes IS a
    latency measurement - measured here, not assumed.

    Not usable in a backtest: it would hit the exchange once per candle.
    `__call__` returns everything None (=> the entry is denied) when the
    ticker is empty or raises, and never guesses.
    """

    def __init__(self, dp, max_ticker_age_s: Optional[float] = None):
        self.dp = dp
        self.max_ticker_age_s = max_ticker_age_s

    def __call__(self, pair: str, rate: float) -> Quotes:
        t0 = time.monotonic()
        try:
            t = self.dp.ticker(pair) or {}
        except Exception as e:  # ExchangeError is already swallowed by dp.ticker into {}
            ms = (time.monotonic() - t0) * 1000.0
            log.warning("[deadman] ticker(%s) raised %s: %s", pair, type(e).__name__, e)
            return Quotes(None, None, ms, None, f"ticker_failed:{type(e).__name__}")
        ms = (time.monotonic() - t0) * 1000.0
        bid, ask = t.get("bid"), t.get("ask")
        if bid is None or ask is None:
            return Quotes(None, None, ms, None, "ticker_empty")
        # Freshness. ccxt reports the ticker's own timestamp only on venues
        # that send one - Kraken does not (observed: `timestamp` is None on a
        # real BTC/USDT ticker). So a max age configured against such a venue
        # is a check that exists and never runs, which is the failure this kit
        # is about. If the caller asked for an age policy and the age cannot be
        # established, the quote is refused: for an ENTRY that is fail-closed,
        # and exits do not consult order sanity unless you opted in.
        age_s: Optional[float] = None
        ts = t.get("timestamp")
        if ts is not None:
            age_s = max(0.0, time.time() - float(ts) / 1000.0)
        if self.max_ticker_age_s is not None:
            if age_s is None:
                return Quotes(None, None, ms, None,
                              f"ticker_age_unknown:venue_sends_no_timestamp:policy_max_{self.max_ticker_age_s}s")
            if age_s > self.max_ticker_age_s:
                return Quotes(None, None, ms, None, f"ticker_stale:{age_s:.1f}s")
        src = "exchange_ticker" if age_s is not None else "exchange_ticker:age_unknown"
        return Quotes(float(bid), float(ask), ms, "connected", src)


class DeclaredSpreadQuotes:
    """A DECLARED SIMULATION, for backtests only.

    A backtest has no order book, so there is no honest way to produce a
    bid/ask. This builds them symmetrically around the rate freqtrade is
    about to use, with a spread and a latency the caller states explicitly -
    both are required arguments precisely so that nobody gets a plausible
    number for free. Every ledger entry fed by this provider carries
    `quote_source: "declared_spread_simulation"`, so a run gated by simulated
    quotes can never be mistaken for a run gated by a venue.
    """

    SOURCE = "declared_spread_simulation"

    def __init__(self, *, spread_bps: float, latency_ms: float, broker_status: str = "connected"):
        if not (isinstance(spread_bps, (int, float)) and math.isfinite(spread_bps) and spread_bps > 0):
            raise ValueError(f"DECLARED_SPREAD_INVALID: {spread_bps!r}")
        if not (isinstance(latency_ms, (int, float)) and math.isfinite(latency_ms) and latency_ms >= 0):
            raise ValueError(f"DECLARED_LATENCY_INVALID: {latency_ms!r}")
        self.spread_bps = float(spread_bps)
        self.latency_ms = float(latency_ms)
        self.broker_status = broker_status

    def __call__(self, pair: str, rate: float) -> Quotes:
        if not (isinstance(rate, (int, float)) and math.isfinite(rate) and rate > 0):
            return Quotes(None, None, self.latency_ms, self.broker_status, self.SOURCE + ":rate_invalid")
        half = float(rate) * (self.spread_bps / 2.0) / 10_000.0
        return Quotes(float(rate) - half, float(rate) + half, self.latency_ms, self.broker_status, self.SOURCE)


# --------------------------------------------------------------------------
# the gate
# --------------------------------------------------------------------------
class DeadmanGate:
    """Owns the deadman state for one bot and answers two questions:
    may this ENTRY be placed, and may this EXIT be placed.

    The two answers are not symmetric, and that asymmetry is the product
    (deadman SPEC 4.4):

      ENTRY  kill switch -> entry halt -> units -> daily limits -> order sanity
      EXIT   kill switch [-> order sanity, only if you opt in]

    Nothing else may stop an exit. An exhausted daily limit, an entry halt, a
    stats file that will not parse, a missing quote: none of them can trap an
    open position, because none of them is consulted on the exit path.

    The kill switch DOES stop exits. That is deadman's decision A, stated
    loudly: the sentinel means "a human takes over", and in freqtrade it means
    an open trade stays open until the file is removed. If that is not the
    behaviour you want, you do not want a kill switch.
    """

    def __init__(
        self,
        root,
        *,
        limits: Limits,
        allowed_pairs,
        quotes: Optional[QuotesProvider],
        max_latency_ms: float,
        max_spread_bps: float,
        min_notional_usd: Optional[float] = None,
        max_notional_usd: Optional[float] = None,
        max_ref_deviation_bps: Optional[float] = None,
        exit_sanity: bool = False,
        clock=None,
        publisher: Optional[Callable[[dict], str]] = None,
        stake_currency: str = "USDT",
        logger: Optional[logging.Logger] = None,
    ):
        if quotes is None:
            raise QuotesNotConfigured(
                "QUOTES_NOT_CONFIGURED: OrderSanity needs bid/ask/latency/broker_status in the call "
                "and freqtrade does not supply them. Pass TickerQuotes(self.dp) for live/dry-run, or "
                "DeclaredSpreadQuotes(spread_bps=..., latency_ms=...) for a backtest - and read what "
                "the second one declares before using it."
            )
        self.log = logger or log
        self.clock = clock or FreqtradeClock()
        self.paths = Paths(root)
        self.ident = WriterIdentity(self.clock)
        self.ledger = Ledger(self.paths, self.clock, publisher=publisher)
        self.kill = KillSwitch(self.paths, self.ledger)
        self.halt = EntryHalt(self.paths, self.clock, self.ident, self.ledger)
        self.halt.startup_check()  # a foreign live writer on the halt file is itself a halt
        self.limits_cfg = limits
        self.limits = DailyLimits(self.paths, limits, spot_long_only_is_exit, self.clock, self.ident, self.ledger)
        self.sanity = OrderSanity(
            allowed_symbols=frozenset(allowed_pairs),
            max_latency_ms=max_latency_ms,
            max_spread_bps=max_spread_bps,
            min_notional_usd=min_notional_usd,
            max_notional_usd=max_notional_usd,
            max_ref_deviation_bps=max_ref_deviation_bps,
        )
        self.quotes = quotes
        self.exit_sanity = bool(exit_sanity)
        self.stake_currency = stake_currency

    # ---------------- helpers ----------------
    def _ledger(self, kind: str, payload: dict) -> Optional[int]:
        try:
            return self.ledger.append(kind, payload, actor="deadman.freqtrade").seq
        except Exception as e:  # a denial must be reported even when the ledger is down
            self.log.critical("[deadman] ledger append failed for %s: %s", kind, e)
            return None

    def _deny(self, verdict: Verdict, intent: Optional[Intent], checks: list, extra: dict,
              already_ledgered: bool = False) -> Verdict:
        """`already_ledgered` is not a detail: DailyLimits.check() writes its own
        INTENT_DENIED (deadman/daily_limits.py::_deny), so re-writing one here
        would put the same denial in the chain twice and inflate the count a
        reader uses to judge the day."""
        if not already_ledgered:
            self._ledger("INTENT_DENIED", {
                "code": verdict.code, "reason": verdict.reason, "by": "deadman.freqtrade",
                "intent": intent.as_dict() if intent is not None else None,
                "checks_run": checks, **extra,
            })
        self.log.warning("[deadman] DENIED %s: %s", verdict.code, verdict.reason)
        return verdict

    @staticmethod
    def _intent(pair: str, side: str, amount_base: float, kind: str, client_id: str,
                meta: Optional[Mapping[str, Any]] = None) -> Intent:
        return Intent(symbol=pair, side=side, units="BASE", amount=float(amount_base),
                      kind=kind, client_id=client_id, meta=dict(meta or {}))

    # ---------------- entries ----------------
    def entry_verdict(self, *, pair: str, amount_base: float, rate: float, size_available_quote: Optional[float],
                      client_id: str, meta: Optional[Mapping[str, Any]] = None) -> Verdict:
        """Spot long entry. `size_available_quote` is free stake currency.

        Order of checks is deadman's, not this file's invention, and the list
        of checks that actually RAN travels to the ledger with every entry -
        because a check that exists is not a check that runs.
        """
        checks: list = []
        intent = self._intent(pair, "buy", amount_base, "ENTRY", client_id, meta)

        checks.append("kill_switch")
        v = self.kill.check()
        if not v.allowed:
            return self._deny(v, intent, checks, {"pair": pair})

        checks.append("entry_halt")
        h = self.halt.active()
        if h is not None:
            v = Verdict.deny("ENTRY_HALT_ACTIVE", f"{h.reason} (source={h.source}, auto_clear={h.auto_clear})")
            return self._deny(v, intent, checks, {"pair": pair})

        checks.append("units")
        try:
            resolved = resolve_units(intent, rate)
        except (IntentUnitsInvalid, IntentAmountInvalid, PriceInvalid, ContractSizeMissing) as e:
            v = Verdict.deny(str(e).split(":")[0], str(e))
            return self._deny(v, intent, checks, {"pair": pair})

        checks.append("daily_limits")
        v = self.limits.check(intent, resolved)
        if not v.allowed:
            return self._deny(v, intent, checks, {"pair": pair}, already_ledgered=True)

        checks.append("order_sanity")
        q = self.quotes(pair, rate)
        v = self.sanity.check(intent, resolved, broker_status=q.broker_status, latency_ms=q.latency_ms,
                              bid=q.bid, ask=q.ask, size_available=size_available_quote, is_exit=False)
        if not v.allowed:
            return self._deny(v, intent, checks, {"pair": pair, "quote_source": q.source})

        self._ledger("ORDER_SENT", {
            "stage": "gate_passed", "gate": "deadman.freqtrade.entry", "is_exit": False,
            "pair": pair, "side": "buy", "amount_base": float(amount_base), "rate": float(rate),
            "resolved_usd": resolved.amount_usd, "stake_currency": self.stake_currency,
            "quote_source": q.source, "checks_run": checks, "intent": intent.as_dict(),
            "placed_by": "freqtrade",  # deadman did not send anything; freqtrade will
        })
        return Verdict.allow("DEADMAN_ENTRY_OK", f"checks run: {','.join(checks)}")

    # ---------------- exits ----------------
    def exit_verdict(self, *, pair: str, amount_base: float, rate: float, exit_reason: str,
                     size_available_base: Optional[float], client_id: str,
                     meta: Optional[Mapping[str, Any]] = None) -> Verdict:
        """Spot long exit (a sell). Only the kill switch - and order sanity if
        you opted in - may say no. Everything else is not even consulted."""
        checks: list = []
        intent = self._intent(pair, "sell", amount_base, "EXIT", client_id, meta)

        checks.append("kill_switch")
        v = self.kill.check()
        if not v.allowed:
            return self._deny(v, intent, checks, {"pair": pair, "exit_reason": exit_reason})

        q = None
        if self.exit_sanity:
            checks.append("units")
            try:
                resolved = resolve_units(intent, rate)
            except (IntentUnitsInvalid, IntentAmountInvalid, PriceInvalid, ContractSizeMissing) as e:
                # A unit failure on an EXIT is not a reason to hold a position:
                # it is a reason to say so and let freqtrade place its own order.
                self.log.critical("[deadman] EXIT units unresolved (%s); exit ALLOWED anyway", e)
                self._ledger("USER_NOTE", {"note": "EXIT_UNITS_UNRESOLVED_ALLOWED", "error": str(e),
                                           "pair": pair, "exit_reason": exit_reason})
                resolved = None
            if resolved is not None:
                checks.append("order_sanity")
                q = self.quotes(pair, rate)
                v = self.sanity.check(intent, resolved, broker_status=q.broker_status, latency_ms=q.latency_ms,
                                      bid=q.bid, ask=q.ask, size_available=size_available_base, is_exit=True)
                if not v.allowed:
                    return self._deny(v, intent, checks, {"pair": pair, "exit_reason": exit_reason,
                                                          "quote_source": q.source})

        self._ledger("ORDER_SENT", {
            "stage": "gate_passed", "gate": "deadman.freqtrade.exit", "is_exit": True,
            "pair": pair, "side": "sell", "amount_base": float(amount_base), "rate": float(rate),
            "exit_reason": exit_reason, "quote_source": (q.source if q is not None else "not_consulted"),
            "checks_run": checks, "intent": intent.as_dict(), "placed_by": "freqtrade",
            "not_consulted": ["entry_halt", "daily_limits"] + ([] if self.exit_sanity else ["order_sanity"]),
        })
        return Verdict.allow("DEADMAN_EXIT_OK", f"checks run: {','.join(checks)}")

    # ---------------- fills ----------------
    def record_fill(self, *, pair: str, side: str, is_exit: bool, filled_base: float, price: float,
                    fee_usd: Optional[float], fee_source: str, requested_base: Optional[float],
                    order_id: Optional[str], client_id: str, extra: Optional[dict] = None) -> None:
        """Ledger the fill and hand it to DailyLimits. Entries AND exits count
        towards the day's numbers (they are just never checked on the way out).

        `fee_usd=None` is passed through as None on purpose: DailyLimits then
        either charges `worst_case_fee_bps` or marks the day unverified. It is
        never turned into 0 - which is what `Order.safe_fee_base` would do
        (freqtrade/persistence/trade_model.py:160 returns `self.ft_fee_base or
        0.0`, and ft_fee_base is None whenever the fee was not paid in base).
        """
        filled_usd = float(filled_base) * float(price)
        partial = requested_base is not None and float(filled_base) + 1e-12 < float(requested_base)
        intent = self._intent(pair, side, filled_base, "EXIT" if is_exit else "ENTRY", client_id)
        self._ledger("PARTIAL_FILL" if partial else "FILL", {
            "pair": pair, "side": side, "is_exit": is_exit, "order_id": order_id,
            "filled_base": float(filled_base), "requested_base": requested_base,
            "avg_price": float(price), "filled_usd": filled_usd,
            "fees_usd": fee_usd, "fee_known": fee_usd is not None, "fee_source": fee_source,
            "stake_currency": self.stake_currency, "recorded_by": "deadman.freqtrade",
            **(extra or {}),
        })
        self.limits.record_fill(intent, filled_usd, fee_usd)

    def record_gross_pnl(self, *, pair: str, gross_usd: float, detail: dict) -> None:
        """Gross realized P&L of a closed round trip. GROSS, not net: DailyLimits
        subtracts the fees it accumulated per fill, and freqtrade's own profit
        figures already include fees (trade_model.py:1156 "All calculations
        include fees"). Feeding freqtrade's net here would count fees twice."""
        self._ledger("USER_NOTE", {"note": "ROUND_TRIP_CLOSED", "pair": pair,
                                   "gross_pnl_usd": float(gross_usd), **detail})
        self.limits.record_pnl(float(gross_usd))

    # ---------------- reading ----------------
    def verify(self):
        return self.ledger.verify()

    def stats(self):
        return self.limits.stats()


# --------------------------------------------------------------------------
# the freqtrade glue
# --------------------------------------------------------------------------
class DeadmanGuardMixin:
    """Mix into an IStrategy subclass, FIRST in the bases:

        class MyStrategy(DeadmanGuardMixin, IStrategy):
            ...
            def deadman_build_gate(self) -> DeadmanGate:
                return DeadmanGate(...)

    It implements five callbacks. If your strategy needs its own version of
    one of them, call `super()` from it - the mixin's answer is the gate's.

    Callback signatures verified against the installed freqtrade
    (freqtrade/strategy/interface.py:275, :282, :354, :390, :428). `side` in
    confirm_trade_entry is the DIRECTION ("long"/"short"), not an order side
    (freqtradebot.py:908 `trade_side: LongShort = "short" if is_short else
    "long"`) - a detail worth getting wrong only once.
    """

    deadman: Optional[DeadmanGate] = None
    deadman_clock: Optional[FreqtradeClock] = None
    #: set when a callback failed internally; entries stay blocked by the halt
    deadman_broken: bool = False

    # ---- construction ----
    def deadman_build_gate(self) -> DeadmanGate:
        raise NotImplementedError(
            "deadman_build_gate() must return a DeadmanGate. There is no default: the state "
            "directory, the limits and the quote source are decisions, not defaults."
        )

    def bot_start(self, **kwargs) -> None:
        """Failures here are NOT caught: freqtrade turns them into a
        StrategyError and the bot does not start (interface.py:217 ->
        strategy_wrapper with default_retval=None). A bot that cannot build
        its safety state must not trade."""
        self._deadman_refuse_unsupported_modes()
        self.deadman = self.deadman_build_gate()
        # DeadmanGate builds a FreqtradeClock unless the caller passed another
        # one; only a FreqtradeClock can be driven by freqtrade's current_time.
        self.deadman_clock = self.deadman.clock if isinstance(self.deadman.clock, FreqtradeClock) else None
        if self.deadman_clock is None:
            log.warning("[deadman] the gate uses %s, not a FreqtradeClock: daily rollover will follow "
                        "that clock and not freqtrade's time", type(self.deadman.clock).__name__)
        log.info("[deadman] gate ready at %s", self.deadman.paths.root)

    def _deadman_refuse_unsupported_modes(self) -> None:
        """Spot long-only, checked at startup rather than per order.

        The shipped exit predicate is `spot_long_only_is_exit`: it reads any
        sell as a reduction. On futures an `amount` may be contracts rather
        than base and a long's exit is still a sell, so the gate would keep
        answering plausibly while measuring the wrong thing - which is worse
        than refusing. Refusing in bot_start means the bot does not start
        (interface.py:217 turns this into a StrategyError).
        """
        mode = str((getattr(self, "config", None) or {}).get("trading_mode", "spot"))
        if mode != "spot":
            raise ValueError(
                f"DEADMAN_TRADING_MODE_UNSUPPORTED: trading_mode={mode!r}. This example ships the "
                f"spot long-only exit predicate; pass a net-position predicate and a gate that "
                f"resolves CONTRACTS before using it on {mode}."
            )
        if getattr(self, "can_short", False):
            raise ValueError("DEADMAN_SHORTS_UNSUPPORTED: can_short=True with the spot long-only "
                             "exit predicate; a short's exit is a buy and would look like an entry.")

    def _deadman_tick(self, current_time: Optional[datetime]) -> None:
        if self.deadman_clock is not None:
            try:
                self.deadman_clock.set(current_time)
            except Exception as e:
                log.critical("[deadman] could not set clock from %r: %s", current_time, e)

    def bot_loop_start(self, current_time: datetime, **kwargs) -> None:
        self._deadman_tick(current_time)

    # ---- entries ----
    def confirm_trade_entry(self, pair: str, order_type: str, amount: float, rate: float,
                            time_in_force: str, current_time: datetime, entry_tag,
                            side: str, **kwargs) -> bool:
        self._deadman_tick(current_time)
        try:
            if self.deadman is None:
                log.critical("[deadman] confirm_trade_entry with no gate: entry denied")
                return False
            if side != "long":
                # The shipped exit predicate is spot long-only (deadman
                # SPEC 4.4). A short's exit is a BUY, which this gate would
                # treat as a new entry, so refusing is the only honest answer.
                log.critical("[deadman] side=%r is not supported by the spot long-only gate: denied", side)
                self.deadman._ledger("INTENT_DENIED", {
                    "code": "SHORT_NOT_SUPPORTED", "by": "deadman.freqtrade", "pair": pair, "side": side,
                    "reason": "the shipped predicate is spot_long_only_is_exit; pass a net-position "
                              "predicate and a gate that understands shorts before enabling can_short",
                })
                return False
            v = self.deadman.entry_verdict(
                pair=pair, amount_base=amount, rate=rate,
                size_available_quote=self._deadman_free_quote(),
                client_id=self._deadman_client_id(pair, "buy", current_time),
                meta={"order_type": order_type, "entry_tag": entry_tag, "time_in_force": time_in_force,
                      "runmode": self._deadman_runmode()},
            )
            return bool(v.allowed)
        except Exception as e:
            # freqtrade would return True here (default_retval=True). Do not
            # let it: an internal failure is not a reason to open a position.
            log.critical("[deadman] confirm_trade_entry failed internally (%s: %s); ENTRY DENIED",
                         type(e).__name__, e, exc_info=True)
            self._deadman_break(f"confirm_trade_entry raised {type(e).__name__}: {e}")
            return False

    # ---- exits ----
    def confirm_trade_exit(self, pair: str, trade, order_type: str, amount: float, rate: float,
                           time_in_force: str, exit_reason: str, current_time: datetime, **kwargs) -> bool:
        self._deadman_tick(current_time)
        try:
            if self.deadman is None:
                log.critical("[deadman] confirm_trade_exit with no gate: exit ALLOWED (asymmetry)")
                return True
            v = self.deadman.exit_verdict(
                pair=pair, amount_base=amount, rate=rate, exit_reason=exit_reason,
                size_available_base=self._deadman_free_base(trade),
                client_id=self._deadman_client_id(pair, "sell", current_time),
                meta={"order_type": order_type, "time_in_force": time_in_force,
                      "runmode": self._deadman_runmode()},
            )
            return bool(v.allowed)
        except Exception as e:
            # The mirror image of the entry path, on purpose: an internal
            # failure must never hold a position (deadman SPEC 4.4). New
            # exposure is stopped instead, by the halt.
            log.critical("[deadman] confirm_trade_exit failed internally (%s: %s); EXIT ALLOWED, "
                         "entries halted", type(e).__name__, e, exc_info=True)
            self._deadman_break(f"confirm_trade_exit raised {type(e).__name__}: {e}")
            return True

    # ---- fills ----
    def order_filled(self, pair: str, trade, order, current_time: datetime, **kwargs) -> None:
        self._deadman_tick(current_time)
        try:
            if self.deadman is None:
                return
            is_entry = order.ft_order_side == trade.entry_side
            filled = float(order.safe_filled)
            price = float(order.safe_price)
            if filled <= 0:
                self.deadman._ledger("USER_NOTE", {"note": "ORDER_FILLED_WITH_ZERO", "pair": pair,
                                                   "order_id": getattr(order, "order_id", None),
                                                   "status": getattr(order, "status", None)})
                return
            fee_usd, fee_source = self._deadman_fee(trade, order, filled, price, is_entry)
            self.deadman.record_fill(
                pair=pair, side=("buy" if is_entry else "sell"), is_exit=not is_entry,
                filled_base=filled, price=price, fee_usd=fee_usd, fee_source=fee_source,
                requested_base=float(order.safe_amount) if order.safe_amount else None,
                order_id=getattr(order, "order_id", None),
                client_id=self._deadman_client_id(pair, "buy" if is_entry else "sell", current_time),
                extra={"order_type": getattr(order, "order_type", None),
                       "exit_reason": getattr(trade, "exit_reason", None) if not is_entry else None},
            )
            if not is_entry:
                self._deadman_round_trip(pair, trade, order, filled, price)
        except Exception as e:
            # freqtrade swallows this one (supress_error=True): if the fill is
            # not accounted, the day's numbers are wrong and no NEW exposure
            # may be taken on top of numbers we know are wrong.
            log.critical("[deadman] order_filled failed internally (%s: %s); halting entries",
                         type(e).__name__, e, exc_info=True)
            self._deadman_break(f"order_filled raised {type(e).__name__}: {e}")

    # ---- pieces the hooks use ----
    def _deadman_round_trip(self, pair, trade, order, filled: float, price: float) -> None:
        """GROSS P&L of the round trip, computed here from the two prices.

        It is not read from the trade: at the moment `order_filled` fires for
        the closing order freqtrade has not computed it yet - verified on a
        real backtest, where `trade.is_open` is still True,
        `close_profit_abs` is None and `realized_profit` is 0.

        Only a full close is attributed. Partial exits are recorded as fills
        (above) but their P&L is not split here, and freqtrade does not even
        call confirm_trade_exit for them (backtesting.py:912 skips
        ExitType.PARTIAL_EXIT).
        """
        open_rate = getattr(trade, "open_rate", None)
        amount = getattr(trade, "amount", None)
        if open_rate is None or amount is None:
            return
        if filled + 1e-12 < float(amount):
            self.deadman._ledger("USER_NOTE", {"note": "PARTIAL_EXIT_PNL_NOT_ATTRIBUTED", "pair": pair,
                                               "filled_base": filled, "trade_amount": float(amount)})
            return
        gross = filled * (price - float(open_rate))
        self.deadman.record_gross_pnl(pair=pair, gross_usd=gross, detail={
            "open_rate": float(open_rate), "close_rate": price, "amount_base": filled,
            "note_units": "gross of fees; DailyLimits subtracts the fees recorded per fill",
        })

    @staticmethod
    def _deadman_fee(trade, order, filled: float, price: float, is_entry: bool):
        """(fee_usd, fee_source). freqtrade keeps the fee as a RATE per side
        (`trade.fee_open` / `trade.fee_close`); `order.ft_fee_base` is a fee
        paid in BASE currency and is None unless that happened, so it is not a
        quote-currency fee and is not used here. No rate => None, never 0."""
        rate = getattr(trade, "fee_open", None) if is_entry else getattr(trade, "fee_close", None)
        try:
            r = float(rate)
        except (TypeError, ValueError):
            return None, "unavailable"
        if not math.isfinite(r) or r < 0:
            return None, "unavailable"
        return filled * price * r, ("trade.fee_open" if is_entry else "trade.fee_close")

    def _deadman_break(self, why: str) -> None:
        """Something inside deadman failed. Stop NEW exposure, keep exits open."""
        self.deadman_broken = True
        try:
            if self.deadman is not None:
                self.deadman.halt.set(f"DEADMAN_INTERNAL_FAILURE: {why}",
                                      source="deadman.freqtrade", auto_clear=False)
        except Exception as e:
            log.critical("[deadman] could not even set the entry halt: %s", e)

    def _deadman_client_id(self, pair: str, side: str, current_time: Optional[datetime]) -> str:
        ts = (current_time or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()
        return f"ft:{self._deadman_runmode()}:{pair}:{side}:{ts}"

    def _deadman_runmode(self) -> str:
        dp = getattr(self, "dp", None)
        try:
            return str(dp.runmode) if dp is not None else "unknown"
        except Exception:
            return "unknown"

    def _deadman_free_quote(self) -> Optional[float]:
        """Free stake currency. freqtrade's Wallets.get_free returns 0 for a
        currency it does not know (wallets.py:61-66), which reads as "no
        money" rather than "unknown" - fail-closed for an ENTRY either way."""
        w = getattr(self, "wallets", None)
        if w is None:
            return None
        try:
            return float(w.get_free(self.config["stake_currency"]))
        except Exception:
            return None

    def _deadman_free_base(self, trade) -> Optional[float]:
        w = getattr(self, "wallets", None)
        if w is None:
            return None
        try:
            return float(w.get_free(trade.safe_base_currency))
        except Exception:
            return None
