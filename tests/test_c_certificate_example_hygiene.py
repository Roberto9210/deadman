"""The shipped examples must keep obeying the rules the spec applies to real certificates.

This file exists because of how the defect it guards against was actually born. Nobody wrote a
bad example: the examples were fine when written, the EMITTER changed, and the published
artefacts aged in silence. `issuer.version` went from "1.0.0.0" to "0.1.0-beta+<sha>" and
`issuer.buildHash` from the hash of a file path to the hash of the assembly's bytes, and the
examples kept teaching the old shape - including a `buildHash` of "example", a constant, which
fails CERT_SPEC rule 5's own question: *what does it distinguish?*

Fixing those by hand would guarantee a repeat at the next emitter change. So the rules are
asserted here instead, over whatever JSON happens to be in deadman/examples/certificate/.

The coverage assertion at the bottom is the one worth defending: the published set must show
BOTH what the emitter produces when it knows a value AND what it produces when it does not,
because rule 1 - unknown is omitted, never defaulted - is otherwise visible only in prose. A
reader learns the shape from the examples, so the examples have to contain the shape.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
EX = ROOT / "deadman" / "examples" / "certificate"

#: Values that look like content and carry none. Compared as whole values, case-insensitively,
#: so a self-describing alias like "example-trader" is fine while a bare "example" is not.
FILLER = {"example", "test", "sample", "sample-value", "todo", "tbd", "changeme",
          "placeholder", "dummy", "foo", "bar", "baz", "xxx", "n/a", "none", "null",
          "unknown", "unset", "1.0.0.0", "0.0.0.0", ""}

#: What IssuerIdentity.VersionOf can emit: a semantic version, optionally a fourth .NET
#: component, optionally a pre-release suffix, optionally "+<commit>" build metadata.
VERSION_FORM = re.compile(r"^\d+\.\d+\.\d+(\.\d+)?(-[0-9A-Za-z.-]+)?(\+[0-9A-Za-z.-]+)?$")

BUILD_HASH_FORM = re.compile(r"^[0-9a-f]{16}$")


def _certificates():
    files = sorted(EX.glob("certificate*.json"))
    assert files, "no example certificates found - has deadman/examples/certificate/ moved?"
    return [(f.name, json.loads(f.read_text(encoding="utf-8"))) for f in files]


def _walk(node, path=""):
    """Every scalar in the document, with the dotted path that reaches it."""
    if isinstance(node, dict):
        for k, v in node.items():
            yield from _walk(v, f"{path}.{k}" if path else k)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from _walk(v, f"{path}[{i}]")
    else:
        yield path, node


# ---------------------------------------------------------------- no filler

def test_no_shipped_certificate_carries_a_filler_value():
    offences = []
    for name, cert in _certificates():
        for path, value in _walk(cert):
            if isinstance(value, str) and value.strip().lower() in FILLER:
                offences.append(f"{name}: {path} = {value!r}")
    assert not offences, (
        "a published example carries a value that looks like content and is none:\n  "
        + "\n  ".join(offences))


# ---------------------------------------------------------------- shape of the issuer block

def test_a_present_build_hash_is_sixteen_lowercase_hex():
    offences = []
    for name, cert in _certificates():
        value = (cert.get("issuer") or {}).get("buildHash")
        if value is None:
            continue
        if not isinstance(value, str) or not BUILD_HASH_FORM.match(value):
            offences.append(f"{name}: buildHash = {value!r}")
    assert not offences, (
        "buildHash must be 16 lowercase hex characters - the emitter derives it from the "
        "assembly's bytes, and anything else is not a fingerprint:\n  " + "\n  ".join(offences))


def test_a_present_version_matches_what_the_emitter_produces():
    offences = []
    for name, cert in _certificates():
        value = (cert.get("issuer") or {}).get("version")
        if value is None:
            continue
        if not isinstance(value, str) or not VERSION_FORM.match(value):
            offences.append(f"{name}: version = {value!r}")
    assert not offences, (
        "version must have the shape IssuerIdentity.VersionOf emits:\n  " + "\n  ".join(offences))


# ---------------------------------------------------------------- the coverage rule

def test_the_published_set_shows_both_a_known_and_an_unknown_issuer():
    """Rule 1 says unknown is omitted, never defaulted. If every example fills those fields in,
    the published artefacts never demonstrate the omission and a reader has only the prose."""
    with_fields, without_fields = [], []
    for name, cert in _certificates():
        issuer = cert.get("issuer") or {}
        has = "version" in issuer and "buildHash" in issuer
        (with_fields if has else without_fields).append(name)

    assert with_fields, (
        "no example shows a certificate whose issuer is fully determined - a reader never sees "
        "the normal shape")
    assert without_fields, (
        "no example shows a certificate that OMITS version and buildHash. Rule 1 - unknown is "
        "omitted, never defaulted - is then visible only in the spec, and the shipped artefacts "
        "quietly teach that those fields are always present. Add a clean example that omits them."
    )


def test_an_omitting_example_omits_rather_than_emptying():
    """Omission means the key is absent. A present-but-empty field is the defaulting rule 1
    forbids, wearing a different hat."""
    for name, cert in _certificates():
        issuer = cert.get("issuer") or {}
        for field in ("version", "buildHash"):
            if field in issuer:
                assert issuer[field], f"{name}: issuer.{field} is present but empty - omit the key"


# ---------------------------------------------------------------- unmistakably synthetic

def test_every_example_announces_itself_as_fabricated():
    """The old `buildHash: "example"` had one virtue worth keeping: nobody could mistake it for
    evidence. The realistic form loses that, so the signal moves somewhere its name does not
    promise evidence - the trader's self-chosen alias - rather than being smuggled into a field
    called buildHash."""
    for name, cert in _certificates():
        alias = (cert.get("subject") or {}).get("alias", "")
        assert alias.lower().startswith("example"), (
            f"{name}: subject.alias is {alias!r}. Every shipped example must say so in a field "
            f"whose name promises nothing, so it cannot be mistaken for a real session.")


def test_no_example_claims_an_external_anchor():
    """An anchor is a third party's attestation. A fabricated one would be the most misleading
    thing this directory could contain."""
    for name, cert in _certificates():
        assert not cert.get("anchors"), f"{name} carries anchors; a synthetic example must not"
        assert cert.get("trustLevel") == "L1", f"{name} claims {cert.get('trustLevel')} with no anchor"


#: Blocks whose contents the EMITTER asserts about the session, rather than the verifier
#: recomputing them from the ledger. Every string leaf in these is a fabricated claim in an
#: example and must be documented; `claims` is excluded because the verifier derives it.
ASSERTED_BLOCKS = ("issuer", "subject", "commitment", "session")

HEX16 = re.compile(r"^[0-9a-f]{16}$")


#: The heading the fabrication table lives under. The README also holds a "one lesson per file"
#: table whose first column is filenames, and parsing both reported every filename as a field.
FABRICATION_HEADING = "## What is fabricated, and how you recognise it"


def _fabrication_rows() -> list:
    """(field path, value cell) for every row of the fabrication table, and no other table."""
    text = (EX / "README.md").read_text(encoding="utf-8")
    assert FABRICATION_HEADING in text, (
        f"the README no longer has a {FABRICATION_HEADING!r} section; these tests read it")

    section = text.split(FABRICATION_HEADING, 1)[1]
    section = re.split(r"^## ", section, maxsplit=1, flags=re.MULTILINE)[0]

    rows = []
    for line in section.splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 3:
            continue
        head = cells[0]
        if head.startswith("`") and head.endswith("`"):
            rows.append((head.strip("`"), cells[1]))
    assert rows, "the fabrication table has no rows"
    return rows


def _readme_table_fields() -> set:
    return {field for field, _ in _fabrication_rows()}


def _fields_the_examples_assert() -> set:
    """Every fabricated claim in the shipped set: string leaves in the emitter-asserted blocks,
    plus any long hex value anywhere, plus `anchors`."""
    required = set()
    for _, cert in _certificates():
        for path, value in _walk(cert):
            base = re.sub(r"\[\d+\]", "", path)
            top = base.split(".")[0]
            if not isinstance(value, str):
                continue
            if top in ASSERTED_BLOCKS or re.fullmatch(r"[0-9a-f]{16,}", value):
                required.add(base)
        if "anchors" in cert:
            required.add("anchors")
    return required


def test_the_readme_table_documents_every_fabricated_field():
    """The anti-drift rule for the documentation itself. Add a fifth example with a new invented
    field and forget to describe it, and this goes red rather than shipping an undocumented
    value that a reader has no way to tell from evidence."""
    documented = _readme_table_fields()
    required = _fields_the_examples_assert()
    missing = sorted(required - documented)
    assert not missing, (
        "these fields are asserted by a shipped example and have no row in the README's "
        "fabrication table, so a reader cannot tell them from evidence:\n  "
        + "\n  ".join(missing))


def _values_at(node, path: str) -> list:
    """Every value reachable by a dotted path, descending through lists."""
    current = [node]
    for part in path.split("."):
        nxt = []
        for item in current:
            if isinstance(item, list):
                item = {k: v for d in item if isinstance(d, dict) for k, v in d.items()}
            if isinstance(item, dict) and part in item:
                nxt.append(item[part])
        current = nxt
        if not current:
            return []
    out = []
    for item in current:
        out.extend(item if isinstance(item, list) else [item])
    return out


def _path_exists(cert, path: str) -> bool:
    node = cert
    for part in path.split("."):
        if isinstance(node, list):
            node = {k: v for d in node if isinstance(d, dict) for k, v in d.items()}
        if not isinstance(node, dict) or part not in node:
            return False
        node = node[part]
    return True


def test_every_hash_quoted_in_a_row_belongs_to_that_rows_own_field():
    """Attribution, not just existence.

    The weak version of this test asked whether a quoted hash appeared ANYWHERE in the example
    set. That passes a table which says `subject.accounts` = X where X is really some other
    field's value: every hash exists, every row is wrong. A reader trusts rows, not sets.

    A quoted token matches when it equals a value at that row's own path, or prefixes one - the
    table legitimately quotes the first 16 characters of a padded sealHash.
    """
    certificates = _certificates()
    offences = []
    for field, cell in _fabrication_rows():
        for token in re.findall(r"`([0-9a-f]{16})`", cell):
            found_here = any(
                isinstance(v, str) and (v == token or v.startswith(token))
                for _, cert in certificates
                for v in _values_at(cert, field))
            if found_here:
                continue
            elsewhere = sorted({
                other for _, cert in certificates
                for other, v in _walk(cert)
                if isinstance(v, str) and (v == token or v.startswith(token))})
            offences.append(
                f"{field}: the table quotes {token}, which is not a value of that field"
                + (f" - it belongs to {', '.join(elsewhere)}" if elsewhere
                   else " and appears nowhere in the examples"))
    assert not offences, "the fabrication table misattributes a value:\n  " + "\n  ".join(offences)


def test_the_readme_table_has_no_stale_rows():
    """The mirror of the coverage test. If a field disappears from the examples, its row keeps
    describing something a reader will look for and not find - documentation that has quietly
    become fiction, which is the same failure as an undocumented field wearing the other face.
    """
    certificates = _certificates()
    stale = [field for field, _ in _fabrication_rows()
             if not any(_path_exists(cert, field) for _, cert in certificates)]
    assert not stale, (
        "the fabrication table has rows for fields no example carries any more:\n  "
        + "\n  ".join(sorted(stale)))


def test_the_documented_build_hash_preimage_actually_produces_it():
    """The tell has to be recomputable, or it is only a claim. This runs the README's own
    instruction and compares the result with what the files carry."""
    import hashlib

    text = (EX / "README.md").read_text(encoding="utf-8")
    preimage = "deadman-guardian example build, not a real assembly"
    assert preimage in text, "the README no longer states the buildHash preimage"

    expected = hashlib.sha256(preimage.encode("utf-8")).hexdigest()[:16]
    assert f"`{expected}`" in text or expected in text, (
        f"the README states a preimage that does not produce the hash it shows ({expected})")

    carried = {(c.get("issuer") or {}).get("buildHash")
               for _, c in _certificates()} - {None}
    assert carried == {expected}, (
        f"the examples carry {sorted(carried)} but the documented preimage yields {expected}")


def test_the_examples_readme_exists_and_says_they_are_synthetic():
    readme = EX / "README.md"
    assert readme.exists(), "deadman/examples/certificate/README.md is missing"
    text = readme.read_text(encoding="utf-8").lower()
    assert "synthetic" in text or "fabricated" in text
    assert "not a real" in text or "no real" in text
