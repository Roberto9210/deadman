"""Gate the RELEASE on the description that is about to be published.

Run against a built distribution, not against the working tree:

    python -m build
    python scripts/check_published_description.py dist/deadman_kit-*.whl

Why this exists, precisely. The long description is frozen into the release artefact at build
time. 0.2.0 shipped a README saying

    git clone ...   # not on PyPI yet: 0.1.0 predates it

which was true when written and false the moment 0.2.0 was published - and PyPI is where
`pip install` sends a reader. `main` was corrected within the hour; the published page stayed
wrong, because **a PyPI description cannot be edited**. Only a new release replaces it.

So the check belongs here and not in the ordinary test suite. `main` is allowed to be mid-repair;
what must never happen is a *published* page that contradicts the package a reader just installed,
or that links somewhere PyPI cannot follow. This breaks the release, and a release is the only
thing that can fix the problem it guards.

Exit 0 clean, 1 with the offences listed, 2 if it could not look.
"""

from __future__ import annotations

import re
import sys
import zipfile
from email import message_from_string
from pathlib import Path

#: Claims that are true only until the next release and become lies the moment it ships.
#: Matched case-insensitively as substrings of the published description.
#:
#: This is deliberately blunt, and it WILL fire on prose that merely quotes one of these
#: phrases while describing a past defect - it did, on the README section about the
#: cold-start run. The correct response is to reword the sentence, never to teach this
#: list to tell quotation from assertion. A gate that can be argued with stops being a
#: gate, and the cost of bluntness is one rewritten sentence.
STALE_CLAIMS = [
    "not on pypi yet",
    "not yet on pypi",
    "not yet released",
    "coming soon",
    "predates it",
    "predates this",
    "until a release is cut",
    "once released",
    "clone until",
]

#: Present-tense capability claims about something that is OFF unless the user wires it up.
#:
#: 0.2.1 shipped the Summary "hash-chained and externally anchored ledger". The library anchors
#: nothing by default - `publisher=None`, and `_maybe_anchor` returns immediately - so on every
#: install that phrase described a ledger that was anchored exactly never. It reads identically
#: whether anchoring is on or off, which is the rule-5 test failing: a phrase that does not
#: distinguish anything is not evidence, it is decoration, and decoration in a Summary is the
#: most-read and least-qualified string the project publishes.
#:
#: Blunt on purpose, exactly like STALE_CLAIMS, and it WILL fire on prose that legitimately
#: discusses one of these phrases while explaining the defect. Reword the sentence. Never teach
#: this list to tell an assertion from a discussion of one: a gate that can be argued with has
#: stopped being a gate.
OPTIONAL_AS_PRESENT = [
    "externally anchored",
    "anchored ledger",
    "is anchored",
    "are anchored",
    "tamper-proof",
    "tamper proof",
    "tamper-evident",
    "tamper evident",
]

#: A published description is read on PyPI, where a relative link resolves to nothing useful.
#: Anchors and mail links are fine.
RELATIVE_LINK = re.compile(r"\]\((?!https?://|#|mailto:)([^)]+)\)")

#: `git clone` is not forbidden outright - a contributor section may legitimately use it - but it
#: must not appear as the way to OBTAIN the tool, which is what shipped in 0.2.0.
CLONE_AS_INSTALL = re.compile(r"git clone[^\n]*\n[^\n]*python -m deadman", re.IGNORECASE)

#: A description shorter than this is not a description; it means extraction failed. The first
#: draft of this script split the metadata on a bare blank line while METADATA uses CRLF, so it
#: read ZERO characters and pronounced the release clean. A gate that passes because it measured
#: nothing is worse than no gate at all, because it also hands out confidence. Hence the floor.
MIN_PLAUSIBLE_DESCRIPTION = 500


def published_text(dist: Path) -> tuple:
    """Both frozen strings: the one-line Summary and the long description.

    METADATA is an RFC 822 document, so it is parsed as one rather than split by hand: the payload
    is the description, whatever line endings the builder happened to use.

    The Summary used to be skipped entirely, which is how "externally anchored ledger" reached
    PyPI through a gate that ran and passed. It is the shortest string on the page and the only
    one that appears in search results, so it is now checked first.
    """
    if dist.suffix != ".whl":
        raise SystemExit(f"expected a .whl, got {dist}")

    with zipfile.ZipFile(dist) as z:
        name = next(n for n in z.namelist() if n.endswith(".dist-info/METADATA"))
        raw = z.read(name).decode("utf-8")

    msg = message_from_string(raw)
    summary = (msg.get("Summary", "") or "").strip()
    if not summary:
        raise SystemExit(f"REFUSING TO RELEASE - {dist.name} has no Summary header to check.")
    body = msg.get_payload()
    if not body:                       # very old metadata folds it into a header instead
        body = msg.get("Description", "") or ""

    if len(body) < MIN_PLAUSIBLE_DESCRIPTION:
        raise SystemExit(
            f"REFUSING TO RELEASE - extracted only {len(body)} characters of description from "
            f"{dist.name}. Either the package genuinely has no README, or this script failed to "
            f"read it. Both mean the checks below would be meaningless, so they do not run.")
    return summary, body


def check(text: str, where: str = "description") -> list:
    offences = []
    low = text.lower()

    for claim in OPTIONAL_AS_PRESENT:
        if claim in low:
            line = next((l.strip() for l in text.splitlines() if claim in l.lower()), "")
            offences.append(
                f"OPTIONAL CAPABILITY STATED AS PRESENT: {claim!r} in the {where}.\n"
                f"      {line[:160]}\n"
                f"      This names something the user must switch on as though it were "
                f"already true. Say what it takes - who supplies it, and what the package "
                f"does without it - or drop the phrase.")

    for claim in STALE_CLAIMS:
        if claim in low:
            line = next((l.strip() for l in text.splitlines() if claim in l.lower()), "")
            offences.append(
                f"STALE CLAIM {claim!r} in the {where} about to be published.\n"
                f"      {line[:120]}\n"
                f"      A PyPI page cannot be edited afterwards. Fix the README and rebuild.")

    for target in RELATIVE_LINK.findall(text):
        offences.append(
            f"RELATIVE LINK ]({target}) - this description is rendered on pypi.org, where a "
            f"relative path reaches nothing. Use the full https://github.com/... URL.")

    if CLONE_AS_INSTALL.search(text):
        offences.append(
            "CLONE PRESENTED AS THE WAY TO GET THE TOOL. The reader arrived by running "
            "`pip install`; telling them to clone contradicts what they just did.")

    return offences


def main(argv: list) -> int:
    if len(argv) != 2:
        print("usage: check_published_description.py dist/deadman_kit-<version>-py3-none-any.whl",
              file=sys.stderr)
        return 2

    dist = Path(argv[1])
    if not dist.exists():
        print(f"no such distribution: {dist}", file=sys.stderr)
        return 2

    summary, text = published_text(dist)
    print(f"checking the published Summary of {dist.name} ({len(summary)} chars)")
    print(f"  {summary}")
    print(f"checking the published description of {dist.name} ({len(text)} chars)")

    offences = check(summary, "Summary") + check(text, "description")
    if not offences:
        print("clean: no optional capability stated as present, no stale claims, no "
              "relative links, no clone-as-install.")
        return 0

    print()
    print(f"REFUSING TO RELEASE - {len(offences)} problem(s) in the description that would be "
          f"frozen on PyPI:")
    for o in offences:
        print(f"  - {o}")
    print()
    print("None of these can be fixed after publication. Correct the README and cut the release "
          "again.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
