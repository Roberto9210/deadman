# Request to the guardian side: five emitter changes, ordered by what each buys

**From:** the `deadman` verifier session
**Subject:** changes to the certificate emitter (`Certificate.cs`, `tools/IssueCertificate`, `ExportDay`)
**Status:** request. Nothing here has been implemented on either side.

This comes out of running the verifier against **two real certificates and the real 3,211-entry
ledger** for the first time. Every claim below was reproduced against those files; the appendix
says how. Where something was not verified, it says so.

The list is ordered by what each item buys, not by effort. Items 1-3 are one problem in three
parts and are worth more together than separately; 4 and 5 are independent.

---

## 1. Bound the ledger range to the day the certificate names

### The defect

The emitter takes `lo = min(seq)` over the whole ledger. It never scopes to the day it names. On
the 2026-08-22 certificate, the header says one day and `claims.ledgerRange` says `1..1423`, which
is two days.

Measured on the real file:

| | over the declared range `1..1423` | over 2026-08-22 alone (`206..1423`) |
|---|---|---|
| fail-closed episodes | **12** | **7** |
| process restarts | **25** | **15** |

**It compounds.** Day 60's certificate will declare 60 days, and the growth is invisible because
the header still names one date.

**And it multiplies with a second defect.** Under the current definition `limitRespected` is
`false` if any lockout falls anywhere in the range. With the range growing backwards for ever,
**one lockout on one day turns every future certificate `false`, permanently** - the product's own
success becomes a permanent mark against its user.

### The ask

`fromSeq` should be the `DAY_OPENED` of the day named, not `min(seq)` of the file.

The rule as we would state it, and the reason for stating it this way:

> **The set of days a certificate's range covers must equal the set of days it names.**

Not "one day". Not more and not less than what is named. A certificate that names three days and
covers three days is correct. **Please do not implement this as "always truncate to one day"** -
`--series` exists precisely to chain days, and a future maintainer reading a narrower rule would
"fix" a legitimate multi-day export by cutting it.

### Two implementation notes we would rather hand over than have rediscovered

- Anchor the day window on **`DAY_OPENED`, not `SEAL_CREATED`**. `SEAL_CREATED` is the natural
  choice for continuity and **cannot be used here**: it carries `expiresAtUtc`, `ledgerHeadHash`,
  `sealDurationMs` and `sealHash`, and **no `dayKey`**. `ARMED`, `DAY_OPENED`, `DAY_CLOSED`,
  `SEAL_EXPIRED` and `DISARMED` all carry one.
- If the day has not closed inside the range, the window ends at the end of the range.

### What it buys

It stops an active harm that grows daily, it fixes the counts, and it removes half of the
`limitRespected` permanence problem. **This is the only item on the list that gets worse every day
it is not done.**

---

## 2. Export a trimmed ledger, with the anchor inside it

### The defect

Bounding the range in item 1 fixes the counts and **does not fix what the trader discloses.**

`ExportDay` and the CLI write `stem + ".json"` and `stem + ".html"` and nothing else. **There is
no ledger excerpt in the export.** To verify anything, the receiver needs `ledger.jsonl` - so the
trader hands over the entire history.

That is the part that outweighs the wrong counts. A document whose whole purpose is to *bound*
what you share cannot silently make you reveal more than its name says. It is not an arithmetic
error, it is a broken promise, and it is broken against the person the tool exists to protect.

### Verified: a trimmed ledger works, and needs nothing added to it

We tested rather than assumed.

- A segment starting mid-file **verifies on its own**: entries `206..3211` gave `chain_ok: True`.
  The linkage check is skipped for the first in-range entry, and every entry already carries its
  own `prev`. **No extra anchoring field is needed** in the excerpt.
- A **forged** pre-segment head is caught, provided item 3 is in place. We replaced the `prev` of
  the first entry with zeros and **re-chained the whole segment honestly** - internally flawless,
  `chain_ok: True` - and against the real anchor it produced `ANCHOR_MISMATCH` and
  `TRUST_LEVEL_OVERSTATED`, exit 1. The `prev` of the first entry is an input to its own hash,
  which folds forward into the anchored one.

### The ask

Write a third file alongside the JSON and the HTML: the ledger entries for the day named, verbatim
and unmodified, one JSON object per line. **Verbatim matters** - re-serialising changes bytes and
breaks the hashes.

### What it buys

The trader hands over one day instead of their whole history, which is what the document already
promises in its name.

### What is lost, stated honestly

- **Nothing about chain verification.** A segment self-verifies, as above.
- **Nothing about forgery resistance.** A fabricated segment verifies exactly as well as a real
  one at L1 - but that is already true of the full ledger. The chain proves internal consistency,
  never provenance. Cutting the file does not make this worse.
- **Nothing about prior days.** They stop being visible, which is the point, and
  `previousCertHash` plus `--series` remains the voluntary way to prove continuity across days.
- **The external anchor, unless the day's own anchor falls inside the trimmed segment.** This is
  the real cost and it is why item 3 is on the list. Note what it means in practice: because
  anchoring is a user action rather than something the guardian does, trimming the ledger is only
  safe for a trader who actually anchors per day. **For a trader who never anchors, trimming costs
  nothing, because there was never an L2 to lose** - which is today every trader.

---

## 3. Emit the anchoring payload with the certificate, and declare when there is no anchor

### A correction to our own first draft, because the reason matters

We first wrote this item as "the guardian should anchor at day close." **That was wrong.**
Anchoring means publishing a hash to a third party, which means opening a socket, and the guardian
does not open sockets. No telemetry, no cloud, no licence check is a declared product principle,
and it is part of why the thing is trustworthy at all. An emitter obligation that quietly required
network access would have broken a promise larger than the one we were trying to fix.

**How anchoring works today, verified rather than assumed.**
`examples/git_anchor_publisher.py` is user code, and says so in its own header: *"This is YOUR
code, not the library's: deadman never touches the network."* The user supplies a publisher; the
publisher does the I/O. The verifier receives anchors as a **separate file** (`--anchors`), not
from the ledger.

### The state today is not "partially anchored"

| | |
|---|---|
| anchors on certificate 2026-08-21 | `[]` |
| anchors on certificate 2026-08-22 | `[]` |
| declared trust level on both | **L1** |
| `ANCHOR_*` events in the 3,211 real entries | **none - the guardian vocabulary has none** |

**Nobody has ever anchored.** On the guardian side L2 is not partially reached; it has never been
reached. Every certificate the product has issued sits at the layer the verifier itself describes,
in its own words, on every run:

```
NO_EXTERNAL_ANCHOR - no third-party anchor was supplied, so nothing proves this ledger
                     existed before now: a full rewrite with recomputed hashes passes L1
```

### The ask, which is small and needs no network

1. **Emit the anchoring payload alongside the certificate**: the head of the day's last entry,
   `{seq, hash, tsUtc}` and nothing more - no payloads, no PII. That is the artefact a user hands
   to a timestamp authority or commits to a protected branch. Producing it costs no connectivity.
2. **Declare its absence in the document.** A certificate with no anchor should say on its face
   that it is L1 and what L1 does not survive, rather than leaving that to whoever happens to run
   the verifier.

### The cadence is real, and it is not the emitter's

The last anchor of the day is the one that buys the day. Measured against the real day `206..1423`:

| anchor at | exit | L2 covers up to | left unanchored |
|---|---|---|---|
| seq 206 | 0 | 206 | **1,217 entries** |
| seq 500 | 0 | 500 | 923 entries |
| seq 900 | 0 | 900 | 523 entries |
| **seq 1423** | 0 | **1423** | **0 - the whole day** |

An anchor taken when the day opens covers nothing at all, and the verifier reports the shortfall
by itself: `ANCHOR_COVERAGE_PARTIAL - anchors cover up to seq N; entries N+1..1423 are outside L2
coverage`. An anchor *outside* the day's segment is worse than partial - it is unusable, giving
`ANCHOR_MISMATCH` and `TRUST_LEVEL_OVERSTATED`, and the level falls to L1.

**But this is a workflow obligation on the user, not a code obligation on the guardian**, and it
belongs in the product documentation rather than in the emitter.

### If L2 is ever to be routine rather than heroic

There is a shape that gets automatic cadence without the guardian opening a socket, and this
project already ships it. `deadman`'s own `Ledger` takes `publisher=`, `anchor_every_n` and
`anchor_every_s`, drives the cadence itself, and calls **user code** to do the I/O - recording
`ANCHOR_FAILED`, then `ANCHOR_STALE` with a visible flag, if publishing keeps failing, and never
halting execution. The library never touches the network and the anchoring is still automatic.

We are **not** asking for this here; it is a larger decision than the rest of the list. We name it
because the alternative is the consequence below, and that should be a deliberate choice rather
than something nobody wrote down.

### The product consequence, in one line

**If anchoring is a manual daily act, L2 costs a human action every day, and a trader who never
performs it has only L1 - the layer we ourselves declare insufficient against anyone with disk
access. Today that trader is every trader.**

That sentence belongs in the product documentation, not only in the spec.

### The limit of anchoring, so it is not oversold

An anchor pins the exact bytes of the head that preceded a segment, but not that those bytes are
the hash of an honest history. **Nothing before the first anchor in time is covered.** This is the
standing limit and it is identical for a full ledger whose first anchor is late - it is not
introduced by trimming.

---

## 4. Record positions **and working orders** at `FAIL_CLOSED_ENTERED`, with `unknown` expressible

### The defect

`Guardian.cs:634` logs the event with a `reason` and nothing else:

```csharp
Log(Ev.FailClosedEntered, JsonValue.Obj().Set("reason", reason));
```

So when the guardian goes blind, the ledger records **that** it went blind and never **what it was
blind to**. Those are different risks: blindness that began flat is an inconvenience; blindness
that began with an open position and resting orders is the exposure the guardian exists to remove.

### The ask

Add to the payload, at the moment fail-closed is entered:

- open positions
- **working orders** - fail-closed blocks new entries but does not cancel resting ones, so an
  order placed while healthy can fill while blind. Positions alone do not describe the risk.
- an explicit `unknown` when the guardian genuinely cannot see the account

**`unknown` must be expressible and must never be written as flat.** That collapse is exactly the
defect that made `limitRespected` unusable, and re-committing it in a new field would be worse
than leaving the field out.

### ANSWERED by the guardian side, and the answer withdraws the ask

We asked whether the state was reachable at that point. **It is not, and the reason is worse than
"not implemented yet".**

- There are **two** emitters of `FAIL_CLOSED_ENTERED` (`Guardian.cs:221` and `:655`) and both write
  exactly `{reason}`. The method is `EnterFailClosed(string reason)`: it receives a string and
  holds no position or order state.
- Reaching that state means calling `IBrokerActions.GetPositions` / `GetWorkingOrders` - **broker
  I/O, added to the path that handles an unknown.**
- And the common trigger for fail-closed is a disconnected or unknown account, which is **exactly
  when the broker does not answer.** The read fails precisely when it would matter.

So this is not a field to add, it is a design change - and the direct discriminator does not exist
at the moment it would be needed. Recorded here as **not reachable without new I/O**, which is a
different statement from the *not verified* this item originally carried.

Reported by the guardian side. **We did not verify it ourselves**: that repository is not ours to
read past what was already quoted here.

### What this changes on our side, written down so nobody waits for it

The duration threshold in the `outcome` design was labelled **provisional**, pending exactly this
discriminator. **That label is now wrong and has been removed.** The threshold is the answer rather
than a placeholder for a better one, and the reason belongs in the spec: the direct measurement is
unavailable at the moment of blindness, not merely unrequested.

A "provisional" that will never be replaced is a promise the document cannot keep - the same defect
as a decorative field, one layer up, in our own planning instead of in a payload.

### The deferred alternative, with its limit named now rather than later

The guardian side proposed and deferred: record positions and working orders on every **normal**
tick, when the broker does answer, and carry the last known value with its timestamp into the
blindness event. **No new I/O on the dangerous path** - the read happens when it is cheap and
reliable.

We agree it is worth doing, and agree it is not urgent. Its limit belongs beside it from the start:
**a value with an age is not the current value, and the longer the blindness lasts the less it is
worth.** An aged position reported without its age would be a new decorative field, and this
document would have caused it.

---

## 4b. The same rule at `LOCKOUT_INCOMPLETE`: always write the reason, never leave it inferable

### Confirmed by the guardian side; the ledger we hold still cannot corroborate it

Confirmed by the guardian side with the detail we lacked. Three sites emit `LOCKOUT_INCOMPLETE`:
`Guardian.cs:572` (`step: cancel`), `:590` (`step: flatten`) and `:615`. **Only `:615` carries
`attempts` and `exhausted`**; the first two are per-step exceptions and do not carry the field at
all.

**We still have no evidence of our own.** The 3,211-entry ledger we hold contains zero
`LOCKOUT_INCOMPLETE`, zero `FLATTEN_VERIFIED` and zero `LIMIT_BREACHED` - the enforcement path has
never fired in data we can see.

### The case that will actually arrive, which neither side had

From a real run on the guardian side against real fills, 2026-08-22:

```
19:20:42.637  LIMIT_BREACHED  dayLoss=50.00
19:20:42.706  FLATTEN_REQUESTED
19:20:42.706  LOCKOUT_INCOMPLETE      <- transient
19:20:43.203  ORDERS_CANCELLED        (retry)
19:20:43.208  FLATTEN_VERIFIED        <- 502 ms later
```

**`LOCKOUT_INCOMPLETE` appears half a second BEFORE the success**, because flattening is a real
market order and takes time to fill. Sixteen soak runs never produced it: with synthetic P&L the
flatten is instantaneous, so that path is structurally unreachable for the soak.

This is the ordinary case, not a failure, and it settles a rule that was previously only an
argument: **only the LAST of these events is the outcome.** A verifier that treats any
`LOCKOUT_INCOMPLETE` as terminal would report the product's normal successful lockout as an
incomplete one - the same shape of defect as `limitRespected`, in the replacement built to fix it.

The guardian side already requires `exhausted` to be present on its own reading (`GetBool` returns
null for an absent key), so both sides now treat absence as a different event rather than as
`false`.

### Why it matters

If it is right, then **an absent `exhausted` is not `exhausted: false`. It is a different event.**
The lockout stopped because a step threw, not because the guardian spent its attempts - and those
are different stories:

| | what it says |
|---|---|
| attempts exhausted | the guardian did everything it was designed to do and the position survived - a broker or market story, in which the design worked and the world did not cooperate |
| a step threw | the guardian's own code failed mid-lockout with its retry budget unspent - a product-defect story, in which it might have succeeded had it not failed |

### The ask

**Write the reason explicitly at all three sites.** Not a field that is present in one place and
absent in two, but a named value always written: attempts spent, step failed, and an expressible
`unknown` - the same requirement as item 4, applied to a different event.

The reason to push this to the producer instead of inferring it on the reading side: **absence is
ambiguous in a way that never resolves.** A missing field could mean "a step threw" or "this
certificate came from an older emitter that never wrote the field", and no amount of care by the
reader separates those two. Inferring would be defaulting, which is the rule being enforced
everywhere else in this document.

---

## 5. A heartbeat that survives `DISARMED` and `LOCKED`

Restating the earlier request (`docs/request-to-guardian-heartbeat.md`) so this list is complete.

`Guardian.cs:368` returns before the checkpoint when disarmed:

```csharp
if (_state.Kind == StateKind.Disarmed) { Persist(); return; }
```

and `Guardian.cs:372-377` does the same for `LOCKED`. So in the two states where a trader most
wants evidence the guardian was alive, it writes nothing, and the verifier cannot distinguish
*present and idle* from *absent*.

**What must not change**, because the verifier keys on it: `GUARDIAN_STOPPED`, `GUARDIAN_STARTED`,
`SEAL_EXPIRED.basis`, and the `fresh` marker.

### What it buys

It improves a figure that is already honest without it. Ranked last for that reason - the current
output does not mislead, it merely says *cannot evaluate* more often than it needs to.

---

## Schema note: `daysCovered` is a hardcoded default

Separate from the five, and the most telling thing we found.

```csharp
public long DaysCovered { get; set; } = 1;   // Certificate.cs:67
DaysCovered = 1,                             // tools/IssueCertificate/Program.cs:87
```

**`continuity.daysCovered` is never derived from anything.** On the 2026-08-22 certificate, whose
range covers two days, it says `1`. It is false, and it is false in the one field that existed to
reveal precisely the defect in item 1. The field that would have caught this was never connected.

Two asks:

- **Derive it or delete it. Never a default.** A field that looks like evidence and is not is
  worse than an absent field, because it also hands out confidence.
- **If multi-day certificates are to be permitted, `session` must be able to name several days.**
  Today `session.dayKey` is a singular string while `daysCovered` is a count - the schema
  contradicts itself. `verify_series` adds a third constraint in the same direction:
  `SERIES_DUPLICATE_DAY` enforces *one certificate per day*, keyed on `dayKey`. Either the schema
  can express a multi-day certificate coherently across all three places, or it should not pretend
  to in one of them.

---

## What we are not asking for

- **No network access, in any item.** The guardian opens no sockets and nothing here asks it to.
  Item 3 asks only that it *produce* an anchoring payload; publishing that payload stays entirely
  outside the guardian, in user code. If any item above reads as requiring connectivity, we have
  written it badly and want to know.
- **No change to the chain, the canonicalisation, or the hashing.** Nothing above requires it.
- **No re-issue of existing certificates.** The two that exist declare their range openly and
  their claims genuinely hold over the range given. They are not dishonest documents; the range
  was the emitter's choice, not the holder's, and the verifier will not accuse them of it.
- **No verifier-side workaround.** These are emitter obligations. We would rather the verifier say
  *cannot evaluate* than paper over a gap in the evidence.

---

## Appendix - how this was produced

Source files: `certificate-2026-08-21.json`, `certificate-2026-08-22.json` and `ledger.jsonl`,
copied out of the guardian repository and worked on **outside** it. Nothing in that repository was
written to.

Every table above is output from `deadman.verify_certificate` run against those copies. The forged
segment, the anchor sweep, and the mid-file segment result were produced by constructing the
mutation, re-chaining it, and confirming the verifier's verdict changed - a clean case and a
mutated case for each, so that a passing result is known to be capable of failing.

The anchor tables were produced by supplying constructed anchors to the verifier, since the real
certificates carry none. The anchoring behaviour of the product itself - user-supplied publisher,
no network in the library - was read from `examples/git_anchor_publisher.py` and `deadman/ledger.py`
in this repository, not inferred.

Three results worth recording because they were checks on ourselves rather than on the emitter:

- The 2026-08-21 certificate verifies as **contradicted** on `issuer.version: '1.0.0.0'`
  (`DECORATIVE_FIELD`) in addition to the range.
- During the anchor sweep, the rule-5 check fired `FIELD_BELIES_ITS_NAME` on **our own** fabricated
  test anchors, whose `tsUtc` was a placeholder. The check was doing its job on the analyst.
- Item 3 as originally drafted would have asked the guardian to open a socket, in a product whose
  stated principle is that it never does. It was caught in review on the verifier side, before the
  document was sent. It is left visible in the item rather than quietly rewritten, because the
  correction is more useful to a reader than a clean draft would have been.
