"""Persistent entry halt (SPEC §4.2, decisions B/D). Blocks NEW exposure only;
exits never consult it. Lives on disk, survives restarts. Cleared by a
reconciliation that sees an empty book (auto_clear) or by a human."""
import logging
from dataclasses import dataclass
from typing import Optional

from .clock import Clock, iso
from .errors import ConcurrentWriterDetected
from .paths import Paths
from .statefile import StateFile, WriterIdentity, Seal

SCHEMA_VERSION = 1


@dataclass(frozen=True)
class HaltRecord:
    active: bool
    reason: str
    source: str
    ts_utc: str
    auto_clear: bool
    schema_version: int = SCHEMA_VERSION


class EntryHalt:
    def __init__(self, paths: Paths, clock: Clock, ident: WriterIdentity, ledger=None, logger: logging.Logger | None = None):
        self.paths = paths
        self.clock = clock
        self.ident = ident
        self.ledger = ledger
        self.log = logger or logging.getLogger("deadman.entry_halt")
        self.file = StateFile(paths.entry_halt, ident, clock)

    # ---- startup ----
    def startup_check(self) -> None:
        """Foreign live writer owns the halt file -> that is itself a halt
        (decision D). Raises ConcurrentWriterDetected after writing the halt."""
        seal = self.file.foreign_live_writer()
        if seal is not None:
            self._set_forced(f"CONCURRENT_WRITER_DETECTED: entry_halt.json owned by live pid {seal.writer_pid} "
                             f"started {seal.writer_started_at}", source="deadman.entry_halt.startup", auto_clear=False)
            self._ledger("CONCURRENT_WRITER_DETECTED", {"file": "entry_halt.json", "found_seal": seal.as_dict()})
            raise ConcurrentWriterDetected(self.paths.entry_halt, None, seal)

    # ---- read ----
    def active(self) -> Optional[HaltRecord]:
        r = self.file.read()
        if r.status == "ABSENT":
            return None
        if r.status == "UNREADABLE":
            return HaltRecord(True, f"ENTRY_HALT_FILE_UNREADABLE: {r.error}", "deadman.entry_halt", "", False)
        d = r.data or {}
        if not d.get("active"):
            return None
        return HaltRecord(True, str(d.get("reason", "")), str(d.get("source", "")), str(d.get("ts_utc", "")),
                          bool(d.get("auto_clear", False)), int(d.get("schema_version", SCHEMA_VERSION)))

    # ---- write ----
    def set(self, reason: str, source: str, auto_clear: bool = False) -> HaltRecord:
        """A halt of too much is acceptable, one too few is not: if another
        writer races us on THIS file, the halt is written forced (decision D)."""
        r = self.file.read()
        cur = self.active()
        # resulting auto_clear: only if no halt existed or the existing one was auto_clear
        eff_auto = bool(auto_clear) and (cur is None or bool(cur.auto_clear))
        rec = HaltRecord(True, str(reason)[:300], source, iso(self.clock.now_utc()), eff_auto)
        try:
            self.file.write(self._to_dict(rec), expected=r.seal if r.status == "OK" else None)
        except ConcurrentWriterDetected as e:
            self.log.critical("[ENTRY_HALT] concurrent writer on entry_halt.json; writing halt FORCED: %s", e)
            self._ledger("CONCURRENT_WRITER_DETECTED", {"file": "entry_halt.json", "expected": _seal(e.expected), "found": _seal(e.found)})
            rec = HaltRecord(True, (f"CONCURRENT_WRITER_DETECTED while setting halt; original: {reason}")[:300],
                             source, rec.ts_utc, False)
            self.file.write(self._to_dict(rec), expected=None, force=True)
        self.log.critical("[ENTRY_HALT] SET by %s: %s (auto_clear=%s) - new entries blocked, exits allowed",
                          source, rec.reason, rec.auto_clear)
        self._ledger("HALT_SET", {"reason": rec.reason, "source": source, "auto_clear": rec.auto_clear})
        return rec

    def _set_forced(self, reason: str, source: str, auto_clear: bool) -> HaltRecord:
        rec = HaltRecord(True, reason[:300], source, iso(self.clock.now_utc()), auto_clear)
        self.file.write(self._to_dict(rec), expected=None, force=True)
        self._ledger("HALT_SET", {"reason": rec.reason, "source": source, "auto_clear": auto_clear})
        return rec

    def clear(self, note: str, only_auto_clear: bool = False) -> bool:
        r = self.file.read()
        cur = self.active()
        if cur is None:
            return False
        if r.status == "UNREADABLE":
            self.log.warning("[ENTRY_HALT] refusing to clear an UNREADABLE halt file (%s); a human must delete it", note)
            return False
        if only_auto_clear and not cur.auto_clear:
            return False
        try:
            self.file.delete(expected=r.seal)
        except ConcurrentWriterDetected as e:
            # someone else wrote in between: do NOT clear; escalate to a manual halt
            self.log.critical("[ENTRY_HALT] concurrent writer during clear; keeping halt and escalating: %s", e)
            self._ledger("CONCURRENT_WRITER_DETECTED", {"file": "entry_halt.json", "expected": _seal(e.expected), "found": _seal(e.found)})
            self._set_forced(f"CONCURRENT_WRITER_DETECTED during clear ({note}); previous: {cur.reason}",
                             source="deadman.entry_halt.clear", auto_clear=False)
            return False
        self.log.warning("[ENTRY_HALT] CLEARED (%s); previous reason: %s", note, cur.reason)
        self._ledger("HALT_CLEARED", {"note": note, "previous_reason": cur.reason, "was_auto_clear": cur.auto_clear})
        return True

    # ---- helpers ----
    @staticmethod
    def _to_dict(rec: HaltRecord) -> dict:
        return {"schema_version": rec.schema_version, "active": rec.active, "reason": rec.reason,
                "source": rec.source, "ts_utc": rec.ts_utc, "auto_clear": rec.auto_clear}

    def _ledger(self, kind: str, payload: dict) -> None:
        if self.ledger is None:
            return
        try:
            self.ledger.append(kind, payload, actor="deadman.entry_halt")
        except Exception as e:  # the halt file is the source of truth; ledger failure is logged, not fatal here
            self.log.critical("[ENTRY_HALT] ledger append failed for %s: %s", kind, e)


def _seal(s: Optional[Seal]) -> Optional[dict]:
    return None if s is None else s.as_dict()
