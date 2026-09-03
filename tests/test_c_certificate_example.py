"""The worked example in deadman/examples/certificate/ is checked in, and documentation that drifts
from the code is worse than none - a reader who runs the command and gets different output
learns to distrust the whole repository. So the shipped files are verified on every run, and
the exact strings quoted in docs/verify-certificate.md are asserted here.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from deadman.verify_certificate import (
    EXIT_CONTRADICTED, EXIT_OK, EXIT_UNEVALUABLE, verify_certificate,
)

ROOT = Path(__file__).resolve().parents[1]
EX = ROOT / "deadman" / "examples" / "certificate"


def _subprocess_env():
    """`python path/to/script.py` puts the SCRIPT's directory on sys.path, not the cwd, so a
    subprocess cannot import `deadman` from a plain checkout. Locally an editable install hides
    that; CI, which installs nothing but pytest, does not. Set the path explicitly."""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    return env


def _entries():
    return [json.loads(l) for l in (EX / "ledger.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]


def _cert(name):
    return json.loads((EX / name).read_text(encoding="utf-8"))


def test_the_shipped_example_files_exist():
    for name in ("ledger.jsonl", "certificate.json", "certificate-tampered.json",
                 "certificate-truncated.json", "make_example.py"):
        assert (EX / name).exists(), f"deadman/examples/certificate/{name} is missing"


def test_the_honest_example_verifies():
    rep = verify_certificate(_cert("certificate.json"), _entries())
    assert rep.exit_code == EXIT_OK, [str(f) for f in rep.contradictions]
    assert rep.reached_level == "L1"
    assert rep.chain_ok and rep.cert_hash_ok


def test_the_honest_example_is_not_a_boring_day():
    """If the example had nothing in it, it would prove nothing about the tool."""
    rep = verify_certificate(_cert("certificate.json"), _entries())
    assert rep.recomputed["changeAttemptsWhileSealed"] == 2
    assert len(rep.recomputed["failClosedEpisodes"]) == 1
    assert rep.recomputed["failClosedEpisodes"][0]["reasons"] == {"ACCOUNT_UNKNOWN": 3}
    assert rep.recomputed["limitRespected"] is True


def test_the_tampered_example_is_contradicted_for_the_documented_reason():
    rep = verify_certificate(_cert("certificate-tampered.json"), _entries())
    assert rep.exit_code == EXIT_CONTRADICTED
    detail = " ".join(f.detail for f in rep.contradictions)
    assert "changeAttemptsWhileSealed" in detail
    assert "certificate says 0, the events say 2" in detail

    # The tampered document is internally consistent: its own certHash is correct. It falls
    # only because the verifier counts the events instead of reading the number.
    assert rep.cert_hash_ok, "the point of this example is that hashing alone would not catch it"


def test_the_truncated_example_is_caught_and_names_what_it_excluded():
    """The attack documented under "The attack that got past this verifier". Every claim in it
    is TRUE over the window it declares; it falls on the range, not on any number."""
    rep = verify_certificate(_cert("certificate-truncated.json"), _entries())
    assert rep.exit_code == EXIT_CONTRADICTED
    assert "RANGE_TRUNCATED" in {f.code for f in rep.contradictions}

    detail = " ".join(f.detail for f in rep.contradictions)
    assert "CONFIG_CHANGE_REJECTED" in detail and "FAIL_CLOSED_ENTERED" in detail
    assert "DAY_CLOSED is at seq 16" in detail

    # Everything else about the document is impeccable, which is the whole point.
    assert rep.chain_ok and rep.cert_hash_ok
    assert rep.recomputed["changeAttemptsWhileSealed"] == 0      # true, over seq 1..6
    assert rep.recomputed["failClosedEpisodes"] == []            # true, over seq 1..6
    assert rep.recomputed["limitRespected"] is True              # true, over seq 1..6


#: What every example must report, in full. The limits list is identical across all four
#: because they share one anchorless ledger; that it is spelled out per example rather than
#: shared is deliberate - if one of them ever stops being anchorless, this notices.
EXPECTED_VERDICTS = {
    "certificate.json": {
        "exit": EXIT_OK,
        "contradictions": set(),
        "could_not_verify": {"NO_EXTERNAL_ANCHOR", "OTHER_VENUES", "PRE_START_BYPASS",
                             "TRADES_OBSERVED"},
        "reached": "L1",
    },
    "certificate-tampered.json": {
        "exit": EXIT_CONTRADICTED,
        "contradictions": {"CLAIM_MISMATCH"},
        "could_not_verify": {"NO_EXTERNAL_ANCHOR", "OTHER_VENUES", "PRE_START_BYPASS",
                             "TRADES_OBSERVED"},
        "reached": "L1",
    },
    "certificate-truncated.json": {
        "exit": EXIT_CONTRADICTED,
        "contradictions": {"RANGE_TRUNCATED"},
        "could_not_verify": {"NO_EXTERNAL_ANCHOR", "OTHER_VENUES", "PRE_START_BYPASS",
                             "TRADES_OBSERVED"},
        "reached": "L1",
    },
    "certificate-unknown-issuer.json": {
        "exit": EXIT_OK,
        "contradictions": set(),
        "could_not_verify": {"NO_EXTERNAL_ANCHOR", "OTHER_VENUES", "PRE_START_BYPASS",
                             "TRADES_OBSERVED"},
        "reached": "L1",
    },
}


@pytest.mark.parametrize("name", sorted(EXPECTED_VERDICTS))
def test_each_example_produces_exactly_the_verdict_it_is_published_to_produce(name):
    """Exit code AND the exact reason sets.

    An exit-code-only assertion passes an example that broke for the wrong reason - the
    truncated one exits 1 whether it is caught for its truncated range or for a mangled
    certHash, and only the second means the file stopped teaching anything. Exact sets make a
    substituted reason as loud as a missing one.
    """
    expected = EXPECTED_VERDICTS[name]
    rep = verify_certificate(_cert(name), _entries())

    assert rep.exit_code == expected["exit"], [str(f) for f in rep.contradictions]
    assert {f.code for f in rep.contradictions} == expected["contradictions"], (
        f"{name} is contradicted for different reasons than it is published to demonstrate: "
        f"{sorted(f.code for f in rep.contradictions)}")
    assert {f.code for f in rep.unverified} == expected["could_not_verify"], (
        f"{name} reports different limits than documented: "
        f"{sorted(f.code for f in rep.unverified)}")
    assert rep.reached_level == expected["reached"]


def test_every_shipped_example_has_a_declared_verdict():
    """A fifth example must declare what it demonstrates, or this fails rather than letting an
    undescribed file ship."""
    shipped = {p.name for p in EX.glob("certificate*.json")}
    undeclared = sorted(shipped - set(EXPECTED_VERDICTS))
    assert not undeclared, (
        "these examples ship without a declared verdict, so nothing pins what they teach: "
        + ", ".join(undeclared))
    assert not sorted(set(EXPECTED_VERDICTS) - shipped), "a declared verdict has no example file"


def test_the_documented_exit_codes_are_what_the_cli_returns(tmp_path):
    def run(cert):
        return subprocess.run(
            [sys.executable, "-m", "deadman.verify_certificate", str(cert), str(EX / "ledger.jsonl")],
            capture_output=True, text=True, cwd=str(ROOT), env=_subprocess_env())

    ok = run(EX / "certificate.json")
    assert ok.returncode == EXIT_OK
    assert "RESULT: VERIFIED at L1, THE FLOOR LAYER (exit 0)." in ok.stdout
    assert "COULD NOT VERIFY" in ok.stdout, "the limits are printed even on success"

    bad = run(EX / "certificate-tampered.json")
    assert bad.returncode == EXIT_CONTRADICTED
    assert "RESULT: CONTRADICTED (exit 1). 1 finding(s)." in bad.stdout

    junk = tmp_path / "junk.json"
    junk.write_text("{not json", encoding="utf-8")
    ugly = run(junk)
    assert ugly.returncode == EXIT_UNEVALUABLE
    assert "COULD NOT EVALUATE" in ugly.stderr


def test_the_shipped_bytes_carry_this_repos_line_endings():
    """CI went red on Linux and macOS because the generator used the platform default: the
    checked-in blob is CRLF (.gitattributes freezes it with `* -text`, and states "Every blob
    in this repo is CRLF"), and a POSIX runner wrote LF. Pinned here so the invariant is a
    test rather than a habit."""
    raw = (EX / "ledger.jsonl").read_bytes()
    crlf = b"\r\n"
    lf = b"\n"
    assert raw.count(crlf) == 16
    assert raw.count(lf) - raw.count(crlf) == 0, "a bare LF crept in"


def test_the_generator_reproduces_the_checked_in_files(tmp_path):
    """The example is regenerable, so nobody has to trust that the committed bytes came from
    the committed script."""
    before = {n: (EX / n).read_bytes()
              for n in ("ledger.jsonl", "certificate.json", "certificate-tampered.json",
                        "certificate-truncated.json")}
    r = subprocess.run([sys.executable, str(EX / "make_example.py")],
                       capture_output=True, text=True, cwd=str(ROOT), env=_subprocess_env())
    assert r.returncode == 0, r.stderr
    for name, original in before.items():
        assert (EX / name).read_bytes() == original, f"{name} is not reproducible from the script"


def test_the_example_flag_works_with_no_files_and_no_network(tmp_path):
    """The cold-start fix: a reader who just ran `pip install` has nothing to verify. This must
    work from a directory containing nothing, reading only what the package itself carries."""
    r = subprocess.run(
        [sys.executable, "-m", "deadman.verify_certificate", "--example"],
        capture_output=True, text=True, cwd=str(tmp_path), env=_subprocess_env())

    assert r.returncode == EXIT_OK, r.stdout + r.stderr
    assert "RESULT: VERIFIED at L1, THE FLOOR LAYER (exit 0)." in r.stdout
    assert "runs entirely offline" in r.stdout
    # It must hand the reader somewhere to go next, with a URL that works off pypi.org.
    assert "https://github.com/Roberto9210/deadman/tree/main/deadman/examples/certificate" in r.stdout
    assert not list(tmp_path.iterdir()), "--example must not write anything"


def test_the_missing_ledger_message_says_what_to_do(tmp_path):
    """It used to end one sentence early - accurate, and silent about the only possible next
    action. A stranger handed a certificate has never heard the word 'ledger'."""
    r = subprocess.run(
        [sys.executable, "-m", "deadman.verify_certificate", str(EX / "certificate.json")],
        capture_output=True, text=True, cwd=str(tmp_path), env=_subprocess_env())

    assert r.returncode == EXIT_UNEVALUABLE
    assert "WHAT TO DO" in r.stderr
    assert "ask whoever gave you the certificate" in r.stderr
    assert "append-only record" in r.stderr, "it must explain what a ledger is, not just name it"


def test_help_cites_no_specification_identifiers_a_reader_cannot_look_up():
    """NOTE ADDED 2026-09-03 - the assertions are unchanged, the PREMISE is not.

    This test was written when no specification document existed anywhere, so `C12` and `C13` in
    the help text were identifiers pointing at nothing and deleting them was the honest fix. That
    premise ended today: CERT_SPEC ships inside the package and `--spec` prints its path.

    It is NOT loosened, and the reason is that `C12`/`C13` remain unresolvable FROM THE HELP TEXT -
    a bare guarantee number still tells a reader nothing about where to look. What changed is that
    the answer now exists, so the right way to satisfy a future reader is to name the document
    (which `--spec` and the epilog do) rather than to name a guarantee.

    The note is here rather than in a commit message because whoever eventually decides this test
    is obsolete will be reading THIS FILE, and would otherwise delete it believing its premise
    still held. If the day comes that the help text can cite something a reader can look up, this
    test should be REPLACED by one asserting that citations resolve - not simply removed.
    """
    r = subprocess.run([sys.executable, "-m", "deadman.verify_certificate", "--help"],
                       capture_output=True, text=True, cwd=str(ROOT), env=_subprocess_env())
    assert r.returncode == 0
    assert "C12" not in r.stdout and "C13" not in r.stdout
    for layer in ("L1", "L2", "L3"):
        assert layer in r.stdout
    assert "does NOT survive an attacker with disk access" in r.stdout
