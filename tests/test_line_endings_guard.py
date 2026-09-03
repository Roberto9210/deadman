"""The guard that replaces a false invariant with the property that matters.

`.gitattributes` claimed for a year that every blob here is CRLF. Measured against the stored
blobs it was false the day it was written - 21 of 46 contradicted it - and the freeze was argued
from it. Uniformity was a PROXY. The damage it stood in for is specific and visible on the diff:

    an edit changed a file's line endings, so a one-line change lands as a whole-file diff and
    moves the git blame of every line onto the editing commit.

These tests build real throwaway repositories rather than mocking git, because the thing under
test is a claim about what git reports.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT / "scripts" / "check_line_endings.py"


def git(repo: Path, *args: str) -> str:
    r = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)
    return r.stdout


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    d = tmp_path / "r"
    d.mkdir()
    git(d, "init", "-q")
    git(d, "config", "user.email", "t@t")
    git(d, "config", "user.name", "t")
    git(d, "config", "core.autocrlf", "false")
    (d / ".gitattributes").write_bytes(b"* -text\n")
    return d


def commit(repo: Path, name: str, data: bytes, message: str) -> str:
    (repo / name).write_bytes(data)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message)
    return git(repo, "rev-parse", "HEAD").strip()


def run_checker(repo: Path, base: str, head: str):
    return subprocess.run([sys.executable, str(CHECKER), base, head],
                          cwd=repo, capture_output=True, text=True)


CRLF = b"one\r\ntwo\r\nthree\r\n"
CRLF_EDITED = b"one\r\ntwo CHANGED\r\nthree\r\n"
LF_REWRITE = b"one\ntwo CHANGED\nthree\n"


def test_an_edit_that_keeps_the_endings_passes(repo):
    """CONTROL. Without this the test below proves only that the checker can say no."""
    base = commit(repo, "f.txt", CRLF, "add")
    head = commit(repo, "f.txt", CRLF_EDITED, "edit, keeping CRLF")

    r = run_checker(repo, base, head)
    assert r.returncode == 0, r.stdout
    assert "unchanged in every modified file" in r.stdout


def test_an_edit_that_rewrites_the_endings_is_refused(repo):
    """The case that actually happened: a one-line change written back as LF."""
    base = commit(repo, "f.txt", CRLF, "add")
    head = commit(repo, "f.txt", LF_REWRITE, "same edit, rewritten as LF")

    r = run_checker(repo, base, head)
    assert r.returncode == 1
    assert "LINE ENDINGS CHANGED" in r.stdout
    assert "f.txt" in r.stdout
    assert "CRLF" in r.stdout and "LF" in r.stdout


def test_an_LF_file_is_equally_protected(repo):
    """The rule is *keep this file's own endings*, not *use CRLF*. A repo-wide convention is
    exactly the proxy this replaces, so the guard must fire in both directions."""
    base = commit(repo, "f.txt", b"one\ntwo\n", "add an LF file")
    head = commit(repo, "f.txt", b"one\r\ntwo CHANGED\r\n", "rewritten as CRLF")

    r = run_checker(repo, base, head)
    assert r.returncode == 1
    assert "f.txt" in r.stdout


def test_a_mixed_file_may_stay_mixed(repo):
    """Four files in this repository are mixed inside themselves. They are not the damage and
    must not be forced to convert by a guard aimed at something else."""
    base = commit(repo, "f.txt", b"a\r\nb\nc\r\n", "add a mixed file")
    head = commit(repo, "f.txt", b"a\r\nb CHANGED\nc\r\n", "edit, still mixed")

    r = run_checker(repo, base, head)
    assert r.returncode == 0, r.stdout


def test_adding_lines_is_not_a_change_of_endings(repo):
    """The check is on WHAT the file is, not how long it is: growing a CRLF file is fine."""
    base = commit(repo, "f.txt", CRLF, "add")
    head = commit(repo, "f.txt", CRLF + b"four\r\nfive\r\n", "append, keeping CRLF")

    r = run_checker(repo, base, head)
    assert r.returncode == 0, r.stdout


def test_a_new_file_is_not_judged(repo):
    """A file with no `before` has no endings to preserve; any choice is legitimate."""
    base = commit(repo, "a.txt", CRLF, "add a")
    head = commit(repo, "b.txt", b"only\nlf\n", "add b as LF")

    r = run_checker(repo, base, head)
    assert r.returncode == 0, r.stdout


def test_the_real_repository_passes_its_own_guard():
    """Run it over this repo's own last change. A guard nobody runs is not a guard."""
    r = subprocess.run([sys.executable, str(CHECKER), "HEAD~1", "HEAD"],
                       cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout


# ---------------------------------------------------------------- restoring, declared and checked

def test_a_declared_restoration_that_is_true_is_allowed(repo):
    """A REPAIR IS INDISTINGUISHABLE FROM A VIOLATION BY THIS MEASUREMENT, and that is not a flaw
    in the measurement - undoing a normalisation IS a whole-file diff. Without a way to say so,
    the only ways out of a broken commit are rewriting history or leaving the guard red forever.

    So the escape hatch exists and it is NOT a rubber stamp: the declaration is CHECKED. The file's
    endings after the change must match a profile that file actually had in its own history. You
    cannot declare your way into a fresh normalisation, only back out of one.
    """
    commit(repo, "f.txt", b"a\r\nb\nc\r\n", "mixed, as it always was")
    commit(repo, "f.txt", b"a\r\nb\r\nc\r\n", "an edit that normalised it by accident")
    commit(repo, "f.txt", b"a\r\nb\nc\r\nd\n",
           "Put it back\n\nLINE-ENDINGS-RESTORED: f.txt")

    r = run_checker(repo, "HEAD~1", "HEAD")
    assert r.returncode == 0, r.stdout


def test_a_declared_restoration_that_is_false_is_still_refused(repo):
    """THE HALF THAT MAKES IT A CHECK. Declaring a restoration to a profile the file never had is
    a normalisation wearing the word 'restored', and it must fail - LOUDER than an undeclared one,
    because someone made a claim."""
    commit(repo, "f.txt", b"a\r\nb\r\nc\r\n", "CRLF from birth")
    commit(repo, "f.txt", b"a\nb\nc\n", "Tidy up\n\nLINE-ENDINGS-RESTORED: f.txt")

    r = run_checker(repo, "HEAD~1", "HEAD")
    assert r.returncode == 1, r.stdout
    assert "REJECTED" in r.stdout, r.stdout
    assert "never had" in r.stdout, r.stdout


def test_a_declaration_only_covers_the_file_it_names(repo):
    """CONTROL. One repair must not license every file in the same commit."""
    commit(repo, "f.txt", b"a\r\nb\nc\r\n", "mixed")
    commit(repo, "g.txt", b"x\r\ny\r\n", "another file, CRLF")
    commit(repo, "f.txt", b"a\r\nb\r\nc\r\n", "normalise f")
    (repo / "f.txt").write_bytes(b"a\r\nb\nc\r\n")
    (repo / "g.txt").write_bytes(b"x\ny\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "Put f back\n\nLINE-ENDINGS-RESTORED: f.txt")

    r = run_checker(repo, "HEAD~1", "HEAD")
    assert r.returncode == 1, r.stdout
    assert "g.txt" in r.stdout
    assert "REJECTED" not in r.stdout, "g.txt was never claimed; nothing to reject"


def test_an_undeclared_repair_is_still_refused(repo):
    """CONTROL THAT MUST NOT MOVE. The hatch opens only when someone says the word."""
    commit(repo, "f.txt", b"a\r\nb\nc\r\n", "mixed")
    commit(repo, "f.txt", b"a\r\nb\r\nc\r\n", "normalised by accident")
    commit(repo, "f.txt", b"a\r\nb\nc\r\n", "put it back, saying nothing")

    assert run_checker(repo, "HEAD~1", "HEAD").returncode == 1
