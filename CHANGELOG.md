# Changelog

Release process (every version): a release is cut ONLY from a git tag `vX.Y.Z` that must equal
`project.version` in `pyproject.toml` (the release workflow fails loudly on a mismatch, before building).
The tag runs the **same suite as CI** (`.github/workflows/deadman.yml` reused via `workflow_call`:
ubuntu/windows/macos × Python 3.10/3.12/3.14, real-process tests unmarked, every skip
visible with its reason), then builds sdist + wheel with `python -m build`, installs the wheel into a clean venv with
`--no-deps` from a neutral cwd and runs a smoke flow asserting zero non-stdlib modules loaded, and only
then publishes to PyPI with `pypa/gh-action-pypi-publish` under **trusted publishing** (environment
`release`, `id-token: write`, no API tokens in secrets). Workflow: `.github/workflows/release.yml`. The human half - what to check before tagging, and how to confirm a release really landed without being fooled by PyPI's cached `/json` endpoint or pip's cached index - is in [`docs/RELEASING.md`](https://github.com/Roberto9210/deadman/blob/main/docs/RELEASING.md).

## 0.3.0 - 2026-09-03

**Why a minor bump and not a patch.** Two contracts changed: the shape of `--json` and the meaning
of the exit codes. Both were measured for consumers before being touched, and both have none we
can find - zero outside this repository's own assertions. The version was raised anyway, because a
version number is an affirmation about compatibility, not a report of how much happened to break.
Shipping an exit-code change as `0.2.3` would make that affirmation false for anyone who arrives
later. 451 tests, 1 skipped.

- **`certHash` and `trustLevel` are now computed before anything can return early.** This is the
  one place where a MUST already published in `CERT_SPEC.md` was contradicted by the code that
  cites it: section A.2 says a verifier MUST recompute `certHash` on any path that reaches a
  verdict, and five reachable paths reached a verdict without doing it. A document that stops the
  verifier early - a missing dialect, a missing range - was therefore also a document whose own
  hash was never checked, which is the wrong way round: the cheaper, purely-local check is the one
  an adversary most wants skipped. It now runs first, and `CERTHASH_MISSING` is separated from
  `CERTHASH_MISMATCH` so that "you did not give me one" stops being reported as "yours is wrong".
- **Two refusals moved from exit 2 to exit 1, and the rule that sorts them is now written down.**
  `DIALECT_MISSING` and `RANGE_MISSING` were being reported as *I could not look* when they are
  *I caught you lying*: both fields are mandatory, and the question that decides every case is
  whether a fully conforming certificate could produce this condition. If yes, it is 2 and the
  remedy is to ask for a better copy; if no, the document itself is the defect and a better copy
  will never arrive. `DIALECT_UNKNOWN` and `DIALECT_MISMATCH` stay at 2 for exactly that reason
  and are commented so nobody "fixes" them to match. The rule is section A.5 of `CERT_SPEC.md`,
  now normative.
- **A contradiction outranks an unevaluable.** When both are present the exit code is 1. Measuring
  something and finding it false is not undone by failing to measure something else - and without
  this, a certificate that had been caught could still buy a 2 by also being unreadable somewhere
  else, which is a strategy rather than an accident.
- **`--json` no longer publishes the result of a check that did not run.** `chainOk`,
  `certHashOk` and `signature` are OMITTED when the verifier stopped before reaching them, rather
  than carrying a default. They were emitting `false`, `false` and `"ABSENT"` - which a consumer
  reads as *the chain is broken, the hash is wrong, there is no signature* when the truth was that
  none of the three had been looked at. Omission rather than `null` is deliberate and follows the
  document's own section 4.1: `null` is falsy in every language that would consume this, so it
  would preserve the exact false reading being removed. `--json` also gained `spec`, naming the
  document version the run was judged against.
- **`CERT_SPEC.md` now travels inside the wheel, and the tool can say where it is.** The document
  the source has cited since it was written lived only in the repository, so a reader who
  installed from PyPI and followed the citation arrived nowhere. It is packaged, `--spec` prints
  its path on disk without needing files or a network, and a test opens the built wheel and
  compares the packaged copy against the repository's byte for byte. That test also settled a
  claim this project had been making since 0.2.1: the `[tool.setuptools.package-data]` block was
  inert. The wheel is identical with it, without its entry, and without the block. What fixed the
  examples gap back then was moving them inside the package, not the globs, and the comment
  crediting the globs has been corrected rather than quietly deleted.
- **Every requirement in `CERT_SPEC.md` was audited against the suite, and six were demoted from
  normative to descriptive.** The rule applied was one line - a MUST that no test sustains is not
  published as a MUST - and nothing was deleted: each demoted paragraph still describes what this
  verifier does, and each says what would return it to normative. Two of the six came back the
  same day, when the tests that sustain them arrived with the exit-code work. Section 9 carries
  the table, including the single requirement left normative with no test and the reason it is
  un-testable from here rather than merely untested.
- **Seven citations in the shipped source pointed at documents that do not exist**, or at sections
  of the wrong one. All seven now resolve, and the sweep that finds them declares what shape of
  citation it can and cannot see, because the seventh was a relative markdown link the original
  pattern was blind to.

Internal, and not part of the distribution: a `scripts/replace.py` that makes the safe way to edit
a file shorter than the unsafe one, after a `sed -i` mangled a line here; `scripts/check_against_old.py`
extended so the checking tools can finally be controlled against their own previous versions; and
a declared, verified escape hatch in the line-endings guard, which caught a real regression in this
release. A repair can be declared and the declaration is checked against the file's own history -
you can back out of a normalisation, you cannot declare your way into one.

## 0.2.2 - 2026-08-22

**An audit of our own promises.** The certificate verifier met real production data for the first
time and reported `REACHED L1` on every certificate ever issued - the layer this project itself
describes as one a rewrite by anyone with disk access passes. That turned the question around:
what do we claim about a layer nobody has reached? The answer was that we claimed it in the
present tense, in the shortest and least-qualified string we publish. Nothing below changes the
chain, the canonicalisation, the hashing, or any verdict. 305 tests.

- **The PyPI Summary described a capability that is off by default.** 0.2.1 shipped
  "hash-chained and externally anchored ledger". The library anchors nothing unless you pass a
  `publisher` - the default is `None` and `_maybe_anchor` returns immediately without one - so
  that phrase described a ledger that was anchored exactly never, and it reads identically whether
  anchoring is on or off. A phrase that does not distinguish anything is decoration. It now reads
  "hash-chained ledger anchorable to a third party by a publisher you supply".
- **The threat model led with the anchor in the present tense.** "The external anchor is the
  guarantee: the ledger tip `(seq, hash)` is published to a third party" stated as fact what
  anchoring *would* give. Rewritten as the guarantee it would give, and what a default `Ledger`
  does without it.
- **The quick start showed only the anchored construction**, with the clarification nineteen lines
  further down. It now shows both ways to build a `Ledger`, with the consequence beside each.
- **The sentence that existed nowhere**: *"Without a publisher there is no anchor, and everything
  stays at L1."* A grep for "off by default" or "opt-in" against the anchoring returned a single
  match, and it was about dependency extras. The sentence is now in the threat model and beside
  the snippet an operator copies.
- **A whole verifier run never contained the strings `L2`, `L3` or `--anchors`.** It told the
  reader that L1 does not survive an attacker with disk access and left them no way to learn that
  a better layer existed, let alone how to reach it. `NO_EXTERNAL_ANCHOR` now names L2 and the
  flag that gets there, inside the block the reader is already looking at, and the headline reads
  `VERIFIED at L1, THE FLOOR LAYER` so that `VERIFIED` cannot be quoted as a grade. A run that
  reaches L2 says neither - the remedy is tied to the absence, not printed unconditionally.
- **The release gate never looked at the Summary.** It ran on 0.2.1, passed, and the offending
  string shipped anyway, because the gate only read the long description. It now reads both, and
  refuses any present-tense claim about an optional capability (`OPTIONAL_AS_PRESENT`, blunt on
  purpose like `STALE_CLAIMS`, and documented as such so nobody softens it later). Controlled
  against the real 0.2.1 Summary: two offences, refused.
- **The gate itself is now tested** (`tests/test_release_gate.py`), against the strings that
  actually shipped rather than invented ones - including the 0.2.0 stale claim, to check the older
  rule did not regress while the new one was added.

## 0.2.1 — 2026-08-22

**Everything here came from one cold-start run**: a stranger's path, in a fresh virtualenv outside
the repository, installing only from PyPI and reading only published pages. It took 2 minutes 26
seconds to verify a certificate arriving via GitHub — and did not complete at all arriving via
PyPI, which is where `pip install` sends people. The log is published at
[`docs/COLD_START_LOG.md`](https://github.com/Roberto9210/deadman/blob/main/docs/COLD_START_LOG.md),
including the point where a reasonable reader gives up.

- **`python -m deadman.verify_certificate --example`** — verifies a certificate **that ships
  inside the package**. No files to find, no download, no network, no GitHub. The first useful
  command now works ten seconds after installing. It ends by printing where the other three
  examples live, as an absolute URL.
- **The worked examples ship.** They lived at the repository root, the README said they "ship",
  and the wheel contained none of them. They now live in `deadman/examples/certificate/` and are
  packaged — one canonical copy, so there is nothing to drift.
- **The trust layers are explained in the README itself**, not behind a link. `REACHED L1` is the
  headline of every run and the published 0.2.0 page contained the string `L1` zero times. The
  table says what L1, L2 and L3 prove, and states plainly that **L1 alone does not survive an
  attacker with disk access**.
- **Every relative link in the README is now absolute.** PyPI renders the description on
  pypi.org, where `docs/verify-certificate.md` reaches nothing. Thirty-six links were relative.
- **The "no ledger" message says what to do.** It used to end one sentence early: accurate, and
  silent about the only possible next action. It now explains what a ledger is to someone who has
  never heard the word, and says to ask whoever handed over the certificate for it.
- **`--help` no longer cites specification identifiers** (`C12/C13`) that a reader cannot look up,
  and defines L1/L2/L3 where it names them.
- **A release gate**: `scripts/check_published_description.py` inspects the built wheel's own
  metadata and refuses to publish a description containing stale claims (`not on PyPI yet`,
  `coming soon`, …) or relative markdown links. Run from `release.yml`, deliberately not from the
  test suite: `main` may be mid-repair, but **a PyPI description cannot be edited after
  publication** — only a new release replaces it, which is what 0.2.1 is.

Nothing about the verification logic changed. A certificate that verified under 0.2.0 verifies
identically here.

## 0.2.0 — 2026-08-21

Adds a **verifiable session certificate verifier**: the part a third party runs to *disprove* a
claim that a trader operated under a self-imposed daily loss limit. Nothing existing changed
behaviour; 0.1.0 code is untouched.

- **`deadman.verify_certificate`** — a pure function `verify_certificate(cert, entries, anchors,
  pubkey) -> CertReport`, plus `python -m deadman.verify_certificate certificate.json ledger.jsonl`.
  It **ignores what the certificate asserts and recomputes every claim from the ledger events**;
  a signature proves origin, not truth, so nothing here trusts one. Reports the trust layer it
  actually **reached** (L1 chain / L2 external anchor / L3 signature), and prints an explicit list
  of what it could **not** verify — on success too, because a verifier that can only say OK is a
  rubber stamp.
- **Exit codes `0` verified / `1` contradicted / `2` could not evaluate**, kept apart on purpose:
  "I caught you lying" and "I could not look" are different facts, and a tool that collapses them
  can be disabled by handing it a broken file.
- **Two ledger dialects**, `guardian-core-v1` and `deadman-kit-v1`, **declared by the certificate
  and enforced**. Sniffing the shape would let a forger supply a ledger built in whichever schema
  suits the lie.
- **Series checks**: links between days, a day removed from the middle, undeclared gaps, gaps
  without a reason, a day certified twice, a certificate naming itself as its own predecessor.
- **Adversarial suite**: 18 named guarantees (C1–C18) and 13 attacks invented afterwards, plus
  mutation control that sabotages the verifier eleven ways and requires the suite to go red for
  each. 65 cases in total; 230 in the package.
- **`examples/certificate/`** — a runnable worked example: one ledger and three certificates over
  it (honest, falsified, truncated), regenerable by `make_example.py` and verified on every test
  run so the documentation cannot drift from the tool.
- **Optional extra `verify-sig`** (`pip install deadman-kit[verify-sig]`) for Ed25519 signature
  checking. **The base package keeps zero runtime dependencies**: extras are opt-in and the
  verifier reaches cryptography through `importlib`, so the stdlib-only import scan still passes.
  Without the extra the signature reports `NOT_VERIFIED` and degrades to L2 — never to "valid".
- **`docs/verify-certificate.md`** — written for the reader who wants to contradict us, including
  **the attack this verifier was wrong about**: claims are recomputed over the range the
  certificate *declares*, so a certificate truncated one entry before a breach verified clean at
  L1 with `limitRespected: true` and every recomputed number agreeing, because the arithmetic was
  honest over a window chosen to exclude the truth. Recomputing catches a dishonest *answer*; that
  was a dishonest *question*. Closed by checking the declared range against the session's own
  `DAY_OPENED`/`DAY_CLOSED`, and calibrated by harm rather than shape so an honest mid-session
  export is reported as incomplete, not as a lie.

Known limits, stated rather than implied: L1 alone does not survive an attacker with disk access
and says so on every run; L3 proves the local emitter's origin, never that our software produced
the document; and `tradesObserved` is not recomputable from the current event vocabulary, so it is
not judged.

## 0.1.0 — 2026-08-18

First release. Distribution name on PyPI: **`deadman-kit`** (`pip install deadman-kit`); the import name is `deadman`. Implements `docs/SPEC.md` v0.1 (closed 2026-08-18).

- `KillSwitch`: existence of one file stops everything, entries and exits; never opened or parsed.
- `EntryHalt`: persistent, blocks new exposure only; unreadable file = halted; concurrent-writer detection.
- `Intent` / `resolve_units`: mandatory units (`USD`/`BASE`/`CONTRACTS`), no defaults, failures carry the intent.
- Exit predicates: `spot_long_only_is_exit` (default, declared spot long-only) and `net_position_is_exit`.
- `DailyLimits`: net-of-fees P&L, unknown fee never zero, UTC rollover ledgered, clock-backwards fail-closed,
  unreadable stats block entries only (exits evaluated before the file is read).
- `OrderSanity` + `quantize`: every missing input denies by name; floor to venue step; never enlarge to a minimum.
- `Ledger`: hash chain, OS lock, anchored rotation with cross-segment `verify`, external anchoring through a
  user publisher, `ANCHOR_STALE` flag on sustained failure, optional signer/verifier hooks. Zero dependencies.
- `BrokerPort` (guarantees G1–G9) and `HonestExecutor`: write-ahead intent, deterministic client order id,
  timeout ⇒ order presumed alive and resolved by client id, no blind retry, honest partial/duplicate fills,
  everything outside the state machine ⇒ `UNKNOWN_STATE` + halt, `startup()` reconcile before any intent.
- Conformance: 11 of 13 test groups, 165 collected cases; G8 and the equity half of G10 declared out of
  scope with rationale (SPEC §6b).
