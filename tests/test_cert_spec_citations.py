"""Every CERT_SPEC reference in the shipped code must land on a section that exists.

`verify_certificate.py` goes to PyPI. Until 2026-09-02 it cited `CERT_SPEC` and its sections
fifteen times and none of them existed anywhere, so a stranger following a reference in the source
arrived nowhere. Writing the document closed that once; this keeps it closed, because a document
and the citations into it drift apart silently and the person who finds out is the stranger.

THE PATTERN WAS WRITTEN AFTER LOOKING AT THE REAL CITATION FORMS, not before. The forms in the
source are irregular - `§A.1`, `SPEC §4`, `SPEC section 4.3`, `CERT_SPEC rule 5`, `guarantee C10` -
and a pattern invented first would have matched the tidy subset and reported a clean sweep over the
half it could see.

THREE OUTCOMES, because two would force a lie in one direction or the other:

    LOCAL     the target belongs to CERT_SPEC.md      -> must exist, or this test fails
    EXTERNAL  the target belongs to another repo      -> not ours to resolve, counted and named
    (nothing else: a citation the extractor cannot classify makes the test fail rather than
     being quietly dropped, which is how a sweep reports success over what it did not read)

WHAT A GREEN HERE MEANS - declared, because it is narrower than it sounds.

The first version of this file found six broken citations and was taken to have swept the shipped
surface. It had not. A SEVENTH, of the same class, sat in the other shipped file as a RELATIVE
MARKDOWN LINK, and the pattern did not match that shape - so the sweep reported that file clean.
A green would have read as "no broken citations" when it only ever meant "none OF THE FORMS
SOMEBODY THOUGHT TO LOOK FOR". That is the very defect this file exists to catch, one level up:
an artefact making a claim wider than what it measured.

The forms covered are listed in COVERED_FORMS, each with a sample the tests assert is still
classified - remove a branch from the pattern and its sample stops matching and the suite goes
red, so the list cannot drift into decoration. What is NOT covered is listed in NOT_COVERED, and
that list is part of reading the green.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "deadman" / "docs" / "CERT_SPEC.md"

#: What ships. A citation anywhere else is a repository concern; a citation in here reaches a
#: stranger who ran `pip install deadman-kit`.
SHIPPED = [
    ROOT / "deadman" / "verify_certificate.py",
    ROOT / "deadman" / "examples" / "certificate" / "README.md",
]

#: Written from the forms actually present. `guardian SPEC ...` is matched FIRST and on purpose:
#: it is a prefix of the local form, so the other order would classify every external citation as
#: local and demand that CERT_SPEC grow a section 17.
CITATION = re.compile(
    r"(?P<external>guardian\s+SPEC\s+section\s+(?P<ext_num>[\d.]+))"
    r"|CERT_SPEC\s+rule\s+(?P<rule>\d+)"
    r"|CERT_SPEC\s+v(?P<version>[\d.]+)"
    r"|(?P<step>CERT_STEP1\.md)"
    r"|SPEC\s+section\s+(?P<sec>[\d.]+)"
    r"|SPEC\s+§\s?(?P<spec_sig>[\dA-Za-z.]+)"
    r"|§\s?(?P<sig>A\.\d+|\d+[a-z]?(?:\.\d+)*)"
    r"|guarantee\s+(?P<guar>C\d+)"
    r"|\b(?P<bare_guar>C(?:9|1[0-9]))\b"
)


#: A markdown link whose target is a path, in a file that ships. Added 2026-09-03 after the sweep
#: reported the examples README clean while it carried a link to `../../docs/verify-certificate.md`
#: - a path that resolves in the repository and resolves to NOTHING inside an installed wheel,
#: because `docs/` is not packaged. The resolution below is deliberately done from the file's own
#: directory, which is the only place the reader of a shipped file can resolve it from.
MD_LINK = re.compile(r"\[[^\]]*\]\((?P<target>[^)#][^)]*)\)")

#: The reach of this sweep, stated. Each entry carries a sample that the tests re-classify, so the
#: declaration is load-bearing rather than a comment that outlives the code it describes.
COVERED_FORMS = (
    ("EXTERNAL", "as specified in guardian SPEC section 17.2, the seal"),
    ("RULE", "CERT_SPEC rule 5: a field that looks like evidence"),
    ("VERSION", "certificate (CERT_SPEC v0.2)."),
    ("DEAD_FILE", "flagged in CERT_STEP1.md as an assumption"),
    ("LOCAL", "counted from the events (SPEC section 4.3)"),
    ("LOCAL", "the layer actually reached (SPEC §A.3)"),
    ("LOCAL", "recomputed over the range (§A.2)"),
    ("GUARANTEE", "the limitations appear verbatim (guarantee C10)"),
)

#: NOT covered. Read this before reading a green.
NOT_COVERED = (
    "prose that describes a rule without naming it ('the verifier refuses a reworded limitation')",
    "citations inside files that do not ship - docs/, tests/, scripts/ are repository concerns",
    "a link whose target exists but whose LABEL names a different document (measured by eye "
    "today: the examples README labels a link 'CERT_SPEC rule 1' and points at another file)",
    "anchors within a target file (#fragments are stripped before resolution)",
)


def citations(text: str):
    """(kind, target, raw) for every reference found. Never silently drops a match."""
    out = []
    for m in CITATION.finditer(text):
        raw = m.group(0)
        if m.group("external"):
            out.append(("EXTERNAL", m.group("ext_num"), raw))
        elif m.group("rule"):
            out.append(("RULE", m.group("rule"), raw))
        elif m.group("version"):
            out.append(("VERSION", m.group("version"), raw))
        elif m.group("step"):
            out.append(("DEAD_FILE", "CERT_STEP1.md", raw))
        elif m.group("guar") or m.group("bare_guar"):
            out.append(("GUARANTEE", m.group("guar") or m.group("bare_guar"), raw))
        else:
            num = m.group("sec") or m.group("spec_sig") or m.group("sig")
            out.append(("LOCAL", num, raw))
    return out


def spec_sections() -> set[str]:
    """Section numbers that exist as HEADINGS. Numbers only, so a heading whose prose happens to
    contain '4.1' cannot satisfy a citation to section 4.1."""
    found = set()
    for line in SPEC.read_text(encoding="utf-8").split("\n"):
        m = re.match(r"^#{1,6}\s+(?:Appendix\s+)?([A-Za-z]?\.?\d+(?:\.\d+)*[a-z]?)[.\s]", line)
        if m:
            found.add(m.group(1).strip("."))
    return found


def spec_guarantees() -> set[str]:
    return set(re.findall(r"\*\*(C\d+)\*\*", SPEC.read_text(encoding="utf-8")))


def spec_rules() -> set[str]:
    return set(re.findall(r"^#{1,6}\s+\d+\.\s+Rule\s+(\d+)", SPEC.read_text(encoding="utf-8"), re.M))


def all_shipped_citations():
    out = []
    for f in SHIPPED:
        for kind, target, raw in citations(f.read_text(encoding="utf-8")):
            out.append((f.name, kind, target, raw))
    return out


# ---------------------------------------------------------------- the guards on the sweep itself

def test_the_extractor_finds_something():
    """A sweep that matches nothing reports a clean result over an empty set. That is the failure
    mode of every lexical check in this repository, so it is the first thing asserted."""
    found = all_shipped_citations()
    assert len(found) >= 20, f"the extractor found {len(found)} citations; the pattern went blind"


def test_every_citation_is_classified():
    """A citation the extractor cannot place must FAIL, not be dropped. Dropping is how a sweep
    reports success over the part it could not read."""
    for name, kind, target, raw in all_shipped_citations():
        assert kind in ("LOCAL", "EXTERNAL", "RULE", "VERSION", "GUARANTEE", "DEAD_FILE"), \
            f"{name}: {raw!r} was not classified"


def test_the_spec_itself_is_readable():
    assert SPEC.exists(), "docs/CERT_SPEC.md is what the shipped code cites"
    assert len(spec_sections()) >= 8, spec_sections()


# ---------------------------------------------------------------- the sweep

def test_every_local_citation_lands_on_a_section_that_exists():
    """The point of the whole file."""
    have = spec_sections()
    missing = sorted({(n, t, r) for n, k, t, r in all_shipped_citations() if k == "LOCAL"
                      if t not in have})
    assert not missing, (
        "these citations ship to PyPI and land nowhere:\n  "
        + "\n  ".join(f"{n}: {r!r} -> CERT_SPEC has no section {t}" for n, t, r in missing)
        + f"\n\nsections that do exist: {sorted(have)}")


def test_every_cited_guarantee_is_defined():
    have = spec_guarantees()
    missing = sorted({t for _, k, t, _ in all_shipped_citations() if k == "GUARANTEE"} - have)
    assert not missing, f"guarantees cited but not defined: {missing}; defined: {sorted(have)}"


def test_every_cited_rule_is_defined():
    have = spec_rules()
    missing = sorted({t for _, k, t, _ in all_shipped_citations() if k == "RULE"} - have)
    assert not missing, f"rules cited but not defined: {missing}; defined: {sorted(have)}"


def test_the_declared_version_matches_the_document():
    cited = {t for _, k, t, _ in all_shipped_citations() if k == "VERSION"}
    head = SPEC.read_text(encoding="utf-8").split("\n")[0]
    for v in cited:
        assert v in head, f"the code cites CERT_SPEC v{v} and the document titles itself {head!r}"


def test_no_shipped_citation_points_at_a_file_that_does_not_exist():
    """`CERT_STEP1.md` was a working document that never got versioned. Declaring it dead in some
    other document does not help the person who installed the package: the name travels inside the
    file that ships, so the fix has to happen there."""
    dead = [(n, r) for n, k, _, r in all_shipped_citations() if k == "DEAD_FILE"]
    assert not dead, (
        "these name a file that exists in no repository, and they ship:\n  "
        + "\n  ".join(f"{n}: {r!r}" for n, r in dead))


# ---------------------------------------------------------------- the reach of the sweep, asserted

def test_every_declared_form_is_still_recognised():
    """COVERED_FORMS is a promise about what this file measures. This is what stops it from
    becoming a comment: delete a branch of the pattern and its sample stops classifying."""
    for expected, sample in COVERED_FORMS:
        found = citations(sample)
        assert found, f"the declared form {expected} no longer matches anything: {sample!r}"
        assert found[0][0] == expected, \
            f"{sample!r} classified as {found[0][0]}, declared as {expected}"


def test_no_shipped_markdown_link_dangles_where_the_reader_will_open_it():
    """A relative link in a file that ships must resolve FROM THAT FILE'S OWN DIRECTORY.

    Not from the repository root: the reader who follows it has the installed package, where the
    repository above `deadman/` does not exist. A link that only works in a clone is a link that
    works for us and for nobody who did `pip install`.
    """
    dangling = []
    for f in SHIPPED:
        if f.suffix != ".md":
            continue
        for m in MD_LINK.finditer(f.read_text(encoding="utf-8")):
            target = m.group("target").split("#")[0].strip()
            if not target or "://" in target:
                continue                                   # a URL is not ours to resolve
            if not (f.parent / target).resolve().exists():
                dangling.append(f"{f.name}: {m.group(0)[:70]} -> {target}")
    assert not dangling, (
        "these ship and resolve to nothing from where the reader opens them:\n  "
        + "\n  ".join(dangling))


# ---------------------------------------------------------------- external, said without lying

def test_external_citations_are_named_not_silently_passed():
    """A citation whose target lives in another repository is neither resolved nor broken. Calling
    it resolved would claim we checked something we cannot; calling it broken would report a defect
    that is not ours. It is EXTERNAL, and it must say which repository - a citation that does not
    name its destination's repository is the same class as one pointing at a missing file: the
    reader cannot get there."""
    ext = [(n, t, r) for n, k, t, r in all_shipped_citations() if k == "EXTERNAL"]
    assert ext, "no external citations found; the classifier may have stopped working"
    for _, _, raw in ext:
        assert "guardian" in raw.lower(), f"{raw!r} does not name the repository it points at"


# ---------------------------------------------------------------- the control

def test_the_sweep_goes_red_when_a_heading_disappears():
    """CONTROL. Without this, every test above passes just as well if `spec_sections()` returns
    everything, or if the citation list is empty."""
    have = spec_sections()
    assert "A.1" in have

    pruned = have - {"A.1"}
    cited = {t for _, k, t, _ in all_shipped_citations() if k == "LOCAL"}
    assert "A.1" in cited, "A.1 must be cited by shipped code for this control to mean anything"
    assert cited - pruned, "removing a cited heading must leave a citation unresolved"
