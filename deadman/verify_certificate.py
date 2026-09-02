"""Independent verifier for a Verifiable Session Certificate (CERT_SPEC v0.2).

Run it without knowing anything about this project:

    pip install deadman-kit
    python -m deadman.verify_certificate certificate.json ledger.jsonl

It answers one question: **does this certificate survive its own evidence?**

Three things about how it answers, because they are the whole point:

1. It **recomputes every claim from the ledger events** and ignores what the certificate
   asserts. `limitRespected` is derived by counting LIMIT_BREACHED, never by reading the
   boolean. A signature proves origin, not truth (SPEC §3b), so nothing here trusts one.
2. It reports the trust layer it actually **reached**, not the one the certificate declares.
   Declaring higher than reached is a contradiction, not a warning (SPEC §A.3).
3. It prints what it could **not** verify, always, including on success. A verifier that can
   only say OK is a rubber stamp (SPEC §5).

Exit codes (SPEC §A.5 C18) - the two failures are different facts and are kept apart:

    0  verified at the layer reported
    1  CONTRADICTED - something in the certificate does not survive the ledger
    2  UNEVALUABLE  - could not look (unreadable file, invalid JSON, missing range)

Zero runtime dependencies. Signature checking (L3) needs the optional extra
`pip install deadman-kit[verify-sig]`; without it the verifier reports the signature as
NOT_VERIFIED and degrades to L2 - never to "valid" (SPEC §A.4). That import is done through
importlib on purpose: `tests/test_g12_clock_and_paths.py::test_package_imports_only_stdlib_and_itself`
walks the AST for import statements anywhere in a file, including inside functions, and a
literal `import cryptography` would break the package's zero-dependency guarantee.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Sequence

__all__ = [
    "verify_certificate", "verify_series", "CertReport", "Finding", "Dialect",
    "DIALECTS", "REQUIRED_LIMITATIONS", "canonical_json",
    "EXIT_OK", "EXIT_CONTRADICTED", "EXIT_UNEVALUABLE", "main",
]

EXIT_OK = 0
EXIT_CONTRADICTED = 1
EXIT_UNEVALUABLE = 2

#: Where the full set of worked examples lives. ABSOLUTE on purpose: this string is
#: printed by --example and also appears in the README, whose relative links do not
#: resolve from the PyPI project page.
REPO_EXAMPLES = "https://github.com/Roberto9210/deadman/tree/main/deadman/examples/certificate"


def canonical_json(obj: Mapping[str, Any]) -> bytes:
    """The one canonicalisation both ledger dialects share: ordinal-sorted keys, no
    whitespace, UTF-8. Verified against 67 real GuardianCore entries."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _human_ms(ms: Optional[int]) -> str:
    """Durations a person reads without counting zeros. Seconds matter here: an ordinary restart
    lasts seconds and a gap of hours is the shape that matters, so the units must make the two
    impossible to confuse at a glance."""
    if ms is None:
        return "unknown"
    if ms < 1000:
        return f"{ms} ms"
    seconds = ms / 1000.0
    if seconds < 90:
        return f"{seconds:.0f} s"
    minutes = seconds / 60.0
    if minutes < 90:
        return f"{minutes:.0f} min"
    hours = int(minutes // 60)
    return f"{hours} h {int(minutes - hours * 60):02d} min"


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# --------------------------------------------------------------------------------------
# Ledger dialects (SPEC §A.1)
#
# Two producers write hash-chained ledgers with the SAME canonicalisation and DIFFERENT
# entry schemas. The certificate DECLARES which one it covers and the verifier fails closed
# if the file does not match. Sniffing the shape would let a forger hand over a ledger built
# in whichever schema suits the lie.
# --------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Dialect:
    name: str
    f_seq: str
    f_ts: str
    f_event: str
    f_payload: str
    f_prev: str
    genesis: str
    required: tuple[str, ...]
    #: Builds the exact object that was hashed. The two producers differ here, and
    #: "just drop the hash field" is only correct for one of them.
    body: Callable[[Mapping[str, Any]], dict]

    def hash_of(self, entry: Mapping[str, Any]) -> str:
        return _sha256_hex(canonical_json(self.body(entry)))


def _guardian_body(e: Mapping[str, Any]) -> dict:
    # GuardianCore hashes everything it writes except the hash itself (Ledger.cs::Unhashed).
    return {k: v for k, v in e.items() if k != "hash"}


def _kit_body(e: Mapping[str, Any]) -> dict:
    # deadman-kit hashes everything except `hash` and `sig` (ledger.py::HASH_EXCLUDED). It used
    # to name seven fields, which left any OTHER top-level field outside the hash entirely -
    # measured, a field injected there survived verification untouched. `sig` stays out because
    # it signs the hash and cannot be inside it; that exclusion is forced by ordering, not chosen.
    return {k: v for k, v in e.items() if k not in ("hash", "sig")}


GUARDIAN_CORE_V1 = Dialect(
    name="guardian-core-v1",
    f_seq="seq", f_ts="tsUtc", f_event="event", f_payload="payload", f_prev="prev",
    genesis="genesis",
    required=("seq", "tsUtc", "event", "schemaVersion", "payload", "prev", "hash"),
    body=_guardian_body,
)

DEADMAN_KIT_V1 = Dialect(
    name="deadman-kit-v1",
    f_seq="seq", f_ts="ts_utc", f_event="kind", f_payload="payload", f_prev="prev_hash",
    genesis="0" * 64,
    required=("schema_version", "seq", "ts_utc", "kind", "actor", "payload", "prev_hash", "hash"),
    body=_kit_body,
)

DIALECTS: dict[str, Dialect] = {d.name: d for d in (GUARDIAN_CORE_V1, DEADMAN_KIT_V1)}


# --------------------------------------------------------------------------------------
# The limitations the certificate must carry verbatim (SPEC §2, guarantee C10)
#
# The canonical text lives HERE, in the public verifier, not in the private emitter. That is
# deliberate: the judge holds the wording, and an emitter that waters it down fails C10.
# --------------------------------------------------------------------------------------

REQUIRED_LIMITATIONS: tuple[str, ...] = (
    "This does not say the trader makes money. It is not a track record of profitability.",
    "This does not say the trader did not trade elsewhere. The guardian sees one platform "
    "and the configured accounts, and nothing else.",
    "This does not say the software was not bypassed before it started. Whoever removes the "
    "add-on with the platform closed does not appear; the gap appears, not the act.",
    "This is not an audit. Nobody inspected this trader. It is a machine's signed assertion "
    "about a record that machine kept.",
)


# --------------------------------------------------------------------------------------
# CERT_SPEC rule 5, checked by the receiver
#
# "A field that looks like evidence and is not is worse than an absent field."
#
# The rule's own test is *what does it distinguish?* - if two things that should differ produce
# the same value, or two identical things produce different ones, the field does not measure what
# its name says and must be omitted or renamed. That question cannot be answered mechanically in
# general. What CAN be answered from a single document is its sharpest special case: a field whose
# NAME promises a specific form, carrying a value that cannot possibly have that form.
#
# `"buildHash": "example"` is the case that produced the rule. A word is not a fingerprint; it
# distinguishes nothing; and nothing in the shipped verifier would have told a recipient so.
# --------------------------------------------------------------------------------------

#: WHERE RULE 5 APPLIES, and it is decided by PROVENANCE rather than by the field's name.
#:
#: A producer writing "unknown" is papering over a hole. A person writing "unknown" is telling you
#: their name. It is the same string and they are different things, and what separates them is
#: where it came from. There is a third provenance, and it is the one that caused the trouble:
#: a value COPIED VERBATIM out of the ledger. Judging the shape of a copied event name is judging
#: somebody else's vocabulary, which changes without telling us.
#:
#: The general rule, because it will apply again:
#:
#:      COMPARISON AND SHAPE ARE ALTERNATIVE VERIFICATIONS, NOT COMPLEMENTARY.
#:
#: If a field can be compared against its source, compare it - and then shape-checking it can only
#: produce false positives, because its shape is decided by someone else. If it cannot be compared,
#: shape is all that is left.
#:
#: Measured over 144 adversarially generated event names (every suffix these checks react to, x
#: every filler word, x the prefixes a real vocabulary produces): before this, 31 failed as a
#: `reasons` key and 44 as a `triggerEvent` value. None of those names exists today; all of them
#: are names somebody could choose tomorrow.

#: Filled by a PERSON. Their word is their word - rule 5 does not apply. The risk of exempting
#: them is nil: this check only ever refuses, so it cannot be tricked into approving anything.
PERSON_SUPPLIED = frozenset({"alias"})

#: COPIED VERBATIM from the ledger. Verified by COMPARISON against the evidence, which is strictly
#: stronger than judging its shape - and that comparison is what DEF-2 asks for.
COPIED_FROM_EVIDENCE = frozenset({"triggerEvent", "triggerSeq", "precedingEvent", "precedingSeq"})

#: Names the CERTIFICATE SCHEMA owns, and the only ones whose shape is ours to judge.
#:
#: Inverted on purpose. Before, the promise checks descended into everything and needed the whole
#: event vocabulary to stay clear of four suffixes to be safe; the keys of `reasons` and of
#: `clockAnomalies.byType` ARE event names, so `CONFIG_HASH` or `DAILY_LOSS` would have accused a
#: certificate over its own integer counter. That failure mode is backwards from the one this file
#: declares 60 lines below ("the cost of a false accusation here is a certificate wrongly refused,
#: so the checks err toward silence"): forgetting to declare a data-keyed container ACCUSED, while
#: forgetting to add a schema name merely stays SILENT. Between two correct fixes, the one whose
#: failure mode matches the calibration the module already declared wins.
PROMISE_BEARING = frozenset({
    "certHash", "previousCertHash", "buildHash", "sealHash", "ledgerHeadHash",
    "armedAtUtc", "sealExpiryUtc", "openedUtc", "expiresAtUtc", "issuedAtUtc", "tsUtc",
    "fromUtc", "toUtc",
    "version",
    "firmDailyLossLimit", "personalDailyLossLimit", "dayLoss",
})


def _leaf_name(path: str) -> str:
    return path.split(".")[-1].split("[")[0]


#: Values that look like content and carry none. Matched as whole values, case-insensitively, so
#: a self-describing alias like "example-trader" passes while a bare "example" does not.
#:
#: Case-insensitive ON PURPOSE, and the alternative was considered and dropped: `TODO`, `TBD` and
#: `XXX` are filler that gets written in capitals, so a case-sensitive match would let all three
#: through. The protection against catching a legitimate value does not come from the comparison
#: rule - it comes from PROVING NON-COLLISION against the real vocabulary, which is what
#: tests/test_c_rule_five.py sweeps.
DECORATIVE_FILLER = frozenset({
    "example", "test", "sample", "sample-value", "todo", "tbd", "changeme", "placeholder",
    "dummy", "foo", "bar", "baz", "xxx", "n/a", "none", "null", "unknown", "unset",
    "1.0.0.0", "0.0.0.0", "string", "value", "your-value-here", "",
})

_HEXISH = re.compile(r"^[0-9a-f]{16,}$")
_ISO_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?Z$")
_VERSIONISH = re.compile(r"^\d+\.\d+\.\d+(\.\d+)?([-+][0-9A-Za-z.-]+)*$")
_MONEY = re.compile(r"^-?\d+\.\d{2}$")


def _promise_violations(node: Any, path: str = "") -> list:
    """Leaves whose key promises a form their value cannot have.

    Deliberately narrow. Only names that promise something specific and checkable are examined -
    a free-text `alias` or a `tool` name promises nothing and is left alone. The cost of a false
    accusation here is a certificate wrongly refused, so the checks err toward silence.
    """
    out = []
    if isinstance(node, dict):
        for k, v in node.items():
            out.extend(_promise_violations(v, f"{path}.{k}" if path else k))
        return out
    if isinstance(node, list):
        for i, v in enumerate(node):
            out.extend(_promise_violations(v, f"{path}[{i}]"))
        return out

    if node is None or path == "":
        return out
    key = _leaf_name(path)
    if key not in PROMISE_BEARING:
        return out          # not a name this schema owns: its shape is not ours to judge
    low = key.lower()

    def fail(promise: str, why: str):
        out.append((path, node, promise, why))

    if low.endswith("hash"):
        if not isinstance(node, str) or not _HEXISH.match(node):
            fail("a cryptographic hash",
                 "a hash is lowercase hex of at least 16 characters; this cannot be one, so the "
                 "field distinguishes nothing")
    elif low.endswith("utc") or low.endswith("atutc"):
        if not isinstance(node, str) or not _ISO_UTC.match(node):
            fail("an ISO-8601 UTC timestamp",
                 "the name promises a point in time and the value is not one")
    elif low == "version":
        if not isinstance(node, str) or not _VERSIONISH.match(node):
            fail("a version",
                 "the name promises something that identifies a build, and this does not")
    elif low.endswith("limit") or low.endswith("loss"):
        if not isinstance(node, str) or not _MONEY.match(node):
            fail("money as a decimal string",
                 "money is a string with exactly two decimals (SPEC section 4); a number or a "
                 "loose string cannot be compared exactly")
    return out


def check_rule_five(cert: Mapping[str, Any]) -> list:
    """Every decorative field a single document can betray, as (code, detail) pairs.

    A recipient runs this without our source, which is the point: the rule is normative in the
    specification, and until it is checkable by the person receiving a certificate it protects
    nobody who matters.
    """
    findings = []

    for path, value in _walk_leaves(cert):
        if _leaf_name(path) in PERSON_SUPPLIED or _leaf_name(path) in COPIED_FROM_EVIDENCE:
            continue        # provenance: not the producer's word, so not the producer's filler
        if isinstance(value, str) and value.strip().lower() in DECORATIVE_FILLER:
            findings.append((
                "DECORATIVE_FIELD",
                f"`{path}` is {value!r} - a filler value that looks like content and carries "
                f"none. SPEC rule 5: a field that looks like evidence and is not is worse than "
                f"an absent field; omit it instead"))

    for path, value, promise, why in _promise_violations(cert):
        findings.append((
            "FIELD_BELIES_ITS_NAME",
            f"`{path}` is named for {promise} but holds {value!r}. {why}"))

    return findings


def _walk_leaves(node: Any, path: str = ""):
    if isinstance(node, dict):
        for k, v in node.items():
            yield from _walk_leaves(v, f"{path}.{k}" if path else k)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from _walk_leaves(v, f"{path}[{i}]")
    else:
        yield path, node


# --------------------------------------------------------------------------------------
# Findings and the report
# --------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Finding:
    code: str
    detail: str

    def __str__(self) -> str:
        return f"{self.code}: {self.detail}"


@dataclass
class CertReport:
    """What the verifier concluded. `contradictions` is the certificate failing against the
    evidence; `unverified` is the verifier being honest about the edges of its own reach."""

    declared_level: Optional[str] = None
    reached_level: Optional[str] = None
    dialect: Optional[str] = None
    entries_read: int = 0
    range_from: Optional[int] = None
    range_to: Optional[int] = None
    chain_ok: bool = False
    broken_seq: Optional[int] = None
    cert_hash_ok: bool = False
    signature_status: str = "ABSENT"
    covered_up_to_seq: Optional[int] = None
    anchors_checked: int = 0
    recomputed: dict = field(default_factory=dict)
    continuity: dict = field(default_factory=dict)
    backwards_time: list = field(default_factory=list)
    contradictions: list[Finding] = field(default_factory=list)
    unverified: list[Finding] = field(default_factory=list)
    unevaluable: list[Finding] = field(default_factory=list)

    @property
    def exit_code(self) -> int:
        if self.unevaluable:
            return EXIT_UNEVALUABLE
        return EXIT_CONTRADICTED if self.contradictions else EXIT_OK

    @property
    def ok(self) -> bool:
        return self.exit_code == EXIT_OK

    def contradict(self, code: str, detail: str) -> None:
        self.contradictions.append(Finding(code, detail))

    def cannot_verify(self, code: str, detail: str) -> None:
        self.unverified.append(Finding(code, detail))

    def cannot_evaluate(self, code: str, detail: str) -> None:
        self.unevaluable.append(Finding(code, detail))

    # -------------------------------------------------------------- continuity
    def _continuity_lines(self) -> list:
        """Seal continuity, and the fixed text that has to travel with it.

        The wording is load-bearing. This is read by a prop firm's risk desk, and every number
        here has an innocent explanation that is also the common one. Nothing may read as an
        accusation, and the normal case must be stated as normal.
        """
        c = self.continuity
        if not c:
            return []

        out = ["", "SEAL CONTINUITY - derived from the ledger by this tool, not claimed by the "
                   "certificate:"]
        if not c.get("supported"):
            out.append(f"  not available: {c['reason']}")
            return out

        coverage = c.get("continuityCoverage")
        if coverage is None and c.get("coverageOmittedBecause"):
            out.append(f"  coverage        not reported: {c['coverageOmittedBecause']}")
        elif coverage is None:
            out.append("  coverage        not computable from this range")
        elif c.get("coverageIsLowerBound"):
            out.append(f"  coverage        at least {coverage * 100:.0f}% of the sealed period - a "
                       f"lower bound, because at least one")
            out.append("                  session has no recorded shutdown and the moment it "
                       "ended is therefore unknown")
        else:
            out.append(f"  coverage        {coverage * 100:.0f}% of the sealed period")
        out.append(f"  process starts  {c.get('processRestarts', 0)} after arming"
                   + (f", {c['uncleanShutdowns']} of them following a session with no recorded "
                      f"clean shutdown" if c.get("uncleanShutdowns") else ""))
        if c.get("uncleanShutdowns"):
            # The only figure here a reader can take as a charge, so it carries the explanation it
            # cannot rule out. A rotated ledger segment that no longer holds the GUARDIAN_STOPPED
            # looks identical to a crash, and so does a range that begins between a shutdown and
            # its restart. Saying that is honest; letting the count imply a crash is not.
            out.append("                  a missing shutdown record is not by itself evidence of "
                       "anything: a crash, a power cut, a")
            out.append("                  ledger rotation that left the record in an earlier "
                       "segment, and a range beginning between a")
            out.append("                  shutdown and its restart all look the same from here, "
                       "and this tool cannot tell them apart")
        if c.get("indeterminateStarts"):
            out.append(f"  undetermined    {c['indeterminateStarts']} further start(s) have "
                       f"nothing at all before them in this record, so they")
            out.append("                  are reported as undetermined rather than counted "
                       "against anyone")

        if c.get("longestGapMs") is not None:
            longest, total = c["longestGapMs"], c.get("unmonitoredMs") or 0
            out.append(f"  time with no guardian running  {_human_ms(total)}"
                       + (f", longest single gap {_human_ms(longest)}" if longest else ""))
        else:
            out.append(f"  time with no guardian running  not derivable: "
                       f"{c.get('durationsOmittedBecause')}")

        basis = c.get("sealExpiryBasis")
        if basis == "monotonic":
            out.append("  the day ended on a monotonic counter, which nobody can adjust: the "
                       "process ran without interruption from arming until the seal expired")
        elif not c.get("dayClosed"):
            out.append("  the session had not closed within the certified range, so nothing is "
                       "said about how it ended")

        if self.backwards_time:
            first = self.backwards_time[0]
            out.append("")
            out.append(f"  NOTE  {len(self.backwards_time)} timestamp(s) move BACKWARDS between "
                       f"consecutive entries, first at seq {first['fromSeq']} -> {first['toSeq']} "
                       f"by {_human_ms(first['byMs'])}.")
            out.append("        Entries are hash-chained, so this cannot be edited out quietly. "
                       "It means the machine's clock moved during the session; it does not by "
                       "itself say why, and daylight-saving changes are handled in UTC and do "
                       "not produce it.")

        out.append("")
        out.append("  Restarts happen for Windows updates, ordinary closes and crashes. These "
                   "lines describe what evidence")
        out.append("  decided the day, not that anyone did anything. Ending on the WALL CLOCK is "
                   "the normal case - it is what")
        out.append("  every trader who closes the platform at the end of the day produces, and "
                   "it is not a finding. A monotonic")
        out.append("  ending is a positive guarantee when present and its absence means nothing "
                   "(guardian SPEC section 17.2).")
        out.append("  COVERAGE AND THE MINUTES MEASURE DIFFERENT THINGS, and a low coverage does "
                   "NOT mean the guardian was")
        out.append("  absent. Coverage is monotonic continuity, which a single restart ends for "
                   "the whole remaining day even")
        out.append("  if the process is back in two seconds - so a day with six brief restarts "
                   "reads near 0% while the guardian")
        out.append("  was running throughout. The minutes are the only figure that reports "
                   "ABSENCE. Read them together: 0.2%")
        out.append("  coverage beside three minutes of absence describes a day that was watched "
                   "almost continuously but whose")
        out.append("  clock could not be vouched for after the first restart.")
        out.append("  Coverage is derived from the ledger's own timestamps - the same clock this "
                   "could not vouch for - so it")
        out.append("  proves nothing on its own. What it does is make visible the condition "
                   "under which that documented gap")
        out.append("  is exploitable, instead of leaving it buried in a file nobody opens.")
        return out

    # -------------------------------------------------------------- rendering
    def render(self) -> str:
        L: list[str] = []
        add = L.append
        add("deadman-kit - verifiable session certificate")
        add("=" * 62)

        if self.unevaluable:
            add("")
            add("COULD NOT EVALUATE - this is not a verdict on the certificate.")
            for f in self.unevaluable:
                add(f"  - {f}")
            add("")
            add("RESULT: UNEVALUABLE (exit 2). Nothing was proved and nothing was disproved.")
            return "\n".join(L)

        add(f"ledger dialect  : {self.dialect}  ({self.entries_read} entries read)")
        if self.range_from is not None:
            add(f"declared range  : seq {self.range_from}..{self.range_to}")
        add("")

        chain = "OK" if self.chain_ok else f"BROKEN at seq {self.broken_seq}"
        add(f"  chain         {chain}")
        add(f"  certHash      {'matches' if self.cert_hash_ok else 'DOES NOT MATCH'}")
        add(f"  claims        {len(self.recomputed)} recomputed from events")
        add(f"  anchors       {self.anchors_checked} checked"
            + (f", covered up to seq {self.covered_up_to_seq}" if self.covered_up_to_seq else ""))
        add(f"  signature     {self.signature_status}")
        if self.recomputed.get("limitStatus") == "undetermined":
            add("  limit         UNDETERMINED - a fail-closed episode is still open with no\n                              breach recorded, so the guardian could not see. This is NOT a\n                              statement that the trader went past a limit")
        add("")
        add(f"  DECLARED      {self.declared_level}")
        add(f"  REACHED       {self.reached_level or 'none'}")

        if self.contradictions:
            add("")
            add("CONTRADICTIONS - the certificate does not survive its own evidence:")
            for f in self.contradictions:
                add(f"  - {f}")

        L.extend(self._continuity_lines())

        add("")
        add("COULD NOT VERIFY - true even when everything above passes:")
        for f in self.unverified:
            add(f"  - {f}")

        add("")
        if self.contradictions:
            add(f"RESULT: CONTRADICTED (exit 1). {len(self.contradictions)} finding(s).")
        else:
            # L1 is where a run lands when nothing external was supplied, so the headline
            # must not read as a grade. One word, because the format is quoted elsewhere.
            floor = ", THE FLOOR LAYER" if self.reached_level == "L1" else ""
            add(f"RESULT: VERIFIED at {self.reached_level}{floor} (exit 0).")
        return "\n".join(L)


# --------------------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------------------

def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_ledger_lines(path: Path) -> list[dict]:
    out: list[dict] = []
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except ValueError as e:
            raise ValueError(f"ledger line {n} is not valid JSON: {e}") from e
        if not isinstance(obj, dict):
            raise ValueError(f"ledger line {n} is not a JSON object")
        out.append(obj)
    return out


# --------------------------------------------------------------------------------------
# Chain
# --------------------------------------------------------------------------------------

def _check_dialect(entries: Sequence[Mapping[str, Any]], dialect: Dialect) -> Optional[str]:
    """Fail closed on a declared dialect the file does not match (C17). Returns a reason or None."""
    if not entries:
        return "the ledger has no entries, so the declared dialect cannot be confirmed"

    # Every entry, not just the first: a ledger with one dialect on line 1 and another further
    # down would otherwise pass this check and fail later as a confusing chain break.
    for i, e in enumerate(entries):
        missing = [f for f in dialect.required if f not in e]
        if not missing:
            continue
        where = f"entry {i + 1}" + (f" (seq {e[dialect.f_seq]})" if dialect.f_seq in e else "")
        other = next((d for d in DIALECTS.values()
                      if d.name != dialect.name and all(f in e for f in d.required)), None)
        if other is not None:
            return (f"certificate declares '{dialect.name}' but {where} is written in "
                    f"'{other.name}' (missing {missing})")
        return f"certificate declares '{dialect.name}' but {where} lacks {missing}"
    return None


def _verify_chain(entries: Sequence[Mapping[str, Any]], dialect: Dialect,
                  from_seq: int, to_seq: int) -> tuple[bool, Optional[int]]:
    """Recompute the hash chain over the declared range. Returns (ok, first_broken_seq)."""
    prev: Optional[str] = None
    seen = 0
    for e in entries:
        seq = e.get(dialect.f_seq)
        if not isinstance(seq, int) or seq < from_seq or seq > to_seq:
            continue
        seen += 1
        expected_prev = dialect.genesis if seq == 1 else prev
        if expected_prev is not None and e.get(dialect.f_prev) != expected_prev:
            return False, seq
        try:
            recomputed = dialect.hash_of(e)
        except KeyError:
            return False, seq
        if recomputed != e.get("hash"):
            return False, seq
        prev = e["hash"]
    if seen == 0:
        return False, from_seq
    return True, None


# --------------------------------------------------------------------------------------
# Claim recomputation (SPEC §A.2) - the heart of the thing
# --------------------------------------------------------------------------------------

_MISSING = object()

_BOUNDARY = ("FAIL_CLOSED_ENTERED", "FAIL_CLOSED_CLEARED")

#: Events that are TESTIMONY ABOUT A PERSON, not evidence about the account. Reserved prefix.
#:
#: An acknowledgement says "somebody saw this". It never says "therefore this does not count", and
#: no event may ever mean that. What it must also never do is become part of the machine's story:
#: measured, an acknowledgement landing inside a fail-closed episode was counted among that
#: episode's `reasons`, and one landing immediately before it was published as its cause. A human
#: reading a certificate would have found "the guardian went blind. Cause: a person looked at the
#: warning."
#:
#: So the exclusion is STRUCTURAL rather than careful: no HUMAN_* event is an input to any
#: recomputed claim. It changes no number.
HUMAN_EVENT_PREFIX = "HUMAN_"


def _is_human(name: Any) -> bool:
    return isinstance(name, str) and name.startswith(HUMAN_EVENT_PREFIX)

#: Events whose absence from a certificate changes what it says about the trader. Used only to
#: describe what a declared range leaves out - never to recompute a claim.
_MATERIAL = (
    "LIMIT_BREACHED", "ORDER_REJECTED_LOCKED", "CONFIG_CHANGE_REJECTED", "FAIL_CLOSED_ENTERED",
    "CLOCK_ANOMALY", "CLOCK_SUSPECT", "LOCKOUT_INCOMPLETE", "SEAL_MISMATCH", "CONFIG_TAMPERED",
    "PNL_DISAGREEMENT", "LEDGER_VERIFY_FAILED", "STATE_CORRUPT",
)


def _events_in_range(entries: Sequence[Mapping[str, Any]], dialect: Dialect,
                     from_seq: int, to_seq: int) -> list[Mapping[str, Any]]:
    rows = [e for e in entries
            if isinstance(e.get(dialect.f_seq), int) and from_seq <= e[dialect.f_seq] <= to_seq]
    rows.sort(key=lambda e: e[dialect.f_seq])
    return rows


def _check_range_covers_its_day(cert: Mapping[str, Any], entries: Sequence[Mapping[str, Any]],
                                dialect: Dialect, from_seq: int, to_seq: int,
                                rep: "CertReport") -> None:
    """The most dangerous lie the format allows, and it took an attack to find it.

    Every claim is recomputed over the DECLARED range, so a certificate that simply declares a
    shorter range hides whatever falls outside it. Truncating at the entry before LIMIT_BREACHED
    produces `limitRespected: true` that recomputes perfectly and verifies clean.

    What makes it detectable is that the certificate also names a DAY. If the ledger holds that
    day's DAY_OPENED before the range starts, or its DAY_CLOSED after the range ends, then the
    document does not cover the session it claims to describe, and says so by omission.

    When the day never closed - an export taken mid-session, which is the normal case - there is
    nothing to anchor against, and the verifier says exactly that instead of pretending."""
    day = (cert.get("session") or {}).get("dayKey")
    ev, seqf = dialect.f_event, dialect.f_seq

    def day_of(e: Mapping[str, Any]) -> Any:
        return (e.get(dialect.f_payload) or {}).get("dayKey")

    outside_before, outside_after = [], []
    for e in entries:
        seq = e.get(seqf)
        if not isinstance(seq, int):
            continue
        if seq < from_seq:
            outside_before.append(e)
        elif seq > to_seq:
            outside_after.append(e)

    # SEVERITY FOLLOWS THE HARM, NOT THE PRESENCE OF A FIELD.
    #
    # `session.dayKey` used to gate this whole check: without it nothing ran, and nothing said so.
    # Measured on the repository's own `certificate-truncated.json` - the shipped example of "the
    # most dangerous lie the format allows" - removing `dayKey` took it from RANGE_TRUNCATED at
    # exit 1 down to exit 0. Not silence exactly: `POST_RANGE_MATERIAL_EVENTS` still fired and
    # still named the hidden events, but as `cannot_verify`. A DOWNGRADE IS WORSE THAN SILENCE: a
    # reader files "could not verify" as inconclusive, and it was conclusive and ugly.
    #
    # AND A SEVERITY THAT DEPENDS ON A FIELD BEING PRESENT CAN BE BOUGHT BY OMITTING DATA. Nobody
    # has to forge anything; it is enough not to write a key.
    #
    # So the harm is established first, and `dayKey` only makes the anchor more precise.
    hidden = [e for e in outside_before + outside_after if e.get(ev) in _MATERIAL]

    # A GUARDIAN_STARTED is not material in itself - ordinary restarts happen constantly and
    # flagging them would make every honest early export a contradiction. An ORPHANED one is:
    # it is the evidence of an ungraceful shutdown, and excluding it from the range is exactly
    # how that evidence would be dropped from the continuity block.
    # ...and only when it was cut off the FRONT. A restart that happened after the export
    # is not hidden by the certificate, it merely postdates it - treating those as
    # contradictions would call every honest mid-session export a liar, which is the same
    # calibration mistake this check was written to avoid in the first place.
    hidden += [e for e in outside_before
               if e.get(ev) == "GUARDIAN_STARTED"
               and _preceded_by_clean_stop(entries, dialect, e) is False]

    if day is not None:
        opened = [e for e in outside_before if e.get(ev) == "DAY_OPENED" and day_of(e) == day]
        closed = [e for e in outside_after if e.get(ev) == "DAY_CLOSED" and day_of(e) == day]
        edge = closed[0] if closed else (opened[0] if opened else None)
        where = ("" if edge is None else
                 ("that day's DAY_CLOSED is at seq %s, past the declared range" % edge[seqf]
                  if closed else
                  "that day's DAY_OPENED is at seq %s, before the declared range" % edge[seqf]))
        subject = f"the certificate is for {day} but"
    else:
        # No declared day, so no day to match against. What can still be established is that a
        # SESSION CLOSED past the range: a DAY_CLOSED after `to_seq` means the record kept going
        # and ended, so the range stops short of a session that finished.
        #
        # ANCHORED ON A CLOSE THAT HAPPENED, NOT ON THE ABSENCE OF ONE. The instruction was
        # "material events outside the range are a contradiction whether or not dayKey is there";
        # applied unconditionally that would charge every honest mid-session export, which has
        # material events after it precisely because the session was still running. That is the
        # harm class this whole file has spent its time removing, so the anchor stays: a session
        # that demonstrably ENDED past the declared range.
        closed = [e for e in outside_after if e.get(ev) == "DAY_CLOSED"]
        edge = closed[0] if closed else None
        where = ("" if edge is None else
                 "a DAY_CLOSED sits at seq %s, past the declared range" % edge[seqf])
        subject = "the certificate names no day, and"
        rep.cannot_verify(
            "SCOPE_MISSING",
            "the certificate carries no `session.dayKey`, so the session-coverage check could not "
            "be anchored to the day it describes. This is NOT the same as the check passing: it "
            "did not run. What was still checked is below, from the ledger alone")

    if edge is not None:
        if hidden:
            names = sorted({str(e.get(ev)) for e in hidden})
            rep.contradict("RANGE_TRUNCATED",
                           f"{subject} {where} {from_seq}..{to_seq}, and {len(hidden)} material "
                           f"event(s) fall outside it ({', '.join(names)}) - the range excludes "
                           f"part of the session it claims to describe")
        else:
            rep.cannot_verify("SESSION_NOT_FULLY_COVERED",
                              f"{subject} {where} {from_seq}..{to_seq}: this is part of that "
                              f"session, not all of it. Nothing material sits outside the range, "
                              f"so nothing is being hidden - but for a complete day, export again "
                              f"after the session closes")
        return

    material_after = [e for e in outside_after if e.get(ev) in _MATERIAL]
    if material_after:
        names = sorted({str(e.get(ev)) for e in material_after})
        # The reason is stated CORRECTLY. This message used to say "with no DAY_CLOSED for this
        # session" in both cases, which was false whenever the real cause was that the certificate
        # named no day at all - a message explaining a gap with the wrong cause, which is the
        # defect this verifier keeps finding in other people's artefacts.
        why = ("this certificate names no day, so no session boundary could be matched"
               if day is None else "no DAY_CLOSED for this session appears after the range")
        rep.cannot_verify("POST_RANGE_MATERIAL_EVENTS",
                          f"{len(material_after)} event(s) after the declared range are of a kind "
                          f"that changes what a certificate says ({', '.join(names)}); {why}, so "
                          f"the verifier cannot tell an export taken mid-session from a range "
                          f"truncated to exclude them - ask for a certificate covering the closed "
                          f"session")


#: THE VOCABULARY THIS VERSION KNOWS, per dialect.
#:
#: An event name outside these is reported - `cannot_verify`, never a refusal. The three ways a
#: verifier can meet something it does not know are all defensible and the choice is a product
#: one, so it was made explicitly:
#:
#:   REJECTING is catastrophic. An old verifier would declare a legitimate ledger invalid, and one
#:   future event type would invalidate every certificate already issued.
#:
#:   IGNORING an event is a silent lie: it says *fine* about a record containing things it did not
#:   understand. (Ignoring an unknown FIELD is different and is what happens - safe only because
#:   the hashed body is now a blocklist, so an unknown field is inside the signature. See
#:   ledger.py::HASH_EXCLUDED.)
#:
#:   MARKING says *I verified what I could and there is content I do not understand*, which is the
#:   only honest one and the same shape as everything else here: the absence speaks.
#:
#: Declared as a list, so §5.7 applies: A LEXICAL LIST IS TESTED AGAINST THE REAL VOCABULARY. The
#: sweep is in tests/test_c_certificate.py and asserts this fires on nothing a real ledger holds.
#: `HUMAN_*` is known BY PREFIX rather than by name - the point of the prefix is that the verifier
#: knows exactly what to do with those without being told each one (nothing: they are testimony
#: about a person, never an input to a claim).
#:
#: The kit's list is written out instead of imported: this module imports nothing from the package
#: on purpose, so a recipient can run the single file. `test_the_kit_vocabulary_here_matches_the
#: _kit_itself` is what stops the copy drifting.
KNOWN_EVENTS: dict[str, frozenset] = {
    "guardian-core-v1": frozenset({
        "GUARDIAN_STARTED", "GUARDIAN_STOPPED", "CONFIG_LOADED", "CONFIG_CHANGE_REJECTED",
        "CONFIG_TAMPERED", "ARMED", "DISARMED", "SEAL_CREATED", "SEAL_EXPIRED", "SEAL_MISMATCH",
        "DAY_OPENED", "DAY_CLOSED", "FAIL_CLOSED_ENTERED", "FAIL_CLOSED_CLEARED",
        "ACCOUNT_UNKNOWN", "PNL_CHECKPOINT", "PNL_DISAGREEMENT", "LIMIT_BREACHED",
        "ORDER_REJECTED_LOCKED", "ORDERS_CANCELLED", "FLATTEN_REQUESTED", "FLATTEN_VERIFIED",
        "LOCKOUT_INCOMPLETE", "CLOCK_ANOMALY", "CLOCK_SUSPECT", "LEDGER_VERIFY_FAILED",
        "STATE_CORRUPT",
    }),
    "deadman-kit-v1": frozenset({
        "ANCHOR_PUBLISHED", "ANCHOR_FAILED", "ANCHOR_STALE", "ANCHOR_RECOVERED", "KILL_ENGAGED",
        "KILL_RELEASED", "HALT_SET", "HALT_CLEARED", "INTENT_DENIED", "ORDER_SENT", "FILL",
        "PARTIAL_FILL", "NO_FILL_CANCELED", "UNKNOWN_STATE", "RECONCILE_REPORT",
        "DAILY_STATS_RESET", "LEDGER_ROTATED", "CONCURRENT_WRITER_DETECTED", "USER_NOTE",
    }),
}


def unknown_event_kinds(rows: Sequence[Mapping[str, Any]], dialect: Dialect) -> list[str]:
    """Distinct event names this version has no rule for. Sorted, deduplicated, named once.

    Once, because a line repeated for every occurrence is how a warning becomes wallpaper."""
    known = KNOWN_EVENTS.get(dialect.name, frozenset())
    seen = {r.get(dialect.f_event) for r in rows}
    return sorted(str(n) for n in seen
                  if isinstance(n, str) and n not in known and not _is_human(n))


#: A BOUND IS ONLY WORTH PUBLISHING WHEN IT CONSTRAINS.
#:
#: The general rule, written here because it will apply again: a bound is information when the
#: interval it leaves open is small. When that interval is almost the whole possible range, the
#: number does not measure - it only suggests. And a reader anchors on the figure, not on the
#: label attached to it: "at least 3%" is read as 3%, however carefully it is qualified, even
#: when the truth might be 99%.
#:
#: So a coverage lower bound is published only at or above this threshold, and omitted with its
#: reason below it - the same treatment the gap durations already get. This is the same inversion
#: applied to sealExpiryBasis: state the thing when it is a guarantee, say nothing when it is not.
#:
#: 0.90 is chosen because it is the point where the bound still excludes the attack it exists to
#: make visible. At 90% the unaccounted stretch is at most a tenth of the sealed period - under an
#: hour on a typical nine-hour session - which is too short to hold the close-move-reopen shape,
#: because moving the clock forward makes the resulting gap MEASURE long. Below that the open
#: interval is wide enough to contain almost anything, and the number stops constraining.
COVERAGE_BOUND_PUBLISHABLE_AT = 0.90

#: The events these quantities are derived from. Only guardian-core-v1 emits them: the
#: deadman-kit dialect's own vocabulary (KINDS in deadman/ledger.py) has no process lifecycle at
#: all. On such a ledger every quantity below is OMITTED rather than reported as zero - a zero
#: would claim "no restarts happened", which is not what "this dialect cannot say" means.
_CONTINUITY_EVENTS = ("GUARDIAN_STARTED", "GUARDIAN_STOPPED", "SEAL_CREATED", "SEAL_EXPIRED")


def _ms_between(a: Optional[str], b: Optional[str]) -> Optional[int]:
    """Milliseconds between two ISO-8601 UTC stamps, or None if either is unusable."""
    from datetime import datetime
    if not a or not b:
        return None
    try:
        ta = datetime.strptime(a, "%Y-%m-%dT%H:%M:%S.%fZ")
        tb = datetime.strptime(b, "%Y-%m-%dT%H:%M:%S.%fZ")
    except (ValueError, TypeError):
        return None
    return int((tb - ta).total_seconds() * 1000)


def recompute_continuity(entries: Sequence[Mapping[str, Any]], dialect: Dialect,
                         from_seq: int, to_seq: int) -> dict:
    """How much of the armed day the guardian's own clock could vouch for.

    SPEC section 17.2 states the gap plainly: across a process restart the seal is no longer
    measured on a monotonic counter, and falls back to the wall clock. That cannot be closed
    without a time source off the machine, which v1 does not have. It can be made NOISY - a
    legitimate restart lasts seconds, and a long gap is the shape the attack needs.

    Two rules govern every name and every sentence produced here:

    * **It reports coverage, never blame.** A restart with a wall-clock expiry is produced by a
      Windows update at 3am exactly as it is by someone cheating. A field that accuses the
      innocent becomes noise people learn to skip, and then it protects nobody.
    * **The verifier computes it, so it is a VERIFIED quantity.** Were the emitter to publish it,
      it would be an asserted one. That is the same distinction as an external anchor versus a
      hash chain, and this project already chose a side.

    WHY THIS DOES NOT MEASURE SILENCE, which matters for anyone tempted to "improve" it later:
    the guardian's five-minute PNL_CHECKPOINT heartbeat is NOT emitted while DISARMED or while
    LOCKED - `Tick()` returns before reaching it in both states. A four-hour lockout with the
    guardian running perfectly leaves the ledger silent, so inferring gaps from silence would
    report four hours "with no guardian", which is false, and false in the direction that
    accuses. Gaps are therefore measured only between explicit lifecycle events.
    """
    rows = _events_in_range(entries, dialect, from_seq, to_seq)
    ev, ts = dialect.f_event, dialect.f_ts
    names = [r.get(ev) for r in rows]

    # Decided by DIALECT, not by which events happen to appear. deadman-kit's vocabulary
    # (KINDS in deadman/ledger.py) has no process lifecycle at all, so on such a ledger these
    # quantities do not exist - and "do not exist" is reported, never zero. A zero would claim
    # "no restarts happened", which is a different statement from "this record cannot say".
    if dialect.name != GUARDIAN_CORE_V1.name:
        return {
            "supported": False,
            "reason": (f"the {dialect.name} vocabulary has no process-lifecycle events "
                       f"(GUARDIAN_STARTED / GUARDIAN_STOPPED / SEAL_EXPIRED), so seal-continuity "
                       f"cannot be derived from this ledger at all"),
        }

    if not any(n in _CONTINUITY_EVENTS for n in names):
        return {
            "supported": False,
            "reason": ("this range contains no process-lifecycle events, so there is nothing to "
                       "derive seal continuity from"),
        }

    # The window starts at SEAL_CREATED, not at ARMED: the seal is the thing whose continuity
    # is being measured, and it does not exist until then. Measuring from ARMED made a day
    # with no restarts read 0.92 rather than 1.00, and a number that is not 1.00 on a clean
    # day is a number nobody will trust.
    armed_start = next((r.get(ts) for r in rows if r.get(ev) == "SEAL_CREATED"), None)
    armed_end = next((r.get(ts) for r in rows if r.get(ev) == "DAY_CLOSED"), None)
    day_closed = armed_end is not None
    if armed_end is None and rows:
        armed_end = rows[-1].get(ts)

    # sealExpiryBasis: a POSITIVE guarantee when it says monotonic, never a suspicion otherwise.
    expiry = next((r for r in rows if r.get(ev) == "SEAL_EXPIRED"), None)
    basis = (expiry.get(dialect.f_payload) or {}).get("basis") if expiry else None

    restarts = unclean = indeterminate = 0
    gaps: list = []
    open_stop: Optional[str] = None
    continuity_ms = 0
    continuous_since: Optional[str] = None
    last_seen: Optional[str] = None
    armed_seen = False          # nothing before the first SEAL_CREATED is a restart of anything

    for r in rows:
        name, when = r.get(ev), r.get(ts)
        if name == "SEAL_CREATED":
            continuous_since = when
            armed_seen = True
        elif name == "GUARDIAN_STOPPED":
            open_stop = when
            if continuous_since is not None:
                continuity_ms += _ms_between(continuous_since, when) or 0
                continuous_since = None
        elif name == "GUARDIAN_STARTED":
            # The first start of a fresh process, before anything was armed, is a boot and not a
            # restart. Counting it inflated every quiet day by one.
            #
            # It is also where a declared range can FABRICATE an accusation. If the range begins
            # between a GUARDIAN_STOPPED and its GUARDIAN_STARTED, that start is orphaned by the
            # cut and not by a crash - the truncated-range attack pointed the other way, making a
            # clean shutdown look unclean. So the full ledger is consulted, not just the range,
            # and when it cannot settle the question the answer is `indeterminate`, never
            # `unclean`. This is the only number here a reader can take as a charge, so it is the
            # only one that may not err toward accusing.
            if not armed_seen:
                # Only starts after a seal has ever existed can be restarts OF a sealed session.
                #
                # The distinction that matters here is a genuine first boot versus a file that
                # simply does not begin at the beginning. Start() marks the first case: it writes
                # `fresh: true` when there was no state to restore. A start with nothing before it
                # in this file and NO such mark is a record whose earlier part is elsewhere - a
                # rotated segment - and that is undetermined, not a crash.
                if (not _any_seal_before(entries, dialect, r)
                        and _preceded_by_clean_stop(entries, dialect, r) is None
                        and not (r.get(dialect.f_payload) or {}).get("fresh")):
                    indeterminate += 1
                last_seen = when or last_seen
                continue
            restarts += 1
            if open_stop is not None:
                gaps.append(_ms_between(open_stop, when))
                open_stop = None
            else:
                # No GUARDIAN_STOPPED preceded this start IN RANGE. Before calling that unclean,
                # look at the whole ledger: the pairing may simply fall outside the declared range.
                paired = _preceded_by_clean_stop(entries, dialect, r)
                if paired is True:
                    pass                       # cleanly paired outside the range; not an offence
                elif paired is None:
                    indeterminate += 1         # nothing precedes it at all; unknowable
                else:
                    # Stop() is what writes GUARDIAN_STOPPED and does not run on a crash, a kill
                    # or a power cut, so the previous session ended without a clean shutdown and
                    # the gap has no measurable beginning.
                    unclean += 1
                if continuous_since is not None:
                    # Count coverage only up to the last moment there is evidence of life.
                    continuity_ms += _ms_between(continuous_since, last_seen) or 0
                    continuous_since = None
        last_seen = when or last_seen

    if continuous_since is not None:
        continuity_ms += _ms_between(continuous_since, armed_end) or 0

    armed_ms = _ms_between(armed_start, armed_end)
    coverage = None
    if armed_ms and armed_ms > 0:
        coverage = max(0.0, min(1.0, continuity_ms / armed_ms))

    # When a session ended with no recorded shutdown, the moment it died is unknown, so the
    # covered fraction lies somewhere between "up to the last proof of life" and "right up to the
    # restart". Reporting the first as if it were the answer picks the worst end of an unknown
    # range and reads as a damning 0% for a day that may have been spotless. It is published as a
    # LOWER BOUND instead, and labelled as one.
    coverage_is_lower_bound = bool(unclean or indeterminate)

    measured = [g for g in gaps if g is not None]
    out = {
        "supported": True,
        "indeterminateStarts": indeterminate,
        "armedMs": armed_ms,
        "dayClosed": day_closed,
        "sealExpiryBasis": basis,
        "processRestarts": restarts,
        "uncleanShutdowns": unclean,
        "continuityCoverage": coverage,
        "coverageIsLowerBound": coverage_is_lower_bound,
    }
    if (coverage_is_lower_bound and coverage is not None
            and coverage < COVERAGE_BOUND_PUBLISHABLE_AT):
        out["continuityCoverage"] = None
        out["coverageOmittedBecause"] = (
            f"the only figure derivable here is a lower bound, and at {coverage * 100:.0f}% it "
            f"leaves almost the whole range open. A bound that does not constrain is not a "
            f"measurement, and a reader anchors on the number rather than on the word 'at least'")

    # The partition that leaves no path silent: a clean shutdown yields a measurable gap; an
    # unclean one yields no duration but IS reported as unclean. Omission without a stated reason
    # would be a mystery, so the reason travels with it.
    if unclean:
        out["unmonitoredMs"] = None
        out["longestGapMs"] = None
        out["durationsOmittedBecause"] = (
            f"{unclean} session(s) in this range ended without a clean shutdown, so those gaps "
            f"have no measurable start")
    else:
        out["unmonitoredMs"] = sum(measured) if measured else 0
        out["longestGapMs"] = max(measured) if measured else 0
    return out


def _any_seal_before(entries: Sequence[Mapping[str, Any]], dialect: Dialect,
                     entry: Mapping[str, Any]) -> bool:
    """Had a seal ever been created before this entry, anywhere in the ledger? A start before the
    first SEAL_CREATED is a boot, not a restart of anything sealed."""
    seqf, ev = dialect.f_seq, dialect.f_event
    seq = entry.get(seqf)
    if not isinstance(seq, int):
        return False
    return any(e.get(ev) == "SEAL_CREATED" and isinstance(e.get(seqf), int) and e[seqf] < seq
               for e in entries)


def _preceded_by_clean_stop(entries: Sequence[Mapping[str, Any]], dialect: Dialect,
                            start_entry: Mapping[str, Any]):
    """Was this GUARDIAN_STARTED preceded by a clean GUARDIAN_STOPPED, anywhere in the ledger?

    True  - yes, so it is an ordinary restart even if the pairing lies outside the declared range.
    False - no, and something else does precede it: the previous session ended ungracefully.
    None  - nothing precedes it in this file at all, so the question cannot be answered here. A
            rotated ledger segment looks exactly like this, and so does a genuine first boot.
    """
    seqf, ev = dialect.f_seq, dialect.f_event
    seq = start_entry.get(seqf)
    if not isinstance(seq, int):
        return None

    earlier = [e for e in entries
               if isinstance(e.get(seqf), int) and e[seqf] < seq]
    if not earlier:
        return None
    earlier.sort(key=lambda e: e[seqf])
    return earlier[-1].get(ev) == "GUARDIAN_STOPPED"


def find_backwards_timestamps(entries: Sequence[Mapping[str, Any]], dialect: Dialect,
                              from_seq: int, to_seq: int) -> list:
    """Timestamps that move BACKWARDS between consecutive seq in a hash-chained file.

    The strongest of these signals and the cheapest: the chain is already walked in seq order,
    and this needs no event the vocabulary does not already have. It works on both dialects and
    on every certificate ever issued.

    What it targets is the return journey. Moving a clock forward leaves no backwards step;
    moving it BACK does - and it has to be moved back to keep trading against coherent market
    data. That leg is the one an attacker cannot avoid, and it cannot be repaired quietly,
    because repairing it means rewriting entries whose hashes chain.
    """
    rows = _events_in_range(entries, dialect, from_seq, to_seq)
    ts, seqf = dialect.f_ts, dialect.f_seq
    out = []
    for previous, current in zip(rows, rows[1:]):
        back = _ms_between(current.get(ts), previous.get(ts))
        if back is not None and back > 0:
            out.append({"fromSeq": previous.get(seqf), "toSeq": current.get(seqf),
                        "byMs": back, "at": current.get(ts)})
    return out


def recompute_claims(entries: Sequence[Mapping[str, Any]], dialect: Dialect,
                     from_seq: int, to_seq: int, chain_ok: bool) -> dict:
    """Every claim of SPEC §2c/§A.2, counted from the events and nothing else."""
    rows = _events_in_range(entries, dialect, from_seq, to_seq)
    ev = dialect.f_event
    names = [r.get(ev) for r in rows]

    lockouts = names.count("LIMIT_BREACHED")
    change_attempts = names.count("CONFIG_CHANGE_REJECTED")

    # Distinct by orderId: a retry of the same id must not inflate the number (§A.2).
    rejected_ids = {
        (r.get(dialect.f_payload) or {}).get("orderId")
        for r in rows if r.get(ev) == "ORDER_REJECTED_LOCKED"
    }
    rejected_ids.discard(None)

    # Episodes, not causes. An episode runs from FAIL_CLOSED_ENTERED to its
    # FAIL_CLOSED_CLEARED, or stays open to the end of the range, AND it includes the event
    # that triggered it (SPEC A.2.1): an episode that leaves out its own cause tells the
    # story wrong. The rule is positional and published - `triggerSeq` names the exact entry
    # counted, so nothing is inferred from the text of `reason`.
    episodes: list[dict] = []
    current: Optional[dict] = None
    for idx, r in enumerate(rows):
        name = r.get(ev)
        if name == "FAIL_CLOSED_ENTERED":
            if current is None:
                # PRECEDING, not TRIGGER. The old name promised a cause and delivered adjacency:
                # measured, inserting PNL_CHECKPOINT, CONFIG_LOADED, DAY_OPENED or SEAL_CREATED
                # before a fail-closed made each of them the published "cause". The rule is
                # positional and always was; only the name claimed otherwise. Deriving the real
                # cause would need FAIL_CLOSED_ENTERED to carry its own reason, which the emitter
                # has already reported as unreachable without new broker I/O on that path.
                j = idx - 1
                while j >= 0 and _is_human(rows[j].get(ev)):
                    j -= 1                      # testimony about a person is not part of the story
                trigger = rows[j] if j >= 0 else None
                if trigger is not None and trigger.get(ev) in _BOUNDARY:
                    trigger = None
                current = {"fromSeq": r[dialect.f_seq], "fromUtc": r.get(dialect.f_ts),
                           "open": True, "reasons": {},
                           "precedingSeq": trigger[dialect.f_seq] if trigger else None,
                           "precedingEvent": trigger.get(ev) if trigger else None}
                if trigger is not None:
                    current["reasons"][trigger[ev]] = 1
        elif name == "FAIL_CLOSED_CLEARED" and current is not None:
            current["toSeq"] = r[dialect.f_seq]
            current["toUtc"] = r.get(dialect.f_ts)
            current["open"] = False
            episodes.append(current)
            current = None
        elif current is not None and name not in _BOUNDARY and not _is_human(name):
            current["reasons"][name] = current["reasons"].get(name, 0) + 1
    if current is not None:
        current["toSeq"] = to_seq
        current["toUtc"] = None
        episodes.append(current)

    clock = {"CLOCK_ANOMALY": names.count("CLOCK_ANOMALY"),
             "CLOCK_SUSPECT": names.count("CLOCK_SUSPECT")}

    # THREE STATES, because reality has three and a boolean has two.
    #
    # `limitRespected: false` was published both when the trader went past their limit and when
    # the guardian COULD NOT SEE - an episode still open at the end of the range, with zero
    # LIMIT_BREACHED. Those are opposite facts about the person holding the document, and the
    # collapse always fell on the accusing side. Measured: an episode missing its
    # FAIL_CLOSED_CLEARED gives lockoutsTriggered=0 and limitRespected=False.
    #
    # A CONNECTION THIS MACHINE MAKES BY DEFAULT: the platform does not connect on startup unless
    # told to, so a fresh install sits in exactly the state that produces an open episode. This is
    # not an edge; it is the first day of every new user.
    #
    # `limitStatus` is INTERNAL and `limitRespected` keeps its boolean value unchanged: renaming or
    # retyping a field of the CERTIFICATE is the emitter's side of the contract (§5.12). What
    # changes here is the SEVERITY the verifier assigns, which is where the accusation lived.
    open_episode = any(e["open"] for e in episodes)
    if lockouts > 0:
        limit_status = "breached"
    elif open_episode or not chain_ok:
        limit_status = "undetermined"
    else:
        limit_status = "respected"
    limit_respected = (lockouts == 0 and not open_episode and chain_ok)

    return {
        "lockoutsTriggered": lockouts,
        "changeAttemptsWhileSealed": change_attempts,
        "ordersRejectedWhileLocked": len(rejected_ids),
        "failClosedEpisodes": episodes,
        "clockAnomalies": {"byType": clock},
        "limitRespected": limit_respected,
        "limitStatus": limit_status,
    }


# `tradesObserved` is intentionally not derived above: no event in the GuardianCore
# vocabulary records a fill count, and inventing one from PNL_CHECKPOINT would be exactly
# the plausible default SPEC §4.1 forbids. It is reported as unverifiable instead.


# --------------------------------------------------------------------------------------
# certHash, anchors, signature
# --------------------------------------------------------------------------------------

def _cert_preimage(cert: Mapping[str, Any]) -> bytes:
    """certHash covers the document without `certHash` and without `signature`.

    SPEC §4 says "sha256 of the document without this field". Excluding `signature` too is
    forced by ordering: the signature is produced over the hash, so it cannot also be inside
    it. Flagged in CERT_STEP1.md as an assumption for the emitter to match.
    """
    return canonical_json({k: v for k, v in cert.items() if k not in ("certHash", "signature")})


def _check_anchors(entries: Sequence[Mapping[str, Any]], dialect: Dialect,
                   anchors: Sequence[Mapping[str, Any]], rep: CertReport) -> Optional[int]:
    """Contrast third-party anchors against the ledger. Returns the highest covered seq."""
    by_seq = {e.get(dialect.f_seq): e for e in entries}
    covered: Optional[int] = None
    for a in anchors:
        seq, h = a.get("seq"), a.get("hash")
        if seq is None or h is None:
            rep.contradict("ANCHOR_MALFORMED", f"anchor without seq/hash: {a!r}")
            continue
        entry = by_seq.get(seq)
        if entry is None:
            rep.contradict("ANCHOR_MISMATCH",
                           f"anchor claims seq {seq} but the ledger has no such entry")
            continue
        if entry.get("hash") != h:
            rep.contradict("ANCHOR_MISMATCH",
                           f"anchor for seq {seq} has hash {h[:12]}... but the ledger has "
                           f"{str(entry.get('hash'))[:12]}... - the ledger was rewritten after anchoring")
            continue
        rep.anchors_checked += 1
        covered = seq if covered is None else max(covered, seq)
    return covered


def _check_signature(cert: Mapping[str, Any], pubkey_path: Optional[Path],
                     rep: CertReport) -> bool:
    """Ed25519 through the optional extra. Absent extra degrades, never validates (§A.4)."""
    sig = cert.get("signature")
    if not sig:
        rep.signature_status = "ABSENT"
        return False
    if pubkey_path is None:
        rep.signature_status = "NOT_VERIFIED (no public key supplied)"
        rep.cannot_verify("SIGNATURE_UNCHECKED",
                          "the certificate is signed but no public key was supplied, so its "
                          "origin is unproven (--pubkey)")
        return False
    try:
        serialization = importlib.import_module("cryptography.hazmat.primitives.serialization")
        ed = importlib.import_module("cryptography.hazmat.primitives.asymmetric.ed25519")
    except ImportError:
        rep.signature_status = "NOT_VERIFIED (extra not installed)"
        rep.cannot_verify("SIGNATURE_UNCHECKED",
                          "signature present but 'pip install deadman-kit[verify-sig]' is "
                          "missing, so origin is unproven - degraded, not accepted")
        return False
    try:
        pub = serialization.load_pem_public_key(pubkey_path.read_bytes())
        if not isinstance(pub, ed.Ed25519PublicKey):
            rep.signature_status = "NOT_VERIFIED (key is not Ed25519)"
            rep.cannot_verify("SIGNATURE_UNCHECKED", "the supplied key is not an Ed25519 public key")
            return False
        pub.verify(bytes.fromhex(sig.get("value", "")), _sha256_hex(_cert_preimage(cert)).encode())
    except Exception as e:  # a bad signature is a contradiction, not an excuse
        rep.signature_status = "INVALID"
        rep.contradict("SIGNATURE_INVALID",
                       f"the signature does not verify with the supplied key ({type(e).__name__})")
        return False
    # `issuer.keyId` USED TO BE INTERPOLATED HERE, and this was the only place the verifier
    # ever read it. Measured: signed by one key, with `issuer.keyId` naming another, verified
    # against the first - the report said `VALID (keyId=<the key that signed nothing>)`. The
    # field is never checked against anything; the key that actually verified is the one the
    # RECIPIENT supplied with --pubkey, and no PEM carries an identifier of its own.
    #
    # A FIELD PRINTED INSIDE A VERDICT INHERITS THE AUTHORITY OF THE VERDICT. It does not matter
    # that it was unverified: on the same line as VALID, a reasonable reader takes it as part of
    # what was verified. So the fix is not a caveat beside it - a caveat competes with an
    # authorised claim and loses - it is removing it from that line. It travelled into --json as
    # the same string, where a consumer parses it as data.
    #
    # Not replaced by a fingerprint of the supplied key, deliberately: printing one where the
    # keyId used to be invites the comparison the specification has not authorised yet, and would
    # pick one of at least four derivations of key identity without saying so. What `VALID` means
    # on its own is exactly what the verifier knows - the key you supplied signed this.
    rep.signature_status = "VALID"
    return True


# --------------------------------------------------------------------------------------
# The verifier
# --------------------------------------------------------------------------------------

#: What a certificate is allowed to say about the limit. The boolean is what every emitter
#: writes today; the three strings are what it should say once it can. `True` is accepted as an
#: EXACT boolean, not as anything equal to it - `1 == True` in Python, and an integer slipping
#: through a claim check would be a tolerance nobody chose. Closed on purpose (§DEF-7).
_LIMIT_LEGACY = {True: "respected", False: "boolean-false"}
_LIMIT_STATES = ("respected", "breached", "undetermined")


def _compare_limit(rep: "CertReport", mine: str, claimed: Mapping[str, Any], disagree) -> None:
    """`limitRespected`, judged by what the events can actually support.

    THE RULE THAT MATTERS: when the recomputed state is `undetermined`, NOTHING here is a
    contradiction. The verifier does not know whether the limit was respected, and a tool that
    does not know must not accuse - least of all in a document whose whole purpose is to be handed
    to a third party who will act on it.

    A legacy `false` against an `undetermined` is the ORIGIN DEFECT, not a lie: that certificate
    said the only thing its type allowed it to say."""
    if "limitRespected" not in claimed:
        rep.cannot_verify("CLAIM_ABSENT",
                          f"the certificate does not state `limitRespected`; recomputed {mine!r}")
        return
    theirs = claimed["limitRespected"]

    if isinstance(theirs, str) and theirs in _LIMIT_STATES:
        said = theirs
    elif theirs is True or theirs is False:            # exact identity: 1 is not True here
        said = _LIMIT_LEGACY[theirs]
    else:
        rep.contradict("CLAIM_MISMATCH",
                       f"`limitRespected` is {theirs!r}, which is neither a boolean nor one of "
                       f"{list(_LIMIT_STATES)}")
        return

    if mine == "undetermined":
        rep.cannot_verify(
            "LIMIT_UNDETERMINED",
            f"the certificate says `limitRespected` {theirs!r}, and the events cannot settle it: "
            f"a fail-closed episode is still open at the end of the range with no LIMIT_BREACHED, "
            f"so the guardian could not see the account rather than the trader going past a "
            f"limit. Not a finding against the holder"
            + ("" if said != "boolean-false" else
               " - and a boolean `false` here is the only thing that field could say"))
        return

    if said == "boolean-false":                        # legacy false == breached, when settled
        said = "breached"
    if said != mine:
        disagree("CLAIM_MISMATCH",
                 f"`limitRespected`: certificate says {theirs!r}, the events say {mine!r}")


def verify_certificate(cert: Mapping[str, Any],
                       ledger_entries: Sequence[Mapping[str, Any]],
                       anchors: Optional[Sequence[Mapping[str, Any]]] = None,
                       pubkey_path: Optional[Path] = None) -> CertReport:
    """Judge one certificate against one ledger. Pure: reads nothing, prints nothing."""
    rep = CertReport()

    if not isinstance(cert, dict):
        rep.cannot_evaluate("CERT_MALFORMED", "the certificate is not a JSON object")
        return rep

    # ---- dialect, declared and enforced (C17)
    dialect_name = cert.get("ledgerDialect")
    if dialect_name is None:
        rep.cannot_evaluate("DIALECT_MISSING",
                            "the certificate does not declare `ledgerDialect`; guessing it "
                            "from the file's shape is what this field exists to prevent")
        return rep
    dialect = DIALECTS.get(dialect_name)
    if dialect is None:
        rep.cannot_evaluate("DIALECT_UNKNOWN",
                            f"unknown ledgerDialect {dialect_name!r}; known: {sorted(DIALECTS)}")
        return rep
    rep.dialect = dialect.name
    rep.entries_read = len(ledger_entries)

    mismatch = _check_dialect(ledger_entries, dialect)
    if mismatch:
        # UNEVALUABLE, not CONTRADICTED. Nothing was measured here: the verifier refused to look
        # at a file that is not the one the certificate declares. Exit 1 means "I caught you
        # lying"; this is "I could not look". Collapsing them lets anyone smear an honest
        # certificate by handing over the wrong ledger - the same failure the exit-code table
        # warns about, pointed at the holder instead of at the tool.
        rep.cannot_evaluate("DIALECT_MISMATCH", mismatch)
        rep.declared_level = cert.get("trustLevel")
        rep.cannot_verify("NOTHING_ELSE_CHECKED",
                          "verification stopped at the dialect check; no claim was recomputed")
        return rep

    # ---- declared range
    rng = (cert.get("claims") or {}).get("ledgerRange") or {}
    from_seq, to_seq = rng.get("fromSeq"), rng.get("toSeq")
    if not isinstance(from_seq, int) or not isinstance(to_seq, int) or from_seq > to_seq:
        rep.cannot_evaluate("RANGE_MISSING",
                            "claims.ledgerRange must carry integer fromSeq <= toSeq")
        return rep
    rep.range_from, rep.range_to = from_seq, to_seq

    present = {e.get(dialect.f_seq) for e in ledger_entries}
    absent = [s for s in range(from_seq, to_seq + 1) if s not in present]

    unknown = unknown_event_kinds(_events_in_range(ledger_entries, dialect, from_seq, to_seq),
                                  dialect)
    if unknown:
        rep.cannot_verify(
            "UNKNOWN_EVENT_KIND",
            f"the ledger contains {len(unknown)} event type(s) this version has no rule for "
            f"({', '.join(unknown)}). Every claim above was recomputed without them, so if any of "
            f"them should have counted, this verifier did not know. It is not evidence of anything "
            f"wrong - a newer emitter writes events an older verifier has not been taught - but a "
            f"newer verifier may reach a different answer over the same ledger")

    _check_range_covers_its_day(cert, ledger_entries, dialect, from_seq, to_seq, rep)

    # ---- chain
    rep.chain_ok, rep.broken_seq = _verify_chain(ledger_entries, dialect, from_seq, to_seq)
    if not rep.chain_ok:
        rep.contradict("CHAIN_BROKEN",
                       f"the hash chain does not recompute; first break at seq {rep.broken_seq}")

    # ---- short file, or a lying range? THE CHAIN CANNOT BE TRUNCATED FROM THE FRONT.
    #
    # A hash chain is built forward, so removing a SUFFIX leaves a prefix that still verifies all
    # the way to genesis. A prefix that chains whole, with the declared range running past the end
    # of the file, is the signature of a TRUNCATION - a real history that stops early - not of a
    # forgery. A broken link in the MIDDLE is the other story, and it still reads as one.
    #
    # Why the severity had to move: a power cut leaves the file cut at a LINE BOUNDARY, because
    # the writer fsyncs after each complete line. Before this, that produced CONTRADICTED, and
    # with a few rows lost it also published `limitRespected: false` and an episode left open -
    # the most damaging thing this document can say about the person holding it, manufactured by
    # the electricity supply. Every other defect in this verifier was the tool claiming too much;
    # this one was the tool accusing someone who did nothing.
    truncated = bool(absent) and rep.chain_ok and absent == list(range(absent[0], to_seq + 1))
    if truncated:
        rep.cannot_evaluate(
            "LEDGER_TRUNCATED",
            f"the ledger stops at seq {absent[0] - 1} but the certificate declares "
            f"{from_seq}..{to_seq}: {len(absent)} entr"
            f"{'y is' if len(absent) == 1 else 'ies are'} missing from the END, and everything "
            f"present chains cleanly. That is a file that was cut short - a power cut, a partial "
            f"copy, a truncated attachment - not a certificate that lies. Nothing here is proved "
            f"or disproved; ask for a complete copy of the ledger")
    elif absent:
        rep.contradict("RANGE_INCOMPLETE",
                       f"the declared range covers seq {from_seq}..{to_seq} but "
                       f"{len(absent)} entr{'y is' if len(absent) == 1 else 'ies are'} "
                       f"missing from the ledger (first: {absent[0]})")

    # ---- certHash
    declared_hash = cert.get("certHash")
    actual = _sha256_hex(_cert_preimage(cert))
    rep.cert_hash_ok = (declared_hash == actual)
    if not rep.cert_hash_ok:
        rep.contradict("CERTHASH_MISMATCH",
                       f"certHash says {str(declared_hash)[:16]}... but the document hashes "
                       f"to {actual[:16]}...")

    # ---- claims, recomputed and compared
    rep.recomputed = recompute_claims(ledger_entries, dialect, from_seq, to_seq, rep.chain_ok)
    rep.continuity = recompute_continuity(ledger_entries, dialect, from_seq, to_seq)
    rep.backwards_time = find_backwards_timestamps(ledger_entries, dialect, from_seq, to_seq)
    claimed = cert.get("claims") or {}
    commitment = cert.get("commitment") or {}

    def disagree(code: str, detail: str) -> None:
        """On a truncated ledger a disagreement is not a finding against the certificate.

        The claims are still recomputed - WHEN they are recomputed does not change here - but they
        were recomputed over rows that are missing their tail, so a difference says the file is
        short, not that the holder lied. Losing a FAIL_CLOSED_CLEARED is enough to turn
        `limitRespected` false. Reported, never charged."""
        if truncated:
            rep.cannot_verify(code + "_OVER_TRUNCATED_RANGE",
                              detail + " - recomputed over an incomplete ledger, so this is a "
                                       "consequence of the missing entries, not a finding")
        else:
            rep.contradict(code, detail)

    def compare(key: str, mine: Any, theirs: Any) -> None:
        if theirs is None:
            rep.cannot_verify("CLAIM_ABSENT",
                              f"the certificate does not state `{key}`; recomputed value is {mine!r}")
        elif theirs != mine:
            disagree("CLAIM_MISMATCH",
                     f"`{key}`: certificate says {theirs!r}, the events say {mine!r}")

    _compare_limit(rep, rep.recomputed["limitStatus"], claimed, disagree)
    compare("lockoutsTriggered", rep.recomputed["lockoutsTriggered"], claimed.get("lockoutsTriggered"))
    compare("ordersRejectedWhileLocked", rep.recomputed["ordersRejectedWhileLocked"],
            claimed.get("ordersRejectedWhileLocked"))
    compare("clockAnomalies", rep.recomputed["clockAnomalies"], claimed.get("clockAnomalies"))
    compare("changeAttemptsWhileSealed", rep.recomputed["changeAttemptsWhileSealed"],
            commitment.get("changeAttemptsWhileSealed"))

    mine_eps = rep.recomputed["failClosedEpisodes"]
    theirs_eps = claimed.get("failClosedEpisodes")
    if theirs_eps is None:
        rep.cannot_verify("CLAIM_ABSENT",
                          f"the certificate does not state `failClosedEpisodes`; recomputed "
                          f"{len(mine_eps)}")
    elif len(theirs_eps) != len(mine_eps):
        disagree("CLAIM_MISMATCH",
                   f"`failClosedEpisodes`: certificate lists {len(theirs_eps)}, the events "
                       f"give {len(mine_eps)}")
    else:
        for i, (m, t) in enumerate(zip(mine_eps, theirs_eps)):
            if t.get("reasons") is not None and t["reasons"] != m["reasons"]:
                disagree("CLAIM_MISMATCH",
                           f"`failClosedEpisodes[{i}].reasons`: certificate says "
                               f"{t['reasons']!r}, the events say {m['reasons']!r}")
            if bool(t.get("open")) != bool(m["open"]):
                disagree("CLAIM_MISMATCH",
                           f"`failClosedEpisodes[{i}].open`: certificate says "
                               f"{t.get('open')!r}, the events say {m['open']!r}")
            # The field that assigns blame was the ONE field in this block nobody checked:
            # measured, replacing it with a fabrication verified clean at exit 0 while a
            # falsified `reasons` was caught. Indefensible in an evidence artefact, so it is
            # compared now. Either name is accepted: the emitter still writes `triggerEvent`
            # and renaming a field of the CERTIFICATE is its side of the contract, not ours.
            #
            # And what this comparison is worth, said plainly rather than oversold: the emitter
            # derives this field by adjacency too, so it will agree with us on every honest
            # certificate. That closes "anybody can write anything" and closes nothing else.
            # What makes the document true is the NAME no longer claiming a cause, plus the
            # limitation the emitter has yet to ship.
            theirs_prev = t.get("precedingEvent", t.get("triggerEvent", _MISSING))
            if theirs_prev is _MISSING:
                rep.cannot_verify("CLAIM_ABSENT",
                                  f"`failClosedEpisodes[{i}]` names no preceding event; "
                                  f"recomputed {m['precedingEvent']!r}")
            elif theirs_prev != m["precedingEvent"]:
                disagree("CLAIM_MISMATCH",
                           f"`failClosedEpisodes[{i}].precedingEvent`: certificate says "
                               f"{theirs_prev!r}, the events say {m['precedingEvent']!r}")
            theirs_seq = t.get("precedingSeq", t.get("triggerSeq", _MISSING))
            if theirs_seq is not _MISSING and theirs_seq != m["precedingSeq"]:
                disagree("CLAIM_MISMATCH",
                           f"`failClosedEpisodes[{i}].precedingSeq`: certificate says "
                               f"{theirs_seq!r}, the events say {m['precedingSeq']!r}")

    # ---- rule 5: fields that promise more than they carry
    for code, detail in check_rule_five(cert):
        rep.contradict(code, detail)

    # ---- limitations, verbatim (C10)
    stated = cert.get("limitations")
    if not isinstance(stated, list):
        rep.contradict("LIMITATIONS_MISSING", "the certificate carries no `limitations` list")
    else:
        for required in REQUIRED_LIMITATIONS:
            if required not in stated:
                rep.contradict("LIMITATIONS_ALTERED",
                               f"a required limitation of SPEC section 2 is missing or reworded: "
                               f"\"{required[:60]}...\"")

    # ---- no individual trades, no personal data (C9)
    blob = json.dumps(cert, ensure_ascii=False)
    for probe in ("fillPrice", "executionId", "orderId", "quantity"):
        if f'"{probe}"' in blob:
            rep.contradict("PRIVACY_LEAK",
                           f"the certificate contains `{probe}`; v1 exports aggregates and "
                           f"guardian events only (SPEC section 4.3)")

    # ---- anchors -> L2
    if anchors:
        rep.covered_up_to_seq = _check_anchors(ledger_entries, dialect, anchors, rep)

    # ---- signature -> L3
    sig_ok = _check_signature(cert, pubkey_path, rep)

    # ---- the layer actually reached (§A.3)
    reached = None
    if rep.chain_ok and rep.cert_hash_ok:
        reached = "L1"
        if rep.anchors_checked > 0 and not any(f.code.startswith("ANCHOR") for f in rep.contradictions):
            reached = "L2"
            if sig_ok:
                reached = "L3"
    rep.reached_level = reached
    rep.declared_level = cert.get("trustLevel")

    order = {"L1": 1, "L2": 2, "L3": 3}
    if rep.declared_level in order and reached is not None:
        if order[rep.declared_level] > order[reached]:
            rep.contradict("TRUST_LEVEL_OVERSTATED",
                           f"the certificate declares {rep.declared_level} but only {reached} "
                           f"was reached")
    elif rep.declared_level not in order:
        rep.contradict("TRUST_LEVEL_INVALID",
                       f"trustLevel {rep.declared_level!r} is not one of L1/L2/L3")

    # ---- what could not be verified, stated even on success (§5)
    if rep.anchors_checked == 0:
        rep.cannot_verify("NO_EXTERNAL_ANCHOR",
                          "no third-party anchor was supplied, so nothing proves this ledger "
                          "existed before now: a full rewrite with recomputed hashes passes L1. "
                          "TO REACH L2, ask whoever holds this ledger for anchors kept by a third "
                          "party and pass them with --anchors")
    elif rep.covered_up_to_seq is not None and rep.covered_up_to_seq < to_seq:
        rep.cannot_verify("ANCHOR_COVERAGE_PARTIAL",
                          f"anchors cover up to seq {rep.covered_up_to_seq}; entries "
                          f"{rep.covered_up_to_seq + 1}..{to_seq} are outside L2 coverage")
    rep.cannot_verify("OTHER_VENUES",
                      "the guardian sees one platform and the configured accounts; trading "
                      "elsewhere is invisible to this document")
    rep.cannot_verify("PRE_START_BYPASS",
                      "removing the add-on with the platform closed leaves a gap, not an act "
                      "(guardian SPEC section 17.1)")
    rep.cannot_verify("TRADES_OBSERVED",
                      "no event in this vocabulary records a fill count, so `tradesObserved` "
                      "is not recomputable and is not judged here")
    return rep


def verify_series(certs: Sequence[Mapping[str, Any]]) -> CertReport:
    """Check the chain BETWEEN certificates and the declared continuity (C12, C13).

    Certificates are ordered by session.dayKey. Each must carry the previous one's certHash.
    A day removed from the middle breaks the link; a day never armed must appear in `gaps`.
    """
    rep = CertReport()
    ordered = sorted(certs, key=lambda c: ((c.get("session") or {}).get("dayKey") or ""))
    if not ordered:
        rep.cannot_evaluate("SERIES_EMPTY", "no certificates supplied")
        return rep

    seen_days: dict = {}
    prev_hash: Optional[str] = None
    prev_day: Optional[str] = None
    for c in ordered:
        day = (c.get("session") or {}).get("dayKey")
        declared_prev = c.get("previousCertHash")

        # A series is one certificate per day. Two for the same day means one of them is being
        # substituted for the other, and a reader cannot tell which.
        if day in seen_days:
            rep.contradict("SERIES_DUPLICATE_DAY",
                           f"two certificates in this series are for {day} "
                           f"({str(seen_days[day])[:12]}... and {str(c.get('certHash'))[:12]}...)")
        seen_days[day] = c.get("certHash")

        # A certificate cannot be its own predecessor. A chain that closes on itself has no
        # beginning, so nothing dates it.
        if declared_prev is not None and declared_prev == c.get("certHash"):
            rep.contradict("SERIES_SELF_REFERENCE",
                           f"the certificate for {day} names itself as previousCertHash")
        if prev_hash is not None and declared_prev != prev_hash:
            rep.contradict("SERIES_BROKEN",
                           f"certificate for {day} carries previousCertHash "
                           f"{str(declared_prev)[:16]}... but the preceding certificate hashes "
                           f"to {prev_hash[:16]}... - a day is missing from the series or was "
                           f"replaced")
        gaps = {g.get("dayKey") for g in ((c.get("continuity") or {}).get("gaps") or [])}
        if prev_day is not None:
            missing = _days_between(prev_day, day)
            undeclared = [d for d in missing if d not in gaps]
            if undeclared:
                rep.contradict("GAP_UNDECLARED",
                               f"{len(undeclared)} day(s) between {prev_day} and {day} are "
                               f"neither certified nor declared as gaps (first: {undeclared[0]})")
        for g in ((c.get("continuity") or {}).get("gaps") or []):
            if not g.get("reason"):
                rep.contradict("GAP_WITHOUT_REASON",
                               f"the gap on {g.get('dayKey')} is declared without a reason")
        prev_hash = c.get("certHash")
        prev_day = day

    rep.reached_level = "series"
    rep.cannot_verify("SERIES_SCOPE",
                      "this checks the links between certificates only; each certificate must "
                      "still be verified against its own ledger")
    return rep


def _days_between(a: str, b: str) -> list[str]:
    """Calendar days strictly between two YYYY-MM-DD keys. Weekends are NOT skipped: a
    weekend day that is not certified is a gap and must be declared as one (§2b)."""
    from datetime import date, timedelta
    try:
        d0 = date.fromisoformat(a)
        d1 = date.fromisoformat(b)
    except ValueError:
        return []
    out = []
    cur = d0 + timedelta(days=1)
    while cur < d1:
        out.append(cur.isoformat())
        cur += timedelta(days=1)
    return out


# --------------------------------------------------------------------------------------
# The door
# --------------------------------------------------------------------------------------

def _packaged_example() -> tuple:
    """The certificate and ledger that ship inside this package.

    A cold-start run found that a reader who installed from PyPI had nothing to verify: the
    examples lived at the repository root, the README linked to them relatively - which does not
    resolve from the PyPI page - and the wheel contained none of them. `--example` exists so the
    first useful command needs no download, no GitHub, and no network.
    """
    try:
        from importlib.resources import files
        base = files("deadman") / "examples" / "certificate"
        cert = json.loads((base / "certificate.json").read_text(encoding="utf-8"))
        entries = [json.loads(line) for line
                   in (base / "ledger.jsonl").read_text(encoding="utf-8").splitlines()
                   if line.strip()]
        return cert, entries
    except (OSError, ModuleNotFoundError, ValueError) as e:
        raise RuntimeError(f"the packaged example could not be read: {e}") from e


def _run_example() -> int:
    try:
        cert, entries = _packaged_example()
    except RuntimeError as e:
        print(f"COULD NOT EVALUATE - {e}", file=sys.stderr)
        return EXIT_UNEVALUABLE

    print("Verifying the example certificate that ships with this package.")
    print("Nothing is downloaded; this runs entirely offline.")
    print()
    rep = verify_certificate(cert, entries)
    print(rep.render())
    print()
    print("That certificate is honest, so it passes. Three more ship beside it - one with a")
    print("falsified claim, one that lies by declaring a shorter range, and one whose issuer")
    print("fields are omitted because the emitter could not determine them:")
    print(f"    {REPO_EXAMPLES}")
    print()
    print("To check a real certificate you need two files: the certificate, and the ledger it")
    print("says it covers. Then:  python -m deadman.verify_certificate certificate.json ledger.jsonl")
    return rep.exit_code


def main(argv: Optional[Sequence[str]] = None) -> int:
    p = argparse.ArgumentParser(
        prog="python -m deadman.verify_certificate",
        description="Verify a deadman session certificate against its ledger. "
                    "Recomputes every claim from the events; never trusts the document.",
        epilog="Trust layers: L1 the ledger's own hash chain recomputes - which does NOT "
               "survive an attacker with disk access; L2 adds a third party's anchor, so the "
               "record is dated by someone other than the trader; L3 adds the issuer's "
               "signature, which proves origin and never truth.\n"
               "Exit codes: 0 = verified, 1 = contradicted, 2 = could not evaluate.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("certificate", type=Path, nargs="?",
                   help="the certificate JSON")
    p.add_argument("ledger", type=Path, nargs="?", help="the ledger .jsonl it claims to cover")
    p.add_argument("--anchors", type=Path,
                   help="JSON list of third-party anchors [{seq, hash, ...}]. Reaches L2: proof "
                        "from someone other than the trader that the ledger existed before a "
                        "point in time")
    p.add_argument("--pubkey", type=Path,
                   help="PEM Ed25519 public key of the issuer. Reaches L3: proof the document "
                        "came from the holder of that key and was not edited afterwards")
    p.add_argument("--series", type=Path, nargs="+", metavar="CERT",
                   help="additional certificates covering other days: checks that the chain "
                        "between days is unbroken and that any missing day is declared")
    p.add_argument("--example", action="store_true",
                   help="verify the example certificate that ships with this package and exit; "
                        "needs no files, no download and no network")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    args = p.parse_args(argv)

    if args.example:
        return _run_example()

    if args.certificate is None:
        p.print_usage(sys.stderr)
        print("\nCOULD NOT EVALUATE - no certificate given. To see this tool work on a "
              "certificate that ships with it, run:\n"
              "    python -m deadman.verify_certificate --example", file=sys.stderr)
        return EXIT_UNEVALUABLE

    try:
        cert = _read_json(args.certificate)
    except (OSError, ValueError) as e:
        print(f"COULD NOT EVALUATE - certificate unreadable: {e}", file=sys.stderr)
        return EXIT_UNEVALUABLE

    if args.series:
        series = [cert]
        for path in args.series:
            try:
                series.append(_read_json(path))
            except (OSError, ValueError) as e:
                print(f"COULD NOT EVALUATE - {path} unreadable: {e}", file=sys.stderr)
                return EXIT_UNEVALUABLE
        srep = verify_series(series)
        print(srep.render())
        if srep.exit_code != EXIT_OK:
            return srep.exit_code

    if args.ledger is None:
        # The cold-start run stopped here. The message was accurate and ended one sentence early:
        # it never said what to do next, and "ledger" means nothing to someone who has just been
        # handed a certificate by a stranger.
        # Rule 5 needs only the document, so run it before giving up. This is the moment a
        # recipient has least information and most need - somebody handed them one file -
        # and staying silent would waste the one check that still works without a ledger.
        rule_five = check_rule_five(cert)
        if rule_five:
            print(f"Found in the certificate itself, without needing the ledger "
                  f"({len(rule_five)} item(s)). CERT_SPEC rule 5: a field that looks "
                  f"like evidence and is not is worse than an absent field.",
                  file=sys.stderr)
            for code, detail in rule_five:
                print(f"  - {code}: {detail}", file=sys.stderr)
            print(file=sys.stderr)
        
        print("COULD NOT EVALUATE - no ledger given; the certificate cannot judge itself.\n"
              "\n"
              "A certificate is a summary. The ledger is the append-only record of what actually\n"
              "happened - every event, hash-chained - and this tool recomputes the summary from it\n"
              "rather than believing it. Without the ledger there is nothing to check against.\n"
              "\n"
              "WHAT TO DO: ask whoever gave you the certificate for the ledger file it covers\n"
              "(usually ledger.jsonl). A certificate handed over without its ledger cannot be\n"
              "verified by anyone, including us. Then run:\n"
              "    python -m deadman.verify_certificate certificate.json ledger.jsonl\n"
              "\n"
              "To see the tool work meanwhile:\n"
              "    python -m deadman.verify_certificate --example",
              file=sys.stderr)
        return EXIT_UNEVALUABLE

    try:
        entries = _read_ledger_lines(args.ledger)
    except (OSError, ValueError) as e:
        print(f"COULD NOT EVALUATE - ledger unreadable: {e}", file=sys.stderr)
        return EXIT_UNEVALUABLE

    anchors = None
    if args.anchors:
        try:
            anchors = _read_json(args.anchors)
        except (OSError, ValueError) as e:
            print(f"COULD NOT EVALUATE - anchors unreadable: {e}", file=sys.stderr)
            return EXIT_UNEVALUABLE

    rep = verify_certificate(cert, entries, anchors=anchors, pubkey_path=args.pubkey)

    if args.json:
        print(json.dumps({
            "result": ["VERIFIED", "CONTRADICTED", "UNEVALUABLE"][rep.exit_code],
            "declaredLevel": rep.declared_level, "reachedLevel": rep.reached_level,
            "chainOk": rep.chain_ok, "certHashOk": rep.cert_hash_ok,
            "anchorsChecked": rep.anchors_checked, "coveredUpToSeq": rep.covered_up_to_seq,
            "signature": rep.signature_status,
            "contradictions": [{"code": f.code, "detail": f.detail} for f in rep.contradictions],
            "couldNotVerify": [{"code": f.code, "detail": f.detail} for f in rep.unverified],
            "couldNotEvaluate": [{"code": f.code, "detail": f.detail} for f in rep.unevaluable],
        }, indent=2, ensure_ascii=False))
    else:
        print(rep.render())
    return rep.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
