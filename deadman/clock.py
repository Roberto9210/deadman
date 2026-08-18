"""Injectable UTC clock (SPEC §5.6). No module in deadman calls
datetime.now()/time.time() directly; everything receives a Clock."""
from datetime import datetime, timedelta, timezone
from typing import Protocol


class Clock(Protocol):
    def now_utc(self) -> datetime: ...
    def today_utc(self) -> str: ...
    def monotonic(self) -> float: ...


class SystemClock:
    def now_utc(self) -> datetime:
        return datetime.now(timezone.utc)

    def today_utc(self) -> str:
        return self.now_utc().strftime("%Y-%m-%d")

    def monotonic(self) -> float:
        import time
        return time.monotonic()


class FakeClock:
    """Test clock: starts where you say, only moves when you advance it."""

    def __init__(self, start: datetime | None = None):
        if start is None:
            start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        if start.tzinfo is None:
            raise ValueError("FakeClock start must be timezone-aware (UTC)")
        self._now = start.astimezone(timezone.utc)
        self._mono = 0.0

    def now_utc(self) -> datetime:
        return self._now

    def today_utc(self) -> str:
        return self._now.strftime("%Y-%m-%d")

    def monotonic(self) -> float:
        return self._mono

    def advance(self, seconds: float = 0.0, **kw) -> None:
        delta = timedelta(seconds=seconds, **kw)
        self._now = self._now + delta
        self._mono += delta.total_seconds()


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
