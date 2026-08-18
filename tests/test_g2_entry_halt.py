"""G2 - entry halt: blocks entries, never exits; unreadable => halted;
auto_clear semantics; clear(only_auto_clear)."""
import json

import pytest

from deadman import EntryHalt, WriterIdentity, StateFile
from deadman.errors import ConcurrentWriterDetected


def test_no_file_no_halt(paths, clock, ident):
    assert EntryHalt(paths, clock, ident).active() is None


def test_set_then_active_and_persisted(paths, clock, ident, ledger):
    h = EntryHalt(paths, clock, ident, ledger=ledger)
    rec = h.set("ORDER_STATE_UNKNOWN: X", source="executor", auto_clear=True)
    assert rec.active and rec.auto_clear and rec.ts_utc.endswith("Z")
    # a fresh instance (restart) sees it
    h2 = EntryHalt(paths, clock, ident)
    a = h2.active()
    assert a is not None and a.reason == "ORDER_STATE_UNKNOWN: X" and a.auto_clear
    d = json.loads(paths.entry_halt.read_text(encoding="utf-8"))
    assert d["schema_version"] == 1 and d["writer_pid"] == 1000 and d["write_seq"] == 1
    kinds = [json.loads(l)["kind"] for l in open(paths.ledger_file, encoding="utf-8")]
    assert "HALT_SET" in kinds


def test_unreadable_file_means_halted(paths, clock, ident):
    paths.entry_halt.write_text("{not json", encoding="utf-8")
    a = EntryHalt(paths, clock, ident).active()
    assert a is not None and a.active and a.reason.startswith("ENTRY_HALT_FILE_UNREADABLE")


def test_auto_clear_downgrades_to_manual_if_existing_is_manual(paths, clock, ident):
    h = EntryHalt(paths, clock, ident)
    h.set("manual", "human", auto_clear=False)
    rec = h.set("auto", "reconcile", auto_clear=True)
    assert rec.auto_clear is False  # manual wins
    assert h.clear("try", only_auto_clear=True) is False
    assert h.active() is not None
    assert h.clear("human ok") is True
    assert h.active() is None


def test_auto_clear_stays_auto_when_existing_is_auto(paths, clock, ident):
    h = EntryHalt(paths, clock, ident)
    h.set("a1", "x", auto_clear=True)
    rec = h.set("a2", "x", auto_clear=True)
    assert rec.auto_clear is True
    assert h.clear("book empty", only_auto_clear=True) is True
    assert h.active() is None


def test_clear_when_absent_is_false(paths, clock, ident):
    assert EntryHalt(paths, clock, ident).clear("nothing") is False


def test_clear_refuses_unreadable_file(paths, clock, ident):
    paths.entry_halt.write_text("garbage", encoding="utf-8")
    h = EntryHalt(paths, clock, ident)
    assert h.clear("x") is False
    assert paths.entry_halt.exists()  # a human must delete it


def test_reason_truncated_to_300(paths, clock, ident):
    rec = EntryHalt(paths, clock, ident).set("r" * 1000, "s")
    assert len(rec.reason) == 300


def test_halt_is_consulted_only_for_entries_by_contract(paths, clock, ident):
    """The API has no side parameter on purpose: callers must gate exits away
    from active() (executor step 3 in SPEC §4). This asserts the type contract."""
    h = EntryHalt(paths, clock, ident)
    h.set("x", "y")
    import inspect
    assert "side" not in inspect.signature(h.active).parameters
