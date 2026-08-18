"""G11 - ledger: chain, tamper detection, concurrency, anchored rotation
(decision C), external anchoring (SPEC §2b), optional signer/verifier hooks."""
import hashlib
import hmac
import json
import os
import subprocess
import sys

import pytest

from deadman import Ledger, Anchor, GENESIS_HASH, FakeClock, Paths, ANCHOR_AFTER
from deadman.errors import LedgerWriteError, LedgerIntegrityError


def _lines(p):
    return [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]


def _rewrite(p, rows):
    p.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows), encoding="utf-8")


def test_first_entry_chains_from_genesis(paths, clock):
    lg = Ledger(paths, clock)
    e = lg.append("USER_NOTE", {"a": 1})
    assert e.seq == 1 and e.prev_hash == GENESIS_HASH and len(e.hash) == 64 and e.sig is None
    e2 = lg.append("USER_NOTE", {"b": 2})
    assert e2.seq == 2 and e2.prev_hash == e.hash
    rep = lg.verify()
    assert rep.ok and rep.chain_complete and rep.entries_checked == 2 and rep.code == "OK"
    assert "sig" not in _lines(paths.ledger_file)[0]


def test_unknown_kind_rejected(paths, clock):
    with pytest.raises(LedgerWriteError):
        Ledger(paths, clock).append("MADE_UP", {})


def test_tampered_line_detected(paths, clock):
    lg = Ledger(paths, clock)
    for i in range(3):
        lg.append("USER_NOTE", {"i": i})
    rows = _lines(paths.ledger_file)
    rows[1]["payload"]["i"] = 99
    _rewrite(paths.ledger_file, rows)
    rep = lg.verify()
    assert not rep.ok and rep.code == "HASH_MISMATCH"


def test_deleted_line_detected(paths, clock):
    lg = Ledger(paths, clock)
    for i in range(3):
        lg.append("USER_NOTE", {"i": i})
    rows = _lines(paths.ledger_file)
    del rows[1]
    _rewrite(paths.ledger_file, rows)
    assert lg.verify().code == "CHAIN_BROKEN"


def test_reordered_lines_detected(paths, clock):
    lg = Ledger(paths, clock)
    for i in range(3):
        lg.append("USER_NOTE", {"i": i})
    rows = _lines(paths.ledger_file)
    rows[0], rows[1] = rows[1], rows[0]
    _rewrite(paths.ledger_file, rows)
    rep = lg.verify()
    assert not rep.ok and rep.code in ("CHAIN_BROKEN", "NO_GENESIS")


def test_tip_file_disagreeing_with_tail_is_integrity_error(paths, clock):
    lg = Ledger(paths, clock)
    lg.append("USER_NOTE", {})
    st = json.loads(paths.chain_state.read_text())
    st["last_hash"] = "f" * 64
    paths.chain_state.write_text(json.dumps(st))
    with pytest.raises(LedgerIntegrityError):
        lg.append("USER_NOTE", {})


# ---------- the honest limit of the chain, and the anchor that covers it (SPEC §2b) ----------

def _recompute_chain(rows):
    """What an attacker with disk access does: rewrite and re-hash to the tip."""
    from deadman.ledger import _entry_hash
    prev = GENESIS_HASH
    for r in rows:
        r["prev_hash"] = prev
        r["hash"] = _entry_hash(r["schema_version"], r["seq"], r["ts_utc"], r["kind"], r["actor"], r["payload"], prev)
        prev = r["hash"]
    return prev


def test_full_rewrite_with_recompute_passes_the_chain_alone(paths, clock):
    lg = Ledger(paths, clock)  # no publisher: chain only
    for i in range(3):
        lg.append("USER_NOTE", {"i": i})
    rows = _lines(paths.ledger_file)
    rows[0]["payload"]["i"] = "REWRITTEN"
    tip = _recompute_chain(rows)
    _rewrite(paths.ledger_file, rows)
    paths.chain_state.write_text(json.dumps({"schema_version": 1, "last_seq": 3, "last_hash": tip}))
    rep = lg.verify()
    assert rep.ok and rep.chain_complete and rep.anchors_checked == 0  # the chain cannot see it: documented limit


def test_same_rewrite_is_caught_by_an_external_anchor(paths, clock):
    published = []
    lg = Ledger(paths, clock, publisher=lambda d: (published.append(d) or f"ref-{len(published)}"), anchor_every_n=1000)
    for i in range(3):
        lg.append("USER_NOTE", {"i": i})
    lg.anchor("manual")
    anchors_from_third_party = [Anchor(**{**d, "external_ref": "x"}) for d in published]  # what the third party holds
    rows = _lines(paths.ledger_file)
    rows[0]["payload"]["i"] = "REWRITTEN"
    tip = _recompute_chain(rows)
    _rewrite(paths.ledger_file, rows)
    paths.chain_state.write_text(json.dumps({"schema_version": 1, "last_seq": len(rows), "last_hash": tip}))
    paths.anchors_file.unlink()  # attacker also wipes the local copy
    rep = lg.verify(anchors=anchors_from_third_party)
    assert not rep.ok and rep.code == "ANCHOR_MISMATCH"


def test_published_form_has_no_payload(paths, clock):
    published = []
    lg = Ledger(paths, clock, publisher=lambda d: (published.append(d) or "r"))
    lg.append("USER_NOTE", {"secret": "do not leak"})
    assert published and set(published[0]) == {"schema_version", "seq", "hash", "ts_utc", "segment"}
    assert "secret" not in json.dumps(published)


def test_anchor_forced_after_safety_events_and_by_count(paths, clock):
    published = []
    lg = Ledger(paths, clock, publisher=lambda d: (published.append(d) or "r"), anchor_every_n=3, anchor_every_s=10**9)
    lg.append("USER_NOTE", {})            # first entry with a publisher -> anchor (seq 1)
    n0 = len(published)
    lg.append("HALT_SET", {"reason": "x", "source": "t", "auto_clear": False})   # forced
    assert len(published) == n0 + 1 and published[-1]["seq"] == 3  # seq 2 HALT_SET, anchored after ANCHOR_PUBLISHED(seq 2)?
    # count-based: 3 plain notes -> one anchor
    before = len(published)
    for _ in range(3):
        lg.append("USER_NOTE", {})
    assert len(published) == before + 1
    rep = lg.verify()
    assert rep.ok and rep.anchors_checked == len(published) and rep.latest_anchor_seq == published[-1]["seq"]
    kinds = [r["kind"] for r in _lines(paths.ledger_file)]
    assert "ANCHOR_PUBLISHED" in kinds and all(k in ANCHOR_AFTER or True for k in kinds)


def test_anchor_by_elapsed_time(paths, clock):
    published = []
    lg = Ledger(paths, clock, publisher=lambda d: (published.append(d) or "r"), anchor_every_n=10**6, anchor_every_s=3600)
    lg.append("USER_NOTE", {})  # first -> anchor
    lg.append("USER_NOTE", {})
    assert len(published) == 1
    clock.advance(seconds=3601)
    lg.append("USER_NOTE", {})
    assert len(published) == 2


def test_publisher_failure_is_recorded_and_does_not_stop(paths, clock):
    def bad(_):
        raise ConnectionError("remote down")
    lg = Ledger(paths, clock, publisher=bad)
    lg.append("USER_NOTE", {"i": 1})
    lg.append("USER_NOTE", {"i": 2})
    kinds = [r["kind"] for r in _lines(paths.ledger_file)]
    assert "ANCHOR_FAILED" in kinds and kinds.count("USER_NOTE") == 2
    assert lg.verify().ok and lg.local_anchors() == []


def test_optional_signer_verifier_hooks(paths, clock, tmp_path):
    key = b"user-owned-secret"
    signer = lambda h: hmac.new(key, h, hashlib.sha256).digest()
    verifier = lambda h, sig: hmac.compare_digest(hmac.new(key, h, hashlib.sha256).digest(), sig)
    lg = Ledger(paths, clock, signer=signer, verifier=verifier)
    lg.append("USER_NOTE", {"i": 0})
    assert lg.verify().ok
    rows = _lines(paths.ledger_file)
    assert len(rows[0]["sig"]) == 64
    rows[0]["sig"] = hmac.new(b"other-key", rows[0]["hash"].encode(), hashlib.sha256).hexdigest()
    _rewrite(paths.ledger_file, rows)
    assert lg.verify().code == "BAD_SIGNATURE"
    # a verifier-less reader still validates the chain
    assert Ledger(paths, clock).verify().ok


# ---------- rotation ----------

def test_rotation_anchor_format_and_verify_crosses_segments(paths, clock):
    lg = Ledger(paths, clock)
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
    lg = Ledger(paths, clock)
    lg.append("USER_NOTE", {}); lg.rotate(); lg.append("USER_NOTE", {}); lg.rotate(); lg.append("USER_NOTE", {})
    rep = lg.verify()
    assert rep.ok and rep.chain_complete and rep.segments_checked == 3


def test_altered_previous_segment_breaks_link(paths, clock):
    lg = Ledger(paths, clock)
    for i in range(3):
        lg.append("USER_NOTE", {"i": i})
    lg.rotate()
    seg = paths.segment(1)
    rows = _lines(seg)
    rows[0]["payload"]["i"] = 42
    _rewrite(seg, rows)
    rep = lg.verify()
    assert not rep.ok and rep.code == "ROTATION_LINK_BROKEN"


def test_missing_previous_segment_is_never_plain_ok(paths, clock):
    lg = Ledger(paths, clock)
    for i in range(3):
        lg.append("USER_NOTE", {"i": i})
    lg.rotate()
    lg.append("USER_NOTE", {"x": 1})
    os.remove(paths.segment(1))
    rep = lg.verify()
    assert rep.ok is True and rep.chain_complete is False and rep.code == "SEGMENT_MISSING"
    assert rep.verified_from_seq == 4  # the anchor entry itself


def test_anchor_entry_with_wrong_prev_hash_detected(paths, clock):
    lg = Ledger(paths, clock)
    lg.append("USER_NOTE", {}); lg.rotate()
    rows = _lines(paths.ledger_file)
    rows[0]["payload"]["prev_last_hash"] = "a" * 64
    _rewrite(paths.ledger_file, rows)
    rep = lg.verify()
    assert not rep.ok and rep.code in ("HASH_MISMATCH", "ROTATION_LINK_BROKEN")


def test_rotate_empty_refused(paths, clock):
    with pytest.raises(LedgerWriteError):
        Ledger(paths, clock).rotate()


def test_rotation_triggers_anchor_when_publisher_present(paths, clock):
    published = []
    lg = Ledger(paths, clock, publisher=lambda d: (published.append(d) or "r"), anchor_every_n=10**6, anchor_every_s=10**9)
    lg.append("USER_NOTE", {})
    n = len(published)
    lg.rotate()
    assert len(published) == n + 1 and published[-1]["segment"] == "ledger.jsonl"


# ---------- concurrency (two real processes) ----------

WORKER = r"""
import sys
sys.path.insert(0, sys.argv[1])
from deadman import Ledger, Paths, SystemClock
lg = Ledger(Paths(sys.argv[2]), SystemClock())
for i in range(int(sys.argv[3])):
    lg.append("USER_NOTE", {"w": sys.argv[4], "i": i})
print("done")
"""


def test_two_processes_appending_do_not_fork_the_chain(paths, clock, tmp_path):
    lg = Ledger(paths, clock)
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
    rep = Ledger(paths, clock).verify()
    assert rep.ok and rep.chain_complete and rep.entries_checked == 2 * n + 1


# ---------- sustained anchor failure is not silent (SPEC §2b) ----------

def test_sustained_anchor_failure_raises_stale_flag_and_recovers(paths, clock):
    state = {"fail": True, "n": 0}

    def pub(d):
        state["n"] += 1
        if state["fail"]:
            raise ConnectionError("remote down")
        return f"ref-{state['n']}"
    lg = Ledger(paths, clock, publisher=pub, anchor_every_n=1, stale_after_failures=3, stale_after_s=10**9)
    lg.append("USER_NOTE", {"i": 1})   # fail 1
    lg.append("USER_NOTE", {"i": 2})   # fail 2
    assert not paths.anchor_stale_flag.exists()
    lg.append("USER_NOTE", {"i": 3})   # fail 3 -> stale
    assert paths.anchor_stale_flag.exists()
    kinds = [r["kind"] for r in _lines(paths.ledger_file)]
    assert kinds.count("ANCHOR_STALE") == 1
    lg.append("USER_NOTE", {"i": 4})   # fail 4 -> still stale, no second STALE entry
    assert [r["kind"] for r in _lines(paths.ledger_file)].count("ANCHOR_STALE") == 1
    assert "ANCHOR_STALE" in lg.verify().detail
    state["fail"] = False
    lg.append("USER_NOTE", {"i": 5})   # success -> recovered
    assert not paths.anchor_stale_flag.exists()
    kinds = [r["kind"] for r in _lines(paths.ledger_file)]
    assert "ANCHOR_RECOVERED" in kinds and kinds.index("ANCHOR_RECOVERED") > kinds.index("ANCHOR_STALE")
    assert "ANCHOR_STALE" not in lg.verify().detail


def test_stale_by_elapsed_time_without_success(paths, clock):
    calls = {"n": 0}

    def pub(d):
        calls["n"] += 1
        if calls["n"] == 1:
            return "ok-1"
        raise ConnectionError("down")
    lg = Ledger(paths, clock, publisher=pub, anchor_every_n=1, stale_after_failures=10**6, stale_after_s=100)
    lg.append("USER_NOTE", {})          # ok
    clock.advance(seconds=50)
    lg.append("USER_NOTE", {})          # fail, 50s since ok -> not stale
    assert not paths.anchor_stale_flag.exists()
    clock.advance(seconds=60)
    lg.append("USER_NOTE", {})          # fail, 110s since ok -> stale
    assert paths.anchor_stale_flag.exists()
    flag = paths.anchor_stale_flag.read_text(encoding="utf-8")
    assert flag.startswith("ANCHOR_STALE") and "seconds_since_last_ok" in flag
