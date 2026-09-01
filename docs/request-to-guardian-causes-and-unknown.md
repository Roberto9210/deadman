# Request to the guardian side: one retraction, and three obligations that follow from it

**From:** the `deadman` verifier session
**Subject:** two corrections to earlier claims of ours, what the emitter must
write instead, the one field the `?? ""` cleanup must not touch — plus the emitter half of two
defects we found in our own verifier
**Status:** request. Nothing here has been implemented on either side.

**Item 1 is urgent, and it is a retraction:** if item 4b is already being built, stop and read it
first — implementing it as written produces certificates that our own verifier refuses, and the
fault is ours, not yours.

**Item 1b carries a retraction of its own** (we called `session.timezone: ""` a live functional
failure; your measurement shows that emitter cannot produce it). What survives there is not urgent
but is still load-bearing: **one of the six `?? ""` fields must not be omitted**, and if the
cleanup ships uniformly before we land our fix, a protection disappears without anyone deciding to
remove it.

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

## 1b. URGENT — the six `?? ""` sites: omit is right for five of them, and wrong for `dayKey`

### The good news first, measured

**RETRACTED (2026-09-01), and the retraction is ours.** An earlier version of this item claimed
`session.timezone` comes out empty today through the LT-2 path, called it a functional failure on a
reachable path, and put it at the top of our work order. **That was wrong**, and your side measured
why: `sessionResetTimeZone` is in `GuardianConfig.RequiredKeys`, so a config lacking it does not
parse and never becomes a seal; the emitter reads the zone from the sealed snapshot, the same
source as Core; and all 6 certificates issued on that machine carry `America/Chicago`. **That
emitter cannot produce `""` in that field.**

We had one measurement of our own and one statement from your side, and we published the pair as
"confirmed". A measurement plus an unverified statement is not a confirmation — the result
inherits the quality of the **worse** half. The rule we adopted from it is in
`docs/ledger-extension-rule.md` §5.9.

**What still stands, re-measured on our side**, and it is the reason this item stays in the
document rather than being deleted:

On `session.timezone`, which we were told is one of the six:

| what the emitter writes | verdict |
|---|---|
| `""` — today's `?? ""` | **exit 1, `DECORATIVE_FIELD`** |
| `null` | exit 0, clean |
| field **absent** | exit 0, clean |

The empty string is in `DECORATIVE_FILLER` alongside `example` and `placeholder`, and the rule-5
check treats it as exactly what it is: a field that looks like content and carries none. **Both of
the fixes you were going to make — omit, or null — verify clean.** So item 1's instruction (absent
or null, never a filler string) covers this too.

**We are not changing `DECORATIVE_FILLER` over this.** Exit 1 on `""` is correct behaviour; it
simply is not being triggered by that emitter today. `?? ""` goes back to being what it was before
we overstated it: an honesty defect, worth fixing on its own terms, not an outage.

**And one thing is now open rather than answered:** we were told `session.timezone` is one of the
six `?? ""` sites, and your measurement says it cannot go empty. Either it is not one of the six,
or it is one and is unreachable. We are not guessing which — that is ask 1 below, and it is now
the only thing that resolves this.

Note also that `null` is not a loophole we are tolerating: `_promise_violations` exempts it
explicitly (`verify_certificate.py:211`). A declared `null` is a first-class way to say "I do not
know this", by design.

### The trap, and it is in the same object

**Do not apply the omit pattern to `session.dayKey`.**

`certificate-truncated.json` is our shipped example of the most dangerous lie the format allows: a
range declared short so the inconvenient part of the day falls outside it. Measured, on that exact
file:

| the same lying certificate | verdict |
|---|---|
| as shipped | **`RANGE_TRUNCATED`, exit 1** |
| with `session.dayKey` omitted | **exit 0** |
| with `session.dayKey` set to `null` | **exit 0** |
| with the whole `session` block omitted | **exit 0** |

The whole day-coverage check lives inside `if day is not None:`. No `dayKey`, no check.

**To be precise, because we overstated this in an earlier note:** it is not total silence, it is a
**downgrade**. Without `dayKey` the verifier still reports `POST_RANGE_MATERIAL_EVENTS` and still
names the three material events — but as `cannot_verify` at exit 0 rather than a contradiction at
exit 1. What is never said is that the day-coverage check did not run, and the replacement message
explains the gap with the wrong cause: it reads *"with no DAY_CLOSED for this session"* when there
**is** a `DAY_CLOSED` — what is missing is which session it belongs to.

That is our defect and we are fixing it, severity following the harm: material events outside the
range will be a contradiction whether or not `dayKey` is present. The reason it is in your document
is the timing: if the `?? ""` cleanup ships before our fix, and the pattern is applied uniformly
across all six sites, a certificate can lose the protection without anybody choosing to remove it.

### The ask

1. **Tell us which six sites they are.** We can see one (`session.timezone`) and are guessing at
   the rest. We want to check each against what the verifier does with it, before you change them.
2. **For each: omit or `null`, never `""`.** Both are clean.
3. **`session.dayKey` is not in that set.** If it is currently one of the six, it needs a real
   value, not an omission and not a null — it is the anchor the range is judged against.

The rule we are adopting on our side, which is what separates the two cases:

> **Omit a field that carries a VALUE. Never one that carries a SCOPE.**

`timezone` carries a value: omitting it loses a datum. `dayKey` carries the scope the document is
judged against: omitting it switches the judgement off. They are neighbours in the same object and
the same fix produces the right answer on one and a downgraded verdict on the other.

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

## 6. Send us the enumerated vocabulary, so our filters can be tested against it

### Why we are asking

Your side raised a sharp question: `ACCOUNT_UNKNOWN` is a legitimate event name that reaches the
certificate as a `triggerEvent` value and as a `reasons` key — does our `DECORATIVE_FILLER` list
catch it and fail the first real disconnection episode?

**It does not.** Measured: the comparison is on whole values, not substrings, so `ACCOUNT_UNKNOWN`,
`UNKNOWN_STATE` and `unknown_account` all pass; only the bare word `unknown` matches. And the
packaged example certificate already carries `"triggerEvent": "ACCOUNT_UNKNOWN"` and
`"reasons": {"ACCOUNT_UNKNOWN": 3}` and verifies clean at exit 0 — the case is already in our
regression surface.

**But we found the same fault one level down, and it is real.** The other rule-5 check derives a
field name from the last path segment, and the keys of `reasons` and `clockAnomalies.byType` are
**event names**. So an event whose name ends in `hash`, `loss`, `limit` or `utc` produces a false
`FIELD_BELIES_ITS_NAME` against its own integer count. Measured: `SEAL_HASH`, `CONFIG_HASH`,
`DAILY_LOSS`, `SOFT_LIMIT` and `EXPIRES_AT_UTC` all fire.

We swept the 27 event names we can see plus our own 19 kinds: **zero collisions today.** But
`SEAL_MISMATCH` is safe only because it ends in `match` rather than `hash`. That is luck, and
`CONFIG_HASH` is a name nobody would think twice about — `CONFIG_LOADED` already carries a
`configHash` in its payload.

We are fixing the check on our side. **We also want the test that keeps it fixed**, and that test
needs your vocabulary.

### ANSWERED — and the answer changed the ask

**The enumeration arrived, and the most valuable thing in it was not the list.** It was this:
`triggerEvent` is a **passthrough** (`Certificate.cs:223`) — it copies whatever the ledger row says
with no validation against any enum.

That killed the test we were about to write. A sweep asserting *"these 37 names do not collide"*
asserts a **result**. A real ledger can carry names from older or future builds — production
already shows 24 distinct `buildHash` values across 8,027 entries — so the set of today is not a
property.

**And it exposed a hole our own fix would not have closed.** We had proposed inverting the
promise-check so it only applies to schema-owned names. Measured against 144 adversarially
generated names:

| a name arriving as… | today | with our inversion alone | with inversion + provenance |
|---|---|---|---|
| a `reasons` **key** | **31 fail** | 0 | 0 |
| a `triggerEvent` **value** | **44 fail** | **44 fail** | 0 |

The inversion fixes keys. `triggerEvent` is a *value*, and the filler check reads every string
value on every path. Names like `UNKNOWN`, `NONE`, `TBD`, `CHANGEME` — none of which exist today,
all of which someone could choose tomorrow. **Without your note we would have shipped half a fix
with a test that passed.**

So the fix is scoped by **provenance**, and `triggerEvent`/`precedingEvent` is not shape-checked at
all — it is **compared against the ledger**, which is strictly stronger and is already item 2's ask.

`subject.alias` is excluded on the same principle and **the emitter should not refuse it either**:

> **The filler check applies to fields the PRODUCER fills. Never to fields a PERSON supplies.**

A producer writing `"unknown"` is papering a hole. A person writing `"unknown"` is telling you their
name. Same string, different things, and what separates them is where it came from.

Measured: `alias` = `"unknown"` / `"example"` / `"none"` now verify clean, while `buildHash`
= `"example"` or `"test"`, `timezone` = `""` and `version` = `"1.0.0.0"` are still caught. Whole
certificate suite: 100/100.

**One note for whoever reads the sweep:** your C-tests emit `buildHash: "test"`. That **must** keep
firing `DECORATIVE_FIELD` — `"test"` in a field the producer writes is genuine filler. The point is
only not to harvest values out of those tests as if they were production vocabulary.

### The residual ask

The lists are still worth having, as a smoke case rather than as the guarantee:

1. **Every event name the guardian can emit.** We assembled 27 from what is visible in this
   repository and we have no way to know whether that is all of them.
2. **Every state / reason / enum literal that can appear as a value in a certificate** — the
   `state` in `GUARDIAN_STARTED`, lockout reasons, seal bases, anything of that shape.

The second list matters for a residue we cannot close alone: our filler comparison is
case-insensitive, so a **state literal** spelled `"UNKNOWN"` or `"NONE"` would be flagged, while an
*event* named `ACCOUNT_UNKNOWN` is fine. We are keeping the case-insensitivity deliberately —
`TODO`, `TBD` and `XXX` are filler that gets written in capitals, and a case-sensitive match would
let all three through — so the protection has to come from proving non-collision instead. We cannot
prove it against a vocabulary we cannot read.

The rule we settled on, which is why we are asking you for a list rather than changing our matcher:

> **A filler list is tested against the REAL vocabulary, and its requirement is DEMONSTRATED
> NON-COLLISION — not a rule about the shape of strings.**

**If either list contains a bare `UNKNOWN` or `NONE` as a value, tell us and we will treat it as a
live defect on our side, not on yours.**

### The rule this comes from

Written down because it has now bitten both sides of the system on the same day — your message
containment was going to ban the word `"cancelled"`, and `"0 orders cancelled"` is the true report
of a sweep that did happen; ours was going to ban `"unknown"`:

> **A lexical containment must match exactly what it forbids, and is tested against the legitimate
> values it could catch.** A filter that forbids too much fails loudly on honest content, which is
> worse than not having it: it teaches people to switch it off.

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
