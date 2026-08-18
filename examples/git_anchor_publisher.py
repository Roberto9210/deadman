"""Example anchor publisher: append the anchor to a file in a git repo, commit,
push to a PROTECTED branch. This is YOUR code, not the library's: deadman never
touches the network. Read SPEC §2b before trusting it as evidence.

What makes the remote a third party (SPEC §2b): the branch must forbid
force-push and deletion for everyone INCLUDING the repository owner/admins.
A remote you can rewrite is not a third party; the anchor is then worth
exactly nothing more than the local chain. Alternatives that qualify: an
RFC 3161 timestamp authority (the token carries the TSA's date over the hash),
or a third-party append-only service with server-side timestamps.

Usage:
    from deadman import Ledger, Paths, SystemClock
    publisher = GitAnchorPublisher(repo_dir="/path/to/anchors-repo", branch="anchors")
    ledger = Ledger(Paths("/path/to/state"), SystemClock(), publisher=publisher,
                    anchor_every_n=100, anchor_every_s=3600)

The publisher receives exactly {"schema_version", "seq", "hash", "ts_utc", "segment"}
(no payloads, no PII) and must return an opaque external reference (here the
commit sha). Raise on failure: the ledger records ANCHOR_FAILED and, if it
persists, ANCHOR_STALE + a visible flag - it never stops execution.
"""
import json
import os
import subprocess


class GitAnchorPublisher:
    def __init__(self, repo_dir: str, branch: str = "anchors", filename: str = "deadman_anchors.jsonl",
                 remote: str = "origin", git: str = "git"):
        self.repo_dir = os.path.abspath(repo_dir)
        self.branch = branch
        self.filename = filename
        self.remote = remote
        self.git = git

    def _run(self, *args) -> str:
        r = subprocess.run([self.git, *args], cwd=self.repo_dir, capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            raise RuntimeError(f"git {' '.join(args)} failed: {r.stderr.strip()}")
        return r.stdout.strip()

    def __call__(self, anchor: dict) -> str:
        line = json.dumps(anchor, sort_keys=True, separators=(",", ":"))
        path = os.path.join(self.repo_dir, self.filename)
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
        self._run("add", self.filename)
        self._run("commit", "-m", f"anchor seq={anchor['seq']} {anchor['hash'][:12]}")
        # push WITHOUT --force. If the branch is protected as SPEC §2b requires, a
        # force-push would be rejected anyway; not passing --force here is not the
        # protection, the branch rule is.
        self._run("push", self.remote, f"HEAD:{self.branch}")
        return self._run("rev-parse", "HEAD")


def read_anchors_from_repo(repo_dir: str, filename: str = "deadman_anchors.jsonl"):
    """Load anchors as the THIRD PARTY holds them (fresh clone/pull), to hand to
    Ledger.verify(anchors=...). external_ref is unknown on this side: use ''."""
    from deadman import Anchor
    out = []
    with open(os.path.join(repo_dir, filename), "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                d = json.loads(line)
                out.append(Anchor(**{**d, "external_ref": d.get("external_ref", "")}))
    return out
