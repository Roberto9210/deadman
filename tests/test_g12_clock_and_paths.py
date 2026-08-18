"""G12 - injectable clock (static check: no module calls datetime.now/time.time
outside clock.py) and Paths(root) resolution."""
import os
import re

import pytest

from deadman import FakeClock, Paths
from deadman.errors import PathsNotWritable

PKG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "deadman")


def test_no_module_calls_wall_clock_directly():
    bad = []
    for fn in os.listdir(PKG):
        if not fn.endswith(".py") or fn == "clock.py":
            continue
        src = open(os.path.join(PKG, fn), encoding="utf-8").read()
        for pat in (r"datetime\.now\(", r"datetime\.utcnow\(", r"time\.time\(", r"date\.today\("):
            if re.search(pat, src):
                bad.append((fn, pat))
    assert bad == []


def test_fake_clock_advances_only_when_told():
    c = FakeClock()
    t0 = c.now_utc()
    assert c.now_utc() == t0
    c.advance(seconds=90)
    assert (c.now_utc() - t0).total_seconds() == 90 and c.monotonic() == 90
    c.advance(days=1)
    assert c.today_utc() == "2026-01-02"


def test_paths_resolves_once_and_creates_dirs(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    p = Paths("rel_state")
    assert p.root.is_absolute() and p.root == (tmp_path / "rel_state").resolve()
    assert p.ledger_dir.is_dir() and not (p.ledger_dir / "keys").exists()
    monkeypatch.chdir(tmp_path.parent)  # changing cwd later must not move anything
    assert p.entry_halt == (tmp_path / "rel_state" / "entry_halt.json").resolve()


def test_paths_unwritable_raises(tmp_path):
    f = tmp_path / "afile"
    f.write_text("x")
    with pytest.raises(PathsNotWritable):
        Paths(f / "under_a_file")


SPEC_NAMES = ["Paths", "KillSwitch", "EntryHalt", "Intent", "resolve_units", "DailyLimits", "OrderSanity",
              "Ledger", "BrokerPort", "HonestExecutor", "spot_long_only_is_exit", "net_position_is_exit"]


def test_public_api_matches_spec():
    """SPEC §4: the 10 names + 2 predicates are exported one to one; the rest of __all__
    are the support types the spec names in signatures (kept explicit here so a rename
    on either side fails loudly)."""
    import deadman
    for n in SPEC_NAMES:
        assert n in deadman.__all__ and hasattr(deadman, n), n
    support = {"Clock", "SystemClock", "FakeClock", "Verdict", "StateFile", "WriterIdentity", "Seal",
               "SignedLedger", "Entry", "Anchor", "VerifyReport", "KINDS", "GENESIS_HASH", "ANCHOR_AFTER",
               "HaltRecord", "Resolved", "PositionSnapshot", "ExposurePredicate", "Limits", "DailyStats",
               "QuantizeResult", "Order", "BrokerRejected", "ORDER_STATUSES", "ExecResult", "ReconcileReport",
               "client_order_id_for", "errors"}
    assert set(deadman.__all__) == set(SPEC_NAMES) | support


def test_package_imports_only_stdlib_and_itself():
    """Zero runtime dependencies (SPEC §2b) and nothing from the origin system (core/):
    static scan of every import statement in the package."""
    import ast
    import sys
    stdlib = set(sys.stdlib_module_names)
    bad = []
    for fn in os.listdir(PKG):
        if not fn.endswith(".py"):
            continue
        tree = ast.parse(open(os.path.join(PKG, fn), encoding="utf-8").read())
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                if node.level and node.level > 0:
                    continue  # relative import inside the package
                names = [node.module or ""]
            for n in names:
                top = n.split(".")[0]
                if top and top not in stdlib and top != "deadman":
                    bad.append((fn, n))
    assert bad == [], bad
