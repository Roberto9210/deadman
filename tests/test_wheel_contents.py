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


def test_the_check_is_capable_of_failing(wheel):
    """CONTROL. Every assertion above would hold just as well if `namelist()` returned everything
    or if the comparison were against itself. A path that is NOT packaged must be seen to be
    absent - `docs/SPEC.md` is a real file in the repository that deliberately does not ship."""
    names = set(wheel.namelist())
    assert (ROOT / "docs" / "SPEC.md").exists(), "fixture: the kit SPEC must exist in the repo"
    assert "docs/SPEC.md" not in names, "the control file is packaged; pick another"
    assert not any(n.startswith("docs/") for n in names), \
        "nothing outside the package directory should be in a wheel"
