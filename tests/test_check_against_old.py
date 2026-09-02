"""The tool that tells a control that FAILED from a control that never RAN.

It exists because the distinction was made by eye twice in one day and went wrong twice, the same
way both times: the test file would not import against the old code, pytest collected nothing, and
the output looked like a run. Nothing failed, so nothing looked wrong.

These tests are on `classify()`, which is where the three outcomes are separated. The swap-and-
restore half is exercised for real every time the command is used, and its own guarantee - that
the working tree comes back byte-identical - is checked by the command itself before it reports.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "check_against_old", ROOT / "scripts" / "check_against_old.py")
cao = importlib.util.module_from_spec(_spec)
sys.modules["check_against_old"] = cao
_spec.loader.exec_module(cao)


COLLECTION_ERROR = """\
ImportError: cannot import name 'entry_body' from 'deadman.ledger'
=========================== short test summary info ===========================
ERROR tests/test_g11_ledger.py
!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
1 error in 0.23s
"""

TWO_FAILED = """\
=========================== short test summary info ===========================
FAILED tests/test_c_certificate.py::test_def6_a_ledger_cut_short_is_not_a_lie
FAILED tests/test_c_certificate.py::test_def6_never_says_the_trader_breached
2 failed, 3 passed, 54 deselected in 0.19s
"""

ALL_PASSED = "5 passed, 54 deselected in 0.20s\n"


def test_a_run_that_never_collected_is_not_a_run_that_passed():
    """THE CASE THE TOOL EXISTS FOR. Zero failures here does not mean the control held: it means
    nothing was measured. This is §5.8 rung 4 pointed at our own test bench."""
    verdict, detail = cao.classify(COLLECTION_ERROR, expected=2)
    assert verdict == cao.DID_NOT_RUN
    assert "collected nothing" in detail


def test_zero_failures_without_a_collection_error_is_merely_a_different_result():
    """CONTROL for the test above: the same failure COUNT, a different cause, a different verdict.

    Without this pair, `classify` could return DID_NOT_RUN for everything that fails to reach the
    expected count and both tests would still pass."""
    verdict, detail = cao.classify(ALL_PASSED, expected=2)
    assert verdict == cao.DIFFERENT
    assert "got 0" in detail


def test_the_expected_failures_make_the_control_hold():
    verdict, detail = cao.classify(TWO_FAILED, expected=2)
    assert verdict == cao.HOLDS
    assert "3 passed against BOTH versions" in detail


def test_more_failures_than_expected_is_not_success_either():
    """A fix that breaks more than it was aimed at is a different result, not a better one."""
    verdict, _ = cao.classify(TWO_FAILED, expected=1)
    assert verdict == cao.DIFFERENT


def test_empty_output_is_treated_as_not_having_run():
    """A crashed interpreter prints nothing and fails nothing. Same class as the collection error:
    absence of failures is not evidence of anything."""
    verdict, _ = cao.classify("", expected=0)
    assert verdict == cao.DID_NOT_RUN


def test_the_three_verdicts_use_this_repository_s_own_exit_codes():
    """0 ok / 1 contradicted / 2 could-not-look, the same vocabulary the verifier publishes. A
    control that did not run is UNEVALUABLE, which is exactly what the number should say."""
    assert (cao.HOLDS, cao.DIFFERENT, cao.DID_NOT_RUN) == (0, 1, 2)
