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


# --------------------------------------------------------------------------------------------
# THE MESSAGE WAS TRUE AND ITS IMPLIED CAUSE WAS FALSE
#
# Measured 2026-09-03: 17 of 84 tracked text files in this repository have a blob that is LF and
# a working copy that is CRLF. Nothing rewrote them. They were committed while `core.autocrlf`
# was normalising CRLF to LF on the way in; `* -text` later switched that off, so the first
# `git add` after the switch stores the working bytes verbatim and the blob "changes" endings.
#
# The guard compares blob to blob, so it reports that correctly. What was wrong was the remedy
# printed beneath it - "Rewrite these keeping their own endings" - because the file ALREADY has
# its own endings, and obeying would rewrite every line nobody touched. That is the exact damage
# the guard exists to prevent, produced by the guard's own advice.
#
# The discriminator is that NOTHING BUT THE ENDINGS CHANGED. It does not prove autocrlf on its
# own - an editor that rewrote endings while changing no content looks the same - so the
# diagnosis names both and withholds the remedy rather than guessing between them.

LF_ONLY = b"alpha\nbeta\ngamma\n"
CRLF_SAME = b"alpha\r\nbeta\r\ngamma\r\n"


def test_the_autocrlf_shape_is_named_as_a_diagnosis(repo):
    commit(repo, "f.txt", LF_ONLY, "blob stored LF, as autocrlf would have left it")
    commit(repo, "f.txt", CRLF_SAME, "first add after -text: the working bytes go in verbatim")

    r = run_checker(repo, "HEAD~1", "HEAD")

    assert r.returncode == 1, "still reported: a correct red beats a convenient green"
    assert "autocrlf" in r.stdout.lower(), r.stdout
    assert "only the line endings" in r.stdout.lower(), r.stdout


def test_the_autocrlf_shape_does_not_get_the_remedy_that_would_cause_the_damage(repo):
    """The defect itself. This is the assertion the whole change exists for."""
    commit(repo, "f.txt", LF_ONLY, "lf blob")
    commit(repo, "f.txt", CRLF_SAME, "crlf blob, same content")

    out = run_checker(repo, "HEAD~1", "HEAD").stdout.lower()

    assert "rewrite these keeping their own endings" not in out, (
        "the file already has its own endings; obeying this rewrites lines nobody touched")


def test_the_diagnosis_says_what_to_actually_do(repo):
    """A refusal that names no way through is how a guard gets disabled instead of obeyed."""
    commit(repo, "f.txt", LF_ONLY, "lf blob")
    commit(repo, "f.txt", CRLF_SAME, "crlf blob, same content")

    out = run_checker(repo, "HEAD~1", "HEAD").stdout.lower()

    assert "working copy" in out and "blob" in out, out


# --------------------------------------------------------------------- controls that must not move

def test_a_real_ending_rewrite_still_gets_the_ordinary_remedy(repo):
    """CONTROL. Content changed AND endings changed: an editor did this, and the old advice is
    the right advice. If this drifts into the diagnosis branch the guard has stopped working."""
    commit(repo, "f.txt", CRLF, "crlf")
    commit(repo, "f.txt", LF_REWRITE, "edited one line and rewrote every ending")

    out = run_checker(repo, "HEAD~1", "HEAD").stdout.lower()

    assert "rewrite these keeping their own endings" in out, out
    assert "autocrlf" not in out, "content changed, so this is not the artefact"


def test_crlf_to_lf_with_identical_content_is_not_the_artefact(repo):
    """CONTROL. Direction matters. autocrlf normalises INTO the blob as LF, so the artefact only
    ever appears as LF-blob becoming CRLF-blob. The opposite direction is somebody normalising,
    which is the thing that is closed."""
    commit(repo, "f.txt", CRLF_SAME, "crlf blob")
    commit(repo, "f.txt", LF_ONLY, "someone normalised it")

    out = run_checker(repo, "HEAD~1", "HEAD").stdout.lower()

    assert "autocrlf" not in out, out
    assert "rewrite these keeping their own endings" in out


def test_a_mixed_file_going_uniform_is_not_the_artefact(repo):
    """CONTROL. MIXED is not LF, so it cannot be the shape autocrlf leaves behind."""
    commit(repo, "f.txt", b"a\r\nb\nc\r\n", "mixed")
    commit(repo, "f.txt", b"a\r\nb\r\nc\r\n", "all crlf now")

    out = run_checker(repo, "HEAD~1", "HEAD").stdout.lower()

    assert "autocrlf" not in out, out


def test_the_declared_restoration_still_wins_over_the_diagnosis(repo):
    """CONTROL. A verified LINE-ENDINGS-RESTORED still passes silently; the new branch must not
    intercept a file that was going back to a shape it really had."""
    commit(repo, "f.txt", CRLF_SAME, "crlf")
    commit(repo, "f.txt", LF_ONLY, "normalised by accident")
    commit(repo, "f.txt", CRLF_SAME, "put it back\n\nLINE-ENDINGS-RESTORED: f.txt")

    assert run_checker(repo, "HEAD~1", "HEAD").returncode == 0
