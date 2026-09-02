"""Run a test selection against the PREVIOUS version of the code, and tell the three outcomes apart.

A test that asserts a fix must FAIL against the code it fixed - otherwise it asserts nothing. The
usual way to check that is by hand: swap the file, run pytest, read the output. That is how it was
done here twice in one day, and it went wrong twice in the same way:

    the test FILE would not import against the old code, so pytest collected nothing, and the
    output looked like a run that had happened.

Nothing failed, so nothing looked wrong. That is this repository's own §5.8 rung 4 pointed at its
own test bench: DECLARING THAT A CHECK DID NOT RUN IS NOT THE SAME AS GUARANTEEING THAT IT RUNS.
A control that did not run is not a control that passed.

So the three outcomes are separated by the command instead of by whoever reads the scrollback:

    0  collected, and exactly the expected tests failed        the control holds
    1  collected, and something else happened                  the control says something else
    2  DID NOT COLLECT                                         the control did not run at all

WHY THE FILES ARE SWAPPED IN PLACE, since a mirror package would be safer and was tried first:
this package is installed EDITABLE, and an editable install puts a finder on `sys.meta_path` that
resolves the name `deadman` to this directory BEFORE `sys.path` is consulted. `PYTHONPATH` cannot
shadow it - measured, not assumed. (The same install once hid a CI failure here; see `git log`.)

So the swap is in place, and made safe by verifying the restore: every file's sha256 is recorded
before and checked after, and a failed restore is shouted rather than returned.

Usage:
    python scripts/check_against_old.py backups/def1_20260902 -k def1 --expect 2
"""
from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

HOLDS, DIFFERENT, DID_NOT_RUN = 0, 1, 2


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def run_pytest(tests: str, selector: str) -> str:
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    cmd = [sys.executable, "-m", "pytest", tests, "-q", "-p", "no:cacheprovider"]
    if selector:
        cmd += ["-k", selector]
    r = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True)
    return r.stdout + r.stderr


def classify(out: str, expected: int) -> tuple[int, str]:
    if "error during collection" in out or "errors during collection" in out:
        return DID_NOT_RUN, ("the test file did not IMPORT against the old code, so pytest "
                             "collected nothing. Nothing failed because nothing ran")
    if not re.search(r"\d+ (passed|failed|deselected)", out):
        return DID_NOT_RUN, "pytest reported no tests at all"
    failed = int(m.group(1)) if (m := re.search(r"(\d+) failed", out)) else 0
    passed = int(m.group(1)) if (m := re.search(r"(\d+) passed", out)) else 0
    if failed == expected:
        return HOLDS, (f"{failed} failed as expected, {passed} passed against BOTH versions "
                       f"(those are the controls for preserved behaviour)")
    return DIFFERENT, f"expected {expected} failures against the old code, got {failed}"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("backup", type=Path, help="backups/<name>/ holding the *.bak files")
    ap.add_argument("-k", "--select", default="", help="pytest -k selector")
    ap.add_argument("--tests", default="tests", help="test path (default: tests)")
    ap.add_argument("--expect", type=int, required=True,
                    help="how many tests must fail against the old code")
    ap.add_argument("--show", action="store_true", help="print the pytest output")
    a = ap.parse_args(argv)

    backup = a.backup if a.backup.is_absolute() else ROOT / a.backup
    if not backup.is_dir():
        raise SystemExit(f"no such backup directory: {backup}")
    baks = sorted(backup.glob("*.bak"))
    if not baks:
        raise SystemExit(f"no .bak files in {backup}")

    targets = {}
    for bak in baks:
        t = ROOT / "deadman" / bak.name[: -len(".bak")]
        if not t.exists():
            raise SystemExit(f"{bak.name} does not correspond to a file in deadman/")
        targets[t] = bak

    with tempfile.TemporaryDirectory() as td:
        keep = {t: (Path(td) / t.name, _sha(t)) for t in targets}
        for t, (saved, _) in keep.items():
            shutil.copy(t, saved)
        broken: list[str] = []
        try:
            for t, bak in targets.items():
                shutil.copy(bak, t)
            out = run_pytest(a.tests, a.select)
        finally:
            # No `return` in here: it would swallow whatever exception brought us to the finally,
            # and losing the reason a restore was needed is worse than the restore failing.
            for t, (saved, before) in keep.items():
                shutil.copy(saved, t)
                if _sha(t) != before:
                    broken.append(t.name)
        if broken:                           # never returned quietly: the tree is not as it was
            print(f"!!! RESTORE FAILED for {broken}. The working tree is NOT as you left it. "
                  f"Recover from {backup} or from git before doing anything else.",
                  file=sys.stderr)
            return DIFFERENT

    verdict, detail = classify(out, a.expect)
    if a.show:
        print(out)
    label = {HOLDS: "CONTROL HOLDS", DIFFERENT: "DIFFERENT RESULT",
             DID_NOT_RUN: "CONTROL DID NOT RUN"}[verdict]
    print(f"{label} (exit {verdict})")
    print(f"  old code:  {', '.join(sorted(t.name for t in targets))}  from {backup.name}")
    print(f"  selection: {a.tests}" + (f" -k {a.select}" if a.select else ""))
    print(f"  {detail}")
    if verdict == DID_NOT_RUN:
        print("  A control that did not run is NOT a control that passed. Move any import of a")
        print("  name the old code lacks INSIDE the single test that needs it.")
    return verdict


if __name__ == "__main__":
    raise SystemExit(main())
