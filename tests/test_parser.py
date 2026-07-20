from booking_driver import parse_seat_title
from seats import Seat


def test_parse_op_seat():
    seat = parse_seat_title("[OP석] 1층 OP구역 1열 01번")
    assert seat == Seat("1F", "OP", 1, 1, True)


def test_parse_vip_seat_zero_padded():
    seat = parse_seat_title("[VIP석] 1층 C구역 01열 05번")
    assert seat == Seat("1F", "C", 1, 5, True)


def test_parse_second_floor_b():
    seat = parse_seat_title("[휠체어석] 2층 B구역 20열 03번")
    assert seat == Seat("2F", "B", 20, 3, True)


def test_parse_invalid_returns_none():
    assert parse_seat_title("garbage") is None


def test_parse_empty_returns_none():
    assert parse_seat_title("") is None
