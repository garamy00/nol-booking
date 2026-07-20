"""좌석 모델과 연석(인접 좌석) 매칭 로직."""

from dataclasses import dataclass

from config import Target


@dataclass(frozen=True)
class Seat:
    floor: str
    section: str
    row: int
    number: int
    available: bool


@dataclass(frozen=True)
class SeatGroup:
    floor: str
    section: str
    row: int
    numbers: tuple[int, ...]

    def key(self) -> tuple:
        """dedupe용 고유 키."""
        return (self.floor, self.section, self.row, self.numbers[0], self.numbers[-1])

    def label(self) -> str:
        """알림용 사람이 읽는 문자열."""
        span = "%d-%d" % (self.numbers[0], self.numbers[-1])
        return "%s %s열 %d행 %s번 (%d연석)" % (
            self.floor,
            self.section,
            self.row,
            span,
            len(self.numbers),
        )


def _runs(numbers: list[int]) -> list[tuple[int, ...]]:
    """정렬된 좌석번호에서 연속 구간(run)들을 뽑는다."""
    if not numbers:
        return []

    runs: list[tuple[int, ...]] = []
    current = [numbers[0]]
    for value in numbers[1:]:
        if value == current[-1] + 1:
            current.append(value)
        else:
            runs.append(tuple(current))
            current = [value]
    runs.append(tuple(current))
    return runs


def find_available_groups(seats: list[Seat], targets: list[Target]) -> list[SeatGroup]:
    """타깃 조건을 만족하는 가용 연석 묶음을 찾는다.

    각 타깃의 (floor, section, rows) 안에서 available 좌석을 열별로 모아
    좌석번호가 연속으로 `consecutive`개 이상 이어지는 최대 구간을 반환한다.
    """
    groups: list[SeatGroup] = []

    for target in targets:
        # 타깃 조건에 맞는 가용 좌석을 열별로 수집
        by_row: dict[int, list[int]] = {}
        for seat in seats:
            matches = (
                seat.available
                and seat.floor == target.floor
                and seat.section == target.section
                and seat.row in target.rows
            )
            if matches:
                by_row.setdefault(seat.row, []).append(seat.number)

        # 열마다 연속 구간을 찾아 consecutive 이상만 채택
        for row, numbers in by_row.items():
            for run in _runs(sorted(numbers)):
                if len(run) >= target.consecutive:
                    groups.append(
                        SeatGroup(
                            floor=target.floor,
                            section=target.section,
                            row=row,
                            numbers=run,
                        )
                    )

    return groups
