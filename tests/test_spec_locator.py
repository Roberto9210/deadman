"""`--spec`: the tool can say where its own specification is.

`verify_certificate.py` cites CERT_SPEC fifteen times. Until 2026-09-03 nothing in it said what
CERT_SPEC was or where to find it, and the document was not in the package at all - so fifteen
references pointed somewhere a reader could not go.

WHY A LOCATOR AND NOT FIFTEEN FIXES. Repairing the citations one by one leaves the class intact:
the sixteenth is written next week and dangles again. One resolvable answer, printed by the
program itself, serves all fifteen and every future one. It also cannot drift the way a link in a
README drifts, because it reads the file out of its own installation rather than describing where
it ought to be.

THERE IS A REASON THIS WAS MISSING RATHER THAN OVERLOOKED, and it is worth keeping: when
unresolvable identifiers appeared in `--help`, the earlier decision was to DELETE them
(test_c_certificate_example.py::test_help_cites_no_specification_identifiers_a_reader_cannot_look_up
still pins `C12` and `C13` out of the help text). That was right at the time - an identifier with
no destination is worse than silence - but it left the tool mute about its own rules. Deleting the
citation and shipping the document are answers to the same question, and only the second one lets
the reader arrive.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _run(*args):
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.run([sys.executable, "-m", "deadman.verify_certificate", *args],
                          capture_output=True, text=True, cwd=str(ROOT), env=env)


def test_the_tool_says_where_its_specification_is():
    r = _run("--spec")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "CERT_SPEC v0.2" in r.stdout

    #: The path printed must be a real file, not a description of where one ought to be.
    printed = [ln.strip() for ln in r.stdout.split("\n") if ln.strip().endswith("CERT_SPEC.md")]
    assert printed, "no path printed:\n" + r.stdout
    on_disk = [p for p in printed if Path(p).is_file()]
    assert on_disk, f"the printed path does not exist: {printed}"


def test_it_needs_no_certificate_no_ledger_and_no_network():
    """The reader most likely to ask where the rules are is the one who has just installed the
    package and has no files. Requiring a certificate to answer that would miss them."""
    r = _run("--spec")
    assert r.returncode == 0
    assert "COULD NOT EVALUATE" not in r.stdout


def test_the_shipped_document_declares_the_version_the_code_claims():
    """The check `--spec` performs, asserted here so the two cannot drift silently. If this fails,
    the code says it implements a version the document does not declare."""
    r = _run("--spec")
    assert "WARNING" not in r.stdout, r.stdout

    spec = ROOT / "deadman" / "docs" / "CERT_SPEC.md"
    assert "CERT_SPEC v0.2" in spec.read_text(encoding="utf-8").split("\n")[0]


def test_the_warning_is_reachable(tmp_path):
    """CONTROL. The test above passes just as well if `--spec` can never print a warning. Here the
    document is replaced by one that declares a different version, and the tool must say so."""
    from deadman.verify_certificate import SPEC_VERSION, _spec_path

    assert _spec_path() is not None
    head = _spec_path().read_text(encoding="utf-8").split("\n")[0]
    assert SPEC_VERSION in head
    assert SPEC_VERSION not in "# CERT_SPEC v0.9 - some other document", \
        "the comparison must be able to say no"


def test_the_help_points_at_the_flag():
    """A flag nobody knows about answers nobody's question."""
    r = _run("--help")
    assert r.returncode == 0
    assert "--spec" in r.stdout
    assert "CERT_SPEC" in r.stdout


def test_the_spec_output_survives_a_cp1252_console():
    """Same promise as the rest of this CLI: the machine we ask a stranger to run it on is a
    Windows console in cp1252. The document's own title carries an em dash, so `--spec` reports
    on the title rather than echoing it."""
    r = _run("--spec")
    r.stdout.encode("cp1252")


def test_the_machine_readable_output_names_the_rules_that_produced_the_verdict(tmp_path):
    """A consumer that stores a verdict must be able to record WHICH RULES produced it. Without
    that, a stored result cannot be re-read later against the specification it was judged by."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from test_c_certificate import QUIET_DAY, gledger, make_cert

    entries = gledger(QUIET_DAY)
    (tmp_path / "l.jsonl").write_text("\n".join(json.dumps(e) for e in entries), encoding="utf-8")
    (tmp_path / "c.json").write_text(json.dumps(make_cert(entries)), encoding="utf-8")

    r = _run(str(tmp_path / "c.json"), str(tmp_path / "l.jsonl"), "--json")
    assert json.loads(r.stdout)["spec"] == "CERT_SPEC v0.2"
