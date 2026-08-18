"""Exceptions raised by deadman. Every one of them is loud on purpose: the
library never swallows a failure it cannot vouch for (SPEC §2)."""


class DeadmanError(Exception):
    """Base class."""


class PathsNotWritable(DeadmanError):
    """Paths(root) could not create or write its state directory."""


class StateUnreadable(DeadmanError):
    """A state file exists but cannot be parsed. Callers decide what that
    means (EntryHalt: halted; DailyLimits: entries denied)."""


class ConcurrentWriterDetected(DeadmanError):
    """The writer seal of a state file changed between read and write, or a
    foreign live pid owns the file at startup (SPEC §5.7, decision D)."""

    def __init__(self, path, expected, found):
        self.path = str(path)
        self.expected = expected
        self.found = found
        super().__init__(f"CONCURRENT_WRITER_DETECTED: {self.path} expected seal {expected} found {found}")


class LedgerWriteError(DeadmanError):
    """append()/rotate() could not complete. Nothing was sent to a broker
    on this path; the caller decides whether to halt."""


class LedgerIntegrityError(DeadmanError):
    """The on-disk chain state disagrees with the ledger file tail."""


class IntentUnitsInvalid(DeadmanError):
    pass


class IntentAmountInvalid(DeadmanError):
    pass


class PriceInvalid(DeadmanError):
    pass


class ContractSizeMissing(DeadmanError):
    pass


class OrderMaybeSent(DeadmanError):
    """A BrokerPort raises this when it cannot tell whether the broker
    accepted an order (guarantee G1). deadman treats it as unknown state."""

    def __init__(self, client_id: str, detail: str = ""):
        self.client_id = client_id
        super().__init__(f"ORDER_MAYBE_SENT client_id={client_id} {detail}".strip())
