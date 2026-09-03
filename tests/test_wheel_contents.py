"""What a stranger who ran `pip install deadman-kit` actually receives.

The repository is not the product. Twice now a file has been written, cited from shipping code,
and left outside the wheel - the examples before 0.2.1, and `CERT_SPEC.md` on 2026-09-02, the day
it was written. Both times the claim "it ships" was true of the repository and false of the
package, and both times the person who found out would have been the reader, not us.

THE PROPERTY MEASURED IS THE PROPERTY THAT MATTERS: the wheel is BUILT and OPENED. Not "the glob
in package-data looks right" - a glob can be correct while `packages.find` excludes the directory,
or while the file sits one level from where the pattern reaches. Checking the declaration instead
of the artefact is checking our intention instead of the result.

NO CHEAP GREEN. Presence alone would pass for an empty file, so the packaged bytes are compared
against the repository's, byte for byte. There is no edit that silences this test except shipping
the document.

AND THE DISK IS NOT THE REPOSITORY, which this file said until 2026-09-03 without noticing the
difference. The wheel is BUILT FROM THE DISK, so comparing the packaged bytes against the disk
compares two copies of one source: it cannot fail for the one cause we have since measured to
exist here. 17 of 84 tracked files have a blob that is LF and a working copy that is CRLF - git
normalised them on the way in under `core.autocrlf` and the two have disagreed silently ever
since. `CERT_SPEC.md` is not one of them today; nothing in the old assertion would have said so.
So the packaged bytes are compared against the BLOB as well, and the comparison is narrowed to
the cause: if the two are the same document, they must be the same bytes. An ordinary uncommitted
edit changes the content, so it does not trip this - only a byte difference with no content
difference does, and that is exactly the divergence.

WHY THIS FAILS INSTEAD OF SKIPPING when the build backend is missing: a check that skips when its
tool is absent is a check that reports nothing and looks like a pass. `build` is declared in the
`test` extra for exactly this reason, so the environment that runs the suite is the environment
that can run this.
"""
from __future__ import annotations

import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

#: Files that must reach the reader, with the reason each one is not decoration. A file listed
#: here without a reason is a file nobody will notice going missing.
MUST_SHIP = {
    "deadman/docs/CERT_SPEC.md":
        "verify_certificate.py cites it fifteen times and `--spec` prints its path",
    "deadman/examples/certificate/certificate.json":
        "`--example` reads it, and it is the only thing a fresh install can verify",
    "deadman/examples/certificate/README.md":
        "it is what tells the reader the examples are fabricated",
    "deadman/py.typed":
        "the package declares itself typed",
}


@pytest.fixture(scope="module")
def wheel(tmp_path_factory) -> zipfile.ZipFile:
    out = tmp_path_factory.mktemp("wheel")
    r = subprocess.run([sys.executable, "-m", "build", "--wheel", "-o", str(out)],
                       capture_output=True, text=True, cwd=str(ROOT))
    assert r.returncode == 0, (
        "the wheel did not build, so nothing below was measured. `build` is in the `test` extra: "
        "pip install -e .[test]\n\n" + r.stdout[-3000:] + r.stderr[-3000:])
    built = sorted(out.glob("*.whl"))
    assert len(built) == 1, f"expected exactly one wheel, got {[p.name for p in built]}"
    return zipfile.ZipFile(built[0])


def test_every_file_the_reader_needs_is_inside_the_wheel(wheel):
    names = set(wheel.namelist())
    missing = sorted(f"{p}  ({why})" for p, why in MUST_SHIP.items() if p not in names)
    assert not missing, (
        "these exist in the repository and NOT in the package a stranger installs:\n  "
        + "\n  ".join(missing)
        + "\n\nthe wheel contains:\n  " + "\n  ".join(sorted(names)))


def test_the_shipped_specification_is_the_one_in_the_repository(wheel):
    """Presence is not enough: an empty file at the right path would pass the test above."""
    packaged = wheel.read("deadman/docs/CERT_SPEC.md")
    on_disk = (ROOT / "deadman" / "docs" / "CERT_SPEC.md").read_bytes()
    assert packaged == on_disk, "the packaged specification is not the one in the repository"
    assert b"CERT_SPEC" in packaged and len(packaged) > 1000, "the packaged file is not a document"


def test_the_shipped_specification_is_also_the_one_git_serves(wheel):
    """The assertion above compares the wheel with the disk the wheel was built from, so it can
    only fail if `build` dropped bytes. This one compares it with what git actually stores, which
    is what every reader of this repository sees and what any other checkout would produce."""
    packaged = wheel.read("deadman/docs/CERT_SPEC.md")
    blob = subprocess.run(["git", "show", "HEAD:deadman/docs/CERT_SPEC.md"],
                          cwd=ROOT, capture_output=True).stdout
    assert b"CERT_SPEC" in blob and len(blob) > 1000, (
        "git did not hand back the stored document, so nothing below was compared - a test that "
        "passes on an empty blob is the cheap green this file exists to refuse")

    assert packaged == blob or _flat(packaged) != _flat(blob), (
        "the packaged specification and the one git stores are the same document with different "
        "bytes - the working copy and the blob have diverged, so what ships is not what any "
        "other checkout would build. Do NOT rewrite the file to match: see scripts/"
        "check_line_endings.py, which diagnoses this shape rather than prescribing the rewrite.")


def _flat(blob: bytes) -> bytes:
    """The document with its line endings taken out of the comparison, so that what remains is
    content. Two blobs that are equal here and unequal raw differ ONLY in their endings."""
    return blob.replace(b"\r\n", b"\n")


def test_the_check_is_capable_of_failing(wheel):
    """CONTROL. Every assertion above would hold just as well if `namelist()` returned everything
    or if the comparison were against itself. A path that is NOT packaged must be seen to be
    absent - `docs/SPEC.md` is a real file in the repository that deliberately does not ship."""
    names = set(wheel.namelist())
    assert (ROOT / "docs" / "SPEC.md").exists(), "fixture: the kit SPEC must exist in the repo"
    assert "docs/SPEC.md" not in names, "the control file is packaged; pick another"
    assert not any(n.startswith("docs/") for n in names), \
        "nothing outside the package directory should be in a wheel"
