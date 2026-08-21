"""A freqtrade strategy guarded by deadman.

The signals are deliberately trivial and deterministic (enter every 20th
candle, exit 10 candles later): this file exists to show the WIRING, not to
suggest an edge. Everything interesting is in the mixin and in the config
section it reads.

Run it:
    python examples/freqtrade/demo.py           # the three scenarios, checked
    freqtrade backtesting --config <cfg> --strategy DeadmanDemoStrategy \
        --strategy-path examples/freqtrade --userdir <dir>
    freqtrade trade --dry-run --config <cfg> --strategy DeadmanDemoStrategy \
        --strategy-path examples/freqtrade --userdir <dir>

The same file works in all three: the callbacks deadman uses are called in
backtesting too (freqtrade/optimize/backtesting.py:351, :813, :915, :1193,
:1671 - bot_start, order_filled, confirm_trade_exit, confirm_trade_entry,
bot_loop_start).
"""
import sys
from pathlib import Path

from freqtrade.strategy import IStrategy
from pandas import DataFrame

# freqtrade loads a strategy file by path, so its directory is not on
# sys.path and a plain sibling import would fail. Explicit beats clever.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from deadman_freqtrade import (  # noqa: E402
    DeadmanGate,
    DeclaredSpreadQuotes,
    QuotesNotConfigured,
    TickerQuotes,
    DeadmanGuardMixin,
)
from deadman import Limits  # noqa: E402

#: Keys that must be PRESENT in config["deadman"]. `null` is a valid value and
#: means "declared, not enforced"; a MISSING key is an error naming the key.
#: This is deadman's rule for state files (DAILY_STATS_KEY_MISSING) applied to
#: configuration: the bug it prevents is a capital key that did not exist
#: being read with a default of 100.
REQUIRED_KEYS = (
    "state_dir",
    "quotes",
    "max_trades_per_day",
    "max_daily_loss_usd",
    "max_notional_usd_per_order",
    "worst_case_fee_bps",
    "max_latency_ms",
    "max_spread_bps",
    "min_notional_usd",
)


class DeadmanDemoStrategy(DeadmanGuardMixin, IStrategy):
    INTERFACE_VERSION = 3
    timeframe = "5m"
    # No ROI/stoploss exits in the demo: the exit signal below is the only way
    # out, so the ledger reads as clean entry/exit pairs. A real strategy keeps
    # its stoploss - and note that a stoploss exit reaches confirm_trade_exit
    # like any other exit, which is why this gate never blocks one.
    minimal_roi = {"0": 10.0}
    stoploss = -0.99
    trailing_stop = False
    process_only_new_candles = True
    use_exit_signal = True
    exit_profit_only = False
    can_short = False
    startup_candle_count = 0

    # ---------------- deadman ----------------
    def deadman_build_gate(self) -> DeadmanGate:
        cfg = self.config.get("deadman")
        if not isinstance(cfg, dict):
            raise ValueError("DEADMAN_CONFIG_MISSING: add a \"deadman\" section to the freqtrade config")
        missing = [k for k in REQUIRED_KEYS if k not in cfg]
        if missing:
            raise ValueError(f"DEADMAN_CONFIG_KEYS_MISSING: {missing} - present with a null value means "
                             f"'declared, not enforced'; absent means nobody decided")

        if cfg["quotes"] == "ticker":
            quotes = TickerQuotes(self.dp, max_ticker_age_s=cfg.get("max_ticker_age_s"))
        elif cfg["quotes"] == "declared_spread":
            for k in ("declared_spread_bps", "declared_latency_ms"):
                if k not in cfg:
                    raise ValueError(f"DEADMAN_CONFIG_KEYS_MISSING: ['{k}'] is required by "
                                     f"quotes=declared_spread")
            quotes = DeclaredSpreadQuotes(spread_bps=cfg["declared_spread_bps"],
                                          latency_ms=cfg["declared_latency_ms"])
        else:
            raise QuotesNotConfigured(f"DEADMAN_QUOTES_UNKNOWN: {cfg['quotes']!r} "
                                      f"(expected 'ticker' or 'declared_spread')")

        return DeadmanGate(
            cfg["state_dir"],
            limits=Limits(
                max_trades_per_day=cfg["max_trades_per_day"],
                max_daily_loss_usd=cfg["max_daily_loss_usd"],
                max_notional_usd_per_order=cfg["max_notional_usd_per_order"],
                worst_case_fee_bps=cfg["worst_case_fee_bps"],
            ),
            allowed_pairs=self.config["exchange"]["pair_whitelist"],
            quotes=quotes,
            max_latency_ms=cfg["max_latency_ms"],
            max_spread_bps=cfg["max_spread_bps"],
            min_notional_usd=cfg["min_notional_usd"],
            max_notional_usd=cfg.get("max_notional_usd"),
            exit_sanity=bool(cfg.get("exit_sanity", False)),
            stake_currency=self.config["stake_currency"],
        )

    # ---------------- signals ----------------
    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["enter_long"] = 0
        dataframe.loc[dataframe.index % 20 == 5, "enter_long"] = 1
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["exit_long"] = 0
        dataframe.loc[dataframe.index % 20 == 15, "exit_long"] = 1
        return dataframe
