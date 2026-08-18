"""Single explicit root for every state file (SPEC §5.1). Resolved once at
construction; nothing in deadman uses os.getcwd() or __file__ afterwards."""
import os
from pathlib import Path

from .errors import PathsNotWritable


class Paths:
    def __init__(self, root: os.PathLike | str):
        self.root = Path(root).resolve()
        self.kill_sentinel = self.root / "kill_switch.enabled"
        self.entry_halt = self.root / "entry_halt.json"
        self.daily_stats = self.root / "daily_stats.json"
        self.ledger_dir = self.root / "ledger"
        self.ledger_file = self.ledger_dir / "ledger.jsonl"
        self.chain_state = self.ledger_dir / "chain_state.json"
        self.chain_lock = self.ledger_dir / "chain_state.lock"
        self.keys_dir = self.ledger_dir / "keys"
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            self.ledger_dir.mkdir(parents=True, exist_ok=True)
            self.keys_dir.mkdir(parents=True, exist_ok=True)
            probe = self.root / ".deadman_write_probe"
            with open(probe, "w", encoding="utf-8") as f:
                f.write("ok")
            os.remove(probe)
        except OSError as e:
            raise PathsNotWritable(f"cannot write state under {self.root}: {e}") from e

    def segment(self, n: int) -> Path:
        return self.ledger_dir / f"ledger.{n:04d}.jsonl"

    def __repr__(self) -> str:
        return f"Paths({str(self.root)!r})"
