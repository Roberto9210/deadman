"""C1-C18 - the adversarial suite for the session-certificate verifier (CERT_SPEC v0.2 A.5).

Written BEFORE the emitter exists, and that ordering is the point: every certificate in this
file is fabricated by hand, most of them dishonest, and the verifier has to refuse them. If
the emitter had come first these tests would have been shaped to agree with it.

The guarantee this file exists to defend is the uncomfortable one:
**a verifier that cannot contradict is a rubber stamp.**

Fixtures are synthetic but built with the REAL hashing rules of both dialects, so a passing
test says something about the code and not about a recorded blob. Roberto's live soak ledger
is deliberately NOT vendored here: this repository is public, and his session data is his to
publish or not. `test_c1_real_soak_ledger` runs against it when it happens to be on the
machine and skips everywhere else.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from deadman.verify_certificate import (
    DEADMAN_KIT_V1, EXIT_CONTRADICTED, EXIT_OK, EXIT_UNEVALUABLE, GUARDIAN_CORE_V1,
    REQUIRED_LIMITATIONS, _cert_preimage, canonical_json, recompute_claims,
    verify_certificate, verify_series,
)

TS = "2026-08-21T12:%02d:00.000Z"


# ---------------------------------------------------------------- ledger fixtures

def gledger(events):
    """A guardian-core-v1 ledger, chained with the real rules."""
    out, prev = [], GUARDIAN_CORE_V1.genesis
    for i, (name, payload) in enumerate(events, start=1):
        e = {"seq": i, "tsUtc": TS % min(i, 59), "event": name,
             "schemaVersion": 1, "payload": payload, "prev": prev}
        e["hash"] = GUARDIAN_CORE_V1.hash_of(e)
        prev = e["hash"]
        out.append(e)
    return out


def kledger(events):
    """A deadman-kit-v1 ledger, chained with the real rules."""
    out, prev = [], DEADMAN_KIT_V1.genesis
    for i, (name, payload) in enumerate(events, start=1):
        e = {"schema_version": 1, "seq": i, "ts_utc": TS % min(i, 59), "kind": name,
             "actor": "user", "payload": payload, "prev_hash": prev}
        e["hash"] = DEADMAN_KIT_V1.hash_of(e)
        prev = e["hash"]
        out.append(e)
    return out


QUIET_DAY = [
    ("GUARDIAN_STARTED", {"fresh": True, "state": "DISARMED"}),
    ("CONFIG_LOADED", {"configHash": "c0ffee"}),
    ("ARMED", {"accounts": ["A1"], "personalLimit": "600.00", "firmLimit": "1000.00"}),
    ("SEAL_CREATED", {"expiresAtUtc": "2026-08-21T22:00:00.000Z"}),
    ("DAY_OPENED", {"dayKey": "2026-08-21"}),
    ("PNL_CHECKPOINT", {"dayLoss": "0.00"}),
    ("DAY_CLOSED", {"dayKey": "2026-08-21"}),
]

BREACH_DAY = QUIET_DAY[:6] + [
    ("LIMIT_BREACHED", {"dayLoss": "600.00", "limit": "600.00"}),
    ("ORDERS_CANCELLED", {"account": "A1", "count": 1}),
    ("FLATTEN_REQUESTED", {"account": "A1"}),
    ("FLATTEN_VERIFIED", {"accounts": ["A1"]}),
    ("ORDER_REJECTED_LOCKED", {"orderId": "o-1", "action": "Buy"}),
    ("ORDER_REJECTED_LOCKED", {"orderId": "o-1", "action": "Buy"}),   # retry, same id
    ("ORDER_REJECTED_LOCKED", {"orderId": "o-2", "action": "Buy"}),
    ("DAY_CLOSED", {"dayKey": "2026-08-21"}),
]

DISCONNECT_DAY = QUIET_DAY[:5] + [
    ("ACCOUNT_UNKNOWN", {"account": "A1", "detail": "Disconnected"}),
    ("FAIL_CLOSED_ENTERED", {"reason": "AccountUnknown on A1"}),
    ("ACCOUNT_UNKNOWN", {"account": "A1", "detail": "Disconnected"}),
    ("ACCOUNT_UNKNOWN", {"account": "A1", "detail": "Disconnected"}),
    ("FAIL_CLOSED_CLEARED", {"previousReason": "AccountUnknown on A1"}),
    ("PNL_CHECKPOINT", {"dayLoss": "0.00", "trigger": "transition"}),
    ("DAY_CLOSED", {"dayKey": "2026-08-21"}),
]


# ---------------------------------------------------------------- certificate fixture

def make_cert(entries, dialect=GUARDIAN_CORE_V1, day="2026-08-21", *, honest=True,
              trust="L1", anchors=None, prev_cert=None, gaps=None, overrides=None,
              drop=(), lo=None):
    lo = 1 if lo is None else lo
    hi = max(e["seq"] for e in entries)
    c = recompute_claims(entries, dialect, lo, hi, True)
    cert = {
        "certVersion": 1,
        "ledgerDialect": dialect.name,
        # Same rules the shipped examples obey (test_c_certificate_example_hygiene.py):
        # no filler, buildHash 16 lowercase hex, version in the emitter's shape.
        "issuer": {"tool": "deadman-guardian", "version": "0.1.0-beta+" + "0" * 40,
                   "buildHash": hashlib.sha256(b"fixture build").hexdigest()[:16]},
        "subject": {"alias": "tester", "accounts": ["acct-hash"]},
        "session": {"dayKey": day, "openedUtc": TS % 0, "closedUtc": TS % 59,
                    "timezone": "America/Chicago"},
        "previousCertHash": prev_cert,
        "continuity": {"daysCovered": 1, "gaps": gaps or []},
        # A real-shaped seal hash. It used to read "seal", which rule 5 correctly flags as a
        # decorative field: a word in something named `...Hash` distinguishes nothing. The
        # verifier caught this fixture the moment the rule was enforced on the receiving side.
        "commitment": {"armedAtUtc": TS % 0,
                       "sealHash": hashlib.sha256(b"fixture seal").hexdigest(),
                       "sealExpiryUtc": TS % 59,
                       "personalDailyLossLimit": "600.00", "firmDailyLossLimit": "1000.00",
                       "changeAttemptsWhileSealed": c["changeAttemptsWhileSealed"]},
        "claims": {
            "limitRespected": c["limitRespected"],
            "lockoutsTriggered": c["lockoutsTriggered"],
            "ordersRejectedWhileLocked": c["ordersRejectedWhileLocked"],
            "failClosedEpisodes": c["failClosedEpisodes"],
            "clockAnomalies": c["clockAnomalies"],
            "ledgerRange": {"fromSeq": lo, "toSeq": hi},
            "ledgerVerified": True,
        },
        "anchors": anchors or [],
        "trustLevel": trust,
        "limitations": list(REQUIRED_LIMITATIONS),
        "verifyInstructions": {"tool": "deadman-kit",
                               "command": "python -m deadman.verify_certificate c.json l.jsonl"},
    }
    for path in drop:
        a, b = path.split(".")
        cert[a].pop(b, None)
    for path, value in (overrides or {}).items():
        if "." in path:
            a, b = path.split(".")
            cert[a][b] = value
        else:
            cert[path] = value
    cert["certHash"] = hashlib.sha256(_cert_preimage(cert)).hexdigest()
    return cert


def codes(rep):
    return {f.code for f in rep.contradictions}


# ================================================================== C1

def test_c1_honest_certificate_verifies_and_reports_the_layer():
    entries = gledger(QUIET_DAY)
    rep = verify_certificate(make_cert(entries), entries)
    assert rep.contradictions == [], [str(f) for f in rep.contradictions]
    assert rep.exit_code == EXIT_OK
    assert rep.reached_level == "L1" and rep.declared_level == "L1"
    assert rep.chain_ok and rep.cert_hash_ok


def test_c1_both_dialects_verify():
    for entries, dialect in ((gledger(QUIET_DAY), GUARDIAN_CORE_V1),
                             (kledger(QUIET_DAY), DEADMAN_KIT_V1)):
        rep = verify_certificate(make_cert(entries, dialect), entries)
        assert rep.ok, (dialect.name, [str(f) for f in rep.contradictions])


def test_c1_real_soak_ledger():
    """Runs against the live guardian ledger when this machine has one. Not vendored: this
    repo is public and that file is Roberto's session data."""
    real = Path.home() / "Documents" / "NinjaTrader 8" / "deadman-guardian" / "ledger.jsonl"
    if not real.exists():
        pytest.skip("no live guardian ledger on this machine")
    entries = [json.loads(l) for l in real.read_text(encoding="utf-8").splitlines() if l.strip()]
    rep = verify_certificate(make_cert(entries), entries)
    assert rep.ok, [str(f) for f in rep.contradictions]
    assert rep.chain_ok and rep.entries_read == len(entries)


# ================================================================== C2

def test_c2_falsified_limit_respected_is_caught_by_recompute():
    entries = gledger(BREACH_DAY)                      # a day that DID breach
    cert = make_cert(entries, overrides={"claims.limitRespected": True,
                                         "claims.lockoutsTriggered": 0})
    rep = verify_certificate(cert, entries)
    assert rep.exit_code == EXIT_CONTRADICTED
    assert "CLAIM_MISMATCH" in codes(rep)
    said = " ".join(f.detail for f in rep.contradictions)
    assert "limitRespected" in said and "lockoutsTriggered" in said


def test_c2_the_honest_version_of_the_same_day_passes():
    """Control: the machinery is not simply refusing everything."""
    entries = gledger(BREACH_DAY)
    rep = verify_certificate(make_cert(entries), entries)
    assert rep.ok, [str(f) for f in rep.contradictions]
    assert rep.recomputed["lockoutsTriggered"] == 1
    assert rep.recomputed["limitRespected"] is False


def test_c2_orders_rejected_distinct_by_order_id():
    """Three ORDER_REJECTED_LOCKED, two distinct ids: the retry must not inflate it (A.2)."""
    entries = gledger(BREACH_DAY)
    rep = verify_certificate(make_cert(entries), entries)
    assert rep.recomputed["ordersRejectedWhileLocked"] == 2
    liar = make_cert(entries, overrides={"claims.ordersRejectedWhileLocked": 3})
    assert verify_certificate(liar, entries).exit_code == EXIT_CONTRADICTED


# ================================================================== C3

def test_c3_edited_ledger_breaks_verification_and_names_the_seq():
    entries = gledger(QUIET_DAY)
    cert = make_cert(entries)
    entries[3]["payload"] = {"expiresAtUtc": "2099-01-01T00:00:00.000Z"}   # move the seal out
    rep = verify_certificate(cert, entries)
    assert rep.exit_code == EXIT_CONTRADICTED
    assert "CHAIN_BROKEN" in codes(rep)
    assert rep.broken_seq == 4


def test_c3_a_removed_line_is_caught_as_an_incomplete_range():
    entries = gledger(QUIET_DAY)
    cert = make_cert(entries)
    del entries[2]
    rep = verify_certificate(cert, entries)
    assert rep.exit_code == EXIT_CONTRADICTED
    assert {"RANGE_INCOMPLETE", "CHAIN_BROKEN"} & codes(rep)


def test_c1_a_ledger_that_kept_growing_after_emission_still_verifies():
    """The real case: the guardian is still running while the trader exports. A certificate
    covers a RANGE, so entries appended afterwards are outside it and must not invalidate it -
    while a range with a hole in it still must."""
    entries = gledger(QUIET_DAY)
    cert = make_cert(entries)                       # declares 1..7
    kept_running = entries + gledger(QUIET_DAY + QUIET_DAY)[7:]
    rep = verify_certificate(cert, kept_running)
    assert rep.range_to == 7 and rep.entries_read > 7
    assert rep.ok, [str(f) for f in rep.contradictions]


# ================================================================== C4

def test_c4_without_an_anchor_it_declares_l1_and_says_why():
    entries = gledger(QUIET_DAY)
    rep = verify_certificate(make_cert(entries), entries)
    assert rep.reached_level == "L1" and rep.anchors_checked == 0
    assert "NO_EXTERNAL_ANCHOR" in {f.code for f in rep.unverified}
    assert "NO_EXTERNAL_ANCHOR" in rep.render()
    assert "existed before now" in rep.render()


def test_c4_declaring_l2_without_anchors_is_a_contradiction():
    entries = gledger(QUIET_DAY)
    rep = verify_certificate(make_cert(entries, trust="L2"), entries)
    assert rep.exit_code == EXIT_CONTRADICTED
    assert "TRUST_LEVEL_OVERSTATED" in codes(rep)


def test_c4_the_report_states_the_reached_level_not_the_declared_one():
    """Found by mutation control: replacing the computed level with the declared one left
    the whole suite green, because every other test happens to have them equal. A report
    that echoes the certificate's own claim is a report that repeats the lie, even while
    listing the contradiction underneath it."""
    entries = gledger(QUIET_DAY)
    for declared in ("L2", "L3"):
        rep = verify_certificate(make_cert(entries, trust=declared), entries)
        assert rep.declared_level == declared
        assert rep.reached_level == "L1", f"{declared}: report echoed the declared level"
        out = rep.render()
        assert f"DECLARED      {declared}" in out
        assert "REACHED       L1" in out


# ================================================================== C5

def _full_rewrite(entries, dialect, seq, new_payload):
    """What an attacker with disk access does: edit, then re-hash the whole chain to the tip."""
    rows = [dict(e) for e in entries]
    for r in rows:
        if r[dialect.f_seq] == seq:
            r[dialect.f_payload] = new_payload
    prev = dialect.genesis
    for r in rows:
        r[dialect.f_prev] = prev
        r["hash"] = dialect.hash_of(r)
        prev = r["hash"]
    return rows


def _erase_and_rechain(entries, dialect, event_name):
    """The real attack: delete the inconvenient events, renumber, and re-hash the whole
    chain so the tip is consistent. Nothing inside the file is left to notice."""
    rows = [dict(e) for e in entries if e[dialect.f_event] != event_name]
    prev = dialect.genesis
    for i, r in enumerate(rows, start=1):
        r[dialect.f_seq] = i
        r[dialect.f_prev] = prev
        r["hash"] = dialect.hash_of(r)
        prev = r["hash"]
    return rows


def test_c5_full_rewrite_with_recompute_passes_the_chain_alone():
    """The documented limit of L1, stated rather than hidden - it mirrors
    tests/test_g11_ledger.py::test_full_rewrite_with_recompute_passes_the_chain_alone.

    A day that breached is rewritten into a day that did not. The chain recomputes, the
    claims recompute, everything agrees - and the certificate is a lie. This test PASSING is
    the honest statement that L1 alone cannot see it; C5's anchor test is what catches it."""
    breached = gledger(BREACH_DAY)
    honest = verify_certificate(make_cert(breached), breached)
    assert honest.recomputed["lockoutsTriggered"] == 1
    assert honest.recomputed["limitRespected"] is False

    laundered = _erase_and_rechain(breached, GUARDIAN_CORE_V1, "LIMIT_BREACHED")
    rep = verify_certificate(make_cert(laundered), laundered)
    assert rep.ok, [str(f) for f in rep.contradictions]
    assert rep.reached_level == "L1" and rep.anchors_checked == 0
    assert rep.recomputed["lockoutsTriggered"] == 0        # the breach is simply gone
    assert rep.recomputed["limitRespected"] is True        # and the lie verifies
    assert "NO_EXTERNAL_ANCHOR" in {f.code for f in rep.unverified}


def test_c5_the_laundered_day_falls_against_an_anchor_taken_before_the_rewrite():
    """Same attack, now with a third party holding one (seq, hash) from before it."""
    breached = gledger(BREACH_DAY)
    anchor = [{"seq": 7, "hash": breached[6]["hash"], "type": "tsa", "ref": "third-party",
               "tsUtc": TS % 30}]
    laundered = _erase_and_rechain(breached, GUARDIAN_CORE_V1, "LIMIT_BREACHED")
    cert = make_cert(laundered, trust="L2", anchors=anchor)
    rep = verify_certificate(cert, laundered, anchors=anchor)
    assert rep.exit_code == EXIT_CONTRADICTED
    assert "ANCHOR_MISMATCH" in codes(rep)


def test_c5_the_same_rewrite_falls_against_a_third_party_anchor():
    """Mirrors tests/test_g11_ledger.py::test_same_rewrite_is_caught_by_an_external_anchor."""
    entries = gledger(BREACH_DAY)
    anchor = [{"seq": 7, "hash": entries[6]["hash"], "type": "tsa",
               "ref": "held-by-third-party", "tsUtc": TS % 30}]

    honest = verify_certificate(make_cert(entries, trust="L2", anchors=anchor), entries,
                                anchors=anchor)
    assert honest.ok and honest.reached_level == "L2"
    assert honest.covered_up_to_seq == 7

    rewritten = _full_rewrite(entries, GUARDIAN_CORE_V1, 7, {"dayLoss": "0.00", "limit": "600.00"})
    cert = make_cert(rewritten, trust="L2", anchors=anchor)
    rep = verify_certificate(cert, rewritten, anchors=anchor)
    assert rep.exit_code == EXIT_CONTRADICTED
    assert "ANCHOR_MISMATCH" in codes(rep)


def test_c5_anchor_coverage_stops_where_the_anchor_stops():
    entries = gledger(BREACH_DAY)
    anchor = [{"seq": 5, "hash": entries[4]["hash"], "type": "tsa", "ref": "x", "tsUtc": TS % 5}]
    rep = verify_certificate(make_cert(entries, trust="L2", anchors=anchor), entries,
                             anchors=anchor)
    assert rep.covered_up_to_seq == 5
    assert "ANCHOR_COVERAGE_PARTIAL" in {f.code for f in rep.unverified}
    assert "outside L2 coverage" in rep.render()


# ================================================================== C6

def test_c6_fail_closed_episodes_are_episodes_not_causes():
    """One episode, and it includes the event that triggered it (SPEC A.2.1).

    DISCONNECT_DAY has ACCOUNT_UNKNOWN at seq 6 (the trigger), FAIL_CLOSED_ENTERED at 7,
    two more ACCOUNT_UNKNOWN inside, then CLEARED: three causes, not two. An episode that
    leaves out its own cause tells the story wrong."""
    entries = gledger(DISCONNECT_DAY)
    rep = verify_certificate(make_cert(entries), entries)
    eps = rep.recomputed["failClosedEpisodes"]
    assert len(eps) == 1, eps
    assert eps[0]["reasons"] == {"ACCOUNT_UNKNOWN": 3}
    assert eps[0]["precedingSeq"] == 6 and eps[0]["precedingEvent"] == "ACCOUNT_UNKNOWN"
    assert eps[0]["fromSeq"] == 7, "the block began at ENTERED; counting the trigger must not lengthen it"
    assert eps[0]["open"] is False
    assert rep.ok


def test_c6_an_episode_with_nothing_before_it_has_no_trigger():
    """The rule is positional, so it must say so when there is no position to look at."""
    entries = gledger([("FAIL_CLOSED_ENTERED", {"reason": "PnlUncomputable"}),
                       ("FAIL_CLOSED_CLEARED", {"previousReason": "PnlUncomputable"})])
    rep = verify_certificate(make_cert(entries), entries)
    ep = rep.recomputed["failClosedEpisodes"][0]
    assert ep["precedingSeq"] is None and ep["precedingEvent"] is None
    assert ep["reasons"] == {}


def test_c6_a_boundary_marker_is_never_counted_as_a_trigger():
    """Back-to-back episodes: the previous CLEARED must not become the next one's cause."""
    entries = gledger([
        ("DAY_OPENED", {"dayKey": "2026-08-21"}),
        ("ACCOUNT_UNKNOWN", {"detail": "Disconnected"}),
        ("FAIL_CLOSED_ENTERED", {"reason": "AccountUnknown"}),
        ("FAIL_CLOSED_CLEARED", {"previousReason": "AccountUnknown"}),
        ("FAIL_CLOSED_ENTERED", {"reason": "PnlUncomputable"}),
        ("FAIL_CLOSED_CLEARED", {"previousReason": "PnlUncomputable"}),
    ])
    rep = verify_certificate(make_cert(entries), entries)
    eps = rep.recomputed["failClosedEpisodes"]
    assert len(eps) == 2
    assert eps[0]["precedingEvent"] == "ACCOUNT_UNKNOWN" and eps[0]["reasons"] == {"ACCOUNT_UNKNOWN": 1}
    assert eps[1]["precedingEvent"] is None and eps[1]["reasons"] == {}


def test_c6_hiding_an_episode_is_a_contradiction():
    entries = gledger(DISCONNECT_DAY)
    cert = make_cert(entries, overrides={"claims.failClosedEpisodes": []})
    rep = verify_certificate(cert, entries)
    assert rep.exit_code == EXIT_CONTRADICTED
    assert "CLAIM_MISMATCH" in codes(rep)


def test_c6_an_episode_still_open_at_the_end_of_the_range_falsifies_limit_respected():
    entries = gledger(QUIET_DAY[:5] + [("FAIL_CLOSED_ENTERED", {"reason": "PnlUncomputable"})])
    rep = verify_certificate(make_cert(entries), entries)
    eps = rep.recomputed["failClosedEpisodes"]
    assert len(eps) == 1 and eps[0]["open"] is True
    assert rep.recomputed["limitRespected"] is False


# ================================================================== C7

def test_c7_an_absent_claim_is_declared_never_invented():
    entries = gledger(QUIET_DAY)
    cert = make_cert(entries, drop=("claims.lockoutsTriggered",))
    rep = verify_certificate(cert, entries)
    absent = [f for f in rep.unverified if f.code == "CLAIM_ABSENT"]
    assert absent and "lockoutsTriggered" in absent[0].detail
    assert "CLAIM_MISMATCH" not in codes(rep)   # absence is not a lie


def test_c7_tradesobserved_is_reported_as_not_recomputable():
    entries = gledger(QUIET_DAY)
    rep = verify_certificate(make_cert(entries), entries)
    assert "TRADES_OBSERVED" in {f.code for f in rep.unverified}
    assert "tradesObserved" not in rep.recomputed


# ================================================================== C9

def test_c9_individual_trade_data_in_the_document_is_refused():
    entries = gledger(QUIET_DAY)
    cert = make_cert(entries, overrides={"subject": {"alias": "t", "accounts": ["a"],
                                                     "fillPrice": "5000.25"}})
    rep = verify_certificate(cert, entries)
    assert rep.exit_code == EXIT_CONTRADICTED
    assert "PRIVACY_LEAK" in codes(rep)


# ================================================================== C10

def test_c10_the_limitations_must_appear_verbatim():
    entries = gledger(QUIET_DAY)
    softened = [REQUIRED_LIMITATIONS[0].replace("does not say", "may not fully reflect")]
    softened += list(REQUIRED_LIMITATIONS[1:])
    rep = verify_certificate(make_cert(entries, overrides={"limitations": softened}), entries)
    assert rep.exit_code == EXIT_CONTRADICTED
    assert "LIMITATIONS_ALTERED" in codes(rep)


def test_c10_dropping_the_limitations_entirely_is_refused():
    entries = gledger(QUIET_DAY)
    rep = verify_certificate(make_cert(entries, overrides={"limitations": None}), entries)
    assert "LIMITATIONS_MISSING" in codes(rep)


# ================================================================== C11

def test_c11_a_day_with_no_trades_is_a_complete_certificate():
    entries = gledger(QUIET_DAY)
    rep = verify_certificate(make_cert(entries), entries)
    assert rep.ok
    assert rep.recomputed["limitRespected"] is True
    assert rep.recomputed["lockoutsTriggered"] == 0
    assert rep.recomputed["failClosedEpisodes"] == []


# ================================================================== C12 / C13

def _series_day(day, prev_hash, gaps=None):
    entries = gledger(QUIET_DAY)
    return make_cert(entries, day=day, prev_cert=prev_hash, gaps=gaps)


def test_c12_a_day_removed_from_the_middle_breaks_the_series():
    d1 = _series_day("2026-08-17", None)
    d2 = _series_day("2026-08-18", d1["certHash"])
    d3 = _series_day("2026-08-19", d2["certHash"])
    assert verify_series([d1, d2, d3]).ok

    rep = verify_series([d1, d3])          # d2 quietly removed
    assert rep.exit_code == EXIT_CONTRADICTED
    assert "SERIES_BROKEN" in codes(rep)


def test_c13_an_undeclared_gap_is_caught():
    d1 = _series_day("2026-08-17", None)
    d3 = _series_day("2026-08-19", d1["certHash"])       # 08-18 simply never happened
    rep = verify_series([d1, d3])
    assert rep.exit_code == EXIT_CONTRADICTED
    assert "GAP_UNDECLARED" in codes(rep)
    assert "2026-08-18" in " ".join(f.detail for f in rep.contradictions)


def test_c13_a_declared_gap_with_a_reason_is_accepted():
    d1 = _series_day("2026-08-17", None)
    d3 = _series_day("2026-08-19", d1["certHash"],
                     gaps=[{"dayKey": "2026-08-18", "reason": "not-armed"}])
    rep = verify_series([d1, d3])
    assert rep.ok, [str(f) for f in rep.contradictions]


def test_c13_a_gap_without_a_reason_is_refused():
    d1 = _series_day("2026-08-17", None)
    d3 = _series_day("2026-08-19", d1["certHash"], gaps=[{"dayKey": "2026-08-18"}])
    rep = verify_series([d1, d3])
    assert "GAP_WITHOUT_REASON" in codes(rep)


# ================================================================== C14

def test_c14_rejected_attempts_to_loosen_the_limit_appear_in_the_claims():
    events = QUIET_DAY[:5] + [
        ("CONFIG_CHANGE_REJECTED", {"attempted": "9000.00", "sealed": "600.00"}),
        ("CONFIG_CHANGE_REJECTED", {"attempted": "1200.00", "sealed": "600.00"}),
        ("DAY_CLOSED", {"dayKey": "2026-08-21"}),
    ]
    entries = gledger(events)
    rep = verify_certificate(make_cert(entries), entries)
    assert rep.recomputed["changeAttemptsWhileSealed"] == 2
    assert rep.ok

    hidden = make_cert(entries, overrides={"commitment.changeAttemptsWhileSealed": 0})
    assert verify_certificate(hidden, entries).exit_code == EXIT_CONTRADICTED


# ================================================================== C15

def test_c15_a_valid_signature_over_false_claims_still_falls_to_recompute():
    ed = pytest.importorskip("cryptography.hazmat.primitives.asymmetric.ed25519",
                             reason="signature checking needs deadman-kit[verify-sig]")
    serialization = pytest.importorskip("cryptography.hazmat.primitives.serialization")

    entries = gledger(BREACH_DAY)
    key = ed.Ed25519PrivateKey.generate()
    cert = make_cert(entries, overrides={"claims.limitRespected": True,
                                         "claims.lockoutsTriggered": 0})
    signature = key.sign(cert["certHash"].encode())
    cert["signature"] = {"alg": "Ed25519", "keyId": "test-key", "value": signature.hex()}

    pem = key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo)
    keyfile = Path(__file__).parent / "_c15_pub.pem"
    keyfile.write_bytes(pem)
    try:
        rep = verify_certificate(cert, entries, pubkey_path=keyfile)
        assert rep.signature_status.startswith("VALID"), rep.signature_status
        assert rep.exit_code == EXIT_CONTRADICTED          # signed, and still a liar
        assert "CLAIM_MISMATCH" in codes(rep)
    finally:
        keyfile.unlink(missing_ok=True)


def test_c15_without_the_extra_the_signature_degrades_it_never_validates(monkeypatch):
    import deadman.verify_certificate as vc
    entries = gledger(QUIET_DAY)
    cert = make_cert(entries, trust="L1")
    cert["signature"] = {"alg": "Ed25519", "keyId": "k", "value": "00"}
    cert["certHash"] = hashlib.sha256(_cert_preimage(cert)).hexdigest()

    def no_crypto(name):
        raise ImportError("simulating a machine without the extra")
    monkeypatch.setattr(vc.importlib, "import_module", no_crypto)

    rep = vc.verify_certificate(cert, entries, pubkey_path=Path("whatever.pem"))
    assert rep.signature_status == "NOT_VERIFIED (extra not installed)"
    assert rep.reached_level == "L1"                       # never L3
    assert "SIGNATURE_UNCHECKED" in {f.code for f in rep.unverified}


def test_c15_l3_is_never_reached_without_l2():
    """A signature dates nothing. Origin without a third-party anchor stays L1 (A.3)."""
    ed = pytest.importorskip("cryptography.hazmat.primitives.asymmetric.ed25519")
    serialization = pytest.importorskip("cryptography.hazmat.primitives.serialization")
    entries = gledger(QUIET_DAY)
    key = ed.Ed25519PrivateKey.generate()
    cert = make_cert(entries, trust="L1")
    cert["signature"] = {"alg": "Ed25519", "keyId": "k",
                         "value": key.sign(cert["certHash"].encode()).hex()}
    keyfile = Path(__file__).parent / "_c15b_pub.pem"
    keyfile.write_bytes(key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo))
    try:
        rep = verify_certificate(cert, entries, pubkey_path=keyfile)
        assert rep.signature_status.startswith("VALID")
        assert rep.reached_level == "L1"
    finally:
        keyfile.unlink(missing_ok=True)


# ================================================================== C17

def test_c17_a_crossed_dialect_fails_closed():
    entries = gledger(QUIET_DAY)
    cert = make_cert(entries, overrides={"ledgerDialect": "deadman-kit-v1"})
    rep = verify_certificate(cert, entries)
    assert rep.exit_code == EXIT_UNEVALUABLE
    assert "DIALECT_MISMATCH" in {f.code for f in rep.unevaluable}
    assert not rep.contradictions
    assert "NOTHING_ELSE_CHECKED" in {f.code for f in rep.unverified}


def test_c17_the_other_crossing_too():
    entries = kledger(QUIET_DAY)
    cert = make_cert(entries, DEADMAN_KIT_V1, overrides={"ledgerDialect": "guardian-core-v1"})
    rep = verify_certificate(cert, entries)
    assert "DIALECT_MISMATCH" in {f.code for f in rep.unevaluable}


def test_c17_an_honest_certificate_cannot_be_smeared_with_the_wrong_ledger():
    """The reason exit 1 was wrong here, as a case rather than as an argument.

    Nobody touches the certificate. Handing the verifier a ledger in the other dialect used to
    produce CONTRADICTED - "I caught you lying" - about a document that says nothing false. A
    script reading only the exit code rejected an honest trader over someone else's file-picking
    mistake. The control is the same certificate with its own ledger, which must still pass."""
    entries = gledger(QUIET_DAY)
    honest = make_cert(entries)

    good = verify_certificate(honest, entries)
    assert good.exit_code == EXIT_OK                    # control: it must be capable of passing

    smeared = verify_certificate(honest, kledger(QUIET_DAY))
    assert smeared.exit_code == EXIT_UNEVALUABLE
    assert not smeared.contradictions, "an honest certificate must never be called a liar"
    assert "DIALECT_MISMATCH" in {f.code for f in smeared.unevaluable}


def test_c17_an_undeclared_dialect_is_unevaluable_not_guessed():
    entries = gledger(QUIET_DAY)
    cert = make_cert(entries, drop=())
    del cert["ledgerDialect"]
    rep = verify_certificate(cert, entries)
    assert rep.exit_code == EXIT_UNEVALUABLE
    assert any(f.code == "DIALECT_MISSING" for f in rep.unevaluable)


# ================================================================== C18

def test_c18_exit_codes_separate_a_lie_from_an_unreadable_input():
    entries = gledger(BREACH_DAY)
    liar = make_cert(entries, overrides={"claims.lockoutsTriggered": 0})
    assert verify_certificate(liar, entries).exit_code == EXIT_CONTRADICTED

    broken = make_cert(entries, overrides={"claims": {"ledgerRange": {"fromSeq": "x"}}})
    assert verify_certificate(broken, entries).exit_code == EXIT_UNEVALUABLE

    assert verify_certificate(make_cert(entries), entries).exit_code == EXIT_OK


def test_c18_the_cli_returns_those_codes(tmp_path):
    entries = gledger(BREACH_DAY)
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text("\n".join(json.dumps(e) for e in entries), encoding="utf-8")

    honest = tmp_path / "honest.json"
    honest.write_text(json.dumps(make_cert(entries)), encoding="utf-8")
    liar = tmp_path / "liar.json"
    liar.write_text(json.dumps(make_cert(entries, overrides={"claims.lockoutsTriggered": 0})),
                    encoding="utf-8")
    junk = tmp_path / "junk.json"
    junk.write_text("{not json", encoding="utf-8")

    root = Path(__file__).resolve().parents[1]
    env = dict(os.environ)
    env["PYTHONPATH"] = str(root) + os.pathsep + env.get("PYTHONPATH", "")

    def run(cert):
        return subprocess.run([sys.executable, "-m", "deadman.verify_certificate",
                               str(cert), str(ledger)],
                              capture_output=True, text=True, cwd=str(root), env=env)

    ok = run(honest)
    assert ok.returncode == EXIT_OK, ok.stdout + ok.stderr
    assert "VERIFIED at L1" in ok.stdout
    assert "COULD NOT VERIFY" in ok.stdout          # printed even on success

    bad = run(liar)
    assert bad.returncode == EXIT_CONTRADICTED
    assert "CONTRADICTED" in bad.stdout

    ugly = run(junk)
    assert ugly.returncode == EXIT_UNEVALUABLE


def test_c18_the_cli_output_is_ascii_safe():
    """A cp1252 Windows console is the machine we are asking a stranger to run this on."""
    entries = gledger(DISCONNECT_DAY)
    rep = verify_certificate(make_cert(entries), entries)
    rep.render().encode("cp1252")                   # raises if we smuggled a section sign in


# ================================================================== the judge itself

# ================================================================== DEF-2

def _episode_ledger(extra=None, where="before"):
    """A fail-closed episode, optionally with one extra event beside its entry."""
    rows = gledger(DISCONNECT_DAY)
    i = next(n for n, r in enumerate(rows) if r.get("event") == "FAIL_CLOSED_ENTERED")
    if extra is not None:
        rows.insert(i if where == "before" else i + 1, dict(extra))
    for n, r in enumerate(rows, start=1):
        r["seq"] = n
    prev = "genesis"
    for r in rows:
        r["prev"] = prev
        r.pop("hash", None)
        r["hash"] = GUARDIAN_CORE_V1.hash_of(r)
        prev = r["hash"]
    return rows


def _reseal(cert):
    """Mutating a cert breaks its own certHash; these tests are about the CLAIM check."""
    from deadman.verify_certificate import _cert_preimage, _sha256_hex
    cert.pop("certHash", None)
    cert["certHash"] = _sha256_hex(_cert_preimage(cert))
    return cert


def _ev(name):
    return {"event": name, "payload": {}, "schemaVersion": 1, "seq": 0,
            "tsUtc": "2026-02-18T15:59:00.000Z"}


def test_def2_the_field_no_longer_claims_a_cause_it_never_derived():
    """`triggerEvent` promised the thing that caused the episode and delivered whatever happened
    to be adjacent. Renamed to what it measures. The rule was always positional; only the name
    said otherwise."""
    rows = _episode_ledger()
    ep = recompute_claims(rows, GUARDIAN_CORE_V1, 1, len(rows), True)["failClosedEpisodes"][0]
    assert "precedingEvent" in ep and "precedingSeq" in ep
    assert "triggerEvent" not in ep and "triggerSeq" not in ep


def test_def2_an_ordinary_event_before_the_entry_is_still_reported():
    """CONTROL for the two HUMAN_ tests below: the position is still read, and reported."""
    rows = _episode_ledger(_ev("PNL_CHECKPOINT"))
    ep = recompute_claims(rows, GUARDIAN_CORE_V1, 1, len(rows), True)["failClosedEpisodes"][0]
    assert ep["precedingEvent"] == "PNL_CHECKPOINT"
    assert ep["reasons"].get("PNL_CHECKPOINT") == 1


def test_def2_a_human_event_never_becomes_the_preceding_event():
    """An acknowledgement is testimony about a PERSON. Published as the thing before a
    fail-closed entry, a reader gets 'the guardian went blind, and here is what came first' with
    a human act in the slot. It is excluded by construction, not by care."""
    rows = _episode_ledger(_ev("HUMAN_ACK"))
    ep = recompute_claims(rows, GUARDIAN_CORE_V1, 1, len(rows), True)["failClosedEpisodes"][0]
    assert ep["precedingEvent"] != "HUMAN_ACK"
    assert "HUMAN_ACK" not in ep["reasons"]


def test_def2_a_human_event_inside_an_episode_is_not_one_of_its_reasons():
    """The position an acknowledgement will ACTUALLY occupy: inside the blind stretch, because
    that is the state a human is being asked to acknowledge. Measured before the fix, it was
    counted among the episode's `reasons` - a human fact inside the machine's causal account."""
    rows = _episode_ledger(_ev("HUMAN_ACK"), where="inside")
    ep = recompute_claims(rows, GUARDIAN_CORE_V1, 1, len(rows), True)["failClosedEpisodes"][0]
    assert "HUMAN_ACK" not in ep["reasons"], ep["reasons"]


def test_def2_a_human_event_changes_not_one_number():
    """§5.4 in one assertion: an acknowledgement is testimony, never evidence about the account."""
    plain = recompute_claims(_episode_ledger(), GUARDIAN_CORE_V1, 1, 99, True)
    acked = recompute_claims(_episode_ledger(_ev("HUMAN_ACK"), where="inside"),
                             GUARDIAN_CORE_V1, 1, 99, True)
    for k in ("lockoutsTriggered", "changeAttemptsWhileSealed", "ordersRejectedWhileLocked",
              "clockAnomalies", "limitRespected"):
        assert plain[k] == acked[k], k
    assert plain["failClosedEpisodes"][0]["reasons"] == acked["failClosedEpisodes"][0]["reasons"]


def test_def2_the_preceding_event_is_now_compared():
    """It was the one field in the episode block nobody checked, and it is the one that assigns
    blame: a fabrication used to verify clean at exit 0."""
    entries = gledger(DISCONNECT_DAY)
    cert = make_cert(entries)
    assert verify_certificate(cert, entries).exit_code == EXIT_OK      # control: it can pass

    cert["claims"]["failClosedEpisodes"][0]["precedingEvent"] = "SOMETHING_THAT_NEVER_HAPPENED"
    rep = verify_certificate(_reseal(cert), entries)
    assert rep.exit_code == EXIT_CONTRADICTED
    assert "CLAIM_MISMATCH" in codes(rep)
    assert "CERTHASH_MISMATCH" not in codes(rep), "must fail on the CLAIM, not on the hash"


def test_def2_either_spelling_is_accepted_while_the_emitter_migrates():
    """Renaming a field of the CERTIFICATE is the emitter's side of the contract, so the verifier
    reads both. The shipped examples still carry `triggerEvent` and must keep verifying."""
    entries = gledger(DISCONNECT_DAY)
    cert = make_cert(entries)
    ep = cert["claims"]["failClosedEpisodes"][0]
    ep["triggerEvent"] = ep.pop("precedingEvent")      # the emitter's current spelling
    ep["triggerSeq"] = ep.pop("precedingSeq")
    assert verify_certificate(_reseal(cert), entries).exit_code == EXIT_OK


def test_def2_a_certificate_that_names_no_preceding_event_is_not_accused():
    """Absence is not a lie (§5.8): an older emitter that never wrote the field must not be
    called a liar for it."""
    entries = gledger(DISCONNECT_DAY)
    cert = make_cert(entries)
    ep = cert["claims"]["failClosedEpisodes"][0]
    ep.pop("precedingEvent", None)
    ep.pop("precedingSeq", None)
    ep.pop("triggerEvent", None)
    ep.pop("triggerSeq", None)
    rep = verify_certificate(_reseal(cert), entries)
    assert rep.exit_code == EXIT_OK
    assert "CLAIM_ABSENT" in {f.code for f in rep.unverified}


# ================================================================== DEF-6

def test_def6_a_ledger_cut_short_is_not_a_certificate_that_lied():
    """A power cut is a condition this machine produces, not a hypothetical: twice in 48 hours.

    The writer fsyncs after every complete line, so the file comes back cut at a LINE BOUNDARY -
    valid JSON, whole rows, just fewer of them. Before this, that verdict was CONTRADICTED, which
    is the tool saying *I caught you lying* about a document that says nothing false."""
    entries = gledger(DISCONNECT_DAY)
    cert = make_cert(entries)
    assert verify_certificate(cert, entries).exit_code == EXIT_OK      # control: it can pass

    rep = verify_certificate(cert, entries[:-1])
    assert rep.exit_code == EXIT_UNEVALUABLE
    assert not rep.contradictions, "a short file must never be charged as a lie"
    assert "LEDGER_TRUNCATED" in {f.code for f in rep.unevaluable}


def test_def6_tampering_is_still_caught_after_the_truncation_fix():
    """THE CONTROL THAT MUST SURVIVE. If teaching the verifier about truncation also blunted its
    detection of forgery, we would have traded one harm for a worse one."""
    entries = gledger(DISCONNECT_DAY)
    cert = make_cert(entries)

    tampered = [dict(e) for e in entries]
    tampered[3] = dict(tampered[3])
    tampered[3]["payload"] = {**tampered[3].get("payload", {}), "planted": True}

    rep = verify_certificate(cert, tampered)
    assert rep.exit_code == EXIT_CONTRADICTED
    assert "CHAIN_BROKEN" in codes(rep)


def test_def6_tampering_wins_when_a_file_is_both_cut_and_forged():
    """Truncation is only an excuse when nothing else is wrong. A broken link is a broken link."""
    entries = gledger(DISCONNECT_DAY)
    cert = make_cert(entries)
    both = [dict(e) for e in entries[:-1]]
    both[3] = dict(both[3])
    both[3]["payload"] = {**both[3].get("payload", {}), "planted": True}

    rep = verify_certificate(cert, both)
    assert rep.exit_code == EXIT_CONTRADICTED
    assert "CHAIN_BROKEN" in codes(rep)


def test_def6_a_hole_in_the_middle_is_not_a_truncation():
    """THE CHAIN CANNOT BE TRUNCATED FROM THE FRONT: that is what makes this discriminator free.
    Rows missing from the MIDDLE break the link and are not excused."""
    entries = gledger(DISCONNECT_DAY)
    cert = make_cert(entries)
    holed = entries[:4] + entries[5:]

    rep = verify_certificate(cert, holed)
    assert rep.exit_code == EXIT_CONTRADICTED
    assert "CHAIN_BROKEN" in codes(rep)


def test_def6_a_truncated_ledger_never_says_the_trader_breached_the_limit():
    """The actual damage, as its own case. Losing a FAIL_CLOSED_CLEARED leaves the episode open,
    and `limitRespected` requires that none are - so a power cut used to publish, as a finding,
    that the holder went past their limit. The claims are still recomputed; what changed is that
    a disagreement over a file with its tail missing is reported, not charged."""
    entries = gledger(DISCONNECT_DAY)
    cert = make_cert(entries)

    for cut in range(1, 4):
        rep = verify_certificate(cert, entries[:-cut])
        assert rep.exit_code != EXIT_CONTRADICTED, f"cut={cut}"
        charged = " ".join(f"{f.code}: {f.detail}" for f in rep.contradictions)
        assert "limitRespected" not in charged, f"cut={cut}: {charged}"


# ================================================================== DEF-5 / 6b

def _sign(cert, key, tmp_path, serialization):
    """Sign a certificate over its own certHash and return the public key on disk."""
    cert["signature"] = {"alg": "Ed25519", "keyId": "whatever-the-emitter-wrote",
                         "value": key.sign(cert["certHash"].encode()).hex()}
    pem = tmp_path / "pub.pem"
    pem.write_bytes(key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo))
    return pem


def test_def5_the_verdict_line_names_no_key_it_did_not_check(tmp_path):
    """A FIELD PRINTED INSIDE A VERDICT INHERITS THE AUTHORITY OF THE VERDICT.

    `issuer.keyId` was interpolated into the VALID line and was never checked against anything -
    measured, a certificate signed by one key while naming another reported
    `VALID (keyId=<the key that signed nothing>)`. The key that actually verifies is the one the
    RECIPIENT supplied, and no PEM carries an identifier of its own, so there was nothing to check
    it against. The fix is removal, not a caveat: a caveat beside an authorised claim loses."""
    ed = pytest.importorskip("cryptography.hazmat.primitives.asymmetric.ed25519",
                             reason="signature checking needs deadman-kit[verify-sig]")
    serialization = pytest.importorskip("cryptography.hazmat.primitives.serialization")

    entries = gledger(QUIET_DAY)
    key, other = ed.Ed25519PrivateKey.generate(), ed.Ed25519PrivateKey.generate()

    cert = make_cert(entries)
    cert["issuer"]["keyId"] = "key-ALPHA-which-signed-nothing"
    _reseal(cert)
    pem = _sign(cert, other, tmp_path, serialization)          # signed by OTHER, not by ALPHA

    rep = verify_certificate(cert, entries, pubkey_path=pem)
    assert rep.signature_status == "VALID"
    assert "key-ALPHA" not in rep.signature_status
    assert "keyId" not in rep.signature_status
    assert "key-ALPHA" not in rep.render()
    assert key is not other                                    # both keys were really distinct


def test_def5_a_good_signature_still_reads_as_valid(tmp_path):
    """CONTROL. Removing the field must not weaken what VALID means, and `VALID` on its own is
    exactly what the verifier knows: the key you supplied signed this."""
    ed = pytest.importorskip("cryptography.hazmat.primitives.asymmetric.ed25519",
                             reason="signature checking needs deadman-kit[verify-sig]")
    serialization = pytest.importorskip("cryptography.hazmat.primitives.serialization")

    entries = gledger(QUIET_DAY)
    key = ed.Ed25519PrivateKey.generate()
    cert = make_cert(entries)
    pem = _sign(cert, key, tmp_path, serialization)

    rep = verify_certificate(cert, entries, pubkey_path=pem)
    assert rep.signature_status == "VALID"
    assert rep.exit_code == EXIT_OK


def test_def5_a_bad_signature_is_still_caught(tmp_path):
    """CONTROL that must survive: teaching it to say less must not make it accept more."""
    ed = pytest.importorskip("cryptography.hazmat.primitives.asymmetric.ed25519",
                             reason="signature checking needs deadman-kit[verify-sig]")
    serialization = pytest.importorskip("cryptography.hazmat.primitives.serialization")

    entries = gledger(QUIET_DAY)
    key, other = ed.Ed25519PrivateKey.generate(), ed.Ed25519PrivateKey.generate()
    cert = make_cert(entries)
    _sign(cert, key, tmp_path, serialization)
    wrong = tmp_path / "wrong.pem"
    wrong.write_bytes(other.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo))

    rep = verify_certificate(cert, entries, pubkey_path=wrong)
    assert rep.signature_status == "INVALID"
    assert rep.exit_code == EXIT_CONTRADICTED
    assert "SIGNATURE_INVALID" in codes(rep)


def test_the_verifier_can_actually_refuse():
    """The meta-guarantee of SPEC section 5: a verifier that only says OK is a rubber stamp.
    Every attack here must be REFUSED - never exit 0 - and must name what it found.

    Refusal has two channels and they are not interchangeable. Four of these are the certificate
    saying something the ledger denies, and those are contradictions (exit 1). The crossed
    dialect is not: the verifier cannot tell a certificate that lies about its dialect from an
    honest certificate handed the wrong file, because the two produce identical input. So it
    reports UNEVALUABLE (exit 2) - still a refusal, never a pass. The price is named rather than
    hidden: a certificate that genuinely lies about its dialect is no longer called a liar. That
    price is paid on purpose, because the alternative punishes the honest holder."""
    entries = gledger(BREACH_DAY)
    lies = {
        "claim": make_cert(entries, overrides={"claims.lockoutsTriggered": 0}),
        "trust": make_cert(entries, trust="L3"),
        "limitations": make_cert(entries, overrides={"limitations": []}),
        "certhash": {**make_cert(entries), "certHash": "0" * 64},
    }
    indistinguishable = {
        "dialect": make_cert(entries, overrides={"ledgerDialect": "deadman-kit-v1"}),
    }

    for name, cert in {**lies, **indistinguishable}.items():
        rep = verify_certificate(cert, entries)
        assert rep.exit_code != EXIT_OK, f"{name} was not refused"
        assert rep.contradictions or rep.unevaluable, f"{name} refused without naming anything"

    for name, cert in lies.items():
        rep = verify_certificate(cert, entries)
        assert rep.contradictions, f"{name} must be a contradiction"
        assert rep.exit_code == EXIT_CONTRADICTED, name
        if name == "trust":
            assert rep.reached_level == "L1" and rep.declared_level == "L3"

    for name, cert in indistinguishable.items():
        rep = verify_certificate(cert, entries)
        assert rep.exit_code == EXIT_UNEVALUABLE, name
        assert not rep.contradictions, f"{name} must not accuse: it cannot tell who is at fault"


# ------------------------------------------------- the reachable layer is named, 0.2.2
# Audit finding behind these: a whole run never contained the strings "L2", "L3" or
# "--anchors". The tool told the reader that L1 does not survive disk access and left them
# with no way to know a better layer existed, let alone how to get there. Naming a limit
# without naming its remedy is half a disclosure.

def test_a_run_that_lands_on_L1_names_the_layer_above_it_and_how_to_reach_it():
    entries = gledger(QUIET_DAY)
    out = verify_certificate(make_cert(entries), entries).render()

    assert "REACHED       L1" in out
    assert "L2" in out, "a reader at L1 is never told a better layer exists"
    assert "--anchors" in out, "and is never told what would take them there"
    # The remedy belongs beside the limitation, not in a footer the reader has left behind.
    anchor_block = next(l for l in out.splitlines() if "NO_EXTERNAL_ANCHOR" in l)
    assert "L2" in anchor_block and "--anchors" in anchor_block


def test_L1_is_marked_as_the_floor_and_a_higher_layer_is_not():
    """`VERIFIED` is the line that gets quoted. At L1 it must not read as a grade."""
    entries = gledger(QUIET_DAY)

    at_l1 = verify_certificate(make_cert(entries), entries)
    assert at_l1.reached_level == "L1"
    assert "RESULT: VERIFIED at L1, THE FLOOR LAYER (exit 0)." in at_l1.render()

    anchor = [{"seq": 7, "hash": entries[6]["hash"], "type": "tsa",
               "ref": "held-by-third-party", "tsUtc": TS % 30}]
    at_l2 = verify_certificate(make_cert(entries, trust="L2", anchors=anchor), entries,
                               anchors=anchor)
    assert at_l2.reached_level == "L2"
    out = at_l2.render()
    assert "RESULT: VERIFIED at L2 (exit 0)." in out
    assert "FLOOR" not in out, "the floor marker must not follow a layer that is not the floor"


def test_the_anchored_run_stops_advertising_the_remedy_it_no_longer_needs():
    """Control for the test above: the --anchors advice is tied to the anchor being ABSENT,
    not printed unconditionally, or it would be noise on every successful L2 run."""
    entries = gledger(QUIET_DAY)
    anchor = [{"seq": 7, "hash": entries[6]["hash"], "type": "tsa",
               "ref": "held-by-third-party", "tsUtc": TS % 30}]
    out = verify_certificate(make_cert(entries, trust="L2", anchors=anchor), entries,
                             anchors=anchor).render()
    assert "NO_EXTERNAL_ANCHOR" not in out
    assert "--anchors" not in out
