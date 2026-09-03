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


def only_the_endings_changed(path: str, base: str, head: str) -> bool:
    """True when the two blobs are the same document under different line endings.

    This is the discriminator, and it is worth being exact about what it does and does not
    establish. It RULES OUT an edit: nobody changed a byte of content. It does NOT establish
    autocrlf, because an editor that rewrote endings while changing nothing leaves an identical
    trace. That is why the branch below reports a shape and withholds a remedy instead of
    choosing between the two causes it cannot tell apart.
    """
    a = _run("show", f"{base}:{path}").replace(b"\r\n", b"\n")
    b = _run("show", f"{head}:{path}").replace(b"\r\n", b"\n")
    return a == b


def check(base: str, head: str) -> list[tuple[str, bool]]:
    """(report, is_autocrlf_shape) per offending file. The flag exists because the ADVICE has to
    differ: the ordinary remedy is actively harmful for the shape it used to be printed under."""
    claimed = restoration_claims(head)
    problems: list[tuple[str, bool]] = []
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
            problems.append((
                f"{path}\n"
                f"      before: {describe(before)}\n"
                f"      after:  {describe(after)}\n"
                f"      CLAIM REJECTED: the commit declares LINE-ENDINGS-RESTORED for this file,\n"
                f"      but it never had these endings. A normalisation does not become a repair\n"
                f"      by being called one.", False))
            continue

        # The blob was LF, the blob is now CRLF, and not one byte of content differs. That is
        # what `core.autocrlf` leaves behind: it normalised CRLF to LF on the way IN, so the blob
        # and the working copy disagreed silently for as long as the conversion was on. When
        # `* -text` switches it off, the next `git add` stores the working bytes and the blob
        # appears to change endings on its own. Measured here on 2026-09-03: 17 of 84 tracked
        # text files are in that state, so this is not a corner case, it is a queue.
        if kind(before) == "lf" and kind(after) == "crlf" \
                and only_the_endings_changed(path, base, head):
            problems.append((
                f"{path}\n"
                f"      before: {describe(before)}\n"
                f"      after:  {describe(after)}\n"
                f"      DIAGNOSIS: only the line endings changed - not one byte of content.\n"
                f"      This is the trace `core.autocrlf` leaves: it normalised this blob to LF\n"
                f"      on the way in, the working copy stayed CRLF, and once `* -text` turned\n"
                f"      the conversion off the working bytes went in verbatim. NOTHING REWROTE\n"
                f"      THE FILE. (An editor that rewrote endings while changing no content\n"
                f"      leaves the same trace, so this is the shape and not a confession - what\n"
                f"      separates them is whether the WORKING COPY changed, which git cannot\n"
                f"      show you after the fact.)\n"
                f"      DO NOT rewrite this file to get back to its old blob. It already has its\n"
                f"      own endings; rewriting moves the blame of every line for a change nobody\n"
                f"      made, which is the damage this guard exists to prevent.\n"
                f"      THE WAY THROUGH, once per file: decide deliberately that the working copy\n"
                f"      and the blob should agree, and say so in the commit. LINE-ENDINGS-RESTORED\n"
                f"      does not apply and will be rejected - the blob never had these endings.",
                True))
            continue

        problems.append((
            f"{path}\n"
            f"      before: {describe(before)}\n"
            f"      after:  {describe(after)}", False))
    return problems


def main(argv: list[str]) -> int:
    base = argv[0] if argv else (
        _run("merge-base", "HEAD", "origin/main").decode().strip() or "HEAD~1")
    head = argv[1] if len(argv) > 1 else "HEAD"

    problems = check(base, head)
    if not problems:
        print(f"line endings: unchanged in every modified file ({base[:12]}..{head[:12]})")
        return 0

    rewrites = [text for text, artefact in problems if not artefact]

    # The remedy is printed only when there is something it applies to. Printing it above a list
    # that is entirely autocrlf artefacts is how a true report acquires a false instruction, and
    # whoever obeyed it would do the damage the report was warning about.
    print("LINE ENDINGS CHANGED - a one-line edit will land as a whole-file diff and move the")
    if rewrites:
        print("git blame of every line onto this commit. Rewrite these keeping their own endings:")
    else:
        print("git blame of every line onto this commit. Read the diagnosis under each before")
        print("changing anything - the ordinary remedy does not apply to what is listed here:")
    print()
    for text, _ in problems:
        print(f"  - {text}")
    print()
    if rewrites:
        print("The repository is deliberately NOT uniform (see .gitattributes). Matching the file")
        print("you edit is the rule; matching some repo-wide convention is not.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
