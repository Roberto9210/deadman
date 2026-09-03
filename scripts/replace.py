"""Replace an exact block of text in a file, or refuse loudly and change nothing.

WHY THIS EXISTS, and it is not tidiness. Editing one line of a config file cost writing a
single-use script - read the bytes, detect the line endings, assert the anchor is unique, write
back - and four of those were written in one afternoon. That is friction, and friction is what
makes a shortcut attractive. The shortcuts taken instead did damage the same day: a `sed -i`
mangled a line into uppercase with its backslashes eaten, and a heredoc was used to edit a config
because it was one command instead of one file.

The house rule is that a fix depending on remembering is not a fix - the correct path has to be
the SHORT one. So this covers both shapes that were actually reached for:

    python scripts/replace.py --batch edits.txt          many edits, many files, atomic
    python scripts/replace.py FILE --old OLD --new NEW    one line, and only when it is safe

THE SECOND FORM EXISTS BECAUSE OF THE FIRST'S ONE WEAKNESS. Repointing a single line through the
batch form costs writing a file plus running a command - two steps against `sed`'s one - and while
the shortcut is shorter it will be used. So the one-line form is one step, AND IT REFUSES the
moment its arguments contain anything the shell mangles: a quote, a backslash, a backtick, a `$`,
or a newline. Safe case: one step. Dangerous case: impossible, with the file form named in the
error. The refusal is the point - it is not a limitation to work around.

LINE ENDINGS ARE NOT NORMALISED. This repository is deliberately not uniform, and a tool that
rewrote a MIXED file to its dominant ending would be committing the exact defect the line-endings
guard exists to catch - a one-line change landing as a whole-file diff. The anchor is matched
against each ending in turn, and WHICHEVER ONE MATCHED IS WHAT THE REPLACEMENT IS WRITTEN WITH, so
the replaced lines keep the endings of their neighbours rather than of the file's majority.

Exit 0 when every edit landed. Exit 1 when anything was refused, and then NOTHING was written.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import difflib
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

#: What the shell eats, mangles, or expands. Not a style preference: `sed -i` uppercased a path and
#: swallowed its backslashes here on 2026-09-03, and a heredoc is a quoting minefield the moment a
#: backtick appears. Each of these sends the caller to the batch form, where nothing is parsed by
#: a shell at all.
SHELL_HOSTILE = {
    '"': "a double quote",
    "'": "a single quote",
    "\\": "a backslash",
    "`": "a backtick",
    "$": "a dollar sign",
    "\n": "a newline",
    "\r": "a carriage return",
}


def _refuse(*lines: str) -> None:
    for line in lines:
        print(line, file=sys.stderr)
    raise SystemExit(1)


# ---------------------------------------------------------------- matching, ending-aware

def _variants(text: str) -> dict[bytes, bytes]:
    """The anchor as it would look under each line ending, keyed by that ending.

    A block with no newline in it has a single form, and there is nothing to key on; the ending is
    then taken from the line the match lands in.
    """
    flat = text.replace("\r\n", "\n")
    lf = flat.encode("utf-8")
    crlf = flat.replace("\n", "\r\n").encode("utf-8")
    return {b"\n": lf} if lf == crlf else {b"\n": lf, b"\r\n": crlf}


def _ending_at(blob: bytes, index: int) -> bytes:
    """The line ending in force where this match landed, for an anchor with no newline of its own."""
    nl = blob.find(b"\n", index)
    if nl == -1:                                   # last line, no terminator: look backwards
        nl = blob.rfind(b"\n", 0, index)
    if nl == -1:
        return b"\n"                               # a file with no line ending at all
    return b"\r\n" if nl > 0 and blob[nl - 1:nl] == b"\r" else b"\n"


def locate(blob: bytes, old: str, where: str) -> tuple[int, bytes, bytes]:
    """(index, matched bytes, ending in force). Refuses unless the anchor appears exactly once.

    Counted across BOTH endings together, so an anchor appearing once as CRLF and once as LF in a
    mixed file is ambiguous and refused rather than silently taking one of them.
    """
    hits = [(blob.find(v), eol, v) for eol, v in _variants(old).items() if blob.count(v) == 1]
    total = sum(blob.count(v) for v in _variants(old).values())

    if total == 1 and hits:
        index, eol, matched = hits[0]
        if b"\n" not in matched:                   # single-line anchor: neighbours decide
            eol = _ending_at(blob, index)
        return index, matched, eol

    if total == 0:
        first = old.replace("\r\n", "\n").split("\n")[0].strip()
        lines = blob.decode("utf-8", "replace").split("\n")
        near = difflib.get_close_matches(first, [ln.strip() for ln in lines], n=3, cutoff=0.5)
        _refuse(
            f"NOT FOUND in {where}: the anchor appears 0 times, so nothing was written.",
            "",
            f"  looking for: {first[:90]!r}",
            *([f"  closest in the file:"] + [f"    {n[:90]!r}" for n in near]
              if near else ["  nothing in the file resembles it."]),
            "",
            "An anchor that does not match is usually one the file already changed under you.",
            "Read the file and rewrite the anchor; do not loosen it.")

    _refuse(
        f"AMBIGUOUS in {where}: the anchor appears {total} times, so nothing was written.",
        "",
        "Replacing 'the first one' is how an edit lands somewhere nobody looked. Extend the",
        "anchor with a neighbouring line until it is unique.")
    raise AssertionError("unreachable")            # _refuse exits


def apply_one(blob: bytes, old: str, new: str, where: str) -> bytes:
    index, matched, eol = locate(blob, old, where)
    replacement = new.replace("\r\n", "\n").replace("\n", eol.decode()).encode("utf-8")
    return blob[:index] + replacement + blob[index + len(matched):]


# ---------------------------------------------------------------- the batch file

def parse_batch(text: str, sep: str, where: str) -> list[tuple[str, str, str]]:
    """(path, old, new) triples. The separator is CHECKED against the payload, not assumed."""
    edits: list[tuple[str, str, str]] = []
    path: str | None = None
    section: str | None = None
    buf: dict[str, list[str]] = {"old": [], "new": []}

    for n, line in enumerate(text.replace("\r\n", "\n").split("\n"), 1):
        if line.startswith(sep):
            token = line[len(sep):].split(None, 1)
            head = (token[0] if token else "").upper()
            if head == "FILE":
                if len(token) < 2 or not token[1].strip():
                    _refuse(f"{where}:{n}: {sep}FILE needs a path")
                path, section = token[1].strip(), None
                buf = {"old": [], "new": []}
            elif head in ("OLD", "NEW"):
                if path is None:
                    _refuse(f"{where}:{n}: {sep}{head} before any {sep}FILE")
                section = head.lower()
            elif head == "END":
                if not buf["old"]:
                    _refuse(f"{where}:{n}: {sep}END with an empty {sep}OLD block")
                edits.append((path, "\n".join(buf["old"]), "\n".join(buf["new"])))
                section, buf = None, {"old": [], "new": []}
            else:
                _refuse(f"{where}:{n}: unknown directive {line!r}",
                        f"If your text really starts with {sep!r}, pass --sep to pick another marker.")
        elif section:
            buf[section].append(line)
        elif line.strip():
            _refuse(f"{where}:{n}: text outside any block: {line[:70]!r}")

    if section is not None:
        _refuse(f"{where}: the last block was never closed with {sep}END")
    if not edits:
        _refuse(f"{where}: no edits found. A batch that changes nothing is not a batch.")
    return edits


# ---------------------------------------------------------------- writing, all or nothing

def run(edits: list[tuple[str, str, str]], backup_dir: Path | None) -> int:
    """Every edit is computed BEFORE anything is written. One bad anchor writes no files at all -
    a half-applied batch leaves a tree that matches neither version, and the person who finds out
    is whoever runs the tests next."""
    staged: dict[Path, bytes] = {}
    originals: dict[Path, bytes] = {}

    for rel, old, new in edits:
        target = (ROOT / rel) if not Path(rel).is_absolute() else Path(rel)
        if not target.is_file():
            _refuse(f"NOT A FILE: {rel} (nothing was written)")
        blob = staged.get(target)
        if blob is None:
            blob = originals[target] = target.read_bytes()
        staged[target] = apply_one(blob, old, new, rel)

    if backup_dir is not None:
        stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        into = backup_dir / f"replace_{stamp}"
        into.mkdir(parents=True, exist_ok=True)
        for target in originals:
            shutil.copy2(target, into / (target.name + ".bak"))
        print(f"backup: {into}")

    for target, blob in staged.items():
        target.write_bytes(blob)
        print(f"replaced in {target.relative_to(ROOT) if ROOT in target.parents else target}")
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(
        prog="python scripts/replace.py",
        description="Exact, unique, ending-preserving text replacement. Refuses rather than guesses.")
    ap.add_argument("file", nargs="?", help="target file (one-line form)")
    ap.add_argument("--old", help="text to replace; refused if it contains anything a shell mangles")
    ap.add_argument("--new", help="replacement; same restriction")
    ap.add_argument("--batch", type=Path, help="a file of @@FILE/@@OLD/@@NEW/@@END blocks")
    ap.add_argument("--sep", default="@@", help="batch directive marker (default @@)")
    ap.add_argument("--backup-dir", type=Path, default=ROOT / "backups",
                    help="where the .bak copies go; pass an empty value to skip")
    a = ap.parse_args(argv)

    backup = a.backup_dir if str(a.backup_dir) else None

    if a.batch:
        if a.file or a.old or a.new:
            _refuse("--batch takes the whole edit; do not also pass a file or --old/--new.")
        text = a.batch.read_text(encoding="utf-8")
        return run(parse_batch(text, a.sep, str(a.batch)), backup)

    if not (a.file and a.old is not None and a.new is not None):
        ap.print_usage(sys.stderr)
        _refuse("", "Give either --batch, or a file with both --old and --new.")

    for label, value in (("--old", a.old), ("--new", a.new)):
        for ch, name in SHELL_HOSTILE.items():
            if ch in value:
                _refuse(
                    f"REFUSED: {label} contains {name}, and nothing was written.",
                    "",
                    "Text with quotes, backslashes, backticks, dollar signs or newlines does not",
                    "survive a shell intact - that is how a `sed -i` turned a path into uppercase",
                    "with its backslashes eaten in this repository. The one-line form is for the",
                    "case that is safe in one step; this is not that case.",
                    "",
                    "USE THE FILE FORM, where no shell parses anything:",
                    "",
                    "    write a batch file:",
                    "        @@FILE path/to/target",
                    "        @@OLD",
                    "        ...the exact text, as it is in the file...",
                    "        @@NEW",
                    "        ...the replacement...",
                    "        @@END",
                    "",
                    "    then:  python scripts/replace.py --batch that-file")
    return run([(a.file, a.old, a.new)], backup)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
