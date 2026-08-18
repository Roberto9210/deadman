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
