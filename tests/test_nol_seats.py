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


def test_large_gap_in_only_row_is_not_grouped():
    # 표본이 1개뿐이라 전역 임계값 추정이 불가 -> DEFAULT_ADJ(6.0) 폴백.
    # gap=100은 어떤 폴백값보다도 훨씬 커서 통로로 판정되어야 한다.
    seats = [
        _seat("s1", "R석", 100.0, 61.763),
        _seat("s2", "R석", 200.0, 61.763),
    ]
    target = NolTarget(grade="R석", consecutive=2)
    groups = find_nol_groups(seats, [target])
    assert groups == []


def test_global_pitch_ignores_far_pair_in_different_row():
    # 한 행에는 촘촘한 좌석(피치=3)들이 있어 전역 중앙값을 형성하고,
    # 다른 행에는 간격이 큰(gap=100) 좌석 쌍이 있다. 전역 피치 기준으로
    # 촘촘한 좌석들만 묶이고 먼 좌석 쌍은 묶이지 않아야 한다.
    close_seats = [
        _seat("c1", "R석", 100.0, 61.763),
        _seat("c2", "R석", 103.0, 61.763),
        _seat("c3", "R석", 106.0, 61.763),
        _seat("c4", "R석", 109.0, 61.763),
    ]
    far_seats = [
        _seat("f1", "R석", 300.0, 200.0),
        _seat("f2", "R석", 400.0, 200.0),
    ]
    target = NolTarget(grade="R석", consecutive=2)
    groups = find_nol_groups(close_seats + far_seats, [target])
    assert len(groups) == 1
    grouped_ids = {seat.seat_id for seat in groups[0].seats}
    assert grouped_ids == {"c1", "c2", "c3", "c4"}


def test_row_clustering_does_not_chain_drift_past_cy_tol():
    # cy가 0,2,4,6,8,10으로 CY_TOL(2.0)씩 증가한다. 마지막으로 추가된
    # 좌석과만 비교하면 전부 하나의 행으로 이어져 버린다(체인 드리프트).
    # 행의 기준(첫 좌석) cy와 비교해야 각 행의 cy 폭이 CY_TOL 이내로
    # 제한되어 3개 행(각 2석)으로 분리된다.
    seats = [
        _seat("s0", "R석", 100.0, 0.0),
        _seat("s1", "R석", 103.0, 2.0),
        _seat("s2", "R석", 106.0, 4.0),
        _seat("s3", "R석", 109.0, 6.0),
        _seat("s4", "R석", 112.0, 8.0),
        _seat("s5", "R석", 115.0, 10.0),
    ]
    target = NolTarget(grade="R석", consecutive=2)
    groups = find_nol_groups(seats, [target])
    assert len(groups) == 3
    for group in groups:
        assert len(group.seats) == 2


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
