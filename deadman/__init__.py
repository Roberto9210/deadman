"""deadman - execution-safety primitives for automated trading systems.
See docs/SPEC.md (v0.1). Paths, clocks,
StateFile (writer seal), Ledger (hash chain, anchored rotation, external anchoring; zero deps), EntryHalt, KillSwitch."""
from .clock import Clock, SystemClock, FakeClock
from .paths import Paths
from .verdict import Verdict
from .statefile import StateFile, WriterIdentity, Seal
from .ledger import Ledger, SignedLedger, Entry, Anchor, VerifyReport, KINDS, GENESIS_HASH, ANCHOR_AFTER
from .entry_halt import EntryHalt, HaltRecord
from .kill_switch import KillSwitch
from .intent import Intent, Resolved, resolve_units, PositionSnapshot, ExposurePredicate, spot_long_only_is_exit, net_position_is_exit
from .daily_limits import DailyLimits, Limits, DailyStats
from .order_sanity import OrderSanity, QuantizeResult
from .broker import BrokerPort, Order, BrokerRejected, ORDER_STATUSES
from .executor import HonestExecutor, ExecResult, ReconcileReport, client_order_id_for
from . import errors

__version__ = "0.2.1"
__all__ = ["Clock", "SystemClock", "FakeClock", "Paths", "Verdict", "StateFile", "WriterIdentity", "Seal",
           "Ledger", "SignedLedger", "Entry", "Anchor", "VerifyReport", "KINDS", "GENESIS_HASH", "ANCHOR_AFTER", "EntryHalt", "HaltRecord",
           "KillSwitch", "Intent", "Resolved", "resolve_units", "PositionSnapshot", "ExposurePredicate",
           "spot_long_only_is_exit", "net_position_is_exit", "DailyLimits", "Limits", "DailyStats",
           "OrderSanity", "QuantizeResult", "BrokerPort", "Order", "BrokerRejected", "ORDER_STATUSES",
           "HonestExecutor", "ExecResult", "ReconcileReport", "client_order_id_for", "errors"]
