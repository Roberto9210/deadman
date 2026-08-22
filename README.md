# deadman

[![CI](https://github.com/Roberto9210/deadman/actions/workflows/deadman.yml/badge.svg?branch=main)](https://github.com/Roberto9210/deadman/actions/workflows/deadman.yml) [![PyPI](https://img.shields.io/pypi/v/deadman-kit.svg)](https://pypi.org/project/deadman-kit/) [![Python](https://img.shields.io/pypi/pyversions/deadman-kit.svg)](https://pypi.org/project/deadman-kit/) [![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](https://github.com/Roberto9210/deadman/blob/main/LICENSE)

> Installs as **`deadman-kit`** (`pip install deadman-kit`), imports as **`deadman`** — the PyPI name `deadman` was taken.

**deadman sits between your strategy and your broker, and when it meets the unknown it stops instead of guessing.**

Execution-safety primitives for automated trading systems. Zero runtime dependencies. Broker-agnostic,
strategy-agnostic. Every claim below has a test or a spec section behind it — the links are the argument.

Specification: [`docs/SPEC.md`](https://github.com/Roberto9210/deadman/blob/main/docs/SPEC.md) (v0.1, closed 2026-08-18; written before the code).
Conformance statement, exact: **11 of 13 test groups implemented, 254 collected cases (252 pass and 2 skips in CI,
each with its reason printed), 2 elements declared out of scope with rationale** — see [SPEC §6b](https://github.com/Roberto9210/deadman/blob/main/docs/SPEC.md).
The two skips: one design skip in `test_g5_order_sanity.py`, and one case that runs only on a machine with a live
guardian ledger, because that file is a trader's session data and is deliberately not vendored here.
Not "13/13". The certificate verifier adds 85 of those cases: 18 named guarantees, 13 adversarial probes, and the
shipped example checked on every run so the documentation cannot drift from the tool:
[`docs/verify-certificate.md`](https://github.com/Roberto9210/deadman/blob/main/docs/verify-certificate.md).

## What it is not — said first, without shame

deadman does **not** bring a strategy, signals, a market-data feed, a broker connection, position sizing,
paper accounting, or any notion of your account's equity. You pass it a `BrokerPort` adapter (five
methods, [guarantees G1–G9](https://github.com/Roberto9210/deadman/blob/main/docs/SPEC.md)) and an `Intent`; it returns allowed/denied with a
code, and — if asked — runs the post-fill sequence honestly. Everything it needs to decide it receives in
the call. Nothing it needs is guessed.

## Threat model, in plain words

- The **external anchor is the only guarantee that survives disk access - and it is off until you switch it
  on.** Give the ledger a `publisher` and it publishes the tip `(seq, hash)` to a third party the operator
  does not control; everything before the latest anchor is then dated by that third party and provably
  unchanged. **Without a publisher there is no anchor, and everything stays at L1.** The library ships no
  publisher and contacts no one, so a default `Ledger` anchors nothing.
- The **local hash chain is the mechanism**: it detects corruption, partial writes, buggy rewrites,
  deletions, reordering, broken rotation — and it is what lets 64 bytes cover the whole history.
- **Signing is optional** and the key is yours (`signer`/`verifier` callables). With the key on the same disk
  as the ledger, a signature adds nothing over the chain; the library does not pretend otherwise.

The two tests that show the library's own limit, next to each other:
[`test_full_rewrite_with_recompute_passes_the_chain_alone`](https://github.com/Roberto9210/deadman/blob/main/tests/test_g11_ledger.py) — an attacker with
disk access rewrites an entry, recomputes the chain to the tip and replaces the tip file: **the chain
verifies** — and
[`test_same_rewrite_is_caught_by_an_external_anchor`](https://github.com/Roberto9210/deadman/blob/main/tests/test_g11_ledger.py) — the same rewrite, plus the
attacker wiping the local anchors file, is caught by `verify(anchors=…)` with the anchors held by the third
party (`ANCHOR_MISMATCH`).

**What counts as a third party** ([SPEC §2b](https://github.com/Roberto9210/deadman/blob/main/docs/SPEC.md)): a git branch **protected against
force-push and deletion for everyone including the owner**, or an **RFC 3161 timestamp authority**, or a
third-party append-only service with server-side timestamps. A remote you can force-push is not one — the
anchor is then worth nothing over the local chain. Sustained publisher failure is not silent:
`ANCHOR_STALE` in the ledger + a visible `anchor_stale.flag`, recovered by the next success
([test](https://github.com/Roberto9210/deadman/blob/main/tests/test_g11_ledger.py) `test_sustained_anchor_failure_raises_stale_flag_and_recovers`).
An example publisher (git push to a protected branch) is in [`examples/`](https://github.com/Roberto9210/deadman/tree/main/examples/) — it is your code; the
library never touches the network.

## The primitives, each with the bug that motivated it

These are patterns from a real system, kept as patterns. They are the reason the library exists.

| Primitive | The bug | What deadman does instead | Proof |
|---|---|---|---|
| **KillSwitch** | The stop sentinel depended on a service that had been dead for months. | The mere **existence** of one file stops entries and exits; the file is never opened or parsed (a parse is one more failure mode); any error while checking also stops. | [G1](https://github.com/Roberto9210/deadman/blob/main/tests/test_g1_kill_switch.py) — incl. a spy proving `open()` is never called on the sentinel |
| **EntryHalt** | An unknown order state in one cycle was forgotten in the next. | Persistent on disk, blocks **new exposure only**, never a close; unreadable file = halted; cleared by a reconcile that sees an empty book or by a human. | [G2](https://github.com/Roberto9210/deadman/blob/main/tests/test_g2_entry_halt.py), [G13](https://github.com/Roberto9210/deadman/blob/main/tests/test_g13_concurrent_writer.py) |
| **Exit predicate** (`spot_long_only_is_exit`, `net_position_is_exit`) | Daily limits, "eligibility" and a disabled policy trapped open positions. And **the February stop-loss was handling August exits**: exit thresholds came from a parameter bank frozen months earlier. | The asymmetry is a *policy over an injectable predicate*; only the kill switch and order sanity may stop an exit. The default is declared spot long-only; futures/shorts must pass a net-position predicate. | [G3](https://github.com/Roberto9210/deadman/blob/main/tests/test_g3_units.py), [G4](https://github.com/Roberto9210/deadman/blob/main/tests/test_g4_daily_limits.py), [G9](https://github.com/Roberto9210/deadman/blob/main/tests/test_g9_todo_en_llamas.py) |
| **Intent / resolve_units** | A quantity travelled in a bare `amount` with no unit; "sell the whole position" sold a USD figure at a stale price. | `units ∈ {USD, BASE, CONTRACTS}` is mandatory; nothing is inferred; every failure names the missing datum and carries the intent. | [G3](https://github.com/Roberto9210/deadman/blob/main/tests/test_g3_units.py) |
| **DailyLimits** | A capital key that did not exist in the config was read with **default 100 → the per-trade risk cap was a fixed $2** for months. And a paper run reported **+$0.29 gross as "the result"** while the net of fees was negative. | A missing key denies naming the key — never a default. P&L is **net of fees**; an unknown fee never counts as zero (worst case, or the day is marked unverified and entries stop). Rollover only via the injected clock, ledgered; a clock going backwards is fail-closed. Unreadable stats block entries only — exits are evaluated **before** the file is read. | [G4](https://github.com/Roberto9210/deadman/blob/main/tests/test_g4_daily_limits.py) `test_g4_7_*`, `test_g4_4_*`, `test_g4_6_*`, `test_g4_9_*` |
| **OrderSanity** | A feed-freshness check read a key **no producer ever wrote**, so it always said NOMINAL. And `equity = max(equity, 1.0)` turned "I don't know how much money there is" into "order too small". | Only inputs the caller passes in the call; any `None`/`NaN` denies as `<ARG>_MISSING`. `quantize()` floors to the venue step, entries and exits alike; an order below the venue minimum is **denied, never enlarged**. | [G5](https://github.com/Roberto9210/deadman/blob/main/tests/test_g5_order_sanity.py) `test_g5_5_below_min_notional_is_denied_not_enlarged`, `test_g10_*` |
| **Ledger** | Records could be edited, and part of the history had been summarised with later data. A rotation left a segment that no longer chained to genesis. | Hash chain + atomic writes + OS lock; anchored rotation (`LEDGER_ROTATED` carries the previous file's last hash and sha256); `verify()` crosses segments and never says plain OK when one is missing. Zero deps. | [G11](https://github.com/Roberto9210/deadman/blob/main/tests/test_g11_ledger.py) — incl. two real processes appending |
| **HonestExecutor** | The adapter declared success on send, not on fill; a timeout counted as a trade; **an order stayed alive with no owner after a timeout**. | Write-ahead intent with a deterministic client order id **before** the network; timeout ⇒ the order is **presumed alive** and resolved by client id — never re-sent; partial is partial, duplicate fills counted once and noted; anything outside the state machine ⇒ `UNKNOWN_STATE` + halt; `startup()` reconciles before any intent is accepted. | [G6/G7](https://github.com/Roberto9210/deadman/blob/main/tests/test_g6_g7_executor.py), [G9](https://github.com/Roberto9210/deadman/blob/main/tests/test_g9_todo_en_llamas.py) — incl. a real process killed mid-send |
| **Injectable clock** | A `now()` nobody controlled made a daily rollover and an outcome window irreproducible. | Every primitive receives a `Clock`; no module calls the wall clock (static test). | [G12](https://github.com/Roberto9210/deadman/blob/main/tests/test_g12_clock_and_paths.py) |
| **Writer seal** | Two adapters once ran at the same time against the same state. | Every state file carries `(writer_pid, writer_started_at, write_seq)`; a changed seal between read and write is `CONCURRENT_WRITER_DETECTED` — not prevented, made loud. | [G13](https://github.com/Roberto9210/deadman/blob/main/tests/test_g13_concurrent_writer.py) |

The principle behind all of it — *zero plausible defaults* — is a contract, not a slogan: [SPEC §2](https://github.com/Roberto9210/deadman/blob/main/docs/SPEC.md).

## What this library does not protect against

This section is what makes the rest credible.

- **A deliberate rewrite of the ledger by someone with disk access, when no external anchor covers it.**
  The chain alone verifies after a recompute — proven, not hidden:
  [`test_full_rewrite_with_recompute_passes_the_chain_alone`](https://github.com/Roberto9210/deadman/blob/main/tests/test_g11_ledger.py). Only an anchor held
  by a real third party catches it ([`test_same_rewrite_is_caught_by_an_external_anchor`](https://github.com/Roberto9210/deadman/blob/main/tests/test_g11_ledger.py)),
  and only for history before that anchor.
- **Anything after the latest anchor.** The window equals your anchoring interval; that is why anchors are
  forced after halts, unknowns and kill events ([`test_anchor_forced_after_safety_events_and_by_count`](https://github.com/Roberto9210/deadman/blob/main/tests/test_g11_ledger.py)).
- **A remote you can force-push.** It is not a third party; see above.
- **Two writers racing on a state file.** Not prevented (no OS lock on halt/stats in 0.1) — detected and
  escalated to a halt ([G13](https://github.com/Roberto9210/deadman/blob/main/tests/test_g13_concurrent_writer.py)).
- **A broker adapter that lies.** `BrokerPort` guarantees G1–G9 are the adapter's job; if `fetch_order`
  invents "closed" for an unmappable state, or `fetch_order_by_client_id` returns `None` without being
  authoritative, deadman will believe it. The conformance tests ([`tests/fake_broker.py`](https://github.com/Roberto9210/deadman/blob/main/tests/fake_broker.py)
  is the reference shape) are how you check an adapter.
- **Your account and your sizing.** deadman has no equity, no positions of its own, no snapshot of your
  account. `size_available` is whatever you pass; a stale balance you pass as fresh is your stale balance
  (SPEC G8 is out of scope for this reason — [SPEC §6b](https://github.com/Roberto9210/deadman/blob/main/docs/SPEC.md)).
- **Losing money.** It stops you from acting on what it cannot vouch for. It does not know whether your
  strategy has an edge.

## Quickstart (honest: this is the whole flow)

```python
from deadman import (Paths, SystemClock, WriterIdentity, Ledger, KillSwitch, EntryHalt,
                     DailyLimits, Limits, OrderSanity, HonestExecutor, Intent, spot_long_only_is_exit)

clock = SystemClock()
paths = Paths("/var/lib/mybot/deadman")            # one explicit root for every state file
ident = WriterIdentity(clock)

# Two ways to build the ledger, and they are NOT equivalent:
# ledger = Ledger(paths, clock)                        # no publisher -> NO ANCHOR, L1 only: a rewrite by
#                                                      # anyone with disk access passes verification
ledger = Ledger(paths, clock, publisher=my_publisher)  # anchored -> L2 up to the last anchor
                                                       # my_publisher is YOUR code: examples/git_anchor_publisher.py
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

**Without a publisher there is no anchor, and everything stays at L1** - the layer that a rewrite by anyone
with disk access passes. Anchoring is opt-in, it is your code that reaches the third party, and nothing in
this library turns it on for you.

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
[**What this integration does NOT cover**](https://github.com/Roberto9210/deadman/blob/main/examples/freqtrade/README.md#what-this-integration-does-not-cover)
— including what was never verified: the backtest was run, `freqtrade trade --dry-run` was not.

**[`examples/freqtrade/`](https://github.com/Roberto9210/deadman/tree/main/examples/freqtrade/)** has the whole thing: the wrapper, a demo strategy, 28
tests that need neither freqtrade nor an exchange, and `demo.py` — three real `freqtrade backtesting`
runs proving the sentinel stops entries, the daily limit blocks, the ledger records and `verify()`
passes, plus a fourth check where an edited ledger is rejected with `HASH_MISMATCH`. Every claim there
carries the file and line in freqtrade that backs it (verified against freqtrade 2026.7 on Python
3.14.2). Those 28 tests and the demo are a **local suite, run by hand**: CI below does not run them —
freqtrade drags in numpy, pandas, scipy, pyarrow, ccxt and TA-Lib, which is too heavy for a
3-OS × 3-Python matrix, and the demo needs network access. A freqtrade release can therefore break the
example without turning the badge red.

## Verifying a session certificate

A **session certificate** is a document produced by a deadman-family tool claiming that a trader
operated under a self-imposed daily loss limit and respected it. This package carries the *verifier* —
the part a third party runs to **disprove** such a claim, which is the only reason the claim is worth
anything:

```bash
pip install deadman-kit                        # 0.2.1 or newer
python -m deadman.verify_certificate --example
```

That second command verifies a certificate **that ships inside the package** — no files to find, no
download, no network. It is there so the first thing you run works ten seconds after installing.

On a certificate somebody actually handed you:

```bash
python -m deadman.verify_certificate certificate.json ledger.jsonl
```

You need **both** files. A certificate is a summary; the ledger is the hash-chained record of what
happened, and the verifier recomputes the summary from it rather than believing it. If you were given
only the certificate, ask for the ledger — without it nobody can check the document, including us.

It ignores what the certificate asserts and **recomputes every claim from the ledger events**, then
prints the trust layer it actually reached and an explicit list of what it could not establish — that
list is printed on success too. Exit `0` verified, `1` contradicted, `2` could not evaluate; the last two
are kept apart so a broken file cannot be mistaken for a pass.

### What `REACHED L1` means

The result line names a trust layer. Spelled out here rather than behind a link, because it is the
headline of every run:

| layer | what it proves | what it does not |
|---|---|---|
| **L1** | the ledger's own hash chain recomputes, and the certificate's claims match the events | **nothing against an attacker with disk access** — a full rewrite with recomputed hashes passes L1, and the tool says so on every run |
| **L2** | L1, plus a third party held `(seq, hash)` at a point in time: the record is dated by someone who is not the trader | nothing after the last anchor |
| **L3** | L2, plus the issuer's signature: the document came from the holder of that key and was not edited afterwards | **not that it is true** — a valid signature over a false claim is still valid; truth comes from the recomputation |

**L1 alone is weak, and the tool never pretends otherwise.** If a certificate matters to you, ask for
anchors and pass them with `--anchors`.

Four worked examples ship inside the package and are also readable at
[`deadman/examples/certificate/`](https://github.com/Roberto9210/deadman/tree/main/deadman/examples/certificate): one ledger and four
certificates over it — honest, falsified, truncated, and one whose issuer fields are omitted because the
emitter could not determine them. The falsified one has a correct `certHash` and an intact chain, and falls
only because the verifier counts the events itself. The truncated one contains no false statement at all:
it declares a shorter range so the inconvenient part of the day falls outside it, and **it verified clean
until a check on the range itself was added**. That case, why recomputing claims
can never catch it, and how the fix was calibrated so honest mid-session exports are not called liars, is
written up in full — it is the most useful page in this repository.

Full guide, including the three trust layers and what none of them prove:
[**`docs/verify-certificate.md`**](https://github.com/Roberto9210/deadman/blob/main/docs/verify-certificate.md).

## How this is checked from the outside

Every claim above is testable in this repository, which is the easy half. The harder half is
whether any of it survives contact with someone who does not have the repository — so the verifier
is periodically run as a **cold start**: a stranger's path, in a fresh virtualenv outside the
checkout, installing only from PyPI and reading only published pages, fixing nothing along the way.

The runs are published in full at
[**`docs/COLD_START_LOG.md`**](https://github.com/Roberto9210/deadman/blob/main/docs/COLD_START_LOG.md), including the one where the
published page still told readers to clone the repository because the release they had just
installed supposedly did not exist yet — the point at which a reasonable reader gives up, found
because nobody was allowed to fix anything mid-run. That run is why `--example`
exists, why the examples ship inside the package, and why a release now cannot publish a stale
description.

Reading the repository would not have found it: the repository was right the whole time. The
artefact was what was wrong. How a release is cut, and how it is verified afterwards by being the
stranger rather than by reading the source, is in
[`docs/RELEASING.md`](https://github.com/Roberto9210/deadman/blob/main/docs/RELEASING.md).

## Install and test

```bash
pip install deadman-kit        # installs as deadman-kit, imports as deadman; zero runtime dependencies
python -m pytest -q tests   # 254 cases; Windows, Linux, macOS in CI
```

CI: `.github/workflows/deadman.yml` — ubuntu/windows/macos × Python 3.10/3.12/3.14, plus a job that builds
the wheel, installs it into a clean venv with `--no-deps` and runs a smoke flow. Windows is not optional there:
the `msvcrt.LK_NBLCK` finding (`LK_LOCK` gives up with an `OSError` that is not a `PermissionError`) is a
claim only a Windows run keeps honest.

## License

MIT. See [LICENSE](https://github.com/Roberto9210/deadman/blob/main/LICENSE). Changes: [CHANGELOG.md](https://github.com/Roberto9210/deadman/blob/main/CHANGELOG.md).
