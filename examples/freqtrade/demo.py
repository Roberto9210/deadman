"""The demo: three freqtrade runs, one claim each, checked - not narrated.

    python examples/freqtrade/demo.py

Each scenario is a real `freqtrade backtesting` run of DeadmanDemoStrategy
over the same deterministic candles, with its own deadman state directory.
Nothing is mocked: the callbacks that decide are the ones freqtrade calls in
live and dry-run too (backtesting.py:351, :813, :915, :1193, :1671).

  1. clean        entries pass the gate, fills are recorded, verify() passes
  2. sentinel     kill_switch.enabled exists -> every entry denied, no trade
  3. daily_limit  max_trades_per_day=1 -> entries denied after the first fill,
                  and the day rolls over on BACKTEST days (injected clock)
  4. tamper       (offline) one byte changed in a COPY of the clean ledger ->
                  verify() reports HASH_MISMATCH

What it needs: freqtrade installed in the interpreter running this file, and
network access ONLY to load the exchange's market metadata (precision, limits)
- freqtrade insists on it even for a backtest. No API keys, no orders, no
money. The candles are generated locally and are identical every run.

Exit code is 0 only if every check passed.
"""
import json
import os
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
OUT = HERE / "demo_out"
USERDIR = OUT / "user_data"
DATADIR = USERDIR / "data"
TIMERANGE = "20260101-20260104"
STRATEGY = "DeadmanDemoStrategy"

sys.path.insert(0, str(REPO))   # the deadman checkout this example ships with
sys.path.insert(0, str(HERE))   # make_demo_data

from deadman import KillSwitch, Ledger, Paths, SystemClock  # noqa: E402
import make_demo_data  # noqa: E402


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _entries(state: Path) -> list:
    f = state / "ledger" / "ledger.jsonl"
    if not f.exists():
        return []
    return [json.loads(line) for line in f.read_text(encoding="utf-8").splitlines() if line.strip()]


def _summary(state: Path) -> dict:
    rows = _entries(state)
    kinds = Counter(r["kind"] for r in rows)
    denies = Counter(r["payload"].get("code") for r in rows if r["kind"] == "INTENT_DENIED")
    gate_entries = [r for r in rows if r["kind"] == "ORDER_SENT"
                    and r["payload"].get("stage") == "gate_passed" and not r["payload"].get("is_exit")]
    gate_exits = [r for r in rows if r["kind"] == "ORDER_SENT"
                  and r["payload"].get("stage") == "gate_passed" and r["payload"].get("is_exit")]
    fills_in = [r for r in rows if r["kind"] in ("FILL", "PARTIAL_FILL") and not r["payload"].get("is_exit")]
    fills_out = [r for r in rows if r["kind"] in ("FILL", "PARTIAL_FILL") and r["payload"].get("is_exit")]
    report = Ledger(Paths(state), SystemClock()).verify()
    stats_file = state / "daily_stats.json"
    stats = json.loads(stats_file.read_text(encoding="utf-8")) if stats_file.exists() else {}
    return {"rows": rows, "kinds": kinds, "denies": denies, "gate_entries": len(gate_entries),
            "gate_exits": len(gate_exits), "fills_in": len(fills_in), "fills_out": len(fills_out),
            "verify": report, "stats": stats}


def _run_backtest(cfg_path: Path, log_path: Path) -> subprocess.CompletedProcess:
    cmd = [sys.executable, "-m", "freqtrade", "backtesting",
           "--config", str(cfg_path), "--strategy", STRATEGY, "--strategy-path", str(HERE),
           "--userdir", str(USERDIR),
           # no --datadir on purpose: an explicit one is used verbatim, while
           # the default appends the exchange name (configuration/
           # directory_operations.py:20-30), which is where the candles are.
           "--timerange", TIMERANGE, "--export", "none", "--logfile", str(log_path)]
    # So the demo runs straight from a checkout. With `pip install deadman-kit`
    # (the normal case) this line changes nothing.
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(REPO)] + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else []))
    return subprocess.run(cmd, capture_output=True, text=True, cwd=str(HERE), env=env)


def _scenario(name: str, overrides: dict, *, engage_kill: bool = False) -> dict:
    root = OUT / name
    state = root / "state"
    if root.exists():
        shutil.rmtree(root)
    state.mkdir(parents=True)

    cfg = json.loads((HERE / "config.demo.json").read_text(encoding="utf-8"))
    cfg["deadman"].update(overrides)
    cfg["deadman"]["state_dir"] = str(state)
    cfg_path = root / "config.json"
    cfg_path.write_text(json.dumps(cfg, indent=4), encoding="utf-8")

    if engage_kill:
        # through the API, so the ledger carries the human decision too
        paths = Paths(state)
        KillSwitch(paths, Ledger(paths, SystemClock())).engage("demo: operator stops the bot", actor="demo.py")

    print("\n" + f"--- {name} ".ljust(74, "-"))
    proc = _run_backtest(cfg_path, root / "freqtrade.log")
    if proc.returncode != 0:
        print(proc.stdout[-2500:])
        print(proc.stderr[-2500:])
        raise SystemExit(f"freqtrade backtesting failed for scenario {name} (exit {proc.returncode}); "
                         f"see {root / 'freqtrade.log'}")
    s = _summary(state)
    print(f"ledger: {dict(s['kinds'])}")
    print(f"denials: {dict(s['denies']) or '{}'}")
    print(f"gate passed: {s['gate_entries']} entries, {s['gate_exits']} exits | "
          f"fills: {s['fills_in']} in, {s['fills_out']} out")
    if s["stats"]:
        print(f"daily_stats (LAST backtest day only; it resets daily): "
              f"day={s['stats'].get('day_utc')} trades={s['stats'].get('trades')} "
              f"filled_usd={s['stats'].get('filled_usd'):.2f} gross={s['stats'].get('gross_pnl_usd'):.4f} "
              f"fees={s['stats'].get('fees_usd'):.4f} "
              f"net={s['stats'].get('gross_pnl_usd', 0) - s['stats'].get('fees_usd', 0):.4f}")
    r = s["verify"]
    print(f"verify(): ok={r.ok} code={r.code} chain_complete={r.chain_complete} "
          f"entries_checked={r.entries_checked} segments={r.segments_checked}")
    s["state"] = state
    return s


def _check(results: list, label: str, ok: bool, detail: str = "") -> None:
    results.append((label, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f" - {detail}" if detail else ""))


# --------------------------------------------------------------------------
def main() -> int:
    try:
        import freqtrade  # noqa: F401
    except ImportError:
        print("freqtrade is not installed in this interpreter.\n"
              f"  {sys.executable} -m pip install freqtrade", file=sys.stderr)
        return 2

    OUT.mkdir(parents=True, exist_ok=True)
    (USERDIR / "strategies").mkdir(parents=True, exist_ok=True)
    path = make_demo_data.write(DATADIR)
    print(f"candles: {path} (deterministic, generated locally)")

    checks: list = []

    # 1 ------------------------------------------------------------------
    # max_trades_per_day=100 and not the config's 20, because a ROUND TRIP
    # costs two: DailyLimits.record_fill counts entries AND exits so the day's
    # numbers are true, and only entries are ever checked against the counter
    # (deadman/daily_limits.py, module docstring). With 20 the clean run stops
    # after 10 round trips a day - correct behaviour, wrong scenario.
    clean = _scenario("1_clean", {"max_trades_per_day": 100})
    print("claim: entries pass the gate, fills are recorded, the ledger verifies")
    _check(checks, "entries passed the gate", clean["gate_entries"] > 0, f"{clean['gate_entries']}")
    _check(checks, "entry fills recorded", clean["fills_in"] > 0, f"{clean['fills_in']}")
    _check(checks, "exit fills recorded", clean["fills_out"] > 0, f"{clean['fills_out']}")
    _check(checks, "no kill/limit denial", not (clean["denies"].get("KILL_SWITCH_ACTIVE")
                                                or clean["denies"].get("DAILY_MAX_TRADES")))
    _check(checks, "verify() ok and chain complete",
           clean["verify"].ok and clean["verify"].chain_complete, clean["verify"].code)

    # 2 ------------------------------------------------------------------
    kill = _scenario("2_sentinel", {}, engage_kill=True)
    print("claim: the sentinel file stops entries; nothing is placed")
    _check(checks, "every entry denied by the sentinel",
           kill["denies"].get("KILL_SWITCH_ACTIVE", 0) > 0, f"{kill['denies'].get('KILL_SWITCH_ACTIVE', 0)}")
    _check(checks, "no entry passed the gate", kill["gate_entries"] == 0)
    _check(checks, "no fill at all", kill["fills_in"] == 0 and kill["fills_out"] == 0)
    _check(checks, "KILL_ENGAGED is in the ledger", kill["kinds"].get("KILL_ENGAGED", 0) == 1)
    _check(checks, "verify() ok", kill["verify"].ok, kill["verify"].code)

    # 3 ------------------------------------------------------------------
    limit = _scenario("3_daily_limit", {"max_trades_per_day": 1})
    print("claim: the daily limit blocks further entries, and rolls over on BACKTEST days")
    _check(checks, "entries denied by the daily limit",
           limit["denies"].get("DAILY_MAX_TRADES", 0) > 0, f"{limit['denies'].get('DAILY_MAX_TRADES', 0)}")
    _check(checks, "some entries still passed", limit["gate_entries"] > 0, f"{limit['gate_entries']}")
    _check(checks, "fewer entries than the clean run",
           limit["gate_entries"] < clean["gate_entries"],
           f"{limit['gate_entries']} < {clean['gate_entries']}")
    _check(checks, "day rolled over on backtest time (DAILY_STATS_RESET)",
           limit["kinds"].get("DAILY_STATS_RESET", 0) >= 1, f"{limit['kinds'].get('DAILY_STATS_RESET', 0)}")
    _check(checks, "the day in daily_stats is a backtest day, not today",
           str(limit["stats"].get("day_utc", "")).startswith("2026-01"), str(limit["stats"].get("day_utc")))
    _check(checks, "verify() ok", limit["verify"].ok, limit["verify"].code)

    # 4 ------------------------------------------------------------------
    print("\n" + "--- 4_tamper ".ljust(74, "-"))
    print("claim: an edited ledger does not verify (on a COPY; the original is untouched)")
    tampered = OUT / "4_tamper" / "state"
    if tampered.parent.exists():
        shutil.rmtree(tampered.parent)
    shutil.copytree(clean["state"], tampered)
    f = tampered / "ledger" / "ledger.jsonl"
    lines = f.read_text(encoding="utf-8").splitlines()
    idx = next(i for i, line in enumerate(lines) if json.loads(line)["kind"] in ("FILL", "PARTIAL_FILL"))
    row = json.loads(lines[idx])
    before = row["payload"].get("filled_usd")
    row["payload"]["filled_usd"] = float(before) * 2 if before else 1.0
    lines[idx] = json.dumps(row, sort_keys=True, ensure_ascii=False)
    f.write_text("\n".join(lines) + "\n", encoding="utf-8")
    rep = Ledger(Paths(tampered), SystemClock()).verify()
    print(f"edited seq {row['seq']} filled_usd {before} -> {row['payload']['filled_usd']}")
    print(f"verify(): ok={rep.ok} code={rep.code} detail={rep.detail}")
    _check(checks, "the tampered ledger is rejected", (not rep.ok) and rep.code == "HASH_MISMATCH", rep.code)
    _check(checks, "the original still verifies", Ledger(Paths(clean["state"]), SystemClock()).verify().ok)

    # --------------------------------------------------------------------
    failed = [c for c in checks if not c[1]]
    print("\n" + "=" * 74)
    print(f"{len(checks) - len(failed)}/{len(checks)} checks passed")
    if failed:
        for label, _, detail in failed:
            print(f"  FAILED: {label} {detail}")
    print(f"state, configs and freqtrade logs: {OUT}")
    print("=" * 74)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
