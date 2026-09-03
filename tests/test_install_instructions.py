"""The install instructions must work for someone who is not us.

This file exists because of a specific failure. `docs/verify-certificate.md` opened with
`pip install deadman-kit` and `python -m deadman.verify_certificate`, and both lines were
wrong at once: the `[verify-sig]` extra they referenced did not exist in `pyproject.toml`, and
PyPI served 0.1.0, which predates the module entirely. Following the documentation in a clean
virtualenv produced `No module named deadman.verify_certificate`.

`tests/test_c_certificate_example.py` did not catch it, and could not have: it verifies the
tool behaves as documented **inside the repository**. Nothing checked whether a reader could
obtain the tool at all. That is the gap these tests close, and it is worth stating plainly:
a shipped example proves the tool works; it says nothing about the install line above it.

Two halves, because the failure had two halves:

* offline, always: the docs may not name a module or an extra this package does not provide.
* online, skipped politely when unavailable: if the docs tell a reader to `pip install
  deadman-kit` and run a module, **the published distribution must actually contain it**.
"""

from __future__ import annotations

import io
import json
import os
import re
import zipfile
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

import pytest

ROOT = Path(__file__).resolve().parents[1]
DOCS = [ROOT / "README.md", ROOT / "docs" / "verify-certificate.md"]
DIST = "deadman-kit"
PYPI_JSON = f"https://pypi.org/pypi/{DIST}/json"
NETWORK_TIMEOUT = 20


def _docs_text() -> str:
    return "\n".join(p.read_text(encoding="utf-8") for p in DOCS if p.exists())


def _declared_version() -> str:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    m = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    assert m, "no version in pyproject.toml"
    return m.group(1)


def test_the_package_reports_the_version_the_project_declares():
    """`_declared_version()` above was written and never called, so nothing tied the number a
    user sees at runtime to the number that gets uploaded. The release workflow checks the TAG
    against `pyproject.toml` and stops there, which means `__version__` could name any release at
    all and every gate would still be green - the installed package answering one version while
    the index served another. This is the missing side of that check."""
    from deadman import __version__

    assert __version__ == _declared_version(), (
        f"deadman.__version__ is {__version__!r} but pyproject.toml declares "
        f"{_declared_version()!r}. Whichever is wrong, a published artefact would misreport "
        f"itself to everyone who asked it directly.")


def _declared_extras() -> set[str]:
    """Parsed without tomllib: this suite runs on 3.10, where it does not exist."""
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    block = re.search(r"^\[project\.optional-dependencies\]\s*$(.*?)(?=^\[)",
                      text, re.MULTILINE | re.DOTALL)
    if not block:
        return set()
    return set(re.findall(r"^([A-Za-z0-9._-]+)\s*=", block.group(1), re.MULTILINE))


# ---------------------------------------------------------------- offline

def test_docs_never_name_a_module_this_package_does_not_ship():
    """`python -m deadman.X` in the documentation must resolve to a real module file."""
    named = set(re.findall(r"python -m (deadman(?:\.[A-Za-z0-9_]+)*)", _docs_text()))
    assert named, "the docs stopped naming any runnable module - check this test still applies"

    for dotted in sorted(named):
        rel = Path(*dotted.split(".")).with_suffix(".py")
        assert (ROOT / rel).exists(), f"docs tell people to run `python -m {dotted}`, but {rel} does not exist"


def test_docs_never_name_an_extra_this_package_does_not_declare():
    """The bug this file was written for: docs promised `deadman-kit[verify-sig]` while
    pyproject declared only `test`, so pip would warn and install nothing."""
    named = set(re.findall(re.escape(DIST) + r"\[([A-Za-z0-9._,-]+)\]", _docs_text()))
    declared = _declared_extras()
    for group in sorted(named):
        for extra in group.split(","):
            assert extra.strip() in declared, (
                f"docs advertise `{DIST}[{extra.strip()}]`, but pyproject declares {sorted(declared)}")


def test_the_package_keeps_zero_runtime_dependencies_whatever_the_extras_say():
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert re.search(r"^dependencies\s*=\s*\[\s*\]", text, re.MULTILINE), (
        "the base package must stay dependency-free; extras are opt-in and do not change that")


# ---------------------------------------------------------------- online

def _pypi_metadata():
    try:
        with urlopen(PYPI_JSON, timeout=NETWORK_TIMEOUT) as r:
            return json.load(r)
    except (URLError, TimeoutError, OSError) as e:
        pytest.skip(f"PyPI not reachable, so the published package cannot be checked here: {e}")


def _blocks_promising_pip_then_run() -> list[tuple[str, ...]]:
    """Fenced code blocks that tell a reader to install from PyPI and then run a module.

    Scoped to a single block on purpose. A `pip install` in one section and a `python -m` in
    another are two separate statements; a reader who copies one block is following one
    instruction, and that is the promise worth holding the package to.
    """
    out = []
    for doc in DOCS:
        if not doc.exists():
            continue
        for block in re.findall(r"```[a-z]*\n(.*?)```", doc.read_text(encoding="utf-8"), re.DOTALL):
            if "git clone" in block:
                continue
            if not re.search(r"(?<!\[)\bpip install " + re.escape(DIST) + r"\b(?!\[)", block):
                continue
            modules = tuple(sorted(set(re.findall(r"python -m (deadman(?:\.[A-Za-z0-9_]+)*)", block))))
            if modules:
                out.append(modules)
    return out


@pytest.mark.skipif(os.environ.get("DEADMAN_NO_NETWORK_TESTS") == "1",
                    reason="DEADMAN_NO_NETWORK_TESTS=1")
def test_a_pip_install_block_delivers_every_module_it_then_tells_you_to_run():
    """Checked against the REAL published distribution, not this checkout - the checkout is
    exactly what misled us the first time. While the docs honestly say "clone", there is no
    promise to keep and this skips, which is the correct state during a release window."""
    promised = _blocks_promising_pip_then_run()
    if not promised:
        pytest.skip("no code block currently promises pip-then-run, so PyPI is not being vouched for")

    meta = _pypi_metadata()
    latest = meta["info"]["version"]
    wheels = [u for u in meta["urls"] if u["packagetype"] == "bdist_wheel"]
    assert wheels, f"{DIST} {latest} publishes no wheel"

    try:
        with urlopen(wheels[0]["url"], timeout=NETWORK_TIMEOUT) as r:
            blob = r.read()
    except (URLError, TimeoutError, OSError) as e:
        pytest.skip(f"could not download the published wheel: {e}")

    shipped = set(zipfile.ZipFile(io.BytesIO(blob)).namelist())
    for modules in promised:
        for dotted in modules:
            member = "/".join(dotted.split(".")) + ".py"
            assert member in shipped, (
                f"a code block says `pip install {DIST}` then `python -m {dotted}`, but the "
                f"published {DIST} {latest} does not contain {member}. Either cut a release, or "
                f"tell readers to clone until you do.")
