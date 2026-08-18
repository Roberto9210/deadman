"""Example: verify a ledger against anchors fetched from the third party.

Run:  python examples/verify_against_anchors.py /path/to/state /path/to/anchors-repo

The point of using the third party's copy (and not ledger/anchors.jsonl) is
SPEC §2b: an attacker with disk access can rewrite the ledger, recompute the
chain to the tip AND wipe the local anchors file. Only the copy the operator
cannot rewrite can contradict that.
"""
import sys

from deadman import Ledger, Paths, SystemClock

sys.path.insert(0, __import__("os").path.dirname(__file__))
from git_anchor_publisher import read_anchors_from_repo  # noqa: E402


def main(state_root: str, anchors_repo: str) -> int:
    ledger = Ledger(Paths(state_root), SystemClock())
    anchors = read_anchors_from_repo(anchors_repo)
    rep = ledger.verify(anchors=anchors)
    print(f"ok={rep.ok} code={rep.code} chain_complete={rep.chain_complete} "
          f"entries={rep.entries_checked} segments={rep.segments_checked} "
          f"anchors_checked={rep.anchors_checked} latest_anchor_seq={rep.latest_anchor_seq}")
    if rep.detail:
        print("detail:", rep.detail)
    if rep.ok and rep.chain_complete and rep.latest_anchor_seq is not None:
        print(f"=> everything up to seq {rep.latest_anchor_seq} is dated by the third party and unchanged; "
              f"entries after it are covered by the chain only.")
    return 0 if rep.ok else 1


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(sys.argv[1], sys.argv[2]))
