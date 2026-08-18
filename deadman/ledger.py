"""Signed, hash-chained, append-only ledger with anchored rotation
(SPEC §4.5, §5.5, decision C).

Entry (one JSON object per line):
  {schema_version, seq, ts_utc, kind, actor, payload, prev_hash, hash, sig}
  hash = sha256(canonical_json({schema_version, seq, ts_utc, kind, actor, payload, prev_hash}))
  sig  = Ed25519 signature (hex) over hash.encode()

Files under Paths.ledger_dir:
  ledger.jsonl            active segment
  ledger.NNNN.jsonl       closed segments (rotate())
  chain_state.json        {"schema_version", "last_seq", "last_hash", "active_segment"} - the tip only
  chain_state.lock        content-irrelevant OS lock target
  keys/ed25519.seed       32-byte seed, hex; keys/ed25519.pub hex

The whole read-tip -> build -> append -> replace-tip cycle runs under an OS
lock so two processes cannot fork the chain. A verify() report NEVER says
plain OK when a segment is missing (chain_complete=False).
"""
import hashlib
import json
import os
import sys
import threading
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Callable, Mapping, Optional

import nacl.signing
import nacl.exceptions

from .clock import Clock, iso
from .errors import LedgerIntegrityError, LedgerWriteError
from .paths import Paths

if sys.platform == "win32":
    import msvcrt
else:
    import fcntl

SCHEMA_VERSION = 1
GENESIS_HASH = "0" * 64
KINDS = frozenset({
    "KEY_GENERATED", "KILL_ENGAGED", "KILL_RELEASED", "HALT_SET", "HALT_CLEARED", "INTENT_DENIED",
    "ORDER_SENT", "FILL", "PARTIAL_FILL", "NO_FILL_CANCELED", "UNKNOWN_STATE", "RECONCILE_REPORT",
    "DAILY_STATS_RESET", "LEDGER_ROTATED", "CONCURRENT_WRITER_DETECTED", "USER_NOTE",
})


@dataclass(frozen=True)
class Entry:
    schema_version: int
    seq: int
    ts_utc: str
    kind: str
    actor: str
    payload: dict
    prev_hash: str
    hash: str
    sig: str

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class VerifyReport:
    ok: bool
    code: str
    chain_complete: bool
    verified_from_seq: Optional[int]
    entries_checked: int
    segments_checked: int
    detail: str = ""


def canonical_json(obj: Mapping) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _entry_hash(schema_version, seq, ts_utc, kind, actor, payload, prev_hash) -> str:
    body = {"schema_version": schema_version, "seq": seq, "ts_utc": ts_utc, "kind": kind,
            "actor": actor, "payload": payload, "prev_hash": prev_hash}
    return hashlib.sha256(canonical_json(body)).hexdigest()


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


class SignedLedger:
    def __init__(self, paths: Paths, clock: Clock, signing_key: bytes | None = None,
                 on_append: Callable[[Entry], None] | None = None, allow_unknown_kinds: bool = False,
                 lock_timeout_s: float = 30.0):
        self.paths = paths
        self.clock = clock
        self.on_append = on_append
        self.allow_unknown_kinds = allow_unknown_kinds
        self.lock_timeout_s = lock_timeout_s
        self._thread_lock = threading.RLock()
        self._key = self._load_or_create_key(signing_key)
        self.paths.chain_lock.touch(exist_ok=True)

    # ---------- keys ----------
    def _load_or_create_key(self, seed: bytes | None) -> nacl.signing.SigningKey:
        seed_path = self.paths.keys_dir / "ed25519.seed"
        pub_path = self.paths.keys_dir / "ed25519.pub"
        if seed is not None:
            key = nacl.signing.SigningKey(seed)
        elif seed_path.exists():
            key = nacl.signing.SigningKey(bytes.fromhex(seed_path.read_text(encoding="utf-8").strip()))
        else:
            key = nacl.signing.SigningKey.generate()
            self._write_private(seed_path, key.encode().hex())
            pub_path.write_text(key.verify_key.encode().hex(), encoding="utf-8")
            self._generated = True
        if not pub_path.exists():
            pub_path.write_text(key.verify_key.encode().hex(), encoding="utf-8")
        return key

    @staticmethod
    def _write_private(path: Path, text: str) -> None:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)

    def public_key(self) -> bytes:
        return self._key.verify_key.encode()

    # ---------- locking ----------
    def _lock(self, fh):
        fh.seek(0)
        if sys.platform == "win32":
            # LK_NBLCK (non-blocking) + our own retry loop. LK_LOCK gives up
            # after 10 internal retries with an OSError (EDEADLK) that is NOT a
            # PermissionError - under real contention that escaped the loop and
            # crashed a writer (seen once in the two-process test).
            deadline = time.monotonic() + self.lock_timeout_s
            while True:
                try:
                    msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
                    return
                except OSError:
                    if time.monotonic() > deadline:
                        raise LedgerWriteError(f"could not acquire ledger lock within {self.lock_timeout_s}s")
                    time.sleep(0.005)
        else:
            fcntl.flock(fh, fcntl.LOCK_EX)

    def _unlock(self, fh):
        fh.seek(0)
        if sys.platform == "win32":
            msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            fcntl.flock(fh, fcntl.LOCK_UN)

    # ---------- tip ----------
    def _read_tip_unlocked(self) -> dict:
        """Tip from chain_state.json, cross-checked against the active file's
        last line. Disagreement is an integrity error, never silently healed."""
        tail = self._last_entry_of(self.paths.ledger_file)
        if self.paths.chain_state.exists():
            try:
                with open(self.paths.chain_state, "r", encoding="utf-8") as f:
                    st = json.load(f)
                last_seq, last_hash = int(st["last_seq"]), str(st["last_hash"])
            except (OSError, ValueError, KeyError, TypeError) as e:
                raise LedgerIntegrityError(f"chain_state.json unreadable: {e}") from e
            if tail is None:
                if last_hash != GENESIS_HASH or last_seq != 0:
                    raise LedgerIntegrityError("chain_state says non-genesis tip but ledger file is empty")
            elif tail["seq"] != last_seq or tail["hash"] != last_hash:
                raise LedgerIntegrityError(
                    f"chain_state tip ({last_seq},{last_hash[:12]}) != file tail ({tail['seq']},{tail['hash'][:12]})")
            return {"last_seq": last_seq, "last_hash": last_hash}
        if tail is None:
            return {"last_seq": 0, "last_hash": GENESIS_HASH}
        return {"last_seq": int(tail["seq"]), "last_hash": str(tail["hash"])}

    def _write_tip_unlocked(self, last_seq: int, last_hash: str) -> None:
        tmp = self.paths.chain_state.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"schema_version": SCHEMA_VERSION, "last_seq": last_seq, "last_hash": last_hash}, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.paths.chain_state)

    @staticmethod
    def _last_entry_of(path: Path) -> Optional[dict]:
        if not path.exists():
            return None
        last = None
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    last = line
        if last is None:
            return None
        try:
            return json.loads(last)
        except ValueError as e:
            raise LedgerIntegrityError(f"last ledger line is not JSON: {e}") from e

    def last_hash(self) -> str:
        with self._thread_lock:
            with open(self.paths.chain_lock, "r+b") as lf:
                self._lock(lf)
                try:
                    return self._read_tip_unlocked()["last_hash"]
                finally:
                    self._unlock(lf)

    # ---------- append ----------
    def append(self, kind: str, payload: Mapping, actor: str = "user") -> Entry:
        if not self.allow_unknown_kinds and kind not in KINDS:
            raise LedgerWriteError(f"unknown ledger kind {kind!r}; pass allow_unknown_kinds=True to extend")
        payload = json.loads(json.dumps(payload, default=str))  # plain JSON only
        with self._thread_lock:
            with open(self.paths.chain_lock, "r+b") as lf:
                self._lock(lf)
                try:
                    return self._append_unlocked(kind, payload, actor)
                finally:
                    self._unlock(lf)

    def _append_unlocked(self, kind: str, payload: dict, actor: str, tip: Optional[dict] = None) -> Entry:
        # `tip` is passed only by rotate(), which has just renamed the active
        # file and therefore cannot re-read the tail; everyone else re-reads.
        if tip is None:
            tip = self._read_tip_unlocked()
        seq = tip["last_seq"] + 1
        prev_hash = tip["last_hash"]
        ts = iso(self.clock.now_utc())
        h = _entry_hash(SCHEMA_VERSION, seq, ts, kind, actor, payload, prev_hash)
        sig = self._key.sign(h.encode("utf-8")).signature.hex()
        entry = Entry(SCHEMA_VERSION, seq, ts, kind, actor, payload, prev_hash, h, sig)
        try:
            with open(self.paths.ledger_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry.as_dict(), sort_keys=True, ensure_ascii=False) + "\n")
                f.flush()
                os.fsync(f.fileno())
        except OSError as e:
            raise LedgerWriteError(f"append failed: {e}") from e
        self._write_tip_unlocked(seq, h)
        if self.on_append is not None:
            try:
                self.on_append(entry)
            except Exception:  # a hook must never break the ledger
                pass
        return entry

    # ---------- rotation (decision C) ----------
    def rotate(self, actor: str = "user") -> Entry:
        with self._thread_lock:
            with open(self.paths.chain_lock, "r+b") as lf:
                self._lock(lf)
                try:
                    tip = self._read_tip_unlocked()
                    if tip["last_seq"] == 0:
                        raise LedgerWriteError("nothing to rotate: ledger is empty")
                    first = self._first_entry_of(self.paths.ledger_file)
                    n = 1
                    while self.paths.segment(n).exists():
                        n += 1
                    closed = self.paths.segment(n)
                    os.replace(self.paths.ledger_file, closed)
                    payload = {
                        "prev_segment": closed.name,
                        "prev_last_seq": tip["last_seq"],
                        "prev_last_hash": tip["last_hash"],
                        "prev_first_seq": int(first["seq"]),
                        "prev_sha256": _sha256_file(closed),
                    }
                    # first entry of the new active file chains from the closed file's last hash
                    return self._append_unlocked("LEDGER_ROTATED", payload, actor, tip=tip)
                finally:
                    self._unlock(lf)

    @staticmethod
    def _first_entry_of(path: Path) -> Optional[dict]:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    return json.loads(line)
        return None

    # ---------- verify ----------
    def verify(self, from_seq: Optional[int] = None) -> VerifyReport:
        """Walk the active segment, then follow LEDGER_ROTATED anchors backwards.
        Never returns ok=True with chain_complete=True unless genesis was reached."""
        vk = self._key.verify_key
        checked = 0
        segments = 0
        seg_path = self.paths.ledger_file
        chain_complete = False
        verified_from = None
        # verify segments back to genesis or first missing one
        expected_last: Optional[tuple[int, str]] = None  # (seq, hash) that this segment must end with
        expected_sha: Optional[str] = None
        while True:
            if not seg_path.exists():
                return VerifyReport(True, "SEGMENT_MISSING", False, verified_from, checked, segments,
                                    f"{seg_path.name} missing; verified from seq {verified_from} only")
            if expected_sha is not None and _sha256_file(seg_path) != expected_sha:
                return VerifyReport(False, "ROTATION_LINK_BROKEN", False, verified_from, checked, segments,
                                    f"{seg_path.name} sha256 != anchor prev_sha256")
            entries = []
            with open(seg_path, "r", encoding="utf-8") as f:
                for i, line in enumerate(f, 1):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entries.append(json.loads(line))
                    except ValueError:
                        return VerifyReport(False, "MALFORMED_LINE", False, verified_from, checked, segments,
                                            f"{seg_path.name}:{i} not JSON")
            segments += 1
            if not entries:
                if seg_path == self.paths.ledger_file and segments == 1:
                    return VerifyReport(True, "EMPTY", True, None, 0, 1, "empty ledger")
                return VerifyReport(False, "EMPTY_SEGMENT", False, verified_from, checked, segments, seg_path.name)
            # within-segment checks, from last to first
            if expected_last is not None:
                last = entries[-1]
                if (int(last.get("seq", -1)), str(last.get("hash", ""))) != expected_last:
                    return VerifyReport(False, "ROTATION_LINK_BROKEN", False, verified_from, checked, segments,
                                        f"{seg_path.name} last entry {last.get('seq')} != anchor {expected_last[0]}")
            for idx in range(len(entries) - 1, -1, -1):
                e = entries[idx]
                try:
                    h = _entry_hash(e["schema_version"], e["seq"], e["ts_utc"], e["kind"], e["actor"], e["payload"], e["prev_hash"])
                except (KeyError, TypeError) as ex:
                    return VerifyReport(False, "MALFORMED_ENTRY", False, verified_from, checked, segments, f"seq? {ex}")
                if h != e.get("hash"):
                    return VerifyReport(False, "HASH_MISMATCH", False, verified_from, checked, segments, f"seq {e.get('seq')}")
                try:
                    vk.verify(h.encode("utf-8"), bytes.fromhex(e.get("sig", "")))
                except (nacl.exceptions.BadSignatureError, ValueError):
                    return VerifyReport(False, "BAD_SIGNATURE", False, verified_from, checked, segments, f"seq {e.get('seq')}")
                if idx > 0:
                    p = entries[idx - 1]
                    if e["prev_hash"] != p.get("hash") or int(e["seq"]) != int(p.get("seq", -99)) + 1:
                        return VerifyReport(False, "CHAIN_BROKEN", False, verified_from, checked, segments,
                                            f"seq {e['seq']} does not chain from {p.get('seq')}")
                checked += 1
                verified_from = int(e["seq"])
            first = entries[0]
            if first.get("kind") == "LEDGER_ROTATED":
                pl = first.get("payload", {})
                if pl.get("prev_last_hash") != first.get("prev_hash"):
                    return VerifyReport(False, "ROTATION_LINK_BROKEN", False, verified_from, checked, segments,
                                        f"seq {first.get('seq')}: prev_last_hash != prev_hash")
                if int(pl.get("prev_last_seq", -99)) + 1 != int(first["seq"]):
                    return VerifyReport(False, "ROTATION_LINK_BROKEN", False, verified_from, checked, segments,
                                        f"seq {first.get('seq')}: prev_last_seq+1 != seq")
                expected_last = (int(pl["prev_last_seq"]), str(pl["prev_last_hash"]))
                expected_sha = str(pl.get("prev_sha256", ""))
                seg_path = self.paths.ledger_dir / str(pl.get("prev_segment", ""))
                continue
            # not a rotation anchor: must be genesis
            if first.get("prev_hash") != GENESIS_HASH or int(first.get("seq", -1)) != 1:
                return VerifyReport(False, "NO_GENESIS", False, verified_from, checked, segments,
                                    f"{seg_path.name} first entry seq {first.get('seq')} does not start at genesis")
            chain_complete = True
            break
        return VerifyReport(True, "OK", chain_complete, verified_from, checked, segments)
