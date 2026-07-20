"""NOL 좌석(SVG circle) 모델과 좌표 기반 연석 매칭 로직.

NOL 좌석맵은 구역/열/번호 라벨이 없는 SVG다. 등급은 fill 색상으로,
좌석 위치는 (cx, cy) 좌표로만 식별된다. 매칭은 등급 필터 + 좌표 영역
필터 + 같은 행(cy) 내 인접(cx) 연석 탐색으로 이루어진다.
"""

from __future__ import annotations

import logging
import re
import statistics
from dataclasses import dataclass

from config import NolTarget, Region

logger = logging.getLogger(__name__)

# 행(같은 cy) 판별 허용 오차
CY_TOL = 2.0

# 인접 판별용 기본 임계값 (좌석 피치를 추정할 표본이 부족할 때의 폴백)
DEFAULT_ADJ = 6.0

# 좌석 피치 추정에 필요한 최소 간격 표본 수 (미만이면 DEFAULT_ADJ로 폴백)
MIN_GAP_SAMPLES = 3

# 등급별 fill 색상 (소문자 #rrggbb 정규화 기준)
GRADE_COLORS: dict[str, str] = {
    "#7c68ee": "VIP석",
    "#1ca814": "OP석",
    "#17b3ff": "R석",
    "#fb7e4e": "S석",
    "#a0d53f": "A석",
}

_RGB_RE = re.compile(r"rgb\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)", re.IGNORECASE)


def _normalize_fill(fill: str) -> str | None:
    """`#RRGGBB` 또는 `rgb(r, g, b)` 형태를 소문자 `#rrggbb`로 정규화한다."""
    fill = fill.strip()
    if fill.startswith("#"):
        return fill.lower()

    match = _RGB_RE.match(fill)
    if match is None:
        return None
    r, g, b = (int(part) for part in match.groups())
    return "#%02x%02x%02x" % (r, g, b)


def grade_from_fill(fill: str) -> str | None:
    """circle의 fill 색상에서 좌석 등급명을 찾는다.

    Args:
        fill: `#RRGGBB`(대소문자 무관) 또는 `rgb(r, g, b)` 형식의 색상값.

    Returns:
        등급명(예 "R석"). 매진(회색)·미지의 색상이면 None.
    """
    normalized = _normalize_fill(fill)
    if normalized is None:
        logger.warning("unrecognized fill format: %s", fill)
        return None
    return GRADE_COLORS.get(normalized)


@dataclass(frozen=True)
class NolSeat:
    seat_id: str
    grade: str
    cx: float
    cy: float


@dataclass(frozen=True)
class NolSeatGroup:
    grade: str
    seats: tuple[NolSeat, ...]

    def key(self) -> tuple:
        """dedupe용 고유 키."""
        return (self.grade, self.seats[0].seat_id, self.seats[-1].seat_id)

    def label(self) -> str:
        """알림용 사람이 읽는 문자열."""
        cx_range = "%.1f-%.1f" % (self.seats[0].cx, self.seats[-1].cx)
        return "%s %d연석 (cx %s, cy %.1f)" % (
            self.grade,
            len(self.seats),
            cx_range,
            self.seats[0].cy,
        )


def _seat_in_region(seat: NolSeat, region: Region | None) -> bool:
    """좌석이 region 안에 있는지 확인한다. region이 None이면 항상 True."""
    if region is None:
        return True
    if region.cx_min is not None and seat.cx < region.cx_min:
        return False
    if region.cx_max is not None and seat.cx > region.cx_max:
        return False
    if region.cy_min is not None and seat.cy < region.cy_min:
        return False
    if region.cy_max is not None and seat.cy > region.cy_max:
        return False
    return True


def _group_by_row(seats: list[NolSeat]) -> list[list[NolSeat]]:
    """cy 기준으로 정렬 후 행 기준(첫 좌석) cy와 CY_TOL 이내인 좌석을 같은 행으로 묶는다.

    WHY: 직전 좌석과만 비교하면 작은 step이 누적돼 한 행의 cy 폭이
    CY_TOL을 훨씬 초과할 수 있다(체인 드리프트). cy로 정렬되어 있으므로
    행의 첫 좌석(기준)과 비교하면 행의 cy 폭이 항상 CY_TOL 이내로 제한된다.
    """
    ordered = sorted(seats, key=lambda seat: seat.cy)
    rows: list[list[NolSeat]] = []
    for seat in ordered:
        if rows and seat.cy - rows[-1][0].cy <= CY_TOL:
            rows[-1].append(seat)
        else:
            rows.append([seat])
    return rows


def _row_gaps(row: list[NolSeat]) -> list[float]:
    """행 내 cx 정렬 후 연속 좌석 간 양수 간격 목록을 반환한다.

    NOTE: 이 프로젝트의 실행 인터프리터가 3.9라 itertools.pairwise(3.10+)를
    쓸 수 없어 인덱스 기반으로 구현한다.
    """
    ordered = sorted(row, key=lambda seat: seat.cx)
    return [
        ordered[i + 1].cx - ordered[i].cx
        for i in range(len(ordered) - 1)
        if ordered[i + 1].cx - ordered[i].cx > 0
    ]


def _seat_pitch_threshold(rows: list[list[NolSeat]]) -> float:
    """타깃(등급+영역 필터 결과) 전체 행에서 좌석 피치를 추정해 인접 임계값을 계산한다.

    WHY: 좌석 간격은 좌석맵 전체에서 거의 일정하고 통로 간격만 크다.
    행 하나만 보면 좌석이 2개뿐일 때 간격이 통로여도 "중앙값"이 그
    간격 자체가 되어버려 통로를 인접으로 오판한다(임계값 degenerate).
    타깃 전체 행의 간격을 모아 중앙값을 구하면 좌석 피치의 안정적인
    추정치가 되어 이 문제를 피한다. 표본이 부족(3개 미만)하면 스케일을
    신뢰할 수 없으므로 절대 기본값(DEFAULT_ADJ)으로 대체한다.
    """
    all_gaps = [gap for row in rows for gap in _row_gaps(row)]
    if len(all_gaps) < MIN_GAP_SAMPLES:
        return DEFAULT_ADJ
    return 1.5 * statistics.median(all_gaps)


def _runs_in_row(row: list[NolSeat], threshold: float) -> list[tuple[NolSeat, ...]]:
    """행 내에서 cx 기준 정렬 후 인접 임계 이하로 이어지는 연속 구간을 뽑는다."""
    if not row:
        return []

    ordered = sorted(row, key=lambda seat: seat.cx)
    runs: list[tuple[NolSeat, ...]] = []
    current = [ordered[0]]
    for seat in ordered[1:]:
        if seat.cx - current[-1].cx <= threshold:
            current.append(seat)
        else:
            runs.append(tuple(current))
            current = [seat]
    runs.append(tuple(current))
    return runs


def find_nol_groups(
    seats: list[NolSeat], targets: list[NolTarget]
) -> list[NolSeatGroup]:
    """타깃 조건을 만족하는 가용 연석 묶음을 찾는다.

    각 타깃의 등급으로 좌석을 필터링하고, region이 있으면 좌표 영역으로
    한 번 더 제한한 뒤, 같은 행(cy)에서 인접(cx)한 좌석이 `consecutive`개
    이상 이어지는 최대 구간을 반환한다.
    """
    groups: list[NolSeatGroup] = []

    for target in targets:
        # 등급 + 좌표 영역으로 대상 좌석 필터링
        filtered = [
            seat
            for seat in seats
            if seat.grade == target.grade and _seat_in_region(seat, target.region)
        ]

        # 행별로 묶고, 타깃 전체 행에서 좌석 피치를 추정해 단일 임계값을 구한 뒤
        # 행마다 인접 연속 구간을 찾아 consecutive 이상만 채택
        rows = _group_by_row(filtered)
        threshold = _seat_pitch_threshold(rows)
        for row in rows:
            for run in _runs_in_row(row, threshold):
                if len(run) >= target.consecutive:
                    groups.append(NolSeatGroup(grade=target.grade, seats=run))

    return groups
