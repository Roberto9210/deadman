"""Which refusals are exit 1 and which are exit 2, and the one rule that decides.

CERT_SPEC §A.5 keeps *I caught you lying* (1) apart from *I could not look* (2), and gives the
reason in its own words: a tool that collapses them "can be made to accuse an honest holder who
supplied the wrong file". So the 2 exists to protect against a fault in SOMETHING THAT IS NOT THE
CERTIFICATE, and the question that sorts every case is:

    CAN A FULLY CONFORMING CERTIFICATE PRODUCE THIS CONDITION?

    yes -> 2. The wrong ledger file, or a producer newer than this verifier.
    no  -> 1. A field the certificate itself must carry and does not.

Measured 2026-09-03, before moving anything: nothing outside this repository's own tests reads
these codes. `deadman-guardian` (read-only, commit 41a545b) names the verifier in eight places -
three documentation lines, one comment, three strings printed for a person to run, and one test
asserting the string appears in the HTML - and launches no process anywhere: no `Process.Start`,
no `ExitCode`, no workflow. The guardian tells a human to run it; nothing reads what it returns.

TWO CASES MOVE FROM 2 TO 1, and the argument that settles it is operational rather than
philosophical: §A.5 documents 2 as *ask for a better copy*. A certificate with no `ledgerDialect`
DOES NOT IMPROVE by asking for another copy - the document is what it is. Telling a script to try
again for a permanent condition is an infinite loop with a polite name.

AND THE MIXED CASE - an unreadable ledger beside a document that fails a check needing no ledger -
is now 1. This is not symmetry for its own sake. `certHash` was moved to the top of verification
precisely because a forger who edited the document has every incentive to hand over a ledger the
verifier will refuse to open. If the exit code still said 2 there, THAT STRATEGY WOULD KEEP
WORKING at the level of the exit code even though it stopped working in the JSON - the code would
undo the fix. Measuring something and finding it false is not undone by failing to measure
something else.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_c_certificate import BREACH_DAY, QUIET_DAY, gledger, make_cert   # noqa: E402

ROOT = Path(__file__).resolve().parents[1]

EXIT_OK, EXIT_CONTRADICTED, EXIT_UNEVALUABLE = 0, 1, 2


def _reseal(cert):
    from deadman.verify_certificate import _cert_preimage, _sha256_hex
    cert["certHash"] = _sha256_hex(_cert_preimage(cert))
    return cert


def _cli(tmp_path, cert, entries, *extra):
    """Through the CLI, because the exit code is the thing under test and only the CLI has one."""
    (tmp_path / "l.jsonl").write_text("\n".join(json.dumps(e) for e in entries), encoding="utf-8")
    (tmp_path / "c.json").write_text(json.dumps(cert), encoding="utf-8")
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    r = subprocess.run([sys.executable, "-m", "deadman.verify_certificate",
                        str(tmp_path / "c.json"), str(tmp_path / "l.jsonl"), *extra],
                       capture_output=True, text=True, cwd=str(ROOT), env=env)
    return r


def _mutate(entries, fn):
    cert = json.loads(json.dumps(make_cert(entries)))
    fn(cert)
    return _reseal(cert)


# ---------------------------------------------------------------- 1: the two that move

def test_a_certificate_missing_a_field_it_must_carry_is_refused_not_excused(tmp_path):
    """§4 requires `ledgerDialect` and `claims.ledgerRange`. A document that omits one is not a
    document the verifier failed to read - it is a document that does not conform, and no better
    copy of it exists."""
    entries = gledger(QUIET_DAY)
    for name, fn in (("no ledgerDialect", lambda c: c.pop("ledgerDialect")),
                     ("no ledgerRange", lambda c: c["claims"].pop("ledgerRange"))):
        r = _cli(tmp_path, _mutate(entries, fn), entries)
        assert r.returncode == EXIT_CONTRADICTED, f"{name}: got {r.returncode}\n{r.stdout}"


def test_the_refusal_still_says_which_field_and_why(tmp_path):
    """Moving the severity must not cost the explanation: the reason the dialect is not guessed
    is the whole point of requiring it."""
    entries = gledger(QUIET_DAY)
    r = _cli(tmp_path, _mutate(entries, lambda c: c.pop("ledgerDialect")), entries)
    assert "ledgerDialect" in r.stdout
    assert "guessing" in r.stdout, r.stdout


# ---------------------------------------------------------------- 1: the ones that must NOT move

def test_the_wrong_ledger_is_still_only_unevaluable(tmp_path):
    """CONTROL THAT MUST NOT MOVE. An honest certificate handed the wrong file is
    indistinguishable from one lying about its dialect, so the tool must not call anyone a liar.
    This is the case §A.5 was written for and the reason the two codes exist."""
    entries = gledger(QUIET_DAY)
    r = _cli(tmp_path, _mutate(entries, lambda c: c.__setitem__("ledgerDialect", "deadman-kit-v1")),
             entries)
    assert r.returncode == EXIT_UNEVALUABLE, r.stdout


def test_a_newer_producer_is_still_only_unevaluable(tmp_path):
    """CONTROL THAT MUST NOT MOVE. An unknown dialect means a producer newer than this verifier -
    the same argument CERT_SPEC §5 already makes for unknown event kinds: refusing would let one
    future name invalidate every certificate already issued."""
    entries = gledger(QUIET_DAY)
    r = _cli(tmp_path, _mutate(entries, lambda c: c.__setitem__("ledgerDialect", "guardian-core-v9")),
             entries)
    assert r.returncode == EXIT_UNEVALUABLE, r.stdout


def test_a_short_ledger_is_still_only_unevaluable(tmp_path):
    """CONTROL THAT MUST NOT MOVE, and the most important one here. A file cut short by a power
    cut must never be charged to the person holding it - that was the whole of DEF-6, and the new
    precedence must not quietly undo it."""
    entries = gledger(QUIET_DAY)
    r = _cli(tmp_path, make_cert(entries), entries[:-2])
    assert r.returncode == EXIT_UNEVALUABLE, r.stdout


# ---------------------------------------------------------------- 3: the mixed case

def test_a_forged_document_beside_an_unreadable_ledger_is_a_contradiction(tmp_path):
    """The adversarial case, stated as an attack: alter the document, then hand over a ledger the
    verifier will refuse to open, and see whether the refusal launders the alteration."""
    entries = gledger(QUIET_DAY)
    cert = _mutate(entries, lambda c: c.__setitem__("ledgerDialect", "deadman-kit-v1"))
    cert["certHash"] = "0" * 64                      # the document no longer hashes to its claim

    r = _cli(tmp_path, cert, entries, "--json")
    out = json.loads(r.stdout)
    assert r.returncode == EXIT_CONTRADICTED, r.stdout
    assert out["result"] == "CONTRADICTED"
    assert any(f["code"].startswith("CERTHASH") for f in out["contradictions"])
    assert any(f["code"] == "DIALECT_MISMATCH" for f in out["couldNotEvaluate"]), \
        "the part that could not be judged must still be reported as such"


def test_the_mixed_verdict_explains_why_the_unreadable_ledger_is_no_excuse(tmp_path):
    """A reader who sees CONTRADICTED beside COULD NOT EVALUATE deserves the reason in the output,
    not in a specification they have not opened."""
    entries = gledger(QUIET_DAY)
    cert = _mutate(entries, lambda c: c.__setitem__("ledgerDialect", "deadman-kit-v1"))
    cert["certHash"] = "0" * 64
    r = _cli(tmp_path, cert, entries)
    assert "CONTRADICTED" in r.stdout
    assert "COULD NOT EVALUATE" in r.stdout
    assert "Nothing was proved and nothing was disproved" not in r.stdout, r.stdout


def test_an_honest_document_beside_an_unreadable_ledger_is_still_unevaluable(tmp_path):
    """CONTROL for the two above. The new precedence must fire ONLY when something was actually
    measured and found false - otherwise it is just the old collapse in the other direction."""
    entries = gledger(QUIET_DAY)
    r = _cli(tmp_path, _mutate(entries, lambda c: c.__setitem__("ledgerDialect", "deadman-kit-v1")),
             entries)
    assert r.returncode == EXIT_UNEVALUABLE
    assert "Nothing was proved and nothing was disproved" in r.stdout


# ---------------------------------------------------------------- 2: the certHash message

def test_an_absent_certhash_is_reported_as_absent_not_as_a_disagreement(tmp_path):
    """The condition is an OMISSION. The old wording - `certHash says None... but the document
    hashes to 1aacf1d2...` - reads as two hashes that disagree, which invites the holder to look
    for a hash that was never there. Lowering a claim needs no evidence."""
    entries = gledger(QUIET_DAY)
    cert = json.loads(json.dumps(make_cert(entries)))
    cert.pop("certHash")

    r = _cli(tmp_path, cert, entries, "--json")
    out = json.loads(r.stdout)
    codes = {f["code"] for f in out["contradictions"]}
    assert "CERTHASH_MISSING" in codes, codes
    assert "CERTHASH_MISMATCH" not in codes, "an omission is not a mismatch"

    detail = " ".join(f["detail"] for f in out["contradictions"] if f["code"] == "CERTHASH_MISSING")
    assert "None" not in detail, f"the message still prints the absent value as if it were one: {detail}"


def test_a_real_mismatch_is_still_called_a_mismatch(tmp_path):
    """CONTROL. Renaming the absent case must not rename the present-and-wrong case."""
    entries = gledger(QUIET_DAY)
    cert = json.loads(json.dumps(make_cert(entries)))
    cert["certHash"] = "0" * 64

    out = json.loads(_cli(tmp_path, cert, entries, "--json").stdout)
    codes = {f["code"] for f in out["contradictions"]}
    assert "CERTHASH_MISMATCH" in codes and "CERTHASH_MISSING" not in codes, codes


# ---------------------------------------------------------------- the shape as a whole

def test_every_refusal_is_still_a_refusal(tmp_path):
    """The meta-guarantee, re-asserted over the new sorting: whichever channel a defect takes, it
    never becomes a pass. This is what stops the two rulings above from being a way to lose a
    case in the gap between them."""
    entries = gledger(BREACH_DAY)
    cases = {
        "claim": make_cert(entries, overrides={"claims.lockoutsTriggered": 0}),
        "trust": make_cert(entries, trust="L3"),
        "limitations": make_cert(entries, overrides={"limitations": []}),
        "certhash": {**make_cert(entries), "certHash": "0" * 64},
        "no dialect": _mutate(entries, lambda c: c.pop("ledgerDialect")),
        "no range": _mutate(entries, lambda c: c["claims"].pop("ledgerRange")),
        "crossed dialect": _mutate(entries, lambda c: c.__setitem__("ledgerDialect", "deadman-kit-v1")),
        "unknown dialect": _mutate(entries, lambda c: c.__setitem__("ledgerDialect", "x-v9")),
    }
    for name, cert in cases.items():
        r = _cli(tmp_path, cert, entries)
        assert r.returncode != EXIT_OK, f"{name} was not refused:\n{r.stdout}"


def test_the_honest_certificate_still_passes(tmp_path):
    """CONTROL. Two rulings that make more things exit 1 are worthless if they also make the
    honest case exit 1."""
    entries = gledger(QUIET_DAY)
    r = _cli(tmp_path, make_cert(entries), entries)
    assert r.returncode == EXIT_OK, r.stdout
