"""Seal-continuity coverage, derived by the verifier (guardian SPEC section 17.2).

The gap being made visible is stated in that specification and cannot be closed without a time
source off the machine, which v1 does not have. It can be made NOISY: an ordinary restart lasts
seconds, and a long gap in the middle of a sealed session is the shape the attack needs.

Two properties are load-bearing and are asserted here, not just implemented:

* **No path is silent.** A clean shutdown yields a measurable gap; an unclean one yields no
  duration BUT is reported as unclean, with the reason. An absent number is a mystery; an absent
  number with a stated reason is information.
* **Nothing accuses.** Every quantity has an innocent explanation that is also the common one, so
  the wording describes coverage and never blame.

And one thing that must NOT be built, recorded so nobody "improves" it later: gaps are never
inferred from silence in the ledger. The guardian's five-minute PNL_CHECKPOINT heartbeat is not
emitted while DISARMED or while LOCKED - `Tick()` returns before reaching it in both states - so a
four-hour lockout with the guardian running perfectly leaves no events at all. Measuring silence
would report four hours "with no guardian", which is false, and false in the accusing direction.
"""

from __future__ import annotations

import json

from deadman.verify_certificate import (
    DEADMAN_KIT_V1, GUARDIAN_CORE_V1, find_backwards_timestamps, recompute_continuity,
    verify_certificate,
)

from test_c_certificate import QUIET_DAY, kledger, make_cert


def led(events):
    """(event, HH:MM:SS, payload) -> a chained guardian-dialect ledger."""
    out, prev = [], GUARDIAN_CORE_V1.genesis
    for i, (name, clock, payload) in enumerate(events, start=1):
        e = {"seq": i, "tsUtc": f"2026-08-19T{clock}.000Z", "event": name,
             "schemaVersion": 1, "payload": payload, "prev": prev}
        e["hash"] = GUARDIAN_CORE_V1.hash_of(e)
        prev = e["hash"]
        out.append(e)
    return out


def continuity(entries):
    return recompute_continuity(entries, GUARDIAN_CORE_V1, 1, len(entries))


ARMED_OPENING = [
    ("GUARDIAN_STARTED", "13:00:00", {}),
    ("ARMED", "13:05:00", {}),
    ("SEAL_CREATED", "13:05:01", {}),
    ("DAY_OPENED", "13:05:02", {"dayKey": "2026-08-19"}),
]


# ---------------------------------------------------------------- the quiet day

def test_a_day_with_no_restarts_reads_exactly_one_hundred_percent():
    """A clean day must read 1.00. It read 0.92 while the window started at ARMED instead of
    SEAL_CREATED - and a coverage figure that is not 100% on a spotless day is one nobody will
    ever trust again."""
    c = continuity(led(ARMED_OPENING + [
        ("PNL_CHECKPOINT", "16:00:00", {"dayLoss": "0.00"}),
        ("DAY_CLOSED", "17:00:00", {"dayKey": "2026-08-19"}),
    ]))
    assert c["continuityCoverage"] == 1.0
    assert c["processRestarts"] == 0
    assert c["uncleanShutdowns"] == 0
    assert c["unmonitoredMs"] == 0
    assert c["longestGapMs"] == 0


def test_the_first_start_of_a_fresh_process_is_not_a_restart():
    """Every ledger opens with GUARDIAN_STARTED before anything is armed. Counting it inflated
    every quiet day by one restart."""
    c = continuity(led(ARMED_OPENING + [("DAY_CLOSED", "17:00:00", {"dayKey": "2026-08-19"})]))
    assert c["processRestarts"] == 0


# ---------------------------------------------------------------- the two halves of the partition

def test_a_clean_shutdown_makes_the_gap_measurable():
    """Half one: the attacker who closes the platform from the menu. GUARDIAN_STOPPED is written,
    so the four-hour hole has a start and a duration, and both are reported."""
    c = continuity(led(ARMED_OPENING + [
        ("GUARDIAN_STOPPED", "13:30:00", {"state": "ARMED"}),
        ("GUARDIAN_STARTED", "17:39:00", {"state": "ARMED"}),
        ("SEAL_EXPIRED", "17:39:01", {"basis": "wallclock"}),
        ("DAY_CLOSED", "17:39:02", {"dayKey": "2026-08-19"}),
    ]))
    assert c["processRestarts"] == 1
    assert c["uncleanShutdowns"] == 0
    assert c["longestGapMs"] == 4 * 3600_000 + 9 * 60_000
    assert c["unmonitoredMs"] == c["longestGapMs"]
    assert c["continuityCoverage"] < 0.2


def test_an_unclean_exit_omits_the_duration_but_never_goes_silent():
    """Half two: the attacker who kills the process, so Stop() never runs and no GUARDIAN_STOPPED
    is written. The gap has no measurable start - and the absence itself is the signal, reported
    with its reason rather than left as a hole in the output."""
    c = continuity(led(ARMED_OPENING + [
        ("PNL_CHECKPOINT", "13:30:00", {"dayLoss": "0.00"}),
        ("GUARDIAN_STARTED", "17:39:00", {"state": "ARMED"}),
        ("SEAL_EXPIRED", "17:39:01", {"basis": "wallclock"}),
        ("DAY_CLOSED", "17:39:02", {"dayKey": "2026-08-19"}),
    ]))
    assert c["processRestarts"] == 1
    assert c["uncleanShutdowns"] == 1
    assert c["unmonitoredMs"] is None
    assert c["longestGapMs"] is None
    assert "without a clean shutdown" in c["durationsOmittedBecause"]


def test_neither_half_of_the_partition_is_silent():
    """The property the whole design rests on: whichever way a session ends, something is said."""
    clean = continuity(led(ARMED_OPENING + [
        ("GUARDIAN_STOPPED", "13:30:00", {}), ("GUARDIAN_STARTED", "17:39:00", {})]))
    unclean = continuity(led(ARMED_OPENING + [("GUARDIAN_STARTED", "17:39:00", {})]))

    assert clean["longestGapMs"] is not None            # a duration
    assert unclean["uncleanShutdowns"] == 1             # or a named reason
    assert unclean["durationsOmittedBecause"]


# ---------------------------------------------------------------- sealExpiryBasis

def test_monotonic_is_reported_as_a_positive_guarantee():
    c = continuity(led(ARMED_OPENING + [
        ("SEAL_EXPIRED", "22:00:00", {"basis": "monotonic"}),
        ("DAY_CLOSED", "22:00:01", {"dayKey": "2026-08-19"}),
    ]))
    assert c["sealExpiryBasis"] == "monotonic"


def test_wallclock_is_the_normal_case_and_the_report_says_so():
    """It is what every trader who closes the platform at the end of the day produces. If a risk
    desk reads it as a finding, the field has done harm rather than good."""
    entries = led(ARMED_OPENING + [
        ("GUARDIAN_STOPPED", "16:00:00", {}),
        ("GUARDIAN_STARTED", "16:00:20", {}),
        ("SEAL_EXPIRED", "22:00:00", {"basis": "wallclock"}),
        ("DAY_CLOSED", "22:00:01", {"dayKey": "2026-08-19"}),
    ])
    rep = verify_certificate(make_cert(entries), entries)
    text = rep.render()

    assert "the normal case" in text
    assert "it is not a finding" in text
    assert "does not by itself" in text or "not that anyone did anything" in text
    # And the absence of a monotonic ending must never be phrased as a finding.
    assert "monotonic" not in text.split("SEAL CONTINUITY")[1].split("Restarts happen")[0]


# ---------------------------------------------------------------- the return journey

def test_a_timestamp_that_moves_backwards_is_caught():
    """Moving a clock forward leaves no backwards step; moving it BACK does, and it has to be
    moved back to keep trading against coherent market data. That leg cannot be avoided, and it
    cannot be repaired quietly because the entries chain."""
    entries = led(ARMED_OPENING + [
        ("PNL_CHECKPOINT", "18:00:00", {}),
        ("PNL_CHECKPOINT", "13:40:00", {}),
        ("DAY_CLOSED", "13:45:00", {"dayKey": "2026-08-19"}),
    ])
    found = find_backwards_timestamps(entries, GUARDIAN_CORE_V1, 1, len(entries))

    assert len(found) == 1
    assert found[0]["fromSeq"] == 5 and found[0]["toSeq"] == 6
    assert found[0]["byMs"] == 4 * 3600_000 + 20 * 60_000

    rep = verify_certificate(make_cert(entries), entries)
    assert "move BACKWARDS" in rep.render()
    # It is evidence about the ledger, not a false claim by the certificate, so the verdict for
    # the document itself is unchanged.
    assert rep.ok


def test_an_ordinary_day_has_no_backwards_timestamps():
    entries = led(ARMED_OPENING + [("DAY_CLOSED", "17:00:00", {})])
    assert find_backwards_timestamps(entries, GUARDIAN_CORE_V1, 1, len(entries)) == []


def test_backwards_detection_works_on_the_kit_dialect_too():
    """It needs no event the vocabulary lacks, so it applies everywhere."""
    entries = kledger(QUIET_DAY)
    entries[3]["ts_utc"] = "2026-08-21T11:00:00.000Z"     # earlier than its predecessor
    found = find_backwards_timestamps(entries, DEADMAN_KIT_V1, 1, len(entries))
    assert found and found[0]["toSeq"] == 4


# ---------------------------------------------------------------- the other dialect

def test_the_kit_dialect_omits_the_quantities_rather_than_zeroing_them():
    """Rule 1 reaching a derived block. A zero would claim "no restarts happened"; the truth is
    "this record cannot say", and those are different statements."""
    entries = kledger(QUIET_DAY)
    c = recompute_continuity(entries, DEADMAN_KIT_V1, 1, len(entries))

    assert c["supported"] is False
    assert "no process-lifecycle events" in c["reason"]
    for absent in ("continuityCoverage", "processRestarts", "unmonitoredMs", "longestGapMs",
                   "sealExpiryBasis"):
        assert absent not in c, f"{absent} must be omitted for a dialect that cannot supply it"


def test_the_report_says_the_dialect_cannot_supply_them_rather_than_staying_quiet():
    entries = kledger(QUIET_DAY)
    rep = verify_certificate(make_cert(entries, DEADMAN_KIT_V1), entries)
    text = rep.render()
    assert "SEAL CONTINUITY" in text
    assert "not available" in text and "no process-lifecycle events" in text


# ---------------------------------------------------------------- the accusation rules

def test_no_wording_in_the_block_accuses_anyone():
    entries = led(ARMED_OPENING + [
        ("GUARDIAN_STARTED", "17:39:00", {}),
        ("SEAL_EXPIRED", "17:39:01", {"basis": "wallclock"}),
        ("DAY_CLOSED", "17:39:02", {"dayKey": "2026-08-19"}),
    ])
    block = verify_certificate(make_cert(entries), entries).render()
    block = block.split("SEAL CONTINUITY")[1]

    for word in ("tamper", "cheat", "fraud", "suspicious", "manipulat", "dishonest",
                 "violation", "abuse"):
        assert word not in block.lower(), f"the continuity block accuses: {word!r}"


def test_process_restarts_never_appears_without_its_context():
    """A high restart count is normal for anyone who reboots their machine. On its own it invites
    the wrong conclusion, so it is only ever printed alongside the gap figure and the fixed text."""
    entries = led(ARMED_OPENING + [
        ("GUARDIAN_STOPPED", "14:00:00", {}), ("GUARDIAN_STARTED", "14:00:10", {}),
        ("DAY_CLOSED", "17:00:00", {"dayKey": "2026-08-19"}),
    ])
    block = verify_certificate(make_cert(entries), entries).render().split("SEAL CONTINUITY")[1]

    assert "process starts" in block
    assert "time with no guardian running" in block
    assert "Restarts happen for Windows updates" in block
