# Changelog

## 0.1.0 — 2026-08-18

First release. Implements `docs/safety_kit/SPEC.md` v0.1 (closed 2026-08-18).

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
