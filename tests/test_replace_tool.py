"""The editing tool, tested on the two things that actually went wrong.

`scripts/replace.py` exists because writing a single-use script to change one line is friction, and
friction is what makes a shortcut attractive. The shortcuts did real damage the day it was written:
a `sed -i` uppercased a path and ate its backslashes, and a heredoc was used to edit a config file
because it was one command instead of one file. Two of the cases below are those exact failures.

WHAT IS ASSERTED IS THE PROPERTY, NOT A PROXY. Not "the tool ran" - that a byte outside the
replaced region is identical, that a MIXED file comes out mixed the same way, and that a refusal
writes NOTHING. A tool whose failure mode is a half-applied batch would be worse than the scripts
it replaces, because a half-applied batch matches neither version and the person who finds out is
whoever runs the tests next.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "scripts" / "replace.py"


def run(*args, cwd=None):
    return subprocess.run([sys.executable, str(TOOL), *[str(a) for a in args]],
                          cwd=str(cwd or ROOT), capture_output=True, text=True)


@pytest.fixture()
def sandbox(tmp_path):
    """A real file on disk with a real backup directory, because both are what the tool touches."""
    (tmp_path / "bk").mkdir()
    return tmp_path


def batch(sandbox, body: str) -> Path:
    p = sandbox / "edits.txt"
    p.write_text(body, encoding="utf-8")
    return p


def nobackup(sandbox):
    return ["--backup-dir", sandbox / "bk"]


# ---------------------------------------------------------------- it does the thing

def test_a_replacement_lands_and_touches_nothing_else(sandbox):
    f = sandbox / "f.py"
    f.write_bytes(b"alpha\nBEFORE\nomega\n")
    r = run(f, "--old", "BEFORE", "--new", "AFTER", *nobackup(sandbox))
    assert r.returncode == 0, r.stderr
    assert f.read_bytes() == b"alpha\nAFTER\nomega\n"


def test_the_batch_form_edits_several_files_in_one_run(sandbox):
    a, b = sandbox / "a.txt", sandbox / "b.txt"
    a.write_bytes(b"one\ntwo\n")
    b.write_bytes(b"three\nfour\n")
    spec = batch(sandbox, f"@@FILE {a}\n@@OLD\ntwo\n@@NEW\nTWO\n@@END\n"
                          f"@@FILE {b}\n@@OLD\nfour\n@@NEW\nFOUR\n@@END\n")
    r = run("--batch", spec, *nobackup(sandbox))
    assert r.returncode == 0, r.stderr
    assert a.read_bytes() == b"one\nTWO\n" and b.read_bytes() == b"three\nFOUR\n"


def test_a_backup_is_written_without_being_asked(sandbox):
    """Taking a backup was a house rule that depended on remembering, and it was forgotten once."""
    f = sandbox / "f.txt"
    f.write_bytes(b"keep\nchange\n")
    r = run(f, "--old", "change", "--new", "changed", *nobackup(sandbox))
    assert r.returncode == 0
    saved = list((sandbox / "bk").rglob("*.bak"))
    assert len(saved) == 1 and saved[0].read_bytes() == b"keep\nchange\n"


# ---------------------------------------------------------------- it refuses

def test_an_anchor_that_matches_nothing_refuses_and_says_what_is_close(sandbox):
    f = sandbox / "f.txt"
    original = b"the quick brown fox\njumps over\n"
    f.write_bytes(original)
    r = run(f, "--old", "the quick brown cat", "--new", "x", *nobackup(sandbox))
    assert r.returncode == 1
    assert "0 times" in r.stderr
    assert "quick brown fox" in r.stderr, "the diagnostic must show what is actually there"
    assert f.read_bytes() == original, "a refusal must write nothing"


def test_an_anchor_that_matches_twice_refuses_rather_than_taking_the_first(sandbox):
    f = sandbox / "f.txt"
    original = b"dup\nmiddle\ndup\n"
    f.write_bytes(original)
    r = run(f, "--old", "dup", "--new", "x", *nobackup(sandbox))
    assert r.returncode == 1
    assert "appears 2 times" in r.stderr
    assert f.read_bytes() == original


def test_a_batch_that_fails_on_its_last_edit_writes_none_of_them(sandbox):
    """ATOMICITY, and it is the reason to prefer this over three separate commands."""
    a, b, c = sandbox / "a.txt", sandbox / "b.txt", sandbox / "c.txt"
    for p, body in ((a, b"one\n"), (b, b"two\n"), (c, b"three\n")):
        p.write_bytes(body)
    spec = batch(sandbox, f"@@FILE {a}\n@@OLD\none\n@@NEW\nONE\n@@END\n"
                          f"@@FILE {b}\n@@OLD\ntwo\n@@NEW\nTWO\n@@END\n"
                          f"@@FILE {c}\n@@OLD\nNOT THERE\n@@NEW\nx\n@@END\n")
    r = run("--batch", spec, *nobackup(sandbox))
    assert r.returncode == 1
    assert a.read_bytes() == b"one\n", "the first edit must not have landed"
    assert b.read_bytes() == b"two\n", "the second edit must not have landed"
    assert c.read_bytes() == b"three\n"


def test_a_payload_that_looks_like_a_directive_is_refused_with_a_way_out(sandbox):
    """A delimiter that can collide and is not checked is the same family of defect this repository
    keeps finding. It is checked, and the escape is named."""
    f = sandbox / "f.txt"
    f.write_bytes(b"x\n")
    spec = batch(sandbox, f"@@FILE {f}\n@@OLD\nx\n@@NEW\n@@decorator\n@@END\n")
    r = run("--batch", spec, *nobackup(sandbox))
    assert r.returncode == 1
    assert "--sep" in r.stderr, r.stderr
    assert f.read_bytes() == b"x\n"


def test_another_separator_makes_that_payload_writable(sandbox):
    """CONTROL for the test above: the refusal must be a real escape, not a dead end."""
    f = sandbox / "f.txt"
    f.write_bytes(b"x\n")
    spec = batch(sandbox, f"%%FILE {f}\n%%OLD\nx\n%%NEW\n@@decorator\n%%END\n")
    r = run("--batch", spec, "--sep", "%%", *nobackup(sandbox))
    assert r.returncode == 0, r.stderr
    assert f.read_bytes() == b"@@decorator\n"


# ---------------------------------------------------------------- line endings

def test_a_crlf_file_stays_crlf(sandbox):
    f = sandbox / "f.txt"
    f.write_bytes(b"a\r\nBEFORE\r\nc\r\n")
    assert run(f, "--old", "BEFORE", "--new", "AFTER", *nobackup(sandbox)).returncode == 0
    assert f.read_bytes() == b"a\r\nAFTER\r\nc\r\n"


def test_an_lf_file_stays_lf(sandbox):
    f = sandbox / "f.txt"
    f.write_bytes(b"a\nBEFORE\nc\n")
    assert run(f, "--old", "BEFORE", "--new", "AFTER", *nobackup(sandbox)).returncode == 0
    assert f.read_bytes() == b"a\nAFTER\nc\n"


def test_a_mixed_file_is_not_normalised_and_each_line_keeps_its_neighbours_endings(sandbox):
    """THE CASE THAT COST A COMMIT. An edit normalised a MIXED file (206 CRLF + 38 LF) to all-CRLF,
    so seventeen new lines landed as a whole-file diff and moved the git blame of 244 lines.

    A tool that picked the file's DOMINANT ending would commit that same defect, quietly, every
    time. So the anchor is matched under each ending and the one that matched decides how the
    replacement is written - here the same file is edited twice, in a CRLF region and in an LF
    region, and each replacement comes out in the ending of the lines around it.

    THE REPLACEMENTS ARE TWO LINES EACH, AND THAT IS NOT DECORATION. The first version of this
    test replaced one line with one line, so NO NEWLINE WAS EVER WRITTEN and the ending logic was
    never reached: it passed against a deliberately broken tool that normalised to the dominant
    ending. A single-line replacement leaves the surrounding bytes untouched, so the file's
    endings are preserved for free and the test measures nothing.
    """
    f = sandbox / "f.txt"
    original = b"crlf one\r\nCRLF TARGET\r\ncrlf two\r\nlf one\nLF TARGET\nlf two\n"
    f.write_bytes(original)

    spec = batch(sandbox,
                 f"@@FILE {f}\n@@OLD\nCRLF TARGET\n@@NEW\ncrlf A\ncrlf B\n@@END\n"
                 f"@@FILE {f}\n@@OLD\nLF TARGET\n@@NEW\nlf A\nlf B\n@@END\n")
    r = run("--batch", spec, *nobackup(sandbox))
    assert r.returncode == 0, r.stderr

    out = f.read_bytes()
    assert out == b"crlf one\r\ncrlf A\r\ncrlf B\r\ncrlf two\r\nlf one\nlf A\nlf B\nlf two\n"
    assert out.count(b"\r\n") == original.count(b"\r\n") + 1, "the CRLF region gained one CRLF"
    assert out.count(b"\n") == original.count(b"\n") + 2, "one new line in each region"


def test_the_minority_ending_wins_in_its_own_region(sandbox):
    """THE DISCRIMINATING CASE, and the one that catches a tool taking the easy route.

    Every other ending test here would pass just as well if the tool used the file's DOMINANT
    ending: in a mostly-CRLF file, guessing CRLF is right almost everywhere. So this puts the edit
    in the LF minority of a CRLF-majority file, where the two answers differ - and asserts the
    region wins.
    """
    f = sandbox / "f.txt"
    f.write_bytes(b"a\r\nb\r\nc\r\nd\r\ne\r\nMINORITY\nz\n")
    spec = batch(sandbox, f"@@FILE {f}\n@@OLD\nMINORITY\n@@NEW\none\ntwo\n@@END\n")
    assert run("--batch", spec, *nobackup(sandbox)).returncode == 0

    out = f.read_bytes()
    assert out == b"a\r\nb\r\nc\r\nd\r\ne\r\none\ntwo\nz\n", out
    assert b"one\r\n" not in out, "the replacement took the file's majority instead of its region"


def test_a_multi_line_replacement_in_a_crlf_region_of_a_mixed_file_uses_crlf(sandbox):
    """The harder half: the REPLACEMENT brings new lines with it, and they must be born with the
    endings of where they land, not with the ones the batch file happened to be written in."""
    f = sandbox / "f.txt"
    f.write_bytes(b"lf head\ncrlf a\r\nANCHOR\r\ncrlf b\r\n")
    spec = batch(sandbox, f"@@FILE {f}\n@@OLD\nANCHOR\n@@NEW\nfirst\nsecond\n@@END\n")
    assert run("--batch", spec, *nobackup(sandbox)).returncode == 0
    assert f.read_bytes() == b"lf head\ncrlf a\r\nfirst\r\nsecond\r\ncrlf b\r\n"


def test_an_anchor_ambiguous_across_endings_is_refused(sandbox):
    """CONTROL for the ending logic. The same two lines present once as CRLF and once as LF are
    two matches, not one - taking either would be the tool choosing for you."""
    f = sandbox / "f.txt"
    original = b"one\r\ntwo\r\nfiller\none\ntwo\n"
    f.write_bytes(original)
    spec = batch(sandbox, f"@@FILE {f}\n@@OLD\none\ntwo\n@@NEW\nX\nY\n@@END\n")
    r = run("--batch", spec, *nobackup(sandbox))
    assert r.returncode == 1
    assert "appears 2 times" in r.stderr
    assert f.read_bytes() == original


# ---------------------------------------------------------------- the shell guard

@pytest.mark.parametrize("bad,name", [
    ("it's here", "single quote"),
    ('say "hi"', "double quote"),
    ("C:\\Users\\home", "backslash"),
    ("`cmd`", "backtick"),
    ("$HOME", "dollar"),
])
def test_the_one_line_form_refuses_anything_a_shell_mangles(sandbox, bad, name):
    f = sandbox / "f.txt"
    original = b"plain\n"
    f.write_bytes(original)
    r = run(f, "--old", "plain", "--new", bad, *nobackup(sandbox))
    assert r.returncode == 1, f"{name} was accepted"
    assert f.read_bytes() == original


def test_the_refusal_tells_you_which_form_to_use_instead(sandbox):
    """THE OTHER CASE THAT COST SOMETHING TODAY. `sed -i` mangled a line here and the lesson is not
    'be careful' - it is that the correct path has to be the reachable one. A refusal that only
    says NO leaves the caller reaching for the shortcut again, so it names the way through."""
    f = sandbox / "f.txt"
    f.write_bytes(b"plain\n")
    r = run(f, "--old", "it's a quote", "--new", "x", *nobackup(sandbox))
    assert r.returncode == 1
    assert "a single quote" in r.stderr, "the message must name what it objected to"
    assert "USE THE FILE FORM" in r.stderr
    assert "@@OLD" in r.stderr and "--batch" in r.stderr, \
        "naming the form is not enough; the message must show it"


def test_the_safe_one_line_case_is_still_one_step(sandbox):
    """CONTROL. A guard that refused everything would be safe and useless: the one-line form has
    to keep working for the case it exists for, or the shortcut wins on convenience again."""
    f = sandbox / "conf.toml"
    f.write_bytes(b"name = old-value\nother = 1\n")
    r = run(f, "--old", "name = old-value", "--new", "name = new-value", *nobackup(sandbox))
    assert r.returncode == 0, r.stderr
    assert f.read_bytes() == b"name = new-value\nother = 1\n"


# ---------------------------------------------------------------- the sweep can fail

def test_the_tool_reports_failure_through_its_exit_code(sandbox):
    """Every assertion above reads stderr. If the tool exited 0 on a refusal, a caller in a script
    would carry on as though the edit had landed."""
    f = sandbox / "f.txt"
    f.write_bytes(b"x\n")
    assert run(f, "--old", "nope", "--new", "y", *nobackup(sandbox)).returncode == 1
    assert run("--batch", sandbox / "does-not-exist.txt", *nobackup(sandbox)).returncode != 0
