"""BrokerPort - the only thing deadman needs from a broker (SPEC §4.6, §5.4).

The user implements this. deadman never talks to the network itself.

Order.status is one of exactly four literals. Anything the adapter cannot map
MUST be reported as "unknown" (G4) - never guessed as "closed". Fees the broker
does not report are None (G5), never 0.

Guarantees the adapter must honour (SPEC §5.4):
  G1 create_order either returns an Order with an id, or raises BEFORE the broker
     could have accepted the order; if it cannot tell (network timeout after send)
     it raises OrderMaybeSent(client_id) - deadman then presumes the order ALIVE
     until proven otherwise.
  G2 client_id is forwarded to the broker when it supports idempotent client ids.
  G3 amount_base is in base units (deadman already resolved units).
  G4 fetch_order status in {open, closed, canceled, unknown}; unmappable => "unknown".
  G5 filled in base; average None if no fills; fee_usd None if not reported (never 0).
  G6 cancel_order returns the state AFTER the attempt; cancelling a filled order is
     not an error (returns closed).
  G7 cancel of an order the broker no longer knows => status "unknown", not an exception.
  G8 fetch_open_orders returns the complete list for the symbol or raises; never a
     silent partial list.
  G9 fetch_order_by_client_id(client_id, symbol) returns the Order or None; None is
     an AUTHORITATIVE statement that the broker never accepted an order with that
     client id. An adapter that cannot make that statement must raise instead.
     (Added by the executor tranche: reconcile-by-client-id is what makes a
     timeout survivable without double exposure.)
"""
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, Protocol

from .errors import DeadmanError, OrderMaybeSent  # noqa: F401  (re-exported for adapters)

ORDER_STATUSES = ("open", "closed", "canceled", "unknown")


class BrokerRejected(DeadmanError):
    """create_order refused BEFORE acceptance (G1). Nothing to reconcile."""


@dataclass(frozen=True)
class Order:
    id: str
    symbol: str
    side: str
    status: str                       # open | closed | canceled | unknown
    filled: float                     # base units, cumulative
    average: Optional[float]          # None if no fills
    fee_usd: Optional[float]          # None if the broker did not report it
    client_id: Optional[str] = None
    raw: Mapping[str, Any] = field(default_factory=dict)  # opaque; may carry "fills": [{"id","qty","price","fee_usd"}]

    def __post_init__(self):
        if self.status not in ORDER_STATUSES:
            # an adapter that lets this through violates G4; deadman treats it as unknown
            object.__setattr__(self, "status", "unknown")


class BrokerPort(Protocol):
    def create_order(self, symbol: str, side: str, amount_base: float, order_type: str,
                     price: Optional[float], client_id: str) -> Order: ...
    def fetch_order(self, order_id: str, symbol: str) -> Order: ...
    def cancel_order(self, order_id: str, symbol: str) -> Order: ...
    def fetch_open_orders(self, symbol: str) -> list[Order]: ...
    def fetch_order_by_client_id(self, client_id: str, symbol: str) -> Optional[Order]: ...
