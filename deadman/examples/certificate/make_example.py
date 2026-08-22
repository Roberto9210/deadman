"""Regenerates the worked example in this directory.

The files it writes are checked in so anyone can run the verifier immediately, without
owning a guardian and without trusting us to hand them an honest one. They are synthetic,
but built with the real hashing rules, so the chain in `ledger.jsonl` is a real chain and
the hashes in the certificates are real hashes.

    python deadman/examples/certificate/make_example.py

`tests/test_c_certificate_example.py` runs the shipped files on every test run, so this
example cannot rot into a lie about what the tool does - including a check that these exact
bytes come back out of this script, which is why the writes below pin their line endings.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from deadman.verify_certificate import (
    GUARDIAN_CORE_V1, REQUIRED_LIMITATIONS, _cert_preimage, canonical_json, recompute_claims,
)

HERE = Path(__file__).parent
DAY = "2026-08-19"


def ts(n: int) -> str:
    return f"{DAY}T{13 + n // 60:02d}:{n % 60:02d}:00.000Z"


# A day that is honest and not boring: the trader armed, tried twice to loosen the limit and
# was refused both times, lost the account connection for a stretch, and never breached.
EVENTS = [
    ("GUARDIAN_STARTED", {"fresh": True, "state": "DISARMED"}),
    ("CONFIG_LOADED", {"configHash": "9f2c1a7e5d3b8046"}),
    ("ARMED", {"accounts": ["Sim101"], "dayKey": DAY,
               "personalLimit": "600.00", "firmLimit": "1000.00"}),
    ("SEAL_CREATED", {"expiresAtUtc": f"{DAY}T22:00:00.000Z", "sealDurationMs": 31500000}),
    ("DAY_OPENED", {"dayKey": DAY}),
    ("PNL_CHECKPOINT", {"dayLoss": "0.00", "perAccount": {"Sim101": "0.00"}, "trigger": "interval"}),
    ("CONFIG_CHANGE_REJECTED", {"attempted": "1500.00", "sealed": "600.00"}),
    ("PNL_CHECKPOINT", {"dayLoss": "185.00", "perAccount": {"Sim101": "-185.00"}, "trigger": "interval"}),
    ("CONFIG_CHANGE_REJECTED", {"attempted": "900.00", "sealed": "600.00"}),
    ("ACCOUNT_UNKNOWN", {"account": "Sim101", "detail": "account is Disconnected"}),
    ("FAIL_CLOSED_ENTERED", {"reason": "AccountUnknown on Sim101: account is Disconnected"}),
    ("ACCOUNT_UNKNOWN", {"account": "Sim101", "detail": "account is Disconnected"}),
    ("ACCOUNT_UNKNOWN", {"account": "Sim101", "detail": "account is Disconnected"}),
    ("FAIL_CLOSED_CLEARED", {"previousReason": "AccountUnknown on Sim101: account is Disconnected"}),
    ("PNL_CHECKPOINT", {"dayLoss": "185.00", "perAccount": {"Sim101": "-185.00"}, "trigger": "transition"}),
    ("DAY_CLOSED", {"dayKey": DAY}),
]


def build_ledger() -> list[dict]:
    out, prev = [], GUARDIAN_CORE_V1.genesis
    for i, (event, payload) in enumerate(EVENTS, start=1):
        e = {"seq": i, "tsUtc": ts(i * 7), "event": event,
             "schemaVersion": 1, "payload": payload, "prev": prev}
        e["hash"] = GUARDIAN_CORE_V1.hash_of(e)
        prev = e["hash"]
        out.append(e)
    return out


#: The shape IssuerIdentity.VersionOf emits: semantic version, pre-release suffix, and the
#: source commit the SDK appends. Synthetic here, but the same form a real certificate carries.
EXAMPLE_VERSION = "0.1.0-beta+0000000000000000000000000000000000000000"

#: The shape IssuerIdentity.BuildHashOf emits: 16 lowercase hex, sha256 over the assembly's
#: bytes. Derived below from synthetic bytes, so it is a real hash of something that is not a
#: real build - which is exactly what an example should be.
EXAMPLE_BUILD_HASH = hashlib.sha256(b"deadman-guardian example build, not a real assembly")\
    .hexdigest()[:16]


def build_certificate(entries: list[dict], salt: str, *, issuer_known: bool = True) -> dict:
    lo, hi = 1, max(e["seq"] for e in entries)
    c = recompute_claims(entries, GUARDIAN_CORE_V1, lo, hi, True)
    cert = {
        "certVersion": 1,
        "ledgerDialect": "guardian-core-v1",
        # Rule 1: a value the emitter cannot determine is OMITTED, never defaulted. The
        # unknown-issuer example below exercises that branch so the published set shows it.
        "issuer": ({"tool": "deadman-guardian", "version": EXAMPLE_VERSION,
                    "buildHash": EXAMPLE_BUILD_HASH}
                   if issuer_known else {"tool": "deadman-guardian"}),
        "subject": {"alias": "example-trader",
                    "accounts": [hashlib.sha256(f"{salt}:Sim101".encode()).hexdigest()[:16]]},
        "session": {"dayKey": DAY, "openedUtc": ts(7), "timezone": "America/Chicago"},
        "previousCertHash": None,
        "continuity": {"daysCovered": 1, "gaps": []},
        "commitment": {
            "armedAtUtc": ts(21), "sealHash": "9f2c1a7e5d3b8046" + "0" * 48,
            "sealExpiryUtc": f"{DAY}T22:00:00.000Z",
            "personalDailyLossLimit": "600.00", "firmDailyLossLimit": "1000.00",
            "changeAttemptsWhileSealed": c["changeAttemptsWhileSealed"],
        },
        "claims": {
            "limitRespected": c["limitRespected"],
            "lockoutsTriggered": c["lockoutsTriggered"],
            "ordersRejectedWhileLocked": c["ordersRejectedWhileLocked"],
            "failClosedEpisodes": c["failClosedEpisodes"],
            "clockAnomalies": c["clockAnomalies"],
            "ledgerRange": {"fromSeq": lo, "toSeq": hi},
            "ledgerVerified": True,
        },
        "anchors": [],
        "trustLevel": "L1",
        "limitations": list(REQUIRED_LIMITATIONS),
        "verifyInstructions": {
            "tool": "deadman-kit", "install": "pip install deadman-kit",
            "command": "python -m deadman.verify_certificate certificate.json ledger.jsonl",
        },
    }
    cert["certHash"] = hashlib.sha256(_cert_preimage(cert)).hexdigest()
    return cert


def main() -> None:
    HERE.mkdir(parents=True, exist_ok=True)
    entries = build_ledger()
    # newline="\r\n" on every write, not the platform default. This repository freezes line
    # endings (`* -text` in .gitattributes, "Every blob in this repo is CRLF"), so a file
    # generated on a POSIX runner with the default translation writes LF and then fails to
    # reproduce against the checked-in blob. A generated artefact has to be the same bytes
    # everywhere - the same rule the ledger hashing lives by, applied to the file itself.
    (HERE / "ledger.jsonl").write_text(
        "\n".join(json.dumps(e, sort_keys=True, separators=(",", ":")) for e in entries) + "\n",
        encoding="utf-8", newline="\r\n")

    honest = build_certificate(entries, salt="c1d0f4a9" * 8)
    (HERE / "certificate.json").write_text(
        canonical_json(honest).decode("utf-8"), encoding="utf-8", newline="\r\n")

    # The same day, with the two refused attempts to loosen the limit quietly zeroed. Everything
    # else about it is untouched, including the certHash, which is recomputed so the document is
    # internally consistent. It is caught because the verifier counts the events itself.
    liar = json.loads(json.dumps(honest))
    liar["commitment"]["changeAttemptsWhileSealed"] = 0
    liar["subject"]["alias"] = "example-trader-lying"
    liar["certHash"] = hashlib.sha256(_cert_preimage(liar)).hexdigest()
    (HERE / "certificate-tampered.json").write_text(
        canonical_json(liar).decode("utf-8"), encoding="utf-8", newline="\r\n")

    # The truncation attack: the SAME ledger, but the certificate declares a range that stops
    # before the two refused attempts and the fail-closed episode. Every claim in it is
    # recomputed honestly over that window, so the document is internally perfect. It is the
    # attack that got past the verifier until a check on the range itself was added.
    truncated = build_certificate(entries[:6], salt="c1d0f4a9" * 8)
    truncated["subject"]["alias"] = "example-trader-truncated"
    truncated["certHash"] = hashlib.sha256(_cert_preimage(truncated)).hexdigest()
    (HERE / "certificate-truncated.json").write_text(
        canonical_json(truncated).decode("utf-8"), encoding="utf-8", newline="\r\n")

    # A clean day whose emitter could not determine its own version or build hash - the
    # branch rule 1 describes. One lesson per file: this one teaches omission and nothing else,
    # which is why it is not folded into the truncated-range example.
    unknown = build_certificate(entries, salt="c1d0f4a9" * 8, issuer_known=False)
    unknown["subject"]["alias"] = "example-trader-unknown-issuer"
    unknown["certHash"] = hashlib.sha256(_cert_preimage(unknown)).hexdigest()
    (HERE / "certificate-unknown-issuer.json").write_text(
        canonical_json(unknown).decode("utf-8"), encoding="utf-8", newline="\r\n")

    print(f"wrote {len(entries)} ledger entries")
    print("certificate.json            certHash", honest["certHash"][:16])
    print("certificate-tampered.json   certHash", liar["certHash"][:16])
    print("certificate-truncated.json  certHash", truncated["certHash"][:16])
    print("certificate-unknown-issuer  certHash", unknown["certHash"][:16], "(issuer fields omitted)")


if __name__ == "__main__":
    main()
