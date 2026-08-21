"""Independent verifier for a Verifiable Session Certificate (CERT_SPEC v0.2).

Run it without knowing anything about this project:

    git clone https://github.com/Roberto9210/deadman.git && cd deadman
    python -m deadman.verify_certificate certificate.json ledger.jsonl

(`pip install deadman-kit` gets you 0.1.0, which predates this module. Clone until a release
is cut; after that the pip line is the whole install.)

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


def canonical_json(obj: Mapping[str, Any]) -> bytes:
    """The one canonicalisation both ledger dialects share: ordinal-sorted keys, no
    whitespace, UTF-8. Verified against 67 real GuardianCore entries."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


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
    # deadman-kit hashes seven named fields (ledger.py::_entry_hash). `sig` is written to
    # disk but is NOT part of the hashed body, so "drop the hash field" would be wrong here.
    return {k: e[k] for k in ("schema_version", "seq", "ts_utc", "kind", "actor", "payload", "prev_hash")}


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
        add("")
        add(f"  DECLARED      {self.declared_level}")
        add(f"  REACHED       {self.reached_level or 'none'}")

        if self.contradictions:
            add("")
            add("CONTRADICTIONS - the certificate does not survive its own evidence:")
            for f in self.contradictions:
                add(f"  - {f}")

        add("")
        add("COULD NOT VERIFY - true even when everything above passes:")
        for f in self.unverified:
            add(f"  - {f}")

        add("")
        if self.contradictions:
            add(f"RESULT: CONTRADICTED (exit 1). {len(self.contradictions)} finding(s).")
        else:
            add(f"RESULT: VERIFIED at {self.reached_level} (exit 0).")
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

_BOUNDARY = ("FAIL_CLOSED_ENTERED", "FAIL_CLOSED_CLEARED")

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

    if day is not None:
        opened = [e for e in outside_before if e.get(ev) == "DAY_OPENED" and day_of(e) == day]
        closed = [e for e in outside_after if e.get(ev) == "DAY_CLOSED" and day_of(e) == day]
        hidden = [e for e in outside_before + outside_after if e.get(ev) in _MATERIAL]
        edge = closed[0] if closed else (opened[0] if opened else None)

        if edge is not None:
            where = ("that day's DAY_CLOSED is at seq %s, past the declared range" % edge[seqf]
                     if closed else
                     "that day's DAY_OPENED is at seq %s, before the declared range" % edge[seqf])
            # Severity follows the harm, not the shape. A range that stops early with nothing
            # material outside it is an incomplete document; a range that stops early with a
            # breach outside it is the lie this check exists for.
            if hidden:
                names = sorted({str(e.get(ev)) for e in hidden})
                rep.contradict("RANGE_TRUNCATED",
                               f"the certificate is for {day} but {where} {from_seq}..{to_seq}, "
                               f"and {len(hidden)} material event(s) fall outside it "
                               f"({', '.join(names)}) - the range excludes part of the session it "
                               f"claims to describe")
            else:
                rep.cannot_verify("SESSION_NOT_FULLY_COVERED",
                                  f"the certificate is for {day} but {where} {from_seq}..{to_seq}: "
                                  f"this is part of that session, not all of it. Nothing material "
                                  f"sits outside the range, so nothing is being hidden - but for a "
                                  f"complete day, export again after the session closes")
            return

    material_after = [e for e in outside_after if e.get(ev) in _MATERIAL]
    if material_after:
        names = sorted({str(e.get(ev)) for e in material_after})
        rep.cannot_verify("POST_RANGE_MATERIAL_EVENTS",
                          f"{len(material_after)} event(s) after the declared range are of a kind "
                          f"that changes what a certificate says ({', '.join(names)}); with no "
                          f"DAY_CLOSED for this session the verifier cannot tell an export taken "
                          f"mid-session from a range truncated to exclude them - ask for a "
                          f"certificate covering the closed session")


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
                trigger = rows[idx - 1] if idx > 0 else None
                if trigger is not None and trigger.get(ev) in _BOUNDARY:
                    trigger = None
                current = {"fromSeq": r[dialect.f_seq], "fromUtc": r.get(dialect.f_ts),
                           "open": True, "reasons": {},
                           "triggerSeq": trigger[dialect.f_seq] if trigger else None,
                           "triggerEvent": trigger.get(ev) if trigger else None}
                if trigger is not None:
                    current["reasons"][trigger[ev]] = 1
        elif name == "FAIL_CLOSED_CLEARED" and current is not None:
            current["toSeq"] = r[dialect.f_seq]
            current["toUtc"] = r.get(dialect.f_ts)
            current["open"] = False
            episodes.append(current)
            current = None
        elif current is not None and name not in _BOUNDARY:
            current["reasons"][name] = current["reasons"].get(name, 0) + 1
    if current is not None:
        current["toSeq"] = to_seq
        current["toUtc"] = None
        episodes.append(current)

    clock = {"CLOCK_ANOMALY": names.count("CLOCK_ANOMALY"),
             "CLOCK_SUSPECT": names.count("CLOCK_SUSPECT")}

    limit_respected = (lockouts == 0
                       and not any(e["open"] for e in episodes)
                       and chain_ok)

    return {
        "lockoutsTriggered": lockouts,
        "changeAttemptsWhileSealed": change_attempts,
        "ordersRejectedWhileLocked": len(rejected_ids),
        "failClosedEpisodes": episodes,
        "clockAnomalies": {"byType": clock},
        "limitRespected": limit_respected,
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
    rep.signature_status = f"VALID (keyId={ (cert.get('issuer') or {}).get('keyId') })"
    return True


# --------------------------------------------------------------------------------------
# The verifier
# --------------------------------------------------------------------------------------

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
        rep.contradict("DIALECT_MISMATCH", mismatch)
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
    if absent:
        rep.contradict("RANGE_INCOMPLETE",
                       f"the declared range covers seq {from_seq}..{to_seq} but "
                       f"{len(absent)} entr{'y is' if len(absent) == 1 else 'ies are'} "
                       f"missing from the ledger (first: {absent[0]})")

    _check_range_covers_its_day(cert, ledger_entries, dialect, from_seq, to_seq, rep)

    # ---- chain
    rep.chain_ok, rep.broken_seq = _verify_chain(ledger_entries, dialect, from_seq, to_seq)
    if not rep.chain_ok:
        rep.contradict("CHAIN_BROKEN",
                       f"the hash chain does not recompute; first break at seq {rep.broken_seq}")

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
    claimed = cert.get("claims") or {}
    commitment = cert.get("commitment") or {}

    def compare(key: str, mine: Any, theirs: Any) -> None:
        if theirs is None:
            rep.cannot_verify("CLAIM_ABSENT",
                              f"the certificate does not state `{key}`; recomputed value is {mine!r}")
        elif theirs != mine:
            rep.contradict("CLAIM_MISMATCH",
                           f"`{key}`: certificate says {theirs!r}, the events say {mine!r}")

    compare("limitRespected", rep.recomputed["limitRespected"], claimed.get("limitRespected"))
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
        rep.contradict("CLAIM_MISMATCH",
                       f"`failClosedEpisodes`: certificate lists {len(theirs_eps)}, the events "
                       f"give {len(mine_eps)}")
    else:
        for i, (m, t) in enumerate(zip(mine_eps, theirs_eps)):
            if t.get("reasons") is not None and t["reasons"] != m["reasons"]:
                rep.contradict("CLAIM_MISMATCH",
                               f"`failClosedEpisodes[{i}].reasons`: certificate says "
                               f"{t['reasons']!r}, the events say {m['reasons']!r}")
            if bool(t.get("open")) != bool(m["open"]):
                rep.contradict("CLAIM_MISMATCH",
                               f"`failClosedEpisodes[{i}].open`: certificate says "
                               f"{t.get('open')!r}, the events say {m['open']!r}")

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
                          "existed before now: a full rewrite with recomputed hashes passes L1")
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

def main(argv: Optional[Sequence[str]] = None) -> int:
    p = argparse.ArgumentParser(
        prog="python -m deadman.verify_certificate",
        description="Verify a deadman session certificate against its ledger. "
                    "Recomputes every claim from the events; never trusts the document.",
        epilog="exit 0 = verified, 1 = contradicted, 2 = could not evaluate",
    )
    p.add_argument("certificate", type=Path, help="the certificate JSON")
    p.add_argument("ledger", type=Path, nargs="?", help="the ledger .jsonl it claims to cover")
    p.add_argument("--anchors", type=Path,
                   help="JSON list of third-party anchors [{seq, hash, ...}] - reaches L2")
    p.add_argument("--pubkey", type=Path,
                   help="PEM Ed25519 public key of the issuer - reaches L3")
    p.add_argument("--series", type=Path, nargs="+", metavar="CERT",
                   help="additional certificates: check the links between days (C12/C13)")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    args = p.parse_args(argv)

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
        print("COULD NOT EVALUATE - no ledger given; the certificate cannot judge itself",
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
