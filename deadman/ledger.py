"""Hash-chained, append-only ledger with anchored rotation and external
anchoring (SPEC §2b, §4.5, §5.5; decision C). Zero external dependencies.

Threat model (SPEC §2b): the hash chain detects accidental corruption, partial
writes, buggy rewrites, deletions, reordering and broken rotation. It does NOT
detect a deliberate rewrite by someone with disk access who recomputes the
chain up to the tip - only an ANCHOR published to a third party the operator
does not control does. So the guarantee that matters is the third party's date
on (seq, hash), and the chain is what lets 64 bytes cover the whole history.
An optional signer/verifier pair (two callables, key owned by the user) can be
plugged in; the kit neither generates nor stores keys.

Entry (one JSON object per line):
  {schema_version, seq, ts_utc, kind, actor, payload, prev_hash, hash[, sig]}
  hash = sha256(canonical_json({schema_version, seq, ts_utc, kind, actor, payload, prev_hash}))

Files under Paths.ledger_dir:
  ledger.jsonl          active segment
  ledger.NNNN.jsonl     closed segments (rotate())
  chain_state.json      {"schema_version","last_seq","last_hash"} - the tip only, atomically replaced
  chain_state.lock      content-irrelevant OS lock target
  anchors.jsonl         local copy of published anchors (the truth lives at the publisher)
"""
import hashlib
import json
import os
import sys
import threading
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Callable, Iterable, Mapping, Optional

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
    "ANCHOR_PUBLISHED", "ANCHOR_FAILED", "KILL_ENGAGED", "KILL_RELEASED", "HALT_SET", "HALT_CLEARED",
    "INTENT_DENIED", "ORDER_SENT", "FILL", "PARTIAL_FILL", "NO_FILL_CANCELED", "UNKNOWN_STATE",
    "RECONCILE_REPORT", "DAILY_STATS_RESET", "LEDGER_ROTATED", "CONCURRENT_WRITER_DETECTED", "USER_NOTE",
})
# entries after which an anchor is forced (SPEC §2b): the ones an operator wants dated by a third party
ANCHOR_AFTER = frozenset({"KILL_ENGAGED", "KILL_RELEASED", "HALT_SET", "HALT_CLEARED", "UNKNOWN_STATE",
                          "CONCURRENT_WRITER_DETECTED", "LEDGER_ROTATED"})


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
    sig: Optional[str] = None

    def as_dict(self) -> dict:
        d = asdict(self)
        if d["sig"] is None:
            del d["sig"]
        return d


@dataclass(frozen=True)
class Anchor:
    schema_version: int
    seq: int
    hash: str
    ts_utc: str
    segment: str
    external_ref: str

    def published_form(self) -> dict:
        """Exactly what goes to the third party: no payloads, no PII."""
        return {"schema_version": self.schema_version, "seq": self.seq, "hash": self.hash,
                "ts_utc": self.ts_utc, "segment": self.segment}


@dataclass(frozen=True)
class VerifyReport:
    ok: bool
    code: str
    chain_complete: bool
    verified_from_seq: Optional[int]
    entries_checked: int
    segments_checked: int
    anchors_checked: int = 0
    latest_anchor_seq: Optional[int] = None
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


class Ledger:
    def __init__(self, paths: Paths, clock: Clock,
                 publisher: Callable[[dict], str] | None = None,
                 anchor_every_n: int = 100, anchor_every_s: float = 3600.0,
                 signer: Callable[[bytes], bytes] | None = None,
                 verifier: Callable[[bytes, bytes], bool] | None = None,
                 on_append: Callable[[Entry], None] | None = None,
                 allow_unknown_kinds: bool = False, lock_timeout_s: float = 30.0):
        self.paths = paths
        self.clock = clock
        self.publisher = publisher
        self.anchor_every_n = int(anchor_every_n)
        self.anchor_every_s = float(anchor_every_s)
        self.signer = signer
        self.verifier = verifier
        self.on_append = on_append
        self.allow_unknown_kinds = allow_unknown_kinds
        self.lock_timeout_s = lock_timeout_s
        self._thread_lock = threading.RLock()
        self._entries_since_anchor = 0
        self._last_anchor_mono: Optional[float] = None
        self.paths.chain_lock.touch(exist_ok=True)

    # ---------- locking ----------
    def _lock(self, fh):
        fh.seek(0)
        if sys.platform == "win32":
            # LK_NBLCK + own retry loop: LK_LOCK gives up after 10 internal
            # retries with an OSError (EDEADLK) that is not a PermissionError.
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

    def _locked(self, fn):
        with self._thread_lock:
            with open(self.paths.chain_lock, "r+b") as lf:
                self._lock(lf)
                try:
                    return fn()
                finally:
                    self._unlock(lf)

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

    @staticmethod
    def _first_entry_of(path: Path) -> Optional[dict]:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    return json.loads(line)
        return None

    def last_hash(self) -> str:
        return self._locked(lambda: self._read_tip_unlocked()["last_hash"])

    # ---------- append ----------
    def append(self, kind: str, payload: Mapping, actor: str = "user") -> Entry:
        if not self.allow_unknown_kinds and kind not in KINDS:
            raise LedgerWriteError(f"unknown ledger kind {kind!r}; pass allow_unknown_kinds=True to extend")
        payload = json.loads(json.dumps(payload, default=str))  # plain JSON only
        entry = self._locked(lambda: self._append_unlocked(kind, payload, actor))
        self._maybe_anchor(entry)
        return entry

    def _append_unlocked(self, kind: str, payload: dict, actor: str, tip: Optional[dict] = None) -> Entry:
        # `tip` is passed only by rotate(), which has just renamed the active
        # file and therefore cannot re-read the tail; everyone else re-reads.
        if tip is None:
            tip = self._read_tip_unlocked()
        seq = tip["last_seq"] + 1
        prev_hash = tip["last_hash"]
        ts = iso(self.clock.now_utc())
        h = _entry_hash(SCHEMA_VERSION, seq, ts, kind, actor, payload, prev_hash)
        sig = self.signer(h.encode("utf-8")).hex() if self.signer is not None else None
        entry = Entry(SCHEMA_VERSION, seq, ts, kind, actor, payload, prev_hash, h, sig)
        try:
            with open(self.paths.ledger_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry.as_dict(), sort_keys=True, ensure_ascii=False) + "\n")
                f.flush()
                os.fsync(f.fileno())
        except OSError as e:
            raise LedgerWriteError(f"append failed: {e}") from e
        self._write_tip_unlocked(seq, h)
        self._entries_since_anchor += 1
        if self.on_append is not None:
            try:
                self.on_append(entry)
            except Exception:  # a hook must never break the ledger
                pass
        return entry

    # ---------- anchoring (SPEC §2b) ----------
    def _maybe_anchor(self, entry: Entry) -> None:
        if self.publisher is None:
            return
        if entry.kind in ("ANCHOR_PUBLISHED", "ANCHOR_FAILED"):
            return
        due = entry.kind in ANCHOR_AFTER or self._entries_since_anchor >= self.anchor_every_n
        if not due and self._last_anchor_mono is not None:
            due = (self.clock.monotonic() - self._last_anchor_mono) >= self.anchor_every_s
        if not due and self._last_anchor_mono is None:
            due = True  # first ever entry with a publisher: establish an anchor
        if due:
            self.anchor(reason=f"after:{entry.kind}")

    def anchor(self, reason: str = "manual") -> Optional[Anchor]:
        """Publish the current tip through the user's publisher. Never raises
        out of a publisher failure: records ANCHOR_FAILED and moves on (a ledger
        without a recent anchor is weaker evidence, not an unsafe system)."""
        if self.publisher is None:
            return None
        tip = self._locked(self._read_tip_unlocked)
        if tip["last_seq"] == 0:
            return None
        seg = self._segment_of_seq(tip["last_seq"]) or self.paths.ledger_file.name
        draft = Anchor(SCHEMA_VERSION, tip["last_seq"], tip["last_hash"], iso(self.clock.now_utc()), seg, "")
        try:
            ref = str(self.publisher(draft.published_form()))
        except Exception as e:
            self._locked(lambda: self._append_unlocked("ANCHOR_FAILED", {"seq": draft.seq, "hash": draft.hash,
                                                                          "reason": reason, "error": f"{type(e).__name__}: {e}"}, "deadman.ledger"))
            return None
        anc = Anchor(draft.schema_version, draft.seq, draft.hash, draft.ts_utc, draft.segment, ref)
        with open(self.paths.anchors_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(anc), sort_keys=True) + "\n")
            f.flush()
            os.fsync(f.fileno())
        self._entries_since_anchor = 0
        self._last_anchor_mono = self.clock.monotonic()
        self._locked(lambda: self._append_unlocked("ANCHOR_PUBLISHED", {**asdict(anc), "reason": reason}, "deadman.ledger"))
        return anc

    def local_anchors(self) -> list[Anchor]:
        p = self.paths.anchors_file
        if not p.exists():
            return []
        out = []
        with open(p, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    out.append(Anchor(**json.loads(line)))
        return out

    def _segment_of_seq(self, seq: int) -> Optional[str]:
        cands = [self.paths.ledger_file]
        n = 1
        while self.paths.segment(n).exists():
            cands.append(self.paths.segment(n))
            n += 1
        for pth in cands:
            if not pth.exists():
                continue
            first, last = self._first_entry_of(pth), self._last_entry_of(pth)
            if first and last and int(first["seq"]) <= seq <= int(last["seq"]):
                return pth.name
        return None

    # ---------- rotation (decision C) ----------
    def rotate(self, actor: str = "user") -> Entry:
        def _do():
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
            return self._append_unlocked("LEDGER_ROTATED", payload, actor, tip=tip)
        entry = self._locked(_do)
        self._maybe_anchor(entry)
        return entry

    # ---------- verify ----------
    def verify(self, from_seq: Optional[int] = None, anchors: Optional[Iterable[Anchor]] = None) -> VerifyReport:
        """Walk the active segment, follow LEDGER_ROTATED anchors backwards, then
        check every external anchor's (seq, hash) against the content. Never
        returns ok=True with chain_complete=True unless genesis was reached."""
        checked = 0
        segments = 0
        seg_path = self.paths.ledger_file
        chain_complete = False
        verified_from = None
        seen: dict[int, str] = {}  # seq -> hash, for anchor checks
        expected_last: Optional[tuple[int, str]] = None
        expected_sha: Optional[str] = None
        code = "OK"
        while True:
            if not seg_path.exists():
                code = "SEGMENT_MISSING"
                break
            if expected_sha is not None and _sha256_file(seg_path) != expected_sha:
                return VerifyReport(False, "ROTATION_LINK_BROKEN", False, verified_from, checked, segments,
                                    detail=f"{seg_path.name} sha256 != anchor prev_sha256")
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
                                            detail=f"{seg_path.name}:{i} not JSON")
            segments += 1
            if not entries:
                if seg_path == self.paths.ledger_file and segments == 1:
                    return VerifyReport(True, "EMPTY", True, None, 0, 1, detail="empty ledger")
                return VerifyReport(False, "EMPTY_SEGMENT", False, verified_from, checked, segments, detail=seg_path.name)
            if expected_last is not None:
                last = entries[-1]
                if (int(last.get("seq", -1)), str(last.get("hash", ""))) != expected_last:
                    return VerifyReport(False, "ROTATION_LINK_BROKEN", False, verified_from, checked, segments,
                                        detail=f"{seg_path.name} last entry {last.get('seq')} != anchor {expected_last[0]}")
            for idx in range(len(entries) - 1, -1, -1):
                e = entries[idx]
                try:
                    h = _entry_hash(e["schema_version"], e["seq"], e["ts_utc"], e["kind"], e["actor"], e["payload"], e["prev_hash"])
                except (KeyError, TypeError) as ex:
                    return VerifyReport(False, "MALFORMED_ENTRY", False, verified_from, checked, segments, detail=f"{ex}")
                if h != e.get("hash"):
                    return VerifyReport(False, "HASH_MISMATCH", False, verified_from, checked, segments, detail=f"seq {e.get('seq')}")
                if self.verifier is not None:
                    sig = e.get("sig")
                    try:
                        good = sig is not None and self.verifier(h.encode("utf-8"), bytes.fromhex(sig))
                    except Exception:
                        good = False
                    if not good:
                        return VerifyReport(False, "BAD_SIGNATURE", False, verified_from, checked, segments, detail=f"seq {e.get('seq')}")
                if idx > 0:
                    p = entries[idx - 1]
                    if e["prev_hash"] != p.get("hash") or int(e["seq"]) != int(p.get("seq", -99)) + 1:
                        return VerifyReport(False, "CHAIN_BROKEN", False, verified_from, checked, segments,
                                            detail=f"seq {e['seq']} does not chain from {p.get('seq')}")
                checked += 1
                verified_from = int(e["seq"])
                seen[int(e["seq"])] = h
            first = entries[0]
            if first.get("kind") == "LEDGER_ROTATED":
                pl = first.get("payload", {})
                if pl.get("prev_last_hash") != first.get("prev_hash") or int(pl.get("prev_last_seq", -99)) + 1 != int(first["seq"]):
                    return VerifyReport(False, "ROTATION_LINK_BROKEN", False, verified_from, checked, segments,
                                        detail=f"seq {first.get('seq')}: anchor fields inconsistent")
                expected_last = (int(pl["prev_last_seq"]), str(pl["prev_last_hash"]))
                expected_sha = str(pl.get("prev_sha256", ""))
                seg_path = self.paths.ledger_dir / str(pl.get("prev_segment", ""))
                continue
            if first.get("prev_hash") != GENESIS_HASH or int(first.get("seq", -1)) != 1:
                return VerifyReport(False, "NO_GENESIS", False, verified_from, checked, segments,
                                    detail=f"{seg_path.name} first entry seq {first.get('seq')} does not start at genesis")
            chain_complete = True
            break
        # ---- external anchors ----
        anchors = list(anchors) if anchors is not None else self.local_anchors()
        anchors_checked = 0
        latest = None
        for a in anchors:
            got = seen.get(int(a.seq))
            if got is None:
                continue  # anchor points into an unverified (missing) segment: cannot judge
            anchors_checked += 1
            if got != a.hash:
                return VerifyReport(False, "ANCHOR_MISMATCH", chain_complete, verified_from, checked, segments,
                                    anchors_checked, latest, f"anchor seq {a.seq} hash {a.hash[:12]} != ledger {got[:12]}")
            latest = max(latest or 0, int(a.seq))
        detail = "" if code == "OK" else f"{seg_path.name} missing; verified from seq {verified_from} only"
        return VerifyReport(True, code, chain_complete, verified_from, checked, segments, anchors_checked, latest, detail)


# Alias kept for the first commit's name.
SignedLedger = Ledger
