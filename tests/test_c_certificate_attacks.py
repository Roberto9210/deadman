"""Attacks beyond the eighteen named guarantees.

Nothing here is C-numbered. These are probes invented by asking "what have we not tried?"
*after* the guarantee suite was green, which is the only moment that question gets an
interesting answer.

The first one found a real hole. Every claim is recomputed over the range the certificate
DECLARES, so a liar declares a shorter range: truncated one entry before LIMIT_BREACHED, a
certificate verified clean at L1 with `limitRespected: true`, and every recomputed number
agreed with it, because the arithmetic was honest over a window chosen to exclude the truth.
The claim check could never have caught that - it needed a check on the range itself.

Everything below stays so a later change cannot quietly reopen any of it.
"""

from __future__ import annotations

import hashlib

from deadman.verify_certificate import (
    EXIT_CONTRADICTED,
    EXIT_UNEVALUABLE, EXIT_OK, REQUIRED_LIMITATIONS, _cert_preimage,
    verify_certificate, verify_series,
)

from test_c_certificate import (
    BREACH_DAY, DISCONNECT_DAY, QUIET_DAY, TS, _series_day, codes, gledger, kledger, make_cert,
)


# ---------------------------------------------------------------- the declared range

def test_attack_range_truncated_to_hide_a_breach():
    """Claims recompute over the DECLARED range, so a liar declares a shorter one. What gives
    it away is that the certificate also names a day, and the ledger says when that day ended."""
    entries = gledger(BREACH_DAY)                     # LIMIT_BREACHED at seq 7
    liar = make_cert(entries[:6])                     # declares 1..6 and stops
    rep = verify_certificate(liar, entries)

    assert rep.exit_code == EXIT_CONTRADICTED
    assert "RANGE_TRUNCATED" in codes(rep)
    said = " ".join(f.detail for f in rep.contradictions)
    assert "LIMIT_BREACHED" in said, "the report must name what was excluded"

    # The claims themselves recompute perfectly over the short window. That is exactly why a
    # check on the RANGE had to exist: no amount of claim-checking would have found this.
    assert rep.recomputed["lockoutsTriggered"] == 0
    assert rep.recomputed["limitRespected"] is True


def test_attack_range_truncated_at_the_front():
    """The mirror image, and a smarter liar: the range starts AFTER the breach and every claim
    is recomputed honestly over that window, so the document is internally consistent."""
    entries = gledger(BREACH_DAY)
    liar = make_cert(entries[7:], lo=8)               # declares 8..14, breach was at 7
    rep = verify_certificate(liar, entries)

    assert rep.exit_code == EXIT_CONTRADICTED
    assert "RANGE_TRUNCATED" in codes(rep)
    assert "DAY_OPENED" in " ".join(f.detail for f in rep.contradictions)


def test_an_early_export_is_incomplete_not_a_lie():
    """The calibration that matters. Stopping early with nothing material outside the range is
    an incomplete document, not a contradiction - severity follows the harm. Without this, every
    honest mid-session export would be reported as a liar and the check would be worthless."""
    entries = gledger(QUIET_DAY)                      # DAY_CLOSED at seq 7
    cert = make_cert(entries[:5])                     # exported before the day closed
    rep = verify_certificate(cert, entries)

    assert rep.exit_code == EXIT_OK
    assert "SESSION_NOT_FULLY_COVERED" in {f.code for f in rep.unverified}
    assert "nothing is being hidden" in rep.render()


def test_attack_material_events_after_a_range_with_no_day_to_anchor_on():
    """No DAY_CLOSED anywhere, so nothing distinguishes an early export from a truncation.
    The verifier says that, rather than picking whichever side is convenient."""
    entries = gledger([e for e in BREACH_DAY if e[0] != "DAY_CLOSED"])
    rep = verify_certificate(make_cert(entries[:6]), entries)

    assert rep.exit_code == EXIT_OK                   # it cannot prove a lie, so it claims none
    assert "POST_RANGE_MATERIAL_EVENTS" in {f.code for f in rep.unverified}
    said = " ".join(f.detail for f in rep.unverified)
    assert "LIMIT_BREACHED" in said and "cannot tell" in said


# ---------------------------------------------------------------- the ledger itself

def test_attack_a_ledger_that_changes_dialect_halfway_down():
    """The dialect check used to read only the first entry, so a file that starts in one dialect
    and continues in another slipped past it and failed later as a confusing chain break."""
    entries = gledger(QUIET_DAY)
    entries[4] = kledger(QUIET_DAY)[4]                # one kit-shaped line in a guardian file
    rep = verify_certificate(make_cert(gledger(QUIET_DAY)), entries)

    assert rep.exit_code == EXIT_UNEVALUABLE
    assert "DIALECT_MISMATCH" in {f.code for f in rep.unevaluable}
    assert "entry 5" in " ".join(f.detail for f in rep.unevaluable)


def test_attack_ledger_lines_reordered():
    entries = gledger(QUIET_DAY)
    cert = make_cert(entries)
    entries[2], entries[4] = entries[4], entries[2]
    rep = verify_certificate(cert, entries)
    assert rep.exit_code == EXIT_CONTRADICTED
    assert "CHAIN_BROKEN" in codes(rep)


def test_attack_a_replayed_entry():
    """The same line twice. The chain must refuse it rather than let it be counted twice."""
    entries = gledger(BREACH_DAY)
    cert = make_cert(entries)
    entries.insert(7, dict(entries[6]))               # LIMIT_BREACHED again
    rep = verify_certificate(cert, entries)
    assert rep.exit_code == EXIT_CONTRADICTED
    assert "CHAIN_BROKEN" in codes(rep)


# ---------------------------------------------------------------- the document

def test_attack_a_limitation_softened_with_a_lookalike_character():
    """A Cyrillic small a for a Latin one reads identically and is a different string. C10 is an
    exact comparison precisely so this is not a matter of anyone's judgement."""
    latin = REQUIRED_LIMITATIONS[0]
    homoglyph = latin.replace("a", "а", 1)
    assert homoglyph != latin and len(homoglyph) == len(latin)

    entries = gledger(QUIET_DAY)
    softened = [homoglyph] + list(REQUIRED_LIMITATIONS[1:])
    rep = verify_certificate(make_cert(entries, overrides={"limitations": softened}), entries)
    assert rep.exit_code == EXIT_CONTRADICTED
    assert "LIMITATIONS_ALTERED" in codes(rep)


def test_attack_an_extra_field_smuggled_in_after_the_hash_was_computed():
    entries = gledger(QUIET_DAY)
    cert = make_cert(entries)
    cert["endorsement"] = "reviewed and approved by the firm"
    rep = verify_certificate(cert, entries)
    assert rep.exit_code == EXIT_CONTRADICTED
    assert "CERTHASH_MISMATCH" in codes(rep)


def test_attack_episodes_reordered_to_keep_the_count_right():
    """Same number of episodes, contents swapped. A count-only check would pass this."""
    entries = gledger(DISCONNECT_DAY + [
        ("ACCOUNT_UNKNOWN", {"detail": "Disconnected"}),
        ("FAIL_CLOSED_ENTERED", {"reason": "PnlUncomputable"}),
        ("PNL_UNCOMPUTABLE", {"detail": "no feed"}),
        ("FAIL_CLOSED_CLEARED", {"previousReason": "PnlUncomputable"}),
    ])
    honest = verify_certificate(make_cert(entries), entries)
    assert honest.ok and len(honest.recomputed["failClosedEpisodes"]) == 2

    swapped = make_cert(entries)
    eps = swapped["claims"]["failClosedEpisodes"]
    eps[0], eps[1] = eps[1], eps[0]
    swapped["certHash"] = hashlib.sha256(_cert_preimage(swapped)).hexdigest()

    rep = verify_certificate(swapped, entries)
    assert rep.exit_code == EXIT_CONTRADICTED
    assert "CLAIM_MISMATCH" in codes(rep)


# ---------------------------------------------------------------- anchors

def test_an_anchor_is_valid_for_any_ledger_sharing_that_prefix():
    """Not a hole, and worth pinning down because it looked like one. BREACH_DAY begins with
    QUIET_DAY, so an anchor over their common prefix is genuinely valid for both: up to that
    seq they ARE the same history. An anchor attests a prefix, not a whole file."""
    breach, quiet = gledger(BREACH_DAY), gledger(QUIET_DAY)
    assert breach[2]["hash"] == quiet[2]["hash"]
    anchor = [{"seq": 3, "hash": quiet[2]["hash"], "type": "tsa", "ref": "third-party",
               "tsUtc": TS % 3}]
    rep = verify_certificate(make_cert(breach, trust="L2", anchors=anchor), breach, anchors=anchor)
    assert rep.ok and rep.reached_level == "L2"
    assert rep.covered_up_to_seq == 3


def test_attack_an_anchor_borrowed_from_a_genuinely_different_ledger():
    entries = gledger(BREACH_DAY)
    other = gledger([("GUARDIAN_STARTED", {"fresh": False}),
                     ("CONFIG_LOADED", {"configHash": "different"}),
                     ("ARMED", {"accounts": ["OTHER"], "personalLimit": "50.00"})])
    assert other[2]["hash"] != entries[2]["hash"]
    anchor = [{"seq": 3, "hash": other[2]["hash"], "type": "tsa", "ref": "elsewhere",
               "tsUtc": TS % 3}]
    rep = verify_certificate(make_cert(entries, trust="L2", anchors=anchor), entries,
                             anchors=anchor)
    assert rep.exit_code == EXIT_CONTRADICTED
    assert "ANCHOR_MISMATCH" in codes(rep)
    assert rep.reached_level == "L1", "a failed anchor must not lift the level it failed to support"


# ---------------------------------------------------------------- the series

def test_attack_two_certificates_for_the_same_day():
    d1 = _series_day("2026-08-17", None)
    d2 = _series_day("2026-08-17", d1["certHash"])
    rep = verify_series([d1, d2])
    assert rep.exit_code == EXIT_CONTRADICTED
    assert "SERIES_DUPLICATE_DAY" in codes(rep)


def test_attack_a_certificate_that_names_itself_as_its_predecessor():
    d = _series_day("2026-08-17", None)
    d["previousCertHash"] = d["certHash"]
    rep = verify_series([d])
    assert rep.exit_code == EXIT_CONTRADICTED
    assert "SERIES_SELF_REFERENCE" in codes(rep)


def test_attack_a_series_chained_against_the_calendar():
    """Every link is present; only comparing them against the dates catches the direction."""
    d1 = _series_day("2026-08-17", None)
    d2 = _series_day("2026-08-18", None)
    d1["previousCertHash"] = d2["certHash"]
    rep = verify_series([d1, d2])
    assert rep.exit_code == EXIT_CONTRADICTED
    assert "SERIES_BROKEN" in codes(rep)
