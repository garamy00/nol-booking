import threading
import time

from control import ControlState


def test_stop_flag_set_and_read():
    c = ControlState("20260802", "14:00")
    assert c.should_stop() is False
    c.request_stop()
    assert c.should_stop() is True


def test_pause_resume_toggles_flag_and_state():
    c = ControlState("20260802", "14:00")
    c.pause()
    assert c.is_paused() is True
    assert c.snapshot().state == "paused"
    c.resume()
    assert c.is_paused() is False
    assert c.snapshot().state == "polling"


def test_wait_if_paused_returns_immediately_when_not_paused():
    c = ControlState("20260802", "14:00")
    c.wait_if_paused(poll=0.01)  # 멈추지 않고 반환해야 한다


def test_wait_if_paused_returns_when_stop_even_if_paused():
    c = ControlState("20260802", "14:00")
    c.pause()
    c.request_stop()
    c.wait_if_paused(poll=0.01)  # stop이면 일시정지여도 즉시 반환


def test_wait_if_paused_unblocks_after_resume():
    c = ControlState("20260802", "14:00")
    c.pause()
    result = {"returned": False}

    def waiter():
        c.wait_if_paused(poll=0.01)
        result["returned"] = True

    t = threading.Thread(target=waiter)
    t.start()
    time.sleep(0.05)
    assert result["returned"] is False  # 아직 일시정지
    c.resume()
    t.join(timeout=1.0)
    assert result["returned"] is True


def test_mark_failure_accumulates_and_success_resets():
    c = ControlState("20260802", "14:00")
    assert c.mark_failure() == 1
    assert c.mark_failure() == 2
    assert c.snapshot().consecutive_failures == 2
    c.mark_success()
    assert c.snapshot().consecutive_failures == 0
    assert c.snapshot().last_success_ts is not None


def test_snapshot_reflects_target_and_state():
    c = ControlState("20260802", "14:00")
    snap = c.snapshot()
    assert snap.target_date == "20260802"
    assert snap.target_time == "14:00"
    assert snap.state == "entering"
    assert snap.last_success_ts is None
