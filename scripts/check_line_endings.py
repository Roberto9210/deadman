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

REPAIRING a file whose endings were normalised by accident is, by this measurement, identical to
committing the damage: undoing a whole-file diff is a whole-file diff. Without a way to say so the
only exits from a bad commit are rewriting history or leaving the guard red for good, and both are
worse than the defect. So a commit may declare, in its message:

    LINE-ENDINGS-RESTORED: path/to/file

and it is NOT taken on trust. The declaration is honoured only when the file's endings after the
change match a profile THAT FILE ACTUALLY HAD in its own history - you can back out of a
normalisation, you cannot declare your way into one. A declaration that does not check out is
reported as REJECTED, which is louder than saying nothing, because a claim was made.
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


def restoration_claims(head: str) -> set[str]:
    """Paths the head commit says it is putting back."""
    message = _run("log", "-1", "--format=%B", head).decode("utf-8", "replace")
    claims = set()
    for line in message.splitlines():
        line = line.strip()
        if line.upper().startswith("LINE-ENDINGS-RESTORED:"):
            path = line.split(":", 1)[1].strip()
            if path:
                claims.add(path)
    return claims


def had_this_shape_before(path: str, head: str, want: str | None) -> bool:
    """Did this file ever have these endings? Bounded to its own recent history, which is enough:
    a restoration is undoing something, and the thing being undone is recent by definition."""
    revs = _run("log", "-n", "30", "--format=%H", f"{head}~1", "--", path).decode().split()
    return any(kind(profile(_run("show", f"{rev}:{path}"))) == want for rev in revs)


def changed_files(base: str, head: str) -> list[str]:
    out = _run("diff", "--name-only", "--diff-filter=M", base, head)
    return [f for f in out.decode("utf-8", "replace").splitlines() if f.strip()]


def check(base: str, head: str) -> list[str]:
    claimed = restoration_claims(head)
    problems = []
    for path in changed_files(base, head):
        before = profile(_run("show", f"{base}:{path}"))
        after = profile(_run("show", f"{head}:{path}"))
        if kind(before) is None or kind(after) is None:
            continue
        if kind(before) == kind(after):
            continue

        if path in claimed:
            if had_this_shape_before(path, head, kind(after)):
                continue                 # a real repair: it is going back to what it was
            problems.append(
                f"{path}\n"
                f"      before: {describe(before)}\n"
                f"      after:  {describe(after)}\n"
                f"      CLAIM REJECTED: the commit declares LINE-ENDINGS-RESTORED for this file,\n"
                f"      but it never had these endings. A normalisation does not become a repair\n"
                f"      by being called one.")
            continue

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
