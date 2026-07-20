import pytest

from config import AppConfig, NtokConfig, PollConfig, Target, TelegramConfig
from errors import DriverError
from seats import Seat
from state import SeatState
import monitor


class FakeDriver:
    def __init__(self, seats):
        self._seats = seats
        self.refreshed = False

    def refresh(self):
        self.refreshed = True

    def is_session_alive(self):
        return True

    def read_available_seats(self):
        return self._seats


class ExpiredSessionDriver(FakeDriver):
    def is_session_alive(self):
        return False


def _cfg():
    return AppConfig(
        ntok=NtokConfig("u", "1", "2", "id", "pw"),
        telegram=TelegramConfig("t", "c"),
        targets=[Target(floor="1F", section="B", rows=[1], consecutive=2)],
        poll=PollConfig(30, 60),
    )


def test_run_once_notifies_new_group():
    sent = []
    seats = [
        Seat("1F", "B", 1, 7, True),
        Seat("1F", "B", 1, 8, True),
    ]
    driver = FakeDriver(seats)
    count = monitor.run_once(driver, _cfg(), SeatState(), notify=sent.append)
    assert count == 1
    assert driver.refreshed is True
    assert len(sent) == 1
    assert "7-8" in sent[0]


def test_run_once_no_available_does_not_notify():
    sent = []
    driver = FakeDriver([Seat("1F", "B", 1, 7, False)])
    count = monitor.run_once(driver, _cfg(), SeatState(), notify=sent.append)
    assert count == 0
    assert sent == []


def test_run_once_same_group_twice_notifies_once():
    sent = []
    seats = [Seat("1F", "B", 1, 7, True), Seat("1F", "B", 1, 8, True)]
    state = SeatState()
    cfg = _cfg()
    monitor.run_once(FakeDriver(seats), cfg, state, notify=sent.append)
    monitor.run_once(FakeDriver(seats), cfg, state, notify=sent.append)
    assert len(sent) == 1


def test_run_once_session_expired_raises_drivererror():
    driver = ExpiredSessionDriver([])
    with pytest.raises(DriverError):
        monitor.run_once(driver, _cfg(), SeatState(), notify=lambda _text: None)
