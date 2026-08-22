# Changelog

Release process (every version): a release is cut ONLY from a git tag `vX.Y.Z` that must equal
`project.version` in `pyproject.toml` (the release workflow fails loudly on a mismatch, before building).
The tag runs the **same suite as CI** (`.github/workflows/deadman.yml` reused via `workflow_call`:
ubuntu/windows/macos × Python 3.10/3.12/3.14, real-process tests unmarked, every skip
visible with its reason), then builds sdist + wheel with `python -m build`, installs the wheel into a clean venv with
`--no-deps` from a neutral cwd and runs a smoke flow asserting zero non-stdlib modules loaded, and only
then publishes to PyPI with `pypa/gh-action-pypi-publish` under **trusted publishing** (environment
`release`, `id-token: write`, no API tokens in secrets). Workflow: `.github/workflows/release.yml`. The human half - what to check before tagging, and how to confirm a release really landed without being fooled by PyPI's cached `/json` endpoint or pip's cached index - is in [`docs/RELEASING.md`](https://github.com/Roberto9210/deadman/blob/main/docs/RELEASING.md).

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
