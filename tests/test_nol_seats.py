from config import NolTarget
from nol_seats import NolSeat, NolSeatGroup, find_nol_groups, parse_rowno, parse_seat_meta


def _seat(section, row, number, grade, seat_id="s"):
    return NolSeat(section=section, row=row, number=number, grade=grade, seat_id=seat_id)


# parse_rowno


def test_parse_rowno_section_with_space_parses_section_and_row():
    assert parse_rowno("A구역 15열") == ("A", 15)


def test_parse_rowno_tolerates_missing_space():
    assert parse_rowno("A구역15열") == ("A", 15)


def test_parse_rowno_without_guyeok_suffix_uses_prefix_as_section():
    assert parse_rowno("BOX1 3열") == ("BOX1", 3)


def test_parse_rowno_unparseable_returns_none():
    assert parse_rowno("A구역") is None


def test_parse_rowno_no_digits_returns_none():
    assert parse_rowno("그냥텍스트") is None


# parse_seat_meta


def test_parse_seat_meta_valid_raw_returns_nolseat():
    raw = {
        "id": "seat_block_26005135:22000526:023:118",
        "floor": "1층",
        "rowNo": "A구역 15열",
        "seatNo": "5",
        "grade": "VIP석",
    }
    seat = parse_seat_meta(raw)
    assert seat == NolSeat(
        section="A", row=15, number=5, grade="VIP석", floor="1층", seat_id=raw["id"]
    )


def test_parse_seat_meta_unparseable_rowno_returns_none():
    raw = {"id": "x", "floor": "1층", "rowNo": "이상한값", "seatNo": "5", "grade": "R석"}
    assert parse_seat_meta(raw) is None


def test_parse_seat_meta_non_integer_seatno_returns_none():
    raw = {
        "id": "x",
        "floor": "1층",
        "rowNo": "A구역 15열",
        "seatNo": "오",
        "grade": "R석",
    }
    assert parse_seat_meta(raw) is None


def test_parse_seat_meta_missing_floor_defaults_to_first_floor():
    raw = {"id": "x", "rowNo": "A구역 15열", "seatNo": "5", "grade": "R석"}
    assert parse_seat_meta(raw).floor == "1층"


# find_nol_groups


def test_two_consecutive_same_row_seats_form_group_of_two():
    seats = [_seat("A", 15, 5, "R석"), _seat("A", 15, 6, "R석")]
    target = NolTarget(grade="R석", consecutive=2)
    groups = find_nol_groups(seats, [target])
    assert len(groups) == 1
    assert groups[0].numbers == (5, 6)
    assert groups[0].section == "A"
    assert groups[0].row == 15


def test_gap_in_numbers_splits_run():
    seats = [
        _seat("A", 15, 1, "R석", seat_id="s1"),  # 통로 건너
        _seat("A", 15, 5, "R석", seat_id="s2"),
        _seat("A", 15, 6, "R석", seat_id="s3"),
    ]
    target = NolTarget(grade="R석", consecutive=2)
    groups = find_nol_groups(seats, [target])
    assert len(groups) == 1
    assert groups[0].numbers == (5, 6)


def test_grade_filter_excludes_other_grade_seats():
    seats = [_seat("A", 15, 5, "R석"), _seat("A", 15, 6, "S석")]
    target = NolTarget(grade="R석", consecutive=2)
    groups = find_nol_groups(seats, [target])
    assert groups == []


def test_section_filter_excludes_other_section_seats():
    seats = [_seat("A", 15, 5, "R석"), _seat("B", 15, 6, "R석")]
    target = NolTarget(section="A", consecutive=1)
    groups = find_nol_groups(seats, [target])
    assert len(groups) == 1
    assert groups[0].section == "A"


def test_rows_filter_restricts_to_listed_rows():
    seats = [_seat("A", 15, 5, "R석"), _seat("A", 16, 5, "R석"), _seat("A", 17, 5, "R석")]
    target = NolTarget(rows=[15, 16], consecutive=1)
    groups = find_nol_groups(seats, [target])
    rows = sorted(g.row for g in groups)
    assert rows == [15, 16]


def test_different_row_seats_do_not_form_group():
    seats = [_seat("A", 15, 5, "R석"), _seat("A", 16, 6, "R석")]
    target = NolTarget(grade="R석", consecutive=2)
    groups = find_nol_groups(seats, [target])
    assert groups == []


def test_different_section_same_row_number_do_not_form_group():
    seats = [_seat("A", 15, 5, "R석"), _seat("B", 15, 6, "R석")]
    target = NolTarget(grade="R석", consecutive=2)
    groups = find_nol_groups(seats, [target])
    assert groups == []


def test_run_of_three_returned_as_one_group():
    seats = [_seat("A", 15, 5, "R석"), _seat("A", 15, 6, "R석"), _seat("A", 15, 7, "R석")]
    target = NolTarget(grade="R석", consecutive=2)
    groups = find_nol_groups(seats, [target])
    assert len(groups) == 1
    assert groups[0].numbers == (5, 6, 7)


def test_consecutive_threshold_excludes_short_runs():
    seats = [_seat("A", 15, 5, "R석"), _seat("A", 15, 6, "R석")]
    target = NolTarget(grade="R석", consecutive=3)
    groups = find_nol_groups(seats, [target])
    assert groups == []


def test_no_grade_filter_splits_run_by_grade_even_if_numbers_consecutive():
    seats = [_seat("A", 15, 5, "VIP석"), _seat("A", 15, 6, "R석")]
    target = NolTarget(consecutive=1)
    groups = find_nol_groups(seats, [target])
    assert len(groups) == 2
    assert {g.grade for g in groups} == {"VIP석", "R석"}


def test_group_key_and_label():
    group = NolSeatGroup(grade="R석", section="A", row=12, numbers=(5, 6))
    assert group.key() == ("R석", "A", 12, 5, 6)
    label = group.label()
    assert "R석" in label
    assert "A구역" in label
    assert "12열" in label
    assert "5-6번" in label
    assert "2연석" in label
