"""The release gate, tested against the strings it failed to stop.

This file exists because of a specific hole. `scripts/check_published_description.py` ran on
0.2.1, passed, and the release shipped a Summary reading "hash-chained and externally anchored
ledger" - a capability that is off unless the user writes a publisher. The gate did not miss it
by being wrong; it never looked at the Summary at all, only at the long description.

So the controls here are the real historical strings, not invented ones: the 0.2.0 offence, the
0.2.1 offence, and the corrected text that has to pass.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from check_published_description import (  # noqa: E402
    MIN_PLAUSIBLE_DESCRIPTION, OPTIONAL_AS_PRESENT, STALE_CLAIMS, check,
)

#: The Summary that 0.2.1 actually published, and that this gate now has to refuse.
SUMMARY_0_2_1 = (
    "Execution-safety primitives for automated trading systems: kill switch, persistent entry "
    "halt, units contract, honest post-fill state machine, hash-chained and externally anchored "
    "ledger. Zero runtime dependencies."
)

#: The Summary 0.2.2 ships instead.
SUMMARY_0_2_2 = (
    "Execution-safety primitives for automated trading systems: kill switch, persistent entry "
    "halt, units contract, honest post-fill state machine, hash-chained ledger anchorable to a "
    "third party by a publisher you supply. Zero runtime dependencies."
)


def test_the_summary_that_shipped_in_0_2_1_is_refused():
    offences = check(SUMMARY_0_2_1, "Summary")
    assert offences, "the string this gate was written for still passes"
    assert any("externally anchored" in o for o in offences)
    assert all("Summary" in o for o in offences), "the offence must name the field it is in"


def test_the_corrected_summary_passes():
    """Control for the test above. A gate that refuses everything is not a gate either."""
    assert check(SUMMARY_0_2_2, "Summary") == []


def test_the_correction_is_not_cosmetic():
    """Both strings describe the same feature. Only one of them says who supplies it, which is
    the whole distinction the rule exists to enforce."""
    assert "anchor" in SUMMARY_0_2_1.lower() and "anchor" in SUMMARY_0_2_2.lower()
    assert "you supply" in SUMMARY_0_2_2
    assert "you supply" not in SUMMARY_0_2_1


def test_the_stale_claim_that_shipped_in_0_2_0_is_still_refused():
    """The older offence must not have regressed while the new rule was added."""
    offences = check("deadman is not on PyPI yet, so clone the repository.", "description")
    assert any("not on pypi yet" in o.lower() for o in offences)


def test_a_relative_link_is_refused_because_pypi_cannot_resolve_it():
    offences = check("See [the spec](docs/SPEC.md) for details.", "description")
    assert any("RELATIVE LINK" in o for o in offences)
    assert check("See [the spec](https://github.com/x/y/blob/main/docs/SPEC.md).") == []


@pytest.mark.parametrize("phrase", OPTIONAL_AS_PRESENT)
def test_every_blacklisted_phrase_actually_fires(phrase):
    """A blacklist entry that matches nothing is decoration in the gate itself."""
    assert check(f"the ledger is {phrase} and ready", "Summary")


def test_the_blacklist_is_blunt_on_purpose_and_that_is_documented():
    """The rule will fire on prose merely discussing the phrase. That is intended, and the
    intent has to survive in the source, or a future reader will 'fix' it into uselessness."""
    src = (Path(__file__).resolve().parents[1] / "scripts" /
           "check_published_description.py").read_text(encoding="utf-8")
    assert "Blunt on purpose" in src
    assert "a gate that can be argued with has" in src


def test_the_floor_that_stops_a_gate_from_passing_on_nothing_is_still_there():
    """0.2.1's first draft read zero characters and pronounced the release clean."""
    assert MIN_PLAUSIBLE_DESCRIPTION >= 500
    assert STALE_CLAIMS and OPTIONAL_AS_PRESENT
