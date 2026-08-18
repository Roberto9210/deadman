"""JSON state files with a writer seal and atomic replace (SPEC §5.2, §5.7).

Every state file carries {schema_version, writer_pid, writer_started_at,
write_seq, ...data}. Writes are read -> decide -> write; before replacing,
the current seal on disk is re-read and compared with the seal observed at
the start of the cycle. A different seal means another writer got in between:
we do NOT write, we raise ConcurrentWriterDetected. It does not prevent the
race; it makes it loud (decision D).
"""
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

from .clock import Clock, iso
from .errors import ConcurrentWriterDetected

SCHEMA_VERSION = 1


@dataclass(frozen=True)
class Seal:
    writer_pid: int
    writer_started_at: str
    write_seq: int

    def as_dict(self) -> dict:
        return {"writer_pid": self.writer_pid, "writer_started_at": self.writer_started_at, "write_seq": self.write_seq}


@dataclass(frozen=True)
class Read:
    status: str  # "ABSENT" | "OK" | "UNREADABLE"
    data: Optional[dict]
    seal: Optional[Seal]
    error: str = ""


def _default_pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        h = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
        if not h:
            return False
        try:
            code = ctypes.c_ulong()
            ok = ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(code))
            STILL_ACTIVE = 259
            return bool(ok) and code.value == STILL_ACTIVE
        finally:
            ctypes.windll.kernel32.CloseHandle(h)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


class WriterIdentity:
    """Who this process is, for the seal. `started_at` is the process start
    (from the injected clock at construction), not the write time."""

    def __init__(self, clock: Clock, pid: int | None = None, pid_alive: Callable[[int], bool] | None = None):
        self.pid = int(os.getpid() if pid is None else pid)
        self.started_at = iso(clock.now_utc())
        self.pid_alive = pid_alive or _default_pid_alive


class StateFile:
    def __init__(self, path: Path, ident: WriterIdentity, clock: Clock):
        self.path = Path(path)
        self.ident = ident
        self.clock = clock

    # ---- read ----
    def read(self) -> Read:
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except FileNotFoundError:
            return Read("ABSENT", None, None)
        except (OSError, ValueError, UnicodeDecodeError) as e:
            return Read("UNREADABLE", None, None, f"{type(e).__name__}: {e}")
        if not isinstance(raw, dict):
            return Read("UNREADABLE", None, None, "not a JSON object")
        try:
            seal = Seal(int(raw["writer_pid"]), str(raw["writer_started_at"]), int(raw["write_seq"]))
        except (KeyError, TypeError, ValueError) as e:
            return Read("UNREADABLE", None, None, f"seal missing/invalid: {e}")
        data = {k: v for k, v in raw.items() if k not in ("writer_pid", "writer_started_at", "write_seq")}
        return Read("OK", data, seal)

    # ---- write ----
    def write(self, data: Mapping[str, Any], expected: Optional[Seal], force: bool = False) -> Seal:
        """Atomically replace the file with `data` + a fresh seal.
        `expected` is the seal observed when this read->decide->write cycle
        began (None if the file was absent/unreadable then). If the seal on
        disk now differs and force is False -> ConcurrentWriterDetected and
        nothing is written."""
        current = self.read()
        cur_seal = current.seal  # None for ABSENT/UNREADABLE
        if not force and cur_seal != expected:
            raise ConcurrentWriterDetected(self.path, expected, cur_seal)
        next_seq = (cur_seal.write_seq + 1) if cur_seal else 1
        seal = Seal(self.ident.pid, self.ident.started_at, next_seq)
        payload = dict(data)
        payload["schema_version"] = payload.get("schema_version", SCHEMA_VERSION)
        payload.update(seal.as_dict())
        tmp = self.path.with_name(self.path.name + f".tmp.{self.ident.pid}")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.path)
        return seal

    def delete(self, expected: Optional[Seal], force: bool = False) -> bool:
        current = self.read()
        if current.status == "ABSENT":
            return False
        if not force and current.seal != expected:
            raise ConcurrentWriterDetected(self.path, expected, current.seal)
        try:
            os.remove(self.path)
        except FileNotFoundError:
            return False
        return True

    # ---- startup ----
    def foreign_live_writer(self) -> Optional[Seal]:
        """At startup: if the file is owned by another pid that is still
        alive, return its seal (caller raises/halts). Own pid or dead pid -> None."""
        r = self.read()
        if r.status != "OK" or r.seal is None:
            return None
        if r.seal.writer_pid == self.ident.pid:
            return None
        return r.seal if self.ident.pid_alive(r.seal.writer_pid) else None
