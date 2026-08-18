"""G11 - signed ledger: chain, signature, tamper detection, concurrency,
anchored rotation (decision C)."""
import json
import os
import subprocess
import sys

import pytest

from deadman import SignedLedger, GENESIS_HASH, FakeClock, Paths
from deadman.errors import LedgerWriteError, LedgerIntegrityError


def _lines(p):
    return [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]


def test_first_entry_chains_from_genesis_and_is_signed(paths, clock):
    lg = SignedLedger(paths, clock)
    e = lg.append("USER_NOTE", {"a": 1})
    assert e.seq == 1 and e.prev_hash == GENESIS_HASH and len(e.hash) == 64 and len(e.sig) == 128
    e2 = lg.append("USER_NOTE", {"b": 2})
    assert e2.seq == 2 and e2.prev_hash == e.hash
    rep = lg.verify()
    assert rep.ok and rep.chain_complete and rep.entries_checked == 2 and rep.code == "OK"


def test_unknown_kind_rejected(paths, clock):
    with pytest.raises(LedgerWriteError):
        SignedLedger(paths, clock).append("MADE_UP", {})


def test_tampered_line_detected(paths, clock):
    lg = SignedLedger(paths, clock)
    for i in range(3):
        lg.append("USER_NOTE", {"i": i})
    rows = _lines(paths.ledger_file)
    rows[1]["payload"]["i"] = 99
    paths.ledger_file.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows), encoding="utf-8")
    rep = lg.verify()
    assert not rep.ok and rep.code == "HASH_MISMATCH"


def test_deleted_line_detected(paths, clock):
    lg = SignedLedger(paths, clock)
    for i in range(3):
        lg.append("USER_NOTE", {"i": i})
    rows = _lines(paths.ledger_file)
    del rows[1]
    paths.ledger_file.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows), encoding="utf-8")
    rep = lg.verify()
    assert not rep.ok and rep.code == "CHAIN_BROKEN"


def test_reordered_lines_detected(paths, clock):
    lg = SignedLedger(paths, clock)
    for i in range(3):
        lg.append("USER_NOTE", {"i": i})
    rows = _lines(paths.ledger_file)
    rows[0], rows[1] = rows[1], rows[0]
    paths.ledger_file.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows), encoding="utf-8")
    rep = lg.verify()
    assert not rep.ok and rep.code in ("CHAIN_BROKEN", "NO_GENESIS")


def test_forged_signature_detected(paths, clock, tmp_path):
    lg = SignedLedger(paths, clock)
    lg.append("USER_NOTE", {"i": 0})
    other = SignedLedger(Paths(tmp_path / "other"), clock)  # different key
    rows = _lines(paths.ledger_file)
    # re-sign the same hash with the other key
    rows[0]["sig"] = other._key.sign(rows[0]["hash"].encode()).signature.hex()
    paths.ledger_file.write_text(json.dumps(rows[0], sort_keys=True) + "\n", encoding="utf-8")
    rep = lg.verify()
    assert not rep.ok and rep.code == "BAD_SIGNATURE"


def test_tip_file_disagreeing_with_tail_is_integrity_error(paths, clock):
    lg = SignedLedger(paths, clock)
    lg.append("USER_NOTE", {})
    st = json.loads(paths.chain_state.read_text())
    st["last_hash"] = "f" * 64
    paths.chain_state.write_text(json.dumps(st))
    with pytest.raises(LedgerIntegrityError):
        lg.append("USER_NOTE", {})


def test_key_persists_across_instances(paths, clock):
    a = SignedLedger(paths, clock)
    a.append("USER_NOTE", {})
    b = SignedLedger(paths, clock)
    assert a.public_key() == b.public_key()
    assert b.verify().ok


# ---------- rotation ----------

def test_rotation_anchor_format_and_verify_crosses_segments(paths, clock):
    lg = SignedLedger(paths, clock)
    for i in range(5):
        lg.append("USER_NOTE", {"i": i})
    tail_before = _lines(paths.ledger_file)[-1]
    anchor = lg.rotate()
    assert anchor.kind == "LEDGER_ROTATED" and anchor.seq == 6
    assert anchor.prev_hash == tail_before["hash"]
    assert anchor.payload["prev_last_hash"] == tail_before["hash"] == anchor.prev_hash
    assert anchor.payload["prev_last_seq"] == 5 and anchor.payload["prev_first_seq"] == 1
    assert anchor.payload["prev_segment"] == "ledger.0001.jsonl"
    assert len(anchor.payload["prev_sha256"]) == 64
    assert paths.segment(1).exists()
    lg.append("USER_NOTE", {"after": True})
    rep = lg.verify()
    assert rep.ok and rep.chain_complete and rep.segments_checked == 2 and rep.entries_checked == 7


def test_rotation_twice_chains_three_segments(paths, clock):
    lg = SignedLedger(paths, clock)
    lg.append("USER_NOTE", {}); lg.rotate(); lg.append("USER_NOTE", {}); lg.rotate(); lg.append("USER_NOTE", {})
    rep = lg.verify()
    assert rep.ok and rep.chain_complete and rep.segments_checked == 3


def test_altered_previous_segment_breaks_link(paths, clock):
    lg = SignedLedger(paths, clock)
    for i in range(3):
        lg.append("USER_NOTE", {"i": i})
    lg.rotate()
    seg = paths.segment(1)
    rows = _lines(seg)
    rows[0]["payload"]["i"] = 42
    seg.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows), encoding="utf-8")
    rep = lg.verify()
    assert not rep.ok and rep.code == "ROTATION_LINK_BROKEN"


def test_missing_previous_segment_is_never_plain_ok(paths, clock):
    lg = SignedLedger(paths, clock)
    for i in range(3):
        lg.append("USER_NOTE", {"i": i})
    lg.rotate()
    lg.append("USER_NOTE", {"x": 1})
    os.remove(paths.segment(1))
    rep = lg.verify()
    assert rep.ok is True and rep.chain_complete is False and rep.code == "SEGMENT_MISSING"
    assert rep.verified_from_seq == 4  # the anchor entry itself


def test_anchor_with_wrong_prev_hash_detected(paths, clock):
    lg = SignedLedger(paths, clock)
    lg.append("USER_NOTE", {}); lg.rotate()
    rows = _lines(paths.ledger_file)
    rows[0]["payload"]["prev_last_hash"] = "a" * 64  # payload changed -> hash mismatch first
    paths.ledger_file.write_text(json.dumps(rows[0], sort_keys=True) + "\n", encoding="utf-8")
    rep = lg.verify()
    assert not rep.ok and rep.code in ("HASH_MISMATCH", "ROTATION_LINK_BROKEN")


def test_rotate_empty_refused(paths, clock):
    with pytest.raises(LedgerWriteError):
        SignedLedger(paths, clock).rotate()


# ---------- concurrency (two real processes) ----------

WORKER = r"""
import sys, os
sys.path.insert(0, sys.argv[1])
from deadman import SignedLedger, Paths, SystemClock
lg = SignedLedger(Paths(sys.argv[2]), SystemClock())
for i in range(int(sys.argv[3])):
    lg.append("USER_NOTE", {"w": sys.argv[4], "i": i})
print("done")
"""


def test_two_processes_appending_do_not_fork_the_chain(paths, clock, tmp_path):
    lg = SignedLedger(paths, clock)  # creates the key first so both workers share it
    lg.append("USER_NOTE", {"init": True})
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    script = tmp_path / "w.py"
    script.write_text(WORKER, encoding="utf-8")
    n = 60
    procs = [subprocess.Popen([sys.executable, str(script), root, str(paths.root), str(n), w],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE) for w in ("A", "B")]
    for p in procs:
        out, err = p.communicate(timeout=120)
        assert p.returncode == 0, err.decode(errors="replace")
    rows = _lines(paths.ledger_file)
    assert len(rows) == 1 + 2 * n
    assert [r["seq"] for r in rows] == list(range(1, 2 * n + 2))
    rep = SignedLedger(paths, clock).verify()
    assert rep.ok and rep.chain_complete and rep.entries_checked == 2 * n + 1
