# Changelog

Release process (every version): a release is cut ONLY from a git tag `vX.Y.Z` that must equal
`project.version` in `pyproject.toml` (the release workflow fails loudly on a mismatch, before building).
The tag runs the **same suite as CI** (`.github/workflows/deadman.yml` reused via `workflow_call`:
ubuntu/windows/macos × Python 3.10/3.12/3.14, real-process tests unmarked, the single platform skip
visible), then builds sdist + wheel with `python -m build`, installs the wheel into a clean venv with
`--no-deps` from a neutral cwd and runs a smoke flow asserting zero non-stdlib modules loaded, and only
then publishes to PyPI with `pypa/gh-action-pypi-publish` under **trusted publishing** (environment
`release`, `id-token: write`, no API tokens in secrets). Workflow: `.github/workflows/release.yml`.

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
