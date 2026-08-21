# deadman

[![CI](https://github.com/Roberto9210/deadman/actions/workflows/deadman.yml/badge.svg?branch=main)](https://github.com/Roberto9210/deadman/actions/workflows/deadman.yml) [![PyPI](https://img.shields.io/pypi/v/deadman-kit.svg)](https://pypi.org/project/deadman-kit/) [![Python](https://img.shields.io/pypi/pyversions/deadman-kit.svg)](https://pypi.org/project/deadman-kit/) [![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

> Installs as **`deadman-kit`** (`pip install deadman-kit`), imports as **`deadman`** — the PyPI name `deadman` was taken.

**deadman sits between your strategy and your broker, and when it meets the unknown it stops instead of guessing.**

Execution-safety primitives for automated trading systems. Zero runtime dependencies. Broker-agnostic,
strategy-agnostic. Every claim below has a test or a spec section behind it — the links are the argument.

Specification: [`docs/SPEC.md`](docs/SPEC.md) (v0.1, closed 2026-08-18; written before the code).
Conformance statement, exact: **11 of 13 test groups implemented, 165 collected cases (164 pass, 1 platform skip
with its reason in the test), 2 elements declared out of scope with rationale** — see [SPEC §6b](docs/SPEC.md).
Not "13/13".

## What it is not — said first, without shame

deadman does **not** bring a strategy, signals, a market-data feed, a broker connection, position sizing,
paper accounting, or any notion of your account's equity. You pass it a `BrokerPort` adapter (five
methods, [guarantees G1–G9](docs/SPEC.md)) and an `Intent`; it returns allowed/denied with a
code, and — if asked — runs the post-fill sequence honestly. Everything it needs to decide it receives in
the call. Nothing it needs is guessed.

## Threat model, in plain words

- The **external anchor is the guarantee**: the ledger tip `(seq, hash)` is published to a third party the
  operator does not control. Everything before the latest anchor is dated by that third party and provably
  unchanged.
- The **local hash chain is the mechanism**: it detects corruption, partial writes, buggy rewrites,
  deletions, reordering, broken rotation — and it is what lets 64 bytes cover the whole history.
- **Signing is optional** and the key is yours (`signer`/`verifier` callables). With the key on the same disk
  as the ledger, a signature adds nothing over the chain; the library does not pretend otherwise.

The two tests that show the library's own limit, next to each other:
[`test_full_rewrite_with_recompute_passes_the_chain_alone`](tests/test_g11_ledger.py) — an attacker with
disk access rewrites an entry, recomputes the chain to the tip and replaces the tip file: **the chain
verifies** — and
[`test_same_rewrite_is_caught_by_an_external_anchor`](tests/test_g11_ledger.py) — the same rewrite, plus the
attacker wiping the local anchors file, is caught by `verify(anchors=…)` with the anchors held by the third
party (`ANCHOR_MISMATCH`).

**What counts as a third party** ([SPEC §2b](docs/SPEC.md)): a git branch **protected against
force-push and deletion for everyone including the owner**, or an **RFC 3161 timestamp authority**, or a
third-party append-only service with server-side timestamps. A remote you can force-push is not one — the
anchor is then worth nothing over the local chain. Sustained publisher failure is not silent:
`ANCHOR_STALE` in the ledger + a visible `anchor_stale.flag`, recovered by the next success
([test](tests/test_g11_ledger.py) `test_sustained_anchor_failure_raises_stale_flag_and_recovers`).
An example publisher (git push to a protected branch) is in [`examples/`](examples/) — it is your code; the
library never touches the network.

## The primitives, each with the bug that motivated it

These are patterns from a real system, kept as patterns. They are the reason the library exists.

| Primitive | The bug | What deadman does instead | Proof |
|---|---|---|---|
| **KillSwitch** | The stop sentinel depended on a service that had been dead for months. | The mere **existence** of one file stops entries and exits; the file is never opened or parsed (a parse is one more failure mode); any error while checking also stops. | [G1](tests/test_g1_kill_switch.py) — incl. a spy proving `open()` is never called on the sentinel |
| **EntryHalt** | An unknown order state in one cycle was forgotten in the next. | Persistent on disk, blocks **new exposure only**, never a close; unreadable file = halted; cleared by a reconcile that sees an empty book or by a human. | [G2](tests/test_g2_entry_halt.py), [G13](tests/test_g13_concurrent_writer.py) |
| **Exit predicate** (`spot_long_only_is_exit`, `net_position_is_exit`) | Daily limits, "eligibility" and a disabled policy trapped open positions. And **the February stop-loss was handling August exits**: exit thresholds came from a parameter bank frozen months earlier. | The asymmetry is a *policy over an injectable predicate*; only the kill switch and order sanity may stop an exit. The default is declared spot long-only; futures/shorts must pass a net-position predicate. | [G3](tests/test_g3_units.py), [G4](tests/test_g4_daily_limits.py), [G9](tests/test_g9_todo_en_llamas.py) |
| **Intent / resolve_units** | A quantity travelled in a bare `amount` with no unit; "sell the whole position" sold a USD figure at a stale price. | `units ∈ {USD, BASE, CONTRACTS}` is mandatory; nothing is inferred; every failure names the missing datum and carries the intent. | [G3](tests/test_g3_units.py) |
| **DailyLimits** | A capital key that did not exist in the config was read with **default 100 → the per-trade risk cap was a fixed $2** for months. And a paper run reported **+$0.29 gross as "the result"** while the net of fees was negative. | A missing key denies naming the key — never a default. P&L is **net of fees**; an unknown fee never counts as zero (worst case, or the day is marked unverified and entries stop). Rollover only via the injected clock, ledgered; a clock going backwards is fail-closed. Unreadable stats block entries only — exits are evaluated **before** the file is read. | [G4](tests/test_g4_daily_limits.py) `test_g4_7_*`, `test_g4_4_*`, `test_g4_6_*`, `test_g4_9_*` |
| **OrderSanity** | A feed-freshness check read a key **no producer ever wrote**, so it always said NOMINAL. And `equity = max(equity, 1.0)` turned "I don't know how much money there is" into "order too small". | Only inputs the caller passes in the call; any `None`/`NaN` denies as `<ARG>_MISSING`. `quantize()` floors to the venue step, entries and exits alike; an order below the venue minimum is **denied, never enlarged**. | [G5](tests/test_g5_order_sanity.py) `test_g5_5_below_min_notional_is_denied_not_enlarged`, `test_g10_*` |
| **Ledger** | Records could be edited, and part of the history had been summarised with later data. A rotation left a segment that no longer chained to genesis. | Hash chain + atomic writes + OS lock; anchored rotation (`LEDGER_ROTATED` carries the previous file's last hash and sha256); `verify()` crosses segments and never says plain OK when one is missing. Zero deps. | [G11](tests/test_g11_ledger.py) — incl. two real processes appending |
| **HonestExecutor** | The adapter declared success on send, not on fill; a timeout counted as a trade; **an order stayed alive with no owner after a timeout**. | Write-ahead intent with a deterministic client order id **before** the network; timeout ⇒ the order is **presumed alive** and resolved by client id — never re-sent; partial is partial, duplicate fills counted once and noted; anything outside the state machine ⇒ `UNKNOWN_STATE` + halt; `startup()` reconciles before any intent is accepted. | [G6/G7](tests/test_g6_g7_executor.py), [G9](tests/test_g9_todo_en_llamas.py) — incl. a real process killed mid-send |
| **Injectable clock** | A `now()` nobody controlled made a daily rollover and an outcome window irreproducible. | Every primitive receives a `Clock`; no module calls the wall clock (static test). | [G12](tests/test_g12_clock_and_paths.py) |
| **Writer seal** | Two adapters once ran at the same time against the same state. | Every state file carries `(writer_pid, writer_started_at, write_seq)`; a changed seal between read and write is `CONCURRENT_WRITER_DETECTED` — not prevented, made loud. | [G13](tests/test_g13_concurrent_writer.py) |

The principle behind all of it — *zero plausible defaults* — is a contract, not a slogan: [SPEC §2](docs/SPEC.md).

## What this library does not protect against

This section is what makes the rest credible.

- **A deliberate rewrite of the ledger by someone with disk access, when no external anchor covers it.**
  The chain alone verifies after a recompute — proven, not hidden:
  [`test_full_rewrite_with_recompute_passes_the_chain_alone`](tests/test_g11_ledger.py). Only an anchor held
  by a real third party catches it ([`test_same_rewrite_is_caught_by_an_external_anchor`](tests/test_g11_ledger.py)),
  and only for history before that anchor.
- **Anything after the latest anchor.** The window equals your anchoring interval; that is why anchors are
  forced after halts, unknowns and kill events ([`test_anchor_forced_after_safety_events_and_by_count`](tests/test_g11_ledger.py)).
- **A remote you can force-push.** It is not a third party; see above.
- **Two writers racing on a state file.** Not prevented (no OS lock on halt/stats in 0.1) — detected and
  escalated to a halt ([G13](tests/test_g13_concurrent_writer.py)).
- **A broker adapter that lies.** `BrokerPort` guarantees G1–G9 are the adapter's job; if `fetch_order`
  invents "closed" for an unmappable state, or `fetch_order_by_client_id` returns `None` without being
  authoritative, deadman will believe it. The conformance tests ([`tests/fake_broker.py`](tests/fake_broker.py)
  is the reference shape) are how you check an adapter.
- **Your account and your sizing.** deadman has no equity, no positions of its own, no snapshot of your
  account. `size_available` is whatever you pass; a stale balance you pass as fresh is your stale balance
  (SPEC G8 is out of scope for this reason — [SPEC §6b](docs/SPEC.md)).
- **Losing money.** It stops you from acting on what it cannot vouch for. It does not know whether your
  strategy has an edge.

## Quickstart (honest: this is the whole flow)

```python
from deadman import (Paths, SystemClock, WriterIdentity, Ledger, KillSwitch, EntryHalt,
                     DailyLimits, Limits, OrderSanity, HonestExecutor, Intent, spot_long_only_is_exit)

clock = SystemClock()
paths = Paths("/var/lib/mybot/deadman")            # one explicit root for every state file
ident = WriterIdentity(clock)

ledger = Ledger(paths, clock, publisher=my_publisher)   # my_publisher: see examples/git_anchor_publisher.py
kill   = KillSwitch(paths, ledger)                       # `touch /var/lib/mybot/deadman/kill_switch.enabled` stops everything
halt   = EntryHalt(paths, clock, ident, ledger)
halt.startup_check()                                     # another live process owns the halt file? -> loud
limits = DailyLimits(paths, Limits(max_trades_per_day=20, max_daily_loss_usd=50.0, worst_case_fee_bps=80.0),
                     spot_long_only_is_exit, clock, ident, ledger)
sanity = OrderSanity(allowed_symbols=frozenset({"BTC/USD"}), max_latency_ms=500, max_spread_bps=20)

ex = HonestExecutor(my_broker_port, kill, halt, limits, sanity, ledger, spot_long_only_is_exit, clock,
                    fill_timeout_s=10.0, poll_interval_s=1.0)
report = ex.startup(["BTC/USD"], position_of=lambda sym: None)   # reconcile BEFORE any intent; halts if it finds anything

intent = Intent(symbol="BTC/USD", side="buy", units="USD", amount=25.0, kind="ENTRY", client_id="sig-2026-08-18-001")
result = ex.execute(intent, price=64_000.0, broker_status="connected", latency_ms=42.0,
                    bid=63_995.0, ask=64_005.0, size_available=1_000.0)
print(result.status, result.code, result.reason)   # FILLED | PARTIAL | NO_FILL_CANCELED | DENIED | UNKNOWN
print(ledger.verify())                              # the ledger alone explains every final state
```

`my_broker_port` is your adapter implementing `BrokerPort` (five methods). `my_publisher` is your anchor
publisher. Neither is provided: the library does not talk to the network.

## Using with freqtrade

If your bot is a [freqtrade](https://www.freqtrade.io) strategy, you do not write a `BrokerPort`:
freqtrade already owns the order. deadman goes in as a **gate plus a ledger**, through five callbacks
freqtrade already calls — in live, in dry-run and in backtesting alike.

```python
class MyStrategy(DeadmanGuardMixin, IStrategy):     # examples/freqtrade/deadman_freqtrade.py
    def deadman_build_gate(self) -> DeadmanGate:
        return DeadmanGate(
            "/var/lib/mybot/deadman",
            limits=Limits(max_trades_per_day=20, max_daily_loss_usd=50.0, worst_case_fee_bps=80.0),
            allowed_pairs=self.config["exchange"]["pair_whitelist"],
            quotes=TickerQuotes(self.dp),            # live/dry-run: real ticker, measured latency
            max_latency_ms=2000.0, max_spread_bps=50.0, min_notional_usd=10.0,
        )
```

`confirm_trade_entry` runs the full chain — kill switch, entry halt, units, daily limits, order sanity
— and `False` cancels the entry. `confirm_trade_exit` runs the **kill switch only**: an exhausted
limit, an active halt, an unreadable stats file or a crash inside deadman must never hold a position,
and `confirm_trade_exit` is the hook that would otherwise suppress a stop-loss exit. `order_filled`
records the fill with its fee and the round trip's **gross** P&L — freqtrade's own profit figures
already include fees, so handing them to `record_pnl` would count fees twice.

One thing worth knowing before you wire it: freqtrade calls the confirm callbacks through
`strategy_safe_wrapper(..., default_retval=True)`, so a strategy whose risk check *raises* does not
stop the trade — it places it. The mixin therefore catches its own exceptions and answers `False` on
an entry, `True` on an exit.

What this does **not** give you: `BrokerPort` and `HonestExecutor` are not used (freqtrade owns
placement, polling, timeout, cancel and startup reconciliation), and the gate never sees position
adjustments, liquidations, partial exits or stoploss-on-exchange orders — their fills are ledgered,
not gated. Shorts and futures are refused rather than guessed. The complete list, with the freqtrade
line that proves each one, is
[**What this integration does NOT cover**](examples/freqtrade/README.md#what-this-integration-does-not-cover)
— including what was never verified: the backtest was run, `freqtrade trade --dry-run` was not.

**[`examples/freqtrade/`](examples/freqtrade/)** has the whole thing: the wrapper, a demo strategy, 28
tests that need neither freqtrade nor an exchange, and `demo.py` — three real `freqtrade backtesting`
runs proving the sentinel stops entries, the daily limit blocks, the ledger records and `verify()`
passes, plus a fourth check where an edited ledger is rejected with `HASH_MISMATCH`. Every claim there
carries the file and line in freqtrade that backs it (verified against freqtrade 2026.7 on Python
3.14.2). Those 28 tests and the demo are a **local suite, run by hand**: CI below does not run them —
freqtrade drags in numpy, pandas, scipy, pyarrow, ccxt and TA-Lib, which is too heavy for a
3-OS × 3-Python matrix, and the demo needs network access. A freqtrade release can therefore break the
example without turning the badge red.

## Install and test

```bash
pip install deadman-kit        # installs as deadman-kit, imports as deadman; zero runtime dependencies
python -m pytest -q tests   # 165 cases; Windows, Linux, macOS in CI
```

CI: `.github/workflows/deadman.yml` — ubuntu/windows/macos × Python 3.10/3.12/3.14, plus a job that builds
the wheel, installs it into a clean venv with `--no-deps` and runs a smoke flow. Windows is not optional there:
the `msvcrt.LK_NBLCK` finding (`LK_LOCK` gives up with an `OSError` that is not a `PermissionError`) is a
claim only a Windows run keeps honest.

## License

MIT. See [LICENSE](LICENSE). Changes: [CHANGELOG.md](CHANGELOG.md).
