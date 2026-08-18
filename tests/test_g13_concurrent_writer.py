"""G13 - concurrent writer detection on state files (decision D): not
prevented, made loud. Two writers are simulated with two WriterIdentity
objects over the same file."""
import json

import pytest

from deadman import StateFile, WriterIdentity, EntryHalt, FakeClock
from deadman.errors import ConcurrentWriterDetected


def _idents(clock):
    a = WriterIdentity(clock, pid=1000, pid_alive=lambda p: p in (1000, 2000))
    b = WriterIdentity(clock, pid=2000, pid_alive=lambda p: p in (1000, 2000))
    return a, b


def test_seal_written_and_incremented(paths, clock, ident):
    sf = StateFile(paths.daily_stats, ident, clock)
    s1 = sf.write({"x": 1}, expected=None)
    s2 = sf.write({"x": 2}, expected=s1)
    assert (s1.write_seq, s2.write_seq) == (1, 2) and s2.writer_pid == 1000
    r = sf.read()
    assert r.status == "OK" and r.data == {"x": 2, "schema_version": 1} and r.seal == s2


def test_second_writer_detects_seal_change_and_does_not_write(paths, clock):
    a, b = _idents(clock)
    fa, fb = StateFile(paths.daily_stats, a, clock), StateFile(paths.daily_stats, b, clock)
    sa = fa.write({"v": "a1"}, expected=None)
    rb = fb.read()  # B starts its cycle here, sees seal sa
    fa.write({"v": "a2"}, expected=sa)  # A writes in between
    with pytest.raises(ConcurrentWriterDetected) as ei:
        fb.write({"v": "b1"}, expected=rb.seal)
    assert ei.value.expected == rb.seal and ei.value.found.write_seq == 2
    assert fb.read().data["v"] == "a2"  # B did not clobber


def test_delete_also_checks_seal(paths, clock):
    a, b = _idents(clock)
    fa, fb = StateFile(paths.entry_halt, a, clock), StateFile(paths.entry_halt, b, clock)
    sa = fa.write({"active": True}, expected=None)
    fb.write({"active": True, "n": 2}, expected=sa)  # B legitimately writes on top of sa
    with pytest.raises(ConcurrentWriterDetected):
        fa.delete(expected=sa)  # A's view is stale
    assert paths.entry_halt.exists()


def test_force_write_bypasses_detection(paths, clock):
    a, b = _idents(clock)
    fa, fb = StateFile(paths.entry_halt, a, clock), StateFile(paths.entry_halt, b, clock)
    fa.write({"active": True}, expected=None)
    s = fb.write({"active": True, "forced": True}, expected=None, force=True)
    assert s.writer_pid == 2000 and fb.read().data["forced"] is True


def test_entry_halt_set_under_race_is_forced_and_ledgered(paths, clock, ledger):
    a, b = _idents(clock)
    ha, hb = EntryHalt(paths, clock, a, ledger=ledger), EntryHalt(paths, clock, b, ledger=ledger)
    ha.set("first", "A")
    # simulate: B read the file, then A writes again, then B sets
    rb = hb.file.read()
    ha.set("second", "A")
    # monkeypatch B's read to return the stale seal for the set() cycle
    real_read = hb.file.read
    calls = {"n": 0}

    def stale_then_real():
        calls["n"] += 1
        return rb if calls["n"] == 1 else real_read()
    hb.file.read = stale_then_real
    rec = hb.set("b-reason", "B", auto_clear=True)
    assert rec.active and rec.auto_clear is False and rec.reason.startswith("CONCURRENT_WRITER_DETECTED")
    d = json.loads(paths.entry_halt.read_text(encoding="utf-8"))
    assert d["writer_pid"] == 2000 and d["active"] is True
    kinds = [json.loads(l)["kind"] for l in open(paths.ledger_file, encoding="utf-8")]
    assert "CONCURRENT_WRITER_DETECTED" in kinds


def test_entry_halt_clear_under_race_keeps_halt_and_escalates(paths, clock, ledger):
    a, b = _idents(clock)
    ha, hb = EntryHalt(paths, clock, a, ledger=ledger), EntryHalt(paths, clock, b, ledger=ledger)
    ha.set("auto", "A", auto_clear=True)
    rb = hb.file.read()
    ha.set("auto2", "A", auto_clear=True)  # A writes in between
    real_read = hb.file.read
    calls = {"n": 0}

    def stale_then_real():
        calls["n"] += 1
        return rb if calls["n"] == 1 else real_read()
    hb.file.read = stale_then_real
    assert hb.clear("book empty", only_auto_clear=True) is False
    cur = EntryHalt(paths, clock, a).active()
    assert cur is not None and cur.auto_clear is False and "CONCURRENT_WRITER_DETECTED" in cur.reason


def test_startup_detects_live_foreign_writer(paths, clock, ledger):
    a, b = _idents(clock)
    EntryHalt(paths, clock, a).set("owned by A", "A")
    hb = EntryHalt(paths, clock, b, ledger=ledger)
    with pytest.raises(ConcurrentWriterDetected):
        hb.startup_check()
    cur = hb.active()
    assert cur is not None and cur.reason.startswith("CONCURRENT_WRITER_DETECTED") and cur.auto_clear is False


def test_startup_takes_over_dead_foreign_writer(paths, clock):
    a = WriterIdentity(clock, pid=1000, pid_alive=lambda p: False)  # nobody alive
    b = WriterIdentity(clock, pid=2000, pid_alive=lambda p: False)
    EntryHalt(paths, clock, a).set("owned by dead A", "A")
    hb = EntryHalt(paths, clock, b)
    hb.startup_check()  # no raise
    hb.set("taken over", "B")
    assert json.loads(paths.entry_halt.read_text())["writer_pid"] == 2000
