# How to contradict a deadman session certificate

You have been handed a file claiming that some trader operated under a self-imposed daily loss
limit and respected it. **This page is how you disprove it.**

That is the right way round. A certificate you cannot attack is a certificate that proves
nothing, so the tool that judges it is public, runs on your machine, needs nothing from us, and
prints what it could *not* establish even when everything passes.

```bash
git clone https://github.com/Roberto9210/deadman.git && cd deadman
python -m deadman.verify_certificate certificate.json ledger.jsonl
```

Two files, one command. No account, no key, no network, no sign-up. The verifier has **zero
runtime dependencies** and opens no socket.

> **Not on PyPI yet.** The published `deadman-kit` package is 0.1.0, which predates this
> verifier, so `pip install deadman-kit` does **not** get you the module today — clone the
> repository instead. When a release is cut, `pip install deadman-kit` becomes the one-line
> install and this note goes away. Checked rather than assumed: installing 0.1.0 into a clean
> virtualenv and running the command gives `No module named deadman.verify_certificate`.

---

## What it actually does

It **ignores what the certificate asserts and recomputes every claim from the ledger events.**

That distinction is the whole design. The certificate says `limitRespected: true`; the verifier
never reads that boolean to decide — it counts `LIMIT_BREACHED` events itself and compares.
A signature, if present, proves who emitted the document, not whether it is true, so nothing
here trusts one.

Concretely, in order:

1. **Dialect.** The certificate must *declare* which ledger format it covers. If the file does
   not match, verification stops there. Sniffing the format would let a forger hand you a ledger
   built in whichever shape suits the lie.
2. **Chain.** Recomputes every hash over the declared range and checks each link. A broken chain
   names the first `seq` that fails.
3. **Range.** Checks that the declared range actually covers the session the certificate names.
   This step exists because of a hole this verifier had and did not catch: claims are recomputed
   over the *declared* range, so a certificate that declares a shorter one hides everything
   outside it, truthfully. [The full account is below](#the-attack-that-got-past-this-verifier).
4. **Claims.** Recomputes `limitRespected`, `lockoutsTriggered`, `changeAttemptsWhileSealed`,
   `ordersRejectedWhileLocked`, `failClosedEpisodes` and `clockAnomalies` from the events and
   contradicts any that disagree.
5. **certHash.** Rehashes the document and compares.
6. **Anchors**, if you supply them, and **signature**, if you supply a key.
7. **Prints the trust layer it reached** — not the one the certificate declares. Declaring
   higher than reached is a contradiction, not a warning.

---

## Try it right now, on files that ship with the package

The repository carries a worked example so you can run the verifier before anyone hands you a
real certificate. `examples/certificate/` holds one ledger and three certificates over it: an
honest one, one with a number quietly changed, and one that lies by declaring a shorter range —
that last one is [its own section below](#the-attack-that-got-past-this-verifier), because it is
the case this verifier was wrong about.

### 1. An honest certificate

```bash
python -m deadman.verify_certificate examples/certificate/certificate.json examples/certificate/ledger.jsonl
```

```
deadman-kit - verifiable session certificate
==============================================================
ledger dialect  : guardian-core-v1  (16 entries read)
declared range  : seq 1..16

  chain         OK
  certHash      matches
  claims        6 recomputed from events
  anchors       0 checked
  signature     ABSENT

  DECLARED      L1
  REACHED       L1

COULD NOT VERIFY - true even when everything above passes:
  - NO_EXTERNAL_ANCHOR: no third-party anchor was supplied, so nothing proves this ledger
    existed before now: a full rewrite with recomputed hashes passes L1
  - OTHER_VENUES: the guardian sees one platform and the configured accounts; trading
    elsewhere is invisible to this document
  - PRE_START_BYPASS: removing the add-on with the platform closed leaves a gap, not an act
  - TRADES_OBSERVED: no event in this vocabulary records a fill count, so `tradesObserved`
    is not recomputable and is not judged here

RESULT: VERIFIED at L1 (exit 0).
```

**Read the bottom half.** Those four lines are printed on success, deliberately. A verifier that
only says OK is a rubber stamp, and the most important thing this one tells you is what it
could not establish.

### 2. The same day, with two inconvenient events removed

`certificate-tampered.json` is identical except that `changeAttemptsWhileSealed` — the number of
times the trader tried to loosen their own limit and was refused — was changed from 2 to 0, and
its `certHash` was recomputed so the document is internally consistent.

```
CONTRADICTIONS - the certificate does not survive its own evidence:
  - CLAIM_MISMATCH: `changeAttemptsWhileSealed`: certificate says 0, the events say 2

RESULT: CONTRADICTED (exit 1). 1 finding(s).
```

Note what caught it. The chain is fine. The `certHash` matches. **Hashing alone would have
passed this document.** It falls because the verifier counted the `CONFIG_CHANGE_REJECTED`
events itself.

### 3. Something it cannot read

```
COULD NOT EVALUATE - certificate unreadable: Expecting property name enclosed in double quotes
```

Exit 2 — and that is a different fact from exit 1, which is the next section.

---

## The three exit codes

| code | meaning | what you should conclude |
|---|---|---|
| **0** | **VERIFIED** at the layer printed | Nothing in the document contradicts the ledger. Now read the *could not verify* list, because that is where the real limits are |
| **1** | **CONTRADICTED** | Something in the certificate does not survive its own evidence. The findings are named, one per line |
| **2** | **UNEVALUABLE** | The verifier could not look: unreadable file, invalid JSON, no declared range, undeclared dialect. **Nothing was proved and nothing was disproved** |

**1 and 2 are kept apart on purpose.** "I caught you lying" and "I could not look" are different
facts, and a tool that collapses them can be disabled by handing it a broken file. If you are
scripting this, treat 2 as *ask for a better copy*, never as a pass.

---

## The three trust layers

The certificate declares one. The verifier prints the one it **reached**. If the declared level
is higher, that is a contradiction.

| | what it proves | what it does not |
|---|---|---|
| **L1** — local chain | The record was not edited clumsily: every line links to the one before | **Nothing against someone with disk access.** They can rewrite the whole file and recompute every hash, and L1 passes. This is stated, not hidden — there is a test whose purpose is to demonstrate that it passes |
| **L2** — external anchor | A third party held `(seq, hash)` at a point in time, so everything up to there **existed before then** and is unchanged | Nothing after the last anchor. The verifier prints `coveredUpToSeq` and tells you what falls outside |
| **L3** — signature | The document came from the holder of that key and was not edited afterwards | **Not that our software emitted it**, and **not that it is true.** The private key lives on the trader's machine, so a signature attests the trader, not the tool. A valid signature over a false claim is a valid signature over a false claim |

**L1 alone is weak and the tool says so on every run.** If the certificate matters to you, ask
for anchors: `--anchors anchors.json`, a JSON list of `{"seq": N, "hash": "..."}` records held by
someone who is not the trader.

Signature checking needs an optional extra, and without it the verifier reports
`NOT_VERIFIED (extra not installed)` and degrades to L2 — never to "valid":

```bash
pip install cryptography          # from a clone; or deadman-kit[verify-sig] once released
python -m deadman.verify_certificate certificate.json ledger.jsonl --pubkey issuer.pem
```

---

## Checking a run of days

One good day proves very little. A series with no gaps is the thing worth showing, and each
certificate carries the previous day's `certHash`:

```bash
python -m deadman.verify_certificate day1.json ledger.jsonl --series day2.json day3.json
```

This checks the links between days, that no day was removed from the middle, that gaps are
declared with a reason rather than omitted, that no day appears twice, and that no certificate
names itself as its own predecessor. Each certificate still has to be verified against its own
ledger separately — the series check says nothing about the contents of any one day.

---

## Using it from Python

The CLI is a thin shell over a pure function. It reads nothing and prints nothing:

```python
import json
from deadman.verify_certificate import verify_certificate

cert = json.load(open("certificate.json"))
entries = [json.loads(l) for l in open("ledger.jsonl") if l.strip()]

report = verify_certificate(cert, entries)          # optionally anchors=..., pubkey_path=...
print(report.reached_level)                          # "L1" | "L2" | "L3" | None
print(report.recomputed["lockoutsTriggered"])        # counted from the events, not read
for finding in report.contradictions:
    print(finding.code, finding.detail)
for finding in report.unverified:
    print(finding.code, finding.detail)
```

`--json` gives the same content as machine-readable output.

---

## What this tool does not do

- **It does not tell you whether the trader made money.** A certificate is not a track record,
  and v1 does not assert P&L as a result at all.
- **It does not tell you whether they traded elsewhere.** The guardian sees one platform and the
  accounts it was configured with. A clean certificate is compatible with a disaster in another
  account.
- **It cannot see what happened before the software started.** Someone who removes the add-on
  with the platform closed leaves a gap in the record, not a confession.
- **It is not an audit.** Nobody inspected this trader. It is a machine's assertion about a
  record that machine kept, and this tool checks the assertion against the record.

Those four sentences are also required, verbatim, inside every certificate. If they are missing
or reworded, the verifier refuses the document — the canonical text lives in this public package
(`REQUIRED_LIMITATIONS`), not in the emitter, so softening them is not something an issuer can do
quietly.

---

## The attack that got past this verifier

Published because it is the useful part. Every checked-in example above passes or fails as
designed; this one is the case the tool was wrong about, how it was wrong, and what it cost to
fix. Run it yourself:

```bash
python -m deadman.verify_certificate examples/certificate/certificate-truncated.json examples/certificate/ledger.jsonl
```

### The attack

Every claim is recomputed over the range the certificate **declares**. So a liar does not
falsify a number — falsified numbers are exactly what recomputation catches. **A liar declares
a shorter range.**

`certificate-truncated.json` is built over the same ledger as the honest example and stops at
`seq 6`, one entry before the first refused attempt to loosen the limit. Everything in it is
then computed honestly over that window:

- `changeAttemptsWhileSealed: 0` — true, over seq 1..6
- `failClosedEpisodes: []` — true, over seq 1..6
- `limitRespected: true` — true, over seq 1..6
- chain recomputes, `certHash` matches, document internally perfect

Before the fix, this verified **clean, at L1, exit 0**. Nothing in it was false. It was a set of
true statements about a window chosen so the inconvenient part of the day fell outside it.

### Why no amount of claim-checking finds it

The verifier's central idea is *do not trust the document, recompute from the events*. That idea
is what fails here, and it fails structurally rather than by oversight: the recomputation is
**parameterised by the range the document supplies**. Recomputing harder, adding claims, or
comparing more fields would all have agreed with the liar, because the liar and the verifier were
reading the same six entries and doing the same correct arithmetic on them.

A dishonest *answer* is caught by recomputing. A dishonest *question* is not.

### How it is closed

Using the one thing a certificate cannot truncate away: **it names a day.** If the ledger holds
that day's `DAY_OPENED` before the declared range, or its `DAY_CLOSED` after it, the document
does not cover the session it claims to describe.

```
CONTRADICTIONS - the certificate does not survive its own evidence:
  - RANGE_TRUNCATED: the certificate is for 2026-08-19 but that day's DAY_CLOSED is at
    seq 16, past the declared range 1..6, and 3 material event(s) fall outside it
    (CONFIG_CHANGE_REJECTED, FAIL_CLOSED_ENTERED) - the range excludes part of the session
    it claims to describe

RESULT: CONTRADICTED (exit 1). 1 finding(s).
```

The finding names what was excluded. A reader should not have to diff two files to learn what a
certificate left out.

### How it is calibrated, which is the harder half

The obvious fix — *contradict any certificate whose range does not cover its whole day* — is
wrong, and shipping it would have made the check worthless.

A trader who exports at 14:00 on a session that closes at 17:00 produces exactly that shape. So
does someone hiding a breach. Treat both as lies and every honest mid-session export is
slandered; people learn the finding means nothing and stop reading it. **A check that cries wolf
is a check that gets ignored, which is the same as not having it.**

So severity follows the harm, not the shape:

| situation | verdict |
|---|---|
| Range stops inside the session, **nothing material outside it** | `SESSION_NOT_FULLY_COVERED`, **exit 0**. An incomplete document, not a lie. It says so, and suggests exporting again after the session closes |
| Range stops inside the session, **material events outside it** | `RANGE_TRUNCATED`, **exit 1**, naming them |
| Material events outside the range, **no `DAY_CLOSED` to anchor on** | `POST_RANGE_MATERIAL_EVENTS`, **exit 0** — it says it cannot tell an early export from a truncation, rather than picking whichever side is convenient |

"Material" means events whose absence changes what the document says about the trader:
`LIMIT_BREACHED`, `ORDER_REJECTED_LOCKED`, `CONFIG_CHANGE_REJECTED`, `FAIL_CLOSED_ENTERED`,
clock anomalies, and the tamper events. They are used **only** to describe what a range leaves
out — never to recompute a claim.

### What it cost

The check was found by asking "what have we not tried?" *after* all eighteen named guarantees
were green, which is the only moment that question gets an interesting answer. Eighteen
guarantees, a mutation-tested suite, and an independent second implementation had all agreed
that the verifier was correct — and it was, at everything it had been asked.

Third-party anchors are the deeper answer to this whole family of problem, and they are worth
asking for. But an anchor only proves the ledger is unchanged; it says nothing about which slice
of it a certificate chose to describe.

## If you find a case it misses

That is the interesting outcome, and the section above is what it looks like when it happens.

The adversarial suite is `tests/test_c_certificate.py` (the eighteen named guarantees) and
`tests/test_c_certificate_attacks.py` (thirteen probes invented afterwards, including this one).
Open an issue with a certificate and a ledger that should be refused and is not.
