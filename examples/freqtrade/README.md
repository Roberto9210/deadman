# deadman + freqtrade

A freqtrade strategy is a good place to decide *what* to trade and a bad place to be sure *nothing
unsafe leaves the building*. This example puts deadman between freqtrade's decision and freqtrade's
order: a kill switch that is one file, a daily limit that is net of fees, and a hash-chained ledger
that explains every entry that was placed and every one that was not.

Everything below was verified against **freqtrade 2026.7** on **Python 3.14.2** by reading the
installed source and running it — every line reference is a file and line in the installed package,
and the demo is a real `freqtrade backtesting` run, not a mock.

```bash
pip install deadman-kit freqtrade
python examples/freqtrade/demo.py          # three runs, 18 checks, exit code 0 if all pass
python -m pytest -q examples/freqtrade/tests
```

## What the demo shows

Three `freqtrade backtesting` runs over the same locally generated candles, each with its own deadman
state directory, plus one offline check on a copy of the resulting ledger:

```
--- 1_clean --------------------------------------------------------------
ledger: {'ORDER_SENT': 86, 'FILL': 86, 'USER_NOTE': 43, 'DAILY_STATS_RESET': 2}
denials: {}
gate passed: 43 entries, 43 exits | fills: 43 in, 43 out
daily_stats (LAST backtest day only; it resets daily): day=2026-01-03 trades=29
             filled_usd=2900.56 gross=0.5693 fees=2.9006 net=-2.3313
verify(): ok=True code=OK chain_complete=True entries_checked=217 segments=1

--- 2_sentinel -----------------------------------------------------------
ledger: {'KILL_ENGAGED': 1, 'INTENT_DENIED': 43}
denials: {'KILL_SWITCH_ACTIVE': 43}
gate passed: 0 entries, 0 exits | fills: 0 in, 0 out

--- 3_daily_limit --------------------------------------------------------
ledger: {'ORDER_SENT': 6, 'FILL': 6, 'USER_NOTE': 3, 'INTENT_DENIED': 40, 'DAILY_STATS_RESET': 2}
denials: {'DAILY_MAX_TRADES': 40}
gate passed: 3 entries, 3 exits | fills: 3 in, 3 out

--- 4_tamper -------------------------------------------------------------
edited seq 2 filled_usd 99.99990739914051 -> 199.99981479828102
verify(): ok=False code=HASH_MISMATCH detail=seq 2
```

Read the clean run's numbers before anything else: **gross +0.5693, fees 2.9006, net −2.3313** on that
day. A bot reporting "profit" from the gross figure would have reported a winner. That is the bug
`DailyLimits` exists for, and here it is on the first run of a demo that was not built to produce it.

The daily-limit run stops after **one** entry per backtest day and the day rolls over on
**2026-01-03**, not on the day you run the demo — that is deadman's injectable clock being driven by
freqtrade's `current_time`, which is what makes a limit reproducible in a backtest at all.

## The wiring

| freqtrade callback | when | what deadman does |
|---|---|---|
| `bot_start` | once, before any candle | build `Paths`/`Ledger`/`KillSwitch`/`EntryHalt`/`DailyLimits`/`OrderSanity`; `EntryHalt.startup_check()`. A failure here is a `StrategyError` and the bot does not start. |
| `bot_loop_start` | every iteration / candle | feed `current_time` to the `FreqtradeClock` |
| `confirm_trade_entry` | right before an entry order | kill switch → entry halt → `resolve_units` → `DailyLimits.check` → `OrderSanity.check`; `False` cancels the entry |
| `confirm_trade_exit` | right before an exit order | kill switch (and `OrderSanity` only if you opt in). Nothing else is consulted. |
| `order_filled` | after any fill | `FILL`/`PARTIAL_FILL` in the ledger, `DailyLimits.record_fill` (fees included, `None` never becomes 0), and on a full close `record_pnl` with the **gross** figure |

Signatures verified in `freqtrade/strategy/interface.py:275, :282, :354, :390, :428`. The same five are
called in backtesting (`optimize/backtesting.py:351, :1671, :1193, :915, :813`), which is why the demo
can prove anything at all with a backtest.

## The asymmetry, in freqtrade terms

Entries fail closed; exits fail open. In this integration that means an exhausted daily limit, an
active entry halt, an unreadable stats file, a missing quote or an internal crash inside deadman
**cannot** stop an exit, because the exit path never consults them. `confirm_trade_exit` is the hook
freqtrade itself warns about — deny there and you deny stop-loss exits too — so this gate denies there
for exactly one reason.

**The kill switch does stop exits.** That is deadman's decision A, not an oversight: the sentinel means
a human is taking over, and in freqtrade it means an open trade stays open until the file is removed.
If that is not what you want from a kill switch, you want a different file.

## What this integration does not give you

freqtrade owns order placement, polling, the unfilled timeout, the cancel and the startup
reconciliation of open orders. Running deadman's `HonestExecutor` beside it would mean two write-ahead
records and two reconcilers for one order, so **`BrokerPort` and `HonestExecutor` are not used here**.
What you do not get, therefore: the write-ahead client order id before the network call, "presumed
alive" on a send timeout resolved by client id, and `startup()` reconciliation. Those are freqtrade's
implementation and freqtrade's guarantees, not deadman's G1–G9.

Verified coverage gaps in the hooks themselves — the gate never sees these orders:

| Not gated | Why | Evidence |
|---|---|---|
| position adjustments (DCA) and order replacements | `confirm_trade_entry` runs only for `mode == "initial"` | `freqtradebot.py:934` |
| liquidations | cannot be rejected, so the callback is skipped | `freqtradebot.py:2140` |
| partial exits | skipped by the same guard (`sub_trade_amt`, `ExitType.PARTIAL_EXIT`) | `freqtradebot.py:2141`, `backtesting.py:912-915` |
| stoploss-on-exchange orders | placed by `create_stoploss_order`, which never calls the strategy | `freqtradebot.py:1420` |

All four still reach `order_filled`, so their fills are ledgered and counted — they are simply not
*gated*. If you run DCA or partial exits, say so out loud in your own README: this one cannot.

Also out of scope here: shorts and futures. The shipped exit predicate is `spot_long_only_is_exit`, so
a short's exit (a buy) would look like a new entry to it, and on futures an `amount` may be contracts
rather than base. `bot_start` refuses `trading_mode != "spot"` and `can_short = True` outright — the
bot does not start — and `confirm_trade_entry` refuses `side="short"` with `SHORT_NOT_SUPPORTED`.
Neither is guessed at.

## The fail-open hole this wrapper closes

freqtrade calls the confirm callbacks through `strategy_safe_wrapper(..., default_retval=True)`
(`strategy/strategy_wrapper.py`, call sites `freqtradebot.py:934`, `:2142`, `backtesting.py:1193`,
`:915`). **Every exception is caught and `True` is returned.** A risk check that raises does not stop
the trade — it places it.

So every callback here catches its own exceptions:

- entry raises → `False` (no new exposure) **and** an `EntryHalt` is set;
- exit raises → `True` (never trap a position) **and** an `EntryHalt` is set;
- `order_filled` raises → freqtrade swallows it (`supress_error=True`, `freqtradebot.py:2384`,
  `backtesting.py:813`), so the halt is set here too: numbers we know are wrong must not be the basis
  for new exposure.

Two tests pin this: `test_entry_is_denied_when_the_gate_raises` and
`test_exit_is_allowed_when_the_gate_raises`.

## Fees and P&L: the double-counting trap

freqtrade's profit figures **already include fees** (`persistence/trade_model.py:1156`). deadman wants
the **gross** figure in `record_pnl` and the fees per fill in `record_fill`, and computes
`net = gross − fees` itself. Feeding freqtrade's net into `record_pnl` would count the fees twice and
make every limit wrong in the safe-looking direction.

So the round trip's gross is computed here from the two prices (`filled × (close − open)`), not read
from the trade — and it cannot be read from the trade anyway: when `order_filled` fires for the closing
order, `trade.is_open` is still `True`, `close_profit_abs` is `None` and `realized_profit` is `0`
(observed in a real backtest, not assumed).

The fee itself comes from the trade's fee **rate** (`trade.fee_open` / `trade.fee_close`).
`Order.ft_fee_base` is a fee paid in *base* currency and is `None` otherwise, and
`Order.safe_fee_base` returns `self.ft_fee_base or 0.0` (`trade_model.py:160`) — using it would be the
"unknown fee counted as zero" bug wearing a helpful name. No rate ⇒ `None` ⇒ deadman charges
`worst_case_fee_bps` or marks the day unverified and stops entries.

`test_round_trip_net_equals_freqtrades_own_number` asserts deadman's net equals freqtrade's own
formula to 1e-9 on numbers taken from a real backtest fill.

## Quotes: why the example refuses to start without them

`OrderSanity` needs `bid`, `ask`, `latency_ms` and `broker_status` **in the call**, and freqtrade hands
you none of them. There is no default, because a default here means inventing a spread:

- `TickerQuotes(self.dp)` — live and dry-run. `dp.ticker()` is a real network call
  (`data/dataprovider.py:565-577`), so the time it takes *is* the latency; it is measured, not assumed.
  An empty or failing ticker yields `None`s, and the entry is denied.
- `DeclaredSpreadQuotes(spread_bps=…, latency_ms=…)` — a **declared simulation** for backtests. Both
  numbers are required arguments, and every ledger entry it feeds carries
  `quote_source: "declared_spread_simulation"` so a run gated by invented quotes can never be read as a
  run gated by a venue.

Anything else: `QuotesNotConfigured` at construction, which in freqtrade means the bot does not start.

## Configuration

The strategy reads a `deadman` section from the freqtrade config. **Every key must be present**;
`null` means "declared, not enforced", a missing key is an error that names the key. That is the
`DAILY_STATS_KEY_MISSING` rule applied to configuration — the bug it prevents is a capital key that did
not exist being read with a default of 100.

```json
"deadman": {
    "state_dir": "/var/lib/mybot/deadman",
    "quotes": "ticker",
    "max_trades_per_day": 20,
    "max_daily_loss_usd": 50.0,
    "max_notional_usd_per_order": 250.0,
    "worst_case_fee_bps": 80.0,
    "max_latency_ms": 2000.0,
    "max_spread_bps": 50.0,
    "min_notional_usd": 10.0,
    "exit_sanity": false
}
```

`"quotes": "declared_spread"` additionally requires `declared_spread_bps` and `declared_latency_ms`.

Two things to know before you copy the numbers:

- **A round trip costs two trades.** `DailyLimits.record_fill` counts entries *and* exits so the day's
  numbers are true; only entries are ever checked against the counter. `max_trades_per_day: 20` is ten
  round trips.
- **deadman says USD, freqtrade says stake currency.** This wrapper maps one onto the other verbatim.
  If you stake USDT, every `*_usd` number here is USDT, and USDT is not USD.

## Files

| File | What it is |
|---|---|
| `deadman_freqtrade.py` | the gate, the fill recorder, the clock and the mixin. No freqtrade import, so it is testable without it |
| `DeadmanDemoStrategy.py` | a minimal `IStrategy` using the mixin; the signals are deliberately trivial |
| `config.demo.json` | dry-run config, no API keys, `kraken`, `BTC/USDT`, 5m |
| `make_demo_data.py` | deterministic candles written through freqtrade's own data handler |
| `demo.py` | the three runs plus the tamper check, each claim asserted |
| `tests/` | 26 tests that need neither freqtrade nor an exchange |

## Running it against a live dry-run

The same strategy file, unchanged, with `"quotes": "ticker"`:

```bash
freqtrade trade --dry-run --config <your-config> --strategy DeadmanDemoStrategy \
    --strategy-path examples/freqtrade --userdir <your-userdir>
```

Dry-run places no orders and needs no API keys, but it does talk to the exchange for market data — and
so does `freqtrade backtesting`, which loads market metadata (precision, limits) before it will start.
That is why `demo.py` needs network access even though it never sends an order. Binance answers `451`
from some locations; the demo config uses `kraken` for that reason.

## What is not proven here

- Nothing in this example demonstrates deadman's **anchoring**. A ledger with no external anchor is
  weaker evidence than one with it — see the main README's threat model and
  `examples/git_anchor_publisher.py`.
- The demo runs a backtest. It proves that these callbacks, in this order, produce these ledger
  entries and these denials. It does not prove anything about an exchange's behaviour under a real
  order, and no backtest can.
- Partial fills: freqtrade reports them and this wrapper ledgers them as `PARTIAL_FILL`, but the demo
  never produced one, so that path is covered by a test and not by a run.
