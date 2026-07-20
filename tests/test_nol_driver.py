import pytest

from config import NolAppConfig, NolConfig, NolTarget, PollConfig, TelegramConfig
from nol_driver import parse_remaining, to_ampm
from nol_monitor import check_once
from nol_seats import NolSeat
from state import SeatState


# to_ampm


@pytest.mark.parametrize(
    "hhmm, expected",
    [
        ("14:00", "2:00 PM"),
        ("09:30", "9:30 AM"),
        ("00:00", "12:00 AM"),
        ("12:00", "12:00 PM"),
        ("15:00", "3:00 PM"),
        ("19:30", "7:30 PM"),
    ],
)
def test_to_ampm_converts_24h_to_12h_with_period(hhmm, expected):
    assert to_ampm(hhmm) == expected


# parse_remaining


def test_parse_remaining_plain_colon_returns_total_seconds():
    assert parse_remaining("좌석 선택 시간 5:35") == 335


def test_parse_remaining_spaced_colon_returns_total_seconds():
    assert parse_remaining("좌석 선택 시간 5 : 35") == 335


def test_parse_remaining_missing_pattern_returns_none():
    assert parse_remaining("2026.08.02(일) 2:00 PM VIP석 73") is None


# check_once (nol_monitor)


class FakeDriver:
    def __init__(self, seats):
        self._seats = seats

    def read_available_seats(self):
        return self._seats


def _cfg(consecutive=2):
    return NolAppConfig(
        nol=NolConfig(
            url="https://tickets.interpark.com/goods",
            goods_id="26005135",
            date="20260802",
            time="14:00",
            toggle_date="20260805",
            toggle_time="15:00",
        ),
        telegram=TelegramConfig("t", "c"),
        targets=[NolTarget(grade="R석", consecutive=consecutive)],
        poll=PollConfig(30, 60),
    )


def test_check_once_notifies_new_consecutive_group():
    sent = []
    seats = [
        NolSeat(section="A", row=15, number=5, grade="R석", seat_id="s1"),
        NolSeat(section="A", row=15, number=6, grade="R석", seat_id="s2"),
    ]
    driver = FakeDriver(seats)
    fresh = check_once(driver, _cfg(), SeatState(), notify=sent.append)
    assert len(fresh) == 1
    assert len(sent) == 1
    assert "R석" in sent[0]


def test_check_once_no_seats_returns_empty_and_no_notify():
    sent = []
    fresh = check_once(FakeDriver([]), _cfg(), SeatState(), notify=sent.append)
    assert fresh == []
    assert sent == []


def test_check_once_same_group_twice_notifies_once():
    sent = []
    seats = [
        NolSeat(section="A", row=15, number=5, grade="R석", seat_id="s1"),
        NolSeat(section="A", row=15, number=6, grade="R석", seat_id="s2"),
    ]
    state = SeatState()
    cfg = _cfg()
    check_once(FakeDriver(seats), cfg, state, notify=sent.append)
    check_once(FakeDriver(seats), cfg, state, notify=sent.append)
    assert len(sent) == 1
