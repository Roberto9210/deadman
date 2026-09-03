"""`check_against_old.py` can now run a control for the checking tools themselves.

WHY THIS WAS A HOLE AND NOT A PREFERENCE. The tool that decides whether a control holds could only
swap files under `deadman/`, so every change to `scripts/` was verified the way the tool exists to
replace: break it by hand, read the scrollback, put it back. That is precisely the procedure this
repository measured going wrong twice in one day, and it was still the procedure for the three
files that do the measuring.

The reason it was limited was written down and it was a real reason - it just did not reach this
far. The docstring argues the swap must be IN PLACE because an editable install resolves the NAME
`deadman` through a `sys.meta_path` finder that `PYTHONPATH` cannot shadow. True, and irrelevant
here: `scripts/` is never imported as a package by the code under test. The tests invoke those
files by absolute path as a subprocess, so there is no name resolution to fool.

WHAT THE FLAT `.bak` NAMES COST. Backups are `<basename>.bak` with no directory in them, so once
two roots are searched a name in both is genuinely undecidable from the backup alone. It is
refused, not resolved by precedence, and that refusal is the interesting test: a precedence rule
would swap the file nobody meant and the run would still print CONTROL HOLDS.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import check_against_old as cao  # noqa: E402


def _touch(directory: Path, name: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    p = directory / name
    p.write_text("# placeholder\n", encoding="utf-8")
    return p


def _baks(tmp_path: Path, *names: str) -> list[Path]:
    """`names` are FULL file names, extension included: a real backup is `ledger.py.bak`, and the
    tool strips only `.bak`. Writing `ledger` here instead cost a red run while this file was
    being written, which is the same mistake in miniature as a `.bak` that names nothing."""
    holder = tmp_path / "backup"
    holder.mkdir(parents=True, exist_ok=True)
    out = []
    for name in names:
        b = holder / f"{name}.bak"
        b.write_text("# old\n", encoding="utf-8")
        out.append(b)
    return out


# --------------------------------------------------------------- the behaviour that is new

def test_a_backup_naming_a_file_under_scripts_now_resolves(tmp_path, monkeypatch):
    """The hole itself. Before this change the same input raised SystemExit."""
    pkg, tools = tmp_path / "deadman", tmp_path / "scripts"
    target = _touch(tools, "replace.py")
    _touch(pkg, "ledger.py")
    monkeypatch.setattr(cao, "SEARCH_ROOTS", (pkg, tools))

    targets = cao.resolve_targets(_baks(tmp_path, "replace.py"))

    assert list(targets) == [target]


def test_the_real_repository_has_both_roots_and_they_are_the_two_that_matter():
    """Pinned against the module's own constant: a later edit that drops `scripts/` fails here
    rather than quietly returning the tool to the state this file was written to end."""
    assert cao.SEARCH_ROOTS == (ROOT / "deadman", ROOT / "scripts")
    assert (ROOT / "scripts" / "replace.py").is_file()


# --------------------------------------------------------------- controls: preserved behaviour
# These must pass against BOTH versions of the tool. If one of them goes red against the old copy
# too, the change did more than it claimed.

def test_a_backup_naming_a_file_under_deadman_still_resolves(tmp_path, monkeypatch):
    pkg, tools = tmp_path / "deadman", tmp_path / "scripts"
    target = _touch(pkg, "ledger.py")
    tools.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(cao, "SEARCH_ROOTS", (pkg, tools))

    targets = cao.resolve_targets(_baks(tmp_path, "ledger.py"))

    assert list(targets) == [target]


def test_several_backups_resolve_together(tmp_path, monkeypatch):
    pkg, tools = tmp_path / "deadman", tmp_path / "scripts"
    a, b = _touch(pkg, "ledger.py"), _touch(tools, "replace.py")
    monkeypatch.setattr(cao, "SEARCH_ROOTS", (pkg, tools))

    targets = cao.resolve_targets(_baks(tmp_path, "ledger.py", "replace.py"))

    assert sorted(targets) == sorted([a, b])


def test_a_backup_naming_nothing_is_still_refused(tmp_path, monkeypatch):
    pkg, tools = tmp_path / "deadman", tmp_path / "scripts"
    pkg.mkdir(parents=True)
    tools.mkdir(parents=True)
    monkeypatch.setattr(cao, "SEARCH_ROOTS", (pkg, tools))

    with pytest.raises(SystemExit) as e:
        cao.resolve_targets(_baks(tmp_path, "nowhere.py"))

    assert "nowhere.py.bak" in str(e.value)


def test_the_refusal_names_every_root_it_looked_in(tmp_path, monkeypatch):
    """A message naming only one root sends the reader to check the wrong directory - the old
    message said `deadman/` and would now be a lie in exactly the case that got harder."""
    pkg, tools = tmp_path / "deadman", tmp_path / "scripts"
    pkg.mkdir(parents=True)
    tools.mkdir(parents=True)
    monkeypatch.setattr(cao, "SEARCH_ROOTS", (pkg, tools))

    with pytest.raises(SystemExit) as e:
        cao.resolve_targets(_baks(tmp_path, "nowhere.py"))

    message = str(e.value)
    assert "deadman/" in message and "scripts/" in message


# --------------------------------------------------------------- the cost of searching two roots

def test_a_name_present_in_both_roots_is_refused_and_not_guessed(tmp_path, monkeypatch):
    """The whole reason this is a refusal. Taking the first root would swap `deadman/x.py` while
    the caller meant `scripts/x.py`, the suite would run against an unchanged tool, and the tool
    would print CONTROL HOLDS - a green built out of the wrong file."""
    pkg, tools = tmp_path / "deadman", tmp_path / "scripts"
    _touch(pkg, "clash.py")
    _touch(tools, "clash.py")
    monkeypatch.setattr(cao, "SEARCH_ROOTS", (pkg, tools))

    with pytest.raises(SystemExit) as e:
        cao.resolve_targets(_baks(tmp_path, "clash.py"))

    message = str(e.value)
    assert "AMBIGUOUS" in message
    assert "deadman" in message and "scripts" in message


def test_the_ambiguous_refusal_happens_before_anything_is_swapped(tmp_path, monkeypatch):
    """Resolution runs to completion before main() copies a single byte, so one bad name in a
    batch of good ones leaves the tree untouched rather than half-swapped."""
    pkg, tools = tmp_path / "deadman", tmp_path / "scripts"
    fine = _touch(pkg, "ledger.py")
    _touch(pkg, "clash.py")
    _touch(tools, "clash.py")
    monkeypatch.setattr(cao, "SEARCH_ROOTS", (pkg, tools))

    before = fine.read_bytes()
    with pytest.raises(SystemExit):
        cao.resolve_targets(_baks(tmp_path, "ledger.py", "clash.py"))

    assert fine.read_bytes() == before


def test_a_directory_with_the_right_name_is_not_mistaken_for_the_file(tmp_path, monkeypatch):
    """`is_file()`, not `exists()`: `deadman/docs` is a directory and a `docs.bak` would have
    resolved to it under the old check, then been overwritten by shutil.copy."""
    pkg, tools = tmp_path / "deadman", tmp_path / "scripts"
    (pkg / "docs").mkdir(parents=True)
    tools.mkdir(parents=True)
    monkeypatch.setattr(cao, "SEARCH_ROOTS", (pkg, tools))

    with pytest.raises(SystemExit) as e:
        cao.resolve_targets(_baks(tmp_path, "docs"))

    assert "does not correspond" in str(e.value)
