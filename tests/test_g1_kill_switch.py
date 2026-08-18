"""G1 - kill switch: existence, never content (SPEC §6, decision A)."""
import os
import stat

from deadman import KillSwitch


def test_absent_passes(paths):
    ks = KillSwitch(paths)
    v = ks.check()
    assert v.allowed and v.code == "KILL_SWITCH_CLEAR"


def test_present_blocks(paths):
    paths.kill_sentinel.write_text("stop", encoding="utf-8")
    v = KillSwitch(paths).check()
    assert not v.allowed and v.code == "KILL_SWITCH_ACTIVE"


def test_garbage_binary_content_still_blocks_without_exception(paths):
    paths.kill_sentinel.write_bytes(b"\xff\xfe\x00\x00{not json" * 100)
    v = KillSwitch(paths).check()
    assert not v.allowed and v.code == "KILL_SWITCH_ACTIVE"


def test_unreadable_content_still_blocks(paths):
    paths.kill_sentinel.write_text("x", encoding="utf-8")
    os.chmod(paths.kill_sentinel, stat.S_IWRITE)  # remove read permission where the OS honours it
    try:
        v = KillSwitch(paths).check()
        assert not v.allowed and v.code == "KILL_SWITCH_ACTIVE"
    finally:
        os.chmod(paths.kill_sentinel, stat.S_IWRITE | stat.S_IREAD)


def test_check_never_opens_the_file(paths, monkeypatch):
    paths.kill_sentinel.write_text("x", encoding="utf-8")
    import builtins
    real_open = builtins.open

    def spy(path, *a, **k):
        if str(path) == str(paths.kill_sentinel):
            raise AssertionError("kill switch opened the sentinel")
        return real_open(path, *a, **k)
    monkeypatch.setattr(builtins, "open", spy)
    assert not KillSwitch(paths).check().allowed


def test_os_error_on_check_blocks(paths, monkeypatch):
    def boom(_):
        raise OSError("disk gone")
    monkeypatch.setattr(os.path, "exists", boom)
    v = KillSwitch(paths).check()
    assert not v.allowed and v.code == "KILL_SWITCH_CHECK_FAILED"


def test_engage_release_idempotent_and_ledgered(paths, ledger):
    ks = KillSwitch(paths, ledger=ledger)
    ks.engage("test reason")
    ks.engage("again")  # idempotent
    assert paths.kill_sentinel.exists() and not ks.check().allowed
    assert ks.release("done") is True
    assert ks.release("done") is False  # already gone
    assert ks.check().allowed
    kinds = [e["kind"] for e in _lines(paths.ledger_file)]
    assert kinds == ["KILL_ENGAGED", "KILL_ENGAGED", "KILL_RELEASED"]


def test_engage_writes_sentinel_even_if_ledger_fails(paths):
    class BadLedger:
        def append(self, *a, **k):
            raise RuntimeError("ledger down")
    ks = KillSwitch(paths, ledger=BadLedger())
    ks.engage("r")
    assert paths.kill_sentinel.exists()
    assert not ks.check().allowed


def test_blocks_entries_and_exits_alike(paths):
    # the kill switch has no notion of side: same verdict for anything
    paths.kill_sentinel.touch()
    ks = KillSwitch(paths)
    assert not ks.check().allowed and not ks.check().allowed


def _lines(p):
    import json
    return [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]
