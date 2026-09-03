# Example certificates — all four are synthetic

**Nothing in this directory is a real trading session.** These files are fabricated so you can
run the verifier before anyone hands you a certificate to check. They are not a real ledger, not
a real account, and not evidence of anything.

They are, however, built with the **real hashing rules**: the chain in `ledger.jsonl` is a genuine
hash chain and every `certHash` is a genuine hash of its document. That is the point — a fake
whose mechanics are real is what lets you watch the verifier work, and then watch it refuse.

```bash
pip install deadman-kit
python -m deadman.verify_certificate certificate.json ledger.jsonl
```

## One lesson per file

| file | teaches | verifier says |
|---|---|---|
| `certificate.json` | an honest day, issuer fully determined | `VERIFIED at L1`, exit **0** |
| `certificate-tampered.json` | a falsified claim — `changeAttemptsWhileSealed` changed from 2 to 0, `certHash` recomputed so the document is internally perfect | `CLAIM_MISMATCH`, exit **1** |
| `certificate-truncated.json` | a range declared short so the inconvenient part of the day falls outside it. Contains no false statement | `RANGE_TRUNCATED`, exit **1** |
| `certificate-unknown-issuer.json` | what the emitter writes when it cannot determine its own version or build hash: it **omits** both fields rather than defaulting them | `VERIFIED at L1`, exit **0** |

The last one exists because CERT_SPEC rule 1 — *a value the emitter could not determine is
omitted or written as an explicit `null`, never filled with a placeholder* — is otherwise visible
only in prose. A reader learns the shape from the
examples, so the examples have to contain the shape. They are deliberately kept in separate files:
the truncated-range example teaches one thing and does not get other lessons stapled to it.

## What is fabricated, and how you recognise it

One row per field, because the tells are not equally visible. `alias`, `sealHash` and `version`
give themselves away the moment you open the file. **`buildHash` does not** — sixteen hex
characters that look exactly like a real fingerprint — so its preimage is written out below and
you can recompute it. *A tell you have to take on faith is not a tell.*

| field | value in these files | how you recognise it |
|---|---|---|
| `issuer.tool` | `deadman-guardian` | Real name of the emitter; the only thing here that is not fabricated |
| `issuer.version` | `0.1.0-beta+000…0` | Real **shape** (that is the lesson), fabricated value: the build-metadata segment is **forty zeros** where a real build carries its source commit |
| `issuer.buildHash` | `1218e58ca4ab455b` | **Recompute it** — see below. A real one is sha256 over an assembly's bytes; this is sha256 over a sentence |
| `subject.alias` | `example-…` | Starts with `example-` in every file. The signal lives here because `alias` is chosen by the trader and its name promises nothing |
| `subject.accounts` | `a2a836b8fa8bf17e` | Salted hash of `Sim101`, NinjaTrader's **simulator** account, with the salt `c1d0f4a9` repeated eight times — printed in `make_example.py`, so no real installation salt is involved |
| `commitment.sealHash` | `9f2c1a7e5d3b8046` + 48 zeros | **Padded with zeros.** No real SHA-256 looks like that |
| `commitment.armedAtUtc` | `2026-08-19T13:21:00.000Z` | Every timestamp in these files falls on an exact seven-minute multiple, which no real session does |
| `commitment.sealExpiryUtc` | `2026-08-19T22:00:00.000Z` | Same |
| `commitment.personalDailyLossLimit` | `600.00` | Round figure, chosen for the example |
| `commitment.firmDailyLossLimit` | `1000.00` | Round figure, chosen for the example |
| `session.dayKey` | `2026-08-19` | A day on which nothing was traded by anyone |
| `session.openedUtc` | `2026-08-19T13:07:00.000Z` | Seven-minute multiple, as above |
| `session.timezone` | `America/Chicago` | Real zone name; the session it describes is not |
| `certHash` | varies per file | **Not fabricated** — genuinely sha256 over the document, which is why the verifier accepts it |
| `anchors` | `[]` | Empty, always. An anchor is a third party's attestation and a fabricated one would be the most misleading thing this directory could hold, so there are none — which is also why every file is `trustLevel: L1` |

### Recompute `issuer.buildHash` yourself

The preimage is this exact sentence, UTF-8, no trailing newline:

```
deadman-guardian example build, not a real assembly
```

```bash
python -c "import hashlib; print(hashlib.sha256(b'deadman-guardian example build, not a real assembly').hexdigest()[:16])"
# 1218e58ca4ab455b
```

That is the value in `certificate.json`, `certificate-tampered.json` and
`certificate-truncated.json`. A real `buildHash` is sha256 over the bytes of the assembly that
issued the document; this one is sha256 over a sentence saying it is not one. The form is real
because the form is the lesson — the value is checkably not.

`certificate-unknown-issuer.json` has no `buildHash` at all, which is what the emitter does when
it cannot determine one.

### The verifier gives them away too, without being asked

Every run prints what it could not establish, and on these files that list opens with
`NO_EXTERNAL_ANCHOR`: nothing proves this ledger existed before now, and a full rewrite with
recomputed hashes would pass L1. That warning is true of these examples in the strongest possible
sense — they *were* written from scratch a moment ago.

## Regenerating

```bash
python deadman/examples/certificate/make_example.py
```

The committed bytes must come back out unchanged; `tests/test_c_certificate_example.py` checks
that, and `tests/test_c_certificate_example_hygiene.py` checks that these files keep obeying the
rules the spec applies to real certificates — including that the published set always shows both a
determined issuer and an omitted one. That second file exists because this directory once drifted:
the examples were correct when written, the emitter changed, and the artefacts aged in silence.
