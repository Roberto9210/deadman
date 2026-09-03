# CERT_SPEC v0.2 — Verifiable Session Certificate

**Status:** this is the document `deadman/verify_certificate.py` cites. Until 2026-09-02 it did not
exist in any repository, so a reader who installed `deadman-kit` from PyPI and followed a reference
in the source arrived nowhere. That is what this closes.

**How to read the two kinds of statement in here**, because mixing them is how a specification
starts describing an implementation instead of binding it:

| | |
|---|---|
| **NORMATIVE** | *A conforming verifier MUST / MUST NOT …* — binding. A verifier that does otherwise is not conforming, whatever else it does. |
| **DESCRIPTIVE** | *Today this verifier …* — a fact about the current implementation, deliberately **not** binding yet. §9 lists what is held back and why. |

**Scope.** This specifies the CERTIFICATE and the verifier that judges it. It does not specify the
guardian that emits one — that is `deadman-guardian`'s own SPEC, and where this document needs a
fact from it, the citation says so by name.

---

## 1. What a certificate is, and what it is not

A certificate is **a machine's signed assertion about a record that machine kept.** It is produced
from a hash-chained ledger and states, over a declared range of that ledger, what the guardian
observed.

**DESCRIPTIVE** (demoted from normative 2026-09-03 — see §9). A certificate is not, and this
verifier does not report it as, any of the following. These four are the limitations of §2, and
each exists because it is a conclusion a reader reaches unaided:

- a record of profitability,
- a statement that the trader did not trade elsewhere,
- a statement that the software was not bypassed before it started,
- an audit of the trader.

This is the paragraph whose demotion costs the most, and it is said plainly rather than buried:
nothing in the suite asserts that a verdict never contains a profitability figure. The behaviour
is correct today because the verifier never computes one, and **absence of a feature is not an
implementation**. It returns to NORMATIVE the day one test says so.

## 2. The limitations, carried verbatim (guarantee C10)

**NORMATIVE.** Every certificate MUST carry a `limitations` array containing these four strings,
**verbatim**. A conforming verifier MUST refuse a certificate that omits or rewords any of them.

```
This does not say the trader makes money. It is not a track record of profitability.

This does not say the trader did not trade elsewhere. The guardian sees one platform and the
configured accounts, and nothing else.

This does not say the software was not bypassed before it started. Whoever removes the add-on
with the platform closed does not appear; the gap appears, not the act.

This is not an audit. Nobody inspected this trader. It is a machine's signed assertion about a
record that machine kept.
```

**The canonical text lives in the verifier, not in the emitter** (`REQUIRED_LIMITATIONS`). That is
deliberate: the judge holds the wording, so an emitter that waters it down fails C10 rather than
redefining it.

**NORMATIVE, ordering.** A new required limitation MUST be emitted by producers **before** a
verifier requires it. Adding one to the required set first turns every certificate already issued
into a refusal, which contradicts the standing rule that existing certificates are not re-issued.

## 3. Trust layers

| layer | what it establishes |
|---|---|
| **L1** | the document is internally consistent with the ledger supplied alongside it |
| **L2** | plus: a third party dated a `(seq, hash)` of that ledger before now |
| **L3** | plus: a signature over the document verifies against a public key the reader supplies |

**NORMATIVE.** A verifier MUST report the layer it actually **reached**, and MUST refuse a
certificate whose declared `trustLevel` is higher than the layer reached. See §A.3.

### 3b. What a signature proves, and what it does not

**NORMATIVE.** A signature establishes **origin, not truth.** A conforming verifier MUST NOT treat
a valid signature as evidence for any claim in the document. Every claim is recomputed from the
ledger regardless of whether the certificate is signed, and a signed certificate whose claims do
not survive recomputation is refused exactly as an unsigned one is.

## 4. The document

**NORMATIVE.** A certificate MUST declare `ledgerDialect` (§A.1) and `limitations` (§2). A
verifier refuses a certificate that omits either.

**DESCRIPTIVE** (the same sentence, split 2026-09-03 — see §9). A certificate is also expected to
declare `claims.ledgerRange` with integer `fromSeq <= toSeq`, `trustLevel`, and `certHash`, and
this verifier refuses one that does not. The three are held back from normative only because no
test yet fixes that refusal: the requirement is not weaker, the evidence for it is.

**NORMATIVE, `certHash`.** `certHash` is the SHA-256 of the canonical JSON of the document **without
`certHash` and without `signature`**. The second exclusion is forced rather than chosen: the
signature is produced over the hash, so it cannot also be inside it. Canonical JSON is UTF-8, keys
sorted at every level, separators `,` and `:`, no inserted whitespace.

**NORMATIVE, money.** Monetary values are strings with exactly two decimals (`"1000.00"`). A number
cannot be compared exactly and a loose string cannot be compared at all.

### 4.1 No plausible defaults

**NORMATIVE.** A value the emitter could not determine MUST be **omitted**, or written as an
explicit `null`. It MUST NOT be filled with a placeholder — not `""`, not `"unknown"`, not `0`, not
a zero-padded hash. A field that looks like evidence and is not is worse than an absent field,
because it also hands out confidence. See rule 1 and rule 5.

### 4.3 No individual trades, no personal data

**NORMATIVE.** A v1 certificate exports aggregates and guardian events only. It MUST NOT contain
`fillPrice`, `executionId`, `orderId` or `quantity`.

**DESCRIPTIVE** (split from the sentence above, 2026-09-03 — see §9). Accounts appear as salted
hashes and are not named. There is no check for this and no test: unlike the four field names
above, "names an account" is not a lexical property a sweep can decide, and a requirement whose
verification nobody has designed is a requirement nobody is enforcing.

---

## Appendix A — what a conforming verifier does

### A.1 Ledger dialects

Two producers write hash-chained ledgers with the **same canonicalisation** and **different entry
schemas**.

| dialect | entry fields | what the entry hash covers | genesis |
|---|---|---|---|
| `guardian-core-v1` | `seq, tsUtc, event, schemaVersion, payload, prev, hash` | everything except `hash` | `"genesis"` |
| `deadman-kit-v1` | `schema_version, seq, ts_utc, kind, actor, payload, prev_hash, hash[, sig]` | everything except `hash` and `sig` | 64 zeros |

`sig` is outside the hashed body in the kit dialect for the same forced reason as `signature` in
§4: it signs the hash.

**NORMATIVE.** The certificate MUST declare which dialect it covers, and a verifier MUST fail closed
when the ledger does not match the declared dialect. **A verifier MUST NOT sniff the dialect from
the file's shape** — sniffing lets a forger hand over a ledger built in whichever schema suits the
lie.

**NORMATIVE.** The check applies to **every** entry, not only the first: a file that changes dialect
part-way must not pass.

### A.2 The chain, and recomputing claims

**NORMATIVE.** A verifier MUST recompute the hash chain over the declared range and MUST recompute
**every claim from the ledger events**, ignoring what the certificate asserts. A claim is a
question put to the events, never a value read from the document.

**NORMATIVE.** A verifier MUST recompute `certHash` (§4) on any path that reaches a verdict. A
verifier that caches it, or skips it in a fast mode, is not conforming — the noise a mismatch makes
is the only thing standing between a shared canonicalisation assumption and silence.

**NORMATIVE, truncation.** A chain cannot be truncated from the front: removing a **suffix** leaves
a prefix that still verifies to genesis. Therefore, when entries are missing and the missing ones
form a suffix of the declared range **and** everything present chains cleanly, a verifier MUST treat
the file as **short, not forged**: the result is *cannot evaluate*, never *contradicted*. A broken
link anywhere, or a hole in the middle, remains a contradiction.

**NORMATIVE.** On such a ledger a verifier MUST NOT compare the certificate's claims against
recomputed figures. The two describe different sets of events, and reporting that difference as a
disagreement charges the holder for the missing tail.

**NORMATIVE, absence.** Recomputation MUST NOT turn an absence of observation into an adverse
claim. Where the events cannot settle a question — a fail-closed episode still open at the end of
the range, with no breach recorded — the answer is *undetermined*, and a verifier MUST NOT report it
as the adverse value.

### A.3 The layer reached versus the layer declared

**NORMATIVE.** A verifier reports `reached` from what it could establish: L1 when the chain and
`certHash` recompute; L2 additionally when supplied third-party anchors match the ledger; L3
additionally when a signature verifies against a supplied public key. Declaring higher than reached
is a **contradiction**, not a warning.

**NORMATIVE.** A verifier MUST print what it could **not** verify, including on success. A verifier
that can only say OK is a rubber stamp.

### A.4 Signatures

**NORMATIVE.** Signature checking is optional tooling. Its absence MUST degrade the reported layer
and MUST NOT validate anything. An unverifiable signature is never treated as valid.

**NORMATIVE.** A verifier MUST NOT print, inside a verdict line, any field it did not check. A field
printed beside `VALID` is read as part of what was verified — `issuer.keyId` is not checked against
anything, so it does not appear there.

**Open, deliberately (§9):** what `keyId` denotes is **not defined by this document**. A PEM carries
no identifier of its own, so any check against it would need a derivation this specification has not
chosen. Until it does, `signature.keyId` and `issuer.keyId` are unverified by design.

### A.5 Exit codes (guarantee C18)

| code | meaning |
|---|---|
| **0** | verified at the layer reported |
| **1** | **CONTRADICTED** — something in the certificate does not survive its own evidence |
| **2** | **UNEVALUABLE** — could not look. Nothing was proved and nothing was disproved |

**NORMATIVE.** 1 and 2 are kept apart. *I caught you lying* and *I could not look* are different
facts, and a tool that collapses them can be disabled by handing it a broken file — or, pointed the
other way, can be made to accuse an honest holder who supplied the wrong file. **A verifier MUST NOT
return 1 for a condition it did not measure.**

**GUIDANCE FOR CONSUMERS, not a conformance requirement** (relabelled 2026-09-03 — see §9). A
script that consumes these codes should treat 2 as *ask for a better copy*, never as a pass. It is
written here because it is the whole point of separating 2 from 0, and it is not NORMATIVE because
this specification binds verifiers, and no test of a verifier can observe what its callers do.

---

## 5. What a verifier must say about its own limits

**NORMATIVE.** When no third-party anchor was supplied, a verifier MUST report, including on
success, that nothing proves the ledger existed before now.

**DESCRIPTIVE** (split from the sentence above, 2026-09-03 — see §9). On every run this verifier
also reports that trading elsewhere is invisible to the document, and that removing the add-on
before start leaves a gap rather than an act. Both are emitted today and neither is pinned by a
test, which is the exact shape this specification exists to distrust: a statement an artefact
makes about itself, that nobody checks.

**NORMATIVE.** When the ledger contains event types the verifier has no rule for, it MUST say so —
naming each distinct type **once** — and MUST NOT refuse on that ground. An unknown event type means
a newer producer, not a broken document. Refusing would let one future event type invalidate every
certificate already issued.

## 6. Guarantees

| | |
|---|---|
| **C9** | no individual trades and no personal data (§4.3) |
| **C10** | the limitations appear verbatim (§2) |
| **C12** | a series of certificates links by `previousCertHash` |
| **C13** | a gap in a series is declared with a reason |
| **C17** | the declared dialect is enforced against every entry (§A.1) |
| **C18** | the three exit codes are kept apart (§A.5) |

## 7. Rule 1 — unknown is omitted, never defaulted

**NORMATIVE.** Restated from §4.1 because it is cited on its own: a value the emitter cannot
determine is omitted or `null`. `certificate-unknown-issuer.json` in `deadman/examples/certificate/`
is the shipped example of the shape.

## 8. Rule 5 — a field that looks like evidence and is not

**NORMATIVE.** A field whose **name promises a specific form** MUST NOT carry a value that cannot
have that form, and a field MUST NOT carry filler (`example`, `tbd`, `""`, …). The rule's own test
is *what does it distinguish?* — if two things that should differ produce the same value, the field
does not measure what its name says and MUST be omitted or renamed.

**NORMATIVE, where it applies.** The check applies to values the **producer** writes. It MUST NOT be
applied to:

- values a **person** supplies (`subject.alias`) — someone whose alias is "unknown" is telling you
  their name, not papering a hole;
- values **copied verbatim from the ledger** (an event name) — these are verified by **comparison
  against the source**, which is strictly stronger. Comparison and shape are **alternative**
  verifications, not complementary: judging the shape of a copied value is judging someone else's
  vocabulary.

## 9. Held back from normative, on purpose

These are things this verifier does today that this document **does not yet bind**. They are listed
so the gap is a decision and not an omission.

### 9.1 Demoted on 2026-09-03, after auditing every requirement against the suite

The rule applied was one line: **a MUST that no test sustains is not published as a MUST.** Nothing
was deleted — each one below still describes what the verifier does, and each says what would
return it to normative. The audit ran because a specification was about to be published, and
writing new public claims while correcting old ones is how the old ones got there.

| demoted | why it has no test | what re-promotes it |
|---|---|---|
| **§1**, the four "this is not" | the behaviour is correct because the verifier never computes a profitability figure; **absence of a feature is not an implementation** | one test asserting no verdict carries such a figure |
| **§4**, `ledgerRange` / `trustLevel` / `certHash` **being declared** | the refusals exist in code and nothing pins them; note that `certHash`'s *computation* is normative and tested — its *presence* is what was untested | a test per field that omits it and asserts the refusal |
| **§4.3**, accounts appear as hashes | "names an account" is not a lexical property a sweep can decide, so no check was ever designed | a decidable definition first, then a check |
| **§5**, trading elsewhere / bypass before start | both are emitted on every run and neither is asserted anywhere | one test reading a successful run's output |
| **§A.5**, what scripts must do with 2 | it binds a **caller**, and no test of a verifier can observe its callers | nothing — it is guidance, correctly labelled |

### 9.2 Normative without a test, deliberately — one, and its reason

**§2, ordering**: a new required limitation must be emitted by producers before a verifier requires
it. It stays NORMATIVE with no test because it is not un-tested, it is **un-testable from here**:
no test run can observe another repository's release order. Its violation is also the least silent
failure this system has — every certificate already issued starts being refused at once. It is the
only case where "no test" does not mean "no detection".

### 9.3 Still open, by design

- **Which fields carry a promise** (§8). Today the set is declared in the verifier. It is not
  normative because the certificate schema is still moving, and freezing the list would freeze the
  schema with it.
- **What `keyId` denotes** (§A.4). Undefined on purpose until a derivation is chosen; naming one
  here would make it the de-facto standard without the decision being taken.
- **The `precedingEvent` field.** A verifier recomputes the event immediately preceding a
  fail-closed entry and compares it. **The name is normative; the value's meaning is not**: it is
  adjacency, not cause, and this document does not authorise any reader to treat it as a cause. Both
  known implementations derive it the same way, so their agreement is **consistency, not
  corroboration** — it does not establish that the field means what a reader assumes.
- **The three-state `limitRespected`.** The verifier distinguishes *respected*, *breached* and
  *undetermined* internally; the certificate field is still a boolean. The type is not yet normative
  because changing it is the emitter's side of the contract.
