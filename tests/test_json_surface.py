"""The `--json` report must not state a result for a check that did not run.

MEASURED FIRST, 2026-09-03. On four early-return paths - no `ledgerDialect`, an unknown dialect,
a dialect that does not match the ledger, no `claims.ledgerRange` - the verifier reaches a verdict
without ever looking at the chain and without computing `certHash`. The JSON published
`chainOk: false`, `certHashOk: false` and `signature: "ABSENT"` anyway.

(All four returned exit 2 when this was written. Two of them return 1 since later the same day -
a certificate missing a field CERT_SPEC §4 requires is a defect of the DOCUMENT, not an input the
verifier failed to read. EXPECTED_EXIT below records which is which. The defect this file is about
is unchanged by that: neither code entitles a report to state a result for a check that did not
run.)

WHY THIS IS WORSE THAN THE SAME DEFECT IN THE TEXT REPORT, and why it is its own file: the text
render returns before printing figures, so a person never sees them. `--json` exists to be parsed.
There is no reader to hesitate, no sentence to qualify it, and `false` is the ADVERSE value - the
tool accuses the holder of a broken chain it never opened.

The sharpest of the four is `signature`. `chainOk: false` is a check that did not run reporting the
adverse result; `"ABSENT"` is a POSITIVE STATEMENT ABOUT THE DOCUMENT - "this certificate carries
no signature" - which is checkable from the document alone and is FALSE when the certificate is
signed. That one is not an unrun check leaking a default: it is a wrong fact.

THE RULE APPLIED IS THE VERIFIER'S OWN, CERT_SPEC section 4.1: a value that could not be determined
is OMITTED or null, never filler. Omission was chosen over null, and the reason is the consumer:
`null` is falsy in every language someone will parse this with, so `if not out["certHashOk"]` keeps
exactly the false accusation being removed - null fixes the document and not the reading. A missing
key raises instead. `result` and `couldNotEvaluate` are always present and carry the whole story.

Everything a consumer needs stays unconditional: `result`, `declaredLevel` (read from the document,
so it is always determinable), `reachedLevel` (null is the MEASURED answer - no layer was reached),
`contradictions`, `couldNotVerify`, `couldNotEvaluate`.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_c_certificate import QUIET_DAY, gledger, make_cert   # noqa: E402

ROOT = Path(__file__).resolve().parents[1]

#: A signature block that is syntactically a signature and cryptographically nothing. It exists to
#: make the certificate CARRY one, which is the only property the `signature: "ABSENT"` claim is
#: about. No key is ever supplied, so nothing here is verified or claimed to be.
FAKE_SIG = {"alg": "ed25519", "value": "aa" * 32, "keyId": "irrelevant-to-this-test"}


def _run_json(tmp_path, cert, entries):
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text("\n".join(json.dumps(e) for e in entries), encoding="utf-8")
    doc = tmp_path / "cert.json"
    doc.write_text(json.dumps(cert), encoding="utf-8")

    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    r = subprocess.run([sys.executable, "-m", "deadman.verify_certificate",
                        str(doc), str(ledger), "--json"],
                       capture_output=True, text=True, cwd=str(ROOT), env=env)
    return r.returncode, json.loads(r.stdout)


#: What each path is worth as a verdict, recorded here rather than assumed. Two of the four are
#: defects OF THE CERTIFICATE - a field CERT_SPEC §4 requires is absent, and no better copy of the
#: document exists - and two are conditions a fully conforming certificate can produce: the wrong
#: ledger file, and a producer newer than this verifier. tests/test_exit_code_semantics.py is where
#: that sorting is argued; this table is here so a reader of THIS file is not left guessing which
#: case is which.
EXPECTED_EXIT = {
    "no dialect declared": 1,
    "unknown dialect": 2,
    "crossed dialect": 2,
    "no ledgerRange": 1,
}


def _cases():
    """The four paths that reach a verdict without reading the ledger, each named by what it is.

    EACH MUTATED CERTIFICATE IS RESEALED, and the first version of this file did not do it. Editing
    a document after its `certHash` was taken makes the hash genuinely wrong, so every case was
    ALSO a real forgery - and once the verifier started computing certHash on these paths (which is
    the whole point of the fix), it correctly accused all four. The controls went red and the
    finding looked like a regression. It was the fixture: a case built to isolate ONE defect must
    be innocent of every other, or a fix that starts working reads as a fix that broke something.
    """
    from deadman.verify_certificate import _cert_preimage, _sha256_hex

    entries = gledger(QUIET_DAY)

    def cert(mutate):
        c = json.loads(json.dumps(make_cert(entries)))
        mutate(c)
        c["certHash"] = _sha256_hex(_cert_preimage(c))   # honest document, wrong dialect/range
        return c

    return entries, {
        "no dialect declared": cert(lambda c: c.pop("ledgerDialect")),
        "unknown dialect": cert(lambda c: c.__setitem__("ledgerDialect", "martian-v9")),
        "crossed dialect": cert(lambda c: c.__setitem__("ledgerDialect", "deadman-kit-v1")),
        "no ledgerRange": cert(lambda c: c["claims"].pop("ledgerRange")),
    }


# ---------------------------------------------------------------- the defect

def test_no_unrun_check_publishes_a_result(tmp_path):
    """The whole point. A key whose check did not run must be ABSENT from the JSON."""
    entries, cases = _cases()
    offenders = []
    for name, cert in cases.items():
        code, out = _run_json(tmp_path, cert, entries)
        assert code == EXPECTED_EXIT[name], f"{name}: expected {EXPECTED_EXIT[name]}, got {code}"
        assert code != 0, f"{name} was not refused"
        for key in ("chainOk", "signature"):
            if key in out:
                offenders.append(f"{name}: {key}={out[key]!r} for a check that never ran")
    assert not offenders, "\n  " + "\n  ".join(offenders)


def test_certhash_is_computed_on_every_path_because_it_needs_no_ledger(tmp_path):
    """CERT_SPEC section A.2 - MUST recompute certHash on any path that reaches a verdict.

    Not a preference: `certHash` is the sha256 of the DOCUMENT. None of these four paths failed for
    want of the document, so none of them has an excuse. A falsified certHash must be caught even
    when the ledger is unreadable - that is the case where a forger has the most to gain by handing
    over a file the verifier will refuse to open.

    THE FIRST VERSION OF THIS TEST PASSED WHILE THE DEFECT WAS INTACT, and the reason is worth
    keeping: it asserted `certHashOk is False`, and `False` IS THE UNINITIALISED DEFAULT. The value
    a skipped check leaves behind was indistinguishable from the value a caught forgery produces.
    What is asserted now is that the mismatch was REPORTED - a finding only the real computation
    can produce.
    """
    entries, cases = _cases()
    silent = []
    for name, cert in cases.items():
        cert["certHash"] = "0" * 64                       # flagrant, checkable without the ledger
        _, out = _run_json(tmp_path, cert, entries)
        found = [f for f in out["contradictions"] if f["code"] == "CERTHASH_MISMATCH"]
        if not found:
            silent.append(f"{name}: the document hashes to something else and nothing said so "
                          f"(certHashOk={out.get('certHashOk')!r})")
    assert not silent, "\n  " + "\n  ".join(silent)


def test_the_certhash_check_is_capable_of_staying_quiet(tmp_path):
    """CONTROL for the test above, which would pass just as well if every run reported a mismatch.
    An honest certificate on the same four paths must produce no CERTHASH finding at all."""
    entries, cases = _cases()
    for name, cert in cases.items():
        _, out = _run_json(tmp_path, cert, entries)
        assert not [f for f in out["contradictions"] if f["code"].startswith("CERTHASH")], \
            f"{name}: an honest document was accused"


def test_a_signed_certificate_is_never_reported_as_unsigned(tmp_path):
    """`"ABSENT"` says the document carries no signature. Here it carries one."""
    entries, cases = _cases()
    lies = []
    for name, cert in cases.items():
        cert["signature"] = FAKE_SIG
        _, out = _run_json(tmp_path, cert, entries)
        if out.get("signature") == "ABSENT":
            lies.append(f"{name}: signature=ABSENT on a certificate that carries one")
    assert not lies, "\n  " + "\n  ".join(lies)


def test_the_declared_level_is_read_from_the_document_on_every_path(tmp_path):
    """`declaredLevel` is a field of the certificate, not a finding. Reporting null for it says
    the document declared nothing, and the document declared L1."""
    entries, cases = _cases()
    dropped = []
    for name, cert in cases.items():
        assert cert.get("trustLevel") == "L1", "fixture must declare a level for this to mean anything"
        _, out = _run_json(tmp_path, cert, entries)
        if out.get("declaredLevel") != "L1":
            dropped.append(f"{name}: declaredLevel={out.get('declaredLevel')!r}, document says 'L1'")
    assert not dropped, "\n  " + "\n  ".join(dropped)


def test_a_finding_that_needs_no_ledger_is_shown_even_when_the_ledger_was_not_read(tmp_path):
    """Computing certHash on every path is worth nothing if the text render swallows it.

    The unevaluable branch prints the reasons it could not look and returns. Once a check that
    needs only the document can produce a finding on that branch, the branch has to show it - and
    ITS CLOSING SENTENCE HAS TO MOVE TOO. `Nothing was proved and nothing was disproved` is exactly
    the kind of claim this repository keeps finding: a sentence the artefact says about itself,
    that no test ever checked, and that becomes false the moment something WAS disproved.

    The exit code is deliberately NOT asserted here. Whether a document-only contradiction should
    outrank `could not look` is the exit-code question raised separately and not yet decided; this
    test fixes only that the finding must be VISIBLE, which is true under either answer.
    """
    entries, cases = _cases()
    # The CROSSED dialect, not the missing one: since 2026-09-03 a missing `ledgerDialect` is
    # itself a contradiction, so it would no longer exercise the mixed case this test is about -
    # a finding measured from the document BESIDE a ledger that could not be judged.
    cert = cases["crossed dialect"]
    cert["certHash"] = "0" * 64

    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text("\n".join(json.dumps(e) for e in entries), encoding="utf-8")
    doc = tmp_path / "cert.json"
    doc.write_text(json.dumps(cert), encoding="utf-8")
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    r = subprocess.run([sys.executable, "-m", "deadman.verify_certificate", str(doc), str(ledger)],
                       capture_output=True, text=True, cwd=str(ROOT), env=env)

    assert "COULD NOT EVALUATE" in r.stdout
    assert "certHash" in r.stdout, "the mismatch was computed and never shown:\n" + r.stdout
    assert "CONTRADICTED" in r.stdout
    assert "Nothing was proved and nothing was disproved" not in r.stdout, \
        "something WAS disproved; that sentence is now false:\n" + r.stdout


def test_the_unevaluable_sentence_survives_when_nothing_was_disproved(tmp_path):
    """CONTROL for the test above. The honest unevaluable case must keep saying exactly what it
    said - the sentence is only wrong when there is a finding beside it."""
    entries, cases = _cases()
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text("\n".join(json.dumps(e) for e in entries), encoding="utf-8")
    doc = tmp_path / "cert.json"
    doc.write_text(json.dumps(cases["crossed dialect"]), encoding="utf-8")
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    r = subprocess.run([sys.executable, "-m", "deadman.verify_certificate", str(doc), str(ledger)],
                       capture_output=True, text=True, cwd=str(ROOT), env=env)

    assert r.returncode == 2
    assert "Nothing was proved and nothing was disproved" in r.stdout


# ---------------------------------------------------------------- controls

def test_a_complete_run_still_publishes_every_key(tmp_path):
    """CONTROL. Omitting keys on the unevaluable paths must not thin out the ordinary report -
    a consumer of a successful verification loses nothing."""
    entries = gledger(QUIET_DAY)
    code, out = _run_json(tmp_path, make_cert(entries), entries)
    assert code == 0, out
    for key in ("result", "declaredLevel", "reachedLevel", "chainOk", "certHashOk",
                "anchorsChecked", "signature", "effectiveToSeq",
                "contradictions", "couldNotVerify", "couldNotEvaluate"):
        assert key in out, f"{key} disappeared from a successful report"
    assert out["chainOk"] is True and out["certHashOk"] is True


def test_the_keys_a_consumer_must_be_able_to_rely_on_are_always_there(tmp_path):
    """CONTROL. Omission has a cost: the key set now varies. These five never do, because a
    consumer that cannot ask `did this pass?` on every path has no contract at all."""
    entries, cases = _cases()
    for name, cert in cases.items():
        _, out = _run_json(tmp_path, cert, entries)
        for key in ("result", "declaredLevel", "contradictions",
                    "couldNotVerify", "couldNotEvaluate"):
            assert key in out, f"{name}: {key} must survive on every path"
        assert out["result"] == ("CONTRADICTED" if EXPECTED_EXIT[name] == 1 else "UNEVALUABLE")
        # Whichever channel it took, the report must NAME what it found. A refusal that lists
        # nothing is the same as no refusal to whoever has to act on it.
        assert out["contradictions"] or out["couldNotEvaluate"], f"{name}: refused, said nothing"


def test_a_clean_series_does_not_print_a_broken_chain_under_a_green_verdict():
    """THE SAME DEFECT IN THE TEXT SURFACE, found while fixing the JSON one and fixed with it.

    `verify_series` checks the links BETWEEN certificates; it never opens a ledger, so there is no
    chain and no certHash to compute. The render printed the defaults anyway, so a passing series
    said `chain BROKEN at seq None` and `certHash DOES NOT MATCH` four lines above
    `RESULT: VERIFIED at series (exit 0)`.

    Left alone this would be the worse half: a person who reads `BROKEN` under a green verdict
    distrusts either the tool or the certificate, and neither is warranted. Fixing only `--json`
    would have removed the smell from the surface nobody reads by eye and left it in the one
    people do.
    """
    from deadman.verify_certificate import verify_series
    from test_c_certificate import _series_day

    d1 = _series_day("2026-08-17", None)
    d2 = _series_day("2026-08-18", d1["certHash"])
    rep = verify_series([d1, d2])
    assert rep.exit_code == 0, "fixture must be a CLEAN series for this to mean anything"

    out = rep.render()
    assert "BROKEN" not in out, out
    assert "DOES NOT MATCH" not in out, out
    assert "VERIFIED at series" in out


def test_a_real_broken_chain_still_reports_false(tmp_path):
    """CONTROL THAT MUST NOT MOVE. Teaching the report to omit what it did not check must not
    teach it to omit what it checked and found broken."""
    entries = gledger(QUIET_DAY)
    tampered = [dict(e) for e in entries]
    tampered[3] = dict(tampered[3])
    tampered[3]["payload"] = {**(tampered[3].get("payload") or {}), "planted": True}

    code, out = _run_json(tmp_path, make_cert(entries), tampered)
    assert code == 1, out
    assert out["chainOk"] is False, "a chain that WAS checked and IS broken must say so"
    assert any(f["code"] == "CHAIN_BROKEN" for f in out["contradictions"])
