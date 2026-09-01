"""Refuse a change that altered a file's line endings as a side effect.

This does NOT check that the repository is uniform. It is not - measured 2026-09-01: 40 blobs are
CRLF-only, 23 are LF-only and 4 are mixed inside themselves - and uniformity was never the property
that mattered. It is a proxy, and the proxy was believed for a year while being false.

The property that matters is the damage that actually happens:

    an edit changed a file's line endings, so a one-line change lands as a whole-file diff,
    and every line of that file has its git blame moved onto the editing commit.

That is what this measures, on the only object where it is visible: the diff. A file may be CRLF,
LF, or mixed - it must simply come out of a change the way it went in.

Usage:
    python scripts/check_line_endings.py [BASE [HEAD]]

BASE defaults to the merge-base with origin/main, HEAD to the working tree's HEAD. Exit 1 if any
changed file's line-ending profile changed; exit 0 otherwise.
"""
from __future__ import annotations

import subprocess
import sys


def _run(*args: str) -> bytes:
    return subprocess.run(["git", *args], capture_output=True, check=False).stdout


def profile(blob: bytes) -> tuple[int, int] | None:
    """(crlf, lone_lf) for a text blob, or None when there is nothing to judge."""
    if not blob or b"\0" in blob or b"\n" not in blob:
        return None                      # binary, empty, or single line without a terminator
    crlf = blob.count(b"\r\n")
    return crlf, blob.count(b"\n") - crlf


def describe(p: tuple[int, int] | None) -> str:
    if p is None:
        return "no line endings to judge"
    crlf, lf = p
    if crlf and lf:
        return f"MIXED ({crlf} CRLF + {lf} LF)"
    return f"{'CRLF' if crlf else 'LF'} ({crlf or lf} lines)"


def kind(p: tuple[int, int] | None) -> str | None:
    """What the file IS, ignoring how long it is: adding lines must not trip this."""
    if p is None:
        return None
    crlf, lf = p
    return "mixed" if (crlf and lf) else ("crlf" if crlf else "lf")


def changed_files(base: str, head: str) -> list[str]:
    out = _run("diff", "--name-only", "--diff-filter=M", base, head)
    return [f for f in out.decode("utf-8", "replace").splitlines() if f.strip()]


def check(base: str, head: str) -> list[str]:
    problems = []
    for path in changed_files(base, head):
        before = profile(_run("show", f"{base}:{path}"))
        after = profile(_run("show", f"{head}:{path}"))
        if kind(before) is None or kind(after) is None:
            continue
        if kind(before) != kind(after):
            problems.append(
                f"{path}\n"
                f"      before: {describe(before)}\n"
                f"      after:  {describe(after)}")
    return problems


def main(argv: list[str]) -> int:
    base = argv[0] if argv else (
        _run("merge-base", "HEAD", "origin/main").decode().strip() or "HEAD~1")
    head = argv[1] if len(argv) > 1 else "HEAD"

    problems = check(base, head)
    if not problems:
        print(f"line endings: unchanged in every modified file ({base[:12]}..{head[:12]})")
        return 0

    print("LINE ENDINGS CHANGED - a one-line edit will land as a whole-file diff and move the")
    print("git blame of every line onto this commit. Rewrite these keeping their own endings:")
    print()
    for p in problems:
        print(f"  - {p}")
    print()
    print("The repository is deliberately NOT uniform (see .gitattributes). Matching the file you")
    print("edit is the rule; matching some repo-wide convention is not.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
