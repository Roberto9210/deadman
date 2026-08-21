"""The worked example in examples/certificate/ is checked in, and documentation that drifts
from the code is worse than none - a reader who runs the command and gets different output
learns to distrust the whole repository. So the shipped files are verified on every run, and
the exact strings quoted in docs/verify-certificate.md are asserted here.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from deadman.verify_certificate import (
    EXIT_CONTRADICTED, EXIT_OK, EXIT_UNEVALUABLE, verify_certificate,
)

ROOT = Path(__file__).resolve().parents[1]
EX = ROOT / "examples" / "certificate"


def _entries():
    return [json.loads(l) for l in (EX / "ledger.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]


def _cert(name):
    return json.loads((EX / name).read_text(encoding="utf-8"))


def test_the_shipped_example_files_exist():
    for name in ("ledger.jsonl", "certificate.json", "certificate-tampered.json", "make_example.py"):
        assert (EX / name).exists(), f"examples/certificate/{name} is missing"


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


def test_the_documented_exit_codes_are_what_the_cli_returns(tmp_path):
    def run(cert):
        return subprocess.run(
            [sys.executable, "-m", "deadman.verify_certificate", str(cert), str(EX / "ledger.jsonl")],
            capture_output=True, text=True, cwd=str(ROOT))

    ok = run(EX / "certificate.json")
    assert ok.returncode == EXIT_OK
    assert "RESULT: VERIFIED at L1 (exit 0)." in ok.stdout
    assert "COULD NOT VERIFY" in ok.stdout, "the limits are printed even on success"

    bad = run(EX / "certificate-tampered.json")
    assert bad.returncode == EXIT_CONTRADICTED
    assert "RESULT: CONTRADICTED (exit 1). 1 finding(s)." in bad.stdout

    junk = tmp_path / "junk.json"
    junk.write_text("{not json", encoding="utf-8")
    ugly = run(junk)
    assert ugly.returncode == EXIT_UNEVALUABLE
    assert "COULD NOT EVALUATE" in ugly.stderr


def test_the_generator_reproduces_the_checked_in_files(tmp_path):
    """The example is regenerable, so nobody has to trust that the committed bytes came from
    the committed script."""
    before = {n: (EX / n).read_bytes()
              for n in ("ledger.jsonl", "certificate.json", "certificate-tampered.json")}
    r = subprocess.run([sys.executable, str(EX / "make_example.py")],
                       capture_output=True, text=True, cwd=str(ROOT))
    assert r.returncode == 0, r.stderr
    for name, original in before.items():
        assert (EX / name).read_bytes() == original, f"{name} is not reproducible from the script"
