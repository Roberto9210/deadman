import os
import sys
from datetime import datetime, timezone

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from deadman import Paths, FakeClock, WriterIdentity, SignedLedger  # noqa: E402


@pytest.fixture
def clock():
    return FakeClock(datetime(2026, 8, 18, 12, 0, tzinfo=timezone.utc))


@pytest.fixture
def paths(tmp_path):
    return Paths(tmp_path / "state")


@pytest.fixture
def ident(clock):
    return WriterIdentity(clock, pid=1000, pid_alive=lambda pid: pid in (1000, 2000))


@pytest.fixture
def ledger(paths, clock):
    return SignedLedger(paths, clock)
