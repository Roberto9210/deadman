"""Cold verification of the built 0.3.0 artefact, before anything is published.

Same shape as the runs in docs/COLD_START_LOG.md, with one difference that matters: those installed
FROM PyPI to check what a stranger gets. This one installs the LOCAL wheel, because the point is to
stop a bad artefact from being uploaded rather than to audit one that already was. The stale-index
trap the log records does not apply here - there is no index - so the version is asserted against
the file name instead.

Everything runs from a NEUTRAL working directory: the repository is on this machine, and a check
that runs inside it can pass by importing the source tree it was supposed to be testing.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

#: The version is NOT written here. A literal in this file would be one more place to forget, and
#: the whole point of the run is to catch an artefact that disagrees with itself - so the expected
#: version is taken from the wheel's own file name and then asserted against what the installed
#: package reports. Likewise the spec version, read from the installed code and compared with the
#: document it shipped beside: two halves of the artefact agreeing, rather than both agreeing with
#: something a person typed while thinking about something else.

def find_wheel(argv: list[str]) -> Path:
    if argv:
        return Path(argv[0])
    built = sorted((REPO / "dist").glob("deadman_kit-*-py3-none-any.whl"))
    if len(built) != 1:
        raise SystemExit(
            f"expected exactly one wheel in {REPO / 'dist'}, found {len(built)}: "
            f"{[w.name for w in built]}. Name the one to check, or clean dist/ first - a stale "
            f"wheel wearing a published version number is exactly what this run exists to stop.")
    return built[0]


def version_of(wheel: Path) -> str:
    return wheel.name.split("-")[1]


PROBE = '''
import json, sys, deadman
from deadman.verify_certificate import SPEC_VERSION
from pathlib import Path
pkg = Path(deadman.__file__).parent
spec = pkg / "docs" / "CERT_SPEC.md"
example = pkg / "examples" / "certificate" / "certificate.json"
print(json.dumps({
    "version": deadman.__version__,
    "spec_version": SPEC_VERSION,
    "package_at": str(pkg),
    "spec_shipped": spec.is_file(),
    "spec_sha256": __import__("hashlib").sha256(spec.read_bytes()).hexdigest() if spec.is_file() else None,
    "example_shipped": example.is_file(),
    "repo_on_path": any("Desktop" in p and "deadman" in p and "site-packages" not in p for p in sys.path),
    "non_stdlib_loaded": sorted(
        n for n, m in sys.modules.items()
        if "." not in n and getattr(m, "__file__", None)
        and "site-packages" in str(m.__file__) and n != "deadman"),
}))
'''

failures: list[str] = []
notes: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'OK  ' if ok else 'FAIL'}  {label}{(' - ' + detail) if detail else ''}")
    if not ok:
        failures.append(label)


def main(argv: list[str]) -> int:
    wheel = find_wheel(argv)
    expect_version = version_of(wheel)
    if not wheel.is_file():
        print(f"no wheel at {wheel}")
        return 2
    print(f"artefact: {wheel.name}  (expecting version {expect_version})")

    with tempfile.TemporaryDirectory(prefix="coldstart030-") as td:
        neutral = Path(td)
        venv = neutral / "v"
        print(f"cold venv: {venv}")
        subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True)
        py = venv / "Scripts" / "python.exe"
        if not py.exists():
            py = venv / "bin" / "python"

        r = subprocess.run([str(py), "-m", "pip", "install", "--no-deps", "-q", str(wheel)],
                           capture_output=True, text=True)
        if r.returncode != 0:
            print(r.stdout + r.stderr)
            return 2
        print("installed, zero dependencies pulled\n")

        probe_file = neutral / "probe.py"
        probe_file.write_text(PROBE, encoding="utf-8")
        r = subprocess.run([str(py), str(probe_file)], capture_output=True, text=True, cwd=neutral)
        if r.returncode != 0:
            print(r.stdout + r.stderr)
            return 2
        info = json.loads(r.stdout.strip().splitlines()[-1])
        expect_spec = info["spec_version"]

        print("ENVIRONMENT HONESTY")
        check("installed version is the one being published", info["version"] == expect_version,
              f'{info["version"]} vs {expect_version} from the file name')
        check("package resolves inside the cold venv", str(venv) in info["package_at"],
              info["package_at"])
        check("repository is NOT on the path", not info["repo_on_path"])
        check("no non-stdlib module loaded", info["non_stdlib_loaded"] == [],
              str(info["non_stdlib_loaded"]))

        print("\nWHAT THIS RELEASE EXISTS TO CHECK")
        check("CERT_SPEC.md is inside the installed package", info["spec_shipped"])
        repo_spec = REPO / "deadman" / "docs" / "CERT_SPEC.md"
        same = (info["spec_sha256"] == hashlib.sha256(repo_spec.read_bytes()).hexdigest())
        check("the packaged CERT_SPEC.md is byte-identical to the repository's", same,
              (info["spec_sha256"] or "")[:16])

        r = subprocess.run([str(py), "-m", "deadman.verify_certificate", "--spec"],
                           capture_output=True, text=True, cwd=neutral)
        printed = r.stdout.strip().splitlines()
        spec_path = next((Path(ln.strip()) for ln in printed
                          if ln.strip().endswith("CERT_SPEC.md")), None)
        check("--spec exits 0", r.returncode == 0, r.stderr.strip()[:120])
        check("--spec prints a path that exists on disk",
              spec_path is not None and spec_path.is_file(),
              str(spec_path))
        check("--spec points inside the cold venv, not at a repository",
              spec_path is not None and str(venv) in str(spec_path))
        check("--spec names the document version the code claims",
              any(expect_spec in ln for ln in printed), expect_spec)
        if spec_path and spec_path.is_file():
            head = spec_path.read_text(encoding="utf-8")[:200]
            check("the shipped document itself declares that version", expect_spec in head)

        print("\nTHE VERIFIER, ON THE CERTIFICATES IT SHIPS")
        check("an example certificate ships", info["example_shipped"])
        r = subprocess.run([str(py), "-m", "deadman.verify_certificate", "--example"],
                           capture_output=True, text=True, cwd=neutral)
        check("--example exits 0 (the honest certificate passes)", r.returncode == 0,
              f"exit {r.returncode}")
        check("--example names the layer it reached", "VERIFIED at L1" in r.stdout)

        pkg_examples = Path(info["package_at"]) / "examples" / "certificate"
        cert, ledger = pkg_examples / "certificate.json", pkg_examples / "ledger.jsonl"
        for name, expect in (("certificate-tampered.json", 1), ("certificate-truncated.json", 1)):
            r = subprocess.run([str(py), "-m", "deadman.verify_certificate",
                                str(pkg_examples / name), str(ledger)],
                               capture_output=True, text=True, cwd=neutral)
            check(f"{name} is CONTRADICTED (exit {expect})", r.returncode == expect,
                  f"exit {r.returncode}")

        r = subprocess.run([str(py), "-m", "deadman.verify_certificate", str(cert)],
                           capture_output=True, text=True, cwd=neutral)
        check("a certificate with no ledger is UNEVALUABLE (exit 2), not a pass",
              r.returncode == 2, f"exit {r.returncode}")

        r = subprocess.run([str(py), "-m", "deadman.verify_certificate",
                            str(cert), str(ledger), "--json"],
                           capture_output=True, text=True, cwd=neutral)
        try:
            payload = json.loads(r.stdout)
        except json.JSONDecodeError:
            payload = {}
            check("--json emits parseable JSON on the verified path", False)
        else:
            check("--json emits parseable JSON on the verified path", True)
            check("--json carries the spec version it judged against",
                  payload.get("spec") == expect_spec, str(payload.get("spec")))
            check("--json reports the checks that DID run",
                  payload.get("chainOk") is True and payload.get("certHashOk") is True,
                  f"chainOk={payload.get('chainOk')} certHashOk={payload.get('certHashOk')}")

        # The contract change itself, seen from outside: a run that stops early must not publish
        # the result of a check it never performed.
        bad = neutral / "no-dialect.json"
        doc = json.loads(cert.read_text(encoding="utf-8"))
        doc.pop("ledgerDialect", None)
        bad.write_text(json.dumps(doc), encoding="utf-8")
        r = subprocess.run([str(py), "-m", "deadman.verify_certificate",
                            str(bad), str(ledger), "--json"],
                           capture_output=True, text=True, cwd=neutral)
        try:
            stopped = json.loads(r.stdout)
        except json.JSONDecodeError:
            check("a stopped run still emits JSON", False, r.stdout[:120])
        else:
            check("a missing mandatory field is CONTRADICTED (exit 1), not unevaluable",
                  r.returncode == 1, f"exit {r.returncode}")
            check("a stopped run omits chainOk rather than publishing false",
                  "chainOk" not in stopped, str(stopped.get("chainOk")))
            check("a stopped run still reports certHashOk, because that check now runs first",
                  "certHashOk" in stopped, str(stopped.get("certHashOk")))

    print()
    if failures:
        print(f"COLD VERIFICATION FAILED: {len(failures)} check(s)")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("COLD VERIFICATION PASSED - every check above ran and held.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
