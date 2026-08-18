"""Daily limits (SPEC §4.4, decision B). Generic counters with a UTC rollover.

Order of evaluation in check() - this order IS the contract:
  1. is_exit(intent, position)  -> allow("EXIT_BYPASSES_DAILY_LIMITS") WITHOUT touching the file.
     A corrupt/absent/backwards-day stats file can never trap a position.
  2. read daily_stats.json
       ABSENT      -> fresh day (no counters); entries evaluated against zero.
       UNREADABLE  -> deny("DAILY_STATS_UNREADABLE")            (decision B)
       key missing -> deny("DAILY_STATS_KEY_MISSING:<key>")     (never a default; the "default 100 -> $2 cap" pattern)
  3. day handling with the injected clock only:
       file day <  today -> rollover: counters restart, previous day's numbers go to the ledger as
                            DAILY_STATS_RESET; never a silent reset.
       file day >  today -> clock went backwards: deny("DAILY_STATS_CLOCK_BACKWARDS"); nothing is reset,
                            an exhausted limit is not reopened.
  4. fees_unverified flag set on the day -> deny("DAILY_FEES_UNVERIFIED")
  5. limits: max_notional_usd_per_order (this order), max_trades_per_day, max_daily_loss_usd
       (net P&L = gross realized - fees). Reaching one -> INTENT_DENIED in the ledger and every later
       entry that day is denied.

P&L is NET of fees. record_fill(intent, filled_usd, fee_usd): a fill's fee is realized P&L; fee_usd=None
never counts as zero. If Limits.worst_case_fee_bps is set, the fee is charged at that worst-case rate and
the fill is counted in fees_estimated; if it is not set, the day is marked fees_unverified and entries
are denied until a human resets the file (the "+$0.29 gross, negative net" pattern).

Exits are recorded too (record_fill counts them) so the numbers are true; they are just never checked.
Every denial carries the intent (client_id) and the offending numbers in the reason.
"""
import logging
import math
from dataclasses import dataclass, asdict
from typing import Optional

from .clock import Clock, iso
from .errors import ConcurrentWriterDetected
from .intent import ExposurePredicate, Intent, PositionSnapshot, Resolved
from .paths import Paths
from .statefile import StateFile, WriterIdentity
from .verdict import Verdict

SCHEMA_VERSION = 1
REQUIRED_KEYS = ("day_utc", "trades", "filled_usd", "gross_pnl_usd", "fees_usd", "fees_estimated", "fees_unverified", "updated_ts_utc")


@dataclass(frozen=True)
class Limits:
    max_trades_per_day: Optional[int] = None          # None = not enforced (declared optional)
    max_daily_loss_usd: Optional[float] = None        # None = not enforced; positive number = allowed loss
    max_notional_usd_per_order: Optional[float] = None
    worst_case_fee_bps: Optional[float] = None        # None => an unknown fee marks the day fees_unverified


@dataclass(frozen=True)
class DailyStats:
    day_utc: str
    trades: int
    filled_usd: float
    gross_pnl_usd: float
    fees_usd: float
    fees_estimated: int
    fees_unverified: bool
    updated_ts_utc: str
    schema_version: int = SCHEMA_VERSION

    @property
    def net_pnl_usd(self) -> float:
        return self.gross_pnl_usd - self.fees_usd

    def as_dict(self) -> dict:
        return asdict(self)


def _fresh(day: str, ts: str) -> DailyStats:
    return DailyStats(day, 0, 0.0, 0.0, 0.0, 0, False, ts)


def _num_ok(x) -> bool:
    try:
        return math.isfinite(float(x))
    except (TypeError, ValueError):
        return False


class DailyLimits:
    def __init__(self, paths: Paths, limits: Limits, is_exit: ExposurePredicate, clock: Clock,
                 ident: WriterIdentity, ledger=None, logger: logging.Logger | None = None):
        self.paths = paths
        self.limits = limits
        self.is_exit = is_exit
        self.clock = clock
        self.ident = ident
        self.ledger = ledger
        self.log = logger or logging.getLogger("deadman.daily_limits")
        self.file = StateFile(paths.daily_stats, ident, clock)

    # ---------- state ----------
    def _load(self):
        """Returns (status, stats|None, seal, reason). status in OK/ABSENT/UNREADABLE/KEY_MISSING/CLOCK_BACKWARDS.
        Performs the rollover (persist + ledger) when the file day is older than today."""
        r = self.file.read()
        today = self.clock.today_utc()
        if r.status == "ABSENT":
            return "ABSENT", None, None, ""
        if r.status == "UNREADABLE":
            return "UNREADABLE", None, None, r.error
        d = r.data or {}
        missing = [k for k in REQUIRED_KEYS if k not in d]
        if missing:
            return "KEY_MISSING", None, r.seal, f"keys {missing} missing in {self.paths.daily_stats.name}"
        try:
            st = DailyStats(str(d["day_utc"]), int(d["trades"]), float(d["filled_usd"]), float(d["gross_pnl_usd"]),
                            float(d["fees_usd"]), int(d["fees_estimated"]), bool(d["fees_unverified"]),
                            str(d["updated_ts_utc"]), int(d.get("schema_version", SCHEMA_VERSION)))
        except (TypeError, ValueError) as e:
            return "UNREADABLE", None, r.seal, f"field type invalid: {e}"
        for k in ("filled_usd", "gross_pnl_usd", "fees_usd"):
            if not _num_ok(getattr(st, k)):
                return "UNREADABLE", None, r.seal, f"{k} not finite"
        if st.day_utc > today:
            return "CLOCK_BACKWARDS", st, r.seal, f"stats day {st.day_utc} is after clock day {today}"
        if st.day_utc < today:
            fresh = _fresh(today, iso(self.clock.now_utc()))
            seal = self._write(fresh, r.seal)
            self._ledger("DAILY_STATS_RESET", {"from_day": st.day_utc, "to_day": today, "previous": st.as_dict()})
            self.log.info("[DAILY_LIMITS] rollover %s -> %s (previous: %s)", st.day_utc, today, st.as_dict())
            return "OK", fresh, seal, ""
        return "OK", st, r.seal, ""

    def _write(self, st: DailyStats, expected):
        try:
            return self.file.write(st.as_dict(), expected=expected)
        except ConcurrentWriterDetected as e:
            self._ledger("CONCURRENT_WRITER_DETECTED", {"file": self.paths.daily_stats.name,
                                                       "expected": None if e.expected is None else e.expected.as_dict(),
                                                       "found": None if e.found is None else e.found.as_dict()})
            raise

    def stats(self) -> Optional[DailyStats]:
        status, st, _, _ = self._load()
        if status == "ABSENT":
            return _fresh(self.clock.today_utc(), iso(self.clock.now_utc()))
        return st  # None if unreadable/key-missing; CLOCK_BACKWARDS returns the file's stats untouched

    # ---------- check ----------
    def check(self, intent: Intent, resolved: Resolved, position: Optional[PositionSnapshot] = None) -> Verdict:
        if self.is_exit(intent, position):
            return Verdict.allow("EXIT_BYPASSES_DAILY_LIMITS", "exits are never checked against daily limits")
        tag = f"client_id={intent.client_id} {intent.symbol} {intent.side}"
        status, st, _, why = self._load()
        if status == "UNREADABLE":
            return self._deny(intent, "DAILY_STATS_UNREADABLE", f"{why}; {tag}")
        if status == "KEY_MISSING":
            return self._deny(intent, "DAILY_STATS_KEY_MISSING", f"{why}; no default is applied; {tag}")
        if status == "CLOCK_BACKWARDS":
            return self._deny(intent, "DAILY_STATS_CLOCK_BACKWARDS", f"{why}; entries denied, nothing reset; {tag}")
        if status == "ABSENT":
            st = _fresh(self.clock.today_utc(), iso(self.clock.now_utc()))
        assert st is not None
        if st.fees_unverified:
            return self._deny(intent, "DAILY_FEES_UNVERIFIED",
                              f"a fill today had no fee and no worst_case_fee_bps is configured: net P&L cannot be trusted; {tag}")
        L = self.limits
        if L.max_notional_usd_per_order is not None and resolved.amount_usd > L.max_notional_usd_per_order:
            return self._deny(intent, "DAILY_MAX_NOTIONAL", f"order {resolved.amount_usd:.2f} USD > max {L.max_notional_usd_per_order}; {tag}")
        if L.max_trades_per_day is not None and st.trades >= L.max_trades_per_day:
            return self._deny(intent, "DAILY_MAX_TRADES", f"trades today {st.trades} >= max {L.max_trades_per_day}; {tag}")
        if L.max_daily_loss_usd is not None and st.net_pnl_usd <= -abs(L.max_daily_loss_usd):
            return self._deny(intent, "DAILY_LOSS_LIMIT",
                              f"net P&L today {st.net_pnl_usd:.2f} (gross {st.gross_pnl_usd:.2f} - fees {st.fees_usd:.2f}) "
                              f"<= -{abs(L.max_daily_loss_usd)}; {tag}")
        return Verdict.allow("DAILY_LIMITS_OK")

    def _deny(self, intent: Intent, code: str, reason: str) -> Verdict:
        self._ledger("INTENT_DENIED", {"code": code, "reason": reason, "intent": intent.as_dict(), "by": "deadman.daily_limits"})
        return Verdict.deny(code, reason)

    # ---------- record ----------
    def _current_for_write(self):
        status, st, seal, why = self._load()
        if status in ("UNREADABLE", "KEY_MISSING"):
            raise RuntimeError(f"daily_stats {status}: {why} - a human must delete/repair {self.paths.daily_stats}")
        if status == "ABSENT":
            return _fresh(self.clock.today_utc(), iso(self.clock.now_utc())), None
        # CLOCK_BACKWARDS: still record against the file's day (never lose a fill), entries stay denied
        return st, seal

    def record_fill(self, intent: Intent, filled_usd: float, fee_usd: Optional[float]) -> DailyStats:
        """Entries AND exits count. fee_usd=None never counts as zero (see module docstring)."""
        if not _num_ok(filled_usd) or float(filled_usd) < 0:
            raise ValueError(f"FILLED_USD_INVALID: {filled_usd!r} for {intent.client_id}")
        st, seal = self._current_for_write()
        fees = st.fees_usd
        est = st.fees_estimated
        unverified = st.fees_unverified
        if fee_usd is None or not _num_ok(fee_usd):
            if self.limits.worst_case_fee_bps is not None:
                fees += float(filled_usd) * float(self.limits.worst_case_fee_bps) / 10_000.0
                est += 1
            else:
                unverified = True
        else:
            fees += abs(float(fee_usd))
        new = DailyStats(st.day_utc, st.trades + 1, st.filled_usd + float(filled_usd), st.gross_pnl_usd, fees, est,
                         unverified, iso(self.clock.now_utc()))
        self._write(new, seal)
        return new

    def record_pnl(self, gross_realized_pnl_usd: float) -> DailyStats:
        """Gross realized P&L of a closed round trip; fees are accounted per fill in record_fill."""
        if not _num_ok(gross_realized_pnl_usd):
            raise ValueError(f"PNL_INVALID: {gross_realized_pnl_usd!r}")
        st, seal = self._current_for_write()
        new = DailyStats(st.day_utc, st.trades, st.filled_usd, st.gross_pnl_usd + float(gross_realized_pnl_usd),
                         st.fees_usd, st.fees_estimated, st.fees_unverified, iso(self.clock.now_utc()))
        self._write(new, seal)
        return new

    # ---------- helpers ----------
    def _ledger(self, kind: str, payload: dict) -> None:
        if self.ledger is None:
            return
        try:
            self.ledger.append(kind, payload, actor="deadman.daily_limits")
        except Exception as e:
            self.log.critical("[DAILY_LIMITS] ledger append failed for %s: %s", kind, e)
