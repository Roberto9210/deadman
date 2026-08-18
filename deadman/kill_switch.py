"""Kill switch (SPEC §4.1, decision A): the EXISTENCE of one file stops
everything - entries and exits. The file is never opened, read or parsed:
this is the piece that must work when everything else failed, and a parse
is one more failure mode. Any error while checking also blocks."""
import logging
import os

from .paths import Paths
from .verdict import Verdict


class KillSwitch:
    def __init__(self, paths: Paths, ledger=None, logger: logging.Logger | None = None):
        self.paths = paths
        self.ledger = ledger
        self.log = logger or logging.getLogger("deadman.kill_switch")

    def check(self) -> Verdict:
        try:
            present = os.path.exists(self.paths.kill_sentinel)
        except OSError as e:  # e.g. permission/IO error on the directory itself
            return Verdict.deny("KILL_SWITCH_CHECK_FAILED", f"cannot check {self.paths.kill_sentinel}: {e}")
        if present:
            return Verdict.deny("KILL_SWITCH_ACTIVE", f"{self.paths.kill_sentinel.name} present")
        return Verdict.allow("KILL_SWITCH_CLEAR")

    def engage(self, reason: str, actor: str = "user") -> None:
        """Create the sentinel (idempotent). The sentinel is written FIRST;
        the ledger note is best-effort - the sentinel rules."""
        with open(self.paths.kill_sentinel, "a", encoding="utf-8") as f:
            f.write(f"{reason}\n")  # free text for humans; deadman never reads it
        self.log.critical("[KILL_SWITCH] ENGAGED by %s: %s", actor, reason)
        self._ledger("KILL_ENGAGED", {"reason": reason}, actor)

    def release(self, note: str, actor: str = "user") -> bool:
        try:
            os.remove(self.paths.kill_sentinel)
        except FileNotFoundError:
            return False
        self.log.warning("[KILL_SWITCH] RELEASED by %s: %s", actor, note)
        self._ledger("KILL_RELEASED", {"note": note}, actor)
        return True

    def _ledger(self, kind: str, payload: dict, actor: str) -> None:
        if self.ledger is None:
            return
        try:
            self.ledger.append(kind, payload, actor=actor)
        except Exception as e:
            self.log.critical("[KILL_SWITCH] ledger append failed for %s: %s", kind, e)
