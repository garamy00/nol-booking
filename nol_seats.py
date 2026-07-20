"""NOL 좌석(React fiber 라벨) 모델과 라벨 기반 연석 매칭 로직.

NOL 좌석맵은 SVG 좌표만으로는 구역/열/번호를 알 수 없다. 대신 각 가용
좌석 circle의 React fiber(memoizedProps.seat)에 등급·구역열·좌석번호가
그대로 들어 있다. 이 모듈은 그 fiber 원시 데이터를 파싱해 NolSeat로
만들고, 등급/구역/열 조건(설정된 것만)으로 필터링한 뒤 같은 (구역, 열)
안에서 좌석번호가 연속인 구간을 찾아 연석 묶음(NolSeatGroup)을 만든다.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from config import NolTarget

logger = logging.getLogger(__name__)

# "A구역 15열" / "A구역15열" 등에서 뒤쪽 "<n>열"과 그 앞부분(구역)을 분리한다
_ROWNO_RE = re.compile(r"^(?P<prefix>.*?)\s*(?P<row>\d+)\s*열$")


def parse_rowno(row_no: str) -> tuple[str, int] | None:
    """rowNo 문자열을 (구역, 열) 튜플로 파싱한다.

    "A구역 15열" -> ("A", 15). "구역" 접미가 없는 형태(박스석 등)는
    "<n>열" 앞부분 전체를 구역명으로 취급한다. "<n>열" 패턴이 없으면 None.
    """
    match = _ROWNO_RE.match(row_no.strip())
    if match is None:
        logger.warning("unparseable rowNo: %s", row_no)
        return None

    prefix = match.group("prefix").strip()
    row = int(match.group("row"))
    section = prefix[:-2].strip() if prefix.endswith("구역") else prefix
    return section, row


@dataclass(frozen=True)
class NolSeat:
    section: str
    row: int
    number: int
    grade: str
    floor: str = "1층"
    seat_id: str = ""


def parse_seat_meta(raw: dict) -> NolSeat | None:
    """React fiber에서 읽은 원시 좌석 dict(id/floor/rowNo/seatNo/grade)를
    NolSeat로 변환한다.

    rowNo를 파싱할 수 없거나 seatNo가 정수가 아니면 None을 반환한다.
    """
    parsed = parse_rowno(raw.get("rowNo", ""))
    if parsed is None:
        return None
    section, row = parsed

    try:
        number = int(raw["seatNo"])
    except (KeyError, TypeError, ValueError):
        logger.warning("unparseable seatNo: %s", raw.get("seatNo"))
        return None

    return NolSeat(
        section=section,
        row=row,
        number=number,
        grade=raw["grade"],
        floor=raw.get("floor", "1층"),
        seat_id=raw.get("id", ""),
    )


@dataclass(frozen=True)
class NolSeatGroup:
    grade: str
    section: str
    row: int
    numbers: tuple[int, ...]

    def key(self) -> tuple:
        """dedupe용 고유 키."""
        return (self.grade, self.section, self.row, self.numbers[0], self.numbers[-1])

    def label(self) -> str:
        """알림용 사람이 읽는 문자열."""
        span = "%d-%d" % (self.numbers[0], self.numbers[-1])
        return "%s %s구역 %d열 %s번 (%d연석)" % (
            self.grade,
            self.section,
            self.row,
            span,
            len(self.numbers),
        )


def _seat_matches_target(seat: NolSeat, target: NolTarget) -> bool:
    """좌석이 타깃의 등급/구역/열 조건(설정된 것만)을 만족하는지 확인한다."""
    if target.grade is not None and seat.grade != target.grade:
        return False
    if target.section is not None and seat.section != target.section:
        return False
    if target.rows is not None and seat.row not in target.rows:
        return False
    return True


def _seat_runs(seats: list[NolSeat]) -> list[list[NolSeat]]:
    """좌석번호 기준 정렬 후 연속 번호+동일 등급으로 이어지는 구간(run)들을 뽑는다.

    NOTE: 등급 필터가 없는 타깃에서는 같은 (구역, 열)에 등급이 다른 좌석이
    섞일 수 있다. run은 번호가 연속이면서 등급도 같아야 이어진다.
    """
    if not seats:
        return []

    ordered = sorted(seats, key=lambda seat: seat.number)
    runs: list[list[NolSeat]] = []
    current = [ordered[0]]
    for seat in ordered[1:]:
        same_run = (
            seat.number == current[-1].number + 1 and seat.grade == current[-1].grade
        )
        if same_run:
            current.append(seat)
        else:
            runs.append(current)
            current = [seat]
    runs.append(current)
    return runs


def find_nol_groups(
    seats: list[NolSeat], targets: list[NolTarget]
) -> list[NolSeatGroup]:
    """타깃 조건을 만족하는 가용 연석 묶음을 찾는다.

    각 타깃의 등급/구역/열(설정된 것만)로 좌석을 필터링하고, 같은
    (구역, 열) 안에서 좌석번호가 연속으로 `consecutive`개 이상 이어지는
    최대 구간을 반환한다.
    """
    groups: list[NolSeatGroup] = []

    for target in targets:
        filtered = [seat for seat in seats if _seat_matches_target(seat, target)]

        # (구역, 열)별로 묶고 각각에서 연속 구간을 찾아 consecutive 이상만 채택
        by_row: dict[tuple[str, int], list[NolSeat]] = {}
        for seat in filtered:
            by_row.setdefault((seat.section, seat.row), []).append(seat)

        for (section, row), row_seats in by_row.items():
            for run in _seat_runs(row_seats):
                if len(run) >= target.consecutive:
                    groups.append(
                        NolSeatGroup(
                            grade=run[0].grade,
                            section=section,
                            row=row,
                            numbers=tuple(seat.number for seat in run),
                        )
                    )

    return groups
