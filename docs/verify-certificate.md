# How to contradict a deadman session certificate

You have been handed a file claiming that some trader operated under a self-imposed daily loss
limit and respected it. **This page is how you disprove it.**

That is the right way round. A certificate you cannot attack is a certificate that proves
nothing, so the tool that judges it is public, runs on your machine, needs nothing from us, and
prints what it could *not* establish even when everything passes.

```bash
pip install deadman-kit
python -m deadman.verify_certificate certificate.json ledger.jsonl
```

Two files, one command. No account, no key, no network, no sign-up. The verifier has **zero
runtime dependencies** and opens no socket.

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
   This exists because of a real hole: claims are recomputed over the *declared* range, so a
   certificate that simply declares a shorter one hides everything outside it.
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
real certificate. `examples/certificate/` holds a ledger, an honest certificate over it, and the
same certificate with one number quietly changed.

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
pip install deadman-kit[verify-sig]
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

## If you find a case it misses

That is the interesting outcome, and it has already happened once: the range check in step 3
exists because a certificate truncated one entry before a breach verified clean, with every
recomputed number agreeing, because the arithmetic was honest over a window chosen to exclude
the truth.

The adversarial suite is `tests/test_c_certificate.py` (the eighteen named guarantees) and
`tests/test_c_certificate_attacks.py` (probes invented afterwards). Open an issue with a
certificate and ledger that should be refused and is not.
