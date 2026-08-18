# deadman

Execution-safety primitives for automated trading systems. Broker-agnostic,
strategy-agnostic. The machine stops when nobody can vouch that everything is
fine — and an exit is never trapped.

Zero external dependencies (stdlib only) — see the threat model in SPEC §2b:
the hash chain detects corruption; the guarantee against deliberate rewrite is an
external ANCHOR (seq, hash) published to a third party the operator does not
control (a remote you can force-push is not one). Sustained anchor failure raises
`ANCHOR_STALE` + a visible `anchor_stale.flag`; it never halts execution. Signing is optional and the key is yours.

Specification (the contract this code is written against):
`../../docs/safety_kit/SPEC.md` (v0.1, closed 2026-08-18).

## Status

| Piece | Spec | State |
|---|---|---|
| `Paths(root)` | §5.1 | done |
| `Clock` / `SystemClock` / `FakeClock` | §5.6 | done |
| `StateFile` + writer seal (`ConcurrentWriterDetected`) | §5.2, §5.7 (D) | done |
| `Ledger` (hash chain, OS lock, anchored rotation, external anchoring via `publisher`, optional `signer/verifier` hooks, `verify`) | §2b, §4.5, §5.5 (C) | done |
| `EntryHalt` | §4.2, decisions B/D | done |
| `KillSwitch` (existence only, never parsed) | §4.1, decision A | done |
| `Intent` / `resolve_units` / exit predicates (`spot_long_only_is_exit` default, `net_position_is_exit`) | §4.3, §4.4 | done |
| `DailyLimits`, `OrderSanity` | §4.4 | pending |
| `BrokerPort`, `HonestExecutor` (post-fill state machine, `reconcile`) | §4.6, §5.3, §5.4 | pending (last) |

Conformance test groups implemented: G1 (kill switch), G2 (entry halt), G3 (units + exit
predicates), G11 (ledger, anchoring, ANCHOR_STALE, rotation, two real processes), G12 (clock/paths),
G13 (concurrent writer). Run:

```bash
python -m pytest -q packages/deadman/tests
```

## Principle

Zero plausible defaults. Missing data for anything that adds exposure ⇒
denied with a code that names the missing datum. Doubt about anything that
reduces exposure ⇒ let it out, with a declared conservative value and a note.
Nothing here guesses.
