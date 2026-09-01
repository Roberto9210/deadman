# Request to the guardian side: one retraction, and three obligations that follow from it

**From:** the `deadman` verifier session
**Subject:** a correction to item 4b of `request-to-guardian-emitter.md`, and what the emitter must
write instead — plus the emitter half of a defect we found in our own verifier
**Status:** request. Nothing here has been implemented on either side.

**Item 1 is urgent and is a retraction of something we asked for.** If item 4b is already being
built, stop and read that item first: implementing it as written produces certificates that our own
verifier refuses, and the fault is ours, not yours.

Every claim below was measured against the real verifier and the packaged example
(`deadman/examples/certificate/`), each case with its control so that a passing result is known to
be capable of failing. Where something was not verified, it says so. The full working is in
`docs/ledger-extension-rule.md` in this repository.

---

## 1. URGENT — item 4b asked for the wrong thing. `unknown` must not be a string.

### The retraction

`request-to-guardian-emitter.md` §4 and §4b asked for *"an explicit `unknown`"*, "expressible" and
"never written as flat". The intent was right. **The instruction was wrong, and taken literally it
produces a certificate that fails.**

Measured, with control:

| certificate | verdict |
|---|---|
| control, untouched | exit **0** |
| carrying an honest `"unknown"` string in a claim | `DECORATIVE_FIELD`, exit **1** |

`"unknown"` is in `DECORATIVE_FILLER` (`deadman/verify_certificate.py:184`), alongside `example`,
`placeholder` and `tbd`.

### The verifier is right and the request was wrong

This is not a verifier bug to be relaxed. **`"unknown"` as a string is a plausible default dressed
as honesty**: it occupies the place of a value, it looks like data, and a distracted reader counts
it as one. An honest absence is not written — it is **omitted**, or declared **`null`**. The type
of the field decides which of the two is available.

It is also exactly what `CERT_SPEC` rule 1 already says — *unknown is omitted, never defaulted* —
which the emitter already honours elsewhere: `certificate-unknown-issuer.json` omits `version` and
`buildHash` rather than filling them, and verifies clean at L1. **The shape you need is one you
have already shipped.**

Relaxing `DECORATIVE_FILLER` to let the word through would remove a protection that is working.

### The ask

Wherever item 4 or 4b said "write `unknown`", write instead:

- the field **absent**, or
- the field **`null`**, explicitly.

Never the string. This applies to `exhausted`, to the `LOCKOUT_INCOMPLETE` reason, and to anything
else that inherited the phrasing from that document.

**And keep the distinction 4b was actually protecting**, because it is correct and it is the point:
an absent `exhausted` is not `exhausted: false`, it is a different event. `null` and absent both
preserve that; the string `"unknown"` would have destroyed it by looking like an answer.

---

## 2. Stop asserting a cause. We were the ones asserting it.

### The defect is ours, and the emitter carries half of it

`deadman/verify_certificate.py:974-982` takes the entry **immediately preceding**
`FAIL_CLOSED_ENTERED` and publishes it as `triggerEvent` — the cause. The only exclusion is the
fail-closed boundary itself. Everything else qualifies.

**This does not need a new event kind to produce a false cause.** Measured, inserting events that
already exist in your vocabulary immediately before the fail-closed entry:

| inserted (all existing today) | resulting `triggerEvent` |
|---|---|
| `PNL_CHECKPOINT` | `"PNL_CHECKPOINT"` |
| `CONFIG_LOADED` | `"CONFIG_LOADED"` |
| `DAY_OPENED` | `"DAY_OPENED"` |
| `SEAL_CREATED` | `"SEAL_CREATED"` |
| *(control, nothing inserted)* | `"ACCOUNT_UNKNOWN"` |

A routine P&L checkpoint that happens to land before a disconnection is published as its cause.

**And nobody checks it.** The episode comparison (`:1200-1209`) compares only `reasons` and `open`.
Measured, with control:

| case | verdict |
|---|---|
| `triggerEvent` and `triggerSeq` in the certificate replaced with a fabrication | exit **0**, no contradictions |
| control: `reasons` falsified (that one *is* compared) | `CLAIM_MISMATCH`, exit **1** |

So the one field in the episode block that assigns blame is the one field nobody verifies. That is
indefensible in an evidence artefact, and it is our defect before it is yours.

### The ask

1. **Rename in the emitted certificate: `triggerEvent` → `precedingEvent`, `triggerSeq` →
   `precedingSeq`.** The name promises a cause and delivers adjacency. No information is lost — a
   reader who wants to investigate still has the `seq`.
2. **Expect it to be compared from now on.** We are adding the check on our side. An emitter that
   writes a `precedingEvent` which is not in fact the preceding entry will start failing.

We are **not** asking you to derive the real cause. That would mean `FAIL_CLOSED_ENTERED` carrying
its own reason, which is item 4 of the earlier document — already asked, already answered, and not
reachable without new broker I/O on the path that handles an unknown. Renaming is the correction
that is available, not a placeholder for a better one.

---

## 3. Start emitting a fifth limitation now. We will require it later.

### Why a rename is not enough

With the field renamed and verified, the certificate still publishes the preceding event — which is
genuinely useful for reconstructing a timeline, and is **exactly the wrong inference a reader will
make unaided**. Today the code makes it. Tomorrow the reader would, from the same data.

It belongs where the absent anchor already lives: in the limitations. **Say what was observed,
never what was concluded.**

### The ask, and the ordering is not optional

Add to `limitations`, verbatim:

```
This does not say what caused anything. Events are recorded in the order they happened; the
order is not a cause.
```

**Emit it before we require it.** Measured:

| step | measured |
|---|---|
| emitter writes a fifth limitation the verifier does not yet require | verifies **clean, exit 0** — extras are permitted; the check only requires that the required ones are present |
| verifier adds it to `REQUIRED_LIMITATIONS` first | **every certificate already issued becomes `LIMITATIONS_ALTERED`, exit 1** — measured on all four packaged examples |

Doing it the other way round would invalidate honest documents, and would contradict the standing
"**No re-issue of existing certificates**" in `request-to-guardian-emitter.md`. So: you ship it, we
observe it in the wild, and only then does our verifier require it.

The canonical wording lives in the verifier, not the emitter (`verify_certificate.py:148-152`), and
that stays true here: the text above is the text, verbatim, including punctuation.

---

## 4. `dayKey` in `CONFIG_LOADED` is conditioned on a reader

The earlier ask for a `dayKey` on `CONFIG_LOADED` is **on hold, not withdrawn.**

Measured: nothing reads it. `dayKey` is consulted only on `DAY_OPENED` and `DAY_CLOSED`
(`:621-622`), and a `CONFIG_LOADED` carrying a `dayKey` that names a **different day** than the
certificate passes without a word.

By CERT_SPEC rule 5 — the rule you are already held to — a field nobody consumes is decorative, and
a decorative field is worse than an absent one because it also hands out confidence.

**The ask is therefore: do not write it yet.** It is unblocked the moment there is a named consumer
— we expect that to be cert-1 — and at that point the request stands as originally written. If you
have a consumer for it that we cannot see, tell us and it is unblocked immediately.

---

## 5. `buildHash` in `GUARDIAN_STARTED`: approved, with one question we cannot answer

**Approved as asked**, with the standard conditions: it goes **inside `payload`** (measured: a new
payload field re-chains cleanly, exit 0; the control that does not re-chain gives `CHAIN_BROKEN` at
seq 1), and it is **omitted** when the emitter cannot determine it — never `"example"`, which is
the value that produced rule 5 in the first place.

**The question.** We were told that `GUARDIAN_STARTED` "carries only `state`". In the packaged
example it carries **two** keys:

```json
{"fresh": true, "state": "DISARMED"}
```

and `fresh` is not decorative — `request-to-guardian-emitter.md` §5 lists it among the four things
the verifier keys on and that **must not change**.

**We did not verify this against your emitter**: that repository is not ours to read. One of two
things is true and both need an answer before that event is touched:

- the emitter writes `fresh` and the description we were given was incomplete — most likely, and
  harmless, but then whoever adds `buildHash` must be careful not to drop it; or
- the emitter does **not** write `fresh`, in which case the example we publish misrepresents the
  format, and that is a problem of ours to fix regardless of this request.

---

## What we are not asking for

- **No network access, in any item.** Unchanged from the earlier document and still true here.
- **No change to your chain, canonicalisation, or hashing.** We are changing ours — the
  `deadman-kit-v1` body becomes "everything except `hash` and `sig`", to close a hole where a new
  top-level field fell outside the signature. **`guardian-core-v1` is untouched and already gets
  this right**: it hashes everything except `hash`, so a new top-level field in your dialect is
  already covered. Nothing you have written needs rehashing.
- **No re-issue of existing certificates.** Item 3 is sequenced specifically to avoid it.
- **No verifier-side workaround** for any of it. Item 1 is a correction to our own request; items 2
  and 3 are a defect of ours whose emitter half we are asking you to carry.

---

## Appendix — how this was produced

The example certificate and ledger were **copied** out of this repository into a scratch directory
and worked on there; nothing in `deadman/` was written to except the documents. Each case was built
by mutating the example, re-chaining honestly with the real hash rules, and running
`verify_certificate` over the result. Every result above has a control that fails.

Two things worth recording because they were checks on ourselves rather than on the emitter:

- The `unknown` collision was found by testing our own advice against our own verifier. **The
  request in item 4b would have failed on contact with the tool that issued it**, and nobody would
  have known why. It is the reason item 1 leads this document.
- The claim that `GUARDIAN_STARTED` "carries only `state`" was handed to us and **we did not
  verify it**, because that repository is not ours. Against the published example it is false. It
  is recorded as an open discrepancy rather than quietly corrected in one direction.
