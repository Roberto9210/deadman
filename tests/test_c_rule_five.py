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
