"""Cold verification of the artefact PyPI actually serves - and only that, unless told otherwise.

WHY THE DEFAULT CHANGED, 2026-09-03. This script used to check the wheel built on this machine.
That is a check that CANNOT FAIL FOR THE ONE CAUSE THAT MATTERS: it compares a local copy against
the repository that produced it, so it is two views of one source agreeing with itself. Everything
between `python -m build` here and the bytes a stranger downloads - the build CI runs, the upload,
whatever the index serves - is exactly the gap it cannot see, and it is the gap the exercise is
about.

It was not a hypothetical. The 0.3.0 wheel published from CI and the one built here differ in 13
members. Measured, not assumed: 12 of the 13 differ ONLY in line endings, every published module
equals the git BLOB and every local module equals the working-copy DISK, and the 13th is `RECORD`,
which stores the others' hashes. So nothing transforms anything - CI builds from a fresh checkout
and this machine builds from a working copy whose endings have drifted from their blobs on 17
files. The conclusion stands regardless: THE ARTEFACT VERIFIED HERE WAS NEVER, BYTE FOR BYTE, THE
ONE ANYONE INSTALLS.

    python scripts/coldstart_check.py                 the published wheel - the default
    python scripts/coldstart_check.py --local         the local build - explicit, and marked
    python scripts/coldstart_check.py --local PATH    a particular local wheel

`--local` still has a job: before a release there is nothing published to check, and stopping a bad
artefact from being uploaded is worth doing. It is a PRE-FLIGHT, not a verification, and it says so
in its own output rather than leaving the reader to remember which mode they ran.

Everything runs from a NEUTRAL working directory: the repository is on this machine, and a check
that runs inside it can pass by importing the source tree it was supposed to be testing.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DIST_NAME = "deadman-kit"
INDEX = f"https://pypi.org/simple/{DIST_NAME}/"

#: The version is NOT written here. A literal in this file would be one more place to forget, and
#: the whole point of the run is to catch an artefact that disagrees with itself - so it is taken
#: from pyproject (published mode) or from the wheel's own file name (local mode) and then asserted
#: against what the installed package reports. Likewise the spec version, read from the installed
#: code and compared with the document it shipped beside: two halves of the artefact agreeing,
#: rather than both agreeing with something a person typed while thinking about something else.


def declared_version() -> str:
    text = (REPO / "pyproject.toml").read_text(encoding="utf-8")
    m = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    if not m:
        raise SystemExit("no version in pyproject.toml")
    return m.group(1)


def local_wheel(argument: str | None) -> Path:
    if argument:
        return Path(argument)
    built = sorted((REPO / "dist").glob("deadman_kit-*-py3-none-any.whl"))
    if len(built) != 1:
        raise SystemExit(
            f"expected exactly one wheel in {REPO / 'dist'}, found {len(built)}: "
            f"{[w.name for w in built]}. Name the one to check, or clean dist/ first - a stale "
            f"wheel wearing a published version number is exactly what this run exists to stop.")
    return built[0]


def download_published(version: str, into: Path) -> Path:
    """The published wheel, or a loud stop. NEVER a fallback to the local build: silently checking
    a different artefact than the one named is how a run reports on something nobody asked about."""
    try:
        with urllib.request.urlopen(INDEX, timeout=30) as r:
            page = r.read().decode("utf-8")
    except (urllib.error.URLError, TimeoutError) as e:
        raise SystemExit(
            f"could not reach {INDEX}: {e!r}\n"
            f"This run checks what PyPI serves, so without the index there is nothing to check. "
            f"It does NOT fall back to the local build - that would answer a different question "
            f"under the same heading. If you meant the pre-flight, pass --local and say so.")

    wanted = f"deadman_kit-{version}-py3-none-any.whl"
    match = [h for h in re.findall(r'href="([^"]+)"', page) if wanted in h]
    if not match:
        seen = sorted(set(re.findall(r"deadman_kit-([0-9.]+)-py3-none-any\.whl", page)))
        raise SystemExit(
            f"{wanted} is not on the index. Versions there: {seen}\n"
            f"If {version} was just tagged, the release may still be running - the simple index "
            f"updates promptly, so a miss here is usually a real miss. If you meant to check the "
            f"artefact BEFORE publishing it, that is --local: a pre-flight, not a verification.")

    target = into / wanted
    with urllib.request.urlopen(match[-1].split("#")[0], timeout=60) as r:
        target.write_bytes(r.read())
    return target


def flat(blob: bytes) -> bytes:
    """The bytes with line endings taken out of the comparison, so what remains is content."""
    return blob.replace(b"\r\n", b"\n")


def compare_with_local(published: Path, version: str) -> tuple[list[str], list[str]]:
    """(content differences, ending-only differences) between what shipped and what we built.

    The split is the whole value. A CONTENT difference means the thing checked before the upload
    was not the thing uploaded, and no amount of "it passed locally" survives that. An ENDING
    difference is the known, measured consequence of building from a working copy whose endings
    have drifted from their blobs - reported so nobody rediscovers it in a panic, not failed.
    """
    built = REPO / "dist" / f"deadman_kit-{version}-py3-none-any.whl"
    if not built.is_file():
        return [], []
    content, endings = [], []
    with zipfile.ZipFile(published) as zp, zipfile.ZipFile(built) as zl:
        names_p, names_l = set(zp.namelist()), set(zl.namelist())
        for only, where in ((names_p - names_l, "published"), (names_l - names_p, "local")):
            content += [f"{n} (only in the {where} wheel)" for n in sorted(only)]
        for name in sorted(names_p & names_l):
            p, l = zp.read(name), zl.read(name)
            if p == l or name.endswith("/RECORD"):
                continue                 # RECORD is derived: it stores the hashes of the rest
            (endings if flat(p) == flat(l) else content).append(name)
    return content, endings


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


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'OK  ' if ok else 'FAIL'}  {label}{(' - ' + detail) if detail else ''}")
    if not ok:
        failures.append(label)


def main(argv: list[str]) -> int:
    use_local = "--local" in argv
    rest = [a for a in argv if a != "--local"]
    if rest and not use_local:
        raise SystemExit(
            f"unexpected argument {rest[0]!r}. A bare path names a LOCAL wheel, and that is no "
            f"longer the default - pass --local with it, so the output says which artefact it "
            f"reports on.")

    with tempfile.TemporaryDirectory(prefix="coldstart-") as td:
        neutral = Path(td)

        if use_local:
            wheel = local_wheel(rest[0] if rest else None)
            expect_version = wheel.name.split("-")[1]
            print("!" * 78)
            print("!! PRE-FLIGHT ON A LOCAL BUILD - THIS IS NOT A VERIFICATION OF WHAT SHIPPED.")
            print("!! It compares a wheel built here against the repository that produced it, so")
            print("!! it cannot fail for the one cause that matters: a difference between what we")
            print("!! built and what PyPI serves. Useful before an upload; not evidence after one.")
            print("!" * 78)
        else:
            expect_version = declared_version()
            print(f"resolving the PUBLISHED {DIST_NAME} {expect_version} from {INDEX}")
            wheel = download_published(expect_version, neutral)
            digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
            print(f"  downloaded {wheel.name}, {wheel.stat().st_size} bytes, "
                  f"sha256 {digest[:16]}...")

        if not wheel.is_file():
            print(f"no wheel at {wheel}")
            return 2
        print(f"\nartefact: {wheel.name}  (expecting version {expect_version})")

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
        check("installed version is the one being checked", info["version"] == expect_version,
              f'{info["version"]} vs {expect_version}')
        check("package resolves inside the cold venv", str(venv) in info["package_at"],
              info["package_at"])
        check("repository is NOT on the path", not info["repo_on_path"])
        check("no non-stdlib module loaded", info["non_stdlib_loaded"] == [],
              str(info["non_stdlib_loaded"]))

        print("\nWHAT THIS RELEASE EXISTS TO CHECK")
        check("CERT_SPEC.md is inside the installed package", info["spec_shipped"])
        # Against the BLOB, not the disk. The disk is what a local build is made FROM, so comparing
        # to it asks the artefact whether it agrees with its own source; the blob is what git hands
        # every other checkout, which is what a stranger's copy is built from.
        blob = subprocess.run(["git", "show", "HEAD:deadman/docs/CERT_SPEC.md"],
                              cwd=REPO, capture_output=True).stdout
        check("git handed back the stored specification",
              b"CERT_SPEC" in blob and len(blob) > 1000, f"{len(blob)} bytes")
        check("the packaged CERT_SPEC.md is byte-identical to the one git stores",
              info["spec_sha256"] == hashlib.sha256(blob).hexdigest(),
              (info["spec_sha256"] or "")[:16])

        r = subprocess.run([str(py), "-m", "deadman.verify_certificate", "--spec"],
                           capture_output=True, text=True, cwd=neutral)
        printed = r.stdout.strip().splitlines()
        spec_path = next((Path(ln.strip()) for ln in printed
                          if ln.strip().endswith("CERT_SPEC.md")), None)
        check("--spec exits 0", r.returncode == 0, r.stderr.strip()[:120])
        check("--spec prints a path that exists on disk",
              spec_path is not None and spec_path.is_file(), str(spec_path))
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

        if not use_local:
            print("\nWHAT SHIPPED vs WHAT WE BUILT")
            built = REPO / "dist" / f"deadman_kit-{expect_version}-py3-none-any.whl"
            if not built.is_file():
                print("  nothing in dist/ to compare against - skipped. The run above stands on")
                print("  its own: it measured the published artefact, which is the point.")
            else:
                content, endings = compare_with_local(wheel, expect_version)
                check("no member differs in CONTENT between the published and the local wheel",
                      not content, ", ".join(content[:6]))
                if content:
                    print("        THIS IS THE LOUD ONE. Same version, different content: what was")
                    print("        checked before the upload is not what anyone installs. Do not")
                    print("        reason from the local run - it describes a different artefact.")
                if endings:
                    print(f"  NOTE  {len(endings)} member(s) differ ONLY in line endings. Expected")
                    print("        here, and not a failure: CI builds from a fresh checkout (the")
                    print("        blobs) and this machine builds from a working copy whose endings")
                    print("        have drifted on 17 files. See .gitattributes.")
                    print(f"        {', '.join(endings[:6])}"
                          + (f", +{len(endings) - 6} more" if len(endings) > 6 else ""))

    print()
    if failures:
        print(f"COLD VERIFICATION FAILED: {len(failures)} check(s)")
        for f in failures:
            print(f"  - {f}")
        return 1
    mode = "the LOCAL build (pre-flight only)" if use_local else "the PUBLISHED artefact"
    print(f"COLD VERIFICATION PASSED on {mode} - every check above ran and held.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
