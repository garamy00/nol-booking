from config import Target
from seats import Seat, SeatGroup, find_available_groups


def _seat(row, number, available, floor="1F", section="B"):
    return Seat(floor=floor, section=section, row=row, number=number, available=available)


TARGET_2 = Target(floor="1F", section="B", rows=[1, 2], consecutive=2)


def test_finds_two_adjacent_available_seats():
    seats = [_seat(1, 7, True), _seat(1, 8, True), _seat(1, 9, False)]
    groups = find_available_groups(seats, [TARGET_2])
    assert len(groups) == 1
    assert groups[0].numbers == (7, 8)


def test_ignores_non_adjacent_available_seats():
    seats = [_seat(1, 7, True), _seat(1, 12, True)]
    groups = find_available_groups(seats, [TARGET_2])
    assert groups == []


def test_ignores_seats_outside_target_rows_and_section():
    seats = [
        _seat(3, 7, True),  # row 밖
        _seat(1, 7, True, section="A"),  # section 밖
        _seat(1, 8, True, section="A"),
    ]
    groups = find_available_groups(seats, [TARGET_2])
    assert groups == []


def test_maximal_run_returned_as_single_group():
    seats = [_seat(2, 3, True), _seat(2, 4, True), _seat(2, 5, True)]
    groups = find_available_groups(seats, [TARGET_2])
    assert len(groups) == 1
    assert groups[0].numbers == (3, 4, 5)


def test_consecutive_one_allows_singletons():
    target = Target(floor="1F", section="B", rows=[1], consecutive=1)
    seats = [_seat(1, 7, True), _seat(1, 20, True)]
    groups = find_available_groups(seats, [target])
    assert len(groups) == 2


def test_group_key_and_label():
    group = SeatGroup(floor="1F", section="B", row=1, numbers=(7, 8))
    assert group.key() == ("1F", "B", 1, 7, 8)
    assert "1F" in group.label() and "B" in group.label() and "7" in group.label()
