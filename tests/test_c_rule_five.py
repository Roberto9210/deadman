"""CERT_SPEC rule 5, checked by the receiver rather than only asserted in the specification.

> A field that looks like evidence and is not is worse than an absent field.

The rule's own question is *what does it distinguish?* - if two things that should differ give the
same value, the field does not measure what its name says. That cannot be answered mechanically in
general, but its sharpest special case can: **a field whose NAME promises a specific form,
carrying a value that cannot have that form.**

`"buildHash": "example"` is the case that produced the rule. A word is not a fingerprint. Until
now nothing told a recipient so: the rule lived in the spec and in a repository test over our own
shipped examples, and neither reaches the person holding the certificate - who is the only
audience that matters.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

from deadman.verify_certificate import (
    DECORATIVE_FILLER, EXIT_CONTRADICTED, EXIT_UNEVALUABLE, check_rule_five, verify_certificate,
)

from test_c_certificate import QUIET_DAY, codes, gledger, make_cert

ROOT = Path(__file__).resolve().parents[1]
EX = ROOT / "deadman" / "examples" / "certificate"


def find(cert):
    return {code for code, _ in check_rule_five(cert)}


# ---------------------------------------------------------------- the case that made the rule

def test_the_original_defect_is_caught_from_the_certificate_alone():
    """`buildHash: "example"` shipped in three published examples and nothing refused it."""
    cert = make_cert(gledger(QUIET_DAY))
    cert["issuer"]["buildHash"] = "example"
    assert "DECORATIVE_FIELD" in find(cert)


def test_a_hash_field_holding_a_word_belies_its_name():
    """Even a word that is not on the filler list: `buildHash: "latest"` is not a fingerprint."""
    cert = make_cert(gledger(QUIET_DAY))
    cert["issuer"]["buildHash"] = "latest"
    assert "FIELD_BELIES_ITS_NAME" in find(cert)


def test_a_hash_too_short_to_be_one_is_caught():
    cert = make_cert(gledger(QUIET_DAY))
    cert["commitment"]["sealHash"] = "abc123"
    assert "FIELD_BELIES_ITS_NAME" in find(cert)


# ---------------------------------------------------------------- the other promises

def test_a_timestamp_field_that_is_not_a_timestamp():
    cert = make_cert(gledger(QUIET_DAY))
    cert["commitment"]["armedAtUtc"] = "this morning"
    assert "FIELD_BELIES_ITS_NAME" in find(cert)


def test_money_must_be_a_two_decimal_string_not_a_number():
    """SPEC section 4: money is a string with exactly two decimals, so it compares exactly. A
    float here is a rounding bug waiting for a bad day."""
    cert = make_cert(gledger(QUIET_DAY))
    cert["commitment"]["personalDailyLossLimit"] = 600
    assert "FIELD_BELIES_ITS_NAME" in find(cert)

    cert["commitment"]["personalDailyLossLimit"] = "600"
    assert "FIELD_BELIES_ITS_NAME" in find(cert)


def test_a_version_that_identifies_no_build():
    cert = make_cert(gledger(QUIET_DAY))
    cert["issuer"]["version"] = "latest"
    assert "FIELD_BELIES_ITS_NAME" in find(cert)


# ---------------------------------------------------------------- what it must NOT flag

def test_free_text_fields_promise_nothing_and_are_left_alone():
    """The cost of a false accusation here is a certificate wrongly refused, so anything whose
    name promises no particular form is not examined at all."""
    cert = make_cert(gledger(QUIET_DAY))
    cert["subject"]["alias"] = "a trader who likes long names"
    cert["issuer"]["tool"] = "some-other-emitter"
    cert["session"]["timezone"] = "America/Chicago"
    assert not find(cert)


# ---------------------------------------------------------------- provenance decides where it applies

def test_a_persons_alias_is_never_filler():
    """`alias` is free text a PERSON chose. If somebody's alias is "unknown", that is their name.

    A producer writing "unknown" is papering over a hole; a person writing it is answering the
    question. Same string, different things, and what separates them is where it came from. The
    risk of exempting it is nil: this check only ever refuses, so it cannot be tricked into
    approving anything."""
    for value in ("unknown", "example", "none", "tbd", ""):
        cert = make_cert(gledger(QUIET_DAY))
        cert["subject"]["alias"] = value
        assert not find(cert), f"alias={value!r} was refused; a person's word is their word"


def test_the_producers_own_fields_are_still_caught():
    """CONTROL for the test above. Without it, exempting alias could have exempted everything."""
    cases = [(("issuer", "buildHash"), "example"),
             (("issuer", "buildHash"), "test"),
             (("issuer", "version"), "1.0.0.0"),
             (("session", "timezone"), ""),
             (("commitment", "sealHash"), "unknown")]
    for (block, field), value in cases:
        cert = make_cert(gledger(QUIET_DAY))
        cert[block][field] = value
        assert find(cert), f"{block}.{field}={value!r} slipped through"


# ---------------------------------------------------------------- the sweep, as a PROPERTY

def _adversarial_event_names():
    """Names nobody has chosen, crossed against everything these checks react to.

    A sweep over the vocabulary that EXISTS asserts a RESULT, not a property: it passes because
    nobody has picked a colliding name yet. `triggerEvent` is a passthrough on the emitting side -
    it copies whatever the ledger row says, with no enum - so the set of possible values is not
    the set of current ones. Production already shows 24 distinct issuer build hashes; event names
    from older or future builds arrive the same way."""
    suffixes = ["HASH", "LOSS", "LIMIT", "UTC", "AT_UTC", "VERSION", "MISMATCH", "BREACHED"]
    prefixes = ["", "CONFIG_", "SEAL_", "DAILY_", "ACCOUNT_", "X_"]
    names = {p + s for p in prefixes for s in suffixes}
    for f in DECORATIVE_FILLER:
        if f:
            names |= {f, f.upper(), f"ACCOUNT_{f.upper()}"}
    names |= {p + f for p in prefixes for f in ("UNKNOWN", "NONE", "NULL", "TBD", "TODO")}
    return sorted(names)


def test_no_event_name_can_make_a_certificate_fail_rule_five():
    """§5.7: a lexical containment must match exactly what it forbids, and is TESTED AGAINST THE
    LEGITIMATE VALUES IT COULD CATCH.

    Both places an event name reaches the document: as a KEY of `reasons` (where the promise check
    used to read it as a schema field name and accuse its own integer counter) and as a VALUE of
    `triggerEvent` (where the filler list used to read it as the producer's own word). The two
    holes are separate and needed separate fixes; this asserts both are shut."""
    names = _adversarial_event_names()
    assert len(names) > 100, "the generator stopped generating"

    for ev in names:
        cert = make_cert(gledger(QUIET_DAY))
        cert["claims"]["failClosedEpisodes"] = [
            {"fromSeq": 1, "toSeq": 2, "open": False, "reasons": {ev: 1},
             "triggerSeq": 1, "triggerEvent": ev}]
        assert not find(cert), f"the event name {ev!r} made an honest certificate fail rule 5"


def test_the_sweep_is_capable_of_failing():
    """CONTROL: the same generator, aimed at a field the PRODUCER owns, must light up.

    Without this, the test above would pass just as well if `find()` had stopped working."""
    caught = 0
    for ev in _adversarial_event_names():
        cert = make_cert(gledger(QUIET_DAY))
        cert["issuer"]["buildHash"] = ev
        if find(cert):
            caught += 1
    assert caught > 100, f"only {caught} names were caught in a producer field; the check is inert"


def test_every_shipped_example_satisfies_the_rule_it_publishes():
    """The examples are what a reader learns the shape from, so they may not violate the rule the
    same package enforces."""
    for path in sorted(EX.glob("certificate*.json")):
        cert = json.loads(path.read_text(encoding="utf-8"))
        assert not check_rule_five(cert), (
            f"{path.name} violates rule 5: {check_rule_five(cert)}")


def test_an_omitted_field_is_never_a_violation():
    """Rule 1 and rule 5 agree: absent is fine, decorative is not."""
    cert = make_cert(gledger(QUIET_DAY))
    cert["issuer"].pop("buildHash", None)
    cert["issuer"].pop("version", None)
    assert not find(cert)


def test_the_filler_list_covers_what_a_generator_leaves_behind():
    for token in ("example", "test", "TODO", "changeme", "placeholder", "", "1.0.0.0"):
        assert token.strip().lower() in DECORATIVE_FILLER


# ---------------------------------------------------------------- end to end

def test_a_decorative_field_contradicts_the_certificate():
    entries = gledger(QUIET_DAY)
    cert = make_cert(entries)
    cert["issuer"]["buildHash"] = "example"
    cert["certHash"] = hashlib.sha256(
        __import__("deadman.verify_certificate", fromlist=["_cert_preimage"])
        ._cert_preimage(cert)).hexdigest()

    rep = verify_certificate(cert, entries)
    assert rep.exit_code == EXIT_CONTRADICTED
    assert "DECORATIVE_FIELD" in codes(rep)


def test_a_recipient_holding_only_the_certificate_still_learns_this(tmp_path):
    """The case where a receiver has least information and most need: someone handed them one
    file. The claims cannot be recomputed without the ledger, but a field that belies its own name
    is visible in the document alone, and saying nothing would waste the one check that still
    works."""
    cert = make_cert(gledger(QUIET_DAY))
    cert["issuer"]["buildHash"] = "example"
    path = tmp_path / "certificate.json"
    path.write_text(json.dumps(cert), encoding="utf-8")

    r = subprocess.run([sys.executable, "-m", "deadman.verify_certificate", str(path)],
                       capture_output=True, text=True, cwd=str(ROOT))

    assert r.returncode == EXIT_UNEVALUABLE          # the claims still could not be checked
    assert "buildHash" in r.stderr
    assert "rule 5" in r.stderr.lower()
    assert "ask whoever gave you the certificate" in r.stderr
