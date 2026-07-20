from config import NolTarget, Region
from nol_seats import NolSeat, NolSeatGroup, find_nol_groups, grade_from_fill


def _seat(seat_id, grade, cx, cy):
    return NolSeat(seat_id=seat_id, grade=grade, cx=cx, cy=cy)


def test_grade_from_fill_hex_lowercase_r_grade():
    assert grade_from_fill("#17b3ff") == "R석"


def test_grade_from_fill_rgb_form_r_grade():
    assert grade_from_fill("rgb(23, 179, 255)") == "R석"


def test_grade_from_fill_grey_returns_none():
    assert grade_from_fill("#edeff3") is None


def test_grade_from_fill_unknown_returns_none():
    assert grade_from_fill("#000000") is None


def test_grade_from_fill_uppercase_vip_grade():
    assert grade_from_fill("#7C68EE") == "VIP석"


def test_two_adjacent_same_row_seats_form_group_of_two():
    seats = [
        _seat("s1", "R석", 131.291, 61.763),
        _seat("s2", "R석", 134.291, 61.763),
    ]
    target = NolTarget(grade="R석", consecutive=2)
    groups = find_nol_groups(seats, [target])
    assert len(groups) == 1
    assert len(groups[0].seats) == 2


def test_aisle_gap_excludes_far_seat_from_run():
    seats = [
        _seat("s1", "R석", 101.291, 61.763),  # 통로 건너 (gap 30)
        _seat("s2", "R석", 131.291, 61.763),
        _seat("s3", "R석", 134.291, 61.763),
    ]
    target = NolTarget(grade="R석", consecutive=2)
    groups = find_nol_groups(seats, [target])
    assert len(groups) == 1
    seat_ids = sorted(s.seat_id for s in groups[0].seats)
    assert seat_ids == ["s2", "s3"]


def test_other_grade_seats_excluded_by_grade_filter():
    seats = [
        _seat("s1", "R석", 131.291, 61.763),
        _seat("s2", "S석", 134.291, 61.763),
    ]
    target = NolTarget(grade="R석", consecutive=2)
    groups = find_nol_groups(seats, [target])
    assert groups == []


def test_region_cx_max_excludes_out_of_range_seats():
    seats = [
        _seat("s1", "R석", 131.291, 61.763),
        _seat("s2", "R석", 200.0, 61.763),
    ]
    target = NolTarget(grade="R석", consecutive=1, region=Region(cx_max=140))
    groups = find_nol_groups(seats, [target])
    seat_ids = sorted(s.seat_id for g in groups for s in g.seats)
    assert seat_ids == ["s1"]


def test_different_rows_do_not_form_group():
    seats = [
        _seat("s1", "R석", 131.291, 61.763),
        _seat("s2", "R석", 132.291, 200.0),
    ]
    target = NolTarget(grade="R석", consecutive=2)
    groups = find_nol_groups(seats, [target])
    assert groups == []


def test_run_of_three_adjacent_returned_as_one_group():
    seats = [
        _seat("s1", "R석", 131.291, 61.763),
        _seat("s2", "R석", 134.291, 61.763),
        _seat("s3", "R석", 137.291, 61.763),
    ]
    target = NolTarget(grade="R석", consecutive=2)
    groups = find_nol_groups(seats, [target])
    assert len(groups) == 1
    assert len(groups[0].seats) == 3


def test_group_key_and_label():
    seats = (
        _seat("s1", "R석", 131.291, 61.763),
        _seat("s2", "R석", 134.291, 61.763),
    )
    group = NolSeatGroup(grade="R석", seats=seats)
    assert group.key() == ("R석", "s1", "s2")
    label = group.label()
    assert "R석" in label
    assert "2" in label
