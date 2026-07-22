from nol_seats import NolSeatGroup
from state import SeatState


def _group(row, numbers):
    return NolSeatGroup(grade="R석", section="B", row=row, numbers=numbers)


def test_first_appearance_is_new():
    state = SeatState()
    groups = [_group(1, (7, 8))]
    assert state.new_groups(groups) == groups


def test_same_group_next_round_is_not_new():
    state = SeatState()
    state.new_groups([_group(1, (7, 8))])
    assert state.new_groups([_group(1, (7, 8))]) == []


def test_disappeared_then_reappeared_group_is_new_again():
    state = SeatState()
    state.new_groups([_group(1, (7, 8))])
    state.new_groups([])  # 사라짐
    assert state.new_groups([_group(1, (7, 8))]) == [_group(1, (7, 8))]


def test_only_new_group_reported_when_mixed():
    state = SeatState()
    state.new_groups([_group(1, (7, 8))])
    result = state.new_groups([_group(1, (7, 8)), _group(2, (3, 4))])
    assert result == [_group(2, (3, 4))]
