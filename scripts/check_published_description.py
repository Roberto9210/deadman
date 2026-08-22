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


def description_of(dist: Path) -> str:
    """The long description exactly as the index will render it.

    METADATA is an RFC 822 document, so it is parsed as one rather than split by hand: the payload
    is the description, whatever line endings the builder happened to use.
    """
    if dist.suffix != ".whl":
        raise SystemExit(f"expected a .whl, got {dist}")

    with zipfile.ZipFile(dist) as z:
        name = next(n for n in z.namelist() if n.endswith(".dist-info/METADATA"))
        raw = z.read(name).decode("utf-8")

    msg = message_from_string(raw)
    body = msg.get_payload()
    if not body:                       # very old metadata folds it into a header instead
        body = msg.get("Description", "") or ""

    if len(body) < MIN_PLAUSIBLE_DESCRIPTION:
        raise SystemExit(
            f"REFUSING TO RELEASE - extracted only {len(body)} characters of description from "
            f"{dist.name}. Either the package genuinely has no README, or this script failed to "
            f"read it. Both mean the checks below would be meaningless, so they do not run.")
    return body


def check(text: str) -> list:
    offences = []
    low = text.lower()

    for claim in STALE_CLAIMS:
        if claim in low:
            line = next((l.strip() for l in text.splitlines() if claim in l.lower()), "")
            offences.append(
                f"STALE CLAIM {claim!r} in the description about to be published.\n"
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

    text = description_of(dist)
    print(f"checking the published description of {dist.name} ({len(text)} chars)")

    offences = check(text)
    if not offences:
        print("clean: no stale claims, no relative links, no clone-as-install.")
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
